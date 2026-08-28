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
        "annual_series_candidate",
        "current_series_candidate",
        "series_candidate_exclusion",
    }
)
_ANALYTICAL_SOURCE_TYPES = frozenset(
    {"REPORTED", "RECAST_REPORTED", "DERIVED_RECAST", "UNAVAILABLE"}
)
_MAPPING_DATASETS = frozenset(
    {"company_concept_map", "company_axis_map", "company_member_map"}
)
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
                raise Layer2MaterializationError(f"published run version already exists: {destination}")
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
            raise Layer2MaterializationError(f"invalid Layer 2 run manifest: {manifest_path}") from exc
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
    if "analytical_fact" not in datasets and not ({"annual_series_candidate", "current_series_candidate"} & set(datasets)):
        raise Layer2MaterializationError(
            "candidate requires analytical_fact or an L2-M3 series candidate dataset"
        )
    return {name: tuple(dict(row) for row in rows) for name, rows in datasets.items()}


def _validate_candidate(run: Layer2Run, datasets: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, int]:
    input_ciks = {row.cik for row in run.inputs}
    counts: dict[str, int] = {}
    mappings_by_id: dict[str, Mapping[str, Any]] = {}
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
                raise Layer2MaterializationError(f"{dataset} row references CIK outside declared inputs")
            record_id = _record_id(dataset, row)
            if record_id in seen_ids:
                raise Layer2MaterializationError(f"duplicate {dataset} record identity: {record_id}")
            seen_ids.add(record_id)
            if dataset == "analytical_fact":
                _validate_analytical_fact(row)
            elif dataset in {"annual_series_candidate", "current_series_candidate"}:
                _validate_series_candidate(dataset, row)
            elif dataset in _MAPPING_DATASETS:
                # This was validated first so structural-change rows can only
                # link to a real map in the same atomic candidate.
                pass
            elif dataset == "structural_change":
                _validate_structural_change(row, mappings_by_id)
            try:
                _canonical_json(row)
            except (TypeError, ValueError) as exc:
                raise Layer2MaterializationError(f"{dataset} row is not canonical JSON serializable") from exc
        counts[dataset] = len(rows)
    return dict(sorted(counts.items()))


def _validate_analytical_fact(row: Mapping[str, Any]) -> None:
    if not row.get("analytical_fact_id"):
        raise Layer2MaterializationError("analytical_fact requires analytical_fact_id")
    source_type = str(row.get("source_type") or "")
    if source_type not in _ANALYTICAL_SOURCE_TYPES:
        raise Layer2MaterializationError(f"unsupported analytical_fact source_type: {source_type!r}")
    has_numeric = row.get("value_numeric") is not None
    selected_fact_id = row.get("selected_fact_id")
    unavailable_reason = row.get("unavailable_reason")
    if source_type == "UNAVAILABLE":
        if has_numeric or selected_fact_id:
            raise Layer2MaterializationError("UNAVAILABLE analytical_fact cannot have numeric value or selected_fact_id")
        if not unavailable_reason:
            raise Layer2MaterializationError("UNAVAILABLE analytical_fact requires unavailable_reason")
        return
    if not selected_fact_id:
        raise Layer2MaterializationError("analytical_fact requires selected raw Fact ID")
    if unavailable_reason:
        raise Layer2MaterializationError("available analytical_fact cannot have unavailable_reason")
    if has_numeric and not selected_fact_id:
        raise Layer2MaterializationError("numeric analytical_fact requires selected raw Fact ID")
    required = ("view", "as_of_date", "selection_rule_version")
    missing = [key for key in required if not row.get(key)]
    if missing:
        raise Layer2MaterializationError(f"analytical_fact missing selection provenance: {missing}")


def _validate_series_candidate(dataset: str, row: Mapping[str, Any]) -> None:
    """Keep pre-selection M3 candidates traceable and period-safe."""
    expected_type = "ANNUAL" if dataset == "annual_series_candidate" else "CURRENT"
    required = (
        "series_candidate_id", "series_type", "series_status",
        "company_canonical_concept_id", "company_canonical_dimension_key",
        "unit_semantics", "actual_period_boundaries", "actual_period_key",
        "period_class", "series_key", "source_period_observation_id",
        "source_filing_id", "mapping_version", "mapping_evidence",
        "classification_rule_version", "series_rule_version",
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


def _record_id(dataset: str, row: Mapping[str, Any]) -> str:
    if dataset == "analytical_fact":
        return str(row.get("analytical_fact_id") or "")
    if dataset in {"annual_series_candidate", "current_series_candidate"}:
        return str(row.get("series_candidate_id") or "")
    if dataset == "series_candidate_exclusion":
        return str(row.get("series_candidate_exclusion_id") or "")
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
        dataset: _sha256_json([json.loads(_canonical_json(row)) for row in _sorted_rows(dataset, rows)])
        for dataset, rows in sorted(datasets.items())
    }


def _validate_written_candidate(root: Path, manifest_name: str, counts: Mapping[str, int]) -> None:
    observed: dict[str, int] = {dataset: 0 for dataset in counts}
    for path in root.glob("*/**/*.jsonl"):
        dataset = path.stem
        if dataset not in observed:
            raise Layer2MaterializationError(f"unexpected dataset file: {path}")
        observed[dataset] += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
    if observed != dict(counts):
        raise Layer2MaterializationError(f"written output counts do not match manifest: {observed} != {counts}")
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
