"""Synthetic availability and company period behavior at the public service boundary."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from sec_xbrl.screening.explorer import LATEST_ANNUAL, LATEST_QUARTER, ScreeningExplorer
from sec_xbrl.screening.service import ScreeningService, _batch_evidence
from sec_xbrl.screening.store import ScreeningStore
from tests.screening.test_screening_explorer import _reader
from tests.screening.test_screening_quarterly_consumer import _quarter_service


def _registration(dataset_id, publication_id, ready_at):
    return {"dataset_id": dataset_id, "publication_id": publication_id, "ready_at": ready_at}


def _evidence(registrations, sessions=None):
    return {"schema_version": "screening-batch-availability-v1", "registrations": registrations, "sessions": sessions}


def _batch_service():
    service = object.__new__(ScreeningService)
    service.datasets = {
        key: SimpleNamespace(publication_id=f"pub-{key}", manifest={"dataset_id": key, "financial_as_of": "2024-11-01"})
        for key in ("older", "newer", "future")
    }
    now = datetime.now(UTC)
    registrations = [
        _registration("older", "pub-older", "2024-11-07T15:00:00-05:00"),
        _registration("newer", "pub-newer", "2024-11-09T00:05:00+00:00"),
        _registration("future", "pub-future", now.replace(year=now.year+1).isoformat()),
    ]
    sessions = {"from": "2024-11-07", "through": "2024-11-12", "dates": [
        "2024-11-07", "2024-11-08", "2024-11-11", "2024-11-12",
    ]}
    service.batch_registrations, service.batch_sessions = _batch_evidence(_evidence(registrations, sessions), service.datasets)
    return service


def test_batch_date_lag_and_future_exclusion():
    service = _batch_service()
    older = service.batch_availability(mode="ACTUAL", decision_date="2024-11-07")
    assert older["dataset_id"] == "older"
    friday = service.batch_availability(mode="ACTUAL", decision_date="2024-11-08")
    assert friday["dataset_id"] == "newer"  # Midnight UTC is still the previous NY date.
    assert friday["ready_at"] == "2024-11-09T00:05:00+00:00"
    assert service.batch_availability(mode="ACTUAL", decision_date="2024-11-09", lag=1)["dataset_id"] == "older"
    assert service.batch_availability(mode="ACTUAL", decision_date="2024-11-11", lag=1)["dataset_id"] == "newer"
    assert service.batch_availability(mode="ACTUAL")["dataset_id"] == "newer"
    with pytest.raises(ValueError, match="does not cover"):
        service.batch_availability(mode="ACTUAL", decision_date="2024-11-13", lag=1)
    service.batch_sessions = None
    with pytest.raises(ValueError, match="pinned US trading"):
        service.batch_availability(mode="ACTUAL", decision_date="2024-11-08", lag=1)


def test_unverified_actual_and_prepared_simulation_are_separate():
    service = _batch_service()
    with pytest.raises(ValueError, match="no verified batch"):
        service.batch_availability(mode="ACTUAL", decision_date="2024-11-01")
    simulated = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id="newer")
    assert simulated["mode"] == "PREPARED_SIMULATION"
    assert simulated["ready_at"] is None and simulated["decision_date"] is None
    assert simulated["financial_as_of"] == "2024-11-01"
    with pytest.raises(ValueError, match="own cutoff"):
        service.batch_availability(mode="PREPARED_SIMULATION", dataset_id="newer", decision_date="2024-10-31")
    with pytest.raises(ValueError, match="timezone"):
        _batch_evidence(_evidence([_registration("older", "pub-older", "2024-11-08")]), service.datasets)
    with pytest.raises(ValueError, match="publication"):
        _batch_evidence(_evidence([_registration("older", "wrong", "2024-11-08T12:00:00Z")]), service.datasets)


def _annual_service(tmp_path):
    reader = _reader()
    reader.manifest.update(fixture_kind="SYNTHETIC_ERROR_FIXTURE", sources={"metadata": {"publication_id": "meta"}})
    reader.metric_support = [
        {"metric_id": row["metric_id"], "definition_version": row["definition_version"], "execution_supported": True}
        for row in reader.metric_definitions
    ]
    reader.company = lambda cik: next(company for company in reader.companies if company["cik"] == cik)
    for row in reader.observations:
        if row["cik"] == "0000000001" and row["fiscal_year"] == 2026:
            if row["metric_id"] == "revenue":
                row["value"] = "0"
                row["trace"] = {"value_lineage": {"filed_date": "2026-10-07"}}
            if row["metric_id"] == "cfo":
                row.update(availability_status="UNAVAILABLE", value=None, unavailable_reason="MISSING_INPUT")
    service = object.__new__(ScreeningService)
    service.datasets = {"fixture-v2": reader}
    service.explorers = {"fixture-v2": ScreeningExplorer(reader)}
    service.company_descriptions = None
    service.batch_registrations = {}
    service.batch_sessions = None
    service.store = ScreeningStore(tmp_path / "journal.sqlite")
    return service


def _condition(mode, availability, predicates):
    return {
        "universe": {"mode": "ALL_PREPARED"}, "predicates": predicates,
        "period_policy": {"mode": mode, "availability": availability},
        "columns": ["company", "aggregate", "predicates"],
        "sort": {"column": "ticker", "direction": "ASC"},
    }


def test_annual_latest_uses_one_anchor_and_pins_save_round_trip(tmp_path):
    service = _annual_service(tmp_path)
    key = "fixture-v2"
    snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
    reader = service.datasets[key]
    version = {row["metric_id"]: row["definition_version"] for row in reader.metric_definitions}
    content = _condition(LATEST_ANNUAL, snapshot, [
        {"metric_id": metric, "operator": "GTE", "threshold": "0", "definition_version": version[metric]}
        for metric in ("revenue", "cfo")
    ])
    result = service.company_explorer(key, latest=True)
    assert result["resolved_periods"]["0000000001"]["fiscal_year"] == 2026
    assert result["resolved_periods"]["0000000021"]["fiscal_year"] == 2025
    assert result["rows"][0]["metrics"]["revenue"]["value"] == "0"
    assert result["rows"][0]["metrics"]["cfo"]["value"] is None
    assert service.company_explorer(key, fiscal_year=2025)["selected_fiscal_year"] == 2025
    profile = service.company_profile(key, cik="0000000001", latest=True)
    assert profile["selected_fiscal_year"] == 2026
    assert profile["resolved_period"]["source_filed_dates"] == ["2026-10-07"]
    compared = service.company_comparison(key, ciks=["0000000001", "0000000021"], metric_ids=["revenue"], latest=True)
    assert [value["fiscal_year"] for value in compared["rows"][0]["values"].values()] == [2026, 2025]
    before = service.store.list_runs()
    preview = service.preview(content, key)
    assert service.store.list_runs() == before
    assert preview["rows"][0]["predicates"][0]["result"] == "PASS"
    assert preview["rows"][0]["predicates"][1]["result"] == "UNDETERMINED"
    revision = service.create_screen("latest", content, dataset_id=key)
    assert service.saved_condition(revision["revision_id"])["content"]["period_policy"]["availability"] == snapshot
    saved = service.save_result(name="latest", content=content, dataset_id=key, preview_hash=preview["preview_hash"], revision_id=revision["revision_id"])
    assert service.run(saved["run_id"])["rows"] == preview["rows"]
    tampered = deepcopy(content)
    tampered["period_policy"]["availability"]["publication_id"] = "wrong"
    with pytest.raises(ValueError, match="differs"):
        service.preview(tampered, key)


def test_quarter_and_ttm_share_company_anchor_even_when_blocked(tmp_path):
    service = _quarter_service(tmp_path)
    key = "synthetic-v3"
    reader = service.datasets[key]
    latest = service.quarter_explorer(key, latest=True)
    assert latest["period_scope"] == "LATEST_COMPANY"
    row = next(row for row in latest["rows"] if row["period"] is not None)
    cik = row["company"]["cik"]
    period = row["period"]
    available = [item for item in reader.quarter_observations if item["cik"] == cik
                 and (item["calendar_year"], item["calendar_quarter"]) == (period["calendar_year"], period["calendar_quarter"])]
    for item in available:
        if item["metric_id"] in {"quarter_revenue", "ttm_revenue"}:
            item.update(availability_status="UNAVAILABLE", value=None, reason="QUALITY_BLOCKED", quality_status="BLOCK")
    older = next(item for item in reader.quarter_observations
                 if item["cik"] == cik and item["metric_id"] == "ttm_revenue"
                 and (item["calendar_year"], item["calendar_quarter"]) < (period["calendar_year"], period["calendar_quarter"]))
    older.update(availability_status="AVAILABLE", value="123", quality_status="PASS", reason=None)
    next(item for item in reader.quarter_support if item["cik"] == cik and item["metric_id"] == "ttm_revenue")["available_bucket_count"] = 1
    snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
    versions = {item["metric_id"]: item["definition_version"] for item in reader.quarter_definitions}
    content = _condition(LATEST_QUARTER, snapshot, [
        {"metric_id": metric, "operator": "GTE", "threshold": "0", "definition_version": versions[metric]}
        for metric in ("quarter_revenue", "ttm_revenue")
    ])
    screened = next(item for item in service.preview(content, key)["rows"] if item["cik"] == cik)
    assert screened["resolved_period"] == period
    assert all(item["result"] == "UNDETERMINED" for item in screened["predicates"])
    for item in screened["predicates"]:
        observation = item["observation"]
        assert (observation["calendar_year"], observation["calendar_quarter"]) == (period["calendar_year"], period["calendar_quarter"])


def test_missing_quarter_anchor_is_saved_as_unknown_and_traceable(tmp_path):
    service = _quarter_service(tmp_path)
    key = "synthetic-v3"
    reader = service.datasets[key]
    cik = reader.companies[0]["cik"]
    reader.quarter_period_inventory = [
        row for row in reader.quarter_period_inventory if row["cik"] != cik
    ]
    snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
    content = _condition(LATEST_QUARTER, snapshot, [
        {"metric_id": "quarter_revenue", "operator": "GTE", "threshold": "0",
         "definition_version": "quarter-reported-core-v1"},
    ])
    preview = service.preview(content, key)
    saved = service.save_result(name="missing", content=content, dataset_id=key, preview_hash=preview["preview_hash"])
    trace = service.trace(saved["run_id"], cik=cik, metric_id="quarter_revenue")
    assert trace["evaluation"]["observation"] is None
    assert trace["evaluation"]["reason"] == "PERIOD_NOT_PREPARED"
    assert trace["trace"] is None


def test_http_batch_and_latest_explorer_use_explicit_query_contract(tmp_path):
    import json
    import threading

    from sec_xbrl.screening.server import create_server
    from tests.screening.test_screening_http import _request

    service = _annual_service(tmp_path)
    server = create_server(service, export_root=tmp_path / "exports")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = _request(base + "/api/batch-availability")
        assert status == 400 and "no verified batch" in json.loads(body)["error"]
        status, body = _request(base + "/api/batch-availability?mode=PREPARED_SIMULATION&dataset_id=fixture-v2")
        assert status == 200 and json.loads(body)["ready_at"] is None
        status, body = _request(base + "/api/explorer?dataset_id=fixture-v2&latest=true")
        assert status == 200 and json.loads(body)["period_scope"] == "LATEST_COMPANY"
        status, _ = _request(base + "/api/explorer?dataset_id=fixture-v2&latest=true&fiscal_year=2025")
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_latest_rehashed_quarter_inventory_mismatch_holds_all_latest_paths(tmp_path):
    import json
    import shutil
    from pathlib import Path

    from sec_xbrl.screening.common import sha256_file, write_json

    root = tmp_path / "wire"
    shutil.copytree(Path(__file__).parents[1] / "fixtures" / "screening_quarterly_wire_v5", root)
    manifest_path = root / "quarterly_screening_metric_manifest.json"
    inventory_path = root / "quarter_period_inventory.json"
    manifest = json.loads(manifest_path.read_bytes())
    inventory = json.loads(inventory_path.read_bytes())
    cik, other = "0000000001", "0000000002"
    anchor = next(row for row in inventory["records"] if row["inventory_id"] == f"quarter-period:{cik}:2026Q3")
    anchor.update(period_end="2026-09-30", report_date="2026-09-29", reported_duration_days=91)
    anchor["candidate_periods"][0].update(period_end="2026-09-30", report_date="2026-09-29", duration_days=91)
    write_json(inventory_path, inventory)
    manifest["files"][inventory_path.name].update(sha256=sha256_file(inventory_path), size=inventory_path.stat().st_size)
    write_json(manifest_path, manifest)

    # The wire remains valid under its frozen legacy contract.
    service = _quarter_service(tmp_path, wire_root=root)
    key, metric = "synthetic-v3", "quarter_revenue"
    fixed = service.quarter_explorer(key, calendar_year=2026, calendar_quarter=3)["rows"][0]
    assert fixed["metrics"][metric]["period_end"] == "2026-10-01"
    assert fixed["metrics"][metric]["value"] is not None
    latest = service.quarter_explorer(key, latest=True)["rows"][0]
    assert latest["period"]["period_end"] == "2026-09-30"
    compared = service.quarter_comparison(key, ciks=[cik, other], metric_id=metric, latest=True)["rows"][0]
    series = service.quarter_series(key, cik=cik, metric_id=metric, latest=True)["observations"]
    assert any(row["value"] is not None for row in series[:-1])
    for observation in (latest["metrics"][metric], compared["observation"], series[-1]):
        assert observation["value"] is None
        assert observation["availability_status"] == "UNAVAILABLE"
        assert observation["reason"] == "PERIOD_MISMATCH"
    snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
    content = _condition(LATEST_QUARTER, snapshot, [
        {"metric_id": metric, "operator": "GTE", "threshold": "0", "definition_version": "quarter-reported-core-v1"},
    ])
    evaluated = service.preview(content, key)["rows"][0]["predicates"][0]
    assert evaluated["result"] == "UNDETERMINED"
    assert evaluated["reason"] == "PERIOD_MISMATCH"
    assert service.quarter_series(key, cik=cik, metric_id=metric)["observations"][-1]["value"] == fixed["metrics"][metric]["value"]


def test_annual_latest_holds_instant_period_mismatch_and_available_quality_block(tmp_path):
    service = _annual_service(tmp_path)
    key, cik = "fixture-v2", "0000000001"
    reader = service.datasets[key]
    rows = {row["metric_id"]: row for row in reader.observations if row["cik"] == cik and row["fiscal_year"] == 2026}
    rows["current_ratio"].update(period_end="2026-09-01", value="11")
    rows["revenue"].update(quality_status="BLOCK", value="0")
    latest = service.company_explorer(key, latest=True)["rows"][0]
    assert latest["resolved_period"]["period_end"] == "2027-01-01"
    profile = service.company_profile(key, cik=cik, latest=True)
    compare = service.company_comparison(key, ciks=[cik, "0000000021"], metric_ids=["current_ratio", "revenue"], latest=True)
    for index, (metric, reason) in enumerate((("current_ratio", "PERIOD_MISMATCH"), ("revenue", "QUALITY_BLOCKED"))):
        for observation in (latest["metrics"][metric], profile["series"][metric][-1], compare["rows"][index]["values"][cik]):
            assert observation["value"] is None and reason in observation["reason_codes"]
        snapshot = service.batch_availability(mode="PREPARED_SIMULATION", dataset_id=key)
        content = _condition(LATEST_ANNUAL, snapshot, [{
            "metric_id": metric, "operator": "GTE", "threshold": "0",
            "definition_version": rows[metric]["metric_definition_version"],
        }])
        result = service.preview(content, key)["rows"][0]["predicates"][0]
        assert result["result"] == "UNDETERMINED" and result["reason"] == reason
    fixed = service.company_explorer(key, fiscal_year=2026)["rows"][0]["metrics"]
    assert fixed["current_ratio"]["value"] == "11" and fixed["revenue"]["value"] == "0"
    rows["revenue"]["quality_status"] = None
    assert service.company_explorer(key, latest=True)["rows"][0]["metrics"]["revenue"]["value"] == "0"


def test_latest_ttm_uses_shared_anchor_end_but_keeps_its_own_start():
    from sec_xbrl.screening.explorer import latest_period_observation

    anchor = {
        "cik": "0000000001", "fiscal_year": 2026, "fiscal_quarter": "Q3", "calendar_year": 2026,
        "calendar_quarter": 3, "period_end": "2026-10-01", "period_start": "2026-07-01",
        "end_convention": "EXCLUSIVE",
    }
    row = {**anchor, "period_start": "2025-10-01", "period_class": "TTM", "availability_status": "AVAILABLE", "value": "0"}
    assert latest_period_observation(row, anchor, cik=anchor["cik"], quarterly=True)["value"] == "0"
    for wrong in ({"period_class": "QTD_3M"}, {"fiscal_quarter": "Q2"}, {"end_convention": "INCLUSIVE"}):
        result = latest_period_observation({**row, **wrong}, anchor, cik=anchor["cik"], quarterly=True)
        assert result["value"] is None and result["reason"] == "PERIOD_MISMATCH"
