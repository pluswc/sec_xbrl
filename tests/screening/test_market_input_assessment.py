from __future__ import annotations

import copy
import itertools
from pathlib import Path

import pytest

from sec_xbrl.metrics import market_input_assessment as assess
from sec_xbrl.metrics.market_inputs import encoded, identity
from sec_xbrl.screening import market_input_publication as publication


def pin(path, value):
    path.write_bytes(encoded(value))
    return {"path": str(path), "sha256": identity(value)}


def eps(value="-1.2", start="2025-10-01", end="2026-10-01", period="FY", fact="one"):
    return {
        "cik": "0000000001",
        "input_id": "reported_eps_diluted_total",
        "observation_id": fact,
        "value": value,
        "start": start,
        "end": end,
        "end_convention": "EXCLUSIVE",
        "period_class": period,
        "status": "AVAILABLE_REPORTED",
        "reported_or_derived": "REPORTED",
        "unit_kind": "USD/share",
        "unit": ['["iso4217:USD"]', '["xbrli:shares"]'],
        "canonical_dimensions": [],
        "raw_dimensions": [],
        "namespace": "http://fasb.org/us-gaap/2026",
        "qname": "us-gaap:EarningsPerShareDiluted",
        "filed_date": "2026-10-20",
        "source": {
            "source_snapshot_id": "raw",
            "source_filing_id": "filing",
            "context_id": "context",
            "selected_source_fact_id": fact,
        },
    }


def anchor():
    return {"end": "2026-10-01", "reason": None}


def test_latest_financial_anchor_not_latest_eps_and_direct_12m_negative():
    intake = {
        "filings": [
            {
                "status": "REUSED",
                "filing": {
                    "cik": "0000000001",
                    "report_date": "2026-09-30",
                    "filed_date": "2026-10-20",
                    "form": "10-K",
                },
            },
            {
                "status": "REUSED",
                "filing": {
                    "cik": "0000000001",
                    "report_date": "2026-12-31",
                    "filed_date": "2027-01-20",
                    "form": "10-Q",
                },
            },
        ]
    }
    actual = assess.latest_financial_anchor(intake, "0000000001", "2026-10-25")
    assert actual["end"] == "2026-10-01"
    row = eps()
    result = assess.assess_reported_12m([row], actual, "2026-10-25")
    assert result["value"] == "-1.2"
    assert result["positive_for_multiple"] is False
    assert result["valuation_binding_status"] == "NOT_ASSESSED"
    stale = eps(start="2024-10-01", end="2025-10-01")
    assert assess.assess_reported_12m([stale], actual, "2026-10-25")["value"] is None
    row["filed_date"] = "2026-11-01"
    assert assess.assess_reported_12m([row], actual, "2026-10-25")["value"] is None


def test_reported_12m_equivalent_duplicates_keep_refs_conflicts_and_cross_filing_reject():
    row = eps()
    duplicate = copy.deepcopy(row)
    duplicate["observation_id"] = "another-fact"
    duplicate["source"]["selected_source_fact_id"] = "another-fact"
    duplicate["value"] = "-1.20"
    result = assess.assess_reported_12m([row, duplicate], anchor(), "2026-10-25")
    assert result["observation_ids"] == ["another-fact", "one"]
    duplicate["value"] = "3"
    assert (
        assess.assess_reported_12m([row, duplicate], anchor(), "2026-10-25")["reason"]
        == "AMBIGUOUS_REPORTED_12M"
    )
    duplicate["value"] = row["value"]
    duplicate["source"]["source_filing_id"] = "different-filing"
    assert assess.assess_reported_12m([row, duplicate], anchor(), "2026-10-25")["value"] is None


def four():
    boundaries = ["2025-10-01", "2026-01-01", "2026-04-01", "2026-07-01", "2026-10-01"]
    return [
        eps(start=a, end=b, period="QTD_3M", fact=str(i))
        for i, (a, b) in enumerate(itertools.pairwise(boundaries))
    ]


def test_four_quarter_real_diagnostics_before_share_basis():
    rows = four()
    result = assess.assess_four_quarters(rows, anchor(), "2026-10-25")
    assert result["financial_input_status"] == "FOUR_DIRECT_QUARTERS_PRESENT"
    assert result["reason"] == "SHARE_BASIS_UNKNOWN"
    assert result["value"] is None
    assert assess.assess_four_quarters([], anchor(), "2026-10-25")["reason"] == "NO_DIRECT_QTD_EPS"
    assert (
        assess.assess_four_quarters(rows[:-1], anchor(), "2026-10-25")["reason"]
        == "MISSING_DIRECT_QUARTER"
    )
    older = dict(anchor(), end="2027-01-01")
    assert (
        assess.assess_four_quarters(rows, older, "2026-10-25")["reason"] == "MISSING_DIRECT_QUARTER"
    )
    rows[2]["start"] = "2026-04-02"
    assert assess.assess_four_quarters(rows, anchor(), "2026-10-25")["reason"] == "QUARTER_GAP"


def test_canonical_dimensions_ignore_raw_ids_but_preserve_namespace_and_custom_identity():
    concepts = {
        "a": {
            "qname": "us-gaap:StatementClassOfStockAxis",
            "namespace_uri": "http://fasb.org/us-gaap/2026",
            "is_standard": True,
            "taxonomy_family": "us-gaap",
        },
        "b": {"qname": "issuer:CapitalClassCMember", "namespace_uri": "http://issuer/2026"},
    }
    dims = [["a", "b", None, "EXPLICIT", "false"]]
    canonical = assess.canonical_dimensions(dims, concepts)
    renamed = {"other-a": concepts["a"], "other-b": concepts["b"]}
    assert (
        assess.canonical_dimensions([["other-a", "other-b", None, "EXPLICIT", "false"]], renamed)
        == canonical
    )
    renamed["other-b"] = dict(renamed["other-b"], namespace_uri="http://issuer/2025")
    assert (
        assess.canonical_dimensions([["other-a", "other-b", None, "EXPLICIT", "false"]], renamed)
        != canonical
    )
    rows = four()
    for row in rows:
        row["canonical_dimensions"] = canonical
    assert (
        assess.assess_four_quarters(rows, anchor(), "2026-10-25")["reason"] == "SHARE_BASIS_UNKNOWN"
    )
    rows[-1]["canonical_dimensions"] = []
    result = assess.assess_four_quarters(rows, anchor(), "2026-10-25")
    assert result["reason"] == "SCOPE_SELECTION_REQUIRED"
    assert len(result["series"]) == 2


def header_fixture():
    concepts = {
        name: {
            "qname": qname,
            "namespace_uri": "http://xbrl.sec.gov/dei/2026",
            "is_standard": True,
            "taxonomy_family": "dei",
        }
        for name, qname in [
            ("symbol", "dei:TradingSymbol"),
            ("title", "dei:Security12bTitle"),
            ("exchange", "dei:SecurityExchangeName"),
        ]
    }
    concepts.update(
        axis={"qname": assess.CLASS_AXIS, "namespace_uri": "http://fasb.org/us-gaap/2026"},
        common={
            "qname": "us-gaap:CommonStockMember",
            "namespace_uri": "http://fasb.org/us-gaap/2026",
            "is_standard": True,
            "taxonomy_family": "us-gaap",
        },
        bond={"qname": "issuer:NotesMember", "namespace_uri": "http://issuer/2026"},
    )
    for name in ("axis", "common"):
        concepts[name].update(is_standard=True, taxonomy_family="us-gaap")
    facts, contexts, dimensions = [], {}, []
    for context_id, member, title in [
        ("stock", "common", "Common stock"),
        ("bond", "bond", "Notes due 2050"),
    ]:
        contexts[context_id] = {
            "filing_id": "filing",
            "entity_identifier": "http://www.sec.gov/CIK:0000000001",
        }
        for concept, text in [("symbol", "SAME"), ("title", title), ("exchange", "Nasdaq")]:
            fact_id = context_id + concept
            facts.append(
                {
                    "fact_id": fact_id,
                    "filing_id": "filing",
                    "context_id": context_id,
                    "raw_concept_id": concept,
                    "value_text": text,
                    "is_nil": False,
                }
            )
            dimensions.append(
                {
                    "fact_id": fact_id,
                    "axis_raw_concept_id": "axis",
                    "member_raw_concept_id": member,
                    "typed_member": None,
                    "dimension_type": "EXPLICIT",
                    "is_default_member": False,
                }
            )
    return concepts, facts, contexts, dimensions


def test_header_same_ticker_stock_and_bond_both_survive_no_eps_binding_and_coregistrant_reject():
    concepts, facts, contexts, dims = header_fixture()
    kwargs = {
        "cik": "0000000001",
        "securities": [{"cik": "0000000001", "ticker": "SAME", "security_id": "US:SAME"}],
        "filing": {"filing_id": "filing"},
        "concepts": concepts,
        "facts": facts,
        "contexts": contexts,
        "dimensions": dims,
        "source": {"raw": "pin"},
    }
    links = assess.link_security_headers(**kwargs)
    assert len(links) == 2
    assert {r["instrument_kind"] for r in links} == {"COMMON_STOCK", "UNKNOWN"}
    assert all(
        r["eps_applicability"] == "NOT_CONFIRMED" and r["split_review"] == "UNKNOWN" for r in links
    )
    contexts["bond"]["entity_identifier"] = "http://www.sec.gov/CIK:0000000002"
    assert len(assess.link_security_headers(**kwargs)) == 1
    kwargs["securities"][0]["ticker"] = "OTHER"
    assert assess.link_security_headers(**kwargs) == []


def test_small_overlay_public_reopen_parent_delegation_and_tamper(tmp_path, monkeypatch):
    intake = pin(tmp_path / "intake.json", {"filings": []})
    financial = [eps()]
    sources = {}
    for name, value in [
        ("financial_inputs", financial),
        ("securities", []),
        ("prices", []),
        ("selections", []),
        ("derived_inputs", [{"cik": "0000000001", "value": None, "reason": "SHARE_BASIS_UNKNOWN"}]),
    ]:
        ref = pin(tmp_path / (name + ".json"), value)
        sources[name] = {"path": Path(ref["path"]).name, "sha256": ref["sha256"]}
    original_parent = pin(tmp_path / "original-parent.json", {})
    export = pin(tmp_path / "price-export.json", {})
    parent = pin(
        tmp_path / "market_input_manifest.json",
        {
            "schema_version": publication.SCHEMA,
            "publication_id": "original-common109",
            "prepared_at": "2026-11-14T00:00:00+00:00",
            "financial_as_of": "2026-10-25",
            "companies": [{"cik": "0000000001", "ticker": "TEST", "intake": intake}],
            "parent": original_parent,
            "price_export": export,
            "files": sources,
        },
    )
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = publication.publish_market_input_assessment(parent, tmp_path / "overlay")
    assert all(p.read_bytes() == data for p, data in before.items())
    manifest = publication.pinned_json(result)
    assert manifest["parent"] == parent
    assert {p.name for p in (tmp_path / "overlay").iterdir()} == {
        "assessments.json",
        "market_input_assessment_manifest.json",
    }
    reader = publication.MarketInputAssessmentReader(result["path"], result["sha256"])
    query = reader.query("0000000001")
    assert query["financial_inputs"] == financial
    assert query["derived_inputs"][0]["reason"] == "SHARE_BASIS_UNKNOWN"
    assert query["assessment"]["reported_12m"]["reason"] == "NO_ELIGIBLE_FINANCIAL_REPORT"
    with pytest.raises(FileExistsError):
        publication.publish_market_input_assessment(parent, tmp_path / "overlay")
    (tmp_path / "market_input_manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        reader.query("0000000001")


def test_quarter_conflicts_distinct_classes_units_and_future_are_distinct_diagnostics():
    rows = four()
    other = copy.deepcopy(rows[0])
    other["value"] = "7"
    other["observation_id"] = "conflict"
    assert (
        assess.assess_four_quarters(rows + [other], anchor(), "2026-10-25")["reason"]
        == "AMBIGUOUS_DIRECT_QUARTER"
    )
    other_class = copy.deepcopy(rows)
    for row in other_class:
        row["canonical_dimensions"] = [
            [
                "http://fasb.org/us-gaap/2026",
                assess.CLASS_AXIS,
                "http://issuer/2026",
                "issuer:ClassCMember",
                None,
                "EXPLICIT",
                "false",
            ]
        ]
        row["observation_id"] += "-class-c"
    result = assess.assess_four_quarters(rows + other_class, anchor(), "2026-10-25")
    assert result["reason"] == "SCOPE_SELECTION_REQUIRED"
    assert all(
        s["financial_input_status"] == "FOUR_DIRECT_QUARTERS_PRESENT" for s in result["series"]
    )
    rows[-1]["filed_date"] = "2026-11-01"
    assert (
        assess.assess_four_quarters(rows, anchor(), "2026-10-25")["reason"]
        == "MISSING_DIRECT_QUARTER"
    )
    rows = four()
    for row in rows:
        row["unit"] = ['["iso4217:EUR"]', '["xbrli:shares"]']
    assert (
        assess.assess_four_quarters(rows, anchor(), "2026-10-25")["reason"] == "UNIT_NOT_COMPATIBLE"
    )


def test_header_common_class_member_exact_namespace_and_ambiguous_title():
    concepts, facts, contexts, dims = header_fixture()
    concepts["common"]["qname"] = "us-gaap:CommonClassAMember"
    kwargs = {
        "cik": "0000000001",
        "securities": [{"cik": "0000000001", "ticker": "SAME", "security_id": "US:SAME"}],
        "filing": {"filing_id": "filing"},
        "concepts": concepts,
        "facts": facts,
        "contexts": contexts,
        "dimensions": dims,
        "source": {},
    }
    links = assess.link_security_headers(**kwargs)
    assert next(r for r in links if r["context_id"] == "stock")["instrument_kind"] == "COMMON_STOCK"
    concepts["common"]["namespace_uri"] = "http://custom-issuer/2026"
    assert (
        next(r for r in assess.link_security_headers(**kwargs) if r["context_id"] == "stock")[
            "instrument_kind"
        ]
        == "UNKNOWN"
    )
    facts.append(dict(facts[1], fact_id="different-title", value_text="Conflicting title"))
    dims.append(dict(dims[1], fact_id="different-title"))
    assert (
        next(r for r in assess.link_security_headers(**kwargs) if r["context_id"] == "stock")[
            "status"
        ]
        == "HEADER_MATCH_CLASS_UNCONFIRMED"
    )


def test_analytical_cover_still_discovers_latest_intake_headers_and_preserves_same_day(tmp_path):
    import polars as pl

    cik = "0000000001"
    concepts, facts, contexts, dims = header_fixture()
    entries = []
    for ordinal, filed in [
        (1, "2026-10-20"),
        (2, "2026-10-20"),
        (3, "2026-09-01"),
        (4, "2026-11-01"),
    ]:
        accession = f"0000000001-26-{ordinal:06d}"
        root = tmp_path / "snapshots" / cik / accession.replace("-", "")
        root.mkdir(parents=True)
        pin(root / "layer1_manifest.json", {"cik": cik, "accession": accession, "form": "10-Q"})
        filing = {
            "cik": cik,
            "accession": accession,
            "filed_date": filed,
            "form": "10-Q",
            "filing_id": "filing",
            "report_date": "2026-09-30",
        }
        records = {
            "filing": [filing],
            "concept": [dict(c, raw_concept_id=k) for k, c in concepts.items()],
            "fact": facts,
            "context": [dict(c, context_id=k) for k, c in contexts.items()],
            "dimension_fact": dims,
        }
        for name, rows in records.items():
            pl.DataFrame(rows).write_parquet(root / (name + ".parquet"))
        entries.append({"filing": filing, "status": "REUSED", "source_run": str(tmp_path)})
    intake = pin(tmp_path / "intake.json", {"filings": entries})
    analytical_cover = {
        "cik": cik,
        "input_id": "outstanding_common_shares_cover",
        "source": {"analysis_manifest": {"path": "prepared-only"}},
        "status": "AVAILABLE_REPORTED",
    }
    tables = assess.RawAssessmentTables()
    result = assess.assess_company(
        [analytical_cover],
        [{"cik": cik, "ticker": "SAME", "security_id": "US:SAME"}],
        cik=cik,
        financial_as_of="2026-10-25",
        intake_pin=intake,
        tables=tables,
    )
    assert len(result["security_header_links"]) == 4  # Two contexts in each latest same-day filing.
    assert {r["source"]["accession"] for r in result["security_header_links"]} == {
        "0000000001-26-000001",
        "0000000001-26-000002",
    }
    assert len(tables.pins) == 10
    assert all(
        r["source"]["raw_manifest"] and len(r["source"]["raw_tables"]) == 5
        for r in result["security_header_links"]
    )
    # The same chosen filing must still honor an existing parent cover-table pin.
    link = result["security_header_links"][0]
    bad_source = copy.deepcopy(link["source"])
    bad_source["raw_tables"]["fact"]["sha256"] = "0" * 64
    raw_cover = dict(analytical_cover, source=bad_source)
    with pytest.raises(ValueError, match="parent pin"):
        assess.assess_company(
            [raw_cover],
            [{"cik": cik, "ticker": "SAME", "security_id": "US:SAME"}],
            cik=cik,
            financial_as_of="2026-10-25",
            intake_pin=intake,
            tables=assess.RawAssessmentTables(),
        )
