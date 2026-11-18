from __future__ import annotations

from copy import deepcopy

from sec_xbrl.longitudinal import PeriodObservationMaterializer
from sec_xbrl.periods.integrity import fiscal_coordinate_problem
from tests.unit.test_period_observation_materialization import _snapshot


def test_conflict_preserves_raw_focus_and_accounts_for_every_fact_without_coordinates():
    snapshot = _snapshot(year=2025)
    snapshot["filing"]["document_fiscal_year_focus"] = "2027"
    before = deepcopy(snapshot)
    result = PeriodObservationMaterializer().materialize(**snapshot)
    assert not result.observations
    assert len(result.exclusions) == len(snapshot["facts"])
    assert all(row["exclusion_reason"] == "FISCAL_FOCUS_REPORT_DATE_CONFLICT" for row in result.exclusions)
    assert all(row["reported_document_fiscal_year_focus"] == "2027" and row["effective_fiscal_coordinate"] is None for row in result.exclusions)
    assert all(row["classification_rule_version"] == "fiscal-coordinate-integrity-v1" for row in result.exclusions)
    assert snapshot == before


def test_named_fiscal_year_one_year_difference_is_not_automatically_corrected():
    assert fiscal_coordinate_problem({"report_date": "2025-06-27", "document_fiscal_year_focus": "2026"}) is None
    assert fiscal_coordinate_problem({"report_date": "2025-06-27", "document_fiscal_year_focus": "2027"}) == "FISCAL_FOCUS_REPORT_DATE_CONFLICT"
    assert fiscal_coordinate_problem({"report_date": "2025-06-27"}) is None


def test_effective_corrected_copy_retains_original_focus_without_weakening_registry():
    snapshot = _snapshot(year=2025)
    snapshot["filing"].update(document_fiscal_year_focus="2025", reported_document_fiscal_year_focus="2027",
        effective_document_fiscal_year_focus="2025", fiscal_focus_correction_id="fixture-approved",
        fiscal_focus_correction_artifact_sha256="a" * 64, fiscal_focus_correction_provenance={"approval_sha256": "b" * 64})
    result = PeriodObservationMaterializer().materialize(**snapshot)
    assert result.observations
    assert all(row["fiscal_year"] in {2024, 2025} for row in result.observations)
    assert all(row["reported_document_fiscal_year_focus"] == "2027" for row in result.observations)
    assert all(row["fiscal_focus_correction_provenance"]["approval_sha256"] == "b" * 64 for row in result.observations)


def test_conflict_provenance_survives_operational_layer2_parquet_roundtrip(tmp_path):
    from sec_xbrl.longitudinal import Layer2PublicationReader, OperationalLayer2Publisher
    from tests.unit.test_layer2_materialization import _datasets, _run

    snapshot = _snapshot(year=2025)
    snapshot["filing"]["document_fiscal_year_focus"] = "2027"
    result = PeriodObservationMaterializer().materialize(**snapshot)
    datasets = {"analytical_fact": _datasets()["analytical_fact"], "period_observation_exclusion": list(result.exclusions)}
    publication = OperationalLayer2Publisher(tmp_path).publish(_run(version="fixture-fiscal-integrity-v1"), datasets)
    reopened = Layer2PublicationReader().load(publication.run_root).records("period_observation_exclusion")
    assert {row["source_fact_id"] for row in reopened} == {row["source_fact_id"] for row in result.exclusions}
    for row in reopened:
        assert row["reported_document_fiscal_year_focus"] == "2027"
        assert row["effective_fiscal_coordinate"] is None
        assert row["classification_rule_version"] == "fiscal-coordinate-integrity-v1"
        assert row["exclusion_reason"] == "FISCAL_FOCUS_REPORT_DATE_CONFLICT"
