from __future__ import annotations

import copy
import gzip
import json

import pytest

from examples.screening import prepare_price_capture_evidence as evidence


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence.encoded(obj))
    return evidence.file_pin(path)


@pytest.fixture
def capture(tmp_path, monkeypatch):
    root = tmp_path / "supplier"
    source_files = {"market_data_pipeline/price.py": b"fixture pinned normalization source",
                    "market_data_pipeline/resources/reviewed_actions.json": b'{"schema_version":1,"actions":[]}'}
    for name, blob in source_files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    monkeypatch.setattr(evidence, "committed_blob", lambda root, commit, relative: source_files[relative])
    master = [{"security_id": "US:"+symbol, "cik": f"{i:010d}", "ticker": symbol, "yahoo_symbol": symbol,
               "company_name": symbol, "exchange": "NASDAQ"} for i, symbol in enumerate(("ONE", "TWO"), 1)]
    invroot = tmp_path / "raw"
    selected = write(tmp_path / "selected.json", master)
    security, price = tmp_path / "security.parquet", tmp_path / "price.parquet"
    security.write_bytes(b"fixture security bytes")
    price.write_bytes(b"fixture canonical price bytes")
    inventory = {"securities": master, "selected_security_ids": [r["security_id"] for r in master],
                 "security_sha256": evidence.file_pin(security)["sha256"], "period1": 0, "period2": 1794873600,
                 "interval": "1d", "events": "splits", "includeAdjustedClose": False,
                 "completed_day_cutoff": "2026-11-16", "started_at": "2026-11-16T00:00:00+00:00"}
    cp_paths = []
    raw_paths = []
    for row in master:
        key = evidence.digest(row["security_id"].encode())[:24]
        raw = evidence.encoded({"chart": {"error": None, "result": [{"meta": {"symbol": row["yahoo_symbol"], "currency": "USD", "instrumentType": "EQUITY"}}]}})
        rawpath = invroot / "raw" / (key + ".json.gz")
        rawpath.parent.mkdir(parents=True, exist_ok=True)
        rawpath.write_bytes(gzip.compress(raw, mtime=0))
        cppath = invroot / "checkpoints" / (key + ".json")
        write(cppath, {"security_id": row["security_id"], "yahoo_symbol": row["yahoo_symbol"], "status": "ok",
                      "raw_path": "raw/"+key+".json.gz", "raw_sha256": evidence.digest(raw), "requested_period1": 0,
                      "history_fallback": False, "collected_at": "2026-11-16T00:01:00+00:00",
                      "url": "https://query1.finance.yahoo.com/v8/finance/chart/"+row["yahoo_symbol"]+"?period1=0&period2=1794873600&interval=1d&events=splits&includeAdjustedClose=false"})
        cp_paths.append(cppath)
        raw_paths.append(rawpath)
    metadata = {}
    def refresh():
        invpin = write(invroot / "manifest.json", inventory)
        import hashlib
        commitment = hashlib.sha256((invroot / "manifest.json").read_bytes())
        for p in cp_paths:
            commitment.update(hashlib.sha256(p.read_bytes()).digest())
            commitment.update(bytes.fromhex(json.loads(p.read_bytes())["raw_sha256"]))
        metadata.update({"schema_contract": "price.v1", "canonical_source": "yahoo_chart", "source_semantics": "as_traded_and_true_split_adjusted",
                         "collected_at": inventory["started_at"], "factor_horizon_period2": str(inventory["period2"]),
                         "security_sha256": evidence.file_pin(security)["sha256"], "inventory_manifest_sha256": invpin["sha256"],
                         "reviewed_actions_sha256": evidence.digest(source_files["market_data_pipeline/resources/reviewed_actions.json"]),
                         "inventory_content_sha256": commitment.hexdigest(), "bounded_scope_json": json.dumps({"selected_security_ids": inventory["selected_security_ids"],
                             "request_period1": inventory["period1"], "request_period2": inventory["period2"], "completed_day_cutoff": inventory["completed_day_cutoff"]})})
        delivery = write(tmp_path / "delivery.json", {"manifest_contract": "data-delivery.v1", "capability": "price", "package_version": "0.5.1", "contract_version": "1.1.1",
            "artifacts": {"price.parquet": evidence.file_pin(price), "security.parquet": evidence.file_pin(security)}, "provenance": {"price": dict(metadata)}})
        return write(tmp_path / "spec.json", {"schema_version": evidence.SPEC, "source_commit": "a"*40, "supplier_root": str(root),
            "delivery": delivery, "inventory": invpin, "selected_securities": selected, "dataset_version": "candidate", "source_dataset_version": "capture"})
    monkeypatch.setattr(evidence, "parquet_inputs", lambda price, security: (dict(metadata), copy.deepcopy(master)))
    return {"spec": refresh(), "refresh": refresh, "inventory": inventory, "metadata": metadata, "master": master,
            "cp": cp_paths, "raw": raw_paths, "price": price, "supplier": root}


def test_candidate_is_deterministic_and_acceptance_is_separate_exact_and_consumer_only(capture, tmp_path):
    c = evidence.prepare(capture["spec"], tmp_path / "candidate")
    manifest = evidence.pinned(c)
    sidecar = evidence.pinned(manifest["artifacts"]["sidecar.json"])
    assert manifest["status"] == "CANDIDATE_UNACCEPTED"
    assert manifest["supplier_independent_acceptance"] is False
    assert [r["currency_status"] for r in sidecar["securities"]] == ["usd_supported", "usd_supported"]
    assert evidence.encoded(evidence.extract(capture["spec"])) == evidence.encoded(sidecar)
    receipt = {"schema_version": "consumer-price-capture-evidence-root-acceptance-v1", "authority": "ROOT", "status": "ACCEPTED_FOR_BOUNDED_PRICE_CURRENCY_ADOPTION",
               "candidate": c, "sidecar": manifest["artifacts"]["sidecar.json"], "source_pins": manifest["source_pins"]}
    rp = write(tmp_path / "acceptance.json", receipt)
    accepted = evidence.pinned(evidence.accept({"path": c["path"], "sha256": c["sha256"]}, rp, tmp_path / "accepted.json"))
    assert accepted["status"] == "accepted" and accepted["supplier_independent_acceptance"] is False
    assert accepted["consumer_acceptance"] == rp
    receipt["sidecar"] = {**receipt["sidecar"], "sha256": "0"*64}
    with pytest.raises(ValueError, match="exact candidate"):
        evidence.accept(c, write(tmp_path / "wrong.json", receipt), tmp_path / "bad-accepted.json")


@pytest.mark.parametrize("mutation,reason", [("checkpoint", "commitment"), ("raw", "decompressed"), ("normalizer", "pinned supplier commit"),
    ("currency", "decompressed"), ("metadata", "horizon"), ("url", "URL"), ("timezone", "timezone"), ("selection", "selection")])
def test_capture_source_and_semantic_mutations_reject(capture, mutation, reason):
    c = capture
    if mutation == "checkpoint":
        c["cp"][0].write_bytes(c["cp"][0].read_bytes()+b" ")
    elif mutation in {"raw", "currency"}:
        blob = gzip.decompress(c["raw"][0].read_bytes())
        c["raw"][0].write_bytes(gzip.compress(blob.replace(b'USD', b'EUR') if mutation == "currency" else blob+b" "))
    elif mutation == "normalizer":
        (c["supplier"] / "market_data_pipeline/price.py").write_bytes(b"changed")
    elif mutation == "metadata":
        c["inventory"]["period2"] += 1
        c["spec"] = c["refresh"]()
        # Bind updated metadata/provenance, but keep the real checkpoint URL horizon.
    elif mutation in {"url", "timezone"}:
        cp = json.loads(c["cp"][0].read_bytes())
        cp["url" if mutation == "url" else "collected_at"] = "https://query1.finance.yahoo.com/v8/finance/chart/OTHER?period1=0" if mutation == "url" else "2026-11-16T00:01:00"
        write(c["cp"][0], cp)
        c["spec"] = c["refresh"]()
    else:
        c["inventory"]["selected_security_ids"].reverse()
        c["spec"] = c["refresh"]()
    with pytest.raises(ValueError, match=reason):
        evidence.extract(c["spec"])


def test_existing_sources_and_outputs_are_never_overwritten(capture, tmp_path):
    original = capture["price"].read_bytes()
    with pytest.raises(ValueError, match="destination"):
        evidence.prepare(capture["spec"], capture["price"])
    assert capture["price"].read_bytes() == original
    evidence.prepare(capture["spec"], tmp_path / "candidate")
    with pytest.raises(ValueError, match="destination"):
        evidence.prepare(capture["spec"], tmp_path / "candidate")
    with pytest.raises(ValueError, match="destination"):
        evidence.accept({}, {}, capture["price"])
    assert capture["price"].read_bytes() == original


@pytest.mark.parametrize("currency,status", [(None, "missing_currency"), ("EUR", "unsupported_currency")])
def test_original_non_usd_metadata_stays_explicit_and_is_not_assumed_usd(capture, currency, status):
    rawpath, cppath = capture["raw"][0], capture["cp"][0]
    raw = json.loads(gzip.decompress(rawpath.read_bytes()))
    meta = raw["chart"]["result"][0]["meta"]
    if currency is None:
        meta.pop("currency")
    else:
        meta["currency"] = currency
    blob = evidence.encoded(raw)
    rawpath.write_bytes(gzip.compress(blob, mtime=0))
    cp = json.loads(cppath.read_bytes())
    cp["raw_sha256"] = evidence.digest(blob)
    write(cppath, cp)
    sidecar = evidence.extract(capture["refresh"]())
    assert sidecar["securities"][0]["source_currency"] == currency
    assert sidecar["securities"][0]["currency_status"] == status


def test_price_bytes_and_reviewed_action_source_changes_reject(capture):
    capture["price"].write_bytes(b"changed price bytes")
    with pytest.raises(ValueError, match="delivery artifact"):
        evidence.extract(capture["spec"])
    capture["price"].write_bytes(b"fixture canonical price bytes")
    (capture["supplier"] / "market_data_pipeline/resources/reviewed_actions.json").write_bytes(b"changed actions")
    with pytest.raises(ValueError, match="pinned supplier commit"):
        evidence.extract(capture["spec"])


def test_acceptance_rechecks_capture_bytes_even_if_inventory_pin_did_not_change(capture, tmp_path):
    candidate = evidence.prepare(capture["spec"], tmp_path / "candidate")
    manifest = evidence.pinned(candidate)
    receipt = write(tmp_path / "receipt.json", {"schema_version": "consumer-price-capture-evidence-root-acceptance-v1", "authority": "ROOT",
        "status": "ACCEPTED_FOR_BOUNDED_PRICE_CURRENCY_ADOPTION", "candidate": candidate,
        "sidecar": manifest["artifacts"]["sidecar.json"], "source_pins": manifest["source_pins"]})
    capture["raw"][0].write_bytes(b"changed after candidate verification")
    with pytest.raises(ValueError, match="capture source changed"):
        evidence.accept(candidate, receipt, tmp_path / "accepted.json")
    assert not (tmp_path / "accepted.json").exists()
