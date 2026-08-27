from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl.longitudinal import (
    Layer1SnapshotInput,
    Layer2MaterializationError,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
)


def _run(version: str = "l2-m0-fixture-v1", selection: str = "selection-v1") -> Layer2Run:
    return Layer2Run(
        run_version=version,
        corpus_run_id="20260827T051322Z",
        inputs=(
            Layer1SnapshotInput(
                cik="0000320193",
                accession="0000320193-26-000020",
                form="10-Q",
                filed_date="2026-05-01",
                report_date="2026-03-28",
                snapshot_id="0000320193/000032019326000020",
                manifest_sha256="a" * 64,
                parser_version="m2-layer1-v2",
            ),
        ),
        rules=Layer2RuleVersions(
            period_rule_version="m6-period-v1",
            mapping_version="m7-company-canonical-v1",
            recast_evidence_version="recast-evidence-v1",
            selection_rule_version=selection,
        ),
    )


def _datasets() -> dict[str, list[dict[str, object]]]:
    return {
        "analytical_fact": [
            {
                "analytical_fact_id": "aapl-revenue-q2",
                "cik": "0000320193",
                "view": "AS_FILED",
                "as_of_date": "2026-05-01",
                "source_type": "REPORTED",
                "selected_fact_id": "raw-aapl-revenue-q2",
                "value_numeric": "95359",
                "selection_rule_version": "selection-v1",
            },
            {
                "analytical_fact_id": "aapl-safe-na",
                "cik": "0000320193",
                "view": "CURRENT_COMPARABLE",
                "as_of_date": "2026-05-01",
                "source_type": "UNAVAILABLE",
                "unavailable_reason": "BASIS_MIXING_NOT_ALLOWED",
            },
        ],
        "period_observation": [
            {"id": "period-aapl-revenue-q2", "cik": "0000320193", "source_fact_id": "raw-aapl-revenue-q2"}
        ],
    }


def test_publishes_complete_manifest_and_partitioned_deterministic_rows(tmp_path: Path) -> None:
    publisher = Layer2Publisher(tmp_path / "layer2")
    published = publisher.publish(_run(), _datasets())

    assert published.reused_existing is False
    assert published.output_counts == {"analytical_fact": 2, "period_observation": 1}
    payload = json.loads(published.manifest_path.read_text(encoding="utf-8"))
    assert payload["corpus_run_id"] == "20260827T051322Z"
    assert payload["inputs"][0]["snapshot_id"] == "0000320193/000032019326000020"
    assert payload["rules"] == {
        "mapping_version": "m7-company-canonical-v1",
        "period_rule_version": "m6-period-v1",
        "recast_evidence_version": "recast-evidence-v1",
        "selection_rule_version": "selection-v1",
    }
    output = published.run_root / "0000320193" / "analytical_fact.jsonl"
    assert [json.loads(line)["analytical_fact_id"] for line in output.read_text().splitlines()] == [
        "aapl-revenue-q2",
        "aapl-safe-na",
    ]

    repeated = publisher.publish(_run(), _datasets())
    assert repeated.reused_existing is True
    assert repeated.fingerprint == published.fingerprint


@pytest.mark.parametrize(
    "row, message",
    [
        ({"source_type": "REPORTED", "selected_fact_id": None}, "selected raw Fact ID"),
        ({"source_type": "UNAVAILABLE", "value_numeric": "1", "unavailable_reason": "NO"}, "cannot have numeric"),
        ({"source_type": "UNAVAILABLE", "unavailable_reason": None}, "requires unavailable_reason"),
    ],
)
def test_analytical_fact_cannot_publish_without_lineage_or_reason(
    tmp_path: Path, row: dict[str, object], message: str
) -> None:
    candidate = {
        "analytical_fact_id": "invalid",
        "cik": "0000320193",
        "view": "AS_FILED",
        "as_of_date": "2026-05-01",
        "selection_rule_version": "selection-v1",
        **row,
    }
    with pytest.raises(Layer2MaterializationError, match=message):
        Layer2Publisher(tmp_path / "layer2").publish(_run(), {"analytical_fact": [candidate]})
    assert not (tmp_path / "layer2" / _run().run_version).exists()


def test_failed_validation_leaves_no_partial_published_run(tmp_path: Path) -> None:
    with pytest.raises(Layer2MaterializationError, match="outside declared inputs"):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(),
            {"analytical_fact": [{**_datasets()["analytical_fact"][0], "cik": "0001045810"}]},
        )
    assert not (tmp_path / "layer2" / "l2-m0-fixture-v1").exists()


def test_changed_rule_version_requires_separate_run_identifier(tmp_path: Path) -> None:
    publisher = Layer2Publisher(tmp_path / "layer2")
    publisher.publish(_run(), _datasets())
    with pytest.raises(Layer2MaterializationError, match="different inputs or rule versions"):
        publisher.publish(_run(selection="selection-v2"), _datasets())
    separate = publisher.publish(_run("l2-m0-fixture-v2", "selection-v2"), _datasets())
    assert separate.run_root.name == "l2-m0-fixture-v2"


def test_same_input_and_versions_cannot_silently_replace_different_values(tmp_path: Path) -> None:
    publisher = Layer2Publisher(tmp_path / "layer2")
    publisher.publish(_run(), _datasets())
    changed = _datasets()
    changed["analytical_fact"][0]["value_numeric"] = "95360"
    with pytest.raises(Layer2MaterializationError, match="different output values or keys"):
        publisher.publish(_run(), changed)


@pytest.mark.parametrize("field", ("form", "filed_date", "report_date"))
def test_run_rejects_layer1_input_without_required_filing_provenance(field: str) -> None:
    values: dict[str, object] = {
        "cik": "0000320193",
        "accession": "0000320193-26-000020",
        "form": "10-Q",
        "filed_date": "2026-05-01",
        "report_date": "2026-03-28",
        "snapshot_id": "0000320193/000032019326000020",
        "manifest_sha256": "a" * 64,
    }
    values[field] = ""
    with pytest.raises(Layer2MaterializationError, match="missing required provenance"):
        Layer2Run(
            run_version="invalid-provenance-v1",
            corpus_run_id="20260827T051322Z",
            inputs=(Layer1SnapshotInput(**values),),  # type: ignore[arg-type]
            rules=Layer2RuleVersions("period-v1", "map-v1", "evidence-v1", "selection-v1"),
        )
