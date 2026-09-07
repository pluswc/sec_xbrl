"""Producer-side fiscal/rolling classification and approved quarterly flows.

The consumer reader remains calculation-free. This producer re-attests selected
reported cells to new T1 period observations, then publishes separate derived
records and consumer cells in a new immutable revision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import defaultdict
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sec_xbrl.analytics.fiscal_time_series import (
    _annotate_comparability,
    _column,
    _id,
    _period_evidence,
)
from sec_xbrl.history import (
    HISTORY_VERSION,
    HistoryPublicationReader,
    _write_json,
    _write_records,
    build_history,
)
from sec_xbrl.longitudinal import Layer2PublicationReader
from sec_xbrl.longitudinal.q4_policy_registry import CASH_FLOW_ALLOWLIST, INCOME_ALLOWLIST

QUARTER_RULE = "approved-core-cumulative-difference-v1"
PERIOD_RULE = "m6-fiscal-boundaries-v2"


def _sequence(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _scope(value: dict[str, Any]) -> str:
    return json.dumps([value.get("company_canonical_concept_id"), value.get("canonical_dimension_signature"),
                       _sequence(value.get("unit_numerator_measures")), _sequence(value.get("unit_denominator_measures")),
                       value.get("selection_view"), value.get("selection_as_of_date"), value.get("comparative_type")], sort_keys=True)


def approved_additive(cell: dict[str, Any]) -> bool:
    value = cell.get("value_lineage") or {}
    name = str(value.get("raw_concept_qname", "")).split(":")[-1]
    unit = _sequence(value.get("unit_numerator_measures") or [])
    if name in {"PaymentsForRepurchaseOfCommonStock", "ShareBasedCompensation", "PaymentsToAcquireProductiveAssets"}:
        evidence = cell.get("binding", {}).get("primary_statement_evidence", [])
        if not any("CF" in e.get("statement_types", []) and e.get("source_network_type") == "PRE" for e in evidence):
            return False
    return bool(
        cell.get("value_status") == "REPORTED" and value.get("source_type") == "REPORTED"
        and name in INCOME_ALLOWLIST | CASH_FLOW_ALLOWLIST
        and re.fullmatch(r"https?://fasb.org/us-gaap/\d{4}", str(value.get("raw_concept_namespace_uri", "")))
        and value.get("raw_concept_period_type") == "duration"
        and "monetary" in str(value.get("raw_concept_data_type", "")).lower()
        and value.get("company_canonical_concept_id") and not value.get("mapping_review_required")
        and not value.get("canonical_dimension_signature")
        and len(unit) == 1 and str(unit[0]).startswith("iso4217:")
        and not _sequence(value.get("unit_denominator_measures") or [])
        and cell.get("binding", {}).get("primary_statement_evidence")
    )


def _has_materialized_cell(cells: list[dict[str, Any]], row_id: str, column_id: str) -> bool:
    """A conflicting direct report is not an absent disclosure to gap-fill."""
    return any(cell["fiscal_time_series_row_id"] == row_id and cell["fiscal_time_series_column_id"] == column_id for cell in cells)


def derive_quarter(later: dict[str, Any], earlier: dict[str, Any], *, quarter: int) -> dict[str, Any] | None:
    """One reviewed additive difference; reject all incompatible scopes."""
    if quarter not in {2, 3, 4} or not approved_additive(later) or not approved_additive(earlier):
        return None
    left, right = later["value_lineage"], earlier["value_lineage"]
    expected = {2: ("YTD_6M", "QTD_3M"), 3: ("YTD_9M", "YTD_6M"), 4: ("FY", "YTD_9M")}[quarter]
    if (left.get("period_class"), right.get("period_class")) != expected or _scope(left) != _scope(right):
        return None
    if not left.get("context_start_date") or left.get("context_start_date") != right.get("context_start_date"):
        return None
    for key in ("basis_version", "structural_version", "recast_version"):
        if left.get(key) != right.get(key):
            return None
    if any(value.get("continuity_break") or value.get("recast_review_required") for value in (left, right)):
        return None
    as_of = left.get("selection_as_of_date")
    if not as_of or any(not value.get("filed_date") or value["filed_date"] > as_of for value in (left, right)):
        return None
    try:
        start, end = date.fromisoformat(right["context_end_date"]), date.fromisoformat(left["context_end_date"])
        if not 75 <= (end - start).days <= 105:
            return None
        amount = Decimal(str(left["value_numeric"])) - Decimal(str(right["value_numeric"]))
        if not amount.is_finite():
            return None
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return None
    fact_ids = [left["selected_source_fact_id"], right["selected_source_fact_id"]]
    metric_id = _id("derived", QUARTER_RULE, fact_ids, quarter, _scope(left))
    return {"derived_metric_id": metric_id, "derivation_rule_version": QUARTER_RULE,
            "formula": f"{expected[0]} - {expected[1]}", "fiscal_quarter": quarter,
            "value_numeric": str(amount), "context_start_date": str(start), "context_end_date": str(end),
            "period_class": "QTD_3M", "source_fact_ids": fact_ids,
            "source_filing_ids": [left["source_filing_id"], right["source_filing_id"]],
            "source_accessions": [left["accession"], right["accession"]],
            "source_inputs": [deepcopy(left), deepcopy(right)], "source_type": "DERIVED_QUARTER",
            "reported_or_derived": "DERIVED", "semantic_review_state": "REVIEWED_ADDITIVE_AMOUNT",
            "policy_registry": "CONTROLLED_STANDARD_STATEMENT_ALLOWLIST",
            "basis_compatibility": "DIRECT_REPORTED_SAME_SCOPE_NO_EVIDENCED_BREAK_NOT_RECAST_COMPARABLE"}


def publish_quarter_history(*, publication: Path, output_root: Path, reuse_roots: bool = False,
                            operational_root: Path | None = None) -> Path:
    """Upgrade reported period evidence and materialize governed quarter cells."""
    old = HistoryPublicationReader(publication)
    old.verify_all()
    destination = output_root / "panels"
    if destination.exists():
        raise ValueError("choose a new immutable quarterly publication destination")
    output_root.mkdir(parents=True, exist_ok=True)
    intake_path = Path(old.manifest["source_intake"])
    if not reuse_roots and operational_root is None:
        build_history(intake_manifest=intake_path, output_root=output_root, views=tuple(old.manifest["views"]), roots_only=True)
    prepared_root = operational_root or output_root
    roots = {name: prepared_root / name / prepared_root.name for name in ("t1", "t2", "t3", "t4")}
    observed = Layer2PublicationReader().load(roots["t1"])
    if (reuse_roots or operational_root is not None) and observed.identity["layer2_run_fingerprint"] != old.manifest["input_fingerprint"]:
        raise ValueError("reused period publications do not match reported panels")
    by_fact = {(row["source_filing_id"], row["source_fact_id"]): row for row in observed.records("reported_period_observation")}
    bundles: dict[tuple[str, str, str], dict[str, Any]] = {}
    changes = defaultdict(int)
    for table in old.manifest["tables"]:
        result = old.load(ticker=table["ticker"], period_class=table["period_class"], view=table["view"])
        columns = {column["fiscal_time_series_column_id"]: column for column in result.columns}
        rows = {row["fiscal_time_series_row_id"]: row for row in result.rows}
        for original in result.cells:
            cell = deepcopy(original)
            value = cell.get("value_lineage")
            old_column = columns[cell["fiscal_time_series_column_id"]]
            period_class = table["period_class"]
            if value is not None and value.get("selected_source_fact_id"):
                source = by_fact.get((value["source_filing_id"], value["selected_source_fact_id"]))
                if source is None or source["comparative_type"] != "CURRENT_FOCUS":
                    raise ValueError("selected cell is not attested by corrected current-focus T1")
                for name in ("value_numeric", "value_text", "context_start_date", "context_end_date", "context_instant_date",
                             "context_id", "unit_id", "raw_concept_id", "raw_concept_qname", "raw_concept_namespace_uri",
                             "company_canonical_concept_id", "filed_date", "source_snapshot_id", "accession"):
                    if source.get(name) != value.get(name):
                        raise ValueError("selected cell differs from corrected T1 source")
                for name in ("unit_numerator_measures", "unit_denominator_measures", "canonical_dimension_signature"):
                    if json.dumps(_sequence(source.get(name)), sort_keys=True) != json.dumps(_sequence(value.get(name)), sort_keys=True):
                        raise ValueError("selected cell measurement scope differs from corrected T1")
                if value.get("selection_view") != table["view"] or value.get("selection_as_of_date") != old.manifest["plan"]["as_of_date"]:
                    raise ValueError("selected cell view/as-of disagrees with publication")
                period_class = source["period_class"]
                if period_class != table["period_class"]:
                    changes[f"{table['period_class']}->{period_class}"] += 1
                value.update(period_class=period_class, classification_rule_version=source["classification_rule_version"],
                             period_classification_reason=source.get("period_classification_reason"))
                if cell.get("candidate_lineage"):
                    cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")
                    cell["prior_candidate_publication"] = str(publication.absolute())
            key = (table["ticker"], table["view"], period_class)
            bundle = bundles.setdefault(key, {"table": {**table, "period_class": period_class,
                "scope": {**table["scope"], "period_class": period_class}}, "rows": {}, "columns": {}, "cells": []})
            column = {**old_column, "period_class": period_class,
                      "fiscal_time_series_column_id": _id("column", (old_column["fiscal_year"], old_column["fiscal_quarter"], period_class))}
            cell["fiscal_time_series_column_id"] = column["fiscal_time_series_column_id"]
            cell["fiscal_time_series_cell_id"] = _id("reclassified-cell", cell.get("fiscal_time_series_cell_id"), PERIOD_RULE)
            bundle["columns"][column["fiscal_time_series_column_id"]] = column
            bundle["rows"][cell["fiscal_time_series_row_id"]] = rows[cell["fiscal_time_series_row_id"]]
            bundle["cells"].append(cell)
    derived = []
    for ticker, view in sorted({(key[0], key[1]) for key in bundles}):
        qtd = bundles.get((ticker, view, "QTD_3M"))
        if qtd is None:
            continue
        grouped = defaultdict(list)
        for (company, selected_view, kind), bundle in bundles.items():
            if company != ticker or selected_view != view or kind not in {"QTD_3M", "YTD_6M", "YTD_9M", "FY"}:
                continue
            for cell in bundle["cells"]:
                if approved_additive(cell):
                    column = bundle["columns"][cell["fiscal_time_series_column_id"]]
                    grouped[(column["fiscal_year"], kind, _scope(cell["value_lineage"]))].append((cell, column, bundle))
        for (year, kind, scope), choices in list(grouped.items()):
            quarter = {"YTD_6M": 2, "YTD_9M": 3, "FY": 4}.get(kind)
            if quarter is None:
                continue
            previous = {2: "QTD_3M", 3: "YTD_6M", 4: "YTD_9M"}[quarter]
            partners = grouped.get((year, previous, scope), [])
            if quarter == 2:
                partners = [item for item in partners if item[1]["fiscal_quarter"] == 1]
            if len(choices) != 1 or len(partners) != 1:
                continue
            later, annual_column, source_bundle = choices[0]
            earlier = partners[0][0]
            metric = derive_quarter(later, earlier, quarter=quarter)
            if metric is None:
                continue
            row_id = later["fiscal_time_series_row_id"]
            column_id = _id("column", (year, quarter, "QTD_3M"))
            if _has_materialized_cell(qtd["cells"], row_id, column_id):
                continue
            metric.update(cik=qtd["table"]["cik"], ticker=ticker, fiscal_year=year, view=view)
            derived.append(metric)
            value = {**deepcopy(later["value_lineage"]), **metric, "value_status": "DERIVED", "value_text": None,
                     "context_instant_date": None, "selected_source_fact_id": None, "source_filing_id": None,
                     "source_snapshot_id": None, "context_id": None, "accession": None,
                     "analysis_line_value_id": metric["derived_metric_id"]}
            definition = {**deepcopy(later["definition"]), "line_kind": "DERIVED"}
            binding = {"analysis_binding_id": metric["derived_metric_id"], "analysis_line_id": definition["analysis_line_id"],
                       "binding_kind": "GOVERNED_DERIVED_QUARTER", "derived_metric_id": metric["derived_metric_id"],
                       "source_bindings": [deepcopy(later["binding"]), deepcopy(earlier["binding"])]}
            column = _column((year, quarter, "QTD_3M"), annual_column.get("fiscal_year_end_as_filed"),
                             _period_evidence(SimpleNamespace(values=[{**value, "value_status": "REPORTED"}])))
            qtd["columns"].setdefault(column_id, column)
            qtd["rows"].setdefault(row_id, source_bundle["rows"][row_id])
            qtd["cells"] = [cell for cell in qtd["cells"] if not (cell["fiscal_time_series_row_id"] == row_id and cell["fiscal_time_series_column_id"] == column_id)]
            qtd["cells"].append({"fiscal_time_series_cell_id": metric["derived_metric_id"], "fiscal_time_series_row_id": row_id,
                                  "fiscal_time_series_column_id": column_id, "value_status": "DERIVED", "value_numeric": metric["value_numeric"],
                                  "value_text": None, "comparability_status": "COMPATIBLE_INPUTS", "comparability_reason": metric["basis_compatibility"],
                                  "definition": definition, "binding": binding, "value_lineage": value})
    staging = Path(tempfile.mkdtemp(prefix=".panels.partial-", dir=output_root))
    tables = []
    for key, bundle in sorted(bundles.items()):
        table = {**bundle["table"], "files": {}}
        # Recompute column boundaries from the corrected partition, not the old
        # FY/TTM mixture. Include derived durations as explicit source evidence.
        columns = []
        for column in bundle["columns"].values():
            values = [{**cell["value_lineage"], "value_status": "REPORTED"} for cell in bundle["cells"]
                      if cell["fiscal_time_series_column_id"] == column["fiscal_time_series_column_id"] and cell.get("value_lineage")]
            rebuilt = _column((column["fiscal_year"], column["fiscal_quarter"], table["period_class"]), column.get("fiscal_year_end_as_filed"),
                              _period_evidence(SimpleNamespace(values=values)))
            columns.append(rebuilt)
        payloads = {"columns": _annotate_comparability(tuple(sorted(columns, key=lambda c: c["column_order_key"]))),
                    "rows": tuple(bundle["rows"].values()), "cells": tuple(bundle["cells"])}
        for name, records in payloads.items():
            relative = Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet"
            table["files"][name] = {**_write_records(staging / relative, records), "path": str(relative)}
        tables.append(table)
        print(json.dumps({"stage": "QUARTER_PANEL", "ticker": key[0], "view": key[1], "period_class": key[2], "cells": len(bundle["cells"])}), flush=True)
    derived_info = _write_records(staging / "derived_quarter.parquet", tuple(derived))
    manifest = {**old.manifest, "version": HISTORY_VERSION, "tables": tables, "period_rule": PERIOD_RULE,
                "operational_roots": {key: str(path.absolute()) for key, path in roots.items()},
                "input_fingerprint": observed.identity["layer2_run_fingerprint"],
                "derived_quarter": {**derived_info, "path": "derived_quarter.parquet"},
                "quarterly_derivation_status": "APPROVED_STANDARD_ADDITIVE_CORE_CONNECTED",
                "derivation_rule": QUARTER_RULE, "period_reclassification_counts": dict(changes),
                "supersedes_publication": str(publication.absolute()),
                "source_manifest_sha256": hashlib.sha256((publication / "history_manifest.json").read_bytes()).hexdigest()}
    _write_json(staging / "history_manifest.json", manifest)
    verified = HistoryPublicationReader(staging, allow_staging=True)
    verified.verify_all()
    verified._records(manifest["derived_quarter"])
    staging.rename(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(publish_quarter_history(publication=args.publication, output_root=args.output_root))


if __name__ == "__main__":
    main()
