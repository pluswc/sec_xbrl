from __future__ import annotations

import os
from pathlib import Path

import pytest

from sec_xbrl.longitudinal import (
    CorpusReleaseAdapter,
    ExplorationGraphPipeline,
    ExplorationGraphReader,
    FilingRelationshipIndexPipeline,
    Layer2PublicationReader,
    Layer2RuleVersions,
    VersionedObservationPanelPipeline,
)


def test_cached_nvda_q3_revenue_has_parallel_standard_and_custom_lenses(tmp_path: Path) -> None:
    root = Path(os.environ.get(
        "SEC_XBRL_CORPUS_ROOT",
        "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/trailing_corpus_runs/20260827T051322Z",
    ))
    if not root.is_dir():
        pytest.skip("cached NVDA corpus is not available")
    release = CorpusReleaseAdapter().load(
        root,
        corpus_run_id=root.name,
        ciks=("1045810",),
        run_version="t3-nvda-exploration-regression-v1",
        rules=Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"),
    )
    t1 = VersionedObservationPanelPipeline().publish(release, output_root=tmp_path / "t1")
    t2 = FilingRelationshipIndexPipeline().publish(release, output_root=tmp_path / "t2")
    result = ExplorationGraphPipeline().publish(
        Layer2PublicationReader().load(t1.publication.run_root),
        Layer2PublicationReader().load(t2.publication.run_root),
        output_root=tmp_path / "t3",
    )
    publication = Layer2PublicationReader().load(result.publication.run_root)
    reader = ExplorationGraphReader()
    roots = reader.roots_for_fact(
        publication, cik="0001045810", fiscal_year=2024, fiscal_quarter=3,
        raw_concept_qname="us-gaap:Revenues",
    )
    total = next(row for row in roots if row.get("value_numeric") == "18120000000")
    assert total["accession"] == "0001045810-23-000227"
    assert total["context_id"] and total["unit_id"] and total["source_fact_id"]
    paths = reader.traverse(publication, root_node_ids=(total["analysis_exploration_node_id"],), max_depth=2)
    nodes = [item["node"] for item in paths]
    assert {
        node["raw_qname"] for node in nodes if node["node_kind"] == "AXIS"
    } >= {
        "srt:StatementGeographicalAxis", "us-gaap:StatementBusinessSegmentsAxis",
        "srt:ProductOrServiceAxis",
    }
    assert any(
        node["origin"] == "CUSTOM_MEMBER" and node["raw_qname"] == "nvda:DataCenterMember"
        for node in nodes
    )
    assert any(
        node["origin"] == "CUSTOM_MEMBER" and node["raw_qname"] == "nvda:ComputeAndNetworkingMember"
        for node in nodes
    )
