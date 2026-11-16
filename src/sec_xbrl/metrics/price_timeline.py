"""Governed historical bands and trailing distributions over immutable ratio rows."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from sec_xbrl.metrics.market_inputs import finite, identity
from sec_xbrl.metrics.price_related import (
    DECIMAL,
    fixed_multiple_bands_for_ratio,
    historical_multiple_percentiles,
    validate_sessions,
)

DEFINITION = {
    "definition_version": "price-band-timeseries-v1:rolling252s",
    "window": "252_EXPECTED_US_SESSIONS_INCLUSIVE", "minimum_eligible_sessions": 252,
    "quantiles": ["0.1", "0.25", "0.5", "0.75", "0.9"],
    "interpolation": "LINEAR_N_MINUS_ONE", "gap": "EXACT_COMPLETE_WINDOW",
    "current_denominator_replayed": False, "screenable": False,
}


def rolling_distribution(rows: list[dict], *, as_of: str, multiple: str,
                         cik: str, security_id: str, session_source: dict,
                         source_coverage: dict, readiness_policy: str,
                         window: str = "252s") -> dict:
    """Calculate only past/current eligible rows; never relax the original 3y rule."""
    if window == "3y":
        return historical_multiple_percentiles(rows, cik=cik, security_id=security_id,
            as_of=as_of, multiple=multiple, readiness_policy=readiness_policy,
            session_source=session_source, source_coverage=source_coverage)
    if window != "252s" or readiness_policy not in {"READY_ONLY", "DIAGNOSTIC_FILED_DAY"}:
        raise ValueError("unsupported timeline window/readiness")
    sessions = validate_sessions(session_source)
    expected = [d for d in sessions if d <= as_of][-252:]
    selected = [r for r in rows if r["cik"] == cik and r["security_id"] == security_id
                and r["metric_id"] == multiple and r["as_of"] in expected]
    if len({r["as_of"] for r in selected}) != len(selected):
        raise ValueError("ambiguous historical multiple/session")
    valid = [r for r in selected if r["status"] == "AVAILABLE" and finite(r.get("value")) is not None
             and finite(r["value"]) > 0
             and (readiness_policy != "READY_ONLY" or r.get("historical_ready") is True)]
    full = (len(expected) == 252 and expected[-1] == as_of
            and source_coverage.get("start", "9999") <= expected[0]
            and source_coverage.get("end", "0000") >= as_of
            and session_source["coverage_end"] >= as_of)
    eligible = full and len(valid) == 252
    quantiles = {}
    if eligible:
        values = sorted(finite(r["value"]) for r in valid)
        with localcontext(DECIMAL):
            for q in DEFINITION["quantiles"]:
                index = Decimal(251) * Decimal(q)
                lo = int(index)
                quantiles[q] = str(values[lo] + (values[min(lo + 1, 251)] - values[lo]) * (index - lo))
    result = {"definition_version": DEFINITION["definition_version"], "as_of": as_of,
        "cik": cik, "security_id": security_id, "metric_id": multiple,
        "status": "AVAILABLE" if eligible else "UNAVAILABLE",
        "reason": None if eligible else "HISTORICAL_252_SESSION_COVERAGE_INCOMPLETE" if not full else "INSUFFICIENT_ELIGIBLE_HISTORY_252_SESSIONS",
        "percentiles": quantiles, "window_start": expected[0] if expected else None,
        "window_end": as_of, "valid_sessions": len(valid), "expected_sessions": len(expected),
        "unavailable_sessions": len(expected) - len(valid), "minimum_eligible_sessions": 252,
        "complete_intended_window_coverage": full, "readiness_policy": readiness_policy,
        "diagnostic": readiness_policy == "DIAGNOSTIC_FILED_DAY",
        "backtest_eligible": eligible and readiness_policy == "READY_ONLY",
        "input_lineage": [{"observation_id": r["observation_id"], "as_of": r["as_of"],
                           "value": r["value"], "historical_ready": r.get("historical_ready")} for r in valid]}
    result["observation_id"] = "price-timeline-distribution-" + identity(result)
    return result


def build_timeline(*, history: list[dict], prices: list[dict], financial: list[dict],
                   sessions: dict, coverage: dict, cik: str, security_id: str,
                   metric: str, multiples: list[str], end: str, view_years: int,
                   window: str, readiness_policy: str) -> list[dict]:
    """Pair published ratios with their exact denominator IDs and original close."""
    finish = date.fromisoformat(end)
    try:
        start = finish.replace(year=finish.year-view_years).isoformat()
    except ValueError:
        start = finish.replace(year=finish.year-view_years, day=28).isoformat()
    by_id = {r["observation_id"]: r for r in financial}
    ratios = {r["as_of"]: r for r in history if r["metric_id"] == metric and r["cik"] == cik}
    price_by_day = {r["trade_date"]: r for r in prices if r["security_id"] == security_id}
    days = [d for d in validate_sessions(sessions) if start <= d <= end]
    output = []
    role = "diluted_eps_12m" if metric == "per" else "book_value_per_common_share"
    for day in days:
        ratio = ratios.get(day)
        bands, denominator = [], None
        ratio_eligible = ratio is not None and ratio["status"] == "AVAILABLE" and (readiness_policy != "READY_ONLY" or ratio.get("historical_ready") is True)
        if ratio:
            enriched = {**ratio, "input_lineage": [{**by_id.get(leg.get("observation_id"), {}), **leg} for leg in ratio["input_lineage"]]}
            if readiness_policy == "READY_ONLY" and ratio.get("historical_ready") is not True:
                enriched = {**enriched, "status": "UNAVAILABLE", "value": None, "reason": "HISTORICAL_READINESS_UNCONFIRMED"}
            denominator = next((leg for leg in enriched["input_lineage"] if leg.get("input_role") == role), None)
            bands = fixed_multiple_bands_for_ratio(enriched, multiples)
            for band in bands:
                band["input_lineage"] = ratio["input_lineage"]
                band["observation_id"] = "price-metric-" + identity({k: v for k, v in band.items() if k != "observation_id"})
            if denominator:
                denominator = {k: denominator[k] for k in ("observation_id", "value", "currency", "unit_kind", "period_start", "period_end", "period_class", "known_on", "ready_on", "status", "reason", "input_role") if k in denominator}
        distribution = rolling_distribution(history, as_of=day, multiple=metric, cik=cik,
            security_id=security_id, session_source=sessions, source_coverage=coverage,
            readiness_policy=readiness_policy, window=window)
        legs = distribution.pop("input_lineage", [])
        distribution["input_observation_ids_sha256"] = identity(legs)
        distribution["input_reference"] = "published historical rows in window, eligible under readiness_policy"
        price = price_by_day.get(day)
        output.append({"as_of": day, "close": price.get("as_traded_close") if price else None,
            "currency": price.get("currency") if price else None,
            "price_input": price, "ratio": ratio, "ratio_eligible": ratio_eligible, "denominator": denominator,
            "bands": bands, "distribution": distribution,
            "reason": ("HISTORICAL_READINESS_UNCONFIRMED" if readiness_policy == "READY_ONLY" and ratio and ratio.get("historical_ready") is not True else ratio.get("reason") if ratio else "METRIC_NOT_PREPARED")})
    return output


INTERPRETATION_VERSION = "price-timeline-interpretation-v1"
QUANTILE_KEYS = ("0.1", "0.25", "0.5", "0.75", "0.9")


def interpret_timeline_point(point: dict, metric: str, *, window: str = "252s") -> dict:
    """Classify supplied governed values; no ratio, band or quantile is recalculated."""
    if window not in {"252s", "3y"}:
        raise ValueError("unsupported interpretation window")
    ratio, distribution = point.get("ratio") or {}, point.get("distribution") or {}
    value = finite(ratio.get("value"))
    eligible = (ratio.get("status") == "AVAILABLE" and point.get("ratio_eligible") is not False
                and value is not None and value > 0)
    valid, expected = distribution.get("valid_sessions", 0), distribution.get("expected_sessions", 0)
    minimum = distribution.get("minimum_eligible_sessions", 252)
    result = {"definition_version": INTERPRETATION_VERSION, "as_of": point["as_of"],
        "metric_id": metric, "ratio_value": ratio.get("value") if eligible else None,
        "position": {"status": "UNAVAILABLE", "reason": point.get("reason") or "RATIO_UNAVAILABLE"},
        "samples": {"window": window, "valid": valid, "expected": expected, "required": minimum,
            "missing_expected": max(0, expected-valid), "minimum_shortfall": max(0, minimum-valid),
            "complete_window_coverage": distribution.get("complete_intended_window_coverage", False)},
        "bands": {"status": "UNAVAILABLE", "reason": point.get("reason") or "BAND_INPUTS_UNAVAILABLE",
            "denominator_role": "EPS12M" if metric == "per" else "BPS",
            "denominator": point.get("denominator"), "assumptions": []}}
    if eligible:
        quantiles = distribution.get("percentiles", {})
        bounds = [finite(quantiles.get(q)) for q in QUANTILE_KEYS]
        if distribution.get("status") != "AVAILABLE":
            result["position"]["reason"] = distribution.get("reason") or "DISTRIBUTION_UNAVAILABLE"
        elif any(v is None or v <= 0 for v in bounds) or bounds != sorted(bounds):
            result["position"]["reason"] = "QUANTILE_BOUNDARIES_UNAVAILABLE"
        else:
            equal = [q for q, bound in zip(QUANTILE_KEYS, bounds, strict=True) if value == bound]
            lower = next((q for q, bound in reversed(list(zip(QUANTILE_KEYS, bounds, strict=True))) if bound < value), None)
            upper = next((q for q, bound in zip(QUANTILE_KEYS, bounds, strict=True) if bound > value), None)
            result["position"] = {"status": "AVAILABLE", "equal_quantiles": equal,
                "lower_quantile": lower, "upper_quantile": upper,
                "median_relation": "EQUAL" if value == bounds[2] else "BELOW" if value < bounds[2] else "ABOVE",
                "central_50_relation": "BELOW" if value < bounds[1] else "ABOVE" if value > bounds[3] else "INSIDE"}
        close = finite(point.get("close"))
        rows = [r for r in point.get("bands", []) if r.get("status") == "AVAILABLE"
                and finite(r.get("value")) is not None and finite(r["value"]) > 0
                and finite(r.get("user_multiple")) is not None and finite(r["user_multiple"]) > 0]
        rows.sort(key=lambda r: finite(r["value"]))
        result["bands"]["assumptions"] = [r["user_multiple"] for r in rows]
        if close is not None and close > 0 and rows:
            equal_rows = [r for r in rows if finite(r["value"]) == close]
            below = [r for r in rows if finite(r["value"]) < close]
            above = [r for r in rows if finite(r["value"]) > close]
            result["bands"].update(status="AVAILABLE", reason=None,
                equal_multiples=[r["user_multiple"] for r in equal_rows],
                lower=({"multiple": below[-1]["user_multiple"], "price": below[-1]["value"]} if below else None),
                upper=({"multiple": above[0]["user_multiple"], "price": above[0]["value"]} if above else None))
    return result


def timeline_missing_ranges(points: list[dict]) -> list[dict]:
    """Compact consecutive actual-session gaps without claiming a future repair date."""
    output = []
    for kind in ("ratio", "distribution"):
        current = None
        for point in points:
            source = point.get(kind) or {}
            missing = (source.get("status") != "AVAILABLE" or
                       (kind == "ratio" and point.get("ratio_eligible") is False))
            reason = (point.get("reason") if kind == "ratio" else source.get("reason")) or "METRIC_NOT_PREPARED"
            if not missing:
                current = None
            elif current and current["reason"] == reason:
                current["end"] = point["as_of"]
                current["sessions"] += 1
            else:
                current = {"kind": kind, "start": point["as_of"], "end": point["as_of"], "sessions": 1, "reason": reason}
                output.append(current)
    return output


def timeline_coverage(histories: list[tuple[dict, list[dict]]], *, session_source: dict,
                      source_coverage: dict, metric: str, readiness_policy: str,
                      window: str, view_years: int, end: str) -> dict:
    """Count eligibility with sliding prefix counts, without calculating109 timelines."""
    from bisect import bisect_left, bisect_right

    if metric not in {"per", "pbr_bps"} or readiness_policy not in {"READY_ONLY", "DIAGNOSTIC_FILED_DAY"} or window not in {"252s", "3y"} or view_years not in {1, 3}:
        raise ValueError("bounded timeline coverage scope required")
    sessions = validate_sessions(session_source)
    finish = date.fromisoformat(end)
    try:
        start = finish.replace(year=finish.year-view_years).isoformat()
    except ValueError:
        start = finish.replace(year=finish.year-view_years, day=28).isoformat()
    dates = [d for d in sessions if start <= d <= end]
    counts = {d: {"as_of": d, "ratio_companies": 0, "distribution_companies": 0} for d in dates}
    any_ratio = any_distribution = 0
    for company, rows in histories:
        scoped = [r for r in rows if r["metric_id"] == metric and r["cik"] == company["cik"] and r["security_id"] == company["security_id"]]
        by_day = {r["as_of"]: r for r in scoped}
        if len(by_day) != len(scoped):
            raise ValueError("ambiguous historical multiple/session")
        valid = []
        for day in sessions:
            row = by_day.get(day, {})
            number = finite(row.get("value"))
            valid.append(row.get("status") == "AVAILABLE" and number is not None
                and (window != "252s" or number > 0)
                and (readiness_policy != "READY_ONLY" or row.get("historical_ready") is True))
        prefix = [0]
        for flag in valid:
            prefix.append(prefix[-1]+int(flag))
        has_ratio = has_distribution = False
        for day in dates:
            right = bisect_right(sessions, day)
            if window == "252s":
                left = max(0, right-252)
                full = (right-left == 252 and source_coverage.get("start", "9999") <= sessions[left]
                        and source_coverage.get("end", "0000") >= day and session_source["coverage_end"] >= day)
                distribution_ok = full and prefix[right]-prefix[left] == 252
            else:
                d = date.fromisoformat(day)
                try:
                    lookback = d.replace(year=d.year-3).isoformat()
                except ValueError:
                    lookback = d.replace(year=d.year-3, day=28).isoformat()
                left = bisect_left(sessions, lookback)
                full = (session_source["coverage_start"] <= lookback and session_source["coverage_end"] >= day
                        and source_coverage.get("start", "9999") <= lookback and source_coverage.get("end", "0000") >= day)
                distribution_ok = full and prefix[right]-prefix[left] >= 252
            ratio_row = by_day.get(day, {})
            ratio_number = finite(ratio_row.get("value"))
            ratio_ok = (ratio_row.get("status") == "AVAILABLE" and ratio_number is not None and ratio_number > 0
                        and (readiness_policy != "READY_ONLY" or ratio_row.get("historical_ready") is True))
            counts[day]["ratio_companies"] += int(ratio_ok)
            counts[day]["distribution_companies"] += int(distribution_ok)
            has_ratio |= ratio_ok
            has_distribution |= distribution_ok
        any_ratio += int(has_ratio)
        any_distribution += int(has_distribution)
    return {"definition_version": "price-timeline-coverage-v1", "metric": metric,
        "readiness_policy": readiness_policy, "window": window, "view_years": view_years,
        "end": end, "selectable_companies": len(histories), "any_ratio_companies": any_ratio,
        "any_distribution_companies": any_distribution, "dates": list(counts.values())}
