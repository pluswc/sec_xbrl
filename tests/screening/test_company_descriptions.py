from __future__ import annotations

import json
import shutil
import threading
import urllib.request
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.screening.common import read_json, sha256_file, write_json
from sec_xbrl.screening.company_descriptions import (
    RECORDS,
    CompanyDescriptionReader,
    FetchResult,
    _extract_selected_text,
    publish_company_descriptions,
    review_company_description_plan,
)
from sec_xbrl.screening.dataset import MANIFEST as DATASET_MANIFEST
from sec_xbrl.screening.dataset_v2 import open_screening_dataset
from sec_xbrl.screening.server import create_server
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore

TODAY = date(2026, 10, 10)


def _plan(
    screening_dataset: Path,
    root: Path,
    *,
    mode: str = "PROVIDED_TEXT",
    rights_status: str = "APPROVED",
    expires: str = "2026-12-31",
    selector: str = "section#intro",
) -> Path:
    dataset = open_screening_dataset(screening_dataset)
    entries: list[dict] = []
    for index, company in enumerate(dataset.companies):
        if index:
            entries.append(
                {
                    "cik": company["cik"],
                    "ticker": company["ticker"],
                    "status": "UNAVAILABLE",
                    "provider_id": None,
                    "provider_name": None,
                    "profile_url": None,
                    "locale": None,
                    "checked_at": None,
                    "observed_at": None,
                    "unavailable_reason": "제공자 프로필 URL과 이용 근거를 아직 확인하지 않았습니다.",
                }
            )
            continue
        row = {
            "cik": company["cik"],
            "ticker": company["ticker"],
            "status": "AVAILABLE",
            "provider_id": "synthetic-provider",
            "provider_name": "합성 설명 출처",
            "profile_url": "https://profiles.example/company/one",
            "locale": "ko",
            "checked_at": "2026-10-10T09:00:00+09:00",
            "observed_at": "2026-10-10T09:00:00+09:00",
            "rights_status": rights_status,
            "rights_reference": "SYNTHETIC_TEST_PERMISSION",
            "rights_scope": (
                "DISPLAY_PLAINTEXT"
                if mode == "PROVIDED_TEXT"
                else "FETCH_AND_DISPLAY_PLAINTEXT"
            ),
            "rights_valid_from": "2026-01-01",
            "rights_expires_at": expires,
        }
        if mode == "PROVIDED_TEXT":
            row["text_path"] = "one.txt"
        else:
            row["description_selector"] = selector
        entries.append(row)
    plan = {
        "schema_version": "company-description-plan-v1",
        "dataset_id": dataset.manifest["dataset_id"],
        "dataset_publication_id": dataset.publication_id,
        "dataset_manifest_sha256": sha256_file(screening_dataset / DATASET_MANIFEST),
        "fixture_kind": "SYNTHETIC_DESCRIPTION_FIXTURE",
        "acquisition_mode": mode,
        "input_root": str(root),
        "allowed_hosts": ["profiles.example"],
        "entries": entries,
    }
    path = root / "plan.json"
    write_json(path, plan)
    return path


def test_supplied_text_publication_is_portable_and_optional(
    screening_dataset: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    supplied = inputs / "one.txt"
    supplied.write_text("합성 회사 설명입니다.\n<script>문자 그대로 보존</script>", encoding="utf-8")
    plan = _plan(screening_dataset, inputs)

    review = review_company_description_plan(plan, screening_dataset, today=TODAY)
    assert review["network_performed"] is False
    assert (review["ready_count"], review["unavailable_count"], review["blocked_count"]) == (1, 2, 0)

    publication = publish_company_descriptions(
        plan, screening_dataset, tmp_path / "publication", today=TODAY
    )
    dataset = open_screening_dataset(screening_dataset)
    reader = CompanyDescriptionReader(
        publication.root, publication.manifest_sha256, dataset, today=TODAY
    )
    assert reader.verify_all(today=TODAY) == {
        "publication_id": publication.publication_id,
        "dataset_id": "fixture",
        "company_count": 3,
        "available_count": 1,
        "fixture_kind": "SYNTHETIC_DESCRIPTION_FIXTURE",
        "rights_expired_count": 0,
    }
    row = reader.company("0000000001", today=TODAY)
    assert row["text"] == "합성 회사 설명입니다.\n<script>문자 그대로 보존</script>"
    assert row["content_fixture_kind"] == "SYNTHETIC_DESCRIPTION_FIXTURE"
    unavailable = reader.company("0000000002", today=TODAY)
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["profile_url"] is None
    assert unavailable["checked_at"] is None

    # Mutable producer inputs are lineage only after the immutable publication exists.
    supplied.unlink()
    plan.write_text("{}", encoding="utf-8")
    moved = tmp_path / "moved-publication"
    shutil.move(publication.root, moved)
    reopened = CompanyDescriptionReader(
        moved, publication.manifest_sha256, dataset, today=TODAY
    )
    assert reopened.company("0000000001", today=TODAY)["text"].startswith("합성 회사")

    service = ScreeningService(
        {"fixture": screening_dataset},
        ScreeningStore(tmp_path / "journal.sqlite"),
        company_descriptions=reopened,
    )
    service.explorers["fixture"] = SimpleNamespace(
        company_profile=lambda **_: {"company": {"ticker": "ONE"}, "summary": []}
    )
    profile = service.company_profile("fixture", cik="0000000001", fiscal_year=2025)
    assert profile["company_description"]["text"].startswith("합성 회사")
    assert profile["company_description"]["content_fixture_kind"] == "SYNTHETIC_DESCRIPTION_FIXTURE"

    plain_service = ScreeningService(
        {"fixture": screening_dataset}, ScreeningStore(tmp_path / "plain.sqlite")
    )
    plain_service.explorers["fixture"] = service.explorers["fixture"]
    assert "company_description" not in plain_service.company_profile(
        "fixture", cik="0000000001", fiscal_year=2025
    )


def test_rights_preflight_blocks_before_fetch_or_destination(
    screening_dataset: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    plan = _plan(
        screening_dataset,
        inputs,
        mode="AUTHORIZED_FETCH",
        rights_status="PENDING",
    )
    calls: list[str] = []

    def fetcher(url: str, _timeout: float, _limit: int) -> FetchResult:
        calls.append(url)
        raise AssertionError("blocked plan must not perform network I/O")

    review = review_company_description_plan(plan, screening_dataset, today=TODAY)
    assert review["blocked_count"] == 1
    destination = tmp_path / "blocked"
    with pytest.raises(PermissionError, match="blocked before network I/O"):
        publish_company_descriptions(
            plan, screening_dataset, destination, today=TODAY, fetcher=fetcher
        )
    assert calls == []
    assert not destination.exists()


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ('<section id="intro">하나</section><section id="intro">둘</section>', "exactly one"),
        ('<section id="intro"><div>설명</section><nav>광고</nav>', "malformed"),
    ],
)
def test_selected_html_rejects_ambiguous_or_malformed_targets(
    html: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _extract_selected_text(html, "section#intro")


def test_selected_html_keeps_only_scoped_text_and_handles_void_tags() -> None:
    html = """
    <html><body><section id="intro">기업 설명<br><img src="x">추가 설명<hr>
    <div>사업 영역</div><script>유출 스크립트</script><style>유출 스타일</style></section>
    <nav>광고와 다른 회사</nav></body></html>
    """
    text = _extract_selected_text(html, "section#intro")
    assert [line for line in text.splitlines() if line] == [
        "기업 설명", "추가 설명", "사업 영역"
    ]
    assert "광고" not in text and "유출" not in text
    for broad in ("html", "body", "head", "main"):
        with pytest.raises(ValueError, match="unsupported"):
            _extract_selected_text(html, broad)


def test_authorized_fetch_is_single_scoped_request_and_rejects_bad_response(
    screening_dataset: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    plan = _plan(screening_dataset, inputs, mode="AUTHORIZED_FETCH")
    calls: list[tuple[str, float, int]] = []

    def fetcher(url: str, timeout: float, limit: int) -> FetchResult:
        calls.append((url, timeout, limit))
        return FetchResult(
            200,
            "text/html; charset=utf-8",
            '<section id="intro">한국어 회사 설명<br>두 번째 줄</section><nav>광고</nav>'.encode(),
            url,
        )

    publication = publish_company_descriptions(
        plan, screening_dataset, tmp_path / "fetched", today=TODAY, fetcher=fetcher
    )
    assert len(calls) == 1
    rows = read_json(publication.root / RECORDS, RECORDS)
    assert rows[0]["text"] == "한국어 회사 설명\n두 번째 줄"
    assert "광고" not in rows[0]["text"]

    bad_plan = _plan(screening_dataset, inputs, mode="AUTHORIZED_FETCH")
    for index, response in enumerate(
        (
            FetchResult(403, "text/html", b"", "https://profiles.example/company/one"),
            FetchResult(302, "text/html", b"", "https://profiles.example/other"),
            FetchResult(200, "text/html", b"<html>captcha</html>", "https://profiles.example/company/one"),
        )
    ):
        with pytest.raises(ValueError):
            publish_company_descriptions(
                bad_plan,
                screening_dataset,
                tmp_path / f"bad-{index}",
                today=TODAY,
                fetcher=lambda *_args, response=response: response,
            )
        assert not (tmp_path / f"bad-{index}").exists()


def test_expired_rights_hide_text_without_disabling_financial_service(
    screening_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "one.txt").write_text("유효기간이 있는 합성 설명", encoding="utf-8")
    plan = _plan(screening_dataset, inputs, expires="2026-10-10")
    publication = publish_company_descriptions(
        plan, screening_dataset, tmp_path / "publication", today=TODAY
    )
    dataset = open_screening_dataset(screening_dataset)
    reader = CompanyDescriptionReader(
        publication.root,
        publication.manifest_sha256,
        dataset,
        today=date(2026, 10, 11),
    )
    assert reader.verify_all(today=date(2026, 10, 11))["rights_expired_count"] == 1
    expired = reader.company("0000000001", today=date(2026, 10, 11))
    assert expired["status"] == "RIGHTS_EXPIRED"
    assert expired["text"] is None and expired["profile_url"] is None

    service = ScreeningService(
        {"fixture": screening_dataset},
        ScreeningStore(tmp_path / "journal.sqlite"),
        company_descriptions=reader,
    )
    service.explorers["fixture"] = SimpleNamespace(
        company_profile=lambda **_: {"company": {"ticker": "ONE"}, "summary": [{"value": "100"}]}
    )
    original_company = reader.company
    monkeypatch.setattr(
        reader,
        "company",
        lambda cik: original_company(cik, today=date(2026, 10, 11)),
    )
    profile = service.company_profile("fixture", cik="0000000001", fiscal_year=2025)
    assert profile["summary"] == [{"value": "100"}]
    assert profile["company_description"]["status"] == "RIGHTS_EXPIRED"
    assert profile["company_description"]["text"] is None


def test_reader_rejects_tampered_records_and_wrong_manifest_pin(
    screening_dataset: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "one.txt").write_text("변조 확인용 합성 설명", encoding="utf-8")
    plan = _plan(screening_dataset, inputs)
    publication = publish_company_descriptions(
        plan, screening_dataset, tmp_path / "publication", today=TODAY
    )
    dataset = open_screening_dataset(screening_dataset)
    with pytest.raises(ValueError, match="pinned digest"):
        CompanyDescriptionReader(publication.root, "0" * 64, dataset, today=TODAY)

    rows_path = publication.root / RECORDS
    rows = read_json(rows_path, RECORDS)
    rows[0]["text"] = "바뀐 설명"
    write_json(rows_path, rows)
    with pytest.raises(ValueError, match="records changed"):
        CompanyDescriptionReader(
            publication.root, publication.manifest_sha256, dataset, today=TODAY
        )


def test_http_profile_returns_plaintext_projection_without_external_fetch(
    screening_dataset: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "one.txt").write_text("<img src=x onerror=alert(1)> 한국어 합성 설명", encoding="utf-8")
    plan = _plan(screening_dataset, inputs)
    publication = publish_company_descriptions(
        plan, screening_dataset, tmp_path / "publication", today=TODAY
    )
    reader = CompanyDescriptionReader(
        publication.root,
        publication.manifest_sha256,
        open_screening_dataset(screening_dataset),
        today=TODAY,
    )
    service = ScreeningService(
        {"fixture": screening_dataset},
        ScreeningStore(tmp_path / "journal.sqlite"),
        company_descriptions=reader,
    )
    service.explorers["fixture"] = SimpleNamespace(
        company_profile=lambda **_: {"company": {"ticker": "ONE"}, "summary": []}
    )
    server = create_server(service, export_root=tmp_path / "exports")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = (
            f"http://127.0.0.1:{server.server_port}/api/company-profile"
            "?dataset_id=fixture&cik=0000000001&fiscal_year=2025"
        )
        with urllib.request.urlopen(url) as response:
            payload = json.loads(response.read())
        assert payload["company_description"]["text"].startswith("<img src=x")
        assert payload["company_description"]["profile_url"].startswith("https://")
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
            html = response.read().decode()
        assert "onerror=alert" not in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
