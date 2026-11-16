from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_company_valuation_readiness import pin

from sec_xbrl.metrics.company_valuation_readiness import propose_bindings
from sec_xbrl.metrics.market_inputs import pinned_json
from sec_xbrl.metrics.price_financial_inputs import bind_financial_inputs


def share_candidate(qname="us-gaap:CommonStockSharesOutstanding", oid="shares", value="10"):
    return {"cik": "0000000001", "observation_id": oid, "qname": qname, "value": value,
        "status": "AVAILABLE_REPORTED", "filed_date": "2026-10-01", "period_class": "INSTANT",
        "start": None, "end": "2026-10-01", "dimensions": [], "raw_dimensions": [], "unit_kind": "shares",
        "source": {"source_filing_id": "filing", "selected_source_fact_id": "fact-" + oid}}


def declaration(proof):
    return {"role": "common_shares", "cik": "0000000001", "currency": "USD", "scope_id": "common",
        "stock_class_id": "class", "split_basis_id": "split", "known_on": "2026-10-01", "ready_on": None,
        "period_class": "INSTANT", "period_start": None, "period_end": "2026-10-01", "dimensions": [],
        "candidate_ids": ["shares"], "formula": "DIRECT", "evidence_pins": [proof],
        "share_measure": "OUTSTANDING_COMMON_EX_TREASURY"}


@pytest.mark.parametrize("qname", ["us-gaap:CommonStockSharesIssued", "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
                                  "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"])
def test_known_issued_and_weighted_sources_cannot_be_direct_actual_shares(tmp_path, qname):
    proof = pin(tmp_path / "proof.json", {"fixture": "review"})
    with pytest.raises(ValueError, match="not actual outstanding"):
        bind_financial_inputs([share_candidate(qname)], [declaration(proof)])


def test_reviewed_custom_actual_share_qname_is_preserved(tmp_path):
    proof = pin(tmp_path / "proof.json", {"fixture": "review"})
    row, = bind_financial_inputs([share_candidate("custom:ActualCommonSharesOutstanding")], [declaration(proof)])
    assert row["value"] == "10"
    assert row["source_refs"][0]["qname"] == "custom:ActualCommonSharesOutstanding"


@pytest.mark.parametrize("mutation", [None, "order", "filing", "end", "raw-dimensions", "unit"])
def test_actual_issued_minus_treasury_requires_exact_quantity_scope(tmp_path, mutation):
    proof = pin(tmp_path / "proof.json", {"fixture": "review"})
    issued = share_candidate("us-gaap:CommonStockSharesIssued", "issued", "10")
    treasury = share_candidate("us-gaap:TreasuryStockCommonShares", "treasury", "3")
    declared = declaration(proof) | {"formula": "SUBTRACT", "candidate_ids": ["issued", "treasury"]}
    if mutation == "order":
        declared["candidate_ids"].reverse()
    elif mutation == "filing":
        treasury["source"]["source_filing_id"] = "other-filing"
    elif mutation == "end":
        treasury["end"] = "2026-07-01"
    elif mutation == "raw-dimensions":
        treasury["raw_dimensions"] = [{"axis": "class", "member": "other-class"}]
    elif mutation == "unit":
        treasury.pop("unit_kind")
        treasury["unit_numerator_measures"] = ["iso4217:USD"]
        treasury["unit_denominator_measures"] = []
    if mutation:
        with pytest.raises(ValueError):
            bind_financial_inputs([issued, treasury], [declared])
    else:
        row, = bind_financial_inputs([issued, treasury], [declared])
        assert row["value"] == "7"
        assert [r["qname"] for r in row["source_refs"] if r.get("qname")] == [issued["qname"], treasury["qname"]]


def role_plan(tmp_path):
    proof = pin(tmp_path / "proof.json", {"fixture": "source proof, no approval"})
    d = declaration(proof)
    d.pop("evidence_pins")
    config = {"schema_version": "company-valuation-role-plan-v1", "candidate_pins": [pin(tmp_path / "candidates.json", [share_candidate()])],
        "companies": [{"cik": "0000000001", "security_id": "US:TEST", "grant_constraints": {"price_split_factor": "1"},
                       "declarations": [d]}]}
    return config


def test_explicit_role_plan_outputs_proof_without_approval_or_typed_values(tmp_path):
    config = role_plan(tmp_path)
    result = propose_bindings(pin(tmp_path / "config.json", config))
    proposal, = result["proposals"]
    assert proposal["status"] == result["status"] == "PROPOSAL_NOT_APPROVED"
    assert proposal["schema_version"] == "price-financial-binding-proposal-v1"
    assert proposal["declarations"] == config["companies"][0]["declarations"]
    assert proposal["source_role_proofs"][0]["source_inputs"][0]["source_fact_id"] == "fact-shares"
    assert "observations" not in result and "value" not in proposal["declarations"][0]
    bad = copy.deepcopy(config)
    bad["companies"][0]["declarations"][0].update(role="diluted_eps_12m", formula="SUBTRACT")
    with pytest.raises(ValueError, match="EPS direct-only"):
        propose_bindings(pin(tmp_path / "bad.json", bad))
    bad = copy.deepcopy(config)
    bad["companies"][0]["declarations"][0].update(role="nci", formula="EVIDENCED_ZERO", candidate_ids=[])
    with pytest.raises(ValueError, match="explicit role evidence"):
        propose_bindings(pin(tmp_path / "zero.json", bad))


def test_binding_proposal_cli_writes_exact_pins_and_refuses_overwrite(tmp_path):
    config = pin(tmp_path / "config.json", role_plan(tmp_path))
    destination = tmp_path / "proposals"
    project = Path(__file__).resolve().parents[2]
    command = [sys.executable, str(project / "examples/screening/prepare_company_valuations.py"), "propose-bindings",
        "--config", config["path"], "--sha256", config["sha256"], "--output", str(destination)]
    env = {**os.environ, "PYTHONPATH": str(project / "src")}
    first = subprocess.run(command, cwd=project, env=env, text=True, capture_output=True, check=True)
    manifest_pin = json.loads(first.stdout)
    manifest = pinned_json(manifest_pin)
    assert pinned_json(manifest["candidate_pin"])[0]["observation_id"] == "shares"
    assert pinned_json(manifest["proposals"][0]["proposal"])["status"] == "PROPOSAL_NOT_APPROVED"
    original = (destination / "manifest.json").read_bytes()
    second = subprocess.run(command, cwd=project, env=env, text=True, capture_output=True, check=False)
    assert second.returncode != 0 and "append-only binding proposal directory exists" in second.stderr
    assert (destination / "manifest.json").read_bytes() == original


@pytest.mark.parametrize("mutation", ["value", "qname", "source"])
def test_new_proposal_receipt_cannot_bind_mutated_flat_source_row(tmp_path, monkeypatch, mutation):
    from test_price_metric_publication import binding_fixture

    from examples.screening import prepare_price_metrics as prepare

    config, _, candidate, _ = binding_fixture(tmp_path)
    original = copy.deepcopy(candidate)
    other = {**original, "cik": "0000000002", "observation_id": "candidate-2"}
    pool_pin = pin(tmp_path / "approved-pool.json", {"candidates": [original, other]})
    config["candidate_pins"] = [pin(tmp_path / "two-flat.json", [candidate, other])]
    binding = config["bindings"][0]
    proposal = pinned_json(binding["proposal"])
    proposal.update(source_role_proofs=[{"role": "common_shares"}], source_pins={"candidate_pins": [pool_pin]})
    binding["proposal"] = pin(tmp_path / "new-proposal.json", proposal)
    receipt = pinned_json(binding["approval"])
    receipt["proposal"] = binding["proposal"]
    binding["approval"] = pin(tmp_path / "new-receipt.json", receipt)
    second = copy.deepcopy(binding)
    second["declarations"][0].update(cik="0000000002", candidate_ids=["candidate-2"])
    second["compatibility_grant"].update(cik="0000000002", security_id="US:TEST2")
    second_proposal = copy.deepcopy(proposal)
    second_proposal["declarations"] = second["declarations"]
    second["proposal"] = pin(tmp_path / "second-proposal.json", second_proposal)
    second["approval"] = pin(tmp_path / "second-receipt.json", {**receipt, "proposal": second["proposal"], "security_id": "US:TEST2"})
    config["bindings"].append(second)
    # Two approved bindings sharing a pool must not reread it for every issuer.
    count = []
    real_pinned = prepare.pinned_json

    def counting(source):
        if source == pool_pin:
            count.append(source)
        return real_pinned(source)

    monkeypatch.setattr(prepare, "pinned_json", counting)
    assert prepare.bind_bundle(pin(tmp_path / "good-config.json", config))["observations"][0]["value"] == "10"
    assert len(count) == 1
    if mutation == "value":
        candidate["value"] = "999"
    elif mutation == "qname":
        candidate["qname"] = "custom:DifferentSource"
    else:
        candidate["source"] = {"selected_source_fact_id": "different-fact"}
    config["candidate_pins"] = [pin(tmp_path / "changed-flat.json", [candidate, other])]
    with pytest.raises(ValueError, match="flat candidate differs"):
        prepare.bind_bundle(pin(tmp_path / "changed-config.json", config))


@pytest.mark.parametrize("role", ["preferred_equity", "nci"])
def test_exact_direct_reported_zero_is_evidence_without_changing_reviewed_zero_shape(tmp_path, role):
    proof = pin(tmp_path / "proof.json", {"fixture": "exact reported amount review"})
    row = share_candidate("us-gaap:PreferredStockValue" if role == "preferred_equity" else "us-gaap:MinorityInterest", value="0")
    row.pop("unit_kind")
    row.update(unit_numerator_measures=["iso4217:USD"], unit_denominator_measures=[])
    d = declaration(proof) | {"role": role}
    reported, = bind_financial_inputs([row], [d])
    assert reported["value"] == "0" and reported["evidenced_zero"] is True
    assert reported["zero_evidence_kind"] == "REPORTED_ZERO"
    reviewed, = bind_financial_inputs([], [{**d, "formula": "EVIDENCED_ZERO", "candidate_ids": []}])
    assert reviewed["evidenced_zero"] is True and "zero_evidence_kind" not in reviewed
    derived, = bind_financial_inputs([{**row, "status": "AVAILABLE_DERIVED_SEPARATE"}], [d])
    assert derived["evidenced_zero"] is False and "zero_evidence_kind" not in derived
    with pytest.raises(ValueError, match="ambiguous/absent"):
        bind_financial_inputs([], [d])
