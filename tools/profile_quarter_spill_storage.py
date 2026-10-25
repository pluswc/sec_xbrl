"""Paired subprocess profile for private quarter spill DB storage.

Only explicitly named JSONL fixtures or deterministic synthetic records are
used.  Named journal bytes remain part of every size comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Any

BASELINE = Path("/home/plusbdw/.codex/worktrees/history-guard-performance/sec_xbrl")
CANDIDATE = Path("/home/plusbdw/.codex/worktrees/audit-payload-storage/sec_xbrl")
MAX_FIXTURE_BYTES = 16 * 1024 * 1024
MAX_RSS_KIB = 1024 * 1024


def _hash_value(digest: Any, quarters: Any, value: Any) -> None:
    payload = quarters._spill_pack(value)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _fixture(path: Path, cycles: int):
    if path.stat().st_size > MAX_FIXTURE_BYTES:
        raise RuntimeError("FIXTURE_EXCEEDS_16_MIB")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
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
    return len(rows), [row for _ in range(cycles) for row in rows]


def _synthetic(case: str):
    if case == "small-typed-financial":
        count = 4_096
        rows = []
        for index in range(count):
            cell = {
                "id": f"cell-{index}",
                "amount": Decimal(f"{10**20 + index}.000100"),
                "day": date(2026, 10, 24),
                "timestamp": datetime(2026, 10, 24, 1, 2, 3, index % 1000, tzinfo=UTC),
                "time": datetime_time(12, 34, 56),
                "delta": timedelta(days=index % 7, microseconds=index),
                "typed": (True, None, b"financial", [index, -0.0]),
                "lineage": {"fact": f"fact-{index}", "accession": "0" * 20},
                "note": "small-typed-uncompressed" * 300,
            }
            rows.append(
                {
                    "cell": cell,
                    "column": {"id": f"column-{index % 64}", "year": 2025},
                    "source_row": {"id": f"row-{index % 256}", "label": "Revenue"},
                }
            )
    elif case == "repeated-rich":
        count = 512
        evidence = [
            {
                "path": [number, "presentation", "node"],
                "label": "Revenue",
                "text": f"evidence-{number:03d}-" + chr(65 + number % 26) * 900,
            }
            for number in range(96)
        ]
        rows = [
            {
                "cell": {
                    "id": f"cell-{index}",
                    "candidate_lineage": evidence,
                    "value_lineage": {"amount": str(index), "evidence": evidence},
                },
                "column": {"id": f"column-{index}", "year": 2025},
                "source_row": {"id": f"row-{index}", "definition": evidence[:4]},
            }
            for index in range(count)
        ]
    else:
        raise ValueError(case)
    return count, rows


def _read_journal(path: Path, quarters: Any) -> tuple[int, str, str]:
    typed = hashlib.sha256()
    raw = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        while header := source.read(40):
            if len(header) != 40:
                raise RuntimeError("TRUNCATED_JOURNAL_HEADER")
            size = int.from_bytes(header[:8], "big")
            payload = source.read(size)
            if len(payload) != size or hashlib.sha256(payload).digest() != header[8:]:
                raise RuntimeError("TRUNCATED_OR_CORRUPT_JOURNAL_PAYLOAD")
            event = quarters._spill_unpack(payload)
            _hash_value(typed, quarters, event)
            raw.update(header)
            raw.update(payload)
            count += 1
    return count, typed.hexdigest(), raw.hexdigest()


def _worker(args: argparse.Namespace) -> dict[str, Any]:
    sys.path.insert(0, str(Path(args.checkout) / "src"))
    from sec_xbrl.analytics import history_quarters as quarters

    if args.fixture:
        original_count, rows = _fixture(Path(args.fixture), args.cycles)
    else:
        original_count, rows = _synthetic(args.case)
    logical = sum(
        len(quarters._spill_pack((index, row["column"])))
        + len(quarters._spill_pack((index, row["source_row"])))
        + len(quarters._spill_pack((index, row["cell"])))
        for index, row in enumerate(rows)
    )
    root = Path(args.directory)
    root.mkdir()
    started = time.perf_counter()
    spill = quarters._QuarterSpill(root)
    create_seconds = time.perf_counter() - started
    columns = spill.mapping()
    source_rows = spill.mapping()
    cells = spill.sequence()
    write_started = time.perf_counter()
    for index, row in enumerate(rows):
        columns[index] = row["column"]
        source_rows[index] = row["source_row"]
        cells.append(row["cell"])
    write_seconds = time.perf_counter() - write_started
    checkpoint_started = time.perf_counter()
    spill.checkpoint()
    checkpoint_seconds = time.perf_counter() - checkpoint_started
    read_started = time.perf_counter()
    digest = hashlib.sha256()
    for _ in range(args.read_passes):
        for key, value in columns.items():
            _hash_value(digest, quarters, ("column", key, value))
        for key, value in source_rows.items():
            _hash_value(digest, quarters, ("row", key, value))
        for value in cells:
            _hash_value(digest, quarters, ("cell", value))
        if cells:
            _hash_value(digest, quarters, ("negative", cells[-1]))
            _hash_value(digest, quarters, ("slice", cells[: min(3, len(cells))]))
    read_seconds = time.perf_counter() - read_started
    page_count = spill.db.execute("PRAGMA page_count").fetchone()[0]
    page_size = spill.db.execute("PRAGMA page_size").fetchone()[0]
    db_bytes = page_count * page_size
    journal_bytes = spill.path.stat().st_size
    journal_count, journal_typed_sha, journal_raw_sha = _read_journal(
        spill.path, quarters
    )
    result = {
        "arm": args.arm,
        "case": args.case,
        "fixture": args.fixture,
        "fixture_original_records": original_count if args.fixture else None,
        "cycles": args.cycles,
        "exercise_records": len(rows),
        "logical_typed_bytes": logical,
        "read_passes": args.read_passes,
        "semantic_sha256": digest.hexdigest(),
        "journal_event_count": journal_count,
        "journal_typed_sha256": journal_typed_sha,
        "journal_raw_sha256": journal_raw_sha,
        "create_seconds": create_seconds,
        "write_seconds": write_seconds,
        "checkpoint_seconds": checkpoint_seconds,
        "read_seconds": read_seconds,
        "total_seconds": (
            create_seconds + write_seconds + checkpoint_seconds + read_seconds
        ),
        "anonymous_db_page_count": page_count,
        "anonymous_db_page_size": page_size,
        "anonymous_db_bytes": db_bytes,
        "named_journal_bytes": journal_bytes,
        "combined_storage_bytes": db_bytes + journal_bytes,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    spill.close()
    return result


def _rss_kib(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    return None


def _run_one(command: list[str], environment: dict[str, str]) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    observed_peak = 0
    deadline = time.monotonic() + 30
    while process.poll() is None:
        rss = _rss_kib(process.pid)
        if rss is not None:
            observed_peak = max(observed_peak, rss)
            if rss > MAX_RSS_KIB:
                process.kill()
                raise RuntimeError("RSS_WATCHDOG_EXCEEDED")
        if time.monotonic() > deadline:
            process.kill()
            raise RuntimeError("WORKER_TIMEOUT")
        time.sleep(0.01)
    stdout, stderr = process.communicate()
    if process.returncode:
        raise RuntimeError(f"WORKER_FAILED:{process.returncode}:{stderr[-2000:]}")
    result = json.loads(stdout)
    result["watchdog_peak_rss_kib"] = observed_peak
    return result


def _parent(args: argparse.Namespace) -> dict[str, Any]:
    if args.fixture:
        cases = [("authorized-fixture", args.fixture, args.cycles)]
    elif args.case:
        cases = [(args.case, None, 1)]
    else:
        cases = [
            ("small-typed-financial", None, 1),
            ("repeated-rich", None, 1),
        ]
    arms = [("baseline", BASELINE), ("candidate", CANDIDATE)]
    results = []
    with tempfile.TemporaryDirectory(prefix="quarter-spill-profile-") as temporary:
        root = Path(temporary)
        for rotation in range(args.rotations):
            ordered = arms if rotation % 2 == 0 else list(reversed(arms))
            for case, fixture, cycles in cases:
                pair = []
                for arm, checkout in ordered:
                    directory = root / f"{rotation}-{case}-{arm}"
                    command = [
                        sys.executable,
                        "-B",
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--arm",
                        arm,
                        "--checkout",
                        str(checkout),
                        "--directory",
                        str(directory),
                        "--case",
                        case,
                        "--cycles",
                        str(cycles),
                        "--read-passes",
                        str(args.read_passes),
                    ]
                    if fixture:
                        command.extend(["--fixture", fixture])
                    environment = os.environ.copy()
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    environment["POLARS_MAX_THREADS"] = "2"
                    result = _run_one(command, environment)
                    result["rotation"] = rotation
                    results.append(result)
                    pair.append(result)
                comparable = {
                    (
                        item["semantic_sha256"],
                        item["journal_event_count"],
                        item["journal_typed_sha256"],
                        item["journal_raw_sha256"],
                    )
                    for item in pair
                }
                if len(comparable) != 1:
                    raise RuntimeError(f"SEMANTIC_OR_JOURNAL_MISMATCH:{rotation}:{case}")
    return {
        "schema_version": "quarter-spill-storage-profile-v1",
        "baseline_head": "59c1c7bc13b2ebcee8b8acad7dc128d26d886b8d",
        "candidate_head_before_commit": "4bc5f67c6946a3525f49292fd196fcfabb981c46",
        "rotations": args.rotations,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--arm", choices=["baseline", "candidate"])
    parser.add_argument("--checkout")
    parser.add_argument("--directory")
    parser.add_argument("--case", choices=["small-typed-financial", "repeated-rich", "authorized-fixture"])
    parser.add_argument("--fixture")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--read-passes", type=int, default=2)
    parser.add_argument("--rotations", type=int, default=3)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.worker:
        if not args.arm or not args.checkout or not args.directory or not args.case:
            parser.error("worker requires arm, checkout, directory and case")
        print(json.dumps(_worker(args), sort_keys=True))
        return
    if not 1 <= args.rotations <= 3 or args.cycles < 1 or args.read_passes < 1:
        parser.error("invalid bounded profile counts")
    result = _parent(args)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
