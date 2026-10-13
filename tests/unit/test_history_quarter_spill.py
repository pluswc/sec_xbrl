from __future__ import annotations

import gc
import sys
import weakref
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import polars as pl
import pytest
from test_history_quarters import _cell
from test_history_recovery import _recovery_fixture

from sec_xbrl import history
from sec_xbrl.analytics import history_quarters as quarters


def test_spill_order_types_overwrite_and_duplicate_groups(tmp_path):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        rows = spill.mapping()
        key = sys.intern("source-key")
        rows[key] = {"version": 1}
        rows["second"] = {"version": 2}
        rows["".join(["source", "-key"])] = {"version": 3}  # noqa: FLY002 -- noninterned key
        assert list(rows) == [key, "second"]
        assert list(rows.values()) == [{"version": 3}, {"version": 2}]
        groups = quarters._SpillGroups(spill)
        group_key = (2026, "FY", '[null,"case-sensitive"]')
        value = {"large": 2**63-1, "bool": True, "float": 1.25,
                 "bytes": b"abc", "tuple": (1, None), "list": [1, None]}
        groups.setdefault(group_key).append(value)
        groups.setdefault(group_key).append(value)
        assert list(groups.get(group_key)) == [value, value]
        assert len(groups.get(group_key)) == 2
        assert next(iter(groups.items()))[0] == group_key
        with pytest.raises(IndexError):
            groups.get(group_key)[-3]
    finally:
        spill.close()


def test_replay_writer_global_schema_json_and_exact_integer(tmp_path):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        records = tuple({"n": 2**60+index, "late": (True if index < 32 else {"nested": [None, index]}),
                         "promoted": (2**60+index if index < 32 else "text"),
                         "floating": 1.25, "flag": False} for index in range(65))
        replay = spill.sequence()
        for record in records:
            replay.append(record)
        expected = history._write_records(tmp_path / "eager.parquet", records)
        actual = history._finalize_staged_records(history._stage_records(tmp_path / "spill.parquet", replay))
        assert actual == expected
        assert pl.read_parquet_schema(tmp_path / "spill.parquet") == pl.read_parquet_schema(tmp_path / "eager.parquet")
        assert tuple(history._iter_history_records(tmp_path / "spill.parquet", actual)) == tuple(history._iter_history_records(tmp_path / "eager.parquet", expected))
    finally:
        spill.close()


def test_streamed_repartition_preserves_large_all_fields_without_eager_load(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    reader = history.HistoryPublicationReader(kwargs["staged_publication"], allow_staging=True)
    table = reader.manifest["tables"][0]
    path = reader.root / table["files"]["cells"]["path"]
    # Independently generated complete source rows, including large unused
    # candidate evidence which the producer must retain rather than project.
    rows = tuple({"fiscal_time_series_cell_id": f"cell-{i}", "fiscal_time_series_row_id": "row",
                  "fiscal_time_series_column_id": "column", "value_status": "UNAVAILABLE",
                  "value_lineage": None, "all_evidence": [{"index": i, "text": "x"*65536} for _ in range(4)]}
                 for i in range(97))
    table["files"]["cells"] = {**history._write_records(path, rows), "path": table["files"]["cells"]["path"]}
    monkeypatch.setattr(reader, "load", lambda **_: pytest.fail("eager quarter load"))
    spill_root = tmp_path / "spill"
    spill_root.mkdir()
    spill = quarters._QuarterSpill(spill_root)
    refs = []
    iterator = quarters._iter_history_records
    class Tracked(dict):
        pass
    def tracked(path, info):
        for record in iterator(path, info):
            if path.name == "cells.parquet":
                record = Tracked(record)
                refs.append(weakref.ref(record))
            yield record
    monkeypatch.setattr(quarters, "_iter_history_records", tracked)
    checkpoint = spill.checkpoint
    def checked():
        gc.collect()
        assert sum(ref() is not None for ref in refs) <= 1
        checkpoint()
    monkeypatch.setattr(spill, "checkpoint", checked)
    try:
        targets, materialized = {}, {}
        quarters._spill_reported_table(reader, table, reader.root, spill.mapping(), targets,
                                       materialized, defaultdict(int), spill, {})
        gc.collect()
        assert all(ref() is None for ref in refs)
        target = next(iter(targets.values()))
        actual = list(target["cells"])
        for before, after in zip(rows, actual, strict=True):
            assert after["all_evidence"] == before["all_evidence"]
            assert after["fiscal_time_series_cell_id"] == quarters._id("reclassified-cell", before["fiscal_time_series_cell_id"], quarters.PERIOD_RULE)
        assert len(actual) == 97
        assert len(materialized[next(iter(targets))]) == 1
        assert spill.path.stat().st_size > 20*1024*1024
    finally:
        spill.close()


@pytest.mark.parametrize("fault", [None, "duplicate_later", "duplicate_earlier", "materialized_unavailable"])
def test_spilled_derivation_matches_full_legacy_evidence_and_ambiguity(tmp_path, monkeypatch, fault):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        key = ("EXAMPLE", "AS_FILED", "QTD_3M")
        later = _cell("FY", "100", "2026-01-01")
        earlier = _cell("YTD_9M", "70", "2025-10-01")
        for cell in (later, earlier):
            cell.update(fiscal_time_series_row_id="row", definition={"analysis_line_id": "line"})
        column = {"fiscal_year_end_as_filed": "--12-31", "fiscal_quarter": 4}
        row = {"fiscal_time_series_row_id": "row", "all": {"nested": [None, 2**60]}}
        lookup = {"later": (later, column, row), "earlier": (earlier, column, row)}
        monkeypatch.setattr(quarters, "_resolve_additive_locator", lambda ref: deepcopy(lookup[ref]))
        monkeypatch.setattr(spill, "resolve", lambda ref: deepcopy(lookup[ref]))
        group = {(2025, "FY", "scope"): ["later"], (2025, "YTD_9M", "scope"): ["earlier"]}
        if fault == "duplicate_later":
            group[2025, "FY", "scope"].append("later")
        if fault == "duplicate_earlier":
            group[2025, "YTD_9M", "scope"].append("earlier")
        blocked = {("row", quarters._id("column", (2025, 4, "QTD_3M")))} if fault == "materialized_unavailable" else set()
        old_target = {"table": {"cik": "123"}, "extra_rows": {}, "extra_columns": {}, "extra_cells": []}
        expected = quarters._derive_quarter_targets({key: old_target}, {key[:2]: group}, {key: blocked})
        disk_group = quarters._SpillGroups(spill)
        for group_key, choices in group.items():
            for choice in choices:
                disk_group.setdefault(group_key).append(choice)
        new_target = {"table": {"cik": "123"}, "extra_rows": spill.mapping(), "extra_columns": spill.mapping(), "extra_cells": spill.sequence()}
        materialized = spill.mapping()
        for pair in blocked:
            materialized[pair] = None
        actual = quarters._derive_quarter_targets({key: new_target}, {key[:2]: disk_group}, {key: materialized}, spill)
        assert list(actual) == expected
        assert list(new_target["extra_cells"]) == old_target["extra_cells"]
        assert dict(new_target["extra_rows"]) == old_target["extra_rows"]
        assert dict(new_target["extra_columns"]) == old_target["extra_columns"]
        assert len(actual) == (1 if fault is None else 0)
    finally:
        spill.close()


def test_spill_preserves_temporal_decimal_and_python_key_equality(tmp_path):
    spill = quarters._QuarterSpill(tmp_path)
    try:
        rows = spill.mapping()
        value = {"day": date(2026, 1, 2), "timestamp": datetime(2026, 1, 2, tzinfo=UTC),
                 "time": time(12, 13, 14), "delta": timedelta(days=1, microseconds=3),
                 "amount": Decimal("12345678901234567890.00100"), "tuple": (True, None)}
        rows[True] = value
        assert rows[1] == value == rows[1.0]
        assert {key: type(item) for key, item in rows[1].items()} == {key: type(item) for key, item in value.items()}
        rows[1.0] = value
        assert type(next(iter(rows))) is bool  # dict preserves the original equal key.
        rows["1"] = "distinct string"
        assert len(rows) == 2
    finally:
        spill.close()


@pytest.mark.parametrize("replacement", ["database", "directory"])
def test_spill_rejects_replaced_owned_paths_without_touching_foreign_files(tmp_path, replacement):
    root = tmp_path / "owned"
    root.mkdir()
    spill = quarters._QuarterSpill(root)
    rows = spill.mapping()
    rows["owned"] = [1]
    spill.checkpoint()
    try:
        if replacement == "database":
            spill.path.rename(root / "moved.sqlite")
            spill.path.write_bytes(b"unrelated database sentinel")
            sentinel = spill.path
        else:
            root.rename(tmp_path / "moved")
            root.mkdir()
            sentinel = root / "keep"
            sentinel.write_bytes(b"unrelated directory sentinel")
        before = sentinel.read_bytes()
        with pytest.raises(ValueError, match="ownership changed"):
            rows["must not write"] = [2]
        assert sentinel.read_bytes() == before
        with pytest.raises(ValueError, match="ownership changed"):
            del rows["owned"]
    finally:
        spill.close()
    assert sentinel.read_bytes() == before


def test_failed_spilled_recovery_retains_diagnostics_and_default_deny(tmp_path, monkeypatch):
    kwargs, _ = _recovery_fixture(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in kwargs["staged_publication"].rglob("*") if p.is_file()}
    def fail(*args):
        raise ValueError("synthetic assembly interruption")
    monkeypatch.setattr(quarters, "_assemble_spilled_table", fail)
    with pytest.raises(ValueError, match="synthetic assembly"):
        history.recover_reported_history(**kwargs)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert list(kwargs["output_root"].glob(".panels.partial-*/.chunks/quarter-spill.sqlite"))
    assert not (kwargs["output_root"] / "reported_recovery_receipt.json").exists()
    with pytest.raises(ValueError, match="NOT_READY"):
        history.HistoryPublicationReader(kwargs["output_root"] / "reported-panels")
