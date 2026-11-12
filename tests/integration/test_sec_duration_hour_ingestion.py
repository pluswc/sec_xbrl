from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import pytest

from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndex, ResolvedFiling
from sec_xbrl.filing.layer1_ingestion import Layer1IngestionError, Layer1Ingestor

SEC_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"


class _TrackingLoader(ArelleFilingLoader):
    model = None

    def load(self, resolved: ResolvedFiling, destination: Path):
        self.model = super().load(resolved, destination)
        return self.model


def _package(tmp_path: Path, markup: str, *, namespace: str = SEC_NAMESPACE) -> ResolvedFiling:
    schema = '''<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:test="https://example.test/duration"
 targetNamespace="https://example.test/duration" elementFormDefault="qualified">
 <xsd:import namespace="http://www.xbrl.org/2003/instance"
  schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
 <xsd:element name="Duration" type="xbrli:durationItemType"
  substitutionGroup="xbrli:item" xbrli:periodType="duration"/>
</xsd:schema>'''
    inline = f'''<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:sec="{namespace}"
 xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:test="https://example.test/duration">
 <head><title>Offline duration fixture</title></head><body><ix:header>
 <ix:references><link:schemaRef xlink:type="simple" xlink:href="duration.xsd"/></ix:references>
 <ix:resources><xbrli:context id="ctx"><xbrli:entity>
 <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
 </xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
 <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context></ix:resources>
 </ix:header>{markup}</body></html>'''
    package = tmp_path / "filing.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("report.htm", inline)
        archive.writestr("duration.xsd", schema)
    filing = FilingRef("0000000001", "0000000001-26-000001", "10-K", date(2026, 2, 1))
    return ResolvedFiling(filing, FilingIndex(filing.cik, filing.accession, "https://example.test/index.json", ()), package, "report.htm")


def _fact(lexical: str, transform: str = "durhour", attributes: str = "") -> str:
    return f'<ix:nonNumeric id="duration" name="test:Duration" contextRef="ctx" format="sec:{transform}" {attributes}>{lexical}</ix:nonNumeric>'


def test_normal_offline_loader_ingests_hours_and_continued_words_without_mutating_snapshot(tmp_path: Path) -> None:
    markup = _fact("20") + _fact("one<ix:exclude>not part of lexical</ix:exclude>", "durwordsen", 'continuedAt="year"').replace('id="duration"', 'id="words"')
    markup += '<ix:continuation id="year"> year</ix:continuation>'
    resolved = _package(tmp_path, markup)
    package_hash = hashlib.sha256(resolved.zip_path.read_bytes()).hexdigest()
    loader = _TrackingLoader()
    ingestor = Layer1Ingestor(tmp_path / "snapshots")
    try:
        manifest = ingestor.load_and_ingest(resolved, loader, tmp_path / "extract")
        assert manifest.layer1_parser_version == "m2-layer1-v7"
        assert manifest.source_fact_count == manifest.materialized_fact_count == 2
        assert {fact.id: (fact.rawValue, fact.value) for fact in loader.model.facts} == {
            "duration": ("20", "PT20H"), "words": ("one year", "P1Y"),
        }
        snapshot = ingestor.snapshot_dir(resolved)
        assert set(pl.read_parquet(snapshot / "fact.parquet")["raw_value"]) == {"PT20H", "P1Y"}
        before = {path.name: path.read_bytes() for path in snapshot.iterdir()}
        with pytest.raises(Layer1IngestionError, match="already exists"):
            ingestor.ingest(resolved, loader.model)
        assert {path.name: path.read_bytes() for path in snapshot.iterdir()} == before
        assert hashlib.sha256(resolved.zip_path.read_bytes()).hexdigest() == package_hash
    finally:
        if loader.model is not None:
            loader.model.close()


@pytest.mark.parametrize(
    ("markup", "namespace", "expected_lexical"),
    ((_fact("20", "durhour"), SEC_NAMESPACE + "/wrong", "20"),
     (_fact("NaN"), SEC_NAMESPACE, "NaN"),
     (_fact("one", "durwordsen"), SEC_NAMESPACE, "one"),
     (_fact("one", "durwordsen", 'continuedAt="year"') + '<ix:continuation id="year"> nonsense</ix:continuation>', SEC_NAMESPACE, "one nonsense"),
     (_fact("20", "not-registered"), SEC_NAMESPACE, "20")),
)
def test_normal_loader_persists_namespace_aware_complete_error_lexical(
    tmp_path: Path, markup: str, namespace: str, expected_lexical: str,
) -> None:
    resolved = _package(tmp_path, markup, namespace=namespace)
    loader = _TrackingLoader()
    ingestor = Layer1Ingestor(tmp_path / "snapshots")
    try:
        with pytest.raises(Layer1IngestionError):
            ingestor.load_and_ingest(resolved, loader, tmp_path / "extract")
        state, = [json.loads(path.read_text()) for path in (tmp_path / "parse_state").rglob("*.json")]
        assert state["outcome"] == "FAILED"
        assert state["retryable"]
        details = json.loads(state["message"].split("; fact_diagnostics=", 1)[1])
        assert details[0]["lexical"] == expected_lexical
        assert details[0]["qname"] == "{https://example.test/duration}Duration"
        assert details[0]["context"] == "ctx"
        assert details[0]["format"].startswith("{" + namespace + "}")
        assert not ingestor.snapshot_dir(resolved).exists()
    finally:
        if loader.model is not None:
            loader.model.close()


@pytest.mark.parametrize(
    ("continuation", "expected_error"),
    (("", "continuationMissing"),
     ('<ix:continuation id="year" continuedAt="year"> year</ix:continuation>', "continuationCycle"),
     ('<span id="year"> year</span>', "continuationTarget")),
)
def test_normal_loader_rejects_missing_cycle_and_wrong_target_continuations(
    tmp_path: Path, continuation: str, expected_error: str,
) -> None:
    resolved = _package(tmp_path, _fact("one", "durwordsen", 'continuedAt="year"') + continuation)
    loader = _TrackingLoader()
    ingestor = Layer1Ingestor(tmp_path / "snapshots")
    try:
        with pytest.raises(Layer1IngestionError, match=expected_error):
            ingestor.load_and_ingest(resolved, loader, tmp_path / "extract")
        state, = [json.loads(path.read_text()) for path in (tmp_path / "parse_state").rglob("*.json")]
        assert '"lexical_unavailable":"INVALID_CONTINUATION_CHAIN"' in state["message"]
        assert not ingestor.snapshot_dir(resolved).exists()
    finally:
        if loader.model is not None:
            loader.model.close()
