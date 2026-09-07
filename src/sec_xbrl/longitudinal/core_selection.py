"""Deterministic basic-fact selection for same-period Layer 2 collisions.

This is intentionally narrower than semantic selection.  It resolves only a
caller-declared set of common canonical concepts and preserves every raw
candidate in the upstream series datasets.  No amendment becomes a default
selection input; an unresolved tie remains explicit and review-required.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CORE_FACT_SELECTION_VERSION = "l2-core-fact-selection-v1"


@dataclass(frozen=True, slots=True)
class CoreFactSelection:
    """Outcome for a collision group without changing its raw candidate lineage."""

    selected: Mapping[str, Any] | None
    unavailable_reason: str | None


class CoreQuarterlyFactSelector:
    """Choose one direct common-core fact using only declared mechanical ranks."""

    def select(
        self,
        candidates: Iterable[Mapping[str, Any]],
        *,
        core_canonical_concept_ids: Iterable[str],
    ) -> CoreFactSelection | None:
        """Select a unique winner or retain fail-closed ambiguity.

        The caller supplies one analytical identity group.  Non-core groups
        return ``None`` so their existing governed collision behaviour stays
        unchanged.  Amendments are retained in raw/series lineage but excluded
        from this default selection policy.
        """
        rows = tuple(dict(row) for row in candidates)
        core_ids = {str(value) for value in core_canonical_concept_ids}
        if not rows or str(rows[0].get("company_canonical_concept_id")) not in core_ids:
            return None
        eligible = tuple(row for row in rows if not _is_amendment(row))
        if not eligible:
            return CoreFactSelection(None, "CORE_FACT_SELECTION_AMENDMENT_ONLY")
        direct = tuple(row for row in eligible if _is_direct_10q(row))
        filing_pool = direct or eligible
        representatives = _filing_representatives(filing_pool)
        latest_filing = max(representatives)
        winners = representatives[latest_filing]
        if len(winners) != 1:
            return CoreFactSelection(None, "CORE_FACT_SELECTION_TIE_REVIEW_REQUIRED")
        return CoreFactSelection(winners[0], None)


def _is_direct_10q(row: Mapping[str, Any]) -> bool:
    return str(row.get("form") or "").upper() == "10-Q"


def _filing_rank(row: Mapping[str, Any]) -> tuple[str, str]:
    """Rank raw filings, never individual Fact IDs, so equal facts stay reviewable."""
    return str(row.get("filed_date") or ""), str(row.get("accession") or "")


def _is_undimensioned(row: Mapping[str, Any]) -> bool:
    return row.get("raw_dimension_signature") in (None, (), [])


def _filing_representatives(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[dict[str, Any], ...]]:
    """Keep only each filing's preferred Fact before comparing filing recency.

    This gives the phrase "within the same filing" literal force: dimensions
    decide only between Facts that share a raw filing.  A tied preferred set is
    deliberately retained so a later filing cannot be replaced by an older
    one merely to escape review.
    """
    by_filing: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_filing.setdefault(_filing_rank(row), []).append(dict(row))
    result: dict[tuple[str, str], tuple[dict[str, Any], ...]] = {}
    for filing, candidates in by_filing.items():
        undimensioned = tuple(row for row in candidates if _is_undimensioned(row))
        result[filing] = undimensioned or tuple(candidates)
    return result


def _is_amendment(row: Mapping[str, Any]) -> bool:
    return str(row.get("form") or "").upper().endswith("/A")
