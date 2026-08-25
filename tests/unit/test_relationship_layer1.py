from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import ClassVar

import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.relationships.layer1 import RelationshipExtractor


@dataclass(frozen=True)
class _QName:
    namespaceURI: str
    localName: str
    prefix: str = "us-gaap"


@dataclass(frozen=True)
class _Concept:
    qname: _QName


@dataclass(frozen=True)
class _RoleType:
    definition: str


class _Relationship:
    def __init__(self, source: _Concept, target: _Concept, **attributes: object) -> None:
        self.fromModelObject = source
        self.toModelObject = target
        self.arcrole = attributes.pop("arcrole")
        for name, value in attributes.items():
            setattr(self, name, value)


class _RelationshipSet:
    def __init__(self, relationships: list[_Relationship]) -> None:
        self.modelRelationships = relationships


class _Model:
    presentation = "http://www.xbrl.org/2003/arcrole/parent-child"
    calculation = "http://www.xbrl.org/2003/arcrole/summation-item"
    definition = "http://xbrl.org/int/dim/arcrole/all"
    statement_role = "http://example.com/role/StatementOfIncome"
    disclosure_role = "http://example.com/role/RevenueDisclosure"
    baseSets: ClassVar[dict[tuple[str, str, str, str], object]] = {
        (presentation, statement_role, "presentationLink", "presentationArc"): object(),
        (presentation, statement_role, "alternatePresentationLink", "alternatePresentationArc"): object(),
        (calculation, statement_role, "calculationLink", "calculationArc"): object(),
        (definition, disclosure_role, "definitionLink", "definitionArc"): object(),
    }
    roleTypes: ClassVar[dict[str, list[_RoleType]]] = {
        statement_role: [_RoleType("Consolidated Statements of Income")],
        disclosure_role: [_RoleType("Revenue Disclosure (Tables)")],
    }

    def __init__(self) -> None:
        revenue = _Concept(_QName("http://fasb.org/us-gaap/2024", "Revenue"))
        gross_profit = _Concept(_QName("http://fasb.org/us-gaap/2024", "GrossProfit"))
        region_axis = _Concept(_QName("http://example.com/acme/2024", "RegionAxis", "acme"))
        self._sets = {
            (self.presentation, self.statement_role): _RelationshipSet(
                [
                    _Relationship(
                        revenue,
                        gross_profit,
                        arcrole=self.presentation,
                        order="2.5",
                        preferredLabel="http://example/label",
                    )
                ]
            ),
            (self.calculation, self.statement_role): _RelationshipSet(
                [
                    _Relationship(
                        revenue, gross_profit, arcrole=self.calculation, order="1", weight="-1"
                    )
                ]
            ),
            (self.definition, self.disclosure_role): _RelationshipSet(
                [
                    _Relationship(
                        revenue,
                        region_axis,
                        arcrole=self.definition,
                        order="7",
                        targetRole="http://example.com/role/RegionMembers",
                        usable=False,
                        closed=True,
                        contextElement="segment",
                    )
                ]
            ),
        }

    def relationshipSet(self, arcrole: str, role_uri: str, *_: object) -> _RelationshipSet:
        return self._sets[(arcrole, role_uri)]


def _filing() -> FilingRef:
    return FilingRef("0000320193", "0000320193-25-000079", "10-K", date(2025, 10, 31))


def test_extract_keeps_pre_cal_def_separate_and_preserves_target_role_metadata() -> None:
    tables = RelationshipExtractor().extract(_Model(), _filing())

    assert {row["network_type"] for row in tables.relationships} == {"PRE", "CAL", "DEF"}
    assert len(tables.relationships) == 4
    assert {row["role_category"] for row in tables.roles} == {"STATEMENT", "TABLE"}
    definition = next(row for row in tables.relationships if row["network_type"] == "DEF")
    assert definition["target_role_uri"] == "http://example.com/role/RegionMembers"
    assert definition["usable"] is False
    assert definition["closed"] is True
    assert definition["context_element"] == "segment"
    assert definition["from_raw_concept_id"] != definition["to_raw_concept_id"]
    presentation = next(row for row in tables.relationships if row["network_type"] == "PRE")
    calculation = next(row for row in tables.relationships if row["network_type"] == "CAL")
    assert presentation["role_id"] == calculation["role_id"]
    assert presentation["relationship_id"] != calculation["relationship_id"]
    presentations = [row for row in tables.relationships if row["network_type"] == "PRE"]
    assert {row["link_qname"] for row in presentations} == {
        "alternatePresentationLink",
        "presentationLink",
    }
    assert {row["arc_qname"] for row in presentations} == {
        "alternatePresentationArc",
        "presentationArc",
    }
    assert len({row["relationship_id"] for row in presentations}) == 2


def test_write_parquet_keeps_role_and_relationship_contract_schemas(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    tables = RelationshipExtractor().extract(_Model(), _filing())

    tables.write_parquet(tmp_path)

    assert {path.stem for path in tmp_path.glob("*.parquet")} == {"role", "relationship"}
    relationship = pl.read_parquet(tmp_path / "relationship.parquet").row(0, named=True)
    assert relationship["network_type"] in {"PRE", "CAL", "DEF"}
    assert "link_qname" in relationship
    assert "arc_qname" in relationship
    with pytest.raises(Exception, match="snapshot already exists"):
        tables.write_parquet(tmp_path)
