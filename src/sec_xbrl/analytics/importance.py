"""Prepared, explainable importance evidence for investor-analysis branches.

This module is a producer.  Consumer queries may select and page its records,
but must never recalculate ranks, changes, shares, or accounting eligibility.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
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
    core_candidates: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for cell in core_cells:
        core_candidates[(cell["row_id"], cell["fiscal_year"], cell["fiscal_quarter"])].append(cell)
    core_by_row_period = {key: rows[0] for key, rows in core_candidates.items() if len(rows) == 1}
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
    if (any(not rule.get(key) for key in required)
            or rule.get("complete_mutually_exclusive") is not True
            or any(not isinstance(rule.get(key), str) or not rule[key].strip()
                   for key in required if key not in {"complete_mutually_exclusive", "bindings"})
            or not isinstance(rule.get("bindings"), list)
            or not _HEX_64.fullmatch(str(rule["evidence_sha256"]))):
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    try:
        reviewed_at = datetime.fromisoformat(str(rule["reviewed_at"]))
        cutoff = datetime.fromisoformat(review_cutoff) if review_cutoff else None
        if cutoff is None or reviewed_at.utcoffset() is None or cutoff.utcoffset() is None or reviewed_at > cutoff:
            raise ValueError("review requires an aware publication cutoff")
        evidence_path = Path(rule["evidence_path"])
        evidence_valid = evidence_path.is_file() and hashlib.sha256(evidence_path.read_bytes()).hexdigest() == rule["evidence_sha256"]
    except (ValueError, TypeError, OSError):
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    if not evidence_valid:
        return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
    by_period: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for binding in rule["bindings"]:
        if (not isinstance(binding, dict)
                or any(type(binding.get(key)) is not int for key in ("fiscal_year", "fiscal_quarter"))
                or binding["fiscal_quarter"] not in {1, 2, 3, 4}
                or any(not isinstance(binding.get(key), dict) for key in
                       ("child_cell_ids", "child_dimensions", "child_source_period_pairs"))):
            return {(period, child): _unavailable_share("INVALID_REVIEW_EVIDENCE") for period in periods for child in child_ids}
        by_period[(binding["fiscal_year"], binding["fiscal_quarter"])].append(binding)
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
        if _duplicate_values(list(cells.values()), trace_by_cell):
            for child in child_ids:
                output[(period, child)] = _unavailable_share("DUPLICATE_DECOMPOSITION_VALUE")
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
        if total != parent_amount:
            for child in child_ids:
                output[(period, child)] = _unavailable_share(
                    "NON_RECONCILING_DECOMPOSITION",
                    decomposition_review_id=rule["review_id"],
                    share_input_cell_ids=[parent_cell["cell_id"], cells[child]["cell_id"]],
                    share_parent_value=parent_cell["value"], share_child_value=cells[child]["value"],
                    share_child_total=str(total), share_total_difference=str(total - parent_amount),
                    share_reconciliation_inputs={cells[key]["cell_id"]: cells[key]["value"] for key in sorted(child_ids)},
                )
            continue
        for child, amount in amounts.items():
            assert amount is not None
            output[(period, child)] = {
                "parent_share": str((amount / parent_amount) * Decimal(100)),
                "share_status": "AVAILABLE",
                "share_reason": None,
                "share_warning": None,
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
    if not isinstance(inputs, list) or any(not isinstance(row, dict) for row in inputs):
        return [[None, None, None]]
    return sorted([[row.get("source_filing_id"), row.get("context_start_date"),
                    row.get("context_end_date") or row.get("context_instant_date")] for row in inputs], key=repr)


def _duplicate_values(cells: list[dict[str, Any]], traces: dict[str, dict[str, Any]]) -> bool:
    """Presentation aliases must not count the same underlying value twice."""
    seen: set[tuple[str, str]] = set()
    for cell in cells:
        lineage = traces.get(cell.get("cell_id"), {})
        inputs = lineage.get("source_inputs") or [lineage]
        identities = [("cell", str(cell.get("cell_id"))), ("value_node", str(cell.get("node_id")))]
        for source in inputs if isinstance(inputs, list) else []:
            if not isinstance(source, dict):
                continue
            if source.get("selected_source_fact_id"):
                identities.append(("fact", json.dumps([source.get("source_filing_id"), source["selected_source_fact_id"]])))
            concept = source.get("company_canonical_concept_id") or source.get("raw_concept_id")
            if concept:
                identities.append(("scope", json.dumps([
                    source.get("source_filing_id"), concept,
                    sorted(source.get("canonical_dimension_signature") or source.get("raw_dimension_signature") or [], key=repr),
                    source.get("context_start_date"), source.get("context_end_date"), source.get("context_instant_date"),
                    source.get("unit_numerator_measures"), source.get("unit_denominator_measures"),
                ], sort_keys=True)))
        if any(identity in seen for identity in identities):
            return True
        seen.update(identities)
    return False


def _complete_source_pairs(cell: dict[str, Any], pairs: list[list[Any]], trace_by_cell: dict[str, dict[str, Any]]) -> bool:
    if (not pairs or any(not isinstance(pair[0], str) or not pair[0] or not isinstance(pair[2], str) or not pair[2]
                         or pair[1] is not None and not isinstance(pair[1], str) for pair in pairs)
            or len({tuple(pair) for pair in pairs}) != len(pairs)):
        return False
    lineage = trace_by_cell.get(cell.get("cell_id"), {})
    try:
        end = date.fromisoformat(cell["end"])
        if cell.get("status") == "REPORTED":
            if len(pairs) != 1 or date.fromisoformat(pairs[0][2]) != end:
                return False
            if cell.get("period_class") == "INSTANT":
                return cell.get("start") is None and pairs[0][1] is None
            return date.fromisoformat(pairs[0][1]) == date.fromisoformat(cell["start"]) < end
        if cell.get("status") != "DERIVED" or cell.get("period_class") != "QTD_3M":
            return False
        inputs = lineage.get("source_inputs") or []
        quarter = cell.get("fiscal_quarter")
        expected = {2: ("YTD_6M", "QTD_3M"), 3: ("YTD_9M", "YTD_6M"), 4: ("FY", "YTD_9M")}.get(quarter)
        if len(inputs) != 2 or expected is None:
            return False
        later, earlier = inputs
        if tuple(row.get("period_class") for row in inputs) != expected or lineage.get("formula") != " - ".join(expected):
            return False
        core_approved = (lineage.get("derivation_rule_version") == "approved-core-cumulative-difference-v1"
                         and lineage.get("source_type") == "DERIVED_QUARTER"
                         and lineage.get("reported_or_derived") == "DERIVED"
                         and lineage.get("semantic_review_state") == "REVIEWED_ADDITIVE_AMOUNT"
                         and lineage.get("policy_registry") == "CONTROLLED_STANDARD_STATEMENT_ALLOWLIST")
        review_approved = (quarter == 4 and lineage.get("derivation_rule_version") == "disclosure-review-v1"
                           and lineage.get("source_type") == "DERIVED_METRIC"
                           and lineage.get("value_status") == "DERIVED"
                           and lineage.get("metric_id") == "QUARTERLY_ADDITIVE_FLOW"
                           and lineage.get("calculation_decision_id")
                           and lineage.get("compatibility_result") == "COMPATIBLE_INPUTS")
        if not (core_approved or review_approved):
            return False
        start = date.fromisoformat(cell["start"])
        if (later.get("context_start_date") != earlier.get("context_start_date")
                or not date.fromisoformat(later["context_start_date"]) < start
                or date.fromisoformat(earlier["context_end_date"]) != start
                or date.fromisoformat(later["context_end_date"]) != end
                or not 75 <= (end - start).days <= 105
                or (lineage.get("context_start_date"), lineage.get("context_end_date"), lineage.get("period_class"))
                != (cell["start"], cell["end"], cell["period_class"])):
            return False
        # Validate ordered input scope and arithmetic without inferring approval.
        scope = ("company_canonical_concept_id", "canonical_dimension_signature", "analytical_dimensions",
                 "unit_numerator_measures", "unit_denominator_measures", "selection_view", "selection_as_of_date",
                 "basis_version", "structural_version", "recast_version")
        if (not later.get("company_canonical_concept_id")
                or any(later.get(key) != earlier.get(key) for key in scope)
                or any(not row.get("selected_source_fact_id") or row.get("source_type") != "REPORTED"
                       or row.get("continuity_break") or row.get("recast_review_required") for row in inputs)):
            return False
        if not _derived_output_scope(cell, lineage, inputs):
            return False
        day_bounds = {"FY": (350, 378), "YTD_9M": (250, 290), "YTD_6M": (160, 200), "QTD_3M": (75, 105)}
        for row in inputs:
            days = (date.fromisoformat(row["context_end_date"]) - date.fromisoformat(row["context_start_date"])).days
            low, high = day_bounds[row["period_class"]]
            if not low <= days <= high:
                return False
            source_unit = [row.get("unit_numerator_measures"), row.get("unit_denominator_measures")]
            if _currency_unit({"monetary": True, "unit": source_unit}) != _currency_unit(cell):
                return False
            dimensions = row.get("analytical_dimensions") or row.get("canonical_dimension_signature") or []
            if dimensions != cell.get("dimensions"):
                return False
        values = [_decimal(row.get("value_numeric")) for row in inputs]
        return all(value is not None for value in values) and values[0] - values[1] == _amount(cell)
    except (KeyError, TypeError, ValueError):
        return False


def _derived_output_scope(cell: dict[str, Any], lineage: dict[str, Any], inputs: list[dict[str, Any]]) -> bool:
    """Bind governed source identity through its persisted output to the display cell."""
    # These are canonical/analytical fields. Raw concept and dimension IDs may
    # legitimately differ between filings and are never used as a mapped bridge.
    mapped = {"company_canonical_concept_id": "semantic_id", "selection_view": "selection_view",
              "selection_as_of_date": "as_of", "basis_version": "basis_version"}
    for source_key, cell_key in mapped.items():
        expected = cell.get(cell_key)
        if source_key != "basis_version" and not expected:
            return False
        if any(row.get(source_key) != expected for row in [lineage, *inputs]):
            return False
    if not lineage.get("cik"):
        return False
    for key in ("cik", "structural_version", "recast_version"):
        if any(row.get(key) != lineage.get(key) for row in inputs):
            return False
    for row in [lineage, *inputs]:
        if row.get("ticker") is not None and row["ticker"] != cell.get("ticker"):
            return False
        unit = [row.get("unit_numerator_measures"), row.get("unit_denominator_measures")]
        dimensions = row.get("analytical_dimensions") or row.get("canonical_dimension_signature") or []
        if (_currency_unit({"monetary": True, "unit": unit}) != _currency_unit(cell)
                or dimensions != cell.get("dimensions")):
            return False
    return True
