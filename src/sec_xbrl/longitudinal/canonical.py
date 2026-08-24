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

MAPPING_VERSION = "m7-company-canonical-v1"


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
        relationships_by_concept = _relationships_by_concept(relationships)
        changes = _changes_by_raw_id(documented_changes)
        rows = tuple(dict(row) for row in concepts)
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
                    method="NEW_RAW_ID",
                    confidence=1.0,
                    evidence={"raw_identity": raw_id},
                    mapping_version=MAPPING_VERSION,
                    continuity_break=False,
                    review_required=False,
                )
                events.append(_event(row, entity_type, "NEW_" + entity_type.upper()))
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
                            "SEGMENT_RECAST" if entity_type == "member" else "UNKNOWN_CHANGE",
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
            elif not (form.startswith("10-K") or form.startswith("10-Q")):
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
                    "series_type": series_type,
                    "company_canonical_concept_id": canonical_id,
                    "company_canonical_dimension_key": dimension_key,
                    "series_key": series_key,
                    "mapping_version": mapping["mapping_version"],
                    "mapping_confidence": mapping["confidence"],
                    "mapping_review_required": bool(mapping["review_required"] or dim_review),
                    "continuity_break": bool(mapping["continuity_break"]),
                }
            )
        return tuple(sorted(result, key=lambda row: (row["series_key"], str(row.get("fact_id")))))


AnnualSeries = SeriesBuilder
CurrentSeries = SeriesBuilder


def _best_candidate(
    row: Mapping[str, Any],
    established: Iterable[Mapping[str, Any]],
    relationships: Mapping[str, tuple[dict[str, Any], ...]],
    changes: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    raw_id = _raw_id(row)
    documented = changes.get(raw_id)
    if documented:
        prior = next(
            (
                item
                for item in established
                if _raw_id(item["source"]) == documented.get("prior_raw_id")
            ),
            None,
        )
        if prior:
            return prior["mapping"], {
                "confirmed": True,
                "relation": MappingRelation.RECAST,
                "method": "DOCUMENTED_RECAST",
                "confidence": 1.0,
                "evidence": {"documented_recast": dict(documented)},
                "continuity_break": True,
            }
    for item in reversed(tuple(established)):
        source = item["source"]
        if _exact_standard_identity(row, source):
            return item["mapping"], {
                "confirmed": True,
                "relation": MappingRelation.SAME,
                "method": "EXACT_STANDARD_TAXONOMY",
                "confidence": 1.0,
                "evidence": {"qname": row.get("qname"), "namespace_uri": row.get("namespace_uri")},
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
    values: set[str] = set(str(value) for value in row.get("axis_domain_role", ()) if value)
    for edge in relationships.get(_raw_id(row), ()):
        if edge.get("role_uri"):
            values.add("role:" + str(edge["role_uri"]))
        elif edge.get("role_id"):
            values.add("role:" + str(edge["role_id"]))
        if edge.get("network_type") == "DEF":
            values.add("def:" + str(edge.get("arcrole") or ""))
    return tuple(sorted(values))


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
        "company_canonical_id": canonical_id,
        "valid_from_filing_id": valid_from_filing_id,
        "valid_to_filing_id": None,
        "relation": relation.value,
        "method": method,
        "confidence": confidence,
        "evidence": dict(evidence),
        "mapping_version": mapping_version,
        "continuity_break": continuity_break,
        "review_required": review_required,
    }


def _event(row: Mapping[str, Any], entity_type: str, event_type: str) -> dict[str, Any]:
    return {
        "filing_id": row.get("filing_id"),
        "source_raw_id": _raw_id(row),
        "entity_type": entity_type,
        "event_type": event_type,
    }


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
