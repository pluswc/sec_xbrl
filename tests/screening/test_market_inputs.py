from __future__ import annotations

import copy
from decimal import localcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics import market_inputs as inputs
from sec_xbrl.screening import market_input_publication as publication


def pin(path, value):
    path.write_bytes(inputs.encoded(value))
    return {"path": str(path), "sha256": inputs.identity(value)}


def quarters(cik="0000000001"):
    dates = [
        ("2025-10-01", "2026-01-01"),
        ("2026-01-01", "2026-04-01"),
        ("2026-04-01", "2026-07-01"),
        ("2026-07-01", "2026-10-01"),
    ]
    return [
        {
            "cik": cik,
            "ticker": "TEST",
            "input_id": "reported_eps_diluted_total",
            "observation_id": f"id-{i}",
            "period_class": "QTD_3M",
            "fiscal_year": 2026,
            "fiscal_quarter": i + 1,
            "start": a,
            "end": b,
            "end_convention": "EXCLUSIVE",
            "dimensions": [],
            "raw_dimensions": [],
            "unit": ['["iso4217:USD"]', '["xbrli:shares"]'],
            "namespace": "http://fasb.org/us-gaap/2026",
            "qname": "us-gaap:EarningsPerShareDiluted",
            "status": "AVAILABLE_REPORTED",
            "reason": None,
            "reported_or_derived": "REPORTED",
            "unit_kind": "USD/share",
            "value": v,
            "source_value": v,
            "filed_date": "2026-10-20",
            "source": {
                "source_snapshot_id": "raw",
                "source_filing_id": "filing",
                "selected_source_fact_id": f"fact-{i}",
                "cell_id": f"cell-{i}",
            },
        }
        for i, ((a, b), v) in enumerate(zip(dates, ["1.2", "-2.3", "0", "4.1"]))
    ]


def declaration(rows):
    return {
        "cik": rows[0]["cik"],
        "stock_class_id": "common-class-a",
        "currency": "USD",
        "basis_id": "reviewed-unadjusted-2026",
        "available_on": "2026-10-21",
        "observation_ids": [r["observation_id"] for r in rows],
        "source_pins": [{"evidence": "fixture"}],
    }


def derive(rows, dec=None):
    return inputs.derive_market_eps_ttm(
        rows,
        cik="0000000001",
        financial_as_of="2026-10-25",
        declaration=declaration(rows) if dec is None else dec,
    )


def test_signed_direct_ttm_exact_and_missing_basis():
    rows = quarters()
    for precision in (2, 40):
        with localcontext() as ctx:
            ctx.prec = precision
            result = derive(rows)
            assert result["value"] == "3.0"
            assert result["status"] == "AVAILABLE_DERIVED_SEPARATE"
    assert (
        inputs.derive_market_eps_ttm(rows, cik="0000000001", financial_as_of="2026-10-25")["reason"]
        == "SHARE_BASIS_UNKNOWN"
    )
    rows[0]["value"] = "-1.8"
    assert derive(rows)["value"] == "0.0"
    rows[0]["value"] = "-2.8"
    assert derive(rows)["value"] == "-1.0"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("derived", "FOUR_DIRECT_QUARTERS_REQUIRED"),
        ("gap", "QUARTER_GAP_OR_DUPLICATE"),
        ("unit", "SCOPE_OR_UNIT_NOT_COMPATIBLE"),
        ("class", "SCOPE_OR_UNIT_NOT_COMPATIBLE"),
        ("future", "FOUR_DIRECT_QUARTERS_REQUIRED"),
        ("split", "BASIS_EVIDENCE_AFTER_CUTOFF"),
        ("duplicate", "AMBIGUOUS_DIRECT_QUARTER"),
        ("missing", "INPUT_IDENTITY_NOT_CONFIRMED"),
    ],
)
def test_ttm_rejects_incompatible_or_missing_legs(change, reason):
    rows = quarters()
    dec = declaration(rows)
    if change == "derived":
        rows[3]["reported_or_derived"] = "DERIVED"
    elif change == "gap":
        rows[3]["fiscal_quarter"] = 5
    elif change == "unit":
        rows[3]["unit"] = ['["iso4217:EUR"]', '["xbrli:shares"]']
    elif change == "class":
        rows[3]["dimensions"] = [["axis", "different-class"]]
    elif change == "future":
        rows[3]["filed_date"] = "2026-11-01"
    elif change == "split":
        dec["available_on"] = "2026-11-01"
    elif change == "duplicate":
        rows.append(dict(rows[0], observation_id="conflicting", value="7"))
    else:
        rows.pop()
    assert derive(rows, dec)["reason"] == reason


def test_same_raw_fact_references_deduplicate_not_conflicting_facts():
    rows = quarters()
    duplicate = copy.deepcopy(rows[0])
    duplicate["source"]["cell_id"] = "second-role-reference"
    merged = inputs.deduplicate_financial_inputs(rows + [duplicate])
    assert len(merged) == 4
    assert max(len(r["analysis_references"]) for r in merged) == 2
    assert derive(merged)["value"] == "3.0"
    duplicate["source_value"] = duplicate["value"] = "99"
    with pytest.raises(ValueError, match="conflicting"):
        inputs.deduplicate_financial_inputs(rows + [duplicate])


def test_selected_analysis_projection_binds_raw_and_preserves_direct_recast(tmp_path, monkeypatch):
    manifest = {"publication_id": "analysis-test", "companies": {"TEST": {"as_of": "2026-10-25"}}}
    ref = pin(tmp_path / "analysis_manifest.json", manifest)
    node = {
        "node_id": "node",
        "kind": "VALUE",
        "concept": "us-gaap:EarningsPerShareDiluted",
        "dimensions": [],
    }
    lineage = {
        "raw_concept_qname": node["concept"],
        "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2026",
        "source_type": "RECAST_REPORTED",
        "unit_numerator_measures": '["iso4217:USD"]',
        "unit_denominator_measures": '["xbrli:shares"]',
        "raw_concept_id": "raw-concept",
        "context_id": "context",
        "source_snapshot_id": "raw",
        "source_filing_id": "filing",
        "selected_source_fact_id": "fact",
        "company_canonical_concept_id": "company:0000000001:concept:eps",
        "value_numeric": "-0.1",
        "filed_date": "2026-10-20",
        "selection_as_of_date": "2026-10-25",
    }
    cell = {
        "node_id": "node",
        "cell_id": "cell",
        "source_fact_id": "fact",
        "status": "RECAST_REPORTED",
        "value": "-0.1",
        "period_class": "QTD_3M",
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
        "start": "2026-07-01",
        "end": "2026-10-01",
    }

    def records(ticker, view, name):
        return (
            [node]
            if name == "nodes"
            else [cell]
            if name == "cells"
            else [{"cell_id": "cell", "value_lineage": lineage}]
        )

    monkeypatch.setattr(
        inputs, "open_analysis", lambda root: SimpleNamespace(manifest=manifest, _records=records)
    )
    result = inputs.project_financial_inputs(
        ref, cik="0000000001", ticker="TEST", financial_as_of="2026-10-25"
    )
    assert result[0]["value"] == "-0.1"
    lineage["selected_source_fact_id"] = "foreign"
    assert (
        inputs.project_financial_inputs(
            ref, cik="0000000001", ticker="TEST", financial_as_of="2026-10-25"
        )[0]["reason"]
        == "SOURCE_IDENTITY_NOT_CONFIRMED"
    )


def fixture_config(tmp_path, count=1):
    ciks = [str(i + 1).zfill(10) for i in range(count)]
    parent = pin(
        tmp_path / "parent.json",
        {"configured_ciks": ciks, "financial_as_of": "2026-10-25", "publication_id": "parent"},
    )
    delivery = pin(
        tmp_path / "delivery.json",
        {
            "package_version": "0.5.1",
            "contract_version": "1.1.1",
            "artifacts": {
                "price.parquet": {"path": "/supplier/price.parquet", "sha256": "a" * 64},
                "security.parquet": {"path": "/supplier/security.parquet", "sha256": "b" * 64},
            },
        },
    )
    securities = [
        {
            "security_id": "US:" + cik,
            "cik": cik,
            "company_name": "Company",
            "ticker": "T" + cik,
            "exchange": "",
            "yahoo_symbol": "T" + cik,
        }
        for cik in ciks
    ]
    securities.append(
        dict(
            securities[0], security_id="US:NONCOMMON", ticker="NONCOMMON", yahoo_symbol="NONCOMMON"
        )
    )
    export = {
        "schema": "canonical-query-price-export-v1",
        "delivery": delivery,
        "supplier": {"package_version": "0.5.1", "contract_version": "1.1.1"},
        "query": {
            "start_date": "2026-10-23",
            "end_date": "2026-10-23",
            "security_ids": [s["security_id"] for s in securities],
        },
        "lineage": {
            "path": "/supplier/price.parquet",
            "sha256": "a" * 64,
            "security_sha256": "b" * 64,
        },
        "securities": securities,
        "prices": [],
        "created_at": "2026-11-14T01:00:00+00:00",
        "producer": {"source_commit": "supplier-test"},
    }
    for security in securities:
        row = dict.fromkeys(publication.PRICE_FIELDS)
        row.update(
            security_id=security["security_id"],
            trade_date="2026-10-23",
            source="yahoo_chart",
            as_traded_close=10,
        )
        export["prices"].append(row)
    price_ref = pin(tmp_path / "export.json", export)
    companies = []
    for cik in ciks:
        ref = pin(tmp_path / (cik + ".json"), {"period_mode": "QUARTERLY"})
        companies.append({"cik": cik, "ticker": "T" + cik, "annual": None, "quarterly": ref})
    config = {
        "schema": "screening-market-input-config-v1",
        "parent": parent,
        "financial_as_of": "2026-10-25",
        "price_export": price_ref,
        "companies": companies,
    }
    return config, export


def test_public109_builder_reopen_missing_states_one_to_many_and_tamper(tmp_path, monkeypatch):
    config, _ = fixture_config(tmp_path, 109)
    monkeypatch.setattr(
        publication, "project_financial_inputs", lambda pin, *, cik, **kw: quarters(cik)
    )
    monkeypatch.setattr(publication, "project_cover_shares", lambda *args, **kwargs: [])
    ref = pin(tmp_path / "config.json", config)
    result = publication.publish_market_inputs(ref["path"], ref["sha256"], tmp_path / "published")
    reader = publication.MarketInputReader(result["path"], result["sha256"])
    assert result["counts"]["companies"] == 109
    queried = reader.query("0000000001")
    assert len(queried["securities"]) == 2
    assert len(queried["prices"]) == 2
    assert queried["financial_inputs"][1]["value"] is not None
    assert queried["derived_inputs"][0]["reason"] == "SHARE_BASIS_UNKNOWN"
    assert len(queried["selections"]) == len(inputs.REGISTRY) + 1
    assert any(
        r["input_id"] == "reported_eps_basic_total" and r["status"] == "UNAVAILABLE"
        for r in queried["selections"]
    )
    with pytest.raises(FileExistsError):
        publication.publish_market_inputs(ref["path"], ref["sha256"], tmp_path / "published")
    path = Path(result["path"]).parent / "financial_inputs.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="hash"):
        reader.query("0000000001")


@pytest.mark.parametrize("change", ["pair", "future", "duplicate", "owner"])
def test_price_export_pairing_and_scope_rejected(tmp_path, change):
    _, export = fixture_config(tmp_path)
    if change == "pair":
        export["lineage"]["security_sha256"] = "c" * 64
    elif change == "future":
        export["query"]["end_date"] = "2026-11-01"
    elif change == "duplicate":
        export["prices"].append(export["prices"][0])
    else:
        export["securities"][0]["cik"] = "0000000002"
    with pytest.raises(ValueError):
        publication._price_rows(export, {"0000000001"}, "2026-10-25")


def test_retained_raw_cover_is_not_selected_eps_and_preserves_classes(tmp_path):
    import polars as pl

    cik = "0000000001"
    accession = "0000000001-26-000001"
    root = tmp_path / "raw" / "snapshots" / cik / accession.replace("-", "")
    root.mkdir(parents=True)
    pin(root / "layer1_manifest.json", {"cik": cik, "accession": accession})

    def table(name, rows):
        pl.DataFrame(rows).write_parquet(root / (name + ".parquet"))

    table(
        "concept",
        [
            {
                "raw_concept_id": "cover",
                "qname": "dei:EntityCommonStockSharesOutstanding",
                "namespace_uri": "http://xbrl.sec.gov/dei/2026",
                "is_standard": True,
                "period_type": "instant",
            },
            {
                "raw_concept_id": "axis",
                "qname": "us-gaap:StatementClassOfStockAxis",
                "namespace_uri": "http://fasb.org/us-gaap/2026",
                "is_standard": True,
                "period_type": "duration",
            },
            {
                "raw_concept_id": "member",
                "qname": "us-gaap:ClassACommonStockMember",
                "namespace_uri": "http://fasb.org/us-gaap/2026",
                "is_standard": True,
                "period_type": "duration",
            },
        ],
    )
    table(
        "filing",
        [
            {
                "cik": cik,
                "accession": accession,
                "filed_date": "2026-10-20",
                "form": "10-Q",
                "filing_id": "filing",
            }
        ],
    )
    table(
        "context",
        [
            {
                "context_id": "context",
                "filing_id": "filing",
                "period_kind": "INSTANT",
                "instant_date": "2026-10-16",
            }
        ],
    )
    table(
        "unit",
        [
            {
                "unit_id": "unit",
                "numerator_measures": '["xbrli:shares"]',
                "denominator_measures": "[]",
            }
        ],
    )
    table(
        "fact",
        [
            {
                "fact_id": "fact",
                "raw_concept_id": "cover",
                "context_id": "context",
                "unit_id": "unit",
                "filing_id": "filing",
                "value_numeric": "0",
                "is_nil": False,
                "source_document": "filing.htm",
                "source_locator": "ix:42",
            }
        ],
    )
    table(
        "dimension_fact",
        [
            {
                "fact_id": "fact",
                "axis_raw_concept_id": "axis",
                "member_raw_concept_id": "member",
                "typed_member": None,
                "dimension_type": "EXPLICIT",
                "is_default_member": False,
            }
        ],
    )
    intake = pin(
        tmp_path / "intake.json",
        {
            "filings": [
                {
                    "ticker": "TEST",
                    "status": "REUSED",
                    "source_run": str(tmp_path / "raw"),
                    "filing": {
                        "cik": cik,
                        "accession": accession,
                        "filed_date": "2026-10-20",
                        "form": "10-Q",
                    },
                }
            ]
        },
    )
    analysis = pin(tmp_path / "analysis.json", {"companies": {"TEST": {}}})
    rows = inputs.project_cover_shares(
        analysis, cik=cik, ticker="TEST", financial_as_of="2026-10-25", intake_pin=intake
    )
    assert len(rows) == 1
    assert rows[0]["value"] == "0"
    assert rows[0]["stock_class_id"] is None
    assert rows[0]["dimensions"][0]["member_qname"] == "us-gaap:ClassACommonStockMember"
    assert rows[0]["selection_view"].startswith("RAW_AS_FILED")
    assert set(rows[0]["source"]["raw_tables"]) == {
        "concept",
        "filing",
        "fact",
        "context",
        "unit",
        "dimension_fact",
    }
    assert rows[0]["input_id"] == "outstanding_common_shares_cover"
    assert (
        inputs.derive_market_eps_ttm(rows, cik=cik, financial_as_of="2026-10-25")["value"] is None
    )


def test_older_direct_quarters_cannot_hide_latest_missing_direct_eps():
    rows = quarters()
    dec = declaration(rows)
    rows.append(
        dict(
            rows[-1],
            observation_id="later",
            start="2026-10-01",
            end="2027-01-01",
            status="UNAVAILABLE",
            value=None,
            fiscal_year=2027,
            fiscal_quarter=1,
        )
    )
    assert derive(rows, dec)["reason"] == "LATEST_DIRECT_QUARTERS_NOT_PREPARED"
