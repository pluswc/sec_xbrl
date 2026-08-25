from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl.facts.layer1 import Layer1ExtractionError, Layer1Extractor, select_fact_corpus
from sec_xbrl.filing.contracts import FilingRef


@dataclass(frozen=True)
class _QName:
    namespaceURI: str
    localName: str
    prefix: str | None = None


class _Concept:
    def __init__(self, qname: _QName, *, numeric: bool = True) -> None:
        self.qname = qname
        self.typeQname = _QName("http://www.w3.org/2001/XMLSchema", "decimal", "xsd")
        self.periodType = "duration"
        self.balance = "credit"
        self.isAbstract = False
        self.isNillable = True
        self.numeric = numeric

    def label(self, role: str | None = None) -> str:
        return "Revenue documentation" if role else "Revenue"


class _Dimension:
    def __init__(self, axis: _QName, member: _QName | None = None, typed: str | None = None) -> None:
        self.dimensionQname = axis
        self.memberQname = member
        self.isExplicit = member is not None
        self.typedMember = typed


class _Context:
    id = "ctx-2024"
    entityIdentifier = ("http://www.sec.gov/CIK", "0000320193")
    isStartEndPeriod = True
    isInstantPeriod = False
    isForeverPeriod = False
    startDatetime = date(2024, 1, 1)
    endDatetime = date(2024, 12, 31)
    xml = "<context id='ctx-2024'/>"

    def __init__(self) -> None:
        self.qnameDims = {
            _QName("http://example.com/acme/2024", "RegionAxis", "acme"): _Dimension(
                _QName("http://example.com/acme/2024", "RegionAxis", "acme"),
                _QName("http://example.com/acme/2024", "KoreaMember", "acme"),
            ),
            _QName("http://example.com/acme/2024", "CustomerAxis", "acme"): _Dimension(
                _QName("http://example.com/acme/2024", "CustomerAxis", "acme"), typed="<typed>customer-7</typed>"
            ),
        }


class _Unit:
    xml = "<unit id='usd'><measure>iso4217:USD</measure></unit>"
    measures = ((_QName("http://www.xbrl.org/2003/iso4217", "USD", "iso4217"),), ())


class _Document:
    basename = "acme-20241231.htm"


class _Fact:
    id = "revenue-1"
    isTuple = False
    isNumeric = True
    isNil = False
    value = "1234.50"
    decimals = "-3"
    precision = None
    modelDocument = _Document()
    sourceline = 42

    def __init__(self, *, nil: bool = False) -> None:
        self.qname = _QName("http://fasb.org/us-gaap/2024", "Revenue", "us-gaap")
        self.concept = _Concept(self.qname)
        self.context = _Context()
        self.unit = _Unit()
        self.isNil = nil


class _Model:
    def __init__(self) -> None:
        self.factsInInstance = (_Fact(), _Fact(nil=True))
        context = self.factsInInstance[0].context
        region_axis, customer_axis = context.qnameDims
        korea_member = context.qnameDims[region_axis].memberQname
        self.qnameConcepts = {
            region_axis: _Concept(region_axis, numeric=False),
            customer_axis: _Concept(customer_axis, numeric=False),
            korea_member: _Concept(korea_member, numeric=False),
        }


def _filing() -> FilingRef:
    return FilingRef("0000320193", "0000320193-25-000079", "10-K", date(2025, 10, 31))


def test_extract_preserves_as_filed_qnames_context_units_values_and_all_dimensions() -> None:
    tables = Layer1Extractor().extract(_Model(), _filing(), source_url="https://sec.example/index.json")

    assert tables.filing[0]["source_url"] == "https://sec.example/index.json"
    revenue = next(row for row in tables.concepts if row["local_name"] == "Revenue")
    assert revenue["namespace_uri"] == "http://fasb.org/us-gaap/2024"
    assert revenue["taxonomy_family"] == "us-gaap"
    assert revenue["is_standard"] is True
    assert revenue["is_custom"] is False
    region_axis = next(row for row in tables.concepts if row["local_name"] == "RegionAxis")
    assert region_axis["is_custom"] is True
    assert tables.contexts[0]["period_kind"] == "DURATION"
    assert tables.contexts[0]["duration_days"] == 365
    assert tables.units[0]["raw_representation"].startswith("<unit")
    assert tables.facts[0]["value_numeric"] == "1234.50"
    assert tables.facts[0]["raw_value"] == "1234.50"
    assert tables.facts[0]["source_locator"] == "line:42"
    assert tables.facts[0]["reported_or_derived"] == "REPORTED"
    assert tables.facts[0]["period_class"] is None
    assert tables.facts[1]["is_nil"] is True
    assert tables.facts[1]["raw_value"] is None
    assert {row["dimension_type"] for row in tables.dimension_facts} == {"EXPLICIT", "TYPED"}
    assert any(row["typed_member"] == "<typed>customer-7</typed>" for row in tables.dimension_facts)


def test_write_parquet_materializes_separate_raw_tables(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    tables = Layer1Extractor().extract(_Model(), _filing())

    tables.write_parquet(tmp_path)

    assert {path.stem for path in tmp_path.glob("*.parquet")} == {
        "filing", "concept", "context", "unit", "fact", "dimension_fact"
    }
    fact = pl.read_parquet(tmp_path / "fact.parquet").row(0, named=True)
    assert fact["reported_or_derived"] == "REPORTED"


def test_dimension_concepts_preserve_resolved_taxonomy_labels_and_documentation() -> None:
    model = _Model()
    context = model.factsInInstance[0].context
    region_axis, customer_axis = context.qnameDims
    korea_member = context.qnameDims[region_axis].memberQname
    model.qnameConcepts = {
        region_axis: _Concept(region_axis, numeric=False),
        customer_axis: _Concept(customer_axis, numeric=False),
        korea_member: _Concept(korea_member, numeric=False),
    }

    tables = Layer1Extractor().extract(model, _filing())

    for local_name in ("RegionAxis", "CustomerAxis", "KoreaMember"):
        row = next(item for item in tables.concepts if item["local_name"] == local_name)
        assert row["data_type"] == "xsd:decimal"
        assert row["label"] == "Revenue"
        assert row["documentation"] == "Revenue documentation"


def test_refuses_unresolved_context_axis_or_explicit_member_metadata() -> None:
    model = type("UnresolvedDimensionModel", (), {"facts": (_Fact(),), "qnameConcepts": {}})()

    with pytest.raises(Layer1ExtractionError, match="unresolved Context Axis concept"):
        Layer1Extractor().extract(model, _filing())


def test_parquet_retains_text_and_lossless_foreign_key_linkage(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    numeric = _Fact()
    text = _Fact()
    text.id = "narrative-1"
    text.isNumeric = False
    text.value = "Filed disclosure text"
    text.decimals = None
    text.precision = "INF"
    context = numeric.context
    region_axis, customer_axis = context.qnameDims
    korea_member = context.qnameDims[region_axis].memberQname
    model = type(
        "MixedModel",
        (),
        {
            "facts": (numeric, text),
            "qnameConcepts": {
                region_axis: _Concept(region_axis, numeric=False),
                customer_axis: _Concept(customer_axis, numeric=False),
                korea_member: _Concept(korea_member, numeric=False),
            },
        },
    )()

    tables = Layer1Extractor().extract(model, _filing())
    tables.write_parquet(tmp_path)

    facts = pl.read_parquet(tmp_path / "fact.parquet")
    concepts = pl.read_parquet(tmp_path / "concept.parquet")
    contexts = pl.read_parquet(tmp_path / "context.parquet")
    units = pl.read_parquet(tmp_path / "unit.parquet")
    dimensions = pl.read_parquet(tmp_path / "dimension_fact.parquet")
    narrative = facts.filter(pl.col("value_text") == "Filed disclosure text").row(0, named=True)
    assert narrative["raw_value"] == "Filed disclosure text"
    assert narrative["value_numeric"] is None
    assert narrative["precision"] == "INF"
    concept_ids = set(concepts["raw_concept_id"].to_list())
    assert set(facts["raw_concept_id"].to_list()) <= concept_ids
    assert set(facts["context_id"].drop_nulls().to_list()) <= set(contexts["context_id"].to_list())
    assert set(facts["unit_id"].drop_nulls().to_list()) <= set(units["unit_id"].to_list())
    assert set(dimensions["fact_id"].to_list()) <= set(facts["fact_id"].to_list())
    assert set(dimensions["axis_raw_concept_id"].to_list()) <= concept_ids
    assert set(dimensions["member_raw_concept_id"].drop_nulls().to_list()) <= concept_ids
    assert facts["period_class"].null_count() == facts.height
    assert facts["comparative_type"].null_count() == facts.height


def test_write_parquet_keeps_contract_schema_for_empty_dimensions_and_rejects_overwrite(
    tmp_path: Path,
) -> None:
    pl = pytest.importorskip("polars")
    model = type("NoDimensionsModel", (), {"factsInInstance": (_Fact(),)})()
    model.factsInInstance[0].context.qnameDims = {}
    tables = Layer1Extractor().extract(model, _filing())

    tables.write_parquet(tmp_path)

    schema = pl.read_parquet_schema(tmp_path / "dimension_fact.parquet")
    assert schema == {
        "fact_id": pl.String,
        "axis_raw_concept_id": pl.String,
        "member_raw_concept_id": pl.String,
        "typed_member": pl.String,
        "dimension_type": pl.String,
        "is_default_member": pl.Boolean,
    }
    with pytest.raises(Layer1ExtractionError, match="snapshot already exists"):
        tables.write_parquet(tmp_path)


def test_inline_model_uses_complete_model_facts_not_partial_facts_in_instance() -> None:
    first = _Fact()
    second = _Fact()
    second.id = "revenue-2"
    context = first.context
    region_axis, customer_axis = context.qnameDims
    korea_member = context.qnameDims[region_axis].memberQname
    model = type(
        "InlineModel",
        (),
        {
            "facts": (first, second),
            "factsInInstance": (first,),
            "qnameConcepts": {
                region_axis: _Concept(region_axis, numeric=False),
                customer_axis: _Concept(customer_axis, numeric=False),
                korea_member: _Concept(korea_member, numeric=False),
            },
        },
    )()

    corpus = select_fact_corpus(model)
    tables = Layer1Extractor().extract(model, _filing())

    assert corpus.source == "model.facts"
    assert corpus.source_count == 2
    assert len(tables.facts) == 2


def test_refuses_ambiguous_fact_corpus_when_instance_facts_are_not_in_model_facts() -> None:
    model = type("BrokenModel", (), {"facts": (_Fact(),), "factsInInstance": (_Fact(),)})()

    with pytest.raises(Layer1ExtractionError, match="not a subset"):
        select_fact_corpus(model)
