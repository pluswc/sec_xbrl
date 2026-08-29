"""Layer 2's immutable-input materialization and atomic publication boundary.

This module deliberately does not select observations, create canonical maps,
or derive a metric.  Those are later Layer 2 milestones.  It gives those
producers one small, typed place to publish their governed records with a
reproducible run manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from types import MappingProxyType

LAYER2_CONTRACT_VERSION = "l2-materialization-v1"
DEFAULT_LAYER2_ROOT = Path("data/processed/analytical/layer2")
LOGICAL_DATASETS = frozenset(
    {
        "period_observation",
        "period_observation_exclusion",
        "company_concept_map",
        "company_axis_map",
        "company_member_map",
        "structural_change",
        "analytical_fact",
        "recast_evidence",
        "capability_inventory",
        "metric_input_candidate",
        "metric_input_compatibility",
        "annual_series_candidate",
        "current_series_candidate",
        "series_candidate_exclusion",
    }
)
_ANALYTICAL_SOURCE_TYPES = frozenset(
    {"REPORTED", "RECAST_REPORTED", "DERIVED_RECAST", "UNAVAILABLE"}
)
_MAPPING_DATASETS = frozenset({"company_concept_map", "company_axis_map", "company_member_map"})
_MAPPING_RELATIONS = frozenset({"SAME", "RENAMED", "RECAST", "SPLIT", "MERGED", "UNCERTAIN"})
_STRUCTURAL_CHANGE_EVENTS = frozenset(
    {
        "NEW_CONCEPT",
        "NEW_AXIS",
        "NEW_MEMBER",
        "MEMBER_RENAME",
        "SEGMENT_RECAST",
        "SPLIT",
        "MERGE",
        "ROLE_RESTRUCTURE",
        "UNKNOWN_CHANGE",
    }
)


class Layer2MaterializationError(RuntimeError):
    """Raised when a Layer 2 run cannot pass its publication contract."""


class Layer2PublicationValidationError(Layer2MaterializationError):
    """Raised when an on-disk Layer 2 publication is not safe to consume.

    This is deliberately distinct from producer-time validation so consumer
    adapters can fail closed when a publication has been copied, altered, or
    only partially published.
    """


@dataclass(frozen=True, slots=True)
class Layer1SnapshotInput:
    """Immutable identity of one Layer 1 snapshot consumed by a run."""

    cik: str
    accession: str
    form: str
    filed_date: str
    report_date: str
    snapshot_id: str
    manifest_sha256: str
    parser_version: str | None = None


@dataclass(frozen=True, slots=True)
class Layer2RuleVersions:
    """All policy/evidence versions that can affect an analytical result."""

    period_rule_version: str
    mapping_version: str
    recast_evidence_version: str
    selection_rule_version: str


@dataclass(frozen=True, slots=True)
class Layer2Run:
    """Reproducible identity and complete input declaration for one run."""

    run_version: str
    corpus_run_id: str
    inputs: tuple[Layer1SnapshotInput, ...]
    rules: Layer2RuleVersions
    contract_version: str = LAYER2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.run_version or "/" in self.run_version or "\\" in self.run_version:
            raise Layer2MaterializationError("run_version must be a non-path identifier")
        if not self.corpus_run_id:
            raise Layer2MaterializationError("corpus_run_id is required")
        if not self.inputs:
            raise Layer2MaterializationError("a Layer 2 run requires at least one Layer 1 input")
        identities = {(row.cik, row.accession, row.snapshot_id) for row in self.inputs}
        if len(identities) != len(self.inputs):
            raise Layer2MaterializationError("duplicate Layer 1 snapshot input identity")
        required_input_fields = (
            "cik",
            "accession",
            "form",
            "filed_date",
            "report_date",
            "snapshot_id",
            "manifest_sha256",
        )
        for row in self.inputs:
            missing = [field for field in required_input_fields if not getattr(row, field)]
            if missing:
                raise Layer2MaterializationError(
                    f"Layer 1 input is missing required provenance: {missing}"
                )

    @property
    def fingerprint(self) -> str:
        """Stable digest of every input and version that affects this run."""
        return _sha256_json(
            {
                "contract_version": self.contract_version,
                "run_version": self.run_version,
                "corpus_run_id": self.corpus_run_id,
                "inputs": _sorted_dicts(asdict(item) for item in self.inputs),
                "rules": asdict(self.rules),
            }
        )


@dataclass(frozen=True, slots=True)
class Layer2Publication:
    """Published run location and deterministic output identity."""

    run_root: Path
    manifest_path: Path
    fingerprint: str
    output_counts: Mapping[str, int]
    reused_existing: bool


@dataclass(frozen=True, slots=True)
class VerifiedLayer2Publication:
    """Immutable, manifest-verified Layer 2 publication for read-only consumers."""

    run_root: Path
    manifest_path: Path
    identity: Mapping[str, str]
    input_ciks: tuple[str, ...]
    datasets: Mapping[str, tuple[Mapping[str, Any], ...]]

    def records(self, dataset: str) -> tuple[dict[str, Any], ...]:
        """Return independent copies of one verified logical dataset."""
        if dataset not in LOGICAL_DATASETS:
            raise Layer2PublicationValidationError(f"unknown Layer 2 dataset: {dataset}")
        return tuple(dict(row) for row in self.datasets.get(dataset, ()))


class Layer2PublicationReader:
    """Fail-closed reader for atomically published canonical-JSONL Layer 2 runs.

    This reader validates the same logical rows and canonical content hashes as
    ``Layer2Publisher`` before exposing records.  It is a JSONL publication
    adapter, not a future DB or Parquet adapter.
    """

    manifest_name = "layer2_run_manifest.json"

    def load(self, run_root: Path) -> VerifiedLayer2Publication:
        root = Path(run_root)
        if not root.is_dir() or root.is_symlink():
            raise Layer2PublicationValidationError(f"unpublished or invalid Layer 2 run root: {root}")
        if root.name == ".staging" or ".partial-" in root.name:
            raise Layer2PublicationValidationError(f"partial Layer 2 publication is not consumable: {root}")
        manifest_path = root / self.manifest_name
        manifest = _read_publication_manifest(manifest_path)
        run = _run_from_manifest(manifest)
        if root.name != run.run_version:
            raise Layer2PublicationValidationError("Layer 2 publication root does not match manifest run_version")
        if manifest.get("run_fingerprint") != run.fingerprint:
            raise Layer2PublicationValidationError("Layer 2 manifest fingerprint does not match its declaration")
        if manifest.get("contract_version") != LAYER2_CONTRACT_VERSION:
            raise Layer2PublicationValidationError("unsupported Layer 2 materialization contract version")
        if manifest.get("storage_format") != "canonical-jsonl-v1":
            raise Layer2PublicationValidationError("unsupported Layer 2 publication storage format")
        _validate_manifest_shape(manifest)
        datasets = _read_published_datasets(root, manifest, run)
        try:
            counts = _validate_candidate(run, datasets)
        except Layer2MaterializationError as exc:
            raise Layer2PublicationValidationError("Layer 2 publication rows fail contract validation") from exc
        declared_counts = manifest["output_counts"]
        if counts != declared_counts:
            raise Layer2PublicationValidationError("Layer 2 publication row counts do not match manifest")
        hashes = _dataset_hashes(datasets)
        if hashes != manifest["output_content_sha256"]:
            raise Layer2PublicationValidationError("Layer 2 publication content hashes do not match manifest")
        identity = {
            "layer2_run_version": run.run_version,
            "layer2_run_fingerprint": run.fingerprint,
            "layer2_contract_version": run.contract_version,
            "layer2_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
        copied = MappingProxyType(
            {
                name: tuple(MappingProxyType(dict(row)) for row in rows)
                for name, rows in datasets.items()
            }
        )
        return VerifiedLayer2Publication(
            run_root=root,
            manifest_path=manifest_path,
            identity=MappingProxyType(identity),
            input_ciks=tuple(sorted(item.cik for item in run.inputs)),
            datasets=copied,
        )


@dataclass(frozen=True, slots=True)
class _RunManifest:
    contract_version: str
    run_version: str
    corpus_run_id: str
    run_fingerprint: str
    inputs: tuple[Layer1SnapshotInput, ...]
    rules: Layer2RuleVersions
    output_counts: Mapping[str, int]
    output_content_sha256: Mapping[str, str]
    validation: Mapping[str, str]
    published_at: str
    storage_format: str = "canonical-jsonl-v1"

    def as_json(self) -> str:
        payload = asdict(self)
        payload["inputs"] = _sorted_dicts(payload["inputs"])
        payload["output_counts"] = dict(sorted(payload["output_counts"].items()))
        payload["output_content_sha256"] = dict(sorted(payload["output_content_sha256"].items()))
        payload["validation"] = dict(sorted(payload["validation"].items()))
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class Layer2Publisher:
    """Validate a complete Layer 2 candidate, then atomically publish it.

    The M0 file format is canonical JSON Lines so the contract can be tested
    without an engine-specific dependency.  Dataset names and rows are logical
    contracts; later milestones may add a Parquet writer without changing the
    run manifest, keys, or atomic directory publication rule.
    """

    manifest_name = "layer2_run_manifest.json"

    def __init__(self, root: Path = DEFAULT_LAYER2_ROOT) -> None:
        self.root = Path(root)

    def publish(
        self,
        run: Layer2Run,
        datasets: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> Layer2Publication:
        """Publish only a fully validated candidate or leave no output behind."""
        normalized = _normalize_datasets(datasets)
        counts = _validate_candidate(run, normalized)
        content_hashes = _dataset_hashes(normalized)
        destination = self.root / run.run_version
        existing = self._existing_publication(destination, run, counts, content_hashes)
        if existing is not None:
            return existing

        self.root.mkdir(parents=True, exist_ok=True)
        staging_root = self.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{run.run_version}.partial-", dir=staging_root))
        try:
            _write_datasets(temporary, normalized)
            manifest = _RunManifest(
                contract_version=run.contract_version,
                run_version=run.run_version,
                corpus_run_id=run.corpus_run_id,
                run_fingerprint=run.fingerprint,
                inputs=run.inputs,
                rules=run.rules,
                output_counts=counts,
                output_content_sha256=content_hashes,
                validation={
                    "ANALYTICAL_FACT_LINEAGE": "SUCCESS",
                    "RUN_INPUT_AND_VERSION_MANIFEST": "SUCCESS",
                    "DETERMINISTIC_OUTPUT_IDENTITY": "SUCCESS",
                    "ATOMIC_PUBLICATION": "SUCCESS",
                },
                published_at=datetime.now(UTC).isoformat(),
            )
            (temporary / self.manifest_name).write_text(manifest.as_json(), encoding="utf-8")
            _validate_written_candidate(temporary, self.manifest_name, counts)
            # A final existence check makes accidental overwrite fail closed.
            if destination.exists():
                existing = self._existing_publication(destination, run, counts, content_hashes)
                if existing is not None:
                    return existing
                raise Layer2MaterializationError(
                    f"published run version already exists: {destination}"
                )
            os.replace(temporary, destination)
            return Layer2Publication(
                run_root=destination,
                manifest_path=destination / self.manifest_name,
                fingerprint=run.fingerprint,
                output_counts=counts,
                reused_existing=False,
            )
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _existing_publication(
        self,
        destination: Path,
        run: Layer2Run,
        counts: Mapping[str, int],
        content_hashes: Mapping[str, str],
    ) -> Layer2Publication | None:
        if not destination.exists():
            return None
        manifest_path = destination / self.manifest_name
        if not manifest_path.is_file():
            raise Layer2MaterializationError(f"unpublished or partial Layer 2 run: {destination}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Layer2MaterializationError(
                f"invalid Layer 2 run manifest: {manifest_path}"
            ) from exc
        if manifest.get("run_fingerprint") != run.fingerprint:
            raise Layer2MaterializationError(
                "run_version already belongs to different inputs or rule versions; use a new run_version"
            )
        if manifest.get("output_counts") != dict(sorted(counts.items())):
            raise Layer2MaterializationError("run_version already has different output counts")
        if manifest.get("output_content_sha256") != dict(sorted(content_hashes.items())):
            raise Layer2MaterializationError(
                "identical input/version declaration produced different output values or keys"
            )
        _validate_written_candidate(destination, self.manifest_name, counts)
        return Layer2Publication(
            run_root=destination,
            manifest_path=manifest_path,
            fingerprint=run.fingerprint,
            output_counts=counts,
            reused_existing=True,
        )


def _normalize_datasets(
    datasets: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    unknown = set(datasets) - LOGICAL_DATASETS
    if unknown:
        raise Layer2MaterializationError(f"unknown Layer 2 logical datasets: {sorted(unknown)}")
    if "analytical_fact" not in datasets and not (
        {
            "annual_series_candidate",
            "current_series_candidate",
            "capability_inventory",
            "metric_input_candidate",
            "metric_input_compatibility",
        }
        & set(datasets)
    ):
        raise Layer2MaterializationError(
            "candidate requires analytical_fact or an L2-M3 series candidate dataset"
        )
    return {name: tuple(dict(row) for row in rows) for name, rows in datasets.items()}


def _validate_candidate(
    run: Layer2Run, datasets: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, int]:
    input_ciks = {row.cik for row in run.inputs}
    counts: dict[str, int] = {}
    mappings_by_id: dict[str, Mapping[str, Any]] = {}
    recast_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in datasets.get("recast_evidence", ()):
        _validate_recast_evidence(row)
        recast_by_id.setdefault(str(row["recast_evidence_id"]), []).append(row)
    for dataset in _MAPPING_DATASETS:
        for row in datasets.get(dataset, ()):
            _validate_company_mapping(dataset, row)
            mapping_id = str(row["mapping_id"])
            if mapping_id in mappings_by_id:
                raise Layer2MaterializationError(
                    f"duplicate company mapping identity across datasets: {mapping_id}"
                )
            mappings_by_id[mapping_id] = row
    for dataset, rows in datasets.items():
        seen_ids: set[str] = set()
        for row in rows:
            if not row.get("cik"):
                raise Layer2MaterializationError(f"{dataset} row is missing cik")
            if str(row["cik"]) not in input_ciks:
                raise Layer2MaterializationError(
                    f"{dataset} row references CIK outside declared inputs"
                )
            record_id = _record_id(dataset, row)
            if record_id in seen_ids:
                raise Layer2MaterializationError(
                    f"duplicate {dataset} record identity: {record_id}"
                )
            seen_ids.add(record_id)
            if dataset == "analytical_fact":
                _validate_analytical_fact(row, recast_by_id)
            elif dataset == "recast_evidence":
                # Checked before facts so evidence references can be validated
                # regardless of logical-dataset insertion order.
                pass
            elif dataset in {"annual_series_candidate", "current_series_candidate"}:
                _validate_series_candidate(dataset, row)
            elif dataset in _MAPPING_DATASETS:
                # This was validated first so structural-change rows can only
                # link to a real map in the same atomic candidate.
                pass
            elif dataset == "structural_change":
                _validate_structural_change(row, mappings_by_id)
            elif dataset == "capability_inventory":
                _validate_capability_inventory(row)
            elif dataset == "metric_input_candidate":
                _validate_metric_input_candidate(row)
            elif dataset == "metric_input_compatibility":
                _validate_metric_input_compatibility(row)
            try:
                _canonical_json(row)
            except (TypeError, ValueError) as exc:
                raise Layer2MaterializationError(
                    f"{dataset} row is not canonical JSON serializable"
                ) from exc
        counts[dataset] = len(rows)
    if "capability_inventory" in datasets:
        covered_ciks = {str(row.get("cik")) for row in datasets["capability_inventory"]}
        missing_ciks = sorted(input_ciks - covered_ciks)
        if missing_ciks:
            raise Layer2MaterializationError(
                "capability_inventory requires explicit coverage for every declared input CIK: "
                + ", ".join(missing_ciks)
            )
    return dict(sorted(counts.items()))


def _validate_analytical_fact(
    row: Mapping[str, Any], recast_by_id: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
) -> None:
    if not row.get("analytical_fact_id"):
        raise Layer2MaterializationError("analytical_fact requires analytical_fact_id")
    source_type = str(row.get("source_type") or "")
    if source_type not in _ANALYTICAL_SOURCE_TYPES:
        raise Layer2MaterializationError(
            f"unsupported analytical_fact source_type: {source_type!r}"
        )
    has_numeric = row.get("value_numeric") is not None
    selected_fact_id = row.get("selected_fact_id")
    unavailable_reason = row.get("unavailable_reason")
    if source_type == "UNAVAILABLE":
        if has_numeric or selected_fact_id:
            raise Layer2MaterializationError(
                "UNAVAILABLE analytical_fact cannot have numeric value or selected_fact_id"
            )
        if not unavailable_reason:
            raise Layer2MaterializationError(
                "UNAVAILABLE analytical_fact requires unavailable_reason"
            )
        return
    if row.get("view") not in {"AS_FILED", "CURRENT_COMPARABLE"}:
        raise Layer2MaterializationError("analytical_fact has unsupported view")
    if source_type != "DERIVED_RECAST" and not selected_fact_id:
        raise Layer2MaterializationError("analytical_fact requires selected raw Fact ID")
    if unavailable_reason:
        raise Layer2MaterializationError("available analytical_fact cannot have unavailable_reason")
    if has_numeric and not selected_fact_id and source_type != "DERIVED_RECAST":
        raise Layer2MaterializationError("numeric analytical_fact requires selected raw Fact ID")
    required = ("view", "as_of_date", "selection_rule_version")
    missing = [key for key in required if not row.get(key)]
    if missing:
        raise Layer2MaterializationError(f"analytical_fact missing selection provenance: {missing}")
    if source_type == "RECAST_REPORTED" and not row.get("recast_evidence_id"):
        raise Layer2MaterializationError(
            "RECAST_REPORTED analytical_fact requires recast_evidence_id"
        )
    if source_type == "DERIVED_RECAST" and (
        not row.get("source_fact_ids")
        or not row.get("derivation_rule_version")
        or not row.get("derived_observation_id")
        or not row.get("recast_evidence_id")
    ):
        raise Layer2MaterializationError(
            "DERIVED_RECAST analytical_fact requires source Fact IDs and derivation rule version"
        )
    if source_type in {"RECAST_REPORTED", "DERIVED_RECAST"}:
        _validate_recast_reference(row, recast_by_id or {})


def _validate_recast_reference(
    fact: Mapping[str, Any], evidence_by_id: Mapping[str, Sequence[Mapping[str, Any]]]
) -> None:
    """Require a selected recast value to resolve inside this atomic run."""
    evidence_id = str(fact.get("recast_evidence_id") or "")
    candidates = evidence_by_id.get(evidence_id, ())
    for evidence in candidates:
        common = ("cik", "source_filing_id", "basis_version")
        if any(fact.get(key) != evidence.get(key) for key in common):
            continue
        if fact.get("source_type") == "RECAST_REPORTED":
            if fact.get("selected_fact_id") == evidence.get("source_raw_fact_id"):
                return
        elif fact.get("derived_observation_id") == evidence.get(
            "source_derived_observation_id"
        ) and evidence.get("source_raw_fact_id") in set(fact.get("source_fact_ids") or ()):
            return
    raise Layer2MaterializationError(
        "recast analytical_fact must resolve to compatible recast_evidence in the same candidate"
    )


def _validate_recast_evidence(row: Mapping[str, Any]) -> None:
    """Keep the published evidence table useful independently of its adapter."""
    required = (
        "recast_evidence_id",
        "source_filing_id",
        "source_raw_fact_id",
        "target_period_key",
        "basis_version",
        "evidence_kind",
        "source_document",
        "source_locator",
        "prior_source_filing_ids",
        "evidence_version",
    )
    missing = [key for key in required if not row.get(key)]
    if missing:
        raise Layer2MaterializationError(f"recast_evidence missing provenance: {missing}")
    if row.get("explicitly_represented") is not True:
        raise Layer2MaterializationError(
            "recast_evidence requires explicit re-presentation evidence"
        )
    if row.get("source_derived_observation_id") is not None and not row.get("source_raw_fact_id"):
        raise Layer2MaterializationError(
            "derived recast evidence requires a compatible source raw Fact"
        )


def _validate_series_candidate(dataset: str, row: Mapping[str, Any]) -> None:
    """Keep pre-selection M3 candidates traceable and period-safe."""
    expected_type = "ANNUAL" if dataset == "annual_series_candidate" else "CURRENT"
    required = (
        "series_candidate_id",
        "series_type",
        "series_status",
        "company_canonical_concept_id",
        "company_canonical_dimension_key",
        "unit_semantics",
        "actual_period_boundaries",
        "actual_period_key",
        "period_class",
        "series_key",
        "source_period_observation_id",
        "source_filing_id",
        "mapping_version",
        "mapping_evidence",
        "classification_rule_version",
        "series_rule_version",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(f"{dataset} missing series provenance: {missing}")
    if row["series_type"] != expected_type:
        raise Layer2MaterializationError(f"{dataset} has incompatible series_type")
    if row["series_status"] not in {"CANDIDATE", "REVIEW_REQUIRED"}:
        raise Layer2MaterializationError(f"{dataset} has unsupported series_status")
    if row["series_status"] == "REVIEW_REQUIRED" and not row.get("unavailable_reason"):
        raise Layer2MaterializationError(f"{dataset} review-required row needs unavailable_reason")
    if not row.get("source_fact_id") and (
        not row.get("source_fact_ids")
        or not row.get("derivation_rule_version")
        or not row.get("formula")
    ):
        raise Layer2MaterializationError(
            f"{dataset} requires source_fact_id or complete derived source lineage"
        )


def _validate_company_mapping(dataset: str, row: Mapping[str, Any]) -> None:
    """Reject a map that cannot explain its raw-to-canonical decision."""
    expected_entity = dataset.removeprefix("company_").removesuffix("_map")
    required = (
        "mapping_id",
        "source_raw_id",
        "source_filing_id",
        "company_canonical_id",
        "valid_from_filing_id",
        "relation",
        "method",
        "evidence",
        "mapping_version",
        "continuity_break",
        "review_required",
        "review_state",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(f"{dataset} missing mapping provenance: {missing}")
    if row.get("entity_type") != expected_entity:
        raise Layer2MaterializationError(f"{dataset} has incompatible entity_type")
    if str(row["relation"]) not in _MAPPING_RELATIONS:
        raise Layer2MaterializationError(f"{dataset} has unsupported mapping relation")
    if bool(row["review_required"]) != (row.get("review_state") == "REVIEW_REQUIRED"):
        raise Layer2MaterializationError(f"{dataset} review state is inconsistent")
    if str(row["relation"]) == "UNCERTAIN" and not row["review_required"]:
        raise Layer2MaterializationError(f"{dataset} cannot silently coalesce unresolved mapping")


def _validate_structural_change(
    row: Mapping[str, Any], mappings_by_id: Mapping[str, Mapping[str, Any]]
) -> None:
    required = (
        "event_id",
        "filing_id",
        "source_raw_id",
        "company_canonical_id",
        "mapping_id",
        "event_type",
        "valid_from_filing_id",
        "mapping_version",
        "continuity_break",
        "review_required",
        "review_state",
        "evidence",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(f"structural_change missing provenance: {missing}")
    if str(row["event_type"]) not in _STRUCTURAL_CHANGE_EVENTS:
        raise Layer2MaterializationError("structural_change has unsupported event_type")
    if bool(row["review_required"]) != (row.get("review_state") == "REVIEW_REQUIRED"):
        raise Layer2MaterializationError("structural_change review state is inconsistent")
    mapping = mappings_by_id.get(str(row["mapping_id"]))
    if mapping is None:
        raise Layer2MaterializationError(
            "structural_change mapping_id must resolve to a mapping row in the same candidate"
        )
    linked_fields = (
        "cik",
        "source_raw_id",
        "source_raw_concept_id",
        "company_canonical_id",
        "valid_from_filing_id",
        "valid_from_period",
        "mapping_version",
        "continuity_break",
        "review_required",
        "review_state",
    )
    mismatched = [key for key in linked_fields if row.get(key) != mapping.get(key)]
    if row.get("filing_id") != mapping.get("source_filing_id"):
        mismatched.append("filing_id/source_filing_id")
    if row.get("entity_type") != mapping.get("entity_type"):
        mismatched.append("entity_type")
    if mismatched:
        raise Layer2MaterializationError(
            f"structural_change does not match linked mapping fields: {mismatched}"
        )


def _validate_capability_inventory(row: Mapping[str, Any]) -> None:
    """Require capability status and drill-down evidence to be explicit."""
    required = (
        "capability_inventory_id",
        "capability_type",
        "capability_status",
        "period_classes",
        "series_types",
        "source_fact_ids",
        "source_filing_ids",
        "source_role_ids",
        "source_disclosure_ids",
        "capability_inventory_version",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(f"capability_inventory missing provenance: {missing}")
    if row["capability_status"] not in {
        "AVAILABLE",
        "PROCESSING_UNAVAILABLE",
        "MAPPING_REVIEW_REQUIRED",
        "NOT_COMPARABLE",
    }:
        raise Layer2MaterializationError("capability_inventory has unsupported capability_status")
    if row["capability_status"] == "AVAILABLE" and row.get("status_reason") is not None:
        raise Layer2MaterializationError(
            "available capability_inventory row cannot have status_reason"
        )
    if row["capability_status"] != "AVAILABLE" and not row.get("status_reason"):
        raise Layer2MaterializationError(
            "unavailable capability_inventory row requires status_reason"
        )
    if row["capability_type"] not in {"CONCEPT", "DIMENSION_MEMBER", "COMPANY_COVERAGE"}:
        raise Layer2MaterializationError("capability_inventory has unsupported capability_type")
    if row["capability_type"] == "DIMENSION_MEMBER" and (
        not row.get("axis_raw_concept_id") or not row.get("member_raw_concept_id")
    ):
        raise Layer2MaterializationError("dimension capability requires observed axis and member")
    if row["capability_type"] in {"CONCEPT", "DIMENSION_MEMBER"}:
        required_observed = ("raw_concept_id", "source_fact_ids", "source_filing_ids")
        missing_observed = [key for key in required_observed if not row.get(key)]
        if missing_observed:
            raise Layer2MaterializationError(
                "observed capability requires raw concept and source Fact/filing lineage: "
                + ", ".join(missing_observed)
            )


def _validate_metric_input_candidate(row: Mapping[str, Any]) -> None:
    """M6 hands off selected inputs; it must not contain a calculated value."""
    required = (
        "metric_input_candidate_id",
        "metric_input_role",
        "analytical_fact_id",
        "view",
        "as_of_date",
        "period_class",
        "period_key",
        "mapping_version",
        "candidate_status",
        "metric_input_handoff_version",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(f"metric_input_candidate missing provenance: {missing}")
    if row["candidate_status"] not in {"CANDIDATE", "UNAVAILABLE", "DIRECT_OBSERVATION_ONLY"}:
        raise Layer2MaterializationError("metric_input_candidate has unsupported candidate_status")
    if row["candidate_status"] == "UNAVAILABLE" and not row.get("unavailable_reason"):
        raise Layer2MaterializationError(
            "unavailable metric_input_candidate requires unavailable_reason"
        )
    if row["candidate_status"] == "CANDIDATE" and not (
        row.get("selected_fact_id") or row.get("source_fact_ids")
    ):
        raise Layer2MaterializationError(
            "available metric_input_candidate requires selected Fact or derived source Fact lineage"
        )
    if row["candidate_status"] == "CANDIDATE" and not row.get("source_filing_id"):
        raise Layer2MaterializationError(
            "available metric_input_candidate requires source filing lineage"
        )
    if (
        row["candidate_status"] == "DIRECT_OBSERVATION_ONLY"
        and row.get("unavailable_reason") != "DIRECT_OBSERVATION_NO_REVERSE_ENGINEERING"
    ):
        raise Layer2MaterializationError(
            "direct EPS/share candidate must prohibit reverse engineering"
        )
    forbidden = {"value_numeric", "value_text", "derived_metric_id", "metric_value"}
    if forbidden & set(row):
        raise Layer2MaterializationError(
            "metric_input_candidate cannot store calculated metric value"
        )


def _validate_metric_input_compatibility(row: Mapping[str, Any]) -> None:
    required = (
        "metric_input_compatibility_id",
        "metric_assessment_id",
        "view",
        "as_of_date",
        "period_class",
        "period_key",
        "company_canonical_dimension_key",
        "required_input_roles",
        "input_analytical_fact_ids",
        "compatibility_status",
        "metric_input_handoff_version",
    )
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise Layer2MaterializationError(
            f"metric_input_compatibility missing provenance: {missing}"
        )
    if row["metric_assessment_id"] not in {
        "GROSS_MARGIN",
        "OPERATING_MARGIN",
        "REVENUE_GROWTH",
        "Q4_FLOW",
    }:
        raise Layer2MaterializationError("metric_input_compatibility has unsupported assessment")
    if row["compatibility_status"] not in {"ELIGIBLE", "UNAVAILABLE"}:
        raise Layer2MaterializationError("metric_input_compatibility has unsupported status")
    if row["compatibility_status"] == "UNAVAILABLE" and not row.get("unavailable_reason"):
        raise Layer2MaterializationError("unavailable metric input compatibility requires reason")
    if row["compatibility_status"] == "ELIGIBLE" and row.get("unavailable_reason") is not None:
        raise Layer2MaterializationError(
            "eligible metric input compatibility cannot have unavailable reason"
        )
    forbidden = {"value_numeric", "value_text", "derived_metric_id", "metric_value", "formula"}
    if forbidden & set(row):
        raise Layer2MaterializationError(
            "metric_input_compatibility cannot store a calculated metric"
        )


def _record_id(dataset: str, row: Mapping[str, Any]) -> str:
    if dataset == "analytical_fact":
        return str(row.get("analytical_fact_id") or "")
    if dataset in {"annual_series_candidate", "current_series_candidate"}:
        return str(row.get("series_candidate_id") or "")
    if dataset == "series_candidate_exclusion":
        return str(row.get("series_candidate_exclusion_id") or "")
    if dataset == "capability_inventory":
        return str(row.get("capability_inventory_id") or "")
    if dataset == "metric_input_candidate":
        return str(row.get("metric_input_candidate_id") or "")
    if dataset == "metric_input_compatibility":
        return str(row.get("metric_input_compatibility_id") or "")
    for key in ("id", f"{dataset}_id", "fact_id", "source_raw_id", "event_id"):
        if row.get(key):
            return str(row[key])
    return _sha256_json(row)


def _write_datasets(root: Path, datasets: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    by_cik: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for dataset, rows in datasets.items():
        for row in rows:
            by_cik.setdefault(str(row["cik"]), {}).setdefault(dataset, []).append(row)
    for cik, tables in sorted(by_cik.items()):
        company_root = root / cik
        company_root.mkdir(parents=True, exist_ok=True)
        for dataset, rows in sorted(tables.items()):
            content = "".join(_canonical_json(row) + "\n" for row in _sorted_rows(dataset, rows))
            (company_root / f"{dataset}.jsonl").write_text(content, encoding="utf-8")


def _dataset_hashes(datasets: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, str]:
    """Stable content digests prove idempotent keys *and* values, not counts alone."""
    return {
        dataset: _sha256_json(
            [json.loads(_canonical_json(row)) for row in _sorted_rows(dataset, rows)]
        )
        for dataset, rows in sorted(datasets.items())
    }


def _validate_written_candidate(root: Path, manifest_name: str, counts: Mapping[str, int]) -> None:
    observed: dict[str, int] = {dataset: 0 for dataset in counts}
    for path in root.glob("*/**/*.jsonl"):
        dataset = path.stem
        if dataset not in observed:
            raise Layer2MaterializationError(f"unexpected dataset file: {path}")
        observed[dataset] += sum(
            1 for line in path.read_text(encoding="utf-8").splitlines() if line
        )
    if observed != dict(counts):
        raise Layer2MaterializationError(
            f"written output counts do not match manifest: {observed} != {counts}"
        )
    manifest_path = root / manifest_name
    if manifest_path.exists():
        try:
            json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Layer2MaterializationError("written manifest is invalid") from exc


def _sorted_rows(dataset: str, rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda row: (_record_id(dataset, row), _canonical_json(row)))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sorted_dicts(rows: Any) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=_canonical_json)


def _read_publication_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise Layer2PublicationValidationError(f"Layer 2 manifest is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Layer2PublicationValidationError(f"invalid Layer 2 manifest: {path}") from exc
    if not isinstance(value, dict):
        raise Layer2PublicationValidationError("Layer 2 manifest must be a JSON object")
    return value


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    expected = {
        "contract_version", "run_version", "corpus_run_id", "run_fingerprint", "inputs", "rules",
        "output_counts", "output_content_sha256", "validation", "published_at", "storage_format",
    }
    if set(manifest) != expected:
        raise Layer2PublicationValidationError("Layer 2 manifest has unsupported or missing fields")
    if not isinstance(manifest["output_counts"], dict) or not isinstance(
        manifest["output_content_sha256"], dict
    ):
        raise Layer2PublicationValidationError("Layer 2 manifest output declarations must be objects")
    counts = manifest["output_counts"]
    hashes = manifest["output_content_sha256"]
    if set(counts) != set(hashes) or not set(counts).issubset(LOGICAL_DATASETS):
        raise Layer2PublicationValidationError("Layer 2 manifest datasets are unsupported or inconsistent")
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise Layer2PublicationValidationError("Layer 2 manifest has invalid output count")
    if any(not isinstance(value, str) or len(value) != 64 for value in hashes.values()):
        raise Layer2PublicationValidationError("Layer 2 manifest has invalid content hash")
    validation = manifest["validation"]
    expected_validation = {
        "ANALYTICAL_FACT_LINEAGE",
        "RUN_INPUT_AND_VERSION_MANIFEST",
        "DETERMINISTIC_OUTPUT_IDENTITY",
        "ATOMIC_PUBLICATION",
    }
    if (
        not isinstance(validation, dict)
        or set(validation) != expected_validation
        or any(value != "SUCCESS" for value in validation.values())
    ):
        raise Layer2PublicationValidationError("Layer 2 manifest did not declare successful validation")


def _run_from_manifest(manifest: Mapping[str, Any]) -> Layer2Run:
    try:
        inputs = tuple(Layer1SnapshotInput(**dict(row)) for row in manifest["inputs"])
        rules = Layer2RuleVersions(**dict(manifest["rules"]))
        return Layer2Run(
            run_version=str(manifest["run_version"]),
            corpus_run_id=str(manifest["corpus_run_id"]),
            inputs=inputs,
            rules=rules,
            contract_version=str(manifest["contract_version"]),
        )
    except (KeyError, TypeError, ValueError, Layer2MaterializationError) as exc:
        raise Layer2PublicationValidationError("Layer 2 manifest run declaration is malformed") from exc


def _read_published_datasets(
    root: Path, manifest: Mapping[str, Any], run: Layer2Run
) -> dict[str, tuple[dict[str, Any], ...]]:
    declared = set(manifest["output_counts"])
    paths: dict[str, list[Path]] = {dataset: [] for dataset in declared}
    input_ciks = {item.cik for item in run.inputs}
    for child in root.iterdir():
        if child.name == Layer2PublicationReader.manifest_name:
            continue
        if not child.is_dir() or child.is_symlink() or child.name not in input_ciks:
            raise Layer2PublicationValidationError(f"unexpected Layer 2 publication entry: {child}")
        for file_path in child.iterdir():
            if not file_path.is_file() or file_path.is_symlink() or file_path.suffix != ".jsonl":
                raise Layer2PublicationValidationError(f"unexpected Layer 2 dataset file: {file_path}")
            dataset = file_path.stem
            if dataset not in declared:
                raise Layer2PublicationValidationError(f"unexpected Layer 2 dataset file: {file_path}")
            paths[dataset].append(file_path)
    datasets: dict[str, tuple[dict[str, Any], ...]] = {}
    for dataset in sorted(declared):
        rows: list[dict[str, Any]] = []
        for file_path in sorted(paths[dataset]):
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError) as exc:
                raise Layer2PublicationValidationError(f"cannot read Layer 2 dataset: {file_path}") from exc
            for line_number, line in enumerate(lines, start=1):
                if not line:
                    raise Layer2PublicationValidationError(
                        f"empty JSONL line in Layer 2 dataset: {file_path}:{line_number}"
                    )
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise Layer2PublicationValidationError(
                        f"invalid JSONL in Layer 2 dataset: {file_path}:{line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise Layer2PublicationValidationError("Layer 2 dataset row must be a JSON object")
                if str(row.get("cik") or "") != file_path.parent.name:
                    raise Layer2PublicationValidationError("Layer 2 dataset row CIK does not match its partition")
                rows.append(row)
        datasets[dataset] = tuple(rows)
    return datasets
