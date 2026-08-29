from __future__ import annotations

from copy import deepcopy

from sec_xbrl.analytics import AnalyticalRepository, ConsumerDataAccess
from sec_xbrl.metrics import DerivedMetricPublisher, DerivedMetricsRun


def _companies() -> tuple[dict[str, str], ...]:
    return (
        {"cik": "0000320193", "ticker": "AAPL", "company_canonical_id": "company:aapl"},
        {"cik": "0001045810", "ticker": "NVDA", "company_canonical_id": "company:nvda"},
    )


def _metric(
    metric_id: str,
    record_id: str,
    *,
    cik: str = "0000320193",
    period_key: str = "FY26-Q1",
    period_class: str = "QTD_3M",
    view: str = "AS_FILED",
    basis_version: str = "as-filed-v1",
    dimension_key: tuple[tuple[str, str], ...] = (),
    value: str | None = "40",
) -> dict[str, object]:
    available = value is not None
    input_source_type = "RECAST_REPORTED" if view == "CURRENT_COMPARABLE" else "REPORTED"
    input_lineage = (
        {
            "selected_fact_id": "raw:numerator",
            "source_type": input_source_type,
            "source_fact_ids": ("raw:numerator",),
        },
        {
            "selected_fact_id": "raw:denominator",
            "source_type": input_source_type,
            "source_fact_ids": ("raw:denominator",),
        },
    )
    if input_source_type == "RECAST_REPORTED":
        input_lineage = tuple(
            item | {"recast_evidence_id": "evidence:metric-fixture"}
            for item in input_lineage
        )
    return {
        "derived_metric_id": record_id,
        "metric_definition_id": f"{metric_id}@1.0.0",
        "metric_id": metric_id,
        "metric_definition_version": "1.0.0",
        "formula_id": f"{metric_id}-formula",
        "formula_version": "v1",
        "cik": cik,
        "view": view,
        "as_of_date": "2026-05-01",
        "basis_version": basis_version,
        "series_type": "CURRENT",
        "period_class": period_class,
        "period_key": period_key,
        "company_canonical_dimension_key": dimension_key,
        "input_unit_semantics": "USD",
        "metric_unit_semantics": "PERCENT",
        "calculation_status": "AVAILABLE" if available else "UNAVAILABLE",
        "metric_value_decimal": value,
        "unavailable_reason": None if available else "M6_HANDOFF_INVALID:missing input",
        "source_type": "DERIVED_METRIC",
        "calculated_at": "2026-05-01T00:00:00+00:00" if available else None,
        "evaluated_at": "2026-05-01T00:00:00+00:00",
        "metric_input_handoff_version": "l2-m6-v1",
        "metric_input_compatibility_id": f"compatibility:{metric_id}",
        "mapping_versions": ("map-v1",),
        "ordered_input_candidate_ids": ("candidate:numerator", "candidate:denominator"),
        "ordered_input_analytical_fact_ids": ("fact:numerator", "fact:denominator"),
        "ordered_input_lineage": input_lineage,
        "derived_metrics_contract_version": "derived-metrics-m1-materialization-v1",
    }


def _repository(tmp_path, *records: dict[str, object]) -> AnalyticalRepository:
    run = DerivedMetricsRun("consumer-c1-fixture", "l2-fingerprint", "registry-v1", "seed-v1")
    publication = DerivedMetricPublisher(tmp_path / "metrics").publish(run, records)
    return AnalyticalRepository(
        companies=_companies(), metric_series_run_roots=(publication.run_root,)
    )


def test_publication_backed_repository_conforms_to_consumer_data_access_protocol(tmp_path) -> None:
    repository = _repository(tmp_path, _metric("gross_margin", "metric:aapl:gm"))

    assert isinstance(repository, ConsumerDataAccess)


def test_discover_metrics_keeps_variant_grain_and_verified_publication_provenance(tmp_path) -> None:
    repository = _repository(
        tmp_path,
        _metric("gross_margin", "metric:aapl:base", period_key="FY26-Q1"),
        _metric("gross_margin", "metric:aapl:later", period_key="FY26-Q2"),
        _metric(
            "gross_margin",
            "metric:aapl:dimension",
            basis_version="product-basis-v2",
            dimension_key=(("aapl:ProductAxis", "aapl:IPhoneMember"),),
        ),
        _metric("gross_margin", "metric:aapl:unavailable", value=None),
        _metric("operating_margin", "metric:aapl:op"),
        _metric("gross_margin", "metric:nvda:gm", cik="0001045810"),
    )

    rows = repository.discover_metrics("AAPL", metric_id="gross_margin", frequency="QTD_3M")

    assert [row["metric_discovery_status"] for row in rows] == ["OBSERVED"] * 3
    assert [row["basis_version"] for row in rows] == [
        "as-filed-v1",
        "as-filed-v1",
        "product-basis-v2",
    ]
    available = next(row for row in rows if row["calculation_status"] == "AVAILABLE")
    assert available["observed_period_keys"] == ("FY26-Q1", "FY26-Q2")
    assert available["source_metric_run_fingerprints"]
    assert available["metric_series_candidate_ids"]
    assert {row["derived_metric_id"] for row in available["observed_metric_records"]} == {
        "metric:aapl:base",
        "metric:aapl:later",
    }
    unavailable = next(row for row in rows if row["calculation_status"] == "UNAVAILABLE")
    assert unavailable["unavailable_reason"] == "M6_HANDOFF_INVALID:missing input"
    dimensional = next(row for row in rows if row["basis_version"] == "product-basis-v2")
    assert dimensional["company_canonical_dimension_key"] == [
        ["aapl:ProductAxis", "aapl:IPhoneMember"],
    ]


def test_discover_metrics_filters_exactly_and_returns_scoped_not_reported(tmp_path) -> None:
    repository = _repository(
        tmp_path,
        _metric("gross_margin", "metric:aapl:as-filed"),
        _metric("gross_margin", "metric:aapl:comparable", view="CURRENT_COMPARABLE"),
        _metric("gross_margin", "metric:nvda:gm", cik="0001045810"),
    )

    comparable = repository.discover_metrics("AAPL", metric_id="gross_margin", view="CURRENT_COMPARABLE")
    assert len(comparable) == 1
    assert comparable[0]["view"] == "CURRENT_COMPARABLE"
    assert repository.discover_metrics("AAPL", metric_id="operating_margin") == (
        {
            "cik": "0000320193",
            "company_canonical_id": "company:aapl",
            "metric_discovery_status": "NOT_REPORTED",
            "status_reason": "NO_ADMITTED_VERIFIED_METRIC_MATCHES_REQUEST",
            "metric_discovery_scope": "SUPPLIED_VERIFIED_METRIC_PUBLICATIONS_ONLY",
            "requested_metric_id": "operating_margin",
            "requested_definition_version": None,
            "requested_frequency": None,
            "requested_view": None,
        },
    )
    assert repository.discover_metrics("NVDA", metric_id="gross_margin")[0]["cik"] == "0001045810"


def test_discover_metrics_is_deterministic_and_returns_deep_copies(tmp_path) -> None:
    records = (
        _metric("gross_margin", "metric:aapl:q2", period_key="FY26-Q2"),
        _metric("gross_margin", "metric:aapl:q1", period_key="FY26-Q1"),
    )
    repository = _repository(tmp_path, *records)
    first = repository.discover_metrics("AAPL")
    second = repository.discover_metrics("AAPL")

    assert first == second
    expected = deepcopy(first)
    first[0]["observed_metric_records"][0]["ordered_input_lineage"] = ()
    assert repository.discover_metrics("AAPL") == expected
