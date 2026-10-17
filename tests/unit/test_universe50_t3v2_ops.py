from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module():
    package = types.ModuleType("sec_xbrl")
    package.__path__ = []
    fake_ops = types.ModuleType("sec_xbrl.collection_operations")
    fake_ops.__file__ = __file__
    fake_history = types.ModuleType("sec_xbrl.history")
    fake_history.__file__ = __file__
    package.collection_operations = fake_ops
    package.history = fake_history
    sys.modules.setdefault("sec_xbrl", package)
    sys.modules.setdefault("sec_xbrl.collection_operations", fake_ops)
    sys.modules.setdefault("sec_xbrl.history", fake_history)
    path = Path(__file__).parents[2] / "tools" / "universe50_t3v2_ops.py"
    spec = importlib.util.spec_from_file_location("universe50_t3v2_ops", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _module()


def _config(tmp_path: Path) -> Path:
    artifacts = {}
    for name, digest in runner.INPUT_HASHES.items():
        artifacts[name] = {"path": str(tmp_path / f"{name}.json"), "sha256": digest}
    value = {
        "schema_version": runner.CONFIG_SCHEMA,
        "run_id": "fresh-run",
        "source_sha": runner.SOURCE_SHA,
        "engine_checkout": str(tmp_path / "engine"),
        "collection_root": str(tmp_path / "fresh-run"),
        "history_root": str(tmp_path / "history"),
        "first5": list(runner.FIRST5),
        "limits": {
            "process_tree_rss_kib": runner.LIMIT_KIB,
            "polars_max_threads": 2,
            "one_heavy_process": True,
            "timeout_seconds": runner.TIMEOUT,
        },
        "artifacts": artifacts,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    return path


def test_config_rejects_non_authoritative_hash(tmp_path: Path) -> None:
    path = _config(tmp_path)
    value = json.loads(path.read_text())
    value["artifacts"]["candidate"]["sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="non-authoritative artifact"):
        runner.load_config(path)


def test_later_45_requires_explicit_first5_gate() -> None:
    with pytest.raises(ValueError, match="later-45"):
        runner.validate_bulk_gate("AAPL", None, None)
    runner.validate_bulk_gate("CVX", None, None)


def test_prepare_is_offline_and_uses_all_candidate_plans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {
        "run_id": "fresh-run",
        "collection_root": str(tmp_path / "fresh-run"),
    }
    universe = {
        "universe_id": "old",
        "companies": [{"ticker": "AAA"}],
    }
    candidate = {"selection": [{"ticker": "AAA", "plan": str(tmp_path / "plan.json")}]}
    values = iter([universe, candidate])
    monkeypatch.setattr(
        runner, "validate_preflight", lambda _: (config, {}, tmp_path / "preflight")
    )
    monkeypatch.setattr(runner, "artifact", lambda *_: (tmp_path / "input.json", "x"))
    monkeypatch.setattr(runner, "read_json", lambda _: next(values))
    monkeypatch.setattr(runner, "write_once", lambda *args: None)
    captured = {}

    def prepare_universe(**kwargs):
        captured.update(kwargs)
        return tmp_path / "manifest.json"

    monkeypatch.setattr(runner.ops, "prepare_universe", prepare_universe, raising=False)
    monkeypatch.setattr(
        runner.ops,
        "read_universe_status",
        lambda **_: SimpleNamespace(requested_companies=50, prepared_companies=50),
        raising=False,
    )
    runner.prepare_new_collection(tmp_path / "ops.json")
    assert captured["offline"] is True
    assert captured["existing_plans"] == {"AAA": tmp_path / "plan.json"}


def test_build_refuses_output_collision_before_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {
        "collection_root": str(tmp_path),
        "history_root": str(tmp_path / "history"),
        "run_id": "r",
    }
    preflight = {"modules": {"aggregate_sha256": "a"}}
    destination = tmp_path / "history" / "CVX-t3v2-r"
    destination.mkdir(parents=True)
    monkeypatch.setattr(runner, "manifest", lambda _: tmp_path / "collection_manifest.json")
    monkeypatch.setattr(
        runner.ops,
        "_attest_run",
        lambda _: SimpleNamespace(manifest={"companies": []}),
        raising=False,
    )
    with pytest.raises(ValueError, match="partial/unreceipted"):
        runner.validate_existing_build(config, "CVX", preflight)


def test_existing_marker_must_pass_actual_validator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {
        "collection_root": str(tmp_path),
        "history_root": str(tmp_path / "history"),
        "run_id": "r",
    }
    company = tmp_path / "companies" / "CVX"
    company.mkdir(parents=True)
    (company / "build_manifest.json").write_text("{}")
    (company / "ops_build_receipt.json").write_text("{}")
    destination = tmp_path / "history" / "CVX-t3v2-r"
    destination.mkdir(parents=True)
    run = SimpleNamespace(
        manifest={"companies": [{"ticker": "CVX", "plan_sha256": "p"}]},
        plans={"CVX": {}},
    )
    monkeypatch.setattr(runner, "manifest", lambda _: tmp_path / "collection_manifest.json")
    monkeypatch.setattr(runner.ops, "_attest_run", lambda _: run, raising=False)
    monkeypatch.setattr(runner.ops, "_attest_intake", lambda *_: object(), raising=False)
    monkeypatch.setattr(
        runner.ops,
        "_validate_build_attestation",
        lambda *args, **kwargs: "bad marker",
        raising=False,
    )
    with pytest.raises(ValueError, match="actual validation"):
        runner.validate_existing_build(config, "CVX", {"modules": {"aggregate_sha256": "a"}})


def test_runner_has_no_network_or_collector_call() -> None:
    source = Path(runner.__file__).read_text()
    assert "offline=True" in source
    assert "SECArchiveClient" not in source
    assert "collect_universe(" not in source


def test_direct_worker_callback_is_rejected_before_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called = False

    def forbidden(**_):
        nonlocal called
        called = True

    monkeypatch.setattr(runner, "validate_go", lambda *args: ({}, {}))
    monkeypatch.setattr(runner.history, "build_history", forbidden, raising=False)
    with pytest.raises(PermissionError, match="inherited supervisor"):
        runner.build_worker(tmp_path / "config", "CVX", tmp_path / "go")
    assert called is False


def test_worker_rechecks_bulk_gate_after_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "validate_go", lambda *args: ({}, {}))
    monkeypatch.setattr(runner, "receive_supervisor", lambda _: None)
    with pytest.raises(ValueError, match="later-45"):
        runner.build_worker(
            tmp_path / "config",
            "AAPL",
            tmp_path / "go",
        )


def test_supervised_first5_worker_passes_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ReachedGuardedWork(Exception):
        pass

    monkeypatch.setattr(runner, "validate_go", lambda *args: ({}, {}))
    monkeypatch.setattr(runner, "receive_supervisor", lambda _: None)
    monkeypatch.setattr(runner, "candidate_rows", lambda _: {"CVX": {}})
    monkeypatch.setattr(
        runner,
        "manifest",
        lambda _: (_ for _ in ()).throw(ReachedGuardedWork()),
    )
    with pytest.raises(ReachedGuardedWork):
        runner.build_worker(
            tmp_path / "config",
            "CVX",
            tmp_path / "go",
        )


def test_supervisor_capability_requires_pipe_and_parent_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = b"x" * 32
    read_fd, write_fd = os.pipe()
    os.write(write_fd, token)
    os.close(write_fd)
    monkeypatch.setenv("SEC_XBRL_T3V2_SUPERVISOR_FD", str(read_fd))
    monkeypatch.setenv("SEC_XBRL_T3V2_SUPERVISOR_PID", "123")
    monkeypatch.setenv("SEC_XBRL_T3V2_SUPERVISOR_SHA256", runner.hashlib.sha256(token).hexdigest())
    for name, value in {
        "POLARS_MAX_THREADS": "2",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(runner.os, "getppid", lambda: 123)
    monkeypatch.setattr(
        runner.fcntl,
        "flock",
        lambda *_: (_ for _ in ()).throw(BlockingIOError()),
    )
    assert runner.receive_supervisor({"collection_root": str(tmp_path)}) is None


def test_direct_worker_cli_boundary_has_no_capability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in (
        "SEC_XBRL_T3V2_SUPERVISOR_FD",
        "SEC_XBRL_T3V2_SUPERVISOR_PID",
        "SEC_XBRL_T3V2_SUPERVISOR_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(PermissionError, match="inherited supervisor"):
        runner.receive_supervisor({"collection_root": str(tmp_path)})


def test_heavy_lock_contention(tmp_path: Path) -> None:
    with (
        runner.heavy_lock(tmp_path),
        pytest.raises(ValueError, match="another heavy"),
        runner.heavy_lock(tmp_path),
    ):
        pass


@pytest.mark.parametrize(
    ("rss", "clocks", "expected"),
    [(2, iter((0.0, 0.0, 0.1)), "RSS_LIMIT"), (0, iter((0.0, 2.0, 2.1)), "TIMEOUT")],
)
def test_monitor_terminates_then_kills_synthetic_process(rss: int, clocks, expected: str) -> None:
    class Process:
        pid = 77

        def __init__(self) -> None:
            self.waits = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.waits += 1
            if timeout is not None:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            return -signal.SIGKILL

    process, kills = Process(), []
    result = runner.monitor_process(
        process,
        io.StringIO(),
        limit_kib=1,
        timeout_seconds=1,
        rss_reader=lambda _: rss,
        clock=lambda: next(clocks),
        sleeper=lambda _: None,
        kill_group=lambda pid, sig: kills.append((pid, sig)),
    )
    assert result[2] == expected
    assert kills == [(77, signal.SIGTERM), (77, signal.SIGKILL)]
