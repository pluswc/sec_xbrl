from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.screening.dataset_v2 import ScreeningDatasetV2Reader
from sec_xbrl.screening.explorer import CORE_METRIC_IDS, ScreeningExplorer

ALL_METRICS = (
    *CORE_METRIC_IDS,
    "cost",
    "gross_profit",
    "research",
    "operating_income",
    "capex",
    "cfi",
    "cff",
    "repurchases",
    "stock_compensation",
    "cash",
    "assets",
    "current_assets",
    "receivables",
    "inventory",
    "liabilities",
    "current_liabilities",
    "debt",
    "equity",
    "gross_margin",
    "net_margin",
    "fcf_margin",
    "liabilities_to_equity",
    "net_debt",
)


def test_explorer_defaults_to_latest_common_year_and_preserves_absent_rows() -> None:
    explorer = ScreeningExplorer(_reader())

    result = explorer.explore()
    assert result["selected_fiscal_year"] == 2025
    assert result["default_fiscal_year"] == 2025
    assert len(result["rows"]) == 21
    assert {row["companies_prepared"] for row in result["fiscal_years"] if row["fiscal_year"] == 2026} == {5}

    future = explorer.explore(fiscal_year=2026)
    assert len(future["rows"]) == 21
    assert sum(row["year_prepared"] for row in future["rows"]) == 5
    absent = next(row for row in future["rows"] if not row["year_prepared"])
    assert absent["metrics"]["revenue"]["value"] is None
    assert absent["metrics"]["revenue"]["reason_labels"] == ["선택 연도 자료 없음"]


def test_explorer_falls_back_to_latest_most_covered_year_without_mixing() -> None:
    reader = _reader()
    reader.observations = [
        row
        for row in reader.observations
        if (
            (int(row["cik"]) <= 10 and row["fiscal_year"] == 2024)
            or (int(row["cik"]) > 10 and row["fiscal_year"] == 2025)
        )
    ]

    result = ScreeningExplorer(reader).explore()

    assert result["default_fiscal_year"] == 2025
    assert result["default_year_is_common"] is False
    assert result["default_year_company_count"] == 11
    assert result["selected_year_company_count"] == 11
    assert sum(row["year_prepared"] for row in result["rows"]) == 11


def test_explorer_sort_rejects_nonvisible_metric() -> None:
    with pytest.raises(ValueError, match="visible core metric"):
        ScreeningExplorer(_reader()).explore(sort="gross_margin")


def test_metric_library_uses_selected_year_coverage_and_all_definitions() -> None:
    explorer = ScreeningExplorer(_reader())

    library = explorer.metric_library(fiscal_year=2026, query="매출")
    assert library["selected_fiscal_year"] == 2026
    assert {row["metric_id"] for row in explorer.metric_library()["metrics"]} == set(ALL_METRICS)
    revenue = next(row for row in library["metrics"] if row["metric_id"] == "revenue")
    assert revenue["selected_year_coverage"]["companies_available"] == 5
    assert revenue["selected_year_coverage"]["companies_prepared"] == 5
    missing = next(
        row
        for row in revenue["selected_year_coverage"]["reason_counts"]
        if row["code"] == "SELECTED_YEAR_NOT_PREPARED"
    )
    assert missing["count"] == 16
    assert revenue["definition_version"] == "annual-core-reported-v1"


def test_search_sort_profile_trend_and_compare_preserve_gaps() -> None:
    explorer = ScreeningExplorer(_reader())

    searched = explorer.explore(query="산업 3")
    assert [row["company"]["ticker"] for row in searched["rows"]] == ["T03"]
    descending = explorer.explore(sort="revenue", direction="desc")
    assert descending["rows"][0]["metrics"]["revenue"]["value"] == "210"
    assert descending["rows"][-1]["metrics"]["revenue"]["value"] is None

    profile = explorer.company_profile(cik="0000000001", fiscal_year=2025)
    assert len(profile["summary"]) == 8
    assert sum(len(group["metrics"]) for group in profile["groups"]) == 31
    assert len(profile["series"]["revenue"]) == 4
    assert profile["series"]["revenue"][0]["value"] is None
    assert profile["series"]["revenue"][0]["availability_status"] == "UNAVAILABLE"

    comparison = explorer.compare(
        ciks=["0000000001", "0000000002"],
        metric_ids=["revenue", "operating_margin"],
        fiscal_year=2025,
    )
    assert len(comparison["companies"]) == 2
    assert [row["metric"]["metric_id"] for row in comparison["rows"]] == [
        "revenue",
        "operating_margin",
    ]
    assert comparison["actual_periods"]["0000000001"]["period_end"] == "2026-01-01"


@pytest.mark.parametrize(
    ("ciks", "metrics"),
    [
        (["0000000001"], ["revenue"]),
        (["0000000001", "0000000001"], ["revenue"]),
        (["0000000001", "0000000002"], ["unknown"]),
    ],
)
def test_compare_rejects_invalid_scope(ciks: list[str], metrics: list[str]) -> None:
    with pytest.raises(ValueError):
        ScreeningExplorer(_reader()).compare(ciks=ciks, metric_ids=metrics)


def test_actual_r3_projection_matches_frozen_observations_when_available() -> None:
    root = Path(
        "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/"
        "screening_runs/20261009_usability/screening_dataset_r3"
    )
    if not root.is_dir():
        pytest.skip("actual R3 screening dataset is not available")
    reader = ScreeningDatasetV2Reader(root)
    explorer = ScreeningExplorer(reader)

    matrix = explorer.explore()
    library = explorer.metric_library()
    assert matrix["selected_fiscal_year"] == 2025
    assert len(matrix["rows"]) == 21
    assert len(library["metrics"]) == 31
    assert [(row["fiscal_year"], row["companies_prepared"]) for row in matrix["fiscal_years"]] == [
        (2022, 16),
        (2023, 21),
        (2024, 21),
        (2025, 21),
        (2026, 5),
    ]
    amd = next(row for row in matrix["rows"] if row["company"]["ticker"] == "AMD")
    source = next(
        row
        for row in reader.observations
        if row["ticker"] == "AMD" and row["metric_id"] == "revenue" and row["fiscal_year"] == 2025
    )
    assert amd["metrics"]["revenue"]["value"] == source["value"] == "34639000000"
    assert amd["metrics"]["revenue"]["period_start"] == source["period_start"]
    assert amd["metrics"]["revenue"]["period_end"] == source["period_end"]


def _reader() -> SimpleNamespace:
    companies = [
        {
            "cik": f"{index:010d}",
            "ticker": f"T{index:02d}",
            "name": f"회사 {index:02d}",
            "sic_description": f"산업 {index}",
        }
        for index in range(1, 22)
    ]
    definitions = [_definition(metric_id) for metric_id in ALL_METRICS]
    observations = []
    for index, company in enumerate(companies, 1):
        years = (2023, 2024, 2025, 2026) if index <= 5 else (2022, 2023, 2024, 2025)
        for year in years:
            for metric_id in ALL_METRICS:
                unavailable = metric_id == "revenue" and (
                    (company["cik"] == "0000000001" and year == 2023)
                    or (company["cik"] == "0000000002" and year == 2025)
                )
                observations.append(
                    {
                        "cik": company["cik"],
                        "metric_id": metric_id,
                        "fiscal_year": year,
                        "availability_status": "UNAVAILABLE" if unavailable else "AVAILABLE",
                        "value": None if unavailable else str(index * 10 + year - 2025),
                        "diagnostic_reasons": ["MISSING_INPUT"] if unavailable else [],
                        "unavailable_reason": "MISSING_INPUT" if unavailable else None,
                        "period_start": f"{year - 1}-01-01" if _period(metric_id) == "FY" else None,
                        "period_end": f"{year + 1}-01-01" if _period(metric_id) == "FY" else f"{year}-12-31",
                        "period_class": _period(metric_id),
                        "source_kind": _source_kind(metric_id),
                        "metric_definition_version": _version(metric_id),
                        "metric_observation_id": f"observation-{company['cik']}-{metric_id}-{year}",
                        "source_filings": [f"accession-{company['cik']}-{year}"],
                        "quality_status": None,
                        "warnings": [],
                    }
                )
    return SimpleNamespace(
        manifest={
            "dataset_id": "fixture-v2",
            "publication_id": "screening-dataset-fixture",
            "financial_as_of": "2026-10-08",
        },
        publication_id="screening-dataset-fixture",
        companies=companies,
        metric_definitions=definitions,
        observations=observations,
    )


def _definition(metric_id: str) -> dict:
    return {
        "metric_id": metric_id,
        "label": {
            "revenue": "매출",
            "revenue_yoy": "매출 전년 대비 성장률",
        }.get(metric_id, metric_id),
        "category": _category(metric_id),
        "period_class": _period(metric_id),
        "source_kind": _source_kind(metric_id),
        "unit_kind": "PERCENT" if metric_id.endswith(("margin", "ratio")) or metric_id == "revenue_yoy" else "MONEY",
        "unit": "PERCENT" if metric_id.endswith(("margin", "ratio")) or metric_id == "revenue_yoy" else "USD",
        "definition_version": _version(metric_id),
        "formula": None,
        "input_metric_ids": [],
    }


def _category(metric_id: str) -> str:
    if metric_id in {"revenue", "revenue_yoy"}:
        return "GROWTH"
    if metric_id in {"operating_margin", "net_income", "cost", "gross_profit", "operating_income", "gross_margin", "net_margin"}:
        return "PROFITABILITY"
    if metric_id in {"cfo", "standardized_fcf", "capex", "cfi", "cff", "fcf_margin"}:
        return "CASH_FLOW"
    if metric_id in {"current_ratio", "liabilities_to_assets", "cash", "assets", "current_assets", "liabilities", "current_liabilities", "debt", "equity", "liabilities_to_equity", "net_debt"}:
        return "FINANCIAL_STABILITY"
    return "OTHER_REPORTED"


def _period(metric_id: str) -> str:
    return "INSTANT" if metric_id in {"cash", "assets", "current_assets", "receivables", "inventory", "liabilities", "current_liabilities", "debt", "equity", "current_ratio", "liabilities_to_equity", "liabilities_to_assets", "net_debt"} else "FY"


def _source_kind(metric_id: str) -> str:
    return "DERIVED_METRIC" if metric_id in {"revenue_yoy", "gross_margin", "operating_margin", "net_margin", "standardized_fcf", "fcf_margin", "current_ratio", "liabilities_to_equity", "liabilities_to_assets", "net_debt"} else "REPORTED"


def _version(metric_id: str) -> str:
    return "annual-core-reported-v1" if metric_id in {"revenue", "cfo", "operating_income", "net_income"} else f"definition-{metric_id}-v1"
