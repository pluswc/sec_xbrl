from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import profile_history_run as profiler


def _stat(*, starttime: int = 123, cpu: int = 30, rss: int = 7, state: str = "R") -> str:
    fields = [state, *(["0"] * 10), str(cpu - 10), "10", *(["0"] * 6), str(starttime), "0", str(rss)]
    return f"88 (worker with ) chars) {' '.join(fields)}\n"


def _proc(tmp_path: Path, *, io: bool = True) -> Path:
    root = tmp_path / "proc"
    process = root / "88"
    process.mkdir(parents=True)
    (process / "stat").write_text(_stat(), encoding="utf-8")
    (process / "cmdline").write_bytes(b"python\0worker.py\0_worker\0")
    if io:
        (process / "io").write_text("read_bytes: 12\nwrite_bytes: 34\n", encoding="utf-8")
    return root


def test_process_identity_command_and_missing_io_are_explicit(tmp_path: Path) -> None:
    proc = _proc(tmp_path, io=False)
    stat = profiler._read_process_stat(88, proc)
    assert stat.starttime_ticks == 123
    profiler._verify_command_fragment(88, "_worker", proc)
    with pytest.raises(ValueError, match="fragment"):
        profiler._verify_command_fragment(88, "different", proc)
    assert profiler._read_process_io(88, proc) == {
        "read_bytes": None,
        "write_bytes": None,
        "unavailable_reason": "/proc PID io file is absent",
    }


def test_cpu_delta_reports_interval_core_use_and_pid_reuse_is_detectable() -> None:
    prior = profiler.ProcessStat("R", cpu_ticks=100, starttime_ticks=9, rss_pages=2)
    current = profiler.ProcessStat("R", cpu_ticks=150, starttime_ticks=9, rss_pages=3)
    metrics = profiler._process_metrics(current, (10.0, prior), 10.5, 100, 4096)
    assert metrics["cpu_seconds"] == 1.5
    assert metrics["interval_core_utilization_percent"] == 100.0
    assert metrics["rss_bytes"] == 12288
    reused = profiler.ProcessStat("R", cpu_ticks=1, starttime_ticks=10, rss_pages=1)
    assert reused.starttime_ticks != prior.starttime_ticks


def test_log_reads_known_events_incrementally_and_keeps_unknown_explicit(tmp_path: Path) -> None:
    log = tmp_path / "events.log"
    log.write_text('{"stage":"reported","event":"complete","secret":"not copied"}\n', encoding="utf-8")
    first, size, pending = profiler._observe_log(log, None, b"", 1024)
    assert first["stage"] == "reported"
    assert first["new_stage_events"] == [{"stage": "reported", "event": "complete"}]
    with log.open("a", encoding="utf-8") as stream:
        stream.write("ordinary non-json output\n")
    second, _, _ = profiler._observe_log(log, size, pending, 1024)
    assert second["stage"] == "unknown"
    assert second["growth_bytes"] > 0


def test_file_observation_is_bounded_and_reports_temporary_bytes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"123")
    (root / "spill.sqlite").write_bytes(b"12345")
    observed = profiler._scan_root(root, max_files=1)
    assert observed["regular_files_observed"] == 1
    assert observed["capped"] is True
    complete = profiler._scan_root(root, max_files=3)
    assert complete["file_bytes"] == 8
    assert complete["temporary_file_bytes"] == 5


def test_short_observation_writes_fresh_outputs_and_stops_on_pid_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _proc(tmp_path)
    observed = tmp_path / "observed"
    observed.mkdir()
    log = tmp_path / "run.log"
    log.write_text('{"stage":"load","status":"start"}\n', encoding="utf-8")
    output = tmp_path / "evidence"
    calls = 0
    real_read = profiler._read_process_stat

    def changing_stat(pid: int, proc_root: Path = Path("/proc")) -> profiler.ProcessStat:
        nonlocal calls
        calls += 1
        value = real_read(pid, proc_root)
        if calls >= 3:
            return profiler.ProcessStat(value.state, value.cpu_ticks, 999, value.rss_pages)
        return value

    monkeypatch.setattr(profiler, "_read_process_stat", changing_stat)
    monkeypatch.setattr(profiler.time, "sleep", lambda _: None)
    summary = profiler.run_observation(
        pid=88,
        expected_command_fragment="_worker",
        log_path=log,
        observed_root=observed,
        output_dir=output,
        interval_seconds=0.01,
        max_files=10,
        proc_root=proc,
    )
    assert summary["termination_reason"] == "PID_REUSED"
    assert summary["accounting_verification"] == "NOT_PERFORMED"
    assert (output / "samples.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert json.loads((output / "summary.json").read_text())["sample_count"] == 1
    assert "not PASS accounting verification" in (output / "report.md").read_text()
    with pytest.raises(FileExistsError):
        profiler.run_observation(
            pid=88,
            expected_command_fragment="_worker",
            log_path=log,
            observed_root=observed,
            output_dir=output,
            duration_seconds=0.01,
            proc_root=proc,
        )
