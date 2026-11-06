"""Recoverable local journal visibility; run only with an explicit existing SQLite store.

Original ScreeningStore records remain authoritative and immutable. This companion
owns only lifecycle events and the visible projection, never financial evaluation.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sec_xbrl.screening.store import SCHEMA, STORE_VERSION, ScreeningStore

MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
TABLE = "journal_lifecycle_events"
LIFECYCLE_SCHEMA = """CREATE TABLE journal_lifecycle_events (
 sequence INTEGER PRIMARY KEY,
 schema_version INTEGER NOT NULL CHECK(schema_version=1),
 record_kind TEXT NOT NULL CHECK(record_kind IN ('REVISION','RUN','DECISION')),
 record_id TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('DELETE','RESTORE')),
 created_at TEXT NOT NULL,
 previous_hash TEXT,
 event_hash TEXT NOT NULL UNIQUE
)"""
PREFIX = {"REVISION": "revision", "RUN": "run", "DECISION": "decision"}


class Conflict(ValueError):
    """The caller confirmed an older visibility projection."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def record_key(kind: Any, identity: Any) -> tuple[str, str]:
    if not isinstance(kind, str) or kind not in PREFIX or not isinstance(identity, str):
        raise ValueError("unsupported history record kind or ID")
    if re.fullmatch(PREFIX[kind] + r"-[0-9a-f]{24}", identity) is None:
        raise ValueError("invalid typed history ID")
    return kind, identity


class JournalHistory:
    """One existing journal, one append-only visibility log, one projection contract."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file():
            raise ValueError("journal must be an existing absolute regular file without aliases")
        for entry in (path, *path.parents):
            if entry.is_symlink():
                raise ValueError("journal aliases are forbidden")
        self.path = path
        # Verify the existing journal before ScreeningStore's IF NOT EXISTS initializer.
        # A typo, unrelated SQLite file, or incomplete schema cannot create a new store.
        with self.connect() as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
            if not required <= tables:
                raise ValueError("existing journal schema is incomplete")
            version = connection.execute("SELECT value FROM store_meta WHERE key='version'").fetchone()
            if version is None or version[0] != STORE_VERSION:
                raise ValueError("existing journal version differs")
        self.store = ScreeningStore(path)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
            if existing is None:
                connection.execute(LIFECYCLE_SCHEMA)
            elif " ".join(existing[0].split()) != " ".join(LIFECYCLE_SCHEMA.split()):
                raise ValueError("unsupported lifecycle schema")
            self._state(connection)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _state(self, connection: sqlite3.Connection) -> tuple[int, dict[tuple[str, str], str], str | None]:
        states: dict[tuple[str, str], str] = {}
        sequence, previous_hash = 0, None
        for row in connection.execute(f"SELECT * FROM {TABLE} ORDER BY sequence"):
            material = {key: row[key] for key in row.keys() if key != "event_hash"}
            key = record_key(row["record_kind"], row["record_id"])
            if (row["sequence"] != sequence + 1 or row["schema_version"] != 1
                    or row["previous_hash"] != previous_hash or not row["created_at"]
                    or row["action"] not in {"DELETE", "RESTORE"}
                    or (states.get(key, "RESTORE") == row["action"])
                    or digest(material) != row["event_hash"]):
                raise ValueError("lifecycle event integrity mismatch")
            self._require_record(*key)
            sequence, previous_hash = row["sequence"], row["event_hash"]
            states[key] = row["action"]
        return sequence, states, previous_hash

    def _require_record(self, kind: str, identity: str) -> dict[str, Any]:
        if kind == "REVISION":
            record = self.store.revision(identity)
            with self.connect() as connection:
                classification = connection.execute(
                    "SELECT save_kind FROM screen_save_kinds WHERE screen_id=?",
                    (record["screen_id"],),
                ).fetchone()
            # Frozen store treats an absent classification as a legacy explicit condition.
            if classification is not None and classification[0] != "EXPLICIT_CONDITION":
                raise ValueError("result-backing revisions are not saved conditions")
            return record
        if kind == "RUN":
            return self.store.run(identity)
        events = self.store.decisions()  # Validate the full raw chain before any projection.
        record = next((event for event in events if event["event_id"] == identity), None)
        if record is None:
            raise ValueError("unknown decision ID")
        return record

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as connection:
            version, states, _ = self._state(connection)
        revisions = self.store.list_saved_revisions()
        runs = self.store.list_runs()
        decisions = self.store.decisions()
        visible_decisions, previous = [], {}
        for event in decisions:
            if states.get(("DECISION", event["event_id"])) == "DELETE":
                continue
            visible_decisions.append({**event, "display_before_state": previous.get(event["cik"])})
            previous[event["cik"]] = event["state"]
        summary_runs = [{key: value for key, value in run.items() if key in {
            "run_id", "revision_id", "created_at", "result_name", "counts", "dataset_id", "period_policy"
        }} for run in runs]
        trash = []
        for kind, records, identity_key in [("REVISION", revisions, "revision_id"),
                                            ("RUN", summary_runs, "run_id"),
                                            ("DECISION", decisions, "event_id")]:
            for record in records:
                if states.get((kind, record[identity_key])) == "DELETE":
                    trash.append({"kind": kind, "record_id": record[identity_key], "record": record})
        return {"configured": True, "version": version,
                "revisions": [row for row in revisions if states.get(("REVISION", row["revision_id"])) != "DELETE"],
                "runs": [row for row in summary_runs if states.get(("RUN", row["run_id"])) != "DELETE"],
                "decisions": visible_decisions, "trash": trash}

    def change(self, kind: Any, identity: Any, action: str, expected_version: Any) -> dict[str, Any]:
        key = record_key(kind, identity)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("expected_version must be a nonnegative integer")
        if action not in {"DELETE", "RESTORE"}:
            raise ValueError("unsupported lifecycle action")
        self._require_record(*key)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version, states, previous_hash = self._state(connection)
            # Retried identical actions are harmless even after the first response was lost.
            if states.get(key, "RESTORE") != action:
                if version != expected_version:
                    raise Conflict("이력이 변경됐습니다. 새로고침 후 항목을 다시 확인해 주세요.")
                material = {"sequence": version + 1, "schema_version": 1,
                            "record_kind": kind, "record_id": identity, "action": action,
                            "created_at": datetime.now(UTC).isoformat(), "previous_hash": previous_hash}
                connection.execute(f"INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?,?)",
                                   (*material.values(), digest(material)))
        return self.snapshot()

    def require_visible(self, kind: str, identity: Any) -> None:
        key = record_key(kind, identity)
        self._require_record(*key)
        with self.connect() as connection:
            _, states, _ = self._state(connection)
        if states.get(key) == "DELETE":
            raise Conflict("휴지통에 있는 기록입니다. 복원 후 다시 열어 주세요.")

    def guard(self, method: str, path: str, body: dict[str, Any]) -> None:
        """Best-effort canonical reference checks; not an atomic backend ACL."""
        parsed = urlsplit(path)
        if method == "POST":
            if parsed.path in {"/api/runs", "/api/results"} and body.get("revision_id") is not None:
                self.require_visible("REVISION", body["revision_id"])
            if parsed.path == "/api/decisions":
                self.require_visible("RUN", body.get("run_id"))
        match = re.fullmatch(r"/api/runs/(run-[0-9a-f]{24})(?:/trace|/exports)?", parsed.path)
        if match:
            self.require_visible("RUN", match[1])
        match = re.fullmatch(r"/api/saved-conditions/(revision-[0-9a-f]{24})", parsed.path)
        if match:
            self.require_visible("REVISION", match[1])
        if parsed.path == "/api/run-comparison":
            query = parse_qs(parsed.query)
            for name in ("old_run_id", "new_run_id"):
                self.require_visible("RUN", query.get(name, [None])[0])

    def dispatch(self, message: dict[str, Any]) -> tuple[int, Any]:
        method, path = message.get("method"), message.get("path")
        if method not in {"GET", "POST"} or not isinstance(path, str):
            raise ValueError("unsupported history request")
        raw = base64.b64decode(message.get("body_base64", ""), validate=True)
        if len(raw) > MAX_REQUEST:
            raise ValueError("history request exceeds limit")
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise ValueError("history body must be an object")
        if message.get("check_only") is True:
            self.guard(method, path, body)
            return 200, {"allowed": True}
        if method == "GET" and path == "/api/history/capabilities":
            with self.connect() as connection:
                self._state(connection)
            return 200, {"configured": True, "available": True, "schema_version": 1}
        if method == "GET" and path == "/api/history":
            return 200, self.snapshot()
        if method == "POST" and path in {"/api/history/delete", "/api/history/restore"}:
            if set(body) != {"kind", "record_id", "expected_version"}:
                raise ValueError("unexpected history fields")
            return 200, self.change(body["kind"], body["record_id"],
                                    "DELETE" if path.endswith("/delete") else "RESTORE", body["expected_version"])
        if method == "POST" and path in {"/api/history/decisions", "/api/decisions"}:
            if not set(body) <= {"cik", "state", "rationale", "run_id", "actor", "evidence_ids"}:
                raise ValueError("unexpected decision fields")
            self.require_visible("RUN", body.get("run_id"))
            self.store.decisions()
            return 201, self.store.add_decision(**body)
        return 404, {"error": "unknown history route"}


def run_worker(history: JournalHistory) -> None:
    while True:
        line = sys.stdin.buffer.readline((MAX_REQUEST * 2) + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST * 2:
            return  # Do not parse a truncated oversized frame as a later request.
        identity = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or not isinstance(request.get("id"), str):
                raise ValueError("history request needs an ID")
            identity = request["id"]
            status, result = history.dispatch(request)
        except Conflict as error:
            status, result = 409, {"error": str(error)}
        except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
            status, result = 400, {"error": str(error)}
        encoded = canonical(result).encode()
        if len(encoded) > MAX_RESPONSE:
            status, encoded = 413, b'{"error":"history response exceeds limit"}'
        response = {"id": identity, "status": status,
                    "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store",
                                "x-content-type-options": "nosniff"},
                    "body_base64": base64.b64encode(encoded).decode()}
        print(canonical(response), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal-store", required=True, type=Path)
    arguments = parser.parse_args()
    run_worker(JournalHistory(arguments.journal_store))
