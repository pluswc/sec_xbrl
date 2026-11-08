"""Append-only screening dataset v3 over annual v2 and quarterly metrics."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
    digest_value,
    read_json,
    real_directory,
    regular_file,
    require_string,
    safe_new_destination,
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
_V3_READERS: ContextVar[dict[Path, ScreeningDatasetV3Reader] | None] = ContextVar("v3_readers", default=None)


@contextmanager
def _share_v3_readers() -> Iterator[dict[Path, ScreeningDatasetV3Reader]]:
    """Share strictly opened v3 readers only within one service initialization."""
    readers: dict[Path, ScreeningDatasetV3Reader] = {}
    token = _V3_READERS.set(readers)
    try:
        yield readers
    finally:
        _V3_READERS.reset(token)


def publish_liability_addition(config_path: Path | str, destination: Path | str) -> Path:
    """Stage an immutable manifest for strict verification at first service open."""
    from sec_xbrl.financial_source_compatibility import use_source_compatibility
    from sec_xbrl.screening.liability_addition import read_approved_audit

    config_file = regular_file(Path(config_path), "liability addition config")
    config = _read_liability_config(config_file)
    destination_path = safe_new_destination(Path(destination), "liability addition")
    with use_source_compatibility(config["source_compatibility"]) as witness:
        _require_liability_witness(config, witness)
        parent = _read_liability_control(witness.controls["LIABILITY_PARENT_MANIFEST"])
        quarter = _read_liability_control(witness.controls["SUPERSEDED:QUARTERLY_SUCCESSOR"])
        read_approved_audit(
            witness.controls["LIABILITY_AUDIT"], cutoff=parent["financial_as_of"],
            company_count=quarter["universe"]["company_count"],
        )
        manifest = _liability_manifest(config_file, config, parent)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / MANIFEST, manifest)
        if _read_liability_config(config_file) != config or sha256_file(config_file) != manifest["config_sha256"]:
            raise ValueError("liability addition config changed during staging")
        safe_new_destination(destination_path, "liability addition")
        staging.rename(destination_path)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination_path


def _read_liability_control(pin: dict[str, str]) -> dict:
    data = Path(pin["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("liability addition parent control changed")
    return json.loads(data)


def _require_liability_witness(config: dict, witness: Any) -> None:
    from sec_xbrl.financial_source_compatibility import LIABILITY_VERSION

    if (
        witness is None or witness.payload["schema_version"] != LIABILITY_VERSION
        or witness.declaration != config["source_compatibility"]
        or witness.payload["liability_addition"] != config["liability_addition"]
    ):
        raise ValueError("liability addition requires exact V5 approval")


def _read_liability_config(path: Path) -> dict:
    from sec_xbrl.screening.liability_addition import CONFIG_VERSION as ADDITION_CONFIG_VERSION

    config = read_json(path, "liability addition config")
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "dataset_id", "source_compatibility", "liability_addition"}
        or config.get("schema_version") != ADDITION_CONFIG_VERSION
    ):
        raise ValueError("unsupported liability addition config")
    require_string(config.get("dataset_id"), "dataset_id")
    return config


def _liability_manifest(config_file: Path, config: dict, parent: dict) -> dict:
    if config["dataset_id"] == parent["dataset_id"]:
        raise ValueError("liability addition requires a new dataset ID")
    addition = config["liability_addition"]
    config_hash = sha256_file(config_file)
    identity = {
        "config_path": str(config_file), "config_sha256": config_hash, "config": config,
        "parent_publication_id": parent["publication_id"],
    }
    return {
        "schema_version": VERSION, "publication_id": "screening-dataset-" + digest_value(identity)[:24],
        "dataset_id": config["dataset_id"], "config_path": str(config_file),
        "config_sha256": config_hash, "config": config, "liability_addition": addition,
        "financial_as_of": parent["financial_as_of"], "fixture_kind": parent["fixture_kind"],
        "sources": copy.deepcopy(parent["sources"]), "parents": copy.deepcopy(parent["parents"]),
        "versions": {**parent["versions"], "liability_addition_audit_sha256": addition["audit"]["sha256"]},
    }


def publish_screening_dataset_v3(config_path: Path | str, destination: Path | str) -> Path:
    config_file = regular_file(Path(config_path), "v3 config")
    config = read_json(config_file, "v3 config")
    if not isinstance(config, dict) or config.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported screening v3 config")
    with _configured_compatibility(config):
        return _publish_screening_dataset_v3(config_file, config, destination)


def _publish_screening_dataset_v3(config_file: Path, config: dict, destination: Path | str) -> Path:
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
        manifest_path = regular_file(self.root / MANIFEST, "v3 manifest")
        self.manifest = read_json(manifest_path, "v3 manifest")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported screening v3 publication")
        self._manifest_sha256 = sha256_file(manifest_path)
        if "liability_addition" in self.manifest:
            self._open_liability_addition()
        else:
            self._open_combined()
        self.verify_all()
        readers = _V3_READERS.get()
        if readers is not None:
            readers[self.root] = self

    def _open_combined(self) -> None:
        annual_parent = self.manifest["parents"]["annual"]
        quarter_parent = self.manifest["parents"]["quarterly"]
        annual_root = real_directory(Path(annual_parent["root"]), "annual parent")
        quarter_root = real_directory(Path(quarter_parent["root"]), "quarter parent")
        if (
            sha256_file(annual_root / MANIFEST) != annual_parent["manifest_sha256"]
            or sha256_file(quarter_root / QUARTER_MANIFEST) != quarter_parent["manifest_sha256"]
        ):
            raise ValueError("screening v3 parent changed")
        config_path = regular_file(Path(self.manifest["config_path"]), "v3 config")
        config = read_json(config_path, "v3 config")
        if sha256_file(config_path) != self.manifest.get(
            "config_sha256"
        ) or config != self.manifest.get("config"):
            raise ValueError("screening v3 config changed")
        if config.get("source_compatibility") is not None and (
            annual_root != real_directory(Path(config["annual_dataset_root"]), "configured annual parent")
            or quarter_root != real_directory(Path(config["quarterly_metric_root"]), "configured quarter parent")
            or annual_parent["manifest_sha256"] != config["annual_manifest_sha256"]
            or quarter_parent["manifest_sha256"] != config["quarterly_manifest_sha256"]
        ):
            raise ValueError("v3 preserved parents differ from configured compatibility scope")
        with _configured_compatibility(config, quarter_path=quarter_root / QUARTER_MANIFEST):
            self.annual = ScreeningDatasetV2Reader(annual_root)
            self.quarterly = QuarterlyScreeningMetricReader(
                quarter_root, manifest_sha256=quarter_parent["manifest_sha256"]
            )
        if self.annual.publication_id != annual_parent["publication_id"]:
            raise ValueError("annual parent publication identity changed")
        if self.quarterly.publication_id != quarter_parent["publication_id"]:
            raise ValueError("quarterly parent publication identity changed")
        _verify_parent_binding(self.annual, self.quarterly)
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

    def _open_liability_addition(self) -> None:
        from sec_xbrl.financial_source_compatibility import (
            use_source_compatibility,
        )
        from sec_xbrl.screening.liability_addition import liability_rows

        config_file = regular_file(Path(self.manifest["config_path"]), "liability addition config")
        config = _read_liability_config(config_file)
        with use_source_compatibility(config["source_compatibility"]) as witness:
            _require_liability_witness(config, witness)
            parent_pin = witness.controls["LIABILITY_PARENT_MANIFEST"]
            parent_path = Path(parent_pin["path"])
            readers = _V3_READERS.get()
            parent = readers.get(parent_path.parent) if readers is not None else None
            if parent is None:
                parent = ScreeningDatasetV3Reader(parent_path.parent)
            if (
                parent._manifest_sha256 != parent_pin["sha256"]
                or parent.publication_id != config["liability_addition"]["parent_publication_id"]
                or self.manifest != _liability_manifest(config_file, config, parent.manifest)
            ):
                raise ValueError("liability addition publication or parent identity differs")
            definition, support, rows = liability_rows(parent, witness.controls["LIABILITY_AUDIT"])
        self.publication_id = self.manifest["publication_id"]
        self.annual = parent.annual
        self.quarterly = parent.quarterly
        self.companies = parent.companies
        self.metadata = parent.metadata
        self.metric_definitions = parent.metric_definitions
        self.metric_support = parent.metric_support
        self.observations = parent.observations
        self.quarter_definitions = [*parent.quarter_definitions, definition]
        self.quarter_support = [*parent.quarter_support, *support]
        self.quarter_observations = [*parent.quarter_observations, *rows]
        self.quarter_period_inventory = parent.quarter_period_inventory

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


@contextmanager
def _configured_compatibility(config: dict, *, quarter_path: Path | None = None) -> Iterator[None]:
    """Bind all four preserved publications to the explicitly configured scope."""
    from sec_xbrl.financial_source_compatibility import (
        CONTINUITY_VERSION,
        LATEST_VERSION,
        LIABILITY_VERSION,
        SUPERSEDING_VERSION,
        use_source_compatibility,
    )
    from sec_xbrl.metrics.statement_metric_evidence import CONTINUITY_CATALOG

    if quarter_path is None:
        quarter_path = Path(require_string(config.get("quarterly_metric_root"), "quarter root")) / QUARTER_MANIFEST
    with use_source_compatibility(config.get("source_compatibility")) as witness:
        quarter_manifest = read_json(regular_file(quarter_path, "quarterly manifest"))
        declares_successor = "quarterly_successor" in config
        if declares_successor != (quarter_manifest.get("catalog_version") == CONTINUITY_CATALOG):
            raise ValueError("v3 continuity quarter requires an explicit successor pin")
        if declares_successor:
            approval = None
            if witness is not None:
                schema = witness.payload["schema_version"]
                if schema == CONTINUITY_VERSION and config.get("source_compatibility") == witness.declaration:
                    approval = witness.controls.get("QUARTERLY_SUCCESSOR")
                elif (schema == LIABILITY_VERSION and config.get("source_compatibility")
                      == witness.controls["SUPERSEDED:SOURCE_COMPATIBILITY"]):
                    approval = witness.controls["SUPERSEDED:QUARTERLY_SUCCESSOR"]
            if (
                approval is None or config["quarterly_successor"] != approval
                or approval != {"path": str(quarter_path.absolute()), "sha256": sha256_file(quarter_path)}
            ):
                raise ValueError("v3 quarterly successor differs from approved continuity scope")
        if witness is not None:
            if witness.payload["schema_version"] not in {
                SUPERSEDING_VERSION, LATEST_VERSION, CONTINUITY_VERSION, LIABILITY_VERSION,
            }:
                raise ValueError("v3 preserved parents require superseding source compatibility")
            completed = witness.payload["supersedes"]["completed_publications"]
            annual_path = Path(config["annual_dataset_root"]) / MANIFEST
            annual = read_json(regular_file(annual_path, "preserved annual manifest"))
            identity = annual["config"]["identity_source"]
            paths = {
                "annual_dataset": annual_path,
                "annual_metrics": Path(annual["sources"]["metrics"]["root"]) / "screening_metric_manifest.json",
                "identity": Path(identity["root"]) / "generic_metric_identity_manifest.json",
            }
            if not declares_successor:
                paths["quarterly_metrics"] = quarter_path
            for name, path in paths.items():
                if completed[name] != {"path": str(path.absolute()), "sha256": sha256_file(path)}:
                    raise ValueError("v3 parent differs from preserved compatibility publication")
        yield
