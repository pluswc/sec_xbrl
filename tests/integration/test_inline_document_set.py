from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndex, ResolvedFiling
from sec_xbrl.filing.inline_document_set import InlineDocumentSetError, discover_inline_set


def package(tmp_path: Path, *, failure: str = "") -> ResolvedFiling:
    schema = '''<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xbrli="http://www.xbrl.org/2003/instance" targetNamespace="https://example.test/ixds" xmlns:t="https://example.test/ixds" elementFormDefault="qualified"><xsd:import namespace="http://www.xbrl.org/2003/instance" schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/><xsd:element name="Revenue" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration"/><xsd:element name="Text" type="xbrli:stringItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration"/></xsd:schema>'''
    header = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:t="https://example.test/ixds"><head><title>IXDS</title></head><body>'''
    resources = '''<ix:header><ix:references><link:schemaRef xlink:type="simple" xlink:href="test.xsd"/></ix:references><ix:resources><xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context><xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header>'''
    facts = '''<ix:nonFraction id="amount" name="t:Revenue" contextRef="c" unitRef="u" decimals="0">125</ix:nonFraction><ix:nonNumeric name="t:Text" contextRef="c" continuedAt="continuation">first </ix:nonNumeric>'''
    continuation = '<ix:continuation id="continuation">second</ix:continuation>'
    if failure == "missing":
        facts = facts.replace('unitRef="u"', 'unitRef="absent"')
    elif failure == "target":
        facts = facts.replace('id="amount"', 'id="amount" target="other"')
    elif failure == "cycle":
        continuation = '<ix:continuation id="continuation" continuedAt="continuation">cycle</ix:continuation>'
    elif failure == "duplicate":
        continuation += '<ix:continuation id="c">duplicate</ix:continuation>'
    (tmp_path / "test.xsd").write_text(schema)
    (tmp_path / "primary.htm").write_text(header + resources + continuation + '</body></html>')
    (tmp_path / "unrelated-name.htm").write_text(header + facts + '</body></html>')
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name in ("test.xsd", "primary.htm", "unrelated-name.htm"):
            output.write(tmp_path / name, name)
    filing = FilingRef(cik="0000000001", accession="0000000001-26-000001", form="10-K", filed_date=date(2026, 2, 1), report_date=date(2025, 12, 31), primary_document="primary.htm")
    return ResolvedFiling(filing, FilingIndex(filing.cik, filing.accession, "fixture", ()), archive, "primary.htm")


def test_actual_arelle_cross_document_context_unit_continuation_and_inventory(tmp_path: Path):
    resolved = package(tmp_path)
    model = ArelleFilingLoader().load(resolved, tmp_path / "loaded")
    try:
        assert not model.errors
        assert {str(f.qname): f.value for f in model.facts} == {"t:Revenue": "125", "t:Text": "first second"}
        inventory = model.sec_inline_document_inventory
        assert [(row["name"], row["expected_fact_count"], row["loaded_fact_count"]) for row in inventory] == [("primary.htm", 0, 0), ("unrelated-name.htm", 2, 2)]
        assert len({f.modelDocument.basename for f in model.facts}) == 1
    finally:
        model.close()


@pytest.mark.parametrize("failure", ["missing", "target", "cycle", "duplicate"])
def test_bad_inline_set_fails_before_loading(tmp_path: Path, failure: str):
    package(tmp_path, failure=failure)
    with pytest.raises(InlineDocumentSetError):
        discover_inline_set(tmp_path, tmp_path / "primary.htm")


def test_direct_ingest_cannot_publish_primary_only_as_complete_multidocument(tmp_path):
    from sec_xbrl.filing.filing_index import _load_with_arelle
    from sec_xbrl.filing.layer1_ingestion import Layer1Ingestor

    resolved = package(tmp_path)
    primary = tmp_path / "primary.htm"
    primary.write_text(primary.read_text().replace('</body>', '<ix:nonFraction id="primary-fact" name="t:Revenue" contextRef="c" unitRef="u" decimals="0">10</ix:nonFraction></body>'))
    continuation = '<ix:continuation id="continuation">second</ix:continuation>'
    primary.write_text(primary.read_text().replace(continuation, ""))
    other = tmp_path / "unrelated-name.htm"
    other.write_text(other.read_text().replace('</body>', continuation + '</body>'))
    with zipfile.ZipFile(resolved.zip_path, "w") as archive:
        for name in ("test.xsd", "primary.htm", "unrelated-name.htm"):
            archive.write(tmp_path / name, name)
    partial = _load_with_arelle(primary)
    try:
        assert len(partial.facts) == 1
        with pytest.raises(InlineDocumentSetError, match="document coverage"):
            Layer1Ingestor(tmp_path / "forbidden-output").ingest(resolved, partial)
        assert not list((tmp_path / "forbidden-output").rglob("layer1_manifest.json"))
    finally:
        partial.close()
    full = ArelleFilingLoader().load(resolved, tmp_path / "full-loaded")
    try:
        manifest = Layer1Ingestor(tmp_path / "new-output").ingest(resolved, full)
        assert manifest.layer1_parser_version == "m2-layer1-v8"
        assert manifest.materialized_fact_count == 3
        assert [doc["extracted_fact_count"] for doc in manifest.inline_document_inventory] == [1, 2]
    finally:
        full.close()


def test_malformed_inline_and_unresolved_relationship_fail_closed(tmp_path):
    package(tmp_path)
    path = tmp_path / "unrelated-name.htm"
    original = path.read_text()
    path.write_text(original.replace('</body>', '<ix:relationship fromRefs="amount" toRefs="missing"/></body>'))
    with pytest.raises(InlineDocumentSetError, match="relationship"):
        discover_inline_set(tmp_path, tmp_path / "primary.htm")
    path.write_text(original.replace('</body>', '<broken></body>'))
    with pytest.raises(InlineDocumentSetError, match="well-formed"):
        discover_inline_set(tmp_path, tmp_path / "primary.htm")


def test_independent_same_target_inline_instance_is_not_silently_combined(tmp_path):
    package(tmp_path)
    extra = (tmp_path / "primary.htm").read_text().replace('id="c"', 'id="different-context"').replace('id="u"', 'id="different-unit"').replace('id="continuation"', 'id="different-continuation"')
    (tmp_path / "third.htm").write_text(extra)
    with pytest.raises(InlineDocumentSetError, match="unrelated Inline"):
        discover_inline_set(tmp_path, tmp_path / "primary.htm")


@pytest.mark.parametrize("name", ["duplicate", "alias", "traversal", "symlink"])
def test_unsafe_zip_members_never_reach_arelle(tmp_path, name):
    from sec_xbrl.filing.filing_index import FilingIndexError, _extract_zip

    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("safe.txt", "first")
        if name == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("safe.txt", "second")
        elif name == "alias":
            archive.writestr("./safe.txt", "second")
        elif name == "traversal":
            archive.writestr("../escape.txt", "second")
        else:
            info = zipfile.ZipInfo("link.txt")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "../outside")
    destination = tmp_path / "extract"
    destination.mkdir()
    with pytest.raises(FilingIndexError):
        _extract_zip(path, destination)
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("reference", ["../outside.xsd", "file:///etc/passwd", "absent.xsd"])
def test_inline_resource_documents_must_be_local_package_or_offline_taxonomy(tmp_path, reference):
    package(tmp_path)
    primary = tmp_path / "primary.htm"
    primary.write_text(primary.read_text().replace('href="test.xsd"', f'href="{reference}"'))
    with pytest.raises(InlineDocumentSetError, match="resource document"):
        discover_inline_set(tmp_path, primary)
