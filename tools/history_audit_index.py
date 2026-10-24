"""Versioned, audit-owned SQLite index with lossless payload deduplication.

This module owns storage mechanics only.  It does not import History producer
code or decide accounting, selection, or comparison policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

FORMAT_VERSION = "history-audit-index-v2"
CANONICAL_ENCODING = "canonical-json-v1"
COMPRESSED_ENCODING = "zlib1-canonical-json-v1"
DEFAULT_COMPRESSION_THRESHOLD: int | None = None
EXPERIMENTAL_COMPRESSION_THRESHOLD = 32 * 1024


class AuditIndexError(RuntimeError):
    """The private audit index is absent, incompatible, or corrupt."""


@dataclass(frozen=True, slots=True)
class PayloadRef:
    """A payload reference that is valid only for its creating index."""

    index_id: str
    payload_id: str


def canonical_text(value: Any) -> str:
    """Return the pre-existing audit canonical JSON representation."""

    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditIndexError(reason)


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def decode_canonical_bytes(data: bytes) -> Any:
    """Decode canonical audit JSON with the storage format's strict number rules."""

    try:
        return json.loads(
            data,
            parse_constant=_reject_json_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuditIndexError("CORRUPT_PAYLOAD_JSON") from exc


class AuditIndex:
    """A new-format audit index; existing files must be opened explicitly."""

    def __init__(
        self,
        path: str | Path,
        *,
        compression_threshold: int | None = DEFAULT_COMPRESSION_THRESHOLD,
    ) -> None:
        self.path = Path(path)
        _require(not self.path.exists(), "AUDIT_DB_ALREADY_EXISTS")
        if compression_threshold is not None:
            _require(compression_threshold > 0, "INVALID_COMPRESSION_THRESHOLD")
        self.db = sqlite3.connect(self.path)
        self._configure()
        self.index_id = uuid.uuid4().hex
        self.compression_threshold = compression_threshold
        try:
            self._create_schema()
        except BaseException:
            self.db.close()
            raise

    @classmethod
    def open(cls, path: str | Path, *, read_only: bool = False) -> AuditIndex:
        """Open only an exact v2 index; old or altered schemas fail closed."""

        result = cls.__new__(cls)
        result.path = Path(path)
        mode = "ro" if read_only else "rw"
        try:
            result.db = sqlite3.connect(f"file:{result.path}?mode={mode}", uri=True)
            result._configure(read_only=read_only)
            result._load_and_validate_format()
        except (sqlite3.Error, AuditIndexError) as exc:
            db = getattr(result, "db", None)
            if db is not None:
                db.close()
            if isinstance(exc, AuditIndexError):
                raise
            raise AuditIndexError("AUDIT_INDEX_OPEN_FAILED") from exc
        return result

    def _configure(self, *, read_only: bool = False) -> None:
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA cache_size=-2048")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("PRAGMA mmap_size=0")
        if read_only:
            self.db.execute("PRAGMA query_only=ON")

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE storage_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE payloads(
                payload_id TEXT PRIMARY KEY,
                encoding TEXT NOT NULL,
                payload BLOB NOT NULL,
                byte_count INTEGER NOT NULL CHECK(byte_count >= 0)
            );
            CREATE TABLE objects(
                bucket TEXT NOT NULL,
                k TEXT NOT NULL,
                payload_id TEXT NOT NULL REFERENCES payloads(payload_id),
                ord INTEGER PRIMARY KEY AUTOINCREMENT,
                UNIQUE(bucket,k)
            );
            CREATE TABLE expected(
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_id TEXT NOT NULL REFERENCES payloads(payload_id)
            );
            CREATE INDEX expected_order ON expected(target,kind,ordinal);
            CREATE TABLE candidates(
                ticker TEXT NOT NULL,
                view TEXT NOT NULL,
                year INTEGER NOT NULL,
                kind TEXT NOT NULL,
                scope TEXT NOT NULL,
                cell_payload_id TEXT NOT NULL REFERENCES payloads(payload_id),
                column_payload_id TEXT NOT NULL REFERENCES payloads(payload_id),
                source_row_payload_id TEXT NOT NULL REFERENCES payloads(payload_id),
                ord INTEGER PRIMARY KEY AUTOINCREMENT
            );
            CREATE INDEX candidate_scope ON candidates(ticker,view,year,kind,scope,ord);
            CREATE TABLE boundaries(
                target TEXT NOT NULL,
                col TEXT NOT NULL,
                b TEXT NOT NULL,
                PRIMARY KEY(target,col,b)
            );
            """
        )
        values = {
            "format_version": FORMAT_VERSION,
            "index_id": self.index_id,
            "payload_encoding": "canonical-json-with-optional-zlib1-v1",
            "compression_threshold": (
                "none"
                if self.compression_threshold is None
                else str(self.compression_threshold)
            ),
        }
        self.db.executemany(
            "INSERT INTO storage_meta(key,value) VALUES(?,?)", values.items()
        )
        self.db.commit()

    def _load_and_validate_format(self) -> None:
        try:
            meta = dict(self.db.execute("SELECT key,value FROM storage_meta"))
        except sqlite3.Error as exc:
            raise AuditIndexError("AUDIT_INDEX_FORMAT_MISSING") from exc
        _require(meta.get("format_version") == FORMAT_VERSION, "AUDIT_INDEX_FORMAT")
        _require(bool(meta.get("index_id")), "AUDIT_INDEX_ID")
        encoding = meta.get("payload_encoding")
        threshold_text = meta.get("compression_threshold")
        _require(
            encoding == "canonical-json-with-optional-zlib1-v1",
            "AUDIT_INDEX_ENCODING",
        )
        if threshold_text == "none":
            threshold = None
        else:
            try:
                threshold = int(str(threshold_text))
            except (TypeError, ValueError) as exc:
                raise AuditIndexError("AUDIT_INDEX_ENCODING_CONFIG") from exc
            _require(threshold > 0, "AUDIT_INDEX_ENCODING_CONFIG")
        expected_columns = {
            "payloads": ["payload_id", "encoding", "payload", "byte_count"],
            "objects": ["bucket", "k", "payload_id", "ord"],
            "expected": ["target", "kind", "ordinal", "payload_id"],
            "candidates": [
                "ticker",
                "view",
                "year",
                "kind",
                "scope",
                "cell_payload_id",
                "column_payload_id",
                "source_row_payload_id",
                "ord",
            ],
            "boundaries": ["target", "col", "b"],
        }
        for table, columns in expected_columns.items():
            actual = [row[1] for row in self.db.execute(f"PRAGMA table_info({table})")]
            _require(actual == columns, f"AUDIT_INDEX_SCHEMA:{table}")
        self.index_id = meta["index_id"]
        self.compression_threshold = threshold

    def _store_payload(self, value: Any) -> PayloadRef:
        canonical = canonical_text(value)
        canonical_bytes = canonical.encode("utf-8")
        payload_id = "sha256:" + _digest(canonical_bytes)
        row = self.db.execute(
            "SELECT encoding,payload,byte_count FROM payloads WHERE payload_id=?",
            (payload_id,),
        ).fetchone()
        if row is not None:
            existing = self._canonical_payload_bytes(payload_id, row)
            _require(existing == canonical_bytes, "PAYLOAD_HASH_COLLISION")
            return PayloadRef(self.index_id, payload_id)
        threshold = self.compression_threshold
        if threshold is not None and len(canonical_bytes) >= threshold:
            encoding = COMPRESSED_ENCODING
            stored = zlib.compress(canonical_bytes, level=1)
        else:
            encoding = CANONICAL_ENCODING
            stored = canonical_bytes
        self.db.execute(
            "INSERT INTO payloads(payload_id,encoding,payload,byte_count) VALUES(?,?,?,?)",
            (payload_id, encoding, stored, len(canonical_bytes)),
        )
        return PayloadRef(self.index_id, payload_id)

    def _check_ref(self, ref: PayloadRef) -> None:
        _require(type(ref) is PayloadRef and ref.index_id == self.index_id, "FOREIGN_PAYLOAD_REF")
        row = self.db.execute(
            "SELECT 1 FROM payloads WHERE payload_id=?", (ref.payload_id,)
        ).fetchone()
        _require(row is not None, "DANGLING_PAYLOAD_REF")

    def _canonical_payload_bytes(
        self, payload_id: str, row: tuple[Any, Any, Any]
    ) -> bytes:
        encoding, raw, byte_count = row
        _require(type(byte_count) is int and byte_count >= 0, "CORRUPT_PAYLOAD_LENGTH")
        data = bytes(raw)
        if encoding == CANONICAL_ENCODING:
            canonical = data
        elif encoding == COMPRESSED_ENCODING:
            decompressor = zlib.decompressobj()
            try:
                canonical = decompressor.decompress(data, byte_count + 1)
            except zlib.error as exc:
                raise AuditIndexError("CORRUPT_PAYLOAD_COMPRESSION") from exc
            _require(
                len(canonical) <= byte_count
                and decompressor.eof
                and not decompressor.unused_data
                and not decompressor.unconsumed_tail,
                "CORRUPT_PAYLOAD_COMPRESSION",
            )
        else:
            raise AuditIndexError("CORRUPT_PAYLOAD_ENCODING")
        _require(len(canonical) == byte_count, "CORRUPT_PAYLOAD_LENGTH")
        _require("sha256:" + _digest(canonical) == payload_id, "CORRUPT_PAYLOAD_HASH")
        return canonical

    def _load_payload(self, payload_id: str) -> Any:
        row = self.db.execute(
            "SELECT encoding,payload,byte_count FROM payloads WHERE payload_id=?",
            (payload_id,),
        ).fetchone()
        _require(row is not None, "DANGLING_PAYLOAD_REF")
        data = self._canonical_payload_bytes(payload_id, row)
        return decode_canonical_bytes(data)

    def _verified_canonical_rows(
        self, rows: Iterator[tuple[Any, Any, Any, Any]]
    ) -> Iterator[bytes]:
        for payload_id, encoding, payload, byte_count in rows:
            _require(encoding is not None, "DANGLING_PAYLOAD_REF")
            yield self._canonical_payload_bytes(
                payload_id, (encoding, payload, byte_count)
            )

    def payload_ref(self, value: Any) -> PayloadRef:
        """Store a logical payload without adding an object/expected row."""

        return self._store_payload(value)

    def put(self, bucket: str, key: Any, value: Any, first: bool = False) -> PayloadRef:
        key_text = canonical_text(key)
        ref = self._store_payload(value)
        if first:
            self.db.execute(
                "INSERT OR IGNORE INTO objects(bucket,k,payload_id) VALUES(?,?,?)",
                (bucket, key_text, ref.payload_id),
            )
            actual = self.db.execute(
                "SELECT payload_id FROM objects WHERE bucket=? AND k=?",
                (bucket, key_text),
            ).fetchone()
            _require(actual is not None, "OBJECT_FIRST_INSERT")
            return PayloadRef(self.index_id, actual[0])
        else:
            self.db.execute(
                """INSERT INTO objects(bucket,k,payload_id) VALUES(?,?,?)
                   ON CONFLICT(bucket,k) DO UPDATE SET payload_id=excluded.payload_id""",
                (bucket, key_text, ref.payload_id),
            )
        return ref

    def get(self, bucket: str, key: Any) -> Any:
        row = self.db.execute(
            "SELECT payload_id FROM objects WHERE bucket=? AND k=?",
            (bucket, canonical_text(key)),
        ).fetchone()
        return self._load_payload(row[0]) if row else None

    def items(self, bucket: str) -> Iterator[tuple[Any, Any]]:
        rows = self.db.execute(
            "SELECT k,payload_id FROM objects WHERE bucket=? ORDER BY ord", (bucket,)
        )
        for key, payload_id in rows:
            yield json.loads(key), self._load_payload(payload_id)

    def item_canonical_values(self, bucket: str) -> Iterator[bytes]:
        """Yield verified object payload bytes in first-insertion order."""

        rows = self.db.execute(
            """SELECT o.payload_id,p.encoding,p.payload,p.byte_count
               FROM objects o LEFT JOIN payloads p ON p.payload_id=o.payload_id
               WHERE o.bucket=? ORDER BY o.ord""",
            (bucket,),
        )
        yield from self._verified_canonical_rows(rows)

    def emit(self, target: str, kind: str, value: Any) -> PayloadRef:
        ref = self._store_payload(value)
        self.db.execute(
            "INSERT INTO expected(target,kind,payload_id) VALUES(?,?,?)",
            (target, kind, ref.payload_id),
        )
        if kind == "cells" and isinstance(value.get("value_lineage"), dict):
            lineage = value["value_lineage"]
            boundary = [
                lineage.get(name)
                for name in (
                    "context_start_date",
                    "context_end_date",
                    "context_instant_date",
                )
            ]
            self.db.execute(
                "INSERT OR IGNORE INTO boundaries VALUES(?,?,?)",
                (
                    target,
                    value["fiscal_time_series_column_id"],
                    canonical_text(boundary),
                ),
            )
        return ref

    def expected(self, target: str, kind: str) -> Iterator[Any]:
        rows = self.db.execute(
            "SELECT payload_id FROM expected WHERE target=? AND kind=? ORDER BY ordinal",
            (target, kind),
        )
        for (payload_id,) in rows:
            yield self._load_payload(payload_id)

    def expected_canonical(self, target: str, kind: str) -> Iterator[bytes]:
        """Yield verified expected payload bytes without JSON decode/re-encode."""

        rows = self.db.execute(
            """SELECT e.payload_id,p.encoding,p.payload,p.byte_count
               FROM expected e LEFT JOIN payloads p ON p.payload_id=e.payload_id
               WHERE e.target=? AND e.kind=? ORDER BY e.ordinal""",
            (target, kind),
        )
        yield from self._verified_canonical_rows(rows)

    def add_candidate_refs(
        self,
        ticker: str,
        view: str,
        year: int,
        kind: str,
        scope: str,
        *,
        cell: PayloadRef,
        column: PayloadRef,
        source_row: PayloadRef,
    ) -> None:
        for ref in (cell, column, source_row):
            self._check_ref(ref)
        self.db.execute(
            """INSERT INTO candidates(
                   ticker,view,year,kind,scope,
                   cell_payload_id,column_payload_id,source_row_payload_id
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                ticker,
                view,
                year,
                kind,
                scope,
                cell.payload_id,
                column.payload_id,
                source_row.payload_id,
            ),
        )

    def add_candidate(
        self,
        ticker: str,
        view: str,
        year: int,
        kind: str,
        scope: str,
        candidate: dict[str, Any],
    ) -> None:
        _require(
            set(candidate) == {"cell", "column", "source_row"},
            "CANDIDATE_SHAPE",
        )
        self.add_candidate_refs(
            ticker,
            view,
            year,
            kind,
            scope,
            cell=self._store_payload(candidate["cell"]),
            column=self._store_payload(candidate["column"]),
            source_row=self._store_payload(candidate["source_row"]),
        )

    def candidates(
        self, ticker: str, view: str, year: int, kind: str, scope: str
    ) -> Iterator[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT cell_payload_id,column_payload_id,source_row_payload_id
               FROM candidates
               WHERE ticker=? AND view=? AND year=? AND kind=? AND scope=?
               ORDER BY ord""",
            (ticker, view, year, kind, scope),
        )
        for cell, column, source_row in rows:
            yield {
                "cell": self._load_payload(cell),
                "column": self._load_payload(column),
                "source_row": self._load_payload(source_row),
            }

    def single(self, bucket: str) -> Any:
        rows = list(self.db.execute("SELECT payload_id FROM objects WHERE bucket=?", (bucket,)))
        _require(len(rows) == 1, "OBJECT_BUCKET_CARDINALITY")
        return self._load_payload(rows[0][0])

    def verify_storage(self) -> dict[str, int]:
        """Fully verify payload/reference integrity before a final audit seal."""

        result = self.db.execute("PRAGMA integrity_check").fetchone()
        _require(result == ("ok",), "SQLITE_INTEGRITY")
        dangling_queries = (
            "SELECT count(*) FROM objects o LEFT JOIN payloads p ON p.payload_id=o.payload_id WHERE p.payload_id IS NULL",
            "SELECT count(*) FROM expected e LEFT JOIN payloads p ON p.payload_id=e.payload_id WHERE p.payload_id IS NULL",
            "SELECT count(*) FROM candidates c LEFT JOIN payloads p ON p.payload_id=c.cell_payload_id WHERE p.payload_id IS NULL",
            "SELECT count(*) FROM candidates c LEFT JOIN payloads p ON p.payload_id=c.column_payload_id WHERE p.payload_id IS NULL",
            "SELECT count(*) FROM candidates c LEFT JOIN payloads p ON p.payload_id=c.source_row_payload_id WHERE p.payload_id IS NULL",
        )
        _require(all(self.db.execute(sql).fetchone()[0] == 0 for sql in dangling_queries), "DANGLING_PAYLOAD_REF")
        payload_count = 0
        for (payload_id,) in self.db.execute("SELECT payload_id FROM payloads ORDER BY payload_id"):
            self._load_payload(payload_id)
            payload_count += 1
        return {"payloads": payload_count}

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        self.db.close()
