from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.metrics.governed_corrections import REVENUE_VERSION
from sec_xbrl.screening import governed_delta as delta
from sec_xbrl.screening.cohort_union import (
    CONFIG_VERSION,
    ScreeningCohortUnionReader,
    publish_cohort_union,
)
from sec_xbrl.screening.cohort_union import MANIFEST as UNION_MANIFEST
from sec_xbrl.screening.common import read_json, sha256_file, write_json
from sec_xbrl.screening.runtime_projection import (
    hydrate_observation,
    observation_rows,
    publish_runtime_projection,
)
from sec_xbrl.screening.service import ScreeningService
from tests.screening.test_cohort_union import _member, _pin
from tests.screening.test_runtime_projection import _condition


def _parent(tmp_path, *, latest=False):
    first, original = _member(tmp_path, 1)
    second, _ = _member(tmp_path, 2)
    coverage = None
    if latest:
        analysis = tmp_path / "analysis"; analysis.mkdir()
        columns = analysis / "columns.parquet"
        pl.DataFrame([{"period_class": "QTD_3M", "column_status": "AVAILABLE", "fiscal_year": 2027,
                       "fiscal_quarter": "Q1", "actual_start_date": "2026-07-04", "actual_end_date": "2026-10-03"}]).write_parquet(columns)
        apath = analysis / "analysis_manifest.json"
        write_json(apath, {"companies": {"T1": {"as_of": original.manifest["financial_as_of"],
            "views": {"LATEST_REPORTED": {"files": {"columns": {"path": columns.name, "sha256": sha256_file(columns)}}}}}}})
        quarter = tmp_path / "quarter"; quarter.mkdir()
        qpath = quarter / "quarterly_screening_metric_manifest.json"
        write_json(qpath, {"financial_as_of": original.manifest["financial_as_of"], "config": {"companies": [{
            "cik": "0000000001", "ticker": "T1", "analysis_root": str(analysis), "analysis_manifest_sha256": sha256_file(apath)}]}})
        original.manifest["config"] = {"quarterly_metric_root": str(quarter), "quarterly_manifest_sha256": sha256_file(qpath)}
        source = Path(first["dataset_manifest"]["path"])
        write_json(source, original.manifest)
        original._manifest_sha256 = sha256_file(source)
        projection = publish_runtime_projection(source.parent, tmp_path / "updated-projection", tmp_path / "blobs", reader=original)
        first = {"dataset_manifest": _pin(source), "projection": _pin(projection)}
        coverage = tmp_path / "coverage.json"
        write_json(coverage, {"schema_version": "screening-latest-source-coverage-v1", "financial_as_of": original.manifest["financial_as_of"],
            "records": [{"cik": "0000000001", "owner_manifest": _pin(source), "analysis_manifest": _pin(apath),
                "latest_qtd": {"fiscal_year": 2027, "fiscal_quarter": "Q1", "period_start": "2026-07-04",
                               "period_end": "2026-10-03", "end_convention": "EXCLUSIVE"}}]})
    config = {"schema_version": CONFIG_VERSION, "dataset_id": "parent", "members": [first, second]}
    if coverage:
        config["latest_source_coverage"] = _pin(coverage)
    cp = tmp_path / "union.json"; write_json(cp, config)
    root = publish_cohort_union(cp, tmp_path / "union")
    pin = _pin(root / UNION_MANIFEST)
    return root, pin, ScreeningCohortUnionReader(root, pin)


def _approve(root):
    manifest = read_json(root / delta.MANIFEST)
    approval = root.parent / "approval.json"
    write_json(approval, {"schema_version": delta.APPROVAL_VERSION, "status": "ROOT_APPROVED_GOVERNED_DELTA",
                          "manifest": _pin(root / delta.MANIFEST), "implementation_sources": manifest["implementation_sources"]})
    return {"manifest": _pin(root / delta.MANIFEST), "approval": _pin(approval)}


def test_public_candidate_approval_parent_sharing_and_lazy_version_adoption(tmp_path):
    parent_root, parent_pin, parent = _parent(tmp_path)
    cp = tmp_path / "delta.json"
    write_json(cp, {"schema_version": delta.CONFIG_VERSION, "dataset_id": "new", "parent": parent_pin})
    root = delta.publish_governed_delta(cp, tmp_path / "delta", parent=parent)
    assert all(member._evidence.cache_info().misses == 0 for member in parent._members)
    declaration = _approve(root)
    reader = delta.ScreeningGovernedDeltaReader(root, declaration, parent=parent)
    assert reader.parent is parent
    for support in reader.metric_support:
        if support["metric_id"] == "revenue_yoy":
            rows = observation_rows(reader, cik=support["cik"], metric_id="revenue_yoy")
            assert support["available_periods"] == sum(row["availability_status"] == "AVAILABLE" for row in rows)
            assert support["definition_version"] == REVENUE_VERSION
    assert all(member._evidence.cache_info().misses == 0 for member in parent._members)
    row = observation_rows(reader, metric_id="revenue_yoy")[0]
    old = observation_rows(parent, cik=row["cik"], metric_id="revenue_yoy", year=row["fiscal_year"])[0]
    assert row["value"] == old["value"] and row["metric_definition_version"] == REVENUE_VERSION
    full = hydrate_observation(reader, row)
    assert full["original_observation"]["id"] == old["metric_observation_id"]
    assert full["metric_observation_id"] == row["metric_observation_id"]
    service = ScreeningService({"new": root, "parent": parent_root}, tmp_path / "private.sqlite",
        cohort_unions={"parent": parent_pin}, governed_deltas={"new": declaration})
    assert service.datasets["new"].parent is service.datasets["parent"]
    assert service.company_explorer("new")["rows"]
    definition = next(d for d in reader.metric_definitions if d["metric_id"] == "revenue_yoy")
    content = _condition({"mode": "FIXED_FISCAL_YEAR", "fiscal_year": row["fiscal_year"]}, definition)
    screen = service.create_screen("private", content, dataset_id="new")
    run = service.execute(screen["revision_id"], "new")
    assert service.store.run(run["run_id"])["dataset_publication_id"] == reader.publication_id
    payload = root / delta.PAYLOAD
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(ValueError, match="pin"):
        delta.ScreeningGovernedDeltaReader(root, declaration, parent=parent)


def test_latest_supplement_is_published_only_for_latest_routes_and_wrong_owner_rejects(tmp_path, monkeypatch):
    parent_root, parent_pin, parent = _parent(tmp_path, latest=True)
    cik = "0000000001"
    owner = parent._owners[cik]
    qpath = Path(owner.manifest["config"]["quarterly_metric_root"]) / "quarterly_screening_metric_manifest.json"
    company = read_json(qpath)["config"]["companies"][0]
    request = {"cik": cik, "ticker": "T1", "owner_manifest": _pin(owner.root / "screening_dataset_manifest.json"),
        "quarterly_manifest": _pin(qpath), "analysis_manifest": _pin(Path(company["analysis_root"]) / "analysis_manifest.json")}
    anchor = {**parent.latest_source_period_guards[cik], "bucket_status": "PERIOD_AVAILABLE", "filed_date": "2026-10-23"}
    old_rows = observation_rows(parent, quarterly=True, cik=cik, year=2026, quarter=3)
    records = [{**deepcopy(hydrate_observation(parent, row, quarterly=True)), "calendar_quarter": 4,
                "fiscal_year": 2027, "fiscal_quarter": "Q1", "period_end": anchor["period_end"],
                "period_start": anchor["period_start"] if row["period_class"] == "QTD_3M" else row.get("period_start")}
               for row in old_rows]
    from sec_xbrl.metrics.quarterly_screening import _observation_id
    for row in records:
        row["observation_id"] = _observation_id(row)
    monkeypatch.setattr(delta, "prepare_latest_quarter", lambda **_: (records, [anchor], []))
    cp = tmp_path / "delta.json"
    config = {"schema_version": delta.CONFIG_VERSION, "dataset_id": "new", "parent": parent_pin, "latest_quarters": [request]}
    write_json(cp, config)
    root = delta.publish_governed_delta(cp, tmp_path / "delta", parent=parent)
    declaration = _approve(root)
    service = ScreeningService({"parent": parent_root, "new": root}, tmp_path / "private.sqlite",
        cohort_unions={"parent": parent_pin}, governed_deltas={"new": declaration})
    assert service.quarter_explorer("new", calendar_year=2026, calendar_quarter=3) == service.quarter_explorer("parent", calendar_year=2026, calendar_quarter=3)
    latest = service.quarter_explorer("new", latest=True)["rows"][0]
    assert latest["period"]["calendar_quarter"] == 4 and latest["period"]["bucket_status"] == "PERIOD_AVAILABLE"
    metric = "quarter_revenue"
    assert service.quarter_series("new", cik=cik, metric_id=metric, latest=True)["observations"][-1]["calendar_quarter"] == 4
    assert service.quarter_series("new", cik=cik, metric_id=metric)["observations"][-1]["calendar_quarter"] == 3
    compared = service.quarter_comparison("new", ciks=[cik, "0000000002"], metric_id=metric, latest=True)
    assert compared["rows"][0]["period"]["calendar_quarter"] == 4
    definition = next(d for d in owner.quarter_definitions if d["metric_id"] == metric)
    content = _condition({"mode": "LATEST_COMPANY_QUARTER_V1", "availability": service.batch_availability(mode="PREPARED_SIMULATION", dataset_id="new")}, definition)
    result = service.preview(content, "new")
    assert result["rows"][0]["predicates"][0]["observation"]["calendar_quarter"] == 4
    config["latest_quarters"][0]["owner_manifest"]["sha256"] = "0" * 64
    write_json(cp, config)
    with pytest.raises(ValueError, match="owner"):
        delta.publish_governed_delta(cp, tmp_path / "bad", parent=parent)
