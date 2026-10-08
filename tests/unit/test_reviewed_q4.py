from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.analysis import _apply_reviewed_q4, open_analysis, prepare_analysis
from sec_xbrl.analytics import reviewed_q4 as module
from sec_xbrl.analytics.reviewed_q4 import (
    ReviewedQ4Reader,
    generate_reviewed_q4,
    publish_reviewed_q4,
)
from sec_xbrl.consumer.export import export_snapshot, prepare_axis_snapshot


def _lineage(period: str, value: str, fact: str, filing: str, accession: str) -> dict:
    return {
        "selected_source_fact_id": fact,
        "source_filing_id": filing,
        "source_snapshot_id": f"l1:0000000001:{accession.replace('-', '')}:abcdef0123456789",
        "accession": accession,
        "filed_date": "2024-02-01" if period == "FY" else "2023-11-01",
        "selection_view": "AS_FILED",
        "selection_as_of_date": "2026-09-06",
        "period_class": period,
        "source_type": "REPORTED",
        "comparative_type": "CURRENT_FOCUS",
        "mapping_review_required": False,
        "context_start_date": "2023-01-01",
        "context_end_date": "2024-01-01" if period == "FY" else "2023-10-02",
        "company_canonical_concept_id": "concept:revenue",
        "canonical_dimension_signature": [["axis", "member", None, "EXPLICIT", "false"]],
        "raw_dimension_signature": [["raw-axis", "raw-member", None, "EXPLICIT", "false"]],
        "unit_numerator_measures": '["iso4217:USD"]',
        "unit_denominator_measures": "[]",
        "basis_version": "products-v1",
        "structural_version": "structure-v1",
        "recast_version": "recast-v1",
        "value_numeric": value,
    }


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, dict, dict]:
    history = tmp_path / "history"
    history.mkdir(parents=True)
    (history / "history_manifest.json").write_text('{"version":"synthetic"}\n')
    fy = _lineage("FY", "1000", "fy-fact", "fy-filing", "0000000001-24-000001")
    ytd = _lineage("YTD_9M", "700", "ytd-fact", "ytd-filing", "0000000001-23-000001")
    def cell(lineage: dict, identity: str) -> dict:
        return {
            "fiscal_time_series_cell_id": identity,
            "fiscal_time_series_row_id": "epoch",
            "value_status": "REPORTED",
            "definition": {"company_cik": "0000000001", "label": "test:Member"},
            "value_lineage": lineage,
        }
    pair = {
        "selection_view": "AS_FILED",
        "selection_as_of_date": "2026-09-06",
        "fiscal_year": 2024,
        "mapping_epoch": "epoch",
        "frozen_report_node_id": "old-node",
        "member_qname": "test:Member",
        "fy_cell": cell(fy, "fy-cell"),
        "ytd_cell": cell(ytd, "ytd-cell"),
        "fy": {"accession": fy["accession"], "value_lineage": fy, "raw_fact": {"fact_id": "fy-fact"},
               "snapshot_path": str(tmp_path / "fy-snapshot"), "snapshot_manifest_sha256": "a" * 64,
               "table_textblock_fact_id": "fy-table"},
        "ytd_9m": {"accession": ytd["accession"], "value_lineage": ytd, "raw_fact": {"fact_id": "ytd-fact"},
                   "snapshot_path": str(tmp_path / "ytd-snapshot"), "snapshot_manifest_sha256": "b" * 64,
                   "table_textblock_fact_id": "ytd-table"},
        "candidate_value": "300",
        "semantic_status": "LEAD_REVIEW_NOT_YET_APPLIED",
    }
    parent_sha = hashlib.sha256((history / "history_manifest.json").read_bytes()).hexdigest()
    evidence = {
        "history_publication": str(history.resolve()),
        "history_manifest_sha256": parent_sha,
        "pairs": [pair],
        "tables": [
            {"accession": fy["accession"], "fact_id": "fy-table", "text": "annual product table",
             "raw_fact": {"fact_id": "fy-table"}},
            {"accession": ytd["accession"], "fact_id": "ytd-table", "text": "nine month product table",
             "raw_fact": {"fact_id": "ytd-table"}},
        ],
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(evidence))
    scope = {"selection_view": "AS_FILED", "selection_as_of_date": "2026-09-06", "fiscal_year": 2024,
             "mapping_epoch": "epoch", "member_qname": "test:Member", "fy_fact_id": "fy-fact",
             "ytd_fact_id": "ytd-fact"}
    approval = {
        "decision_id": "review", "scope": scope, "decision": module.APPROVAL, "reviewer": "lead",
        "known_at": "2026-10-08T00:00:00+00:00", "purpose": "product revenue Q4",
        "policy_version": "review-v1", "additivity": "REVENUE_DURATION_AMOUNT",
        "basis_compatibility": "exact same scope", "fy_accession": fy["accession"],
        "ytd_accession": ytd["accession"], "fy_snapshot_manifest_sha256": "a" * 64,
        "ytd_snapshot_manifest_sha256": "b" * 64, "fy_evidence_fact_id": "fy-table",
        "ytd_evidence_fact_id": "ytd-table", "approved_expected_value": "300",
    }
    ledger_data = {
        "source_evidence_path": str(source.resolve()),
        "source_evidence_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "history_publication": str(history.resolve()), "history_manifest_sha256": parent_sha,
        "approval_count": 1, "distinct_product_period_values": 1, "excluded_scope_notes": [],
        "approvals": [approval],
    }
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(ledger_data))
    return history, source, ledger, evidence, ledger_data


@pytest.fixture
def attested(monkeypatch):
    reader = SimpleNamespace(
        manifest={"tables": [{"ticker": "TEST", "cik": "0000000001"}]},
        verify_all=lambda: None,
    )
    monkeypatch.setattr(module, "open_history_publication", lambda path: reader)
    monkeypatch.setattr(module, "_attest_parent_cell", lambda *args, **kwargs: None)
    def snapshot(source, lineage, cache, snapshots):
        table_id = source["table_textblock_fact_id"]
        cache[Path(source["snapshot_path"])] = SimpleNamespace(
            records=lambda name: [source["raw_fact"], {"fact_id": table_id}]
        )
    monkeypatch.setattr(module, "_attest_snapshot", snapshot)
    monkeypatch.setattr(module, "_q4_materialized", lambda *args, **kwargs: False)
    return reader


def test_exact_approval_and_missing_review(tmp_path: Path, attested) -> None:
    history, source, ledger, _, ledger_data = _inputs(tmp_path)
    build = generate_reviewed_q4(
        history_publication=history, source_evidence=source, review_ledger=ledger
    )
    assert [row["value_numeric"] for row in build.derived] == ["300"]
    assert build.derived[0]["mapping_epoch"] == "epoch"
    assert build.derived[0]["canonical_dimension_signature"] == [
        ["axis", "member", None, "EXPLICIT", "false"]
    ]
    ledger_data["approvals"] = []
    ledger_data["approval_count"] = 0
    ledger_data["distinct_product_period_values"] = 0
    ledger.write_text(json.dumps(ledger_data))
    build = generate_reviewed_q4(
        history_publication=history, source_evidence=source, review_ledger=ledger
    )
    assert not build.derived
    assert build.exclusions[0]["reason"] == "EXACT_SOURCE_PAIR_REVIEW_REQUIRED"


def test_input_hash_and_parent_tamper_fail_closed(tmp_path: Path, attested) -> None:
    history, source, ledger, evidence, _ = _inputs(tmp_path)
    evidence["pairs"][0]["candidate_value"] = "999"
    source.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="exact source evidence"):
        generate_reviewed_q4(history_publication=history, source_evidence=source, review_ledger=ledger)
    _, source, ledger, _, _ = _inputs(tmp_path / "other")
    other_history = tmp_path / "other" / "history"
    (other_history / "history_manifest.json").write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match="parent history"):
        generate_reviewed_q4(
            history_publication=other_history, source_evidence=source, review_ledger=ledger
        )


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("unit", "INCOMPATIBLE_UNIT_NUMERATOR"),
        ("denominator", "INCOMPATIBLE_UNIT_DENOMINATOR"),
        ("period", "PERIOD_CLASS_MISMATCH"),
        ("mapping", "MAPPING_REVIEW_REQUIRED"),
        ("dimension", "INCOMPATIBLE_CANONICAL_DIMENSION_SIGNATURE"),
        ("future", "SOURCE_FILED_AFTER_SELECTION_AS_OF"),
        ("dates", "ACTUAL_START_DATE_MISMATCH"),
        ("view", "SELECTION_VIEW_MISMATCH"),
    ],
)
def test_full_structural_scope_rejects_defects(tmp_path: Path, attested, defect: str, reason: str) -> None:
    history, source, ledger, evidence, ledger_data = _inputs(tmp_path)
    pair = evidence["pairs"][0]
    ytd = pair["ytd_cell"]["value_lineage"]
    if defect == "unit":
        ytd["unit_numerator_measures"] = '["iso4217:EUR"]'
    elif defect == "denominator":
        ytd["unit_denominator_measures"] = '["xbrli:shares"]'
    elif defect == "period":
        ytd["period_class"] = "QTD_3M"
    elif defect == "mapping":
        ytd["mapping_review_required"] = True
    elif defect == "dimension":
        ytd["canonical_dimension_signature"] = [["axis", "other", None, "EXPLICIT", "false"]]
    elif defect == "future":
        ytd["filed_date"] = "2027-01-01"
    elif defect == "dates":
        ytd["context_start_date"] = "2023-01-02"
    else:
        ytd["selection_view"] = "LATEST_REPORTED"
    pair["ytd_9m"]["value_lineage"] = ytd
    source.write_text(json.dumps(evidence))
    ledger_data["source_evidence_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    ledger.write_text(json.dumps(ledger_data))
    with pytest.raises(ValueError, match=reason):
        generate_reviewed_q4(history_publication=history, source_evidence=source, review_ledger=ledger)


def test_consumer_direct_cell_precedence_and_trace() -> None:
    dimensions = [["axis", "member", None, "EXPLICIT", "false"]]
    node = {"node_id": "node", "row_id": "epoch", "period_class": "QTD_3M",
            "canonical_concept_id": "concept:revenue", "dimensions": dimensions,
            "canonical_dimension_signature": dimensions}
    column = {"fiscal_time_series_column_id": "q4", "fiscal_year": 2024,
              "fiscal_quarter": 4, "period_class": "QTD_3M"}
    derived = {
        "ticker": "TEST", "selection_view": "AS_FILED", "selection_as_of_date": "2026-09-06",
        "fiscal_year": 2024, "mapping_epoch": "epoch", "company_canonical_concept_id": "concept:revenue",
        "canonical_dimension_signature": dimensions, "source_inputs": [{"unit_numerator_measures": '["iso4217:USD"]',
            "unit_denominator_measures": "[]", "basis_version": "products"}], "derived_cell_id": "derived",
        "actual_start_date": "2023-10-02", "actual_end_date": "2024-01-01", "value_numeric": "300",
        "source_filing_ids": ["fy", "ytd"], "review_id": "review", "formula": "FY - YTD_9M",
        "derivation_rule_version": "rule", "source_fact_ids": ["f1", "f2"],
        "source_snapshot_ids": ["s1", "s2"], "source_table_evidence": [], "member_qname": "test:Member",
        "reviewer": "lead", "reviewed_at": "now", "review_purpose": "display",
        "review_policy_version": "review", "additivity": "revenue", "basis_compatibility": "exact",
    }
    existing = {"node_id": "node", "column_id": "q4", "cell_id": "reported"}
    cells, traces = [existing], []
    _apply_reviewed_q4(ticker="TEST", view="AS_FILED", as_of="2026-09-06", derived=[derived],
                       columns=[column], cells=cells, traces=traces, nodes={"node": node}, years={2024},
                       source_publication="reviewed")
    assert cells == [existing] and not traces
    cells.clear()
    _apply_reviewed_q4(ticker="TEST", view="AS_FILED", as_of="2026-09-06", derived=[derived],
                       columns=[column], cells=cells, traces=traces, nodes={"node": node}, years={2024},
                       source_publication="reviewed")
    assert cells[0]["status"] == "DERIVED" and cells[0]["value"] == "300"
    assert traces[0]["value_lineage"]["source_inputs"] == derived["source_inputs"]
    assert traces[0]["value_lineage"]["review"]["review_id"] == "review"


@pytest.mark.skipif(not os.getenv("SEC_XBRL_RUN_REVIEWED_Q4_INTEGRATION"), reason="explicit cached integration")
def test_cached_nvda_source_to_api_snapshot_xlsx(tmp_path: Path) -> None:
    evidence_root = Path("/home/plusbdw/user_work/projects/sec_xbrl/data/processed/universe_runs/20261008_initial/q4_lead_review")
    history = Path("/home/plusbdw/user_work/projects/sec_xbrl/data/processed/analytical/history/five_company_custom_continuity_v5/panels")
    q4 = publish_reviewed_q4(history_publication=history, source_evidence=evidence_root / "source_pairs.json",
                             review_ledger=evidence_root / "lead_approval.json", destination=tmp_path / "reviewed-q4")
    reviewed = ReviewedQ4Reader(q4).records("derived")
    for view in ("AS_FILED", "LATEST_REPORTED"):
        values = {(row["fiscal_year"], row["member_qname"]): Decimal(row["value_numeric"])
                  for row in reviewed if row["selection_view"] == view}
        assert sum(value for (year, _), value in values.items() if year == 2024) == Decimal(22103000000)
        top = {"nvda:DataCenterMember", "nvda:GamingMember", "nvda:ProfessionalVisualizationMember",
               "nvda:AutomotiveMember", "nvda:OEMAndOtherMember"}
        assert sum(value for (year, member), value in values.items()
                   if year == 2026 and member in top) == Decimal(68127000000)
        assert (values[(2026, "nvda:ComputeMember")] + values[(2026, "nvda:NetworkingMember")]
                == values[(2026, "nvda:DataCenterMember")])
    analysis = prepare_analysis(publication=history, destination=tmp_path / "analysis", tickers=("NVDA",),
                                fiscal_start=2024, fiscal_end=2026, reviewed_q4_publication=q4)
    client = open_analysis(analysis)
    derived = []
    for view in ("AS_FILED", "LATEST_REPORTED"):
        overview = client.overview("NVDA", fiscal_start=2024, fiscal_end=2026, view=view)
        groups = client.list_breakdowns("revenue", context=overview["context"], include_hidden=True)["groups"]
        groups = [group for group in groups if group.get("lens_type") == "DIMENSIONAL_VIEW"]
        for group in groups:
            response = client.axis_timeseries("NVDA", group["node_id"], context=overview["context"])
            derived.extend(cell for row in response["rows"] for cell in row["cells"]
                           if cell.get("status") == "DERIVED" and cell.get("review_id"))
        if groups:
            snapshot = prepare_axis_snapshot(client, "NVDA", groups[0]["node_id"], context=overview["context"])
            export_snapshot(snapshot, tmp_path / f"{view}.xlsx")
    assert len({cell["cell_id"] for cell in derived}) == 32
    assert (tmp_path / "AS_FILED.xlsx").is_file() and (tmp_path / "LATEST_REPORTED.xlsx").is_file()
