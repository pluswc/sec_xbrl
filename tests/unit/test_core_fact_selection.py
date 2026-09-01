from __future__ import annotations

from sec_xbrl.longitudinal import CoreQuarterlyFactSelector

CORE_ID = "company:0001045810:concept:revenue"


def _candidate(
    fact_id: str,
    *,
    form: str = "10-Q",
    filed_date: str = "2024-05-22",
    accession: str = "0001045810-24-000100",
    dimensions: tuple[object, ...] = (),
) -> dict[str, object]:
    return {
        "analytical_fact_id": "same-quarter",
        "company_canonical_concept_id": CORE_ID,
        "selected_fact_id": fact_id,
        "form": form,
        "filed_date": filed_date,
        "accession": accession,
        "raw_dimension_signature": dimensions,
    }


def test_prefers_direct_10q_then_latest_raw_filing_then_undimensioned() -> None:
    result = CoreQuarterlyFactSelector().select(
        (
            _candidate("10k-comparative", form="10-K", filed_date="2025-02-26"),
            _candidate("dimensioned-10q", dimensions=(("axis", "member"),)),
            _candidate("later-10q", filed_date="2024-05-23", accession="0001045810-24-000101"),
        ),
        core_canonical_concept_ids=(CORE_ID,),
    )
    assert result is not None
    assert result.unavailable_reason is None
    assert result.selected is not None
    assert result.selected["selected_fact_id"] == "later-10q"


def test_undimensioned_preference_applies_only_within_the_selected_filing() -> None:
    result = CoreQuarterlyFactSelector().select(
        (
            _candidate("older-undimensioned"),
            _candidate(
                "newer-dimensioned",
                filed_date="2024-05-23",
                accession="0001045810-24-000101",
                dimensions=(("axis", "member"),),
            ),
        ),
        core_canonical_concept_ids=(CORE_ID,),
    )
    assert result is not None
    assert result.selected is not None
    assert result.selected["selected_fact_id"] == "newer-dimensioned"


def test_excludes_amendments_from_default_selection_but_keeps_ties_unavailable() -> None:
    result = CoreQuarterlyFactSelector().select(
        (
            _candidate("original"),
            _candidate("amendment", form="10-Q/A", filed_date="2024-06-01"),
        ),
        core_canonical_concept_ids=(CORE_ID,),
    )
    assert result is not None
    assert result.selected is not None
    assert result.selected["selected_fact_id"] == "original"

    tied = CoreQuarterlyFactSelector().select(
        (_candidate("first"), _candidate("second")), core_canonical_concept_ids=(CORE_ID,)
    )
    assert tied is not None
    assert tied.selected is None
    assert tied.unavailable_reason == "CORE_FACT_SELECTION_TIE_REVIEW_REQUIRED"

    amendment_only = CoreQuarterlyFactSelector().select(
        (_candidate("amendment", form="10-Q/A"),), core_canonical_concept_ids=(CORE_ID,)
    )
    assert amendment_only is not None
    assert amendment_only.selected is None
    assert amendment_only.unavailable_reason == "CORE_FACT_SELECTION_AMENDMENT_ONLY"


def test_non_core_group_is_not_selected_by_core_policy() -> None:
    assert CoreQuarterlyFactSelector().select(
        (_candidate("fact"),), core_canonical_concept_ids=("company:other",)
    ) is None
