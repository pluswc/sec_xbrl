from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from sec_xbrl.screening import dataset as dataset_module
from sec_xbrl.screening.common import digest_value, sha256_file, write_json
from sec_xbrl.screening.dataset import (
    COMPANIES,
    MANIFEST,
    OBSERVATIONS,
    ScreeningDatasetReader,
    _observation,
    _verify_analysis_files,
)
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore, backup_store, restore_store


def _service(dataset: Path, tmp_path: Path) -> ScreeningService:
    return ScreeningService({"fixture": dataset}, ScreeningStore(tmp_path / "journal.sqlite"))


def test_executor_preserves_every_target_unknown_and_original_quality(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    revision = service.create_screen("FY2025 예시", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    assert run["counts"] == {"target": 3, "pass": 1, "fail": 1, "undetermined": 1, "quality_block": 0}
    assert [(row["ticker"], row["aggregate"]) for row in run["rows"]] == [
        ("ONE", "PASS"), ("THREE", "UNDETERMINED"), ("TWO", "FAIL")
    ]
    unknown = next(row for row in run["rows"] if row["ticker"] == "THREE")
    assert unknown["predicates"][0]["reason"] == "MULTIPLE_CANDIDATES"
    assert unknown["predicates"][0]["observation"]["value"] is None
    warning = next(row for row in run["rows"] if row["ticker"] == "TWO")
    assert warning["predicates"][0]["observation"]["quality_status"] == "WARN"
    assert warning["quality_blocking"] is False
    assert service.store.run(run["run_id"])["output_hash"] == run["output_hash"]


def test_unknown_and_unsupported_metrics_fail_closed(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    for metric in ("not_a_metric", "revenue_growth"):
        invalid = json.loads(json.dumps(revision_content))
        invalid["predicates"] = [{"metric_id": metric, "operator": "GTE", "threshold": "0",
                                  "definition_version": "annual-core-reported-v1"}]
        revision = service.create_screen(metric, invalid)
        with pytest.raises(ValueError, match="unknown|unavailable"):
            service.execute(revision["revision_id"], "fixture")
    invalid_number = json.loads(json.dumps(revision_content))
    invalid_number["predicates"][0]["threshold"] = "NaN"
    with pytest.raises(ValueError, match="finite"):
        service.create_screen("bad", invalid_number)


def test_sic_universe_metadata_unknown_trace_and_peer_dates(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    narrowed = json.loads(json.dumps(revision_content))
    narrowed["universe"] = {"mode": "SIC", "sic_codes": ["3674"]}
    revision = service.create_screen("반도체", narrowed)
    run = service.execute(revision["revision_id"], "fixture")
    assert [row["cik"] for row in run["rows"]] == ["0000000001", "0000000002"]
    inventory = service.metadata_inventory("fixture", prepared=False)
    assert inventory["total"] == 1 and inventory["rows"][0]["sic_status"] == "UNKNOWN_SIC"
    peers = service.peer_candidates("fixture", cik="0000000001")
    assert [row["cik"] for row in peers["peers"]] == ["0000000002"]
    trace = service.trace(run["run_id"], cik="0000000001", metric_id="revenue")
    assert trace["trace"]["value_lineage"]["source_filing_id"] == "0000000001-25-000001"
    comparison = service.compare_peers(
        "fixture", ciks=["0000000001", "0000000002"], metric_id="revenue", fiscal_year=2025
    )
    assert all(row["observation"]["context_end_convention"] == "SOURCE_CONTEXT_END_EXCLUSIVE" for row in comparison["rows"])


def test_append_only_decisions_restart_backup_and_blank_restore(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    revision = service.create_screen("영속 조건", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    first = service.add_decision(cik="0000000001", state="INTEREST", rationale="원천 확인",
                                 run_id=run["run_id"], actor="tester", evidence_ids=["fact-1"])
    second = service.add_decision(cik="0000000001", state="HOLD", rationale="추가 검토",
                                  run_id=run["run_id"], actor="tester", evidence_ids=["fact-2"])
    assert second["previous_event_id"] == first["event_id"]
    assert second["before_state"] == "INTEREST"
    restarted = _service(screening_dataset, tmp_path)
    assert restarted.store.revision(revision["revision_id"])["content"] == revision_content
    assert [event["state"] for event in restarted.decisions("0000000001")] == ["INTEREST", "HOLD"]
    backup = backup_store(tmp_path / "journal.sqlite", tmp_path / "backup")
    restored_path = restore_store(backup, tmp_path / "restored.sqlite")
    restored = ScreeningStore(restored_path)
    assert restored.run(run["run_id"])["output_hash"] == run["output_hash"]
    assert len(restored.decisions("0000000001")) == 2
    with pytest.raises(ValueError, match="new destination"):
        restore_store(backup, restored_path)


def test_run_comparison_separates_revision_from_universe_membership(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    first_revision = service.create_screen("비교", revision_content)
    first = service.execute(first_revision["revision_id"], "fixture")
    second_revision = service.revise_screen(first_revision["screen_id"], revision_content)
    second = service.execute(second_revision["revision_id"], "fixture")
    comparison = service.compare_runs(first["run_id"], second["run_id"])
    assert comparison["changed_dimensions"]["condition_revision"] is True
    assert comparison["changed_dimensions"]["universe"] is False
    assert comparison["changed_dimensions"]["universe_selector"] is False
    assert comparison["universe_membership"]["old_ciks"] == comparison[
        "universe_membership"
    ]["new_ciks"]
    assert second["versions"]["predicate_definition_versions"] == [
        "annual-core-reported-v1"
    ]


def test_full_and_selected_csv_xlsx_equal_frozen_run(
    screening_dataset: Path, revision_content: dict, tmp_path: Path
) -> None:
    service = _service(screening_dataset, tmp_path)
    revision = service.create_screen("내보내기", revision_content)
    run = service.execute(revision["revision_id"], "fixture")
    outputs = {}
    for scope, selected in (("FULL", None), ("SELECTED", ["0000000001"])):
        for extension in ("csv", "xlsx"):
            destination = tmp_path / f"{scope.lower()}.{extension}"
            outputs[(scope, extension)] = service.export_run(
                run["run_id"], destination, scope=scope, selected_ciks=selected
            )
    full_rows = list(csv.DictReader((tmp_path / "full.csv").open(encoding="utf-8-sig")))
    assert [json.loads(row["record_json"])["cik"] for row in full_rows if row["record_type"] == "ROW"] == [row["cik"] for row in run["rows"]]
    selected_rows = list(csv.DictReader((tmp_path / "selected.csv").open(encoding="utf-8-sig")))
    assert [row["cik"] for row in selected_rows if row["record_type"] == "ROW"] == ["0000000001"]
    for scope, expected in (("full", 3), ("selected", 1)):
        workbook = load_workbook(tmp_path / f"{scope}.xlsx", data_only=False)
        assert workbook.sheetnames == ["Rows", "Metadata"]
        assert workbook["Rows"].max_row == expected + 1
        assert all(cell.data_type != "f" for sheet in workbook for row in sheet.iter_rows() for cell in row)
    assert all(result["canonical_payload_hash"] for result in outputs.values())


def test_dataset_reader_rejects_rehashed_record_count_or_payload_tamper(
    screening_dataset: Path,
) -> None:
    reader = ScreeningDatasetReader(screening_dataset)
    assert reader.verify_all()["counts"]["metadata_candidates"] == 4
    path = screening_dataset / "metric_observations.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        ScreeningDatasetReader(screening_dataset)


def test_actual_dataset_cannot_omit_governed_source_anchors(screening_dataset: Path) -> None:
    path = screening_dataset / MANIFEST
    manifest = json.loads(path.read_text())
    manifest["fixture_kind"] = "ACTUAL_PREPARED"
    manifest["fixture_policy"] = None
    identity = {key: value for key, value in manifest.items() if key != "publication_id"}
    manifest["publication_id"] = "screening-dataset-" + digest_value(identity)[:24]
    write_json(path, manifest)
    with pytest.raises(ValueError, match="source anchors"):
        ScreeningDatasetReader(screening_dataset)


def test_analysis_parent_bytes_must_match_declared_hash(tmp_path: Path) -> None:
    root = tmp_path / "analysis"
    root.mkdir()
    data = root / "core.parquet"
    data.write_bytes(b"governed prepared bytes")
    manifest = {
        "companies": {
            "ONE": {
                "views": {
                    "LATEST_REPORTED": {
                        "files": {
                            "core": {"path": "core.parquet", "sha256": sha256_file(data)}
                        }
                    }
                }
            }
        }
    }
    _verify_analysis_files(root, manifest)
    data.write_bytes(b"changed while manifest stayed unchanged")
    with pytest.raises(ValueError, match="analysis data integrity mismatch"):
        _verify_analysis_files(root, manifest)


def test_coordinated_embedded_rehash_cannot_replace_prepared_source_value(
    screening_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Self-consistent copied JSON still has to equal the independent prepared parent."""
    publication = tmp_path / "actual"
    shutil.copytree(screening_dataset, publication)
    companies = json.loads((publication / COMPANIES).read_text())
    original_snapshots = {}
    for company in companies:
        path = publication / "source_snapshots" / company["cik"] / (
            company["source_snapshot_id"] + ".json"
        )
        original_snapshots[company["ticker"]] = json.loads(path.read_text())

    config_path = tmp_path / "config.json"
    completion_root = tmp_path / "completion"
    metadata_root = tmp_path / "metadata"
    completion_root.mkdir()
    metadata_root.mkdir()
    write_json(completion_root / "universe_delivery_manifest.json", {"fixture": True})
    write_json(metadata_root / "company_metadata_manifest.json", {"fixture": True})
    analysis_sources = []
    config_companies = []
    fake_clients = {}
    for company in companies:
        analysis_root = tmp_path / f"analysis-{company['ticker']}"
        history_root = tmp_path / f"history-{company['ticker']}"
        analysis_root.mkdir()
        history_root.mkdir()
        history = history_root / "history_manifest.json"
        write_json(history, {"ticker": company["ticker"]})
        analysis_manifest = {
            "publication_id": company["analysis_publication_id"],
            "period_mode": "ANNUAL",
            "companies": {
                company["ticker"]: {
                    "as_of": "2026-10-08",
                    "source_publication": str(history_root),
                    "views": {},
                }
            },
            "source_manifest_hashes": {"history_manifest_sha256": sha256_file(history)},
        }
        write_json(analysis_root / "analysis_manifest.json", analysis_manifest)
        fake_clients[str(analysis_root.resolve())] = SimpleNamespace(
            manifest=analysis_manifest,
            overview_snapshot=lambda *args, _snapshot=original_snapshots[company["ticker"]], **kwargs: _snapshot,
        )
        config_companies.append(
            {"ticker": company["ticker"], "cik": company["cik"], "analysis_root": str(analysis_root)}
        )
        analysis_sources.append(
            {
                "ticker": company["ticker"],
                "cik": company["cik"],
                "root": str(analysis_root.resolve()),
                "manifest_sha256": sha256_file(analysis_root / "analysis_manifest.json"),
                "publication_id": company["analysis_publication_id"],
                "source_publication": str(history_root),
                "history_manifest_sha256": sha256_file(history),
            }
        )
    config = {
        "schema_version": "screening-prepare-config-v1",
        "dataset_id": "fixture",
        "fixture_kind": "ACTUAL_PREPARED",
        "financial_as_of": "2026-10-08",
        "completion_root": str(completion_root),
        "metadata_root": str(metadata_root),
        "companies": config_companies,
    }
    write_json(config_path, config)
    metadata_rows = json.loads((publication / "metadata_inventory.json").read_text())
    candidates = [
        SimpleNamespace(
            cik=row["cik"],
            name=row["name"],
            tickers=tuple(row["tickers"]),
            exchanges=tuple(row["exchanges"]),
            sic_code=row["sic_code"],
            sic_description=row["sic_description"],
            metadata_status=row["metadata_status"],
            observed_at=row["observed_at"],
        )
        for row in metadata_rows
    ]
    completion_rows = [
        {"cik": company["cik"], "ticker": company["ticker"]} for company in companies
    ]
    monkeypatch.setattr(
        dataset_module,
        "UniverseDeliveryReader",
        lambda root: SimpleNamespace(
            publication_id="completion-fixture",
            readiness={
                "assessment_state": "READY",
                "dates": {"financial_as_of": "2026-10-08"},
                "companies": completion_rows,
            },
        ),
    )
    monkeypatch.setattr(
        dataset_module,
        "CompanyMetadataReader",
        lambda root: SimpleNamespace(
            publication_id="metadata-fixture", list_companies=lambda: candidates
        ),
    )
    monkeypatch.setattr(
        dataset_module, "open_analysis", lambda root: fake_clients[str(root.resolve())]
    )

    manifest_path = publication / MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["fixture_kind"] = "ACTUAL_PREPARED"
    manifest["fixture_policy"] = None
    manifest["sources"] = {
        "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        "completion": {
            "root": str(completion_root),
            "publication_id": "completion-fixture",
            "manifest_sha256": sha256_file(
                completion_root / "universe_delivery_manifest.json"
            ),
        },
        "metadata": {
            "root": str(metadata_root),
            "publication_id": "metadata-fixture",
            "manifest_sha256": sha256_file(metadata_root / "company_metadata_manifest.json"),
        },
        "analysis": analysis_sources,
    }

    target = companies[0]
    old_path = publication / "source_snapshots" / target["cik"] / (
        target["source_snapshot_id"] + ".json"
    )
    changed_snapshot = json.loads(old_path.read_text())
    changed_snapshot["cells"][0]["display_value"] = "999"
    changed_snapshot["cells"][0]["value"] = "999"
    material = {key: value for key, value in changed_snapshot.items() if key != "snapshot_id"}
    changed_snapshot["snapshot_id"] = digest_value(material)
    new_path = old_path.with_name(changed_snapshot["snapshot_id"] + ".json")
    old_path.unlink()
    write_json(new_path, changed_snapshot)
    target["source_snapshot_id"] = changed_snapshot["snapshot_id"]
    write_json(publication / COMPANIES, companies)
    observations = json.loads((publication / OBSERVATIONS).read_text())
    observations = [row for row in observations if row["cik"] != target["cik"]]
    observations.extend(
        _observation(target["cik"], target["ticker"], cell["row_id"], cell, changed_snapshot)
        for cell in changed_snapshot["cells"]
    )
    write_json(publication / OBSERVATIONS, observations)
    declared_files = {
        str(path.relative_to(publication)): {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
        for path in publication.rglob("*")
        if path.is_file() and path != manifest_path
    }
    manifest["files"] = declared_files
    identity = {key: value for key, value in manifest.items() if key != "publication_id"}
    manifest["publication_id"] = "screening-dataset-" + digest_value(identity)[:24]
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="differs from prepared analysis source"):
        ScreeningDatasetReader(publication)
