"""Strict parent-quality subset reuse is separately approved before financial publication."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sec_xbrl import financial_native_source as native
from sec_xbrl import financial_storage_reuse as storage
from sec_xbrl import history, metric_quality
from sec_xbrl.history_validation import validation_code_identity
from sec_xbrl.metrics.quarterly_screening import publish_quarterly_screening_metrics
from sec_xbrl.metrics.screening import publish_screening_metrics
from sec_xbrl.screening import dataset_v3, metric_identity
from sec_xbrl.screening.common import digest_value, read_json, sha256_file, write_json
from sec_xbrl.screening.dataset_v2 import publish_screening_dataset_v2
from tests.screening.test_financial_native_source import _fixture
from tests.screening.test_financial_storage_reuse import _pin
from tests.unit.test_source_bindings import _quality_config


def _preparation(tmp_path, monkeypatch):
    old_config, old_packet, _ = _fixture(tmp_path, monkeypatch, outside_ready=True)
    old = read_json(old_packet)
    request = read_json(Path(old["parents"]["identity"]["path"]))["config"]
    collection = Path(request["collection_manifest"])
    selected_storage = read_json(Path(old["storage_reuse"]["path"]))
    origin = Path(old["source"]["old_root"])
    build_path = collection.parent / "companies/SIX/build_manifest.json"
    build = read_json(build_path)
    manifest = Path(build["history_manifest"])
    root = manifest.parent
    result = history.HistoryPublicationReader(root).validate(mode="routine", state_root=tmp_path / "six-validation")
    report = Path(result.state_path)
    body = read_json(report)
    body["code_identity"] = validation_code_identity(sources=tuple(sorted(origin.rglob("*.py"))), rules=storage.history_validation_rules(read_json(manifest)))
    write_json(report, body)
    build["storage_validation"] = {"level": result.level, "reason": result.reason, "report": result.state_path, "detailed_fallback": False}
    write_json(build_path, build)
    acceptance = tmp_path / "six-acceptance.json"
    write_json(acceptance, {"status": "ROOT_APPROVED", "kind": "ACCEPTED_CURRENT_ROUTINE_HISTORY",
                           "build_manifest": _pin(build_path), "history_manifest": _pin(manifest), "validation_report": _pin(report)})
    prior = tmp_path / "six-routine.json"
    write_json(prior, {"schema_version": "accepted-financial-storage-evidence-v1", "kind": "ACCEPTED_CURRENT_ROUTINE_HISTORY",
                       "history_manifest": _pin(manifest), "build_manifest": _pin(build_path),
                       "declared_payload_sha256s": build["declared_files"],
                       "historical_controls": {"acceptance": _pin(acceptance), "report": _pin(report)}})
    parent_storage = deepcopy(selected_storage)
    parent_storage["companies"].append({"ticker": "SIX", "cik": "0000000456", "histories": [{
        "acceptance": _pin(acceptance), "previous_validation": _pin(prior), "build_manifest": _pin(build_path),
        "history_manifest": _pin(manifest), "payload_inventory": {str(p.relative_to(root)): sha256_file(p) for p in root.rglob('*') if p.is_file()},
        "retained_diagnostics": []}]})
    parent_path = tmp_path / "parent-storage.json"; write_json(parent_path, parent_storage)
    histories = {"FIVE": Path(request["companies"][0]["history_root"]) / "history_manifest.json", "SIX": manifest}
    qconfig = _quality_config({"collection": collection}, histories, tmp_path / "quality-two.json",
        companies=({"ticker": "FIVE", "cik": "0000000123"}, {"ticker": "SIX", "cik": "0000000456"}))
    q = read_json(qconfig); q.update(financial_as_of=request["financial_as_of"], storage_reuse=_pin(parent_path)); write_json(qconfig, q)
    old_policy = parent_storage["current_policy_source_sha256s"]
    with monkeypatch.context() as producer:
        producer.setattr(storage, "financial_storage_policy_sources", lambda: old_policy)
        producer.setattr(storage, "current_history_validation_identity", lambda m: validation_code_identity(sources=tuple(sorted(origin.rglob('*.py'))), rules=storage.history_validation_rules(m)))
        quality = metric_quality.prepare_generic_metric_quality(config_path=qconfig, collection_manifest=collection,
            package_root=tmp_path / "mixed-packages", source_index_destination=tmp_path / "quality-two-indexes",
            source_binding_destination=tmp_path / "quality-two-bindings", history_manifests=histories,
            destination=tmp_path / "quality-two", producer_revision=native.PRODUCER)
    request.update(quality_root=str(quality.root), quality_manifest_sha256=sha256_file(quality.manifest_path))
    baseline = native._inventory(native._SOURCE_ROOT)
    monkeypatch.setattr(native, "_PREPARATION_BASELINE", digest_value(baseline))
    # The approved original occurrence input contains both companies. The selected
    # projection is a reference-only subset; no builder execution occurs here.
    rows = []
    for company in read_json(quality.manifest_path)["collection_status"]:
        intake = {"path": company["intake_manifest_path"], "sha256": company["intake_sha256"]}
        for index, entry in enumerate(read_json(Path(intake['path']))['filings']):
            scope = {"entry": entry, "cik": company['cik'], "accession": entry['filing']['accession'],
                     "intake": intake, "financial_as_of": request['financial_as_of'],
                     "builder_sha256": old['source']['old_files']['metrics/statement_metric_evidence.py']}
            checkpoint = tmp_path / f"input-{company['cik']}-{index}.json"
            write_json(checkpoint, {"input": scope, "records": []})
            rows.append({"scope": scope, "checkpoint": _pin(checkpoint), "admitted_records": 0})
    inputs = tmp_path / "parent-occurrences.json"
    write_json(inputs, {"evidence": old['statement_metric_evidence'], "admitted_records": 0, "selected_filings": rows})
    packet = native.prepare_native_preparation_packet(identity_config=request, old_source_root=origin,
        consumer_baseline_files=baseline, occurrence_inputs=_pin(inputs), financial_producer_revision='f' * 40,
        destination=tmp_path / "preparation.json")
    approval = tmp_path / "preparation-approval.json"
    write_json(approval, {"schema_version": native.PREPARATION_APPROVAL, "status": "ROOT_APPROVED_NATIVE_PREPARATION", "packet": _pin(packet)})
    declaration = {"packet": _pin(packet), "approval": _pin(approval)}
    request['native_preparation'] = declaration
    return request, declaration, old_config, old


def test_preparation_public_financial_chain_skips_quality_replay_and_excluded_history(tmp_path, monkeypatch):
    request, declaration, old_config, old = _preparation(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError('completed quality/routine must not execute again')
    monkeypatch.setattr(metric_quality.GenericMetricQualityReader, 'verify_sources', forbidden)
    monkeypatch.setattr(history.HistoryPublicationReader, 'validate', forbidden)
    from sec_xbrl.screening import verified_source_closure as closure
    status_history = closure._add_status_history
    def selected_only(collector, build, role):
        assert build.get("ticker") != "SIX", "excluded History must not be visited"
        return status_history(collector, build, role)
    monkeypatch.setattr(closure, "_add_status_history", selected_only)
    config = tmp_path / 'identity-nine.json'; write_json(config, request)
    identity = metric_identity.publish_generic_metric_identity(config, tmp_path / 'identity-nine')
    source = {"kind": metric_identity.SOURCE_KIND, "root": str(identity.root), "manifest_sha256": sha256_file(identity.manifest_path)}
    metric_config = read_json(Path(old['parents']['annual_metrics']['path']))['config']; metric_config['identity_source'] = source
    mc = tmp_path / 'metrics-nine.json'; write_json(mc, metric_config)
    with native.use_native_preparation(declaration):
        metrics = publish_screening_metrics(mc, tmp_path / 'metrics-nine')
        ac = tmp_path / 'annual-nine.json'
        annual_config = read_json(Path(old['parents']['annual_dataset']['path']))['config']
        annual_config.update(identity_source=source, metric_root=str(metrics.root), metric_manifest_sha256=sha256_file(metrics.manifest_path))
        write_json(ac, annual_config)
        annual = publish_screening_dataset_v2(ac, tmp_path / 'annual-nine')
        qc = tmp_path / 'quarter-nine.json'
        quarter_config = read_json(Path(old['parents']['quarterly_metrics']['path']))['config']
        quarter_config.update(source_commit_sha='f' * 40, annual_metric_root=str(metrics.root), annual_metric_manifest_sha256=sha256_file(metrics.manifest_path))
        write_json(qc, quarter_config)
        quarter = publish_quarterly_screening_metrics(qc, tmp_path / 'quarter-nine')
    parents = {'identity': _pin(identity.manifest_path), 'annual_metrics': _pin(metrics.manifest_path),
               'annual_dataset': _pin(annual.manifest_path), 'quarterly_metrics': _pin(quarter.manifest_path)}
    packet = native.prepare_native_source_packet(parents=parents, old_source_root=Path(old['source']['old_root']),
        preparation=declaration, destination=tmp_path / 'final-native.json')
    body = read_json(packet)
    assert body['producer_revision'] == native.PRODUCER and body['financial_producer_revision'] == 'f' * 40
    assert body['schema_version'] == native.VERSION_V3
    approval = tmp_path / 'final-approval.json'; write_json(approval, {'schema_version': native.APPROVAL_VERSION_V3,
        'status': 'ROOT_APPROVED_NATIVE_SOURCE_TRANSITION', 'packet': _pin(packet)})
    combined = {**old_config, 'native_source': {'packet': _pin(packet), 'approval': _pin(approval)},
                'annual_dataset_root': str(annual.root), 'annual_manifest_sha256': parents['annual_dataset']['sha256'],
                'quarterly_metric_root': str(quarter.root), 'quarterly_manifest_sha256': parents['quarterly_metrics']['sha256']}
    cp = tmp_path / 'combined-nine.json'; write_json(cp, combined)
    root = dataset_v3.publish_screening_dataset_v3(cp, tmp_path / 'combined-nine')
    assert len(dataset_v3.ScreeningDatasetV3Reader(root).companies) == 1
    assert native.native_controls() == ({}, ())


def test_preparation_scope_negative_reset_and_unknown_producer(tmp_path, monkeypatch):
    request, declaration, _config, _old = _preparation(tmp_path, monkeypatch)
    with native.use_native_preparation(declaration, config=request):
        assert native.native_controls()[0]
        with native.use_native_preparation(None):
            assert native.native_controls() == ({}, ())
        assert native.native_controls()[0]
        with pytest.raises(RuntimeError), native.use_native_preparation(declaration):
            raise RuntimeError('fixture')
        assert native.native_controls()[0]
    assert native.native_controls() == ({}, ())
    with pytest.raises(ValueError), native.use_native_source(declaration):
        pass
    bad = deepcopy(request); bad['companies'][0]['display_years'] = [2025]
    with pytest.raises(ValueError, match='request'), native.use_native_preparation(declaration, config=bad):
        pass
    payload = read_json(Path(declaration['packet']['path']))
    for field, value in [('ciks', ['0000000456']), ('selected_occurrences', []), ('producer_revision', '0' * 40), ('quality', {**payload['quality'], 'sha256': '0' * 64}), ('routines', [])]:
        invalid = deepcopy(payload); invalid[field] = value
        with pytest.raises(ValueError):
            native._preparation_controls(invalid)



def test_preparation_source_qualification_rejects_math_and_identity_core_changes(tmp_path, monkeypatch):
    baseline = native._inventory(native._SOURCE_ROOT)
    monkeypatch.setattr(native, '_PREPARATION_BASELINE', digest_value(baseline))
    native.qualified_preparation_consumer_files(baseline, baseline)
    changed = {**baseline, 'metrics/screening.py': '0' * 64}
    with pytest.raises(ValueError, match='unqualified financial'):
        native.qualified_preparation_consumer_files(baseline, changed)
    root = tmp_path/'source'; (root/'screening').mkdir(parents=True)
    source = (native._SOURCE_ROOT/'screening/metric_identity.py').read_text()
    source += '\ndef _years(value, field, count): return [2025]\n'
    (root/'screening/metric_identity.py').write_text(source)
    monkeypatch.setattr(native, '_SOURCE_ROOT', root)
    with pytest.raises(ValueError, match='identity core'):
        native.qualified_preparation_consumer_files(baseline, baseline)
