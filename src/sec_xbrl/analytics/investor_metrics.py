"""Fiscal-panel adapter for the existing quarterly metric arithmetic.

This is a producer, never query-time calculation. Reported and approved derived
inputs retain their real types; missing basis/dimension/quality is not patched
to make an existing reported-only policy accept them.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sec_xbrl.analytics.quarterly_derived_metrics import _predecessor, percentage_result

VERSION = "investor-fiscal-metrics-v1"


def materialize_metrics(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {(c["row_id"], c["period_class"], c["fiscal_year"], c["fiscal_quarter"]): c for c in cells}
    result = []
    for current in cells:
        for metric, predecessor in (("YOY", "YOY"), ("QOQ", "QOQ")):
            year, quarter = _predecessor(current, predecessor)
            previous = index.get((current["row_id"], current["period_class"], year, quarter))
            result.append(ratio(current, previous, metric=metric, growth=True))
    for current in cells:
        role = {"gross_profit": "GROSS_MARGIN", "operating_income": "OPERATING_MARGIN"}.get(current["row_id"])
        if role:
            denominator = index.get(("revenue", current["period_class"], current["fiscal_year"], current["fiscal_quarter"]))
            result.append(ratio(current, denominator, metric=role, growth=False))
    return result


def ratio(current: dict, prior: dict | None, *, metric: str, growth: bool) -> dict:
    row = {"metric_id": metric, "row_id": current["row_id"], "column_id": current["column_id"],
           "fiscal_year": current["fiscal_year"], "fiscal_quarter": current["fiscal_quarter"],
           "period_class": current["period_class"], "value": None, "absolute_change": None,
           "unit": "PERCENT", "source_type": "DERIVED_METRIC", "status": "UNAVAILABLE",
           "rule_version": VERSION, "formula": "(current / prior - 1) * 100" if growth else "numerator / revenue * 100",
           "input_ids": [c["cell_id"] for c in (current, prior) if c], "reason": None}
    if prior is None or any(c["status"] not in {"REPORTED", "DERIVED"} or c["value"] is None for c in (current, prior)):
        row["reason"] = "REQUIRED_INPUT_NOT_AVAILABLE"
        return row
    if any(not c.get("monetary") or not c.get("unit") or any(v is None for v in c["unit"]) for c in (current, prior)):
        row["reason"] = "MONETARY_UNIT_REQUIRED"
        return row
    try:
        for c in (current, prior):
            numerator, denominator = [json.loads(v) if isinstance(v, str) else v for v in c["unit"]]
            if len(numerator) != 1 or not str(numerator[0]).startswith("iso4217:") or denominator:
                raise ValueError("currency")
    except (TypeError, ValueError):
        row["reason"] = "MONETARY_UNIT_REQUIRED"
        return row
    if not growth and (metric, current["row_id"], prior["row_id"]) not in {("GROSS_MARGIN", "gross_profit", "revenue"), ("OPERATING_MARGIN", "operating_income", "revenue")}:
        row["reason"] = "MARGIN_ROLE_PAIR_NOT_APPROVED"
        return row
    if current["period_class"] not in {"QTD_3M", "INSTANT"} or any(not c.get("end") or (c["period_class"] == "QTD_3M" and not c.get("start")) for c in (current, prior)):
        row["reason"] = "ACTUAL_PERIOD_REQUIRED"
        return row
    if not growth and not (set(current.get("statement_roles", [])) & set(prior.get("statement_roles", []))):
        row["reason"] = "SAME_PRIMARY_STATEMENT_REQUIRED"
        return row
    if not growth:
        statements = current.get("statement_evidence", {})
        other = prior.get("statement_evidence", {})
        if set(statements) != set(other) or any(not set(roles) & set(other.get(filing, [])) for filing, roles in statements.items()):
            row["reason"] = "STATEMENT_INPUT_LEG_MISMATCH"
            return row
    scope_field = "comparison_scope" if growth else "margin_scope"
    if any(c.get(scope_field) is None for c in (current, prior)):
        row["reason"] = "BASIS_NOT_APPROVED"
        return row
    for field in (scope_field, "unit", "period_class", "dimensions", "selection_view", "as_of", "ticker"):
        if current[field] != prior[field]:
            row["reason"] = "INCOMPATIBLE_" + field.upper()
            return row
    if growth and current["semantic_id"] != prior["semantic_id"]:
        row["reason"] = "DIFFERENT_REPORTED_DEFINITION"
        return row
    if growth and (prior["fiscal_year"], prior["fiscal_quarter"]) != _predecessor(current, metric):
        row["reason"] = "WRONG_FISCAL_PREDECESSOR"
        return row
    if growth:
        try:
            gap = (date.fromisoformat(current["end"])-date.fromisoformat(prior["end"])).days
            if not (330 <= gap <= 400 if metric == "YOY" else 75 <= gap <= 105):
                raise ValueError("fiscal transition")
        except (TypeError, ValueError):
            row["reason"] = "ACTUAL_PREDECESSOR_TRANSITION"
            return row
    if current.get("basis_version") != prior.get("basis_version"):
        row["reason"] = "DIFFERENT_REVIEWED_BASIS"
        return row
    if not growth and (current["start"] != prior["start"] or current["end"] != prior["end"]):
        row["reason"] = "INCOMPATIBLE_ACTUAL_PERIOD"
        return row
    try:
        top, bottom = Decimal(current["value"]), Decimal(prior["value"])
    except (InvalidOperation, TypeError):
        row["reason"] = "NON_NUMERIC_INPUT"
        return row
    if not top.is_finite() or not bottom.is_finite():
        row["reason"] = "NON_FINITE_INPUT"
        return row
    if growth:
        row["absolute_change"] = str(top-bottom)
    if bottom <= 0 or (growth and top < 0):
        row["reason"] = "ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE"
        row["transition"] = "LOSS_TO_PROFIT" if bottom < 0 <= top else "PROFIT_TO_LOSS" if bottom >= 0 > top else "NON_POSITIVE_BASE"
        return row
    row.update(value=str(percentage_result(top, bottom, subtract_one=growth)), status="AVAILABLE",
               source_basis_version=current.get("basis_version"),
               comparison_policy_version="reported-value-arithmetic-v1" if growth else "same-filing-margin-v1",
               comparability="REVIEWED_BASIS" if current.get("basis_version") else "REPORTED_VALUES_NOT_RECAST_VALIDATED",
               label="검토 기준 변화율" if current.get("basis_version") and growth else "공시값 산술 변화율" if growth else "동일 공시 이익률",
               comparison_evidence={"scope": current[scope_field], "input_semantic_ids": [current.get("semantic_id"), prior.get("semantic_id")],
                                    "input_periods": [[c.get("start"), c.get("end")] for c in (current, prior)]})
    if growth and current["period_class"] == "QTD_3M":
        days = [(date.fromisoformat(c["end"])-date.fromisoformat(c["start"])).days for c in (current, prior)]
        if not all(70 <= n <= 105 for n in days):
            row.update(value=None, status="UNAVAILABLE", reason="FISCAL_TRANSITION_DURATION")
        elif days[0] != days[1]:
            row["warning"] = "ACTUAL_DURATION_DIFFERS"
    return row
