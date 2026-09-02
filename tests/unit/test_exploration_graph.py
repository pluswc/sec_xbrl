from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    CorpusRelease,
    CorpusSnapshot,
    ExplorationGraphPipeline,
    ExplorationGraphReader,
    FilingRelationshipIndexPipeline,
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
    OperationalLayer2Publisher,
    VersionedObservationPanelPipeline,
)


def _release() -> CorpusRelease:
    cik, accession, filing_id = "0000320193", "0000320193-25-000001", "filing:one"
    revenue, geography, product = "concept:revenue", "axis:geography", "axis:product"
    us, cloud = "member:us", "member:cloud"
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik, "accession": accession, "form": "10-Q", "filed_date": "2025-05-01", "report_date": "2025-03-29", "document_fiscal_year_focus": "2025", "document_fiscal_period_focus": "Q1", "is_amendment": False},),
        "concept": (
            {"filing_id": filing_id, "raw_concept_id": revenue, "qname": "us-gaap:Revenues", "namespace_uri": "http://fasb.org/us-gaap/2024", "taxonomy_family": "us-gaap", "taxonomy_version": "2024", "local_name": "Revenues", "period_type": "duration", "data_type": "monetaryItemType", "is_standard": True, "is_custom": False},
            {"filing_id": filing_id, "raw_concept_id": geography, "qname": "srt:StatementGeographicalAxis", "namespace_uri": "http://fasb.org/srt/2024", "taxonomy_family": "srt", "taxonomy_version": "2024", "local_name": "StatementGeographicalAxis", "period_type": "duration", "data_type": "stringItemType", "is_standard": True, "is_custom": False},
            {"filing_id": filing_id, "raw_concept_id": us, "qname": "country:US", "namespace_uri": "http://xbrl.sec.gov/country/2024", "taxonomy_family": "country", "taxonomy_version": "2024", "local_name": "US", "period_type": "duration", "data_type": "stringItemType", "is_standard": True, "is_custom": False},
            {"filing_id": filing_id, "raw_concept_id": product, "qname": "acme:ProductAxis", "namespace_uri": "http://example.com/acme/2025", "taxonomy_family": "company-extension", "taxonomy_version": "2025", "local_name": "ProductAxis", "period_type": "duration", "data_type": "stringItemType", "is_standard": False, "is_custom": True},
            {"filing_id": filing_id, "raw_concept_id": cloud, "qname": "acme:CloudMember", "namespace_uri": "http://example.com/acme/2025", "taxonomy_family": "company-extension", "taxonomy_version": "2025", "local_name": "CloudMember", "period_type": "duration", "data_type": "stringItemType", "is_standard": False, "is_custom": True},
        ),
        "context": ({"filing_id": filing_id, "context_id": "qtd", "period_kind": "DURATION", "start_date": "2024-12-29", "end_date": "2025-03-29", "instant_date": None, "duration_days": 91},),
        "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
        "fact": (
            {"filing_id": filing_id, "fact_id": "fact:total", "raw_concept_id": revenue, "context_id": "qtd", "unit_id": "usd", "value_numeric": "100", "value_text": None, "is_nil": False, "source_document": "report.htm", "source_locator": "table:1"},
            {"filing_id": filing_id, "fact_id": "fact:us", "raw_concept_id": revenue, "context_id": "qtd", "unit_id": "usd", "value_numeric": "60", "value_text": None, "is_nil": False, "source_document": "note.htm", "source_locator": "table:geo"},
            {"filing_id": filing_id, "fact_id": "fact:cloud", "raw_concept_id": revenue, "context_id": "qtd", "unit_id": "usd", "value_numeric": "70", "value_text": None, "is_nil": False, "source_document": "note.htm", "source_locator": "table:product"},
        ),
        "dimension_fact": (
            {"filing_id": filing_id, "fact_id": "fact:us", "axis_raw_concept_id": geography, "member_raw_concept_id": us, "typed_member": None, "dimension_type": "EXPLICIT", "is_default_member": False},
            {"filing_id": filing_id, "fact_id": "fact:cloud", "axis_raw_concept_id": product, "member_raw_concept_id": cloud, "typed_member": None, "dimension_type": "EXPLICIT", "is_default_member": False},
        ),
        "role": ({"filing_id": filing_id, "role_id": "role:income", "role_uri": "http://example.com/role/income", "role_definition": "Income", "role_category": "STATEMENT"},),
        "relationship": (
            {"filing_id": filing_id, "relationship_id": "rel:pre", "network_type": "PRE", "role_id": "role:income", "arcrole": "parent-child", "link_qname": "link:presentationLink", "arc_qname": "link:presentationArc", "from_raw_concept_id": revenue, "to_raw_concept_id": cloud, "order": "1", "weight": None, "preferred_label": None, "target_role_uri": None, "usable": None, "closed": None, "context_element": None},
            {"filing_id": filing_id, "relationship_id": "rel:cal", "network_type": "CAL", "role_id": "role:income", "arcrole": "summation-item", "link_qname": "link:calculationLink", "arc_qname": "link:calculationArc", "from_raw_concept_id": revenue, "to_raw_concept_id": cloud, "order": "2", "weight": "1", "preferred_label": None, "target_role_uri": "http://example.com/role/detail", "usable": None, "closed": None, "context_element": None},
            {"filing_id": filing_id, "relationship_id": "rel:def", "network_type": "DEF", "role_id": "role:income", "arcrole": "domain-member", "link_qname": "link:definitionLink", "arc_qname": "link:definitionArc", "from_raw_concept_id": product, "to_raw_concept_id": cloud, "order": "3", "weight": None, "preferred_label": None, "target_role_uri": None, "usable": True, "closed": False, "context_element": "segment"},
        ),
    }
    manifest = Layer1SnapshotManifest(1, cik, accession, "10-Q", "fixture", "a" * 64, "fixture", 1, 5, 1, 1, 3, 2, 1, 3, "fixture", "fixture")
    input_row = Layer1SnapshotInput(cik, accession, "10-Q", "2025-05-01", "2025-03-29", "snap:one", hashlib.sha256(accession.encode()).hexdigest())
    snapshot = CorpusSnapshot(input_row, manifest, Path("/fixture/layer1_manifest.json"), MappingProxyType({}), MappingProxyType({name: len(rows) for name, rows in tables.items()}), MappingProxyType({name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}))
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    return CorpusRelease(Path("/fixture"), "fixture", (cik,), (snapshot,), Layer2Run("t3-exploration-fixture-v1", "fixture", (input_row,), rules))


def test_t3_keeps_independent_lenses_and_network_evidence(tmp_path: Path) -> None:
    release = _release()
    t1 = VersionedObservationPanelPipeline().publish(release, output_root=tmp_path / "t1")
    t2 = FilingRelationshipIndexPipeline().publish(release, output_root=tmp_path / "t2")
    result = ExplorationGraphPipeline().publish(
        Layer2PublicationReader().load(t1.publication.run_root),
        Layer2PublicationReader().load(t2.publication.run_root), output_root=tmp_path / "t3",
    )
    publication = Layer2PublicationReader().load(result.publication.run_root)
    reader = ExplorationGraphReader()
    roots = reader.roots_for_fact(publication, cik="0000320193", fiscal_year=2025, fiscal_quarter=1, raw_concept_qname="us-gaap:Revenues")
    total = next(row for row in roots if row["source_fact_id"] == "fact:total")
    paths = reader.traverse(publication, root_node_ids=(total["analysis_exploration_node_id"],), max_depth=4)
    edges = [row["incoming_edge"] for row in paths if row["incoming_edge"]]
    assert {edge["edge_kind"] for edge in edges} >= {"DIMENSION_LENS", "FACT_SCOPE"}
    lens_edges = [edge for edge in edges if edge["edge_kind"] == "DIMENSION_LENS"]
    assert len(lens_edges) == 2
    descendants = [row["node"] for row in paths]
    assert any(row["node_kind"] == "MEMBER" and row["origin"] == "CUSTOM_MEMBER" and row["raw_qname"] == "acme:CloudMember" for row in descendants)
    graph_edges = publication.records(reader.edge_dataset)
    statement = [row for row in graph_edges if row["edge_kind"] == "STATEMENT_COMPONENT"]
    assert {row["source_network_type"] for row in statement} == {"PRE", "CAL"}
    assert all(row["role_uri"] == "http://example.com/role/income" for row in statement)
    assert any(row["edge_kind"] == "MEMBER_HIERARCHY" and row["source_network_type"] == "DEF" for row in graph_edges)
    assert result.node_count and result.edge_count


def test_reader_keeps_alternative_paths_but_stops_a_cycle(tmp_path: Path) -> None:
    release = _release()
    cik = "0000320193"
    node_a, node_b = "node:a", "node:b"
    published = OperationalLayer2Publisher(tmp_path / "graph").publish(release.layer2_run, {
        "analysis_exploration_node": (
            {"cik": cik, "analysis_exploration_node_id": node_a, "node_kind": "CONCEPT", "origin": "STANDARD_CONCEPT", "raw_id": "a", "raw_qname": "us-gaap:A"},
            {"cik": cik, "analysis_exploration_node_id": node_b, "node_kind": "CONCEPT", "origin": "CUSTOM_CONCEPT", "raw_id": "b", "raw_qname": "acme:B"},
        ),
        "analysis_exploration_edge": (
            {"cik": cik, "analysis_exploration_edge_id": "edge:one", "edge_kind": "DIMENSION_LENS", "from_node_id": node_a, "to_node_id": node_b},
            {"cik": cik, "analysis_exploration_edge_id": "edge:two", "edge_kind": "FACT_SCOPE", "from_node_id": node_a, "to_node_id": node_b},
            {"cik": cik, "analysis_exploration_edge_id": "edge:cycle", "edge_kind": "DIMENSION_LENS", "from_node_id": node_b, "to_node_id": node_a},
        ),
    })
    rows = ExplorationGraphReader().traverse(
        Layer2PublicationReader().load(published.run_root), root_node_ids=(node_a,)
    )
    assert len(rows) == 3  # root + two alternative A→B paths; B→A is cycle-stopped.
    assert [row["node"]["analysis_exploration_node_id"] for row in rows].count(node_b) == 2
