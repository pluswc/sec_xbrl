from __future__ import annotations

from pathlib import Path

from sec_xbrl.filing.filing_index import _load_with_arelle


def test_arelle_applies_sec_metadata_transforms_from_local_inline_fixture(
    tmp_path: Path,
) -> None:
    (tmp_path / "metadata.xsd").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:test="https://example.test/metadata"
 targetNamespace="https://example.test/metadata" elementFormDefault="qualified">
 <xsd:import namespace="http://www.xbrl.org/2003/instance"
  schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
 <xsd:element name="Metadata" type="xbrli:stringItemType"
  substitutionGroup="xbrli:item" xbrli:periodType="duration"/>
</xsd:schema>""",
        encoding="utf-8",
    )
    facts = (
        ("country-uk", "countrynameen", "United Kingdom"),
        ("country-us", "countrynameen", "United States"),
        ("edgar-ie", "edgarprovcountryen", "Ireland"),
        ("state-ne", "stateprovnameen", "Nebraska"),
        ("state-in", "stateprovnameen", "Indiana"),
        ("exchange-chx", "exchnameen", "Chicago Stock Exchange, Inc."),
    )
    fact_markup = "\n".join(
        f'<ix:nonNumeric id="{identifier}" name="test:Metadata" contextRef="c" '
        f'format="ixt-sec:{transform}">{lexical}</ix:nonNumeric>'
        for identifier, transform, lexical in facts
    )
    (tmp_path / "report.htm").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
 xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:test="https://example.test/metadata">
 <head><title>SEC metadata transform fixture</title></head>
 <body>
  <ix:header>
   <ix:references><link:schemaRef xlink:type="simple" xlink:href="metadata.xsd"/></ix:references>
   <ix:resources>
    <xbrli:context id="c">
     <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
     <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
   </ix:resources>
  </ix:header>
  {fact_markup}
 </body>
</html>""",
        encoding="utf-8",
    )

    model = _load_with_arelle(tmp_path / "report.htm")
    try:
        assert model.errors == []
        assert {fact.id: fact.value for fact in model.facts} == {
            "country-uk": "GB",
            "country-us": "US",
            "edgar-ie": "L2",
            "state-ne": "NE",
            "state-in": "IN",
            "exchange-chx": "CHX",
        }
    finally:
        model.close()
