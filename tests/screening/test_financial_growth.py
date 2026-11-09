from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from examples.screening.prepare_financial_growth import (
    ARITHMETIC,
    _dates,
    compare_amounts,
    compare_periods,
)

CUTOFF = "2026-10-25"


@pytest.mark.parametrize(("prior", "current", "status", "yoy", "magnitude", "delta"), [
    ("10", "15", "RATE_AVAILABLE", "50", None, "5"),
    ("10", "0", "ZERO_REACHED", "-100", None, "-10"),
    ("10", "-5", "NEGATIVE_TURN", None, None, "-15"),
    ("0", "5", "ZERO_BASE", None, None, "5"),
    ("0", "0", "ZERO_UNCHANGED", None, None, "0"),
    ("0", "-5", "ZERO_BASE", None, None, "-5"),
    ("-10", "5", "POSITIVE_TURN", None, None, "15"),
    ("-10", "0", "ZERO_REACHED", None, None, "10"),
    ("-10", "-4", "NEGATIVE_MAGNITUDE_REDUCED", None, "60", "6"),
    ("-10", "-15", "NEGATIVE_MAGNITUDE_EXPANDED", None, "-50", "-5"),
    ("-10", "-10", "NEGATIVE_MAGNITUDE_UNCHANGED", None, "0", "0"),
])
def test_sign_policy(prior, current, status, yoy, magnitude, delta):
    assert compare_amounts(Decimal(current), Decimal(prior)) == {
        "status": status, "yoy": yoy, "negative_magnitude_change": magnitude, "delta": delta,
    }


def test_small_change_is_not_lost_to_decimal_context():
    result = compare_amounts(Decimal("1." + "0" * 69 + "1"), Decimal(1))
    assert Decimal(result["delta"]) == Decimal("1e-70")
    assert Decimal(result["yoy"]) == Decimal("1e-68")


def annual(year):
    return {
        "metric_observation_id": f"FY{year}", "metric_id": "operating_income",
        "metric_definition_version": "v1", "fiscal_year": year, "period_class": "FY",
        "period_start": f"{year}-01-01", "period_end": f"{year + 1}-01-01",
        "availability_status": "AVAILABLE", "source_kind": "REPORTED", "value": "100",
        "view": "LATEST_REPORTED", "financial_as_of": CUTOFF, "cik": "0000000001", "unit": "USD",
        "unit_semantics": ['["iso4217:USD"]', '[]'], "dimensions": [], "basis_version": None,
        "mapping_review_required": False, "comparability_policy": "REPORTED_VALUES_NOT_RECAST_VALIDATED",
        "semantic_identity": "operating-income", "concept_mapping_version": "m1",
        "raw_concept_qname": "us-gaap:OperatingIncomeLoss", "raw_concept_taxonomy_family": "us-gaap",
        "raw_concept_data_type": "monetary", "raw_concept_period_type": "duration",
    }


@pytest.mark.parametrize(("field", "changed", "reason"), [
    ("fiscal_year", 2022, "INCOMPATIBLE_PERIOD"),
    ("period_start", "2023-04-01", "INCOMPATIBLE_PERIOD"),
    ("period_end", "2024-01-02", "INCOMPATIBLE_PERIOD"),
    ("semantic_identity", "other", "INCOMPATIBLE_SEMANTICS"),
    ("concept_mapping_version", "m2", "INCOMPATIBLE_SEMANTICS"),
    ("unit", "EUR", "PRIOR_UNAVAILABLE"),
    ("unit_scale", 3, "PRIOR_UNAVAILABLE"),
    ("unit_semantics", ['["iso4217:EUR"]', '[]'], "PRIOR_UNAVAILABLE"),
    ("financial_as_of", "2026-10-24", "PRIOR_UNAVAILABLE"),
    ("view", "OTHER", "PRIOR_UNAVAILABLE"),
    ("value", "Infinity", "PRIOR_UNAVAILABLE"),
    ("quality_status", "BLOCK", "PRIOR_UNAVAILABLE"),
    ("mapping_review_required", True, "PRIOR_UNAVAILABLE"),
    ("dimensions", ["axis=member"], "INCOMPATIBLE_SCOPE"),
    ("metric_definition_version", "v2", "INCOMPATIBLE_SCOPE"),
    ("basis_version", "restated", "INCOMPATIBLE_SCOPE"),
    ("comparability_policy", None, "INCOMPATIBLE_SCOPE"),
    ("cik", "0000000002", "INCOMPATIBLE_SCOPE"),
])
def test_annual_comparison_fails_closed(field, changed, reason):
    result = compare_periods(annual(2024), {**annual(2023), field: changed}, "FY", CUTOFF, {})
    assert result["reason"] == reason
    assert result["delta"] is result["yoy"] is None


def test_annual_52_53_week_inputs_keep_original_observation_references():
    before = {**annual(2023), "period_start": "2022-09-25", "period_end": "2023-10-01"}
    after = {**annual(2024), "period_start": "2023-10-01", "period_end": "2024-09-29", "value": "0"}
    result = compare_periods(after, before, "FY", CUTOFF, {})
    assert result["status"] == "ZERO_REACHED"
    assert result["basis_assurance"] == ARITHMETIC
    assert result["prior"]["observation_id"] == "FY2023"
    assert result["current"]["period_end"] == "2024-09-29"
    assert result["current"]["end_convention"] == "EXCLUSIVE"
    assert compare_periods(after, None, "FY", CUTOFF, {})["reason"] == "PRIOR_NOT_PREPARED"
    assert compare_periods(after, before, "FY", CUTOFF, {}, ambiguous=True)["reason"] == "AMBIGUOUS_FISCAL_PERIOD"


@pytest.mark.parametrize("days", [364, 365, 366, 371])
def test_normal_annual_and_ttm_durations(days):
    start = date(2024, 1, 1)
    end = start + timedelta(days=days)
    for basis in ("FY", "TTM"):
        row = {"period_class": basis, "period_start": start.isoformat(), "period_end": end.isoformat(),
               "end_convention": "EXCLUSIVE"}
        assert _dates(row, basis) == (start, end)


@pytest.mark.parametrize(("start", "end"), [("2024-01-15", "2025-01-01"), ("2024-01-02", "2025-01-02")])
def test_annual_gap_does_not_publish_delta_or_rate(start, end):
    current = {**annual(2024), "period_start": start, "period_end": end}
    result = compare_periods(current, annual(2023), "FY", CUTOFF, {})
    assert result["reason"] == "INCOMPATIBLE_PERIOD"
    assert result["yoy"] is result["delta"] is None


def test_contiguous_annual_stub_is_unavailable():
    current = {**annual(2024), "period_end": "2024-12-15"}
    assert compare_periods(current, annual(2023), "FY", CUTOFF, {})["reason"] == "INCOMPATIBLE_PERIOD"


def quarter(year, q, metric="quarter_cfo"):
    start = date(year, 3 * q - 2, 1)
    end = date(year, 3 * q + 1, 1) if q < 4 else date(year + 1, 1, 1)
    concept = metric.removeprefix("quarter_")
    source = {"raw_concept_qname": concept, "company_canonical_concept_id": concept, "mapping_review_required": False}
    return {
        "observation_id": f"{metric}-{year}Q{q}", "metric_id": metric, "definition_version": "v1",
        "fiscal_year": year, "fiscal_quarter": f"Q{q}", "period_class": "QTD_3M",
        "period_start": start.isoformat(), "period_end": end.isoformat(), "end_convention": "EXCLUSIVE",
        "selection_view": "LATEST_REPORTED", "selection_as_of_date": CUTOFF, "value": "100",
        "unit": "USD", "availability_status": "AVAILABLE", "source_kind": "REPORTED",
        "cik": "0000000001", "dimensions": [], "basis_version": None, "mapping_review_required": False,
        "company_canonical_concept_id": concept, "canonical_mapping_version": "m1", "source_lineage": source,
    }


def ttm(year):
    legs = [quarter(year, q) for q in range(1, 5)]
    return {
        **legs[-1], "observation_id": f"TTM{year}", "metric_id": "ttm_cfo", "period_class": "TTM",
        "source_kind": "DERIVED_METRIC", "period_start": legs[0]["period_start"], "value": "400",
        "source_lineage": {"derivation_inputs": legs, "compatibility_policy": ARITHMETIC,
                           "derivation_rule_version": "verified-ttm-v1"},
    }


@pytest.mark.parametrize("case", ["missing", "duplicate", "gap", "semantic", "cutoff", "overlap", "mixed_basis", "root_mapping"])
def test_ttm_requires_eight_distinct_contiguous_compatible_observations(case):
    prior, current = ttm(2024), ttm(2025)
    legs = current["source_lineage"]["derivation_inputs"]
    if case == "missing":
        legs.pop()
    elif case == "duplicate":
        legs[0]["observation_id"] = prior["source_lineage"]["derivation_inputs"][0]["observation_id"]
    elif case == "gap":
        legs[1]["period_start"] = "2025-04-02"
    elif case == "semantic":
        legs[1]["source_lineage"]["raw_concept_qname"] = "other"
    elif case == "cutoff":
        legs[1]["selection_as_of_date"] = "2026-10-24"
    elif case == "overlap":
        legs[0]["period_start"] = current["period_start"] = "2024-12-31"
    elif case == "root_mapping":
        current["canonical_mapping_version"] = "m2"
    else:
        legs[1]["basis_version"] = "restated"
    result = compare_periods(current, prior, "TTM", CUTOFF, {})
    assert result["reason"] in {"INCOMPATIBLE_TTM_LINEAGE", "INCOMPATIBLE_PERIOD"}
    assert result["yoy"] is None


def test_ttm_uses_published_levels_and_preserves_both_windows():
    result = compare_periods({**ttm(2025), "value": "500"}, ttm(2024), "TTM", CUTOFF, {})
    assert result["yoy"] == "25"
    assert result["delta"] == "100"
    assert len(set(result["ttm_input_ids"]["prior"] + result["ttm_input_ids"]["current"])) == 8


def test_quarter_pairs_use_issuer_fiscal_quarter_not_calendar_coordinate():
    prior = {**quarter(2024, 2), "calendar_year": 2024, "calendar_quarter": 2}
    current = {**quarter(2025, 2), "calendar_year": 2025, "calendar_quarter": 3}
    assert compare_periods(current, prior, "QTD_3M", CUTOFF, {})["yoy"] == "0"
    wrong = {**current, "fiscal_quarter": "Q3"}
    assert compare_periods(wrong, prior, "QTD_3M", CUTOFF, {})["reason"] == "INCOMPATIBLE_PERIOD"


def test_fcf_rejects_changed_capex_meaning_even_when_output_identity_matches():
    def fcf(year):
        legs = [quarter(year, 2, metric) for metric in ("quarter_cfo", "quarter_capex")]
        return {
            **legs[0], "observation_id": f"FCF{year}", "metric_id": "quarter_standardized_fcf",
            "source_kind": "DERIVED_METRIC",
            "source_lineage": {"derivation_inputs": legs, "compatibility_policy": ARITHMETIC},
        }
    prior, current = fcf(2024), fcf(2025)
    assert compare_periods(current, prior, "QTD_3M", CUTOFF, {})["yoy"] == "0"
    changed = deepcopy(current)
    changed["source_lineage"]["derivation_inputs"][1]["source_lineage"]["raw_concept_qname"] = "capex-other"
    assert compare_periods(changed, prior, "QTD_3M", CUTOFF, {})["reason"] == "INCOMPATIBLE_SEMANTICS"
