"""Invocation-local proof that a producer's governed sources stayed unchanged.

This module is deliberately private to the two publishers that need to avoid a
second deep reader construction.  It does not create a persistent verification
receipt and it does not offer a caller-controlled skip or verifier callback.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import secrets
import stat
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sec_xbrl.screening.common import canonical_json, digest_value

_IDENTITY = "IDENTITY_PUBLISH"
_V3 = "COMBINED_V3_PUBLISH"
_ISSUER = object()


@dataclass(frozen=True, slots=True)
class _FileRecord:
    path: str
    roles: tuple[str, ...]
    sha256: str
    size: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _MemberRecord:
    archive: str
    member: str
    role: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class _InventoryRecord:
    root: str
    role: str
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    files: tuple[_FileRecord, ...]
    members: tuple[_MemberRecord, ...]
    inventories: tuple[_InventoryRecord, ...]
    control_bytes: dict[str, bytes]

    @property
    def fingerprint(self) -> str:
        return digest_value(
            {
                "files": [
                    {
                        "path": row.path,
                        "roles": row.roles,
                        "sha256": row.sha256,
                        "size": row.size,
                        "identity": row.identity,
                    }
                    for row in self.files
                ],
                "members": [
                    {
                        "archive": row.archive,
                        "member": row.member,
                        "role": row.role,
                        "sha256": row.sha256,
                        "size": row.size,
                    }
                    for row in self.members
                ],
                "inventories": [
                    {"root": row.root, "role": row.role, "entries": row.entries}
                    for row in self.inventories
                ],
            }
        )


class _Collector:
    def __init__(self, captured: dict[str, bytes] | None = None) -> None:
        self._captured = captured
        self._files: dict[str, tuple[set[str], str, int, tuple[int, int, int, int, int]]] = {}
        self._members: list[_MemberRecord] = []
        self._inventories: list[_InventoryRecord] = []
        self._control_bytes: dict[str, bytes] = {}

    def file(
        self,
        value: Path | str,
        role: str,
        *,
        control: bool = False,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
    ) -> bytes | None:
        path = _absolute_file(Path(value))
        key = str(path)
        existing = self._files.get(key)
        if existing is not None and role in existing[0]:
            raise ValueError(f"duplicate source closure role: {role}: {path}")
        data, digest, size, identity = _read_stable(path, retain=control)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError(f"source closure hash differs for {role}: {path}")
        if expected_size is not None and size != expected_size:
            raise ValueError(f"source closure size differs for {role}: {path}")
        if existing is None:
            self._files[key] = ({role}, digest, size, identity)
        else:
            roles, previous_digest, previous_size, previous_identity = existing
            if (digest, size, identity) != (
                previous_digest,
                previous_size,
                previous_identity,
            ):
                raise ValueError(f"source closure file changed during discovery: {path}")
            roles.add(role)
        if control:
            assert data is not None
            self._control_bytes[key] = data
            if self._captured is not None:
                captured = self._captured.get(key)
                if captured is None or hashlib.sha256(captured).hexdigest() != digest:
                    raise ValueError(f"captured source control changed: {path}")
                return captured
        return data

    def json(self, value: Path | str, role: str) -> Any:
        path = _absolute_file(Path(value))
        data = self.file(path, role, control=True)
        try:
            return json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"invalid source closure JSON: {path}") from exc

    def inventory(
        self,
        value: Path | str,
        role: str,
        *,
        expected_files: set[str] | None = None,
    ) -> tuple[Path, ...]:
        root = _absolute_directory(Path(value))
        entries: list[tuple[str, str]] = []
        actual_files: set[str] = set()
        files: list[Path] = []
        for path in sorted(root.rglob("*")):
            _reject_symlink_components(path)
            relative = str(path.relative_to(root))
            value_stat = path.lstat()
            if stat.S_ISREG(value_stat.st_mode):
                entries.append((relative, "FILE"))
                actual_files.add(relative)
                files.append(path)
            elif stat.S_ISDIR(value_stat.st_mode):
                entries.append((relative, "DIRECTORY"))
            else:
                raise ValueError(f"unsafe source closure inventory entry: {path}")
        if expected_files is not None and actual_files != expected_files:
            raise ValueError(f"source closure publication file set changed: {root}")
        self._inventories.append(_InventoryRecord(str(root), role, tuple(entries)))
        return tuple(files)

    def pattern_inventory(
        self, value: Path | str, role: str, patterns: tuple[str, ...]
    ) -> tuple[Path, ...]:
        candidate = Path(value)
        if ".." in candidate.parts:
            raise ValueError(f"source closure path contains traversal: {candidate}")
        root = Path(os.path.abspath(candidate))
        if not root.exists():
            self._inventories.append(
                _InventoryRecord(str(root), role, ((".", "ABSENT"),))
            )
            return ()
        root = _absolute_directory(root)
        matched: dict[str, Path] = {}
        for pattern in patterns:
            for path in root.glob(pattern):
                _reject_symlink_components(path)
                relative = str(path.relative_to(root))
                matched[relative] = path
        entries = []
        for relative, path in sorted(matched.items()):
            mode = path.lstat().st_mode
            kind = "FILE" if stat.S_ISREG(mode) else "DIRECTORY" if stat.S_ISDIR(mode) else "OTHER"
            entries.append((relative, kind))
        self._inventories.append(_InventoryRecord(str(root), role, tuple(entries)))
        return tuple(path for _, path in sorted(matched.items()))

    def zip_member(
        self,
        archive: Path | str,
        member: str,
        role: str,
        *,
        archive_role: str,
        expected_archive_sha256: str | None = None,
        expected_member_sha256: str | None = None,
    ) -> None:
        archive_path = _absolute_file(Path(archive))
        self.file(
            archive_path,
            archive_role,
            expected_sha256=expected_archive_sha256,
        )
        member_path = Path(member)
        if member_path.is_absolute() or not member_path.parts or ".." in member_path.parts:
            raise ValueError("unsafe source closure ZIP member")
        try:
            with zipfile.ZipFile(archive_path) as package:
                if package.namelist().count(member) != 1:
                    raise ValueError("source closure ZIP member is missing or duplicated")
                data = package.read(member)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("invalid source closure ZIP package") from exc
        digest = hashlib.sha256(data).hexdigest()
        if expected_member_sha256 is not None and digest != expected_member_sha256:
            raise ValueError("source closure ZIP member hash differs")
        self._members.append(
            _MemberRecord(str(archive_path), member, role, digest, len(data))
        )

    def snapshot(self) -> _Snapshot:
        files = tuple(
            _FileRecord(path, tuple(sorted(values[0])), values[1], values[2], values[3])
            for path, values in sorted(self._files.items())
        )
        members = tuple(
            sorted(self._members, key=lambda row: (row.archive, row.member, row.role))
        )
        inventories = tuple(
            sorted(self._inventories, key=lambda row: (row.root, row.role))
        )
        if len({(row.archive, row.member, row.role) for row in members}) != len(members):
            raise ValueError("duplicate source closure ZIP-member role")
        if len({(row.root, row.role) for row in inventories}) != len(inventories):
            raise ValueError("duplicate source closure inventory role")
        return _Snapshot(files, members, inventories, dict(self._control_bytes))


class _VerifiedSourceClosure:
    __slots__ = ("__nonce", "__operation", "__pid")

    def __init__(self, issuer: object, nonce: str, operation: str) -> None:
        if issuer is not _ISSUER:
            raise TypeError("verified source closure is issuer-only")
        self.__nonce = nonce
        self.__operation = operation
        self.__pid = os.getpid()

    def __reduce__(self):
        raise TypeError("verified source closure cannot be serialized")

    def __reduce_ex__(self, protocol: int):
        raise TypeError("verified source closure cannot be serialized")

    def __copy__(self):
        raise TypeError("verified source closure cannot be copied")

    def __deepcopy__(self, memo: dict[int, Any]):
        raise TypeError("verified source closure cannot be copied")


@dataclass(slots=True)
class _RegistryRecord:
    capability: _VerifiedSourceClosure
    operation: str
    pid: int
    destination: str
    config_path: str
    config_bytes: bytes
    expected_payload_bytes: bytes
    parent_bytes: bytes | None
    snapshot: _Snapshot
    state: str = "ISSUED"


_REGISTRY: dict[str, _RegistryRecord] = {}


def _verify_identity_sources_once(
    *, config_path: Path, config: dict[str, Any], destination: Path
) -> tuple[dict[str, Any], _VerifiedSourceClosure]:
    initial = _stable_identity_snapshot(config_path, config)
    module = importlib.import_module("sec_xbrl.screening.metric_identity")
    sources = module._verify_configured_sources(config)
    post = _identity_snapshot(config_path, config)
    _require_same_snapshot(initial, post, "identity post-verification")
    nonce, capability, record = _unregistered_record(
        operation=_IDENTITY,
        destination=destination,
        config_path=config_path,
        config=config,
        expected_payload=sources,
        parent_payload=None,
        snapshot=initial,
    )
    _REGISTRY[nonce] = record
    return copy.deepcopy(sources), capability


def _verify_v3_sources_once(
    *,
    config_path: Path,
    config: dict[str, Any],
    annual_root: Path,
    quarter_root: Path,
    destination: Path,
) -> tuple[Any, Any, _VerifiedSourceClosure]:
    initial = _stable_v3_snapshot(config_path, config, annual_root, quarter_root)
    dataset_v2 = importlib.import_module("sec_xbrl.screening.dataset_v2")
    quarterly = importlib.import_module("sec_xbrl.screening.quarterly")
    dataset_v3 = importlib.import_module("sec_xbrl.screening.dataset_v3")
    annual = dataset_v2.ScreeningDatasetV2Reader(annual_root)
    quarter_hash = _sha256(quarter_root / quarterly.MANIFEST)
    quarter = quarterly.QuarterlyScreeningMetricReader(
        quarter_root, manifest_sha256=quarter_hash
    )
    dataset_v3._verify_parent_binding(annual, quarter)
    if [row["cik"] for row in annual.companies] != quarter.manifest["universe"]["ciks"]:
        raise ValueError("annual and quarterly company membership differ")
    parent_payload = _v3_parent_payload(annual, quarter)
    post = _v3_snapshot(config_path, config, annual_root, quarter_root)
    _require_same_snapshot(initial, post, "v3 post-verification")
    nonce, capability, record = _unregistered_record(
        operation=_V3,
        destination=destination,
        config_path=config_path,
        config=config,
        expected_payload={},
        parent_payload=parent_payload,
        snapshot=initial,
    )
    _REGISTRY[nonce] = record
    return annual, quarter, capability


def _publish_identity(
    capability: _VerifiedSourceClosure, *, staging: Path, destination: Path
) -> None:
    try:
        record = _lookup(capability, _IDENTITY, destination)
        module = importlib.import_module("sec_xbrl.screening.metric_identity")
        config = json.loads(record.config_bytes)
        sources = json.loads(record.expected_payload_bytes)
        config_path = Path(record.config_path)
        identity = {
            "schema_version": module.VERSION,
            "source_kind": module.SOURCE_KIND,
            "readiness": "READY",
            "universe_id": config["universe_id"],
            "financial_as_of": config["financial_as_of"],
            "metadata_observation_cutoff": config["metadata_observation_cutoff"],
            "annual_window": copy.deepcopy(config["annual_window"]),
            "global_quarter_spine": copy.deepcopy(config["global_quarter_spine"]),
            "configured_ciks": [row["cik"] for row in config["companies"]],
            "configured_tickers": [row["ticker"] for row in config["companies"]],
            "config": copy.deepcopy(config),
            "config_path": str(config_path),
            "config_sha256": _sha256(config_path),
            **sources,
        }
        publication_id = "generic-metric-identity-" + digest_value(identity)[:24]
        manifest = {**identity, "publication_id": publication_id}
        _require_exact_output(staging, module.MANIFEST_NAME, manifest)
        fresh = _identity_snapshot(config_path, config)
        _require_same_snapshot(record.snapshot, fresh, "identity pre-publication")
        _require_exact_output(staging, module.MANIFEST_NAME, manifest)
        nonce = capability._VerifiedSourceClosure__nonce
        record.state = "FINALIZING"
        try:
            os.rename(staging, destination)
        except BaseException:
            record.state = "INVALID"
            _REGISTRY.pop(nonce, None)
            raise
        record.state = "CONSUMED"
        _REGISTRY.pop(nonce, None)
    except BaseException:
        _discard(capability)
        raise


def _publish_v3(
    capability: _VerifiedSourceClosure, *, staging: Path, destination: Path
) -> None:
    try:
        record = _lookup(capability, _V3, destination)
        module = importlib.import_module("sec_xbrl.screening.dataset_v3")
        config = json.loads(record.config_bytes)
        parents = json.loads(record.parent_bytes or b"null")
        config_path = Path(record.config_path)
        identity = {
            "config_path": str(config_path),
            "config_sha256": _sha256(config_path),
            "config": config,
            "annual_publication_id": parents["annual"]["publication_id"],
            "quarterly_publication_id": parents["quarterly"]["publication_id"],
        }
        manifest = {
            "schema_version": module.VERSION,
            "publication_id": "screening-dataset-" + digest_value(identity)[:24],
            "dataset_id": config["dataset_id"],
            "fixture_kind": config.get("fixture_kind", "ACTUAL_PREPARED"),
            "financial_as_of": parents["quarterly"]["manifest"]["financial_as_of"],
            "config_path": str(config_path),
            "config_sha256": _sha256(config_path),
            "config": config,
            "sources": {
                "metadata": copy.deepcopy(
                    parents["annual"]["manifest"]["sources"]["metadata"]
                )
            },
            "versions": {
                "annual_publication_id": parents["annual"]["publication_id"],
                "quarterly_publication_id": parents["quarterly"]["publication_id"],
            },
            "parents": {
                "annual": {
                    "root": parents["annual"]["root"],
                    "publication_id": parents["annual"]["publication_id"],
                    "manifest_sha256": parents["annual"]["manifest_sha256"],
                },
                "quarterly": {
                    "root": parents["quarterly"]["root"],
                    "publication_id": parents["quarterly"]["publication_id"],
                    "manifest_sha256": parents["quarterly"]["manifest_sha256"],
                },
            },
        }
        if parents["annual"]["company_ciks"] != parents["quarterly"]["company_ciks"]:
            raise ValueError("verified v3 parent membership changed")
        _require_exact_output(staging, module.MANIFEST, manifest)
        fresh = _v3_snapshot(
            config_path,
            config,
            Path(parents["annual"]["root"]),
            Path(parents["quarterly"]["root"]),
        )
        _require_same_snapshot(record.snapshot, fresh, "v3 pre-publication")
        _require_exact_output(staging, module.MANIFEST, manifest)
        nonce = capability._VerifiedSourceClosure__nonce
        record.state = "FINALIZING"
        try:
            os.rename(staging, destination)
        except BaseException:
            record.state = "INVALID"
            _REGISTRY.pop(nonce, None)
            raise
        record.state = "CONSUMED"
        _REGISTRY.pop(nonce, None)
    except BaseException:
        _discard(capability)
        raise


def _discard(capability: _VerifiedSourceClosure) -> None:
    nonce = getattr(capability, "_VerifiedSourceClosure__nonce", None)
    if isinstance(nonce, str):
        _REGISTRY.pop(nonce, None)


def _unregistered_record(
    *,
    operation: str,
    destination: Path,
    config_path: Path,
    config: dict[str, Any],
    expected_payload: dict[str, Any],
    parent_payload: dict[str, Any] | None,
    snapshot: _Snapshot,
) -> tuple[str, _VerifiedSourceClosure, _RegistryRecord]:
    nonce = secrets.token_hex(32)
    capability = _VerifiedSourceClosure(_ISSUER, nonce, operation)
    record = _RegistryRecord(
        capability=capability,
        operation=operation,
        pid=os.getpid(),
        destination=str(Path(os.path.abspath(destination))),
        config_path=str(_absolute_file(config_path)),
        config_bytes=canonical_json(config).encode("utf-8"),
        expected_payload_bytes=canonical_json(expected_payload).encode("utf-8"),
        parent_bytes=(
            canonical_json(parent_payload).encode("utf-8")
            if parent_payload is not None
            else None
        ),
        snapshot=snapshot,
    )
    return nonce, capability, record


def _lookup(
    capability: _VerifiedSourceClosure, operation: str, destination: Path
) -> _RegistryRecord:
    if type(capability) is not _VerifiedSourceClosure:
        raise TypeError("invalid verified source closure")
    nonce = getattr(capability, "_VerifiedSourceClosure__nonce", None)
    record = _REGISTRY.get(nonce)
    if (
        record is None
        or record.capability is not capability
        or record.operation != operation
        or record.pid != os.getpid()
        or getattr(capability, "_VerifiedSourceClosure__pid", None) != os.getpid()
        or getattr(capability, "_VerifiedSourceClosure__operation", None) != operation
        or record.destination != str(Path(os.path.abspath(destination)))
        or record.state != "ISSUED"
    ):
        raise ValueError("verified source closure is invalid or already consumed")
    return record


def _require_exact_output(root: Path, manifest_name: str, expected: dict[str, Any]) -> None:
    root = _absolute_directory(root)
    children = tuple(root.iterdir())
    if {path.name for path in children} != {manifest_name} or any(
        path.is_symlink() or not path.is_file() for path in children
    ):
        raise ValueError("staged publication file set changed")
    expected_bytes = (canonical_json(expected) + "\n").encode("utf-8")
    actual, _digest, _size, _identity = _read_stable(root / manifest_name, retain=True)
    if actual != expected_bytes:
        raise ValueError("staged publication bytes differ from verified source payload")


def _stable_identity_snapshot(config_path: Path, config: dict[str, Any]) -> _Snapshot:
    first = _identity_snapshot(config_path, config)
    reconstructed = _identity_snapshot(
        config_path, config, captured=first.control_bytes
    )
    _require_same_snapshot(first, reconstructed, "identity discovery reconstruction")
    return first


def _stable_v3_snapshot(
    config_path: Path,
    config: dict[str, Any],
    annual_root: Path,
    quarter_root: Path,
) -> _Snapshot:
    first = _v3_snapshot(config_path, config, annual_root, quarter_root)
    reconstructed = _v3_snapshot(
        config_path,
        config,
        annual_root,
        quarter_root,
        captured=first.control_bytes,
    )
    _require_same_snapshot(first, reconstructed, "v3 discovery reconstruction")
    return first


def _identity_snapshot(
    config_path: Path,
    config: dict[str, Any],
    *,
    captured: dict[str, bytes] | None = None,
) -> _Snapshot:
    collector = _Collector(captured)
    _discover_identity(collector, config_path, config, prefix="IDENTITY")
    _add_source_code(collector, _identity_source_modules(), "IDENTITY")
    return collector.snapshot()


def _v3_snapshot(
    config_path: Path,
    config: dict[str, Any],
    annual_root: Path,
    quarter_root: Path,
    *,
    captured: dict[str, bytes] | None = None,
) -> _Snapshot:
    collector = _Collector(captured)
    collector.file(config_path, "V3_CONFIG", control=True)
    annual_root = _absolute_directory(annual_root)
    quarter_root = _absolute_directory(quarter_root)
    annual_manifest_path = annual_root / "screening_dataset_manifest.json"
    annual_manifest = collector.json(annual_manifest_path, "ANNUAL_V2_MANIFEST")
    annual_files = _declared_list_files(
        collector, annual_root, annual_manifest.get("files"), "ANNUAL_V2_OUTPUT"
    )
    collector.inventory(
        annual_root,
        "ANNUAL_V2_INVENTORY",
        expected_files={"screening_dataset_manifest.json", *annual_files},
    )
    annual_config_path = Path(str(annual_manifest.get("config_path", "")))
    annual_config = collector.json(annual_config_path, "ANNUAL_V2_CONFIG")

    metrics = annual_manifest.get("sources", {}).get("metrics", {})
    metric_root = Path(str(metrics.get("root", "")))
    metric_manifest = collector.json(
        metric_root / "screening_metric_manifest.json", "ANNUAL_METRIC_MANIFEST"
    )
    metric_files = _declared_list_files(
        collector, metric_root, metric_manifest.get("files"), "ANNUAL_METRIC_OUTPUT"
    )
    collector.inventory(
        metric_root,
        "ANNUAL_METRIC_INVENTORY",
        expected_files={"screening_metric_manifest.json", *metric_files},
    )
    collector.file(
        Path(str(metric_manifest.get("config_path", ""))),
        "ANNUAL_METRIC_CONFIG",
        control=True,
    )

    declaration = annual_config.get("identity_source") if isinstance(annual_config, dict) else None
    if not isinstance(declaration, dict) or declaration.get("kind") != "GENERIC_METRIC_IDENTITY_ATTESTATION":
        raise ValueError("single-pass v3 requires the explicit generic identity source")
    identity_root = Path(str(declaration.get("root", "")))
    identity_manifest = collector.json(
        identity_root / "generic_metric_identity_manifest.json",
        "V3_IDENTITY_MANIFEST",
    )
    identity_config_path = Path(str(identity_manifest.get("config_path", "")))
    identity_config = collector.json(identity_config_path, "V3_IDENTITY_CONFIG")
    identity_module = importlib.import_module("sec_xbrl.screening.metric_identity")
    normalized_identity_config = identity_module._validate_config(identity_config)
    _discover_identity(
        collector,
        identity_config_path,
        normalized_identity_config,
        prefix="V3_IDENTITY",
        config_already_added=True,
    )

    quarter_manifest = collector.json(
        quarter_root / "quarterly_screening_metric_manifest.json",
        "QUARTER_METRIC_MANIFEST",
    )
    quarter_files = _declared_mapping_files(
        collector,
        quarter_root,
        quarter_manifest.get("files"),
        "QUARTER_METRIC_OUTPUT",
    )
    expected_quarter_files = {
        "quarterly_screening_metric_manifest.json",
        *quarter_files,
    }
    if (quarter_root / "MANIFEST.sha256").exists():
        collector.file(quarter_root / "MANIFEST.sha256", "QUARTER_MANIFEST_SIDECAR")
        expected_quarter_files.add("MANIFEST.sha256")
    collector.inventory(
        quarter_root,
        "QUARTER_METRIC_INVENTORY",
        expected_files=expected_quarter_files,
    )
    collector.file(
        Path(str(quarter_manifest.get("config_path", ""))),
        "QUARTER_METRIC_CONFIG",
        control=True,
    )
    generic = quarter_manifest.get("annual_parent", {}).get("generic_identity")
    if not isinstance(generic, dict) or generic.get("root") != str(_absolute_directory(identity_root)):
        raise ValueError("quarterly generic identity parent differs")
    _add_source_code(collector, _v3_source_modules(), "V3")
    return collector.snapshot()


def _capture_prospective_inputs(collector: _Collector, config: dict, *, prefix: str):
    """Capture declared bytes, never issue a semantic acceptance proof.

    The governed identity/quality reader replays the full prospective proof once.
    This closure independently binds its exact declarations before/after that
    replay. Repeating the semantic resolver during every snapshot would multiply
    whole-cohort IO; a declaration differing from replay cannot publish.
    """
    declaration = config.get("prospective_selection")
    if declaration is None:
        return None
    _add_declaration_file(collector, declaration, f"{prefix}_PROSPECTIVE_MANIFEST_PIN")
    manifest = collector.json(Path(declaration["path"]), f"{prefix}_PROSPECTIVE_MANIFEST")
    _add_declaration_file(collector, manifest["config"], f"{prefix}_PROSPECTIVE_CONFIG_PIN")
    prospective_config = collector.json(Path(manifest["config"]["path"]), f"{prefix}_PROSPECTIVE_CONFIG")
    storage = None
    if "storage_reuse" in prospective_config:
        origin_storage = prospective_config["storage_reuse"]
        _add_declaration_file(collector, origin_storage, f"{prefix}_PROSPECTIVE_STORAGE_PIN")
        registry = collector.json(Path(origin_storage["path"]), f"{prefix}_PROSPECTIVE_STORAGE")
        storage = SimpleNamespace(companies={row["ticker"]:row for row in registry["companies"]}, controls={})
    return SimpleNamespace(companies=manifest["companies"], controls=manifest["controls"], storage_reuse=storage)


def _discover_identity(
    collector: _Collector,
    config_path: Path,
    config: dict[str, Any],
    *,
    prefix: str,
    config_already_added: bool = False,
) -> None:
    if not config_already_added:
        collector.file(config_path, f"{prefix}_CONFIG", control=True)
    collection_path = Path(config["collection_manifest"])
    collection = collector.json(collection_path, f"{prefix}_COLLECTION_MANIFEST")
    request_path = Path(str(collection.get("request_path", "")))
    if request_path.absolute() != (collection_path.parent / "collection_request.json").absolute():
        raise ValueError("source closure collection request path differs")
    request = collector.json(request_path, f"{prefix}_COLLECTION_REQUEST")
    rows = collection.get("companies")
    request_rows = request.get("companies")
    if not isinstance(rows, list) or not isinstance(request_rows, list):
        raise TypeError("source closure collection company scope is malformed")
    if [(row.get("ticker"), row.get("cik")) for row in rows] != [
        (row.get("ticker"), row.get("cik")) for row in request_rows
    ]:
        raise ValueError("source closure collection membership differs")
    from sec_xbrl.metric_quality import _configured_storage_reuse
    prospective = _capture_prospective_inputs(collector, config, prefix=prefix)
    if prospective is not None:
        for name,declaration in prospective.controls.items():
            _add_declaration_file(collector,declaration,f"{prefix}_PROSPECTIVE:{name}")
    if prospective is not None and prospective.storage_reuse is not None:
        for ticker, company in prospective.storage_reuse.companies.items():
            for index, entry in enumerate(company["histories"]):
                if "retained_diagnostics" in entry:
                    collector.inventory(Path(entry["history_manifest"]["path"]).parent,
                        f"{prefix}_PROSPECTIVE_TOPOLOGY:{ticker}:{index}",
                        expected_files=set(entry["payload_inventory"]) | set(entry["retained_diagnostics"]))
    scoped = {(row["ticker"], row["cik"]) for row in config["companies"]}
    for row in rows:
        ticker = str(row.get("ticker"))
        company_root = collection_path.parent / "companies" / ticker
        if row.get("plan_status") == "PREPARED":
            plan_path = company_root / "plan.json"
            collector.json(plan_path, f"{prefix}_COLLECTION_PLAN:{ticker}")
            collector.json(
                company_root / "plan_identity.json",
                f"{prefix}_COLLECTION_PLAN_IDENTITY:{ticker}",
            )
            intake = company_root / "intake" / "history_intake.json"
            if intake.exists():
                collector.json(intake, f"{prefix}_STATUS_INTAKE:{ticker}")
        collector.pattern_inventory(
            company_root / "operation_attempts",
            f"{prefix}_STATUS_ATTEMPT_INVENTORY:{ticker}",
            ("collect-*.json", "build-*.json"),
        )
        attempts_root = company_root / "operation_attempts"
        if attempts_root.exists():
            for operation in ("collect", "build"):
                for attempt in sorted(attempts_root.glob(f"{operation}-*.json")):
                    collector.json(
                        attempt,
                        f"{prefix}_STATUS_ATTEMPT:{ticker}:{operation}:{attempt.name}",
                    )
        build_path = company_root / "build_manifest.json"
        if build_path.exists():
            build = collector.json(build_path, f"{prefix}_STATUS_BUILD:{ticker}")
            _add_status_history(collector, build, f"{prefix}_STATUS_HISTORY:{ticker}")
        elif (ticker, str(row.get("cik"))) in scoped and not (prospective and ticker in prospective.companies):
            raise ValueError(f"{ticker}: scoped source closure build is missing")

    metadata_root = Path(config["metadata_root"])
    metadata_manifest = collector.json(
        metadata_root / "company_metadata_manifest.json",
        f"{prefix}_METADATA_MANIFEST",
    )
    metadata_files = _declared_mapping_files(
        collector,
        metadata_root,
        metadata_manifest.get("files"),
        f"{prefix}_METADATA_DATASET",
    )
    collector.inventory(
        metadata_root,
        f"{prefix}_METADATA_INVENTORY",
        expected_files={"company_metadata_manifest.json", *metadata_files},
    )

    storage = None
    if "storage_reuse" in config:
        declared_parent = collector.json(Path(config["storage_reuse"]["path"]), f"{prefix}_CONFIGURED_STORAGE")
        if prospective is not None and declared_parent["collection_manifest"]["path"] != str(collection_path):
            storage = prospective.storage_reuse
        else:
            storage = _configured_storage_reuse(config, collection_path)
        for name, declaration in storage.controls.items():
            _add_declaration_file(collector, declaration, f"{prefix}_STORAGE_REUSE:{name}")
        for ticker, company in storage.companies.items():
            for index, entry in enumerate(company["histories"]):
                if "retained_diagnostics" in entry:
                    root = Path(entry["history_manifest"]["path"]).parent
                    collector.inventory(root, f"{prefix}_STORAGE_V2_TOPOLOGY:{ticker}:{index}",
                        expected_files=set(entry["payload_inventory"]) | set(entry["retained_diagnostics"]))
    from sec_xbrl.financial_storage_reuse import storage_history
    selection = None
    if "history_selection" in config:
        from sec_xbrl.history_selection import resolve_history_selection
        selection = resolve_history_selection(config["history_selection"], collection_manifest=collection_path,
                                              scope_companies=config["companies"], storage_reuse=storage)
        for name, declaration in selection.controls.items():
            _add_declaration_file(collector, declaration, f"{prefix}_HISTORY_SELECTION:{name}")
    for company in config["companies"]:
        ticker = company["ticker"]
        selected = selection.companies.get(ticker) if selection else None
        equivalent = prospective.companies.get(ticker) if prospective else None
        if equivalent:
            selected = {"build_manifest":equivalent["origin_build_manifest"]}
        build_path = (Path(selected["build_manifest"]["path"]) if selected else
                      collection_path.parent / "companies" / ticker / "build_manifest.json")
        build = collector.json(build_path, f"{prefix}_SCOPED_BUILD:{ticker}")
        from sec_xbrl.collection_operations import history_build_controls
        for name,declaration in history_build_controls(build).items():
            _add_declaration_file(collector,declaration,f"{prefix}_BUILD_CONTROL:{ticker}:{name}")
        collector.file(
            Path(str(build.get("intake_manifest", ""))),
            f"{prefix}_SCOPED_INTAKE:{ticker}",
            control=True,
        )
        history_root = Path(company["history_root"])
        _add_history(
            collector,
            history_root,
            f"{prefix}_HISTORY:{ticker}",
            check_recovery=True,
            storage_entry=(storage_history(storage, ticker, history_root / "history_manifest.json")
                or storage_history(prospective.storage_reuse if prospective else None,
                                   ticker, history_root / "history_manifest.json")),
        )
        _add_analysis(
            collector,
            Path(company["annual_analysis_root"]),
            f"{prefix}_ANNUAL_ANALYSIS:{ticker}",
        )
        _add_analysis(
            collector,
            Path(company["quarterly_analysis_root"]),
            f"{prefix}_QUARTER_ANALYSIS:{ticker}",
        )

    quality_root = Path(config["quality_root"])
    quality_manifest = collector.json(
        quality_root / "generic_metric_quality_manifest.json",
        f"{prefix}_QUALITY_MANIFEST",
    )
    quality_files = _declared_mapping_files(
        collector,
        quality_root,
        quality_manifest.get("files"),
        f"{prefix}_QUALITY_REPORT",
    )
    collector.inventory(
        quality_root,
        f"{prefix}_QUALITY_INVENTORY",
        expected_files={"generic_metric_quality_manifest.json", *quality_files},
    )
    evidence = quality_manifest.get("evidence_hashes")
    if not isinstance(evidence, dict):
        raise TypeError("source closure quality evidence is malformed")
    _add_quality_evidence(collector, evidence, prefix)
    source_binding = quality_manifest.get("source_binding")
    if not isinstance(source_binding, dict):
        raise TypeError("source closure quality binding is malformed")
    _add_source_binding(collector, Path(source_binding["root"]), prefix)


def _add_status_history(collector: _Collector, build: dict[str, Any], role: str) -> None:
    if build.get("status") != "READY":
        return
    publication = Path(str(build.get("publication", "")))
    history = importlib.import_module("sec_xbrl.history")
    history._check_recovery_access(publication)
    _add_recovery_gate_files(collector, publication, role)
    manifest_path = Path(str(build.get("history_manifest", "")))
    from sec_xbrl.collection_operations import history_build_controls
    for name,declaration in history_build_controls(build).items():
        _add_declaration_file(collector,declaration,f"{role}:BUILD_CONTROL:{name}")
    manifest = collector.json(manifest_path, f"{role}:MANIFEST")
    declared = _history_declarations(manifest)
    if build.get("declared_files") != declared:
        raise ValueError("status-only History declaration differs")
    for relative, info in _history_infos(manifest).items():
        collector.file(
            publication / relative,
            f"{role}:DATA:{relative}",
            expected_sha256=str(info["sha256"]),
        )


def _add_history(
    collector: _Collector, root: Path, role: str, *, check_recovery: bool,
    storage_entry: dict | None = None,
) -> None:
    root = Path(os.path.abspath(root))
    if check_recovery:
        history = importlib.import_module("sec_xbrl.history")
        history._check_recovery_access(root)
    manifest = collector.json(root / "history_manifest.json", f"{role}:MANIFEST")
    infos = _history_infos(manifest)
    for relative, info in infos.items():
        collector.file(
            root / relative,
            f"{role}:DATA:{relative}",
            expected_sha256=str(info["sha256"]),
        )
    physical_files = collector.inventory(
        root,
        f"{role}:INVENTORY",
    )
    governed_files = {"history_manifest.json", *infos}
    for path in physical_files:
        relative = str(path.relative_to(root))
        if relative not in governed_files:
            diagnostics = storage_entry.get("retained_diagnostics") if storage_entry else None
            if diagnostics is not None and relative in diagnostics:
                continue  # Explicit v2 nonconsumed producer diagnostics: topology only.
            collector.file(path, f"{role}:RETAINED_PHYSICAL:{relative}")
    if check_recovery:
        _add_recovery_gate_files(collector, root, role)


def _add_recovery_gate_files(collector: _Collector, history_root: Path, role: str) -> None:
    patterns = (
        ".history-recovery-*",
        ".receipt.partial-*",
        "reported_recovery_receipt.json",
    )
    for parent in (history_root, *history_root.parents):
        present = [path for pattern in patterns for path in parent.glob(pattern)]
        if not present:
            continue
        selected = collector.pattern_inventory(
            parent, f"{role}:RECOVERY_SELECTION:{parent}", patterns
        )
        for path in selected:
            relative = path.relative_to(parent)
            if path.is_file():
                collector.file(path, f"{role}:RECOVERY_GATE_FILE:{relative}")
                continue
            for control_file in collector.inventory(
                path, f"{role}:RECOVERY_CONTROL_INVENTORY:{relative}"
            ):
                collector.file(
                    control_file,
                    f"{role}:RECOVERY_GATE_FILE:{control_file.relative_to(parent)}",
                )
        for name in ("reported-panels", "panels"):
            collector.file(
                parent / name / "history_manifest.json",
                f"{role}:RECOVERY_GATE_MANIFEST:{name}",
                control=True,
            )


def _add_analysis(collector: _Collector, root: Path, role: str) -> None:
    manifest = collector.json(root / "analysis_manifest.json", f"{role}:MANIFEST")
    declared: dict[str, dict[str, Any]] = {}
    for company in manifest.get("companies", {}).values():
        for view in company.get("views", {}).values():
            for info in view.get("files", {}).values():
                relative = str(info.get("path"))
                if relative in declared:
                    raise ValueError("duplicate analysis source closure path")
                declared[relative] = info
    if not declared:
        raise ValueError("analysis source closure is empty")
    for relative, info in sorted(declared.items()):
        collector.file(
            root / relative,
            f"{role}:DATA:{relative}",
            expected_sha256=str(info.get("sha256")),
        )
    collector.inventory(
        root,
        f"{role}:INVENTORY",
        expected_files={"analysis_manifest.json", *declared},
    )


def _add_quality_evidence(
    collector: _Collector, evidence: dict[str, Any], prefix: str
) -> None:
    expected = {
        "config",
        "collection_manifest",
        "collection_request",
        "source_binding_manifest",
        "source_binding_documents",
        "source_binding_records",
        "duration_source_index",
        "correction_source_index",
        "history_manifests",
        "collection_build_manifests",
    }
    if "history_selection_controls" in evidence:
        expected.add("history_selection_controls")
    if "storage_reuse_controls" in evidence:
        expected.add("storage_reuse_controls")
    if "prospective_selection_controls" in evidence:
        expected.add("prospective_selection_controls")
    if set(evidence) != expected:
        raise ValueError("quality evidence source closure roles differ")
    for name, declaration in evidence.items():
        if name in {"history_manifests", "collection_build_manifests", "history_selection_controls", "storage_reuse_controls", "prospective_selection_controls"}:
            if not isinstance(declaration, dict):
                raise TypeError("quality grouped evidence is malformed")
            for ticker, item in sorted(declaration.items()):
                _add_declaration_file(
                    collector, item, f"{prefix}_QUALITY_EVIDENCE:{name}:{ticker}"
                )
        else:
            _add_declaration_file(
                collector, declaration, f"{prefix}_QUALITY_EVIDENCE:{name}"
            )


def _add_declaration_file(
    collector: _Collector, declaration: Any, role: str
) -> None:
    if not isinstance(declaration, dict) or not isinstance(declaration.get("path"), str):
        raise TypeError("source closure file declaration is malformed")
    collector.file(
        Path(declaration["path"]),
        role,
        control=True,
        expected_sha256=str(declaration.get("sha256")),
        expected_size=(
            declaration.get("size") if type(declaration.get("size")) is int else None
        ),
    )


def _add_source_binding(collector: _Collector, root: Path, prefix: str) -> None:
    manifest = collector.json(
        root / "source_binding_manifest.json", f"{prefix}_SOURCE_BINDING_MANIFEST"
    )
    binding_files = _declared_mapping_files(
        collector,
        root,
        manifest.get("files"),
        f"{prefix}_SOURCE_BINDING_FILE",
    )
    if set(binding_files) != {"source_documents.json", "source_bindings.json"}:
        raise ValueError("source-binding publication file roles differ")
    collector.inventory(
        root,
        f"{prefix}_SOURCE_BINDING_INVENTORY",
        expected_files={"source_binding_manifest.json", *binding_files},
    )
    candidates = manifest.get("candidate_inputs")
    if not isinstance(candidates, dict) or set(candidates) != {
        "duration_source_index",
        "correction_source_index",
    }:
        raise ValueError("source-binding candidate roles differ")
    for name, declaration in sorted(candidates.items()):
        _add_declaration_file(
            collector, declaration, f"{prefix}_SOURCE_INDEX:{name}"
        )
    documents_payload = collector.json(
        root / "source_documents.json",
        f"{prefix}_SOURCE_BINDING_DOCUMENTS_PAYLOAD",
    )
    documents = documents_payload.get("documents")
    if not isinstance(documents, list) or documents_payload.get("document_count") != len(documents):
        raise ValueError("source-binding document closure is malformed")
    identities: set[tuple[str, str, str]] = set()
    for document in documents:
        identity = (
            str(document.get("ticker")),
            str(document.get("cik")),
            str(document.get("accession")),
        )
        if identity in identities:
            raise ValueError("duplicate source-binding document closure identity")
        identities.add(identity)
        suffix = ":".join(identity)
        collector.zip_member(
            Path(str(document.get("package_path", ""))),
            str(document.get("primary_document", "")),
            f"{prefix}_PRIMARY_MEMBER:{suffix}",
            archive_role=f"{prefix}_PACKAGE_ZIP:{suffix}",
            expected_archive_sha256=str(document.get("package_sha256")),
            expected_member_sha256=str(document.get("primary_sha256")),
        )
        collector.file(
            Path(str(document.get("snapshot_manifest_path", ""))),
            f"{prefix}_RAW_MANIFEST:{suffix}",
            control=True,
            expected_sha256=str(document.get("snapshot_manifest_sha256")),
        )
        snapshot_root = Path(str(document.get("snapshot_root", "")))
        tables = document.get("tables")
        if not isinstance(tables, dict) or set(tables) != {
            "fact.parquet",
            "concept.parquet",
            "context.parquet",
        }:
            raise ValueError("Raw source closure table roles differ")
        for name, declaration in sorted(tables.items()):
            if not isinstance(declaration, dict):
                raise TypeError("Raw source closure table declaration is malformed")
            collector.file(
                snapshot_root / name,
                f"{prefix}_RAW_{name.split('.')[0].upper()}:{suffix}",
                expected_sha256=str(declaration.get("sha256")),
                expected_size=(
                    declaration.get("size")
                    if type(declaration.get("size")) is int
                    else None
                ),
            )


def _declared_mapping_files(
    collector: _Collector,
    root: Path,
    declarations: Any,
    role: str,
) -> set[str]:
    if not isinstance(declarations, dict):
        raise TypeError("source closure mapping declaration is malformed")
    result: set[str] = set()
    for name, info in sorted(declarations.items()):
        if name in result or not isinstance(info, dict):
            raise ValueError("duplicate source closure mapping path")
        result.add(name)
        collector.file(
            root / name,
            f"{role}:{name}",
            expected_sha256=str(info.get("sha256")),
            expected_size=info.get("size") if type(info.get("size")) is int else None,
        )
    return result


def _declared_list_files(
    collector: _Collector,
    root: Path,
    declarations: Any,
    role: str,
) -> set[str]:
    if not isinstance(declarations, list):
        raise TypeError("source closure list declaration is malformed")
    result: set[str] = set()
    for info in declarations:
        if not isinstance(info, dict) or not isinstance(info.get("path"), str):
            raise TypeError("source closure list item is malformed")
        relative = info["path"]
        if relative in result:
            raise ValueError("duplicate source closure list path")
        result.add(relative)
        collector.file(
            root / relative,
            f"{role}:{relative}",
            expected_sha256=str(info.get("sha256")),
            expected_size=info.get("size") if type(info.get("size")) is int else None,
        )
    return result


def _history_infos(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for table in manifest.get("tables", []):
        for info in table.get("files", {}).values():
            relative = str(info.get("path"))
            if relative in result:
                raise ValueError("duplicate History source closure path")
            result[relative] = info
    if manifest.get("derived_quarter") is not None:
        info = manifest["derived_quarter"]
        relative = str(info.get("path"))
        if relative in result:
            raise ValueError("duplicate History source closure path")
        result[relative] = info
    if not result:
        raise ValueError("History source closure is empty")
    return result


def _history_declarations(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        relative: str(info.get("sha256"))
        for relative, info in sorted(_history_infos(manifest).items())
    }


def _v3_parent_payload(annual: Any, quarter: Any) -> dict[str, Any]:
    return {
        "annual": {
            "root": str(annual.root),
            "publication_id": annual.publication_id,
            "manifest_sha256": _sha256(annual.root / "screening_dataset_manifest.json"),
            "manifest": copy.deepcopy(annual.manifest),
            "company_ciks": [row["cik"] for row in annual.companies],
            "companies": copy.deepcopy(annual.companies),
            "metadata": copy.deepcopy(annual.metadata),
            "definitions": copy.deepcopy(annual.metric_definitions),
            "support": copy.deepcopy(annual.metric_support),
            "observations": copy.deepcopy(annual.observations),
        },
        "quarterly": {
            "root": str(quarter.root),
            "publication_id": quarter.publication_id,
            "manifest_sha256": _sha256(
                quarter.root / "quarterly_screening_metric_manifest.json"
            ),
            "manifest": copy.deepcopy(quarter.manifest),
            "company_ciks": list(quarter.manifest["universe"]["ciks"]),
            "definitions": copy.deepcopy(quarter.definitions),
            "support": copy.deepcopy(quarter.support),
            "observations": copy.deepcopy(quarter.observations),
            "period_inventory": copy.deepcopy(quarter.period_inventory),
        },
    }


def _identity_source_modules() -> tuple[str, ...]:
    return (
        "sec_xbrl.screening.verified_source_closure",
        "sec_xbrl.screening.metric_identity",
        "sec_xbrl.screening.common",
        "sec_xbrl.collection_operations",
        "sec_xbrl.company_metadata",
        "sec_xbrl.history",
        "sec_xbrl.analysis",
        "sec_xbrl.metric_quality",
        "sec_xbrl.filing.sec_inline_transforms",
        "sec_xbrl.source_bindings",
        "sec_xbrl.facts.layer1",
    )


def _v3_source_modules() -> tuple[str, ...]:
    return (
        *_identity_source_modules(),
        "sec_xbrl.screening.dataset",
        "sec_xbrl.screening.dataset_v2",
        "sec_xbrl.screening.dataset_v3",
        "sec_xbrl.screening.quarterly",
        "sec_xbrl.metrics.screening",
        "sec_xbrl.metrics.quarterly_screening",
    )


def _add_source_code(
    collector: _Collector, module_names: tuple[str, ...], prefix: str
) -> None:
    package_root = _loaded_package_root()
    first = _local_python_files(package_root)
    expected: dict[str, tuple[str, int]] = {}
    for relative, path in first:
        _data, digest, size, _identity = _read_stable(path, retain=False)
        expected[relative] = (digest, size)
        collector.file(
            path,
            f"{prefix}_LOCAL_PACKAGE_SOURCE_CODE:{relative}",
            expected_sha256=digest,
            expected_size=size,
        )

    second = _local_python_files(package_root)
    if tuple(relative for relative, _path in first) != tuple(
        relative for relative, _path in second
    ):
        raise ValueError("local Python source file set changed during discovery")
    for relative, path in second:
        _data, digest, size, _identity = _read_stable(path, retain=False)
        if (digest, size) != expected[relative]:
            raise ValueError("local Python source bytes changed during discovery")

    for name in dict.fromkeys(module_names):
        module = importlib.import_module(name)
        path = getattr(module, "__file__", None)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        expected_path = package_root.joinpath(*name.split(".")[1:]).with_suffix(".py")
        if (
            not isinstance(path, str)
            or not isinstance(origin, str)
            or Path(path) != expected_path
            or Path(origin) != expected_path
        ):
            raise ValueError(f"source closure module path is unavailable: {name}")
        collector.file(expected_path, f"{prefix}_VERIFIER_SOURCE_CODE:{name}")
    _validate_loaded_package_modules(package_root)


def _loaded_package_root() -> Path:
    package = importlib.import_module("sec_xbrl")
    path = getattr(package, "__file__", None)
    spec = getattr(package, "__spec__", None)
    origin = getattr(spec, "origin", None)
    if not isinstance(path, str) or not isinstance(origin, str):
        raise TypeError("sec_xbrl package source origin is unavailable")
    package_file = _absolute_file(Path(path))
    if package_file.name != "__init__.py" or Path(origin) != package_file:
        raise ValueError("sec_xbrl package source origin differs")
    return _absolute_directory(package_file.parent)


def _local_python_files(root: Path) -> tuple[tuple[str, Path], ...]:
    result: list[tuple[str, Path]] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                if entry.is_symlink():
                    raise ValueError(f"local package path traverses a symlink: {path}")
                if entry.is_dir(follow_symlinks=False):
                    visit(path)
                elif entry.name.endswith(".py"):
                    if not entry.is_file(follow_symlinks=False):
                        raise ValueError(f"local Python source is not a regular file: {path}")
                    relative = path.relative_to(root).as_posix()
                    result.append((relative, path))

    visit(root)
    return tuple(sorted(result))


def _loaded_package_modules() -> tuple[tuple[str, Any], ...]:
    return tuple(
        (name, module)
        for name, module in sorted(sys.modules.items())
        if name == "sec_xbrl" or name.startswith("sec_xbrl.")
    )


def _validate_loaded_package_modules(root: Path) -> None:
    for name, module in _loaded_package_modules():
        if module is None:
            raise ValueError(f"loaded sec_xbrl module is unavailable: {name}")
        parts = name.split(".")[1:]
        if any(not part.isidentifier() for part in parts):
            raise ValueError(f"loaded sec_xbrl module name is invalid: {name}")
        module_path = root.joinpath(*parts).with_suffix(".py")
        package_path = root.joinpath(*parts, "__init__.py")
        path = getattr(module, "__file__", None)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if isinstance(path, str) and isinstance(origin, str):
            if Path(path) not in (module_path, package_path) or Path(origin) != Path(path):
                raise ValueError(f"loaded sec_xbrl module origin differs: {name}")
            _absolute_file(Path(path))
            continue
        namespace = getattr(module, "__path__", None)
        expected_directory = root.joinpath(*parts)
        if path is None and origin is None and namespace is not None:
            directories = tuple(_absolute_directory(Path(value)) for value in namespace)
            if directories == (expected_directory,):
                continue
        raise ValueError(f"loaded sec_xbrl module source origin is unavailable: {name}")


def _require_same_snapshot(expected: _Snapshot, actual: _Snapshot, label: str) -> None:
    if expected.fingerprint != actual.fingerprint:
        raise ValueError(f"{label} source closure changed")


def _absolute_file(path: Path) -> Path:
    _reject_symlink_components(path)
    absolute = Path(os.path.abspath(path))
    value = absolute.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"source closure path is not a regular file: {absolute}")
    return absolute


def _absolute_directory(path: Path) -> Path:
    _reject_symlink_components(path)
    absolute = Path(os.path.abspath(path))
    value = absolute.lstat()
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"source closure path is not a directory: {absolute}")
    return absolute


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    if ".." in path.parts:
        raise ValueError(f"source closure path contains traversal: {path}")
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError(f"source closure path traverses a symlink: {path}")
        except FileNotFoundError:
            raise ValueError(f"source closure path is missing: {path}") from None


def _read_stable(
    path: Path, *, retain: bool
) -> tuple[bytes | None, str, int, tuple[int, int, int, int, int]]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    data = bytearray() if retain else None
    digest = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"source closure file is unsafe: {path}")
        size = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if data is not None:
                data.extend(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    current = os.lstat(path)
    current_identity = (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
        current.st_ctime_ns,
    )
    if identity != after_identity or identity != current_identity or size != before.st_size:
        raise ValueError(f"source closure file changed while hashing: {path}")
    return (bytes(data) if data is not None else None, digest.hexdigest(), size, identity)


def _sha256(path: Path) -> str:
    return _read_stable(_absolute_file(path), retain=False)[1]
