"""Exact supersession preserves completed parents through public combined APIs."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sec_xbrl import financial_source_compatibility as compat
from sec_xbrl import history
from sec_xbrl.screening.common import digest_value, sha256_file, write_json
from tests.screening.test_financial_source_compatibility import _transition
from tests.screening.test_financial_storage_reuse import COHORT, _pin


def _completed_publications(tmp_path, prepared, registry, old_packet):
    from sec_xbrl.metrics.quarterly_screening import publish_quarterly_screening_metrics
    from sec_xbrl.metrics.screening import publish_screening_metrics
    from sec_xbrl.screening.dataset import GENERIC_IDENTITY_SOURCE_KIND
    from sec_xbrl.screening.dataset_v2 import (
        EXPLICIT_IDENTITY_CONFIG_VERSION,
        publish_screening_dataset_v2,
    )
    from sec_xbrl.screening.metric_identity import publish_generic_metric_identity
    from tests.screening.test_generic_metric_identity_integration import FINANCIAL_AS_OF

    config = json.loads(prepared.identity_config.read_text())
    config.update(quality_root=str(prepared.quality.root),
                  quality_manifest_sha256=sha256_file(prepared.quality.manifest_path),
                  storage_reuse=_pin(registry), source_compatibility=_pin(old_packet))
    identity_config = tmp_path / "preserved-identity-config.json"
    write_json(identity_config, config)
    identity = publish_generic_metric_identity(identity_config, tmp_path / "preserved-identity")
    declaration = {"kind": GENERIC_IDENTITY_SOURCE_KIND, "root": str(identity.root),
                   "manifest_sha256": sha256_file(identity.manifest_path)}
    metrics_config = tmp_path / "preserved-metrics-config.json"
    write_json(metrics_config, {"schema_version": "screening-metric-config-v2",
        "financial_as_of": FINANCIAL_AS_OF, "identity_source": declaration,
        "companies": [{**COHORT[0], "analysis_root": str(prepared.annual),
                       "analysis_manifest_sha256": sha256_file(prepared.annual / "analysis_manifest.json"),
                       "input_years": [2021, 2022, 2023, 2024, 2025],
                       "display_years": [2022, 2023, 2024, 2025]}]})
    metrics = publish_screening_metrics(metrics_config, tmp_path / "preserved-metrics")
    annual_config = tmp_path / "preserved-annual-config.json"
    write_json(annual_config, {"schema_version": EXPLICIT_IDENTITY_CONFIG_VERSION,
        "dataset_id": "preserved-annual", "financial_as_of": FINANCIAL_AS_OF,
        "metric_root": str(metrics.root), "metric_manifest_sha256": sha256_file(metrics.manifest_path),
        "identity_source": declaration})
    annual = publish_screening_dataset_v2(annual_config, tmp_path / "preserved-annual")
    quarter_config = tmp_path / "preserved-quarter-config.json"
    write_json(quarter_config, {"schema_version": "quarterly-screening-metric-config-v1",
        "financial_as_of": FINANCIAL_AS_OF, "source_commit_sha": "f" * 40,
        "annual_metric_root": str(metrics.root),
        "annual_metric_manifest_sha256": sha256_file(metrics.manifest_path),
        "companies": [{**COHORT[0], "analysis_root": str(prepared.quarterly),
                       "analysis_manifest_sha256": sha256_file(prepared.quarterly / "analysis_manifest.json")}]})
    quarterly = publish_quarterly_screening_metrics(quarter_config, tmp_path / "preserved-quarter")
    return {"identity": _pin(identity.manifest_path), "annual_metrics": _pin(metrics.manifest_path),
            "annual_dataset": _pin(annual.manifest_path), "quarterly_metrics": _pin(quarterly.manifest_path)}


def _supersession(tmp_path, monkeypatch, *, public_parents=False):
    prepared, registry, _report, old_path, old, current = _transition(
        tmp_path, monkeypatch, with_quality=public_parents)
    if public_parents:
        completed = _completed_publications(tmp_path, prepared, registry, old_path)
    else:
        completed = {}
        for name in sorted(compat._COMPLETED_PUBLICATIONS):
            path = tmp_path / f"preserved-{name}.json"
            write_json(path, {"fixture_kind": "SYNTHETIC_CONTROL", "name": name})
            completed[name] = _pin(path)
    archive = tmp_path / "source984"
    shutil.copytree(current, archive)
    for name in compat._SUPERSEDING_CHANGES:
        with (current / name).open("a") as stream:
            stream.write("\n# exact synthetic prepared-reader/combined compatibility change\n")
    supersedes = {"packet": _pin(old_path), "source_root": str(archive),
                  "completed_publications": completed}
    histories = [{name: row[name] for name in ("report", "build_manifest", "history_manifest")}
                 for row in old["routine_histories"]]
    value = compat.prepare_source_compatibility_packet(
        origin_source_root=Path(old["origin_source_root"]),
        preserved_controls=old["preserved_controls"] + [completed[name] for name in sorted(completed)],
        routine_histories=histories, supersedes=supersedes)
    assert value["status"] == "PROPOSED"
    value["status"] = "ROOT_APPROVED"
    path = tmp_path / "superseding-compatibility.json"
    write_json(path, value)
    return path, value, old_path, archive, current, completed


def test_exact_supersession_scope_restores_strict_old_reader_and_binds_closure(tmp_path, monkeypatch):
    path, _, old, archive, current, completed = _supersession(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in (old, *[Path(pin["path"]) for pin in completed.values()])}
    with pytest.raises(ValueError, match="inventories"):
        compat.resolve_source_compatibility(_pin(old))
    with compat.use_source_compatibility(_pin(path)) as witness:
        resolved = compat.resolve_source_compatibility(_pin(old))
        assert resolved.declaration == _pin(path)
        assert {pin["path"] for pin in resolved.controls.values()} >= {
            str(path), str(old), str(archive / "history.py"), str(current / "history.py"),
            *[pin["path"] for pin in completed.values()]}
        resolved.require_control(completed["annual_dataset"])
        assert witness.payload["schema_version"] == compat.SUPERSEDING_VERSION
    with pytest.raises(ValueError, match="inventories"):
        compat.resolve_source_compatibility(_pin(old))
    assert {p: sha256_file(p) for p in before} == before


def test_supersession_resets_after_exception_and_isolates_async_context(tmp_path, monkeypatch):
    path, _, old, _, _, _ = _supersession(tmp_path, monkeypatch)
    async def run():
        ready, checked = asyncio.Event(), asyncio.Event()
        async def scoped():
            with compat.use_source_compatibility(_pin(path)):
                ready.set()
                await checked.wait()
                assert compat.resolve_source_compatibility(_pin(old)).declaration == _pin(path)
        async def ordinary():
            await ready.wait()
            try:
                with pytest.raises(ValueError, match="inventories"):
                    compat.resolve_source_compatibility(_pin(old))
            finally:
                checked.set()
        await asyncio.gather(scoped(), ordinary())
    asyncio.run(run())
    with pytest.raises(RuntimeError, match="scope failed"), compat.use_source_compatibility(_pin(path)):
        raise RuntimeError("scope failed")
    with pytest.raises(ValueError, match="inventories"):
        compat.resolve_source_compatibility(_pin(old))


@pytest.mark.parametrize("defect", ["approval", "other_pin", "old_packet", "archive", "current",
    "unknown", "prior_allowed", "unknown_file", "reverse", "rules", "report",
    "preserved", "publication", "missing_publication", "declaration"])
def test_supersession_rejects_unapproved_or_changed_scope(tmp_path, monkeypatch, defect):
    path, value, old, archive, current, completed = _supersession(tmp_path, monkeypatch)
    if defect == "approval":
        value["status"] = "PROPOSED"
    elif defect == "other_pin":
        other = tmp_path / "other-approval.json"
        shutil.copyfile(old, other)
        with compat.use_source_compatibility(_pin(path)), pytest.raises(ValueError, match="inventories"):
            compat.resolve_source_compatibility(_pin(other))
        return
    elif defect == "old_packet":
        old.write_text(old.read_text() + " ")
    elif defect in {"archive", "current", "unknown", "prior_allowed", "unknown_file"}:
        root = archive if defect == "archive" else current
        name = {"unknown": "history.py", "prior_allowed": "metric_quality.py",
                "unknown_file": "unexpected.py"}.get(defect, "screening/quarterly.py")
        with (root / name).open("a") as stream:
            stream.write("\n# unexpected source change\n")
        if defect in {"unknown", "prior_allowed", "unknown_file"}:
            value["current_source_sha256s"] = compat.source_inventory(current)
            value["approved_changes"][name] = {"origin": value["origin_source_sha256s"].get(name),
                                                 "current": value["current_source_sha256s"][name]}
            for row in value["routine_histories"]:
                row["current_code_identity"] = compat._code_identity(current, value["current_source_sha256s"], row["rules"])
    elif defect == "reverse":
        value["origin_source_sha256s"], value["current_source_sha256s"] = (
            value["current_source_sha256s"], value["origin_source_sha256s"])
    elif defect == "rules":
        value["routine_histories"][0]["rules"]["period_rule"] = "changed-rule"
    elif defect == "report":
        source = Path(value["routine_histories"][0]["report"]["path"])
        source.write_text(source.read_text() + " ")
    elif defect == "missing_publication":
        value["supersedes"]["completed_publications"].pop("identity")
    elif defect == "preserved":
        value["preserved_controls"].pop(0)
    elif defect == "publication":
        source = Path(completed["annual_metrics"]["path"])
        source.write_text(source.read_text() + " ")
    else:
        value["supersedes"]["unknown_scope"] = True
    write_json(path, value)
    with pytest.raises(ValueError):
        compat.resolve_source_compatibility(_pin(path))


def test_active_scope_rechecks_current_bytes_and_packet_seal(tmp_path, monkeypatch):
    path, _, old, _, current, _ = _supersession(tmp_path, monkeypatch)
    with compat.use_source_compatibility(_pin(path)) as witness:
        source = current / "screening/quarterly.py"
        source.write_text(source.read_text() + "\n# later change\n")
        with pytest.raises(ValueError, match="inventories"):
            compat.resolve_source_compatibility(_pin(old))
        witness.payload["status"] = "PROPOSED"
        with pytest.raises(ValueError, match="untrusted"):
            compat.resolve_source_compatibility(_pin(old))


def test_public_combined_publish_and_reopen_reuse_four_immutable_parents(tmp_path, monkeypatch):
    from sec_xbrl.screening import verified_source_closure as closure
    from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader, publish_screening_dataset_v3
    from sec_xbrl.screening.metric_identity import GenericMetricIdentityReader

    path, _, old, _, _, completed = _supersession(tmp_path, monkeypatch, public_parents=True)
    immutable = [old, *[Path(pin["path"]) for pin in completed.values()],
                 *tmp_path.glob("preserved-*-config.json")]
    before = {source: sha256_file(source) for source in immutable}
    config = {"schema_version": "screening-prepare-config-v3", "dataset_id": "reused-four",
              "annual_dataset_root": str(Path(completed["annual_dataset"]["path"]).parent),
              "annual_manifest_sha256": completed["annual_dataset"]["sha256"],
              "quarterly_metric_root": str(Path(completed["quarterly_metrics"]["path"]).parent),
              "quarterly_manifest_sha256": completed["quarterly_metrics"]["sha256"],
              "source_compatibility": _pin(path)}
    config_path = tmp_path / "new-combined-config.json"
    write_json(config_path, config)
    def forbidden(*args, **kwargs):
        raise AssertionError("completed routine/full History validation must not repeat")
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    identity_root = Path(completed["identity"]["path"]).parent
    with pytest.raises(ValueError, match="inventories"):
        GenericMetricIdentityReader(identity_root)
    combined = publish_screening_dataset_v3(config_path, tmp_path / "new-combined")
    reader = ScreeningDatasetV3Reader(combined)
    assert reader.manifest["config"]["source_compatibility"] == _pin(path)
    assert reader.verify_all()["company_count"] == 1
    assert reader.verify_all()["quarter_observation_count"] == 328
    with compat.use_source_compatibility(_pin(path)):
        snapshot = closure._v3_snapshot(config_path, config,
            Path(config["annual_dataset_root"]), Path(config["quarterly_metric_root"]))
    assert {str(path), str(old)} <= {record.path for record in snapshot.files}
    assert {source: sha256_file(source) for source in immutable} == before
    with pytest.raises(ValueError, match="inventories"):
        GenericMetricIdentityReader(identity_root)
    manifest_path = combined / "screening_dataset_manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    alias_annual = tmp_path / "copied-annual"
    shutil.copytree(Path(config["annual_dataset_root"]), alias_annual)
    manifest["parents"]["annual"]["root"] = str(alias_annual)
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="configured compatibility scope"):
        ScreeningDatasetV3Reader(combined)
    manifest_path.write_bytes(original_manifest)
    missing = dict(config)
    missing.pop("source_compatibility")
    write_json(tmp_path / "missing-compatibility.json", missing)
    with pytest.raises(ValueError, match="inventories"):
        publish_screening_dataset_v3(tmp_path / "missing-compatibility.json", tmp_path / "missing-combined")
    assert not (tmp_path / "missing-combined").exists()
    # A pinless caller must fail even when its caller has an approved ambient scope.
    with compat.use_source_compatibility(_pin(path)):
        with pytest.raises(ValueError, match="inventories"):
            publish_screening_dataset_v3(tmp_path / "missing-compatibility.json", tmp_path / "ambient-combined")
        assert not (tmp_path / "ambient-combined").exists()
        # Construct an otherwise consistent pinless manifest without publishing it.
        pinless_root = tmp_path / "pinless-combined-fixture"
        pinless_root.mkdir()
        pinless = json.loads(original_manifest)
        pinless.update(config=missing, config_path=str(tmp_path / "missing-compatibility.json"),
                       config_sha256=sha256_file(tmp_path / "missing-compatibility.json"))
        identity = {"config_path": pinless["config_path"], "config_sha256": pinless["config_sha256"],
                    "config": missing, "annual_publication_id": pinless["versions"]["annual_publication_id"],
                    "quarterly_publication_id": pinless["versions"]["quarterly_publication_id"]}
        pinless["publication_id"] = "screening-dataset-" + digest_value(identity)[:24]
        write_json(pinless_root / "screening_dataset_manifest.json", pinless)
        with pytest.raises(ValueError, match="inventories"):
            ScreeningDatasetV3Reader(pinless_root)
        assert compat.resolve_source_compatibility(_pin(old)).declaration == _pin(path)
    with pytest.raises(ValueError, match="inventories"):
        ScreeningDatasetV3Reader(pinless_root)


@pytest.mark.parametrize("first", ["compatibility", "dataset_v3"])
def test_fresh_process_public_import_order(first):
    imports = [
        "from sec_xbrl.financial_source_compatibility import prepare_source_compatibility_packet",
        "from sec_xbrl.screening.dataset_v3 import publish_screening_dataset_v3, ScreeningDatasetV3Reader",
    ]
    if first == "dataset_v3":
        imports.reverse()
    result = subprocess.run([sys.executable, "-c", "\n".join(imports)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_explicit_none_scope_isolates_and_restores_outer_after_exception(tmp_path, monkeypatch):
    path, _, old, _, _, _ = _supersession(tmp_path, monkeypatch)
    with compat.use_source_compatibility(_pin(path)):
        assert compat.resolve_source_compatibility(_pin(old)).declaration == _pin(path)
        with pytest.raises(RuntimeError, match="isolated failure"), compat.use_source_compatibility(None) as witness:
            assert witness is None
            with pytest.raises(ValueError, match="inventories"):
                compat.resolve_source_compatibility(_pin(old))
            raise RuntimeError("isolated failure")
        assert compat.resolve_source_compatibility(_pin(old)).declaration == _pin(path)
    with pytest.raises(ValueError, match="inventories"):
        compat.resolve_source_compatibility(_pin(old))


@pytest.mark.parametrize("continuity", [False, True])
def test_latest_consumer_transition_reopens_old_and_new_combined_without_replaying_history(tmp_path, monkeypatch, continuity):
    from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader, publish_screening_dataset_v3
    from sec_xbrl.screening.service import ScreeningService

    prior, previous, origin, _, current, completed = _supersession(tmp_path, monkeypatch, public_parents=True)
    config = {
        "schema_version": "screening-prepare-config-v3", "dataset_id": "prior-combined",
        "annual_dataset_root": str(Path(completed["annual_dataset"]["path"]).parent),
        "annual_manifest_sha256": completed["annual_dataset"]["sha256"],
        "quarterly_metric_root": str(Path(completed["quarterly_metrics"]["path"]).parent),
        "quarterly_manifest_sha256": completed["quarterly_metrics"]["sha256"],
        "source_compatibility": _pin(prior),
    }
    old_config = tmp_path / "prior-config.json"
    write_json(old_config, config)
    old_root = publish_screening_dataset_v3(old_config, tmp_path / "prior-combined")
    old_publication = ScreeningDatasetV3Reader(old_root).publication_id
    archive = tmp_path / "source408"
    shutil.copytree(current, archive)
    for name in compat._LATEST_CHANGES:
        with (current / name).open("a") as stream:
            stream.write("\n# approved latest consumer change\n")
    latest = tmp_path / "latest-compatibility.json"
    packet = compat.prepare_source_compatibility_packet(
        origin_source_root=Path(previous["origin_source_root"]),
        preserved_controls=previous["preserved_controls"],
        routine_histories=[{key: row[key] for key in ("report", "build_manifest", "history_manifest")}
                           for row in previous["routine_histories"]],
        supersedes={"packet": _pin(prior), "source_root": str(archive), "completed_publications": completed},
        latest=True,
    )
    packet["status"] = "ROOT_APPROVED"
    write_json(latest, packet)
    config.update(dataset_id="latest-combined", source_compatibility=_pin(latest))
    new_config = tmp_path / "latest-config.json"
    write_json(new_config, config)
    def forbidden(*args, **kwargs):
        raise AssertionError("prior History checks must not repeat")
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    new_root = publish_screening_dataset_v3(new_config, tmp_path / "latest-combined")
    with pytest.raises(ValueError, match="inventories"):
        ScreeningDatasetV3Reader(old_root)
    with compat.use_source_compatibility(_pin(latest)):
        for old_pin in (prior, origin):
            assert compat.resolve_source_compatibility(_pin(old_pin)).declaration == _pin(latest)
    service = ScreeningService(
        {"prior-combined": old_root, "latest-combined": new_root},
        tmp_path / "journal.sqlite", source_compatibility=_pin(latest),
    )
    service.require_publication("prior-combined", old_publication)
    assert len(service.status()["datasets"]) == 2
    with pytest.raises(ValueError, match="inventories"):
        compat.resolve_source_compatibility(_pin(prior))

    if not continuity:
        return

    from sec_xbrl.metrics.quarterly_screening import publish_quarterly_screening_metrics
    from sec_xbrl.metrics.statement_metric_evidence import (
        CONTINUITY_CATALOG,
        STATEMENT_EVIDENCE_VERSION,
    )
    from sec_xbrl.screening import dataset_v3

    latest_archive = tmp_path / "source-latest"
    shutil.copytree(current, latest_archive)
    for name in compat._CONTINUITY_CHANGES:
        with (current / name).open("a") as stream:
            stream.write("\n# approved continuity source change\n")
    v4_inputs = {
        "origin_source_root": Path(packet["origin_source_root"]),
        "preserved_controls": packet["preserved_controls"],
        "routine_histories": [{key: row[key] for key in ("report", "build_manifest", "history_manifest")}
                              for row in packet["routine_histories"]],
        "supersedes": {"packet": _pin(latest), "source_root": str(latest_archive),
                       "completed_publications": completed},
        "continuity": True,
    }
    bootstrap = tmp_path / "continuity-bootstrap.json"
    write_json(bootstrap, compat.prepare_source_compatibility_packet(**v4_inputs) | {"status": "ROOT_APPROVED"})
    old_quarter = json.loads(Path(completed["quarterly_metrics"]["path"]).read_text())
    evidence = tmp_path / "statement-evidence.json"
    write_json(evidence, {"version": STATEMENT_EVIDENCE_VERSION,
                          "financial_as_of": old_quarter["financial_as_of"], "records": []})
    quarter_config = tmp_path / "continuity-quarter-config.json"
    write_json(quarter_config, old_quarter["config"] | {
        "catalog_version": CONTINUITY_CATALOG, "statement_metric_evidence": _pin(evidence),
    })
    with compat.use_source_compatibility(_pin(bootstrap)):
        for ancestor in (latest, prior, origin):
            assert compat.resolve_source_compatibility(_pin(ancestor)).declaration == _pin(bootstrap)
        quarter = publish_quarterly_screening_metrics(quarter_config, tmp_path / "continuity-quarter")
        assert ScreeningDatasetV3Reader(new_root).manifest["dataset_id"] == "latest-combined"

    final = tmp_path / "continuity-final.json"
    write_json(final, compat.prepare_source_compatibility_packet(
        **v4_inputs, quarterly_successor=_pin(quarter.manifest_path),
    ) | {"status": "ROOT_APPROVED"})
    combined = tmp_path / "continuity-config.json"
    combined_config = config | {
        "dataset_id": "continuity-combined", "source_compatibility": _pin(final),
        "quarterly_metric_root": str(quarter.root), "quarterly_manifest_sha256": sha256_file(quarter.manifest_path),
        "quarterly_successor": _pin(quarter.manifest_path),
    }
    write_json(combined, combined_config)
    with compat.use_source_compatibility(_pin(final)) as witness:
        assert witness.controls["QUARTERLY_STATEMENT_EVIDENCE"] == _pin(evidence)
        assert witness.controls["QUARTERLY_SUCCESSOR_CONFIG"] == _pin(quarter_config)
        for ancestor in (latest, prior, origin):
            assert compat.resolve_source_compatibility(_pin(ancestor)).declaration == _pin(final)
        for key, value in (
            ("source_compatibility", None),
            ("source_compatibility", _pin(bootstrap)),
            ("source_compatibility", _pin(latest)),
            ("quarterly_successor", completed["quarterly_metrics"]),
        ):
            write_json(combined, combined_config | {key: value})
            with pytest.raises(ValueError, match="approved continuity scope"):
                publish_screening_dataset_v3(combined, tmp_path / "rejected-combined")
        write_json(combined, {key: value for key, value in combined_config.items() if key != "quarterly_successor"})
        with pytest.raises(ValueError, match="explicit successor pin"):
            publish_screening_dataset_v3(combined, tmp_path / "rejected-combined")
    assert not (tmp_path / "rejected-combined").exists()

    write_json(combined, combined_config)
    combined_root = publish_screening_dataset_v3(combined, tmp_path / "continuity-combined")
    service = ScreeningService(
        {"prior-combined": old_root, "latest-combined": new_root, "continuity-combined": combined_root},
        tmp_path / "continuity-journal.sqlite", source_compatibility=_pin(final),
    )
    service.require_publication("prior-combined", old_publication)
    assert len(service.status()["datasets"]) == 3
    assert ScreeningDatasetV3Reader(combined_root).quarterly.publication_id == quarter.publication_id

    original = evidence.read_bytes()
    promote = dataset_v3._publish_verified_v3

    def change_evidence_after_verification(*args, **kwargs):
        evidence.write_bytes(original + b" ")
        try:
            return promote(*args, **kwargs)
        finally:
            evidence.write_bytes(original)

    monkeypatch.setattr(dataset_v3, "_publish_verified_v3", change_evidence_after_verification)
    destination = tmp_path / "invalidated-combined"
    with pytest.raises(ValueError, match="changed|differs"):
        publish_screening_dataset_v3(combined, destination)
    assert not destination.exists()

    changed_manifest = json.loads(quarter.manifest_path.read_text())
    changed_manifest["governance_parents"] = []
    invalid_child = tmp_path / "invalid-child" / quarter.manifest_path.name
    invalid_child.parent.mkdir()
    write_json(invalid_child, changed_manifest)
    invalid_packet = tmp_path / "invalid-continuity-packet.json"
    write_json(invalid_packet, compat.prepare_source_compatibility_packet(
        **v4_inputs, quarterly_successor=_pin(invalid_child),
    ) | {"status": "ROOT_APPROVED"})
    with pytest.raises(ValueError, match="preserve the approved parent scope"):
        compat.resolve_source_compatibility(_pin(invalid_packet))

    from sec_xbrl.screening import liability_addition

    v4_archive = tmp_path / "source-continuity"
    shutil.copytree(current, v4_archive)
    for name in compat._LIABILITY_CHANGES:
        with (current / name).open("a") as stream:
            stream.write("\n# approved liability addition source change\n")
    audit = tmp_path / "approved-audit.json"
    write_json(audit, {"synthetic_fixture": True})
    parent_manifest = combined_root / dataset_v3.MANIFEST
    addition = {"audit": _pin(audit), "parent_manifest": _pin(parent_manifest),
                "parent_publication_id": json.loads(parent_manifest.read_text())["publication_id"]}
    v5 = tmp_path / "liability-approval.json"
    write_json(v5, compat.prepare_source_compatibility_packet(
        **(v4_inputs | {"continuity": False, "supersedes": {
            "packet": _pin(final), "source_root": str(v4_archive), "completed_publications": completed,
        }}),
        liability_addition=addition,
    ) | {"status": "ROOT_APPROVED"})
    overlay_config = tmp_path / "liability-config.json"
    write_json(overlay_config, {"schema_version": liability_addition.CONFIG_VERSION,
                                "dataset_id": "liability-overlay", "source_compatibility": _pin(v5),
                                "liability_addition": addition})

    # Value projection has its own fixed/latest six-candidate tests. This fixture
    # verifies real approval ancestry and that both catalog IDs share one reader.
    parents = []

    def project(parent, pin):
        assert pin == _pin(audit)
        parents.append(parent)
        return {"metric_id": liability_addition.METRIC_ID}, [], []

    monkeypatch.setattr(liability_addition, "read_approved_audit", lambda *args, **kwargs: {})
    monkeypatch.setattr(liability_addition, "liability_rows", project)
    overlay_root = dataset_v3.publish_liability_addition(overlay_config, tmp_path / "liability-overlay")
    assert parents == []
    with compat.use_source_compatibility(_pin(v5)):
        for ancestor in (final, latest, prior, origin):
            assert compat.resolve_source_compatibility(_pin(ancestor)).declaration == _pin(v5)
    for catalog in (
        {"liability-overlay": overlay_root, "continuity-combined": combined_root},
        {"continuity-combined": combined_root, "liability-overlay": overlay_root},
    ):
        reopened = ScreeningService(catalog, tmp_path / "liability-journal.sqlite", source_compatibility=_pin(v5))
        old_reader = reopened.datasets["continuity-combined"]
        new_reader = reopened.datasets["liability-overlay"]
        assert parents[-1] is old_reader
        assert new_reader.observations is old_reader.observations
        assert new_reader.quarterly is old_reader.quarterly
        assert len(new_reader.quarter_definitions) == len(old_reader.quarter_definitions) + 1
        reopened.require_publication("continuity-combined", addition["parent_publication_id"])
    audit.write_text("{}\n")
    with pytest.raises(ValueError, match="missing, unsafe or changed"):
        ScreeningDatasetV3Reader(overlay_root)
