from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.analytics import (
    AnalyticalRepository,
    CapabilityInventoryNotFoundError,
    DerivedMetricConflictError,
    DerivedMetricNotFoundError,
)
from sec_xbrl.metrics import DerivedMetricPublisher, DerivedMetricsRun
from sec_xbrl.metrics.series import DerivedMetricSeriesError


def _companies() -> tuple[dict[str, str], ...]:
    return (
        {"cik": "0000320193", "ticker": "AAPL", "company_canonical_id": "company:aapl"},
        {"cik": "0001045810", "ticker": "NVDA", "company_canonical_id": "company:nvda"},
    )


def _capabilities() -> tuple[dict[str, object], ...]:
    return (
        {
            "capability_inventory_id": "capability:aapl:iphone",
            "cik": "0000320193",
            "capability_type": "DIMENSION_MEMBER",
            "capability_status": "AVAILABLE",
            "status_reason": None,
            "raw_concept_id": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "axis_raw_concept_id": "aapl:ProductAndServiceAxis",
            "member_raw_concept_id": "aapl:IPhoneMember",
            "period_classes": ("QTD_3M",),
            "series_types": ("CURRENT",),
            "source_fact_ids": ("aapl:iphone-revenue",),
            "source_filing_ids": ("aapl:2026-q1",),
            "source_role_ids": ("role:aapl-products",),
            "source_disclosure_ids": ("aapl:products-note",),
            "source_locator": "products/table-1",
            "capability_inventory_version": "l2-m5-capability-inventory-v1",
        },
        {
            "capability_inventory_id": "capability:nvda:us",
            "cik": "0001045810",
            "capability_type": "DIMENSION_MEMBER",
            "capability_status": "NOT_COMPARABLE",
            "status_reason": "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS",
            "raw_concept_id": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "axis_raw_concept_id": "nvidia:GeographicalAreasAxis",
            "member_raw_concept_id": "nvidia:UnitedStatesMember",
            "period_classes": ("QTD_3M",),
            "series_types": ("CURRENT",),
            "source_fact_ids": ("nvda:us-revenue",),
            "source_filing_ids": ("nvda:2026-q3",),
            "source_role_ids": ("role:nvda-geography",),
            "source_disclosure_ids": ("nvda:geography-note",),
            "source_locator": "geography/table-1",
            "capability_inventory_version": "l2-m5-capability-inventory-v1",
        },
    )


def _metric_record(
    record_id: str,
    *,
    value: str | None = "40",
    cik: str = "0000320193",
) -> dict[str, object]:
    available = value is not None
    return {
        "derived_metric_id": record_id,
        "metric_definition_id": "gross_margin@1.0.0",
        "metric_id": "gross_margin",
        "metric_definition_version": "1.0.0",
        "formula_id": "gross-profit-over-revenue",
        "formula_version": "v1",
        "cik": cik,
        "view": "AS_FILED",
        "as_of_date": "2026-05-01",
        "basis_version": "as-filed-v1",
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": "FY26-Q1",
        "company_canonical_dimension_key": (),
        "input_unit_semantics": "USD",
        "metric_unit_semantics": "PERCENT",
        "calculation_status": "AVAILABLE" if available else "UNAVAILABLE",
        "metric_value_decimal": value,
        "unavailable_reason": None if available else "M6_HANDOFF_INVALID:missing input",
        "source_type": "DERIVED_METRIC",
        "calculated_at": "2026-05-01T00:00:00+00:00" if available else None,
        "evaluated_at": "2026-05-01T00:00:00+00:00",
        "metric_input_handoff_version": "l2-m6-v1",
        "metric_input_compatibility_id": "compatibility:gross-margin",
        "mapping_versions": ("map-v1",),
        "ordered_input_candidate_ids": ("candidate:profit", "candidate:revenue"),
        "ordered_input_analytical_fact_ids": ("fact:profit", "fact:revenue"),
        "ordered_input_lineage": (
            {"selected_fact_id": "raw:profit", "source_type": "REPORTED", "source_fact_ids": ("raw:profit",)},
            {"selected_fact_id": "raw:revenue", "source_type": "REPORTED", "source_fact_ids": ("raw:revenue",)},
        ),
        "derived_metrics_contract_version": "derived-metrics-m1-materialization-v1",
    }


def _published(tmp_path, *records: dict[str, object]):
    run = DerivedMetricsRun("consumer-c0-fixture", "l2-fingerprint", "registry-v1", "seed-v1")
    return DerivedMetricPublisher(tmp_path / "metrics").publish(run, records)


def test_capability_discovery_resolves_public_selector_and_preserves_observed_rows() -> None:
    inventory = list(_capabilities())
    repository = AnalyticalRepository(companies=_companies(), capability_inventory=inventory)

    rows = repository.discover_capabilities(
        "AAPL",
        raw_concept_id="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_raw_concept_id="aapl:ProductAndServiceAxis",
        period_class="QTD_3M",
    )

    assert rows[0]["member_raw_concept_id"] == "aapl:IPhoneMember"
    assert rows[0]["source_role_ids"] == ("role:aapl-products",)
    assert rows[0]["source_disclosure_ids"] == ("aapl:products-note",)
    assert rows[0]["capability_status"] == "AVAILABLE"
    rows[0]["source_role_ids"] = ()
    assert repository.discover_capabilities("320193")[0]["source_role_ids"] == ("role:aapl-products",)


def test_capability_discovery_returns_m5_not_reported_without_cross_company_template() -> None:
    repository = AnalyticalRepository(companies=_companies(), capability_inventory=_capabilities())

    row = repository.discover_capabilities(
        "NVDA", axis_raw_concept_id="aapl:ProductAndServiceAxis"
    )[0]

    assert row == {
        "cik": "0001045810",
        "capability_type": "REQUEST",
        "capability_status": "NOT_REPORTED",
        "status_reason": "NO_OBSERVED_COMPANY_STRUCTURE_MATCHES_REQUEST",
        "requested_raw_concept_id": None,
        "requested_axis_raw_concept_id": "aapl:ProductAndServiceAxis",
        "requested_member_raw_concept_id": None,
        "requested_period_class": None,
        "capability_inventory_version": "l2-m5-capability-inventory-v1",
    }
    assert repository.discover_capabilities("NVDA")[0]["capability_status"] == "NOT_COMPARABLE"


def test_capability_discovery_fails_clearly_when_resolved_company_has_no_inventory() -> None:
    repository = AnalyticalRepository(companies=_companies(), capability_inventory=_capabilities()[:1])

    with pytest.raises(CapabilityInventoryNotFoundError, match="no supplied capability inventory"):
        repository.discover_capabilities("NVDA")


def test_trace_metric_keeps_verified_unavailable_record_and_full_lineage(tmp_path) -> None:
    record = _metric_record("metric:unavailable", value=None)
    publication = _published(tmp_path, record)
    repository = AnalyticalRepository(
        companies=_companies(), metric_series_run_roots=(publication.run_root,)
    )

    result = repository.trace_metric("metric:unavailable")

    assert result["calculation_status"] == "UNAVAILABLE"
    assert result["metric_value_decimal"] is None
    assert result["unavailable_reason"] == "M6_HANDOFF_INVALID:missing input"
    assert result["ordered_input_lineage"][0]["selected_fact_id"] == "raw:profit"
    assert result["ordered_input_lineage"][1]["selected_fact_id"] == "raw:revenue"
    lineage = deepcopy(result["ordered_input_lineage"])
    assert result["source_metric_run_fingerprint"] == publication.fingerprint
    result["ordered_input_lineage"] = ()
    assert repository.trace_metric("metric:unavailable")["ordered_input_lineage"] == lineage


def test_trace_metric_rejects_conflicting_verified_identity_and_unverified_root(tmp_path) -> None:
    first = _published(tmp_path / "first", _metric_record("metric:conflict", value="40"))
    second = _published(tmp_path / "second", _metric_record("metric:conflict", value="41"))
    repository = AnalyticalRepository(
        companies=_companies(), metric_series_run_roots=(first.run_root, second.run_root)
    )

    with pytest.raises(DerivedMetricConflictError, match="conflicting records"):
        repository.trace_metric("metric:conflict")
    with pytest.raises(DerivedMetricNotFoundError):
        repository.trace_metric("metric:missing")
    with pytest.raises(DerivedMetricSeriesError, match="incomplete"):
        AnalyticalRepository(companies=_companies(), metric_series_run_roots=(tmp_path / "unverified",))
