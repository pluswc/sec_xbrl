import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.package_cache import (
    AccessionPackageCache,
    PackageCacheError,
    PackageIntegrityError,
    SECArchiveClient,
)


def _filing() -> FilingRef:
    return FilingRef("0000320193", "0000320193-25-000079", "10-K", date(2025, 10, 31))


def test_package_cache_downloads_validates_and_reuses_without_network(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["User-Agent"] == "sec-xbrl contact@example.com"
        return httpx.Response(200, content=b"zip" if request.url.path.endswith(".zip") else b"headers")

    client = SECArchiveClient(
        user_agent="sec-xbrl contact@example.com",
        min_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    cache = AccessionPackageCache(tmp_path / "packages")

    manifest = cache.ensure(_filing(), client)
    assert len(calls) == 2
    assert manifest.cik == "0000320193"
    assert manifest.source == "sec_archive"
    assert [artifact.byte_size for artifact in manifest.artifacts] == [3, 7]
    assert cache.ensure(_filing(), client) == manifest
    assert len(calls) == 2


def test_package_cache_rejects_corrupt_or_partial_published_content(tmp_path: Path) -> None:
    cache = AccessionPackageCache(tmp_path / "packages")
    filing = _filing()
    package_dir = cache.package_dir(filing)
    package_dir.mkdir(parents=True)
    with pytest.raises(PackageIntegrityError, match="unpublished or partial"):
        cache.ensure(filing, _NeverFetch())


def test_package_cache_rejects_tampered_published_artifact_or_provenance(tmp_path: Path) -> None:
    cache = AccessionPackageCache(tmp_path / "packages")
    filing = _filing()
    cache.ensure(filing, _StaticFetch())
    package_dir = cache.package_dir(filing)
    zip_path = package_dir / f"{filing.accession}-xbrl.zip"
    zip_path.write_bytes(b"tampered")
    with pytest.raises(PackageIntegrityError, match="artifact hash mismatch"):
        cache.ensure(filing, _NeverFetch())

    cache = AccessionPackageCache(tmp_path / "other-packages")
    cache.ensure(filing, _StaticFetch())
    manifest_path = cache.package_dir(filing) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    original_url = manifest["artifacts"][0]["source_url"]
    manifest["artifacts"][0]["source_url"] = "https://invalid.example/file"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageIntegrityError, match="source URL mismatch"):
        cache.ensure(filing, _NeverFetch())

    manifest["artifacts"][0]["source_url"] = original_url
    manifest["artifacts"].append(manifest["artifacts"][0])
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PackageIntegrityError, match="artifact set mismatch"):
        cache.ensure(filing, _NeverFetch())


def test_package_cache_cleans_failed_temporary_download_and_rejects_bad_accession(tmp_path: Path) -> None:
    cache = AccessionPackageCache(tmp_path / "packages")
    filing = _filing()
    with pytest.raises(PackageCacheError):
        cache.ensure(filing, _FailOnSecondFetch())
    assert not cache.package_dir(filing).exists()
    assert not list(cache.package_dir(filing).parent.glob(".*.partial-*"))

    invalid = FilingRef("0000320193", "../escape", "10-K", date(2025, 10, 31))
    with pytest.raises(PackageIntegrityError, match="invalid accession"):
        cache.ensure(invalid, _NeverFetch())


def test_archive_client_retries_failed_request_with_mock_transport() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts == 1 else 200, content=b"ok")

    client = SECArchiveClient(
        user_agent="sec-xbrl contact@example.com",
        min_interval_seconds=0,
        retries=1,
        transport=httpx.MockTransport(handler),
    )
    assert client.fetch("https://www.sec.gov/example") == b"ok"
    assert attempts == 2


class _NeverFetch:
    def fetch(self, url: str) -> bytes:
        raise AssertionError(f"network must not be used: {url}")


class _StaticFetch:
    def fetch(self, url: str) -> bytes:
        return b"zip" if url.endswith(".zip") else b"headers"


class _FailOnSecondFetch:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, url: str) -> bytes:
        self.calls += 1
        if self.calls == 2:
            raise PackageCacheError("simulated second artifact failure")
        return b"zip"
