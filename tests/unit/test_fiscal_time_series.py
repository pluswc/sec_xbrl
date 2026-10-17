from __future__ import annotations

import gc
import sqlite3
import weakref
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from sec_xbrl.analytics import (
    CompanyAnalysisPanelResult,
    FiscalPeriod,
    FiscalTimeSeriesBuilder,
    FiscalTimeSeriesError,
    FiscalTimeSeriesInput,
    FiscalTimeSeriesQuery,
)


def _panel(
    year: int,
    quarter: int,
    start: str,
    end: str,
    *,
    custom: bool = False,
    view: str = "LATEST_REPORTED",
    period_class: str = "QTD_3M",
    derived: bool = False,
) -> CompanyAnalysisPanelResult:
    line = f"line:{year}:{quarter}:{custom}"
    definition = {"analysis_line_id": line, "label": "Data Center" if custom else "Revenue", "line_class": "COMPANY_CUSTOM" if custom else "COMMON_GAAP", "line_scope": "DETAIL" if custom else "STATEMENT", "line_kind": "REPORTED"}
    binding = {"analysis_binding_id": f"binding:{line}", "analysis_line_id": line}
    value = {
        "analysis_line_value_id": f"value:{line}", "analysis_line_id": line, "value_status": "REPORTED",
        "value_numeric": "100", "value_text": None, "selection_view": view, "selection_as_of_date": "2025-12-01",
        "source_filing_id": f"filing:{year}:{quarter}", "selected_source_fact_id": f"fact:{year}:{quarter}",
        "raw_concept_qname": "nvda:DataCenterRevenue" if custom else "us-gaap:Revenues",
        "company_canonical_concept_id": "company:data-center" if custom else "company:revenue",
        "canonical_dimension_signature": (("company:product", "company:data-center", None, "EXPLICIT", False),) if custom else (),
        "unit_numerator_measures": ("iso4217:USD",), "unit_denominator_measures": (),
        "mapping_review_required": False, "context_start_date": start, "context_end_date": end, "context_instant_date": None,
        "comparative_type": "CURRENT_FOCUS",
        "accession": f"0000000000-{year}-{quarter:06d}", "filed_date": "2025-01-01", "source_snapshot_id": "snapshot", "context_id": "context",
        "source_type": "DERIVED_Q4" if derived else "REPORTED", "reported_or_derived": "DERIVED" if derived else "REPORTED",
    }
    return CompanyAnalysisPanelResult((definition,), (binding,), (value,), {"cik": "0001045810", "fiscal_year": year, "fiscal_quarter": quarter, "period_class": period_class, "selection_view": view, "selection_as_of_date": "2025-12-01"})


def test_fiscal_columns_keep_actual_boundaries_custom_rows_and_missing_history() -> None:
    result = FiscalTimeSeriesBuilder().build(
        inputs=(
            FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-29"), "--01-28"),
            FiscalTimeSeriesInput(_panel(2025, 3, "2024-07-29", "2024-10-27", custom=True), "--01-26"),
        ),
        expected_periods=(FiscalPeriod(2024, 2, "QTD_3M"), FiscalPeriod(2024, 3, "QTD_3M"), FiscalPeriod(2025, 3, "QTD_3M")),
    )
    assert [item["fiscal_label"] for item in result.columns] == ["FY2024 Q2", "FY2024 Q3", "FY2025 Q3"]
    assert result.columns[1]["actual_start_date"] == "2023-07-31"
    assert result.columns[1]["duration_days"] == 90
    assert result.columns[1]["fiscal_calendar_version"] == "DEI_FYE_MONTH:01"
    assert {row["line_class"] for row in result.rows} == {"COMMON_GAAP", "COMPANY_CUSTOM"}
    matrix = FiscalTimeSeriesQuery(result).matrix()
    assert all(cells["value_status"] == "MISSING_HISTORY" for cells in (matrix[0]["cells"][0], matrix[1]["cells"][0]))
    assert all(cells["value_numeric"] is None for cells in (matrix[0]["cells"][0], matrix[1]["cells"][0]))


def test_53_week_difference_is_visible_and_never_normalized() -> None:
    result = FiscalTimeSeriesBuilder().build(inputs=(
        FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-28"), "--01-28"),
        FiscalTimeSeriesInput(_panel(2025, 3, "2024-07-29", "2024-11-02"), "--01-26"),
    ))
    assert result.columns[1]["comparability_status"] == "DURATION_EXCEPTION_7_DAYS"


def test_calendar_month_change_and_unknown_dei_are_review_required() -> None:
    result = FiscalTimeSeriesBuilder().build(inputs=(
        FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-28"), "--01-28"),
        FiscalTimeSeriesInput(_panel(2025, 3, "2024-07-29", "2024-10-27"), "--02-02"),
    ))
    assert result.columns[1]["comparability_reason"] == "FISCAL_CALENDAR_VERSION_CHANGE"
    unknown = FiscalTimeSeriesBuilder().build(inputs=(FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-28"), None),))
    assert unknown.columns[0]["comparability_status"] == "BASELINE"
    assert FiscalTimeSeriesQuery(unknown).matrix()[0]["cells"][0]["comparability_status"] == "BASELINE"


def test_period_class_view_and_derived_q4_boundaries_fail_closed() -> None:
    q3 = FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-28"), "--01-28")
    as_filed = FiscalTimeSeriesInput(_panel(2024, 2, "2023-05-01", "2023-07-30", view="AS_FILED"), "--01-28")
    with pytest.raises(FiscalTimeSeriesError, match="cannot mix"):
        FiscalTimeSeriesBuilder().build(inputs=(q3, as_filed))
    bad_derived = FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-28", derived=True), "--01-28")
    with pytest.raises(FiscalTimeSeriesError, match="DERIVED_Q4"):
        FiscalTimeSeriesBuilder().build(inputs=(bad_derived,))
    with pytest.raises(FiscalTimeSeriesError, match="cannot mix"):
        FiscalTimeSeriesBuilder().build(inputs=(q3,), expected_periods=(FiscalPeriod(2024, 3, "FY"),))


def _duplicate_panel(*, different_fact=False, amount="100.00", primary=False, different_period=False, different_version=False):
    panel = _panel(2024, 3, "2023-07-31", "2023-10-30")
    definition, binding, value = deepcopy(panel.definitions[0]), deepcopy(panel.bindings[0]), deepcopy(panel.values[0])
    for row in (definition, binding, value):
        row["analysis_line_id"] += ":other-path"
    definition["line_scope"] = "EXPLORATION_DETAIL"
    binding["analysis_binding_id"] += ":other-path"
    value["analysis_line_value_id"] += ":other-path"
    value["value_numeric"] = amount
    if different_fact:
        value["selected_source_fact_id"] += ":second"
    if different_period:
        value["context_start_date"] = "2023-08-01"
    if different_version:
        value["source_filing_id"] += ":amendment"
    if primary:
        binding["primary_statement_evidence"] = [{"role_uri": "primary-is", "source_relationship_edge_id": "edge:1"}]
    return CompanyAnalysisPanelResult(panel.definitions + (definition,), panel.bindings + (binding,), panel.values + (value,), panel.scope)


@pytest.mark.parametrize("different_fact", [False, True])
def test_equal_numeric_facts_and_graph_paths_coalesce_with_all_lineage(different_fact):
    panel = _duplicate_panel(different_fact=different_fact)
    result = FiscalTimeSeriesBuilder().build(inputs=(FiscalTimeSeriesInput(panel, "--01-28"),))
    assert len(result.cells) == 1
    cell = result.cells[0]
    assert cell["resolution_status"] == "COALESCED"
    assert len(cell["candidate_lineage"]) == 2
    assert cell["source_fact_count"] == (2 if different_fact else 1)
    assert cell["value_status"] == "REPORTED"


def test_primary_statement_preference_uses_evidence_not_root_label():
    panel = _duplicate_panel(different_fact=True, amount="105", primary=True)
    cell = FiscalTimeSeriesBuilder().build(inputs=(FiscalTimeSeriesInput(panel, "--01-28"),)).cells[0]
    assert cell["value_numeric"] == "105"
    assert cell["candidate_count"] == 2
    assert cell["binding"]["primary_statement_evidence"]


@pytest.mark.parametrize("kwargs,reason", [
    ({"amount": "105", "different_fact": True}, "CONFLICTING_EQUAL_PRIORITY_FACTS"),
    ({"different_period": True, "primary": True}, "AMBIGUOUS_ACTUAL_PERIOD_BOUNDARIES"),
    ({"different_version": True, "primary": True}, "MULTIPLE_SELECTED_FILING_VERSIONS"),
])
def test_conflict_is_cell_local_and_preserves_all_candidates(kwargs, reason):
    panel = _duplicate_panel(**kwargs)
    other = _panel(2025, 3, "2024-07-29", "2024-10-28")
    result = FiscalTimeSeriesBuilder().build(inputs=(FiscalTimeSeriesInput(panel, "--01-28"), FiscalTimeSeriesInput(other, "--01-26")))
    bad = next(cell for cell in result.cells if cell["value_status"] == "UNAVAILABLE")
    assert bad["resolution_reason"] == reason
    assert bad["value_lineage"] is None and bad["value_numeric"] is None
    assert len(bad["candidate_lineage"]) == 2
    assert any(cell["value_status"] == "REPORTED" for cell in result.cells)


def test_absent_item_in_available_period_is_not_missing_history():
    result = FiscalTimeSeriesBuilder().build(inputs=(
        FiscalTimeSeriesInput(_panel(2024, 3, "2023-07-31", "2023-10-30"), "--01-28"),
        FiscalTimeSeriesInput(_panel(2025, 3, "2024-07-29", "2024-10-28", custom=True), "--01-26"),
    ))
    assert {cell["value_status"] for row in FiscalTimeSeriesQuery(result).matrix() for cell in row["cells"]} == {"REPORTED", "NOT_REPORTED"}


def test_equal_reported_and_derived_numbers_do_not_coalesce():
    panel = _duplicate_panel(different_fact=True)
    scope = {**panel.scope, "fiscal_quarter": 4}
    values = deepcopy(panel.values)
    values[1]["reported_or_derived"] = "DERIVED"
    mixed = CompanyAnalysisPanelResult(panel.definitions, panel.bindings, values, scope)
    cell = FiscalTimeSeriesBuilder().build(inputs=(FiscalTimeSeriesInput(mixed, "--01-28"),)).cells[0]
    assert cell["value_status"] == "UNAVAILABLE"
    assert cell["resolution_reason"] == "CONFLICTING_EQUAL_PRIORITY_FACTS"


def _typed_panel(year: int, quarter: int) -> CompanyAnalysisPanelResult:
    panel = _panel(year, quarter, f"{year - 1}-01-01", f"{year - 1}-03-31")
    definitions = deepcopy(panel.definitions)
    bindings = deepcopy(panel.bindings)
    values = deepcopy(panel.values)
    definitions[0]["typed_provenance"] = {
        "tuple": (True, None, b"bytes"),
        "list": [Decimal("12.3400"), date(2026, 10, 17)],
    }
    bindings[0]["ordered_roles"] = (
        {"role": "first", "depth": 0},
        {"role": "second", "depth": 1},
    )
    values[0]["nested_lineage"] = {
        "dimensions": (("axis", "member", None, "EXPLICIT", False),),
        "unit": {"numerator": ["iso4217:USD"], "denominator": []},
    }
    return replace(
        panel,
        definitions=definitions,
        bindings=bindings,
        values=values,
    )


def test_spilled_builder_is_exactly_equal_with_typed_ordered_provenance(tmp_path):
    inputs = (
        FiscalTimeSeriesInput(_typed_panel(2024, 1), "--12-31"),
        FiscalTimeSeriesInput(_typed_panel(2025, 1), "--12-31"),
    )
    expected = FiscalTimeSeriesBuilder().build(inputs=inputs)
    actual = FiscalTimeSeriesBuilder().build_spilled(
        inputs=iter(inputs), spill_root=tmp_path
    )
    diagnostic = actual.diagnostic_path
    try:
        assert actual.materialize() == expected
        nested = actual.materialize().cells[0]["candidate_lineage"][0]["definition"]
        assert type(nested["typed_provenance"]["tuple"]) is tuple
        assert type(nested["typed_provenance"]["tuple"][0]) is bool
        assert type(nested["typed_provenance"]["tuple"][2]) is bytes
        assert type(nested["typed_provenance"]["list"][0]) is Decimal
        assert type(nested["typed_provenance"]["list"][1]) is date
    finally:
        actual.close(success=True)
    assert not diagnostic.exists()
    assert not list(tmp_path.glob("fiscal-timeseries-*"))


@pytest.mark.parametrize("count", (8, 128))
def test_spilled_builder_releases_each_panel_before_requesting_the_next(
    tmp_path, count
):
    class TrackedDict(dict):
        pass

    released = 0

    def inputs():
        nonlocal released
        previous = None
        for index in range(count):
            if previous is not None:
                gc.collect()
                assert previous() is None
                released += 1
            panel = _panel(
                2024 + index,
                1,
                f"{2023 + index}-01-01",
                f"{2023 + index}-03-31",
            )
            tracked = TrackedDict(panel.definitions[0])
            previous = weakref.ref(tracked)
            yield FiscalTimeSeriesInput(
                replace(panel, definitions=(tracked,)), "--12-31"
            )
            del tracked, panel
        gc.collect()
        assert previous is not None and previous() is None
        released += 1

    result = FiscalTimeSeriesBuilder().build_spilled(
        inputs=inputs(), spill_root=tmp_path
    )
    try:
        assert result.counts == {"columns": count, "rows": 1, "cells": count}
        assert released == count
    finally:
        result.close(success=True)


def test_spilled_builder_preserves_typed_journal_on_failure(tmp_path):
    inputs = (
        FiscalTimeSeriesInput(_typed_panel(2024, 1), "--12-31"),
        FiscalTimeSeriesInput(
            _panel(
                2025,
                1,
                "2024-01-01",
                "2024-03-31",
                view="AS_FILED",
            ),
            "--12-31",
        ),
    )
    with pytest.raises(FiscalTimeSeriesError, match="cannot mix"):
        FiscalTimeSeriesBuilder().build_spilled(
            inputs=inputs, spill_root=tmp_path
        )
    journals = list(tmp_path.glob("fiscal-timeseries-*/fiscal-time-series-spill.records"))
    assert len(journals) == 1
    assert journals[0].stat().st_size > 40


def test_spilled_builder_rejects_memory_only_sqlite(tmp_path, monkeypatch):
    connect = sqlite3.connect

    class Connection:
        def __init__(self):
            self.connection = connect("")

        def execute(self, sql, *args):
            if sql == "PRAGMA compile_options":
                return [("TEMP_STORE=3",)]
            pytest.fail("mutating spill initialization before disk-storage check")

        def close(self):
            self.connection.close()

    monkeypatch.setattr(sqlite3, "connect", lambda filename: Connection())
    with pytest.raises(FiscalTimeSeriesError, match="disk-backed"):
        FiscalTimeSeriesBuilder().build_spilled(
            inputs=(FiscalTimeSeriesInput(_typed_panel(2024, 1), "--12-31"),),
            spill_root=tmp_path,
        )
    assert list(tmp_path.glob("fiscal-timeseries-*/fiscal-time-series-spill.records"))


def test_spilled_builder_cleanup_never_removes_a_foreign_replacement(tmp_path):
    result = FiscalTimeSeriesBuilder().build_spilled(
        inputs=(FiscalTimeSeriesInput(_typed_panel(2024, 1), "--12-31"),),
        spill_root=tmp_path / "spill",
    )
    journal = result.diagnostic_path
    retained = journal.with_name("retained-owned-journal")
    journal.rename(retained)
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"FOREIGN")
    journal.symlink_to(foreign)
    with pytest.raises(FiscalTimeSeriesError, match="ownership changed"):
        result.close(success=True)
    assert foreign.read_bytes() == b"FOREIGN"
    assert retained.exists()
