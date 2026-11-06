"""Lifecycle checks use synthetic journals only; no live journal is opened."""
from __future__ import annotations

import base64
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore, backup_store, restore_store

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("journal_history", ROOT / "examples/screening/journal_history.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
JournalHistory = MODULE.JournalHistory


def raw_tables(path: Path) -> dict:
    with sqlite3.connect(path) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'") if row[0] != MODULE.TABLE]
        return {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in tables}


@pytest.fixture
def journal(tmp_path: Path, screening_dataset: Path, revision_content: dict):
    path = tmp_path / "journal.sqlite"
    store = ScreeningStore(path)
    service = ScreeningService({"fixture": screening_dataset}, store)
    revision = service.create_screen("<조건 & 이름>", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    notes = [store.add_decision(cik="0000000001", state=state, rationale="private " + state,
                               run_id=run["run_id"], actor="fixture") for state in ("INTEREST", "HOLD", "EXCLUDE")]
    return path, store, revision, run, notes


def test_all_types_noncascade_idempotence_and_raw_preservation(journal):
    path, store, revision, run, notes = journal
    before = raw_tables(path)
    history = JournalHistory(path)
    for kind, identity in [("REVISION", revision["revision_id"]), ("RUN", run["run_id"]), ("DECISION", notes[-1]["event_id"])]:
        version = history.snapshot()["version"]
        hidden = history.change(kind, identity, "DELETE", version)
        assert history.change(kind, identity, "DELETE", version)["version"] == hidden["version"]
        assert any(row["record_id"] == identity for row in hidden["trash"])
        assert store.run(run["run_id"])["revision_id"] == revision["revision_id"]
        restored = history.change(kind, identity, "RESTORE", hidden["version"])
        assert not restored["trash"]
        assert history.change(kind, identity, "RESTORE", version)["version"] == restored["version"]
    assert raw_tables(path) == before
    store.integrity_check()


def test_effective_decisions_preserve_raw_chain_and_new_note_after_hidden_latest(journal):
    path, store, _, run, notes = journal
    history = JournalHistory(path)
    history.change("DECISION", notes[1]["event_id"], "DELETE", 0)
    projected = history.snapshot()["decisions"]
    assert projected[-1]["before_state"] == "HOLD"
    assert projected[-1]["display_before_state"] == "INTEREST"
    history.change("DECISION", notes[2]["event_id"], "DELETE", 1)
    assert history.snapshot()["decisions"][-1]["state"] == "INTEREST"
    body = {"cik": "0000000001", "state": "HOLD", "rationale": "new private", "run_id": run["run_id"], "actor": "fixture"}
    status, added = history.dispatch({"method": "POST", "path": "/api/history/decisions", "body_base64": base64.b64encode(json.dumps(body).encode()).decode()})
    assert status == 201 and added["before_state"] == "EXCLUDE"
    assert added["previous_event_id"] == notes[-1]["event_id"]
    assert history.snapshot()["decisions"][-1]["display_before_state"] == "INTEREST"
    history.change("DECISION", notes[1]["event_id"], "RESTORE", 2)
    assert history.snapshot()["decisions"][-1]["display_before_state"] == "HOLD"
    store.integrity_check()


def test_restart_backup_restore_and_reference_guards(journal, tmp_path):
    path, _, revision, run, _ = journal
    history = JournalHistory(path)
    history.change("REVISION", revision["revision_id"], "DELETE", 0)
    # Active results may use hidden raw revision metadata, but not execute that revision.
    history.guard("GET", "/api/runs/" + run["run_id"], {})
    history.guard("GET", "/api/revisions/" + revision["revision_id"], {})
    with pytest.raises(MODULE.Conflict):
        history.guard("POST", "/api/results", {"revision_id": revision["revision_id"]})
    history.change("RUN", run["run_id"], "DELETE", 1)
    with pytest.raises(MODULE.Conflict):
        history.guard("POST", "/api/runs/" + run["run_id"] + "/exports", {})
    backup = backup_store(path, tmp_path / "backup")
    restored = restore_store(backup, tmp_path / "restored.sqlite")
    assert JournalHistory(restored).snapshot() == JournalHistory(path).snapshot()
    body = json.dumps({"id": "probe", "method": "GET", "path": "/api/history", "body_base64": ""}) + "\n"
    result = subprocess.run([str(ROOT / ".venv/bin/python"), str(ROOT / "examples/screening/journal_history.py"), "--journal-store", str(restored)], input=body, text=True, capture_output=True, check=True)
    response = json.loads(result.stdout)
    assert json.loads(base64.b64decode(response["body_base64"]))["version"] == 2


def test_input_stale_schema_and_lifecycle_tamper_fail_closed(journal, tmp_path):
    path, _, revision, run, _ = journal
    history = JournalHistory(path)
    for kind, identity in [("SQL", "DROP TABLE"), ("RUN", revision["revision_id"]), ("RUN", "run-" + "f" * 24)]:
        with pytest.raises(ValueError):
            history.change(kind, identity, "DELETE", 0)
    history.change("REVISION", revision["revision_id"], "DELETE", 0)
    with pytest.raises(MODULE.Conflict):
        history.change("RUN", run["run_id"], "DELETE", 0)
    with pytest.raises(ValueError):
        history.change("RUN", run["run_id"], "DELETE", True)
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE {MODULE.TABLE} SET action='RESTORE'")
    with pytest.raises(ValueError, match="integrity"):
        JournalHistory(path)
    nonexistent = tmp_path / "typo.sqlite"
    with pytest.raises(FileNotFoundError):
        JournalHistory(nonexistent)
    assert not nonexistent.exists()
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        JournalHistory(alias)
    unrelated = tmp_path / "unrelated.sqlite"
    sqlite3.connect(unrelated).close()
    with pytest.raises(ValueError, match="incomplete"):
        JournalHistory(unrelated)


def test_legacy_unclassified_conditions_remain_visible_deletable_and_restorable(journal):
    path, store, revision, run, _ = journal
    revisions = [revision] + [store.create_screen(f"legacy {index}", revision["content"]) for index in range(3)]
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM screen_save_kinds")
    before = raw_tables(path)
    history = JournalHistory(path)
    assert len(history.snapshot()["revisions"]) == 4
    history.guard("GET", "/api/saved-conditions/" + revision["revision_id"], {})
    for index, record in enumerate(revisions):
        history.change("REVISION", record["revision_id"], "DELETE", index)
    history.guard("GET", "/api/runs/" + run["run_id"], {})
    assert not history.snapshot()["revisions"]
    for index, record in enumerate(revisions):
        history.change("REVISION", record["revision_id"], "RESTORE", index + 4)
    assert len(history.snapshot()["revisions"]) == 4
    assert raw_tables(path) == before


def test_fixed_routes_reject_http_sql_fields_and_incompatible_lifecycle_schema(journal, tmp_path):
    history = JournalHistory(journal[0])
    for body in [{"kind": "RUN", "record_id": journal[3]["run_id"], "expected_version": 0, "sql": "DELETE FROM screen_runs"}, []]:
        request = {"method": "POST", "path": "/api/history/delete", "body_base64": base64.b64encode(json.dumps(body).encode()).decode()}
        with pytest.raises(ValueError):
            history.dispatch(request)
    assert history.dispatch({"method": "GET", "path": "/api/history/../../private"})[0] == 404
    with pytest.raises(ValueError):
        history.dispatch({"method": "POST", "path": "/api/history/delete", "body_base64": "%%%"})
    path = tmp_path / "wrong-schema.sqlite"
    ScreeningStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE journal_lifecycle_events (sequence INTEGER)")
    with pytest.raises(ValueError, match="schema"):
        JournalHistory(path)
