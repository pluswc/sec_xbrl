"""Project pinned, already prepared company revenue breakdowns for the local UI."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import polars as pl

from sec_xbrl.analysis import open_analysis
from sec_xbrl.analytics.quarterly_derived_metrics import percentage_result
from sec_xbrl.analytics.statement_structure import finite_decimal
from sec_xbrl.longitudinal.materialization import (
    LAYER2_CONTRACT_VERSION,
    Layer2PublicationValidationError,
    _run_from_manifest,
    _validate_operational_manifest_shape,
)
from sec_xbrl.longitudinal.relationship_index import (
    FilingRelationshipIndexError,
    FilingRelationshipIndexReader,
)
from sec_xbrl.screening.common import (
    real_directory,
    regular_file,
    require_cik,
    safe_new_destination,
)

SCHEMA_VERSION = "screening-revenue-breakdowns-v1"
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_COMPANY_BYTES = 1024 * 1024
SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
PRODUCT_AXES = {"srt:ProductOrServiceAxis", "us-gaap:ProductOrServiceAxis"}
GEOGRAPHY_AXIS = "srt:StatementGeographicalAxis"
# Explicit semantic registration; axis names never auto-enable a view.
REVENUE_VIEWS = (
    {"id": "segments", "label": "사업부문", "axes": [SEGMENT_AXIS], "fixed_groups": []},
    {"id": "products", "label": "제품·서비스", "axes": sorted(PRODUCT_AXES), "fixed_groups": ["segments"]},
    {"id": "geography", "label": "지역", "axes": [GEOGRAPHY_AXIS],
     "fixed_groups": ["segments", "products"], "share_basis": "EXACT_FIXED_SCOPE"},
)
REVENUE_QNAMES = {
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
}
VIEW = "LATEST_REPORTED"
RATIO_RULE_VERSION = "same-filing-revenue-ratios-v1"
OBSERVATIONS = "reported_period_observation"
PRODUCT_HIERARCHY_VERSION = "disclosed-revenue-role-presentation-v1"


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
        relationship_cache = {}
        company = {
            "ticker": ticker,
            "annual": _prepare_company(annual_config, cutoff, "FY", 4, relationship_cache),
            "quarterly": _prepare_company(quarter_config, cutoff, "QTD_3M", 8, relationship_cache),
        }
        companies[cik] = company
    payload = {
        "schema_version": SCHEMA_VERSION, "dataset_id": dataset["dataset_id"],
        "dataset_publication_id": dataset["publication_id"], "financial_as_of": cutoff,
        "dataset_manifest_sha256": dataset_manifest_sha256, "companies": companies,
    }
    data = _bounded_payload(payload)
    with destination.open("xb") as stream:
        stream.write(data)
    return destination


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _bounded_payload(payload: dict) -> bytes:
    scope_keys = ("schema_version", "dataset_id", "dataset_publication_id", "financial_as_of", "dataset_manifest_sha256")
    scope = {key: payload[key] for key in scope_keys}
    for cik, company in payload["companies"].items():
        size = len(_json(company | scope | {"cik": cik}))
        if size > MAX_COMPANY_BYTES:
            raise ValueError(f"revenue breakdown company {company['ticker']} exceeds response limit: {size}")
    data = _json(payload)
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("revenue breakdown asset exceeds size limit")
    return data


def _prepare_company(
    declaration: dict, cutoff: str, period_class: str, limit: int, relationship_cache: dict,
) -> dict:
    root = real_directory(Path(declaration["analysis_root"]), "revenue breakdown analysis")
    digest = declaration["analysis_manifest_sha256"]
    manifest = _pinned_json(root / "analysis_manifest.json", digest)
    client = open_analysis(root)
    if client.manifest != manifest or (manifest.get("period_mode") == "ANNUAL") != (period_class == "FY"):
        raise ValueError("revenue breakdown analysis manifest scope differs")
    ticker, cik = declaration["ticker"], declaration["cik"]
    observations, evidence, history = _ratio_observations(manifest, ticker, cik, cutoff, period_class)
    result = project_breakdowns(client, ticker, cik, cutoff, period_class, limit, ratio_observations=observations)
    result["ratio_evidence"] = evidence
    relationships = _relationship_lookup(history, cik, relationship_cache)
    result["product_hierarchy_version"] = PRODUCT_HIERARCHY_VERSION
    result["product_hierarchy"] = _product_hierarchy(result, observations, relationships)
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
    groups: dict[str, list] = {view["id"]: [] for view in REVENUE_VIEWS}
    for row in series.values():
        cells = [row["cells"].get(key, _gap("PERIOD_NOT_PREPARED")) for key in coordinates]
        if any(cell["value"] is not None or cell["reason"] == "COMPETING_PREPARED_SCOPE" for cell in cells):
            groups[row["group"]].append({**row, "cells": cells})
    totals = _consolidated_totals(overview, coordinates, client, context, cik, period_class)
    _add_revenue_ratios(totals, groups, periods, comparison_periods, ratio_observations)
    return {"periods": periods, "totals": totals, "groups": groups, "ratio_rule_version": RATIO_RULE_VERSION, "views": list(REVENUE_VIEWS)}


def _ratio_observations(
    manifest: dict, ticker: str, cik: str, cutoff: str, period_class: str,
) -> tuple[list[dict], dict, dict]:
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
    }, history


def _relationship_lookup(history: dict, cik: str, cache: dict) -> Callable[[str], tuple[dict, ...]]:
    declaration = history["operational_roots"].get("t2")
    if not declaration:
        return lambda _: ()
    try:
        root = real_directory(Path(declaration), "revenue presentation relationship index")
        manifest = json.loads(regular_file(root / "layer2_run_manifest.json", "relationship manifest").read_bytes())
        if manifest.get("run_fingerprint") != history["input_fingerprint"]:
            return lambda _: ()
    except (ValueError, OSError):
        return lambda _: ()

    def lookup(accession: str) -> tuple[dict, ...]:
        key = (root, accession)
        if key not in cache:
            try:
                edges = FilingRelationshipIndexReader().query_parquet(root, cik=cik, accession=accession)
                cache[key] = tuple(edge for edge in edges if edge["network_type"] in {"PRE", "DEF"})
            except (FilingRelationshipIndexError, Layer2PublicationValidationError, ValueError, OSError):
                cache[key] = ()
        return cache[key]

    return lookup


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


def _observation_indexes(observations: Iterable[dict]) -> tuple[dict, dict]:
    by_fact = defaultdict(list)
    by_scope = defaultdict(list)
    for row in observations:
        scope = _ratio_scope(row)
        if scope is None:
            continue
        by_fact[(row["source_snapshot_id"], row["source_fact_id"])].append((scope, row))
        by_scope[(scope, row["context_start_date"], row["context_end_date"], row["comparative_type"])].append(row)
    return by_fact, by_scope


def _add_revenue_ratios(
    totals: list[dict], groups: dict, periods: list[dict], comparison_periods: list[dict], observations: Iterable[dict],
) -> None:
    by_fact, by_scope = _observation_indexes(observations)
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
                if "fixed_axis_members" in row:
                    fixed = row["fixed_axis_members"]
                    candidates = [candidate for candidate, candidate_cell in entries
                                  if candidate["axis_members"] == fixed
                                  and (candidate_cell["value"] is not None
                                       or candidate_cell["reason"] == "COMPETING_PREPARED_SCOPE")]
                    parent = candidates[0]["cells"][index] if len(candidates) == 1 else {} if fixed else total
                denominator = bound.get(parent.get("cell_id"))
                if denominator is not None:
                    parent_scope, parent_value = denominator
                    if (
                        scope[:-1] == parent_scope[:-1] and 0 <= value <= parent_value and parent_value > 0
                        and set(parent_scope[-1]) < set(scope[-1])
                    ):
                        cell["share"] = str(percentage_result(value, parent_value, subtract_one=False))
                        ratios["share"] = {
                            "denominator": _share_denominator(row),
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


def _share_denominator(row: dict) -> str:
    if "fixed_axis_members" in row:
        return "FIXED_SCOPE_REPORTED" if row["fixed_axis_members"] else "CONSOLIDATED"
    return "SEGMENT_SUBTOTAL" if row["scope"] else "CONSOLIDATED"


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


def _product_hierarchy(
    result: dict, observations: Iterable[dict], relationships: Callable[[str], tuple[dict, ...]],
) -> list[list[dict]]:
    by_fact, by_scope = _observation_indexes(observations)
    periods = []
    for index, period in enumerate(result["periods"]):
        layouts = []
        periods.append(layouts)
        start, end = period["period_start"], period["period_end"]
        if not start or not end:
            continue
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        by_segment = defaultdict(list)
        for row in result["groups"]["products"]:
            cell = row["cells"][index]
            if cell["value"] is not None or cell["reason"] == "COMPETING_PREPARED_SCOPE":
                by_segment[row["scope"]].append((row, cell))
        for segment, entries in by_segment.items():
            parents = [row["cells"][index] for row in result["groups"]["segments"] if row["member"] == segment
                       and (row["cells"][index]["value"] is not None
                            or row["cells"][index]["reason"] == "COMPETING_PREPARED_SCOPE")] if segment else [result["totals"][index]]
            if len(parents) != 1:
                continue
            parent, = parents
            bound = _bind_ratio_cell(parent, by_fact, by_scope, start, end, days, int(segment is not None))
            if bound is None or bound[1] <= 0:
                continue
            identity, parent_value = bound
            members = {}
            for row, cell in entries:
                current = _bind_ratio_cell(cell, by_fact, by_scope, start, end, days, len(row["axis_members"]))
                if current is None or current[0][:-1] != identity[:-1] or current[1] <= 0:
                    break
                extra = set(current[0][-1]) - set(identity[-1])
                if len(extra) != 1 or not set(identity[-1]) < set(current[0][-1]):
                    break
                axis, member, *_ = next(iter(extra))
                if member in members:
                    break
                product_axis, = set(row["axis_members"]) & PRODUCT_AXES
                members[member] = (axis, product_axis, row["member"], row["id"], Fraction(current[1]))
            else:
                axes = {(member[0], member[1]) for member in members.values()}
                if len(members) < 2 or len(axes) != 1:
                    continue
                axis, axis_qname = axes.pop()
                edges = relationships(identity[2])
                roles = _product_role_partitions(edges, identity, axis, axis_qname, segment, members)
                layout = _reconcile_product_roles(roles, members, Fraction(parent_value))
                if layout is not None:
                    layouts.append({
                        "scope": segment, "parent_fact_id": parent["sources"][0]["fact_id"],
                        "accession": identity[2], **layout,
                    })
    return periods


def _product_role_partitions(
    edges: Iterable[dict], identity: tuple, axis: str, axis_qname: str, segment: str | None, members: dict,
) -> list[dict]:
    by_role = defaultdict(list)
    redirected_members = set()
    redirected_cubes = set()
    for edge in edges:
        if (
            (edge["source_snapshot_id"], edge["source_filing_id"], edge["accession"], edge["filed_date"])
            != identity[:4]
        ):
            continue
        by_role[(edge["role_id"], edge["role_uri"])].append(edge)
        arc = _dimensional_arc(edge)
        if target_role := edge["target_role_uri"]:
            target = (target_role, edge["to_raw_concept_id"])
            if arc == "domain-member":
                redirected_members.update((target, (edge["role_uri"], edge["to_raw_concept_id"])))
            elif arc in {"all", "notAll"}:
                redirected_cubes.add(target)

    partitions = []
    for (role_id, uri), role_edges in by_role.items():
        if not role_id or not uri:
            continue
        pre = defaultdict(list)
        definitions = defaultdict(list)
        for edge in role_edges:
            source, target = edge["from_raw_concept_id"], edge["to_raw_concept_id"]
            if (
                edge["network_type"] == "PRE" and edge["arcrole"] == "http://www.xbrl.org/2003/arcrole/parent-child"
                and (edge["link_qname"], edge["arc_qname"]) == ("link:presentationLink", "link:presentationArc")
            ):
                pre[source].append(edge)
            elif arc := _dimensional_arc(edge):
                definitions[(source, target, arc)].append(edge)
        shapes = []
        for table, children in pre.items():
            table_axes = [edge for edge in children if edge["to_raw_concept_id"] == axis
                          and edge["to_raw_concept_qname"] == axis_qname]
            concepts = [(child, leaf) for child in children for leaf in pre.get(child["to_raw_concept_id"], ())
                        if leaf["to_raw_concept_id"] == identity[4]
                        and (leaf["to_raw_concept_qname"], leaf["to_namespace_uri"]) == identity[5:7]]
            if not table_axes or not concepts:
                continue
            if len(table_axes) != 1 or len(concepts) != 1:
                return []
            for domain_edge in pre.get(axis, ()):
                domain = domain_edge["to_raw_concept_id"]
                leaves = pre.get(domain, ())
                if not any(edge["to_raw_concept_id"] in members for edge in leaves):
                    continue
                member_ids = [edge["to_raw_concept_id"] for edge in leaves]
                orders = [finite_decimal(edge["order"]) for edge in leaves]
                if (
                    len(member_ids) != len(set(member_ids)) or None in orders or len(set(orders)) != len(orders)
                    or any(member not in members or edge["to_raw_concept_qname"] != members[member][2]
                           or pre.get(member) for edge, member in zip(leaves, member_ids, strict=True))
                ):
                    return []
                pre_proof = [*table_axes, *concepts[0], domain_edge, *leaves]
                def_proof = _definition_arcs(definitions, [
                    (table, axis, "hypercube-dimension"), (axis, domain, "dimension-domain"),
                    *((domain, member, "domain-member") for member in member_ids),
                ])
                if def_proof is None or not _hypercube_is_uncontested(
                    pre, definitions, uri, table, identity[4], redirected_members, redirected_cubes,
                ):
                    return []
                if segment:
                    (segment_axis, segment_member, *_), = identity[-1]
                    fixed_scope = _fixed_role_scope(pre, definitions, table, segment_axis, segment_member, segment)
                    if fixed_scope is None:
                        return []
                    pre_proof += fixed_scope[0]
                    def_proof += fixed_scope[1]
                if any(edge["target_role_uri"] or edge["usable"] is False for edge in pre_proof):
                    return []
                ordered = [member for _, member in sorted(zip(orders, member_ids, strict=True))]
                shapes.append({
                    "label": table_axes[0]["role_definition"], "role_uri": uri, "members": ordered,
                    "relationship_ids": [edge["relationship_id"] for edge in (*pre_proof, *def_proof)],
                })
        if len(shapes) > 1:
            return []
        partitions.extend(shapes)
    return sorted(partitions, key=lambda role: (role["label"] or "", role["role_uri"]))


def _dimensional_arc(edge: dict) -> str | None:
    if (
        edge["network_type"] == "DEF" and edge["arcrole"].startswith("http://xbrl.org/int/dim/arcrole/")
        and (edge["link_qname"], edge["arc_qname"]) == ("link:definitionLink", "link:definitionArc")
    ):
        return edge["arcrole"].rsplit("/", 1)[-1]
    return None


def _hypercube_is_uncontested(
    pre: dict, definitions: dict, uri: str, table: str, concept: str,
    redirected_members: set[tuple[str, str]], redirected_cubes: set[tuple[str, str]],
) -> bool:
    # PRE is only used to widen the exclusion check. It cannot prove a
    # positive dimensional relationship or bridge role boundaries.
    parents = defaultdict(list)
    for source, children in pre.items():
        for edge in children:
            parents[edge["to_raw_concept_id"]].append(source)
    for source, target, arc in definitions:
        if arc == "domain-member":
            parents[target].append(source)
    ancestors = {concept}
    pending = [concept]
    while pending:
        for parent in parents[pending.pop()]:
            if parent not in ancestors:
                ancestors.add(parent)
                pending.append(parent)

    if (uri, table) in redirected_cubes or any((uri, node) in redirected_members for node in ancestors):
        return False
    contexts = set()
    for node in ancestors:
        if definitions.get((node, table, "notAll")):
            return False
        for edge in definitions.get((node, table, "all"), ()):
            if edge["target_role_uri"] or edge["context_element"] not in {"segment", "scenario"}:
                return False
            contexts.add(edge["context_element"])
    return len(contexts) <= 1


def _definition_arcs(definitions: dict, keys: list[tuple]) -> list[dict] | None:
    found = []
    for key in keys:
        edges = definitions[key]
        if len(edges) != 1 or edges[0]["target_role_uri"] or edges[0]["usable"] is False:
            return None
        found.extend(edges)
    return found


def _fixed_role_scope(
    pre: dict, definitions: dict, table: str, axis: str, member: str, member_qname: str,
) -> tuple[list[dict], list[dict]] | None:
    paths = [
        (axis_edge, domain_edge, member_edge)
        for axis_edge in pre[table] if axis_edge["to_raw_concept_id"] == axis
        and axis_edge["to_raw_concept_qname"] == SEGMENT_AXIS
        for domain_edge in pre.get(axis, ())
        for member_edge in pre.get(domain_edge["to_raw_concept_id"], ())
        if member_edge["to_raw_concept_id"] == member and member_edge["to_raw_concept_qname"] == member_qname
    ]
    if len(paths) != 1:
        return None
    _, domain_edge, _ = paths[0]
    domain = domain_edge["to_raw_concept_id"]
    proof = _definition_arcs(definitions, [
        (table, axis, "hypercube-dimension"), (axis, domain, "dimension-domain"), (domain, member, "domain-member"),
    ])
    return (list(paths[0]), proof) if proof is not None else None


def _reconcile_product_roles(roles: list[dict], members: dict, parent: Fraction) -> dict | None:
    sets = [set(role["members"]) for role in roles]
    if not sets or set.union(*sets) != set(members):
        return None
    amounts = {member: data[-1] for member, data in members.items()}

    def rows(order: Iterable[str], nested: dict | None = None) -> list[dict]:
        return [{"id": members[member][3], "children": rows(nested[member]) if nested and member in nested else []}
                for member in order]

    evidence = [{key: value for key, value in role.items() if key != "members"} for role in roles]
    complete = all(sum(amounts[member] for member in group) == parent for group in sets)
    if len(sets) > 1 and complete and sum(map(len, sets)) == len(members):
        return {"mode": "DISCLOSURES", "evidence": evidence,
                "groups": [{"label": role["label"], "rows": rows(role["members"])} for role in roles]}
    if len(sets) == 2 and complete:
        shared = sets[0] & sets[1]
        coarse, detailed = sorted(range(2), key=lambda index: len(sets[index]))
        roots = sets[coarse] - shared
        details = [member for member in roles[detailed]["members"] if member not in shared]
        if len(roots) == 1 and len(details) >= 2:
            root, = roots
            if amounts[root] == sum(amounts[member] for member in details):
                return {"mode": "RECONCILED", "evidence": evidence,
                        "groups": [{"rows": rows(roles[coarse]["members"], {root: details})}]}
    if len(sets) != 1:
        return None
    order = roles[0]["members"]
    total = sum(amounts.values())
    if total == parent:
        return {"mode": "VERIFIED", "evidence": evidence, "groups": [{"rows": rows(order)}]}
    matches = []
    for index, member in enumerate(order):
        if total - amounts[member] != parent:
            continue
        amount = Fraction(0)
        for first in range(index - 1, -1, -1):
            amount += amounts[order[first]]
            if amount == amounts[member] and index - first >= 2:
                matches.append((member, order[first:index]))
            if amount >= amounts[member]:
                break
    if len(matches) != 1:
        return None
    member, details = matches[0]
    return {"mode": "RECONCILED", "evidence": evidence,
            "groups": [{"rows": rows([item for item in order if item not in details], {member: details})}]}


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


def _view_for_axes(axes: set[str]) -> dict | None:
    registry = {view["id"]: view for view in REVENUE_VIEWS}
    # Later registrations take priority when their primary axis is present.
    for view in reversed(REVENUE_VIEWS):
        allowed = set(view["axes"])
        fixed = [registry[group] for group in view["fixed_groups"]]
        allowed.update(axis for group in fixed for axis in group["axes"])
        if (len(axes & set(view["axes"])) == 1 and axes <= allowed
                and all(len(axes & set(group["axes"])) <= 1 for group in fixed)):
            return view
    return None


def _supported_axes(axes: set[str]) -> bool:
    return _view_for_axes(axes) is not None


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
    view = _view_for_axes(set(axes))
    assert view is not None
    group = view["id"]
    primary_axis, = set(axes) & set(view["axes"])
    row = series.setdefault(node["node_id"], {
        "id": node["node_id"], "label": node["label"], "group": group,
        "scope": axes.get(SEGMENT_AXIS) if group == "products" else None,
        "member": axes[primary_axis],
        "axis_members": axes, "mapping_epoch": node["row_id"],
        "mapping_review_required": bool(node.get("mapping_review_required")), "cells": {},
    })
    if view.get("share_basis") == "EXACT_FIXED_SCOPE":
        row["fixed_axis_members"] = {axis: member for axis, member in axes.items() if axis != primary_axis}
        row["raw_dimensions"] = node["dimensions"]
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
