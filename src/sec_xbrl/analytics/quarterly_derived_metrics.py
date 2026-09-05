"""Governed in-memory derived metrics over an already-built T6 pivot.

This is deliberately a consumer of the T6 adapter, not a selector.  It never
looks in Layer 1, reopens a filing, or uses labels/display order to find an
input.  An unsafe calculation is published as an auditable ``UNAVAILABLE``
record rather than omitted or filled.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from sec_xbrl.analytics.quarterly_analysis_pivot import QuarterlyAnalysisPivotResult

QUARTERLY_DERIVED_METRICS_VERSION = "derived-t7-quarterly-metrics-v1"
_FORMULA_VERSION = "1.0.0"
_REPORTED = frozenset({"REPORTED", "RECAST_REPORTED"})
_ROLE_QNAMES = {
    "REVENUE": "us-gaap:Revenues",
    "GROSS_PROFIT": "us-gaap:GrossProfit",
    "OPERATING_INCOME": "us-gaap:OperatingIncomeLoss",
}


@dataclass(frozen=True, slots=True)
class QuarterlyDerivedMetricsResult:
    """Separate immutable-looking records; the T6 input is never modified."""

    records: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class QuarterlyDerivedMetricsBuilder:
    """Calculate only the small, explicitly governed T7 metric set."""

    def build(self, *, pivot: QuarterlyAnalysisPivotResult) -> QuarterlyDerivedMetricsResult:
        columns = {str(column["quarterly_analysis_column_id"]): dict(column) for column in pivot.columns}
        cells_by_row: dict[str, dict[str, dict[str, Any]]] = {}
        for cell in pivot.cells:
            cells_by_row.setdefault(str(cell["quarterly_analysis_row_id"]), {})[
                str(cell["quarterly_analysis_column_id"])
            ] = dict(cell)
        records: list[dict[str, Any]] = []
        for row in pivot.rows:
            row_id = str(row["quarterly_analysis_row_id"])
            row_cells = cells_by_row.get(row_id, {})
            for column_id, column in columns.items():
                current = row_cells.get(column_id)
                records.append(
                    self._growth(
                        "QOQ_GROWTH", row, current, column, columns, row_cells, predecessor="QOQ"
                    )
                )
                records.append(
                    self._growth(
                        "YOY_GROWTH", row, current, column, columns, row_cells, predecessor="YOY"
                    )
                )
                parent = self._evidenced_parent(current, cells_by_row, column_id)
                if parent is not None:
                    records.append(self._share(row, current, parent, column))
        for column_id, column in columns.items():
            roles = self._role_cells(pivot, cells_by_row, column_id)
            revenue_candidates, revenue_error = roles["REVENUE"]
            gross_candidates, gross_error = roles["GROSS_PROFIT"]
            operating_candidates, operating_error = roles["OPERATING_INCOME"]
            revenue = revenue_candidates[0] if len(revenue_candidates) == 1 else None
            gross = gross_candidates[0] if len(gross_candidates) == 1 else None
            operating = operating_candidates[0] if len(operating_candidates) == 1 else None
            records.append(
                self._margin(
                    "GROSS_MARGIN",
                    gross,
                    revenue,
                    column,
                    input_error=gross_error or revenue_error,
                    considered=gross_candidates + revenue_candidates,
                )
            )
            records.append(
                self._margin(
                    "OPERATING_MARGIN",
                    operating,
                    revenue,
                    column,
                    input_error=operating_error or revenue_error,
                    considered=operating_candidates + revenue_candidates,
                )
            )
        return QuarterlyDerivedMetricsResult(
            records=tuple(sorted(records, key=lambda row: str(row["derived_metric_id"]))),
            scope={**deepcopy(pivot.scope), "quarterly_derived_metrics_version": QUARTERLY_DERIVED_METRICS_VERSION},
        )

    def _growth(
        self,
        metric: str,
        row: dict[str, Any],
        current: dict[str, Any] | None,
        column: dict[str, Any],
        columns: dict[str, dict[str, Any]],
        row_cells: dict[str, dict[str, Any]],
        *,
        predecessor: str,
    ) -> dict[str, Any]:
        prior_period = _predecessor(column, predecessor)
        prior_column = next(
            (
                item
                for item in columns.values()
                if (item["fiscal_year"], item["fiscal_quarter"]) == prior_period
            ),
            None,
        )
        if prior_column is None:
            return _unavailable(metric, column, (current,), "PREDECESSOR_PERIOD_NOT_DECLARED", row=row)
        prior = row_cells.get(str(prior_column["quarterly_analysis_column_id"]))
        return _ratio(
            metric,
            current,
            prior,
            column,
            row=row,
            numerator_name="current",
            denominator_name="declared_predecessor",
            subtract_one=True,
        )

    def _margin(
        self,
        metric: str,
        numerator: dict[str, Any] | None,
        revenue: dict[str, Any] | None,
        column: dict[str, Any],
        *,
        input_error: str | None,
        considered: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        if input_error is not None:
            numerator_role = "GROSS_PROFIT" if metric == "GROSS_MARGIN" else "OPERATING_INCOME"
            roles = (numerator_role,) * (len(considered) - (1 if revenue is not None else 0))
            # The considered sequence is numerator candidates followed by
            # revenue candidates.  When Revenue itself has multiple candidates,
            # all of them must be visible, not just an arbitrary first one.
            if revenue is None:
                role_count = sum(1 for item in considered if _standard_role_from_cell(item) == "REVENUE")
                roles = (numerator_role,) * (len(considered) - role_count) + ("REVENUE",) * role_count
            else:
                roles += ("REVENUE",)
            return _unavailable(metric, column, considered, input_error, row=None, input_roles=roles)
        return _ratio(
            metric,
            numerator,
            revenue,
            column,
            row=None,
            numerator_name="gross_profit" if metric == "GROSS_MARGIN" else "operating_income",
            denominator_name="revenue",
            subtract_one=False,
        )

    def _share(
        self,
        row: dict[str, Any],
        component: dict[str, Any] | None,
        parent: dict[str, Any],
        column: dict[str, Any],
    ) -> dict[str, Any]:
        return _ratio(
            "COMPONENT_SHARE",
            component,
            parent,
            column,
            row=row,
            numerator_name="component",
            denominator_name="evidenced_parent",
            subtract_one=False,
        )

    def _role_cells(
        self,
        pivot: QuarterlyAnalysisPivotResult,
        cells_by_row: dict[str, dict[str, dict[str, Any]]],
        column_id: str,
    ) -> dict[str, tuple[tuple[dict[str, Any], ...], str | None]]:
        found: dict[str, list[dict[str, Any]]] = {role: [] for role in _ROLE_QNAMES}
        for row in pivot.rows:
            role = _standard_role(row)
            if role is not None:
                cell = cells_by_row.get(str(row["quarterly_analysis_row_id"]), {}).get(column_id)
                if cell is not None:
                    found[role].append(cell)
        return {
            role: (tuple(values), None if len(values) <= 1 else "MULTIPLE_CANDIDATES")
            for role, values in found.items()
        }

    def _evidenced_parent(
        self,
        child: dict[str, Any] | None,
        cells_by_row: dict[str, dict[str, dict[str, Any]]],
        column_id: str,
    ) -> dict[str, Any] | None:
        if child is None:
            return None
        definition = child.get("definition") or {}
        parent_line_id = definition.get("parent_analysis_line_id")
        nav = (child.get("binding") or {}).get("relationship_navigation") or ()
        if not parent_line_id or not any(edge.get("edge_type") == "STATEMENT_COMPONENT" for edge in nav):
            return None
        # Same fiscal column and exact T5 parent line identity are both required;
        # label/order adjacency can never manufacture a hierarchy.
        candidates = [
            cell
            for row_cells in cells_by_row.values()
            for cell in row_cells.values()
            if str(cell.get("quarterly_analysis_column_id")) == column_id
            and str((cell.get("definition") or {}).get("analysis_line_id")) == str(parent_line_id)
        ]
        return candidates[0] if len(candidates) == 1 else None


def _predecessor(column: dict[str, Any], kind: str) -> tuple[int, int]:
    year, quarter = int(column["fiscal_year"]), int(column["fiscal_quarter"])
    if kind == "YOY":
        return year - 1, quarter
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _standard_role(row: dict[str, Any]) -> str | None:
    """Recognise roles only through fully qualified standard QName identity."""
    if not row.get("first_binding", {}).get("raw_concept_is_standard"):
        return None
    family = row.get("first_binding", {}).get("raw_concept_taxonomy_family")
    qname = row.get("first_binding", {}).get("raw_concept_qname") or row.get("raw_concept_qname")
    if family != "us-gaap":
        return None
    return next((role for role, expected in _ROLE_QNAMES.items() if qname == expected), None)


def _standard_role_from_cell(cell: dict[str, Any]) -> str | None:
    binding = cell.get("binding") or {}
    if not binding.get("raw_concept_is_standard") or binding.get("raw_concept_taxonomy_family") != "us-gaap":
        return None
    return next(
        (role for role, expected in _ROLE_QNAMES.items() if binding.get("raw_concept_qname") == expected),
        None,
    )


def _ratio(
    metric: str,
    numerator: dict[str, Any] | None,
    denominator: dict[str, Any] | None,
    column: dict[str, Any],
    *,
    row: dict[str, Any] | None,
    numerator_name: str,
    denominator_name: str,
    subtract_one: bool,
) -> dict[str, Any]:
    inputs = (numerator, denominator)
    input_roles = (numerator_name.upper(), denominator_name.upper())
    code = _compatibility_code(inputs)
    if code is not None:
        return _unavailable(metric, column, inputs, code, row=row, input_roles=input_roles)
    assert numerator is not None and denominator is not None
    try:
        top, bottom = Decimal(str(numerator["value_numeric"])), Decimal(str(denominator["value_numeric"]))
    except (InvalidOperation, TypeError, ValueError):
        return _unavailable(metric, column, inputs, "NON_DECIMAL_INPUT", row=row, input_roles=input_roles)
    if not top.is_finite() or not bottom.is_finite():
        return _unavailable(metric, column, inputs, "NON_FINITE_INPUT", row=row, input_roles=input_roles)
    if bottom == 0:
        return _unavailable(metric, column, inputs, "ZERO_DENOMINATOR", row=row, input_roles=input_roles)
    result = ((top / bottom) - Decimal(1) if subtract_one else top / bottom) * Decimal(100)
    return _record(
        metric,
        column,
        inputs,
        row=row,
        status="AVAILABLE",
        value=result,
        evaluation_status="CALCULATED",
        formula=f"({numerator_name} / {denominator_name}{' - 1' if subtract_one else ''}) * 100",
        input_roles=input_roles,
    )


def _compatibility_code(inputs: tuple[dict[str, Any] | None, ...]) -> str | None:
    if any(item is None for item in inputs):
        return "REQUIRED_INPUT_NOT_AVAILABLE"
    assert all(item is not None for item in inputs)
    cells = tuple(item for item in inputs if item is not None)
    if any(item.get("value_status") not in _REPORTED for item in cells):
        return "INPUT_NOT_REPORTED"
    if any((item.get("value_lineage") or {}).get("mapping_review_required") for item in cells):
        return "MAPPING_REVIEW_REQUIRED"
    lineages = tuple(item.get("value_lineage") or {} for item in cells)
    required = ("selection_view", "selection_as_of_date", "basis_version", "canonical_dimension_signature")
    if any(any(lineage.get(field) in (None, "") for field in required) for lineage in lineages):
        return "INCOMPLETE_GOVERNED_SCOPE"
    if len({repr(_unit(item)) for item in cells}) != 1:
        return "INCOMPATIBLE_UNIT"
    if len({repr(lineage["canonical_dimension_signature"]) for lineage in lineages}) != 1:
        return "INCOMPATIBLE_DIMENSIONS"
    if len({(lineage["selection_view"], lineage["selection_as_of_date"], lineage["basis_version"]) for lineage in lineages}) != 1:
        return "INCOMPATIBLE_SELECTION_SCOPE"
    if len({repr((lineage.get("concept_mapping_version"), lineage.get("dimension_mapping_ids"))) for lineage in lineages}) != 1:
        return "INCOMPATIBLE_MAPPING"
    if any(not _context_complete(lineage) for lineage in lineages):
        return "INCOMPLETE_CONTEXT"
    return None


def _unit(cell: dict[str, Any]) -> tuple[Any, Any]:
    lineage = cell.get("value_lineage") or {}
    return lineage.get("unit_numerator_measures"), lineage.get("unit_denominator_measures")


def _context_complete(lineage: dict[str, Any]) -> bool:
    return bool(lineage.get("context_id")) and bool(
        lineage.get("context_end_date") or lineage.get("context_instant_date")
    )


def _unavailable(
    metric: str,
    column: dict[str, Any],
    inputs: tuple[dict[str, Any] | None, ...],
    code: str,
    *,
    row: dict[str, Any] | None,
    input_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    return _record(
        metric,
        column,
        inputs,
        row=row,
        status="UNAVAILABLE",
        value=None,
        evaluation_status=code,
        formula=None,
        input_roles=input_roles,
    )


def _record(
    metric: str,
    column: dict[str, Any],
    inputs: tuple[dict[str, Any] | None, ...],
    *,
    row: dict[str, Any] | None,
    status: str,
    value: Decimal | None,
    evaluation_status: str,
    formula: str | None,
    input_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    input_cells = tuple(cell for cell in inputs if cell is not None)
    ordered_ids = tuple(str(cell["quarterly_analysis_cell_id"]) for cell in input_cells)
    lineage = tuple(
        {
            "input_role": input_roles[index] if index < len(input_roles) else "CONSIDERED_INPUT",
            "candidate_status": cell.get("value_status"),
            "quarterly_analysis_cell_id": cell["quarterly_analysis_cell_id"],
            "value_numeric": deepcopy(cell.get("value_numeric")),
            "value_lineage": deepcopy(cell.get("value_lineage")),
            "binding": deepcopy(cell.get("binding")),
        }
        for index, cell in enumerate(input_cells)
    )
    identity = (metric, _FORMULA_VERSION, column["quarterly_analysis_column_id"], row and row.get("quarterly_analysis_row_id"), ordered_ids)
    first_lineage = (input_cells[0].get("value_lineage") or {}) if input_cells else {}
    return {
        "derived_metric_id": "quarterly-derived:" + sha256(repr(identity).encode()).hexdigest()[:24],
        "metric_id": metric,
        "metric_definition_version": _FORMULA_VERSION,
        "formula_version": _FORMULA_VERSION,
        "formula": formula,
        "source_type": "DERIVED_METRIC",
        "evaluation_status": evaluation_status,
        "value_status": status,
        "value_percentage_points": value,
        "quarterly_analysis_column_id": column["quarterly_analysis_column_id"],
        "fiscal_year": column["fiscal_year"],
        "fiscal_quarter": column["fiscal_quarter"],
        "period_class": column["period_class"],
        "quarterly_analysis_row_id": row.get("quarterly_analysis_row_id") if row else None,
        "selection_view": first_lineage.get("selection_view"),
        "selection_as_of_date": first_lineage.get("selection_as_of_date"),
        "basis_version": first_lineage.get("basis_version"),
        "canonical_dimension_signature": deepcopy(first_lineage.get("canonical_dimension_signature")),
        "unit_semantics": deepcopy(_unit(input_cells[0])) if input_cells else None,
        "ordered_input_cell_ids": ordered_ids,
        "input_lineage": lineage,
    }
