"""Prepared, explainable importance evidence for investor-analysis branches.

This module is a producer.  Consumer queries may select and page its records,
but must never recalculate ranks, changes, shares, or accounting eligibility.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.investor_metrics import ratio

POLICY_ID = "important-financial-items"
POLICY_VERSION = "u3-important-items-v1"
DEFAULT_TOP = 5
_HEX_64 = re.compile(r"[0-9a-f]{64}")


def materialize_importance(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    core_cells: list[dict[str, Any]],
    configuration: dict[str, Any] | None = None,
    review_cutoff: str | None = None,
    traces: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Materialize period ranks and independent importance reason evidence."""
    configuration = configuration or {}
    trace_by_cell = {row["cell_id"]: row.get("value_lineage", {}) for row in traces or []}
    node_by_id = {row["node_id"]: row for row in nodes}
    value_node = {key: value.get("value_node_id") or key for key, value in node_by_id.items()}
    cell_by_node_period: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        cell_by_node_period[(cell["node_id"], cell["fiscal_year"], cell["fiscal_quarter"])].append(cell)
    core_by_row_period = {(c["row_id"], c["fiscal_year"], c["fiscal_quarter"]): c for c in core_cells}
    children: dict[str, set[str]] = defaultdict(set)
    edge_periods: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    for edge in edges:
        children[edge["parent_id"]].add(edge["child_id"])
        edge_periods[(edge["parent_id"], edge["child_id"])].update(tuple(p) for p in edge["periods"])

    pinned = set(configuration.get("pinned_nodes", []))
    excluded = set(configuration.get("excluded_nodes", []))
    unknown = (pinned | excluded) - set(node_by_id)
    if unknown:
        raise ValueError("importance display configuration references an unknown exact node")

    records: list[dict[str, Any]] = []
    for parent_id, child_ids in children.items():
        parent = node_by_id[parent_id]
        all_periods = sorted({period for child_id in child_ids for period in edge_periods[(parent_id, child_id)]})
        period_cells: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
        for period in all_periods:
            selected: dict[str, dict[str, Any]] = {}
            for child_id in child_ids:
                if period not in edge_periods[(parent_id, child_id)]:
                    continue
                candidates = cell_by_node_period.get((value_node[child_id], *period), [])
                if len(candidates) == 1:
                    selected[child_id] = candidates[0]
            period_cells[period] = selected

        amount_ranks: dict[tuple[int, int], dict[str, int]] = {}
        parent_cells_by_period: dict[tuple[int, int], dict[str, Any] | None] = {}
        change_ranks: dict[tuple[int, int], dict[str, int]] = {}
        changes: dict[tuple[int, int], dict[str, dict[str, Any]]] = defaultdict(dict)
        for period in all_periods:
            current = period_cells[period]
            parent_cell = _parent_cell(parent, parent_id, period, value_node, cell_by_node_period, core_by_row_period)
            parent_cells_by_period[period] = parent_cell
            parent_unit = _currency_unit(parent_cell)
            parent_period_class = parent_cell.get("period_class") if parent_cell else None
            comparable: dict[str, Decimal] = {}
            for child_id, cell in current.items():
                amount = _amount(cell)
                if amount is not None and parent_unit is not None and _currency_unit(cell) == parent_unit and cell.get("period_class") == parent_period_class:
                    comparable[child_id] = abs(amount)
            amount_ranks[period] = _ranks(comparable)
            deltas: dict[str, Decimal] = {}
            for child_id, cell in current.items():
                previous = period_cells.get(_previous_period(period), {}).get(child_id)
                change = ratio(cell, previous, metric="YOY", growth=True)
                changes[period][child_id] = change
                if child_id in comparable and change.get("absolute_change") is not None and change.get("reason") is None:
                    try:
                        deltas[child_id] = abs(Decimal(str(change["absolute_change"])))
                    except InvalidOperation:
                        pass
            change_ranks[period] = _ranks(deltas)

        share_rows = _reviewed_shares(
            parent_id=parent_id,
            child_ids=child_ids,
            parent=parent,
            periods=all_periods,
            period_cells=period_cells,
            core_by_row_period=core_by_row_period,
            rules=configuration.get("economic_decompositions", []),
            review_cutoff=review_cutoff,
            trace_by_cell=trace_by_cell,
            parent_cells_by_period=parent_cells_by_period,
        )
        for period in all_periods:
            for child_id in sorted(child_ids):
                cell = period_cells[period].get(child_id)
                amount_rank = amount_ranks[period].get(child_id)
                change = changes[period].get(child_id, {})
                change_rank = change_ranks[period].get(child_id)
                reasons: list[str] = []
                warnings: list[str] = []
                if amount_rank is not None and amount_rank <= DEFAULT_TOP:
                    reasons.append("TOP_AMOUNT")
                if change_rank is not None and change_rank <= DEFAULT_TOP:
                    reasons.append("TOP_AMOUNT_CHANGE")
                rate = _decimal(change.get("value"))
                if rate is not None and abs(rate) >= Decimal(50):
                    previous_rank = amount_ranks.get(_previous_period(period), {}).get(child_id)
                    if previous_rank is not None and previous_rank > DEFAULT_TOP:
                        warnings.append("SMALL_BASE_HIGH_RATE")
                    if change_rank is not None and change_rank <= DEFAULT_TOP:
                        reasons.append("ABRUPT_RATE_AND_MATERIAL_CHANGE")
                transition = change.get("transition")
                if transition in {"LOSS_TO_PROFIT", "PROFIT_TO_LOSS"}:
                    reasons.append("SIGN_TRANSITION")
                    warnings.append(transition)
                basis_breaks = {"DIFFERENT_REVIEWED_BASIS", "DIFFERENT_REPORTED_DEFINITION",
                                "INCOMPATIBLE_COMPARISON_SCOPE", "INCOMPATIBLE_SELECTION_SCOPE"}
                if change.get("reason") in {"BASIS_NOT_APPROVED", *basis_breaks}:
                    warnings.append(change["reason"])
                    if change.get("reason") in basis_breaks:
                        reasons.append("BASIS_WARNING")
                if change.get("warning"):
                    warnings.append(change["warning"])
                source_reason = str(cell.get("reason") or "") if cell else ""
                if any(token in source_reason.upper() for token in ("BLOCK", "QUARANTINE", "REVIEW_REQUIRED")):
                    reasons.append("CRITICAL_SOURCE_WARNING")
                    warnings.append(source_reason)
                if child_id in pinned:
                    reasons.append("USER_PINNED")
                if node_by_id[child_id].get("kind") == "STRUCTURAL" and children.get(child_id):
                    reasons.append("STRUCTURAL_NAVIGATION")
                records.append({
                    "policy_id": POLICY_ID,
                    "policy_version": POLICY_VERSION,
                    "parent_id": parent_id,
                    "child_id": child_id,
                    "fiscal_year": period[0],
                    "fiscal_quarter": period[1],
                    "present": cell is not None,
                    "amount_rank": amount_rank,
                    "amount_change_rank": change_rank,
                    "rate_change": change.get("value"),
                    "absolute_change": change.get("absolute_change"),
                    "change_status": change.get("status"),
                    "change_reason": change.get("reason"),
                    "change_comparability": change.get("comparability"),
                    "change_warning": change.get("warning"),
                    "change_input_ids": list(change.get("input_ids", [])),
                    "current_cell_id": cell.get("cell_id") if cell else None,
                    "reasons": sorted(set(reasons)),
                    "warnings": sorted(set(warnings)),
                    "pinned": child_id in pinned,
                    "presentation_excluded": child_id in excluded,
                    **share_rows.get((period, child_id), _unavailable_share("NO_REVIEWED_ECONOMIC_DECOMPOSITION")),
                })
    return records


def _amount(cell: dict[str, Any]) -> Decimal | None:
    if cell.get("status") not in {"REPORTED", "DERIVED"} or cell.get("value") is None or _currency_unit(cell) is None:
        return None
    try:
        amount = Decimal(str(cell["value"]))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def _currency_unit(cell: dict[str, Any] | None) -> tuple[str] | None:
    if not cell or not cell.get("monetary"):
        return None
    unit = cell.get("unit")
    if not isinstance(unit, list) or len(unit) != 2 or any(value is None for value in unit):
        return None
    try:
        numerator, denominator = [json.loads(value) if isinstance(value, str) else value for value in unit]
    except (TypeError, ValueError):
        return None
    if not isinstance(numerator, list) or len(numerator) != 1 or not str(numerator[0]).startswith("iso4217:") or denominator != []:
        return None
    return (str(numerator[0]),)


def _parent_cell(parent: dict[str, Any], parent_id: str, period: tuple[int, int], value_node: dict[str, str],
                 cell_by_node_period: dict[tuple[str, int, int], list[dict[str, Any]]],
                 core_by_row_period: dict[tuple[str, int, int], dict[str, Any]]) -> dict[str, Any] | None:
    if parent.get("kind") == "LENS":
        return core_by_row_period.get((parent.get("anchor_row_id"), *period))
    candidates = cell_by_node_period.get((value_node[parent_id], *period), [])
    return candidates[0] if len(candidates) == 1 else None


def _ranks(values: dict[str, Decimal]) -> dict[str, int]:
    return {node_id: rank for rank, (node_id, _) in enumerate(sorted(values.items(), key=lambda row: (-row[1], row[0])), 1)}


def _previous_period(period: tuple[int, int]) -> tuple[int, int]:
    return period[0] - 1, period[1]


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _unavailable_share(reason: str, **extra: Any) -> dict[str, Any]:
    return {"parent_share": None, "share_status": "UNAVAILABLE", "share_reason": reason, **extra}


def _reviewed_shares(
    *, parent_id: str, child_ids: set[str], parent: dict[str, Any], periods: list[tuple[int, int]],
    period_cells: dict[tuple[int, int], dict[str, dict[str, Any]]],
    core_by_row_period: dict[tuple[str, int, int], dict[str, Any]], rules: list[dict[str, Any]],
    review_cutoff: str | None, trace_by_cell: dict[str, dict[str, Any]],
    parent_cells_by_period: dict[tuple[int, int], dict[str, Any] | None],
) -> dict[tuple[tuple[int, int], str], dict[str, Any]]:
    """Validate exact reviewed decomposition bindings and calculate their shares."""
    output: dict[tuple[tuple[int, int], str], dict[str, Any]] = {}
    matching = [rule for rule in rules if rule.get("parent_node_id") == parent_id]
    if len(matching) > 1:
        return {(period, child): _unavailable_share("DUPLICATE_DECOMPOSITION_REVIEW") for period in periods for child in child_ids}
    if not matching:
        return output
    rule = matching[0]
    required = ("review_id", "reviewer", "reviewed_at", "evidence_path", "evidence_sha256", "classification_basis", "complete_mutually_exclusive", "bindings")
    if any(not rule.get(key) for key in required) or not _HEX_64.fullmatch(str(rule["evidence_sha256"])):
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    try:
        reviewed_at = datetime.fromisoformat(str(rule["reviewed_at"]))
        cutoff = datetime.fromisoformat(review_cutoff) if review_cutoff else None
        evidence_path = Path(rule["evidence_path"])
        evidence_valid = evidence_path.is_file() and hashlib.sha256(evidence_path.read_bytes()).hexdigest() == rule["evidence_sha256"]
    except (ValueError, TypeError):
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    if not rule["complete_mutually_exclusive"] or not evidence_valid or (cutoff and reviewed_at > cutoff):
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    by_period: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for binding in rule["bindings"]:
        by_period[(int(binding["fiscal_year"]), int(binding["fiscal_quarter"]))].append(binding)
    for period in periods:
        bindings = by_period.get(period, [])
        if len(bindings) != 1:
            reason = "DUPLICATE_PERIOD_DECOMPOSITION" if len(bindings) > 1 else "INCOMPLETE_DECOMPOSITION"
            for child in child_ids:
                output[(period, child)] = _unavailable_share(reason)
            continue
        binding = bindings[0]
        cells = period_cells[period]
        bound_children = binding.get("child_cell_ids", {})
        if set(bound_children) != child_ids or set(cells) != child_ids:
            for child in child_ids:
                output[(period, child)] = _unavailable_share("INCOMPLETE_DECOMPOSITION")
            continue
        parent_cell = parent_cells_by_period.get(period)
        if parent_cell is None or parent_cell.get("cell_id") != binding.get("parent_cell_id"):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("PARENT_BINDING_MISMATCH")
            continue
        if any(cells[child].get("cell_id") != bound_children.get(child) for child in child_ids):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("CHILD_BINDING_MISMATCH")
            continue
        required_binding = ("parent_dimensions", "child_dimensions", "parent_source_period_pairs", "child_source_period_pairs",
                            "actual_start", "actual_end", "period_class", "classification_basis")
        if any(key not in binding for key in required_binding) or binding["classification_basis"] != rule["classification_basis"]:
            for child in child_ids:
                output[(period, child)] = _unavailable_share("INCOMPLETE_ECONOMIC_SCOPE")
            continue
        if parent_cell.get("dimensions") != binding["parent_dimensions"] or any(cells[child].get("dimensions") != binding["child_dimensions"].get(child) for child in child_ids):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("DIMENSION_SCOPE_MISMATCH")
            continue
        if (parent_cell.get("start"), parent_cell.get("end"), parent_cell.get("period_class")) != (binding["actual_start"], binding["actual_end"], binding["period_class"]):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("PERIOD_MISMATCH")
            continue
        if any((cells[child].get("start"), cells[child].get("end"), cells[child].get("period_class")) != (binding["actual_start"], binding["actual_end"], binding["period_class"]) for child in child_ids):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("PERIOD_MISMATCH")
            continue
        parent_pairs = _source_period_pairs(parent_cell, trace_by_cell)
        child_pairs = {child: _source_period_pairs(cells[child], trace_by_cell) for child in child_ids}
        if (not _complete_source_pairs(parent_cell, parent_pairs, trace_by_cell)
                or any(not _complete_source_pairs(cells[child], child_pairs[child], trace_by_cell) for child in child_ids)
                or parent_pairs != binding["parent_source_period_pairs"]
                or any(child_pairs[child] != binding["child_source_period_pairs"].get(child) for child in child_ids)
                or any(child_pairs[child] != parent_pairs for child in child_ids)):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("SOURCE_PERIOD_PAIR_MISMATCH")
            continue
        parent_amount = _amount(parent_cell)
        if parent_amount is None:
            reason = "PARENT_NIL_OR_NON_MONETARY"
        elif parent_amount <= 0:
            reason = "ZERO_OR_NEGATIVE_PARENT"
        else:
            reason = ""
        parent_scope = tuple(parent_cell.get(k) for k in ("unit", "period_class", "basis_version", "selection_view", "as_of", "ticker"))
        child_scopes = [tuple(cells[child].get(k) for k in ("unit", "period_class", "basis_version", "selection_view", "as_of", "ticker")) for child in child_ids]
        if not reason and any(scope != parent_scope for scope in child_scopes):
            fields = ("unit", "period_class", "basis_version", "selection_view", "as_of", "ticker")
            differing = next(fields[i] for i in range(len(fields)) if any(scope[i] != parent_scope[i] for scope in child_scopes))
            reason = {"unit": "UNIT_MISMATCH", "period_class": "PERIOD_MISMATCH", "basis_version": "BASIS_MISMATCH"}.get(differing, "SELECTION_SCOPE_MISMATCH")
        amounts = {child: _amount(cells[child]) for child in child_ids}
        if not reason and any(value is None for value in amounts.values()):
            reason = "CHILD_NIL_OR_NON_MONETARY"
        if not reason and any(value < 0 for value in amounts.values() if value is not None):
            reason = "OFFSET_CHILD"
        if reason:
            for child in child_ids:
                output[(period, child)] = _unavailable_share(reason)
            continue
        assert parent_amount is not None and all(value is not None for value in amounts.values())
        total = sum((value for value in amounts.values() if value is not None), Decimal(0))
        for child, amount in amounts.items():
            assert amount is not None
            output[(period, child)] = {
                "parent_share": str((amount / parent_amount) * Decimal(100)),
                "share_status": "AVAILABLE",
                "share_reason": None,
                "share_warning": "CHILDREN_EXCEED_PARENT" if total > parent_amount else None,
                "decomposition_review_id": rule["review_id"],
                "decomposition_evidence_sha256": rule["evidence_sha256"],
                "share_formula": "child / reviewed economic parent * 100",
                "share_input_cell_ids": [parent_cell["cell_id"], cells[child]["cell_id"]],
                "share_source_period_pairs": {"parent": parent_pairs, "child": child_pairs[child]},
                "share_classification_basis": rule["classification_basis"],
                "share_reviewed_at": rule["reviewed_at"],
                "share_reviewer": rule["reviewer"],
            }
    return output


def _source_period_pairs(cell: dict[str, Any], trace_by_cell: dict[str, dict[str, Any]]) -> list[list[Any]]:
    lineage = trace_by_cell.get(cell.get("cell_id"), {})
    inputs = lineage.get("source_inputs") or [lineage]
    return sorted([[row.get("source_filing_id"), row.get("context_start_date"),
                    row.get("context_end_date") or row.get("context_instant_date")] for row in inputs], key=repr)


def _complete_source_pairs(cell: dict[str, Any], pairs: list[list[Any]], trace_by_cell: dict[str, dict[str, Any]]) -> bool:
    if not pairs or any(pair[0] in (None, "") or pair[2] in (None, "") for pair in pairs) or len({tuple(pair) for pair in pairs}) != len(pairs):
        return False
    if cell.get("period_class") == "INSTANT":
        if any(pair[1] not in (None, "") for pair in pairs):
            return False
    elif any(pair[1] in (None, "") for pair in pairs):
        return False
    lineage = trace_by_cell.get(cell.get("cell_id"), {})
    return not (cell.get("status") == "DERIVED" and len(lineage.get("source_inputs") or []) < 2)
