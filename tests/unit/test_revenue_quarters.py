from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.analytics.revenue_quarters import ASSURANCE, derive_revenue_q4


def _observation(kind, amount, **changes):
    return {"cik": "0000000001", "fiscal_year": 2025, "fiscal_quarter": 4 if kind == "FY" else 3,
            "period_class": kind, "comparative_type": "CURRENT_FOCUS", "source_fact_id": kind,
            "source_filing_id": f"filing:{kind}", "source_snapshot_id": f"snapshot:{kind}", "accession": kind,
            "filed_date": "2026-02-01" if kind == "FY" else "2025-10-20",
            "raw_concept_qname": "us-gaap:Revenues", "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2025",
            "raw_concept_is_standard": True, "raw_concept_period_type": "duration", "raw_concept_data_type": "xbrli:monetaryItemType",
            "company_canonical_concept_id": "canonical-revenue", "concept_mapping_id": "concept-map",
            "mapping_review_required": False, "canonical_dimension_signature": [["axis", "member", None, "EXPLICIT", "false"]],
            "raw_dimension_signature": [["raw-axis", "raw-member", None, "EXPLICIT", "false"]], "dimension_mapping_ids": [["axis-map", "member-map"]],
            "context_period_kind": "DURATION", "context_start_date": "2025-01-01",
            "context_end_date": "2026-01-01" if kind == "FY" else "2025-10-01",
            "context_duration_days": 365 if kind == "FY" else 273, "is_nil": False,
            "unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": '[]',
            "reported_or_derived": "REPORTED", "value_numeric": amount, **changes}


@pytest.mark.parametrize("annual,nine,expected", [("100", "70", "30"), ("70", "70", "0"), ("60", "70", "-10")])
def test_confirmed_full_scope_q4_reuses_governed_arithmetic_and_ordered_sources(annual, nine, expected):
    rows = [_observation("FY", annual), _observation("YTD_9M", nine)]
    before = deepcopy(rows)
    metrics, exclusions = derive_revenue_q4(rows, cutoff="2026-10-25")
    assert not exclusions
    metric, = metrics
    assert metric["value_numeric"] == expected
    assert metric["source_fact_ids"] == ["FY", "YTD_9M"]
    assert metric["reported_or_derived"] == "DERIVED"
    assert metric["formula"] == "FY - YTD_9M"
    assert metric["basis_assurance"] == ASSURANCE
    assert metric["context_start_date"] == "2025-10-01"
    assert rows == before


@pytest.mark.parametrize("changes", [
    {"mapping_review_required": True}, {"dimension_mapping_ids": [["axis-map", None]]}, {"canonical_dimension_signature": [["axis", "different", None, "EXPLICIT", "false"]]},
    {"quality_blocking": True}, {"is_nil": True}, {"continuity_break": True},
    {"structural_break": True}, {"recast_break": True}, {"basis_break": True}, {"compatibility_failure": True},
    {"unit_numerator_measures": '["iso4217:EUR"]'}, {"context_start_date": "2025-01-02"},
    {"basis_version": "changed"}, {"value_numeric": "NaN"}, {"source_is_amendment": True},
    {"context_end_date": "2025-11-01", "context_duration_days": 304},
])
def test_q4_never_bridges_incompatible_or_unconfirmed_inputs(changes):
    metrics, exclusions = derive_revenue_q4([_observation("FY", "100"), _observation("YTD_9M", "70", **changes)], cutoff="2026-10-25")
    assert not metrics
    assert exclusions


def test_missing_future_and_competing_inputs_hold_without_zero_substitution():
    for rows in ([_observation("FY", "100")], [_observation("FY", "100"), _observation("YTD_9M", "70", filed_date="2027-01-01")],
                 [_observation("FY", "100"), _observation("FY", "100", source_fact_id="other"), _observation("YTD_9M", "70")]):
        metrics, exclusions = derive_revenue_q4(rows, cutoff="2026-10-25")
        assert not metrics
        assert exclusions
