"""Fail-closed append orchestration and approved fiscal-rule compatibility."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl import history, history_reuse
from sec_xbrl.longitudinal import CohortReleaseAdapter, VersionedObservationPanelPipeline
from sec_xbrl.longitudinal.materialization import Layer2RuleVersions, Layer2Run
from sec_xbrl.screening.common import sha256_file, write_json
from tests.unit.test_source_bindings import _fixture


def _pin(path):
    return {"path":str(path.resolve()),"sha256":sha256_file(path)}


@pytest.mark.parametrize("required",[False,True])
def test_required_append_never_calls_full_producer_on_failed_prefix_proof(tmp_path,monkeypatch,required):
    intake=tmp_path/"intake.json"
    write_json(intake,{"complete":True,"plan":{"companies":[{"ticker":"TEST","cik":"0000000999","filings":[]}]},"filings":[]})
    release=SimpleNamespace(layer2_run=SimpleNamespace(fingerprint="fixture"),snapshots=())
    monkeypatch.setattr(CohortReleaseAdapter,"load",lambda *args,**kwargs:release)
    def reject(**kwargs): raise history_reuse.HistoryAppendReuseError("prefix is not exact")
    monkeypatch.setattr(history_reuse,"prepare_history_append",reject)
    calls=[]
    def full(*args,**kwargs):
        calls.append(True)
        raise RuntimeError("full producer reached only by legacy fallback")
    monkeypatch.setattr(VersionedObservationPanelPipeline,"publish",full)
    if required:
        with pytest.raises(history_reuse.HistoryAppendReuseError,match="fallback prohibited"):
            history.build_history(intake_manifest=intake,output_root=tmp_path/"new",previous_history=tmp_path/"old",require_append_reuse=True)
        assert calls==[]
    else:
        with pytest.raises(RuntimeError,match="legacy fallback"):
            history.build_history(intake_manifest=intake,output_root=tmp_path/"new",previous_history=tmp_path/"old")
        assert calls==[True]
    assert not (tmp_path/"new").exists()


def test_require_append_needs_previous_before_loading_any_raw(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError("Raw must not load")
    monkeypatch.setattr(CohortReleaseAdapter,"load",forbidden)
    with pytest.raises(ValueError,match="explicit previous"):
        history.build_history(intake_manifest=tmp_path/"absent",output_root=tmp_path/"new",require_append_reuse=True)


def test_public_collector_forwards_pinned_append_options_and_writes_real_ready_marker(tmp_path,monkeypatch):
    paths=_fixture(tmp_path/"source")
    previous=tmp_path/"previous/history_manifest.json";previous.parent.mkdir();write_json(previous,{"version":"fixture"})
    migration=tmp_path/"migration.json";write_json(migration,{"status":"ROOT_APPROVED","fixture_kind":"SYNTHETIC"})
    options={"previous_history_manifest":_pin(previous),"previous_reuse_evidence":_pin(migration),"require_append_reuse":True}
    calls=[]
    def build(**kwargs):
        calls.append(kwargs)
        intake=json.loads(kwargs["intake_manifest"].read_text())
        publication=kwargs["output_root"]/"panels"
        relative="scope/rows.parquet";info=history._write_records(publication/relative,({"row_id":"fixture"},))
        write_json(publication/"history_manifest.json",{"version":history.HISTORY_VERSION,"plan":intake["plan"],
            "source_intake":str(kwargs["intake_manifest"]),"views":list(kwargs["views"]),
            "history_append_reuse":{"mode":"STRICTLY_LATER_SINGLE_CIK_APPEND_V1","previous_history":str(previous.parent)},
            "tables":[{"files":{"rows":{"path":relative,**info}}}]})
        return publication
    monkeypatch.setattr(history,"build_history",build)
    operations.build_universe(manifest_path=Path(paths["collection"]),output_root=tmp_path/"new",selected_tickers=("TEST",),
                              history_build_options={"TEST":options})
    marker=Path(paths["collection"]).parent/"companies/TEST/build_manifest.json"
    payload=json.loads(marker.read_text())
    assert payload["status"]=="READY"
    assert payload["history_build_options"]==options
    assert calls[0]["previous_history"]==previous.parent
    assert calls[0]["previous_reuse_evidence"]==migration
    assert calls[0]["require_append_reuse"] is True
    assert set(operations.history_build_controls(payload))=={"previous_history_manifest","previous_reuse_evidence"}
    migration.write_text("tampered")
    status=operations.read_universe_status(manifest_path=Path(paths["collection"]))
    assert status.companies[0].state=="BUILD_FAILED"


@pytest.mark.parametrize("defect",["scope","pin","fallback"])
def test_public_append_options_fail_before_any_builder(tmp_path,monkeypatch,defect):
    paths=_fixture(tmp_path/"source")
    previous=tmp_path/"previous/history_manifest.json";previous.parent.mkdir();write_json(previous,{"version":"fixture"})
    migration=tmp_path/"migration.json";write_json(migration,{"status":"ROOT_APPROVED"})
    options={"previous_history_manifest":_pin(previous),"previous_reuse_evidence":_pin(migration),"require_append_reuse":True}
    key="OTHER" if defect=="scope" else "TEST"
    if defect=="pin": options["previous_reuse_evidence"]["sha256"]="0"*64
    if defect=="fallback": options["require_append_reuse"]=False
    monkeypatch.setattr(history,"build_history",lambda **kwargs:pytest.fail("builder must not run"))
    with pytest.raises(ValueError):
        operations.build_universe(manifest_path=Path(paths["collection"]),output_root=tmp_path/"new",selected_tickers=("TEST",),history_build_options={key:options})
    assert not (tmp_path/"new").exists()


@pytest.mark.parametrize("changed_hash",[False,True])
def test_existing_approved_correction_rule_hash_is_preserved_for_strict_prefix(tmp_path,monkeypatch,changed_hash):
    from tests.unit.test_fiscal_focus_correction import _snapshot
    artifact_sha="6"*64
    expected=Layer2RuleVersions("period-fiscal-boundaries-v2+fiscal-focus:"+artifact_sha,
                               "l2-m2-company-canonical-v4","recast-v1","selection-v1")
    assert history._history_layer2_rule_versions(artifact_sha)==expected
    snapshot=_snapshot();old_input=replace(snapshot.input,accession="0000000999-25-000001",filed_date="2025-03-04",report_date="2025-01-31",snapshot_id="previous-snapshot")
    old_run=Layer2Run("old","fixture",(old_input,),expected)
    current_rules=history._history_layer2_rule_versions("7"*64 if changed_hash else artifact_sha)
    current_run=Layer2Run("new","fixture",(old_input,snapshot.input),current_rules)
    old=tmp_path/"old/panels";reported=tmp_path/"old/reported-panels";old.mkdir(parents=True);reported.mkdir()
    roots={name:str(tmp_path/name) for name in ("t1","t2","t3","t4")}
    payload={"views":["AS_FILED","LATEST_REPORTED"],"input_fingerprint":old_run.fingerprint,
             "source_manifest_sha256":"fixture-sha","operational_roots":roots,
             "plan":{"companies":[{"cik":snapshot.input.cik}]}}
    write_json(reported/"history_manifest.json",payload)
    write_json(old/"history_manifest.json",{**payload,"supersedes_publication":str(reported)})
    monkeypatch.setattr(history_reuse,"_read_publication_manifest",lambda *args:{})
    monkeypatch.setattr(history_reuse,"_run_from_manifest",lambda *args:old_run)
    monkeypatch.setattr(history_reuse,"_sha256",lambda *args:"fixture-sha")
    def prefix_boundary(*args): raise RuntimeError("same approved rules reached canonical prefix proof")
    monkeypatch.setattr(history_reuse,"_canonical_mappings",prefix_boundary)
    release=SimpleNamespace(layer2_run=current_run)
    if changed_hash:
        with pytest.raises(history_reuse.HistoryAppendReuseError,match="rules changed"):
            history_reuse.prepare_history_append(previous_history=old,release=release,views=("AS_FILED","LATEST_REPORTED"))
    else:
        with pytest.raises(RuntimeError,match="same approved rules reached"):
            history_reuse.prepare_history_append(previous_history=old,release=release,views=("AS_FILED","LATEST_REPORTED"))
