from __future__ import annotations

from dataclasses import replace

import pytest

from sec_xbrl.longitudinal.metric_input import MetricInputHandoffMaterializer
from sec_xbrl.metrics.registry import MetricDefinitionError, seed_metric_registry


def _candidate(role: str, *, status: str = "CANDIDATE", source_type: str = "REPORTED") -> dict[str, object]:
    return {
        "metric_input_candidate_id": f"candidate:{role}",
        "analytical_fact_id": f"candidate:{role}",
        "metric_input_role": role,
        "candidate_status": status,
        "source_type": source_type,
        "selected_fact_id": "fact:1",
        "source_fact_ids": (),
        "source_filing_id": "filing:1",
        "cik": "0000320193",
        "view": "AS_FILED",
        "as_of_date": "2026-08-28",
        "basis_version": None,
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": "2026-Q1",
        "company_canonical_dimension_key": (),
        "unit_semantics": "USD",
        "mapping_version": "map-v1",
        "metric_input_handoff_version": "l2-m6-metric-input-handoff-v1",
    }


def _compatibility(definition_id: str, roles: tuple[str, ...]) -> dict[str, object]:
    return {
        "metric_input_compatibility_id": "compatibility:1",
        "cik": "0000320193",
        "metric_definition_id": definition_id,
        "view": "AS_FILED",
        "as_of_date": "2026-08-28",
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": "2026-Q1",
        "basis_version": None,
        "company_canonical_dimension_key": (),
        "unit_semantics": "USD",
        "mapping_versions": ("map-v1",),
        "compatibility_status": "ELIGIBLE",
        "required_input_roles": roles,
        "input_metric_input_candidate_ids": tuple(f"candidate:{role}" for role in roles),
        "input_role_bindings": tuple(
            {
                "metric_input_candidate_id": f"candidate:{role}",
                "assessment_input_role": role,
            }
            for role in roles
        ),
        "input_analytical_fact_ids": tuple(f"candidate:{role}" for role in roles),
        "input_selected_fact_ids": ("fact:1",) * len(roles),
        "metric_input_handoff_version": "l2-m6-metric-input-handoff-v1",
    }


def _m6_fact(fact_id: str, concept: str, **overrides: object) -> dict[str, object]:
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
        "period_key": "FY26-Q1",
        "company_canonical_dimension_key": (),
        "unit_semantics": "usd",
        "mapping_version": "map-v1",
        "source_type": "REPORTED",
        **overrides,
    }


def _m6_records_for(
    candidates: tuple[dict[str, object], ...], diagnostic: dict[str, object]
) -> tuple[dict[str, object], ...]:
    by_id = {str(candidate["metric_input_candidate_id"]): candidate for candidate in candidates}
    return tuple(by_id[str(item)] for item in diagnostic["input_metric_input_candidate_ids"])


def test_seed_registry_has_controlled_versioned_definitions() -> None:
    registry = seed_metric_registry()
    definition = registry.resolve("gross_margin@1.0.0")

    assert definition.formula is not None
    assert definition.formula.expression == "GROSS_PROFIT / REVENUE"
    assert registry.resolve("eps@1.0.0").direct_observation_required is True


def test_registry_accepts_eligible_l2_m6_handoff_without_calculating() -> None:
    registry = seed_metric_registry()
    registry.validate_handoff(
        definition_id="gross_margin@1.0.0",
        candidates=(_candidate("GROSS_PROFIT"), _candidate("REVENUE")),
        compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
    )


@pytest.mark.parametrize("field", ("value", "metric_value", "formula_result", "derived_metric_id"))
def test_registry_rejects_calculated_values(field: str) -> None:
    registry = seed_metric_registry()
    candidate = _candidate("GROSS_PROFIT")
    candidate[field] = 1
    with pytest.raises(MetricDefinitionError, match="calculated"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(candidate, _candidate("REVENUE")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )


def test_registry_rejects_prohibited_null_formula_and_incomplete_provenance() -> None:
    registry = seed_metric_registry()
    candidate = _candidate("GROSS_PROFIT")
    candidate["formula"] = None
    with pytest.raises(MetricDefinitionError, match="calculated"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(candidate, _candidate("REVENUE")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )
    candidate = _candidate("GROSS_PROFIT")
    del candidate["source_filing_id"]
    with pytest.raises(MetricDefinitionError, match="provenance"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(candidate, _candidate("REVENUE")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )


def test_registry_rejects_unavailable_and_unlinked_compatibility() -> None:
    registry = seed_metric_registry()
    unavailable = _candidate("GROSS_PROFIT")
    unavailable["candidate_status"] = "UNAVAILABLE"
    unavailable["source_type"] = "UNAVAILABLE"
    with pytest.raises(MetricDefinitionError, match="unavailable"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(unavailable, _candidate("REVENUE")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("unit_semantics", "EUR"), ("company_canonical_dimension_key", ("region:us",))),
)
def test_registry_rejects_scope_mismatch_with_compatibility(field: str, value: object) -> None:
    registry = seed_metric_registry()
    compatibility = _compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE"))
    compatibility[field] = value
    with pytest.raises(MetricDefinitionError, match=field):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(_candidate("GROSS_PROFIT"), _candidate("REVENUE")),
            compatibility=compatibility,
        )
    compatibility = _compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE"))
    compatibility["input_analytical_fact_ids"] = ("wrong", "also-wrong")
    with pytest.raises(MetricDefinitionError, match="analytical Fact IDs"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(_candidate("GROSS_PROFIT"), _candidate("REVENUE")),
            compatibility=compatibility,
        )


def test_registry_rejects_raw_name_inference_and_wrong_roles() -> None:
    registry = seed_metric_registry()
    raw_candidate = _candidate("GROSS_PROFIT")
    raw_candidate["raw_concept_id"] = "us-gaap:GrossProfit"
    with pytest.raises(MetricDefinitionError, match="raw concept"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(raw_candidate, _candidate("REVENUE")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )
    with pytest.raises(MetricDefinitionError, match="analytical Fact IDs"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(_candidate("REVENUE"), _candidate("GROSS_PROFIT")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )


def test_eps_rejects_non_direct_candidate() -> None:
    registry = seed_metric_registry()
    with pytest.raises(MetricDefinitionError, match="cannot use derived"):
        registry.validate_direct_observation(
            definition_id="eps@1.0.0",
            candidate=_candidate("EPS", source_type="DERIVED_RECAST"),
        )


def test_eps_accepts_direct_l2_m6_candidate() -> None:
    registry = seed_metric_registry()
    registry.validate_direct_observation(
        definition_id="eps@1.0.0",
        candidate=_candidate("EPS", status="DIRECT_OBSERVATION_ONLY"),
    )


def test_registry_integrates_with_actual_m6_margin_growth_q4_and_direct_candidates() -> None:
    registry = seed_metric_registry()
    result = MetricInputHandoffMaterializer().materialize(
        analytical_facts=(
            _m6_fact("revenue", "us-gaap:Revenues", comparison_period_key="FY25-Q1"),
            _m6_fact("prior", "us-gaap:Revenues", period_key="FY25-Q1"),
            _m6_fact("gross", "us-gaap:GrossProfit"),
            _m6_fact("operating", "us-gaap:OperatingIncomeLoss"),
            _m6_fact(
                "q4", "us-gaap:Revenues", period_key="FY26-Q4", source_type="DERIVED_RECAST",
                derived_observation_id="q4", source_fact_ids=("fy", "ytd"),
                derivation_rule_version="q4-v1", formula="FY-YTD",
            ),
            _m6_fact("eps", "us-gaap:EarningsPerShareDiluted"),
        ),
        metric_definition_ids={
            "GROSS_MARGIN": "gross_margin@1.0.0",
            "OPERATING_MARGIN": "operating_margin@1.0.0",
            "REVENUE_GROWTH": "revenue_growth@1.0.0",
            "Q4_FLOW": "q4_flow_eligibility@1.0.0",
        },
    )
    for assessment, definition_id in (
        ("GROSS_MARGIN", "gross_margin@1.0.0"),
        ("OPERATING_MARGIN", "operating_margin@1.0.0"),
        ("REVENUE_GROWTH", "revenue_growth@1.0.0"),
        ("Q4_FLOW", "q4_flow_eligibility@1.0.0"),
    ):
        diagnostic = next(
            row for row in result.compatibility
            if row["metric_assessment_id"] == assessment and row["compatibility_status"] == "ELIGIBLE"
        )
        registry.validate_handoff(
            definition_id=definition_id,
            candidates=_m6_records_for(result.candidates, diagnostic),
            compatibility=diagnostic,
        )
    eps = next(row for row in result.candidates if row["metric_input_role"] == "EPS")
    registry.validate_direct_observation(definition_id="eps@1.0.0", candidate=eps)


def test_definition_dependency_cycles_are_rejected() -> None:
    registry = seed_metric_registry()
    gross = registry.resolve("gross_margin@1.0.0")
    operating = registry.resolve("operating_margin@1.0.0")
    with pytest.raises(MetricDefinitionError, match="cycle"):
        type(registry)((replace(gross, dependency_metric_ids=("operating_margin",)),
                        replace(operating, dependency_metric_ids=("gross_margin",))))
