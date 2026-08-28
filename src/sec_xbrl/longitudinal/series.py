"""L2-M3 durable company-internal series candidates.

This module deliberately stops before M4 selection.  A candidate is an
auditable input to selection, not an ``analytical_fact`` and not a consumer
view.  In particular, an unresolved map is retained as a separate,
review-required candidate; it is never used to join two reported observations.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

SERIES_RULE_VERSION = "l2-m3-company-series-v1"
_CONFIRMED_RELATIONS = frozenset({"SAME", "RENAMED", "RECAST"})


@dataclass(frozen=True, slots=True)
class CompanySeriesResult:
    """Publisher-ready M3 candidates and explicit compatibility exclusions."""

    annual: tuple[dict[str, Any], ...]
    current: tuple[dict[str, Any], ...]
    exclusions: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "annual_series_candidate": self.annual,
            "current_series_candidate": self.current,
            "series_candidate_exclusion": self.exclusions,
        }


class CompanySeriesMaterializer:
    """Materialize non-mutating Annual and Current candidates from L2 inputs.

    Mapping lookup is exact on ``(source_filing_id, source_raw_id)``.  This is
    important: the same extension local name in a later filing is not assumed
    equivalent merely because its spelling is identical.
    """

    def materialize(
        self,
        *,
        observations: Iterable[Mapping[str, Any]],
        mappings: Iterable[Mapping[str, Any]] | Any,
        declared_snapshot_ids: Iterable[str] | None = None,
        snapshot_id_by_filing_id: Mapping[str, str] | None = None,
    ) -> CompanySeriesResult:
        map_rows = _mapping_rows(mappings)
        maps = _maps_by_identity(map_rows)
        declared = (
            None
            if declared_snapshot_ids is None
            else {str(value) for value in declared_snapshot_ids}
        )
        annual: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        for source in observations:
            row = dict(source)
            reason = _source_compatibility_reason(row, declared, snapshot_id_by_filing_id)
            if reason:
                exclusions.append(_exclusion(row, reason))
                continue
            form = str(row.get("form") or "")
            period_class = str(row.get("period_class") or "")
            if form.startswith("10-K") and period_class == "FY":
                annual.append(_candidate(row, "ANNUAL", maps))
            if form.startswith(("10-K", "10-Q")):
                current.append(_candidate(row, "CURRENT", maps))
        return CompanySeriesResult(
            annual=tuple(sorted(annual, key=_candidate_sort_key)),
            current=tuple(sorted(current, key=_candidate_sort_key)),
            exclusions=tuple(
                sorted(exclusions, key=lambda row: str(row["series_candidate_exclusion_id"]))
            ),
        )


class MemberOrderingView:
    """Read-only, deterministic latest-QTD member ordering for a current view."""

    def build(self, candidates: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        latest: dict[tuple[Any, ...], dict[str, Any]] = {}
        for source in candidates:
            row = dict(source)
            if (
                row.get("series_type") != "CURRENT"
                or row.get("period_class") != "QTD_3M"
                or row.get("series_status") != "CANDIDATE"
            ):
                continue
            for axis, member, typed, dimension_type, default in row[
                "company_canonical_dimension_key"
            ]:
                if not member and typed is None:
                    continue
                other = tuple(
                    item for item in row["company_canonical_dimension_key"] if item[0] != axis
                )
                group = (
                    row["cik"],
                    row["company_canonical_concept_id"],
                    axis,
                    row["unit_semantics"],
                    other,
                )
                key = group + (member, typed, dimension_type, default)
                previous = latest.get(key)
                if previous is None or _latest_key(row) > _latest_key(previous):
                    latest[key] = row
        ordered: list[dict[str, Any]] = []
        groups: dict[tuple[Any, ...], list[tuple[tuple[Any, ...], dict[str, Any]]]] = defaultdict(
            list
        )
        for key, row in latest.items():
            groups[key[:5]].append((key, row))
        for group, members in sorted(groups.items(), key=repr):
            ranked = sorted(members, key=lambda item: _member_rank(item[0], item[1]))
            for ordinal, (key, row) in enumerate(ranked, 1):
                ordered.append(
                    {
                        "member_ordering_id": _id("member-ordering", *map(str, key)),
                        "cik": row["cik"],
                        "company_canonical_concept_id": row["company_canonical_concept_id"],
                        "axis_id": key[2],
                        "member_id": key[5],
                        "typed_member": key[6],
                        "dimension_type": key[7],
                        "is_default_member": key[8],
                        "unit_semantics": row["unit_semantics"],
                        "ordering_basis": "LATEST_VALID_QTD_VALUE_DESC",
                        "latest_period_key": row["actual_period_key"],
                        "latest_source_fact_id": row["source_fact_id"],
                        "latest_filing_id": row["source_filing_id"],
                        "latest_value_numeric": row.get("value_numeric"),
                        "display_order": ordinal,
                        "series_rule_version": SERIES_RULE_VERSION,
                    }
                )
        return tuple(ordered)


def _candidate(
    row: Mapping[str, Any], series_type: str, maps: Mapping[tuple[str, str, str], Mapping[str, Any]]
) -> dict[str, Any]:
    filing_id = str(row["source_filing_id"])
    concept, concept_review = _canonical(maps, filing_id, str(row["raw_concept_id"]), "concept")
    canonical_dimensions: list[tuple[str, str | None, str | None, str | None, bool | None]] = []
    review = concept_review
    for raw in row.get("dimension_signature") or ():
        axis_raw, member_raw, typed, dimension_type, default = tuple(raw)
        axis, axis_review = _canonical(maps, filing_id, str(axis_raw), "axis")
        member: str | None = None
        member_review = False
        if member_raw is not None:
            member, member_review = _canonical(maps, filing_id, str(member_raw), "member")
        canonical_dimensions.append(
            (axis, member, _none_or_str(typed), _none_or_str(dimension_type), default)
        )
        review = review or axis_review or member_review
    dimensions = tuple(sorted(canonical_dimensions, key=repr))
    boundaries = (
        _none_or_str(row.get("context_start_date")),
        _none_or_str(row.get("context_end_date")),
        _none_or_str(row.get("context_instant_date")),
    )
    unit = _unit_semantics(row)
    period_class = str(row["period_class"])
    identity = (str(row["cik"]), concept, dimensions, unit, boundaries, period_class, series_type)
    status = "REVIEW_REQUIRED" if review else "CANDIDATE"
    return {
        "series_candidate_id": _id(
            "series-candidate", str(row["period_observation_id"]), series_type, SERIES_RULE_VERSION
        ),
        "cik": str(row["cik"]),
        "series_type": series_type,
        "series_status": status,
        "unavailable_reason": "MAPPING_REVIEW_REQUIRED" if review else None,
        "company_canonical_concept_id": concept,
        "company_canonical_dimension_key": dimensions,
        "unit_semantics": unit,
        "unit_id": row.get("unit_id"),
        "actual_period_boundaries": boundaries,
        "actual_period_key": row.get("period_key"),
        "period_class": period_class,
        "series_key": identity,
        "series_family_key": (
            str(row["cik"]),
            concept,
            dimensions,
            unit,
            period_class,
            series_type,
        ),
        "source_period_observation_id": row["period_observation_id"],
        "source_fact_id": row["source_fact_id"],
        "source_fact_ids": row.get("source_fact_ids"),
        "source_filing_id": filing_id,
        "accession": row.get("accession"),
        "form": row.get("form"),
        "filed_date": row.get("filed_date"),
        "report_date": row.get("report_date"),
        "source_document": row.get("source_document"),
        "source_locator": row.get("source_locator"),
        "raw_concept_id": row.get("raw_concept_id"),
        "raw_dimension_signature": row.get("dimension_signature"),
        "value_numeric": row.get("value_numeric"),
        "value_text": row.get("value_text"),
        "reported_or_derived": row.get("reported_or_derived"),
        "formula": row.get("formula"),
        "derivation_rule_version": row.get("derivation_rule_version"),
        "mapping_version": _mapping_versions(maps, filing_id, row, review),
        "mapping_evidence": _mapping_evidence(maps, filing_id, row),
        "mapping_review_required": review,
        "classification_rule_version": row.get("classification_rule_version"),
        "series_rule_version": SERIES_RULE_VERSION,
    }


def _mapping_rows(mappings: Any) -> tuple[Mapping[str, Any], ...]:
    if hasattr(mappings, "company_concept_map"):
        return tuple(
            mappings.company_concept_map + mappings.company_axis_map + mappings.company_member_map
        )
    return tuple(mappings)


def _maps_by_identity(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("source_filing_id") or ""),
            str(row.get("source_raw_id") or ""),
            str(row.get("entity_type") or ""),
        )
        if key in result:
            raise ValueError(f"duplicate mapping identity: {key}")
        result[key] = row
    return result


def _canonical(
    maps: Mapping[tuple[str, str, str], Mapping[str, Any]], filing: str, raw: str, entity: str
) -> tuple[str, bool]:
    mapping = maps.get((filing, raw, entity))
    if mapping is None:
        return f"raw-unmapped:{filing}:{entity}:{raw}", True
    review = (
        bool(mapping.get("review_required"))
        or str(mapping.get("relation")) not in _CONFIRMED_RELATIONS
    )
    if review:
        return f"raw-review:{filing}:{entity}:{raw}", True
    return str(mapping["company_canonical_id"]), False


def _mapping_versions(
    maps: Mapping[tuple[str, str, str], Mapping[str, Any]],
    filing: str,
    row: Mapping[str, Any],
    review: bool,
) -> tuple[str, ...]:
    values = []
    for raw, entity in [(row.get("raw_concept_id"), "concept")]:
        item = maps.get((filing, str(raw), entity))
        if item:
            values.append(str(item.get("mapping_version")))
    for axis, member, *_ in row.get("dimension_signature") or ():
        for raw, entity in (
            (axis, "axis"),
            (member, "member") if member is not None else (None, ""),
        ):
            item = maps.get((filing, str(raw), entity)) if raw is not None else None
            if item:
                values.append(str(item.get("mapping_version")))
    return tuple(sorted(set(values))) if values else ("UNMAPPED",)


def _mapping_evidence(
    maps: Mapping[tuple[str, str, str], Mapping[str, Any]], filing: str, row: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    refs = (
        [(row.get("raw_concept_id"), "concept")]
        + [(axis, "axis") for axis, *_ in row.get("dimension_signature") or ()]
        + [
            (member, "member")
            for _, member, *_ in row.get("dimension_signature") or ()
            if member is not None
        ]
    )
    return tuple(
        sorted(
            (
                {
                    "entity_type": entity,
                    "raw_id": raw,
                    "mapping_id": item.get("mapping_id"),
                    "evidence": item.get("evidence"),
                }
                for raw, entity in refs
                if (item := maps.get((filing, str(raw), entity))) is not None
            ),
            key=_json,
        )
    )


def _source_compatibility_reason(
    row: Mapping[str, Any],
    declared: set[str] | None,
    snapshot_id_by_filing_id: Mapping[str, str] | None,
) -> str | None:
    required = (
        "period_observation_id",
        "cik",
        "source_filing_id",
        "form",
        "period_class",
        "raw_concept_id",
    )
    if any(not row.get(key) for key in required):
        return "MISSING_PERIOD_OBSERVATION_PROVENANCE"
    if row.get("reported_or_derived") == "DERIVED":
        if not row.get("source_fact_ids") or not row.get("derivation_rule_version") or not row.get("formula"):
            return "MISSING_DERIVED_SOURCE_LINEAGE"
    elif not row.get("source_fact_id"):
        return "MISSING_PERIOD_OBSERVATION_PROVENANCE"
    if declared is not None:
        snapshot_id = row.get("source_snapshot_id") or row.get("snapshot_id")
        if snapshot_id is None and snapshot_id_by_filing_id is not None:
            snapshot_id = snapshot_id_by_filing_id.get(str(row["source_filing_id"]))
        if snapshot_id is None:
            return "MISSING_SOURCE_SNAPSHOT_ID"
        if str(snapshot_id) not in declared:
            return "SOURCE_SNAPSHOT_NOT_DECLARED"
    if not row.get("context_end_date") and not row.get("context_instant_date"):
        return "MISSING_ACTUAL_PERIOD_BOUNDARY"
    return None


def _exclusion(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "series_candidate_exclusion_id": _id(
            "series-candidate-exclusion", str(row.get("period_observation_id")), reason
        ),
        "cik": row.get("cik"),
        "source_period_observation_id": row.get("period_observation_id"),
        "source_fact_id": row.get("source_fact_id"),
        "source_fact_ids": row.get("source_fact_ids"),
        "source_filing_id": row.get("source_filing_id"),
        "exclusion_reason": reason,
        "series_rule_version": SERIES_RULE_VERSION,
    }


def _unit_semantics(row: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        _measures(row.get("unit_numerator_measures")),
        _measures(row.get("unit_denominator_measures")),
    )


def _measures(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(sorted(str(item) for item in value))


def _latest_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(
            row.get("actual_period_boundaries", (None, None, None))[1]
            or row.get("actual_period_boundaries", (None, None, None))[2]
            or ""
        ),
        str(row.get("filed_date") or ""),
        str(row.get("source_fact_id") or ""),
    )


def _member_rank(key: tuple[Any, ...], row: Mapping[str, Any]) -> tuple[int, Decimal, str, str]:
    try:
        value = Decimal(str(row.get("value_numeric")))
    except (InvalidOperation, ValueError):
        return (1, Decimal(0), str(key[5] or ""), str(key[6] or ""))
    return (0, -value, str(key[5] or ""), str(key[6] or ""))


def _candidate_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (repr(row["series_key"]), str(row["series_candidate_id"]))


def _none_or_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _id(prefix: str, *parts: str) -> str:
    return (
        prefix
        + ":"
        + hashlib.sha256(
            json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()[:24]
    )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
