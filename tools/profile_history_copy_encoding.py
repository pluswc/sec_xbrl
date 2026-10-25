"""Paired bounded profile for selective copy and typed hashing."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import resource
import struct
import subprocess
import sys
import time
from pathlib import Path

from tools.history_audit_typed_hash import TypedHash

MAX_FIXTURE = 16 * 1024 * 1024
MAX_RSS_KIB = 1024 * 1024
TARGET_LOGICAL = 32 * 1024 * 1024


def _put(digest, payload):
    digest.update(struct.pack(">Q", len(payload)))
    digest.update(payload)


def _raw(value):
    if value is None:
        return b"N"
    if type(value) is bool:
        return b"B1" if value else b"B0"
    if type(value) is int:
        return b"I" + str(value).encode("ascii")
    if type(value) is float:
        return b"F" + struct.pack(">d", value)
    if type(value) is str:
        return b"S" + value.encode()
    if type(value) is bytes:
        return b"Y" + value
    if type(value) in (dict, list, tuple):
        nested = hashlib.sha256()
        _logical(nested, value)
        return b"C" + nested.digest()
    raise TypeError(type(value))


def _logical(digest, value):
    if type(value) is dict:
        digest.update(b"D")
        _put(digest, str(len(value)).encode())
        for key in sorted(value):
            _put(digest, key.encode())
            _logical(digest, value[key])
    elif type(value) in (list, tuple):
        digest.update(b"L" if type(value) is list else b"T")
        _put(digest, str(len(value)).encode())
        for item in value:
            _logical(digest, item)
    else:
        _put(digest, _raw(value))


def _load(path):
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_FIXTURE:
        raise RuntimeError("FIXTURE_TOO_LARGE")
    lines = [line for line in path.read_text().splitlines() if line]
    cycles = max(1, (TARGET_LOGICAL + size - 1) // size)
    return lines, cycles


def _worker(args):
    lines, cycles = _load(args.fixture)
    digest = hashlib.sha256()
    started = time.perf_counter()
    for _ in range(cycles):
        for line in lines:
            if args.mode == "copy":
                source = json.loads(line)["cell"]
                before = json.dumps(
                    source,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if args.arm == "baseline":
                    cell = copy.deepcopy(source)
                else:
                    cell = dict(source)
                    value = cell.get("value_lineage")
                    if isinstance(value, dict):
                        cell["value_lineage"] = dict(value)
                value = cell.get("value_lineage")
                if isinstance(value, dict):
                    value["period_class"] = "QTD_3M"
                if cell.get("candidate_lineage"):
                    cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")
                payload = json.dumps(
                    cell, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
                if (
                    json.dumps(
                        source,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    != before
                ):
                    raise RuntimeError("INPUT_MUTATED")
            elif args.mode == "hash":
                left = json.loads(line)["cell"]
                right = json.loads(line)["cell"]
                if args.arm == "baseline":
                    hashes = []
                    for value in (left, left, left, right, right):
                        item = hashlib.sha256()
                        _logical(item, value)
                        hashes.append(item.digest())
                    for item in hashes:
                        digest.update(item)
                else:
                    a = TypedHash()
                    achunk = TypedHash()
                    arow = TypedHash()
                    a.update(left, mirrors=(achunk, arow))
                    b = TypedHash()
                    brow = TypedHash()
                    b.update(right, mirrors=(brow,))
                    for item in (a, achunk, arow, b, brow):
                        digest.update(item.digest())
            else:
                value = json.loads(line)["cell"]
                if args.arm == "baseline":
                    item = hashlib.sha256()
                    _logical(item, value)
                    digest.update(item.digest())
                else:
                    item = TypedHash()
                    item.update(value)
                    digest.update(item.digest())
    return {
        "arm": args.arm,
        "mode": args.mode,
        "original_records": len(lines),
        "exercise_iterations": len(lines) * cycles,
        "cycles": cycles,
        "seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "fingerprint": digest.hexdigest(),
    }


def _run(command, env):
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    peak = 0
    deadline = time.monotonic() + 30
    while process.poll() is None:
        try:
            for line in Path(f"/proc/{process.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    peak = max(peak, int(line.split()[1]))
        except OSError:
            pass
        if peak > MAX_RSS_KIB or time.monotonic() > deadline:
            process.kill()
            raise RuntimeError("WORKER_LIMIT")
        time.sleep(0.01)
    out, err = process.communicate()
    if process.returncode:
        raise RuntimeError(err[-2000:])
    result = json.loads(out)
    result["watchdog_peak_rss_kib"] = peak
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--arm", choices=("baseline", "candidate"))
    parser.add_argument("--mode", choices=("copy", "hash", "single"))
    parser.add_argument("--only-mode", choices=("copy", "hash", "single"))
    parser.add_argument("--fixture")
    parser.add_argument("--rotations", type=int, default=3)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args), sort_keys=True))
        return
    if not args.fixture or not 1 <= args.rotations <= 3:
        parser.error("bounded fixture and rotations required")
    results = []
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for rotation in range(args.rotations):
        arms = ("baseline", "candidate") if rotation % 2 == 0 else ("candidate", "baseline")
        for mode in (args.only_mode,) if args.only_mode else ("copy", "hash"):
            for arm in arms:
                command = [
                    sys.executable,
                    "-B",
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--arm",
                    arm,
                    "--mode",
                    mode,
                    "--fixture",
                    args.fixture,
                ]
                result = _run(command, env)
                result["rotation"] = rotation
                results.append(result)
    report = {
        "schema_version": "history-copy-encoding-profile-v1",
        "fixture": args.fixture,
        "rotations": args.rotations,
        "results": results,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
