"""A real financial custom concept must reach the consumer as one time-series row."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl.history import HistoryPublicationReader, _write_json, build_history


def test_cached_custom_expense_is_connected_in_default_consumer(tmp_path: Path) -> None:
    source = Path("/home/plusbdw/user_work/projects/sec_xbrl/data/processed/history_runs/20260906_five_company/history_intake.json")
    if not source.exists():
        pytest.skip("explicit cached company-history fixture is unavailable")
    intake = json.loads(source.read_text())
    items = [item for item in intake["filings"] if item["ticker"] == "AMZN" and item["filing"]["report_date"] in {"2023-03-31", "2023-06-30"}]
    assert len(items) == 2
    company = next(company for company in intake["plan"]["companies"] if company["ticker"] == "AMZN")
    company = {**company, "filings": [item["filing"] for item in items]}
    selected = {**intake, "plan": {**intake["plan"], "companies": [company]}, "filings": items}
    fixture = tmp_path / "intake.json"
    _write_json(fixture, selected)
    consumer = build_history(intake_manifest=fixture, output_root=tmp_path / "custom-history")
    result = HistoryPublicationReader(consumer).load(ticker="AMZN", period_class="QTD_3M")
    values = [cell for cell in result.cells if (cell.get("value_lineage") or {}).get("raw_concept_qname") == "amzn:FulfillmentExpense"
              and not cell["value_lineage"].get("canonical_dimension_signature")]
    assert len(values) == 2
    assert len({cell["fiscal_time_series_row_id"] for cell in values}) == 1
    assert len({cell["fiscal_time_series_column_id"] for cell in values}) == 2
    assert all(cell["value_status"] == "REPORTED" and cell["value_numeric"] is not None for cell in values)
    assert len({cell["value_lineage"]["source_filing_id"] for cell in values}) == 2
    assert all(cell["binding"]["concept_origin"] == "CUSTOM_CONCEPT" for cell in values)
