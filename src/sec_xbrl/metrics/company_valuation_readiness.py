"""Evidence-bound reuse of a financial selection through a later discovery window.

No filing selection, accounting approval or market-data capture occurs here.
The original selection cutoff/IDs remain intact. A ROOT receipt can approve
only an exact pinned reuse proposal; it cannot approve class/equity/EPS meaning.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from sec_xbrl.metrics.market_inputs import finite, identity, pinned_json, project_financial_inputs
from sec_xbrl.metrics.price_financial_inputs import (
    check_actual_share_sources,
    project_additional_candidates,
)
from sec_xbrl.metrics.price_related import ROLE_UNITS

FINANCIAL_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def _unique(rows: list[dict], field: str) -> dict:
    result = {r[field]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate company identity")
    return result


def _filing_key(filing: dict) -> tuple:
    return tuple(filing.get(k) for k in ("accession", "form", "filed_date", "report_date"))


def _verify_window(company: dict, assessment: dict, receipt: dict, baseline: str, target: str) -> dict:
    """Validate one existing-source/no-new-filing window against the raw root JSON."""
    cik, ticker = company["cik"], company["ticker"]
    if (receipt.get("cik") != cik or receipt.get("ticker") != ticker
        or receipt.get("status") != "WINDOW_VERIFIED"
        or receipt.get("baseline_financial_as_of") != baseline
        or receipt.get("target_as_of") != target
        or receipt.get("baseline_intake") != company["intake"]
        or receipt.get("scope") != "ROOT_RECENT_WINDOW_ONLY_NOT_FULL_HISTORY_COLLECTION"
        or receipt.get("source_url") != f"https://data.sec.gov/submissions/CIK{cik}.json"
        or receipt.get("new_unprocessed_filings") != [] or receipt.get("newer_than_cutoff") != []):
        raise ValueError("discovery receipt does not authorize unchanged source reuse")
    if date.fromisoformat(receipt["collected_at"][:10]) < date.fromisoformat(target):
        raise ValueError("discovery capture precedes verified-through date")
    intake = pinned_json(company["intake"])
    if intake.get("complete") is not True:
        raise ValueError("baseline intake is incomplete")
    filings = [item.get("filing", item) for item in intake["filings"]]
    filings = [f for f in filings if f.get("form") in FINANCIAL_FORMS and f.get("filed_date", "") <= baseline]
    if not filings or any(f.get("cik") != cik or not f.get("report_date") or not f.get("filed_date") for f in filings):
        raise ValueError("baseline financial filing identity missing")
    latest = max(filings, key=lambda f: (f["report_date"], f["filed_date"], f["accession"]))
    anchor = (date.fromisoformat(latest["report_date"]) + timedelta(days=1)).isoformat()
    if assessment.get("cik") != cik or assessment["financial_anchor"]["end"] != anchor:
        raise ValueError("baseline financial anchor differs from assessment")
    if (receipt.get("baseline_latest_filed_date") != max(f["filed_date"] for f in filings)
        or _filing_key(receipt.get("latest_financial_filing", {})) != _filing_key(latest)):
        raise ValueError("discovery latest financial filing differs from baseline")
    root = pinned_json(receipt["root_snapshot"])
    if str(root.get("cik", "")).zfill(10) != cik:
        raise ValueError("discovery root CIK differs")
    recent = root["filings"]["recent"]
    columns = [recent[k] for k in ("accessionNumber", "form", "filingDate", "reportDate")]
    if not columns[0] or len({len(c) for c in columns}) != 1:
        raise ValueError("discovery recent columns are incomplete")
    if (min(recent["filingDate"]) > baseline
        or receipt.get("root_recent_min_filed_date") != min(recent["filingDate"])
        or receipt.get("root_recent_max_filed_date") != max(recent["filingDate"])):
        raise ValueError("discovery recent window does not cover baseline")
    recent_filings = [dict(zip(("accession", "form", "filed_date", "report_date"), values, strict=True))
                      for values in zip(*columns, strict=True)
                      if values[1] in FINANCIAL_FORMS and values[2] <= target]
    baseline_keys = {_filing_key(f) for f in filings}
    if (any(f["filed_date"] > baseline for f in recent_filings)
        or any(_filing_key(f) not in baseline_keys for f in recent_filings
               if f["filed_date"] >= latest["filed_date"])
        or _filing_key(latest) not in {_filing_key(f) for f in recent_filings}):
        raise ValueError("discovery window contains an unprepared or changed financial filing")
    analysis_pins = {}
    for mode in ("annual", "quarterly"):
        if company.get(mode):
            manifest = pinned_json(company[mode])
            if manifest["companies"][ticker]["as_of"] != baseline:
                raise ValueError("baseline analysis selection cutoff differs")
            analysis_pins[mode] = company[mode]
    if not analysis_pins:
        raise ValueError("baseline selected analysis is absent")
    return {"cik": cik, "ticker": ticker, "source_selection_as_of": baseline,
            "verified_through": target, "financial_anchor": anchor,
            "latest_financial_filing": latest, "intake": company["intake"],
            "analysis_pins": analysis_pins, "discovery_root": receipt["root_snapshot"],
            "status": "PROPOSED_FOR_EXACT_REUSE", "accounting_binding_approved": False}


def propose_reuse(config_pin: dict) -> dict:
    """Return a create-only-ready proposal; no readiness is approved by this call.

    Each requested company must have a complete unchanged discovery window.
    New-filing companies are explicitly excluded, never promoted by a global date.
    All source pins are verified before deriving the exact proposal identity.
    """
    config = pinned_json(config_pin)
    if config.get("schema_version") != "company-valuation-reuse-config-v1":
        raise ValueError("unsupported reuse configuration")
    common = pinned_json(config["common_manifest"])
    assessments = _unique(pinned_json(config["assessments"]), "cik")
    discovery = pinned_json(config["discovery_manifest"])
    baseline, target = common["financial_as_of"], discovery["as_of"]
    if (discovery.get("schema_version") != "company-valuation-discovery-window-v1"
        or date.fromisoformat(target) < date.fromisoformat(baseline)):
        raise ValueError("invalid discovery window")
    companies = _unique(common["companies"], "cik")
    windows = _unique(discovery["records"], "cik")
    if companies.keys() != windows.keys():
        raise ValueError("discovery company universe differs from pinned baseline")
    output, excluded = [], []
    for cik in sorted(companies):
        company, window = companies[cik], windows[cik]
        if window.get("ticker") != company["ticker"] or window.get("status") != "WINDOW_VERIFIED":
            raise ValueError("discovery company identity/status differs")
        if window.get("new_count") != 0:
            excluded.append({"cik": cik, "ticker": company["ticker"], "reason": "NEW_FINANCIAL_FILING_REQUIRES_PREPARATION",
                             "discovery_receipt": window["receipt"]})
            continue
        row = _verify_window(company, assessments[cik], pinned_json(window["receipt"]), baseline, target)
        row["discovery_receipt"] = window["receipt"]
        row["readiness_id"] = "company-reuse-" + identity(row)
        output.append(row)
    return {"schema_version": "company-valuation-reuse-proposal-v1", "status": "PROPOSAL_NOT_APPROVED",
            "source_selection_as_of": baseline, "verified_through": target,
            "source_pins": {"config": config_pin, "common_manifest": config["common_manifest"],
                            "assessments": config["assessments"], "discovery_manifest": config["discovery_manifest"]},
            "companies": output, "excluded_companies": excluded}


def accept_reuse(proposal_pin: dict, receipt_pin: dict) -> dict:
    """Validate exact ROOT reuse acceptance, independently of accounting grants."""
    proposal, receipt = pinned_json(proposal_pin), pinned_json(receipt_pin)
    if (proposal.get("schema_version") != "company-valuation-reuse-proposal-v1"
        or receipt.get("schema_version") != "company-valuation-readiness-acceptance-v1"
        or receipt.get("reviewer") != "ROOT" or receipt.get("status") != "APPROVED_FOR_EXACT_REUSE"
        or receipt.get("proposal") != proposal_pin):
        raise ValueError("reuse requires exact ROOT acceptance")
    # Rebuild from the pinned original inputs, rejecting edited proposal fields.
    if propose_reuse(proposal["source_pins"]["config"]) != proposal:
        raise ValueError("reuse proposal differs from verified source evidence")
    companies = _unique(proposal["companies"], "cik")
    approved = receipt.get("approved_ciks", [])
    if not approved or len(approved) != len(set(approved)) or any(cik not in companies for cik in approved):
        raise ValueError("reuse approval includes absent/duplicate company")
    return {"schema_version": "company-valuation-readiness-v1", "source_pins": {"proposal": proposal_pin, "approval": receipt_pin},
            "companies": [{**companies[cik], "status": "APPROVED_FOR_EXACT_REUSE",
                           "reuse_evidence_pins": [proposal_pin, receipt_pin]} for cik in sorted(approved)]}


def _raw_filing(pin: dict) -> dict:
    path = Path(pin["path"])
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != pin.get("sha256")):
        raise ValueError("raw filing table pin differs")
    records = pl.read_parquet(path).to_dicts()
    if len(records) != 1:
        raise ValueError("fresh preparation requires one exact raw filing")
    return records[0]


def propose_fresh(config_pin: dict) -> dict:
    """Qualify declared newly prepared single-filing sources for the price plane.

    Reads small manifests, the discovery root and one pinned Raw filing metadata
    table per issuer. It neither audits all Raw facts nor inherits native approval.
    Partial preparation cohorts are explicit, never a readiness claim for all65.
    """
    config = pinned_json(config_pin)
    if config.get("schema_version") != "company-valuation-fresh-config-v1":
        raise ValueError("unsupported fresh preparation configuration")
    common = pinned_json(config["common_manifest"])
    discovery = pinned_json(config["discovery_manifest"])
    execution = pinned_json(config["intake_execution_manifest"])
    existing_raw = config.get("preparation_kind") == "EXISTING_RAW_LATEST_ANCHOR"
    if config.get("preparation_kind") not in {None, "NEW_DISCOVERED_FILING", "EXISTING_RAW_LATEST_ANCHOR"}:
        raise ValueError("unsupported explicit preparation kind")
    baseline, target = common["financial_as_of"], discovery["as_of"]
    if (discovery.get("schema_version") != "company-valuation-discovery-window-v1"
        or execution.get("schema_version") != ("company-valuation-existing-raw-intake-v1" if existing_raw else "company-valuation-delta-intake-v1")
        or execution.get("target_as_of") != target or target < baseline):
        raise ValueError("fresh discovery/intake window differs")
    registered = _unique(common["companies"], "cik")
    assessments = _unique(pinned_json(config["assessments"]), "cik") if existing_raw else None
    windows = _unique(discovery["records"], "cik")
    ingested = _unique(execution["results"], "cik")
    prepared_execution = None
    if config.get("preparation_execution_manifest"):
        aggregate = pinned_json(config["preparation_execution_manifest"])
        if aggregate.get("schema_version") != "company-valuation-delta-analytical-v1" or aggregate.get("as_of") != target:
            raise ValueError("prepared execution manifest differs from target")
        prepared_execution = _unique(aggregate["results"], "cik")
        if prepared_execution.keys() != ingested.keys():
            raise ValueError("prepared execution manifest omits an ingested company")
    preparations = config["preparations"]
    if not preparations:
        raise ValueError("fresh preparation cohort is empty")
    output = []
    for item in preparations:
        prepared = pinned_json(item["execution"])
        cik, ticker = prepared["cik"], prepared["ticker"]
        if prepared_execution is not None and prepared_execution[cik] != {**prepared, "returncode": 0}:
            raise ValueError("prepared execution record differs from exact company execution")
        company, window, ingest = registered[cik], windows[cik], ingested[cik]
        receipt = pinned_json(window["receipt"])
        if (company["ticker"] != ticker or window["ticker"] != ticker or ingest["ticker"] != ticker
            or window.get("status") != "WINDOW_VERIFIED" or window.get("new_count") != (0 if existing_raw else 1)
            or receipt.get("cik") != cik or receipt.get("ticker") != ticker
            or receipt.get("baseline_intake") != company["intake"]
            or receipt.get("baseline_financial_as_of") != baseline or receipt.get("target_as_of") != target
            or receipt.get("status") != "WINDOW_VERIFIED"
            or receipt.get("source_url") != f"https://data.sec.gov/submissions/CIK{cik}.json"
            or receipt.get("scope") != "ROOT_RECENT_WINDOW_ONLY_NOT_FULL_HISTORY_COLLECTION"
            or date.fromisoformat(receipt["collected_at"][:10]) < date.fromisoformat(target)):
            raise ValueError("fresh source differs from registered discovery window")
        baseline_intake = pinned_json(company["intake"])
        if baseline_intake.get("complete") is not True:
            raise ValueError("fresh source baseline intake is incomplete")
        new_filings = receipt.get("new_unprocessed_filings")
        if existing_raw:
            _verify_window(company, assessments[cik], receipt, baseline, target)
            filing = receipt["latest_financial_filing"]
        else:
            if len(new_filings or []) != 1 or receipt.get("newer_than_cutoff") != new_filings:
                raise ValueError("fresh source requires one exact new discovery filing")
            filing = new_filings[0]
        filed = filing.get("filed_date", "")
        filed_in_scope = bool(filed) and (filed <= baseline if existing_raw else baseline < filed <= target)
        if (filing.get("cik") != cik or filing.get("form") not in FINANCIAL_FORMS
            or not filed_in_scope
            or _filing_key(receipt.get("latest_financial_filing", {})) != _filing_key(filing)):
            raise ValueError("fresh latest financial filing identity differs")
        root = pinned_json(receipt["root_snapshot"])
        recent = root["filings"]["recent"]
        columns = [recent[k] for k in ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")]
        if (str(root.get("cik", "")).zfill(10) != cik or not columns[0]
            or len({len(c) for c in columns}) != 1 or min(recent["filingDate"]) > baseline
            or receipt.get("root_recent_min_filed_date") != min(recent["filingDate"])
            or receipt.get("root_recent_max_filed_date") != max(recent["filingDate"])):
            raise ValueError("fresh discovery root identity/window differs")
        newer = [values for values in zip(*columns, strict=True)
                 if values[1] in FINANCIAL_FORMS and baseline < values[2] <= target]
        expected = tuple(filing.get(k) for k in ("accession", "form", "filed_date", "report_date", "primary_document"))
        if newer != ([] if existing_raw else [expected]):
            raise ValueError("fresh intake omits or changes a new financial filing")
        intake = pinned_json(item["intake"])
        intake_status, new_count = ("REUSED", 0) if existing_raw else ("INGESTED", 1)
        if (not ingest.get("complete") or ingest.get("returncode") != 0 or ingest.get("new_filings") != new_count
            or ingest.get("intake_manifest") != item["intake"]["path"]
            or ingest.get("outcomes") != [{"status": intake_status, "error": None, "accession": filing["accession"]}]
            or intake.get("complete") is not True or len(intake.get("filings", [])) != 1):
            raise ValueError("fresh intake is not completely ingested")
        entry = intake["filings"][0]
        plan = intake["plan"]
        if (entry.get("filing") != filing or entry.get("ticker") != ticker or entry.get("status") != intake_status
            or plan.get("as_of_date") != target or len(plan.get("companies", [])) != 1
            or plan["companies"][0].get("cik") != cik or plan["companies"][0].get("ticker") != ticker
            or plan["companies"][0].get("filings") != [filing]):
            raise ValueError("fresh intake plan differs from exact discovery filing")
        if existing_raw:
            baseline_entries = [r for r in baseline_intake["filings"] if r.get("filing") == filing]
            if (len(baseline_entries) != 1 or entry.get("source_run") != baseline_entries[0].get("source_run")
                or assessments[cik]["financial_anchor"]["end"] != (date.fromisoformat(filing["report_date"]) + timedelta(days=1)).isoformat()):
                raise ValueError("existing Raw source/financial anchor differs from exact baseline entry")
        raw_directory = Path(entry["source_run"]) / "snapshots" / cik / filing["accession"].replace("-", "")
        if (item["raw_manifest"]["path"] != str(raw_directory / "layer1_manifest.json")
            or item["raw_filing"]["path"] != str(raw_directory / "filing.parquet")):
            raise ValueError("fresh raw source locator differs from intake")
        raw_manifest, raw = pinned_json(item["raw_manifest"]), _raw_filing(item["raw_filing"])
        if (any(raw.get(k) != filing.get(k) for k in ("cik", "accession", "form", "filed_date", "report_date", "primary_document"))
            or any(raw_manifest.get(k) != filing.get(k) for k in ("cik", "accession", "form"))
            or not raw.get("filing_id") or not raw_manifest.get("package_sha256")
            or raw.get("package_hash") != raw_manifest["package_sha256"]
            or raw.get("parser_version") != raw_manifest.get("layer1_parser_version")
            or raw.get("source_url") != raw_manifest.get("source_url")):
            raise ValueError("fresh raw filing metadata differs from discovered source")
        expected_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{filing['accession'].replace('-', '')}/index.json"
        if raw.get("source_url") != expected_url:
            raise ValueError("fresh raw source URL differs")
        annual = filing["form"] in {"10-K", "10-K/A"}
        mode = "annual" if annual else "quarterly"
        if (prepared.get("status") != "ANALYTICAL_PREPARED_PRICE_SCOPE_ONLY" or prepared.get("as_of") != target
            or prepared.get("new_filings") != new_count or prepared.get("old_history_rebuilt") is not False
            or prepared.get("old_native_qualification_inherited") is not False
            or prepared.get("period_mode") != mode.upper() or prepared.get("accession") != filing["accession"]
            or prepared.get("report_date") != filing["report_date"]
            or str(prepared.get("fiscal_year")) != raw.get("document_fiscal_year_focus")
            or (raw.get("document_fiscal_period_focus") == "FY") != annual):
            raise ValueError("fresh prepared scope/fiscal identity differs")
        if existing_raw and prepared.get("preparation_kind") != "EXISTING_RAW_LATEST_ANCHOR":
            raise ValueError("existing Raw preparation requires explicit execution opt-in")
        history = pinned_json(item["history_manifest"])
        if (item["history_manifest"]["path"] != str(Path(prepared["history_publication"]) / "history_manifest.json")
            or history.get("source_intake") != item["intake"]["path"] or history.get("plan") != plan
            or history.get("comparative_scope") != "CURRENT_FOCUS" or set(history.get("views", [])) != {"AS_FILED", "LATEST_REPORTED"}):
            raise ValueError("fresh history source/plan differs")
        reported_pin = {"path": str(Path(history["supersedes_publication"]) / "history_manifest.json"),
                        "sha256": history["source_manifest_sha256"]}
        reported = pinned_json(reported_pin)
        if any(reported.get(k) != history.get(k) for k in ("plan", "source_intake", "input_fingerprint", "comparative_scope", "views")):
            raise ValueError("fresh reported/consumer history source differs")
        analysis = pinned_json(prepared["analysis_manifest"])
        info = analysis["companies"][ticker]
        # Existing quarterly Analysis encodes its mode via typed quarter evidence;
        # unlike the annual producer it does not export a period_mode field.
        mode_matches = analysis.get("period_mode") == "ANNUAL" if annual else (
            analysis.get("quarter_source_evidence") == {"included": True, "rule_version": "quarter-typed-primary-pre-evidence-v1"})
        if (not mode_matches or info.get("as_of") != target
            or info.get("source_publication") != prepared["history_publication"]
            or analysis.get("source_manifest_hashes", {}).get("history_manifest_sha256") != item["history_manifest"]["sha256"]
            or analysis.get("targets", {}).get(ticker, {}).get("status") != "READY"
            or prepared["fiscal_year"] not in info.get("years", [])
            or not {"AS_FILED", "LATEST_REPORTED"} <= set(info.get("views", {}))):
            raise ValueError("fresh analysis identity/selection differs")
        baseline_filings = [r.get("filing", r) for r in baseline_intake["filings"]]
        old_anchors = [f["report_date"] for f in baseline_filings
                       if f.get("form") in FINANCIAL_FORMS and f.get("filed_date", "") <= baseline]
        if old_anchors and max(old_anchors) > filing["report_date"]:
            raise ValueError("fresh filing does not replace the latest financial anchor")
        row = {"cik": cik, "ticker": ticker, "status": "PROPOSED_FRESH_PREPARATION", "price_plane_only": True,
               "source_selection_as_of": target, "verified_through": target,
               "financial_anchor": (date.fromisoformat(filing["report_date"]) + timedelta(days=1)).isoformat(),
               "latest_financial_filing": filing, "analysis_pins": {mode: prepared["analysis_manifest"]},
               "intake": item["intake"], "preparation_pins": item,
               "reported_history_manifest": reported_pin, "discovery_receipt": window["receipt"],
               "discovery_root": receipt["root_snapshot"], "accounting_binding_approved": False}
        if existing_raw:
            row["preparation_kind"] = "EXISTING_RAW_LATEST_ANCHOR"
        row["readiness_id"] = "company-fresh-" + identity(row)
        output.append(row)
    _unique(output, "cik")
    return {"schema_version": "company-valuation-fresh-proposal-v1", "status": "PROPOSAL_NOT_APPROVED",
            "source_pins": {"config": config_pin, "common_manifest": config["common_manifest"],
                            "discovery_manifest": config["discovery_manifest"], "intake_execution_manifest": config["intake_execution_manifest"],
                            **({"assessments": config["assessments"]} if existing_raw else {}),
                            **({"preparation_execution_manifest": config["preparation_execution_manifest"]} if prepared_execution is not None else {})},
            "companies": sorted(output, key=lambda r: r["cik"])}


def accept_fresh(proposal_pin: dict, receipt_pin: dict) -> dict:
    """Accept only the ROOT-approved exact newly prepared price-plane cohort."""
    proposal, receipt = pinned_json(proposal_pin), pinned_json(receipt_pin)
    if (proposal.get("schema_version") != "company-valuation-fresh-proposal-v1"
        or receipt.get("schema_version") != "company-valuation-readiness-acceptance-v1"
        or receipt.get("reviewer") != "ROOT" or receipt.get("status") != "APPROVED_FOR_EXACT_FRESH_PREPARATION"
        or receipt.get("proposal") != proposal_pin):
        raise ValueError("fresh preparation requires exact ROOT acceptance")
    if propose_fresh(proposal["source_pins"]["config"]) != proposal:
        raise ValueError("fresh proposal differs from verified preparation evidence")
    companies = _unique(proposal["companies"], "cik")
    approved = receipt.get("approved_ciks", [])
    if not approved or len(approved) != len(set(approved)) or any(cik not in companies for cik in approved):
        raise ValueError("fresh approval includes absent/duplicate company")
    return {"schema_version": "company-valuation-readiness-v1", "source_pins": {"proposal": proposal_pin, "approval": receipt_pin},
            "companies": [{**companies[cik], "status": "APPROVED_FOR_EXACT_FRESH_PREPARATION",
                           "preparation_evidence_pins": [proposal_pin, receipt_pin]} for cik in sorted(approved)]}


def _accepted_readiness(pin: dict) -> list[dict]:
    supplied = pinned_json(pin)
    if supplied.get("schema_version") == "company-valuation-readiness-set-v1":
        # One bounded level combines the actual reuse and fresh cohorts; no cycles.
        records = []
        if not supplied.get("readiness_pins"):
            raise ValueError("readiness set is empty")
        for member in supplied["readiness_pins"]:
            if pinned_json(member).get("schema_version") != "company-valuation-readiness-v1":
                raise ValueError("readiness set requires accepted leaf publications")
            records.extend(_accepted_readiness(member))
        _unique(records, "cik")
        return records
    pins = supplied.get("source_pins", {})
    proposal = pinned_json(pins["proposal"])
    accept = accept_fresh if proposal.get("schema_version") == "company-valuation-fresh-proposal-v1" else accept_reuse
    accepted = accept(pins["proposal"], pins["approval"])
    if supplied != accepted:
        raise ValueError("company readiness differs from exact ROOT acceptance")
    return accepted["companies"]


def validated_company_readiness(bundle: dict) -> dict[str, dict]:
    """Resolve optional exact company reuse evidence once before a new computation.

    Old bundles have no override. Historical readers use their immutable values
    without reinterpreting this producer qualification under future source code.
    """
    from sec_xbrl.metrics.q4_eps_reconstruction import validated_q4_ttm_rows
    from sec_xbrl.metrics.reported_quarter_eps import validated_ttm_rows

    quarter_eps = {**validated_ttm_rows(bundle), **validated_q4_ttm_rows(bundle)}
    if not bundle.get("company_readiness"):
        return {}
    result = {}
    for company in _accepted_readiness(bundle["company_readiness"]):
        cik, baseline = company["cik"], company["source_selection_as_of"]
        fresh = company["status"] == "APPROVED_FOR_EXACT_FRESH_PREPARATION"
        if not fresh and baseline != bundle.get("financial_as_of"):
            raise ValueError("reuse readiness changes the original bundle cutoff")
        anchors = [a for a in bundle.get("financial_anchors", [])
                   if a["cik"] == cik and a["known_on"] <= baseline]
        if not anchors or max(a["period_end"] for a in anchors) != company["financial_anchor"]:
            raise ValueError("reuse readiness differs from bundle financial anchor")
        approved_sources = list(company["analysis_pins"].values())
        current_ids = {oid for grant in bundle.get("compatibility_grants", [])
                       if grant["cik"] == cik and grant.get("financial_anchor") == company["financial_anchor"]
                       for oid in grant.get("input_ids", {}).values()}
        for row in bundle["observations"]:
            if row["cik"] != cik or fresh and row["observation_id"] not in current_ids:
                continue
            if row.get("known_on", "9999") > baseline:
                raise ValueError("reuse observation became known after source selection")
            if row.get("observation_id") in quarter_eps:
                # This role has a separately replayed approved multi-filing chain.
                # It does not qualify any other role or historical system readiness.
                continue
            refs = [r["source"] for r in row.get("source_refs", []) if r.get("source")]
            if (not refs and not row.get("evidenced_zero")
                or any(r.get("analysis_manifest") not in approved_sources for r in refs)):
                raise ValueError("reuse observation differs from approved analysis source")
        result[cik] = {k: company[k] for k in ("readiness_id", "source_selection_as_of", "verified_through", "financial_anchor", "status")}
        result[cik]["financial_report_date"] = company["latest_financial_filing"]["report_date"]
    return result


def project_reuse_candidates(config_pin: dict, reuse_proposal_pin: dict) -> dict:
    """Extract exact latest-anchor reported candidates for a bounded review cohort.

    Projection may precede ROOT approval. Output carries no accounting approval or
    accepted readiness. EPS/actual shares are reused from the pinned common table.
    """
    config, proposal = pinned_json(config_pin), pinned_json(reuse_proposal_pin)
    if propose_reuse(proposal["source_pins"]["config"]) != proposal:
        raise ValueError("reuse proposal differs from verified source evidence")
    if config.get("schema_version") != "company-valuation-candidate-config-v1":
        raise ValueError("unsupported candidate configuration")
    financial = pinned_json(config["financial_inputs"])
    common_pin = proposal["source_pins"]["common_manifest"]
    common = pinned_json(common_pin)
    stored = common["files"]["financial_inputs"]
    expected = {"path": str(Path(common_pin["path"]).parent / stored["path"]), "sha256": stored["sha256"]}
    if config["financial_inputs"] != expected:
        raise ValueError("financial inputs are not the pinned baseline publication artifact")
    requested = config["tickers"]
    companies = {r["ticker"]: r for r in proposal["companies"]}
    if not requested or len(requested) != len(set(requested)) or any(t not in companies for t in requested):
        raise ValueError("candidate cohort must be unique unchanged-source companies")
    candidates, reports = [], []
    for ticker in sorted(requested):
        company = companies[ticker]
        rows = []
        for pin in company["analysis_pins"].values():
            rows.extend(project_additional_candidates(pin, cik=company["cik"], ticker=ticker,
                        cutoff=company["source_selection_as_of"], anchor_end=company["financial_anchor"]))
        reused = [r for r in financial if r["cik"] == company["cik"] and r.get("end") == company["financial_anchor"]]
        if any(r.get("financial_as_of") != company["source_selection_as_of"]
               or any(ref.get("analysis_manifest") not in company["analysis_pins"].values()
                      for ref in r.get("analysis_references", [])) for r in reused):
            raise ValueError("common input differs from baseline selection")
        candidates.extend(rows + reused)
        reports.append({"cik": company["cik"], "ticker": ticker, "financial_anchor": company["financial_anchor"],
                        "readiness_id": company["readiness_id"], "source_selection_as_of": company["source_selection_as_of"],
                        "proposed_verified_through": company["verified_through"], "accounting_binding_approved": False,
                        "projected_candidate_count": len(rows), "reused_common_count": len(reused),
                        "candidate_ids": sorted({r["observation_id"] for r in rows + reused})})
    # Equivalent source rows may occur in annual and quarterly views. Do not first-match them.
    unique = {}
    for row in candidates:
        key = row["observation_id"]
        if key in unique and unique[key] != row:
            raise ValueError("conflicting financial candidate identity")
        unique[key] = row
    return {"schema_version": "company-valuation-candidate-proposal-v1", "status": "PROPOSAL_NOT_APPROVED",
            "source_pins": {"config": config_pin, "reuse_proposal": reuse_proposal_pin,
                            "financial_inputs": config["financial_inputs"]},
            "companies": reports, "candidates": [unique[k] for k in sorted(unique)],
            "limitations": ["No common-equity, class, split, zero, EV or EPS-basis approval is conferred.",
                            "Original selection_as_of is retained; proposed verified-through is not accepted readiness."]}


def project_fresh_candidates(config_pin: dict, fresh_proposal_pin: dict) -> dict:
    """Project only the proposed single-filing current anchors, without binding roles."""
    config, proposal = pinned_json(config_pin), pinned_json(fresh_proposal_pin)
    if (config.get("schema_version") != "company-valuation-fresh-candidate-config-v1"
        or proposal.get("schema_version") != "company-valuation-fresh-proposal-v1"):
        raise ValueError("unsupported fresh candidate configuration/proposal")
    if propose_fresh(proposal["source_pins"]["config"]) != proposal:
        raise ValueError("fresh candidate proposal differs from verified preparation")
    companies = {r["ticker"]: r for r in proposal["companies"]}
    requested = config["tickers"]
    if not requested or len(requested) != len(set(requested)) or any(t not in companies for t in requested):
        raise ValueError("fresh candidate cohort must be unique prepared companies")
    candidates, reports = {}, []
    for ticker in sorted(requested):
        company = companies[ticker]
        rows = []
        for pin in company["analysis_pins"].values():
            rows.extend(project_additional_candidates(pin, cik=company["cik"], ticker=ticker,
                        cutoff=company["source_selection_as_of"], anchor_end=company["financial_anchor"]))
            rows.extend(r for r in project_financial_inputs(pin, cik=company["cik"], ticker=ticker,
                        financial_as_of=company["source_selection_as_of"]) if r.get("end") == company["financial_anchor"])
        for row in rows:
            key = row["observation_id"]
            if key in candidates and candidates[key] != row:
                raise ValueError("conflicting fresh financial candidate identity")
            candidates[key] = row
        reports.append({k: company[k] for k in ("cik", "ticker", "financial_anchor", "readiness_id", "source_selection_as_of", "verified_through")}
                       | {"accounting_binding_approved": False, "candidate_ids": sorted({r["observation_id"] for r in rows})})
    return {"schema_version": "company-valuation-candidate-proposal-v1", "status": "PROPOSAL_NOT_APPROVED",
            "source_pins": {"config": config_pin, "fresh_proposal": fresh_proposal_pin},
            "companies": reports, "candidates": [candidates[k] for k in sorted(candidates)],
            "limitations": ["No accounting role/class/split/zero approval or native financial source approval.",
                            "A current 10-Q alone does not manufacture direct12m EPS or a complete governed TTM."]}


def propose_bindings(config_pin: dict) -> dict:
    """Expand explicit lead role plans into exact existing-schema review proposals.

    Performs source identity/period/scope checks, never chooses accounting roles,
    interprets class labels, invents zeros or returns approved typed observations.
    Numeric binding remains the existing receipt-gated bind_bundle command.
    """
    config = pinned_json(config_pin)
    if config.get("schema_version") != "company-valuation-role-plan-v1":
        raise ValueError("unsupported explicit role plan")
    candidates = {}
    for pin in config["candidate_pins"]:
        source = pinned_json(pin)
        for row in source["candidates"] if isinstance(source, dict) else source:
            key = row["observation_id"]
            if key in candidates and candidates[key] != row:
                raise ValueError("ambiguous role-plan financial candidate")
            candidates[key] = row
    output = []
    used_ids = set()
    for plan in config["companies"]:
        declarations, proofs = plan["declarations"], []
        if not declarations or len({d["role"] for d in declarations}) != len(declarations):
            raise ValueError("explicit nonduplicate role declarations required")
        first = declarations[0]
        fields = ("cik", "currency", "scope_id", "stock_class_id", "split_basis_id", "known_on", "period_end")
        if any(not first.get(k) or any(d.get(k) != first[k] for d in declarations) for k in fields):
            raise ValueError("proposed current binding scope must be explicit and homogeneous")
        if (plan.get("cik") != first["cik"] or not plan.get("security_id")
            or len(first["cik"]) != 10 or not first["cik"].isdecimal()):
            raise ValueError("proposed security/company identity required")
        date.fromisoformat(first["known_on"])
        date.fromisoformat(first["period_end"])
        for d in declarations:
            role, formula, ids = d["role"], d.get("formula", "DIRECT"), d.get("candidate_ids", [])
            if role not in ROLE_UNITS or formula not in {"DIRECT", "SUM", "SUBTRACT", "PER_SHARE", "EVIDENCED_ZERO"}:
                raise ValueError("unsupported proposed role/formula")
            if role == "diluted_eps_12m" and formula != "DIRECT":
                raise ValueError("EPS direct-only; no proposed EPS reconstruction")
            if (len(ids) != len(set(ids)) or any(i not in candidates for i in ids)
                or formula == "DIRECT" and len(ids) != 1 or formula in {"SUBTRACT", "PER_SHARE"} and len(ids) != 2
                or formula == "SUM" and not ids or formula == "EVIDENCED_ZERO" and ids):
                raise ValueError("proposed formula sources/arity differ")
            if role == "common_shares":
                check_actual_share_sources([candidates[i] for i in ids], formula)
            evidence = plan.get("role_evidence", {}).get(role, {})
            for pin in evidence.get("pins", []):
                pinned_json(pin)
            if formula == "EVIDENCED_ZERO" and (not evidence.get("pins") or not evidence.get("rationale")):
                raise ValueError("proposed zero requires explicit role evidence and rationale")
            refs = []
            for oid in ids:
                row = candidates[oid]
                used_ids.add(oid)
                if (row["cik"] != first["cik"] or finite(row.get("value")) is None
                    or row.get("status") not in {"AVAILABLE_REPORTED", "AVAILABLE_DERIVED_SEPARATE"}
                    or row.get("dimensions") != d.get("dimensions", []) or row.get("end") != d["period_end"]
                    or row.get("period_class") != d.get("period_class")
                    or d.get("period_start") is not None and row.get("start") != d["period_start"]
                    or not row.get("filed_date") or row["filed_date"] > d["known_on"]):
                    raise ValueError("proposed role source identity/scope/period differs")
                source = row.get("source", {})
                lineage = source.get("value_lineage", source)
                refs.append({"observation_id": oid, "qname": row["qname"], "value": row["value"],
                    "period_class": row["period_class"], "start": row.get("start"), "end": row["end"],
                    "dimensions": row.get("dimensions"), "raw_dimensions": row.get("raw_dimensions", lineage.get("raw_dimension_signature")),
                    "unit": row.get("unit"), "unit_kind": row.get("unit_kind"),
                    "unit_numerator_measures": row.get("unit_numerator_measures", lineage.get("unit_numerator_measures")),
                    "unit_denominator_measures": row.get("unit_denominator_measures", lineage.get("unit_denominator_measures")),
                    "source_fact_id": lineage.get("selected_source_fact_id"), "source_filing_id": lineage.get("source_filing_id"),
                    "source_snapshot_id": lineage.get("source_snapshot_id"), "context_id": lineage.get("context_id"),
                    "filed_date": row["filed_date"], "source": source})
            proofs.append({"role": role, "formula": formula, "source_inputs": refs, "review_evidence": evidence})
        output.append({"schema_version": "price-financial-binding-proposal-v1", "status": "PROPOSAL_NOT_APPROVED",
            "cik": plan["cik"], "security_id": plan["security_id"], "declarations": declarations,
            "grant_constraints": plan["grant_constraints"], "source_role_proofs": proofs,
            "source_pins": {"role_plan": config_pin, "candidate_pins": config["candidate_pins"]},
            **({"limitations": plan["limitations"]} if plan.get("limitations") else {})})
    _unique(output, "cik")
    if not output:
        raise ValueError("role plan cohort is empty")
    return {"schema_version": "company-valuation-binding-proposal-set-v1", "status": "PROPOSAL_NOT_APPROVED",
            "source_pins": {"role_plan": config_pin}, "proposals": output,
            "candidates": [candidates[k] for k in sorted(used_ids)]}
