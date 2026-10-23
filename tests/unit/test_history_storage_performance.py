from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from sec_xbrl import history


class _JsonLineSequence(Sequence[dict[str, Any]]):
    def __init__(self, path: Path, rows: list[dict[str, Any]]) -> None:
        self.path = path
        self.count = len(rows)
        self.iterations = 0
        self.decodes = 0
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> dict[str, Any]:
        raise TypeError("sequential fixture")

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.iterations += 1
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                self.decodes += 1
                yield json.loads(line)


def _decoded(path: Path, json_fields: list[str]) -> list[dict[str, Any]]:
    import polars as pl

    return [
        {
            key: json.loads(value)
            if key in json_fields and value is not None
            else value
            for key, value in row.items()
        }
        for row in pl.read_parquet(path).to_dicts()
    ]


def test_disk_sequence_uses_two_scans_and_preserves_late_json_values(
    tmp_path: Path,
) -> None:
    leading: list[Any] = [7, True, 1.25, "text", None]
    rows = [
        {
            "id": index,
            "late_json": leading[index] if index < len(leading) else None,
            **({"sparse": "present"} if index == 1 else {}),
        }
        for index in range(history._RECORD_WRITE_BATCH_SIZE)
    ]
    rows.extend(
        (
            {"id": history._RECORD_WRITE_BATCH_SIZE, "late_json": {"k": [1, None]}},
            {"id": history._RECORD_WRITE_BATCH_SIZE + 1, "late_json": [False, 3.5]},
        )
    )

    first_records = _JsonLineSequence(tmp_path / "first.jsonl", rows)
    first_path = tmp_path / "first.parquet"
    first = history._write_records(first_path, first_records)
    second_records = _JsonLineSequence(tmp_path / "second.jsonl", rows)
    second_path = tmp_path / "second.parquet"
    second = history._write_records(second_path, second_records)

    assert first_records.iterations == second_records.iterations == 2
    assert first_records.decodes == second_records.decodes == 2 * len(rows)
    assert first == second
    assert first["json_fields"] == ["late_json"]
    expected = [{**row, "sparse": row.get("sparse")} for row in rows]
    assert _decoded(first_path, first["json_fields"]) == expected
    assert first_path.read_bytes() == second_path.read_bytes()


def test_late_json_extreme_integer_uses_compatibility_fallback(tmp_path: Path) -> None:
    rows = (
        [{"id": 0, "late_json": 2**200}]
        + [
            {"id": index, "late_json": None}
            for index in range(1, history._RECORD_WRITE_BATCH_SIZE)
        ]
        + [{"id": history._RECORD_WRITE_BATCH_SIZE, "late_json": {"exact": True}}]
    )
    records = _JsonLineSequence(tmp_path / "overflow.jsonl", rows)
    path = tmp_path / "overflow.parquet"

    info = history._write_records(path, records)

    assert records.iterations == 3
    assert records.decodes == 3 * len(rows)
    assert _decoded(path, info["json_fields"]) == rows


def test_encoding_failure_cleans_bounded_workspace(tmp_path: Path) -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    path = tmp_path / "cyclic.parquet"

    with pytest.raises(ValueError, match="Circular reference detected"):
        history._write_records(path, ({"nested": cycle},))

    assert not path.exists()
    assert not list(tmp_path.glob(".cyclic.parquet.chunks-*"))


def test_empty_records_keep_empty_contract(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"

    info = history._write_records(path, ())

    assert info["count"] == 0
    assert info["json_fields"] == []
    assert _decoded(path, []) == []
