"""Producer-side fiscal/rolling classification and approved quarterly flows.

The consumer reader remains calculation-free. This producer re-attests selected
reported cells to new T1 period observations, then publishes separate derived
records and consumer cells in a new immutable revision.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import marshal
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zlib
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any

from sec_xbrl.analytics.fiscal_time_series import (
    _annotate_comparability,
    _column,
    _id,
    _period_evidence,
)
from sec_xbrl.history import (
    HISTORY_VERSION,
    HistoryPublicationReader,
    _check_history_storage,
    _finalize_staged_records,
    _history_dataset_path,
    _iter_history_records,
    _open_recovery_path,
    _rename_history_directory,
    _retain_history_artifacts,
    _sha256_file,
    _stage_records,
    _write_json,
    _write_records,
    build_history,
)
from sec_xbrl.longitudinal import Layer2PublicationReader
from sec_xbrl.longitudinal.q4_policy_registry import CASH_FLOW_ALLOWLIST, INCOME_ALLOWLIST

QUARTER_RULE = "approved-core-cumulative-difference-v1"
PERIOD_RULE = "m6-fiscal-boundaries-v2"


def _sequence(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _scope(value: dict[str, Any]) -> str:
    return json.dumps([value.get("company_canonical_concept_id"), value.get("canonical_dimension_signature"),
                       _sequence(value.get("unit_numerator_measures")), _sequence(value.get("unit_denominator_measures")),
                       value.get("selection_view"), value.get("selection_as_of_date"), value.get("comparative_type")], sort_keys=True)


def approved_additive(cell: dict[str, Any]) -> bool:
    value = cell.get("value_lineage") or {}
    name = str(value.get("raw_concept_qname", "")).split(":")[-1]
    unit = _sequence(value.get("unit_numerator_measures") or [])
    if name in {"PaymentsForRepurchaseOfCommonStock", "ShareBasedCompensation", "PaymentsToAcquireProductiveAssets"}:
        evidence = cell.get("binding", {}).get("primary_statement_evidence", [])
        if not any("CF" in e.get("statement_types", []) and e.get("source_network_type") == "PRE" for e in evidence):
            return False
    return bool(
        cell.get("value_status") == "REPORTED" and value.get("source_type") == "REPORTED"
        and name in INCOME_ALLOWLIST | CASH_FLOW_ALLOWLIST
        and re.fullmatch(r"https?://fasb.org/us-gaap/\d{4}", str(value.get("raw_concept_namespace_uri", "")))
        and value.get("raw_concept_period_type") == "duration"
        and "monetary" in str(value.get("raw_concept_data_type", "")).lower()
        and value.get("company_canonical_concept_id") and not value.get("mapping_review_required")
        and not value.get("canonical_dimension_signature")
        and len(unit) == 1 and str(unit[0]).startswith("iso4217:")
        and not _sequence(value.get("unit_denominator_measures") or [])
        and cell.get("binding", {}).get("primary_statement_evidence")
    )


def _has_materialized_cell(cells: list[dict[str, Any]], row_id: str, column_id: str) -> bool:
    """A conflicting direct report is not an absent disclosure to gap-fill."""
    return any(cell["fiscal_time_series_row_id"] == row_id and cell["fiscal_time_series_column_id"] == column_id for cell in cells)


_PERIOD_ATTESTATION_FIELDS = (
    "source_filing_id", "source_fact_id", "comparative_type", "period_class",
    "classification_rule_version", "period_classification_reason", "value_numeric", "value_text",
    "context_start_date", "context_end_date", "context_instant_date", "context_id", "unit_id",
    "raw_concept_id", "raw_concept_qname", "raw_concept_namespace_uri",
    "company_canonical_concept_id", "filed_date", "source_snapshot_id", "accession",
    "unit_numerator_measures", "unit_denominator_measures", "canonical_dimension_signature",
)


def _period_attestation_index(observed: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Keep only fields used to attest a selected history cell.

    ``Layer2PublicationReader`` has already validated every declared dataset and
    row count before this projection.  Dropping unrelated tables here prevents
    the verified publication object from remaining live while large history
    tables are rewritten.
    """
    return {
        (row["source_filing_id"], row["source_fact_id"]): {
            field: row.get(field) for field in _PERIOD_ATTESTATION_FIELDS
        }
        for row in observed.records("reported_period_observation")
    }


def _spill_pack(value):
    try:
        return b"M" + marshal.dumps(value)
    except ValueError:
        # Parquet can also return temporal/Decimal scalars. Tagged fallback
        # preserves these types without executable deserialization or str casts.
        def encode(item):
            if isinstance(item, dict):
                return ("dict", [(encode(k), encode(v)) for k, v in item.items()])
            if isinstance(item, (list, tuple)):
                return (type(item).__name__, [encode(v) for v in item])
            if isinstance(item, datetime):
                return ("datetime", (item.isoformat(), item.fold))
            if isinstance(item, (date, time, Decimal)):
                return (type(item).__name__, str(item))
            if isinstance(item, timedelta):
                return ("timedelta", (item.days, item.seconds, item.microseconds))
            return ("scalar", item)
        return b"T" + marshal.dumps(encode(value))


def _spill_unpack(payload):
    if payload[:1] == b"M":
        return marshal.loads(payload[1:])
    if payload[:1] != b"T":
        raise ValueError("invalid private quarter spill record")
    def decode(item):
        kind, value = item
        if kind == "dict":
            return {decode(k): decode(v) for k, v in value}
        if kind in {"list", "tuple"}:
            values = [decode(v) for v in value]
            return values if kind == "list" else tuple(values)
        if kind == "datetime":
            return datetime.fromisoformat(value[0]).replace(fold=value[1])
        if kind == "timedelta":
            return timedelta(days=value[0], seconds=value[1], microseconds=value[2])
        if kind in {"date", "time", "Decimal"}:
            return {"date": date.fromisoformat, "time": time.fromisoformat, "Decimal": Decimal}[kind](value)
        if kind == "scalar":
            return value
        raise ValueError("invalid private quarter spill scalar")
    return decode(marshal.loads(payload[1:]))


_SPILL_DB_VALUE_MAGIC = b"QSV1"
_SPILL_DB_VALUE_HEADER_SIZE = len(_SPILL_DB_VALUE_MAGIC) + 1 + 8 + 32
_SPILL_DB_COMPRESSION_THRESHOLD = 32 * 1024
_SPILL_DB_MAX_RAW_BYTES = 1 << 30


def _spill_db_value_pack(value):
    """Envelope typed bytes for the disposable SQLite value BLOB only."""
    raw = _spill_pack(value)
    kind = b"R"
    body = raw
    if len(raw) >= _SPILL_DB_COMPRESSION_THRESHOLD:
        compressed = zlib.compress(raw, level=1)
        if len(compressed) < len(raw):
            kind = b"Z"
            body = compressed
    return (
        _SPILL_DB_VALUE_MAGIC
        + kind
        + len(raw).to_bytes(8, "big")
        + hashlib.sha256(raw).digest()
        + body
    )


def _spill_db_value_raw(payload):
    """Strictly restore new-format private DB bytes without migration."""
    encoded = bytes(payload)
    if len(encoded) < _SPILL_DB_VALUE_HEADER_SIZE:
        raise ValueError("invalid private quarter spill database value")
    if encoded[: len(_SPILL_DB_VALUE_MAGIC)] != _SPILL_DB_VALUE_MAGIC:
        raise ValueError("invalid private quarter spill database value")
    kind = encoded[len(_SPILL_DB_VALUE_MAGIC) : len(_SPILL_DB_VALUE_MAGIC) + 1]
    size_start = len(_SPILL_DB_VALUE_MAGIC) + 1
    raw_size = int.from_bytes(encoded[size_start : size_start + 8], "big")
    if raw_size > _SPILL_DB_MAX_RAW_BYTES:
        raise ValueError("invalid private quarter spill database value size")
    expected_hash = encoded[size_start + 8 : _SPILL_DB_VALUE_HEADER_SIZE]
    body = encoded[_SPILL_DB_VALUE_HEADER_SIZE :]
    if kind == b"R":
        raw = body
    elif kind == b"Z":
        decompressor = zlib.decompressobj()
        try:
            raw = decompressor.decompress(body, raw_size + 1)
        except zlib.error as exc:
            raise ValueError("invalid private quarter spill database compression") from exc
        if (
            len(raw) > raw_size
            or not decompressor.eof
            or decompressor.unused_data
            or decompressor.unconsumed_tail
        ):
            raise ValueError("invalid private quarter spill database compression")
    else:
        raise ValueError("invalid private quarter spill database value")
    if len(raw) != raw_size or hashlib.sha256(raw).digest() != expected_hash:
        raise ValueError("invalid private quarter spill database value integrity")
    return raw


def _spill_db_row_factory(cursor, row):
    """Expose the protected typed bytes while storing only envelopes on disk."""
    values = list(row)
    for index, column in enumerate(cursor.description or ()):
        if column[0] == "value" and values[index] is not None:
            values[index] = _spill_db_value_raw(values[index])
    return tuple(values)


class _QuarterSpill:
    """Private, run-owned typed records; never opens an input-supplied database.

    BLOB keys avoid SQLite affinity/collation changing Python keys. marshal is
    non-executable and preserves int/float/bool/bytes/tuple/list distinctions;
    this is an ephemeral implementation format, not a publication contract.
    """

    def __init__(self, directory: Path):
        _check_history_storage(directory)
        self.path = directory / "quarter-spill.records"
        self.db = None
        self.fd = None
        self.directory_fd = _open_recovery_path(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            # The named diagnostic journal is never reopened for writes.
            self.fd = os.open(self.path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=self.directory_fd)
            owned = os.fstat(self.fd)
            parent = os.fstat(self.directory_fd)
            self.directory_stamp = (parent.st_mtime_ns, parent.st_ctime_ns)
            self.bindings = {path: (path.stat().st_dev, path.stat().st_ino)
                             for path in directory.parents}
            self.bindings[directory] = (parent.st_dev, parent.st_ino)
            self.bindings[self.path] = (owned.st_dev, owned.st_ino)
            self.check()
            # Empty filename asks the trusted SQLite VFS for a private on-disk
            # temporary database. No publication pathname or sidecar is opened.
            self.db = sqlite3.connect("")
            self.db.row_factory = _spill_db_row_factory
            self.check()
            options = {row[0] for row in self.execute("PRAGMA compile_options")}
            if "TEMP_STORE=3" in options:
                raise ValueError("quarter spill requires SQLite disk-backed temporary storage")
            self.execute("PRAGMA temp_store=FILE")
            if self.execute("PRAGMA temp_store").fetchone() != (1,):
                raise ValueError("quarter spill temporary storage is not FILE")
            self.execute("PRAGMA cache_size=-2048")
            self.execute("PRAGMA mmap_size=0")
            # This index is disposable; the held-FD record journal, not SQLite
            # rollback, is retained evidence. No named DB journal is required.
            self.execute("PRAGMA journal_mode=OFF")
            self.execute("CREATE TABLE records (ordinal INTEGER PRIMARY KEY, bucket INTEGER, key BLOB, original_key BLOB, value BLOB, UNIQUE(bucket,key))")
            self.execute("CREATE INDEX bucket_order ON records(bucket,ordinal)")
            self.next_bucket = 0
            self.sequence_number = 0
            self._append_event({"event": "OPEN", "version": "quarter-spill-records-v1",
                                "sqlite_version": sqlite3.sqlite_version, "temp_store": "FILE",
                                "cache_kib": 2048, "index": "anonymous-disposable"})
        except BaseException:
            self.close()
            raise

    def execute(self, sql, parameters=()):
        self.check()
        return self.db.execute(sql, parameters)

    def _append_event(self, event):
        self.check()
        payload = _spill_pack(event)
        frame = len(payload).to_bytes(8, "big") + hashlib.sha256(payload).digest()
        for part in (frame, payload):
            remaining = memoryview(part)
            while remaining:
                written = os.write(self.fd, remaining)
                if written <= 0:
                    raise OSError("quarter spill journal short write")
                remaining = remaining[written:]

    def mutate(self, operation, bucket, key, value=None):
        self.check()
        self.sequence_number += 1
        sequence = self.sequence_number
        self._append_event({"event": "PLANNED", "sequence": sequence,
                            "operation": operation, "bucket": bucket, "key": key, "value": value})
        if operation == "SET":
            self.execute("INSERT INTO records(bucket,key,original_key,value) VALUES(?,?,?,?) ON CONFLICT(bucket,key) DO UPDATE SET value=excluded.value",
                         (bucket, _SpillMap._key(key), _spill_pack(key), _spill_db_value_pack((key, value))))
            row = self.execute("SELECT ordinal,original_key FROM records WHERE bucket=? AND key=?",
                               (bucket, _SpillMap._key(key))).fetchone()
            evidence = {"ordinal": row[0], "original_key": _spill_unpack(row[1])}
        elif operation == "DELETE":
            changed = self.execute("DELETE FROM records WHERE bucket=? AND key=?", (bucket, _SpillMap._key(key))).rowcount
            if not changed:
                # A PLANNED event without APPLIED is deliberately not reported
                # as committed or rolled back. Public recovery fails normally.
                raise KeyError(key)
            evidence = {}
        else:
            raise ValueError("unknown private quarter spill mutation")
        self._append_event({"event": "APPLIED", "sequence": sequence, **evidence})

    def mapping(self):
        self.next_bucket += 1
        self._append_event({"event": "BUCKET", "bucket": self.next_bucket})
        return _SpillMap(self, self.next_bucket)

    def sequence(self):
        return _SpillSequence(self.mapping())

    def check(self):
        _check_history_storage(self.path.parent)
        self._check_open_handles()
        for path, expected in self.bindings.items():
            try:
                actual = path.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValueError("quarter spill ownership changed; artifacts preserved") from exc
            if stat.S_ISLNK(actual.st_mode) or (actual.st_dev, actual.st_ino) != expected:
                raise ValueError("quarter spill ownership changed; artifacts preserved")

    def _check_open_handles(self):
        """Cheaply detect changes to the held directory entry and journal FD."""
        parent = os.fstat(self.directory_fd)
        if (parent.st_mtime_ns, parent.st_ctime_ns) != self.directory_stamp:
            raise ValueError("quarter spill ownership changed; directory entries changed")
        owned = os.fstat(self.fd)
        if (owned.st_dev, owned.st_ino) != self.bindings[self.path]:
            raise ValueError("quarter spill file descriptor ownership changed")

    def checkpoint(self):
        self.check()
        self.db.commit()
        self._append_event({"event": "CHECKPOINT", "sequence": self.sequence_number})
        os.fsync(self.fd)

    def close(self):
        # Reclaim only SQLite's anonymous cache. Named evidence is never deleted.
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.directory_fd is not None:
            os.close(self.directory_fd)
            self.directory_fd = None

    def resolve(self, locator):
        if "additive" in locator:
            record = _SpillSequence(_SpillMap(self, locator["additive"]))[locator["cell_key"]]
            cell, column, row = record["cell"], record["column"], record["row"]
            if (
                cell["fiscal_time_series_column_id"] != column["fiscal_time_series_column_id"]
                or cell["fiscal_time_series_row_id"] != row["fiscal_time_series_row_id"]
                or not approved_additive(cell)
            ):
                raise ValueError("quarter additive delta locator changed")
            return cell, column, row
        cell = _SpillMap(self, locator["cells"])[locator["cell_key"]]
        column = locator["reclassified_column"]
        _SpillMap(self, locator["columns"])[locator["column_id"]]
        row = _SpillMap(self, locator["rows"])[locator["row_id"]]
        if (cell["fiscal_time_series_column_id"] != column["fiscal_time_series_column_id"]
            or cell["fiscal_time_series_row_id"] != locator["row_id"]
            or not approved_additive(cell)):
            raise ValueError("quarter additive spill locator changed")
        return cell, column, row


class _SpillMap(MutableMapping):
    def __init__(self, spill, bucket):
        self.spill, self.bucket = spill, bucket

    @staticmethod
    def _key(key):
        # Canonicalize marshal's intern/reference flags before using bytes as
        # a SQL key. Equal keys must not depend on Python string interning.
        def typed(value):
            if isinstance(value, tuple):
                return ["tuple", [typed(item) for item in value]]
            if isinstance(value, (bool, int)) or (isinstance(value, float) and value.is_integer()):
                return ["int", int(value)]
            if value is None or type(value) in (str, float):
                return [type(value).__name__, value]
            raise TypeError("unsupported private quarter index key")
        return json.dumps(typed(key), ensure_ascii=True, separators=(",", ":")).encode()

    def __getitem__(self, key):
        row = self.spill.execute("SELECT value FROM records WHERE bucket=? AND key=?", (self.bucket, self._key(key))).fetchone()
        if row is None:
            raise KeyError(key)
        return _spill_unpack(row[0])[1]

    def __setitem__(self, key, value):
        # UPDATE preserves the first ordinal; INSERT OR REPLACE would not.
        self.spill.mutate("SET", self.bucket, key, value)

    def __delitem__(self, key):
        self.spill.mutate("DELETE", self.bucket, key)

    def __iter__(self):
        for row in self.spill.execute("SELECT original_key FROM records WHERE bucket=? ORDER BY ordinal", (self.bucket,)):
            yield _spill_unpack(row[0])

    def __len__(self):
        return self.spill.execute("SELECT count(*) FROM records WHERE bucket=?", (self.bucket,)).fetchone()[0]

    def values(self):
        for row in self.spill.execute("SELECT value FROM records WHERE bucket=? ORDER BY ordinal", (self.bucket,)):
            yield _spill_unpack(row[0])[1]

    def items(self):
        for row in self.spill.execute(
            "SELECT original_key,value FROM records WHERE bucket=? ORDER BY ordinal",
            (self.bucket,),
        ):
            # A caller may hold the iterator while an owned path is exchanged.
            # Validate every record before returning it, while retaining the
            # single ordered SQL query used by this performance path.
            self.spill.check()
            yield _spill_unpack(row[0]), _spill_unpack(row[1])[1]

    def records(self):
        return _SpillSequence(self)


class _SpillSequence(Sequence):
    def __init__(self, mapping):
        self.mapping = mapping
        self.length = len(mapping)

    def __len__(self):
        return self.length

    def __iter__(self):
        return self.mapping.values()

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                raise ValueError("spill slices require ordered contiguous records")
            return tuple(_spill_unpack(row[0])[1] for row in self.mapping.spill.execute("SELECT value FROM records WHERE bucket=? ORDER BY ordinal LIMIT ? OFFSET ?", (self.mapping.bucket, max(0, stop-start), start)))
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        row = self.mapping.spill.execute("SELECT value FROM records WHERE bucket=? ORDER BY ordinal LIMIT 1 OFFSET ?", (self.mapping.bucket, index)).fetchone()
        if row is None:
            raise IndexError(index)
        return _spill_unpack(row[0])[1]

    def append(self, value):
        self.mapping[self.length] = value
        self.length += 1


class _SpillGroups:
    def __init__(self, spill):
        self.spill, self.index = spill, spill.mapping()

    def get(self, key, default=None):
        bucket = self.index.get(key)
        return default if bucket is None else _SpillSequence(_SpillMap(self.spill, bucket))

    def setdefault(self, key, default=None):
        result = self.get(key)
        if result is None:
            result = self.spill.sequence()
            self.index[key] = result.mapping.bucket
        return result

    def items(self):
        for key in self.index:
            yield key, self.get(key)


def _quarter_progress(stage, table, count, started_at):
    import resource

    now = monotonic()
    print(json.dumps({"stage": stage, "ticker": table["ticker"],
                      "view": table["view"], "period_class": table["period_class"],
                      "records": count, "process_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      "monotonic_seconds": now, "elapsed_seconds": now - started_at}), flush=True)


def _copy_reclassified_cell(original):
    """Copy only dictionaries mutated while reclassifying a reported cell."""
    cell = dict(original)
    value = cell.get("value_lineage")
    if isinstance(value, dict):
        value = dict(value)
        cell["value_lineage"] = value
    return cell, value


class _QuarterDeltaFallback(ValueError):
    """Use the unchanged full quarter producer when delta proof is incomplete."""


_QUARTER_DELTA_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _QuarterDeltaCapability:
    """Private proof minted only after the append builder validates its prefix."""

    token: object
    publication: Path
    publication_manifest_sha256: str
    previous_history: Path
    previous_reported: Path
    dirty_period_classes: frozenset[str]
    input_fingerprint: str
    operational_roots: tuple[tuple[str, str], ...]
    producer_code_identity: str


def _make_quarter_delta_capability(
    *,
    publication: Path,
    previous_history: Path,
    previous_reported: Path,
    dirty_period_classes: frozenset[str],
    append_payload: Mapping[str, Any],
) -> _QuarterDeltaCapability:
    """Bind a validated append plan to the immutable reported publication."""
    from sec_xbrl.history_reuse import _producer_code_identity

    publication = Path(publication).absolute()
    manifest_path = publication / "history_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roots = manifest.get("operational_roots")
    if (
        append_payload.get("mode") != "STRICTLY_LATER_SINGLE_CIK_APPEND_V1"
        or manifest.get("history_append_reuse") != append_payload
        or not isinstance(roots, dict)
        or set(roots) != {"t1", "t2", "t3", "t4"}
        or append_payload.get("previous_history") != str(Path(previous_history).absolute())
        or append_payload.get("previous_reported") != str(Path(previous_reported).absolute())
        or append_payload.get("dirty_period_classes") != sorted(dirty_period_classes)
        or append_payload.get("producer_code_identity") != _producer_code_identity()
    ):
        raise ValueError("quarter delta requires a validated append capability")
    return _QuarterDeltaCapability(
        token=_QUARTER_DELTA_TOKEN,
        publication=publication,
        publication_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        previous_history=Path(previous_history).absolute(),
        previous_reported=Path(previous_reported).absolute(),
        dirty_period_classes=frozenset(dirty_period_classes),
        input_fingerprint=str(manifest["input_fingerprint"]),
        operational_roots=tuple(sorted((str(key), str(value)) for key, value in roots.items())),
        producer_code_identity=str(append_payload["producer_code_identity"]),
    )


def _quarter_delta_inputs(
    capability: _QuarterDeltaCapability | None,
    *,
    publication: Path,
    publication_manifest_sha256: str,
    input_fingerprint: str,
    operational_roots: Mapping[str, Path],
) -> tuple[Path, Path, frozenset[str]] | None:
    """Return proven delta inputs; unsupported or stale callers get full mode."""
    if not (
        capability is not None
        and capability.token is _QUARTER_DELTA_TOKEN
        and capability.publication == Path(publication).absolute()
        and capability.publication_manifest_sha256 == publication_manifest_sha256
        and capability.input_fingerprint == input_fingerprint
        and capability.operational_roots
        == tuple(
            sorted(
                (str(key), str(path.absolute()))
                for key, path in operational_roots.items()
            )
        )
    ):
        return None
    return (
        capability.previous_history,
        capability.previous_reported,
        capability.dirty_period_classes,
    )


def _delta_typed_equal(left: Any, right: Any) -> bool:
    """Typed equality with the established Parquet schema-union boundary."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = set(left) | set(right)
        return all(_delta_typed_equal(left.get(key), right.get(key)) for key in keys)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _delta_typed_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _delta_scalar_rows(root: Path, info: dict[str, Any], fields: tuple[str, ...]) -> tuple[tuple[Any, ...], ...]:
    """Read only compact scalar routing fields from one attested dataset."""
    import polars as pl

    path = _history_dataset_path(root, info)
    frame = pl.scan_parquet(path, parallel="none", low_memory=True, rechunk=False)
    schema = frame.collect_schema()
    if any(field not in schema for field in fields):
        raise _QuarterDeltaFallback("quarter delta routing field is unavailable")
    rows = frame.select(fields).collect(engine="streaming").iter_rows()
    result = tuple(tuple(row) for row in rows)
    if len(result) != info["count"]:
        raise _QuarterDeltaFallback("quarter delta routing count changed")
    return result


def _delta_table_key(table: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(table["ticker"]), str(table["view"]), str(table["period_class"])


def _new_delta_target(table: Mapping[str, Any], period_class: str, spill: Any) -> dict[str, Any]:
    return {
        "table": {
            **table,
            "period_class": period_class,
            "scope": {**table["scope"], "period_class": period_class},
        },
        "columns": spill.mapping(),
        "rows": spill.mapping(),
        "cell_chunks": [],
        "cell_buffer": [],
        "extra_columns": spill.mapping(),
        "extra_rows": spill.mapping(),
        "extra_cells": spill.sequence(),
    }


def _flush_delta_cells(target: dict[str, Any], chunk_root: Path, target_index: int) -> None:
    buffer = target["cell_buffer"]
    if not buffer:
        return
    path = chunk_root / f"delta-{target_index:04d}-{len(target['cell_chunks']):06d}-cells.parquet"
    plan = _stage_records(path, tuple(buffer))
    try:
        target["cell_chunks"].append({**_finalize_staged_records(plan), "path": path})
    finally:
        plan.cleanup()
    buffer.clear()


def _spill_reported_table(old, table, publication, by_fact, targets, materialized, changes, spill, additive):
    """Reclassify one fully decoded cell at a time; retain only disk references."""
    source = {}
    for name in ("columns", "rows"):
        source[name] = spill.mapping()
        for record in _iter_history_records(_history_dataset_path(old.root, table["files"][name]), table["files"][name]):
            source[name][record[f"fiscal_time_series_{name[:-1]}_id"]] = record
    record = None
    columns, rows = source["columns"], source["rows"]
    info = table["files"]["cells"]
    count = 0
    # A source table owns one value for each row ID. Columns can converge on
    # one reclassified target ID, so retain the last source-column identity
    # rather than assuming that target IDs are unique. These indexes live for
    # this source table only; the first write from every later table still
    # preserves the existing cross-table last-wins order.
    written_rows: set[tuple[tuple[str, str, str], str]] = set()
    last_source_column: dict[
        tuple[tuple[str, str, str], str], str
    ] = {}
    started_at = monotonic()
    _quarter_progress("QUARTER_SPILL_BEGIN", table, count, started_at)
    for original in _iter_history_records(_history_dataset_path(old.root, info), info):
        # Large evidence trees remain read-only until the typed spill serializes.
        cell, value = _copy_reclassified_cell(original)
        source_column_id = cell["fiscal_time_series_column_id"]
        old_column = columns[source_column_id]
        period_class = table["period_class"]
        if value is not None and value.get("selected_source_fact_id"):
            source = by_fact.get((value["source_filing_id"], value["selected_source_fact_id"]))
            if source is None or source["comparative_type"] != "CURRENT_FOCUS":
                raise ValueError("selected cell is not attested by corrected current-focus T1")
            for name in ("value_numeric", "value_text", "context_start_date", "context_end_date", "context_instant_date",
                         "context_id", "unit_id", "raw_concept_id", "raw_concept_qname", "raw_concept_namespace_uri",
                         "company_canonical_concept_id", "filed_date", "source_snapshot_id", "accession"):
                if source.get(name) != value.get(name):
                    raise ValueError("selected cell differs from corrected T1 source")
            for name in ("unit_numerator_measures", "unit_denominator_measures", "canonical_dimension_signature"):
                if json.dumps(_sequence(source.get(name)), sort_keys=True) != json.dumps(_sequence(value.get(name)), sort_keys=True):
                    raise ValueError("selected cell measurement scope differs from corrected T1")
            if value.get("selection_view") != table["view"] or value.get("selection_as_of_date") != old.manifest["plan"]["as_of_date"]:
                raise ValueError("selected cell view/as-of disagrees with publication")
            period_class = source["period_class"]
            if period_class != table["period_class"]:
                changes[f"{table['period_class']}->{period_class}"] += 1
            value.update(period_class=period_class, classification_rule_version=source["classification_rule_version"],
                         period_classification_reason=source.get("period_classification_reason"))
            if cell.get("candidate_lineage"):
                cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")
                cell["prior_candidate_publication"] = str(publication.absolute())
        key = (table["ticker"], table["view"], period_class)
        if key not in targets:
            targets[key] = {"table": {**table, "period_class": period_class,
                "scope": {**table["scope"], "period_class": period_class}},
                "columns": spill.mapping(), "rows": spill.mapping(), "cells": spill.sequence(),
                "extra_columns": spill.mapping(), "extra_rows": spill.mapping(), "extra_cells": spill.sequence()}
            materialized[key] = spill.mapping()
        target = targets[key]
        column = {**old_column, "period_class": period_class,
                  "fiscal_time_series_column_id": _id("column", (old_column["fiscal_year"], old_column["fiscal_quarter"], period_class))}
        column_id = column["fiscal_time_series_column_id"]
        cell["fiscal_time_series_column_id"] = column_id
        cell["fiscal_time_series_cell_id"] = _id("reclassified-cell", cell.get("fiscal_time_series_cell_id"), PERIOD_RULE)
        column_key = (key, column_id)
        if last_source_column.get(column_key) != source_column_id:
            target["columns"][column_id] = column
            last_source_column[column_key] = source_column_id
        row_id = cell["fiscal_time_series_row_id"]
        row_key = (key, row_id)
        if row_key not in written_rows:
            target["rows"][row_id] = rows[row_id]
            written_rows.add(row_key)
        cell_key = len(target["cells"])
        target["cells"].append(cell)
        materialized[key][(cell["fiscal_time_series_row_id"], cell["fiscal_time_series_column_id"])] = True
        if approved_additive(cell):
            pair_key = (key[0], key[1])
            if pair_key not in additive:
                additive[pair_key] = _SpillGroups(spill)
            pair = additive[pair_key]
            pair.setdefault((column["fiscal_year"], key[2], _scope(cell["value_lineage"]))).append({
                "cells": target["cells"].mapping.bucket, "cell_key": cell_key,
                # Source-table metadata, not later target overwrites, attests this candidate.
                "columns": columns.bucket, "rows": rows.bucket,
                "column_id": old_column["fiscal_time_series_column_id"],
                "row_id": cell["fiscal_time_series_row_id"],
                "reclassified_column": column})
        count += 1
        if count % 32 == 0:
            spill.checkpoint()
            _quarter_progress("QUARTER_SPILL_FLUSH", table, count, started_at)
    spill.checkpoint()
    _quarter_progress("QUARTER_SPILL_END", table, count, started_at)


def _delta_reclassify_cell(
    original: dict[str, Any],
    *,
    table: Mapping[str, Any],
    publication: Path,
    by_fact: Mapping[tuple[str, str], dict[str, Any]],
    old_column: dict[str, Any],
    changes: MutableMapping[str, int],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Run the unchanged full-producer transformation for one dirty occurrence."""
    cell, value = _copy_reclassified_cell(original)
    period_class = str(table["period_class"])
    if value is not None and value.get("selected_source_fact_id"):
        source = by_fact.get((value["source_filing_id"], value["selected_source_fact_id"]))
        if source is None or source["comparative_type"] != "CURRENT_FOCUS":
            raise ValueError("selected cell is not attested by corrected current-focus T1")
        for name in (
            "value_numeric", "value_text", "context_start_date", "context_end_date",
            "context_instant_date", "context_id", "unit_id", "raw_concept_id",
            "raw_concept_qname", "raw_concept_namespace_uri", "company_canonical_concept_id",
            "filed_date", "source_snapshot_id", "accession",
        ):
            if source.get(name) != value.get(name):
                raise ValueError("selected cell differs from corrected T1 source")
        for name in (
            "unit_numerator_measures", "unit_denominator_measures",
            "canonical_dimension_signature",
        ):
            if json.dumps(_sequence(source.get(name)), sort_keys=True) != json.dumps(
                _sequence(value.get(name)), sort_keys=True
            ):
                raise ValueError("selected cell measurement scope differs from corrected T1")
        if (
            value.get("selection_view") != table["view"]
            or value.get("selection_as_of_date") != table["scope"]["selection_as_of_date"]
        ):
            raise ValueError("selected cell view/as-of disagrees with publication")
        period_class = source["period_class"]
        if period_class != table["period_class"]:
            changes[f"{table['period_class']}->{period_class}"] += 1
        value.update(
            period_class=period_class,
            classification_rule_version=source["classification_rule_version"],
            period_classification_reason=source.get("period_classification_reason"),
        )
        if cell.get("candidate_lineage"):
            cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")
            cell["prior_candidate_publication"] = str(publication.absolute())
    column = {
        **old_column,
        "period_class": period_class,
        "fiscal_time_series_column_id": _id(
            "column",
            (old_column["fiscal_year"], old_column["fiscal_quarter"], period_class),
        ),
    }
    cell["fiscal_time_series_column_id"] = column["fiscal_time_series_column_id"]
    cell["fiscal_time_series_cell_id"] = _id(
        "reclassified-cell", cell.get("fiscal_time_series_cell_id"), PERIOD_RULE
    )
    return cell, column, str(period_class)


def _spill_reported_delta(
    *,
    current: HistoryPublicationReader,
    previous_reported: HistoryPublicationReader,
    previous_final: HistoryPublicationReader,
    publication: Path,
    by_fact: Mapping[tuple[str, str], dict[str, Any]],
    targets: dict[tuple[str, str, str], dict[str, Any]],
    materialized: dict[tuple[str, str, str], Any],
    changes: MutableMapping[str, int],
    spill: _QuarterSpill,
    additive: MutableMapping[tuple[str, str], Any],
    chunk_root: Path,
    dirty_period_classes: frozenset[str],
    metrics: MutableMapping[str, int],
) -> tuple[MutableMapping[str, Any], MutableMapping[str, Any]]:
    """Reuse exact old final cells and rebuild only changed source occurrences."""
    previous_tables = {_delta_table_key(table): table for table in previous_reported.manifest["tables"]}
    current_keys = [_delta_table_key(table) for table in current.manifest["tables"]]
    previous_keys = [_delta_table_key(table) for table in previous_reported.manifest["tables"]]
    if [key for key in current_keys if key in previous_tables] != previous_keys:
        raise _QuarterDeltaFallback("reported source table order is not append-compatible")

    final_tables = {_delta_table_key(table): table for table in previous_final.manifest["tables"]}
    final_locations: dict[str, deque[tuple[str, str, str]]] = defaultdict(deque)
    final_reported_counts: Counter[tuple[str, str, str]] = Counter()
    final_streams: dict[tuple[str, str, str], Any] = {}
    final_consumed: Counter[tuple[str, str, str]] = Counter()
    for key, table in final_tables.items():
        info = table["files"]["cells"]
        for cell_id, status in _delta_scalar_rows(
            previous_final.root, info, ("fiscal_time_series_cell_id", "value_status")
        ):
            if status == "DERIVED":
                continue
            final_locations[str(cell_id)].append(key)
            final_reported_counts[key] += 1
        final_streams[key] = iter(
            _iter_history_records(_history_dataset_path(previous_final.root, info), info)
        )

    additive_records = spill.sequence()
    target_indexes: dict[tuple[str, str, str], int] = {}

    def ensure_target(table: Mapping[str, Any], period_class: str) -> tuple[tuple[str, str, str], dict[str, Any]]:
        key = (str(table["ticker"]), str(table["view"]), str(period_class))
        if key not in targets:
            targets[key] = _new_delta_target(table, period_class, spill)
            materialized[key] = spill.mapping()
            target_indexes[key] = len(target_indexes)
        return key, targets[key]

    def take_previous(key: tuple[str, str, str], expected_id: str) -> dict[str, Any]:
        try:
            cell = next(final_streams[key])
        except (KeyError, StopIteration) as exc:
            raise _QuarterDeltaFallback("previous final cell stream ended early") from exc
        if cell.get("value_status") == "DERIVED" or cell.get("fiscal_time_series_cell_id") != expected_id:
            raise _QuarterDeltaFallback("previous final cell order changed")
        final_consumed[key] += 1
        return cell

    for table in current.manifest["tables"]:
        source_key = _delta_table_key(table)
        previous_table = previous_tables.get(source_key)
        current_maps: dict[str, Any] = {}
        previous_maps: dict[str, Any] = {}
        for name in ("columns", "rows"):
            current_maps[name] = spill.mapping()
            for record in _iter_history_records(
                _history_dataset_path(current.root, table["files"][name]), table["files"][name]
            ):
                current_maps[name][record[f"fiscal_time_series_{name[:-1]}_id"]] = record
            if previous_table is not None:
                previous_maps[name] = spill.mapping()
                for record in _iter_history_records(
                    _history_dataset_path(previous_reported.root, previous_table["files"][name]),
                    previous_table["files"][name],
                ):
                    previous_maps[name][record[f"fiscal_time_series_{name[:-1]}_id"]] = record

        previous_ids: Counter[str] = Counter()
        previous_iter = iter(())
        previous_next = None
        if previous_table is not None:
            previous_info = previous_table["files"]["cells"]
            previous_ids.update(
                str(row[0]) for row in _delta_scalar_rows(
                    previous_reported.root, previous_info, ("fiscal_time_series_cell_id",)
                )
            )
            previous_iter = iter(
                _iter_history_records(
                    _history_dataset_path(previous_reported.root, previous_info), previous_info
                )
            )
            previous_next = next(previous_iter, None)

        written_rows: set[tuple[tuple[str, str, str], str]] = set()
        last_source_column: dict[tuple[tuple[str, str, str], str], str] = {}
        current_info = table["files"]["cells"]
        for original in _iter_history_records(
            _history_dataset_path(current.root, current_info), current_info
        ):
            metrics["scanned_current_cells"] += 1
            source_cell_id = str(original["fiscal_time_series_cell_id"])
            source_column_id = str(original["fiscal_time_series_column_id"])
            row_id = str(original["fiscal_time_series_row_id"])
            old_column = current_maps["columns"][source_column_id]
            old_row = current_maps["rows"][row_id]
            existed = previous_ids[source_cell_id] > 0
            unchanged = False
            prior_key = None
            prior_cell = None
            if existed:
                if previous_next is None or str(previous_next.get("fiscal_time_series_cell_id")) != source_cell_id:
                    raise _QuarterDeltaFallback("reported cell order is not append-compatible")
                previous_column_id = str(previous_next["fiscal_time_series_column_id"])
                previous_row_id = str(previous_next["fiscal_time_series_row_id"])
                try:
                    unchanged = (
                        _delta_typed_equal(original, previous_next)
                        and _delta_typed_equal(old_column, previous_maps["columns"][previous_column_id])
                        and _delta_typed_equal(old_row, previous_maps["rows"][previous_row_id])
                    )
                except KeyError as exc:
                    raise _QuarterDeltaFallback("reported row or column identity changed") from exc
                previous_ids[source_cell_id] -= 1
                previous_next = next(previous_iter, None)
                output_id = _id("reclassified-cell", source_cell_id, PERIOD_RULE)
                if not final_locations[output_id]:
                    raise _QuarterDeltaFallback("previous final cell locator is missing")
                prior_key = final_locations[output_id].popleft()
                prior_cell = take_previous(prior_key, output_id)
                metrics["compared_cells"] += 1

            if unchanged:
                cell = dict(prior_cell)
                if "prior_candidate_publication" in cell:
                    cell["prior_candidate_publication"] = str(publication.absolute())
                period_class = prior_key[2]
                if period_class != table["period_class"]:
                    changes[f"{table['period_class']}->{period_class}"] += 1
                column = {
                    **old_column,
                    "period_class": period_class,
                    "fiscal_time_series_column_id": _id(
                        "column",
                        (old_column["fiscal_year"], old_column["fiscal_quarter"], period_class),
                    ),
                }
                metrics["reused_cells"] += 1
            else:
                cell, column, period_class = _delta_reclassify_cell(
                    original,
                    table=table,
                    publication=publication,
                    by_fact=by_fact,
                    old_column=old_column,
                    changes=changes,
                )
                key = (str(table["ticker"]), str(table["view"]), str(period_class))
                if prior_key is not None and prior_key != key:
                    raise _QuarterDeltaFallback("reported cell changed target partition")
                metrics["regenerated_cells"] += 1

            key, target = ensure_target(table, period_class)
            if key[2] in dirty_period_classes:
                column_id = str(column["fiscal_time_series_column_id"])
                column_key = (key, column_id)
                if last_source_column.get(column_key) != source_column_id:
                    target["columns"][column_id] = column
                    last_source_column[column_key] = source_column_id
                row_key = (key, row_id)
                if row_key not in written_rows:
                    target["rows"][row_id] = old_row
                    written_rows.add(row_key)
                target["cell_buffer"].append(cell)
                materialized[key][(row_id, column_id)] = True
                if len(target["cell_buffer"]) == 32:
                    _flush_delta_cells(target, chunk_root, target_indexes[key])
            if approved_additive(cell):
                additive_index = len(additive_records)
                additive_records.append({
                    "cell": cell,
                    "column": column,
                    "row": old_row,
                    "inputs_unchanged": unchanged,
                })
                pair_key = (key[0], key[1])
                if pair_key not in additive:
                    additive[pair_key] = _SpillGroups(spill)
                additive[pair_key].setdefault(
                    (column["fiscal_year"], key[2], _scope(cell["value_lineage"]))
                ).append(
                    {
                        "additive": additive_records.mapping.bucket,
                        "cell_key": additive_index,
                    }
                )

        if previous_next is not None or any(previous_ids.values()):
            raise _QuarterDeltaFallback("reported source cell was removed")

    if any(final_locations.values()) or final_consumed != final_reported_counts:
        raise _QuarterDeltaFallback("previous final reported cells were not consumed exactly")
    prior_derived_cells = spill.mapping()
    for stream in final_streams.values():
        for cell in stream:
            if cell.get("value_status") != "DERIVED":
                raise _QuarterDeltaFallback("previous final cell order changed")
            cell_id = str(cell["fiscal_time_series_cell_id"])
            if cell_id in prior_derived_cells:
                raise _QuarterDeltaFallback("previous derived cell identity is duplicated")
            prior_derived_cells[cell_id] = cell
    prior_derived_metrics = spill.mapping()
    derived_info = previous_final.manifest.get("derived_quarter")
    if not isinstance(derived_info, dict):
        raise _QuarterDeltaFallback("previous derived-quarter evidence is missing")
    for metric in _iter_history_records(
        _history_dataset_path(previous_final.root, derived_info), derived_info
    ):
        metric_id = str(metric["derived_metric_id"])
        if metric_id in prior_derived_metrics:
            raise _QuarterDeltaFallback("previous derived metric identity is duplicated")
        prior_derived_metrics[metric_id] = metric
    if set(prior_derived_cells) != set(prior_derived_metrics):
        raise _QuarterDeltaFallback("previous derived cells and metrics disagree")
    for target in targets.values():
        _flush_delta_cells(target, chunk_root, target_indexes[_delta_table_key(target["table"])])
    return prior_derived_cells, prior_derived_metrics


def _assemble_spilled_table(target, staging, spill):
    table = {**target["table"], "files": {}}
    for key, column in target["extra_columns"].items():
        target["columns"].setdefault(key, column)
    for key, row in target["extra_rows"].items():
        target["rows"].setdefault(key, row)
    for cell in target["extra_cells"]:
        target["cells"].append(cell)
    boundaries = _SpillGroups(spill)
    unique = spill.mapping()
    for cell in target["cells"]:
        lineage = cell.get("value_lineage")
        if isinstance(lineage, dict):
            column_id = cell["fiscal_time_series_column_id"]
            boundary = tuple(lineage.get(name) for name in ("context_start_date", "context_end_date", "context_instant_date"))
            if (column_id, boundary) not in unique:
                unique[column_id, boundary] = True
                boundaries.setdefault(column_id).append(boundary)
    # Sort only fiscal keys/IDs. One complete boundary-bearing column is an
    # indivisible output record; never retain all such records at once.
    order = sorted(((column["fiscal_year"], column["fiscal_quarter"] is None, column["fiscal_quarter"] or 0, table["period_class"]), key) for key, column in target["columns"].items())
    columns = spill.sequence()
    previous = None
    for _, column_id in order:
        column = target["columns"][column_id]
        values = [{"context_start_date": start, "context_end_date": end,
                   "context_instant_date": instant, "value_status": "REPORTED"}
                  for start, end, instant in sorted(boundaries.get(column_id, ()), key=lambda item: tuple(value or "" for value in item))]
        rebuilt = _column((column["fiscal_year"], column["fiscal_quarter"], table["period_class"]), column.get("fiscal_year_end_as_filed"), _period_evidence(SimpleNamespace(values=values)))
        annotated = _annotate_comparability((rebuilt,) if previous is None else (previous, rebuilt))[-1]
        columns.append(annotated)
        if rebuilt["column_status"] == "AVAILABLE":
            previous = rebuilt
    payloads = {"columns": columns, "rows": target["rows"].records(), "cells": target["cells"]}
    previous = rebuilt = annotated = None
    cell = row = column = lineage = values = None
    spill.checkpoint()
    for name, records in payloads.items():
        relative = Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet"
        plan = _stage_records(staging / relative, records)
        table["files"][name] = {**_finalize_staged_records(plan), "path": str(relative)}
    return table


def _assemble_delta_table(target: dict[str, Any], staging: Path, spill: _QuarterSpill) -> dict[str, Any]:
    """Assemble bounded delta chunks with the full producer's observable order."""
    table = {**target["table"], "files": {}}
    for key, column in target["extra_columns"].items():
        target["columns"].setdefault(key, column)
    for key, row in target["extra_rows"].items():
        target["rows"].setdefault(key, row)
    chunks = list(target["cell_chunks"])
    if len(target["extra_cells"]):
        path = staging / ".delta-chunks" / f"delta-derived-{table['view']}-{table['period_class']}.parquet"
        plan = _stage_records(path, target["extra_cells"])
        try:
            chunks.append({**_finalize_staged_records(plan), "path": path})
        finally:
            plan.cleanup()

    boundaries = _SpillGroups(spill)
    unique = spill.mapping()
    for info in chunks:
        for cell in _iter_history_records(info["path"], info):
            lineage = cell.get("value_lineage")
            if isinstance(lineage, dict):
                column_id = cell["fiscal_time_series_column_id"]
                boundary = tuple(
                    lineage.get(name)
                    for name in ("context_start_date", "context_end_date", "context_instant_date")
                )
                if (column_id, boundary) not in unique:
                    unique[column_id, boundary] = True
                    boundaries.setdefault(column_id).append(boundary)

    order = sorted(
        (
            (
                column["fiscal_year"],
                column["fiscal_quarter"] is None,
                column["fiscal_quarter"] or 0,
                table["period_class"],
            ),
            key,
        )
        for key, column in target["columns"].items()
    )
    columns = spill.sequence()
    previous = None
    for _, column_id in order:
        column = target["columns"][column_id]
        values = [
            {
                "context_start_date": start,
                "context_end_date": end,
                "context_instant_date": instant,
                "value_status": "REPORTED",
            }
            for start, end, instant in sorted(
                boundaries.get(column_id, ()),
                key=lambda item: tuple(value or "" for value in item),
            )
        ]
        rebuilt = _column(
            (column["fiscal_year"], column["fiscal_quarter"], table["period_class"]),
            column.get("fiscal_year_end_as_filed"),
            _period_evidence(SimpleNamespace(values=values)),
        )
        annotated = _annotate_comparability(
            (rebuilt,) if previous is None else (previous, rebuilt)
        )[-1]
        columns.append(annotated)
        if rebuilt["column_status"] == "AVAILABLE":
            previous = rebuilt

    payloads = {"columns": columns, "rows": target["rows"].records()}
    for name, records in payloads.items():
        relative = Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet"
        plan = _stage_records(staging / relative, records)
        try:
            table["files"][name] = {**_finalize_staged_records(plan), "path": str(relative)}
        finally:
            plan.cleanup()
    cell_relative = Path(table["cik"]) / table["view"] / table["period_class"] / "cells.parquet"
    table["files"]["cells"] = {
        **_concatenate_staged_records(staging / cell_relative, chunks),
        "path": str(cell_relative),
    }
    return table


def _read_staged_records(path: Path, info: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Read one producer-owned chunk with the same hash/count checks as history."""
    import polars as pl

    json_fields = _attest_staged_chunk(path, info)
    rows = pl.read_parquet(path).to_dicts()
    return tuple(
        {
            key: json.loads(value)
            if key in json_fields and value is not None
            else value
            for key, value in row.items()
        }
        for row in rows
    )


def _attest_staged_chunk(path: Path, info: dict[str, Any]) -> frozenset[str]:
    """Verify the complete immutable chunk before decoding any selected record."""
    import polars as pl

    if path.is_symlink() or not path.is_file() or _sha256_file(path) != info["sha256"]:
        raise ValueError("quarter history staging chunk integrity mismatch")
    frame = pl.scan_parquet(path)
    schema = frame.collect_schema()
    count = frame.select(pl.len()).collect(engine="streaming").item()
    if count != info["count"]:
        raise ValueError("quarter history staging chunk count mismatch")
    declared = info.get("json_fields")
    if (
        not isinstance(declared, list)
        or not all(isinstance(field, str) for field in declared)
        or not set(declared).issubset(schema.names())
    ):
        raise ValueError("quarter history staging chunk schema mismatch")
    return frozenset(declared)


def _read_staged_record_at(
    path: Path, info: dict[str, Any], index: int
) -> dict[str, Any]:
    """Decode one ordered record after full-file integrity and schema attestation."""
    import polars as pl

    json_fields = _attest_staged_chunk(path, info)
    if type(index) is not int or index < 0 or index >= info["count"]:
        raise ValueError("quarter additive cell locator is invalid")
    rows = (
        pl.scan_parquet(path)
        .slice(index, 1)
        .collect(engine="streaming")
        .to_dicts()
    )
    if len(rows) != 1:
        raise ValueError("quarter additive cell locator changed")
    return {
        key: json.loads(value)
        if key in json_fields and value is not None
        else value
        for key, value in rows[0].items()
    }


def _merge_staged_rows(
    destination: dict[str, dict[str, Any]], rows: tuple[dict[str, Any], ...]
) -> None:
    """Match the legacy table-order merge: later source row metadata wins."""
    for row in rows:
        destination[row["fiscal_time_series_row_id"]] = row


def _resolve_additive_locator(
    locator: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve one unique additive candidate from verified producer chunks."""
    chunks = locator["chunks"]
    index = locator["cell_index"]
    cell = _read_staged_record_at(
        chunks["cells"]["path"], chunks["cells"], index
    )
    if (
        cell.get("fiscal_time_series_column_id") != locator["column_id"]
        or cell.get("fiscal_time_series_row_id") != locator["row_id"]
        or not approved_additive(cell)
    ):
        raise ValueError("quarter additive cell locator changed")
    columns = _read_staged_records(chunks["columns"]["path"], chunks["columns"])
    rows = _read_staged_records(chunks["rows"]["path"], chunks["rows"])
    matching_columns = [
        row
        for row in columns
        if row["fiscal_time_series_column_id"] == locator["column_id"]
    ]
    matching_rows = [
        row
        for row in rows
        if row["fiscal_time_series_row_id"] == locator["row_id"]
    ]
    if len(matching_columns) != 1 or len(matching_rows) != 1:
        raise ValueError("quarter additive row or column locator changed")
    return cell, matching_columns[0], matching_rows[0]


def _concatenate_staged_records(
    destination: Path,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stream validated encoded chunks into one ordered Parquet dataset."""
    _check_history_storage(destination)
    import polars as pl

    if not chunks:
        return _write_records(destination, ())
    validated_chunks: list[tuple[dict[str, Any], Any]] = []
    count = 0
    json_fields: set[str] = set()
    for info in chunks:
        path = info["path"]
        if path.is_symlink() or _sha256_file(path) != info["sha256"]:
            raise ValueError("quarter history staging chunk integrity mismatch")
        actual_count = (
            pl.scan_parquet(path).select(pl.len().alias("count")).collect().item()
        )
        if actual_count != info["count"]:
            raise ValueError("quarter history staging chunk count mismatch")
        frame = pl.scan_parquet(path)
        validated_chunks.append((info, frame))
        count += info["count"]
        json_fields.update(info["json_fields"])
    frames = []
    for info, frame in validated_chunks:
        columns = set(frame.collect_schema().names())
        local_json_fields = set(info["json_fields"])
        scalar_json_fields = sorted((json_fields - local_json_fields) & columns)
        if scalar_json_fields:
            frame = frame.with_columns(
                pl.col(field)
                .map_elements(
                    lambda value: json.dumps(value, sort_keys=True, default=str),
                    return_dtype=pl.String,
                )
                .alias(field)
                for field in scalar_json_fields
            )
        frames.append(frame)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pl.concat(frames, how="diagonal_relaxed").sink_parquet(
        destination,
        maintain_order=True,
        mkdir=True,
    )
    return {
        "count": count,
        "json_fields": sorted(json_fields),
        "sha256": _sha256_file(destination),
    }


def derive_quarter(later: dict[str, Any], earlier: dict[str, Any], *, quarter: int) -> dict[str, Any] | None:
    """One reviewed additive difference; reject all incompatible scopes."""
    if quarter not in {2, 3, 4} or not approved_additive(later) or not approved_additive(earlier):
        return None
    left, right = later["value_lineage"], earlier["value_lineage"]
    expected = {2: ("YTD_6M", "QTD_3M"), 3: ("YTD_9M", "YTD_6M"), 4: ("FY", "YTD_9M")}[quarter]
    if (left.get("period_class"), right.get("period_class")) != expected or _scope(left) != _scope(right):
        return None
    if not left.get("context_start_date") or left.get("context_start_date") != right.get("context_start_date"):
        return None
    for key in ("basis_version", "structural_version", "recast_version"):
        if left.get(key) != right.get(key):
            return None
    if any(value.get("continuity_break") or value.get("recast_review_required") for value in (left, right)):
        return None
    as_of = left.get("selection_as_of_date")
    if not as_of or any(not value.get("filed_date") or value["filed_date"] > as_of for value in (left, right)):
        return None
    try:
        start, end = date.fromisoformat(right["context_end_date"]), date.fromisoformat(left["context_end_date"])
        if not 75 <= (end - start).days <= 105:
            return None
        amount = Decimal(str(left["value_numeric"])) - Decimal(str(right["value_numeric"]))
        if not amount.is_finite():
            return None
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return None
    fact_ids = [left["selected_source_fact_id"], right["selected_source_fact_id"]]
    metric_id = _id("derived", QUARTER_RULE, fact_ids, quarter, _scope(left))
    return {"derived_metric_id": metric_id, "derivation_rule_version": QUARTER_RULE,
            "formula": f"{expected[0]} - {expected[1]}", "fiscal_quarter": quarter,
            "value_numeric": str(amount), "context_start_date": str(start), "context_end_date": str(end),
            "period_class": "QTD_3M", "source_fact_ids": fact_ids,
            "source_filing_ids": [left["source_filing_id"], right["source_filing_id"]],
            "source_accessions": [left["accession"], right["accession"]],
            "source_inputs": [deepcopy(left), deepcopy(right)], "source_type": "DERIVED_QUARTER",
            "reported_or_derived": "DERIVED", "semantic_review_state": "REVIEWED_ADDITIVE_AMOUNT",
            "policy_registry": "CONTROLLED_STANDARD_STATEMENT_ALLOWLIST",
            "basis_compatibility": "DIRECT_REPORTED_SAME_SCOPE_NO_EVIDENCED_BREAK_NOT_RECAST_COMPARABLE"}


def _repartition_reported_table(old, table, publication, by_fact, targets, materialized, changes):
    """Return owned partitions; source reader results die before storage work."""
    result = old.load(ticker=table["ticker"], period_class=table["period_class"], view=table["view"])
    columns = {column["fiscal_time_series_column_id"]: column for column in result.columns}
    rows = {row["fiscal_time_series_row_id"]: row for row in result.rows}
    chunks: dict[tuple[str, str, str], dict[str, Any]] = {}
    for original in result.cells:
        cell = deepcopy(original)
        value = cell.get("value_lineage")
        old_column = columns[cell["fiscal_time_series_column_id"]]
        period_class = table["period_class"]
        if value is not None and value.get("selected_source_fact_id"):
            source = by_fact.get((value["source_filing_id"], value["selected_source_fact_id"]))
            if source is None or source["comparative_type"] != "CURRENT_FOCUS":
                raise ValueError("selected cell is not attested by corrected current-focus T1")
            for name in ("value_numeric", "value_text", "context_start_date", "context_end_date", "context_instant_date",
                         "context_id", "unit_id", "raw_concept_id", "raw_concept_qname", "raw_concept_namespace_uri",
                         "company_canonical_concept_id", "filed_date", "source_snapshot_id", "accession"):
                if source.get(name) != value.get(name):
                    raise ValueError("selected cell differs from corrected T1 source")
            for name in ("unit_numerator_measures", "unit_denominator_measures", "canonical_dimension_signature"):
                if json.dumps(_sequence(source.get(name)), sort_keys=True) != json.dumps(_sequence(value.get(name)), sort_keys=True):
                    raise ValueError("selected cell measurement scope differs from corrected T1")
            if value.get("selection_view") != table["view"] or value.get("selection_as_of_date") != old.manifest["plan"]["as_of_date"]:
                raise ValueError("selected cell view/as-of disagrees with publication")
            period_class = source["period_class"]
            if period_class != table["period_class"]:
                changes[f"{table['period_class']}->{period_class}"] += 1
            value.update(period_class=period_class, classification_rule_version=source["classification_rule_version"],
                         period_classification_reason=source.get("period_classification_reason"))
            if cell.get("candidate_lineage"):
                cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")
                cell["prior_candidate_publication"] = str(publication.absolute())
        key = (table["ticker"], table["view"], period_class)
        targets.setdefault(key, {"table": {**table, "period_class": period_class,
            "scope": {**table["scope"], "period_class": period_class}}, "chunks": [],
            "extra_rows": {}, "extra_columns": {}, "extra_cells": []})
        bundle = chunks.setdefault(key, {"rows": {}, "columns": {}, "cells": []})
        column = {**old_column, "period_class": period_class,
                  "fiscal_time_series_column_id": _id("column", (old_column["fiscal_year"], old_column["fiscal_quarter"], period_class))}
        cell["fiscal_time_series_column_id"] = column["fiscal_time_series_column_id"]
        cell["fiscal_time_series_cell_id"] = _id("reclassified-cell", cell.get("fiscal_time_series_cell_id"), PERIOD_RULE)
        bundle["columns"][column["fiscal_time_series_column_id"]] = column
        bundle["rows"][cell["fiscal_time_series_row_id"]] = rows[cell["fiscal_time_series_row_id"]]
        bundle["cells"].append(cell)
        materialized[key].add((cell["fiscal_time_series_row_id"], cell["fiscal_time_series_column_id"]))
    return chunks


def _stage_quarter_bundle(bundle, *, key, table_index, chunk_index, chunk_root,
                          targets, additive_by_pair):
    """Transfer every encoded payload to disk before any native final merge."""
    staged = {}
    chunk_files = {}
    try:
        for name in ("columns", "rows", "cells"):
            records = tuple(bundle[name] if name == "cells" else bundle[name].values())
            path = chunk_root / f"{table_index:04d}-{chunk_index:02d}-{name}.parquet"
            staged[name] = _stage_records(path, records)
            del records
        # Locators refer to metadata populated below, never live cell payloads.
        pair_groups = additive_by_pair.setdefault((key[0], key[1]), {})
        for cell_index, cell in enumerate(bundle["cells"]):
            if not approved_additive(cell):
                continue
            column = bundle["columns"][cell["fiscal_time_series_column_id"]]
            pair_groups.setdefault(
                (
                    column["fiscal_year"],
                    key[2],
                    _scope(cell["value_lineage"]),
                ),
                [],
            ).append(
                {
                    "chunks": chunk_files,
                    "cell_index": cell_index,
                    "column_id": cell["fiscal_time_series_column_id"],
                    "row_id": cell["fiscal_time_series_row_id"],
                }
            )
        cell = column = None
        bundle.clear()
        gc.collect()
        for name, plan in staged.items():
            chunk_files[name] = {**_finalize_staged_records(plan), "path": plan.path}
        targets[key]["chunks"].append(chunk_files)
    finally:
        for plan in staged.values():
            plan.cleanup()


def _derive_quarter_targets(
    targets,
    additive_by_pair,
    materialized,
    spill=None,
    *,
    prior_derived_cells=None,
    prior_derived_metrics=None,
    delta_metrics=None,
):
    """Keep candidate source aliases within the derivation phase."""
    derived = [] if spill is None else spill.sequence()
    resolve = _resolve_additive_locator if spill is None else spill.resolve
    retained_derived_ids: set[str] = set()
    for ticker, view in sorted({(key[0], key[1]) for key in targets}):
        qtd_key = (ticker, view, "QTD_3M")
        qtd = targets.get(qtd_key)
        if qtd is None:
            continue
        grouped = additive_by_pair.get((ticker, view), {})
        for (year, kind, scope), choices in grouped.items():
            quarter = {"YTD_6M": 2, "YTD_9M": 3, "FY": 4}.get(kind)
            if quarter is None:
                continue
            previous = {2: "QTD_3M", 3: "YTD_6M", 4: "YTD_9M"}[quarter]
            partners = grouped.get((year, previous, scope), [])
            if quarter == 2:
                filtered = [] if spill is None else spill.sequence()
                for item in partners:
                    if resolve(item)[1]["fiscal_quarter"] == 1:
                        filtered.append(item)
                partners = filtered
            if len(choices) != 1 or len(partners) != 1:
                continue
            later, annual_column, source_row = resolve(choices[0])
            earlier = resolve(partners[0])[0]
            reusable = (
                prior_derived_cells is not None
                and prior_derived_metrics is not None
                and choices[0].get("inputs_unchanged") is True
                and partners[0].get("inputs_unchanged") is True
            )
            metric_id = _id(
                "derived",
                QUARTER_RULE,
                [
                    later["value_lineage"]["selected_source_fact_id"],
                    earlier["value_lineage"]["selected_source_fact_id"],
                ],
                quarter,
                _scope(later["value_lineage"]),
            )
            reusable = (
                reusable
                and metric_id in prior_derived_metrics
                and metric_id in prior_derived_cells
            )
            if reusable:
                metric = prior_derived_metrics[metric_id]
            else:
                metric = derive_quarter(later, earlier, quarter=quarter)
            if metric is None:
                continue
            row_id = later["fiscal_time_series_row_id"]
            column_id = _id("column", (year, quarter, "QTD_3M"))
            if (row_id, column_id) in materialized[qtd_key]:
                continue
            if reusable:
                prior_cell = prior_derived_cells[metric_id]
                if (
                    metric.get("derived_metric_id") != metric_id
                    or prior_cell.get("fiscal_time_series_cell_id") != metric_id
                    or prior_cell.get("fiscal_time_series_row_id") != row_id
                    or prior_cell.get("fiscal_time_series_column_id") != column_id
                    or prior_cell.get("value_status") != "DERIVED"
                ):
                    raise _QuarterDeltaFallback("previous derived cell binding changed")
                column = _column(
                    (year, quarter, "QTD_3M"),
                    annual_column.get("fiscal_year_end_as_filed"),
                    _period_evidence(
                        SimpleNamespace(
                            values=[
                                {
                                    **prior_cell["value_lineage"],
                                    "value_status": "REPORTED",
                                }
                            ]
                        )
                    ),
                )
                qtd["extra_columns"].setdefault(column_id, column)
                qtd["extra_rows"].setdefault(row_id, source_row)
                derived.append(metric)
                qtd["extra_cells"].append(prior_cell)
                retained_derived_ids.add(metric_id)
                if delta_metrics is not None:
                    delta_metrics["derived_reused_cells"] += 1
                continue
            metric.update(cik=qtd["table"]["cik"], ticker=ticker, fiscal_year=year, view=view)
            derived.append(metric)
            value = {**deepcopy(later["value_lineage"]), **metric, "value_status": "DERIVED", "value_text": None,
                     "context_instant_date": None, "selected_source_fact_id": None, "source_filing_id": None,
                     "source_snapshot_id": None, "context_id": None, "accession": None,
                     "analysis_line_value_id": metric["derived_metric_id"]}
            definition = {**deepcopy(later["definition"]), "line_kind": "DERIVED"}
            binding = {"analysis_binding_id": metric["derived_metric_id"], "analysis_line_id": definition["analysis_line_id"],
                       "binding_kind": "GOVERNED_DERIVED_QUARTER", "derived_metric_id": metric["derived_metric_id"],
                       "source_bindings": [deepcopy(later["binding"]), deepcopy(earlier["binding"])]}
            column = _column((year, quarter, "QTD_3M"), annual_column.get("fiscal_year_end_as_filed"),
                             _period_evidence(SimpleNamespace(values=[{**value, "value_status": "REPORTED"}])))
            qtd["extra_columns"].setdefault(column_id, column)
            qtd["extra_rows"].setdefault(row_id, source_row)
            qtd["extra_cells"].append({"fiscal_time_series_cell_id": metric["derived_metric_id"], "fiscal_time_series_row_id": row_id,
                                  "fiscal_time_series_column_id": column_id, "value_status": "DERIVED", "value_numeric": metric["value_numeric"],
                                  "value_text": None, "comparability_status": "COMPATIBLE_INPUTS", "comparability_reason": metric["basis_compatibility"],
                                  "definition": definition, "binding": binding, "value_lineage": value})
            retained_derived_ids.add(str(metric["derived_metric_id"]))
            if delta_metrics is not None:
                delta_metrics["derived_recomputed_cells"] += 1
    if prior_derived_metrics is not None and delta_metrics is not None:
        delta_metrics["derived_removed_cells"] = sum(
            1 for metric_id in prior_derived_metrics if metric_id not in retained_derived_ids
        )
    return derived


def _assemble_quarter_table(target, *, target_index, staging, chunk_root):
    """Assemble one output, releasing its owned payloads before native merges."""
    table = {**target["table"], "files": {}}
    bundle: dict[str, Any] = {"columns": {}, "rows": {}}
    boundaries: dict[str, set[tuple[Any, Any, Any]]] = defaultdict(set)
    cell_chunks: list[dict[str, Any]] = []
    for chunk in target["chunks"]:
        for column in _read_staged_records(chunk["columns"]["path"], chunk["columns"]):
            bundle["columns"][column["fiscal_time_series_column_id"]] = column
        _merge_staged_rows(
            bundle["rows"],
            _read_staged_records(chunk["rows"]["path"], chunk["rows"]),
        )
        _attest_staged_chunk(chunk["cells"]["path"], chunk["cells"])
        for cell in _iter_history_records(chunk["cells"]["path"], chunk["cells"]):
            lineage = cell.get("value_lineage")
            if isinstance(lineage, dict):
                boundaries[cell["fiscal_time_series_column_id"]].add(
                    (
                        lineage.get("context_start_date"),
                        lineage.get("context_end_date"),
                        lineage.get("context_instant_date"),
                    )
                )
        cell_chunks.append(chunk["cells"])
    for column_id, column in target["extra_columns"].items():
        bundle["columns"].setdefault(column_id, column)
    for row_id, row in target["extra_rows"].items():
        bundle["rows"].setdefault(row_id, row)
    if target["extra_cells"]:
        extra_path = chunk_root / f"derived-{target_index:04d}-cells.parquet"
        extra_info = {
            **_write_records(extra_path, tuple(target["extra_cells"])),
            "path": extra_path,
        }
        cell_chunks.append(extra_info)
        for cell in target["extra_cells"]:
            lineage = cell.get("value_lineage")
            if isinstance(lineage, dict):
                boundaries[cell["fiscal_time_series_column_id"]].add(
                    (
                        lineage.get("context_start_date"),
                        lineage.get("context_end_date"),
                        lineage.get("context_instant_date"),
                    )
                )
    # Recompute column boundaries from the corrected partition, not the old
    # FY/TTM mixture. Include derived durations as explicit source evidence.
    columns = []
    for column in bundle["columns"].values():
        values = [
            {
                "context_start_date": start,
                "context_end_date": end,
                "context_instant_date": instant,
                "value_status": "REPORTED",
            }
            for start, end, instant in sorted(
                boundaries.get(column["fiscal_time_series_column_id"], set()),
                key=lambda item: tuple(value or "" for value in item),
            )
        ]
        rebuilt = _column((column["fiscal_year"], column["fiscal_quarter"], table["period_class"]), column.get("fiscal_year_end_as_filed"),
                          _period_evidence(SimpleNamespace(values=values)))
        columns.append(rebuilt)
    payloads = {
        "columns": _annotate_comparability(
            tuple(sorted(columns, key=lambda c: c["column_order_key"]))
        ),
        "rows": tuple(bundle["rows"].values()),
    }
    staged = {}
    try:
        for name, records in payloads.items():
            relative = Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet"
            staged[name] = _stage_records(staging / relative, records)
        # Remove all owners of rows and derived cells before native merging.
        column = row = cell = lineage = values = None
        del records, payloads, bundle, columns
        target.clear()
        gc.collect()
        for name, plan in staged.items():
            table["files"][name] = {
                **_finalize_staged_records(plan), "path": str(plan.path.relative_to(staging))
            }
    finally:
        for plan in staged.values():
            plan.cleanup()
    cell_relative = (
        Path(table["cik"])
        / table["view"]
        / table["period_class"]
        / "cells.parquet"
    )
    table["files"]["cells"] = {
        **_concatenate_staged_records(staging / cell_relative, cell_chunks),
        "path": str(cell_relative),
    }
    return table


def _quarter_target_keys(
    targets: Mapping[tuple[Any, Any, Any], Any],
) -> list[tuple[str, str, str]]:
    """Keep the full producer's target order for incremental publication."""
    return sorted((str(key[0]), str(key[1]), str(key[2])) for key in targets)


def publish_quarter_history(*, publication: Path, output_root: Path, reuse_roots: bool = False,
                            operational_root: Path | None = None, _recovery_access: Any = None,
                            validation_mode: str = "routine",
                            validation_state_root: Path | None = None,
                            previous_history: Path | None = None,
                            previous_reported: Path | None = None,
                            dirty_period_classes: frozenset[str] | None = None,
                            _delta_capability: _QuarterDeltaCapability | None = None) -> Path:
    """Upgrade reported period evidence and materialize governed quarter cells."""
    old = HistoryPublicationReader(publication, _recovery_access=_recovery_access)
    if _recovery_access is None:
        old.validate(mode=validation_mode, state_root=validation_state_root)
    else:
        old.verify_all()
    destination = output_root / "panels"
    if destination.exists():
        raise ValueError("choose a new immutable quarterly publication destination")
    _check_history_storage()
    output_root.mkdir(parents=True, exist_ok=True)
    intake_path = Path(old.manifest["source_intake"])
    if not reuse_roots and operational_root is None:
        build_history(
            intake_manifest=intake_path, output_root=output_root,
            views=tuple(old.manifest["views"]), roots_only=True,
            validation_mode=validation_mode, validation_state_root=validation_state_root,
        )
    prepared_root = operational_root or output_root
    roots = {name: prepared_root / name / prepared_root.name for name in ("t1", "t2", "t3", "t4")}
    observed = Layer2PublicationReader().load(roots["t1"])
    input_fingerprint = observed.identity["layer2_run_fingerprint"]
    if (reuse_roots or operational_root is not None) and input_fingerprint != old.manifest["input_fingerprint"]:
        raise ValueError("reused period publications do not match reported panels")
    delta_inputs = _quarter_delta_inputs(
        _delta_capability,
        publication=publication,
        publication_manifest_sha256=hashlib.sha256(
            (old.root / "history_manifest.json").read_bytes()
        ).hexdigest(),
        input_fingerprint=input_fingerprint,
        operational_roots=roots,
    )
    if delta_inputs is not None:
        previous_history, previous_reported, dirty_period_classes = delta_inputs
    else:
        if previous_history is not None or previous_reported is not None or dirty_period_classes is not None:
            print(
                json.dumps(
                    {
                        "stage": "QUARTER_CELL_DELTA_FULL_FALLBACK",
                        "reason": "validated append capability is unavailable",
                    }
                ),
                flush=True,
            )
        previous_history = None
        previous_reported = None
        dirty_period_classes = None
    _check_history_storage()
    staging = Path(tempfile.mkdtemp(prefix=".panels.partial-", dir=output_root))
    chunk_root = staging / ".chunks"
    chunk_root.mkdir()
    delta_chunk_root = staging / ".delta-chunks"
    delta_chunk_root.mkdir()
    spill = _QuarterSpill(chunk_root)
    try:
        by_fact = spill.mapping()
        for row in observed.records("reported_period_observation"):
            by_fact[row["source_filing_id"], row["source_fact_id"]] = {field: row.get(field) for field in _PERIOD_ATTESTATION_FIELDS}
        row = None
        del observed
        gc.collect()
        targets, additive_by_pair, materialized = {}, {}, {}
        changes = defaultdict(int)
        delta_metrics = defaultdict(int)
        prior_derived_cells = None
        prior_derived_metrics = None
        delta_mode = previous_history is not None and previous_reported is not None and dirty_period_classes is not None

        def full_delta_fallback(exc: _QuarterDeltaFallback) -> Path:
            print(
                json.dumps(
                    {"stage": "QUARTER_CELL_DELTA_FULL_FALLBACK", "reason": str(exc)}
                ),
                flush=True,
            )
            spill.close()
            shutil.rmtree(staging)
            return publish_quarter_history(
                publication=publication,
                output_root=output_root,
                reuse_roots=True,
                operational_root=operational_root,
                _recovery_access=_recovery_access,
                validation_mode=validation_mode,
                validation_state_root=validation_state_root,
            )

        if delta_mode:
            try:
                prior_reported_reader = HistoryPublicationReader(previous_reported)
                prior_final_reader = HistoryPublicationReader(previous_history)
                prior_manifest_path = prior_reported_reader.root / "history_manifest.json"
                if (
                    prior_final_reader.manifest.get("supersedes_publication")
                    != str(prior_reported_reader.root.absolute())
                    or prior_final_reader.manifest.get("source_manifest_sha256")
                    != hashlib.sha256(prior_manifest_path.read_bytes()).hexdigest()
                ):
                    raise _QuarterDeltaFallback(
                        "previous final publication is not bound to previous reported input"
                    )
                prior_derived_cells, prior_derived_metrics = _spill_reported_delta(
                    current=old,
                    previous_reported=prior_reported_reader,
                    previous_final=prior_final_reader,
                    publication=publication,
                    by_fact=by_fact,
                    targets=targets,
                    materialized=materialized,
                    changes=changes,
                    spill=spill,
                    additive=additive_by_pair,
                    chunk_root=delta_chunk_root,
                    dirty_period_classes=dirty_period_classes,
                    metrics=delta_metrics,
                )
            except _QuarterDeltaFallback as exc:
                return full_delta_fallback(exc)
        else:
            for table in old.manifest["tables"]:
                _spill_reported_table(old, table, publication, by_fact, targets, materialized, changes, spill, additive_by_pair)
        try:
            derived = _derive_quarter_targets(
                targets,
                additive_by_pair,
                materialized,
                spill,
                prior_derived_cells=prior_derived_cells,
                prior_derived_metrics=prior_derived_metrics,
                delta_metrics=delta_metrics if delta_mode else None,
            )
        except _QuarterDeltaFallback as exc:
            if not delta_mode:
                raise
            return full_delta_fallback(exc)
        if delta_mode:
            for name in (
                "compared_cells",
                "reused_cells",
                "regenerated_cells",
                "derived_reused_cells",
                "derived_recomputed_cells",
                "derived_removed_cells",
            ):
                delta_metrics[name] += 0
            print(
                json.dumps(
                    {"stage": "QUARTER_CELL_DELTA", **dict(sorted(delta_metrics.items()))}
                ),
                flush=True,
            )
        spill.checkpoint()
        built_tables: dict[tuple[str, str, str], dict[str, Any]] = {}
        for target_index, (key, target) in enumerate(sorted(targets.items())):
            if dirty_period_classes is not None and key[2] not in dirty_period_classes:
                continue
            table = (
                _assemble_delta_table(target, staging, spill)
                if delta_mode
                else _assemble_spilled_table(target, staging, spill)
            )
            built_tables[(str(key[0]), str(key[1]), str(key[2]))] = table
            print(
                json.dumps(
                    {
                        "stage": "QUARTER_PANEL",
                        "ticker": key[0],
                        "view": key[1],
                        "period_class": key[2],
                        "cells": table["files"]["cells"]["count"],
                    }
                ),
                flush=True,
            )
        shutil.rmtree(delta_chunk_root)
        _check_history_storage()
        derived_info = _finalize_staged_records(_stage_records(staging / "derived_quarter.parquet", derived))
        spill.close()
        if not _retain_history_artifacts():
            shutil.rmtree(chunk_root)
        tables: list[dict[str, Any]] = []
        previous_tables: dict[tuple[str, str, str], dict[str, Any]] = {}
        previous_reader = None
        if previous_history is not None:
            previous_reader = HistoryPublicationReader(previous_history)
            previous_tables = {
                (str(table["ticker"]), str(table["view"]), str(table["period_class"])): table
                for table in previous_reader.manifest["tables"]
            }
        target_keys = _quarter_target_keys(targets)
        for key in target_keys:
            if key in built_tables:
                tables.append(built_tables[key])
                continue
            if previous_reader is None or key not in previous_tables:
                raise ValueError("unchanged quarter table has no previous publication proof")
            prior = previous_tables[key]
            copied = {**prior, "files": {}}
            for name, info in prior["files"].items():
                _check_history_storage()
                relative = Path(info["path"])
                source = _history_dataset_path(previous_reader.root, info)
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if _sha256_file(target) != info["sha256"]:
                    raise ValueError("reused quarter table hash mismatch")
                copied["files"][name] = dict(info)
            tables.append(copied)
        manifest = {**old.manifest, "version": HISTORY_VERSION, "tables": tables, "period_rule": PERIOD_RULE,
                    "operational_roots": {key: str(path.absolute()) for key, path in roots.items()},
                    "input_fingerprint": input_fingerprint,
                    "derived_quarter": {**derived_info, "path": "derived_quarter.parquet"},
                    "quarterly_derivation_status": "APPROVED_STANDARD_ADDITIVE_CORE_CONNECTED",
                    "derivation_rule": QUARTER_RULE, "period_reclassification_counts": dict(changes),
                    "supersedes_publication": str(publication.absolute()),
                    "source_manifest_sha256": hashlib.sha256((publication / "history_manifest.json").read_bytes()).hexdigest()}
        if previous_history is not None:
            manifest["history_append_reuse"] = old.manifest.get("history_append_reuse")
        _write_json(staging / "history_manifest.json", manifest)
        del targets, derived
        gc.collect()
        verified = HistoryPublicationReader(staging, allow_staging=True, _recovery_access=_recovery_access)
        if _recovery_access is None:
            verified.validate(mode=validation_mode, state_root=validation_state_root)
        else:
            verified.verify_all()
        _check_history_storage()
        _rename_history_directory(staging, destination)
        return destination
    finally:
        spill.close()



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--validation-mode", choices=("routine", "detailed"), default="routine")
    parser.add_argument("--validation-state-root", type=Path)
    args = parser.parse_args()
    print(publish_quarter_history(
        publication=args.publication, output_root=args.output_root,
        validation_mode=args.validation_mode, validation_state_root=args.validation_state_root,
    ))


if __name__ == "__main__":
    main()
