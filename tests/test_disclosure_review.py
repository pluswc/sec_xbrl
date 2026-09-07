from __future__ import annotations

import copy
import hashlib
import json
import zipfile

import pytest

from sec_xbrl import history
from sec_xbrl.longitudinal import disclosure_review as review


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    source = tmp_path / "source.htm"
    source.write_text("<root/>")
    evidence = {"source_file": str(source), "source_file_sha256": review.document(source)[1],
                "inline_fact_id": "inline", "validation": "RAW_FACT_BOUND", "display_label": "Division",
                "decimals": "-6"}
    concepts = {"axis": {"qname": "x:Axis"}, "member": {"qname": "x:Wrong"}}
    facts = {}
    candidates = []
    tables = []
    for period, quarter, end, value in (("FY", None, "2024-01-01", "100000000"),
                                        ("YTD_9M", 3, "2023-10-01", "75000000"),
                                        ("QTD_3M", 4, "2024-01-01", None)):
        column = {"fiscal_time_series_column_id": period + "-col", "period_class": period,
                  "fiscal_year": 2023, "fiscal_quarter": quarter, "fiscal_label": period}
        row = {"fiscal_time_series_row_id": "row", "raw_concept_qname": "x:Revenue"}
        lineage = {"accession": period + "-acc", "source_snapshot_id": "snapshot", "source_filing_id": "filing",
                   "selected_source_fact_id": period + "-fact", "raw_concept_id": "concept", "context_id": period + "-ctx",
                   "unit_id": "unit", "raw_dimension_signature": [["axis", "member", None, "EXPLICIT", "false"]],
                   "canonical_dimension_signature": [["canonical-axis", "canonical-member", None, "EXPLICIT", "false"]],
                   "context_start_date": "2023-01-01", "context_end_date": end, "context_instant_date": None,
                   "unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": "[]",
                   "value_numeric": value, "raw_concept_qname": "x:Revenue", "raw_concept_data_type": "xbrli:monetaryItemType",
                   "raw_concept_period_type": "duration", "company_canonical_concept_id": "company:concept",
                   "raw_concept_is_standard": False, "filed_date": "2024-02-01"}
        cell = {"fiscal_time_series_cell_id": period + "-cell", "fiscal_time_series_row_id": "row",
                "fiscal_time_series_column_id": period + "-col", "value_status": "REPORTED", "value_numeric": value,
                "value_text": None, "value_lineage": lineage, "binding": {}}
        if value is not None:
            facts[period + "-fact"] = {"source_document": "source.htm"}
            candidates.append(review.interpretation_candidate(ticker="TEST", view="AS_FILED", cell=cell, row=row,
                              column=column, evidence=evidence, target_dimensions=[["analysis:Axis", "Division", None, "EXPLICIT", "false"]],
                              basis_version="basis-v1", corroboration="explicit table and adjacent comparative",
                              resolved_issue_ids=["tag-issue"]))
        for view in ("AS_FILED", "LATEST_REPORTED"):
            files = {}
            for name, records in (("columns", [column]), ("rows", [row]), ("cells", [cell] if value else [])):
                relative = f"{period}-{view}-{name}.parquet"
                files[name] = {"path": relative, **history._write_records(parent / relative, tuple(records))}
            tables.append({"ticker": "TEST", "period_class": period, "view": view, "files": files, "scope": {}})
    (parent / "history_manifest.json").write_text(json.dumps({"version": history.HISTORY_VERSION, "tables": tables}))
    monkeypatch.setattr(review, "raw_index", lambda *args: (concepts, facts))
    monkeypatch.setattr(review, "source_evidence", lambda **kwargs: evidence)
    candidates.append(review.q4_candidate(annual=candidates[0], ytd=candidates[1], evidence="additive compatible revenue"))
    decisions = [{"decision_id": f"decision-{i}", "previous_decision_id": "", "candidate_id": c["candidate_id"],
                  "action": "APPROVE", "reviewer": "reviewer", "reason": "source table", "known_at": "2026-09-07T10:00:00+09:00"}
                 for i, c in enumerate(candidates)]
    return parent, candidates, decisions


def publish(corpus, destination, **kwargs):
    parent, candidates, decisions = corpus
    return review.publish_review(parent=parent, destination=destination, candidates=candidates,
                                 decisions=decisions, review_as_of=review.timestamp("2026-09-07T11:00:00+09:00"), **kwargs)


def test_persisted_planes_and_shared_reader(corpus, tmp_path):
    root = publish(corpus, tmp_path / "published")
    reader = history.open_history_publication(root)
    assert len(reader.records("analytical")) == 2
    assert reader.records("derived")[0]["cell"]["value_numeric"] == "25000000"
    assert reader.load(ticker="TEST").cells[0]["value_status"] == "DERIVED"
    assert reader.load(ticker="TEST", view="AS_FILED").cells == ()
    assert reader.load(ticker="TEST", period_class="FY").cells[0]["value_numeric"] == "100000000"
    assert len(reader.records("candidates")) == 3
    with pytest.raises(ValueError, match="already exists"):
        publish(corpus, root)


@pytest.mark.parametrize("withdrawn", [0, 2])
def test_a_and_b_independent_withdrawal(corpus, tmp_path, withdrawn):
    corpus[2][withdrawn]["action"] = "MORE_EVIDENCE"
    root = publish(corpus, tmp_path / "p")
    reader = review.ReviewedPublicationReader(root)
    assert not reader.records("derived")
    assert reader.records("review_queue")


def test_same_day_historical_chain(corpus):
    _, candidates, decisions = corpus
    active = review.effective_decisions(decisions, candidates, as_of=review.timestamp("2026-09-07T09:59:59+09:00"))
    assert active == {}
    original = decisions[0]
    withdraw = dict(original, decision_id="withdraw", previous_decision_id=original["decision_id"],
                    action="WITHDRAW", known_at="2026-09-07T10:01:00+09:00")
    assert review.effective_decisions([*decisions, withdraw], candidates, as_of=review.timestamp("2026-09-07T10:02:00+09:00"))[original["candidate_id"]]["action"] == "WITHDRAW"
    with pytest.raises(ValueError, match="conflict"):
        review.effective_decisions([*decisions, dict(withdraw, known_at=original["known_at"])], candidates, as_of=review.timestamp("2026-09-08T00:00:00+09:00"))
    with pytest.raises(ValueError, match="cannot be changed"):
        review.effective_decisions(decisions[1:], candidates, as_of=review.timestamp("2026-09-08T00:00:00+09:00"), previous=decisions)


def test_source_candidate_stale_period(corpus, tmp_path):
    corpus[1][0]["fiscal_year"] = 2022
    old = corpus[1][0]["candidate_id"]
    corpus[1][0]["candidate_id"] = review.identity({k: v for k, v in corpus[1][0].items() if k != "candidate_id"})
    corpus[2][0]["candidate_id"] = corpus[1][0]["candidate_id"]
    # Remove B here to isolate the source period-binding failure.
    corpus[1].pop()
    corpus[2].pop()
    with pytest.raises(ValueError, match="period/row"):
        publish(corpus, tmp_path / "p")
    assert old != corpus[1][0]["candidate_id"]


@pytest.mark.parametrize("field,value", [
    ("unit_denominator_measures", '["xbrli:shares"]'),
    ("unit_numerator_measures", '["xbrli:shares"]'),
    ("raw_concept_qname", "us-gaap:EarningsPerShareBasic"),
    ("raw_concept_period_type", "instant"),
    ("context_end_date", "2023-05-01"),
    ("ledger_lineage", {"ledger_is_amendment": True}),
])
def test_q4_fail_closed_for_incompatible_inputs(corpus, field, value):
    parent, candidates, _ = corpus
    reader = history.HistoryPublicationReader(parent)
    annual = copy.deepcopy(reader.load(ticker="TEST", period_class="FY").cells[0])
    ytd = copy.deepcopy(reader.load(ticker="TEST", period_class="YTD_9M").cells[0])
    annual["value_lineage"][field] = value
    assert review._q4_gate(annual, ytd, {c["candidate_id"]: c for c in candidates}, candidates[-1])


def test_53_week_and_extra_axis(corpus):
    parent, candidates, _ = corpus
    reader = history.HistoryPublicationReader(parent)
    annual = copy.deepcopy(reader.load(ticker="TEST", period_class="FY").cells[0])
    ytd = reader.load(ticker="TEST", period_class="YTD_9M").cells[0]
    annual["value_lineage"]["context_end_date"] = "2024-01-08"
    index = {c["candidate_id"]: c for c in candidates}
    assert review._q4_gate(annual, ytd, index, candidates[-1]) is None
    candidates[1]["target_dimensions"].append(["other", "member", None, "EXPLICIT", "false"])
    assert review._q4_gate(annual, ytd, index, candidates[-1]) == "Q4_INCOMPATIBLE_REVIEWED_SCOPE"


def test_unrelated_quality_block_survives_a_and_blocks_b(corpus, tmp_path):
    quality = [{"decision_id": "q1", "issue_id": "unrelated", "ticker": "TEST", "accession": "YTD_9M-acc",
                "concept": "x:Revenue", "axis": "x:Axis", "member": "x:Wrong", "decision": "BLOCK",
                "known_at": "2026-09-07T09:00:00+09:00"}]
    root = publish(corpus, tmp_path / "p", quality_decisions=quality)
    reader = review.ReviewedPublicationReader(root)
    assert not reader.records("derived")
    assert reader.load(ticker="TEST", period_class="YTD_9M").cells[0]["value_numeric"] is None
    assert reader.records("review_queue")[0]["reason"] == "Q4_INPUT_QUALITY_BLOCKED"


def test_duplicate_b_candidates_all_excluded(corpus, tmp_path):
    b = dict(corpus[1][-1], evidence="second ambiguous approval")
    b["candidate_id"] = review.identity({k: v for k, v in b.items() if k != "candidate_id"})
    corpus[1].append(b)
    corpus[2].append(dict(corpus[2][-1], candidate_id=b["candidate_id"], decision_id="other-b"))
    reader = review.ReviewedPublicationReader(publish(corpus, tmp_path / "p"))
    assert not reader.records("derived")
    assert all(r["reason"] == "Q4_AMBIGUOUS_COMPATIBLE_INPUT_PAIR" for r in reader.records("review_queue"))


def test_publication_decision_history_immutable(corpus, tmp_path):
    first = publish(corpus, tmp_path / "p1")
    corpus[2][0]["reason"] = "changed"
    with pytest.raises(ValueError, match="cannot be changed"):
        publish(corpus, tmp_path / "p2", previous_publication=first)


def test_source_evidence_bound_to_original_package(tmp_path):
    document = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:x="urn:context">
    <x:context id="ctx"><x:period><x:startDate>2023-01-01</x:startDate><x:endDate>2023-03-31</x:endDate></x:period><x:explicitMember dimension="x:Axis">x:Wrong</x:explicitMember></x:context>
    <x:unit id="usd"><x:measure>iso4217:USD</x:measure></x:unit>
    <table><tr><td>Division</td><td><ix:nonFraction id="fact" name="x:Revenue" contextRef="ctx" unitRef="usd" scale="6">25</ix:nonFraction></td></tr></table></html>'''
    path = tmp_path / "source.htm"
    path.write_text(document)
    package = tmp_path / "filing.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("source.htm", document)
    lineage = {"source_filing_id": "filing", "raw_concept_qname": "x:Revenue", "raw_concept_id": "concept", "value_numeric": "25000000",
                   "raw_dimension_signature": [["axis", "member", None, "EXPLICIT", "false"]],
                   "context_start_date": "2023-01-01", "context_end_date": "2023-04-01",
                   "unit_numerator_measures": '["iso4217:USD"]', "unit_denominator_measures": "[]"}
    raw = {"source_document": "source.htm", "source_package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
               "context_id": review._stable_id("context", "filing", "ctx"), "raw_concept_id": "concept", "value_numeric": "25000000", "decimals": "-6"}
    concepts = {"axis": {"qname": "x:Axis"}, "member": {"qname": "x:Wrong"}}
    args = {"file": path, "inline_fact_id": "fact", "lineage": lineage, "raw_fact": raw, "concepts": concepts, "package_zip": package}
    evidence = review.source_evidence(**args)
    assert evidence["display_label"] == "Division"
    path.write_text(document.replace("Division", "Forged division"))
    with pytest.raises(ValueError, match="original Layer1 package"):
        review.source_evidence(**args)


def test_quality_time_ties_and_scope_changes():
    row = {"decision_id": "q1", "issue_id": "issue", "ticker": "T", "accession": "a", "concept": "c", "axis": "", "member": "",
               "decision": "BLOCK", "known_at": "2026-09-07T09:00:00+09:00"}
    with pytest.raises(ValueError, match="identity/time"):
        review.effective_quality([row, dict(row, decision_id="q2")], review.timestamp("2026-09-07T10:00:00+09:00"))
    with pytest.raises(ValueError, match="scope changed"):
        review.effective_quality([row, dict(row, decision_id="q2", concept="different", known_at="2026-09-07T09:01:00+09:00")], review.timestamp("2026-09-07T10:00:00+09:00"))


def test_report_rejects_future_interpretation_publication(corpus, tmp_path):
    from sec_xbrl.company_reports import _company_data
    root = publish(corpus, tmp_path / "p")
    with pytest.raises(ValueError, match="newer than requested"):
        _company_data({"ticker": "TEST", "publication": str(root)}, [], review_as_of=review.date(2026, 9, 6))


@pytest.mark.parametrize("approve_direct,amount,expected", [
    (False, "25000000", "DIRECT_Q4_INTERPRETATION_REQUIRED"),
    (True, "25000000", "DIRECT_Q4_CONFIRMED"),
    (True, "40000000", "DIRECT_Q4_CONFLICT"),
])
def test_direct_q4_preferred_and_conflict_visible(corpus, tmp_path, approve_direct, amount, expected):
    parent, candidates, decisions = corpus
    reader = history.HistoryPublicationReader(parent)
    direct = copy.deepcopy(reader.load(ticker="TEST", period_class="FY").cells[0])
    direct.update(fiscal_time_series_cell_id="direct-q4", fiscal_time_series_column_id="QTD_3M-col", value_numeric=amount)
    direct["value_lineage"].update(selected_source_fact_id="direct-fact", value_numeric=amount, context_start_date="2023-10-01")
    manifest = json.loads((parent / "history_manifest.json").read_text())
    for table in manifest["tables"]:
        if table["period_class"] == "QTD_3M":
            relative = table["files"]["cells"]["path"]
            table["files"]["cells"] = {"path": relative, **history._write_records(parent / relative, (direct,))}
    (parent / "history_manifest.json").write_text(json.dumps(manifest))
    review.raw_index(reader, "TEST")[1]["direct-fact"] = {"source_document": "source.htm"}
    if approve_direct:
        panel = history.HistoryPublicationReader(parent).load(ticker="TEST")
        a = review.interpretation_candidate(ticker="TEST", view="AS_FILED", cell=direct, row=panel.rows[0], column=panel.columns[0],
                                           evidence=candidates[0]["evidence"], target_dimensions=candidates[0]["target_dimensions"],
                                           basis_version=candidates[0]["basis_version"], corroboration="direct Q4 table")
        candidates.append(a)
        decisions.append(dict(decisions[0], decision_id="direct-decision", candidate_id=a["candidate_id"]))
    published = review.ReviewedPublicationReader(publish(corpus, tmp_path / "p"))
    assert not published.records("derived")
    assert published.records("review_queue")[-1]["reason"] == expected
    if expected == "DIRECT_Q4_CONFLICT":
        assert published.load(ticker="TEST").cells[0]["resolution_reason"] == expected
