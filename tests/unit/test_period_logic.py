from __future__ import annotations

from sec_xbrl.periods.logic import DisclosureState, DisclosureStateTracker, PeriodClassifier, derive_q4_facts


def _context(context_id: str, start: str | None, end: str | None, *, instant: str | None = None) -> dict[str, object]:
    return {
        "context_id": context_id,
        "period_kind": "INSTANT" if instant else "DURATION",
        "start_date": start,
        "end_date": end,
        "instant_date": instant,
        "duration_days": None if instant else _days(start, end),
    }


def _days(start: str | None, end: str | None) -> int:
    from datetime import date

    assert start and end
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _fact(fact_id: str, context_id: str, *, value: str = "100", **extra: object) -> dict[str, object]:
    return {
        "fact_id": fact_id,
        "raw_concept_id": "raw-revenue",
        "context_id": context_id,
        "unit_id": "usd",
        "value_numeric": value,
        "reported_or_derived": "REPORTED",
        "is_nil": False,
        **extra,
    }


def test_context_and_concept_drive_duration_and_comparative_classes() -> None:
    contexts = (
        _context("qtd", "2025-06-29", "2025-09-27"),
        _context("ytd", "2024-12-29", "2025-09-27"),
        _context("prior-ytd", "2023-12-31", "2024-09-28"),
        _context("prior-fy", None, None, instant="2024-12-28"),
        _context("weird", "2025-01-01", "2025-02-01"),
    )
    concepts = (
        {"raw_concept_id": "raw-revenue", "period_type": "duration"},
        {"raw_concept_id": "raw-assets", "period_type": "instant"},
    )
    facts = (
        _fact("qtd", "qtd"),
        _fact("ytd", "ytd"),
        _fact("prior-ytd", "prior-ytd"),
        {**_fact("prior-fy", "prior-fy"), "raw_concept_id": "raw-assets"},
        _fact("weird", "weird"),
    )

    rows = PeriodClassifier().classify(
        filing={"report_date": "2025-09-27", "fiscal_year_end": "12-28"},
        concepts=concepts,
        contexts=contexts,
        facts=facts,
    )

    by_id = {row["fact_id"]: row for row in rows}
    assert by_id["qtd"]["period_class"] == "QTD_3M"
    assert by_id["qtd"]["comparative_type"] == "CURRENT_FOCUS"
    assert by_id["ytd"]["period_class"] == "YTD_9M"
    assert by_id["prior-ytd"]["comparative_type"] == "PRIOR_YEAR_COMPARABLE"
    assert by_id["prior-fy"]["period_class"] == "INSTANT"
    assert by_id["prior-fy"]["comparative_type"] == "PRIOR_FY_BALANCE"
    assert by_id["weird"]["period_class"] == "OTHER_DURATION"


def test_52_and_53_week_fiscal_years_are_fy_not_calendar_assumptions() -> None:
    contexts = (
        _context("fy-52", "2024-12-29", "2025-12-28"),
        _context("fy-53", "2025-12-28", "2027-01-03"),
    )
    rows = PeriodClassifier().classify(
        filing={"report_date": "2027-01-03"},
        concepts=({"raw_concept_id": "raw-revenue", "period_type": "duration"},),
        contexts=contexts,
        facts=(_fact("fy-52", "fy-52"), _fact("fy-53", "fy-53")),
    )
    assert [row["period_class"] for row in rows] == ["FY", "FY"]


def test_derived_q4_is_distinct_and_requires_canonical_additive_compatible_sources() -> None:
    contexts = (
        _context("fy", "2024-12-29", "2025-12-28"),
        _context("ytd", "2024-12-29", "2025-09-28"),
    )
    facts = (
        _fact(
            "fy", "fy", value="1000", period_class="FY", canonical_concept_id="revenue", is_additive=True,
            fiscal_year=2025, structural_version="v1",
        ),
        _fact(
            "ytd", "ytd", value="720", period_class="YTD_9M", canonical_concept_id="revenue", is_additive=True,
            fiscal_year=2025, structural_version="v1",
        ),
        _fact(
            "bad", "ytd", value="720", period_class="YTD_9M", canonical_concept_id="margin", is_additive=False,
            fiscal_year=2025, structural_version="v1",
        ),
    )

    derived = derive_q4_facts(facts, contexts, ())

    assert len(derived) == 1
    q4 = derived[0]
    assert q4["value_numeric"] == "280"
    assert q4["reported_or_derived"] == "DERIVED"
    assert q4["formula"] == "FY - YTD_9M"
    assert q4["source_fact_ids"] == ("fy", "ytd")
    assert q4["fact_id"] not in {"fy", "ytd"}
    assert all(row["reported_or_derived"] == "REPORTED" for row in facts)


def test_q4_rejects_dimension_or_recast_mismatch() -> None:
    contexts = (_context("fy", "2024-12-29", "2025-12-28"), _context("ytd", "2024-12-29", "2025-09-28"))
    common = {"period_class": "FY", "canonical_concept_id": "revenue", "is_additive": True, "fiscal_year": 2025}
    fy = _fact("fy", "fy", **common)
    ytd = _fact("ytd", "ytd", **{**common, "period_class": "YTD_9M", "recast_version": "recast-1"})
    assert derive_q4_facts((fy, ytd), contexts, ()) == ()

    dimensions = (
        {"fact_id": "fy", "axis_raw_concept_id": "axis", "member_raw_concept_id": "a", "typed_member": None},
        {"fact_id": "ytd", "axis_raw_concept_id": "axis", "member_raw_concept_id": "b", "typed_member": None},
    )
    ytd_same_recast = {**ytd, "recast_version": None}
    assert derive_q4_facts((fy, ytd_same_recast), contexts, dimensions) == ()


def test_missing_disclosure_never_becomes_resolved_without_explicit_evidence() -> None:
    tracker = DisclosureStateTracker()
    state = tracker.next_state(DisclosureState.REPORTED_UNCHANGED, reported=False)
    assert state == DisclosureState.NOT_REPORTED_THIS_QUARTER
    assert tracker.next_state(state, reported=False) == DisclosureState.NOT_REPORTED_THIS_QUARTER
    assert tracker.next_state(state, reported=True) == DisclosureState.NEW
    assert tracker.next_state(state, reported=False, resolved=True) == DisclosureState.RESOLVED
