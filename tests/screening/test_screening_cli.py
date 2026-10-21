import json
import sqlite3
from pathlib import Path

import pytest

from sec_xbrl.screening import cli
from sec_xbrl.screening.store import ScreeningStore


def _catalog(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "screening-catalog-v1",
                "datasets": [{"dataset_id": "fixture", "root": str(path.parent / "dataset")}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _serve_args(tmp_path: Path, store: Path, *extra: str) -> list[str]:
    return [
        "serve",
        "--catalog",
        str(_catalog(tmp_path / "catalog.json")),
        "--store",
        str(store),
        "--exports",
        str(tmp_path / "exports"),
        *extra,
    ]


def _stub_runtime(monkeypatch: pytest.MonkeyPatch) -> list[ScreeningStore]:
    opened: list[ScreeningStore] = []

    class FakeService:
        def __init__(self, datasets, store, *, company_descriptions=None):
            assert sorted(datasets) == ["fixture"]
            assert company_descriptions is None
            opened.append(store)

    monkeypatch.setattr(cli, "ScreeningService", FakeService)
    monkeypatch.setattr(cli, "serve", lambda *args, **kwargs: None)
    return opened


def test_serve_default_still_initializes_a_new_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "new" / "journal.sqlite"
    opened = _stub_runtime(monkeypatch)

    assert cli.main(_serve_args(tmp_path, store)) == 0

    assert store.is_file()
    assert [item.path for item in opened] == [store.absolute()]
    with sqlite3.connect(store) as connection:
        assert connection.execute(
            "SELECT value FROM store_meta WHERE key='version'"
        ).fetchone() == ("screening-store-v1",)


@pytest.mark.parametrize("payload", [b"", b"not a sqlite database"])
def test_required_store_rejects_missing_or_invalid_file_before_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    store = tmp_path / "journal.sqlite"
    if payload:
        store.write_bytes(payload)
    before = store.read_bytes() if store.exists() else None
    constructed = False

    class UnexpectedStore:
        def __init__(self, path):
            nonlocal constructed
            constructed = True

    monkeypatch.setattr(cli, "ScreeningStore", UnexpectedStore)
    monkeypatch.setattr(cli, "ScreeningService", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "serve", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="required screening store"):
        cli.main(_serve_args(tmp_path, store, "--require-existing-store"))

    assert constructed is False
    assert (store.read_bytes() if store.exists() else None) == before


def test_required_store_rejects_wrong_store_version_without_changing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "journal.sqlite"
    with sqlite3.connect(store) as connection:
        connection.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO store_meta VALUES ('version', 'other-store-v1')")
    before = store.read_bytes()
    monkeypatch.setattr(cli, "ScreeningStore", lambda path: pytest.fail("store was initialized"))

    with pytest.raises(ValueError, match="unsupported screening store version"):
        cli.main(_serve_args(tmp_path, store, "--require-existing-store"))

    assert store.read_bytes() == before


def test_required_store_rejects_version_marker_without_core_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "journal.sqlite"
    with sqlite3.connect(store) as connection:
        connection.execute("CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO store_meta VALUES ('version', 'screening-store-v1')")
    before = store.read_bytes()
    monkeypatch.setattr(cli, "ScreeningStore", lambda path: pytest.fail("store was initialized"))

    with pytest.raises(ValueError, match="missing core journal tables"):
        cli.main(_serve_args(tmp_path, store, "--require-existing-store"))

    assert store.read_bytes() == before


def test_required_store_opens_existing_journal_and_reports_runtime_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "journal.sqlite"
    ScreeningStore(store)
    opened = _stub_runtime(monkeypatch)

    assert cli.main(_serve_args(tmp_path, store, "--require-existing-store")) == 0

    startup = json.loads(capsys.readouterr().out)
    assert startup == {
        "event": "screening_service_startup",
        "python": str(Path(cli.sys.executable).absolute()),
        "module": str(Path(cli.__file__).resolve()),
        "catalog": str((tmp_path / "catalog.json").absolute()),
        "store": str(store.absolute()),
        "exports": str((tmp_path / "exports").absolute()),
        "require_existing_store": True,
        "dataset_ids": ["fixture"],
    }
    assert [item.path for item in opened] == [store.absolute()]
