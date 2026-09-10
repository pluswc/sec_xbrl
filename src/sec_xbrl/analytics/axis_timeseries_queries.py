"""Read-only axis-wide time-series response over prepared analysis datasets."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def axis_timeseries(client: Any, ticker: str, lens_id: str, *, context: dict[str, Any]) -> dict[str, Any]:
    requested_ticker = ticker.upper()
    ticker, view, requested = client._validate_context(context)
    if ticker != requested_ticker:
        raise ValueError("query context company mismatch")
    pages = []
    cursor = None
    cursors = set()
    while True:
        page = client.children(lens_id, context=context, selection="all", limit=1000, cursor=cursor)
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            break
        if cursor in cursors:
            raise ValueError("axis pagination repeated cursor")
        cursors.add(cursor)
    page = _merge_pages(pages)
    lens = page["parent"]
    if lens.get("kind") != "LENS" or lens.get("lens_type") != "DIMENSIONAL_VIEW":
        raise ValueError("axis time series requires a prepared dimensional lens")
    period_classes = {node.get("period_class") for node in page["children"] if node.get("period_class")}
    if len(period_classes) != 1 or not period_classes <= {"QTD_3M", "INSTANT"}:
        raise ValueError("axis lens must have one supported prepared period class")
    period_class = next(iter(period_classes))

    periods = sorted(requested)
    columns = [_column(period, period_class, page["columns"]) for period in periods]
    traces = _trace_index(client, ticker, view)
    v2 = client.importance_v2(ticker, view=view)["records"] if "importance_v2" in client.manifest["companies"][ticker]["views"][view]["files"] else []
    total_id = f"axis-total:{lens_id}"
    rows = [
        {
            "row_id": total_id,
            "prepared_node_id": None,
            "label": _total_label(client, ticker, view, lens),
            "row_kind": "TOTAL",
            "parent_row_id": None,
            "depth": 0,
            "mapping_epoch": None,
            "mapping_review_required": False,
            "dimensions": [],
            "cells": _aligned(page["parent_cells"], periods, period_class, traces, total_id),
            "relationship_kind": "METRIC_TOTAL_CONTEXT",
            "display_order": -1,
            "protected": True,
            "warnings": [],
        }
    ]
    values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cell in page["cells"]:
        values[cell["node_id"]].append(cell)
    for node in page["children"]:
        edge_provenance = [
            copy.deepcopy(edge) for edge in page["evidence"] if edge["child_id"] == node["node_id"]
        ]
        prepared_warnings = sorted(
            {
                warning
                for importance in node.get("importance_history") or []
                for warning in importance.get("warnings") or []
            }
        )
        rows.append(
            {
                "row_id": node["node_id"],
                "prepared_node_id": node["node_id"],
                "label": node.get("label") or node["node_id"],
                "row_kind": "MEMBER",
                "parent_row_id": total_id,
                "depth": 1,
                "mapping_epoch": node.get("row_id"),
                "mapping_review_required": bool(node.get("mapping_review_required")),
                "basis_version": node.get("basis_version"),
                "canonical_concept_id": node.get("canonical_concept_id"),
                "dimensions": copy.deepcopy(node.get("dimensions") or []),
                "cells": _aligned(values[node["node_id"]], periods, period_class, traces, node["node_id"]),
                "relationship_kind": "DIMENSIONAL_VIEW_MEMBERSHIP_NOT_EQUATION",
                "display_order": len(rows),
                "importance": copy.deepcopy(node.get("importance")),
                "importance_history": copy.deepcopy(node.get("importance_history") or []),
                "importance_reasons": copy.deepcopy(node.get("importance_reasons") or []),
                "warnings": prepared_warnings,
                "edge_provenance": edge_provenance,
                "prepared_node": copy.deepcopy(node),
            }
        )

    for row in rows:
        cell_ids = {cell.get("cell_id") for cell in row["cells"]} - {None}
        row["importance_v2"] = copy.deepcopy([record for record in v2 if record.get("current_cell_id") in cell_ids])
        row["warnings"] = sorted(set(row.get("warnings", [])) | {
            warning for record in row["importance_v2"] for warning in record.get("warnings", [])
        } | ({"MAPPING_REVIEW_REQUIRED"} if row.get("mapping_review_required") else set()))

    reviews, source_comparisons = _reviews(client, ticker, lens, rows, total_id)
    publication = {
        "analysis_publication_id": client.manifest["publication_id"],
        "axis_publication_id": (client.axis_manifest or {}).get("publication_id"),
        "axis_decision_cutoff": (client.axis_manifest or {}).get("decision_cutoff"),
    }
    for evidence in [*reviews, *source_comparisons]:
        evidence["publication"] = copy.deepcopy(publication)
    parent_by_child: dict[str, str] = {}
    for relation in reviews:
        if relation["display_scope"] != "ANALYTICAL_EXACT_MATCH":
            continue
        for order, child in enumerate(relation["child_row_ids"]):
            previous = parent_by_child.setdefault(child, relation["parent_row_id"])
            if previous != relation["parent_row_id"]:
                raise ValueError("reviewed hierarchy assigns two analytical parents")
            next(row for row in rows if row["row_id"] == child)["reviewed_source_order"] = order
    by_id = {row["row_id"]: row for row in rows}
    for child, parent in parent_by_child.items():
        by_id[child]["parent_row_id"] = parent
        by_id[child]["depth"] = by_id[parent]["depth"] + 1
        by_id[parent]["protected"] = True
    # Protection retains the whole navigation path for every mandatory warning.
    for row in rows:
        row["observed_periods"] = [[cell["fiscal_year"], cell["fiscal_quarter"]] for cell in row["cells"] if cell.get("value") is not None and cell.get("status") in {"REPORTED", "DERIVED"}]
        row["reference_period_disclosed"] = list(max(requested)) in row["observed_periods"]
        if row.get("warnings") or row.get("protected"):
            parent = row["parent_row_id"]
            seen = set()
            while parent and parent not in seen:
                seen.add(parent)
                by_id[parent]["protected"] = True
                parent = by_id[parent]["parent_row_id"]
    rows = _top_down(rows)
    return copy.deepcopy(
        {
            "publication": publication,
            "axis_context": {**context, **publication, "lens_id": lens_id},
            "context": context,
            "lens": lens,
            "axis_identity": copy.deepcopy(lens.get("dimensions") or []),
            "period_class": period_class,
            "columns": columns,
            "rows": rows,
            "reviewed_relationships": reviews,
            "source_comparisons": source_comparisons,
            "warnings": [
                "MAPPING_EPOCHS_REMAIN_SEPARATE",
                "MISSING_PERIOD_IS_UNAVAILABLE_NOT_ZERO",
                "NESTED_MEMBERS_MUST_NOT_BE_DOUBLE_COUNTED",
                "CROSS_AXIS_VALUES_MUST_NOT_BE_ADDED",
            ],
        }
    )


def _merge_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    first = copy.deepcopy(pages[0])
    for page in pages[1:]:
        if page["parent"] != first["parent"] or page["columns"] != first["columns"] or page["parent_cells"] != first["parent_cells"]:
            raise ValueError("axis pagination changed prepared parent scope")
        first["children"].extend(copy.deepcopy(page["children"]))
        first["cells"].extend(copy.deepcopy(page["cells"]))
        first["evidence"].extend(copy.deepcopy(page["evidence"]))
    identities = [row["node_id"] for row in first["children"]]
    if len(identities) != len(set(identities)):
        raise ValueError("axis pagination repeated a member node")
    first["next_cursor"] = None
    return first


def _column(period: tuple[int, int], period_class: str, prepared: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [row for row in prepared if (row["fiscal_year"], row["fiscal_quarter"]) == period and row.get("period_class") == period_class]
    if len(matches) > 1:
        raise ValueError("prepared axis has duplicate quarter columns")
    source = matches[0] if matches else {}
    return {
        "column_id": source.get("column_id") or source.get("fiscal_time_series_column_id") or f"missing:{period_class}:{period[0]}:{period[1]}",
        "fiscal_year": period[0],
        "fiscal_quarter": period[1],
        "period_class": period_class,
        "actual_period_boundaries": copy.deepcopy(source.get("actual_period_boundaries")),
    }


def _aligned(cells: list[dict[str, Any]], periods: list[tuple[int, int]], period_class: str, traces: dict[str, dict[str, Any]], row_id: str) -> list[dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    for cell in cells:
        if cell.get("period_class") != period_class:
            raise ValueError("axis row mixes prepared period classes")
        key = (cell["fiscal_year"], cell["fiscal_quarter"])
        if key in indexed:
            raise ValueError("prepared row has duplicate cell for one fiscal quarter")
        indexed[key] = cell
    result = []
    for year, quarter in periods:
        cell = indexed.get((year, quarter))
        if cell is None:
            result.append(
                {
                    "row_id": row_id,
                    "fiscal_year": year,
                    "fiscal_quarter": quarter,
                    "period_class": period_class,
                    "status": "UNAVAILABLE",
                    "value": None,
                    "reason": "PERIOD_NOT_DISCLOSED_FOR_PREPARED_ROW_IDENTITY",
                    "source_fact_id": None,
                    "provenance": None,
                }
            )
        else:
            result.append({**copy.deepcopy(cell), "row_id": row_id, "provenance": copy.deepcopy(traces.get(cell["cell_id"]))})
    return result


def _trace_index(client: Any, ticker: str, view: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    files = client.manifest["companies"][ticker]["views"][view]["files"]
    for name in files:
        if not name.startswith("trace_"):
            continue
        for row in client._records(ticker, view, name):
            if row["cell_id"] in found:
                raise ValueError("duplicate prepared trace identity")
            found[row["cell_id"]] = row
    return found


def _total_label(client: Any, ticker: str, view: str, lens: dict[str, Any]) -> str:
    source_parent = lens.get("source_parent_concept")
    if source_parent:
        return str(source_parent).split(":")[-1]
    anchors = [row for row in client._records(ticker, view, "core_rows") if row["row_id"] == lens.get("anchor_row_id")]
    return anchors[0]["label"] if len(anchors) == 1 else str(lens.get("anchor_row_id") or "Total")


def _reviews(client: Any, ticker: str, lens: dict[str, Any], rows: list[dict[str, Any]], total_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not client.axis_manifest:
        return [], []
    candidates = defaultdict(list)
    for row in rows:
        for cell in row["cells"]:
            if cell.get("source_fact_id"):
                candidates[cell["source_fact_id"]].append((row["row_id"], cell))
    fact_to_row = {fact_id: matches[0] for fact_id, matches in candidates.items() if len(matches) == 1}
    relations, comparisons = [], []
    for entry in client.axis_manifest.get("reviews", []):
        if (entry["ticker"], entry["row_id"], entry["lens_id"]) != (ticker, lens.get("anchor_row_id"), lens["node_id"]):
            continue
        prepared = client._axis_json(entry["prepared_path"], entry["prepared_sha256"])
        comparisons.append(prepared["source_comparison"])
        for check in prepared["checks"]:
            ids = [check["parent_fact_id"], *check["child_fact_ids"]]
            matched = all(
                fact_id in fact_to_row
                and _cell_matches_binding(fact_to_row[fact_id][1], check["bindings"][fact_id])
                for fact_id in ids
            )
            relations.append(
                {
                    "review_id": entry["review_id"],
                    "validation_status": check["validation_status"],
                    "relationship_kind": check["relationship_kind"],
                    "structural_relationship": check["structural_relationship"],
                    "calculation_relationship": check["calculation_relationship"],
                    "display_scope": "ANALYTICAL_EXACT_MATCH" if matched else "SOURCE_COMPARISON_ONLY",
                    "parent_row_id": fact_to_row.get(check["parent_fact_id"], (total_id,))[0],
                    "child_row_ids": [fact_to_row[fact_id][0] for fact_id in check["child_fact_ids"]] if matched else [],
                    "parent_fact_id": check["parent_fact_id"],
                    "child_fact_ids": copy.deepcopy(check["child_fact_ids"]),
                    "weights": copy.deepcopy(check["weights"]),
                    "formula": check.get("formula"),
                    "parent_label": check.get("parent_label"),
                    "child_labels": copy.deepcopy(check.get("child_labels", [])),
                    "difference": check["difference"],
                    "period": copy.deepcopy(check["period"]),
                    "source_table_id": prepared["table"]["table_id"],
                    "reviewed_at": prepared["reviewed_at"],
                }
            )
    return relations, comparisons


def _cell_matches_binding(cell: dict[str, Any], binding: dict[str, Any]) -> bool:
    lineage = (cell.get("provenance") or {}).get("value_lineage") or {}
    unit = [_json_list(lineage.get("unit_numerator_measures")), _json_list(lineage.get("unit_denominator_measures"))]
    raw_dimensions = lineage.get("raw_dimension_signature") or []
    return (
        cell.get("source_fact_id") == binding["fact_id"]
        and str(cell.get("value")) == binding["value_numeric"]
        and cell.get("period_class") == binding["period"]["class"]
        and cell.get("start") == binding["period"]["start"]
        and cell.get("end") == binding["period"]["end"]
        and cell.get("status") == binding["status"] == "REPORTED"
        and lineage.get("source_filing_id") == binding["filing_id"]
        and lineage.get("accession") == binding["accession"]
        and lineage.get("raw_concept_id") == binding["raw_concept_id"]
        and unit == binding["unit"]
        and raw_dimensions == binding["raw_dimension_signature"]
    )


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise TypeError("prepared unit measure is not a list")
    return parsed


def _top_down(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_parent[row.get("parent_row_id")].append(row)
    for values in by_parent.values():
        values.sort(key=lambda row: (
            "reviewed_source_order" not in row,
            row.get("reviewed_source_order", 10**9),
            -max((p[0] * 4 + p[1] for p in row.get("observed_periods", [])), default=0),
            row.get("display_order", row.get("source_order", 10**9)), row["row_id"],
        ))
    result: list[dict[str, Any]] = []

    def visit(parent: str | None, depth: int) -> None:
        for row in by_parent.get(parent, []):
            row["depth"] = depth
            result.append(row)
            visit(row["row_id"], depth + 1)

    visit(None, 0)
    if len(result) != len(rows):
        raise ValueError("axis row hierarchy contains a cycle or orphan")
    return result


def load_axis_manifest(root: Path, analysis_manifest: dict[str, Any]) -> dict[str, Any] | None:
    path = root / "axis_timeseries_manifest.json"
    if path.is_symlink():
        raise ValueError("axis manifest cannot be a symlink")
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != "u3-axis-timeseries-v1" or manifest.get("source_publication_id") != analysis_manifest.get("publication_id"):
        raise ValueError("axis companion does not match analysis publication")
    actual = hashlib.sha256((root / "analysis_manifest.json").read_bytes()).hexdigest()
    if manifest.get("source_analysis_manifest_sha256") != actual:
        raise ValueError("axis companion analysis manifest checksum mismatch")
    return manifest
