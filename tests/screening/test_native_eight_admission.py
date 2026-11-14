"""Named native producer grants remain exact, scoped and separate from old401."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sec_xbrl import financial_native_source as native
from sec_xbrl.screening import dataset_v3
from sec_xbrl.screening.common import digest_value, read_json, write_json
from tests.screening.test_financial_native_source import _fixture
from tests.screening.test_financial_storage_reuse import _pin


def _v2(tmp_path, monkeypatch, name):
    target = native._PRODUCER_PROFILES[name]["producer_revision"]
    original = native.PRODUCER
    monkeypatch.setattr(native, "PRODUCER", target)
    config, old_packet, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(native, "PRODUCER", original)
    old = read_json(old_packet)
    quality = read_json(Path(old["quality"]["path"]))
    profiles = copy.deepcopy(native._PRODUCER_PROFILES)
    # Synthetic producer fixture has its own exact source/parser inventory.
    profiles[name].update(origin_inventory=digest_value(old["source"]["old_files"]),
                          parser_profiles=quality["parser_profiles"], annual_coverage_policy="STRICT_5_INPUT_4_DISPLAY")
    monkeypatch.setattr(native, "_PRODUCER_PROFILES", profiles)
    baseline = old["source"]["current_files"]
    monkeypatch.setattr(native, "_CONSUMER_BASELINE_INVENTORY", digest_value(baseline))
    # This fixture models its own exact accepted consumer, not production's old qualification.
    monkeypatch.setattr(native, "_PARTIAL_CONSUMER_FILES",
                        {name: baseline[name] for name in native._PARTIAL_CONSUMER_FILES})
    plan = tmp_path / "occurrence-plan.json"
    write_json(plan, {"scope": old["ciks"]})
    selected = []
    for company in quality["collection_status"]:
        intake_pin = {"path": company["intake_manifest_path"], "sha256": company["intake_sha256"]}
        for index, entry in enumerate(read_json(Path(intake_pin["path"]))["filings"]):
            ref = entry["filing"]
            raw = Path(entry["source_run"]) / "snapshots" / ref["cik"] / ref["accession"].replace("-", "") / "layer1_manifest.json"
            scope = {"entry": entry, "cik": ref["cik"], "accession": ref["accession"], "intake": intake_pin,
                     "financial_as_of": old["financial_as_of"], "snapshot_manifest": _pin(raw),
                     "builder_sha256": old["source"]["old_files"]["metrics/statement_metric_evidence.py"]}
            checkpoint = tmp_path / f"checkpoint-{company['cik']}-{index}.json"
            write_json(checkpoint, {"input": scope, "records": []})
            selected.append({"scope": scope, "checkpoint": _pin(checkpoint), "admitted_records": 0})
    inputs = tmp_path / "occurrence-inputs.json"
    write_json(inputs, {"evidence": old["statement_metric_evidence"], "admitted_records": 0,
                        "cohort_plan": _pin(plan), "selected_filings": selected})
    packet = native.prepare_native_source_packet(parents=old["parents"], old_source_root=Path(old["source"]["old_root"]),
        destination=tmp_path / "v2-packet.json", producer_profile=name,
        consumer_baseline_files=baseline, occurrence_inputs=_pin(inputs))
    approval = tmp_path / "v2-approval.json"
    write_json(approval, {"schema_version": native.APPROVAL_VERSION_V2,
                         "status": "ROOT_APPROVED_NATIVE_SOURCE_TRANSITION", "packet": _pin(packet)})
    declaration = {"packet": _pin(packet), "approval": _pin(approval)}
    config["native_source"] = declaration
    return config, packet, inputs


@pytest.mark.parametrize("profile", ["partial-annual-882-v1", "duration-hour-20ec-v1"])
def test_named_profile_public_combine_reopen_and_context_reset(tmp_path, monkeypatch, profile):
    config, packet, _ = _v2(tmp_path, monkeypatch, profile)
    config_path = tmp_path / "combined.json"
    write_json(config_path, config)
    publication = dataset_v3.publish_screening_dataset_v3(config_path, tmp_path / "combined")
    reader = dataset_v3.ScreeningDatasetV3Reader(publication)
    assert len(reader.companies) == 1
    assert read_json(packet)["producer_revision"] == native._PRODUCER_PROFILES[profile]["producer_revision"]
    assert native.native_controls() == ({}, ())
    with native.use_native_source(config["native_source"]):
        assert native.native_controls()[0]
        with native.use_native_source(None):
            assert native.native_controls() == ({}, ())
        assert native.native_controls()[0]
        with pytest.raises(RuntimeError), native.use_native_source(config["native_source"]):
            raise RuntimeError("fixture exception")
        assert native.native_controls()[0]
    assert native.native_controls() == ({}, ())
    body = read_json(packet)
    body["schema_version"] = native.VERSION
    write_json(packet, body)
    invalid = copy.deepcopy(config["native_source"])
    invalid["packet"] = _pin(packet)
    with pytest.raises(ValueError), native.use_native_source(invalid):
        pass


def test_named_profile_rejects_unknown_mixed_parent_and_borrowed_empty_inputs(tmp_path, monkeypatch):
    _config, packet, inputs = _v2(tmp_path, monkeypatch, "duration-hour-20ec-v1")
    body = read_json(packet)
    bad = copy.deepcopy(body)
    bad["producer_profile"] = "unknown"
    with pytest.raises(ValueError, match="profile"):
        native._source_controls(bad)
    bad = copy.deepcopy(body)
    bad["source"]["old_files"]["history.py"] = "0" * 64
    with pytest.raises(ValueError, match="inventory"):
        native._source_controls(bad)
    bad = copy.deepcopy(body)
    bad["producer_revision"] = native.PRODUCER
    # Parent quarter/quality must match the named producer, not a caller's relabel.
    bad["parents"]["annual_metrics"] = bad["parents"]["identity"]
    with pytest.raises(ValueError):
        native._data_controls(bad)
    inventory = read_json(inputs)
    inventory["selected_filings"] = []
    write_json(inputs, inventory)
    body["occurrence_inputs"] = _pin(inputs)
    with pytest.raises(ValueError, match="coverage"):
        native._data_controls(body)
    inventory = read_json(inputs)
    inventory["evidence"] = {"path": "foreign", "sha256": "0" * 64}
    write_json(inputs, inventory)
    body["occurrence_inputs"] = _pin(inputs)
    with pytest.raises(ValueError, match="inventory"):
        native._data_controls(body)



def test_real_current_inventory_does_not_inherit_legacy_consumer_qualification():
    current = native._inventory(Path(native.__file__).parent)
    with pytest.raises(ValueError, match="acceptance baseline inventory differs"):
        native.qualified_consumer_files(current, current)
