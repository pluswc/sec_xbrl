from __future__ import annotations

from sec_xbrl.longitudinal import (
    CORE_CONCEPTS_BY_KEY,
    CoreQuarterlyCoverageValidator,
    CoverageStatus,
)

CIK = "0001045810"
REVENUE_ID = "company:0001045810:concept:revenue"


def _mapping() -> dict[str, object]:
    return {
        "entity_type": "concept",
        "company_canonical_id": REVENUE_ID,
        "source_is_standard": True,
        "source_taxonomy_family": "us-gaap",
        "source_namespace_uri": "http://fasb.org/us-gaap/2025",
        "source_local_name": "Revenues",
        "evidence": {"context_semantics": {"period_type": "duration"}},
    }


def _reported(quarter: int, *, unavailable: bool = False) -> dict[str, object]:
    return {
        "analytical_fact_id": f"reported-q{quarter}",
        "view": "AS_FILED",
        "company_canonical_concept_id": REVENUE_ID,
        "company_canonical_dimension_key": (),
        "period_class": "QTD_3M",
        "fiscal_year": 2025,
        "fiscal_quarter": quarter,
        "source_type": "UNAVAILABLE" if unavailable else "REPORTED",
        "unavailable_reason": "AMBIGUOUS_AS_FILED_SELECTION_IDENTITY" if unavailable else None,
    }


def test_core_quarterly_coverage_accepts_reported_and_mechanical_derived_q4() -> None:
    result = CoreQuarterlyCoverageValidator().validate(
        cik=CIK,
        analytical_facts=tuple(_reported(quarter) for quarter in (1, 2, 3)),
        derived_facts=(
            {
                "mechanical_q4_id": "derived-q4",
                "company_canonical_concept_id": REVENUE_ID,
                "company_canonical_dimension_key": (),
                "period_class": "QTD_3M",
                "fiscal_year": 2025,
                "fiscal_quarter": 4,
                "reported_or_derived": "DERIVED",
            },
        ),
        company_concept_map=(_mapping(),),
        fiscal_years=(2025,),
    )
    assert [cell.status for cell in result.cells] == [
        CoverageStatus.REPORTED, CoverageStatus.REPORTED, CoverageStatus.REPORTED, CoverageStatus.DERIVED,
    ]
    assert result.complete is True


def test_core_quarterly_coverage_surfaces_unavailable_and_missing_cells() -> None:
    result = CoreQuarterlyCoverageValidator().validate(
        cik=CIK,
        analytical_facts=(_reported(1), _reported(2, unavailable=True)),
        company_concept_map=(_mapping(),),
        fiscal_years=(2025,),
        core_concepts=(CORE_CONCEPTS_BY_KEY["revenue"],),
    )
    assert [cell.status for cell in result.cells] == [
        CoverageStatus.REPORTED, CoverageStatus.UNAVAILABLE, CoverageStatus.MISSING, CoverageStatus.MISSING,
    ]
    assert result.unavailable[0].reason == "AMBIGUOUS_AS_FILED_SELECTION_IDENTITY"
    assert {(cell.fiscal_quarter, cell.status) for cell in result.missing} == {
        (3, CoverageStatus.MISSING), (4, CoverageStatus.MISSING),
    }
