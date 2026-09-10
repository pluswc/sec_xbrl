"""Additive publication for prepared axis time-series review evidence."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

AXIS_TIMESERIES_VERSION = "u3-axis-timeseries-v1"


@dataclass(frozen=True)
class AxisReviewInput:
    ticker: str
    row_id: str
    lens_id: str
    review_path: Path
    source_panel_path: Path


def prepare_axis_timeseries(
    *,
    source_bundle: Path,
    destination: Path,
    reviews: tuple[AxisReviewInput, ...] = (),
) -> Path:
    """Copy an attested analysis bundle and add exact, bounded axis reviews."""
    unresolved_source = Path(source_bundle)
    if unresolved_source.is_symlink():
        raise ValueError("source bundle cannot be a symlink")
    source_bundle = unresolved_source.resolve()
    destination = Path(destination)
    if destination.exists():
        raise ValueError("source must be a real bundle and destination must be new")
    if source_bundle == destination.resolve() or source_bundle in destination.resolve().parents:
        raise ValueError("destination cannot be inside the source bundle")
    if any(path.is_symlink() for path in source_bundle.rglob("*")):
        raise ValueError("source bundle cannot contain symlinks")
    if (source_bundle / "axis_timeseries_manifest.json").exists() or (source_bundle / "axis_reviews").exists():
        raise ValueError("axis companion input cannot already contain axis review data")
    analysis_manifest_path = source_bundle / "analysis_manifest.json"
    analysis_manifest = json.loads(analysis_manifest_path.read_text(encoding="utf-8"))
    _verify_manifest_files(source_bundle, analysis_manifest)
    from sec_xbrl.analysis import AnalysisClient

    source_client = AnalysisClient(source_bundle)

    prepared_reviews: list[dict[str, Any]] = []
    inputs = []
    review_scopes = set()
    latest_review = datetime.min.replace(tzinfo=UTC)
    for supplied in reviews:
        review_bytes = Path(supplied.review_path).read_bytes()
        panel_bytes = Path(supplied.source_panel_path).read_bytes()
        review = json.loads(review_bytes)
        panel = json.loads(panel_bytes)
        scope = (supplied.ticker.upper(), supplied.row_id, supplied.lens_id)
        if scope in review_scopes:
            raise ValueError("duplicate axis review scope")
        review_scopes.add(scope)
        inputs.append((review_bytes, panel_bytes, review, panel))
        reviewed_at = _aware(review.get("reviewed_at"), "reviewed_at")
        latest_review = max(latest_review, reviewed_at)
        _validate_review(
            review,
            panel,
            publication_id=analysis_manifest["publication_id"],
            attested_panel=source_client.statement(supplied.ticker, review["table_id"]),
        )
        lens = next(
            (
                node
                for node in source_client._records(supplied.ticker.upper(), "LATEST_REPORTED", "nodes")
                if node.get("node_id") == supplied.lens_id
            ),
            None,
        )
        if (
            lens is None
            or lens.get("kind") != "LENS"
            or lens.get("lens_type") != "DIMENSIONAL_VIEW"
            or lens.get("anchor_row_id") != supplied.row_id
            or [review["axis"]] != (lens.get("dimensions") or [])
        ):
            raise ValueError("review does not match the prepared metric/axis lens")
        review_id = _stable(
            supplied.ticker.upper(), supplied.row_id, supplied.lens_id, hashlib.sha256(review_bytes).hexdigest()
        )
        prepared_reviews.append(
            {
                "review_id": review_id,
                "ticker": supplied.ticker.upper(),
                "row_id": supplied.row_id,
                "lens_id": supplied.lens_id,
                "axis_qname": review["axis"],
                "reviewed_at": review["reviewed_at"],
                "review_path": f"axis_reviews/{review_id}.json",
                "review_sha256": hashlib.sha256(review_bytes).hexdigest(),
                "source_panel_path": f"axis_reviews/{review_id}.source_panel.json",
                "source_panel_sha256": hashlib.sha256(panel_bytes).hexdigest(),
                "prepared_path": f"axis_reviews/{review_id}.prepared.json",
            }
        )

    staging = destination.parent / f".partial-axis-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source_bundle, staging)
        review_dir = staging / "axis_reviews"
        review_dir.mkdir()
        for (review_bytes, panel_bytes, review, panel), entry in zip(inputs, prepared_reviews, strict=True):
            (staging / entry["review_path"]).write_bytes(review_bytes)
            (staging / entry["source_panel_path"]).write_bytes(panel_bytes)
            prepared = _prepared_review(entry, review, panel)
            prepared_bytes = (json.dumps(prepared, ensure_ascii=False, indent=2) + "\n").encode()
            (staging / entry["prepared_path"]).write_bytes(prepared_bytes)
            entry["prepared_sha256"] = hashlib.sha256(prepared_bytes).hexdigest()
        decision_cutoff = datetime.now(UTC)
        if decision_cutoff < latest_review:
            raise ValueError("axis decision cutoff cannot predate a review")
        companion = {
            "version": AXIS_TIMESERIES_VERSION,
            "publication_id": uuid.uuid4().hex,
            "source_publication_id": analysis_manifest["publication_id"],
            "source_analysis_manifest_sha256": hashlib.sha256(
                analysis_manifest_path.read_bytes()
            ).hexdigest(),
            "decision_cutoff": decision_cutoff.isoformat(),
            "reviews": prepared_reviews,
        }
        (staging / "axis_timeseries_manifest.json").write_text(
            json.dumps(companion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return destination


def _verify_manifest_files(root: Path, manifest: dict[str, Any]) -> None:
    seen: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                relative = value["path"]
                if relative in seen:
                    if seen[relative] != value["sha256"]:
                        raise ValueError("conflicting prepared dataset attestations")
                    return
                seen[relative] = value["sha256"]
                path = root / relative
                if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
                    raise ValueError(f"missing or unsafe prepared dataset: {relative}")
                if hashlib.sha256(path.read_bytes()).hexdigest() != value["sha256"]:
                    raise ValueError(f"prepared dataset checksum mismatch: {relative}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(manifest)


def _validate_review(
    review: dict[str, Any],
    panel: dict[str, Any],
    *,
    publication_id: str,
    attested_panel: dict[str, Any],
) -> None:
    if review.get("status") != "LEAD_APPROVED_EXACT_SOURCE_COMPOSITION_AND_DISPLAY":
        raise ValueError("axis review is not approved for exact source display")
    table = panel.get("table") or {}
    expected = {
        "table_id": review.get("table_id"),
        "table_locator": review.get("table_locator"),
        "table_sha256": review.get("table_sha256"),
        "source_document_sha256": review.get("source_document_sha256"),
    }
    if panel.get("publication_id") != publication_id or any(table.get(k) != v for k, v in expected.items()):
        raise ValueError("review and prepared source panel identity disagree")
    if panel != attested_panel:
        raise ValueError("supplied source panel does not equal the attested prepared statement")
    if (table.get("filing") or {}).get("accession") != review.get("accession"):
        raise ValueError("review accession does not match source panel")
    if len({row["fact_id"] for row in panel.get("facts", [])}) != len(panel.get("facts", [])):
        raise ValueError("prepared source panel has duplicate fact identity")
    if len({row["row_id"] for row in panel.get("rows", [])}) != len(panel.get("rows", [])):
        raise ValueError("prepared source panel has duplicate row identity")
    if len({row["source_order"] for row in panel.get("rows", [])}) != len(panel.get("rows", [])):
        raise ValueError("prepared source panel has duplicate source order")
    facts = {row["fact_id"]: row for row in panel.get("facts", [])}
    row_facts = {
        row["source_order"]: {
            fact["fact_id"] for cell in row.get("cells", []) for fact in cell.get("inline_facts", [])
        }
        for row in panel.get("rows", [])
    }
    if not review.get("checks") or not str(review.get("reviewer") or "").strip():
        raise ValueError("review needs an explicit reviewer and equations")
    seen_checks = set()
    for check in review["checks"]:
        signature = check["parent_fact_id"]
        if signature in seen_checks:
            raise ValueError("duplicate review equation")
        seen_checks.add(signature)
        if check["period"].get("class") != "QTD_3M" or check["period"].get("type") != "duration":
            raise ValueError("review approves only reported QTD duration equations")
        if not check["child_fact_ids"] or any(str(w) != "1" for w in check["weights"]) or str(check["difference"]) != "0":
            raise ValueError("review requires exact unweighted zero-difference composition")
        ids = [check["parent_fact_id"], *check["child_fact_ids"]]
        if len(ids) != len(set(ids)) or any(fact_id not in facts for fact_id in ids):
            raise ValueError("review equation has missing or duplicate fact identity")
        if check["parent_fact_id"] not in row_facts.get(check["parent_row"], set()):
            raise ValueError("review parent row binding mismatch")
        if any(fid not in row_facts.get(row, set()) for fid, row in zip(check["child_fact_ids"], check["child_rows"], strict=True)):
            raise ValueError("review child row binding mismatch")
        if any(_period(facts[fact_id]) != check["period"] for fact_id in ids):
            raise ValueError("review equation period mismatch")
        scoped = [facts[fact_id] for fact_id in ids]
        first = scoped[0]
        for fact in scoped:
            scope = fact["scope"]
            if (fact["filing_id"] != table["filing_id"]
                or fact["filing"] != table["filing"]
                or scope["filing_id"] != table["filing_id"]
                or scope["cik"] != table["filing"]["cik"]
                or any(scope.get(k) != first["scope"].get(k) for k in ("view", "as_of", "basis"))
                or scope.get("view") != "RAW_AS_FILED"
                or fact["raw_concept_id"] != first["raw_concept_id"]
                or fact["reported_or_derived"] != "REPORTED"
                or fact["source_document"] != table["source_document"]):
                raise ValueError("review equation mixes source/concept/full scope")
        units = [_unit(fact) for fact in scoped]
        if any(unit != units[0] for unit in units[1:]):
            raise ValueError("review equation mixes unit scopes")
        if any(fact.get("is_nil") or fact.get("value_numeric") is None for fact in scoped):
            raise ValueError("review equation contains nil or nonnumeric input")
        child_dimensions = [_dimensions(facts[fact_id]) for fact_id in check["child_fact_ids"]]
        if len(child_dimensions) != len(set(child_dimensions)):
            raise ValueError("review repeats a dimensional scope")
        if any(len(dimensions) != 1 or dimensions[0][0] != review["axis"] for dimensions in child_dimensions):
            raise ValueError("review child scope must contain only the approved axis")
        parent_dimensions = _dimensions(facts[check["parent_fact_id"]])
        if parent_dimensions in child_dimensions:
            raise ValueError("review repeats parent dimensional scope")
        if parent_dimensions and (len(parent_dimensions) != 1 or parent_dimensions[0][0] != review["axis"]):
            raise ValueError("review parent scope contains an unapproved axis")
        parent = Decimal(str(facts[check["parent_fact_id"]]["value_numeric"]))
        values = [parent, *(Decimal(str(facts[fact_id]["value_numeric"])) for fact_id in check["child_fact_ids"])]
        if any(not value.is_finite() for value in values):
            raise ValueError("review equation contains nonfinite value")
        children = sum(
            Decimal(weight) * Decimal(str(facts[fact_id]["value_numeric"]))
            for fact_id, weight in zip(check["child_fact_ids"], check["weights"], strict=True)
        )
        if children - parent != Decimal(str(check["difference"])):
            raise ValueError("review equation does not match exact prepared values")


def _prepared_review(entry: dict[str, Any], review: dict[str, Any], panel: dict[str, Any]) -> dict[str, Any]:
    facts = {fact["fact_id"]: fact for fact in panel["facts"]}
    row_labels = {row["source_order"]: row["label"] for row in panel["rows"]}
    periods = sorted({(check["period"]["start"], check["period"]["end"]) for check in review["checks"]})
    cell_by_row_period: dict[tuple[int, tuple[str, str]], str] = {}
    parent_rows: dict[int, int | None] = {}
    checks = []
    for check in review["checks"]:
        period = (check["period"]["start"], check["period"]["end"])
        cell_by_row_period[(check["parent_row"], period)] = check["parent_fact_id"]
        for row, fact_id in zip(check["child_rows"], check["child_fact_ids"], strict=True):
            cell_by_row_period[(row, period)] = fact_id
            previous = parent_rows.get(row)
            if previous is not None and previous != check["parent_row"]:
                raise ValueError("review source row has conflicting parents")
            parent_rows[row] = check["parent_row"]
        parent_rows.setdefault(check["parent_row"], None)
        checks.append(
            {
                **check,
                "validation_status": "MATCH",
                "relationship_kind": "REVIEWED_SOURCE_ECONOMIC_SUM",
                "structural_relationship": False,
                "calculation_relationship": False,
                "parent_label": row_labels[check["parent_row"]],
                "child_labels": [row_labels[row] for row in check["child_rows"]],
                "formula": row_labels[check["parent_row"]] + " = " + " + ".join(row_labels[row] for row in check["child_rows"]),
                "bindings": {
                    fact_id: _fact_binding(facts[fact_id])
                    for fact_id in [check["parent_fact_id"], *check["child_fact_ids"]]
                },
            }
        )
    source_rows = []
    all_rows = {row for row, _ in cell_by_row_period}
    child_rows = {row for check in review["checks"] for row in check["child_rows"]}
    roots = all_rows - child_rows
    if not roots:
        raise ValueError("review graph has no source root")
    ordered_source_rows = sorted(roots)
    pending = set(all_rows) - roots
    while pending:
        added = [row for row in sorted(pending) if parent_rows.get(row) in ordered_source_rows]
        if not added:
            raise ValueError("review graph contains a cycle or orphan")
        for parent in list(ordered_source_rows):
            children = [row for row in added if parent_rows.get(row) == parent]
            if children:
                insert_at = ordered_source_rows.index(parent) + 1
                while insert_at < len(ordered_source_rows) and parent_rows.get(ordered_source_rows[insert_at]) == parent:
                    insert_at += 1
                ordered_source_rows[insert_at:insert_at] = children
                pending.difference_update(children)
    for source_order in ordered_source_rows:
        source_rows.append(
            {
                "row_id": f"source:{entry['review_id']}:{source_order}",
                "source_order": source_order,
                "label": row_labels[source_order],
                "parent_row_id": f"source:{entry['review_id']}:{parent_rows[source_order]}" if parent_rows.get(source_order) is not None else None,
                "cells": [
                    {
                        "status": "REPORTED",
                        "source_scope": "SOURCE_SCOPED_AS_FILED",
                        "period": {"start": start, "end": end, "class": "QTD_3M"},
                        "fact": facts[cell_by_row_period[(source_order, (start, end))]] if (source_order, (start, end)) in cell_by_row_period else None,
                    }
                    for start, end in periods
                ],
            }
        )
    return {
        "review_id": entry["review_id"],
        "reviewed_at": review["reviewed_at"],
        "axis_qname": review["axis"],
        "table": panel["table"],
        "checks": checks,
        "source_comparison": {
            "review_id": entry["review_id"],
            "scope": "SOURCE_SCOPED_AS_FILED",
            "columns": [{"period_class": "QTD_3M", "start": start, "end": end} for start, end in periods],
            "rows": _top_down_source(source_rows),
            "table": panel["table"],
            "warnings": ["SOURCE_COMPARISON_DOES_NOT_REPLACE_PREPARED_HISTORICAL_SELECTION"],
        },
    }


def _top_down_source(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(row.get("parent_row_id"), []).append(row)
    result: list[dict[str, Any]] = []

    def visit(parent: str | None, depth: int) -> None:
        for row in sorted(by_parent.get(parent, []), key=lambda item: item["source_order"]):
            row["depth"] = depth
            result.append(row)
            visit(row["row_id"], depth + 1)

    visit(None, 0)
    if len(result) != len(rows):
        raise ValueError("prepared source hierarchy is incomplete")
    return result


def _period(fact: dict[str, Any]) -> dict[str, Any]:
    period = fact["scope"]["period"]
    return {key: period.get(key) for key in ("class", "end", "instant", "start", "type")}


def _unit(fact: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    unit = fact["scope"]["unit"]
    return tuple(unit.get("numerator") or ()), tuple(unit.get("denominator") or ())


def _dimensions(fact: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            dimension.get("axis_qname"),
            dimension.get("member_qname"),
            dimension.get("typed_value"),
            dimension.get("dimension_type"),
            bool(dimension.get("is_default")),
        )
        for dimension in fact["scope"].get("dimensions", [])
    )


def _fact_binding(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": fact["fact_id"],
        "filing_id": fact["filing_id"],
        "accession": fact["filing"]["accession"],
        "value_numeric": str(fact["value_numeric"]),
        "period": _period(fact),
        "unit": [list(part) for part in _unit(fact)],
        "dimensions": [list(part) for part in _dimensions(fact)],
        "raw_dimension_signature": [
            [
                dimension.get("axis"),
                dimension.get("member"),
                dimension.get("typed_value"),
                "EXPLICIT" if dimension.get("member") else "TYPED",
                str(bool(dimension.get("is_default"))).lower(),
            ]
            for dimension in fact["scope"].get("dimensions", [])
        ],
        "raw_concept_id": fact["raw_concept_id"],
        "status": fact["reported_or_derived"],
    }


def _aware(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _stable(*parts: Any) -> str:
    encoded = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]
