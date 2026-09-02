from __future__ import annotations

from sec_xbrl.longitudinal import (
    CORE_CONCEPTS_BY_KEY,
    CoreQuarterlyCoverageValidator,
    CoverageBasis,
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


def _flow_mappings() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            **_mapping(),
            "company_canonical_id": f"company:0001045810:concept:{key}",
            "source_local_name": local_name,
        }
        for key, local_name in (
            ("revenue", "Revenues"),
            ("gross_profit", "GrossProfit"),
            ("operating_income_loss", "OperatingIncomeLoss"),
            ("net_income_loss", "NetIncomeLoss"),
        )
    )


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


def _flow_fact(
    concept_key: str, quarter: int, period_class: str,
) -> dict[str, object]:
    return {
        "analytical_fact_id": f"{concept_key}-{period_class}-q{quarter}",
        "view": "AS_FILED",
        "company_canonical_concept_id": f"company:0001045810:concept:{concept_key}",
        "company_canonical_dimension_key": (),
        "period_class": period_class,
        "fiscal_year": 2025,
        "fiscal_quarter": quarter,
        "source_type": "REPORTED",
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


def test_core_flow_completion_requires_all_four_concepts_on_quarterly_and_cumulative_bases() -> None:
    concept_keys = ("revenue", "gross_profit", "operating_income_loss", "net_income_loss")
    facts = tuple(
        _flow_fact(concept_key, quarter, "QTD_3M")
        for concept_key in concept_keys
        for quarter in range(1, 5)
    ) + tuple(
        _flow_fact(concept_key, quarter, period_class)
        for concept_key in ("revenue", "gross_profit", "operating_income_loss", "net_income_loss")
        for quarter, period_class in ((2, "YTD_6M"), (3, "YTD_9M"), (4, "FY"))
    )
    result = CoreQuarterlyCoverageValidator().validate_core_flow_completion(
        cik=CIK,
        analytical_facts=facts,
        company_concept_map=_flow_mappings(),
        fiscal_years=(2025,),
    )

    assert len(result.cells) == 32
    assert result.complete is True
    assert {
        (cell.coverage_basis, cell.fiscal_quarter, cell.required_period_class)
        for cell in result.cells
        if cell.concept_key == "revenue"
    } == {
        (CoverageBasis.QUARTERLY, 1, "QTD_3M"),
        (CoverageBasis.QUARTERLY, 2, "QTD_3M"),
        (CoverageBasis.QUARTERLY, 3, "QTD_3M"),
        (CoverageBasis.QUARTERLY, 4, "QTD_3M"),
        (CoverageBasis.CUMULATIVE, 1, "QTD_3M"),
        (CoverageBasis.CUMULATIVE, 2, "YTD_6M"),
        (CoverageBasis.CUMULATIVE, 3, "YTD_9M"),
        (CoverageBasis.CUMULATIVE, 4, "FY"),
    }


def test_core_flow_completion_does_not_use_derived_q4_for_cumulative_fy() -> None:
    facts = tuple(
        _flow_fact("revenue", quarter, period_class)
        for quarter, period_class in ((1, "QTD_3M"), (2, "YTD_6M"), (3, "YTD_9M"))
    )
    result = CoreQuarterlyCoverageValidator().validate(
        cik=CIK,
        analytical_facts=facts,
        company_concept_map=(_flow_mappings()[0],),
        fiscal_years=(2025,),
        core_concepts=(CORE_CONCEPTS_BY_KEY["revenue"],),
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
        coverage_bases=(CoverageBasis.QUARTERLY, CoverageBasis.CUMULATIVE),
    )
    by_basis_and_quarter = {
        (cell.coverage_basis, cell.fiscal_quarter): cell.status for cell in result.cells
    }
    assert by_basis_and_quarter[(CoverageBasis.QUARTERLY, 4)] == CoverageStatus.DERIVED
    assert by_basis_and_quarter[(CoverageBasis.CUMULATIVE, 4)] == CoverageStatus.MISSING
