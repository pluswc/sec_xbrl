"""L2-M4 governed analytical-fact selection.

This module is deliberately the *only* L2 boundary that turns M3 candidates
into consumer-facing ``analytical_fact`` rows.  It retains both as-filed and
current-comparable views, and makes an unavailable result a first-class row
instead of borrowing a value from another reporting basis.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sec_xbrl.longitudinal.canonical import AsOfSeriesSelector
from sec_xbrl.longitudinal.recast import (
    RecastObservationBuilder,
    RecastObservationError,
    validate_recast_evidence,
)


SELECTION_MATERIALIZATION_VERSION = "l2-m4-as-of-recast-v1"


@dataclass(frozen=True, slots=True)
class AnalyticalFactSelectionResult:
    """Publisher-ready M4 outputs, still separate from immutable L1 inputs."""

    analytical_facts: tuple[dict[str, Any], ...]
    recast_evidence: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {"analytical_fact": self.analytical_facts, "recast_evidence": self.recast_evidence}


class AnalyticalFactMaterializer:
    """Select M3 candidates in immutable as-filed and comparable views.

    ``CURRENT_COMPARABLE`` is intentionally more conservative than the
    legacy selector's pre-recast baseline behavior: a basis can enter this
    durable consumer view only through reviewed recast evidence (or through
    an explicitly governed ``DERIVED_RECAST`` record).  This prevents a
    current view from silently treating a caller-supplied basis label as
    comparability evidence.
    """

    def materialize(
        self,
        *,
        annual_candidates: Iterable[Mapping[str, Any]] = (),
        current_candidates: Iterable[Mapping[str, Any]] = (),
        recast_evidence: Iterable[Mapping[str, Any]] = (),
        as_of_date: str,
    ) -> AnalyticalFactSelectionResult:
        candidates = tuple(_selection_candidate(row) for row in (*annual_candidates, *current_candidates))
        evidence = tuple(validate_recast_evidence(row) for row in recast_evidence)
        self._validate_candidates(candidates)
        cik_by_raw_fact = {
            str(row.get("source_raw_fact_id") or row.get("source_fact_id")): row.get("cik")
            for row in candidates
        }
        evidence = tuple(
            {
                **row,
                "cik": cik_by_raw_fact.get(str(row["source_raw_fact_id"])),
            }
            for row in evidence
        )
        if any(not row.get("cik") for row in evidence):
            raise RecastObservationError("recast evidence source raw Fact has no candidate CIK")
        bound = RecastObservationBuilder().build(candidates, evidence=evidence)

        as_filed = AsOfSeriesSelector().select(bound, as_of_date=as_of_date, view="AS_FILED")
        comparable_inputs = tuple(row for row in bound if _comparable_input(row))
        comparable = self._select_comparable(
            all_rows=bound, comparable_rows=comparable_inputs, as_of_date=as_of_date
        )
        facts = tuple(sorted(
            tuple(_analytical_fact(row, durable_view="AS_FILED") for row in as_filed)
            + tuple(_analytical_fact(row, durable_view="CURRENT_COMPARABLE") for row in comparable),
            key=lambda row: str(row["analytical_fact_id"]),
        ))
        return AnalyticalFactSelectionResult(
            analytical_facts=facts,
            recast_evidence=tuple(sorted(evidence, key=lambda row: (
                str(row["recast_evidence_id"]), str(row["source_raw_fact_id"])
            ))),
        )

    def _select_comparable(
        self,
        *,
        all_rows: tuple[dict[str, Any], ...],
        comparable_rows: tuple[dict[str, Any], ...],
        as_of_date: str,
    ) -> tuple[dict[str, Any], ...]:
        # We retain all target periods in the selector input so an incomplete
        # selected basis produces PERIOD_NOT_AVAILABLE... rather than omitting
        # history.  Non-evidence rows are made ineligible by clearing their
        # supplied basis at this trust boundary.
        eligible_ids = {str(row.get("source_raw_fact_id") or row.get("fact_id")) for row in comparable_rows}
        governed = []
        for row in all_rows:
            copied = dict(row)
            raw_id = str(copied.get("source_raw_fact_id") or copied.get("fact_id") or "")
            if raw_id not in eligible_ids:
                copied["basis_version"] = None
                if copied.get("source_type") != "RECAST_REPORTED":
                    copied["source_type"] = "REPORTED"
            governed.append(copied)
        selected = AsOfSeriesSelector().select(governed, as_of_date=as_of_date, view="LATEST_RECAST")
        review_periods = {
            _selection_scope(row): str(row["selection_unavailable_reason"])
            for row in all_rows
            if row.get("selection_unavailable_reason")
        }
        return tuple(
            {
                **row,
                "unavailable_reason": review_periods.get(_selection_scope(row), row.get("unavailable_reason")),
            }
            if row.get("source_type") == "UNAVAILABLE" and _selection_scope(row) in review_periods
            else row
            for row in selected
        )

    @staticmethod
    def _validate_candidates(candidates: Iterable[Mapping[str, Any]]) -> None:
        for row in candidates:
            required = ("cik", "series_type", "period_class", "actual_period_key", "source_filing_id", "filed_date")
            missing = [name for name in required if not row.get(name)]
            if missing:
                raise RecastObservationError("series candidate missing selection provenance: " + ", ".join(missing))
            if row.get("series_status") == "REVIEW_REQUIRED":
                # It is kept in AS_FILED only as an explicit unavailable row,
                # never selected as a canonical/current-comparable value.
                row["selection_unavailable_reason"] = "MAPPING_REVIEW_REQUIRED"


def _comparable_input(row: Mapping[str, Any]) -> bool:
    if row.get("selection_unavailable_reason"):
        return False
    source_type = str(row.get("source_type") or "")
    if source_type == "RECAST_REPORTED":
        return bool(row.get("basis_version") and row.get("recast_evidence_id"))
    if source_type == "DERIVED_RECAST":
        return bool(row.get("basis_version") and row.get("source_fact_ids") and row.get("derivation_rule_version"))
    return False


def _selection_candidate(source: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the M3 spelling without changing its source lineage."""
    row = dict(source)
    if not row.get("source_raw_fact_id") and row.get("source_fact_id"):
        row["source_raw_fact_id"] = row["source_fact_id"]
    if not row.get("period_key") and row.get("actual_period_key"):
        row["period_key"] = row["actual_period_key"]
    return row


def _selection_scope(row: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        row.get("cik"), row.get("series_type"), row.get("company_canonical_concept_id"),
        repr(row.get("company_canonical_dimension_key")), row.get("period_class"),
        row.get("fiscal_year"), row.get("period_key") or row.get("actual_period_key"),
    )


def _analytical_fact(row: Mapping[str, Any], *, durable_view: str) -> dict[str, Any]:
    unavailable = row.get("source_type") == "UNAVAILABLE" or row.get("selection_unavailable_reason")
    source_type = "UNAVAILABLE" if unavailable else str(row.get("source_type") or "REPORTED")
    reason = row.get("selection_unavailable_reason") or row.get("unavailable_reason")
    selected = None if unavailable else row.get("selected_raw_fact_id")
    period_key = str(row.get("period_key") or row.get("actual_period_key") or "")
    identity = (durable_view, row.get("as_of_date"), row.get("series_type"), row.get("cik"),
                row.get("company_canonical_concept_id"), row.get("company_canonical_dimension_key"),
                row.get("period_class"), period_key)
    return {
        "analytical_fact_id": _stable_id("analytical-fact", identity),
        "cik": row.get("cik"),
        "view": durable_view,
        "as_of_date": row.get("as_of_date"),
        "series_type": row.get("series_type"),
        "company_canonical_concept_id": row.get("company_canonical_concept_id"),
        "company_canonical_dimension_key": row.get("company_canonical_dimension_key"),
        "period_class": row.get("period_class"),
        "period_key": period_key,
        "basis_version": row.get("basis_version"),
        "source_type": source_type,
        "value_numeric": None if unavailable else row.get("value_numeric"),
        "value_text": None if unavailable else row.get("value_text"),
        "selected_fact_id": selected,
        "source_fact_ids": row.get("source_fact_ids"),
        "source_filing_id": None if unavailable else row.get("source_filing_id"),
        "filed_date": None if unavailable else row.get("filed_date"),
        "mapping_version": row.get("mapping_version"),
        "mapping_evidence": row.get("mapping_evidence"),
        "recast_evidence_id": row.get("recast_evidence_id"),
        "recast_event_id": row.get("recast_event_id"),
        "recast_prior_raw_fact_ids": row.get("recast_prior_raw_fact_ids"),
        "derivation_rule_version": row.get("derivation_rule_version"),
        "formula": row.get("formula"),
        "selection_rule_version": AsOfSeriesSelector.RULE_VERSION,
        "selection_materialization_version": SELECTION_MATERIALIZATION_VERSION,
        "unavailable_reason": reason if unavailable else None,
    }


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, default=repr, sort_keys=True, separators=(",", ":")).encode()
    return prefix + ":" + hashlib.sha256(encoded).hexdigest()[:24]
