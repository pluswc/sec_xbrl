from __future__ import annotations

import pytest

from sec_xbrl.cross_company import (
    ComparisonPanelBuilder,
    CrossCompanyMapper,
    CrossCompanyRelation,
)


def _map(company_id: str, relation: CrossCompanyRelation, **extra: object) -> dict[str, object]:
    return {
        "company_canonical_id": company_id,
        "analytical_id": "analytical:CLOUD"
        if relation not in {CrossCompanyRelation.NOT_COMPARABLE, CrossCompanyRelation.UNRESOLVED}
        else None,
        "relation": relation,
        "confidence": 0.8,
        "evidence": {"disclosure": "Segment note"},
        "method": "REVIEWED_DISCLOSURE_SCOPE",
        "mapping_version": "m8-review-2026-01",
        **extra,
    }


def test_cloud_scopes_keep_subcategory_distinct_from_analytical_similarity() -> None:
    tables = CrossCompanyMapper().build(
        member_mappings=(
            _map("company:amzn:member:aws", CrossCompanyRelation.SUBCATEGORY_OF),
            _map("company:goog:member:google-cloud", CrossCompanyRelation.SUBCATEGORY_OF),
            _map(
                "company:msft:member:intelligent-cloud",
                CrossCompanyRelation.ANALYTICALLY_SIMILAR,
                confidence=0.55,
                evidence={"scope_note": "Includes server products and cloud services"},
            ),
        )
    )

    rows = ComparisonPanelBuilder().build(
        observations=(
            {
                "entity_type": "member",
                "source_raw_id": "amzn:AWSMember",
                "company_canonical_id": "company:amzn:member:aws",
                "filing_id": "amzn-10k-2025",
                "report_period": "2025-12-31",
            },
            {
                "entity_type": "member",
                "source_raw_id": "msft:IntelligentCloudMember",
                "company_canonical_id": "company:msft:member:intelligent-cloud",
                "filing_id": "msft-10k-2025",
                "report_period": "2025-06-30",
            },
        ),
        mappings=tables,
    )

    aws, intelligent_cloud = rows
    assert aws["analytical_id"] == intelligent_cloud["analytical_id"] == "analytical:CLOUD"
    assert aws["mapping_relation"] == CrossCompanyRelation.SUBCATEGORY_OF
    assert intelligent_cloud["mapping_relation"] == CrossCompanyRelation.ANALYTICALLY_SIMILAR
    assert intelligent_cloud["mapping_relation"] != CrossCompanyRelation.EQUIVALENT
    assert intelligent_cloud["mapping_review_required"] is True


def test_panel_preserves_raw_company_source_and_version_for_every_row() -> None:
    tables = CrossCompanyMapper().build(
        concept_mappings=(
            _map("company:amzn:concept:revenue", CrossCompanyRelation.EQUIVALENT, confidence=1.0),
        )
    )
    row = ComparisonPanelBuilder().build(
        observations=(
            {
                "raw_concept_id": "amzn:NetSales",
                "company_canonical_concept_id": "company:amzn:concept:revenue",
                "filing_id": "amzn-10k-2025",
                "period_class": "FY",
                "value": "638000000000",
            },
        ),
        mappings=tables,
    )[0]

    assert row["source_raw_id"] == "amzn:NetSales"
    assert row["company_canonical_id"] == "company:amzn:concept:revenue"
    assert row["analytical_id"] == "analytical:CLOUD"
    assert row["source_filing_id"] == "amzn-10k-2025"
    assert row["source_period"] == "FY"
    assert row["mapping_version"] == "m8-review-2026-01"


def test_exact_compatible_standard_taxonomy_identity_is_equivalent() -> None:
    tables = CrossCompanyMapper().build(
        standard_concept_observations=(
            {
                "cik": "0001045810",
                "filing_id": "nvda-10q",
                "raw_concept_id": "nvda:Revenue",
                "company_canonical_concept_id": "company:nvda:concept:revenue",
                "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "taxonomy_family": "us-gaap",
                "data_type": "xbrli:monetaryItemType",
                "period_type": "duration",
                "is_standard": True,
            },
            {
                "cik": "0000320193",
                "filing_id": "aapl-10q",
                "raw_concept_id": "aapl:Revenue",
                "company_canonical_concept_id": "company:aapl:concept:revenue",
                "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "taxonomy_family": "us-gaap",
                "data_type": "xbrli:monetaryItemType",
                "period_type": "duration",
                "is_standard": True,
            },
        )
    )

    assert len(tables.cross_company_concept_map) == 2
    assert {row["relation"] for row in tables.cross_company_concept_map} == {
        CrossCompanyRelation.EQUIVALENT
    }
    assert {row["analytical_id"] for row in tables.cross_company_concept_map} == {
        "analytical:standard:us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    }
    assert all(
        row["method"] == "EXACT_STANDARD_TAXONOMY_IDENTITY"
        for row in tables.cross_company_concept_map
    )
    assert all(
        row["evidence"]["source_filings"] == ["aapl-10q", "nvda-10q"]
        for row in tables.cross_company_concept_map
    )


def test_label_only_standard_claim_remains_unresolved_not_equivalent() -> None:
    tables = CrossCompanyMapper().build(
        standard_concept_observations=(
            {
                "cik": "0001045810",
                "filing_id": "nvda-10q",
                "raw_concept_id": "nvda:CloudLikeRevenue",
                "company_canonical_concept_id": "company:nvda:concept:cloud-like",
                "label": "Cloud revenue",
                "is_standard": False,
            },
            {
                "cik": "0000789019",
                "filing_id": "msft-10q",
                "raw_concept_id": "msft:CloudLikeRevenue",
                "company_canonical_concept_id": "company:msft:concept:cloud-like",
                "label": "Cloud revenue",
                "is_standard": False,
            },
        )
    )
    rows = ComparisonPanelBuilder().build(
        observations=(
            {
                "raw_concept_id": "nvda:CloudLikeRevenue",
                "company_canonical_concept_id": "company:nvda:concept:cloud-like",
                "filing_id": "nvda-10q",
                "period_end": "2026-04-26",
            },
        ),
        mappings=tables,
    )

    assert tables.cross_company_concept_map == ()
    assert rows[0]["mapping_relation"] == CrossCompanyRelation.UNRESOLVED
    assert rows[0]["mapping_confidence"] == 0.0


def test_explicit_mapping_cannot_silently_override_generated_standard_mapping() -> None:
    standard = {
        "cik": "0001045810",
        "filing_id": "nvda-10q",
        "raw_concept_id": "nvda:Revenue",
        "company_canonical_concept_id": "company:nvda:concept:revenue",
        "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "taxonomy_family": "us-gaap",
        "data_type": "xbrli:monetaryItemType",
        "period_type": "duration",
        "is_standard": True,
    }
    peer = {
        **standard,
        "cik": "0000320193",
        "filing_id": "aapl-10q",
        "company_canonical_concept_id": "company:aapl:concept:revenue",
    }
    with pytest.raises(ValueError, match="cannot duplicate"):
        CrossCompanyMapper().build(
            concept_mappings=(
                _map("company:nvda:concept:revenue", CrossCompanyRelation.ANALYTICALLY_SIMILAR),
            ),
            standard_concept_observations=(standard, peer),
        )


def test_low_confidence_and_unmapped_rows_remain_visible_with_versioned_status() -> None:
    tables = CrossCompanyMapper().build(
        concept_mappings=(
            _map(
                "company:goog:concept:cloud-revenue",
                CrossCompanyRelation.ANALYTICALLY_SIMILAR,
                confidence=0.4,
                mapping_version="m8-review-2026-02",
            ),
        )
    )
    rows = ComparisonPanelBuilder().build(
        observations=(
            {
                "raw_concept_id": "goog:CloudRevenue",
                "company_canonical_concept_id": "company:goog:concept:cloud-revenue",
                "filing_id": "goog-10k-2025",
                "period_end": "2025-12-31",
            },
            {
                "raw_concept_id": "other:UnmappedMetric",
                "company_canonical_concept_id": "company:other:concept:metric",
                "filing_id": "other-10k-2025",
                "period_end": "2025-12-31",
            },
        ),
        mappings=tables,
    )

    low_confidence, unresolved = rows
    assert low_confidence["mapping_confidence"] == 0.4
    assert low_confidence["mapping_review_required"] is True
    assert low_confidence["mapping_version"] == "m8-review-2026-02"
    assert unresolved["mapping_relation"] == CrossCompanyRelation.UNRESOLVED
    assert unresolved["analytical_id"] is None
    assert unresolved["mapping_review_required"] is True


def test_invalid_relation_and_false_unresolved_target_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported relation"):
        CrossCompanyMapper().build(concept_mappings=(_map("company:a", "SAME"),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot have analytical_id"):
        CrossCompanyMapper().build(
            concept_mappings=(
                _map(
                    "company:a",
                    CrossCompanyRelation.UNRESOLVED,
                    analytical_id="analytical:should-not-exist",
                ),
            )
        )
