from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sec_xbrl.longitudinal import (
    AsOfSeriesSelector,
    CompanyCanonicalizer,
    Layer1SnapshotInput,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
    MappingRelation,
    SeriesBuilder,
)


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


def test_aapl_product_service_and_nvda_segment_geography_are_raw_traceable() -> None:
    """Representative names are fixtures, never ticker-specific mapping logic."""
    cases = (
        (
            "0000320193",
            "aapl-10k",
            "product-service-axis",
            "iphone-member",
            "ProductOrServiceAxis",
            "IPhoneMember",
        ),
        (
            "0001045810",
            "nvda-10q",
            "segment-axis",
            "united-states-member",
            "OperatingSegmentsAxis",
            "UnitedStatesMember",
        ),
    )
    for cik, filing_id, axis_id, member_id, axis_name, member_name in cases:
        tables = CompanyCanonicalizer().build(
            filings=({"filing_id": filing_id, "cik": cik, "filed_date": "2026-01-01"},),
            concepts=(
                _concept(axis_id, filing_id, local_name=axis_name, label=axis_name),
                _concept(member_id, filing_id, local_name=member_name, label=member_name),
            ),
            dimension_facts=(
                {
                    "fact_id": "revenue-fact",
                    "axis_raw_concept_id": axis_id,
                    "member_raw_concept_id": member_id,
                },
            ),
        )
        axis, member = tables.company_axis_map[0], tables.company_member_map[0]
        assert axis["source_raw_id"] == axis_id
        assert axis["source_filing_id"] == filing_id
        assert axis["company_canonical_id"]
        assert axis["evidence"]["raw_identity"] == axis_id
        assert member["source_raw_id"] == member_id
        assert member["source_filing_id"] == filing_id
        assert member["company_canonical_id"]
        event = next(item for item in tables.structural_change if item["source_raw_id"] == member_id)
        assert event["evidence"]["raw_identity"] == member_id


def test_uncertain_mapping_is_not_coalesced_and_has_explainable_change_event() -> None:
    tables = CompanyCanonicalizer().build(
        filings=_filings(),
        concepts=(
            _concept("old", "k24"),
            _concept("new", "k25", namespace_uri="https://example.test/2025"),
        ),
    )
    uncertain = tables.company_concept_map[-1]
    assert uncertain["relation"] == "UNCERTAIN"
    assert uncertain["review_state"] == "REVIEW_REQUIRED"
    assert uncertain["company_canonical_id"] != tables.company_concept_map[0]["company_canonical_id"]
    change = tables.structural_change[-1]
    assert change["event_type"] == "UNKNOWN_CHANGE"
    assert change["company_canonical_id"] == uncertain["company_canonical_id"]
    assert change["evidence"] == uncertain["evidence"]


def test_same_standard_concept_with_changed_role_network_records_role_restructure() -> None:
    tables = CompanyCanonicalizer().build(
        filings=_filings(),
        concepts=(
            _concept("revenue-old", "k24", is_standard=True, qname="us-gaap:Revenue"),
            _concept("revenue-new", "k25", is_standard=True, qname="us-gaap:Revenue"),
        ),
        relationships=(
            {"from_raw_concept_id": "revenue-old", "role_uri": "role:old", "network_type": "PRE"},
            {"from_raw_concept_id": "revenue-new", "role_uri": "role:new", "network_type": "PRE"},
        ),
    )
    same = tables.company_concept_map[-1]
    assert same["relation"] == "SAME"
    event = next(item for item in tables.structural_change if item["event_type"] == "ROLE_RESTRUCTURE")
    assert event["source_raw_id"] == "revenue-new"
    assert event["company_canonical_id"] == same["company_canonical_id"]


def test_mapping_tables_are_publisher_ready_with_l2_m0_contract(tmp_path: Path) -> None:
    tables = CompanyCanonicalizer().build(filings=_filings(), concepts=(_concept("revenue", "k24"),))
    run = Layer2Run(
        run_version="l2-m2-contract-fixture-v1",
        corpus_run_id="fixture",
        inputs=(
            Layer1SnapshotInput(
                cik="0000123456",
                accession="fixture-1",
                form="10-K",
                filed_date="2025-02-01",
                report_date="2024-12-31",
                snapshot_id="fixture/1",
                manifest_sha256="a" * 64,
            ),
        ),
        rules=Layer2RuleVersions("period-v1", "l2-m2-company-canonical-v1", "recast-v1", "selection-v1"),
    )
    datasets = {
        **tables.as_datasets(),
        "analytical_fact": [
            {
                "analytical_fact_id": "fixture-unavailable",
                "cik": "0000123456",
                "view": "AS_FILED",
                "as_of_date": "2025-02-01",
                "source_type": "UNAVAILABLE",
                "unavailable_reason": "NOT_SELECTED_IN_L2_M2",
            }
        ],
    }
    publication = Layer2Publisher(tmp_path / "layer2").publish(run, datasets)
    assert publication.output_counts["company_concept_map"] == 1
    assert publication.output_counts["structural_change"] == 1


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
    assert qtd["source_raw_fact_id"] == "qtd"
    assert qtd["source_filing_id"] == "q25"
    assert qtd["filed_date"] == "2025-05-01"
    assert qtd["source_type"] == "REPORTED"
    assert qtd["basis_version"] is None
    assert qtd["mapping_evidence"]
    assert (
        next(row for row in annual if row["fact_id"] == "uncertain")["mapping_review_required"]
        is True
    )


def _nvidia_style_observations(*, include_recast_q2: bool = True) -> tuple[dict[str, object], ...]:
    common = {
        "cik": "0001045810",
        "company_canonical_concept_id": "company:0001045810:concept:geographic-revenue",
        "company_canonical_dimension_key": (("axis:geography", "member:us", None),),
        "series_key": ("0001045810", "company:0001045810:concept:geographic-revenue", "us", "usd", "QTD_3M"),
        "series_type": "CURRENT",
        "unit_id": "usd",
        "period_class": "QTD_3M",
        "fiscal_year": 2026,
        "mapping_version": "m7-company-canonical-v1",
        "mapping_evidence": {"method": "reviewed"},
    }
    rows = [
        {**common, "fact_id": "q1-original", "source_raw_fact_id": "q1-original", "filing_id": "q1-10q", "filed_date": "2025-05-28", "period_key": "FY26-Q1", "value_numeric": "20739", "basis_version": "geography-billing-address-v1", "source_type": "REPORTED"},
        {**common, "fact_id": "q2-original", "source_raw_fact_id": "q2-original", "filing_id": "q2-10q", "filed_date": "2025-08-27", "period_key": "FY26-Q2", "value_numeric": "23470", "basis_version": "geography-billing-address-v1", "source_type": "REPORTED"},
        {**common, "fact_id": "q1-recast", "source_raw_fact_id": "q1-recast", "filing_id": "q3-10q", "filed_date": "2025-11-19", "period_key": "FY26-Q1", "value_numeric": "25685", "basis_version": "geography-customer-hq-v2", "source_type": "RECAST_REPORTED", "recast_evidence_id": "note-geography-basis-change"},
    ]
    if include_recast_q2:
        rows.append(
            {**common, "fact_id": "q2-recast", "source_raw_fact_id": "q2-recast", "filing_id": "q3-10q", "filed_date": "2025-11-19", "period_key": "FY26-Q2", "value_numeric": "32897", "basis_version": "geography-customer-hq-v2", "source_type": "RECAST_REPORTED", "recast_evidence_id": "note-geography-basis-change"}
        )
    return tuple(rows)


def test_as_of_selector_preserves_originals_then_selects_one_documented_recast_basis() -> None:
    selector = AsOfSeriesSelector()
    before = selector.select(
        _nvidia_style_observations(), as_of_date="2025-10-01", view="LATEST_RECAST"
    )
    assert {row["period_key"]: row["value_numeric"] for row in before} == {
        "FY26-Q1": "20739",
        "FY26-Q2": "23470",
    }
    assert {row["basis_version"] for row in before} == {"geography-billing-address-v1"}

    after = selector.select(
        _nvidia_style_observations(), as_of_date="2025-11-20", view="LATEST_RECAST"
    )
    assert {row["period_key"]: row["value_numeric"] for row in after} == {
        "FY26-Q1": "25685",
        "FY26-Q2": "32897",
    }
    assert {row["basis_version"] for row in after} == {"geography-customer-hq-v2"}
    assert {row["source_type"] for row in after} == {"RECAST_REPORTED"}
    assert all(row["selected_raw_fact_id"] for row in after)

    as_filed = selector.select(
        _nvidia_style_observations(), as_of_date="2025-11-20", view="AS_FILED"
    )
    assert {row["period_key"]: row["value_numeric"] for row in as_filed} == {
        "FY26-Q1": "20739",
        "FY26-Q2": "23470",
    }
    assert {row["view"] for row in as_filed} == {"AS_FILED"}


def test_latest_recast_never_mixes_an_incomplete_new_basis() -> None:
    selected = AsOfSeriesSelector().select(
        _nvidia_style_observations(include_recast_q2=False),
        as_of_date="2025-11-20",
        view="LATEST_RECAST",
    )
    by_period = {row["period_key"]: row for row in selected}
    assert by_period["FY26-Q1"]["value_numeric"] == "25685"
    assert by_period["FY26-Q1"]["basis_version"] == "geography-customer-hq-v2"
    assert by_period["FY26-Q2"]["status"] == "N/A"
    assert by_period["FY26-Q2"]["source_type"] == "UNAVAILABLE"
    assert by_period["FY26-Q2"]["unavailable_reason"] == "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS"


def test_latest_recast_requires_explicit_basis_and_recast_evidence() -> None:
    observations = list(_nvidia_style_observations())
    observations[2].pop("recast_evidence_id")
    observations[3]["basis_version"] = None
    selected = AsOfSeriesSelector().select(
        observations, as_of_date="2025-11-20", view="LATEST_RECAST"
    )
    assert {row["basis_version"] for row in selected} == {"geography-billing-address-v1"}
    assert {row["value_numeric"] for row in selected} == {"20739", "23470"}
