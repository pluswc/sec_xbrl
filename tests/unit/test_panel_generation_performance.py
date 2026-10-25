from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from sec_xbrl import history
from sec_xbrl.analytics.fiscal_time_series import (
    FiscalTimeSeriesError,
    FiscalTimeSeriesSpilledResult,
    _FiscalTimeSeriesSpill,
    _SpilledRecordSequence,
)


class _IntegrityProbe:
    def __init__(self) -> None:
        self.calls = 0

    def verify_integrity(self) -> None:
        self.calls += 1


class _SpilledFixture:
    def __init__(self, rows: tuple[dict[str, Any], ...]) -> None:
        self.rows = rows
        self.counts = {"cells": len(rows)}
        self._closed = False
        self._spill = _IntegrityProbe()
        self.iterations = 0

    def _records_unverified(self, name: str):
        assert name == "cells"
        self.iterations += 1
        yield from self.rows


def _decode(path: Path, json_fields: list[str]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            key: json.loads(value)
            if key in json_fields and value is not None
            else value
            for key, value in row.items()
        }
        for row in pl.read_parquet(path).to_dicts()
    )


def _rich_rows() -> tuple[dict[str, Any], ...]:
    rows = []
    for index in range(history._RECORD_WRITE_BATCH_SIZE + 2):
        if index == 0:
            late: Any = True
        elif index == 1:
            late = 2**80
        elif index == 2:
            late = None
        elif index == history._RECORD_WRITE_BATCH_SIZE:
            late = {"nested": [False, None, "한글"]}
        elif index == history._RECORD_WRITE_BATCH_SIZE + 1:
            late = (Decimal("1.2300"), date(2026, 10, 24))
        else:
            late = index
        rows.append(
            {
                "id": f"row-{index:03d}",
                "late": late,
                "large": 2**63 + index,
                "decimal": Decimal("12.3400"),
                "day": date(2026, 10, 24),
                "unicode": "정확한 값",
                "nullable": None,
            }
        )
    return tuple(rows)


def test_spilled_staging_reads_expensive_source_once_and_matches_eager_output(
    tmp_path: Path,
) -> None:
    rows = _rich_rows()
    original_rows = deepcopy(rows)
    eager_path = tmp_path / "eager.parquet"
    eager = history._finalize_staged_records(
        history._stage_records(eager_path, rows)
    )
    fixture = _SpilledFixture(rows)
    sequence = _SpilledRecordSequence(fixture, "cells")
    spilled_path = tmp_path / "spilled.parquet"

    plan = history._stage_records(spilled_path, sequence)
    spool_bytes = plan.spool_bytes
    assert not list(tmp_path.glob(".spilled.parquet.chunks-*/typed-records.spool"))
    spilled = history._finalize_staged_records(plan)

    assert fixture.iterations == 1
    assert fixture._spill.calls == 1
    assert spool_bytes > 0
    assert spilled == eager
    assert pl.read_parquet_schema(spilled_path) == pl.read_parquet_schema(eager_path)
    assert spilled_path.read_bytes() == eager_path.read_bytes()
    assert _decode(spilled_path, spilled["json_fields"]) == _decode(
        eager_path, eager["json_fields"]
    )
    assert spilled["json_fields"] == ["late"]
    assert rows == original_rows


@pytest.mark.parametrize("mutation", ("header", "truncate", "append", "reorder"))
def test_typed_stage_spool_detects_mutation(tmp_path: Path, mutation: str) -> None:
    spool = history._TypedStageRecordSpool(tmp_path)
    spool.append({"id": "aaaa", "nested": {"exact": Decimal("1.20")}})
    spool.append({"id": "bbbb", "nested": {"exact": Decimal("1.20")}})
    spool.seal()
    try:
        assert spool.fd is not None
        if mutation == "header":
            os.pwrite(spool.fd, b"X", 0)
        elif mutation == "truncate":
            os.ftruncate(spool.fd, spool.byte_count - 1)
        elif mutation == "reorder":
            start = len(history._TYPED_STAGE_SPOOL_MAGIC)
            first_size = int.from_bytes(os.pread(spool.fd, 8, start), "big") + 40
            second_start = start + first_size
            second_size = int.from_bytes(os.pread(spool.fd, 8, second_start), "big") + 40
            assert first_size == second_size
            first = os.pread(spool.fd, first_size, start)
            second = os.pread(spool.fd, second_size, second_start)
            os.pwrite(spool.fd, second + first, start)
        else:
            os.pwrite(spool.fd, b"X", spool.byte_count)
        with pytest.raises(ValueError, match="spool"):
            tuple(spool)
    finally:
        spool.close()
        spool.path.unlink(missing_ok=True)


def test_typed_stage_spool_constructor_failure_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(_fd: int, _payload: Any) -> int:
        raise OSError("injected header failure")

    monkeypatch.setattr(history.os, "write", fail_write)
    with pytest.raises(OSError, match="injected header failure"):
        history._TypedStageRecordSpool(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ("file", "symlink"))
def test_typed_stage_spool_exclusive_collision_preserves_foreign_path(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "typed-records.spool"
    target = tmp_path / "foreign-target"
    target.write_bytes(b"foreign-content")
    if kind == "file":
        path.write_bytes(b"foreign-content")
    else:
        path.symlink_to(target)

    with pytest.raises(FileExistsError):
        history._TypedStageRecordSpool(tmp_path)

    assert path.read_bytes() == b"foreign-content"
    assert target.read_bytes() == b"foreign-content"
    if kind == "symlink":
        assert path.is_symlink()


def test_typed_stage_spool_guard_rejection_preserves_preexisting_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "typed-records.spool"
    path.write_bytes(b"foreign-content")

    def reject_existing(candidate: Path | None = None) -> None:
        if candidate is not None and candidate.exists():
            raise ValueError("guard refuses overwrite")

    token = history._HISTORY_STORAGE_GUARD.set(reject_existing)
    try:
        with pytest.raises(ValueError, match="guard refuses overwrite"):
            history._TypedStageRecordSpool(tmp_path)
    finally:
        history._HISTORY_STORAGE_GUARD.reset(token)

    assert path.read_bytes() == b"foreign-content"


def test_typed_stage_spool_constructor_path_exchange_preserves_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "typed-records.spool"
    displaced = tmp_path / "owned-displaced.spool"
    opened_fd: int | None = None

    def exchange_then_fail(fd: int, _payload: Any) -> int:
        nonlocal opened_fd
        opened_fd = fd
        path.rename(displaced)
        path.write_bytes(b"foreign-replacement")
        raise OSError("injected exchanged-path write failure")

    monkeypatch.setattr(history.os, "write", exchange_then_fail)
    with pytest.raises(OSError, match="exchanged-path"):
        history._TypedStageRecordSpool(tmp_path)

    assert path.read_bytes() == b"foreign-replacement"
    assert displaced.exists()
    assert opened_fd is not None
    with pytest.raises(OSError):
        os.fstat(opened_fd)


def test_spilled_staging_constructor_failure_cleans_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _SpilledFixture(({"id": "one"},))

    def fail_init(_self: Any, _directory: Path) -> None:
        raise OSError("injected spool open failure")

    monkeypatch.setattr(history._TypedStageRecordSpool, "__init__", fail_init)
    with pytest.raises(OSError, match="injected spool open failure"):
        history._stage_records(
            tmp_path / "failed.parquet", _SpilledRecordSequence(fixture, "cells")
        )
    assert not list(tmp_path.glob(".failed.parquet.chunks-*"))


def test_spilled_staging_path_exchange_retains_foreign_workspace_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _SpilledFixture(({"id": "one"},))

    def exchange_then_fail(
        spool: history._TypedStageRecordSpool, _record: dict[str, Any]
    ) -> None:
        spool.path.rename(spool.path.with_name("owned-displaced.spool"))
        spool.path.write_bytes(b"foreign-replacement")
        raise OSError("injected staging path exchange")

    monkeypatch.setattr(history._TypedStageRecordSpool, "append", exchange_then_fail)
    with pytest.raises(OSError, match="staging path exchange"):
        history._stage_records(
            tmp_path / "failed.parquet", _SpilledRecordSequence(fixture, "cells")
        )

    workspaces = list(tmp_path.glob(".failed.parquet.chunks-*"))
    assert len(workspaces) == 1
    assert (workspaces[0] / "typed-records.spool").read_bytes() == b"foreign-replacement"
    assert (workspaces[0] / "owned-displaced.spool").exists()


def test_guarded_staging_failure_retains_diagnostic_workspace(tmp_path: Path) -> None:
    fixture = _SpilledFixture(({"id": "one", "unsupported": object()},))
    token = history._HISTORY_STORAGE_GUARD.set(lambda _path=None: None)
    try:
        with pytest.raises(FiscalTimeSeriesError, match="unsupported typed spill scalar"):
            history._stage_records(
                tmp_path / "failed.parquet", _SpilledRecordSequence(fixture, "cells")
            )
    finally:
        history._HISTORY_STORAGE_GUARD.reset(token)

    assert len(list(tmp_path.glob(".failed.parquet.chunks-*"))) == 1


def test_ordinary_sequence_keeps_existing_nonspooled_path(tmp_path: Path) -> None:
    path = tmp_path / "ordinary.parquet"
    plan = history._stage_records(path, ({"id": "one", "nested": [1, None]},))
    assert plan.spool_bytes == 0
    info = history._finalize_staged_records(plan)
    assert _decode(path, info["json_fields"]) == ({"id": "one", "nested": [1, None]},)


def test_spilled_spool_uses_path_guard_only_before_exclusive_creates(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    calls: list[Path | None] = []

    def exclusive_create_guard(path: Path | None = None) -> None:
        calls.append(path)
        if path is not None:
            assert path.resolve().is_relative_to(root)
            if path.exists():
                raise ValueError("guard refuses overwrite")

    token = history._HISTORY_STORAGE_GUARD.set(exclusive_create_guard)
    fixture = _SpilledFixture(({"id": "one", "nested": {"source": "exact"}},))
    try:
        path = tmp_path / "guarded.parquet"
        plan = history._stage_records(path, _SpilledRecordSequence(fixture, "cells"))
        info = history._finalize_staged_records(plan)
    finally:
        history._HISTORY_STORAGE_GUARD.reset(token)

    assert _decode(path, info["json_fields"]) == (
        {"id": "one", "nested": {"source": "exact"}},
    )
    assert calls.count(None) >= 3
    assert all(path is None or path.is_relative_to(tmp_path) for path in calls)


def test_original_spill_mutation_after_staging_fails_success_close(
    tmp_path: Path,
) -> None:
    spill_root = tmp_path / "source-spill"
    spill_root.mkdir()
    spill = _FiscalTimeSeriesSpill(spill_root)
    spill.add_row("row-one", {"id": "row-one", "evidence": {"source": "original"}})
    spill.checkpoint()
    result = FiscalTimeSeriesSpilledResult(
        spill=spill,
        columns=(),
        scope={"fixture": "source-mutation"},
    )
    diagnostic = result.diagnostic_path
    plan = history._stage_records(
        tmp_path / "never-published.parquet", result.dataset("rows")
    )
    payload = spill.execute("SELECT record FROM rows WHERE row_id='row-one'").fetchone()[0]
    spill.execute(
        "UPDATE rows SET record=? WHERE row_id='row-one'",
        (payload[:-1] + bytes([payload[-1] ^ 1]),),
    )
    spill.db.commit()

    with pytest.raises(FiscalTimeSeriesError, match="payload changed"):
        result.close(success=True)

    plan.cleanup()
    assert diagnostic.exists()
    assert not (tmp_path / "never-published.parquet").exists()
