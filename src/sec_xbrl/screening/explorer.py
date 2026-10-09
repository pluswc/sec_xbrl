"""Read-only company and metric projections over a verified screening dataset."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sec_xbrl.screening.common import canonical_json, require_cik, require_string
from sec_xbrl.screening.dataset_v2 import ScreeningDatasetV2Reader

CORE_METRIC_IDS = (
    "revenue",
    "revenue_yoy",
    "operating_margin",
    "net_income",
    "cfo",
    "standardized_fcf",
    "current_ratio",
    "liabilities_to_assets",
)
CATEGORY_ORDER = (
    "GROWTH",
    "PROFITABILITY",
    "CASH_FLOW",
    "FINANCIAL_STABILITY",
    "OTHER_REPORTED",
)
CATEGORY_LABELS = {
    "GROWTH": "성장성",
    "PROFITABILITY": "수익성",
    "CASH_FLOW": "현금흐름",
    "FINANCIAL_STABILITY": "재무안정성",
    "OTHER_REPORTED": "기타 공시항목",
}

_GUIDANCE: dict[str, tuple[str, str]] = {
    "revenue": ("한 회계연도에 회사가 보고한 매출입니다.", "사업 규모와 매출 흐름을 볼 때 사용합니다."),
    "cost": ("매출을 내기 위해 회사가 보고한 원가입니다.", "매출총이익과 원가 부담을 함께 볼 때 사용합니다."),
    "gross_profit": ("매출에서 매출원가를 뺀 회사 보고 금액입니다.", "핵심 영업의 이익 여력을 볼 때 사용합니다."),
    "research": ("회사가 보고한 연구개발비입니다.", "미래 제품·기술 투자 규모를 볼 때 사용합니다."),
    "operating_income": ("본업에서 회사가 보고한 영업이익 또는 손실입니다.", "본업의 수익 규모를 볼 때 사용합니다."),
    "net_income": ("해당 회계연도의 회사 보고 순이익 또는 손실입니다.", "최종 손익을 볼 때 사용합니다."),
    "cfo": ("영업활동에서 발생한 회사 보고 현금흐름입니다.", "본업의 현금 창출을 볼 때 사용합니다."),
    "capex": ("유형자산 취득에 사용한 회사 보고 지출입니다.", "설비 투자 부담을 볼 때 사용합니다."),
    "cfi": ("투자활동 전체의 회사 보고 현금흐름입니다.", "투자와 자산 처분 흐름을 볼 때 사용합니다."),
    "cff": ("재무활동 전체의 회사 보고 현금흐름입니다.", "차입·상환·자본 거래 흐름을 볼 때 사용합니다."),
    "repurchases": ("회사가 보고한 자사주 취득 지출입니다.", "주주환원 관련 현금 사용을 볼 때 사용합니다."),
    "stock_compensation": ("회사가 보고한 주식보상비용입니다.", "주식 기반 보상 규모를 볼 때 사용합니다."),
    "cash": ("회계연도 말의 현금 및 현금성자산입니다.", "즉시 사용할 수 있는 유동성을 볼 때 사용합니다."),
    "assets": ("회계연도 말의 회사 보고 총자산입니다.", "재무상태표 규모를 볼 때 사용합니다."),
    "current_assets": ("회계연도 말의 회사 보고 유동자산입니다.", "단기 자산 여력을 볼 때 사용합니다."),
    "receivables": ("회계연도 말의 회사 보고 매출채권입니다.", "아직 회수하지 않은 매출 관련 자산을 볼 때 사용합니다."),
    "inventory": ("회계연도 말의 회사 보고 재고자산입니다.", "판매 전 재고 규모를 볼 때 사용합니다."),
    "liabilities": ("회계연도 말의 회사 보고 총부채입니다.", "전체 부채 부담을 볼 때 사용하며 차입금과는 다릅니다."),
    "current_liabilities": ("회계연도 말의 회사 보고 유동부채입니다.", "단기 지급 부담을 볼 때 사용합니다."),
    "debt": ("회사가 직접 결합해 보고한 차입금입니다.", "직접 보고된 이자부 차입금 범위를 볼 때만 사용합니다."),
    "equity": ("회계연도 말의 회사 보고 자본입니다.", "자산에서 부채를 뺀 순자산 기반을 볼 때 사용합니다."),
    "revenue_yoy": ("현재 연도 매출을 직전 회계연도 매출과 비교한 성장률입니다.", "연간 매출의 증가·감소를 볼 때 사용합니다."),
    "gross_margin": ("회사 보고 매출총이익을 같은 연도 매출로 나눈 비율입니다.", "매출원가를 반영한 수익성을 볼 때 사용합니다."),
    "operating_margin": ("회사 보고 영업이익을 같은 연도 매출로 나눈 비율입니다.", "본업의 매출 대비 수익성을 볼 때 사용합니다."),
    "net_margin": ("회사 보고 순이익을 같은 연도 매출로 나눈 비율입니다.", "최종 손익의 매출 대비 비중을 볼 때 사용합니다."),
    "standardized_fcf": ("영업현금흐름에서 유형자산 취득 지출을 뺀 표준화 값입니다.", "일관된 두 보고 항목으로 투자 후 현금을 볼 때 사용합니다."),
    "fcf_margin": ("표준화 FCF를 같은 연도 매출로 나눈 비율입니다.", "매출 대비 표준화 현금 여력을 볼 때 사용합니다."),
    "current_ratio": ("유동자산을 유동부채로 나눈 백분율입니다.", "단기 지급 여력을 볼 때 사용합니다."),
    "liabilities_to_equity": ("총부채를 자본으로 나눈 백분율입니다.", "자본 대비 전체 부채 부담을 볼 때 사용합니다."),
    "liabilities_to_assets": ("총부채를 총자산으로 나눈 백분율입니다.", "자산 중 부채가 차지하는 비중을 볼 때 사용합니다."),
    "net_debt": ("직접 보고 결합 차입금에서 현금을 뺀 값입니다.", "직접 결합 차입금이 있는 회사의 순차입 상태를 볼 때 사용합니다."),
}

_REASON_LABELS = {
    "SELECTED_YEAR_NOT_PREPARED": "선택 연도 자료 없음",
    "MISSING_INPUT": "필요한 보고 항목 없음",
    "MULTIPLE_CANDIDATES": "여러 후보가 있어 값 확정 필요",
    "MAPPING_REVIEW_REQUIRED": "항목 연결 검토 필요",
    "QUALITY_BLOCKED": "자료 품질 확인 필요",
    "PRIMARY_STATEMENT_EVIDENCE_MISSING": "주요 재무제표 근거 없음",
    "DIRECT_COMBINED_DEBT_UNAVAILABLE": "직접 보고 결합 차입금 없음",
    "NON_POSITIVE_DENOMINATOR": "비율 계산 기준값이 0 이하",
    "NEGATIVE_EQUITY": "자본이 0 이하",
    "CAPEX_SIGN_UNCERTAIN": "유형자산 지출 부호 확인 필요",
    "PERIOD_MISMATCH": "재무기간 불일치",
    "SOURCE_FILING_MISMATCH": "출처 공시 불일치",
    "BASIS_INCOMPATIBLE": "회계 기준 비교 불가",
    "SEMANTIC_IDENTITY_MISMATCH": "보고 항목 의미 불일치",
}


class ScreeningExplorer:
    """Indexed, display-only projections from one verified v2 publication."""

    def __init__(self, reader: ScreeningDatasetV2Reader) -> None:
        self.reader = reader
        self.definitions = {
            row["metric_id"]: row for row in reader.metric_definitions
        }
        self.companies = {row["cik"]: row for row in reader.companies}
        self.observations = {
            (row["cik"], row["metric_id"], row["fiscal_year"]): row
            for row in reader.observations
        }
        self.company_years = {
            cik: sorted(
                {
                    row["fiscal_year"]
                    for row in reader.observations
                    if row["cik"] == cik
                }
            )
            for cik in self.companies
        }
        years = sorted({year for values in self.company_years.values() for year in values})
        self.year_options = [
            {
                "fiscal_year": year,
                "companies_prepared": sum(
                    year in values for values in self.company_years.values()
                ),
                "companies_total": len(self.companies),
            }
            for year in years
        ]
        common = [
            row["fiscal_year"]
            for row in self.year_options
            if row["companies_prepared"] == row["companies_total"]
        ]
        if common:
            self.default_fiscal_year = max(common)
            self.default_year_is_common = True
        else:
            most_covered = max(
                self.year_options,
                key=lambda row: (row["companies_prepared"], row["fiscal_year"]),
            )
            self.default_fiscal_year = most_covered["fiscal_year"]
            self.default_year_is_common = False

    def explore(
        self,
        *,
        fiscal_year: int | None = None,
        query: str | None = None,
        sort: str = "company",
        direction: str = "asc",
    ) -> dict[str, Any]:
        year = self._year(fiscal_year)
        sort = require_string(sort, "explorer sort")
        direction = require_string(direction, "explorer sort direction").lower()
        if direction not in {"asc", "desc"}:
            raise ValueError("explorer sort direction must be asc or desc")
        if sort != "company" and sort not in CORE_METRIC_IDS:
            raise ValueError("explorer sort must be company or a visible core metric")
        needle = (query or "").strip().casefold()
        rows = []
        for company in self.companies.values():
            if needle and not any(
                needle in str(value or "").casefold()
                for value in (
                    company.get("name"),
                    company.get("ticker"),
                    company.get("sic_description"),
                )
            ):
                continue
            metrics = {
                metric_id: self._observation(company["cik"], metric_id, year)
                for metric_id in CORE_METRIC_IDS
            }
            rows.append(
                {
                    "company": self._company(company),
                    "year_prepared": year in self.company_years[company["cik"]],
                    "actual_period": self._actual_period(company["cik"], year),
                    "metrics": metrics,
                }
            )
        rows = self._sort(rows, sort, direction)
        return self._context(year) | {
            "core_metric_ids": list(CORE_METRIC_IDS),
            "core_metrics": [self._definition(metric_id, year) for metric_id in CORE_METRIC_IDS],
            "query": query or "",
            "sort": sort,
            "direction": direction,
            "rows": rows,
        }

    def metric_library(
        self,
        *,
        fiscal_year: int | None = None,
        query: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        year = self._year(fiscal_year)
        if category is not None and category not in CATEGORY_ORDER:
            raise ValueError("unknown metric category")
        needle = (query or "").strip().casefold()
        metrics = []
        for metric_id in self.definitions:
            item = self._definition(metric_id, year)
            if category is not None and item["category"] != category:
                continue
            searchable = " ".join(
                str(item.get(key) or "")
                for key in ("metric_id", "label", "meaning", "use", "category_label")
            ).casefold()
            if needle and needle not in searchable:
                continue
            metrics.append(item)
        return self._context(year) | {
            "query": query or "",
            "category": category,
            "categories": [
                {"code": code, "label": CATEGORY_LABELS[code]} for code in CATEGORY_ORDER
            ],
            "metrics": metrics,
        }

    def company_profile(
        self, *, cik: str, fiscal_year: int | None = None
    ) -> dict[str, Any]:
        cik = require_cik(cik)
        if cik not in self.companies:
            raise ValueError("company is not prepared in this dataset")
        year = self._year(fiscal_year)
        groups = []
        for category in CATEGORY_ORDER:
            metrics = [
                self._profile_metric(cik, metric_id, year)
                for metric_id, definition in self.definitions.items()
                if definition["category"] == category
            ]
            groups.append(
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "metrics": metrics,
                }
            )
        series = {
            metric_id: [
                self._observation(cik, metric_id, prepared_year)
                for prepared_year in self.company_years[cik]
            ]
            for metric_id in self.definitions
        }
        return self._context(year) | {
            "company": self._company(self.companies[cik]),
            "prepared_years": self.company_years[cik],
            "year_prepared": year in self.company_years[cik],
            "actual_period": self._actual_period(cik, year),
            "summary": [self._profile_metric(cik, metric_id, year) for metric_id in CORE_METRIC_IDS],
            "groups": groups,
            "series": series,
        }

    def compare(
        self,
        *,
        ciks: list[str],
        metric_ids: list[str],
        fiscal_year: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(ciks, list) or not 2 <= len(ciks) <= 4:
            raise ValueError("company comparison requires two to four CIKs")
        checked_ciks = [require_cik(cik) for cik in ciks]
        if len(set(checked_ciks)) != len(checked_ciks):
            raise ValueError("company comparison contains duplicate CIKs")
        if any(cik not in self.companies for cik in checked_ciks):
            raise ValueError("company comparison contains an unprepared company")
        if not isinstance(metric_ids, list) or not 1 <= len(metric_ids) <= len(self.definitions):
            raise ValueError("company comparison requires one to 31 metrics")
        checked_metrics = [require_string(value, "metric_id") for value in metric_ids]
        if len(set(checked_metrics)) != len(checked_metrics):
            raise ValueError("company comparison contains duplicate metrics")
        if any(metric_id not in self.definitions for metric_id in checked_metrics):
            raise ValueError("company comparison contains an unknown metric")
        year = self._year(fiscal_year)
        return self._context(year) | {
            "companies": [self._company(self.companies[cik]) for cik in checked_ciks],
            "actual_periods": {
                cik: self._actual_period(cik, year) for cik in checked_ciks
            },
            "rows": [
                {
                    "metric": self._definition(metric_id, year),
                    "values": {
                        cik: self._observation(cik, metric_id, year)
                        for cik in checked_ciks
                    },
                }
                for metric_id in checked_metrics
            ],
            "date_limitation": "같은 회계연도 표시는 실제 시작·종료일이 같다는 뜻이 아닙니다.",
        }

    def _context(self, fiscal_year: int) -> dict[str, Any]:
        selected = next(
            row for row in self.year_options if row["fiscal_year"] == fiscal_year
        )
        default = next(
            row
            for row in self.year_options
            if row["fiscal_year"] == self.default_fiscal_year
        )
        return {
            "dataset_id": self.reader.manifest["dataset_id"],
            "dataset_publication_id": self.reader.publication_id,
            "financial_as_of": self.reader.manifest["financial_as_of"],
            "selected_fiscal_year": fiscal_year,
            "default_fiscal_year": self.default_fiscal_year,
            "default_year_is_common": self.default_year_is_common,
            "default_year_company_count": default["companies_prepared"],
            "selected_year_company_count": selected["companies_prepared"],
            "fiscal_years": self.year_options,
            "company_count": len(self.companies),
        }

    def _year(self, fiscal_year: int | None) -> int:
        if fiscal_year is None:
            return self.default_fiscal_year
        if type(fiscal_year) is not int:
            raise TypeError("fiscal_year must be an integer")
        if fiscal_year not in {row["fiscal_year"] for row in self.year_options}:
            raise ValueError("fiscal_year is not prepared in this dataset")
        return fiscal_year

    def _definition(self, metric_id: str, fiscal_year: int) -> dict[str, Any]:
        definition = self.definitions[metric_id]
        observations = [
            self.observations.get((cik, metric_id, fiscal_year)) for cik in self.companies
        ]
        available = sum(_available(row) for row in observations)
        prepared = sum(
            fiscal_year in self.company_years[cik] for cik in self.companies
        )
        reasons: dict[str, int] = {}
        for cik, row in zip(self.companies, observations, strict=True):
            codes = (
                ["SELECTED_YEAR_NOT_PREPARED"]
                if fiscal_year not in self.company_years[cik]
                else _reason_codes(row)
            )
            for code in codes:
                reasons[code] = reasons.get(code, 0) + 1
        meaning, use = _GUIDANCE[metric_id]
        return {
            "metric_id": metric_id,
            "label": definition["label"],
            "category": definition["category"],
            "category_label": CATEGORY_LABELS[definition["category"]],
            "meaning": meaning,
            "use": use,
            "period_class": definition["period_class"],
            "period_label": "연간실적" if definition["period_class"] == "FY" else "연도말 재무상태",
            "source_kind": definition["source_kind"],
            "source_label": "회사 보고" if definition["source_kind"] == "REPORTED" else "표준화 계산",
            "unit_kind": definition["unit_kind"],
            "unit": definition["unit"],
            "definition_version": definition["definition_version"],
            "formula": definition.get("formula"),
            "input_metric_ids": definition.get("input_metric_ids", []),
            "selected_year_coverage": {
                "companies_available": available,
                "companies_prepared": prepared,
                "companies_total": len(self.companies),
                "companies_unavailable": len(self.companies) - available,
                "reason_counts": [
                    {
                        "code": code,
                        "label": _reason_label(code),
                        "count": count,
                    }
                    for code, count in sorted(reasons.items())
                ],
            },
        }

    def _profile_metric(self, cik: str, metric_id: str, fiscal_year: int) -> dict[str, Any]:
        return {
            "definition": self._definition(metric_id, fiscal_year),
            "observation": self._observation(cik, metric_id, fiscal_year),
        }

    def _observation(self, cik: str, metric_id: str, fiscal_year: int) -> dict[str, Any]:
        row = self.observations.get((cik, metric_id, fiscal_year))
        if row is None:
            return {
                "metric_id": metric_id,
                "fiscal_year": fiscal_year,
                "availability_status": "UNAVAILABLE",
                "value": None,
                "reason_codes": ["SELECTED_YEAR_NOT_PREPARED"],
                "reason_labels": [_reason_label("SELECTED_YEAR_NOT_PREPARED")],
                "period_start": None,
                "period_end": None,
                "period_class": self.definitions[metric_id]["period_class"],
                "source_kind": self.definitions[metric_id]["source_kind"],
                "definition_version": self.definitions[metric_id]["definition_version"],
                "metric_observation_id": None,
                "source_filings": [],
                "quality_status": None,
            }
        codes = _reason_codes(row)
        return {
            "metric_id": metric_id,
            "fiscal_year": fiscal_year,
            "availability_status": row["availability_status"],
            "value": row.get("value") if _available(row) else None,
            "reason_codes": codes,
            "reason_labels": [_reason_label(code) for code in codes],
            "period_start": row.get("period_start"),
            "period_end": row.get("period_end"),
            "period_class": row["period_class"],
            "source_kind": row["source_kind"],
            "definition_version": row["metric_definition_version"],
            "metric_observation_id": row["metric_observation_id"],
            "source_filings": row.get("source_filings", []),
            "quality_status": row.get("quality_status"),
            "warnings": row.get("warnings", []),
        }

    def _company(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "cik": row["cik"],
            "ticker": row["ticker"],
            "name": row["name"],
            "industry": row.get("sic_description") or "업종 정보 없음",
            "financial_as_of": self.reader.manifest["financial_as_of"],
            "prepared_years": self.company_years[row["cik"]],
        }

    def _actual_period(self, cik: str, fiscal_year: int) -> dict[str, Any] | None:
        candidates = [
            row
            for (row_cik, _, year), row in self.observations.items()
            if row_cik == cik and year == fiscal_year and row["period_class"] == "FY"
        ]
        if not candidates:
            return None
        periods = sorted(
            {
                (row["period_start"], row["period_end"])
                for row in candidates
                if row.get("period_start") is not None and row.get("period_end") is not None
            }
        )
        if not periods:
            return None
        if len(periods) != 1:
            raise ValueError("company fiscal year has conflicting actual periods")
        start, end = periods[0]
        return {"period_start": start, "period_end": end, "end_convention": "EXCLUSIVE"}

    @staticmethod
    def _sort(
        rows: list[dict[str, Any]], sort: str, direction: str
    ) -> list[dict[str, Any]]:
        if sort == "company":
            return sorted(
                rows,
                key=lambda row: (
                    row["company"]["ticker"].casefold(),
                    row["company"]["cik"],
                ),
                reverse=direction == "desc",
            )
        available = [row for row in rows if row["metrics"].get(sort, {}).get("value") is not None]
        missing = [row for row in rows if row["metrics"].get(sort, {}).get("value") is None]
        available.sort(
            key=lambda row: (
                Decimal(row["metrics"][sort]["value"]),
                row["company"]["cik"],
            ),
            reverse=direction == "desc",
        )
        missing.sort(key=lambda row: row["company"]["cik"])
        return available + missing


def _available(row: dict[str, Any] | None) -> bool:
    return bool(
        row is not None
        and row.get("availability_status") == "AVAILABLE"
        and row.get("value") is not None
    )


def _reason_codes(row: dict[str, Any] | None) -> list[str]:
    if row is None:
        return []
    values = list(row.get("diagnostic_reasons") or [])
    unavailable = row.get("unavailable_reason")
    if unavailable and unavailable not in values:
        values.append(unavailable)
    return values


def _reason_label(code: str) -> str:
    return _REASON_LABELS.get(code, "자료 조건을 충족하지 않음")


def public_copy(value: Any) -> Any:
    """Return a detached JSON-compatible projection for HTTP callers."""
    return json.loads(canonical_json(value))
