from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl import history
from sec_xbrl.analytics import FiscalTimeSeriesQuery
from sec_xbrl.filing.contracts import FilingRef


def test_report_window_and_as_of_are_independent() -> None:
    original = FilingRef("0000000001", "0000000001-24-000001", "10-Q", date(2024, 5, 1), date(2024, 3, 31))
    amendment = FilingRef("0000000001", "0000000001-24-000002", "10-Q/A", date(2024, 6, 1), date(2024, 3, 31))
    args = {"report_start": date(2024, 1, 1), "report_end": date(2024, 3, 31)}
    assert history.select_history_filings((original, amendment), as_of=date(2024, 5, 31), **args) == (original,)
    assert history.select_history_filings((original, amendment), as_of=date(2024, 6, 1), **args) == (original, amendment)
    with pytest.raises(ValueError, match="exclusively"):
        history.select_history_filings((original,), as_of=date(2024, 6, 1), recent_fiscal_years=3, **args)
    with pytest.raises(ValueError, match="exclusively"):
        history.select_history_filings((original,), as_of=date(2024, 6, 1), recent_fiscal_years=3, report_start=date(2024, 1, 1))


def test_expected_quarters_do_not_fabricate_future_history() -> None:
    keys = [("1", 2024, None, "FY"), ("1", 2024, 3, "YTD_9M"), ("1", 2025, 2, "QTD_3M")]
    periods = history._expected_quarters(keys)
    assert [(p.fiscal_year, p.fiscal_quarter) for p in periods] == [(2024, 1), (2024, 2), (2024, 3), (2024, 4), (2025, 1), (2025, 2)]


def test_incomplete_intake_cannot_be_published() -> None:
    with pytest.raises(ValueError, match="all planned"):
        history._validate_intake({"plan": {"companies": [{"cik": "1", "filings": [{"accession": "a"}]}]}, "filings": [], "complete": False})


def test_parquet_publication_reload_retains_nested_lineage_and_detects_corruption(tmp_path: Path) -> None:
    records = {"columns": ({"fiscal_time_series_column_id": "c", "column_status": "UNAVAILABLE", "column_reason": "DERIVATION_NOT_MATERIALIZED"},),
               "rows": ({"fiscal_time_series_row_id": "r", "evidence": {"sources": ["raw-fact"]}},), "cells": ()}
    files = {}
    for name, rows in records.items():
        path = tmp_path / f"{name}.parquet"
        files[name] = {**history._write_records(path, rows), "path": path.name}
    history._write_json(tmp_path / "history_manifest.json", {"version": history.HISTORY_VERSION, "tables": [{"ticker": "TEST", "period_class": "QTD_3M", "view": "LATEST_REPORTED", "scope": {}, "files": files}]})
    reader = history.HistoryPublicationReader(tmp_path)
    reader.verify_all()
    result = reader.load(ticker="test")
    assert result.rows[0]["evidence"] == {"sources": ["raw-fact"]}
    assert FiscalTimeSeriesQuery(result).matrix()[0]["cells"][0]["value_status"] == "UNAVAILABLE"
    (tmp_path / "rows.parquet").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="integrity"):
        reader.load(ticker="TEST")


def test_intake_bootstrap_is_after_offline_failure_with_unique_paths_and_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = FilingRef("0000000001", "0000000001-24-000001", "10-Q", date(2024, 5, 1), date(2024, 3, 31))
    plan = {"companies": [{"ticker": "TEST", "cik": ref.cik, "filings": [history._ref_record(ref)]}]}
    plan_path = tmp_path / "plan.json"
    history._write_json(plan_path, plan)
    output = tmp_path / "output"
    history._write_json(output / "history_intake.json", {"plan": plan, "complete": False, "filings": [{"old": "failure"}]})
    events = []
    class Loader:
        def __init__(self, **kwargs):
            pass

        @staticmethod
        def bootstrap_taxonomy_cache(resolved, destination, taxonomy_cache):
            events.append(("bootstrap", destination))
            return SimpleNamespace(close=lambda: events.append(("close", None)))

    class Ingestor:
        def __init__(self, root):
            pass

        def load_and_ingest(self, resolved, loader, destination):
            events.append(("offline", destination))
            if len(events) == 1:
                raise ValueError("missing taxonomy")

        def _validate_model(self, model):
            pass

        def snapshot_dir(self, resolved):
            return tmp_path

    monkeypatch.setenv("SEC_USER_AGENT", "unit-test-only")
    monkeypatch.setattr(history, "ArelleFilingLoader", Loader)
    monkeypatch.setattr(history, "Layer1Ingestor", Ingestor)
    monkeypatch.setattr(history, "FilingPackageResolver", lambda *args: SimpleNamespace(resolve=lambda *args: object()))
    monkeypatch.setattr(history, "_load_declared_cohort_snapshot", lambda *args: SimpleNamespace(records=lambda name: (history._ref_record(ref),)))
    path = history.ingest_history(plan_path=plan_path, source_runs=(), output_run=output,
                                 package_cache=tmp_path / "packages", index_cache=tmp_path / "index",
                                 taxonomy_cache=tmp_path / "taxonomy", bootstrap_taxonomy=True)
    assert json.loads(path.read_text())["complete"] is True
    assert [event[0] for event in events] == ["offline", "bootstrap", "close", "offline"]
    assert len({event[1] for event in events if event[1] is not None}) == 3
    audit = list((output / "history_attempts").glob("manifest-*.json"))
    assert json.loads(audit[0].read_text())["filings"] == [{"old": "failure"}]


def test_snapshot_metadata_must_match_plan() -> None:
    original = {"cik": "1", "accession": "a", "form": "10-Q", "filed_date": "2024-05-01", "report_date": "2024-03-31"}
    snapshot = SimpleNamespace(records=lambda name: (original,))
    history._validate_snapshot_plan(snapshot, original)
    with pytest.raises(ValueError, match="metadata"):
        history._validate_snapshot_plan(snapshot, {**original, "filed_date": "2024-04-01"})


def test_offline_arbitrary_ticker_discovery_reuses_immutable_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"cik": "1234", "tickers": ["EXAMPLE"], "name": "Offline Fixture Company", "filings": {"recent": {
        "accessionNumber": ["0000001234-24-000001"], "form": ["10-Q"],
        "filingDate": ["2024-05-01"], "reportDate": ["2024-03-31"],
        "primaryDocument": ["example.htm"], "isXBRL": [1], "isInlineXBRL": [1],
    }}}
    submissions = tmp_path / "submissions"
    history._write_json(submissions / "example.json", payload)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    kwargs = {"workspace": tmp_path / "workspace", "tickers": ("example",),
              "as_of": date(2024, 6, 1), "submissions_roots": (submissions,), "offline": True,
              "report_start": date(2024, 1, 1), "report_end": date(2024, 3, 31)}
    path = history.discover_history(**kwargs)
    before = path.read_bytes()
    assert json.loads(before)["companies"][0]["cik"] == "0000001234"
    assert json.loads(before)["companies"][0]["ticker"] == "EXAMPLE"
    assert history.discover_history(**kwargs).read_bytes() == before
    with pytest.raises(ValueError, match="different scope"):
        history.discover_history(**{**kwargs, "as_of": date(2024, 7, 1)})
    assert path.read_bytes() == before


def test_coverage_annual_completion_requires_annual_filing_focus() -> None:
    filings = ({"cik": "1", "form": "10-K", "document_fiscal_year_focus": "2025", "document_fiscal_period_focus": "FY"},
               {"cik": "1", "form": "10-Q", "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "Q2"},
               {"cik": "1", "form": "10-Q", "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "FY"})
    keys = history._filing_coverage_keys(filings, "1")
    assert [(p.fiscal_year, p.fiscal_quarter) for p in history._expected_quarters(keys)] == [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2)]


def test_coverage_repair_preserves_real_cells_and_rejects_plan_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "panels"
    record = {"cik": "1", "accession": "a", "form": "10-Q", "filed_date": "2026-08-01", "report_date": "2026-06-30"}
    plan = {"companies": [{"cik": "1", "filings": [record]}]}
    intake_path = tmp_path / "intake.json"
    history._write_json(intake_path, {"complete": True, "plan": plan, "filings": [{"filing": record, "source_run": str(tmp_path), "status": "REUSED"}]})
    columns = tuple({"fiscal_time_series_column_id": f"q{q}", "fiscal_year": 2026, "fiscal_quarter": q,
                     "column_status": "AVAILABLE" if q == 2 else "MISSING_HISTORY"} for q in (2, 3, 4))
    cells = ({"fiscal_time_series_column_id": "q2", "fiscal_time_series_row_id": "r", "value_numeric": "100"},)
    files = {}
    for name, rows in {"columns": columns, "cells": cells, "rows": ({"fiscal_time_series_row_id": "r"},)}.items():
        files[name] = {**history._write_records(root / f"{name}.parquet", rows), "path": f"{name}.parquet"}
    history._write_json(root / "history_manifest.json", {"version": history.HISTORY_VERSION, "plan": plan,
                        "source_intake": str(intake_path), "tables": [{"ticker": "TEST", "cik": "1", "view": "LATEST_REPORTED", "period_class": "QTD_3M", "scope": {}, "files": files}]})
    monkeypatch.setattr(history, "_load_declared_cohort_snapshot", lambda *args: SimpleNamespace(records=lambda name: ({**record, "document_fiscal_year_focus": "2026", "document_fiscal_period_focus": "Q2"},)))
    destination = history.repair_history_coverage(publication=root, destination=tmp_path / "repaired")
    repaired = history.HistoryPublicationReader(destination)
    assert repaired.load(ticker="TEST").cells == cells
    assert len(repaired.load(ticker="TEST").columns) == 1
    assert len(history.HistoryPublicationReader(root).load(ticker="TEST").columns) == 3
    assert repaired.manifest["source_manifest_sha256"]
    wrong = json.loads(intake_path.read_text())
    wrong["plan"]["extra"] = "tamper"
    history._write_json(intake_path, wrong)
    with pytest.raises(ValueError, match="disagrees"):
        history.repair_history_coverage(publication=root, destination=tmp_path / "rejected")
