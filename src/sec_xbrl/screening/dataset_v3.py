"""Append-only screening dataset v3 over annual v2 and quarterly metrics."""

from __future__ import annotations

import copy
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
    digest_value,
    read_json,
    real_directory,
    regular_file,
    require_string,
    sha256_file,
    write_json,
)
from sec_xbrl.screening.dataset_v2 import MANIFEST, ScreeningDatasetV2Reader
from sec_xbrl.screening.quarterly import MANIFEST as QUARTER_MANIFEST
from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader
from sec_xbrl.screening.verified_source_closure import (
    _discard as _discard_verified_source_closure,
)
from sec_xbrl.screening.verified_source_closure import (
    _publish_v3 as _publish_verified_v3,
)
from sec_xbrl.screening.verified_source_closure import _verify_v3_sources_once

VERSION = "screening-dataset-v3"
CONFIG_VERSION = "screening-prepare-config-v3"


def publish_screening_dataset_v3(config_path: Path | str, destination: Path | str) -> Path:
    config_file = regular_file(Path(config_path), "v3 config")
    config = read_json(config_file, "v3 config")
    if not isinstance(config, dict) or config.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported screening v3 config")
    destination_path = Path(destination).absolute()
    if destination_path.exists():
        raise ValueError("screening v3 destination must be new")
    annual_root = real_directory(
        Path(require_string(config.get("annual_dataset_root"), "annual root")), "annual v2"
    )
    quarter_root = real_directory(
        Path(require_string(config.get("quarterly_metric_root"), "quarter root")),
        "quarter metrics",
    )
    annual_hash = sha256_file(annual_root / MANIFEST)
    quarter_hash = sha256_file(quarter_root / QUARTER_MANIFEST)
    if annual_hash != config.get("annual_manifest_sha256") or quarter_hash != config.get(
        "quarterly_manifest_sha256"
    ):
        raise ValueError("screening v3 parent differs from pinned manifest")
    annual_manifest = read_json(
        regular_file(annual_root / MANIFEST, "annual v2 manifest"),
        "annual v2 manifest",
    )
    explicit_identity = (annual_manifest.get("config") or {}).get("identity_source")
    generic_single_pass = (
        isinstance(explicit_identity, dict)
        and explicit_identity.get("kind") == "GENERIC_METRIC_IDENTITY_ATTESTATION"
    )
    source_closure = None
    if generic_single_pass:
        annual, quarter, source_closure = _verify_v3_sources_once(
            config_path=config_file,
            config=config,
            annual_root=annual_root,
            quarter_root=quarter_root,
            destination=destination_path,
        )
    else:
        annual = ScreeningDatasetV2Reader(annual_root)
        quarter = QuarterlyScreeningMetricReader(
            quarter_root, manifest_sha256=quarter_hash
        )
    staging: Path | None = None
    try:
        _verify_parent_binding(annual, quarter)
        if [row["cik"] for row in annual.companies] != quarter.manifest["universe"]["ciks"]:
            raise ValueError("annual and quarterly company membership differ")
        identity = {
            "config_path": str(config_file),
            "config_sha256": sha256_file(config_file),
            "config": config,
            "annual_publication_id": annual.publication_id,
            "quarterly_publication_id": quarter.publication_id,
        }
        manifest = {
            "schema_version": VERSION,
            "publication_id": "screening-dataset-" + digest_value(identity)[:24],
            "dataset_id": require_string(config.get("dataset_id"), "dataset_id"),
            "fixture_kind": config.get("fixture_kind", "ACTUAL_PREPARED"),
            "financial_as_of": quarter.manifest["financial_as_of"],
            "config_path": str(config_file),
            "config_sha256": sha256_file(config_file),
            "config": config,
            "sources": {"metadata": copy.deepcopy(annual.manifest["sources"]["metadata"])},
            "versions": {
                "annual_publication_id": annual.publication_id,
                "quarterly_publication_id": quarter.publication_id,
            },
            "parents": {
                "annual": {
                    "root": str(annual_root),
                    "publication_id": annual.publication_id,
                    "manifest_sha256": annual_hash,
                },
                "quarterly": {
                    "root": str(quarter_root),
                    "publication_id": quarter.publication_id,
                    "manifest_sha256": quarter_hash,
                },
            },
        }
        if not generic_single_pass:
            destination_path.mkdir(parents=True)
            write_json(destination_path / MANIFEST, manifest)
            ScreeningDatasetV3Reader(destination_path)
            return destination_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        staging = (
            destination_path.parent
            / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
        )
        staging.mkdir()
        assert source_closure is not None
        write_json(staging / MANIFEST, manifest)
        _publish_verified_v3(
            source_closure,
            staging=staging,
            destination=destination_path,
        )
    except BaseException:
        if source_closure is not None:
            _discard_verified_source_closure(source_closure)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination_path


class ScreeningDatasetV3Reader:
    """Bind verified annual and quarterly parents without rewriting either publication."""

    def __init__(self, root: Path | str) -> None:
        self.root = real_directory(Path(root), "screening v3")
        self.manifest = read_json(regular_file(self.root / MANIFEST, "v3 manifest"), "v3 manifest")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported screening v3 publication")
        annual_parent = self.manifest["parents"]["annual"]
        quarter_parent = self.manifest["parents"]["quarterly"]
        annual_root = real_directory(Path(annual_parent["root"]), "annual parent")
        quarter_root = real_directory(Path(quarter_parent["root"]), "quarter parent")
        if (
            sha256_file(annual_root / MANIFEST) != annual_parent["manifest_sha256"]
            or sha256_file(quarter_root / QUARTER_MANIFEST) != quarter_parent["manifest_sha256"]
        ):
            raise ValueError("screening v3 parent changed")
        self.annual = ScreeningDatasetV2Reader(annual_root)
        self.quarterly = QuarterlyScreeningMetricReader(
            quarter_root, manifest_sha256=quarter_parent["manifest_sha256"]
        )
        if self.annual.publication_id != annual_parent["publication_id"]:
            raise ValueError("annual parent publication identity changed")
        if self.quarterly.publication_id != quarter_parent["publication_id"]:
            raise ValueError("quarterly parent publication identity changed")
        _verify_parent_binding(self.annual, self.quarterly)
        config_path = regular_file(Path(self.manifest["config_path"]), "v3 config")
        config = read_json(config_path, "v3 config")
        if sha256_file(config_path) != self.manifest.get(
            "config_sha256"
        ) or config != self.manifest.get("config"):
            raise ValueError("screening v3 config changed")
        identity = {
            "config_path": str(config_path),
            "config_sha256": sha256_file(config_path),
            "config": config,
            "annual_publication_id": self.annual.publication_id,
            "quarterly_publication_id": self.quarterly.publication_id,
        }
        if (
            self.manifest.get("publication_id")
            != "screening-dataset-" + digest_value(identity)[:24]
        ):
            raise ValueError("screening v3 publication identity differs")
        if self.manifest.get("dataset_id") != config.get("dataset_id"):
            raise ValueError("screening v3 dataset ID differs from config")
        if self.manifest.get("financial_as_of") != self.quarterly.manifest.get("financial_as_of"):
            raise ValueError("screening v3 financial as-of differs from parents")
        expected_versions = {
            "annual_publication_id": self.annual.publication_id,
            "quarterly_publication_id": self.quarterly.publication_id,
        }
        if self.manifest.get("versions") != expected_versions:
            raise ValueError("screening v3 version vector differs from parents")
        if (
            self.manifest.get("sources", {}).get("metadata")
            != self.annual.manifest["sources"]["metadata"]
        ):
            raise ValueError("screening v3 metadata source differs from annual parent")
        self.publication_id = require_string(
            self.manifest.get("publication_id"), "v3 publication ID"
        )
        self.companies = copy.deepcopy(self.annual.companies)
        self.metadata = copy.deepcopy(self.annual.metadata)
        self.metric_definitions = copy.deepcopy(self.annual.metric_definitions)
        self.metric_support = copy.deepcopy(self.annual.metric_support)
        self.observations = copy.deepcopy(self.annual.observations)
        self.quarter_definitions = copy.deepcopy(self.quarterly.definitions)
        self.quarter_support = copy.deepcopy(self.quarterly.support)
        self.quarter_observations = copy.deepcopy(self.quarterly.observations)
        self.quarter_period_inventory = copy.deepcopy(self.quarterly.period_inventory)
        self.verify_all()

    def company(self, cik: str) -> dict[str, Any]:
        return self.annual.company(cik)

    def verify_all(self) -> dict[str, Any]:
        if [row["cik"] for row in self.companies] != self.quarterly.manifest["universe"]["ciks"]:
            raise ValueError("screening v3 membership changed")
        return {
            "publication_id": self.publication_id,
            "dataset_id": self.manifest["dataset_id"],
            "fixture_kind": self.manifest["fixture_kind"],
            "financial_as_of": self.manifest["financial_as_of"],
            "company_count": len(self.companies),
            "quarter_definition_count": len(self.quarter_definitions),
            "quarter_observation_count": len(self.quarter_observations),
        }


def _verify_parent_binding(
    annual: ScreeningDatasetV2Reader, quarter: QuarterlyScreeningMetricReader
) -> None:
    annual_metrics = annual.manifest.get("sources", {}).get("metrics")
    declared = quarter.manifest.get("annual_parent")
    if not isinstance(annual_metrics, dict) or not isinstance(declared, dict):
        raise TypeError("screening v3 parent metric binding is missing")
    membership_hash = hashlib.sha256(
        ("\n".join(row["cik"] for row in annual.companies) + "\n").encode()
    ).hexdigest()
    if (
        declared.get("schema_version") != "screening-metric-publication-v1"
        or declared.get("publication_id") != annual_metrics.get("publication_id")
        or declared.get("manifest_sha256") != annual_metrics.get("manifest_sha256")
        or declared.get("company_membership_sha256") != membership_hash
        or quarter.manifest.get("financial_as_of") != annual.manifest.get("financial_as_of")
    ):
        raise ValueError("quarterly publication is not bound to the annual metric parent")
