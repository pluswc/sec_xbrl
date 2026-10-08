from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from sec_xbrl.screening.server import create_server
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore


def _request(url: str, *, body: dict | None = None, origin: str | None = None) -> tuple[int, bytes]:
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_loopback_http_native_ui_origin_and_restart(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    store_path = tmp_path / "journal.sqlite"
    service = ScreeningService({"fixture": screening_dataset}, ScreeningStore(store_path))
    server = create_server(service, export_root=tmp_path / "exports")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"127.0.0.1:{server.server_port}"
    base = "http://" + host
    try:
        status, html = _request(base + "/")
        assert status == 200
        text = html.decode()
        assert "기업 스크리닝 작업대" in text and "전 회사 결과" in text
        assert "localStorage" not in text
        status, icon = _request(base + "/favicon.ico")
        assert status == 204 and icon == b""
        status, body = _request(
            base + "/api/screens",
            body={"name": "브라우저 조건", "content": revision_content},
            origin=base,
        )
        assert status == 201
        revision = json.loads(body)
        status, body = _request(
            base + "/api/runs",
            body={"revision_id": revision["revision_id"], "dataset_id": "fixture"},
            origin=base,
        )
        run = json.loads(body)
        assert status == 201 and run["counts"]["target"] == 3
        status, body = _request(
            base + f"/api/runs/{run['run_id']}/exports",
            body={"scope": "FULL", "format": "csv", "selected_ciks": None},
            origin=base,
        )
        export = json.loads(body)
        assert status == 201
        status, downloaded = _request(base + export["download_url"])
        assert status == 200 and downloaded.startswith(b"\xef\xbb\xbf")
        private = tmp_path / "exports" / "unregistered.txt"
        private.write_text("not an export", encoding="utf-8")
        status, _ = _request(base + "/exports/unregistered.txt")
        assert status == 400
        status, body = _request(
            base + "/api/screens",
            body={"name": "외부 origin", "content": revision_content},
            origin="https://example.com",
        )
        assert status == 403 and "origin" in json.loads(body)["error"]
        status, _ = _request(base + "/api/debug/fail-save")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    restarted = ScreeningService({"fixture": screening_dataset}, ScreeningStore(store_path))
    assert restarted.store.list_screens()[0]["revision_id"] == revision["revision_id"]


def test_server_rejects_non_loopback(screening_dataset: Path, tmp_path: Path) -> None:
    service = ScreeningService({"fixture": screening_dataset}, ScreeningStore(tmp_path / "db.sqlite"))
    with pytest.raises(ValueError, match="loopback"):
        create_server(service, export_root=tmp_path / "exports", host="0.0.0.0")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked-exports"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        create_server(service, export_root=linked)


def test_save_failure_has_no_false_commit(
    screening_dataset: Path,
    revision_content: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ScreeningService({"fixture": screening_dataset}, ScreeningStore(tmp_path / "db.sqlite"))

    class BrokenConnection:
        def __enter__(self):
            raise OSError("synthetic commit failure")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(service.store, "_connect", lambda: BrokenConnection())
    with pytest.raises(OSError, match="synthetic"):
        service.create_screen("저장 실패", revision_content)
    recovered = ScreeningStore(tmp_path / "db.sqlite")
    assert recovered.list_screens() == []
