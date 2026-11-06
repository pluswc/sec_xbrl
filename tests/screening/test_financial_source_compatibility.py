"""Directed source evidence and nullable Parquet transport repair boundaries."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from sec_xbrl import financial_source_compatibility as compat
from sec_xbrl import financial_storage_reuse as storage
from sec_xbrl import history
from sec_xbrl.prospective_selection import _same_transport_records
from sec_xbrl.screening.common import sha256_file, write_json
from tests.screening.test_financial_storage_reuse import COHORT, _current_routine_proof, _pin


def test_nullable_top_level_parquet_roundtrip_preserves_values_and_input(tmp_path):
    from sec_xbrl.analysis import _table

    expected = [{"id": "a"}, {"id": "b", "availability_note": None}]
    original = copy.deepcopy(expected)
    info = history._write_records(tmp_path / "trace.parquet", tuple(expected))
    actual = _table(tmp_path, {"path": "trace.parquet", **info})
    assert actual[0] == {"id": "a", "availability_note": None}
    assert _same_transport_records(expected, actual, actual_columns=actual[0])
    assert expected == original


@pytest.mark.parametrize("actual", [
    [{"id": "a", "note": None, "extra": None}, {"id": "b", "note": None, "extra": None}],
    [{"id": "a", "note": "changed"}, {"id": "b", "note": None}],
    [{"id": "b", "note": None}, {"id": "a", "note": None}],
    [{"id": "a", "note": None}],
    [{"id": "a"}, {"id": "b", "note": None}],
])
def test_transport_rejects_unknown_values_order_count_or_missing_actual_columns(actual):
    assert not _same_transport_records([{"id": "a"}, {"id": "b", "note": None}], actual)


def test_transport_never_normalizes_nested_keys_or_ignores_empty_schema():
    assert not _same_transport_records([{"lineage": {}}], [{"lineage": {"extra": None}}])
    assert not _same_transport_records([], [], actual_columns=["extra"])
    assert _same_transport_records([], [], actual_columns=[])


def _transition(tmp_path, monkeypatch, *, with_quality=False):
    prepared, registry, report_path = _current_routine_proof(tmp_path, monkeypatch)
    preserved = [_pin(registry)]
    if with_quality:
        from sec_xbrl.metric_quality import publish_generic_metric_quality
        payload = json.loads((tmp_path / "quality-config.json").read_text())
        payload["storage_reuse"] = _pin(registry)
        config = tmp_path / "routine-quality-config.json"
        write_json(config, payload)
        quality = publish_generic_metric_quality(config_path=config,
            collection_manifest=Path(prepared.paths["collection"]),
            source_binding_publication=tmp_path / "quality-bindings",
            history_manifests=prepared.histories, destination=tmp_path / "routine-quality",
            producer_revision="e" * 40)
        prepared.quality = quality
        preserved.append(_pin(quality.manifest_path))
    package = Path(storage.__file__).parent
    origin = tmp_path / "source451"
    current = tmp_path / "source-current"
    for destination in (origin, current):
        for path in package.rglob("*.py"):
            target = destination / path.relative_to(package)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    # Simulate an approved consumer-only change after the completed routine report.
    with (current / "prospective_selection.py").open("a") as stream:
        stream.write("\n# exact synthetic transport repair\n")
    with (current / "financial_storage_reuse.py").open("a") as stream:
        stream.write("\n# exact synthetic compatibility reader repair\n")
    monkeypatch.setattr(compat, "_current_source_root", lambda: current)
    monkeypatch.setattr(storage, "financial_storage_policy_sources", lambda: {
        "src/sec_xbrl/" + name: sha256_file(current / name) for name in storage._POLICY})
    monkeypatch.setattr(storage, "current_history_validation_identity", lambda manifest:
        compat._code_identity(current, compat.source_inventory(current), storage.history_validation_rules(manifest)))
    value = json.loads(registry.read_text())
    entry = value["companies"][0]["histories"][0]
    packet = compat.prepare_source_compatibility_packet(
        origin_source_root=origin, preserved_controls=preserved,
        routine_histories=[{"report": _pin(report_path), "build_manifest": entry["build_manifest"],
                            "history_manifest": entry["history_manifest"]}])
    packet["status"] = "ROOT_APPROVED"
    path = tmp_path / "source-compatibility.json"
    write_json(path, packet)
    return prepared, registry, report_path, path, packet, current


def test_directed_transition_reuses_unchanged_routine_report_without_decoding(tmp_path, monkeypatch):
    prepared, registry, report, path, _, _ = _transition(tmp_path, monkeypatch)
    before = {p: sha256_file(p) for p in (registry, report)}
    collection = Path(prepared.paths["collection"])
    with pytest.raises(ValueError, match="stale|policy compatibility"):
        storage.resolve_storage_reuse(_pin(registry), collection_manifest=collection, scope_companies=list(COHORT))
    proof = compat.resolve_source_compatibility(_pin(path))
    def forbidden(*args, **kwargs):
        raise AssertionError("completed routine validation must not repeat")
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    resolved = storage.resolve_storage_reuse(_pin(registry), collection_manifest=collection,
                                            scope_companies=list(COHORT), source_compatibility=proof)
    assert resolved.companies["FIVE"]
    assert {p: sha256_file(p) for p in before} == before


@pytest.mark.parametrize("defect", ["unapproved", "reverse", "rules", "report", "payload", "unlisted_control", "future_inventory"])
def test_transition_rejects_unapproved_direction_rules_report_payload_and_scope(tmp_path, monkeypatch, defect):
    prepared, registry, report, path, packet, current = _transition(tmp_path, monkeypatch)
    if defect == "unapproved":
        with (current / "history.py").open("a") as stream:
            stream.write("\n# forbidden validator modification\n")
        packet["current_source_sha256s"] = compat.source_inventory(current)
        packet["approved_changes"]["history.py"] = {
            "origin": packet["origin_source_sha256s"]["history.py"],
            "current": packet["current_source_sha256s"]["history.py"]}
    elif defect == "reverse":
        packet["origin_source_sha256s"], packet["current_source_sha256s"] = (
            packet["current_source_sha256s"], packet["origin_source_sha256s"])
    elif defect == "rules":
        packet["routine_histories"][0]["rules"]["period_rule"] = "unapproved-period"
    elif defect == "report":
        report.write_text(report.read_text() + " ")
    elif defect == "payload":
        manifest = json.loads(Path(packet["routine_histories"][0]["history_manifest"]["path"]).read_text())
        root = Path(packet["routine_histories"][0]["history_manifest"]["path"]).parent
        from sec_xbrl.collection_operations import _declared_publication_files
        relative = next(iter(_declared_publication_files(root, manifest)))
        with (root / relative).open("ab") as stream:
            stream.write(b"changed")
    elif defect == "unlisted_control":
        alternate = tmp_path / "other-control.json"
        write_json(alternate, {})
        packet["preserved_controls"] = [_pin(alternate)]
    elif defect == "future_inventory":
        with (current / "prospective_selection.py").open("a") as stream:
            stream.write("\n# later unapproved change\n")
    write_json(path, packet)
    with pytest.raises(ValueError):
        proof = compat.resolve_source_compatibility(_pin(path))
        storage.resolve_storage_reuse(_pin(registry), collection_manifest=Path(prepared.paths["collection"]),
                                     scope_companies=list(COHORT), source_compatibility=proof)


@pytest.mark.parametrize("mutate_at_boundary", [False, True])
def test_new_identity_reuses_immutable_quality_and_binds_transition_closure(tmp_path, monkeypatch, mutate_at_boundary):
    from sec_xbrl.screening import metric_identity

    prepared, registry, report, packet_path, _, _ = _transition(tmp_path, monkeypatch, with_quality=True)
    immutable = [registry, report, prepared.quality.manifest_path, prepared.quality.report_path]
    before = {path: sha256_file(path) for path in immutable}
    config = json.loads(prepared.identity_config.read_text())
    config.update(quality_root=str(prepared.quality.root),
                  quality_manifest_sha256=sha256_file(prepared.quality.manifest_path),
                  storage_reuse=_pin(registry), source_compatibility=_pin(packet_path))
    path = tmp_path / "compatible-identity-config.json"
    write_json(path, config)
    def forbidden(*args, **kwargs):
        raise AssertionError("completed native checks must not run again")
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    if mutate_at_boundary:
        original = metric_identity._verify_configured_sources
        def change_packet(config):
            result = original(config)
            packet_path.write_text(packet_path.read_text() + " ")
            return result
        monkeypatch.setattr(metric_identity, "_verify_configured_sources", change_packet)
        with pytest.raises(ValueError):
            metric_identity.publish_generic_metric_identity(path, tmp_path / "compatible-identity")
        assert not (tmp_path / "compatible-identity").exists()
        assert {p: sha256_file(p) for p in immutable} == before
        return
    publication = metric_identity.publish_generic_metric_identity(path, tmp_path / "compatible-identity")
    reader = metric_identity.GenericMetricIdentityReader(publication.root)
    assert reader.manifest["config"]["source_compatibility"] == _pin(packet_path)
    assert {p: sha256_file(p) for p in immutable} == before


def test_rejects_caller_forged_compatibility_object():
    from types import SimpleNamespace
    fake = SimpleNamespace(require_control=lambda pin: None, policy_matches=lambda *args: True)
    with pytest.raises(TypeError, match="untrusted"):
        compat.checked_source_compatibility(fake)


def test_existing_prospective_proof_and_origin_registry_replay_unchanged_under_transition(tmp_path, monkeypatch):
    from sec_xbrl.prospective_selection import (
        publish_prospective_selection,
        resolve_prospective_selection,
    )
    from tests.screening.test_prospective_selection import _fixture

    original = tmp_path / "prospective-fixture"
    original.mkdir()
    _, latest, config_path = _fixture(original, monkeypatch)
    manifest = publish_prospective_selection(config_path=config_path, destination=original / "proof")
    baseline = resolve_prospective_selection(_pin(manifest), collection_manifest=latest,
                                             scope_companies=list(COHORT))
    registry_pin = json.loads(config_path.read_text())["storage_reuse"]
    native = tmp_path / "native-fixture"
    native.mkdir()
    _, _, _, packet_path, packet, _ = _transition(native, monkeypatch)
    packet["preserved_controls"].extend([_pin(manifest), registry_pin])
    write_json(packet_path, packet)
    witness = compat.resolve_source_compatibility(_pin(packet_path))
    def forbidden(*args, **kwargs):
        raise AssertionError("accepted History must not decode again")
    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, "validate", forbidden)
    replay = resolve_prospective_selection(_pin(manifest), collection_manifest=latest,
                                           scope_companies=list(COHORT), source_compatibility=witness)
    assert replay.controls == baseline.controls
    assert replay.companies == baseline.companies
    assert replay.storage_reuse.controls == baseline.storage_reuse.controls


def test_source_inventory_rejects_alias(tmp_path):
    (tmp_path / "valid.py").write_text("x = 1\n")
    (tmp_path / "alias.py").symlink_to(tmp_path / "valid.py")
    with pytest.raises(ValueError, match="aliases"):
        compat.source_inventory(tmp_path)
