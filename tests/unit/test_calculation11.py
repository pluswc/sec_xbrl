import hashlib
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from sec_xbrl.analytics import calculation11


def test_only_exact_fully_qualified_calculation11_effective_set(monkeypatch, tmp_path):
    package = tmp_path / "source.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("source.xsd", calculation11.ARCROLE)
    filing = {"filing_id": "filing", "cik": "0000000001", "accession": "0000000001-26-000001", "form": "10-Q", "filed_date": "2026-09-01", "primary_document": "source.htm", "source_url": "https://example.invalid", "package_hash": hashlib.sha256(package.read_bytes()).hexdigest()}
    element = SimpleNamespace(sourceline=10, modelDocument=SimpleNamespace(uri="/new/source.xsd"))
    rel = SimpleNamespace(fromModelObject="parent", toModelObject="child", arcElement=element, order=1, weight=-1)
    keys = [(calculation11.ARCROLE, "role", None, None), (calculation11.ARCROLE, "role", "link", "arc"), ("http://www.xbrl.org/2003/arcrole/summation-item", "role", "link", "arc")]
    called = []
    model = SimpleNamespace(baseSets=keys, relationshipSet=lambda *key: (called.append(key) or SimpleNamespace(modelRelationships=[rel])), close=lambda: None)
    monkeypatch.setattr(calculation11.ArelleFilingLoader, "load", lambda *args: model)
    monkeypatch.setattr(calculation11, "_raw_concept_id", lambda filing_id, endpoint: endpoint)
    rows = calculation11.supplement_calculation11(filing=filing, package=package, concepts={"parent": {}, "child": {}}, roles={"r": {"role_id": "r", "role_uri": "role", "role_definition": "role"}}, taxonomy_cache=tmp_path, destination=tmp_path / "extract")
    assert len(rows) == 1
    assert called == [(calculation11.ARCROLE, "role", "link", "arc")]
    assert rows[0]["weight"] == "-1"
    assert rows[0]["source_document"] == "source.xsd"
    assert rows[0]["validation_scope"] == "EXACT_ARITHMETIC_ONLY_NOT_CALCULATION11_INTERVAL_VALIDATION"
    assert not (tmp_path / "extract").exists()


def test_package_without_cal11_does_not_load_parser(monkeypatch, tmp_path):
    package = tmp_path / "source.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("source.xsd", "no cal11")
    def fail(*args):
        raise AssertionError("Arelle must not run")
    monkeypatch.setattr(calculation11.ArelleFilingLoader, "load", fail)
    assert calculation11.supplement_calculation11(filing={"package_hash": hashlib.sha256(package.read_bytes()).hexdigest()}, package=package, concepts={}, roles={}, taxonomy_cache=Path("/not-used"), destination=tmp_path / "extract") == []
