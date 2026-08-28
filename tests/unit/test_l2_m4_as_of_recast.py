from __future__ import annotations

from sec_xbrl.longitudinal import (
    AnalyticalFactMaterializer,
    Layer1SnapshotInput,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
)


def _candidate(
    fact: str, filing: str, filed: str, period: str, value: str,
    *, status: str = "CANDIDATE",
) -> dict[str, object]:
    return {
        "series_candidate_id": f"candidate:{fact}",
        "cik": "0001045810",
        "series_type": "CURRENT",
        "series_status": status,
        "raw_concept_id": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "raw_dimension_signature": (("axis:geography", "member:us", None, "explicit", False),),
        "company_canonical_concept_id": "company:geographic-revenue",
        "company_canonical_dimension_key": (("axis:geography", "member:us", None, "explicit", False),),
        "unit_id": "usd",
        "unit_semantics": (("iso4217:USD",), ()),
        "period_class": "QTD_3M",
        "actual_period_boundaries": ("2026-01-01", "2026-03-31", None),
        "actual_period_key": period,
        "period_key": period,
        "source_fact_id": fact,
        "source_filing_id": filing,
        "filed_date": filed,
        "value_numeric": value,
        "mapping_version": "map-v1",
        "mapping_evidence": {"reviewed": True},
    }


def _evidence(fact: str, period: str) -> dict[str, object]:
    return {
        "recast_evidence_id": f"reviewed-geography:{fact}",
        "source_filing_id": "fy27-q1",
        "source_raw_fact_id": fact,
        "target_period_key": period,
        "basis_version": "geography-customer-hq-v2",
        "evidence_kind": "NARRATIVE_AND_TABLE",
        "source_document": "nvda-20260426.htm",
        "source_locator": "Geographic revenue note / reviewed linkage",
        "explicitly_represented": True,
        "prior_source_filing_ids": ("fy26-q1",),
    }


def test_nvidia_golden_shape_preserves_as_filed_and_never_mixes_incomplete_recast_basis() -> None:
    # These are the documented FY2026 US geography values used only as a
    # generic fixture.  No NVIDIA identifier or value participates in the
    # production selection rule.
    candidates = (
        _candidate("old-q1", "fy26-q1", "2025-05-28", "FY26-Q1", "20739"),
        _candidate("old-q2", "fy26-q2", "2025-08-27", "FY26-Q2", "23470"),
        _candidate("old-q3", "fy26-q3", "2025-11-19", "FY26-Q3", "39177"),
        _candidate("old-q4", "fy26-10k", "2026-02-25", "FY26-Q4", "51858"),
        _candidate("new-q1", "fy27-q1", "2026-05-20", "FY26-Q1", "25685"),
    )
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=candidates,
        recast_evidence=(_evidence("new-q1", "FY26-Q1"),),
        as_of_date="2026-05-21",
    )
    as_filed = {row["period_key"]: row for row in result.analytical_facts if row["view"] == "AS_FILED"}
    comparable = {row["period_key"]: row for row in result.analytical_facts if row["view"] == "CURRENT_COMPARABLE"}
    assert as_filed["FY26-Q1"]["value_numeric"] == "20739"
    assert as_filed["FY26-Q2"]["value_numeric"] == "23470"
    assert comparable["FY26-Q1"]["value_numeric"] == "25685"
    assert comparable["FY26-Q1"]["source_type"] == "RECAST_REPORTED"
    assert comparable["FY26-Q1"]["raw_concept_id"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert comparable["FY26-Q1"]["unit_semantics"] == (("iso4217:USD",), ())
    for period in ("FY26-Q2", "FY26-Q3", "FY26-Q4"):
        assert comparable[period]["source_type"] == "UNAVAILABLE"
        assert comparable[period]["unavailable_reason"] == "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS"
    assert len(result.recast_evidence) == 1


def test_numeric_change_without_reviewed_evidence_is_not_current_comparable() -> None:
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=(
            _candidate("old", "q1", "2025-05-01", "FY25-Q1", "100"),
            _candidate("changed", "q3", "2025-11-01", "FY25-Q1", "120"),
        ),
        as_of_date="2025-11-02",
    )
    comparable = next(row for row in result.analytical_facts if row["view"] == "CURRENT_COMPARABLE")
    assert comparable["source_type"] == "UNAVAILABLE"
    assert comparable["unavailable_reason"] == "UNKNOWN_OR_UNSUPPORTED_BASIS_VERSION"


def test_mapping_review_candidate_is_explicitly_unavailable_in_both_views() -> None:
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=(_candidate("review", "q1", "2025-05-01", "FY25-Q1", "100", status="REVIEW_REQUIRED"),),
        as_of_date="2025-05-02",
    )
    assert {row["source_type"] for row in result.analytical_facts} == {"UNAVAILABLE"}
    assert {row["unavailable_reason"] for row in result.analytical_facts} == {"MAPPING_REVIEW_REQUIRED"}


def test_m4_result_is_directly_publishable_with_evidence_lineage(tmp_path) -> None:
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=(
            _candidate("old", "fy26-q1", "2025-05-28", "FY26-Q1", "20739"),
            _candidate("new", "fy27-q1", "2026-05-20", "FY26-Q1", "25685"),
        ),
        recast_evidence=(_evidence("new", "FY26-Q1"),),
        as_of_date="2026-05-21",
    )
    run = Layer2Run(
        run_version="m4-fixture", corpus_run_id="fixture",
        inputs=(Layer1SnapshotInput(
            cik="0001045810", accession="fixture", form="10-Q", filed_date="2026-05-20",
            report_date="2026-04-26", snapshot_id="fixture/snapshot", manifest_sha256="a" * 64,
        ),),
        rules=Layer2RuleVersions("period-v1", "map-v1", "m9-recast-evidence-v1", "m7-as-of-selection-v1"),
    )
    published = Layer2Publisher(tmp_path / "layer2").publish(run, result.as_datasets())
    assert published.output_counts == {"analytical_fact": 2, "recast_evidence": 1}


def test_derived_recast_is_comparable_only_with_inputs_rule_and_evidence() -> None:
    previous = _candidate("old-q4", "fy25-10k", "2026-02-25", "FY25-Q4", "80")
    derived = {
        **_candidate("placeholder", "fy26-10k", "2027-02-25", "FY25-Q4", "90"),
        "source_fact_id": None,
        "source_fact_ids": ("fy-new", "ytd-new"),
        "derived_observation_id": "derived-q4-new",
        "reported_or_derived": "DERIVED",
        "derivation_rule_version": "q4-subtraction-v1",
        "formula": "FY - YTD_9M",
    }
    evidence = {
        **_evidence("fy-new", "FY25-Q4"),
        "source_filing_id": "fy26-10k",
        "source_derived_observation_id": "derived-q4-new",
        "prior_source_filing_ids": ("fy25-10k",),
    }
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=(previous, derived), recast_evidence=(evidence,), as_of_date="2027-02-26"
    )
    comparable = next(row for row in result.analytical_facts if row["view"] == "CURRENT_COMPARABLE")
    assert comparable["source_type"] == "DERIVED_RECAST"
    assert comparable["value_numeric"] == "90"
    assert comparable["selected_fact_id"] is None
    assert comparable["source_fact_ids"] == ("fy-new", "ytd-new")


def test_derived_candidate_without_governed_lineage_is_unavailable() -> None:
    derived = {
        **_candidate("placeholder", "fy26-10k", "2027-02-25", "FY25-Q4", "90"),
        "source_fact_id": None,
        "source_fact_ids": (),
        "derived_observation_id": "derived-q4-new",
        "reported_or_derived": "DERIVED",
        "derivation_rule_version": None,
        "formula": None,
    }
    result = AnalyticalFactMaterializer().materialize(
        current_candidates=(derived,), as_of_date="2027-02-26"
    )
    assert {row["source_type"] for row in result.analytical_facts} == {"UNAVAILABLE"}
    assert {row["unavailable_reason"] for row in result.analytical_facts} == {
        "DERIVED_RECAST_EVIDENCE_REQUIRED"
    }
