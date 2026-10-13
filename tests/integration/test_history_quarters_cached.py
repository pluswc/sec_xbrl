"""Real cached filings prove the default build returns calculated consumer data."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from sec_xbrl.history import (
    HistoryPublicationReader,
    _sha256_file,
    _write_json,
    build_history,
    recover_reported_history,
)


def test_default_history_build_connects_reported_and_derived_consumer(tmp_path: Path, capsys) -> None:
    intake_path = Path("/home/plusbdw/user_work/projects/sec_xbrl/data/processed/history_runs/20260906_five_company/history_intake.json")
    if not intake_path.exists():
        pytest.skip("explicit five-company cached fixture is unavailable")
    original = json.loads(intake_path.read_text())
    items = [item for item in original["filings"] if item["filing"]["cik"] == "0001045810"
             and item["filing"]["report_date"] in {"2024-10-27", "2025-01-26"}]
    assert len(items) == 2
    company = {**next(company for company in original["plan"]["companies"] if company["ticker"] == "NVDA"),
               "filings": [item["filing"] for item in items]}
    intake = {**original, "plan": {**original["plan"], "companies": [company]}, "filings": items}
    fixture = tmp_path / "intake.json"
    _write_json(fixture, intake)
    output = build_history(intake_manifest=fixture, output_root=tmp_path / "default-build")
    assert output.name == "panels"
    reader = HistoryPublicationReader(output)
    reader.verify_all()
    result = reader.load(ticker="NVDA", period_class="QTD_3M")
    q4 = next(column for column in result.columns if column["fiscal_year"] == 2025 and column["fiscal_quarter"] == 4)
    revenue = next(cell for cell in result.cells if cell["fiscal_time_series_column_id"] == q4["fiscal_time_series_column_id"]
                   and cell.get("value_lineage", {}).get("raw_concept_qname") == "us-gaap:Revenues"
                   and not cell["value_lineage"].get("canonical_dimension_signature"))
    assert revenue["value_numeric"] == "39331000000"
    assert revenue["value_status"] == "DERIVED"
    assert revenue["value_lineage"]["source_fact_ids"]
    assert q4["actual_start_date"] == "2024-10-28"
    assert q4["actual_end_date"] == "2025-01-27"
    assert reader.manifest["derived_quarter"]["count"] > 0
    assert build_history(intake_manifest=fixture, output_root=tmp_path / "default-build") == output

    # Expected recovery evidence comes from the completed public fixture run,
    # independently of the copied failed-stage stand-in.
    import polars as pl

    source_log = tmp_path / "source-execution.log"
    source_log.write_text(capsys.readouterr().out)
    reported = output.parent / "reported-panels"
    reported_reader = HistoryPublicationReader(reported)
    manifest = reported_reader.manifest
    expected_tables = []
    for table in manifest["tables"]:
        files = {
            name: {**info, "schema": [[n, str(d)] for n, d in
                    pl.read_parquet_schema(reported / info["path"]).items()]}
            for name, info in table["files"].items()
        }
        expected_tables.append({**table, "files": files})
    failed_stage = tmp_path / ".panels.partial-complete-fixture"
    shutil.copytree(reported, failed_stage)
    source_hashes = {str(p.relative_to(failed_stage)): _sha256_file(p)
                     for p in failed_stage.rglob("*") if p.is_file()}
    report = tmp_path / "fixture-attestation-report.json"
    _write_json(report, {"status": "PASS", "scope": "cached two-filing fixture only"})
    attestation = tmp_path / "recovery-attestation.json"
    _write_json(attestation, {
        "version": "reported-stage-recovery-v1", "status": "PASS",
        "generation_source_identity": "a" * 40, "recovery_source_identity": "b" * 40,
        "staged_manifest_sha256": _sha256_file(reported / "history_manifest.json"),
        "intake_sha256": _sha256_file(fixture), "input_fingerprint": manifest["input_fingerprint"],
        "plan": manifest["plan"], "views": manifest["views"], "tables": expected_tables,
        "operational_manifest_sha256": {
            name: _sha256_file(Path(root) / "layer2_run_manifest.json")
            for name, root in manifest["operational_roots"].items()
        },
        "verification_report": {"path": str(report), "sha256": _sha256_file(report)},
        "source_execution_log": {"path": str(source_log), "sha256": _sha256_file(source_log)},
    })
    proof = json.loads(attestation.read_text())
    proof["required_prefixes"] = []
    verified_files = []
    for table in expected_tables:
        for name in ("columns", "rows", "cells"):
            info = table["files"][name]
            records = reported_reader._records(info)
            digest = hashlib.sha256(json.dumps(records, sort_keys=True, default=str).encode()).hexdigest()
            verified_files.append({**info, "ordered_full_record_sha256": digest})
    _write_json(report, {
        "schema_version": "independent-staged-reported-component-audit-v1",
        "verdict": "PASS_STAGED_REPORTED_COMPONENT_ONLY", "fixture_kind": "CACHED_TEST",
        "verification_level": "FULL_STAGED_REPORTED_PASS", "history_ready": False,
        "source_generation_sha": proof["generation_source_identity"],
        "stage_manifest": {"sha256": proof["staged_manifest_sha256"]},
        "source_intake": {"sha256": proof["intake_sha256"]},
        "input_fingerprint": proof["input_fingerprint"],
        "counts": {"tables": len(expected_tables), "stage_files": len(verified_files)},
        "full_verification": {key: True for key in (
            "all_reported_files_fully_decoded", "all_ordered_records_hashed", "all_json_fields_decoded",
            "all_physical_hashes_verified", "all_schema_counts_verified")},
        "verified_files": verified_files, "prefix_checks": [],
    })
    proof["verification_report"]["sha256"] = _sha256_file(report)
    _write_json(attestation, proof)
    recovered = recover_reported_history(
        staged_publication=failed_stage, output_root=tmp_path / "recovered",
        intake_manifest=fixture, operational_root=output.parent,
        attestation=attestation, expected_attestation_sha256=_sha256_file(attestation),
    )
    recovered_reader = HistoryPublicationReader(recovered)
    assert recovered_reader.manifest["input_fingerprint"] == reader.manifest["input_fingerprint"]
    assert recovered_reader.manifest["operational_roots"] == reader.manifest["operational_roots"]
    assert recovered_reader.manifest["source_manifest_sha256"] == _sha256_file(reported / "history_manifest.json")
    assert recovered_reader.manifest["supersedes_publication"] == str(recovered.parent / "reported-panels")
    for table in reader.manifest["tables"]:
        query = {key: table[key] for key in ("ticker", "view", "period_class")}
        expected, actual = reader.load(**query), recovered_reader.load(**query)
        # Parent publication locations intentionally change; all source values,
        # candidates, dimensions, IDs, flags and ordering must remain identical.
        for cell in expected.cells:
            if cell.get("prior_candidate_publication") is not None:
                cell["prior_candidate_publication"] = str(recovered.parent / "reported-panels")
        assert actual == expected
    assert recovered_reader._records(recovered_reader.manifest["derived_quarter"]) == reader._records(reader.manifest["derived_quarter"])
    assert {str(p.relative_to(failed_stage)): _sha256_file(p)
            for p in failed_stage.rglob("*") if p.is_file()} == source_hashes
    assert {str(p.relative_to(recovered.parent / "reported-panels")): _sha256_file(p)
            for p in (recovered.parent / "reported-panels").rglob("*") if p.is_file()} == source_hashes
    receipt = json.loads((recovered.parent / "reported_recovery_receipt.json").read_text())
    assert receipt["generation_source_identity"] == "a" * 40
    assert receipt["recovery_source_identity"] == "b" * 40
