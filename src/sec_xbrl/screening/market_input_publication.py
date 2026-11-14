"""Immutable common-input publication; readers never calculate financial values."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from sec_xbrl.metrics.market_inputs import (
    REGISTRY,
    TTM_RULE,
    deduplicate_financial_inputs,
    derive_market_eps_ttm,
    encoded,
    identity,
    pinned_json,
    project_cover_shares,
    project_financial_inputs,
)

SCHEMA = "screening-market-input-publication-v1"
PRICE_FIELDS = {
    "security_id",
    "trade_date",
    "as_traded_open",
    "as_traded_high",
    "as_traded_low",
    "as_traded_close",
    "as_traded_volume",
    "split_adj_open",
    "split_adj_high",
    "split_adj_low",
    "split_adj_close",
    "split_adj_volume",
    "split_factor",
    "source",
}


def _schema(value: dict) -> str | None:
    if (
        "schema" in value
        and "schema_version" in value
        and value["schema"] != value["schema_version"]
    ):
        raise ValueError("conflicting schema identifiers")
    return value.get("schema", value.get("schema_version"))


def _aware(text: str) -> None:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware actual timestamp is required")


def _price_rows(export: dict, ciks: set[str], cutoff: str) -> tuple[list[dict], list[dict]]:
    if _schema(export) != "canonical-query-price-export-v1":
        raise ValueError("unsupported CanonicalQuery export")
    _aware(export["created_at"])
    supplier = export["supplier"]
    if supplier.get("package_version") != "0.5.1" or supplier.get("contract_version") != "1.1.1":
        raise ValueError("unqualified supplier contract")
    delivery = pinned_json(export["delivery"])
    # Retain the full supplier lineage; validate its accessed price and security pins.
    lineage = export["lineage"]
    if not isinstance(lineage.get("sha256"), str) or len(lineage["sha256"]) != 64:
        raise ValueError("supplier price lineage is absent")
    price_pin = delivery["artifacts"]["price.parquet"]
    security_pin = delivery["artifacts"]["security.parquet"]
    if (
        lineage["sha256"] != price_pin["sha256"]
        or lineage.get("path") != price_pin["path"]
        or lineage.get("security_sha256") != security_pin["sha256"]
        or any(supplier[k] != delivery.get(k) for k in ("package_version", "contract_version"))
        or not export.get("producer")
    ):
        raise ValueError("supplier delivery/price/security lineage mismatch")
    query = export["query"]
    start, end = date.fromisoformat(query["start_date"]), date.fromisoformat(query["end_date"])
    if start > end or end > date.fromisoformat(cutoff):
        raise ValueError("price observation is outside cutoff")
    securities = export["securities"]
    if any(
        set(s) != {"security_id", "cik", "company_name", "ticker", "exchange", "yahoo_symbol"}
        or s["cik"] not in ciks
        for s in securities
    ):
        raise ValueError("supplier security identity/scope mismatch")
    ids = [s["security_id"] for s in securities]
    if (
        len(set(ids)) != len(ids)
        or len(set(query["security_ids"])) != len(query["security_ids"])
        or set(ids) != set(query["security_ids"])
    ):
        raise ValueError("supplier requested security identities mismatch")
    owners = {s["security_id"]: s["cik"] for s in securities}
    seen, rows = set(), []
    for price in export["prices"]:
        if set(price) != PRICE_FIELDS or price["security_id"] not in owners:
            raise ValueError("supplier price schema/owner mismatch")
        day = date.fromisoformat(price["trade_date"])
        key = (price["security_id"], price["trade_date"])
        if not start <= day <= end or key in seen:
            raise ValueError("duplicate/out-of-query price")
        seen.add(key)
        record = {
            "cik": owners[price["security_id"]],
            "input_id": "observed_security_price",
            "unit_kind": "price",
            "currency": None,
            "stock_class_id": None,
            "instrument_kind": None,
            "status": "AVAILABLE_OBSERVED",
            "reason": None,
            "reported_or_derived": None,
            "price": price,
            "source": {
                "supplier_export_schema": _schema(export),
                "delivery": export["delivery"],
                "price_sha256": lineage["sha256"],
            },
        }
        record["observation_id"] = "market-price-" + identity(record)
        rows.append(record)
    return copy.deepcopy(securities), rows


def _write_json(path: Path, value: object) -> dict:
    data = encoded(value)
    path.write_bytes(data)
    return {"path": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def publish_market_inputs(config_path: str | Path, config_sha256: str, output: str | Path) -> dict:
    """Build once from existing analysis and one batch supplier export. No source writes."""
    config_pin = {"path": str(Path(config_path).absolute()), "sha256": config_sha256}
    config = pinned_json(config_pin)
    if _schema(config) != "screening-market-input-config-v1":
        raise ValueError("unsupported market-input configuration")
    parent = pinned_json(config["parent"])
    cutoff = config["financial_as_of"]
    date.fromisoformat(cutoff)
    if parent.get("financial_as_of") != cutoff:
        raise ValueError("parent cutoff mismatch")
    companies = config["companies"]
    ciks = [c["cik"] for c in companies]
    if any(not isinstance(c, str) or len(c) != 10 or not c.isdigit() for c in ciks):
        raise ValueError("invalid registered CIK")
    if len(set(ciks)) != len(ciks) or set(ciks) != set(parent["configured_ciks"]):
        raise ValueError("registered companies must exactly match parent universe")
    export = pinned_json(config["price_export"])
    securities, prices = _price_rows(export, set(ciks), cutoff)
    declarations = []
    if config.get("basis_declarations") is not None:
        artifact = pinned_json(config["basis_declarations"])
        if _schema(artifact) != "market-eps-share-basis-v1":
            raise ValueError("unsupported share-basis declarations")
        declarations = artifact["declarations"]
        if any(d.get("cik") not in ciks for d in declarations):
            raise ValueError("share-basis scope mismatch")
        for declaration in declarations:
            for pin in declaration.get("source_pins", []):
                pinned_json(pin)
    observations = []
    for company in sorted(companies, key=lambda c: c["cik"]):
        for mode in ("annual", "quarterly"):
            pin = company.get(mode)
            if pin is not None:
                manifest = pinned_json(pin)
                if manifest.get("period_mode", "QUARTERLY") != mode.upper():
                    raise ValueError("analysis frequency mismatch")
                observations.extend(
                    project_financial_inputs(
                        pin, cik=company["cik"], ticker=company["ticker"], financial_as_of=cutoff
                    )
                )
        if not any(
            r["cik"] == company["cik"]
            and r["input_id"] == "outstanding_common_shares_cover"
            and r["status"] == "AVAILABLE_REPORTED"
            for r in observations
        ):
            source = company.get("quarterly") or company.get("annual")
            if source is not None:
                observations.extend(
                    project_cover_shares(
                        source,
                        cik=company["cik"],
                        ticker=company["ticker"],
                        financial_as_of=cutoff,
                        intake_pin=company.get("intake"),
                    )
                )
    observations = deduplicate_financial_inputs(observations)
    derived, selections = [], []
    for company in sorted(companies, key=lambda c: c["cik"]):
        cik = company["cik"]
        rows = [r for r in observations if r["cik"] == cik]
        for input_id in REGISTRY:
            matched = [r for r in rows if r["input_id"] == input_id]
            available = [
                r["observation_id"] for r in matched if r["status"] == "AVAILABLE_REPORTED"
            ]
            selections.append(
                {
                    "cik": cik,
                    "input_id": input_id,
                    "status": "AVAILABLE_REPORTED" if available else "UNAVAILABLE",
                    "reason": None if available else "NO_SELECTED_DIRECT_OBSERVATION",
                    "observation_ids": sorted(r["observation_id"] for r in matched),
                    "available_observation_ids": sorted(available),
                    "selection_policy": "ALL_PREPARED_SCOPES_NO_CLASS_WINNER",
                }
            )
        company_prices = [p for p in prices if p["cik"] == cik]
        selections.append(
            {
                "cik": cik,
                "input_id": "observed_security_price",
                "status": "AVAILABLE_OBSERVED" if company_prices else "UNAVAILABLE",
                "reason": None if company_prices else "NO_OBSERVED_PRICE",
                "observation_ids": sorted(p["observation_id"] for p in company_prices),
            }
        )
        declared = [d for d in declarations if d["cik"] == cik]
        keys = [(d.get("stock_class_id"), d.get("basis_id")) for d in declared]
        if len(set(keys)) != len(keys):
            raise ValueError("ambiguous share-basis declaration")
        for declaration in declared or [None]:
            item = derive_market_eps_ttm(
                rows, cik=cik, financial_as_of=cutoff, declaration=declaration
            )
            item["observation_id"] = "market-derived-" + identity(item)
            derived.append(item)
    destination = Path(output).absolute()
    if destination.exists():
        raise FileExistsError("append-only publication destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".partial-market-input-", dir=destination.parent))
    try:
        files = {
            name: _write_json(staging / (name + ".json"), value)
            for name, value in (
                ("financial_inputs", observations),
                ("prices", prices),
                ("securities", securities),
                ("selections", selections),
                ("derived_inputs", derived),
            )
        }
        manifest = {
            "schema_version": SCHEMA,
            "financial_as_of": cutoff,
            "parent": config["parent"],
            "parent_publication_id": parent["publication_id"],
            "config": config_pin,
            "companies": companies,
            "price_export": config["price_export"],
            "basis_declarations": config.get("basis_declarations"),
            "files": files,
            "registry": {k: {"qname": v[0], "unit_kind": v[1]} for k, v in REGISTRY.items()},
            "derived_rule": TTM_RULE,
            "counts": {
                "companies": len(ciks),
                "securities": len(securities),
                "prices": len(prices),
                "financial_inputs": len(observations),
            },
            "producer": {
                "market_inputs_sha256": hashlib.sha256(
                    Path(project_financial_inputs.__code__.co_filename).read_bytes()
                ).hexdigest(),
                "publication_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            "availability": {
                "source_filing_date_precision": "DAY",
                "historical_ready_at": None,
                "market_session_lag": 0,
            },
        }
        manifest["publication_id"] = "screening-market-input-" + identity(manifest)[:24]
        # Completion observation is recorded after all outputs/source rechecks, never at batch start.
        for pin in [config_pin, config["parent"], config["price_export"]]:
            pinned_json(pin)
        manifest["prepared_at"] = datetime.now(UTC).isoformat()
        _write_json(staging / "market_input_manifest.json", manifest)
        MarketInputReader(staging / "market_input_manifest.json", identity(manifest)).verify_all()
        os.rename(staging, destination)
        return {
            "path": str(destination / "market_input_manifest.json"),
            "sha256": identity(manifest),
            "publication_id": manifest["publication_id"],
            "counts": manifest["counts"],
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


class MarketInputReader:
    """Hash-verified reads of already-published values; never recomputes TTM."""

    def __init__(self, manifest_path: str | Path, sha256: str):
        self.pin = {"path": str(Path(manifest_path).absolute()), "sha256": sha256}
        self.manifest = pinned_json(self.pin)
        if self.manifest.get("schema_version") != SCHEMA:
            raise ValueError("unsupported market-input publication")
        _aware(self.manifest["prepared_at"])
        self.root = Path(self.pin["path"]).parent

    def _read(self, name: str) -> list[dict]:
        pinned_json(self.pin)
        ref = self.manifest["files"][name]
        if Path(ref["path"]).name != ref["path"]:
            raise ValueError("publication content escapes root")
        return pinned_json({"path": str(self.root / ref["path"]), "sha256": ref["sha256"]})

    def query(self, cik: str, input_id: str | None = None) -> dict:
        if cik not in {c["cik"] for c in self.manifest["companies"]}:
            raise KeyError(cik)
        # Validate small pinned source declarations, not full legacy company audits.
        pinned_json(self.manifest["parent"])
        pinned_json(self.manifest["price_export"])
        company = next(c for c in self.manifest["companies"] if c["cik"] == cik)
        for key in ("annual", "quarterly", "intake"):
            if company.get(key) is not None:
                pinned_json(company[key])

        def selected(name):
            return [
                r
                for r in self._read(name)
                if r.get("cik") == cik and (input_id is None or r.get("input_id") == input_id)
            ]

        return {
            "publication_id": self.manifest["publication_id"],
            "financial_as_of": self.manifest["financial_as_of"],
            "prepared_at": self.manifest["prepared_at"],
            "historical_ready_at": None,
            "financial_inputs": selected("financial_inputs"),
            "prices": selected("prices"),
            "securities": [r for r in self._read("securities") if r["cik"] == cik],
            "selections": selected("selections"),
            "derived_inputs": selected("derived_inputs"),
        }

    def verify_all(self) -> None:
        for name in self.manifest["files"]:
            self._read(name)
