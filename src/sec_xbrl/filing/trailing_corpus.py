"""Deterministic trailing-fiscal-year filing corpus orchestration.

This module is intentionally a *consumer* of Filing Discovery, immutable
package caching, Layer 1 ingestion, and the analysis adapters.  It does not
know a ticker, company name, or accession number.  Its public boundary is a
CIK-scoped :class:`AccessionProvider` and a requested number of annual
baselines.

The selected window is fiscal rather than calendar based: it begins immediately
after the annual baseline preceding the oldest selected 10-K and includes all
10-K/10-Q amendments through the latest discovered filing.  A corpus analysis
is published only if every selected filing has an atomic Layer 1 snapshot.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from sec_xbrl.filing.contracts import AccessionProvider, FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, ResolvedFiling
from sec_xbrl.filing.layer1_ingestion import Layer1Ingestor, Layer1SnapshotManifest
from sec_xbrl.longitudinal import CompanyCanonicalizer, RecastObservationBuilder, SeriesBuilder
from sec_xbrl.periods.logic import Layer1PeriodAnalysis

FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})


class TrailingCorpusError(RuntimeError):
    """Raised when the requested trailing fiscal-year selection is invalid."""


class FilingResolver(Protocol):
    def resolve(self, filing: FilingRef, fetcher: object) -> ResolvedFiling: ...


class FilingIngestor(Protocol):
    def load_and_ingest(
        self, resolved: ResolvedFiling, loader: ArelleFilingLoader, extraction_dir: Path
    ) -> Layer1SnapshotManifest: ...


@dataclass(frozen=True, slots=True)
class CorpusFilingStatus:
    accession: str
    form: str
    filed_date: str
    report_date: str | None
    status: str
    source_url: str | None
    source_fact_count: int | None = None
    materialized_fact_count: int | None = None
    error: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TrailingCorpusReport:
    schema_version: int
    cik: str
    fiscal_years_requested: int
    annual_baseline_accessions: tuple[str, ...]
    window_start_report_date_exclusive: str | None
    filings: tuple[CorpusFilingStatus, ...]
    analysis_status: str
    analysis_reason: str | None
    period_observation_count: int
    annual_series_count: int
    current_series_count: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def select_trailing_fiscal_filings(
    filings: Iterable[FilingRef], *, fiscal_years: int
) -> tuple[tuple[FilingRef, ...], tuple[FilingRef, ...], FilingRef | None]:
    """Select annual baselines and all intervening updates deterministically.

    The third return value is the predecessor annual baseline which defines the
    exclusive lower window boundary.  It is evidence only, not itself selected.
    10-K is preferred to 10-K/A as an annual baseline; amendments are retained
    when their report period falls inside the selected coverage.
    """
    if fiscal_years < 1:
        raise TrailingCorpusError("fiscal_years must be at least one")
    # ``report_date`` controls fiscal coverage only.  It must not control
    # ingestion order: an amendment for an older report period can be filed
    # after a newer normal quarterly filing.
    all_rows = tuple(sorted(set(filings), key=_coverage_order))
    annuals = [row for row in all_rows if row.form == "10-K" and row.report_date is not None]
    by_period: dict[object, FilingRef] = {}
    for row in annuals:
        # Later filed duplicate annual records are deterministic but never
        # replace the baseline 10-K with an amendment.
        by_period.setdefault(row.report_date, row)
    baselines = tuple(sorted(by_period.values(), key=_coverage_order)[-fiscal_years:])
    if len(baselines) != fiscal_years:
        raise TrailingCorpusError(
            f"requires {fiscal_years} annual 10-K baselines with report_date; found {len(baselines)}"
        )
    earliest = baselines[0]
    predecessor = max(
        (row for row in by_period.values() if row.report_date < earliest.report_date),
        key=_coverage_order,
        default=None,
    )
    boundary = predecessor.report_date if predecessor else None
    selected = tuple(
        row
        for row in all_rows
        if row.form in FORMS
        and (boundary is None or row.report_date is None or row.report_date > boundary)
    )
    return tuple(sorted(selected, key=_processing_order)), baselines, predecessor


class TrailingFilingCorpus:
    """Build a complete company corpus then connect its M6/M7 analysis rows."""

    def __init__(
        self,
        *,
        provider: AccessionProvider,
        resolver: FilingResolver,
        fetcher: object,
        ingestor: FilingIngestor,
        loader: ArelleFilingLoader,
        snapshot_root: Path,
        extraction_root: Path,
        report_root: Path | None = None,
    ) -> None:
        self.provider = provider
        self.resolver = resolver
        self.fetcher = fetcher
        self.ingestor = ingestor
        self.loader = loader
        self.snapshot_root = snapshot_root
        self.extraction_root = extraction_root
        self.report_root = report_root

    def run(self, *, fiscal_years: int = 3) -> TrailingCorpusReport:
        rows = tuple(self.provider.iter_filings(forms=set(FORMS)))
        selected, baselines, predecessor = select_trailing_fiscal_filings(
            rows, fiscal_years=fiscal_years
        )
        statuses: list[CorpusFilingStatus] = []
        manifests: list[Layer1SnapshotManifest] = []
        for filing in selected:
            try:
                manifest, status = self._ingest_one(filing)
                manifests.append(manifest)
                statuses.append(status)
            except Exception as exc:  # noqa: BLE001 - pipeline errors are a retryable report boundary.
                statuses.append(_failed_status(filing, exc))
        success = len(manifests) == len(selected)
        if success:
            analysis = self._build_analysis(selected)
            analysis_status, reason = "AVAILABLE", None
        else:
            analysis = {"period": 0, "annual": 0, "current": 0}
            analysis_status, reason = "NOT_PUBLISHED", "COMPLETE_LAYER1_CORPUS_REQUIRED"
        cik = selected[0].cik if selected else (rows[0].cik if rows else "")
        report = TrailingCorpusReport(
            schema_version=1,
            cik=cik,
            fiscal_years_requested=fiscal_years,
            annual_baseline_accessions=tuple(row.accession for row in baselines),
            window_start_report_date_exclusive=(
                predecessor.report_date.isoformat()
                if predecessor and predecessor.report_date
                else None
            ),
            filings=tuple(statuses),
            analysis_status=analysis_status,
            analysis_reason=reason,
            period_observation_count=analysis["period"],
            annual_series_count=analysis["annual"],
            current_series_count=analysis["current"],
        )
        self._publish_report(report)
        return report

    def _ingest_one(self, filing: FilingRef) -> tuple[Layer1SnapshotManifest, CorpusFilingStatus]:
        # Existing immutable snapshots are reusable and require no network.
        destination = self.snapshot_root / filing.cik / filing.accession.replace("-", "")
        manifest_path = destination / Layer1Ingestor.manifest_name
        if manifest_path.is_file():
            manifest = Layer1SnapshotManifest.from_path(manifest_path)
            return manifest, _success_status(filing, manifest, "ALREADY_PUBLISHED")
        resolved = self.resolver.resolve(filing, self.fetcher)
        # A failed Arelle attempt may have left extracted package files behind.
        # Keep retries isolated instead of reusing a directory whose contents
        # are not an immutable published artifact.
        extraction = self.extraction_root / filing.accession.replace("-", "") / uuid.uuid4().hex
        manifest = self.ingestor.load_and_ingest(resolved, self.loader, extraction)
        return manifest, _success_status(filing, manifest, "PUBLISHED")

    def _build_analysis(self, filings: tuple[FilingRef, ...]) -> dict[str, int]:
        tables = _read_snapshot_tables(self.snapshot_root, filings)
        period_facts: list[dict[str, Any]] = []
        for filing in tables["filing"]:
            filing_id = str(filing["filing_id"])
            facts = [row for row in tables["fact"] if str(row.get("filing_id")) == filing_id]
            contexts = [row for row in tables["context"] if str(row.get("filing_id")) == filing_id]
            concepts = [row for row in tables["concept"] if str(row.get("filing_id")) == filing_id]
            dimensions = [
                row
                for row in tables["dimension_fact"]
                if str(row.get("fact_id")) in {str(item.get("fact_id")) for item in facts}
            ]
            observations, _ = Layer1PeriodAnalysis().build(
                filing=filing,
                concepts=concepts,
                contexts=contexts,
                facts=facts,
                dimension_facts=dimensions,
                units=(),
            )
            period_facts.extend(observations)
        mappings = CompanyCanonicalizer().build(
            filings=tables["filing"],
            concepts=tables["concept"],
            dimension_facts=tables["dimension_fact"],
            relationships=tables["relationship"],
        )
        builder = SeriesBuilder()
        annual = builder.annual(
            filings=tables["filing"],
            facts=period_facts,
            mappings=mappings,
            dimension_facts=tables["dimension_fact"],
        )
        current = builder.current(
            filings=tables["filing"],
            facts=period_facts,
            mappings=mappings,
            dimension_facts=tables["dimension_fact"],
        )
        # This explicit Layer 2 hand-off keeps reported/recast governed even
        # when no reviewed recast evidence has yet been supplied.
        current = RecastObservationBuilder().build(current)
        return {"period": len(period_facts), "annual": len(annual), "current": len(current)}

    def _publish_report(self, report: TrailingCorpusReport) -> None:
        if self.report_root is None:
            return
        destination = self.report_root / report.cik / "trailing_corpus_manifest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, delete=False
        ) as temp:
            temp.write(report.to_json())
            temporary = Path(temp.name)
        os.replace(temporary, destination)


def _read_snapshot_tables(
    root: Path, filings: Iterable[FilingRef]
) -> dict[str, list[dict[str, Any]]]:
    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover
        raise TrailingCorpusError("polars is required for trailing corpus analysis") from exc
    names = ("filing", "concept", "context", "fact", "dimension_fact", "relationship")
    result = {name: [] for name in names}
    for filing in filings:
        directory = root / filing.cik / filing.accession.replace("-", "")
        for name in names:
            result[name].extend(pl.read_parquet(directory / f"{name}.parquet").to_dicts())
    return result


def _coverage_order(row: FilingRef) -> tuple[object, object, object]:
    return (row.report_date or row.filed_date, row.filed_date, row.accession)


def _processing_order(row: FilingRef) -> tuple[object, object]:
    """Order processing by public availability, never by covered period."""
    return (row.filed_date, row.accession)


def _success_status(
    filing: FilingRef, manifest: Layer1SnapshotManifest, status: str
) -> CorpusFilingStatus:
    return CorpusFilingStatus(
        accession=filing.accession,
        form=filing.form,
        filed_date=filing.filed_date.isoformat(),
        report_date=filing.report_date.isoformat() if filing.report_date else None,
        status=status,
        source_url=manifest.source_url,
        source_fact_count=manifest.source_fact_count,
        materialized_fact_count=manifest.materialized_fact_count,
    )


def _failed_status(filing: FilingRef, exc: Exception) -> CorpusFilingStatus:
    return CorpusFilingStatus(
        accession=filing.accession,
        form=filing.form,
        filed_date=filing.filed_date.isoformat(),
        report_date=filing.report_date.isoformat() if filing.report_date else None,
        status="FAILED",
        source_url=None,
        error=f"{type(exc).__name__}: {exc}",
        retryable=True,
    )
