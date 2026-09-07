from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from sec_xbrl.analytics import (
    CompanyAnalysisPanelResult,
    QuarterlyAnalysisPivotBuilder,
    QuarterlyDerivedMetricsBuilder,
)

CIK = "0001045810"


def _panel(year: int, quarter: int, lines: tuple[tuple[str, str, str], ...]) -> CompanyAnalysisPanelResult:
    definitions, bindings, values = [], [], []
    for index, (qname, label, value) in enumerate(lines):
        line_id = f"line:{year}:{quarter}:{index}"
        definition = {
            "analysis_line_id": line_id,
            "label": label,
            "line_class": "COMMON_GAAP",
            "line_scope": "STATEMENT",
            "line_kind": "REPORTED",
            "parent_analysis_line_id": None,
        }
        binding = {
            "analysis_binding_id": f"binding:{line_id}",
            "analysis_line_id": line_id,
            "raw_concept_qname": qname,
            "raw_concept_is_standard": True,
            "raw_concept_taxonomy_family": "us-gaap",
            "relationship_navigation": (),
        }
        lineage = {
            "selection_view": "LATEST_REPORTED",
            "selection_as_of_date": "2025-12-31",
            "basis_version": "basis-v1",
            "canonical_dimension_signature": (),
            "concept_mapping_version": "map-v1",
            "dimension_mapping_ids": (),
            "mapping_review_required": False,
            "context_id": f"context:{year}:{quarter}:{index}",
            "context_start_date": f"{year}-01-01",
            "context_end_date": f"{year}-03-31",
            "unit_numerator_measures": ("iso4217:USD",),
            "unit_denominator_measures": (),
            "source_filing_id": f"filing:{year}:{quarter}",
            "selected_source_fact_id": f"fact:{year}:{quarter}:{index}",
        }
        values.append(
            {
                "analysis_line_value_id": f"value:{line_id}",
                "analysis_line_id": line_id,
                "value_status": "REPORTED",
                "value_numeric": value,
                "value_text": None,
                "selection_view": "LATEST_REPORTED",
                "selection_as_of_date": "2025-12-31",
                "raw_concept_qname": qname,
                "raw_concept_is_standard": True,
                "raw_concept_taxonomy_family": "us-gaap",
                **lineage,
            }
        )
        definitions.append(definition)
        bindings.append(binding)
    return CompanyAnalysisPanelResult(
        definitions=tuple(definitions), bindings=tuple(bindings), values=tuple(values),
        scope={"cik": CIK, "fiscal_year": year, "fiscal_quarter": quarter,
               "period_class": "QTD_3M", "selection_view": "LATEST_REPORTED",
               "selection_as_of_date": "2025-12-31"},
    )


def _pivot(*panels: CompanyAnalysisPanelResult):
    return QuarterlyAnalysisPivotBuilder().build(panels=panels)


def _records(result, metric: str):
    return [row for row in result.records if row["metric_id"] == metric]


def test_qoq_q1_q3_and_next_year_yoy_use_declared_fiscal_predecessors() -> None:
    revenue = "us-gaap:Revenues"
    pivot = _pivot(
        _panel(2024, 1, ((revenue, "Revenue", "100"),)),
        _panel(2024, 2, ((revenue, "Revenue", "120"),)),
        _panel(2024, 3, ((revenue, "Revenue", "180"),)),
        _panel(2025, 3, ((revenue, "Revenue", "270"),)),
    )
    result = QuarterlyDerivedMetricsBuilder().build(pivot=pivot)
    qoq = _records(result, "QOQ_GROWTH")
    q3 = next(row for row in qoq if row["fiscal_year"] == 2024 and row["fiscal_quarter"] == 3)
    assert q3["value_percentage_points"] == Decimal("50.0")
    yoy = next(row for row in _records(result, "YOY_GROWTH") if row["fiscal_year"] == 2025)
    assert yoy["value_percentage_points"] == Decimal("50.0")
    q1 = next(row for row in qoq if row["fiscal_year"] == 2024 and row["fiscal_quarter"] == 1)
    assert q1["evaluation_status"] == "PREDECESSOR_PERIOD_NOT_DECLARED"


def test_zero_review_and_incompatible_inputs_fail_closed_with_lineage() -> None:
    revenue, gross = "us-gaap:Revenues", "us-gaap:GrossProfit"
    pivot = _pivot(_panel(2024, 1, ((revenue, "Revenue", "0"), (gross, "Gross", "5"))))
    zero = next(row for row in _records(QuarterlyDerivedMetricsBuilder().build(pivot=pivot), "GROSS_MARGIN"))
    assert zero["evaluation_status"] == "ZERO_DENOMINATOR"
    assert len(zero["input_lineage"]) == 2
    altered = deepcopy(pivot)
    altered.cells[0]["value_lineage"]["mapping_review_required"] = True
    blocked = next(row for row in _records(QuarterlyDerivedMetricsBuilder().build(pivot=altered), "GROSS_MARGIN"))
    assert blocked["evaluation_status"] == "MAPPING_REVIEW_REQUIRED"


def test_basis_and_unit_incompatibility_and_missing_roles_are_unavailable() -> None:
    revenue, gross = "us-gaap:Revenues", "us-gaap:GrossProfit"
    pivot = _pivot(_panel(2024, 1, ((revenue, "Revenue", "100"), (gross, "Gross", "50"))))
    mismatch = deepcopy(pivot)
    gross_cell = next(cell for cell in mismatch.cells if cell["binding"]["raw_concept_qname"] == gross)
    gross_cell["value_lineage"]["basis_version"] = "different-basis"
    record = next(row for row in _records(QuarterlyDerivedMetricsBuilder().build(pivot=mismatch), "GROSS_MARGIN"))
    assert record["evaluation_status"] == "INCOMPATIBLE_SELECTION_SCOPE"
    only_revenue = _pivot(_panel(2024, 1, ((revenue, "Revenue", "100"),)))
    unavailable = next(row for row in _records(QuarterlyDerivedMetricsBuilder().build(pivot=only_revenue), "GROSS_MARGIN"))
    assert unavailable["evaluation_status"] == "REQUIRED_INPUT_NOT_AVAILABLE"


def test_multiple_role_candidates_keep_every_considered_cell_lineage() -> None:
    revenue, gross = "us-gaap:Revenues", "us-gaap:GrossProfit"
    panel = _panel(
        2024, 1, ((revenue, "Revenue total", "100"), (revenue, "Revenue region", "60"), (gross, "Gross", "50"))
    )
    values = [dict(row) for row in panel.values]
    # Make the second Revenue a distinct, safely represented dimensional row,
    # rather than a duplicate T5 value in the same pivot coordinate.
    values[1]["raw_dimension_signature"] = (("us-gaap:StatementGeographicalAxis", "nvda:USMember", None, "EXPLICIT", False),)
    values[1]["canonical_dimension_signature"] = (("company:geo", "company:us", None, "EXPLICIT", False),)
    values[1]["dimension_mapping_ids"] = (("map:axis", "map:member"),)
    dimensional = CompanyAnalysisPanelResult(panel.definitions, panel.bindings, tuple(values), panel.scope)
    result = QuarterlyDerivedMetricsBuilder().build(pivot=_pivot(dimensional))
    gross_margin = next(row for row in _records(result, "GROSS_MARGIN"))
    assert gross_margin["evaluation_status"] == "MULTIPLE_CANDIDATES"
    assert len(gross_margin["ordered_input_cell_ids"]) == 3
    assert len(gross_margin["input_lineage"]) == 3
    assert [item["input_role"] for item in gross_margin["input_lineage"]] == [
        "GROSS_PROFIT",
        "REVENUE",
        "REVENUE",
    ]
    assert {item["candidate_status"] for item in gross_margin["input_lineage"]} == {"REPORTED"}


def test_margin_requires_qualified_us_gaap_identity_and_complete_provenance() -> None:
    revenue, operating = "us-gaap:Revenues", "us-gaap:OperatingIncomeLoss"
    pivot = _pivot(_panel(2024, 1, ((revenue, "Revenue", "100"), (operating, "OI", "20"))))
    result = QuarterlyDerivedMetricsBuilder().build(pivot=pivot)
    operating_margin = next(row for row in _records(result, "OPERATING_MARGIN"))
    assert operating_margin["value_percentage_points"] == Decimal("20.0")
    # A local-name lookalike cannot enter the standard role classifier.
    lookalike = deepcopy(pivot)
    for row in lookalike.rows:
        if row["first_binding"]["raw_concept_qname"] == operating:
            row["first_binding"]["raw_concept_taxonomy_family"] = "nvda"
    unavailable = next(
        row for row in _records(QuarterlyDerivedMetricsBuilder().build(pivot=lookalike), "OPERATING_MARGIN")
    )
    assert unavailable["evaluation_status"] == "REQUIRED_INPUT_NOT_AVAILABLE"


def test_component_share_needs_actual_statement_parent_navigation_not_label_order() -> None:
    parent_qname, child_qname = "us-gaap:Revenues", "nvda:DataCenterRevenue"
    panel = _panel(2024, 1, ((parent_qname, "Revenue", "100"), (child_qname, "Data Center", "40")))
    definitions = [dict(row) for row in panel.definitions]
    bindings = [dict(row) for row in panel.bindings]
    child = definitions[1]
    child["parent_analysis_line_id"] = definitions[0]["analysis_line_id"]
    bindings[1]["relationship_navigation"] = ({"edge_type": "STATEMENT_COMPONENT", "analysis_exploration_edge_id": "edge:1"},)
    evidence_panel = CompanyAnalysisPanelResult(tuple(definitions), tuple(bindings), panel.values, panel.scope)
    shared = _records(QuarterlyDerivedMetricsBuilder().build(pivot=_pivot(evidence_panel)), "COMPONENT_SHARE")
    assert len(shared) == 1 and shared[0]["value_percentage_points"] == Decimal("40.0")
    bindings[1]["relationship_navigation"] = ({"edge_type": "DIMENSION_LENS"},)
    false_panel = CompanyAnalysisPanelResult(tuple(definitions), tuple(bindings), panel.values, panel.scope)
    assert not _records(QuarterlyDerivedMetricsBuilder().build(pivot=_pivot(false_panel)), "COMPONENT_SHARE")
