"""M6 context-driven period classes, comparisons, and conservative Q4 derivation.

The functions in this module return new records.  They never modify the
immutable Layer 1 source rows supplied by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sec_xbrl.facts.layer1 import _stable_id

DERIVATION_RULE_VERSION = "m6-q4-subtraction-v1"

_DURATION_RANGES = {
    "QTD_3M": range(75, 106),
    "YTD_6M": range(160, 206),
    "YTD_9M": range(250, 301),
    # 52- and 53-week fiscal years are 364 and 371 days respectively.
    "FY": range(350, 379),
}


class DisclosureState(StrEnum):
    """Controlled states for a critical disclosure across filings."""

    BASELINE = "BASELINE"
    NEW = "NEW"
    CHANGED = "CHANGED"
    REPORTED_UNCHANGED = "REPORTED_UNCHANGED"
    NOT_REPORTED_THIS_QUARTER = "NOT_REPORTED_THIS_QUARTER"
    RESOLVED = "RESOLVED"


class PeriodClassifier:
    """Classify Layer 1 facts from concepts and contexts, not filing labels."""

    def classify(
        self,
        *,
        filing: Mapping[str, Any],
        concepts: Iterable[Mapping[str, Any]],
        contexts: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        """Return copied fact records enriched with period and comparative classes."""
        concept_by_id = {str(row["raw_concept_id"]): row for row in concepts}
        context_by_id = {str(row["context_id"]): row for row in contexts}
        focus_date = _as_date(filing.get("report_date"))
        fiscal_year_end = _fiscal_year_end(filing.get("fiscal_year_end"))
        result: list[dict[str, Any]] = []
        for raw_fact in facts:
            fact = dict(raw_fact)
            context = context_by_id.get(str(fact.get("context_id")))
            concept = concept_by_id.get(str(fact.get("raw_concept_id")))
            fact["period_class"] = _period_class(concept, context)
            fact["comparative_type"] = _comparative_type(
                context, fact["period_class"], focus_date, fiscal_year_end
            )
            result.append(fact)
        return tuple(result)


class Layer1PeriodAnalysis:
    """Create separate analytical observations from immutable Layer 1 rows."""

    def build(
        self,
        *,
        filing: Mapping[str, Any],
        concepts: Iterable[Mapping[str, Any]],
        contexts: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]],
        units: Iterable[Mapping[str, Any]],
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        del units
        observations = PeriodClassifier().classify(
            filing=filing, concepts=concepts, contexts=contexts, facts=facts
        )
        # M7 owns canonical identity and additivity.  Surface the absent policy
        # as an auditable no-candidate outcome instead of guessing Q4 sources.
        q4 = derive_q4_facts(observations, contexts, dimension_facts)
        outcomes = (
            {
                "filing_id": filing.get("filing_id"),
                "candidate_count": len(q4),
                "outcome": "DERIVED" if q4 else "NO_CANDIDATE",
                "reason": None if q4 else "M7_CANONICAL_ADDITIVE_POLICY_REQUIRED",
            },
        )
        return observations + q4, outcomes


def derive_q4_facts(
    facts: Iterable[Mapping[str, Any]],
    contexts: Iterable[Mapping[str, Any]],
    dimension_facts: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Create distinct Q4 records only for explicitly compatible additive facts.

    ``canonical_concept_id`` and ``is_additive`` must be supplied by the
    analytical caller.  M6 intentionally does not guess a canonical mapping
    or additivity from a raw local name.
    """
    context_by_id = {str(row["context_id"]): row for row in contexts}
    dimensions_by_fact: dict[str, tuple[tuple[str | None, str | None, str | None], ...]] = {}
    grouped: dict[str, list[tuple[str | None, str | None, str | None]]] = {}
    for row in dimension_facts:
        fact_id = str(row["fact_id"])
        grouped.setdefault(fact_id, []).append(
            (
                _optional_text(row.get("axis_raw_concept_id")),
                _optional_text(row.get("member_raw_concept_id")),
                _optional_text(row.get("typed_member")),
            )
        )
    dimensions_by_fact = {key: tuple(sorted(value)) for key, value in grouped.items()}
    reported = [dict(row) for row in facts if row.get("reported_or_derived", "REPORTED") == "REPORTED"]
    fiscal_years = [_fiscal_year(row, context_by_id) for row in reported]
    results: list[dict[str, Any]] = []
    for fy, fy_year in zip(reported, fiscal_years, strict=True):
        if fy.get("period_class") != "FY" or not _eligible_additive(fy):
            continue
        for ytd, ytd_year in zip(reported, fiscal_years, strict=True):
            if ytd.get("period_class") != "YTD_9M" or not _eligible_additive(ytd):
                continue
            if not _compatible(fy, ytd, fy_year, ytd_year, context_by_id, dimensions_by_fact):
                continue
            q4_value = _subtract(fy.get("value_numeric"), ytd.get("value_numeric"))
            if q4_value is None:
                continue
            source_ids = (str(fy["fact_id"]), str(ytd["fact_id"]))
            row = dict(fy)
            row.update(
                {
                    "fact_id": _stable_id("derived-q4", *source_ids, DERIVATION_RULE_VERSION),
                    "context_id": None,
                    "value_numeric": q4_value,
                    "value_text": None,
                    "raw_value": None,
                    "reported_or_derived": "DERIVED",
                    "period_class": "QTD_3M",
                    "formula": "FY - YTD_9M",
                    "source_fact_ids": source_ids,
                    "derivation_rule_version": DERIVATION_RULE_VERSION,
                }
            )
            results.append(row)
    return tuple(sorted(results, key=lambda row: str(row["fact_id"])))


class DisclosureStateTracker:
    """Apply disclosure transitions without treating a missing 10-Q as resolution."""

    def next_state(
        self,
        previous: DisclosureState | str | None,
        *,
        reported: bool,
        changed: bool = False,
        resolved: bool = False,
    ) -> DisclosureState:
        """Return a state; explicit resolution evidence is the sole path to RESOLVED."""
        if resolved:
            return DisclosureState.RESOLVED
        if not reported:
            return DisclosureState.NOT_REPORTED_THIS_QUARTER
        if previous is None:
            return DisclosureState.BASELINE
        if previous in {DisclosureState.RESOLVED, DisclosureState.NOT_REPORTED_THIS_QUARTER}:
            return DisclosureState.NEW
        return DisclosureState.CHANGED if changed else DisclosureState.REPORTED_UNCHANGED


def _period_class(concept: Mapping[str, Any] | None, context: Mapping[str, Any] | None) -> str:
    if context is None:
        return "OTHER_DURATION"
    if context.get("period_kind") == "INSTANT" or (concept or {}).get("period_type") == "instant":
        return "INSTANT"
    if context.get("period_kind") != "DURATION":
        return "OTHER_DURATION"
    duration_days = context.get("duration_days")
    if not isinstance(duration_days, int):
        start, end = _as_date(context.get("start_date")), _as_date(context.get("end_date"))
        duration_days = (end - start).days if start and end else None
    if isinstance(duration_days, int):
        for period_class, days in _DURATION_RANGES.items():
            if duration_days in days:
                return period_class
    return "OTHER_DURATION"


def _comparative_type(
    context: Mapping[str, Any] | None,
    period_class: str,
    focus_date: date | None,
    fiscal_year_end: tuple[int, int] | None,
) -> str:
    if context is None or focus_date is None:
        return "OTHER_COMPARATIVE_CONTEXT"
    observed = _as_date(context.get("instant_date") if period_class == "INSTANT" else context.get("end_date"))
    observed = _normalized_context_endpoint(observed, focus_date)
    if observed is None:
        return "OTHER_COMPARATIVE_CONTEXT"
    if observed == focus_date:
        return "CURRENT_FOCUS"
    distance = (focus_date - observed).days
    if period_class != "INSTANT" and 330 <= distance <= 390:
        return "PRIOR_YEAR_COMPARABLE"
    if period_class == "INSTANT" and fiscal_year_end == (observed.month, observed.day) and observed < focus_date:
        return "PRIOR_FY_BALANCE"
    return "OTHER_COMPARATIVE_CONTEXT"


def _compatible(
    fy: Mapping[str, Any], ytd: Mapping[str, Any], fy_year: int | None, ytd_year: int | None,
    contexts: Mapping[str, Mapping[str, Any]], dimensions: Mapping[str, tuple[tuple[str | None, str | None, str | None], ...]],
) -> bool:
    if not fy.get("canonical_concept_id") or fy.get("canonical_concept_id") != ytd.get("canonical_concept_id"):
        return False
    if fy_year is None or fy_year != ytd_year or fy.get("unit_id") != ytd.get("unit_id"):
        return False
    if dimensions.get(str(fy["fact_id"]), ()) != dimensions.get(str(ytd["fact_id"]), ()):
        return False
    for key in ("structural_version", "recast_version"):
        if fy.get(key) != ytd.get(key):
            return False
    if fy.get("comparability_flag") != "COMPATIBLE" or ytd.get("comparability_flag") != "COMPATIBLE":
        return False
    fy_context = contexts.get(str(fy.get("context_id")), {})
    ytd_context = contexts.get(str(ytd.get("context_id")), {})
    fy_start, fy_end = _as_date(fy_context.get("start_date")), _as_date(fy_context.get("end_date"))
    ytd_start, ytd_end = _as_date(ytd_context.get("start_date")), _as_date(ytd_context.get("end_date"))
    return (
        fy_start is not None
        and fy_start == ytd_start
        and fy_end is not None
        and ytd_end is not None
        and 60 <= (fy_end - ytd_end).days <= 120
    )


def _eligible_additive(fact: Mapping[str, Any]) -> bool:
    return fact.get("is_additive") is True and fact.get("is_nil") is not True


def _fiscal_year(fact: Mapping[str, Any], contexts: Mapping[str, Mapping[str, Any]]) -> int | None:
    supplied = fact.get("fiscal_year")
    if isinstance(supplied, int):
        return supplied
    end = _as_date(contexts.get(str(fact.get("context_id")), {}).get("end_date"))
    return None if end is None else end.year


def _subtract(left: Any, right: Any) -> str | None:
    try:
        return str(Decimal(str(left)) - Decimal(str(right)))
    except (InvalidOperation, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalized_context_endpoint(value: date | None, focus_date: date | None) -> date | None:
    """Normalize SEC XBRL Context endpoints to the DEI reporting-date convention.

    SEC Inline filings commonly encode the end/instant boundary as the next
    calendar day while DEI ``DocumentPeriodEndDate`` names the preceding
    reporting date.  M6 uses this documented boundary convention only for
    analytical comparisons; the Raw Context text/dates are never changed.
    """
    if value is not None and focus_date is not None and value != focus_date and (value - focus_date).days == 1:
        return value - timedelta(days=1)
    return value


def _fiscal_year_end(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str):
        if value.startswith("--"):
            parts = value[2:].split("-")
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                return int(parts[0]), int(parts[1])
        try:
            parsed = date.fromisoformat(value)
            return parsed.month, parsed.day
        except ValueError:
            parts = value.replace("/", "-").split("-")
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                return int(parts[0]), int(parts[1])
    return None


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)
