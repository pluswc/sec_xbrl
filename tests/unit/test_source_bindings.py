from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest
from lxml import html as lxml_html

from sec_xbrl import collection_operations as operations
from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.history import HISTORY_VERSION
from sec_xbrl.source_bindings import (
    SEC_TRANSFORM_NAMESPACE,
    SourceBindingsReader,
    publish_source_bindings,
)


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> dict[str, Path]:
    ticker = "TEST"
    cik = "0000000123"
    accession = "0000000123-26-000001"
    primary_document = "test.htm"
    config = _write(
        tmp_path / "config.json",
        {
            "schema_version": 1,
            "universe_id": "source-binding-fixture",
            "purpose": "fixture",
            "as_of_date": "2026-10-08",
            "source_observed_at": "2026-10-08T00:00:00+00:00",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [{"ticker": ticker, "cik": cik, "groups": ["fixture"]}],
        },
    )
    filing = {
        "cik": cik,
        "accession": accession,
        "form": "10-K",
        "filed_date": "2026-03-01",
        "report_date": "2025-12-31",
        "primary_document": primary_document,
        "is_xbrl": True,
        "is_inline_xbrl": True,
        "source": "fixture",
    }
    plan = _write(
        tmp_path / "plan.json",
        {
            "version": HISTORY_VERSION,
            "as_of_date": "2026-10-08",
            "report_start": "2025-12-31",
            "report_end": "2025-12-31",
            "recent_fiscal_years": None,
            "companies": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "name": "Test Corp",
                    "submissions": [],
                    "filings": [filing],
                }
            ],
        },
    )
    collection = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "operations",
        existing_plans={ticker: plan},
    )
    local_plan = json.loads((collection.parent / "companies/TEST/plan.json").read_text())

    primary = b"""<html xmlns=\"http://www.w3.org/1999/xhtml\"
 xmlns:ix=\"http://www.xbrl.org/2013/inlineXBRL\"
 xmlns:ixt-sec=\"http://www.sec.gov/inlineXBRL/transformation/2015-08-31\"
 xmlns:test=\"https://example.test/2026\"
 xmlns:dei=\"http://xbrl.sec.gov/dei/2026\">
 <body>
  <ix:nonNumeric id=\"duration-source\" name=\"test:ExpectedLife\" contextRef=\"duration-context\" format=\"ixt-sec:duryear\">1.5</ix:nonNumeric>
  <ix:nonNumeric id=\"exchange-source\" name=\"dei:SecurityExchangeName\" contextRef=\"exchange-context\" format=\"ixt-sec:exchnameen\">Nasdaq</ix:nonNumeric>
 </body>
</html>"""
    package = (
        tmp_path
        / "packages"
        / cik
        / accession.replace("-", "")
        / f"{accession}-xbrl.zip"
    )
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(primary_document, primary)
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    primary_sha = hashlib.sha256(primary).hexdigest()

    document = lxml_html.fromstring(
        primary,
        parser=lxml_html.HTMLParser(huge_tree=True, no_network=True, recover=False),
    )
    elements = {element.get("id"): element for element in document.xpath("//*[@id]")}
    filing_id = _stable_id("filing", cik, accession)
    duration_context = _stable_id("context", filing_id, "duration-context")
    exchange_context = _stable_id("context", filing_id, "exchange-context")
    duration_concept = _stable_id(
        "concept", filing_id, "https://example.test/2026", "ExpectedLife"
    )
    exchange_concept = _stable_id(
        "concept", filing_id, "http://xbrl.sec.gov/dei/2026", "SecurityExchangeName"
    )
    duration_locator = f"line:{elements['duration-source'].sourceline}"
    exchange_locator = f"line:{elements['exchange-source'].sourceline}"
    duration_fact = _stable_id(
        "fact", filing_id, "duration-source", duration_locator, 0
    )
    exchange_fact = _stable_id(
        "fact", filing_id, "exchange-source", exchange_locator, 1
    )
    snapshot = (
        collection.parent
        / "companies/TEST/intake/snapshots"
        / cik
        / accession.replace("-", "")
    )
    snapshot.mkdir(parents=True)
    _write(
        snapshot / "layer1_manifest.json",
        {
            "cik": cik,
            "accession": accession,
            "layer1_parser_version": "m2-layer1-v5",
            "package_sha256": package_sha,
        },
    )
    pl.DataFrame(
        {
            "fact_id": [duration_fact, exchange_fact],
            "filing_id": [filing_id, filing_id],
            "raw_concept_id": [duration_concept, exchange_concept],
            "context_id": [duration_context, exchange_context],
            "value_numeric": [None, None],
            "value_text": ["P1Y6M", "NASDAQ"],
            "is_nil": [False, False],
            "source_document": [primary_document, primary_document],
            "source_locator": [duration_locator, exchange_locator],
            "reported_or_derived": ["REPORTED", "REPORTED"],
            "raw_value": ["P1Y6M", "NASDAQ"],
        }
    ).write_parquet(snapshot / "fact.parquet")
    pl.DataFrame(
        {
            "raw_concept_id": [duration_concept, exchange_concept],
            "qname": ["test:ExpectedLife", "dei:SecurityExchangeName"],
            "data_type": [
                "xbrli:durationItemType",
                "dei:edgarExchangeCodeItemType",
            ],
        }
    ).write_parquet(snapshot / "concept.parquet")
    pl.DataFrame(
        {
            "context_id": [duration_context, exchange_context],
            "filing_id": [filing_id, filing_id],
        }
    ).write_parquet(snapshot / "context.parquet")
    intake = collection.parent / "companies/TEST/intake/history_intake.json"
    _write(
        intake,
        {
            "version": HISTORY_VERSION,
            "plan": local_plan,
            "complete": True,
            "filings": [
                {
                    "filing": filing,
                    "status": "INGESTED",
                    "source_run": str(intake.parent),
                    "ticker": ticker,
                }
            ],
        },
    )
    duration_index = _write(
        tmp_path / "duration-source-index.json",
        {
            "primary_document_count": 1,
            "missing_primary_documents": 0,
            "format_counts": {
                "durday": 0,
                "durmonth": 0,
                "duryear": 1,
                "durweek": 0,
            },
            "primary_documents": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "accession": accession,
                    "primary_document": primary_document,
                    "primary_sha256": primary_sha,
                }
            ],
            "duration_facts": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "accession": accession,
                    "primary_document": primary_document,
                    "format": "duryear",
                    "format_qname": "ixt-sec:duryear",
                    "namespace": SEC_TRANSFORM_NAMESPACE,
                    "format_namespace": SEC_TRANSFORM_NAMESPACE,
                    "source_id": "duration-source",
                    "concept_qname": "test:ExpectedLife",
                    "context_ref": "duration-context",
                    "source_lexical": "1.5",
                    "fact_id": duration_fact,
                }
            ],
        },
    )
    correction_index = _write(
        tmp_path / "correction-source-index.json",
        {
            "fact_count": 1,
            "unmatched": [],
            "facts": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "accession": accession,
                    "primary_document": primary_document,
                    "source_id": "exchange-source",
                    "source_lexical": "Nasdaq",
                    "source_locator": exchange_locator,
                    "source_element_type": "nonNumeric",
                    "source_scale": None,
                    "source_sign": None,
                    "format_qname": "ixt-sec:exchnameen",
                    "format_namespace": SEC_TRANSFORM_NAMESPACE,
                    "concept_qname": "dei:SecurityExchangeName",
                    "concept_data_type_qname": "dei:edgarExchangeCodeItemType",
                    "primary_sha256": primary_sha,
                    "filing_id": filing_id,
                    "fact_id": exchange_fact,
                    "context_id": exchange_context,
                    "raw_concept_id": exchange_concept,
                }
            ],
        },
    )
    return {
        "collection": collection,
        "packages": tmp_path / "packages",
        "duration": duration_index,
        "correction": correction_index,
        "package": package,
        "snapshot": snapshot,
    }


def _publish(paths: dict[str, Path], destination: Path):
    return publish_source_bindings(
        collection_manifest=paths["collection"],
        package_root=paths["packages"],
        duration_source_index=paths["duration"],
        correction_source_index=paths["correction"],
        destination=destination,
        producer_revision="a" * 40,
    )


def test_publish_and_verify_binds_source_bytes_and_v5_rows(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    publication = _publish(paths, tmp_path / "source-bindings")

    reader = SourceBindingsReader(publication.root)
    reader.verify_all()

    assert len(reader.duration_bindings()) == 1
    assert len(reader.approved_transform_corrections()) == 1
    assert reader.duration_bindings()[0]["source_lexical"] == "1.5"
    assert reader.approved_transform_corrections()[0]["source_lexical"] == "Nasdaq"
    assert reader.manifest["counts"] == {
        "companies": 1,
        "filings": 1,
        "duration_bindings": 1,
        "approved_transform_corrections": 1,
    }


@pytest.mark.parametrize(
    ("input_name", "field", "value", "message"),
    [
        ("duration", "source_id", "invented-source", "differs from primary"),
        ("duration", "source_lexical", "9.55", "differs from cached"),
        ("correction", "source_id", "invented-source", "differs from primary"),
        ("correction", "primary_sha256", "f" * 64, "identity differs"),
    ],
)
def test_producer_rejects_rehashed_candidate_source_claims(
    tmp_path: Path,
    input_name: str,
    field: str,
    value: str,
    message: str,
) -> None:
    paths = _fixture(tmp_path)
    path = paths[input_name]
    payload = json.loads(path.read_text())
    record_key = "duration_facts" if input_name == "duration" else "facts"
    payload[record_key][0][field] = value
    _write(path, payload)

    with pytest.raises(ValueError, match=message):
        _publish(paths, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_reader_rejects_changed_package_or_raw_table(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    publication = _publish(paths, tmp_path / "source-bindings")

    with paths["package"].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="package bytes changed"):
        SourceBindingsReader(publication.root).verify_all()

    paths = _fixture(tmp_path / "table-case")
    publication = _publish(paths, tmp_path / "table-case/source-bindings")
    facts = pl.read_parquet(paths["snapshot"] / "fact.parquet").with_columns(
        pl.when(pl.col("raw_value") == "P1Y6M")
        .then(pl.lit("P9Y"))
        .otherwise(pl.col("raw_value"))
        .alias("raw_value")
    )
    facts.write_parquet(paths["snapshot"] / "fact.parquet")
    with pytest.raises(ValueError, match="file integrity mismatch"):
        SourceBindingsReader(publication.root).verify_all()
