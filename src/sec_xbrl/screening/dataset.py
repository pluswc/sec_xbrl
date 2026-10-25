"""Immutable prepared screening publication over governed consumer bundles.

This offline consumer preparation step does not read SEC source material,
choose filings, approve mappings, or calculate financial metrics.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.analysis import open_analysis
from sec_xbrl.company_metadata import CompanyMetadataReader
from sec_xbrl.screening.common import (
    atomic_replace,
    canonical_json,
    contained_file,
    digest_value,
    read_json,
    real_directory,
    regular_file,
    require_cik,
    require_string,
    require_ticker,
    safe_new_destination,
    sha256_file,
    write_json,
)
from sec_xbrl.universe_delivery import UniverseDeliveryReader

VERSION = "screening-dataset-v1"
CONFIG_VERSION = "screening-prepare-config-v1"
LEGACY_IDENTITY_SOURCE_KIND = "LEGACY_SCREENING_DATASET"
GENERIC_IDENTITY_SOURCE_KIND = "GENERIC_METRIC_IDENTITY_ATTESTATION"
GENERIC_IDENTITY_MANIFEST = "generic_metric_identity_manifest.json"
MANIFEST = "screening_dataset_manifest.json"
COMPANIES = "companies.json"
METADATA = "metadata_inventory.json"
SUPPORT = "metric_support.json"
OBSERVATIONS = "metric_observations.json"
VIEW = "LATEST_REPORTED"
SUPPORTED_METRICS = {
    "revenue": "매출",
    "cfo": "영업활동 현금흐름",
    "operating_income": "영업이익",
    "net_income": "순이익",
}
UNSUPPORTED_METRICS = {
    "revenue_growth": ("매출 성장률", "ACTUAL_PERIOD_REQUIRED"),
    "operating_margin": ("영업이익률", "ACTUAL_PERIOD_REQUIRED"),
}


@dataclass(frozen=True, slots=True)
class ScreeningPublication:
    root: Path
    publication_id: str
    manifest_path: Path


def open_screening_identity_source(
    *, kind: str, root: Path | str, manifest_sha256: str
) -> Any:
    """Open one explicitly selected metric-identity source without fallback."""
    source_root = real_directory(Path(root), "screening metric identity source")
    if kind == LEGACY_IDENTITY_SOURCE_KIND:
        manifest_path = regular_file(
            source_root / MANIFEST, "legacy screening identity source manifest"
        )
        if sha256_file(manifest_path) != manifest_sha256:
            raise ValueError("screening identity source manifest differs from metric config")
        return ScreeningDatasetReader(source_root)
    if kind == GENERIC_IDENTITY_SOURCE_KIND:
        from sec_xbrl.screening.metric_identity import GenericMetricIdentityReader

        return GenericMetricIdentityReader(
            source_root, manifest_sha256=manifest_sha256
        )
    raise ValueError("unsupported explicit screening metric identity source kind")


def publish_screening_dataset(
    config_path: Path | str, destination: Path | str
) -> ScreeningPublication:
    """Validate governed inputs and atomically publish a screening dataset."""
    config_file = regular_file(Path(config_path), "screening preparation config")
    config = _validate_config(read_json(config_file, "screening preparation config"))
    destination_path = safe_new_destination(Path(destination), "screening publication")

    completion_root = real_directory(Path(config["completion_root"]), "completion publication")
    metadata_root = real_directory(Path(config["metadata_root"]), "metadata publication")
    completion = UniverseDeliveryReader(completion_root)
    metadata = CompanyMetadataReader(metadata_root)
    if completion.readiness.get("assessment_state") != "READY":
        raise ValueError("completion publication is not READY")
    if completion.readiness.get("dates", {}).get("financial_as_of") != config["financial_as_of"]:
        raise ValueError("completion financial-as-of differs from screening config")

    completion_rows = completion.readiness["companies"]
    completion_companies = {
        require_cik(row.get("cik"), "completion company CIK"): row
        for row in completion_rows
    }
    if len(completion_companies) != len(completion_rows):
        raise ValueError("completion publication contains duplicate companies")
    collection_sources = {
        require_cik(row.get("cik"), "completion source CIK"): row
        for row in completion.readiness.get("sources", {}).get("collection_companies", [])
    }
    if set(collection_sources) != set(completion_companies):
        raise ValueError("completion collection source membership is incomplete")
    metadata_candidates = metadata.list_companies()
    metadata_by_cik = {row.cik: row for row in metadata_candidates}
    requested_ciks = [company["cik"] for company in config["companies"]]
    if set(requested_ciks) != set(completion_companies):
        raise ValueError("screening config must exactly match completion company membership")

    company_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    snapshots: list[tuple[str, dict[str, Any]]] = []
    analysis_sources: list[dict[str, Any]] = []
    common_versions: dict[str, set[str]] = {
        "analysis_versions": set(),
        "source_publications": set(),
        "review_cutoffs": set(),
        "source_observed_times": set(),
        "metric_definition_versions": set(),
        "concept_mapping_versions": set(),
        "selection_rule_versions": set(),
        "classification_rule_versions": set(),
        "accession_version_ledger_ids": set(),
        "raw_concept_taxonomy_versions": set(),
    }

    for requested in config["companies"]:
        cik, ticker = requested["cik"], requested["ticker"]
        completion_row = completion_companies[cik]
        if completion_row.get("ticker") != ticker:
            raise ValueError(f"{ticker}: completion ticker/CIK identity mismatch")
        if not _ready_completion_company(completion_row):
            raise ValueError(f"{ticker}: completion company collection/identity is not ready")
        candidate = metadata_by_cik.get(cik)
        if candidate is None or ticker not in candidate.tickers:
            raise ValueError(f"{ticker}: metadata ticker/CIK identity mismatch")

        analysis_root = real_directory(Path(requested["analysis_root"]), f"{ticker} analysis")
        manifest_path = regular_file(analysis_root / "analysis_manifest.json", f"{ticker} manifest")
        client = open_analysis(analysis_root)
        manifest = client.manifest
        _verify_analysis_files(analysis_root, manifest)
        if manifest.get("period_mode") != "ANNUAL":
            raise ValueError(f"{ticker}: screening requires an ANNUAL analysis bundle")
        if set(manifest.get("companies", {})) != {ticker}:
            raise ValueError(f"{ticker}: analysis bundle must contain exactly the configured company")
        info = manifest["companies"][ticker]
        if info.get("as_of") != config["financial_as_of"]:
            raise ValueError(f"{ticker}: analysis financial-as-of mismatch")
        collection_source = collection_sources[cik]
        build = collection_source.get("build")
        if not isinstance(build, dict) or build.get("status") != "READY":
            raise ValueError(f"{ticker}: completion history build is not READY")
        history_sha = require_string(
            build.get("history_manifest_sha256"), f"{ticker} history manifest hash"
        )
        if (
            manifest.get("source_manifest_hashes", {}).get("history_manifest_sha256")
            != history_sha
            or info.get("source_publication") != build.get("publication")
        ):
            raise ValueError(f"{ticker}: annual analysis is not bound to completion history")

        overview = client.overview(ticker, view=VIEW, recent_quarters=100)
        prepared_rows = {row["row_id"]: row for row in overview["rows"]}
        requested_rows = [metric for metric in SUPPORTED_METRICS if metric in prepared_rows]
        if not requested_rows:
            raise ValueError(f"{ticker}: no approved annual core screening rows are prepared")
        snapshot = client.overview_snapshot(
            ticker, view=VIEW, recent_quarters=100, row_ids=requested_rows
        )
        if snapshot["context"].get("period_mode") != "ANNUAL":
            raise ValueError(f"{ticker}: U5 snapshot is not annual")
        snapshot_relative = f"source_snapshots/{cik}/{snapshot['snapshot_id']}.json"
        snapshots.append((snapshot_relative, snapshot))

        company_rows.append(
            {
                "cik": cik,
                "ticker": ticker,
                "name": candidate.name,
                "sic_code": candidate.sic_code,
                "sic_description": candidate.sic_description,
                "metadata_status": candidate.metadata_status,
                "metadata_observed_at": candidate.observed_at,
                "financial_prepared": True,
                "analysis_publication_id": manifest["publication_id"],
                "source_snapshot_id": snapshot["snapshot_id"],
            }
        )
        analysis_sources.append(
            {
                "ticker": ticker,
                "cik": cik,
                "root": str(analysis_root),
                "manifest_sha256": sha256_file(manifest_path),
                "publication_id": manifest["publication_id"],
                "source_publication": info["source_publication"],
                "history_manifest_sha256": history_sha,
            }
        )
        _add_version(common_versions["analysis_versions"], manifest.get("version"))
        _add_version(common_versions["source_publications"], info.get("source_publication"))
        _add_version(common_versions["review_cutoffs"], info.get("review_cutoff"))

        by_metric: dict[str, list[dict[str, Any]]] = {metric: [] for metric in SUPPORTED_METRICS}
        for cell in snapshot["cells"]:
            metric_id = cell["row_id"]
            observation = _observation(cik, ticker, metric_id, cell, snapshot)
            by_metric[metric_id].append(observation)
            observations.append(observation)
            _collect_observation_versions(common_versions, observation)
        for metric_id, label in SUPPORTED_METRICS.items():
            metric_observations = by_metric[metric_id]
            available = sum(row["availability_status"] == "AVAILABLE" for row in metric_observations)
            support_rows.append(
                {
                    "cik": cik,
                    "ticker": ticker,
                    "metric_id": metric_id,
                    "label": label,
                    "definition_version": "annual-core-reported-v1",
                    "execution_supported": available > 0,
                    "support_status": "AVAILABLE" if available else "UNAVAILABLE",
                    "available_periods": available,
                    "observed_periods": len(metric_observations),
                    "reason": None if available else "NO_AVAILABLE_REPORTED_ANNUAL_OBSERVATION",
                }
            )
        for metric_id, (label, reason) in UNSUPPORTED_METRICS.items():
            support_rows.append(
                {
                    "cik": cik,
                    "ticker": ticker,
                    "metric_id": metric_id,
                    "label": label,
                    "definition_version": "existing-investor-metric-policy-v1",
                    "execution_supported": False,
                    "support_status": "UNAVAILABLE",
                    "available_periods": 0,
                    "observed_periods": 0,
                    "reason": reason,
                }
            )

    _assert_unique(company_rows, ("cik",), "company")
    _assert_unique(support_rows, ("cik", "metric_id"), "metric support")
    for metric_id in SUPPORTED_METRICS:
        if not any(
            row["metric_id"] == metric_id and row["execution_supported"]
            for row in support_rows
        ):
            raise ValueError(f"screening metric has no available cohort coverage: {metric_id}")
    for support in support_rows:
        _add_version(
            common_versions["metric_definition_versions"],
            support.get("definition_version"),
        )
    _assert_unique(
        observations,
        ("cik", "metric_id", "fiscal_year", "period_class", "view"),
        "metric observation",
    )
    metadata_rows = [_metadata_row(row, set(requested_ciks)) for row in metadata_candidates]
    for row in metadata_rows:
        _add_version(common_versions["source_observed_times"], row.get("observed_at"))

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / COMPANIES, sorted(company_rows, key=lambda row: row["cik"]))
        write_json(staging / METADATA, metadata_rows)
        write_json(staging / SUPPORT, sorted(support_rows, key=_support_key))
        write_json(staging / OBSERVATIONS, sorted(observations, key=_observation_key))
        for relative, snapshot in snapshots:
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, snapshot)
        declared = sorted(
            [COMPANIES, METADATA, SUPPORT, OBSERVATIONS, *(relative for relative, _ in snapshots)]
        )
        files = {
            relative: {
                "sha256": sha256_file(staging / relative),
                "size": (staging / relative).stat().st_size,
            }
            for relative in declared
        }
        accuracy = completion.manifest.get("sources", {}).get("accuracy_assessment")
        if not isinstance(accuracy, dict) or accuracy.get("state") != "PASS":
            raise ValueError("completion publication lacks a passing parser accuracy assessment")
        versions = _version_manifest(common_versions, accuracy)
        identity = {
            "version": VERSION,
            "dataset_id": config["dataset_id"],
            "fixture_kind": config["fixture_kind"],
            "fixture_policy": config["fixture_policy"],
            "financial_as_of": config["financial_as_of"],
            "view": VIEW,
            "configured_ciks": sorted(requested_ciks),
            "counts": {
                "companies": len(company_rows),
                "metadata_candidates": len(metadata_rows),
                "metric_support": len(support_rows),
                "observations": len(observations),
                "source_snapshots": len(snapshots),
            },
            "sources": {
                "config": {"path": str(config_file), "sha256": sha256_file(config_file)},
                "completion": {
                    "root": str(completion_root),
                    "publication_id": completion.publication_id,
                    "manifest_sha256": sha256_file(
                        completion_root / "universe_delivery_manifest.json"
                    ),
                },
                "metadata": {
                    "root": str(metadata_root),
                    "publication_id": metadata.publication_id,
                    "manifest_sha256": sha256_file(metadata.manifest_path),
                },
                "analysis": sorted(analysis_sources, key=lambda row: row["cik"]),
            },
            "versions": versions,
            "files": files,
        }
        publication_id = "screening-dataset-" + digest_value(identity)[:24]
        write_json(staging / MANIFEST, {**identity, "publication_id": publication_id})
        ScreeningDatasetReader(staging, allow_staging=True)
        atomic_replace(staging, destination_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    reader = ScreeningDatasetReader(destination_path)
    return ScreeningPublication(destination_path, reader.publication_id, destination_path / MANIFEST)


class ScreeningDatasetReader:
    """Defensive read-only access to one immutable screening publication."""

    def __init__(self, root: Path | str, *, allow_staging: bool = False) -> None:
        self.root = real_directory(Path(root), "screening publication")
        if not allow_staging and self.root.name.startswith(".") and ".partial-" in self.root.name:
            raise ValueError("unpublished screening staging directory")
        self.manifest_path = contained_file(self.root, MANIFEST, "screening manifest")
        self._manifest_sha256 = sha256_file(self.manifest_path)
        self.manifest = read_json(self.manifest_path, "screening manifest")
        if self.manifest.get("version") != VERSION:
            raise ValueError("unsupported screening dataset version")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("invalid screening file manifest")
        actual = {
            str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file()
        }
        if actual != {MANIFEST, *files}:
            raise ValueError("screening publication file set mismatch")
        if any(path.is_symlink() for path in self.root.rglob("*")):
            raise ValueError("screening publication contains a symlink")
        for relative, info in files.items():
            path = contained_file(self.root, relative, "screening data")
            if (
                not isinstance(info, dict)
                or info.get("sha256") != sha256_file(path)
                or info.get("size") != path.stat().st_size
            ):
                raise ValueError(f"screening data integrity mismatch: {relative}")
        identity = {key: value for key, value in self.manifest.items() if key != "publication_id"}
        expected = "screening-dataset-" + digest_value(identity)[:24]
        if self.manifest.get("publication_id") != expected:
            raise ValueError("screening publication identity mismatch")
        self.publication_id = expected
        self.companies = self._list(COMPANIES)
        self.metadata = self._list(METADATA)
        self.metric_support = self._list(SUPPORT)
        self.observations = self._list(OBSERVATIONS)
        self._snapshot_cache: dict[str, dict[str, Any]] = {}
        self._validate_records()
        self._validate_external_sources()

    def verify_all(self) -> dict[str, Any]:
        self._verify_current_publication_files()
        return {
            "publication_id": self.publication_id,
            "dataset_id": self.manifest["dataset_id"],
            "fixture_kind": self.manifest["fixture_kind"],
            "fixture_policy": self.manifest.get("fixture_policy"),
            "financial_as_of": self.manifest["financial_as_of"],
            "counts": dict(self.manifest["counts"]),
            "state": "VERIFIED",
            "verification_scope": "CURRENT_PUBLICATION_FILES; SOURCE_ANCHORS_AT_READER_OPEN",
        }

    def source_snapshot(self, cik: str) -> dict[str, Any]:
        cik = require_cik(cik)
        if cik in self._snapshot_cache:
            return json.loads(canonical_json(self._snapshot_cache[cik]))
        company = self.company(cik)
        relative = f"source_snapshots/{cik}/{company['source_snapshot_id']}.json"
        path = contained_file(self.root, relative, "source snapshot")
        info = self.manifest["files"].get(relative)
        if (
            not isinstance(info, dict)
            or info.get("sha256") != sha256_file(path)
            or info.get("size") != path.stat().st_size
        ):
            raise ValueError("source snapshot changed after publication verification")
        snapshot = read_json(path, "source snapshot")
        if not isinstance(snapshot, dict):
            raise TypeError("source snapshot must be an object")
        self._snapshot_cache[cik] = snapshot
        return json.loads(canonical_json(snapshot))

    def company(self, cik: str) -> dict[str, Any]:
        cik = require_cik(cik)
        matches = [row for row in self.companies if row["cik"] == cik]
        if len(matches) != 1:
            raise ValueError("company is not uniquely prepared")
        return dict(matches[0])

    def _list(self, relative: str) -> list[dict[str, Any]]:
        value = read_json(contained_file(self.root, relative, relative), relative)
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ValueError(f"{relative} must contain a list of objects")
        return value

    def _verify_current_publication_files(self) -> None:
        if sha256_file(self.manifest_path) != self._manifest_sha256:
            raise ValueError("screening manifest changed after reader verification")
        files = self.manifest["files"]
        actual = {
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if path.is_file()
        }
        if actual != {MANIFEST, *files} or any(path.is_symlink() for path in self.root.rglob("*")):
            raise ValueError("screening publication file set changed after reader verification")
        for relative, info in files.items():
            path = contained_file(self.root, relative, "screening data")
            if info.get("sha256") != sha256_file(path) or info.get("size") != path.stat().st_size:
                raise ValueError("screening data changed after reader verification")

    def _validate_records(self) -> None:
        counts = self.manifest.get("counts", {})
        expected = {
            "companies": len(self.companies),
            "metadata_candidates": len(self.metadata),
            "metric_support": len(self.metric_support),
            "observations": len(self.observations),
        }
        if any(counts.get(key) != value for key, value in expected.items()):
            raise ValueError("screening record count mismatch")
        if counts.get("source_snapshots") != len(self.companies):
            raise ValueError("screening source snapshot count mismatch")
        _assert_unique(self.companies, ("cik",), "company")
        _assert_unique(self.metadata, ("cik",), "metadata")
        _assert_unique(self.metric_support, ("cik", "metric_id"), "metric support")
        _assert_unique(
            self.observations,
            ("cik", "metric_id", "fiscal_year", "period_class", "view"),
            "metric observation",
        )
        ciks = {row["cik"] for row in self.companies}
        if ciks != set(self.manifest.get("configured_ciks", [])):
            raise ValueError("screening company membership differs from manifest")
        if any(row.get("cik") not in ciks for row in self.metric_support + self.observations):
            raise ValueError("screening record references an unprepared company")
        for company in self.companies:
            require_cik(company.get("cik"), "screening company CIK")
            require_ticker(company.get("ticker"), "screening company ticker")
        for support in self.metric_support:
            require_string(support.get("metric_id"), "support metric ID")
            require_string(support.get("definition_version"), "support definition version")
            if type(support.get("execution_supported")) is not bool:
                raise TypeError("metric support execution flag must be boolean")
        for observation in self.observations:
            require_string(observation.get("metric_id"), "observation metric ID")
            if type(observation.get("fiscal_year")) is not int:
                raise TypeError("observation fiscal year must be an integer")
            if observation.get("availability_status") not in {"AVAILABLE", "UNAVAILABLE"}:
                raise ValueError("observation availability status is invalid")
        if any(
            row.get("financial_as_of") != self.manifest["financial_as_of"]
            for row in self.observations
        ):
            raise ValueError("screening observation financial-as-of mismatch")
        for company in self.companies:
            snapshot = self.source_snapshot(company["cik"])
            if snapshot.get("snapshot_id") != company.get("source_snapshot_id"):
                raise ValueError("source snapshot identity mismatch")
            material = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
            if digest_value(material) != snapshot["snapshot_id"]:
                raise ValueError("source snapshot canonical identity mismatch")
            expected = sorted(
                (
                    _observation(
                        company["cik"], company["ticker"], cell["row_id"], cell, snapshot
                    )
                    for cell in snapshot.get("cells", [])
                ),
                key=_observation_key,
            )
            actual = sorted(
                (row for row in self.observations if row["cik"] == company["cik"]),
                key=_observation_key,
            )
            if expected != actual:
                raise ValueError("screening observations differ from bound U5 source snapshot")

    def _validate_external_sources(self) -> None:
        sources = self.manifest.get("sources", {})
        if self.manifest.get("fixture_kind") == "SYNTHETIC_ERROR_FIXTURE":
            if self.manifest.get("fixture_policy") != "SELF_CONTAINED_TEST_ONLY":
                raise ValueError("synthetic screening fixture lacks its test-only policy")
            return
        if self.manifest.get("fixture_policy") is not None:
            raise ValueError("prepared screening dataset cannot use a synthetic fixture policy")
        if set(sources) != {"config", "completion", "metadata", "analysis"}:
            raise ValueError("prepared screening dataset lacks governed source anchors")

        config_source = sources.get("config")
        completion_source = sources.get("completion")
        metadata_source = sources.get("metadata")
        analysis_sources = sources.get("analysis")
        if (
            not isinstance(config_source, dict)
            or not isinstance(completion_source, dict)
            or not isinstance(metadata_source, dict)
            or not isinstance(analysis_sources, list)
        ):
            raise TypeError("prepared screening source anchors are malformed")
        config_path = regular_file(Path(config_source.get("path", "")), "screening config source")
        if sha256_file(config_path) != config_source.get("sha256"):
            raise ValueError("screening config source changed")
        config = _validate_config(read_json(config_path, "screening config source"))
        if (
            config["dataset_id"] != self.manifest["dataset_id"]
            or config["financial_as_of"] != self.manifest["financial_as_of"]
            or config["fixture_kind"] != self.manifest["fixture_kind"]
            or sorted(row["cik"] for row in config["companies"])
            != self.manifest["configured_ciks"]
        ):
            raise ValueError("screening config scope differs from publication")

        completion_root = real_directory(
            Path(completion_source.get("root", "")), "screening completion source"
        )
        completion_manifest = regular_file(
            completion_root / "universe_delivery_manifest.json", "screening completion manifest"
        )
        if sha256_file(completion_manifest) != completion_source.get("manifest_sha256"):
            raise ValueError("screening completion source changed")
        completion = UniverseDeliveryReader(completion_root)
        if (
            completion.publication_id != completion_source.get("publication_id")
            or completion.readiness.get("assessment_state") != "READY"
            or completion.readiness.get("dates", {}).get("financial_as_of")
            != self.manifest["financial_as_of"]
            or sorted(row["cik"] for row in completion.readiness["companies"])
            != self.manifest["configured_ciks"]
        ):
            raise ValueError("screening completion source scope changed")
        completion_by_cik = {
            require_cik(row.get("cik"), "completion company CIK"): row
            for row in completion.readiness["companies"]
        }
        if len(completion_by_cik) != len(completion.readiness["companies"]):
            raise ValueError("screening completion contains duplicate companies")
        accuracy = completion.manifest.get("sources", {}).get("accuracy_assessment")
        if not isinstance(accuracy, dict) or accuracy.get("state") != "PASS":
            raise ValueError("screening completion lacks a passing parser assessment")

        metadata_root = real_directory(
            Path(metadata_source.get("root", "")), "screening metadata source"
        )
        metadata_manifest = regular_file(
            metadata_root / "company_metadata_manifest.json", "screening metadata manifest"
        )
        if sha256_file(metadata_manifest) != metadata_source.get("manifest_sha256"):
            raise ValueError("screening metadata source changed")
        metadata = CompanyMetadataReader(metadata_root)
        if metadata.publication_id != metadata_source.get("publication_id"):
            raise ValueError("screening metadata publication identity changed")
        expected_metadata = [
            _metadata_row(row, set(self.manifest["configured_ciks"]))
            for row in metadata.list_companies()
        ]
        if expected_metadata != self.metadata:
            raise ValueError("screening metadata rows differ from governed source")

        config_by_cik = {row["cik"]: row for row in config["companies"]}
        source_by_cik = {row.get("cik"): row for row in analysis_sources if isinstance(row, dict)}
        if set(source_by_cik) != set(self.manifest["configured_ciks"]):
            raise ValueError("screening analysis source membership changed")
        company_by_cik = {row["cik"]: row for row in self.companies}
        observed_versions: dict[str, set[str]] = {
            "analysis_versions": set(),
            "source_publications": set(),
            "review_cutoffs": set(),
            "source_observed_times": set(),
            "metric_definition_versions": set(),
            "concept_mapping_versions": set(),
            "selection_rule_versions": set(),
            "classification_rule_versions": set(),
            "accession_version_ledger_ids": set(),
            "raw_concept_taxonomy_versions": set(),
        }
        for observation in self.observations:
            _collect_observation_versions(observed_versions, observation)
        for support in self.metric_support:
            _add_version(
                observed_versions["metric_definition_versions"],
                support.get("definition_version"),
            )
        for row in self.metadata:
            _add_version(observed_versions["source_observed_times"], row.get("observed_at"))
        for cik in self.manifest["configured_ciks"]:
            source = source_by_cik[cik]
            configured = config_by_cik[cik]
            if source.get("ticker") != configured["ticker"]:
                raise ValueError("screening analysis source company identity changed")
            if (
                company_by_cik[cik]["ticker"] != configured["ticker"]
                or completion_by_cik[cik].get("ticker") != configured["ticker"]
            ):
                raise ValueError("screening company ticker differs across governed sources")
            if not _ready_completion_company(completion_by_cik[cik]):
                raise ValueError("screening completion company is not fully prepared")
            root = real_directory(Path(source.get("root", "")), "screening analysis source")
            if root != Path(configured["analysis_root"]).resolve():
                raise ValueError("screening analysis source path differs from config")
            manifest_path = regular_file(root / "analysis_manifest.json", "screening analysis manifest")
            if sha256_file(manifest_path) != source.get("manifest_sha256"):
                raise ValueError("screening analysis source changed")
            client = open_analysis(root)
            _verify_analysis_files(root, client.manifest)
            ticker = source["ticker"]
            if (
                client.manifest.get("publication_id") != source.get("publication_id")
                or client.manifest.get("period_mode") != "ANNUAL"
                or set(client.manifest.get("companies", {})) != {ticker}
            ):
                raise ValueError("screening analysis publication scope changed")
            company_info = client.manifest["companies"][ticker]
            _add_version(observed_versions["analysis_versions"], client.manifest.get("version"))
            _add_version(observed_versions["source_publications"], source.get("source_publication"))
            _add_version(observed_versions["review_cutoffs"], company_info.get("review_cutoff"))
            if (
                company_info.get("as_of") != self.manifest["financial_as_of"]
                or company_info.get("source_publication") != source.get("source_publication")
                or client.manifest.get("source_manifest_hashes", {}).get(
                    "history_manifest_sha256"
                )
                != source.get("history_manifest_sha256")
            ):
                raise ValueError("screening analysis history binding changed")
            history = regular_file(
                Path(source["source_publication"]) / "history_manifest.json",
                "screening history manifest",
            )
            if sha256_file(history) != source.get("history_manifest_sha256"):
                raise ValueError("screening history source changed")
            packaged = self.source_snapshot(cik)
            prepared = client.overview_snapshot(
                ticker,
                view=VIEW,
                recent_quarters=100,
                row_ids=packaged["selection"]["row_ids"],
            )
            if prepared != packaged:
                raise ValueError("screening U5 snapshot differs from prepared analysis source")
            metadata_company = next(row for row in self.metadata if row["cik"] == cik)
            company = company_by_cik[cik]
            if (
                company["ticker"] not in metadata_company["tickers"]
                or company["name"] != metadata_company["name"]
                or company.get("sic_code") != metadata_company.get("sic_code")
                or company.get("sic_description") != metadata_company.get("sic_description")
            ):
                raise ValueError("screening company identity differs from metadata source")
        if self.manifest.get("versions") != _version_manifest(observed_versions, accuracy):
            raise ValueError("screening governed version vector differs from prepared sources")


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported screening preparation config")
    companies = value.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("screening config requires companies")
    normalized = []
    for index, row in enumerate(companies):
        if not isinstance(row, dict):
            raise TypeError("company config must be an object")
        normalized.append(
            {
                "ticker": require_ticker(row.get("ticker"), f"companies[{index}].ticker"),
                "cik": require_cik(row.get("cik"), f"companies[{index}].cik"),
                "analysis_root": require_string(
                    row.get("analysis_root"), f"companies[{index}].analysis_root"
                ),
            }
        )
    _assert_unique(normalized, ("ticker",), "configured ticker")
    _assert_unique(normalized, ("cik",), "configured CIK")
    fixture_kind = value.get("fixture_kind", "ACTUAL_PREPARED")
    if fixture_kind not in {
        "ACTUAL_PREPARED",
        "CACHE_FUTURE_UPDATE_FIXTURE",
        "SYNTHETIC_ERROR_FIXTURE",
    }:
        raise ValueError("unsupported fixture_kind")
    fixture_policy = value.get("fixture_policy")
    if fixture_kind == "SYNTHETIC_ERROR_FIXTURE":
        if fixture_policy != "SELF_CONTAINED_TEST_ONLY":
            raise ValueError("synthetic fixture requires SELF_CONTAINED_TEST_ONLY policy")
    elif fixture_policy is not None:
        raise ValueError("fixture_policy is only valid for a synthetic error fixture")
    return {
        "schema_version": CONFIG_VERSION,
        "dataset_id": require_string(value.get("dataset_id"), "dataset_id"),
        "fixture_kind": fixture_kind,
        "fixture_policy": fixture_policy,
        "financial_as_of": require_string(value.get("financial_as_of"), "financial_as_of"),
        "completion_root": require_string(value.get("completion_root"), "completion_root"),
        "metadata_root": require_string(value.get("metadata_root"), "metadata_root"),
        "companies": normalized,
    }


def _observation(
    cik: str,
    ticker: str,
    metric_id: str,
    cell: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    provenance = cell.get("provenance") or {}
    lineage = provenance.get("value_lineage") or {}
    status = cell.get("status")
    quality_status = cell.get("quality_status")
    value = cell.get("display_value")
    unit = cell.get("unit")
    dimensions = cell.get("dimensions") or []
    reason = cell.get("reason")
    available = (
        status == "REPORTED"
        and value is not None
        and quality_status != "BLOCK"
        and not dimensions
        and _is_usd_unit(unit)
    )
    if available:
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("screenable prepared value is not a decimal") from exc
        if not numeric.is_finite():
            raise ValueError("screenable prepared value is not finite")
    if not available:
        reason = reason or _unavailable_reason(status, value, quality_status, dimensions, unit)
    source_inputs = lineage.get("source_inputs") or [lineage]
    source_filings = sorted(
        {
            str(item.get("accession") or item.get("source_filing_id"))
            for item in source_inputs
            if item.get("accession") or item.get("source_filing_id")
        }
    )
    if available and (
        type(cell.get("fiscal_year")) is not int
        or not isinstance(cell.get("source_fact_id"), str)
        or not cell["source_fact_id"]
        or not source_filings
        or not isinstance(cell.get("start"), str)
        or not isinstance(cell.get("end"), str)
        or not isinstance(provenance, dict)
        or not provenance
        or not isinstance(lineage.get("concept_mapping_version"), str)
        or not isinstance(lineage.get("selection_rule_version"), str)
        or not isinstance(lineage.get("classification_rule_version"), str)
    ):
        raise ValueError("available screening value lacks governed source trace")
    return {
        "cik": cik,
        "ticker": ticker,
        "metric_id": metric_id,
        "metric_definition_version": "annual-core-reported-v1",
        "fiscal_year": cell.get("fiscal_year"),
        "fiscal_quarter": cell.get("fiscal_quarter"),
        "period_class": cell.get("period_class"),
        "period_start": cell.get("start"),
        "context_end_date": cell.get("end"),
        "context_end_convention": "SOURCE_CONTEXT_END_EXCLUSIVE",
        "view": snapshot["context"]["view"],
        "financial_as_of": snapshot["context"]["as_of"],
        "review_cutoff": snapshot["context"].get("review_cutoff"),
        "availability_status": "AVAILABLE" if available else "UNAVAILABLE",
        "unavailable_reason": None if available else reason,
        "value": str(value) if value is not None else None,
        "unit": unit,
        "dimensions": dimensions,
        "status": status,
        "quality_status": quality_status,
        "quality_reasons": cell.get("quality_reasons") or [],
        "quality_blocking": quality_status == "BLOCK",
        "mapping_relation": lineage.get("mapping_relation")
        or lineage.get("mapping_status")
        or "UNSPECIFIED_PREPARED_CORE",
        "concept_mapping_version": lineage.get("concept_mapping_version"),
        "concept_mapping_id": lineage.get("concept_mapping_id"),
        "selection_rule_version": lineage.get("selection_rule_version"),
        "classification_rule_version": lineage.get("classification_rule_version"),
        "accession_version_ledger_id": lineage.get("accession_version_ledger_id"),
        "raw_concept_taxonomy_version": lineage.get("raw_concept_taxonomy_version"),
        "basis_version": cell.get("basis_version"),
        "cell_id": cell.get("cell_id"),
        "source_fact_id": cell.get("source_fact_id"),
        "source_filings": source_filings,
        "source_snapshot_id": snapshot["snapshot_id"],
        "trace": provenance,
    }


def _collect_observation_versions(
    versions: dict[str, set[str]], observation: dict[str, Any]
) -> None:
    fields = {
        "metric_definition_versions": "metric_definition_version",
        "concept_mapping_versions": "concept_mapping_version",
        "selection_rule_versions": "selection_rule_version",
        "classification_rule_versions": "classification_rule_version",
        "accession_version_ledger_ids": "accession_version_ledger_id",
        "raw_concept_taxonomy_versions": "raw_concept_taxonomy_version",
    }
    for target, source in fields.items():
        value = observation.get(source)
        if isinstance(value, str) and value:
            versions[target].add(value)


def _add_version(target: set[str], value: Any) -> None:
    if isinstance(value, str) and value:
        target.add(value)


def _ready_completion_company(row: dict[str, Any]) -> bool:
    return (
        row.get("collection_state") == "READY"
        and row.get("held_filings") == row.get("selected_filings")
        and row.get("pending_filings") == 0
        and row.get("failed_filings") == 0
        and row.get("industry_status") == "CLASSIFIED"
    )


def _version_manifest(
    versions: dict[str, set[str]], accuracy: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {key: sorted(values) for key, values in versions.items()}
    result.update(
        {
            "parser_version": require_string(
                accuracy.get("parser_version"), "accuracy parser version"
            ),
            "parser_rule_version": require_string(
                accuracy.get("parser_rule_version"), "accuracy parser rule version"
            ),
            "parser_frozen_commit_sha": require_string(
                accuracy.get("frozen_commit_sha"), "accuracy parser frozen commit"
            ),
            "accuracy_assessment_sha256": require_string(
                accuracy.get("sha256"), "accuracy assessment hash"
            ),
        }
    )
    return result


def _is_usd_unit(unit: Any) -> bool:
    if not isinstance(unit, list) or len(unit) != 2:
        return False
    numerator, denominator = unit
    return numerator in (["iso4217:USD"], '["iso4217:USD"]') and denominator in (
        [],
        "[]",
    )


def _unavailable_reason(
    status: Any, value: Any, quality_status: Any, dimensions: Any, unit: Any
) -> str:
    if quality_status == "BLOCK":
        return "QUALITY_BLOCKED"
    if value is None:
        return "NO_PREPARED_VALUE"
    if status != "REPORTED":
        return "NOT_DIRECT_REPORTED"
    if dimensions:
        return "DIMENSIONED_CORE_NOT_SCREENABLE"
    if not _is_usd_unit(unit):
        return "UNIT_NOT_USD"
    return "UNAVAILABLE"


def _metadata_row(candidate: Any, prepared: set[str]) -> dict[str, Any]:
    return {
        "cik": candidate.cik,
        "name": candidate.name,
        "tickers": list(candidate.tickers),
        "exchanges": list(candidate.exchanges),
        "sic_code": candidate.sic_code,
        "sic_description": candidate.sic_description,
        "sic_status": "CLASSIFIED" if candidate.sic_code else "UNKNOWN_SIC",
        "metadata_status": candidate.metadata_status,
        "observed_at": candidate.observed_at,
        "financial_prepared": candidate.cik in prepared,
    }


def _verify_analysis_files(root: Path, manifest: dict[str, Any]) -> None:
    declared: set[str] = set()
    for company in manifest.get("companies", {}).values():
        for view in company.get("views", {}).values():
            for info in view.get("files", {}).values():
                if not isinstance(info, dict):
                    raise TypeError("analysis file declaration is malformed")
                relative = require_string(info.get("path"), "analysis data path")
                if relative in declared:
                    raise ValueError("analysis manifest declares a duplicate data path")
                path = contained_file(root, relative, "analysis data")
                if info.get("sha256") != sha256_file(path):
                    raise ValueError(f"analysis data integrity mismatch: {relative}")
                declared.add(relative)
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "analysis_manifest.json"
    }
    if declared != actual or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("analysis publication file set mismatch")


def _assert_unique(rows: list[dict[str, Any]], fields: tuple[str, ...], label: str) -> None:
    keys = [tuple(row.get(field) for field in fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {label} identity")


def _support_key(row: dict[str, Any]) -> tuple[str, str]:
    return row["cik"], row["metric_id"]


def _observation_key(row: dict[str, Any]) -> tuple[str, str, int, str, str]:
    return (
        row["cik"],
        row["metric_id"],
        int(row["fiscal_year"]),
        row["period_class"],
        row["view"],
    )
