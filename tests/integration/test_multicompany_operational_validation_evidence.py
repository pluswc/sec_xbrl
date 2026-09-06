from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

PACK = Path(__file__).parents[2] / "docs/test-materials/multicompany-operational-validation-v1.json"


def _pack() -> dict[str, object]:
    return json.loads(PACK.read_text(encoding="utf-8"))


def _corpus_root(pack: dict[str, object]) -> Path:
    configured = os.environ.get("SEC_XBRL_CORPUS_ROOT")
    if configured:
        return Path(configured)
    relative_root = pack["local_corpus_evidence"]["processed_run_relative_root"]  # type: ignore[index]
    return Path(__file__).parents[2] / relative_root


def _manifest(root: Path, relative_path: str) -> dict[str, object]:
    if not root.is_dir():
        pytest.skip(f"local corpus evidence is unavailable: {root}")
    path = root / relative_path
    if not path.is_file():
        pytest.skip(f"local corpus evidence is unavailable: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_available_company_reference_filings_match_local_layer1_manifests() -> None:
    pack = _pack()
    root = _corpus_root(pack)
    for company in pack["companies"]:  # type: ignore[index]
        if company["layer1_status"] != "AVAILABLE":
            continue
        filing = company["reference_filing"]
        manifest = _manifest(root, filing["snapshot_manifest_relative_path"])
        assert manifest["cik"] == company["cik"]
        assert manifest["accession"] == filing["accession"]
        assert manifest["form"] == filing["form"]


def test_missing_companies_have_no_local_layer1_snapshot_in_this_frozen_run() -> None:
    pack = _pack()
    root = _corpus_root(pack)
    if not root.is_dir():
        pytest.skip(f"local corpus evidence is unavailable: {root}")
    for company in pack["companies"]:  # type: ignore[index]
        if company["layer1_status"] == "MISSING":
            assert not (root / "snapshots" / company["cik"]).exists()


def test_amd_original_and_amendment_match_distinct_local_layer1_manifests() -> None:
    pack = _pack()
    root = _corpus_root(pack)
    amendment = pack["amendment_case"]  # type: ignore[index]
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
