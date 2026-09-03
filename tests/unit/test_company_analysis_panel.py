from __future__ import annotations

import pytest

from sec_xbrl.analytics import (
    CompanyAnalysisPanelBuilder,
    CompanyAnalysisPanelError,
    CompanyAnalysisPanelQuery,
)
from sec_xbrl.longitudinal import (
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
    OperationalLayer2Publisher,
)

CIK = "0001045810"
FILING = "filing:q3"
TOTAL = "fact:revenue-total"
DETAIL = "fact:data-center"
ROOT = "node:total"
AXIS = "node:product-axis"
MEMBER = "node:data-center"
DETAIL_NODE = "node:detail"


def _graph(tmp_path, *, snapshot_id: str = "snap:q3"):
    run = Layer2Run(
        "t5-fixture", "fixture",
        (Layer1SnapshotInput(CIK, "0001045810-23-000227", "10-Q", "2023-11-21", "2023-10-30", "snap:q3", "a" * 64),),
        Layer2RuleVersions("period", "mapping", "recast", "selection"),
    )
    nodes = (
        {"cik": CIK, "analysis_exploration_node_id": ROOT, "node_kind": "FACT", "origin": "STANDARD_CONCEPT", "raw_id": TOTAL, "source_filing_id": FILING, "source_fact_id": TOTAL, "source_snapshot_id": snapshot_id, "accession": "0001045810-23-000227", "filed_date": "2023-11-21", "context_id": f"ctx:{TOTAL}", "unit_id": "unit:usd", "raw_qname": "us-gaap:Revenues"},
        {"cik": CIK, "analysis_exploration_node_id": AXIS, "node_kind": "AXIS", "origin": "STANDARD_AXIS", "raw_id": "axis:product", "source_filing_id": FILING, "raw_qname": "srt:ProductOrServiceAxis"},
        {"cik": CIK, "analysis_exploration_node_id": MEMBER, "node_kind": "MEMBER", "origin": "CUSTOM_MEMBER", "raw_id": "member:data-center", "source_filing_id": FILING, "raw_qname": "nvda:DataCenterMember"},
        {"cik": CIK, "analysis_exploration_node_id": DETAIL_NODE, "node_kind": "FACT", "origin": "STANDARD_CONCEPT", "raw_id": DETAIL, "source_filing_id": FILING, "source_fact_id": DETAIL, "source_snapshot_id": "snap:q3", "accession": "0001045810-23-000227", "filed_date": "2023-11-21", "context_id": f"ctx:{DETAIL}", "unit_id": "unit:usd", "raw_qname": "us-gaap:Revenues"},
    )
    edges = (
        {"cik": CIK, "analysis_exploration_edge_id": "edge:lens", "edge_kind": "DIMENSION_LENS", "from_node_id": ROOT, "to_node_id": AXIS, "scope_kind": "TOTAL_FACT_AXIS_LENS", "order": None},
        {"cik": CIK, "analysis_exploration_edge_id": "edge:member", "edge_kind": "FACT_SCOPE", "from_node_id": AXIS, "to_node_id": MEMBER, "scope_kind": "AXIS_MEMBER_SCOPE", "order": None},
        {"cik": CIK, "analysis_exploration_edge_id": "edge:fact", "edge_kind": "FACT_SCOPE", "from_node_id": MEMBER, "to_node_id": DETAIL_NODE, "scope_kind": "MEMBER_SCOPED_FACT", "order": None},
    )
    published = OperationalLayer2Publisher(tmp_path / "graph").publish(run, {"analysis_exploration_node": nodes, "analysis_exploration_edge": edges})
    return Layer2PublicationReader().load(published.run_root)


def _selected(fact_id: str, *, dimensions=(), value: str = "18120000000"):
    return {
        "cik": CIK, "fiscal_year": 2024, "fiscal_quarter": 3, "period_class": "QTD_3M",
        "selection_status": "SELECTED", "selection_view": "LATEST_REPORTED", "selection_as_of_date": "2023-11-21", "selection_rule_version": "t4b-v1", "selection_reason": "LATEST_ELIGIBLE_DIRECT_REPORTED_OBSERVATION", "source_type": "REPORTED",
        "selected_source_fact_id": fact_id, "source_filing_id": FILING, "source_snapshot_id": "snap:q3", "accession": "0001045810-23-000227", "filed_date": "2023-11-21", "report_date": "2023-10-30",
        "context_id": f"ctx:{fact_id}", "unit_id": "unit:usd", "value_numeric": value, "value_text": None,
        "raw_concept_id": "concept:revenue", "raw_concept_qname": "us-gaap:Revenues", "raw_concept_is_standard": True, "raw_dimension_signature": dimensions, "canonical_dimension_signature": dimensions,
        "dimension_mapping_ids": (), "concept_mapping_id": "map:revenue", "concept_mapping_version": "map-v1", "company_canonical_concept_id": "company:revenue", "mapping_review_required": False,
        "comparability_status": "NOT_ASSESSED", "accession_version_ledger_id": "ledger:q3", "ledger_amendment_linkage_state": "NOT_APPLICABLE",
    }


def _build(tmp_path, rows):
    return CompanyAnalysisPanelBuilder().build(
        selected_rows=rows, exploration=_graph(tmp_path), cik=CIK, fiscal_year=2024, fiscal_quarter=3,
        period_class="QTD_3M", view="LATEST_REPORTED", as_of_date="2023-11-21", analysis_view_id="nvda-q3",
    )


def test_panel_separates_statement_and_custom_dimension_detail_with_full_lineage(tmp_path) -> None:
    panel = _build(tmp_path, (_selected(TOTAL), _selected(DETAIL, dimensions=(("axis:product", "member:data-center", None, "EXPLICIT", False),), value="14514000000")))
    assert [(row["line_scope"], row["label"], row["line_class"]) for row in panel.definitions] == [
        ("STATEMENT", "us-gaap:Revenues", "COMMON_GAAP"),
        ("EXPLORATION_DETAIL", "nvda:DataCenterMember", "COMPANY_CUSTOM"),
    ]
    detail = panel.values[1]
    assert detail["selected_source_fact_id"] == DETAIL
    assert detail["accession"] == "0001045810-23-000227"
    assert detail["context_id"] == "ctx:fact:data-center"
    assert detail["accession_version_ledger_id"] == "ledger:q3"
    assert len(panel.bindings[1]["relationship_navigation"]) == 3
    assert panel.definitions[1]["parent_analysis_line_id"] == panel.definitions[0]["analysis_line_id"]


def test_unavailable_is_a_visible_non_filled_row(tmp_path) -> None:
    unavailable = {**_selected(TOTAL), "selection_status": "UNAVAILABLE", "source_type": "UNAVAILABLE", "selected_source_fact_id": None, "source_filing_id": None, "accession": None, "source_snapshot_id": None, "context_id": None, "selection_unavailable_reason": "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION"}
    panel = _build(tmp_path, (unavailable,))
    row = CompanyAnalysisPanelQuery(panel).rows()[0]
    assert row["definition"]["line_scope"] == "UNAVAILABLE"
    assert row["value"]["value_status"] == "UNAVAILABLE"
    assert row["value"]["value_numeric"] is None


def test_panel_rejects_derived_or_wrong_as_of_selection(tmp_path) -> None:
    with pytest.raises(CompanyAnalysisPanelError, match="directly reported"):
        _build(tmp_path, ({**_selected(TOTAL), "source_type": "DERIVED"},))
    with pytest.raises(CompanyAnalysisPanelError, match="view/as-of"):
        _build(tmp_path, ({**_selected(TOTAL), "selection_as_of_date": "2024-01-01"},))


def test_panel_fails_closed_when_t3_fact_lineage_disagrees(tmp_path) -> None:
    with pytest.raises(CompanyAnalysisPanelError, match="source_snapshot_id"):
        CompanyAnalysisPanelBuilder().build(
            selected_rows=(_selected(TOTAL),), exploration=_graph(tmp_path, snapshot_id="snap:other"),
            cik=CIK, fiscal_year=2024, fiscal_quarter=3, period_class="QTD_3M",
            view="LATEST_REPORTED", as_of_date="2023-11-21",
        )


def test_query_returns_defensive_copies_and_does_not_calculate_metrics(tmp_path) -> None:
    panel = _build(tmp_path, (_selected(TOTAL),))
    query = CompanyAnalysisPanelQuery(panel)
    first = query.rows()[0]
    first["value"]["value_numeric"] = "changed"
    assert query.rows()[0]["value"]["value_numeric"] == "18120000000"
    assert "qoq" not in query.rows()[0]["value"]
