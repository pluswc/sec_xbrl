from __future__ import annotations

import hashlib
import math
import struct

import pytest

from sec_xbrl.analytics import history_quarters as quarters
from tools.history_audit_typed_hash import TypedHash, typed_digest


def _put(digest, payload):
    digest.update(struct.pack(">Q", len(payload)))
    digest.update(payload)


def _raw(value):
    if value is None:
        return b"N"
    if type(value) is bool:
        return b"B1" if value else b"B0"
    if type(value) is int:
        return b"I" + str(value).encode("ascii")
    if type(value) is float:
        return b"F" + struct.pack(">d", value)
    if type(value) is str:
        return b"S" + value.encode()
    if type(value) is bytes:
        return b"Y" + value
    if type(value) in (dict, list, tuple):
        nested = hashlib.sha256()
        _logical(nested, value)
        return b"C" + nested.digest()
    raise TypeError(type(value))


def _logical(digest, value):
    if type(value) is dict:
        digest.update(b"D")
        _put(digest, str(len(value)).encode())
        for key in sorted(value):
            _put(digest, key.encode())
            _logical(digest, value[key])
    elif type(value) in (list, tuple):
        digest.update(b"L" if type(value) is list else b"T")
        _put(digest, str(len(value)).encode())
        for item in value:
            _logical(digest, item)
    else:
        _put(digest, _raw(value))


def _old_digest(value):
    digest = hashlib.sha256()
    _logical(digest, value)
    return digest.digest()


@pytest.mark.parametrize("buffer_bytes", [1, 7, 64 * 1024])
def test_buffered_encoder_is_exact_old_protocol(buffer_bytes):
    values = [
        None,
        True,
        2**100,
        "한글🙂",
        b"\x00\xff",
        -0.0,
        float("nan"),
        [1, False, None],
        (1, False, None),
        {"z": [2**80, -0.0], "a": {"bytes": b"x" * 100_000}},
    ]
    old = hashlib.sha256()
    new = TypedHash(buffer_bytes=buffer_bytes)
    for value in values:
        _logical(old, value)
        new.update(value)
    assert new.digest() == old.digest()
    assert typed_digest(values[-1]) == _old_digest(values[-1])
    assert math.copysign(1.0, values[5]) == -1.0


def test_shared_walk_keeps_independent_row_and_aggregate_digests():
    records = [{"id": 1, "nested": [True, None]}, {"id": 2, "nested": (False, -0.0)}]
    aggregate = TypedHash()
    row_digests = []
    for record in records:
        row = TypedHash()
        aggregate.update(record, mirrors=(row,))
        row_digests.append(row.hexdigest())
    old = hashlib.sha256()
    for record in records:
        _logical(old, record)
    assert aggregate.hexdigest() == old.hexdigest()
    assert row_digests == [_old_digest(record).hex() for record in records]
    assert row_digests[0] != typed_digest(records[1]).hex()
    with pytest.raises(TypeError):
        typed_digest({"unsupported": object()})


def test_independent_chunk_and_public_streams_match_and_detect_mutation():
    chunk_records = [
        {"id": 1, "evidence": [{"flag": True, "value": None}]},
        {"id": 2, "evidence": [{"flag": False, "value": -0.0}]},
    ]
    public_records = [
        {"id": 1, "evidence": [{"flag": True, "value": None}]},
        {"id": 2, "evidence": [{"flag": False, "value": -0.0}]},
    ]
    chunk_aggregate = TypedHash()
    public_aggregate = TypedHash()
    chunk_rows = []
    public_rows = []
    for record in chunk_records:
        chunk_digest = TypedHash()
        chunk_row = TypedHash()
        chunk_aggregate.update(record, mirrors=(chunk_digest, chunk_row))
        chunk_rows.append(chunk_row.digest())
    for record in public_records:
        public_row = TypedHash()
        public_aggregate.update(record, mirrors=(public_row,))
        public_rows.append(public_row.digest())
    assert chunk_rows == public_rows
    assert chunk_aggregate.digest() == public_aggregate.digest()

    public_records[1]["evidence"][0]["flag"] = True
    assert typed_digest(public_records[1]) != chunk_rows[1]


def test_selective_cell_copy_isolated_mutations_preserve_large_evidence():
    evidence = [{"candidate": number, "payload": "x" * 4096} for number in range(570)]
    original = {
        "fiscal_time_series_cell_id": "cell",
        "candidate_lineage": evidence,
        "value_lineage": {"period_class": "FY", "nested": {"immutable": [1, 2]}},
    }
    cell, lineage = quarters._copy_reclassified_cell(original)
    lineage["period_class"] = "QTD_3M"
    cell["fiscal_time_series_cell_id"] = "reclassified"
    cell["prior_publication_candidate_lineage"] = cell.pop("candidate_lineage")

    assert original["fiscal_time_series_cell_id"] == "cell"
    assert original["value_lineage"]["period_class"] == "FY"
    assert cell["value_lineage"] is not original["value_lineage"]
    assert cell["value_lineage"]["nested"] is original["value_lineage"]["nested"]
    assert cell["prior_publication_candidate_lineage"] is evidence
    assert len(cell["prior_publication_candidate_lineage"]) == 570
