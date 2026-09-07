"""Declarative, diagnostic quarterly coverage checks for selected core concepts.

The checker is intentionally a consumer-side quality gate.  It does not claim
that every issuer must use every registry entry, and it never changes Layer 1
or Layer 2 selections.  Callers choose the applicable core definitions and
receive a complete per-concept/per-quarter diagnostic table.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CoverageStatus(StrEnum):
    REPORTED = "REPORTED"
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"
    MISSING = "MISSING"


class CoverageBasis(StrEnum):
    """Whether a cell represents a quarter-alone or fiscal-year-to-date value."""

    QUARTERLY = "QUARTERLY"
    CUMULATIVE = "CUMULATIVE"


@dataclass(frozen=True, slots=True)
class CoreConceptDefinition:
    """A standard-taxonomy concept family a caller may elect to validate."""

    key: str
    label: str
    us_gaap_local_names: tuple[str, ...]
    period_type: str
    required_period_class: str


# These are a compact default vocabulary for statement-core exploration, not a
# universal issuer mandate.  Revenue accepts the two common US-GAAP spellings.
CORE_CONCEPTS: tuple[CoreConceptDefinition, ...] = (
    CoreConceptDefinition("revenue", "Revenue", ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"), "duration", "QTD_3M"),
    CoreConceptDefinition("gross_profit", "Gross profit", ("GrossProfit",), "duration", "QTD_3M"),
    CoreConceptDefinition("operating_income_loss", "Operating income (loss)", ("OperatingIncomeLoss",), "duration", "QTD_3M"),
    CoreConceptDefinition("net_income_loss", "Net income (loss)", ("NetIncomeLoss",), "duration", "QTD_3M"),
    CoreConceptDefinition("assets", "Assets", ("Assets",), "instant", "INSTANT"),
    CoreConceptDefinition("liabilities", "Liabilities", ("Liabilities",), "instant", "INSTANT"),
    CoreConceptDefinition("stockholders_equity", "Stockholders' equity", ("StockholdersEquity",), "instant", "INSTANT"),
    CoreConceptDefinition("cash_and_cash_equivalents", "Cash and cash equivalents", ("CashAndCashEquivalentsAtCarryingValue",), "instant", "INSTANT"),
)
CORE_CONCEPTS_BY_KEY = {definition.key: definition for definition in CORE_CONCEPTS}
FLOW_CORE_CONCEPTS: tuple[CoreConceptDefinition, ...] = tuple(
    definition
    for definition in CORE_CONCEPTS
    if definition.period_type == "duration" and definition.required_period_class == "QTD_3M"
)


def core_canonical_concept_ids(
    company_concept_map: Iterable[Mapping[str, Any]],
    core_concepts: Iterable[CoreConceptDefinition] = CORE_CONCEPTS,
) -> frozenset[str]:
    """Return canonical IDs for a caller-selected standard common-core registry."""
    return frozenset().union(*_canonical_ids(tuple(core_concepts), company_concept_map).values())


@dataclass(frozen=True, slots=True)
class QuarterlyCoverageCell:
    cik: str
    concept_key: str
    fiscal_year: int
    fiscal_quarter: int
    coverage_basis: CoverageBasis
    required_period_class: str
    status: CoverageStatus
    company_canonical_concept_id: str | None
    source_id: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class QuarterlyCoverageResult:
    cells: tuple[QuarterlyCoverageCell, ...]

    @property
    def complete(self) -> bool:
        return all(cell.status in {CoverageStatus.REPORTED, CoverageStatus.DERIVED} for cell in self.cells)

    @property
    def missing(self) -> tuple[QuarterlyCoverageCell, ...]:
        return tuple(cell for cell in self.cells if cell.status == CoverageStatus.MISSING)

    @property
    def unavailable(self) -> tuple[QuarterlyCoverageCell, ...]:
        return tuple(cell for cell in self.cells if cell.status == CoverageStatus.UNAVAILABLE)

    def as_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "cik": cell.cik,
                "concept_key": cell.concept_key,
                "fiscal_year": cell.fiscal_year,
                "fiscal_quarter": cell.fiscal_quarter,
                "coverage_basis": cell.coverage_basis.value,
                "required_period_class": cell.required_period_class,
                "status": cell.status.value,
                "company_canonical_concept_id": cell.company_canonical_concept_id,
                "source_id": cell.source_id,
                "reason": cell.reason,
            }
            for cell in self.cells
        )


class CoreQuarterlyCoverageValidator:
    """Build a read-only core flow coverage matrix from governed observations.

    ``QUARTERLY`` cells require QTD_3M for every quarter.  ``CUMULATIVE``
    cells require QTD_3M, YTD_6M, YTD_9M, and FY for Q1 through Q4.  A
    mechanical derived fact may fill only a quarterly Q4 cell; it is never a
    substitute for the FY cumulative cell.
    """

    def validate(
        self,
        *,
        cik: str,
        analytical_facts: Iterable[Mapping[str, Any]],
        company_concept_map: Iterable[Mapping[str, Any]],
        fiscal_years: Iterable[int],
        core_concepts: Iterable[CoreConceptDefinition] = (CORE_CONCEPTS_BY_KEY["revenue"],),
        derived_facts: Iterable[Mapping[str, Any]] = (),
        coverage_bases: Iterable[CoverageBasis] = (CoverageBasis.QUARTERLY,),
    ) -> QuarterlyCoverageResult:
        definitions = tuple(core_concepts)
        years = tuple(sorted({int(year) for year in fiscal_years}))
        bases = tuple(dict.fromkeys(CoverageBasis(basis) for basis in coverage_bases))
        canonical_by_definition = _canonical_ids(definitions, company_concept_map)
        reported = _reported_by_cell(analytical_facts)
        derived = _derived_by_cell(derived_facts)
        cells: list[QuarterlyCoverageCell] = []
        for definition in definitions:
            canonical_ids = canonical_by_definition[definition.key]
            for year in years:
                for quarter in range(1, 5):
                    for basis in bases:
                        required_period_class = _required_period_class(definition, basis, quarter)
                        key = (year, quarter)
                        selected = _first_for_concepts(
                            reported.get(key, ()), canonical_ids, period_class=required_period_class
                        )
                        if selected is not None:
                            cells.append(_cell(
                                cik, definition, year, quarter, basis, required_period_class,
                                selected, CoverageStatus.REPORTED,
                            ))
                            continue
                        if basis == CoverageBasis.QUARTERLY and quarter == 4:
                            selected = _first_for_concepts(
                                derived.get(key, ()), canonical_ids, period_class=required_period_class
                            )
                            if selected is not None:
                                cells.append(_cell(
                                    cik, definition, year, quarter, basis, required_period_class,
                                    selected, CoverageStatus.DERIVED,
                                ))
                                continue
                        unavailable = _first_for_concepts(
                            reported.get(key, ()), canonical_ids,
                            unavailable=True, period_class=required_period_class,
                        )
                        cells.append(
                            _cell(
                                cik,
                                definition,
                                year,
                                quarter,
                                basis,
                                required_period_class,
                                unavailable,
                                CoverageStatus.UNAVAILABLE if unavailable else CoverageStatus.MISSING,
                            )
                        )
        return QuarterlyCoverageResult(tuple(cells))

    def validate_core_flow_completion(
        self,
        *,
        cik: str,
        analytical_facts: Iterable[Mapping[str, Any]],
        company_concept_map: Iterable[Mapping[str, Any]],
        fiscal_years: Iterable[int],
        derived_facts: Iterable[Mapping[str, Any]] = (),
    ) -> QuarterlyCoverageResult:
        """Validate the requested four GAAP flow anchors on both bases."""
        return self.validate(
            cik=cik,
            analytical_facts=analytical_facts,
            company_concept_map=company_concept_map,
            fiscal_years=fiscal_years,
            core_concepts=FLOW_CORE_CONCEPTS,
            derived_facts=derived_facts,
            coverage_bases=(CoverageBasis.QUARTERLY, CoverageBasis.CUMULATIVE),
        )


def _canonical_ids(
    definitions: Iterable[CoreConceptDefinition], mappings: Iterable[Mapping[str, Any]]
) -> dict[str, frozenset[str]]:
    rows = tuple(mappings)
    result: dict[str, frozenset[str]] = {}
    for definition in definitions:
        ids = {
            str(row.get("company_canonical_id"))
            for row in rows
            if row.get("entity_type") == "concept"
            and row.get("source_is_standard") is True
            and _is_us_gaap(row)
            and str(row.get("source_local_name") or _local_name(row.get("source_qname"))) in definition.us_gaap_local_names
            and _period_type_from_mapping(row) == definition.period_type
            and row.get("company_canonical_id")
        }
        result[definition.key] = frozenset(ids)
    return result


def _reported_by_cell(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[int, int], tuple[dict[str, Any], ...]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        if row.get("view") != "AS_FILED" or row.get("company_canonical_dimension_key") not in (None, (), []):
            continue
        key = _year_quarter(row)
        if key:
            grouped[key].append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _derived_by_cell(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[int, int], tuple[dict[str, Any], ...]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        if row.get("company_canonical_dimension_key") not in (None, (), []):
            continue
        key = _year_quarter(row)
        if key:
            grouped[key].append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _year_quarter(row: Mapping[str, Any]) -> tuple[int, int] | None:
    year = row.get("fiscal_year")
    quarter = row.get("fiscal_quarter")
    if year is not None and quarter is not None:
        return int(year), int(quarter)
    # M8 candidates carry the FY end period key rather than a redundant year.
    period = str(row.get("fiscal_year_end_period_key") or row.get("period_key") or "")
    if len(period) >= 4 and period[:4].isdigit():
        return int(period[:4]), 4 if row.get("reported_or_derived") == "DERIVED" else _quarter_from_period_class(row)
    return None


def _quarter_from_period_class(row: Mapping[str, Any]) -> int | None:
    quarter = row.get("fiscal_quarter")
    return int(quarter) if quarter is not None else None


def _first_for_concepts(
    rows: Iterable[Mapping[str, Any]], canonical_ids: frozenset[str], *, unavailable: bool = False,
    period_class: str,
) -> Mapping[str, Any] | None:
    for row in rows:
        if str(row.get("company_canonical_concept_id")) not in canonical_ids:
            continue
        is_unavailable = row.get("source_type") == "UNAVAILABLE"
        if row.get("period_class") == period_class and is_unavailable == unavailable:
            return row
    return None


def _required_period_class(
    definition: CoreConceptDefinition, basis: CoverageBasis, quarter: int,
) -> str:
    if basis == CoverageBasis.QUARTERLY:
        return definition.required_period_class
    if definition.period_type != "duration":
        raise ValueError("cumulative coverage is defined only for duration concepts")
    return {1: "QTD_3M", 2: "YTD_6M", 3: "YTD_9M", 4: "FY"}[quarter]


def _cell(
    cik: str, definition: CoreConceptDefinition, year: int, quarter: int,
    basis: CoverageBasis, required_period_class: str,
    source: Mapping[str, Any] | None, status: CoverageStatus,
) -> QuarterlyCoverageCell:
    source_id = None
    reason = None
    canonical_id = None
    if source:
        canonical_id = str(source.get("company_canonical_concept_id") or "") or None
        source_id = str(source.get("analytical_fact_id") or source.get("mechanical_q4_id") or "") or None
        reason = source.get("unavailable_reason")
    return QuarterlyCoverageCell(
        cik, definition.key, year, quarter, basis, required_period_class,
        status, canonical_id, source_id, reason,
    )


def _is_us_gaap(row: Mapping[str, Any]) -> bool:
    return str(row.get("source_taxonomy_family") or "").casefold() == "us-gaap" or "us-gaap" in str(row.get("source_namespace_uri") or "").casefold()


def _period_type_from_mapping(row: Mapping[str, Any]) -> str:
    evidence = row.get("evidence") or {}
    semantics = evidence.get("context_semantics") or {}
    return str(semantics.get("period_type") or "")


def _local_name(qname: object) -> str:
    return str(qname or "").rsplit(":", 1)[-1]
