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
