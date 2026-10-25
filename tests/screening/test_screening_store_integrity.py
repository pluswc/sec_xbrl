from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sec_xbrl.screening.common import digest_value, read_json, sha256_file, write_json
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import (
    ScreeningStore,
    _new_revision,
    backup_store,
    restore_store,
)


def _revision_chain(
    path: Path, content: dict
) -> tuple[ScreeningStore, dict, dict]:
    store = ScreeningStore(path)
    first = store.create_screen("무결성 조건", content)
    changed = json.loads(json.dumps(content))
    changed["predicates"][0]["threshold"] = "51"
    second = store.revise_screen(first["screen_id"], changed)
    store.integrity_check()
    return store, first, second


def _revision_row(path: Path, revision_id: str) -> sqlite3.Row:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM screen_revisions WHERE revision_id=?", (revision_id,)
        ).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()


def _replace_revision_identity(
    path: Path,
    revision_id: str,
    *,
    parent_revision_id: str | None,
    revision_number: int,
) -> str:
    row = _revision_row(path, revision_id)
    content = json.loads(row["content_json"])
    replacement = _new_revision(
        row["screen_id"],
        parent_revision_id,
        revision_number,
        content,
        row["created_at"],
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE screen_revisions SET revision_id=?,parent_revision_id=?,"
            "revision_number=? WHERE revision_id=?",
            (
                replacement["revision_id"],
                parent_revision_id,
                revision_number,
                revision_id,
            ),
        )
    return replacement["revision_id"]


def test_valid_revision_chain_and_definition_identity_pass(
    revision_content: dict, tmp_path: Path
) -> None:
    store, first, second = _revision_chain(tmp_path / "valid.sqlite", revision_content)
    assert first["revision_number"] == 1
    assert second["revision_number"] == 2
    assert store.revision(first["revision_id"])["content"] == revision_content
    assert store.revision(second["revision_id"])["content"]["predicates"][0]["threshold"] == "51"
    store.integrity_check()


@pytest.mark.parametrize("corruption", ["cycle", "gap", "identity", "orphan"])
def test_revision_chain_corruption_is_rejected(
    corruption: str, revision_content: dict, tmp_path: Path
) -> None:
    path = tmp_path / f"{corruption}.sqlite"
    store, _first, second = _revision_chain(path, revision_content)
    if corruption == "cycle":
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE screen_revisions SET parent_revision_id=revision_id "
                "WHERE revision_id=?",
                (second["revision_id"],),
            )
    elif corruption == "gap":
        _replace_revision_identity(
            path,
            second["revision_id"],
            parent_revision_id=second["parent_revision_id"],
            revision_number=99,
        )
    elif corruption == "identity":
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE screen_revisions SET revision_id=? WHERE revision_id=?",
                ("revision-" + "0" * 24, second["revision_id"]),
            )
    else:
        _replace_revision_identity(
            path,
            second["revision_id"],
            parent_revision_id="revision-" + "f" * 24,
            revision_number=2,
        )
    with pytest.raises(ValueError, match="revision|orphan"):
        store.integrity_check()


def test_cross_screen_parent_rejected_even_with_recomputed_revision_identity(
    revision_content: dict, tmp_path: Path
) -> None:
    path = tmp_path / "cross-screen.sqlite"
    store, first, _second = _revision_chain(path, revision_content)
    other_first = store.create_screen("다른 조건", revision_content)
    changed = json.loads(json.dumps(revision_content))
    changed["predicates"][0]["threshold"] = "51"
    other_second = store.revise_screen(other_first["screen_id"], changed)
    _replace_revision_identity(
        path,
        other_second["revision_id"],
        parent_revision_id=first["revision_id"],
        revision_number=2,
    )
    with pytest.raises(ValueError, match="parent chain"):
        store.integrity_check()


def test_definition_creation_envelope_and_terminal_decision_identity_rejected(
    screening_dataset: Path,
    revision_content: dict,
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.sqlite"
    service = ScreeningService(
        {"fixture": screening_dataset}, ScreeningStore(path)
    )
    revision = service.create_screen("관계 조건", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    event = service.add_decision(
        cik="0000000001",
        state="INTEREST",
        rationale="원천 확인",
        run_id=run["run_id"],
        actor="tester",
    )
    service.store.integrity_check()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE decision_events SET event_id=? WHERE event_id=?",
            ("decision-" + "0" * 24, event["event_id"]),
        )
    with pytest.raises(ValueError, match="decision event integrity"):
        service.store.integrity_check()

    clean_path = tmp_path / "definition.sqlite"
    clean, first, _second = _revision_chain(clean_path, revision_content)
    with sqlite3.connect(clean_path) as connection:
        connection.execute(
            "UPDATE screen_definitions SET created_at=? WHERE screen_id=?",
            ("2000-01-01T00:00:00+00:00", first["screen_id"]),
        )
    with pytest.raises(ValueError, match="definition creation"):
        clean.integrity_check()


def test_backup_and_restore_reject_corrupted_revision_chains(
    revision_content: dict, tmp_path: Path
) -> None:
    corrupt_path = tmp_path / "corrupt.sqlite"
    _store, _first, second = _revision_chain(corrupt_path, revision_content)
    with sqlite3.connect(corrupt_path) as connection:
        connection.execute(
            "UPDATE screen_revisions SET parent_revision_id=revision_id "
            "WHERE revision_id=?",
            (second["revision_id"],),
        )
    corrupt_backup = tmp_path / "corrupt-backup"
    with pytest.raises(ValueError, match="revision"):
        backup_store(corrupt_path, corrupt_backup)
    assert not corrupt_backup.exists()

    valid_path = tmp_path / "valid.sqlite"
    _valid, _first, valid_second = _revision_chain(valid_path, revision_content)
    backup = backup_store(valid_path, tmp_path / "valid-backup")
    backup_database = backup / "journal.sqlite"
    with sqlite3.connect(backup_database) as connection:
        connection.execute(
            "UPDATE screen_revisions SET parent_revision_id=revision_id "
            "WHERE revision_id=?",
            (valid_second["revision_id"],),
        )
    manifest_path = backup / "backup_manifest.json"
    manifest = read_json(manifest_path, "backup manifest")
    manifest["file"] = {
        "path": "journal.sqlite",
        "sha256": sha256_file(backup_database),
        "size": backup_database.stat().st_size,
    }
    identity = {key: value for key, value in manifest.items() if key != "backup_id"}
    manifest["backup_id"] = "screening-backup-" + digest_value(identity)[:24]
    write_json(manifest_path, manifest)
    restored = tmp_path / "restored.sqlite"
    with pytest.raises(ValueError, match="revision"):
        restore_store(backup, restored)
    assert not restored.exists()
