"""Offline batch adoption, typed financial binding and immutable price publication.

No capture/network logic; the supplier's CanonicalQuery is imported only for the
explicit batch-adoption command. All generated outputs are create-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from sec_xbrl.metrics.company_valuation_readiness import validated_company_readiness
from sec_xbrl.metrics.market_inputs import encoded, pinned_json
from sec_xbrl.metrics.price_batch import canonical_price_batch
from sec_xbrl.metrics.price_financial_inputs import (
    bind_financial_inputs,
    project_additional_candidates,
)
from sec_xbrl.screening.price_metric_publication import PriceMetricReader, publish_price_metrics


def write_new(path: str | Path, value: object) -> dict:
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = encoded(value)
    with path.open("xb") as handle:
        handle.write(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def bind_bundle(config_pin: dict) -> dict:
    config = pinned_json(config_pin)
    if config.get("schema_version") != "price-financial-binding-config-v1":
        raise ValueError("unsupported binding configuration")
    candidates = [row for pin in config["candidate_pins"] for row in pinned_json(pin)]
    anchors = pinned_json(config["financial_anchors"])
    cutoff = config["financial_as_of"]
    date.fromisoformat(cutoff)
    observations, grants = [], []
    candidate_groups = {}
    for row in candidates:
        candidate_groups.setdefault(row["observation_id"], []).append(row)
    approved_pool_cache = {}
    for binding in config["bindings"]:
        receipt = pinned_json(binding["approval"])
        if (receipt.get("schema_version") != "price-metrics-root-binding-acceptance-v1"
            or receipt.get("reviewer") != "ROOT"
            or receipt.get("status") != "APPROVED_FOR_EXACT_TYPED_BINDING"
            or receipt.get("proposal") != binding["proposal"]):
            raise ValueError("binding requires explicit exact lead approval receipt")
        proposal = pinned_json(binding["proposal"])
        declared = binding["declarations"]
        if proposal.get("schema_version") == "price-financial-binding-proposal-v1":
            approved = proposal["declarations"]
        elif proposal.get("schema_version") == "price-historical-pbr-binding-proposal-v1":
            matches = [r["declarations"] for r in proposal["records"] if r["declarations"] == declared]
            if len(matches) != 1:
                raise ValueError("historical declaration differs from exact approved record")
            approved = matches[0]
        else:
            raise ValueError("unsupported exact binding proposal")
        if declared != approved or not approved:
            raise ValueError("declaration differs from exact approved proposal")
        if "source_role_proofs" in proposal:
            source_pins = proposal.get("source_pins", {}).get("candidate_pins", [])
            if not source_pins:
                raise ValueError("exact source proof requires pinned candidate pools")
            approved_pools = []
            for pin in source_pins:
                key = (pin["path"], pin["sha256"])
                if key not in approved_pool_cache:
                    pool = pinned_json(pin)
                    index = {}
                    for row in pool["candidates"] if isinstance(pool, dict) else pool:
                        oid = row["observation_id"]
                        if oid in index and index[oid] != row:
                            raise ValueError("conflicting approved candidate pool identities")
                        index[oid] = row
                    approved_pool_cache[key] = index
                approved_pools.append(approved_pool_cache[key])
            for oid in {oid for d in approved for oid in d.get("candidate_ids", [])}:
                exact = [pool[oid] for pool in approved_pools if oid in pool]
                if (len(candidate_groups.get(oid, [])) != 1 or not exact
                    or any(candidate_groups[oid][0] != row for row in exact)):
                    raise ValueError("flat candidate differs from exact approved source pool row")
        g = binding["compatibility_grant"]
        first = approved[0]
        if any(any(d.get(k) != first.get(k) for k in ("cik", "currency", "scope_id", "stock_class_id", "split_basis_id", "known_on", "period_end")) for d in approved):
            raise ValueError("approved scope must be homogeneous")
        required = {"cik": first["cik"], "currency": first["currency"],
            "stock_class_id": first["stock_class_id"], "split_basis_id": first["split_basis_id"],
            "financial_scope_id": first["scope_id"], "known_on": first["known_on"],
            "financial_anchor": first["period_end"], "ready_on": None,
            "common_valuation_scope": "EXACT_COMMON_CLASS_OR_APPROVED_ISSUER_AGGREGATION",
            "invalid_after_newer_financial_anchor": True,
            "required_price_split_factor": proposal.get("grant_constraints", {}).get("price_split_factor", proposal.get("required_price_split_factor"))}
        if any(g.get(k) != value for k, value in required.items()) or not required["required_price_split_factor"]:
            raise ValueError("compatibility grant widens approved scope or basis")
        # Exact registered security is bound by the reviewed common class evidence;
        # declarations/proposals never authorize a different exchange identity.
        approved_security = receipt.get("security_id") or proposal.get("security_id")
        if not approved_security:
            raise ValueError("lead receipt must explicitly bind the approved security ID")
        if g.get("security_id") != approved_security:
            raise ValueError("security differs from approved class identity")
        newer = [a["known_on"] for a in anchors if a["cik"] == first["cik"]
                 and a["period_end"] > first["period_end"] and a["known_on"] > first["known_on"]]
        expiry = (date.fromisoformat(min(newer)) - timedelta(days=1)).isoformat() if newer else None
        if g.get("valid_until") != expiry:
            raise ValueError("grant expiry differs from next known financial anchor")
        declarations = [{**d, "evidence_pins": [binding["approval"], binding["proposal"]]} for d in approved]
        prepared = bind_financial_inputs(candidates, declarations)
        observations.extend(prepared)
        grants.append({**g, "schema_version": "price-financial-compatibility-v1",
                       "input_ids": {r["role"]: r["observation_id"] for r in prepared},
                       "evidence_pins": [binding["approval"], binding["proposal"]]})
    if len({row["observation_id"] for row in observations}) != len(observations):
        raise ValueError("duplicate typed input bindings")
    anchors = pinned_json(config["financial_anchors"])
    bundle = {"schema_version": "price-financial-input-bundle-v1",
            "producer": {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "binding_rule_sha256": hashlib.sha256(Path(bind_financial_inputs.__code__.co_filename).read_bytes()).hexdigest()},
            "observations": observations,
            "compatibility_grants": grants, "financial_anchors": anchors, "financial_as_of": cutoff,
            "source_pins": {"binding_config": config_pin, "candidate_pins": config["candidate_pins"],
                            "financial_anchors": config["financial_anchors"]}}
    if config.get("company_readiness"):
        bundle["company_readiness"] = config["company_readiness"]
        validated_company_readiness(bundle)
    return bundle


def financial_anchors(common_pin: dict) -> list[dict]:
    """Issuer report dates from the existing discovery/intake contract, no rediscovery."""
    common = pinned_json(common_pin)
    output = []
    for company in common["companies"]:
        intake = pinned_json(company["intake"])
        for item in intake.get("filings", []):
            filing = item.get("filing", item)
            if filing.get("form") not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                continue
            report, filed = filing.get("report_date"), filing.get("filed_date")
            if not report or not filed or filed > common["financial_as_of"]:
                continue
            end = (date.fromisoformat(report) + timedelta(days=1)).isoformat()
            output.append({"cik": company["cik"], "known_on": filed, "period_end": end,
                           "accession": filing.get("accession"), "form": filing["form"], "intake": company["intake"]})
    return sorted(output, key=lambda r: (r["cik"], r["known_on"], r["period_end"], r.get("accession") or ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("batch", "project", "bind", "publish", "anchors"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--config", required=True)
        cmd.add_argument("--sha256", required=True)
        cmd.add_argument("--output", required=True)
    query = commands.add_parser("query")
    query.add_argument("--manifest", required=True)
    query.add_argument("--sha256", required=True)
    query.add_argument("--request", required=True, help="JSON request file")
    args = parser.parse_args()
    if args.command == "query":
        result = PriceMetricReader({"path": args.manifest, "sha256": args.sha256}).query(**json.loads(Path(args.request).read_bytes()))
    else:
        pin = {"path": args.config, "sha256": args.sha256}
        config = pinned_json(pin)
        if args.command == "publish":
            result = publish_price_metrics(pin, args.output)
        elif args.command == "bind":
            result = write_new(args.output, bind_bundle(pin))
        elif args.command == "anchors":
            result = write_new(args.output, financial_anchors(pin))
        elif args.command == "project":
            rows = []
            for company in config["companies"]:
                for mode in config.get("period_modes", ["annual", "quarterly"]):
                    if company.get(mode):
                        rows.extend(project_additional_candidates(company[mode], cik=company["cik"],
                                    ticker=company["ticker"], cutoff=config["financial_as_of"]))
            result = write_new(args.output, rows)
        else:
            from market_data_pipeline.delivery import verify_delivery_manifest
            from market_data_pipeline.query import CanonicalQuery
            batch = canonical_price_batch(CanonicalQuery(config["supplier_root"]), verify_delivery_manifest,
                delivery_pin=config["delivery"], companies=config["companies"], start=config["start"], end=config["end"],
                currency_pin=config.get("currency"), currency_manifest_pin=config.get("currency_manifest"))
            batch["producer"] = {"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                 "config": pin, "batch_rule_sha256": hashlib.sha256(Path(canonical_price_batch.__code__.co_filename).read_bytes()).hexdigest()}
            result = write_new(args.output, batch)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
