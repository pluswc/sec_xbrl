from __future__ import annotations

import copy
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from sec_xbrl.analysis import open_analysis, prepare_analysis
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
