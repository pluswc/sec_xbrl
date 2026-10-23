"""Read-only, bounded sampler for an already-running History worker.

The sampler never signals, traces or otherwise changes the target process.  Its
elapsed times cover only the interval after attachment; they are not the run's
total elapsed time and its output is not an accounting acceptance result.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "history-resource-observation-v1"
TEMP_SUFFIXES = {".db", ".part", ".shm", ".sqlite", ".sqlite3", ".temp", ".tmp", ".wal"}
TEMP_PARTS = {".chunks", "spill", "spills", "tmp"}


class ProcessUnavailable(RuntimeError):
    """The observed PID is absent or no longer has the attached identity."""


@dataclass(frozen=True)
class ProcessStat:
    state: str
    cpu_ticks: int
    starttime_ticks: int
    rss_pages: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_process_stat(pid: int, proc_root: Path = Path("/proc")) -> ProcessStat:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
        fields = raw.rsplit(") ", 1)[1].split()
        return ProcessStat(
            state=fields[0],
            cpu_ticks=int(fields[11]) + int(fields[12]),
            starttime_ticks=int(fields[19]),
            rss_pages=int(fields[21]),
        )
    except (FileNotFoundError, ProcessLookupError) as exc:
        raise ProcessUnavailable("process stat is unavailable") from exc
    except PermissionError as exc:
        raise ProcessUnavailable("process stat is not readable") from exc
    except (IndexError, ValueError) as exc:
        raise ProcessUnavailable("process stat is malformed") from exc


def _verify_command_fragment(
    pid: int, expected_fragment: str, proc_root: Path = Path("/proc")
) -> None:
    if not expected_fragment or "\x00" in expected_fragment:
        raise ValueError("expected command fragment must be non-empty and contain no NUL")
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError) as exc:
        raise ProcessUnavailable("process command is unavailable") from exc
    except PermissionError as exc:
        raise ProcessUnavailable("process command is not readable") from exc
    command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
    if expected_fragment not in command:
        raise ValueError("target command does not contain --expected-command-fragment")


def _read_process_io(pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    path = proc_root / str(pid) / "io"
    try:
        fields = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            name, value = line.split(":", 1)
            fields[name.strip()] = int(value.strip())
        if "read_bytes" not in fields or "write_bytes" not in fields:
            raise ValueError("required counters are absent")
        return {
            "read_bytes": fields["read_bytes"],
            "write_bytes": fields["write_bytes"],
            "unavailable_reason": None,
        }
    except FileNotFoundError:
        return {
            "read_bytes": None,
            "write_bytes": None,
            "unavailable_reason": "/proc PID io file is absent",
        }
    except PermissionError:
        return {
            "read_bytes": None,
            "write_bytes": None,
            "unavailable_reason": "/proc PID io file is not readable",
        }
    except (ValueError, IndexError):
        return {
            "read_bytes": None,
            "write_bytes": None,
            "unavailable_reason": "/proc PID io counters are malformed or incomplete",
        }


def _process_metrics(
    stat: ProcessStat,
    previous: tuple[float, ProcessStat] | None,
    now_monotonic: float,
    clock_ticks: int,
    page_size: int,
) -> dict[str, Any]:
    cpu_seconds = stat.cpu_ticks / clock_ticks
    utilization = None
    if previous is not None:
        previous_time, previous_stat = previous
        elapsed = now_monotonic - previous_time
        delta_ticks = stat.cpu_ticks - previous_stat.cpu_ticks
        if elapsed > 0 and delta_ticks >= 0:
            utilization = (delta_ticks / clock_ticks) / elapsed * 100.0
    return {
        "state": stat.state,
        "cpu_seconds": round(cpu_seconds, 6),
        "interval_core_utilization_percent": (
            None if utilization is None else round(utilization, 3)
        ),
        "rss_bytes": stat.rss_pages * page_size,
    }


def _is_temporary(path: Path) -> bool:
    return path.suffix.lower() in TEMP_SUFFIXES or any(part.lower() in TEMP_PARTS for part in path.parts)


def _scan_root(root: Path, max_files: int) -> dict[str, Any]:
    if not root.exists():
        return {
            "exists": False,
            "regular_files_observed": 0,
            "file_bytes": None,
            "temporary_file_bytes": None,
            "capped": False,
            "scan_error": "observed root does not exist",
        }
    if not root.is_dir():
        raise ValueError("observed root must be a directory")
    files = 0
    total = 0
    temporary = 0
    capped = False
    error = None
    pending = [root]
    try:
        while pending and not capped:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if files >= max_files:
                        capped = True
                        break
                    size = entry.stat(follow_symlinks=False).st_size
                    path = Path(entry.path)
                    files += 1
                    total += size
                    if _is_temporary(path.relative_to(root)):
                        temporary += size
    except (FileNotFoundError, PermissionError, OSError) as exc:
        error = f"bounded scan incomplete: {type(exc).__name__}"
    return {
        "exists": True,
        "regular_files_observed": files,
        "file_bytes": total,
        "temporary_file_bytes": temporary,
        "capped": capped,
        "scan_error": error,
    }


def _filesystem_free(root: Path) -> dict[str, Any]:
    anchor = root
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    try:
        value = os.statvfs(anchor)
        return {"free_bytes": value.f_bavail * value.f_frsize, "unavailable_reason": None}
    except OSError as exc:
        return {"free_bytes": None, "unavailable_reason": f"statvfs failed: {type(exc).__name__}"}


def _numeric_delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _stage_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("stage"), str):
        return None
    result = {"stage": value["stage"]}
    for key in ("event", "status", "timestamp"):
        if isinstance(value.get(key), (str, int, float, bool)):
            result[key] = value[key]
    return result


def _observe_log(
    path: Path,
    previous_size: int | None,
    pending_bytes: bytes,
    tail_limit: int,
) -> tuple[dict[str, Any], int | None, bytes]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return {
            "exists": False,
            "size_bytes": None,
            "growth_bytes": None,
            "stage": "unknown",
            "new_stage_events": [],
            "read_truncated": False,
            "unavailable_reason": "observed log does not exist",
        }, None, b""

    reset = previous_size is None or size < previous_size
    offset = max(0, size - tail_limit) if reset else previous_size
    read_truncated = reset and offset > 0
    with path.open("rb") as stream:
        stream.seek(offset)
        new_bytes = stream.read(tail_limit + 1)
    if len(new_bytes) > tail_limit:
        new_bytes = new_bytes[-tail_limit:]
        read_truncated = True
        pending_bytes = b""
    payload = (b"" if reset else pending_bytes) + new_bytes
    lines = payload.split(b"\n")
    pending = lines.pop()[-tail_limit:]
    events = []
    for raw in lines:
        try:
            event = _stage_event(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            event = None
        if event is not None:
            events.append(event)
    stage = events[-1]["stage"] if events else "unknown"
    return {
        "exists": True,
        "size_bytes": size,
        "growth_bytes": None if previous_size is None else size - previous_size,
        "stage": stage,
        "new_stage_events": events,
        "read_truncated": read_truncated,
        "unavailable_reason": None,
    }, size, pending


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _report(summary: dict[str, Any]) -> str:
    latest = summary.get("latest_sample") or {}
    process = latest.get("process") or {}
    observed = latest.get("observed_root") or {}
    log = latest.get("log") or {}
    io = process.get("io") or {}
    return "\n".join(
        [
            "# History worker resource observation",
            "",
            f"- Termination: `{summary['termination_reason']}`",
            f"- Observation elapsed: {summary['observation_elapsed_seconds']} seconds (partial interval after attach)",
            f"- Samples: {summary['sample_count']}",
            f"- Latest stage: `{log.get('stage', 'unknown')}` (unknown means no recognized new JSON stage event)",
            f"- CPU cumulative seconds: {process.get('cpu_seconds')}",
            f"- Latest interval core utilization: {process.get('interval_core_utilization_percent')}%",
            f"- RSS bytes: {process.get('rss_bytes')}",
            f"- Kernel read/write bytes: {io.get('read_bytes')} / {io.get('write_bytes')}",
            f"- Kernel I/O unavailable reason: {io.get('unavailable_reason')}",
            f"- Observed regular-file bytes: {observed.get('file_bytes')} (delta {observed.get('file_bytes_delta')})",
            f"- Observed temporary-file bytes: {observed.get('temporary_file_bytes')} (delta {observed.get('temporary_file_bytes_delta')})",
            f"- Bounded scan capped: {observed.get('capped')}",
            "",
            "This is an operational resource observation, not PASS accounting verification or acceptance.",
            "It does not include runtime before attachment and cannot see unlinked open spill files via /proc fd.",
            "",
        ]
    )


def run_observation(
    *,
    pid: int,
    expected_command_fragment: str,
    log_path: Path,
    observed_root: Path,
    output_dir: Path,
    interval_seconds: float = 5.0,
    duration_seconds: float | None = None,
    max_files: int = 2000,
    log_tail_bytes: int = 65536,
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    if pid <= 0 or interval_seconds <= 0 or max_files <= 0 or log_tail_bytes <= 0:
        raise ValueError("pid, interval, max-files and log-tail-bytes must be positive")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration must be positive when supplied")
    output_dir = output_dir.resolve()
    observed_root = observed_root.resolve()
    log_path = log_path.resolve()
    if output_dir == observed_root or observed_root in output_dir.parents:
        raise ValueError("output directory must be outside the observed root")

    initial_stat = _read_process_stat(pid, proc_root)
    _verify_command_fragment(pid, expected_command_fragment, proc_root)
    identity = initial_stat.starttime_ticks
    output_dir.mkdir(parents=True, exist_ok=False)
    samples_path = output_dir / "samples.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    started = time.monotonic()
    started_utc = _utc_now()
    previous_process: tuple[float, ProcessStat] | None = None
    previous_root: dict[str, Any] | None = None
    previous_log_size: int | None = None
    log_pending = b""
    sample_count = 0
    latest: dict[str, Any] | None = None
    termination = "UNKNOWN"
    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")

    with samples_path.open("x", encoding="utf-8") as samples:
        while True:
            now = time.monotonic()
            try:
                stat = _read_process_stat(pid, proc_root)
            except ProcessUnavailable:
                termination = "PROCESS_EXITED"
                break
            if stat.starttime_ticks != identity:
                termination = "PID_REUSED"
                break

            process = _process_metrics(
                stat, previous_process, now, clock_ticks=clock_ticks, page_size=page_size
            )
            process["io"] = _read_process_io(pid, proc_root)
            root = _scan_root(observed_root, max_files)
            prior_total = None if previous_root is None else previous_root["file_bytes"]
            prior_temp = None if previous_root is None else previous_root["temporary_file_bytes"]
            root["file_bytes_delta"] = _numeric_delta(root["file_bytes"], prior_total)
            root["temporary_file_bytes_delta"] = _numeric_delta(
                root["temporary_file_bytes"], prior_temp
            )
            root["filesystem"] = _filesystem_free(observed_root)
            log, previous_log_size, log_pending = _observe_log(
                log_path, previous_log_size, log_pending, log_tail_bytes
            )
            latest = {
                "schema_version": SCHEMA_VERSION,
                "sample_number": sample_count + 1,
                "observed_at": _utc_now(),
                "observation_elapsed_seconds": round(now - started, 3),
                "process": process,
                "log": log,
                "observed_root": root,
            }
            samples.write(json.dumps(latest, sort_keys=True) + "\n")
            samples.flush()
            sample_count += 1
            previous_process = (now, stat)
            previous_root = root

            elapsed = time.monotonic() - started
            if duration_seconds is not None and elapsed >= duration_seconds:
                termination = "DURATION_REACHED"
            elif stat.state == "Z":
                termination = "PROCESS_EXITED_ZOMBIE"
            if termination != "UNKNOWN":
                break
            sleep_for = interval_seconds
            if duration_seconds is not None:
                sleep_for = min(sleep_for, max(0.0, duration_seconds - elapsed))
            if sleep_for <= 0:
                termination = "DURATION_REACHED"
                break

            interim = {
                "schema_version": SCHEMA_VERSION,
                "status": "OBSERVING",
                "termination_reason": None,
                "pid": pid,
                "process_starttime_ticks": identity,
                "command_fragment_verified": True,
                "started_at": started_utc,
                "observation_elapsed_seconds": round(elapsed, 3),
                "sample_count": sample_count,
                "latest_sample": latest,
                "limitations": [
                    "elapsed time starts at attachment",
                    "unlinked open spill files are not visible because /proc PID fd is not scanned",
                ],
            }
            _atomic_json(summary_path, interim)
            _atomic_text(report_path, _report(interim | {"termination_reason": "IN_PROGRESS"}))
            time.sleep(sleep_for)

    elapsed = time.monotonic() - started
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "RESOURCE_OBSERVATION_COMPLETE",
        "accounting_verification": "NOT_PERFORMED",
        "termination_reason": termination,
        "pid": pid,
        "process_starttime_ticks": identity,
        "command_fragment_verified": True,
        "started_at": started_utc,
        "finished_at": _utc_now(),
        "observation_elapsed_seconds": round(elapsed, 3),
        "sample_count": sample_count,
        "latest_sample": latest,
        "limitations": [
            "elapsed time starts at attachment and is not total run elapsed time",
            "unlinked open spill files are not visible because /proc PID fd is not scanned",
            "bounded file totals are partial when capped or when a scan error is reported",
            "unknown stage means no recognized new JSON stage event; no stage or ETA is inferred",
        ],
    }
    _atomic_json(summary_path, summary)
    _atomic_text(report_path, _report(summary))
    return summary


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--pid", type=int, required=True)
    value.add_argument("--expected-command-fragment", required=True)
    value.add_argument("--log", type=Path, required=True)
    value.add_argument("--observe-root", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--interval", type=float, default=5.0)
    value.add_argument("--duration", type=float)
    value.add_argument("--max-files", type=int, default=2000)
    value.add_argument("--log-tail-bytes", type=int, default=65536)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    summary = run_observation(
        pid=args.pid,
        expected_command_fragment=args.expected_command_fragment,
        log_path=args.log,
        observed_root=args.observe_root,
        output_dir=args.output_dir,
        interval_seconds=args.interval,
        duration_seconds=args.duration,
        max_files=args.max_files,
        log_tail_bytes=args.log_tail_bytes,
    )
    print(json.dumps({"summary": str(args.output_dir / "summary.json"), "termination": summary["termination_reason"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
