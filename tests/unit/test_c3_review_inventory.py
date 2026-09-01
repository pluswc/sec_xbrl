from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    CorpusRelease,
    CorpusSnapshot,
    Layer1SnapshotInput,
    Layer2RuleVersions,
    Layer2Run,
    ReviewInventoryError,
    ReviewInventoryMaterializer,
    ReviewInventoryPublicationReader,
    ReviewInventoryPublisher,
)
from sec_xbrl.longitudinal.materialization import (
    _READER_ATTESTATION_TOKEN,
    VerifiedLayer2Publication,
)


def _release() -> CorpusRelease:
    cik, filing_id = "0000320193", "f1"
    tables = {"filing": ({"filing_id": filing_id, "cik": cik},),
              "fact": tuple({"filing_id": filing_id, "fact_id": x, "raw_concept_id": "rev", "unit_id": "usd"} for x in ("fy", "ytd")),
              "concept": ({"filing_id": filing_id, "raw_concept_id": "rev", "period_type": "duration", "data_type": "monetaryItemType", "namespace_uri": "http://fasb.org/us-gaap/2024", "local_name": "Revenues"},),
              "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
              "context": (), "dimension_fact": (),
              "role": ({"filing_id": filing_id, "role_id": "operations", "role_definition": "Consolidated Statements of Operations"},),
              "relationship": ({"filing_id": filing_id, "network_type": "PRE", "role_id": "operations", "to_raw_concept_id": "rev", "relationship_id": "pre-revenues"},)}
    manifest = Layer1SnapshotManifest(1, cik, "a", "10-K", "x", "a" * 64, "x", 2, 1, 0, 1, 1, 0, 0, 0, "x", "x")
    inp = Layer1SnapshotInput(cik, "a", "10-K", "2025-11-01", "2025-09-30", "snap", sha256(b"x").hexdigest())
    snapshot = CorpusSnapshot(inp, manifest, Path("/fixture/manifest"), MappingProxyType({}), MappingProxyType({k: len(v) for k, v in tables.items()}), MappingProxyType({k: tuple(MappingProxyType(dict(x)) for x in v) for k, v in tables.items()}))
    run = Layer2Run("fixture", "fixture", (inp,), Layer2RuleVersions("p", "m", "r", "s"))
    return CorpusRelease(Path("/fixture"), "fixture", (cik,), (snapshot,), run)


def _fact(identifier: str, raw: str, period: str, value: str, *, bounds: tuple[str, str, None]) -> dict:
    return {"analytical_fact_id": identifier, "cik": "0000320193", "view": "AS_FILED", "source_type": "REPORTED", "value_numeric": value,
            "company_canonical_concept_id": "revenue", "company_canonical_dimension_key": (), "basis_version": None,
            "unit_semantics": "USD", "period_class": period, "period_key": f"{period}:{bounds[1]}", "actual_period_boundaries": bounds,
            "selected_fact_id": raw, "source_filing_id": "f1"}


def _publication(release, *, changed_cik: str | None = None, dimensions: object = ()) -> VerifiedLayer2Publication:
    cik = changed_cik or "0000320193"
    fy = _fact("fy", "fy", "FY", "100", bounds=("2024-09-29", "2025-09-28", None))
    ytd = _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29", None))
    fy["cik"] = ytd["cik"] = cik
    fy["company_canonical_dimension_key"] = ytd["company_canonical_dimension_key"] = dimensions
    candidate = {"series_candidate_id": "later", "cik": cik, "company_canonical_concept_id": "revenue",
                 "company_canonical_dimension_key": (), "period_class": "FY", "actual_period_key": fy["period_key"],
                 "basis_version": None, "unit_semantics": "USD", "source_filing_id": "later-filing",
                 "source_fact_id": "later-fact", "filed_date": "2026-01-01"}
    return VerifiedLayer2Publication(Path("/verified"), Path("/verified/m"), MappingProxyType({"layer2_run_fingerprint": release.layer2_run.fingerprint, "layer2_manifest_sha256": "a" * 64}), (cik,), MappingProxyType({"analytical_fact": tuple(MappingProxyType(x) for x in (fy, ytd)), "current_series_candidate": (MappingProxyType(candidate),)}), _READER_ATTESTATION_TOKEN)


def test_inventory_is_pending_only_and_has_no_q4_value() -> None:
    release = _release()
    result = ReviewInventoryMaterializer().materialize(_publication(release), release=release)
    assert result.q4_candidates[0]["review_status"] == "PENDING_SEMANTIC_REVIEW"
    assert result.q4_candidates[0]["value_numeric"] is None
    assert result.q4_candidates[0]["formula"] is None
    assert result.recast_candidates[0]["review_status"] == "PENDING_EVIDENCE_REVIEW"
    assert result.recast_candidates[0]["recast_claim"] == "NOT_MADE"
    assert {row["artifact_status"] for row in result.artifact_coverage} == {"ARTIFACT_NOT_RETAINED"}


def test_reader_rejects_tampering_and_upstream_mismatch(tmp_path: Path) -> None:
    release = _release()
    upstream = _publication(release)
    result = ReviewInventoryMaterializer().materialize(upstream, release=release)
    published = ReviewInventoryPublisher().publish(result, output_root=tmp_path, run_version="review", upstream=upstream, release=release)
    assert ReviewInventoryPublicationReader().load(published.run_root, upstream=upstream, release=release).q4_candidates
    (published.run_root / "q4_review_candidate.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ReviewInventoryError, match="content"):
        ReviewInventoryPublicationReader().load(published.run_root, upstream=upstream, release=release)


def test_rejects_forged_or_cross_company_input() -> None:
    release = _release()
    forged = VerifiedLayer2Publication(Path("/x"), Path("/x/m"), MappingProxyType({}), (), MappingProxyType({}))
    with pytest.raises(ReviewInventoryError, match="reader-attested"):
        ReviewInventoryMaterializer().materialize(forged, release=release)
    with pytest.raises(ReviewInventoryError, match="does not match"):
        ReviewInventoryMaterializer().materialize(_publication(release, changed_cik="0001045810"), release=release)
