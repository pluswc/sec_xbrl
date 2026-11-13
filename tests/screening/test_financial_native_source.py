"""Explicit native admission preserves ordinary checks and historical isolation."""
from __future__ import annotations

import asyncio
import copy
import json
import shutil
from pathlib import Path

import pytest

import sec_xbrl
from sec_xbrl import collection_operations, history, metric_quality
from sec_xbrl import financial_native_source as native
from sec_xbrl import financial_storage_reuse as storage
from sec_xbrl.history_validation import validation_code_identity
from sec_xbrl.metrics.quarterly_screening import publish_quarterly_screening_metrics
from sec_xbrl.metrics.screening import publish_screening_metrics
from sec_xbrl.metrics.statement_metric_evidence import CONTINUITY_CATALOG
from sec_xbrl.screening import dataset_v3
from sec_xbrl.screening import verified_source_closure as closure
from sec_xbrl.screening.common import digest_value, sha256_file, write_json
from sec_xbrl.screening.dataset_v2 import publish_screening_dataset_v2
from tests.screening.test_financial_storage_reuse import COHORT, _current_routine_proof, _pin
from tests.screening.test_generic_metric_identity_integration import FINANCIAL_AS_OF


def _fixture(tmp_path, monkeypatch, *, outside_ready=False):
    prepared, proof, report_path = _current_routine_proof(tmp_path, monkeypatch)
    if outside_ready:
        from tests.screening.test_generic_metric_identity_integration import _install_intake
        from tests.unit.test_source_bindings import _build_ready_histories
        _install_intake(prepared.paths, "SIX")
        _build_ready_histories(prepared.paths, tmp_path, monkeypatch, selected_tickers=("SIX",))
    current = tmp_path / "current-producer"
    shutil.copytree(Path(sec_xbrl.__file__).parent, current,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    monkeypatch.setattr(native, "_SOURCE_ROOT", current)
    origin = tmp_path / "accepted-producer"
    shutil.copytree(current, origin, ignore=shutil.ignore_patterns("financial_native_source.py"))
    with (origin / "financial_storage_reuse.py").open("a") as stream:
        stream.write("\n# Synthetic previous consumer bytes.\n")
    old_files = native._inventory(origin)
    monkeypatch.setattr(native, "_ORIGIN_INVENTORY", digest_value(old_files))
    monkeypatch.setattr(native, "_BASE_CHANGES", {})
    payload = json.loads(proof.read_text())
    entry = payload["companies"][0]["histories"][0]
    manifest = json.loads(Path(entry["history_manifest"]["path"]).read_text())
    old_identity = validation_code_identity(sources=tuple(sorted(origin.rglob("*.py"))),
                                            rules=storage.history_validation_rules(manifest))
    report = json.loads(report_path.read_text())
    report["code_identity"] = old_identity
    write_json(report_path, report)
    acceptance = Path(entry["acceptance"]["path"])
    write_json(acceptance, {"status": "ROOT_APPROVED", "kind": "ACCEPTED_CURRENT_ROUTINE_HISTORY",
                           "build_manifest": entry["build_manifest"], "history_manifest": entry["history_manifest"],
                           "validation_report": _pin(report_path)})
    entry["acceptance"] = _pin(acceptance)
    wrapper = Path(entry["previous_validation"]["path"])
    prior = json.loads(wrapper.read_text())
    prior["historical_controls"] = {"acceptance": entry["acceptance"], "report": _pin(report_path)}
    write_json(wrapper, prior)
    entry["previous_validation"] = _pin(wrapper)
    old_policy = {name: old_files[name.removeprefix("src/sec_xbrl/")] for name in storage.financial_storage_policy_sources()}
    payload["current_policy_source_sha256s"] = old_policy
    write_json(proof, payload)
    # Simulate the immutable prior producer only while creating synthetic parents.
    with monkeypatch.context() as producer:
        producer.setattr(storage, "financial_storage_policy_sources", lambda: old_policy)
        producer.setattr(storage, "current_history_validation_identity", lambda manifest: old_identity)
        config = json.loads((tmp_path / "quality-config.json").read_text())
        config["storage_reuse"] = _pin(proof)
        quality_config = tmp_path / "native-quality-config.json"
        write_json(quality_config, config)
        quality = metric_quality.publish_generic_metric_quality(config_path=quality_config,
            collection_manifest=Path(prepared.paths["collection"]), source_binding_publication=tmp_path / "quality-bindings",
            history_manifests=prepared.histories, destination=tmp_path / "native-quality", producer_revision=native.PRODUCER)
        config = json.loads(prepared.identity_config.read_text())
        config.update(storage_reuse=_pin(proof), quality_root=str(quality.root),
                      quality_manifest_sha256=sha256_file(quality.manifest_path))
        path = tmp_path / "native-identity-config.json"
        write_json(path, config)
        from sec_xbrl.screening.metric_identity import publish_generic_metric_identity
        identity = publish_generic_metric_identity(path, tmp_path / "native-identity")
        identity_source = {"kind": "GENERIC_METRIC_IDENTITY_ATTESTATION", "root": str(identity.root),
                           "manifest_sha256": sha256_file(identity.manifest_path)}
        path = tmp_path / "native-metrics-config.json"
        write_json(path, {"schema_version": "screening-metric-config-v2", "financial_as_of": FINANCIAL_AS_OF,
            "identity_source": identity_source, "companies": [{**COHORT[0], "analysis_root": str(prepared.annual),
                "analysis_manifest_sha256": sha256_file(prepared.annual / "analysis_manifest.json"),
                "input_years": [2021, 2022, 2023, 2024, 2025], "display_years": [2022, 2023, 2024, 2025]}]})
        metrics = publish_screening_metrics(path, tmp_path / "native-metrics")
        path = tmp_path / "native-annual-config.json"
        write_json(path, {"schema_version": "screening-prepare-config-v2-identity-v1", "dataset_id": "native-test",
            "financial_as_of": FINANCIAL_AS_OF, "fixture_kind": "ACTUAL_PREPARED", "identity_source": identity_source,
            "metric_root": str(metrics.root), "metric_manifest_sha256": sha256_file(metrics.manifest_path)})
        annual = publish_screening_dataset_v2(path, tmp_path / "native-annual")
        evidence = tmp_path / "occurrences.json"
        write_json(evidence, {"version": "statement-metric-occurrence-v1", "financial_as_of": FINANCIAL_AS_OF, "records": []})
        path = tmp_path / "native-quarter-config.json"
        write_json(path, {"schema_version": "quarterly-screening-metric-config-v1", "financial_as_of": FINANCIAL_AS_OF,
            "source_commit_sha": native.PRODUCER, "catalog_version": CONTINUITY_CATALOG,
            "statement_metric_evidence": _pin(evidence), "annual_metric_root": str(metrics.root),
            "annual_metric_manifest_sha256": sha256_file(metrics.manifest_path), "companies": [{**COHORT[0],
                "analysis_root": str(prepared.quarterly),
                "analysis_manifest_sha256": sha256_file(prepared.quarterly / "analysis_manifest.json")}]})
        quarter = publish_quarterly_screening_metrics(path, tmp_path / "native-quarter")
    parents = {"identity": _pin(identity.manifest_path), "annual_metrics": _pin(metrics.manifest_path),
               "annual_dataset": _pin(annual.manifest_path), "quarterly_metrics": _pin(quarter.manifest_path)}
    packet = native.prepare_native_source_packet(parents=parents, old_source_root=origin,
                                                 destination=tmp_path / "native-packet.json")
    approval = tmp_path / "native-root-approval.json"
    write_json(approval, {"schema_version": native.APPROVAL_VERSION,
                         "status": "ROOT_APPROVED_NATIVE_SOURCE_TRANSITION", "packet": _pin(packet)})
    declaration = {"packet": _pin(packet), "approval": _pin(approval)}
    config = {"schema_version": dataset_v3.CONFIG_VERSION, "dataset_id": "native-combined",
              "annual_dataset_root": str(annual.root), "annual_manifest_sha256": parents["annual_dataset"]["sha256"],
              "quarterly_metric_root": str(quarter.root), "quarterly_manifest_sha256": parents["quarterly_metrics"]["sha256"],
              "native_source": declaration}
    return config, packet, report_path


def test_public_native_publish_reopen_keeps_normal_checks_and_closure(tmp_path, monkeypatch):
    config, packet, _ = _fixture(tmp_path, monkeypatch)
    path = tmp_path / "combined-config.json"
    write_json(path, config)
    before = {Path(p["path"]): p["sha256"] for p in json.loads(packet.read_text())["parents"].values()}
    def forbidden(*args, **kwargs):
        raise AssertionError("completed History routine/deep checks must not repeat")
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    combined = dataset_v3.publish_screening_dataset_v3(path, tmp_path / "combined")
    reader = dataset_v3.ScreeningDatasetV3Reader(combined)
    assert reader.verify_all()["company_count"] == 1
    assert all(sha256_file(p) == digest for p, digest in before.items())
    manifest_path = Path(combined) / "screening_dataset_manifest.json"
    original_manifest = manifest_path.read_bytes()
    altered = json.loads(original_manifest)
    alias = tmp_path / "copied-annual"
    shutil.copytree(Path(config["annual_dataset_root"]), alias)
    altered["parents"]["annual"]["root"] = str(alias)
    write_json(manifest_path, altered)
    with pytest.raises(ValueError, match="configured compatibility scope"):
        dataset_v3.ScreeningDatasetV3Reader(combined)
    manifest_path.write_bytes(original_manifest)
    with dataset_v3._configured_compatibility(config):
        snapshot = closure._v3_snapshot(path, config, Path(config["annual_dataset_root"]), Path(config["quarterly_metric_root"]))
    controls = {record.path for record in snapshot.files}
    assert str(packet) in controls
    assert config["native_source"]["approval"]["path"] in controls
    assert any(record.role.startswith("NATIVE_SOURCE_INVENTORY:") for record in snapshot.inventories)
    pinless = {k: v for k, v in config.items() if k != "native_source"}
    with pytest.raises(ValueError, match="explicit successor"), dataset_v3._configured_compatibility(config), dataset_v3._configured_compatibility(pinless):
        pass
    assert native.native_controls() == ({}, ())


@pytest.mark.parametrize("defect", ["packet", "approval", "parent", "report", "source", "unknown", "current_source", "current_unknown", "mixed", "scope"])
def test_native_rejects_changed_or_mixed_controls(tmp_path, monkeypatch, defect):
    config, packet, report = _fixture(tmp_path, monkeypatch)
    declaration = config["native_source"]
    if defect in {"packet", "approval", "report"}:
        target = packet if defect == "packet" else Path(declaration["approval"]["path"]) if defect == "approval" else report
        target.write_bytes(target.read_bytes() + b" ")
    elif defect == "parent":
        config["annual_manifest_sha256"] = "0" * 64
    elif defect == "mixed":
        config["source_compatibility"] = {"path": "/tmp/old-packet", "sha256": "0" * 64}
    elif defect == "scope":
        config["quarterly_metric_root"] = str(tmp_path / "another-quarter")
    else:
        origin = native._SOURCE_ROOT if defect.startswith("current_") else Path(json.loads(packet.read_text())["source"]["old_root"])
        target = origin / ("unknown.py" if defect.endswith("unknown") else "history.py")
        target.write_text("unapproved source bytes")
    with pytest.raises(ValueError), dataset_v3._configured_compatibility(config):
        pass
    assert native.native_controls() == ({}, ())


def test_native_context_reset_report_scope_and_async_isolation(tmp_path, monkeypatch):
    config, packet, _ = _fixture(tmp_path, monkeypatch)
    payload = json.loads(packet.read_text())
    claim = payload["routines"][0]
    current = validation_code_identity(sources=tuple(sorted(native._SOURCE_ROOT.rglob("*.py"))), rules=claim["rules"])
    arguments = {**claim, "current_identity": current}
    assert native.native_routine_matches(**arguments) is False
    with dataset_v3._configured_compatibility(config):
        assert native.native_routine_matches(**arguments)
        foreign = copy.deepcopy(arguments)
        foreign["declared"] = {}
        assert native.native_routine_matches(**foreign) is False
        other_report = tmp_path / "unnamed-report.json"
        shutil.copyfile(Path(claim["report"]["path"]), other_report)
        foreign = copy.deepcopy(arguments)
        foreign["report"] = _pin(other_report)
        assert native.native_routine_matches(**foreign) is False
        with pytest.raises(RuntimeError), native.use_native_source(None):
            assert native.native_routine_matches(**arguments) is False
            raise RuntimeError("nested exit")
        assert native.native_routine_matches(**arguments)
        async def isolated():
            with native.use_native_source(None):
                await asyncio.sleep(0)
                assert native.native_routine_matches(**arguments) is False
        async def inherited():
            await asyncio.sleep(0)
            assert native.native_routine_matches(**arguments)
        async def concurrent():
            await asyncio.gather(isolated(), inherited())
        asyncio.run(concurrent())
        assert native.native_routine_matches(**arguments)
    assert native.native_routine_matches(**arguments) is False
    with pytest.raises(RuntimeError), dataset_v3._configured_compatibility(config):
        raise RuntimeError("outer exit")
    assert native.native_routine_matches(**arguments) is False


def test_native_keeps_payload_stat_validation(tmp_path, monkeypatch):
    config, packet, _ = _fixture(tmp_path, monkeypatch)
    payload = json.loads(packet.read_text())
    claim = payload["routines"][0]
    history_root = Path(claim["pins"]["history_manifest"]["path"]).parent
    data = history_root / next(iter(claim["declared"]))
    data.write_bytes(data.read_bytes() + b"changed")
    with dataset_v3._configured_compatibility(config), pytest.raises(ValueError):
        reuse = json.loads(Path(payload["storage_reuse"]["path"]).read_text())
        storage.resolve_storage_reuse(payload["storage_reuse"],
            collection_manifest=Path(reuse["collection_manifest"]["path"]), scope_companies=list(COHORT))


def test_native_control_tamper_before_promotion_leaves_no_candidate(tmp_path, monkeypatch):
    config, _, _ = _fixture(tmp_path, monkeypatch)
    path = tmp_path / "combined-config.json"
    write_json(path, config)
    original = dataset_v3._publish_verified_v3
    def changed_control(capability, **kwargs):
        approval = Path(config["native_source"]["approval"]["path"])
        approval.write_bytes(approval.read_bytes() + b" ")
        return original(capability, **kwargs)
    monkeypatch.setattr(dataset_v3, "_publish_verified_v3", changed_control)
    target = tmp_path / "combined"
    with pytest.raises(ValueError):
        dataset_v3.publish_screening_dataset_v3(path, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".combined.partial-*"))


def test_active_native_scope_rechecks_current_bytes(tmp_path, monkeypatch):
    config, packet, _ = _fixture(tmp_path, monkeypatch)
    payload = json.loads(packet.read_text())
    claim = payload["routines"][0]
    current = validation_code_identity(sources=tuple(sorted(native._SOURCE_ROOT.rglob("*.py"))), rules=claim["rules"])
    with dataset_v3._configured_compatibility(config):
        assert native.native_routine_matches(**claim, current_identity=current)
        path = native._SOURCE_ROOT / "financial_native_source.py"
        path.write_bytes(path.read_bytes() + b"# drift\n")
        with pytest.raises(ValueError, match="inventory"):
            native.native_routine_matches(**claim, current_identity=current)
    assert native.native_controls() == ({}, ())


def test_native_multi_company_assesses_only_named_parent_in_identity_and_quality(tmp_path, monkeypatch):
    config, packet, _ = _fixture(tmp_path, monkeypatch, outside_ready=True)
    payload = json.loads(packet.read_text())
    identity = json.loads(Path(payload["parents"]["identity"]["path"]).read_text())
    collection = Path(identity["config"]["collection_manifest"])
    original = history.HistoryPublicationReader.validate
    outside_calls = []
    def poisoned(self, *args, **kwargs):
        if self.manifest["plan"]["companies"][0]["ticker"] == "SIX":
            outside_calls.append("SIX")
            raise AssertionError("outside History.validate must not run")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", poisoned)
    path = tmp_path / "multi-combined-config.json"
    write_json(path, config)
    combined = dataset_v3.publish_screening_dataset_v3(path, tmp_path / "multi-combined")
    assert dataset_v3.ScreeningDatasetV3Reader(combined).verify_all()["company_count"] == 1
    assert outside_calls == []
    with dataset_v3._configured_compatibility(config):
        reuse = json.loads(Path(payload["storage_reuse"]["path"]).read_text())
        assessed = native.native_assessed_ciks(collection_manifest=collection, scope_companies=list(COHORT))
        status = collection_operations.read_universe_status(manifest_path=collection, validation_mode="financial_sources",
            storage_reuse=payload["storage_reuse"], assessed_ciks=assessed)
        assert status.requested_companies == 2
        assert [row.state for row in status.companies if row.ticker == "SIX"] == ["NOT_ASSESSED_OUTSIDE_SCOPE"]
        assert status.ready_companies == 1
        outside_cik = next(row.cik for row in status.companies if row.ticker == "SIX")
        with pytest.raises(ValueError, match="assessment"):
            collection_operations.read_universe_status(manifest_path=collection, validation_mode="financial_sources",
                storage_reuse=payload["storage_reuse"], assessed_ciks=(outside_cik,))
        with pytest.raises(ValueError, match="assessment"):
            collection_operations.read_universe_status(manifest_path=collection, validation_mode="financial_sources",
                storage_reuse=payload["storage_reuse"])
        with pytest.raises(ValueError, match="scope"):
            native.native_assessed_ciks(collection_manifest=collection, scope_companies=reuse["companies"] + [{"ticker": "OTHER", "cik": "0000009999"}])
    # Default None preserves the previous full assessment, including its failure.
    with pytest.raises(AssertionError, match="outside"):
        collection_operations.read_universe_status(manifest_path=collection)
    assert outside_calls == ["SIX"]


@pytest.mark.parametrize("scope", [(), ("0000009999",), ("123",), ("0000000123", "0000000123")])
def test_status_rejects_unknown_noncanonical_or_empty_assessment(tmp_path, monkeypatch, scope):
    _, packet, _ = _fixture(tmp_path, monkeypatch)
    identity = json.loads(Path(json.loads(packet.read_text())["parents"]["identity"]["path"]).read_text())
    with pytest.raises(ValueError, match="assessed CIK"):
        collection_operations.read_universe_status(manifest_path=Path(identity["config"]["collection_manifest"]), assessed_ciks=scope)
