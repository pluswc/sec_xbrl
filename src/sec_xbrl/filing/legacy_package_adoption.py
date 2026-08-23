"""Adopt validated accession packages from the read-only XbrlDataLoad layout."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.package_cache import (
    AccessionPackageCache,
    PackageIntegrityError,
    PackageManifest,
)

LEGACY_SOURCE = "legacy_xbrl_data_load"


class LegacyPackageAdoptionError(PackageIntegrityError):
    """Raised when a legacy package cannot be safely adopted."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class LegacyAdoptionIssue:
    cik: str
    accession: str
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class LegacyAdoptionReport:
    adopted: tuple[PackageManifest, ...]
    rejected: tuple[LegacyAdoptionIssue, ...]


class LegacyPackageAdopter:
    """Read the documented legacy layout without importing or modifying that project."""

    def __init__(self, legacy_data_root: Path, cache: AccessionPackageCache) -> None:
        self.legacy_data_root = legacy_data_root
        self.cache = cache

    def adopt(self, filings: Iterable[FilingRef]) -> LegacyAdoptionReport:
        adopted: list[PackageManifest] = []
        rejected: list[LegacyAdoptionIssue] = []
        for filing in filings:
            try:
                adopted.append(self.adopt_one(filing))
            except LegacyPackageAdoptionError as exc:
                rejected.append(
                    LegacyAdoptionIssue(
                        cik=canonicalize_cik(filing.cik),
                        accession=filing.accession,
                        code=exc.code,
                        detail=str(exc),
                    )
                )
        return LegacyAdoptionReport(tuple(adopted), tuple(rejected))

    def adopt_one(self, filing: FilingRef) -> PackageManifest:
        metadata, package_dir = self._find_metadata_and_package(filing)
        self._validate_identity(metadata, filing)
        artifact_paths = self._artifact_paths(filing, package_dir)
        self._validate_content(artifact_paths)
        return self.cache.adopt(filing, source=LEGACY_SOURCE, artifact_paths=artifact_paths)

    def _find_metadata_and_package(self, filing: FilingRef) -> tuple[dict[str, object], Path]:
        if not self.legacy_data_root.is_dir():
            raise LegacyPackageAdoptionError("LEGACY_ROOT_MISSING", str(self.legacy_data_root))
        matches: list[tuple[dict[str, object], Path]] = []
        for index_path in sorted(self.legacy_data_root.glob("*/index.json")):
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LegacyPackageAdoptionError("LEGACY_INDEX_INVALID", str(index_path)) from exc
            filings = index.get("filings")
            if not isinstance(filings, list):
                raise LegacyPackageAdoptionError("LEGACY_INDEX_INVALID", f"missing filings: {index_path}")
            for metadata in filings:
                if isinstance(metadata, dict) and metadata.get("adsh") == filing.accession:
                    matches.append((metadata, index_path.parent / filing.accession))
        if not matches:
            raise LegacyPackageAdoptionError("LEGACY_ACCESSION_MISSING", filing.accession)
        if len(matches) > 1:
            raise LegacyPackageAdoptionError("LEGACY_ACCESSION_AMBIGUOUS", filing.accession)
        return matches[0]

    def _validate_identity(self, metadata: dict[str, object], filing: FilingRef) -> None:
        expected = (canonicalize_cik(filing.cik), filing.accession, filing.form)
        try:
            actual = (canonicalize_cik(str(metadata["cik"])), str(metadata["adsh"]), str(metadata["form"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise LegacyPackageAdoptionError("LEGACY_IDENTITY_INVALID", filing.accession) from exc
        if actual != expected:
            raise LegacyPackageAdoptionError(
                "LEGACY_IDENTITY_MISMATCH", f"expected {expected!r}, found {actual!r}"
            )

    def _artifact_paths(self, filing: FilingRef, package_dir: Path) -> dict[str, Path]:
        return {
            f"{filing.accession}-xbrl.zip": package_dir / f"{filing.accession}-xbrl.zip",
            f"{filing.accession}-index-headers.html": package_dir
            / f"{filing.accession}-index-headers.html",
        }

    def _validate_content(self, artifact_paths: dict[str, Path]) -> None:
        zip_path = next(path for name, path in artifact_paths.items() if name.endswith(".zip"))
        header_path = next(path for name, path in artifact_paths.items() if name.endswith(".html"))
        if not zip_path.is_file():
            raise LegacyPackageAdoptionError("LEGACY_ZIP_MISSING", str(zip_path))
        if not header_path.is_file():
            raise LegacyPackageAdoptionError("LEGACY_HEADERS_MISSING", str(header_path))
        if zip_path.stat().st_size == 0:
            raise LegacyPackageAdoptionError("LEGACY_ZIP_EMPTY", str(zip_path))
        if header_path.stat().st_size == 0:
            raise LegacyPackageAdoptionError("LEGACY_HEADERS_EMPTY", str(header_path))
        if not zipfile.is_zipfile(zip_path):
            raise LegacyPackageAdoptionError("LEGACY_ZIP_INVALID", str(zip_path))
