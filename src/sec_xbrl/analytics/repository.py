"""In-process, provenance-first analytical repository for the M9 boundary.

This module deliberately contains no MCP transport or parser object references.
It accepts independently materialized Layer 1, Layer 2 series, and Layer 3
comparison records, copies them on entry, and returns copies on every query.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any


class AnalyticalRepositoryError(LookupError):
    """Base error for stable analytical-repository lookup failures."""


class CompanyNotFoundError(AnalyticalRepositoryError):
    """Raised when no supplied company matches a company selector."""


class CompanyAmbiguousError(AnalyticalRepositoryError):
    """Raised when a company selector identifies more than one company."""


class FactNotFoundError(AnalyticalRepositoryError):
    """Raised when no reported or derived fact has the requested fact ID."""


class AnalyticalRepository:
    """Read-only facade over materialized analytical records.

    ``companies`` has one row per company and should include a CIK plus any
    available ticker, name, and company canonical ID.  ``facts`` is Layer 1
    (and may include derived records); ``series`` is Layer 2 output; and
    ``comparisons`` is Layer 3 panel output.  Missing optional provenance is
    left absent rather than inferred.
    """

    def __init__(
        self,
        *,
        companies: Iterable[Mapping[str, Any]],
        filings: Iterable[Mapping[str, Any]] = (),
        concepts: Iterable[Mapping[str, Any]] = (),
        facts: Iterable[Mapping[str, Any]] = (),
        series: Iterable[Mapping[str, Any]] = (),
        comparisons: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self._companies = _copy_rows(companies)
        self._filings = _copy_rows(filings)
        self._concepts = _copy_rows(concepts)
        self._facts = _copy_rows(facts)
        self._series = _copy_rows(series)
        self._comparisons = _copy_rows(comparisons)
        self._filings_by_id = {
            str(row["filing_id"]): row for row in self._filings if row.get("filing_id")
        }
        self._concepts_by_id = {
            str(row["raw_concept_id"]): row
            for row in self._concepts
            if row.get("raw_concept_id")
        }

    def resolve_company(self, selector: str) -> dict[str, Any]:
        """Resolve an exact CIK, ticker, canonical ID, or normalized company name.

        A name selector intentionally requires exactly one match; callers must
        refine a selector rather than receiving an arbitrary company.
        """
        value = str(selector).strip()
        if not value:
            raise CompanyNotFoundError("company selector must not be empty")
        matches = [row for row in self._companies if _company_matches(row, value)]
        if not matches:
            raise CompanyNotFoundError(f"no company matches {value!r}")
        unique = {str(row.get("company_canonical_id") or row.get("cik") or id(row)): row for row in matches}
        if len(unique) != 1:
            raise CompanyAmbiguousError(f"company selector {value!r} is ambiguous")
        return deepcopy(next(iter(unique.values())))

    def get_fact_series(
        self,
        company: str,
        concept: str,
        frequency: str | None = None,
        start: str | None = None,
        end: str | None = None,
        view: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return a company/concept series, without coalescing period classes.

        ``frequency`` filters exact Layer 2 ``period_class`` values.  ``view``
        filters exact ``series_type`` values (for example ``ANNUAL`` or
        ``CURRENT``).  Date limits apply to ISO source/report periods only.
        """
        resolved = self.resolve_company(company)
        rows = [
            row
            for row in self._series
            if _row_is_company(row, resolved)
            and _concept_matches(row, concept)
            and (frequency is None or str(row.get("period_class") or "") == frequency)
            and (view is None or str(row.get("series_type") or "") == view)
            and _within_period(row, start, end)
        ]
        return tuple(self._with_provenance(row, resolved) for row in _sort_rows(rows))

    def compare_companies(
        self,
        companies: Sequence[str],
        concept_or_metric: str,
        period_or_range: str | tuple[str | None, str | None] | None = None,
        mapping_version: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return visible Layer 3 comparison rows for the selected companies.

        Low-confidence and ``ANALYTICALLY_SIMILAR`` rows are returned unchanged;
        no relation is promoted to equivalence by this boundary.
        """
        if not companies:
            raise CompanyNotFoundError("compare_companies requires at least one company")
        resolved = tuple(self.resolve_company(selector) for selector in companies)
        start, end = _period_range(period_or_range)
        rows = [
            row
            for row in self._comparisons
            if any(_row_is_company(row, item) for item in resolved)
            and _concept_matches(row, concept_or_metric)
            and (mapping_version is None or row.get("mapping_version") == mapping_version)
            and _within_period(row, start, end)
        ]
        return tuple(self._with_provenance(row, _company_for_row(row, resolved)) for row in _sort_rows(rows))

    def trace_fact(self, fact_id: str) -> dict[str, Any]:
        """Return one provenance-enriched reported or derived fact by stable ID."""
        target = str(fact_id)
        rows = [row for row in (*self._facts, *self._series) if str(row.get("fact_id")) == target]
        if not rows:
            raise FactNotFoundError(f"no fact matches {target!r}")
        # Prefer an explicit fact record; a series row is its analytical view.
        row = next((item for item in rows if item in self._facts), rows[0])
        company = _company_for_row(row, self._companies)
        return self._with_provenance(row, company)

    def _with_provenance(
        self, source: Mapping[str, Any], company: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        row = deepcopy(dict(source))
        filing_id = str(row.get("source_filing_id") or row.get("filing_id") or "")
        filing = self._filings_by_id.get(filing_id)
        if filing:
            for key in ("cik", "accession", "form", "filed_date", "report_date"):
                if row.get(key) is None and filing.get(key) is not None:
                    row[key] = deepcopy(filing[key])
            if row.get("report_period") is None and filing.get("report_date") is not None:
                row["report_period"] = deepcopy(filing["report_date"])
        raw_id = _raw_concept_id(row)
        concept = self._concepts_by_id.get(raw_id)
        if concept:
            for key in ("qname", "namespace_uri", "local_name", "is_standard", "is_custom"):
                if row.get(key) is None and concept.get(key) is not None:
                    row[key] = deepcopy(concept[key])
        if company:
            for key in ("cik", "company_canonical_id"):
                if row.get(key) is None and company.get(key) is not None:
                    row[key] = deepcopy(company[key])
        if "reported_or_derived" not in row:
            row["reported_or_derived"] = "DERIVED" if _is_derived(row) else "REPORTED"
        return row


def _copy_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(deepcopy(dict(row)) for row in rows)


def _normalize_cik(value: object) -> str:
    text = str(value or "").strip()
    return text.zfill(10) if text.isdigit() else text


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _company_matches(row: Mapping[str, Any], selector: str) -> bool:
    normalized = _normalized_name(selector)
    return selector == str(row.get("company_canonical_id") or "") or (
        _normalize_cik(selector) == _normalize_cik(row.get("cik"))
    ) or normalized in {
        _normalized_name(row.get("ticker")),
        _normalized_name(row.get("name")),
        _normalized_name(row.get("company_name")),
    }


def _row_is_company(row: Mapping[str, Any], company: Mapping[str, Any]) -> bool:
    company_id = str(company.get("company_canonical_id") or "")
    row_id = str(row.get("company_canonical_id") or "")
    if company_id and row_id:
        return company_id == row_id
    return _normalize_cik(row.get("cik")) == _normalize_cik(company.get("cik"))


def _company_for_row(
    row: Mapping[str, Any], companies: Iterable[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    return next((company for company in companies if _row_is_company(row, company)), None)


def _raw_concept_id(row: Mapping[str, Any]) -> str:
    return str(row.get("source_raw_id") or row.get("raw_concept_id") or "")


def _concept_matches(row: Mapping[str, Any], selector: str) -> bool:
    value = str(selector)
    return value in {
        _raw_concept_id(row),
        str(row.get("company_canonical_id") or row.get("company_canonical_concept_id") or ""),
        str(row.get("analytical_id") or ""),
        str(row.get("qname") or ""),
        str(row.get("local_name") or ""),
    }


def _period_value(row: Mapping[str, Any]) -> str | None:
    for key in ("source_period", "report_period", "period_end"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def _within_period(row: Mapping[str, Any], start: str | None, end: str | None) -> bool:
    value = _period_value(row)
    return value is not None and (start is None or value >= start) and (end is None or value <= end)


def _period_range(value: str | tuple[str | None, str | None] | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, tuple):
        return value
    return value, value


def _sort_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda row: (_period_value(row) or "", str(row.get("fact_id") or "")))


def _is_derived(row: Mapping[str, Any]) -> bool:
    return bool(row.get("source_fact_ids") or row.get("derivation_formula") or row.get("formula"))
