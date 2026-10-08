"""Durable append-only SQLite records for local screening work."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
    canonical_json,
    digest_value,
    read_json,
    require_cik,
    require_string,
    safe_new_destination,
    sha256_file,
    write_json,
)

STORE_VERSION = "screening-store-v1"
BACKUP_VERSION = "screening-store-backup-v1"
DECISION_STATES = {"INTEREST", "HOLD", "EXCLUDE"}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS store_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen_definitions (
  screen_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen_revisions (
  revision_id TEXT PRIMARY KEY,
  screen_id TEXT NOT NULL REFERENCES screen_definitions(screen_id),
  parent_revision_id TEXT REFERENCES screen_revisions(revision_id),
  revision_number INTEGER NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(screen_id, revision_number)
);
CREATE TABLE IF NOT EXISTS universe_snapshots (
  universe_snapshot_id TEXT PRIMARY KEY,
  dataset_publication_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen_runs (
  run_id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES screen_revisions(revision_id),
  universe_snapshot_id TEXT NOT NULL REFERENCES universe_snapshots(universe_snapshot_id),
  dataset_publication_id TEXT NOT NULL,
  fixture_kind TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_events (
  event_id TEXT PRIMARY KEY,
  cik TEXT NOT NULL,
  state TEXT NOT NULL,
  before_state TEXT,
  rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES screen_runs(run_id),
  previous_event_id TEXT REFERENCES decision_events(event_id),
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL,
  event_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_manifests (
  export_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES screen_runs(run_id),
  scope TEXT NOT NULL,
  format TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class ScreeningStore:
    """Transactional local journal without mutable business records."""

    def __init__(self, path: Path | str) -> None:
        self.path = _safe_database_path(Path(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_screen(self, name: str, content: dict[str, Any]) -> dict[str, Any]:
        name = require_string(name, "screen name")
        normalized = _revision_content(content)
        screen_id = "screen-" + uuid.uuid4().hex
        created_at = _now()
        revision = _new_revision(screen_id, None, 1, normalized, created_at)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO screen_definitions(screen_id,name,created_at) VALUES(?,?,?)",
                (screen_id, name, created_at),
            )
            connection.execute(
                "INSERT INTO screen_revisions VALUES(?,?,?,?,?,?,?)",
                (
                    revision["revision_id"],
                    screen_id,
                    None,
                    1,
                    canonical_json(normalized),
                    revision["content_hash"],
                    created_at,
                ),
            )
        return {"screen_id": screen_id, "name": name, **revision, "content": normalized}

    def revise_screen(self, screen_id: str, content: dict[str, Any]) -> dict[str, Any]:
        screen_id = require_string(screen_id, "screen_id")
        normalized = _revision_content(content)
        created_at = _now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT revision_id,revision_number FROM screen_revisions "
                "WHERE screen_id=? ORDER BY revision_number DESC LIMIT 1",
                (screen_id,),
            ).fetchone()
            if current is None:
                raise ValueError("screen definition does not exist")
            number = int(current["revision_number"]) + 1
            revision = _new_revision(screen_id, current["revision_id"], number, normalized, created_at)
            connection.execute(
                "INSERT INTO screen_revisions VALUES(?,?,?,?,?,?,?)",
                (
                    revision["revision_id"],
                    screen_id,
                    current["revision_id"],
                    number,
                    canonical_json(normalized),
                    revision["content_hash"],
                    created_at,
                ),
            )
        return {"screen_id": screen_id, **revision, "content": normalized}

    def list_screens(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT d.screen_id,d.name,d.created_at,r.revision_id,r.revision_number,"
                "r.content_json,r.content_hash,r.created_at AS revised_at "
                "FROM screen_definitions d JOIN screen_revisions r ON r.screen_id=d.screen_id "
                "WHERE r.revision_number=(SELECT MAX(x.revision_number) FROM screen_revisions x "
                "WHERE x.screen_id=d.screen_id) ORDER BY d.name,d.screen_id"
            ).fetchall()
        return [_screen_row(row) for row in rows]

    def revision(self, revision_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.name,r.* FROM screen_revisions r JOIN screen_definitions d "
                "ON d.screen_id=r.screen_id WHERE r.revision_id=?",
                (require_string(revision_id, "revision_id"),),
            ).fetchone()
        if row is None:
            raise ValueError("screen revision does not exist")
        result = _screen_row(row)
        if digest_value(result["content"]) != result["content_hash"]:
            raise ValueError("screen revision integrity mismatch")
        return result

    def save_universe(self, content: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(canonical_json(content))
        digest = digest_value(normalized)
        identity = "universe-" + digest[:24]
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO universe_snapshots VALUES(?,?,?,?,?)",
                (
                    identity,
                    require_string(content.get("dataset_publication_id"), "dataset publication"),
                    canonical_json(normalized),
                    digest,
                    created_at,
                ),
            )
        return {"universe_snapshot_id": identity, "content_hash": digest, "content": normalized}

    def universe(self, universe_snapshot_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM universe_snapshots WHERE universe_snapshot_id=?",
                (require_string(universe_snapshot_id, "universe snapshot ID"),),
            ).fetchone()
        if row is None:
            raise ValueError("universe snapshot does not exist")
        content = json.loads(row["content_json"])
        if (
            digest_value(content) != row["content_hash"]
            or row["universe_snapshot_id"] != "universe-" + row["content_hash"][:24]
            or content.get("dataset_publication_id") != row["dataset_publication_id"]
        ):
            raise ValueError("universe snapshot integrity mismatch")
        return {
            "universe_snapshot_id": row["universe_snapshot_id"],
            "content_hash": row["content_hash"],
            "created_at": row["created_at"],
            "content": content,
        }

    def save_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(canonical_json(payload))
        revision_id = require_string(normalized.get("revision_id"), "revision_id")
        universe_id = require_string(
            normalized.get("universe_snapshot_id"), "universe_snapshot_id"
        )
        input_hash = require_string(normalized.get("input_hash"), "input_hash")
        output_hash = digest_value(normalized.get("rows"))
        if normalized.get("output_hash") not in {None, output_hash}:
            raise ValueError("run output hash does not match rows")
        normalized["output_hash"] = output_hash
        run_id = "run-" + digest_value(
            {"payload": normalized, "nonce": uuid.uuid4().hex}
        )[:24]
        created_at = _now()
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM screen_revisions WHERE revision_id=?", (revision_id,)
            ).fetchone() is None:
                raise ValueError("run references an unknown revision")
            if connection.execute(
                "SELECT 1 FROM universe_snapshots WHERE universe_snapshot_id=?", (universe_id,)
            ).fetchone() is None:
                raise ValueError("run references an unknown universe snapshot")
            connection.execute(
                "INSERT INTO screen_runs VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    revision_id,
                    universe_id,
                    require_string(normalized.get("dataset_publication_id"), "dataset publication"),
                    require_string(normalized.get("fixture_kind"), "fixture_kind"),
                    input_hash,
                    output_hash,
                    canonical_json(normalized),
                    created_at,
                ),
            )
        return {"run_id": run_id, "created_at": created_at, **normalized}

    def run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM screen_runs WHERE run_id=?",
                (require_string(run_id, "run_id"),),
            ).fetchone()
            revision = connection.execute(
                "SELECT content_hash FROM screen_revisions WHERE revision_id=?",
                (row["revision_id"],),
            ).fetchone() if row is not None else None
        if row is None:
            raise ValueError("screen run does not exist")
        payload = json.loads(row["payload_json"])
        if (
            revision is None
            or payload.get("revision_id") != row["revision_id"]
            or payload.get("universe_snapshot_id") != row["universe_snapshot_id"]
            or payload.get("dataset_publication_id") != row["dataset_publication_id"]
            or payload.get("fixture_kind") != row["fixture_kind"]
            or payload.get("input_hash") != row["input_hash"]
            or payload.get("output_hash") != row["output_hash"]
            or digest_value(payload.get("rows")) != row["output_hash"]
            or digest_value(
                {
                    "revision_id": row["revision_id"],
                    "revision_hash": revision["content_hash"],
                    "universe_snapshot_id": row["universe_snapshot_id"],
                    "dataset_publication_id": row["dataset_publication_id"],
                    "versions": payload.get("versions"),
                }
            )
            != row["input_hash"]
        ):
            raise ValueError("screen run output integrity mismatch")
        return {"run_id": row["run_id"], "created_at": row["created_at"], **payload}

    def list_runs(self, revision_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT run_id FROM screen_runs"
        params: tuple[Any, ...] = ()
        if revision_id is not None:
            sql += " WHERE revision_id=?"
            params = (require_string(revision_id, "revision_id"),)
        sql += " ORDER BY created_at,run_id"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self.run(row["run_id"]) for row in rows]

    def add_decision(
        self,
        *,
        cik: str,
        state: str,
        rationale: str,
        run_id: str,
        actor: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        cik = require_cik(cik)
        if state not in DECISION_STATES:
            raise ValueError("unsupported decision state")
        rationale = require_string(rationale, "rationale")
        actor = require_string(actor, "actor")
        run_id = require_string(run_id, "run_id")
        evidence = [require_string(value, "evidence ID") for value in (evidence_ids or [])]
        if len(evidence) != len(set(evidence)):
            raise ValueError("duplicate decision evidence ID")
        created_at = _now()
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM screen_runs WHERE run_id=?", (run_id,)
            ).fetchone() is None:
                raise ValueError("decision references an unknown run")
            prior = connection.execute(
                "SELECT event_id,state FROM decision_events WHERE cik=? "
                "ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (cik,),
            ).fetchone()
            material = {
                "cik": cik,
                "state": state,
                "before_state": prior["state"] if prior else None,
                "rationale": rationale,
                "evidence_ids": evidence,
                "run_id": run_id,
                "previous_event_id": prior["event_id"] if prior else None,
                "actor": actor,
                "created_at": created_at,
            }
            event_hash = digest_value(material)
            event_id = "decision-" + event_hash[:24]
            connection.execute(
                "INSERT INTO decision_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    cik,
                    state,
                    material["before_state"],
                    rationale,
                    canonical_json(evidence),
                    run_id,
                    material["previous_event_id"],
                    actor,
                    created_at,
                    event_hash,
                ),
            )
        return {"event_id": event_id, "event_hash": event_hash, **material}

    def decisions(self, cik: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM decision_events"
        params: tuple[Any, ...] = ()
        if cik is not None:
            sql += " WHERE cik=?"
            params = (require_cik(cik),)
        sql += " ORDER BY created_at,rowid"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        results = []
        for row in rows:
            material = {
                "cik": row["cik"],
                "state": row["state"],
                "before_state": row["before_state"],
                "rationale": row["rationale"],
                "evidence_ids": json.loads(row["evidence_json"]),
                "run_id": row["run_id"],
                "previous_event_id": row["previous_event_id"],
                "actor": row["actor"],
                "created_at": row["created_at"],
            }
            if digest_value(material) != row["event_hash"]:
                raise ValueError("decision event integrity mismatch")
            results.append({"event_id": row["event_id"], "event_hash": row["event_hash"], **material})
        latest: dict[str, dict[str, Any]] = {}
        for event in results:
            prior = latest.get(event["cik"])
            if event["previous_event_id"] != (prior["event_id"] if prior else None) or event[
                "before_state"
            ] != (prior["state"] if prior else None):
                raise ValueError("decision event chain integrity mismatch")
            latest[event["cik"]] = event
        return results

    def record_export(self, manifest: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(canonical_json(manifest))
        export_id = "export-" + digest_value(normalized)[:24]
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO export_manifests VALUES(?,?,?,?,?,?)",
                (
                    export_id,
                    require_string(normalized.get("run_id"), "run_id"),
                    require_string(normalized.get("scope"), "scope"),
                    require_string(normalized.get("format"), "format"),
                    canonical_json(normalized),
                    created_at,
                ),
            )
        return {"export_id": export_id, "created_at": created_at, **normalized}

    def integrity_check(self) -> None:
        with self._connect() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"SQLite integrity check failed: {result}")
            revision_ids = [
                row["revision_id"]
                for row in connection.execute("SELECT revision_id FROM screen_revisions")
            ]
            universes = list(connection.execute("SELECT * FROM universe_snapshots"))
            exports = list(connection.execute("SELECT * FROM export_manifests"))
        for revision_id in revision_ids:
            self.revision(revision_id)
        for row in universes:
            content = json.loads(row["content_json"])
            if (
                digest_value(content) != row["content_hash"]
                or row["universe_snapshot_id"] != "universe-" + row["content_hash"][:24]
            ):
                raise ValueError("universe snapshot integrity mismatch")
        for run in self.list_runs():
            self.run(run["run_id"])
        self.decisions()
        for row in exports:
            manifest = json.loads(row["manifest_json"])
            if (
                row["export_id"] != "export-" + digest_value(manifest)[:24]
                or manifest.get("run_id") != row["run_id"]
                or manifest.get("scope") != row["scope"]
                or manifest.get("format") != row["format"]
            ):
                raise ValueError("export manifest integrity mismatch")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute(
                "SELECT value FROM store_meta WHERE key='version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO store_meta(key,value) VALUES('version',?)", (STORE_VERSION,)
                )
            elif row["value"] != STORE_VERSION:
                raise ValueError("unsupported screening store version")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


def backup_store(store_path: Path | str, destination: Path | str) -> Path:
    source = ScreeningStore(store_path)
    source.integrity_check()
    destination_path = safe_new_destination(Path(destination), "screening backup")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.mkdir()
    backup_path = destination_path / "journal.sqlite"
    try:
        source_connection = sqlite3.connect(source.path)
        destination_connection = sqlite3.connect(backup_path)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        ScreeningStore(backup_path).integrity_check()
        manifest = {
            "version": BACKUP_VERSION,
            "source_store": str(source.path),
            "created_at": _now(),
            "file": {
                "path": "journal.sqlite",
                "sha256": sha256_file(backup_path),
                "size": backup_path.stat().st_size,
            },
        }
        manifest["backup_id"] = "screening-backup-" + digest_value(manifest)[:24]
        write_json(destination_path / "backup_manifest.json", manifest)
    except Exception:
        shutil.rmtree(destination_path, ignore_errors=True)
        raise
    return destination_path


def restore_store(backup_root: Path | str, destination: Path | str) -> Path:
    root = Path(backup_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("backup root is not a real directory")
    manifest_path = root / "backup_manifest.json"
    backup_path = root / "journal.sqlite"
    if any(path.is_symlink() or not path.is_file() for path in (manifest_path, backup_path)):
        raise ValueError("backup contains unsafe files")
    manifest = read_json(manifest_path, "backup manifest")
    identity = {key: value for key, value in manifest.items() if key != "backup_id"}
    if (
        manifest.get("version") != BACKUP_VERSION
        or manifest.get("backup_id") != "screening-backup-" + digest_value(identity)[:24]
        or manifest.get("file", {}).get("sha256") != sha256_file(backup_path)
        or manifest.get("file", {}).get("size") != backup_path.stat().st_size
    ):
        raise ValueError("backup integrity mismatch")
    destination_path = safe_new_destination(Path(destination), "restored screening store")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    shutil.copyfile(backup_path, temporary)
    try:
        ScreeningStore(temporary).integrity_check()
        temporary.rename(destination_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination_path


def _safe_database_path(path: Path) -> Path:
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise ValueError("screening store path traverses a symlink")
    if absolute.exists() and not absolute.is_file():
        raise ValueError("screening store path is not a regular file")
    return absolute


def _revision_content(content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise TypeError("screen revision content must be an object")
    required = {"universe", "predicates", "period_policy", "columns", "sort"}
    if set(content) != required:
        raise ValueError(f"screen revision content fields must be {sorted(required)}")
    if not isinstance(content["predicates"], list) or not content["predicates"]:
        raise ValueError("screen revision requires predicates")
    return json.loads(canonical_json(content))


def _new_revision(
    screen_id: str,
    parent_revision_id: str | None,
    number: int,
    content: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    content_hash = digest_value(content)
    revision_id = "revision-" + digest_value(
        {
            "screen_id": screen_id,
            "parent": parent_revision_id,
            "number": number,
            "content_hash": content_hash,
            "created_at": created_at,
        }
    )[:24]
    return {
        "revision_id": revision_id,
        "parent_revision_id": parent_revision_id,
        "revision_number": number,
        "content_hash": content_hash,
        "created_at": created_at,
    }


def _screen_row(row: sqlite3.Row) -> dict[str, Any]:
    values = dict(row)
    return {
        "screen_id": values["screen_id"],
        "name": values.get("name"),
        "revision_id": values["revision_id"],
        "revision_number": values["revision_number"],
        "content": json.loads(values["content_json"]),
        "content_hash": values["content_hash"],
        "created_at": values.get("revised_at", values["created_at"]),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
