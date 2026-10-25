"""Explicit ordinary-publication byte proof reuse, with strict default readers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl import history, metric_quality
from sec_xbrl.financial_storage_reuse import (
    financial_storage_policy_sources,
    resolve_storage_reuse,
    storage_history,
)
from sec_xbrl.history_selection import verify_financial_history_source
from sec_xbrl.screening import metric_identity
from sec_xbrl.screening.common import sha256_file, write_json
from tests.screening.test_generic_metric_identity_integration import (
    COHORT,
    _publish_identity_inputs,
)


def _pin(path):
    return {"path":str(path.resolve()),"sha256":sha256_file(path)}


def _proof(tmp_path, monkeypatch, *, kind="FULL_TYPED_COMPANY_AUDIT"):
    prepared=_publish_identity_inputs(tmp_path,monkeypatch)
    collection=Path(prepared.paths["collection"])
    build_path=collection.parent/"companies/FIVE/build_manifest.json"
    build=json.loads(build_path.read_text())
    history_path=Path(build["history_manifest"])
    root=history_path.parent
    declared=build["declared_files"]
    acceptance=tmp_path/"prior-acceptance.json"
    controls={}
    if kind=="FULL_TYPED_COMPANY_AUDIT":
        report=tmp_path/"prior-full-typed-report.json"
        write_json(report,{"verdict":"PASS_SEMANTICS_PENDING_FINAL_SEAL_GUARD",
                           "ticker":"FIVE","cik":COHORT[0]["cik"],"output_root":build["output_root"],
                           "all_file_results":[{"path":str(root/relative),"physical_sha256":digest,
                                                "all_records_consumed":True,"hash_schema_checked_before_after":True}
                                               for relative,digest in declared.items()]})
        write_json(acceptance,{"accepted_by":"ROOT_LEAD","actual_audit_report":_pin(report)})
        controls["report"]=_pin(report)
    elif kind=="ACCEPTED_FIRST5_FINANCIAL_CHAIN":
        config=tmp_path/"prior-first-financial-config.json"
        write_json(config,{"companies":[{"ticker":"FIVE","cik":COHORT[0]["cik"],
                    "history_root":str(root),"history_manifest_sha256":sha256_file(history_path),
                    "build_manifest":str(build_path),"build_manifest_sha256":sha256_file(build_path),
                    "plan_sha256":build["plan_sha256"],"intake_sha256":build["intake_sha256"]}]})
        write_json(acceptance,{"schema_version":"universe50-first5-financial-acceptance-v1",
                              "status":"LOCALLY_ACCEPTED_FIRST5_FINANCIAL","first5_config":_pin(config)})
        controls["config"]=_pin(config)
    else:
        write_json(acceptance,{"accepted_by":"ROOT_LEAD","fixture_kind":"SYNTHETIC"})
    controls["acceptance"]=_pin(acceptance)
    prior=tmp_path/"prior-storage-evidence.json"
    if kind=="NATIVE":
        write_json(prior,{"version":1,"full_storage_validation":True,"validation_level":"DETAILED",
                          "publication_root":str(root),"manifest_sha256":sha256_file(history_path),
                          "files":{relative:{"sha256":digest} for relative,digest in declared.items()}})
    else:
        write_json(prior,{"schema_version":"accepted-financial-storage-evidence-v1","kind":kind,
                          "history_manifest":_pin(history_path),"build_manifest":_pin(build_path),
                          "declared_payload_sha256s":declared,"historical_controls":controls})
    proof=tmp_path/"storage-reuse.json"
    write_json(proof,{"schema_version":"financial-history-storage-reuse-v1","status":"ROOT_APPROVED",
                     "collection_manifest":_pin(collection),"current_policy_source_sha256s":financial_storage_policy_sources(),
                     "companies":[{"ticker":"FIVE","cik":COHORT[0]["cik"],"histories":[{
                         "acceptance":_pin(acceptance),"previous_validation":_pin(prior),"build_manifest":_pin(build_path),
                         "history_manifest":_pin(history_path),"payload_inventory":{
                             str(path.relative_to(root)):sha256_file(path) for path in root.rglob("*") if path.is_file()}}]}]})
    return prepared,proof



def _as_v2(path):
    value=json.loads(path.read_text())
    value["schema_version"]="financial-history-storage-reuse-v2"
    value["diagnostic_policy"]="NONCONSUMED_TOPOLOGY_ONLY"
    diagnostics=set()
    for company in value["companies"]:
        for entry in company["histories"]:
            root=Path(entry["history_manifest"]["path"]).parent
            diagnostic=root/".chunks/quarter-spill.records"
            diagnostic.parent.mkdir(exist_ok=True);diagnostic.write_bytes(b"retained producer diagnostic")
            entry["retained_diagnostics"]=[str(diagnostic.relative_to(root))]
            diagnostics.add(diagnostic)
    write_json(path,value)
    return diagnostics

def _forbidden(*args,**kwargs):
    raise AssertionError("completed typed decoder must not run")


@pytest.mark.parametrize("kind",["NATIVE","FULL_TYPED_COMPANY_AUDIT","ACCEPTED_FIRST5_FINANCIAL_CHAIN"])
def test_ordinary_accepted_source_uses_exact_byte_proof_without_typed_decoder(tmp_path,monkeypatch,kind):
    prepared,path=_proof(tmp_path,monkeypatch,kind=kind)
    collection=Path(prepared.paths["collection"])
    monkeypatch.setattr(history.HistoryPublicationReader,"verify_all",_forbidden)
    proof=resolve_storage_reuse(_pin(path),collection_manifest=collection,scope_companies=list(COHORT))
    manifest=prepared.histories["FIVE"]
    verify_financial_history_source(manifest.parent,storage_entry=storage_history(proof,"FIVE",manifest))
    status=operations.read_universe_status(manifest_path=collection,validation_mode="financial_sources",storage_reuse=_pin(path))
    assert next(row for row in status.companies if row.ticker=="FIVE").state=="READY"
    with pytest.raises(AssertionError,match="decoder"):
        verify_financial_history_source(manifest.parent)
    with pytest.raises(ValueError,match="financial"):
        operations.read_universe_status(manifest_path=collection,storage_reuse=_pin(path))


@pytest.mark.parametrize("v2",[False,True])
def test_new_quality_identity_binds_storage_proof_and_replays_historical_controls(tmp_path,monkeypatch,v2):
    prepared,path=_proof(tmp_path,monkeypatch)
    diagnostics=_as_v2(path) if v2 else set()
    from sec_xbrl import financial_storage_reuse as storage_module
    from sec_xbrl.screening import verified_source_closure as closure
    real_sha=storage_module.sha256_file
    real_read=closure._read_stable
    def digest(source):
        assert Path(source) not in diagnostics,"diagnostic body was hashed"
        return real_sha(source)
    def read(source,**kwargs):
        assert Path(source) not in diagnostics,"diagnostic body entered active financial closure"
        return real_read(source,**kwargs)
    monkeypatch.setattr(storage_module,"sha256_file",digest)
    monkeypatch.setattr(closure,"_read_stable",read)
    monkeypatch.setattr(history.HistoryPublicationReader,"verify_all",_forbidden)
    config=json.loads((tmp_path/"quality-config.json").read_text())
    config["storage_reuse"]=_pin(path)
    config_path=tmp_path/"proof-quality-config.json"
    write_json(config_path,config)
    published=metric_quality.publish_generic_metric_quality(config_path=config_path,
                collection_manifest=Path(prepared.paths["collection"]),source_binding_publication=tmp_path/"quality-bindings",
                history_manifests=prepared.histories,destination=tmp_path/"proof-quality",producer_revision="a"*40)
    quality=metric_quality.GenericMetricQualityReader(published.root)
    identity_config=json.loads(prepared.identity_config.read_text())
    identity_config.update(storage_reuse=_pin(path),quality_root=str(published.root),
                           quality_manifest_sha256=sha256_file(published.manifest_path))
    identity_path=tmp_path/"proof-identity-config.json"
    write_json(identity_path,identity_config)
    identity=metric_identity.publish_generic_metric_identity(identity_path,tmp_path/"proof-identity")
    reader=metric_identity.GenericMetricIdentityReader(identity.root)
    assert reader.manifest["readiness"]=="READY"
    assert quality.manifest["storage_reuse"]==_pin(path)
    before=closure._Collector()
    closure._discover_identity(before,identity_path,metric_identity._validate_config(identity_config),prefix="TOPOLOGY")
    for diagnostic in diagnostics: diagnostic.write_bytes(b"changed unconsumed diagnostic body of different size")
    after=closure._Collector()
    closure._discover_identity(after,identity_path,metric_identity._validate_config(identity_config),prefix="TOPOLOGY")
    assert before.snapshot().fingerprint==after.snapshot().fingerprint
    assert not diagnostics & {Path(record.path) for record in after.snapshot().files}
    assert metric_identity.GenericMetricIdentityReader(identity.root).publication_id==reader.publication_id
    wrong=copy.deepcopy(identity_config);wrong.pop("storage_reuse")
    with pytest.raises((AssertionError,ValueError)):
        metric_identity._verify_configured_sources(metric_identity._validate_config(wrong))
    (tmp_path/"prior-full-typed-report.json").write_text("tampered historical witness")
    with pytest.raises(ValueError,match="changed|missing|digest"):
        metric_identity.GenericMetricIdentityReader(identity.root)


@pytest.mark.parametrize("defect",["approval","policy","payload","extra","alias","duplicate","missing_evidence","report_hash","first_config","approved_unknown_extra","unconsumed"])
def test_storage_reuse_rejects_changed_or_unaccepted_sources(tmp_path,monkeypatch,defect):
    kind="ACCEPTED_FIRST5_FINANCIAL_CHAIN" if defect=="first_config" else "FULL_TYPED_COMPANY_AUDIT"
    prepared,path=_proof(tmp_path,monkeypatch,kind=kind)
    value=json.loads(path.read_text());entry=value["companies"][0]["histories"][0]
    if defect=="approval": value["status"]="READY"
    elif defect=="policy": value["current_policy_source_sha256s"]["src/sec_xbrl/history.py"]="0"*64
    elif defect=="payload": (prepared.histories["FIVE"].parent/next(iter(json.loads(Path(entry["build_manifest"]["path"]).read_text())["declared_files"]))).write_bytes(b"bad")
    elif defect=="extra": (prepared.histories["FIVE"].parent/"unknown.txt").write_text("extra")
    elif defect=="alias": (prepared.histories["FIVE"].parent/"alias").symlink_to(path)
    elif defect=="duplicate": value["companies"][0]["histories"].append(copy.deepcopy(entry))
    elif defect=="missing_evidence": Path(entry["previous_validation"]["path"]).unlink()
    elif defect=="report_hash": (tmp_path/"prior-full-typed-report.json").write_text("changed")
    elif defect=="approved_unknown_extra":
        extra=prepared.histories["FIVE"].parent/"unknown.txt";extra.write_text("extra")
        entry["payload_inventory"][extra.name]=sha256_file(extra)
    elif defect=="unconsumed":
        report=tmp_path/"prior-full-typed-report.json"
        payload=json.loads(report.read_text());payload["all_file_results"][0]["all_records_consumed"]=False;write_json(report,payload)
        acceptance=tmp_path/"prior-acceptance.json";write_json(acceptance,{"actual_audit_report":_pin(report)})
        prior=Path(entry["previous_validation"]["path"]);payload=json.loads(prior.read_text())
        payload["historical_controls"].update(report=_pin(report),acceptance=_pin(acceptance));write_json(prior,payload)
        entry.update(previous_validation=_pin(prior),acceptance=_pin(acceptance))
    else:
        config_path=tmp_path/"prior-first-financial-config.json"
        config=json.loads(config_path.read_text());config["companies"][0]["history_manifest_sha256"]="0"*64
        write_json(config_path,config)
        acceptance_path=tmp_path/"prior-acceptance.json"
        acceptance=json.loads(acceptance_path.read_text());acceptance["first5_config"]=_pin(config_path);write_json(acceptance_path,acceptance)
        prior_path=Path(entry["previous_validation"]["path"]);prior=json.loads(prior_path.read_text())
        prior["historical_controls"]={"acceptance":_pin(acceptance_path),"config":_pin(config_path)};write_json(prior_path,prior)
        entry["acceptance"]=_pin(acceptance_path);entry["previous_validation"]=_pin(prior_path)
    write_json(path,value)
    with pytest.raises((ValueError,OSError)):
        resolve_storage_reuse(_pin(path),collection_manifest=Path(prepared.paths["collection"]),scope_companies=list(COHORT))



@pytest.mark.parametrize("v2",[False,True])
def test_ordinary_selected_history_and_storage_reuse_share_proof_without_decoder(tmp_path,monkeypatch,v2):
    from tests.screening.test_generic_metric_identity_integration import (
        FINANCIAL_AS_OF,
        _quarterly_analysis,
    )
    from tests.screening.test_history_selection import _selected_fixture
    from tests.screening.test_screening_metric_publication import _analysis_bundle

    prepared,companion,_=_selected_fixture(tmp_path,monkeypatch)
    collection=Path(prepared.paths["collection"])
    selection=json.loads(companion.read_text())["companies"][0]
    histories=[]
    for index,build_path in enumerate((collection.parent/"companies/FIVE/build_manifest.json",
                                       Path(selection["build_manifest"]["path"]))):
        build=json.loads(build_path.read_text())
        manifest=Path(build["history_manifest"])
        prior=tmp_path/f"combined-prior-storage-{index}.json"
        write_json(prior,{"version":1,"full_storage_validation":True,"validation_level":"DETAILED",
                          "publication_root":str(manifest.parent),"manifest_sha256":sha256_file(manifest),
                          "files":{name:{"sha256":digest} for name,digest in build["declared_files"].items()}})
        histories.append({"acceptance":selection["acceptance"],"previous_validation":_pin(prior),
                          "build_manifest":_pin(build_path),"history_manifest":_pin(manifest),
                          "payload_inventory":{str(path.relative_to(manifest.parent)):sha256_file(path)
                                               for path in manifest.parent.rglob("*") if path.is_file()}})
    storage_path=tmp_path/"combined-storage-reuse.json"
    write_json(storage_path,{"schema_version":"financial-history-storage-reuse-v1","status":"ROOT_APPROVED",
                            "collection_manifest":_pin(collection),"current_policy_source_sha256s":financial_storage_policy_sources(),
                            "companies":[{**COHORT[0],"histories":histories}]})
    if v2: _as_v2(storage_path)
    selected_manifest=Path(selection["history_manifest"]["path"])
    years=(2021,2022,2023,2024,2025)
    annual=_analysis_bundle(tmp_path/"combined-selected-annual",years,ticker="FIVE",cik=COHORT[0]["cik"],
                           financial_as_of=FINANCIAL_AS_OF,history_root=selected_manifest.parent)
    quarterly=_quarterly_analysis(tmp_path/"combined-selected-quarter",history_root=selected_manifest.parent,years=years)
    monkeypatch.setattr(history.HistoryPublicationReader,"verify_all",_forbidden)
    config=json.loads((tmp_path/"quality-config.json").read_text())
    config.update(history_selection=_pin(companion),storage_reuse=_pin(storage_path))
    config["source_provenance"][0]["history_manifest_sha256"]=sha256_file(selected_manifest)
    quality_config=tmp_path/"combined-quality-config.json";write_json(quality_config,config)
    quality=metric_quality.publish_generic_metric_quality(config_path=quality_config,
                collection_manifest=collection,source_binding_publication=tmp_path/"quality-bindings",
                history_manifests={"FIVE":selected_manifest},destination=tmp_path/"combined-quality",producer_revision="b"*40)
    config=json.loads(prepared.identity_config.read_text())
    config.update(history_selection=_pin(companion),storage_reuse=_pin(storage_path),quality_root=str(quality.root),
                  quality_manifest_sha256=sha256_file(quality.manifest_path))
    config["companies"][0].update(history_root=str(selected_manifest.parent),history_manifest_sha256=sha256_file(selected_manifest),
                                 annual_analysis_root=str(annual),annual_analysis_manifest_sha256=sha256_file(annual/"analysis_manifest.json"),
                                 quarterly_analysis_root=str(quarterly),quarterly_analysis_manifest_sha256=sha256_file(quarterly/"analysis_manifest.json"))
    identity_config=tmp_path/"combined-identity-config.json";write_json(identity_config,config)
    identity=metric_identity.publish_generic_metric_identity(identity_config,tmp_path/"combined-identity")
    reader=metric_identity.GenericMetricIdentityReader(identity.root)
    assert reader.companies[0]["history"]["root"]==str(selected_manifest.parent)
    assert reader.manifest["config"]["storage_reuse"]==_pin(storage_path)


def test_v2_resolves_storage_once_per_financial_preflight(tmp_path,monkeypatch):
    prepared,path=_proof(tmp_path,monkeypatch);diagnostics=_as_v2(path)
    config=json.loads((tmp_path/"quality-config.json").read_text());config["storage_reuse"]=_pin(path)
    from sec_xbrl import financial_storage_reuse as storage_module
    real=storage_module.resolve_storage_reuse
    count=0
    def resolve(*args,**kwargs):
        nonlocal count
        count+=1
        return real(*args,**kwargs)
    monkeypatch.setattr(storage_module,"resolve_storage_reuse",resolve)
    monkeypatch.setattr(history.HistoryPublicationReader,"verify_all",_forbidden)
    metric_quality._preflight_quality_inputs(config=config,collection_manifest=Path(prepared.paths["collection"]),
                                             history_manifests=prepared.histories)
    assert count==1
    assert all(path.exists() for path in diagnostics)


@pytest.mark.parametrize("v2",[False,True])
def test_retained_diagnostic_content_policy_is_explicit(tmp_path,monkeypatch,v2):
    prepared,path=_proof(tmp_path,monkeypatch)
    diagnostic=prepared.histories["FIVE"].parent/".chunks/quarter-spill.records"
    if v2: _as_v2(path)
    else:
        diagnostic.parent.mkdir();diagnostic.write_bytes(b"retained")
        value=json.loads(path.read_text());value["companies"][0]["histories"][0]["payload_inventory"][".chunks/quarter-spill.records"]=sha256_file(diagnostic);write_json(path,value)
    proof=resolve_storage_reuse(_pin(path),collection_manifest=Path(prepared.paths["collection"]),scope_companies=list(COHORT))
    entry=storage_history(proof,"FIVE",prepared.histories["FIVE"])
    diagnostic.write_bytes(b"changed body")
    if v2:
        verify_financial_history_source(prepared.histories["FIVE"].parent,storage_entry=entry)
    else:
        with pytest.raises(ValueError,match="changed"):
            verify_financial_history_source(prepared.histories["FIVE"].parent,storage_entry=entry)


@pytest.mark.parametrize("defect",["core","alias","unknown","listed_unknown","missing_diagnostic","active_excluded","scope"])
def test_v2_retained_diagnostic_policy_still_rejects_unsafe_or_changed_governed_sources(tmp_path,monkeypatch,defect):
    prepared,path=_proof(tmp_path,monkeypatch);diagnostics=_as_v2(path)
    value=json.loads(path.read_text());entry=value["companies"][0]["histories"][0]
    root=prepared.histories["FIVE"].parent
    if defect=="core":
        name=next(name for name in entry["payload_inventory"] if name!="history_manifest.json");(root/name).write_bytes(b"changed")
    elif defect=="alias":
        diagnostic=next(iter(diagnostics));diagnostic.unlink();diagnostic.symlink_to(path)
    elif defect in {"unknown","listed_unknown"}:
        (root/"unknown.txt").write_text("unknown")
        if defect=="listed_unknown": entry["retained_diagnostics"].append("unknown.txt");entry["retained_diagnostics"].sort()
    elif defect=="missing_diagnostic": next(iter(diagnostics)).unlink()
    elif defect=="active_excluded": entry["retained_diagnostics"].append("history_manifest.json");entry["retained_diagnostics"].sort()
    else: value["diagnostic_policy"]="SKIP_ANYTHING"
    write_json(path,value)
    with pytest.raises(ValueError):
        resolve_storage_reuse(_pin(path),collection_manifest=Path(prepared.paths["collection"]),scope_companies=list(COHORT))


def test_invocation_storage_proof_cannot_be_mutated_or_cross_bound(tmp_path,monkeypatch):
    prepared,path=_proof(tmp_path,monkeypatch);_as_v2(path)
    collection=Path(prepared.paths["collection"])
    proof=resolve_storage_reuse(_pin(path),collection_manifest=collection,scope_companies=list(COHORT))
    proof.companies["FIVE"]["histories"][0]["retained_diagnostics"].append("forged")
    with pytest.raises(ValueError,match="untrusted|mutated"):
        operations.read_universe_status(manifest_path=collection,validation_mode="financial_sources",storage_reuse=_pin(path),_verified_storage_reuse=proof)
