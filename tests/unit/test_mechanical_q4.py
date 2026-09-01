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
    MECHANICAL_Q4_VERSION,
    MechanicalQ4Error,
    MechanicalQ4Materializer,
    MechanicalQ4Publisher,
    MechanicalQ4Reader,
)
from sec_xbrl.longitudinal.materialization import (
    VerifiedLayer2Publication,
    _READER_ATTESTATION_TOKEN,
)


RULES = Layer2RuleVersions("period", "mapping", "recast", "selection")


def _release(
    *, namespace: str = "http://fasb.org/us-gaap/2025", denominator: object = None
) -> CorpusRelease:
    cik, filing_id = "0000320193", "f1"
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik},),
        "fact": tuple(
            {
                "filing_id": filing_id,
                "fact_id": fact_id,
                "raw_concept_id": "concept",
                "unit_id": "unit",
                "value_numeric": "100" if fact_id.startswith("fy") else "70",
            }
            for fact_id in ("fy", "ytd", "fy2", "ytd2")
        ),
        "concept": (
            {
                "filing_id": filing_id,
                "raw_concept_id": "concept",
                "period_type": "duration",
                "namespace_uri": namespace,
            },
        ),
        "unit": (
            {
                "filing_id": filing_id,
                "unit_id": "unit",
                "numerator_measures": "iso4217:USD",
                "denominator_measures": denominator,
            },
        ),
        "context": (),
        "dimension_fact": (),
        "role": (),
        "relationship": (),
    }
    manifest = Layer1SnapshotManifest(
        1, cik, "a", "10-K", "x", "a" * 64, "x", 4, 1, 0, 1, 1, 0, 0, 0, "x", "x"
    )
    inp = Layer1SnapshotInput(
        cik, "a", "10-K", "2025-11-01", "2025-09-30", "snap", sha256(b"x").hexdigest()
    )
    snapshot = CorpusSnapshot(
        inp,
        manifest,
        Path("/fixture/manifest"),
        MappingProxyType({}),
        MappingProxyType({key: len(value) for key, value in tables.items()}),
        MappingProxyType(
            {
                key: tuple(MappingProxyType(dict(row)) for row in value)
                for key, value in tables.items()
            }
        ),
    )
    return CorpusRelease(
        Path("/fixture"),
        "fixture",
        (cik,),
        (snapshot,),
        Layer2Run("fixture", "fixture", (inp,), RULES),
    )


def _fact(
    identifier: str,
    fact_id: str,
    period: str,
    value: str,
    *,
    dimensions: object = (),
    basis: str | None = None,
    bounds: tuple[str, str] = ("2024-09-29", "2025-09-28"),
) -> dict[str, object]:
    return {
        "analytical_fact_id": identifier,
        "cik": "0000320193",
        "view": "AS_FILED",
        "source_type": "REPORTED",
        "value_numeric": value,
        "company_canonical_concept_id": "company:detail",
        "company_canonical_dimension_key": dimensions,
        "basis_version": basis,
        "unit_semantics": "USD",
        "period_class": period,
        "period_key": f"{period}:{bounds[1]}",
        "actual_period_boundaries": (*bounds, None),
        "selected_fact_id": fact_id,
        "source_filing_id": "f1",
    }


def _publication(
    release: CorpusRelease, facts: tuple[dict[str, object], ...]
) -> VerifiedLayer2Publication:
    return VerifiedLayer2Publication(
        Path("/verified"),
        Path("/verified/manifest"),
        MappingProxyType(
            {
                "layer2_run_fingerprint": release.layer2_run.fingerprint,
                "layer2_manifest_sha256": "a" * 64,
            }
        ),
        release.ciks,
        MappingProxyType({"analytical_fact": tuple(MappingProxyType(row) for row in facts)}),
        _READER_ATTESTATION_TOKEN,
    )


def test_mechanical_q4_admits_custom_dimensioned_duration_with_flags() -> None:
    release = _release(namespace="https://example.com/company")
    facts = (
        _fact("fy", "fy", "FY", "100", dimensions=(("axis", "member"),), basis="recast-v2"),
        _fact(
            "ytd",
            "ytd",
            "YTD_9M",
            "70",
            dimensions=(("axis", "member"),),
            basis="recast-v2",
            bounds=("2024-09-29", "2025-06-29"),
        ),
    )
    candidate = (
        MechanicalQ4Materializer()
        .materialize(_publication(release, facts), release=release)
        .candidates[0]
    )
    assert candidate["value_numeric"] == "30"
    assert candidate["actual_period_boundaries"] == ("2025-06-29", "2025-09-28")
    assert set(candidate["review_flags"]) == {
        "BASIS_VERSION_PRESENT",
        "CUSTOM_CONCEPT",
        "DIMENSIONED",
        "PRIMARY_STATEMENT_PRE_ABSENT",
        "RECAST_SENSITIVE",
    }
    assert candidate["derivation_rule_version"] == MECHANICAL_Q4_VERSION


def test_mechanical_q4_rejects_denominator_and_fails_closed_for_ambiguity() -> None:
    release = _release(denominator="shares")
    facts = (
        _fact("fy", "fy", "FY", "100"),
        _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29")),
    )
    result = MechanicalQ4Materializer().materialize(_publication(release, facts), release=release)
    assert not result.candidates
    assert {row["exclusion_reason"] for row in result.exclusions} == {"Q4_SIMPLE_UNIT_REQUIRED"}

    release = _release()
    facts = facts + (
        _fact("fy2", "fy2", "FY", "100"),
        _fact("ytd2", "ytd2", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29")),
    )
    result = MechanicalQ4Materializer().materialize(_publication(release, facts), release=release)
    assert not result.candidates
    assert {row["exclusion_reason"] for row in result.exclusions} == {
        "Q4_AMBIGUOUS_COMPATIBLE_INPUT_PAIR"
    }
    assert {row["implicated_source_filing_ids"] for row in result.exclusions} == {
        ("f1", "f1", "f1", "f1")
    }


def test_mechanical_q4_publication_is_hash_bound_to_release(tmp_path: Path) -> None:
    release = _release()
    facts = (
        _fact("fy", "fy", "FY", "100"),
        _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29")),
    )
    upstream = _publication(release, facts)
    result = MechanicalQ4Materializer().materialize(upstream, release=release)
    published = MechanicalQ4Publisher().publish(
        result, output_root=tmp_path, run_version="run", upstream=upstream, release=release
    )
    loaded = MechanicalQ4Reader().load(published.run_root, upstream=upstream, release=release)
    assert loaded.candidates[0]["value_numeric"] == result.candidates[0]["value_numeric"]
    assert loaded.candidates[0]["input_source_fact_ids"] == ["fy", "ytd"]
    (published.run_root / "mechanical_q4_candidate.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(MechanicalQ4Error, match="content verification"):
        MechanicalQ4Reader().load(published.run_root, upstream=upstream, release=release)
