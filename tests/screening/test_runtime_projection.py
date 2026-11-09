"""Runtime read model parity, integrity, and immutable update scope."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.dataset_v3 import MANIFEST as DATASET_MANIFEST
from sec_xbrl.screening.dataset_v3 import VERSION as DATASET_VERSION
from sec_xbrl.screening.dataset_v3 import publish_screening_dataset_v3
from sec_xbrl.screening.runtime_projection import (
    RuntimeProjectionBuilder,
    ScreeningRuntimeProjection,
    compact_observation,
    publish_runtime_projection,
)
from sec_xbrl.screening.service import ScreeningService
from tests.screening.test_financial_source_compatibility_v2 import _pin, _supersession
from tests.screening.test_screening_quarterly_consumer import _quarter_service

DATASET = "projection-fixture"


def _verified_v3(tmp_path, monkeypatch):
    path, _, _, _, _, completed = _supersession(tmp_path, monkeypatch, public_parents=True)
    config = tmp_path / "combined.json"
    write_json(config, {
        "schema_version": "screening-prepare-config-v3", "dataset_id": DATASET,
        "annual_dataset_root": str(Path(completed["annual_dataset"]["path"]).parent),
        "annual_manifest_sha256": completed["annual_dataset"]["sha256"],
        "quarterly_metric_root": str(Path(completed["quarterly_metrics"]["path"]).parent),
        "quarterly_manifest_sha256": completed["quarterly_metrics"]["sha256"],
        "source_compatibility": _pin(path),
    })
    return publish_screening_dataset_v3(config, tmp_path / "combined")


def _reader(root, manifest):
    return ScreeningRuntimeProjection(root, _pin(manifest))


def _condition(policy, definition):
    return {
        "universe": {"mode": "ALL_PREPARED"}, "period_policy": policy,
        "predicates": [{"metric_id": definition["metric_id"], "operator": "GTE",
                        "threshold": "0", "definition_version": definition["definition_version"]}],
        "columns": ["ticker", "aggregate"], "sort": {"column": "ticker", "direction": "ASC"},
    }


def test_opted_in_service_preserves_verified_public_api_and_saved_records(tmp_path, monkeypatch):
    root = _verified_v3(tmp_path, monkeypatch)
    original_manifest = sha256_file(root / DATASET_MANIFEST)
    legacy = ScreeningService({DATASET: root}, tmp_path / "legacy.sqlite")
    verified = legacy.datasets[DATASET]
    manifest = publish_runtime_projection(root, tmp_path / "projection", tmp_path / "blobs", reader=verified)
    projected = ScreeningService({DATASET: root}, tmp_path / "projected.sqlite", runtime_projections={DATASET: _pin(manifest)})
    reader = projected.datasets[DATASET]
    assert isinstance(reader, ScreeningRuntimeProjection)
    assert reader.publication_id == verified.publication_id and reader._manifest_sha256 == original_manifest
    assert DATASET not in projected.explorers and reader._core.cache_info().misses == 0
    assert projected.status() == legacy.status()
    assert projected.company_explorer(DATASET, latest=True) == legacy.company_explorer(DATASET, latest=True)
    cik = verified.companies[0]["cik"]
    assert projected.company_profile(DATASET, cik=cik) == legacy.company_profile(DATASET, cik=cik)
    assert reader._evidence.cache_info().misses == 0

    quarter = next(row for row in verified.quarter_observations
                   if row["metric_id"] == "quarter_revenue" and row["availability_status"] == "AVAILABLE")
    coord = {"calendar_year": quarter["calendar_year"], "calendar_quarter": quarter["calendar_quarter"]}
    spec = {"metric_id": quarter["metric_id"], "definition_version": quarter["definition_version"]}
    condition = _condition({"mode": "FIXED_CALENDAR_QUARTER_END", **coord}, spec)
    core_matrix = projected.quarter_explorer(DATASET, **coord, include_evidence=False)
    assert core_matrix == legacy.quarter_explorer(DATASET, **coord, include_evidence=False)
    assert "source_lineage" not in core_matrix["rows"][0]["metrics"][spec["metric_id"]]
    before = sha256_file(projected.store.path)
    compact = projected.preview(condition, DATASET, include_evidence=False)
    assert compact == legacy.preview(condition, DATASET, include_evidence=False)
    assert reader._evidence.cache_info().misses == 0
    assert sha256_file(projected.store.path) == before

    assert projected.quarter_explorer(DATASET, **coord) == legacy.quarter_explorer(DATASET, **coord)
    full = projected.preview(condition, DATASET)
    assert full == legacy.preview(condition, DATASET)
    assert compact["preview_hash"] != full["preview_hash"]
    assert compact["include_evidence"] is False and "include_evidence" not in full
    for core, whole in zip(compact["rows"], full["rows"], strict=True):
        core_observation = core["predicates"][0]["observation"]
        assert core_observation == compact_observation(whole["predicates"][0]["observation"])
    with pytest.raises(ValueError, match="preview is stale"):
        projected.save_result(name="mismatch", content=condition, dataset_id=DATASET,
                              preview_hash=compact["preview_hash"])
    assert sha256_file(projected.store.path) == before
    saved = projected.save_result(name="same trace", content=condition, dataset_id=DATASET,
                                  preview_hash=compact["preview_hash"], include_evidence=False)
    assert saved["rows"] == full["rows"]
    assert "include_evidence" not in saved
    historical = ScreeningService({DATASET: root}, projected.store.path)
    assert historical.run(saved["run_id"]) == saved
    assert projected.trace(saved["run_id"], cik=cik, metric_id=spec["metric_id"]) == historical.trace(
        saved["run_id"], cik=cik, metric_id=spec["metric_id"],
    )
    assert sha256_file(root / DATASET_MANIFEST) == original_manifest


def _stand_in_source(tmp_path, root_name, *, change=False):
    # The quarterly wire reader is verified. The V3 wrapper is synthetic so the
    # test can isolate a single publication delta without rerunning producers.
    reader = _quarter_service(tmp_path).datasets["synthetic-v3"]
    root = tmp_path / root_name
    root.mkdir()
    reader.root = root
    reader.manifest.update(schema_version=DATASET_VERSION, publication_id=root_name)
    reader.publication_id = root_name
    reader.metadata = copy.deepcopy(reader.companies)
    reader.annual = None
    reader.observations = [
        {"cik": reader.companies[0]["cik"], "fiscal_year": 2025, "metric_id": "revenue",
         "period_class": period_class, "view": "LATEST_REPORTED", "value": str(index),
         "trace": {"value_lineage": {"filed_date": "2026-01-01"}, "sequence": [None, False, index]}}
        for index, period_class in enumerate(("FY", "INSTANT"))
    ]
    if change:
        reader.quarter_observations = copy.deepcopy(reader.quarter_observations)
        reader.quarter_observations[0]["source_lineage"]["fixture_delta"] = [1, None, "001"]
    write_json(root / DATASET_MANIFEST, reader.manifest)
    reader._manifest_sha256 = sha256_file(root / DATASET_MANIFEST)
    return root, reader


def _files(root):
    return {path.relative_to(root): (path.stat().st_ino, path.stat().st_mtime_ns)
            for path in root.rglob("*.json.gz")}


def test_one_evidence_update_reuses_core_and_unrelated_partitions(tmp_path):
    first, old = _stand_in_source(tmp_path, "old")
    second, new = _stand_in_source(tmp_path, "new", change=True)
    blobs = tmp_path / "blobs"
    builder = RuntimeProjectionBuilder(blobs)
    prior = builder.publish(first, tmp_path / "prior", reader=old)
    files = _files(blobs)
    assert builder.publish(first, tmp_path / "prior", reader=old) == prior
    assert _files(blobs) == files
    updated = builder.publish(second, tmp_path / "updated", reader=new)
    current_files = _files(blobs)
    assert {name: current_files[name] for name in files} == files
    old_index = json.loads(prior.read_bytes())["observations"]
    new_index = json.loads(updated.read_bytes())["observations"]
    assert old_index["annual"] == new_index["annual"]
    assert len(new_index["quarterly"]) == len(old_index["quarterly"])
    assert sum(left != right for left, right in zip(
        old_index["quarterly"], new_index["quarterly"], strict=True,
    )) == 1
    assert all(left["core"] == right["core"] for left, right in zip(
        old_index["quarterly"], new_index["quarterly"], strict=True,
    ))
    reader = _reader(second, updated)
    assert [reader.hydrate(row) for row in reader.rows(metric_id="revenue")] == new.observations
    rows = reader.rows(quarterly=True)
    assert [reader.hydrate(row, quarterly=True) for row in rows] == new.quarter_observations
    with pytest.raises(ValueError, match="original publication"):
        _reader(second, prior)


def test_only_touched_detail_is_checked_and_tampering_does_not_fall_back(tmp_path):
    source, old = _stand_in_source(tmp_path, "original")
    blobs = tmp_path / "blobs"
    manifest = publish_runtime_projection(source, tmp_path / "projection", blobs, reader=old)
    declarations = json.loads(manifest.read_bytes())["observations"]["quarterly"]
    bad = declarations[-1]
    digest = bad["evidence"]["content_sha256"]
    path = blobs / digest[:2] / f"{digest}.json.gz"
    path.write_bytes(path.read_bytes() + b"corruption")
    reader = _reader(source, manifest)
    cik, year, quarter = bad["coordinate"]
    core = reader.rows(quarterly=True, cik=cik, year=year, quarter=quarter)
    assert core and reader._evidence.cache_info().misses == 0
    good = next(item for item in declarations if item["evidence"] != bad["evidence"])
    other_cik, other_year, other_quarter = good["coordinate"]
    other = reader.rows(quarterly=True, cik=other_cik, year=other_year, quarter=other_quarter)
    assert reader.hydrate(other[0], quarterly=True)["source_lineage"]
    with pytest.raises(ValueError, match="blob differs from pinned digest"):
        reader.hydrate(core[0], quarterly=True)
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(ValueError, match="manifest differs from pinned digest"):
        ScreeningRuntimeProjection(source, {"path": str(manifest), "sha256": "a" * 64})
