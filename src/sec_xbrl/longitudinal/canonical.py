"""M7 additive, evidence-backed canonical mappings and company time series.

Layer 2 consumes copies of immutable Layer 1 records.  It never changes raw
identifiers or treats a label/string match as confirmation of identity.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

MAPPING_VERSION = "l2-m2-company-canonical-v1"


class MappingRelation(StrEnum):
    """Controlled relationship between an as-filed raw ID and company ID."""

    SAME = "SAME"
    RENAMED = "RENAMED"
    RECAST = "RECAST"
    SPLIT = "SPLIT"
    MERGED = "MERGED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class MappingTables:
    """Additive Layer 2 mapping rows, ready for independent materialization."""

    company_concept_map: tuple[dict[str, Any], ...]
    company_axis_map: tuple[dict[str, Any], ...]
    company_member_map: tuple[dict[str, Any], ...]
    structural_change: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        """Return the four publisher-ready L2-M2 logical datasets.

        This is deliberately an additive hand-off.  It does not publish data,
        choose an as-of view, or mutate a Layer 1 record.
        """
        return {
            "company_concept_map": self.company_concept_map,
            "company_axis_map": self.company_axis_map,
            "company_member_map": self.company_member_map,
            "structural_change": self.structural_change,
        }


class CompanyCanonicalizer:
    """Create conservative company-scoped IDs from ordered filing snapshots.

    Input concept/axis/member rows are the Layer 1 rows plus optional
    relationship evidence.  Rows must retain their ``filing_id``; a filing's
    order is supplied by the corresponding filing records.
    """

    def build(
        self,
        *,
        filings: Iterable[Mapping[str, Any]],
        concepts: Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]] = (),
        relationships: Iterable[Mapping[str, Any]] = (),
        documented_changes: Iterable[Mapping[str, Any]] = (),
    ) -> MappingTables:
        """Return new mapping rows; callers retain all supplied Layer 1 rows."""
        filing_rows = tuple(dict(row) for row in filings)
        cik = _single_cik(filing_rows)
        order = _filing_order(filing_rows)
        filing_by_id = {str(row["filing_id"]): row for row in filing_rows}
        relationships_by_concept = _relationships_by_concept(relationships)
        changes = _changes_by_raw_id(documented_changes)
        # Concepts are immutable Layer 1 records.  The copied analysis rows
        # receive filing validity only from their declared source filing.
        rows = tuple(
            {
                **dict(row),
                **{
                    key: filing_by_id.get(str(row.get("filing_id")), {}).get(key)
                    for key in ("report_date", "filed_date", "accession")
                    if not row.get(key)
                },
            }
            for row in concepts
        )
        dimension_rows = tuple(dimension_facts)
        axis_ids = {
            str(row["axis_raw_concept_id"])
            for row in dimension_rows
            if row.get("axis_raw_concept_id")
        }
        member_ids = {
            str(row["member_raw_concept_id"])
            for row in dimension_rows
            if row.get("member_raw_concept_id")
        }
        concept_rows = [row for row in rows if _entity_kind(row, axis_ids, member_ids) == "concept"]
        axis_rows = [row for row in rows if _entity_kind(row, axis_ids, member_ids) == "axis"]
        member_rows = [row for row in rows if _entity_kind(row, axis_ids, member_ids) == "member"]

        concept_map, concept_events = self._map_entity_rows(
            cik, "concept", concept_rows, order, relationships_by_concept, changes
        )
        axis_map, axis_events = self._map_entity_rows(
            cik, "axis", axis_rows, order, relationships_by_concept, changes
        )
        member_map, member_events = self._map_entity_rows(
            cik, "member", member_rows, order, relationships_by_concept, changes
        )
        return MappingTables(
            company_concept_map=tuple(concept_map),
            company_axis_map=tuple(axis_map),
            company_member_map=tuple(member_map),
            structural_change=tuple(concept_events + axis_events + member_events),
        )

    def segment_recast(
        self,
        *,
        cik: str,
        prior_member_map: Mapping[str, Any],
        recast_member: Mapping[str, Any],
        filing_id: str,
        evidence: Mapping[str, Any],
        mapping_version: str = MAPPING_VERSION,
    ) -> dict[str, Any]:
        """Append a continuity-breaking RECAST mapping without altering history.

        A recast is intentionally not an update of ``prior_member_map``.  The
        new row has a distinct canonical ID and a new mapping version, forcing
        consumers to choose whether a recast bridge is analytically suitable.
        """
        raw_id = _raw_id(recast_member)
        if not raw_id:
            raise ValueError("recast_member requires raw_concept_id")
        if not prior_member_map.get("company_canonical_id"):
            raise ValueError("prior_member_map requires company_canonical_id")
        return _mapping_row(
            cik=cik,
            entity_type="member",
            source=recast_member,
            canonical_id=_canonical_id(cik, "member", raw_id, f"recast:{filing_id}"),
            valid_from_filing_id=filing_id,
            relation=MappingRelation.RECAST,
            method="DOCUMENTED_SEGMENT_RECAST",
            confidence=1.0,
            evidence={
                "documented_recast": dict(evidence),
                "prior_company_canonical_id": str(prior_member_map["company_canonical_id"]),
            },
            mapping_version=_next_version(mapping_version, filing_id),
            continuity_break=True,
            review_required=False,
        )

    def _map_entity_rows(
        self,
        cik: str,
        entity_type: str,
        rows: list[dict[str, Any]],
        filing_order: Mapping[str, int],
        relationships: Mapping[str, tuple[dict[str, Any], ...]],
        changes: Mapping[str, Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        result: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        established: list[dict[str, Any]] = []
        for row in sorted(
            rows,
            key=lambda item: (filing_order.get(str(item.get("filing_id")), 10**9), _raw_id(item)),
        ):
            raw_id = _raw_id(row)
            if not raw_id:
                continue
            prior, decision = _best_candidate(row, established, relationships, changes)
            if prior is None:
                canonical_id = _canonical_id(cik, entity_type, raw_id)
                mapping = _mapping_row(
                    cik=cik,
                    entity_type=entity_type,
                    source=row,
                    canonical_id=canonical_id,
                    valid_from_filing_id=str(row.get("filing_id") or ""),
                    relation=MappingRelation.SAME,
                    method="RAW_IDENTITY_BASELINE",
                    confidence=1.0,
                    evidence={
                        "raw_identity": raw_id,
                        "qname": row.get("qname"),
                        "context_semantics": _context_semantics(row),
                        "structural_signature": _role_axis_signature(row, relationships),
                    },
                    mapping_version=MAPPING_VERSION,
                    continuity_break=False,
                    review_required=False,
                )
                events.append(
                    _event(
                        row,
                        entity_type,
                        "NEW_" + entity_type.upper(),
                        mapping=mapping,
                        evidence=mapping["evidence"],
                    )
                )
            else:
                canonical_id = (
                    _canonical_id(cik, entity_type, raw_id, f"recast:{row.get('filing_id')}")
                    if decision["continuity_break"]
                    else (
                        str(prior["company_canonical_id"])
                        if decision["confirmed"]
                        else _canonical_id(cik, entity_type, raw_id)
                    )
                )
                mapping = _mapping_row(
                    cik=cik,
                    entity_type=entity_type,
                    source=row,
                    canonical_id=canonical_id,
                    valid_from_filing_id=str(row.get("filing_id") or ""),
                    relation=decision["relation"],
                    method=decision["method"],
                    confidence=decision["confidence"],
                    evidence=decision["evidence"],
                    mapping_version=(
                        _next_version(MAPPING_VERSION, str(row.get("filing_id") or ""))
                        if decision["continuity_break"]
                        else MAPPING_VERSION
                    ),
                    continuity_break=decision["continuity_break"],
                    review_required=not decision["confirmed"],
                )
                if decision["continuity_break"]:
                    events.append(
                        _event(
                            row,
                            entity_type,
                            _event_type_for_relation(entity_type, decision["relation"]),
                            mapping=mapping,
                            evidence=decision["evidence"],
                        )
                    )
                elif decision["relation"] == MappingRelation.RENAMED and entity_type == "member":
                    events.append(
                        _event(
                            row,
                            entity_type,
                            "MEMBER_RENAME",
                            mapping=mapping,
                            evidence=decision["evidence"],
                        )
                    )
                elif decision["relation"] == MappingRelation.SAME and _role_restructured(
                    row, decision["evidence"], relationships
                ):
                    events.append(
                        _event(
                            row,
                            entity_type,
                            "ROLE_RESTRUCTURE",
                            mapping=mapping,
                            evidence={
                                **decision["evidence"],
                                "prior_role_signature": _role_axis_signature(prior, relationships),
                                "current_role_signature": _role_axis_signature(row, relationships),
                            },
                        )
                    )
                elif decision["relation"] == MappingRelation.UNCERTAIN:
                    events.append(
                        _event(
                            row,
                            entity_type,
                            "UNKNOWN_CHANGE",
                            mapping=mapping,
                            evidence=decision["evidence"],
                        )
                    )
            result.append(mapping)
            established.append({"source": row, "mapping": mapping})
        return result, events


class SeriesBuilder:
    """Build non-mutating Annual and Current company series from mapped facts."""

    def annual(
        self,
        *,
        filings: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        mappings: MappingTables | Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Return FY-focused observations from 10-K filings only."""
        return self._build("ANNUAL", filings, facts, mappings, dimension_facts)

    def current(
        self,
        *,
        filings: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        mappings: MappingTables | Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Return 10-K baseline and 10-Q updates, keyed by exact period class."""
        return self._build("CURRENT", filings, facts, mappings, dimension_facts)

    def _build(
        self,
        series_type: str,
        filings: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        mappings: MappingTables | Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        filing_by_id = {str(row["filing_id"]): dict(row) for row in filings}
        mapping_rows = _mapping_rows(mappings)
        concepts = {
            str(row["source_raw_id"]): row
            for row in mapping_rows
            if row["entity_type"] == "concept"
        }
        axes = {
            str(row["source_raw_id"]): row for row in mapping_rows if row["entity_type"] == "axis"
        }
        members = {
            str(row["source_raw_id"]): row for row in mapping_rows if row["entity_type"] == "member"
        }
        dimensions_by_fact: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for dimension in dimension_facts:
            dimensions_by_fact[str(dimension["fact_id"])].append(dimension)
        result: list[dict[str, Any]] = []
        for raw_fact in facts:
            fact = dict(raw_fact)
            filing = filing_by_id.get(str(fact.get("filing_id")))
            mapping = concepts.get(str(fact.get("raw_concept_id")))
            if filing is None or mapping is None:
                continue
            form = str(filing.get("form", ""))
            period_class = str(fact.get("period_class") or "OTHER_DURATION")
            if series_type == "ANNUAL":
                if not form.startswith("10-K") or period_class != "FY":
                    continue
            elif not form.startswith(("10-K", "10-Q")):
                continue
            dimension_key, dim_review = _dimension_key(
                dimensions_by_fact[str(fact.get("fact_id"))], axes, members
            )
            canonical_id = str(mapping["company_canonical_id"])
            cik = str(mapping["cik"])
            series_key = (
                cik,
                canonical_id,
                dimension_key,
                str(fact.get("unit_id") or ""),
                period_class,
            )
            result.append(
                {
                    **fact,
                    # These are analytical copies.  The raw Fact remains the
                    # source of truth, while a later selector can explain the
                    # exact filing/version it chose.
                    "source_raw_fact_id": str(fact.get("fact_id") or ""),
                    "source_filing_id": str(fact.get("filing_id") or ""),
                    "filed_date": filing.get("filed_date"),
                    "period_key": _period_key(fact),
                    "basis_version": fact.get("basis_version"),
                    "source_type": _source_type(fact),
                    "recast_evidence_id": fact.get("recast_evidence_id"),
                    "recast_evidence": fact.get("recast_evidence"),
                    "source_fact_ids": fact.get("source_fact_ids"),
                    "derivation_rule_version": fact.get("derivation_rule_version"),
                    "series_type": series_type,
                    "company_canonical_concept_id": canonical_id,
                    "company_canonical_dimension_key": dimension_key,
                    "series_key": series_key,
                    "mapping_version": mapping["mapping_version"],
                    "mapping_confidence": mapping["confidence"],
                    "mapping_evidence": dict(mapping["evidence"]),
                    "mapping_review_required": bool(mapping["review_required"] or dim_review),
                    "continuity_break": bool(mapping["continuity_break"]),
                }
            )
        return tuple(sorted(result, key=lambda row: (row["series_key"], str(row.get("fact_id")))))


AnnualSeries = SeriesBuilder
CurrentSeries = SeriesBuilder


class AsOfSeriesSelector:
    """Select governed ``AS_FILED`` or ``LATEST_RECAST`` observations.

    This is deliberately a selector, rather than a mutating canonicalizer.
    ``basis_version`` and recast evidence must be supplied by the analytical
    ingestion/review process; a changed number alone never establishes a
    recast.  Latest-recast selection chooses one basis for the whole period
    family and publishes an unavailable row for any period absent from it.
    """

    RULE_VERSION = "m7-as-of-selection-v1"
    _SOURCE_TYPES = frozenset({"REPORTED", "RECAST_REPORTED", "DERIVED_RECAST"})

    def select(
        self, observations: Iterable[Mapping[str, Any]], *, as_of_date: str, view: str
    ) -> tuple[dict[str, Any], ...]:
        if view not in {"AS_FILED", "LATEST_RECAST"}:
            raise ValueError("view must be AS_FILED or LATEST_RECAST")
        eligible = [
            dict(row)
            for row in observations
            if row.get("filed_date") and str(row["filed_date"]) <= as_of_date
        ]
        families: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            families[_family_key(row)].append(row)

        result: list[dict[str, Any]] = []
        for family_key in sorted(families, key=repr):
            rows = families[family_key]
            if view == "AS_FILED":
                result.extend(self._select_as_filed(rows, as_of_date))
            else:
                result.extend(self._select_latest_recast(rows, as_of_date))
        return tuple(sorted(result, key=_selection_sort_key))

    def _select_as_filed(
        self, rows: list[dict[str, Any]], as_of_date: str
    ) -> list[dict[str, Any]]:
        """Keep the first source-filed observation for each period unchanged."""
        result: list[dict[str, Any]] = []
        for candidates in _by_period(rows).values():
            # Original direct reporting is preferred.  If a period only first
            # appears as a later comparative/recast, retain that as-filed fact
            # rather than silently manufacturing an unavailable historical row.
            direct = [row for row in candidates if _source_type(row) == "REPORTED"]
            chosen = min(direct or candidates, key=_observation_order)
            result.append(_available(chosen, as_of_date, "AS_FILED"))
        return result

    def _select_latest_recast(
        self, rows: list[dict[str, Any]], as_of_date: str
    ) -> list[dict[str, Any]]:
        """Select one evidence-backed basis and never mix it across periods."""
        period_rows = _by_period(rows)
        valid = [row for row in rows if self._eligible_comparable(row)]
        if not valid:
            return [
                _unavailable(rows_for_period, as_of_date, "UNKNOWN_OR_UNSUPPORTED_BASIS_VERSION")
                for rows_for_period in period_rows.values()
            ]

        # A basis becomes selectable when its latest observation becomes
        # available.  This deterministic rule avoids looking into future
        # filings and chooses a later recast basis over an older baseline.
        by_basis: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in valid:
            by_basis[str(row["basis_version"])].append(row)
        selected_basis = max(
            by_basis,
            key=lambda basis: (
                max(_observation_order(row) for row in by_basis[basis]),
                basis,
            ),
        )
        result: list[dict[str, Any]] = []
        for candidates in period_rows.values():
            same_basis = [
                row for row in candidates if str(row.get("basis_version")) == selected_basis
                and self._eligible_comparable(row)
            ]
            if not same_basis:
                result.append(
                    _unavailable(
                        candidates,
                        as_of_date,
                        "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS",
                        basis_version=selected_basis,
                    )
                )
                continue
            chosen = max(same_basis, key=_observation_order)
            result.append(_available(chosen, as_of_date, "LATEST_RECAST"))
        return result

    def _eligible_comparable(self, row: Mapping[str, Any]) -> bool:
        source_type = _source_type(row)
        if source_type not in self._SOURCE_TYPES or not row.get("basis_version"):
            return False
        if source_type == "RECAST_REPORTED":
            return bool(row.get("recast_evidence_id") or row.get("recast_evidence"))
        if source_type == "DERIVED_RECAST":
            return bool(row.get("source_fact_ids") and row.get("derivation_rule_version"))
        return True


def _period_key(row: Mapping[str, Any]) -> str:
    """Return a durable target-period key without assuming calendar quarters."""
    explicit = row.get("period_key")
    if explicit:
        return str(explicit)
    for key in ("report_period", "period_end", "end_date", "instant_date"):
        if row.get(key):
            return str(row[key])
    return "fact:" + str(row.get("fact_id") or "")


def _family_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Key a comparable period family, excluding its individual period."""
    return (
        row.get("cik"),
        row.get("company_canonical_concept_id") or row.get("company_canonical_id"),
        _freeze(row.get("company_canonical_dimension_key")),
        row.get("unit_id"),
        row.get("period_class"),
        row.get("fiscal_year"),
        row.get("series_type"),
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def _by_period(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_period_key(row)].append(row)
    return dict(sorted(grouped.items()))


def _source_type(row: Mapping[str, Any]) -> str:
    return str(row.get("source_type") or row.get("reported_or_derived") or "REPORTED")


def _observation_order(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("filed_date") or ""),
        str(row.get("source_filing_id") or row.get("filing_id") or ""),
        str(row.get("source_raw_fact_id") or row.get("fact_id") or ""),
    )


def _available(row: Mapping[str, Any], as_of_date: str, view: str) -> dict[str, Any]:
    selected_fact_id = str(row.get("source_raw_fact_id") or row.get("fact_id") or "")
    return {
        **dict(row),
        "period_key": _period_key(row),
        "source_type": _source_type(row),
        "as_of_date": as_of_date,
        "view": view,
        "selection_rule_version": AsOfSeriesSelector.RULE_VERSION,
        "status": "AVAILABLE",
        "unavailable_reason": None,
        "selected_raw_fact_id": selected_fact_id,
    }


def _unavailable(
    candidates: Iterable[Mapping[str, Any]],
    as_of_date: str,
    reason: str,
    *,
    basis_version: str | None = None,
) -> dict[str, Any]:
    representative = min(candidates, key=_observation_order)
    return {
        "series_key": representative.get("series_key"),
        "series_type": representative.get("series_type"),
        "cik": representative.get("cik"),
        "company_canonical_concept_id": representative.get("company_canonical_concept_id"),
        "company_canonical_dimension_key": representative.get("company_canonical_dimension_key"),
        "unit_id": representative.get("unit_id"),
        "period_class": representative.get("period_class"),
        "fiscal_year": representative.get("fiscal_year"),
        "period_key": _period_key(representative),
        "as_of_date": as_of_date,
        "view": "LATEST_RECAST",
        "selection_rule_version": AsOfSeriesSelector.RULE_VERSION,
        "basis_version": basis_version,
        "source_type": "UNAVAILABLE",
        "status": "N/A",
        "unavailable_reason": reason,
        "selected_raw_fact_id": None,
        "mapping_version": representative.get("mapping_version"),
        "mapping_evidence": representative.get("mapping_evidence"),
    }


def _selection_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        repr(row.get("series_key")),
        str(row.get("fiscal_year") or ""),
        str(row.get("period_key") or ""),
        str(row.get("selected_raw_fact_id") or ""),
    )


def _best_candidate(
    row: Mapping[str, Any],
    established: Iterable[Mapping[str, Any]],
    relationships: Mapping[str, tuple[dict[str, Any], ...]],
    changes: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    raw_id = _raw_id(row)
    documented = changes.get(raw_id)
    if documented:
        relation = _documented_relation(documented)
        prior = next(
            (
                item
                for item in reversed(tuple(established))
                if _raw_id(item["source"]) in _documented_prior_raw_ids(documented)
            ),
            None,
        )
        if prior:
            return prior["mapping"], {
                "confirmed": True,
                "relation": relation,
                "method": "DOCUMENTED_" + relation.value,
                "confidence": 1.0,
                "evidence": {
                    "documented_change": dict(documented),
                    "prior_raw_ids": sorted(_documented_prior_raw_ids(documented)),
                    "context_semantics": _context_semantics(row),
                },
                "continuity_break": relation in {
                    MappingRelation.RECAST,
                    MappingRelation.SPLIT,
                    MappingRelation.MERGED,
                },
            }
    for item in reversed(tuple(established)):
        source = item["source"]
        if _exact_standard_identity(row, source):
            return item["mapping"], {
                "confirmed": True,
                "relation": MappingRelation.SAME,
                "method": "EXACT_STANDARD_TAXONOMY",
                "confidence": 1.0,
                "evidence": {
                    "qname": row.get("qname"),
                    "namespace_uri": row.get("namespace_uri"),
                    "prior_raw_id": _raw_id(source),
                    "context_semantics": _context_semantics(row),
                    "prior_context_semantics": _context_semantics(source),
                },
                "continuity_break": False,
            }
    for item in reversed(tuple(established)):
        source = item["source"]
        if _well_supported_namespace_change(row, source, relationships):
            return item["mapping"], {
                "confirmed": True,
                "relation": MappingRelation.RENAMED,
                "method": "LOCAL_AXIS_ROLE_LABEL_CONTINUITY",
                "confidence": 0.9,
                "evidence": _continuity_evidence(row, source, relationships),
                "continuity_break": False,
            }
    for item in reversed(tuple(established)):
        source = item["source"]
        if _same_text(row, source):
            return item["mapping"], {
                "confirmed": False,
                "relation": MappingRelation.UNCERTAIN,
                "method": "STRING_SIMILARITY_ONLY",
                "confidence": 0.35,
                "evidence": {"label_or_local_name": _label_or_name(row)},
                "continuity_break": False,
            }
    return None, {"confirmed": False}


def _entity_kind(
    row: Mapping[str, Any], axis_ids: set[str] | None = None, member_ids: set[str] | None = None
) -> str:
    explicit = str(row.get("entity_type") or "").lower()
    if explicit in {"concept", "axis", "member"}:
        return explicit
    raw_id = _raw_id(row)
    if member_ids is not None and raw_id in member_ids:
        return "member"
    if axis_ids is not None and raw_id in axis_ids:
        return "axis"
    if row.get("is_axis") is True:
        return "axis"
    if row.get("is_member") is True:
        return "member"
    return "concept"


def _exact_standard_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        bool(left.get("is_standard"))
        and bool(right.get("is_standard"))
        and left.get("qname") == right.get("qname")
        and left.get("namespace_uri") == right.get("namespace_uri")
    )


def _well_supported_namespace_change(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    relationships: Mapping[str, tuple[dict[str, Any], ...]],
) -> bool:
    if left.get("namespace_uri") == right.get("namespace_uri") or left.get(
        "local_name"
    ) != right.get("local_name"):
        return False
    if _label_or_name(left) != _label_or_name(right):
        return False
    # The same local/label is insufficient.  Require compatible axis/domain and
    # role evidence supplied by Layer 1 DEF/PRE/CAL relationships.
    return _role_axis_signature(left, relationships) == _role_axis_signature(
        right, relationships
    ) and bool(_role_axis_signature(left, relationships))


def _role_axis_signature(
    row: Mapping[str, Any], relationships: Mapping[str, tuple[dict[str, Any], ...]]
) -> tuple[str, ...]:
    values: set[str] = {str(value) for value in row.get("axis_domain_role", ()) if value}
    for edge in relationships.get(_raw_id(row), ()):
        if edge.get("role_uri"):
            values.add("role:" + str(edge["role_uri"]))
        elif edge.get("role_id"):
            values.add("role:" + str(edge["role_id"]))
        if edge.get("network_type") == "DEF":
            values.add("def:" + str(edge.get("arcrole") or ""))
    return tuple(sorted(values))


def _role_restructured(
    row: Mapping[str, Any],
    evidence: Mapping[str, Any],
    relationships: Mapping[str, tuple[dict[str, Any], ...]],
) -> bool:
    """Record an observed network move without treating it as an ID change."""
    prior_signature: tuple[str, ...] = ()
    # Exact standard identity stores the former raw ID in its evidence.  A
    # structural event is relevant only when both filings expose signatures.
    prior_raw_id = evidence.get("prior_raw_id")
    if not prior_raw_id:
        return False
    prior_signature = _role_axis_signature(
        {"raw_concept_id": prior_raw_id}, relationships
    )
    current_signature = _role_axis_signature(row, relationships)
    return bool(prior_signature and current_signature and prior_signature != current_signature)


def _continuity_evidence(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    relationships: Mapping[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    return {
        "local_name": left.get("local_name"),
        "label": left.get("label"),
        "prior_raw_id": _raw_id(right),
        "axis_domain_role_signature": _role_axis_signature(left, relationships),
        "context_semantics": _context_semantics(left),
        "prior_context_semantics": _context_semantics(right),
    }


def _same_text(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    value = _label_or_name(left)
    return bool(value) and value == _label_or_name(right)


def _label_or_name(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get("label") or row.get("local_name") or "").casefold().split())


def _relationships_by_concept(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        copy = dict(row)
        for key in ("from_raw_concept_id", "to_raw_concept_id"):
            if copy.get(key):
                grouped[str(copy[key])].append(copy)
    return {key: tuple(value) for key, value in grouped.items()}


def _changes_by_raw_id(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row["source_raw_id"]): row for row in rows if row.get("source_raw_id")}


def _mapping_row(
    *,
    cik: str,
    entity_type: str,
    source: Mapping[str, Any],
    canonical_id: str,
    valid_from_filing_id: str,
    relation: MappingRelation,
    method: str,
    confidence: float,
    evidence: Mapping[str, Any],
    mapping_version: str,
    continuity_break: bool,
    review_required: bool,
) -> dict[str, Any]:
    raw_id = _raw_id(source)
    return {
        "mapping_id": _stable_mapping_id(cik, entity_type, raw_id, canonical_id, mapping_version),
        "cik": cik,
        "entity_type": entity_type,
        "source_raw_id": raw_id,
        "source_raw_concept_id": raw_id,
        "source_filing_id": str(source.get("filing_id") or ""),
        "source_qname": source.get("qname"),
        "source_namespace_uri": source.get("namespace_uri"),
        "source_local_name": source.get("local_name"),
        "company_canonical_id": canonical_id,
        "canonical_entity_type": entity_type,
        "valid_from_filing_id": valid_from_filing_id,
        "valid_to_filing_id": None,
        "valid_from_period": _validity_period(source),
        "valid_to_period": None,
        "relation": relation.value,
        "method": method,
        "confidence": confidence,
        "evidence": dict(evidence),
        "mapping_version": mapping_version,
        "continuity_break": continuity_break,
        "review_required": review_required,
        "review_state": "REVIEW_REQUIRED" if review_required else "AUTO_ACCEPTED",
    }


def _event(
    row: Mapping[str, Any],
    entity_type: str,
    event_type: str,
    *,
    mapping: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": "structural-change:"
        + _digest(str(row.get("filing_id") or ""), _raw_id(row), event_type, mapping["mapping_id"]),
        "cik": mapping["cik"],
        "filing_id": row.get("filing_id"),
        "source_raw_id": _raw_id(row),
        "source_raw_concept_id": _raw_id(row),
        "company_canonical_id": mapping["company_canonical_id"],
        "entity_type": entity_type,
        "event_type": event_type,
        "valid_from_filing_id": mapping["valid_from_filing_id"],
        "valid_from_period": mapping["valid_from_period"],
        "mapping_version": mapping["mapping_version"],
        "continuity_break": mapping["continuity_break"],
        "review_required": mapping["review_required"],
        "evidence": dict(evidence),
    }


def _context_semantics(row: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only declared raw semantic fields; never infer from values."""
    return {
        key: row.get(key)
        for key in ("period_type", "data_type", "balance", "abstract")
        if row.get(key) is not None
    }


def _validity_period(row: Mapping[str, Any]) -> str | None:
    for key in ("report_date", "period_end", "end_date", "instant_date"):
        if row.get(key):
            return str(row[key])
    return None


def _documented_prior_raw_ids(change: Mapping[str, Any]) -> set[str]:
    values = {str(change["prior_raw_id"])} if change.get("prior_raw_id") else set()
    values.update(str(value) for value in change.get("prior_raw_ids", ()) if value)
    return values


def _documented_relation(change: Mapping[str, Any]) -> MappingRelation:
    value = str(change.get("relation") or "RECAST").upper()
    try:
        return MappingRelation(value)
    except ValueError as exc:
        raise ValueError(f"unsupported documented mapping relation: {value!r}") from exc


def _event_type_for_relation(entity_type: str, relation: MappingRelation) -> str:
    if relation == MappingRelation.RECAST:
        return "SEGMENT_RECAST" if entity_type == "member" else "UNKNOWN_CHANGE"
    if relation == MappingRelation.SPLIT:
        return "SPLIT"
    if relation == MappingRelation.MERGED:
        return "MERGE"
    return "UNKNOWN_CHANGE"


def _mapping_rows(
    mappings: MappingTables | Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(mappings, MappingTables):
        return (
            mappings.company_concept_map + mappings.company_axis_map + mappings.company_member_map
        )
    return tuple(mappings)


def _dimension_key(
    rows: Iterable[Mapping[str, Any]],
    axes: Mapping[str, Mapping[str, Any]],
    members: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[tuple[str, str, str | None], ...], bool]:
    result: list[tuple[str, str, str | None]] = []
    review = False
    for row in rows:
        axis = axes.get(str(row.get("axis_raw_concept_id")))
        member = (
            members.get(str(row.get("member_raw_concept_id")))
            if row.get("member_raw_concept_id")
            else None
        )
        if axis is None or (row.get("member_raw_concept_id") and member is None):
            review = True
        axis_id = (
            str(axis.get("company_canonical_id"))
            if axis
            else str(row.get("axis_raw_concept_id") or "")
        )
        member_id = (
            str(member.get("company_canonical_id"))
            if member
            else str(row.get("member_raw_concept_id") or "")
        )
        typed = str(row.get("typed_member")) if row.get("typed_member") is not None else None
        review = (
            review
            or bool((axis or {}).get("review_required"))
            or bool((member or {}).get("review_required"))
        )
        result.append((axis_id, member_id, typed))
    return tuple(sorted(result)), review


def _single_cik(filings: Iterable[Mapping[str, Any]]) -> str:
    ciks = {str(row.get("cik")) for row in filings if row.get("cik") is not None}
    if len(ciks) != 1:
        raise ValueError("Layer 2 mappings require exactly one company CIK")
    return next(iter(ciks))


def _filing_order(filings: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    ordered = sorted(
        filings,
        key=lambda row: (
            str(row.get("filed_date") or ""),
            str(row.get("accession") or ""),
            str(row.get("filing_id") or ""),
        ),
    )
    return {str(row["filing_id"]): index for index, row in enumerate(ordered)}


def _raw_id(row: Mapping[str, Any]) -> str:
    return str(row.get("raw_concept_id") or row.get("source_raw_id") or "")


def _canonical_id(cik: str, entity_type: str, raw_id: str, discriminator: str = "") -> str:
    return "company:" + cik + ":" + entity_type + ":" + _digest(raw_id, discriminator)


def _stable_mapping_id(
    cik: str, entity_type: str, raw_id: str, canonical_id: str, version: str
) -> str:
    return "company-map:" + _digest(cik, entity_type, raw_id, canonical_id, version)


def _next_version(version: str, filing_id: str) -> str:
    return version + ":recast:" + _digest(filing_id)[:12]


def _digest(*parts: str) -> str:
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()[:24]
