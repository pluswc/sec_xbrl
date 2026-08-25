from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest

from sec_xbrl.facts.layer1 import Layer1Extractor, Layer1Tables
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import FilingIndex, ResolvedFiling
from sec_xbrl.filing.layer1_ingestion import Layer1IngestionError, Layer1Ingestor
from sec_xbrl.relationships.layer1 import RelationshipTables


@dataclass(frozen=True)
class _QName:
    namespaceURI: str
    localName: str
    prefix: str = "us-gaap"


class _Concept:
    def __init__(self, qname: _QName) -> None:
        self.qname = qname
        self.typeQname = _QName("http://www.w3.org/2001/XMLSchema", "decimal", "xsd")
        self.periodType = "duration"
        self.balance = "credit"
        self.isAbstract = False
        self.isNillable = True

    def label(self, _: str | None = None) -> str:
        return "Revenue"


class _Context:
    id = "ctx"
    entityIdentifier = ("http://www.sec.gov/CIK", "0000000001")
    isStartEndPeriod = True
    isForeverPeriod = False
    startDatetime = date(2025, 1, 1)
    endDatetime = date(2025, 3, 31)
    xml = "<context id='ctx'/>"
    qnameDims: ClassVar[dict[object, object]] = {}


class _Fact:
    isTuple = False
    isNumeric = True
    isNil = False
    value = "100"
    decimals = "0"
    precision = None
    context = _Context()
    unit = None
    modelDocument = None
    sourceline = 1

    def __init__(self, identifier: str) -> None:
        self.id = identifier
        self.qname = _QName("http://fasb.org/us-gaap/2025", "RevenueFromContractWithCustomerExcludingAssessedTax")
        self.concept = _Concept(self.qname)


class _Dimension:
    def __init__(self, axis: _QName, member: _QName) -> None:
        self.dimensionQname = axis
        self.memberQname = member
        self.isExplicit = True
        self.typedMember = None


class _Relationship:
    def __init__(self, source: _Concept, target: _Concept) -> None:
        self.fromModelObject = source
        self.toModelObject = target
        self.arcrole = "http://xbrl.org/int/dim/arcrole/all"
        self.order = "1"


class _RelationshipSet:
    def __init__(self, relationship: _Relationship) -> None:
        self.modelRelationships = (relationship,)


class _FullInlineModel:
    role_uri = "http://example.com/role/RevenueGeography"
    baseSets: ClassVar[dict[tuple[str, str, str, str], object]] = {
        ("http://xbrl.org/int/dim/arcrole/all", role_uri, "definitionLink", "definitionArc"): object()
    }
    roleTypes: ClassVar[dict[str, tuple[object, ...]]] = {role_uri: ()}
    errors = ()

    def __init__(self) -> None:
        fact = _Fact("revenue")
        axis = _QName("http://xbrl.org/2005/xbrldt", "GeographyAxis", "srt")
        member = _QName("http://example.com/company/2025", "UnitedStatesMember", "ex")
        fact.context.qnameDims = {axis: _Dimension(axis, member)}
        self.facts = (fact,)
        self.factsInInstance = ()
        self._relationship = _Relationship(fact.concept, _Concept(axis))

    def relationshipSet(self, *_: object) -> _RelationshipSet:
        return _RelationshipSet(self._relationship)


class _Relationships:
    parser_version = "test-relationships"

    def extract(self, model: object, filing: FilingRef) -> RelationshipTables:
        return RelationshipTables(roles=(), relationships=())


class _PartialFacts:
    parser_version = "test-partial-facts"

    def extract(self, model: object, filing: FilingRef, **_: object) -> Layer1Tables:
        tables = Layer1Extractor().extract(model, filing)
        return replace(tables, facts=tables.facts[:1])


class _EarlyFailingFacts:
    parser_version = "test-early-failing-facts"

    def extract(self, model: object, filing: FilingRef, **_: object) -> Layer1Tables:
        raise RuntimeError("fixture extractor stopped early")


class _FailingLoader:
    def load(self, resolved: ResolvedFiling, destination: Path) -> object:
        raise RuntimeError("Arelle fixture load failed")


def _resolved(tmp_path: Path) -> ResolvedFiling:
    filing = FilingRef("0000000001", "0000000001-25-000001", "10-Q", date(2025, 5, 1))
    zip_path = tmp_path / "filing.zip"
    zip_path.write_bytes(b"xbrl fixture")
    index = FilingIndex(cik=filing.cik, accession=filing.accession, source_url="https://sec.example/index.json", entries=())
    return ResolvedFiling(filing=filing, index=index, zip_path=zip_path, entrypoint_name="filing.htm")


def test_ingestion_materializes_complete_fact_corpus_and_success_manifest(tmp_path: Path) -> None:
    pytest.importorskip("polars")
    first, second = _Fact("one"), _Fact("two")
    model = type("InlineModel", (), {"facts": (first, second), "factsInInstance": (first,), "errors": ()})()
    ingestor = Layer1Ingestor(tmp_path / "snapshots", relationship_extractor=_Relationships())

    manifest = ingestor.ingest(_resolved(tmp_path), model)
    snapshot = tmp_path / "snapshots" / "0000000001" / "000000000125000001"

    assert manifest.fact_corpus_source == "model.facts"
    assert manifest.source_fact_count == 2
    assert manifest.materialized_fact_count == 2
    assert (snapshot / "fact.parquet").is_file()
    assert (snapshot / "relationship.parquet").is_file()
    assert (snapshot / "layer1_manifest.json").is_file()
    states = list((tmp_path / "parse_state").rglob("*.json"))
    parsed_states = [json.loads(state.read_text()) for state in states]
    assert {state["quality_gate"] for state in parsed_states} == {
        "TAXONOMY_AND_TRANSFORM_RESOLUTION",
        "RAW_CORPUS_COMPLETENESS",
        "ATOMIC_FILING_SNAPSHOT",
    }
    raw_gate = next(state for state in parsed_states if state["quality_gate"] == "RAW_CORPUS_COMPLETENESS")
    assert raw_gate["outcome"] == "SUCCEEDED"
    assert raw_gate["expected_count"] == raw_gate["actual_count"] == 2
    assert raw_gate["validation_rule_version"]
    assert raw_gate["recorded_at"]
    assert raw_gate["message"] is None
    with pytest.raises(Layer1IngestionError, match="already exists"):
        ingestor.ingest(_resolved(tmp_path), model)


def test_complete_inline_fixture_publishes_dimensional_fact_and_definition_relationship(
    tmp_path: Path,
) -> None:
    pytest.importorskip("polars")
    ingestor = Layer1Ingestor(tmp_path / "snapshots")

    manifest = ingestor.ingest(_resolved(tmp_path), _FullInlineModel())

    assert manifest.materialized_fact_count == 1
    assert manifest.dimension_fact_count == 1
    assert manifest.role_count == 1
    assert manifest.relationship_count == 1


@pytest.mark.parametrize("error", ["IOerror: taxonomy unavailable", "invalidTransformation: ixt missing"])
def test_ingestion_refuses_resolution_or_inline_transform_errors_before_writing(
    tmp_path: Path, error: str
) -> None:
    model = type("BadModel", (), {"facts": (_Fact("one"),), "errors": (error,)})()
    ingestor = Layer1Ingestor(tmp_path / "snapshots", relationship_extractor=_Relationships())

    with pytest.raises(Layer1IngestionError, match="unresolved taxonomy or Inline transform"):
        ingestor.ingest(_resolved(tmp_path), model)

    assert not (tmp_path / "snapshots" / "0000000001" / "000000000125000001").exists()
    state = json.loads(next((tmp_path / "parse_state").rglob("*.json")).read_text())
    assert state["stage"] == "VALIDATION"
    assert state["retryable"] is True


def test_ingestion_refuses_unresolved_concept_before_writing(tmp_path: Path) -> None:
    fact = _Fact("one")
    fact.concept = None
    model = type("UnresolvedModel", (), {"facts": (fact,), "errors": ()})()
    ingestor = Layer1Ingestor(tmp_path / "snapshots", relationship_extractor=_Relationships())

    with pytest.raises(Layer1IngestionError, match="unresolved concepts"):
        ingestor.ingest(_resolved(tmp_path), model)

    assert not (tmp_path / "snapshots" / "0000000001").exists()


def test_ingestion_refuses_partial_extractor_output_and_records_retryable_state(tmp_path: Path) -> None:
    first, second = _Fact("one"), _Fact("two")
    model = type("InlineModel", (), {"facts": (first, second), "factsInInstance": (first,), "errors": ()})()
    ingestor = Layer1Ingestor(
        tmp_path / "snapshots",
        fact_extractor=_PartialFacts(),
        relationship_extractor=_Relationships(),
    )

    with pytest.raises(Layer1IngestionError, match="does not match validated source corpus"):
        ingestor.ingest(_resolved(tmp_path), model)

    assert not (tmp_path / "snapshots" / "0000000001" / "000000000125000001").exists()
    state = json.loads(next((tmp_path / "parse_state").rglob("*.json")).read_text())
    assert state["stage"] == "LAYER1_EXTRACT"
    assert state["outcome"] == "FAILED"
    assert state["retryable"] is True


def test_early_extractor_failure_preserves_error_and_records_raw_completeness_gate(
    tmp_path: Path,
) -> None:
    model = type("InlineModel", (), {"facts": (_Fact("one"),), "errors": ()})()
    ingestor = Layer1Ingestor(
        tmp_path / "snapshots",
        fact_extractor=_EarlyFailingFacts(),
        relationship_extractor=_Relationships(),
    )

    with pytest.raises(RuntimeError, match="fixture extractor stopped early"):
        ingestor.ingest(_resolved(tmp_path), model)

    assert not (tmp_path / "snapshots" / "0000000001" / "000000000125000001").exists()
    state = json.loads(next((tmp_path / "parse_state").rglob("*.json")).read_text())
    assert state["quality_gate"] == "RAW_CORPUS_COMPLETENESS"
    assert state["outcome"] == "FAILED"
    assert state["expected_count"] == 1
    assert state["actual_count"] is None
    assert state["message"] == "fixture extractor stopped early"


def test_load_failure_is_recorded_as_retryable_arelle_load_state(tmp_path: Path) -> None:
    ingestor = Layer1Ingestor(tmp_path / "snapshots", relationship_extractor=_Relationships())

    with pytest.raises(RuntimeError, match="fixture load failed"):
        ingestor.load_and_ingest(_resolved(tmp_path), _FailingLoader(), tmp_path / "extract")  # type: ignore[arg-type]

    state = json.loads(next((tmp_path / "parse_state").rglob("*.json")).read_text())
    assert state["stage"] == "ARELLE_LOAD"
    assert state["outcome"] == "FAILED"
    assert state["retryable"] is True
