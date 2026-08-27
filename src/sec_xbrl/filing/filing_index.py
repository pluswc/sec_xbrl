"""Resolve a cached SEC filing package to a local Arelle entry point."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.package_cache import (
    AccessionPackageCache,
    ArchiveFetcher,
    PackageIntegrityError,
)


class FilingIndexError(RuntimeError):
    """Raised when an accession filing index cannot be safely resolved."""


class ArelleLoadError(RuntimeError):
    """Raised when Arelle does not create a model for a resolved filing."""


@dataclass(frozen=True, slots=True)
class FilingIndexEntry:
    """One file entry in the SEC ``index.json`` directory listing."""

    name: str
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class FilingIndex:
    cik: str
    accession: str
    source_url: str
    entries: tuple[FilingIndexEntry, ...]


@dataclass(frozen=True, slots=True)
class ResolvedFiling:
    """Immutable package paths and the selected Arelle entry-point filename."""

    filing: FilingRef
    index: FilingIndex
    zip_path: Path
    entrypoint_name: str


class ArelleModelLoader(Protocol):
    def __call__(self, entrypoint: Path) -> Any: ...


class FilingIndexCache:
    """Immutable cache for an accession's SEC directory ``index.json`` payload."""

    archive_base_url = "https://www.sec.gov/Archives/edgar/data"

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self, filing: FilingRef, fetcher: ArchiveFetcher) -> FilingIndex:
        cache_dir = self.cache_dir(filing)
        index_path = cache_dir / "index.json"
        manifest_path = cache_dir / "manifest.json"
        if index_path.exists() or manifest_path.exists():
            return self._read_cached(filing, cache_dir)
        if cache_dir.exists():
            raise FilingIndexError(f"unpublished or partial filing index directory: {cache_dir}")

        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".index.partial-", dir=cache_dir.parent))
        try:
            source_url = self.source_url(filing)
            content = fetcher.fetch(source_url)
            (temporary / "index.json").write_bytes(content)
            index = self._parse(filing, source_url, content)
            manifest = {
                "cik": index.cik,
                "accession": index.accession,
                "source_url": source_url,
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(temporary, cache_dir)
            return index
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def cache_dir(self, filing: FilingRef) -> Path:
        return self.root / canonicalize_cik(filing.cik) / self._accession_nodash(filing)

    def source_url(self, filing: FilingRef) -> str:
        cik = str(int(canonicalize_cik(filing.cik)))
        return f"{self.archive_base_url}/{cik}/{self._accession_nodash(filing)}/index.json"

    def _read_cached(self, filing: FilingRef, cache_dir: Path) -> FilingIndex:
        index_path = cache_dir / "index.json"
        manifest_path = cache_dir / "manifest.json"
        if not index_path.is_file() or not manifest_path.is_file():
            raise FilingIndexError(f"unpublished or partial filing index directory: {cache_dir}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            content = index_path.read_bytes()
            expected = (canonicalize_cik(filing.cik), filing.accession, self.source_url(filing))
            actual = (manifest["cik"], manifest["accession"], manifest["source_url"])
            if actual != expected:
                raise FilingIndexError("filing index manifest identity mismatch")
            if manifest["byte_size"] != len(content) or manifest["sha256"] != hashlib.sha256(content).hexdigest():
                raise FilingIndexError("filing index artifact hash mismatch")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise FilingIndexError(f"invalid filing index manifest: {manifest_path}") from exc
        return self._parse(filing, self.source_url(filing), content)

    def _parse(self, filing: FilingRef, source_url: str, content: bytes) -> FilingIndex:
        try:
            payload = json.loads(content)
            items = payload["directory"]["item"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise FilingIndexError("filing index has no directory.item list") from exc
        if not isinstance(items, list):
            raise FilingIndexError("filing index has no directory.item list")
        entries: list[FilingIndexEntry] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise FilingIndexError("filing index contains an invalid directory item")
            name = item["name"]
            if not _is_safe_member_name(name):
                raise FilingIndexError(f"filing index contains unsafe filename: {name!r}")
            item_type = item.get("type")
            if item_type is not None and not isinstance(item_type, str):
                raise FilingIndexError(f"filing index has invalid type for {name!r}")
            entries.append(FilingIndexEntry(name=name, content_type=item_type))
        if not entries:
            raise FilingIndexError("filing index has no directory items")
        return FilingIndex(
            cik=canonicalize_cik(filing.cik),
            accession=filing.accession,
            source_url=source_url,
            entries=tuple(entries),
        )

    @staticmethod
    def _accession_nodash(filing: FilingRef) -> str:
        accession_nodash = filing.accession.replace("-", "")
        if len(accession_nodash) != 18 or not accession_nodash.isdigit():
            raise FilingIndexError(f"invalid accession: {filing.accession!r}")
        return accession_nodash


class FilingPackageResolver:
    """Join the immutable package cache and filing-index cache for one accession."""

    def __init__(self, package_cache: AccessionPackageCache, index_cache: FilingIndexCache) -> None:
        self.package_cache = package_cache
        self.index_cache = index_cache

    def resolve(self, filing: FilingRef, fetcher: ArchiveFetcher) -> ResolvedFiling:
        """Return an entry point after validating cached package artifacts and index metadata."""
        self.package_cache.ensure(filing, fetcher)
        index = self.index_cache.ensure(filing, fetcher)
        zip_path = self.package_cache.package_dir(filing) / f"{filing.accession}-xbrl.zip"
        available = set(_zip_member_names(zip_path))
        entrypoint = _select_entrypoint(filing, index.entries, available)
        return ResolvedFiling(filing=filing, index=index, zip_path=zip_path, entrypoint_name=entrypoint)


class ArelleFilingLoader:
    """Materialize and load a filing with an explicit taxonomy-cache policy.

    Normal ingestion is offline and therefore reproducible from the supplied
    package plus ``taxonomy_cache``.  A one-time cache bootstrap may opt in to
    network resolution explicitly; it is never an accidental side effect of a
    production load.
    """

    def __init__(
        self,
        model_loader: ArelleModelLoader | None = None,
        *,
        taxonomy_cache: Path | None = None,
        allow_network_taxonomy_resolution: bool = False,
    ) -> None:
        self._model_loader = model_loader or (
            lambda entrypoint: _load_with_arelle(
                entrypoint,
                taxonomy_cache=taxonomy_cache,
                allow_network_taxonomy_resolution=allow_network_taxonomy_resolution,
            )
        )

    def load(self, resolved: ResolvedFiling, destination: Path) -> Any:
        """Extract only local package files and pass the selected local path to Arelle."""
        destination.mkdir(parents=True, exist_ok=True)
        _extract_zip(resolved.zip_path, destination)
        entrypoint = destination / resolved.entrypoint_name
        if not entrypoint.is_file():
            raise ArelleLoadError(f"resolved entry point is absent after extraction: {resolved.entrypoint_name}")
        model = self._model_loader(entrypoint)
        if model is None or getattr(model, "modelDocument", None) is None:
            raise ArelleLoadError(f"Arelle did not load entry point: {resolved.entrypoint_name}")
        return model

    @classmethod
    def bootstrap_taxonomy_cache(
        cls, resolved: ResolvedFiling, destination: Path, taxonomy_cache: Path
    ) -> Any:
        """Explicitly populate a reproducible taxonomy cache for one package.

        This is deliberately separate from normal ingestion: callers must
        invoke it knowingly in a network-enabled environment, then archive or
        retain ``taxonomy_cache`` for subsequent offline loads.  The returned
        model is still subject to Layer 1 completeness validation.
        """
        loader = cls(
            taxonomy_cache=taxonomy_cache,
            allow_network_taxonomy_resolution=True,
        )
        return loader.load(resolved, destination)


def _select_entrypoint(
    filing: FilingRef, entries: Iterable[FilingIndexEntry], available: set[str]
) -> str:
    if filing.primary_document:
        if not _is_safe_member_name(filing.primary_document):
            raise FilingIndexError("primary document has unsafe filename")
        if filing.primary_document not in available:
            raise FilingIndexError("primary document is absent from XBRL package")
        return filing.primary_document

    instance_entries = [
        entry.name for entry in entries if entry.content_type == "EX-101.INS" and entry.name in available
    ]
    if len(instance_entries) == 1:
        return instance_entries[0]
    if len(instance_entries) > 1:
        raise FilingIndexError("filing index has ambiguous XBRL instance documents")
    candidates = [
        entry.name
        for entry in entries
        if entry.name in available and Path(entry.name).suffix.lower() in {".htm", ".html", ".xml"}
    ]
    if len(candidates) != 1:
        raise FilingIndexError("filing index cannot determine a unique Arelle entry point")
    return candidates[0]


def _zip_member_names(zip_path: Path) -> tuple[str, ...]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = tuple(info.filename for info in archive.infolist() if not info.is_dir())
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageIntegrityError(f"invalid cached XBRL ZIP: {zip_path}") from exc
    if any(not _is_safe_member_name(name) for name in names):
        raise FilingIndexError("XBRL package contains unsafe filename")
    return names


def _extract_zip(zip_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if not _is_safe_member_name(info.filename):
                    raise FilingIndexError("XBRL package contains unsafe filename")
                target = destination / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise PackageIntegrityError(f"invalid cached XBRL ZIP: {zip_path}") from exc


def _is_safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _load_with_arelle(
    entrypoint: Path,
    *,
    taxonomy_cache: Path | None = None,
    allow_network_taxonomy_resolution: bool = False,
) -> Any:
    try:
        from arelle import Cntlr
    except ImportError as exc:  # pragma: no cover - exercised by the project dependency in CI.
        raise ArelleLoadError("arelle-release is required to load filing packages") from exc
    # SEC-specific transforms are an Arelle runtime dependency, not a filing
    # taxonomy import. Register them before parsing both bootstrap and offline
    # loads so a valid SEC Inline filing is not rejected as incomplete.
    from sec_xbrl.filing.sec_inline_transforms import register_sec_inline_transforms

    register_sec_inline_transforms()
    controller = Cntlr.Cntlr(logFileName="logToBuffer")
    if taxonomy_cache is not None:
        taxonomy_cache.mkdir(parents=True, exist_ok=True)
        controller.webCache.cacheDir = str(taxonomy_cache)
    controller.webCache.workOffline = not allow_network_taxonomy_resolution
    model = controller.modelManager.load(str(entrypoint))
    if model is None or getattr(model, "modelDocument", None) is None:
        try:
            controller.close()
        finally:
            raise ArelleLoadError(f"Arelle did not load entry point: {entrypoint.name}")
    return model
