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


def test_recast_evidence_cannot_publish_without_explicit_basis_binding(tmp_path: Path) -> None:
    evidence = {
        "recast_evidence_id": "evidence-1",
        "cik": "0000320193",
        "source_filing_id": "filing-2",
        "source_raw_fact_id": "fact-2",
        "target_period_key": "FY26-Q1",
        "basis_version": "basis-v2",
        "evidence_kind": "TABLE",
        "source_document": "filing.htm",
        "source_locator": "Note 1",
        "prior_source_filing_ids": ("filing-1",),
        "evidence_version": "m9-recast-evidence-v1",
        "explicitly_represented": False,
    }
    with pytest.raises(Layer2MaterializationError, match="explicit re-presentation"):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(),
            {"analytical_fact": [_datasets()["analytical_fact"][0]], "recast_evidence": [evidence]},
        )


def test_recast_analytical_fact_requires_matching_same_run_evidence(tmp_path: Path) -> None:
    fact = {
        "analytical_fact_id": "recast-fact", "cik": "0000320193",
        "view": "CURRENT_COMPARABLE", "as_of_date": "2026-05-01",
        "source_type": "RECAST_REPORTED", "selected_fact_id": "new-fact",
        "source_filing_id": "filing-2", "basis_version": "basis-v2", "value_numeric": "120",
        "recast_evidence_id": "evidence-1", "selection_rule_version": "selection-v1",
    }
    evidence = {
        "recast_evidence_id": "evidence-1", "cik": "0000320193",
        "source_filing_id": "filing-2", "source_raw_fact_id": "other-fact",
        "target_period_key": "FY26-Q1", "basis_version": "basis-v2",
        "evidence_kind": "TABLE", "source_document": "filing.htm", "source_locator": "Note 1",
        "prior_source_filing_ids": ("filing-1",), "evidence_version": "m9-recast-evidence-v1",
        "explicitly_represented": True,
    }
    with pytest.raises(Layer2MaterializationError, match="must resolve to compatible recast_evidence"):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(), {"analytical_fact": [fact], "recast_evidence": [evidence]}
        )


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


def test_publisher_accepts_auditable_period_observation_exclusions(tmp_path: Path) -> None:
    published = Layer2Publisher(tmp_path / "layer2").publish(
        _run(),
        {
            "analytical_fact": _datasets()["analytical_fact"],
            "period_observation_exclusion": [
                {
                    "period_observation_exclusion_id": "missing-context",
                    "cik": "0000320193",
                    "source_fact_id": "raw-missing-context",
                    "source_filing_id": "filing-aapl-q2",
                    "exclusion_reason": "MISSING_OR_UNRESOLVED_CONTEXT",
                    "classification_rule_version": "l2-m1-period-observation-v1",
                }
            ],
        },
    )
    assert published.output_counts["period_observation_exclusion"] == 1


@pytest.mark.parametrize(
    "event, message",
    [
        (
            {
                "event_id": "bad-event",
                "cik": "0000320193",
                "filing_id": "filing-aapl-q2",
                "source_raw_id": "raw-revenue",
                "company_canonical_id": "company:0000320193:concept:revenue",
                "mapping_version": "map-v1",
                "event_type": "NOT_A_CONTROLLED_EVENT",
                "valid_from_filing_id": "filing-aapl-q2",
                "continuity_break": False,
                "review_required": False,
                "review_state": "AUTO_ACCEPTED",
                "evidence": {"raw": "raw-revenue"},
            },
            "missing provenance",
        ),
        (
            {
                "event_id": "bad-event",
                "cik": "0000320193",
                "filing_id": "filing-aapl-q2",
                "source_raw_id": "raw-revenue",
                "company_canonical_id": "company:0000320193:concept:revenue",
                "mapping_id": "company-map:fixture",
                "mapping_version": "map-v1",
                "event_type": "NOT_A_CONTROLLED_EVENT",
                "valid_from_filing_id": "filing-aapl-q2",
                "continuity_break": False,
                "review_required": False,
                "review_state": "AUTO_ACCEPTED",
                "evidence": {"raw": "raw-revenue"},
            },
            "unsupported event_type",
        ),
    ],
)
def test_publisher_rejects_unlinked_or_uncontrolled_structural_change(
    tmp_path: Path, event: dict[str, object], message: str
) -> None:
    with pytest.raises(Layer2MaterializationError, match=message):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(), {"analytical_fact": _datasets()["analytical_fact"], "structural_change": [event]}
        )


def test_publisher_rejects_controlled_structural_event_without_matching_map(tmp_path: Path) -> None:
    mapping = {
        "mapping_id": "company-map:real",
        "cik": "0000320193",
        "entity_type": "concept",
        "source_raw_id": "raw-revenue",
        "source_filing_id": "filing-aapl-q2",
        "company_canonical_id": "company:0000320193:concept:revenue",
        "valid_from_filing_id": "filing-aapl-q2",
        "relation": "SAME",
        "method": "RAW_IDENTITY_BASELINE",
        "evidence": {"raw": "raw-revenue"},
        "mapping_version": "map-v1",
        "continuity_break": False,
        "review_required": False,
        "review_state": "AUTO_ACCEPTED",
    }
    event = {
        "event_id": "fabricated-controlled-event",
        "cik": "0000320193",
        "filing_id": "filing-aapl-q2",
        "source_raw_id": "raw-revenue",
        "company_canonical_id": "company:0000320193:concept:wrong",
        "mapping_id": "company-map:real",
        "event_type": "NEW_CONCEPT",
        "valid_from_filing_id": "filing-aapl-q2",
        "mapping_version": "map-v1",
        "continuity_break": False,
        "review_required": False,
        "review_state": "AUTO_ACCEPTED",
        "evidence": {"raw": "raw-revenue"},
    }
    with pytest.raises(Layer2MaterializationError, match="does not match linked mapping"):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(),
            {
                "analytical_fact": _datasets()["analytical_fact"],
                "company_concept_map": [mapping],
                "structural_change": [event],
            },
        )


@pytest.mark.parametrize(
    "field, value",
    [("filing_id", "other-filing"), ("continuity_break", True)],
)
def test_publisher_rejects_structural_event_with_mismatched_shared_mapping_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    mapping = {
        "mapping_id": "company-map:real",
        "cik": "0000320193",
        "entity_type": "concept",
        "source_raw_id": "raw-revenue",
        "source_raw_concept_id": "raw-revenue",
        "source_filing_id": "filing-aapl-q2",
        "company_canonical_id": "company:0000320193:concept:revenue",
        "valid_from_filing_id": "filing-aapl-q2",
        "valid_from_period": "2026-03-28",
        "relation": "SAME",
        "method": "RAW_IDENTITY_BASELINE",
        "evidence": {"raw": "raw-revenue"},
        "mapping_version": "map-v1",
        "continuity_break": False,
        "review_required": False,
        "review_state": "AUTO_ACCEPTED",
    }
    event: dict[str, object] = {
        "event_id": "controlled-event",
        "cik": "0000320193",
        "filing_id": "filing-aapl-q2",
        "source_raw_id": "raw-revenue",
        "source_raw_concept_id": "raw-revenue",
        "company_canonical_id": "company:0000320193:concept:revenue",
        "mapping_id": "company-map:real",
        "entity_type": "concept",
        "event_type": "NEW_CONCEPT",
        "valid_from_filing_id": "filing-aapl-q2",
        "valid_from_period": "2026-03-28",
        "mapping_version": "map-v1",
        "continuity_break": False,
        "review_required": False,
        "review_state": "AUTO_ACCEPTED",
        "evidence": {"raw": "raw-revenue"},
    }
    event[field] = value
    with pytest.raises(Layer2MaterializationError, match="does not match linked mapping"):
        Layer2Publisher(tmp_path / "layer2").publish(
            _run(),
            {
                "analytical_fact": _datasets()["analytical_fact"],
                "company_concept_map": [mapping],
                "structural_change": [event],
            },
        )


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
