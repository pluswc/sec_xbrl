"""Durable, provenance-bound materialization for governed derived metrics.

This module is intentionally downstream of Layer 2.  It consumes an M0
definition plus an eligible M6 handoff, then joins the selected analytical
observation values by their already-governed candidate IDs.  It never looks up
an XBRL QName, label, or raw Fact to decide what an input means.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.metrics.registry import MetricCategory, MetricDefinitionError, MetricRegistry

DERIVED_METRICS_CONTRACT_VERSION = "derived-metrics-m1-materialization-v1"
DEFAULT_DERIVED_METRICS_ROOT = Path("data/processed/analytical/derived_metrics")


class DerivedMetricMaterializationError(RuntimeError):
    """Raised when a metric cannot safely be calculated or published."""


@dataclass(frozen=True, slots=True)
class DerivedMetricsRun:
    """Immutable declaration of an independently reproducible metric run."""

    run_version: str
    layer2_run_fingerprint: str
    registry_contract_version: str
    registry_version: str
    contract_version: str = DERIVED_METRICS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.run_version or "/" in self.run_version or "\\" in self.run_version:
            raise DerivedMetricMaterializationError("run_version must be a non-path identifier")
        if not all(
            (self.layer2_run_fingerprint, self.registry_contract_version, self.registry_version)
        ):
            raise DerivedMetricMaterializationError(
                "metric run requires Layer 2 and registry identity"
            )

    @property
    def fingerprint(self) -> str:
        return _sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class DerivedMetricPublication:
    run_root: Path
    manifest_path: Path
    fingerprint: str
    output_count: int
    reused_existing: bool


class DerivedMetricMaterializer:
    """Evaluate only the small controlled set of M0 numerical definitions."""

    def __init__(self, registry: MetricRegistry) -> None:
        self.registry = registry

    def materialize(
        self,
        *,
        definition_id: str,
        candidates: Iterable[Mapping[str, Any]],
        compatibility: Mapping[str, Any],
        selected_observation_values: Iterable[Mapping[str, Any]],
        evaluated_at: str,
    ) -> dict[str, Any]:
        """Create one immutable output, after registry and value-lineage gates.

        ``selected_observation_values`` is not a semantic input source.  It is
        the numeric payload of the L2 analytical observations named by the M6
        candidate IDs.  Its IDs and every scope field must equal its candidate.
        This deliberate separation lets M0 reject values in its handoff while
        still allowing M1 to calculate from selected L2 observations.
        """
        _timestamp(evaluated_at)
        definition = self.registry.resolve(definition_id)
        if definition.category is not MetricCategory.DERIVED:
            raise DerivedMetricMaterializationError("only DERIVED definitions can be materialized")
        if definition.output_semantics == "ELIGIBILITY_ONLY":
            raise DerivedMetricMaterializationError(
                "eligibility-only definition cannot materialize a numeric metric value"
            )
        candidate_rows = tuple(dict(row) for row in candidates)
        try:
            self.registry.validate_handoff(
                definition_id=definition_id, candidates=candidate_rows, compatibility=compatibility
            )
        except MetricDefinitionError as exc:
            return _unavailable_record(
                definition, compatibility, candidate_rows, evaluated_at, f"M6_HANDOFF_INVALID:{exc}"
            )
        try:
            values = _bind_selected_values(candidate_rows, selected_observation_values)
            input_values = tuple(
                values[str(row["metric_input_candidate_id"])] for row in candidate_rows
            )
            calculated = _calculate(definition.metric_id, input_values)
        except DerivedMetricMaterializationError as exc:
            return _unavailable_record(
                definition,
                compatibility,
                candidate_rows,
                evaluated_at,
                f"INPUT_VALUE_UNAVAILABLE:{exc}",
            )
        formula = definition.formula
        if formula is None:  # registry protects this, retained as a hard boundary.
            raise DerivedMetricMaterializationError("derived definition lacks formula provenance")
        ordered_lineage = _ordered_lineage(candidate_rows, values)
        return _record_base(definition, compatibility, candidate_rows, ordered_lineage) | {
            "metric_definition_id": definition.definition_id,
            "metric_id": definition.metric_id,
            "metric_definition_version": definition.version,
            "formula_id": formula.formula_id,
            "formula_version": formula.formula_version,
            "formula_expression": formula.expression,
            "calculation_status": "AVAILABLE",
            "unavailable_reason": None,
            "metric_value_decimal": _decimal_text(calculated),
            "source_type": "DERIVED_METRIC",
            "calculated_at": evaluated_at,
            "evaluated_at": evaluated_at,
            "metric_unit_semantics": definition.output_unit_semantics,
            "cik": compatibility["cik"],
            "view": compatibility["view"],
            "as_of_date": compatibility["as_of_date"],
            "basis_version": compatibility["basis_version"],
            "series_type": compatibility["series_type"],
            "period_class": compatibility["period_class"],
            "period_key": compatibility["period_key"],
            "comparison_period_key": compatibility.get("comparison_period_key"),
            "company_canonical_dimension_key": compatibility["company_canonical_dimension_key"],
            "input_unit_semantics": compatibility["unit_semantics"],
            "mapping_versions": tuple(compatibility["mapping_versions"]),
            "metric_input_handoff_version": compatibility["metric_input_handoff_version"],
            "metric_input_compatibility_id": compatibility["metric_input_compatibility_id"],
            "ordered_input_candidate_ids": tuple(
                row["metric_input_candidate_id"] for row in candidate_rows
            ),
            "ordered_input_analytical_fact_ids": tuple(
                row["analytical_fact_id"] for row in candidate_rows
            ),
            "ordered_input_selected_fact_ids": tuple(
                row.get("selected_fact_id") for row in candidate_rows
            ),
            "ordered_input_lineage": ordered_lineage,
            "derived_metrics_contract_version": DERIVED_METRICS_CONTRACT_VERSION,
        }


class DerivedMetricPublisher:
    """Atomically publish immutable ``derived_metric`` records and manifest."""

    manifest_name = "derived_metrics_run_manifest.json"

    def __init__(self, root: Path = DEFAULT_DERIVED_METRICS_ROOT) -> None:
        self.root = Path(root)

    def publish(
        self, run: DerivedMetricsRun, records: Sequence[Mapping[str, Any]]
    ) -> DerivedMetricPublication:
        rows = tuple(dict(row) for row in records)
        _validate_records(rows)
        content_hash = _sha256_json(rows)
        destination = self.root / run.run_version
        existing = self._existing(destination, run, len(rows), content_hash)
        if existing is not None:
            return existing
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{run.run_version}.partial-", dir=staging))
        try:
            path = temporary / "derived_metric.jsonl"
            path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")
            manifest = {
                **asdict(run),
                "run_fingerprint": run.fingerprint,
                "output_counts": {"derived_metric": len(rows)},
                "output_content_sha256": {"derived_metric": content_hash},
                "validation": {
                    "REGISTRY_AND_M6_HANDOFF": "SUCCESS",
                    "FORMULA_LINEAGE": "SUCCESS",
                    "ATOMIC_PUBLICATION": "SUCCESS",
                },
                "published_at": datetime.now(UTC).isoformat(),
            }
            (temporary / self.manifest_name).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            _validate_written(temporary, len(rows))
            if destination.exists():
                existing = self._existing(destination, run, len(rows), content_hash)
                if existing is not None:
                    return existing
                raise DerivedMetricMaterializationError(
                    "run_version already belongs to another output"
                )
            os.replace(temporary, destination)
            return DerivedMetricPublication(
                destination, destination / self.manifest_name, run.fingerprint, len(rows), False
            )
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _existing(
        self, destination: Path, run: DerivedMetricsRun, count: int, content_hash: str
    ) -> DerivedMetricPublication | None:
        if not destination.exists():
            return None
        manifest_path = destination / self.manifest_name
        if not manifest_path.is_file():
            raise DerivedMetricMaterializationError("unpublished or partial derived metric run")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DerivedMetricMaterializationError("invalid derived metric run manifest") from exc
        if manifest.get("run_fingerprint") != run.fingerprint:
            raise DerivedMetricMaterializationError(
                "run_version already belongs to different inputs or rules"
            )
        if manifest.get("output_counts") != {"derived_metric": count} or manifest.get(
            "output_content_sha256"
        ) != {"derived_metric": content_hash}:
            raise DerivedMetricMaterializationError(
                "identical metric run declaration produced different output"
            )
        _validate_written(destination, count)
        return DerivedMetricPublication(destination, manifest_path, run.fingerprint, count, True)


def _bind_selected_values(
    candidates: Sequence[Mapping[str, Any]], values: Iterable[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_candidate = {str(row["metric_input_candidate_id"]): row for row in candidates}
    bound: dict[str, dict[str, Any]] = {}
    required = ("metric_input_candidate_id", "analytical_fact_id", "value_decimal")
    provenance = (
        "source_filing_id",
        "view",
        "as_of_date",
        "basis_version",
        "series_type",
        "period_class",
        "period_key",
        "company_canonical_dimension_key",
        "unit_semantics",
        "mapping_version",
        "source_type",
    )
    for source in values:
        row = dict(source)
        missing = [field for field in required if field not in row]
        if missing:
            raise DerivedMetricMaterializationError(
                "selected observation value lacks: " + ", ".join(missing)
            )
        candidate_id = str(row["metric_input_candidate_id"])
        candidate = by_candidate.get(candidate_id)
        if candidate is None:
            raise DerivedMetricMaterializationError(
                "selected observation value is not named by M6 handoff"
            )
        if candidate_id in bound:
            raise DerivedMetricMaterializationError(
                "duplicate selected observation value for candidate"
            )
        if str(row["analytical_fact_id"]) != str(candidate["analytical_fact_id"]):
            raise DerivedMetricMaterializationError(
                "selected observation analytical Fact does not match M6 candidate"
            )
        missing_provenance = [field for field in provenance if field not in row]
        if missing_provenance:
            raise DerivedMetricMaterializationError(
                "selected observation value lacks provenance: " + ", ".join(missing_provenance)
            )
        for field in provenance:
            if row[field] != candidate.get(field):
                raise DerivedMetricMaterializationError(
                    f"selected observation provenance mismatch: {field}"
                )
        row["value_decimal"] = _decimal(row["value_decimal"])
        bound[candidate_id] = row
    missing_values = [key for key in by_candidate if key not in bound]
    if missing_values:
        raise DerivedMetricMaterializationError(
            "eligible M6 candidate has no selected observation value"
        )
    return bound


def _record_base(
    definition: Any,
    compatibility: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    ordered_lineage: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Keep an unavailable evaluation as traceable as a successful one."""
    scope = dict(compatibility)
    template = candidates[0] if candidates else {}
    def field(name: str) -> Any:
        return scope.get(name, template.get(name))

    identity = (
        definition.definition_id,
        field("cik"), field("view"), field("as_of_date"), field("period_key"),
        repr(field("company_canonical_dimension_key")),
        tuple(row.get("metric_input_candidate_id") for row in candidates),
        scope.get("metric_input_compatibility_id"),
    )
    return {
        "derived_metric_id": _id("derived-metric", identity),
        "metric_definition_id": definition.definition_id,
        "metric_id": definition.metric_id,
        "metric_definition_version": definition.version,
        "formula_id": definition.formula.formula_id if definition.formula else None,
        "formula_version": definition.formula.formula_version if definition.formula else None,
        "formula_expression": definition.formula.expression if definition.formula else None,
        "metric_unit_semantics": definition.output_unit_semantics,
        "cik": field("cik"),
        "view": field("view"),
        "as_of_date": field("as_of_date"),
        "basis_version": field("basis_version"),
        "series_type": field("series_type"),
        "period_class": field("period_class"),
        "period_key": field("period_key"),
        "comparison_period_key": scope.get("comparison_period_key"),
        "company_canonical_dimension_key": field("company_canonical_dimension_key"),
        "input_unit_semantics": field("unit_semantics"),
        "mapping_versions": tuple(scope.get("mapping_versions") or ()),
        "metric_input_handoff_version": scope.get("metric_input_handoff_version"),
        "metric_input_compatibility_id": scope.get("metric_input_compatibility_id"),
        "ordered_input_candidate_ids": tuple(row.get("metric_input_candidate_id") for row in candidates),
        "ordered_input_analytical_fact_ids": tuple(row.get("analytical_fact_id") for row in candidates),
        "ordered_input_selected_fact_ids": tuple(row.get("selected_fact_id") for row in candidates),
        "ordered_input_lineage": ordered_lineage,
        "derived_metrics_contract_version": DERIVED_METRICS_CONTRACT_VERSION,
    }


def _ordered_lineage(
    candidates: Sequence[Mapping[str, Any]], values: Mapping[str, Mapping[str, Any]] | None = None
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "metric_input_candidate_id": row.get("metric_input_candidate_id"),
            "analytical_fact_id": row.get("analytical_fact_id"),
            "selected_fact_id": row.get("selected_fact_id"),
            "source_fact_ids": tuple(row.get("source_fact_ids") or ()),
            "source_filing_id": row.get("source_filing_id"),
            "view": row.get("view"),
            "as_of_date": row.get("as_of_date"),
            "basis_version": row.get("basis_version"),
            "period_class": row.get("period_class"),
            "period_key": row.get("period_key"),
            "company_canonical_dimension_key": row.get("company_canonical_dimension_key"),
            "unit_semantics": row.get("unit_semantics"),
            "mapping_version": row.get("mapping_version"),
            "source_type": row.get("source_type"),
            "recast_evidence_id": row.get("recast_evidence_id"),
            "derivation_rule_version": row.get("derivation_rule_version"),
            "value_decimal": (
                _decimal_text(values[str(row["metric_input_candidate_id"])]["value_decimal"])
                if values is not None and str(row.get("metric_input_candidate_id")) in values
                else None
            ),
        }
        for row in candidates
    )


def _unavailable_record(
    definition: Any,
    compatibility: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    evaluated_at: str,
    reason: str,
) -> dict[str, Any]:
    return _record_base(definition, compatibility, candidates, _ordered_lineage(candidates)) | {
        "calculation_status": "UNAVAILABLE",
        "unavailable_reason": reason,
        "metric_value_decimal": None,
        "source_type": "DERIVED_METRIC",
        "calculated_at": None,
        "evaluated_at": evaluated_at,
    }


def _calculate(metric_id: str, values: Sequence[Mapping[str, Any]]) -> Decimal:
    operands = [value["value_decimal"] for value in values]
    if metric_id in {"gross_margin", "operating_margin"}:
        if operands[1] == 0:
            raise DerivedMetricMaterializationError("ratio denominator is zero")
        return (operands[0] / operands[1]) * Decimal(100)
    if metric_id == "revenue_growth":
        if operands[1] == 0:
            raise DerivedMetricMaterializationError("growth predecessor denominator is zero")
        return ((operands[0] / operands[1]) - Decimal(1)) * Decimal(100)
    raise DerivedMetricMaterializationError(
        f"definition has no approved numeric materializer: {metric_id}"
    )


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise DerivedMetricMaterializationError("boolean is not a numeric observation")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DerivedMetricMaterializationError(
            "selected observation value is not Decimal-compatible"
        ) from exc
    if not result.is_finite():
        raise DerivedMetricMaterializationError("selected observation value must be finite")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _timestamp(value: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (AttributeError, ValueError) as exc:
        raise DerivedMetricMaterializationError("evaluation timestamp must be ISO-8601") from exc


def _validate_records(rows: Sequence[Mapping[str, Any]]) -> None:
    ids: set[str] = set()
    required = (
        "derived_metric_id",
        "metric_definition_id",
        "metric_definition_version",
        "formula_id",
        "formula_version",
        "calculation_status",
        "source_type",
        "evaluated_at",
        "cik",
        "view",
        "as_of_date",
        "period_class",
        "period_key",
        "metric_input_compatibility_id",
        "ordered_input_candidate_ids",
        "ordered_input_lineage",
    )
    for row in rows:
        missing = [field for field in required if row.get(field) is None or row.get(field) == ""]
        if missing:
            raise DerivedMetricMaterializationError(
                "derived_metric lacks required provenance: " + ", ".join(missing)
            )
        if row.get("source_type") != "DERIVED_METRIC":
            raise DerivedMetricMaterializationError("derived_metric requires DERIVED_METRIC source type")
        status = row.get("calculation_status")
        if status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise DerivedMetricMaterializationError(
                "derived_metric has unsupported calculation status"
            )
        if row["derived_metric_id"] in ids:
            raise DerivedMetricMaterializationError("duplicate derived_metric identity")
        ids.add(str(row["derived_metric_id"]))
        _timestamp(str(row["evaluated_at"]))
        if status == "AVAILABLE":
            if row.get("unavailable_reason") is not None or row.get("metric_value_decimal") is None:
                raise DerivedMetricMaterializationError("available derived_metric requires numeric value only")
            if not row.get("calculated_at"):
                raise DerivedMetricMaterializationError("available derived_metric requires calculation timestamp")
            _timestamp(str(row["calculated_at"]))
            _decimal(row["metric_value_decimal"])
        else:
            if not row.get("unavailable_reason") or row.get("metric_value_decimal") is not None:
                raise DerivedMetricMaterializationError(
                    "unavailable derived_metric requires reason and no numeric value"
                )
            if row.get("calculated_at") is not None:
                raise DerivedMetricMaterializationError(
                    "unavailable derived_metric cannot carry calculation timestamp"
                )
        if len(row["ordered_input_candidate_ids"]) != len(row["ordered_input_lineage"]):
            raise DerivedMetricMaterializationError("derived metric input lineage is incomplete")
        if status == "AVAILABLE" and not all(
            item.get("selected_fact_id") or item.get("source_fact_ids")
            for item in row["ordered_input_lineage"]
        ):
            raise DerivedMetricMaterializationError("derived metric input lacks raw Fact lineage")


def _validate_written(root: Path, expected_count: int) -> None:
    path = root / "derived_metric.jsonl"
    if not path.is_file() or not (root / DerivedMetricPublisher.manifest_name).is_file():
        raise DerivedMetricMaterializationError("derived metric atomic candidate is incomplete")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(lines) != expected_count:
        raise DerivedMetricMaterializationError("derived metric output count differs after write")
    _validate_records(tuple(json.loads(line) for line in lines))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=list)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str, identity: object) -> str:
    return f"{prefix}:{_sha256_json(identity)[:24]}"
