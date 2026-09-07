from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.facts.layer1 import select_fact_corpus
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndexCache, FilingPackageResolver
from sec_xbrl.filing.package_cache import AccessionPackageCache

PACK = Path(__file__).parents[2] / "docs/test-materials/multicompany-operational-validation-v1.json"


def _pack() -> dict[str, object]:
    return json.loads(PACK.read_text(encoding="utf-8"))


def _corpus_root(company: dict[str, object]) -> Path:
    configured = os.environ.get("SEC_XBRL_CORPUS_ROOT")
    if configured:
        return Path(configured)
    relative_root = company["layer1_evidence"]["processed_run_relative_root"]  # type: ignore[index]
    data_root = Path(os.environ.get("SEC_XBRL_DATA_ROOT", Path(__file__).parents[2]))
    return data_root / relative_root


def _manifest(root: Path, relative_path: str) -> dict[str, object]:
    if not root.is_dir():
        pytest.skip(f"local corpus evidence is unavailable: {root}")
    path = root / relative_path
    if not path.is_file():
        pytest.skip(f"local corpus evidence is unavailable: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _filing_row(root: Path, manifest_relative_path: str) -> dict[str, object]:
    manifest_path = root / manifest_relative_path
    if not manifest_path.is_file():
        pytest.skip(f"local corpus evidence is unavailable: {manifest_path}")
    filing_path = manifest_path.with_name("filing.parquet")
    if not filing_path.is_file():
        pytest.skip(f"local corpus filing evidence is unavailable: {filing_path}")
    rows = pl.read_parquet(filing_path).select(
        "cik", "accession", "form", "filed_date", "report_date", "is_amendment"
    ).to_dicts()
    assert len(rows) == 1
    return rows[0]


class _NoNetworkFetcher:
    """Makes a cached-package test fail if resolution tries the network."""

    def fetch(self, url: str) -> bytes:
        raise AssertionError(f"offline evidence test attempted network fetch: {url}")


def test_available_company_reference_filings_match_local_layer1_manifests() -> None:
    pack = _pack()
    for company in pack["companies"]:  # type: ignore[index]
        if company["layer1_status"] != "AVAILABLE":
            continue
        root = _corpus_root(company)
        filing = company["reference_filing"]
        manifest = _manifest(root, filing["snapshot_manifest_relative_path"])
        assert manifest["cik"] == company["cik"]
        assert manifest["accession"] == filing["accession"]
        assert manifest["form"] == filing["form"]
        assert manifest["source_fact_count"] == filing.get("source_fact_count", manifest["source_fact_count"])


def test_available_companies_have_declared_snapshot_evidence() -> None:
    pack = _pack()
    for company in pack["companies"]:  # type: ignore[index]
        assert company["layer1_status"] == "AVAILABLE"
        root = _corpus_root(company)
        filing = company["reference_filing"]
        assert _manifest(root, filing["snapshot_manifest_relative_path"])["accession"] == filing["accession"]


def test_declared_snapshot_counts_match_this_frozen_local_corpus_run() -> None:
    pack = _pack()
    for company in pack["companies"]:  # type: ignore[index]
        root = _corpus_root(company)
        if not root.is_dir():
            pytest.skip(f"local corpus evidence is unavailable: {root}")
        snapshot_root = root / "snapshots" / company["cik"]
        actual_count = len(list(snapshot_root.glob("*/layer1_manifest.json"))) if snapshot_root.is_dir() else 0
        assert actual_count == company["available_snapshot_count"]


def test_amd_original_and_amendment_match_distinct_local_layer1_manifests() -> None:
    pack = _pack()
    amendment = pack["amendment_case"]  # type: ignore[index]
    amd = next(company for company in pack["companies"] if company["ticker"] == "AMD")  # type: ignore[index]
    root = _corpus_root(amd)
    original = amendment["original_filing"]
    amended = amendment["amendment_filing"]
    original_manifest = _manifest(root, original["snapshot_manifest_relative_path"])
    amended_manifest = _manifest(root, amended["snapshot_manifest_relative_path"])
    assert original_manifest["cik"] == amendment["cik"]
    assert amended_manifest["cik"] == amendment["cik"]
    assert original_manifest["accession"] == original["accession"]
    assert amended_manifest["accession"] == amended["accession"]
    assert original_manifest["form"] == "10-K"
    assert amended_manifest["form"] == "10-K/A"
    assert original_manifest["accession"] != amended_manifest["accession"]
    original_filing = _filing_row(root, original["snapshot_manifest_relative_path"])
    amended_filing = _filing_row(root, amended["snapshot_manifest_relative_path"])
    for expected, actual in ((original, original_filing), (amended, amended_filing)):
        assert actual["cik"] == amendment["cik"]
        assert actual["accession"] == expected["accession"]
        assert actual["form"] == expected["form"]
        assert actual["filed_date"] == expected["filed_date"]
        assert actual["report_date"] == expected["report_date"]
        assert actual["is_amendment"] is expected["is_amendment"]


def test_msft_cached_package_reloads_offline_with_existing_taxonomy_cache(tmp_path: Path) -> None:
    """Prove the successful MSFT evidence can be parsed again without a request or publication."""
    pack = _pack()
    msft = next(company for company in pack["companies"] if company["ticker"] == "MSFT")  # type: ignore[index]
    root = _corpus_root(msft)
    filing = msft["reference_filing"]
    data_root = Path(os.environ.get("SEC_XBRL_DATA_ROOT", Path(__file__).parents[2]))
    raw_root = data_root / "data/raw/operational_cohort_runs" / msft["layer1_evidence"]["run_id"]  # type: ignore[index]
    taxonomy_cache = data_root / "data/taxonomy_cache"
    accession_nodash = filing["accession"].replace("-", "")
    required = (
        raw_root / "packages" / msft["cik"] / accession_nodash / f"{filing['accession']}-xbrl.zip",
        raw_root / "indexes" / msft["cik"] / accession_nodash / "index.json",
        taxonomy_cache,
        root / filing["snapshot_manifest_relative_path"],
    )
    if not all(path.exists() for path in required):
        pytest.skip("actual MSFT package, taxonomy cache, or snapshot evidence is unavailable")

    filing_ref = FilingRef(
        cik=msft["cik"], accession=filing["accession"], form=filing["form"],
        filed_date=date.fromisoformat(filing["filed_date"]),
        report_date=date.fromisoformat(filing["report_date"]),
        primary_document="msft-20240930.htm", source="sec_submissions",
    )
    resolver = FilingPackageResolver(
        AccessionPackageCache(raw_root / "packages"), FilingIndexCache(raw_root / "indexes"),
    )
    resolved = resolver.resolve(filing_ref, _NoNetworkFetcher())
    loader = ArelleFilingLoader(taxonomy_cache=taxonomy_cache, allow_network_taxonomy_resolution=False)
    model = loader.load(resolved, tmp_path / "offline_msft_extraction")
    try:
        errors = tuple(str(error) for error in (getattr(model, "errors", None) or ()))
        assert not any("ioerror" in error.lower() or "unresolved" in error.lower() for error in errors)
        corpus = select_fact_corpus(model)
        assert corpus.source == "model.facts"
        assert corpus.source_count == filing["source_fact_count"] == 1236
        assert all(getattr(fact, "concept", None) is not None for fact in corpus.facts)
    finally:
        model_manager = getattr(model, "modelManager", None)
        if model_manager is not None:
            model_manager.close()
