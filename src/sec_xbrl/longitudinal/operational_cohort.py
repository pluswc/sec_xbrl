"""Declared, reproducible operational cohort releases.

The five-company reference cohort intentionally joins already immutable Layer
1 snapshots from two source runs.  It validates those source snapshots in
place through ``CohortReleaseAdapter`` and then invokes the normal T1--T4
publishers; it never creates a synthetic Layer 1 run or copies raw records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sec_xbrl.longitudinal.accession_version_ledger import AccessionVersionLedgerPipeline
from sec_xbrl.longitudinal.corpus_release import (
    CohortReleaseAdapter,
    CohortSnapshotReference,
    CohortSource,
    CorpusRelease,
)
from sec_xbrl.longitudinal.exploration_graph import ExplorationGraphPipeline
from sec_xbrl.longitudinal.materialization import Layer2PublicationReader, Layer2RuleVersions
from sec_xbrl.longitudinal.relationship_index import FilingRelationshipIndexPipeline
from sec_xbrl.longitudinal.versioned_observation_panel import VersionedObservationPanelPipeline

FIVE_COMPANY_REFERENCE_COHORT_ID = "five-company-reference-2024q3-v1"
FIVE_COMPANY_REFERENCE_CIKS = (
    "0000002488",
    "0000320193",
    "0000789019",
    "0001018724",
    "0001045810",
)
FIVE_COMPANY_REFERENCE_RULES = Layer2RuleVersions(
    "period-v1", "mapping-v1", "recast-v1", "selection-v1"
)


@dataclass(frozen=True, slots=True)
class FiveCompanyOperationalCohortResult:
    """Verified source declaration and the four separately published roots."""

    release: CorpusRelease
    reported_observations_root: Path
    relationships_root: Path
    exploration_graph_root: Path
    accession_ledger_root: Path
    reported_observation_count: int
    relationship_edge_count: int
    exploration_node_count: int
    exploration_edge_count: int
    filing_count: int


def five_company_reference_release(data_root: Path) -> CorpusRelease:
    """Load the exact five reference filings named in the validation pack."""
    data_root = Path(data_root)
    legacy_run = data_root / "processed/trailing_corpus_runs/20260827T051322Z"
    intake_run = data_root / "processed/operational_cohort_runs/20260906T020000Z_msft_amzn_2024q3"
    return CohortReleaseAdapter().load(
        (
            CohortSource(
                legacy_run,
                legacy_run.name,
                (
                    CohortSnapshotReference("0001045810", "0001045810-24-000316"),
                    CohortSnapshotReference("0000002488", "0000002488-24-000163"),
                    CohortSnapshotReference("0000320193", "0000320193-24-000123"),
                ),
            ),
            CohortSource(
                intake_run,
                intake_run.name,
                (
                    CohortSnapshotReference("0000789019", "0000950170-24-118967"),
                    CohortSnapshotReference("0001018724", "0001018724-24-000161"),
                ),
            ),
        ),
        cohort_id=FIVE_COMPANY_REFERENCE_COHORT_ID,
        ciks=FIVE_COMPANY_REFERENCE_CIKS,
        run_version=FIVE_COMPANY_REFERENCE_COHORT_ID,
        rules=FIVE_COMPANY_REFERENCE_RULES,
    )


def publish_five_company_reference_cohort(
    *, data_root: Path, output_root: Path
) -> FiveCompanyOperationalCohortResult:
    """Publish T1--T4 operational Parquet roots from the declared cohort."""
    release = five_company_reference_release(data_root)
    output_root = Path(output_root)
    t1 = VersionedObservationPanelPipeline().publish(release, output_root=output_root / "t1")
    t2 = FilingRelationshipIndexPipeline().publish(release, output_root=output_root / "t2")
    graph = ExplorationGraphPipeline().publish(
        Layer2PublicationReader().load(t1.publication.run_root),
        Layer2PublicationReader().load(t2.publication.run_root),
        output_root=output_root / "t3",
    )
    ledger = AccessionVersionLedgerPipeline().publish(release, output_root=output_root / "t4")
    return FiveCompanyOperationalCohortResult(
        release=release,
        reported_observations_root=t1.publication.run_root,
        relationships_root=t2.publication.run_root,
        exploration_graph_root=graph.publication.run_root,
        accession_ledger_root=ledger.publication.run_root,
        reported_observation_count=t1.reported_observation_count,
        relationship_edge_count=t2.edge_count,
        exploration_node_count=graph.node_count,
        exploration_edge_count=graph.edge_count,
        filing_count=ledger.filing_count,
    )
