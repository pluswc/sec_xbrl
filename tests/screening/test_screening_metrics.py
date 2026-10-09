from __future__ import annotations

import copy
import inspect
from decimal import Decimal, getcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.analysis import (
    _analysis_columns,
    _annual_fy_end_by_year,
    _with_primary_statement_evidence,
    open_analysis,
    prepare_analysis,
)
from sec_xbrl.metrics.screening import (
    DEFINITION_BY_ID,
    METRIC_DEFINITIONS,
    _derive_net_debt,
    _derive_pair,
    _derive_revenue_yoy,
    _exact_subtract,
    expanded_analysis_profile,
)


def _reported(
    metric_id: str,
    value: str,
    *,
    year: int = 2025,
    period_class: str = "FY",
    start: str | None = "2024-12-29",
    end: str = "2025-12-28",
    statement_type: str = "IS",
    qname: str | None = None,
    basis: str | None = None,
) -> dict:
    return {
        "metric_observation_id": f"observation-{metric_id}-{year}",
        "cik": "0000000001",
        "ticker": "TEST",
        "metric_id": metric_id,
        "metric_definition_version": "test-v1",
        "source_kind": "REPORTED",
        "fiscal_year": year,
        "period_class": period_class,
        "period_start": start if period_class == "FY" else None,
        "period_end": end,
        "view": "LATEST_REPORTED",
        "financial_as_of": "2026-10-08",
        "availability_status": "AVAILABLE",
        "unavailable_reason": None,
        "diagnostic_reasons": [],
        "value": value,
        "unit_kind": "MONEY",
        "unit": "USD",
        "unit_semantics": ['["iso4217:USD"]', "[]"],
        "dimensions": [],
        "basis_version": basis,
        "quality_status": None,
        "mapping_review_required": False,
        "semantic_identity": qname or metric_id,
        "raw_concept_qname": qname or f"us-gaap:{metric_id}",
        "raw_concept_taxonomy_family": "us-gaap",
        "raw_concept_data_type": "xbrli:monetaryItemType",
        "raw_concept_period_type": "duration" if period_class == "FY" else "instant",
        "concept_mapping_version": "mapping-v1",
        "selection_rule_version": "selection-v1",
        "classification_rule_version": "period-v1",
        "parser_version": "parser-v1",
        "source_fact_ids": [f"fact-{metric_id}-{year}"],
        "source_filings": [f"filing-{year}"],
        "primary_statement_evidence": [
            {"statement_types": [statement_type], "source_relationship_edge_id": f"edge-{metric_id}"}
        ] if statement_type else [],
        "source_snapshot_id": "snapshot",
    }


def test_expanded_profile_and_opt_in_signature_are_exact() -> None:
    profile = expanded_analysis_profile()
    assert len(METRIC_DEFINITIONS) == 31
    assert len(profile) == 21
    assert len([row for row in profile if row["period_class"] == "FY"]) == 12
    assert len([row for row in profile if row["period_class"] == "INSTANT"]) == 9
    assert "eps" not in {row["row_id"] for row in profile}
    assert "shares" not in {row["row_id"] for row in profile}
    assert inspect.signature(prepare_analysis).parameters["include_year_end_balances"].default is False


def test_exact_year_end_instant_selection_rejects_interim_and_ambiguous_fy() -> None:
    fy_columns = [
        {"fiscal_year": 2024, "column_status": "AVAILABLE", "actual_end_date": "2024-12-29"},
        {"fiscal_year": 2025, "column_status": "AVAILABLE", "actual_end_date": "2025-12-28"},
    ]
    ends = _annual_fy_end_by_year(fy_columns, [2024, 2025])
    instant_columns = [
        {"fiscal_time_series_column_id": "interim", "fiscal_year": 2025, "fiscal_quarter": 3,
         "period_class": "INSTANT", "column_status": "AVAILABLE", "actual_instant_date": "2025-09-27"},
        {"fiscal_time_series_column_id": "year-end", "fiscal_year": 2025, "fiscal_quarter": 4,
         "period_class": "INSTANT", "column_status": "REVIEW_REQUIRED",
         "column_reason": "MISSING_ACTUAL_DURATION", "actual_instant_date": "2025-12-28"},
    ]
    selected = _analysis_columns(
        instant_columns, years=[2025], period_class="INSTANT", period_mode="ANNUAL", exact_fy_ends=ends
    )
    assert list(selected) == ["year-end"]
    assert selected["year-end"]["fiscal_label"] == "FY2025 기말"
    assert selected["year-end"]["column_status"] == "REVIEW_REQUIRED"
    assert selected["year-end"]["column_reason"] == "MISSING_ACTUAL_DURATION"
    assert selected["year-end"]["screening_balance_eligibility"] == "EXACT_FY_END_INSTANT"
    ambiguous = _annual_fy_end_by_year(
        [*fy_columns, {**fy_columns[-1], "actual_end_date": "2025-12-31"}], [2025]
    )
    assert ambiguous == {}


def test_missing_cell_keeps_absent_lineage_when_statement_evidence_is_requested() -> None:
    lineage, evidence = _with_primary_statement_evidence(
        None,
        {"primary_statement_evidence": [{"statement_types": ["BS"]}]},
    )
    assert lineage is None
    assert evidence == []


def test_opt_in_prepare_preserves_unavailable_cell_with_no_lineage(
    tmp_path: Path, monkeypatch
) -> None:
    from sec_xbrl import analysis

    fy_column = {
        "fiscal_time_series_column_id": "fy-2025",
        "fiscal_year": 2025,
        "fiscal_quarter": 4,
        "period_class": "FY",
        "column_status": "AVAILABLE",
        "actual_end_date": "2025-12-28",
    }
    instant_column = {
        "fiscal_time_series_column_id": "instant-2025",
        "fiscal_year": 2025,
        "fiscal_quarter": 4,
        "period_class": "INSTANT",
        "column_status": "REVIEW_REQUIRED",
        "column_reason": "MISSING_ACTUAL_DURATION",
        "actual_instant_date": "2025-12-28",
    }
    row = {
        "fiscal_time_series_row_id": "cash",
        "raw_concept_qname": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "mapping_review_required": False,
        "row_identity": ["JOIN"],
    }
    reported_lineage = {
        "selected_source_fact_id": "fact-revenue",
        "source_filing_id": "filing-2025",
        "context_start_date": "2024-12-29",
        "context_end_date": "2025-12-28",
        "raw_dimension_signature": [],
        "mapping_review_required": False,
        "raw_concept_is_standard": True,
        "raw_concept_taxonomy_family": "us-gaap",
        "raw_concept_data_type": "xbrli:monetaryItemType",
        "unit_numerator_measures": '["iso4217:USD"]',
        "unit_denominator_measures": "[]",
    }
    panels = {
        "FY": SimpleNamespace(
            columns=(fy_column,),
            rows=(row,),
            cells=(
                {
                    "fiscal_time_series_cell_id": "cash-fy-2025",
                    "fiscal_time_series_row_id": "cash",
                    "fiscal_time_series_column_id": "fy-2025",
                    "value_status": "REPORTED",
                    "value_numeric": "10",
                    "value_lineage": reported_lineage,
                    "comparability_status": "COMPARABLE",
                },
            ),
            scope={"selection_as_of_date": "2026-10-08"},
        ),
        "INSTANT": SimpleNamespace(
            columns=(instant_column,),
            rows=(row,),
            cells=(
                {
                    "fiscal_time_series_cell_id": "cash-instant-2025",
                    "fiscal_time_series_row_id": "cash",
                    "fiscal_time_series_column_id": "instant-2025",
                    "value_status": "UNAVAILABLE",
                    "value_numeric": None,
                    "value_lineage": None,
                    "resolution_reason": "NO_CANDIDATE",
                    "comparability_status": "UNAVAILABLE",
                    "binding": {"primary_statement_evidence": [{"statement_types": ["BS"]}]},
                },
            ),
            scope={"selection_as_of_date": "2026-10-08"},
        ),
    }
    history = tmp_path / "history"
    history.mkdir()
    (history / "history_manifest.json").write_text("{}\n")
    reader = SimpleNamespace(
        root=history,
        manifest={"tables": [{"ticker": "TEST", "period_class": key} for key in panels]},
        load=lambda **kwargs: panels[kwargs["period_class"]],
    )
    monkeypatch.setattr(analysis, "open_history_publication", lambda publication: reader)
    monkeypatch.setattr(analysis, "_raw_material", lambda *args: ({}, []))
    destination = prepare_analysis(
        publication=history,
        destination=tmp_path / "analysis",
        tickers=("TEST",),
        fiscal_start=2025,
        fiscal_end=2025,
        period_mode="ANNUAL",
        include_year_end_balances=True,
        configuration={
            "TEST": {
                "core_rows": [
                    {
                        "row_id": "cash",
                        "concepts": ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
                        "period_class": "INSTANT",
                    }
                ]
            }
        },
    )
    client = open_analysis(destination)
    cells = client._records("TEST", "LATEST_REPORTED", "core_cells")
    missing = next(cell for cell in cells if cell["period_class"] == "INSTANT")
    assert missing["status"] == "UNAVAILABLE"
    assert missing["reason"] == "NO_CANDIDATE"
    assert missing["value"] is None
    assert "primary_statement_evidence" not in missing
    traces = [
        trace
        for digit in "0123456789abcdef"
        for trace in client._records("TEST", "LATEST_REPORTED", f"trace_{digit}")
    ]
    trace = next(row for row in traces if row["cell_id"] == missing["cell_id"])
    assert trace["value_lineage"] is None


def test_revenue_yoy_accepts_53_week_duration_and_ignores_ambient_precision() -> None:
    qname = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    current = _reported("revenue", "130", year=2025, start="2024-12-22", end="2025-12-28", qname=qname)
    prior = _reported("revenue", "100", year=2024, start="2023-12-24", end="2024-12-22", qname=qname)
    previous_precision = getcontext().prec
    getcontext().prec = 3
    try:
        result = _derive_revenue_yoy(
            ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["revenue_yoy"],
            current=current, prior=prior, fiscal_year=2025,
        )
    finally:
        getcontext().prec = previous_precision
    assert result["availability_status"] == "AVAILABLE"
    assert result["value"] == "30"
    assert result["warnings"] == ["ACTUAL_DURATION_DIFFERS"]


def test_rational_percentage_and_money_subtraction_have_explicit_precision() -> None:
    qname = "us-gaap:Revenues"
    current = _reported("revenue", "10000000000000000000000000001", year=2025, qname=qname)
    prior = _reported("revenue", "10000000000000000000000000000", year=2024,
                      start="2023-12-31", end="2024-12-29", qname=qname)
    old_precision = getcontext().prec
    getcontext().prec = 3
    try:
        result = _derive_revenue_yoy(
            ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["revenue_yoy"],
            current=current, prior=prior, fiscal_year=2025,
        )
        money = _exact_subtract(
            Decimal("10000000000000000000000000001.01"),
            Decimal("9999999999999999999999999999.99"),
        )
    finally:
        getcontext().prec = old_precision
    assert result["value"] == "0.00000000000000000000000001"
    assert money == Decimal("1.02")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda current, prior: current.update(raw_concept_qname="us-gaap:SalesRevenueNet"), "SEMANTIC_IDENTITY_MISMATCH"),
        (lambda current, prior: prior.update(period_start="2024-02-01"), "FY_DURATION_OUT_OF_RANGE"),
        (lambda current, prior: current.update(basis_version="new"), "BASIS_INCOMPATIBLE"),
        (lambda current, prior: prior.update(value="0"), "NON_POSITIVE_DENOMINATOR"),
    ],
)
def test_revenue_yoy_fails_closed_on_semantic_period_basis_and_zero(mutation, reason) -> None:
    qname = "us-gaap:Revenues"
    current = _reported("revenue", "120", year=2025, qname=qname)
    prior = _reported("revenue", "100", year=2024, start="2023-12-31", end="2024-12-29", qname=qname)
    mutation(current, prior)
    result = _derive_revenue_yoy(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["revenue_yoy"],
        current=current, prior=prior, fiscal_year=2025,
    )
    assert result["availability_status"] == "UNAVAILABLE"
    assert reason in result["diagnostic_reasons"]


def test_margin_allows_loss_but_rejects_zero_revenue_and_role_mismatch() -> None:
    loss = _reported("operating_income", "-25")
    revenue = _reported("revenue", "100")
    result = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["operating_margin"],
        first=loss, second=revenue, fiscal_year=2025, statement_types=({"IS"}, {"IS"}), operation="PERCENT",
    )
    assert result["value"] == "-25"
    zero = copy.deepcopy(revenue)
    zero["value"] = "0"
    unavailable = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["operating_margin"],
        first=loss, second=zero, fiscal_year=2025, statement_types=({"IS"}, {"IS"}), operation="PERCENT",
    )
    assert unavailable["unavailable_reason"] == "NON_POSITIVE_DENOMINATOR"
    revenue["primary_statement_evidence"] = []
    no_role = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["operating_margin"],
        first=loss, second=revenue, fiscal_year=2025, statement_types=({"IS"}, {"IS"}), operation="PERCENT",
    )
    assert "PRIMARY_STATEMENT_EVIDENCE_MISSING" in no_role["diagnostic_reasons"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("period_end", "2025-12-31", "PERIOD_MISMATCH"),
        ("unit_semantics", ['["iso4217:EUR"]', "[]"], "UNIT_MISMATCH"),
        ("dimensions", [["axis", "member"]], "DIMENSION_MISMATCH"),
        ("source_filings", ["other-filing"], "SOURCE_FILING_MISMATCH"),
    ],
)
def test_derived_pair_rejects_period_unit_dimension_and_filing_mismatch(
    field: str, value: object, reason: str
) -> None:
    numerator = _reported("gross_profit", "30")
    revenue = _reported("revenue", "100")
    numerator[field] = value
    result = _derive_pair(
        ticker="TEST",
        cik="0000000001",
        definition=DEFINITION_BY_ID["gross_margin"],
        first=numerator,
        second=revenue,
        fiscal_year=2025,
        statement_types=({"IS"}, {"IS"}),
        operation="PERCENT",
    )
    assert result["availability_status"] == "UNAVAILABLE"
    assert reason in result["diagnostic_reasons"]


def test_fcf_capex_sign_and_balance_ratio_negative_gates() -> None:
    cfo = _reported("cfo", "80", statement_type="CF")
    capex = _reported("capex", "20", statement_type="CF")
    fcf = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["standardized_fcf"],
        first=cfo, second=capex, fiscal_year=2025, statement_types=({"CF"}, {"CF"}),
        operation="SUBTRACT", require_nonnegative_second=True,
    )
    assert fcf["value"] == "60"
    capex["value"] = "-20"
    rejected = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["standardized_fcf"],
        first=cfo, second=capex, fiscal_year=2025, statement_types=({"CF"}, {"CF"}),
        operation="SUBTRACT", require_nonnegative_second=True,
    )
    assert rejected["unavailable_reason"] == "CAPEX_SIGN_UNCERTAIN"
    liabilities = _reported("liabilities", "-1", period_class="INSTANT", start=None, statement_type="BS")
    assets = _reported("assets", "100", period_class="INSTANT", start=None, statement_type="BS")
    ratio = _derive_pair(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["liabilities_to_assets"],
        first=liabilities, second=assets, fiscal_year=2025, statement_types=({"BS"}, {"BS"}),
        operation="PERCENT", require_nonnegative_first=True,
    )
    assert ratio["unavailable_reason"] == "NEGATIVE_NUMERATOR"


def test_net_debt_exact_standard_note_allowance_and_nonnegative_components() -> None:
    debt = _reported(
        "debt", "70", period_class="INSTANT", start=None, statement_type="",
        qname="us-gaap:DebtLongtermAndShorttermCombinedAmount",
    )
    cash = _reported("cash", "100", period_class="INSTANT", start=None, statement_type="BS")
    result = _derive_net_debt(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["net_debt"],
        debt=debt, cash=cash, fiscal_year=2025,
    )
    assert result["value"] == "-30"
    assert result["debt_input_policy"] == "EXACT_STANDARD_COMBINED_DEBT_NOTE_ALLOWANCE"
    custom = copy.deepcopy(debt)
    custom["raw_concept_qname"] = "test:CombinedDebt"
    rejected = _derive_net_debt(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["net_debt"],
        debt=custom, cash=cash, fiscal_year=2025,
    )
    assert "DIRECT_COMBINED_DEBT_UNAVAILABLE" in rejected["diagnostic_reasons"]
    negative = copy.deepcopy(debt)
    negative["value"] = "-1"
    rejected_negative = _derive_net_debt(
        ticker="TEST", cik="0000000001", definition=DEFINITION_BY_ID["net_debt"],
        debt=negative, cash=cash, fiscal_year=2025,
    )
    assert rejected_negative["unavailable_reason"] == "NEGATIVE_BALANCE_COMPONENT"

