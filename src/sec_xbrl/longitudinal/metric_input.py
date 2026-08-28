"""L2-M6 governed input handoff for the separate Derived Metrics plane.

This module deliberately assesses inputs only.  It never calculates a ratio,
growth rate, Q4 flow, or writes a ``derived_metric`` row.  A later metrics
plane must consume the published candidates and diagnostics and retain its own
formula/version lineage.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

METRIC_INPUT_HANDOFF_VERSION = "l2-m6-metric-input-handoff-v1"

_ROLE_BY_STANDARD_LOCAL_NAME = {
    "revenuefromcontractwithcustomerexcludingassessedtax": "REVENUE",
    "salesrevenuenet": "REVENUE",
    "revenues": "REVENUE",
    "revenue": "REVENUE",
    "grossprofit": "GROSS_PROFIT",
    "operatingincomeloss": "OPERATING_INCOME",
    "earningspersharebasic": "EPS",
    "earningspersharediluted": "EPS",
    "weightedaveragenumberofsharesoutstandingbasic": "WEIGHTED_AVERAGE_SHARES",
    "weightedaveragenumberofdilutedsharesoutstanding": "WEIGHTED_AVERAGE_SHARES",
}
_ASSESSMENTS = frozenset({"GROSS_MARGIN", "OPERATING_MARGIN", "REVENUE_GROWTH", "Q4_FLOW"})


@dataclass(frozen=True, slots=True)
class MetricInputHandoffResult:
    """Publisher-ready metric input records, with no calculated metric value."""

    candidates: tuple[dict[str, Any], ...]
    compatibility: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "metric_input_candidate": self.candidates,
            "metric_input_compatibility": self.compatibility,
        }


class MetricInputHandoffMaterializer:
    """Assess selected analytical facts as safe Metric-plane inputs.

    ``metric_input_role`` is accepted only when it is explicit upstream
    metadata.  Otherwise roles are recognised from QName-aware standard
    concept identity (not labels).  Company extension concepts therefore need
    an explicit role assignment from a governed future definition/mapping;
    they are not guessed from their display text.
    """

    def materialize(
        self,
        *,
        analytical_facts: Iterable[Mapping[str, Any]],
        metric_definition_ids: Mapping[str, str] | None = None,
    ) -> MetricInputHandoffResult:
        definitions = {str(key): str(value) for key, value in (metric_definition_ids or {}).items()}
        facts = tuple(_normalized_fact(row) for row in analytical_facts)
        _validate_inputs(facts)
        candidates = tuple(
            sorted(
                (_candidate(row) for row in facts if row["metric_input_role"]), key=_candidate_sort
            )
        )
        compatibility = _diagnostics(facts, definitions)
        return MetricInputHandoffResult(
            candidates=candidates, compatibility=tuple(sorted(compatibility, key=_diagnostic_sort))
        )


def _normalized_fact(source: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(source)
    explicit_role = row.get("metric_input_role")
    role = str(explicit_role) if explicit_role else _standard_role(row.get("raw_concept_id"))
    row["metric_input_role"] = role
    row.setdefault("company_canonical_dimension_key", ())
    row.setdefault("source_fact_ids", ())
    return row


def _standard_role(raw_concept_id: object) -> str | None:
    if not raw_concept_id:
        return None
    # QName-aware identity is retained upstream.  This parser only recognises
    # named standard concepts; it never uses a label or fuzzy company name.
    local_name = str(raw_concept_id).rsplit("}", 1)[-1].rsplit(":", 1)[-1]
    return _ROLE_BY_STANDARD_LOCAL_NAME.get(
        "".join(char.lower() for char in local_name if char.isalnum())
    )


def _validate_inputs(rows: Iterable[Mapping[str, Any]]) -> None:
    required = (
        "analytical_fact_id",
        "cik",
        "view",
        "as_of_date",
        "period_class",
        "period_key",
        "mapping_version",
    )
    for row in rows:
        missing = [field for field in required if row.get(field) in {None, ""}]
        if missing:
            raise ValueError(
                "metric input requires selected analytical-fact provenance: " + ", ".join(missing)
            )
        if row.get("view") not in {"AS_FILED", "CURRENT_COMPARABLE"}:
            raise ValueError("metric input has unsupported analytical-fact view")
        if row.get("source_type") == "UNAVAILABLE" and not row.get("unavailable_reason"):
            raise ValueError("unavailable metric input must retain unavailable_reason")


def _candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    role = str(row["metric_input_role"])
    direct = role in {"EPS", "WEIGHTED_AVERAGE_SHARES"}
    direct_reported = _is_direct_reported_observation(row) if direct else False
    unavailable = row.get("source_type") == "UNAVAILABLE" or (direct and not direct_reported)
    status = (
        "UNAVAILABLE" if unavailable else ("DIRECT_OBSERVATION_ONLY" if direct else "CANDIDATE")
    )
    reason = (
        "DIRECT_OBSERVATION_REQUIRED"
        if direct and not direct_reported
        else row.get("unavailable_reason")
        if unavailable
        else "DIRECT_OBSERVATION_NO_REVERSE_ENGINEERING"
        if direct
        else None
    )
    identity = (row.get("analytical_fact_id"), role)
    return {
        "metric_input_candidate_id": _id("metric-input", identity),
        "cik": row.get("cik"),
        "metric_input_role": role,
        "analytical_fact_id": row.get("analytical_fact_id"),
        "selected_fact_id": row.get("selected_fact_id"),
        "source_fact_ids": tuple(row.get("source_fact_ids") or ()),
        "source_filing_id": row.get("source_filing_id"),
        "view": row.get("view"),
        "as_of_date": row.get("as_of_date"),
        "basis_version": row.get("basis_version"),
        "series_type": row.get("series_type"),
        "period_class": row.get("period_class"),
        "period_key": row.get("period_key"),
        "company_canonical_dimension_key": row.get("company_canonical_dimension_key"),
        "unit_semantics": row.get("unit_semantics") or row.get("unit_id"),
        "mapping_version": row.get("mapping_version"),
        "source_type": row.get("source_type"),
        "candidate_status": status,
        "unavailable_reason": reason,
        "source_selection_unavailable_reason": row.get("unavailable_reason"),
        "metric_input_handoff_version": METRIC_INPUT_HANDOFF_VERSION,
    }


def _is_direct_reported_observation(row: Mapping[str, Any]) -> bool:
    """EPS/shares must retain one reported raw Fact, never a subtraction result."""
    source_type = row.get("source_type")
    if not row.get("selected_fact_id"):
        return False
    if source_type == "REPORTED":
        return True
    return source_type == "RECAST_REPORTED" and bool(row.get("recast_evidence_id"))


def _diagnostics(
    rows: tuple[dict[str, Any], ...], definitions: Mapping[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    growth_grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["metric_input_role"]:
            grouped[_base_scope(row)].append(row)
            growth_grouped[_growth_scope(row)].append(row)
    for facts in grouped.values():
        out.append(
            _pair_diagnostic(
                "GROSS_MARGIN", facts, definitions.get("GROSS_MARGIN"), ("GROSS_PROFIT", "REVENUE")
            )
        )
        out.append(
            _pair_diagnostic(
                "OPERATING_MARGIN",
                facts,
                definitions.get("OPERATING_MARGIN"),
                ("OPERATING_INCOME", "REVENUE"),
            )
        )
        out.extend(_q4_diagnostics(facts, definitions.get("Q4_FLOW")))
    for facts in growth_grouped.values():
        out.extend(_growth_diagnostics(facts, definitions.get("REVENUE_GROWTH")))
    return out


def _base_scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("cik"),
        row.get("view"),
        row.get("as_of_date"),
        row.get("series_type"),
        row.get("period_class"),
        row.get("period_key"),
    )


def _growth_scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("cik"),
        row.get("view"),
        row.get("as_of_date"),
        row.get("series_type"),
        row.get("period_class"),
        row.get("basis_version"),
        repr(row.get("company_canonical_dimension_key")),
        row.get("unit_semantics") or row.get("unit_id"),
    )


def _pair_diagnostic(
    assessment: str, rows: list[dict[str, Any]], definition_id: str | None, roles: tuple[str, str]
) -> dict[str, Any]:
    chosen = {role: _one_usable(rows, role) for role in roles}
    inputs = tuple(value for value in chosen.values() if value is not None)
    status, reason = _compatibility(inputs, required=len(roles))
    return _diagnostic(assessment, definition_id, rows[0], roles, inputs, status, reason)


def _growth_diagnostics(
    rows: list[dict[str, Any]], definition_id: str | None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key = {
        str(row.get("period_key")): row for row in rows if row["metric_input_role"] == "REVENUE"
    }
    for current in sorted(by_key.values(), key=lambda item: str(item["analytical_fact_id"])):
        prior_key = current.get("comparison_period_key")
        prior = by_key.get(str(prior_key)) if prior_key else None
        status, reason = _compatibility(
            tuple(item for item in (current, prior) if item is not None),
            required=2,
            same_period=False,
        )
        if prior_key is None:
            status, reason = "UNAVAILABLE", "PREDECESSOR_PERIOD_NOT_DECLARED"
        result.append(
            _diagnostic(
                "REVENUE_GROWTH",
                definition_id,
                current,
                ("CURRENT_REVENUE", "PRIOR_REVENUE"),
                tuple(item for item in (current, prior) if item is not None),
                status,
                reason,
                comparison_period_key=prior_key,
            )
        )
    return result


def _q4_diagnostics(rows: list[dict[str, Any]], definition_id: str | None) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("period_class") != "QTD_3M" or not row.get("derived_observation_id"):
            continue
        prohibited = row["metric_input_role"] in {"EPS", "WEIGHTED_AVERAGE_SHARES"}
        eligible = (
            not prohibited
            and row.get("source_type") == "DERIVED_RECAST"
            and len(tuple(row.get("source_fact_ids") or ())) >= 2
            and bool(row.get("derivation_rule_version"))
            and bool(row.get("formula"))
        )
        status = "ELIGIBLE" if eligible else "UNAVAILABLE"
        reason = (
            None
            if eligible
            else (
                "Q4_REVERSE_ENGINEERING_PROHIBITED_FOR_NON_ADDITIVE_OBSERVATION"
                if prohibited
                else "CONTROLLED_Q4_INPUT_LINEAGE_INCOMPLETE"
            )
        )
        result.append(
            _diagnostic(
                "Q4_FLOW", definition_id, row, ("CONTROLLED_Q4_FLOW",), (row,), status, reason
            )
        )
    return result


def _one_usable(rows: Iterable[Mapping[str, Any]], role: str) -> dict[str, Any] | None:
    matches = [dict(row) for row in rows if row["metric_input_role"] == role]
    available = [row for row in matches if row.get("source_type") != "UNAVAILABLE"]
    if len(available) == 1:
        return available[0]
    if len(available) > 1:
        return None
    return matches[0] if len(matches) == 1 else None


def _compatibility(
    inputs: tuple[dict[str, Any], ...], *, required: int, same_period: bool = True
) -> tuple[str, str | None]:
    if len(inputs) != required:
        return "UNAVAILABLE", "REQUIRED_INPUT_NOT_AVAILABLE"
    if any(row.get("source_type") == "UNAVAILABLE" for row in inputs):
        return "UNAVAILABLE", "INPUT_ANALYTICAL_FACT_UNAVAILABLE"
    fields = (
        "cik",
        "view",
        "as_of_date",
        "series_type",
        "period_class",
        "basis_version",
        "company_canonical_dimension_key",
        "unit_semantics",
    )
    if same_period:
        fields = (*fields, "period_key")
    for field in fields:
        if len({repr(row.get(field)) for row in inputs}) != 1:
            return "UNAVAILABLE", "INCOMPATIBLE_" + field.upper()
    return "ELIGIBLE", None


def _diagnostic(
    assessment: str,
    definition_id: str | None,
    template: Mapping[str, Any],
    required_roles: tuple[str, ...],
    inputs: tuple[dict[str, Any], ...],
    status: str,
    reason: str | None,
    *,
    comparison_period_key: object = None,
) -> dict[str, Any]:
    identity = (
        assessment,
        template.get("cik"),
        template.get("view"),
        template.get("as_of_date"),
        template.get("series_type"),
        template.get("period_class"),
        template.get("period_key"),
        repr(template.get("company_canonical_dimension_key")),
        definition_id,
        comparison_period_key,
    )
    return {
        "metric_input_compatibility_id": _id("metric-compatibility", identity),
        "cik": template.get("cik"),
        "metric_assessment_id": assessment,
        "metric_definition_id": definition_id,
        "view": template.get("view"),
        "as_of_date": template.get("as_of_date"),
        "series_type": template.get("series_type"),
        "period_class": template.get("period_class"),
        "period_key": template.get("period_key"),
        "comparison_period_key": comparison_period_key,
        "basis_version": template.get("basis_version"),
        "company_canonical_dimension_key": template.get("company_canonical_dimension_key"),
        "unit_semantics": template.get("unit_semantics") or template.get("unit_id"),
        "mapping_versions": tuple(
            sorted(
                {str(row.get("mapping_version")) for row in inputs if row.get("mapping_version")}
            )
        ),
        "required_input_roles": required_roles,
        "input_analytical_fact_ids": tuple(row["analytical_fact_id"] for row in inputs),
        "input_selected_fact_ids": tuple(
            row.get("selected_fact_id") for row in inputs if row.get("selected_fact_id")
        ),
        "compatibility_status": status,
        "unavailable_reason": reason,
        "metric_input_handoff_version": METRIC_INPUT_HANDOFF_VERSION,
    }


def _id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, default=repr, sort_keys=True, separators=(",", ":")).encode()
    return prefix + ":" + hashlib.sha256(encoded).hexdigest()[:24]


def _candidate_sort(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["metric_input_candidate_id"]), str(row["analytical_fact_id"])


def _diagnostic_sort(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["metric_input_compatibility_id"]), str(row["metric_assessment_id"])
