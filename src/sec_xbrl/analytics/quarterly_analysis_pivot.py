"""Read-only quarterly pivot over T5 company analysis panels.

T6 deliberately lays out already selected reported values.  It does not choose
facts, fill gaps, derive Q4, or calculate QoQ/YoY.  A row can span periods
only where the T5 lineage supplies a safe same-company semantic identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sec_xbrl.analytics.company_analysis_panel import CompanyAnalysisPanelResult

QUARTERLY_ANALYSIS_PIVOT_VERSION = "analysis-t6-quarterly-pivot-v1"


class QuarterlyAnalysisPivotError(ValueError):
    """Raised when a pivot would conflate incompatible T5 analytical rows."""


@dataclass(frozen=True, slots=True)
class QuarterlyAnalysisPivotResult:
    """A time-column layout with row and cell lineage kept separately."""

    columns: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]
    cells: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class QuarterlyAnalysisPivotBuilder:
    """Make a governed pivot from T5 results without analytical policy."""

    def build(
        self, *, panels: Iterable[CompanyAnalysisPanelResult]
    ) -> QuarterlyAnalysisPivotResult:
        prepared = tuple(panels)
        if not prepared:
            raise QuarterlyAnalysisPivotError("quarterly pivot requires at least one T5 panel")
        scope = _shared_scope(prepared)
        columns = _columns(prepared)
        row_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        cells: list[dict[str, Any]] = []
        occupied: set[tuple[str, str]] = set()
        for panel in prepared:
            definition_by_id = {str(row["analysis_line_id"]): row for row in panel.definitions}
            binding_by_id = {str(row["analysis_line_id"]): row for row in panel.bindings}
            for value in panel.values:
                line_id = str(value["analysis_line_id"])
                definition = definition_by_id.get(line_id)
                binding = binding_by_id.get(line_id)
                if definition is None or binding is None:
                    raise QuarterlyAnalysisPivotError("T5 value has no definition/binding lineage")
                _validate_cell_scope(panel.scope, value)
                row_key, review_required, reason = _row_key(panel.scope, definition, binding, value)
                row_id = _row_id(row_key)
                if row_key not in row_by_key:
                    row_by_key[row_key] = _row_metadata(
                        row_id,
                        row_key,
                        definition,
                        binding,
                        value,
                        review_required=review_required,
                        review_reason=reason,
                    )
                column_id = _column_id(panel.scope, value)
                collision = (row_id, column_id)
                if collision in occupied:
                    raise QuarterlyAnalysisPivotError(
                        "duplicate compatible T5 values collide in one pivot cell"
                    )
                occupied.add(collision)
                cells.append(
                    {
                        "quarterly_analysis_cell_id": _cell_id(row_id, column_id, value),
                        "quarterly_analysis_row_id": row_id,
                        "quarterly_analysis_column_id": column_id,
                        "value_status": value.get("value_status"),
                        "value_numeric": deepcopy(value.get("value_numeric")),
                        "value_text": deepcopy(value.get("value_text")),
                        "unavailable_reason": value.get("selection_unavailable_reason"),
                        # A pivot cell is an adapter, never a replacement for its
                        # T5 fact, selection, ledger, mapping, or graph evidence.
                        "definition": deepcopy(definition),
                        "binding": deepcopy(binding),
                        "value_lineage": deepcopy(value),
                    }
                )
        return QuarterlyAnalysisPivotResult(
            columns=tuple(sorted(columns, key=lambda row: row["column_order_key"])),
            rows=tuple(sorted(row_by_key.values(), key=_row_order)),
            cells=tuple(
                sorted(
                    cells,
                    key=lambda row: (
                        row["quarterly_analysis_row_id"],
                        row["quarterly_analysis_column_id"],
                    ),
                )
            ),
            scope={**scope, "quarterly_analysis_pivot_version": QUARTERLY_ANALYSIS_PIVOT_VERSION},
        )


class QuarterlyAnalysisPivotQuery:
    """Defensive, read-only query API for a T6 pivot matrix."""

    def __init__(self, pivot: QuarterlyAnalysisPivotResult) -> None:
        self._pivot = deepcopy(pivot)

    def matrix(self) -> tuple[dict[str, Any], ...]:
        """Return rows with an explicit unavailable/gap cell for every column."""
        by_coordinate = {
            (
                str(cell["quarterly_analysis_row_id"]),
                str(cell["quarterly_analysis_column_id"]),
            ): cell
            for cell in self._pivot.cells
        }
        result: list[dict[str, Any]] = []
        for row in self._pivot.rows:
            rendered = []
            for column in self._pivot.columns:
                cell = by_coordinate.get(
                    (
                        str(row["quarterly_analysis_row_id"]),
                        str(column["quarterly_analysis_column_id"]),
                    )
                )
                rendered.append(
                    deepcopy(cell)
                    if cell is not None
                    else {
                        "quarterly_analysis_row_id": row["quarterly_analysis_row_id"],
                        "quarterly_analysis_column_id": column["quarterly_analysis_column_id"],
                        "value_status": "UNAVAILABLE",
                        "unavailable_reason": "NO_T5_PANEL_VALUE_FOR_PERIOD",
                        "value_numeric": None,
                        "value_text": None,
                    }
                )
            result.append({"row": deepcopy(row), "cells": tuple(rendered)})
        return tuple(result)


def _shared_scope(panels: tuple[CompanyAnalysisPanelResult, ...]) -> dict[str, Any]:
    required = ("cik", "period_class", "selection_view", "selection_as_of_date")
    first = dict(panels[0].scope)
    if any(first.get(key) in (None, "") for key in required):
        raise QuarterlyAnalysisPivotError("T5 panel is missing complete query scope")
    for panel in panels[1:]:
        for key in required:
            if panel.scope.get(key) != first.get(key):
                raise QuarterlyAnalysisPivotError(
                    "T6 cannot mix company, period class, selection view, or as-of date"
                )
    return {key: first[key] for key in required}


def _columns(panels: tuple[CompanyAnalysisPanelResult, ...]) -> tuple[dict[str, Any], ...]:
    seen: dict[str, dict[str, Any]] = {}
    for panel in panels:
        scope = panel.scope
        _require_scope_period(scope)
        probe = panel.values[0] if panel.values else {}
        column_id = _column_id(scope, probe)
        column = {
            "quarterly_analysis_column_id": column_id,
            "fiscal_year": scope["fiscal_year"],
            "fiscal_quarter": scope["fiscal_quarter"],
            "period_class": scope["period_class"],
            "context_start_date": probe.get("context_start_date"),
            "context_end_date": probe.get("context_end_date"),
            "context_instant_date": probe.get("context_instant_date"),
            "column_order_key": (scope["fiscal_year"], scope["fiscal_quarter"]),
        }
        prior = seen.get(column_id)
        if prior is not None and prior != column:
            raise QuarterlyAnalysisPivotError(
                "same fiscal column has incompatible actual date boundaries"
            )
        seen[column_id] = column
    # A fiscal period label must not conceal two distinct actual periods.
    labels = [(row["fiscal_year"], row["fiscal_quarter"]) for row in seen.values()]
    if len(labels) != len(set(labels)):
        raise QuarterlyAnalysisPivotError(
            "same fiscal year/quarter has multiple T5 panel period identities"
        )
    return tuple(seen.values())


def _column_id(scope: Mapping[str, Any], value: Mapping[str, Any]) -> str:
    # T5 scope is authoritative; actual dates are retained in every cell but
    # cannot be reliably inferred from a panel containing unavailable rows.
    return _stable_id(
        "column", scope["fiscal_year"], scope["fiscal_quarter"], scope["period_class"]
    )


def _row_key(
    scope: Mapping[str, Any],
    definition: Mapping[str, Any],
    binding: Mapping[str, Any],
    value: Mapping[str, Any],
) -> tuple[tuple[Any, ...], bool, str | None]:
    unit = _unit_semantics(value)
    dimensions = _freeze(value.get("canonical_dimension_signature") or ())
    standard = bool(value.get("raw_concept_is_standard"))
    review = bool(value.get("mapping_review_required"))
    canonical_concept = value.get("company_canonical_concept_id")
    confirmed_concept = bool(
        canonical_concept
        and value.get("concept_mapping_id")
        and value.get("concept_mapping_version")
        and not review
    )
    complete_dimensions = _complete_dimensions(dimensions)
    raw_dimensions = _freeze(value.get("raw_dimension_signature") or ())
    confirmed_dimensions = not raw_dimensions or (
        complete_dimensions and bool(value.get("dimension_mapping_ids")) and not review
    )
    common = definition.get("line_class") == "COMMON_GAAP"
    if common and standard and unit is not None and complete_dimensions and not review:
        # Standard identity is QName + family, never a local name.  A confirmed
        # canonical ID is preferred, while exact standard identity remains a
        # permitted qualified fallback under the L2 mapping contract.
        concept = (
            ("CANONICAL", canonical_concept)
            if confirmed_concept
            else (
                "QUALIFIED_STANDARD",
                value.get("raw_concept_taxonomy_family"),
                value.get("raw_concept_qname"),
            )
        )
        if all(concept):
            return (
                (
                    "JOIN",
                    scope["cik"],
                    definition.get("line_scope"),
                    definition.get("line_kind"),
                    concept,
                    dimensions,
                    unit,
                    scope["period_class"],
                ),
                False,
                None,
            )
    if not common and confirmed_concept and confirmed_dimensions and unit is not None:
        return (
            (
                "JOIN",
                scope["cik"],
                definition.get("line_scope"),
                definition.get("line_kind"),
                ("CANONICAL", canonical_concept),
                dimensions,
                unit,
                scope["period_class"],
            ),
            False,
            None,
        )
    # A filing/period-specific fallback makes the uncertainty visible and can
    # never bridge periods just because labels or local names happen to match.
    reason = (
        "MAPPING_REVIEW_REQUIRED"
        if review or not confirmed_concept or not confirmed_dimensions
        else "MISSING_COMPATIBLE_UNIT_SEMANTICS"
    )
    return (
        (
            "REVIEW",
            scope["cik"],
            scope["fiscal_year"],
            scope["fiscal_quarter"],
            value.get("source_filing_id"),
            value.get("selected_source_fact_id"),
            binding.get("analysis_binding_id"),
        ),
        True,
        reason,
    )


def _row_metadata(
    row_id: str,
    row_key: tuple[Any, ...],
    definition: Mapping[str, Any],
    binding: Mapping[str, Any],
    value: Mapping[str, Any],
    *,
    review_required: bool,
    review_reason: str | None,
) -> dict[str, Any]:
    return {
        "quarterly_analysis_row_id": row_id,
        "row_identity": deepcopy(row_key),
        "label": definition.get("label"),
        "line_class": definition.get("line_class"),
        "line_scope": definition.get("line_scope"),
        "line_kind": definition.get("line_kind"),
        "mapping_review_required": review_required,
        "review_reason": review_reason,
        "raw_concept_qname": value.get("raw_concept_qname"),
        "company_canonical_concept_id": value.get("company_canonical_concept_id"),
        "canonical_dimension_signature": deepcopy(value.get("canonical_dimension_signature")),
        "unit_numerator_measures": deepcopy(value.get("unit_numerator_measures")),
        "unit_denominator_measures": deepcopy(value.get("unit_denominator_measures")),
        "first_definition": deepcopy(definition),
        "first_binding": deepcopy(binding),
    }


def _validate_cell_scope(scope: Mapping[str, Any], value: Mapping[str, Any]) -> None:
    for scope_key, value_key in (
        ("selection_view", "selection_view"),
        ("selection_as_of_date", "selection_as_of_date"),
    ):
        if value.get(value_key) != scope.get(scope_key):
            raise QuarterlyAnalysisPivotError(
                "T5 cell selection provenance disagrees with its panel scope"
            )


def _require_scope_period(scope: Mapping[str, Any]) -> None:
    if (
        not isinstance(scope.get("fiscal_year"), int)
        or scope["fiscal_year"] < 1
        or scope.get("fiscal_quarter") not in {1, 2, 3, 4}
    ):
        raise QuarterlyAnalysisPivotError("T6 requires a fiscal-year and fiscal-quarter T5 panel")


def _unit_semantics(value: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    numerator = value.get("unit_numerator_measures")
    denominator = value.get("unit_denominator_measures")
    if numerator is None and denominator is None:
        return None
    return (_measures(numerator), _measures(denominator))


def _measures(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(sorted(part.strip() for part in value.split() if part.strip()))
    return tuple(sorted(str(part) for part in value))


def _complete_dimensions(dimensions: Any) -> bool:
    return all(
        isinstance(item, tuple)
        and len(item) >= 3
        and item[0] is not None
        and (item[1] is not None or item[2] is not None)
        for item in dimensions
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _stable_id(prefix: str, *parts: Any) -> str:
    import hashlib

    return f"quarterly-analysis:{prefix}:{hashlib.sha256(repr(parts).encode()).hexdigest()[:24]}"


def _row_id(key: tuple[Any, ...]) -> str:
    return _stable_id("row", key)


def _cell_id(row_id: str, column_id: str, value: Mapping[str, Any]) -> str:
    return _stable_id("cell", row_id, column_id, value.get("analysis_line_value_id"))


def _row_order(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        bool(row.get("mapping_review_required")),
        str(row.get("label") or ""),
        str(row["quarterly_analysis_row_id"]),
    )
