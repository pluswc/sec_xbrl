from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.longitudinal import (
    CorpusReleaseAdapter,
    CorpusReleaseError,
    Layer2RuleVersions,
    RAW_TABLES,
)


RULES = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")


def _write_corpus(tmp_path: Path, *, amendment: bool = False) -> Path:
    root = tmp_path / "20260827T051322Z"
    cik = "0000320193"
    rows = [
        _write_snapshot(root, cik, "0000320193-25-000001", "10-Q", "2025-05-01", "2025-03-29"),
    ]
    if amendment:
        rows.append(_write_snapshot(root, cik, "0000320193-25-000002", "10-Q/A", "2025-06-01", "2025-03-29"))
    company = {
        "cik": cik,
        "integrity": [row[0] for row in rows],
        "report": {"cik": cik, "analysis_status": "AVAILABLE", "filings": [row[1] for row in rows]},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "run_metadata.json").write_text(json.dumps({"run_id": root.name}), encoding="utf-8")
    (root / "run_summary.json").write_text(json.dumps({"companies": [company]}), encoding="utf-8")
    return root


def _write_snapshot(root: Path, cik: str, accession: str, form: str, filed: str, report: str):
    directory = root / "snapshots" / cik / accession.replace("-", "")
    directory.mkdir(parents=True)
    filing_id = f"filing-{accession[-6:]}"
    records = {
        "filing": [{"filing_id": filing_id, "cik": cik, "accession": accession, "form": form}],
        "concept": [{"filing_id": filing_id, "raw_concept_id": "concept"}],
        "context": [{"filing_id": filing_id, "context_id": "context"}],
        "unit": [{"filing_id": filing_id, "unit_id": "unit"}],
        "fact": [{"filing_id": filing_id, "fact_id": "fact", "raw_concept_id": "concept"}],
        "dimension_fact": [],
        "role": [{"filing_id": filing_id, "role_id": "role"}],
        "relationship": [{"filing_id": filing_id, "relationship_id": "rel"}],
    }
    for name, values in records.items():
        pl.DataFrame(values).write_parquet(directory / f"{name}.parquet")
    manifest = {
        "schema_version": 1, "cik": cik, "accession": accession, "form": form,
        "source_url": "cached://fixture", "package_sha256": "a", "fact_corpus_source": "fixture",
        "source_fact_count": 1, "materialized_fact_count": 1, "concept_count": 1,
        "context_count": 1, "unit_count": 1, "dimension_fact_count": 0,
        "role_count": 1, "relationship_count": 1, "layer1_parser_version": "fixture-v1",
        "relationship_parser_version": "fixture-v1",
    }
    (directory / "layer1_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    integrity = {
        "accession": accession, "status": "PUBLISHED", "counts_match": True,
        "missing_tables": [], "required_table_count": len(RAW_TABLES),
        "source_fact_count": 1, "materialized_fact_count": 1,
    }
    filing = {"accession": accession, "form": form, "filed_date": filed, "report_date": report, "status": "PUBLISHED"}
    return integrity, filing


def _release(root: Path):
    return CorpusReleaseAdapter().load(
        root, corpus_run_id=root.name, ciks=("320193",), run_version="c3-fixture-v1", rules=RULES
    )


def test_release_preserves_all_raw_tables_and_deterministic_layer2_declaration(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    release = _release(root)
    repeated = _release(root)
    assert release.layer2_run.fingerprint == repeated.layer2_run.fingerprint
    assert tuple(release.snapshots[0].tables) == RAW_TABLES
    assert release.records("unit") == ({"filing_id": "filing-000001", "unit_id": "unit"},)
    assert release.layer2_run.inputs[0].manifest_sha256 == hashlib.sha256(
        release.snapshots[0].manifest_path.read_bytes()
    ).hexdigest()
    copy = release.snapshot_records(release.layer2_run.inputs[0].snapshot_id, "fact")
    copy[0]["fact_id"] = "changed"
    assert release.snapshot_records(release.layer2_run.inputs[0].snapshot_id, "fact")[0]["fact_id"] == "fact"


def test_release_preserves_amendment_as_distinct_snapshot(tmp_path: Path) -> None:
    release = _release(_write_corpus(tmp_path, amendment=True))
    assert [item.form for item in release.layer2_run.inputs] == ["10-Q", "10-Q/A"]
    assert len({item.accession for item in release.layer2_run.inputs}) == 2


@pytest.mark.parametrize("mutation", ["missing", "extra", "bad_manifest", "foreign_filing", "count", "failed", "wrong_scope"])
def test_release_fails_closed_for_invalid_corpus(tmp_path: Path, mutation: str) -> None:
    root = _write_corpus(tmp_path)
    snapshot = next((root / "snapshots").glob("*/*"))
    summary_path = root / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    if mutation == "missing":
        (snapshot / "unit.parquet").unlink()
    elif mutation == "extra":
        (snapshot / "extra.txt").write_text("not atomic")
    elif mutation == "bad_manifest":
        payload = json.loads((snapshot / "layer1_manifest.json").read_text())
        payload["accession"] = "0000320193-99-999999"
        (snapshot / "layer1_manifest.json").write_text(json.dumps(payload))
    elif mutation == "foreign_filing":
        pl.DataFrame([{"filing_id": "foreign", "unit_id": "unit"}]).write_parquet(snapshot / "unit.parquet")
    elif mutation == "count":
        pl.DataFrame([
            {"filing_id": "filing-000001", "fact_id": "fact", "raw_concept_id": "concept"},
            {"filing_id": "filing-000001", "fact_id": "fact2", "raw_concept_id": "concept"},
        ]).write_parquet(snapshot / "fact.parquet")
    elif mutation == "failed":
        summary["companies"][0]["integrity"][0]["status"] = "FAILED"
        summary_path.write_text(json.dumps(summary))
    elif mutation == "wrong_scope":
        summary["companies"][0]["cik"] = "0000000001"
        summary_path.write_text(json.dumps(summary))
    with pytest.raises(CorpusReleaseError):
        _release(root)


def test_release_rejects_missing_requested_cik_and_never_uses_latest_path(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    with pytest.raises(CorpusReleaseError):
        CorpusReleaseAdapter().load(root, corpus_run_id="different", ciks=("320193",), run_version="v", rules=RULES)
    with pytest.raises(CorpusReleaseError):
        CorpusReleaseAdapter().load(root, corpus_run_id=root.name, ciks=("1045810",), run_version="v", rules=RULES)


def test_actual_seven_company_corpus_is_admitted_when_cached() -> None:
    root = Path(
        os.environ.get(
            "SEC_XBRL_CORPUS_ROOT",
            "data/processed/trailing_corpus_runs/20260827T051322Z",
        )
    )
    if not root.is_dir():
        pytest.skip("cached seven-company corpus is not available")
    release = CorpusReleaseAdapter().load(
        root,
        corpus_run_id="20260827T051322Z",
        ciks=("320193", "1045810", "1318605", "2488", "1652044", "1326801", "1065280"),
        run_version="c3-golden-v1",
        rules=RULES,
    )
    assert len(release.snapshots) == 102
    assert set(release.ciks) == {"0000320193", "0001045810", "0001318605", "0000002488", "0001652044", "0001326801", "0001065280"}
