from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from sec_xbrl.history_reuse import (
    HistoryAppendReuseError,
    _dirty_period_classes,
    _merge_graph,
    _root_content_pins,
    _rows_equal_with_schema_union,
    _sha256,
    _verify_reuse_evidence,
    history_policy_changed,
)
from sec_xbrl.longitudinal.exploration_graph import _graph_datasets
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication


def _publication(root: Path, datasets: dict[str, tuple[dict, ...]]) -> VerifiedLayer2Publication:
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "layer2_run_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    frozen = MappingProxyType(
        {
            name: tuple(MappingProxyType(dict(row)) for row in rows)
            for name, rows in datasets.items()
        }
    )
    return VerifiedLayer2Publication(root, manifest, MappingProxyType({}), (), frozen)


def test_migration_evidence_binds_code_and_every_payload(tmp_path: Path) -> None:
    previous = tmp_path / "previous" / "panels"
    previous.mkdir(parents=True)
    previous_manifest = previous / "history_manifest.json"
    previous_manifest.write_text("{}\n", encoding="utf-8")
    publications = {}
    for name in ("t1", "t2", "t3", "t4"):
        publication = _publication(tmp_path / name / "run", {})
        (publication.run_root / "payload.parquet").write_bytes(name.encode())
        publications[name] = publication
    evidence = {
        "version": "history-append-migration-v1",
        "status": "ROOT_APPROVED",
        "previous_history": str(previous),
        "previous_history_manifest_sha256": _sha256(previous_manifest),
        "previous_operational_manifest_sha256": {
            name: _sha256(publication.manifest_path)
            for name, publication in sorted(publications.items())
        },
        "previous_operational_content_sha256": {
            name: _root_content_pins(publication.run_root)
            for name, publication in sorted(publications.items())
        },
        "compatible_producer_code_identity": "code-one",
    }
    path = tmp_path / "migration.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    _verify_reuse_evidence(
        migration_evidence=path,
        previous_history=previous,
        previous_manifest=previous_manifest,
        roots={name: publication.run_root for name, publication in publications.items()},
        manifests={name: publication.manifest_path for name, publication in publications.items()},
        producer_code_identity="code-one",
    )
    with pytest.raises(HistoryAppendReuseError, match="does not bind"):
        _verify_reuse_evidence(
            migration_evidence=path,
            previous_history=previous,
            previous_manifest=previous_manifest,
            roots={name: publication.run_root for name, publication in publications.items()},
            manifests={name: publication.manifest_path for name, publication in publications.items()},
            producer_code_identity="code-two",
        )
    (publications["t2"].run_root / "payload.parquet").write_bytes(b"changed")
    with pytest.raises(HistoryAppendReuseError, match="does not bind"):
        _verify_reuse_evidence(
            migration_evidence=path,
            previous_history=previous,
            previous_manifest=previous_manifest,
            roots={name: publication.run_root for name, publication in publications.items()},
            manifests={name: publication.manifest_path for name, publication in publications.items()},
            producer_code_identity="code-one",
        )


def test_prefix_comparison_is_typed_with_only_parquet_list_normalization() -> None:
    assert _rows_equal_with_schema_union([{"v": [1, 2]}], [{"v": (1, 2), "optional": None}])
    assert not _rows_equal_with_schema_union([{"v": True}], [{"v": 1}])
    assert not _rows_equal_with_schema_union([{"v": 1}], [{"v": 1.0}])
    assert not _rows_equal_with_schema_union([{"v": [1]}], [{"v": {"0": 1}}])


def test_dirty_scope_uses_current_focus_and_ytd_closes_qtd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sec_xbrl.longitudinal import period_observation

    class Materializer:
        def materialize(self, **_kwargs):
            return SimpleNamespace(
                observations=(
                    {"period_class": "YTD_9M", "comparative_type": "CURRENT_FOCUS"},
                    {"period_class": "FY", "comparative_type": "HISTORICAL_COMPARATIVE"},
                )
            )

    snapshot = SimpleNamespace(
        input=SimpleNamespace(snapshot_id="new"),
        records=lambda name: ({"form": "10-Q"},) if name == "filing" else (),
    )
    monkeypatch.setattr(period_observation, "PeriodObservationMaterializer", Materializer)
    assert _dirty_period_classes((snapshot,)) == {"YTD_9M", "QTD_3M"}
    previous = {"as_of_date": "2026-10-10", "companies": [{"cik": "1", "filings": [1]}]}
    current = {"as_of_date": "2026-10-11", "companies": [{"cik": "1", "filings": [1, 2]}]}
    assert history_policy_changed(previous, current)


def test_t3_stage_merge_matches_full_graph(tmp_path: Path) -> None:
    def observation(filing: str, fact: str, value: str) -> dict:
        return {
            "cik": "0000000001",
            "source_filing_id": filing,
            "source_snapshot_id": f"snapshot:{filing}",
            "source_fact_id": fact,
            "raw_concept_id": "concept:revenue",
            "raw_concept_qname": "us-gaap:Revenue",
            "raw_concept_is_standard": True,
            "accession": filing,
            "form": "10-Q",
            "filed_date": "2026-01-01",
            "report_date": "2025-12-31",
            "context_id": f"context:{filing}",
            "unit_id": "USD",
            "value_numeric": value,
            "value_text": None,
            "raw_dimension_signature": (),
            "canonical_dimension_signature": (),
            "dimension_mapping_ids": (),
            "mapping_review_required": False,
            "concept_mapping_id": f"mapping:{filing}",
            "concept_mapping_version": "v1",
            "company_canonical_concept_id": "company:revenue",
            "fiscal_year": 2026,
            "fiscal_quarter": 1,
            "period_class": "QTD_3M",
            "period_key": f"period:{filing}",
        }

    old = observation("filing:old", "fact:old", "10")
    new = observation("filing:new", "fact:new", "11")
    maps = {"axis": {}, "member": {}}
    old_graph = _graph_datasets((old,), (), maps)
    full_graph = _graph_datasets((old, new), (), maps)
    previous = _publication(tmp_path / "old", old_graph)
    current_t1 = _publication(
        tmp_path / "t1",
        {
            "reported_period_observation": (old, new),
            "company_axis_map": (),
            "company_member_map": (),
        },
    )
    current_t2 = _publication(
        tmp_path / "t2", {"filing_relationship_edge": ()}
    )
    assert _merge_graph(previous, current_t1, current_t2, ()) == full_graph


def test_incremental_quarter_manifest_follows_current_targets() -> None:
    from sec_xbrl.analytics.history_quarters import _quarter_target_keys

    targets = {
        ("TEST", "AS_FILED", "QTD_3M"): object(),
        ("TEST", "AS_FILED", "YTD_9M"): object(),
    }

    assert _quarter_target_keys(targets) == [
        ("TEST", "AS_FILED", "QTD_3M"),
        ("TEST", "AS_FILED", "YTD_9M"),
    ]
