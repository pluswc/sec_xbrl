"""Verified, immutable Layer 1 corpus input for a future Layer 2 run.

This adapter is intentionally before all Layer 2 analytical policy.  It reads
an explicitly named trailing-corpus release, verifies the complete atomic
Layer 1 snapshots it selects, and returns immutable records plus the precise
``Layer2Run`` declaration that later producers must consume.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.layer1_ingestion import Layer1IngestionError, Layer1Ingestor, Layer1SnapshotManifest
from sec_xbrl.longitudinal.materialization import (
    Layer1SnapshotInput,
    Layer2RuleVersions,
    Layer2Run,
)


RAW_TABLES = Layer1Ingestor.required_table_names


class CorpusReleaseError(RuntimeError):
    """Raised when an on-disk corpus cannot safely become a Layer 2 input."""


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    """One validated immutable Layer 1 snapshot and all of its raw tables."""

    input: Layer1SnapshotInput
    manifest: Layer1SnapshotManifest
    manifest_path: Path
    table_sha256: Mapping[str, str]
    table_counts: Mapping[str, int]
    tables: Mapping[str, tuple[Mapping[str, Any], ...]]

    def records(self, table: str) -> tuple[dict[str, Any], ...]:
        """Return independent copies; callers cannot mutate release records."""
        if table not in RAW_TABLES:
            raise CorpusReleaseError(f"unknown raw Layer 1 table: {table}")
        return tuple(dict(row) for row in self.tables[table])


@dataclass(frozen=True, slots=True)
class CorpusRelease:
    """A deterministic, complete raw corpus selected for one Layer 2 run."""

    corpus_root: Path
    corpus_run_id: str
    ciks: tuple[str, ...]
    snapshots: tuple[CorpusSnapshot, ...]
    layer2_run: Layer2Run

    def snapshot_records(self, snapshot_id: str, table: str) -> tuple[dict[str, Any], ...]:
        for snapshot in self.snapshots:
            if snapshot.input.snapshot_id == snapshot_id:
                return snapshot.records(table)
        raise CorpusReleaseError(f"unknown corpus snapshot_id: {snapshot_id}")

    def records(self, table: str) -> tuple[dict[str, Any], ...]:
        """Return deterministic release-wide copies of a required raw table."""
        return tuple(row for snapshot in self.snapshots for row in snapshot.records(table))


class CorpusReleaseAdapter:
    """Turn an exact, already-published trailing corpus into an L2 input.

    ``corpus_root`` and ``corpus_run_id`` are both explicit.  The adapter never
    discovers a latest run and never invokes the legacy transient corpus
    analysis path.  It reads the eight complete Layer 1 tables, including
    ``unit``, ``role`` and ``relationship``.
    """

    summary_name = "run_summary.json"
    metadata_name = "run_metadata.json"

    def load(
        self,
        corpus_root: Path,
        *,
        corpus_run_id: str,
        ciks: Iterable[str],
        run_version: str,
        rules: Layer2RuleVersions,
    ) -> CorpusRelease:
        root = Path(corpus_root)
        requested = tuple(sorted({canonicalize_cik(cik) for cik in ciks}))
        if not requested:
            raise CorpusReleaseError("at least one requested CIK is required")
        if not root.is_dir() or root.is_symlink() or root.name != corpus_run_id:
            raise CorpusReleaseError("corpus_root must be an explicit non-symlink corpus_run_id directory")
        metadata = _read_json(root / self.metadata_name, "corpus metadata")
        if metadata.get("run_id") != corpus_run_id:
            raise CorpusReleaseError("corpus metadata run_id does not match requested corpus_run_id")
        summary = _read_json(root / self.summary_name, "corpus summary")
        companies = _companies_by_cik(summary)
        missing = sorted(set(requested) - set(companies))
        if missing:
            raise CorpusReleaseError(f"requested CIKs are absent from corpus summary: {missing}")

        snapshots: list[CorpusSnapshot] = []
        for cik in requested:
            snapshots.extend(_load_company(root, cik, companies[cik]))
        snapshots.sort(key=lambda item: (
            item.input.cik,
            item.input.filed_date,
            item.input.accession,
            item.input.snapshot_id,
        ))
        identities = {(item.input.cik, item.input.accession, item.input.snapshot_id) for item in snapshots}
        if len(identities) != len(snapshots):
            raise CorpusReleaseError("duplicate Layer 1 snapshot identity in corpus release")
        run = Layer2Run(
            run_version=run_version,
            corpus_run_id=corpus_run_id,
            inputs=tuple(item.input for item in snapshots),
            rules=rules,
        )
        return CorpusRelease(root, corpus_run_id, requested, tuple(snapshots), run)


def _load_company(root: Path, cik: str, company: Mapping[str, Any]) -> list[CorpusSnapshot]:
    report = company.get("report")
    integrity = company.get("integrity")
    if not isinstance(report, Mapping) or report.get("cik") != cik:
        raise CorpusReleaseError(f"corpus summary report identity is invalid for {cik}")
    if report.get("analysis_status") != "AVAILABLE":
        raise CorpusReleaseError(f"corpus summary is not complete/available for {cik}")
    if not isinstance(integrity, list) or not integrity:
        raise CorpusReleaseError(f"corpus summary has no snapshot integrity records for {cik}")
    filing_rows = report.get("filings")
    if not isinstance(filing_rows, list):
        raise CorpusReleaseError(f"corpus summary has no filing records for {cik}")
    by_accession = {str(row.get("accession")): row for row in filing_rows if isinstance(row, Mapping)}
    snapshots: list[CorpusSnapshot] = []
    seen_accessions: set[str] = set()
    for item in integrity:
        if not isinstance(item, Mapping):
            raise CorpusReleaseError(f"invalid integrity record for {cik}")
        accession = str(item.get("accession") or "")
        if not accession or accession in seen_accessions:
            raise CorpusReleaseError(f"duplicate or missing accession in corpus integrity for {cik}")
        seen_accessions.add(accession)
        filing = by_accession.get(accession)
        if filing is None or filing.get("status") != "PUBLISHED":
            raise CorpusReleaseError(f"unpublished/missing filing record for {cik} {accession}")
        if item.get("status") != "PUBLISHED" or item.get("counts_match") is not True:
            raise CorpusReleaseError(f"snapshot integrity gate failed for {cik} {accession}")
        missing = item.get("missing_tables")
        if missing not in ([], ()) or item.get("required_table_count") != len(RAW_TABLES):
            raise CorpusReleaseError(f"snapshot table completeness gate failed for {cik} {accession}")
        relative = Path("snapshots") / cik / accession.replace("-", "")
        directory = root / relative
        # The summary's saved path is diagnostic only; a corpus release is
        # relocatable and must not trust an arbitrary external path.
        snapshots.append(_load_snapshot(directory, cik, filing, item))
    if set(by_accession) != seen_accessions:
        raise CorpusReleaseError(f"corpus filing/integrity coverage mismatch for {cik}")
    return snapshots


def _load_snapshot(
    directory: Path, cik: str, filing: Mapping[str, Any], integrity: Mapping[str, Any]
) -> CorpusSnapshot:
    if not directory.is_dir() or directory.is_symlink() or ".partial-" in directory.name:
        raise CorpusReleaseError(f"snapshot is missing, non-atomic, or unsafe: {directory}")
    expected_names = {"layer1_manifest.json", *(f"{name}.parquet" for name in RAW_TABLES)}
    actual_names = {child.name for child in directory.iterdir()}
    if actual_names != expected_names or any(child.is_symlink() for child in directory.iterdir()):
        raise CorpusReleaseError(f"snapshot has incomplete or unexpected atomic layout: {directory}")
    manifest_path = directory / "layer1_manifest.json"
    try:
        manifest = Layer1SnapshotManifest.from_path(manifest_path)
    except Layer1IngestionError as exc:
        raise CorpusReleaseError(f"invalid Layer 1 manifest: {directory}") from exc
    accession = str(filing.get("accession") or "")
    if (
        manifest.cik != cik
        or manifest.accession != accession
        or manifest.form != filing.get("form")
        or directory.name != accession.replace("-", "")
    ):
        raise CorpusReleaseError(f"snapshot manifest identity does not match corpus summary: {directory}")
    table_counts: dict[str, int] = {}
    table_hashes: dict[str, str] = {}
    tables: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for name in RAW_TABLES:
        path = directory / f"{name}.parquet"
        before = _sha256_file(path)
        rows = _read_parquet(path)
        after = _sha256_file(path)
        if before != after:
            raise CorpusReleaseError(f"raw table changed while reading snapshot: {path}")
        table_counts[name] = len(rows)
        table_hashes[name] = before
        tables[name] = tuple(MappingProxyType(dict(row)) for row in rows)
    _validate_table_counts(manifest, table_counts, integrity, directory)
    _validate_filing_rows(tables, cik, accession, directory)
    manifest_sha = _sha256_file(manifest_path)
    parser_version = manifest.layer1_parser_version or None
    snapshot_id = f"l1:{cik}:{accession.replace('-', '')}:{manifest_sha[:16]}"
    return CorpusSnapshot(
        Layer1SnapshotInput(
            cik=cik,
            accession=accession,
            form=manifest.form,
            filed_date=str(filing.get("filed_date") or ""),
            report_date=str(filing.get("report_date") or ""),
            snapshot_id=snapshot_id,
            manifest_sha256=manifest_sha,
            parser_version=parser_version,
        ),
        manifest,
        manifest_path,
        MappingProxyType(table_hashes),
        MappingProxyType(table_counts),
        MappingProxyType(tables),
    )


def _validate_table_counts(
    manifest: Layer1SnapshotManifest,
    counts: Mapping[str, int],
    integrity: Mapping[str, Any],
    directory: Path,
) -> None:
    expected = {
        "fact": manifest.materialized_fact_count,
        "concept": manifest.concept_count,
        "context": manifest.context_count,
        "unit": manifest.unit_count,
        "dimension_fact": manifest.dimension_fact_count,
        "role": manifest.role_count,
        "relationship": manifest.relationship_count,
    }
    if counts["filing"] != 1 or any(counts[name] != value for name, value in expected.items()):
        raise CorpusReleaseError(f"Layer 1 manifest table counts do not match bytes: {directory}")
    if integrity.get("materialized_fact_count") != counts["fact"] or integrity.get("source_fact_count") != manifest.source_fact_count:
        raise CorpusReleaseError(f"corpus summary counts do not match Layer 1 manifest: {directory}")


def _validate_filing_rows(
    tables: Mapping[str, tuple[Mapping[str, Any], ...]], cik: str, accession: str, directory: Path
) -> None:
    filing = tables["filing"][0]
    if filing.get("cik") != cik or filing.get("accession") != accession or not filing.get("filing_id"):
        raise CorpusReleaseError(f"filing table identity does not match snapshot: {directory}")
    filing_id = str(filing["filing_id"])
    for name in ("concept", "context", "unit", "fact", "role", "relationship"):
        if any(str(row.get("filing_id")) != filing_id for row in tables[name]):
            raise CorpusReleaseError(f"foreign or missing filing identity in {name}: {directory}")


def _companies_by_cik(summary: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = summary.get("companies")
    if not isinstance(rows, list):
        raise CorpusReleaseError("corpus summary has no companies collection")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("cik"):
            raise CorpusReleaseError("corpus summary contains an invalid company record")
        cik = canonicalize_cik(str(row["cik"]))
        if cik in result:
            raise CorpusReleaseError(f"duplicate company CIK in corpus summary: {cik}")
        result[cik] = row
    return result


def _read_json(path: Path, description: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise CorpusReleaseError(f"missing or unsafe {description}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusReleaseError(f"invalid {description}: {path}") from exc
    if not isinstance(value, Mapping):
        raise CorpusReleaseError(f"invalid {description} shape: {path}")
    return value


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover - project dependency
        raise CorpusReleaseError("polars is required to read a Layer 1 corpus release") from exc
    try:
        return pl.read_parquet(path).to_dicts()
    except Exception as exc:  # noqa: BLE001 - corrupt raw data must fail closed.
        raise CorpusReleaseError(f"invalid raw parquet table: {path}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()
