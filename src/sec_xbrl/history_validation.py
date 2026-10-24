"""Routine, stateful validation for immutable history publications.

This module deliberately does not define accounting or period semantics.  It
decides how much persisted storage evidence must be revisited and delegates the
existing detailed path to the publication reader.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

VALIDATION_POLICY_VERSION = "history-routine-validation-v1"
_SAMPLE_ROWS = 8


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Auditable outcome; routine evidence is never labelled full validation."""

    level: str
    reason: str
    checked_files: tuple[str, ...]
    reused_files: tuple[str, ...]
    hashed_files: tuple[str, ...]
    sampled_rows: int
    decoded_json_values: int
    detailed_fallback: bool
    state_path: str
    declared_files: dict[str, str]


def validation_code_identity(*, sources: tuple[Path, ...], rules: Mapping[str, Any]) -> str:
    """Bind policy state to the actual relevant source bytes and rule values."""

    digest = hashlib.sha256()
    digest.update(VALIDATION_POLICY_VERSION.encode())
    for path in sorted((Path(path) for path in sources), key=str):
        digest.update(str(path.name).encode())
        digest.update(path.read_bytes())
    digest.update(_canonical_bytes(rules))
    return digest.hexdigest()


def validate_publication(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    detailed: Callable[[], None],
    code_identity: str,
    mode: Literal["routine", "detailed"] = "routine",
    state_root: Path | None = None,
) -> ValidationResult:
    """Validate one publication and atomically advance external routine state.

    No state is a normal ROUTINE_INITIAL condition.  Malformed prior state,
    policy/code drift, or structural anomalies trigger the existing detailed
    validator.  A normal declared-file change validates only its table closure.
    """

    root = Path(root).absolute()
    state_root = Path(state_root) if state_root is not None else root.parent / ".history-validation"
    state_path = state_root / (_scope_key(manifest) + ".json")
    inventory = _manifest_inventory(manifest)
    declared = {relative: str(entry["info"]["sha256"]) for relative, entry in inventory.items()}
    prior, prior_error = _read_state(state_path)
    if mode == "detailed":
        before = _capture_identities(root, inventory)
        detailed()
        after = _capture_identities(root, inventory)
        if after != before:
            raise ValueError("history publication changed during detailed validation")
        result = ValidationResult(
            "DETAILED", "EXPLICIT_DETAILED", tuple(sorted(inventory)), (), tuple(sorted(inventory)),
            sum(int(entry["info"]["count"]) for entry in inventory.values()), -1, False,
            str(state_path.absolute()), dict(sorted(declared.items())),
        )
        _write_state(
            state_path,
            _state_payload(root, manifest, code_identity, inventory, result, after),
        )
        return result

    fallback_reason: str | None = None
    if prior_error is not None:
        fallback_reason = "STATE_INVALID:" + prior_error
    elif prior is not None and prior.get("code_identity") != code_identity:
        fallback_reason = "VALIDATION_CODE_OR_RULE_IDENTITY_CHANGED"
    elif prior is not None and prior.get("policy_version") != VALIDATION_POLICY_VERSION:
        fallback_reason = "VALIDATION_POLICY_CHANGED"

    structure_error: Exception | None = None
    try:
        actual = _actual_publication_files(root)
        if actual != set(inventory):
            raise ValueError("publication file inventory differs from manifest")
    except (OSError, ValueError) as exc:
        structure_error = exc

    if structure_error is not None:
        # Detailed storage decode is useful diagnostic evidence, but it does not
        # define exact inventory.  Never turn a known structural violation into
        # a passing receipt merely because the narrower legacy scan completed.
        detailed()
        raise ValueError("history publication structure anomaly") from structure_error

    if fallback_reason is not None:
        before = _capture_identities(root, inventory)
        detailed()
        after = _capture_identities(root, inventory)
        if after != before:
            raise ValueError("history publication changed during detailed fallback")
        result = ValidationResult(
            "DETAILED_FALLBACK", fallback_reason, tuple(sorted(inventory)), (),
            tuple(sorted(inventory)), sum(int(entry["info"]["count"]) for entry in inventory.values()),
            -1, True, str(state_path.absolute()), dict(sorted(declared.items())),
        )
        _write_state(
            state_path,
            _state_payload(root, manifest, code_identity, inventory, result, after),
        )
        return result

    prior_files = {} if prior is None else prior.get("files", {})
    changed: set[str] = set()
    reused: set[str] = set()
    hashed: set[str] = set()
    identities: dict[str, list[int]] = {}
    try:
        for relative, entry in inventory.items():
            path = root / relative
            identity = _safe_identity(path)
            identities[relative] = list(identity)
            old = prior_files.get(relative) if isinstance(prior_files, dict) else None
            if (
                isinstance(old, dict)
                and old.get("sha256") == entry["info"]["sha256"]
                and old.get("count") == entry["info"]["count"]
                and old.get("json_fields") == entry["info"].get("json_fields")
                and old.get("table_key") == entry["table_key"]
                and old.get("role") == entry["role"]
                and old.get("identity") == list(identity)
            ):
                reused.add(relative)
                continue
            # A new inode/root can reuse prior semantic evidence only after its
            # full bytes prove the same declared digest. Stat equality alone is
            # a change signal and is never described as content proof.
            actual_digest = _sha256_file(path)
            hashed.add(relative)
            if actual_digest != entry["info"]["sha256"]:
                raise ValueError("history dataset integrity mismatch")
            if (
                isinstance(old, dict)
                and old.get("sha256") == actual_digest
                and old.get("count") == entry["info"]["count"]
                and old.get("json_fields") == entry["info"].get("json_fields")
                and old.get("table_key") == entry["table_key"]
                and old.get("role") == entry["role"]
            ):
                reused.add(relative)
            else:
                changed.add(relative)
    except (OSError, TypeError, ValueError) as exc:
        detailed()
        raise ValueError("history publication file anomaly") from exc

    removed = set(prior_files) - set(inventory) if isinstance(prior_files, dict) else set()
    checked = set(inventory) if prior is None or removed else _table_closure(
        changed, inventory, prior_files
    )
    sampled_rows = 0
    decoded_json = 0
    schemas = {
        path: value.get("schema_fingerprint")
        for path, value in prior_files.items()
        if isinstance(value, dict) and isinstance(value.get("schema_fingerprint"), str)
    } if isinstance(prior_files, dict) else {}
    try:
        for relative in sorted(checked):
            rows, decoded, schema_fingerprint = _routine_file_check(
                root / relative, inventory[relative]["info"]
            )
            sampled_rows += rows
            decoded_json += decoded
            schemas[relative] = schema_fingerprint
        _check_table_references(root, inventory, checked)
        after = _capture_identities(root, inventory)
        if after != identities:
            raise ValueError("history publication changed during routine validation")
    except (OSError, TypeError, ValueError) as exc:
        detailed()
        raise ValueError("history publication routine check anomaly") from exc

    reason = "ROUTINE_INITIAL" if prior is None else (
        "ROUTINE_CHANGED" if changed or removed else "ROUTINE_UNCHANGED"
    )
    result = ValidationResult(
        reason, reason, tuple(sorted(checked)), tuple(sorted(reused)), tuple(sorted(hashed)),
        sampled_rows, decoded_json, False, str(state_path.absolute()), dict(sorted(declared.items())),
    )
    _write_state(
        state_path,
        _state_payload(root, manifest, code_identity, inventory, result, identities, schemas),
    )
    return result


def _manifest_inventory(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        raise TypeError("history publication tables must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, table in enumerate(tables):
        if not isinstance(table, dict) or not isinstance(table.get("files"), dict):
            raise TypeError("history publication table files are malformed")
        table_key = _canonical_hash(
            {
                key: table.get(key)
                for key in ("cik", "ticker", "view", "period_class", "scope")
            }
        )
        for role, info in table["files"].items():
            _add_info(result, info, table_key=table_key, role=str(role), table_index=index)
    if manifest.get("derived_quarter") is not None:
        _add_info(result, manifest["derived_quarter"], table_key="derived-quarter", role="derived", table_index=-1)
    if not result:
        raise ValueError("history publication has no declared data files")
    return result


def _add_info(result: dict[str, dict[str, Any]], info: Any, **metadata: Any) -> None:
    if not isinstance(info, dict):
        raise TypeError("history publication file declaration is malformed")
    relative = Path(info.get("path", ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("history publication file path is unsafe")
    key = str(relative)
    if key in result or type(info.get("sha256")) is not str or type(info.get("count")) is not int:
        raise ValueError("history publication file declaration is duplicated or malformed")
    result[key] = {"info": info, **metadata}


def _actual_publication_files(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or (not stat.S_ISDIR(value.st_mode) and not stat.S_ISREG(value.st_mode)):
            raise ValueError("history publication contains an unsafe entry")
        if stat.S_ISREG(value.st_mode) and path != root / "history_manifest.json":
            result.add(str(path.relative_to(root)))
    return result


def _table_closure(
    changed: set[str],
    inventory: Mapping[str, Mapping[str, Any]],
    prior_files: Mapping[str, Any],
) -> set[str]:
    keys = {inventory[path]["table_key"] for path in changed}
    keys.update(
        prior["table_key"]
        for path in changed
        if isinstance((prior := prior_files.get(path)), dict)
        and isinstance(prior.get("table_key"), str)
    )
    return {path for path, entry in inventory.items() if entry["table_key"] in keys}


def _routine_file_check(path: Path, info: Mapping[str, Any]) -> tuple[int, int, str]:
    import polars as pl

    frame = pl.scan_parquet(path, parallel="none", low_memory=True, rechunk=False)
    schema = frame.collect_schema()
    count = frame.select(pl.len()).collect(engine="streaming").item()
    if count != info["count"]:
        raise ValueError("history dataset row count mismatch")
    fields = info.get("json_fields")
    if (
        not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or len(set(fields)) != len(fields)
        or any(field not in schema or schema[field] not in (pl.String, pl.Null) for field in fields)
    ):
        raise ValueError("history dataset JSON schema mismatch")
    sample_size = min(_SAMPLE_ROWS // 2, count)
    sample = (
        frame.with_row_index("__validation_row")
        .filter(
            (pl.col("__validation_row") < sample_size)
            | (pl.col("__validation_row") >= max(sample_size, count - sample_size))
        )
        .drop("__validation_row")
        .collect(engine="streaming")
    )
    decoded = 0
    for row in sample.iter_rows(named=True, buffer_size=1):
        for key, value in row.items():
            if key in fields and value is not None:
                json.loads(value, parse_constant=lambda token: (_raise_nonfinite(token)))
                decoded += 1
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("history dataset contains a non-finite sampled scalar")
    schema_fingerprint = _canonical_hash(
        [(name, str(dtype)) for name, dtype in zip(schema.names(), schema.dtypes(), strict=True)]
    )
    return sample.height, decoded, schema_fingerprint


def _check_table_references(
    root: Path, inventory: Mapping[str, Mapping[str, Any]], checked: set[str]
) -> None:
    import polars as pl

    table_keys = {inventory[path]["table_key"] for path in checked}
    for table_key in table_keys:
        entries = {entry["role"]: (path, entry) for path, entry in inventory.items() if entry["table_key"] == table_key}
        if not {"columns", "rows", "cells"}.issubset(entries):
            continue
        cells_path, _cells = entries["cells"]
        cell_frame = pl.scan_parquet(root / cells_path, parallel="none", low_memory=True, rechunk=False)
        schema = cell_frame.collect_schema()
        row_field, column_field = "fiscal_time_series_row_id", "fiscal_time_series_column_id"
        cell_id = "fiscal_time_series_cell_id"
        if any(field not in schema for field in (cell_id, row_field, column_field)):
            raise ValueError("history cell reference schema is missing")
        row_path, _ = entries["rows"]
        column_path, _ = entries["columns"]
        row_ids = (
            pl.scan_parquet(root / row_path, parallel="none", low_memory=True, rechunk=False)
            .select(row_field)
            .collect(engine="streaming")
        )
        column_ids = (
            pl.scan_parquet(root / column_path, parallel="none", low_memory=True, rechunk=False)
            .select(column_field)
            .collect(engine="streaming")
        )
        for frame, field in ((row_ids, row_field), (column_ids, column_field)):
            identifiers = frame.get_column(field)
            if identifiers.null_count() or identifiers.n_unique() != frame.height:
                raise ValueError("history table identity is null or duplicated")
        if (
            schema[row_field] != row_ids.schema[row_field]
            or schema[column_field] != column_ids.schema[column_field]
        ):
            raise ValueError("history cell reference type differs from table identity type")
        counts = cell_frame.select(
            pl.len().alias("count"),
            pl.col(cell_id).null_count().alias("cell_nulls"),
            pl.col(cell_id).n_unique().alias("cell_unique"),
            pl.col(row_field)
            .is_in(pl.lit(row_ids.get_column(row_field)).implode())
            .fill_null(False)
            .not_()
            .sum()
            .alias("dangling_rows"),
            pl.col(column_field)
            .is_in(pl.lit(column_ids.get_column(column_field)).implode())
            .fill_null(False)
            .not_()
            .sum()
            .alias("dangling_columns"),
        ).collect(engine="streaming").row(0, named=True)
        if counts["cell_nulls"] or counts["cell_unique"] != counts["count"]:
            raise ValueError("history table identity is null or duplicated")
        if counts["dangling_rows"] or counts["dangling_columns"]:
            raise ValueError("history cell reference is dangling")


def _state_payload(
    root: Path,
    manifest: Mapping[str, Any],
    code_identity: str,
    inventory: Mapping[str, Mapping[str, Any]],
    result: ValidationResult,
    identities: Mapping[str, list[int]] | None = None,
    schemas: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    identities = identities or {path: list(_safe_identity(root / path)) for path in inventory}
    schemas = schemas or {}
    return {
        "version": 1,
        "policy_version": VALIDATION_POLICY_VERSION,
        "code_identity": code_identity,
        "scope_key": _scope_key(manifest),
        "publication_root": str(root),
        "manifest_sha256": _sha256_file(root / "history_manifest.json"),
        "validation_level": result.level,
        "validation_reason": result.reason,
        "full_storage_validation": result.level in {"DETAILED", "DETAILED_FALLBACK"},
        "semantic_validation": False,
        "files": {
            path: {
                "identity": identities[path],
                "sha256": entry["info"]["sha256"],
                "count": entry["info"]["count"],
                "json_fields": entry["info"].get("json_fields"),
                "table_key": entry["table_key"],
                "role": entry["role"],
                "schema_fingerprint": schemas.get(path),
            }
            for path, entry in sorted(inventory.items())
        },
        "result": asdict(result),
    }


def _scope_key(manifest: Mapping[str, Any]) -> str:
    companies = manifest.get("plan", {}).get("companies", []) if isinstance(manifest.get("plan"), dict) else []
    scope = {
        "companies": sorted((str(row.get("cik", "")), str(row.get("ticker", ""))) for row in companies if isinstance(row, dict)),
        "views": manifest.get("views"),
        "kind": "quarter" if manifest.get("derived_quarter") is not None else "reported",
    }
    return _canonical_hash(scope)


def _read_state(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("validation state path is unsafe")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("files"), dict):
            raise ValueError("validation state schema is invalid")
        return value, None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _write_state(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_identity(path: Path) -> tuple[int, int, int, int, int]:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError("history dataset path is not a regular file")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _capture_identities(
    root: Path, inventory: Mapping[str, Mapping[str, Any]]
) -> dict[str, list[int]]:
    return {path: list(_safe_identity(root / path)) for path in inventory}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _raise_nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON scalar: {token}")
