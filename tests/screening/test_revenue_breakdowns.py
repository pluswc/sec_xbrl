from __future__ import annotations

from examples.screening.prepare_revenue_breakdowns import (
    SEGMENT_AXIS,
    project_breakdowns,
)

CIK = "0000000042"
CUTOFF = "2026-10-25"
CONCEPT = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
PRODUCT = "srt:ProductOrServiceAxis"
ACCESSION = "0000000042-26-000001"


def _dimension(axis, member):
    return [axis, member, None, "EXPLICIT", "false"]


def _node(identifier, dimensions, *, review=False):
    return {
        "node_id": identifier, "kind": "VALUE", "period_class": "QTD_3M", "concept": CONCEPT,
        "origin_kind": "STANDARD", "label": identifier, "row_id": f"epoch-{identifier}",
        "dimensions": dimensions, "mapping_review_required": review,
    }


class _Prepared:
    def __init__(self):
        self.nodes = [
            _node("segment", [_dimension(SEGMENT_AXIS, "issuer:CloudMember")]),
            _node("product", [_dimension(PRODUCT, "issuer:SearchMember"),
                              _dimension(SEGMENT_AXIS, "issuer:ServicesMember")], review=True),
            _node("geography", [_dimension("srt:StatementGeographicalAxis", "issuer:EuropeMember")]),
            {"node_id": "segment-lens", "kind": "LENS"},
        ]
        self.edges = [{"parent_id": "segment-lens", "child_id": "segment", "kind": "OBSERVED_DIMENSION",
                       "periods": [[2026, 1], [2026, 3]]}]
        self.cells = [self.cell("segment", 1, "1000000"), self.cell("segment", 3, "3000000"),
                      self.cell("product", 2, "2000000"), self.cell("geography", 2, "4000000"),
                      {**self.cell("consolidated", 2, "99000000"), "row_id": "revenue", "dimensions": []}]

    @staticmethod
    def cell(node, quarter, value):
        month = 3 * quarter - 2
        return {
            "node_id": node, "cell_id": f"{node}-{quarter}", "source_fact_id": f"fact-{node}-{quarter}",
            "fiscal_year": 2026, "fiscal_quarter": quarter, "period_class": "QTD_3M", "status": "REPORTED",
            "start": f"2026-{month:02}-01", "end": f"2026-{month + 3:02}-01", "value": value,
            "selection_view": "LATEST_REPORTED", "as_of": CUTOFF, "unit": ['["iso4217:USD"]', "[]"],
        }

    def overview(self, ticker, **kwargs):
        assert ticker == "TEST" and kwargs["as_of"] == CUTOFF
        columns = [
            {"fiscal_year": 2026, "fiscal_quarter": quarter, "period_class": "QTD_3M",
             "actual_start_date": self.cell("period", quarter, "0")["start"],
             "actual_end_date": self.cell("period", quarter, "0")["end"]}
            for quarter in (1, 2, 3)
        ]
        columns.append({"fiscal_year": 2026, "fiscal_quarter": 4, "period_class": "QTD_3M",
                        "actual_start_date": "2026-10-01", "actual_end_date": "2027-01-01"})
        return {"context": {"ticker": ticker, "as_of": CUTOFF, "view": "LATEST_REPORTED"},
                "columns": columns, "cells": self.cells}

    def list_breakdowns(self, row_id, *, context):
        assert row_id == "revenue"
        return {"groups": [{"node_id": "segment-lens", "lens_type": "DIMENSIONAL_VIEW", "dimensions": [SEGMENT_AXIS]}]}

    def axis_timeseries(self, ticker, lens_id, *, context):
        assert lens_id == "segment-lens"
        return {"period_class": "QTD_3M", "rows": [{
            "row_kind": "MEMBER", "prepared_node": self.nodes[0],
            "cells": [cell for cell in self.cells if cell["node_id"] == "segment"],
            "importance_history": [{
                "current_cell_id": "segment-3", "share_status": "AVAILABLE", "parent_share": "12.5",
                "share_input_cell_ids": ["parent-3", "segment-3"], "change_status": "AVAILABLE",
                "rate_change": "4.25", "change_input_ids": ["segment-3", "segment-prev"],
            }],
        }]}

    def trace(self, cell_id, *, context):
        cell = next(cell for cell in self.cells if cell["cell_id"] == cell_id)
        return {"trace": {"value_lineage": {
            "accession": ACCESSION, "filed_date": "2026-10-12",
            "source_snapshot_id": f"l1:{CIK}:{ACCESSION.replace('-', '')}:snapshot",
            "selected_source_fact_id": cell["source_fact_id"], "raw_concept_qname": CONCEPT,
            "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2026", "raw_concept_is_standard": True,
        }}}

    def _records(self, ticker, view, name):
        assert ticker == "TEST" and view == "LATEST_REPORTED"
        return getattr(self, name)


def test_projects_stored_lens_and_unlinked_product_with_exact_scope_and_cutoff():
    projected = project_breakdowns(_Prepared(), "TEST", CIK, CUTOFF, "QTD_3M", 8)
    assert [row["fiscal_quarter"] for row in projected["periods"]] == [1, 2, 3]
    segment, = projected["groups"]["segments"]
    product, = projected["groups"]["products"]
    assert [cell["value"] for cell in segment["cells"]] == ["1000000", None, "3000000"]
    assert segment["cells"][2]["share"] == "12.5"
    assert segment["cells"][2]["yoy"] == "4.25"
    assert product["scope"] == "issuer:ServicesMember"
    assert product["mapping_epoch"] == "epoch-product"
    assert [cell["value"] for cell in product["cells"]] == [None, "2000000", None]
    assert product["cells"][1]["sources"][0]["accession"] == ACCESSION
    assert product["cells"][1]["share"] is None and product["cells"][1]["yoy"] is None


def test_keeps_competing_epochs_separate_and_blocks_bad_source_cells():
    fixture = _Prepared()
    fixture.nodes.append(_node("different-epoch", fixture.nodes[0]["dimensions"]))
    fixture.cells.append(fixture.cell("different-epoch", 3, "5000000"))
    fixture.cells[0]["quality_blocking"] = True
    projected = project_breakdowns(fixture, "TEST", CIK, CUTOFF, "QTD_3M", 8)
    assert len(projected["groups"]["segments"]) == 2
    for row in projected["groups"]["segments"]:
        assert all(cell["value"] is None for cell in row["cells"])
        assert row["cells"][-1]["reason"] == "COMPETING_PREPARED_SCOPE"


def test_fallback_never_reopens_hidden_lens_attachment_but_allows_unlinked_period():
    fixture = _Prepared()
    fixture.nodes.append({"node_id": "hidden-product-lens", "kind": "LENS", "hidden": True})
    fixture.edges.append({"parent_id": "hidden-product-lens", "child_id": "product",
                          "kind": "OBSERVED_DIMENSION", "periods": [[2026, 2]]})
    fixture.cells.append(fixture.cell("product", 1, "1000000"))
    projected = project_breakdowns(fixture, "TEST", CIK, CUTOFF, "QTD_3M", 8)
    product, = projected["groups"]["products"]
    assert [cell["value"] for cell in product["cells"]] == ["1000000", None, None]


def test_projects_consolidated_revenue_by_period_with_source_and_no_member_sum():
    fixture = _Prepared()
    projected = project_breakdowns(fixture, "TEST", CIK, CUTOFF, "QTD_3M", 8)
    totals = projected["totals"]
    assert [cell["value"] for cell in totals] == [None, "99000000", None]
    assert totals[1]["status"] == "REPORTED"
    assert totals[1]["sources"][0]["fact_id"] == "fact-consolidated-2"
    assert totals[0]["reason"] == "PERIOD_NOT_PREPARED"
    fixture.cells.append({**fixture.cells[-1], "cell_id": "competing-total"})
    projected = project_breakdowns(fixture, "TEST", CIK, CUTOFF, "QTD_3M", 8)
    assert projected["totals"][1]["reason"] == "COMPETING_PREPARED_SCOPE"
    assert projected["totals"][1]["value"] is None
