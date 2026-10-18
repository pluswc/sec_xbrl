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
from sec_xbrl import history
from sec_xbrl.screening import dataset_v3, metric_identity
from sec_xbrl.screening import verified_source_closure as closure
from sec_xbrl.screening.common import canonical_json, digest_value, sha256_file
from tests.screening.test_generic_metric_identity_integration import (
    _install_intake,
    _publish_identity_inputs,
)
from tests.unit.test_history_recovery import _recovery_fixture
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


def _install_synthetic_v3_capability_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, destination_name: str
) -> tuple[Path, Path, closure._Snapshot]:
    annual_root = tmp_path / "v3-annual"
    quarter_root = tmp_path / "v3-quarter"
    annual_root.mkdir()
    quarter_root.mkdir()
    annual_manifest_path = annual_root / "screening_dataset_manifest.json"
    quarter_manifest_path = quarter_root / "quarterly_screening_metric_manifest.json"
    annual_manifest_path.write_text(
        canonical_json(
            {
                "config": {
                    "identity_source": {
                        "kind": "GENERIC_METRIC_IDENTITY_ATTESTATION"
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    quarter_manifest_path.write_text("{}\n", encoding="utf-8")
    config_path = tmp_path / f"{destination_name}-config.json"
    config = {
        "schema_version": dataset_v3.CONFIG_VERSION,
        "dataset_id": "synthetic-v3-source-closure",
        "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
        "annual_dataset_root": str(annual_root),
        "annual_manifest_sha256": sha256_file(annual_manifest_path),
        "quarterly_metric_root": str(quarter_root),
        "quarterly_manifest_sha256": sha256_file(quarter_manifest_path),
    }
    config_path.write_text(canonical_json(config) + "\n", encoding="utf-8")
    annual = SimpleNamespace(
        root=annual_root,
        publication_id="synthetic-annual-v2",
        companies=[{"ticker": "FIVE", "cik": "0000000123"}],
        manifest={"sources": {"metadata": {"publication_id": "synthetic-metadata"}}},
        metadata=[],
        metric_definitions=[],
        metric_support=[],
        observations=[],
    )
    quarter = SimpleNamespace(
        root=quarter_root,
        publication_id="synthetic-quarterly",
        manifest={
            "financial_as_of": "2026-10-10",
            "universe": {"ciks": ["0000000123"]},
        },
        definitions=[],
        support=[],
        observations=[],
        period_inventory=[],
    )
    snapshot = closure._Snapshot((), (), (), {})

    def issue_capability(
        *,
        config_path: Path,
        config: dict[str, object],
        annual_root: Path,
        quarter_root: Path,
        destination: Path,
    ):
        capability = closure._issue(
            operation=closure._V3,
            destination=destination,
            config_path=config_path,
            config=config,
            expected_payload={},
            parent_payload=closure._v3_parent_payload(annual, quarter),
            snapshot=snapshot,
        )
        return annual, quarter, capability

    monkeypatch.setattr(dataset_v3, "_verify_v3_sources_once", issue_capability)
    monkeypatch.setattr(dataset_v3, "_verify_parent_binding", lambda *_: None)
    return config_path, tmp_path / destination_name, snapshot


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
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    destination = tmp_path / "published"
    snapshot = closure._Snapshot((), (), (), {})
    capability = closure._issue(
        operation=closure._IDENTITY,
        destination=destination,
        config_path=config_path,
        config={},
        expected_payload={},
        parent_payload=None,
        snapshot=snapshot,
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
    staging.mkdir()
    record = closure._lookup(capability, closure._IDENTITY, destination)
    closure._consume_and_rename(capability, record, staging, destination)
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
    config_path, destination, snapshot = _install_synthetic_v3_capability_fixture(
        tmp_path, monkeypatch, destination_name="late-v3-stage"
    )

    def mutate_stage_then_return_snapshot(*_args: object, **_kwargs: object):
        staging = next(tmp_path.glob(".late-v3-stage.partial-*"))
        manifest_path = staging / dataset_v3.MANIFEST
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["dataset_id"] = "FORGED_AFTER_STAGE_CHECK"
        manifest_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(closure, "_v3_snapshot", mutate_stage_then_return_snapshot)
    with pytest.raises(ValueError, match="staged publication bytes differ"):
        dataset_v3.publish_screening_dataset_v3(config_path, destination)
    assert not destination.exists()


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
    config_path, destination, _snapshot = _install_synthetic_v3_capability_fixture(
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
        dataset_v3.publish_screening_dataset_v3(config_path, destination)
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
