"""Read-only same-company series and as-of selection for derived metrics.

M2 consumes immutable M1 ``derived_metric`` records.  It does not evaluate a
formula, bind a new input, or change a materialized record.  A metric result is
available to this boundary as of the L2 ``as_of_date`` embedded in the record;
that date is the governed availability ceiling of its selected inputs, rather
than the time at which this process happened to read a file.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

DERIVED_METRIC_SERIES_CONTRACT_VERSION = "derived-metrics-m2-series-v1"
_NO_COMPATIBLE_INPUT_REASONS = frozenset({"REQUIRED_INPUT_NOT_AVAILABLE"})


class DerivedMetricSeriesError(ValueError):
    """A materialized metric cannot safely participate in a metric series."""


_REQUIRED = (
    "derived_metric_id", "metric_definition_id", "metric_id", "metric_definition_version",
    "formula_id", "formula_version",
    "cik", "view", "as_of_date", "basis_version", "series_type", "period_class",
    "period_key", "company_canonical_dimension_key", "input_unit_semantics",
    "metric_unit_semantics", "calculation_status", "source_type", "evaluated_at",
    "metric_input_handoff_version", "metric_input_compatibility_id", "mapping_versions",
    "ordered_input_candidate_ids", "ordered_input_analytical_fact_ids",
    "ordered_input_lineage", "derived_metrics_contract_version",
)


class DerivedMetricSeriesMaterializer:
    """Create deterministic candidates and select immutable metric revisions."""

    def load_published_candidates(self, run_root: Path) -> tuple[dict[str, Any], ...]:
        """Load candidates only from one hash-verified M1 publication.

        This is intentionally the sole M1-to-M2 admission path.  Callers may
        not supply a convenient list of rows plus a separately invented
        manifest: the JSONL payload and its adjacent M1 manifest are checked
        together before any row is allowed into a series.
        """
        root = Path(run_root)
        manifest_path = root / "derived_metrics_run_manifest.json"
        records_path = root / "derived_metric.jsonl"
        if not manifest_path.is_file() or not records_path.is_file():
            raise DerivedMetricSeriesError("verified M1 publication is incomplete")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = tuple(
                json.loads(line)
                for line in records_path.read_text(encoding="utf-8").splitlines()
                if line
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise DerivedMetricSeriesError("verified M1 publication is unreadable") from exc
        _validate_published_run(manifest, records)
        result: list[dict[str, Any]] = []
        identities: dict[str, str] = {}
        for source in records:
            row = deepcopy(dict(source))
            _validate_record(row)
            identity = _candidate_identity(row)
            candidate_id = _stable_id("derived-metric-series-candidate", identity)
            canonical = _canonical_json(row)
            prior = identities.get(candidate_id)
            if prior is not None and prior != canonical:
                raise DerivedMetricSeriesError("immutable derived_metric identity has conflicting content")
            if prior is None:
                identities[candidate_id] = canonical
                result.append(
                    row
                    | {
                        "metric_series_candidate_id": candidate_id,
                        "metric_series_key": _series_key(row),
                        "metric_series_family_key": _family_key(row),
                        "metric_revision_id": str(row["derived_metric_id"]),
                        "metric_revision_as_of_date": str(row["as_of_date"]),
                        "source_metric_run_version": manifest["run_version"],
                        "source_metric_run_fingerprint": manifest["run_fingerprint"],
                        "source_metric_manifest_identity": _stable_id("derived-metric-run", manifest),
                        "metric_series_contract_version": DERIVED_METRIC_SERIES_CONTRACT_VERSION,
                    }
                )
        return tuple(sorted(result, key=_candidate_order))

    def select(
        self,
        candidates: Iterable[Mapping[str, Any]],
        *,
        as_of_date: str,
        view: str,
    ) -> tuple[dict[str, Any], ...]:
        """Select an as-filed or current-comparable metric series.

        No candidate is rewritten.  ``CURRENT_COMPARABLE`` selects one
        evidence-governed basis for a family and emits ``UNAVAILABLE`` for a
        target period not available under that basis.
        """
        _date(as_of_date, "as_of_date")
        if view not in {"AS_FILED", "CURRENT_COMPARABLE"}:
            raise DerivedMetricSeriesError("view must be AS_FILED or CURRENT_COMPARABLE")
        rows = tuple(deepcopy(dict(row)) for row in candidates)
        for row in rows:
            _validate_candidate(row)
        visible = tuple(
            row for row in rows
            if row["view"] == view and str(row["metric_revision_as_of_date"]) <= as_of_date
        )
        families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in visible:
            families[str(row["metric_series_family_key"])].append(row)
        selected: list[dict[str, Any]] = []
        for family_rows in families.values():
            if view == "AS_FILED":
                selected.extend(_select_as_filed(family_rows, as_of_date))
            else:
                selected.extend(_select_current_comparable(family_rows, as_of_date))
        return tuple(sorted(selected, key=_selection_order))


def _validate_record(row: Mapping[str, Any]) -> None:
    missing = [key for key in _REQUIRED if row.get(key) is None]
    if missing:
        raise DerivedMetricSeriesError("derived_metric lacks required provenance: " + ", ".join(missing))
    if row["source_type"] != "DERIVED_METRIC":
        raise DerivedMetricSeriesError("metric series accepts only DERIVED_METRIC records")
    if row["view"] not in {"AS_FILED", "CURRENT_COMPARABLE"}:
        raise DerivedMetricSeriesError("derived_metric has unsupported governed view")
    _date(str(row["as_of_date"]), "derived_metric as_of_date")
    if not str(row["basis_version"]):
        raise DerivedMetricSeriesError("derived_metric requires an explicit basis_version")
    if row["calculation_status"] == "AVAILABLE":
        if row.get("metric_value_decimal") is None or not row.get("calculated_at"):
            raise DerivedMetricSeriesError("available derived_metric lacks value or calculation timestamp")
    elif row["calculation_status"] == "UNAVAILABLE":
        if row.get("metric_value_decimal") is not None or not row.get("unavailable_reason"):
            raise DerivedMetricSeriesError("unavailable derived_metric requires reason and no value")
    else:
        raise DerivedMetricSeriesError("derived_metric has unsupported calculation status")
    lineage = tuple(row["ordered_input_lineage"])
    candidate_ids = tuple(row["ordered_input_candidate_ids"])
    fact_ids = tuple(row["ordered_input_analytical_fact_ids"])
    if len(candidate_ids) != len(lineage) or len(fact_ids) != len(lineage):
        raise DerivedMetricSeriesError("derived_metric has incomplete source input lineage")
    if row["calculation_status"] == "AVAILABLE":
        if not lineage:
            raise DerivedMetricSeriesError("available derived_metric lacks source input lineage")
        if row.get("input_lineage_status") not in {None, "COMPLETE"}:
            raise DerivedMetricSeriesError("available derived_metric has incomplete source input lineage")
    elif not lineage:
        # M1 may publish a diagnostic-only UNAVAILABLE evaluation when M6 had
        # no compatible input candidates. It is a governed result, not a
        # missing provenance error, and no fallback may be selected.
        if row.get("input_lineage_status") != "NO_COMPATIBLE_INPUTS":
            raise DerivedMetricSeriesError(
                "unavailable derived_metric without inputs lacks no-input diagnostic status"
            )
        if candidate_ids or fact_ids:
            raise DerivedMetricSeriesError(
                "unavailable no-input derived_metric claims source input IDs"
            )
        if row.get("metric_input_compatibility_status") != "UNAVAILABLE":
            raise DerivedMetricSeriesError(
                "unavailable no-input derived_metric requires M6 UNAVAILABLE compatibility"
            )
        if row.get("metric_input_diagnostic_reason") not in _NO_COMPATIBLE_INPUT_REASONS:
            raise DerivedMetricSeriesError(
                "unavailable no-input derived_metric lacks approved no-compatible-input diagnostic"
            )
    elif row.get("input_lineage_status") == "NO_COMPATIBLE_INPUTS":
        raise DerivedMetricSeriesError(
            "unavailable derived_metric with inputs claims no-input diagnostic status"
        )
    if row["view"] == "CURRENT_COMPARABLE":
        for input_row in row["ordered_input_lineage"]:
            source_type = input_row.get("source_type")
            if source_type == "RECAST_REPORTED" and not input_row.get("recast_evidence_id"):
                raise DerivedMetricSeriesError(
                    "current-comparable metric input lacks recast evidence provenance"
                )
            if source_type == "DERIVED_RECAST" and not (
                input_row.get("source_fact_ids") and input_row.get("derivation_rule_version")
            ):
                raise DerivedMetricSeriesError(
                    "current-comparable derived input lacks recast derivation provenance"
                )
            if source_type not in {"RECAST_REPORTED", "DERIVED_RECAST"}:
                raise DerivedMetricSeriesError(
                    "current-comparable metric input is not evidence-governed"
                )


def _validate_candidate(row: Mapping[str, Any]) -> None:
    _validate_record(row)
    required = ("metric_series_candidate_id", "metric_series_key", "metric_series_family_key", "metric_revision_id", "metric_revision_as_of_date", "source_metric_run_version", "source_metric_run_fingerprint", "source_metric_manifest_identity", "metric_series_contract_version")
    missing = [key for key in required if row.get(key) is None]
    if missing:
        raise DerivedMetricSeriesError("metric series candidate lacks: " + ", ".join(missing))
    if row["metric_series_contract_version"] != DERIVED_METRIC_SERIES_CONTRACT_VERSION:
        raise DerivedMetricSeriesError("unsupported metric series candidate contract")
    if str(row["metric_revision_id"]) != str(row["derived_metric_id"]):
        raise DerivedMetricSeriesError("metric revision does not identify its derived_metric")
    if str(row["metric_revision_as_of_date"]) != str(row["as_of_date"]):
        raise DerivedMetricSeriesError("metric revision as-of date differs from materialized record")


def _select_as_filed(rows: list[dict[str, Any]], as_of_date: str) -> list[dict[str, Any]]:
    periods: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        periods[str(row["period_key"])].append(row)
    return [_selected(min(items, key=_candidate_order), as_of_date, "AS_FILED") for items in periods.values()]


def _select_current_comparable(rows: list[dict[str, Any]], as_of_date: str) -> list[dict[str, Any]]:
    # A metric is comparable only when it was itself materialized from the
    # governed L2 current-comparable view.  The basis is never inferred from a
    # formula, display label, or calculation timestamp.
    available = [row for row in rows if row["calculation_status"] == "AVAILABLE"]
    if not available:
        return [_unavailable(items, as_of_date, "NO_AVAILABLE_METRIC_IN_COMPARABLE_BASIS") for items in _by_period(rows).values()]
    by_basis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in available:
        by_basis[str(row["basis_version"])].append(row)
    basis = max(by_basis, key=lambda value: max(_candidate_order(row) for row in by_basis[value]))
    selected: list[dict[str, Any]] = []
    for items in _by_period(rows).values():
        same_basis = [row for row in items if str(row["basis_version"]) == basis]
        if not same_basis:
            selected.append(_unavailable(items, as_of_date, "PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS", basis))
        else:
            selected.append(_selected(max(same_basis, key=_candidate_order), as_of_date, "CURRENT_COMPARABLE"))
    return selected


def _by_period(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["period_key"])].append(row)
    return dict(sorted(grouped.items()))


def _selected(row: Mapping[str, Any], as_of_date: str, view: str) -> dict[str, Any]:
    result = deepcopy(dict(row))
    result.update({
        "metric_selection_status": result["calculation_status"],
        "metric_selection_reason": result.get("unavailable_reason"),
        "metric_selection_as_of_date": as_of_date,
        "metric_selection_view": view,
        "metric_selection_rule_version": DERIVED_METRIC_SERIES_CONTRACT_VERSION,
        "selected_metric_series_candidate_id": result["metric_series_candidate_id"],
        "selected_derived_metric_id": result["derived_metric_id"],
    })
    return result


def _unavailable(
    candidates: Iterable[Mapping[str, Any]], as_of_date: str, reason: str, basis_version: str | None = None
) -> dict[str, Any]:
    template = deepcopy(dict(next(iter(candidates))))
    template.update({
        "derived_metric_id": None,
        "metric_series_candidate_id": None,
        "metric_revision_id": None,
        "metric_revision_as_of_date": None,
        "basis_version": basis_version or template["basis_version"],
        "calculation_status": "UNAVAILABLE",
        "metric_value_decimal": None,
        "calculated_at": None,
        "unavailable_reason": reason,
        "metric_selection_status": "UNAVAILABLE",
        "metric_selection_reason": reason,
        "metric_selection_as_of_date": as_of_date,
        "metric_selection_view": "CURRENT_COMPARABLE",
        "metric_selection_rule_version": DERIVED_METRIC_SERIES_CONTRACT_VERSION,
        "selected_metric_series_candidate_id": None,
        "selected_derived_metric_id": None,
        "candidate_metric_series_candidate_ids": tuple(
            row["metric_series_candidate_id"] for row in candidates
        ),
    })
    return template


def _candidate_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["derived_metric_id"], row["cik"], row["metric_definition_id"], row["metric_definition_version"],
        _freeze(row["company_canonical_dimension_key"]), row["input_unit_semantics"],
        row["metric_unit_semantics"], row["series_type"], row["period_class"], row["period_key"],
        row["view"], row["basis_version"], row["as_of_date"], row["evaluated_at"],
    )


def _series_key(row: Mapping[str, Any]) -> str:
    # The candidate identity includes the exact period, view and basis.  This
    # prevents QTD/YTD, as-filed/current, or basis versions from coalescing.
    return _stable_id("derived-metric-series", _candidate_identity(row))


def _family_key(row: Mapping[str, Any]) -> str:
    return _stable_id("derived-metric-series-family", (
        row["cik"], row["metric_definition_id"], row["metric_definition_version"],
        _freeze(row["company_canonical_dimension_key"]), row["input_unit_semantics"],
        row["metric_unit_semantics"], row["series_type"], row["period_class"], row["view"],
    ))


def _candidate_order(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (str(row["metric_revision_as_of_date"]), str(row.get("evaluated_at") or ""), str(row.get("calculated_at") or ""), str(row["metric_revision_id"]))


def _selection_order(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (str(row["metric_definition_id"]), str(row["period_class"]), str(row["period_key"]), str(row.get("basis_version") or ""), str(row.get("selected_derived_metric_id") or ""))


def _date(value: str, field: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DerivedMetricSeriesError(f"{field} must be an ISO date") from exc


def _validate_published_run(manifest: Mapping[str, Any], records: tuple[Mapping[str, Any], ...]) -> None:
    required = (
        "run_version", "run_fingerprint", "layer2_run_fingerprint",
        "registry_contract_version", "registry_version", "contract_version",
        "output_counts", "output_content_sha256",
    )
    missing = [key for key in required if manifest.get(key) is None]
    if missing:
        raise DerivedMetricSeriesError("derived metric source manifest lacks: " + ", ".join(missing))
    declaration = {
        key: manifest[key]
        for key in (
            "run_version", "layer2_run_fingerprint", "registry_contract_version",
            "registry_version", "contract_version",
        )
    }
    if manifest["run_fingerprint"] != _sha256_json(declaration):
        raise DerivedMetricSeriesError("derived metric source manifest fingerprint does not match declaration")
    if manifest["output_counts"] != {"derived_metric": len(records)}:
        raise DerivedMetricSeriesError("derived metric source manifest count does not match JSONL")
    if manifest["output_content_sha256"] != {"derived_metric": _sha256_json(records)}:
        raise DerivedMetricSeriesError("derived metric source manifest content hash does not match JSONL")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _stable_id(prefix: str, payload: object) -> str:
    return prefix + ":" + _sha256_json(payload)[:24]


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, default=list, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
