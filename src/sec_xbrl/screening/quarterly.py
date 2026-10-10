"""Verified read-only adapter for governed quarterly screening publications."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.screening.common import (
    contained_file,
    read_json,
    real_directory,
    regular_file,
    require_cik,
    require_string,
    sha256_file,
)

MANIFEST = "quarterly_screening_metric_manifest.json"
VERSION = "quarterly-screening-metric-manifest-v1"
FILES = {
    "quarter_metric_definitions.json": "definitions",
    "quarter_metric_support.json": "support",
    "quarter_metric_observations.json": "observations",
    "quarter_period_inventory.json": "period_inventory",
}
SOURCE_KINDS = {"REPORTED", "DERIVED_QUARTER", "DERIVED_METRIC", "UNAVAILABLE"}
AVAILABILITY = {"AVAILABLE", "UNAVAILABLE"}


class QuarterlyScreeningMetricReader:
    """Read a frozen producer publication without selecting or calculating values."""

    def __init__(self, root: Path | str, *, manifest_sha256: str | None = None) -> None:
        self.root = real_directory(Path(root), "quarterly screening metric publication")
        manifest_path = regular_file(self.root / MANIFEST, "quarterly screening metric manifest")
        if manifest_sha256 is not None and sha256_file(manifest_path) != manifest_sha256:
            raise ValueError("quarterly metric manifest differs from pinned SHA-256")
        self.manifest = read_json(manifest_path, "quarterly screening metric manifest")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported quarterly screening metric publication")
        loaded: dict[str, list[dict[str, Any]]] = {}
        for filename, name in FILES.items():
            loaded[name] = self._payload(filename)
        self.definitions = loaded["definitions"]
        self.support = loaded["support"]
        self.observations = loaded["observations"]
        self.period_inventory = loaded["period_inventory"]
        self.verify_all()

    @property
    def publication_id(self) -> str:
        return require_string(self.manifest.get("publication_id"), "quarterly publication ID")

    def _payload(self, filename: str) -> list[dict[str, Any]]:
        info = self.manifest.get("files", {}).get(filename)
        if not isinstance(info, dict):
            raise TypeError("quarterly manifest file declaration is missing")
        path = contained_file(self.root, filename, "quarterly payload")
        if sha256_file(path) != info.get("sha256") or path.stat().st_size != info.get("size"):
            raise ValueError("quarterly payload changed")
        payload = read_json(path, "quarterly payload")
        records = payload.get("records") if isinstance(payload, dict) else None
        if (
            not isinstance(records, list)
            or not all(isinstance(row, dict) for row in records)
            or len(records) != info.get("record_count")
        ):
            raise ValueError("quarterly payload record count differs")
        if payload.get("fixture_kind") != self.manifest.get("fixture_kind"):
            raise ValueError("quarterly payload fixture kind differs")
        return records

    def verify_all(self) -> dict[str, Any]:
        if set(self.manifest.get("files", {})) != set(FILES):
            raise ValueError("quarterly payload file set changed")
        actual = {
            path.name
            for path in self.root.iterdir()
            if path.is_file() and path.name != MANIFEST and path.name != "MANIFEST.sha256"
        }
        if actual != set(FILES) or any(path.is_symlink() for path in self.root.iterdir()):
            raise ValueError("quarterly publication file set changed")
        spine = [
            (row.get("calendar_year"), row.get("calendar_quarter"))
            for row in self.manifest.get("global_quarter_spine", [])
        ]
        cutoff = date.fromisoformat(
            require_string(self.manifest.get("financial_as_of"), "financial as-of")
        )
        last_index = cutoff.year * 4 + (cutoff.month - 1) // 3 - 1
        expected_spine = [divmod(last_index - offset, 4) for offset in range(7, -1, -1)]
        expected_spine = [(year, quarter + 1) for year, quarter in expected_spine]
        spine_rows = self.manifest.get("global_quarter_spine", [])
        if (
            len(spine) != 8
            or spine != expected_spine
            or any(type(y) is not int or type(q) is not int for y, q in spine)
            or any(row.get("status") != "COMPLETED_BUCKET" for row in spine_rows)
        ):
            raise ValueError("quarterly publication must declare eight unique completed buckets")
        ciks = self.manifest.get("universe", {}).get("ciks")
        if not isinstance(ciks, list) or len(ciks) != self.manifest.get("universe", {}).get(
            "company_count"
        ):
            raise ValueError("quarterly company membership differs")
        ciks = [require_cik(cik) for cik in ciks]
        membership_hash = hashlib.sha256(("\n".join(ciks) + "\n").encode()).hexdigest()
        if (
            ciks != sorted(set(ciks))
            or membership_hash != self.manifest["universe"].get("company_membership_sha256")
            or membership_hash
            != self.manifest.get("annual_parent", {}).get("company_membership_sha256")
        ):
            raise ValueError("quarterly and annual company membership differ")
        definitions = {row.get("metric_id"): row for row in self.definitions}
        if (
            None in definitions
            or len(definitions) != len(self.definitions)
            or any(
                not str(metric_id).startswith(
                    "ttm_" if row.get("observation_basis") == "TTM" else "quarter_"
                )
                for metric_id, row in definitions.items()
            )
        ):
            raise ValueError("quarterly metric definitions are not unique and prefixed")
        support_keys = [(row.get("cik"), row.get("metric_id")) for row in self.support]
        observation_keys = [
            (
                row.get("cik"),
                row.get("metric_id"),
                row.get("calendar_year"),
                row.get("calendar_quarter"),
            )
            for row in self.observations
        ]
        inventory_keys = [
            (row.get("cik"), row.get("calendar_year"), row.get("calendar_quarter"))
            for row in self.period_inventory
        ]
        if (
            len(support_keys) != len(set(support_keys))
            or len(observation_keys) != len(set(observation_keys))
            or len(inventory_keys) != len(set(inventory_keys))
        ):
            raise ValueError("duplicate quarterly publication grain")
        if set(support_keys) != {(cik, metric) for cik in ciks for metric in definitions}:
            raise ValueError("quarterly support does not cover company/metric grain")
        if set(inventory_keys) != {(cik, year, quarter) for cik in ciks for year, quarter in spine}:
            raise ValueError("quarterly period inventory does not cover the fixed spine")
        if set(observation_keys) != {
            (cik, metric, year, quarter)
            for cik in ciks
            for metric in definitions
            for year, quarter in spine
        }:
            raise ValueError("quarterly observations do not cover metric/company/spine grain")
        for row in self.observations:
            self._verify_observation(row, definitions)
        self._verify_support(spine)
        self._verify_source_coherence()
        counts = self.manifest.get("counts", {})
        expected = {
            "definitions": len(self.definitions),
            "support": len(self.support),
            "observations": len(self.observations),
            "period_inventory": len(self.period_inventory),
        }
        if counts != expected:
            raise ValueError("quarterly manifest counts differ")
        return {
            "publication_id": self.publication_id,
            "fixture_kind": self.manifest["fixture_kind"],
            "financial_as_of": self.manifest["financial_as_of"],
            **expected,
        }

    def _verify_observation(
        self, row: dict[str, Any], definitions: dict[str, dict[str, Any]]
    ) -> None:
        definition = definitions.get(row.get("metric_id"))
        if (
            definition is None
            or row.get("definition_version") != definition.get("definition_version")
            or row.get("unit") != definition.get("unit")
        ):
            raise ValueError("quarterly observation differs from its definition")
        if (
            row.get("availability_status") not in AVAILABILITY
            or row.get("source_kind") not in SOURCE_KINDS
        ):
            raise ValueError("invalid quarterly observation status")
        available = row["availability_status"] == "AVAILABLE"
        if available != (row.get("value") is not None) or available == bool(row.get("reason")):
            raise ValueError("quarterly availability/value/reason disagree")
        if available:
            try:
                value = Decimal(row["value"])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("quarterly value must be an exact decimal string") from exc
            if not isinstance(row["value"], str) or not value.is_finite():
                raise ValueError("quarterly value must be an exact decimal string")
            required = (
                "period_start",
                "period_end",
                "filed_date",
                "report_date",
                "fiscal_year",
                "fiscal_quarter",
            )
            if any(row.get(field) is None for field in required):
                raise ValueError(
                    "available quarterly observation requires actual dates and fiscal labels"
                )
            if row.get("selection_as_of_date") != self.manifest.get("financial_as_of"):
                raise ValueError("quarterly observation as-of differs from publication")
            if date.fromisoformat(row["filed_date"]) > date.fromisoformat(
                self.manifest["financial_as_of"]
            ):
                raise ValueError("quarterly observation filing is after cutoff")
            if row.get("source_kind") not in definition.get("allowed_source_kinds", []):
                raise ValueError("quarterly observation source kind is not allowed")
            if row.get("period_class", definition.get("observation_basis")) != definition.get(
                "observation_basis"
            ):
                raise ValueError("quarterly observation period class differs from definition")
            if definition.get("observation_basis") == "TTM" and not row.get("basis_version"):
                raise ValueError("available TTM observation requires a basis version")
        if row.get("period_end") is not None:
            if row.get("end_convention") != "EXCLUSIVE":
                raise ValueError("quarterly period end must remain exclusive")
            inclusive = date.fromisoformat(row["period_end"]) - timedelta(days=1)
            expected_quarter = (inclusive.month - 1) // 3 + 1
            if (inclusive.year, expected_quarter) != (
                row.get("calendar_year"),
                row.get("calendar_quarter"),
            ):
                raise ValueError("quarterly bucket differs from inclusive period end")
        if not isinstance(row.get("source_lineage"), dict):
            raise TypeError("quarterly observation lineage is required")
        if available:
            anchors = [
                item for item in _nested_dicts(row["source_lineage"]) if item.get("accession")
            ]
            if not anchors:
                raise ValueError("available quarterly observation requires source anchors")
            required_anchor = {
                "accession",
                "filed_date",
                "report_date",
                "source_fact_id",
                "context_id",
                "raw_concept_qname",
                "raw_concept_namespace_uri",
                "unit",
                "period_start",
                "period_end",
                "end_convention",
                "period_class",
                "duration_days",
                "basis_version",
            }
            if any(not required_anchor.issubset(anchor) for anchor in anchors):
                raise ValueError("quarterly source anchor is incomplete")
            expected_basis = definition.get("observation_basis")
            if row["source_kind"] == "REPORTED" and any(
                anchor.get("period_class") != expected_basis for anchor in anchors
            ):
                raise ValueError("quarterly source period class differs from definition basis")

    def _verify_support(self, spine: list[tuple[int, int]]) -> None:
        for support in self.support:
            rows = [
                row
                for row in self.observations
                if row["cik"] == support["cik"] and row["metric_id"] == support["metric_id"]
            ]
            available = sum(row["availability_status"] == "AVAILABLE" for row in rows)
            source_counts = Counter(row["source_kind"] for row in rows)
            reason_counts = Counter(row["reason"] for row in rows if row.get("reason"))
            expected = {
                "fixed_bucket_count": len(spine),
                "available_bucket_count": available,
                "unavailable_bucket_count": len(spine) - available,
                "source_kind_counts": dict(sorted(source_counts.items())),
                "unavailable_reason_counts": dict(sorted(reason_counts.items())),
            }
            if any(support.get(key) != value for key, value in expected.items()):
                raise ValueError("quarterly support counts differ from observations")

    def _verify_source_coherence(self) -> None:
        accession_metadata: dict[str, tuple[Any, ...]] = {}
        inventory = {
            (row["cik"], row["calendar_year"], row["calendar_quarter"]): row
            for row in self.period_inventory
        }
        for observation in self.observations:
            anchors = [
                row for row in _nested_dicts(observation["source_lineage"]) if row.get("accession")
            ]
            key = (
                observation["cik"],
                observation["calendar_year"],
                observation["calendar_quarter"],
            )
            if inventory[key]["bucket_status"] == "NO_FILING_AS_OF_CUTOFF" and anchors:
                raise ValueError("no-filing bucket contains source filing lineage")
            for row in anchors:
                start = row.get("period_start")
                end = row.get("period_end")
                if start is not None and end is not None:
                    duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
                    if row.get("duration_days") != duration:
                        raise ValueError("source period duration differs from its dates")
                    period_class = row.get("period_class")
                    permitted_hold = (
                        observation["availability_status"] == "UNAVAILABLE"
                        and observation.get("reason") == "UNSUPPORTED_FISCAL_QUARTER_DURATION"
                    )
                    if (
                        period_class == "QTD_3M"
                        and not 75 <= duration <= 105
                        and not permitted_hold
                    ):
                        raise ValueError("QTD source duration is outside the governed range")
                    if period_class == "YTD_6M" and not 150 <= duration <= 210:
                        raise ValueError("YTD source duration is outside the governed range")
                accession = str(row["accession"])
                metadata = tuple(
                    row.get(field) for field in ("filed_date", "report_date", "filing_id")
                )
                prior = accession_metadata.setdefault(accession, metadata)
                if prior != metadata:
                    raise ValueError("accession source metadata is inconsistent")

    def copy_observations(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.observations)


def _nested_dicts(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        rows.append(value)
        for child in value.values():
            rows.extend(_nested_dicts(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_nested_dicts(child))
    return rows
