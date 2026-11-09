from __future__ import annotations

from examples.screening.prepare_revenue_breakdowns import (
    SEGMENT_AXIS,
    _add_revenue_ratios,
    _product_hierarchy,
    _same_fiscal_duration,
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
    assert segment["cells"][2]["share"] is None
    assert segment["cells"][2]["yoy"] is None
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


CURRENT_PERIOD = {"fiscal_year": 2026, "fiscal_quarter": 2,
                  "period_start": "2026-04-01", "period_end": "2026-07-01"}
PRIOR_PERIOD = {"fiscal_year": 2025, "fiscal_quarter": 2,
                "period_start": "2025-04-01", "period_end": "2025-07-01"}
SEGMENT_DIMS = [_dimension("raw-segment-axis", "raw-services")]
PRODUCT_DIMS = [*SEGMENT_DIMS, _dimension("raw-product-axis", "raw-search")]


def _reported(fact_id, value, dimensions, *, prior=False, **overrides):
    period = PRIOR_PERIOD if prior else CURRENT_PERIOD
    return {
        "source_snapshot_id": "snapshot", "source_filing_id": "filing", "accession": ACCESSION,
        "filed_date": "2026-07-25", "source_fact_id": fact_id,
        "raw_concept_id": "raw-revenue", "raw_concept_qname": CONCEPT,
        "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2026", "raw_concept_is_standard": True,
        "raw_dimension_signature": dimensions, "context_period_kind": "DURATION", "context_duration_days": 91,
        "unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": "[]",
        "context_start_date": period["period_start"], "context_end_date": period["period_end"],
        "comparative_type": "PRIOR_YEAR_COMPARABLE" if prior else "CURRENT_FOCUS",
        "is_nil": False, "reported_or_derived": "REPORTED", "value_numeric": value, **overrides,
    }


def _ratios(current, *comparatives, include_segment=True, **overrides):
    total = _reported("total", "200", [])
    segment = _reported("segment", "100", SEGMENT_DIMS)

    def cell(row, **overrides):
        return {
            "status": "REPORTED", "cell_id": row["source_fact_id"], "value": row["value_numeric"],
            "sources": [{"fact_id": row["source_fact_id"], "snapshot_id": row["source_snapshot_id"],
                         "accession": row["accession"], "filed_date": row["filed_date"],
                         "qname": row["raw_concept_qname"]}],
            "share": None, "yoy": None, **overrides,
        }

    product = cell(current, **overrides)
    group = {"segments": [{"group": "segments", "scope": None, "member": "services",
                           "axis_members": {SEGMENT_AXIS: "services"}, "cells": [cell(segment)]}]
             if include_segment else [],
             "products": [{"group": "products", "scope": "services", "axis_members": {SEGMENT_AXIS: "services",
                          PRODUCT: "search"}, "mapping_review_required": True, "cells": [product]}]}
    _add_revenue_ratios([cell(total)], group, [CURRENT_PERIOD], [PRIOR_PERIOD, CURRENT_PERIOD],
                        [total, segment, current, *comparatives])
    return product, group


def test_ratio_uses_exact_segment_subtotal_and_same_filing_prior_even_across_mapping_epochs():
    current = _reported("current", "60", PRODUCT_DIMS)
    prior = _reported("prior", "50", list(reversed(PRODUCT_DIMS)), prior=True)
    duplicate = {**prior, "source_fact_id": "prior-other-appearance"}
    cell, groups = _ratios(current, prior, duplicate)
    assert cell["share"] == "60.0"
    assert cell["yoy"] == "20.0"
    assert cell["ratios"]["share"] == {"denominator": "SEGMENT_SUBTOTAL", "numerator_fact_id": "current",
                                       "denominator_fact_id": "segment"}
    evidence = cell["ratios"]["yoy"]
    assert evidence["prior_fact_ids"] == ["prior", "prior-other-appearance"]
    assert evidence["prior_period_start"] == "2025-04-01" and evidence["prior_period_end"] == "2025-07-01"
    assert groups["segments"][0]["cells"][0]["share"] == "50.0"
    assert _ratios(current, prior, include_segment=False)[0]["share"] is None


def test_ratio_holds_bad_legs_and_conflicts_while_preserving_valid_zero():
    current = _reported("current", "0", PRODUCT_DIMS)
    prior = _reported("prior", "50", PRODUCT_DIMS, prior=True)
    zero, _ = _ratios(current, prior)
    assert (zero["share"], zero["yoy"]) == ("0", "-100")
    for invalid in (
        {**prior, "value_numeric": "0"},
        {**prior, "quality_blocking": True},
        {**prior, "source_snapshot_id": "other"},
        {**prior, "filed_date": "2026-11-01"},
        {**prior, "raw_concept_id": "other"},
        {**prior, "raw_dimension_signature": [*SEGMENT_DIMS, _dimension("raw-product-axis", "other")]},
        {**prior, "unit_numerator_measures": '["iso4217:EUR"]'},
        {**prior, "context_end_date": "2025-07-02"},
        {**prior, "comparative_type": "CURRENT_FOCUS"},
    ):
        assert _ratios(current, invalid)[0]["yoy"] is None
    assert _ratios(current, prior, {**prior, "source_fact_id": "prior-conflict", "value_numeric": "51"})[0]["yoy"] is None
    assert _ratios(current, prior, status="DERIVED")[0].get("ratios") is None
    assert _ratios(current, prior, value="1")[0].get("ratios") is None
    assert _ratios({**current, "value_numeric": "101"}, prior)[0]["share"] is None
    assert _ratios({**current, "source_snapshot_id": "other"}, prior)[0]["share"] is None
    assert _ratios({**current, "raw_concept_qname": "us-gaap:Revenues"}, prior)[0]["share"] is None
    assert _ratios({**current, "raw_dimension_signature": [_dimension("segment", "other"), PRODUCT_DIMS[1]]},
                   prior)[0]["share"] is None


def test_ratio_duration_allows_fiscal_week_and_leap_shifts_but_rejects_noncomparable_dates():
    assert _same_fiscal_duration("2024-02-04", "2025-02-09", "2023-02-05", "2024-02-04") == (371, 364)
    assert _same_fiscal_duration("2024-01-01", "2025-01-01", "2023-01-01", "2024-01-01") == (366, 365)
    assert _same_fiscal_duration("2026-04-01", "2026-07-01", "2025-04-01", "2025-07-09") is None


def _role(name, members, *, scoped=False):
    table, line = f"{name}-table", f"{name}-line"
    relationships = []

    def edge(network, source, target, arcrole, order=1):
        qname = {"raw-product-axis": PRODUCT, "raw-segment-axis": SEGMENT_AXIS,
                 "raw-services": "issuer:ServicesMember", "raw-revenue": CONCEPT}
        kind = "presentation" if network == "PRE" else "definition"
        relationships.append({
            "source_snapshot_id": "snapshot", "source_filing_id": "filing", "accession": ACCESSION,
            "filed_date": "2026-07-25", "role_id": name, "role_uri": f"urn:{name}", "role_definition": name,
            "network_type": network, "from_raw_concept_id": source, "to_raw_concept_id": target,
            "to_raw_concept_qname": qname.get(target, target), "to_namespace_uri": "http://fasb.org/us-gaap/2026",
            "arcrole": arcrole, "order": str(order), "target_role_uri": None, "usable": True,
            "link_qname": f"link:{kind}Link", "arc_qname": f"link:{kind}Arc",
            "relationship_id": f"{name}-{network}-{source}-{target}",
        })

    def pre(source, target, order=1):
        edge("PRE", source, target, "http://www.xbrl.org/2003/arcrole/parent-child", order)

    def dimensions(axis, domain, values):
        def definition(source, target, name):
            edge("DEF", source, target, f"http://xbrl.org/int/dim/arcrole/{name}")

        pre(table, axis)
        definition(table, axis, "hypercube-dimension")
        pre(axis, domain)
        definition(axis, domain, "dimension-domain")
        for order, member in enumerate(values, 1):
            pre(domain, member, order)
            definition(domain, member, "domain-member")

    pre(table, line)
    pre(line, "raw-revenue")
    dimensions("raw-product-axis", "product-domain", members)
    if scoped:
        dimensions("raw-segment-axis", "segment-domain", ["raw-services"])
    return relationships


def _hierarchy(amounts, roles, *, total="100", scoped=False, edit=None):
    observations = []

    def cell(name, value, dimensions):
        row = _reported(name, value, dimensions)
        observations.append(row)
        return {"cell_id": name, "value": value, "status": "REPORTED", "reason": None,
                "sources": [{"fact_id": name, "snapshot_id": "snapshot", "filed_date": row["filed_date"],
                             "accession": ACCESSION, "qname": CONCEPT}]}

    scope = "issuer:ServicesMember" if scoped else None
    parent_dimensions = SEGMENT_DIMS if scoped else []
    parent = cell("total", total, parent_dimensions)
    products = [
        {"id": name, "scope": scope, "member": name,
         "axis_members": {PRODUCT: name, **({SEGMENT_AXIS: scope} if scoped else {})},
         "cells": [cell(name, value, [*parent_dimensions, _dimension("raw-product-axis", name)])]}
        for name, value in amounts.items()
    ]
    segments = [{"member": scope, "cells": [parent]}] if scoped else []
    result = {"periods": [CURRENT_PERIOD], "totals": [parent], "groups": {"segments": segments, "products": products}}
    if edit:
        edit(result, observations)
    return _product_hierarchy(result, observations, lambda accession: tuple(roles) if accession == ACCESSION else ())[0]


def _display_rows(*rows):
    return [{"id": item, "children": []} if isinstance(item, str)
            else {"id": item[0], "children": _display_rows(*item[1])} for item in rows]


def test_two_complete_roles_with_shared_member_refine_one_reported_product():
    groups = _hierarchy({"product": "70", "service": "30", "phone": "50", "tablet": "20"},
                        [*_role("statement", ["product", "service"]), *_role("detail", ["tablet", "phone", "service"])])
    layout, = groups
    assert layout["mode"] == "RECONCILED"
    assert layout["groups"] == [{"rows": _display_rows(("product", ["tablet", "phone"]), "service")}]
    assert {row["role_uri"] for row in layout["evidence"]} == {"urn:statement", "urn:detail"}
    assert layout["parent_fact_id"] == "total"


def test_disjoint_complete_roles_stay_separate_even_when_amounts_happen_to_match():
    roles = [*_role("statement", ["product", "service"]), *_role("detail", ["store", "web"])]
    layout, = _hierarchy({"product": "70", "service": "30", "store": "70", "web": "30"}, roles)
    assert layout["mode"] == "DISCLOSURES"
    assert layout["groups"] == [{"label": "detail", "rows": _display_rows("store", "web")},
                                {"label": "statement", "rows": _display_rows("product", "service")}]


def test_single_role_requires_ordered_contiguous_children_and_reconciled_segment():
    values = {"search": "60", "video": "10", "network": "10", "advertising": "80", "subscriptions": "20"}
    roles = _role("detail", list(values), scoped=True)
    layout, = _hierarchy(values, roles, scoped=True)
    assert layout["scope"] == "issuer:ServicesMember"
    assert layout["groups"] == [{"rows": _display_rows(("advertising", ["search", "video", "network"]), "subscriptions")}]
    assert not _hierarchy(values, _role("detail", ["search", "advertising", "video", "network", "subscriptions"],
                                       scoped=True), scoped=True)
    assert not _hierarchy(values, roles, scoped=True, total="101")


def test_ambiguous_or_unbound_roles_do_not_imply_hierarchy():
    values = {"product": "70", "service": "30", "phone": "50", "tablet": "20"}
    coarse = _role("statement", ["product", "service"])
    details = _role("detail", ["phone", "tablet", "service"])
    assert not _hierarchy(values, [*coarse, *details, *_role("other", ["tablet", "phone", "service"])])
    assert not _hierarchy(values, [*coarse, *[edge for edge in details if edge["network_type"] != "DEF"]])
    assert not _hierarchy(values, [*coarse, *[{**edge, "source_snapshot_id": "another"} for edge in details]])
    assert not _hierarchy(values, [*coarse, *details],
                          edit=lambda result, _: result["totals"][0].update(status="DERIVED"))
    assert not _hierarchy(values, [*coarse, *details],
                          edit=lambda _, facts: facts[-1].update(context_end_date="2026-07-02"))
