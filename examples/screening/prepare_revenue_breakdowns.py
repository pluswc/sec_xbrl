"""Project pinned, already prepared company revenue breakdowns for the local UI."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from sec_xbrl.analysis import open_analysis
from sec_xbrl.analytics.quarterly_derived_metrics import percentage_result
from sec_xbrl.analytics.statement_structure import finite_decimal
from sec_xbrl.longitudinal.materialization import (
    LAYER2_CONTRACT_VERSION,
    _run_from_manifest,
    _validate_operational_manifest_shape,
)
from sec_xbrl.screening.common import (
    real_directory,
    regular_file,
    require_cik,
    safe_new_destination,
)

SCHEMA_VERSION = "screening-revenue-breakdowns-v1"
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_COMPANY_BYTES = 512 * 1024
SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
PRODUCT_AXES = {"srt:ProductOrServiceAxis", "us-gaap:ProductOrServiceAxis"}
REVENUE_QNAMES = {
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
}
VIEW = "LATEST_REPORTED"
RATIO_RULE_VERSION = "same-filing-revenue-ratios-v1"
OBSERVATIONS = "reported_period_observation"


def _pinned_json(path: Path, digest: str) -> dict[str, Any]:
    data = regular_file(path, "revenue breakdown manifest").read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"revenue breakdown manifest differs from pin: {path}")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise TypeError("revenue breakdown manifest must be an object")
    return result


def _parent(declaration: dict, filename: str, cutoff: str) -> dict:
    root = real_directory(Path(declaration["root"]), "revenue breakdown source")
    manifest = _pinned_json(root / filename, declaration["manifest_sha256"])
    if manifest["publication_id"] != declaration["publication_id"] or manifest["financial_as_of"] != cutoff:
        raise ValueError("revenue breakdown parent scope differs")
    return manifest


def _company_declarations(manifest: dict) -> dict[str, dict]:
    declarations = {}
    for company in manifest["config"]["companies"]:
        cik = require_cik(company["cik"])
        if cik in declarations:
            raise ValueError("duplicate revenue breakdown company declaration")
        declarations[cik] = company
    return declarations


def prepare_revenue_breakdowns(
    *, dataset_manifest: Path, dataset_manifest_sha256: str, output: Path,
    ciks: list[str] | None = None,
) -> Path:
    """Build an optional read-only artifact from exact active dataset parents."""
    dataset = _pinned_json(dataset_manifest, dataset_manifest_sha256)
    if dataset.get("schema_version") != "screening-dataset-v3" or dataset.get("fixture_kind") != "ACTUAL_PREPARED":
        raise ValueError("revenue breakdowns require a prepared v3 screening dataset")
    cutoff = dataset["financial_as_of"]
    annual = _parent(dataset["parents"]["annual"], "screening_dataset_manifest.json", cutoff)
    quarter = _parent(dataset["parents"]["quarterly"], "quarterly_screening_metric_manifest.json", cutoff)
    metrics = _parent(annual["sources"]["metrics"], "screening_metric_manifest.json", cutoff)
    annual_by_cik = _company_declarations(metrics)
    quarter_by_cik = _company_declarations(quarter)
    membership = set(quarter["universe"]["ciks"])
    if not membership == set(annual_by_cik) == set(quarter_by_cik) == set(annual["configured_ciks"]):
        raise ValueError("revenue breakdown company membership differs")
    selected = [require_cik(cik) for cik in ciks] if ciks else sorted(membership)
    if len(set(selected)) != len(selected) or not set(selected) <= membership:
        raise ValueError("revenue breakdown selection is outside the prepared membership")
    destination = safe_new_destination(output, "revenue breakdown output")
    companies = {}
    for cik in selected:
        annual_config, quarter_config = annual_by_cik[cik], quarter_by_cik[cik]
        ticker = annual_config["ticker"]
        if ticker != quarter_config["ticker"]:
            raise ValueError("revenue breakdown company identity differs")
        company = {
            "ticker": ticker,
            "annual": _prepare_company(annual_config, cutoff, "FY", 4),
            "quarterly": _prepare_company(quarter_config, cutoff, "QTD_3M", 8),
        }
        if len(_json(company)) > MAX_COMPANY_BYTES:
            raise ValueError("revenue breakdown company exceeds response limit")
        companies[cik] = company
    payload = {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset["dataset_id"],
        "dataset_publication_id": dataset["publication_id"], "financial_as_of": cutoff,
        "dataset_manifest_sha256": dataset_manifest_sha256, "companies": companies,
    }
    data = _json(payload)
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("revenue breakdown asset exceeds size limit")
    with destination.open("xb") as stream:
        stream.write(data)
    return destination


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _prepare_company(declaration: dict, cutoff: str, period_class: str, limit: int) -> dict:
    root = real_directory(Path(declaration["analysis_root"]), "revenue breakdown analysis")
    digest = declaration["analysis_manifest_sha256"]
    manifest = _pinned_json(root / "analysis_manifest.json", digest)
    client = open_analysis(root)
    if client.manifest != manifest or (manifest.get("period_mode") == "ANNUAL") != (period_class == "FY"):
        raise ValueError("revenue breakdown analysis manifest scope differs")
    ticker, cik = declaration["ticker"], declaration["cik"]
    observations, evidence = _ratio_observations(manifest, ticker, cik, cutoff, period_class)
    result = project_breakdowns(client, ticker, cik, cutoff, period_class, limit, ratio_observations=observations)
    result["ratio_evidence"] = evidence
    return result | {"analysis_publication_id": manifest["publication_id"], "analysis_manifest_sha256": digest}


def project_breakdowns(
    client: Any, ticker: str, cik: str, cutoff: str, period_class: str, limit: int,
    *, ratio_observations: Iterable[dict] = (),
) -> dict:
    """Reuse exact prepared lenses, with an unlinked reported-node fallback."""
    overview = client.overview(ticker, view=VIEW, as_of=cutoff, recent_quarters=limit + 4)
    context = overview["context"]
    comparison_periods = _periods(overview, cutoff, period_class, limit + 4)
    periods = comparison_periods[-limit:]
    coordinates = {(p["fiscal_year"], p["fiscal_quarter"]): p for p in periods}
    series: dict[str, dict] = {}
    for lens in client.list_breakdowns("revenue", context=context)["groups"]:
        axes = set(lens.get("dimensions") or [])
        if lens.get("lens_type") != "DIMENSIONAL_VIEW" or not _supported_axes(axes):
            continue
        axis = client.axis_timeseries(ticker, lens["node_id"], context=context)
        if axis["period_class"] != period_class:
            continue
        for row in axis["rows"]:
            if row["row_kind"] != "MEMBER":
                continue
            node = row["prepared_node"]
            _project_row(series, node, row["cells"], coordinates, client, context, cik)
    prepared_nodes = client._records(ticker, VIEW, "nodes")
    lens_ids = {node["node_id"] for node in prepared_nodes if node.get("kind") == "LENS"}
    attached = {
        (edge["child_id"], tuple(period))
        for edge in client._records(ticker, VIEW, "edges")
        if edge.get("kind") == "OBSERVED_DIMENSION" and edge["parent_id"] in lens_ids
        for period in edge["periods"]
    }
    nodes = {node["node_id"]: node for node in prepared_nodes
             if node.get("kind") == "VALUE" and node.get("period_class") == period_class
             and node.get("origin_kind") == "STANDARD" and node.get("concept") in REVENUE_QNAMES
             and _axis_identity(node.get("dimensions"))}
    by_node = defaultdict(list)
    for cell in client._records(ticker, VIEW, "cells"):
        coordinate = _coordinate(cell)
        node_id = cell.get("node_id")
        if (node_id in nodes and coordinate in coordinates and (node_id, coordinate) not in attached
            and cell.get("status") == "REPORTED"):
            by_node[node_id].append(cell)
    for node_id, cells in by_node.items():
        _project_row(series, nodes[node_id], cells, coordinates, client, context, cik, fallback=True)
    _hold_conflicts(series)
    groups: dict[str, list] = {"segments": [], "products": []}
    for row in series.values():
        cells = [row["cells"].get(key, _gap("PERIOD_NOT_PREPARED")) for key in coordinates]
        if any(cell["value"] is not None or cell["reason"] == "COMPETING_PREPARED_SCOPE" for cell in cells):
            groups[row["group"]].append({**row, "cells": cells})
    totals = _consolidated_totals(overview, coordinates, client, context, cik, period_class)
    _add_revenue_ratios(totals, groups, periods, comparison_periods, ratio_observations)
    return {"periods": periods, "totals": totals, "groups": groups, "ratio_rule_version": RATIO_RULE_VERSION}


def _ratio_observations(manifest: dict, ticker: str, cik: str, cutoff: str, period_class: str) -> tuple[list[dict], dict]:
    company = manifest["companies"][ticker]
    pins = company.get("source_manifest_hashes") or manifest["source_manifest_hashes"]
    history_pin = pins["history_manifest_sha256"]
    history_root = real_directory(Path(company["source_publication"]), "revenue ratio history")
    history = _pinned_json(history_root / "history_manifest.json", history_pin)
    root = real_directory(Path(history["operational_roots"]["t1"]), "revenue ratio reported panel")
    manifest_path = regular_file(root / "layer2_run_manifest.json", "revenue ratio panel manifest")
    manifest_bytes = manifest_path.read_bytes()
    panel = json.loads(manifest_bytes)
    _validate_operational_manifest_shape(panel)
    run = _run_from_manifest(panel)
    if (
        panel["storage_format"] != "parquet-operational-v1" or run.contract_version != LAYER2_CONTRACT_VERSION
        or run.fingerprint != panel["run_fingerprint"] or run.fingerprint != history["input_fingerprint"]
        or run.run_version != root.name or OBSERVATIONS not in panel["output_counts"]
    ):
        raise ValueError("revenue ratio reported panel identity differs from history")
    inputs = {(row.snapshot_id, row.accession, row.filed_date, row.form)
              for row in run.inputs if row.cik == cik}
    if not inputs:
        raise ValueError("revenue ratio company is outside the reported panel")
    partition = real_directory(root / cik, "revenue ratio company partition")
    data = regular_file(partition / f"{OBSERVATIONS}.parquet", "revenue ratio observations").read_bytes()
    frame = pl.scan_parquet(data).filter(
        (pl.col("cik") == cik) & (pl.col("filed_date") <= cutoff)
        & (pl.col("period_class") == period_class)
        & pl.col("raw_concept_qname").is_in(sorted(REVENUE_QNAMES))
        & pl.col("comparative_type").is_in(["CURRENT_FOCUS", "PRIOR_YEAR_COMPARABLE"])
    ).collect()
    rows = frame.to_dicts()
    if any((row["source_snapshot_id"], row["accession"], row["filed_date"], row["form"]) not in inputs for row in rows):
        raise ValueError("revenue ratio observation lies outside the reported panel input snapshots")
    return rows, {
        "history_manifest_sha256": history_pin,
        "reported_panel_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "reported_observations_sha256": hashlib.sha256(data).hexdigest(),
    }


def _ratio_scope(row: dict) -> tuple | None:
    dims = row.get("raw_dimension_signature")
    if not isinstance(dims, list) or any(
        not isinstance(dim, list) or len(dim) != 5 or not dim[0] or not dim[1]
        or dim[2:] != [None, "EXPLICIT", "false"] for dim in dims
    ):
        return None
    if len({dim[0] for dim in dims}) != len(dims):
        return None
    if (
        row.get("reported_or_derived") != "REPORTED" or row.get("context_period_kind") != "DURATION"
        or row.get("raw_concept_is_standard") is not True or row.get("raw_concept_qname") not in REVENUE_QNAMES
        or not row.get("raw_concept_id") or not row.get("source_filing_id")
        or row.get("unit_numerator_measures") != '["iso4217:USD"]'
        or row.get("unit_denominator_measures") != "[]"
    ):
        return None
    return (row["source_snapshot_id"], row["source_filing_id"], row["accession"], row["filed_date"],
            row["raw_concept_id"], row["raw_concept_qname"], row["raw_concept_namespace_uri"],
            tuple(sorted(tuple(dim) for dim in dims)))


def _ratio_amount(rows: list[dict], days: int) -> tuple[Decimal, list[str]] | None:
    values = {finite_decimal(row.get("value_numeric")) for row in rows}
    if len(values) != 1 or None in values or any(
        row.get("is_nil") is not False or row.get("context_duration_days") != days
        or row.get("quality_blocking") or row.get("quality_status") == "BLOCK"
        or not row.get("source_fact_id") for row in rows
    ):
        return None
    value, = values
    return value, sorted({row["source_fact_id"] for row in rows})


def _same_fiscal_duration(start: str, end: str, prior_start: str, prior_end: str) -> tuple[int, int] | None:
    start_date, end_date, earlier_start, earlier_end = map(date.fromisoformat, (start, end, prior_start, prior_end))
    days, earlier_days = (end_date - start_date).days, (earlier_end - earlier_start).days
    if (
        not 358 <= (start_date - earlier_start).days <= 373
        or not 358 <= (end_date - earlier_end).days <= 373 or abs(days - earlier_days) > 7
    ):
        return None
    return days, earlier_days


def _add_revenue_ratios(
    totals: list[dict], groups: dict, periods: list[dict], comparison_periods: list[dict], observations: Iterable[dict],
) -> None:
    by_fact = defaultdict(list)
    by_scope = defaultdict(list)
    for row in observations:
        scope = _ratio_scope(row)
        if scope is None:
            continue
        by_fact[(row["source_snapshot_id"], row["source_fact_id"])].append((scope, row))
        by_scope[(scope, row["context_start_date"], row["context_end_date"], row["comparative_type"])].append(row)

    prior_periods = {_coordinate(period): period for period in comparison_periods}
    for index, period in enumerate(periods):
        start, end = period["period_start"], period["period_end"]
        if not start or not end:
            continue
        year, quarter = _coordinate(period)
        prior = prior_periods.get((year - 1, quarter), {})
        earlier_start, earlier_end = prior.get("period_start"), prior.get("period_end")
        duration = _same_fiscal_duration(start, end, earlier_start, earlier_end) if earlier_start and earlier_end else None
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        entries = [(row, row["cells"][index]) for rows in groups.values() for row in rows]
        segments = defaultdict(list)
        for row, cell in entries:
            if row["group"] == "segments" and (cell["value"] is not None or cell["reason"] == "COMPETING_PREPARED_SCOPE"):
                segments[row["member"]].append(cell)
        total = totals[index]
        bound = {}
        for row, cell in [(None, total), *entries]:
            current = _bind_ratio_cell(cell, by_fact, by_scope, start, end, days, len(row["axis_members"]) if row else 0)
            if current is not None:
                bound[cell["cell_id"]] = current
        for row, cell in [(None, total), *entries]:
            current = bound.get(cell.get("cell_id"))
            if current is None:
                continue
            scope, value = current
            fact = cell["sources"][0]["fact_id"]
            ratios = {}
            if row:
                subtotal = segments[row["scope"]] if row["scope"] else []
                parent = (subtotal[0] if len(subtotal) == 1 else {}) if row["scope"] else total
                denominator = bound.get(parent.get("cell_id"))
                if denominator is not None:
                    parent_scope, parent_value = denominator
                    if (
                        scope[:-1] == parent_scope[:-1] and 0 <= value <= parent_value and parent_value > 0
                        and set(parent_scope[-1]) < set(scope[-1])
                    ):
                        cell["share"] = str(percentage_result(value, parent_value, subtract_one=False))
                        ratios["share"] = {
                            "denominator": "SEGMENT_SUBTOTAL" if row["scope"] else "CONSOLIDATED",
                            "numerator_fact_id": fact, "denominator_fact_id": parent["sources"][0]["fact_id"],
                        }
            if duration and value >= 0:
                earlier = _ratio_amount(by_scope[(scope, earlier_start, earlier_end, "PRIOR_YEAR_COMPARABLE")], duration[1])
                if earlier is not None and earlier[0] > 0:
                    cell["yoy"] = str(percentage_result(value, earlier[0], subtract_one=True))
                    ratios["yoy"] = {
                        "current_fact_id": fact, "prior_fact_ids": earlier[1], "prior_value": str(earlier[0]),
                        "prior_fiscal_year": year - 1, "prior_fiscal_quarter": quarter,
                        "prior_period_start": earlier_start, "prior_period_end": earlier_end,
                    }
            if ratios:
                cell["ratios"] = ratios


def _bind_ratio_cell(
    cell: dict, by_fact: dict, by_scope: dict, start: str, end: str, days: int, dimension_count: int,
) -> tuple[tuple, Decimal] | None:
    if cell["status"] != "REPORTED" or len(cell["sources"]) != 1:
        return None
    source, = cell["sources"]
    records = by_fact[(source["snapshot_id"], source["fact_id"])]
    if len(records) != 1:
        return None
    scope, row = records[0]
    if (
        (row["accession"], row["filed_date"], row["raw_concept_qname"])
        != (source["accession"], source["filed_date"], source["qname"])
        or (row["context_start_date"], row["context_end_date"], row["comparative_type"])
        != (start, end, "CURRENT_FOCUS")
        or len(scope[-1]) != dimension_count
    ):
        return None
    amounts = _ratio_amount(by_scope[(scope, start, end, "CURRENT_FOCUS")], days)
    if amounts is None or amounts[0] != finite_decimal(cell["value"]):
        return None
    return scope, amounts[0]


def _consolidated_totals(
    overview: dict, coordinates: dict, client: Any, context: dict, cik: str, period_class: str,
) -> list[dict]:
    by_period = defaultdict(list)
    for cell in overview["cells"]:
        if cell.get("row_id") == "revenue" and cell.get("period_class") == period_class:
            by_period[_coordinate(cell)].append(cell)
    totals = []
    for key, period in coordinates.items():
        candidates = by_period[key]
        if len(candidates) > 1:
            totals.append(_gap("COMPETING_PREPARED_SCOPE"))
            continue
        if not candidates or candidates[0].get("status") not in {"REPORTED", "DERIVED"}:
            totals.append(_gap("PERIOD_NOT_PREPARED"))
            continue
        cell = candidates[0]
        if cell.get("dimensions") != []:
            totals.append(_gap("PREPARED_OBSERVATION_HELD"))
            continue
        trace = client.trace(cell["cell_id"], context=context)["trace"]
        totals.append(_prepared_cell(cell, trace, period, context, cik))
    return totals


def _coordinate(row: dict) -> tuple[int, int]:
    return row["fiscal_year"], row["fiscal_quarter"]


def _periods(overview: dict, cutoff: str, period_class: str, limit: int) -> list[dict]:
    by_coordinate = defaultdict(list)
    for column in overview["columns"]:
        if column["period_class"] == period_class:
            by_coordinate[_coordinate(column)].append(column)
    end_limit = date.fromisoformat(cutoff) + timedelta(days=1)
    periods = []
    last_completed = 0
    for coordinate in sorted(by_coordinate):
        columns = by_coordinate[coordinate]
        start = columns[0].get("actual_start_date") if len(columns) == 1 else None
        end = columns[0].get("actual_end_date") if len(columns) == 1 else None
        valid = bool(start and end and date.fromisoformat(start) < date.fromisoformat(end) <= end_limit)
        periods.append({
            "fiscal_year": coordinate[0], "fiscal_quarter": coordinate[1],
            "period_start": start if valid else None, "period_end": end if valid else None,
        })
        if valid:
            last_completed = len(periods)
    return periods[max(0, last_completed - limit):last_completed]


def _supported_axes(axes: set[str]) -> bool:
    return axes == {SEGMENT_AXIS} or (
        len(axes & PRODUCT_AXES) == 1 and axes <= PRODUCT_AXES | {SEGMENT_AXIS}
    )


def _axis_identity(dimensions: Any) -> dict[str, str] | None:
    if not dimensions or any(
        not isinstance(row, list) or len(row) != 5 or not row[0] or not row[1]
        or row[2] is not None or row[3:] != ["EXPLICIT", "false"]
        for row in dimensions
    ):
        return None
    axes = {row[0]: row[1] for row in dimensions}
    return axes if len(axes) == len(dimensions) and _supported_axes(set(axes)) else None


def _project_row(
    series: dict, node: dict, cells: list[dict],
    coordinates: dict, client: Any, context: dict, cik: str, *, fallback: bool = False,
) -> None:
    axes = _axis_identity(node.get("dimensions"))
    if not axes or node.get("concept") not in REVENUE_QNAMES:
        return
    group = "segments" if set(axes) == {SEGMENT_AXIS} else "products"
    row = series.setdefault(node["node_id"], {
        "id": node["node_id"], "label": node["label"], "group": group,
        "scope": axes.get(SEGMENT_AXIS) if group == "products" else None,
        "member": axes[SEGMENT_AXIS] if group == "segments" else next(axes[axis] for axis in axes if axis in PRODUCT_AXES),
        "axis_members": axes, "mapping_epoch": node["row_id"],
        "mapping_review_required": bool(node.get("mapping_review_required")), "cells": {},
    })
    pending = defaultdict(list)
    for cell in cells:
        if _coordinate(cell) in coordinates and (not fallback or _coordinate(cell) not in row["cells"]):
            pending[_coordinate(cell)].append(cell)
    for key, candidates in pending.items():
        if len(candidates) != 1:
            row["cells"][key] = _gap("COMPETING_PREPARED_SCOPE")
            continue
        cell = candidates[0]
        if cell.get("value") is None or cell.get("status") not in {"REPORTED", "DERIVED"}:
            # The fallback may supply only an exact independently stored reported cell.
            if cell.get("reason") not in {None, "PERIOD_NOT_DISCLOSED_FOR_PREPARED_ROW_IDENTITY"}:
                row["cells"][key] = _gap("PREPARED_OBSERVATION_HELD")
            continue
        evidence = cell.get("provenance") or client.trace(cell["cell_id"], context=context)["trace"]
        row["cells"][key] = _prepared_cell(cell, evidence, coordinates[key], context, cik)


def _prepared_cell(cell: dict, trace: dict, period: dict, context: dict, cik: str) -> dict:
    lineage = trace.get("value_lineage") or {}
    unit = cell.get("unit")
    if (
        not isinstance(unit, list) or len(unit) != 2
        or [json.loads(item) if isinstance(item, str) else item for item in unit] != [["iso4217:USD"], []]
        or not isinstance(cell.get("value"), str) or finite_decimal(cell["value"]) is None
        or cell.get("start") != period["period_start"] or cell.get("end") != period["period_end"]
        or not cell.get("start") or not cell.get("end")
        or cell.get("as_of") != context["as_of"] or cell.get("selection_view") != context["view"]
        or any(source.get("quality_blocking") or source.get("quality_status") == "BLOCK"
               for source in (cell, lineage, trace.get("quality_overlay") or {}))
        or any(lineage.get(field) for field in ("ambiguity", "ambiguous", "compatibility_failure", "recast_review_required"))
    ):
        return _gap("PREPARED_OBSERVATION_HELD")
    raw_sources = [lineage] if cell["status"] == "REPORTED" else lineage.get("source_inputs") or []
    if not raw_sources or (cell["status"] == "REPORTED" and lineage.get("selected_source_fact_id") != cell.get("source_fact_id")):
        return _gap("SOURCE_NOT_PREPARED")
    sources = [_source(raw, cik, context["as_of"]) for raw in raw_sources]
    if not all(sources):
        return _gap("SOURCE_NOT_PREPARED")
    return {
        "value": cell["value"], "status": cell["status"], "reason": None, "cell_id": cell["cell_id"],
        "sources": sources, "share": None, "yoy": None,
    }


def _source(raw: dict, cik: str, cutoff: str) -> dict | None:
    accession, filed, snapshot = raw.get("accession"), raw.get("filed_date"), raw.get("source_snapshot_id")
    fact = raw.get("selected_source_fact_id")
    if (
        not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
        or not isinstance(filed, str) or not filed <= cutoff
        or not isinstance(snapshot, str) or not snapshot.startswith(f"l1:{cik}:{accession.replace('-', '')}:")
        or not isinstance(fact, str) or not fact or raw.get("raw_concept_is_standard") is not True
        or raw.get("raw_concept_qname") not in REVENUE_QNAMES
        or not re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", str(raw.get("raw_concept_namespace_uri")))
        or raw.get("quality_blocking") or raw.get("quality_status") == "BLOCK"
    ):
        return None
    return {"accession": accession, "filed_date": filed, "snapshot_id": snapshot, "fact_id": fact,
            "qname": raw["raw_concept_qname"]}


def _hold_conflicts(series: dict) -> None:
    seen = defaultdict(list)
    for row in series.values():
        for coordinate, cell in row["cells"].items():
            if cell["value"] is not None:
                key = (coordinate, tuple(sorted(row["axis_members"].items())))
                seen[key].append((row, coordinate, cell))
    for candidates in seen.values():
        if len(candidates) < 2:
            continue
        identity = {
            (cell["value"], tuple((source["snapshot_id"], source["fact_id"]) for source in cell["sources"]))
            for _, _, cell in candidates
        }
        if len(identity) == 1:
            for row, coordinate, _ in candidates[1:]:
                row["cells"].pop(coordinate)
        else:
            for row, coordinate, _ in candidates:
                row["cells"][coordinate] = _gap("COMPETING_PREPARED_SCOPE")


def _gap(reason: str) -> dict:
    return {"value": None, "status": "UNAVAILABLE", "reason": reason, "sources": [], "share": None, "yoy": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--dataset-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cik", action="append", dest="ciks")
    args = parser.parse_args()
    print(prepare_revenue_breakdowns(**vars(args)))


if __name__ == "__main__":
    main()
