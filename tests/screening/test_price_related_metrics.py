from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest

from sec_xbrl.metrics.price_related import (
    REGISTRY,
    ROLE_UNITS,
    calculate_price_metrics,
    calculate_valuation_metrics,
    fixed_multiple_bands,
    historical_multiple_percentiles,
)


def sessions(n=260):
    # Explicit synthetic sessions: the engine must honor this fixture, not infer weekdays.
    days = [(date(2025, 1, 1) + timedelta(days=i * 2)).isoformat() for i in range(n)]
    return {"schema_version": "verified-us-sessions-v1", "market": "US_EQUITIES", "verified": True,
            "source_pins": [{"fixture": "explicit-test-calendar"}], "sessions": days,
            "coverage_start": days[0], "coverage_end": days[-1]}


def prices(calendar):
    return [{"security_id": "US:TEST", "trade_date": day, "split_adj_close": str(100 + i),
             "split_adj_volume": "100" if i < len(calendar["sessions"])-1 else "200",
             "source": {"fixture": "price"}, "observation_id": f"p-{i}"}
            for i, day in enumerate(calendar["sessions"])]


def calc(prices, calendar, **kw):
    return {r["metric_id"]: r for r in calculate_price_metrics(prices, calendar,
        cik="0000000001", security_id="US:TEST", as_of=calendar["sessions"][-1],
        volume_basis="TRUE_SPLIT_COMPATIBLE", **kw)}


def financial():
    values = {"common_shares": "10", "diluted_eps_12m": "2", "common_equity": "200",
              "book_value_per_common_share": "20", "revenue_12m": "400", "standardized_fcf_12m": "-10",
              "interest_debt": "50", "preferred_equity": "0", "nci": "0", "cash_equivalents": "20",
              "operating_income_12m": "30", "depreciation_amortization_12m": "10"}
    observations = [{"observation_id": role, "role": role, "cik": "0000000001", "value": value,
        "status": "AVAILABLE", "unit_kind": ROLE_UNITS[role], "currency": "USD",
        "scope_id": "issuer-common", "stock_class_id": "common", "split_basis_id": "unadjusted-2026",
        "known_on": "2026-10-01", "ready_on": "2026-10-02", "period_end": "2026-10-01",
        "end_convention": "EXCLUSIVE", "period_start": "2025-10-01" if role.endswith("_12m") else None,
        "period_class": "FY" if role.endswith("_12m") else "INSTANT", "source_refs": [{"fact_id": role}],
        "source_kind": "DIRECT_REPORTED", "share_measure": "OUTSTANDING_COMMON_EX_TREASURY",
        "formula_id": "STANDARDIZED_CFO_MINUS_PPE_ACQUISITIONS", "evidenced_zero": True,
        "valuation_basis": "REPORTED_CARRYING_VALUE",
        "debt_scope": "INTEREST_BEARING_INCLUDING_FINANCE_EXCLUDING_OPERATING_LEASES",
        "cash_scope": "CASH_AND_CASH_EQUIVALENTS", "da_scope": "OPERATING_INCOME_INCLUDED_DA",
        "ebitda_scope_id": "operating-total"} for role, value in values.items()]
    grant = {"schema_version": "price-financial-compatibility-v1", "cik": "0000000001",
        "security_id": "US:TEST", "stock_class_id": "common", "split_basis_id": "unadjusted-2026",
        "financial_scope_id": "issuer-common", "known_on": "2026-10-02", "ready_on": "2026-10-02",
        "financial_anchor": "2026-10-01", "currency": "USD", "evidence_pins": [{"fixture": "review"}],
        "common_valuation_scope": "EXACT_COMMON_CLASS_OR_APPROVED_ISSUER_AGGREGATION",
        "input_ids": {role: role for role in values}}
    price = {"security_id": "US:TEST", "trade_date": "2026-10-23", "as_traded_close": "100", "currency": "USD", "ready_on": "2026-10-23"}
    return price, observations, grant


def valuations(p=None, rows=None, grant=None):
    price, observations, approved = financial()
    return {r["metric_id"]: r for r in calculate_valuation_metrics(p or price, rows or observations,
        grant or approved, cik="0000000001", security_id="US:TEST", as_of="2026-10-23", financial_as_of="2026-10-25",
        ev_policy={"version": "ev-finance-lease-ex-operating-v1", "approved": True})}


def test_registry_full_families_and_price_numeric():
    assert len(REGISTRY) == 28
    calendar = sessions()
    rows = calc(prices(calendar), calendar)
    assert float(rows["price_return_1s"]["value"]) == pytest.approx((359/358-1)*100)
    assert float(rows["price_return_252s"]["value"]) == pytest.approx((359/107-1)*100)
    assert rows["relative_volume_20s"]["value"] == "2"
    assert float(rows["price_volatility_20s"]["value"]) > 0
    assert rows["price_return_252s"]["window_sessions"] == 252


def test_constant_log_returns_have_zero_sample_volatility():
    calendar = sessions(25)
    source = prices(calendar)
    for i, row in enumerate(source):
        row["split_adj_close"] = str(Decimal(2) ** i)
    rows = calc(source, calendar)
    assert float(rows["price_volatility_20s"]["value"]) < 1e-11
    assert rows["price_volatility_60s"]["reason"] == "INSUFFICIENT_VERIFIED_SESSION_HISTORY"


def test_gap_not_skipped_and_zero_is_not_missing():
    calendar = sessions()
    source = prices(calendar)
    source.pop(-6)
    rows = calc(source, calendar)
    assert rows["price_return_5s"]["reason"] == "PRICE_SESSION_GAP"
    assert rows["price_return_1s"]["status"] == "AVAILABLE"
    source = prices(calendar)
    source[-1]["split_adj_volume"] = "0"
    assert calc(source, calendar)["relative_volume_20s"]["value"] == "0"
    for r in source[:-1]:
        r["split_adj_volume"] = "0"
    assert calc(source, calendar)["relative_volume_20s"]["reason"] == "VOLUME_BASE_NONPOSITIVE"


def test_no_inferred_sessions_or_duplicate_or_close_filling():
    calendar = sessions()
    source = prices(calendar)
    with pytest.raises(ValueError, match="verified"):
        calc(source, {**calendar, "verified": False})
    with pytest.raises(ValueError, match="duplicate"):
        calc(source + [source[-1]], calendar)
    source[-1]["split_adj_close"] = "0"
    assert calc(source, calendar)["price_return_1s"]["reason"] == "CLOSE_MISSING_OR_NONPOSITIVE"


def test_all_valuation_values_signed_yield_and_proxy_label():
    rows = valuations()
    expected = {"common_market_cap": 1000, "per": 50, "pbr": 5, "pbr_bps": 5, "price_sales": 2.5,
                "earnings_yield": 2, "standardized_fcf_yield": -1, "enterprise_value": 1030,
                "ev_revenue": 2.575, "ev_ebitda": 25.75}
    assert {k: float(v["value"]) for k, v in rows.items()} == expected
    assert rows["ev_ebitda"]["denominator_route"] == "OPERATING_INCOME_PLUS_INCLUDED_DA_PROXY"
    assert "proxy" in REGISTRY["ev_ebitda"]["label"]
    assert rows["ev_revenue"]["financing_valuation_bases"]["interest_debt"] == "REPORTED_CARRYING_VALUE"


@pytest.mark.parametrize("eps", ["0", "-2"])
def test_per_nonpositive_and_signed_earnings_yield(eps):
    p, rows, grant = financial()
    next(r for r in rows if r["role"] == "diluted_eps_12m")["value"] = eps
    got = valuations(p, rows, grant)
    assert got["per"]["reason"] == "EPS_NONPOSITIVE"
    assert Decimal(got["earnings_yield"]["value"]) == Decimal(eps)


@pytest.mark.parametrize("role,field,value,metric,reason", [
    ("common_shares", "share_measure", "WEIGHTED_AVERAGE", "common_market_cap", "ACTUAL_OUTSTANDING_COMMON_REQUIRED"),
    ("diluted_eps_12m", "split_basis_id", "unknown", "per", "CLASS_OR_SPLIT_BASIS_MISMATCH"),
    ("diluted_eps_12m", "stock_class_id", "other", "per", "CLASS_OR_SPLIT_BASIS_MISMATCH"),
    ("diluted_eps_12m", "source_kind", "FY_MINUS_9M", "per", "EPS_DIRECT_OBSERVATION_REQUIRED"),
    ("common_equity", "value", "0", "pbr", "COMMON_EQUITY_NONPOSITIVE"),
    ("revenue_12m", "value", "-1", "price_sales", "REVENUE_NONPOSITIVE"),
    ("revenue_12m", "currency", "EUR", "price_sales", "UNIT_OR_CURRENCY_MISMATCH"),
    ("revenue_12m", "known_on", "2026-10-24", "price_sales", "INPUT_AFTER_PRICE_AS_OF"),
    ("preferred_equity", "evidenced_zero", False, "ev_revenue", "EXPLICIT_ZERO_EVIDENCE_REQUIRED"),
    ("interest_debt", "debt_scope", "TOTAL_LIABILITIES", "ev_revenue", "EV_COMPONENT_SCOPE_NOT_APPROVED"),
    ("depreciation_amortization_12m", "da_scope", "CFO_ADDBACK", "ev_ebitda", "EBITDA_SCOPE_OR_PERIOD_MISMATCH"),
])
def test_incompatible_financial_legs_fail_closed(role, field, value, metric, reason):
    p, rows, grant = financial()
    next(r for r in rows if r["role"] == role)[field] = value
    assert valuations(p, rows, grant)[metric]["reason"] == reason


def test_no_currency_or_grant_identity_assumption():
    p, rows, grant = financial()
    p["currency"] = None
    assert valuations(p, rows, grant)["per"]["reason"] == "PRICE_CURRENCY_UNKNOWN"
    p["currency"] = "USD"
    grant.pop("split_basis_id")
    assert valuations(p, rows, grant)["per"]["reason"] == "CLASS_CURRENCY_SPLIT_COMPATIBILITY_NOT_APPROVED"


def test_bands_exact_backend_user_scenarios_and_no_forward_claim():
    rows = list(valuations().values())
    with localcontext() as ctx:
        ctx.prec = 2
        bands = fixed_multiple_bands(rows, {"per": ["10", "20"], "pbr": ["0.5", "2"]})
    assert [b["value"] for b in bands] == ["20", "40", "10.0", "40"]
    assert all(b["scenario_kind"] == "USER_FIXED_MULTIPLE_NOT_FORECAST" for b in bands)


def test_historical_uses_actual_daily_rows_and_ready_gate():
    rows = [copy.deepcopy(valuations()["per"]) for _ in range(3)]
    for i, row in enumerate(rows):
        row.update(as_of=f"2026-10-{21+i}", value=str(10 + i*10), observation_id=f"old-{i}")
    rows[1]["historical_ready"] = False
    kwargs = {"cik": "0000000001", "security_id": "US:TEST", "as_of": "2026-10-23", "multiple": "per", "session_source": {**sessions(365), "coverage_start":"2022-01-01", "coverage_end":"2027-01-01"}, "source_coverage": {"start":"2022-01-01", "end":"2027-01-01"}}
    kwargs["session_source"]["sessions"] = sorted(set(kwargs["session_source"]["sessions"] + [r["as_of"] for r in rows]))
    strict = historical_multiple_percentiles(rows, **kwargs, readiness_policy="READY_ONLY")
    assert strict["valid_sessions"] == 2
    assert strict["reason"] == "INSUFFICIENT_ELIGIBLE_HISTORY_252_SESSIONS"
    diagnostic = historical_multiple_percentiles(rows, **kwargs, readiness_policy="DIAGNOSTIC_FILED_DAY")
    assert diagnostic["diagnostic"] is True and diagnostic["backtest_eligible"] is False
    assert diagnostic["valid_sessions"] == 3
    rows.append(rows[0])
    with pytest.raises(ValueError, match="ambiguous"):
        historical_multiple_percentiles(rows, **kwargs, readiness_policy="READY_ONLY")


def test_price_readiness_and_financial_cutoff_are_independent_of_filed_knowledge():
    price, rows, grant = financial()
    price["ready_on"] = None
    values = calculate_valuation_metrics(price, rows, grant, cik="0000000001", security_id="US:TEST",
        as_of="2026-10-23", financial_as_of="2026-10-25")
    assert next(r for r in values if r["metric_id"] == "per")["historical_ready"] is False
    future = calculate_valuation_metrics(price, rows, grant, cik="0000000001", security_id="US:TEST",
        as_of="2026-10-23", financial_as_of="2026-10-22")
    assert all(r["reason"] == "FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF" for r in future)
    changed_anchor = calculate_valuation_metrics(price, rows, grant, cik="0000000001", security_id="US:TEST",
        as_of="2026-10-23", financial_as_of="2026-10-25", financial_anchor="2026-10-20")
    assert all(r["reason"] == "FINANCIAL_ANCHOR_SCOPE_NOT_APPROVED" for r in changed_anchor)
    assert valuations()["common_market_cap"]["share_measurement_date"] == "2026-09-30"
    assert valuations()["common_market_cap"]["share_period_end"] == "2026-10-01"


def test_historical_percentiles_require_calendar_coverage_and_minimum_eligible_sample():
    calendar = sessions(365)
    calendar["coverage_start"] = "2022-01-01"
    calendar["coverage_end"] = "2027-01-01"
    base = valuations()["pbr"]
    rows = [{**base, "as_of": day, "observation_id": f"history-{i}", "value": str(i + 1), "historical_ready": True}
            for i, day in enumerate(calendar["sessions"]) if day <= "2026-10-23"]
    args = {"cik": "0000000001", "security_id": "US:TEST", "as_of": "2026-10-23", "multiple": "pbr",
            "session_source": calendar, "source_coverage": {"start": "2022-01-01", "end": "2026-10-23"}}
    result = historical_multiple_percentiles(rows, **args, readiness_policy="READY_ONLY")
    assert result["status"] == "AVAILABLE"
    assert result["valid_sessions"] == result["expected_sessions"] == len(rows)
    assert Decimal(result["percentiles"]["0.5"]) == Decimal(len(rows)+1)/2
    assert result["backtest_eligible"] is True
    args["source_coverage"]["start"] = "2026-01-01"
    assert historical_multiple_percentiles(rows, **args, readiness_policy="READY_ONLY")["reason"] == "HISTORICAL_CALENDAR_OR_SOURCE_COVERAGE_INCOMPLETE"
