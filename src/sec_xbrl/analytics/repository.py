"""In-process, provenance-first analytical repository for the M9 boundary.

This module deliberately contains no MCP transport or parser object references.
It accepts independently materialized Layer 1, Layer 2 series, and Layer 3
comparison records, copies them on entry, and returns copies on every query.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.capability import CapabilityInventoryQuery
from sec_xbrl.longitudinal.materialization import Layer2PublicationReader
from sec_xbrl.metrics.series import DerivedMetricSeriesMaterializer


class AnalyticalRepositoryError(LookupError):
    """Base error for stable analytical-repository lookup failures."""


class CompanyNotFoundError(AnalyticalRepositoryError):
    """Raised when no supplied company matches a company selector."""


class CompanyAmbiguousError(AnalyticalRepositoryError):
    """Raised when a company selector identifies more than one company."""


class FactNotFoundError(AnalyticalRepositoryError):
    """Raised when no reported or derived fact has the requested fact ID."""


class CapabilityInventoryNotFoundError(AnalyticalRepositoryError):
    """Raised when a resolved company has no supplied capability inventory."""


class DerivedMetricNotFoundError(AnalyticalRepositoryError):
    """Raised when no verified derived metric has the requested stable ID."""


class DerivedMetricConflictError(AnalyticalRepositoryError):
    """Raised when one derived metric ID has conflicting verified records."""


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
        analytical_facts: Iterable[Mapping[str, Any]] = (),
        capability_inventory: Iterable[Mapping[str, Any]] = (),
        metric_series_run_roots: Iterable[Path] = (),
        comparisons: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self._companies = _copy_rows(companies)
        self._filings = _copy_rows(filings)
        self._concepts = _copy_rows(concepts)
        self._facts = _copy_rows(facts)
        self._series = _copy_rows(series)
        self._analytical_facts = _copy_rows(analytical_facts)
        self._capability_inventory = _copy_rows(capability_inventory)
        self._capability_query = CapabilityInventoryQuery(self._capability_inventory)
        metric_materializer = DerivedMetricSeriesMaterializer()
        self._metric_series_candidates = _copy_rows(
            candidate
            for root in metric_series_run_roots
            for candidate in metric_materializer.load_published_candidates(Path(root))
        )
        self._comparisons = _copy_rows(comparisons)
        self._filings_by_id = {
            str(row["filing_id"]): row for row in self._filings if row.get("filing_id")
        }
        self._concepts_by_id = {
            str(row["raw_concept_id"]): row
            for row in self._concepts
            if row.get("raw_concept_id")
        }

    @classmethod
    def from_layer2_publications(
        cls,
        layer2_publication_roots: Iterable[Path],
        *,
        company_catalog: Iterable[Mapping[str, Any]] = (),
        metric_series_run_roots: Iterable[Path] = (),
    ) -> AnalyticalRepository:
        """Build a consumer repository from manifest-verified L2 publications only.

        This is the current canonical-JSONL publication adapter.  It does not
        implement a database or Parquet adapter, infer company metadata, or
        perform any Layer 2 selection.  Each exposed L2 row retains the
        immutable publication identity that admitted it.
        """
        reader = Layer2PublicationReader()
        publications = tuple(reader.load(Path(root)) for root in layer2_publication_roots)
        if not publications:
            raise AnalyticalRepositoryError("at least one verified Layer 2 publication is required")
        declared_ciks = {
            cik
            for publication in publications
            for cik in publication.input_ciks
        }
        catalog_by_cik: dict[str, dict[str, Any]] = {}
        allowed_catalog_fields = {"cik", "ticker", "name", "company_name", "company_canonical_id"}
        for catalog_row in company_catalog:
            row = dict(catalog_row)
            if set(row) - allowed_catalog_fields or not row.get("cik"):
                raise AnalyticalRepositoryError("company catalog supports CIK/ticker/name/canonical ID only")
            cik = _normalize_cik(row["cik"])
            if cik not in {_normalize_cik(value) for value in declared_ciks}:
                raise AnalyticalRepositoryError("company catalog CIK is not declared by Layer 2 publication")
            if cik in catalog_by_cik and catalog_by_cik[cik] != row:
                raise AnalyticalRepositoryError("company catalog has conflicting metadata for one CIK")
            copied = deepcopy(row)
            copied["cik"] = cik
            catalog_by_cik[cik] = copied
        companies = []
        for cik in sorted(declared_ciks):
            row = {"cik": cik}
            row.update(catalog_by_cik.get(_normalize_cik(cik), {}))
            companies.append(row)
        analytical_facts: list[dict[str, Any]] = []
        capabilities: list[dict[str, Any]] = []
        for publication in publications:
            identity = deepcopy(dict(publication.identity))
            analytical_facts.extend(
                _with_publication_identity(row, identity)
                for row in publication.records("analytical_fact")
            )
            capabilities.extend(
                _with_publication_identity(row, identity)
                for row in publication.records("capability_inventory")
            )
        return cls(
            companies=companies,
            analytical_facts=analytical_facts,
            capability_inventory=capabilities,
            metric_series_run_roots=metric_series_run_roots,
        )

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

    def get_analytical_facts(
        self,
        company: str,
        *,
        view: str,
        concept: str | None = None,
        period_class: str | None = None,
        period_key: str | None = None,
        as_of_date: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read exact governed L2 analytical facts without selection or coalescing.

        ``view`` is required so a consumer cannot silently mix `AS_FILED` and
        `CURRENT_COMPARABLE`.  Optional filters are exact; an omitted filter
        preserves every matching basis, source type, dimension, status, and
        unavailable/evidence/selection lineage in the verified publication.
        """
        if view not in {"AS_FILED", "CURRENT_COMPARABLE"}:
            raise AnalyticalRepositoryError("get_analytical_facts requires a supported explicit view")
        resolved = self.resolve_company(company)
        rows = [
            row
            for row in self._analytical_facts
            if _row_is_company(row, resolved)
            and row.get("view") == view
            and (concept is None or _concept_matches(row, concept))
            and (period_class is None or row.get("period_class") == period_class)
            and (period_key is None or row.get("period_key") == period_key)
            and (as_of_date is None or row.get("as_of_date") == as_of_date)
        ]
        return tuple(self._with_provenance(row, resolved) for row in _sort_analytical_rows(rows))

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

    def get_metric_series(
        self,
        company: str,
        metric: str,
        *,
        as_of_date: str,
        view: str,
        frequency: str | None = None,
        start: str | None = None,
        end: str | None = None,
        definition_version: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read a governed same-company metric series without recalculation.

        Callers must choose both the historical view and its date.  The facade
        only selects immutable M1 revisions; it never substitutes a basis,
        infers a metric from a label, or evaluates a formula.
        """
        resolved = self.resolve_company(company)
        candidates = [
            row
            for row in self._metric_series_candidates
            if _row_is_company(row, resolved)
            and metric in {str(row.get("metric_id") or ""), str(row.get("metric_definition_id") or "")}
            and (frequency is None or str(row.get("period_class") or "") == frequency)
            and (definition_version is None or str(row.get("metric_definition_version") or "") == definition_version)
            and _within_period(row, start, end)
        ]
        selected = DerivedMetricSeriesMaterializer().select(
            candidates, as_of_date=as_of_date, view=view
        )
        return tuple(self._with_provenance(row, resolved) for row in selected)

    def discover_capabilities(
        self,
        company: str,
        *,
        raw_concept_id: str | None = None,
        axis_raw_concept_id: str | None = None,
        member_raw_concept_id: str | None = None,
        period_class: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return supplied M5 capabilities for one resolved public company.

        This method delegates filtering and ``NOT_REPORTED`` behavior to the
        governed M5 query contract.  It does not infer disclosure categories
        or promote an omitted structure to a company-wide claim.
        """
        resolved = self.resolve_company(company)
        cik = resolved.get("cik")
        if cik is None:
            raise CapabilityInventoryNotFoundError(
                "resolved company has no CIK for capability inventory lookup"
            )
        try:
            return self._capability_query.discover(
                cik=str(cik),
                raw_concept_id=raw_concept_id,
                axis_raw_concept_id=axis_raw_concept_id,
                member_raw_concept_id=member_raw_concept_id,
                period_class=period_class,
            )
        except LookupError as exc:
            raise CapabilityInventoryNotFoundError(
                f"company has no supplied capability inventory: {cik}"
            ) from exc

    def discover_metrics(
        self,
        company: str,
        *,
        metric_id: str | None = None,
        definition_version: str | None = None,
        frequency: str | None = None,
        view: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Discover admitted metric candidates without metric selection.

        This is a discovery view over records that were admitted through the
        hash-verified M1-to-M2 publication path during construction.  It does
        not call M2 selection, choose an ``as_of_date``, calculate a value, or
        infer a Metric from a label.  Each response group retains its full
        dimension, basis, definition, formula, status, and mapping variants;
        its ``observed_metric_records`` preserve every admitted candidate and
        associated publication provenance.

        ``NOT_REPORTED`` is deliberately limited to the supplied verified
        publication scope.  It means no admitted candidate for this resolved
        company matches the exact request; it is not a claim about every SEC
        filing or a company-wide metric template.
        """
        resolved = self.resolve_company(company)
        candidates = [
            row
            for row in self._metric_series_candidates
            if _row_is_company(row, resolved)
            and (metric_id is None or str(row.get("metric_id") or "") == metric_id)
            and (
                definition_version is None
                or str(row.get("metric_definition_version") or "") == definition_version
            )
            and (frequency is None or str(row.get("period_class") or "") == frequency)
            and (view is None or str(row.get("view") or "") == view)
        ]
        if not candidates:
            return (
                {
                    "cik": deepcopy(resolved.get("cik")),
                    "company_canonical_id": deepcopy(resolved.get("company_canonical_id")),
                    "metric_discovery_status": "NOT_REPORTED",
                    "status_reason": "NO_ADMITTED_VERIFIED_METRIC_MATCHES_REQUEST",
                    "metric_discovery_scope": "SUPPLIED_VERIFIED_METRIC_PUBLICATIONS_ONLY",
                    "requested_metric_id": metric_id,
                    "requested_definition_version": definition_version,
                    "requested_frequency": frequency,
                    "requested_view": view,
                },
            )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in candidates:
            grouped.setdefault(_metric_discovery_group_key(row), []).append(row)
        discovered = [
            _metric_discovery_row(resolved, rows)
            for _, rows in sorted(grouped.items())
        ]
        return tuple(deepcopy(row) for row in discovered)

    def trace_metric(self, derived_metric_id: str) -> dict[str, Any]:
        """Return one immutable M1 metric record admitted through verified M2 roots.

        A metric identity must identify exactly one stored record.  Conflicting
        records from multiple verified roots fail closed; the facade never
        selects one by root ordering, metric value, or recency.
        """
        target = str(derived_metric_id).strip()
        if not target:
            raise DerivedMetricNotFoundError("derived metric ID must not be empty")
        rows = [
            row
            for row in self._metric_series_candidates
            if str(row.get("derived_metric_id") or "") == target
        ]
        if not rows:
            raise DerivedMetricNotFoundError(f"no verified derived metric matches {target!r}")
        versions = {_canonical_record(row) for row in rows}
        if len(versions) != 1:
            raise DerivedMetricConflictError(
                f"verified derived metric identity {target!r} has conflicting records"
            )
        row = min(rows, key=_canonical_record)
        return self._with_provenance(row, _company_for_row(row, self._companies))

    def trace_fact(self, fact_id: str) -> dict[str, Any]:
        """Return one provenance-enriched reported or derived fact by stable ID."""
        target = str(fact_id)
        rows = [
            row for row in (*self._facts, *self._series, *self._analytical_facts)
            if str(row.get("fact_id") or row.get("analytical_fact_id")) == target
        ]
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
        return row


def _copy_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(deepcopy(dict(row)) for row in rows)


def _with_publication_identity(
    row: Mapping[str, Any], identity: Mapping[str, str]
) -> dict[str, Any]:
    copied = deepcopy(dict(row))
    copied["layer2_publication_identity"] = deepcopy(dict(identity))
    return copied


def _canonical_record(row: Mapping[str, Any]) -> str:
    """Use a stable full-record comparison for conflict detection only."""
    return json.dumps(row, default=list, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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
    for key in ("source_period", "report_period", "period_end", "period_key"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def _within_period(row: Mapping[str, Any], start: str | None, end: str | None) -> bool:
    value = _period_value(row)
    return value is not None and (start is None or value >= start) and (end is None or value <= end)


def _metric_discovery_group_key(row: Mapping[str, Any]) -> str:
    """Identify a discovery variant without collapsing analytical semantics."""
    return _canonical_record({
        key: row.get(key)
        for key in (
            "cik",
            "metric_id",
            "metric_definition_id",
            "metric_definition_version",
            "formula_id",
            "formula_version",
            "view",
            "basis_version",
            "company_canonical_dimension_key",
            "input_unit_semantics",
            "metric_unit_semantics",
            "series_type",
            "period_class",
            "calculation_status",
            "unavailable_reason",
            "source_type",
            "mapping_versions",
        )
    })


def _metric_discovery_row(
    company: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Create one deterministic discovery row and retain all exact candidates."""
    observed = tuple(sorted((_copy_rows(rows)), key=_metric_candidate_sort_key))
    template = observed[0]
    return {
        "cik": deepcopy(template.get("cik") or company.get("cik")),
        "company_canonical_id": deepcopy(company.get("company_canonical_id")),
        "metric_discovery_status": "OBSERVED",
        "metric_id": deepcopy(template.get("metric_id")),
        "metric_definition_id": deepcopy(template.get("metric_definition_id")),
        "metric_definition_version": deepcopy(template.get("metric_definition_version")),
        "formula_id": deepcopy(template.get("formula_id")),
        "formula_version": deepcopy(template.get("formula_version")),
        "view": deepcopy(template.get("view")),
        "basis_version": deepcopy(template.get("basis_version")),
        "company_canonical_dimension_key": deepcopy(template.get("company_canonical_dimension_key")),
        "input_unit_semantics": deepcopy(template.get("input_unit_semantics")),
        "metric_unit_semantics": deepcopy(template.get("metric_unit_semantics")),
        "series_type": deepcopy(template.get("series_type")),
        "calculation_status": deepcopy(template.get("calculation_status")),
        "unavailable_reason": deepcopy(template.get("unavailable_reason")),
        "source_type": deepcopy(template.get("source_type")),
        "mapping_versions": deepcopy(template.get("mapping_versions")),
        "observed_period_classes": tuple(sorted({str(row["period_class"]) for row in observed})),
        "observed_period_keys": tuple(sorted({str(row["period_key"]) for row in observed})),
        "observed_views": tuple(sorted({str(row["view"]) for row in observed})),
        "observed_as_of_dates": tuple(sorted({str(row["as_of_date"]) for row in observed})),
        "derived_metric_ids": tuple(sorted({str(row["derived_metric_id"]) for row in observed})),
        "metric_series_candidate_ids": tuple(
            sorted({str(row["metric_series_candidate_id"]) for row in observed})
        ),
        "source_metric_run_versions": tuple(
            sorted({str(row["source_metric_run_version"]) for row in observed})
        ),
        "source_metric_run_fingerprints": tuple(
            sorted({str(row["source_metric_run_fingerprint"]) for row in observed})
        ),
        "source_metric_manifest_identities": tuple(
            sorted({str(row["source_metric_manifest_identity"]) for row in observed})
        ),
        "metric_series_contract_versions": tuple(
            sorted({str(row["metric_series_contract_version"]) for row in observed})
        ),
        "observed_metric_records": observed,
    }


def _metric_candidate_sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("period_class") or ""),
        str(row.get("period_key") or ""),
        str(row.get("as_of_date") or ""),
        str(row.get("evaluated_at") or ""),
        str(row.get("derived_metric_id") or ""),
    )


def _period_range(value: str | tuple[str | None, str | None] | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, tuple):
        return value
    return value, value


def _sort_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda row: (_period_value(row) or "", str(row.get("fact_id") or "")))


def _sort_analytical_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("period_class") or ""),
            str(row.get("period_key") or row.get("period_end") or ""),
            str(row.get("as_of_date") or ""),
            str(row.get("analytical_fact_id") or ""),
        ),
    )
