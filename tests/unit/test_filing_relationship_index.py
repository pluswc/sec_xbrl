from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    CorpusRelease,
    CorpusSnapshot,
    FilingRelationshipIndexPipeline,
    FilingRelationshipIndexReader,
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
)


def _release() -> CorpusRelease:
    cik, accession, filing_id = "0000320193", "0000320193-25-000001", "filing:one"
    revenue, product = "concept:revenue", "concept:product"
    tables = {
        "filing": (
            {
                "filing_id": filing_id,
                "cik": cik,
                "accession": accession,
                "form": "10-Q",
                "filed_date": "2025-05-01",
                "report_date": "2025-03-29",
                "is_amendment": False,
            },
        ),
        "concept": (
            {
                "filing_id": filing_id,
                "raw_concept_id": revenue,
                "qname": "us-gaap:Revenue",
                "namespace_uri": "http://fasb.org/us-gaap/2024",
                "taxonomy_family": "us-gaap",
                "taxonomy_version": "2024",
                "local_name": "Revenue",
                "period_type": "duration",
                "data_type": "monetaryItemType",
                "is_standard": True,
                "is_custom": False,
            },
            {
                "filing_id": filing_id,
                "raw_concept_id": product,
                "qname": "acme:ProductRevenue",
                "namespace_uri": "http://example.com/acme/2025",
                "taxonomy_family": "company-extension",
                "taxonomy_version": "2025",
                "local_name": "ProductRevenue",
                "period_type": "duration",
                "data_type": "monetaryItemType",
                "is_standard": False,
                "is_custom": True,
            },
        ),
        "context": (),
        "unit": (),
        "fact": (),
        "dimension_fact": (),
        "role": (
            {
                "filing_id": filing_id,
                "role_id": "role:income",
                "role_uri": "http://example.com/role/income",
                "role_definition": "Income Statement",
                "role_category": "STATEMENT",
            },
        ),
        "relationship": (
            {
                "filing_id": filing_id,
                "relationship_id": "rel:pre",
                "network_type": "PRE",
                "role_id": "role:income",
                "arcrole": "parent-child",
                "link_qname": "link:presentationLink",
                "arc_qname": "link:presentationArc",
                "from_raw_concept_id": revenue,
                "to_raw_concept_id": product,
                "order": "1",
                "weight": None,
                "preferred_label": "label",
                "target_role_uri": None,
                "usable": None,
                "closed": None,
                "context_element": None,
            },
            {
                "filing_id": filing_id,
                "relationship_id": "rel:cal",
                "network_type": "CAL",
                "role_id": "role:income",
                "arcrole": "summation-item",
                "link_qname": "link:calculationLink",
                "arc_qname": "link:calculationArc",
                "from_raw_concept_id": revenue,
                "to_raw_concept_id": product,
                "order": "2",
                "weight": "1",
                "preferred_label": None,
                "target_role_uri": "http://example.com/role/detail",
                "usable": None,
                "closed": None,
                "context_element": None,
            },
            {
                "filing_id": filing_id,
                "relationship_id": "rel:def",
                "network_type": "DEF",
                "role_id": "role:income",
                "arcrole": "domain-member",
                "link_qname": "link:definitionLink",
                "arc_qname": "link:definitionArc",
                "from_raw_concept_id": revenue,
                "to_raw_concept_id": product,
                "order": "3",
                "weight": None,
                "preferred_label": None,
                "target_role_uri": None,
                "usable": True,
                "closed": False,
                "context_element": "segment",
            },
        ),
    }
    manifest = Layer1SnapshotManifest(
        1,
        cik,
        accession,
        "10-Q",
        "fixture",
        "a" * 64,
        "fixture",
        1,
        2,
        0,
        0,
        0,
        0,
        1,
        3,
        "fixture",
        "fixture",
    )
    input_row = Layer1SnapshotInput(
        cik,
        accession,
        "10-Q",
        "2025-05-01",
        "2025-03-29",
        "snap:one",
        hashlib.sha256(accession.encode()).hexdigest(),
    )
    frozen = MappingProxyType(
        {name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}
    )
    snapshot = CorpusSnapshot(
        input_row,
        manifest,
        Path("/fixture/one/layer1_manifest.json"),
        MappingProxyType({}),
        MappingProxyType({name: len(rows) for name, rows in tables.items()}),
        frozen,
    )
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    return CorpusRelease(
        Path("/fixture"),
        "fixture",
        (cik,),
        (snapshot,),
        Layer2Run("t2-relationship-fixture-v1", "fixture", (input_row,), rules),
    )


def test_t2_preserves_network_and_raw_canonical_endpoint_lineage(tmp_path: Path) -> None:
    result = FilingRelationshipIndexPipeline().publish(_release(), output_root=tmp_path / "layer2")
    publication = Layer2PublicationReader().load(result.publication.run_root)
    rows = FilingRelationshipIndexReader().get_filing(
        publication, cik="0000320193", accession="0000320193-25-000001"
    )
    assert result.edge_count == 3
    assert [row["network_type"] for row in rows] == ["CAL", "DEF", "PRE"]
    cal = next(row for row in rows if row["network_type"] == "CAL")
    assert cal["relationship_id"] == "rel:cal"
    assert cal["target_role_uri"] == "http://example.com/role/detail"
    assert cal["from_raw_concept_qname"] == "us-gaap:Revenue"
    assert cal["to_raw_concept_qname"] == "acme:ProductRevenue"
    assert cal["from_company_canonical_concept_id"]
    assert cal["to_company_canonical_concept_id"]
    assert cal["from_mapping_evidence"]
    assert set(result.publication.output_counts) == {"filing_relationship_edge"}


def test_t2_query_by_raw_and_canonical_endpoint_keeps_role_networks(tmp_path: Path) -> None:
    result = FilingRelationshipIndexPipeline().publish(_release(), output_root=tmp_path / "layer2")
    reader = FilingRelationshipIndexReader()
    publication = Layer2PublicationReader().load(result.publication.run_root)
    raw = reader.edges_for_concept(
        publication, cik="0000320193", raw_concept_id="concept:revenue", direction="OUTGOING"
    )
    canonical_id = raw[0]["from_company_canonical_concept_id"]
    canonical = reader.edges_for_concept(
        publication,
        cik="0000320193",
        company_canonical_concept_id=canonical_id,
        direction="OUTGOING",
    )
    assert {row["network_type"] for row in raw} == {"PRE", "CAL", "DEF"}
    assert [row["relationship_id"] for row in canonical] == [row["relationship_id"] for row in raw]
    direct = reader.query_parquet(
        result.publication.run_root,
        cik="0000320193",
        accession="0000320193-25-000001",
        raw_concept_id="concept:revenue",
        direction="OUTGOING",
    )
    assert [row["relationship_id"] for row in direct] == [row["relationship_id"] for row in raw]
