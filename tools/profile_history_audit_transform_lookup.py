"""Profile verified-canonical consumer comparison on bounded audit fixtures."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from itertools import zip_longest
from pathlib import Path
from typing import Any

from tools.history_audit_index import (
    EXPERIMENTAL_COMPRESSION_THRESHOLD,
    AuditIndex,
    canonical_text,
    decode_canonical_bytes,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _transactions(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _cow_cell(original: dict[str, Any]) -> dict[str, Any]:
    cell = dict(original)
    lineage = cell.get("value_lineage")
    if isinstance(lineage, dict):
        lineage = dict(lineage)
        cell["value_lineage"] = lineage
        lineage["period_class"] = lineage.get("period_class")
    return cell


def _equal_record(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    expected = {**{key: None for key in actual}, **expected}
    if canonical_text(expected) != canonical_text(actual):
        raise AssertionError("FULL_RECORD_OR_ORDER_MISMATCH")


def _sidecar_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
        if candidate.exists()
    )


def _actual_cells(
    transactions: list[dict[str, Any]], cycles: int, case: str
) -> Iterator[dict[str, Any]]:
    for _ in range(cycles):
        for transaction in transactions:
            cell = _cow_cell(transaction["cell"])
            if case == "null-padding":
                cell["__schema_padding__"] = None
            yield cell


def run_worker(
    fixture: Path, cycles: int, mode: str, case: str, output: Path
) -> dict[str, Any]:
    transactions = _transactions(fixture)
    input_sha = hashlib.sha256(
        canonical_text(transactions).encode("utf-8")
    ).hexdigest()
    counts = {
        "object_payload_selects": 0,
        "expected_json_decodes": 0,
        "expected_canonical_encodes": 0,
        "actual_canonical_encodes": 0,
    }
    queries: list[str] = []
    phases: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="audit-transform-lookup-") as directory:
        database = Path(directory) / "index.sqlite"
        started = time.perf_counter()
        index = AuditIndex(
            database, compression_threshold=EXPERIMENTAL_COMPRESSION_THRESHOLD
        )
        index.db.set_trace_callback(queries.append)
        metadata_started = time.perf_counter()
        for transaction in transactions:
            cell = transaction["cell"]
            lineage = cell.get("value_lineage") or {}
            index.put(
                "source:columns",
                cell["fiscal_time_series_column_id"],
                transaction["column"],
            )
            index.put(
                "source:rows",
                cell["fiscal_time_series_row_id"],
                transaction["source_row"],
            )
            index.put(
                "t1",
                [lineage.get("source_filing_id"), lineage.get("selected_source_fact_id")],
                lineage,
            )
        phases["metadata_write"] = time.perf_counter() - metadata_started

        source_started = time.perf_counter()
        for cycle in range(cycles):
            for transaction in transactions:
                original = transaction["cell"]
                lineage = original.get("value_lineage") or {}
                column = index.get(
                    "source:columns", original["fiscal_time_series_column_id"]
                )
                row = index.get("source:rows", original["fiscal_time_series_row_id"])
                t1 = index.get(
                    "t1",
                    [
                        lineage.get("source_filing_id"),
                        lineage.get("selected_source_fact_id"),
                    ],
                )
                if column is None or row is None or t1 is None:
                    raise AssertionError("SOURCE_REFERENCE")
                cell = copy.deepcopy(original) if mode == "r14" else _cow_cell(original)
                target = f"target:{transaction['table_index']}"
                index.put(target + ":columns", column["fiscal_time_series_column_id"], column)
                index.put(target + ":rows", row["fiscal_time_series_row_id"], row)
                index.emit("all", "cells", cell)
                index.put("cycle", [cycle, cell["fiscal_time_series_cell_id"]], True)
        phases["source_transform_write"] = time.perf_counter() - source_started

        consumer_started = time.perf_counter()
        fingerprint = hashlib.sha256()
        sentinel = object()
        expected: Iterator[Any]
        if mode in {"r14", "r15"}:
            expected = index.expected("all", "cells")
        elif mode == "r17":
            expected = index.expected_canonical("all", "cells")
        else:
            raise ValueError(f"unknown mode: {mode}")
        records = 0
        for stored, actual in zip_longest(
            expected, _actual_cells(transactions, cycles, case), fillvalue=sentinel
        ):
            if stored is sentinel or actual is sentinel:
                raise AssertionError("MULTIPLICITY_OR_MISSING_RECORD")
            actual_text = canonical_text(actual)
            actual_bytes = actual_text.encode("utf-8")
            counts["actual_canonical_encodes"] += 1
            if mode in {"r14", "r15"}:
                counts["expected_json_decodes"] += 1
                counts["expected_canonical_encodes"] += 1
                expected_value = {**{key: None for key in actual}, **stored}
                if canonical_text(expected_value) != actual_text:
                    raise AssertionError("FULL_RECORD_OR_ORDER_MISMATCH")
            elif stored != actual_bytes:
                counts["expected_json_decodes"] += 1
                expected_value = decode_canonical_bytes(stored)
                expected_value = {**{key: None for key in actual}, **expected_value}
                counts["expected_canonical_encodes"] += 1
                if canonical_text(expected_value) != actual_text:
                    raise AssertionError("FULL_RECORD_OR_ORDER_MISMATCH")
            fingerprint.update(len(actual_bytes).to_bytes(8, "big"))
            fingerprint.update(actual_bytes)
            records += 1
        phases["consumer_compare"] = time.perf_counter() - consumer_started

        verify_started = time.perf_counter()
        storage = index.verify_storage()
        phases["storage_verify"] = time.perf_counter() - verify_started
        index.db.commit()
        database_bytes = _sidecar_bytes(database)
        counts["object_payload_selects"] = sum(
            statement.startswith("SELECT") for statement in queries
        )
        index.close()
        phases["total"] = time.perf_counter() - started
    final_input_sha = hashlib.sha256(
        canonical_text(transactions).encode("utf-8")
    ).hexdigest()
    if final_input_sha != input_sha:
        raise AssertionError("SOURCE_INPUT_MUTATED")
    report = {
        "schema_version": "audit-transform-lookup-worker-v1",
        "mode": mode,
        "case": case,
        "fixture": {
            "path": str(fixture),
            "sha256": _sha256(fixture),
            "original_records": len(transactions),
            "cycles": cycles,
            "exercise_records": records,
        },
        "phases_seconds": phases,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "counts": counts,
        "database_and_sidecar_bytes": database_bytes,
        "storage": storage,
        "ordered_semantic_sha256": fingerprint.hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _run_process(
    script: Path,
    fixture: Path,
    cycles: int,
    mode: str,
    case: str,
    output: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(script),
        "worker",
        "--fixture",
        str(fixture),
        "--cycles",
        str(cycles),
        "--mode",
        mode,
        "--case",
        case,
        "--output",
        str(output),
    ]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(command, env=environment)
    deadline = time.monotonic() + 30
    watchdog_peak_rss_kib = 0
    while process.poll() is None:
        try:
            for line in Path(f"/proc/{process.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    watchdog_peak_rss_kib = max(
                        watchdog_peak_rss_kib, int(line.split()[1])
                    )
                    break
        except FileNotFoundError:
            pass
        if watchdog_peak_rss_kib > 1024 * 1024:
            process.kill()
            process.wait()
            raise RuntimeError(f"{mode} exceeded 1 GiB RSS")
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            raise TimeoutError(f"{mode} exceeded 30 seconds")
        time.sleep(0.005)
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    result = json.loads(output.read_text())
    result["watchdog_peak_rss_kib"] = watchdog_peak_rss_kib
    return result


def compare(
    fixture: Path, cycles: int, rotations: int, case: str, output: Path
) -> dict[str, Any]:
    script = Path(__file__).resolve()
    modes = ("r14", "r15", "r17")
    runs: dict[str, list[dict[str, Any]]] = {mode: [] for mode in modes}
    run_root = output.parent / ("." + output.stem + "-runs")
    run_root.mkdir(parents=True, exist_ok=True)
    for rotation in range(rotations):
        shift = rotation % len(modes)
        order = modes[shift:] + modes[:shift]
        for mode in order:
            result = _run_process(
                script,
                fixture,
                cycles,
                mode,
                case,
                run_root / f"{rotation:02d}-{mode}.json",
            )
            result["rotation"] = rotation
            runs[mode].append(result)
    fingerprints = {
        result["ordered_semantic_sha256"]
        for arm in runs.values()
        for result in arm
    }
    if len(fingerprints) != 1:
        raise AssertionError("SEMANTIC_FINGERPRINT_MISMATCH")

    def summary(mode: str) -> dict[str, Any]:
        elapsed = [run["phases_seconds"]["total"] for run in runs[mode]]
        consumer = [run["phases_seconds"]["consumer_compare"] for run in runs[mode]]
        rss = [run["peak_rss_kib"] for run in runs[mode]]
        return {
            "total_seconds": elapsed,
            "median_total_seconds": statistics.median(elapsed),
            "consumer_seconds": consumer,
            "median_consumer_seconds": statistics.median(consumer),
            "peak_rss_kib": rss,
            "median_peak_rss_kib": statistics.median(rss),
            "counts": runs[mode][0]["counts"],
            "database_and_sidecar_bytes": runs[mode][0]["database_and_sidecar_bytes"],
        }

    report = {
        "schema_version": "audit-transform-lookup-paired-v1",
        "fixture": {
            "path": str(fixture),
            "sha256": _sha256(fixture),
            "cycles": cycles,
            "case": case,
        },
        "rotations": rotations,
        "limits": {"seconds_per_process": 30, "peak_rss_kib": 1024 * 1024},
        "r14": summary("r14"),
        "r15": summary("r15"),
        "r17": summary("r17"),
        "ordered_semantic_sha256": next(iter(fingerprints)),
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--fixture", type=Path, required=True)
    worker.add_argument("--cycles", type=int, required=True)
    worker.add_argument("--mode", choices=("r14", "r15", "r17"), required=True)
    worker.add_argument("--case", choices=("exact", "null-padding"), required=True)
    worker.add_argument("--output", type=Path, required=True)
    paired = commands.add_parser("compare")
    paired.add_argument("--fixture", type=Path, required=True)
    paired.add_argument("--cycles", type=int, required=True)
    paired.add_argument("--rotations", type=int, default=3)
    paired.add_argument("--case", choices=("exact", "null-padding"), required=True)
    paired.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        result = run_worker(args.fixture, args.cycles, args.mode, args.case, args.output)
    else:
        result = compare(
            args.fixture, args.cycles, args.rotations, args.case, args.output
        )
    print(json.dumps({"output": str(args.output), "schema": result["schema_version"]}))


if __name__ == "__main__":
    main()
