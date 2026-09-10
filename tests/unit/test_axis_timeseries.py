"""Synthetic identity/scope probes; no SEC fixtures or producer calls in queries."""
import hashlib
import json
from copy import deepcopy
from typing import ClassVar

import pytest

from sec_xbrl.analytics.axis_timeseries import _validate_review, prepare_axis_timeseries
from sec_xbrl.analytics.axis_timeseries_queries import _cell_matches_binding, axis_timeseries


class Client:
    axis_manifest = None
    manifest: ClassVar[dict] = {"publication_id": "old", "companies": {"TEST": {"views": {"LATEST_REPORTED": {"files": {}}}}}}

    def __init__(self, count=3):
        self.calls = []
        self.nodes = [{"node_id": f"n{i}", "row_id": f"epoch{i}", "label": "Same label", "period_class": "QTD_3M", "importance_reasons": ["KEEP"], "importance_history": [{"warnings": ["BASIS_WARNING"]}]} for i in range(count)]
        self.cells = [{"node_id": n["node_id"], "cell_id": f"c{i}", "fiscal_year": 2025, "fiscal_quarter": 1, "period_class": "QTD_3M", "status": "REPORTED", "value": str(i), "source_fact_id": None} for i,n in enumerate(self.nodes)]
        self.lens = {"node_id": "lens", "kind": "LENS", "lens_type": "DIMENSIONAL_VIEW", "anchor_row_id": "metric", "dimensions": ["axis"]}

    def _validate_context(self, context):
        return "TEST", "LATEST_REPORTED", {(2025,1),(2025,2)}

    def _records(self, ticker, view, name):
        return [{"row_id": "metric", "label": "Total"}] if name == "core_rows" else []

    def children(self, lens_id, *, cursor, limit, selection, context):
        assert selection == "all"
        self.calls.append(cursor)
        start = int(cursor or 0)
        return {"parent": self.lens, "children": self.nodes[start:start+limit], "cells": self.cells[start:start+limit], "parent_cells": [], "columns": [], "evidence": [], "next_cursor": str(start+limit) if start+limit < len(self.nodes) else None}


def test_all_nodes_pagination_nulls_and_epochs():
    c = Client(1003)
    a = axis_timeseries(c, "test", "lens", context={})
    assert len(c.calls) == 2
    assert len(a["rows"]) == 1004
    assert len({r["mapping_epoch"] for r in a["rows"][1:]}) == 1003
    for row in a["rows"]:
        assert len(row["cells"]) == 2
        assert row["cells"][1]["value"] is None
        assert row["cells"][1]["status"] == "UNAVAILABLE"
    assert a["rows"][1]["cells"][0]["value"] == "0"
    assert a["rows"][1]["importance_reasons"] == ["KEEP"]
    assert a["rows"][1]["warnings"] == ["BASIS_WARNING"]
    a["rows"][1]["cells"][0]["value"] = "changed"
    assert c.cells[0]["value"] == "0"


@pytest.mark.parametrize("defect", ["ticker", "lens", "period", "duplicate", "repeated_cursor"])
def test_query_rejects_invalid_scope(defect):
    c = Client(1001 if defect == "repeated_cursor" else 3)
    if defect == "lens": c.lens["lens_type"] = "PRE"
    if defect == "period": c.cells[0]["period_class"] = "YTD_9M"
    if defect == "duplicate": c.cells.append(deepcopy(c.cells[0]))
    if defect == "repeated_cursor":
        original = c.children
        c.children = lambda *a, **kw: {**original(*a, **kw), "next_cursor": "1000"}
    # Put duplicate in the page even when there are fewer nodes than cells.
    if defect == "duplicate": c.nodes.append({**c.nodes[0], "node_id": "extra"})
    with pytest.raises(ValueError):
        axis_timeseries(c, "OTHER" if defect == "ticker" else "TEST", "lens", context={})


def reviewed():
    period = {"class": "QTD_3M", "start": "2025-01-01", "end": "2025-04-01", "instant": None, "type": "duration"}
    filing = {"accession": "acc", "cik": "123"}
    table = {"table_id": "table", "table_locator": "xpath", "table_sha256": "hash", "source_document_sha256": "doc-hash", "filing_id": "f", "source_document": "doc", "filing": filing}
    facts=[]
    for i,value in enumerate(["3", "1", "2"]):
        facts.append({"fact_id": f"f{i}", "value_numeric": value, "filing_id": "f", "filing": filing, "raw_concept_id": "concept", "source_document": "doc", "reported_or_derived": "REPORTED", "scope": {"period": period, "filing_id": "f", "cik": "123", "as_of": "2025-06-01", "basis": "RAW:f", "view": "RAW_AS_FILED", "unit": {"numerator": ["USD"], "denominator": []}, "dimensions": [] if i==0 else [{"axis_qname": "axis", "member_qname": f"m{i}", "typed_value": None}]}})
    rows=[{"row_id": f"r{i}", "source_order": i, "cells": [{"inline_facts": [{"fact_id": f"f{i}"}]}]} for i in range(3)]
    panel={"publication_id": "old", "table": table, "facts": facts, "rows": rows}
    review={**{k:table[k] for k in ["table_id", "table_locator", "table_sha256", "source_document_sha256"]}, "accession": "acc", "axis": "axis", "reviewer": "lead", "status": "LEAD_APPROVED_EXACT_SOURCE_COMPOSITION_AND_DISPLAY", "checks": [{"parent_fact_id": "f0", "child_fact_ids": ["f1", "f2"], "parent_row": 0, "child_rows": [1,2], "weights": ["1", "1"], "period": period, "difference": "0"}]}
    return deepcopy(review), deepcopy(panel)


def test_exact_review():
    r,p=reviewed()
    _validate_review(r,p,publication_id="old",attested_panel=deepcopy(p))


@pytest.mark.parametrize("defect", ["unattested", "period", "concept", "cik", "filing", "as_of", "basis", "view", "unit", "nonfinite", "nil", "derived", "duplicate_scope", "crossaxis", "parent_scope", "weight", "difference", "duplicate_fact", "duplicate_order", "duplicate_equation", "source_row"])
def test_review_rejects_full_scope_defects(defect):
    r,p=reviewed(); f=p["facts"][1]; check=r["checks"][0]
    if defect=="unattested":
        attested=deepcopy(p); f["value_numeric"]="999"
    elif defect=="period":
        for fact in p["facts"]: fact["scope"]["period"]["class"]="YTD_9M"
        check["period"]["class"]="YTD_9M"
    elif defect=="concept": f["raw_concept_id"]="other"
    elif defect=="filing": f["filing_id"]="other"
    elif defect in {"cik", "as_of", "basis", "view"}: f["scope"][defect]="other"
    elif defect=="unit": f["scope"]["unit"]={"numerator":["EUR"],"denominator":[]}
    elif defect=="nonfinite": f["value_numeric"]="Infinity"
    elif defect=="nil": f["is_nil"]=True
    elif defect=="derived": f["reported_or_derived"]="DERIVED"
    elif defect=="duplicate_scope": p["facts"][2]["scope"]["dimensions"]=deepcopy(f["scope"]["dimensions"])
    elif defect=="crossaxis": f["scope"]["dimensions"].append({"axis_qname":"other"})
    elif defect=="parent_scope": p["facts"][0]["scope"]["dimensions"]=deepcopy(f["scope"]["dimensions"])
    elif defect=="weight": check["weights"][0]="NaN"
    elif defect=="difference": check["difference"]="1"
    elif defect=="duplicate_fact": p["facts"].append(deepcopy(f))
    elif defect=="duplicate_order": p["rows"][1]["source_order"]=0
    elif defect=="duplicate_equation": r["checks"].append(deepcopy(check))
    elif defect=="source_row": check["parent_row"]=1
    if defect!="unattested": attested=deepcopy(p)
    with pytest.raises(ValueError): _validate_review(r,p,publication_id="old",attested_panel=attested)


def test_id_only_binding_cannot_pass():
    binding={"fact_id":"f", "value_numeric":"1", "period":{"class":"QTD_3M","start":"s","end":"e"}, "status":"REPORTED", "filing_id":"filing", "accession":"acc", "raw_concept_id":"concept", "unit":[[],[]],"raw_dimension_signature":[]}
    cell={"source_fact_id":"f", "value":"1", "period_class":"QTD_3M","start":"s","end":"e","status":"REPORTED"}
    assert not _cell_matches_binding(cell,binding)
    cell["provenance"]={"value_lineage":{"source_filing_id":"filing","accession":"acc","raw_concept_id":"concept"}}
    assert _cell_matches_binding(cell,binding)
    cell["provenance"]["value_lineage"]["raw_dimension_signature"]=[["other"]]
    assert not _cell_matches_binding(cell,binding)


def test_publication_copy_and_safe_paths(tmp_path):
    source=tmp_path/"source";source.mkdir()
    payload=b"immutable\n";(source/"data").write_bytes(payload)
    manifest={"version":"consumer-focused-analysis-v1","publication_id":"old","files":{"x":{"path":"data","sha256":hashlib.sha256(payload).hexdigest()}}}
    (source/"analysis_manifest.json").write_text(json.dumps(manifest))
    dest=tmp_path/"new"
    prepare_axis_timeseries(source_bundle=source,destination=dest)
    assert (dest/"data").read_bytes()==payload
    assert (dest/"analysis_manifest.json").read_bytes()==(source/"analysis_manifest.json").read_bytes()
    with pytest.raises(ValueError): prepare_axis_timeseries(source_bundle=dest,destination=tmp_path/"again")
    link=tmp_path/"link";link.symlink_to(source,target_is_directory=True)
    with pytest.raises(ValueError): prepare_axis_timeseries(source_bundle=link,destination=tmp_path/"unsafe")
    with pytest.raises(ValueError): prepare_axis_timeseries(source_bundle=source,destination=source/"inside")
    (source/"alias").symlink_to(source/"data")
    with pytest.raises(ValueError): prepare_axis_timeseries(source_bundle=source,destination=tmp_path/"unsafe2")


def test_companion_cache_key_and_defensive_copy(tmp_path):
    from sec_xbrl.analysis import AnalysisClient
    c=object.__new__(AnalysisClient); c.root=tmp_path; c._axis_cache={}
    c.axis_manifest={"publication_id":"a","decision_cutoff":"one"}
    path=tmp_path/"review.json";path.write_text('{"value":1}')
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    value=c._axis_json(path.name,checksum);value["value"]=0
    assert c._axis_json(path.name,checksum)["value"]==1
    c.axis_manifest={"publication_id":"b","decision_cutoff":"two"}
    c._axis_json(path.name,checksum)
    assert len(c._axis_cache)==2
    with pytest.raises(ValueError): c._axis_json(path.name,"bad")
