from __future__ import annotations

import copy
import gzip
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from lxml import html
from test_price_related_metrics import financial

from sec_xbrl.metrics.market_inputs import encoded, identity
from sec_xbrl.metrics.price_related import calculate_valuation_metrics, fixed_multiple_bands
from sec_xbrl.metrics.q4_eps_reconstruction import (
    DILUTION_CLAIMS,
    NUMERATOR_CLAIMS,
    RULE,
    _official,
    _qualify,
    _quarter_sources,
    _select,
    augment_q4_eps_ttm,
    discover_accounting_evidence,
    propose_q4_eps,
    qualify_q4_eps,
    validated_q4_ttm_rows,
    verify_q4_eps,
)
from sec_xbrl.metrics.reported_quarter_eps import validate_current_evaluation

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction._now", lambda: NOW)
    def replay(_normalizer, payload, _security, _p1, _p2, _reviewed):
        raw = json.loads(payload)["chart"]["result"][0]
        rows = [{"trade_date": datetime.fromtimestamp(ts, UTC).date(), "split_factor": 1} for ts in raw["timestamp"]]
        return rows, {"status": "ok", "source_sha256": hashlib.sha256(payload).hexdigest()}
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction._supplier_replay", replay)


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


def source(path, text):
    path.write_text(text)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def snapshot(root, cik, accession, form, filed, report, periods):
    directory = root / "snapshots" / cik / accession.replace("-", "")
    directory.mkdir(parents=True)
    fid = accession
    filing = {"filing_id": fid, "cik": cik, "accession": accession, "form": form,
              "filed_date": filed, "report_date": report,
              "document_fiscal_period_focus": "FY" if form == "10-K" else "Q3"}
    records = {"filing": [filing], "concept": [], "context": [], "unit": [], "fact": [],
               "dimension_fact": [], "role": [], "relationship": []}
    for i, (start, end, n, w, eps) in enumerate(periods):
        records["context"].append({"filing_id": fid, "context_id": f"ctx{i}", "start_date": start,
            "end_date": end, "entity_identifier": cik, "dimension_count": 0})
        for flavor in ("basic", "diluted"):
            for kind, tag, value, unit in (
                ("numerator", "NetIncomeLossAvailableToCommonStockholdersBasic" if flavor == "basic" else "NetIncomeLossAvailableToCommonStockholdersDiluted", n, [["iso4217:USD"], []]),
                ("shares", "WeightedAverageNumberOfSharesOutstandingBasic" if flavor == "basic" else "WeightedAverageNumberOfDilutedSharesOutstanding", w, [["xbrli:shares"], []]),
                ("eps", "EarningsPerShareBasic" if flavor == "basic" else "EarningsPerShareDiluted", eps, [["iso4217:USD"], ["xbrli:shares"]]),
            ):
                cid = flavor+kind
                if i == 0:
                    records["concept"].append({"filing_id": fid, "raw_concept_id": cid,
                        "qname": "us-gaap:"+tag, "namespace_uri": "http://fasb.org/us-gaap/2026",
                        "local_name": tag, "taxonomy_family": "us-gaap", "taxonomy_version": "2026",
                        "is_standard": True, "period_type": "duration", "data_type": "xbrli:monetaryItemType" if kind == "numerator" else "xbrli:decimalItemType",
                        "label": tag})
                    records["unit"].append({"filing_id": fid, "unit_id": cid,
                        "numerator_measures": json.dumps(unit[0]), "denominator_measures": json.dumps(unit[1])})
                records["fact"].append({"filing_id": fid, "fact_id": f"{cid}{i}", "raw_concept_id": cid,
                    "context_id": f"ctx{i}", "unit_id": cid, "value_numeric": str(value),
                    "decimals": "2" if kind == "eps" else "INF", "reported_or_derived": "REPORTED",
                    "source_document": "filing.htm", "source_locator": f"fact-{cid}{i}"})
    for name, values in records.items():
        pl.DataFrame(values).write_parquet(directory / f"{name}.parquet")
    manifest = {"schema_version": 1, "cik": cik, "accession": accession, "form": form,
        "source_url": "cached://fixture", "package_sha256": "fixture", "fact_corpus_source": "fixture",
        "source_fact_count": len(records["fact"]), "materialized_fact_count": len(records["fact"]),
        "concept_count": len(records["concept"]), "context_count": len(records["context"]),
        "unit_count": len(records["unit"]), "dimension_fact_count": 0, "role_count": 0,
        "relationship_count": 0, "layer1_parser_version": "fixture-v1", "relationship_parser_version": "fixture-v1"}
    (directory / "layer1_manifest.json").write_bytes(encoded(manifest))
    return {"filing": filing, "source_run": str(root)}


def fixture(tmp_path, *, direct=False, cik="0000000001", ticker="TEST"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "raw"
    nine = snapshot(root, cik, f"{cik}-25-000001", "10-Q", "2025-10-30", "2025-09-30",
                    [("2025-01-01", "2025-10-01", 300, 100, 3)])
    annual_periods = [("2025-01-01", "2026-01-01", 400, 100, 4)]
    if direct:
        annual_periods.append(("2025-10-01", "2026-01-01", 100, 100, 1))
    annual = snapshot(root, cik, f"{cik}-26-000001", "10-K", "2026-02-01", "2025-12-31", annual_periods)
    interim = snapshot(root, cik, f"{cik}-26-000002", "10-Q", "2026-10-30", "2026-09-30",
        [("2026-01-01", "2026-04-01", 200, 100, 2), ("2026-04-01", "2026-07-01", 300, 100, 3),
         ("2026-07-01", "2026-10-01", 400, 100, 4)])
    intake = pin(tmp_path / "intake.json", {"complete": True, "filings": [nine, annual, interim]})
    registry = pin(tmp_path / "registry.json", {"companies": [{"cik": cik, "ticker": ticker, "intake": intake}]})
    price, rows, grant = financial()
    rows = [r for r in rows if r["role"] != "diluted_eps_12m"]
    grant["input_ids"].pop("diluted_eps_12m")
    grant.update(cik=cik, security_id="US:"+ticker, stock_class_id="reviewed-single-common-class")
    for r in rows:
        r["cik"] = cik
    document = source(tmp_path / "accounting.htm", '<html><body><p>Common stock EPS uses the numerator attributable to common shareholders and the time weighted shares for each period. All adjustments and classes reconcile on the same split and reporting basis.</p></body></html>')
    citation = {"source_pin": document, "xpath": "/html/body/p", "expected_text": "Common stock EPS uses the numerator attributable to common shareholders and the time weighted shares for each period. All adjustments and classes reconcile on the same split and reporting basis."}
    grant_proposal = pin(tmp_path / "old-grant-proposal.json", {"declarations": [{"role": "common_shares", "cik": cik,
        "share_measure": "OUTSTANDING_COMMON_EX_TREASURY", "dimensions": [], "period_end": grant["financial_anchor"],
        "stock_class_id": grant["stock_class_id"], "split_basis_id": grant["split_basis_id"], "scope_id": grant["financial_scope_id"]}]})
    grant["evidence_pins"] = [pin(tmp_path / "old-grant-review.json", {"schema_version": "price-metrics-root-binding-acceptance-v1",
        "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_TYPED_BINDING", "security_id": grant["security_id"], "proposal": grant_proposal})]
    base = {"schema_version": "price-financial-input-bundle-v1", "financial_as_of": "2026-11-13",
            "observations": rows, "compatibility_grants": [grant],
            "financial_anchors": [{"cik": cik, "period_end": "2026-10-01", "known_on": "2026-10-30"}]}
    base_pin = pin(tmp_path / "base.json", base)
    config = {"schema_version": "common-q4-eps-config-v1", "registry": registry,
              "base_financial_bundle": base_pin, "public_cutoff": "2026-11-13"}
    config.update(basis_inputs(tmp_path, cik, ticker, [nine, annual, interim]))
    config_pin = pin(tmp_path / "config.json", config)
    proposal = propose_q4_eps(config_pin)
    cases = []
    for candidate in proposal["candidates"]:
        names = ["SAME_CLASS_SPLIT_RECAST_BASIS", "COMPATIBLE_SOURCE_VINTAGE", "COMMON_NUMERATOR_ATTRIBUTION",
                 "DIRECT_Q4_RECONCILIATION_COMPONENTS" if direct else "PERIOD_TIME_WEIGHTED_COMMON_SHARES",
                 "CUMULATIVE_DILUTION_ADDITIVITY_PROVEN", "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE", "SOURCE_REPORTING_BASIS_REVIEW_SUPPORTED"]
        fake = dict(candidate, value="1", selected_eps_interval=[".995", "1.005"], selected_source_type="DERIVED_Q4_EPS")
        quarters = _quarter_sources(proposal, fake, "2026-10-01")
        cases.append({"candidate_id": candidate["candidate_id"], "source_fact_keys": candidate["source_fact_keys"],
            "stock_class_id": "reviewed-single-common-class", "split_basis_id": "unadjusted-2026", "financial_scope_id": "issuer-common",
            "weight_method": "DAY", "claims": [{"claim": name, "citations": [dict(citation, cik=cik, accession=accession)
                for accession in sorted({r["accession"] for r in proposal["source_rows"]})]} for name in names],
            "dilution_bridge": {name: [citation] for name in DILUTION_CLAIMS},
            "ttm_source_fact_keys": sorted({key for q in quarters for key in q["source_fact_keys"]})})
    policy = {"schema_version": "common-q4-eps-policy-v1", "rule_version": RULE,
              "reviewer": "ROOT", "status": "APPROVED_GLOBAL_RULE", "approved_at": "2026-11-18T00:00:00+00:00"}
    evidence = {"schema_version": "common-q4-eps-accounting-evidence-v1", "reviewer": "ROOT",
                "status": "REVIEWED_SOURCE_ACCOUNTING_EVIDENCE", "reviewed_at": "2026-11-18T00:01:00+00:00", "cases": cases}
    decision = {"reviewer": "ROOT", "status": "APPROVED_FOR_BOUNDED_IMPLEMENTATION",
        "mode": "CURRENT_EVALUATION_WITH_LAGGED_QUOTE", "quote_session": "2026-11-13",
        "public_financial_information_cutoff": "2026-11-13", "evaluation_as_of": "2026-11-18",
        "decided_at": "2026-11-18T00:00:00+00:00"}
    run = {"schema_version": "common-q4-eps-run-v1", "proposal": pin(tmp_path / "proposal.json", proposal),
           "policy": pin(tmp_path / "policy.json", policy), "accounting_evidence": pin(tmp_path / "evidence.json", evidence),
           "evaluation_decision": pin(tmp_path / "decision.json", decision)}
    return {"run": run, "proposal": proposal, "base": base, "cases": cases, "evidence": evidence,
            "citation": citation, "config": config, "price": price, "policy": policy, "decision": decision}


def run_pin(tmp_path, f):
    f["run"]["accounting_evidence"] = pin(tmp_path / "evidence.json", f["evidence"])
    return pin(tmp_path / "run.json", f["run"])


@pytest.mark.parametrize("direct", [False, True])
def test_qualified_common_basic_diluted_ttm_append_and_exact_replay(tmp_path, direct):
    f = fixture(tmp_path, direct=direct)
    original = copy.deepcopy(f["base"])
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert len(artifact["quarter_results"]) == 2
    assert all(r["status"] == "QUALIFIED" and Decimal(r["value"]) == 1 for r in artifact["quarter_results"])
    assert artifact["quarter_results"][0]["selected_source_type"] == ("REPORTED_Q4_EPS" if direct else "DERIVED_Q4_EPS")
    assert len(artifact["observations"]) == 1
    row = artifact["observations"][0]
    assert Decimal(row["value"]) == 10 and row["ready_on"] == "2026-11-18"
    assert row["known_on"] == "2026-10-30" and row["historical_ready"] is False
    artifact_pin = pin(tmp_path / "artifact.json", artifact)
    assert verify_q4_eps(artifact_pin) == artifact
    bundle = augment_q4_eps_ttm(artifact_pin)
    assert bundle["observations"][:-1] == original["observations"]
    assert f["base"] == original
    assert bundle["compatibility_grants"][0]["ready_on"] == original["compatibility_grants"][0]["ready_on"]
    assert validated_q4_ttm_rows(bundle) == {row["observation_id"]: row}


def test_missing_accounting_evidence_never_numeric_admission(tmp_path):
    f = fixture(tmp_path)
    f["evidence"]["cases"] = []
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert artifact["observations"] == []
    assert {r["reason"] for r in artifact["quarter_results"]} == {"ACCOUNTING_SOURCE_PATTERN_OR_REVIEW_NOT_AVAILABLE"}


@pytest.mark.parametrize("flavor,bridge,reason", [
    ("diluted", "dilution_bridge", "DILUTED_CUMULATIVE_ADDITIVITY_NOT_PROVEN"),
    ("basic", "claims", "ACCOUNTING_CLAIMS_MISSING"),
])
def test_diluted_ifconverted_participating_loss_bridge_not_inferred(tmp_path, flavor, bridge, reason):
    f = fixture(tmp_path)
    candidate = next(c for c in f["proposal"]["candidates"] if c["flavor"] == flavor)
    case = next(c for c in f["cases"] if c["candidate_id"] == candidate["candidate_id"])
    case[bridge] = {} if bridge.endswith("bridge") else []
    result = _qualify(candidate, case)
    assert result["status"] == "HOLD" and result["reason"].startswith(reason)


def test_parent_income_requires_explicit_complete_numerator_bridge(tmp_path):
    f = fixture(tmp_path)
    candidate, case = copy.deepcopy(f["proposal"]["candidates"][0]), copy.deepcopy(f["cases"][0])
    candidate["components"]["FY_numerator"]["sources"][0]["role"] = "parent_numerator"
    assert _qualify(candidate, case)["reason"] == "COMMON_NUMERATOR_COMPLETE_ADJUSTMENT_BRIDGE_REQUIRED"
    case["numerator_bridge"] = {name: [f["citation"]] for name in NUMERATOR_CLAIMS}
    assert _qualify(candidate, case)["status"] == "QUALIFIED"


@pytest.mark.parametrize("w,value,expected", [("0", "0", "HOLD"), ("100", "-1", "QUALIFIED")])
def test_zero_denominator_and_signed_loss(tmp_path, w, value, expected):
    f = fixture(tmp_path, direct=True)
    candidate, case = copy.deepcopy(f["proposal"]["candidates"][0]), f["cases"][0]
    for key, v in (("Q4_shares", w), ("Q4_numerator", str(Decimal(value)*Decimal(w))), ("Q4_eps", value)):
        candidate["components"][key].update(value=v, interval=[v, v])
    result = _qualify(candidate, case)
    assert result["status"] == expected
    if expected == "QUALIFIED":
        assert Decimal(result["value"]) == -1


def test_shop_point_58_reference_57_disjoint_is_fail_not_tolerance(tmp_path):
    f = fixture(tmp_path, direct=True)
    candidate = copy.deepcopy(f["proposal"]["candidates"][1])
    candidate["components"]["Q4_numerator"].update(value="58", interval=["57.99", "58.01"])
    candidate["components"]["Q4_eps"].update(value=".57", interval=[".565", ".575"])
    assert _qualify(candidate, f["cases"][1])["reason"] == "DIRECT_Q4_EPS_ROUNDING_MISMATCH"


def test_rounding_compatible_not_unique_keeps_fixed_point_and_direct_preference(tmp_path):
    f = fixture(tmp_path, direct=True)
    candidate = copy.deepcopy(f["proposal"]["candidates"][1])
    candidate["components"]["Q4_numerator"].update(value="100", interval=["99", "101"])
    candidate["components"]["Q4_eps"].update(value="1.01", interval=["1.005", "1.015"])
    result = _qualify(candidate, f["cases"][1])
    assert result["status"] == "QUALIFIED" and result["reconstructed_value"] == "1"
    assert result["value"] == "1.01" and result["direct_comparison"]["status"] == "ROUNDING_COMPATIBLE"


def test_hidden_split_basis_mismatch_prevents_ttm(tmp_path):
    f = fixture(tmp_path)
    f["cases"][1]["split_basis_id"] = "hidden-pre-split"
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert artifact["observations"] == []
    assert any(r["reason"] == "CURRENT_GRANT_CLASS_SPLIT_SCOPE_MISMATCH" for r in artifact["quarter_results"])


@pytest.mark.parametrize("field,value,reason", [
    ("unit", [["iso4217:EUR"], []], "COMPONENT_UNIT_MISMATCH"),
    ("namespace", "http://lookalike.example/us-gaap/2026", "OFFICIAL_STANDARD_SEMANTICS_NOT_CONFIRMED"),
    ("entity_identifier", "0000000002", "CONTEXT_ENTITY_MISMATCH"),
    ("decimals", None, "SOURCE_ROUNDING_PRECISION_UNKNOWN"),
])
def test_source_units_namespace_entity_precision_fail_closed(tmp_path, field, value, reason):
    f = fixture(tmp_path)
    rows = copy.deepcopy(f["proposal"]["source_rows"])
    for row in rows:
        if row["role"] == "basic_numerator":
            row[field] = value
    result = _select(rows, "0000000001", "2025-01-01", "2026-01-01", "basic_numerator", [])
    assert result["status"] == "HOLD" and result["reason"] == reason


def test_same_accession_precision_duplicate_but_foreign_vintage_or_real_conflict_hold(tmp_path):
    f = fixture(tmp_path)
    row = next(r for r in f["proposal"]["source_rows"] if r["role"] == "basic_numerator" and r["end"] == "2026-01-01")
    row = dict(row, value="400", decimals="0")
    duplicate = dict(row, fact_key="duplicate", value="400.1", decimals="1")
    select = lambda rows: _select(rows, row["cik"], row["start"], row["end"], row["role"], [])
    result = select([row, duplicate])
    assert result["status"] == "AVAILABLE" and result["value"] == "400.1"
    assert len(result["sources"]) == 2
    assert select([row, dict(duplicate, accession="foreign")])["reason"] == "AMBIGUOUS_COMPONENT_SOURCE_IDENTITY"
    assert select([row, dict(duplicate, value="402")])["reason"] == "CONFLICTING_COMPONENT_DUPLICATES"


def test_original_pin_and_ready_boundary_mutations_rejected(tmp_path):
    f = fixture(tmp_path)
    rpin = run_pin(tmp_path, f)
    with pytest.raises(ValueError, match="ready"):
        qualify_q4_eps(rpin, _recorded_at="2026-11-13T12:00:00+00:00")
    artifact = qualify_q4_eps(rpin)
    artifact["observations"][0]["value"] = "999"
    with pytest.raises(ValueError, match="replayed"):
        verify_q4_eps(pin(tmp_path / "mutated.json", artifact))
    Path(f["citation"]["source_pin"]["path"]).write_text("mutated")
    with pytest.raises(ValueError, match="hash"):
        qualify_q4_eps(rpin)


def test_approved_global_grammar_adds_company_without_case_authoring(tmp_path):
    first = fixture(tmp_path / "one", direct=True)
    second = fixture(tmp_path / "two", direct=True, cik="0000000002", ticker="NEW")
    companies = [json.loads(Path(f["config"]["registry"]["path"]).read_text())["companies"][0] for f in (second, first)]
    base = copy.deepcopy(first["base"])
    for k in ("observations", "compatibility_grants", "financial_anchors"):
        base[k] += second["base"][k]
    catalog = {"documents": [d for f in (first, second) for d in json.loads(Path(f["config"]["source_catalog"]["path"]).read_text())["documents"]]}
    # One existing batch can carry both registered identities without new accounting rules.
    batches = [json.loads(Path(f["config"]["basis_price_batch"]["path"]).read_text()) for f in (first, second)]
    batch = copy.deepcopy(batches[0])
    for key in ("securities", "prices"):
        batch[key] += batches[1][key]
    config = dict(first["config"], registry=pin(tmp_path / "both-registry.json", {"companies": companies}),
                  base_financial_bundle=pin(tmp_path / "both-base.json", base),
                  source_catalog=pin(tmp_path / "both-catalog.json", catalog))
    sidecars = [json.loads(Path(b["currency_evidence"]["path"]).read_text()) for b in batches]
    sidecar = copy.deepcopy(sidecars[0])
    sidecar["securities"] += sidecars[1]["securities"]
    sidecar_pin = pin(tmp_path / "both-sidecar.json", sidecar)
    accepted = json.loads(Path(batch["currency_manifest"]["path"]).read_text())
    accepted["artifacts"]["sidecar.json"] = sidecar_pin
    batch.update(currency_evidence=sidecar_pin, currency_manifest=pin(tmp_path / "both-accepted.json", accepted))
    config["basis_price_batch"] = pin(tmp_path / "both-batch.json", batch)
    proposal = propose_q4_eps(pin(tmp_path / "both-config.json", config))
    proposal_pin = pin(tmp_path / "both-proposal.json", proposal)
    documents = [{"cik": r["cik"], "accession": r["accession"], "source_pin": first["citation"]["source_pin"]}
                 for r in proposal["source_rows"]]
    # All companies use the same approved pattern and independent original sources.
    documents = list({(r["cik"], r["accession"]): r for r in documents}.values())
    claim_names = [c["claim"] for c in first["cases"][0]["claims"]]
    grammar = {"schema_version": "common-q4-eps-evidence-grammar-v1", "reviewer": "ROOT",
        "status": "APPROVED_GLOBAL_SOURCE_GRAMMAR", "approved_at": "2026-11-18T00:01:00+00:00",
        "rules": [{"rule_id": "fixture-common-table", "route": "DIRECT_Q4_COMPONENTS", "weight_method": "DAY",
                   "claims": [{"claim": c, "xpath": "//p", "text_pattern": "Common stock EPS"} for c in claim_names]}]}
    automatic = discover_accounting_evidence(proposal_pin, pin(tmp_path / "grammar.json", grammar), pin(tmp_path / "catalog.json", {"documents": documents}))
    assert len(automatic["cases"]) == 4 and automatic["holds"] == []
    run = dict(first["run"], proposal=proposal_pin, accounting_evidence=pin(tmp_path / "auto-evidence.json", automatic))
    artifact = qualify_q4_eps(pin(tmp_path / "auto-run.json", run))
    assert {r["cik"] for r in artifact["observations"]} == {"0000000001", "0000000002"}
    # Registration order never changes discovery content except the explicit config pin.
    registry = pin(tmp_path / "reverse-registry.json", {"companies": list(reversed(companies))})
    reverse = propose_q4_eps(pin(tmp_path / "reverse-config.json", dict(config, registry=registry)))
    assert reverse["candidates"] == proposal["candidates"]
    assert reverse["source_rows"] == proposal["source_rows"]


def evaluation(tmp_path, f, artifact_pin):
    bundle = augment_q4_eps_ttm(artifact_pin)
    bundle_pin = pin(tmp_path / "bundle.json", bundle)
    batch_pin = pin(tmp_path / "batch.json", {"fixture": "price batch"})
    policy = {"schema_version": "eps-current-evaluation-policy-v2", "mode": f["decision"]["mode"],
        "decision": f["run"]["evaluation_decision"], "financial_inputs": bundle_pin, "price_batch": batch_pin,
        "quote_session": "2026-11-13", "public_financial_information_cutoff": "2026-11-13",
        "evaluation_as_of": "2026-11-18", "evaluation_at": NOW.isoformat(),
        "derivations": {"q4_component_derivation": artifact_pin}}
    policy_pin = pin(tmp_path / "evaluation-policy.json", policy)
    approval = pin(tmp_path / "evaluation-approval.json", {"schema_version": "eps-current-evaluation-root-acceptance-v1",
        "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_CURRENT_EVALUATION", "policy": policy_pin,
        "approved_at": NOW.isoformat()})
    declaration = {"policy": policy_pin, "approval": approval}
    return bundle, bundle_pin, batch_pin, declaration


def test_current_lagged_quote_per_ey_band_and_no_historical_backfill(tmp_path):
    f = fixture(tmp_path)
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    apin = pin(tmp_path / "artifact.json", artifact)
    bundle, bpin, batch_pin, declaration = evaluation(tmp_path, f, apin)
    validated = validate_current_evaluation(declaration, bundle_pin=bpin, batch_pin=batch_pin,
        requested="2026-11-18", selected="2026-11-13")
    assert validated["backtest_eligible"] is False
    price = dict(f["price"], trade_date="2026-11-13")
    kwargs = {"cik": "0000000001", "security_id": "US:TEST", "as_of": "2026-11-13",
              "financial_anchor": "2026-10-01", "financial_as_of": "2026-11-13"}
    old = calculate_valuation_metrics(price, bundle["observations"], bundle["compatibility_grants"][0], **kwargs)
    assert next(r for r in old if r["metric_id"] == "per")["status"] == "UNAVAILABLE"
    rows = calculate_valuation_metrics(price, bundle["observations"], bundle["compatibility_grants"][0], **kwargs,
        current_eps_evaluation={"declaration": declaration, "financial_inputs": bpin, "price_batch": batch_pin,
                                "requested_as_of": "2026-11-18"})
    per = next(r for r in rows if r["metric_id"] == "per")
    ey = next(r for r in rows if r["metric_id"] == "earnings_yield")
    assert Decimal(per["value"]) == 10 and Decimal(ey["value"]) == 10
    assert per["eps_source_kind"] == "GOVERNED_Q4_COMPONENT_TTM" and per["historical_ready"] is False
    bands = fixed_multiple_bands(rows, {"per": ["20"]})
    assert Decimal(next(r for r in bands if r["metric_id"] == "fixed_per_band")["value"]) == 200
    mutated = copy.deepcopy(bundle)
    mutated["observations"][-1]["value"] = "99"
    with pytest.raises(ValueError, match="differs"):
        validated_q4_ttm_rows(mutated)


def test_official_table_component_scale_and_locator_validation(tmp_path):
    text = '<html><table><tr><td></td><td>Three Months Ended December 31, 2025</td></tr><tr><td>Q4 common numerator (millions)</td><td>12</td></tr></table></html>'
    sp = source(tmp_path / "source.htm", text)
    doc = html.fromstring(text)
    record = {"source_record_id": "official-n", "cik": "0000000001", "ticker": "TEST",
        "accession": "0000000001-26-000001", "form": "8-K", "filed_date": "2026-02-01",
        "report_date": "2025-12-31", "start": "2025-10-01", "end": "2026-01-01",
        "role": "diluted_numerator", "value": "12000000", "scale": 6, "decimals": "-6",
        "unit": [["iso4217:USD"], []], "dimensions": [], "source_pin": sp,
        "captured_at": NOW.isoformat(), "source_document": "source.htm",
        "source_url": "https://www.sec.gov/Archives/example/source.htm",
        "locator": {"value_xpath": "/html/body/table/tr[2]/td[2]", "row_xpath": "/html/body/table/tr[2]",
                    "raw_cell_text": "12", "row_text": "Q4 common numerator (millions) 12",
                    "table_text_sha256": hashlib.sha256(" ".join(" ".join(doc.xpath('//table')[0].itertext()).split()).encode()).hexdigest(),
                    "headers": ["Q4 common numerator (millions)"]}}
    assert _official(record)["raw_fact_id"] is None
    with pytest.raises(ValueError, match="scale"):
        _official(dict(record, scale=3))


def test_publication_consumes_prepared_component_values_and_expands_saved_evidence(tmp_path):
    from sec_xbrl.screening.price_metric_publication import PriceMetricReader, publish_price_metrics
    from sec_xbrl.screening.price_metric_service import PriceMetricService

    f = fixture(tmp_path)
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    apin = pin(tmp_path / "artifact.json", artifact)
    _, bpin, _, _ = evaluation(tmp_path, f, apin)
    proof = pin(tmp_path / "proof.json", {"fixture": "verified calendar"})
    days = ["2026-11-12", "2026-11-13"]
    calendar = {"schema_version": "verified-us-sessions-v1", "market": "US_EQUITIES", "verified": True,
                "source_pins": [proof], "sessions": days, "coverage_start": days[0], "coverage_end": days[-1]}
    prices = [{"security_id": "US:TEST", "trade_date": day, "as_traded_close": "100", "currency": "USD",
               "split_adj_close": "100", "split_adj_volume": "10", "observation_id": "p-"+day,
               "ready_on": day} for day in days]
    batch = {"schema_version": "price-metric-canonical-batch-v1", "price_batch_calls": 1,
        "prices": prices, "companies": [{"cik": "0000000001", "ticker": "TEST", "security_id": "US:TEST"}],
        "query": {"start_date": days[0], "end_date": days[-1]}, "volume_basis": "TRUE_SPLIT_COMPATIBLE"}
    batch_pin = pin(tmp_path / "publication-batch.json", batch)
    ep = json.loads(Path(tmp_path / "evaluation-policy.json").read_text())
    ep["price_batch"] = batch_pin
    epin = pin(tmp_path / "publication-evaluation.json", ep)
    approval = pin(tmp_path / "publication-approval.json", {"schema_version": "eps-current-evaluation-root-acceptance-v1",
        "reviewer": "ROOT", "status": "APPROVED_FOR_EXACT_CURRENT_EVALUATION", "policy": epin, "approved_at": NOW.isoformat()})
    config = {"schema_version": "screening-price-metrics-config-v1", "price_batch": batch_pin,
        "sessions": pin(tmp_path / "sessions.json", calendar), "financial_inputs": bpin,
        "requested_as_of": "2026-11-18", "price_as_of": "2026-11-13", "session_selection_policy": "EXPLICIT_COMPLETED_SESSION",
        "historical_readiness_policy": "READY_ONLY", "series_start": days[0], "historical_start": days[0],
        "dataset_scope": {"dataset_id": "fixture", "dataset_publication_id": "source", "financial_as_of": "2026-11-13", "dataset_manifest_sha256": "a"*64},
        "fixed_multiples": {"per": ["20"]}, "current_eps_evaluation": {"policy": epin, "approval": approval}}
    output = publish_price_metrics(pin(tmp_path / "publication-config.json", config), tmp_path / "published")
    reader = PriceMetricReader({k: output[k] for k in ("path", "sha256")})
    latest = reader.query(metric_ids=["per"])["rows"][0]
    assert Decimal(latest["value"]) == 10 and latest["historical_ready"] is False
    assert all(r["status"] == "UNAVAILABLE" for r in reader.query(mode="series", metric_ids=["per"])["rows"])
    evidence = reader.evidence("0000000001", latest["observation_id"])
    assert evidence["q4_component_evidence"]["quarters"][0]["flavor"] == "diluted"
    service = PriceMetricService(reader, tmp_path / "private.sqlite")
    saved = service.save(kind="RESULT", operation="query", request={"metric_ids": ["per"]}, title="prepared EPS")
    assert PriceMetricService(reader, tmp_path / "private.sqlite").reopen(saved["id"])["result"] == saved["result"]


def test_scope_grammar_requires_each_selected_filing_and_rejects_missing_scope(tmp_path):
    f = fixture(tmp_path, direct=True)
    proposal_pin = f["run"]["proposal"]
    annual = source(tmp_path / "annual-policy.htm", "<html><body><p>Annual common share policy</p><table><tr><td>Q4 components reconciled</td></tr></table></body></html>")
    nine = source(tmp_path / "interim-policy.htm", "<html><body><p>Quarterly common share policy</p></body></html>")
    documents = []
    for r in f["proposal"]["source_rows"]:
        if (r["cik"], r["accession"]) not in {(d["cik"], d["accession"]) for d in documents}:
            documents.append({"cik": r["cik"], "accession": r["accession"], "source_pin": annual if r["form"] == "10-K" else nine})
    grammar = {"schema_version": "common-q4-eps-evidence-grammar-v1", "reviewer": "ROOT",
        "status": "APPROVED_GLOBAL_SOURCE_GRAMMAR", "approved_at": "2026-11-18T00:01:00+00:00",
        "rules": [{"rule_id": "scope-rule", "route": "DIRECT_Q4_COMPONENTS", "claims": [
            {"claim": "SAME_CLASS_SPLIT_RECAST_BASIS", "xpath": "//p", "text_pattern": "Annual common", "filing_scope": "ANNUAL_FILINGS"},
            {"claim": "COMPATIBLE_SOURCE_VINTAGE", "xpath": "//p", "text_pattern": "Quarterly common", "filing_scope": "QUARTERLY_FILINGS"},
            {"claim": "COMMON_NUMERATOR_ATTRIBUTION", "xpath": "//table", "text_pattern": "Q4 components", "filing_scope": "DIRECT_Q4_FILINGS"},
            {"claim": "DIRECT_Q4_RECONCILIATION_COMPONENTS", "xpath": "//table", "text_pattern": "Q4 components", "filing_scope": "COMPONENT_FILINGS"},
        ]}]}
    catalog = pin(tmp_path / "catalog.json", {"documents": documents})
    result = discover_accounting_evidence(proposal_pin, pin(tmp_path / "grammar.json", grammar), catalog)
    assert len(result["cases"]) == 2
    grammar["rules"][0]["claims"][0]["filing_scope"] = "COMPONENT_FILINGS"
    grammar["rules"][0]["claims"][0]["text_pattern"] = "Quarterly common"
    rejected = discover_accounting_evidence(proposal_pin, pin(tmp_path / "bad-grammar.json", grammar), catalog)
    assert rejected["cases"] == []
    assert any(d["reason"] == "SOURCE_PATTERN_NOT_MATCHED_IN_EVERY_SCOPED_FILING" for h in rejected["holds"] for d in h.get("details", []))


def test_full_dimension_identity_and_alternative_prefix_have_semantic_meaning(tmp_path):
    f = fixture(tmp_path)
    row = next(r for r in f["proposal"]["source_rows"] if r["role"] == "basic_numerator" and r["end"] == "2026-01-01")
    alternate = dict(row, qname="otherprefix:NetIncomeLossAvailableToCommonStockholdersBasic")
    result = _select([alternate], row["cik"], row["start"], row["end"], row["role"], [])
    assert result["status"] == "AVAILABLE"
    alternate["dimensions"] = [{"axis": "class", "member": "A"}]
    assert _select([alternate], row["cik"], row["start"], row["end"], row["role"], [])["status"] == "MISSING"


def test_missing_ttm_filing_citation_and_diluted_below_basic_are_not_admitted(tmp_path):
    f = fixture(tmp_path, direct=True)
    ttm_claim = next(c for c in f["cases"][1]["claims"] if c["claim"] == "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE")
    ttm_claim["citations"] = ttm_claim["citations"][:1]
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert artifact["observations"] == []
    assert any(h["reason"] == "TTM_SOURCE_FILING_EVIDENCE_COVERAGE_INCOMPLETE" for h in artifact["holds"])


def test_rounding_boundary_contact_is_not_a_display_reconciliation(tmp_path):
    f = fixture(tmp_path, direct=True)
    candidate = copy.deepcopy(f["proposal"]["candidates"][1])
    candidate["components"]["Q4_numerator"].update(value="58", interval=["57.5", "58.5"])
    candidate["components"]["Q4_eps"].update(value=".57", interval=[".565", ".575"])
    assert _qualify(candidate, f["cases"][1])["status"] == "FAIL"


def test_korean_evaluation_day_does_not_backdate_actual_utc_ready_time(tmp_path, monkeypatch):
    f = fixture(tmp_path)
    actual = datetime(2026, 11, 17, 16, tzinfo=UTC)
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction._now", lambda: actual)
    f["decision"].update(evaluation_timezone="Asia/Seoul", decided_at="2026-11-17T15:00:00+00:00")
    f["policy"]["approved_at"] = "2026-11-17T15:00:00+00:00"
    f["evidence"]["reviewed_at"] = "2026-11-17T15:01:00+00:00"
    f["run"]["policy"] = pin(tmp_path / "policy.json", f["policy"])
    f["run"]["evaluation_decision"] = pin(tmp_path / "decision.json", f["decision"])
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert artifact["prepared_at"] == actual.isoformat()
    assert artifact["observations"][0]["ready_on"] == "2026-11-17"
    assert artifact["quarter_results"][0]["cumulative_reconstruction_diagnostic"]["accounting_qualified"] is False
    apin = pin(tmp_path / "artifact.json", artifact)
    _, bpin, batch, declaration = evaluation(tmp_path, f, apin)
    policy = json.loads(Path(declaration["policy"]["path"]).read_text())
    policy.update(evaluation_timezone="Asia/Seoul", evaluation_at=actual.isoformat())
    policy_pin = pin(tmp_path / "kst-evaluation.json", policy)
    approval = {"schema_version": "eps-current-evaluation-root-acceptance-v1", "reviewer": "ROOT",
        "status": "APPROVED_FOR_EXACT_CURRENT_EVALUATION", "policy": policy_pin, "approved_at": actual.isoformat()}
    declaration = {"policy": policy_pin, "approval": pin(tmp_path / "kst-approval.json", approval)}
    assert validate_current_evaluation(declaration, bundle_pin=bpin, batch_pin=batch,
        requested="2026-11-18", selected="2026-11-13")["evaluation_timezone"] == "Asia/Seoul"


def basis_inputs(tmp_path, cik, ticker, filings):
    sid = "US:"+ticker
    security = {"security_id": sid, "cik": cik, "ticker": ticker, "yahoo_symbol": ticker}
    cover = source(tmp_path / "cover.htm", '<html xmlns:dei="http://xbrl.sec.gov/dei/2026"><body>'
        f'<ix:nonNumeric name="dei:EntityCentralIndexKey">{cik}</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:Security12bTitle">Common Stock, par value $0.01</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:Security12bTitle">3.5% Senior Notes</ix:nonNumeric></body></html>')
    documents = []
    for filing in filings:
        directory = Path(filing["source_run"]) / "snapshots" / cik / filing["filing"]["accession"].replace("-", "")
        concepts = {c["raw_concept_id"]: c for c in pl.read_parquet(directory / "concept.parquet").to_dicts()}
        contexts = pl.read_parquet(directory / "context.parquet").to_dicts()
        units = pl.read_parquet(directory / "unit.parquet").to_dicts()
        parts = [Path(cover["path"]).read_text().replace('</body></html>', '')]
        # Preserve source Context and Unit elements, as an actual inline document does.
        for context in contexts:
            from datetime import date, timedelta
            end = (date.fromisoformat(context["end_date"])-timedelta(days=1)).isoformat()
            parts.append(f'<xbrli:context id="{context["context_id"]}"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{context["start_date"]}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        for unit in units:
            num, den = json.loads(unit["numerator_measures"]), json.loads(unit["denominator_measures"])
            if den:
                measures = '<xbrli:divide><xbrli:unitNumerator>'+''.join(f'<xbrli:measure>{m}</xbrli:measure>' for m in num)+'</xbrli:unitNumerator><xbrli:unitDenominator>'+''.join(f'<xbrli:measure>{m}</xbrli:measure>' for m in den)+'</xbrli:unitDenominator></xbrli:divide>'
            else:
                measures = ''.join(f'<xbrli:measure>{m}</xbrli:measure>' for m in num)
            parts.append(f'<xbrli:unit id="{unit["unit_id"]}">{measures}</xbrli:unit>')
        facts = pl.read_parquet(directory / "fact.parquet").to_dicts()
        for context in contexts:
            selected = {fact["raw_concept_id"]: fact for fact in facts if fact["context_id"] == context["context_id"]}
            def ix(key, selected=selected, concepts=concepts):
                fact = selected[key]
                return f'<ix:nonFraction name="{concepts[fact["raw_concept_id"]]["qname"]}" contextRef="{fact["context_id"]}" unitRef="{fact["unit_id"]}">{fact["value_numeric"]}</ix:nonFraction>'
            parts.append('<table><tr><td>Net income</td><td>'+ix("basicnumerator")+'</td><td>'+ix("dilutednumerator")+'</td></tr>'
                '<tr><td>Basic earnings per share</td><td>'+ix("basiceps")+'</td></tr>'
                '<tr><td>Diluted earnings per share</td><td>'+ix("dilutedeps")+'</td></tr>'
                '<tr><td>Weighted-average shares used in computation of earnings per share:</td></tr>'
                '<tr><td>Basic</td><td>'+ix("basicshares")+'</td></tr>'
                '<tr><td>Diluted</td><td>'+ix("dilutedshares")+'</td></tr></table>')
        parts.append('</body></html>')
        text = ''.join(parts).replace('<html ', '<html xmlns:us-gaap="http://fasb.org/us-gaap/2026" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" ')
        documents.append({"cik": cik, "accession": filing["filing"]["accession"],
                          "source_pin": source(tmp_path / (filing["filing"]["accession"]+'.htm'), text)})
    catalog = pin(tmp_path / "source-catalog.json", {"documents": documents})
    p1 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    p2 = int(datetime(2026, 11, 16, tzinfo=UTC).timestamp())
    days = ["2025-01-02", "2026-11-13"]
    raw = {"chart": {"result": [{"meta": {"symbol": ticker, "exchangeTimezoneName": "America/New_York"},
        "timestamp": [int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp()) for day in days], "events": {"splits": {}}}], "error": None}}
    payload = encoded(raw)
    compressed = gzip.compress(payload)
    raw_path = tmp_path / "price-raw.json.gz"
    raw_path.write_bytes(compressed)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=splits&includeAdjustedClose=false"
    checkpoint = {"security_id": sid, "yahoo_symbol": ticker, "status": "ok", "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "requested_period1": p1, "url": url}
    checkpoint_pin = pin(tmp_path / "checkpoint.json", checkpoint)
    package = tmp_path / "supplier"
    (package / "adapters").mkdir(parents=True)
    fixture_pin = source(package / "price.py", "synthetic accepted supplier fixture")
    dependency_pins = {relative: source(package / relative, "synthetic pinned supplier dependency")
                       for relative in ("__init__.py", "adapters/yahoo_price.py", "security.py")}
    inventory_pin = pin(tmp_path / "price-inventory.json", {"events": "splits", "period1": p1, "period2": p2})
    reviewed = pin(tmp_path / "reviewed-actions.json", {"schema_version": 1, "actions": []})
    capture = {"security_id": sid, "cik": cik, "checkpoint_path": checkpoint_pin["path"], "checkpoint_sha256": checkpoint_pin["sha256"],
        "raw_path": str(raw_path), "compressed_raw_sha256": hashlib.sha256(compressed).hexdigest(),
        "raw_sha256": checkpoint["raw_sha256"], "requested_period1": p1, "request_url": url}
    sidecar = {"schema_contract": "price-capture-evidence.v1", "factor_horizon_period2": p2,
        "input_pins": {"price.parquet": fixture_pin, "security.parquet": fixture_pin,
            "inventory_manifest": inventory_pin, "reviewed_actions": reviewed, "normalizer_source": fixture_pin}, "securities": [capture]}
    sidecar_pin = pin(tmp_path / "sidecar.json", sidecar)
    accepted = pin(tmp_path / "accepted-price.json", {"status": "accepted", "manifest_contract": "price-capture-evidence-delivery.v1",
        "artifacts": {"sidecar.json": sidecar_pin}})
    batch = {"schema_version": "price-metric-canonical-batch-v1", "query": {"start_date": "2022-10-01", "end_date": "2026-11-13"},
        "securities": [security], "prices": [{"security_id": sid, "trade_date": day, "split_factor": 1} for day in days],
        "currency_evidence": sidecar_pin, "currency_manifest": accepted,
        "lineage": {"sha256": fixture_pin["sha256"], "security_sha256": fixture_pin["sha256"]}}
    return {"source_catalog": catalog, "basis_price_batch": pin(tmp_path / "basis-batch.json", batch),
            "basis_normalizer_dependencies": dependency_pins}


def test_actual_amzn_official_layout_period_mapping_closed_equation_and_precision():
    from sec_xbrl.metrics.q4_eps_reconstruction import _closed_eps_section

    root = Path(__file__).parents[1] / "fixtures/q4_eps"
    metadata = json.loads((root / "amzn-2025-q4-source.json").read_text())
    verified = {}
    for original in metadata["records"]:
        record = dict(original, source_pin={"path": str(root / original["source_file"]), "sha256": original["source_sha256"]})
        row = _official(record)
        verified[row["role"]] = Decimal(row["value"])
        doc = html.fromstring((root / original["source_file"]).read_bytes())
        assert _closed_eps_section(doc.xpath('//table')[0])["status"] == "VERIFIED"
        with pytest.raises(ValueError, match="period"):
            _official(dict(record, start="2025-01-01"))  # Q4 cell cannot claim the FY column.
    assert verified == {"basic_numerator": Decimal(21192000000), "diluted_numerator": Decimal(21192000000),
                        "basic_shares": Decimal(10709000000), "diluted_shares": Decimal(10863000000),
                        "basic_eps": Decimal("1.98"), "diluted_eps": Decimal("1.95")}
    table = doc.xpath('//table')[0]
    allocation = html.fromstring('<tr><td colspan="3">Income allocated to participating securities</td><td>20</td></tr>')
    table.insert(4, allocation)
    assert _closed_eps_section(table)["status"] == "HOLD"


def test_official_date_namespace_and_equity_cover_ignore_debt_but_reject_multiple_classes(tmp_path):
    from sec_xbrl.metrics.q4_eps_reconstruction import _single_common_cover

    f = fixture(tmp_path)
    row = next(r for r in f["proposal"]["source_rows"] if r["role"] == "basic_numerator")
    row = dict(row, namespace="http://fasb.org/us-gaap/2021-01-31")
    assert _select([row], row["cik"], row["start"], row["end"], row["role"], [])["status"] == "AVAILABLE"
    catalog = json.loads(Path(f["config"]["source_catalog"]["path"]).read_text())
    entry = catalog["documents"][0]
    path = Path(entry["source_pin"]["path"])
    text = path.read_text().replace("http://xbrl.sec.gov/dei/2026", "http://xbrl.sec.gov/dei/2021-01-31")
    entry["source_pin"] = source(tmp_path / "date-dei.htm", text)
    assert _single_common_cover([entry], (entry["cik"], entry["accession"]))["status"] == "VERIFIED"
    entry["source_pin"] = source(tmp_path / "class-dei.htm", text.replace("3.5% Senior Notes", "Class B Common Stock"))
    assert _single_common_cover([entry], (entry["cik"], entry["accession"]))["status"] == "HOLD"


def projection_acceptance(tmp_path, proposal, proposal_pin):
    review = pin(tmp_path / "independent-projection-review.json", {"status": "PASS", "proposal": proposal_pin,
        "scope": "PRODUCT_RAW_SOURCE_PROJECTION"})
    return pin(tmp_path / "projection-acceptance.json", {"schema_version": "common-q4-eps-source-projection-acceptance-v1",
        "reviewer": "ROOT", "status": "ACCEPTED_EXACT_PRODUCT_SOURCE_PROJECTION", "proposal": proposal_pin,
        "config": proposal["config"], "snapshot_inventory_sha256": identity(proposal["snapshots"]),
        "producer": {"kind": "EMBEDDED_PRODUCT_SOURCE_SHA256", "sha256": proposal["producer_sha256"]},
        "independent_verification": review, "approved_at": NOW.isoformat()})


def test_accepted_product_projection_skips_full_reextract_but_hashes_selected_raw_closure(tmp_path, monkeypatch):
    f = fixture(tmp_path)
    receipt = projection_acceptance(tmp_path, f["proposal"], f["run"]["proposal"])
    f["run"]["source_projection_acceptance"] = receipt
    def forbidden_extract(*_args):
        raise AssertionError("accepted source projection must not re-extract the full Raw corpus")
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction.propose_q4_eps", forbidden_extract)
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert len(artifact["observations"]) == 1
    first_snapshot = f["proposal"]["snapshots"][0]
    raw = Path(first_snapshot["manifest"]["path"]).parent / "fact.parquet"
    raw.write_bytes(raw.read_bytes()+b"mutation")
    with pytest.raises(ValueError, match="hash"):
        qualify_q4_eps(run_pin(tmp_path, f))


def test_accepted_projection_reuse_extracts_only_new_registered_company(tmp_path, monkeypatch):
    import sec_xbrl.metrics.q4_eps_reconstruction as module

    first = fixture(tmp_path / "one")
    second = fixture(tmp_path / "two", cik="0000000002", ticker="NEW")
    receipt = projection_acceptance(tmp_path, first["proposal"], first["run"]["proposal"])
    companies = [json.loads(Path(f["config"]["registry"]["path"]).read_text())["companies"][0] for f in (first, second)]
    config = dict(first["config"], registry=pin(tmp_path / "registry.json", {"companies": companies}),
        base_product_projection=first["run"]["proposal"], base_projection_acceptance=receipt)
    loaded = []
    original = module._load_declared_cohort_snapshot
    def load(directory, cik, accession):
        loaded.append(cik)
        return original(directory, cik, accession)
    monkeypatch.setattr(module, "_load_declared_cohort_snapshot", load)
    reused = propose_q4_eps(pin(tmp_path / "reuse-config.json", config))
    assert loaded == ["0000000002"]*3
    assert len(reused["registered_companies"]) == 2
    assert [r for r in reused["source_rows"] if r["cik"] == "0000000001"] == first["proposal"]["source_rows"]


def test_indexed_source_selection_is_byte_equal_for_every_retained_fixture_scope(tmp_path):
    from sec_xbrl.metrics.q4_eps_reconstruction import _selection_index

    f = fixture(tmp_path, direct=True)
    rows = f["proposal"]["source_rows"]
    indexed = _selection_index(rows)
    for row in rows:
        args = row["cik"], row["start"], row["end"], row["role"], row["dimensions"]
        assert encoded(_select(rows, *args)) == encoded(_select(indexed, *args))


def test_basis_detects_visible_hidden_and_comparative_numerator_conflict(tmp_path):
    from sec_xbrl.metrics.q4_eps_reconstruction import _comparative_conflicts, _visible_raw_binding

    f = fixture(tmp_path)
    row = next(r for r in f["proposal"]["source_rows"] if r["role"] == "basic_numerator")
    catalog = json.loads(Path(f["config"]["source_catalog"]["path"]).read_text())
    assert _visible_raw_binding(row, catalog["documents"])["status"] == "VERIFIED"
    entries = [d for d in catalog["documents"] if d["accession"] == row["accession"]]
    for entry in entries:
        text = Path(entry["source_pin"]["path"]).read_text().replace('<ix:nonFraction ', '<ix:nonFraction style="display:none" ')
        entry["source_pin"] = source(tmp_path / "hidden.htm", text)
    assert _visible_raw_binding(row, entries)["status"] == "HOLD"
    peer = dict(row, accession="later-comparative", fact_key="changed-numerator", value="999", decimals="INF")
    assert _comparative_conflicts({"source_rows": [row, peer]}, [row])[0]["comparative_fact_key"] == "changed-numerator"


def test_literal_ix_continuation_policy_citations_use_resolvable_exact_xpath(tmp_path):
    from sec_xbrl.metrics.q4_eps_reconstruction import _cite, _xpath

    text = '<html><body><ix:continuation>Other note</ix:continuation><ix:continuation><ix:nonNumeric>Common stock EPS uses time weighted shares.</ix:nonNumeric></ix:continuation></body></html>'
    document = source(tmp_path / "inline-policy.htm", text)
    doc = html.fromstring(text)
    node = doc.xpath("//*[name()='ix:nonnumeric']")[0]
    xpath = _xpath(node)
    assert "*[name()='ix:continuation'][2]" in xpath
    assert doc.xpath(xpath) == [node]
    _cite([{"source_pin": document, "xpath": xpath, "expected_text": "Common stock EPS uses time weighted shares."}])
    with pytest.raises(ValueError, match="locator/text"):
        _cite([{"source_pin": document, "xpath": xpath, "expected_text": "Different policy"}])


def test_verified_artifact_cache_returns_copies_and_detects_source_mutation(tmp_path, monkeypatch):
    f = fixture(tmp_path)
    f["run"]["source_projection_acceptance"] = projection_acceptance(tmp_path, f["proposal"], f["run"]["proposal"])
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    apin = pin(tmp_path / "artifact.json", artifact)
    first = verify_q4_eps(apin)
    first["observations"][0]["value"] = "poisoned caller copy"
    def no_replay(*_args, **_kwargs):
        raise AssertionError("unchanged verified artifact should reuse its replay")
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction.qualify_q4_eps", no_replay)
    assert Decimal(verify_q4_eps(apin)["observations"][0]["value"]) == 10
    Path(f["citation"]["source_pin"]["path"]).write_text("mutated source after cache")
    with pytest.raises(ValueError, match="hash"):
        verify_q4_eps(apin)


@pytest.mark.parametrize("event_year,expected", [(2025, "HOLD"), (2022, "QUALIFIED")])
def test_basis_checks_raw_events_even_when_canonical_factor_is_one(tmp_path, event_year, expected):
    f = fixture(tmp_path)
    batch = json.loads(Path(f["config"]["basis_price_batch"]["path"]).read_text())
    sidecar = json.loads(Path(batch["currency_evidence"]["path"]).read_text())
    capture = sidecar["securities"][0]
    payload = json.loads(gzip.decompress(Path(capture["raw_path"]).read_bytes()))
    ts = int(datetime(event_year, 6, 1, 15, tzinfo=UTC).timestamp())
    payload["chart"]["result"][0]["events"]["splits"] = {str(ts): {"date": ts, "numerator": 2, "denominator": 1, "splitRatio": "2:1"}}
    blob = encoded(payload)
    compressed = gzip.compress(blob)
    Path(capture["raw_path"]).write_bytes(compressed)
    capture.update(compressed_raw_sha256=hashlib.sha256(compressed).hexdigest(), raw_sha256=hashlib.sha256(blob).hexdigest())
    checkpoint = json.loads(Path(capture["checkpoint_path"]).read_text())
    checkpoint["raw_sha256"] = capture["raw_sha256"]
    cp = pin(Path(capture["checkpoint_path"]), checkpoint)
    capture["checkpoint_sha256"] = cp["sha256"]
    sidecar_pin = pin(tmp_path / "event-sidecar.json", sidecar)
    accepted = json.loads(Path(batch["currency_manifest"]["path"]).read_text())
    accepted["artifacts"]["sidecar.json"] = sidecar_pin
    batch.update(currency_evidence=sidecar_pin, currency_manifest=pin(tmp_path / "event-accepted.json", accepted))
    config = dict(f["config"], basis_price_batch=pin(tmp_path / "event-batch.json", batch))
    proposal = propose_q4_eps(pin(tmp_path / "event-config.json", config))
    f["run"]["proposal"] = pin(tmp_path / "event-proposal.json", proposal)
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    assert {r["status"] for r in artifact["quarter_results"]} == {expected}
    if expected == "HOLD":
        assert {r["reason"] for r in artifact["quarter_results"]} == {"SPLIT_OR_UNKNOWN_CANDIDATE_IN_EPS_BASIS_WINDOW"}


def test_prepared_q4_reader_filters_basic_and_holds_without_recalculation(tmp_path, monkeypatch):
    import test_price_metric_publication

    from sec_xbrl.screening.price_metric_publication import PriceMetricReader

    reader, _, _ = test_price_metric_publication.publication(tmp_path)
    assert reader.q4_eps("0000000001", "basic")["reason"] == "COMMON_Q4_EPS_ARTIFACT_NOT_PUBLISHED"
    artifact = {"schema_version": "governed-common-q4-eps-v1", "source_projection": {"path": "/not-read-by-consumer", "sha256": "a"*64},
        "prepared_at": NOW.isoformat(), "public_cutoff": "2026-11-13", "holds": [],
        "quarter_results": [{"cik": "0000000001", "flavor": "basic", "status": "HOLD", "reason": "SOURCE_GRAMMAR_UNSUPPORTED"},
                            {"cik": "0000000001", "flavor": "diluted", "status": "QUALIFIED", "value": "1"}]}
    apin = pin(tmp_path / "prepared-only-q4.json", artifact)
    manifest = dict(reader.manifest)
    manifest["source_pins"] = dict(manifest["source_pins"], q4_component_derivation=apin)
    prepared = PriceMetricReader(pin(tmp_path / "prepared-only-manifest.json", manifest))
    def no_calculation(*_args, **_kwargs):
        raise AssertionError("consumer must read prepared values")
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction.verify_q4_eps", no_calculation)
    result = prepared.q4_eps("0000000001", "basic")
    assert result["rows"] == artifact["quarter_results"][:1]
    result["rows"][0]["status"] = "caller mutation"
    assert prepared.q4_eps("0000000001", "basic")["rows"][0]["status"] == "HOLD"
    assert prepared.q4_eps("0000000001", "diluted")["rows"][0]["value"] == "1"
    with pytest.raises(ValueError, match="company"):
        prepared.q4_eps("0000000999")


def test_current_only_component_eps_never_enters_history_even_after_actual_ready(tmp_path):
    f = fixture(tmp_path)
    artifact = qualify_q4_eps(run_pin(tmp_path, f))
    bundle = augment_q4_eps_ttm(pin(tmp_path / "artifact.json", artifact))
    price = dict(f["price"], trade_date="2026-11-20", ready_on="2026-11-20")
    rows = calculate_valuation_metrics(price, bundle["observations"], bundle["compatibility_grants"][0],
        cik="0000000001", security_id="US:TEST", as_of="2026-11-20", financial_as_of="2026-11-20", financial_anchor="2026-10-01")
    selected = [r for r in rows if r["metric_id"] in {"per", "earnings_yield"}]
    assert {r["reason"] for r in selected} == {"CURRENT_Q4_EPS_EVALUATION_REQUIRED"}
    assert all(r["status"] == "UNAVAILABLE" and r["historical_ready"] is False for r in selected)
    assert all(r["backtest_eligible"] is False for r in selected)


def test_only_ttm_claim_can_skip_an_empty_scope_without_qualifying_current_ttm(tmp_path):
    f = fixture(tmp_path, direct=True)
    base = copy.deepcopy(f["base"])
    base["compatibility_grants"][0]["financial_anchor"] = "2026-01-01"
    config = dict(f["config"], base_financial_bundle=pin(tmp_path / "other-anchor-base.json", base))
    proposal = copy.deepcopy(f["proposal"])
    proposal["config"] = pin(tmp_path / "other-anchor-config.json", config)
    proposal_pin = pin(tmp_path / "other-anchor-proposal.json", proposal)
    documents = [{"cik": r["cik"], "accession": r["accession"], "source_pin": f["citation"]["source_pin"]}
                 for r in proposal["source_rows"]]
    documents = list({(d["cik"], d["accession"]): d for d in documents}.values())
    grammar = {"schema_version": "common-q4-eps-evidence-grammar-v1", "reviewer": "ROOT",
        "status": "APPROVED_GLOBAL_SOURCE_GRAMMAR", "approved_at": "2026-11-18T00:01:00+00:00",
        "rules": [{"rule_id": "local-q4-with-optional-current-ttm", "route": "DIRECT_Q4_COMPONENTS", "claims": [
            {"claim": c["claim"], "xpath": "//p", "text_pattern": "Common stock EPS"}
            for c in f["cases"][0]["claims"]]}]}
    ttm = next(c for c in grammar["rules"][0]["claims"] if c["claim"] == "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE")
    ttm.update(filing_scope="TTM_FILINGS", optional_if_scope_empty=True)
    catalog = pin(tmp_path / "optional-catalog.json", {"documents": documents})
    automatic = discover_accounting_evidence(proposal_pin, pin(tmp_path / "optional-grammar.json", grammar), catalog)
    assert len(automatic["cases"]) == 2
    assert all("TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" not in {c["claim"] for c in case["claims"]} for case in automatic["cases"])
    grammar["rules"][0]["claims"][0]["optional_if_scope_empty"] = True
    with pytest.raises(ValueError, match="only the TTM"):
        discover_accounting_evidence(proposal_pin, pin(tmp_path / "invalid-optional-grammar.json", grammar), catalog)


def test_explicit_common_numerator_tag_without_a_closed_visible_equation_is_hold(tmp_path):
    from sec_xbrl.metrics.q4_eps_reconstruction import _source_equation_gate

    f = fixture(tmp_path, direct=True)
    catalog = json.loads(Path(f["config"]["source_catalog"]["path"]).read_text())
    for entry in catalog["documents"]:
        doc = html.fromstring(Path(entry["source_pin"]["path"]).read_bytes())
        for table in doc.xpath('//table'):
            table.insert(1, html.fromstring('<tr><td>Income allocated to participating securities</td><td>20</td></tr>'))
        entry["source_pin"] = source(tmp_path / (entry["accession"]+"-allocation.htm"), html.tostring(doc, encoding="unicode"))
    config = dict(f["config"], source_catalog=pin(tmp_path / "allocation-catalog.json", catalog))
    result = _source_equation_gate(f["proposal"]["candidates"][0], config)
    assert result["status"] == "HOLD" and result["bindings"] == []
