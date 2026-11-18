from __future__ import annotations

from datetime import date

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import _load_with_arelle
from sec_xbrl.relationships.layer1 import (
    CALCULATION_10_ARCROLE,
    CALCULATION_11_ARCROLE,
    RelationshipExtractor,
)


def test_arelle_applies_prohibition_separately_in_legacy_and_modern_calculation(tmp_path):
    (tmp_path / "taxonomy.xsd").write_text(
        '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:link="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        targetNamespace="https://example.test/calculation" elementFormDefault="qualified">
          <xs:import namespace="http://www.xbrl.org/2003/instance"
            schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
          <xs:annotation><xs:appinfo>
            <link:linkbaseRef xlink:type="simple" xlink:href="calculation.xml"
              xlink:role="http://www.xbrl.org/2003/role/calculationLinkbaseRef"
              xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
          </xs:appinfo></xs:annotation>
          <xs:element name="Total" id="Total" type="xbrli:monetaryItemType"
            substitutionGroup="xbrli:item" xbrli:periodType="duration"/>
          <xs:element name="Child" id="Child" type="xbrli:monetaryItemType"
            substitutionGroup="xbrli:item" xbrli:periodType="duration"/>
        </xs:schema>''',
        encoding="utf-8",
    )
    (tmp_path / "calculation.xml").write_text(
        f'''<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
             xmlns:xlink="http://www.w3.org/1999/xlink">
          <link:calculationLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
            <link:loc xlink:type="locator" xlink:href="taxonomy.xsd#Total" xlink:label="total"/>
            <link:loc xlink:type="locator" xlink:href="taxonomy.xsd#Child" xlink:label="child"/>
            <link:calculationArc xlink:type="arc" xlink:arcrole="{CALCULATION_10_ARCROLE}"
              xlink:from="total" xlink:to="child" weight="1" order="1"/>
            <link:calculationArc xlink:type="arc" xlink:arcrole="{CALCULATION_11_ARCROLE}"
              xlink:from="total" xlink:to="child" weight="1" order="1"/>
            <link:calculationArc xlink:type="arc" xlink:arcrole="{CALCULATION_11_ARCROLE}"
              xlink:from="total" xlink:to="child" weight="1" order="1" priority="1" use="prohibited"/>
            <link:calculationArc xlink:type="arc" xlink:arcrole="{CALCULATION_11_ARCROLE}"
              xlink:from="total" xlink:to="child" weight="-1" order="2"/>
          </link:calculationLink>
        </link:linkbase>''',
        encoding="utf-8",
    )
    entry = tmp_path / "report.xml"
    entry.write_text(
        '''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
         <link:schemaRef xlink:type="simple" xlink:href="taxonomy.xsd"/>
        </xbrli:xbrl>''',
        encoding="utf-8",
    )
    model = _load_with_arelle(entry)
    try:
        tables = RelationshipExtractor().extract(
            model, FilingRef("0000000001", "0000000001-25-000001", "10-K", date(2025, 2, 1)),
        )
    finally:
        controller = model.modelManager.cntlr
        model.close()
        controller.close()
    assert {(r["arcrole"], r["weight"]) for r in tables.relationships} == {
        (CALCULATION_10_ARCROLE, "1"), (CALCULATION_11_ARCROLE, "-1"),
    }
    assert {r["source_document"] for r in tables.relationships} == {"calculation.xml"}
    assert all(r["source_locator"].startswith("line:") for r in tables.relationships)
