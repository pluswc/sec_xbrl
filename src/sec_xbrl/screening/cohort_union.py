"""Same-cutoff composition of explicitly pinned, verified V3 read projections."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sec_xbrl.screening.common import (
    canonical_json,
    contained_file,
    digest_value,
    real_directory,
    regular_file,
    require_string,
    safe_new_destination,
)
from sec_xbrl.screening.runtime_projection import ScreeningRuntimeProjection

CONFIG_VERSION = "screening-cohort-union-config-v1"
VERSION = "screening-cohort-union-v1"
CONFIG_VERSION_V2 = "screening-cohort-union-config-v2"
VERSION_V2 = "screening-cohort-union-v2"
MANIFEST = "screening_cohort_union_manifest.json"


def _read_pin(pin: dict[str, str]) -> tuple[Path, dict]:
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or not Path(pin["path"]).is_absolute():
        raise ValueError("cohort union requires an explicit absolute path and SHA-256")
    path = regular_file(Path(pin["path"]), "cohort union input")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("cohort union input differs from pinned digest")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise TypeError("cohort union input must be an object")
    return path, value


def _open_members(config: dict, shared_readers: tuple = ()) -> list[Any]:
    required = {"schema_version", "dataset_id", "members"}
    if not isinstance(config, dict) or not required <= set(config) or set(config) - required - {"membership_evidence", "expose_auxiliary_owners", "latest_source_coverage"}:
        raise ValueError("unsupported cohort union configuration")
    if config["schema_version"] not in {CONFIG_VERSION, CONFIG_VERSION_V2} or not isinstance(config["members"], list) or len(config["members"]) < 2:
        raise ValueError("cohort union requires at least two explicitly pinned members")
    require_string(config["dataset_id"], "cohort union dataset ID")
    if "expose_auxiliary_owners" in config and type(config["expose_auxiliary_owners"]) is not bool:
        raise ValueError("auxiliary owner exposure requires an explicit boolean")
    if "membership_evidence" in config:
        _read_pin(config["membership_evidence"])
    members = []
    for member in config["members"]:
        if config["schema_version"] == CONFIG_VERSION_V2:
            from sec_xbrl.screening.governed_delta import MANIFEST as DELTA_MANIFEST
            from sec_xbrl.screening.governed_delta import ScreeningGovernedDeltaReader
            if not isinstance(member, dict) or set(member) != {"kind", "declaration"} or member["kind"] != "GOVERNED_DELTA":
                raise ValueError("union v2 requires explicitly typed governed delta members")
            declaration = member["declaration"]
            if (not isinstance(declaration, dict) or not {"manifest", "approval"} <= set(declaration)
                    or set(declaration) - {"manifest", "approval", "reader_source_transition"}):
                raise ValueError("union v2 delta declaration differs")
            path, manifest = _read_pin(declaration["manifest"])
            if path.name != DELTA_MANIFEST:
                raise ValueError("union v2 member manifest differs")
            for pin in declaration.values():
                _read_pin(pin)
            reader = next((item for item in shared_readers if item.root == path.parent
                           and item._manifest_sha256 == declaration["manifest"]["sha256"]), None)
            if reader is not None:
                if not isinstance(reader, ScreeningGovernedDeltaReader) or reader._declaration != declaration:
                    raise ValueError("union v2 shared delta declaration differs")
            else:
                reader = ScreeningGovernedDeltaReader(path.parent, declaration)
            members.append(reader)
            continue
        if not isinstance(member, dict) or set(member) != {"dataset_manifest", "projection"}:
            raise ValueError("cohort union member requires source and projection pins")
        path, manifest = _read_pin(member["dataset_manifest"])
        if path.name != "screening_dataset_manifest.json":
            raise ValueError("cohort union member is not an original V3 manifest")
        reader = ScreeningRuntimeProjection(path.parent, member["projection"])
        if reader.manifest != manifest or reader._manifest_sha256 != member["dataset_manifest"]["sha256"]:
            raise ValueError("cohort union member projection differs from original V3")
        members.append(reader)
    return members


def _definitions(members: list[ScreeningRuntimeProjection], attribute: str) -> list[dict]:
    definitions = {}
    for member in members:
        for row in getattr(member, attribute):
            identifier = row["metric_id"]
            if identifier in definitions and definitions[identifier] != row:
                raise ValueError("cohort union shared metric definition differs")
            definitions.setdefault(identifier, copy.deepcopy(row))
    return list(definitions.values())


def _metadata(members: list[ScreeningRuntimeProjection], owners: dict[str, ScreeningRuntimeProjection]) -> list[dict]:
    candidates: dict[str, list[tuple[ScreeningRuntimeProjection, dict]]] = {}
    for member in members:
        seen = set()
        for row in member.metadata:
            cik = row["cik"]
            if cik in seen:
                raise ValueError("cohort member metadata CIK is duplicated")
            seen.add(cik)
            candidates.setdefault(cik, []).append((member, row))
    if not set(owners) <= set(candidates):
        raise ValueError("cohort union prepared company has no metadata")
    rows = []
    for cik, sources in sorted(candidates.items()):
        if cik in owners:
            selected = [row for member, row in sources if member is owners[cik]]
            if len(selected) != 1:
                raise ValueError("cohort union prepared owner has no unique metadata")
            row = copy.deepcopy(selected[0])
        else:
            observed = [{key: value for key, value in row.items() if key != "financial_prepared"} for _, row in sources]
            row = (copy.deepcopy(observed[0]) if all(item == observed[0] for item in observed) else
                   {"cik": cik, "metadata_conflict": True, "reason": "COHORT_CANDIDATE_METADATA_CONFLICT"})
        row["financial_prepared"] = cik in owners
        rows.append(row)
    return rows


def _latest_source_coverage(config: dict, owners: dict, cutoff: str, spine: list[dict]) -> dict:
    """Verify an optional source-header witness; never create financial observations."""
    if "latest_source_coverage" not in config:
        return {}
    import polars as pl

    _, evidence = _read_pin(config["latest_source_coverage"])
    if (evidence.get("schema_version") != "screening-latest-source-coverage-v1"
            or evidence.get("financial_as_of") != cutoff or not isinstance(evidence.get("records"), list)):
        raise ValueError("latest source coverage scope differs")
    overrides = {}
    seen = set()
    buckets = {(row["calendar_year"], row["calendar_quarter"]) for row in spine}
    for record in evidence["records"]:
        cik = record["cik"]
        if cik in seen or cik not in owners:
            raise ValueError("latest source coverage CIK is duplicated or unowned")
        seen.add(cik)
        owner = owners[cik]
        owner_path, owner_manifest = _read_pin(record["owner_manifest"])
        if (owner_manifest != owner.manifest or owner_path != owner.root / "screening_dataset_manifest.json"
                or record["owner_manifest"]["sha256"] != owner._manifest_sha256):
            raise ValueError("latest source coverage owner differs")
        parent_config = owner.manifest["config"]
        _quarter_path, quarter = _read_pin({
            "path": str(Path(parent_config["quarterly_metric_root"]) / "quarterly_screening_metric_manifest.json"),
            "sha256": parent_config["quarterly_manifest_sha256"],
        })
        if quarter["financial_as_of"] != cutoff:
            raise ValueError("latest source coverage quarterly cutoff differs")
        company, = [row for row in quarter["config"]["companies"] if row["cik"] == cik]
        analysis_path, analysis = _read_pin(record["analysis_manifest"])
        if (analysis_path != Path(company["analysis_root"]) / "analysis_manifest.json"
                or record["analysis_manifest"]["sha256"] != company["analysis_manifest_sha256"]):
            raise ValueError("latest source coverage analysis parent differs")
        scope = analysis["companies"][company["ticker"]]
        if scope["as_of"] != cutoff or analysis.get("period_mode", "QUARTERLY") != "QUARTERLY":
            raise ValueError("latest source coverage analysis scope differs")
        declaration = scope["views"]["LATEST_REPORTED"]["files"]["columns"]
        header_path = contained_file(analysis_path.parent, declaration["path"], "latest source headers")
        if hashlib.sha256(header_path.read_bytes()).hexdigest() != declaration["sha256"]:
            raise ValueError("latest source coverage headers changed")
        columns = [row for row in pl.read_parquet(header_path).to_dicts()
                   if row.get("period_class") == "QTD_3M" and row.get("column_status") == "AVAILABLE"]
        dated = [row for row in columns if row.get("actual_start_date") and row.get("actual_end_date")]
        if not dated:
            raise ValueError("latest source coverage has no dated available QTD headers")
        for row in dated:
            date.fromisoformat(row["actual_start_date"])
            date.fromisoformat(row["actual_end_date"])
        end = max(row["actual_end_date"] for row in dated)
        latest_coordinate = max((row["fiscal_year"], str(row["fiscal_quarter"]))
                                for row in dated if row["actual_end_date"] == end)
        if any((row["fiscal_year"], str(row["fiscal_quarter"])) >= latest_coordinate
               for row in columns if row not in dated):
            raise ValueError("latest source coverage has unresolved undated latest headers")
        candidates = {canonical_json({"fiscal_year": row["fiscal_year"], "fiscal_quarter": row["fiscal_quarter"],
                      "period_start": row["actual_start_date"], "period_end": row["actual_end_date"],
                      "end_convention": "EXCLUSIVE"}) for row in dated if row["actual_end_date"] == end}
        if len(candidates) != 1 or canonical_json(record["latest_qtd"]) not in candidates:
            raise ValueError("latest source coverage latest tuple differs or is ambiguous")
        actual = record["latest_qtd"]
        if (date.fromisoformat(actual["period_start"]) >= date.fromisoformat(actual["period_end"])
                or date.fromisoformat(actual["period_end"]) > date.fromisoformat(cutoff) + timedelta(days=1)):
            raise ValueError("latest source coverage dates exceed source cutoff")
        inclusive = date.fromisoformat(actual["period_end"]) - timedelta(days=1)
        bucket = inclusive.year, (inclusive.month - 1) // 3 + 1
        if bucket not in buckets:
            overrides[cik] = {**copy.deepcopy(actual), "cik": cik,
                "calendar_year": bucket[0], "calendar_quarter": bucket[1],
                "bucket_status": "LATEST_SOURCE_PERIOD_NOT_PUBLISHED",
                "unavailable_reason": "LATEST_SOURCE_PERIOD_NOT_PUBLISHED",
                "reason_label": "최신 분기 조회 자료 미준비"}
    return overrides


def _compose(config: dict, members: list[ScreeningRuntimeProjection]) -> tuple[dict, dict]:
    cutoffs = {member.manifest["financial_as_of"] for member in members}
    kinds = {member.manifest["fixture_kind"] for member in members}
    spine = members[0].quarterly.manifest["global_quarter_spine"]
    if len(cutoffs) != 1 or len(kinds) != 1 or any(
        member.quarterly.manifest["global_quarter_spine"] != spine for member in members
    ):
        raise ValueError("cohort union cutoff, fixture kind or prepared spine differs")
    owners = {}
    companies = []
    for member in members:
        for company in member.companies:
            cik = company["cik"]
            if cik in owners:
                raise ValueError("cohort union prepared CIK is owned by more than one parent")
            owners[cik] = member
            companies.append(copy.deepcopy(company))
    if config["schema_version"] == CONFIG_VERSION_V2 and any(
            set(member.manifest.get("auxiliary_owners", {})) != {row["cik"] for row in member.companies}
            for member in members):
        raise ValueError("union v2 requires complete published member auxiliary ownership")
    annual = _definitions(members, "metric_definitions")
    quarterly = _definitions(members, "quarter_definitions")
    metadata_sources = [member.manifest["sources"]["metadata"] for member in members]
    metadata = {
        "kind": "SAME_CUTOFF_COHORT_METADATA_UNION", "members": copy.deepcopy(metadata_sources),
        "publication_id": "cohort-metadata-" + digest_value(metadata_sources)[:24],
    }
    body = {
        "schema_version": (VERSION_V2 if config["schema_version"] == CONFIG_VERSION_V2 else VERSION), "dataset_id": config["dataset_id"], "config": copy.deepcopy(config),
        "financial_as_of": next(iter(cutoffs)), "fixture_kind": next(iter(kinds)),
        "sources": {"metadata": metadata}, "versions": {"cohort_publication_ids": [member.publication_id for member in members]},
        "configured_ciks": sorted(owners), "metric_definitions": annual, "quarter_definitions": quarterly,
        "global_quarter_spine": copy.deepcopy(spine),
    }
    if config.get("expose_auxiliary_owners"):
        body["auxiliary_owners"] = {
            cik: (copy.deepcopy(owner.manifest["auxiliary_owners"][cik]) if config["schema_version"] == CONFIG_VERSION_V2 else
                  {"dataset_id": owner.manifest["dataset_id"], "dataset_publication_id": owner.publication_id,
                   "financial_as_of": owner.manifest["financial_as_of"], "dataset_manifest_sha256": owner._manifest_sha256})
            for cik, owner in sorted(owners.items())
        }
    if config["schema_version"] == CONFIG_VERSION_V2:
        if "latest_source_coverage" in config:
            raise ValueError("union v2 inherits only already-published latest source coverage")
        body["latest_company_periods"] = {cik: copy.deepcopy(row) for member in members
                                         for cik, row in member.latest_quarter_periods.items()}
        body["latest_source_period_guards"] = {cik: copy.deepcopy(row) for member in members
                                              for cik, row in member.latest_source_period_guards.items()}
        contexts = []
        for member in members:
            for ancestor in (member, member.parent):
                contexts.append({"scope": {"dataset_id": ancestor.manifest["dataset_id"],
                    "dataset_publication_id": ancestor.publication_id,
                    "financial_as_of": ancestor.manifest["financial_as_of"],
                    "dataset_manifest_sha256": ancestor._manifest_sha256},
                    "ciks": sorted(row["cik"] for row in ancestor.companies)})
        body["auxiliary_contexts"] = contexts
    guards = _latest_source_coverage(config, owners, next(iter(cutoffs)), spine)
    if "latest_source_coverage" in config:
        body["latest_source_period_guards"] = guards
    manifest = {**body, "publication_id": "screening-cohort-union-" + digest_value(body)[:24]}
    return manifest, {
        "companies": sorted(companies, key=lambda row: row["cik"]), "metadata": _metadata(members, owners),
        "owners": owners, "metric_definitions": annual, "quarter_definitions": quarterly,
    }


def publish_cohort_union(config_path: Path | str, destination: Path | str) -> Path:
    """Publish only an exact composition of already verified read projections."""
    path = regular_file(Path(config_path), "cohort union config")
    config = json.loads(path.read_bytes())
    manifest, _ = _compose(config, _open_members(config))
    destination = Path(destination).absolute()
    encoded = canonical_json(manifest).encode("utf-8") + b"\n"
    if destination.exists():
        if regular_file(destination / MANIFEST, "cohort union manifest").read_bytes() != encoded:
            raise ValueError("cohort union destination already has a different publication")
        return destination
    destination = safe_new_destination(destination, "cohort union")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / (".partial-cohort-union-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        (staging / MANIFEST).write_bytes(encoded)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


class ScreeningCohortUnionReader:
    """Route core and exact detail by the unique prepared owner of each CIK."""

    def __init__(self, root: Path | str, pin: dict[str, str], *, shared_readers: tuple = ()) -> None:
        self.root = real_directory(Path(root), "cohort union")
        path, manifest = _read_pin(pin)
        if path != self.root / MANIFEST or manifest.get("schema_version") not in {VERSION, VERSION_V2}:
            raise ValueError("cohort union pin differs from configured root or schema")
        self._members = _open_members(manifest["config"], shared_readers)
        expected, metadata = _compose(manifest["config"], self._members)
        if expected != manifest:
            raise ValueError("cohort union declaration differs from its exact parents")
        self.manifest = manifest
        self._manifest_sha256 = pin["sha256"]
        self.publication_id = manifest["publication_id"]
        self.companies = metadata["companies"]
        self.metadata = metadata["metadata"]
        self._owners = metadata["owners"]
        self.latest_source_period_guards = manifest.get("latest_source_period_guards", {})
        self.latest_quarter_periods = manifest.get("latest_company_periods", {})
        self.metric_definitions = metadata["metric_definitions"]
        self.quarter_definitions = metadata["quarter_definitions"]
        self.quarterly = SimpleNamespace(manifest={"global_quarter_spine": manifest["global_quarter_spine"]})
        for field in ("metric_support", "quarter_support", "quarter_period_inventory"):
            setattr(self, field, [row for member in self._members for row in getattr(member, field)])

    def rows(self, **selection: Any) -> list[dict]:
        cik = selection.get("cik")
        if cik is not None:
            owner = self._owners.get(cik)
            return owner.rows(**selection) if owner is not None else []
        return [row for member in self._members for row in member.rows(**selection)]

    def latest_rows(self, **selection: Any) -> list[dict]:
        from sec_xbrl.screening.runtime_projection import observation_rows
        cik = selection.get("cik")
        members = [self._owners[cik]] if cik in self._owners else ([] if cik is not None else self._members)
        return [row for member in members for row in observation_rows(member, latest=True, **selection)]

    def hydrate(self, row: dict, *, quarterly: bool = False) -> dict:
        return self._owners[row["cik"]].hydrate(row, quarterly=quarterly)

    def company(self, cik: str) -> dict:
        try:
            return self._owners[cik].company(cik)
        except KeyError as exc:
            raise ValueError("company is not prepared in the cohort union") from exc

    def verify_all(self) -> dict:
        return {
            "publication_id": self.publication_id, "dataset_id": self.manifest["dataset_id"],
            "fixture_kind": self.manifest["fixture_kind"], "financial_as_of": self.manifest["financial_as_of"],
            "company_count": len(self.companies), "quarter_definition_count": len(self.quarter_definitions),
            **({"auxiliary_manifest_sha256": self._manifest_sha256} if "auxiliary_owners" in self.manifest else {}),
            "quarter_observation_count": sum(member.verify_all()["quarter_observation_count"] for member in self._members),
        }
