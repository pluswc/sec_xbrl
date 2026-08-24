from dataclasses import replace

from sec_xbrl.pilots.amd_msft_meta_p2 import CompanyDossier, DossierEvidence
from sec_xbrl.pilots.amd_msft_meta_p3 import (
    P3_MAPPING_VERSION,
    UNMAPPED_COMPANY_CANONICAL_ID,
    build_peer_review,
    render_peer_review,
)


def _evidence(*, dimensions: tuple[str, ...] = ()) -> DossierEvidence:
    return DossierEvidence(
        label="Revenue", value="10 × 10^6", period_class="QTD_3M",
        period="2026-01-01 to 2026-03-31", dimensions=dimensions,
        accession="0000000000-26-000001", document="example.htm", locator="inline-id:f-1",
        qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", unit="iso4217:USD",
    )


def _dossier(*, breakdown: DossierEvidence | None = None) -> CompanyDossier:
    return CompanyDossier(
        company="Example Corp.", ticker="EX", annual_accession="0000000000-25-000001",
        update_accession="0000000000-26-000001", annual_revenue=(), update_revenue=(_evidence(),),
        annual_breakdowns=(), update_breakdowns=(() if breakdown is None else (breakdown,)),
        disclosure_states=(), statement_qa=(), relationship_qa=(), warnings=(),
    )


def test_total_revenue_is_visible_but_unmapped_until_layer2_exists() -> None:
    row = build_peer_review((_dossier(),)).comparisons[0]

    assert row.metric == "REPORTED_TOTAL_REVENUE"
    assert row.source_raw_id.endswith("0000000000-26-000001:example.htm:inline-id:f-1")
    assert row.company_canonical_id == UNMAPPED_COMPANY_CANONICAL_ID
    assert row.analytical_id is None
    assert row.mapping_relation == "UNRESOLVED"
    assert row.mapping_confidence == 0.0
    assert row.mapping_version == P3_MAPPING_VERSION


def test_segment_product_breakdown_is_not_promoted_to_peer_equivalence() -> None:
    row = build_peer_review((_dossier(breakdown=_evidence(dimensions=(
        "us-gaap:StatementBusinessSegmentsAxis=msft:IntelligentCloudMember",)),),)).comparisons[1]

    assert row.metric == "MSFT_INTELLIGENT_CLOUD_REVENUE"
    assert row.mapping_relation == "NOT_COMPARABLE"
    assert row.analytical_id is None
    assert "broader than cloud services" in row.scope_warning


def test_only_latest_baseline_update_and_highlighted_breakdowns_are_selected() -> None:
    old = replace(_evidence(), period="2025-01-01 to 2025-03-31")
    dossier = replace(
        _dossier(),
        annual_revenue=(_evidence(),),
        update_revenue=(old, _evidence()),
        update_breakdowns=(
            _evidence(dimensions=("srt:StatementGeographicalAxis=country:US",)),
            _evidence(dimensions=("us-gaap:StatementBusinessSegmentsAxis=amd:DatacenterMember",)),
        ),
    )

    rows = build_peer_review((dossier,)).comparisons
    assert [row.metric for row in rows] == [
        "REPORTED_TOTAL_REVENUE", "REPORTED_TOTAL_REVENUE", "AMD_DATA_CENTER_REVENUE"
    ]


def test_meta_segment_wins_over_non_highlighted_product_breakdown() -> None:
    dossier = replace(
        _dossier(),
        update_breakdowns=(
            _evidence(dimensions=(
                "srt:ProductOrServiceAxis=us-gaap:ServiceOtherMember",
                "us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember",
            )),
            _evidence(dimensions=("us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember",)),
        ),
    )

    assert build_peer_review((dossier,)).comparisons[-1].metric == "META_FAMILY_OF_APPS_REVENUE"


def test_rendered_review_has_every_required_provenance_field_and_backlog() -> None:
    report = render_peer_review(build_peer_review((_dossier(),)))

    for required in (
        "Raw ID:", "Company canonical ID:", "Analytical ID:", "relation:",
        "confidence:", "version:", "accession", "Source:", "Scope warning:",
        "P3-BLK-001", "Evidence gap:", "Impact:", "Owner lane:", "Decision needed:",
        "UNMAPPED", "UNRESOLVED",
    ):
        assert required in report
