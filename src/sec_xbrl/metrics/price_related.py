"""Versioned daily price metrics, valuation and bands; consumers never calculate.

Inputs are immutable observations plus explicit evidence-bound compatibility grants.
No filing selection, currency/class inference or EPS subtraction lives here.
"""
from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise
from pathlib import Path

from sec_xbrl.metrics.market_inputs import finite, identity

RULE = "price-related-metrics-v1"
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DECIMAL = Context(prec=34, rounding=ROUND_HALF_EVEN)
RETURN_WINDOWS = (1, 5, 21, 63, 126, 252)
VOLATILITY_WINDOWS = (20, 60, 252)


def _definition(metric_id: str, label: str, family: str, formula: str,
                unit: str, inputs: list[str], **policy: object) -> dict:
    return {"metric_id": metric_id, "label": label, "family": family,
            "definition_version": RULE + ":" + metric_id,
            "formula": formula, "unit": unit, "grain": "US_SESSION",
            "required_inputs": inputs, "policy": policy}


def definitions() -> dict[str, dict]:
    """Return a fresh complete registry, including unavailable output definitions."""
    result = {}
    for n in RETURN_WINDOWS:
        mid = f"price_return_{n}s"
        result[mid] = _definition(mid, f"가격 수익률 {n}거래일", "PRICE_RETURN",
            "100 * (split_adj_close[t] / split_adj_close[t-N] - 1)", "PERCENT",
            ["split_adj_close", "verified_us_sessions"], sessions=n,
            dividends="EXCLUDED", gap="STRICT_COMPLETE", denominator="POSITIVE")
    for n in VOLATILITY_WINDOWS:
        mid = f"price_volatility_{n}s"
        result[mid] = _definition(mid, f"연율 변동성 {n}거래일", "VOLATILITY",
            "100 * stddev(log(P[t]/P[t-1]), ddof=1) * sqrt(252)", "PERCENT",
            ["split_adj_close", "verified_us_sessions"], sessions=n, ddof=1,
            annual_sessions=252, gap="STRICT_COMPLETE", close="STRICTLY_POSITIVE")
    result["relative_volume_20s"] = _definition("relative_volume_20s", "상대 거래량 · 이전20일", "VOLUME",
        "split_adj_volume[t] / mean(split_adj_volume[t-20:t])", "MULTIPLE",
        ["split_adj_volume", "verified_us_sessions"], prior_sessions=20,
        current_in_mean=False, denominator="POSITIVE", volume="TRUE_SPLIT_COMPATIBLE")
    specs = (
        ("common_market_cap", "보통주 시가총액", "P * outstanding_common_ex_treasury", "CURRENCY", ["common_shares"]),
        ("per", "PER", "P / diluted_eps_12m", "MULTIPLE", ["diluted_eps_12m"]),
        ("pbr", "PBR · 보통주 자본", "common_market_cap / common_equity", "MULTIPLE", ["common_shares", "common_equity"]),
        ("pbr_bps", "PBR · BPS", "P / book_value_per_common_share", "MULTIPLE", ["book_value_per_common_share"]),
        ("price_sales", "P/S", "common_market_cap / revenue_12m", "MULTIPLE", ["common_shares", "revenue_12m"]),
        ("earnings_yield", "이익수익률", "100 * diluted_eps_12m / P", "PERCENT", ["diluted_eps_12m"]),
        ("standardized_fcf_yield", "표준화 FCF 수익률", "100 * standardized_fcf_12m / common_market_cap", "PERCENT", ["common_shares", "standardized_fcf_12m"]),
        ("enterprise_value", "기업가치 EV", "common_market_cap + interest_debt + preferred_equity + nci - cash_equivalents", "CURRENCY", ["common_shares", "interest_debt", "preferred_equity", "nci", "cash_equivalents"]),
        ("ev_revenue", "EV/Revenue", "enterprise_value / revenue_12m", "MULTIPLE", ["common_shares", "interest_debt", "preferred_equity", "nci", "cash_equivalents", "revenue_12m"]),
        ("ev_ebitda", "EV/영업이익+D&A proxy", "enterprise_value / (operating_income_12m + depreciation_amortization_12m)", "MULTIPLE", ["common_shares", "interest_debt", "preferred_equity", "nci", "cash_equivalents", "operating_income_12m", "depreciation_amortization_12m"]),
    )
    for mid, label, formula, unit, roles in specs:
        result[mid] = _definition(mid, label, "VALUATION", formula, unit,
            ["as_traded_close", *roles], currency="EXACT_PROVEN_MATCH",
            class_scope="EXPLICIT_EVIDENCE", split_basis="EXPLICIT_COMPATIBILITY",
            eps="DIRECT_ONLY_NO_FY_MINUS_9M", nonpositive=("SIGNED_NUMERATOR_ALLOWED" if mid in
                {"earnings_yield", "standardized_fcf_yield"} else "POSITIVE_DENOMINATOR"))
    for multiple, role in (("per", "diluted_eps_12m"), ("pbr", "book_value_per_common_share")):
        mid = f"fixed_{multiple}_band"
        result[mid] = _definition(mid, f"고정 {multiple.upper()} 가격 밴드", "FIXED_BAND",
            f"{role} * user_multiple", "CURRENCY_PER_SHARE", [role, "user_multiple"],
            interpretation="USER_SCENARIO_NOT_FORECAST", denominator="POSITIVE")
    for multiple in ("per", "pbr", "pbr_bps", "price_sales", "ev_revenue", "ev_ebitda"):
        mid = f"historical_{multiple}_percentiles_3y"
        result[mid] = _definition(mid, f"과거3년 {multiple.upper()} 분포", "HISTORICAL_MULTIPLE",
            "linear percentile of point-in-time daily multiples in trailing3 calendar years",
            "MULTIPLE", [multiple, "point_in_time_inputs"], quantiles=[0.1, 0.25, 0.5, 0.75, 0.9],
            current_denominator_replayed=False, readiness="EXPLICIT", scalar_statistic="P50_MEDIAN", screenable=False)
    return result


REGISTRY = definitions()


def _row(metric_id: str, cik: str, security_id: str, as_of: str,
         *, value: object = None, reason: str | None = None, inputs: list[dict] | None = None,
         **extra: object) -> dict:
    result = {"metric_id": metric_id, "definition_version": REGISTRY[metric_id]["definition_version"],
        "cik": cik, "security_id": security_id, "as_of": as_of, "grain": "US_SESSION",
        "unit": REGISTRY[metric_id]["unit"], "value": str(value) if value is not None else None,
        "status": "AVAILABLE" if value is not None else "UNAVAILABLE", "reason": reason,
        "reported_or_derived": "DERIVED", "input_lineage": inputs or [], **extra}
    result["observation_id"] = "price-metric-" + identity(result)
    return result


def validate_sessions(session_source: dict) -> list[str]:
    """Require an explicit verified calendar range; price observations cannot define it."""
    sessions = session_source.get("sessions")
    if (session_source.get("schema_version") != "verified-us-sessions-v1"
        or session_source.get("market") != "US_EQUITIES"
        or session_source.get("verified") is not True
        or not session_source.get("source_pins") or not isinstance(sessions, list)
        or not sessions or sessions != sorted(set(sessions))):
        raise ValueError("explicit verified US session source required")
    for day in [*sessions, session_source["coverage_start"], session_source["coverage_end"]]:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("invalid session date")
    if not session_source["coverage_start"] <= sessions[0] <= sessions[-1] <= session_source["coverage_end"]:
        raise ValueError("session source outside verified coverage")
    return sessions


def calculate_price_metrics(prices: list[dict], session_source: dict, *, cik: str,
                            security_id: str, as_of: str, volume_basis: str | None) -> list[dict]:
    """Compute all independent price metrics, retaining every strict missing window.

    `as_of` is an explicitly selected completed US session. A later request date is
    carried by the publisher; this function never silently substitutes a close.
    """
    date.fromisoformat(as_of)
    sessions = validate_sessions(session_source)
    ids = [f"price_return_{n}s" for n in RETURN_WINDOWS] + [f"price_volatility_{n}s" for n in VOLATILITY_WINDOWS] + ["relative_volume_20s"]
    if as_of not in sessions:
        return [_row(mid, cik, security_id, as_of, reason="AS_OF_NOT_VERIFIED_COMPLETED_SESSION") for mid in ids]
    by_day = {}
    for row in prices:
        if row.get("security_id") != security_id:
            continue
        day = row["trade_date"]
        if day in by_day:
            raise ValueError("duplicate security/session price")
        by_day[day] = row
    end = sessions.index(as_of)
    result = []
    for mid in ids:
        n = 20 if mid == "relative_volume_20s" else int(mid.rsplit("_", 1)[1][:-1])
        expected = sessions[max(0, end - n):end + 1]
        rows = [by_day.get(day) for day in expected]
        lineage = [{"security_id": security_id, "start_session": expected[0], "end_session": as_of,
                    "ordered_input_ids_sha256": identity([(day, (row or {}).get("observation_id"))
                                                        for day, row in zip(expected, rows)]),
                    "session_count": len(expected)}]
        reason = None
        value = None
        if end < n:
            reason = "INSUFFICIENT_VERIFIED_SESSION_HISTORY"
        elif any(row is None for row in rows):
            reason = "PRICE_SESSION_GAP"
        elif mid == "relative_volume_20s":
            volumes = [finite(row.get("split_adj_volume")) for row in rows]
            if volume_basis != "TRUE_SPLIT_COMPATIBLE":
                reason = "VOLUME_SPLIT_BASIS_UNKNOWN"
            elif any(v is None or v < 0 for v in volumes):
                reason = "VOLUME_MISSING_OR_NEGATIVE"
            else:
                with localcontext(DECIMAL):
                    mean = sum(volumes[:-1]) / Decimal(20)
                    if mean <= 0:
                        reason = "VOLUME_BASE_NONPOSITIVE"
                    else:
                        value = volumes[-1] / mean
        else:
            closes = [finite(row.get("split_adj_close")) for row in rows]
            if any(v is None or v <= 0 for v in closes):
                reason = "CLOSE_MISSING_OR_NONPOSITIVE"
            elif mid.startswith("price_return"):
                with localcontext(DECIMAL):
                    value = (closes[-1] / closes[0] - 1) * 100
            else:
                # log differences avoid overflowing a floating close ratio.
                def log_close(value: Decimal) -> float:
                    number = float(value)
                    return math.log(number) if math.isfinite(number) and number > 0 else float(value.ln(context=DECIMAL))
                returns = [log_close(b) - log_close(a) for a, b in pairwise(closes)]
                number = statistics.stdev(returns) * math.sqrt(252) * 100
                if not math.isfinite(number):
                    reason = "NUMERIC_RANGE_UNSUPPORTED"
                else:
                    value = format(number, ".15g")
        result.append(_row(mid, cik, security_id, as_of, value=value, reason=reason,
                           inputs=lineage, session_source_id=identity(session_source),
                           window_start=expected[0], window_sessions=n))
    return result


ROLE_UNITS = {
    "common_shares": "shares", "diluted_eps_12m": "currency/share",
    "book_value_per_common_share": "currency/share", "common_equity": "currency",
    "revenue_12m": "currency", "standardized_fcf_12m": "currency",
    "interest_debt": "currency", "preferred_equity": "currency", "nci": "currency",
    "cash_equivalents": "currency", "operating_income_12m": "currency",
    "depreciation_amortization_12m": "currency",
}
DURATION_ROLES = {r for r in ROLE_UNITS if r.endswith("_12m")}


def _input_reason(row: dict, *, role: str, cik: str, as_of: str,
                  currency: str, grant: dict) -> str | None:
    if row.get("cik") != cik or row.get("role") != role or not row.get("observation_id"):
        return "INPUT_IDENTITY_MISMATCH"
    if row.get("status") != "AVAILABLE" or finite(row.get("value")) is None:
        return row.get("reason") or "FINANCIAL_INPUT_UNAVAILABLE"
    if row.get("unit_kind") != ROLE_UNITS[role] or (role != "common_shares" and row.get("currency") != currency):
        return "UNIT_OR_CURRENCY_MISMATCH"
    if not row.get("known_on") or row["known_on"] > as_of or (row.get("ready_on") and row["ready_on"] > as_of):
        return "INPUT_AFTER_PRICE_AS_OF"
    if not row.get("source_refs"):
        return "INPUT_LINEAGE_MISSING"
    if row.get("scope_id") != grant.get("financial_scope_id"):
        return "FINANCIAL_SCOPE_MISMATCH"
    if row.get("end_convention") != "EXCLUSIVE" or not row.get("period_end"):
        return "FINANCIAL_PERIOD_UNKNOWN"
    if date.fromisoformat(row["period_end"]) > date.fromisoformat(as_of) + timedelta(days=1):
        return "FINANCIAL_PERIOD_AFTER_AS_OF"
    if role in DURATION_ROLES:
        if row.get("period_class") not in {"FY", "TTM"} or not row.get("period_start"):
            return "TWELVE_MONTH_PERIOD_REQUIRED"
        days = (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days
        if not 350 <= days <= 378:
            return "TWELVE_MONTH_PERIOD_REQUIRED"
    if role in {"common_shares", "diluted_eps_12m", "book_value_per_common_share"} and (
        row.get("stock_class_id") != grant.get("stock_class_id")
        or row.get("split_basis_id") != grant.get("split_basis_id")
    ):
        return "CLASS_OR_SPLIT_BASIS_MISMATCH"
    if role in {"preferred_equity", "nci"} and finite(row["value"]) == 0 and row.get("evidenced_zero") is not True:
        return "EXPLICIT_ZERO_EVIDENCE_REQUIRED"
    if role == "diluted_eps_12m" and row.get("source_kind") not in {"DIRECT_REPORTED", "GOVERNED_DIRECT_QTD_TTM"}:
        return "EPS_DIRECT_OBSERVATION_REQUIRED"
    if role == "common_shares" and row.get("share_measure") != "OUTSTANDING_COMMON_EX_TREASURY":
        return "ACTUAL_OUTSTANDING_COMMON_REQUIRED"
    if role == "standardized_fcf_12m" and row.get("formula_id") != "STANDARDIZED_CFO_MINUS_PPE_ACQUISITIONS":
        return "STANDARDIZED_FCF_DEFINITION_MISMATCH"
    return None


def calculate_valuation_metrics(price: dict | None, observations: list[dict], grant: dict | None,
                                *, cik: str, security_id: str, as_of: str,
                                ev_policy: dict | None = None, financial_anchor: str | None = None,
                                financial_as_of: str | None = None) -> list[dict]:
    """A grant binds exact observation IDs and security/basis; it never creates data.

    Monetary rows retain fiscal periods. The value here is daily as-of using only
    evidence known then. Ambiguous observations never select a first row.
    """
    date.fromisoformat(as_of)
    mids = [mid for mid, definition in REGISTRY.items() if definition["family"] == "VALUATION"]
    price_reason = None
    p = finite((price or {}).get("as_traded_close"))
    if price is None or price.get("security_id") != security_id or price.get("trade_date") != as_of:
        price_reason = "EXACT_SESSION_PRICE_MISSING"
    elif p is None or p <= 0:
        price_reason = "PRICE_NONPOSITIVE_OR_MISSING"
    elif not price.get("currency"):
        price_reason = "PRICE_CURRENCY_UNKNOWN"
    elif (grant is None or grant.get("schema_version") != "price-financial-compatibility-v1"
          or not grant.get("evidence_pins") or grant.get("cik") != cik
          or grant.get("security_id") != security_id or not grant.get("stock_class_id")
          or not grant.get("financial_scope_id") or not grant.get("split_basis_id")
          or grant.get("common_valuation_scope") != "EXACT_COMMON_CLASS_OR_APPROVED_ISSUER_AGGREGATION"
          or grant.get("currency") != price.get("currency")
          or not grant.get("known_on") or grant["known_on"] > as_of):
        price_reason = "CLASS_CURRENCY_SPLIT_COMPATIBILITY_NOT_APPROVED"
    if price_reason is None and grant.get("required_price_split_factor") is not None and (
        finite(price.get("split_factor")) != finite(grant["required_price_split_factor"])
    ):
        price_reason = "SPLIT_FACTOR_DIFFERENT_FROM_APPROVED_BASIS"
    if price_reason is None and (not financial_as_of or financial_as_of < as_of):
        price_reason = "FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF"
    if price_reason is None and financial_anchor is not None and grant.get("financial_anchor") != financial_anchor:
        price_reason = "FINANCIAL_ANCHOR_SCOPE_NOT_APPROVED"
    refs = [{"input_role": "as_traded_close", **(price or {})}]
    grouped = defaultdict(list)
    for row in observations:
        grouped[row.get("observation_id")].append(row)
    values, reasons, chosen = {}, {}, {}
    if price_reason is None:
        for role in ROLE_UNITS:
            oid = grant.get("input_ids", {}).get(role)
            matched = grouped.get(oid, []) if oid else []
            if len(matched) != 1:
                reasons[role] = "FINANCIAL_INPUT_NOT_BOUND" if not matched else "AMBIGUOUS_FINANCIAL_INPUT"
                continue
            row = matched[0]
            chosen[role] = row
            reason = _input_reason(row, role=role, cik=cik, as_of=as_of,
                                   currency=price["currency"], grant=grant)
            if reason is None and role in DURATION_ROLES:
                anchor = financial_anchor or grant.get("financial_anchor")
                if not anchor:
                    reason = "LATEST_FINANCIAL_ANCHOR_NOT_BOUND"
                elif row.get("period_end") != anchor:
                    reason = "TWELVE_MONTH_INPUT_NOT_AT_LATEST_FINANCIAL_END"
            if reason:
                reasons[role] = reason
            else:
                values[role] = finite(row["value"])
    results = []
    for mid in mids:
        roles = REGISTRY[mid]["required_inputs"][1:]
        inputs = refs + [{"input_role": role, **chosen.get(role, {"observation_id": (grant or {}).get("input_ids", {}).get(role)})} for role in roles]
        reason = price_reason or next((reasons[r] for r in roles if r in reasons), None)
        value = None
        if reason is None:
            # EV and EBITDA components must be approved explicitly, including evidenced zeros.
            if mid in {"enterprise_value", "ev_revenue", "ev_ebitda"}:
                if (not ev_policy or ev_policy.get("approved") is not True
                    or ev_policy.get("version") != "ev-finance-lease-ex-operating-v1"):
                    reason = "EV_POLICY_NOT_APPROVED"
                elif any(values[r] < 0 for r in ("interest_debt", "preferred_equity", "nci", "cash_equivalents")):
                    reason = "EV_COMPONENT_NEGATIVE"
                elif (chosen["interest_debt"].get("debt_scope") != "INTEREST_BEARING_INCLUDING_FINANCE_EXCLUDING_OPERATING_LEASES"
                      or chosen["cash_equivalents"].get("cash_scope") != "CASH_AND_CASH_EQUIVALENTS"):
                    reason = "EV_COMPONENT_SCOPE_NOT_APPROVED"
                elif any(chosen[r].get("valuation_basis") not in {"REPORTED_CARRYING_VALUE", "OBSERVED_MARKET_VALUE", "REVIEWED_BOOK_CAPITAL_RESIDUAL_ZERO"}
                         for r in ("interest_debt", "preferred_equity", "nci")):
                    reason = "FINANCING_VALUATION_BASIS_UNKNOWN"
                elif len({(chosen[r]["period_end"], chosen[r]["scope_id"]) for r in ("interest_debt", "preferred_equity", "nci", "cash_equivalents")}) != 1:
                    reason = "EV_COMPONENT_PERIOD_MISMATCH"
            if not reason:
                with localcontext(DECIMAL):
                    shares = values.get("common_shares")
                    cap = p * shares if shares is not None and shares > 0 else None
                    eps = values.get("diluted_eps_12m")
                    equity = values.get("common_equity")
                    bps = values.get("book_value_per_common_share")
                    revenue = values.get("revenue_12m")
                    if "common_shares" in roles and cap is None:
                        reason = "COMMON_SHARES_NONPOSITIVE"
                    elif mid == "common_market_cap":
                        value = cap
                    elif mid == "per":
                        if eps <= 0:
                            reason = "EPS_NONPOSITIVE"
                        else:
                            value = p / eps
                    elif mid == "earnings_yield":
                        value = eps / p * 100
                    elif mid in {"pbr", "pbr_bps"}:
                        denominator = equity if mid == "pbr" else bps
                        if denominator <= 0:
                            reason = "COMMON_EQUITY_NONPOSITIVE" if mid == "pbr" else "BPS_NONPOSITIVE"
                        else:
                            value = (cap if mid == "pbr" else p) / denominator
                    elif mid == "price_sales":
                        if revenue <= 0:
                            reason = "REVENUE_NONPOSITIVE"
                        else:
                            value = cap / revenue
                    elif mid == "standardized_fcf_yield":
                        value = values["standardized_fcf_12m"] / cap * 100
                    elif mid in {"enterprise_value", "ev_revenue", "ev_ebitda"}:
                        ev = cap + values["interest_debt"] + values["preferred_equity"] + values["nci"] - values["cash_equivalents"]
                        if mid == "enterprise_value":
                            value = ev
                        elif mid == "ev_revenue":
                            if revenue <= 0:
                                reason = "REVENUE_NONPOSITIVE"
                            else:
                                value = ev / revenue
                        else:
                            a, b = chosen["operating_income_12m"], chosen["depreciation_amortization_12m"]
                            if (a.get("ebitda_scope_id") is None or a.get("ebitda_scope_id") != b.get("ebitda_scope_id")
                                or (a["period_start"], a["period_end"]) != (b["period_start"], b["period_end"])
                                or b.get("da_scope") != "OPERATING_INCOME_INCLUDED_DA"):
                                reason = "EBITDA_SCOPE_OR_PERIOD_MISMATCH"
                            elif values["depreciation_amortization_12m"] < 0:
                                reason = "DA_NEGATIVE"
                            else:
                                ebitda = values["operating_income_12m"] + values["depreciation_amortization_12m"]
                                if ebitda <= 0:
                                    reason = "EBITDA_NONPOSITIVE"
                                else:
                                    value = ev / ebitda
        result = _row(mid, cik, security_id, as_of, value=value, reason=reason,
                      inputs=inputs, currency=(price or {}).get("currency"),
                      compatibility_grant_id=identity(grant) if grant else None,
                      historical_ready=bool(price and price.get("ready_on") and price["ready_on"] <= as_of)
                          and bool(grant and grant.get("ready_on") and grant["ready_on"] <= as_of)
                          and all(chosen.get(role, {}).get("ready_on") and chosen[role]["ready_on"] <= as_of for role in roles),
                      financing_valuation_bases={role: chosen.get(role, {}).get("valuation_basis") for role in roles
                          if role in {"interest_debt", "preferred_equity", "nci"}},
                      share_measurement_date=((date.fromisoformat(chosen["common_shares"]["period_end"]) - timedelta(days=1)).isoformat()
                                              if "common_shares" in roles and chosen.get("common_shares", {}).get("period_end") else None),
                      share_period_end=chosen.get("common_shares", {}).get("period_end") if "common_shares" in roles else None,
                      financial_end_convention="EXCLUSIVE",
                      market_cap_interpretation="LATEST_DISCLOSED_OUTSTANDING_SHARE_BASED_NOT_DAILY_SHARE_MEASUREMENT" if "common_shares" in roles else None,
                      denominator_route="OPERATING_INCOME_PLUS_INCLUDED_DA_PROXY" if mid == "ev_ebitda" else None)
        results.append(result)
    return results


def fixed_multiple_bands_for_ratio(base: dict, scenarios: list[str]) -> list[dict]:
    """Single approved ratio route, shared by legacy scenarios and temporal analysis."""
    routes = {"per": ("per", "diluted_eps_12m"), "pbr_bps": ("pbr", "book_value_per_common_share")}
    if base["metric_id"] not in routes:
        raise ValueError("fixed bands require PER or BPS-based PBR")
    multiple, role = routes[base["metric_id"]]
    denominator = next((r for r in base["input_lineage"] if r.get("input_role") == role), {})
    results = []
    for text in scenarios or [None]:
        m = finite(text)
        value = None
        reason = base["reason"]
        if not reason and (m is None or m <= 0):
            reason = "POSITIVE_USER_MULTIPLE_REQUIRED"
        if not reason:
            with localcontext(DECIMAL):
                value = finite(denominator["value"]) * m
        results.append(_row(f"fixed_{multiple}_band", base["cik"], base["security_id"], base["as_of"],
            value=value, reason=reason, inputs=base["input_lineage"], user_multiple=str(m) if m is not None else None,
            currency=base.get("currency"), scenario_kind="USER_FIXED_MULTIPLE_NOT_FORECAST"))
    return results


def fixed_multiple_bands(valuation_rows: list[dict], multiples: dict[str, list[str]]) -> list[dict]:
    """Use approved financial legs of valuation results; calculations remain upstream."""
    by_id = {row["metric_id"]: row for row in valuation_rows}
    return [row for route, metric in (("per", "per"), ("pbr", "pbr_bps"))
            for row in fixed_multiple_bands_for_ratio(by_id[metric], multiples.get(route, []))]


def historical_multiple_percentiles(rows: list[dict], *, cik: str, security_id: str,
                                    as_of: str, multiple: str, readiness_policy: str,
                                    session_source: dict, source_coverage: dict) -> dict:
    """Three calendar years, actual point-in-time rows only. No synthetic price band.

    The distribution reports valid/expected/missing counts and is diagnostic when
    readiness is unconfirmed; only READY_ONLY can certify historical-ready inputs.
    """
    if multiple not in {"per", "pbr", "pbr_bps", "price_sales", "ev_revenue", "ev_ebitda"} or readiness_policy not in {"READY_ONLY", "DIAGNOSTIC_FILED_DAY"}:
        raise ValueError("unsupported multiple/readiness policy")
    end = date.fromisoformat(as_of)
    try:
        start = end.replace(year=end.year - 3)
    except ValueError:
        start = end.replace(year=end.year - 3, day=28)
    sessions = validate_sessions(session_source)
    expected = [d for d in sessions if start.isoformat() <= d <= as_of]
    full_coverage = (session_source["coverage_start"] <= start.isoformat()
                     and session_source["coverage_end"] >= as_of
                     and source_coverage.get("start", "9999") <= start.isoformat()
                     and source_coverage.get("end", "0000") >= as_of)
    selected = [r for r in rows if r["metric_id"] == multiple and r["cik"] == cik
                and r["security_id"] == security_id and start.isoformat() <= r["as_of"] <= as_of]
    if len({r["as_of"] for r in selected}) != len(selected):
        raise ValueError("ambiguous historical multiple/session")
    valid = [r for r in selected if r["status"] == "AVAILABLE" and finite(r.get("value")) is not None
             and (readiness_policy != "READY_ONLY" or r.get("historical_ready") is True)]
    valid = [r for r in valid if r["as_of"] in expected]
    values = sorted(finite(r["value"]) for r in valid)
    quantiles = {}
    eligible = full_coverage and len(values) >= 252
    if eligible:
        with localcontext(DECIMAL):
            for q in ("0.1", "0.25", "0.5", "0.75", "0.9"):
                index = Decimal(len(values) - 1) * Decimal(q)
                lo = int(index)
                quantiles[q] = str(values[lo] + (values[min(lo + 1, len(values)-1)] - values[lo]) * (index - lo))
    result = _row(f"historical_{multiple}_percentiles_3y", cik, security_id, as_of,
        value=quantiles.get("0.5"), reason=(None if eligible else "HISTORICAL_CALENDAR_OR_SOURCE_COVERAGE_INCOMPLETE" if not full_coverage
               else "INSUFFICIENT_ELIGIBLE_HISTORY_252_SESSIONS"),
        inputs=[{"observation_id": r["observation_id"], "as_of": r["as_of"], "value": r["value"],
                 "historical_ready": r.get("historical_ready")} for r in valid],
        percentiles=quantiles, window_start=start.isoformat(), window_end=as_of,
        valid_sessions=len(valid), expected_sessions=len(expected), observed_sessions=len(selected),
        unavailable_sessions=len(expected)-len(valid), minimum_eligible_sessions=252,
        complete_intended_window_coverage=full_coverage,
        coverage_status="COMPLETE" if full_coverage and len(valid) == len(expected) else "PARTIAL_OR_UNREADY",
        readiness_policy=readiness_policy, diagnostic=readiness_policy == "DIAGNOSTIC_FILED_DAY",
        scalar_statistic="P50_MEDIAN",
        ready_unknown_sessions=sum(r["status"] == "AVAILABLE" and r.get("historical_ready") is not True for r in selected),
        backtest_eligible=eligible and len(valid) == len(expected) and readiness_policy == "READY_ONLY")
    return result
