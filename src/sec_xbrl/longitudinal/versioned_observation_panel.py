"""Pre-selection Layer 2 panel for every reported, period-normalized Fact.

This is deliberately not an AS_OF view.  It is the durable hand-off from
immutable filing snapshots to later analysis views: one row per eligible raw
Fact, including originals, amendments, and later comparative presentations.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.canonical import CompanyCanonicalizer
from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import (
    Layer2Publication,
    OperationalLayer2Publisher,
    VerifiedLayer2Publication,
)
from sec_xbrl.longitudinal.period_observation import PeriodObservationMaterializer

VERSIONED_PANEL_RULE_VERSION = "l2-t1-versioned-reported-panel-v1"


class VersionedObservationPanelError(RuntimeError):
    """Raised when a versioned reported-observation panel is unsafe to use."""


@dataclass(frozen=True, slots=True)
class VersionedObservationPanelResult:
    publication: Layer2Publication
    reported_observation_count: int
    exclusion_count: int


class VersionedObservationPanelPipeline:
    """Publish all eligible reported facts without selection, recast, or Q4.

    Canonical IDs are additive lookup metadata.  Raw QName, fact, context,
    unit, dimensions, filing and amendment identity remain on every row.
    """

    def publish(self, release: CorpusRelease, *, output_root: Path) -> VersionedObservationPanelResult:
        if not isinstance(release, CorpusRelease):
            raise VersionedObservationPanelError("T1 requires an explicit CorpusRelease")
        filings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        concepts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dimensions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
        roles: dict[str, list[dict[str, Any]]] = defaultdict(list)
        observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        exclusions: list[dict[str, Any]] = []
        materializer = PeriodObservationMaterializer()

        for snapshot in release.snapshots:
            filing_rows = snapshot.records("filing")
            if len(filing_rows) != 1:
                raise VersionedObservationPanelError("admitted snapshot must have exactly one filing row")
            filing = filing_rows[0]
            cik = snapshot.input.cik
            if str(filing.get("cik") or "") != cik:
                raise VersionedObservationPanelError("snapshot filing CIK disagrees with CorpusRelease")
            result = materializer.materialize(
                filing=filing,
                concepts=snapshot.records("concept"),
                contexts=snapshot.records("context"),
                units=snapshot.records("unit"),
                facts=snapshot.records("fact"),
                dimension_facts=snapshot.records("dimension_fact"),
                q4_policy_by_fact_id=None,
                source_snapshot_id=snapshot.input.snapshot_id,
            )
            filings[cik].append(filing)
            concepts[cik].extend(snapshot.records("concept"))
            dimensions[cik].extend(snapshot.records("dimension_fact"))
            relationships[cik].extend(snapshot.records("relationship"))
            roles[cik].extend(snapshot.records("role"))
            observations[cik].extend(
                {
                    **row,
                    "source_is_amendment": bool(filing.get("is_amendment"))
                    or str(filing.get("form") or "").endswith("/A"),
                    "source_amends_accession": filing.get("amends_accession"),
                }
                for row in result.observations
            )
            exclusions.extend(result.exclusions)

        datasets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        reported_count = 0
        for cik in release.ciks:
            mappings = CompanyCanonicalizer().build(
                filings=filings[cik],
                concepts=concepts[cik],
                dimension_facts=dimensions[cik],
                relationships=relationships[cik],
                roles=roles[cik],
            )
            datasets["company_concept_map"].extend(mappings.company_concept_map)
            datasets["company_axis_map"].extend(mappings.company_axis_map)
            datasets["company_member_map"].extend(mappings.company_member_map)
            concept_map = _map_index(mappings.company_concept_map)
            axis_map = _map_index(mappings.company_axis_map)
            member_map = _map_index(mappings.company_member_map)
            rows = [_panel_row(row, concept_map, axis_map, member_map) for row in observations[cik]]
            datasets["reported_period_observation"].extend(rows)
            reported_count += len(rows)
        if exclusions:
            datasets["period_observation_exclusion"].extend(exclusions)
        publication = OperationalLayer2Publisher(Path(output_root)).publish(
            release.layer2_run, {name: tuple(rows) for name, rows in datasets.items()}
        )
        return VersionedObservationPanelResult(publication, reported_count, len(exclusions))


class VersionedObservationPanelReader:
    """Exact company/FY/Q retrieval that intentionally returns all versions."""

    dataset = "reported_period_observation"

    def get_period(
        self,
        publication: VerifiedLayer2Publication,
        *,
        cik: str,
        fiscal_year: int,
        fiscal_quarter: int | None,
        period_class: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if not publication.is_reader_attested:
            raise VersionedObservationPanelError("versioned panel must be loaded by Layer2PublicationReader")
        if cik not in publication.input_ciks:
            raise VersionedObservationPanelError("requested CIK is outside the verified publication")
        if self.dataset not in publication.datasets:
            raise VersionedObservationPanelError("publication has no versioned reported-observation panel")
        rows = [
            dict(row)
            for row in publication.records(self.dataset)
            if str(row.get("cik")) == cik
            and row.get("fiscal_year") == fiscal_year
            and row.get("fiscal_quarter") == fiscal_quarter
            and (period_class is None or row.get("period_class") == period_class)
        ]
        return tuple(sorted(rows, key=lambda row: (
            str(row.get("filed_date") or ""), str(row.get("accession") or ""),
            str(row.get("source_fact_id") or ""),
        )))


def _map_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("source_filing_id") or ""), str(row.get("source_raw_id") or "")): dict(row)
        for row in rows
    }


def _panel_row(
    observation: Mapping[str, Any],
    concept_map: Mapping[tuple[str, str], Mapping[str, Any]],
    axis_map: Mapping[tuple[str, str], Mapping[str, Any]],
    member_map: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    row = dict(observation)
    if row.get("reported_or_derived") != "REPORTED" or not row.get("source_fact_id"):
        raise VersionedObservationPanelError("T1 can publish only a directly reported Layer 1 Fact")
    filing_id = str(row["source_filing_id"])
    concept = concept_map.get((filing_id, str(row["raw_concept_id"])))
    raw_dimensions = tuple(row.get("dimension_signature") or ())
    canonical_dimensions: list[tuple[Any, ...]] = []
    dimension_mapping_ids: list[tuple[Any, ...]] = []
    review_required = bool(concept and concept.get("review_required")) or concept is None
    for dimension in raw_dimensions:
        axis_raw_id, member_raw_id, typed_member, dimension_type, is_default_member = dimension
        axis = axis_map.get((filing_id, str(axis_raw_id))) if axis_raw_id else None
        member = member_map.get((filing_id, str(member_raw_id))) if member_raw_id else None
        canonical_dimensions.append((
            None if axis is None else axis.get("company_canonical_id"),
            None if member is None else member.get("company_canonical_id"), typed_member,
            dimension_type, is_default_member,
        ))
        dimension_mapping_ids.append((
            None if axis is None else axis.get("mapping_id"),
            None if member is None else member.get("mapping_id"),
        ))
        review_required = review_required or axis is None or bool(axis.get("review_required"))
        review_required = review_required or (member_raw_id is not None and (member is None or bool(member.get("review_required"))))
    return {
        **row,
        "reported_period_observation_id": _id(row["source_snapshot_id"], row["source_fact_id"]),
        "raw_dimension_signature": raw_dimensions,
        "company_canonical_concept_id": None if concept is None else concept.get("company_canonical_id"),
        "concept_mapping_id": None if concept is None else concept.get("mapping_id"),
        "concept_mapping_version": None if concept is None else concept.get("mapping_version"),
        "canonical_dimension_signature": tuple(canonical_dimensions),
        "dimension_mapping_ids": tuple(dimension_mapping_ids),
        "mapping_review_required": review_required,
        "source_version": "AMENDMENT" if row.get("form") in {"10-Q/A", "10-K/A"} else "ORIGINAL",
        "versioned_panel_rule_version": VERSIONED_PANEL_RULE_VERSION,
    }


def _id(snapshot_id: object, fact_id: object) -> str:
    digest = hashlib.sha256(f"{snapshot_id}|{fact_id}|{VERSIONED_PANEL_RULE_VERSION}".encode()).hexdigest()[:24]
    return f"reported-period-observation:{digest}"
