"""Optional real-cache integration; it never downloads SEC material."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sec_xbrl.pilots.amd_msft_meta_p1 import load_pilot_manifest
from sec_xbrl.pilots.amd_msft_meta_p3 import PilotP3Runner


@pytest.mark.integration
def test_p3_builds_from_the_validated_p1_cache() -> None:
    cache = os.environ.get("SEC_XBRL_P1_CACHE")
    if not cache:
        pytest.skip("SEC_XBRL_P1_CACHE is required for the explicit local cache integration test")
    root = Path(cache)
    if not (root / "packages").is_dir() or not (root / "filing-indexes").is_dir():
        pytest.skip("SEC_XBRL_P1_CACHE does not contain a validated P1 package and index cache")
    manifest = Path(__file__).parents[2] / "docs/pilots/amd-msft-meta-filing-manifest.json"

    review = PilotP3Runner(cache_root=root).run(load_pilot_manifest(manifest))

    assert {row.ticker for row in review.comparisons} == {"AMD", "MSFT", "META"}
    assert all(row.source_raw_id.startswith("as-filed-inline-fact:") for row in review.comparisons)
    assert all(row.company_canonical_id.startswith("UNMAPPED") for row in review.comparisons)
