"""L2-M1 materialization of immutable Layer 1 Facts into period observations.

This boundary deliberately has no company mapping or recast-selection policy.
It copies each usable raw Fact exactly once, retaining its complete raw
identity and classifying the actual Context period.  Rows that cannot be
classified safely are represented by explicit exclusion records instead of
being silently omitted.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sec_xbrl.periods.logic import DERIVATION_RULE_VERSION, PeriodClassifier, derive_q4_facts

PERIOD_OBSERVATION_RULE_VERSION = "l2-m1-period-observation-v1"


@dataclass(frozen=True, slots=True)
class PeriodObservationResult:
    """A complete, non-mutating accounting for one Layer 1 snapshot's Facts."""

    observations: tuple[dict[str, Any], ...]
    exclusions: tuple[dict[str, Any], ...]

    @property
    def accounted_source_fact_count(self) -> int:
        return sum(row.get("reported_or_derived") == "REPORTED" for row in self.observations) + len(self.exclusions)


class PeriodObservationMaterializer:
    """Create L2-M1 period observations without changing Layer 1 input rows.

    Q4 requires separately supplied, reviewed additive policy.  It is not
    inferred from a label, concept local name, value pattern, or filing form.
    The policy hook is intentionally optional because company canonical
    mapping and structural/recast review belong to later milestones.
    """

    def materialize(
        self,
        *,
        filing: Mapping[str, Any],
        concepts: Iterable[Mapping[str, Any]],
        contexts: Iterable[Mapping[str, Any]],
        units: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any],],
        dimension_facts: Iterable[Mapping[str, Any]] = (),
        q4_policy_by_fact_id: Mapping[str, Mapping[str, Any]] | None = None,
        source_snapshot_id: str | None = None,
    ) -> PeriodObservationResult:
        """Return one reported observation or one exclusion per raw Fact.

        ``q4_policy_by_fact_id`` may supply only explicit, independently
        reviewed additivity/canonical metadata.  Supplying no policy is safe:
        it publishes reported observations and no Q4 candidate.
        """
        filing_row = dict(filing)
        concept_by_id = {str(row.get("raw_concept_id")): dict(row) for row in concepts}
        context_by_id = {str(row.get("context_id")): dict(row) for row in contexts}
        unit_by_id = {str(row.get("unit_id")): dict(row) for row in units}
        dimensions = _dimensions_by_fact(dimension_facts, concept_by_id)
        raw_facts = tuple(dict(row) for row in facts)
        classified = PeriodClassifier().classify(
            filing=filing_row,
            concepts=concept_by_id.values(),
            contexts=context_by_id.values(),
            facts=raw_facts,
        )

        observations: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        policy = q4_policy_by_fact_id or {}
        for ordinal, fact in enumerate(classified):
            reason = _exclusion_reason(fact, filing_row, concept_by_id, context_by_id, unit_by_id, dimensions)
            if reason is not None:
                exclusions.append(_exclusion(filing_row, fact, ordinal, reason))
                continue
            observations.append(
                _observation(
                    filing=filing_row,
                    fact=fact,
                    concept=concept_by_id[str(fact["raw_concept_id"])],
                    context=context_by_id[str(fact["context_id"])],
                    unit=unit_by_id.get(str(fact.get("unit_id"))),
                    dimension_signature=dimensions.get(str(fact["fact_id"]), ()),
                    policy=policy.get(str(fact["fact_id"])),
                    source_snapshot_id=source_snapshot_id,
                )
            )

        q4 = _q4_candidates(observations, contexts=context_by_id.values(), dimension_facts=dimension_facts)
        return PeriodObservationResult(
            observations=tuple(sorted(observations + q4, key=lambda row: str(row["period_observation_id"]))),
            exclusions=tuple(sorted(exclusions, key=lambda row: str(row["period_observation_exclusion_id"]))),
        )


def _dimensions_by_fact(
    rows: Iterable[Mapping[str, Any]], concepts: Mapping[str, Mapping[str, Any]]
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        fact_id = str(item.get("fact_id") or "")
        axis_id = str(item.get("axis_raw_concept_id") or "")
        member_id = item.get("member_raw_concept_id")
        # L1 has already made unresolved explicit dimensions a completeness
        # failure.  Preserve a malformed supplied row so the Fact becomes an
        # explicit L2 exclusion rather than losing this evidence.
        item["axis_resolved"] = bool(axis_id and axis_id in concepts)
        item["member_resolved"] = member_id is None or str(member_id) in concepts
        grouped[fact_id].append(
            {
                "axis_raw_concept_id": axis_id or None,
                "member_raw_concept_id": None if member_id is None else str(member_id),
                "typed_member": item.get("typed_member"),
                "dimension_type": item.get("dimension_type"),
                "is_default_member": item.get("is_default_member"),
                "axis_resolved": item["axis_resolved"],
                "member_resolved": item["member_resolved"],
            }
        )
    return {
        fact_id: tuple(sorted(values, key=_canonical_json))
        for fact_id, values in grouped.items()
    }


def _exclusion_reason(
    fact: Mapping[str, Any],
    filing: Mapping[str, Any],
    concepts: Mapping[str, Mapping[str, Any]],
    contexts: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, Mapping[str, Any]],
    dimensions: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> str | None:
    if not fact.get("fact_id"):
        return "MISSING_FACT_ID"
    if not fact.get("filing_id") or str(fact.get("filing_id")) != str(filing.get("filing_id")):
        return "FACT_FILING_MISMATCH"
    if not fact.get("raw_concept_id") or str(fact.get("raw_concept_id")) not in concepts:
        return "MISSING_OR_UNRESOLVED_CONCEPT"
    concept_reference = _reference_filing_reason(concepts[str(fact["raw_concept_id"])], filing, "CONCEPT")
    if concept_reference:
        return concept_reference
    if not fact.get("context_id") or str(fact.get("context_id")) not in contexts:
        return "MISSING_OR_UNRESOLVED_CONTEXT"
    context_reference = _reference_filing_reason(contexts[str(fact["context_id"])], filing, "CONTEXT")
    if context_reference:
        return context_reference
    if fact.get("unit_id") and str(fact["unit_id"]) not in units:
        return "MISSING_OR_UNRESOLVED_UNIT"
    if fact.get("unit_id"):
        unit_reference = _reference_filing_reason(units[str(fact["unit_id"])], filing, "UNIT")
        if unit_reference:
            return unit_reference
    if any(not item["axis_resolved"] or not item["member_resolved"] for item in dimensions.get(str(fact["fact_id"]), ())):
        return "MISSING_OR_UNRESOLVED_DIMENSION"
    for dimension in dimensions.get(str(fact["fact_id"]), ()):
        axis = concepts[str(dimension["axis_raw_concept_id"])]
        axis_reference = _reference_filing_reason(axis, filing, "DIMENSION")
        if axis_reference:
            return axis_reference
        member_id = dimension.get("member_raw_concept_id")
        if member_id is not None:
            member_reference = _reference_filing_reason(concepts[str(member_id)], filing, "DIMENSION")
            if member_reference:
                return member_reference
    return None


def _exclusion(filing: Mapping[str, Any], fact: Mapping[str, Any], ordinal: int, reason: str) -> dict[str, Any]:
    source_id = str(fact.get("fact_id") or f"ordinal:{ordinal}")
    return {
        "period_observation_exclusion_id": _stable_id("period-observation-exclusion", filing.get("filing_id"), source_id, reason),
        "cik": filing.get("cik"),
        "source_fact_id": fact.get("fact_id"),
        "source_fact_ordinal": ordinal,
        "source_filing_id": filing.get("filing_id"),
        "accession": filing.get("accession"),
        "filed_date": filing.get("filed_date"),
        "report_date": filing.get("report_date"),
        "exclusion_reason": reason,
        "classification_rule_version": PERIOD_OBSERVATION_RULE_VERSION,
    }


def _observation(
    *,
    filing: Mapping[str, Any],
    fact: Mapping[str, Any],
    concept: Mapping[str, Any],
    context: Mapping[str, Any],
    unit: Mapping[str, Any] | None,
    dimension_signature: tuple[Mapping[str, Any], ...],
    policy: Mapping[str, Any] | None,
    source_snapshot_id: str | None,
) -> dict[str, Any]:
    period_class = str(fact["period_class"])
    signature = tuple(
        (
            row.get("axis_raw_concept_id"), row.get("member_raw_concept_id"), row.get("typed_member"),
            row.get("dimension_type"), row.get("is_default_member"),
        )
        for row in dimension_signature
    )
    fiscal_year = _fiscal_year(filing, context)
    source_fact_id = str(fact["fact_id"])
    result = {
        "period_observation_id": _stable_id("period-observation", source_fact_id, PERIOD_OBSERVATION_RULE_VERSION),
        "cik": filing.get("cik"),
        "source_fact_id": source_fact_id,
        "source_filing_id": filing.get("filing_id"),
        "source_snapshot_id": source_snapshot_id,
        "accession": filing.get("accession"),
        "form": filing.get("form"),
        "filed_date": filing.get("filed_date"),
        "report_date": filing.get("report_date"),
        "source_document": fact.get("source_document"),
        "source_locator": fact.get("source_locator"),
        "raw_concept_id": fact.get("raw_concept_id"),
        "raw_concept_qname": concept.get("qname"),
        "raw_concept_namespace_uri": concept.get("namespace_uri"),
        "raw_concept_local_name": concept.get("local_name"),
        "raw_concept_period_type": concept.get("period_type"),
        "context_id": fact.get("context_id"),
        "context_period_kind": context.get("period_kind"),
        "context_start_date": context.get("start_date"),
        "context_end_date": context.get("end_date"),
        "context_instant_date": context.get("instant_date"),
        "context_duration_days": context.get("duration_days"),
        "unit_id": fact.get("unit_id"),
        "unit_numerator_measures": None if unit is None else unit.get("numerator_measures"),
        "unit_denominator_measures": None if unit is None else unit.get("denominator_measures"),
        "dimension_signature": signature,
        "value_numeric": fact.get("value_numeric"),
        "value_text": fact.get("value_text"),
        "is_nil": fact.get("is_nil"),
        "reported_or_derived": "REPORTED",
        "period_class": period_class,
        "period_key": _period_key(context, period_class),
        "comparative_type": fact.get("comparative_type"),
        "fiscal_year": fiscal_year,
        # Class is deliberately inside this identity: QTD/YTD/FY/instant
        # candidates cannot coalesce before later mapping/series policy.
        "raw_series_identity": (
            filing.get("cik"), fact.get("raw_concept_id"), signature, fact.get("unit_id"), period_class,
        ),
        "classification_rule_version": PERIOD_OBSERVATION_RULE_VERSION,
        "q4_derivation_eligible": False,
    }
    if policy is not None:
        result.update(_validated_q4_policy(policy, concept, unit))
    return result


def _validated_q4_policy(
    policy: Mapping[str, Any], concept: Mapping[str, Any], unit: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Require reviewed policy *and* independently safe raw semantics.

    The policy is evidence, not an authority to reclassify a per-share, share,
    ratio, margin, or average Fact as additive.  A candidate needs a distinct
    reviewed semantic state as well as a duration concept with monetary data
    type and a single currency Unit.  This is intentionally conservative: an
    uncertain value remains directly reported until a later semantic policy can
    expose it safely.
    """
    value_kind = policy.get("value_kind")
    forbidden = {"EPS", "WEIGHTED_AVERAGE_SHARES", "RATIO", "MARGIN", "AVERAGE", "NON_ADDITIVE"}
    eligible = (
        policy.get("canonical_concept_id")
        and policy.get("is_additive") is True
        and value_kind == "ADDITIVE_AMOUNT"
        and policy.get("semantic_review_state") == "REVIEWED_ADDITIVE_AMOUNT"
        and str(value_kind) not in forbidden
        and policy.get("comparability_flag") == "COMPATIBLE"
        and _has_safe_additive_amount_semantics(concept, unit)
    )
    return {
        "canonical_concept_id": policy.get("canonical_concept_id"),
        "is_additive": policy.get("is_additive") is True,
        "value_kind": value_kind,
        "semantic_review_state": policy.get("semantic_review_state"),
        "structural_version": policy.get("structural_version"),
        "recast_version": policy.get("recast_version"),
        "comparability_flag": policy.get("comparability_flag"),
        "q4_derivation_eligible": bool(eligible),
    }


def _has_safe_additive_amount_semantics(
    concept: Mapping[str, Any], unit: Mapping[str, Any] | None
) -> bool:
    if str(concept.get("period_type") or "").lower() != "duration" or unit is None:
        return False
    data_type = str(concept.get("data_type") or "").lower()
    if "monetary" not in data_type:
        return False
    # Defense in depth only: this is raw QName/local identity, never a label
    # heuristic.  The primary fail-closed gate is the typed monetary Unit and
    # reviewed semantic state above; these well-known non-additive identities
    # catch extensions that happen to use a currency unit.
    identity = "".join(str(concept.get(key) or "") for key in ("qname", "local_name")).lower()
    if any(token in identity for token in ("average", "margin", "ratio", "rate", "pershare")):
        return False
    numerator = _measure_tokens(unit.get("numerator_measures"))
    denominator = _measure_tokens(unit.get("denominator_measures"))
    if denominator or not numerator:
        return False
    # Monetary flow candidates carry an ISO 4217 currency measure.  A share,
    # pure, or other non-currency Unit is never eligible for subtraction.
    return any(token.startswith("iso4217:") for token in numerator)


def _measure_tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip().lower() for item in value.replace(",", " ").split() if item.strip())
    if isinstance(value, Iterable):
        return tuple(str(item).strip().lower() for item in value if str(item).strip())
    return (str(value).strip().lower(),)


def _reference_filing_reason(row: Mapping[str, Any], filing: Mapping[str, Any], kind: str) -> str | None:
    reference_filing_id = row.get("filing_id")
    if not reference_filing_id:
        return f"MISSING_{kind}_REFERENCE_FILING_ID"
    if str(reference_filing_id) != str(filing.get("filing_id")):
        return f"CROSS_FILING_{kind}_REFERENCE"
    return None


def _q4_candidates(
    observations: Iterable[Mapping[str, Any]],
    *,
    contexts: Iterable[Mapping[str, Any]],
    dimension_facts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    source_rows = tuple(dict(row) for row in observations)
    candidates = [
        {**row, "fact_id": row["source_fact_id"]}
        for row in source_rows
        if row.get("q4_derivation_eligible") and row.get("source_fact_id")
    ]
    # Reuse the conservative M6 compatibility engine after passing only
    # explicit reviewed policy.  Its dimensional, unit, fiscal-start,
    # structural/recast and comparability gates all remain in force.
    derived = derive_q4_facts(candidates, contexts, dimension_facts)
    output: list[dict[str, Any]] = []
    by_source = {str(row["source_fact_id"]): row for row in source_rows}
    for row in derived:
        source_ids = tuple(str(item) for item in row["source_fact_ids"])
        source = by_source[source_ids[0]]
        ytd_source = by_source[source_ids[1]]
        q4_start, q4_end = _q4_boundaries(source, ytd_source)
        output.append(
            {
                **source,
                "period_observation_id": _stable_id("period-observation", row["fact_id"], PERIOD_OBSERVATION_RULE_VERSION),
                "source_fact_id": None,
                "derived_observation_id": row["fact_id"],
                "reported_or_derived": "DERIVED",
                "value_numeric": row["value_numeric"],
                "context_id": None,
                "context_start_date": q4_start,
                "context_end_date": q4_end,
                "context_instant_date": None,
                "context_duration_days": _duration_days(q4_start, q4_end),
                "period_class": "QTD_3M",
                "period_key": _period_key_from_bounds(q4_start, q4_end, fallback=_q4_period_key(source)),
                "fiscal_period_key": _q4_period_key(source),
                "comparative_type": "CURRENT_FOCUS",
                "raw_series_identity": (
                    source.get("cik"), source.get("raw_concept_id"), source.get("dimension_signature"),
                    source.get("unit_id"), "QTD_3M",
                ),
                "formula": row["formula"],
                "source_fact_ids": source_ids,
                "derivation_rule_version": DERIVATION_RULE_VERSION,
                "classification_rule_version": PERIOD_OBSERVATION_RULE_VERSION,
            }
        )
    return output


def _period_key(context: Mapping[str, Any], period_class: str) -> str:
    if period_class == "INSTANT":
        return str(context.get("instant_date") or "")
    return f"{context.get('start_date') or ''}/{context.get('end_date') or ''}"


def _q4_period_key(source: Mapping[str, Any]) -> str:
    year = source.get("fiscal_year")
    return f"FY{year}-Q4" if year is not None else "Q4-DERIVED"


def _q4_boundaries(fy: Mapping[str, Any], ytd: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Use the reviewed FY/YTD source contexts to give Q4 a real duration."""
    fy_end = _as_date(fy.get("context_end_date"))
    ytd_end = _as_date(ytd.get("context_end_date"))
    if fy_end is None or ytd_end is None or ytd_end >= fy_end:
        return None, None
    return (ytd_end.fromordinal(ytd_end.toordinal() + 1).isoformat(), fy_end.isoformat())


def _duration_days(start: str | None, end: str | None) -> int | None:
    start_date, end_date = _as_date(start), _as_date(end)
    return None if start_date is None or end_date is None else (end_date - start_date).days + 1


def _period_key_from_bounds(start: str | None, end: str | None, *, fallback: str) -> str:
    return f"{start}/{end}" if start is not None and end is not None else fallback


def _as_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _fiscal_year(filing: Mapping[str, Any], context: Mapping[str, Any]) -> int | None:
    value = filing.get("document_fiscal_year_focus")
    try:
        return int(str(value))
    except (TypeError, ValueError):
        endpoint = context.get("instant_date") or context.get("end_date")
        try:
            return date.fromisoformat(str(endpoint)).year
        except (TypeError, ValueError):
            return None


def _stable_id(*parts: Any) -> str:
    return "l2:" + hashlib.sha256("|".join(str(item) for item in parts).encode()).hexdigest()[:24]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
