"""C3-M1 deterministic, as-filed Layer 2 publication orchestration.

This module composes the existing governed Layer 2 producers.  It deliberately
does not add a new mapping, selection, Q4, recast, or Metric policy.  In
particular, its only durable consumer view is ``AS_FILED``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.canonical import CompanyCanonicalizer, MappingTables
from sec_xbrl.longitudinal.capability import CapabilityInventoryMaterializer
from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import Layer2Publication, Layer2Publisher
from sec_xbrl.longitudinal.period_observation import PeriodObservationMaterializer
from sec_xbrl.longitudinal.selection import AnalyticalFactMaterializer
from sec_xbrl.longitudinal.series import CompanySeriesMaterializer


class AsFiledPublicationError(RuntimeError):
    """Raised when a CorpusRelease cannot safely become an AS_FILED publication."""


@dataclass(frozen=True, slots=True)
class CompanyCoverage:
    """Consumer-safe materialization coverage, never a disclosure assertion."""

    cik: str
    filing_count: int
    observed_analytical_fact_count: int
    period_observation_exclusion_count: int
    series_candidate_exclusion_count: int
    capability_count: int
    period_classes: tuple[str, ...]
    views: tuple[str, ...]
    source_type_counts: Mapping[str, int]
    capability_status_counts: Mapping[str, int]

    @property
    def has_observed_or_explicit_coverage(self) -> bool:
        return bool(
            self.observed_analytical_fact_count
            or self.period_observation_exclusion_count
            or self.series_candidate_exclusion_count
            or self.capability_count
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "filing_count": self.filing_count,
            "observed_analytical_fact_count": self.observed_analytical_fact_count,
            "period_observation_exclusion_count": self.period_observation_exclusion_count,
            "series_candidate_exclusion_count": self.series_candidate_exclusion_count,
            "capability_count": self.capability_count,
            "period_classes": self.period_classes,
            "views": self.views,
            "source_type_counts": dict(self.source_type_counts),
            "capability_status_counts": dict(self.capability_status_counts),
            "coverage_status": (
                "OBSERVED_OR_EXPLICIT_UNAVAILABLE"
                if self.has_observed_or_explicit_coverage
                else "NO_MATERIALIZED_COVERAGE"
            ),
        }


@dataclass(frozen=True, slots=True)
class AsFiledPublicationResult:
    """Atomic output plus a read-only coverage summary for consumers."""

    publication: Layer2Publication
    coverage: tuple[CompanyCoverage, ...]

    @property
    def coverage_by_cik(self) -> Mapping[str, CompanyCoverage]:
        return {row.cik: row for row in self.coverage}


class AsFiledPublicationPipeline:
    """Compose existing L2-M1 through L2-M5 components for one release.

    The release carries the complete immutable run declaration.  ``as_of_date``
    is explicit because it is selection policy input, not a display filter.
    Callers cannot inject a Q4 policy, recast evidence, or comparable view here.
    """

    def publish(
        self,
        release: CorpusRelease,
        *,
        output_root: Path,
        as_of_date: str,
    ) -> AsFiledPublicationResult:
        _validate_as_of_date(as_of_date)
        if not isinstance(release, CorpusRelease):
            raise AsFiledPublicationError("C3-M1 requires an explicit CorpusRelease")

        observations_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        exclusions_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        filings_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        concepts_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dimensions_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        relationships_by_cik: dict[str, list[dict[str, Any]]] = defaultdict(list)
        evidence_by_fact_id: dict[str, dict[str, Any]] = {}

        period_materializer = PeriodObservationMaterializer()
        for snapshot in release.snapshots:
            filing_rows = snapshot.records("filing")
            if len(filing_rows) != 1:
                raise AsFiledPublicationError("admitted CorpusRelease snapshot must have one filing row")
            filing = filing_rows[0]
            if str(filing.get("cik")) != snapshot.input.cik:
                raise AsFiledPublicationError("CorpusRelease filing CIK does not match declared snapshot")
            result = period_materializer.materialize(
                filing=filing,
                concepts=snapshot.records("concept"),
                contexts=snapshot.records("context"),
                units=snapshot.records("unit"),
                facts=snapshot.records("fact"),
                dimension_facts=snapshot.records("dimension_fact"),
                # C3-M1 must not enable new derived Q4 policy.
                q4_policy_by_fact_id=None,
                source_snapshot_id=snapshot.input.snapshot_id,
            )
            cik = snapshot.input.cik
            observations_by_cik[cik].extend(result.observations)
            exclusions_by_cik[cik].extend(result.exclusions)
            filings_by_cik[cik].append(filing)
            concepts_by_cik[cik].extend(snapshot.records("concept"))
            dimensions_by_cik[cik].extend(snapshot.records("dimension_fact"))
            relationships = snapshot.records("relationship")
            relationships_by_cik[cik].extend(relationships)
            evidence_by_fact_id.update(_role_evidence(snapshot.records("fact"), relationships))

        datasets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        all_analytical: list[dict[str, Any]] = []
        all_capabilities: list[dict[str, Any]] = []
        all_series_exclusions: list[dict[str, Any]] = []
        all_observations: list[dict[str, Any]] = []
        all_period_exclusions: list[dict[str, Any]] = []
        for cik in release.ciks:
            mappings = CompanyCanonicalizer().build(
                filings=filings_by_cik[cik],
                concepts=concepts_by_cik[cik],
                dimension_facts=dimensions_by_cik[cik],
                relationships=relationships_by_cik[cik],
            )
            _append_mapping_datasets(datasets, mappings)
            snapshots = tuple(item for item in release.snapshots if item.input.cik == cik)
            snapshot_by_filing = {
                str(item.records("filing")[0]["filing_id"]): item.input.snapshot_id for item in snapshots
            }
            series = CompanySeriesMaterializer().materialize(
                observations=observations_by_cik[cik],
                mappings=mappings,
                declared_snapshot_ids=(item.input.snapshot_id for item in snapshots),
                snapshot_id_by_filing_id=snapshot_by_filing,
            )
            # CURRENT candidates are the governed input family containing both
            # 10-K and 10-Q.  Annual candidates remain published separately;
            # they are not a duplicate AS_FILED selection family here.
            selected = AnalyticalFactMaterializer().materialize(
                current_candidates=series.current,
                as_of_date=as_of_date,
            )
            as_filed = _resolve_as_filed_identity_collisions(
                row for row in selected.analytical_facts if row.get("view") == "AS_FILED"
            )
            if any(row.get("view") != "AS_FILED" for row in as_filed):
                raise AsFiledPublicationError("C3-M1 emitted a non-AS_FILED analytical fact")
            capabilities = CapabilityInventoryMaterializer().materialize(
                company_ciks=(cik,),
                series_candidates=series.current,
                analytical_facts=as_filed,
                processing_exclusions=(*exclusions_by_cik[cik], *series.exclusions),
                source_evidence_by_fact_id=evidence_by_fact_id,
            )
            datasets["annual_series_candidate"].extend(series.annual)
            datasets["current_series_candidate"].extend(series.current)
            datasets["series_candidate_exclusion"].extend(series.exclusions)
            datasets["analytical_fact"].extend(as_filed)
            datasets["capability_inventory"].extend(capabilities.inventory)
            all_observations.extend(observations_by_cik[cik])
            all_period_exclusions.extend(exclusions_by_cik[cik])
            all_series_exclusions.extend(series.exclusions)
            all_analytical.extend(as_filed)
            all_capabilities.extend(capabilities.inventory)

        datasets["period_observation"].extend(all_observations)
        datasets["period_observation_exclusion"].extend(all_period_exclusions)
        # deterministic rows make the publisher's content hash meaningful.
        publication = Layer2Publisher(Path(output_root)).publish(
            release.layer2_run, {name: tuple(_sorted_rows(rows)) for name, rows in datasets.items()}
        )
        return AsFiledPublicationResult(
            publication=publication,
            coverage=_coverage(
                release,
                observations=all_observations,
                period_exclusions=all_period_exclusions,
                series_exclusions=all_series_exclusions,
                analytical_facts=all_analytical,
                capabilities=all_capabilities,
            ),
        )


def _append_mapping_datasets(target: dict[str, list[dict[str, Any]]], mappings: MappingTables) -> None:
    for name, rows in mappings.as_datasets().items():
        target[name].extend(rows)


def _resolve_as_filed_identity_collisions(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Fail closed when the existing M4 identity cannot distinguish candidates.

    M4 selection preserves source rows; its durable analytical ID intentionally
    represents the consumer grain.  Some raw filings contain more than one
    selected source row at that grain (for example, unit variants).  C3-M1
    must not pick one based on input order.  The competing source rows remain
    in the published series candidates; the consumer-facing row becomes an
    explicit unavailable result.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("analytical_fact_id") or "")].append(dict(row))
    result: list[dict[str, Any]] = []
    for identity, candidates in sorted(grouped.items()):
        if not identity:
            raise AsFiledPublicationError("AS_FILED materializer returned a fact without identity")
        canonical = min(candidates, key=lambda row: repr(sorted(row.items())))
        if len(candidates) == 1:
            result.append(canonical)
            continue
        result.append(
            {
                **canonical,
                "source_type": "UNAVAILABLE",
                "value_numeric": None,
                "value_text": None,
                "selected_fact_id": None,
                "source_filing_id": None,
                "filed_date": None,
                "unavailable_reason": "AMBIGUOUS_AS_FILED_SELECTION_IDENTITY",
            }
        )
    return tuple(result)


def _role_evidence(
    facts: Iterable[Mapping[str, Any]], relationships: Iterable[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Copy only direct raw relationship role provenance; never infer a disclosure."""
    roles_by_concept: dict[str, set[str]] = defaultdict(set)
    for relationship in relationships:
        role_id = relationship.get("role_id")
        if not role_id:
            continue
        for key in ("from_raw_concept_id", "to_raw_concept_id"):
            concept = relationship.get(key)
            if concept:
                roles_by_concept[str(concept)].add(str(role_id))
    result: dict[str, dict[str, Any]] = {}
    for fact in facts:
        fact_id, concept = fact.get("fact_id"), fact.get("raw_concept_id")
        if fact_id and concept and roles_by_concept.get(str(concept)):
            result[str(fact_id)] = {"source_role_ids": tuple(sorted(roles_by_concept[str(concept)]))}
    return result


def _coverage(
    release: CorpusRelease,
    *,
    observations: Iterable[Mapping[str, Any]],
    period_exclusions: Iterable[Mapping[str, Any]],
    series_exclusions: Iterable[Mapping[str, Any]],
    analytical_facts: Iterable[Mapping[str, Any]],
    capabilities: Iterable[Mapping[str, Any]],
) -> tuple[CompanyCoverage, ...]:
    observation_rows = tuple(observations)
    period_exclusion_rows = tuple(period_exclusions)
    series_exclusion_rows = tuple(series_exclusions)
    fact_rows = tuple(analytical_facts)
    capability_rows = tuple(capabilities)
    output: list[CompanyCoverage] = []
    for cik in release.ciks:
        facts = [row for row in fact_rows if row.get("cik") == cik]
        caps = [row for row in capability_rows if row.get("cik") == cik]
        output.append(
            CompanyCoverage(
                cik=cik,
                filing_count=sum(1 for item in release.snapshots if item.input.cik == cik),
                observed_analytical_fact_count=len(facts),
                period_observation_exclusion_count=sum(1 for row in period_exclusion_rows if row.get("cik") == cik),
                series_candidate_exclusion_count=sum(1 for row in series_exclusion_rows if row.get("cik") == cik),
                capability_count=len(caps),
                period_classes=tuple(sorted({str(row["period_class"]) for row in observation_rows if row.get("cik") == cik and row.get("period_class")})),
                views=tuple(sorted({str(row["view"]) for row in facts if row.get("view")})),
                source_type_counts=dict(sorted(Counter(str(row.get("source_type")) for row in facts).items())),
                capability_status_counts=dict(sorted(Counter(str(row.get("capability_status")) for row in caps).items())),
            )
        )
    return tuple(output)


def _sorted_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in sorted(rows, key=lambda row: repr(sorted(dict(row).items())))]


def _validate_as_of_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AsFiledPublicationError("as_of_date must be an ISO-8601 date") from exc
