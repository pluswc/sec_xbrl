"""Read-only, provenance-preserving comparison of selected T6 pivot cells.

This is deliberately the first, narrow Layer 3 serving surface.  It compares
one governed fiscal column across companies; it neither selects facts nor
recasts, calculates, ranks, or aggregates values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sec_xbrl.analytics.quarterly_analysis_pivot import QuarterlyAnalysisPivotResult
from sec_xbrl.cross_company.mapping import (
    CROSS_COMPANY_MAPPING_VERSION,
    CrossCompanyMapper,
    CrossCompanyRelation,
)

CROSS_COMPANY_COMPARISON_PANEL_VERSION = "analysis-t8-cross-company-comparison-v1"


class CrossCompanyComparisonPanelError(ValueError):
    """Raised if a comparison would mix governed query scopes or hide a conflict."""


@dataclass(frozen=True, slots=True)
class CrossCompanyComparisonPanelResult:
    """One selected fiscal column, rows, and company-specific source cells."""

    companies: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]
    cells: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class CrossCompanyComparisonPanelBuilder:
    """Compare T6 outputs only through narrow, governed Layer 3 relations."""

    def build(
        self,
        *,
        pivots: Iterable[QuarterlyAnalysisPivotResult],
        fiscal_year: int,
        fiscal_quarter: int,
        reviewed_concept_mappings: Iterable[Mapping[str, Any]] = (),
    ) -> CrossCompanyComparisonPanelResult:
        """Build a one-column comparison panel.

        The input pivots must agree on period class, selection view and as-of
        date.  Automatic mapping is confined to undimensioned, exact qualified
        standard taxonomy identity with matching unit semantics.  Reviewed
        Layer 3 mappings can express analytical similarity/subset scope, but
        never silently replace the automatic standard identity relation.
        """
        prepared = tuple(pivots)
        if len(prepared) < 2:
            raise CrossCompanyComparisonPanelError("comparison panel requires at least two company pivots")
        if not isinstance(fiscal_year, int) or fiscal_year < 1 or fiscal_quarter not in {1, 2, 3, 4}:
            raise CrossCompanyComparisonPanelError("comparison requires a valid selected fiscal column")
        scope = _shared_scope(prepared, fiscal_year, fiscal_quarter)
        sources = _selected_sources(prepared, fiscal_year, fiscal_quarter)
        explicit = tuple(dict(row) for row in reviewed_concept_mappings)
        _validate_reviewed_mappings(explicit)
        mapper = CrossCompanyMapper()
        maps = mapper.build(
            concept_mappings=explicit,
            standard_concept_observations=_qualified_automatic_observations(sources),
        )
        mapping_by_company = {
            str(row["company_canonical_id"]): dict(row) for row in maps.cross_company_concept_map
        }
        rows_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
        cells: list[dict[str, Any]] = []
        occupied: set[tuple[str, str]] = set()
        for source in sources:
            mapping = mapping_by_company.get(source["company_canonical_id"])
            if mapping is None:
                mapping = _unresolved(source["company_canonical_id"])
            key = _comparison_key(source, mapping)
            row_id = _stable_id("row", key)
            if key not in rows_by_key:
                rows_by_key[key] = _row(row_id, source, mapping)
            coordinate = (row_id, source["cik"])
            if coordinate in occupied:
                raise CrossCompanyComparisonPanelError(
                    "multiple selected T6 cells collide for one company comparison row"
                )
            occupied.add(coordinate)
            cells.append(_cell(row_id, source, mapping))
        companies = tuple(
            {"cik": cik, "company_order_key": cik}
            for cik in sorted({source["cik"] for source in sources})
        )
        return CrossCompanyComparisonPanelResult(
            companies=companies,
            rows=tuple(sorted(rows_by_key.values(), key=_row_order)),
            cells=tuple(sorted(cells, key=lambda cell: (cell["comparison_row_id"], cell["cik"]))),
            scope={
                **scope,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "cross_company_comparison_panel_version": CROSS_COMPANY_COMPARISON_PANEL_VERSION,
            },
        )


class CrossCompanyComparisonPanelQuery:
    """Read-only rows with an explicit unavailable cell for absent companies."""

    def __init__(self, panel: CrossCompanyComparisonPanelResult) -> None:
        self._panel = deepcopy(panel)

    def matrix(self) -> tuple[dict[str, Any], ...]:
        by_coordinate = {(cell["comparison_row_id"], cell["cik"]): cell for cell in self._panel.cells}
        result: list[dict[str, Any]] = []
        for row in self._panel.rows:
            rendered = []
            for company in self._panel.companies:
                cell = by_coordinate.get((row["comparison_row_id"], company["cik"]))
                rendered.append(
                    deepcopy(cell)
                    if cell is not None
                    else {
                        "comparison_row_id": row["comparison_row_id"],
                        "cik": company["cik"],
                        "value_status": "UNAVAILABLE",
                        "unavailable_reason": "NO_T6_CELL_FOR_COMPANY",
                        "value_numeric": None,
                        "value_text": None,
                    }
                )
            result.append({"row": deepcopy(row), "cells": tuple(rendered)})
        return tuple(result)


def _shared_scope(
    pivots: tuple[QuarterlyAnalysisPivotResult, ...], fiscal_year: int, fiscal_quarter: int
) -> dict[str, Any]:
    keys = ("period_class", "selection_view", "selection_as_of_date")
    first = dict(pivots[0].scope)
    if any(first.get(key) in (None, "") for key in keys):
        raise CrossCompanyComparisonPanelError("T6 pivot is missing company-independent query scope")
    ciks: set[str] = set()
    for pivot in pivots:
        scope = pivot.scope
        cik = str(scope.get("cik") or "")
        if not cik:
            raise CrossCompanyComparisonPanelError("T6 pivot is missing company identity")
        if cik in ciks:
            raise CrossCompanyComparisonPanelError("comparison requires exactly one T6 pivot per company")
        ciks.add(cik)
        if any(scope.get(key) != first.get(key) for key in keys):
            raise CrossCompanyComparisonPanelError(
                "comparison cannot mix period class, selection view, or as-of date"
            )
        if not any(
            column.get("fiscal_year") == fiscal_year
            and column.get("fiscal_quarter") == fiscal_quarter
            and column.get("period_class") == first["period_class"]
            for column in pivot.columns
        ):
            raise CrossCompanyComparisonPanelError("selected fiscal column is absent from a company T6 pivot")
    return {key: first[key] for key in keys}


def _selected_sources(
    pivots: tuple[QuarterlyAnalysisPivotResult, ...], fiscal_year: int, fiscal_quarter: int
) -> tuple[dict[str, Any], ...]:
    sources: list[dict[str, Any]] = []
    for pivot in pivots:
        cik = str(pivot.scope["cik"])
        column_ids = {
            str(column["quarterly_analysis_column_id"])
            for column in pivot.columns
            if column.get("fiscal_year") == fiscal_year and column.get("fiscal_quarter") == fiscal_quarter
        }
        if len(column_ids) != 1:
            raise CrossCompanyComparisonPanelError("selected fiscal column is ambiguous in a T6 pivot")
        column_id = next(iter(column_ids))
        row_by_id = {str(row["quarterly_analysis_row_id"]): dict(row) for row in pivot.rows}
        for cell in pivot.cells:
            if str(cell.get("quarterly_analysis_column_id")) != column_id:
                continue
            row = row_by_id.get(str(cell.get("quarterly_analysis_row_id")))
            if row is None:
                raise CrossCompanyComparisonPanelError("T6 cell is missing row lineage")
            sources.append(_source(cik, row, cell, pivot.scope))
    return tuple(sorted(sources, key=lambda source: (source["cik"], source["t6_row_id"])))


def _source(cik: str, row: Mapping[str, Any], cell: Mapping[str, Any], scope: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(cell.get("value_lineage") or {})
    binding = dict(cell.get("binding") or {})
    raw_qname = str(value.get("raw_concept_qname") or binding.get("raw_concept_qname") or row.get("raw_concept_qname") or "")
    company_id = str(value.get("company_canonical_concept_id") or row.get("company_canonical_concept_id") or "")
    if not raw_qname or not company_id:
        raise CrossCompanyComparisonPanelError("T6 cell has no raw/company canonical concept lineage")
    return {
        "cik": cik,
        "t6_row_id": str(row["quarterly_analysis_row_id"]),
        "raw_concept_qname": raw_qname,
        "raw_concept_id": value.get("raw_concept_id") or binding.get("raw_concept_id"),
        "company_canonical_id": company_id,
        "raw_concept_is_standard": value.get("raw_concept_is_standard"),
        "raw_concept_taxonomy_family": value.get("raw_concept_taxonomy_family"),
        "raw_concept_data_type": value.get("raw_concept_data_type"),
        "raw_concept_period_type": value.get("raw_concept_period_type"),
        "raw_dimension_signature": deepcopy(value.get("raw_dimension_signature")),
        "unit_numerator_measures": deepcopy(value.get("unit_numerator_measures")),
        "unit_denominator_measures": deepcopy(value.get("unit_denominator_measures")),
        "source_filing_id": value.get("source_filing_id"),
        "source_period": {
            "period_class": scope["period_class"],
            "context_start_date": value.get("context_start_date"),
            "context_end_date": value.get("context_end_date"),
            "context_instant_date": value.get("context_instant_date"),
        },
        "value_status": cell.get("value_status"),
        "value_numeric": deepcopy(cell.get("value_numeric")),
        "value_text": deepcopy(cell.get("value_text")),
        "unavailable_reason": cell.get("unavailable_reason"),
        # Preserve T6/T5/T4/T3 source objects whole, rather than copying a
        # hand-picked provenance subset into Layer 3.
        "t6_row_lineage": deepcopy(row),
        "t6_cell_lineage": deepcopy(cell),
        "t5_definition": deepcopy(cell.get("definition")),
        "t5_binding": deepcopy(cell.get("binding")),
        "t5_value_lineage": deepcopy(cell.get("value_lineage")),
    }


def _can_auto_map(source: Mapping[str, Any]) -> bool:
    return bool(
        source.get("raw_concept_is_standard") is True
        and source.get("raw_concept_qname")
        and source.get("raw_concept_taxonomy_family")
        and source.get("raw_concept_data_type")
        and source.get("raw_concept_period_type")
        and source.get("source_filing_id")
        and _unit_scope(source) is not None
        # Cross-company automatic identity does not pretend company-specific
        # dimension members or axes carry equal scope.
        and not tuple(source.get("raw_dimension_signature") or ())
    )


def _automatic_standard_observation(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cik": source["cik"],
        "filing_id": source["source_filing_id"],
        "raw_concept_id": source.get("raw_concept_id") or source["raw_concept_qname"],
        "company_canonical_concept_id": source["company_canonical_id"],
        "qname": source["raw_concept_qname"],
        "taxonomy_family": source["raw_concept_taxonomy_family"],
        "data_type": source["raw_concept_data_type"],
        "period_type": source["raw_concept_period_type"],
        "is_standard": True,
        "measurement_scope": _unit_scope(source),
    }


def _qualified_automatic_observations(
    sources: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Pass only measurement-compatible standard groups to the mapper.

    ``CrossCompanyMapper`` is also used by the generic M8 mapping table.  The
    serving panel has the extra T6 measurement boundary, so it enforces it
    here rather than weakening that reusable mapping-table API.
    """
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for source in sources:
        if not _can_auto_map(source):
            continue
        key = (
            source["raw_concept_qname"],
            source["raw_concept_taxonomy_family"],
            source["raw_concept_data_type"],
            source["raw_concept_period_type"],
            _unit_scope(source),
        )
        grouped.setdefault(key, []).append(source)
    result: list[dict[str, Any]] = []
    for group in grouped.values():
        if len({source["cik"] for source in group}) >= 2:
            result.extend(_automatic_standard_observation(source) for source in group)
    return tuple(result)


def _unit_scope(source: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    numerator = source.get("unit_numerator_measures")
    denominator = source.get("unit_denominator_measures")
    if numerator is None and denominator is None:
        return None
    return (_measures(numerator), _measures(denominator))


def _measures(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(sorted(item for item in value.split() if item))
    return tuple(sorted(str(item) for item in value))


def _validate_reviewed_mappings(rows: tuple[dict[str, Any], ...]) -> None:
    allowed = {
        CrossCompanyRelation.SUBCATEGORY_OF.value,
        CrossCompanyRelation.SUPERSET_OF.value,
        CrossCompanyRelation.ANALYTICALLY_SIMILAR.value,
    }
    for row in rows:
        if str(row.get("relation") or "") not in allowed:
            raise CrossCompanyComparisonPanelError(
                "T8 reviewed mappings may only express subcategory, superset, or analytical similarity"
            )
        if not str(row.get("mapping_version") or "") or not isinstance(row.get("evidence"), Mapping):
            raise CrossCompanyComparisonPanelError("reviewed Layer 3 mapping requires evidence and version")
        if row.get("review_state") != "REVIEWED":
            raise CrossCompanyComparisonPanelError("reviewed Layer 3 mapping requires review_state REVIEWED")


def _comparison_key(source: Mapping[str, Any], mapping: Mapping[str, Any]) -> tuple[str, ...]:
    analytical_id = mapping.get("analytical_id")
    if analytical_id is not None:
        return ("MAPPED", str(analytical_id))
    return (
        "UNRESOLVED",
        str(source["cik"]),
        str(source["company_canonical_id"]),
        str(source["raw_concept_qname"]),
        str(source["t6_row_id"]),
    )


def _row(row_id: str, source: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "comparison_row_id": row_id,
        "analytical_id": mapping.get("analytical_id"),
        "mapping_relation": mapping["relation"],
        "mapping_confidence": mapping["confidence"],
        "mapping_method": mapping["method"],
        "mapping_evidence": deepcopy(mapping["evidence"]),
        "mapping_version": mapping["mapping_version"],
        "mapping_review_required": bool(mapping["review_required"]),
        "row_origin": "CROSS_COMPANY_MAPPING" if mapping.get("analytical_id") else "UNRESOLVED_SOURCE",
        "representative_raw_concept_qname": source["raw_concept_qname"],
    }


def _cell(row_id: str, source: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "comparison_row_id": row_id,
        "cik": source["cik"],
        "source_raw_id": source.get("raw_concept_id") or source["raw_concept_qname"],
        "raw_concept_qname": source["raw_concept_qname"],
        "company_canonical_id": source["company_canonical_id"],
        "analytical_id": mapping.get("analytical_id"),
        "mapping_relation": mapping["relation"],
        "mapping_confidence": mapping["confidence"],
        "mapping_method": mapping["method"],
        "mapping_evidence": deepcopy(mapping["evidence"]),
        "mapping_version": mapping["mapping_version"],
        "mapping_review_required": bool(mapping["review_required"]),
        "source_filing_id": source.get("source_filing_id"),
        "source_period": deepcopy(source["source_period"]),
        "value_status": source["value_status"],
        "value_numeric": deepcopy(source["value_numeric"]),
        "value_text": deepcopy(source["value_text"]),
        "unavailable_reason": source["unavailable_reason"],
        "t6_row_lineage": deepcopy(source["t6_row_lineage"]),
        "t6_cell_lineage": deepcopy(source["t6_cell_lineage"]),
        "t5_definition": deepcopy(source["t5_definition"]),
        "t5_binding": deepcopy(source["t5_binding"]),
        "t5_value_lineage": deepcopy(source["t5_value_lineage"]),
    }


def _unresolved(company_id: str) -> dict[str, Any]:
    return {
        "company_canonical_id": company_id,
        "analytical_id": None,
        "relation": CrossCompanyRelation.UNRESOLVED.value,
        "confidence": 0.0,
        "evidence": {"reason": "no_cross_company_mapping"},
        "method": "NO_CROSS_COMPANY_MAPPING",
        "mapping_version": CROSS_COMPANY_MAPPING_VERSION,
        "review_required": True,
    }


def _row_order(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row["analytical_id"] is None, str(row.get("analytical_id") or ""), row["comparison_row_id"])


def _stable_id(prefix: str, parts: tuple[str, ...]) -> str:
    import hashlib

    return f"cross-company:{prefix}:{hashlib.sha256(repr(parts).encode()).hexdigest()[:24]}"
