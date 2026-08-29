from __future__ import annotations

import pytest

from sec_xbrl.analytics.repository import AnalyticalRepository
from sec_xbrl.metrics import (
    DerivedMetricPublisher,
    DerivedMetricSeriesError,
    DerivedMetricSeriesMaterializer,
    DerivedMetricsRun,
)


def _record(
    record_id: str,
    *,
    period: str,
    view: str,
    basis: str,
    as_of: str,
    value: str | None = "40",
    cik: str = "0000320193",
) -> dict[str, object]:
    available = value is not None
    source_type = "RECAST_REPORTED" if view == "CURRENT_COMPARABLE" else "REPORTED"
    return {
        "derived_metric_id": record_id,
        "metric_definition_id": "gross_margin@1.0.0",
        "metric_id": "gross_margin",
        "metric_definition_version": "1.0.0",
        "formula_id": "gross-profit-over-revenue",
        "formula_version": "v1",
        "cik": cik,
        "view": view,
        "as_of_date": as_of,
        "basis_version": basis,
        "series_type": "CURRENT",
        "period_class": "QTD_3M",
        "period_key": period,
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
            {"selected_fact_id": "raw:profit", "source_type": source_type, "recast_evidence_id": "evidence:profit" if view == "CURRENT_COMPARABLE" else None, "source_fact_ids": ("raw:profit",)},
            {"selected_fact_id": "raw:revenue", "source_type": source_type, "recast_evidence_id": "evidence:revenue" if view == "CURRENT_COMPARABLE" else None, "source_fact_ids": ("raw:revenue",)},
        ),
        "derived_metrics_contract_version": "derived-metrics-m1-materialization-v1",
    }


def _published(tmp_path, *records: dict[str, object]):
    run = DerivedMetricsRun("m1-fixture", "l2-fingerprint", "registry-v1", "seed-v1")
    return DerivedMetricPublisher(tmp_path / "metrics").publish(run, records)


def test_candidate_keeps_verified_manifest_and_full_non_coalescing_identity(tmp_path) -> None:
    source = _record("metric:one", period="FY26-Q1", view="AS_FILED", basis="as-filed-v1", as_of="2026-05-01")
    publication = _published(tmp_path, source)
    candidate = DerivedMetricSeriesMaterializer().load_published_candidates(publication.run_root)[0]
    assert candidate["source_metric_run_fingerprint"] == publication.fingerprint
    assert candidate["metric_series_key"]
    assert candidate["metric_series_contract_version"] == "derived-metrics-m2-series-v1"
    assert source["derived_metric_id"] == "metric:one"  # source was not rewritten


def test_as_filed_uses_earliest_revision_but_current_comparable_never_mixes_basis(tmp_path) -> None:
    records = (
        _record("as-q1-old", period="FY26-Q1", view="AS_FILED", basis="as-filed-v1", as_of="2026-05-01", value="40"),
        _record("as-q1-later", period="FY26-Q1", view="AS_FILED", basis="as-filed-v1", as_of="2026-08-01", value="41"),
        _record("current-q1-new", period="FY26-Q1", view="CURRENT_COMPARABLE", basis="recast-v2", as_of="2026-08-01", value="42"),
        _record("current-q2-old", period="FY26-Q2", view="CURRENT_COMPARABLE", basis="old-v1", as_of="2026-05-01", value="43"),
    )
    materializer = DerivedMetricSeriesMaterializer()
    candidates = materializer.load_published_candidates(_published(tmp_path, *records).run_root)
    as_filed = materializer.select(candidates, as_of_date="2026-08-31", view="AS_FILED")
    assert len(as_filed) == 1
    assert as_filed[0]["selected_derived_metric_id"] == "as-q1-old"
    comparable = materializer.select(candidates, as_of_date="2026-08-31", view="CURRENT_COMPARABLE")
    by_period = {row["period_key"]: row for row in comparable}
    assert by_period["FY26-Q1"]["metric_value_decimal"] == "42"
    assert by_period["FY26-Q2"]["metric_selection_status"] == "UNAVAILABLE"
    assert by_period["FY26-Q2"]["metric_selection_reason"] == "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS"


def test_unavailable_and_tampered_or_fabricated_publication_fail_closed(tmp_path) -> None:
    materializer = DerivedMetricSeriesMaterializer()
    bad = _record("bad", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01", value=None)
    bad["metric_value_decimal"] = "1"
    with pytest.raises(Exception, match="reason and no numeric"):
        _published(tmp_path, bad)
    with pytest.raises(DerivedMetricSeriesError, match="incomplete"):
        materializer.load_published_candidates(tmp_path / "fabricated")
    publication = _published(tmp_path, _record("good", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01"))
    payload = publication.run_root / "derived_metric.jsonl"
    payload.write_text(payload.read_text(encoding="utf-8").replace('"40"', '"999"'), encoding="utf-8")
    with pytest.raises(DerivedMetricSeriesError, match="content hash"):
        materializer.load_published_candidates(publication.run_root)


def test_no_input_unavailable_metric_is_admitted_and_queryable_without_fallback(tmp_path) -> None:
    record = _record("metric:no-input", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01", value=None)
    record.update({
        "ordered_input_candidate_ids": (),
        "ordered_input_analytical_fact_ids": (),
        "ordered_input_lineage": (),
        "input_lineage_status": "NO_COMPATIBLE_INPUTS",
        "metric_input_compatibility_status": "UNAVAILABLE",
        "metric_input_diagnostic_reason": "REQUIRED_INPUT_NOT_AVAILABLE",
        "metric_input_required_roles": ("GROSS_PROFIT", "REVENUE"),
        "input_metric_input_candidate_ids": (),
        "input_role_bindings": (),
    })
    publication = _published(tmp_path, record)
    repository = AnalyticalRepository(
        companies=({"cik": "0000320193", "ticker": "AAPL"},),
        metric_series_run_roots=(publication.run_root,),
    )

    selected = repository.get_metric_series(
        "AAPL", "gross_margin", as_of_date="2026-05-02", view="AS_FILED"
    )[0]
    assert selected["calculation_status"] == "UNAVAILABLE"
    assert selected["metric_value_decimal"] is None
    assert selected["unavailable_reason"] == "M6_HANDOFF_INVALID:missing input"
    assert selected["ordered_input_lineage"] == []
    assert repository.discover_metrics("AAPL", metric_id="gross_margin")[0]["observed_metric_records"][0]["input_lineage_status"] == "NO_COMPATIBLE_INPUTS"
    assert repository.trace_metric("metric:no-input")["unavailable_reason"] == "M6_HANDOFF_INVALID:missing input"


def test_available_metric_without_input_lineage_is_rejected(tmp_path) -> None:
    record = _record("metric:available-no-input", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01")
    record.update({
        "ordered_input_candidate_ids": (),
        "ordered_input_analytical_fact_ids": (),
        "ordered_input_lineage": (),
        "input_lineage_status": "NO_COMPATIBLE_INPUTS",
    })
    with pytest.raises(Exception, match="lacks source input lineage"):
        _published(tmp_path, record)


def test_no_input_metric_requires_m6_unavailable_diagnostic_not_default_coercion(tmp_path) -> None:
    record = _record("metric:forged-no-input", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01", value=None)
    record.update({
        "ordered_input_candidate_ids": (),
        "ordered_input_analytical_fact_ids": (),
        "ordered_input_lineage": (),
        "input_lineage_status": "NO_COMPATIBLE_INPUTS",
        "metric_input_compatibility_status": "ELIGIBLE",
        "metric_input_diagnostic_reason": "REQUIRED_INPUT_NOT_AVAILABLE",
    })
    with pytest.raises(Exception, match="M6 UNAVAILABLE compatibility"):
        _published(tmp_path, record)


def test_current_comparable_requires_recast_evidence_even_from_verified_m1_run(tmp_path) -> None:
    record = _record("metric:current", period="FY26-Q1", view="CURRENT_COMPARABLE", basis="recast-v2", as_of="2026-08-01")
    record["ordered_input_lineage"] = tuple(
        {**item, "recast_evidence_id": None} for item in record["ordered_input_lineage"]
    )
    publication = _published(tmp_path, record)
    with pytest.raises(DerivedMetricSeriesError, match="recast evidence"):
        DerivedMetricSeriesMaterializer().load_published_candidates(publication.run_root)


def test_comparable_basis_tie_is_stable_regardless_of_jsonl_order(tmp_path) -> None:
    first = _record("metric:a", period="FY26-Q1", view="CURRENT_COMPARABLE", basis="basis-a", as_of="2026-08-01")
    second = _record("metric:z", period="FY26-Q1", view="CURRENT_COMPARABLE", basis="basis-z", as_of="2026-08-01")
    materializer = DerivedMetricSeriesMaterializer()
    left = materializer.load_published_candidates(_published(tmp_path / "left", first, second).run_root)
    right = materializer.load_published_candidates(_published(tmp_path / "right", second, first).run_root)
    selected_left = materializer.select(left, as_of_date="2026-08-01", view="CURRENT_COMPARABLE")
    selected_right = materializer.select(right, as_of_date="2026-08-01", view="CURRENT_COMPARABLE")
    assert selected_left[0]["basis_version"] == selected_right[0]["basis_version"] == "basis-z"


def test_extra_or_missing_jsonl_rows_fail_manifest_count_or_hash(tmp_path) -> None:
    publication = _published(tmp_path, _record("metric:one", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01"))
    payload = publication.run_root / "derived_metric.jsonl"
    original = payload.read_text(encoding="utf-8")
    payload.write_text(original + original, encoding="utf-8")
    with pytest.raises(DerivedMetricSeriesError, match="count"):
        DerivedMetricSeriesMaterializer().load_published_candidates(publication.run_root)


def test_repository_queries_only_prebuilt_candidates_without_formula_execution(tmp_path) -> None:
    publication = _published(
        tmp_path, _record("metric:one", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01")
    )
    repository = AnalyticalRepository(
        companies=({"cik": "0000320193", "ticker": "AAPL"},),
        metric_series_run_roots=(publication.run_root,),
    )
    result = repository.get_metric_series(
        "AAPL", "gross_margin", as_of_date="2026-05-02", view="AS_FILED", frequency="QTD_3M"
    )
    assert result[0]["metric_value_decimal"] == "40"
    assert result[0]["selected_derived_metric_id"] == "metric:one"


@pytest.mark.parametrize("ticker,cik", (("AAPL", "0000320193"), ("NVDA", "0001045810"), ("TSLA", "0001318605")))
def test_same_contract_handles_aapl_nvda_and_tsla_metric_series(tmp_path, ticker: str, cik: str) -> None:
    publication = _published(
        tmp_path, _record(f"metric:{ticker}", period="FY26-Q1", view="AS_FILED", basis="v1", as_of="2026-05-01", cik=cik)
    )
    repository = AnalyticalRepository(companies=({"cik": cik, "ticker": ticker},), metric_series_run_roots=(publication.run_root,))
    assert repository.get_metric_series(ticker, "gross_margin", as_of_date="2026-05-01", view="AS_FILED")[0]["cik"] == cik
