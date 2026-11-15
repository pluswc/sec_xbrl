"""Price worksheet operations and explicit immutable saves, separate from old journal."""
from __future__ import annotations

import copy
import json
import sqlite3
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sec_xbrl.metrics.market_inputs import encoded, identity, pinned_json
from sec_xbrl.metrics.price_related import REGISTRY, fixed_multiple_bands
from sec_xbrl.screening.price_metric_publication import PriceMetricReader


class PriceMetricService:
    def __init__(self, reader: PriceMetricReader, journal_path: str | Path):
        self.reader = reader
        self._evidence_contexts: OrderedDict[str, dict] = OrderedDict()
        self.path = Path(journal_path)
        if not self.path.is_absolute() or any(p.is_symlink() for p in (self.path, *self.path.parents)):
            raise ValueError("price journal requires an absolute non-symlink path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with sqlite3.connect(self.path) as con:
                tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
                if tables != {"price_metric_saves"}:
                    raise ValueError("price journal must be separate from existing screening journal")
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS price_metric_saves (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")

    def capability(self) -> dict:
        pinned_json(self.reader.pin)
        m = self.reader.manifest
        return {"configured": True, **{key: m[key] for key in ("publication_id", "requested_as_of", "price_as_of",
                "staleness_calendar_days", "definitions", "companies", "dataset_scope", "historical_readiness_policy")},
                "publication_pin": self.reader.pin, "automatic_update": False,
                "ev_policy": m["ev_policy"], "series_start": m["series_start"]}

    def _register_evidence_context(self, reader: PriceMetricReader, operation: str,
                                   result: dict) -> str:
        rows = result.get("rows", [])
        allowed = {(row["cik"], row["observation_id"]) for row in rows}
        for company in result.get("results", []):
            allowed.update((company["cik"], c["observation_id"]) for c in company["conditions"] if c.get("observation_id"))
        token = "price-evidence-" + uuid4().hex
        self._evidence_contexts[token] = {
            "reader": reader, "allowed": allowed,
            # Only backend-computed or hash-verified saved scenarios reach here.
            # A client supplies the opaque token/ID, never a calculated row.
            "scenario_rows": {(row["cik"], row["observation_id"]): copy.deepcopy(row)
                              for row in rows} if operation == "bands" else {},
        }
        while len(self._evidence_contexts) > 16:
            self._evidence_contexts.popitem(last=False)
        return token

    def execute(self, operation: str, request: dict) -> dict:
        if not isinstance(request, dict):
            raise TypeError("object request required")
        if operation == "evidence":
            if set(request) - {"cik", "observation_id", "evidence_context"}:
                raise ValueError("evidence accepts only a verified result context and observation identity")
            token = request.get("evidence_context")
            if token is None:
                # Retain the original read-only current-publication query contract.
                return self.reader.evidence(request["cik"], request["observation_id"])
            context = self._evidence_contexts.get(token)
            key = (request["cik"], request["observation_id"])
            if context is None or key not in context["allowed"]:
                raise ValueError("evidence context expired or observation is outside its verified result")
            self._evidence_contexts.move_to_end(token)
            reader = context["reader"]
            if key in context["scenario_rows"]:
                reader.verify_sources()
                result = reader._expand_evidence(context["scenario_rows"][key])
            else:
                result = reader.evidence(*key)
            return {**result, "evidence_context": token}
        result = self._evaluate(self.reader, operation, request)
        return {**result, "evidence_context": self._register_evidence_context(self.reader, operation, result)}

    def _evaluate(self, reader: PriceMetricReader, operation: str, request: dict) -> dict:
        if not isinstance(request, dict):
            raise TypeError("object request required")
        if operation == "query":
            return reader.query(**request)
        if operation == "screen":
            return reader.screen(**request)
        if operation == "bands":
            if set(request) != {"cik", "multiples"}:
                raise ValueError("band request requires company and exact user multiples")
            if set(request["multiples"]) - {"per", "pbr"} or any(not isinstance(v, list) or len(v) > 12 for v in request["multiples"].values()):
                raise ValueError("bounded PER/PBR user multiples required")
            if any(reader.manifest["definitions"].get(mid, {}).get("definition_version") != REGISTRY[mid]["definition_version"]
                   for mid in ("per", "pbr_bps", "fixed_per_band", "fixed_pbr_band")):
                raise ValueError("new band calculation requires compatible declared definition versions")
            query = reader.query(ciks=[request["cik"]], metric_ids=["per", "pbr_bps"], include_lineage=True)
            source = reader._source(reader.manifest["source_pins"]["financial_inputs"])
            by_id = {r["observation_id"]: r for r in source["observations"]}
            for row in query["rows"]:
                row["input_lineage"] = [{**by_id.get(leg.get("observation_id"), {}), **leg} for leg in row["input_lineage"]]
            return {**query, "mode": "bands", "multiples": request["multiples"],
                    "definitions": {mid: reader.manifest["definitions"][mid] for mid in ("fixed_per_band", "fixed_pbr_band")},
                    "rows": fixed_multiple_bands(query["rows"], request["multiples"])}
        raise ValueError("unsupported price operation")

    def save(self, *, kind: str, operation: str, request: dict, title: str, note: str = "") -> dict:
        if kind not in {"CONDITION", "RESULT"} or not isinstance(title, str) or not title.strip() or len(title) > 160 or not isinstance(note, str) or len(note) > 10000:
            raise ValueError("valid explicit save kind/title/note required")
        if operation not in {"query", "screen", "bands"}:
            raise ValueError("only worksheet conditions/results may be saved")
        if kind == "CONDITION" and operation != "screen":
            raise ValueError("condition save requires a screening request")
        result = self._evaluate(self.reader, operation, request)
        self.reader.verify_sources()
        payload = {"schema_version": "price-metric-save-v1", "kind": kind, "operation": operation,
            "request": request, "result": result if kind == "RESULT" else None,
            "title": title.strip(), "note": note, "publication_pin": self.reader.pin,
            "publication_id": self.reader.manifest["publication_id"],
            "source_pins": self.reader.manifest["source_pins"],
            "definition_versions": {mid: d["definition_version"] for mid, d in self.reader.manifest["definitions"].items()}}
        key = "price-save-" + uuid4().hex
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as con:
            con.execute("INSERT INTO price_metric_saves VALUES (?,?,?,?)", (key, now, encoded(payload).decode(), identity(payload)))
        return {"id": key, "created_at": now, **payload}

    def reopen(self, key: str) -> dict:
        with sqlite3.connect(self.path) as con:
            record = con.execute("SELECT created_at,payload,sha256 FROM price_metric_saves WHERE id=?", (key,)).fetchone()
        if record is None:
            raise KeyError(key)
        created, raw, sha = record
        payload = json.loads(raw)
        if identity(payload) != sha:
            raise ValueError("saved price result content hash differs")
        reader = PriceMetricReader(payload["publication_pin"])
        reader.verify_sources()
        if (payload["publication_id"] != reader.manifest["publication_id"]
            or payload["source_pins"] != reader.manifest["source_pins"]
            or payload["definition_versions"] != {mid: d["definition_version"] for mid, d in reader.manifest["definitions"].items()}):
            raise ValueError("saved price source/definition pin differs")
        preview = None
        if payload["kind"] == "CONDITION":
            preview = reader.screen(**payload["request"])
        if payload["kind"] == "RESULT":
            # Verify only the exact saved query files, never scan all history per reopen.
            if payload["operation"] == "query":
                reader.query(**payload["request"])
            else:
                reader.query(ciks=payload["request"].get("ciks") or ([payload["request"]["cik"]] if "cik" in payload["request"] else None))
        context = self._register_evidence_context(reader, payload["operation"], payload["result"] or preview)
        return {"id": key, "created_at": created, **payload, "reopened_original": True,
                "original_context_readonly": True, "original_condition_preview": preview,
                "evidence_context": context, "definition_context": reader.manifest["definitions"],
                "company_context": reader.manifest["companies"]}

    def saves(self) -> list[dict]:
        with sqlite3.connect(self.path) as con:
            records = con.execute("SELECT id,created_at,payload,sha256 FROM price_metric_saves ORDER BY created_at DESC").fetchall()
        output = []
        for key, created, raw, sha in records:
            payload = json.loads(raw)
            if identity(payload) != sha:
                raise ValueError("saved price metadata content hash differs")
            output.append({"id": key, "created_at": created, **{k: payload[k] for k in ("kind", "title", "note", "publication_id")}})
        return output
