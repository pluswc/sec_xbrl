"""Paired, source-only benchmark for the private History audit index.

The default cases are deterministic synthetic records.  ``--fixture`` accepts
an explicitly authorized JSONL capture; this script never discovers inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

try:
    from .history_audit_index import (
        EXPERIMENTAL_COMPRESSION_THRESHOLD,
        AuditIndex,
        canonical_text,
    )
except ImportError:  # Direct ``python tools/profile_history_audit_index.py`` execution.
    from history_audit_index import (
        EXPERIMENTAL_COMPRESSION_THRESHOLD,
        AuditIndex,
        canonical_text,
    )


def _update_hash(digest: Any, value: Any) -> None:
    data = canonical_text(value).encode("utf-8")
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


class LegacyIndex:
    """Exact storage shape used by the frozen audit runtime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA cache_size=-2048")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.execute("PRAGMA mmap_size=0")
        self.db.executescript(
            """
            CREATE TABLE objects(bucket TEXT,k TEXT,payload TEXT,ord INTEGER PRIMARY KEY AUTOINCREMENT,UNIQUE(bucket,k));
            CREATE TABLE expected(target TEXT,kind TEXT,ordinal INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT);
            CREATE INDEX expected_order ON expected(target,kind,ordinal);
            CREATE TABLE candidates(ticker TEXT,view TEXT,year INTEGER,kind TEXT,scope TEXT,payload TEXT,ord INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE INDEX candidate_scope ON candidates(ticker,view,year,kind,scope,ord);
            CREATE TABLE boundaries(target TEXT,col TEXT,b TEXT,PRIMARY KEY(target,col,b));
            """
        )

    def put(self, bucket: str, key: Any, value: Any, first: bool = False) -> None:
        sql = "INSERT OR IGNORE" if first else "INSERT"
        sql += " INTO objects(bucket,k,payload) VALUES(?,?,?)"
        if not first:
            sql += " ON CONFLICT(bucket,k) DO UPDATE SET payload=excluded.payload"
        self.db.execute(sql, (bucket, canonical_text(key), canonical_text(value)))

    def emit(self, target: str, kind: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO expected(target,kind,payload) VALUES(?,?,?)",
            (target, kind, canonical_text(value)),
        )

    def add_candidate(self, metadata: tuple[Any, ...], value: Any) -> None:
        self.db.execute(
            "INSERT INTO candidates(ticker,view,year,kind,scope,payload) VALUES(?,?,?,?,?,?)",
            (*metadata, canonical_text(value)),
        )


def _synthetic(case: str) -> tuple[int, Iterable[dict[str, Any]]]:
    if case == "small-financial":
        count, width = 2_000, 180
    elif case in {"long-repeated", "long-unique-within-record"}:
        count, width = 512, 65_536
    else:
        raise ValueError(case)

    def records() -> Iterable[dict[str, Any]]:
        repeated = "분기 공시 repeated audit text | " + "R" * width
        for number in range(count):
            if case == "long-repeated":
                value_text = repeated
            elif case == "long-unique-within-record":
                prefix = f"record-{number:08d}|"
                value_text = prefix + (chr(65 + number % 26) * width)
            else:
                value_text = f"record-{number}|" + "s" * width
            column = {
                "fiscal_time_series_column_id": f"column-{number}",
                "fiscal_year": 2020 + number % 6,
                "fiscal_quarter": 1 + number % 4,
            }
            source_row = {
                "fiscal_time_series_row_id": f"row-{number}",
                "label": "Revenue",
            }
            cell = {
                "fiscal_time_series_cell_id": f"cell-{number}",
                "fiscal_time_series_column_id": column["fiscal_time_series_column_id"],
                "fiscal_time_series_row_id": source_row["fiscal_time_series_row_id"],
                "value_numeric": str(10**30 + number) + ".000000000000000001",
                "value_text": value_text,
                "value_lineage": {
                    "value_text": value_text,
                    "value_numeric": str(10**30 + number) + ".000000000000000001",
                    "reported_or_derived": "REPORTED",
                },
            }
            yield {
                "cell": cell,
                "column": column,
                "source_row": source_row,
                "eligible": number % 4 != 0,
                "ticker": "SYN",
                "view": "AS_FILED",
                "year": column["fiscal_year"],
                "kind": "FY",
                "scope": f"scope-{number % 8}",
                "table_index": number % 12,
            }

    return count, records()


def _fixture(path: Path, cycles: int) -> tuple[int, Iterable[dict[str, Any]]]:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("FIXTURE_EXCEEDS_16_MIB")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    required = {
        "cell",
        "column",
        "source_row",
        "eligible",
        "ticker",
        "view",
        "year",
        "kind",
        "scope",
        "table_index",
    }
    if not rows or any(set(row) != required for row in rows):
        raise RuntimeError("FIXTURE_SHAPE")

    def repeated() -> Iterable[dict[str, Any]]:
        for _ in range(cycles):
            yield from rows

    return len(rows) * cycles, repeated()


def _db_size(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal"))
        if item.exists()
    )


def _legacy_semantics(index: LegacyIndex) -> tuple[str, dict[str, int]]:
    digest = hashlib.sha256()
    counts = {"objects": 0, "expected": 0, "candidates": 0}
    for bucket, key, payload in index.db.execute(
        "SELECT bucket,k,payload FROM objects ORDER BY ord"
    ):
        _update_hash(digest, ["object", bucket, json.loads(key), json.loads(payload)])
        counts["objects"] += 1
    for target, kind, payload in index.db.execute(
        "SELECT target,kind,payload FROM expected ORDER BY ordinal"
    ):
        _update_hash(digest, ["expected", target, kind, json.loads(payload)])
        counts["expected"] += 1
    for ticker, view, year, kind, scope, payload in index.db.execute(
        "SELECT ticker,view,year,kind,scope,payload FROM candidates ORDER BY ord"
    ):
        _update_hash(
            digest,
            ["candidate", ticker, view, year, kind, scope, json.loads(payload)],
        )
        counts["candidates"] += 1
    return digest.hexdigest(), counts


def _candidate_semantics(index: AuditIndex) -> tuple[str, dict[str, int]]:
    digest = hashlib.sha256()
    counts = {"objects": 0, "expected": 0, "candidates": 0}
    for bucket, key in index.db.execute("SELECT bucket,k FROM objects ORDER BY ord"):
        _update_hash(digest, ["object", bucket, json.loads(key), index.get(bucket, json.loads(key))])
        counts["objects"] += 1
    for target, kind, payload_id in index.db.execute(
        "SELECT target,kind,payload_id FROM expected ORDER BY ordinal"
    ):
        _update_hash(digest, ["expected", target, kind, index._load_payload(payload_id)])
        counts["expected"] += 1
    for ticker, view, year, kind, scope, cell, column, source_row in index.db.execute(
        """SELECT ticker,view,year,kind,scope,
                  cell_payload_id,column_payload_id,source_row_payload_id
           FROM candidates ORDER BY ord"""
    ):
        value = {
            "cell": index._load_payload(cell),
            "column": index._load_payload(column),
            "source_row": index._load_payload(source_row),
        }
        _update_hash(digest, ["candidate", ticker, view, year, kind, scope, value])
        counts["candidates"] += 1
    return digest.hexdigest(), counts


def _worker(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.db)
    original_count, records = (
        _fixture(Path(args.fixture), args.fixture_cycles)
        if args.fixture
        else _synthetic(args.case)
    )
    threshold = None if args.arm == "refs" else EXPERIMENTAL_COMPRESSION_THRESHOLD
    started = time.perf_counter()
    if args.arm == "baseline":
        index: Any = LegacyIndex(path)
    else:
        index = AuditIndex(path, compression_threshold=threshold)
    create_seconds = time.perf_counter() - started
    logical_bytes = 0
    insert_started = time.perf_counter()
    for number, record in enumerate(records):
        cell = record["cell"]
        column = record["column"]
        source_row = record["source_row"]
        logical_bytes += sum(
            len(canonical_text(value).encode("utf-8"))
            for value in (cell, column, source_row)
        )
        target = f"target:{record['table_index']}"
        if args.arm == "baseline":
            index.put(target + "columns", column["fiscal_time_series_column_id"], column)
            index.put(target + "rows", source_row["fiscal_time_series_row_id"], source_row)
            index.emit(target, "cells", cell)
            if record["eligible"]:
                candidate = {"cell": cell, "column": column, "source_row": source_row}
                index.add_candidate(
                    (
                        record["ticker"],
                        record["view"],
                        record["year"],
                        record["kind"],
                        record["scope"],
                    ),
                    candidate,
                )
                logical_bytes += len(canonical_text(candidate).encode("utf-8"))
        else:
            column_ref = index.put(
                target + "columns", column["fiscal_time_series_column_id"], column
            )
            row_ref = index.put(
                target + "rows", source_row["fiscal_time_series_row_id"], source_row
            )
            cell_ref = index.emit(target, "cells", cell)
            if record["eligible"]:
                index.add_candidate_refs(
                    record["ticker"],
                    record["view"],
                    record["year"],
                    record["kind"],
                    record["scope"],
                    cell=cell_ref,
                    column=column_ref,
                    source_row=row_ref,
                )
                logical_bytes += len(
                    canonical_text(
                        {"cell": cell, "column": column, "source_row": source_row}
                    ).encode("utf-8")
                )
        if number and number % 128 == 0:
            index.db.commit()
    index.db.commit()
    insert_seconds = time.perf_counter() - insert_started
    read_started = time.perf_counter()
    semantic_sha, counts = (
        _legacy_semantics(index)
        if args.arm == "baseline"
        else _candidate_semantics(index)
    )
    read_seconds = time.perf_counter() - read_started
    verify_started = time.perf_counter()
    storage_counts = None if args.arm == "baseline" else index.verify_storage()
    verify_seconds = time.perf_counter() - verify_started
    index.close() if args.arm != "baseline" else index.db.close()
    return {
        "arm": args.arm,
        "case": args.case,
        "fixture": args.fixture,
        "fixture_cycles": args.fixture_cycles,
        "exercise_records": original_count,
        "logical_bytes": logical_bytes,
        "semantic_sha256": semantic_sha,
        "counts": counts,
        "storage_counts": storage_counts,
        "create_seconds": create_seconds,
        "insert_seconds": insert_seconds,
        "read_seconds": read_seconds,
        "verify_seconds": verify_seconds,
        "total_seconds": create_seconds + insert_seconds + read_seconds + verify_seconds,
        "db_and_sidecars_bytes": _db_size(path),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def _run_parent(args: argparse.Namespace) -> dict[str, Any]:
    cases = [args.case] if args.case else [
        "small-financial",
        "long-repeated",
        "long-unique-within-record",
    ]
    if args.fixture:
        cases = ["authorized-fixture"]
    results = []
    arms = ["baseline", "refs", "compact"]
    with tempfile.TemporaryDirectory(prefix="history-audit-index-profile-") as temporary:
        root = Path(temporary)
        for rotation in range(args.rotations):
            ordered = arms if rotation % 2 == 0 else list(reversed(arms))
            for case in cases:
                for arm in ordered:
                    db = root / f"{rotation}-{case}-{arm}.sqlite"
                    command = [
                        sys.executable,
                        "-B",
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--arm",
                        arm,
                        "--case",
                        case,
                        "--db",
                        str(db),
                        "--fixture-cycles",
                        str(args.fixture_cycles),
                    ]
                    if args.fixture:
                        command.extend(["--fixture", args.fixture])
                    environment = os.environ.copy()
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    environment["POLARS_MAX_THREADS"] = "2"
                    completed = subprocess.run(
                        command,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=environment,
                    )
                    result = json.loads(completed.stdout)
                    result["rotation"] = rotation
                    results.append(result)
        for rotation in range(args.rotations):
            for case in cases:
                group = [
                    row
                    for row in results
                    if row["rotation"] == rotation and row["case"] == case
                ]
                if len({(row["semantic_sha256"], canonical_text(row["counts"])) for row in group}) != 1:
                    raise RuntimeError(f"SEMANTIC_MISMATCH:{rotation}:{case}")
    return {
        "schema_version": "history-audit-index-profile-v1",
        "rotations": args.rotations,
        "original_fixture_records": (
            sum(1 for line in Path(args.fixture).read_text(encoding="utf-8").splitlines() if line)
            if args.fixture
            else None
        ),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--arm", choices=["baseline", "refs", "compact"])
    parser.add_argument("--case", choices=["small-financial", "long-repeated", "long-unique-within-record", "authorized-fixture"])
    parser.add_argument("--db")
    parser.add_argument("--rotations", type=int, default=2)
    parser.add_argument("--fixture")
    parser.add_argument("--fixture-cycles", type=int, default=1)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.worker:
        if not args.arm or not args.case or not args.db:
            parser.error("--worker requires --arm, --case and --db")
        print(json.dumps(_worker(args), sort_keys=True))
        return
    if not 1 <= args.rotations <= 3:
        parser.error("--rotations must be between 1 and 3")
    if args.fixture_cycles < 1:
        parser.error("--fixture-cycles must be positive")
    result = _run_parent(args)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
