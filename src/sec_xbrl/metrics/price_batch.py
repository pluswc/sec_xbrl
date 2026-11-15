"""One verified supplier adoption and one batch price read, independent of metrics."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path


# Deliberately stdlib-only: the supplier's runtime need not install SEC/Arelle.
def identity(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def pinned_json(pin: dict) -> dict:
    path = Path(pin["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("absolute regular input pin required")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("source input hash differs")
    return json.loads(data)


def canonical_price_batch(query: object, verify_delivery: object, *, delivery_pin: dict,
                          companies: list[dict], start: str, end: str,
                          currency_pin: dict | None = None, currency_manifest_pin: dict | None = None) -> dict:
    """Adopt once. Callers reuse this immutable batch for all companies and metrics.

    Dependencies are the official CanonicalQuery object and delivery verifier.
    There is no downloader, alternate security mapping or observed-date calendar.
    """
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("invalid batch date range")
    delivery = pinned_json(delivery_pin)
    receipt = verify_delivery(delivery_pin["path"])
    if receipt.get("status") != "verified":
        raise ValueError("supplier delivery did not verify")
    securities = query.get_securities().to_dicts()
    selected, mapping = [], []
    for company in companies:
        matches = [s for s in securities if s["cik"] == company["cik"] and s["ticker"] == company["ticker"]]
        if len(matches) != 1:
            mapping.append({**company, "security_id": None, "reason": "EXACT_REGISTERED_SECURITY_NOT_UNIQUE"})
        else:
            selected.append(matches[0])
            mapping.append({**company, "security_id": matches[0]["security_id"], "reason": None})
    ids = sorted({s["security_id"] for s in selected})
    if not ids:
        raise ValueError("no exact registered securities")
    # This is the sole supplier price scan. No company or metric loop may call it.
    frame = query.get_price_history(ids, start, end)
    lineage = query.price_lineage()
    if (lineage["sha256"] != delivery["artifacts"]["price.parquet"]["sha256"]
        or lineage["security_sha256"] != delivery["artifacts"]["security.parquet"]["sha256"]):
        raise ValueError("supplier batch differs from adopted delivery")
    currency = pinned_json(currency_pin) if currency_pin else None
    currencies = {}
    if currency:
        if not currency_manifest_pin:
            raise ValueError("trusted supplier sidecar manifest pin required")
        manifest = pinned_json(currency_manifest_pin)
        if (currency.get("schema_contract") != "price-capture-evidence.v1"
            or currency.get("schema_version") != "1.0.0"
            or manifest.get("manifest_contract") != "price-capture-evidence-delivery.v1"
            or manifest.get("status") != "accepted"
            or manifest["artifacts"]["sidecar.json"]["sha256"] != currency_pin["sha256"]
            or currency["input_pins"]["price.parquet"]["sha256"] != lineage["sha256"]
            or currency["input_pins"]["security.parquet"]["sha256"] != lineage["security_sha256"]):
            raise ValueError("currency sidecar differs from supplier batch")
        rows = currency["securities"]
        currencies = {r["security_id"]: r for r in rows}
        if len(currencies) != len(rows) or any(currencies.get(s["security_id"], {}).get("cik") != s["cik"] for s in selected):
            raise ValueError("currency sidecar security identity differs")
    prices = []
    for row in frame.to_dicts():
        row["trade_date"] = row["trade_date"].isoformat() if isinstance(row["trade_date"], date) else row["trade_date"]
        metadata = currencies.get(row["security_id"], {})
        row["currency"] = "USD" if metadata.get("currency_status") == "usd_supported" and metadata.get("source_currency") == "USD" else None
        row["capture_collected_at"] = metadata.get("capture_collected_at")
        row["ready_on"] = None  # Capture time is not historical system-ready proof.
        row["observation_id"] = "canonical-batch-price-" + identity({"price_sha256": lineage["sha256"], **row})
        prices.append(row)
    pinned_json(delivery_pin)
    if currency_pin:
        pinned_json(currency_pin)
    return {"schema_version": "price-metric-canonical-batch-v1", "created_at": datetime.now(UTC).isoformat(),
            "delivery": delivery_pin, "delivery_receipt": receipt, "lineage": lineage,
            "companies": mapping, "securities": selected, "prices": prices,
            "currency_evidence": currency_pin, "currency_manifest": currency_manifest_pin, "query": {"security_ids": ids, "start_date": start, "end_date": end},
            "price_batch_calls": 1, "adoption_verification_calls": 1,
            "volume_basis": "TRUE_SPLIT_COMPATIBLE", "automatic_update": False}
