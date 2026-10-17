"""Governed Raw/Quality bindings between cached Inline XBRL and Layer 1.

The producer is an offline preparation step.  It reads immutable accession
packages, extracts the narrow source fields needed by the SEC transform
conformance assessment, and binds them to already materialized Layer 1 rows.
The reader deliberately does not parse Inline XBRL.  It verifies the governed
publication, the cached bytes, the collection scope, and the Layer 1 table
identities consumed by downstream completion reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl
from lxml import html as lxml_html

from sec_xbrl.facts.layer1 import _stable_id

VERSION = "sec-source-bindings-v1"
VERSION_V2 = "sec-source-bindings-v2"
MANIFEST_NAME = "source_binding_manifest.json"
DOCUMENTS_NAME = "source_documents.json"
BINDINGS_NAME = "source_bindings.json"
PARSER_VERSION = "m2-layer1-v5"
KNOWN_PARSER_PROFILES: dict[str, dict[str, str]] = {
    "m2-layer1-v5": {
        "profile": "sec-inline-duration-and-approved-lexical-v1",
        "parser_source_commit": "c1fdc21a267545c3c67ad4bdce8c74137ee340e1",
        "transform_rule_version": "sec-duration-conformance-v1",
    },
    "m2-layer1-v6": {
        "profile": "sec-inline-duration-approved-lexical-and-metadata-v1",
        "parser_source_commit": "4077e87097c294ed779186b613157839f215a63e",
        "transform_rule_version": "sec-duration-conformance-v1",
    },
}
SEC_TRANSFORM_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"

_DURATION_TRANSFORMS = frozenset({"durday", "durmonth", "duryear", "durweek"})
_SAFE_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.^-]{0,31}$")
_SAFE_CIK = re.compile(r"^[0-9]{10}$")
_SAFE_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_XMLNS = re.compile(r"xmlns:([^\s=]+)\s*=\s*([\"'])(.*?)\2")


@dataclass(frozen=True, slots=True)
class SourceBindingPublication:
    """Paths and identity for one immutable Raw/Quality publication."""

    root: Path
    publication_id: str
    manifest_path: Path
    documents_path: Path
    bindings_path: Path


@dataclass(frozen=True, slots=True)
class SourceIndexPublication:
    """Candidate indexes created from cached packages and Raw snapshots."""

    root: Path
    duration_path: Path
    correction_path: Path


@dataclass(frozen=True, slots=True)
class _FilingScope:
    ticker: str
    cik: str
    accession: str
    primary_document: str
    snapshot_root: Path
    snapshot_manifest: Path


def publish_source_bindings(
    *,
    collection_manifest: Path,
    package_root: Path,
    duration_source_index: Path,
    correction_source_index: Path,
    destination: Path,
    producer_revision: str,
) -> SourceBindingPublication:
    """Build and atomically publish source-to-Raw bindings without network I/O.

    Candidate JSON files are treated as claims.  The producer independently
    scans every planned primary document and refuses omissions, additions, or
    changed source fields before binding a claim to a v5 Fact row.
    """
    if _COMMIT.fullmatch(producer_revision) is None:
        raise ValueError("producer_revision must be a 40-character commit SHA")
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    package_root = _real_directory(package_root, "package root")
    duration_source_index = _regular_file(
        duration_source_index, "duration source index"
    )
    correction_source_index = _regular_file(
        correction_source_index, "supported lexical correction source index"
    )
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"source-binding destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise ValueError("source-binding destination parent cannot be a symlink")

    collection, request, scope = _load_collection_scope(collection_manifest)
    duration_claims, duration_documents = _load_duration_claims(
        duration_source_index, scope
    )
    correction_claims = _load_correction_claims(correction_source_index, scope)

    documents: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    observed_duration: set[tuple[str, str, str, str]] = set()
    observed_corrections: set[tuple[str, str, str, str]] = set()
    for filing in scope:
        package_path = _package_path(package_root, filing.cik, filing.accession)
        package_sha256 = _sha256(package_path)
        snapshot_manifest_payload = _read_json(filing.snapshot_manifest)
        if (
            snapshot_manifest_payload.get("cik") != filing.cik
            or snapshot_manifest_payload.get("accession") != filing.accession
            or snapshot_manifest_payload.get("layer1_parser_version") != PARSER_VERSION
            or snapshot_manifest_payload.get("package_sha256") != package_sha256
        ):
            raise ValueError(
                f"v5 snapshot/package identity differs for {filing.accession}"
            )
        primary = _read_primary_member(package_path, filing.primary_document)
        primary_sha256 = _sha256_bytes(primary)
        declared_primary = duration_documents[(
            filing.ticker,
            filing.cik,
            filing.accession,
        )]
        if declared_primary != primary_sha256:
            raise ValueError(
                f"duration source index primary hash differs for {filing.accession}"
            )

        fact_path = _regular_file(filing.snapshot_root / "fact.parquet", "v5 Fact table")
        concept_path = _regular_file(
            filing.snapshot_root / "concept.parquet", "v5 Concept table"
        )
        context_path = _regular_file(
            filing.snapshot_root / "context.parquet", "v5 Context table"
        )
        facts = pl.read_parquet(fact_path).with_row_index("_source_ordinal").to_dicts()
        concepts = pl.read_parquet(concept_path).to_dicts()
        contexts = pl.read_parquet(context_path).to_dicts()
        fact_index = _unique_index(facts, "fact_id", "v5 Fact")
        concept_index = _unique_index(concepts, "raw_concept_id", "v5 Concept")
        context_index = _unique_index(contexts, "context_id", "v5 Context")

        source_rows = _extract_source_rows(primary, filing)
        filing_key = (filing.ticker, filing.cik, filing.accession)
        duration_rows = {
            key: row
            for key, row in source_rows.items()
            if row["transform"] in _DURATION_TRANSFORMS
        }
        correction_rows = {
            key: row
            for key, row in source_rows.items()
            if _is_supported_correction_source(row)
        }
        expected_duration = {
            key: value
            for key, value in duration_claims.items()
            if key[:3] == filing_key
        }
        expected_corrections = {
            key: value
            for key, value in correction_claims.items()
            if key[:3] == filing_key
        }
        if set(duration_rows) != set(expected_duration):
            raise ValueError(
                f"duration source index differs from primary document: {filing.accession}"
            )
        if set(correction_rows) != set(expected_corrections):
            raise ValueError(
                "supported lexical correction index differs from primary document: "
                f"{filing.accession}"
            )

        for key, source in sorted(duration_rows.items()):
            claim = expected_duration[key]
            _compare_source_claim(source, claim, correction=False)
            bindings.append(
                _bind_source_row(
                    filing=filing,
                    kind="DURATION",
                    source=source,
                    claim=claim,
                    package_sha256=package_sha256,
                    primary_sha256=primary_sha256,
                    facts=fact_index,
                    concepts=concept_index,
                    contexts=context_index,
                )
            )
            observed_duration.add(key)
        for key, source in sorted(correction_rows.items()):
            claim = expected_corrections[key]
            _compare_source_claim(source, claim, correction=True)
            bindings.append(
                _bind_source_row(
                    filing=filing,
                    kind="APPROVED_TRANSFORM_CORRECTION",
                    source=source,
                    claim=claim,
                    package_sha256=package_sha256,
                    primary_sha256=primary_sha256,
                    facts=fact_index,
                    concepts=concept_index,
                    contexts=context_index,
                )
            )
            observed_corrections.add(key)

        documents.append(
            {
                "ticker": filing.ticker,
                "cik": filing.cik,
                "accession": filing.accession,
                "primary_document": filing.primary_document,
                "package_path": str(package_path),
                "package_sha256": package_sha256,
                "primary_sha256": primary_sha256,
                "snapshot_root": str(filing.snapshot_root),
                "snapshot_manifest_path": str(filing.snapshot_manifest),
                "snapshot_manifest_sha256": _sha256(filing.snapshot_manifest),
                "parser_version": PARSER_VERSION,
                "tables": {
                    "fact.parquet": _file_declaration(fact_path),
                    "concept.parquet": _file_declaration(concept_path),
                    "context.parquet": _file_declaration(context_path),
                },
            }
        )

    if observed_duration != set(duration_claims):
        raise ValueError("duration source index was not completely bound")
    if observed_corrections != set(correction_claims):
        raise ValueError("supported lexical correction index was not completely bound")

    documents.sort(key=lambda row: (row["ticker"], row["accession"]))
    bindings.sort(
        key=lambda row: (
            row["ticker"],
            row["accession"],
            row["binding_kind"],
            row["source_id"],
        )
    )
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        documents_path = _write_json(
            staging / DOCUMENTS_NAME,
            {
                "version": VERSION,
                "document_count": len(documents),
                "documents": documents,
            },
        )
        bindings_path = _write_json(
            staging / BINDINGS_NAME,
            {
                "version": VERSION,
                "binding_count": len(bindings),
                "bindings": bindings,
            },
        )
        manifest: dict[str, Any] = {
            "version": VERSION,
            "producer_revision": producer_revision,
            "parser_version": PARSER_VERSION,
            "universe_id": request["universe_id"],
            "financial_as_of": request["as_of_date"],
            "collection": {
                "manifest_path": str(collection_manifest),
                "manifest_sha256": _sha256(collection_manifest),
                "request_path": str(Path(collection["request_path"])),
                "request_sha256": collection["request_sha256"],
            },
            "package_root": str(package_root),
            "candidate_inputs": {
                "duration_source_index": {
                    "path": str(duration_source_index),
                    "sha256": _sha256(duration_source_index),
                },
                "correction_source_index": {
                    "path": str(correction_source_index),
                    "sha256": _sha256(correction_source_index),
                },
            },
            "counts": {
                "companies": len({row["cik"] for row in documents}),
                "filings": len(documents),
                "duration_bindings": sum(
                    row["binding_kind"] == "DURATION" for row in bindings
                ),
                "approved_transform_corrections": sum(
                    row["binding_kind"] == "APPROVED_TRANSFORM_CORRECTION"
                    for row in bindings
                ),
            },
            "files": {
                DOCUMENTS_NAME: _file_declaration(documents_path),
                BINDINGS_NAME: _file_declaration(bindings_path),
            },
        }
        manifest["publication_id"] = "source-bindings-" + hashlib.sha256(
            _json(manifest).encode("utf-8")
        ).hexdigest()[:24]
        _write_json(staging / MANIFEST_NAME, manifest)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return SourceBindingPublication(
        root=destination,
        publication_id=str(manifest["publication_id"]),
        manifest_path=destination / MANIFEST_NAME,
        documents_path=destination / DOCUMENTS_NAME,
        bindings_path=destination / BINDINGS_NAME,
    )


def write_source_indexes_v2(
    *,
    collection_manifest: Path,
    package_root: Path,
    destination: Path,
    collection_scope_companies: tuple[dict[str, str], ...] | None = None,
) -> SourceIndexPublication:
    """Create complete candidate indexes from cached source and mixed v5/v6 Raw.

    These indexes are conveniences, not trust roots. ``publish_source_bindings_v2``
    independently reopens and rescans every planned primary document before it
    accepts any candidate record.
    """
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    package_root = _real_directory(package_root, "package root")
    destination = _new_destination(destination, "source-index")
    _, request, all_scope = _load_collection_scope(collection_manifest)
    scope, _, _ = _select_collection_scope(
        all_scope, request=request, requested=collection_scope_companies
    )
    documents: list[dict[str, Any]] = []
    duration_facts: list[dict[str, Any]] = []
    correction_facts: list[dict[str, Any]] = []
    format_counts = {name: 0 for name in sorted(_DURATION_TRANSFORMS)}
    for filing in scope:
        package_path = _package_path(package_root, filing.cik, filing.accession)
        package_sha256 = _sha256(package_path)
        snapshot_manifest = _read_json(filing.snapshot_manifest)
        parser_version = _known_parser_version(snapshot_manifest, filing, package_sha256)
        primary = _read_primary_member(package_path, filing.primary_document)
        primary_sha256 = _sha256_bytes(primary)
        facts = pl.read_parquet(
            _regular_file(filing.snapshot_root / "fact.parquet", "Raw Fact table")
        ).with_row_index("_source_ordinal").to_dicts()
        concepts = _unique_index(
            pl.read_parquet(
                _regular_file(filing.snapshot_root / "concept.parquet", "Raw Concept table")
            ).to_dicts(),
            "raw_concept_id",
            "Raw Concept",
        )
        contexts = _unique_index(
            pl.read_parquet(
                _regular_file(filing.snapshot_root / "context.parquet", "Raw Context table")
            ).to_dicts(),
            "context_id",
            "Raw Context",
        )
        source_rows = _extract_source_rows(primary, filing)
        documents.append(
            {
                "ticker": filing.ticker,
                "cik": filing.cik,
                "accession": filing.accession,
                "primary_document": filing.primary_document,
                "primary_sha256": primary_sha256,
                "package_sha256": package_sha256,
                "parser_version": parser_version,
            }
        )
        for source in source_rows.values():
            if source["transform"] not in _DURATION_TRANSFORMS and not _is_supported_correction_source(source):
                continue
            fact_id = _source_fact_id(source, filing=filing, facts=facts)
            fact = _unique_index(facts, "fact_id", "Raw Fact")[fact_id]
            concept = concepts.get(str(fact.get("raw_concept_id")))
            context_id = str(fact.get("context_id"))
            if concept is None or context_id not in contexts:
                raise ValueError("source index cannot bind source to complete Raw identity")
            common = {
                "ticker": filing.ticker,
                "cik": filing.cik,
                "accession": filing.accession,
                "primary_document": filing.primary_document,
                "source_id": source["source_id"],
                "source_lexical": source["source_lexical"],
                "format_qname": source["format_qname"],
                "format_namespace": source["format_namespace"],
                "concept_qname": source["concept_qname"],
                "fact_id": fact_id,
            }
            if source["transform"] in _DURATION_TRANSFORMS:
                duration_facts.append(
                    {
                        **common,
                        "format": source["transform"],
                        "namespace": source["format_namespace"],
                        "context_ref": source["source_context_ref"],
                    }
                )
                format_counts[source["transform"]] += 1
            if _is_supported_correction_source(source):
                correction_facts.append(
                    {
                        **common,
                        "source_locator": source["source_locator"],
                        "source_element_type": source["source_element_type"],
                        "source_scale": source["source_scale"],
                        "source_sign": source["source_sign"],
                        "concept_data_type_qname": concept.get("data_type"),
                        "primary_sha256": primary_sha256,
                        "filing_id": fact.get("filing_id")
                        or _stable_id("filing", filing.cik, filing.accession),
                        "context_id": context_id,
                        "raw_concept_id": fact.get("raw_concept_id"),
                    }
                )
    documents.sort(key=lambda row: (row["ticker"], row["accession"]))
    duration_facts.sort(key=lambda row: (row["ticker"], row["accession"], row["source_id"]))
    correction_facts.sort(key=lambda row: (row["ticker"], row["accession"], row["source_id"]))
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        duration_path = _write_json(
            staging / "duration_source_index.json",
            {
                "schema_version": "sec-duration-source-index-v2",
                "primary_document_count": len(documents),
                "missing_primary_documents": 0,
                "format_counts": format_counts,
                "primary_documents": documents,
                "duration_facts": duration_facts,
            },
        )
        correction_path = _write_json(
            staging / "correction_source_index.json",
            {
                "schema_version": "sec-approved-lexical-source-index-v2",
                "fact_count": len(correction_facts),
                "unmatched": [],
                "facts": correction_facts,
            },
        )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return SourceIndexPublication(
        root=destination,
        duration_path=destination / duration_path.name,
        correction_path=destination / correction_path.name,
    )


def publish_source_bindings_v2(
    *,
    collection_manifest: Path,
    package_root: Path,
    duration_source_index: Path,
    correction_source_index: Path,
    destination: Path,
    producer_revision: str,
    collection_scope_companies: tuple[dict[str, str], ...] | None = None,
) -> SourceBindingPublication:
    """Publish exact mixed-v5/v6 bindings under a distinct public contract."""
    if _COMMIT.fullmatch(producer_revision) is None:
        raise ValueError("producer_revision must be a 40-character commit SHA")
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    package_root = _real_directory(package_root, "package root")
    duration_source_index = _regular_file(duration_source_index, "duration source index")
    correction_source_index = _regular_file(
        correction_source_index, "supported lexical correction source index"
    )
    destination = _new_destination(destination, "source-binding v2")

    collection, request, all_scope = _load_collection_scope(collection_manifest)
    scope, parent_companies, scope_companies = _select_collection_scope(
        all_scope, request=request, requested=collection_scope_companies
    )
    duration_claims, duration_documents = _load_duration_claims(duration_source_index, scope)
    correction_claims = _load_correction_claims(correction_source_index, scope)
    documents: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    observed_duration: set[tuple[str, str, str, str]] = set()
    observed_corrections: set[tuple[str, str, str, str]] = set()
    used_profiles: set[str] = set()
    for filing in scope:
        package_path = _package_path(package_root, filing.cik, filing.accession)
        package_sha256 = _sha256(package_path)
        snapshot_manifest_payload = _read_json(filing.snapshot_manifest)
        parser_version = _known_parser_version(snapshot_manifest_payload, filing, package_sha256)
        used_profiles.add(parser_version)
        primary = _read_primary_member(package_path, filing.primary_document)
        primary_sha256 = _sha256_bytes(primary)
        filing_key = (filing.ticker, filing.cik, filing.accession)
        if duration_documents[filing_key] != primary_sha256:
            raise ValueError(f"duration source index primary hash differs for {filing.accession}")
        fact_path = _regular_file(filing.snapshot_root / "fact.parquet", "Raw Fact table")
        concept_path = _regular_file(filing.snapshot_root / "concept.parquet", "Raw Concept table")
        context_path = _regular_file(filing.snapshot_root / "context.parquet", "Raw Context table")
        facts = pl.read_parquet(fact_path).with_row_index("_source_ordinal").to_dicts()
        concepts = pl.read_parquet(concept_path).to_dicts()
        contexts = pl.read_parquet(context_path).to_dicts()
        fact_index = _unique_index(facts, "fact_id", "Raw Fact")
        concept_index = _unique_index(concepts, "raw_concept_id", "Raw Concept")
        context_index = _unique_index(contexts, "context_id", "Raw Context")
        source_rows = _extract_source_rows(primary, filing)
        duration_rows = {
            key: row for key, row in source_rows.items() if row["transform"] in _DURATION_TRANSFORMS
        }
        correction_rows = {
            key: row for key, row in source_rows.items() if _is_supported_correction_source(row)
        }
        expected_duration = {key: value for key, value in duration_claims.items() if key[:3] == filing_key}
        expected_corrections = {key: value for key, value in correction_claims.items() if key[:3] == filing_key}
        if set(duration_rows) != set(expected_duration):
            raise ValueError(f"duration source index differs from primary document: {filing.accession}")
        if set(correction_rows) != set(expected_corrections):
            raise ValueError(
                "supported lexical correction index differs from primary document: "
                f"{filing.accession}"
            )
        for key, source in sorted(duration_rows.items()):
            claim = expected_duration[key]
            _compare_source_claim(source, claim, correction=False)
            bindings.append(
                _bind_source_row(
                    filing=filing,
                    kind="DURATION",
                    source=source,
                    claim=claim,
                    package_sha256=package_sha256,
                    primary_sha256=primary_sha256,
                    facts=fact_index,
                    concepts=concept_index,
                    contexts=context_index,
                )
            )
            observed_duration.add(key)
        for key, source in sorted(correction_rows.items()):
            claim = expected_corrections[key]
            _compare_source_claim(source, claim, correction=True)
            bindings.append(
                _bind_source_row(
                    filing=filing,
                    kind="APPROVED_TRANSFORM_CORRECTION",
                    source=source,
                    claim=claim,
                    package_sha256=package_sha256,
                    primary_sha256=primary_sha256,
                    facts=fact_index,
                    concepts=concept_index,
                    contexts=context_index,
                )
            )
            observed_corrections.add(key)
        documents.append(
            {
                "ticker": filing.ticker,
                "cik": filing.cik,
                "accession": filing.accession,
                "primary_document": filing.primary_document,
                "package_path": str(package_path),
                "package_sha256": package_sha256,
                "primary_sha256": primary_sha256,
                "snapshot_root": str(filing.snapshot_root),
                "snapshot_manifest_path": str(filing.snapshot_manifest),
                "snapshot_manifest_sha256": _sha256(filing.snapshot_manifest),
                "parser_version": parser_version,
                "parser_profile": dict(KNOWN_PARSER_PROFILES[parser_version]),
                "tables": {
                    "fact.parquet": _file_declaration(fact_path),
                    "concept.parquet": _file_declaration(concept_path),
                    "context.parquet": _file_declaration(context_path),
                },
            }
        )
    if observed_duration != set(duration_claims):
        raise ValueError("duration source index was not completely bound")
    if observed_corrections != set(correction_claims):
        raise ValueError("supported lexical correction index was not completely bound")
    documents.sort(key=lambda row: (row["ticker"], row["accession"]))
    bindings.sort(key=lambda row: (row["ticker"], row["accession"], row["binding_kind"], row["source_id"]))
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        documents_path = _write_json(
            staging / DOCUMENTS_NAME,
            {"version": VERSION_V2, "document_count": len(documents), "documents": documents},
        )
        bindings_path = _write_json(
            staging / BINDINGS_NAME,
            {"version": VERSION_V2, "binding_count": len(bindings), "bindings": bindings},
        )
        manifest: dict[str, Any] = {
            "version": VERSION_V2,
            "producer_revision": producer_revision,
            "parser_profiles": [
                {"parser_version": version, **KNOWN_PARSER_PROFILES[version]}
                for version in sorted(used_profiles)
            ],
            "universe_id": request["universe_id"],
            "financial_as_of": request["as_of_date"],
            "collection_scope_mode": (
                "FULL" if scope_companies == parent_companies else "EXPLICIT_SUBSET"
            ),
            "parent_collection_companies": list(parent_companies),
            "scope_companies": list(scope_companies),
            "collection": {
                "manifest_path": str(collection_manifest),
                "manifest_sha256": _sha256(collection_manifest),
                "request_path": str(Path(collection["request_path"])),
                "request_sha256": collection["request_sha256"],
            },
            "package_root": str(package_root),
            "candidate_inputs": {
                "duration_source_index": {"path": str(duration_source_index), "sha256": _sha256(duration_source_index)},
                "correction_source_index": {"path": str(correction_source_index), "sha256": _sha256(correction_source_index)},
            },
            "counts": {
                "companies": len({row["cik"] for row in documents}),
                "filings": len(documents),
                "duration_bindings": sum(row["binding_kind"] == "DURATION" for row in bindings),
                "approved_transform_corrections": sum(
                    row["binding_kind"] == "APPROVED_TRANSFORM_CORRECTION" for row in bindings
                ),
            },
            "files": {
                DOCUMENTS_NAME: _file_declaration(documents_path),
                BINDINGS_NAME: _file_declaration(bindings_path),
            },
        }
        manifest["publication_id"] = "source-bindings-v2-" + hashlib.sha256(
            _json(manifest).encode("utf-8")
        ).hexdigest()[:24]
        _write_json(staging / MANIFEST_NAME, manifest)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return SourceBindingPublication(
        root=destination,
        publication_id=str(manifest["publication_id"]),
        manifest_path=destination / MANIFEST_NAME,
        documents_path=destination / DOCUMENTS_NAME,
        bindings_path=destination / BINDINGS_NAME,
    )


class SourceBindingsReader:
    """Verify prepared source bindings without parsing Inline XBRL."""

    def __init__(self, root: Path) -> None:
        self.root = _real_directory(root, "source-binding publication")
        children = tuple(self.root.iterdir())
        expected = {MANIFEST_NAME, DOCUMENTS_NAME, BINDINGS_NAME}
        if {path.name for path in children} != expected or any(
            path.is_symlink() or not path.is_file() for path in children
        ):
            raise ValueError("source-binding publication file set is invalid")
        self.manifest_path = self.root / MANIFEST_NAME
        self.manifest = _read_json(self.manifest_path)
        if self.manifest.get("version") != VERSION:
            raise ValueError("unsupported source-binding publication")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or set(files) != {DOCUMENTS_NAME, BINDINGS_NAME}:
            raise ValueError("source-binding file manifest is invalid")
        for name, declaration in files.items():
            _verify_file_declaration(self.root / name, declaration, name)
        identity = {
            key: value for key, value in self.manifest.items() if key != "publication_id"
        }
        publication_id = "source-bindings-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        if self.manifest.get("publication_id") != publication_id:
            raise ValueError("source-binding publication identity mismatch")
        if _COMMIT.fullmatch(str(self.manifest.get("producer_revision"))) is None:
            raise ValueError("source-binding producer revision is invalid")
        self.publication_id = publication_id
        documents_payload = _read_json(self.root / DOCUMENTS_NAME)
        bindings_payload = _read_json(self.root / BINDINGS_NAME)
        self.documents = _declared_records(
            documents_payload, "document_count", "documents"
        )
        self.bindings = _declared_records(
            bindings_payload, "binding_count", "bindings"
        )

    def verify_all(self) -> None:
        """Verify collection, package bytes, snapshot tables, and stable identities."""
        candidate_inputs = self.manifest.get("candidate_inputs")
        if not isinstance(candidate_inputs, dict) or set(candidate_inputs) != {
            "duration_source_index",
            "correction_source_index",
        }:
            raise ValueError("source-binding candidate input declaration is invalid")
        for name, declaration in candidate_inputs.items():
            if not isinstance(declaration, dict) or type(declaration.get("path")) is not str:
                raise ValueError("source-binding candidate input declaration is invalid")
            path = _regular_file(Path(declaration["path"]), name)
            if declaration.get("sha256") != _sha256(path):
                raise ValueError("source-binding candidate input digest changed")
        collection = self.manifest.get("collection")
        if not isinstance(collection, dict):
            raise TypeError("source-binding collection declaration is invalid")
        collection_manifest = _regular_file(
            Path(str(collection.get("manifest_path"))), "collection manifest"
        )
        if collection.get("manifest_sha256") != _sha256(collection_manifest):
            raise ValueError("source-binding collection manifest digest changed")
        collection_payload, request, scope = _load_collection_scope(collection_manifest)
        if (
            collection.get("request_path") != collection_payload.get("request_path")
            or collection.get("request_sha256") != collection_payload.get("request_sha256")
            or self.manifest.get("universe_id") != request.get("universe_id")
            or self.manifest.get("financial_as_of") != request.get("as_of_date")
            or self.manifest.get("parser_version") != PARSER_VERSION
        ):
            raise ValueError("source-binding request scope differs")
        package_root = _real_directory(
            Path(str(self.manifest.get("package_root"))), "package root"
        )
        document_index = _document_index(self.documents)
        scope_index = {
            (row.ticker, row.cik, row.accession): row for row in scope
        }
        if set(document_index) != set(scope_index):
            raise ValueError("source-binding document scope differs from collection")

        verified_tables: dict[
            tuple[str, str, str],
            tuple[dict[str, dict[str, Any]], dict[str, Any], set[str]],
        ] = {}
        for key, document in document_index.items():
            filing = scope_index[key]
            expected_package = _package_path(package_root, filing.cik, filing.accession)
            if document.get("package_path") != str(expected_package):
                raise ValueError("source-binding package path differs from cache root")
            if document.get("package_sha256") != _sha256(expected_package):
                raise ValueError("source-binding package bytes changed")
            primary = _read_primary_member(expected_package, filing.primary_document)
            if document.get("primary_sha256") != _sha256_bytes(primary):
                raise ValueError("source-binding primary-document bytes changed")
            if (
                document.get("primary_document") != filing.primary_document
                or document.get("snapshot_root") != str(filing.snapshot_root)
                or document.get("snapshot_manifest_path")
                != str(filing.snapshot_manifest)
                or document.get("snapshot_manifest_sha256")
                != _sha256(filing.snapshot_manifest)
                or document.get("parser_version") != PARSER_VERSION
            ):
                raise ValueError("source-binding snapshot declaration changed")
            snapshot_manifest = _read_json(filing.snapshot_manifest)
            if (
                snapshot_manifest.get("cik") != filing.cik
                or snapshot_manifest.get("accession") != filing.accession
                or snapshot_manifest.get("package_sha256")
                != document.get("package_sha256")
                or snapshot_manifest.get("layer1_parser_version") != PARSER_VERSION
            ):
                raise ValueError("source-binding snapshot identity differs")
            tables = document.get("tables")
            if not isinstance(tables, dict) or set(tables) != {
                "fact.parquet",
                "concept.parquet",
                "context.parquet",
            }:
                raise ValueError("source-binding table declaration is invalid")
            for name, declaration in tables.items():
                _verify_file_declaration(filing.snapshot_root / name, declaration, name)
            facts = pl.read_parquet(filing.snapshot_root / "fact.parquet").with_row_index(
                "_source_ordinal"
            ).to_dicts()
            concepts = _unique_index(
                pl.read_parquet(filing.snapshot_root / "concept.parquet").to_dicts(),
                "raw_concept_id",
                "v5 Concept",
            )
            contexts = {
                str(row["context_id"])
                for row in pl.read_parquet(
                    filing.snapshot_root / "context.parquet"
                ).to_dicts()
            }
            verified_tables[key] = (
                _unique_index(facts, "fact_id", "v5 Fact"),
                concepts,
                contexts,
            )

        source_ids: set[tuple[str, str, str, str, str]] = set()
        fact_ids: set[tuple[str, str, str, str]] = set()
        counts = {"DURATION": 0, "APPROVED_TRANSFORM_CORRECTION": 0}
        for binding in self.bindings:
            if not isinstance(binding, dict) or binding.get("binding_kind") not in counts:
                raise ValueError("source-binding record is invalid")
            key = (
                str(binding.get("ticker")),
                str(binding.get("cik")),
                str(binding.get("accession")),
            )
            document = document_index.get(key)
            tables = verified_tables.get(key)
            if document is None or tables is None:
                raise ValueError("source-binding record is outside collection scope")
            source_identity = (*key, binding["binding_kind"], str(binding.get("source_id")))
            fact_identity = (*key, str(binding.get("fact_id")))
            if source_identity in source_ids or fact_identity in fact_ids:
                raise ValueError("source-binding identity is duplicated")
            source_ids.add(source_identity)
            fact_ids.add(fact_identity)
            facts, concepts, contexts = tables
            fact = facts.get(str(binding.get("fact_id")))
            if fact is None:
                raise ValueError("source-binding Fact is absent from v5 snapshot")
            concept = concepts.get(str(binding.get("raw_concept_id")))
            filing_id = _stable_id("filing", key[1], key[2])
            expected_context = _stable_id(
                "context", filing_id, binding.get("source_context_ref")
            )
            expected_fact = _stable_id(
                "fact",
                filing_id,
                binding.get("source_id"),
                binding.get("source_locator"),
                binding.get("source_ordinal"),
            )
            expected_concept = _stable_id(
                "concept",
                filing_id,
                binding.get("concept_namespace"),
                binding.get("concept_local_name"),
            )
            if (
                binding.get("filing_id") != filing_id
                or binding.get("context_id") != expected_context
                or binding.get("fact_id") != expected_fact
                or binding.get("raw_concept_id") != expected_concept
                or binding.get("package_sha256") != document.get("package_sha256")
                or binding.get("primary_sha256") != document.get("primary_sha256")
                or fact.get("_source_ordinal") != binding.get("source_ordinal")
                or fact.get("source_locator") != binding.get("source_locator")
                or fact.get("source_document") != binding.get("primary_document")
                or fact.get("context_id") != binding.get("context_id")
                or fact.get("raw_concept_id") != binding.get("raw_concept_id")
                or fact.get("raw_value") != binding.get("actual_raw_value")
                or _json_scalar(fact.get("value_numeric"))
                != binding.get("actual_value_numeric")
                or fact.get("value_text") != binding.get("actual_value_text")
                or fact.get("is_nil") != binding.get("actual_is_nil")
                or fact.get("reported_or_derived") != "REPORTED"
                or concept is None
                or concept.get("qname") != binding.get("concept_qname")
                or concept.get("data_type") != binding.get("concept_data_type_qname")
                or binding.get("context_id") not in contexts
            ):
                raise ValueError("source-binding stable identity differs from v5 Raw")
            counts[binding["binding_kind"]] += 1
        declared_counts = self.manifest.get("counts")
        if not isinstance(declared_counts, dict) or (
            declared_counts.get("companies") != len({key[1] for key in document_index})
            or declared_counts.get("filings") != len(document_index)
            or declared_counts.get("duration_bindings") != counts["DURATION"]
            or declared_counts.get("approved_transform_corrections")
            != counts["APPROVED_TRANSFORM_CORRECTION"]
        ):
            raise ValueError("source-binding manifest counts differ")

    def duration_bindings(self) -> tuple[dict[str, Any], ...]:
        """Return governed duration source bindings."""
        return tuple(
            dict(row) for row in self.bindings if row["binding_kind"] == "DURATION"
        )

    def approved_transform_corrections(self) -> tuple[dict[str, Any], ...]:
        """Return governed supported-lexical source bindings."""
        return tuple(
            dict(row)
            for row in self.bindings
            if row["binding_kind"] == "APPROVED_TRANSFORM_CORRECTION"
        )


class SourceBindingsV2Reader:
    """Reopen and verify an explicit-scope mixed v5/v6 binding publication."""

    def __init__(self, root: Path, manifest_sha256: str | None = None) -> None:
        self.root = _real_directory(root, "source-binding v2 publication")
        children = tuple(self.root.iterdir())
        expected = {MANIFEST_NAME, DOCUMENTS_NAME, BINDINGS_NAME}
        if {path.name for path in children} != expected or any(
            path.is_symlink() or not path.is_file() for path in children
        ):
            raise ValueError("source-binding v2 publication file set is invalid")
        self.manifest_path = self.root / MANIFEST_NAME
        if manifest_sha256 is not None and _sha256(self.manifest_path) != manifest_sha256:
            raise ValueError("source-binding v2 manifest digest differs")
        self.manifest = _read_json(self.manifest_path)
        if self.manifest.get("version") != VERSION_V2:
            raise ValueError("unsupported source-binding v2 publication")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or set(files) != {DOCUMENTS_NAME, BINDINGS_NAME}:
            raise ValueError("source-binding v2 file manifest is invalid")
        for name, declaration in files.items():
            _verify_file_declaration(self.root / name, declaration, name)
        identity = {key: value for key, value in self.manifest.items() if key != "publication_id"}
        publication_id = "source-bindings-v2-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        if self.manifest.get("publication_id") != publication_id:
            raise ValueError("source-binding v2 publication identity mismatch")
        if _COMMIT.fullmatch(str(self.manifest.get("producer_revision"))) is None:
            raise ValueError("source-binding v2 producer revision is invalid")
        self.publication_id = publication_id
        self.documents = _declared_records_version(
            _read_json(self.root / DOCUMENTS_NAME),
            version=VERSION_V2,
            count_key="document_count",
            records_key="documents",
        )
        self.bindings = _declared_records_version(
            _read_json(self.root / BINDINGS_NAME),
            version=VERSION_V2,
            count_key="binding_count",
            records_key="bindings",
        )
        versions = sorted({str(row.get("parser_version")) for row in self.documents})
        profiles = self.manifest.get("parser_profiles")
        expected_profiles = [
            {"parser_version": version, **KNOWN_PARSER_PROFILES[version]}
            for version in versions
            if version in KNOWN_PARSER_PROFILES
        ]
        if len(expected_profiles) != len(versions) or profiles != expected_profiles:
            raise ValueError("source-binding v2 parser profile declaration is invalid")

    def verify_all(self) -> None:
        """Verify source indexes, cached bytes, complete Raw bindings, and scope."""
        candidate_inputs = self.manifest.get("candidate_inputs")
        if not isinstance(candidate_inputs, dict) or set(candidate_inputs) != {
            "duration_source_index",
            "correction_source_index",
        }:
            raise ValueError("source-binding v2 candidate input declaration is invalid")
        for name, declaration in candidate_inputs.items():
            if not isinstance(declaration, dict) or type(declaration.get("path")) is not str:
                raise ValueError("source-binding v2 candidate input declaration is invalid")
            path = _regular_file(Path(declaration["path"]), name)
            if declaration.get("sha256") != _sha256(path):
                raise ValueError("source-binding v2 candidate input digest changed")
        collection = self.manifest.get("collection")
        if not isinstance(collection, dict):
            raise TypeError("source-binding v2 collection declaration is invalid")
        collection_manifest = _regular_file(
            Path(str(collection.get("manifest_path"))), "collection manifest"
        )
        if collection.get("manifest_sha256") != _sha256(collection_manifest):
            raise ValueError("source-binding v2 collection manifest digest changed")
        collection_payload, request, all_scope = _load_collection_scope(collection_manifest)
        scope_rows = self.manifest.get("scope_companies")
        requested_scope = (
            tuple(scope_rows) if isinstance(scope_rows, list) else None
        )
        scope, parent_companies, scope_companies = _select_collection_scope(
            all_scope, request=request, requested=requested_scope
        )
        mode = "FULL" if scope_companies == parent_companies else "EXPLICIT_SUBSET"
        if (
            self.manifest.get("parent_collection_companies") != list(parent_companies)
            or self.manifest.get("scope_companies") != list(scope_companies)
            or self.manifest.get("collection_scope_mode") != mode
            or collection.get("request_path") != collection_payload.get("request_path")
            or collection.get("request_sha256") != collection_payload.get("request_sha256")
            or self.manifest.get("universe_id") != request.get("universe_id")
            or self.manifest.get("financial_as_of") != request.get("as_of_date")
        ):
            raise ValueError("source-binding v2 request scope differs")
        package_root = _real_directory(Path(str(self.manifest.get("package_root"))), "package root")
        document_index = _document_index(self.documents)
        scope_index = {(row.ticker, row.cik, row.accession): row for row in scope}
        if set(document_index) != set(scope_index):
            raise ValueError("source-binding v2 document scope differs from collection")

        verified: dict[
            tuple[str, str, str],
            tuple[
                dict[str, dict[str, Any]],
                dict[str, dict[str, Any]],
                set[str],
                dict[tuple[str, str, str, str], dict[str, Any]],
            ],
        ] = {}
        for key, document in document_index.items():
            filing = scope_index[key]
            package = _package_path(package_root, filing.cik, filing.accession)
            if document.get("package_path") != str(package) or document.get("package_sha256") != _sha256(package):
                raise ValueError("source-binding v2 package identity changed")
            primary = _read_primary_member(package, filing.primary_document)
            if document.get("primary_sha256") != _sha256_bytes(primary):
                raise ValueError("source-binding v2 primary-document bytes changed")
            if (
                document.get("primary_document") != filing.primary_document
                or document.get("snapshot_root") != str(filing.snapshot_root)
                or document.get("snapshot_manifest_path") != str(filing.snapshot_manifest)
                or document.get("snapshot_manifest_sha256") != _sha256(filing.snapshot_manifest)
            ):
                raise ValueError("source-binding v2 snapshot declaration changed")
            snapshot_manifest = _read_json(filing.snapshot_manifest)
            parser_version = _known_parser_version(snapshot_manifest, filing, _sha256(package))
            if (
                document.get("parser_version") != parser_version
                or document.get("parser_profile") != KNOWN_PARSER_PROFILES[parser_version]
            ):
                raise ValueError("source-binding v2 parser profile differs")
            tables = document.get("tables")
            if not isinstance(tables, dict) or set(tables) != {
                "fact.parquet",
                "concept.parquet",
                "context.parquet",
            }:
                raise ValueError("source-binding v2 table declaration is invalid")
            for name, declaration in tables.items():
                _verify_file_declaration(filing.snapshot_root / name, declaration, name)
            facts = pl.read_parquet(filing.snapshot_root / "fact.parquet").with_row_index(
                "_source_ordinal"
            ).to_dicts()
            concepts = _unique_index(
                pl.read_parquet(filing.snapshot_root / "concept.parquet").to_dicts(),
                "raw_concept_id",
                "Raw Concept",
            )
            contexts = {
                str(row["context_id"])
                for row in pl.read_parquet(filing.snapshot_root / "context.parquet").to_dicts()
            }
            verified[key] = (
                _unique_index(facts, "fact_id", "Raw Fact"),
                concepts,
                contexts,
                _extract_source_rows(primary, filing),
            )

        source_ids: set[tuple[str, str, str, str, str]] = set()
        fact_ids: set[tuple[str, str, str, str]] = set()
        observed_sources: set[tuple[str, str, str, str, str]] = set()
        counts = {"DURATION": 0, "APPROVED_TRANSFORM_CORRECTION": 0}
        for binding in self.bindings:
            if not isinstance(binding, dict) or binding.get("binding_kind") not in counts:
                raise ValueError("source-binding v2 record is invalid")
            key = (str(binding.get("ticker")), str(binding.get("cik")), str(binding.get("accession")))
            document = document_index.get(key)
            tables = verified.get(key)
            if document is None or tables is None:
                raise ValueError("source-binding v2 record is outside collection scope")
            kind = str(binding["binding_kind"])
            source_identity = (*key, kind, str(binding.get("source_id")))
            fact_identity = (*key, str(binding.get("fact_id")))
            if source_identity in source_ids or fact_identity in fact_ids:
                raise ValueError("source-binding v2 identity is duplicated")
            source_ids.add(source_identity)
            fact_ids.add(fact_identity)
            facts, concepts, contexts, source_rows = tables
            source_key = (*key, str(binding.get("source_id")))
            source = source_rows.get(source_key)
            expected_kind = (
                source is not None
                and (
                    (kind == "DURATION" and source["transform"] in _DURATION_TRANSFORMS)
                    or (kind == "APPROVED_TRANSFORM_CORRECTION" and _is_supported_correction_source(source))
                )
            )
            fact = facts.get(str(binding.get("fact_id")))
            concept = concepts.get(str(binding.get("raw_concept_id")))
            filing_id = _stable_id("filing", key[1], key[2])
            expected_context = _stable_id("context", filing_id, binding.get("source_context_ref"))
            expected_fact = _stable_id(
                "fact", filing_id, binding.get("source_id"), binding.get("source_locator"), binding.get("source_ordinal")
            )
            expected_concept = _stable_id(
                "concept", filing_id, binding.get("concept_namespace"), binding.get("concept_local_name")
            )
            if (
                not expected_kind
                or source is None
                or any(source.get(name) != binding.get(name) for name in source)
                or fact is None
                or binding.get("filing_id") != filing_id
                or binding.get("context_id") != expected_context
                or binding.get("fact_id") != expected_fact
                or binding.get("raw_concept_id") != expected_concept
                or binding.get("package_sha256") != document.get("package_sha256")
                or binding.get("primary_sha256") != document.get("primary_sha256")
                or fact.get("_source_ordinal") != binding.get("source_ordinal")
                or fact.get("source_locator") != binding.get("source_locator")
                or fact.get("source_document") != binding.get("primary_document")
                or fact.get("context_id") != binding.get("context_id")
                or fact.get("raw_concept_id") != binding.get("raw_concept_id")
                or fact.get("raw_value") != binding.get("actual_raw_value")
                or _json_scalar(fact.get("value_numeric")) != binding.get("actual_value_numeric")
                or fact.get("value_text") != binding.get("actual_value_text")
                or fact.get("is_nil") != binding.get("actual_is_nil")
                or fact.get("reported_or_derived") != "REPORTED"
                or concept is None
                or concept.get("qname") != binding.get("concept_qname")
                or concept.get("data_type") != binding.get("concept_data_type_qname")
                or binding.get("context_id") not in contexts
            ):
                raise ValueError("source-binding v2 differs from cached source or Raw")
            observed_sources.add(source_identity)
            counts[kind] += 1
        expected_sources = {
            (*key, kind, source["source_id"])
            for key, tables in verified.items()
            for source in tables[3].values()
            for kind in (
                (["DURATION"] if source["transform"] in _DURATION_TRANSFORMS else [])
                + (["APPROVED_TRANSFORM_CORRECTION"] if _is_supported_correction_source(source) else [])
            )
        }
        if observed_sources != expected_sources:
            raise ValueError("source-binding v2 does not cover every governed source")
        declared = self.manifest.get("counts")
        if not isinstance(declared, dict) or declared != {
            "companies": len({key[1] for key in document_index}),
            "filings": len(document_index),
            "duration_bindings": counts["DURATION"],
            "approved_transform_corrections": counts["APPROVED_TRANSFORM_CORRECTION"],
        }:
            raise ValueError("source-binding v2 manifest counts differ")

    def duration_bindings(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in self.bindings if row["binding_kind"] == "DURATION")

    def approved_transform_corrections(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.bindings
            if row["binding_kind"] == "APPROVED_TRANSFORM_CORRECTION"
        )


def _select_collection_scope(
    scope: tuple[_FilingScope, ...],
    *,
    request: dict[str, Any],
    requested: tuple[dict[str, str], ...] | None,
) -> tuple[
    tuple[_FilingScope, ...],
    tuple[dict[str, str], ...],
    tuple[dict[str, str], ...],
]:
    companies = request.get("companies")
    if not isinstance(companies, list):
        raise TypeError("collection request company scope is malformed")
    parent = tuple(
        sorted(
            (
                {"ticker": str(row.get("ticker")), "cik": str(row.get("cik"))}
                for row in companies
                if isinstance(row, dict)
            ),
            key=lambda row: (row["ticker"], row["cik"]),
        )
    )
    parent_keys = {(row["ticker"], row["cik"]) for row in parent}
    if len(parent) != len(companies) or len(parent_keys) != len(parent):
        raise ValueError("collection request company scope is duplicated or malformed")
    if requested is None:
        selected_companies = parent
    else:
        if not requested:
            raise ValueError("explicit collection scope must not be empty")
        selected_companies = tuple(
            sorted(
                (
                    {"ticker": str(row.get("ticker")), "cik": str(row.get("cik"))}
                    for row in requested
                    if isinstance(row, dict)
                ),
                key=lambda row: (row["ticker"], row["cik"]),
            )
        )
        selected_keys = {
            (row["ticker"], row["cik"]) for row in selected_companies
        }
        if (
            len(selected_companies) != len(requested)
            or len(selected_keys) != len(selected_companies)
            or not selected_keys.issubset(parent_keys)
        ):
            raise ValueError("explicit collection scope is duplicated or foreign")
    selected_keys = {(row["ticker"], row["cik"]) for row in selected_companies}
    selected_scope = tuple(
        row for row in scope if (row.ticker, row.cik) in selected_keys
    )
    represented = {(row.ticker, row.cik) for row in selected_scope}
    if represented != selected_keys:
        raise ValueError("explicit collection scope has no complete planned filing scope")
    return selected_scope, parent, selected_companies


def _known_parser_version(
    manifest: dict[str, Any], filing: _FilingScope, package_sha256: str
) -> str:
    parser_version = manifest.get("layer1_parser_version")
    if (
        manifest.get("cik") != filing.cik
        or manifest.get("accession") != filing.accession
        or manifest.get("package_sha256") != package_sha256
        or parser_version not in KNOWN_PARSER_PROFILES
    ):
        raise ValueError(
            f"known snapshot/package profile differs for {filing.accession}"
        )
    return str(parser_version)


def _source_fact_id(
    source: dict[str, Any], *, filing: _FilingScope, facts: list[dict[str, Any]]
) -> str:
    filing_id = _stable_id("filing", filing.cik, filing.accession)
    matches = [
        str(row.get("fact_id"))
        for row in facts
        if row.get("fact_id")
        == _stable_id(
            "fact",
            filing_id,
            source["source_id"],
            source["source_locator"],
            row.get("_source_ordinal"),
        )
    ]
    if len(matches) != 1:
        raise ValueError("source index source does not resolve to exactly one Raw Fact")
    return matches[0]


def _load_collection_scope(
    collection_manifest: Path,
) -> tuple[dict[str, Any], dict[str, Any], tuple[_FilingScope, ...]]:
    collection = _read_json(collection_manifest)
    request_path = _regular_file(Path(str(collection.get("request_path"))), "collection request")
    if collection.get("request_sha256") != _sha256(request_path):
        raise ValueError("collection request digest changed")
    request = _read_json(request_path)
    request_companies = request.get("companies")
    companies = collection.get("companies")
    if not isinstance(request_companies, list) or not isinstance(companies, list):
        raise TypeError("collection company scope is malformed")
    requested = {
        (str(row.get("ticker")), str(row.get("cik")))
        for row in request_companies
        if isinstance(row, dict)
    }
    manifested = {
        (str(row.get("ticker")), str(row.get("cik")))
        for row in companies
        if isinstance(row, dict)
    }
    if (
        len(requested) != len(request_companies)
        or len(manifested) != len(companies)
        or manifested != requested
    ):
        raise ValueError("collection membership differs from immutable request")
    scope: list[_FilingScope] = []
    for company in companies:
        ticker = str(company["ticker"])
        cik = str(company["cik"])
        if _SAFE_TICKER.fullmatch(ticker) is None or _SAFE_CIK.fullmatch(cik) is None:
            raise ValueError("collection company identity is unsafe")
        plan_path = _regular_file(Path(str(company.get("plan_path"))), "collection plan")
        if company.get("plan_sha256") != _sha256(plan_path):
            raise ValueError("collection plan digest changed")
        plan = _read_json(plan_path)
        plan_companies = plan.get("companies")
        if not isinstance(plan_companies, list) or len(plan_companies) != 1:
            raise ValueError("collection plan company scope is malformed")
        planned = plan_companies[0]
        filings = planned.get("filings") if isinstance(planned, dict) else None
        if planned.get("ticker") != ticker or planned.get("cik") != cik or not isinstance(filings, list):
            raise ValueError("collection plan company identity differs")
        intake_path = _regular_file(
            collection_manifest.parent / "companies" / ticker / "intake" / "history_intake.json",
            "collection intake",
        )
        intake = _read_json(intake_path)
        outcomes = intake.get("filings")
        if intake.get("complete") is not True or intake.get("plan") != plan or not isinstance(outcomes, list):
            raise ValueError("collection intake is incomplete or foreign")
        planned_index = {
            (str(row.get("cik")), str(row.get("accession"))): row
            for row in filings
            if isinstance(row, dict)
        }
        if len(planned_index) != len(filings):
            raise ValueError("collection plan repeats a filing identity")
        outcome_index: dict[tuple[str, str], dict[str, Any]] = {}
        for outcome in outcomes:
            filing = outcome.get("filing") if isinstance(outcome, dict) else None
            if (
                not isinstance(filing, dict)
                or outcome.get("ticker") != ticker
                or outcome.get("status") not in {"INGESTED", "REUSED"}
                or type(outcome.get("source_run")) is not str
            ):
                raise ValueError("collection intake outcome is invalid")
            identity = (str(filing.get("cik")), str(filing.get("accession")))
            if identity in outcome_index or planned_index.get(identity) != filing:
                raise ValueError("collection intake outcome differs from plan")
            outcome_index[identity] = outcome
        if set(outcome_index) != set(planned_index):
            raise ValueError("collection intake does not cover the plan")
        for filing in filings:
            accession = str(filing.get("accession"))
            primary = str(filing.get("primary_document"))
            if (
                _SAFE_ACCESSION.fullmatch(accession) is None
                or not _safe_member_name(primary)
            ):
                raise ValueError("planned filing path identity is unsafe")
            outcome = outcome_index[(cik, accession)]
            source_run = _real_directory(Path(outcome["source_run"]), "intake source run")
            snapshot_root = _real_directory(
                source_run / "snapshots" / cik / accession.replace("-", ""),
                "v5 snapshot",
            )
            scope.append(
                _FilingScope(
                    ticker=ticker,
                    cik=cik,
                    accession=accession,
                    primary_document=primary,
                    snapshot_root=snapshot_root,
                    snapshot_manifest=_regular_file(
                        snapshot_root / "layer1_manifest.json", "v5 snapshot manifest"
                    ),
                )
            )
    identities = {(row.ticker, row.cik, row.accession) for row in scope}
    if len(identities) != len(scope):
        raise ValueError("collection plans repeat a filing identity")
    return collection, request, tuple(sorted(scope, key=lambda row: (row.ticker, row.accession)))


def _load_duration_claims(
    path: Path, scope: tuple[_FilingScope, ...]
) -> tuple[
    dict[tuple[str, str, str, str], dict[str, Any]],
    dict[tuple[str, str, str], str],
]:
    payload = _read_json(path)
    documents = payload.get("primary_documents")
    facts = payload.get("duration_facts")
    if not isinstance(documents, list) or not isinstance(facts, list):
        raise TypeError("duration source index is malformed")
    document_index: dict[tuple[str, str, str], str] = {}
    for row in documents:
        if not isinstance(row, dict) or _SHA256.fullmatch(str(row.get("primary_sha256"))) is None:
            raise ValueError("duration source document claim is invalid")
        key = (str(row.get("ticker")), str(row.get("cik")), str(row.get("accession")))
        if key in document_index:
            raise ValueError("duration source index repeats a document")
        document_index[key] = str(row["primary_sha256"])
    expected_documents = {(row.ticker, row.cik, row.accession) for row in scope}
    if set(document_index) != expected_documents:
        raise ValueError("duration source index document scope differs")
    claims: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in facts:
        if not isinstance(row, dict) or type(row.get("source_id")) is not str:
            raise ValueError("duration source claim is invalid")
        key = (
            str(row.get("ticker")),
            str(row.get("cik")),
            str(row.get("accession")),
            row["source_id"],
        )
        if key in claims or key[:3] not in expected_documents:
            raise ValueError("duration source claim is duplicated or foreign")
        claims[key] = row
    return claims, document_index


def _load_correction_claims(
    path: Path, scope: tuple[_FilingScope, ...]
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    payload = _read_json(path)
    facts = payload.get("facts")
    if payload.get("unmatched") != [] or not isinstance(facts, list) or payload.get("fact_count") != len(facts):
        raise ValueError("supported lexical correction source index is incomplete")
    planned = {(row.ticker, row.cik, row.accession) for row in scope}
    claims: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in facts:
        if not isinstance(row, dict) or type(row.get("source_id")) is not str:
            raise ValueError("supported lexical correction claim is invalid")
        key = (
            str(row.get("ticker")),
            str(row.get("cik")),
            str(row.get("accession")),
            row["source_id"],
        )
        if key in claims or key[:3] not in planned:
            raise ValueError("supported lexical correction claim is duplicated or foreign")
        claims[key] = row
    return claims


def _extract_source_rows(
    primary: bytes, filing: _FilingScope
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    text = primary.decode("utf-8", errors="replace")
    namespaces = {match.group(1): match.group(3) for match in _XMLNS.finditer(text)}
    document = lxml_html.fromstring(
        primary,
        parser=lxml_html.HTMLParser(huge_tree=True, no_network=True, recover=False),
    )
    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for element in document.xpath("//*[@format]"):
        format_qname = element.get("format")
        if not isinstance(format_qname, str) or ":" not in format_qname:
            continue
        format_prefix, transform = format_qname.split(":", 1)
        if namespaces.get(format_prefix) != SEC_TRANSFORM_NAMESPACE:
            continue
        source_id = element.get("id")
        concept_qname = element.get("name")
        context_ref = element.get("contextref")
        if (
            type(source_id) is not str
            or not source_id
            or type(concept_qname) is not str
            or ":" not in concept_qname
            or type(context_ref) is not str
            or not context_ref
            or element.sourceline is None
        ):
            raise ValueError(f"transform source fields are incomplete: {filing.accession}")
        concept_prefix, concept_local = concept_qname.split(":", 1)
        concept_namespace = namespaces.get(concept_prefix)
        if not concept_namespace:
            raise ValueError(f"transform Concept namespace is unresolved: {filing.accession}")
        tag_local = str(element.tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()
        element_type = {
            "nonnumeric": "nonNumeric",
            "nonfraction": "nonFraction",
        }.get(tag_local)
        if element_type is None:
            raise ValueError(f"unsupported transform source element: {element.tag}")
        key = (filing.ticker, filing.cik, filing.accession, source_id)
        if key in rows:
            raise ValueError(f"duplicate transform source id: {filing.accession} {source_id}")
        rows[key] = {
            "ticker": filing.ticker,
            "cik": filing.cik,
            "accession": filing.accession,
            "primary_document": filing.primary_document,
            "source_id": source_id,
            "source_context_ref": context_ref,
            "source_lexical": "".join(element.itertext()).strip(),
            "source_line": int(element.sourceline),
            "source_locator": f"line:{element.sourceline}",
            "source_element_type": element_type,
            "source_sign": element.get("sign"),
            "source_scale": element.get("scale"),
            "format_qname": format_qname,
            "format_namespace": SEC_TRANSFORM_NAMESPACE,
            "transform": transform,
            "concept_qname": concept_qname,
            "concept_namespace": concept_namespace,
            "concept_local_name": concept_local,
        }
    return rows


def _is_supported_correction_source(row: dict[str, Any]) -> bool:
    return (row["transform"], row["source_lexical"]) in {
        ("exchnameen", "Nasdaq"),
        ("stateprovnameen", "Idaho"),
        ("durwordsen", "three\N{NON-BREAKING HYPHEN}year"),
        ("durwordsen", "five\N{NON-BREAKING HYPHEN}year"),
        ("numwordsen", "nil"),
    }


def _compare_source_claim(
    source: dict[str, Any], claim: dict[str, Any], *, correction: bool
) -> None:
    pairs = {
        "primary_document": "primary_document",
        "source_id": "source_id",
        "concept_qname": "concept_qname",
        "source_lexical": "source_lexical",
        "format_qname": "format_qname",
        "format_namespace": "format_namespace",
    }
    if correction:
        pairs.update(
            {
                "source_element_type": "source_element_type",
                "source_scale": "source_scale",
                "source_sign": "source_sign",
            }
        )
    else:
        pairs["source_context_ref"] = "context_ref"
    if any(source[left] != claim.get(right) for left, right in pairs.items()):
        raise ValueError("source claim differs from cached primary document")


def _bind_source_row(
    *,
    filing: _FilingScope,
    kind: str,
    source: dict[str, Any],
    claim: dict[str, Any],
    package_sha256: str,
    primary_sha256: str,
    facts: dict[str, dict[str, Any]],
    concepts: dict[str, dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fact_id = claim.get("fact_id")
    if type(fact_id) is not str or fact_id not in facts:
        raise ValueError("source claim Fact is absent from v5 snapshot")
    fact = facts[fact_id]
    filing_id = _stable_id("filing", filing.cik, filing.accession)
    context_id = _stable_id("context", filing_id, source["source_context_ref"])
    raw_concept_id = _stable_id(
        "concept",
        filing_id,
        source["concept_namespace"],
        source["concept_local_name"],
    )
    ordinal = fact.get("_source_ordinal")
    expected_fact_id = _stable_id(
        "fact", filing_id, source["source_id"], source["source_locator"], ordinal
    )
    concept = concepts.get(raw_concept_id)
    if (
        expected_fact_id != fact_id
        or fact.get("filing_id") not in {None, filing_id}
        or fact.get("source_locator") != source["source_locator"]
        or fact.get("source_document") != filing.primary_document
        or fact.get("context_id") != context_id
        or fact.get("raw_concept_id") != raw_concept_id
        or fact.get("reported_or_derived") != "REPORTED"
        or context_id not in contexts
        or concept is None
        or concept.get("qname") != source["concept_qname"]
    ):
        raise ValueError("source claim does not bind to the v5 Raw identity")
    if kind == "APPROVED_TRANSFORM_CORRECTION" and (
        claim.get("context_id") != context_id
        or claim.get("raw_concept_id") != raw_concept_id
        or claim.get("source_locator") != source["source_locator"]
        or claim.get("concept_data_type_qname") != concept.get("data_type")
        or claim.get("primary_sha256") != primary_sha256
    ):
        raise ValueError("supported lexical correction identity differs from v5 Raw")
    return {
        **source,
        "binding_kind": kind,
        "package_sha256": package_sha256,
        "primary_sha256": primary_sha256,
        "filing_id": filing_id,
        "source_ordinal": ordinal,
        "fact_id": fact_id,
        "context_id": context_id,
        "raw_concept_id": raw_concept_id,
        "concept_data_type_qname": concept.get("data_type"),
        "actual_raw_value": fact.get("raw_value"),
        "actual_value_numeric": _json_scalar(fact.get("value_numeric")),
        "actual_value_text": fact.get("value_text"),
        "actual_is_nil": fact.get("is_nil"),
    }


def _document_index(
    documents: tuple[dict[str, Any], ...]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for document in documents:
        if not isinstance(document, dict):
            raise TypeError("source-binding document record is invalid")
        key = (
            str(document.get("ticker")),
            str(document.get("cik")),
            str(document.get("accession")),
        )
        if key in result:
            raise ValueError("source-binding document identity is duplicated")
        result[key] = document
    return result


def _package_path(package_root: Path, cik: str, accession: str) -> Path:
    candidate = package_root / cik / accession.replace("-", "") / f"{accession}-xbrl.zip"
    return _contained_regular_file(candidate, package_root, "cached accession package")


def _read_primary_member(package_path: Path, primary_document: str) -> bytes:
    if not _safe_member_name(primary_document):
        raise ValueError("primary-document member path is unsafe")
    with zipfile.ZipFile(package_path) as archive:
        matches = [info for info in archive.infolist() if info.filename == primary_document]
        if len(matches) != 1 or matches[0].is_dir():
            raise ValueError("primary-document member is absent or repeated")
        return archive.read(matches[0])


def _safe_member_name(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _declared_records(
    payload: dict[str, Any], count_key: str, records_key: str
) -> tuple[dict[str, Any], ...]:
    return _declared_records_version(
        payload,
        version=VERSION,
        count_key=count_key,
        records_key=records_key,
    )


def _declared_records_version(
    payload: dict[str, Any],
    *,
    version: str,
    count_key: str,
    records_key: str,
) -> tuple[dict[str, Any], ...]:
    records = payload.get(records_key)
    if (
        payload.get("version") != version
        or type(payload.get(count_key)) is not int
        or not isinstance(records, list)
        or payload[count_key] != len(records)
        or any(not isinstance(row, dict) for row in records)
    ):
        raise ValueError(f"source-binding {records_key} file is invalid")
    return tuple(records)


def _unique_index(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if type(value) is not str or not value or value in result:
            raise ValueError(f"{label} identity is missing or duplicated")
        result[value] = row
    return result


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


def _regular_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = path.absolute()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path


def _contained_regular_file(path: Path, root: Path, label: str) -> Path:
    path = _regular_file(path, label)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes its declared root") from exc
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")
        current = current.parent
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(_json(payload) + "\n", encoding="utf-8")
    return path


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_declaration(path: Path) -> dict[str, Any]:
    return {"sha256": _sha256(path), "size": path.stat().st_size}


def _verify_file_declaration(path: Path, declaration: Any, label: str) -> None:
    path = _regular_file(path, label)
    if (
        not isinstance(declaration, dict)
        or declaration.get("sha256") != _sha256(path)
        or declaration.get("size") != path.stat().st_size
    ):
        raise ValueError(f"source-binding file integrity mismatch: {label}")


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish governed SEC source bindings")
    parser.add_argument("--collection-manifest", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--duration-source-index", type=Path, required=True)
    parser.add_argument("--correction-source-index", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--producer-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    publication = publish_source_bindings(
        collection_manifest=args.collection_manifest,
        package_root=args.package_root,
        duration_source_index=args.duration_source_index,
        correction_source_index=args.correction_source_index,
        destination=args.destination,
        producer_revision=args.producer_revision,
    )
    SourceBindingsReader(publication.root).verify_all()
    print(str(publication.manifest_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
