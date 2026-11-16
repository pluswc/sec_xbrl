from __future__ import annotations

import copy
import hashlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import html
from test_price_related_metrics import financial, prices, sessions

from sec_xbrl.metrics.market_inputs import encoded, identity
from sec_xbrl.metrics.price_financial_inputs import augment_reported_quarter_eps
from sec_xbrl.metrics.reported_quarter_eps import (
    MODE,
    _reported_html,
    prepare_ttm,
    validate_current_evaluation,
    verify_ttm,
)
from sec_xbrl.screening.price_metric_publication import PriceMetricReader, publish_price_metrics
from sec_xbrl.screening.price_metric_service import PriceMetricService

FIXTURE_EVALUATION_AT = datetime(2026, 11, 16, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixture_evaluation_clock(monkeypatch):
    # Replay this fixture's declared evaluation, independent of the CI wall clock.
    # Product preparation still records its actual clock; no stored data is changed.
    monkeypatch.setattr("sec_xbrl.metrics.reported_quarter_eps._now", lambda: FIXTURE_EVALUATION_AT)


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


def blob(path, value):
    path.write_text(value)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def setup(tmp_path):
    """Mixed physical formats, with exact review; no network or retained archives."""
    review = pin(tmp_path / "review.json", {"reviewer": "ROOT", "status": "SOURCE_AND_SEMANTIC_MAPPING_REVIEWED_FOR_EXACT_PLAN",
        "companies": [{"ticker": "TEST", "cik": "0000000001", "security_id": "US:TEST", "stock_class_id": "common",
            "split_basis_id": "unadjusted-2026", "financial_scope_id": "issuer-common", "target_anchor": "2026-10-01",
            "window_start": "2025-10-01", "exact_sum": "10", "original_XBRL_observation_ids": ["q0", "q1", "q3"],
            "original_HTML_source_ids": ["html-q2"], "unadjusted_GAAP_total_not_continuing_or_normalized": True}]})
    decision = pin(tmp_path / "decision.json", {"reviewer": "ROOT", "status": "APPROVED_FOR_BOUNDED_IMPLEMENTATION",
        "mode": MODE, "quote_session": "2026-11-13", "evaluation_as_of": "2026-11-16",
        "public_financial_information_cutoff": "2026-11-13", "decided_at": "2026-11-16T00:00:00+00:00"})
    _, observations, grant = financial()
    old_eps = next(r for r in observations if r["role"] == "diluted_eps_12m")
    observations.remove(old_eps)
    grant["input_ids"].pop("diluted_eps_12m")
    grant["evidence_pins"] = [review]
    base = {"schema_version": "price-financial-input-bundle-v1", "financial_as_of": "2026-11-13",
        "observations": observations, "compatibility_grants": [grant],
        "financial_anchors": [{"cik": grant["cik"], "period_end": "2026-10-01", "known_on": "2026-10-01"}]}
    base_pin = pin(tmp_path / "base.json", base)
    periods = [(2025, 4, "2025-10-01", "2026-01-01"), (2026, 1, "2026-01-01", "2026-04-01"),
               (2026, 2, "2026-04-01", "2026-07-01"), (2026, 3, "2026-07-01", "2026-10-01")]
    rows = [{"observation_id": f"q{i}", "cik": grant["cik"], "input_id": "reported_eps_diluted_total",
        "status": "AVAILABLE_REPORTED", "reported_or_derived": "REPORTED", "period_class": "QTD_3M",
        "fiscal_year": fy, "fiscal_quarter": q, "start": start, "end": end, "end_convention": "EXCLUSIVE",
        "filed_date": "2026-10-01", "value": str(i + 1), "unit_kind": "USD/share",
        "unit": ['["iso4217:USD"]', '["xbrli:shares"]'], "dimensions": "[]", "raw_dimensions": "[]"}
        for i, (fy, q, start, end) in enumerate(periods)]
    text = '<html><body><table><tr><td>Three Months Ended June30</td><td>Twelve Months Ended</td></tr><tr><td>Diluted</td><td>3</td><td>8</td></tr></table></body></html>'
    source = blob(tmp_path / "exhibit.htm", text)
    primary = blob(tmp_path / "8k.htm", '<html><a href="exhibit.htm">EX99.1</a></html>')
    primary["url"] = "https://www.sec.gov/Archives/example/8k.htm"
    capture = pin(tmp_path / "capture.json", {"cik": grant["cik"], "ticker": "TEST", "accession": "accession",
        "form": "8-K", "files": [{**source, "fetched_at": "2026-11-16T00:01:00+00:00"}]})
    doc = html.fromstring(text)
    table_text = " ".join(" ".join(doc.xpath('//table')[0].itertext()).split())
    reported = {"source_observation_id": "html-q2", "cik": grant["cik"], "ticker": "TEST", "form": "8-K",
        "accession": "accession", "source_document": "exhibit.htm", "source_document_type": "EX-99.1",
        "source_kind": "OFFICIAL_REPORTED_HTML_TABLE", "raw_xbrl_identity": None, "raw_dimension_signature": None,
        "measurement": "GAAP_DILUTED_TOTAL_EPS", "metric_label": "Diluted", "unit_semantics": "USD/share",
        "reported_value": "3", "reported_or_derived": "REPORTED", "period_class": "QTD_3M",
        "fiscal_year": 2026, "fiscal_quarter": 2, "period_start": "2026-04-01", "period_end": "2026-07-01",
        "end_convention": "EXCLUSIVE", "filed_date": "2026-07-30", "actual_captured_at": "2026-11-16T00:01:00+00:00",
        "source_pin": source, "capture_manifest_pin": capture, "source_url": "https://www.sec.gov/Archives/example/exhibit.htm",
        "exhibit_identity": {"source_primary_pin": primary}, "locator": {"value_xpath": "/html/body/table/tr[2]/td[2]",
        "row_xpath": "/html/body/table/tr[2]", "raw_cell_text": "3", "row_text": "Diluted 3 8",
        "table_text_sha256": hashlib.sha256(table_text.encode()).hexdigest(), "table_header_rows": ["Three Months Ended June30 Twelve Months Ended"]}}
    pool = pin(tmp_path / "pool.json", [r for i, r in enumerate(rows) if i != 2])
    supplement = pin(tmp_path / "html.json", {"observations": [reported]})
    ids = ["q0", "q1", "html-q2", "q3"]
    company = {"ticker": "TEST", "cik": grant["cik"], "security_id": grant["security_id"], "currency": "USD",
        "stock_class_id": grant["stock_class_id"], "split_basis_id": grant["split_basis_id"], "scope_id": grant["financial_scope_id"],
        "target_anchor": "2026-10-01", "window_start": "2025-10-01", "expected_value": "10",
        "input_refs": [{"kind": "OFFICIAL_REPORTED_HTML_TABLE" if i == 2 else "XBRL_ANALYTICAL",
            "source_pin": supplement if i == 2 else pool, "observation_id": ids[i], "record_sha256": identity(reported if i == 2 else rows[i]),
            "period_start": p[2], "period_end": p[3]} for i, p in enumerate(periods)],
        "scope_mapping": {"version": "EXACT_REVIEWED_SOURCE_SCOPE_V1", "target_eps_scope_id": "reviewed-total",
            "input_ids": ids, "basis_status": "COMPATIBLE_NO_RESCALE", "evidence_pins": [review]}}
    hold = {"ticker": "HON", "cik": "0000773840", "reason": "PER_SHARE_BASIS_MISMATCH", "value": None,
        "evidence_pins": [pin(tmp_path / "hold.json", {"reason": "PER_SHARE_BASIS_MISMATCH", "needed": "Direct Q4FY25 and Q1FY26 on the post-split basis"})]}
    plan = {"schema_version": "eps-ttm-plan-v1", "quote_session": "2026-11-13", "requested_as_of": "2026-11-16",
        "public_financial_information_cutoff": "2026-11-13", "evaluation_decision": decision, "source_review": review,
        "quarter_source_proof": review, "base_financial_bundle": base_pin, "source_pins": [pool, supplement], "companies": [company], "holds": [hold]}
    return {"plan": plan, "base": base, "reported": reported, "rows": rows, "old_eps": old_eps}


def run_pin(tmp_path, plan, tag=""):
    plan_pin = pin(tmp_path / f"plan{tag}.json", plan)
    approval = pin(tmp_path / f"approval{tag}.json", {"schema_version": "eps-ttm-root-acceptance-v1", "reviewer": "ROOT",
        "status": "APPROVED_FOR_EXACT_DIRECT_QTD_TTM", "plan": plan_pin,
        "approved_ciks": [c["cik"] for c in plan["companies"]], "approved_at": "2026-11-16T00:02:00+00:00"})
    return pin(tmp_path / f"run{tag}.json", {"schema_version": "eps-ttm-run-v1", "plan": plan_pin, "approval": approval})


def test_mixed_reported_sources_exact_sum_and_additive_bundle(tmp_path):
    fixture = setup(tmp_path)
    original = copy.deepcopy(fixture["base"])
    artifact = prepare_ttm(run_pin(tmp_path, fixture["plan"]))
    row = artifact["observations"][0]
    assert row["value"] == "10" and row["source_kind"] == "GOVERNED_DIRECT_QTD_TTM"
    assert row["ready_on"] == "2026-11-16" and row["known_on"] == "2026-10-01"
    html_source = artifact["reported_quarter_sources"]["html-q2"]
    assert html_source["original_record"]["raw_dimension_signature"] is None
    assert html_source["reported_comparison_record"]["dimensions"] is None
    derived = pin(tmp_path / "derived.json", artifact)
    assert verify_ttm(derived) == artifact
    bundle = augment_reported_quarter_eps(derived)
    assert bundle["observations"][:-1] == original["observations"]
    assert fixture["base"] == original
    assert bundle["compatibility_grants"][0]["ready_on"] == original["compatibility_grants"][0]["ready_on"]
    assert all(r["cik"] != "0000773840" for r in artifact["observations"])
    assert artifact["holds"][0]["reason"] == "PER_SHARE_BASIS_MISMATCH"


@pytest.mark.parametrize("field,value", [("raw_dimension_signature", []), ("raw_xbrl_identity", {}),
    ("measurement", "NON_GAAP_EPS"), ("period_class", "YTD_6M"), ("unit_semantics", "EUR/share"),
    ("reported_value", "8"), ("actual_captured_at", "2026-11-16T00:01:00")])
def test_html_identity_column_units_and_actual_timestamp_fail_closed(tmp_path, field, value):
    record = setup(tmp_path)["reported"]
    record[field] = value
    with pytest.raises(ValueError):
        _reported_html(record)


def test_exact_mapping_gap_and_competing_physical_format_fail_closed(tmp_path):
    f = setup(tmp_path)
    plan = copy.deepcopy(f["plan"])
    plan["companies"][0]["scope_mapping"]["basis_status"] = "UNKNOWN"
    with pytest.raises(ValueError, match="mapping"):
        prepare_ttm(run_pin(tmp_path, plan, "mapping"))
    # Different physical scope must not hide a conflicting same-quarter value.
    competitor = {**f["rows"][2], "observation_id": "competing-xbrl", "value": "7", "dimensions": "[]"}
    pool = pin(tmp_path / "competing.json", [competitor])
    plan = copy.deepcopy(f["plan"])
    plan["source_pins"].append(pool)
    with pytest.raises(ValueError, match="AMBIGUOUS_DIRECT_QUARTER_REVIEWED_SCOPE"):
        prepare_ttm(run_pin(tmp_path, plan, "competing"))
    plan = copy.deepcopy(f["plan"])
    plan["companies"][0]["input_refs"].pop(0)
    with pytest.raises(ValueError, match="reviewed EPS"):
        prepare_ttm(run_pin(tmp_path, plan, "gap"))


@pytest.mark.parametrize("change", ["company", "input", "class", "overlap"])
def test_exact_source_review_case_and_hold_scope_are_mandatory(tmp_path, change):
    f = setup(tmp_path)
    plan = copy.deepcopy(f["plan"])
    if change == "company":
        plan["companies"][0]["cik"] = "0000773841"
    elif change == "input":
        plan["companies"][0]["input_refs"][0]["observation_id"] = "not-reviewed"
    elif change == "class":
        plan["companies"][0]["stock_class_id"] = "other-class"
    else:
        plan["holds"].append({"cik": "0000000001", "reason": "PER_SHARE_BASIS_MISMATCH", "value": None})
    with pytest.raises(ValueError, match="scope|reviewed EPS"):
        prepare_ttm(run_pin(tmp_path, plan, "scope"))


def test_approval_source_and_ready_mutation_rejected(tmp_path):
    f = setup(tmp_path)
    run = run_pin(tmp_path, f["plan"])
    artifact = prepare_ttm(run)
    with pytest.raises(ValueError, match="future"):
        prepare_ttm(run, _recorded_at="2026-11-17T00:00:00+00:00")
    artifact["observations"][0]["value"] = "21.02"
    with pytest.raises(ValueError, match="differs"):
        verify_ttm(pin(tmp_path / "mutated.json", artifact))
    Path(f["plan"]["source_pins"][0]["path"]).write_text("[]")
    with pytest.raises(ValueError, match="hash"):
        prepare_ttm(run)


@pytest.mark.parametrize("field,value", [("filed_date", "2026-11-14"), ("unit", ['["iso4217:EUR"]', '["xbrli:shares"]']),
    ("start", "2025-10-02"), ("period_class", "YTD_6M")])
def test_source_mechanics_cannot_be_relabelled_by_review(tmp_path, field, value):
    f = setup(tmp_path)
    plan = copy.deepcopy(f["plan"])
    pool = [copy.deepcopy(r) for i, r in enumerate(f["rows"]) if i != 2]
    pool[0][field] = value
    changed = pin(tmp_path / "changed-pool.json", pool)
    plan["source_pins"][0] = changed
    for ref in plan["companies"][0]["input_refs"]:
        if ref["kind"] == "XBRL_ANALYTICAL":
            ref["source_pin"] = changed
        if ref["observation_id"] == pool[0]["observation_id"]:
            ref["record_sha256"] = identity(pool[0])
    with pytest.raises(ValueError):
        prepare_ttm(run_pin(tmp_path, plan, "changed"))


def current_publication(tmp_path):
    f = setup(tmp_path)
    derived = pin(tmp_path / "derived.json", prepare_ttm(run_pin(tmp_path, f["plan"])))
    bundle = augment_reported_quarter_eps(derived)
    # Hold company retains capital roles; a separate existing FY issuer is unchanged.
    for cik, ticker, eps in [("0000773840", "HON", False), ("0000000009", "FY", True)]:
        _, rows, grant = financial()
        for r in rows:
            r.update(cik=cik, observation_id=cik + r["observation_id"])
        grant.update(cik=cik, security_id="US:" + ticker, evidence_pins=[f["plan"]["source_review"]])
        grant["input_ids"] = {r["role"]: r["observation_id"] for r in rows if eps or r["role"] != "diluted_eps_12m"}
        bundle["observations"].extend(r for r in rows if eps or r["role"] != "diluted_eps_12m")
        bundle["compatibility_grants"].append(grant)
        bundle["financial_anchors"].append({"cik": cik, "period_end": "2026-10-01", "known_on": "2026-10-01"})
    bundle_pin = pin(tmp_path / "bundle.json", bundle)
    calendar = sessions(331)
    calendar["sessions"].append("2026-11-13")
    calendar["coverage_end"] = "2026-11-13"
    calendar["source_pins"] = [f["plan"]["source_review"]]
    price_rows = prices(calendar)
    companies = [{"cik": "0000000001", "ticker": "TEST", "security_id": "US:TEST"},
        {"cik": "0000773840", "ticker": "HON", "security_id": "US:HON"}, {"cik": "0000000009", "ticker": "FY", "security_id": "US:FY"}]
    source = [{**p, "security_id": c["security_id"], "observation_id": c["cik"] + p["observation_id"],
        "as_traded_close": "100", "currency": "USD", "ready_on": None} for c in companies for p in price_rows]
    batch = pin(tmp_path / "batch.json", {"schema_version": "price-metric-canonical-batch-v1", "price_batch_calls": 1,
        "prices": source, "companies": companies, "query": {"start_date": calendar["sessions"][0], "end_date": "2026-11-13"}, "volume_basis": "TRUE_SPLIT_COMPATIBLE"})
    policy = {"schema_version": "eps-current-evaluation-policy-v1", "mode": MODE, "decision": f["plan"]["evaluation_decision"],
        "evaluation_as_of": "2026-11-16", "evaluation_at": artifact_time(), "quote_session": "2026-11-13",
        "public_financial_information_cutoff": "2026-11-13", "derivation": derived, "financial_inputs": bundle_pin, "price_batch": batch}
    policy_pin = pin(tmp_path / "policy.json", policy)
    approval = pin(tmp_path / "policy-approval.json", {"schema_version": "eps-current-evaluation-root-acceptance-v1",
        "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_CURRENT_EVALUATION", "policy": policy_pin, "approved_at": artifact_time()})
    config = {"schema_version": "screening-price-metrics-config-v1", "price_batch": batch, "sessions": pin(tmp_path / "sessions.json", calendar),
        "financial_inputs": bundle_pin, "requested_as_of": "2026-11-16", "price_as_of": "2026-11-13", "session_selection_policy": "EXPLICIT_COMPLETED_SESSION",
        "historical_readiness_policy": "READY_ONLY", "series_start": "2026-10-01", "historical_start": "2026-10-01",
        "dataset_scope": {"dataset_id": "test", "financial_as_of": "2026-10-25"}, "ev_policy": {}, "fixed_multiples": {"per": ["10"], "pbr": ["2"]},
        "current_eps_evaluation": {"policy": policy_pin, "approval": approval}}
    return config, bundle, policy


def artifact_time():
    return FIXTURE_EVALUATION_AT.isoformat()


def test_current_snapshot_is_distinct_from_daily_history_and_fy_capital_unchanged(tmp_path):
    config, _, _ = current_publication(tmp_path)
    result = publish_price_metrics(pin(tmp_path / "pub-config.json", config), tmp_path / "published")
    reader = PriceMetricReader({k: result[k] for k in ("path", "sha256")})
    current = reader.query(ciks=["0000000001"], metric_ids=["per", "earnings_yield"])["rows"]
    assert [Decimal(r["value"]) for r in current] == [Decimal(10), Decimal(10)]
    assert all(r["historical_ready"] is False and r["backtest_eligible"] is False for r in current)
    daily = reader.query(ciks=["0000000001"], metric_ids=["per"], mode="series", start="2026-11-13")["rows"][0]
    assert daily["reason"] == "INPUT_AFTER_PRICE_AS_OF" and "current_eps_evaluation" not in daily
    assert daily["observation_id"] != current[0]["observation_id"]
    fy = reader.query(ciks=["0000000009"], metric_ids=["per"])["rows"][0]
    assert fy["value"] == "50" and "current_eps_evaluation" not in fy
    hon = {r["metric_id"]: r for r in reader.query(ciks=["0000773840"], metric_ids=["per", "pbr", "common_market_cap"])["rows"]}
    assert hon["per"]["reason"] == "PER_SHARE_BASIS_MISMATCH"
    assert hon["pbr"]["value"] == "5" and hon["common_market_cap"]["value"] == "1000"
    evidence = reader.evidence("0000773840", hon["per"]["observation_id"])
    assert "Q4FY25 and Q1FY26" in evidence["diagnostic_evidence"][0]["needed"]
    evidence = reader.evidence("0000000001", current[0]["observation_id"])
    assert len(evidence["reported_quarter_sources"]) == 4
    assert evidence["reported_quarter_sources"]["html-q2"]["original_record"]["raw_xbrl_identity"] is None
    service = PriceMetricService(reader, tmp_path / "journal.sqlite")
    band = service.execute("bands", {"cik": "0000000001", "multiples": {"per": ["11.25"]}})
    assert band["rows"][0]["value"] == "112.50"
    saved = service.save(kind="RESULT", operation="bands", request={"cik": "0000000001", "multiples": {"per": ["11.25"]}}, title="current", note="quote13 evaluation16")
    cold = PriceMetricService(reader, tmp_path / "journal.sqlite")
    reopened = cold.reopen(saved["id"])
    assert reopened["result"] == saved["result"] and reopened["source_context"]["current_eps_evaluation"]["quote_session"] == "2026-11-13"
    # Runtime evidence uses pinned materialized inputs, never the producer replay.
    from unittest.mock import patch
    with patch("sec_xbrl.metrics.reported_quarter_eps.prepare_ttm", side_effect=AssertionError("consumer rederived")):
        assert cold.execute("evidence", {"cik": "0000000001", "observation_id": reopened["result"]["rows"][0]["observation_id"], "evidence_context": reopened["evidence_context"]})["reported_quarter_sources"]


def test_without_current_opt_in_new_eps_stays_unready_and_mutated_input_is_rejected(tmp_path):
    from sec_xbrl.metrics.price_related import calculate_valuation_metrics

    config, bundle, _ = current_publication(tmp_path)
    declaration = config.pop("current_eps_evaluation")
    result = publish_price_metrics(pin(tmp_path / "no-opt-in.json", config), tmp_path / "no-opt-in-publication")
    reader = PriceMetricReader({k: result[k] for k in ("path", "sha256")})
    row = reader.query(ciks=["0000000001"], metric_ids=["per"])["rows"][0]
    assert row["reason"] == "INPUT_AFTER_PRICE_AS_OF"
    assert "current_eps_evaluation" not in reader.query()
    altered = copy.deepcopy(bundle["observations"])
    next(r for r in altered if r.get("source_kind") == "GOVERNED_DIRECT_QTD_TTM")["value"] = "21.02"
    with pytest.raises(ValueError, match="input differs"):
        calculate_valuation_metrics({"security_id": "US:TEST", "trade_date": "2026-11-13", "as_traded_close": "100", "currency": "USD"},
            altered, bundle["compatibility_grants"][0], cik="0000000001", security_id="US:TEST", as_of="2026-11-13", financial_as_of="2026-11-13",
            current_eps_evaluation={"declaration": declaration, "financial_inputs": config["financial_inputs"], "price_batch": config["price_batch"], "requested_as_of": config["requested_as_of"]})


@pytest.mark.parametrize("field,value", [("evaluation_at", "2026-11-16T23:59:59+00:00"),
    ("evaluation_at", "2026-11-16T00:00:00+00:00"), ("evaluation_at", "2026-11-16T08:00:00"),
    ("evaluation_as_of", "2026-11-17"), ("quote_session", "2026-11-16")])
def test_exact_policy_and_aware_future_ready_guards(tmp_path, field, value):
    config, _, policy = current_publication(tmp_path)
    policy[field] = value
    altered = pin(tmp_path / "altered-policy.json", policy)
    accepted = pin(tmp_path / "altered-approval.json", {"schema_version": "eps-current-evaluation-root-acceptance-v1",
        "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_CURRENT_EVALUATION", "policy": altered, "approved_at": artifact_time()})
    declaration = {"policy": altered, "approval": accepted}
    with pytest.raises(ValueError):
        validate_current_evaluation(declaration, bundle_pin=config["financial_inputs"], batch_pin=config["price_batch"], requested="2026-11-16", selected="2026-11-13")


@pytest.mark.skipif(not os.environ.get("SEC_XBRL_EPS_TTM_CACHED_CONFIG"), reason="explicit cached ROOT inputs only")
def test_cached_exact_three_company_and_hon_reverse_split_boundary(monkeypatch):
    from sec_xbrl.metrics.market_inputs import pinned_json
    from sec_xbrl.metrics.reported_quarter_eps import aware

    config = {"path": os.environ["SEC_XBRL_EPS_TTM_CACHED_CONFIG"], "sha256": os.environ["SEC_XBRL_EPS_TTM_CACHED_SHA256"]}
    # This is a test-only replay at the exact declaration's recorded approval
    # time, not a new assertion about actual operational preparation readiness.
    recorded_at = pinned_json(pinned_json(config)["approval"])["approved_at"]
    monkeypatch.setattr("sec_xbrl.metrics.reported_quarter_eps._now", lambda: aware(recorded_at))
    artifact = prepare_ttm(config, _recorded_at=recorded_at)
    assert artifact["prepared_at"] == recorded_at
    assert {r["ticker"]: r["value"] for r in artifact["observations"]} == {"MSFT": "19.16", "NVDA": "7.91", "ABBV": "5.81"}
    assert len(artifact["reported_quarter_sources"]) == 12
    hon = next(h for h in artifact["holds"] if h["ticker"] == "HON")
    assert hon["reason"] == "PER_SHARE_BASIS_MISMATCH" and hon["value"] is None
    proof = pinned_json(hon["evidence_pins"][0])
    assert "one-for-two" in proof["event"].lower() and "2026" in proof["event"]
    assert proof["unapproved_mechanical_sum"] == "21.02"
    assert [(q["start"], q["end"]) for q in proof["affected_original_quarters"]] == [
        ("2025-10-01", "2026-01-01"), ("2026-01-01", "2026-04-01")]
    assert all(r["cik"] != hon["cik"] for r in artifact["observations"])
