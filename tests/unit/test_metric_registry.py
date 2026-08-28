from __future__ import annotations

from dataclasses import replace

import pytest

from sec_xbrl.metrics.registry import MetricDefinitionError, seed_metric_registry


def _candidate(role: str, *, status: str = "CANDIDATE", source_type: str = "REPORTED") -> dict[str, object]:
    return {
        "metric_input_candidate_id": f"candidate:{role}",
        "metric_input_role": role,
        "candidate_status": status,
        "source_type": source_type,
        "selected_fact_id": "fact:1",
    }


def _compatibility(definition_id: str, roles: tuple[str, ...]) -> dict[str, object]:
    return {
        "metric_definition_id": definition_id,
        "compatibility_status": "ELIGIBLE",
        "required_input_roles": roles,
    }


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
    with pytest.raises(MetricDefinitionError, match="candidate roles"):
        registry.validate_handoff(
            definition_id="gross_margin@1.0.0",
            candidates=(_candidate("REVENUE"), _candidate("GROSS_PROFIT")),
            compatibility=_compatibility("gross_margin@1.0.0", ("GROSS_PROFIT", "REVENUE")),
        )


def test_eps_rejects_non_direct_candidate() -> None:
    registry = seed_metric_registry()
    with pytest.raises(MetricDefinitionError, match="direct-observation-only"):
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


def test_definition_dependency_cycles_are_rejected() -> None:
    registry = seed_metric_registry()
    gross = registry.resolve("gross_margin@1.0.0")
    operating = registry.resolve("operating_margin@1.0.0")
    with pytest.raises(MetricDefinitionError, match="cycle"):
        type(registry)((replace(gross, dependency_metric_ids=("operating_margin",)),
                        replace(operating, dependency_metric_ids=("gross_margin",))))
