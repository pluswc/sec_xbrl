"""Screening dataset v2 over a governed screening-metric publication."""

from __future__ import annotations

import copy
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.metrics.screening import ScreeningMetricReader
from sec_xbrl.screening.common import (
    atomic_replace,
    contained_file,
    digest_value,
    read_json,
    real_directory,
    regular_file,
    require_string,
    safe_new_destination,
    sha256_file,
    write_json,
)
from sec_xbrl.screening.dataset import ScreeningDatasetReader

VERSION = "screening-dataset-v2"
CONFIG_VERSION = "screening-prepare-config-v2"
MANIFEST = "screening_dataset_manifest.json"
COMPANIES = "companies.json"
METADATA = "metadata_inventory.json"
DEFINITIONS = "metric_definitions.json"
SUPPORT = "metric_support.json"
OBSERVATIONS = "metric_observations.json"


@dataclass(frozen=True, slots=True)
class ScreeningPublicationV2:
    root: Path
    publication_id: str
    manifest_path: Path


def publish_screening_dataset_v2(
    config_path: Path | str, destination: Path | str
) -> ScreeningPublicationV2:
    config_file = regular_file(Path(config_path), "screening v2 config")
    config = _validate_config(read_json(config_file, "screening v2 config"))
    destination_path = safe_new_destination(Path(destination), "screening v2 publication")
    metrics_root = real_directory(Path(config["metric_root"]), "screening metric publication")
    source_root = real_directory(Path(config["source_dataset_root"]), "screening source dataset")
    metric_manifest_path = regular_file(
        metrics_root / "screening_metric_manifest.json", "screening metric manifest"
    )
    source_manifest_path = regular_file(
        source_root / MANIFEST, "screening source dataset manifest"
    )
    if sha256_file(metric_manifest_path) != config["metric_manifest_sha256"]:
        raise ValueError("screening metric manifest differs from v2 config")
    if sha256_file(source_manifest_path) != config["source_dataset_manifest_sha256"]:
        raise ValueError("screening source dataset manifest differs from v2 config")
    metrics = ScreeningMetricReader(metrics_root)
    source = ScreeningDatasetReader(source_root)
    if metrics.manifest["financial_as_of"] != config["financial_as_of"]:
        raise ValueError("metric publication financial-as-of differs from v2 config")
    if source.manifest["financial_as_of"] != config["financial_as_of"]:
        raise ValueError("source dataset financial-as-of differs from v2 config")
    if set(metrics.manifest["configured_ciks"]) != {row["cik"] for row in source.companies}:
        raise ValueError("metric and source dataset company membership differs")
    identity_source = metrics.manifest.get("identity_source") or {}
    if (
        identity_source.get("publication_id") != source.publication_id
        or identity_source.get("manifest_sha256")
        != sha256_file(source_root / MANIFEST)
    ):
        raise ValueError("v2 source dataset differs from metric identity source")

    definitions = copy.deepcopy(metrics.definitions)
    support = [
        {**copy.deepcopy(row), "reason": (row.get("reasons") or [None])[0]}
        for row in metrics.support
    ]
    observations = [
        {
            **copy.deepcopy(row),
            "quality_blocking": row.get("quality_status") == "BLOCK",
        }
        for row in metrics.observations
    ]
    companies = copy.deepcopy(source.companies)
    metadata = copy.deepcopy(source.metadata)
    publication_id = "screening-dataset-" + digest_value(
        {
            "config": config,
            "metric_publication_id": metrics.manifest["publication_id"],
            "definitions": definitions,
            "support": support,
            "observations": observations,
        }
    )[:24]
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / COMPANIES, companies)
        write_json(staging / METADATA, metadata)
        write_json(staging / DEFINITIONS, definitions)
        write_json(staging / SUPPORT, support)
        write_json(staging / OBSERVATIONS, observations)
        files = _file_manifest(staging)
        metric_manifest = regular_file(metrics_root / "screening_metric_manifest.json", "metric manifest")
        source_manifest = regular_file(source_root / MANIFEST, "source screening manifest")
        versions = {
            "metric_definition_versions": sorted({row["definition_version"] for row in definitions}),
            "metric_publication_id": metrics.manifest["publication_id"],
            "metric_publication_versions": copy.deepcopy(metrics.manifest.get("versions", {})),
            "source_dataset_publication_id": source.publication_id,
            "source_dataset_versions": copy.deepcopy(source.manifest.get("versions", {})),
        }
        manifest = {
            "schema_version": VERSION,
            "publication_id": publication_id,
            "dataset_id": config["dataset_id"],
            "fixture_kind": config["fixture_kind"],
            "financial_as_of": config["financial_as_of"],
            "configured_ciks": [row["cik"] for row in companies],
            "company_count": len(companies),
            "metadata_count": len(metadata),
            "definition_count": len(definitions),
            "support_count": len(support),
            "observation_count": len(observations),
            "versions": versions,
            "config": config,
            "config_path": str(config_file),
            "config_sha256": sha256_file(config_file),
            "sources": {
                "metrics": {
                    "root": str(metrics_root),
                    "publication_id": metrics.manifest["publication_id"],
                    "manifest_sha256": sha256_file(metric_manifest),
                },
                "source_dataset": {
                    "root": str(source_root),
                    "publication_id": source.publication_id,
                    "manifest_sha256": sha256_file(source_manifest),
                },
                "metadata": copy.deepcopy(source.manifest["sources"]["metadata"]),
            },
            "files": files,
        }
        write_json(staging / MANIFEST, manifest)
        atomic_replace(staging, destination_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return ScreeningPublicationV2(destination_path, publication_id, destination_path / MANIFEST)


class ScreeningDatasetV2Reader:
    """Read v2 rows while revalidating metric and v1 identity parents."""

    def __init__(self, root: Path | str):
        self.root = real_directory(Path(root), "screening v2 publication")
        self.manifest = read_json(regular_file(self.root / MANIFEST, "screening v2 manifest"))
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported screening v2 publication")
        self.publication_id = self.manifest["publication_id"]
        self.companies = self._records(COMPANIES)
        self.metadata = self._records(METADATA)
        self.metric_definitions = self._records(DEFINITIONS)
        self.metric_support = self._records(SUPPORT)
        self.observations = self._records(OBSERVATIONS)
        self.verify_all()

    def _records(self, relative: str) -> list[dict[str, Any]]:
        value = read_json(contained_file(self.root, relative, relative), relative)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise TypeError(f"{relative} must contain object records")
        return value

    def company(self, cik: str) -> dict[str, Any]:
        rows = [row for row in self.companies if row["cik"] == cik]
        if len(rows) != 1:
            raise ValueError("company is not uniquely prepared")
        return copy.deepcopy(rows[0])

    def verify_all(self) -> dict[str, Any]:
        _verify_files(self.root, self.manifest)
        _assert_unique(self.companies, ("cik",), "company")
        _assert_unique(self.metric_definitions, ("metric_id",), "metric definition")
        _assert_unique(self.metric_support, ("cik", "metric_id"), "metric support")
        _assert_unique(
            self.observations,
            ("cik", "metric_id", "fiscal_year", "period_class", "view"),
            "metric observation",
        )
        counts = {
            "company_count": len(self.companies),
            "metadata_count": len(self.metadata),
            "definition_count": len(self.metric_definitions),
            "support_count": len(self.metric_support),
            "observation_count": len(self.observations),
        }
        if any(self.manifest.get(key) != value for key, value in counts.items()):
            raise ValueError("screening v2 declared counts changed")
        sources = self.manifest["sources"]
        metric_root = real_directory(Path(sources["metrics"]["root"]), "screening metric source")
        metric_manifest = regular_file(metric_root / "screening_metric_manifest.json", "screening metric manifest")
        if sha256_file(metric_manifest) != sources["metrics"]["manifest_sha256"]:
            raise ValueError("screening metric parent changed")
        metric_reader = ScreeningMetricReader(metric_root)
        if metric_reader.manifest["publication_id"] != sources["metrics"]["publication_id"]:
            raise ValueError("screening metric parent identity changed")
        source_root = real_directory(Path(sources["source_dataset"]["root"]), "screening v1 source")
        source_manifest = regular_file(source_root / MANIFEST, "screening v1 manifest")
        if sha256_file(source_manifest) != sources["source_dataset"]["manifest_sha256"]:
            raise ValueError("screening v1 identity parent changed")
        source_reader = ScreeningDatasetReader(source_root)
        if source_reader.publication_id != sources["source_dataset"]["publication_id"]:
            raise ValueError("screening v1 parent identity changed")
        identity_source = metric_reader.manifest.get("identity_source") or {}
        if (
            identity_source.get("publication_id") != source_reader.publication_id
            or identity_source.get("manifest_sha256")
            != sources["source_dataset"]["manifest_sha256"]
        ):
            raise ValueError("screening v2 parents do not share one identity source")
        expected_support = [
            {**copy.deepcopy(row), "reason": (row.get("reasons") or [None])[0]}
            for row in metric_reader.support
        ]
        expected_observations = [
            {**copy.deepcopy(row), "quality_blocking": row.get("quality_status") == "BLOCK"}
            for row in metric_reader.observations
        ]
        if (
            self.metric_definitions != metric_reader.definitions
            or self.metric_support != expected_support
            or self.observations != expected_observations
            or self.companies != source_reader.companies
            or self.metadata != source_reader.metadata
        ):
            raise ValueError("screening v2 rows differ from governed parents")
        return {
            "publication_id": self.publication_id,
            "dataset_id": self.manifest["dataset_id"],
            "fixture_kind": self.manifest["fixture_kind"],
            "financial_as_of": self.manifest["financial_as_of"],
            **counts,
        }


def open_screening_dataset(root: Path | str) -> ScreeningDatasetReader | ScreeningDatasetV2Reader:
    root_path = real_directory(Path(root), "screening dataset")
    manifest = read_json(regular_file(root_path / MANIFEST, "screening dataset manifest"))
    if manifest.get("schema_version") == VERSION:
        return ScreeningDatasetV2Reader(root_path)
    return ScreeningDatasetReader(root_path)


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported screening v2 config")
    fixture_kind = value.get("fixture_kind", "ACTUAL_PREPARED")
    if fixture_kind not in {"ACTUAL_PREPARED", "CACHE_FUTURE_UPDATE_FIXTURE", "SYNTHETIC_ERROR_FIXTURE"}:
        raise ValueError("unsupported screening v2 fixture kind")
    return {
        "schema_version": CONFIG_VERSION,
        "dataset_id": require_string(value.get("dataset_id"), "dataset_id"),
        "fixture_kind": fixture_kind,
        "financial_as_of": require_string(value.get("financial_as_of"), "financial_as_of"),
        "metric_root": require_string(value.get("metric_root"), "metric_root"),
        "metric_manifest_sha256": _require_sha256(
            value.get("metric_manifest_sha256"), "metric_manifest_sha256"
        ),
        "source_dataset_root": require_string(value.get("source_dataset_root"), "source_dataset_root"),
        "source_dataset_manifest_sha256": _require_sha256(
            value.get("source_dataset_manifest_sha256"),
            "source_dataset_manifest_sha256",
        ),
    }


def _require_sha256(value: Any, field: str) -> str:
    digest = require_string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": str(path.relative_to(root)), "sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _verify_files(root: Path, manifest: dict[str, Any]) -> None:
    expected = set()
    for row in manifest.get("files", []):
        relative = require_string(row.get("path"), "screening v2 file path")
        path = contained_file(root, relative, "screening v2 file")
        if sha256_file(path) != row.get("sha256") or path.stat().st_size != row.get("size"):
            raise ValueError("screening v2 file changed")
        expected.add(relative)
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != MANIFEST
    }
    if expected != actual or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("screening v2 file set changed")


def _assert_unique(rows: list[dict[str, Any]], fields: tuple[str, ...], label: str) -> None:
    keys = [tuple(digest_value(row.get(field)) for field in fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {label}")

