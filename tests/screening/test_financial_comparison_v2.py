from copy import deepcopy
from types import SimpleNamespace

import pytest

from examples.screening import financial_comparison_v2 as v2
from examples.screening import prepare_financial_growth as v1
from tests.screening.test_financial_growth import CUTOFF, annual, quarter


def definition(metric, kind="MONEY", period="FY", **kwargs):
    return {"metric_id": metric, "definition_version": "v1", "unit_kind": kind,
            "unit": "USD" if kind == "MONEY" else "PERCENT", "period_class": period,
            "rule_version": "test-rule", **kwargs}


def reported(year, metric="cost", *, instant=False):
    row = {**annual(year), "metric_id": metric, "metric_observation_id": f"{metric}-{year}"}
    if instant:
        row.update(period_class="INSTANT", period_start=None, raw_concept_period_type="instant")
    return row


def ratio(year, *, instant=False):
    numerator, denominator = reported(year, "cost", instant=instant), reported(year, "revenue", instant=instant)
    row = {**reported(year, "gross_margin", instant=instant), "source_kind": "DERIVED_METRIC",
           "unit": "PERCENT", "value": "12.345", "formula": "cost / revenue * 100",
           "arithmetic_rule_version": "exact-v1"}
    refs = [{"observation_id": v1._id(leg), **{key: leg[key] for key in
             ("metric_id", "value", "fiscal_year", "period_class", "period_start", "period_end")}}
            for leg in (numerator, denominator)]
    row.update(input_values=refs, input_observation_ids=[ref["observation_id"] for ref in refs])
    return row, [numerator, denominator]


def ratio_pair(instant=False):
    current, now = ratio(2024, instant=instant)
    prior, before = ratio(2023, instant=instant)
    prior["value"] = "12.344999999999999999999999999999"
    catalog = {"gross_margin": definition("gross_margin", "PERCENT", "INSTANT" if instant else "FY",
               formula=current["formula"], input_metric_ids=["cost", "revenue"], arithmetic_rule_version="exact-v1"),
               **{key: definition(key) for key in ("cost", "revenue")}}
    return current, prior, {v1._id(leg): leg for leg in [*now, *before]}, catalog


@pytest.mark.parametrize("instant", [False, True])
def test_percentage_point_change_is_exact_and_never_ratio_growth(instant):
    current, prior, by_id, catalog = ratio_pair(instant)
    result = v2.compare(current, prior, CUTOFF, by_id, catalog)
    assert result["status"] == "CHANGE_AVAILABLE"
    assert result["change_pp"] == "0.000000000000000000000000000001"
    assert result["delta"] == result["change_pp"]
    assert result["yoy"] is result["negative_magnitude_change"] is None


@pytest.mark.parametrize(("field", "value"), [
    ("metric_definition_version", "other"), ("basis_version", "other"),
    ("semantic_identity", "other denominator"), ("value", "0"), ("value", "-1"),
    ("period_end", "2023-12-31"), ("dimensions", ["axis=member"]),
    ("financial_as_of", "2026-10-24"), ("unit", "EUR"),
])
def test_percentage_denominator_scope_and_identity_fail_closed(field, value):
    current, prior, by_id, catalog = ratio_pair()
    leg = by_id["revenue-2023"]
    leg[field] = value
    # Match the published reference when testing its underlying meaning, not merely ref tampering.
    if field in prior["input_values"][1]:
        prior["input_values"][1][field] = value
    result = v2.compare(current, prior, CUTOFF, by_id, catalog)
    assert result["status"] == "UNAVAILABLE"
    assert result["change_pp"] is result["delta"] is None


@pytest.mark.parametrize("change", ["missing", "duplicate", "formula", "cycle"])
def test_ratio_recursive_provenance_is_required(change):
    current, prior, by_id, catalog = ratio_pair()
    if change == "missing":
        by_id.pop("revenue-2023")
    elif change == "duplicate":
        prior["input_observation_ids"][1] = prior["input_observation_ids"][0]
    elif change == "formula":
        prior["formula"] = "different"
    else:
        by_id["revenue-2023"] = prior
    assert v2.compare(current, prior, CUTOFF, by_id, catalog)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize(("prior", "current", "status", "rate"), [
    ("100", "120", "RATE_AVAILABLE", "20"), ("100", "0", "ZERO_REACHED", "-100"),
    ("0", "100", "ZERO_BASE", None), ("-100", "-50", "NEGATIVE_MAGNITUDE_REDUCED", None),
    ("-100", "100", "POSITIVE_TURN", None), ("100", "-100", "NEGATIVE_TURN", None),
])
def test_instant_money_uses_same_fiscal_end_not_duration_or_ttm(prior, current, status, rate):
    before, after = reported(2023, instant=True), reported(2024, instant=True)
    before["value"], after["value"] = prior, current
    result = v2.compare(after, before, CUTOFF, {}, {"cost": definition("cost", period="INSTANT")})
    assert (result["status"], result["yoy"]) == (status, rate)
    assert result["current"]["period_start"] is None
    assert v2.compare(after, {**before, "period_end": "2023-01-01"}, CUTOFF, {},
                      {"cost": definition("cost")})["reason"] == "INCOMPATIBLE_PERIOD"


def test_catalog_publication_preserves_all_nine_legacy_results_and_adds_instant_and_percent():
    definitions = [definition(name) for name in v1.METRICS]
    quarter_definitions = [definition(prefix + name, period=basis) for basis, prefix in v1.BASIS_PREFIX.items()
                           if prefix for name in v1.METRICS]
    rows = [{**annual(year), "metric_id": name, "metric_observation_id": f"{name}-{year}"}
            for year in (2023, 2024) for name in v1.METRICS]
    current, prior, inputs, catalog = ratio_pair()
    definitions += list(catalog.values()) + [definition("cash", period="INSTANT")]
    rows += [current, prior, *inputs.values(), reported(2023, "cash", instant=True), reported(2024, "cash", instant=True)]
    quarters = [{**quarter(year, 1, "quarter_cfo"), "calendar_year": year, "calendar_quarter": 1}
                for year in (2023, 2024)]
    # Normalize actual quarterly catalog spelling: observation_basis, not period_class.
    quarter_definitions = [{**row, "observation_basis": row["period_class"]} for row in quarter_definitions]
    for row in quarter_definitions:
        row.pop("period_class")
    parent = SimpleNamespace(manifest={"financial_as_of": CUTOFF, "dataset_id": "sample"}, publication_id="P",
                             companies=[{"cik": "0000000001"}], metric_definitions=definitions,
                             quarter_definitions=quarter_definitions, observations=rows, quarter_observations=quarters)
    before = deepcopy(parent.observations)
    legacy, actual = v1.build_artifact(parent, "a" * 64), v2.build_artifact(parent, "a" * 64)
    assert actual["schema_version"] == v2.SCHEMA
    assert set(actual["definitions"]) == {row["metric_id"] for row in definitions + quarter_definitions}
    for metric in legacy["definitions"]:
        assert actual["companies"]["0000000001"].get(metric) == legacy["companies"]["0000000001"].get(metric)
    assert actual["companies"]["0000000001"]["gross_margin"]["2024"]["change_pp"] is not None
    assert actual["companies"]["0000000001"]["cash"]["2024"]["yoy"] == "0"
    assert parent.observations == before


def ttm_margin(year):
    numerator = [quarter(year, q, "quarter_operating_income") for q in range(1, 5)]
    denominator = [quarter(year, q, "quarter_revenue") for q in range(1, 5)]
    row = {**numerator[-1], "metric_id": "ttm_operating_margin", "observation_id": f"margin-{year}",
           "period_class": "TTM", "period_start": numerator[0]["period_start"], "unit": "PERCENT",
           "value": "12.5", "source_kind": "DERIVED_METRIC", "source_lineage": {
               "derivation_inputs": numerator + denominator, "derivation_rule_version": "test-rule",
               "formula": "SUM(numerator) * 100 / SUM(denominator)", "compatibility_policy": v1.ARITHMETIC}}
    catalog = {"ttm_operating_margin": definition("ttm_operating_margin", "PERCENT", "TTM",
               formula=row["source_lineage"]["formula"]),
               **{name: definition(name, period="QTD_3M") for name in ("quarter_operating_income", "quarter_revenue")}}
    return row, catalog


def test_ttm_percentage_points_validate_both_four_quarter_numerator_and_denominator_windows():
    current, catalog = ttm_margin(2024)
    prior, _ = ttm_margin(2023)
    prior["value"] = "10"
    result = v2.compare(current, prior, CUTOFF, {}, catalog)
    assert result["change_pp"] == "2.5"
    assert len(result["ttm_input_ids"]["current"]) == 8
    assert len(result["ttm_input_ids"]["prior"]) == 8


@pytest.mark.parametrize("change", ["gap", "duplicate", "missing", "zero_denominator", "mapping", "version", "cutoff", "formula"])
def test_ttm_percentage_points_fail_closed_for_invalid_denominator_lineage(change):
    current, catalog = ttm_margin(2024)
    prior, _ = ttm_margin(2023)
    legs = current["source_lineage"]["derivation_inputs"]
    if change == "gap":
        legs[-1]["period_start"] = "2024-10-02"
    elif change == "duplicate":
        legs[-1]["observation_id"] = legs[-2]["observation_id"]
    elif change == "missing":
        legs.pop()
    elif change == "zero_denominator":
        for leg in legs[4:]:
            leg["value"] = "0"
    elif change == "mapping":
        legs[-1]["canonical_mapping_version"] = "other"
    elif change == "version":
        legs[-1]["definition_version"] = "other"
    elif change == "cutoff":
        legs[-1]["selection_as_of_date"] = "2026-10-24"
    else:
        current["source_lineage"]["formula"] = "different"
    result = v2.compare(current, prior, CUTOFF, {}, catalog)
    assert result["status"] == "UNAVAILABLE"
    assert result["change_pp"] is result["delta"] is None


def test_unprepared_calculated_liabilities_remains_visible_with_specific_lineage_reason():
    current = {**quarter(2024, 1), "metric_id": "quarter_calculated_total_liabilities"}
    assert v2.compare(current, None, CUTOFF, {}, {})["reason"] == "SUPPORTED_LINEAGE_NOT_PREPARED"


@pytest.mark.parametrize(("values", "available"), [
    (["-100", "100", "100", "100"], True),
    (["-300", "100", "100", "100"], False),
    (["-301", "100", "100", "100"], False),
])
def test_ttm_percent_denominator_policy_applies_to_the_sum(values, available):
    current, catalog = ttm_margin(2024)
    prior, _ = ttm_margin(2023)
    for leg, value in zip(current["source_lineage"]["derivation_inputs"][4:], values):
        leg["value"] = value
    result = v2.compare(current, prior, CUTOFF, {}, catalog)
    assert (result["status"] == "CHANGE_AVAILABLE") is available
