"""Timeline rules cannot turn missing/late inputs into historical valuation evidence."""
from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest
from test_price_metric_publication import publication

from sec_xbrl.metrics.price_timeline import DEFINITION, rolling_distribution
from sec_xbrl.screening.price_metric_service import PriceMetricService


def sample(n=260):
    days = [(date(2024, 1, 1)+timedelta(days=i)).isoformat() for i in range(n)]
    calendar = {"schema_version": "verified-us-sessions-v1", "market": "US_EQUITIES", "verified": True,
        "sessions": days, "coverage_start": days[0], "coverage_end": days[-1], "source_pins": [{"fixture": "calendar"}]}
    rows = [{"metric_id": "pbr_bps", "cik": "1", "security_id": "S", "as_of": d,
        "value": str(i+1), "observation_id": str(i), "status": "AVAILABLE", "historical_ready": True}
        for i, d in enumerate(days)]
    return calendar, rows


def distribution(calendar, rows, day=None, **kw):
    return rolling_distribution(rows, as_of=day or calendar["sessions"][-1], multiple="pbr_bps",
        cik="1", security_id="S", session_source=calendar,
        source_coverage={"start": calendar["coverage_start"], "end": calendar["coverage_end"]},
        readiness_policy=kw.pop("readiness_policy", "READY_ONLY"), **kw)


def test_exact_252_linear_quantiles_no_future_and_no_partial_window():
    calendar, rows = sample()
    before = copy.deepcopy(rows)
    result = distribution(calendar, rows, calendar["sessions"][251])
    assert result["percentiles"]["0.5"] == "126.5"
    assert result["valid_sessions"] == result["expected_sessions"] == 252
    assert result["backtest_eligible"] is True
    assert result["definition_version"] == DEFINITION["definition_version"]
    assert distribution(calendar, rows, calendar["sessions"][250])["percentiles"] == {}
    rows[-1]["value"] = "99999999"
    assert distribution(calendar, rows, calendar["sessions"][251]) == result
    assert before[:-1] == rows[:-1]


@pytest.mark.parametrize("change", ["missing", "negative", "unready", "nonfinite"])
def test_missing_negative_unready_session_never_fills_window(change):
    calendar, rows = sample()
    if change == "missing":
        rows.pop(30)
    elif change == "negative":
        rows[30]["value"] = "-1"
    elif change == "unready":
        rows[30]["historical_ready"] = False
    else:
        rows[30]["value"] = "NaN"
    result = distribution(calendar, rows)
    assert result["percentiles"] == {}
    assert result["valid_sessions"] == 251
    assert not result["backtest_eligible"]


def test_diagnostic_never_promotes_readiness_and_3y_unchanged():
    calendar, rows = sample()
    for row in rows:
        row["historical_ready"] = False
    diagnostic = distribution(calendar, rows, readiness_policy="DIAGNOSTIC_FILED_DAY")
    assert diagnostic["status"] == "AVAILABLE"
    assert diagnostic["diagnostic"] and not diagnostic["backtest_eligible"]
    old = distribution(calendar, rows, readiness_policy="DIAGNOSTIC_FILED_DAY", window="3y")
    assert old["definition_version"] == "price-related-metrics-v1:historical_pbr_bps_percentiles_3y"
    assert old["percentiles"] == {}


def test_timeline_saved_snapshot_custom_bands_and_old_journal(tmp_path):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "private.sqlite")
    old = service.save(kind="RESULT", operation="query", request={"metric_ids": ["per"]}, title="old")
    request = {"cik": "0000000001", "metric": "per", "multiples": ["7", "0"], "view_years": 1}
    result = service.execute("timeline", request)
    assert result["mode"] == "timeline"
    assert result["points"][-1]["bands"][0]["user_multiple"] == "7"
    assert result["points"][-1]["bands"][1]["value"] is None
    assert result["points"][-1]["denominator"]["known_on"] <= result["points"][-1]["as_of"]
    saved = service.save(kind="RESULT", operation="timeline", request=request, title="timeline")
    reopened = service.reopen(saved["id"])
    assert reopened["result"] == saved["result"]
    assert service.reopen(old["id"])["result"] == old["result"]
    assert reopened["request"] == request
    with pytest.raises(ValueError):
        service.execute("timeline", {**request, "view_years": 10})


def test_bands_follow_exact_financial_leg_update_not_latest_replay():
    from sec_xbrl.metrics.price_timeline import build_timeline

    calendar, _ = sample(3)
    days = calendar["sessions"]
    history = [{"metric_id": "per", "definition_version": "original", "cik": "1", "security_id": "S",
        "as_of": day, "observation_id": "ratio-"+str(i), "value": "2", "status": "AVAILABLE",
        "reason": None, "historical_ready": True,
        "input_lineage": [{"observation_id": "eps-old" if i < 2 else "eps-new", "input_role": "diluted_eps_12m"}]}
        for i, day in enumerate(days)]
    financial = [{"observation_id": "eps-old", "value": "5", "known_on": days[0]},
                 {"observation_id": "eps-new", "value": "8", "known_on": days[2]}]
    before = copy.deepcopy(history)
    points = build_timeline(history=history, financial=financial,
        prices=[{"security_id": "S", "trade_date": d, "as_traded_close": "10", "currency": "USD"} for d in days],
        sessions=calendar, coverage={"start": days[0], "end": days[-1]}, cik="1", security_id="S",
        metric="per", multiples=["3"], end=days[-1], view_years=1, window="252s", readiness_policy="READY_ONLY")
    assert [p["bands"][0]["value"] for p in points] == ["15", "15", "24"]
    assert [p["denominator"]["observation_id"] for p in points] == ["eps-old", "eps-old", "eps-new"]
    assert history == before
    assert all(p["bands"][0]["metric_id"] == "fixed_per_band" for p in points)
    history[0]["historical_ready"] = False
    unready = build_timeline(history=history, financial=financial,
        prices=[], sessions=calendar, coverage={"start": days[0], "end": days[-1]}, cik="1", security_id="S",
        metric="per", multiples=["3"], end=days[-1], view_years=1, window="252s", readiness_policy="READY_ONLY")
    assert unready[0]["ratio"] == history[0]
    assert unready[0]["ratio_eligible"] is False
    assert unready[0]["bands"][0]["value"] is None



def test_cached_timeline_still_checks_original_historical_artifact(tmp_path):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "cache.sqlite")
    request = {"cik": "0000000001", "metric": "per"}
    result = service.execute("timeline", request)
    result["timeline_definition"]["window"] = "tampered consumer object"
    assert service.execute("timeline", request)["timeline_definition"]["window"] != "tampered consumer object"
    artifact = reader.root / reader.manifest["files"][request["cik"]]["historical"]["path"]
    artifact.write_bytes(artifact.read_bytes()+b"x")
    with pytest.raises(ValueError, match="artifact hash"):
        service.execute("timeline", request)
