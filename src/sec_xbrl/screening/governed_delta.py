"""An explicitly approved, immutable correction over one shared prepared union."""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from sec_xbrl.metrics.governed_corrections import (
    REVENUE_VERSION,
    adopt_revenue_version,
    checked_file,
    prepare_latest_quarter,
    prepare_revenue_bridge,
    quarter_name,
)
from sec_xbrl.screening.cohort_union import MANIFEST as UNION_MANIFEST
from sec_xbrl.screening.cohort_union import ScreeningCohortUnionReader
from sec_xbrl.screening.common import (
    canonical_json,
    digest_value,
    safe_new_destination,
    sha256_file,
)
from sec_xbrl.screening.runtime_projection import (
    compact_observation,
    hydrate_observation,
    observation_rows,
)

VERSION = "screening-governed-delta-v1"
CONFIG_VERSION = "screening-governed-delta-config-v1"
APPROVAL_VERSION = "screening-governed-delta-approval-v1"
MANIFEST = "screening_governed_delta_manifest.json"
PAYLOAD = "governed_observations.json"

def _source_hashes(source_root: Path | None = None) -> dict[str, str]:
    root = Path(__file__).parents[1] if source_root is None else source_root
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("governed source root must be absolute without aliases")
    result = {str(path.relative_to(root)): sha256_file(checked_file(_pin(path)))
              for path in sorted(root.rglob("*.py"))}
    bridge = root.parent.parent / "examples/screening/windows-loopback-bridge.cjs"
    result["examples/screening/windows-loopback-bridge.cjs"] = sha256_file(bridge)
    return result


def _pin(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256_file(path)}


def _load(pin: dict) -> dict:
    return json.loads(checked_file(pin).read_bytes())


def _parent(pin: dict) -> ScreeningCohortUnionReader:
    path = checked_file(pin)
    if path.name != UNION_MANIFEST:
        raise ValueError("governed delta requires an exact cohort-union parent")
    return ScreeningCohortUnionReader(path.parent, pin)


def _full(reader: Any, *, cik: str, metric_id: str, year: int) -> dict:
    rows = observation_rows(reader, cik=cik, metric_id=metric_id, year=year)
    if len(rows) != 1:
        raise ValueError("governed delta annual input is not unique")
    return hydrate_observation(reader, rows[0])


def _prior(reader: Any, request: dict, original: dict) -> tuple[dict, list[dict]]:
    year = request["fiscal_year"] - 1
    rows = observation_rows(reader, cik=request["cik"], metric_id="revenue", year=year)
    if len(rows) == 1:
        return hydrate_observation(reader, rows[0]), []
    # The five-year source snapshot retains the first display year's prior input.
    from sec_xbrl.metrics.screening import _reported_observations

    snapshot = _load(request["prior_source_snapshot"])
    if snapshot["snapshot_id"] not in original["source_snapshot_id"] or snapshot["cik"] != request["cik"]:
        raise ValueError("governed delta prior source snapshot differs")
    reported = _reported_observations(ticker=original["ticker"], cik=request["cik"],
        financial_as_of=original["financial_as_of"], snapshot=snapshot, years=[year])
    selected = [row for row in reported if row["metric_id"] == "revenue" and row["fiscal_year"] == year]
    if len(selected) != 1 or selected[0]["metric_observation_id"] != original["input_observation_ids"][1]:
        raise ValueError("governed delta prior original observation identity differs")
    return selected[0], [request["prior_source_snapshot"]]


def publish_governed_delta(config_path: Path | str, destination: Path | str,
                           *, parent: Any = None) -> Path:
    """Prepare a candidate. A separate ROOT receipt is required before any runtime use."""
    config_path = Path(config_path).absolute()
    config = json.loads(config_path.read_bytes())
    if (config.get("schema_version") != CONFIG_VERSION or not isinstance(config.get("dataset_id"), str)
            or not {"schema_version", "dataset_id", "parent"} <= set(config)
            or set(config) - {"schema_version", "dataset_id", "parent", "annual_bridges", "latest_quarters"}
            or not isinstance(config.get("annual_bridges", []), list)
            or not isinstance(config.get("latest_quarters", []), list)):
        raise ValueError("unsupported governed delta configuration")
    parent = _parent(config["parent"]) if parent is None else parent
    parent_path = checked_file(config["parent"])
    if parent_path.parent != parent.root or parent._manifest_sha256 != config["parent"]["sha256"]:
        raise ValueError("governed delta parent reader differs")
    cutoff = parent.manifest["financial_as_of"]
    originals = observation_rows(parent, metric_id="revenue_yoy")
    annual = {(row["cik"], row["fiscal_year"]): adopt_revenue_version(row) for row in originals}
    if len(annual) != len(originals):
        raise ValueError("governed delta parent annual grain differs")
    seen = set()
    inputs = [config["parent"]]
    for request in config.get("annual_bridges", []):
        key = request["cik"], request["fiscal_year"]
        if key in seen or key not in annual:
            raise ValueError("governed delta annual request is duplicated or outside parent")
        seen.add(key)
        current = _full(parent, cik=key[0], metric_id="revenue", year=key[1])
        original = _full(parent, cik=key[0], metric_id="revenue_yoy", year=key[1])
        prior, extra = _prior(parent, request, original)
        annual[key] = prepare_revenue_bridge(current=current, prior=prior, original=original,
            raw=request["raw"], package_root=Path(request["package_root"]), financial_as_of=cutoff)
        raw = request["raw"]
        raw_root = Path(raw["manifest"]["path"]).parent
        inputs += [raw["manifest"], *extra]
        inputs += [{"path": str(raw_root / f"{name}.parquet"), "sha256": digest}
                   for name, digest in raw["table_sha256"].items()]
        filing = annual[key]["continuity_proof"]["filing"]
        package = Path(request["package_root"]) / key[0] / filing["accession"].replace("-", "")
        inputs += [_pin(package / "manifest.json"), {"path": str(package / (filing["accession"] + "-xbrl.zip")),
                                                    "sha256": filing["package_hash"]}]
    quarter, periods = [], []
    requested = set()
    for request in config.get("latest_quarters", []):
        cik = request["cik"]
        if cik in requested or cik not in parent._owners:
            raise ValueError("governed delta latest CIK is duplicated or unowned")
        requested.add(cik)
        owner = parent._owners[cik]
        if request["owner_manifest"] != {"path": str(owner.root / "screening_dataset_manifest.json"),
                                         "sha256": owner._manifest_sha256}:
            raise ValueError("governed delta latest owner differs")
        owner_config = owner.manifest["config"]
        expected_quarter = {"path": str(Path(owner_config["quarterly_metric_root"]) / "quarterly_screening_metric_manifest.json"),
                            "sha256": owner_config["quarterly_manifest_sha256"]}
        if request["quarterly_manifest"] != expected_quarter:
            raise ValueError("governed delta latest quarter parent differs")
        anchor = parent.latest_source_period_guards.get(cik)
        if anchor is None:
            raise ValueError("governed delta latest request must resolve a pinned unpublished source period")
        records, inventory, touched = prepare_latest_quarter(
            analysis_manifest=request["analysis_manifest"], ticker=request["ticker"], cik=cik,
            financial_as_of=cutoff, latest=anchor, quarterly_manifest=expected_quarter)
        quarter.extend(records)
        periods.extend(inventory)
        inputs += [request["owner_manifest"], expected_quarter, request["analysis_manifest"], *touched]
    from sec_xbrl.metrics.screening import _support_rows

    annual_records = [annual[key] for key in sorted(annual)]
    support = [row for row in _support_rows(parent.companies, annual_records) if row["metric_id"] == "revenue_yoy"]
    old_support = {row["cik"]: row for row in parent.metric_support if row["metric_id"] == "revenue_yoy"}
    support = [{**old_support[row["cik"]], **row, "definition_version": REVENUE_VERSION,
                "reason": (row["reasons"] or [None])[0]} for row in support]
    represented = {row["cik"] for row in annual_records}
    for row in support:
        if row["cik"] not in represented:
            # An admitted quarter-only company retains its published annual absence reason.
            old = old_support[row["cik"]]
            row["reasons"] = copy.deepcopy(old.get("reasons") or ([old["reason"]] if old.get("reason") else []))
            row["reason"] = (row["reasons"] or [None])[0]
    payload = {"schema_version": VERSION, "annual_records": annual_records, "annual_support": support,
               "quarter_records": quarter, "latest_quarter_periods": periods}
    _validate_payload(payload, parent)
    destination = safe_new_destination(Path(destination), "governed delta publication")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / (".partial-governed-delta-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        (staging / PAYLOAD).write_text(canonical_json(payload) + "\n")
        definitions = copy.deepcopy(parent.metric_definitions)
        for row in definitions:
            if row["metric_id"] == "revenue_yoy":
                row["definition_version"] = REVENUE_VERSION
                row["continuity_policy"] = "EXACT_SAME_FILING_PRIMARY_PRIOR_REVENUE"
        body = {"schema_version": VERSION, "dataset_id": config["dataset_id"], "parent": copy.deepcopy(config["parent"]),
                "financial_as_of": cutoff, "fixture_kind": parent.manifest["fixture_kind"],
                "config": config, "config_pin": _pin(config_path), "implementation_sources": _source_hashes(),
                "sources": copy.deepcopy(parent.manifest["sources"]), "versions": {"governed_delta": VERSION},
                "configured_ciks": sorted(row["cik"] for row in parent.companies),
                "metric_definitions": definitions, "quarter_definitions": copy.deepcopy(parent.quarter_definitions),
                "global_quarter_spine": copy.deepcopy(parent.manifest["global_quarter_spine"]),
                "auxiliary_owners": copy.deepcopy(parent.manifest.get("auxiliary_owners", {})),
                "inputs": inputs, "payload": {"path": PAYLOAD, "sha256": sha256_file(staging / PAYLOAD)}}
        body["publication_id"] = "screening-governed-delta-" + digest_value(body)[:24]
        (staging / MANIFEST).write_text(canonical_json(body) + "\n")
        for pin in [body["config_pin"], *inputs]:
            checked_file(pin)
        if _source_hashes() != body["implementation_sources"]:
            raise ValueError("governed delta implementation changed before promotion")
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def _core(row: dict) -> dict:
    return {key: value for key, value in compact_observation(row).items() if key != "continuity_proof"}


def _validate_payload(payload: dict, parent: Any) -> None:
    annual = payload["annual_records"]
    old = {(row["cik"], row["fiscal_year"]): row for row in observation_rows(parent, metric_id="revenue_yoy")}
    if len(annual) != len(old) or {(row["cik"], row["fiscal_year"]) for row in annual} != set(old):
        raise ValueError("governed delta annual adoption coverage differs")
    for row in annual:
        original = old[row["cik"], row["fiscal_year"]]
        if (row["metric_id"] != "revenue_yoy" or row["metric_definition_version"] != REVENUE_VERSION
                or row["original_observation"]["id"] != original["metric_observation_id"]):
            raise ValueError("governed delta annual adoption identity differs")
        if "continuity_proof" not in row:
            if row != adopt_revenue_version(original):
                raise ValueError("governed delta unchanged annual payload differs")
        elif (original["availability_status"] != "UNAVAILABLE"
              or row["continuity_proof"]["rule_version"] != "same-filing-primary-revenue-exact-prior-v1"
              or row["proof_available_on"] > parent.manifest["financial_as_of"]):
            raise ValueError("governed delta annual replacement differs")
    from sec_xbrl.metrics.quarterly_screening import _observation_id

    periods = {row["cik"]: row for row in payload["latest_quarter_periods"]}
    if len(periods) != len(payload["latest_quarter_periods"]):
        raise ValueError("governed delta latest period is duplicated")
    if set(periods) != {row["cik"] for row in payload["quarter_records"]}:
        raise ValueError("governed delta latest inventory and observations differ")
    for cik in periods:
        expected_ids = {row["metric_id"] for row in parent._owners[cik].quarter_definitions}
        if {row["metric_id"] for row in payload["quarter_records"] if row["cik"] == cik} != expected_ids:
            raise ValueError("governed delta latest metric coverage differs")
    seen = set()
    original_ids = {row["observation_id"] for row in observation_rows(parent, quarterly=True)}
    definitions = {row["metric_id"]: row for row in parent.quarter_definitions}
    for row in payload["quarter_records"]:
        key = (row["cik"], row["metric_id"], row["calendar_year"], row["calendar_quarter"])
        period = periods.get(row["cik"])
        if key in seen or period is None or period["bucket_status"] != "PERIOD_AVAILABLE":
            raise ValueError("governed delta quarterly record grain differs")
        seen.add(key)
        if (row["observation_id"] in original_ids or row["observation_id"] != _observation_id(row)
                or row.get("definition_version") != definitions.get(row["metric_id"], {}).get("definition_version")
                or row.get("selection_as_of_date") != parent.manifest["financial_as_of"]):
            raise ValueError("governed delta quarterly identity or definition differs")
        if (row["metric_id"] not in {d["metric_id"] for d in parent.quarter_definitions}
                or (row["calendar_year"], row["calendar_quarter"]) != (period["calendar_year"], period["calendar_quarter"])):
            raise ValueError("governed delta quarterly period differs")
        expected = parent.latest_source_period_guards.get(row["cik"])
        if (expected is None or quarter_name(period["fiscal_quarter"]) != quarter_name(expected["fiscal_quarter"])
                or any(period.get(k) != expected.get(k) for k in ("fiscal_year", "period_start", "period_end"))):
            raise ValueError("governed delta latest source identity differs")


class ScreeningGovernedDeltaReader:
    """Read approved published values and share all unaffected data with the parent."""

    def __init__(self, root: Path | str, declaration: dict, *, parent: Any = None) -> None:
        self.root = Path(root)
        path = checked_file(declaration["manifest"])
        if path != self.root / MANIFEST:
            raise ValueError("governed delta manifest root differs")
        manifest = _load(declaration["manifest"])
        approval = _load(declaration["approval"])
        if (manifest.get("schema_version") != VERSION or approval != {
                "schema_version": APPROVAL_VERSION, "status": "ROOT_APPROVED_GOVERNED_DELTA",
                "manifest": declaration["manifest"], "implementation_sources": manifest["implementation_sources"]}
                or not _reader_sources_match(manifest, declaration)):
            raise ValueError("governed delta requires exact ROOT-approved current source and artifact")
        if (_load(manifest["config_pin"]) != manifest["config"]
                or manifest["parent"] != manifest["config"]["parent"]
                or manifest["dataset_id"] != manifest["config"]["dataset_id"]):
            raise ValueError("governed delta configured scope differs")
        for pin in manifest["inputs"]:
            checked_file(pin)
        self.parent = _parent(manifest["parent"]) if parent is None else parent
        if (self.parent._manifest_sha256 != manifest["parent"]["sha256"]
                or self.parent.root != Path(manifest["parent"]["path"]).parent
                or manifest["financial_as_of"] != self.parent.manifest["financial_as_of"]
                or manifest["configured_ciks"] != sorted(row["cik"] for row in self.parent.companies)
                or manifest["auxiliary_owners"] != self.parent.manifest.get("auxiliary_owners", {})
                or manifest["sources"] != self.parent.manifest["sources"]
                or manifest["fixture_kind"] != self.parent.manifest["fixture_kind"]
                or manifest["quarter_definitions"] != self.parent.quarter_definitions
                or manifest["global_quarter_spine"] != self.parent.manifest["global_quarter_spine"]):
            raise ValueError("governed delta shared parent or owner scope differs")
        payload_path = self.root / manifest["payload"]["path"]
        if payload_path != self.root / PAYLOAD:
            raise ValueError("governed delta payload path differs")
        payload = _load({"path": str(payload_path), "sha256": manifest["payload"]["sha256"]})
        _validate_payload(payload, self.parent)
        body = {k: v for k, v in manifest.items() if k != "publication_id"}
        if manifest["publication_id"] != "screening-governed-delta-" + digest_value(body)[:24]:
            raise ValueError("governed delta publication identity differs")
        self.manifest = manifest
        self._declaration = copy.deepcopy(declaration)
        self.publication_id = manifest["publication_id"]
        self._manifest_sha256 = declaration["manifest"]["sha256"]
        self.companies, self.metadata = self.parent.companies, self.parent.metadata
        self.metric_definitions, self.quarter_definitions = manifest["metric_definitions"], manifest["quarter_definitions"]
        self.quarterly = self.parent.quarterly
        self._owners = self.parent._owners
        support = {row["cik"]: row for row in payload["annual_support"]}
        self.metric_support = [support[row["cik"]] if row["metric_id"] == "revenue_yoy" else row
                               for row in self.parent.metric_support]
        self.quarter_support = self.parent.quarter_support
        self.quarter_period_inventory = self.parent.quarter_period_inventory
        self.latest_quarter_periods = {row["cik"]: row for row in payload["latest_quarter_periods"]}
        self.latest_source_period_guards = {cik: row for cik, row in self.parent.latest_source_period_guards.items()
                                           if cik not in self.latest_quarter_periods}
        self._annual = payload["annual_records"]
        self._quarter = payload["quarter_records"]
        self._details = {row.get("metric_observation_id", row.get("observation_id")): row
                         for row in [*self._annual, *self._quarter]}

    def rows(self, **selection: Any) -> list[dict]:
        rows = self.parent.rows(**selection)
        if selection.get("quarterly"):
            return rows
        rows = [row for row in rows if row["metric_id"] != "revenue_yoy"]
        rows += [_core(row) for row in self._annual if self._matches(row, selection, quarterly=False)]
        return rows

    def latest_rows(self, **selection: Any) -> list[dict]:
        rows = self.rows(**selection)
        if selection.get("quarterly"):
            rows += [compact_observation(row) for row in self._quarter if self._matches(row, selection, quarterly=True)]
        return rows

    @staticmethod
    def _matches(row: dict, selection: dict, *, quarterly: bool) -> bool:
        keys = {"cik": "cik", "metric_id": "metric_id", "year": "calendar_year" if quarterly else "fiscal_year",
                "quarter": "calendar_quarter"}
        return all(selection.get(k) is None or row.get(field) == selection[k] for k, field in keys.items())

    def hydrate(self, row: dict, *, quarterly: bool = False) -> dict:
        key = row.get("metric_observation_id", row.get("observation_id"))
        if key not in self._details:
            return self.parent.hydrate(row, quarterly=quarterly)
        record = self._details[key]
        if not quarterly and "continuity_proof" not in record:
            original = _full(self.parent, cik=record["cik"], metric_id="revenue_yoy", year=record["fiscal_year"])
            if original["metric_observation_id"] != record["original_observation"]["id"]:
                raise ValueError("governed delta original detail identity differs")
            return adopt_revenue_version(original)
        return copy.deepcopy(record)

    def company(self, cik: str) -> dict:
        return self.parent.company(cik)

    def verify_all(self) -> dict:
        return {**self.parent.verify_all(), "dataset_id": self.manifest["dataset_id"],
                "publication_id": self.publication_id, "auxiliary_manifest_sha256": self._manifest_sha256,
                "latest_supplement_observation_count": len(self._quarter)}


def _reader_sources_match(manifest: dict, declaration: dict) -> bool:
    """Explicit per-artifact read grant; never enters a producer/native context."""
    current = _source_hashes()
    transition = declaration.get("reader_source_transition")
    if transition is None:
        return manifest["implementation_sources"] == current
    from sec_xbrl.financial_native_source import (
        qualified_consumer_files,
        qualified_preparation_consumer_files,
    )

    receipt = _load(transition)
    fields = {"schema_version", "status", "manifest", "approval", "origin_source_root",
              "origin_implementation_sources", "current_implementation_sources", "consumer_baseline_files"}
    v2 = receipt.get("schema_version") == "governed-delta-reader-source-transition-v2"
    if v2:
        fields.add("previous_declaration")
    if (set(receipt) != fields or receipt["schema_version"] not in {"governed-delta-reader-source-transition-v1", "governed-delta-reader-source-transition-v2"}
            or receipt["status"] != "ROOT_APPROVED_READER_ONLY_SOURCE_TRANSITION"
            or receipt["manifest"] != declaration["manifest"] or receipt["approval"] != declaration["approval"]
            or receipt["origin_implementation_sources"] != manifest["implementation_sources"]
            or receipt["current_implementation_sources"] != current):
        raise ValueError("governed delta reader source transition scope differs")
    origin = _source_hashes(Path(receipt["origin_source_root"]))
    if origin != manifest["implementation_sources"]:
        raise ValueError("governed delta reader accepted origin differs")
    if v2:
        previous = receipt["previous_declaration"]
        if (not isinstance(previous, dict) or not {"manifest", "approval"} <= set(previous)
                or set(previous) - {"manifest", "approval", "reader_source_transition"}
                or previous["manifest"] != declaration["manifest"] or previous["approval"] != declaration["approval"]):
            raise ValueError("governed reader previous declaration differs")
        for pin in previous.values():
            checked_file(pin)
    qualifier = qualified_preparation_consumer_files if v2 else qualified_consumer_files
    qualifier(receipt["consumer_baseline_files"], {key: value for key, value in current.items() if key.endswith(".py")})
    # Only the bounded owner-context consumer bridge may change; its exact bytes are root-pinned above.
    return True


def shared_reader_declaration_matches(reader: ScreeningGovernedDeltaReader, previous: dict) -> bool:
    """Only a separately verified read-only receipt can replace immutable source admission."""
    if reader._declaration == previous:
        return True
    transition = reader._declaration.get("reader_source_transition")
    if transition is None:
        return False
    receipt = _load(transition)
    return (receipt.get("schema_version") == "governed-delta-reader-source-transition-v2"
            and receipt.get("previous_declaration") == previous
            and receipt.get("manifest") == reader._declaration["manifest"]
            and receipt.get("approval") == reader._declaration["approval"])
