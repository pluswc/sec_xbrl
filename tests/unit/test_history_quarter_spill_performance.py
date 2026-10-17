from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from sec_xbrl.analytics import history_quarters as quarters


def test_quarter_progress_adds_nonnegative_monotonic_timing(capsys, monkeypatch):
    monkeypatch.setattr(quarters, "monotonic", lambda: 105.25)
    quarters._quarter_progress(
        "QUARTER_SPILL_FLUSH",
        {"ticker": "SYNTHETIC", "view": "AS_FILED", "period_class": "YTD_6M"},
        32,
        100.0,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "stage": "QUARTER_SPILL_FLUSH",
        "ticker": "SYNTHETIC",
        "view": "AS_FILED",
        "period_class": "YTD_6M",
        "records": 32,
        "process_maxrss_kib": payload["process_maxrss_kib"],
        "monotonic_seconds": 105.25,
        "elapsed_seconds": 5.25,
    }
    assert payload["process_maxrss_kib"] >= 0
    assert payload["elapsed_seconds"] >= 0


def test_spill_optimized_path_matches_python_mapping_order_and_typed_values(tmp_path):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        actual = spill.mapping()
        expected = {}
        operations = (
            ("set", ("row", 1), {"id": "cell-1", "value": Decimal("10.500"), "day": date(2026, 1, 2)}),
            ("set", ("row", 2), {"id": "cell-2", "timestamp": datetime(2026, 1, 2, tzinfo=UTC)}),
            ("set", ("row", 1), {"id": "cell-1-recast", "typed": (True, None, b"raw")}),
            ("delete", ("row", 2), None),
            ("set", ("row", 2), {"id": "cell-2-reinserted", "nested": [1, False]}),
        )
        for operation, key, value in operations:
            if operation == "set":
                actual[key] = value
                expected[key] = value
            else:
                del actual[key]
                del expected[key]

        assert list(actual.items()) == list(expected.items())
        assert list(actual) == list(expected)
        assert list(actual.values()) == list(expected.values())
        assert {key: type(value) for key, value in actual[("row", 1)].items()} == {
            key: type(value) for key, value in expected[("row", 1)].items()
        }
    finally:
        spill.close()


def test_full_path_validation_count_scales_once_per_public_operation(tmp_path, monkeypatch):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        original_check = spill.check
        calls = 0

        def counted_check():
            nonlocal calls
            calls += 1
            return original_check()

        monkeypatch.setattr(spill, "check", counted_check)

        def exercise(count: int) -> int:
            before = calls
            records = spill.mapping()
            for index in range(count):
                records[("row", index)] = {"id": f"cell-{index}", "value": index}
            assert len(list(records.items())) == count
            return calls - before

        assert exercise(32) == 34  # bucket journal + mutations + one streaming read
        assert exercise(128) == 130
    finally:
        spill.close()


def test_items_stream_uses_one_validated_sql_operation(tmp_path, monkeypatch):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        records = spill.mapping()
        for index in range(64):
            records[("row", index)] = {"id": f"cell-{index}"}
        original_execute = spill._execute
        sql: list[str] = []

        def counted_execute(statement, parameters=()):
            sql.append(statement)
            return original_execute(statement, parameters)

        monkeypatch.setattr(spill, "_execute", counted_execute)
        assert [value["id"] for _, value in records.items()] == [f"cell-{index}" for index in range(64)]
        assert len(sql) == 1
        assert "ORDER BY ordinal" in sql[0]
    finally:
        spill.close()


def test_mutation_detects_owned_path_exchange_between_plan_and_sql(tmp_path, monkeypatch):
    spill = quarters._QuarterSpill(tmp_path)
    records = spill.mapping()
    original_write = spill._write_event
    replacement = spill.path
    moved = tmp_path / "owned-quarter-spill.records"

    def exchange_after_plan(event):
        original_write(event)
        if event["event"] == "PLANNED":
            replacement.rename(moved)
            replacement.write_bytes(b"foreign replacement sentinel")

    monkeypatch.setattr(spill, "_write_event", exchange_after_plan)
    try:
        with pytest.raises(ValueError, match="directory entries changed"):
            records[("row", 1)] = {"id": "must-not-apply"}
        assert spill.db.execute("SELECT count(*) FROM records").fetchone() == (0,)
        assert replacement.read_bytes() == b"foreign replacement sentinel"
    finally:
        spill.close()
    assert replacement.read_bytes() == b"foreign replacement sentinel"
