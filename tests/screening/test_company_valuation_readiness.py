from __future__ import annotations

from types import SimpleNamespace

import pytest

from sec_xbrl.metrics import company_valuation_readiness as readiness
from sec_xbrl.metrics import price_financial_inputs as financial
from sec_xbrl.metrics.market_inputs import encoded, identity, pinned_json


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


@pytest.fixture
def evidence(tmp_path):
    cik, ticker = "0000000001", "TEST"
    filing = {"cik": cik, "accession": "old", "form": "10-K", "filed_date": "2026-10-10", "report_date": "2026-09-30"}
    intake = pin(tmp_path / "intake.json", {"complete": True, "filings": [{"filing": filing}]})
    analysis = pin(tmp_path / "analysis.json", {"companies": {ticker: {"as_of": "2026-10-25"}}})
    root = pin(tmp_path / "root.json", {"cik": 1, "filings": {"recent": {
        "accessionNumber": ["later-8k", "old", "irrelevant-history"],
        "form": ["8-K", "10-K", "10-Q"], "filingDate": ["2026-11-13", "2026-10-10", "2020-01-01"],
        "reportDate": ["2026-11-13", "2026-09-30", "2019-12-31"]}}})
    receipt = {"baseline_financial_as_of": "2026-10-25", "baseline_intake": intake,
               "baseline_latest_filed_date": "2026-10-10", "cik": cik, "ticker": ticker,
               "collected_at": "2026-11-16T03:00:00+00:00", "latest_financial_filing": filing,
               "new_unprocessed_filings": [], "newer_than_cutoff": [],
               "root_recent_min_filed_date": "2020-01-01", "root_recent_max_filed_date": "2026-11-13",
               "root_snapshot": root, "scope": "ROOT_RECENT_WINDOW_ONLY_NOT_FULL_HISTORY_COLLECTION",
               "source_url": "https://data.sec.gov/submissions/CIK0000000001.json",
               "status": "WINDOW_VERIFIED", "target_as_of": "2026-11-13"}
    receipt_pin = pin(tmp_path / "receipt.json", receipt)
    windows = {"schema_version": "company-valuation-discovery-window-v1", "as_of": "2026-11-13", "records": [
        {"cik": cik, "ticker": ticker, "status": "WINDOW_VERIFIED", "receipt": receipt_pin, "new_count": 0},
        {"cik": "0000000002", "ticker": "DELTA", "status": "WINDOW_VERIFIED", "receipt": receipt_pin, "new_count": 1}]}
    common = {"financial_as_of": "2026-10-25", "companies": [
        {"cik": cik, "ticker": ticker, "intake": intake, "annual": analysis},
        {"cik": "0000000002", "ticker": "DELTA"}]}
    assessments = [{"cik": cik, "financial_anchor": {"end": "2026-10-01"}}]
    config = {"schema_version": "company-valuation-reuse-config-v1",
              "common_manifest": pin(tmp_path / "common.json", common),
              "assessments": pin(tmp_path / "assessment.json", assessments),
              "discovery_manifest": pin(tmp_path / "discovery.json", windows)}
    return {"config": config, "receipt": receipt, "windows": windows, "common": common, "assessments": assessments}


def config_pin(tmp_path, evidence):
    return pin(tmp_path / "config.json", evidence["config"])


def test_reuse_preserves_original_selection_and_excludes_delta(tmp_path, evidence):
    proposal = readiness.propose_reuse(config_pin(tmp_path, evidence))
    row, = proposal["companies"]
    assert row["source_selection_as_of"] == "2026-10-25"
    assert row["verified_through"] == "2026-11-13"
    assert row["financial_anchor"] == "2026-10-01"
    assert row["status"] == "PROPOSED_FOR_EXACT_REUSE"
    assert row["accounting_binding_approved"] is False
    assert proposal["excluded_companies"][0]["ticker"] == "DELTA"


@pytest.mark.parametrize("mutation", ["new-filing", "wrong-cik", "short-window", "anchor", "analysis-cutoff", "snapshot-tamper"])
def test_reuse_rejects_false_unchanged_claims(tmp_path, evidence, mutation):
    receipt = evidence["receipt"]
    if mutation in {"new-filing", "wrong-cik", "short-window", "snapshot-tamper"}:
        raw = pinned_json(receipt["root_snapshot"])
        if mutation == "new-filing":
            raw["filings"]["recent"]["form"][0] = "10-Q"
        elif mutation == "wrong-cik":
            raw["cik"] = 999
        elif mutation == "short-window":
            raw["filings"]["recent"]["filingDate"] = ["2026-11-13"] * 3
            receipt["root_recent_min_filed_date"] = "2026-11-13"
        if mutation == "snapshot-tamper":
            from pathlib import Path
            Path(receipt["root_snapshot"]["path"]).write_bytes(b"{}")
        else:
            receipt["root_snapshot"] = pin(tmp_path / "mutated-root.json", raw)
    elif mutation == "anchor":
        evidence["assessments"][0]["financial_anchor"]["end"] = "2026-07-01"
        evidence["config"]["assessments"] = pin(tmp_path / "assessment-new.json", evidence["assessments"])
    else:
        evidence["common"]["companies"][0]["annual"] = pin(tmp_path / "new-analysis.json", {"companies": {"TEST": {"as_of": "2026-11-13"}}})
        evidence["config"]["common_manifest"] = pin(tmp_path / "new-common.json", evidence["common"])
    evidence["windows"]["records"][0]["receipt"] = pin(tmp_path / "mutated-receipt.json", receipt)
    evidence["config"]["discovery_manifest"] = pin(tmp_path / "new-discovery.json", evidence["windows"])
    with pytest.raises(ValueError):
        readiness.propose_reuse(config_pin(tmp_path, evidence))


def test_exact_root_acceptance_cannot_promote_delta_or_edited_scope(tmp_path, evidence):
    proposal = readiness.propose_reuse(config_pin(tmp_path, evidence))
    proposal_pin = pin(tmp_path / "proposal.json", proposal)
    receipt = {"schema_version": "company-valuation-readiness-acceptance-v1", "reviewer": "ROOT",
               "status": "APPROVED_FOR_EXACT_REUSE", "proposal": proposal_pin, "approved_ciks": ["0000000001"]}
    accepted = readiness.accept_reuse(proposal_pin, pin(tmp_path / "root-approval.json", receipt))
    assert accepted["companies"][0]["accounting_binding_approved"] is False
    assert accepted["companies"][0]["status"] == "APPROVED_FOR_EXACT_REUSE"
    receipt["approved_ciks"] = ["0000000002"]
    with pytest.raises(ValueError, match="absent/duplicate"):
        readiness.accept_reuse(proposal_pin, pin(tmp_path / "delta-approval.json", receipt))
    receipt["approved_ciks"] = ["0000000001"]
    proposal["companies"][0]["financial_anchor"] = "2026-12-01"
    changed = pin(tmp_path / "edited-proposal.json", proposal)
    receipt["proposal"] = changed
    with pytest.raises(ValueError, match="differs from verified"):
        readiness.accept_reuse(changed, pin(tmp_path / "edited-approval.json", receipt))


def test_candidate_filters_read_only_selected_trace_shards_and_keep_cutoff(tmp_path, monkeypatch):
    manifest_pin = pin(tmp_path / "analysis.json", {"companies": {"TEST": {"as_of": "2026-10-25"}}})
    nodes = [{"node_id": "n", "kind": "VALUE", "concept": "us-gaap:StockholdersEquity", "dimensions": []}]
    cells = [{"node_id": "n", "cell_id": name, "end": end, "value": "10", "status": "REPORTED",
              "source_fact_id": "fact-" + name} for name, end in [("current", "2026-10-01"), ("old", "2025-10-01")]]
    trace = {"cell_id": "current", "value_lineage": {"source_type": "REPORTED", "filed_date": "2026-10-10",
             "selection_as_of_date": "2026-10-25", "raw_concept_qname": "us-gaap:StockholdersEquity",
             "selected_source_fact_id": "fact-current", "source_filing_id": "filing", "source_snapshot_id": "snapshot",
             "raw_concept_namespace_uri": "us-gaap-uri", "company_canonical_concept_id": "company:0000000001:eq", "value_numeric": "10"}}
    calls = []

    def records(ticker, view, table):
        calls.append(table)
        return nodes if table == "nodes" else cells if table == "cells" else [trace]

    monkeypatch.setattr(financial, "open_analysis", lambda _: SimpleNamespace(_records=records))
    rows = financial.project_additional_candidates(manifest_pin, cik="0000000001", ticker="TEST", cutoff="2026-10-25",
                                                   anchor_end="2026-10-01", cell_ids={"current"})
    assert len(rows) == 1 and rows[0]["status"] == "AVAILABLE_REPORTED"
    assert rows[0]["source"]["value_lineage"]["selection_as_of_date"] == "2026-10-25"
    assert calls == ["nodes", "cells", "trace_" + financial.stable("current")[0]]
    with pytest.raises(ValueError, match="candidate anchor/scope"):
        financial.project_additional_candidates(manifest_pin, cik="0000000001", ticker="TEST", cutoff="2026-10-25",
                                                anchor_end="2026-10-01", cell_ids={"old"})
    with pytest.raises(ValueError, match="selection cutoff"):
        financial.project_additional_candidates(manifest_pin, cik="0000000001", ticker="TEST", cutoff="2026-11-13")


def test_candidate_projection_retains_source_dates_and_rejects_unpinned_table(tmp_path, evidence, monkeypatch):
    shared = [{"cik": "0000000001", "ticker": "TEST", "observation_id": "reported-eps",
               "financial_as_of": "2026-10-25", "end": "2026-10-01", "value": "2",
               "status": "AVAILABLE_REPORTED", "analysis_references": []}]
    shared_pin = pin(tmp_path / "financial.json", shared)
    evidence["common"]["files"] = {"financial_inputs": {"path": "financial.json", "sha256": shared_pin["sha256"]}}
    evidence["config"]["common_manifest"] = pin(tmp_path / "common.json", evidence["common"])
    proposal = readiness.propose_reuse(config_pin(tmp_path, evidence))
    proposal_pin = pin(tmp_path / "proposal.json", proposal)
    calls = []

    def project(source, **kwargs):
        calls.append((source, kwargs))
        return []

    monkeypatch.setattr(readiness, "project_additional_candidates", project)
    config = {"schema_version": "company-valuation-candidate-config-v1", "financial_inputs": shared_pin, "tickers": ["TEST"]}
    result = readiness.project_reuse_candidates(pin(tmp_path / "candidate-config.json", config), proposal_pin)
    assert result["candidates"] == shared
    assert calls[0][1]["cutoff"] == "2026-10-25"
    assert calls[0][1]["anchor_end"] == "2026-10-01"
    assert result["companies"][0]["accounting_binding_approved"] is False
    assert result["companies"][0]["proposed_verified_through"] == "2026-11-13"
    config["financial_inputs"] = pin(tmp_path / "other-financial.json", shared)
    with pytest.raises(ValueError, match="pinned baseline"):
        readiness.project_reuse_candidates(pin(tmp_path / "other-config.json", config), proposal_pin)
    config["financial_inputs"] = shared_pin
    config["tickers"] = ["DELTA"]
    with pytest.raises(ValueError, match="unchanged-source"):
        readiness.project_reuse_candidates(pin(tmp_path / "delta-config.json", config), proposal_pin)
    assert len(calls) == 1


def accepted_readiness(tmp_path, evidence):
    proposal = readiness.propose_reuse(config_pin(tmp_path, evidence))
    proposal_pin = pin(tmp_path / "proposal.json", proposal)
    receipt = {"schema_version": "company-valuation-readiness-acceptance-v1", "reviewer": "ROOT",
               "status": "APPROVED_FOR_EXACT_REUSE", "proposal": proposal_pin, "approved_ciks": ["0000000001"]}
    receipt_pin = pin(tmp_path / "approval.json", receipt)
    return pin(tmp_path / "accepted.json", readiness.accept_reuse(proposal_pin, receipt_pin))


def test_readiness_checks_typed_source_anchor_and_cannot_override_old_bundle(tmp_path, evidence):
    accepted = accepted_readiness(tmp_path, evidence)
    row = {"cik": "0000000001", "known_on": "2026-10-10", "source_refs": [
        {"source": {"analysis_manifest": evidence["common"]["companies"][0]["annual"]}}]}
    bundle = {"financial_as_of": "2026-10-25", "observations": [row], "company_readiness": accepted,
              "financial_anchors": [{"cik": "0000000001", "known_on": "2026-10-10", "period_end": "2026-10-01"}]}
    ready = readiness.validated_company_readiness(bundle)
    assert list(ready) == ["0000000001"]
    assert ready["0000000001"]["verified_through"] == "2026-11-13"
    assert readiness.validated_company_readiness({"financial_as_of": "2026-10-25"}) == {}
    row["source_refs"][0]["source"]["analysis_manifest"] = {"path": "/wrong", "sha256": "wrong"}
    with pytest.raises(ValueError, match="analysis source"):
        readiness.validated_company_readiness(bundle)
    row["source_refs"][0]["source"]["analysis_manifest"] = evidence["common"]["companies"][0]["annual"]
    bundle["financial_anchors"][0]["period_end"] = "2026-07-01"
    with pytest.raises(ValueError, match="financial anchor"):
        readiness.validated_company_readiness(bundle)


def test_publication_uses_company_readiness_without_promoting_other_company(tmp_path, evidence):
    from test_price_metric_publication import publication
    from test_price_related_metrics import prices, sessions

    from sec_xbrl.screening.price_metric_publication import PriceMetricReader, publish_price_metrics
    from sec_xbrl.screening.price_metric_service import PriceMetricService

    accepted = accepted_readiness(tmp_path, evidence)
    original_reader, config, _ = publication(tmp_path, "old")
    journal = tmp_path / "source-context.sqlite"
    saved = PriceMetricService(original_reader, journal).save(kind="RESULT", operation="query", request={"metric_ids": ["per"]}, title="Original")
    calendar = sessions(341)
    calendar["sessions"].append("2026-11-13")
    calendar["coverage_end"] = "2026-11-13"
    assert calendar["sessions"][-1] == "2026-11-13"
    calendar["source_pins"] = pinned_json(config["sessions"])["source_pins"]
    config["sessions"] = pin(tmp_path / "fresh-sessions.json", calendar)
    batch = pinned_json(config["price_batch"])
    batch["prices"] = [{**p, "as_traded_close": "100", "currency": "USD"} for p in prices(calendar)]
    batch["companies"].append({"cik": "0000000002", "ticker": "DELTA", "security_id": "US:DELTA"})
    batch["prices"] += [{**p, "security_id": "US:DELTA"} for p in list(batch["prices"])]
    batch["query"]["end_date"] = "2026-11-13"
    config["price_batch"] = pin(tmp_path / "fresh-batch.json", batch)
    source = pinned_json(config["financial_inputs"])
    analysis_pin = evidence["common"]["companies"][0]["annual"]
    for row in source["observations"]:
        row["source_refs"] = [{"source": {"analysis_manifest": analysis_pin}}]
    source["observations"] += [{**row, "cik": "0000000002", "observation_id": row["observation_id"] + "-2"}
                               for row in list(source["observations"])]
    grant = source["compatibility_grants"][0]
    source["compatibility_grants"].append({**grant, "cik": "0000000002", "security_id": "US:DELTA",
        "input_ids": {k: v + "-2" for k, v in grant["input_ids"].items()}})
    source["financial_anchors"].append({**source["financial_anchors"][0], "cik": "0000000002"})
    source["company_readiness"] = accepted
    config["financial_inputs"] = pin(tmp_path / "fresh-financial.json", source)
    config["price_as_of"] = "2026-11-13"
    result = publish_price_metrics(pin(tmp_path / "fresh-config.json", config), tmp_path / "fresh-publication")
    reader = PriceMetricReader({k: result[k] for k in ("path", "sha256")})
    query = reader.query(metric_ids=["per"])
    rows = {r["cik"]: r for r in query["rows"]}
    assert rows["0000000001"]["value"] == "50"
    assert rows["0000000002"]["reason"] == "FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF"
    assert source["financial_as_of"] == config["dataset_scope"]["financial_as_of"] == "2026-10-25"
    assert set(query["company_financial_readiness"]) == {"0000000001"}
    capability = PriceMetricService(reader, tmp_path / "fresh-journal.sqlite").capability()
    assert capability["company_financial_readiness"]["0000000001"]["verified_through"] == "2026-11-13"
    reopened = PriceMetricService(reader, journal).reopen(saved["id"])
    assert reopened["result"] == saved["result"]
    assert "source_context" not in reopened
    assert "dataset_scope" not in reopened["result"]
