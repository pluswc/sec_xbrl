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
                        financial_as_of=source.get("financial_as_of")) if has_grants or day == selected else []
                    history.extend(_compact(row, config["price_batch"]) for row in vals
                                   if row["metric_id"] in {"per", "pbr", "pbr_bps", "price_sales", "ev_revenue", "ev_ebitda"})
                    if day in series_day_set:
                        price_metrics = calculate_price_metrics(prices, session_source, cik=cik,
                            security_id=sid, as_of=day, volume_basis=batch.get("volume_basis"))
                        series.extend(_compact(row, config["price_batch"]) for row in [*price_metrics, *vals])
                    if day == selected:
                        latest_valuation = vals
                latest = [row for row in series if row["as_of"] == selected]
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
        source = self._source(self.manifest["source_pins"]["financial_inputs"])
        ids = {leg.get("observation_id") for leg in rows[0]["input_lineage"]}
        price_inputs = []
        expected = []
        for leg in rows[0]["input_lineage"]:
            if leg.get("source_ref") == "price_batch":
                batch = self._source(self.manifest["source_pins"]["price_batch"])
                price_inputs = [p for p in batch["prices"] if p["security_id"] == leg["security_id"]
                                and leg["start_session"] <= p["trade_date"] <= leg["end_session"]]
                calendar = self._source(self.manifest["source_pins"]["sessions"])
                expected = [d for d in calendar["sessions"] if leg["start_session"] <= d <= leg["end_session"]]
        return {"row": rows[0], "financial_inputs": [r for r in source["observations"] if r["observation_id"] in ids],
                "price_inputs": price_inputs, "expected_sessions": expected,
                "compatibility_grant": next((g for g in source["compatibility_grants"]
                    if identity(g) == rows[0].get("compatibility_grant_id")), None),
                "source_pins": self.manifest["source_pins"], "ev_policy": self.manifest["ev_policy"]}

    def verify_all(self) -> None:
        for cik in self.manifest["files"]:
            for mode in ("latest", "series", "historical", "bands", "coverage"):
                self._read_rows(cik, mode)
        self.verify_sources()
