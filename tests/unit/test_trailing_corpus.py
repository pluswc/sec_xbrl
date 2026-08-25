from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.filing.trailing_corpus import TrailingFilingCorpus, select_trailing_fiscal_filings


def _ref(accession: str, form: str, filed: str, report: str) -> FilingRef:
    return FilingRef(
        "0001045810", accession, form, date.fromisoformat(filed), date.fromisoformat(report)
    )


def test_selection_uses_annual_boundaries_not_calendar_years_and_keeps_amendments() -> None:
    rows = (
        _ref("0001045810-22-000001", "10-K", "2022-03-01", "2022-01-30"),
        _ref("0001045810-22-000002", "10-Q", "2022-06-01", "2022-05-01"),
        _ref("0001045810-23-000001", "10-K", "2023-03-01", "2023-01-29"),
        _ref("0001045810-23-000002", "10-Q", "2023-06-01", "2023-04-30"),
        _ref("0001045810-24-000001", "10-K", "2024-03-01", "2024-01-28"),
        _ref("0001045810-24-000002", "10-Q/A", "2024-07-01", "2024-04-28"),
        _ref("0001045810-25-000001", "10-K", "2025-03-01", "2025-01-26"),
        _ref("0001045810-25-000002", "10-Q", "2025-06-01", "2025-04-27"),
    )
    selected, baselines, predecessor = select_trailing_fiscal_filings(rows, fiscal_years=3)
    assert [row.accession for row in baselines] == [
        "0001045810-23-000001",
        "0001045810-24-000001",
        "0001045810-25-000001",
    ]
    assert predecessor and predecessor.accession == "0001045810-22-000001"
    assert [row.accession for row in selected] == [row.accession for row in rows[1:]]


class _Provider:
    def __init__(self, rows: tuple[FilingRef, ...]) -> None:
        self.rows = rows

    def iter_filings(self, *, forms: set[str]):
        return iter(row for row in self.rows if row.form in forms)


class _Resolver:
    def resolve(self, filing: FilingRef, fetcher: object) -> object:
        assert fetcher is _CACHED_FETCHER
        return type("Resolved", (), {"filing": filing})()


class _Ingestor:
    def __init__(self, root: Path, fail: str | None = None) -> None:
        self.root, self.fail, self.calls = root, fail, []

    def load_and_ingest(
        self, resolved: object, loader: object, extraction_dir: Path
    ) -> Layer1SnapshotManifest:
        filing = resolved.filing
        self.calls.append(filing.accession)
        if filing.accession == self.fail:
            raise RuntimeError("offline package missing")
        directory = self.root / filing.cik / filing.accession.replace("-", "")
        directory.mkdir(parents=True)
        manifest = _manifest(filing)
        (directory / "layer1_manifest.json").write_text(manifest.to_json())
        return manifest


_CACHED_FETCHER = object()


def _manifest(filing: FilingRef) -> Layer1SnapshotManifest:
    return Layer1SnapshotManifest(
        1,
        filing.cik,
        filing.accession,
        filing.form,
        "cached://index",
        "hash",
        "model.facts",
        2,
        2,
        2,
        1,
        1,
        0,
        1,
        1,
        "test",
        "test",
    )


def _rows() -> tuple[FilingRef, ...]:
    return (
        _ref("0001045810-22-000001", "10-K", "2022-03-01", "2022-01-30"),
        _ref("0001045810-23-000001", "10-K", "2023-03-01", "2023-01-29"),
        _ref("0001045810-24-000001", "10-K", "2024-03-01", "2024-01-28"),
        _ref("0001045810-25-000001", "10-K", "2025-03-01", "2025-01-26"),
    )


def test_partial_failure_leaves_analysis_unpublished_and_reports_retryable(tmp_path: Path) -> None:
    ingestor = _Ingestor(tmp_path / "snapshots", fail="0001045810-24-000001")
    corpus = TrailingFilingCorpus(
        provider=_Provider(_rows()),
        resolver=_Resolver(),
        fetcher=_CACHED_FETCHER,
        ingestor=ingestor,
        loader=object(),
        snapshot_root=tmp_path / "snapshots",
        extraction_root=tmp_path / "extract",
        report_root=tmp_path / "reports",
    )
    report = corpus.run(fiscal_years=3)
    assert report.analysis_status == "NOT_PUBLISHED"
    assert next(row for row in report.filings if row.status == "FAILED").retryable is True
    persisted = json.loads(
        (tmp_path / "reports" / "0001045810" / "trailing_corpus_manifest.json").read_text()
    )
    assert persisted["analysis_reason"] == "COMPLETE_LAYER1_CORPUS_REQUIRED"


def test_retry_reuses_completed_filings_and_attempts_only_previous_failure(tmp_path: Path) -> None:
    ingestor = _Ingestor(tmp_path / "snapshots", fail="0001045810-24-000001")
    corpus = TrailingFilingCorpus(
        provider=_Provider(_rows()),
        resolver=_Resolver(),
        fetcher=_CACHED_FETCHER,
        ingestor=ingestor,
        loader=object(),
        snapshot_root=tmp_path / "snapshots",
        extraction_root=tmp_path / "extract",
    )
    corpus._build_analysis = lambda _: {"period": 0, "annual": 0, "current": 0}  # type: ignore[method-assign]
    first = corpus.run(fiscal_years=3)
    assert first.analysis_status == "NOT_PUBLISHED"
    ingestor.fail = None
    ingestor.calls.clear()
    second = corpus.run(fiscal_years=3)
    assert second.analysis_status == "AVAILABLE"
    assert ingestor.calls == ["0001045810-24-000001"]


def test_existing_snapshot_is_reused_without_resolve_or_network(tmp_path: Path) -> None:
    filing = _rows()[-1]
    destination = tmp_path / "snapshots" / filing.cik / filing.accession.replace("-", "")
    destination.mkdir(parents=True)
    (destination / "layer1_manifest.json").write_text(_manifest(filing).to_json())
    corpus = TrailingFilingCorpus(
        provider=_Provider((filing,)),
        resolver=_Resolver(),
        fetcher=_CACHED_FETCHER,
        ingestor=_Ingestor(tmp_path / "snapshots"),
        loader=object(),
        snapshot_root=tmp_path / "snapshots",
        extraction_root=tmp_path / "extract",
    )
    corpus._build_analysis = lambda _: {"period": 0, "annual": 0, "current": 0}  # type: ignore[method-assign]
    report = corpus.run(fiscal_years=1)
    assert report.filings[0].status == "ALREADY_PUBLISHED"
