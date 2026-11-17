"""Append-only price metrics and one common screening/comparison/time-series query.

Large source price history remains one pinned batch. Daily metric rows reference
that batch plus exact session windows; financial rows reference the shared typed
input table and reviewed compatibility grants, never copy original archives.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import polars as pl

from sec_xbrl.metrics.company_valuation_readiness import validated_company_readiness
from sec_xbrl.metrics.market_inputs import encoded, finite, identity, pinned_json
from sec_xbrl.metrics.price_related import (
    REGISTRY,
    SOURCE_SHA256,
    calculate_price_metrics,
    calculate_valuation_metrics,
    fixed_multiple_bands,
    historical_multiple_percentiles,
    validate_sessions,
)
from sec_xbrl.metrics.reported_quarter_eps import validate_current_evaluation

SCHEMA = "screening-price-metrics-v1"
SOURCE_SHA256_PUBLICATION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _write(path: Path, obj: object) -> dict:
    data = encoded(obj)
    with path.open("xb") as handle:
        handle.write(data)
    return {"path": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _write_rows(path: Path, rows: list[dict]) -> dict:
    # Lossless row payloads retain the versioned logical contract, while Parquet
    # compression avoids repeating field names/pins across every daily observation.
    frame = pl.DataFrame({"metric_id": [r.get("metric_id") for r in rows],
                          "as_of": [r.get("as_of") for r in rows],
                          "payload": [encoded(row).decode() for row in rows]},
                         schema={"metric_id": pl.String, "as_of": pl.String, "payload": pl.String})
    frame.write_parquet(path, compression="zstd")
    data = path.read_bytes()
    return {"path": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "format": "PARQUET_JSON_ROWS", "rows": len(rows)}


def _grant_for(grants: list[dict], cik: str, sid: str, day: str) -> dict | None:
    candidates = [g for g in grants if g.get("cik") == cik and g.get("security_id") == sid
                  and g.get("known_on") and g["known_on"] <= day
                  and (not g.get("valid_until") or day <= g["valid_until"])]
    if not candidates:
        return None
    newest = max(g["known_on"] for g in candidates)
    latest = [g for g in candidates if g["known_on"] == newest]
    if len(latest) != 1:
        raise ValueError("ambiguous compatibility grants for company/session")
    return latest[0]


def _compact(row: dict, batch_pin: dict) -> dict:
    result = copy.deepcopy(row)
    if row["metric_id"].startswith(("price_return_", "price_volatility_")) or row["metric_id"] == "relative_volume_20s":
        result["input_lineage"] = [{"source_ref": "price_batch", "security_id": row["security_id"],
                                    "start_session": row.get("window_start"), "end_session": row["as_of"],
                                    "session_count": row.get("window_sessions", 0) + 1,
                                    "ordered_input_ids_sha256": row["input_lineage"][0].get("ordered_input_ids_sha256")}]
    else:
        result["input_lineage"] = [{k: leg.get(k) for k in ("input_role", "observation_id", "trade_date", "security_id") if k in leg}
                                   for leg in row["input_lineage"]]
    # Content identity covers the actual published compact contract. Sources remain
    # immutable pins, and detailed input values resolve through the common reader.
    result.pop("observation_id")
    result["observation_id"] = "price-metric-" + identity(result)
    return result


def publish_price_metrics(config_pin: dict, output: str | Path) -> dict:
    """Materialize daily results offline. Existing publications are never rewritten."""
    producer_sources = {Path(__file__): SOURCE_SHA256_PUBLICATION,
                        Path(calculate_price_metrics.__code__.co_filename): SOURCE_SHA256}
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha in producer_sources.items()):
        raise ValueError("producer source changed since module import; reload frozen source")
    config = pinned_json(config_pin)
    if config.get("schema_version") != "screening-price-metrics-config-v1":
        raise ValueError("unsupported price metrics configuration")
    batch, session_source = pinned_json(config["price_batch"]), pinned_json(config["sessions"])
    if batch.get("schema_version") != "price-metric-canonical-batch-v1" or batch.get("price_batch_calls") != 1:
        raise ValueError("shared canonical batch required")
    for pin in session_source["source_pins"]:
        pinned_json(pin)
    sessions = validate_sessions(session_source)
    requested, selected = config["requested_as_of"], config["price_as_of"]
    date.fromisoformat(requested)
    if selected not in sessions or selected > requested or selected > batch["query"]["end_date"]:
        raise ValueError("explicit completed price session differs from input scope")
    if config.get("session_selection_policy") != "EXPLICIT_COMPLETED_SESSION":
        raise ValueError("explicit session selection required")
    source = pinned_json(config["financial_inputs"])
    if source.get("schema_version") != "price-financial-input-bundle-v1":
        raise ValueError("typed financial input bundle required")
    grants, observations = source["compatibility_grants"], source["observations"]
    readiness = validated_company_readiness(source)
    evaluation = None
    if "current_eps_evaluation" in config:
        evaluation = validate_current_evaluation(config["current_eps_evaluation"], bundle_pin=config["financial_inputs"],
            batch_pin=config["price_batch"], requested=requested, selected=selected)
    eps_diagnostics = source.get("current_eps_diagnostics", [])
    for grant in grants:
        if not grant.get("evidence_pins"):
            raise ValueError("compatibility grant requires actual evidence pins")
        for pin in grant["evidence_pins"]:
            pinned_json(pin)
    policy = config["historical_readiness_policy"]
    if policy not in {"READY_ONLY", "DIAGNOSTIC_FILED_DAY"}:
        raise ValueError("explicit historical readiness policy required")
    if policy == "DIAGNOSTIC_FILED_DAY":
        declaration = config.get("historical_policy", {})
        if declaration.get("version") != "price-historical-filed-day-diagnostic-v1" or declaration.get("approved") is not True or not declaration.get("evidence_pins"):
            raise ValueError("filed-day diagnostic publication requires explicit policy approval evidence")
        for pin in declaration["evidence_pins"]:
            pinned_json(pin)
    if config.get("ev_policy", {}).get("approved"):
        if not config["ev_policy"].get("evidence_pins"):
            raise ValueError("approved EV policy requires actual evidence pins")
        for pin in config["ev_policy"]["evidence_pins"]:
            pinned_json(pin)
    destination = Path(output).absolute()
    if destination.exists():
        raise FileExistsError("append-only price publication already exists")
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("publication destination must not traverse a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".partial-price-metrics-", dir=destination.parent))
    try:
        grouped, financial = defaultdict(list), defaultdict(list)
        for price in batch["prices"]:
            grouped[price["security_id"]].append(price)
        for row in observations:
            financial[row["cik"]].append(row)
        series_days = [d for d in sessions if config["series_start"] <= d <= selected]
        historical_days = [d for d in sessions if config["historical_start"] <= d <= selected]
        if not series_days or not historical_days:
            raise ValueError("empty series/historical window")
        companies, files, counts = [], {}, defaultdict(int)
        series_day_set = set(series_days)
        for company in batch["companies"]:
            cik, sid = company["cik"], company["security_id"]
            companies.append(company)
            if sid is None:
                payload = {"company": company, "latest": [], "series": [], "historical": [],
                           "bands": [], "coverage": [], "reason": company["reason"]}
            else:
                prices = grouped[sid]
                by_day = {p["trade_date"]: p for p in prices}
                if len(by_day) != len(prices):
                    raise ValueError("duplicate shared batch price")
                series = []
                history = []
                latest_valuation = []
                has_grants = any(g["cik"] == cik and g["security_id"] == sid for g in grants)
                # Historical ratios use each day's eligible evidence grant, never
                # today's denominator against an old price. Missing days persist.
                for day in historical_days:
                    grant = _grant_for(grants, cik, sid, day)
                    anchors = [a for a in source.get("financial_anchors", []) if a["cik"] == cik and a["known_on"] <= day]
                    anchor = max(anchors, key=lambda a: (a["period_end"], a["known_on"]))["period_end"] if anchors else None
                    vals = calculate_valuation_metrics(by_day.get(day), financial[cik], grant,
                        cik=cik, security_id=sid, as_of=day, ev_policy=config.get("ev_policy"), financial_anchor=anchor,
                        financial_as_of=readiness.get(cik, {}).get("verified_through", source.get("financial_as_of"))) if has_grants or day == selected else []
                    history.extend(_compact(row, config["price_batch"]) for row in vals
                                   if row["metric_id"] in {"per", "pbr", "pbr_bps", "price_sales", "ev_revenue", "ev_ebitda"})
                    if day in series_day_set:
                        price_metrics = calculate_price_metrics(prices, session_source, cik=cik,
                            security_id=sid, as_of=day, volume_basis=batch.get("volume_basis"))
                        series.extend(_compact(row, config["price_batch"]) for row in [*price_metrics, *vals])
                    if day == selected:
                        latest_valuation = vals
                latest = [copy.deepcopy(row) if evaluation else row for row in series if row["as_of"] == selected]
                if evaluation and any(r["cik"] == cik and r["observation_id"] in evaluation["input_ids"] for r in financial[cik]):
                    # Current snapshots are separate from the already materialized
                    # daily series/history. Only EPS-dependent current values change.
                    current = calculate_valuation_metrics(by_day.get(selected), financial[cik], grant,
                        cik=cik, security_id=sid, as_of=selected, ev_policy=config.get("ev_policy"),
                        financial_anchor=anchor, financial_as_of=readiness.get(cik, {}).get("verified_through", source.get("financial_as_of")),
                        current_eps_evaluation={"declaration": config["current_eps_evaluation"], "financial_inputs": config["financial_inputs"],
                            "price_batch": config["price_batch"], "requested_as_of": requested})
                    replacements = {r["metric_id"]: r for r in current if r["metric_id"] in {"per", "earnings_yield"}}
                    latest_valuation = [replacements.get(r["metric_id"], r) for r in latest_valuation]
                    latest = [_compact(replacements[r["metric_id"]], config["price_batch"]) if r["metric_id"] in replacements else r for r in latest]
                diagnostic = next((d for d in eps_diagnostics if d["cik"] == cik), None)
                if evaluation and diagnostic:
                    for rows in (latest, latest_valuation):
                        for row in rows:
                            if row["metric_id"] in {"per", "earnings_yield"} and row["status"] == "UNAVAILABLE":
                                row.update(reason=diagnostic["reason"], eps_diagnostic=diagnostic)
                                row.pop("observation_id")
                                row["observation_id"] = "price-metric-" + identity(row)
                for multiple in ("per", "pbr", "pbr_bps", "price_sales", "ev_revenue", "ev_ebitda"):
                    latest.append(historical_multiple_percentiles(history, cik=cik, security_id=sid,
                        as_of=selected, multiple=multiple, readiness_policy=policy, session_source=session_source,
                        source_coverage={"start": batch["query"]["start_date"], "end": batch["query"]["end_date"]}))
                bands = fixed_multiple_bands(latest_valuation, config.get("fixed_multiples", {}))
                coverage = [] if has_grants else [{"cik": cik, "security_id": sid,
                    "metric_ids": [mid for mid, d in REGISTRY.items() if d["family"] == "VALUATION"],
                    "start": historical_days[0], "end": selected, "expected_sessions": len(historical_days),
                    "status": "UNAVAILABLE", "reason": "CLASS_CURRENCY_SPLIT_COMPATIBILITY_NOT_APPROVED",
                    "grain": "US_SESSION", "session_source_ref": "sessions", "input_source_ref": "financial_inputs"}]
                payload = {"company": company, "latest": latest, "series": series, "historical": history,
                           "bands": bands, "coverage": coverage, "reason": None}
                for row in latest:
                    counts[row["status"]] += 1
            files[cik] = {mode: _write_rows(staging / f"{cik}.{mode}.parquet", payload[mode])
                          for mode in ("latest", "series", "historical", "bands")}
            files[cik]["coverage"] = _write(staging / f"{cik}.coverage.json", payload["coverage"])
        manifest = {"schema_version": SCHEMA, "config": config_pin, "requested_as_of": requested,
            "price_as_of": selected, "staleness_calendar_days": (date.fromisoformat(requested)-date.fromisoformat(selected)).days,
            "session_selection_policy": config["session_selection_policy"],
            "source_pins": {key: config[key] for key in ("price_batch", "sessions", "financial_inputs")},
            "dataset_scope": config["dataset_scope"], "companies": companies, "files": files,
            "definitions": REGISTRY, "historical_readiness_policy": policy, "historical_policy": config.get("historical_policy"),
            "ev_policy": config.get("ev_policy"), "fixed_multiples": config.get("fixed_multiples", {}),
            "series_start": config["series_start"], "historical_start": config["historical_start"],
            "counts": dict(counts), "automatic_update": False,
            "producer": {"publication_sha256": SOURCE_SHA256_PUBLICATION, "metrics_sha256": SOURCE_SHA256}}
        if readiness:
            manifest["company_financial_readiness"] = readiness
        if source.get("q4_component_derivation"):
            manifest["source_pins"]["q4_component_derivation"] = source["q4_component_derivation"]
        if evaluation:
            manifest["current_eps_evaluation"] = evaluation
            manifest["current_eps_diagnostics"] = eps_diagnostics
            manifest["source_pins"].update({k: source[k] for k in ("reported_quarter_derivation", "q4_component_derivation") if source.get(k)})
            manifest["source_pins"].update(current_evaluation_policy=config["current_eps_evaluation"]["policy"],
                current_evaluation_approval=config["current_eps_evaluation"]["approval"])
        for pin in [config_pin, *manifest["source_pins"].values()]:
            pinned_json(pin)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != sha for path, sha in producer_sources.items()):
            raise ValueError("producer source changed during materialization")
        manifest["publication_id"] = "screening-price-metrics-" + identity(manifest)[:24]
        manifest["prepared_at"] = datetime.now(UTC).isoformat()
        _write(staging / "price_metric_manifest.json", manifest)
        PriceMetricReader({"path": str(staging / "price_metric_manifest.json"), "sha256": identity(manifest)}).verify_all()
        os.rename(staging, destination)
        return {"path": str(destination / "price_metric_manifest.json"), "sha256": identity(manifest),
                "publication_id": manifest["publication_id"], "counts": dict(counts)}
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


class PriceMetricReader:
    """Storage-neutral common query over prepared values, with exact publication pin."""

    def __init__(self, pin: dict):
        self.pin = dict(pin)
        self.manifest = pinned_json(pin)
        if self.manifest.get("schema_version") != SCHEMA:
            raise ValueError("unsupported price metric publication")
        self.root = Path(pin["path"]).parent

    def _read_rows(self, cik: str, mode: str) -> list[dict]:
        ref = self.manifest["files"][cik][mode]
        if Path(ref["path"]).name != ref["path"]:
            raise ValueError("price publication path escapes root")
        pin = {"path": str(self.root / ref["path"]), "sha256": ref["sha256"]}
        if ref.get("format") == "PARQUET_JSON_ROWS":
            path = Path(pin["path"])
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
                raise ValueError("price row artifact hash differs")
            return [json.loads(value) for value in pl.read_parquet(path, columns=["payload"])["payload"].to_list()]
        return pinned_json(pin)

    def verify_sources(self) -> None:
        pinned_json(self.pin)
        for pin in self.manifest["source_pins"].values():
            self._source(pin)

    @staticmethod
    @lru_cache(maxsize=8)
    def _cached_source(path: str, sha256: str, stat: tuple) -> dict:
        return pinned_json({"path": path, "sha256": sha256})

    def _source(self, pin: dict) -> dict:
        path = Path(pin["path"])
        if path.is_symlink():
            raise ValueError("source pin aliases are forbidden")
        st = path.stat()
        return self._cached_source(pin["path"], pin["sha256"],
                                   (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))

    def q4_eps(self, cik: str, flavor: str | None = None) -> dict:
        """Read prepared basic/diluted quarter diagnostics without source rederivation."""
        pinned_json(self.pin)
        if cik not in self.manifest["files"] or flavor not in {None, "basic", "diluted"}:
            raise ValueError("unknown company or Q4 EPS flavor")
        pin = self.manifest["source_pins"].get("q4_component_derivation")
        result = {"schema_version": "common-q4-eps-prepared-query-v1", "publication_id": self.manifest["publication_id"],
                  "publication_pin": self.pin, "cik": cik, "flavor": flavor,
                  "derivation_pin": pin, "rows": []}
        if not pin:
            return dict(result, status="UNAVAILABLE", reason="COMMON_Q4_EPS_ARTIFACT_NOT_PUBLISHED")
        artifact = self._source(pin)
        if artifact.get("schema_version") != "governed-common-q4-eps-v1":
            raise ValueError("prepared Q4 EPS derivation schema differs")
        return dict(result, status="PREPARED", reason=None, source_projection=artifact["source_projection"],
                    prepared_at=artifact["prepared_at"], public_cutoff=artifact["public_cutoff"],
                    rows=copy.deepcopy([r for r in artifact["quarter_results"] if r["cik"] == cik
                                        and (flavor is None or r["flavor"] == flavor)]),
                    holds=copy.deepcopy([r for r in artifact["holds"] if r["cik"] == cik]))

    def query(self, *, ciks: list[str] | None = None, metric_ids: list[str] | None = None,
              mode: str = "latest", start: str | None = None, end: str | None = None,
              include_lineage: bool = False) -> dict:
        if mode not in {"latest", "series", "historical", "bands"}:
            raise ValueError("unknown price query mode")
        pinned_json(self.pin)
        selected = ciks if ciks is not None else list(self.manifest["files"])
        if len(selected) != len(set(selected)) or any(cik not in self.manifest["files"] for cik in selected):
            raise ValueError("unknown/duplicate company")
        if metric_ids is not None and any(mid not in self.manifest["definitions"] for mid in metric_ids):
            raise ValueError("unknown price metric")
        for day in (start, end):
            if day is not None:
                date.fromisoformat(day)
        rows = [r for cik in selected for r in self._read_rows(cik, mode)
                if (metric_ids is None or r["metric_id"] in metric_ids)
                and (start is None or r["as_of"] >= start) and (end is None or r["as_of"] <= end)]
        if not include_lineage:
            rows = [{k: v for k, v in row.items() if k != "input_lineage"} for row in rows]
        return {"publication_id": self.manifest["publication_id"], "publication_pin": self.pin,
                "source_pins": self.manifest["source_pins"],
                "requested_as_of": self.manifest["requested_as_of"], "price_as_of": self.manifest["price_as_of"],
                "staleness_calendar_days": self.manifest["staleness_calendar_days"], "mode": mode,
                "definitions": {mid: d for mid, d in self.manifest["definitions"].items() if metric_ids is None or mid in metric_ids},
                **({"dataset_scope": self.manifest["dataset_scope"],
                    "company_financial_readiness": {cik: r for cik, r in self.manifest["company_financial_readiness"].items() if cik in selected}}
                   if "company_financial_readiness" in self.manifest else {}),
                **({"current_eps_evaluation": self.manifest["current_eps_evaluation"],
                    "current_eps_diagnostics": [d for d in self.manifest.get("current_eps_diagnostics", []) if d["cik"] in selected]}
                   if "current_eps_evaluation" in self.manifest else {}),
                "rows": rows, "unavailable_ranges": [r for cik in selected for r in self._read_rows(cik, "coverage")
                    if metric_ids is None or set(metric_ids) & set(r["metric_ids"])]}

    def screen(self, conditions: list[dict], *, ciks: list[str] | None = None) -> dict:
        """Exact-decimal parallel conditions; missing data stays an explained result."""
        mids = [c["metric_id"] for c in conditions]
        if not mids or len(mids) > 32:
            raise ValueError("one to32 ordered screening conditions required")
        if any(self.manifest["definitions"].get(mid, {}).get("family") in {"HISTORICAL_MULTIPLE", "FIXED_BAND"} for mid in mids):
            raise ValueError("historical distributions and user scenarios are not screening scalars")
        ops = {"gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b,
               "gt": lambda a, b: a > b, "lt": lambda a, b: a < b, "eq": lambda a, b: a == b}
        for c in conditions:
            if c.get("operator") not in ops or finite(c.get("value")) is None:
                raise ValueError("finite threshold/operator required")
        query = self.query(ciks=ciks, metric_ids=list(dict.fromkeys(mids)))
        by_cik = defaultdict(dict)
        for row in query["rows"]:
            by_cik[row["cik"]][row["metric_id"]] = row
        results = []
        for company in self.manifest["companies"]:
            cik = company["cik"]
            if ciks is not None and cik not in ciks:
                continue
            checks = []
            for c in conditions:
                row = by_cik[cik].get(c["metric_id"])
                if row is None or row["status"] != "AVAILABLE":
                    checks.append({**c, "status": "UNAVAILABLE", "reason": (row or {}).get("reason", company.get("reason") or "METRIC_NOT_PREPARED"), "value_observed": None})
                else:
                    checks.append({**c, "status": "PASS" if ops[c["operator"]](Decimal(row["value"]), Decimal(c["value"])) else "FAIL",
                                   "reason": None, "value_observed": row["value"], "observation_id": row["observation_id"]})
            status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "UNAVAILABLE" if any(c["status"] == "UNAVAILABLE" for c in checks) else "PASS"
            results.append({"cik": cik, "ticker": company["ticker"], "status": status, "conditions": checks})
        return {**{k: v for k, v in query.items() if k != "rows"}, "conditions": conditions, "results": results}

    def evidence(self, cik: str, observation_id: str) -> dict:
        rows = [row for key in ("latest", "series", "historical", "bands") for row in self._read_rows(cik, key)
                if row["observation_id"] == observation_id]
        if not rows:
            raise KeyError(observation_id)
        return self._expand_evidence(rows[0])

    def _diagnostic_evidence(self, pin: dict, diagnostic: dict, cik: str) -> dict:
        data = self._source(pin)
        if data.get("schema_version") != "governed-common-q4-eps-v1":
            return data
        ids = {d["candidate_id"] for d in diagnostic.get("details", []) if d.get("candidate_id")}
        quarters = [r for r in data["quarter_results"] if r["cik"] == cik and (not ids or r["candidate_id"] in ids)]
        keys = {key for q in quarters for key in q["source_fact_keys"]}
        return {"schema_version": data["schema_version"], "artifact_pin": pin,
                "source_projection": data["source_projection"], "rule_version": data["rule_version"],
                "prepared_at": data["prepared_at"], "quarter_results": quarters,
                "observations": [r for r in data["observations"] if r["cik"] == cik],
                "holds": [r for r in data["holds"] if r["cik"] == cik],
                "source_rows": [r for r in data["source_rows"] if r["fact_key"] in keys]}

    def _expand_evidence(self, row: dict) -> dict:
        """Expand a stored row or a service-owned verified scenario, never client values."""
        pinned_json(self.pin)
        source = self._source(self.manifest["source_pins"]["financial_inputs"])
        lineage = list(row["input_lineage"])
        historical_inputs = []
        if row["metric_id"].startswith("historical_"):
            referenced = {leg.get("observation_id") for leg in lineage}
            historical_inputs = [r for r in self._read_rows(row["cik"], "historical") if r["observation_id"] in referenced]
            if {r["observation_id"] for r in historical_inputs} != referenced:
                raise ValueError("historical multiple input identity differs")
            lineage = [leg for r in historical_inputs for leg in r["input_lineage"]]
        ids = {leg.get("observation_id") for leg in lineage}
        financial_inputs = [r for r in source["observations"] if r["observation_id"] in ids]
        quarter_sources = {}
        if any(r.get("source_kind") == "GOVERNED_DIRECT_QTD_TTM" for r in financial_inputs):
            # Read the pinned published derivation; consumers never reparse/rederive.
            artifact = self._source(source["reported_quarter_derivation"])
            quarter_ids = {ref["observation_id"] for r in financial_inputs for ref in r.get("source_refs", [])}
            quarter_sources = {oid: r for oid, r in artifact["reported_quarter_sources"].items() if oid in quarter_ids}
        component_evidence = {}
        if any(r.get("source_kind") == "GOVERNED_Q4_COMPONENT_TTM" for r in financial_inputs):
            artifact = self._source(source["q4_component_derivation"])
            candidate_ids = {r["q4_candidate_id"] for r in financial_inputs if r.get("q4_candidate_id")}
            component_evidence = {"derivation": source["q4_component_derivation"],
                "quarters": [r for r in artifact["quarter_results"] if r["candidate_id"] in candidate_ids],
                "source_rows": [r for r in artifact["source_rows"] if any(r["fact_key"] in q.get("source_fact_keys", [])
                    for row in financial_inputs for q in row.get("source_refs", []))]}
        price_inputs, expected = {}, set()
        batch = None
        price_by_id = None
        for leg in lineage:
            if leg.get("source_ref") == "price_batch":
                batch = batch or self._source(self.manifest["source_pins"]["price_batch"])
                for price in batch["prices"]:
                    if price["security_id"] == leg["security_id"] and leg["start_session"] <= price["trade_date"] <= leg["end_session"]:
                        price_inputs[price["observation_id"]] = price
                calendar = self._source(self.manifest["source_pins"]["sessions"])
                expected.update(d for d in calendar["sessions"] if leg["start_session"] <= d <= leg["end_session"])
            elif leg.get("input_role") == "as_traded_close" and leg.get("observation_id"):
                batch = batch or self._source(self.manifest["source_pins"]["price_batch"])
                if price_by_id is None:
                    price_by_id = {p["observation_id"]: p for p in batch["prices"]}
                    if len(price_by_id) != len(batch["prices"]):
                        raise ValueError("ambiguous quoted price observation identity")
                price = price_by_id.get(leg["observation_id"])
                if price is None or price["security_id"] != leg.get("security_id") or price["trade_date"] != leg.get("trade_date"):
                    raise ValueError("exact quoted numerator identity differs from pinned shared batch")
                price_inputs[price["observation_id"]] = price
                expected.add(price["trade_date"])
        return {"row": copy.deepcopy(row), "publication_id": self.manifest["publication_id"],
                "publication_pin": self.pin, "definitions": self.manifest["definitions"],
                "financial_inputs": financial_inputs,
                **({"reported_quarter_sources": quarter_sources} if quarter_sources else {}),
                **({"q4_component_evidence": component_evidence} if component_evidence else {}),
                **({"current_eps_evaluation": row["current_eps_evaluation"]} if "current_eps_evaluation" in row else {}),
                **({"eps_diagnostic": row["eps_diagnostic"], "diagnostic_evidence": [self._diagnostic_evidence(pin, row["eps_diagnostic"], row["cik"]) for pin in row["eps_diagnostic"]["evidence_pins"]]}
                   if "eps_diagnostic" in row else {}),
                "price_inputs": sorted(price_inputs.values(), key=lambda p: (p["trade_date"], p["security_id"])),
                "expected_sessions": sorted(expected), "historical_multiple_inputs": historical_inputs,
                "compatibility_grant": next((g for g in source["compatibility_grants"]
                    if identity(g) == row.get("compatibility_grant_id")), None),
                "source_pins": self.manifest["source_pins"], "ev_policy": self.manifest["ev_policy"]}

    def verify_all(self) -> None:
        for cik in self.manifest["files"]:
            for mode in ("latest", "series", "historical", "bands", "coverage"):
                self._read_rows(cik, mode)
        self.verify_sources()
