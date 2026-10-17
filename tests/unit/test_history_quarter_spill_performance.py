from __future__ import annotations

import hashlib
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


def test_full_path_validation_count_scales_with_guarded_boundaries(tmp_path, monkeypatch):
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

        # One bucket journal check, five checks at each mutation's public,
        # PLANNED, INSERT, SELECT, and APPLIED boundaries, one streaming query,
        # and one full check before every yielded item.
        assert exercise(32) == 194
        assert exercise(128) == 770
    finally:
        spill.close()


def test_items_stream_uses_one_validated_sql_operation(tmp_path, monkeypatch):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        records = spill.mapping()
        for index in range(64):
            records[("row", index)] = {"id": f"cell-{index}"}
        original_execute = spill.execute
        sql: list[str] = []

        def counted_execute(statement, parameters=()):
            sql.append(statement)
            return original_execute(statement, parameters)

        monkeypatch.setattr(spill, "execute", counted_execute)
        assert [value["id"] for _, value in records.items()] == [f"cell-{index}" for index in range(64)]
        assert len(sql) == 1
        assert "ORDER BY ordinal" in sql[0]
    finally:
        spill.close()


def test_mutation_rejects_ancestor_exchange_after_plan_before_sql(tmp_path, monkeypatch):
    ancestor = tmp_path / "owned"
    directory = ancestor / "leaf"
    directory.mkdir(parents=True)
    spill = quarters._QuarterSpill(directory)
    records = spill.mapping()
    original_append = spill._append_event
    retained_ancestor = tmp_path / "retained-owned"
    foreign = spill.path
    sentinel = b"foreign replacement sentinel"

    def exchange_after_plan(event):
        original_append(event)
        if event["event"] == "PLANNED":
            ancestor.rename(retained_ancestor)
            directory.mkdir(parents=True)
            foreign.write_bytes(sentinel)

    monkeypatch.setattr(spill, "_append_event", exchange_after_plan)
    try:
        with pytest.raises(ValueError, match="ownership changed"):
            records[("row", 1)] = {"id": "must-not-apply"}
        assert spill.db.execute("SELECT count(*) FROM records").fetchone() == (0,)
        assert foreign.read_bytes() == sentinel
        journal = retained_ancestor / "leaf" / "quarter-spill.records"
        events = []
        with journal.open("rb") as source:
            while header := source.read(40):
                assert len(header) == 40
                payload = source.read(int.from_bytes(header[:8], "big"))
                assert hashlib.sha256(payload).digest() == header[8:]
                events.append(quarters._spill_unpack(payload))
        assert [event["event"] for event in events] == ["OPEN", "BUCKET", "PLANNED"]
    finally:
        spill.close()
    assert foreign.read_bytes() == sentinel


@pytest.mark.parametrize("attack", ["replacement", "symlink", "ancestor"])
def test_items_rejects_owned_journal_exchange_between_yields(tmp_path, attack):
    ancestor = tmp_path / "owned"
    directory = ancestor / "leaf"
    directory.mkdir(parents=True)
    spill = quarters._QuarterSpill(directory)
    records = spill.mapping()
    records[("row", 1)] = {"id": "first"}
    records[("row", 2)] = {"id": "must-not-return"}
    iterator = iter(records.items())
    assert next(iterator) == (("row", 1), {"id": "first"})

    retained = directory / "retained-quarter-spill.records"
    foreign = tmp_path / "foreign-sentinel"
    sentinel = b"foreign replacement sentinel"
    if attack == "ancestor":
        ancestor.rename(tmp_path / "retained-owned")
        directory.mkdir(parents=True)
        spill.path.write_bytes(sentinel)
    else:
        spill.path.rename(retained)
        if attack == "replacement":
            spill.path.write_bytes(sentinel)
        else:
            foreign.write_bytes(sentinel)
            spill.path.symlink_to(foreign)
    foreign_entry = foreign if attack == "symlink" else spill.path

    try:
        with pytest.raises(ValueError, match="ownership changed"):
            next(iterator)
        assert foreign_entry.read_bytes() == sentinel
    finally:
        spill.close()
    assert foreign_entry.read_bytes() == sentinel
