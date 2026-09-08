"""Actual cached-source evidence. Set SEC_XBRL_HIERARCHY_BUNDLE explicitly.

These tests never download SEC data. Synthetic review/threshold evidence lives
in unit tests and is not represented as actual-source approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from lxml import html

from sec_xbrl.analysis import open_analysis


@pytest.fixture(scope="module")
def client():
    value = os.environ.get("SEC_XBRL_HIERARCHY_BUNDLE")
    if not value:
        pytest.skip("explicit cached H1 publication not supplied")
    return open_analysis(Path(value))


def panel(client, ticker, accession, section):
    table = next(t for t in client.statement_catalog(ticker)["tables"] if t["filing"]["accession"] == accession and t["section"] == section)
    return client.statement(ticker, table["table_id"])


def test_actual_nvda_same_table_two_period_signed_cal_and_review(client):
    p = panel(client, "NVDA", "0001045810-25-000230", "IS")
    assert p["table"]["table_locator"] == "/html/body/div[64]/table"
    assert len(p["rows"]) == 27
    by_inline = {loc["inline_id"]: f for f in p["facts"] for loc in f["source_locations"] if loc["table_id"] == p["table"]["table_id"]}
    for tags in (("f-50", "f-42", "f-46"), ("f-51", "f-43", "f-47")):
        parent, a, b = [by_inline[t] for t in tags]
        assert a["scope"] == b["scope"] == parent["scope"]
        assert Decimal(a["value_numeric"]) + Decimal(b["value_numeric"]) == Decimal(parent["value_numeric"])
        checks = [c for c in p["checks"] if c["parent_fact_id"] == parent["fact_id"] and c["network_identity"]["role_id"] == p["table"]["role_id"]]
        assert len(checks) == 1 and checks[0]["status"] == "MATCH"
    assert by_inline["f-43"]["fact_id"] == "fact_6c196d8796454dc9360eebc6"
    income = next(c for c in p["checks"] if c["parent_fact_id"] == by_inline["f-54"]["fact_id"] and c["network_identity"]["role_id"] == p["table"]["role_id"])
    assert income["status"] == "MATCH"
    assert sorted(i["weight"] for i in income["inputs"]) in [["-1.0", "1.0"], ["-1", "1"]]
    current = [i for i in p["importance"] if i["comparison_fact_id"] and i.get("review")]
    assert len(current) == 2
    for i in current:
        assert abs(Decimal(i["share_change_pp"]["value"])) < Decimal(5)
        assert "REVIEWED_SHARE_CHANGE_AT_LEAST_5_PP" not in i["reasons"]
        assert len(i["share_change_pp"]["input_ids"]) == 4
    heading = next(r for r in p["rows"] if r["label"] == "Operating expenses")
    children = [r for r in p["rows"] if r["parent_row_id"] == heading["row_id"]]
    assert [r["label"] for r in children] == ["Research and development", "Sales, general and administrative", "Total operating expenses"]
    assert children[-1]["protected"]
    assert {f["scope"]["period"]["class"] for f in p["facts"]} >= {"QTD_3M", "YTD_9M"}


def test_actual_msft_expense_structure_preserved(client):
    p = panel(client, "MSFT", "0001193125-26-191507", "IS")
    concepts = {f["concept"]["qname"] for f in p["facts"]}
    assert "us-gaap:OperatingExpenses" not in concepts
    assert {"us-gaap:SellingAndMarketingExpense", "us-gaap:GeneralAndAdministrativeExpense"} <= concepts
    f = next(f for f in p["facts"] if f["concept"]["qname"] == "us-gaap:OperatingIncomeLoss" and f["value_numeric"] == "38398000000")
    check = next(c for c in p["checks"] if c["parent_fact_id"] == f["fact_id"] and c["network_identity"]["role_id"] == p["table"]["role_id"])
    assert check["status"] == "MATCH"
    assert len(check["inputs"]) == 4
    assert sum(Decimal(i["contribution"]) for i in check["inputs"]) == Decimal(38398000000)


@pytest.mark.parametrize("ticker", ["AMD", "NVDA", "MSFT", "AMZN", "AAPL", "NFLX"])
def test_real_source_coverage_and_fy_ytd_instant(client, ticker):
    tables = client.statement_catalog(ticker)["tables"]
    primary = [t for t in tables if t["section"] in {"IS", "BS", "CF"}]
    assert primary
    period_classes = set()
    for table in primary:
        p = client.statement(ticker, table["table_id"])
        assert len(p["rows"]) == table["row_count"]
        assert [r["source_order"] for r in p["rows"]] == list(range(table["row_count"]))
        assert not any(r["coverage_status"] == "UNPREPARED" for r in p["rows"])
        period_classes.update(f["scope"]["period"]["class"] for f in p["facts"])
    assert {"FY", "INSTANT", "QTD_3M", "YTD_9M"} <= period_classes


def test_original_html_independent_denominator(client):
    """Enumerate raw HTML directly, independent of PRE/source materializer."""
    root = Path(os.environ["SEC_XBRL_PROJECT_ROOT"])
    p = panel(client, "NVDA", "0001045810-25-000230", "IS")
    package = root / "data/raw/trailing_corpus_runs/20260827T051322Z/packages/0001045810/000104581025000230/0001045810-25-000230-xbrl.zip"
    with zipfile.ZipFile(package) as archive:
        doc = archive.read("nvda-20251026.htm")
    tree = html.fromstring(doc)
    source = tree.xpath(p["table"]["table_locator"])[0]
    rows = [r for r in source.xpath(".//tr") if next(r.iterancestors("table")) is source]
    assert len(rows) == len(p["rows"])
    assert hashlib.sha256(doc).hexdigest() == p["table"]["source_document_sha256"]
    assert [tree.getroottree().getpath(r) for r in rows] == [r["row_locator"] for r in p["rows"]]


def test_unknown_scope_and_offline_boundary(client):
    from sec_xbrl import analysis
    from sec_xbrl.analytics import hierarchy_publication, importance_v2, statement_source
    def fail(*args, **kwargs):
        raise AssertionError("query invoked a producer or network")
    with patch.object(analysis, "prepare_analysis", fail), patch.object(analysis, "_raw_material", fail), patch.object(hierarchy_publication, "prepare_hierarchy", fail), patch.object(statement_source, "prepare_filing", fail), patch.object(importance_v2, "materialize_analytical_v2", fail), patch.object(socket, "socket", fail), patch.object(socket, "getaddrinfo", fail):
        for ticker in client.manifest["companies"]:
            t = next(t for t in client.statement_catalog(ticker)["tables"] if t["section"] == "IS")
            p = client.statement(ticker, t["table_id"])
            client.pre_table(ticker, t["table_id"])
            axes = client.axes(ticker, t["filing_id"])["axes"]
            client.importance_v2(ticker)
            if axes:
                a, m = axes[0], axes[0]["members"][0]
                result = client.member_metrics(ticker, t["filing_id"], axis_id=a["axis_id"], member_id=m["member_id"], typed_value=m["typed_value"])
                assert len({f["fact_id"] for f in result["facts"]}) == len(result["facts"])
                assert all(any(d["axis"] == a["axis_id"] for d in f["scope"]["dimensions"]) for f in result["facts"])
            with pytest.raises(ValueError):
                client.member_metrics(ticker, "unknown-filing", axis_id="unknown", member_id="unknown")
            with pytest.raises(ValueError):
                client.member_metrics(ticker, t["filing_id"], axis_id="unknown", member_id="unknown")
            assert p["facts"]


def test_old_v1_dataset_bytes_and_values_unchanged(client):
    root = Path(os.environ["SEC_XBRL_PROJECT_ROOT"])
    old = open_analysis(root / "work/u3_complete/bundle")
    for ticker, info in old.manifest["companies"].items():
        for view, vi in info["views"].items():
            for name, old_file in vi["files"].items():
                new_file = client.manifest["companies"][ticker]["views"][view]["files"][name]
                assert old_file["sha256"] == new_file["sha256"]
                assert old._records(ticker, view, name) == client._records(ticker, view, name)
    # Extra baseline evidence is optional; dataset identity above is mandatory.
    baseline = os.environ.get("SEC_XBRL_HIERARCHY_BASELINE_HASHES")
    if baseline:
        hashes = json.loads(Path(baseline).read_text())
        assert isinstance(hashes, dict) and hashes, "explicit baseline must be nonempty"
        for path, digest in hashes.items():
            assert isinstance(digest, str) and len(digest) == 64
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path


def test_supplemental_msft_cal11_and_amendment_coverage(client):
    p = panel(client, "MSFT", "0001193125-26-191507", "IS")
    relationships = client._hierarchy_records("MSFT", "statement_relationships", p["table"]["filing_id"])
    supplemental = [r for r in relationships if r["arcrole"] == "https://xbrl.org/2023/arcrole/summation-item"]
    assert supplemental and all(r["evidence_origin"] == "ADDITIVE_ARELLE_CALCULATION_1_1" for r in supplemental)
    assert all(r["source_document_sha256"] and r["parser_version"].startswith("arelle-release:") for r in supplemental)
    amendment = next(i for i in client.statement_catalog("AMD")["filings"] if i["filing"]["accession"] == "0000002488-26-000021")
    assert amendment["filing"]["form"] == "10-K/A"
    assert all(r["status"] == "NOT_PREPARED" for r in amendment["primary_coverage"])
    assert client._hierarchy_records("AMD", "statement_facts", amendment["filing"]["filing_id"])


def test_actual_nvda_segments_adjustments_and_amd_reorganization(client):
    """Exact reported amounts checked independently; no aggregate is authorized."""
    table = next(t for t in client.statement_catalog("NVDA")["tables"] if t["filing"]["accession"] == "0001045810-25-000230")
    facts = client._hierarchy_records("NVDA", "statement_facts", table["filing_id"])
    inline = {loc["inline_id"]: f for f in facts for loc in f["source_locations"]}
    assert [Decimal(inline[tag]["value_numeric"]) for tag in ("f-858", "f-859", "f-860")] == [Decimal(50908000000), Decimal(6098000000), Decimal(57006000000)]
    assert len(inline["f-858"]["scope"]["dimensions"]) == 2
    assert len(inline["f-860"]["scope"]["dimensions"]) == 1
    assert Decimal(inline["f-864"]["value_numeric"]) + Decimal(inline["f-865"]["value_numeric"]) == Decimal(inline["f-866"]["value_numeric"])
    assert inline["f-866"]["value_numeric"] == "38267000000"
    assert [inline[t]["value_numeric"] for t in ("f-906", "f-910", "f-914")] == ["1655000000", "515000000", "87000000"]
    assert Decimal(inline["f-902"]["value_numeric"]) - sum(Decimal(inline[t]["value_numeric"]) for t in ("f-906", "f-910", "f-914")) == Decimal(36010000000)
    table = next(t for t in client.statement_catalog("AMD")["tables"] if t["filing"]["accession"] == "0000002488-26-000018")
    facts = client._hierarchy_records("AMD", "statement_facts", table["filing_id"])
    gaming = [f for f in facts if f["value_numeric"] == "3910000000" and f["scope"]["period"]["class"] == "FY"]
    assert any({d["member_qname"] for d in f["scope"]["dimensions"]} >= {"amd:GamingMember"} for f in gaming)
    assert any(f["value_numeric"] == "4007000000" and any("AllOther" in (d["member_qname"] or "") for d in f["scope"]["dimensions"]) for f in facts)
    # The displayed All Other loss f-539 actually has only the source
    # OperatingSegments dimension. Preserve that source discrepancy too.
    loss = next(f for f in facts if any(l["inline_id"] == "f-539" for l in f["source_locations"]))
    assert loss["value_numeric"] == "-4007000000"
    assert [d["member_qname"] for d in loss["scope"]["dimensions"]] == ["us-gaap:OperatingSegmentsMember"]
    assert any("retrospect" in (f["value_text"] or "").lower() for f in facts)
