from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tools import history_audit_index as storage
from tools.history_audit_index import AuditIndex, AuditIndexError, canonical_text
from tools.profile_history_audit_index import LegacyIndex


def _value(number: int, *, text: str = "reported") -> dict[str, Any]:
    return {
        "id": f"cell-{number}",
        "fiscal_time_series_column_id": "column-1",
        "value_numeric": f"1000000000000000000000000000000.{number:018d}",
        "value_text": text,
        "typed": [number, number == 0, None, -0.0, 1.2345678901234567],
        "value_lineage": {"value_text": text, "source_fact_ids": [f"fact-{number}"]},
    }


def _exercise(index: Any) -> dict[str, Any]:
    first = index.put("rows", "row-1", {"label": "first"})
    retained = index.put("rows", "row-1", {"label": "ignored"}, first=True)
    index.put("rows", "row-2", {"label": "second"})
    index.put("rows", "row-1", {"label": "updated"})
    cell = _value(1)
    column = {"id": "column-1", "year": 2025}
    row = {"id": "row-1", "label": "updated"}
    if isinstance(index, AuditIndex):
        column_ref = index.put("columns", "column-1", column)
        row_ref = index.put("source_rows", "row-1", row)
        cell_ref = index.emit("target", "cells", cell)
        index.add_candidate_refs(
            "SYN",
            "AS_FILED",
            2025,
            "FY",
            "scope",
            cell=cell_ref,
            column=column_ref,
            source_row=row_ref,
        )
    else:
        index.put("columns", "column-1", column)
        index.put("source_rows", "row-1", row)
        index.emit("target", "cells", cell)
        index.add_candidate(
            ("SYN", "AS_FILED", 2025, "FY", "scope"),
            {"cell": cell, "column": column, "source_row": row},
        )
    index.emit("__derived__", "derived", {"id": "metric-1", "value": "3.1400"})
    return {"first": first, "retained": retained}


def _trace_legacy(index: LegacyIndex) -> dict[str, Any]:
    return {
        "objects": [
            (bucket, json.loads(key), json.loads(payload), ordinal)
            for bucket, key, payload, ordinal in index.db.execute(
                "SELECT bucket,k,payload,ord FROM objects ORDER BY ord"
            )
        ],
        "expected": [
            (target, kind, json.loads(payload), ordinal)
            for target, kind, payload, ordinal in index.db.execute(
                "SELECT target,kind,payload,ordinal FROM expected ORDER BY ordinal"
            )
        ],
        "candidates": [
            (ticker, view, year, kind, scope, json.loads(payload), ordinal)
            for ticker, view, year, kind, scope, payload, ordinal in index.db.execute(
                "SELECT ticker,view,year,kind,scope,payload,ord FROM candidates ORDER BY ord"
            )
        ],
    }


def _trace_candidate(index: AuditIndex) -> dict[str, Any]:
    objects = []
    for bucket, key, payload_id, ordinal in index.db.execute(
        "SELECT bucket,k,payload_id,ord FROM objects ORDER BY ord"
    ):
        objects.append((bucket, json.loads(key), index._load_payload(payload_id), ordinal))
    expected = []
    for target, kind, payload_id, ordinal in index.db.execute(
        "SELECT target,kind,payload_id,ordinal FROM expected ORDER BY ordinal"
    ):
        expected.append((target, kind, index._load_payload(payload_id), ordinal))
    candidates = []
    for ticker, view, year, kind, scope, cell, column, row, ordinal in index.db.execute(
        """SELECT ticker,view,year,kind,scope,cell_payload_id,column_payload_id,
                  source_row_payload_id,ord FROM candidates ORDER BY ord"""
    ):
        candidates.append(
            (
                ticker,
                view,
                year,
                kind,
                scope,
                {
                    "cell": index._load_payload(cell),
                    "column": index._load_payload(column),
                    "source_row": index._load_payload(row),
                },
                ordinal,
            )
        )
    return {"objects": objects, "expected": expected, "candidates": candidates}


def _expected_values(index: Any, target: str, kind: str) -> list[Any]:
    if isinstance(index, AuditIndex):
        return list(index.expected(target, kind))
    return [
        json.loads(payload)
        for (payload,) in index.db.execute(
            "SELECT payload FROM expected WHERE target=? AND kind=? ORDER BY ordinal",
            (target, kind),
        )
    ]


def _candidate_values(index: Any, kind: str) -> list[dict[str, Any]]:
    if isinstance(index, AuditIndex):
        return list(index.candidates("SYN", "AS_FILED", 2025, kind, "scope"))
    return [
        json.loads(payload)
        for (payload,) in index.db.execute(
            """SELECT payload FROM candidates
               WHERE ticker='SYN' AND view='AS_FILED' AND year=2025
                 AND kind=? AND scope='scope' ORDER BY ord""",
            (kind,),
        )
    ]


def _finish_phase_flow(index: Any) -> dict[str, Any]:
    source = _expected_values(index, "target", "cells")
    derived = _expected_values(index, "__derived__", "derived")
    consumer = [json.loads(canonical_text(value)) for value in source]
    return {
        "source": source,
        "derived": derived,
        "consumer": consumer,
        "semantic_equal": consumer == source,
    }


def _run_phase_flow(index: Any) -> dict[str, Any]:
    for kind, number in (("YTD_9M", 70), ("FY", 100)):
        column = {"id": f"column-{kind}", "year": 2025, "kind": kind}
        row = {"id": "row-revenue", "label": "Revenue"}
        cell = {
            **_value(number),
            "value_numeric": str(number),
            "fiscal_time_series_column_id": column["id"],
        }
        if isinstance(index, AuditIndex):
            column_ref = index.put("columns", column["id"], column)
            row_ref = index.put("source_rows", row["id"], row, first=True)
            cell_ref = index.emit("target", "cells", cell)
            index.add_candidate_refs(
                "SYN",
                "AS_FILED",
                2025,
                kind,
                "scope",
                cell=cell_ref,
                column=column_ref,
                source_row=row_ref,
            )
        else:
            index.put("columns", column["id"], column)
            index.put("source_rows", row["id"], row, first=True)
            index.emit("target", "cells", cell)
            index.add_candidate(
                ("SYN", "AS_FILED", 2025, kind, "scope"),
                {"cell": cell, "column": column, "source_row": row},
            )
    earlier = _candidate_values(index, "YTD_9M")
    later = _candidate_values(index, "FY")
    assert len(earlier) == len(later) == 1
    amount = Decimal(later[0]["cell"]["value_numeric"]) - Decimal(
        earlier[0]["cell"]["value_numeric"]
    )
    index.emit(
        "__derived__",
        "derived",
        {
            "id": "metric-q4-revenue",
            "formula": "FY - YTD_9M",
            "value_numeric": str(amount),
            "source_ids": [earlier[0]["cell"]["id"], later[0]["cell"]["id"]],
        },
    )
    return _finish_phase_flow(index)


def test_full_legacy_observable_trace_and_reference_reuse(tmp_path: Path) -> None:
    legacy = LegacyIndex(tmp_path / "legacy.sqlite")
    candidate = AuditIndex(tmp_path / "candidate.sqlite", compression_threshold=None)
    try:
        _exercise(legacy)
        refs = _exercise(candidate)

        assert _trace_candidate(candidate) == _trace_legacy(legacy)
        assert refs["retained"] == refs["first"]
        assert candidate.get("rows", "row-1") == {"label": "updated"}
        assert list(candidate.items("rows")) == [
            ("row-1", {"label": "updated"}),
            ("row-2", {"label": "second"}),
        ]
        assert list(candidate.expected("target", "cells")) == [_value(1)]
        assert list(candidate.candidates("SYN", "AS_FILED", 2025, "FY", "scope")) == [
            {
                "cell": _value(1),
                "column": {"id": "column-1", "year": 2025},
                "source_row": {"id": "row-1", "label": "updated"},
            }
        ]
    finally:
        legacy.db.close()
        candidate.close()


def test_equal_payloads_deduplicate_without_coalescing_logical_rows(tmp_path: Path) -> None:
    index = AuditIndex(tmp_path / "index.sqlite", compression_threshold=None)
    try:
        value = {"same": [1, True, None]}
        refs = [index.put("bucket", f"logical-{number}", value) for number in range(3)]
        index.emit("one", "cells", value)
        index.emit("two", "cells", value)

        assert len({ref.payload_id for ref in refs}) == 1
        assert index.db.execute("SELECT count(*) FROM payloads").fetchone()[0] == 1
        assert index.db.execute("SELECT count(*) FROM objects").fetchone()[0] == 3
        assert index.db.execute("SELECT count(*) FROM expected").fetchone()[0] == 2
    finally:
        index.close()


def test_large_unicode_payload_compression_is_lossless(tmp_path: Path) -> None:
    long_text = "한글🚀" * 2_000
    value = {
        "value_text": long_text,
        "value_lineage": {"value_text": long_text},
        "user_tag_like_data": ["r", "sha256:not-a-private-reference"],
        "nested": {"d": [["user", ["n"]]]},
    }
    index = AuditIndex(tmp_path / "index.sqlite", compression_threshold=4096)
    try:
        index.put("cells", "cell", value)
        assert index.get("cells", "cell") == value
        assert index.db.execute("SELECT encoding FROM payloads").fetchone()[0] == storage.COMPRESSED_ENCODING
        assert index.verify_storage() == {"payloads": 1}
    finally:
        index.close()


def test_precision_bool_null_and_negative_zero_survive_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    value = _value(7, text="x" * 5_000)
    created = AuditIndex(path, compression_threshold=4096)
    created.put("cells", "cell", value)
    created.close()

    reopened = AuditIndex.open(path)
    try:
        actual = reopened.get("cells", "cell")
        assert canonical_text(actual) == canonical_text(value)
        assert type(actual["typed"][0]) is int
        assert type(actual["typed"][1]) is bool
        assert actual["typed"][2] is None
        assert canonical_text(actual["typed"][3]) == "-0.0"
        assert reopened.verify_storage()["payloads"] == 1
    finally:
        reopened.close()


def test_nan_is_rejected_without_object_row(tmp_path: Path) -> None:
    index = AuditIndex(tmp_path / "index.sqlite", compression_threshold=4096)
    try:
        with pytest.raises(ValueError, match="Out of range float values"):
            index.put("cells", "nan", {"value": float("nan")})
        assert index.db.execute("SELECT count(*) FROM objects").fetchone()[0] == 0
    finally:
        index.close()


def test_foreign_and_dangling_candidate_references_fail_closed(tmp_path: Path) -> None:
    first = AuditIndex(tmp_path / "first.sqlite")
    second = AuditIndex(tmp_path / "second.sqlite")
    try:
        foreign = first.payload_ref({"id": "foreign"})
        local = second.payload_ref({"id": "local"})
        with pytest.raises(AuditIndexError, match="FOREIGN_PAYLOAD_REF"):
            second.add_candidate_refs(
                "SYN",
                "AS_FILED",
                2025,
                "FY",
                "scope",
                cell=foreign,
                column=local,
                source_row=local,
            )
        second.db.commit()
        second.db.execute("PRAGMA foreign_keys=OFF")
        second.db.execute(
            """INSERT INTO candidates VALUES(
               'SYN','AS_FILED',2025,'FY','scope','missing','missing','missing',NULL)"""
        )
        with pytest.raises(AuditIndexError, match="DANGLING_PAYLOAD_REF"):
            list(second.candidates("SYN", "AS_FILED", 2025, "FY", "scope"))
    finally:
        first.close()
        second.close()


def test_compressed_payload_corruption_fails_closed(tmp_path: Path) -> None:
    index = AuditIndex(tmp_path / "index.sqlite", compression_threshold=4096)
    try:
        index.put("cells", "cell", {"value_text": "z" * 5_000})
        index.db.commit()
        payload_id = index.db.execute("SELECT payload_id FROM payloads").fetchone()[0]
        index.db.execute(
            "UPDATE payloads SET payload=? WHERE payload_id=?", (b"[]", payload_id)
        )
        with pytest.raises(
            AuditIndexError,
            match="CORRUPT_PAYLOAD_COMPRESSION|CORRUPT_PAYLOAD_LENGTH|CORRUPT_PAYLOAD_HASH",
        ):
            index.get("cells", "cell")
        index.db.rollback()
        index.db.execute(
            "UPDATE payloads SET byte_count=1 WHERE payload_id=?", (payload_id,)
        )
        with pytest.raises(
            AuditIndexError, match="CORRUPT_PAYLOAD_COMPRESSION|CORRUPT_PAYLOAD_LENGTH"
        ):
            index.get("cells", "cell")
    finally:
        index.close()


def test_hash_collisions_compare_exact_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(storage, "_digest", lambda data: "0" * 64)
    index = AuditIndex(tmp_path / "index.sqlite", compression_threshold=None)
    try:
        index.put("objects", "one", {"value": 1})
        with pytest.raises(AuditIndexError, match="PAYLOAD_HASH_COLLISION"):
            index.put("objects", "two", {"value": 2})
    finally:
        index.close()


def test_old_or_mismatched_storage_format_fails_closed(tmp_path: Path) -> None:
    old = tmp_path / "old.sqlite"
    connection = sqlite3.connect(old)
    connection.execute("CREATE TABLE objects(bucket TEXT,k TEXT,payload TEXT)")
    connection.close()
    with pytest.raises(AuditIndexError, match="FORMAT_MISSING"):
        AuditIndex.open(old)

    path = tmp_path / "wrong-version.sqlite"
    index = AuditIndex(path)
    index.db.execute(
        "UPDATE storage_meta SET value='future' WHERE key='format_version'"
    )
    index.close()
    with pytest.raises(AuditIndexError, match="AUDIT_INDEX_FORMAT"):
        AuditIndex.open(path)


def test_synthetic_source_derive_consumer_finish_matches_legacy(tmp_path: Path) -> None:
    legacy = LegacyIndex(tmp_path / "legacy.sqlite")
    candidate = AuditIndex(tmp_path / "candidate.sqlite")
    try:
        legacy_result = _run_phase_flow(legacy)
        candidate_result = _run_phase_flow(candidate)
        assert candidate_result == legacy_result
        assert candidate_result["semantic_equal"] is True
        assert candidate_result["derived"] == [
            {
                "id": "metric-q4-revenue",
                "formula": "FY - YTD_9M",
                "value_numeric": "30",
                "source_ids": ["cell-70", "cell-100"],
            }
        ]
        candidate.close()

        reopened = AuditIndex.open(tmp_path / "candidate.sqlite")
        try:
            assert _finish_phase_flow(reopened) == legacy_result
            assert reopened.verify_storage()["payloads"] > 0
        finally:
            reopened.close()
    finally:
        legacy.db.close()
        if candidate.db:
            try:
                candidate.db.close()
            except sqlite3.ProgrammingError:
                pass
