"""Real cached filings prove the default build returns calculated consumer data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl.history import HistoryPublicationReader, _write_json, build_history


def test_default_history_build_connects_reported_and_derived_consumer(tmp_path: Path) -> None:
    intake_path = Path("/home/plusbdw/user_work/projects/sec_xbrl/data/processed/history_runs/20260906_five_company/history_intake.json")
    if not intake_path.exists():
        pytest.skip("explicit five-company cached fixture is unavailable")
    original = json.loads(intake_path.read_text())
    items = [item for item in original["filings"] if item["filing"]["cik"] == "0001045810"
             and item["filing"]["report_date"] in {"2024-10-27", "2025-01-26"}]
    assert len(items) == 2
    company = {**next(company for company in original["plan"]["companies"] if company["ticker"] == "NVDA"),
               "filings": [item["filing"] for item in items]}
    intake = {**original, "plan": {**original["plan"], "companies": [company]}, "filings": items}
    fixture = tmp_path / "intake.json"
    _write_json(fixture, intake)
    output = build_history(intake_manifest=fixture, output_root=tmp_path / "default-build")
    assert output.name == "panels"
    reader = HistoryPublicationReader(output)
    reader.verify_all()
    result = reader.load(ticker="NVDA", period_class="QTD_3M")
    q4 = next(column for column in result.columns if column["fiscal_year"] == 2025 and column["fiscal_quarter"] == 4)
    revenue = next(cell for cell in result.cells if cell["fiscal_time_series_column_id"] == q4["fiscal_time_series_column_id"]
                   and cell.get("value_lineage", {}).get("raw_concept_qname") == "us-gaap:Revenues"
                   and not cell["value_lineage"].get("canonical_dimension_signature"))
    assert revenue["value_numeric"] == "39331000000"
    assert revenue["value_status"] == "DERIVED"
    assert revenue["value_lineage"]["source_fact_ids"]
    assert q4["actual_start_date"] == "2024-10-28"
    assert q4["actual_end_date"] == "2025-01-27"
    assert reader.manifest["derived_quarter"]["count"] > 0
    assert build_history(intake_manifest=fixture, output_root=tmp_path / "default-build") == output
