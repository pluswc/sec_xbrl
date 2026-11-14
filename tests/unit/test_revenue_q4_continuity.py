from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.analytics.revenue_q4_continuity import (
    derive_reviewed_q4,
    exact_difference,
    review_endpoint,
)
from tests.unit.test_revenue_quarters import _observation


def inputs():
    return [
        _observation("FY", "150", period_observation_id="annual", mapping_review_required=True,
                     company_canonical_concept_id="annual-epoch", context_id="annual-context"),
        _observation("YTD_9M", "100", period_observation_id="nine", company_canonical_concept_id="quarter-epoch", context_id="nine-context"),
    ]


def link(rows):
    return {"id": "approved-scope", "cik": rows[0]["cik"], "relation": "RENAMED",
            "annual": review_endpoint(rows[0]), "ytd9": review_endpoint(rows[1]),
            "period": {"fiscal_year": 2025, "fiscal_quarter": 4, "period_start": "2025-10-01", "period_end": "2026-01-01"},
            "evidence": [{"file_id": "disclosure", "locator": "segment table", "assertion": "same reviewed full scope"}]}


def test_exact_reviewed_link_preserves_original_unconfirmed_mappings():
    rows = inputs()
    original = deepcopy(rows)
    metrics, exclusions = derive_reviewed_q4(rows, [link(rows)], cutoff="2026-10-25")
    assert not exclusions
    metric, = metrics
    assert metric["value_numeric"] == "50"
    assert metric["source_inputs"] == original == rows
    assert metric["source_inputs"][0]["mapping_review_required"] is True
    assert metric["source_inputs"][0]["company_canonical_concept_id"] == "annual-epoch"
    assert metric["source_inputs"][1]["company_canonical_concept_id"] == "quarter-epoch"
    assert metric["basis_assurance"] == "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
    assert metric["comparison_only"] is False


@pytest.mark.parametrize("field,value", [("quality_blocking", True), ("continuity_break", True),
    ("source_is_amendment", True), ("unit_numerator_measures", '["iso4217:EUR"]'),
    ("filed_date", "2027-01-01"), ("value_numeric", "NaN"), ("basis_version", "different")])
def test_review_never_authorizes_ineligible_financial_inputs(field, value):
    rows = inputs()
    rows[0][field] = value
    metrics, exclusions = derive_reviewed_q4(rows, [link(rows)], cutoff="2026-10-25")
    assert not metrics and exclusions


def test_endpoint_tamper_duplicate_and_missing_evidence_fail_closed():
    rows = inputs()
    approval = link(rows)
    rows[0]["value_numeric"] = "151"
    with pytest.raises(ValueError, match="exact original"):
        derive_reviewed_q4(rows, [approval], cutoff="2026-10-25")
    approval = link(rows)
    with pytest.raises(ValueError, match="duplicated"):
        derive_reviewed_q4(rows, [approval, deepcopy(approval)], cutoff="2026-10-25")
    approval["evidence"] = []
    with pytest.raises(ValueError, match="evidence"):
        derive_reviewed_q4(rows, [approval], cutoff="2026-10-25")


def test_prior_actual_period_is_not_the_source_filing_focus_year():
    rows = inputs()
    for row in rows:
        row["comparative_type"] = "PRIOR_YEAR_COMPARABLE"
        row["fiscal_year"] = 2026
    approval = link(rows)
    metrics, exclusions = derive_reviewed_q4(rows, [approval], cutoff="2026-10-25")
    assert not exclusions and metrics[0]["comparison_only"] is True
    assert metrics[0]["fiscal_year"] == 2025
    assert metrics[0]["source_inputs"][0]["fiscal_year"] == 2026
    approval["period"]["fiscal_year"] = 2026
    assert derive_reviewed_q4(rows, [approval], cutoff="2026-10-25")[1][0]["reason"] == "Q4_REVIEW_ACTUAL_PERIOD_MISMATCH"


def test_exact_zero_negative_and_long_coefficient_subtraction():
    assert exact_difference("100", "100") == "0"
    assert exact_difference("100", "150") == "-50"
    assert exact_difference("1." + "0" * 69 + "1", "1") == "0." + "0" * 69 + "1"


@pytest.mark.parametrize("annual,nine,expected", [("100", "100", "0"), ("50", "100", "-50")])
def test_valid_zero_and_negative_reviewed_amounts_remain_available(annual, nine, expected):
    rows = inputs()
    rows[0]["value_numeric"], rows[1]["value_numeric"] = annual, nine
    metrics, exclusions = derive_reviewed_q4(rows, [link(rows)], cutoff="2026-10-25")
    assert not exclusions and metrics[0]["value_numeric"] == expected
