from __future__ import annotations

from pathlib import Path

import pytest

from sec_xbrl.longitudinal import MetricInputHandoffMaterializer
from sec_xbrl.metrics import (
    METRIC_REGISTRY_CONTRACT_VERSION,
    DerivedMetricMaterializationError,
    DerivedMetricMaterializer,
    DerivedMetricPublisher,
    DerivedMetricsRun,
    seed_metric_registry,
)


def _fact(
    fact_id: str,
    concept: str,
    value: str,
    *,
    period: str = "FY26-Q1",
    comparison_period_key: str | None = None,
) -> dict[str, object]:
    return {
        "analytical_fact_id": fact_id,
        "cik": "0000320193",
        "raw_concept_id": concept,
        "selected_fact_id": f"raw:{fact_id}",
        "source_filing_id": "filing:q1",
        "view": "CURRENT_COMPARABLE",
        "as_of_date": "2026-05-01",
        "basis_version": "basis-v1",
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": period,
        "company_canonical_dimension_key": (),
        "unit_semantics": "USD",
        "mapping_version": "map-v1",
        "source_type": "REPORTED",
        "comparison_period_key": comparison_period_key,
        "value_decimal": value,
    }


def _handoff(*facts: dict[str, object]):
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=facts,
        metric_definition_ids={
            "GROSS_MARGIN": "gross_margin@1.0.0",
            "OPERATING_MARGIN": "operating_margin@1.0.0",
            "REVENUE_GROWTH": "revenue_growth@1.0.0",
        },
    )
    return result


def _inputs(candidates: tuple[dict[str, object], ...], facts: tuple[dict[str, object], ...]):
    by_fact = {str(row["analytical_fact_id"]): row for row in facts}
    return tuple(
        {
            "metric_input_candidate_id": candidate["metric_input_candidate_id"],
            "analytical_fact_id": candidate["analytical_fact_id"],
            "value_decimal": by_fact[str(candidate["analytical_fact_id"])]["value_decimal"],
            **{
                key: candidate[key]
                for key in (
                    "source_filing_id",
                    "view",
                    "as_of_date",
                    "basis_version",
                    "series_type",
                    "period_class",
                    "period_key",
                    "company_canonical_dimension_key",
                    "unit_semantics",
                    "mapping_version",
                    "source_type",
                )
            },
        }
        for candidate in candidates
    )


def _eligible(result, assessment: str, period: str = "FY26-Q1") -> dict[str, object]:
    return next(
        row
        for row in result.compatibility
        if row["metric_assessment_id"] == assessment
        and row["period_key"] == period
        and row["compatibility_status"] == "ELIGIBLE"
    )


def _candidates(result, diagnostic: dict[str, object]) -> tuple[dict[str, object], ...]:
    by_id = {str(row["metric_input_candidate_id"]): row for row in result.candidates}
    return tuple(by_id[str(key)] for key in diagnostic["input_metric_input_candidate_ids"])


def test_m6_to_registry_to_materialized_margin_keeps_full_lineage() -> None:
    facts = (
        _fact("revenue", "us-gaap:Revenues", "200"),
        _fact("gross", "us-gaap:GrossProfit", "80"),
    )
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "GROSS_MARGIN")
    candidates = _candidates(handoff, diagnostic)
    row = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="gross_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=_inputs(candidates, facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert row["metric_value_decimal"] == "40"
    assert row["metric_unit_semantics"] == "PERCENT"
    assert row["formula_version"] == "v1"
    assert row["ordered_input_selected_fact_ids"] == ("raw:gross", "raw:revenue")
    assert row["ordered_input_lineage"][0]["value_decimal"] == "80"


def test_growth_uses_declared_predecessor_and_decimal_percent() -> None:
    facts = (
        _fact("current", "us-gaap:Revenues", "125", comparison_period_key="FY25-Q1"),
        _fact("prior", "us-gaap:Revenues", "100", period="FY25-Q1"),
    )
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "REVENUE_GROWTH")
    candidates = _candidates(handoff, diagnostic)
    row = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="revenue_growth@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=_inputs(candidates, facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert row["metric_value_decimal"] == "25"
    assert row["comparison_period_key"] == "FY25-Q1"


def test_missing_or_mismatched_selected_value_is_reasoned_unavailable() -> None:
    facts = (
        _fact("revenue", "us-gaap:Revenues", "200"),
        _fact("gross", "us-gaap:GrossProfit", "80"),
    )
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "GROSS_MARGIN")
    candidates = _candidates(handoff, diagnostic)
    values = list(_inputs(candidates, facts))
    values[0]["basis_version"] = "wrong-basis"
    row = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="gross_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=values,
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert row["calculation_status"] == "UNAVAILABLE"
    assert row["metric_value_decimal"] is None
    assert "provenance mismatch" in row["unavailable_reason"]
    row = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="gross_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=(),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert "no selected observation value" in row["unavailable_reason"]


def test_ineligible_handoff_is_unavailable_and_direct_q4_are_rejected() -> None:
    facts = (_fact("revenue", "us-gaap:Revenues", "200"),)
    handoff = _handoff(*facts)
    unavailable = next(
        row for row in handoff.compatibility if row["metric_assessment_id"] == "GROSS_MARGIN"
    )
    candidate = next(row for row in handoff.candidates if row["analytical_fact_id"] == "revenue")
    materializer = DerivedMetricMaterializer(seed_metric_registry())
    row = materializer.materialize(
        definition_id="gross_margin@1.0.0",
        candidates=(candidate,),
        compatibility=unavailable,
        selected_observation_values=_inputs((candidate,), facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert row["calculation_status"] == "UNAVAILABLE"
    assert row["source_type"] == "DERIVED_METRIC"
    with pytest.raises(DerivedMetricMaterializationError, match="only DERIVED"):
        materializer.materialize(
            definition_id="eps@1.0.0",
            candidates=(),
            compatibility={},
            selected_observation_values=(),
            evaluated_at="2026-08-28T00:00:00+00:00",
        )
    with pytest.raises(DerivedMetricMaterializationError, match="eligibility-only"):
        materializer.materialize(
            definition_id="q4_flow_eligibility@1.0.0",
            candidates=(),
            compatibility={},
            selected_observation_values=(),
            evaluated_at="2026-08-28T00:00:00+00:00",
        )


def test_zero_denominator_is_unavailable_with_evaluation_lineage() -> None:
    facts = (
        _fact("revenue", "us-gaap:Revenues", "0"),
        _fact("gross", "us-gaap:GrossProfit", "80"),
    )
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "GROSS_MARGIN")
    candidates = _candidates(handoff, diagnostic)
    row = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="gross_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=_inputs(candidates, facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    assert row["calculation_status"] == "UNAVAILABLE"
    assert row["metric_value_decimal"] is None
    assert row["calculated_at"] is None
    assert row["evaluated_at"] == "2026-08-28T00:00:00+00:00"
    assert "denominator is zero" in row["unavailable_reason"]
    assert row["ordered_input_lineage"][0]["selected_fact_id"] == "raw:gross"


def test_atomic_publisher_reuses_same_run_and_rejects_different_output(tmp_path: Path) -> None:
    facts = (
        _fact("revenue", "us-gaap:Revenues", "200"),
        _fact("operating", "us-gaap:OperatingIncomeLoss", "50"),
    )
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "OPERATING_MARGIN")
    candidates = _candidates(handoff, diagnostic)
    record = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="operating_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=_inputs(candidates, facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    run = DerivedMetricsRun(
        "m1-fixture", "layer2-fingerprint", METRIC_REGISTRY_CONTRACT_VERSION, "seed-v1"
    )
    publisher = DerivedMetricPublisher(tmp_path / "metrics")
    first = publisher.publish(run, (record,))
    second = publisher.publish(run, (record,))
    assert first.reused_existing is False
    assert second.reused_existing is True
    changed = {**record, "metric_value_decimal": "25.1"}
    with pytest.raises(DerivedMetricMaterializationError, match="different output"):
        publisher.publish(run, (changed,))


def test_publisher_keeps_unavailable_metric_non_numeric(tmp_path: Path) -> None:
    facts = (_fact("revenue", "us-gaap:Revenues", "0"), _fact("gross", "us-gaap:GrossProfit", "80"))
    handoff = _handoff(*facts)
    diagnostic = _eligible(handoff, "GROSS_MARGIN")
    candidates = _candidates(handoff, diagnostic)
    record = DerivedMetricMaterializer(seed_metric_registry()).materialize(
        definition_id="gross_margin@1.0.0",
        candidates=candidates,
        compatibility=diagnostic,
        selected_observation_values=_inputs(candidates, facts),
        evaluated_at="2026-08-28T00:00:00+00:00",
    )
    run = DerivedMetricsRun("unavailable-fixture", "layer2-fingerprint", METRIC_REGISTRY_CONTRACT_VERSION, "seed-v1")
    output = DerivedMetricPublisher(tmp_path / "metrics").publish(run, (record,))
    assert output.output_count == 1
    invalid = {**record, "metric_value_decimal": "999"}
    with pytest.raises(DerivedMetricMaterializationError, match="reason and no numeric"):
        DerivedMetricPublisher(tmp_path / "bad").publish(run, (invalid,))
