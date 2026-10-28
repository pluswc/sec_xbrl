"""Explicit arithmetic TTM policy over reused small prepared-quarter fixtures."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics import quarterly_screening as producer
from sec_xbrl.metrics.screening import digest_value, sha256_file, write_json
from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader
from tests.screening.test_quarterly50_expansion import _inputs, _publication, _records, _row
from tests.screening.test_quarterly_screening_producer import (
    AS_OF,
    CIK,
    _four_quarters_with_derived_q4,
    _profile_rows,
)
from tests.screening.test_screening_quarterly_consumer import _quarter_service

NEW = producer.ARITHMETIC_CATALOG_VERSION


def _null_inputs(inputs=None):
    result = inputs or _inputs()
    def clear(value):
        if isinstance(value, list):
            for item in value: clear(item)
        elif isinstance(value, dict):
            if "basis_version" in value: value["basis_version"] = None
            for item in value.values(): clear(item)
    clear(result[1]);clear(result[2])
    return result


def test_all_nine_arithmetic_ttm_are_available_without_inventing_basis_and_strict_stays_unavailable():
    inputs = _null_inputs()
    strict, _ = _records(copy.deepcopy(inputs))
    arithmetic, _ = _records(copy.deepcopy(inputs), catalog_version=NEW)
    assert [row for row in strict if not row["metric_id"].startswith("ttm_")] == [
        row for row in arithmetic if not row["metric_id"].startswith("ttm_")]
    expected = {"ttm_revenue":"1000","ttm_operating_income":"55","ttm_net_income":"40",
                "ttm_cfo":"160","ttm_standardized_fcf":"120","ttm_gross_margin":"30",
                "ttm_operating_margin":"5.5","ttm_net_margin":"4","ttm_fcf_margin":"12"}
    for metric, value in expected.items():
        assert _row(strict, metric)["availability_status"] == "UNAVAILABLE"
        row = _row(arithmetic, metric)
        assert row["value"] == value
        assert row["basis_version"] is None
        assert row["source_lineage"]["compatibility_policy"] == producer.ARITHMETIC_POLICY
        assert all(item["basis_version"] is None for item in row["source_lineage"]["derivation_inputs"])
    assert _row(arithmetic,"ttm_gross_margin")["source_lineage"]["period_sums"] == {
        "NUMERATOR":"300","DENOMINATOR":"1000"}
    assert _row(arithmetic,"quarter_cash")["value"] == "40"
    assert all(item["definition_version"] != producer.DEFINITION_BY_ID[item["metric_id"]]["definition_version"]
               for item in producer.quarterly_metric_definitions(NEW) if item["observation_basis"] == "TTM")


@pytest.mark.parametrize("basis", [None,"stable-basis"])
def test_new_catalog_opens_in_both_readers_and_retains_declared_or_arithmetic_assurance(tmp_path,basis):
    inputs = _null_inputs() if basis is None else _inputs()
    root = _publication(tmp_path,inputs=inputs,catalog_version=NEW)
    assert len(producer.QuarterlyMetricReader(root).definitions) == 41
    wire = QuarterlyScreeningMetricReader(root)
    expected = producer.ARITHMETIC_POLICY if basis is None else "DECLARED_BASIS:"+basis
    for metric in ("ttm_revenue","ttm_fcf_margin"):
        assert _row(wire.observations,metric)["source_lineage"]["compatibility_policy"] == expected


@pytest.mark.parametrize("defect", ["mixed","mismatch","empty","quality","continuity","recast","structural",
                                    "review","unit","mapping","dimensions","gap","missing","ytd","capex_sign"])
def test_arithmetic_ttm_still_rejects_incompatible_cfo_capex_and_quarter_scope(defect):
    columns,cells,traces = _null_inputs()
    cell=next(row for row in cells if row["cell_id"] == "cell-capex2026-Q2")
    trace=next(row for row in traces if row["cell_id"] == cell["cell_id"])
    lineage=trace["value_lineage"]
    if defect in {"mixed","mismatch","empty"}:
        if defect == "mismatch":
            for row in cells: row["basis_version"] = "basis-A"
            for row in traces: row["value_lineage"]["basis_version"] = "basis-A"
        cell["basis_version"] = lineage["basis_version"] = "" if defect == "empty" else "basis-B"
    elif defect in {"quality","continuity","recast","structural","review"}:
        field={"quality":"quality_blocking","continuity":"continuity_break","recast":"recast_break",
               "structural":"structural_break","review":"mapping_review_required"}[defect]
        lineage[field] = True
    elif defect == "unit":
        cell["unit"] = ['["iso4217:EUR"]',"[]"]
        lineage["unit_numerator_measures"] = ["iso4217:EUR"]
    elif defect == "mapping": lineage["concept_mapping_version"] = "other-mapping"
    elif defect == "dimensions": lineage["canonical_dimension_signature"] = ["segment"]
    elif defect == "gap": cell["start"] = lineage["context_start_date"] = "2026-04-02"
    elif defect == "missing": cells.remove(cell);traces.remove(trace)
    elif defect == "ytd": cell["period_class"] = lineage["period_class"] = "YTD_6M"
    else: cell["value"] = lineage["value_numeric"] = "-10"
    rows,_ = _records((columns,cells,traces),catalog_version=NEW)
    assert _row(rows,"ttm_standardized_fcf")["availability_status"] == "UNAVAILABLE"
    assert _row(rows,"ttm_fcf_margin")["availability_status"] == "UNAVAILABLE"


def test_arithmetic_ttm_preserves_eligible_derived_q4_and_full_reported_anchors():
    columns,cells,traces = _null_inputs(_four_quarters_with_derived_q4())
    rows,_=producer.build_quarterly_company_records(ticker="TEST",cik=CIK,financial_as_of=AS_OF,
        columns=columns,rows=_profile_rows(),cells=cells,traces=traces,
        spine=producer._quarter_spine(AS_OF),catalog_version=NEW)
    row=_row(rows,"ttm_revenue",2025,4)
    assert row["value"] == "1200" and row["basis_version"] is None
    quarter=row["source_lineage"]["derivation_inputs"][-1]
    assert quarter["source_kind"] == "DERIVED_QUARTER"
    assert len(quarter["source_lineage"]["derivation_inputs"]) == 2
    assert quarter["source_lineage"]["formula"] == "FY - YTD_9M"


@pytest.mark.parametrize("defect", ["assurance","definition","catalog","nested_capex_basis","nested_quality","period"])
def test_new_consumer_rejects_rehashed_contract_or_lineage_mutation(tmp_path,defect):
    def mutate(rows):
        row=_row(rows,"ttm_fcf_margin")
        if defect == "assurance": row["source_lineage"]["compatibility_policy"] = "DECLARED_BASIS:fake"
        elif defect == "nested_capex_basis":
            row["source_lineage"]["derivation_inputs"][0]["source_lineage"]["derivation_inputs"][1]["basis_version"]="fake"
        elif defect == "nested_quality":
            row["source_lineage"]["derivation_inputs"][0]["source_lineage"]["derivation_inputs"][1]["quality_blocking"]=True
        elif defect == "period": row["source_lineage"]["derivation_inputs"][0]["period_class"]="YTD_6M"
    root=_publication(tmp_path,inputs=_null_inputs(),catalog_version=NEW,mutate=mutate)
    if defect in {"catalog","definition"}:
        path=root/producer.MANIFEST;manifest=json.loads(path.read_text())
        if defect == "catalog": manifest["catalog_version"]=producer.CATALOG_VERSION
        else:
            definition_path=root/producer.DEFINITIONS_FILE;value=json.loads(definition_path.read_text())
            next(row for row in value["records"] if row["metric_id"]=="ttm_revenue")["definition_version"]="quarter-ttm-v1"
            write_json(definition_path,value)
            manifest["files"][producer.DEFINITIONS_FILE].update(sha256=sha256_file(definition_path),size=definition_path.stat().st_size)
        write_json(path,manifest)
    with pytest.raises(ValueError): QuarterlyScreeningMetricReader(root)


def test_new_consumer_preserves_materialized_ratio_without_recalculating(tmp_path):
    def mutate(rows): _row(rows,"ttm_fcf_margin")["value"]="12.00000000000000000000000000000001"
    root=_publication(tmp_path,inputs=_null_inputs(),catalog_version=NEW,mutate=mutate)
    assert _row(QuarterlyScreeningMetricReader(root).observations,"ttm_fcf_margin")["value"]=="12.00000000000000000000000000000001"


def test_public_config_cli_defaults_and_explicit_new_catalog_roundtrip(tmp_path,monkeypatch,capsys):
    columns,cells,traces=_null_inputs()
    records={"columns":columns,"core_rows":_profile_rows(),"core_cells":cells,
             **{f"trace_{digit}":traces if digit=="0" else [] for digit in "0123456789abcdef"}}
    class Client:
        def _records(self,ticker,view,name): return copy.deepcopy(records[name])
    annual=tmp_path/"annual";annual.mkdir();annual_manifest=annual/"screening_metric_manifest.json"
    write_json(annual_manifest,{})
    monkeypatch.setattr(producer,"ScreeningMetricReader",lambda root:SimpleNamespace(manifest={
        "publication_id":"accepted-small-annual","financial_as_of":AS_OF,"configured_ciks":[CIK]}))
    monkeypatch.setattr(producer,"_open_company_source",lambda *args:(Client(),{
        "kind":"QUARTERLY_ANALYSIS_PUBLICATION","ticker":"TEST","cik":CIK,
        "publication_id":"prepared-small-quarter","manifest_sha256":"a"*64,"declared_files":[]}))
    config={"schema_version":producer.CONFIG_VERSION,"financial_as_of":AS_OF,"source_commit_sha":"b"*40,
            "annual_metric_root":str(annual),"annual_metric_manifest_sha256":sha256_file(annual_manifest),
            "companies":[{"ticker":"TEST","cik":CIK,"analysis_root":"/controlled-prepared-source",
                          "analysis_manifest_sha256":"c"*64}]}
    config_path=tmp_path/"strict-config.json";write_json(config_path,config)
    assert "catalog_version" not in producer._validate_config(config)
    strict=producer.publish_quarterly_screening_metrics(config_path,tmp_path/"strict")
    assert _row(producer.QuarterlyMetricReader(strict.root).observations,"ttm_revenue")["value"] is None
    new_config=tmp_path/"new-config.json";write_json(new_config,{**config,"catalog_version":NEW})
    destination=tmp_path/"arithmetic"
    assert producer.main(["publish","--config",str(new_config),"--destination",str(destination),
                          "--catalog-version",NEW])==0
    wire=QuarterlyScreeningMetricReader(destination)
    assert _row(wire.observations,"ttm_revenue")["value"]=="1000"
    assert wire.manifest["config"]["catalog_version"]==NEW
    assert wire.manifest["publication_id"] != strict.publication_id
    assert json.loads(capsys.readouterr().out)["root"]==str(destination)
    with pytest.raises(SystemExit):
        producer.main(["publish","--config",str(config_path),"--destination",str(tmp_path/"wrong"),
                       "--catalog-version",NEW])
    with pytest.raises(ValueError): producer._validate_config({**config,"catalog_version":"unknown"})


def test_new_ttm_screen_uses_new_definition_and_preserves_existing_saved_context(tmp_path):
    service=_quarter_service(tmp_path)
    old=service.datasets["synthetic-v3"]
    content={"universe":{"mode":"ALL_PREPARED"},"predicates":[{"metric_id":"quarter_revenue","operator":"GTE",
             "threshold":"0","definition_version":"quarter-reported-core-v1"}],
             "period_policy":{"mode":"FIXED_CALENDAR_QUARTER_END","calendar_year":2026,"calendar_quarter":3},
             "columns":["company","aggregate","predicates"],"sort":{"column":"ticker","direction":"ASC"}}
    revision=service.create_screen("기존",content,dataset_id="synthetic-v3")
    old_run=service.execute(revision["revision_id"],"synthetic-v3")
    publication=tmp_path/"new-publication";publication.mkdir()
    wire=QuarterlyScreeningMetricReader(_publication(publication,inputs=_null_inputs(),catalog_version=NEW))
    current=copy.copy(old);current.manifest=copy.deepcopy(old.manifest)
    current.manifest["dataset_id"]="arithmetic-v3";current.publication_id="new-arithmetic-dataset"
    current.manifest["versions"]["quarterly_publication_id"]=wire.publication_id
    current.companies=old.companies[:1]
    current.quarterly=wire;current.quarter_definitions=wire.definitions;current.quarter_support=wire.support
    current.quarter_observations=wire.observations;current.quarter_period_inventory=wire.period_inventory
    service.datasets["arithmetic-v3"]=current
    new_content=copy.deepcopy(content)
    definition=next(row for row in wire.definitions if row["metric_id"]=="ttm_fcf_margin")
    new_content["predicates"][0].update(metric_id="ttm_fcf_margin",definition_version=definition["definition_version"])
    new_revision=service.create_screen("최근4분기",new_content,dataset_id="arithmetic-v3")
    result=service.execute(new_revision["revision_id"],"arithmetic-v3")
    assert result["rows"][0]["predicates"][0]["observation"]["value"]=="12"
    assert service.run(old_run["run_id"])["rows"]==old_run["rows"]
    assert service.run(old_run["run_id"])["dataset_id"]=="synthetic-v3"
    description=next(row for row in service.quarter_metric_catalog("arithmetic-v3") if row["metric_id"]=="ttm_fcf_margin")["description"]
    assert "합계" in description and "비율" in description
    assert len(service.quarter_series("arithmetic-v3",cik=CIK,metric_id="ttm_fcf_margin")["observations"])==8
    assert len(service.trace(result["run_id"],cik=CIK,metric_id="ttm_fcf_margin")["trace"]["derivation_inputs"])==8


def test_strict_catalog_and_null_basis_results_match_accepted_source_golden():
    # Captured by direct equality comparison with accepted e0b6/d359 source;
    # these digests are not generated from the new catalog at assertion time.
    assert digest_value(list(producer.METRIC_DEFINITIONS))=="1e1a64235d1b39eca4fe4a45b3362b94764a2d89836e637a234810d1b5aae25c"
    assert digest_value(_records(_null_inputs()))=="c5183a7e9ed2b5ca42ba70c47c11decfbcb97e7f8659050aec1b7069f3ce2903"
