from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.analytics.history_quarters import _has_materialized_cell, derive_quarter
from sec_xbrl.periods.logic import PeriodClassifier


def _classify(start, end, *, focus="2026-06-30", form="10-Q", fiscal_focus="Q2", anchor="--12-31"):
    return PeriodClassifier().classify(
        filing={"form": form, "report_date": focus, "document_fiscal_period_focus": fiscal_focus, "fiscal_year_end": anchor},
        concepts=({"raw_concept_id": "r", "period_type": "duration"},),
        contexts=({"context_id": "c", "period_kind": "DURATION", "start_date": start, "end_date": end},),
        facts=({"fact_id": "f", "context_id": "c", "raw_concept_id": "r"},),
    )[0]


def test_annual_and_ttm_need_boundary_evidence_not_just_duration() -> None:
    assert _classify("2025-07-01", "2026-07-01")["period_class"] == "TTM"
    assert _classify("2025-01-01", "2026-01-01", focus="2025-12-31", form="10-K", fiscal_focus="FY")["period_class"] == "FY"
    assert _classify("2025-01-15", "2026-01-01", focus="2025-12-31", form="10-K", fiscal_focus="FY")["period_class"] == "OTHER_DURATION"
    assert _classify("2025-07-01", "2026-07-01", anchor=None)["period_class"] == "OTHER_DURATION"
    # A non-current twelve-month disclosure is not automatically rolling TTM.
    assert _classify("2024-07-01", "2025-07-01")["period_class"] == "OTHER_DURATION"


def _cell(kind, amount, end):
    return {"value_status": "REPORTED", "binding": {"primary_statement_evidence": [{"role": "IS"}]},
            "value_lineage": {"source_type": "REPORTED", "period_class": kind,
            "raw_concept_qname": "us-gaap:NetCashProvidedByUsedInOperatingActivities", "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2025",
            "raw_concept_period_type": "duration", "raw_concept_data_type": "xbrli:monetaryItemType", "company_canonical_concept_id": "company:1:cfo",
            "canonical_dimension_signature": [], "unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": '[]',
            "selection_view": "AS_FILED", "selection_as_of_date": "2026-03-01", "filed_date": "2026-02-01", "comparative_type": "CURRENT_FOCUS",
            "context_start_date": "2025-01-01", "context_end_date": end, "value_numeric": amount,
            "selected_source_fact_id": kind, "source_filing_id": "filing:" + kind, "accession": "accession:" + kind}}


@pytest.mark.parametrize("quarter,later,earlier,end,previous_end", [
    (2, "YTD_6M", "QTD_3M", "2025-07-01", "2025-04-01"),
    (3, "YTD_9M", "YTD_6M", "2025-10-01", "2025-07-01"),
    (4, "FY", "YTD_9M", "2026-01-01", "2025-10-01"),
])
def test_governed_quarter_retains_formula_and_both_raw_sources(quarter, later, earlier, end, previous_end) -> None:
    left, right = _cell(later, "100", end), _cell(earlier, "70", previous_end)
    before = deepcopy(left)
    result = derive_quarter(left, right, quarter=quarter)
    assert result["value_numeric"] == "30"
    assert result["source_fact_ids"] == [later, earlier]
    assert result["source_inputs"][0] == left["value_lineage"]
    assert result["context_start_date"] == previous_end
    assert result["reported_or_derived"] == "DERIVED"
    assert left == before


@pytest.mark.parametrize("field,value", [
    ("period_class", "TTM"), ("context_start_date", "2025-01-02"),
    ("unit_numerator_measures", '["iso4217:EUR"]'), ("canonical_dimension_signature", [["axis", "member"]]),
    ("selection_view", "LATEST_REPORTED"), ("filed_date", "2026-04-01"),
    ("raw_concept_qname", "us-gaap:EarningsPerShareDiluted"), ("raw_concept_data_type", "sharesItemType"),
    ("raw_concept_namespace_uri", "http://example.com/us-gaap/2025"), ("recast_version", "changed"),
])
def test_derivation_rejects_ttm_nonadditive_and_incompatible_inputs(field, value) -> None:
    left, right = _cell("FY", "100", "2026-01-01"), _cell("YTD_9M", "70", "2025-10-01")
    left["value_lineage"][field] = value
    assert derive_quarter(left, right, quarter=4) is None


@pytest.mark.parametrize("status", ["REPORTED", "UNAVAILABLE"])
def test_derived_gap_fill_never_replaces_materialized_report_or_conflict(status) -> None:
    cells = [{"fiscal_time_series_row_id": "r", "fiscal_time_series_column_id": "q4", "value_status": status}]
    assert _has_materialized_cell(cells, "r", "q4")
    assert not _has_materialized_cell(cells, "r", "q3")
