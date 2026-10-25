from __future__ import annotations

import copy
import json
import os
import pickle
import shutil
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import sec_xbrl
from sec_xbrl import collection_operations, history
from sec_xbrl.metrics.quarterly_screening import publish_quarterly_screening_metrics
from sec_xbrl.metrics.screening import MANIFEST as METRIC_MANIFEST
from sec_xbrl.metrics.screening import publish_screening_metrics
from sec_xbrl.screening import dataset_v3, metric_identity
from sec_xbrl.screening import verified_source_closure as closure
from sec_xbrl.screening.common import canonical_json, digest_value, sha256_file
from sec_xbrl.screening.dataset import GENERIC_IDENTITY_SOURCE_KIND
from sec_xbrl.screening.dataset_v2 import (
    EXPLICIT_IDENTITY_CONFIG_VERSION,
    publish_screening_dataset_v2,
)
from sec_xbrl.screening.quarterly import MANIFEST as QUARTERLY_MANIFEST
from tests.screening import test_generic_metric_identity_integration as identity_fixture
from tests.screening.test_generic_metric_identity_integration import (
    _install_intake,
    _publish_identity_inputs,
)
from tests.unit.test_history_recovery import _full_report, _recovery_fixture
from tests.unit.test_source_bindings import _build_ready_histories


def _owned_package_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SimpleNamespace, SimpleNamespace]:
    root = tmp_path / "sec_xbrl"
    shutil.copytree(
        Path(sec_xbrl.__file__).parent,
        root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    package_path = root / "__init__.py"
    module_path = root / "analysis.py"
    package = SimpleNamespace(
        __file__=str(package_path), __spec__=SimpleNamespace(origin=str(package_path))
    )
    module = SimpleNamespace(
        __file__=str(module_path), __spec__=SimpleNamespace(origin=str(module_path))
    )
    original_import = closure.importlib.import_module

    def import_owned(name: str):
        if name == "sec_xbrl":
            return package
        if name == "sec_xbrl.analysis":
            return module
        return original_import(name)

    monkeypatch.setattr(closure.importlib, "import_module", import_owned)
    monkeypatch.setattr(
        closure,
        "_loaded_package_modules",
        lambda: (("sec_xbrl", package), ("sec_xbrl.analysis", module)),
    )
    return root, package, module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _prepare_real_v3_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, destination_name: str
) -> SimpleNamespace:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    metric_config = tmp_path / "metric-config.json"
    _write_json(
        metric_config,
        {
            "schema_version": "screening-metric-config-v2",
            "financial_as_of": "2026-10-10",
            "identity_source": {
                "kind": GENERIC_IDENTITY_SOURCE_KIND,
                "root": str(prepared.identity.root),
                "manifest_sha256": sha256_file(prepared.identity.manifest_path),
            },
            "companies": [
                {
                    "ticker": "FIVE",
                    "cik": "0000000123",
                    "analysis_root": str(prepared.annual),
                    "analysis_manifest_sha256": sha256_file(
                        prepared.annual / "analysis_manifest.json"
                    ),
                    "input_years": [2021, 2022, 2023, 2024, 2025],
                    "display_years": [2022, 2023, 2024, 2025],
                }
            ],
        },
    )
    metrics = publish_screening_metrics(metric_config, tmp_path / "metrics")
    annual_config = tmp_path / "annual-v2-config.json"
    _write_json(
        annual_config,
        {
            "schema_version": EXPLICIT_IDENTITY_CONFIG_VERSION,
            "dataset_id": "single-pass-v3-fixture",
            "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
            "financial_as_of": "2026-10-10",
            "metric_root": str(metrics.root),
            "metric_manifest_sha256": sha256_file(metrics.root / METRIC_MANIFEST),
            "identity_source": {
                "kind": GENERIC_IDENTITY_SOURCE_KIND,
                "root": str(prepared.identity.root),
                "manifest_sha256": sha256_file(prepared.identity.manifest_path),
            },
        },
    )
    annual = publish_screening_dataset_v2(annual_config, tmp_path / "annual-v2")
    quarter_config = tmp_path / "quarter-config.json"
    _write_json(
        quarter_config,
        {
            "schema_version": "quarterly-screening-metric-config-v1",
            "financial_as_of": "2026-10-10",
            "source_commit_sha": "f" * 40,
            "annual_metric_root": str(metrics.root),
            "annual_metric_manifest_sha256": sha256_file(
                metrics.root / METRIC_MANIFEST
            ),
            "companies": [
                {
                    "ticker": "FIVE",
                    "cik": "0000000123",
                    "analysis_root": str(prepared.quarterly),
                    "analysis_manifest_sha256": sha256_file(
                        prepared.quarterly / "analysis_manifest.json"
                    ),
                }
            ],
        },
    )
    quarter = publish_quarterly_screening_metrics(
        quarter_config, tmp_path / "quarter-metrics"
    )
    config_path = tmp_path / f"{destination_name}-config.json"
    config = {
        "schema_version": dataset_v3.CONFIG_VERSION,
        "dataset_id": "synthetic-v3-source-closure",
        "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
        "annual_dataset_root": str(annual.root),
        "annual_manifest_sha256": sha256_file(annual.manifest_path),
        "quarterly_metric_root": str(quarter.root),
        "quarterly_manifest_sha256": sha256_file(
            quarter.root / QUARTERLY_MANIFEST
        ),
    }
    _write_json(config_path, config)
    return SimpleNamespace(
        config_path=config_path,
        config=config,
        annual_root=annual.root,
        quarter_root=quarter.root,
        destination=tmp_path / destination_name,
    )


def _build_fifty_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    original = identity_fixture._mixed_v2_fixture_at_financial_cutoff

    def fifty(root: Path) -> dict[str, object]:
        paths = original(root)
        payload = json.loads((root / "mixed-config.json").read_text(encoding="utf-8"))
        plans = {
            ticker: root / "plans" / f"{ticker}.json" for ticker in ("FIVE", "SIX")
        }
        template = (root / "plans/SIX.json").read_text(encoding="utf-8")
        for index in range(48):
            ticker = f"OWN{index:02d}"
            cik = f"{1000 + index:010d}"
            plan = root / "plans" / f"{ticker}.json"
            plan.write_text(
                template.replace("SIX", ticker).replace("0000000456", cik),
                encoding="utf-8",
            )
            plans[ticker] = plan
            payload["companies"].append(
                {"ticker": ticker, "cik": cik, "groups": ["fixture"]}
            )
        config = root / "fifty-config.json"
        _write_json(config, payload)
        collection = collection_operations.prepare_universe(
            config_path=config,
            run_root=root / "fifty-run",
            existing_plans=plans,
        )
        paths["collection"] = collection
        _install_intake(paths, "FIVE")
        _install_intake(paths, "SIX")
        _build_ready_histories(paths, root, monkeypatch, selected_tickers=("SIX",))
        return paths

    with monkeypatch.context() as context:
        context.setattr(
            identity_fixture, "_mixed_v2_fixture_at_financial_cutoff", fifty
        )
        return identity_fixture._publish_identity_inputs(tmp_path, monkeypatch)


def test_collector_rejects_path_role_inventory_and_byte_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"ready":true}\n', encoding="utf-8")
    collector = closure._Collector()
    collector.file(source, "CONTROL", control=True)
    with pytest.raises(ValueError, match="duplicate source closure role"):
        collector.file(source, "CONTROL")

    linked = tmp_path / "linked.json"
    linked.symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        closure._Collector().file(linked, "LINK")
    with pytest.raises(ValueError, match="traversal"):
        closure._Collector().file(tmp_path / "child/../source.json", "TRAVERSAL")

    inventory = tmp_path / "inventory"
    inventory.mkdir()
    (inventory / "declared").write_text("declared", encoding="utf-8")
    with pytest.raises(ValueError, match="file set changed"):
        closure._Collector().inventory(
            inventory, "INVENTORY", expected_files={"missing"}
        )
    (inventory / "extra").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file set changed"):
        closure._Collector().inventory(
            inventory, "INVENTORY", expected_files={"declared"}
        )

    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("primary.htm", b"primary")
    with pytest.raises(ValueError, match="missing or duplicated"):
        closure._Collector().zip_member(
            archive, "missing.htm", "PRIMARY", archive_role="PACKAGE"
        )
    with pytest.raises(ValueError, match="unsafe"):
        closure._Collector().zip_member(
            archive, "../primary.htm", "PRIMARY", archive_role="PACKAGE"
        )

    unstable = tmp_path / "unstable"
    unstable.write_bytes(b"a" * (2 * 1024 * 1024))
    original_read = closure.os.read
    mutated = False

    def mutate_after_first_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        data = original_read(fd, size)
        if data and not mutated:
            mutated = True
            unstable.write_bytes(b"changed")
        return data

    monkeypatch.setattr(closure.os, "read", mutate_after_first_read)
    with pytest.raises(ValueError, match="changed while hashing"):
        closure._Collector().file(unstable, "UNSTABLE")


def test_capability_is_process_local_single_use_and_unserializable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    config_path = prepared.identity_config
    config = metric_identity._validate_config(
        json.loads(config_path.read_text(encoding="utf-8"))
    )
    destination = tmp_path / "published"
    _sources, capability = closure._verify_identity_sources_once(
        destination=destination,
        config_path=config_path,
        config=config,
    )
    with pytest.raises(TypeError, match="issuer-only"):
        closure._VerifiedSourceClosure(object(), "nonce", closure._IDENTITY)
    with pytest.raises(TypeError, match="copied"):
        copy.copy(capability)
    with pytest.raises(TypeError, match="copied"):
        copy.deepcopy(capability)
    with pytest.raises(TypeError, match="serialized"):
        pickle.dumps(capability)

    forged = object.__new__(closure._VerifiedSourceClosure)
    for name in ("nonce", "operation", "pid"):
        setattr(
            forged,
            f"_VerifiedSourceClosure__{name}",
            getattr(capability, f"_VerifiedSourceClosure__{name}"),
        )
    with pytest.raises(ValueError, match="invalid"):
        closure._lookup(forged, closure._IDENTITY, destination)
    with pytest.raises(ValueError, match="invalid"):
        closure._lookup(capability, closure._V3, destination)
    with pytest.raises(ValueError, match="invalid"):
        closure._lookup(capability, closure._IDENTITY, tmp_path / "wrong")

    read_fd, write_fd = os.pipe()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*multi-threaded.*fork", category=DeprecationWarning
        )
        pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            closure._lookup(capability, closure._IDENTITY, destination)
        except ValueError:
            os.write(write_fd, b"REJECTED")
            os._exit(0)
        os._exit(70)
    os.close(write_fd)
    child_result = os.read(read_fd, 64)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert child_result == b"REJECTED"

    staging = tmp_path / "staging"
    shutil.copytree(prepared.identity.root, staging)
    closure._publish_identity(capability, staging=staging, destination=destination)
    with pytest.raises(ValueError, match="already consumed"):
        closure._lookup(capability, closure._IDENTITY, destination)


def test_recovery_gate_runs_before_private_hash_and_allows_receipt_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _proof = _recovery_fixture(tmp_path, monkeypatch)
    publication = history.recover_reported_history(**kwargs)
    root = publication.parent
    receipt = root / "reported_recovery_receipt.json"
    temporary = next(root.glob(".receipt.partial-*"))
    assert receipt.stat().st_ino == temporary.stat().st_ino

    collector = closure._Collector()
    closure._add_history(
        collector, publication, "RECOVERED_HISTORY", check_recovery=True
    )
    roles = {
        role for record in collector.snapshot().files for role in record.roles
    }
    assert any("RECOVERY_GATE_FILE" in role for role in roles)
    assert any("transaction.json" in role for role in roles)
    assert any("attestation.json" in role for role in roles)
    assert any("verification_report.json" in role for role in roles)
    retained = {
        role for role in roles if "RECOVERED_HISTORY:RETAINED_PHYSICAL:" in role
    }
    assert len(retained) == 8
    assert any("history_manifest.json.partial" in role for role in retained)
    assert any("quarter-spill.records" in role for role in retained)

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["status"] = "BUILDING"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    private_hash_calls = 0
    original_read_stable = closure._read_stable

    def counted_read_stable(*args: object, **kwargs: object):
        nonlocal private_hash_calls
        private_hash_calls += 1
        return original_read_stable(*args, **kwargs)

    monkeypatch.setattr(closure, "_read_stable", counted_read_stable)
    with pytest.raises(ValueError, match="NOT_READY"):
        closure._add_history(
            closure._Collector(),
            publication,
            "BUILDING_HISTORY",
            check_recovery=True,
        )
    assert private_hash_calls == 0


@pytest.mark.parametrize("status_only", (False, True))
def test_integrated_recovery_gate_before_any_history_private_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_only: bool
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    if status_only:
        _install_intake(prepared.paths, "SIX")
        histories = _build_ready_histories(
            prepared.paths, tmp_path, monkeypatch, selected_tickers=("SIX",)
        )
        history_root = histories["SIX"].parent
    else:
        history_root = prepared.histories["FIVE"].parent
    (history_root / ".history-recovery-invalid").mkdir()
    private_history_reads: list[str] = []
    original_read_stable = closure._read_stable

    def counted_read_stable(path: Path, **kwargs: object):
        if path == history_root / "history_manifest.json" or history_root in path.parents:
            private_history_reads.append(str(path))
        return original_read_stable(path, **kwargs)

    monkeypatch.setattr(closure, "_read_stable", counted_read_stable)
    with pytest.raises(ValueError, match="NOT_READY"):
        metric_identity.publish_generic_metric_identity(
            prepared.identity_config, tmp_path / f"invalid-gate-{status_only}"
        )
    assert private_history_reads == []


def test_status_only_recovered_history_pins_complete_receipt_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _proof = _recovery_fixture(tmp_path, monkeypatch)
    publication = history.recover_reported_history(**kwargs)
    manifest_path = publication / "history_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    build = {
        "status": "READY",
        "publication": str(publication),
        "history_manifest": str(manifest_path),
        "declared_files": closure._history_declarations(manifest),
    }
    first = closure._Collector()
    closure._add_status_history(first, build, "STATUS_HISTORY:NONSCOPED")
    receipt = publication.parent / "reported_recovery_receipt.json"
    receipt.write_bytes(receipt.read_bytes() + b"\n")
    history._check_recovery_access(publication)
    second = closure._Collector()
    closure._add_status_history(second, build, "STATUS_HISTORY:NONSCOPED")
    assert first.snapshot().fingerprint != second.snapshot().fingerprint


def test_integrated_fifty_parent_status_recovery_receipt_mutation_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _build_fifty_identity(tmp_path / "inputs", monkeypatch)
    collection = Path(prepared.paths["collection"])
    company_root = collection.parent / "companies/SIX"
    plan = json.loads((company_root / "plan.json").read_text(encoding="utf-8"))
    intake = company_root / "intake/history_intake.json"
    with monkeypatch.context() as context:
        kwargs, proof = _recovery_fixture(tmp_path / "recovery", context)
        stage = kwargs["staged_publication"]
        manifest_path = stage / "history_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_cik = manifest["tables"][0]["cik"]
        new_cik = plan["companies"][0]["cik"]
        for tables in (manifest["tables"], proof["tables"]):
            for table in tables:
                table["cik"] = new_cik
                table["ticker"] = "SIX"
                for info in table["files"].values():
                    info["path"] = info["path"].replace(old_cik, new_cik)
        (stage / old_cik).rename(stage / new_cik)
        execution_log = Path(proof["source_execution_log"]["path"])
        execution_log.write_text(
            execution_log.read_text(encoding="utf-8").replace("EXAMPLE", "SIX"),
            encoding="utf-8",
        )
        proof["source_execution_log"]["sha256"] = history._sha256_file(
            execution_log
        )
        manifest["plan"] = plan
        manifest["source_intake"] = str(intake)
        history._write_json(manifest_path, manifest)
        proof["plan"] = plan
        proof["staged_manifest_sha256"] = history._sha256_file(manifest_path)
        proof["intake_sha256"] = history._sha256_file(intake)
        report = Path(proof["verification_report"]["path"])
        history._write_json(report, _full_report(proof, stage))
        proof["verification_report"]["sha256"] = history._sha256_file(report)
        history._write_json(kwargs["attestation"], proof)
        kwargs["intake_manifest"] = intake
        kwargs["expected_attestation_sha256"] = history._sha256_file(
            kwargs["attestation"]
        )
        publication = history.recover_reported_history(**kwargs)

    marker = company_root / "build_manifest.json"
    build = json.loads(marker.read_text(encoding="utf-8"))
    recovered_manifest = publication / "history_manifest.json"
    recovered_payload = json.loads(recovered_manifest.read_text(encoding="utf-8"))
    build.update(
        views=recovered_payload["views"],
        output_root=str(publication.parent),
        publication=str(publication),
        history_manifest=str(recovered_manifest),
        history_manifest_sha256=history._sha256_file(recovered_manifest),
        declared_files=closure._history_declarations(recovered_payload),
    )
    _write_json(marker, build)
    status = collection_operations.read_universe_status(manifest_path=collection)
    states = {row.ticker: row.state for row in status.companies}
    assert len(states) == 50
    assert states["SIX"] == "READY"
    history._check_recovery_access(publication)

    # The completed recovery consumer keeps its accepted private diagnostic
    # artifacts, while its declared public payload remains fully verified.
    validation = history.HistoryPublicationReader(publication).validate(
        state_root=tmp_path / "recovery-validation-state"
    )
    assert validation.level == "DETAILED"
    assert validation.reason == "COMPLETED_RECOVERY_COMPATIBILITY"
    public_file = publication / recovered_payload["tables"][0]["files"]["cells"]["path"]
    public_bytes = public_file.read_bytes()
    public_file.write_bytes(public_bytes + b"tampered")
    with pytest.raises(ValueError, match="integrity mismatch"):
        history.HistoryPublicationReader(publication).validate(
            state_root=tmp_path / "tampered-recovery-validation-state"
        )
    public_file.write_bytes(public_bytes)

    # A sibling recovery publication is not the gate-bound consumer root and
    # therefore receives the ordinary exact-inventory policy.
    reported_publication = publication.parent / "reported-panels"
    foreign = reported_publication / "foreign.bin"
    foreign.write_bytes(b"foreign")
    with pytest.raises(ValueError, match="structure anomaly"):
        history.HistoryPublicationReader(reported_publication).validate(
            state_root=tmp_path / "reported-validation-state"
        )
    foreign.unlink()
    config = metric_identity._validate_config(
        json.loads(prepared.identity_config.read_text(encoding="utf-8"))
    )
    metric_identity._verify_configured_sources(config)
    receipt = publication.parent / "reported_recovery_receipt.json"
    original_verify = metric_identity._verify_configured_sources

    def verify_then_mutate(*args: object, **kwargs: object):
        result = original_verify(*args, **kwargs)
        receipt.write_bytes(receipt.read_bytes() + b"\n")
        history._check_recovery_access(publication)
        return result

    monkeypatch.setattr(
        metric_identity, "_verify_configured_sources", verify_then_mutate
    )
    destination = tmp_path / "rejected-receipt-change"
    with pytest.raises(ValueError, match="post-verification source closure changed"):
        metric_identity.publish_generic_metric_identity(
            prepared.identity_config, destination
        )
    assert not destination.exists()


def test_unverified_record_constructor_cannot_mint_publish_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    _write_json(config_path, {})
    destination = tmp_path / "forged"
    deep_calls = 0
    original_verify = metric_identity._verify_configured_sources

    def counted_verify(*args: object, **kwargs: object):
        nonlocal deep_calls
        deep_calls += 1
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(metric_identity, "_verify_configured_sources", counted_verify)
    before = dict(closure._REGISTRY)
    nonce, capability, _record = closure._unregistered_record(
        operation=closure._IDENTITY,
        destination=destination,
        config_path=config_path,
        config={},
        expected_payload={"metadata": {"publication_id": "FORGED_NOT_DEEP_VERIFIED"}},
        parent_payload=None,
        snapshot=closure._Snapshot((), (), (), {}),
    )
    assert nonce not in closure._REGISTRY
    assert closure._REGISTRY == before
    assert not hasattr(closure, "_issue")
    assert not hasattr(closure, "_consume_and_rename")
    assert not hasattr(closure, "_finalize_identity")
    assert not hasattr(closure, "_finalize_v3")
    staging = tmp_path / "stage"
    staging.mkdir()
    with pytest.raises(ValueError, match="invalid or already consumed"):
        closure._publish_identity(
            capability, staging=staging, destination=destination
        )
    assert deep_calls == 0
    assert not destination.exists()


def test_fixed_operation_publishers_are_sole_finalization_boundaries() -> None:
    assert not hasattr(closure, "_finalize_identity")
    assert not hasattr(closure, "_finalize_v3")
    assert callable(closure._publish_identity)
    assert callable(closure._publish_v3)


def test_identity_capability_cannot_publish_arbitrary_staged_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    config = metric_identity._validate_config(
        json.loads(prepared.identity_config.read_text(encoding="utf-8"))
    )
    destination = tmp_path / "bad-identity-output"
    _sources, capability = closure._verify_identity_sources_once(
        config_path=prepared.identity_config,
        config=config,
        destination=destination,
    )
    staging = tmp_path / "bad-identity-stage"
    staging.mkdir()
    _write_json(staging / metric_identity.MANIFEST_NAME, {"forged": True})
    with pytest.raises(ValueError, match="staged publication bytes differ"):
        closure._publish_identity(
            capability, staging=staging, destination=destination
        )
    with pytest.raises(ValueError, match="already consumed"):
        closure._lookup(capability, closure._IDENTITY, destination)
    with pytest.raises(ValueError, match="already consumed"):
        closure._publish_identity(
            capability, staging=staging, destination=destination
        )
    assert not destination.exists()


def test_v3_capability_cannot_publish_arbitrary_staged_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare_real_v3_inputs(
        tmp_path, monkeypatch, destination_name="bad-v3-output"
    )
    _annual, _quarter, capability = closure._verify_v3_sources_once(
        config_path=prepared.config_path,
        config=prepared.config,
        annual_root=prepared.annual_root,
        quarter_root=prepared.quarter_root,
        destination=prepared.destination,
    )
    staging = tmp_path / "bad-v3-stage"
    staging.mkdir()
    _write_json(staging / dataset_v3.MANIFEST, {"forged": True})
    with pytest.raises(ValueError, match="staged publication bytes differ"):
        closure._publish_v3(
            capability, staging=staging, destination=prepared.destination
        )
    with pytest.raises(ValueError, match="already consumed"):
        closure._lookup(capability, closure._V3, prepared.destination)
    with pytest.raises(ValueError, match="already consumed"):
        closure._publish_v3(
            capability, staging=staging, destination=prepared.destination
        )
    assert not prepared.destination.exists()


def test_stage_mutation_during_final_source_rehash_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    destination = tmp_path / "late-stage"
    original_snapshot = closure._identity_snapshot
    snapshots = 0

    def snapshot_then_mutate(*args: object, **kwargs: object):
        nonlocal snapshots
        result = original_snapshot(*args, **kwargs)
        snapshots += 1
        if snapshots == 4:
            staging = next(tmp_path.glob(".late-stage.partial-*"))
            manifest_path = staging / metric_identity.MANIFEST_NAME
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["readiness"] = "FORGED_AFTER_STAGE_CHECK"
            manifest_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        return result

    monkeypatch.setattr(closure, "_identity_snapshot", snapshot_then_mutate)
    with pytest.raises(ValueError, match="staged publication bytes differ"):
        metric_identity.publish_generic_metric_identity(
            prepared.identity_config, destination
        )
    assert snapshots == 4
    assert not destination.exists()


def test_v3_stage_mutation_during_final_source_rehash_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare_real_v3_inputs(
        tmp_path, monkeypatch, destination_name="late-v3-stage"
    )
    original_snapshot = closure._v3_snapshot
    snapshots = 0

    def snapshot_then_mutate(*args: object, **kwargs: object):
        nonlocal snapshots
        result = original_snapshot(*args, **kwargs)
        snapshots += 1
        if snapshots == 4:
            staging = next(tmp_path.glob(".late-v3-stage.partial-*"))
            manifest_path = staging / dataset_v3.MANIFEST
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["dataset_id"] = "FORGED_AFTER_STAGE_CHECK"
            manifest_path.write_text(
                canonical_json(payload) + "\n", encoding="utf-8"
            )
        return result

    monkeypatch.setattr(closure, "_v3_snapshot", snapshot_then_mutate)
    with pytest.raises(ValueError, match="staged publication bytes differ"):
        dataset_v3.publish_screening_dataset_v3(
            prepared.config_path, prepared.destination
        )
    assert snapshots == 4
    assert not prepared.destination.exists()


def test_identity_capability_discarded_when_stage_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    original_mkdir = Path.mkdir
    old_registry = set(closure._REGISTRY)

    def fail_stage(self: Path, *args: object, **kwargs: object):
        if self.name.startswith(".failed-stage.partial-"):
            raise OSError("injected identity stage mkdir failure")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_stage)
    with pytest.raises(OSError, match="identity stage mkdir failure"):
        metric_identity.publish_generic_metric_identity(
            prepared.identity_config, tmp_path / "failed-stage"
        )
    assert set(closure._REGISTRY) == old_registry


def test_v3_capability_discarded_when_stage_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare_real_v3_inputs(
        tmp_path, monkeypatch, destination_name="failed-v3-stage"
    )
    original_mkdir = Path.mkdir
    old_registry = set(closure._REGISTRY)

    def fail_stage(self: Path, *args: object, **kwargs: object):
        if self.name.startswith(".failed-v3-stage.partial-"):
            raise OSError("injected v3 stage mkdir failure")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_stage)
    with pytest.raises(OSError, match="v3 stage mkdir failure"):
        dataset_v3.publish_screening_dataset_v3(
            prepared.config_path, prepared.destination
        )
    assert set(closure._REGISTRY) == old_registry


def test_identity_closure_covers_status_only_and_all_source_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    _install_intake(prepared.paths, "SIX")
    _build_ready_histories(
        prepared.paths, tmp_path, monkeypatch, selected_tickers=("SIX",)
    )
    raw_config = json.loads(prepared.identity_config.read_text(encoding="utf-8"))
    config = metric_identity._validate_config(raw_config)
    snapshot = closure._identity_snapshot(prepared.identity_config, config)
    roles = {role for record in snapshot.files for role in record.roles}
    member_roles = {record.role for record in snapshot.members}

    required_fragments = {
        "COLLECTION_MANIFEST",
        "COLLECTION_REQUEST",
        "COLLECTION_PLAN:FIVE",
        "STATUS_BUILD:SIX",
        "STATUS_HISTORY:SIX:MANIFEST",
        "METADATA_DATASET",
        "HISTORY:FIVE:DATA",
        "ANNUAL_ANALYSIS:FIVE:DATA",
        "QUARTER_ANALYSIS:FIVE:DATA",
        "QUALITY_REPORT",
        "SOURCE_BINDING_FILE",
        "SOURCE_INDEX",
        "RAW_MANIFEST",
        "RAW_FACT",
        "RAW_CONCEPT",
        "RAW_CONTEXT",
        "VERIFIER_SOURCE_CODE",
    }
    assert all(any(fragment in role for role in roles) for fragment in required_fragments)
    code_paths = {
        Path(record.path).relative_to(Path(sec_xbrl.__file__).parent).as_posix()
        for record in snapshot.files
        if any("LOCAL_PACKAGE_SOURCE_CODE" in role for role in record.roles)
    }
    assert {
        "filing/sec_inline_transforms.py",
        "facts/layer1.py",
        "filing/company_discovery.py",
        "analytics/axis_timeseries_queries.py",
        "analytics/history_quarters.py",
    } <= code_paths
    assert any("PRIMARY_MEMBER" in role for role in member_roles)

    sources = metric_identity._verify_configured_sources(config)
    identity = {
        "schema_version": metric_identity.VERSION,
        "source_kind": metric_identity.SOURCE_KIND,
        "readiness": "READY",
        "universe_id": config["universe_id"],
        "financial_as_of": config["financial_as_of"],
        "metadata_observation_cutoff": config["metadata_observation_cutoff"],
        "annual_window": copy.deepcopy(config["annual_window"]),
        "global_quarter_spine": copy.deepcopy(config["global_quarter_spine"]),
        "configured_ciks": [row["cik"] for row in config["companies"]],
        "configured_tickers": [row["ticker"] for row in config["companies"]],
        "config": copy.deepcopy(config),
        "config_path": str(prepared.identity_config),
        "config_sha256": closure._sha256(prepared.identity_config),
        **sources,
    }
    expected = {
        **identity,
        "publication_id": "generic-metric-identity-" + digest_value(identity)[:24],
    }
    assert prepared.identity.manifest_path.read_bytes() == (
        canonical_json(expected) + "\n"
    ).encode("utf-8")


def test_local_package_code_rejects_change_during_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _package, _module = _owned_package_imports(tmp_path, monkeypatch)
    target = root / "__init__.py"
    original_read = closure._read_stable
    changed = False

    def mutate_after_first_read(path: Path, **kwargs: object):
        nonlocal changed
        result = original_read(path, **kwargs)
        if path == target and not changed:
            target.write_bytes(target.read_bytes() + b"\n# changed during discovery\n")
            changed = True
        return result

    monkeypatch.setattr(closure, "_read_stable", mutate_after_first_read)
    with pytest.raises(ValueError, match="source closure hash differs"):
        closure._add_source_code(
            closure._Collector(), ("sec_xbrl.analysis",), "OWNED"
        )


@pytest.mark.parametrize("window", ("postdeep", "prefinal"))
@pytest.mark.parametrize("defect", ("missing", "extra", "bytes"))
def test_local_package_code_rejects_pathset_or_bytes_across_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
    defect: str,
) -> None:
    root, _package, _module = _owned_package_imports(tmp_path, monkeypatch)

    def snapshot() -> closure._Snapshot:
        collector = closure._Collector()
        closure._add_source_code(collector, ("sec_xbrl.analysis",), "OWNED")
        return collector.snapshot()

    initial = snapshot()
    if defect == "missing":
        (root / "analytics/history_quarters.py").unlink()
    elif defect == "extra":
        (root / f"extra_{window}.py").write_text("VALUE = 1\n", encoding="utf-8")
    else:
        target = root / "analytics/axis_timeseries_queries.py"
        target.write_bytes(target.read_bytes() + f"\n# {window}\n".encode())
    changed = snapshot()
    with pytest.raises(ValueError, match="source closure changed"):
        closure._require_same_snapshot(initial, changed, f"owned {window}")


@pytest.mark.parametrize("swapped", ("package", "module"))
def test_local_package_code_rejects_origin_outside_bound_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swapped: str
) -> None:
    _root, package, module = _owned_package_imports(tmp_path, monkeypatch)
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    target = package if swapped == "package" else module
    target.__spec__ = SimpleNamespace(origin=str(outside))
    with pytest.raises(
        ValueError, match="source (origin differs|closure module path is unavailable)"
    ):
        closure._add_source_code(
            closure._Collector(), ("sec_xbrl.analysis",), "OWNED"
        )


def test_local_package_code_rejects_loaded_verifier_origin_outside_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, package, module = _owned_package_imports(tmp_path, monkeypatch)
    outside = tmp_path / "outside-company-discovery.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    swapped = SimpleNamespace(
        __file__=str(outside), __spec__=SimpleNamespace(origin=str(outside))
    )
    monkeypatch.setattr(
        closure,
        "_loaded_package_modules",
        lambda: (
            ("sec_xbrl", package),
            ("sec_xbrl.analysis", module),
            ("sec_xbrl.filing.company_discovery", swapped),
        ),
    )
    with pytest.raises(ValueError, match="loaded sec_xbrl module origin differs"):
        closure._add_source_code(
            closure._Collector(), ("sec_xbrl.analysis",), "OWNED"
        )
    assert root != outside.parent


@pytest.mark.parametrize(
    "source_class",
    (
        "config",
        "collection_control",
        "collection_scope",
        "quality",
        "source_binding",
        "history_public",
        "history_retained",
        "metadata",
        "package_zip",
        "primary_member",
        "raw_fact",
        "raw_concept",
        "raw_context",
    ),
)
def test_integrated_identity_rejects_each_source_class_after_deep_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_class: str,
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    config = json.loads(prepared.identity_config.read_text(encoding="utf-8"))
    collection_path = Path(config["collection_manifest"])
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    quality_manifest = json.loads(prepared.quality.manifest_path.read_text(encoding="utf-8"))
    binding_root = Path(quality_manifest["source_binding"]["root"])
    documents_path = binding_root / "source_documents.json"
    documents = json.loads(documents_path.read_text(encoding="utf-8"))["documents"]
    document = documents[0]
    history_root = Path(config["companies"][0]["history_root"])

    if source_class == "history_retained":
        retained = history_root / "history_manifest.json.partial"
        retained.write_bytes((history_root / "history_manifest.json").read_bytes())

    def append(path: Path) -> None:
        path.write_bytes(path.read_bytes() + b"\nmutated")

    def mutation() -> None:
        if source_class == "config":
            append(prepared.identity_config)
        elif source_class == "collection_control":
            append(Path(collection["request_path"]))
        elif source_class == "collection_scope":
            append(collection_path.parent / "companies/FIVE/plan.json")
        elif source_class == "quality":
            append(prepared.quality.report_path)
        elif source_class == "source_binding":
            append(binding_root / "source_bindings.json")
        elif source_class == "history_public":
            manifest = json.loads(
                (history_root / "history_manifest.json").read_text(encoding="utf-8")
            )
            relative = next(iter(manifest["tables"][0]["files"].values()))["path"]
            append(history_root / relative)
        elif source_class == "history_retained":
            append(history_root / "history_manifest.json.partial")
        elif source_class == "metadata":
            metadata_root = Path(config["metadata_root"])
            manifest = json.loads(
                (metadata_root / "company_metadata_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            append(metadata_root / next(iter(manifest["files"])))
        elif source_class == "package_zip":
            append(Path(document["package_path"]))
        elif source_class == "primary_member":
            package_path = Path(document["package_path"])
            with zipfile.ZipFile(package_path) as package:
                members = {name: package.read(name) for name in package.namelist()}
            members[document["primary_document"]] += b"mutated-primary"
            with zipfile.ZipFile(package_path, "w") as package:
                for name, data in members.items():
                    package.writestr(name, data)
        elif source_class == "raw_concept":
            (Path(document["snapshot_root"]) / "concept.parquet").unlink()
        else:
            name = "fact.parquet" if source_class == "raw_fact" else "context.parquet"
            append(Path(document["snapshot_root"]) / name)

    original_verify = metric_identity._verify_configured_sources

    def verify_then_mutate(value: dict[str, object]) -> dict[str, object]:
        result = original_verify(value)
        mutation()
        return result

    with monkeypatch.context() as context:
        context.setattr(
            metric_identity, "_verify_configured_sources", verify_then_mutate
        )
        destination = tmp_path / f"rejected-postdeep-{source_class}"
        with pytest.raises((FileNotFoundError, ValueError)):
            metric_identity.publish_generic_metric_identity(
                prepared.identity_config, destination
            )
    assert not destination.exists()


def test_integrated_identity_rejects_discovery_window_mutation_before_deep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    original_snapshot = closure._identity_snapshot
    original_verify = metric_identity._verify_configured_sources
    snapshots = 0
    deep_calls = 0

    def snapshot_then_mutate(*args: object, **kwargs: object):
        nonlocal snapshots
        result = original_snapshot(*args, **kwargs)
        snapshots += 1
        if snapshots == 1:
            prepared.identity_config.write_bytes(
                prepared.identity_config.read_bytes() + b"\nmutated-discovery"
            )
        return result

    def counted_verify(value: dict[str, object]) -> dict[str, object]:
        nonlocal deep_calls
        deep_calls += 1
        return original_verify(value)

    with monkeypatch.context() as context:
        context.setattr(closure, "_identity_snapshot", snapshot_then_mutate)
        context.setattr(metric_identity, "_verify_configured_sources", counted_verify)
        destination = tmp_path / "rejected-discovery"
        with pytest.raises(ValueError):
            metric_identity.publish_generic_metric_identity(
                prepared.identity_config, destination
            )
    assert deep_calls == 0
    assert not destination.exists()


@pytest.mark.parametrize("mutation", ("staged_bytes", "staged_extra", "source"))
def test_integrated_identity_rejects_mutation_after_staged_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    config = json.loads(prepared.identity_config.read_text(encoding="utf-8"))
    metadata_root = Path(config["metadata_root"])
    metadata_manifest = json.loads(
        (metadata_root / "company_metadata_manifest.json").read_text(encoding="utf-8")
    )
    source_path = metadata_root / next(iter(metadata_manifest["files"]))
    original_write = metric_identity.write_json

    def write_then_mutate(path: Path, value: object) -> None:
        original_write(path, value)
        if path.name != metric_identity.MANIFEST_NAME:
            return
        if mutation == "staged_bytes":
            path.write_bytes(path.read_bytes() + b"mutated-stage")
        elif mutation == "staged_extra":
            (path.parent / "extra.json").write_text("{}\n", encoding="utf-8")
        else:
            source_path.write_bytes(source_path.read_bytes() + b"mutated-source")

    with monkeypatch.context() as context:
        context.setattr(metric_identity, "write_json", write_then_mutate)
        destination = tmp_path / f"rejected-stage-{mutation}"
        with pytest.raises(ValueError):
            metric_identity.publish_generic_metric_identity(
                prepared.identity_config, destination
            )
    assert not destination.exists()


@pytest.mark.parametrize("defect", ("package_swap", "raw_missing", "wrong_roles"))
def test_source_binding_closure_rejects_raw_zip_and_role_defects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    quality_manifest = json.loads(prepared.quality.manifest_path.read_text(encoding="utf-8"))
    root = Path(quality_manifest["source_binding"]["root"])
    documents_path = root / "source_documents.json"
    payload = json.loads(documents_path.read_text(encoding="utf-8"))
    document = payload["documents"][0]
    if defect == "package_swap":
        Path(document["package_path"]).write_bytes(b"not-the-declared-package")
    elif defect == "raw_missing":
        (Path(document["snapshot_root"]) / "fact.parquet").unlink()
    else:
        document["tables"]["dimension.parquet"] = document["tables"].pop(
            "context.parquet"
        )
        documents_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        manifest_path = root / "source_binding_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["source_documents.json"].update(
            sha256=sha256_file(documents_path), size=documents_path.stat().st_size
        )
        manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises((FileNotFoundError, ValueError)):
        closure._add_source_binding(closure._Collector(), root, "TEST")


@pytest.mark.parametrize("defect", ["missing", "extra", "bytes"])
def test_staged_output_is_exact_before_publication(
    tmp_path: Path, defect: str
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    expected = {"schema_version": "fixture", "status": "READY"}
    manifest = staging / "manifest.json"
    if defect != "missing":
        manifest.write_text(canonical_json(expected) + "\n", encoding="utf-8")
    if defect == "extra":
        (staging / "extra.json").write_text("{}\n", encoding="utf-8")
    elif defect == "bytes":
        manifest.write_text('{"status":"BUILDING"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="staged publication"):
        closure._require_exact_output(staging, "manifest.json", expected)
