from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import polars as pl
import pytest
from lxml import html as lxml_html

from sec_xbrl import collection_operations as operations
from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.history import HISTORY_VERSION
from sec_xbrl.metric_quality import (
    CONFIG_SCHEMA_VERSION,
    GenericMetricQualityReader,
    prepare_generic_metric_quality,
)
from sec_xbrl.source_bindings import (
    SEC_TRANSFORM_NAMESPACE,
    SourceBindingsReader,
    SourceBindingsV2Reader,
    publish_source_bindings,
    publish_source_bindings_v2,
    write_source_indexes_v2,
)


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(
    tmp_path: Path,
    *,
    ticker: str = "TEST",
    cik: str = "0000000123",
    accession: str = "0000000123-26-000001",
    parser_version: str = "m2-layer1-v5",
) -> dict[str, Path]:
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
    local_plan = json.loads((collection.parent / f"companies/{ticker}/plan.json").read_text())

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
        / f"companies/{ticker}/intake/snapshots"
        / cik
        / accession.replace("-", "")
    )
    snapshot.mkdir(parents=True)
    _write(
        snapshot / "layer1_manifest.json",
        {
            "cik": cik,
            "accession": accession,
            "layer1_parser_version": parser_version,
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
    intake = collection.parent / f"companies/{ticker}/intake/history_intake.json"
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
        "intake": intake,
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


def _mixed_v2_fixture(tmp_path: Path) -> dict[str, object]:
    first = _fixture(
        tmp_path / "first",
        ticker="FIVE",
        cik="0000000123",
        accession="0000000123-26-000001",
        parser_version="m2-layer1-v5",
    )
    second = _fixture(
        tmp_path / "second",
        ticker="SIX",
        cik="0000000456",
        accession="0000000456-26-000002",
        parser_version="m2-layer1-v6",
    )
    config = _write(
        tmp_path / "mixed-config.json",
        {
            "schema_version": 1,
            "universe_id": "mixed-source-binding-fixture",
            "purpose": "fixture",
            "as_of_date": "2026-10-08",
            "source_observed_at": "2026-10-08T00:00:00+00:00",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [
                {"ticker": "FIVE", "cik": "0000000123", "groups": ["fixture"]},
                {"ticker": "SIX", "cik": "0000000456", "groups": ["fixture"]},
            ],
        },
    )
    mixed = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "mixed-run",
        existing_plans={
            "FIVE": Path(first["collection"]).parent / "companies/FIVE/plan.json",
            "SIX": Path(second["collection"]).parent / "companies/SIX/plan.json",
        },
    )
    for ticker, source in (("FIVE", first), ("SIX", second)):
        plan = json.loads(
            (mixed.parent / f"companies/{ticker}/plan.json").read_text()
        )
        original_intake = json.loads(Path(source["intake"]).read_text())
        original_intake["plan"] = plan
        _write(
            mixed.parent / f"companies/{ticker}/intake/history_intake.json",
            original_intake,
        )
    packages = tmp_path / "mixed-packages"
    for source in (first, second):
        package = Path(source["package"])
        destination = packages / package.relative_to(Path(source["packages"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, destination)
    return {"collection": mixed, "packages": packages, "first": first, "second": second}


def test_v2_mixed_profiles_are_derived_from_each_snapshot_and_reopened(
    tmp_path: Path,
) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    indexes = write_source_indexes_v2(
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        destination=tmp_path / "indexes",
    )
    publication = publish_source_bindings_v2(
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        duration_source_index=indexes.duration_path,
        correction_source_index=indexes.correction_path,
        destination=tmp_path / "bindings-v2",
        producer_revision="b" * 40,
    )

    reader = SourceBindingsV2Reader(publication.root)
    reader.verify_all()

    with pytest.raises(ValueError, match="unsupported source-binding publication"):
        SourceBindingsReader(publication.root)

    assert [row["parser_version"] for row in reader.manifest["parser_profiles"]] == [
        "m2-layer1-v5",
        "m2-layer1-v6",
    ]
    assert reader.manifest["collection_scope_mode"] == "FULL"
    assert reader.manifest["counts"]["filings"] == 2


def test_v2_requires_explicit_subset_and_rejects_unknown_parser(tmp_path: Path) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    subset = ({"ticker": "FIVE", "cik": "0000000123"},)
    indexes = write_source_indexes_v2(
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        destination=tmp_path / "subset-indexes",
        collection_scope_companies=subset,
    )
    publication = publish_source_bindings_v2(
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        duration_source_index=indexes.duration_path,
        correction_source_index=indexes.correction_path,
        destination=tmp_path / "subset-bindings",
        producer_revision="c" * 40,
        collection_scope_companies=subset,
    )
    reader = SourceBindingsV2Reader(publication.root)
    reader.verify_all()
    assert reader.manifest["collection_scope_mode"] == "EXPLICIT_SUBSET"
    assert reader.manifest["scope_companies"] == list(subset)

    unknown = Path(paths["second"]["snapshot"]) / "layer1_manifest.json"
    payload = json.loads(unknown.read_text())
    payload["layer1_parser_version"] = "m2-layer1-v7-self-declared"
    _write(unknown, payload)
    with pytest.raises(ValueError, match="known snapshot/package profile"):
        write_source_indexes_v2(
            collection_manifest=Path(paths["collection"]),
            package_root=Path(paths["packages"]),
            destination=tmp_path / "rejected-indexes",
        )
    assert not (tmp_path / "rejected-indexes").exists()


def test_v2_independent_scan_rejects_incomplete_candidate_index(tmp_path: Path) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    indexes = write_source_indexes_v2(
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        destination=tmp_path / "indexes",
    )
    payload = json.loads(indexes.duration_path.read_text())
    payload["duration_facts"].pop()
    _write(indexes.duration_path, payload)

    with pytest.raises(ValueError, match="differs from primary document"):
        publish_source_bindings_v2(
            collection_manifest=Path(paths["collection"]),
            package_root=Path(paths["packages"]),
            duration_source_index=indexes.duration_path,
            correction_source_index=indexes.correction_path,
            destination=tmp_path / "rejected-bindings",
            producer_revision="d" * 40,
        )
    assert not (tmp_path / "rejected-bindings").exists()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_ready_histories(
    paths: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    selected_tickers: tuple[str, ...] | None = None,
) -> dict[str, Path]:
    def build(**kwargs: object) -> Path:
        output_root = Path(kwargs["output_root"])
        intake_path = Path(kwargs["intake_manifest"])
        intake = json.loads(intake_path.read_text())
        publication = output_root / "panels"
        company = intake["plan"]["companies"][0]
        relative = (
            Path(company["cik"])
            / "LATEST_REPORTED/QTD_3M/rows.parquet"
        )
        info = operations.history._write_records(
            publication / relative, ({"row_id": company["ticker"]},)
        )
        _write(
            publication / "history_manifest.json",
            {
                "version": operations.history.HISTORY_VERSION,
                "plan": intake["plan"],
                "views": list(kwargs["views"]),
                "source_intake": str(intake_path.absolute()),
                "tables": [{"files": {"rows": {**info, "path": str(relative)}}}],
            },
        )
        return publication

    monkeypatch.setattr(operations.history, "build_history", build)
    output = tmp_path / "histories"
    operations.build_universe(
        manifest_path=Path(paths["collection"]),
        output_root=output,
        selected_tickers=selected_tickers,
    )
    selected = selected_tickers or ("FIVE", "SIX")
    return {
        ticker: output / ticker / "panels/history_manifest.json"
        for ticker in selected
    }


def _quality_config(
    paths: dict[str, object],
    histories: dict[str, Path],
    destination: Path,
    *,
    companies: tuple[dict[str, str], ...],
) -> Path:
    collection = json.loads(Path(paths["collection"]).read_text())
    collection_index = {row["ticker"]: row for row in collection["companies"]}
    return _write(
        destination,
        {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "financial_as_of": "2026-10-08",
            "collection_scope_companies": list(companies),
            "source_provenance": [
                {
                    "ticker": company["ticker"],
                    "cik": company["cik"],
                    "collector_source_commit_sha": (
                        "1d3a068feb74b43145df3abcb506b1285cdf6353"
                        if company["ticker"] == "FIVE"
                        else "4077e87097c294ed779186b613157839f215a63e"
                    ),
                    "plan_sha256": collection_index[company["ticker"]]["plan_sha256"],
                    "intake_sha256": _sha256(
                        Path(paths["collection"]).parent
                        / f"companies/{company['ticker']}/intake/history_intake.json"
                    ),
                    "history_manifest_sha256": _sha256(histories[company["ticker"]]),
                }
                for company in companies
            ],
        },
    )


def test_generic_quality_subset_pass_reopens_all_source_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    histories = _build_ready_histories(
        paths, tmp_path, monkeypatch, selected_tickers=("FIVE",)
    )
    companies = ({"ticker": "FIVE", "cik": "0000000123"},)
    config = _quality_config(
        paths, histories, tmp_path / "quality-config.json", companies=companies
    )
    publication = prepare_generic_metric_quality(
        config_path=config,
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        history_manifests=histories,
        source_index_destination=tmp_path / "quality-indexes",
        source_binding_destination=tmp_path / "quality-bindings",
        destination=tmp_path / "quality",
        producer_revision="e" * 40,
    )

    reader = GenericMetricQualityReader(
        publication.root, manifest_sha256=_sha256(publication.manifest_path)
    )
    result = reader.verify_sources(
        collection_manifest=Path(paths["collection"]),
        history_manifest_sha256s={"FIVE": _sha256(histories["FIVE"])},
        financial_as_of="2026-10-08",
        expected_companies=companies,
    )

    assert result["state"] == "PASS"
    assert result["filing_count"] == 1
    assert reader.manifest["collection_scope_mode"] == "EXPLICIT_SUBSET"
    assert reader.manifest["assurance_scope"] == "RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY"
    assert reader.manifest["full_financial_semantic_assurance"] is False
    status = operations.read_universe_status(manifest_path=Path(paths["collection"]))
    assert {row.ticker: row.state for row in status.companies} == {
        "FIVE": "READY",
        "SIX": "RAW_COMPLETE",
    }


def test_generic_quality_full_mixed_v5_v6_fresh_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    histories = _build_ready_histories(paths, tmp_path, monkeypatch)
    companies = (
        {"ticker": "FIVE", "cik": "0000000123"},
        {"ticker": "SIX", "cik": "0000000456"},
    )
    config = _quality_config(
        paths, histories, tmp_path / "mixed-quality-config.json", companies=companies
    )
    publication = prepare_generic_metric_quality(
        config_path=config,
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        history_manifests=histories,
        source_index_destination=tmp_path / "mixed-quality-indexes",
        source_binding_destination=tmp_path / "mixed-quality-bindings",
        destination=tmp_path / "mixed-quality",
        producer_revision="e" * 40,
    )
    reader = GenericMetricQualityReader(publication.root)

    assert reader.verify_sources(
        collection_manifest=Path(paths["collection"]),
        history_manifest_sha256s={
            ticker: _sha256(path) for ticker, path in histories.items()
        },
        financial_as_of="2026-10-08",
        expected_companies=companies,
    )["state"] == "PASS"
    assert reader.manifest["collection_scope_mode"] == "FULL"
    assert [row["parser_version"] for row in reader.manifest["parser_profiles"]] == [
        "m2-layer1-v5",
        "m2-layer1-v6",
    ]
    assert reader.manifest["filing_count"] == 2


def test_generic_quality_rejects_history_scope_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    histories = _build_ready_histories(
        paths, tmp_path, monkeypatch, selected_tickers=("FIVE",)
    )
    companies = ({"ticker": "FIVE", "cik": "0000000123"},)
    config = _quality_config(
        paths, histories, tmp_path / "quality-config.json", companies=companies
    )
    with pytest.raises(ValueError, match="accepted history manifests differ"):
        prepare_generic_metric_quality(
            config_path=config,
            collection_manifest=Path(paths["collection"]),
            package_root=Path(paths["packages"]),
            history_manifests={**histories, "SIX": histories["FIVE"]},
            source_index_destination=tmp_path / "failed-indexes",
            source_binding_destination=tmp_path / "failed-bindings",
            destination=tmp_path / "failed-quality",
            producer_revision="e" * 40,
        )
    assert not (tmp_path / "failed-quality").exists()


def test_generic_quality_rejects_cutoff_before_any_output(tmp_path: Path) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    config = _write(
        tmp_path / "wrong-cutoff.json",
        {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "financial_as_of": "2026-10-09",
            "collection_scope_companies": [
                {"ticker": "FIVE", "cik": "0000000123"}
            ],
            "source_provenance": [
                {
                    "ticker": "FIVE",
                    "cik": "0000000123",
                    "collector_source_commit_sha": "f" * 40,
                    "plan_sha256": "a" * 64,
                    "intake_sha256": "b" * 64,
                    "history_manifest_sha256": "c" * 64,
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="cutoff differs"):
        prepare_generic_metric_quality(
            config_path=config,
            collection_manifest=Path(paths["collection"]),
            package_root=Path(paths["packages"]),
            history_manifests={},
            source_index_destination=tmp_path / "cutoff-indexes",
            source_binding_destination=tmp_path / "cutoff-bindings",
            destination=tmp_path / "cutoff-quality",
            producer_revision="f" * 40,
        )
    assert not (tmp_path / "cutoff-quality").exists()


def test_generic_quality_rejects_raw_normalization_mismatch_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _mixed_v2_fixture(tmp_path)
    histories = _build_ready_histories(
        paths, tmp_path, monkeypatch, selected_tickers=("FIVE",)
    )
    companies = ({"ticker": "FIVE", "cik": "0000000123"},)
    config = _quality_config(
        paths, histories, tmp_path / "quality-config.json", companies=companies
    )
    facts_path = Path(paths["first"]["snapshot"]) / "fact.parquet"
    facts = pl.read_parquet(facts_path).with_columns(
        pl.when(pl.col("raw_value") == "P1Y6M")
        .then(pl.lit("P9Y"))
        .otherwise(pl.col("raw_value"))
        .alias("raw_value"),
        pl.when(pl.col("value_text") == "P1Y6M")
        .then(pl.lit("P9Y"))
        .otherwise(pl.col("value_text"))
        .alias("value_text"),
    )
    facts.write_parquet(facts_path)

    with pytest.raises(ValueError, match="conformance did not pass"):
        prepare_generic_metric_quality(
            config_path=config,
            collection_manifest=Path(paths["collection"]),
            package_root=Path(paths["packages"]),
            history_manifests=histories,
            source_index_destination=tmp_path / "mismatch-indexes",
            source_binding_destination=tmp_path / "mismatch-bindings",
            destination=tmp_path / "mismatch-quality",
            producer_revision="f" * 40,
        )
    assert not (tmp_path / "mismatch-quality").exists()
