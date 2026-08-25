from __future__ import annotations

import pytest

from sec_xbrl.longitudinal import (
    AsOfSeriesSelector,
    RecastObservationBuilder,
    RecastObservationError,
)


def _rows() -> tuple[dict[str, object], ...]:
    common = {
        "cik": "0000123456", "company_canonical_concept_id": "company:revenue",
        "company_canonical_dimension_key": (("company:axis:geo", "company:member:us", None),),
        "unit_id": "usd", "period_class": "QTD_3M", "series_type": "CURRENT",
    }
    return (
        {**common, "fact_id": "old-q1", "source_filing_id": "q1", "filed_date": "2025-05-01", "period_key": "FY25-Q1", "value_numeric": "100"},
        {**common, "fact_id": "old-q2", "source_filing_id": "q2", "filed_date": "2025-08-01", "period_key": "FY25-Q2", "value_numeric": "110"},
        {**common, "fact_id": "new-q1", "source_filing_id": "q3", "filed_date": "2025-11-01", "period_key": "FY25-Q1", "value_numeric": "120"},
        {**common, "fact_id": "new-q2", "source_filing_id": "q3", "filed_date": "2025-11-01", "period_key": "FY25-Q2", "value_numeric": "130"},
    )


def _evidence(fact_id: str, period: str) -> dict[str, object]:
    return {
        "recast_evidence_id": "geo-method-change", "source_filing_id": "q3",
        "source_raw_fact_id": fact_id, "target_period_key": period,
        "basis_version": "geography-method-v2", "evidence_kind": "NARRATIVE_AND_TABLE",
        "source_document": "q3.htm", "source_locator": "Geographic Revenue note",
        "narrative_excerpt": "Prior period information has been recast.",
        "explicitly_represented": True, "prior_source_filing_ids": ("q1", "q2"),
    }


def test_builder_binds_later_reported_facts_to_explicit_recast_evidence() -> None:
    observations = RecastObservationBuilder().build(
        _rows(), evidence=(_evidence("new-q1", "FY25-Q1"), _evidence("new-q2", "FY25-Q2"))
    )
    recast = {row["fact_id"]: row for row in observations}
    assert recast["new-q1"]["source_type"] == "RECAST_REPORTED"
    assert recast["new-q1"]["basis_version"] == "geography-method-v2"
    assert recast["new-q1"]["recast_prior_raw_fact_ids"] == ("old-q1",)
    assert recast["old-q1"]["source_type"] == "REPORTED"
    assert recast["old-q1"]["basis_version"] is None
    assert recast["new-q1"]["recast_evidence"]["narrative_excerpt"]

    selected = AsOfSeriesSelector().select(
        observations, as_of_date="2025-11-02", view="LATEST_RECAST"
    )
    assert {row["selected_raw_fact_id"] for row in selected} == {"new-q1", "new-q2"}
    assert {row["basis_version"] for row in selected} == {"geography-method-v2"}


def test_builder_rejects_numeric_difference_without_explicit_recast_evidence() -> None:
    evidence = _evidence("new-q1", "FY25-Q1")
    evidence["explicitly_represented"] = False
    with pytest.raises(RecastObservationError, match="recast evidence"):
        RecastObservationBuilder().build(_rows(), evidence=(evidence,))


def test_builder_rejects_recast_when_same_scope_prior_is_absent() -> None:
    evidence = _evidence("new-q1", "FY25-Q1")
    evidence["prior_source_filing_ids"] = ("missing",)
    with pytest.raises(RecastObservationError, match="no earlier observation"):
        RecastObservationBuilder().build(_rows(), evidence=(evidence,))


def test_selector_never_promotes_unbound_later_comparative_fact() -> None:
    observations = RecastObservationBuilder().build(_rows())
    selected = AsOfSeriesSelector().select(
        observations, as_of_date="2025-11-02", view="LATEST_RECAST"
    )
    assert {row["status"] for row in selected} == {"N/A"}
    assert {row["unavailable_reason"] for row in selected} == {
        "UNKNOWN_OR_UNSUPPORTED_BASIS_VERSION"
    }


def test_builder_clears_unreviewed_caller_recast_metadata() -> None:
    rows = list(_rows())
    rows[-1] = {
        **rows[-1],
        "source_type": "RECAST_REPORTED",
        "basis_version": "unreviewed-v2",
        "recast_evidence_id": "invented",
        "recast_evidence": {"not": "validated"},
    }
    observations = RecastObservationBuilder().build(rows)
    row = next(item for item in observations if item["fact_id"] == "new-q2")
    assert row["source_type"] == "REPORTED"
    assert row["basis_version"] is None
    assert row["recast_evidence_id"] is None
    assert row["recast_evidence"] is None
    selected = AsOfSeriesSelector().select(
        observations, as_of_date="2025-11-02", view="LATEST_RECAST"
    )
    assert {item["status"] for item in selected} == {"N/A"}


def test_builder_rejects_evidence_with_unknown_source_fact_id() -> None:
    evidence = _evidence("not-a-fact", "FY25-Q1")
    with pytest.raises(RecastObservationError, match="unknown source raw Fact"):
        RecastObservationBuilder().build(_rows(), evidence=(evidence,))
