from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, getcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics.quarterly_screening import (
    MANIFEST,
    METRIC_DEFINITIONS,
    QuarterlyMetricReader,
    _exact_subtract,
    _percentage,
    _quarter_spine,
    build_quarterly_company_records,
    publish_quarterly_screening_metrics,
)
from sec_xbrl.metrics.screening import sha256_file

CIK = "0000000001"
AS_OF = "2026-10-10"
USD = ['["iso4217:USD"]', "[]"]


def _profile_rows() -> list[dict]:
    return [
        {"row_id": metric["source_row_id"], "period_class": metric["observation_basis"]}
        for metric in METRIC_DEFINITIONS
        if metric.get("source_row_id")
    ]


def _prepared_input(
    *, row_id: str, value: str, start: str | None, end: str, period_class: str,
    fiscal_year: int = 2025, fiscal_quarter: int = 1, suffix: str | None = None,
) -> tuple[dict, dict]:
    suffix = suffix or row_id
    filing_id = f"filing-{suffix}"
    fact_id = f"fact-{suffix}"
    snapshot = f"l1:{CIK}:000000000125000001:{suffix}"
    cell_id = f"cell-{suffix}"
    cell = {
        "row_id": row_id,
        "cell_id": cell_id,
        "column_id": "instant" if period_class == "INSTANT" else "quarter",
        "as_of": AS_OF,
        "selection_view": "LATEST_REPORTED",
        "period_class": period_class,
        "start": start,
        "end": end,
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "value": value,
        "status": "REPORTED",
        "dimensions": [],
        "unit": USD,
        "basis_version": None,
        "source_fact_id": fact_id,
        "source_filing_ids": [filing_id],
        "statement_evidence": {filing_id: [f"https://example.invalid/{row_id}"]},
    }
    statement_type = (
        "IS"
        if row_id in {"revenue", "gross_profit", "operating_income", "net_income"}
        else "CF"
        if row_id in {"cfo", "capex"}
        else "BS"
    )
    evidence = [{
        "cik": CIK,
        "accession": "0000000001-25-000001",
        "source_filing_id": filing_id,
        "source_network_type": "PRE",
        "role_uri": f"https://example.invalid/{statement_type.lower()}",
        "statement_types": [statement_type],
    }]
    cell["primary_statement_evidence"] = deepcopy(evidence)
    lineage = {
        "accession": "0000000001-25-000001",
        "source_filing_id": filing_id,
        "source_snapshot_id": snapshot,
        "selected_source_fact_id": fact_id,
        "context_id": f"context-{suffix}",
        "raw_concept_qname": f"us-gaap:{row_id.title().replace('_', '')}",
        "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2025",
        "unit_id": "unit-usd",
        "unit_numerator_measures": ["iso4217:USD"],
        "unit_denominator_measures": [],
        "canonical_dimension_signature": [],
        "value_numeric": value,
        "company_canonical_concept_id": f"company:{CIK}:{row_id}",
        "concept_mapping_version": "l2-m2-company-canonical-v4",
        "mapping_review_required": False,
        "selection_view": "LATEST_REPORTED",
        "selection_as_of_date": AS_OF,
        "filed_date": "2025-05-01",
        "report_date": "2025-03-31",
        "period_class": period_class,
        "basis_version": None,
        "structural_version": "struct-v1",
        "recast_version": "recast-v1",
        "context_start_date": start,
        "context_end_date": end if period_class != "INSTANT" else None,
        "context_instant_date": end if period_class == "INSTANT" else None,
        "primary_statement_evidence": deepcopy(evidence),
    }
    return cell, {"cell_id": cell_id, "value_lineage": lineage}


def _one_quarter_inputs() -> tuple[list[dict], list[dict], list[dict]]:
    cells, traces = [], []
    values = {
        "revenue": "100",
        "gross_profit": "45",
        "operating_income": "20",
        "net_income": "15",
        "cfo": "30",
        "capex": "7",
        "assets": "300",
        "cash": "40",
        "liabilities": "120",
        "current_assets": "90",
        "current_liabilities": "60",
    }
    for row_id, value in values.items():
        period_class = "INSTANT" if row_id in {
            "assets", "cash", "liabilities", "current_assets", "current_liabilities"
        } else "QTD_3M"
        cell, trace = _prepared_input(
            row_id=row_id,
            value=value,
            start=None if period_class == "INSTANT" else "2025-01-01",
            end="2025-04-01",
            period_class=period_class,
        )
        old_filing = trace["value_lineage"]["source_filing_id"]
        cell["source_filing_ids"] = ["filing-shared"]
        cell["primary_statement_evidence"][0]["source_filing_id"] = "filing-shared"
        cell["statement_evidence"] = {
            "filing-shared": cell["statement_evidence"].pop(old_filing)
        }
        trace["value_lineage"]["source_filing_id"] = "filing-shared"
        trace["value_lineage"]["primary_statement_evidence"][0][
            "source_filing_id"
        ] = "filing-shared"
        cells.append(cell)
        traces.append(trace)
    columns = [
        {
            "fiscal_time_series_column_id": "quarter",
            "actual_end_date": "2025-04-01",
            "actual_instant_date": None,
        },
        {
            "fiscal_time_series_column_id": "instant",
            "actual_end_date": None,
            "actual_instant_date": "2025-04-01",
        },
    ]
    return columns, cells, traces


def test_fixed_spine_keeps_missing_as_unavailable_and_derives_safe_same_period_metrics() -> None:
    columns, cells, traces = _one_quarter_inputs()
    observations, inventory = build_quarterly_company_records(
        ticker="TEST",
        cik=CIK,
        financial_as_of=AS_OF,
        columns=columns,
        rows=_profile_rows(),
        cells=cells,
        traces=traces,
        spine=_quarter_spine(AS_OF),
    )

    assert len(observations) == len(METRIC_DEFINITIONS) * 8
    assert len(inventory) == 8
    selected = {
        row["metric_id"]: row
        for row in observations
        if (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    }
    assert selected["quarter_revenue"]["value"] == "100"
    assert selected["quarter_gross_margin"]["value"] == "45"
    assert selected["quarter_operating_margin"]["value"] == "20"
    assert selected["quarter_standardized_fcf"]["value"] == "23"
    assert selected["quarter_assets"]["period_start"] is None
    assert selected["quarter_assets"]["source_lineage"]["context_instant_date"] == "2025-04-01"
    future = next(
        row
        for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2026, 3)
    )
    assert future["availability_status"] == "UNAVAILABLE"
    assert future["reason"] == "NO_FILING_AS_OF_CUTOFF"
    assert future["value"] is None


def test_extended_112_day_quarter_is_retained_as_an_explicit_hold() -> None:
    columns, cells, traces = _one_quarter_inputs()
    revenue = next(row for row in cells if row["row_id"] == "revenue")
    revenue["start"] = "2024-12-10"
    lineage = next(row["value_lineage"] for row in traces if row["cell_id"] == revenue["cell_id"])
    lineage["context_start_date"] = "2024-12-10"
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert row["reason"] == "UNSUPPORTED_FISCAL_QUARTER_DURATION"
    assert row["source_lineage"]["candidate_evidence"] == []


def test_m8_quarter_uses_two_full_reported_anchors_and_rejects_wrong_value() -> None:
    cell, trace = _prepared_input(
        row_id="revenue",
        value="25",
        start="2025-10-01",
        end="2026-01-01",
        period_class="QTD_3M",
        fiscal_quarter=4,
        suffix="q4-revenue",
    )
    cell.update(status="DERIVED", source_fact_id=None)
    lineage = trace["value_lineage"]
    lineage.update(
        accession=None,
        source_filing_id=None,
        source_snapshot_id=None,
        selected_source_fact_id=None,
        context_id=None,
        derived_metric_id="derived-quarter-revenue",
        derivation_rule_version="approved-core-cumulative-difference-v1",
        formula="FY - YTD_9M",
        filed_date="2026-02-01",
        report_date="2025-12-31",
    )
    source_inputs = []
    for suffix, value, period_class, end, filed, report in (
        ("fy", "100", "FY", "2026-01-01", "2026-02-01", "2025-12-31"),
        ("ytd", "75", "YTD_9M", "2025-10-01", "2025-11-01", "2025-09-30"),
    ):
        _, source_trace = _prepared_input(
            row_id="revenue", value=value, start="2025-01-01", end=end,
            period_class=period_class, fiscal_quarter=4, suffix=suffix,
        )
        source = source_trace["value_lineage"]
        source["value_numeric"] = value
        source["canonical_dimension_signature"] = []
        source["filed_date"] = filed
        source["report_date"] = report
        cell["statement_evidence"][source["source_filing_id"]] = [
            "https://example.invalid/revenue"
        ]
        source_inputs.append(source)
    lineage["source_inputs"] = source_inputs
    columns = [{
        "fiscal_time_series_column_id": "quarter",
        "actual_end_date": "2026-01-01",
        "actual_instant_date": None,
    }]
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=[cell], traces=[trace], spine=_quarter_spine(AS_OF),
    )
    record = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 4)
    )
    assert record["availability_status"] == "AVAILABLE"
    assert record["source_kind"] == "DERIVED_QUARTER"
    assert [row["value"] for row in record["source_lineage"]["derivation_inputs"]] == [
        "100", "75"
    ]
    assert all(
        "IS" in row["primary_statement_evidence"][0]["statement_types"]
        and row["primary_statement_evidence"][0]["source_network_type"] == "PRE"
        for row in record["source_lineage"]["derivation_inputs"]
    )

    cell["value"] = "26"
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=[cell], traces=[trace], spine=_quarter_spine(AS_OF),
    )
    changed = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 4)
    )
    assert changed["availability_status"] == "UNAVAILABLE"
    assert changed["reason"] == "DERIVATION_VALUE_MISMATCH"


def _m8_cfo_inputs() -> tuple[list[dict], list[dict], list[dict]]:
    cell, trace = _prepared_input(
        row_id="cfo", value="30", start="2025-04-01", end="2025-07-01",
        period_class="QTD_3M", fiscal_quarter=2, suffix="cfo-q2",
    )
    cell.update(
        status="DERIVED", source_fact_id=None,
        source_filing_ids=["filing-q2", "filing-q1"],
    )
    lineage = trace["value_lineage"]
    lineage.update(
        accession=None, source_filing_id=None, source_snapshot_id=None,
        selected_source_fact_id=None, context_id=None,
        derived_metric_id="derived-cfo-q2",
        derivation_rule_version="approved-core-cumulative-difference-v1",
        formula="YTD_6M - Q1", filed_date="2025-08-01",
        report_date="2025-06-30",
    )
    sources = []
    for fiscal_quarter, value, end, period_class, filed, report in (
        (2, "50", "2025-07-01", "YTD_6M", "2025-08-01", "2025-06-30"),
        (1, "20", "2025-04-01", "QTD_3M", "2025-05-01", "2025-03-31"),
    ):
        _, source_trace = _prepared_input(
            row_id="cfo", value=value, start="2025-01-01", end=end,
            period_class=period_class, fiscal_quarter=fiscal_quarter,
            suffix=f"source-cfo-{fiscal_quarter}",
        )
        source = source_trace["value_lineage"]
        source.update(
            source_filing_id=f"filing-q{fiscal_quarter}",
            accession=f"0000000001-25-00000{fiscal_quarter}",
            filed_date=filed, report_date=report,
            source_snapshot_id=(
                f"l1:{CIK}:00000000012500000{fiscal_quarter}:snapshot"
            ),
        )
        for evidence in source["primary_statement_evidence"]:
            evidence.update(
                source_filing_id=source["source_filing_id"],
                accession=source["accession"],
            )
        sources.append(source)
    lineage["source_inputs"] = sources
    return (
        [{
            "fiscal_time_series_column_id": "quarter",
            "actual_end_date": "2025-07-01",
            "actual_instant_date": None,
        }],
        [cell],
        [trace],
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("basis_version", "other"),
        ("canonical_dimension_signature", [{"axis": "A", "member": "M"}]),
        ("company_canonical_concept_id", "company:OTHER:other_metric"),
        ("structural_version", "other"),
    ],
)
def test_m8_sources_must_match_outer_prepared_scope(field: str, value: object) -> None:
    columns, cells, traces = _m8_cfo_inputs()
    for source in traces[0]["value_lineage"]["source_inputs"]:
        source[field] = deepcopy(value)
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item for item in observations
        if item["metric_id"] == "quarter_cfo"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 2)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert "DERIVATION_OUTPUT_SCOPE_MISMATCH" in row["reasons"]


@pytest.mark.parametrize("flag", ["mapping_uncertainty", "basis_break"])
def test_m8_preserves_and_rejects_ineligible_nested_source(flag: str) -> None:
    columns, cells, traces = _m8_cfo_inputs()
    traces[0]["value_lineage"]["source_inputs"][1][flag] = True
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item for item in observations
        if item["metric_id"] == "quarter_cfo"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 2)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert row["source_lineage"]["derivation_inputs"][1][flag] is True


@pytest.mark.parametrize(
    "flag",
    [
        "mapping_uncertainty",
        "ambiguous",
        "compatibility_failure",
        "basis_break",
        "structural_break",
        "recast_break",
    ],
)
def test_m8_preserves_and_rejects_ineligible_outer_lineage(flag: str) -> None:
    columns, cells, traces = _m8_cfo_inputs()
    traces[0]["value_lineage"][flag] = True
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item for item in observations
        if item["metric_id"] == "quarter_cfo"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 2)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert row[flag] is True
    assert row["source_lineage"][flag] is True
    expected_reason = "SOURCE_AMBIGUITY" if flag == "ambiguous" else flag.upper()
    assert expected_reason in row["reasons"]


@pytest.mark.parametrize(
    "outer_dates",
    [
        {"filed_date": "2030-01-01"},
        {"filed_date": "2025-05-01", "report_date": "2025-03-31"},
    ],
)
def test_m8_output_dates_must_attest_selected_input_dates(
    outer_dates: dict[str, str],
) -> None:
    columns, cells, traces = _m8_cfo_inputs()
    traces[0]["value_lineage"].update(outer_dates)
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item for item in observations
        if item["metric_id"] == "quarter_cfo"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 2)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert "DERIVATION_SOURCE_DATE_MISMATCH" in row["reasons"]


def test_missing_raw_anchor_cannot_be_published_as_available() -> None:
    columns, cells, traces = _one_quarter_inputs()
    trace = next(row for row in traces if row["cell_id"] == "cell-revenue")
    trace["value_lineage"]["context_id"] = None
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert row["reason"] == "SOURCE_ANCHOR_INCOMPLETE"


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (lambda _cell, lineage: lineage.update(filed_date="2030-01-01"), "SOURCE_DATE_INVALID"),
        (
            lambda _cell, lineage: lineage.update(
                context_start_date="2024-01-01", context_end_date="2024-04-01"
            ),
            "SOURCE_SCOPE_MISMATCH",
        ),
        (lambda _cell, lineage: lineage.update(value_numeric="42"), "SOURCE_VALUE_MISMATCH"),
        (lambda _cell, lineage: lineage.update(value_numeric=None), "SOURCE_VALUE_MISMATCH"),
        (
            lambda _cell, lineage: lineage.update(
                source_snapshot_id="l1:0000000002:000000000125000001:foreign"
            ),
            "SOURCE_IDENTITY_MISMATCH",
        ),
        (lambda _cell, lineage: lineage.update(ambiguity=True), "SOURCE_AMBIGUITY"),
        (lambda _cell, lineage: lineage.update(continuity_break=True), "CONTINUITY_BREAK"),
    ],
)
def test_elected_reported_source_must_match_prepared_scope_and_cutoff(
    mutation: Callable[[dict, dict], None], expected_reason: str
) -> None:
    columns, cells, traces = _one_quarter_inputs()
    cell = next(row for row in cells if row["row_id"] == "revenue")
    lineage = next(
        row["value_lineage"] for row in traces if row["cell_id"] == cell["cell_id"]
    )
    mutation(cell, lineage)
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item
        for item in observations
        if item["metric_id"] == "quarter_revenue"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 1)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    assert expected_reason in row["reasons"]


def test_reported_numeric_identity_is_exact_decimal_not_string_identity() -> None:
    columns, cells, traces = _one_quarter_inputs()
    revenue_trace = next(
        row["value_lineage"] for row in traces if row["cell_id"] == "cell-revenue"
    )
    revenue_trace["value_numeric"] = "100.0"
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    revenue = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert revenue["availability_status"] == "AVAILABLE"
    assert revenue["value"] == "100"
    assert revenue["source_lineage"]["value"] == "100.0"


@pytest.mark.parametrize(
    "flag", ["mapping_uncertainty", "ambiguous", "compatibility_failure"]
)
def test_selected_identity_failures_are_preserved_and_ineligible(flag: str) -> None:
    columns, cells, traces = _one_quarter_inputs()
    revenue_trace = next(
        row["value_lineage"] for row in traces if row["cell_id"] == "cell-revenue"
    )
    revenue_trace[flag] = True
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    revenue = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert revenue["availability_status"] == "UNAVAILABLE"
    assert revenue[flag] is True
    assert revenue["source_lineage"][flag] is True


@pytest.mark.parametrize("flag", ["basis_break", "structural_break", "recast_break"])
def test_reported_comparison_break_is_visible_but_blocks_arithmetic(flag: str) -> None:
    columns, cells, traces = _one_quarter_inputs()
    revenue_trace = next(
        row["value_lineage"] for row in traces if row["cell_id"] == "cell-revenue"
    )
    revenue_trace[flag] = True
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    selected = {
        row["metric_id"]: row for row in observations
        if (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    }
    assert selected["quarter_revenue"]["availability_status"] == "AVAILABLE"
    assert selected["quarter_revenue"]["source_lineage"][flag] is True
    assert selected["quarter_gross_margin"]["availability_status"] == "UNAVAILABLE"
    assert flag.upper() in selected["quarter_gross_margin"]["reasons"]


def test_actual_typed_primary_evidence_and_same_endpoint_filing_are_required() -> None:
    columns, cells, traces = _one_quarter_inputs()
    gross = next(row for row in cells if row["row_id"] == "gross_profit")
    gross_trace = next(
        row["value_lineage"] for row in traces if row["cell_id"] == gross["cell_id"]
    )
    gross["primary_statement_evidence"] = []
    gross_trace["primary_statement_evidence"] = []
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    gross_record = next(
        row
        for row in observations
        if row["metric_id"] == "quarter_gross_profit"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert gross_record["reason"] == "PRIMARY_STATEMENT_EVIDENCE_MISSING"

    columns, cells, traces = _one_quarter_inputs()
    gross = next(row for row in cells if row["row_id"] == "gross_profit")
    gross_trace = next(
        row["value_lineage"] for row in traces if row["cell_id"] == gross["cell_id"]
    )
    gross["source_filing_ids"] = ["filing-other"]
    gross["primary_statement_evidence"][0]["source_filing_id"] = "filing-other"
    gross_trace["source_filing_id"] = "filing-other"
    gross_trace["primary_statement_evidence"][0]["source_filing_id"] = "filing-other"
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    margin = next(
        row
        for row in observations
        if row["metric_id"] == "quarter_gross_margin"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert margin["availability_status"] == "UNAVAILABLE"
    assert "SOURCE_FILING_MISMATCH" in margin["reasons"]


def _four_quarter_revenue_inputs() -> tuple[list[dict], list[dict], list[dict]]:
    columns, cells, traces = [], [], []
    periods = (
        (2024, 4, "2024-10-01", "2025-01-01", "2025-02-01"),
        (2025, 1, "2025-01-01", "2025-04-01", "2025-05-01"),
        (2025, 2, "2025-04-01", "2025-07-01", "2025-08-01"),
        (2025, 3, "2025-07-01", "2025-10-01", "2025-11-01"),
    )
    for index, (year, quarter, start, end, filed) in enumerate(periods):
        cell, trace = _prepared_input(
            row_id="revenue",
            value=str((index + 1) * 100),
            start=start,
            end=end,
            period_class="QTD_3M",
            fiscal_year=year,
            fiscal_quarter=quarter,
            suffix=f"ttm-{index}",
        )
        cell["column_id"] = f"quarter-{index}"
        cell["basis_version"] = "basis-A"
        trace["value_lineage"].update(
            basis_version="basis-A",
            structural_version="struct-A",
            recast_version="recast-A",
            filed_date=filed,
            report_date=(date.fromisoformat(end) - timedelta(days=1)).isoformat(),
        )
        columns.append(
            {
                "fiscal_time_series_column_id": cell["column_id"],
                "actual_end_date": end,
                "actual_instant_date": None,
            }
        )
        cells.append(cell)
        traces.append(trace)
    return columns, cells, traces


@pytest.mark.parametrize(
    "mutation",
    ["EMPTY_BASIS", "STRUCTURAL_MISMATCH", "BASIS_BREAK", "STRUCTURAL_BREAK"],
)
def test_ttm_requires_nonempty_common_basis_and_version_scope(mutation: str) -> None:
    columns, cells, traces = _four_quarter_revenue_inputs()
    if mutation == "EMPTY_BASIS":
        for cell, trace in zip(cells, traces):
            cell["basis_version"] = ""
            trace["value_lineage"]["basis_version"] = ""
    elif mutation == "STRUCTURAL_MISMATCH":
        traces[0]["value_lineage"]["structural_version"] = "struct-other"
    else:
        traces[0]["value_lineage"][mutation.lower()] = True
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    row = next(
        item
        for item in observations
        if item["metric_id"] == "ttm_revenue"
        and (item["calendar_year"], item["calendar_quarter"]) == (2025, 3)
    )
    assert row["availability_status"] == "UNAVAILABLE"
    expected_reason = (
        mutation if mutation in {"BASIS_BREAK", "STRUCTURAL_BREAK"}
        else "INPUTS_NOT_COMPATIBLE"
    )
    assert row["reason"] == expected_reason


def test_exact_decimal_arithmetic_ignores_ambient_context() -> None:
    previous_precision = getcontext().prec
    getcontext().prec = 3
    try:
        assert _percentage(
            Decimal(10000000000000000000000000001),
            Decimal(10000000000000000000000000000),
            subtract_one=True,
        ) == Decimal("1E-26")
        assert _exact_subtract(
            Decimal("10000000000000000000000000000.0001"),
            Decimal("10000000000000000000000000000.0002"),
        ) == Decimal("-0.0001")
    finally:
        getcontext().prec = previous_precision


def test_fiscal_coordinate_conflict_does_not_reappear_on_third_duplicate() -> None:
    columns, cells, traces = _one_quarter_inputs()
    revenue = next(row for row in cells if row["row_id"] == "revenue")
    revenue_trace = next(row for row in traces if row["cell_id"] == revenue["cell_id"])
    for suffix, start, end in (("dup2", "2024-12-31", "2025-03-31"), ("dup3", "2025-01-02", "2025-04-02")):
        duplicate = deepcopy(revenue)
        duplicate_trace = deepcopy(revenue_trace)
        duplicate["cell_id"] = f"cell-{suffix}"
        duplicate["column_id"] = f"column-{suffix}"
        duplicate["start"], duplicate["end"] = start, end
        duplicate_trace["cell_id"] = duplicate["cell_id"]
        duplicate_trace["value_lineage"].update(
            context_start_date=start,
            context_end_date=end,
            source_snapshot_id=f"l1:{CIK}:000000000125000001:{suffix}",
            selected_source_fact_id=f"fact-{suffix}",
            context_id=f"context-{suffix}",
        )
        columns.append({
            "fiscal_time_series_column_id": duplicate["column_id"],
            "actual_end_date": end,
            "actual_instant_date": None,
        })
        cells.append(duplicate)
        traces.append(duplicate_trace)
    observations, _ = build_quarterly_company_records(
        ticker="TEST", cik=CIK, financial_as_of=AS_OF, columns=columns,
        rows=_profile_rows(), cells=cells, traces=traces, spine=_quarter_spine(AS_OF),
    )
    qoq = next(
        row for row in observations
        if row["metric_id"] == "quarter_revenue_qoq"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
    )
    assert qoq["availability_status"] == "UNAVAILABLE"


def test_immutable_publication_roundtrip_and_payload_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    columns, cells, traces = _one_quarter_inputs()
    records = {
        "columns": columns,
        "core_rows": _profile_rows(),
        "core_cells": cells,
    }
    for digit in "0123456789abcdef":
        records[f"trace_{digit}"] = []
    records["trace_0"] = traces

    class FakeClient:
        def _records(self, ticker: str, view: str, name: str) -> list[dict]:
            assert ticker == "TEST"
            assert view == "LATEST_REPORTED"
            return deepcopy(records[name])

    annual_root = tmp_path / "annual"
    annual_root.mkdir()
    annual_manifest = annual_root / "screening_metric_manifest.json"
    annual_manifest.write_text("{}\n", encoding="utf-8")
    annual = SimpleNamespace(
        manifest={
            "publication_id": "annual-metrics-test",
            "financial_as_of": AS_OF,
            "configured_ciks": [CIK],
        }
    )
    monkeypatch.setattr(
        "sec_xbrl.metrics.quarterly_screening.ScreeningMetricReader", lambda root: annual
    )
    monkeypatch.setattr(
        "sec_xbrl.metrics.quarterly_screening._open_company_source",
        lambda company, financial_as_of: (
            FakeClient(),
            {
                "kind": "QUARTERLY_ANALYSIS_PUBLICATION",
                "ticker": "TEST",
                "cik": CIK,
                "publication_id": "analysis-test",
                "manifest_sha256": "a" * 64,
                "declared_files": [],
            },
        ),
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "quarterly-screening-metric-config-v1",
                "financial_as_of": AS_OF,
                    "source_commit_sha": "b" * 40,
                "annual_metric_root": str(annual_root),
                "annual_metric_manifest_sha256": sha256_file(annual_manifest),
                "companies": [
                    {
                        "ticker": "TEST",
                        "cik": CIK,
                        "analysis_root": "/unused/by-controlled-source",
                        "analysis_manifest_sha256": "c" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "quarterly"
    published = publish_quarterly_screening_metrics(config, destination)
    assert published.root == destination
    status = QuarterlyMetricReader(destination).verify_all()
    assert status == {
        "publication_id": published.publication_id,
        "companies": 1,
        "definitions": 17,
        "support": 17,
        "observations": 136,
        "period_inventory": 8,
    }

    payload = destination / "quarter_metric_observations.json"
    payload.write_text(payload.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="payload changed"):
        QuarterlyMetricReader(destination)
    assert (destination / MANIFEST).is_file()

