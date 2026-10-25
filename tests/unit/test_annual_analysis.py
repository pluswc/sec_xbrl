from __future__ import annotations

import copy
import inspect
import json
import subprocess
from decimal import localcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from sec_xbrl.analysis import (
    _select_expanded_annual_core,
    open_analysis,
    prepare_analysis,
    render_analysis,
)
from sec_xbrl.consumer.export import export_snapshot, prepare_axis_snapshot


def _reader() -> SimpleNamespace:
    columns = tuple(
        {
            "fiscal_time_series_column_id": f"fy-{year}",
            "fiscal_year": year,
            "fiscal_quarter": 4,
            "period_class": "FY",
            "column_status": "AVAILABLE",
            "fiscal_label": f"FY{year} Q4",
        }
        for year in (2024, 2025)
    )
    rows = (
        {"fiscal_time_series_row_id": "total", "raw_concept_qname": "us-gaap:Revenues",
         "mapping_review_required": False, "row_identity": ["JOIN"]},
        {"fiscal_time_series_row_id": "member", "raw_concept_qname": "us-gaap:Revenues",
         "mapping_review_required": False, "row_identity": ["JOIN"]},
    )
    cells = []
    for year in (2024, 2025):
        for row, dimensions, value in (("total", [], "1000"),
                                       ("member", [["axis", "member-id", None, "EXPLICIT", "false"]], "600")):
            lineage = {
                "selected_source_fact_id": f"{row}-{year}",
                "source_filing_id": f"filing-{year}",
                "accession": f"accession-{year}",
                "selection_view": "AS_FILED",
                "selection_as_of_date": "2026-09-06",
                "context_start_date": f"{year-1}-01-01",
                "context_end_date": f"{year}-01-01",
                "period_class": "FY",
                "source_type": "REPORTED",
                "raw_concept_id": "revenue",
                "raw_concept_qname": "us-gaap:Revenues",
                "raw_concept_is_standard": True,
                "raw_concept_taxonomy_family": "us-gaap",
                "raw_concept_data_type": "xbrli:monetaryItemType",
                "company_canonical_concept_id": "canonical-revenue",
                "canonical_dimension_signature": dimensions,
                "raw_dimension_signature": dimensions,
                "unit_numerator_measures": '["iso4217:USD"]',
                "unit_denominator_measures": "[]",
                "mapping_review_required": False,
                "value_numeric": value,
            }
            cells.append({
                "fiscal_time_series_cell_id": f"{row}-{year}",
                "fiscal_time_series_row_id": row,
                "fiscal_time_series_column_id": f"fy-{year}",
                "value_status": "REPORTED",
                "value_numeric": value,
                "value_lineage": lineage,
                "comparability_status": "COMPARABLE",
            })
    result = SimpleNamespace(
        columns=columns, rows=rows, cells=tuple(cells),
        scope={"selection_as_of_date": "2026-09-06"},
    )
    return SimpleNamespace(
        root=Path("/synthetic-history"),
        manifest={"tables": [{"ticker": "TEST", "period_class": "FY"}]},
        load=lambda **kwargs: result,
    )


def _core_candidate_fixture(
    name: str,
    qname: str,
    value: str,
    *,
    primary: bool,
    role: str = "role:is",
) -> tuple[dict, dict, dict]:
    cell = {
        "cell_id": name,
        "node_id": f"node-{name}",
        "column_id": "fy-2025",
        "cik": "0000000001",
        "ticker": "TEST",
        "period_class": "FY",
        "selection_view": "LATEST_REPORTED",
        "as_of": "2026-10-08",
        "status": "REPORTED",
        "value": value,
        "unit": ['["iso4217:USD"]', "[]"],
        "dimensions": [],
        "start": "2024-01-01",
        "end": "2025-01-01",
        "source_fact_id": f"fact-{name}",
        "source_filing_ids": ["filing"],
        "primary_statement_evidence": [
            {
                "statement_types": ["IS"],
                "source_filing_id": "filing",
                "role_uri": role,
            }
        ] if primary else [],
    }
    node = {
        "node_id": f"node-{name}",
        "concept": qname,
        "dimensions": [],
        "mapping_review_required": False,
    }
    trace = {
        "cell_id": name,
        "value_lineage": {
            "raw_concept_id": f"concept-{name}",
            "raw_concept_qname": qname,
            "raw_concept_is_standard": True,
            "raw_concept_taxonomy_family": "us-gaap",
            "mapping_review_required": False,
            "source_filing_id": "filing",
            "source_snapshot_id": "l1:0000000001:000000000126000001:fixture",
            "selected_source_fact_id": f"fact-{name}",
            "primary_statement_evidence": copy.deepcopy(
                cell["primary_statement_evidence"]
            ),
        },
    }
    return cell, node, trace


def _select_fixture(
    candidates: list[tuple[dict, dict, dict]],
    *,
    row_id: str = "revenue",
    relationships: list[dict] | None = None,
    extra_sources: list[tuple[dict, dict, dict]] | None = None,
):
    nodes = {node["node_id"]: node for _, node, _ in [*candidates, *(extra_sources or [])]}
    traces = {trace["cell_id"]: trace for _, _, trace in [*candidates, *(extra_sources or [])]}
    source_index = {}
    for cell, _node, trace in [*candidates, *(extra_sources or [])]:
        lineage = trace["value_lineage"]
        source_index.setdefault(
            (lineage["source_filing_id"], lineage["raw_concept_id"]), []
        ).append((cell["node_id"], cell, []))
    return _select_expanded_annual_core(
        spec={"row_id": row_id},
        matches=[row[0] for row in candidates],
        nodes=nodes,
        trace_by_cell=traces,
        relationships=relationships or [],
        source_index=source_index,
        expected_scope={
            "cik": "0000000001",
            "ticker": "TEST",
            "column_id": "fy-2025",
            "period_class": "FY",
            "selection_view": "LATEST_REPORTED",
            "as_of": "2026-10-08",
            "start": "2024-01-01",
            "end": "2025-01-01",
        },
    )


def test_expanded_annual_core_prefers_unique_typed_primary_statement_candidate() -> None:
    note = _core_candidate_fixture("note", "us-gaap:Revenues", "100", primary=False)
    statement = _core_candidate_fixture(
        "statement",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    selected, reason, candidates, evidence = _select_fixture([note, statement])

    assert selected["cell_id"] == "statement"
    assert reason is None
    assert evidence == {"method": "UNIQUE_TYPED_PRIMARY_STATEMENT", "statement_type": "IS"}
    assert {row["candidate_status"] for row in candidates} == {
        "PRIMARY_STATEMENT_EVIDENCE_MISSING",
        "PRIMARY_STATEMENT_ELIGIBLE",
    }


def test_expanded_annual_revenue_selects_exact_reported_cal_parent() -> None:
    parent = _core_candidate_fixture("total", "us-gaap:Revenues", "110", primary=True)
    revenue = _core_candidate_fixture(
        "contract",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    other = _core_candidate_fixture("other", "us-gaap:OtherIncome", "10", primary=True)
    relationships = [
        {
            "network_type": "CAL",
            "filing_id": "filing",
            "role_uri": "role:is",
            "from_raw_concept_id": "concept-total",
            "to_raw_concept_id": "concept-contract",
            "weight": "1",
            "relationship_id": "cal-contract",
        },
        {
            "network_type": "CAL",
            "filing_id": "filing",
            "role_uri": "role:is",
            "from_raw_concept_id": "concept-total",
            "to_raw_concept_id": "concept-other",
            "weight": "1.0",
            "relationship_id": "cal-other",
        },
    ]
    selected, reason, _candidates, evidence = _select_fixture(
        [parent, revenue], relationships=relationships, extra_sources=[other]
    )

    assert selected["cell_id"] == "total"
    assert reason is None
    assert evidence["method"] == "REPORTED_REVENUE_CAL_TOTAL"
    assert evidence["relationship_ids"] == ["cal-contract", "cal-other"]
    assert evidence["reported_parent_value"] == evidence["reported_child_sum"] == "110"


def test_reported_revenue_total_fails_closed_for_weight_role_scope_and_footing() -> None:
    parent = _core_candidate_fixture("total", "us-gaap:Revenues", "110", primary=True)
    revenue = _core_candidate_fixture(
        "contract",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    other = _core_candidate_fixture("other", "us-gaap:OtherIncome", "10", primary=True)
    base = [
        {
            "network_type": "CAL", "filing_id": "filing", "role_uri": "role:is",
            "from_raw_concept_id": "concept-total", "to_raw_concept_id": "concept-contract",
            "weight": "1", "relationship_id": "cal-contract",
        },
        {
            "network_type": "CAL", "filing_id": "filing", "role_uri": "role:is",
            "from_raw_concept_id": "concept-total", "to_raw_concept_id": "concept-other",
            "weight": "1", "relationship_id": "cal-other",
        },
    ]
    mutations = (
        lambda rels, extra: rels[0].update(weight="-1"),
        lambda rels, extra: rels[0].update(role_uri="role:note"),
        lambda rels, extra: extra[0][0].update(unit=['["iso4217:EUR"]', "[]"]),
        lambda rels, extra: extra[0][0].update(value="9"),
    )
    for mutate in mutations:
        relationships = copy.deepcopy(base)
        sources = copy.deepcopy([other])
        mutate(relationships, sources)
        selected, reason, _candidates, evidence = _select_fixture(
            copy.deepcopy([parent, revenue]),
            relationships=relationships,
            extra_sources=sources,
        )
        assert selected is None
        assert reason is not None
        assert evidence is None

    selected, reason, _candidates, evidence = _select_fixture(
        [parent, revenue], row_id="operating_income", relationships=base, extra_sources=[other]
    )
    assert selected is None and reason == "MULTIPLE_CANDIDATES" and evidence is None


def test_expanded_annual_core_validates_all_candidate_scope_before_priority() -> None:
    note = _core_candidate_fixture("note", "us-gaap:Revenues", "100", primary=False)
    statement = _core_candidate_fixture(
        "statement",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    mutations = (
        lambda row: row[0].update(start="2020-01-01", end="2021-01-01"),
        lambda row: (
            row[0].update(source_filing_ids=["other-filing"]),
            row[2]["value_lineage"].update(source_filing_id="other-filing"),
        ),
        lambda row: row[0].update(start=None),
    )
    for mutate in mutations:
        changed = copy.deepcopy(note)
        mutate(changed)
        selected, reason, candidates, evidence = _select_fixture(
            [changed, copy.deepcopy(statement)]
        )
        assert selected is None
        assert reason in {
            "PERIOD_SCOPE_MISMATCH",
            "PERIOD_SCOPE_INCOMPLETE",
            "CANDIDATE_SCOPE_CONFLICT",
        }
        assert len(candidates) == 2
        assert evidence is None


def test_expanded_annual_core_preserves_single_candidate_eligibility_reason() -> None:
    held = _core_candidate_fixture(
        "held",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    held[1]["mapping_review_required"] = True
    held[2]["value_lineage"]["mapping_review_required"] = True

    selected, reason, candidates, evidence = _select_fixture([held])

    assert selected is None
    assert reason == "MAPPING_REVIEW_REQUIRED"
    assert candidates[0]["candidate_status"] == "MAPPING_REVIEW_REQUIRED"
    assert evidence is None


def test_reported_revenue_total_requires_component_and_exact_ambient_free_footing() -> None:
    parent = _core_candidate_fixture("total", "us-gaap:Revenues", "110", primary=True)
    revenue = _core_candidate_fixture(
        "contract",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "100",
        primary=True,
    )
    other = _core_candidate_fixture("other", "us-gaap:OtherIncome", "10.04", primary=True)
    one_child = [{
        "network_type": "CAL",
        "filing_id": "filing",
        "role_uri": "role:is",
        "from_raw_concept_id": "concept-total",
        "to_raw_concept_id": "concept-contract",
        "weight": "1",
        "relationship_id": "cal-contract",
    }]
    selected, reason, _candidates, evidence = _select_fixture(
        copy.deepcopy([parent, revenue]), relationships=one_child
    )
    assert selected is None and reason == "MULTIPLE_CANDIDATES" and evidence is None

    two_children = [
        *one_child,
        {
            "network_type": "CAL",
            "filing_id": "filing",
            "role_uri": "role:is",
            "from_raw_concept_id": "concept-total",
            "to_raw_concept_id": "concept-other",
            "weight": "1",
            "relationship_id": "cal-other",
        },
    ]
    with localcontext() as context:
        context.prec = 3
        selected, reason, _candidates, evidence = _select_fixture(
            copy.deepcopy([parent, revenue]),
            relationships=two_children,
            extra_sources=[other],
        )
    assert selected is None and reason == "MULTIPLE_CANDIDATES" and evidence is None


def test_annual_bundle_isolated_fy_axis_and_xlsx_label(tmp_path: Path, monkeypatch) -> None:
    from sec_xbrl import analysis

    reader = _reader()
    history = tmp_path / "history"
    history.mkdir()
    reader.root = history
    (history / "history_manifest.json").write_text("{}\n")
    monkeypatch.setattr(analysis, "open_history_publication", lambda publication: reader)
    monkeypatch.setattr(analysis, "_raw_material", lambda *args: (
        {"axis": {"qname": "test:ProductAxis"}, "member-id": {"qname": "test:ProductMember"}}, []
    ))
    destination = prepare_analysis(
        publication=history,
        destination=tmp_path / "annual",
        tickers=("TEST",),
        fiscal_start=2024,
        fiscal_end=2025,
        period_mode="ANNUAL",
        configuration={"TEST": {"hierarchies": [{"quarterly_review": "must not apply"}]}},
    )
    client = open_analysis(destination)
    assert client.manifest["period_mode"] == "ANNUAL"
    overview = client.overview("TEST", fiscal_start=2024, fiscal_end=2025, view="AS_FILED")
    assert {row["period_class"] for row in overview["rows"]} == {"FY"}
    assert {column["fiscal_label"] for column in overview["columns"]} == {"FY2024", "FY2025"}
    assert all(metric["status"] == "UNAVAILABLE" for metric in overview["metrics"])
    group = client.list_breakdowns("revenue", context=overview["context"])["groups"][0]
    response = client.axis_timeseries("TEST", group["node_id"], context=overview["context"])
    assert response["period_class"] == "FY"
    assert {cell["period_class"] for row in response["rows"] for cell in row["cells"]} == {"FY"}
    snapshot = prepare_axis_snapshot(client, "TEST", group["node_id"], context=overview["context"])
    output = export_snapshot(snapshot, tmp_path / "annual.xlsx")
    headers = [cell.value for cell in load_workbook(output, read_only=True)["Table"][1]]
    assert "FY2024" in headers and "FY2025" in headers
    assert not any("Q4" in str(value) for value in headers)
    html = tmp_path / "annual.html"
    render_analysis(client, ticker="TEST", destination=html, fiscal_start=2024, fiscal_end=2025)
    rendered = html.read_text(encoding="utf-8")
    assert "<h2>연간 금액</h2>" in rendered
    assert "<h2>분기 금액</h2>" not in rendered
    assert "기준 연도의 금액" in rendered
    assert ">FY2024<br>" in rendered and ">FY2025<br>" in rendered
    assert "FY2024 Q4" not in rendered and "FY2025 Q4" not in rendered
    mixed = copy.deepcopy(next(row for row in client._records("TEST", "AS_FILED", "nodes")
                               if row.get("period_class") == "FY" and row.get("kind") == "VALUE"))
    mixed.update(node_id="mixed", period_class="QTD_3M")
    client._records("TEST", "AS_FILED", "nodes").append(mixed)
    client._records("TEST", "AS_FILED", "edges").append({
        "parent_id": group["node_id"], "child_id": "mixed", "periods": [[2025, 4]],
    })
    with pytest.raises(ValueError, match="one supported prepared period class"):
        client.axis_timeseries("TEST", group["node_id"], context=overview["context"])


def test_quarterly_mode_remains_default_and_rejects_annual_q4_companion(tmp_path: Path) -> None:
    signature = inspect.signature(prepare_analysis)
    assert signature.parameters["period_mode"].default == "QUARTERLY"
    assert signature.parameters["reviewed_q4_publication"].default is None
    with pytest.raises(ValueError, match="only in a quarterly"):
        prepare_analysis(
            publication=tmp_path / "history",
            destination=tmp_path / "annual",
            tickers=("TEST",),
            period_mode="ANNUAL",
            reviewed_q4_publication=tmp_path / "reviewed-q4",
        )


def test_hierarchy_javascript_uses_period_mode_for_all_analytical_labels() -> None:
    source = (Path(__file__).parents[2] / "src/sec_xbrl/display/hierarchy.js").read_text(encoding="utf-8")
    assert "ctx.period_mode==='ANNUAL'?`FY${p[0]}`" in source
    assert "periodNoun=ctx.period_mode==='ANNUAL'?'개 연도':'분기'" in source
    assert ".map(p=>analyticalPeriodLabel(ctx,p))" in source
    assert "text('th',analyticalPeriodLabel(ctx,period))" in source


def test_hierarchy_active_controls_switch_annual_and_restore_quarterly() -> None:
    source = (Path(__file__).parents[2] / "src/sec_xbrl/display/hierarchy.js").read_text(encoding="utf-8")
    function_source = source[source.index("function configureAnalyticalPeriodLanguage"):]
    function_source = function_source[:function_source.index("\nfunction ", 10)]
    program = f"""
const elements={{
  'analytical-mode-option':{{textContent:''}},
  'analytical-empty-hint':{{textContent:''}}
}};
const $=id=>elements[id];
{function_source}
configureAnalyticalPeriodLanguage({{period_mode:'ANNUAL'}});
const annual=[elements['analytical-mode-option'].textContent,elements['analytical-empty-hint'].textContent];
configureAnalyticalPeriodLanguage({{}});
const quarterly=[elements['analytical-mode-option'].textContent,elements['analytical-empty-hint'].textContent];
process.stdout.write(JSON.stringify({{annual,quarterly}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    labels = json.loads(result.stdout)
    assert labels["annual"] == ["연간 비교 · Analytical", "같은 준비 노드만 연결 · 빈 연도는 미준비"]
    assert labels["quarterly"] == ["분기 비교 · Analytical", "같은 준비 노드만 연결 · 빈 분기는 미준비"]
