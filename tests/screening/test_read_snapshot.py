"""The new reader has no authority to reopen or requalify old source."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.screening.common import digest_value, sha256_file
from sec_xbrl.screening.read_snapshot import ScreeningReadSnapshot

TOOL = Path(__file__).parents[2] / "tools/export_screening_read_snapshot.py"
spec = importlib.util.spec_from_file_location("snapshot_export", TOOL)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def approve(root: Path) -> dict:
    manifest = json.loads((root / exporter.MANIFEST).read_bytes())
    pin = {"path": str(root / exporter.MANIFEST), "sha256": sha256_file(root / exporter.MANIFEST)}
    receipt = {"schema_version": "screening-read-export-verification-v1", "verified": True,
               "manifest_sha256": pin["sha256"], "logical_sha256": manifest["logical_sha256"], "origin": manifest["origin"]}
    verification = root / "verification.json"
    verification.write_bytes(exporter.encoded(receipt))
    approval = {"schema_version": "screening-read-snapshot-root-approval-v1", "authority": "ROOT", "approved": True,
                "reader_version": exporter.VERSION, "manifest_sha256": pin["sha256"],
                "verification_sha256": sha256_file(verification), "logical_sha256": manifest["logical_sha256"],
                "origin": manifest["origin"]}
    path = root.parent / (root.name + "-approval.json")
    path.write_bytes(exporter.encoded(approval))
    return {"manifest": pin, "verification": {"path": str(verification), "sha256": sha256_file(verification)},
            "approval": {"path": str(path), "sha256": sha256_file(path)}}


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    from sec_xbrl.screening import runtime_projection
    company = {"cik": "0000000001", "ticker": "TEST", "name": "Example"}
    row = {"cik": company["cik"], "metric_id": "revenue", "fiscal_year": 2025, "value": "1.0000000001",
           "metric_observation_id": "original-id", "trace": {"source": "original"}, "availability_status": "AVAILABLE"}
    reader = SimpleNamespace(companies=[company], company=lambda cik: copy.deepcopy(company),
        manifest={"dataset_id": "original", "publication_id": "original-pub", "financial_as_of": "2026-10-25"},
        _manifest_sha256="a" * 64, metric_definitions=[{"metric_id": "revenue"}], metadata=[{"original": True}],
        metric_support=[{"metric_id": "revenue", "execution_supported": True}], quarterly=SimpleNamespace(manifest={"global_quarter_spine": []}),
        quarter_definitions=[], quarter_support=[], quarter_period_inventory=[],
        verify_all=lambda: {"dataset_id": "original", "publication_id": "original-pub"})
    monkeypatch.setattr(runtime_projection, "observation_rows", lambda reader, **selection: [] if selection["quarterly"] else [row])
    monkeypatch.setattr(runtime_projection, "hydrate_observation", lambda reader, row, **kw: copy.deepcopy(row))
    root = tmp_path / "snapshot"
    exporter.export_reader(reader, root, {"source_files": [], "artifact_files": [], "source_revision": "old"})
    return root, approve(root), row


def test_snapshot_preserves_identity_metadata_precision_trace_and_copy_isolation(snapshot):
    root, declaration, original = snapshot
    reader = ScreeningReadSnapshot(root, declaration)
    assert reader.manifest["publication_id"] == "original-pub"
    assert reader.hydrate(reader.rows()[0]) == original == reader.hydrate(reader.latest_rows()[0])
    assert reader.metric_support == [{"metric_id": "revenue", "execution_supported": True}]
    reader.hydrate(reader.rows()[0])["trace"]["source"] = "changed"
    assert reader.hydrate(reader.rows()[0])["trace"]["source"] == "original"
    assert reader.verify_all() == {"dataset_id": "original", "publication_id": "original-pub"}


@pytest.mark.parametrize("field", ["trace", "owner", "period", "company", "missing"])
def test_snapshot_file_tampering_and_missing_fail_closed(snapshot, field):
    root, declaration, _ = snapshot
    path = root / "0000000001.json"
    if field == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_bytes())
        data[field] = "tampered"
        path.write_bytes(exporter.encoded(data))
    with pytest.raises(ValueError):
        ScreeningReadSnapshot(root, declaration)


def test_separate_exact_root_approval_required(snapshot):
    root, declaration, _ = snapshot
    approval = Path(declaration["approval"]["path"])
    data = json.loads(approval.read_bytes())
    data["approved"] = False
    approval.write_bytes(exporter.encoded(data))
    declaration["approval"]["sha256"] = sha256_file(approval)
    with pytest.raises(ValueError, match="ROOT"):
        ScreeningReadSnapshot(root, declaration)


def test_rehashed_manifest_cannot_reuse_verification_and_root_receipt(snapshot):
    root, declaration, _ = snapshot
    manifest = root / exporter.MANIFEST
    data = json.loads(manifest.read_bytes())
    data["properties"]["original_manifest"]["publication_id"] = "other"
    data["logical_sha256"] = digest_value({key: value for key, value in data.items() if key != "logical_sha256"})
    manifest.write_bytes(exporter.encoded(data))
    declaration["manifest"]["sha256"] = sha256_file(manifest)
    with pytest.raises(ValueError, match="verification"):
        ScreeningReadSnapshot(root, declaration)


def test_original_v1_capabilities_full_api_trace_and_saved_result_remain_equal(screening_dataset, tmp_path):
    from sec_xbrl.screening.service import ScreeningService
    original_id = json.loads((screening_dataset / "screening_dataset_manifest.json").read_bytes())["dataset_id"]
    original = ScreeningService({original_id: screening_dataset}, tmp_path / "original.sqlite")
    dataset_id = next(iter(original.datasets))
    root = tmp_path / "v1-snapshot"
    exporter.export_reader(original.datasets[dataset_id], root, {"source_revision": "synthetic"})
    reopened = ScreeningService({dataset_id: root}, tmp_path / "reopened.sqlite", read_snapshots={dataset_id: approve(root)})
    assert reopened.status() == original.status()
    assert reopened.metric_catalog(dataset_id) == original.metric_catalog(dataset_id)
    with pytest.raises(ValueError, match="v2 screening dataset"):
        reopened.company_explorer(dataset_id)
    with pytest.raises(TypeError, match="v3 screening dataset"):
        reopened.quarter_metric_catalog(dataset_id)
    definition = original.metric_catalog(dataset_id)[0]
    condition = {"universe": {"mode": "ALL_PREPARED"}, "period_policy": {"mode": "LATEST_COMPLETE_ANNUAL", "offset": 0},
                 "predicates": [{"metric_id": definition["metric_id"], "definition_version": definition["definition_version"], "operator": "GTE", "threshold": "0"}],
                 "columns": ["ticker", "aggregate"], "sort": {"column": "ticker", "direction": "ASC"}}
    assert reopened.preview(condition, dataset_id) == original.preview(condition, dataset_id)


def test_v2_and_v3_snapshot_public_api_equivalence(tmp_path, monkeypatch):
    from sec_xbrl.screening.service import ScreeningService
    from tests.screening.test_runtime_projection import DATASET, _verified_v3
    root = _verified_v3(tmp_path, monkeypatch)
    original = ScreeningService({DATASET: root}, tmp_path / "old-v3.sqlite")
    reader = original.datasets[DATASET]
    snapshots = tmp_path / "v3-snapshot"
    exporter.export_reader(reader, snapshots, {"source_revision": "synthetic"})
    reopened = ScreeningService({DATASET: snapshots}, tmp_path / "new-v3.sqlite", read_snapshots={DATASET: approve(snapshots)})
    assert reopened.status() == original.status()
    assert reopened.metric_catalog(DATASET) == original.metric_catalog(DATASET)
    assert reopened.quarter_metric_catalog(DATASET) == original.quarter_metric_catalog(DATASET)
    assert reopened.quarter_periods(DATASET) == original.quarter_periods(DATASET)
    assert reopened.company_explorer(DATASET, latest=True) == original.company_explorer(DATASET, latest=True)
    cik = reader.companies[0]["cik"]
    assert reopened.company_profile(DATASET, cik=cik) == original.company_profile(DATASET, cik=cik)
    annual_reader = reader.annual
    annual_snapshot = tmp_path / "v2-snapshot"
    from sec_xbrl.screening.dataset_v3 import _configured_compatibility
    with _configured_compatibility(reader.manifest["config"]):
        exporter.export_reader(annual_reader, annual_snapshot, {"source_revision": "synthetic"})
    annual = ScreeningReadSnapshot(annual_snapshot, approve(annual_snapshot))
    assert annual.capabilities == {"explorer": True, "quarterly": False}


def test_export_full_source_bridge_artifact_pins_reject_toctou_and_inventory_additions(tmp_path, monkeypatch):
    base = tmp_path / "accepted"
    source = base / "src/sec_xbrl"
    source.mkdir(parents=True)
    module = source / "module.py"
    module.write_text("# original\n")
    bridge = base / "examples/screening/windows-loopback-bridge.cjs"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("// original\n")
    artifact = tmp_path / "original.json"
    artifact.write_text('{"original":true}')
    def pin(path):
        return {"path": str(path), "sha256": sha256_file(path)}
    monkeypatch.setattr(exporter.subprocess, "check_output", lambda *args, **kw: "accepted-revision\n")
    monkeypatch.setattr(exporter.subprocess, "run", lambda *args, **kw: SimpleNamespace(returncode=0))
    config = {"exporter_sha256": sha256_file(TOOL), "source_revision": "accepted-revision", "source_root": str(source), "source_files": [pin(module)], "source_aux_files": [pin(bridge)],
              "artifact_files": [pin(artifact)], "catalog": pin(artifact)}
    exporter.verify_pins(config)
    artifact.write_text('{"original":false}')
    with pytest.raises(ValueError, match="pin changed"):
        exporter.verify_pins(config)
    artifact.write_text('{"original":true}')
    (source / "unapproved.py").write_text("# extra")
    with pytest.raises(ValueError, match="inventory"):
        exporter.verify_pins(config)


def test_fixed_and_supplementary_latest_are_separate(snapshot):
    root, _declaration, _ = snapshot
    data = json.loads((root / "0000000001.json").read_bytes())
    # Build a separately approved synthetic fixture with a latest-only annual row.
    full = {**data["details"]["original-id"], "metric_observation_id": "supplement", "fiscal_year": 2026}
    data["details"]["supplement"] = full
    core = {key: value for key, value in full.items() if key != "trace"}
    data["views"]["annual_latest"].append(core)
    (root / "0000000001.json").write_bytes(exporter.encoded(data))
    manifest = json.loads((root / exporter.MANIFEST).read_bytes())
    manifest["files"]["0000000001"]["sha256"] = sha256_file(root / "0000000001.json")
    manifest["properties"]["row_order"]["annual_latest"].append("supplement")
    manifest["logical_sha256"] = digest_value({key: value for key, value in manifest.items() if key != "logical_sha256"})
    (root / exporter.MANIFEST).write_bytes(exporter.encoded(manifest))
    reader = ScreeningReadSnapshot(root, approve(root))
    assert [row["fiscal_year"] for row in reader.rows()] == [2025]
    assert [row["fiscal_year"] for row in reader.latest_rows()] == [2025, 2026]
