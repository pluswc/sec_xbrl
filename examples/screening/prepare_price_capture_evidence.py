"""Offline consumer-generated capture evidence; never supplier certification.

Generalizes the pinned supplier extraction rules for one explicitly selected
bounded capture. No network, source writes, SEC/Arelle dependency or price math.
Prepare a candidate, obtain independent review and a ROOT exact acceptance receipt,
then create a separate accepted manifest for consumer adoption.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ORIGIN = "CONSUMER_GENERATED_SOURCE_VALIDATION"
SPEC = "consumer-price-capture-evidence-spec-v1"


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("absolute regular source without aliases required")
    return path


def file_pin(path: str | Path) -> dict:
    path = regular(path)
    data = path.read_bytes()
    return {"path": str(path), "sha256": digest(data), "bytes": len(data)}


def pinned(pin: dict) -> object:
    actual = file_pin(pin["path"])
    if actual["sha256"] != pin.get("sha256") or ("bytes" in pin and actual["bytes"] != pin["bytes"]):
        raise ValueError("source pin differs")
    return json.loads(Path(pin["path"]).read_bytes())


def aware(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.utcoffset() is None:
        raise ValueError("capture timestamp needs an explicit timezone")
    return value


def parquet_inputs(price: Path, security: Path) -> tuple[dict, list[dict]]:
    import pyarrow.parquet as pq
    metadata = {k.decode(): v.decode() for k, v in (pq.read_schema(price).metadata or {}).items() if k != b"ARROW:schema"}
    return metadata, pq.read_table(security).to_pylist()


def committed_blob(root: Path, commit: str, relative: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), "show", commit + ":" + relative])


def extract(spec_pin: dict) -> dict:
    spec = pinned(spec_pin)
    if spec.get("schema_version") != SPEC or re.fullmatch(r"[0-9a-f]{40}", spec.get("source_commit", "")) is None:
        raise ValueError("explicit pinned capture specification/commit required")
    delivery = pinned(spec["delivery"])
    if (delivery.get("manifest_contract") != "data-delivery.v1" or delivery.get("capability") != "price"
        or delivery.get("package_version") != "0.5.1" or delivery.get("contract_version") != "1.1.1"):
        raise ValueError("unsupported official price delivery")
    pins = {"spec": spec_pin, "price_manifest": spec["delivery"], "inventory_manifest": spec["inventory"],
            "consumer_input": spec["selected_securities"]}
    for name in ("price.parquet", "security.parquet"):
        actual = file_pin(delivery["artifacts"][name]["path"])
        if any(actual[k] != delivery["artifacts"][name].get(k) for k in ("sha256", "bytes")):
            raise ValueError("delivery artifact differs: " + name)
        pins[name] = actual
    metadata, master_rows = parquet_inputs(Path(pins["price.parquet"]["path"]), Path(pins["security.parquet"]["path"]))
    inventory = pinned(spec["inventory"])
    supplied = pinned(spec["selected_securities"])
    master = {row["security_id"]: row for row in master_rows}
    ids = [row["security_id"] for row in supplied]
    if not ids or ids != sorted(set(ids)) or len(master) != len(master_rows):
        raise ValueError("selected/security identities must be nonempty and unique")
    selected = inventory["selected_security_ids"]
    if set(selected) != set(ids) or selected != [r["security_id"] for r in master_rows if r["security_id"] in set(ids)]:
        raise ValueError("exact bounded selection or checkpoint ordering differs")
    if inventory["securities"] != master_rows:
        raise ValueError("inventory security master differs")
    if (metadata.get("schema_contract") != "price.v1" or metadata.get("canonical_source") != "yahoo_chart"
        or metadata.get("source_semantics") != "as_traded_and_true_split_adjusted"
        or metadata.get("inventory_manifest_sha256") != spec["inventory"]["sha256"]
        or metadata.get("security_sha256") != pins["security.parquet"]["sha256"]
        or inventory["security_sha256"] != pins["security.parquet"]["sha256"]):
        raise ValueError("canonical metadata/inventory/security pairing differs")
    provenance = delivery.get("provenance", {}).get("price", {})
    if any(provenance.get(key) != metadata.get(key) for key in (
        "schema_contract", "canonical_source", "source_semantics", "collected_at", "factor_horizon_period2",
        "security_sha256", "reviewed_actions_sha256", "inventory_manifest_sha256", "inventory_content_sha256", "bounded_scope_json",
    )):
        raise ValueError("delivery provenance differs from canonical metadata")
    period1, period2 = inventory["period1"], inventory["period2"]
    if (type(period1) is not int or type(period2) is not int or period1 >= period2
        or inventory.get("interval") != "1d" or inventory.get("events") != "splits"
        or inventory.get("includeAdjustedClose") is not False):
        raise ValueError("frozen request semantics differ")
    cutoff = inventory["completed_day_cutoff"]
    date.fromisoformat(cutoff)
    bounded = json.loads(metadata["bounded_scope_json"])
    if (bounded.get("selected_security_ids") != selected or bounded.get("request_period1") != period1
        or bounded.get("request_period2") != period2 or bounded.get("completed_day_cutoff") != cutoff
        or metadata.get("factor_horizon_period2") != str(period2)
        or metadata.get("collected_at") != inventory["started_at"]):
        raise ValueError("canonical bounded horizon/capture metadata differs")
    started = aware(inventory["started_at"])
    root = Path(spec["supplier_root"])
    for name, relative, expected in (
        ("normalizer_source", "market_data_pipeline/price.py", None),
        ("reviewed_actions", "market_data_pipeline/resources/reviewed_actions.json", metadata.get("reviewed_actions_sha256")),
    ):
        pin = file_pin(root / relative)
        if digest(committed_blob(root, spec["source_commit"], relative)) != pin["sha256"] or expected is not None and pin["sha256"] != expected:
            raise ValueError("normalizer/reviewed actions differ from pinned supplier commit")
        pins[name] = pin
    inventory_root = Path(spec["inventory"]["path"]).parent
    commitment = hashlib.sha256(Path(spec["inventory"]["path"]).read_bytes())
    checkpoints = {}
    for sid in selected:
        key = digest(sid.encode())[:24]
        path = regular(inventory_root / "checkpoints" / (key + ".json"))
        blob = path.read_bytes()
        cp = json.loads(blob)
        if cp.get("security_id") != sid or cp.get("yahoo_symbol") != master[sid]["yahoo_symbol"] or cp.get("status") != "ok":
            raise ValueError("successful checkpoint identity differs")
        commitment.update(hashlib.sha256(blob).digest())
        try:
            commitment.update(bytes.fromhex(cp["raw_sha256"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("checkpoint raw digest absent/invalid") from exc
        checkpoints[sid] = (path, blob, cp)
    if commitment.hexdigest() != metadata["inventory_content_sha256"]:
        raise ValueError("ordered checkpoint/raw-hash commitment differs")
    rows = []
    for selected_identity in supplied:
        sid = selected_identity["security_id"]
        identity = master[sid]
        if selected_identity != identity:
            raise ValueError("selected full canonical identity differs")
        cp_path, cp_blob, cp = checkpoints[sid]
        key = digest(sid.encode())[:24]
        if cp.get("raw_path") != "raw/" + key + ".json.gz":
            raise ValueError("checkpoint raw path is not confined")
        raw_path = regular(inventory_root / cp["raw_path"])
        compressed = raw_path.read_bytes()
        raw = gzip.decompress(compressed)
        if digest(raw) != cp["raw_sha256"]:
            raise ValueError("decompressed raw hash differs")
        chart = json.loads(raw)["chart"]
        if chart.get("error") is not None or len(chart.get("result") or []) != 1:
            raise ValueError("successful checkpoint has invalid chart response")
        meta = chart["result"][0]["meta"]
        if str(meta.get("symbol", "")).upper() != identity["yahoo_symbol"].upper():
            raise ValueError("raw response symbol differs")
        if aware(cp["collected_at"]) < started:
            raise ValueError("checkpoint capture precedes inventory start")
        requested_start = cp["requested_period1"]
        fallback = period2 - 99 * 365 * 86400
        if requested_start not in {period1, fallback} or cp.get("history_fallback", False) != (requested_start == fallback):
            raise ValueError("checkpoint request start/fallback differs")
        parsed = urlparse(cp["url"])
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (parsed.scheme != "https" or parsed.netloc != "query1.finance.yahoo.com" or parsed.fragment
            or unquote(parsed.path) != "/v8/finance/chart/" + identity["yahoo_symbol"]
            or query != {"period1": [str(requested_start)], "period2": [str(period2)], "interval": ["1d"], "events": ["splits"], "includeAdjustedClose": ["false"]}):
            raise ValueError("request URL symbol/horizon differs")
        currency = meta.get("currency")
        rows.append({**identity, "checkpoint_status": "ok", "source_currency": currency,
            "currency_status": "usd_supported" if currency == "USD" else "missing_currency" if currency is None else "unsupported_currency",
            "source_instrument_type": meta.get("instrumentType"), "source_exchange_timezone": meta.get("exchangeTimezoneName"),
            "source_exchange_name": meta.get("exchangeName"), "source_full_exchange_name": meta.get("fullExchangeName"),
            "capture_collected_at": cp["collected_at"], "request_url": cp["url"], "requested_period1": requested_start,
            "checkpoint_path": str(cp_path), "checkpoint_sha256": digest(cp_blob), "raw_path": str(raw_path),
            "raw_sha256": digest(raw), "compressed_raw_sha256": digest(compressed)})
    for pin in pins.values():
        if file_pin(pin["path"])["sha256"] != pin["sha256"]:
            raise ValueError("input changed during evidence extraction")
    for row in rows:
        if file_pin(row["checkpoint_path"])["sha256"] != row["checkpoint_sha256"] or file_pin(row["raw_path"])["sha256"] != row["compressed_raw_sha256"]:
            raise ValueError("capture changed during evidence extraction")
    return {"schema_contract": "price-capture-evidence.v1", "schema_version": "1.0.0",
        "dataset_version": spec["dataset_version"], "source_dataset_version": spec["source_dataset_version"],
        "source_package_version": delivery["package_version"], "source_contract_version": delivery["contract_version"],
        "source_commit": spec["source_commit"], "input_pins": pins, "securities": rows,
        "inventory_content_sha256": commitment.hexdigest(), "factor_horizon_period2": period2,
        "trade_date_cutoff_exclusive": cutoff, "origin": ORIGIN, "supplier_independent_acceptance": False,
        "limits": ["Capture metadata and source-byte validation only; not historical per-date currency or system-ready evidence.",
                   "No EPS/class/ADR/FX/total-return or complete corporate-action certification.",
                   "Consumer-generated validation is not supplier certification or independent supplier acceptance."]}


def prepare(spec_pin: dict, output: str | Path) -> dict:
    output = Path(output)
    if output.exists() or not output.is_absolute() or any(p.is_symlink() for p in output.parents):
        raise ValueError("candidate destination must be new, absolute and without aliases")
    sidecar = extract(spec_pin)
    output.mkdir(parents=True)
    with (output / "sidecar.json").open("xb") as handle:
        handle.write(encoded(sidecar))
    manifest = {"manifest_contract": "price-capture-evidence-delivery.v1", "status": "CANDIDATE_UNACCEPTED",
        "origin": ORIGIN, "supplier_independent_acceptance": False, "spec": spec_pin,
        "artifacts": {"sidecar.json": file_pin(output / "sidecar.json")},
        "source_pins": sidecar["input_pins"], "producer": file_pin(Path(__file__).absolute())}
    with (output / "manifest.json").open("xb") as handle:
        handle.write(encoded(manifest))
    return file_pin(output / "manifest.json")


def accept(candidate_pin: dict, acceptance_pin: dict, output: str | Path) -> dict:
    output = Path(output)
    if output.exists() or not output.is_absolute() or any(p.is_symlink() for p in output.parents):
        raise ValueError("accepted manifest destination must be new and absolute")
    candidate, receipt = pinned(candidate_pin), pinned(acceptance_pin)
    if candidate.get("status") != "CANDIDATE_UNACCEPTED" or candidate.get("origin") != ORIGIN:
        raise ValueError("unaccepted consumer candidate required")
    sidecar_pin = candidate["artifacts"]["sidecar.json"]
    sidecar = pinned(sidecar_pin)
    if file_pin(candidate["producer"]["path"]) != candidate["producer"]:
        raise ValueError("candidate producer source changed before adoption")
    for row in sidecar["securities"]:
        if (file_pin(row["checkpoint_path"])["sha256"] != row["checkpoint_sha256"]
            or file_pin(row["raw_path"])["sha256"] != row["compressed_raw_sha256"]):
            raise ValueError("candidate capture source changed before adoption")
    if (receipt.get("schema_version") != "consumer-price-capture-evidence-root-acceptance-v1"
        or receipt.get("authority") != "ROOT" or receipt.get("status") != "ACCEPTED_FOR_BOUNDED_PRICE_CURRENCY_ADOPTION"
        or receipt.get("candidate") != file_pin(candidate_pin["path"]) or receipt.get("sidecar") != sidecar_pin
        or receipt.get("source_pins") != candidate["source_pins"]):
        raise ValueError("ROOT acceptance must bind the exact candidate, sidecar and source pins")
    for pin in candidate["source_pins"].values():
        if file_pin(pin["path"])["sha256"] != pin["sha256"]:
            raise ValueError("accepted source pin changed")
    accepted = {**candidate, "status": "accepted", "consumer_acceptance": acceptance_pin,
                "candidate_manifest": candidate_pin, "acceptance_scope": "CONSUMER_ADOPTION_ONLY_NOT_SUPPLIER_CERTIFICATION"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(encoded(accepted))
    return file_pin(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--spec", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--output", required=True)
    a = commands.add_parser("accept")
    for key in ("candidate", "candidate-sha256", "acceptance", "acceptance-sha256", "output"):
        a.add_argument("--" + key, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare({"path": args.spec, "sha256": args.sha256}, args.output)
    else:
        result = accept({"path": args.candidate, "sha256": args.candidate_sha256},
                        {"path": args.acceptance, "sha256": args.acceptance_sha256}, args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
