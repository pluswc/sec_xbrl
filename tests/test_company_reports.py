from __future__ import annotations

import csv
import json
import os
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl import company_reports as cr


def decision(**changes):
    return {**dict(zip(cr.DECISION_FIELDS, ("d1", "issue1", "AMD", "a1", "gaap:Revenue", "gaap:Axis", "amd:Client", "BLOCK", "reviewer", "confirmed mismatch", "source.html", "2026-09-07"))), **changes}


def cell(**changes):
    return {"value_numeric": "123", "value_text": None, "value_status": "REPORTED",
            "value_lineage": {"accession": "a1", "raw_concept_qname": "gaap:Revenue"}, **changes}


def test_issue_scope_and_specific_release():
    dims = [{"axis": "gaap:Axis", "member": "amd:Client"}]
    assert cr.materialize_quality(ticker="AMD", cell=cell(), dimensions=dims, decisions=[decision()])["analytical_value"] is None
    for ticker, dimension, concept in [("NVDA", dims, "gaap:Revenue"), ("AMD", [{"axis": "gaap:Axis", "member": "amd:Embedded"}], "gaap:Revenue"), ("AMD", dims, "gaap:Income")]:
        result = cr.materialize_quality(ticker=ticker, cell=cell(value_lineage={"accession": "a1", "raw_concept_qname": concept}), dimensions=dimension, decisions=[decision()])
        assert result["analytical_value"] == "123"
    result = cr.materialize_quality(ticker="AMD", cell=cell(), dimensions=dims,
                                    decisions=[decision(decision="RELEASE"), decision(issue_id="other", decision_id="d2")])
    assert result["quality_status"] == "BLOCK"


def test_derived_input_hold_and_no_value_reason():
    output = cell(value_status="DERIVED", value_lineage={"accession": None, "raw_concept_qname": "gaap:Revenue"})
    result = cr.materialize_quality(ticker="AMD", cell=output, dimensions=[], decisions=[decision(axis="", member="")],
                                    source_scopes=[{"accession": "a1", "concept": "gaap:Revenue", "dimensions": []}])
    assert result["quality_status"] == "BLOCK"
    assert output["value_numeric"] == "123"
    result = cr.materialize_quality(ticker="AMD", cell=cell(value_numeric=None, value_status="CONFLICT"), dimensions=[], decisions=[])
    assert result["quality_status"] == "UNAVAILABLE"
    assert result["quality_reasons"]
    result = cr.materialize_quality(ticker="AMD", cell=cell(comparability_status="COMPATIBLE_INPUTS", comparability_reason="approved inputs"), dimensions=[], decisions=[])
    assert result["quality_status"] == "AVAILABLE"


def test_review_time_append_only_ties_and_scope(tmp_path):
    cr.init_admin(tmp_path)
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [decision()])
    assert cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 6)) == []
    assert cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 7))[0]["decision"] == "BLOCK"
    saved = tmp_path / "runs" / "first"
    saved.mkdir(parents=True)
    (saved / "decisions.csv").write_bytes((tmp_path / "decisions.csv").read_bytes())
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [decision(reason="edited")])
    with pytest.raises(ValueError, match="edited"):
        cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 8))
    release = decision(decision_id="d2", decision="RELEASE", known_at="2026-09-08")
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [decision(), release])
    assert cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 8))[0]["decision"] == "RELEASE"
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [decision(), {**release, "known_at": "2026-09-07"}])
    with pytest.raises(ValueError, match="tie"):
        cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 8))
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [decision(), {**release, "member": "amd:Other"}])
    with pytest.raises(ValueError, match="scope"):
        cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 8))


def test_same_day_timestamp_decisions_and_timezone_cutoff(tmp_path):
    cr.init_admin(tmp_path)
    earlier = decision(known_at="2026-09-07T08:00:00+09:00")
    release = decision(decision_id="d2", decision="RELEASE", known_at="2026-09-07T09:00:00+09:00")
    future = decision(decision_id="d3", decision="BLOCK", known_at="2026-09-07T15:00:00Z")
    cr._csv(tmp_path / "decisions.csv", cr.DECISION_FIELDS, [earlier, release, future])
    assert cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 7))[0]["decision"] == "RELEASE"
    assert cr.read_decisions(tmp_path, review_as_of=date(2026, 9, 8))[0]["decision"] == "BLOCK"
    with pytest.raises(ValueError, match="timezone"):
        cr._decision_time("2026-09-07T09:00:00")


def test_manual_register_validation(tmp_path):
    cr.register_company(tmp_path, ticker="NVDA", publication=tmp_path)
    cr.register_company(tmp_path, ticker="NVDA", recent_fiscal_years=2)
    rows = cr._read_csv(tmp_path / "companies.csv", cr.COMPANY_FIELDS)
    assert rows[0]["publication"] == str(tmp_path)
    assert rows[0]["recent_fiscal_years"] == "2"
    for bad in [{**rows[0], "ticker": "../escape"}, {**rows[0], "active": "yes"}, {**rows[0], "recent_fiscal_years": "0"}, {**rows[0], "fiscal_start": "2025"}, {**rows[0], "publication": "relative"}]:
        with pytest.raises(ValueError):
            cr._validate_companies([bad])
    with pytest.raises(ValueError, match="duplicate"):
        cr._validate_companies(rows * 2)


def test_end_dates_and_scaling():
    assert cr._end("2023-04-02") == "2023-04-01"
    value = {"quality_status": "AVAILABLE", "analytical_value": "1234567890", "value_status": "DERIVED",
             "lineage": {"unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": "[]"}}
    assert cr._number(value) == "1,234.568 D"
    value["lineage"]["unit_denominator_measures"] = '["xbrli:shares"]'
    assert cr._number(value) == "1234567890 D"


def test_csv_text_safe_numeric_negative(tmp_path):
    from decimal import Decimal
    target = tmp_path / "values.csv"
    cr._csv(target, ("text", "number"), [{"text": "\t=CMD()", "number": Decimal(-123)}], safe=True)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row == {"text": "'\t=CMD()", "number": "-123"}


def test_report_settings_snapshot_and_new_run(tmp_path, monkeypatch):
    cr.register_company(tmp_path, ticker="NVDA", publication=tmp_path)
    original = (tmp_path / "companies.csv").read_bytes()
    def data(company, decisions, review_as_of=None):
        cr.register_company(tmp_path, ticker="AMD", publication=tmp_path)
        return {"ticker": company["ticker"], "years": [2024, 2025, 2026], "publication": str(tmp_path), "source_manifest_sha256": "test", "tables": [], "quality_overlay": []}
    monkeypatch.setattr(cr, "_company_data", data)
    run = cr.report(tmp_path, review_as_of=date(2026, 9, 7))
    assert (run / "companies.csv").read_bytes() == original
    again = cr.report(tmp_path, review_as_of=date(2026, 9, 7))
    assert run != again
    assert (run / "companies.csv").read_bytes() == original
    assert (again / "AMD" / "index.html").exists()


def test_html_escapes_untrusted_labels(tmp_path):
    data = {"ticker": "NVDA", "years": [2026], "tables": [{"period_class": "QTD_3M", "scope": {"selection_as_of_date": "2026-09-06"},
            "columns": [], "cells": [], "rows": [{"row_id": "test", "qname": "custom:Unsafe", "label": "<img src=x onerror=alert(1)>",
            "dimensioned": False, "sections": ["IS"], "line_class": "COMPANY_CUSTOM"}]}]}
    cr.render_company(data, tmp_path / "output", date(2026, 9, 7))
    markup = (tmp_path / "output" / "index.html").read_text()
    assert "<img" not in markup
    assert "&lt;img" in markup


def test_refresh_reuses_existing_workflow(tmp_path, monkeypatch):
    cr.register_company(tmp_path, ticker="NVDA", recent_fiscal_years=3)
    calls = []
    for name, result in [("discover_history", tmp_path / "plan"), ("ingest_history", tmp_path / "intake"), ("build_history", tmp_path / "panels")]:
        def operation(_name=name, _result=result, **kwargs):
            calls.append((_name, kwargs))
            return _result
        monkeypatch.setattr(cr.history, name, operation)
    monkeypatch.setattr(cr, "report", lambda root, **kwargs: root / "complete")
    assert cr.refresh(tmp_path, as_of=date(2026, 9, 6), review_as_of=date(2026, 9, 7), workspace=tmp_path / "work", offline=True) == tmp_path / "complete"
    assert [name for name, _ in calls] == ["discover_history", "ingest_history", "build_history"]
    assert calls[0][1]["tickers"] == ("NVDA",)
    assert calls[0][1]["recent_fiscal_years"] == 3
    assert calls[0][1]["offline"] is True


@pytest.mark.skipif(not os.environ.get("SEC_XBRL_REPORT_PUBLICATION"), reason="explicit cached publication required")
def test_actual_cached_three_company_report(tmp_path):
    publication = Path(os.environ["SEC_XBRL_REPORT_PUBLICATION"])
    for ticker in ("NVDA", "AMD", "AAPL"):
        cr.register_company(tmp_path, ticker=ticker, publication=publication)
    run = cr.report(tmp_path, review_as_of=date(2026, 9, 7))
    for ticker, years in [("NVDA", [2024, 2025, 2026]), ("AMD", [2023, 2024, 2025]), ("AAPL", [2023, 2024, 2025])]:
        data = json.loads((run / ticker / "data.json").read_text())
        assert data["years"] == years
        quarter = next(table for table in data["tables"] if table["period_class"] == "QTD_3M")
        assert len(quarter["columns"]) == 12
        assert quarter["cells"]
    old = (run / "NVDA" / "index.html").read_bytes()
    cr.register_company(tmp_path, ticker="NVDA", publication=publication, recent_fiscal_years=2)
    changed = cr.report(tmp_path, review_as_of=date(2026, 9, 7))
    assert json.loads((changed / "NVDA" / "data.json").read_text())["years"] == [2025, 2026]
    assert (run / "NVDA" / "index.html").read_bytes() == old
