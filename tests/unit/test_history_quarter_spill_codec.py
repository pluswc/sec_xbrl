from __future__ import annotations

import hashlib
import math
import os
import random
import sqlite3
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from sec_xbrl.analytics import history_quarters as quarters


def _physical_value(spill: quarters._QuarterSpill, ordinal: int = 1) -> bytes:
    value = spill.db.execute(
        "SELECT hex(value) AS physical_value FROM records WHERE ordinal=?", (ordinal,)
    ).fetchone()[0]
    return bytes.fromhex(value)


def _journal_payloads(path: Path) -> list[bytes]:
    result = []
    with path.open("rb") as source:
        while header := source.read(40):
            assert len(header) == 40
            size = int.from_bytes(header[:8], "big")
            payload = source.read(size)
            assert len(payload) == size
            assert hashlib.sha256(payload).digest() == header[8:]
            result.append(payload)
    return result


def _unlinked_file_sizes() -> dict[tuple[int, int], int]:
    result = {}
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            status = os.stat(descriptor)
        except OSError:
            continue
        if status.st_nlink == 0:
            result[(status.st_dev, status.st_ino)] = status.st_size
    return result


def test_codec_preserves_supported_types_and_all_mapping_sequence_paths(tmp_path: Path) -> None:
    spill = quarters._QuarterSpill(tmp_path)
    try:
        mapping = spill.mapping()
        timestamp = datetime(2026, 10, 24, 1, 2, 3, 4, tzinfo=UTC, fold=1)
        value = {
            "int": 2**100,
            "bool": True,
            "float": 1.2345678901234567,
            "negative_zero": -0.0,
            "bytes": b"\x00typed\xff",
            "tuple": (1, False, None),
            "list": [Decimal("1234567890.000100"), date(2026, 10, 24)],
            "time": time(12, 34, 56, 789),
            "datetime": timestamp,
            "timedelta": timedelta(days=3, seconds=5, microseconds=7),
        }
        mapping[True] = value
        first_ordinal = spill.db.execute(
            "SELECT ordinal FROM records WHERE bucket=?", (mapping.bucket,)
        ).fetchone()[0]
        mapping[1.0] = value
        assert spill.db.execute(
            "SELECT ordinal FROM records WHERE bucket=?", (mapping.bucket,)
        ).fetchone()[0] == first_ordinal
        mapping["second"] = {"payload": "x" * 40_000}

        assert mapping[1] == value
        assert list(mapping.values()) == [value, {"payload": "x" * 40_000}]
        assert list(mapping.items()) == [
            (True, value),
            ("second", {"payload": "x" * 40_000}),
        ]
        sequence = mapping.records()
        assert sequence[0] == sequence[-2] == value
        assert sequence[-1] == {"payload": "x" * 40_000}
        assert sequence[:] == (value, {"payload": "x" * 40_000})
        assert timestamp.fold == sequence[0]["datetime"].fold == 1
        assert math.copysign(1.0, sequence[0]["negative_zero"]) == -1.0
        assert {key: type(item) for key, item in sequence[0].items()} == {
            key: type(item) for key, item in value.items()
        }
        del mapping["second"]
        assert list(mapping) == [True]
    finally:
        spill.close()


def test_small_raw_large_compressed_and_incompressible_fallback(tmp_path: Path, monkeypatch) -> None:
    spill = quarters._QuarterSpill(tmp_path)
    try:
        values = spill.sequence()
        values.append({"small": [1, True, None]})
        small = _physical_value(spill)
        assert small[:5] == quarters._SPILL_DB_VALUE_MAGIC + b"R"

        values.append({"large": "repeat" * 10_000})
        large = _physical_value(spill, 2)
        assert large[:5] == quarters._SPILL_DB_VALUE_MAGIC + b"Z"

        monkeypatch.setattr(quarters.zlib, "compress", lambda raw, level: raw + b"larger")
        values.append({"fallback": "x" * 40_000})
        fallback = _physical_value(spill, 3)
        assert fallback[:5] == quarters._SPILL_DB_VALUE_MAGIC + b"R"
        assert values[-1] == {"fallback": "x" * 40_000}
    finally:
        spill.close()


@pytest.mark.parametrize(
    "damage",
    ["prefix", "length-small", "length-large", "hash", "truncated", "trailing"],
)
def test_codec_rejects_malformed_or_unbounded_values(tmp_path: Path, damage: str) -> None:
    spill = quarters._QuarterSpill(tmp_path)
    try:
        values = spill.sequence()
        values.append({"large": "repeat" * 10_000})
        encoded = bytearray(_physical_value(spill))
        size_start = len(quarters._SPILL_DB_VALUE_MAGIC) + 1
        if damage == "prefix":
            encoded[0] ^= 0x01
        elif damage == "length-small":
            encoded[size_start : size_start + 8] = (1).to_bytes(8, "big")
        elif damage == "length-large":
            encoded[size_start : size_start + 8] = (
                quarters._SPILL_DB_MAX_RAW_BYTES + 1
            ).to_bytes(8, "big")
        elif damage == "hash":
            encoded[size_start + 8] ^= 0x01
        elif damage == "truncated":
            del encoded[-5:]
        else:
            encoded.extend(b"trailing")
        spill.db.execute(
            "UPDATE records SET value=? WHERE ordinal=1", (sqlite3.Binary(encoded),)
        )
        with pytest.raises(ValueError, match="private quarter spill database"):
            values[0]
    finally:
        spill.close()


def test_named_journal_keeps_exact_typed_event_framing(tmp_path: Path) -> None:
    spill = quarters._QuarterSpill(tmp_path)
    mapping = spill.mapping()
    value = {"large": "journal-stays-typed" * 3_000}
    mapping["key"] = value
    spill.checkpoint()
    path = spill.path
    sqlite_version = sqlite3.sqlite_version
    spill.close()

    events = [
        {
            "event": "OPEN",
            "version": "quarter-spill-records-v1",
            "sqlite_version": sqlite_version,
            "temp_store": "FILE",
            "cache_kib": 2048,
            "index": "anonymous-disposable",
        },
        {"event": "BUCKET", "bucket": 1},
        {
            "event": "PLANNED",
            "sequence": 1,
            "operation": "SET",
            "bucket": 1,
            "key": "key",
            "value": value,
        },
        {"event": "APPLIED", "sequence": 1, "ordinal": 1, "original_key": "key"},
        {"event": "CHECKPOINT", "sequence": 1},
    ]
    payloads = _journal_payloads(path)
    assert payloads == [quarters._spill_pack(event) for event in events]
    assert [quarters._spill_unpack(payload) for payload in payloads] == events


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux /proc descriptors")
def test_incompressible_value_uses_anonymous_disk_beyond_cache(tmp_path: Path) -> None:
    before = _unlinked_file_sizes()
    payload = random.Random(20261024).randbytes(3 * 1024 * 1024)
    spill = quarters._QuarterSpill(tmp_path)
    try:
        values = spill.sequence()
        values.append({"payload": payload})
        values.append({"payload": payload[::-1]})
        spill.checkpoint()

        assert _physical_value(spill)[:5] == quarters._SPILL_DB_VALUE_MAGIC + b"R"
        assert values[0] == {"payload": payload}
        assert values[-1] == {"payload": payload[::-1]}
        after = _unlinked_file_sizes()
        new_sizes = [size for identity, size in after.items() if identity not in before]
        assert max(new_sizes, default=0) > 2 * 1024 * 1024
        assert spill.path.stat().st_size > 6 * 1024 * 1024
    finally:
        spill.close()
