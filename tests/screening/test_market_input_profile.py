from __future__ import annotations

import copy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics.market_inputs import encoded, identity

SPEC = spec_from_file_location(
    "market_profile",
    Path(__file__).parents[2] / "examples/screening/prepare_market_input_profile.py",
)
profile = module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


def share(
    value="0", end="2026-07-01", node="class-a", input_id="outstanding_common_shares_balance"
):
    return {
        "cik": "0000000001",
        "input_id": input_id,
        "value": value,
        "status": "AVAILABLE_REPORTED",
        "reason": None,
        "start": None,
        "end": end,
        "end_convention": "EXCLUSIVE",
        "period_class": "INSTANT",
        "dimensions": [["axis", node]],
        "raw_dimensions": [["raw-axis", node]],
        "unit": ["shares", None],
        "unit_kind": "shares",
        "source": {
            "node_id": node,
            "selected_source_fact_id": node,
            "accession": "0000000001-26-000001",
        },
        "observation_id": node + end + str(value),
    }


def test_latest_shares_per_full_prepared_scope_keep_zero_classes_and_conflicts():
    old = share("2", "2025-07-01")
    current = share("0")
    other = share("7", node="class-b")
    future = share("999", end="2026-11-01")
    rows = profile.latest_share_candidates([old, current, other, future], "2026-10-25")
    assert len(rows) == 2
    assert {r["value"] for r in rows} == {"0", "7"}
    assert {r["display_end"] for r in rows} == {"2026-06-30"}
    conflicting = share("8", node="class-b")
    rows = profile.latest_share_candidates([other, conflicting], "2026-10-25")
    assert all(r["value"] is None and r["reason"] == "AMBIGUOUS_REPORTED_SHARE_VALUE" for r in rows)


def test_read_snapshot_scope_uses_original_identity_and_rejects_other_parent(tmp_path):
    original = {
        "schema_version": "screening-prepared-changes-v1",
        "dataset_id": "prepared109",
        "publication_id": "pub109",
        "parent_manifest_sha256": "a" * 64,
        "financial_as_of": "2026-10-25",
        "configured_ciks": ["0000000001"],
    }
    common = {
        "parent": {"sha256": "a" * 64},
        "financial_as_of": "2026-10-25",
        "companies": [{"cik": "0000000001"}],
    }
    snapshot = {
        "schema_version": "screening-read-snapshot-v1",
        "properties": {"original_manifest": original, "original_manifest_sha256": "b" * 64},
    }
    snapshot["logical_sha256"] = identity(snapshot)
    ref = pin(tmp_path / "snapshot.json", snapshot)
    result = profile.dataset_scope(ref, common)
    assert result["dataset_manifest_sha256"] == "b" * 64
    assert result["dataset_publication_id"] == "pub109"
    original["parent_manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="exact prepared descendant"):
        profile.dataset_scope(pin(tmp_path / "plain.json", original), common)
    snapshot["properties"]["original_manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="logical identity"):
        profile.dataset_scope(pin(tmp_path / "bad.json", snapshot), common)


def test_compact_asset_uses_exact_registered_ticker_price_basis_and_preserves_parent(
    tmp_path, monkeypatch
):
    cik = "0000000001"
    export = pin(
        tmp_path / "export.json",
        {
            "delivery": {"sha256": "d" * 64},
            "supplier": {"package_version": "0.5.1"},
            "created_at": "2026-11-08T00:00:00+00:00",
            "lineage": {},
            "producer": {"source_commit": "supplier"},
        },
    )
    common = {
        "parent": {"sha256": "a" * 64},
        "financial_as_of": "2026-10-25",
        "companies": [{"cik": cik, "ticker": "COMMON"}],
        "price_export": export,
        "prepared_at": "2026-11-14T00:00:00+00:00",
    }
    securities = [
        {"cik": cik, "security_id": "US:PREFERRED", "ticker": "PREFERRED"},
        {"cik": cik, "security_id": "US:COMMON", "ticker": "COMMON"},
    ]
    prices = [
        {
            "cik": cik,
            "status": "AVAILABLE_OBSERVED",
            "observation_id": str(i),
            "price": {
                "security_id": s["security_id"],
                "trade_date": "2026-10-23",
                "as_traded_close": value,
                "split_adj_close": value / 2,
                "source": "yahoo_chart",
            },
        }
        for i, (s, value) in enumerate(zip(securities, [300, 10]))
    ]
    rows = [share()]
    assessment = {
        "cik": cik,
        "reported_12m": {
            "status": "AVAILABLE_REPORTED",
            "value": "-1.2",
            "observation_ids": [],
            "end": "2026-07-01",
            "period_class": "FY",
        },
        "four_quarter_diagnostic": {"reason": "SHARE_BASIS_UNKNOWN"},
        "security_header_links": [],
    }
    data = {"financial_inputs": rows, "prices": prices, "securities": securities}
    reader = SimpleNamespace(
        parent=SimpleNamespace(manifest=common, _read=lambda name: copy.deepcopy(data[name])),
        manifest={"parent": {"sha256": "e" * 64}, "prepared_at": "2026-11-14T00:00:00+00:00"},
        _assessments=lambda: [copy.deepcopy(assessment)],
    )
    monkeypatch.setattr(profile, "MarketInputAssessmentReader", lambda *args: reader)
    original = {
        "schema_version": "screening-prepared-changes-v1",
        "dataset_id": "prepared109",
        "publication_id": "pub109",
        "parent_manifest_sha256": "a" * 64,
        "financial_as_of": "2026-10-25",
        "configured_ciks": [cik],
    }
    dataset = pin(tmp_path / "dataset.json", original)
    before = copy.deepcopy(data)
    asset = profile.build_profile_asset(
        {"path": "/approved/assessment", "sha256": "f" * 64}, dataset
    )
    company = asset["companies"][cik]
    assert company["prices"][0]["security"]["ticker"] == "COMMON"
    assert company["prices"][0]["value"] == 10
    assert company["prices"][0]["currency"] is None
    assert company["prices"][0]["trade_date"] == "2026-10-23"
    assert company["prices"][0]["staleness_calendar_days"] == 2
    assert company["reported_12m"]["value"] == "-1.2"
    assert company["reported_12m"]["display_end"] == "2026-06-30"
    assert len(company["other_prices"]) == 1
    assert data == before
    securities.append(dict(securities[1], security_id="US:SECOND-COMMON"))
    assert (
        profile.build_profile_asset({"path": "/approved/assessment", "sha256": "f" * 64}, dataset)[
            "companies"
        ][cik]["prices"]
        == []
    )
