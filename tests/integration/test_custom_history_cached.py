"""A real financial custom concept must reach the consumer as one time-series row."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.history import HistoryPublicationReader, _write_json, build_history
from sec_xbrl.longitudinal import Layer2PublicationReader


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
    t1 = Layer2PublicationReader().load(consumer.parent / "t1" / consumer.parent.name)
    mapped = next(row for row in t1.records("company_concept_map")
                  if row.get("source_qname") == "amzn:FulfillmentExpense" and row["method"] == "CUSTOM_SEMANTIC_NETWORK_CONTINUITY")
    evidence = mapped["evidence"]
    assert evidence["qualified_network_signature"]
    assert evidence["prior_relationship_ids"]
    source_item = next(item for item in items if item["filing"]["report_date"] == "2023-06-30")
    raw_dir = Path(source_item["source_run"]) / "snapshots" / source_item["filing"]["cik"] / source_item["filing"]["accession"].replace("-", "")
    raw_edges = pl.read_parquet(raw_dir / "relationship.parquet").to_dicts()
    expected_ids = {edge["relationship_id"] for edge in raw_edges
                    if mapped["source_raw_id"] in (edge["from_raw_concept_id"], edge["to_raw_concept_id"])}
    assert set(evidence["source_relationship_ids"]) == expected_ids
