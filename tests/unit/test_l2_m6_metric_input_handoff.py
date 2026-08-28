from __future__ import annotations

import pytest

from sec_xbrl.longitudinal import (
    Layer1SnapshotInput,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
    MetricInputHandoffMaterializer,
)


def _fact(
    fact_id: str,
    concept: str,
    *,
    period: str = "FY26-Q1",
    basis: str | None = "basis-v1",
    unit: str = "usd",
    dimensions: tuple[object, ...] = (),
    source_type: str = "REPORTED",
    role: str | None = None,
    comparison_period_key: str | None = None,
    **extra: object,
) -> dict[str, object]:
    return {
        "analytical_fact_id": fact_id,
        "cik": "0000320193",
        "raw_concept_id": concept,
        "metric_input_role": role,
        "selected_fact_id": f"raw:{fact_id}",
        "source_filing_id": "filing:q1",
        "view": "CURRENT_COMPARABLE",
        "as_of_date": "2026-05-01",
        "basis_version": basis,
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": period,
        "company_canonical_dimension_key": dimensions,
        "unit_semantics": unit,
        "mapping_version": "map-v1",
        "source_type": source_type,
        "comparison_period_key": comparison_period_key,
        **extra,
    }


def _diagnostic(
    rows: tuple[dict[str, object], ...], assessment: str, period: str = "FY26-Q1"
) -> dict[str, object]:
    return next(
        row
        for row in rows
        if row["metric_assessment_id"] == assessment and row["period_key"] == period
    )


def test_margin_inputs_are_eligible_only_with_same_governed_scope_and_keep_lineage() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact("revenue", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
            _fact("gross", "us-gaap:GrossProfit"),
            _fact("operating", "us-gaap:OperatingIncomeLoss"),
        ),
        metric_definition_ids={"GROSS_MARGIN": "metric:gross-margin-v1"},
    )
    gross = _diagnostic(result.compatibility, "GROSS_MARGIN")
    operating = _diagnostic(result.compatibility, "OPERATING_MARGIN")
    assert gross["compatibility_status"] == "ELIGIBLE"
    assert gross["metric_definition_id"] == "metric:gross-margin-v1"
    assert gross["input_analytical_fact_ids"] == ("gross", "revenue")
    assert operating["compatibility_status"] == "ELIGIBLE"
    candidate = next(row for row in result.candidates if row["analytical_fact_id"] == "gross")
    assert candidate["selected_fact_id"] == "raw:gross"
    assert candidate["source_filing_id"] == "filing:q1"
    assert "value_numeric" not in candidate


def test_incompatible_dimension_and_missing_predecessor_are_reasoned_unavailable() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact("revenue", "us-gaap:Revenues", dimensions=(("axis", "all"),)),
            _fact("gross", "us-gaap:GrossProfit", dimensions=(("axis", "product"),)),
        )
    )
    gross = _diagnostic(result.compatibility, "GROSS_MARGIN")
    growth = _diagnostic(result.compatibility, "REVENUE_GROWTH")
    assert gross["compatibility_status"] == "UNAVAILABLE"
    assert gross["unavailable_reason"] == "INCOMPATIBLE_COMPANY_CANONICAL_DIMENSION_KEY"
    assert growth["unavailable_reason"] == "PREDECESSOR_PERIOD_NOT_DECLARED"


def test_growth_requires_declared_prior_period_and_never_sorts_display_labels() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact("previous", "us-gaap:Revenues", period="FY25-Q1"),
            _fact("current", "us-gaap:Revenues", period="FY26-Q1", comparison_period_key="FY25-Q1"),
        )
    )
    assert (
        _diagnostic(result.compatibility, "REVENUE_GROWTH", "FY26-Q1")["compatibility_status"]
        == "ELIGIBLE"
    )
    assert (
        _diagnostic(result.compatibility, "REVENUE_GROWTH", "FY25-Q1")["unavailable_reason"]
        == "PREDECESSOR_PERIOD_NOT_DECLARED"
    )


def test_derived_eps_and_shares_are_unavailable_not_direct_observations() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact(
                "eps",
                "us-gaap:EarningsPerShareDiluted",
                source_type="DERIVED_RECAST",
                role="EPS",
                derived_observation_id="q4-eps",
                source_fact_ids=("fy", "ytd"),
                derivation_rule_version="v1",
                formula="FY-YTD",
            ),
            _fact(
                "shares",
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                source_type="DERIVED_RECAST",
                role="WEIGHTED_AVERAGE_SHARES",
                derived_observation_id="q4-shares",
                source_fact_ids=("fy", "ytd"),
                derivation_rule_version="v1",
                formula="FY-YTD",
            ),
        )
    )
    assert {row["candidate_status"] for row in result.candidates} == {"UNAVAILABLE"}
    assert {row["unavailable_reason"] for row in result.candidates} == {
        "DIRECT_OBSERVATION_REQUIRED"
    }
    q4 = [row for row in result.compatibility if row["metric_assessment_id"] == "Q4_FLOW"]
    assert {row["unavailable_reason"] for row in q4} == {
        "Q4_REVERSE_ENGINEERING_PROHIBITED_FOR_NON_ADDITIVE_OBSERVATION"
    }


def test_unavailable_direct_eps_retains_source_selection_reason() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact(
                "eps-unavailable",
                "us-gaap:EarningsPerShareDiluted",
                role="EPS",
                source_type="UNAVAILABLE",
                unavailable_reason="PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS",
            ),
        )
    )
    candidate = result.candidates[0]
    assert candidate["candidate_status"] == "UNAVAILABLE"
    assert candidate["unavailable_reason"] == "DIRECT_OBSERVATION_REQUIRED"
    assert (
        candidate["source_selection_unavailable_reason"] == "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS"
    )


def test_reported_eps_and_recast_reported_shares_are_direct_only() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact("eps", "us-gaap:EarningsPerShareDiluted", role="EPS"),
            _fact(
                "shares",
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                role="WEIGHTED_AVERAGE_SHARES",
                source_type="RECAST_REPORTED",
                recast_evidence_id="reviewed-recast",
            ),
        )
    )
    assert {row["candidate_status"] for row in result.candidates} == {"DIRECT_OBSERVATION_ONLY"}
    assert {row["unavailable_reason"] for row in result.candidates} == {
        "DIRECT_OBSERVATION_NO_REVERSE_ENGINEERING"
    }


def test_controlled_q4_requires_governed_lineage_but_does_not_calculate_value() -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _fact(
                "q4",
                "us-gaap:Revenues",
                source_type="DERIVED_RECAST",
                derived_observation_id="q4",
                source_fact_ids=("fy", "ytd"),
                derivation_rule_version="q4-v1",
                formula="FY-YTD",
            ),
        )
    )
    q4 = _diagnostic(result.compatibility, "Q4_FLOW")
    assert q4["compatibility_status"] == "ELIGIBLE"
    assert "metric_value" not in q4


def test_handoff_is_publisher_ready_and_calculated_values_are_rejected(tmp_path) -> None:
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(_fact("revenue", "us-gaap:Revenues"),)
    )
    run = Layer2Run(
        run_version="m6-fixture",
        corpus_run_id="fixture",
        inputs=(
            Layer1SnapshotInput(
                "0000320193", "fixture", "10-Q", "2026-05-01", "2026-03-28", "fixture", "a" * 64
            ),
        ),
        rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
    )
    output = Layer2Publisher(tmp_path / "layer2").publish(run, result.as_datasets())
    assert output.output_counts["metric_input_candidate"] == 1
    invalid = {**result.candidates[0], "metric_value": "0.5"}
    with pytest.raises(Exception, match="calculated metric value"):
        Layer2Publisher(tmp_path / "second").publish(run, {"metric_input_candidate": (invalid,)})


def test_aapl_and_nvda_style_selected_facts_use_identity_not_ticker_templates() -> None:
    # AAPL and NVDA use different company-local dimensional structures.  The
    # revenue role comes only from the standard QName, and the custom concept
    # requires explicit upstream role metadata: no ticker branch or label.
    aapl = _fact(
        "aapl-product-revenue",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        dimensions=(("aapl:ProductAndServiceAxis", "aapl:IPhoneMember"),),
    )
    nvda = {
        **_fact(
            "nvda-geography-revenue",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            dimensions=(("nvda:GeographicalAreasAxis", "nvda:UnitedStatesMember"),),
        ),
        "cik": "0001045810",
    }
    custom = _fact("company-custom", "aapl:CompanyAdjustedRevenue", role=None)
    result = MetricInputHandoffMaterializer().materialize(analytical_facts=(aapl, nvda, custom))
    assert {row["analytical_fact_id"] for row in result.candidates} == {
        "aapl-product-revenue",
        "nvda-geography-revenue",
    }
