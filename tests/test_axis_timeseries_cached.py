"""Opt-in actual six-company prepared data evidence, kept separate from synthetic tests."""
import hashlib
import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from sec_xbrl.analysis import AnalysisClient


@pytest.fixture(scope="module")
def axis_client():
    root=os.environ.get("SEC_XBRL_AXIS_BUNDLE")
    if not root: pytest.skip("explicit prepared axis companion required")
    return AnalysisClient(Path(root))


@pytest.mark.parametrize("ticker", ["NVDA","AMD","MSFT","AMZN","AAPL","NFLX"])
def test_actual_all_axes_values_traces_periods_and_importance(axis_client,ticker):
    c=axis_client; info=c.manifest["companies"][ticker]
    with patch("sec_xbrl.analytics.axis_timeseries.prepare_axis_timeseries",side_effect=AssertionError("producer")), patch("sec_xbrl.analysis.prepare_analysis",side_effect=AssertionError("producer")), patch.object(socket,"socket",side_effect=AssertionError("network")):
        overview=c.overview(ticker,fiscal_start=min(info["years"]),fiscal_end=max(info["years"]))
        count=0; ranks=[]
        for row in overview["rows"]:
            for lens in c.list_breakdowns(row["row_id"],context=overview["context"])["groups"]:
                if lens["lens_type"]!="DIMENSIONAL_VIEW": continue
                result=c.axis_timeseries(ticker,lens["node_id"],context=overview["context"])
                expected=c.children(lens["node_id"],context=overview["context"],selection="all",limit=1000)
                assert expected["next_cursor"] is None # Actual corpus; >1000 separately synthetic.
                assert {r["row_id"] for r in result["rows"][1:]}=={n["node_id"] for n in expected["children"]}
                assert len(result["columns"])==len(overview["context"]["periods"])
                expected_cells={cell["cell_id"]:cell for cell in expected["cells"]+expected["parent_cells"]}
                for r in result["rows"]:
                    assert len(r["cells"])==len(result["columns"])
                    for cell in r["cells"]:
                        assert cell["period_class"]==result["period_class"]
                        if cell.get("cell_id"):
                            for key,value in expected_cells[cell["cell_id"]].items():
                                if key!="row_id": assert cell[key]==value
                            assert cell["provenance"]==c.trace(cell["cell_id"],context=overview["context"])["trace"]
                        else: assert cell["value"] is None
                    for record in r.get("importance_history",[]):
                        if record.get("amount_rank"): ranks.append(record["amount_rank"])
                count+=1
        assert count>0
        if ticker=="AMD":
            # AMD's rank>5 records belong to other prepared branches, not the
            # dimensional axis cohort. Keep those existing inspections intact.
            ranked=next(i for i in c._records(ticker,"LATEST_REPORTED","importance") if (i.get("amount_rank") or 0)>5)
            branch=c.children(ranked["parent_id"],context=overview["context"],selection="all",limit=1000)
            assert ranked["child_id"] in {n["node_id"] for n in branch["children"]}


def test_actual_exact_four_equations_and_epoch_boundaries(axis_client):
    c=axis_client; overview=c.overview("NVDA")
    lens=next(g for g in c.list_breakdowns("revenue",context=overview["context"])["groups"] if g["dimensions"]==["srt:ProductOrServiceAxis"])
    a=c.axis_timeseries("NVDA",lens["node_id"],context=overview["context"])
    assert len(a["rows"])==39
    assert len({r["label"] for r in a["rows"][1:]})==7
    checks=a["reviewed_relationships"]
    assert [r["display_scope"] for r in checks]==["ANALYTICAL_EXACT_MATCH"]*2+["SOURCE_COMPARISON_ONLY"]*2
    assert len({f for r in checks for f in [r["parent_fact_id"],*r["child_fact_ids"]]})==16
    for check in checks:
        assert check["publication"]==a["publication"]
        assert check["period"]["class"]=="QTD_3M"
        assert check["difference"]=="0"
    total,dc=checks[:2]
    assert len(total["child_row_ids"])==5 and len(dc["child_row_ids"])==2
    assert not set(total["child_row_ids"]) & set(dc["child_row_ids"])
    byid={r["row_id"]:r for r in a["rows"]}
    assert byid[dc["parent_row_id"]]["protected"]
    for child in dc["child_row_ids"]: assert byid[child]["parent_row_id"]==dc["parent_row_id"]
    comparison=a["source_comparisons"][0]
    assert len(comparison["rows"])==8 and len(comparison["columns"])==2
    assert comparison["publication"]==a["publication"]
    assert a["axis_context"]["axis_publication_id"]!=overview["context"]["publication_id"]
    assert a["axis_context"]["axis_decision_cutoff"]>overview["context"]["review_cutoff"]


def test_attested_old_bundle_bytes_unchanged(axis_client):
    source=os.environ.get("SEC_XBRL_AXIS_SOURCE_BUNDLE")
    if not source: pytest.skip("explicit immutable predecessor required")
    source=Path(source)
    files=[p for p in source.rglob("*") if p.is_file()]
    assert files
    for p in files:
        assert hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256((axis_client.root/p.relative_to(source)).read_bytes()).digest()
    old=AnalysisClient(source)
    for ticker in old.manifest["companies"]:
        assert old.overview(ticker)==axis_client.overview(ticker)
    report=os.environ.get("SEC_XBRL_AXIS_REPORT")
    if report: Path(report).write_text(json.dumps({"old_bundle_unchanged_files":len(files),"companies":list(old.manifest["companies"]),"status":"PASS"},indent=2))
