from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl.screening.common import sha256_file
from tools import nasdaq100_ops as ops


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return {"path": str(path), "sha256": sha256_file(path)}


def _config(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "PROJECT", tmp_path)
    identity = _write(tmp_path / "identity.json", {"securities": [
        {"ticker": "NEW", "cik": "0000000001", "status": "SUPPORTED_K_Q"},
        {"ticker": "HELD", "cik": "0000000002", "status": "HOLD_UNSUPPORTED_FORMS"},
    ]})
    universe = _write(tmp_path / "universe.json", {
        "schema_version": 1, "universe_id": "new", "purpose": "synthetic test", "as_of_date": "2026-10-25",
        "collection": {"completed_fiscal_years": 5, "analytical_fiscal_years": 4, "include_subsequent_quarters": True},
        "companies": [{"ticker": "NEW", "cik": "0000000001"}],
    })
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    value = {
        "schema_version": ops.VERSION, "operator_sha256": sha256_file(Path(ops.__file__)),
        "identity": identity, "universe_config": universe,
        "run_root": str(tmp_path / "data/raw/nasdaq100_20261111/collection"),
        "work_root": str(tmp_path / "work/nasdaq100-expansion-20261111/ops"),
        "history_root": str(tmp_path / "data/processed/nasdaq100_20261111/history"),
        "analysis_root": str(tmp_path / "data/processed/nasdaq100_20261111/analysis"),
        "submissions_roots": [str(submissions)],
        "package_cache": str(tmp_path / "data/raw/nasdaq100_20261111/packages"),
        "index_cache": str(tmp_path / "data/raw/nasdaq100_20261111/indexes"),
        "taxonomy_cache": str(tmp_path / "taxonomy"),
        "companies": [{"ticker": "NEW", "cik": "0000000001", "source_runs": []}],
        "collection_manifest": _write(tmp_path / "data/raw/nasdaq100_20261111/collection/collection_manifest.json", {"pinned": True}),
    }
    path = tmp_path / "ops.json"
    _write(path, value)
    return path, value


def test_pinned_scope_rejects_wrong_identity_cutoff_or_original_mutation(tmp_path, monkeypatch):
    path, config = _config(tmp_path, monkeypatch)
    assert ops.load_config(path, sha256_file(path)) == config
    wrong = {**config, "run_root": str(tmp_path / "data/raw/old50/collection")}
    _write(path, wrong)
    with pytest.raises(ValueError, match="authorized expansion scope"):
        ops.load_config(path, sha256_file(path))
    _write(path, config)
    with pytest.raises(ValueError, match="differs from pin"):
        ops.load_config(path, "f" * 64)
    config["companies"][0].update(ticker="HELD", cik="0000000002")
    _write(path, config)
    with pytest.raises(ValueError, match="not confirmed"):
        ops.load_config(path, sha256_file(path))


def test_completion_resumes_only_same_pinned_output_and_blocks_missing_parent(tmp_path, monkeypatch):
    path, config = _config(tmp_path, monkeypatch)
    expected = sha256_file(path)
    output = tmp_path / "accepted.json"
    output_pin = _write(output, {"immutable": True})
    receipt = ops._completion(config, "NEW", "collect")
    _write(receipt, {"status": "PASS", "identity": ops._identity(path, expected, "NEW", "collect"),
                     "outputs": [output_pin]})
    assert ops.run_stage(path, expected, "NEW", "collect") == receipt
    with pytest.raises(ValueError, match="not a regular file"):
        ops.run_stage(path, expected, "NEW", "annual")
    output.write_text("changed")
    with pytest.raises(ValueError, match="differs from pin"):
        ops.run_stage(path, expected, "NEW", "collect")


def test_cleanup_only_accepted_new_intake_scratch_and_preserves_raw(tmp_path):
    intake = tmp_path / "run/companies/NEW/intake"
    accession = "0000000001-26-000001"
    accepted = intake / "extracted/0000000001" / accession.replace("-", "")
    accepted.mkdir(parents=True)
    (accepted / "temporary.htm").write_text("scratch")
    failed = intake / "extracted/0000000001/000000000126000002"
    failed.mkdir()
    (failed / "failed.htm").write_text("retain diagnostic")
    manifest = intake / "snapshots/0000000001" / accession.replace("-", "") / "layer1_manifest.json"
    _write(manifest, {"accepted": True})
    before = manifest.read_bytes()
    _write(intake / "history_intake.json", {"filings": [
        {"status": "INGESTED", "source_run": str(intake), "filing": {"cik": "0000000001", "accession": accession}},
        {"status": "FAILED", "filing": {"cik": "0000000001", "accession": "0000000001-26-000002"}},
    ]})
    result = ops._accepted_scratch({"run_root": str(tmp_path / "run")}, "NEW")
    assert len(result["removed"]) == 1 and not accepted.exists() and failed.exists()
    assert manifest.read_bytes() == before
    assert ops._accepted_scratch({"run_root": str(tmp_path / "run")}, "NEW")["removed"] == []


def test_default_quarter_uses_current_qtd_year_without_changing_annual_scope(tmp_path, monkeypatch):
    import polars as pl

    path, config = _config(tmp_path, monkeypatch)
    company_root = Path(config["run_root"]) / "companies/NEW"
    history = tmp_path / "prepared-history"
    history.mkdir()
    headers = history / "columns.parquet"
    pl.DataFrame({"fiscal_year": list(range(2021, 2027)), "period_class": ["QTD_3M"] * 6,
                  "column_status": ["AVAILABLE"] * 6}).write_parquet(headers)
    history_pin = _write(history / "history_manifest.json", {"tables": [{
        "ticker": "NEW", "cik": "0000000001", "period_class": "QTD_3M", "view": "LATEST_REPORTED",
        "files": {"columns": {"path": headers.name, "sha256": sha256_file(headers)}}}]})
    _write(company_root / "build_manifest.json", {"publication": str(history),
        "history_manifest": history_pin["path"], "history_manifest_sha256": history_pin["sha256"]})
    _write(company_root / "plan.json", {"companies": [{"filings": [{"form": "10-K"}]}]})
    calls = []
    monkeypatch.setattr(ops.analysis, "prepare_analysis", lambda **kwargs: calls.append(kwargs))
    ops._work(config, "NEW", "quarterly")
    ops._work(config, "NEW", "annual")
    quarterly, annual = calls
    assert (quarterly["fiscal_start"], quarterly["fiscal_end"]) == (2022, 2026)
    assert quarterly["configuration"] is None and quarterly["include_quarter_source_evidence"] is True
    assert "fiscal_start" not in annual and "fiscal_end" not in annual
    assert annual["fiscal_years"] == 5 and annual["configuration"] is not None
    assert annual["period_mode"] == "ANNUAL" and annual["include_year_end_balances"] is True
    headers.write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs from pin"):
        ops._work(config, "NEW", "quarterly")
    assert len(calls) == 2
