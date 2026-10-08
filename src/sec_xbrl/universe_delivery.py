"""Offline completion publication for the governed company-universe delivery.

The renderer joins already prepared A, B, and C publications.  It performs no
SEC collection, XBRL parsing, filing selection, or financial calculation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from sec_xbrl import analysis
from sec_xbrl.analytics.reviewed_q4 import ReviewedQ4Reader
from sec_xbrl.collection_operations import load_universe_config, read_universe_status
from sec_xbrl.company_metadata import CompanyMetadataReader
from sec_xbrl.source_bindings import SourceBindingsReader

VERSION = "company-universe-delivery-v1"
MANIFEST_NAME = "universe_delivery_manifest.json"
READINESS_JSON = "company_readiness.json"
READINESS_CSV = "company_readiness.csv"
REPORT_HTML = "index.html"
REPRO_README = "README.md"
ACCURACY_SCHEMA = "sec-duration-conformance-assessment-v1"
ACCURACY_PARSER_VERSION = "m2-layer1-v5"
ACCURACY_RULE_VERSION = "sec-duration-conformance-v1"
SUPPORTED_LEXICAL_REPAIR_POLICY = "sec-supported-lexical-repairs-v1"
SEC_TRANSFORM_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class UniverseDeliveryPublication:
    """Paths and identity for one immutable completion publication."""

    root: Path
    publication_id: str
    manifest_path: Path
    readiness_json: Path
    readiness_csv: Path
    report_html: Path
    readme: Path


class UniverseDeliveryReader:
    """Defensively read and verify one immutable completion publication."""

    def __init__(self, root: Path, *, allow_staging: bool = False) -> None:
        self.root = Path(root)
        if (
            not self.root.is_dir()
            or self.root.is_symlink()
            or (self.root.name.startswith(".") and ".partial-" in self.root.name and not allow_staging)
        ):
            raise ValueError("completion publication is not a real published directory")
        expected = {
            MANIFEST_NAME,
            READINESS_JSON,
            READINESS_CSV,
            REPORT_HTML,
            REPRO_README,
        }
        children = tuple(self.root.iterdir())
        if {path.name for path in children} != expected or any(
            path.is_symlink() or not path.is_file() for path in children
        ):
            raise ValueError("completion publication file set is invalid")
        self.manifest = _read_json(self.root / MANIFEST_NAME)
        if self.manifest.get("version") != VERSION:
            raise ValueError("unsupported completion publication")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or set(files) != {
            READINESS_JSON,
            READINESS_CSV,
            REPORT_HTML,
            REPRO_README,
        }:
            raise ValueError("completion file manifest is invalid")
        for name, info in files.items():
            path = self.root / name
            if (
                not isinstance(info, dict)
                or info.get("sha256") != _sha256(path)
                or info.get("size") != path.stat().st_size
            ):
                raise ValueError(f"completion output integrity mismatch: {name}")
        identity = {
            key: value for key, value in self.manifest.items() if key != "publication_id"
        }
        expected_id = "universe-delivery-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        if self.manifest.get("publication_id") != expected_id:
            raise ValueError("completion publication identity mismatch")
        self.readiness = _read_json(self.root / READINESS_JSON)
        if (
            self.readiness.get("version") != VERSION
            or self.readiness.get("universe_id") != self.manifest.get("universe_id")
            or self.readiness.get("assessment_state") != self.manifest.get("assessment_state")
        ):
            raise ValueError("completion readiness scope differs from manifest")
        companies = self.readiness.get("companies")
        if not isinstance(companies, list) or not companies or len(companies) != len(
            {row.get("cik") for row in companies if isinstance(row, dict)}
        ):
            raise ValueError("completion readiness contains duplicate company rows")
        self.publication_id = expected_id


@dataclass(frozen=True, slots=True)
class _AnalysisAttestation:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    publication_id: str
    period_mode: str
    companies: tuple[str, ...]
    selection_as_of_dates: tuple[str, ...]
    source_publications: tuple[str, ...]
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _AccuracyAttestation:
    path: Path
    sha256: str
    state: str
    reason: str | None
    parser_version: str | None
    parser_rule_version: str | None
    frozen_commit_sha: str | None
    evidence_files: tuple[dict[str, Any], ...]
    approved_correction_summary: dict[str, dict[str, int]]
    payload: dict[str, Any]


def publish_universe_delivery(
    *,
    config_path: Path,
    collection_manifest: Path,
    metadata_publication: Path,
    destination: Path,
    reviewed_q4_publication: Path | None = None,
    quarterly_analysis: Path | None = None,
    annual_analysis: Path | None = None,
    accuracy_assessment: Path | None = None,
    source_binding_publication: Path | None = None,
    expected_q4_economic_cells: int = 16,
    expected_q4_view_records: int = 32,
) -> UniverseDeliveryPublication:
    """Validate prepared inputs and atomically publish readiness JSON/CSV/HTML."""
    if type(expected_q4_economic_cells) is not int or expected_q4_economic_cells < 0:
        raise ValueError("expected_q4_economic_cells must be a nonnegative integer")
    if type(expected_q4_view_records) is not int or expected_q4_view_records < 0:
        raise ValueError("expected_q4_view_records must be a nonnegative integer")
    if quarterly_analysis is not None and reviewed_q4_publication is None:
        raise ValueError("quarterly analysis requires its reviewed-Q4 publication")

    config_path = _regular_file(config_path, "universe configuration")
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    _read_json(config_path)
    config = load_universe_config(config_path)
    if any(company.cik is None for company in config.companies):
        raise ValueError("completion configuration requires an explicit CIK for every company")
    configured_tickers = tuple(company.ticker for company in config.companies)
    configured_ciks = tuple(str(company.cik) for company in config.companies)
    if len(configured_ciks) != len(set(configured_ciks)):
        raise ValueError("completion configuration contains duplicate company CIKs")

    collection_status = read_universe_status(manifest_path=collection_manifest)
    _validate_collection_scope(config, collection_status)
    collection_payload = _read_json(collection_manifest)
    request_path = _regular_file(
        Path(collection_payload["request_path"]), "collection request"
    )
    if collection_payload.get("request_sha256") != _sha256(request_path):
        raise ValueError("collection request digest changed")
    collection_company_sources = _collection_company_sources(
        collection_manifest, collection_payload
    )
    planned_filings = (
        _planned_filing_scope(collection_company_sources)
        if accuracy_assessment is not None
        else ()
    )
    snapshot_scope = (
        _collection_snapshot_scope(collection_company_sources)
        if accuracy_assessment is not None
        else {}
    )
    if source_binding_publication is None and accuracy_assessment is not None:
        declared_binding = _read_json(Path(accuracy_assessment)).get(
            "source_binding_publication"
        )
        if isinstance(declared_binding, dict) and type(declared_binding.get("root")) is str:
            source_binding_publication = Path(declared_binding["root"])
    source_bindings = (
        SourceBindingsReader(Path(source_binding_publication))
        if source_binding_publication is not None
        else None
    )
    if source_bindings is not None:
        source_bindings.verify_all()
    accuracy = (
        _attest_accuracy(
            Path(accuracy_assessment),
            universe_id=config.universe_id,
            financial_as_of=config.as_of_date.isoformat(),
            collection_request_sha256=collection_payload["request_sha256"],
            collection_manifest_sha256=_sha256(collection_manifest),
            requested_companies=collection_status.requested_companies,
            selected_filings=collection_status.selected_filings,
            planned_filings=planned_filings,
            snapshot_scope=snapshot_scope,
            history_manifest_sha256s={
                row["ticker"]: row["build"]["history_manifest_sha256"]
                for row in collection_company_sources
                if isinstance(row.get("build"), dict)
                and type(row["build"].get("history_manifest_sha256")) is str
            },
            source_bindings=source_bindings,
        )
        if accuracy_assessment is not None
        else None
    )

    metadata = CompanyMetadataReader(metadata_publication)
    metadata_rows = metadata.list_companies()
    metadata_by_cik = {row.cik: row for row in metadata_rows}
    if len(metadata_by_cik) != len(metadata_rows):
        raise ValueError("metadata publication contains duplicate company rows")
    for company in config.companies:
        row = metadata_by_cik.get(str(company.cik))
        if row is None:
            raise ValueError(f"configured CIK is absent from metadata publication: {company.cik}")
        if company.ticker not in {ticker.upper() for ticker in row.tickers}:
            raise ValueError(f"metadata ticker/CIK differs from configuration: {company.ticker}")

    q4_reader: ReviewedQ4Reader | None = None
    q4_manifest: dict[str, Any] | None = None
    q4_derived: tuple[dict[str, Any], ...] = ()
    q4_exclusions: tuple[dict[str, Any], ...] = ()
    if reviewed_q4_publication is not None:
        q4_reader = ReviewedQ4Reader(reviewed_q4_publication)
        q4_reader.verify_all()
        q4_manifest = q4_reader.manifest
        q4_derived = q4_reader.records("derived")
        q4_exclusions = q4_reader.records("exclusion")
        _validate_q4_scope(
            q4_derived,
            {company.ticker: str(company.cik) for company in config.companies},
        )
        if any(
            row.get("ticker") is not None and row.get("ticker") not in configured_tickers
            for row in q4_exclusions
        ):
            raise ValueError("reviewed-Q4 exclusions contain a foreign ticker")

    quarterly = (
        _attest_analysis(Path(quarterly_analysis), expected_mode="QUARTERLY")
        if quarterly_analysis is not None
        else None
    )
    annual = (
        _attest_analysis(Path(annual_analysis), expected_mode="ANNUAL")
        if annual_analysis is not None
        else None
    )
    _validate_c_analysis_links(
        q4_root=Path(reviewed_q4_publication) if reviewed_q4_publication else None,
        q4_manifest=q4_manifest,
        q4_derived=q4_derived,
        quarterly=quarterly,
        annual=annual,
        configured_tickers=set(configured_tickers),
    )

    report = _readiness_model(
        config_path=config_path,
        config=config,
        collection_manifest=collection_manifest,
        collection_request=request_path,
        collection_company_sources=collection_company_sources,
        collection_status=collection_status,
        metadata=metadata,
        metadata_rows=metadata_rows,
        metadata_by_cik=metadata_by_cik,
        q4_root=Path(reviewed_q4_publication) if reviewed_q4_publication else None,
        q4_manifest=q4_manifest,
        q4_derived=q4_derived,
        q4_exclusions=q4_exclusions,
        quarterly=quarterly,
        annual=annual,
        accuracy=accuracy,
        source_bindings=source_bindings,
        expected_q4_economic_cells=expected_q4_economic_cells,
        expected_q4_view_records=expected_q4_view_records,
    )
    return _publish(report, Path(destination))


def _attest_accuracy(
    path: Path,
    *,
    universe_id: str,
    financial_as_of: str,
    collection_request_sha256: str,
    collection_manifest_sha256: str,
    requested_companies: int,
    selected_filings: int,
    planned_filings: tuple[tuple[str, str, str], ...],
    snapshot_scope: dict[tuple[str, str, str], dict[str, str]],
    history_manifest_sha256s: dict[str, str],
    source_bindings: SourceBindingsReader | None,
) -> _AccuracyAttestation:
    path = _regular_file(path, "duration-conformance assessment")
    payload = _read_json(path)
    if payload.get("schema_version") != ACCURACY_SCHEMA:
        raise ValueError("unsupported duration-conformance assessment")
    state = payload.get("state")
    if state not in {"PASS", "PENDING", "BLOCKED"}:
        raise ValueError("duration-conformance state must be PASS, PENDING, or BLOCKED")
    scope = payload.get("scope")
    expected_scope = {
        "universe_id": universe_id,
        "financial_as_of": financial_as_of,
        "collection_request_sha256": collection_request_sha256,
        "collection_manifest_sha256": collection_manifest_sha256,
        "requested_companies": requested_companies,
        "selected_filings": selected_filings,
    }
    if scope != expected_scope:
        raise ValueError("duration-conformance scope differs from collection request")
    reason = payload.get("reason")
    if reason is not None and (type(reason) is not str or not reason.strip()):
        raise ValueError("duration-conformance reason must be non-empty text")
    if state != "PASS" and reason is None:
        raise ValueError("non-PASS duration-conformance assessment requires a reason")

    parser_version = payload.get("parser_version")
    rule_version = payload.get("parser_rule_version")
    commit_sha = payload.get("frozen_commit_sha")
    evidence_files = _attest_accuracy_evidence(payload.get("evidence_files", []))
    approved_correction_summary: dict[str, dict[str, int]] = {
        "repair_families": {},
        "value_classes": {},
    }
    if state == "PASS":
        if parser_version != ACCURACY_PARSER_VERSION:
            raise ValueError("duration-conformance parser version is not v5")
        if rule_version != ACCURACY_RULE_VERSION:
            raise ValueError("duration-conformance rule version differs")
        if payload.get("supported_lexical_repair_policy") != SUPPORTED_LEXICAL_REPAIR_POLICY:
            raise ValueError("supported lexical repair policy differs")
        if type(commit_sha) is not str or _COMMIT_SHA.fullmatch(commit_sha) is None:
            raise ValueError("duration-conformance frozen commit SHA is invalid")
        approved_correction_summary = _validate_accuracy_pass(
            payload,
            requested_companies=requested_companies,
            selected_filings=selected_filings,
            planned_filings=planned_filings,
            snapshot_scope=snapshot_scope,
            commit_sha=commit_sha,
            evidence_files=evidence_files,
            history_manifest_sha256s=history_manifest_sha256s,
            source_bindings=source_bindings,
        )
    return _AccuracyAttestation(
        path=path,
        sha256=_sha256(path),
        state=state,
        reason=reason,
        parser_version=parser_version if isinstance(parser_version, str) else None,
        parser_rule_version=rule_version if isinstance(rule_version, str) else None,
        frozen_commit_sha=commit_sha if isinstance(commit_sha, str) else None,
        evidence_files=evidence_files,
        approved_correction_summary=approved_correction_summary,
        payload=payload,
    )


def _planned_filing_scope(
    company_sources: list[dict[str, Any]],
) -> tuple[tuple[str, str, str], ...]:
    scope: list[tuple[str, str, str]] = []
    for source in company_sources:
        plan_source = source.get("plan")
        if not isinstance(plan_source, dict) or type(plan_source.get("path")) is not str:
            continue
        plan = _read_json(_regular_file(Path(plan_source["path"]), "collection plan"))
        companies = plan.get("companies")
        if not isinstance(companies, list) or len(companies) != 1:
            raise ValueError("collection plan company scope is malformed")
        company = companies[0]
        filings = company.get("filings") if isinstance(company, dict) else None
        if not isinstance(filings, list):
            raise TypeError("collection plan filing scope is malformed")
        for filing in filings:
            if not isinstance(filing, dict):
                raise TypeError("collection plan filing identity is malformed")
            scope.append(
                (
                    str(source["ticker"]),
                    str(source["cik"]),
                    str(filing.get("accession")),
                )
            )
    if len(scope) != len(set(scope)):
        raise ValueError("collection plans contain duplicate filing scope")
    return tuple(sorted(scope))


def _collection_snapshot_scope(
    company_sources: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    snapshots: dict[tuple[str, str, str], dict[str, str]] = {}
    for source in company_sources:
        intake_source = source.get("intake")
        if not isinstance(intake_source, dict) or type(intake_source.get("path")) is not str:
            continue
        intake = _read_json(_regular_file(Path(intake_source["path"]), "collection intake"))
        filings = intake.get("filings")
        if not isinstance(filings, list):
            raise TypeError("collection intake filing scope is malformed")
        for outcome in filings:
            filing = outcome.get("filing") if isinstance(outcome, dict) else None
            if not isinstance(filing, dict) or type(outcome.get("source_run")) is not str:
                raise TypeError("collection intake outcome is malformed")
            ticker = str(outcome.get("ticker"))
            cik = str(filing.get("cik"))
            accession = str(filing.get("accession"))
            source_run = Path(outcome["source_run"])
            if not source_run.is_absolute():
                raise ValueError("collection intake source run must be absolute")
            manifest_path = _regular_file(
                source_run
                / "snapshots"
                / cik
                / accession.replace("-", "")
                / "layer1_manifest.json",
                "Layer 1 snapshot manifest",
            )
            manifest = _read_json(manifest_path)
            if manifest.get("cik") != cik or manifest.get("accession") != accession:
                raise ValueError("Layer 1 snapshot identity differs from intake")
            key = (ticker, cik, accession)
            if key in snapshots:
                raise ValueError("collection intake repeats a snapshot identity")
            snapshots[key] = {
                "snapshot_manifest_sha256": _sha256(manifest_path),
                "source_package_sha256": str(manifest.get("package_sha256")),
                "parser_version": str(manifest.get("layer1_parser_version")),
                "snapshot_root": str(manifest_path.parent),
            }
    return snapshots


def _attest_accuracy_evidence(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError("duration-conformance evidence_files must be a list")
    result: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict) or type(entry.get("path")) is not str:
            raise ValueError("duration-conformance evidence declaration is malformed")
        evidence_path = Path(entry["path"])
        if not evidence_path.is_absolute():
            raise ValueError("duration-conformance evidence path must be absolute")
        evidence_path = _regular_file(evidence_path, "duration-conformance evidence")
        digest = _sha256(evidence_path)
        if entry.get("sha256") != digest:
            raise ValueError("duration-conformance evidence digest changed")
        result.append({"path": str(evidence_path), "sha256": digest})
    if len(result) != len({row["path"] for row in result}):
        raise ValueError("duration-conformance evidence paths must be unique")
    return tuple(result)


def _validate_accuracy_pass(
    payload: dict[str, Any],
    *,
    requested_companies: int,
    selected_filings: int,
    planned_filings: tuple[tuple[str, str, str], ...],
    snapshot_scope: dict[tuple[str, str, str], dict[str, str]],
    commit_sha: str,
    evidence_files: tuple[dict[str, Any], ...],
    history_manifest_sha256s: dict[str, str],
    source_bindings: SourceBindingsReader | None,
) -> dict[str, dict[str, int]]:
    if source_bindings is None:
        raise ValueError(
            "PASS duration conformance requires a governed source-binding publication"
        )
    packages = payload.get("source_packages")
    if packages != {
        "expected": selected_filings,
        "verified": selected_filings,
        "missing": 0,
    }:
        raise ValueError("duration-conformance source-package coverage is incomplete")
    filing_checks = payload.get("filing_checks")
    if not isinstance(filing_checks, list) or len(filing_checks) != selected_filings:
        raise ValueError("duration-conformance requires one check per selected filing")
    checked_scope: list[tuple[str, str, str]] = []
    filing_check_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for check in filing_checks:
        if (
            not isinstance(check, dict)
            or check.get("status") != "PASS"
            or type(check.get("duration_fact_count")) is not int
            or check["duration_fact_count"] < 0
            or check.get("normalized_value_mismatches") != 0
            or type(check.get("source_package_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", check["source_package_sha256"]) is None
            or type(check.get("source_primary_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", check["source_primary_sha256"]) is None
            or type(check.get("snapshot_manifest_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", check["snapshot_manifest_sha256"]) is None
        ):
            raise ValueError("duration-conformance filing check is invalid")
        key = (str(check.get("ticker")), str(check.get("cik")), str(check.get("accession")))
        checked_scope.append(key)
        filing_check_index[key] = check
    if len(checked_scope) != len(set(checked_scope)) or tuple(sorted(checked_scope)) != planned_filings:
        raise ValueError("duration-conformance filing checks differ from immutable plans")
    if set(snapshot_scope) != set(planned_filings):
        raise ValueError("duration-conformance snapshot scope differs from immutable plans")
    for key, snapshot in snapshot_scope.items():
        check = filing_check_index[key]
        if (
            snapshot.get("parser_version") != ACCURACY_PARSER_VERSION
            or check["source_package_sha256"] != snapshot.get("source_package_sha256")
            or check["snapshot_manifest_sha256"]
            != snapshot.get("snapshot_manifest_sha256")
        ):
            raise ValueError("duration-conformance filing check differs from v5 snapshot")
    if (
        len(history_manifest_sha256s) != requested_companies
        or payload.get("history_manifest_sha256s") != history_manifest_sha256s
    ):
        raise ValueError("duration-conformance governed-history scope differs")
    if payload.get("ingestion_gates") != {
        "TAXONOMY_AND_TRANSFORM_RESOLUTION": "PASS",
        "RAW_CORPUS_COMPLETENESS": "PASS",
        "ATOMIC_FILING_SNAPSHOT": "PASS",
    } or payload.get("invalid_duration_lexical_fails_closed") is not True:
        raise ValueError("duration-conformance ingestion gates are incomplete")
    checks = payload.get("transform_checks")
    if not isinstance(checks, dict) or set(checks) != {
        "durday",
        "durmonth",
        "duryear",
        "durweek",
    }:
        raise ValueError("duration-conformance transform checks are incomplete")
    for transform, check in checks.items():
        if (
            not isinstance(check, dict)
            or type(check.get("examined")) is not int
            or check["examined"] < 0
            or check.get("normalized_value_mismatches") != 0
        ):
            raise ValueError(f"duration-conformance {transform} result is invalid")
    duration_fact_count = sum(check["duration_fact_count"] for check in filing_checks)
    examined_facts = sum(check["examined"] for check in checks.values())
    if duration_fact_count != examined_facts:
        raise ValueError("duration-conformance filing and transform counts differ")
    evidence_index = {row["path"]: row["sha256"] for row in evidence_files}
    _validate_source_binding_reference(
        payload,
        source_bindings=source_bindings,
        evidence_index=evidence_index,
        selected_filings=selected_filings,
        collection_manifest_sha256=str(
            payload.get("scope", {}).get("collection_manifest_sha256")
        ),
    )
    source_index = payload.get("source_index")
    fact_level = payload.get("fact_level_evidence")
    for label, declaration, expected_count_key, expected_count in (
        ("source index", source_index, "filing_count", selected_filings),
        ("fact-level evidence", fact_level, "record_count", examined_facts),
    ):
        if (
            not isinstance(declaration, dict)
            or type(declaration.get("path")) is not str
            or type(declaration.get("sha256")) is not str
            or declaration.get(expected_count_key) != expected_count
            or evidence_index.get(str(Path(declaration["path"]).resolve()))
            != declaration["sha256"]
        ):
            raise ValueError(f"duration-conformance {label} is not declared")
    if source_index.get("duration_fact_count") != examined_facts:
        raise ValueError("duration-conformance source index fact count differs")
    source_counts, source_primary_hashes, duration_sources = _validate_accuracy_source_index(
        Path(source_index["path"]), planned_filings=planned_filings
    )
    _validate_trusted_duration_bindings(
        duration_sources=duration_sources,
        source_primary_hashes=source_primary_hashes,
        source_bindings=source_bindings,
    )
    if source_counts != {
        transform: check["examined"] for transform, check in checks.items()
    }:
        raise ValueError("duration-conformance transform counts differ from source index")
    if any(
        filing_check_index[key]["source_primary_sha256"] != source_primary_hashes[key]
        for key in planned_filings
    ):
        raise ValueError("duration-conformance primary document hash differs")
    fact_counts, fact_scope_counts = _validate_fact_level_evidence(
        Path(fact_level["path"]),
        expected_records=examined_facts,
        duration_sources=duration_sources,
        snapshot_scope=snapshot_scope,
    )
    if fact_counts != source_counts:
        raise ValueError("duration-conformance fact evidence differs from source index")
    if any(
        fact_scope_counts.get(key, 0) != filing_check_index[key]["duration_fact_count"]
        for key in planned_filings
    ):
        raise ValueError("duration-conformance fact evidence differs from filing checks")
    approved_corrections = payload.get("approved_transform_corrections")
    if (
        not isinstance(approved_corrections, dict)
        or type(approved_corrections.get("path")) is not str
        or type(approved_corrections.get("sha256")) is not str
        or type(approved_corrections.get("source_index_path")) is not str
        or type(approved_corrections.get("source_index_sha256")) is not str
        or type(approved_corrections.get("record_count")) is not int
        or approved_corrections["record_count"] < 0
        or evidence_index.get(str(Path(approved_corrections["path"]).resolve()))
        != approved_corrections["sha256"]
        or evidence_index.get(
            str(Path(approved_corrections["source_index_path"]).resolve())
        )
        != approved_corrections["source_index_sha256"]
    ):
        raise ValueError("approved transform corrections are not declared")
    approved_correction_summary = _validate_approved_transform_corrections(
        Path(approved_corrections["path"]),
        expected_records=approved_corrections["record_count"],
        planned_filings=set(planned_filings),
        snapshot_scope=snapshot_scope,
        source_index_path=Path(approved_corrections["source_index_path"]),
        source_index_sha256=approved_corrections["source_index_sha256"],
        evidence_index=evidence_index,
        trusted_bindings=source_bindings.approved_transform_corrections(),
    )
    normalized = payload.get("normalized_value_checks")
    if not isinstance(normalized, list) or not normalized:
        raise ValueError("duration-conformance requires normalized-value checks")
    for check in normalized:
        if (
            not isinstance(check, dict)
            or check.get("status") != "PASS"
            or type(check.get("expected_value")) is not str
            or check.get("actual_value") != check.get("expected_value")
        ):
            raise ValueError("duration-conformance normalized-value check failed")
    known = {
        (
            check.get("ticker"),
            check.get("accession"),
            check.get("fact_id"),
            check.get("transform"),
            check.get("lexical_input"),
            check.get("previous_value"),
            check.get("expected_value"),
            check.get("actual_value"),
        )
        for check in normalized
    }
    if (
        "AMD",
        "0000002488-23-000047",
        "fact_a6259d1f828fa6d425c0fd2c",
        "duryear",
        "4.55",
        "P4Y7M",
        "P4Y6M18D",
        "P4Y6M18D",
    ) not in known:
        raise ValueError("duration-conformance known AMD regression is not attested")
    foreign = payload.get("foreign_change_counts")
    expected_foreign = {
        "non_duration_facts",
        "duration_source_lexicals",
        "monetary_values",
        "contexts",
        "units",
        "dimensions",
        "relationship_keys",
    }
    if (
        not isinstance(foreign, dict)
        or set(foreign) != expected_foreign
        or any(type(value) is not int or value != 0 for value in foreign.values())
    ):
        raise ValueError("duration-conformance replay has foreign changes")
    independent = payload.get("independent_verification")
    if (
        not isinstance(independent, dict)
        or independent.get("state") != "PASS"
        or independent.get("frozen_commit_sha") != commit_sha
        or type(independent.get("evidence_path")) is not str
        or type(independent.get("evidence_sha256")) is not str
    ):
        raise ValueError("duration-conformance independent verification is missing")
    independent_path = str(Path(independent["evidence_path"]).resolve())
    if evidence_index.get(independent_path) != independent["evidence_sha256"]:
        raise ValueError("duration-conformance independent evidence is not declared")
    return approved_correction_summary


def _validate_accuracy_source_index(
    path: Path,
    *,
    planned_filings: tuple[tuple[str, str, str], ...],
) -> tuple[
    dict[str, int],
    dict[tuple[str, str, str], str],
    dict[tuple[str, str, str, str], dict[str, Any]],
]:
    source = _read_json(_regular_file(path, "duration source index"))
    documents = source.get("primary_documents")
    format_counts = source.get("format_counts")
    duration_facts = source.get("duration_facts")
    if (
        source.get("primary_document_count") != len(planned_filings)
        or source.get("missing_primary_documents") != 0
        or not isinstance(documents, list)
        or len(documents) != len(planned_filings)
        or not isinstance(format_counts, dict)
        or set(format_counts) != {"durday", "durmonth", "duryear", "durweek"}
        or any(type(value) is not int or value < 0 for value in format_counts.values())
        or not isinstance(duration_facts, list)
        or len(duration_facts) != sum(format_counts.values())
    ):
        raise ValueError("duration source index scope is invalid")
    hashes: dict[tuple[str, str, str], str] = {}
    for document in documents:
        if (
            not isinstance(document, dict)
            or type(document.get("primary_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", document["primary_sha256"]) is None
        ):
            raise ValueError("duration source index document is invalid")
        key = (
            str(document.get("ticker")),
            str(document.get("cik")),
            str(document.get("accession")),
        )
        if key in hashes:
            raise ValueError("duration source index repeats a filing")
        hashes[key] = document["primary_sha256"]
    if tuple(sorted(hashes)) != planned_filings:
        raise ValueError("duration source index differs from immutable plans")
    indexed_facts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    calculated_counts = {name: 0 for name in ("durday", "durmonth", "duryear", "durweek")}
    for fact in duration_facts:
        if not isinstance(fact, dict):
            raise TypeError("duration source index Fact is invalid")
        filing_key = (
            str(fact.get("ticker")),
            str(fact.get("cik")),
            str(fact.get("accession")),
        )
        source_id = fact.get("source_id")
        format_qname = fact.get("format_qname")
        transform = format_qname.removeprefix("ixt-sec:") if isinstance(format_qname, str) else ""
        key = (*filing_key, str(source_id))
        if (
            filing_key not in hashes
            or type(source_id) is not str
            or not source_id
            or key in indexed_facts
            or type(fact.get("fact_id")) is not str
            or not fact["fact_id"]
            or transform not in calculated_counts
            or fact.get("format_namespace") != SEC_TRANSFORM_NAMESPACE
            or type(fact.get("source_lexical")) is not str
            or type(fact.get("concept_qname")) is not str
            or type(fact.get("context_ref")) is not str
            or not fact["context_ref"]
        ):
            raise ValueError("duration source index Fact is invalid")
        indexed_facts[key] = fact
        calculated_counts[transform] += 1
    if calculated_counts != format_counts:
        raise ValueError("duration source index Fact counts differ")
    return calculated_counts, hashes, indexed_facts


def _validate_source_binding_reference(
    payload: dict[str, Any],
    *,
    source_bindings: SourceBindingsReader,
    evidence_index: dict[str, str],
    selected_filings: int,
    collection_manifest_sha256: str,
) -> None:
    declaration = payload.get("source_binding_publication")
    manifest = source_bindings.manifest
    if not isinstance(declaration, dict):
        raise TypeError("governed source-binding publication is not declared")
    counts = manifest.get("counts")
    collection = manifest.get("collection")
    expected = {
        "root": str(source_bindings.root),
        "publication_id": source_bindings.publication_id,
        "manifest_sha256": _sha256(source_bindings.manifest_path),
        "producer_revision": manifest.get("producer_revision"),
        "filing_count": selected_filings,
        "duration_binding_count": (
            counts.get("duration_bindings") if isinstance(counts, dict) else None
        ),
        "approved_transform_correction_count": (
            counts.get("approved_transform_corrections")
            if isinstance(counts, dict)
            else None
        ),
    }
    if any(declaration.get(key) != value for key, value in expected.items()):
        raise ValueError("governed source-binding publication identity differs")
    manifest_path = str(source_bindings.manifest_path.resolve())
    if evidence_index.get(manifest_path) != expected["manifest_sha256"]:
        raise ValueError("source-binding manifest is not declared as evidence")
    if (
        not isinstance(collection, dict)
        or collection.get("manifest_sha256") != collection_manifest_sha256
        or not isinstance(counts, dict)
        or counts.get("filings") != selected_filings
    ):
        raise ValueError("governed source-binding collection scope differs")
    verification = declaration.get("independent_verification")
    if (
        not isinstance(verification, dict)
        or verification.get("state") != "PASS"
        or verification.get("producer_revision") != manifest.get("producer_revision")
        or type(verification.get("evidence_path")) is not str
        or type(verification.get("evidence_sha256")) is not str
    ):
        raise ValueError("source-binding independent verification is missing")
    evidence_path = str(Path(verification["evidence_path"]).resolve())
    if evidence_index.get(evidence_path) != verification["evidence_sha256"]:
        raise ValueError("source-binding independent evidence is not declared")


def _validate_trusted_duration_bindings(
    *,
    duration_sources: dict[tuple[str, str, str, str], dict[str, Any]],
    source_primary_hashes: dict[tuple[str, str, str], str],
    source_bindings: SourceBindingsReader,
) -> None:
    trusted: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for binding in source_bindings.duration_bindings():
        key = (
            str(binding.get("ticker")),
            str(binding.get("cik")),
            str(binding.get("accession")),
            str(binding.get("source_id")),
        )
        if key in trusted:
            raise ValueError("governed duration source identity is duplicated")
        trusted[key] = binding
    if set(trusted) != set(duration_sources):
        raise ValueError("duration source index differs from governed source bindings")
    for key, source in duration_sources.items():
        binding = trusted[key]
        filing_key = key[:3]
        if (
            source.get("fact_id") != binding.get("fact_id")
            or source.get("primary_document") != binding.get("primary_document")
            or source_primary_hashes.get(filing_key) != binding.get("primary_sha256")
            or source.get("format_qname") != binding.get("format_qname")
            or source.get("format_namespace") != binding.get("format_namespace")
            or source.get("source_lexical") != binding.get("source_lexical")
            or source.get("concept_qname") != binding.get("concept_qname")
            or source.get("context_ref") != binding.get("source_context_ref")
        ):
            raise ValueError("duration source fields differ from governed source bindings")


def _validate_fact_level_evidence(
    path: Path,
    *,
    expected_records: int,
    duration_sources: dict[tuple[str, str, str, str], dict[str, Any]],
    snapshot_scope: dict[tuple[str, str, str], dict[str, str]],
) -> tuple[dict[str, int], dict[tuple[str, str, str], int]]:
    evidence = _read_json(_regular_file(path, "duration fact-level evidence"))
    records = evidence.get("records")
    if (
        evidence.get("schema_version") != "sec-duration-fact-checks-v1"
        or evidence.get("record_count") != expected_records
        or not isinstance(records, list)
        or len(records) != expected_records
    ):
        raise ValueError("duration fact-level evidence scope is invalid")
    transform_counts = {name: 0 for name in ("durday", "durmonth", "duryear", "durweek")}
    filing_counts: dict[tuple[str, str, str], int] = {}
    source_identities: set[tuple[str, str, str, str]] = set()
    fact_identities: set[tuple[str, str, str, str]] = set()
    records_by_filing: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("transform") not in transform_counts
            or record.get("status") != "PASS"
            or type(record.get("source_id")) is not str
            or type(record.get("fact_id")) is not str
            or type(record.get("context_id")) is not str
            or type(record.get("source_context_ref")) is not str
            or type(record.get("concept_qname")) is not str
            or type(record.get("lexical_input")) is not str
            or type(record.get("expected_value")) is not str
            or record.get("actual_value") != record.get("expected_value")
        ):
            raise ValueError("duration fact-level normalized value is invalid")
        filing_key = (
            str(record.get("ticker")),
            str(record.get("cik")),
            str(record.get("accession")),
        )
        source_identity = (*filing_key, record["source_id"])
        fact_identity = (*filing_key, record["fact_id"])
        source = duration_sources.get(source_identity)
        if (
            source is None
            or source_identity in source_identities
            or fact_identity in fact_identities
            or source.get("fact_id") != record["fact_id"]
            or source.get("format_qname") != f"ixt-sec:{record['transform']}"
            or source.get("source_lexical") != record["lexical_input"]
            or source.get("concept_qname") != record["concept_qname"]
            or source.get("context_ref") != record["source_context_ref"]
        ):
            raise ValueError("duration fact-level evidence differs from source index")
        source_identities.add(source_identity)
        fact_identities.add(fact_identity)
        transform_counts[record["transform"]] += 1
        filing_counts[filing_key] = filing_counts.get(filing_key, 0) + 1
        records_by_filing.setdefault(filing_key, []).append(record)
    if source_identities != set(duration_sources):
        raise ValueError("duration fact-level evidence does not cover the source index")

    for filing_key, filing_records in records_by_filing.items():
        snapshot = snapshot_scope.get(filing_key)
        if snapshot is None or type(snapshot.get("snapshot_root")) is not str:
            raise ValueError("duration Fact has no v5 snapshot")
        snapshot_root = Path(snapshot["snapshot_root"])
        facts = pl.read_parquet(_regular_file(snapshot_root / "fact.parquet", "v5 Fact table"))
        concepts = pl.read_parquet(
            _regular_file(snapshot_root / "concept.parquet", "v5 Concept table")
        )
        fact_ids = [record["fact_id"] for record in filing_records]
        selected = facts.filter(pl.col("fact_id").is_in(fact_ids)).to_dicts()
        selected_by_id = {row.get("fact_id"): row for row in selected}
        if len(selected) != len(filing_records) or len(selected_by_id) != len(selected):
            raise ValueError("duration Fact evidence identity is absent or repeated in v5")
        concept_ids = {row.get("raw_concept_id") for row in selected}
        concept_rows = concepts.filter(pl.col("raw_concept_id").is_in(concept_ids)).to_dicts()
        concepts_by_id = {row.get("raw_concept_id"): row for row in concept_rows}
        if len(concepts_by_id) != len(concept_ids):
            raise ValueError("duration Fact Concept identity is absent from v5")
        for record in filing_records:
            fact = selected_by_id[record["fact_id"]]
            concept = concepts_by_id.get(fact.get("raw_concept_id"))
            if (
                fact.get("context_id") != record["context_id"]
                or fact.get("raw_value") != record["actual_value"]
                or fact.get("value_text") != record["actual_value"]
                or fact.get("value_numeric") is not None
                or fact.get("is_nil") is not False
                or fact.get("reported_or_derived") != "REPORTED"
                or concept is None
                or concept.get("qname") != record["concept_qname"]
            ):
                raise ValueError("duration fact-level value differs from v5 Fact or Concept")
    return transform_counts, filing_counts


def _validate_approved_transform_corrections(
    path: Path,
    *,
    expected_records: int,
    planned_filings: set[tuple[str, str, str]],
    snapshot_scope: dict[tuple[str, str, str], dict[str, str]],
    source_index_path: Path,
    source_index_sha256: str,
    evidence_index: dict[str, str],
    trusted_bindings: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, int]]:
    evidence = _read_json(_regular_file(path, "approved inline transform corrections"))
    records = evidence.get("records")
    if (
        evidence.get("schema_version")
        != "sec-approved-inline-transform-corrections-v1"
        or evidence.get("record_count") != expected_records
        or not isinstance(records, list)
        or len(records) != expected_records
    ):
        raise ValueError("approved transform correction scope is invalid")
    source_index_path = _regular_file(
        source_index_path, "supported lexical correction source index"
    )
    if (
        _sha256(source_index_path) != source_index_sha256
        or evidence_index.get(str(source_index_path.resolve())) != source_index_sha256
    ):
        raise ValueError("supported lexical correction source index is not bound")
    source_index = _read_json(source_index_path)
    source_records = source_index.get("facts")
    if (
        source_index.get("fact_count") != expected_records
        or source_index.get("unmatched") != []
        or not isinstance(source_records, list)
        or len(source_records) != expected_records
    ):
        raise ValueError("supported lexical correction source index is incomplete")

    indexed_sources: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for source in source_records:
        if not isinstance(source, dict):
            raise TypeError("supported lexical correction source record is invalid")
        key = (
            str(source.get("ticker")),
            str(source.get("cik")),
            str(source.get("accession")),
            str(source.get("source_id")),
            str(source.get("fact_id")),
        )
        if (
            key[:3] not in planned_filings
            or key in indexed_sources
            or type(source.get("context_id")) is not str
            or type(source.get("raw_concept_id")) is not str
            or type(source.get("concept_qname")) is not str
            or type(source.get("concept_data_type_qname")) is not str
            or source.get("source_element_type") not in {"nonNumeric", "nonFraction"}
            or type(source.get("source_lexical")) is not str
            or type(source.get("format_qname")) is not str
            or source.get("format_namespace") != SEC_TRANSFORM_NAMESPACE
            or source.get("source_scale") is not None
            and type(source.get("source_scale")) is not str
            or source.get("source_sign") is not None
            and type(source.get("source_sign")) is not str
            or type(source.get("primary_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", source["primary_sha256"]) is None
        ):
            raise ValueError("supported lexical correction source record is invalid")
        indexed_sources[key] = source

    trusted_sources: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for binding in trusted_bindings:
        key = (
            str(binding.get("ticker")),
            str(binding.get("cik")),
            str(binding.get("accession")),
            str(binding.get("source_id")),
            str(binding.get("fact_id")),
        )
        if key in trusted_sources:
            raise ValueError("governed correction source identity is duplicated")
        trusted_sources[key] = binding
    if set(trusted_sources) != set(indexed_sources):
        raise ValueError("correction source index differs from governed source bindings")
    for key, source in indexed_sources.items():
        binding = trusted_sources[key]
        if (
            source.get("context_id") != binding.get("context_id")
            or source.get("raw_concept_id") != binding.get("raw_concept_id")
            or source.get("concept_qname") != binding.get("concept_qname")
            or source.get("concept_data_type_qname")
            != binding.get("concept_data_type_qname")
            or source.get("source_element_type")
            != binding.get("source_element_type")
            or source.get("source_lexical") != binding.get("source_lexical")
            or source.get("source_locator") != binding.get("source_locator")
            or source.get("format_qname") != binding.get("format_qname")
            or source.get("format_namespace") != binding.get("format_namespace")
            or source.get("source_scale") != binding.get("source_scale")
            or source.get("source_sign") != binding.get("source_sign")
            or source.get("primary_document") != binding.get("primary_document")
            or source.get("primary_sha256") != binding.get("primary_sha256")
        ):
            raise ValueError(
                "correction source fields differ from governed source bindings"
            )

    identities: set[tuple[str, str, str, str, str]] = set()
    families: dict[str, int] = {}
    value_classes: dict[str, int] = {}
    records_by_filing: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        filing_key = (
            str(record.get("ticker")),
            str(record.get("cik")),
            str(record.get("accession")),
        ) if isinstance(record, dict) else ("", "", "")
        identity = (
            *filing_key,
            str(record.get("source_id")),
            str(record.get("fact_id")),
        ) if isinstance(record, dict) else (*filing_key, "", "")
        source = indexed_sources.get(identity)
        if (
            not isinstance(record, dict)
            or filing_key not in planned_filings
            or type(record.get("source_id")) is not str
            or type(record.get("fact_id")) is not str
            or source is None
            or record.get("context_id") != source.get("context_id")
            or record.get("concept_qname") != source.get("concept_qname")
            or record.get("concept_data_type_qname")
            != source.get("concept_data_type_qname")
            or record.get("source_element_type") != source.get("source_element_type")
            or record.get("transform_namespace") != source.get("format_namespace")
            or f"ixt-sec:{record.get('transform')}" != source.get("format_qname")
            or record.get("lexical_input") != source.get("source_lexical")
            or record.get("source_scale") != source.get("source_scale")
            or record.get("source_sign") != source.get("source_sign")
            or record.get("source_primary_sha256") != source.get("primary_sha256")
            or record.get("previous_raw_value") != "(ixTransformValueError)"
            or record.get("expected_raw_value") != record.get("actual_raw_value")
            or record.get("actual_is_nil") is not False
            or record.get("status") != "APPROVED"
            or type(record.get("rule_reference")) is not str
            or not record["rule_reference"]
        ):
            raise ValueError("approved transform correction record is invalid")
        policy = _supported_lexical_repair_policy(record)
        if policy is None:
            raise ValueError("approved transform correction policy is invalid")
        family, value_class = policy
        source_identity = (*filing_key, record["source_id"], record["fact_id"])
        if source_identity in identities:
            raise ValueError("approved transform correction repeats a source identity")
        identities.add(source_identity)
        families[family] = families.get(family, 0) + 1
        value_classes[value_class] = value_classes.get(value_class, 0) + 1
        records_by_filing.setdefault(filing_key, []).append(record)
    if len(identities) != len(indexed_sources):
        raise ValueError("approved corrections do not cover the source index")
    for filing_key, filing_records in records_by_filing.items():
        snapshot = snapshot_scope.get(filing_key)
        if snapshot is None or type(snapshot.get("snapshot_root")) is not str:
            raise ValueError("approved correction has no v5 snapshot")
        snapshot_root = Path(snapshot["snapshot_root"])
        facts = pl.read_parquet(_regular_file(snapshot_root / "fact.parquet", "v5 Fact table"))
        concepts = pl.read_parquet(
            _regular_file(snapshot_root / "concept.parquet", "v5 Concept table")
        )
        for record in filing_records:
            fact_rows = facts.filter(pl.col("fact_id") == record["fact_id"]).to_dicts()
            if len(fact_rows) != 1:
                raise ValueError("approved correction Fact is absent from v5 snapshot")
            fact = fact_rows[0]
            concept_rows = concepts.filter(
                pl.col("raw_concept_id") == fact.get("raw_concept_id")
            ).to_dicts()
            if (
                len(concept_rows) != 1
                or fact.get("context_id") != record["context_id"]
                or fact.get("is_nil") is not False
                or fact.get("raw_value") != record["actual_raw_value"]
                or fact.get("reported_or_derived") != "REPORTED"
                or concept_rows[0].get("qname") != record["concept_qname"]
                or concept_rows[0].get("data_type")
                != record["concept_data_type_qname"]
            ):
                raise ValueError("approved correction differs from v5 Fact or Concept")
            if record["value_class"] in {"monetary", "shares"}:
                if (
                    not _is_approved_reported_zero(
                        fact.get("value_numeric"), record["actual_raw_value"]
                    )
                    or fact.get("value_text") is not None
                ):
                    raise ValueError("approved numeric correction is not a reported zero")
            elif fact.get("value_text") != record["actual_raw_value"] or fact.get(
                "value_numeric"
            ) is not None:
                raise ValueError("approved text correction value differs from v5 Fact")
    return {
        "repair_families": dict(sorted(families.items())),
        "value_classes": dict(sorted(value_classes.items())),
    }


def _is_approved_reported_zero(value: Any, raw_value: Any) -> bool:
    """Match the Raw numeric scalar to the approved as-reported zero spelling."""
    if raw_value not in {"0", "-0"}:
        return False
    if type(value) is str:
        return value == raw_value
    if isinstance(value, Decimal):
        return value.is_zero() and value.is_signed() == (raw_value == "-0")
    return False


def _supported_lexical_repair_policy(record: dict[str, Any]) -> tuple[str, str] | None:
    transform = record.get("transform")
    lexical = record.get("lexical_input")
    concept = record.get("concept_qname")
    data_type = record.get("concept_data_type_qname")
    element_type = record.get("source_element_type")
    sign = record.get("source_sign")
    scale = record.get("source_scale")
    actual = record.get("actual_raw_value")
    family = record.get("repair_family")
    rule = record.get("repair_rule")
    value_class = record.get("value_class")
    if (
        family == "SEC_EXCHNAMEEN_NASDAQ"
        and rule == "sec-inline-2015-exchnameen-nasdaq"
        and transform == "exchnameen"
        and lexical == "Nasdaq"
        and concept == "dei:SecurityExchangeName"
        and data_type == "dei:edgarExchangeCodeItemType"
        and element_type == "nonNumeric"
        and sign is None
        and scale is None
        and actual == "NASDAQ"
        and value_class == "metadata_text"
    ):
        return family, value_class
    if (
        family == "SEC_STATEPROVNAMEEN_IDAHO"
        and rule == "sec-inline-2015-stateprovnameen-idaho"
        and transform == "stateprovnameen"
        and lexical == "Idaho"
        and concept == "dei:EntityAddressStateOrProvince"
        and data_type == "dei:stateOrProvinceItemType"
        and element_type == "nonNumeric"
        and sign is None
        and scale is None
        and actual == "ID"
        and value_class == "metadata_text"
    ):
        return family, value_class
    if (
        family == "SEC_DURWORDSEN_UNICODE_HYPHEN"
        and rule == "sec-inline-2015-durwordsen-unicode-hyphen"
        and transform == "durwordsen"
        and lexical in {"three\u2011year", "five\u2011year"}
        and type(concept) is str
        and concept
        and data_type == "xbrli:durationItemType"
        and element_type == "nonNumeric"
        and sign is None
        and scale is None
        and actual == {"three\u2011year": "P3Y", "five\u2011year": "P5Y"}[lexical]
        and value_class == "duration"
    ):
        return family, value_class
    expected_zero = "-0" if sign == "-" else "0"
    if (
        family == "SEC_NUMWORDSEN_NIL_ZERO"
        and rule == "sec-inline-2015-numwordsen-nil-zero"
        and transform == "numwordsen"
        and lexical == "nil"
        and type(concept) is str
        and concept
        and data_type in {"xbrli:monetaryItemType", "xbrli:sharesItemType"}
        and element_type == "nonFraction"
        and sign in {None, "-"}
        and (scale is None or type(scale) is str)
        and actual == expected_zero
        and value_class
        == {
            "xbrli:monetaryItemType": "monetary",
            "xbrli:sharesItemType": "shares",
        }[data_type]
    ):
        return family, value_class
    return None


def _validate_collection_scope(config: Any, status: Any) -> None:
    if status.universe_id != config.universe_id:
        raise ValueError("collection universe differs from completion configuration")
    if status.as_of_date != config.as_of_date.isoformat():
        raise ValueError("collection as-of differs from completion configuration")
    if status.source_observed_at != config.source_observed_at:
        raise ValueError("collection observation time differs from completion configuration")
    expected = [(company.ticker, str(company.cik)) for company in config.companies]
    actual = [(row.ticker, row.cik) for row in status.companies]
    if actual != expected:
        raise ValueError("collection ticker/CIK membership differs from configuration")
    if status.requested_companies != len(expected):
        raise ValueError("collection requested-company count differs from configuration")


def _collection_company_sources(
    collection_manifest: Path, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    companies = payload.get("companies")
    if not isinstance(companies, list):
        raise TypeError("collection manifest companies are malformed")
    sources: list[dict[str, Any]] = []
    for company in companies:
        if not isinstance(company, dict) or type(company.get("ticker")) is not str:
            raise ValueError("collection company identity is malformed")
        ticker = company["ticker"]
        root = collection_manifest.parent / "companies" / ticker
        entry: dict[str, Any] = {
            "ticker": ticker,
            "cik": company.get("cik"),
            "plan_status": company.get("plan_status"),
            "plan": None,
        }
        plan_path = root / "plan.json"
        if company.get("plan_status") == "PREPARED":
            plan = _contained_file(
                collection_manifest.parent,
                Path("companies") / ticker / "plan.json",
                f"{ticker} collection plan",
            )
            if company.get("plan_sha256") != _sha256(plan):
                raise ValueError(f"collection plan digest changed: {ticker}")
            entry["plan"] = _source(plan)
        elif plan_path.exists() or plan_path.is_symlink():
            entry["plan"] = _source(
                _contained_file(
                    collection_manifest.parent,
                    Path("companies") / ticker / "plan.json",
                    f"{ticker} failed collection plan",
                )
            )
        intake = root / "intake/history_intake.json"
        if intake.exists() or intake.is_symlink():
            entry["intake"] = _source(
                _contained_file(
                    collection_manifest.parent,
                    Path("companies") / ticker / "intake/history_intake.json",
                    f"{ticker} intake manifest",
                )
            )
        marker = root / "build_manifest.json"
        if marker.exists() or marker.is_symlink():
            marker = _contained_file(
                collection_manifest.parent,
                Path("companies") / ticker / "build_manifest.json",
                f"{ticker} build manifest",
            )
            marker_payload = _read_json(marker)
            entry["build"] = {
                **_source(marker),
                "status": marker_payload.get("status"),
                "publication": marker_payload.get("publication"),
                "history_manifest": marker_payload.get("history_manifest"),
                "history_manifest_sha256": marker_payload.get("history_manifest_sha256"),
            }
        sources.append(entry)
    if len(sources) != len({row["ticker"] for row in sources}):
        raise ValueError("collection source identities contain duplicate tickers")
    return sources


def _validate_q4_scope(
    derived: tuple[dict[str, Any], ...],
    configured_ticker_ciks: dict[str, str],
) -> None:
    if any(row.get("ticker") not in configured_ticker_ciks for row in derived):
        raise ValueError("reviewed-Q4 publication contains a foreign ticker")
    if any(
        row.get("cik") != configured_ticker_ciks.get(str(row.get("ticker")))
        for row in derived
    ):
        raise ValueError("reviewed-Q4 ticker/CIK differs from configuration")
    ticker_ciks: dict[str, str] = {}
    for row in derived:
        previous = ticker_ciks.setdefault(str(row["ticker"]), str(row["cik"]))
        if previous != row["cik"]:
            raise ValueError("reviewed-Q4 ticker resolves to more than one CIK")


def _attest_analysis(root: Path, *, expected_mode: str) -> _AnalysisAttestation:
    root = _real_directory(root, f"{expected_mode.lower()} analysis")
    manifest_path = _regular_file(root / "analysis_manifest.json", "analysis manifest")
    manifest = _read_json(manifest_path)
    if manifest.get("version") != analysis.VERSION:
        raise ValueError("unsupported prepared analysis publication")
    period_mode = manifest.get("period_mode", "QUARTERLY")
    if period_mode != expected_mode:
        raise ValueError(f"prepared analysis period mode is not {expected_mode}")
    publication_id = manifest.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id:
        raise ValueError("prepared analysis publication ID is missing")
    companies = manifest.get("companies")
    if not isinstance(companies, dict) or not companies:
        raise ValueError("prepared analysis contains no companies")
    if len(companies) != len(set(companies)) or any(
        type(ticker) is not str or ticker != ticker.upper() for ticker in companies
    ):
        raise ValueError("prepared analysis company identity is invalid")
    client = analysis.open_analysis(root)
    declared_paths: set[str] = set()
    as_of_dates: set[str] = set()
    source_publications: set[str] = set()
    for ticker, info in companies.items():
        if not isinstance(info, dict) or client.target_status(ticker).get("status") != "READY":
            raise ValueError(f"prepared analysis company is not READY: {ticker}")
        as_of = info.get("as_of")
        if type(as_of) is not str or not as_of:
            raise ValueError(f"prepared analysis selection as-of is missing: {ticker}")
        as_of_dates.add(as_of)
        source = _real_directory(Path(info.get("source_publication", "")), "analysis source")
        source_manifest = _regular_file(source / "history_manifest.json", "history manifest")
        expected_source_sha = manifest.get("source_manifest_hashes", {}).get(
            "history_manifest_sha256"
        )
        if expected_source_sha != _sha256(source_manifest):
            raise ValueError("prepared analysis source history identity changed")
        source_publications.add(str(source))
        views = info.get("views")
        if not isinstance(views, dict) or set(views) != {"AS_FILED", "LATEST_REPORTED"}:
            raise ValueError(f"prepared analysis views are incomplete: {ticker}")
        for view in views.values():
            files = view.get("files") if isinstance(view, dict) else None
            if not isinstance(files, dict) or not files:
                raise ValueError(f"prepared analysis declares no datasets: {ticker}")
            for file_info in files.values():
                relative = _verify_parquet(root, file_info)
                if relative in declared_paths:
                    raise ValueError("prepared analysis repeats a dataset path")
                declared_paths.add(relative)
    return _AnalysisAttestation(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_path),
        publication_id=publication_id,
        period_mode=period_mode,
        companies=tuple(sorted(companies)),
        selection_as_of_dates=tuple(sorted(as_of_dates)),
        source_publications=tuple(sorted(source_publications)),
        manifest=manifest,
    )


def _verify_parquet(root: Path, info: Any) -> str:
    if not isinstance(info, dict) or type(info.get("path")) is not str:
        raise ValueError("prepared analysis dataset declaration is malformed")
    relative = Path(info["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("prepared analysis dataset path is unsafe")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("prepared analysis dataset traverses a symlink")
    path = _regular_file(root / relative, "prepared analysis dataset")
    if not path.resolve().is_relative_to(root):
        raise ValueError("prepared analysis dataset escapes its publication")
    if info.get("sha256") != _sha256(path):
        raise ValueError("prepared analysis dataset digest changed")
    count = info.get("count")
    if type(count) is not int or count < 0:
        raise ValueError("prepared analysis dataset count is invalid")
    try:
        actual = pl.scan_parquet(path).select(pl.len()).collect().item()
    except Exception as exc:
        raise ValueError("prepared analysis dataset is not readable Parquet") from exc
    if actual != count:
        raise ValueError("prepared analysis dataset count changed")
    return str(relative)


def _validate_c_analysis_links(
    *,
    q4_root: Path | None,
    q4_manifest: dict[str, Any] | None,
    q4_derived: tuple[dict[str, Any], ...],
    quarterly: _AnalysisAttestation | None,
    annual: _AnalysisAttestation | None,
    configured_tickers: set[str],
) -> None:
    for publication in (quarterly, annual):
        if publication is not None and set(publication.companies) - configured_tickers:
            raise ValueError("prepared analysis contains a foreign configured ticker")
    q4_tickers = {str(row["ticker"]) for row in q4_derived}
    if quarterly is not None:
        reviewed = quarterly.manifest.get("reviewed_q4")
        if q4_manifest is None or q4_root is None or not isinstance(reviewed, dict):
            raise ValueError("quarterly analysis lacks its declared reviewed-Q4 identity")
        if Path(reviewed.get("publication", "")).resolve() != q4_root.resolve():
            raise ValueError("quarterly analysis references another reviewed-Q4 publication")
        if reviewed.get("publication_id") != q4_manifest.get("publication_id"):
            raise ValueError("quarterly analysis reviewed-Q4 publication ID differs")
        if reviewed.get("review_cutoff") != q4_manifest.get("review_cutoff"):
            raise ValueError("quarterly analysis reviewed-Q4 cutoff differs")
        q4_manifest_path = _regular_file(q4_root / "reviewed_q4_manifest.json", "Q4 manifest")
        if reviewed.get("manifest_sha256") != _sha256(q4_manifest_path):
            raise ValueError("quarterly analysis reviewed-Q4 manifest digest differs")
        if not q4_tickers.issubset(quarterly.companies):
            raise ValueError("quarterly analysis omits a reviewed-Q4 company")
    if annual is not None:
        if annual.manifest.get("reviewed_q4") is not None:
            raise ValueError("annual analysis must remain separate from reviewed Q4")
        if not q4_tickers.issubset(annual.companies):
            raise ValueError("annual analysis omits a reviewed-Q4 company")
    if q4_manifest is not None:
        selection_dates = tuple(sorted(q4_manifest.get("selection_as_of_dates", [])))
        for publication in (quarterly, annual):
            if publication is not None and publication.selection_as_of_dates != selection_dates:
                raise ValueError("prepared analysis selection as-of differs from reviewed Q4")
        expected_history = str(Path(q4_manifest["history_publication"]).resolve())
        for publication in (quarterly, annual):
            if publication is not None and publication.source_publications != (expected_history,):
                raise ValueError("prepared analysis source history differs from reviewed Q4")


def _readiness_model(
    *,
    config_path: Path,
    config: Any,
    collection_manifest: Path,
    collection_request: Path,
    collection_company_sources: list[dict[str, Any]],
    collection_status: Any,
    metadata: CompanyMetadataReader,
    metadata_rows: tuple[Any, ...],
    metadata_by_cik: dict[str, Any],
    q4_root: Path | None,
    q4_manifest: dict[str, Any] | None,
    q4_derived: tuple[dict[str, Any], ...],
    q4_exclusions: tuple[dict[str, Any], ...],
    quarterly: _AnalysisAttestation | None,
    annual: _AnalysisAttestation | None,
    accuracy: _AccuracyAttestation | None,
    source_bindings: SourceBindingsReader | None,
    expected_q4_economic_cells: int,
    expected_q4_view_records: int,
) -> dict[str, Any]:
    status_by_ticker = {row.ticker: row for row in collection_status.companies}
    q4_tickers = {str(row["ticker"]) for row in q4_derived}
    quarterly_tickers = set(quarterly.companies) if quarterly else set()
    annual_tickers = set(annual.companies) if annual else set()
    companies: list[dict[str, Any]] = []
    for target in config.companies:
        collection = status_by_ticker[target.ticker]
        master = metadata_by_cik[str(target.cik)]
        peers = metadata.peer_candidates(str(target.cik))
        q4_state = "REVIEWED_SCOPE" if target.ticker in q4_tickers else "OUTSIDE_REVIEWED_Q4_SCOPE"
        quarterly_state = "READY" if target.ticker in quarterly_tickers else "NOT_PREPARED"
        annual_state = "READY" if target.ticker in annual_tickers else "NOT_PREPARED"
        if collection.state not in {"RAW_COMPLETE", "READY"}:
            assessment = "RAW_PENDING" if "FAILED" not in collection.state else "RAW_FAILED"
        elif master.sic_code is None:
            assessment = "INDUSTRY_NOT_CLASSIFIED"
        elif target.ticker in q4_tickers and (quarterly_state != "READY" or annual_state != "READY"):
            assessment = "ANALYSIS_PENDING"
        elif target.ticker in q4_tickers:
            assessment = "ANALYSIS_PREPARED"
        else:
            assessment = "RAW_METADATA_READY"
        companies.append(
            {
                "ticker": target.ticker,
                "metadata_tickers": list(master.tickers),
                "cik": str(target.cik),
                "name": master.name,
                "groups": list(target.groups),
                "sic_code": master.sic_code,
                "sic_description": master.sic_description,
                "metadata_status": master.metadata_status,
                "industry_status": "CLASSIFIED" if master.sic_code is not None else "NOT_CLASSIFIED",
                "sic_peer_candidate_count": len(peers),
                "sic_peer_candidates": [
                    {
                        "cik": peer.cik,
                        "name": peer.name,
                        "tickers": list(peer.tickers),
                    }
                    for peer in peers
                ],
                "collection_state": collection.state,
                "collection_capability": collection.capability,
                "collection_action": collection.action,
                "selected_filings": collection.selected_filings,
                "held_filings": collection.held_filings,
                "pending_filings": collection.pending_filings,
                "failed_filings": collection.failed_filings,
                "report_start": collection.report_start,
                "report_end": collection.report_end,
                "q4_scope": q4_state,
                "quarterly_analysis": quarterly_state,
                "annual_analysis": annual_state,
                "assessment_state": assessment,
            }
        )
    if len(companies) != len({row["cik"] for row in companies}):
        raise ValueError("completion report would contain duplicate company rows")

    economic_keys = {
        (
            row.get("ticker"),
            row.get("cik"),
            row.get("fiscal_year"),
            row.get("member_qname"),
            row.get("mapping_epoch"),
            json.dumps(row.get("canonical_dimension_signature"), sort_keys=True),
            row.get("value_numeric"),
        )
        for row in q4_derived
    }
    q4_count_ready = (
        len(q4_derived) == expected_q4_view_records
        and len(economic_keys) == expected_q4_economic_cells
    )
    raw_complete = all(
        row["collection_state"] in {"RAW_COMPLETE", "READY"} for row in companies
    )
    collection_ready = all(row["collection_state"] == "READY" for row in companies)
    metadata_ready = all(row["sic_code"] is not None for row in companies)
    q4_ready = (
        q4_manifest is not None
        and q4_count_ready
        and set(q4_manifest.get("views", [])) == {"AS_FILED", "LATEST_REPORTED"}
        and all(row.get("status") == "DERIVED" for row in q4_derived)
    )
    quarterly_ready = quarterly is not None
    annual_ready = annual is not None
    current_history_publications = {
        str(Path(row["build"]["publication"]).resolve())
        for row in collection_company_sources
        if isinstance(row.get("build"), dict)
        and type(row["build"].get("publication")) is str
    }
    q4_parent = (
        str(Path(q4_manifest["history_publication"]).resolve())
        if q4_manifest is not None
        else None
    )
    q4_parent_relation = (
        "CURRENT_A_HISTORY"
        if q4_parent in current_history_publications
        else "SEPARATE_APPROVED_REFERENCE"
        if q4_parent is not None
        else None
    )
    failed = any(row["assessment_state"] == "RAW_FAILED" for row in companies)
    accuracy_state = accuracy.state if accuracy is not None else "NOT_PROVIDED"
    overall = (
        "FAILED"
        if failed
        else "BLOCKED"
        if accuracy_state == "BLOCKED"
        else "READY"
        if (
            collection_ready
            and metadata_ready
            and q4_ready
            and quarterly_ready
            and annual_ready
            and accuracy_state in {"PASS", "NOT_PROVIDED"}
        )
        else "PARTIAL"
    )
    classified = sum(row.sic_code is not None for row in metadata_rows)
    metadata_manifest = metadata.manifest
    q4_rows = [
        {
            "ticker": row.get("ticker"),
            "cik": row.get("cik"),
            "selection_view": row.get("selection_view"),
            "selection_as_of_date": row.get("selection_as_of_date"),
            "fiscal_year": row.get("fiscal_year"),
            "member_qname": row.get("member_qname"),
            "value_numeric": row.get("value_numeric"),
            "status": row.get("status"),
            "review_id": row.get("review_id"),
            "source_accessions": row.get("source_accessions"),
            "source_snapshot_ids": row.get("source_snapshot_ids"),
            "source_fact_ids": row.get("source_fact_ids"),
        }
        for row in sorted(
            q4_derived,
            key=lambda item: (
                str(item.get("ticker")),
                int(item.get("fiscal_year", 0)),
                str(item.get("member_qname")),
                str(item.get("selection_view")),
            ),
        )
    ]
    exclusion_rows = [
        {
            "ticker": row.get("ticker"),
            "selection_view": row.get("selection_view"),
            "fiscal_year": row.get("fiscal_year"),
            "member_qname": row.get("member_qname"),
            "reason": row.get("reason"),
            "detail": row.get("detail"),
        }
        for row in q4_exclusions
    ]
    return {
        "version": VERSION,
        "title": "기업·산업·원자료·분석준비·Q4범위",
        "universe_id": config.universe_id,
        "assessment_state": overall,
        "dates": {
            "financial_as_of": config.as_of_date.isoformat(),
            "collection_source_observed_at": config.source_observed_at,
            "metadata_cutoff": metadata_manifest.get("cutoff"),
            "metadata_observed_at": sorted(
                {
                    row.get("observed_at")
                    for row in metadata_manifest.get("selected_inputs", [])
                    if row.get("observed_at")
                }
            ),
            "metadata_candidate_inventory_observed_at": (
                metadata_manifest.get("candidate_inventory", {}).get("observed_at")
                if isinstance(metadata_manifest.get("candidate_inventory"), dict)
                else None
            ),
            "q4_selection_as_of_dates": (
                list(q4_manifest.get("selection_as_of_dates", [])) if q4_manifest else []
            ),
            "q4_review_cutoff": q4_manifest.get("review_cutoff") if q4_manifest else None,
        },
        "assessments": {
            "collection": {
                "state": (
                    "READY"
                    if collection_ready
                    else "RAW_COMPLETE"
                    if raw_complete
                    else "PARTIAL"
                ),
                "requested_companies": collection_status.requested_companies,
                "raw_complete_companies": collection_status.raw_complete_companies,
                "ready_companies": collection_status.ready_companies,
                "selected_filings": collection_status.selected_filings,
                "held_filings": collection_status.held_filings,
                "pending_filings": collection_status.pending_filings,
                "failed_filings": collection_status.failed_filings,
                "reused_filings": collection_status.reused_filings,
                "reused_interpretation": (
                    "REUSED는 이 최종 run에서 검증 후 채택한 상태이며, 원래 외부 baseline과 "
                    "신규 취득 건수를 뜻하지 않습니다."
                ),
            },
            "metadata": {
                "state": "READY" if metadata_ready else "PARTIAL",
                "candidate_issuers": len(metadata_rows),
                "classified_issuers": classified,
                "unclassified_issuers": len(metadata_rows) - classified,
                "pilot_companies": len(companies),
                "pilot_sic_classified": sum(row["sic_code"] is not None for row in companies),
                "coverage_note": "SEC SIC 미분류 후보도 회사 마스터에 유지됩니다.",
            },
            "reviewed_q4": {
                "state": "READY" if q4_ready else "PENDING",
                "expected_economic_cells": expected_q4_economic_cells,
                "economic_cells": len(economic_keys),
                "expected_view_records": expected_q4_view_records,
                "view_records": len(q4_derived),
                "exclusions": len(q4_exclusions),
                "parent_history_relation": q4_parent_relation,
            },
            "quarterly_analysis": {
                "state": "READY" if quarterly_ready else "PENDING",
                "companies": list(quarterly.companies) if quarterly else [],
                "period_mode": quarterly.period_mode if quarterly else None,
            },
            "annual_analysis": {
                "state": "READY" if annual_ready else "PENDING",
                "companies": list(annual.companies) if annual else [],
                "period_mode": annual.period_mode if annual else None,
            },
            "duration_conformance": {
                "state": accuracy_state,
                "required_for_this_delivery": accuracy is not None,
                "reason": accuracy.reason if accuracy else None,
                "parser_version": accuracy.parser_version if accuracy else None,
                "parser_rule_version": (
                    accuracy.parser_rule_version if accuracy else None
                ),
                "supported_lexical_repair_policy": (
                    accuracy.payload.get("supported_lexical_repair_policy")
                    if accuracy
                    else None
                ),
                "frozen_commit_sha": accuracy.frozen_commit_sha if accuracy else None,
                "source_packages": (
                    accuracy.payload.get("source_packages") if accuracy else None
                ),
                "filing_checks": (
                    len(accuracy.payload.get("filing_checks", [])) if accuracy else 0
                ),
                "source_index": (
                    accuracy.payload.get("source_index") if accuracy else None
                ),
                "source_binding_publication": (
                    accuracy.payload.get("source_binding_publication")
                    if accuracy
                    else None
                ),
                "fact_level_evidence": (
                    accuracy.payload.get("fact_level_evidence") if accuracy else None
                ),
                "approved_transform_corrections": (
                    accuracy.payload.get("approved_transform_corrections")
                    if accuracy
                    else None
                ),
                "approved_correction_summary": (
                    accuracy.approved_correction_summary if accuracy else None
                ),
                "transform_checks": (
                    accuracy.payload.get("transform_checks") if accuracy else None
                ),
                "normalized_value_checks": (
                    accuracy.payload.get("normalized_value_checks", [])
                    if accuracy
                    else []
                ),
                "foreign_change_counts": (
                    accuracy.payload.get("foreign_change_counts") if accuracy else None
                ),
                "ingestion_gates": (
                    accuracy.payload.get("ingestion_gates") if accuracy else None
                ),
                "invalid_duration_lexical_fails_closed": (
                    accuracy.payload.get("invalid_duration_lexical_fails_closed")
                    if accuracy
                    else None
                ),
            },
        },
        "sources": {
            "config": _source(config_path),
            "collection_manifest": _source(collection_manifest),
            "collection_request": _source(collection_request),
            "collection_companies": collection_company_sources,
            "metadata": {
                **_source(metadata.manifest_path),
                "root": str(metadata.root),
                "publication_id": metadata.publication_id,
            },
            "reviewed_q4": _optional_publication_source(q4_root, q4_manifest),
            "quarterly_analysis": _analysis_source(quarterly),
            "annual_analysis": _analysis_source(annual),
            "accuracy_assessment": _accuracy_source(accuracy),
            "source_binding_publication": _source_binding_source(source_bindings),
        },
        "companies": companies,
        "reviewed_q4": {
            "rows": q4_rows,
            "exclusions": exclusion_rows,
            "scope_note": "승인된 정확한 FY/YTD-9M 원천쌍만 표시하며 HTML에서 Q4를 계산하지 않습니다.",
        },
        "warnings": [
            f"Raw SEC transform conformance 판정은 {accuracy_state}입니다.",
            (
                "승인된 SEC 표기 지원 보완은 "
                f"{accuracy.payload.get('approved_transform_corrections', {}).get('record_count', 0) if accuracy else 0}건이며, "
                f"그중 monetary {accuracy.approved_correction_summary.get('value_classes', {}).get('monetary', 0) if accuracy else 0}건, "
                f"shares {accuracy.approved_correction_summary.get('value_classes', {}).get('shares', 0) if accuracy else 0}건입니다. "
                "그 밖의 미승인 foreign change는 0이어야 합니다."
            ),
            (
                "Q4 원천 parent는 현재 A history입니다."
                if q4_parent_relation == "CURRENT_A_HISTORY"
                else "Q4 원천 parent는 현재 A history와 분리된 승인 reference입니다."
                if q4_parent_relation == "SEPARATE_APPROVED_REFERENCE"
                else "Q4 원천 parent가 아직 제공되지 않았습니다."
            ),
            "재무 수집 기준일, SEC 메타데이터 관측시각, 분석 선택 기준일, Q4 검토시각은 서로 다른 provenance입니다.",
            "서로 다른 기준일의 값을 동일 기준 횡단면처럼 비교하지 않습니다.",
            "SEC SIC는 동종 후보 신호이며 회계적 동등성을 뜻하지 않습니다.",
            "미검토 segment/geography 및 mapping epoch 범위는 보류 상태로 남습니다.",
            "최종 run의 REUSED 수와 최초 외부 baseline·신규 취득 이력은 서로 다른 provenance입니다.",
        ],
    }


def _optional_publication_source(
    root: Path | None, manifest: dict[str, Any] | None
) -> dict[str, Any] | None:
    if root is None or manifest is None:
        return None
    path = _regular_file(root / "reviewed_q4_manifest.json", "Q4 manifest")
    return {
        **_source(path),
        "root": str(root.resolve()),
        "publication_id": manifest.get("publication_id"),
        "history_publication": manifest.get("history_publication"),
        "history_manifest_sha256": manifest.get("history_manifest_sha256"),
        "source_evidence_path": manifest.get("source_evidence_path"),
        "source_evidence_sha256": manifest.get("source_evidence_sha256"),
        "review_ledger_path": manifest.get("review_ledger_path"),
        "review_ledger_sha256": manifest.get("review_ledger_sha256"),
        "source_snapshots": manifest.get("source_snapshots", []),
    }


def _analysis_source(value: _AnalysisAttestation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "root": str(value.root),
        "manifest_path": str(value.manifest_path),
        "manifest_sha256": value.manifest_sha256,
        "publication_id": value.publication_id,
        "period_mode": value.period_mode,
        "selection_as_of_dates": list(value.selection_as_of_dates),
        "source_publications": list(value.source_publications),
    }


def _accuracy_source(value: _AccuracyAttestation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "path": str(value.path),
        "sha256": value.sha256,
        "schema_version": ACCURACY_SCHEMA,
        "state": value.state,
        "parser_version": value.parser_version,
        "parser_rule_version": value.parser_rule_version,
        "frozen_commit_sha": value.frozen_commit_sha,
        "evidence_files": list(value.evidence_files),
    }


def _source_binding_source(value: SourceBindingsReader | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "root": str(value.root),
        "manifest_path": str(value.manifest_path),
        "manifest_sha256": _sha256(value.manifest_path),
        "publication_id": value.publication_id,
        "producer_revision": value.manifest.get("producer_revision"),
        "counts": value.manifest.get("counts"),
    }


def _source(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _publish(report: dict[str, Any], destination: Path) -> UniverseDeliveryPublication:
    _safe_new_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        json_path = staging / READINESS_JSON
        csv_path = staging / READINESS_CSV
        html_path = staging / REPORT_HTML
        readme_path = staging / REPRO_README
        json_path.write_text(_json(report) + "\n", encoding="utf-8")
        _write_csv(csv_path, report["companies"])
        html_path.write_text(_render_html(report), encoding="utf-8")
        readme_path.write_text(_render_readme(report), encoding="utf-8")
        files = {
            path.name: {"sha256": _sha256(path), "size": path.stat().st_size}
            for path in (json_path, csv_path, html_path, readme_path)
        }
        identity = {
            "version": VERSION,
            "universe_id": report["universe_id"],
            "assessment_state": report["assessment_state"],
            "sources": report["sources"],
            "files": files,
        }
        publication_id = "universe-delivery-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        manifest = {**identity, "publication_id": publication_id}
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(_json(manifest) + "\n", encoding="utf-8")
        UniverseDeliveryReader(staging, allow_staging=True)
        os.rename(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    reader = UniverseDeliveryReader(destination)
    return UniverseDeliveryPublication(
        root=destination,
        publication_id=reader.publication_id,
        manifest_path=destination / MANIFEST_NAME,
        readiness_json=destination / READINESS_JSON,
        readiness_csv=destination / READINESS_CSV,
        report_html=destination / REPORT_HTML,
        readme=destination / REPRO_README,
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "ticker",
        "cik",
        "name",
        "sic_code",
        "sic_description",
        "sic_peer_candidate_count",
        "collection_state",
        "selected_filings",
        "held_filings",
        "pending_filings",
        "q4_scope",
        "quarterly_analysis",
        "annual_analysis",
        "assessment_state",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _render_readme(report: dict[str, Any]) -> str:
    lines = [
        "# Company-universe completion publication",
        "",
        f"- Version: `{report['version']}`",
        f"- Universe: `{report['universe_id']}`",
        f"- Assessment: `{report['assessment_state']}`",
        f"- Financial as-of: `{report['dates']['financial_as_of']}`",
        "",
        "This directory was rendered offline from immutable prepared outputs. It does not",
        "collect SEC data, parse XBRL, select facts, or calculate Q4 values.",
        "",
        "## Inputs",
        "",
    ]
    for name, value in report["sources"].items():
        if isinstance(value, dict):
            path = value.get("root") or value.get("path")
            digest = value.get("manifest_sha256") or value.get("sha256")
            lines.append(f"- {name}: `{path}` (`{digest}`)")
        elif isinstance(value, list):
            lines.append(f"- {name}: {len(value)} per-company source attestations in JSON")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            "- `company_readiness.json`: complete joined data and source identities",
            "- `company_readiness.csv`: one row per configured CIK",
            "- `index.html`: Korean completion and scope view",
            "- `universe_delivery_manifest.json`: output hashes and publication identity",
            "",
            "The final-run REUSED count is replay/adoption provenance. Original baseline and",
            "new-acquisition history remains a separate runtime record.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_html(report: dict[str, Any]) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    assessments = report["assessments"]
    cards = "".join(
        f"<article><h2>{esc(label)}</h2><strong>{esc(value['state'])}</strong><p>{esc(detail)}</p></article>"
        for label, value, detail in (
            (
                "원자료 수집",
                assessments["collection"],
                f"회사 {assessments['collection']['raw_complete_companies']}/{assessments['collection']['requested_companies']} · 공시 {assessments['collection']['held_filings']}/{assessments['collection']['selected_filings']}",
            ),
            (
                "회사·산업",
                assessments["metadata"],
                f"후보 {assessments['metadata']['candidate_issuers']} · SIC 분류 {assessments['metadata']['classified_issuers']} · 미분류 {assessments['metadata']['unclassified_issuers']}",
            ),
            (
                "검토 Q4",
                assessments["reviewed_q4"],
                f"경제값 {assessments['reviewed_q4']['economic_cells']}/{assessments['reviewed_q4']['expected_economic_cells']} · view 기록 {assessments['reviewed_q4']['view_records']}/{assessments['reviewed_q4']['expected_view_records']} · parent {assessments['reviewed_q4']['parent_history_relation'] or '미제공'}",
            ),
            (
                "분기 분석",
                assessments["quarterly_analysis"],
                f"준비 회사 {len(assessments['quarterly_analysis']['companies'])}",
            ),
            (
                "연간 분석",
                assessments["annual_analysis"],
                f"준비 회사 {len(assessments['annual_analysis']['companies'])}",
            ),
            (
                "Raw SEC transform 정확성",
                assessments["duration_conformance"],
                (
                    f"parser {assessments['duration_conformance']['parser_version'] or '미제공'} · "
                    f"검증 commit {assessments['duration_conformance']['frozen_commit_sha'] or '미제공'} · "
                    f"승인된 SEC 표기 지원 보완 {(assessments['duration_conformance']['approved_transform_corrections'] or {}).get('record_count', 0)}"
                ),
            ),
        )
    )
    company_rows = "".join(
        "<tr>"
        f"<td>{esc(row['ticker'])}</td><td>{esc(row['cik'])}</td><td>{esc(row['name'])}</td>"
        f"<td>{esc(row['sic_code'])} {esc(row['sic_description'])}<br>동일 SIC 후보 {row['sic_peer_candidate_count']}개</td>"
        f"<td>{esc(row['collection_state'])}</td><td>{row['held_filings']}/{row['selected_filings']}</td>"
        f"<td>{esc(row['q4_scope'])}</td><td>{esc(row['quarterly_analysis'])}</td>"
        f"<td>{esc(row['annual_analysis'])}</td><td>{esc(row['assessment_state'])}</td>"
        "</tr>"
        for row in report["companies"]
    )
    q4_rows = "".join(
        "<tr>"
        f"<td>{esc(row['ticker'])}</td><td>{esc(row['selection_view'])}</td>"
        f"<td>FY{esc(row['fiscal_year'])} Q4</td><td>{esc(row['member_qname'])}</td>"
        f"<td>{esc(row['value_numeric'])}</td><td>{esc(row['status'])}</td>"
        f"<td>{esc(', '.join(row['source_accessions'] or []))}</td>"
        "</tr>"
        for row in report["reviewed_q4"]["rows"]
    ) or '<tr><td colspan="7">준비된 검토 Q4 publication이 없습니다.</td></tr>'
    exclusion_rows = "".join(
        "<li>"
        f"{esc(row['ticker'] or '정책')} · {esc(row['selection_view'])} · "
        f"FY{esc(row['fiscal_year'])} · {esc(row['member_qname'])}: {esc(row['reason'])}"
        "</li>"
        for row in report["reviewed_q4"]["exclusions"]
    ) or "<li>기록된 제외 범위 없음</li>"
    warnings = "".join(f"<li>{esc(value)}</li>" for value in report["warnings"])
    dates = report["dates"]
    date_rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"
        for label, value in (
            ("재무 수집 기준일", dates["financial_as_of"]),
            ("수집 source 관측시각", dates["collection_source_observed_at"]),
            ("메타데이터 cutoff", dates["metadata_cutoff"] or "미지정"),
            ("메타데이터 관측시각", ", ".join(dates["metadata_observed_at"])),
            (
                "후보 inventory 관측시각",
                dates["metadata_candidate_inventory_observed_at"] or "미지정",
            ),
            ("분석 선택 기준일", ", ".join(dates["q4_selection_as_of_dates"])),
            ("Q4 검토 cutoff", dates["q4_review_cutoff"] or "미지정"),
        )
    )
    sources = "".join(
        f"<tr><th>{esc(name)}</th><td><code>{esc(value.get('root') or value.get('path'))}</code></td>"
        f"<td><code>{esc(value.get('manifest_sha256') or value.get('sha256'))}</code></td></tr>"
        for name, value in report["sources"].items()
        if isinstance(value, dict)
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(report['title'])}</title><style>
body{{font-family:system-ui,sans-serif;margin:2rem;background:#f4f6f8;color:#17202a}}main{{max-width:1500px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}}article,section{{background:white;border:1px solid #dfe5eb;border-radius:10px;padding:1rem;margin:1rem 0}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}th,td{{border-bottom:1px solid #e7ebef;padding:.55rem;text-align:left;vertical-align:top}}th{{background:#f8fafc}}code{{word-break:break-all}}.warning{{border-left:5px solid #c47b00}}
</style></head><body><main>
<h1>{esc(report['title'])}</h1><p>전체 판정: <strong>{esc(report['assessment_state'])}</strong></p>
<div class="cards">{cards}</div>
<section class="warning"><h2>기준일을 분리해서 읽기</h2><ul>{warnings}</ul>
<table><tbody>{date_rows}</tbody></table></section>
<section><h2>기업·산업·원자료·분석준비</h2><table><thead><tr><th>티커</th><th>CIK</th><th>회사</th><th>SEC SIC</th><th>원자료</th><th>보유/선택</th><th>Q4 범위</th><th>분기</th><th>연간</th><th>판정</th></tr></thead><tbody>{company_rows}</tbody></table></section>
<section><h2>검토된 Q4 범위</h2><p>{esc(report['reviewed_q4']['scope_note'])}</p><table><thead><tr><th>회사</th><th>선택 view</th><th>기간</th><th>구성원</th><th>값</th><th>상태</th><th>원천 accession</th></tr></thead><tbody>{q4_rows}</tbody></table></section>
<section><h2>검토 보류·제외 범위</h2><ul>{exclusion_rows}</ul></section>
<section><h2>Publication source identity</h2><table><tbody>{sources}</tbody></table></section>
</main></body></html>"""


def _safe_new_destination(destination: Path) -> None:
    absolute = destination.absolute()
    for path in (absolute, *absolute.parents):
        if path.is_symlink():
            raise ValueError("completion destination traverses a symlink")
    if destination.exists():
        raise ValueError("completion publication requires a new destination")


def _real_directory(path: Path, label: str) -> Path:
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"{label} is not a real directory: {path}")
    return path.resolve()


def _regular_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path.resolve()


def _contained_file(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path is unsafe")
    root = root.resolve()
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    path = _regular_file(root / relative, label)
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes its publication")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--collection-manifest", type=Path, required=True)
    parser.add_argument("--metadata-publication", type=Path, required=True)
    parser.add_argument("--reviewed-q4-publication", type=Path)
    parser.add_argument("--quarterly-analysis", type=Path)
    parser.add_argument("--annual-analysis", type=Path)
    parser.add_argument("--accuracy-assessment", type=Path)
    parser.add_argument("--source-binding-publication", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-q4-economic-cells", type=int, default=16)
    parser.add_argument("--expected-q4-view-records", type=int, default=32)
    args = parser.parse_args()
    publication = publish_universe_delivery(
        config_path=args.config,
        collection_manifest=args.collection_manifest,
        metadata_publication=args.metadata_publication,
        reviewed_q4_publication=args.reviewed_q4_publication,
        quarterly_analysis=args.quarterly_analysis,
        annual_analysis=args.annual_analysis,
        accuracy_assessment=args.accuracy_assessment,
        source_binding_publication=args.source_binding_publication,
        destination=args.destination,
        expected_q4_economic_cells=args.expected_q4_economic_cells,
        expected_q4_view_records=args.expected_q4_view_records,
    )
    print(publication.report_html)


if __name__ == "__main__":
    main()
