"""Read-only provenance routing to explicitly accepted History replacements."""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.collection_operations import _attest_intake, _validate_build_attestation
from sec_xbrl.screening.common import read_json, require_cik, require_ticker, sha256_file

VERSION = "accepted-history-selection-v1"
APPROVAL_VERSION = "lead-later45-company-history-acceptance-v1"
APPROVAL_STATUS = "LOCALLY_ACCEPTED_COMPANY_HISTORY_ONLY_NOT_FINANCIAL_READY"
RECOVERY_VERSION = "universe50-history-recovery-receipt-v1"


def selection_declaration(value: Any) -> dict[str, str]:
    """Normalize an explicit immutable companion reference; aliases are rejected."""
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("History selection requires exact path/sha256 declaration")
    path, digest = value["path"], value["sha256"]
    if (not isinstance(path, str) or not Path(path).is_absolute()
        or path != str(Path(path).resolve())
        or not isinstance(digest, str) or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("History selection declaration is unsafe or malformed")
    return {"path": path, "sha256": digest}


def _pin(value: Any) -> dict[str, str]:
    declaration = selection_declaration(value)
    path = Path(declaration["path"])
    if not path.is_file() or path.is_symlink() or sha256_file(path) != declaration["sha256"]:
        raise ValueError("History selection evidence is missing, unsafe or changed")
    return declaration


@dataclass(frozen=True)
class HistorySelections:
    declaration: dict[str, str]
    companies: dict[str, dict[str, Any]]
    controls: dict[str, dict[str, str]]


def resolve_history_selection(
    declaration: dict[str, str], *, collection_manifest: Path,
    scope_companies: list[dict[str, Any]], storage_reuse: Any = None,
) -> HistorySelections:
    """Replay accepted replacement provenance without modifying collection status."""
    declaration = _pin(declaration)
    companion = read_json(Path(declaration["path"]), "accepted History selection")
    if not isinstance(companion, dict) or set(companion) != {"schema_version", "collection_manifest", "companies"} or companion.get("schema_version") != VERSION:
        raise ValueError("unsupported accepted History selection")
    collection_pin = _pin(companion["collection_manifest"])
    collection_manifest = collection_manifest.resolve()
    if collection_pin["path"] != str(collection_manifest):
        raise ValueError("History selection belongs to a different collection")
    collection = read_json(collection_manifest, "History selection collection")
    parent = {(row["ticker"], row["cik"]): row for row in collection["companies"]}
    scope = {(row["ticker"], row["cik"]) for row in scope_companies}
    entries = companion["companies"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("History selection requires explicit company entries")
    controls = {"COMPANION": declaration, "COLLECTION": collection_pin}
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"ticker", "cik", "acceptance", "recovery_receipt", "build_manifest", "history_manifest"}:
            raise ValueError("History selection company entry has unknown or missing fields")
        ticker = require_ticker(entry["ticker"], "History selection ticker")
        cik = require_cik(entry["cik"], "History selection CIK")
        if entry["ticker"] != ticker or ticker in result or (ticker, cik) not in parent or (ticker, cik) not in scope:
            raise ValueError("History selection company is duplicate or outside scope")
        pins = {name: _pin(entry[name]) for name in ("acceptance", "recovery_receipt", "build_manifest", "history_manifest")}
        approval = read_json(Path(pins["acceptance"]["path"]), "historical History acceptance")
        recovery = read_json(Path(pins["recovery_receipt"]["path"]), "accepted History recovery receipt")
        build = read_json(Path(pins["build_manifest"]["path"]), "selected History build")
        if not all(isinstance(value, dict) for value in (approval, recovery, build)):
            raise ValueError("History selection evidence must be JSON objects")
        original_path = collection_manifest.parent / "companies" / ticker / "build_manifest.json"
        original_pin = _pin({"path": str(original_path), "sha256": sha256_file(original_path)})
        original = read_json(original_path, "original collection build")
        plan_path = Path(parent[(ticker, cik)]["plan_path"])
        plan = read_json(plan_path, "original collection plan")
        intake_path = collection_manifest.parent / "companies" / ticker / "intake" / "history_intake.json"
        if (approval.get("schema_version") != APPROVAL_VERSION or approval.get("status") != APPROVAL_STATUS
            or approval.get("accepted_by") != "ROOT_LEAD" or approval.get("ticker") != ticker or approval.get("cik") != cik
            or approval.get("build_manifest") != pins["build_manifest"] or approval.get("recovery_receipt") != pins["recovery_receipt"]):
            raise ValueError("History selection lacks the exact historical lead approval")
        if (recovery.get("schema_version") != RECOVERY_VERSION or recovery.get("status") != "READY"
            or recovery.get("ticker") != ticker or recovery.get("cik") != cik
            or recovery.get("collection_manifest") != str(collection_manifest)
            or recovery.get("collection_manifest_sha256") != collection_pin["sha256"]
            or recovery.get("build_manifest") != pins["build_manifest"]["path"]
            or recovery.get("build_manifest_sha256") != pins["build_manifest"]["sha256"]
            or recovery.get("history_manifest_sha256") != pins["history_manifest"]["sha256"]
            or recovery.get("publication") != build.get("publication")
            or recovery.get("declared_files") != build.get("declared_files")
            or recovery.get("financial_as_of") != plan.get("as_of_date")):
            raise ValueError("History selection differs from its READY recovery receipt")
        if (build.get("history_manifest") != pins["history_manifest"]["path"]
            or original.get("status") != "READY"
            or any(build.get(field) != original.get(field) for field in ("ticker", "plan_sha256", "intake_manifest", "intake_sha256", "views"))
            or recovery.get("plan_sha256") != build.get("plan_sha256")
            or recovery.get("intake_sha256") != build.get("intake_sha256")
            or len(plan.get("companies", [])) != 1
            or plan["companies"][0].get("ticker") != ticker or plan["companies"][0].get("cik") != cik):
            raise ValueError("selected History must preserve the original plan, intake, views and company")
        from sec_xbrl.financial_storage_reuse import storage_history
        verify_financial_history_source(Path(build["publication"]),
            storage_entry=storage_history(storage_reuse, ticker, Path(pins["history_manifest"]["path"])))
        error = _validate_build_attestation(
            build, ticker=ticker, plan=plan, plan_sha256=sha256_file(plan_path),
            intake_path=intake_path, intake=_attest_intake(intake_path, plan),
        )
        if error:
            raise ValueError(f"selected History build failed original provenance checks: {error}")
        # Historical audits are immutable evidence blobs. Their financial assertions
        # are not re-run and their old Raw inventories are not active inputs.
        for name, pin in pins.items():
            controls[f"{ticker}:{name}"] = pin
        controls[f"{ticker}:ORIGINAL_BUILD"] = original_pin
        for name, payload in (("APPROVAL", approval), ("RECOVERY", recovery)):
            for role, pin in _historical_controls(payload, name):
                controls[f"{ticker}:{role}"] = _pin(pin)
        result[ticker] = {"ticker": ticker, "cik": cik, **pins,
                          "original_build_manifest": original_pin,
                          "selection_status": "ACCEPTED_HISTORY_SELECTED"}
    return HistorySelections(declaration, result, controls)


def _historical_controls(payload: dict[str, Any], prefix: str) -> Iterator[tuple[str, dict[str, str]]]:
    # Referenced historical JSON blobs are opaque witnesses, not an instruction
    # to reopen old checkout code, Raw inventories, journals or audit programs.
    for key, value in payload.items():
        if isinstance(value, dict) and "path" in value and "sha256" in value:
            yield prefix + ":" + key, {"path": value["path"], "sha256": value["sha256"]}
    for key in ("engine_source", "runner_source"):
        value = payload.get(key)
        approval = value.get("acceptance") if isinstance(value, dict) else None
        if isinstance(approval, dict) and "path" in approval and "sha256" in approval:
            yield prefix + ":" + key + ":acceptance", {"path": approval["path"], "sha256": approval["sha256"]}


def completed_recovery_source(root: Path) -> bool:
    """Require the public COMPLETE/PASS gate and exact, safe payload inventory."""
    from sec_xbrl import history

    parent = history._check_recovery_access(root)
    if parent is None or root.absolute() != parent / "panels":
        return False
    reader = history.HistoryPublicationReader(root)
    declared = {info["path"] for table in reader.manifest["tables"] for info in table["files"].values()}
    if reader.manifest.get("derived_quarter"):
        declared.add(reader.manifest["derived_quarter"]["path"])
    actual = set()
    for path in root.rglob("*"):
        history._reject_symlink_components(path)
        if path.is_file():
            actual.add(str(path.relative_to(root)))
        elif not path.is_dir():
            raise ValueError("financial History has an unsafe physical entry")
    extras = actual - declared - {"history_manifest.json"}
    if not declared <= actual or any(not _retained_diagnostic(path, declared) for path in extras):
        raise ValueError("financial completed History payload inventory differs")
    return True


def _retained_diagnostic(relative: str, declared: set[str]) -> bool:
    # V1 recovery preserved producer spill/partial artifacts. They are never
    # selected financial values and the old receipt did not hash them. Current
    # invocation closure retains their physical inventory and complete bytes.
    if relative in {"history_manifest.json.partial", ".chunks/quarter-spill.records"}:
        return True
    path = Path(relative)
    if not re.fullmatch(r"[0-9]{8}\.parquet", path.name):
        return False
    return any(path.parent.parent == Path(name).parent
               and re.fullmatch(re.escape("." + Path(name).name + ".chunks-") + r"[A-Za-z0-9_-]+", path.parent.name)
               for name in declared)


def verify_financial_history_source(root: Path, *, storage_entry: dict | None = None) -> None:
    """Reuse completed storage proof by current byte identity, never accounting inference.

    Ordinary/new publications retain the public detailed validation path. Only
    exact completed-recovery consumer publications can reuse their existing
    transaction/PASS report, plan, intake, rule and manifest bindings. All current
    declared payload bytes are still hashed; no stat-only shortcut is allowed.
    """
    from sec_xbrl import history
    from sec_xbrl.collection_operations import _declared_publication_files

    reader = history.HistoryPublicationReader(root)
    if storage_entry is not None:
        from sec_xbrl.financial_storage_reuse import verify_storage_entry
        verify_storage_entry(root, storage_entry)
        _declared_publication_files(root, reader.manifest)
    elif completed_recovery_source(root):
        _declared_publication_files(root, reader.manifest)
    else:
        reader.verify_all()
