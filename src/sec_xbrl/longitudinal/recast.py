"""Evidence-governed comparable/recast observations.

Layer 1 deliberately has no opinion about a filing changing the basis of an
older period.  This module is the small Layer 2 boundary that binds a later
reported Fact to *reviewed, filing-local evidence* of that change.  It does
not scrape a narrative, mutate a raw snapshot, or infer a recast from a value
difference.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


class RecastObservationError(ValueError):
    """Raised when a proposed comparable/recast observation is not governed."""


RECAST_EVIDENCE_VERSION = "m9-recast-evidence-v1"


class RecastObservationBuilder:
    """Add recast provenance to already-materialized Layer 2 observations.

    ``observations`` normally come from :class:`SeriesBuilder`; therefore they
    already contain company canonical concept, complete canonical dimension
    key, unit, period class, target period, and raw Fact lineage.  ``evidence``
    is an analysis-layer review/extraction record.  An evidence row must bind a
    later raw Fact to an explicit re-presentation statement/table in that same
    later filing.  This explicit hand-off keeps narrative interpretation out of
    the immutable XBRL parser and makes it auditable.
    """

    def build(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        evidence: Iterable[Mapping[str, Any]] = (),
    ) -> tuple[dict[str, Any], ...]:
        rows = [deepcopy(dict(row)) for row in observations]
        by_fact = {
            _raw_fact_id(row): row for row in rows if _raw_fact_id(row)
        }
        evidence_rows = [_validated_evidence(row) for row in evidence]
        bound: dict[str, dict[str, Any]] = {}
        for item in evidence_rows:
            source_id = item["source_raw_fact_id"]
            source = by_fact.get(source_id)
            if source is None:
                raise RecastObservationError(
                    f"recast evidence {item['recast_evidence_id']} references unknown "
                    f"source raw Fact {source_id}"
                )
            if str(source.get("source_filing_id") or source.get("filing_id") or "") != item[
                "source_filing_id"
            ]:
                raise RecastObservationError("recast evidence source filing does not match source Fact")
            if _period_key(source) != item["target_period_key"]:
                raise RecastObservationError("recast evidence target period does not match source Fact")
            if item["source_filing_id"] in item["prior_source_filing_ids"]:
                raise RecastObservationError("recast evidence cannot cite its own filing as a prior filing")
            if source_id in bound:
                raise RecastObservationError("one raw Fact cannot be bound to two recast evidence records")
            bound[source_id] = item

        result: list[dict[str, Any]] = []
        for row in rows:
            source_id = _raw_fact_id(row)
            item = bound.get(source_id)
            if item is None:
                # This is a trust boundary.  Do not accept a caller-supplied
                # RECAST_REPORTED flag, basis, or evidence ID: an observation
                # becomes comparable only through the validated binding above.
                # It remains visible in AS_FILED but cannot enter
                # LATEST_RECAST on a guessed or unreviewed basis.
                result.append({
                    **row,
                    "source_raw_fact_id": source_id,
                    "source_type": "REPORTED",
                    "basis_version": None,
                    "recast_evidence_id": None,
                    "recast_evidence": None,
                    "recast_event_id": None,
                    "recast_prior_raw_fact_ids": (),
                })
                continue
            prior_rows = _matching_priors(row, rows, item)
            if not prior_rows:
                raise RecastObservationError(
                    "recast evidence has no earlier observation with the same company, canonical scope, "
                    "period, dimension, unit, and period class"
                )
            result.append({
                **row,
                "source_raw_fact_id": source_id,
                "source_type": "RECAST_REPORTED",
                "basis_version": item["basis_version"],
                "recast_evidence_id": item["recast_evidence_id"],
                "recast_evidence": item,
                "recast_event_id": _event_id(item),
                "recast_prior_raw_fact_ids": tuple(sorted(_raw_fact_id(prior) for prior in prior_rows)),
            })
        return tuple(sorted(result, key=lambda row: (_scope_key(row), _raw_fact_id(row))))


def _validated_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    row = deepcopy(dict(value))
    required = (
        "recast_evidence_id", "source_filing_id", "source_raw_fact_id", "target_period_key",
        "basis_version", "evidence_kind", "source_document", "source_locator",
        "explicitly_represented", "prior_source_filing_ids",
    )
    missing = [key for key in required if not row.get(key)]
    if missing:
        raise RecastObservationError("recast evidence missing: " + ", ".join(missing))
    if row["evidence_kind"] not in {"NARRATIVE_AND_TABLE", "NARRATIVE", "TABLE", "REVIEWED"}:
        raise RecastObservationError("unsupported recast evidence_kind")
    if row["explicitly_represented"] is not True:
        raise RecastObservationError("a numeric change alone is not recast evidence")
    prior_ids = tuple(str(item) for item in row["prior_source_filing_ids"] if item)
    if not prior_ids:
        raise RecastObservationError("recast evidence must identify earlier source filing(s)")
    row["prior_source_filing_ids"] = prior_ids
    row["evidence_version"] = RECAST_EVIDENCE_VERSION
    return row


def _matching_priors(
    source: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], evidence: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    source_filed = str(source.get("filed_date") or "")
    source_filing = str(source.get("source_filing_id") or source.get("filing_id") or "")
    candidates = []
    for row in rows:
        filing = str(row.get("source_filing_id") or row.get("filing_id") or "")
        if filing not in evidence["prior_source_filing_ids"]:
            continue
        if filing == source_filing or str(row.get("filed_date") or "") >= source_filed:
            continue
        if _scope_key(row) == _scope_key(source):
            candidates.append(row)
    return tuple(candidates)


def _scope_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("cik"),
        row.get("company_canonical_concept_id") or row.get("company_canonical_id"),
        _freeze(row.get("company_canonical_dimension_key")),
        row.get("unit_id"), row.get("period_class"), _period_key(row),
    )


def _period_key(row: Mapping[str, Any]) -> str:
    return str(row.get("period_key") or row.get("period_end") or row.get("report_period") or "")


def _raw_fact_id(row: Mapping[str, Any]) -> str:
    return str(row.get("source_raw_fact_id") or row.get("fact_id") or "")


def _event_id(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        [row["recast_evidence_id"], row["source_filing_id"], row["basis_version"]],
        separators=(",", ":"), sort_keys=True,
    ).encode()
    return "recast-event:" + hashlib.sha256(payload).hexdigest()[:24]


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value
