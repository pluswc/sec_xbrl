"""Immutable accession package cache for SEC XBRL archive artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx

from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.contracts import FilingRef

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class PackageCacheError(RuntimeError):
    """Base error for accession package cache failures."""


class PackageIntegrityError(PackageCacheError):
    """Raised when a published package does not match its manifest."""


@dataclass(frozen=True, slots=True)
class PackageArtifact:
    filename: str
    source_url: str
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class PackageManifest:
    schema_version: int
    cik: str
    accession: str
    form: str
    source: str
    artifacts: tuple[PackageArtifact, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_path(cls, path: Path) -> PackageManifest:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            artifacts = tuple(PackageArtifact(**artifact) for artifact in raw["artifacts"])
            return cls(
                schema_version=raw["schema_version"],
                cik=raw["cik"],
                accession=raw["accession"],
                form=raw["form"],
                source=raw["source"],
                artifacts=artifacts,
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise PackageIntegrityError(f"invalid package manifest: {path}") from exc


class ArchiveFetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


class SECArchiveClient:
    """Synchronous SEC archive client with explicit User-Agent, rate limiting and retry."""

    def __init__(
        self,
        *,
        user_agent: str,
        min_interval_seconds: float = 0.2,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC user agent is required")
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.retries = retries
        self.transport = transport
        self.sleep = sleep
        self._last_request_at = 0.0

    def fetch(self, url: str) -> bytes:
        for attempt in range(self.retries + 1):
            delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if delay > 0:
                self.sleep(delay)
            self._last_request_at = time.monotonic()
            try:
                with httpx.Client(
                    headers={"User-Agent": self.user_agent}, timeout=30.0, transport=self.transport
                ) as client:
                    response = client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise PackageCacheError(f"SEC archive request failed: {url}") from exc
        raise AssertionError("unreachable")


class AccessionPackageCache:
    """Cache immutable ZIP and index-header artifacts for one filing accession."""

    schema_version = 2
    archive_base_url = "https://www.sec.gov/Archives/edgar/data"

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self, filing: FilingRef, fetcher: ArchiveFetcher) -> PackageManifest:
        package_dir = self.package_dir(filing)
        manifest_path = package_dir / "manifest.json"
        if manifest_path.exists():
            manifest = PackageManifest.from_path(manifest_path)
            self._validate(manifest, package_dir, filing)
            return manifest
        if package_dir.exists():
            raise PackageIntegrityError(f"unpublished or partial package directory: {package_dir}")

        package_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{filing.accession.replace('-', '')}.partial-", dir=package_dir.parent)
        )
        try:
            artifacts: list[PackageArtifact] = []
            for filename, url in self._artifact_urls(filing):
                content = fetcher.fetch(url)
                artifact_path = temporary / filename
                artifact_path.write_bytes(content)
                artifacts.append(
                    PackageArtifact(
                        filename=filename,
                        source_url=url,
                        sha256=hashlib.sha256(content).hexdigest(),
                        byte_size=len(content),
                    )
                )
            manifest = PackageManifest(
                schema_version=self.schema_version,
                cik=canonicalize_cik(filing.cik),
                accession=filing.accession,
                form=filing.form,
                source="sec_archive",
                artifacts=tuple(artifacts),
            )
            (temporary / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
            self._validate(manifest, temporary, filing)
            os.replace(temporary, package_dir)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def adopt(
        self,
        filing: FilingRef,
        *,
        source: str,
        artifact_paths: Mapping[str, Path],
    ) -> PackageManifest:
        """Atomically publish verified local artifacts without changing their source."""
        package_dir = self.package_dir(filing)
        manifest_path = package_dir / "manifest.json"
        if manifest_path.exists():
            manifest = PackageManifest.from_path(manifest_path)
            self._validate(manifest, package_dir, filing)
            return manifest
        if package_dir.exists():
            raise PackageIntegrityError(f"unpublished or partial package directory: {package_dir}")
        if not source:
            raise PackageIntegrityError("package source is required")

        expected_urls = dict(self._artifact_urls(filing))
        if set(artifact_paths) != set(expected_urls):
            raise PackageIntegrityError("adopted artifact set mismatch")
        package_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{filing.accession.replace('-', '')}.partial-", dir=package_dir.parent)
        )
        try:
            artifacts = tuple(
                self._copy_artifact(
                    filename=filename,
                    source_path=artifact_paths[filename],
                    destination_dir=temporary,
                    source_url=expected_urls[filename],
                )
                for filename in expected_urls
            )
            manifest = PackageManifest(
                schema_version=self.schema_version,
                cik=canonicalize_cik(filing.cik),
                accession=filing.accession,
                form=filing.form,
                source=source,
                artifacts=artifacts,
            )
            (temporary / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
            self._validate(manifest, temporary, filing)
            os.replace(temporary, package_dir)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def package_dir(self, filing: FilingRef) -> Path:
        return self.root / canonicalize_cik(filing.cik) / self._accession_nodash(filing)

    def _artifact_urls(self, filing: FilingRef) -> tuple[tuple[str, str], ...]:
        cik = str(int(canonicalize_cik(filing.cik)))
        accession_nodash = self._accession_nodash(filing)
        base = f"{self.archive_base_url}/{cik}/{accession_nodash}"
        return (
            (f"{filing.accession}-xbrl.zip", f"{base}/{filing.accession}-xbrl.zip"),
            (f"{filing.accession}-index-headers.html", f"{base}/{filing.accession}-index-headers.html"),
        )

    def _accession_nodash(self, filing: FilingRef) -> str:
        if not _ACCESSION_RE.fullmatch(filing.accession):
            raise PackageIntegrityError(f"invalid accession: {filing.accession!r}")
        return filing.accession.replace("-", "")

    def _copy_artifact(
        self, *, filename: str, source_path: Path, destination_dir: Path, source_url: str
    ) -> PackageArtifact:
        if not source_path.is_file():
            raise PackageIntegrityError(f"missing adopted artifact: {filename}")
        before = source_path.stat()
        digest = hashlib.sha256()
        byte_size = 0
        destination = destination_dir / filename
        with source_path.open("rb") as source_file, destination.open("xb") as destination_file:
            while chunk := source_file.read(1024 * 1024):
                destination_file.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)
        after = source_path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PackageIntegrityError(f"adopted artifact changed while reading: {filename}")
        return PackageArtifact(
            filename=filename,
            source_url=source_url,
            sha256=digest.hexdigest(),
            byte_size=byte_size,
        )

    def _validate(self, manifest: PackageManifest, package_dir: Path, filing: FilingRef) -> None:
        if manifest.schema_version != self.schema_version:
            raise PackageIntegrityError("unsupported package manifest version")
        if (manifest.cik, manifest.accession, manifest.form) != (
            canonicalize_cik(filing.cik),
            filing.accession,
            filing.form,
        ):
            raise PackageIntegrityError("manifest filing identity mismatch")
        expected_urls = dict(self._artifact_urls(filing))
        artifact_names = [artifact.filename for artifact in manifest.artifacts]
        if len(artifact_names) != len(expected_urls) or set(artifact_names) != set(expected_urls):
            raise PackageIntegrityError("manifest artifact set mismatch")
        for artifact in manifest.artifacts:
            if artifact.source_url != expected_urls[artifact.filename]:
                raise PackageIntegrityError(f"manifest source URL mismatch: {artifact.filename}")
            path = package_dir / artifact.filename
            if not path.is_file():
                raise PackageIntegrityError(f"missing package artifact: {artifact.filename}")
            content = path.read_bytes()
            if len(content) != artifact.byte_size or hashlib.sha256(content).hexdigest() != artifact.sha256:
                raise PackageIntegrityError(f"artifact hash mismatch: {artifact.filename}")
