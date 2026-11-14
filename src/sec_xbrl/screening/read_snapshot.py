"""Explicitly ROOT-approved immutable read snapshots; no upstream source authority."""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from sec_xbrl.screening.common import (
    contained_file,
    digest_value,
    real_directory,
    regular_file,
    sha256_file,
)

VERSION = "screening-read-snapshot-v1"
MANIFEST = "screening_read_snapshot_manifest.json"


def observation_identity(row: dict) -> str:
    return row.get("metric_observation_id") or row.get("observation_id") or "legacy-coordinate-" + digest_value(
        {key: row.get(key) for key in ("cik", "metric_id", "fiscal_year", "period_class", "view")})


def read_pin(pin: dict) -> dict:
    path = regular_file(Path(pin["path"]), "snapshot pin")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("snapshot pin differs")
    return json.loads(data)


class ScreeningReadSnapshot:
    """Expose the original logical scope only after exact independent ROOT approval."""

    def __init__(self, root: Path | str, declaration: dict) -> None:
        self.root = real_directory(Path(root), "read snapshot")
        data = read_pin(declaration["manifest"])
        if Path(declaration["manifest"]["path"]).resolve() != self.root / MANIFEST:
            raise ValueError("snapshot root differs")
        if Path(declaration["verification"]["path"]).resolve() != self.root / "verification.json":
            raise ValueError("snapshot verification file differs from publication")
        receipt = read_pin(declaration["verification"])
        approval = read_pin(declaration["approval"])
        body = {key: value for key, value in data.items() if key != "logical_sha256"}
        if (data.get("schema_version") != VERSION or data.get("reader_version") != VERSION
            or data.get("logical_sha256") != digest_value(body)
            or receipt != {"schema_version": "screening-read-export-verification-v1", "verified": True,
                "manifest_sha256": declaration["manifest"]["sha256"],
                "logical_sha256": data["logical_sha256"], "origin": data["origin"]}):
            raise ValueError("snapshot verification or logical contract differs")
        expected = {"schema_version": "screening-read-snapshot-root-approval-v1", "authority": "ROOT",
                    "approved": True, "reader_version": VERSION,
                    "manifest_sha256": declaration["manifest"]["sha256"],
                    "verification_sha256": declaration["verification"]["sha256"],
                    "logical_sha256": data["logical_sha256"], "origin": data["origin"]}
        if approval != expected:
            raise ValueError("snapshot requires exact separate ROOT approval")
        self._snapshot = data
        properties = data["properties"]
        self.manifest = copy.deepcopy(properties["original_manifest"])
        self._manifest_sha256 = properties["original_manifest_sha256"]
        self.publication_id = self.manifest["publication_id"]
        self.logical_sha256 = data["logical_sha256"]
        allowed_properties = {"companies", "metadata", "metric_definitions", "metric_support", "quarter_definitions",
            "quarter_support", "quarter_period_inventory", "latest_source_period_guards", "latest_quarter_periods",
            "original_manifest", "original_manifest_sha256", "status", "quarterly_manifest", "capabilities", "reader_contract", "row_order"}
        if set(properties) - allowed_properties or properties.get("capabilities") not in (
            {"explorer": False, "quarterly": False}, {"explorer": True, "quarterly": False},
            {"explorer": True, "quarterly": True}):
            raise ValueError("snapshot public reader contract differs")
        for key, value in properties.items():
            if key not in {"original_manifest", "original_manifest_sha256", "status", "quarterly_manifest"}:
                setattr(self, key, copy.deepcopy(value))
        self.quarterly = SimpleNamespace(manifest=copy.deepcopy(properties["quarterly_manifest"]))
        ciks = [company["cik"] for company in self.companies]
        if len(set(ciks)) != len(ciks) or set(ciks) != set(data["files"]):
            raise ValueError("snapshot company ownership differs")
        self._company_data = lru_cache(maxsize=2)(self._load_company)
        self._cores = {}
        self._companies = {}
        for cik in ciks:
            payload = self._load_company(cik)
            if payload["company"].get("cik") != cik:
                raise ValueError("snapshot company metadata owner differs")
            self._companies[cik] = payload["company"]
            if set(payload["views"]) != {"annual", "quarter", "annual_latest", "quarter_latest"}:
                raise ValueError("snapshot period views incomplete")
            self._cores[cik] = payload["views"]
            from sec_xbrl.screening.runtime_projection import _split
            used = set()
            for rows in payload["views"].values():
                identities = [observation_identity(row) for row in rows]
                if len(set(identities)) != len(identities):
                    raise ValueError("snapshot observation coordinate is duplicated")
                for row, identity in zip(rows, identities, strict=True):
                    full = payload["details"].get(identity)
                    if row["cik"] != cik or full is None or observation_identity(full) != identity:
                        raise ValueError("snapshot row owner or evidence identity differs")
                    core, _ = _split(full)
                    core.pop("comparison_evidence", None)
                    if core != row:
                        raise ValueError("snapshot core differs from original evidence")
                    used.add(identity)
            if used != set(payload["details"]):
                raise ValueError("snapshot has unreferenced evidence")
        if hasattr(self, "row_order"):
            if set(self.row_order) != {"annual", "quarter", "annual_latest", "quarter_latest"}:
                raise ValueError("snapshot global view ordering differs")
            for view, ordering in self.row_order.items():
                expected_order_ids = [observation_identity(row) for views in self._cores.values() for row in views[view]]
                if len(ordering) != len(set(ordering)) or set(ordering) != set(expected_order_ids):
                    raise ValueError("snapshot global observation ordering differs")
        expected_files = {MANIFEST, "verification.json", *[pin["path"] for pin in data["files"].values()]}
        # Approval is intentionally external; unexpected content is never silently accepted.
        if {str(path.relative_to(self.root)) for path in self.root.iterdir()} != expected_files:
            raise ValueError("snapshot inventory differs")

    def _load_company(self, cik: str) -> dict:
        pin = self._snapshot["files"][cik]
        path = contained_file(self.root, pin["path"], "snapshot company")
        if sha256_file(path) != pin["sha256"]:
            raise ValueError("snapshot company bytes differ")
        return json.loads(path.read_bytes())

    def _rows(self, latest: bool = False, *, quarterly: bool = False, cik: str | None = None,
              metric_id: str | None = None, year: int | None = None, quarter: int | None = None) -> list[dict]:
        name = ("quarter" if quarterly else "annual") + ("_latest" if latest else "")
        ciks = [cik] if cik in self._snapshot["files"] else ([] if cik else list(self._snapshot["files"]))
        year_field = "calendar_year" if quarterly else "fiscal_year"
        selected = [row for owner in ciks for row in self._cores[owner][name]
            if (metric_id is None or row["metric_id"] == metric_id)
            and (year is None or row[year_field] == year)
            and (quarter is None or row["calendar_quarter"] == quarter)]
        if hasattr(self, "row_order"):
            ranks = {identity: rank for rank, identity in enumerate(self.row_order[name])}
            selected.sort(key=lambda row: ranks[observation_identity(row)])
        return copy.deepcopy(selected)

    def rows(self, **selection) -> list[dict]:
        return self._rows(False, **selection)

    def latest_rows(self, **selection) -> list[dict]:
        return self._rows(True, **selection)

    def hydrate(self, row: dict, *, quarterly: bool = False) -> dict:
        identity = observation_identity(row)
        original = self._company_data(row["cik"])["details"].get(identity)
        if original is None:
            raise ValueError("snapshot evidence identity is not prepared")
        # Scalar overrides applied by period guards are retained, exactly as projections do.
        return copy.deepcopy({**original, **row, **{key: original[key] for key in ("trace", "source_lineage", "comparison_evidence") if key in original}})

    def company(self, cik: str) -> dict:
        if cik not in self._snapshot["files"]:
            raise ValueError("company is not prepared")
        return copy.deepcopy(self._companies[cik])

    def verify_all(self) -> dict:
        return copy.deepcopy(self._snapshot["properties"]["status"])
