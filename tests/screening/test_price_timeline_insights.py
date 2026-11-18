from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest
from test_price_metric_publication import publication
from test_price_timeline import sample

from sec_xbrl.metrics.price_timeline import (
    interpret_timeline_point,
    rolling_distribution,
    timeline_coverage,
    timeline_missing_ranges,
)
from sec_xbrl.screening.price_metric_service import PriceMetricService


def point(value="35"):
    return {"as_of": "2026-11-13", "ratio": {"status": "AVAILABLE", "value": value},
        "ratio_eligible": True, "close": "35", "reason": None,
        "denominator": {"value": "5"},
        "bands": [{"status": "AVAILABLE", "value": v, "user_multiple": m} for m, v in (("2", "10"), ("8", "40"))],
        "distribution": {"status": "AVAILABLE", "percentiles": dict(zip(("0.1", "0.25", "0.5", "0.75", "0.9"), ("10", "20", "30", "40", "50"), strict=True)),
            "valid_sessions": 252, "expected_sessions": 252, "minimum_eligible_sessions": 252,
            "complete_intended_window_coverage": True}}


@pytest.mark.parametrize("value,lower,upper,median", [("5", None, "0.1", "BELOW"), ("15", "0.1", "0.25", "BELOW"), ("35", "0.5", "0.75", "ABOVE"), ("60", "0.9", None, "ABOVE")])
def test_quantile_buckets_never_invent_exact_rank(value, lower, upper, median):
    p = point(value)
    original = copy.deepcopy(p)
    result = interpret_timeline_point(p, "per")
    assert result["position"] == {"status": "AVAILABLE", "equal_quantiles": [],
        "lower_quantile": lower, "upper_quantile": upper, "median_relation": median,
        "central_50_relation": "BELOW" if value in {"5", "15"} else "ABOVE" if value == "60" else "INSIDE"}
    assert p == original
    assert "percentile_rank" not in result
    assert result["bands"]["denominator_role"] == "EPS12M"


@pytest.mark.parametrize("q,value", [("0.1", "10"), ("0.25", "20"), ("0.5", "30"), ("0.75", "40"), ("0.9", "50")])
def test_equality_and_tied_boundaries(q, value):
    result = interpret_timeline_point(point(value), "pbr_bps")
    assert result["position"]["equal_quantiles"] == [q]
    p = point("30")
    p["distribution"]["percentiles"] = {key: "30" for key in p["distribution"]["percentiles"]}
    tied = interpret_timeline_point(p, "pbr_bps")["position"]
    assert len(tied["equal_quantiles"]) == 5 and tied["median_relation"] == "EQUAL"


@pytest.mark.parametrize("value", ["0", "-1", "NaN", None])
def test_nonpositive_or_invalid_ratio_has_no_position_or_band_bracket(value):
    result = interpret_timeline_point(point(value), "per")
    assert result["position"]["status"] == result["bands"]["status"] == "UNAVAILABLE"


def test_policy_distribution_and_coverage_gaps_are_independent():
    p = point()
    p["ratio_eligible"] = False
    assert interpret_timeline_point(p, "per")["position"]["status"] == "UNAVAILABLE"
    p["ratio_eligible"] = True
    p["distribution"].update(status="UNAVAILABLE", reason="HISTORICAL_CALENDAR_OR_SOURCE_COVERAGE_INCOMPLETE", complete_intended_window_coverage=False, valid_sessions=300, expected_sessions=400)
    result = interpret_timeline_point(p, "per")
    assert result["position"]["reason"] == "HISTORICAL_CALENDAR_OR_SOURCE_COVERAGE_INCOMPLETE"
    assert result["samples"]["minimum_shortfall"] == 0
    assert result["samples"]["missing_expected"] == 100
    assert result["bands"]["status"] == "AVAILABLE"
    assert result["bands"]["lower"] == {"multiple": "2", "price": "10"}
    assert result["bands"]["upper"] == {"multiple": "8", "price": "40"}
    p["close"] = "10"
    assert interpret_timeline_point(p, "per")["bands"]["equal_multiples"] == ["2"]
    p["bands"].append({"status": "AVAILABLE", "value": "0", "user_multiple": "0"})
    assert interpret_timeline_point(p, "per")["bands"]["assumptions"] == ["2", "8"]


@pytest.mark.parametrize("window", ["252s", "3y"])
def test_sliding_coverage_matches_governed_distribution_per_day(window):
    calendar, rows = sample(1200)
    rows[300]["status"] = "UNAVAILABLE"
    for r in rows[800:]:
        r["historical_ready"] = False
    company = {"cik": "1", "security_id": "S"}
    source = {"start": calendar["coverage_start"], "end": calendar["coverage_end"]}
    coverage = timeline_coverage([(company, rows)], session_source=calendar, source_coverage=source,
        metric="pbr_bps", readiness_policy="READY_ONLY", window=window, view_years=3, end=calendar["sessions"][-1])
    for row in coverage["dates"][::37]:
        distribution = rolling_distribution(rows, as_of=row["as_of"], multiple="pbr_bps", cik="1", security_id="S", session_source=calendar, source_coverage=source, readiness_policy="READY_ONLY", window=window)
        assert row["distribution_companies"] == int(distribution["status"] == "AVAILABLE")
    assert coverage["dates"][-1]["ratio_companies"] == 0
    assert coverage["any_ratio_companies"] == 1


def test_missing_ranges_group_by_kind_reason_and_actual_session():
    points = []
    for i in range(4):
        p = point()
        p["as_of"] = (date(2026, 1, 1)+timedelta(days=i)).isoformat()
        p["distribution"].update(status="UNAVAILABLE", reason="COVERAGE" if i < 2 else "MINIMUM")
        points.append(p)
    result = timeline_missing_ranges(points)
    assert [(r["reason"], r["sessions"]) for r in result] == [("COVERAGE", 2), ("MINIMUM", 2)]


def test_coverage_cache_reverifies_all_artifacts_and_dependency_pins(tmp_path):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "private.sqlite")
    request = {"metric": "per", "view_years": 3, "window": "252s", "readiness_policy": "READY_ONLY"}
    assert service.execute("coverage", request)["selectable_companies"] == 1
    assert service.execute("coverage", request)["selectable_companies"] == 1
    path = reader.root / reader.manifest["files"]["0000000001"]["historical"]["path"]
    old = path.read_bytes()
    path.write_bytes(old+b"x")
    with pytest.raises(ValueError, match="artifact hash"):
        service.execute("coverage", request)
    path.write_bytes(old)
    dependency = reader.manifest["source_pins"]["financial_inputs"]["path"]
    from pathlib import Path
    Path(dependency).write_bytes(Path(dependency).read_bytes()+b"x")
    with pytest.raises(ValueError):
        service.execute("coverage", request)


def test_legacy_saved_timeline_reopens_unchanged_without_new_interpretation(tmp_path, monkeypatch):
    reader, _, _ = publication(tmp_path)
    service = PriceMetricService(reader, tmp_path / "private.sqlite")
    original = service._evaluate
    def legacy(reader, operation, request):
        result = original(reader, operation, request)
        result.pop("interpretation_definition", None)
        result.pop("missing_ranges", None)
        for p in result.get("points", []):
            p.pop("interpretation", None)
        return result
    monkeypatch.setattr(service, "_evaluate", legacy)
    saved = service.save(kind="RESULT", operation="timeline", request={"cik": "0000000001", "metric": "per"}, title="legacy")
    reopened = PriceMetricService(reader, tmp_path / "private.sqlite").reopen(saved["id"])
    assert reopened["result"] == saved["result"]
    assert all("interpretation" not in p for p in reopened["result"]["points"])


def test_coverage_reopen_uses_original_reader_after_current_publication_changes(tmp_path):
    old, _, _ = publication(tmp_path, tag="old")
    service = PriceMetricService(old, tmp_path / "shared.sqlite")
    saved = service.save(kind="RESULT", operation="timeline", request={"cik": "0000000001", "metric": "per"}, title="original source")
    new, _, _ = publication(tmp_path, tag="new", close="200")
    switched = PriceMetricService(new, tmp_path / "shared.sqlite")
    reopened = switched.reopen(saved["id"])
    result = switched.execute("coverage", {"metric": "per", "view_years": 3, "window": "252s", "readiness_policy": "READY_ONLY", "evidence_context": reopened["evidence_context"]})
    assert result["publication_pin"] == old.pin
    assert result["publication_id"] == saved["publication_id"] != new.manifest["publication_id"]
    assert switched.reopen(saved["id"])["result"] == saved["result"]
    with pytest.raises(ValueError, match="expired"):
        switched.execute("coverage", {"metric": "per", "view_years": 3, "window": "252s", "readiness_policy": "READY_ONLY", "evidence_context": "expired"})
