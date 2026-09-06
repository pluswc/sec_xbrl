"""Company-internal fiscal time-series serving model.

This is deliberately downstream of T4-B/T5: it lays out already selected
observations and does not discover filings, choose a recast, calculate a
metric, or normalize a 53-week year.  Fiscal labels are the primary columns;
the real context boundaries remain first-class evidence on every column/cell.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from sec_xbrl.analytics.company_analysis_panel import CompanyAnalysisPanelResult

FISCAL_TIME_SERIES_VERSION = "analysis-company-fiscal-timeseries-v1"
_PERIOD_CLASSES = frozenset({"QTD_3M", "YTD_6M", "YTD_9M", "FY", "INSTANT", "OTHER_DURATION"})


class FiscalTimeSeriesError(ValueError):
    """Raised when a time-series request would hide incompatible history."""


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    """A requested fiscal column; absent panels become explicit history gaps."""

    fiscal_year: int
    fiscal_quarter: int | None
    period_class: str

    def __post_init__(self) -> None:
        if self.fiscal_year < 1 or self.period_class not in _PERIOD_CLASSES:
            raise FiscalTimeSeriesError("fiscal period requires a valid year and period class")
        if self.fiscal_quarter is not None and self.fiscal_quarter not in {1, 2, 3, 4}:
            raise FiscalTimeSeriesError("fiscal quarter must be 1 through 4 when supplied")


@dataclass(frozen=True, slots=True)
class FiscalTimeSeriesInput:
    """A selected T5 panel plus DEI fiscal metadata from its raw filing.

    ``fiscal_year_end`` is the as-filed DEI value (normally ``--MM-DD``).
    It is intentionally passed in rather than inferred from a revenue fact;
    without it automatic cross-year calendar comparability is fail-closed.
    """

    panel: CompanyAnalysisPanelResult
    fiscal_year_end: str | None


@dataclass(frozen=True, slots=True)
class FiscalTimeSeriesResult:
    """Pivot rows and cells with fiscal-calendar and selection provenance."""

    columns: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]
    cells: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class FiscalTimeSeriesBuilder:
    """Build a single-company, single-period-class fiscal pivot.

    The caller may request historical columns that have no source panel.  Such
    columns are represented, but no row/value is fabricated: each existing
    analytical row receives a ``MISSING_HISTORY`` cell with provenance-free
    value fields set to ``None``.
    """

    def build(
        self,
        *,
        inputs: Iterable[FiscalTimeSeriesInput],
        expected_periods: Sequence[FiscalPeriod] = (),
    ) -> FiscalTimeSeriesResult:
        prepared = tuple(inputs)
        if not prepared:
            raise FiscalTimeSeriesError("time series requires at least one selected panel")
        scope = _shared_scope(prepared)
        expected = tuple(expected_periods)
        _validate_expected(expected, scope["period_class"])
        columns = _annotate_comparability(
            tuple(sorted(_columns(prepared, expected), key=lambda item: item["column_order_key"]))
        )
        rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        cells: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        column_by_period = {
            (item["fiscal_year"], item["fiscal_quarter"], item["period_class"]): item
            for item in columns
        }
        for item in prepared:
            panel = item.panel
            period = (panel.scope["fiscal_year"], panel.scope["fiscal_quarter"], panel.scope["period_class"])
            column = column_by_period[period]
            definitions = {str(row["analysis_line_id"]): row for row in panel.definitions}
            bindings = {str(row["analysis_line_id"]): row for row in panel.bindings}
            for value in panel.values:
                line_id = str(value["analysis_line_id"])
                definition, binding = definitions.get(line_id), bindings.get(line_id)
                if definition is None or binding is None:
                    raise FiscalTimeSeriesError("T5 value has no definition/binding lineage")
                _validate_value_scope(value, panel.scope)
                _validate_derived_q4(value, panel.scope)
                key = _row_key(definition, binding, value)
                row_id = _id("row", key)
                rows.setdefault(row_id, _row(row_id, key, definition, binding, value))
                coordinate = (row_id, str(column["fiscal_time_series_column_id"]))
                if coordinate in seen:
                    raise FiscalTimeSeriesError("duplicate selected values collide in one fiscal cell")
                seen.add(coordinate)
                cells.append(_cell(row_id, column, definition, binding, value))
        result = FiscalTimeSeriesResult(
            columns=columns,
            rows=tuple(sorted(rows.values(), key=_row_order)),
            cells=tuple(sorted(cells, key=lambda item: (item["fiscal_time_series_row_id"], item["fiscal_time_series_column_id"]))),
            scope={**scope, "fiscal_time_series_version": FISCAL_TIME_SERIES_VERSION},
        )
        return result


class FiscalTimeSeriesQuery:
    """Defensive matrix reader which makes missing history explicit."""

    def __init__(self, result: FiscalTimeSeriesResult) -> None:
        self._result = deepcopy(result)

    def matrix(self) -> tuple[dict[str, Any], ...]:
        existing = {(str(cell["fiscal_time_series_row_id"]), str(cell["fiscal_time_series_column_id"])): cell for cell in self._result.cells}
        rendered = []
        for row in self._result.rows:
            cells = []
            for column in self._result.columns:
                cell = existing.get((str(row["fiscal_time_series_row_id"]), str(column["fiscal_time_series_column_id"])))
                cells.append(deepcopy(cell) if cell is not None else _missing_cell(row, column))
            rendered.append({"row": deepcopy(row), "cells": tuple(cells)})
        return tuple(rendered)


def _shared_scope(inputs: tuple[FiscalTimeSeriesInput, ...]) -> dict[str, Any]:
    first = inputs[0].panel.scope
    required = ("cik", "period_class", "selection_view", "selection_as_of_date")
    if any(first.get(field) in (None, "") for field in required):
        raise FiscalTimeSeriesError("T5 panel lacks complete company, period, view, or as-of scope")
    if first["period_class"] not in _PERIOD_CLASSES:
        raise FiscalTimeSeriesError("unknown period class")
    for item in inputs[1:]:
        scope = item.panel.scope
        if any(scope.get(field) != first.get(field) for field in required):
            raise FiscalTimeSeriesError("time series cannot mix company, period class, view, or as-of date")
    return {field: first[field] for field in required}


def _validate_expected(periods: tuple[FiscalPeriod, ...], period_class: str) -> None:
    seen = set()
    for period in periods:
        if period.period_class != period_class:
            raise FiscalTimeSeriesError("requested columns cannot mix QTD, YTD, FY, or instant period classes")
        key = (period.fiscal_year, period.fiscal_quarter, period.period_class)
        if key in seen:
            raise FiscalTimeSeriesError("requested fiscal columns cannot repeat")
        seen.add(key)


def _columns(inputs: tuple[FiscalTimeSeriesInput, ...], expected: tuple[FiscalPeriod, ...]) -> tuple[dict[str, Any], ...]:
    by_period: dict[tuple[int, int | None, str], dict[str, Any]] = {}
    for item in inputs:
        scope = item.panel.scope
        period = (scope["fiscal_year"], scope["fiscal_quarter"], scope["period_class"])
        evidence = _period_evidence(item.panel)
        column = _column(period, item.fiscal_year_end, evidence)
        previous = by_period.get(period)
        if previous is not None and previous != column:
            raise FiscalTimeSeriesError("one fiscal label has incompatible actual period evidence")
        by_period[period] = column
    for period in expected:
        key = (period.fiscal_year, period.fiscal_quarter, period.period_class)
        by_period.setdefault(key, _missing_column(key))
    return tuple(by_period.values())


def _period_evidence(panel: CompanyAnalysisPanelResult) -> dict[str, Any]:
    reported = [row for row in panel.values if row.get("value_status") == "REPORTED"]
    if not reported:
        return {"actual_start_date": None, "actual_end_date": None, "actual_instant_date": None, "duration_days": None}
    boundaries = {
        (row.get("context_start_date"), row.get("context_end_date"), row.get("context_instant_date"))
        for row in reported
    }
    # A T5 exploration panel may contain valid disclosure details with a
    # different context boundary from the statement anchor.  Never choose one
    # by label/order and silently apply it to the whole fiscal column.
    if len(boundaries) != 1:
        return {
            "actual_start_date": None, "actual_end_date": None, "actual_instant_date": None,
            "duration_days": None, "actual_period_boundaries": tuple(sorted(boundaries)),
            "period_evidence_status": "MULTIPLE_ACTUAL_PERIOD_BOUNDARIES",
        }
    start, end, instant = next(iter(boundaries))
    return {
        "actual_start_date": start, "actual_end_date": end, "actual_instant_date": instant,
        "duration_days": _duration(start, end), "actual_period_boundaries": tuple(sorted(boundaries)),
        "period_evidence_status": "ONE_ACTUAL_PERIOD_BOUNDARY",
    }


def _column(period: tuple[int, int | None, str], fiscal_year_end: str | None, evidence: Mapping[str, Any]) -> dict[str, Any]:
    fy, fq, period_class = period
    anchor = _fiscal_anchor(fiscal_year_end)
    # The month is stable across a normally rolling 52/53-week calendar.  The
    # actual day remains evidence and its difference is evaluated separately.
    version = f"DEI_FYE_MONTH:{anchor[:2]}" if anchor else "UNKNOWN_DEI_FYE"
    return {
        "fiscal_time_series_column_id": _id("column", period),
        "fiscal_year": fy, "fiscal_quarter": fq, "period_class": period_class,
        "fiscal_label": f"FY{fy}" + (f" Q{fq}" if fq is not None else ""),
        "actual_start_date": evidence["actual_start_date"], "actual_end_date": evidence["actual_end_date"],
        "actual_instant_date": evidence["actual_instant_date"], "duration_days": evidence["duration_days"],
        "actual_period_boundaries": deepcopy(evidence.get("actual_period_boundaries", ())),
        "period_evidence_status": evidence.get("period_evidence_status", "ONE_ACTUAL_PERIOD_BOUNDARY"),
        "fiscal_year_end_as_filed": fiscal_year_end, "fiscal_calendar_version": version,
        "column_status": "AVAILABLE", "column_reason": None,
        "column_order_key": (fy, fq is None, fq or 0, period_class),
    }


def _missing_column(period: tuple[int, int | None, str]) -> dict[str, Any]:
    fy, fq, period_class = period
    return {
        "fiscal_time_series_column_id": _id("column", period), "fiscal_year": fy, "fiscal_quarter": fq,
        "period_class": period_class, "fiscal_label": f"FY{fy}" + (f" Q{fq}" if fq is not None else ""),
        "actual_start_date": None, "actual_end_date": None, "actual_instant_date": None, "duration_days": None,
        "actual_period_boundaries": (), "period_evidence_status": "MISSING_HISTORY",
        "fiscal_year_end_as_filed": None, "fiscal_calendar_version": "UNKNOWN_DEI_FYE",
        "column_status": "MISSING_HISTORY", "column_reason": "NO_SELECTED_PANEL_FOR_REQUESTED_FISCAL_PERIOD",
        "column_order_key": (fy, fq is None, fq or 0, period_class),
    }


def _annotate_comparability(columns: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Attach a visible, non-calculating comparison gate to every column."""
    previous: dict[str, Any] | None = None
    result: list[dict[str, Any]] = []
    for source in columns:
        column = dict(source)
        if column["column_status"] != "AVAILABLE":
            status, reason = "NOT_COMPARABLE", column["column_reason"]
        elif previous is None:
            status, reason = "BASELINE", None
        elif column["period_evidence_status"] != "ONE_ACTUAL_PERIOD_BOUNDARY" or previous["period_evidence_status"] != "ONE_ACTUAL_PERIOD_BOUNDARY":
            status, reason = "REVIEW_REQUIRED", "MULTIPLE_ACTUAL_PERIOD_BOUNDARIES"
        elif "UNKNOWN_DEI_FYE" in {column["fiscal_calendar_version"], previous["fiscal_calendar_version"]}:
            status, reason = "REVIEW_REQUIRED", "MISSING_DEI_FISCAL_YEAR_END"
        elif column["fiscal_calendar_version"] != previous["fiscal_calendar_version"]:
            status, reason = "REVIEW_REQUIRED", "FISCAL_CALENDAR_VERSION_CHANGE"
        elif column["duration_days"] is None or previous["duration_days"] is None:
            status, reason = "REVIEW_REQUIRED", "MISSING_ACTUAL_DURATION"
        else:
            difference = abs(int(column["duration_days"]) - int(previous["duration_days"]))
            if difference == 7:
                status, reason = "DURATION_EXCEPTION_53_WEEK", "ACTUAL_DURATION_DIFFERS_BY_7_DAYS_NO_NORMALIZATION"
            elif difference > 7:
                status, reason = "REVIEW_REQUIRED", "ACTUAL_DURATION_DIFFERS_BY_MORE_THAN_7_DAYS"
            else:
                status, reason = "COMPARABLE", None
        column["comparability_status"], column["comparability_reason"] = status, reason
        if column["column_status"] == "AVAILABLE": previous = column
        result.append(column)
    return tuple(result)


def _row_key(definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> tuple[Any, ...]:
    # T6's strict key is retained: both common GAAP and mapped company custom
    # detail can continue, while reviewed/unmapped facts cannot merge by label.
    review = bool(value.get("mapping_review_required"))
    canonical = value.get("company_canonical_concept_id")
    dimensions = _freeze(value.get("canonical_dimension_signature") or ())
    unit = _freeze((value.get("unit_numerator_measures"), value.get("unit_denominator_measures")))
    # T4's fiscal label is filing metadata.  A filing can also contain prior
    # comparative contexts under that label.  The upstream comparative class
    # is the safe separator; without one the actual boundary remains scoped.
    comparative = value.get("comparative_type")
    boundaries = (value.get("context_start_date"), value.get("context_end_date"), value.get("context_instant_date"))
    family = ("COMPARATIVE", comparative) if comparative else ("UNCLASSIFIED_BOUNDARY", boundaries)
    if canonical and not review and unit != (None, None):
        return ("JOIN", definition.get("line_class"), definition.get("line_scope"), definition.get("line_kind"), canonical, dimensions, unit, family)
    return ("REVIEW", value.get("source_filing_id"), value.get("selected_source_fact_id"), binding.get("analysis_binding_id"))


def _row(row_id: str, key: tuple[Any, ...], definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fiscal_time_series_row_id": row_id, "row_identity": deepcopy(key), "label": definition.get("label"),
        "line_class": definition.get("line_class"), "line_scope": definition.get("line_scope"), "line_kind": definition.get("line_kind"),
        "raw_concept_qname": value.get("raw_concept_qname"), "company_canonical_concept_id": value.get("company_canonical_concept_id"),
        "canonical_dimension_signature": deepcopy(value.get("canonical_dimension_signature")),
        "mapping_review_required": bool(value.get("mapping_review_required")), "first_definition": deepcopy(definition), "first_binding": deepcopy(binding),
    }


def _cell(row_id: str, column: Mapping[str, Any], definition: Mapping[str, Any], binding: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    status, reason = _comparability(column, value)
    return {
        "fiscal_time_series_cell_id": _id("cell", row_id, column["fiscal_time_series_column_id"], value.get("analysis_line_value_id")),
        "fiscal_time_series_row_id": row_id, "fiscal_time_series_column_id": column["fiscal_time_series_column_id"],
        "value_status": value.get("value_status"), "value_numeric": deepcopy(value.get("value_numeric")), "value_text": deepcopy(value.get("value_text")),
        "comparability_status": status, "comparability_reason": reason,
        "definition": deepcopy(definition), "binding": deepcopy(binding), "value_lineage": deepcopy(value),
    }


def _missing_cell(row: Mapping[str, Any], column: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fiscal_time_series_row_id": row["fiscal_time_series_row_id"], "fiscal_time_series_column_id": column["fiscal_time_series_column_id"],
        "value_status": "MISSING_HISTORY", "value_numeric": None, "value_text": None,
        "comparability_status": "NOT_COMPARABLE", "comparability_reason": column["column_reason"] or "NO_SELECTED_PANEL_FOR_REQUESTED_FISCAL_PERIOD",
        "definition": None, "binding": None, "value_lineage": None,
    }


def _comparability(column: Mapping[str, Any], value: Mapping[str, Any]) -> tuple[str, str | None]:
    if column["column_status"] != "AVAILABLE":
        return "NOT_COMPARABLE", str(column["column_reason"])
    # Per-cell source facts must agree with the column's actual context.
    actual = (value.get("context_start_date"), value.get("context_end_date"), value.get("context_instant_date"))
    expected = (column["actual_start_date"], column["actual_end_date"], column["actual_instant_date"])
    if column.get("period_evidence_status") == "ONE_ACTUAL_PERIOD_BOUNDARY" and actual != expected:
        return "REVIEW_REQUIRED", "CELL_PERIOD_BOUNDARY_DISAGREES_WITH_FISCAL_COLUMN"
    return str(column.get("comparability_status") or "COMPARABLE"), column.get("comparability_reason")


def _validate_value_scope(value: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    if value.get("selection_view") != scope["selection_view"] or value.get("selection_as_of_date") != scope["selection_as_of_date"]:
        raise FiscalTimeSeriesError("cell selection provenance disagrees with panel scope")


def _validate_derived_q4(value: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    derived = value.get("reported_or_derived") == "DERIVED" or value.get("source_type") == "DERIVED_Q4"
    if derived and (scope["fiscal_quarter"] != 4 or scope["period_class"] != "QTD_3M"):
        raise FiscalTimeSeriesError("DERIVED_Q4 is allowed only in a QTD_3M fiscal Q4 column")


def _duration(start: Any, end: Any) -> int | None:
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days + 1
    except ValueError as exc:
        raise FiscalTimeSeriesError("actual context boundary is not ISO date") from exc


def _fiscal_anchor(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 7 and text.startswith("--") and text[2:4].isdigit() and text[5:7].isdigit() and text[4] == "-":
        return text[2:]
    return None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping): return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)): return tuple(_freeze(item) for item in value)
    return value


def _id(prefix: str, *parts: Any) -> str:
    return f"fiscal-timeseries:{prefix}:{hashlib.sha256(repr(parts).encode()).hexdigest()[:24]}"


def _row_order(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (bool(row.get("mapping_review_required")), str(row.get("label") or ""), str(row["fiscal_time_series_row_id"]))
