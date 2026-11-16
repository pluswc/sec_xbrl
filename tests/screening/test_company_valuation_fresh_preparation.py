from __future__ import annotations

import copy
from pathlib import Path

import polars as pl
import pytest
import test_company_valuation_readiness as reuse_tests
from test_company_valuation_readiness import pin

from sec_xbrl.metrics import company_valuation_readiness as readiness
from sec_xbrl.metrics.market_inputs import pinned_json

evidence = reuse_tests.evidence


@pytest.fixture
def fresh(tmp_path, evidence):
    import hashlib

    filing = {"cik": "0000000001", "accession": "0000000001-26-000002", "form": "10-Q",
              "filed_date": "2026-11-03", "report_date": "2026-10-31", "primary_document": "test.htm"}
    root = pinned_json(evidence["receipt"]["root_snapshot"])
    root["filings"]["recent"] = {"accessionNumber": [filing["accession"], "old"], "form": ["10-Q", "10-K"],
        "filingDate": ["2026-11-03", "2026-10-10"], "reportDate": ["2026-10-31", "2026-09-30"],
        "primaryDocument": ["test.htm", "old.htm"]}
    receipt = evidence["receipt"] | {"root_snapshot": pin(tmp_path / "fresh-root.json", root),
        "latest_financial_filing": filing, "new_unprocessed_filings": [filing], "newer_than_cutoff": [filing],
        "root_recent_min_filed_date": "2026-10-10", "root_recent_max_filed_date": "2026-11-03"}
    evidence["windows"]["records"][0].update(new_count=1, receipt=pin(tmp_path / "fresh-window.json", receipt))
    source = tmp_path / "fresh-intake"
    raw_dir = source / "snapshots" / filing["cik"] / filing["accession"].replace("-", "")
    raw_dir.mkdir(parents=True)
    plan = {"as_of_date": "2026-11-13", "companies": [{"cik": filing["cik"], "ticker": "TEST", "filings": [filing]}]}
    intake_pin = pin(source / "history_intake.json", {"complete": True, "plan": plan, "filings": [
        {"filing": filing, "ticker": "TEST", "status": "INGESTED", "source_run": str(source)}]})
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/index.json"
    raw = filing | {"filing_id": "raw-filing", "document_fiscal_year_focus": "2027", "document_fiscal_period_focus": "Q1",
                    "package_hash": "a" * 64, "source_url": url, "parser_version": "m2-layer1-v7"}
    pl.DataFrame([raw]).write_parquet(raw_dir / "filing.parquet")
    raw_pin = {"path": str(raw_dir / "filing.parquet"), "sha256": hashlib.sha256((raw_dir / "filing.parquet").read_bytes()).hexdigest()}
    raw_manifest_pin = pin(raw_dir / "layer1_manifest.json", {"cik": filing["cik"], "accession": filing["accession"],
        "form": "10-Q", "package_sha256": "a" * 64, "source_url": url, "layer1_parser_version": "m2-layer1-v7"})
    reported_dir, history_dir = tmp_path / "reported", tmp_path / "history"
    reported_dir.mkdir()
    history_dir.mkdir()
    history = {"source_intake": intake_pin["path"], "plan": plan, "comparative_scope": "CURRENT_FOCUS",
               "views": ["AS_FILED", "LATEST_REPORTED"], "input_fingerprint": "fingerprint"}
    reported_pin = pin(reported_dir / "history_manifest.json", history)
    history |= {"supersedes_publication": str(reported_dir), "source_manifest_sha256": reported_pin["sha256"]}
    history_pin = pin(history_dir / "history_manifest.json", history)
    analysis = {"companies": {"TEST": {"as_of": "2026-11-13", "source_publication": str(history_dir),
        "years": [2027], "views": {"AS_FILED": {}, "LATEST_REPORTED": {}}}},
        "quarter_source_evidence": {"included": True, "rule_version": "quarter-typed-primary-pre-evidence-v1"},
        "source_manifest_hashes": {"history_manifest_sha256": history_pin["sha256"]}, "targets": {"TEST": {"status": "READY"}}}
    analysis_pin = pin(tmp_path / "fresh-analysis.json", analysis)
    prepared = {"ticker": "TEST", "cik": filing["cik"], "status": "ANALYTICAL_PREPARED_PRICE_SCOPE_ONLY",
        "as_of": "2026-11-13", "period_mode": "QUARTERLY", "fiscal_year": 2027, "report_date": "2026-10-31",
        "accession": filing["accession"], "history_publication": str(history_dir), "analysis_manifest": analysis_pin,
        "new_filings": 1, "old_history_rebuilt": False, "old_native_qualification_inherited": False}
    prepared_pin = pin(tmp_path / "execution.json", prepared)
    ingest = {"schema_version": "company-valuation-delta-intake-v1", "target_as_of": "2026-11-13", "results": [
        {"cik": filing["cik"], "ticker": "TEST", "complete": True, "returncode": 0, "new_filings": 1,
         "intake_manifest": intake_pin["path"], "outcomes": [{"status": "INGESTED", "error": None, "accession": filing["accession"]}]}]}
    config = {"schema_version": "company-valuation-fresh-config-v1", "common_manifest": evidence["config"]["common_manifest"],
        "discovery_manifest": pin(tmp_path / "fresh-discovery.json", evidence["windows"]),
        "intake_execution_manifest": pin(tmp_path / "intake-execution.json", ingest), "preparations": [
            {"execution": prepared_pin, "intake": intake_pin, "history_manifest": history_pin,
             "raw_manifest": raw_manifest_pin, "raw_filing": raw_pin}]}
    return {"config": config, "prepared": prepared, "analysis": analysis}


def test_new_preparation_exact_source_chain_and_root_acceptance(tmp_path, fresh):
    config_pin = pin(tmp_path / "fresh-config.json", fresh["config"])
    proposal = readiness.propose_fresh(config_pin)
    row, = proposal["companies"]
    assert row["status"] == "PROPOSED_FRESH_PREPARATION"
    assert row["source_selection_as_of"] == row["verified_through"] == "2026-11-13"
    assert row["financial_anchor"] == "2026-11-01" and row["price_plane_only"] is True
    assert row["accounting_binding_approved"] is False
    proposal_pin = pin(tmp_path / "fresh-proposal.json", proposal)
    approval = {"schema_version": "company-valuation-readiness-acceptance-v1", "reviewer": "ROOT",
        "status": "APPROVED_FOR_EXACT_FRESH_PREPARATION", "proposal": proposal_pin, "approved_ciks": ["0000000001"]}
    accepted = readiness.accept_fresh(proposal_pin, pin(tmp_path / "approval.json", approval))
    assert accepted["companies"][0]["status"] == "APPROVED_FOR_EXACT_FRESH_PREPARATION"
    approval["status"] = "APPROVED_FOR_EXACT_REUSE"
    with pytest.raises(ValueError, match="exact ROOT"):
        readiness.accept_fresh(proposal_pin, pin(tmp_path / "wrong-approval.json", approval))


@pytest.mark.parametrize("mutation", ["source-cutoff", "native-inherited", "raw-hash", "history-link", "fiscal-year", "duplicate"])
def test_fresh_qualification_rejects_incompatible_preparation(tmp_path, fresh, mutation):
    item = fresh["config"]["preparations"][0]
    if mutation == "source-cutoff":
        fresh["analysis"]["companies"]["TEST"]["as_of"] = "2026-10-25"
        fresh["prepared"]["analysis_manifest"] = pin(tmp_path / "edited-analysis.json", fresh["analysis"])
    elif mutation == "native-inherited":
        fresh["prepared"]["old_native_qualification_inherited"] = True
    elif mutation == "raw-hash":
        Path(item["raw_filing"]["path"]).write_bytes(b"not the pinned original")
    elif mutation == "history-link":
        history = pinned_json(item["history_manifest"])
        history["source_intake"] = "/other/intake.json"
        item["history_manifest"] = pin(Path(item["history_manifest"]["path"]), history)
    elif mutation == "fiscal-year":
        fresh["prepared"]["fiscal_year"] = 2026
    else:
        fresh["config"]["preparations"].append(item)
    item["execution"] = pin(tmp_path / "edited-execution.json", fresh["prepared"])
    with pytest.raises(ValueError):
        readiness.propose_fresh(pin(tmp_path / "bad-config.json", fresh["config"]))


def test_fresh_typed_current_anchor_uses_new_source_not_global_cutoff(tmp_path, fresh):
    proposal_pin = pin(tmp_path / "proposal.json", readiness.propose_fresh(pin(tmp_path / "config.json", fresh["config"])))
    approval = {"schema_version": "company-valuation-readiness-acceptance-v1", "reviewer": "ROOT",
        "status": "APPROVED_FOR_EXACT_FRESH_PREPARATION", "proposal": proposal_pin, "approved_ciks": ["0000000001"]}
    accepted_pin = pin(tmp_path / "accepted.json", readiness.accept_fresh(proposal_pin, pin(tmp_path / "approval.json", approval)))
    row = {"cik": "0000000001", "observation_id": "new", "known_on": "2026-11-03", "source_refs": [
        {"source": {"analysis_manifest": fresh["prepared"]["analysis_manifest"]}}]}
    bundle = {"company_readiness": accepted_pin, "financial_as_of": "2026-10-25", "observations": [row],
        "financial_anchors": [{"cik": "0000000001", "known_on": "2026-11-03", "period_end": "2026-11-01"}],
        "compatibility_grants": [{"cik": "0000000001", "financial_anchor": "2026-11-01", "input_ids": {"common_shares": "new"}}]}
    assert readiness.validated_company_readiness(bundle)["0000000001"]["source_selection_as_of"] == "2026-11-13"
    assert bundle["financial_as_of"] == "2026-10-25"
    row["source_refs"][0]["source"]["analysis_manifest"] = {"path": "/old/source", "sha256": "old"}
    with pytest.raises(ValueError, match="analysis source"):
        readiness.validated_company_readiness(bundle)
    duplicate_set = pin(tmp_path / "set.json", {"schema_version": "company-valuation-readiness-set-v1",
                                               "readiness_pins": [accepted_pin, accepted_pin]})
    bundle["company_readiness"] = duplicate_set
    with pytest.raises(ValueError, match="duplicate company"):
        readiness.validated_company_readiness(bundle)


@pytest.fixture
def existing_raw(tmp_path, fresh):
    config = copy.deepcopy(fresh["config"])
    item = config["preparations"][0]
    baseline_intake = pinned_json(item["intake"])
    filing = baseline_intake["filings"][0]["filing"]
    common = pinned_json(config["common_manifest"])
    common["financial_as_of"] = "2026-11-04"
    company = common["companies"][0]
    company["intake"] = item["intake"]
    company.pop("annual")
    old_analysis = copy.deepcopy(fresh["analysis"])
    old_analysis["companies"]["TEST"]["as_of"] = "2026-11-04"
    company["quarterly"] = pin(tmp_path / "baseline-analysis.json", old_analysis)
    config["common_manifest"] = pin(tmp_path / "existing-common.json", common)
    discovery = pinned_json(config["discovery_manifest"])
    window = discovery["records"][0]
    receipt = pinned_json(window["receipt"])
    receipt.update(baseline_financial_as_of="2026-11-04", baseline_intake=item["intake"],
                   baseline_latest_filed_date=filing["filed_date"], new_unprocessed_filings=[], newer_than_cutoff=[])
    window.update(new_count=0, receipt=pin(tmp_path / "existing-window.json", receipt))
    config["discovery_manifest"] = pin(tmp_path / "existing-discovery.json", discovery)
    config["assessments"] = pin(tmp_path / "existing-assessment.json", [{"cik": "0000000001", "financial_anchor": {"end": "2026-11-01"}}])
    reused = copy.deepcopy(baseline_intake)
    reused["filings"][0]["status"] = "REUSED"
    item["intake"] = pin(tmp_path / "reused-intake.json", reused)
    history = pinned_json(item["history_manifest"])
    reported = pinned_json({"path": str(Path(history["supersedes_publication"]) / "history_manifest.json"),
                            "sha256": history["source_manifest_sha256"]})
    reported["source_intake"] = item["intake"]["path"]
    reported_dir, history_dir = tmp_path / "existing-reported", tmp_path / "existing-history"
    reported_dir.mkdir()
    history_dir.mkdir()
    reported_pin = pin(reported_dir / "history_manifest.json", reported)
    history.update(source_intake=item["intake"]["path"], supersedes_publication=str(reported_dir), source_manifest_sha256=reported_pin["sha256"])
    item["history_manifest"] = pin(history_dir / "history_manifest.json", history)
    analysis = copy.deepcopy(fresh["analysis"])
    analysis["companies"]["TEST"]["source_publication"] = str(history_dir)
    analysis["source_manifest_hashes"]["history_manifest_sha256"] = item["history_manifest"]["sha256"]
    prepared = copy.deepcopy(fresh["prepared"])
    prepared.update(preparation_kind="EXISTING_RAW_LATEST_ANCHOR", new_filings=0, history_publication=str(history_dir),
                    analysis_manifest=pin(tmp_path / "existing-analysis.json", analysis))
    item["execution"] = pin(tmp_path / "existing-execution.json", prepared)
    execution = {"schema_version": "company-valuation-existing-raw-intake-v1", "target_as_of": "2026-11-13", "results": [
        {"cik": "0000000001", "ticker": "TEST", "complete": True, "returncode": 0, "new_filings": 0,
         "intake_manifest": item["intake"]["path"], "outcomes": [{"status": "REUSED", "error": None, "accession": filing["accession"]}]}]}
    config["intake_execution_manifest"] = pin(tmp_path / "existing-ingest.json", execution)
    config["preparation_kind"] = "EXISTING_RAW_LATEST_ANCHOR"
    return config


def test_existing_raw_latest_anchor_is_explicit_and_preserves_original_source(tmp_path, existing_raw):
    proposal = readiness.propose_fresh(pin(tmp_path / "config.json", existing_raw))
    row, = proposal["companies"]
    assert row["preparation_kind"] == "EXISTING_RAW_LATEST_ANCHOR"
    assert row["source_selection_as_of"] == "2026-11-13"
    assert row["latest_financial_filing"]["filed_date"] == "2026-11-03"
    assert row["accounting_binding_approved"] is False
    del existing_raw["preparation_kind"]
    with pytest.raises(ValueError, match="window differs"):
        readiness.propose_fresh(pin(tmp_path / "no-optin.json", existing_raw))


def test_existing_raw_cannot_substitute_a_different_raw_source_run(tmp_path, existing_raw):
    item = existing_raw["preparations"][0]
    intake = pinned_json(item["intake"])
    intake["filings"][0]["source_run"] = "/different/raw/source"
    item["intake"] = pin(tmp_path / "wrong-intake.json", intake)
    execution = pinned_json(existing_raw["intake_execution_manifest"])
    execution["results"][0]["intake_manifest"] = item["intake"]["path"]
    existing_raw["intake_execution_manifest"] = pin(tmp_path / "wrong-ingest.json", execution)
    with pytest.raises(ValueError, match="existing Raw source/financial anchor"):
        readiness.propose_fresh(pin(tmp_path / "wrong-config.json", existing_raw))
