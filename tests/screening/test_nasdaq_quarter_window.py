"""Only the explicit-quarter correction boundary; no company rebuilds."""
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from tools import nasdaq100_quarter_window as worker


def test_current_quarter_year_is_not_annual_inference():
    columns = [{"period_class": "QTD_3M", "fiscal_year": year, "column_status": "AVAILABLE"}
               for year in range(2021, 2027)]
    assert worker.quarter_bounds(columns) == (2022, 2026)
    columns.append({"period_class": "FY", "fiscal_year": 2030, "column_status": "AVAILABLE"})
    assert worker.quarter_bounds(columns) == (2022, 2026)
    with pytest.raises(ValueError, match="nonconsecutive"):
        worker.quarter_bounds([columns[0], columns[2]])


def test_pin_tamper_and_relative_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text("{}")
    pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert worker.pin_file(pin) == path
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="changed"):
        worker.pin_file(pin)
    with pytest.raises(ValueError, match="absolute"):
        worker.pin_file({"path": "relative", "sha256": "x"})


def test_public_worker_explicit_args_and_no_overwrite(tmp_path, monkeypatch):
    from sec_xbrl import analysis
    from tools import universe50_t3v2_ops as resources

    def pinned(path, value):
        path.write_text(json.dumps(value))
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(analysis, "__file__", str(source / "src/sec_xbrl/analysis.py"))
    monkeypatch.setattr(worker.subprocess, "check_output", lambda argv, **_: worker.SOURCE_COMMIT + "\n" if argv[1] == "rev-parse" else "")
    monkeypatch.setattr(resources, "install_parent_death_guard", lambda: None)
    headers = tmp_path / "columns.parquet"
    pl.DataFrame({"period_class": ["QTD_3M"] * 6, "fiscal_year": list(range(2021, 2027)),
                  "column_status": ["AVAILABLE"] * 6}).write_parquet(headers)
    history = pinned(tmp_path / "history_manifest.json", {"tables": [{
        "ticker": "TEST", "cik": "0000000001", "period_class": "QTD_3M", "view": "LATEST_REPORTED",
        "scope": {"selection_as_of_date": "2026-10-25"},
        "files": {"columns": {"path": headers.name, "sha256": hashlib.sha256(headers.read_bytes()).hexdigest()}}}]})
    parent = {"companies": {"TEST": {"source_publication": str(tmp_path), "as_of": "2026-10-25"}},
              "source_manifest_hashes": {"history_manifest_sha256": history["sha256"]}}
    annual = pinned(tmp_path / "annual.json", parent)
    quarter = pinned(tmp_path / "quarter.json", parent)
    destination = tmp_path / "new-quarter"
    plan = pinned(tmp_path / "plan.json", {"schema_version": worker.VERSION, "source_root": str(source),
        "source_commit": worker.SOURCE_COMMIT, "companies": [{"ticker": "TEST", "cik": "0000000001",
        "history_manifest": history, "annual_manifest": annual, "quarterly_manifest": quarter,
        "destination": str(destination), "fiscal_start": 2022, "fiscal_end": 2026}]})
    calls = []

    def prepare(**kwargs):
        calls.append(kwargs)
        destination.mkdir()
        (destination / "analysis_manifest.json").write_text('{}')

    monkeypatch.setattr(analysis, "prepare_analysis", prepare)
    result = tmp_path / "result.json"
    assert worker.prepare_company(Path(plan["path"]), plan["sha256"], "TEST", result)["status"] == "PASS"
    assert calls[0] == {"publication": tmp_path, "destination": destination, "tickers": ("TEST",), "fiscal_years": 5,
        "fiscal_start": 2022, "fiscal_end": 2026, "configuration": None, "period_mode": "QUARTERLY",
        "include_year_end_balances": False, "include_quarter_source_evidence": True}
    with pytest.raises(ValueError, match="never overwrite"):
        worker.prepare_company(Path(plan["path"]), plan["sha256"], "TEST", result)
    assert len(calls) == 1
