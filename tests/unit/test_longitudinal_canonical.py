from __future__ import annotations

from copy import deepcopy

from sec_xbrl.longitudinal import CompanyCanonicalizer, MappingRelation, SeriesBuilder


def _filings() -> tuple[dict[str, object], ...]:
    return (
        {
            "filing_id": "k24",
            "cik": "0000123456",
            "form": "10-K",
            "filed_date": "2025-02-01",
            "accession": "1",
        },
        {
            "filing_id": "q25",
            "cik": "0000123456",
            "form": "10-Q",
            "filed_date": "2025-05-01",
            "accession": "2",
        },
        {
            "filing_id": "k25",
            "cik": "0000123456",
            "form": "10-K",
            "filed_date": "2026-02-01",
            "accession": "3",
        },
    )


def _concept(raw_id: str, filing_id: str, **extra: object) -> dict[str, object]:
    return {
        "raw_concept_id": raw_id,
        "filing_id": filing_id,
        "qname": "ex:" + raw_id,
        "namespace_uri": "https://example.test/2024",
        "local_name": "Revenue",
        "label": "Revenue",
        "is_standard": False,
        **extra,
    }


def test_mappings_are_additive_and_string_similarity_never_confirms_identity() -> None:
    concepts = (
        _concept("old", "k24"),
        _concept("new", "k25", namespace_uri="https://example.test/2025"),
    )
    original = deepcopy(concepts)

    tables = CompanyCanonicalizer().build(filings=_filings(), concepts=concepts)

    assert concepts == original
    old, new = tables.company_concept_map
    assert old["source_raw_id"] == "old"
    assert new["source_raw_id"] == "new"
    assert new["relation"] == MappingRelation.UNCERTAIN
    assert new["method"] == "STRING_SIMILARITY_ONLY"
    assert new["review_required"] is True
    assert old["company_canonical_id"] != new["company_canonical_id"]
    for row in tables.company_concept_map:
        assert {
            "valid_from_filing_id",
            "valid_to_filing_id",
            "evidence",
            "mapping_version",
        } <= row.keys()


def test_namespace_change_preserves_well_supported_same_company_series() -> None:
    concepts = (
        _concept("old", "k24", axis_domain_role=("axis:product", "role:segment")),
        _concept(
            "new",
            "k25",
            namespace_uri="https://example.test/2025",
            axis_domain_role=("axis:product", "role:segment"),
        ),
    )

    tables = CompanyCanonicalizer().build(filings=_filings(), concepts=concepts)

    old, new = tables.company_concept_map
    assert new["relation"] == MappingRelation.RENAMED
    assert new["method"] == "LOCAL_AXIS_ROLE_LABEL_CONTINUITY"
    assert new["company_canonical_id"] == old["company_canonical_id"]
    assert new["confidence"] == 0.9
    assert new["review_required"] is False


def test_segment_recast_appends_new_mapping_version_and_continuity_break() -> None:
    canonicalizer = CompanyCanonicalizer()
    prior = {
        "company_canonical_id": "company:0000123456:member:old",
        "source_raw_id": "old-segment",
        "mapping_version": "m7-company-canonical-v1",
    }
    recast = canonicalizer.segment_recast(
        cik="0000123456",
        prior_member_map=prior,
        recast_member={"raw_concept_id": "new-segment"},
        filing_id="k25",
        evidence={"source_document": "10-K", "locator": "Note 7"},
    )

    assert prior["company_canonical_id"] == "company:0000123456:member:old"
    assert recast["relation"] == MappingRelation.RECAST
    assert recast["continuity_break"] is True
    assert recast["company_canonical_id"] != prior["company_canonical_id"]
    assert recast["mapping_version"] != prior["mapping_version"]
    assert recast["evidence"]["prior_company_canonical_id"] == prior["company_canonical_id"]


def test_documented_recast_is_persisted_without_rewriting_prior_mapping() -> None:
    concepts = (
        _concept(
            "old-segment", "k24", entity_type="member", local_name="Consumer", label="Consumer"
        ),
        _concept(
            "new-segment", "k25", entity_type="member", local_name="Products", label="Products"
        ),
    )
    tables = CompanyCanonicalizer().build(
        filings=_filings(),
        concepts=concepts,
        documented_changes=(
            {"source_raw_id": "new-segment", "prior_raw_id": "old-segment", "document": "Note 7"},
        ),
    )

    old, new = tables.company_member_map
    assert old["valid_to_filing_id"] is None
    assert new["relation"] == MappingRelation.RECAST
    assert new["continuity_break"] is True
    assert new["company_canonical_id"] != old["company_canonical_id"]
    assert new["mapping_version"] != old["mapping_version"]
    assert tables.structural_change[-1]["event_type"] == "SEGMENT_RECAST"


def test_dimension_facts_classify_raw_concepts_into_additive_axis_and_member_maps() -> None:
    tables = CompanyCanonicalizer().build(
        filings=_filings(),
        concepts=(
            _concept("revenue", "k24"),
            _concept("segment-axis", "k24"),
            _concept("consumer-member", "k24"),
        ),
        dimension_facts=(
            {
                "fact_id": "fact",
                "axis_raw_concept_id": "segment-axis",
                "member_raw_concept_id": "consumer-member",
            },
        ),
    )

    assert [row["source_raw_id"] for row in tables.company_concept_map] == ["revenue"]
    assert [row["source_raw_id"] for row in tables.company_axis_map] == ["segment-axis"]
    assert [row["source_raw_id"] for row in tables.company_member_map] == ["consumer-member"]


def test_annual_and_current_series_keep_period_classes_distinct_and_surface_review() -> None:
    mappings = CompanyCanonicalizer().build(
        filings=_filings(),
        concepts=(
            _concept(
                "revenue-k",
                "k24",
                is_standard=True,
                qname="us-gaap:Revenue",
                namespace_uri="us-gaap/2024",
            ),
            _concept(
                "revenue-q",
                "q25",
                is_standard=True,
                qname="us-gaap:Revenue",
                namespace_uri="us-gaap/2024",
            ),
            _concept("same-name-only", "k25", local_name="Revenue", label="Revenue"),
        ),
    )
    facts = (
        {
            "fact_id": "fy",
            "filing_id": "k24",
            "raw_concept_id": "revenue-k",
            "period_class": "FY",
            "unit_id": "usd",
        },
        {
            "fact_id": "qtd",
            "filing_id": "q25",
            "raw_concept_id": "revenue-q",
            "period_class": "QTD_3M",
            "unit_id": "usd",
        },
        {
            "fact_id": "ytd",
            "filing_id": "q25",
            "raw_concept_id": "revenue-q",
            "period_class": "YTD_6M",
            "unit_id": "usd",
        },
        {
            "fact_id": "uncertain",
            "filing_id": "k25",
            "raw_concept_id": "same-name-only",
            "period_class": "FY",
            "unit_id": "usd",
        },
    )
    builder = SeriesBuilder()
    annual = builder.annual(filings=_filings(), facts=facts, mappings=mappings)
    current = builder.current(filings=_filings(), facts=facts, mappings=mappings)

    assert {row["fact_id"] for row in annual} == {"fy", "uncertain"}
    assert {row["period_class"] for row in current} == {"FY", "QTD_3M", "YTD_6M"}
    qtd = next(row for row in current if row["fact_id"] == "qtd")
    ytd = next(row for row in current if row["fact_id"] == "ytd")
    assert qtd["company_canonical_concept_id"] == ytd["company_canonical_concept_id"]
    assert qtd["series_key"] != ytd["series_key"]
    assert (
        next(row for row in annual if row["fact_id"] == "uncertain")["mapping_review_required"]
        is True
    )
