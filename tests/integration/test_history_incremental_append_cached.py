"""A bounded cached suffix proves append reuse matches the unchanged full build."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl.history import HistoryPublicationReader, _sha256_file, _write_json, build_history
from sec_xbrl.history_reuse import _producer_code_identity, _root_content_pins
from sec_xbrl.longitudinal.materialization import Layer2PublicationReader


def test_strict_suffix_append_matches_full_history(tmp_path: Path) -> None:
    source = Path(
        "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/"
        "history_runs/20260906_five_company/history_intake.json"
    )
    if not source.exists():
        pytest.skip("explicit cached history fixture is unavailable")
    original = json.loads(source.read_text(encoding="utf-8"))
    items = [
        item
        for item in original["filings"]
        if item["filing"]["cik"] == "0001045810"
        and item["filing"]["report_date"] in {"2024-04-28", "2024-07-28"}
    ]
    items.sort(key=lambda item: (item["filing"]["filed_date"], item["filing"]["accession"]))
    assert len(items) == 2
    company = next(
        company for company in original["plan"]["companies"] if company["ticker"] == "NVDA"
    )

    def intake(selected: list[dict], path: Path) -> Path:
        value = {
            **original,
            "plan": {
                **original["plan"],
                "companies": [{**company, "filings": [item["filing"] for item in selected]}],
            },
            "filings": selected,
        }
        _write_json(path, value)
        return path

    previous = build_history(
        intake_manifest=intake(items[:1], tmp_path / "previous-intake.json"),
        output_root=tmp_path / "previous-run",
    )
    full = build_history(
        intake_manifest=intake(items, tmp_path / "current-intake.json"),
        output_root=tmp_path / "full-run",
    )
    previous_reader = HistoryPublicationReader(previous)
    reported = Path(previous_reader.manifest["supersedes_publication"])
    roots = json.loads((reported / "history_manifest.json").read_text())["operational_roots"]
    evidence = tmp_path / "migration-evidence.json"
    _write_json(
        evidence,
        {
            "version": "history-append-migration-v1",
            "status": "ROOT_APPROVED",
            "previous_history": str(previous.absolute()),
            "previous_history_manifest_sha256": _sha256_file(previous / "history_manifest.json"),
            "previous_operational_manifest_sha256": {
                name: _sha256_file(Path(root) / "layer2_run_manifest.json")
                for name, root in sorted(roots.items())
            },
            "previous_operational_content_sha256": {
                name: _root_content_pins(Path(root)) for name, root in sorted(roots.items())
            },
            "compatible_producer_code_identity": _producer_code_identity(),
        },
    )
    appended = build_history(
        intake_manifest=tmp_path / "current-intake.json",
        output_root=tmp_path / "append-run",
        previous_history=previous,
        previous_reuse_evidence=evidence,
    )
    receipt = json.loads(
        (tmp_path / "append-run" / "history_append_reuse_receipt.json").read_text()
    )
    assert receipt["producer_code_identity"] == _producer_code_identity()
    assert receipt["current_history_manifest_sha256"] == _sha256_file(
        appended / "history_manifest.json"
    )

    full_reader = HistoryPublicationReader(full)
    append_reader = HistoryPublicationReader(appended)
    assert append_reader.manifest["input_fingerprint"] != previous_reader.manifest["input_fingerprint"]
    assert append_reader.manifest["history_append_reuse"]["mode"] == "STRICTLY_LATER_SINGLE_CIK_APPEND_V1"
    assert append_reader.manifest["history_append_reuse"]["quarter_fast_input_proof"]["proven"]
    full_tables = {
        (table["ticker"], table["view"], table["period_class"]): table
        for table in full_reader.manifest["tables"]
    }
    append_tables = {
        (table["ticker"], table["view"], table["period_class"]): table
        for table in append_reader.manifest["tables"]
    }
    assert full_tables.keys() == append_tables.keys()
    for key in full_tables:
        for name in ("columns", "rows", "cells"):
            expected = full_reader._records(full_tables[key]["files"][name])
            actual = append_reader._records(append_tables[key]["files"][name])
            assert _normalize_publication_paths(expected) == _normalize_publication_paths(actual)
    layer2_reader = Layer2PublicationReader()
    for layer in ("t1", "t2", "t3", "t4"):
        full_layer = layer2_reader.load(Path(full_reader.manifest["operational_roots"][layer]))
        append_layer = layer2_reader.load(Path(append_reader.manifest["operational_roots"][layer]))
        assert full_layer.datasets.keys() == append_layer.datasets.keys()
        for dataset in full_layer.datasets:
            assert full_layer.records(dataset) == append_layer.records(dataset)


def _normalize_publication_paths(records: tuple[dict, ...]) -> tuple[dict, ...]:
    """Normalize only the explicit immutable-publication provenance path."""
    return tuple(
        {
            **record,
            "prior_candidate_publication": "$REPORTED_PUBLICATION",
        }
        if "prior_candidate_publication" in record
        else record
        for record in records
    )


def test_schema_union_padding_is_typed_and_policy_ignores_only_filing_suffix() -> None:
    from sec_xbrl.history_reuse import (
        _rows_equal_with_schema_union,
        history_policy_changed,
    )

    assert _rows_equal_with_schema_union([{"a": {"x": 1}}], [{"a": {"x": 1, "y": None}}])
    assert _rows_equal_with_schema_union([{"a": [1, 2]}], [{"a": (1, 2)}])
    assert not _rows_equal_with_schema_union([{"a": True}], [{"a": 1}])
    previous = {"as_of_date": "2026-10-10", "companies": [{"cik": "1", "filings": [1]}]}
    current = {"as_of_date": "2026-10-10", "companies": [{"cik": "1", "filings": [1, 2]}]}
    changed = {**current, "as_of_date": "2026-10-11"}
    assert not history_policy_changed(previous, current)
    assert history_policy_changed(previous, changed)
