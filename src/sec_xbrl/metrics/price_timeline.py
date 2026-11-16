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
