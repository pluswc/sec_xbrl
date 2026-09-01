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
    QuarterlyPeriodPolicyError,
    QuarterlyPeriodPolicyMaterializer,
    QuarterlyPolicyPublicationReader,
    QuarterlyPolicyPublisher,
    QuarterlySemanticDeclaration,
)
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication

RULES = Layer2RuleVersions("p", "m", "r", "s")


def _release(*, data_type: str = "monetaryItemType", unit: str = "iso4217:USD") -> CorpusRelease:
    cik, filing_id = "0000320193", "f1"
    facts = tuple(
        {"filing_id": filing_id, "fact_id": fact_id, "raw_concept_id": "rev", "unit_id": "usd"}
        for fact_id in ("fy", "ytd", "q1", "q2")
    )
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik},),
        "fact": facts,
        "concept": (
            {
                "filing_id": filing_id,
                "raw_concept_id": "rev",
                "period_type": "duration",
                "data_type": data_type,
            },
        ),
        "unit": (
            {
                "filing_id": filing_id,
                "unit_id": "usd",
                "numerator_measures": unit,
                "denominator_measures": None,
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
    dimensions: tuple = (),
    basis: str | None = None,
    unit: str = "USD",
    bounds: tuple[str, str, None] = ("2024-09-29", "2025-09-28", None),
) -> dict:
    return {
        "analytical_fact_id": identifier,
        "cik": "0000320193",
        "view": "AS_FILED",
        "source_type": "REPORTED",
        "value_numeric": value,
        "company_canonical_concept_id": "revenue",
        "company_canonical_dimension_key": dimensions,
        "basis_version": basis,
        "unit_semantics": unit,
        "period_class": period,
        "period_key": f"{period}:{bounds[1]}",
        "actual_period_boundaries": bounds,
        "selected_fact_id": fact_id,
        "source_filing_id": "f1",
    }


def _publication(release: CorpusRelease, facts: tuple[dict, ...]) -> VerifiedLayer2Publication:
    return VerifiedLayer2Publication(
        Path("/verified"),
        Path("/verified/manifest"),
        MappingProxyType(
            {
                "layer2_run_fingerprint": release.layer2_run.fingerprint,
                "layer2_manifest_sha256": "a" * 64,
            }
        ),
        ("0000320193",),
        MappingProxyType({"analytical_fact": tuple(MappingProxyType(row) for row in facts)}),
    )


def _policy() -> QuarterlySemanticDeclaration:
    return QuarterlySemanticDeclaration(
        "revenue", "REVIEWED_ADDITIVE_AMOUNT", "ADDITIVE_AMOUNT", True, "review:revenue"
    )


def test_q4_is_derived_only_from_declared_reviewed_compatible_monetary_flow() -> None:
    release = _release()
    fy = _fact("fy", "fy", "FY", "100", bounds=("2024-09-29", "2025-09-28", None))
    ytd = _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29", None))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, (fy, ytd)), release=release, declarations=(_policy(),)
    )
    assert result.q4_candidates[0]["value_numeric"] == "30"
    assert result.q4_candidates[0]["formula"] == "FY - YTD_9M"
    assert result.q4_candidates[0]["input_source_fact_ids"] == ("fy", "ytd")


def test_q4_accepts_list_serialized_dimensions_and_unit_semantics() -> None:
    release = _release()
    fy = _fact("fy", "fy", "FY", "100", dimensions=[["axis", "member"]], unit=["iso4217:USD"])
    ytd = _fact(
        "ytd",
        "ytd",
        "YTD_9M",
        "70",
        dimensions=[["axis", "member"]],
        unit=["iso4217:USD"],
        bounds=("2024-09-29", "2025-06-29", None),
    )
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, (fy, ytd)), release=release, declarations=(_policy(),)
    )
    assert result.q4_candidates[0]["value_numeric"] == "30"


def test_exact_declarations_keep_same_concept_members_separate() -> None:
    release = _release()
    product_dimensions = (("ProductOrServiceAxis", "ProductMember"),)
    service_dimensions = (("ProductOrServiceAxis", "ServiceMember"),)
    facts = (
        _fact("product-fy", "fy", "FY", "100", dimensions=product_dimensions),
        _fact(
            "product-ytd",
            "ytd",
            "YTD_9M",
            "70",
            dimensions=product_dimensions,
            bounds=("2024-09-29", "2025-06-29", None),
        ),
        _fact("service-fy", "q1", "FY", "50", dimensions=service_dimensions),
        _fact(
            "service-ytd",
            "q2",
            "YTD_9M",
            "40",
            dimensions=service_dimensions,
            bounds=("2024-09-29", "2025-06-29", None),
        ),
    )
    declarations = (
        QuarterlySemanticDeclaration(
            "revenue",
            "REVIEWED_ADDITIVE_AMOUNT",
            "ADDITIVE_AMOUNT",
            True,
            "review:product",
            cik="0000320193",
            company_canonical_dimension_key=product_dimensions,
            basis_version=None,
            unit_semantics="USD",
            scope_is_exact=True,
        ),
        QuarterlySemanticDeclaration(
            "revenue",
            "REVIEWED_ADDITIVE_AMOUNT",
            "ADDITIVE_AMOUNT",
            True,
            "review:service",
            cik="0000320193",
            company_canonical_dimension_key=service_dimensions,
            basis_version=None,
            unit_semantics="USD",
            scope_is_exact=True,
        ),
    )

    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, facts), release=release, declarations=declarations
    )

    assert {row["value_numeric"] for row in result.q4_candidates} == {"10", "30"}
    assert {
        tuple(tuple(item) for item in row["company_canonical_dimension_key"])
        for row in result.q4_candidates
    } == {product_dimensions, service_dimensions}


@pytest.mark.parametrize(
    ("data_type", "unit"),
    [
        ("sharesItemType", "shares"),
        ("perShareItemType", "iso4217:USD"),
        ("monetaryItemType", "shares"),
        ("monetaryItemType", "iso4217:USD,iso4217:EUR"),
    ],
)
def test_q4_rejects_shares_eps_ratios_and_nonmonetary_units(data_type: str, unit: str) -> None:
    release = _release(data_type=data_type, unit=unit)
    fy = _fact("fy", "fy", "FY", "100")
    ytd = _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29", None))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, (fy, ytd)), release=release, declarations=(_policy(),)
    )
    assert not result.q4_candidates
    assert {row["exclusion_reason"] for row in result.q4_exclusions} == {
        "Q4_REVIEWED_MONETARY_ADDITIVE_SEMANTICS_REQUIRED"
    }


@pytest.mark.parametrize("changed", ["dimensions", "basis", "unit"])
def test_q4_requires_exact_dimension_basis_and_unit_scope(changed: str) -> None:
    release = _release()
    fy = _fact("fy", "fy", "FY", "100", dimensions=(("axis", "a"),), basis="v1")
    kwargs = {
        changed: (("axis", "b"),)
        if changed == "dimensions"
        else "v2"
        if changed == "basis"
        else "EUR"
    }
    ytd = _fact(
        "ytd",
        "ytd",
        "YTD_9M",
        "70",
        dimensions=kwargs.get("dimensions", (("axis", "a"),)),
        basis=kwargs.get("basis", "v1"),
        unit=kwargs.get("unit", "USD"),
        bounds=("2024-09-29", "2025-06-29", None),
    )
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, (fy, ytd)), release=release, declarations=(_policy(),)
    )
    assert not result.q4_candidates


def test_predecessor_is_line_level_and_no_growth_is_created() -> None:
    release = _release()
    q1 = _fact("q1", "q1", "QTD_3M", "10", bounds=("2024-09-29", "2024-12-29", None))
    q2 = _fact("q2", "q2", "QTD_3M", "20", bounds=("2024-12-30", "2025-03-30", None))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        _publication(release, (q1, q2)), release=release, declarations=()
    )
    links = {row["analytical_fact_id"]: row for row in result.predecessor_linkage}
    assert links["q1"]["unavailable_reason"] == "PREDECESSOR_PERIOD_NOT_DECLARED"
    assert links["q2"]["predecessor_analytical_fact_id"] == "q1"
    assert not result.q4_candidates


def test_requires_matching_verified_release() -> None:
    release = _release()
    publication = _publication(release, (_fact("q1", "q1", "QTD_3M", "10"),))
    other = _release()
    other = CorpusRelease(
        other.corpus_root,
        other.corpus_run_id,
        other.ciks,
        other.snapshots,
        Layer2Run("other", "fixture", other.layer2_run.inputs, RULES),
    )
    with pytest.raises(QuarterlyPeriodPolicyError, match="does not match"):
        QuarterlyPeriodPolicyMaterializer().materialize(publication, release=other, declarations=())


def test_companion_publication_is_atomic_and_linked_to_verified_c3_m1(tmp_path: Path) -> None:
    release = _release()
    fy = _fact("fy", "fy", "FY", "100")
    ytd = _fact("ytd", "ytd", "YTD_9M", "70", bounds=("2024-09-29", "2025-06-29", None))
    publication = _publication(release, (fy, ytd))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        publication, release=release, declarations=(_policy(),)
    )
    published = QuarterlyPolicyPublisher().publish(
        result, output_root=tmp_path, run_version="c3-m2-fixture", upstream=publication
    )
    manifest = (published.run_root / "quarterly_policy_manifest.json").read_text(encoding="utf-8")
    assert release.layer2_run.fingerprint in manifest
    assert published.output_counts["quarterly_q4_candidate"] == 1
    reread = QuarterlyPolicyPublicationReader().load(published.run_root, upstream=publication)
    assert (
        reread.q4_candidates[0]["quarterly_policy_candidate_id"]
        == result.q4_candidates[0]["quarterly_policy_candidate_id"]
    )


def test_companion_reader_rejects_same_run_with_different_upstream_manifest(tmp_path: Path) -> None:
    release = _release()
    publication = _publication(release, (_fact("q1", "q1", "QTD_3M", "10"),))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        publication, release=release, declarations=()
    )
    published = QuarterlyPolicyPublisher().publish(
        result, output_root=tmp_path, run_version="c3-m2-fixture", upstream=publication
    )
    mismatched = VerifiedLayer2Publication(
        publication.run_root,
        publication.manifest_path,
        MappingProxyType(
            {
                "layer2_run_fingerprint": release.layer2_run.fingerprint,
                "layer2_manifest_sha256": "b" * 64,
            }
        ),
        publication.input_ciks,
        publication.datasets,
    )
    with pytest.raises(QuarterlyPeriodPolicyError, match="manifest"):
        QuarterlyPolicyPublicationReader().load(published.run_root, upstream=mismatched)


def test_companion_reader_rejects_extra_layout_file(tmp_path: Path) -> None:
    release = _release()
    publication = _publication(release, (_fact("q1", "q1", "QTD_3M", "10"),))
    result = QuarterlyPeriodPolicyMaterializer().materialize(
        publication, release=release, declarations=()
    )
    published = QuarterlyPolicyPublisher().publish(
        result, output_root=tmp_path, run_version="c3-m2-fixture", upstream=publication
    )
    (published.run_root / "unexpected.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(QuarterlyPeriodPolicyError, match="layout"):
        QuarterlyPolicyPublicationReader().load(published.run_root, upstream=publication)
