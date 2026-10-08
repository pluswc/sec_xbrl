from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl import universe_delivery
from sec_xbrl.analysis import VERSION as ANALYSIS_VERSION
from sec_xbrl.analytics.reviewed_q4 import VERSION as Q4_VERSION
from sec_xbrl.company_metadata import (
    SnapshotInput,
    build_company_metadata,
    publish_company_metadata,
)
from sec_xbrl.history import HISTORY_VERSION, _write_records


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class _FixtureSourceBindingsReader:
    """Small governed-publication stand-in for consumer-policy unit tests."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "source_binding_manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text())
        self.publication_id = self.manifest["publication_id"]

    def verify_all(self) -> None:
        return None

    def duration_bindings(self) -> tuple[dict[str, object], ...]:
        return tuple(self.manifest["duration_bindings"])

    def approved_transform_corrections(self) -> tuple[dict[str, object], ...]:
        return tuple(self.manifest["correction_bindings"])


def _collection(tmp_path: Path) -> tuple[Path, Path]:
    config = _write(
        tmp_path / "config.json",
        {
            "schema_version": 1,
            "universe_id": "one-company-delivery",
            "purpose": "completion fixture",
            "as_of_date": "2026-10-08",
            "source_observed_at": "2026-10-08T01:00:00+00:00",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [
                {"ticker": "TEST", "cik": "0000000123", "groups": ["fixture"]}
            ],
        },
    )
    filing = {
        "cik": "0000000123",
        "accession": "0000000123-26-000001",
        "form": "10-K",
        "filed_date": "2026-03-01",
        "report_date": "2025-12-31",
        "primary_document": "test.htm",
        "is_xbrl": True,
        "is_inline_xbrl": True,
        "source": "fixture",
    }
    plan = _write(
        tmp_path / "plan.json",
        {
            "version": HISTORY_VERSION,
            "as_of_date": "2026-10-08",
            "report_start": "2025-12-31",
            "report_end": "2025-12-31",
            "recent_fiscal_years": None,
            "companies": [
                {
                    "ticker": "TEST",
                    "cik": "0000000123",
                    "name": "Test Corp",
                    "submissions": [],
                    "filings": [filing],
                }
            ],
        },
    )
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "operations",
        existing_plans={"TEST": plan},
    )
    local_plan = json.loads((tmp_path / "operations/companies/TEST/plan.json").read_text())
    intake_root = tmp_path / "operations/companies/TEST/intake"
    _write(
        intake_root
        / "snapshots/0000000123/000000012326000001/layer1_manifest.json",
        {
            "cik": "0000000123",
            "accession": "0000000123-26-000001",
            "layer1_parser_version": universe_delivery.ACCURACY_PARSER_VERSION,
            "package_sha256": "c" * 64,
        },
    )
    snapshot_root = (
        intake_root / "snapshots/0000000123/000000012326000001"
    )
    pl.DataFrame(
        {
            "fact_id": ["fact-fixture"],
            "raw_concept_id": ["concept-duration-fixture"],
            "context_id": ["context-duration-fixture"],
            "value_numeric": [None],
            "value_text": ["P1Y6M"],
            "is_nil": [False],
            "raw_value": ["P1Y6M"],
            "reported_or_derived": ["REPORTED"],
        }
    ).write_parquet(snapshot_root / "fact.parquet")
    pl.DataFrame(
        {
            "raw_concept_id": ["concept-duration-fixture"],
            "qname": ["test:ExpectedLife"],
            "data_type": ["xbrli:durationItemType"],
        }
    ).write_parquet(snapshot_root / "concept.parquet")
    _write(
        intake_root / "history_intake.json",
        {
            "plan": local_plan,
            "complete": True,
            "filings": [
                {
                    "filing": filing,
                    "status": "REUSED",
                    "source_run": str(intake_root.absolute()),
                    "ticker": "TEST",
                }
            ],
        },
    )
    return config, manifest


def _mark_collection_ready(collection_manifest: Path) -> None:
    run_root = collection_manifest.parent
    company_root = run_root / "companies/TEST"
    plan_path = company_root / "plan.json"
    intake_path = company_root / "intake/history_intake.json"
    plan = json.loads(plan_path.read_text())
    output_root = run_root / "history"
    publication = output_root / "panels"
    publication.mkdir(parents=True)
    data_path = publication / "fixture.parquet"
    data_path.write_bytes(b"fixture-history-data")
    data_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    history_manifest = _write(
        publication / "history_manifest.json",
        {
            "plan": plan,
            "source_intake": str(intake_path.absolute()),
            "views": ["AS_FILED", "LATEST_REPORTED"],
            "tables": [
                {
                    "files": {
                        "fixture": {
                            "path": "fixture.parquet",
                            "sha256": data_sha,
                        }
                    }
                }
            ],
        },
    )
    _write(
        company_root / "build_manifest.json",
        {
            "version": operations.COLLECTION_VERSION,
            "status": "READY",
            "ticker": "TEST",
            "output_root": str(output_root.absolute()),
            "publication": str(publication.absolute()),
            "views": ["AS_FILED", "LATEST_REPORTED"],
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "intake_manifest": str(intake_path.absolute()),
            "intake_sha256": hashlib.sha256(intake_path.read_bytes()).hexdigest(),
            "history_manifest": str(history_manifest.absolute()),
            "history_manifest_sha256": hashlib.sha256(
                history_manifest.read_bytes()
            ).hexdigest(),
            "declared_files": {"fixture.parquet": data_sha},
            "completed_at": "2026-10-08T02:00:00+00:00",
        },
    )


def _accuracy_assessment(
    tmp_path: Path,
    collection_manifest: Path,
    *,
    state: str = "PASS",
    actual_value: str = "P4Y6M18D",
) -> Path:
    collection = json.loads(collection_manifest.read_text())
    build = json.loads(
        (collection_manifest.parent / "companies/TEST/build_manifest.json").read_text()
    )
    verification = tmp_path / f"accuracy-{state.lower()}-verification.json"
    _write(verification, {"state": state, "fixture": True})
    verification_sha = hashlib.sha256(verification.read_bytes()).hexdigest()
    source_index = _write(
        tmp_path / f"accuracy-{state.lower()}-source-index.json",
        {
            "primary_document_count": 1,
            "missing_primary_documents": 0,
            "format_counts": {"durday": 0, "durmonth": 0, "duryear": 1, "durweek": 0},
            "primary_documents": [
                {
                    "ticker": "TEST",
                    "cik": "0000000123",
                    "accession": "0000000123-26-000001",
                    "primary_sha256": "e" * 64,
                }
            ],
            "duration_facts": [
                {
                    "ticker": "TEST",
                    "cik": "0000000123",
                    "accession": "0000000123-26-000001",
                    "source_id": "source-duration-fixture",
                    "fact_id": "fact-fixture",
                    "format_qname": "ixt-sec:duryear",
                    "format_namespace": universe_delivery.SEC_TRANSFORM_NAMESPACE,
                    "source_lexical": "1.5",
                    "concept_qname": "test:ExpectedLife",
                    "context_ref": "source-context-duration-fixture",
                }
            ],
        },
    )
    source_index_sha = hashlib.sha256(source_index.read_bytes()).hexdigest()
    fact_evidence = _write(
        tmp_path / f"accuracy-{state.lower()}-fact-checks.json",
        {
            "schema_version": "sec-duration-fact-checks-v1",
            "record_count": 1,
            "records": [
                {
                    "ticker": "TEST",
                    "cik": "0000000123",
                    "accession": "0000000123-26-000001",
                    "source_id": "source-duration-fixture",
                    "fact_id": "fact-fixture",
                    "context_id": "context-duration-fixture",
                    "source_context_ref": "source-context-duration-fixture",
                    "concept_qname": "test:ExpectedLife",
                    "transform": "duryear",
                    "lexical_input": "1.5",
                    "expected_value": "P1Y6M",
                    "actual_value": "P1Y6M",
                    "status": "PASS",
                }
            ],
        },
    )
    fact_evidence_sha = hashlib.sha256(fact_evidence.read_bytes()).hexdigest()
    approved_corrections = _write(
        tmp_path / f"accuracy-{state.lower()}-approved-corrections.json",
        {
            "schema_version": "sec-approved-inline-transform-corrections-v1",
            "record_count": 0,
            "records": [],
        },
    )
    approved_corrections_sha = hashlib.sha256(
        approved_corrections.read_bytes()
    ).hexdigest()
    correction_source_index = _write(
        tmp_path / f"accuracy-{state.lower()}-correction-source-index.json",
        {"fact_count": 0, "facts": [], "unmatched": []},
    )
    correction_source_index_sha = hashlib.sha256(
        correction_source_index.read_bytes()
    ).hexdigest()
    source_binding_root = tmp_path / f"source-bindings-{state.lower()}"
    source_binding_manifest = _write(
        source_binding_root / "source_binding_manifest.json",
        {
            "version": "sec-source-bindings-v1",
            "publication_id": f"source-bindings-{state.lower()}-fixture",
            "producer_revision": "b" * 40,
            "collection": {
                "manifest_sha256": hashlib.sha256(
                    collection_manifest.read_bytes()
                ).hexdigest()
            },
            "counts": {
                "companies": 1,
                "filings": 1,
                "duration_bindings": 1,
                "approved_transform_corrections": 0,
            },
            "duration_source_index": str(source_index),
            "correction_source_index": str(correction_source_index),
            "duration_bindings": [
                {
                    **json.loads(source_index.read_text())["duration_facts"][0],
                    "source_context_ref": "source-context-duration-fixture",
                    "primary_sha256": "e" * 64,
                }
            ],
            "correction_bindings": [],
        },
    )
    source_binding_manifest_sha = hashlib.sha256(
        source_binding_manifest.read_bytes()
    ).hexdigest()
    assessment: dict[str, object] = {
        "schema_version": universe_delivery.ACCURACY_SCHEMA,
        "state": state,
        "reason": None if state == "PASS" else "fresh v5 cohort is not accepted",
        "scope": {
            "universe_id": "one-company-delivery",
            "financial_as_of": "2026-10-08",
            "collection_request_sha256": collection["request_sha256"],
            "collection_manifest_sha256": hashlib.sha256(
                collection_manifest.read_bytes()
            ).hexdigest(),
            "requested_companies": 1,
            "selected_filings": 1,
        },
        "evidence_files": [
            {"path": str(verification.absolute()), "sha256": verification_sha},
            {"path": str(source_index.absolute()), "sha256": source_index_sha},
            {"path": str(fact_evidence.absolute()), "sha256": fact_evidence_sha},
            {
                "path": str(approved_corrections.absolute()),
                "sha256": approved_corrections_sha,
            },
            {
                "path": str(correction_source_index.absolute()),
                "sha256": correction_source_index_sha,
            },
            {
                "path": str(source_binding_manifest.absolute()),
                "sha256": source_binding_manifest_sha,
            },
        ],
    }
    if state == "PASS":
        assessment.update(
            {
                "parser_version": universe_delivery.ACCURACY_PARSER_VERSION,
                "parser_rule_version": universe_delivery.ACCURACY_RULE_VERSION,
                "supported_lexical_repair_policy": (
                    universe_delivery.SUPPORTED_LEXICAL_REPAIR_POLICY
                ),
                "frozen_commit_sha": "a" * 40,
                "source_binding_publication": {
                    "root": str(source_binding_root.absolute()),
                    "publication_id": f"source-bindings-{state.lower()}-fixture",
                    "manifest_sha256": source_binding_manifest_sha,
                    "producer_revision": "b" * 40,
                    "filing_count": 1,
                    "duration_binding_count": 1,
                    "approved_transform_correction_count": 0,
                    "independent_verification": {
                        "state": "PASS",
                        "producer_revision": "b" * 40,
                        "evidence_path": str(verification.absolute()),
                        "evidence_sha256": verification_sha,
                    },
                },
                "source_packages": {"expected": 1, "verified": 1, "missing": 0},
                "filing_checks": [
                    {
                        "ticker": "TEST",
                        "cik": "0000000123",
                        "accession": "0000000123-26-000001",
                        "source_package_sha256": "c" * 64,
                        "source_primary_sha256": "e" * 64,
                        "snapshot_manifest_sha256": hashlib.sha256(
                            (
                                collection_manifest.parent
                                / "companies/TEST/intake/snapshots/0000000123/000000012326000001/layer1_manifest.json"
                            ).read_bytes()
                        ).hexdigest(),
                        "duration_fact_count": 1,
                        "normalized_value_mismatches": 0,
                        "status": "PASS",
                    }
                ],
                "history_manifest_sha256s": {
                    "TEST": build["history_manifest_sha256"]
                },
                "ingestion_gates": {
                    "TAXONOMY_AND_TRANSFORM_RESOLUTION": "PASS",
                    "RAW_CORPUS_COMPLETENESS": "PASS",
                    "ATOMIC_FILING_SNAPSHOT": "PASS",
                },
                "invalid_duration_lexical_fails_closed": True,
                "transform_checks": {
                    "durday": {"examined": 0, "normalized_value_mismatches": 0},
                    "durmonth": {"examined": 0, "normalized_value_mismatches": 0},
                    "duryear": {"examined": 1, "normalized_value_mismatches": 0},
                    "durweek": {"examined": 0, "normalized_value_mismatches": 0},
                },
                "source_index": {
                    "path": str(source_index.absolute()),
                    "sha256": source_index_sha,
                    "filing_count": 1,
                    "duration_fact_count": 1,
                },
                "fact_level_evidence": {
                    "path": str(fact_evidence.absolute()),
                    "sha256": fact_evidence_sha,
                    "record_count": 1,
                },
                "approved_transform_corrections": {
                    "path": str(approved_corrections.absolute()),
                    "sha256": approved_corrections_sha,
                    "record_count": 0,
                    "source_index_path": str(correction_source_index.absolute()),
                    "source_index_sha256": correction_source_index_sha,
                },
                "normalized_value_checks": [
                    {
                        "ticker": "AMD",
                        "accession": "0000002488-23-000047",
                        "fact_id": "fact_a6259d1f828fa6d425c0fd2c",
                        "transform": "duryear",
                        "lexical_input": "4.55",
                        "previous_value": "P4Y7M",
                        "expected_value": "P4Y6M18D",
                        "actual_value": actual_value,
                        "status": "PASS",
                    }
                ],
                "foreign_change_counts": {
                    "non_duration_facts": 0,
                    "duration_source_lexicals": 0,
                    "monetary_values": 0,
                    "contexts": 0,
                    "units": 0,
                    "dimensions": 0,
                    "relationship_keys": 0,
                },
                "independent_verification": {
                    "state": "PASS",
                    "frozen_commit_sha": "a" * 40,
                    "evidence_path": str(verification.absolute()),
                    "evidence_sha256": verification_sha,
                },
            }
        )
    return _write(tmp_path / f"accuracy-{state.lower()}.json", assessment)


def _metadata(tmp_path: Path) -> Path:
    snapshot = _write(
        tmp_path / "metadata-input/0000000123/root.json",
        {
            "cik": "0000000123",
            "name": "Test Corp",
            "sic": "3571",
            "sicDescription": "Electronic Computers",
            "tickers": ["TEST", "TST.A"],
            "exchanges": ["Nasdaq", "NYSE"],
            "formerNames": [],
            "filings": {"recent": {"form": ["10-K", "10-Q"]}},
        },
    )
    observed = datetime(2026, 10, 8, 1, 0, tzinfo=UTC)
    build = build_company_metadata(
        [SnapshotInput(snapshot, observed)], cutoff=observed
    )
    return publish_company_metadata(build, tmp_path / "company-metadata").root


def _reviewed_q4(tmp_path: Path) -> tuple[Path, Path]:
    history = tmp_path / "history/panels"
    history.mkdir(parents=True)
    history_manifest = _write(history / "history_manifest.json", {"version": "fixture"})
    root = tmp_path / "reviewed-q4"
    root.mkdir()
    derived = tuple(
        {
            "ticker": "TEST",
            "cik": "0000000123",
            "selection_view": view,
            "selection_as_of_date": "2026-09-06",
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "member_qname": "test:ProductMember",
            "canonical_dimension_signature": [["axis", "member"]],
            "value_numeric": "300",
            "status": "DERIVED",
            "review_id": f"review-{view}",
            "source_accessions": ["fy-accession", "ytd-accession"],
            "source_snapshot_ids": ["fy-snapshot", "ytd-snapshot"],
            "source_fact_ids": ["fy-fact", "ytd-fact"],
        }
        for view in ("AS_FILED", "LATEST_REPORTED")
    )
    exclusions = (
        {
            "ticker": "TEST",
            "selection_view": "LATEST_REPORTED",
            "fiscal_year": 2025,
            "member_qname": "test:NeedsReviewMember",
            "reason": "MAPPING_REVIEW_REQUIRED_DIFFERENT_EPOCHS",
            "detail": "fixture pending scope",
        },
    )
    records = {"candidate": (), "exclusion": exclusions, "review": (), "derived": derived}
    files = {}
    for name, rows in records.items():
        relative = f"reviewed_q4_{name}.parquet"
        files[name] = {"path": relative, **_write_records(root / relative, rows)}
    _write(
        root / "reviewed_q4_manifest.json",
        {
            "version": Q4_VERSION,
            "rule_version": "fixture-rule",
            "publication_id": "reviewed-q4-fixture",
            "history_publication": str(history.resolve()),
            "history_manifest_sha256": hashlib.sha256(history_manifest.read_bytes()).hexdigest(),
            "source_evidence_path": str((tmp_path / "source.json").resolve()),
            "source_evidence_sha256": "a" * 64,
            "review_ledger_path": str((tmp_path / "ledger.json").resolve()),
            "review_ledger_sha256": "b" * 64,
            "source_snapshots": [],
            "files": files,
            "counts": {name: len(rows) for name, rows in records.items()},
            "selection_as_of_dates": ["2026-09-06"],
            "views": ["AS_FILED", "LATEST_REPORTED"],
            "review_cutoff": "2026-10-08T01:30:00+00:00",
        },
    )
    return root, history


def _analysis_bundle(
    tmp_path: Path,
    *,
    name: str,
    history: Path,
    q4: Path | None,
    annual: bool,
) -> Path:
    root = tmp_path / name
    root.mkdir()
    views = {}
    for view in ("AS_FILED", "LATEST_REPORTED"):
        relative = f"TEST/{view}/columns.parquet"
        info = _write_records(
            root / relative,
            ({"fiscal_year": 2025, "fiscal_quarter": 4, "period_class": "FY" if annual else "QTD_3M"},),
        )
        views[view] = {"files": {"columns": {"path": relative, **info}}}
    history_sha = hashlib.sha256((history / "history_manifest.json").read_bytes()).hexdigest()
    company = {
        "views": views,
        "source_publication": str(history.resolve()),
        "as_of": "2026-09-06",
        "review_cutoff": None,
        "years": [2025],
    }
    manifest: dict[str, object] = {
        "version": ANALYSIS_VERSION,
        "publication_id": f"{name}-publication",
        "companies": {"TEST": company},
        "targets": {"TEST": {"status": "READY", "reason": None}},
        "configuration": {},
        "source_manifest_hashes": {"history_manifest_sha256": history_sha},
    }
    if annual:
        manifest["period_mode"] = "ANNUAL"
    if q4 is not None:
        q4_manifest_path = q4 / "reviewed_q4_manifest.json"
        q4_manifest = json.loads(q4_manifest_path.read_text())
        manifest["reviewed_q4"] = {
            "publication": str(q4.resolve()),
            "publication_id": q4_manifest["publication_id"],
            "manifest_sha256": hashlib.sha256(q4_manifest_path.read_bytes()).hexdigest(),
            "review_cutoff": q4_manifest["review_cutoff"],
        }
        company["reviewed_q4_publication_id"] = q4_manifest["publication_id"]
        company["reviewed_q4_cutoff"] = q4_manifest["review_cutoff"]
    _write(root / "analysis_manifest.json", manifest)
    return root


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    config, collection = _collection(tmp_path)
    _mark_collection_ready(collection)
    accuracy = _accuracy_assessment(tmp_path, collection)
    metadata = _metadata(tmp_path)
    q4, history = _reviewed_q4(tmp_path)
    quarterly = _analysis_bundle(
        tmp_path, name="quarterly", history=history, q4=q4, annual=False
    )
    annual = _analysis_bundle(
        tmp_path, name="annual", history=history, q4=None, annual=True
    )
    monkeypatch.setattr(universe_delivery.ReviewedQ4Reader, "verify_all", lambda self: None)
    monkeypatch.setattr(
        universe_delivery, "SourceBindingsReader", _FixtureSourceBindingsReader
    )
    return {
        "config": config,
        "collection": collection,
        "metadata": metadata,
        "q4": q4,
        "quarterly": quarterly,
        "annual": annual,
        "accuracy": accuracy,
    }


def test_one_company_completion_joins_statuses_and_c_scope_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    published = universe_delivery.publish_universe_delivery(
        config_path=paths["config"],
        collection_manifest=paths["collection"],
        metadata_publication=paths["metadata"],
        reviewed_q4_publication=paths["q4"],
        quarterly_analysis=paths["quarterly"],
        annual_analysis=paths["annual"],
        accuracy_assessment=paths["accuracy"],
        destination=tmp_path / "completion",
        expected_q4_economic_cells=1,
        expected_q4_view_records=2,
    )

    report = json.loads(published.readiness_json.read_text())
    assert report["assessment_state"] == "READY"
    assert report["dates"] == {
        "collection_source_observed_at": "2026-10-08T01:00:00+00:00",
        "financial_as_of": "2026-10-08",
        "metadata_candidate_inventory_observed_at": None,
        "metadata_cutoff": "2026-10-08T01:00:00Z",
        "metadata_observed_at": ["2026-10-08T01:00:00Z"],
        "q4_review_cutoff": "2026-10-08T01:30:00+00:00",
        "q4_selection_as_of_dates": ["2026-09-06"],
    }
    assert len(report["companies"]) == 1
    company = report["companies"][0]
    assert company["metadata_tickers"] == ["TEST", "TST.A"]
    assert company["collection_state"] == "READY"
    assert report["assessments"]["collection"]["state"] == "READY"
    assert company["assessment_state"] == "ANALYSIS_PREPARED"
    assert company["q4_scope"] == "REVIEWED_SCOPE"
    assert report["assessments"]["reviewed_q4"]["economic_cells"] == 1
    assert report["assessments"]["reviewed_q4"]["view_records"] == 2
    assert (
        report["assessments"]["reviewed_q4"]["parent_history_relation"]
        == "SEPARATE_APPROVED_REFERENCE"
    )
    assert report["assessments"]["duration_conformance"]["state"] == "PASS"
    assert len(report["reviewed_q4"]["rows"]) == 2
    assert report["reviewed_q4"]["rows"][0]["source_accessions"]
    rendered = published.report_html.read_text(encoding="utf-8")
    assert "기업·산업·원자료·분석준비·Q4범위" in rendered
    assert "기준일을 분리해서 읽기" in rendered
    assert "MAPPING_REVIEW_REQUIRED_DIFFERENT_EPOCHS" in rendered
    assert "Raw SEC transform 정확성" in rendered
    assert "FY2025 Q4" in rendered
    assert published.readiness_csv.read_text().count("\n") == 2
    assert "does not" in published.readme.read_text(encoding="utf-8")
    reader = universe_delivery.UniverseDeliveryReader(published.root)
    assert reader.publication_id == published.publication_id
    published.report_html.write_text(rendered + "tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity mismatch"):
        universe_delivery.UniverseDeliveryReader(published.root)


def test_completion_can_publish_explicit_partial_state_before_c_is_ready(
    tmp_path: Path,
) -> None:
    config, collection = _collection(tmp_path)
    metadata = _metadata(tmp_path)
    published = universe_delivery.publish_universe_delivery(
        config_path=config,
        collection_manifest=collection,
        metadata_publication=metadata,
        destination=tmp_path / "completion",
    )

    report = json.loads(published.readiness_json.read_text())
    assert report["assessment_state"] == "PARTIAL"
    assert report["assessments"]["collection"]["state"] == "RAW_COMPLETE"
    assert report["assessments"]["metadata"]["state"] == "READY"
    assert report["assessments"]["reviewed_q4"]["state"] == "PENDING"
    assert report["assessments"]["quarterly_analysis"]["state"] == "PENDING"
    assert report["assessments"]["annual_analysis"]["state"] == "PENDING"
    assert report["assessments"]["duration_conformance"]["state"] == "NOT_PROVIDED"
    assert report["companies"][0]["assessment_state"] == "RAW_METADATA_READY"
    assert "준비된 검토 Q4 publication이 없습니다" in published.report_html.read_text()


@pytest.mark.parametrize("defect", ("config_cik", "q4_identity", "analysis_asof"))
def test_completion_rejects_foreign_or_stale_input_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    if defect == "config_cik":
        config = json.loads(paths["config"].read_text())
        config["companies"][0]["cik"] = "0000000999"
        paths["config"] = _write(tmp_path / "foreign-config.json", config)
    elif defect == "q4_identity":
        manifest_path = paths["quarterly"] / "analysis_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["reviewed_q4"]["publication_id"] = "foreign-q4"
        manifest["companies"]["TEST"]["reviewed_q4_publication_id"] = "foreign-q4"
        _write(manifest_path, manifest)
    else:
        manifest_path = paths["annual"] / "analysis_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["companies"]["TEST"]["as_of"] = "2026-09-05"
        _write(manifest_path, manifest)

    with pytest.raises(ValueError):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            reviewed_q4_publication=paths["q4"],
            quarterly_analysis=paths["quarterly"],
            annual_analysis=paths["annual"],
            destination=tmp_path / "completion",
            expected_q4_economic_cells=1,
            expected_q4_view_records=2,
        )
    assert not (tmp_path / "completion").exists()


def test_reviewed_q4_ticker_cannot_borrow_another_configured_cik() -> None:
    with pytest.raises(ValueError, match="ticker/CIK differs"):
        universe_delivery._validate_q4_scope(
            ({"ticker": "TEST", "cik": "0000000999"},),
            {"TEST": "0000000123", "OTHER": "0000000999"},
        )


def test_completion_rejects_symlinked_prepared_dataset_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    dataset = paths["quarterly"] / "TEST/AS_FILED/columns.parquet"
    outside = tmp_path / "outside-columns.parquet"
    outside.write_bytes(dataset.read_bytes())
    dataset.unlink()
    dataset.symlink_to(outside)

    with pytest.raises(ValueError, match="traverses a symlink"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            reviewed_q4_publication=paths["q4"],
            quarterly_analysis=paths["quarterly"],
            annual_analysis=paths["annual"],
            destination=tmp_path / "completion",
            expected_q4_economic_cells=1,
            expected_q4_view_records=2,
        )
    assert outside.is_file()
    assert not (tmp_path / "completion").exists()


def test_completion_rejects_symlinked_destination_without_external_write(
    tmp_path: Path,
) -> None:
    config, collection = _collection(tmp_path)
    metadata = _metadata(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "completion"
    destination.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="traverses a symlink"):
        universe_delivery.publish_universe_delivery(
            config_path=config,
            collection_manifest=collection,
            metadata_publication=metadata,
            destination=destination,
        )
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("accuracy_state", "expected_delivery_state"),
    (("PENDING", "PARTIAL"), ("BLOCKED", "BLOCKED")),
)
def test_duration_conformance_state_prevents_delivery_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accuracy_state: str,
    expected_delivery_state: str,
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    accuracy = _accuracy_assessment(
        tmp_path / accuracy_state.lower(),
        paths["collection"],
        state=accuracy_state,
    )
    publication = universe_delivery.publish_universe_delivery(
        config_path=paths["config"],
        collection_manifest=paths["collection"],
        metadata_publication=paths["metadata"],
        reviewed_q4_publication=paths["q4"],
        quarterly_analysis=paths["quarterly"],
        annual_analysis=paths["annual"],
        accuracy_assessment=accuracy,
        destination=tmp_path / "completion",
        expected_q4_economic_cells=1,
        expected_q4_view_records=2,
    )

    report = json.loads(publication.readiness_json.read_text())
    assert report["assessment_state"] == expected_delivery_state
    assert (
        report["assessments"]["duration_conformance"]["state"]
        == accuracy_state
    )
    assert accuracy_state in publication.report_html.read_text(encoding="utf-8")


def test_duration_conformance_pass_checks_normalized_values_not_only_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    inaccurate = _accuracy_assessment(
        tmp_path / "inaccurate",
        paths["collection"],
        actual_value="P4Y7M",
    )

    with pytest.raises(ValueError, match="normalized-value check failed"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=inaccurate,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


def test_duration_conformance_scope_must_match_immutable_collection_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    payload["scope"]["selected_filings"] = 381
    foreign = _write(tmp_path / "foreign-accuracy.json", payload)

    with pytest.raises(ValueError, match="scope differs"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=foreign,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


def test_duration_conformance_pass_binds_current_governed_histories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    payload["history_manifest_sha256s"]["TEST"] = "b" * 64
    foreign = _write(tmp_path / "foreign-history-accuracy.json", payload)

    with pytest.raises(ValueError, match="governed-history scope differs"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=foreign,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


def test_duration_conformance_pass_binds_actual_v5_snapshot_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    payload["filing_checks"][0]["source_package_sha256"] = "f" * 64
    foreign = _write(tmp_path / "foreign-snapshot-accuracy.json", payload)

    with pytest.raises(ValueError, match="differs from v5 snapshot"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=foreign,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


@pytest.mark.parametrize(
    ("tamper", "error"),
    (
        ("fact_id", "differs from source index"),
        ("matching_wrong_value", "value differs from v5 Fact or Concept"),
    ),
)
def test_duration_conformance_binds_fact_evidence_to_actual_v5_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
    error: str,
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    fact_declaration = payload["fact_level_evidence"]
    fact_path = Path(fact_declaration["path"])
    facts = json.loads(fact_path.read_text())
    if tamper == "fact_id":
        facts["records"][0]["fact_id"] = "fact-rehashed-fake"
    else:
        facts["records"][0]["expected_value"] = "P1Y7M"
        facts["records"][0]["actual_value"] = "P1Y7M"
    _write(fact_path, facts)
    changed_sha = hashlib.sha256(fact_path.read_bytes()).hexdigest()
    fact_declaration["sha256"] = changed_sha
    for evidence in payload["evidence_files"]:
        if evidence["path"] == str(fact_path):
            evidence["sha256"] = changed_sha
    inaccurate = _write(tmp_path / "inaccurate-fact-evidence.json", payload)

    with pytest.raises(ValueError, match=error):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=inaccurate,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


def test_rehashed_duration_json_cannot_replace_governed_source_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    source_declaration = payload["source_index"]
    fact_declaration = payload["fact_level_evidence"]
    source_path = Path(source_declaration["path"])
    fact_path = Path(fact_declaration["path"])
    source = json.loads(source_path.read_text())
    facts = json.loads(fact_path.read_text())
    source["duration_facts"][0]["source_id"] = "invented-source"
    source["duration_facts"][0]["source_lexical"] = "9.55"
    facts["records"][0]["source_id"] = "invented-source"
    facts["records"][0]["lexical_input"] = "9.55"
    _write(source_path, source)
    _write(fact_path, facts)
    for declaration, path in (
        (source_declaration, source_path),
        (fact_declaration, fact_path),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        declaration["sha256"] = digest
        next(
            row for row in payload["evidence_files"] if row["path"] == str(path)
        )["sha256"] = digest
    inaccurate = _write(tmp_path / "rehashed-duration-pair.json", payload)

    with pytest.raises(ValueError, match="governed source bindings"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=inaccurate,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


def test_rehashed_correction_json_cannot_replace_governed_source_or_primary_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    declaration = payload["approved_transform_corrections"]
    source_path = Path(declaration["source_index_path"])
    correction_path = Path(declaration["path"])
    source_record = {
        "ticker": "TEST",
        "cik": "0000000123",
        "accession": "0000000123-26-000001",
        "source_id": "invented-source",
        "fact_id": "fact-invented",
        "context_id": "context-invented",
        "raw_concept_id": "concept-invented",
        "concept_qname": "dei:SecurityExchangeName",
        "concept_data_type_qname": "dei:edgarExchangeCodeItemType",
        "source_element_type": "nonNumeric",
        "source_lexical": "Nasdaq",
        "source_locator": "line:999",
        "format_qname": "ixt-sec:exchnameen",
        "format_namespace": universe_delivery.SEC_TRANSFORM_NAMESPACE,
        "source_scale": None,
        "source_sign": None,
        "primary_document": "test.htm",
        "primary_sha256": "f" * 64,
    }
    _write(
        source_path,
        {"fact_count": 1, "facts": [source_record], "unmatched": []},
    )
    correction_record = {
        "ticker": "TEST",
        "cik": "0000000123",
        "accession": "0000000123-26-000001",
        "source_id": "invented-source",
        "fact_id": "fact-invented",
        "context_id": "context-invented",
        "concept_qname": "dei:SecurityExchangeName",
        "concept_data_type_qname": "dei:edgarExchangeCodeItemType",
        "source_element_type": "nonNumeric",
        "transform_namespace": universe_delivery.SEC_TRANSFORM_NAMESPACE,
        "transform": "exchnameen",
        "lexical_input": "Nasdaq",
        "source_scale": None,
        "source_sign": None,
        "source_primary_sha256": "f" * 64,
        "previous_raw_value": "(ixTransformValueError)",
        "expected_raw_value": "NASDAQ",
        "actual_raw_value": "NASDAQ",
        "actual_is_nil": False,
        "repair_family": "SEC_EXCHNAMEEN_NASDAQ",
        "repair_rule": "sec-inline-2015-exchnameen-nasdaq",
        "value_class": "metadata_text",
        "status": "APPROVED",
        "rule_reference": "SEC staff inline transformation reference",
    }
    _write(
        correction_path,
        {
            "schema_version": "sec-approved-inline-transform-corrections-v1",
            "record_count": 1,
            "records": [correction_record],
        },
    )
    declaration["record_count"] = 1
    for key, path in (
        ("source_index_sha256", source_path),
        ("sha256", correction_path),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        declaration[key] = digest
        next(
            row for row in payload["evidence_files"] if row["path"] == str(path)
        )["sha256"] = digest
    inaccurate = _write(tmp_path / "rehashed-correction-pair.json", payload)

    with pytest.raises(ValueError, match="governed source bindings"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=inaccurate,
            destination=tmp_path / "completion",
        )
    assert not (tmp_path / "completion").exists()


@pytest.mark.parametrize(
    (
        "family",
        "rule",
        "transform",
        "lexical",
        "concept_qname",
        "data_type",
        "element_type",
        "source_sign",
        "source_scale",
        "actual",
        "value_class",
    ),
    (
        (
            "SEC_EXCHNAMEEN_NASDAQ",
            "sec-inline-2015-exchnameen-nasdaq",
            "exchnameen",
            "Nasdaq",
            "dei:SecurityExchangeName",
            "dei:edgarExchangeCodeItemType",
            "nonNumeric",
            None,
            None,
            "NASDAQ",
            "metadata_text",
        ),
        (
            "SEC_STATEPROVNAMEEN_IDAHO",
            "sec-inline-2015-stateprovnameen-idaho",
            "stateprovnameen",
            "Idaho",
            "dei:EntityAddressStateOrProvince",
            "dei:stateOrProvinceItemType",
            "nonNumeric",
            None,
            None,
            "ID",
            "metadata_text",
        ),
        (
            "SEC_DURWORDSEN_UNICODE_HYPHEN",
            "sec-inline-2015-durwordsen-unicode-hyphen",
            "durwordsen",
            "three\u2011year",
            "test:ExpectedLife",
            "xbrli:durationItemType",
            "nonNumeric",
            None,
            None,
            "P3Y",
            "duration",
        ),
        (
            "SEC_NUMWORDSEN_NIL_ZERO",
            "sec-inline-2015-numwordsen-nil-zero",
            "numwordsen",
            "nil",
            "us-gaap:GainLoss",
            "xbrli:monetaryItemType",
            "nonFraction",
            "-",
            "6",
            "-0",
            "monetary",
        ),
        (
            "SEC_NUMWORDSEN_NIL_ZERO",
            "sec-inline-2015-numwordsen-nil-zero",
            "numwordsen",
            "nil",
            "us-gaap:TreasuryStockSharesRetired",
            "xbrli:sharesItemType",
            "nonFraction",
            None,
            None,
            "0",
            "shares",
        ),
    ),
)
def test_approved_transform_corrections_are_source_and_snapshot_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    rule: str,
    transform: str,
    lexical: str,
    concept_qname: str,
    data_type: str,
    element_type: str,
    source_sign: str | None,
    source_scale: str | None,
    actual: str,
    value_class: str,
) -> None:
    paths = _inputs(tmp_path, monkeypatch)
    payload = json.loads(paths["accuracy"].read_text())
    declaration = payload["approved_transform_corrections"]
    correction_path = Path(declaration["path"])
    source_index_path = Path(declaration["source_index_path"])
    snapshot = (
        paths["collection"].parent
        / "companies/TEST/intake/snapshots/0000000123/000000012326000001"
    )
    fact_id = "fact-supported-lexical"
    source_id = "source-supported-lexical"
    context_id = "context-supported-lexical"
    raw_concept_id = "concept-supported-lexical"
    source_record = {
        "ticker": "TEST",
        "cik": "0000000123",
        "accession": "0000000123-26-000001",
        "source_id": source_id,
        "fact_id": fact_id,
        "context_id": context_id,
        "raw_concept_id": raw_concept_id,
        "concept_qname": concept_qname,
        "concept_data_type_qname": data_type,
        "source_element_type": element_type,
        "source_lexical": lexical,
        "format_qname": f"ixt-sec:{transform}",
        "format_namespace": universe_delivery.SEC_TRANSFORM_NAMESPACE,
        "source_scale": source_scale,
        "source_sign": source_sign,
        "source_locator": "line:99",
        "primary_document": "test.htm",
        "primary_sha256": "e" * 64,
    }
    _write(
        source_index_path,
        {"fact_count": 1, "facts": [source_record], "unmatched": []},
    )
    correction_record = {
        "ticker": "TEST",
        "cik": "0000000123",
        "accession": "0000000123-26-000001",
        "source_id": source_id,
        "fact_id": fact_id,
        "context_id": context_id,
        "concept_qname": concept_qname,
        "concept_data_type_qname": data_type,
        "source_element_type": element_type,
        "transform_namespace": universe_delivery.SEC_TRANSFORM_NAMESPACE,
        "transform": transform,
        "lexical_input": lexical,
        "source_scale": source_scale,
        "source_sign": source_sign,
        "source_primary_sha256": "e" * 64,
        "previous_raw_value": "(ixTransformValueError)",
        "expected_raw_value": actual,
        "actual_raw_value": actual,
        "actual_is_nil": False,
        "repair_family": family,
        "repair_rule": rule,
        "value_class": value_class,
        "status": "APPROVED",
        "rule_reference": "SEC staff inline transformation reference",
    }
    _write(
        correction_path,
        {
            "schema_version": "sec-approved-inline-transform-corrections-v1",
            "record_count": 1,
            "records": [correction_record],
        },
    )
    pl.concat(
        [
            pl.read_parquet(snapshot / "fact.parquet"),
            pl.DataFrame(
                {
                    "fact_id": [fact_id],
                    "raw_concept_id": [raw_concept_id],
                    "context_id": [context_id],
                    "value_numeric": [
                        Decimal(0) if value_class in {"monetary", "shares"} else None
                    ],
                    "value_text": [
                        None if value_class in {"monetary", "shares"} else actual
                    ],
                    "is_nil": [False],
                    "raw_value": [actual],
                    "reported_or_derived": ["REPORTED"],
                }
            ),
        ],
        how="diagonal_relaxed",
    ).write_parquet(snapshot / "fact.parquet")
    pl.concat(
        [
            pl.read_parquet(snapshot / "concept.parquet"),
            pl.DataFrame(
                {
                    "raw_concept_id": [raw_concept_id],
                    "qname": [concept_qname],
                    "data_type": [data_type],
                }
            ),
        ],
        how="vertical_relaxed",
    ).write_parquet(snapshot / "concept.parquet")
    changed_sha = hashlib.sha256(correction_path.read_bytes()).hexdigest()
    source_index_sha = hashlib.sha256(source_index_path.read_bytes()).hexdigest()
    declaration.update(
        sha256=changed_sha,
        record_count=1,
        source_index_sha256=source_index_sha,
    )
    binding_declaration = payload["source_binding_publication"]
    binding_manifest_path = (
        Path(binding_declaration["root"]) / "source_binding_manifest.json"
    )
    binding_manifest = json.loads(binding_manifest_path.read_text())
    binding_manifest["counts"]["approved_transform_corrections"] = 1
    binding_manifest["correction_bindings"] = [source_record]
    _write(binding_manifest_path, binding_manifest)
    binding_manifest_sha = hashlib.sha256(binding_manifest_path.read_bytes()).hexdigest()
    binding_declaration["manifest_sha256"] = binding_manifest_sha
    binding_declaration["approved_transform_correction_count"] = 1
    for evidence in payload["evidence_files"]:
        if evidence["path"] == str(correction_path):
            evidence["sha256"] = changed_sha
        elif evidence["path"] == str(source_index_path):
            evidence["sha256"] = source_index_sha
        elif evidence["path"] == str(binding_manifest_path):
            evidence["sha256"] = binding_manifest_sha
    valid = _write(tmp_path / f"valid-{family}-{value_class}.json", payload)

    publication = universe_delivery.publish_universe_delivery(
        config_path=paths["config"],
        collection_manifest=paths["collection"],
        metadata_publication=paths["metadata"],
        accuracy_assessment=valid,
        destination=tmp_path / "completion-valid",
    )
    report = json.loads(publication.readiness_json.read_text())
    assert report["assessments"]["duration_conformance"][
        "approved_correction_summary"
    ]["value_classes"] == {value_class: 1}

    facts = pl.read_parquet(snapshot / "fact.parquet").with_columns(
        pl.when(pl.col("fact_id") == fact_id)
        .then(pl.lit("foreign-value"))
        .otherwise(pl.col("raw_value"))
        .alias("raw_value")
    )
    facts.write_parquet(snapshot / "fact.parquet")
    with pytest.raises(ValueError, match="differs from v5 Fact or Concept"):
        universe_delivery.publish_universe_delivery(
            config_path=paths["config"],
            collection_manifest=paths["collection"],
            metadata_publication=paths["metadata"],
            accuracy_assessment=valid,
            destination=tmp_path / "completion-invalid",
        )
    assert not (tmp_path / "completion-invalid").exists()
