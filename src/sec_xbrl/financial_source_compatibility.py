"""Explicit, directed reuse of immutable source451 financial storage evidence.

This is a compatibility witness, never a replacement validation report. Current
payload and provenance checks remain the responsibility of their strict readers.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from sec_xbrl.history_selection import _pin
from sec_xbrl.screening.common import digest_value, read_json, sha256_file

VERSION = "financial-source-compatibility-v1"
SUPERSEDING_VERSION = "financial-source-compatibility-v2"
LATEST_VERSION = "financial-source-compatibility-v3"
ORIGIN_REVISION = "451205b08fed2617d6e04f3c209e1a21b8aa9f29"
# Exact responsibilities approved for this repair; no accounting/Raw validator changes.
_ALLOWED = frozenset({
    "prospective_selection.py", "financial_storage_reuse.py",
    "financial_source_compatibility.py", "metric_quality.py",
    "screening/metric_identity.py", "screening/verified_source_closure.py",
})
_SUPERSEDING_CHANGES = frozenset({
    "financial_source_compatibility.py", "screening/quarterly.py", "screening/dataset_v3.py",
})
_LATEST_CHANGES = frozenset({
    "financial_source_compatibility.py", "screening/dataset_v3.py",
    "screening/explorer.py", "screening/service.py", "screening/server.py",
    "screening/cli.py",
})
_COMPLETED_PUBLICATIONS = frozenset({"identity", "annual_metrics", "annual_dataset", "quarterly_metrics"})
_ISSUER = object()
_ACTIVE: ContextVar[SourceCompatibility | None] = ContextVar("financial_source_compatibility", default=None)


def _current_source_root() -> Path:
    return Path(__file__).parent


def source_inventory(root: Path) -> dict[str, str]:
    """Hash the complete Python inventory, rejecting aliases and unsafe entries."""
    root = Path(root)
    if (not root.is_absolute() or not root.is_dir()
        or any(path.is_symlink() for path in (root, *root.parents))):
        raise ValueError("source compatibility root is unsafe")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("source compatibility aliases are forbidden")
        if path.suffix == ".py":
            if not path.is_file():
                raise ValueError("source compatibility Python inventory is unsafe")
            result[str(path.relative_to(root))] = sha256_file(path)
    if not result:
        raise ValueError("source compatibility inventory is empty")
    return result


def _code_identity(root: Path, inventory: dict, rules: dict) -> str:
    from sec_xbrl.history_validation import VALIDATION_POLICY_VERSION, _canonical_bytes

    digest = hashlib.sha256()
    digest.update(VALIDATION_POLICY_VERSION.encode())
    for relative in sorted(inventory):
        path = root / relative
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(_canonical_bytes(rules))
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceCompatibility:
    declaration: dict
    payload: dict
    controls: dict
    _issuer: object
    _seal: str

    def check(self) -> None:
        if (self._issuer is not _ISSUER or
            self._seal != digest_value([self.declaration, self.payload, self.controls])):
            raise ValueError("untrusted source compatibility witness")

    def require_control(self, declaration: dict) -> None:
        self.check()
        if _pin(declaration) not in self.payload["preserved_controls"]:
            raise ValueError("source compatibility does not approve this preserved control")

    def policy_matches(self, declared: dict, current: dict) -> bool:
        self.check()
        origin = self.payload["origin_source_sha256s"]
        return (isinstance(declared, dict) and set(declared) == set(current) and declared == {
            name: origin.get(name.removeprefix("src/sec_xbrl/")) for name in current
        })

    def accepts_routine(self, *, report: dict, pins: dict, declared: dict,
                        rules: dict, current_identity: str) -> bool:
        self.check()
        for row in self.payload["routine_histories"]:
            if row["report"] != report:
                continue
            return (row["build_manifest"] == pins["build_manifest"]
                and row["history_manifest"] == pins["history_manifest"]
                and row["declared_payload_sha256s"] == declared
                and row["rules"] == rules
                and row["current_code_identity"] == current_identity)
        return False


def checked_source_compatibility(value: object) -> SourceCompatibility | None:
    """Only accept an intact resolver-issued witness, never a caller duck type."""
    if value is None:
        return None
    if not isinstance(value, SourceCompatibility):
        raise TypeError("untrusted source compatibility witness")
    value.check()
    return value


def resolve_source_compatibility(declaration: dict | None) -> SourceCompatibility | None:
    if declaration is None:
        return None
    pin = _pin(declaration)
    active = _ACTIVE.get()
    if active is not None:
        active.check()
        supersedes = active.payload.get("supersedes")
        ancestors = [] if supersedes is None else [supersedes["packet"]]
        if active.payload["schema_version"] == LATEST_VERSION:
            ancestors.append(active.controls["SUPERSEDED:SUPERSEDED:SOURCE_COMPATIBILITY"])
        if pin in ancestors:
            # Recheck exact bytes/inventories; the scope does not cache acceptance.
            return _resolve_packet(active.declaration, current_root=_current_source_root())
    return _resolve_packet(pin, current_root=_current_source_root())


@contextmanager
def use_source_compatibility(declaration: dict | None) -> Iterator[SourceCompatibility | None]:
    """Apply an explicitly pinned transition only within this execution context."""
    witness = resolve_source_compatibility(declaration)
    # An explicit absent declaration isolates the caller from any ambient scope.
    token = _ACTIVE.set(witness)
    try:
        yield witness
    finally:
        _ACTIVE.reset(token)


def _resolve_packet(declaration: dict, *, current_root: Path, expected_version: str | None = None) -> SourceCompatibility:
    pin = _pin(declaration)
    value = read_json(Path(pin["path"]))
    fields = {"schema_version", "status", "origin_revision", "origin_source_root",
              "origin_source_sha256s", "current_source_sha256s", "approved_changes",
              "preserved_controls", "routine_histories"}
    version = value.get("schema_version") if isinstance(value, dict) else None
    latest = version == LATEST_VERSION
    superseding = version in (SUPERSEDING_VERSION, LATEST_VERSION)
    if superseding:
        fields.add("supersedes")
    if (not isinstance(value, dict) or set(value) != fields
        or version not in (VERSION, SUPERSEDING_VERSION, LATEST_VERSION)
        or (expected_version is not None and version != expected_version) or value["status"] != "ROOT_APPROVED"
        or value["origin_revision"] != ORIGIN_REVISION):
        raise ValueError("source compatibility needs exact directed ROOT approval")
    origin_root = Path(value["origin_source_root"])
    origin = source_inventory(origin_root)
    current = source_inventory(current_root)
    changes = {name: {"origin": origin.get(name), "current": current.get(name)}
               for name in sorted(set(origin) | set(current)) if origin.get(name) != current.get(name)}
    allowed = _ALLOWED
    if superseding:
        allowed |= _SUPERSEDING_CHANGES
    if latest:
        allowed |= _LATEST_CHANGES
    if (value["origin_source_sha256s"] != origin or value["current_source_sha256s"] != current
        or not changes or set(changes) - allowed
        or value["approved_changes"] != changes
        or any(row["current"] is None or (row["origin"] is None and name != "financial_source_compatibility.py")
               for name, row in changes.items())):
        raise ValueError("source compatibility inventories or approved exact changes differ")
    controls = {"SOURCE_COMPATIBILITY": pin}
    for prefix, root, inventory in (("ORIGIN_SOURCE", origin_root, origin),
                                    ("CURRENT_SOURCE", current_root, current)):
        for name, sha in inventory.items():
            controls[f"{prefix}:{name}"] = _pin({"path": str(root / name), "sha256": sha})
    preserved = value["preserved_controls"]
    if not isinstance(preserved, list) or not preserved:
        raise ValueError("source compatibility needs preserved controls")
    seen = set()
    for index, entry in enumerate(preserved):
        checked = _pin(entry)
        if checked["path"] in seen:
            raise ValueError("duplicate preserved compatibility control")
        seen.add(checked["path"])
        controls[f"PRESERVED:{index}"] = checked
    histories = value["routine_histories"]
    if not isinstance(histories, list) or not histories:
        raise ValueError("source compatibility needs explicit routine reports")
    seen = set()
    for index, row in enumerate(histories):
        if not isinstance(row, dict) or set(row) != {
            "report", "build_manifest", "history_manifest", "declared_payload_sha256s",
            "rules", "origin_code_identity", "current_code_identity"}:
            raise ValueError("source compatibility routine scope differs")
        for name in ("report", "build_manifest", "history_manifest"):
            controls[f"ROUTINE:{index}:{name}"] = _pin(row[name])
        if row["report"]["path"] in seen:
            raise ValueError("duplicate compatibility routine report")
        seen.add(row["report"]["path"])
        report = read_json(Path(row["report"]["path"]))
        if (not isinstance(row["rules"], dict)
            or row["origin_code_identity"] != _code_identity(origin_root, origin, row["rules"])
            or row["current_code_identity"] != _code_identity(current_root, current, row["rules"])
            or report.get("code_identity") != row["origin_code_identity"]):
            raise ValueError("source compatibility report identity or rules differ")
    if superseding:
        prior = value["supersedes"]
        if not isinstance(prior, dict) or set(prior) != {"packet", "source_root", "completed_publications"}:
            raise ValueError("superseding source compatibility requires exact prior scope")
        archive = Path(prior["source_root"])
        old = _resolve_packet(
            prior["packet"], current_root=archive,
            expected_version=SUPERSEDING_VERSION if latest else VERSION,
        )
        archived = old.payload["current_source_sha256s"]
        delta = {name for name in set(archived) | set(current) if archived.get(name) != current.get(name)}
        if not delta or delta - (_LATEST_CHANGES if latest else _SUPERSEDING_CHANGES):
            raise ValueError("superseding compatibility changes unknown source responsibilities")
        if (old.payload["origin_source_root"] != value["origin_source_root"]
            or old.payload["origin_source_sha256s"] != value["origin_source_sha256s"]):
            raise ValueError("superseding compatibility origin differs")
        def original_rows(rows: list[dict]) -> list[dict]:
            return [{key: item for key, item in row.items() if key != "current_code_identity"} for row in rows]
        if original_rows(old.payload["routine_histories"]) != original_rows(histories):
            raise ValueError("superseding compatibility routine reports or rules differ")
        completed = prior["completed_publications"]
        if not isinstance(completed, dict) or set(completed) != _COMPLETED_PUBLICATIONS:
            raise ValueError("superseding compatibility needs four completed publication pins")
        completion_pins = [_pin(completed[name]) for name in sorted(completed)]
        if latest and completed != old.payload["supersedes"]["completed_publications"]:
            raise ValueError("latest source compatibility changes a completed publication")
        expected_preserved = old.payload["preserved_controls"]
        if not latest:
            expected_preserved = expected_preserved + completion_pins
        if sorted(preserved, key=lambda item: item["path"]) != sorted(expected_preserved, key=lambda item: item["path"]):
            raise ValueError("superseding compatibility preserved controls differ")
        for name, control in old.controls.items():
            controls[f"SUPERSEDED:{name}"] = control
    return SourceCompatibility(pin, value, controls, _ISSUER,
                               digest_value([pin, value, controls]))


def prepare_source_compatibility_packet(
    *, origin_source_root: Path, preserved_controls: list[dict], routine_histories: list[dict],
    supersedes: dict | None = None,
    latest: bool = False,
) -> dict:
    """Prepare a proposal from immutable source bytes and exact report/build/history pins.

    No writes, validation replay or approval. ROOT must review the source diff and
    change PROPOSED to ROOT_APPROVED before resolving this packet in a new config.
    """
    from sec_xbrl.financial_storage_reuse import history_validation_rules

    origin_source_root = Path(origin_source_root)
    current_root = _current_source_root()
    origin = source_inventory(origin_source_root)
    current = source_inventory(current_root)
    reports = []
    for entry in routine_histories:
        if set(entry) != {"report", "build_manifest", "history_manifest"}:
            raise ValueError("packet input requires exact report/build/history pins")
        pins = {name: _pin(pin) for name, pin in entry.items()}
        manifest = read_json(Path(pins["history_manifest"]["path"]))
        report = read_json(Path(pins["report"]["path"]))
        build = read_json(Path(pins["build_manifest"]["path"]))
        rules = history_validation_rules(manifest)
        old_identity = _code_identity(origin_source_root, origin, rules)
        if (report.get("code_identity") != old_identity
            or build.get("history_manifest_sha256") != pins["history_manifest"]["sha256"]
            or report.get("manifest_sha256") != pins["history_manifest"]["sha256"]):
            raise ValueError("packet input does not bind original source/report/History")
        reports.append({**pins, "declared_payload_sha256s": build["declared_files"],
                        "rules": rules, "origin_code_identity": old_identity,
                        "current_code_identity": _code_identity(current_root, current, rules)})
    packet = {"schema_version": VERSION, "status": "PROPOSED", "origin_revision": ORIGIN_REVISION,
            "origin_source_root": str(origin_source_root), "origin_source_sha256s": origin,
            "current_source_sha256s": current,
            "approved_changes": {name: {"origin": origin.get(name), "current": current.get(name)}
                for name in sorted(set(origin) | set(current)) if origin.get(name) != current.get(name)},
            "preserved_controls": [_pin(pin) for pin in preserved_controls],
            "routine_histories": reports}
    if latest and supersedes is None:
        raise ValueError("latest compatibility requires the exact prior packet")
    if supersedes is not None:
        if not isinstance(supersedes, dict) or set(supersedes) != {"packet", "source_root", "completed_publications"}:
            raise ValueError("packet input requires exact superseded packet/source/publication scope")
        packet["schema_version"] = LATEST_VERSION if latest else SUPERSEDING_VERSION
        packet["supersedes"] = {
            "packet": _pin(supersedes["packet"]),
            "source_root": str(Path(supersedes["source_root"])),
            "completed_publications": {name: _pin(pin) for name, pin in supersedes["completed_publications"].items()},
        }
    return packet
