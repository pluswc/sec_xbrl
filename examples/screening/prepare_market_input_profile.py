"""Project a pinned common-input assessment into a compact, current-dataset UI asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sec_xbrl.metrics.market_inputs import encoded, finite, identity, pinned_json
from sec_xbrl.screening.market_input_publication import MarketInputAssessmentReader

SCHEMA = "screening-market-input-profile-v1"
SHARE_ROLES = {
    "outstanding_common_shares_cover",
    "outstanding_common_shares_balance",
    "weighted_average_basic_shares",
    "weighted_average_diluted_shares",
}


def dataset_scope(pin: dict, common: dict) -> dict:
    data = pinned_json(pin)
    digest = pin["sha256"]
    if data.get("schema_version") == "screening-read-snapshot-v1":
        if identity({k: v for k, v in data.items() if k != "logical_sha256"}) != data.get(
            "logical_sha256"
        ):
            raise ValueError("read snapshot logical identity differs")
        digest = data["properties"]["original_manifest_sha256"]
        data = data["properties"]["original_manifest"]
    if (
        data.get("schema_version") != "screening-prepared-changes-v1"
        or data.get("parent_manifest_sha256") != common["parent"]["sha256"]
        or data.get("financial_as_of") != common["financial_as_of"]
        or set(data.get("configured_ciks", [])) != {c["cik"] for c in common["companies"]}
    ):
        raise ValueError("profile asset requires the exact prepared descendant and issuer scope")
    return {
        "dataset_id": data["dataset_id"],
        "dataset_publication_id": data["publication_id"],
        "financial_as_of": data["financial_as_of"],
        "dataset_manifest_sha256": digest,
    }


def _source(row: dict) -> dict:
    source = row["source"]
    accession = source.get("accession")
    url = None
    if accession and len(accession.replace("-", "")) == 18:
        url = f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{accession.replace('-', '')}/{accession}-index.html"
    return {
        "observation_id": row["observation_id"],
        "source_fact_id": source.get("selected_source_fact_id"),
        "accession": accession,
        "filed_date": row.get("filed_date"),
        "url": url,
        "selection_view": row.get("selection_view"),
        "qname": row.get("qname"),
        "namespace": row.get("namespace"),
    }


def latest_share_candidates(rows: list[dict], cutoff: str) -> list[dict]:
    """Use each existing prepared full-scope series; never pick a stock class winner."""
    groups = defaultdict(list)
    for row in rows:
        if row["input_id"] not in SHARE_ROLES or not row.get("end"):
            continue
        end = date.fromisoformat(row["end"])
        if row.get("end_convention") != "EXCLUSIVE" or end > date.fromisoformat(cutoff) + timedelta(
            days=1
        ):
            continue
        source = row["source"]
        # Prepared node IDs preserve governed series/mapping scope across its periods.
        # Raw cover candidates have no analytical node and retain their full Raw dimensions.
        series = source.get("node_id") or row.get("raw_dimensions")
        groups[encoded([row["input_id"], row["period_class"], series, row.get("unit")])].append(row)
    result = []
    for candidates in groups.values():
        latest = max(row["end"] for row in candidates)
        current = [r for r in candidates if r["end"] == latest]
        values = {finite(r.get("value")) for r in current if r["status"] == "AVAILABLE_REPORTED"}
        ambiguous = len(values) > 1
        for row in current:
            result.append(
                {
                    "input_id": row["input_id"],
                    "value": None if ambiguous else row.get("value"),
                    "status": "UNAVAILABLE" if ambiguous else row["status"],
                    "reason": "AMBIGUOUS_REPORTED_SHARE_VALUE" if ambiguous else row.get("reason"),
                    "period_class": row["period_class"],
                    "start": row.get("start"),
                    "end": row["end"],
                    "display_end": (date.fromisoformat(row["end"]) - timedelta(days=1)).isoformat(),
                    "dimensions": row.get("dimensions"),
                    "raw_dimensions": row.get("raw_dimensions"),
                    "stock_class_id": row.get("stock_class_id"),
                    "unit_kind": row["unit_kind"],
                    "source": _source(row),
                }
            )
    return sorted(
        result,
        key=lambda r: (r["input_id"], r["period_class"], r["end"], r["source"]["observation_id"]),
    )


def build_profile_asset(assessment_pin: dict, dataset_pin: dict) -> dict:
    reader = MarketInputAssessmentReader(assessment_pin["path"], assessment_pin["sha256"])
    common = reader.parent.manifest
    scope = dataset_scope(dataset_pin, common)
    rows = reader.parent._read("financial_inputs")
    prices = reader.parent._read("prices")
    securities = reader.parent._read("securities")
    assessments = {r["cik"]: r for r in reader._assessments()}
    price_export = pinned_json(common["price_export"])
    companies = {}
    for company in common["companies"]:
        cik, ticker = company["cik"], company["ticker"]
        owned = [s for s in securities if s["cik"] == cik]
        matched = [s["security_id"] for s in owned if s["ticker"] == ticker]
        price_rows = []
        for security in owned:
            observed = [
                p
                for p in prices
                if p["cik"] == cik and p["price"]["security_id"] == security["security_id"]
            ]
            for item in observed or [None]:
                price = item["price"] if item else {}
                trade_date = price.get("trade_date")
                price_rows.append(
                    {
                        "security": security,
                        "value": price.get("as_traded_close"),
                        "basis": "AS_TRADED_CLOSE",
                        "currency": None,
                        "currency_status": "UNKNOWN",
                        "status": item["status"] if item else "UNAVAILABLE",
                        "reason": None if item else "NO_OBSERVED_PRICE",
                        "requested_date": scope["financial_as_of"],
                        "trade_date": trade_date,
                        "staleness_calendar_days": (
                            date.fromisoformat(scope["financial_as_of"])
                            - date.fromisoformat(trade_date)
                        ).days
                        if trade_date
                        else None,
                        "source": price.get("source"),
                        "observation_id": item["observation_id"] if item else None,
                    }
                )
        default_prices = [p for p in price_rows if p["security"]["security_id"] in matched]
        # Multiple exact identities/dates remain explicit candidates; never first-match wins.
        if len(default_prices) != 1:
            default_prices = []
        assessment = assessments[cik]
        by_id = {r["observation_id"]: r for r in rows if r["cik"] == cik}
        reported = assessment["reported_12m"]
        eps = {
            **reported,
            "display_end": (date.fromisoformat(reported["end"]) - timedelta(days=1)).isoformat()
            if reported.get("end")
            else None,
            "sources": [_source(by_id[oid]) for oid in reported["observation_ids"]],
        }
        companies[cik] = {
            "registered_ticker": ticker,
            "prices": default_prices,
            "other_prices": [p for p in price_rows if p not in default_prices],
            "price_reason": None if default_prices else "EXACT_REGISTERED_SECURITY_NOT_UNIQUE",
            "reported_12m": eps,
            "four_quarter_diagnostic": assessment["four_quarter_diagnostic"],
            "share_candidates": latest_share_candidates(
                [r for r in rows if r["cik"] == cik], scope["financial_as_of"]
            ),
            "header_links": assessment["security_header_links"],
        }
    return {
        "schema_version": SCHEMA,
        **scope,
        "companies": companies,
        "source_pins": {
            "assessment": assessment_pin,
            "common": reader.manifest["parent"],
            "dataset": dataset_pin,
            "price_export": common["price_export"],
            "supplier_delivery": price_export["delivery"],
        },
        "price_provenance": {
            "supplier": price_export["supplier"],
            "created_at": price_export["created_at"],
            "lineage": price_export["lineage"],
            "producer": price_export["producer"],
            "realtime": False,
            "automatic_update": False,
        },
        "prepared_at": reader.manifest["prepared_at"],
        "common_prepared_at": common["prepared_at"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assessment", "dataset"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asset = build_profile_asset(
        {"path": args.assessment, "sha256": args.assessment_sha256},
        {"path": args.dataset, "sha256": args.dataset_sha256},
    )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encoded(asset))
        handle.flush()
        os.fsync(handle.fileno())
    print(
        json.dumps(
            {
                "path": str(path.absolute()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "companies": len(asset["companies"]),
            }
        )
    )


if __name__ == "__main__":
    main()
