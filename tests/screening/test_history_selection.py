"""Synthetic accepted-input routing and financial-only storage-proof reuse."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl import history, metric_quality
from sec_xbrl.history_selection import (
    resolve_history_selection,
    selection_declaration,
    verify_financial_history_source,
)
from sec_xbrl.screening import metric_identity
from sec_xbrl.screening import verified_source_closure as closure
from sec_xbrl.screening.common import sha256_file, write_json
from tests.screening.test_generic_metric_identity_integration import (
    COHORT,
    FINANCIAL_AS_OF,
    _publish_identity_inputs,
    _quarterly_analysis,
)
from tests.screening.test_screening_metric_publication import _analysis_bundle
from tests.unit.test_history_recovery import _full_report, _recovery_fixture


def _pin(path):
    return {"path": str(path), "sha256": sha256_file(path)}


def _selected_fixture(tmp_path, monkeypatch):
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    collection = Path(prepared.paths["collection"])
    original_marker = collection.parent / "companies/FIVE/build_manifest.json"
    build = json.loads(original_marker.read_text())
    selected_root = tmp_path / "accepted-selected-history"
    shutil.copytree(prepared.histories["FIVE"].parent, selected_root)
    selected_manifest = selected_root / "history_manifest.json"
    # Different retained immutable History identity, same original source scope.
    payload = json.loads(selected_manifest.read_text())
    payload["synthetic_selected_history"] = True
    write_json(selected_manifest, payload)
    build.update(output_root=str(selected_root), publication=str(selected_root),
                 history_manifest=str(selected_manifest), history_manifest_sha256=sha256_file(selected_manifest))
    build_path = tmp_path / "accepted-build.json"
    write_json(build_path, build)
    recovery = {"schema_version": "universe50-history-recovery-receipt-v1", "status": "READY",
                "ticker": "FIVE", "cik": COHORT[0]["cik"], "collection_manifest": str(collection),
                "collection_manifest_sha256": sha256_file(collection),
                "build_manifest": str(build_path), "build_manifest_sha256": sha256_file(build_path),
                "publication": str(selected_root), "history_manifest_sha256": sha256_file(selected_manifest),
                "declared_files": build["declared_files"], "financial_as_of": FINANCIAL_AS_OF,
                "plan_sha256": build["plan_sha256"], "intake_sha256": build["intake_sha256"]}
    recovery_path = tmp_path / "accepted-recovery.json"
    write_json(recovery_path, recovery)
    witness = tmp_path / "historical-audit.json"
    # Historical paths are data in a hash-bound witness, never active inventories.
    write_json(witness, {"fixture_kind": "SYNTHETIC", "old_engine_checkout": "/nonexistent/old-checkout"})
    approval_path = tmp_path / "historical-lead-acceptance.json"
    write_json(approval_path, {"schema_version": "lead-later45-company-history-acceptance-v1",
                              "status": "LOCALLY_ACCEPTED_COMPANY_HISTORY_ONLY_NOT_FINANCIAL_READY",
                              "accepted_by": "ROOT_LEAD", **COHORT[0],
                              "fixture_kind": "SYNTHETIC_SELECTION_TEST",
                              "build_manifest": _pin(build_path), "recovery_receipt": _pin(recovery_path),
                              "actual_audit_report": _pin(witness)})
    companion_path = tmp_path / "history-selection.json"
    entry = {**COHORT[0], "acceptance": _pin(approval_path), "recovery_receipt": _pin(recovery_path),
             "build_manifest": _pin(build_path), "history_manifest": _pin(selected_manifest)}
    write_json(companion_path, {"schema_version": "accepted-history-selection-v1",
                               "collection_manifest": _pin(collection), "companies": [entry]})
    return prepared, companion_path, witness


def test_explicit_selection_preserves_original_ready_and_replays_quality_identity(tmp_path, monkeypatch):
    prepared, companion, _ = _selected_fixture(tmp_path, monkeypatch)
    collection = Path(prepared.paths["collection"])
    original = (collection.parent / "companies/FIVE/build_manifest.json").read_bytes()
    selection = resolve_history_selection(_pin(companion), collection_manifest=collection, scope_companies=list(COHORT))
    entry = selection.companies["FIVE"]
    selected_manifest = Path(entry["history_manifest"]["path"])
    old_config = json.loads((tmp_path / "quality-config.json").read_text())
    old_config["history_selection"] = _pin(companion)
    old_config["source_provenance"][0]["history_manifest_sha256"] = sha256_file(selected_manifest)
    quality_config = tmp_path / "selected-quality-config.json"
    write_json(quality_config, old_config)
    quality = metric_quality.publish_generic_metric_quality(
        config_path=quality_config, collection_manifest=collection,
        source_binding_publication=tmp_path / "quality-bindings", history_manifests={"FIVE": selected_manifest},
        destination=tmp_path / "selected-quality", producer_revision="e" * 40)
    q = metric_quality.GenericMetricQualityReader(quality.root)
    q.verify_sources(collection_manifest=collection, history_manifest_sha256s={"FIVE": sha256_file(selected_manifest)},
                     financial_as_of=FINANCIAL_AS_OF, expected_companies=COHORT)
    assert q.manifest["collection_status"][0]["history_manifest_path"] == str(prepared.histories["FIVE"])
    assert q.manifest["selected_history_evidence"]["FIVE"]["selection_status"] == "ACCEPTED_HISTORY_SELECTED"
    years = (2021, 2022, 2023, 2024, 2025)
    annual = _analysis_bundle(tmp_path / "selected-annual", years, ticker="FIVE", cik=COHORT[0]["cik"],
                              financial_as_of=FINANCIAL_AS_OF, history_root=selected_manifest.parent)
    quarterly = _quarterly_analysis(tmp_path / "selected-inputs", history_root=selected_manifest.parent, years=years)
    config = json.loads(prepared.identity_config.read_text())
    config.update(history_selection=_pin(companion), quality_root=str(quality.root), quality_manifest_sha256=sha256_file(quality.manifest_path))
    config["companies"][0].update(history_root=str(selected_manifest.parent), history_manifest_sha256=sha256_file(selected_manifest),
                                 annual_analysis_root=str(annual), annual_analysis_manifest_sha256=sha256_file(annual / "analysis_manifest.json"),
                                 quarterly_analysis_root=str(quarterly), quarterly_analysis_manifest_sha256=sha256_file(quarterly / "analysis_manifest.json"))
    selected_config = tmp_path / "selected-identity-config.json"
    write_json(selected_config, config)
    identity = metric_identity.publish_generic_metric_identity(selected_config, tmp_path / "selected-identity")
    reader = metric_identity.GenericMetricIdentityReader(identity.root)
    assert reader.companies[0]["history"]["root"] == str(selected_manifest.parent)
    assert reader.companies[0]["history"]["collection_build_manifest_sha256"] == sha256_file(collection.parent / "companies/FIVE/build_manifest.json")
    assert (collection.parent / "companies/FIVE/build_manifest.json").read_bytes() == original
    snapshot = closure._Collector()
    closure._discover_identity(snapshot, selected_config, metric_identity._validate_config(config), prefix="SELECTION")
    paths = {row.path for row in snapshot.snapshot().files}
    assert str(companion) in paths
    assert str(tmp_path / "historical-audit.json") in paths
    twin = tmp_path / "different-selection.json"
    twin.write_bytes(companion.read_bytes())
    different = copy.deepcopy(config)
    different["history_selection"] = _pin(twin)
    with pytest.raises(ValueError, match="companions differ"):
        metric_identity._verify_configured_sources(metric_identity._validate_config(different))
    # A control changed after deep verification must fail publication freshness.
    witness = tmp_path / "historical-audit.json"
    before = witness.read_bytes()
    original_verify = metric_identity._verify_configured_sources
    def verify_then_mutate(value):
        result = original_verify(value)
        witness.write_text("changed during publication")
        return result
    with monkeypatch.context() as context:
        context.setattr(metric_identity, "_verify_configured_sources", verify_then_mutate)
        with pytest.raises(ValueError, match="changed|hash"):
            metric_identity.publish_generic_metric_identity(selected_config, tmp_path / "changed-identity")
    assert not (tmp_path / "changed-identity").exists()
    witness.write_bytes(before)
    # The persisted publication replays current selection evidence on every open.
    (tmp_path / "historical-audit.json").write_text("tampered")
    with pytest.raises(ValueError, match="changed|digest"):
        metric_identity.GenericMetricIdentityReader(identity.root)


@pytest.mark.parametrize("defect", ["duplicate", "unknown", "cik", "approval", "recovery", "views", "intake", "history", "alias", "extra_field"])
def test_selection_rejects_unapproved_or_mismatched_routes(tmp_path, monkeypatch, defect):
    prepared, companion, _ = _selected_fixture(tmp_path, monkeypatch)
    payload = json.loads(companion.read_text())
    entry = payload["companies"][0]
    if defect == "duplicate":
        payload["companies"].append(copy.deepcopy(entry))
    elif defect == "unknown":
        entry["ticker"] = "UNKNOWN"
    elif defect == "cik":
        entry["cik"] = "0000000456"
    elif defect == "extra_field":
        entry["allow_override"] = True
    elif defect == "alias":
        alias = tmp_path / "approval-link.json"
        alias.symlink_to(entry["acceptance"]["path"])
        entry["acceptance"]["path"] = str(alias)
    elif defect == "approval":
        path = Path(entry["acceptance"]["path"])
        approval = json.loads(path.read_text()); approval["status"] = "PROPOSED"
        write_json(path, approval); entry["acceptance"] = _pin(path)
    elif defect == "recovery":
        path = Path(entry["recovery_receipt"]["path"])
        recovery = json.loads(path.read_text()); recovery["status"] = "NOT_READY"
        write_json(path, recovery); entry["recovery_receipt"] = _pin(path)
    elif defect in {"views", "intake"}:
        path = Path(entry["build_manifest"]["path"])
        build = json.loads(path.read_text()); build["views" if defect == "views" else "intake_manifest"] = [] if defect == "views" else "/different"
        write_json(path, build); entry["build_manifest"] = _pin(path)
        receipt_path = Path(entry["recovery_receipt"]["path"])
        receipt = json.loads(receipt_path.read_text())
        receipt["build_manifest_sha256"] = entry["build_manifest"]["sha256"]
        write_json(receipt_path, receipt); entry["recovery_receipt"] = _pin(receipt_path)
        approval_path = Path(entry["acceptance"]["path"])
        approval = json.loads(approval_path.read_text())
        approval.update(build_manifest=entry["build_manifest"], recovery_receipt=entry["recovery_receipt"])
        write_json(approval_path, approval); entry["acceptance"] = _pin(approval_path)
    else:
        entry["history_manifest"]["sha256"] = "0" * 64
    write_json(companion, payload)
    with pytest.raises(ValueError):
        resolve_history_selection(_pin(companion), collection_manifest=Path(prepared.paths["collection"]), scope_companies=list(COHORT))


def _recovered(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    return history.recover_reported_history(**kwargs)


def test_completed_recovery_reuses_current_bytes_without_detailed_callback(tmp_path, monkeypatch):
    root = _recovered(tmp_path, monkeypatch)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", lambda self: pytest.fail("detailed records decoded again"))
    verify_financial_history_source(root)


@pytest.mark.parametrize("defect", ["payload", "receipt", "missing_receipt", "pass_report", "extra", "alias"])
def test_completed_recovery_reuse_rejects_changed_proof_payload_and_inventory(tmp_path, monkeypatch, defect):
    root = _recovered(tmp_path, monkeypatch)
    reader = history.HistoryPublicationReader(root)
    if defect in {"payload", "alias"}:
        path = root / reader.manifest["tables"][0]["files"]["cells"]["path"]
        if defect == "payload":
            path.write_bytes(path.read_bytes() + b"tampered")
        else:
            outside = tmp_path / "outside.parquet"; path.rename(outside); path.symlink_to(outside)
    elif defect == "extra":
        (root / "unexpected.bin").write_bytes(b"unexpected")
    elif defect == "pass_report":
        marker = next(root.parent.glob(".history-recovery-*"))
        (marker / "verification_report.json").write_text('{"status":"FAIL"}')
    else:
        path = root.parent / "reported_recovery_receipt.json"
        if defect == "missing_receipt":
            path.unlink()
        else:
            payload = json.loads(path.read_text()); payload["status"] = "NOT_READY"; write_json(path, payload)
    with pytest.raises(ValueError):
        verify_financial_history_source(root)


def test_non_recovery_does_not_trust_an_arbitrary_ready_marker(tmp_path, monkeypatch):
    root = tmp_path / "unaccepted"
    info = {**history._write_records(root / "cells.parquet", ({"nested": [1]},)), "path": "cells.parquet"}
    write_json(root / "history_manifest.json", {"version": history.HISTORY_VERSION, "tables": [{"files": {"cells": info}}]})
    calls = []
    original = history.HistoryPublicationReader.verify_all
    def verify(reader):
        calls.append(True); original(reader)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", verify)
    verify_financial_history_source(root)
    assert calls == [True]
    (root / "cells.parquet").write_bytes(b"invalid")
    with pytest.raises(ValueError):
        verify_financial_history_source(root)


def test_selection_config_defaults_preserve_legacy_and_reject_unsafe_declarations():
    with pytest.raises(ValueError):
        selection_declaration({"path": "relative", "sha256": "0" * 64})
    with pytest.raises(ValueError):
        selection_declaration({"path": "/tmp/../unsafe", "sha256": "0" * 64})


def test_financial_status_reuses_completed_proof_while_default_keeps_detailed(tmp_path, monkeypatch):
    prepared = _publish_identity_inputs(tmp_path / "inputs", monkeypatch)
    collection = Path(prepared.paths["collection"])
    company_root = collection.parent / "companies/FIVE"
    plan = json.loads((company_root / "plan.json").read_text())
    intake = company_root / "intake/history_intake.json"
    with monkeypatch.context() as context:
        kwargs, proof = _recovery_fixture(tmp_path / "recovery", context)
        stage = kwargs["staged_publication"]
        manifest_path = stage / "history_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        old_cik = manifest["tables"][0]["cik"]
        new_cik = COHORT[0]["cik"]
        for tables in (manifest["tables"], proof["tables"]):
            for table in tables:
                table.update(cik=new_cik, ticker="FIVE")
                for info in table["files"].values():
                    info["path"] = info["path"].replace(old_cik, new_cik)
        (stage / old_cik).rename(stage / new_cik)
        log = Path(proof["source_execution_log"]["path"])
        log.write_text(log.read_text().replace("EXAMPLE", "FIVE"))
        proof["source_execution_log"]["sha256"] = sha256_file(log)
        manifest.update(plan=plan, source_intake=str(intake))
        write_json(manifest_path, manifest)
        proof.update(plan=plan, staged_manifest_sha256=sha256_file(manifest_path), intake_sha256=sha256_file(intake))
        report = Path(proof["verification_report"]["path"])
        write_json(report, _full_report(proof, stage))
        proof["verification_report"]["sha256"] = sha256_file(report)
        write_json(kwargs["attestation"], proof)
        kwargs.update(intake_manifest=intake, expected_attestation_sha256=sha256_file(kwargs["attestation"]))
        publication = history.recover_reported_history(**kwargs)
    marker = company_root / "build_manifest.json"
    build = json.loads(marker.read_text())
    manifest_path = publication / "history_manifest.json"
    recovered_payload = json.loads(manifest_path.read_text())
    build.update(output_root=str(publication.parent), publication=str(publication), history_manifest=str(manifest_path),
                 history_manifest_sha256=sha256_file(manifest_path), declared_files=closure._history_declarations(recovered_payload))
    write_json(marker, build)
    calls = []
    original = history.HistoryPublicationReader.verify_all
    def observed(reader):
        calls.append(str(reader.root)); original(reader)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", observed)
    financial = operations.read_universe_status(manifest_path=collection, validation_mode="financial_sources")
    assert next(row for row in financial.companies if row.ticker == "FIVE").state == "READY"
    assert calls == []
    verify_financial_history_source(publication)
    assert calls == []
    default = operations.read_universe_status(manifest_path=collection)
    assert next(row for row in default.companies if row.ticker == "FIVE").state == "READY"
    assert calls == [str(publication)]
    # Hash-only status still checks every current payload byte.
    file = publication / recovered_payload["tables"][0]["files"]["cells"]["path"]
    file.write_bytes(file.read_bytes() + b"changed")
    rejected = operations.read_universe_status(manifest_path=collection, validation_mode="financial_sources")
    assert next(row for row in rejected.companies if row.ticker == "FIVE").state == "BUILD_FAILED"


def test_financial_status_mode_does_not_accept_unknown_validation_mode(tmp_path):
    with pytest.raises(ValueError, match="validation mode"):
        operations.read_universe_status(manifest_path=tmp_path / "missing.json", validation_mode="skip")
