"""Read-only, bounded sampler for an already-running History worker.

The sampler never signals, traces or otherwise changes the target process.  Its
elapsed times cover only the interval after attachment; they are not the run's
total elapsed time and its output is not an accounting acceptance result.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "history-resource-observation-v2"
TEMP_SUFFIXES = {".db", ".part", ".shm", ".sqlite", ".sqlite3", ".temp", ".tmp", ".wal"}
TEMP_PARTS = {".chunks", "spill", "spills", "tmp"}


class ProcessReadError(RuntimeError):
    """A categorized failure to read the observed process identity."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ProcessStat:
    state: str
    cpu_ticks: int
    starttime_ticks: int
    rss_pages: int


@dataclass(frozen=True)
class LogCursor:
    size: int
    device: int
    inode: int
    pending: bytes


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
        raise ProcessReadError("PROCESS_ABSENT_OR_INVISIBLE", "process stat is absent") from exc
    except PermissionError as exc:
        raise ProcessReadError(
            "PROCESS_STAT_PERMISSION_DENIED", "process stat is not readable"
        ) from exc
    except (IndexError, ValueError) as exc:
        raise ProcessReadError("PROCESS_STAT_MALFORMED", "process stat is malformed") from exc


def _verify_command_fragment(
    pid: int, expected_fragment: str, proc_root: Path = Path("/proc")
) -> None:
    if not expected_fragment or "\x00" in expected_fragment:
        raise ValueError("expected command fragment must be non-empty and contain no NUL")
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError) as exc:
        raise ProcessReadError(
            "PROCESS_COMMAND_ABSENT_OR_INVISIBLE", "process command is absent"
        ) from exc
    except PermissionError as exc:
        raise ProcessReadError(
            "PROCESS_COMMAND_PERMISSION_DENIED", "process command is not readable"
        ) from exc
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


def _scan_root(root: Path, max_files: int, max_entries: int) -> dict[str, Any]:
    if not root.exists():
        return {
            "exists": False,
            "entries_observed": 0,
            "regular_files_observed": 0,
            "file_bytes": None,
            "temporary_file_bytes": None,
            "capped": False,
            "partial_reason": None,
            "scan_error": "observed root does not exist",
        }
    if not root.is_dir():
        raise ValueError("observed root must be a directory")
    files = 0
    entries_seen = 0
    total = 0
    temporary = 0
    capped = False
    partial_reason = None
    error = None
    pending = [root]
    try:
        while pending and not capped:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entries_seen >= max_entries:
                        capped = True
                        partial_reason = "max_entries reached"
                        break
                    entries_seen += 1
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if files >= max_files:
                        capped = True
                        partial_reason = "max_files reached"
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
        "entries_observed": entries_seen,
        "regular_files_observed": files,
        "file_bytes": total,
        "temporary_file_bytes": temporary,
        "capped": capped,
        "partial_reason": partial_reason,
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
    for key in ("event", "status", "timestamp", "ticker", "view", "period_class"):
        scalar = value.get(key)
        if isinstance(scalar, (str, int, bool)) or (
            isinstance(scalar, float) and math.isfinite(scalar)
        ):
            result[key] = scalar
    records = value.get("records")
    if isinstance(records, int) and not isinstance(records, bool) and records >= 0:
        result["records"] = records
    for key in ("elapsed_seconds", "monotonic_seconds"):
        elapsed = value.get(key)
        if (
            isinstance(elapsed, (int, float))
            and not isinstance(elapsed, bool)
            and math.isfinite(elapsed)
            and elapsed >= 0
        ):
            result[key] = elapsed
    return result


def _observe_log(
    path: Path,
    cursor: LogCursor | None,
    tail_limit: int,
    max_events: int,
) -> tuple[dict[str, Any], LogCursor | None]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {
            "exists": False,
            "size_bytes": None,
            "growth_bytes": None,
            "stage": "unknown",
            "new_stage_events": [],
            "read_truncated": False,
            "coverage_gap_bytes": 0,
            "event_coverage_gap_count": 0,
            "unavailable_reason": "observed log does not exist",
        }, None

    size = stat.st_size
    identity_changed = cursor is not None and (cursor.device, cursor.inode) != (
        stat.st_dev,
        stat.st_ino,
    )
    truncated = cursor is not None and not identity_changed and size < cursor.size
    reset = cursor is None or identity_changed or truncated
    previous_size = None if cursor is None else cursor.size
    unread_start = 0 if reset else cursor.size
    bounded_start = max(unread_start, size - tail_limit)
    coverage_gap = max(0, bounded_start - unread_start)
    read_truncated = coverage_gap > 0
    pending_bytes = b"" if reset or coverage_gap else cursor.pending
    with path.open("rb") as stream:
        if bounded_start > 0:
            stream.seek(bounded_start - 1)
            prefix = stream.read(1)
        else:
            prefix = b"\n"
        stream.seek(bounded_start)
        new_bytes = stream.read(size - bounded_start)
    if (reset or coverage_gap) and bounded_start > 0 and prefix != b"\n":
        before_discard = len(new_bytes)
        _, separator, new_bytes = new_bytes.partition(b"\n")
        if not separator:
            new_bytes = b""
        coverage_gap += before_discard - len(new_bytes)
        read_truncated = True
    payload = pending_bytes + new_bytes
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
    event_gap = max(0, len(events) - max_events)
    if event_gap:
        events = events[-max_events:]
    stage = events[-1]["stage"] if events else "unknown"
    return {
        "exists": True,
        "size_bytes": size,
        "growth_bytes": (
            None if previous_size is None or identity_changed else size - previous_size
        ),
        "stage": stage,
        "new_stage_events": events,
        "read_truncated": read_truncated,
        "coverage_gap_bytes": coverage_gap,
        "event_coverage_gap_count": event_gap,
        "log_identity_changed": identity_changed,
        "log_reset_reason": (
            "initial"
            if cursor is None
            else "identity_changed"
            if identity_changed
            else "truncated"
            if truncated
            else None
        ),
        "unavailable_reason": None,
    }, LogCursor(size=size, device=stat.st_dev, inode=stat.st_ino, pending=pending)


def _phase_name(event: str) -> tuple[str, str] | None:
    for suffix, kind in (("_BEGIN", "begin"), ("_FLUSH", "flush"), ("_END", "end")):
        if event.endswith(suffix):
            return event[: -len(suffix)], kind
    return None


def _update_phase_summaries(
    phases: dict[tuple[str, str, str, str, str], dict[str, Any]],
    events: list[dict[str, Any]],
    observer_elapsed: float,
    max_phases: int,
) -> int:
    coverage_gap = 0
    for event in events:
        event_name = event.get("event")
        parsed = _phase_name(event_name) if isinstance(event_name, str) else None
        if parsed is None:
            continue
        phase, kind = parsed
        key = (
            event["stage"],
            phase,
            str(event.get("ticker", "unknown")),
            str(event.get("view", "unknown")),
            str(event.get("period_class", "unknown")),
        )
        if key not in phases:
            if len(phases) >= max_phases:
                coverage_gap += 1
                continue
            phases[key] = {
                "stage": key[0],
                "phase": key[1],
                "ticker": key[2],
                "view": key[3],
                "period_class": key[4],
                "observed_event_count": 0,
                "source_records_total": 0,
                "begin_observer_elapsed_seconds": None,
                "end_observer_elapsed_seconds": None,
                "begin_source_elapsed_seconds": None,
                "end_source_elapsed_seconds": None,
                "begin_source_elapsed_field": None,
                "end_source_elapsed_field": None,
                "seen_begin": False,
                "seen_end": False,
            }
        summary = phases[key]
        summary["observed_event_count"] += 1
        summary["source_records_total"] += event.get("records", 0)
        source_field = None
        source_elapsed = None
        for candidate in ("elapsed_seconds", "monotonic_seconds"):
            if candidate in event:
                source_field = candidate
                source_elapsed = event[candidate]
                break
        if kind == "begin":
            summary["seen_begin"] = True
            summary["seen_end"] = False
            summary["begin_observer_elapsed_seconds"] = observer_elapsed
            summary["begin_source_elapsed_seconds"] = source_elapsed
            summary["begin_source_elapsed_field"] = source_field
            summary["end_observer_elapsed_seconds"] = None
            summary["end_source_elapsed_seconds"] = None
            summary["end_source_elapsed_field"] = None
        elif kind == "end":
            summary["seen_end"] = True
            summary["end_observer_elapsed_seconds"] = observer_elapsed
            summary["end_source_elapsed_seconds"] = source_elapsed
            summary["end_source_elapsed_field"] = source_field
    return coverage_gap


def _phase_rows(phases: dict[tuple[str, str, str, str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for value in phases.values():
        row = dict(value)
        begin = row["begin_source_elapsed_seconds"]
        end = row["end_source_elapsed_seconds"]
        same_source = (
            row["begin_source_elapsed_field"] is not None
            and row["begin_source_elapsed_field"] == row["end_source_elapsed_field"]
        )
        seen_begin = row.pop("seen_begin")
        seen_end = row.pop("seen_end")
        ordered = (
            row["begin_observer_elapsed_seconds"] is not None
            and row["end_observer_elapsed_seconds"] is not None
            and row["end_observer_elapsed_seconds"] >= row["begin_observer_elapsed_seconds"]
        )
        row["status"] = "complete" if seen_begin and seen_end and ordered else "partial"
        if row["status"] != "complete":
            row["source_duration_seconds"] = None
            row["source_duration_basis"] = None
        elif (
            row["end_source_elapsed_field"] == "elapsed_seconds"
            and row["begin_source_elapsed_field"] != "elapsed_seconds"
        ):
            row["source_duration_seconds"] = end
            row["source_duration_basis"] = "end_event_elapsed_seconds"
        elif same_source and begin is not None and end is not None and end >= begin:
            row["source_duration_seconds"] = end - begin
            row["source_duration_basis"] = "matching_source_elapsed_delta"
        else:
            row["source_duration_seconds"] = None
            row["source_duration_basis"] = None
        rows.append(row)
    return rows


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
    lines = [
        "# History worker resource observation",
        "",
        f"- Termination: `{summary['termination_reason']}`",
        f"- Observation elapsed: {summary['observation_elapsed_seconds']} seconds (partial interval after attach)",
        f"- Samples: {summary['sample_count']}",
        f"- Latest stage: `{log.get('stage', 'unknown')}` (unknown means no recognized new JSON stage event)",
        f"- CPU cumulative seconds: {process.get('cpu_seconds')}",
        f"- CPU delta during observation: {summary.get('observation_cpu_delta_seconds')} seconds",
        f"- Latest interval core utilization: {process.get('interval_core_utilization_percent')}%",
        f"- RSS bytes: {process.get('rss_bytes')}",
        f"- Kernel read/write bytes: {io.get('read_bytes')} / {io.get('write_bytes')}",
        f"- Kernel I/O unavailable reason: {io.get('unavailable_reason')}",
        f"- Observed regular-file bytes: {observed.get('file_bytes')} (delta {observed.get('file_bytes_delta')})",
        f"- Observed temporary-file bytes: {observed.get('temporary_file_bytes')} (delta {observed.get('temporary_file_bytes_delta')})",
        f"- Bounded scan capped: {observed.get('capped')}",
        "",
        "## Observed phase timing",
        "",
        "| Phase | Stage | Company | View / period | Events | Source elapsed begin / end / duration | Status |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for phase in summary.get("phase_summaries", []):
        lines.append(
            "| {phase} | {stage} | {ticker} | {view} / {period_class} | {count} | "
            "{begin_field}:{begin} / {end_field}:{end} / {duration} ({basis}) | {status} |".format(
                phase=phase["phase"],
                stage=phase["stage"],
                ticker=phase["ticker"],
                view=phase["view"],
                period_class=phase["period_class"],
                count=phase["observed_event_count"],
                begin_field=phase["begin_source_elapsed_field"],
                begin=phase["begin_source_elapsed_seconds"],
                end_field=phase["end_source_elapsed_field"],
                end=phase["end_source_elapsed_seconds"],
                duration=phase["source_duration_seconds"],
                basis=phase["source_duration_basis"],
                status=phase["status"],
            )
        )
    if not summary.get("phase_summaries"):
        lines.append("| unknown | unknown | unknown | unknown / unknown | 0 | None / None / None | partial |")
    lines.extend(
        [
            "",
            f"Phase coverage-gap events: {summary.get('phase_coverage_gap_events', 0)}.",
            f"Log coverage-gap bytes: {summary.get('log_coverage_gap_bytes', 0)}.",
            "Source elapsed values come only from whitelisted log fields. Missing BEGIN or END keeps duration unknown; no ETA is inferred.",
            "Observer elapsed and CPU delta cover only the interval after attachment.",
            "",
            "This is an operational resource observation, not PASS accounting verification or acceptance.",
            "It does not include runtime before attachment and cannot see unlinked open spill files via /proc fd.",
            "",
        ]
    )
    return "\n".join(lines)


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
    max_entries: int = 8000,
    log_tail_bytes: int = 65536,
    max_log_events: int = 1000,
    max_phases: int = 100,
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    if (
        pid <= 0
        or interval_seconds <= 0
        or max_files <= 0
        or max_entries <= 0
        or log_tail_bytes <= 0
        or max_log_events <= 0
        or max_phases <= 0
    ):
        raise ValueError("all numeric limits and pid must be positive")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration must be positive when supplied")
    output_dir = output_dir.resolve()
    observed_root = observed_root.resolve()
    log_path = log_path.resolve()
    if output_dir == observed_root or observed_root in output_dir.parents:
        raise ValueError("output directory must be outside the observed root")

    started = time.monotonic()
    started_utc = _utc_now()
    initial_stat = _read_process_stat(pid, proc_root)
    _verify_command_fragment(pid, expected_command_fragment, proc_root)
    identity = initial_stat.starttime_ticks
    output_dir.mkdir(parents=True, exist_ok=False)
    samples_path = output_dir / "samples.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    previous_process: tuple[float, ProcessStat] | None = None
    previous_root: dict[str, Any] | None = None
    log_cursor: LogCursor | None = None
    phases: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    phase_coverage_gap = 0
    log_coverage_gap_bytes = 0
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
            except ProcessReadError as exc:
                termination = exc.reason
                break
            if stat.starttime_ticks != identity:
                termination = "PID_REUSED"
                break

            process = _process_metrics(
                stat, previous_process, now, clock_ticks=clock_ticks, page_size=page_size
            )
            process["io"] = _read_process_io(pid, proc_root)
            root = _scan_root(observed_root, max_files, max_entries)
            prior_total = None if previous_root is None else previous_root["file_bytes"]
            prior_temp = None if previous_root is None else previous_root["temporary_file_bytes"]
            root["file_bytes_delta"] = _numeric_delta(root["file_bytes"], prior_total)
            root["temporary_file_bytes_delta"] = _numeric_delta(
                root["temporary_file_bytes"], prior_temp
            )
            root["filesystem"] = _filesystem_free(observed_root)
            log, log_cursor = _observe_log(
                log_path, log_cursor, log_tail_bytes, max_log_events
            )
            log_coverage_gap_bytes += log["coverage_gap_bytes"]
            phase_coverage_gap += log["event_coverage_gap_count"]
            phase_coverage_gap += _update_phase_summaries(
                phases,
                log["new_stage_events"],
                round(now - started, 3),
                max_phases,
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
                "observation_cpu_delta_seconds": round(
                    (stat.cpu_ticks - initial_stat.cpu_ticks) / clock_ticks, 6
                ),
                "phase_summaries": _phase_rows(phases),
                "phase_coverage_gap_events": phase_coverage_gap,
                "log_coverage_gap_bytes": log_coverage_gap_bytes,
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
        "observation_cpu_delta_seconds": (
            None
            if previous_process is None
            else round((previous_process[1].cpu_ticks - initial_stat.cpu_ticks) / clock_ticks, 6)
        ),
        "phase_summaries": _phase_rows(phases),
        "phase_coverage_gap_events": phase_coverage_gap,
        "log_coverage_gap_bytes": log_coverage_gap_bytes,
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
    value.add_argument("--max-entries", type=int, default=8000)
    value.add_argument("--log-tail-bytes", type=int, default=65536)
    value.add_argument("--max-log-events", type=int, default=1000)
    value.add_argument("--max-phases", type=int, default=100)
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
        max_entries=args.max_entries,
        log_tail_bytes=args.log_tail_bytes,
        max_log_events=args.max_log_events,
        max_phases=args.max_phases,
    )
    print(json.dumps({"summary": str(args.output_dir / "summary.json"), "termination": summary["termination_reason"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
