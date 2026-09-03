from __future__ import annotations

import pytest

from sec_xbrl.analytics import (
    CompanyAnalysisPanelResult,
    QuarterlyAnalysisPivotBuilder,
    QuarterlyAnalysisPivotError,
    QuarterlyAnalysisPivotQuery,
)

CIK = "0001045810"


def _panel(
    quarter: int,
    *,
    value: str = "100",
    custom: bool = False,
    mapping_review: bool = False,
    dimensions=(),
    unit=("iso4217:USD",),
    view: str = "LATEST_REPORTED",
    as_of: str = "2024-12-01",
    unavailable: bool = False,
    suffix: str = "",
    dimension_mapping_ids=None,
) -> CompanyAnalysisPanelResult:
    fact = f"fact:{quarter}:{suffix}"
    line = f"line:{quarter}:{suffix}"
    binding = {
        "analysis_binding_id": f"binding:{quarter}:{suffix}",
        "analysis_line_id": line,
        "raw_concept_qname": "nvda:DataCenterRevenue" if custom else "us-gaap:Revenues",
    }
    definition = {
        "analysis_line_id": line,
        "label": "Data Center" if custom else "Revenue",
        "line_class": "COMPANY_CUSTOM" if custom else "COMMON_GAAP",
        "line_scope": "EXPLORATION_DETAIL" if custom else "STATEMENT",
        "line_kind": "REPORTED",
    }
    value_row = {
        "analysis_line_value_id": f"value:{quarter}:{suffix}",
        "analysis_line_id": line,
        "value_status": "UNAVAILABLE" if unavailable else "REPORTED",
        "value_numeric": None if unavailable else value,
        "value_text": None,
        "selection_unavailable_reason": "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION"
        if unavailable
        else None,
        "selection_view": view,
        "selection_as_of_date": as_of,
        "source_filing_id": f"filing:{quarter}:{suffix}",
        "selected_source_fact_id": None if unavailable else fact,
        "raw_concept_qname": binding["raw_concept_qname"],
        "raw_concept_is_standard": not custom,
        "raw_concept_taxonomy_family": "us-gaap" if not custom else "nvda",
        "company_canonical_concept_id": "company:data-center" if custom else "company:revenue",
        "concept_mapping_id": "map:concept",
        "concept_mapping_version": "v1",
        "raw_dimension_signature": dimensions,
        "canonical_dimension_signature": dimensions,
        "dimension_mapping_ids": (
            dimension_mapping_ids
            if dimension_mapping_ids is not None
            else (("map:axis", "map:member"),)
            if dimensions
            else ()
        ),
        "mapping_review_required": mapping_review,
        "unit_numerator_measures": unit,
        "unit_denominator_measures": None if unit is None else (),
        "accession_version_ledger_id": f"ledger:{quarter}",
        "relationship_navigation": ({"analysis_exploration_edge_id": f"edge:{quarter}"},),
    }
    return CompanyAnalysisPanelResult(
        definitions=(definition,),
        bindings=(binding,),
        values=(value_row,),
        scope={
            "cik": CIK,
            "fiscal_year": 2024,
            "fiscal_quarter": quarter,
            "period_class": "QTD_3M",
            "selection_view": view,
            "selection_as_of_date": as_of,
        },
    )


def test_common_gaap_q1_to_q3_make_one_ordered_row_with_full_cell_lineage() -> None:
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(_panel(3, value="300"), _panel(1, value="100"), _panel(2, value="200"))
    )
    matrix = QuarterlyAnalysisPivotQuery(result).matrix()
    assert [column["fiscal_quarter"] for column in result.columns] == [1, 2, 3]
    assert len(result.rows) == 1
    assert [cell["value_numeric"] for cell in matrix[0]["cells"]] == ["100", "200", "300"]
    cell = matrix[0]["cells"][2]
    assert cell["value_lineage"]["accession_version_ledger_id"] == "ledger:3"
    assert cell["binding"]["analysis_binding_id"] == "binding:3:"


def test_confirmed_custom_concept_and_dimension_join_across_quarters() -> None:
    dims = (("company:axis:product", "company:member:data-center", None, "EXPLICIT", False),)
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(_panel(1, custom=True, dimensions=dims), _panel(2, custom=True, dimensions=dims))
    )
    assert len(result.rows) == 1
    assert result.rows[0]["mapping_review_required"] is False


def test_custom_mapping_uncertainty_stays_period_scoped_and_marked_for_review() -> None:
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(
            _panel(1, custom=True, mapping_review=True),
            _panel(2, custom=True, mapping_review=True),
        )
    )
    assert len(result.rows) == 2
    assert {row["review_reason"] for row in result.rows} == {"MAPPING_REVIEW_REQUIRED"}


def test_custom_dimension_with_missing_axis_or_member_map_cannot_join() -> None:
    dims = (("company:axis:product", "company:member:data-center", None, "EXPLICIT", False),)
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(
            _panel(1, custom=True, dimensions=dims, dimension_mapping_ids=(("map:axis", None),)),
            _panel(2, custom=True, dimensions=dims, dimension_mapping_ids=((None, "map:member"),)),
        )
    )
    assert len(result.rows) == 2
    assert {row["review_reason"] for row in result.rows} == {"MAPPING_REVIEW_REQUIRED"}


def test_typed_dimension_remains_review_scoped_without_a_canonical_typed_mapping() -> None:
    dims = (("company:axis:customer", None, "customer-1", "TYPED", False),)
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(
            _panel(1, custom=True, dimensions=dims, dimension_mapping_ids=(("map:axis", None),)),
            _panel(2, custom=True, dimensions=dims, dimension_mapping_ids=(("map:axis", None),)),
        )
    )
    assert len(result.rows) == 2
    assert {row["review_reason"] for row in result.rows} == {"MAPPING_REVIEW_REQUIRED"}


@pytest.mark.parametrize("change", ["view", "as_of", "period_class"])
def test_view_as_of_and_period_class_cannot_mix(change: str) -> None:
    first = _panel(1)
    second = _panel(2)
    scope = dict(second.scope)
    scope[
        {"view": "selection_view", "as_of": "selection_as_of_date", "period_class": "period_class"}[
            change
        ]
    ] = "AS_FILED" if change == "view" else ("2025-01-01" if change == "as_of" else "YTD_6M")
    second = CompanyAnalysisPanelResult(second.definitions, second.bindings, second.values, scope)
    with pytest.raises(QuarterlyAnalysisPivotError, match="cannot mix"):
        QuarterlyAnalysisPivotBuilder().build(panels=(first, second))


def test_unit_boundary_creates_distinct_rows_and_missing_unit_requires_review() -> None:
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(_panel(1, unit=("iso4217:USD",)), _panel(2, unit=("shares",)))
    )
    assert len(result.rows) == 2
    no_unit = _panel(3, unit=None)  # type: ignore[arg-type]
    reviewed = QuarterlyAnalysisPivotBuilder().build(panels=(no_unit,))
    assert reviewed.rows[0]["mapping_review_required"] is True


def test_unavailable_and_missing_period_are_explicit_not_filled() -> None:
    result = QuarterlyAnalysisPivotBuilder().build(
        panels=(_panel(1), _panel(2, unavailable=True), _panel(3, custom=True))
    )
    matrix = QuarterlyAnalysisPivotQuery(result).matrix()
    revenue = next(row for row in matrix if row["row"]["label"] == "Revenue")
    assert revenue["cells"][1]["value_status"] == "UNAVAILABLE"
    assert revenue["cells"][1]["unavailable_reason"] == "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION"
    assert revenue["cells"][2]["unavailable_reason"] == "NO_T5_PANEL_VALUE_FOR_PERIOD"


def test_duplicate_compatible_values_fail_closed() -> None:
    with pytest.raises(QuarterlyAnalysisPivotError, match="collide"):
        QuarterlyAnalysisPivotBuilder().build(panels=(_panel(1), _panel(1, suffix="other")))
