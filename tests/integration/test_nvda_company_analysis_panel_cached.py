"""Cached NVDA proof: selected revenue and Data Center remain separately traceable."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sec_xbrl.analytics import CompanyAnalysisPanelBuilder
from sec_xbrl.longitudinal import (
    AccessionVersionLedgerPipeline,
    AccessionVersionLedgerReader,
    CorpusReleaseAdapter,
    ExplorationGraphPipeline,
    ExplorationGraphReader,
    FilingRelationshipIndexPipeline,
    Layer2PublicationReader,
    Layer2RuleVersions,
    ReportedObservationIdentity,
    ReportedObservationSelector,
    VersionedObservationPanelPipeline,
    VersionedObservationPanelReader,
)


def test_cached_nvda_q3_panel_keeps_revenue_and_data_center_provenance(tmp_path: Path) -> None:
    root = Path(os.environ.get(
        "SEC_XBRL_CORPUS_ROOT",
        "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/trailing_corpus_runs/20260827T051322Z",
    ))
    if not root.is_dir():
        pytest.skip("cached NVDA corpus is not available")
    release = CorpusReleaseAdapter().load(
        root, corpus_run_id=root.name, ciks=("1045810",), run_version="t5-nvda-company-panel-proof-v1",
        rules=Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"),
    )
    t1 = VersionedObservationPanelPipeline().publish(release, output_root=tmp_path / "t1")
    t2 = FilingRelationshipIndexPipeline().publish(release, output_root=tmp_path / "t2")
    graph_result = ExplorationGraphPipeline().publish(
        Layer2PublicationReader().load(t1.publication.run_root),
        Layer2PublicationReader().load(t2.publication.run_root), output_root=tmp_path / "t3",
    )
    graph = Layer2PublicationReader().load(graph_result.publication.run_root)
    ledger_result = AccessionVersionLedgerPipeline().publish(release, output_root=tmp_path / "ledger")
    observations = VersionedObservationPanelReader().get_period(
        Layer2PublicationReader().load(t1.publication.run_root), cik="0001045810", fiscal_year=2024,
        fiscal_quarter=3, period_class="QTD_3M",
    )
    ledger = AccessionVersionLedgerReader().get_company(
        Layer2PublicationReader().load(ledger_result.publication.run_root), cik="0001045810",
    )
    reader = ExplorationGraphReader()
    revenue_root = next(
        row for row in reader.roots_for_fact(graph, cik="0001045810", fiscal_year=2024, fiscal_quarter=3, raw_concept_qname="us-gaap:Revenues")
        if row.get("value_numeric") == "18120000000"
    )
    paths = reader.traverse(graph, root_node_ids=(revenue_root["analysis_exploration_node_id"],))
    selected_by_source = {str(row["source_fact_id"]): row for row in observations}
    data_center_fact = next(
        row["node"]["source_fact_id"] for row in paths
        if row["node"].get("node_kind") == "FACT"
        and row["node"].get("source_fact_id")
        and any(node_id == row["node"]["analysis_exploration_node_id"] for node_id in row["path_node_ids"])
        and any(
            item["node"].get("raw_qname") == "nvda:DataCenterMember"
            for item in paths if item["node"]["analysis_exploration_node_id"] in row["path_node_ids"]
        )
        and row["node"]["source_fact_id"] in selected_by_source
    )
    selector = ReportedObservationSelector()
    chosen = tuple(
        selector.select_identity(
            observations=observations, ledger=ledger,
            identity=ReportedObservationIdentity.from_observation(selected_by_source[source_fact_id]),
            as_of_date="2023-11-21", view="LATEST_REPORTED",
        ).rows[0]
        for source_fact_id in (str(revenue_root["source_fact_id"]), data_center_fact)
    )
    panel = CompanyAnalysisPanelBuilder().build(
        selected_rows=chosen, exploration=graph, cik="0001045810", fiscal_year=2024, fiscal_quarter=3,
        period_class="QTD_3M", view="LATEST_REPORTED", as_of_date="2023-11-21", analysis_view_id="nvda-q3-proof",
    )
    assert all(row["selection_status"] == "SELECTED" for row in chosen)
    assert any(row["label"] == "us-gaap:Revenues" and row["line_class"] == "COMMON_GAAP" for row in panel.definitions), panel.definitions
    assert any(row["label"] == "nvda:DataCenterMember" and row["line_class"] == "COMPANY_CUSTOM" for row in panel.definitions)
    detail = next(row for row in panel.values if row["selected_source_fact_id"] == data_center_fact)
    assert detail["accession"] == "0001045810-23-000227"
    assert detail["source_snapshot_id"] and detail["context_id"] and detail["unit_id"]
    assert detail["ledger_lineage"]["ledger_amendment_linkage_state"] == "NOT_APPLICABLE"
