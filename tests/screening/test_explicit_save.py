from __future__ import annotations

import copy
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from test_screening_http import _request

from sec_xbrl.screening.common import sha256_file
from sec_xbrl.screening.server import create_server
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore, backup_store, restore_store


def service_for(dataset: Path, tmp_path: Path) -> ScreeningService:
    return ScreeningService({"fixture": dataset}, ScreeningStore(tmp_path / "journal.sqlite"))


def counts(store: ScreeningStore) -> dict:
    with sqlite3.connect(store.path) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def test_preview_is_read_only_and_explicit_result_reopens_after_restart(
    screening_dataset, revision_content, tmp_path
):
    service = service_for(screening_dataset, tmp_path)
    before = counts(service.store), sha256_file(service.store.path)
    preview = service.preview(revision_content, "fixture")
    assert preview["persistence_state"] == "PREVIEW"
    assert "run_id" not in preview
    assert (counts(service.store), sha256_file(service.store.path)) == before
    preview2 = service.preview(revision_content, "fixture")
    assert preview2 == preview
    saved = service.save_result(name="선별 결과", content=preview["content"], dataset_id="fixture", preview_hash=preview["preview_hash"])
    assert saved["rows"] == preview["rows"]
    assert saved["versions"] == preview["versions"]
    assert service.store.list_screens() == service.store.list_saved_revisions() == []
    restarted = service_for(screening_dataset, tmp_path)
    assert restarted.run(saved["run_id"]) == saved
    assert restarted.store.revision(saved["revision_id"])["content"] == revision_content
    restarted.store.integrity_check()
    backup = backup_store(service.store.path, tmp_path / "backup")
    restored = ScreeningStore(restore_store(backup, tmp_path / "restored.sqlite"))
    assert restored.list_saved_revisions() == []
    assert restored.run(saved["run_id"]) == saved


def test_condition_versions_and_noop_do_not_save_results(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    first = service.create_screen("조건", revision_content)
    no_op = service.revise_screen(first["screen_id"], copy.deepcopy(revision_content))
    assert no_op["revision_id"] == first["revision_id"]
    changed = copy.deepcopy(revision_content)
    changed["predicates"][0]["threshold"] = "1000"
    second = service.revise_screen(first["screen_id"], changed)
    assert [x["revision_id"] for x in service.store.list_saved_revisions()] == [first["revision_id"], second["revision_id"]]
    assert service.store.revision(first["revision_id"])["content"] == revision_content
    assert service.store.list_runs() == []
    p = service.preview(revision_content, "fixture")
    r = service.save_result(name="이전 조건의 결과", content=revision_content, dataset_id="fixture", preview_hash=p["preview_hash"], revision_id=first["revision_id"])
    assert r["revision_id"] == first["revision_id"]
    assert len(service.store.list_saved_revisions()) == 2


def test_stale_result_refused_without_writes_and_evaluation_saved_once(screening_dataset, revision_content, tmp_path, monkeypatch):
    service = service_for(screening_dataset, tmp_path)
    p = service.preview(revision_content, "fixture")
    changed = copy.deepcopy(revision_content)
    changed["predicates"][0]["threshold"] = "1000"
    before = counts(service.store)
    with pytest.raises(ValueError, match="stale"):
        service.save_result(name="bad", content=changed, dataset_id="fixture", preview_hash=p["preview_hash"])
    assert counts(service.store) == before
    calls = []
    original = service._evaluate
    def once(*args):
        calls.append(1)
        result = original(*args)
        if len(calls) > 1:
            result["rows"][0]["name"] = "MUTATED AFTER VALIDATION"
        return result
    monkeypatch.setattr(service, "_evaluate", once)
    saved = service.save_result(name="정확한 결과", content=revision_content, dataset_id="fixture", preview_hash=p["preview_hash"])
    assert len(calls) == 1 and saved["rows"] == p["rows"]


def test_result_transaction_rolls_back_backing_universe_and_run(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    p = service.preview(revision_content, "fixture")
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("CREATE TRIGGER reject_run BEFORE INSERT ON screen_runs BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    before = counts(service.store)
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        service.save_result(name="rollback", content=revision_content, dataset_id="fixture", preview_hash=p["preview_hash"])
    assert counts(service.store) == before


def test_legacy_store_additive_migration_preserves_records(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    revision = service.create_screen("legacy", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("DROP TABLE screen_save_kinds")
    reopened = service_for(screening_dataset, tmp_path)
    assert reopened.store.list_saved_revisions()[0]["revision_id"] == revision["revision_id"]
    assert reopened.run(run["run_id"]) == run
    reopened.store.integrity_check()


def test_explicit_preview_and_save_http(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    server = create_server(service, export_root=tmp_path / "exports")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        before = counts(service.store)
        status, data = _request(base + "/api/preview", body={"content": revision_content, "dataset_id": "fixture"}, origin=base)
        assert status == 200
        p = json.loads(data)
        assert counts(service.store) == before
        status, data = _request(base + "/api/results", body={"name": "HTTP 결과", "content": revision_content, "dataset_id": "fixture", "preview_hash": p["preview_hash"]}, origin=base)
        assert status == 201
        result = json.loads(data)
        status, data = _request(base + "/api/runs/" + result["run_id"])
        assert status == 200 and json.loads(data)["rows"] == p["rows"]
        status, data = _request(base + "/api/screen-revisions")
        assert status == 200 and json.loads(data) == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_saved_condition_context_exact_and_legacy_unknown(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    legacy = service.create_screen("unknown", revision_content)
    assert service.saved_condition(legacy["revision_id"])["context_origin"] == "UNKNOWN"
    saved = service.create_screen("bound", revision_content, dataset_id="fixture")
    assert service.saved_condition(saved["revision_id"])["open_dataset_id"] == "fixture"
    assert service.revise_screen(saved["screen_id"], revision_content, dataset_id="fixture")["revision_id"] == saved["revision_id"]
    before = counts(service.store)
    original = service.datasets["fixture"].manifest["publication_id"]
    service.datasets["fixture"].manifest["publication_id"] = "different-publication"
    with pytest.raises(ValueError, match="publication has changed"):
        service.saved_condition(saved["revision_id"])
    assert counts(service.store) == before
    service.datasets["fixture"].manifest["publication_id"] = original
    service.execute(legacy["revision_id"], "fixture")
    assert service.saved_condition(legacy["revision_id"])["context_origin"] == "HISTORICAL_RUN"
    backup = backup_store(service.store.path, tmp_path / "context-backup")
    restored = ScreeningStore(restore_store(backup, tmp_path / "context-restored.sqlite"))
    assert restored.revision(saved["revision_id"])["saved_context"] == saved["saved_context"]


def test_context_change_new_revision_and_corruption_rejected(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    saved = service.create_screen("bound", revision_content, dataset_id="fixture")
    context = dict(saved["saved_context"], publication_id="other")
    changed = service.store.revise_screen(saved["screen_id"], revision_content, context=context)
    assert changed["revision_number"] == 2
    assert changed["content_hash"] == saved["content_hash"]
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("UPDATE revision_contexts SET context_hash=? WHERE revision_id=?", ("0" * 64, changed["revision_id"]))
    with pytest.raises(ValueError, match="context hash"):
        service.store.integrity_check()


def test_context_orphan_rejected(screening_dataset, revision_content, tmp_path):
    service = service_for(screening_dataset, tmp_path)
    service.create_screen("bound", revision_content, dataset_id="fixture")
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("UPDATE revision_contexts SET revision_id='missing'")
    with pytest.raises(ValueError, match="orphaned"):
        service.store.integrity_check()


def test_quarter_preview_save_preserves_fiscal_identity(tmp_path):
    from test_screening_quarterly_consumer import _quarter_service

    service = _quarter_service(tmp_path)
    content = {
        "universe": {"mode": "ALL_PREPARED"},
        "predicates": [{"metric_id": "quarter_revenue", "operator": "GTE", "threshold": "1", "definition_version": "quarter-reported-core-v1"}],
        "period_policy": {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2025, "calendar_quarter": 1},
        "columns": ["company", "aggregate", "predicates"],
        "sort": {"column": "ticker", "direction": "ASC"},
    }
    before = counts(service.store)
    preview = service.preview(content, "synthetic-v3")
    assert counts(service.store) == before
    saved = service.create_screen("분기 조건", content, dataset_id="synthetic-v3")
    assert service.saved_condition(saved["revision_id"])["content"] == content
    result = service.save_result(name="분기 결과", content=content, dataset_id="synthetic-v3", preview_hash=preview["preview_hash"], revision_id=saved["revision_id"])
    assert result["result_name"] == "분기 결과"
    assert result["rows"] == preview["rows"]
    assert result["rows"][0]["predicates"][0]["observation"]["period_end"] == "2025-04-01"
    service.store.integrity_check()


def test_replaced_publication_rejects_reopen_and_pinned_lookups(
    screening_dataset, revision_content, tmp_path
):
    service = service_for(screening_dataset, tmp_path)
    preview = service.preview(revision_content, "fixture")
    run = service.save_result(name="frozen", content=revision_content, dataset_id="fixture", preview_hash=preview["preview_hash"])
    row = run["rows"][0]
    metric = row["predicates"][0]["metric_id"]
    trace = service.trace(run["run_id"], cik=row["cik"], metric_id=metric)
    original = service.datasets["fixture"].publication_id
    before = counts(service.store), sha256_file(service.store.path)
    service.datasets["fixture"].publication_id = "replacement"
    with pytest.raises(ValueError, match="저장 결과는 보존"):
        service.run(run["run_id"])
    assert service.store.run(run["run_id"]) == run
    assert service.trace(run["run_id"], cik=row["cik"], metric_id=metric) == trace
    server = create_server(service, export_root=tmp_path / "exports")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = _request(base + "/api/runs/" + run["run_id"])
        assert status == 400 and "저장 결과는 보존" in json.loads(body)["error"]
        for endpoint in ("series", "quarter-series", "peers", "peer-comparison", "quarter-comparison"):
            status, body = _request(base + f"/api/{endpoint}?dataset_id=fixture&dataset_publication_id={original}&cik={row['cik']}&metric_id={metric}")
            assert status == 400 and "publication has changed" in json.loads(body)["error"]
        service.datasets["fixture"].publication_id = original
        status, body = _request(base + f"/api/series?dataset_id=fixture&dataset_publication_id={original}&cik={row['cik']}&metric_id={metric}")
        assert status == 200 and json.loads(body)["observations"]
        assert service.run(run["run_id"]) == run
        assert (counts(service.store), sha256_file(service.store.path)) == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
