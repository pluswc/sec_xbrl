from __future__ import annotations

import ctypes
import fcntl
import json
import os
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tools import universe50_history_recovery_ops as runner

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="shared C lease contract uses Linux flock and proc identity",
)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _lease_controls(tmp_path: Path) -> tuple[Path, Path, Path]:
    resource_root = tmp_path / "collection"
    resource_root.mkdir()
    lock_path = resource_root / ".one-heavy.lock"
    lock_path.touch()
    config = _write(tmp_path / "config.json", {"resource_root": str(resource_root)})
    go = _write(tmp_path / "go.json", {"status": "GO"})
    return config, go, lock_path


def _capability(
    config: Path,
    go: Path,
    lease_fd: int,
    *,
    parent_pid: int | None = None,
) -> dict[str, object]:
    parent_pid = os.getpid() if parent_pid is None else parent_pid
    descriptor = os.fstat(lease_fd)
    return {
        "schema_version": runner.SHARED_C_LEASE_VERSION,
        "operation": "recover-history-one",
        "parent": {
            "pid": parent_pid,
            "birth_ticks": runner._process_birth_ticks(parent_pid),
        },
        "config": {"path": str(config.absolute()), "sha256": runner._sha256(config)},
        "go": {"path": str(go.absolute()), "sha256": runner._sha256(go)},
        "lease": {
            "path": str((config.parent / "collection/.one-heavy.lock").absolute()),
            "device": descriptor.st_dev,
            "inode": descriptor.st_ino,
            "mode": descriptor.st_mode,
        },
    }


def _borrow_once(
    config: Path,
    go: Path,
    lease_fd: int,
    capability: dict[str, object] | bytes,
    *,
    replay: bool = False,
) -> str:
    capability_read, capability_write = os.pipe()
    result_read, result_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(capability_write)
            os.close(result_read)
            os.environ.update(
                {
                    runner.SHARED_C_LEASE_ENV["lease_fd"]: str(lease_fd),
                    runner.SHARED_C_LEASE_ENV["capability_fd"]: str(capability_read),
                    runner.SHARED_C_LEASE_ENV["parent_pid"]: str(os.getppid()),
                }
            )
            try:
                with runner._borrowed_c_lease(config, go) as received:
                    result = f"PASS:{received}"
                if replay:
                    try:
                        with runner._borrowed_c_lease(config, go):
                            result += ":REPLAYED"
                    except Exception as exc:  # noqa: BLE001 - report typed replay rejection
                        result += f":REPLAY_{type(exc).__name__}"
            except Exception as exc:  # noqa: BLE001 - child returns a typed rejection
                result = f"{type(exc).__name__}:{exc}"
            os.write(result_write, result.encode())
            os._exit(0)
        except BaseException:  # noqa: BLE001 - child reports only through its exit status
            os._exit(71)
    os.close(capability_read)
    os.close(result_write)
    try:
        encoded = (
            capability
            if isinstance(capability, bytes)
            else json.dumps(capability, sort_keys=True).encode()
        )
        os.write(capability_write, encoded)
    finally:
        os.close(capability_write)
    result = os.read(result_read, 8192).decode()
    os.close(result_read)
    waited, status = os.waitpid(pid, 0)
    assert waited == pid
    assert os.waitstatus_to_exitcode(status) == 0
    return result


def _locked_descriptor(lock_path: Path) -> int:
    descriptor = os.open(lock_path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def test_real_borrowed_descriptor_proves_parent_lock_and_decimal_inode(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        capability = _capability(config, go, lease_fd)
        assert capability["lease"]["inode"] == os.fstat(lease_fd).st_ino  # type: ignore[index]
        assert _borrow_once(config, go, lease_fd, capability) == f"PASS:{lease_fd}"
    finally:
        os.close(lease_fd)


def test_consumed_capability_cannot_fall_back_or_replay(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        capability = _capability(config, go, lease_fd)
        assert _borrow_once(config, go, lease_fd, capability, replay=True) == (
            f"PASS:{lease_fd}:REPLAY_PermissionError"
        )
    finally:
        os.close(lease_fd)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "operation",
        "parent_pid",
        "parent_birth",
        "config_path",
        "config_hash",
        "go_path",
        "go_hash",
        "lease_path",
        "lease_device",
        "lease_inode",
        "lease_mode",
        "missing",
        "extra",
    ],
)
def test_forged_capability_fields_reject(
    tmp_path: Path,
    mutation: str,
) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        capability = _capability(config, go, lease_fd)
        if mutation == "schema":
            capability["schema_version"] = "wrong"
        elif mutation == "operation":
            capability["operation"] = "audit"
        elif mutation == "parent_pid":
            capability["parent"]["pid"] += 1  # type: ignore[index,operator]
        elif mutation == "parent_birth":
            capability["parent"]["birth_ticks"] += 1  # type: ignore[index,operator]
        elif mutation == "config_path":
            capability["config"]["path"] = str(tmp_path / "other")  # type: ignore[index]
        elif mutation == "config_hash":
            capability["config"]["sha256"] = "0" * 64  # type: ignore[index]
        elif mutation == "go_path":
            capability["go"]["path"] = str(tmp_path / "other")  # type: ignore[index]
        elif mutation == "go_hash":
            capability["go"]["sha256"] = "0" * 64  # type: ignore[index]
        elif mutation == "lease_path":
            capability["lease"]["path"] = str(tmp_path / "other")  # type: ignore[index]
        elif mutation == "lease_device":
            capability["lease"]["device"] += 1  # type: ignore[index,operator]
        elif mutation == "lease_inode":
            capability["lease"]["inode"] += 1  # type: ignore[index,operator]
        elif mutation == "lease_mode":
            capability["lease"]["mode"] ^= 0o100  # type: ignore[index,operator]
        elif mutation == "missing":
            del capability["go"]
        else:
            capability["unexpected"] = True
        assert _borrow_once(config, go, lease_fd, capability).startswith("PermissionError:")
    finally:
        os.close(lease_fd)


@pytest.mark.parametrize("changed", ["config", "go"])
def test_capability_rejects_control_bytes_changed_after_issue(tmp_path: Path, changed: str) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        capability = _capability(config, go, lease_fd)
        target = config if changed == "config" else go
        target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
        assert _borrow_once(config, go, lease_fd, capability).startswith("PermissionError:")
    finally:
        os.close(lease_fd)


def test_same_inode_unlocked_description_rejects(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    locked_fd = _locked_descriptor(lock_path)
    other_description = os.open(lock_path, os.O_RDONLY)
    try:
        capability = _capability(config, go, other_description)
        result = _borrow_once(config, go, other_description, capability)
        assert result.startswith("PermissionError:shared C descriptor is not")
    finally:
        os.close(other_description)
        os.close(locked_fd)


def test_symlinked_c_path_rejects_even_when_target_descriptor_is_locked(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    target = tmp_path / "foreign-lock-name"
    lock_path.rename(target)
    lock_path.symlink_to(target)
    lease_fd = _locked_descriptor(target)
    try:
        capability = _capability(config, go, lease_fd)
        assert _borrow_once(config, go, lease_fd, capability).startswith(
            "PermissionError:shared C lease path is not canonical"
        )
    finally:
        os.close(lease_fd)


def test_unheld_descriptor_rejects(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = os.open(lock_path, os.O_RDWR)
    try:
        capability = _capability(config, go, lease_fd)
        assert _borrow_once(config, go, lease_fd, capability).startswith(
            "PermissionError:shared C lease is not held"
        )
    finally:
        os.close(lease_fd)


def test_closed_descriptor_rejects(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        capability = _capability(config, go, lease_fd)
        invalid_fd = os.sysconf("SC_OPEN_MAX") + 1
        assert _borrow_once(config, go, invalid_fd, capability).startswith(
            "PermissionError:shared C lease descriptor is unavailable"
        )
    finally:
        os.close(lease_fd)


@pytest.mark.parametrize("encoded", [b"", b"{" + b"x" * 65_536])
def test_empty_or_oversized_capability_rejects(tmp_path: Path, encoded: bytes) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    try:
        assert _borrow_once(config, go, lease_fd, encoded).startswith(
            "PermissionError:shared C lease capability size differs"
        )
    finally:
        os.close(lease_fd)


def test_default_mode_and_partial_environment_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in runner.SHARED_C_LEASE_ENV.values():
        monkeypatch.delenv(variable, raising=False)
    with runner._borrowed_c_lease(tmp_path / "missing-config", tmp_path / "missing-go") as value:
        assert value is None

    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["lease_fd"], "7")
    with (
        pytest.raises(PermissionError, match="incomplete"),
        runner._borrowed_c_lease(tmp_path / "missing-config", tmp_path / "missing-go"),
    ):
        pass

    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["lease_fd"], "1")
    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["capability_fd"], "2")
    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["parent_pid"], str(os.getpid()))
    with (
        pytest.raises(PermissionError, match="parent PID differs"),
        runner._borrowed_c_lease(tmp_path / "missing-config", tmp_path / "missing-go"),
    ):
        pass


def test_capability_must_be_one_shot_pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    lease_fd = _locked_descriptor(lock_path)
    capability_file = _write(tmp_path / "capability.json", _capability(config, go, lease_fd))
    capability_fd = os.open(capability_file, os.O_RDONLY)
    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["lease_fd"], str(lease_fd))
    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["capability_fd"], str(capability_fd))
    monkeypatch.setenv(runner.SHARED_C_LEASE_ENV["parent_pid"], str(os.getppid()))
    try:
        with (
            pytest.raises(PermissionError, match="must be a pipe"),
            runner._borrowed_c_lease(config, go),
        ):
            pass
        with pytest.raises(OSError):
            os.fstat(capability_fd)
    finally:
        os.close(lease_fd)


def test_worker_environment_drops_consumed_shared_lease_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in runner.SHARED_C_LEASE_ENV.values():
        monkeypatch.setenv(variable, "forged")
    config = {
        "runner": {"checkout": str(tmp_path / "runner")},
        "engine": {"checkout": str(tmp_path / "engine")},
    }
    environment = runner._worker_environment(config, 9, b"x" * 32)
    assert all(variable not in environment for variable in runner.SHARED_C_LEASE_ENV.values())


def _stage_config(tmp_path: Path) -> dict[str, object]:
    collection = tmp_path / "collection"
    collection.mkdir()
    history_parent = tmp_path / "history"
    history_parent.mkdir()
    return {
        "resource_root": str(collection),
        "execution_root": str(tmp_path / "execution"),
        "runner": {"checkout": str(tmp_path / "runner")},
        "engine": {"checkout": str(tmp_path / "engine")},
        "collection": {"manifest": str(collection / "collection_manifest.json")},
        "target": {
            "ticker": "SYN",
            "history_parent": str(history_parent),
            "history_basename": "SYN-history-recovery-bounded-memory-v1",
            "run_version": "bounded-memory-v1",
        },
    }


def _stub_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    borrowed_fd: int | None,
) -> tuple[dict[str, object], dict[str, object]]:
    config = _stage_config(tmp_path)
    captured: dict[str, object] = {}
    inherited_token_fd: int | None = None

    @contextmanager
    def borrowed(*_args: object) -> Iterator[int | None]:
        yield borrowed_fd

    class Process:
        pid = 101

        @staticmethod
        def poll() -> int:
            return 0

    def popen(command: list[str], **kwargs: object) -> Process:
        nonlocal inherited_token_fd
        captured["command"] = command
        captured["pass_fds"] = kwargs["pass_fds"]
        inherited_token_fd = os.dup(kwargs["pass_fds"][0])  # type: ignore[index]
        return Process()

    def supervise(*_args: object, **_kwargs: object) -> tuple[int, int, None, float]:
        nonlocal inherited_token_fd
        assert inherited_token_fd is not None
        os.close(inherited_token_fd)
        inherited_token_fd = None
        paths = runner._target_paths(config)
        _write(paths["receipt"], {"status": "READY"})
        return 0, 123, None, 0.5

    monkeypatch.setattr(runner, "_borrowed_c_lease", borrowed)
    monkeypatch.setattr(runner, "_validate_go", lambda *_: config)
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.resource_ops, "supervise_owned_process", supervise)
    return config, captured


def test_run_stage_external_mode_inherits_same_fd_without_internal_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_path = tmp_path / "lease"
    lease_path.touch()
    lease_fd = os.open(lease_path, os.O_RDONLY)
    config, captured = _stub_stage(tmp_path, monkeypatch, lease_fd)
    monkeypatch.setattr(
        runner.resource_ops,
        "heavy_lock",
        lambda *_: (_ for _ in ()).throw(AssertionError("external mode reopened C")),
    )
    try:
        result = runner.run_stage(tmp_path / "config", tmp_path / "go")
        assert result == runner._target_paths(config)["receipt"]
        assert captured["pass_fds"][1] == lease_fd  # type: ignore[index]
        os.fstat(lease_fd)
    finally:
        os.close(lease_fd)


def test_run_stage_default_mode_keeps_internal_lock_and_single_token_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, captured = _stub_stage(tmp_path, monkeypatch, None)
    entered: list[Path] = []

    @contextmanager
    def heavy_lock(path: Path) -> Iterator[None]:
        entered.append(path)
        yield

    monkeypatch.setattr(runner.resource_ops, "heavy_lock", heavy_lock)
    result = runner.run_stage(tmp_path / "config", tmp_path / "go")
    assert result == runner._target_paths(config)["receipt"]
    assert entered == [Path(config["resource_root"])]
    assert len(captured["pass_fds"]) == 1  # type: ignore[arg-type]


def test_parent_death_keeps_lock_until_inherited_descriptor_exits(tmp_path: Path) -> None:
    config, go, lock_path = _lease_controls(tmp_path)
    libc = ctypes.CDLL(None, use_errno=True)
    get_subreaper = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(get_subreaper), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    status_read, status_write = os.pipe()
    release_read, release_write = os.pipe()
    keeper_pid = os.fork()
    if keeper_pid == 0:
        try:
            os.close(status_read)
            os.close(release_write)
            lease_fd = _locked_descriptor(lock_path)
            capability_read, capability_write = os.pipe()
            validated_read, validated_write = os.pipe()
            borrower_pid = os.fork()
            if borrower_pid == 0:
                try:
                    os.close(capability_write)
                    os.close(validated_read)
                    os.environ.update(
                        {
                            runner.SHARED_C_LEASE_ENV["lease_fd"]: str(lease_fd),
                            runner.SHARED_C_LEASE_ENV["capability_fd"]: str(capability_read),
                            runner.SHARED_C_LEASE_ENV["parent_pid"]: str(os.getppid()),
                        }
                    )
                    with runner._borrowed_c_lease(config, go):
                        os.write(validated_write, b"1")
                        os.close(validated_write)
                        os.write(status_write, f"READY:{os.getpid()}\n".encode())
                        os.read(release_read, 1)
                    os._exit(0)
                except BaseException:  # noqa: BLE001 - child reports only through exit status
                    os._exit(72)
            os.close(capability_read)
            os.close(validated_write)
            capability = _capability(config, go, lease_fd, parent_pid=os.getpid())
            os.write(capability_write, json.dumps(capability, sort_keys=True).encode())
            os.close(capability_write)
            assert os.read(validated_read, 1) == b"1"
            os.close(validated_read)
            os.close(lease_fd)
            os._exit(0)
        except BaseException:  # noqa: BLE001 - child reports only through exit status
            os._exit(73)
    os.close(status_write)
    os.close(release_read)
    try:
        message = os.read(status_read, 128).decode().strip()
        assert message.startswith("READY:")
        borrower_pid = int(message.split(":", 1)[1])
        _, keeper_status = os.waitpid(keeper_pid, 0)
        assert os.waitstatus_to_exitcode(keeper_status) == 0

        contender = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender)

        os.write(release_write, b"x")
        os.close(release_write)
        release_write = -1
        _, borrower_status = os.waitpid(borrower_pid, 0)
        assert os.waitstatus_to_exitcode(borrower_status) == 0

        contender = _locked_descriptor(lock_path)
        os.close(contender)
    finally:
        os.close(status_read)
        if release_write >= 0:
            os.close(release_write)
        libc.prctl(36, get_subreaper.value, 0, 0, 0)
        for pid in (keeper_pid,):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
