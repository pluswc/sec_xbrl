from __future__ import annotations

from pathlib import Path

import pytest

from sec_xbrl.longitudinal import (
    CapabilityInventoryMaterializer,
    CapabilityInventoryQuery,
    Layer1SnapshotInput,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
)


def _candidate(*, cik: str = "0000320193", fact: str = "aapl-iphone", member: str | None = "iphone", review: bool = False) -> dict[str, object]:
    dimensions = () if member is None else (("product-axis", member, None, "explicit", False),)
    canonical_dimensions = () if member is None else (("company:product-axis", f"company:{member}", None, "explicit", False),)
    return {
        "series_candidate_id": f"candidate:{fact}", "cik": cik, "series_type": "CURRENT",
        "series_status": "REVIEW_REQUIRED" if review else "CANDIDATE",
        "unavailable_reason": "MAPPING_REVIEW_REQUIRED" if review else None,
        "raw_concept_id": "revenue", "company_canonical_concept_id": "company:revenue",
        "raw_dimension_signature": dimensions, "company_canonical_dimension_key": canonical_dimensions,
        "period_class": "QTD_3M", "actual_period_key": "2026-Q1", "source_fact_id": fact,
        "source_filing_id": f"filing:{cik}", "mapping_version": "map-v1", "source_locator": "table:1",
        "source_document": "report.htm", "mapping_review_required": review,
    }


def _focused_candidate(*, cik: str, fact: str, axis: str, member: str, role: str) -> dict[str, object]:
    raw_concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    return {
        **_candidate(cik=cik, fact=fact, member=None),
        "raw_concept_id": raw_concept,
        "company_canonical_concept_id": "company:revenue",
        "raw_dimension_signature": ((axis, member, None, "explicit", False),),
        "company_canonical_dimension_key": ((f"canonical:{axis}", f"canonical:{member}", None, "explicit", False),),
        "source_locator": f"{role}/table",
    }


def _unavailable(candidate: dict[str, object], reason: str = "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS") -> dict[str, object]:
    return {
        "cik": candidate["cik"], "series_type": candidate["series_type"],
        "company_canonical_concept_id": candidate["company_canonical_concept_id"],
        "company_canonical_dimension_key": candidate["company_canonical_dimension_key"],
        "period_class": candidate["period_class"], "period_key": candidate["actual_period_key"],
        "source_type": "UNAVAILABLE", "unavailable_reason": reason,
        "selection_rule_version": "selection-v1", "selected_fact_id": None,
    }


def test_inventory_lists_only_observed_dimensions_and_query_is_explicit_about_not_reported() -> None:
    candidate = _candidate()
    result = CapabilityInventoryMaterializer().materialize(
        company_ciks=("0000320193", "0001045810"), series_candidates=(candidate,),
        analytical_facts=(_unavailable(candidate),),
        source_evidence_by_fact_id={"aapl-iphone": {"role_id": "role:income", "disclosure_id": "note:revenue"}},
    )
    aapl = [row for row in result.inventory if row["cik"] == "0000320193"]
    dimension = next(row for row in aapl if row["capability_type"] == "DIMENSION_MEMBER")
    assert dimension["axis_raw_concept_id"] == "product-axis"
    assert dimension["member_raw_concept_id"] == "iphone"
    assert dimension["capability_status"] == "NOT_COMPARABLE"
    assert dimension["source_role_ids"] == ("role:income",)
    assert not any(row.get("member_raw_concept_id") == "segment" for row in aapl)
    query = CapabilityInventoryQuery(result.inventory)
    missing = query.discover(cik="0000320193", axis_raw_concept_id="geography-axis")
    assert missing[0]["capability_status"] == "NOT_REPORTED"
    assert query.discover(cik="0001045810")[0]["capability_status"] == "PROCESSING_UNAVAILABLE"


def test_statuses_keep_processing_mapping_and_comparability_separate() -> None:
    available = _candidate(fact="nvda-segment", cik="0001045810", member="compute")
    review = _candidate(fact="nvda-review", cik="0001045810", member=None, review=True)
    excluded = {"cik": "0001045810", "source_fact_id": "bad-fact", "source_filing_id": "q1", "raw_concept_id": "bad", "exclusion_reason": "MISSING_OR_UNRESOLVED_CONTEXT"}
    rows = CapabilityInventoryMaterializer().materialize(
        company_ciks=("0001045810",), series_candidates=(available, review),
        processing_exclusions=(excluded,),
    ).inventory
    assert {row["capability_status"] for row in rows} == {"AVAILABLE", "MAPPING_REVIEW_REQUIRED", "PROCESSING_UNAVAILABLE"}


def test_seven_company_corpus_has_company_local_coverage_without_a_shared_template() -> None:
    ciks = ("0000320193", "0001045810", "0001318605", "0000002488", "0001652044", "0001326801", "0001065280")
    candidates = tuple(_candidate(cik=cik, fact=f"fact:{cik}", member=f"member:{cik}") for cik in ciks)
    rows = CapabilityInventoryMaterializer().materialize(company_ciks=ciks, series_candidates=candidates).inventory
    assert {row["cik"] for row in rows} == set(ciks)
    assert {row["member_raw_concept_id"] for row in rows if row["capability_type"] == "DIMENSION_MEMBER"} == {f"member:{cik}" for cik in ciks}


def test_aapl_and_nvda_focused_dimension_evidence_stays_company_local() -> None:
    # These raw IDs deliberately model actual company extension namespaces.
    # The implementation only copies observed input identities; it has no
    # ticker-specific branch or built-in product/segment/geography template.
    aapl = _focused_candidate(
        cik="0000320193", fact="aapl-iphone-revenue", axis="aapl:ProductAndServiceAxis",
        member="aapl:IPhoneMember", role="role:aapl-products",
    )
    nvda = _focused_candidate(
        cik="0001045810", fact="nvda-us-revenue", axis="nvidia:GeographicalAreasAxis",
        member="nvidia:UnitedStatesMember", role="role:nvda-geography",
    )
    result = CapabilityInventoryMaterializer().materialize(
        company_ciks=("0000320193", "0001045810"), series_candidates=(aapl, nvda),
        source_evidence_by_fact_id={
            "aapl-iphone-revenue": {"role_id": "role:aapl-products", "disclosure_id": "aapl:products-note"},
            "nvda-us-revenue": {"role_id": "role:nvda-geography", "disclosure_id": "nvda:geography-note"},
        },
    )
    query = CapabilityInventoryQuery(result.inventory)
    assert query.discover(cik="0000320193", axis_raw_concept_id="aapl:ProductAndServiceAxis")[0]["member_raw_concept_id"] == "aapl:IPhoneMember"
    assert query.discover(cik="0001045810", axis_raw_concept_id="nvidia:GeographicalAreasAxis")[0]["member_raw_concept_id"] == "nvidia:UnitedStatesMember"
    assert query.discover(cik="0001045810", axis_raw_concept_id="aapl:ProductAndServiceAxis")[0]["capability_status"] == "NOT_REPORTED"


def test_inventory_is_publisher_ready_and_rejects_undeclared_company(tmp_path: Path) -> None:
    result = CapabilityInventoryMaterializer().materialize(company_ciks=("0000320193",), series_candidates=(_candidate(),))
    run = Layer2Run(
        run_version="m5-fixture", corpus_run_id="fixture",
        inputs=(Layer1SnapshotInput(cik="0000320193", accession="fixture", form="10-Q", filed_date="2026-05-01", report_date="2026-03-28", snapshot_id="fixture", manifest_sha256="a" * 64),),
        rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
    )
    output = Layer2Publisher(tmp_path / "layer2").publish(run, result.as_datasets())
    assert output.output_counts == {"capability_inventory": 2}
    with pytest.raises(ValueError, match="outside declared"):
        CapabilityInventoryMaterializer().materialize(company_ciks=("0000320193",), series_candidates=(_candidate(cik="0001045810"),))


def test_publisher_rejects_fabricated_dimension_without_member_or_source_lineage(tmp_path: Path) -> None:
    row = next(
        item for item in CapabilityInventoryMaterializer().materialize(
            company_ciks=("0000320193",), series_candidates=(_candidate(),)
        ).inventory if item["capability_type"] == "DIMENSION_MEMBER"
    )
    invalid = {**row, "member_raw_concept_id": None}
    run = Layer2Run(
        run_version="m5-invalid", corpus_run_id="fixture",
        inputs=(Layer1SnapshotInput(cik="0000320193", accession="fixture", form="10-Q", filed_date="2026-05-01", report_date="2026-03-28", snapshot_id="fixture", manifest_sha256="a" * 64),),
        rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
    )
    with pytest.raises(Exception, match="axis and member"):
        Layer2Publisher(tmp_path / "layer2").publish(run, {"capability_inventory": (invalid,)})
    invalid = {**row, "source_fact_ids": ()}
    with pytest.raises(Exception, match="source Fact/filing lineage"):
        Layer2Publisher(tmp_path / "layer2").publish(run, {"capability_inventory": (invalid,)})


def test_publisher_requires_inventory_coverage_for_every_declared_input(tmp_path: Path) -> None:
    row = next(iter(CapabilityInventoryMaterializer().materialize(
        company_ciks=("0000320193",), series_candidates=(_candidate(),)
    ).inventory))
    run = Layer2Run(
        run_version="m5-coverage", corpus_run_id="fixture",
        inputs=(
            Layer1SnapshotInput(cik="0000320193", accession="aapl", form="10-Q", filed_date="2026-05-01", report_date="2026-03-28", snapshot_id="aapl", manifest_sha256="a" * 64),
            Layer1SnapshotInput(cik="0001045810", accession="nvda", form="10-Q", filed_date="2026-05-01", report_date="2026-04-26", snapshot_id="nvda", manifest_sha256="b" * 64),
        ),
        rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
    )
    with pytest.raises(Exception, match="every declared input CIK"):
        Layer2Publisher(tmp_path / "layer2").publish(run, {"capability_inventory": (row,)})
