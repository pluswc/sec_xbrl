from pathlib import Path

import pytest
from test_c3_review_inventory import _publication, _release

from sec_xbrl.longitudinal import (
    Q4PolicyRegistryError,
    Q4PolicyRegistryMaterializer,
    Q4PolicyRegistryPublisher,
    Q4PolicyRegistryReader,
    QuarterlyPeriodPolicyError,
    QuarterlyPeriodPolicyV2Materializer,
    QuarterlyPolicyV2Publisher,
    QuarterlyPolicyV2Reader,
)


def _published(tmp_path: Path):
    release = _release()
    upstream = _publication(release)
    registry = Q4PolicyRegistryMaterializer().materialize(upstream, release=release, effective_from="2026-01-01")
    reg = Q4PolicyRegistryPublisher().publish(registry, output_root=tmp_path, run_version="reg", upstream=upstream, release=release)
    result = QuarterlyPeriodPolicyV2Materializer().materialize(upstream, release=release, registry_root=reg.run_root)
    policy = QuarterlyPolicyV2Publisher().publish(result, output_root=tmp_path, run_version="m2", upstream=upstream, release=release, registry_root=reg.run_root)
    return release, upstream, reg, policy


def test_registry_reader_rejects_tamper_and_m2_reader_rejects_tamper(tmp_path: Path) -> None:
    release, upstream, reg, policy = _published(tmp_path)
    assert Q4PolicyRegistryReader().load(reg.run_root, upstream=upstream, release=release)
    assert QuarterlyPolicyV2Reader().load(policy.run_root, upstream=upstream, release=release, registry_root=reg.run_root)
    (reg.run_root / "approved_q4_declaration.jsonl").write_text("{}\n")
    with pytest.raises(Q4PolicyRegistryError, match="content"):
        Q4PolicyRegistryReader().load(reg.run_root, upstream=upstream, release=release)


def test_m2_reader_rejects_registry_manifest_and_dataset_change(tmp_path: Path) -> None:
    release, upstream, reg, policy = _published(tmp_path)
    (policy.run_root / "quarterly_q4_candidate.jsonl").write_text("{}\n")
    with pytest.raises(QuarterlyPeriodPolicyError, match="content"):
        QuarterlyPolicyV2Reader().load(policy.run_root, upstream=upstream, release=release, registry_root=reg.run_root)
    release, upstream, reg, policy = _published(tmp_path / "other")
    (reg.run_root / "q4_policy_registry_manifest.json").write_text("{}\n")
    with pytest.raises((Q4PolicyRegistryError, QuarterlyPeriodPolicyError)):
        QuarterlyPolicyV2Reader().load(policy.run_root, upstream=upstream, release=release, registry_root=reg.run_root)


def test_v2_derives_a_dimensioned_q4_only_from_the_same_exact_scope(tmp_path: Path) -> None:
    release = _release()
    dimensions = [["ProductOrServiceAxis", "ProductMember"]]
    upstream = _publication(release, dimensions=dimensions)
    registry = Q4PolicyRegistryMaterializer().materialize(
        upstream, release=release, effective_from="2026-01-01"
    )

    assert len(registry.declarations) == 1
    assert registry.declarations[0]["company_canonical_dimension_key"] == (
        ("ProductOrServiceAxis", "ProductMember"),
    )
    reg = Q4PolicyRegistryPublisher().publish(
        registry, output_root=tmp_path, run_version="dimensioned", upstream=upstream, release=release
    )
    result = QuarterlyPeriodPolicyV2Materializer().materialize(
        upstream, release=release, registry_root=reg.run_root
    )

    assert len(result.q4_candidates) == 1
    candidate = result.q4_candidates[0]
    assert candidate["reported_or_derived"] == "DERIVED"
    assert candidate["company_canonical_dimension_key"] == dimensions
    assert candidate["formula"] == "FY - YTD_9M"
    assert candidate["input_source_fact_ids"] == ("fy", "ytd")


def test_v2_does_not_cross_derive_between_dimension_members(tmp_path: Path) -> None:
    release = _release()
    upstream = _publication(release, dimensions=[["ProductOrServiceAxis", "ProductMember"]])
    registry = Q4PolicyRegistryMaterializer().materialize(
        upstream, release=release, effective_from="2026-01-01"
    )
    reg = Q4PolicyRegistryPublisher().publish(
        registry, output_root=tmp_path, run_version="member-a", upstream=upstream, release=release
    )
    altered_rows = []
    for row in upstream.records("analytical_fact"):
        updated = dict(row)
        if updated["analytical_fact_id"] == "ytd":
            updated["company_canonical_dimension_key"] = [["ProductOrServiceAxis", "ServiceMember"]]
        altered_rows.append(updated)
    incompatible = type(upstream)(
        upstream.run_root,
        upstream.manifest_path,
        upstream.identity,
        upstream.input_ciks,
        {"analytical_fact": tuple(altered_rows)},
        upstream._reader_attestation,
    )

    result = QuarterlyPeriodPolicyV2Materializer().materialize(
        incompatible, release=release, registry_root=reg.run_root
    )
    assert not result.q4_candidates
