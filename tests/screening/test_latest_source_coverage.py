"""A pinned source period outside the published spine cannot become an older latest."""
from copy import deepcopy
from types import SimpleNamespace

import polars as pl
import pytest

from sec_xbrl.screening.cohort_union import _latest_source_coverage
from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.explorer import LATEST_QUARTER, latest_company_period
from tests.screening.test_company_latest_availability import _condition
from tests.screening.test_screening_quarterly_consumer import _quarter_service

REASON = "LATEST_SOURCE_PERIOD_NOT_PUBLISHED"


def _pin(path):
    return {"path": str(path), "sha256": sha256_file(path)}


def _witness(tmp_path):
    cik = "0000000001"
    analysis = tmp_path / "analysis"
    quarter = tmp_path / "quarter"
    owner_root = tmp_path / "owner"
    for root in (analysis, quarter, owner_root):
        root.mkdir()
    columns = analysis / "columns.parquet"
    pl.DataFrame([{"period_class": "QTD_3M", "column_status": "AVAILABLE", "fiscal_year": 2027,
                   "fiscal_quarter": 1, "actual_start_date": "2026-07-01", "actual_end_date": "2026-10-03"}]).write_parquet(columns)
    analysis_path = analysis / "analysis_manifest.json"
    write_json(analysis_path, {"period_mode": "QUARTERLY", "companies": {"TEST": {
        "as_of": "2026-10-25", "views": {"LATEST_REPORTED": {"files": {"columns": {
            "path": columns.name, "sha256": sha256_file(columns)}}}}}}})
    quarter_path = quarter / "quarterly_screening_metric_manifest.json"
    write_json(quarter_path, {"financial_as_of": "2026-10-25", "config": {"companies": [{
        "cik": cik, "ticker": "TEST", "analysis_root": str(analysis),
        "analysis_manifest_sha256": sha256_file(analysis_path)}]}})
    owner_manifest = {"config": {"quarterly_metric_root": str(quarter), "quarterly_manifest_sha256": sha256_file(quarter_path)}}
    owner_path = owner_root / "screening_dataset_manifest.json"
    write_json(owner_path, owner_manifest)
    record = {"cik": cik, "owner_manifest": _pin(owner_path), "analysis_manifest": _pin(analysis_path),
              "latest_qtd": {"fiscal_year": 2027, "fiscal_quarter": 1, "period_start": "2026-07-01",
                             "period_end": "2026-10-03", "end_convention": "EXCLUSIVE"}}
    evidence = tmp_path / "coverage.json"
    payload = {"schema_version": "screening-latest-source-coverage-v1", "financial_as_of": "2026-10-25", "records": [record]}
    write_json(evidence, payload)
    owner = SimpleNamespace(root=owner_root, manifest=owner_manifest, _manifest_sha256=sha256_file(owner_path))
    return evidence, payload, {cik: owner}


def test_pinned_owner_and_header_latest_guard(tmp_path):
    path, payload, owners = _witness(tmp_path)
    spine = [{"calendar_year": 2026, "calendar_quarter": 3}]
    guards = _latest_source_coverage({"latest_source_coverage": _pin(path)}, owners, "2026-10-25", spine)
    assert guards["0000000001"]["bucket_status"] == REASON
    assert _latest_source_coverage({}, owners, "2026-10-25", spine) == {}
    assert _latest_source_coverage({"latest_source_coverage": _pin(path)}, owners, "2026-10-25",
                                   [{"calendar_year": 2026, "calendar_quarter": 4}]) == {}
    for change in ("tuple", "owner", "duplicate", "header"):
        mutated = deepcopy(payload)
        if change == "tuple":
            mutated["records"][0]["latest_qtd"]["period_end"] = "2026-10-04"
        elif change == "owner":
            mutated["records"][0]["owner_manifest"]["sha256"] = "0" * 64
        elif change == "duplicate":
            mutated["records"] *= 2
        else:
            (tmp_path / "analysis/columns.parquet").write_bytes(b"changed")
        write_json(path, mutated)
        with pytest.raises(ValueError):
            _latest_source_coverage({"latest_source_coverage": _pin(path)}, owners, "2026-10-25", spine)


def test_all_latest_paths_hold_while_fixed_and_annual_stay_usable(tmp_path):
    service = _quarter_service(tmp_path)
    key, cik, other, metric = "synthetic-v3", "0000000001", "0000000002", "quarter_revenue"
    reader = service.datasets[key]
    fixed_before = service.quarter_explorer(key, calendar_year=2026, calendar_quarter=3)
    annual_before = latest_company_period(reader, cik, quarterly=False)
    reader.latest_source_period_guards = {cik: {"cik": cik, "calendar_year": 2026, "calendar_quarter": 4,
        "fiscal_year": 2027, "fiscal_quarter": 1, "period_start": "2026-07-01", "period_end": "2026-10-03",
        "end_convention": "EXCLUSIVE", "bucket_status": REASON, "reason_label": "최신 분기 조회 자료 미준비"}}
    row = service.quarter_explorer(key, latest=True)["rows"][0]
    assert row["period"]["bucket_status"] == REASON and row["metrics"] == {}
    assert service.quarter_comparison(key, ciks=[cik, other], metric_id=metric, latest=True)["rows"][0]["observation"] is None
    series = service.quarter_series(key, cik=cik, metric_id=metric, latest=True)
    assert series["observations"] == [] and series["unavailable_reason"] == REASON
    ttm = next(row["metric_id"] for row in reader.quarter_definitions if row["metric_id"].startswith("ttm_"))
    assert service.quarter_series(key, cik=cik, metric_id=ttm, latest=True)["observations"] == []
    assert service.quarter_comparison(key, ciks=[cik, other], metric_id=ttm, latest=True)["rows"][0]["observation"] is None
    snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
    content = _condition(LATEST_QUARTER, snapshot, [{"metric_id": metric, "operator": "GTE", "threshold": "0",
                                                   "definition_version": "quarter-reported-core-v1"}])
    evaluated = service.preview(content, key)["rows"][0]["predicates"][0]
    assert evaluated["result"] == "UNDETERMINED" and evaluated["reason"] == REASON
    assert service.quarter_explorer(key, calendar_year=2026, calendar_quarter=3) == fixed_before
    assert latest_company_period(reader, cik, quarterly=False) == annual_before
    assert service.quarter_series(key, cik=other, metric_id=metric, latest=True)["observations"]
