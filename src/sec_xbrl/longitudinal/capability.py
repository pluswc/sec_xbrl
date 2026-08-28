"""L2-M5 evidence-governed company capability inventory.

The inventory is intentionally a discovery result, not a template of what a
company *ought* to disclose.  It only publishes concepts and dimensions seen
in supplied Layer 1/L2 evidence.  A request for a structure that was not seen
returns ``NOT_REPORTED`` at query time; it does not manufacture a Product,
Segment, or Geography row.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

CAPABILITY_INVENTORY_VERSION = "l2-m5-capability-inventory-v1"
_STATUSES = frozenset(
    {"AVAILABLE", "PROCESSING_UNAVAILABLE", "MAPPING_REVIEW_REQUIRED", "NOT_COMPARABLE"}
)


@dataclass(frozen=True, slots=True)
class CapabilityInventoryResult:
    """Publisher-ready, company-local capability rows."""

    inventory: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {"capability_inventory": self.inventory}


class CapabilityInventoryMaterializer:
    """Build discoverable capabilities from observed L1/L2 records only.

    ``series_candidates`` gives the observed company concepts/dimensions and
    their mapping state.  ``analytical_facts`` supplies governed comparability
    results.  ``processing_exclusions`` retains an input that was observed but
    could not be made analytical.  ``source_evidence_by_fact_id`` is optional
    enrichment from L1 statement/disclosure discovery; its role information is
    copied when present and never guessed from a label.
    """

    def materialize(
        self,
        *,
        company_ciks: Iterable[str],
        series_candidates: Iterable[Mapping[str, Any]] = (),
        analytical_facts: Iterable[Mapping[str, Any]] = (),
        processing_exclusions: Iterable[Mapping[str, Any]] = (),
        source_evidence_by_fact_id: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> CapabilityInventoryResult:
        companies = tuple(sorted({str(cik) for cik in company_ciks if str(cik)}))
        if not companies:
            raise ValueError("capability inventory requires at least one declared company CIK")
        evidence = {str(key): dict(value) for key, value in (source_evidence_by_fact_id or {}).items()}
        candidates = tuple(dict(row) for row in series_candidates)
        unknown = {str(row.get("cik")) for row in candidates if str(row.get("cik")) not in companies}
        if unknown:
            raise ValueError(f"series candidate CIK outside declared inventory: {sorted(unknown)}")
        facts_by_scope = _facts_by_scope(analytical_facts)
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            rows.extend(_candidate_rows(candidate, facts_by_scope, evidence.get(str(candidate.get("source_fact_id") or ""))))
        for excluded in processing_exclusions:
            row = dict(excluded)
            if str(row.get("cik")) not in companies:
                raise ValueError("processing exclusion CIK outside declared inventory")
            rows.append(_processing_row(row, evidence.get(str(row.get("source_fact_id") or ""))))
        # A coverage row is not a disclosure claim.  It makes an incomplete
        # company materialization visible without pretending that all omitted
        # concepts are NOT_REPORTED.
        seen = {str(row.get("cik")) for row in candidates}
        for cik in companies:
            if cik not in seen:
                rows.append(_coverage_unavailable(cik))
        return CapabilityInventoryResult(inventory=tuple(sorted(_deduplicate(rows), key=_sort_key)))


class CapabilityInventoryQuery:
    """Read-only discovery boundary over a materialized capability inventory."""

    def __init__(self, inventory: Iterable[Mapping[str, Any]]) -> None:
        rows = tuple(deepcopy(dict(row)) for row in inventory)
        invalid = [row for row in rows if str(row.get("capability_status")) not in _STATUSES]
        if invalid:
            raise ValueError("inventory contains an unsupported capability_status")
        self._rows = rows
        self._companies = {str(row["cik"]) for row in rows if row.get("cik")}

    def discover(
        self,
        *,
        cik: str,
        raw_concept_id: str | None = None,
        axis_raw_concept_id: str | None = None,
        member_raw_concept_id: str | None = None,
        period_class: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return only observed capabilities or one explicit non-report result."""
        company = str(cik)
        if company not in self._companies:
            raise LookupError(f"company has no capability inventory: {company}")
        matches = [
            row for row in self._rows
            if str(row["cik"]) == company
            and (raw_concept_id is None or row.get("raw_concept_id") == raw_concept_id)
            and (axis_raw_concept_id is None or row.get("axis_raw_concept_id") == axis_raw_concept_id)
            and (member_raw_concept_id is None or row.get("member_raw_concept_id") == member_raw_concept_id)
            and (period_class is None or period_class in row.get("period_classes", ()))
        ]
        if matches:
            return tuple(deepcopy(row) for row in sorted(matches, key=_sort_key))
        return ({
            "cik": company,
            "capability_type": "REQUEST",
            "capability_status": "NOT_REPORTED",
            "status_reason": "NO_OBSERVED_COMPANY_STRUCTURE_MATCHES_REQUEST",
            "requested_raw_concept_id": raw_concept_id,
            "requested_axis_raw_concept_id": axis_raw_concept_id,
            "requested_member_raw_concept_id": member_raw_concept_id,
            "requested_period_class": period_class,
            "capability_inventory_version": CAPABILITY_INVENTORY_VERSION,
        },)


def _candidate_rows(
    candidate: Mapping[str, Any], facts_by_scope: Mapping[tuple[Any, ...], tuple[Mapping[str, Any], ...]], evidence: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    dimensions = tuple(candidate.get("raw_dimension_signature") or ())
    scope = _scope(candidate)
    fact_rows = facts_by_scope.get(scope, ())
    common = _common(candidate, evidence, fact_rows)
    rows = [{**common, "capability_inventory_id": _id("capability", candidate.get("cik"), candidate.get("series_candidate_id"), "CONCEPT"),
             "capability_type": "CONCEPT", "axis_raw_concept_id": None,
             "member_raw_concept_id": None, "dimension_type": None}]
    for dimension in dimensions:
        axis, member, _typed, dimension_type, _default = tuple(dimension)
        rows.append({**common, "capability_inventory_id": _id("capability", candidate.get("cik"), candidate.get("series_candidate_id"), "DIMENSION_MEMBER", axis, member),
                     "capability_type": "DIMENSION_MEMBER", "axis_raw_concept_id": axis,
                     "member_raw_concept_id": member, "dimension_type": dimension_type})
    return rows


def _common(candidate: Mapping[str, Any], evidence: Mapping[str, Any] | None, facts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    status, reason = _candidate_status(candidate, facts)
    source_fact_id = candidate.get("source_fact_id")
    return {
        "capability_inventory_id": _id("capability", candidate.get("cik"), candidate.get("series_candidate_id"), status),
        "cik": str(candidate["cik"]),
        "capability_status": status,
        "status_reason": reason,
        "raw_concept_id": candidate.get("raw_concept_id"),
        "company_canonical_concept_id": candidate.get("company_canonical_concept_id"),
        "period_classes": (candidate.get("period_class"),),
        "series_types": (candidate.get("series_type"),),
        "mapping_version": candidate.get("mapping_version"),
        "selection_rule_version": _one_or_none(facts, "selection_rule_version"),
        "source_fact_ids": _distinct((source_fact_id, *(_source_values(facts, "selected_fact_id")))),
        "source_filing_ids": _distinct((candidate.get("source_filing_id"), *(_source_values(facts, "source_filing_id")))),
        "source_role_ids": _distinct(_evidence_values(evidence, "role_id", "source_role_ids")),
        "source_disclosure_ids": _distinct(_evidence_values(evidence, "disclosure_id", "source_disclosure_ids")),
        "source_locator": (evidence or {}).get("source_locator") or candidate.get("source_locator"),
        "source_document": (evidence or {}).get("source_document") or candidate.get("source_document"),
        "source_series_candidate_ids": (candidate.get("series_candidate_id"),),
        "capability_inventory_version": CAPABILITY_INVENTORY_VERSION,
    }


def _processing_row(row: Mapping[str, Any], evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "capability_inventory_id": _id("capability-processing", row.get("cik"), row.get("source_fact_id"), row.get("period_observation_exclusion_id")),
        "cik": str(row["cik"]), "capability_type": "CONCEPT", "capability_status": "PROCESSING_UNAVAILABLE",
        "status_reason": row.get("exclusion_reason") or "PROCESSING_UNAVAILABLE",
        "raw_concept_id": row.get("raw_concept_id"), "company_canonical_concept_id": None,
        "axis_raw_concept_id": None, "member_raw_concept_id": None, "dimension_type": None,
        "period_classes": (), "series_types": (), "mapping_version": None, "selection_rule_version": None,
        "source_fact_ids": _distinct((row.get("source_fact_id"),)), "source_filing_ids": _distinct((row.get("source_filing_id"),)),
        "source_role_ids": _distinct(_evidence_values(evidence, "role_id", "source_role_ids")),
        "source_disclosure_ids": _distinct(_evidence_values(evidence, "disclosure_id", "source_disclosure_ids")),
        "source_locator": (evidence or {}).get("source_locator"), "source_document": (evidence or {}).get("source_document"),
        "source_series_candidate_ids": (), "capability_inventory_version": CAPABILITY_INVENTORY_VERSION,
    }


def _coverage_unavailable(cik: str) -> dict[str, Any]:
    return {"capability_inventory_id": _id("capability-coverage", cik), "cik": cik,
            "capability_type": "COMPANY_COVERAGE", "capability_status": "PROCESSING_UNAVAILABLE",
            "status_reason": "NO_MATERIALIZED_L2_INPUT", "raw_concept_id": None,
            "company_canonical_concept_id": None, "axis_raw_concept_id": None, "member_raw_concept_id": None,
            "dimension_type": None, "period_classes": (), "series_types": (), "mapping_version": None,
            "selection_rule_version": None, "source_fact_ids": (), "source_filing_ids": (), "source_role_ids": (),
            "source_disclosure_ids": (), "source_locator": None, "source_document": None,
            "source_series_candidate_ids": (), "capability_inventory_version": CAPABILITY_INVENTORY_VERSION}


def _candidate_status(candidate: Mapping[str, Any], facts: Iterable[Mapping[str, Any]]) -> tuple[str, str | None]:
    if candidate.get("series_status") == "REVIEW_REQUIRED" or candidate.get("mapping_review_required"):
        return "MAPPING_REVIEW_REQUIRED", candidate.get("unavailable_reason") or "MAPPING_REVIEW_REQUIRED"
    unavailable = [row for row in facts if row.get("source_type") == "UNAVAILABLE"]
    if unavailable:
        return "NOT_COMPARABLE", str(unavailable[0].get("unavailable_reason") or "NOT_COMPARABLE")
    return "AVAILABLE", None


def _facts_by_scope(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[Any, ...], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        grouped[_scope(item)].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row.get("cik"), row.get("series_type"), row.get("company_canonical_concept_id"),
            repr(row.get("company_canonical_dimension_key")), row.get("period_class"),
            row.get("period_key") or row.get("actual_period_key"))


def _source_values(rows: Iterable[Mapping[str, Any]], key: str) -> tuple[Any, ...]:
    return tuple(row.get(key) for row in rows)


def _one_or_none(rows: Iterable[Mapping[str, Any]], key: str) -> str | None:
    values = _distinct(_source_values(rows, key))
    return values[0] if len(values) == 1 else None


def _evidence_values(evidence: Mapping[str, Any] | None, scalar: str, plural: str) -> tuple[Any, ...]:
    if not evidence:
        return ()
    return (evidence.get(scalar), *(evidence.get(plural) or ()))


def _distinct(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(sorted({value for value in values if value is not None and value != ""}, key=repr))


def _deduplicate(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        # Same candidate can enter Annual and Current; the series type remains
        # part of identity rather than silently merging incomparable periods.
        key = _id("capability-key", item.get("cik"), item.get("capability_type"), item.get("raw_concept_id"),
                  item.get("axis_raw_concept_id"), item.get("member_raw_concept_id"), item.get("period_classes"),
                  item.get("series_types"), item.get("source_fact_ids"), item.get("capability_status"))
        if key in result:
            continue
        result[key] = item
    return tuple(result.values())


def _sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (str(row.get("cik")), str(row.get("capability_type")), str(row.get("raw_concept_id")),
            str(row.get("axis_raw_concept_id")), str(row.get("member_raw_concept_id")))


def _id(prefix: str, *values: Any) -> str:
    payload = json.dumps(values, default=repr, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"
