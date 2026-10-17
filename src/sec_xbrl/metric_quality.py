"""Offline Raw transform/source-conformance quality for generic metric identity.

This publication makes a deliberately narrow claim. It proves complete source
binding and normalized-value conformance for SEC duration transforms and the
approved lexical repair set. It does not attest financial metric semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.collection_operations import read_universe_status
from sec_xbrl.filing.sec_inline_transforms import _decimal_duration, _week_duration
from sec_xbrl.history import HISTORY_VERSION, HistoryPublicationReader
from sec_xbrl.source_bindings import (
    BINDINGS_NAME,
    DOCUMENTS_NAME,
    KNOWN_PARSER_PROFILES,
    SourceBindingsV2Reader,
    publish_source_bindings_v2,
    verify_source_bindings_v2_producer_completeness,
    write_source_indexes_v2,
)

SCHEMA_VERSION = "generic-metric-quality-v1"
CONFIG_SCHEMA_VERSION = "generic-metric-quality-config-v1"
MANIFEST_NAME = "generic_metric_quality_manifest.json"
REPORT_NAME = "raw_transform_conformance_report.json"
ASSURANCE_SCOPE = "RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY"
COLLECTOR_PROVENANCE_ASSURANCE = "CONFIG_DECLARED_NOT_SOURCE_VERIFIED"
COLLECTOR_PROVENANCE_GRANULARITY = "COMPANY_CONFIG_DECLARATION"
RULE_VERSIONS = {
    "quality_rule": "generic-metric-raw-transform-quality-v1",
    "duration_transform_rule": "sec-duration-conformance-v1",
    "approved_lexical_repair_rule": "sec-supported-lexical-repairs-v1",
    "source_binding_schema": "sec-source-bindings-v2",
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class GenericMetricQualityPublication:
    root: Path
    publication_id: str
    manifest_path: Path
    report_path: Path


def prepare_generic_metric_quality(
    *,
    config_path: Path,
    collection_manifest: Path,
    package_root: Path,
    history_manifests: dict[str, Path],
    source_index_destination: Path,
    source_binding_destination: Path,
    destination: Path,
    producer_revision: str,
) -> GenericMetricQualityPublication:
    """Run the complete public offline source-only quality preparation."""
    config = _load_config(config_path)
    companies = tuple(config["collection_scope_companies"])
    _preflight_quality_inputs(
        config=config,
        collection_manifest=collection_manifest,
        history_manifests=history_manifests,
    )
    indexes = write_source_indexes_v2(
        collection_manifest=collection_manifest,
        package_root=package_root,
        destination=source_index_destination,
        collection_scope_companies=companies,
    )
    bindings = publish_source_bindings_v2(
        collection_manifest=collection_manifest,
        package_root=package_root,
        duration_source_index=indexes.duration_path,
        correction_source_index=indexes.correction_path,
        destination=source_binding_destination,
        producer_revision=producer_revision,
        collection_scope_companies=companies,
    )
    return publish_generic_metric_quality(
        config_path=config_path,
        collection_manifest=collection_manifest,
        source_binding_publication=bindings.root,
        history_manifests=history_manifests,
        destination=destination,
        producer_revision=producer_revision,
    )


def _preflight_quality_inputs(
    *,
    config: dict[str, Any],
    collection_manifest: Path,
    history_manifests: dict[str, Path],
) -> None:
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    collection = _read_json(collection_manifest)
    request_path = _regular_file(Path(str(collection.get("request_path"))), "collection request")
    if collection.get("request_sha256") != _sha256(request_path):
        raise ValueError("collection request digest changed")
    request = _read_json(request_path)
    companies = tuple(config["collection_scope_companies"])
    parent = _company_scope(request.get("companies"), "parent collection")
    if config["financial_as_of"] != request.get("as_of_date"):
        raise ValueError("generic quality cutoff differs from collection")
    if not {(row["ticker"], row["cik"]) for row in companies}.issubset(
        {(row["ticker"], row["cik"]) for row in parent}
    ):
        raise ValueError("generic quality scope is outside parent collection")
    provenance = {
        (row["ticker"], row["cik"]): row for row in config["source_provenance"]
    }
    readiness = _validate_status(
        collection_manifest=collection_manifest,
        parent_companies=parent,
        expected_companies=companies,
    )
    _validate_source_provenance(
        collection_manifest=collection_manifest,
        collection=collection,
        expected_companies=companies,
        provenance=provenance,
    )
    _validate_histories(
        history_manifests=history_manifests,
        expected_companies=companies,
        provenance=provenance,
        financial_as_of=config["financial_as_of"],
        readiness=readiness,
    )


def publish_generic_metric_quality(
    *,
    config_path: Path,
    collection_manifest: Path,
    source_binding_publication: Path,
    history_manifests: dict[str, Path],
    destination: Path,
    producer_revision: str,
) -> GenericMetricQualityPublication:
    """Validate all governed inputs, then atomically publish a narrow PASS."""
    if _COMMIT.fullmatch(producer_revision) is None:
        raise ValueError("producer_revision must be a 40-character commit SHA")
    config_path = _regular_file(config_path, "generic quality config")
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    config = _load_config(config_path)
    companies = tuple(config["collection_scope_companies"])
    company_keys = tuple((row["ticker"], row["cik"]) for row in companies)
    provenance = {
        (row["ticker"], row["cik"]): row for row in config["source_provenance"]
    }
    destination = _new_destination(destination, "generic quality")

    collection = _read_json(collection_manifest)
    request_path = _regular_file(Path(str(collection.get("request_path"))), "collection request")
    if collection.get("request_sha256") != _sha256(request_path):
        raise ValueError("collection request digest changed")
    request = _read_json(request_path)
    parent_companies = _company_scope(request.get("companies"), "parent collection")
    if not set(company_keys).issubset({(row["ticker"], row["cik"]) for row in parent_companies}):
        raise ValueError("generic quality scope is outside parent collection")
    if config["financial_as_of"] != request.get("as_of_date"):
        raise ValueError("generic quality cutoff differs from collection")
    readiness = _validate_status(
        collection_manifest=collection_manifest,
        parent_companies=parent_companies,
        expected_companies=companies,
    )
    _validate_source_provenance(
        collection_manifest=collection_manifest,
        collection=collection,
        expected_companies=companies,
        provenance=provenance,
    )
    histories = _validate_histories(
        history_manifests=history_manifests,
        expected_companies=companies,
        provenance=provenance,
        financial_as_of=config["financial_as_of"],
        readiness=readiness,
    )

    bindings = SourceBindingsV2Reader(Path(source_binding_publication))
    bindings.verify_all()
    verify_source_bindings_v2_producer_completeness(bindings)
    binding_collection = bindings.manifest.get("collection")
    if (
        bindings.manifest.get("scope_companies") != list(companies)
        or bindings.manifest.get("financial_as_of") != config["financial_as_of"]
        or not isinstance(binding_collection, dict)
        or binding_collection.get("manifest_sha256") != _sha256(collection_manifest)
    ):
        raise ValueError("source-binding v2 scope differs from generic quality config")
    report = _conformance_report(bindings)
    if report["state"] != "PASS":
        raise ValueError("Raw transform conformance did not pass")

    documents = {
        (str(row["ticker"]), str(row["cik"]), str(row["accession"])): row
        for row in bindings.documents
    }
    filings: list[dict[str, Any]] = []
    for key, document in sorted(documents.items()):
        company_provenance = provenance[(key[0], key[1])]
        filings.append(
            {
                "ticker": key[0],
                "cik": key[1],
                "accession": key[2],
                "parser_version": document["parser_version"],
                "parser_profile": document["parser_profile"],
                "snapshot_manifest_sha256": document["snapshot_manifest_sha256"],
                "package_sha256": document["package_sha256"],
                "primary_sha256": document["primary_sha256"],
                "source_binding_publication_id": bindings.publication_id,
                "source_binding_manifest_sha256": _sha256(bindings.manifest_path),
                "collector_source_commit_sha": company_provenance[
                    "collector_source_commit_sha"
                ],
                "plan_sha256": company_provenance["plan_sha256"],
                "intake_sha256": company_provenance["intake_sha256"],
            }
        )

    evidence_hashes = {
        "config": {"path": str(config_path), "sha256": _sha256(config_path)},
        "collection_manifest": {
            "path": str(collection_manifest),
            "sha256": _sha256(collection_manifest),
        },
        "collection_request": {"path": str(request_path), "sha256": _sha256(request_path)},
        "source_binding_manifest": {
            "path": str(bindings.manifest_path),
            "sha256": _sha256(bindings.manifest_path),
        },
        "source_binding_documents": {
            "path": str(bindings.root / DOCUMENTS_NAME),
            "sha256": _sha256(bindings.root / DOCUMENTS_NAME),
        },
        "source_binding_records": {
            "path": str(bindings.root / BINDINGS_NAME),
            "sha256": _sha256(bindings.root / BINDINGS_NAME),
        },
        "duration_source_index": dict(
            bindings.manifest["candidate_inputs"]["duration_source_index"]
        ),
        "correction_source_index": dict(
            bindings.manifest["candidate_inputs"]["correction_source_index"]
        ),
        "history_manifests": histories,
        "collection_build_manifests": {
            row["ticker"]: {
                "path": row["build_manifest_path"],
                "sha256": row["build_manifest_sha256"],
            }
            for row in readiness
        },
    }
    parser_profiles = bindings.manifest["parser_profiles"]
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        report_path = _write_json(staging / REPORT_NAME, report)
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "state": "PASS",
            "assurance_scope": ASSURANCE_SCOPE,
            "full_financial_semantic_assurance": False,
            "collector_provenance_assurance": COLLECTOR_PROVENANCE_ASSURANCE,
            "collector_provenance_granularity": COLLECTOR_PROVENANCE_GRANULARITY,
            "producer_revision": producer_revision,
            "financial_as_of": config["financial_as_of"],
            "collection_scope_mode": (
                "FULL" if companies == parent_companies else "EXPLICIT_SUBSET"
            ),
            "collection_manifest_sha256": _sha256(collection_manifest),
            "collection_request_sha256": _sha256(request_path),
            "parent_collection_companies": list(parent_companies),
            "parent_collection_companies_sha256": _json_sha256(parent_companies),
            "companies": list(companies),
            "companies_sha256": _json_sha256(companies),
            "filing_count": len(filings),
            "filings": filings,
            "history_manifest_sha256s": {
                ticker: declaration["sha256"] for ticker, declaration in histories.items()
            },
            "collection_status": list(readiness),
            "source_binding": {
                "root": str(bindings.root),
                "publication_id": bindings.publication_id,
                "manifest_sha256": _sha256(bindings.manifest_path),
            },
            "parser_profiles": parser_profiles,
            "rule_versions": dict(RULE_VERSIONS),
            "evidence_hashes": evidence_hashes,
            "files": {REPORT_NAME: _file_declaration(report_path)},
        }
        manifest["publication_id"] = "generic-metric-quality-" + hashlib.sha256(
            _canonical_json(manifest).encode("utf-8")
        ).hexdigest()[:24]
        _write_json(staging / MANIFEST_NAME, manifest)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return GenericMetricQualityPublication(
        root=destination,
        publication_id=str(manifest["publication_id"]),
        manifest_path=destination / MANIFEST_NAME,
        report_path=destination / REPORT_NAME,
    )


class GenericMetricQualityReader:
    """Verify an immutable generic metric quality publication and its sources."""

    def __init__(self, root: Path, manifest_sha256: str | None = None) -> None:
        self.root = _real_directory(root, "generic metric quality publication")
        children = tuple(self.root.iterdir())
        if {path.name for path in children} != {MANIFEST_NAME, REPORT_NAME} or any(
            path.is_symlink() or not path.is_file() for path in children
        ):
            raise ValueError("generic metric quality file set is invalid")
        self.manifest_path = self.root / MANIFEST_NAME
        if manifest_sha256 is not None:
            if _SHA256.fullmatch(manifest_sha256) is None:
                raise ValueError("generic metric quality manifest digest is invalid")
            if _sha256(self.manifest_path) != manifest_sha256:
                raise ValueError("generic metric quality manifest digest differs")
        self.manifest = _read_json(self.manifest_path)
        if (
            self.manifest.get("schema_version") != SCHEMA_VERSION
            or self.manifest.get("state") != "PASS"
            or self.manifest.get("assurance_scope") != ASSURANCE_SCOPE
            or self.manifest.get("full_financial_semantic_assurance") is not False
            or self.manifest.get("collector_provenance_assurance")
            != COLLECTOR_PROVENANCE_ASSURANCE
            or self.manifest.get("collector_provenance_granularity")
            != COLLECTOR_PROVENANCE_GRANULARITY
            or self.manifest.get("rule_versions") != RULE_VERSIONS
        ):
            raise ValueError("generic metric quality proof is invalid")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or set(files) != {REPORT_NAME}:
            raise ValueError("generic metric quality file declaration is invalid")
        _verify_file_declaration(self.root / REPORT_NAME, files[REPORT_NAME], REPORT_NAME)
        identity = {key: value for key, value in self.manifest.items() if key != "publication_id"}
        publication_id = "generic-metric-quality-" + hashlib.sha256(
            _canonical_json(identity).encode("utf-8")
        ).hexdigest()[:24]
        if self.manifest.get("publication_id") != publication_id:
            raise ValueError("generic metric quality identity mismatch")
        self.publication_id = publication_id
        self._validate_basic_proof()

    def _validate_basic_proof(self) -> None:
        companies = _company_scope(self.manifest.get("companies"), "quality")
        parent = _company_scope(
            self.manifest.get("parent_collection_companies"), "parent collection"
        )
        if (
            self.manifest.get("companies") != list(companies)
            or self.manifest.get("parent_collection_companies") != list(parent)
            or self.manifest.get("companies_sha256") != _json_sha256(companies)
            or self.manifest.get("parent_collection_companies_sha256")
            != _json_sha256(parent)
            or not {(row["ticker"], row["cik"]) for row in companies}.issubset(
                {(row["ticker"], row["cik"]) for row in parent}
            )
        ):
            raise ValueError("generic metric quality company scope is invalid")
        expected_mode = "FULL" if companies == parent else "EXPLICIT_SUBSET"
        if (
            self.manifest.get("collection_scope_mode") != expected_mode
            or type(self.manifest.get("financial_as_of")) is not str
            or not self.manifest["financial_as_of"]
            or _COMMIT.fullmatch(str(self.manifest.get("producer_revision"))) is None
            or any(
                _SHA256.fullmatch(str(self.manifest.get(field))) is None
                for field in ("collection_manifest_sha256", "collection_request_sha256")
            )
        ):
            raise ValueError("generic metric quality scope mode is invalid")
        histories = self.manifest.get("history_manifest_sha256s")
        if (
            not isinstance(histories, dict)
            or set(histories) != {row["ticker"] for row in companies}
            or any(_SHA256.fullmatch(str(value)) is None for value in histories.values())
        ):
            raise ValueError("generic metric quality history proof is invalid")
        readiness = self.manifest.get("collection_status")
        if (
            not isinstance(readiness, list)
            or [str(row.get("ticker")) for row in readiness if isinstance(row, dict)]
            != [row["ticker"] for row in companies]
            or any(
                not isinstance(row, dict)
                or row.get("state") != "READY"
                or row.get("selected_filings") != row.get("held_filings")
                or row.get("pending_filings") != 0
                or row.get("failed_filings") != 0
                or type(row.get("build_manifest_path")) is not str
                or not Path(row["build_manifest_path"]).is_absolute()
                or _SHA256.fullmatch(str(row.get("build_manifest_sha256"))) is None
                or any(
                    type(row.get(field)) is not str
                    or not Path(row[field]).is_absolute()
                    for field in (
                        "plan_path",
                        "intake_manifest_path",
                        "history_manifest_path",
                    )
                )
                or any(
                    _SHA256.fullmatch(str(row.get(field))) is None
                    for field in (
                        "plan_sha256",
                        "intake_sha256",
                        "history_manifest_sha256",
                    )
                )
                for row in readiness
            )
        ):
            raise ValueError("generic metric quality collection status proof is invalid")
        source_binding = self.manifest.get("source_binding")
        if (
            not isinstance(source_binding, dict)
            or type(source_binding.get("root")) is not str
            or not Path(source_binding["root"]).is_absolute()
            or type(source_binding.get("publication_id")) is not str
            or not source_binding["publication_id"].startswith("source-bindings-v2-")
            or _SHA256.fullmatch(str(source_binding.get("manifest_sha256"))) is None
        ):
            raise ValueError("generic metric quality source-binding proof is invalid")
        filings = self.manifest.get("filings")
        if (
            not isinstance(filings, list)
            or self.manifest.get("filing_count") != len(filings)
            or not filings
        ):
            raise ValueError("generic metric quality filing scope is invalid")
        identities: set[tuple[str, str, str]] = set()
        used_profiles: set[str] = set()
        for filing in filings:
            if not isinstance(filing, dict):
                raise TypeError("generic metric quality filing proof is invalid")
            identity = (
                str(filing.get("ticker")),
                str(filing.get("cik")),
                str(filing.get("accession")),
            )
            parser_version = filing.get("parser_version")
            if (
                identity in identities
                or identity[:2] not in {(row["ticker"], row["cik"]) for row in companies}
                or parser_version not in KNOWN_PARSER_PROFILES
                or filing.get("parser_profile") != KNOWN_PARSER_PROFILES[parser_version]
                or any(
                    _SHA256.fullmatch(str(filing.get(field))) is None
                    for field in (
                        "snapshot_manifest_sha256",
                        "package_sha256",
                        "primary_sha256",
                        "source_binding_manifest_sha256",
                        "plan_sha256",
                        "intake_sha256",
                    )
                )
                or _COMMIT.fullmatch(str(filing.get("collector_source_commit_sha"))) is None
                or filing.get("source_binding_publication_id")
                != source_binding["publication_id"]
                or filing.get("source_binding_manifest_sha256")
                != source_binding["manifest_sha256"]
            ):
                raise ValueError("generic metric quality filing proof is invalid")
            identities.add(identity)
            used_profiles.add(str(parser_version))
        expected_profiles = [
            {"parser_version": version, **KNOWN_PARSER_PROFILES[version]}
            for version in sorted(used_profiles)
        ]
        if self.manifest.get("parser_profiles") != expected_profiles:
            raise ValueError("generic metric quality parser profiles are invalid")
        evidence = self.manifest.get("evidence_hashes")
        expected_evidence = {
            "config",
            "collection_manifest",
            "collection_request",
            "source_binding_manifest",
            "source_binding_documents",
            "source_binding_records",
            "duration_source_index",
            "correction_source_index",
            "history_manifests",
            "collection_build_manifests",
        }
        if not isinstance(evidence, dict) or set(evidence) != expected_evidence:
            raise ValueError("generic metric quality evidence proof is invalid")
        _validate_evidence_declarations(evidence, expected_tickers=set(histories))
        report = _read_json(self.root / REPORT_NAME)
        report_filings = report.get("filings")
        expected_report_scope = sorted(
            (
                str(row["ticker"]),
                str(row["cik"]),
                str(row["accession"]),
                str(row["parser_version"]),
            )
            for row in filings
        )
        actual_report_scope = sorted(
            (
                str(row.get("ticker")),
                str(row.get("cik")),
                str(row.get("accession")),
                str(row.get("parser_version")),
            )
            for row in report_filings
            if isinstance(row, dict)
        ) if isinstance(report_filings, list) else []
        if (
            report.get("schema_version") != "raw-transform-conformance-report-v1"
            or report.get("state") != "PASS"
            or report.get("assurance_scope") != ASSURANCE_SCOPE
            or report.get("full_financial_semantic_assurance") is not False
            or report.get("filing_count") != len(filings)
            or report.get("missing_source_records") != 0
            or report.get("normalized_value_mismatches") != 0
            or not isinstance(report_filings, list)
            or len(report_filings) != len(filings)
            or actual_report_scope != expected_report_scope
            or any(
                not isinstance(row, dict)
                or row.get("status") != "PASS"
                or row.get("missing_source_records") != 0
                or row.get("normalized_value_mismatches") != 0
                or type(row.get("duration_fact_count")) is not int
                or row["duration_fact_count"] < 0
                or type(row.get("approved_lexical_repair_count")) is not int
                or row["approved_lexical_repair_count"] < 0
                for row in report_filings
            )
            or report.get("duration_fact_count")
            != sum(row["duration_fact_count"] for row in report_filings)
            or report.get("approved_lexical_repair_count")
            != sum(row["approved_lexical_repair_count"] for row in report_filings)
            or report.get("mismatches") != []
        ):
            raise ValueError("generic metric quality conformance report is invalid")

    def verify_sources(
        self,
        *,
        collection_manifest: Path,
        history_manifest_sha256s: dict[str, str],
        financial_as_of: str,
        expected_companies: tuple[dict[str, str], ...],
    ) -> dict[str, Any]:
        """Reopen the exact parent collection, histories, source bytes, and Raw."""
        collection_manifest = _regular_file(collection_manifest, "collection manifest")
        companies = _company_scope(list(expected_companies), "expected quality")
        if (
            list(companies) != self.manifest.get("companies")
            or financial_as_of != self.manifest.get("financial_as_of")
            or _sha256(collection_manifest)
            != self.manifest.get("collection_manifest_sha256")
            or history_manifest_sha256s != self.manifest.get("history_manifest_sha256s")
        ):
            raise ValueError("generic metric quality requested source scope differs")
        evidence = self.manifest.get("evidence_hashes")
        if not isinstance(evidence, dict):
            raise TypeError("generic metric quality evidence declaration is invalid")
        _verify_evidence_files(evidence)
        collection = _read_json(collection_manifest)
        request_path = _regular_file(Path(str(collection.get("request_path"))), "collection request")
        request = _read_json(request_path)
        parent = _company_scope(request.get("companies"), "parent collection")
        if (
            request.get("as_of_date") != financial_as_of
            or list(parent) != self.manifest.get("parent_collection_companies")
            or _sha256(request_path) != self.manifest.get("collection_request_sha256")
        ):
            raise ValueError("generic metric quality parent collection differs")
        readiness = _validate_status(
            collection_manifest=collection_manifest,
            parent_companies=parent,
            expected_companies=companies,
        )
        if list(readiness) != self.manifest.get("collection_status"):
            raise ValueError("generic metric quality collection status replay differs")
        config_declaration = evidence.get("config")
        history_declarations = evidence.get("history_manifests")
        if not isinstance(config_declaration, dict) or not isinstance(
            history_declarations, dict
        ):
            raise TypeError("generic metric quality history evidence is invalid")
        config = _load_config(Path(str(config_declaration.get("path"))))
        if (
            config["financial_as_of"] != financial_as_of
            or config["collection_scope_companies"] != list(companies)
        ):
            raise ValueError("generic metric quality config replay differs")
        provenance = {
            (row["ticker"], row["cik"]): row for row in config["source_provenance"]
        }
        for filing in self.manifest["filings"]:
            declared = provenance[(str(filing["ticker"]), str(filing["cik"]))]
            if any(
                filing.get(field) != declared[field]
                for field in (
                    "collector_source_commit_sha",
                    "plan_sha256",
                    "intake_sha256",
                )
            ):
                raise ValueError("generic metric quality declared provenance replay differs")
        _validate_source_provenance(
            collection_manifest=collection_manifest,
            collection=collection,
            expected_companies=companies,
            provenance=provenance,
        )
        histories = _validate_histories(
            history_manifests={
                ticker: Path(str(declaration.get("path")))
                for ticker, declaration in history_declarations.items()
                if isinstance(declaration, dict)
            },
            expected_companies=companies,
            provenance=provenance,
            financial_as_of=financial_as_of,
            readiness=readiness,
        )
        if histories != history_declarations:
            raise ValueError("generic metric quality history replay differs")
        source_binding = self.manifest.get("source_binding")
        if not isinstance(source_binding, dict):
            raise TypeError("generic metric quality source binding is invalid")
        reader = SourceBindingsV2Reader(
            Path(str(source_binding.get("root"))),
            manifest_sha256=str(source_binding.get("manifest_sha256")),
        )
        reader.verify_all()
        if (
            reader.publication_id != source_binding.get("publication_id")
            or reader.manifest.get("scope_companies") != list(companies)
            or reader.manifest.get("financial_as_of") != financial_as_of
        ):
            raise ValueError("generic metric quality source-binding identity differs")
        report = _conformance_report(reader)
        stored_report = _read_json(self.root / REPORT_NAME)
        if report != stored_report:
            raise ValueError("generic metric quality conformance replay differs")
        return {
            "state": "PASS",
            "publication_id": self.publication_id,
            "parser_profiles": self.manifest["parser_profiles"],
            "rule_versions": self.manifest["rule_versions"],
            "filing_count": self.manifest["filing_count"],
        }


def _conformance_report(reader: SourceBindingsV2Reader) -> dict[str, Any]:
    duration_by_filing: dict[tuple[str, str, str], int] = {}
    correction_by_filing: dict[tuple[str, str, str], int] = {}
    mismatches: list[dict[str, str]] = []
    for binding in reader.duration_bindings():
        key = (str(binding["ticker"]), str(binding["cik"]), str(binding["accession"]))
        duration_by_filing[key] = duration_by_filing.get(key, 0) + 1
        expected = _duration_expected(str(binding["transform"]), str(binding["source_lexical"]))
        if not _text_raw_matches(binding, expected):
            mismatches.append({"kind": "DURATION", "identity": ":".join((*key, str(binding["source_id"])))})
    for binding in reader.approved_transform_corrections():
        key = (str(binding["ticker"]), str(binding["cik"]), str(binding["accession"]))
        correction_by_filing[key] = correction_by_filing.get(key, 0) + 1
        expected = _approved_expected(str(binding["transform"]), str(binding["source_lexical"]))
        if not _raw_matches(binding, expected):
            mismatches.append(
                {"kind": "APPROVED_TRANSFORM_CORRECTION", "identity": ":".join((*key, str(binding["source_id"]))) }
            )
    filings = []
    for document in reader.documents:
        key = (str(document["ticker"]), str(document["cik"]), str(document["accession"]))
        filings.append(
            {
                "ticker": key[0],
                "cik": key[1],
                "accession": key[2],
                "parser_version": document["parser_version"],
                "duration_fact_count": duration_by_filing.get(key, 0),
                "approved_lexical_repair_count": correction_by_filing.get(key, 0),
                "missing_source_records": 0,
                "normalized_value_mismatches": sum(
                    row["identity"].startswith(":".join(key) + ":") for row in mismatches
                ),
                "status": "PASS" if not any(
                    row["identity"].startswith(":".join(key) + ":") for row in mismatches
                ) else "FAIL",
            }
        )
    return {
        "schema_version": "raw-transform-conformance-report-v1",
        "state": "PASS" if not mismatches else "FAIL",
        "assurance_scope": ASSURANCE_SCOPE,
        "full_financial_semantic_assurance": False,
        "filing_count": len(filings),
        "filings": filings,
        "duration_fact_count": sum(duration_by_filing.values()),
        "approved_lexical_repair_count": sum(correction_by_filing.values()),
        "missing_source_records": 0,
        "normalized_value_mismatches": len(mismatches),
        "mismatches": mismatches,
    }


def _duration_expected(transform: str, lexical: str) -> str:
    if transform == "durweek":
        return _week_duration(lexical)
    units = {"durday": "D", "durmonth": "M", "duryear": "Y"}
    if transform not in units:
        raise ValueError(f"unsupported governed duration transform: {transform}")
    return _decimal_duration(lexical, units[transform])


def _approved_expected(transform: str, lexical: str) -> str:
    expected = {
        ("exchnameen", "Nasdaq"): "NASDAQ",
        ("stateprovnameen", "Idaho"): "ID",
        ("durwordsen", "three\N{NON-BREAKING HYPHEN}year"): "P3Y",
        ("durwordsen", "five\N{NON-BREAKING HYPHEN}year"): "P5Y",
        ("numwordsen", "nil"): "0",
    }
    try:
        return expected[(transform, lexical)]
    except KeyError as exc:
        raise ValueError("unsupported approved lexical repair source") from exc


def _text_raw_matches(binding: dict[str, Any], expected: str) -> bool:
    return (
        binding.get("actual_raw_value") == expected
        and binding.get("actual_value_text") == expected
        and binding.get("actual_value_numeric") is None
        and binding.get("actual_is_nil") is False
    )


def _raw_matches(binding: dict[str, Any], expected: str) -> bool:
    if binding.get("transform") == "numwordsen":
        return (
            binding.get("actual_raw_value") == expected
            and str(binding.get("actual_value_numeric")) == expected
            and binding.get("actual_value_text") is None
            and binding.get("actual_is_nil") is False
        )
    return _text_raw_matches(binding, expected)


def _load_config(path: Path) -> dict[str, Any]:
    payload = _read_json(_regular_file(path, "generic quality config"))
    companies = _company_scope(payload.get("collection_scope_companies"), "quality config")
    provenance_rows = payload.get("source_provenance")
    if (
        payload.get("schema_version") != CONFIG_SCHEMA_VERSION
        or type(payload.get("financial_as_of")) is not str
        or not payload["financial_as_of"]
        or not isinstance(provenance_rows, list)
    ):
        raise ValueError("generic quality config is invalid")
    provenance: list[dict[str, str]] = []
    for row in provenance_rows:
        if not isinstance(row, dict):
            raise TypeError("generic quality source provenance is invalid")
        normalized = {key: str(row.get(key)) for key in (
            "ticker", "cik", "collector_source_commit_sha", "plan_sha256",
            "intake_sha256", "history_manifest_sha256",
        )}
        if (
            _COMMIT.fullmatch(normalized["collector_source_commit_sha"]) is None
            or any(
                _SHA256.fullmatch(normalized[key]) is None
                for key in ("plan_sha256", "intake_sha256", "history_manifest_sha256")
            )
        ):
            raise ValueError("generic quality source provenance is invalid")
        provenance.append(normalized)
    provenance.sort(key=lambda row: (row["ticker"], row["cik"]))
    if [(row["ticker"], row["cik"]) for row in provenance] != [
        (row["ticker"], row["cik"]) for row in companies
    ]:
        raise ValueError("generic quality provenance scope differs from companies")
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "financial_as_of": payload["financial_as_of"],
        "collection_scope_companies": list(companies),
        "source_provenance": provenance,
    }


def _validate_status(
    *,
    collection_manifest: Path,
    parent_companies: tuple[dict[str, str], ...],
    expected_companies: tuple[dict[str, str], ...],
) -> tuple[dict[str, Any], ...]:
    collection = _read_json(collection_manifest)
    declared_companies = collection.get("companies")
    if not isinstance(declared_companies, list):
        raise TypeError("collection company declarations are invalid")
    collection_index = {
        (str(item.get("ticker")), str(item.get("cik"))): item
        for item in declared_companies
        if isinstance(item, dict)
    }
    status = read_universe_status(manifest_path=collection_manifest)
    status_parent = tuple(
        sorted(
            ({"ticker": row.ticker, "cik": str(row.cik)} for row in status.companies),
            key=lambda row: (row["ticker"], row["cik"]),
        )
    )
    if status_parent != parent_companies:
        raise ValueError("collection status parent membership differs")
    status_index = {(row.ticker, str(row.cik)): row for row in status.companies}
    evidence: list[dict[str, Any]] = []
    for company in expected_companies:
        row = status_index.get((company["ticker"], company["cik"]))
        if (
            row is None
            or row.state != "READY"
            or row.selected_filings != row.held_filings
            or row.pending_filings != 0
            or row.failed_filings != 0
        ):
            raise ValueError(f"quality company is not exact READY: {company['ticker']}")
        build_manifest = _regular_file(
            collection_manifest.parent
            / "companies"
            / company["ticker"]
            / "build_manifest.json",
            "collection build manifest",
        )
        marker = _read_json(build_manifest)
        declared = collection_index.get((company["ticker"], company["cik"]))
        if declared is None:
            raise ValueError("READY company is absent from collection manifest")
        plan_path = _regular_file(Path(str(declared.get("plan_path"))), "collection plan")
        intake_path = _regular_file(
            Path(str(marker.get("intake_manifest"))), "collection intake"
        )
        history_path = _regular_file(
            Path(str(marker.get("history_manifest"))), "accepted history manifest"
        )
        if (
            marker.get("ticker") != company["ticker"]
            or marker.get("status") != "READY"
            or marker.get("plan_sha256") != _sha256(plan_path)
            or marker.get("plan_sha256") != declared.get("plan_sha256")
            or marker.get("intake_sha256") != _sha256(intake_path)
            or marker.get("history_manifest_sha256") != _sha256(history_path)
        ):
            raise ValueError("collection READY build provenance differs")
        evidence.append(
            {
                "ticker": company["ticker"],
                "cik": company["cik"],
                "state": row.state,
                "selected_filings": row.selected_filings,
                "held_filings": row.held_filings,
                "pending_filings": row.pending_filings,
                "failed_filings": row.failed_filings,
                "build_manifest_path": str(build_manifest),
                "build_manifest_sha256": _sha256(build_manifest),
                "plan_path": str(plan_path),
                "plan_sha256": str(marker["plan_sha256"]),
                "intake_manifest_path": str(intake_path),
                "intake_sha256": str(marker["intake_sha256"]),
                "history_manifest_path": str(history_path),
                "history_manifest_sha256": str(marker["history_manifest_sha256"]),
            }
        )
    return tuple(evidence)


def _validate_source_provenance(
    *,
    collection_manifest: Path,
    collection: dict[str, Any],
    expected_companies: tuple[dict[str, str], ...],
    provenance: dict[tuple[str, str], dict[str, str]],
) -> None:
    companies = collection.get("companies")
    if not isinstance(companies, list):
        raise TypeError("collection company source declarations are invalid")
    collection_index = {
        (str(row.get("ticker")), str(row.get("cik"))): row
        for row in companies if isinstance(row, dict)
    }
    for company in expected_companies:
        key = (company["ticker"], company["cik"])
        source = collection_index.get(key)
        declared = provenance[key]
        if source is None or source.get("plan_sha256") != declared["plan_sha256"]:
            raise ValueError("quality plan provenance differs from collection")
        intake = _regular_file(
            collection_manifest.parent / "companies" / key[0] / "intake" / "history_intake.json",
            "collection intake",
        )
        if _sha256(intake) != declared["intake_sha256"]:
            raise ValueError("quality intake provenance differs from collection")


def _validate_histories(
    *,
    history_manifests: dict[str, Path],
    expected_companies: tuple[dict[str, str], ...],
    provenance: dict[tuple[str, str], dict[str, str]],
    financial_as_of: str,
    readiness: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, str]]:
    expected_tickers = {row["ticker"] for row in expected_companies}
    if set(history_manifests) != expected_tickers:
        raise ValueError("accepted history manifests differ from quality scope")
    readiness_index = {row["ticker"]: row for row in readiness}
    result: dict[str, dict[str, str]] = {}
    for company in expected_companies:
        ticker, cik = company["ticker"], company["cik"]
        path = _regular_file(history_manifests[ticker], "accepted history manifest")
        digest = _sha256(path)
        ready = readiness_index.get(ticker)
        if (
            ready is None
            or path != Path(str(ready["history_manifest_path"]))
            or digest != provenance[(ticker, cik)]["history_manifest_sha256"]
            or digest != ready["history_manifest_sha256"]
        ):
            raise ValueError("accepted history manifest differs from READY build")
        HistoryPublicationReader(path.parent).verify_all()
        payload = _read_json(path)
        plan = payload.get("plan")
        plan_companies = plan.get("companies") if isinstance(plan, dict) else None
        plan_path = _regular_file(Path(str(ready["plan_path"])), "collection plan")
        intake_path = _regular_file(
            Path(str(ready["intake_manifest_path"])), "collection intake"
        )
        expected_plan = _read_json(plan_path)
        intake = _read_json(intake_path)
        if (
            payload.get("version") != HISTORY_VERSION
            or plan != expected_plan
            or not isinstance(plan_companies, list)
            or len(plan_companies) != 1
            or plan_companies[0].get("ticker") != ticker
            or str(plan_companies[0].get("cik")) != cik
            or plan.get("as_of_date") != financial_as_of
            or payload.get("source_intake") != str(intake_path)
            or intake.get("complete") is not True
            or intake.get("plan") != expected_plan
            or _sha256(plan_path) != provenance[(ticker, cik)]["plan_sha256"]
            or _sha256(intake_path) != provenance[(ticker, cik)]["intake_sha256"]
            or _sha256(plan_path) != ready["plan_sha256"]
            or _sha256(intake_path) != ready["intake_sha256"]
        ):
            raise ValueError("accepted history plan/intake contract differs")
        result[ticker] = {"path": str(path), "sha256": digest}
    return dict(sorted(result.items()))


def _company_scope(value: Any, label: str) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} company scope must be a non-empty list")
    rows = tuple(
        sorted(
            ({"ticker": str(row.get("ticker")), "cik": str(row.get("cik"))} for row in value if isinstance(row, dict)),
            key=lambda row: (row["ticker"], row["cik"]),
        )
    )
    identities = {(row["ticker"], row["cik"]) for row in rows}
    if len(rows) != len(value) or len(identities) != len(rows):
        raise ValueError(f"{label} company scope is duplicated or malformed")
    if any(not row["ticker"] or re.fullmatch(r"[0-9]{10}", row["cik"]) is None for row in rows):
        raise ValueError(f"{label} company identity is invalid")
    return rows


def _verify_evidence_files(value: dict[str, Any]) -> None:
    for label, declaration in value.items():
        if label in {"history_manifests", "collection_build_manifests"}:
            if not isinstance(declaration, dict):
                raise TypeError("history evidence declaration is invalid")
            for ticker, nested in declaration.items():
                _verify_external_declaration(nested, f"{label} {ticker}")
        else:
            _verify_external_declaration(declaration, label)


def _validate_evidence_declarations(
    value: dict[str, Any], *, expected_tickers: set[str]
) -> None:
    histories = value.get("history_manifests")
    builds = value.get("collection_build_manifests")
    if (
        not isinstance(histories, dict)
        or set(histories) != expected_tickers
        or not isinstance(builds, dict)
        or set(builds) != expected_tickers
    ):
        raise ValueError("scoped company evidence proof is invalid")
    declarations = [
        declaration
        for label, declaration in value.items()
        if label not in {"history_manifests", "collection_build_manifests"}
    ] + list(histories.values()) + list(builds.values())
    for declaration in declarations:
        if (
            not isinstance(declaration, dict)
            or type(declaration.get("path")) is not str
            or not Path(declaration["path"]).is_absolute()
            or _SHA256.fullmatch(str(declaration.get("sha256"))) is None
        ):
            raise ValueError("generic metric quality evidence proof is invalid")


def _verify_external_declaration(value: Any, label: str) -> None:
    if not isinstance(value, dict) or type(value.get("path")) is not str:
        raise ValueError(f"{label} evidence declaration is invalid")
    path = _regular_file(Path(value["path"]), label)
    if value.get("sha256") != _sha256(path):
        raise ValueError(f"{label} evidence digest changed")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
    return path


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _json_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = path.absolute()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path


def _real_directory(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = path.absolute()
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"{label} is not a real directory: {path}")
    return path


def _new_destination(path: Path, label: str) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{label} destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError(f"{label} destination parent cannot use symlinks")
    return path


def _file_declaration(path: Path) -> dict[str, Any]:
    return {"sha256": _sha256(path), "size": path.stat().st_size}


def _verify_file_declaration(path: Path, declaration: Any, label: str) -> None:
    path = _regular_file(path, label)
    if (
        not isinstance(declaration, dict)
        or declaration.get("sha256") != _sha256(path)
        or declaration.get("size") != path.stat().st_size
    ):
        raise ValueError(f"generic metric quality file integrity mismatch: {label}")


def _history_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        ticker, separator, path = value.partition("=")
        if not separator or not ticker or ticker in result:
            raise ValueError("history manifest arguments must be unique TICKER=PATH values")
        result[ticker] = Path(path)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare generic metric Raw quality")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--collection-manifest", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--history-manifest", action="append", default=[])
    parser.add_argument("--source-index-destination", type=Path, required=True)
    parser.add_argument("--source-binding-destination", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--producer-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    publication = prepare_generic_metric_quality(
        config_path=args.config,
        collection_manifest=args.collection_manifest,
        package_root=args.package_root,
        history_manifests=_history_args(args.history_manifest),
        source_index_destination=args.source_index_destination,
        source_binding_destination=args.source_binding_destination,
        destination=args.destination,
        producer_revision=args.producer_revision,
    )
    print(publication.manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
