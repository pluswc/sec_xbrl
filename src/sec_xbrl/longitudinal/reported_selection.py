"""Strictly direct-reported, filing-chronology selection views.

``AS_FILED`` selects the first directly reported fact and ``LATEST_REPORTED``
the last directly reported fact for one exact observation scope.  Neither view
asserts recast, comparability, amendment scope, or missing-fact replacement.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

REPORTED_SELECTION_RULE_VERSION = "l2-t4b-direct-reported-selection-v1"
_VIEWS = frozenset({"AS_FILED", "LATEST_REPORTED"})
_LEDGER_LINEAGE_FIELDS = (
    "is_amendment", "amends_accession", "amendment_linkage_state",
    "amendment_linkage_method", "amendment_linkage_review_status",
    "amendment_linkage_evidence", "reported_amendment_ordinal",
    "reported_amendment_ordinal_state", "amendment_flag_state",
    "dei_amendment_flag_raw", "dei_amendment_flag_fact_id",
    "dei_amendment_description_raw", "dei_amendment_description_fact_id",
)


class ReportedObservationSelectionError(RuntimeError):
    """T1 observations and T4-A ledger cannot be safely joined."""


@dataclass(frozen=True, slots=True)
class ReportedObservationIdentity:
    """Full scope within which another direct fact may be selected."""

    cik: str
    concept_identity: tuple[Any, ...]
    dimension_identity: tuple[Any, ...]
    unit_semantics: tuple[tuple[str, ...], tuple[str, ...]]
    actual_period_boundaries: tuple[str | None, str | None, str | None]
    period_class: str

    @classmethod
    def from_observation(cls, row: Mapping[str, Any]) -> ReportedObservationIdentity:
        _require_direct_observation(row)
        return cls(
            cik=str(row["cik"]), concept_identity=_concept_identity(row),
            dimension_identity=_dimension_identity(row), unit_semantics=_unit_semantics(row),
            actual_period_boundaries=_period_boundaries(row), period_class=str(row["period_class"]),
        )


@dataclass(frozen=True, slots=True)
class ReportedObservationSelectionResult:
    view: str
    as_of_date: str
    rows: tuple[dict[str, Any], ...]


class ReportedObservationSelector:
    """Select direct observations using ledger chronology as provenance only."""

    def select_period(
        self,
        *,
        observations: Iterable[Mapping[str, Any]],
        ledger: Iterable[Mapping[str, Any]],
        cik: str,
        fiscal_year: int,
        fiscal_quarter: int | None,
        period_class: str,
        as_of_date: str,
        view: str,
    ) -> ReportedObservationSelectionResult:
        """Return one result for every exact identity found in this period."""
        view = _validate_view(view)
        grouped: dict[ReportedObservationIdentity, list[dict[str, Any]]] = defaultdict(list)
        for source in observations:
            row = dict(source)
            if not _is_direct_observation(row):
                continue
            if (str(row.get("cik") or ""), row.get("fiscal_year"), row.get("fiscal_quarter"), row.get("period_class")) != (cik, fiscal_year, fiscal_quarter, period_class):
                continue
            grouped[ReportedObservationIdentity.from_observation(row)].append(row)
        ledger_by_input = _ledger_index(ledger)
        rows = [
            self._select(identity, candidates, ledger_by_input, as_of_date=as_of_date, view=view)
            for identity, candidates in grouped.items()
        ]
        return ReportedObservationSelectionResult(
            view=view, as_of_date=as_of_date,
            rows=tuple(sorted(rows, key=lambda row: (repr(row["selection_identity"]), str(row.get("source_fact_id") or "")))),
        )

    def select_identity(
        self,
        *,
        observations: Iterable[Mapping[str, Any]],
        ledger: Iterable[Mapping[str, Any]],
        identity: ReportedObservationIdentity,
        as_of_date: str,
        view: str,
    ) -> ReportedObservationSelectionResult:
        """Return an explicit unavailable row if no direct observation exists."""
        view = _validate_view(view)
        candidates = [
            dict(row) for row in observations
            if _is_direct_observation(row) and ReportedObservationIdentity.from_observation(row) == identity
        ]
        row = self._select(identity, candidates, _ledger_index(ledger), as_of_date=as_of_date, view=view)
        return ReportedObservationSelectionResult(view=view, as_of_date=as_of_date, rows=(row,))

    @staticmethod
    def _select(
        identity: ReportedObservationIdentity,
        candidates: Iterable[Mapping[str, Any]],
        ledger_by_input: Mapping[tuple[str, str, str], Mapping[str, Any]],
        *, as_of_date: str, view: str,
    ) -> dict[str, Any]:
        dated: list[dict[str, Any]] = []
        for candidate in candidates:
            _require_direct_observation(candidate)
            ledger_row = _lookup_ledger(candidate, ledger_by_input)
            if str(candidate["filed_date"]) <= as_of_date:
                dated.append({**candidate, **_ledger_lineage(ledger_row)})
        if not dated:
            return {
                "selection_view": view, "selection_as_of_date": as_of_date,
                "selection_rule_version": REPORTED_SELECTION_RULE_VERSION,
                "selection_identity": identity, "selection_status": "UNAVAILABLE",
                "selection_reason": "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION",
                "selection_unavailable_reason": "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION",
                "source_type": "UNAVAILABLE", "selected_source_fact_id": None,
                "selected_accession": None, "comparability_status": "NOT_ASSESSED",
                **_empty_ledger_lineage(),
            }
        ordered = sorted(dated, key=_chronology_key)
        selected = ordered[0] if view == "AS_FILED" else ordered[-1]
        return {
            **selected, "selection_view": view, "selection_as_of_date": as_of_date,
            "selection_rule_version": REPORTED_SELECTION_RULE_VERSION,
            "selection_identity": identity, "selection_status": "SELECTED",
            "selection_reason": "FIRST_ELIGIBLE_DIRECT_REPORTED_OBSERVATION" if view == "AS_FILED" else "LATEST_ELIGIBLE_DIRECT_REPORTED_OBSERVATION",
            "selection_unavailable_reason": None, "source_type": "REPORTED",
            "selected_source_fact_id": selected["source_fact_id"],
            "selected_accession": selected["accession"],
            # Filing chronology is never evidence of recast/comparability.
            "comparability_status": "NOT_ASSESSED",
        }


def _ledger_index(ledger: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in ledger:
        row = dict(source)
        key = (str(row.get("cik") or ""), str(row.get("accession") or ""), str(row.get("source_snapshot_id") or ""))
        if not all(key):
            raise ReportedObservationSelectionError("ledger requires CIK, accession, and source snapshot identity")
        if key in indexed:
            raise ReportedObservationSelectionError("ledger has duplicate filing identity")
        indexed[key] = row
    return indexed


def _lookup_ledger(observation: Mapping[str, Any], index: Mapping[tuple[str, str, str], Mapping[str, Any]]) -> Mapping[str, Any]:
    key = (str(observation.get("cik") or ""), str(observation.get("accession") or ""), str(observation.get("source_snapshot_id") or ""))
    ledger = index.get(key)
    if ledger is None:
        raise ReportedObservationSelectionError("direct observation has no matching accession ledger row")
    for field in ("source_filing_id", "form", "filed_date", "report_date"):
        if str(observation.get(field) or "") != str(ledger.get(field) or ""):
            raise ReportedObservationSelectionError("observation and ledger filing provenance disagree")
    return ledger


def _ledger_lineage(ledger: Mapping[str, Any]) -> dict[str, Any]:
    # Evidence payloads may be nested JSON-like values.  The result must retain
    # them for audit without exposing mutable ledger-owned objects to callers.
    return {
        **{f"ledger_{key}": deepcopy(ledger.get(key)) for key in _LEDGER_LINEAGE_FIELDS},
        "accession_version_ledger_id": deepcopy(ledger.get("accession_version_ledger_id")),
    }


def _empty_ledger_lineage() -> dict[str, Any]:
    """Keep unavailable results schema-compatible without inventing evidence."""
    return {**{f"ledger_{key}": None for key in _LEDGER_LINEAGE_FIELDS}, "accession_version_ledger_id": None}


def _is_direct_observation(row: Mapping[str, Any]) -> bool:
    return row.get("reported_or_derived") == "REPORTED" and bool(row.get("source_fact_id"))


def _require_direct_observation(row: Mapping[str, Any]) -> None:
    if not _is_direct_observation(row):
        raise ReportedObservationSelectionError("selection accepts directly reported observations only")
    required = ("cik", "accession", "source_snapshot_id", "source_filing_id", "filed_date", "period_class", "raw_concept_qname")
    missing = [field for field in required if row.get(field) is None or row.get(field) == ""]
    if missing:
        raise ReportedObservationSelectionError("direct observation missing identity: " + ", ".join(missing))


def _concept_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    # Standard annual taxonomy namespace versions do not break identity;
    # extension/unknown namespace does, unless mapping explicitly normalizes it.
    canonical = row.get("company_canonical_concept_id")
    raw = ("STANDARD", row.get("raw_concept_taxonomy_family"), row.get("raw_concept_qname")) if row.get("raw_concept_is_standard") else ("CUSTOM_OR_UNKNOWN", row.get("raw_concept_namespace_uri"), row.get("raw_concept_qname"))
    return (*raw, "CANONICAL", canonical)


def _dimension_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    # Parquet readers can reconstruct tuple-shaped signatures as nested lists.
    # Freeze recursively before using them in the selection dictionary key.
    canonical = _freeze(row.get("canonical_dimension_signature") or ())
    if canonical and all(axis is not None and (member is not None or typed is not None) for axis, member, typed, *_ in canonical):
        return ("CANONICAL", canonical)
    return ("RAW_FALLBACK", _freeze(row.get("raw_dimension_signature") or row.get("dimension_signature") or ()))


def _unit_semantics(row: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (_measures(row.get("unit_numerator_measures")), _measures(row.get("unit_denominator_measures")))


def _measures(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(sorted(part.strip() for part in value.split() if part.strip()))
    return tuple(sorted(str(part) for part in value))


def _freeze(value: Any) -> Any:
    """Turn decoded Parquet JSON/list signatures into stable hashable keys."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _period_boundaries(row: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    return tuple(None if row.get(key) is None else str(row.get(key)) for key in ("context_start_date", "context_end_date", "context_instant_date"))  # type: ignore[return-value]


def _chronology_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    # Accession is only same-day tie-breaker, not a temporal/ordinal signal.
    return (str(row["filed_date"]), str(row["accession"]), str(row["source_fact_id"]))


def _validate_view(view: str) -> str:
    if view not in _VIEWS:
        raise ReportedObservationSelectionError(f"unsupported reported selection view: {view}")
    return view
