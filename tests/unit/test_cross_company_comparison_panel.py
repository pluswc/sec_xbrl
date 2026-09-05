from __future__ import annotations

import pytest

from sec_xbrl.analytics import QuarterlyAnalysisPivotResult
from sec_xbrl.cross_company import (
    CrossCompanyComparisonPanelBuilder,
    CrossCompanyComparisonPanelError,
    CrossCompanyComparisonPanelQuery,
    CrossCompanyRelation,
)


def _pivot(
    cik: str,
    *,
    qname: str = "us-gaap:Revenues",
    canonical: str | None = None,
    standard: bool = True,
    family: str | None = "us-gaap",
    data_type: str | None = "xbrli:monetaryItemType",
    period_type: str | None = "duration",
    taxonomy_version: str | None = "2024",
    namespace_uri: str | None = "http://fasb.org/us-gaap/2024",
    unit: tuple[str, ...] | None = ("iso4217:USD",),
    dimensions: tuple[object, ...] = (),
    value: str | None = "100",
    view: str = "LATEST_REPORTED",
    as_of: str = "2024-12-01",
    period_class: str = "QTD_3M",
    year: int = 2024,
    quarter: int = 3,
) -> QuarterlyAnalysisPivotResult:
    row_id = f"row:{cik}:{qname}"
    column_id = f"column:{year}:{quarter}:{period_class}"
    canonical = canonical or f"company:{cik}:concept:{qname}"
    value_lineage = {
        "analysis_line_value_id": f"value:{cik}:{qname}",
        "analysis_line_id": f"line:{cik}:{qname}",
        "value_status": "REPORTED" if value is not None else "UNAVAILABLE",
        "value_numeric": value,
        "value_text": None,
        "selection_unavailable_reason": None if value is not None else "NO_ELIGIBLE",
        "source_filing_id": f"filing:{cik}",
        "selected_source_fact_id": f"fact:{cik}:{qname}",
        "raw_concept_id": f"raw:{cik}:{qname}",
        "raw_concept_qname": qname,
        "raw_concept_is_standard": standard,
        "raw_concept_taxonomy_family": family,
        "raw_concept_taxonomy_version": taxonomy_version,
        "raw_concept_namespace_uri": namespace_uri,
        "raw_concept_data_type": data_type,
        "raw_concept_period_type": period_type,
        "company_canonical_concept_id": canonical,
        "raw_dimension_signature": dimensions,
        "unit_numerator_measures": unit,
        "unit_denominator_measures": () if unit is not None else None,
        "selection_view": view,
        "selection_as_of_date": as_of,
        "accession_version_ledger_id": f"ledger:{cik}",
        "relationship_navigation": ({"analysis_exploration_edge_id": f"edge:{cik}"},),
    }
    return QuarterlyAnalysisPivotResult(
        columns=(
            {
                "quarterly_analysis_column_id": column_id,
                "fiscal_year": year,
                "fiscal_quarter": quarter,
                "period_class": period_class,
            },
        ),
        rows=(
            {
                "quarterly_analysis_row_id": row_id,
                "raw_concept_qname": qname,
                "company_canonical_concept_id": canonical,
                "label": "Revenue" if standard else "Cloud revenue",
            },
        ),
        cells=(
            {
                "quarterly_analysis_row_id": row_id,
                "quarterly_analysis_column_id": column_id,
                "value_status": value_lineage["value_status"],
                "value_numeric": value,
                "value_text": None,
                "unavailable_reason": value_lineage["selection_unavailable_reason"],
                "definition": {"analysis_line_id": value_lineage["analysis_line_id"]},
                "binding": {"analysis_binding_id": f"binding:{cik}", "raw_concept_qname": qname},
                "value_lineage": value_lineage,
            },
        ),
        scope={
            "cik": cik,
            "period_class": period_class,
            "selection_view": view,
            "selection_as_of_date": as_of,
        },
    )


def _build(*pivots: QuarterlyAnalysisPivotResult, **kwargs: object):
    return CrossCompanyComparisonPanelBuilder().build(
        pivots=pivots, fiscal_year=2024, fiscal_quarter=3, **kwargs
    )


def test_exact_standard_revenue_builds_one_equivalent_row_and_preserves_lineage() -> None:
    panel = _build(_pivot("0001045810"), _pivot("0000320193", value="200"))

    assert len(panel.rows) == 1
    assert len(panel.cells) == 2
    assert panel.rows[0]["analytical_id"] == "analytical:standard:us-gaap:Revenues"
    assert {cell["mapping_relation"] for cell in panel.cells} == {CrossCompanyRelation.EQUIVALENT}
    assert {cell["mapping_method"] for cell in panel.cells} == {"EXACT_STANDARD_TAXONOMY_IDENTITY"}
    assert panel.cells[0]["t5_value_lineage"]["accession_version_ledger_id"].startswith("ledger:")
    assert panel.cells[0]["t6_cell_lineage"]["binding"]["analysis_binding_id"].startswith("binding:")


def test_standard_taxonomy_version_is_auditable_not_an_equivalence_gate() -> None:
    panel = _build(
        _pivot("0001045810", taxonomy_version="2024", namespace_uri="http://fasb.org/us-gaap/2024"),
        _pivot("0000320193", taxonomy_version="2025", namespace_uri="http://fasb.org/us-gaap/2025"),
    )

    assert {cell["mapping_relation"] for cell in panel.cells} == {CrossCompanyRelation.EQUIVALENT}
    assert {cell["raw_concept_taxonomy_version"] for cell in panel.cells} == {"2024", "2025"}
    evidence = panel.cells[0]["mapping_evidence"]["source_taxonomy_provenance_for_company"]
    assert evidence[0]["taxonomy_version"] in {"2024", "2025"}


@pytest.mark.parametrize(
    ("field", "left", "right"),
    [
        ("family", "us-gaap", "dei"),
        ("data_type", "xbrli:monetaryItemType", "xbrli:sharesItemType"),
        ("period_type", "duration", "instant"),
        ("unit", ("iso4217:USD",), ("shares",)),
    ],
)
def test_incompatible_standard_semantics_remain_separate_unresolved(
    field: str, left: object, right: object
) -> None:
    first = _pivot("0001045810", **{field: left})
    second = _pivot("0000320193", **{field: right})
    panel = _build(first, second)

    assert len(panel.rows) == 2
    assert {row["mapping_relation"] for row in panel.rows} == {CrossCompanyRelation.UNRESOLVED}


def test_same_label_custom_values_are_visible_unresolved_without_label_or_value_inference() -> None:
    first = _pivot("0001045810", qname="nvda:CloudRevenue", standard=False, family="nvda")
    second = _pivot("0000789019", qname="msft:CloudRevenue", standard=False, family="msft")
    panel = _build(first, second)

    assert len(panel.rows) == 2
    assert {cell["mapping_relation"] for cell in panel.cells} == {CrossCompanyRelation.UNRESOLVED}
    assert all(cell["analytical_id"] is None for cell in panel.cells)


def test_reviewed_similarity_is_not_promoted_to_equivalent() -> None:
    first = _pivot("0001045810", qname="nvda:CloudRevenue", standard=False, family="nvda")
    second = _pivot("0000789019", qname="msft:CloudRevenue", standard=False, family="msft")
    mappings = (
        {
            "company_canonical_id": first.cells[0]["value_lineage"]["company_canonical_concept_id"],
            "analytical_id": "analytical:CLOUD",
            "relation": "SUBCATEGORY_OF",
            "confidence": 0.9,
            "evidence": {"disclosure": "product note"},
            "method": "REVIEWED_DISCLOSURE_SCOPE",
            "mapping_version": "t8-review-v1",
            "review_state": "REVIEWED",
        },
        {
            "company_canonical_id": second.cells[0]["value_lineage"]["company_canonical_concept_id"],
            "analytical_id": "analytical:CLOUD",
            "relation": "ANALYTICALLY_SIMILAR",
            "confidence": 0.6,
            "evidence": {"scope": "includes more than cloud"},
            "method": "REVIEWED_DISCLOSURE_SCOPE",
            "mapping_version": "t8-review-v1",
            "review_state": "REVIEWED",
        },
    )
    panel = _build(first, second, reviewed_concept_mappings=mappings)

    assert len(panel.rows) == 1
    assert {cell["mapping_relation"] for cell in panel.cells} == {
        CrossCompanyRelation.SUBCATEGORY_OF,
        CrossCompanyRelation.ANALYTICALLY_SIMILAR,
    }
    assert CrossCompanyRelation.EQUIVALENT not in {cell["mapping_relation"] for cell in panel.cells}


def test_review_mapping_requires_nonempty_evidence_version_and_review_state() -> None:
    first, second = _pivot("0001045810", standard=False), _pivot("0000320193", standard=False)
    bad = {
        "company_canonical_id": first.cells[0]["value_lineage"]["company_canonical_concept_id"],
        "analytical_id": "analytical:X",
        "relation": "ANALYTICALLY_SIMILAR",
        "confidence": 0.5,
        "evidence": {},
        "method": "REVIEW",
        "mapping_version": "v1",
        "review_state": "REVIEWED",
    }
    with pytest.raises(CrossCompanyComparisonPanelError, match="evidence"):
        _build(first, second, reviewed_concept_mappings=(bad,))


def test_explicit_mapping_collision_with_auto_standard_identity_fails_closed() -> None:
    first, second = _pivot("0001045810"), _pivot("0000320193")
    explicit = {
        "company_canonical_id": first.cells[0]["value_lineage"]["company_canonical_concept_id"],
        "analytical_id": "analytical:OTHER",
        "relation": "ANALYTICALLY_SIMILAR",
        "confidence": 0.5,
        "evidence": {"scope": "test"},
        "method": "REVIEW",
        "mapping_version": "v1",
        "review_state": "REVIEWED",
    }
    with pytest.raises(ValueError, match="cannot duplicate"):
        _build(first, second, reviewed_concept_mappings=(explicit,))


def test_scope_mismatch_and_absent_selected_column_fail_closed() -> None:
    with pytest.raises(CrossCompanyComparisonPanelError, match="cannot mix"):
        _build(_pivot("0001045810"), _pivot("0000320193", as_of="2025-01-01"))
    with pytest.raises(CrossCompanyComparisonPanelError, match="absent"):
        _build(_pivot("0001045810"), _pivot("0000320193", quarter=2))


def test_unavailable_cell_is_preserved_and_query_has_company_gaps() -> None:
    panel = _build(_pivot("0001045810"), _pivot("0000320193", value=None))
    unavailable = next(cell for cell in panel.cells if cell["cik"] == "0000320193")
    assert unavailable["value_status"] == "UNAVAILABLE"
    matrix = CrossCompanyComparisonPanelQuery(panel).matrix()
    assert any(cell["value_status"] == "UNAVAILABLE" for cell in matrix[0]["cells"])
