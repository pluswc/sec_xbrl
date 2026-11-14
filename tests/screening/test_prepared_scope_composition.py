"""Read-only source qualification preserves old100 and composes a third delta."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sec_xbrl import financial_native_source as native
from sec_xbrl.metrics.quarterly_screening import _observation_id
from sec_xbrl.screening import cohort_union as union
from sec_xbrl.screening import governed_delta as delta
from sec_xbrl.screening.common import read_json, write_json
from sec_xbrl.screening.runtime_projection import (
    hydrate_observation,
    observation_rows,
    publish_runtime_projection,
)
from sec_xbrl.screening.service import ScreeningService
from tests.screening.test_cohort_union import _member, _pin
from tests.screening.test_governed_delta import _parent
from tests.screening.test_native_eight_consumers import _adopt, _other_parent


def _third_parent(tmp_path):
    members = []
    for index in (1, 2):
        _, source = _member(tmp_path, index)
        source.metadata = [r for r in source.metadata if r['financial_prepared']]
        old, new = f'{index:010d}', f'{index + 4:010d}'
        def renumber(value, old=old, new=new):
            if isinstance(value, dict):
                return {k: renumber(v) for k, v in value.items()}
            if isinstance(value, list):
                return [renumber(v) for v in value]
            return value.replace(old, new) if isinstance(value, str) else value
        for name in ('manifest','companies','metadata','observations','quarter_observations','metric_support','quarter_support','quarter_period_inventory'):
            setattr(source, name, renumber(getattr(source, name)))
        source.quarterly.manifest = renumber(source.quarterly.manifest)
        manifest = source.root/'screening_dataset_manifest.json';write_json(manifest, source.manifest)
        source._manifest_sha256 = _pin(manifest)['sha256']
        projected = publish_runtime_projection(source.root, tmp_path/f'p{index}',tmp_path/'new-blobs',reader=source)
        members.append({'dataset_manifest':_pin(manifest),'projection':_pin(projected)})
    config = tmp_path/'parent9.json';write_json(config, {'schema_version':union.CONFIG_VERSION,'dataset_id':'parent9','members':members,'expose_auxiliary_owners':True})
    root = union.publish_cohort_union(config,tmp_path/'parent9');pin=_pin(root/union.MANIFEST)
    return root,pin,union.ScreeningCohortUnionReader(root,pin)


def test_retained100_with_explicit_source_override_and_three_member109(tmp_path, monkeypatch):
    old=tmp_path/'old';old.mkdir();pr,pp,parent=_parent(old,latest=True)
    config=read_json(pr/union.MANIFEST)['config'];config['expose_auxiliary_owners']=True
    cp=old/'owners.json';write_json(cp,config);pr=union.publish_cohort_union(cp,old/'owner-parent');pp=_pin(pr/union.MANIFEST);parent=union.ScreeningCohortUnionReader(pr,pp)
    cik='0000000001';owner=parent._owners[cik]
    qp=Path(owner.manifest['config']['quarterly_metric_root'])/'quarterly_screening_metric_manifest.json'
    company=read_json(qp)['config']['companies'][0]
    request={'cik':cik,'ticker':'T1','owner_manifest':_pin(owner.root/'screening_dataset_manifest.json'),'quarterly_manifest':_pin(qp),'analysis_manifest':_pin(Path(company['analysis_root'])/'analysis_manifest.json')}
    anchor={**parent.latest_source_period_guards[cik],'bucket_status':'PERIOD_AVAILABLE','filed_date':'2026-10-23'}
    records=[]
    for row in observation_rows(parent,quarterly=True,cik=cik,year=2026,quarter=3):
        full=hydrate_observation(parent,row,quarterly=True)
        item={**deepcopy(full),'calendar_quarter':4,'fiscal_year':2027,'fiscal_quarter':'Q1','period_end':anchor['period_end'],
              'period_start':anchor['period_start'] if row['period_class']=='QTD_3M' else row.get('period_start')}
        item['observation_id']=_observation_id(item);records.append(item)
    monkeypatch.setattr(delta,'prepare_latest_quarter',lambda **_:(records,[anchor],[]))
    r92,d92,_a92=_adopt(old,pp,parent,'old92',request)
    fresh=tmp_path/'eight';fresh.mkdir();p8,p8pin,parent8=_other_parent(fresh);r8,d8,_a8=_adopt(fresh,p8pin,parent8,'old8')
    c100={'schema_version':union.CONFIG_VERSION_V2,'dataset_id':'old100','expose_auxiliary_owners':True,
          'members':[{'kind':'GOVERNED_DELTA','declaration':d} for d in (d92,d8)]}
    cp=tmp_path/'old100.json';write_json(cp,c100);r100=union.publish_cohort_union(cp,tmp_path/'100');pin100=_pin(r100/union.MANIFEST)
    original=union.ScreeningCohortUnionReader(r100,pin100);original_rows=observation_rows(original,quarterly=True,latest=True)
    from tests.screening.test_runtime_projection import _condition
    prior_service=ScreeningService({'old100':r100,'old92':r92,'old8':r8,'parent':pr,'other-parent':p8},tmp_path/'private.sqlite',
        cohort_unions={'old100':pin100,'parent':pp,'other-parent':p8pin},governed_deltas={'old92':d92,'old8':d8})
    definition=next(d for d in original.metric_definitions if d['metric_id']=='revenue')
    saved=prior_service.create_screen('old100 saved',_condition({'mode':'FIXED_FISCAL_YEAR','fiscal_year':2025},definition),dataset_id='old100')
    run=prior_service.execute(saved['revision_id'],'old100'); original_run=prior_service.run(run['run_id'])
    original_trace=prior_service.trace(run['run_id'],cik=cik,metric_id='revenue')
    origin=delta._source_hashes();current={**origin,'screening/cohort_union.py':'9'*64}
    monkeypatch.setattr(delta,'_source_hashes',lambda source_root=None: current if source_root is None else origin)
    baseline={k:v for k,v in origin.items() if k.endswith('.py')};monkeypatch.setattr(native,'_PREPARATION_BASELINE',native.digest_value(baseline))
    def qualify(declaration,name):
        receipt=tmp_path/f'{name}-reader.json'
        body={'schema_version':'governed-delta-reader-source-transition-v2','status':'ROOT_APPROVED_READER_ONLY_SOURCE_TRANSITION',
              'manifest':declaration['manifest'],'approval':declaration['approval'],'origin_source_root':str(tmp_path),
              'origin_implementation_sources':origin,'current_implementation_sources':current,
              'consumer_baseline_files':baseline,'previous_declaration':declaration}
        write_json(receipt,body);return {**declaration,'reader_source_transition':_pin(receipt)}
    q92,q8=qualify(d92,'92'),qualify(d8,'8')
    shared92=delta.ScreeningGovernedDeltaReader(r92,q92,parent=parent);shared8=delta.ScreeningGovernedDeltaReader(r8,q8,parent=parent8)
    with pytest.raises(ValueError,match='current source'):
        union.ScreeningCohortUnionReader(r100,pin100)
    kept=union.ScreeningCohortUnionReader(r100,pin100,shared_readers=(shared92,shared8))
    assert observation_rows(kept,quarterly=True,latest=True)==original_rows
    assert _pin(r100/union.MANIFEST)==pin100
    extra=tmp_path/'nine';extra.mkdir();p9,p9pin,parent9=_third_parent(extra);r9,d9,_a9=_adopt(extra,p9pin,parent9,'new9')
    cfg={'schema_version':union.CONFIG_VERSION_V2,'dataset_id':'new109','expose_auxiliary_owners':True,
         'members':[{'kind':'GOVERNED_DELTA','declaration':d} for d in (q92,q8,d9)],'retained_unions':[pin100]}
    cp=tmp_path/'109.json';write_json(cp,cfg);r109=union.publish_cohort_union(cp,tmp_path/'109');pin109=_pin(r109/union.MANIFEST)
    service=ScreeningService({'new109':r109,'old100':r100,'old92':r92,'old8':r8,'new9':r9,'parent':pr,'other-parent':p8,'parent9':p9},tmp_path/'private.sqlite',
        cohort_unions={'new109':pin109,'old100':pin100,'parent':pp,'other-parent':p8pin,'parent9':p9pin},governed_deltas={'old92':q92,'old8':q8,'new9':d9})
    assert len(service.datasets['new109'].companies)==6
    assert service.run(run['run_id'])==original_run
    assert service.trace(run['run_id'],cik=cik,metric_id='revenue')==original_trace
    assert observation_rows(service.datasets['old100'],quarterly=True,latest=True)==original_rows
    assert service.quarter_series('new109',cik=cik,metric_id='quarter_revenue',latest=True)['observations'][-1]['calendar_quarter']==4
    contexts=service.datasets['new109'].manifest['auxiliary_contexts']
    retained=next(x for x in contexts if x['scope']['dataset_id']=='old100')
    assert retained['scope']['dataset_manifest_sha256']==pin100['sha256']
    assert retained['ciks']==sorted(original._owners)
    for c in original._owners:
        assert service.datasets['new109'].manifest['auxiliary_owners'][c]==original.manifest['auxiliary_owners'][c]
    assert native.native_controls()==({},())
    bad=deepcopy(d92);bad['approval']=d8['approval']
    assert not delta.shared_reader_declaration_matches(shared92,bad)



def test_single_cohort_parent_alias_is_explicit_and_adopts_without_second_financial_group(tmp_path):
    member, original = _member(tmp_path, 1)
    config = {'schema_version': union.CONFIG_VERSION, 'dataset_id': 'single9',
              'members': [member], 'expose_auxiliary_owners': True}
    path = tmp_path/'single.json'
    write_json(path, config)
    with pytest.raises(ValueError, match='at least two'):
        union.publish_cohort_union(path, tmp_path/'default-rejected')
    config['allow_single_member'] = True; write_json(path, config)
    root = union.publish_cohort_union(path, tmp_path/'single9')
    pin = _pin(root/union.MANIFEST); parent = union.ScreeningCohortUnionReader(root, pin)
    assert len(parent._members) == 1 and len(parent.companies) == 1
    assert observation_rows(parent, quarterly=True) == parent._members[0].rows(quarterly=True)
    assert parent.manifest['auxiliary_owners']['0000000001']['dataset_publication_id'] == original.publication_id
    _root, _declaration, adopted = _adopt(tmp_path, pin, parent, 'new9-adopted')
    for row in observation_rows(adopted, metric_id='revenue_yoy'):
        previous = observation_rows(parent, cik=row['cik'], metric_id='revenue_yoy', year=row['fiscal_year'])[0]
        assert row['value'] == previous['value'] and row['original_observation']['id'] == previous['metric_observation_id']
    config['schema_version'] = union.CONFIG_VERSION_V2
    with pytest.raises(ValueError, match='single-cohort'):
        union._open_members(config)
