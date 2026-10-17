from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from sec_xbrl.analytics import (
    CompanyAnalysisPanelResult,
    FiscalTimeSeriesBuilder,
    FiscalTimeSeriesInput,
)
from sec_xbrl.history import _iter_history_records, _write_records


def _panel(
    year: int, quarter: int, start: str, end: str
) -> CompanyAnalysisPanelResult:
    line_id = "line:revenue"
    definition = {
        "analysis_line_id": line_id,
        "label": "Revenue",
        "line_class": "COMMON_GAAP",
        "line_scope": "STATEMENT",
        "line_kind": "REPORTED",
    }
    binding = {
        "analysis_binding_id": f"binding:{year}:{quarter}",
        "analysis_line_id": line_id,
    }
    value = {
        "analysis_line_value_id": f"value:{year}:{quarter}",
        "analysis_line_id": line_id,
        "value_status": "REPORTED",
        "value_numeric": str(year),
        "value_text": None,
        "selection_view": "LATEST_REPORTED",
        "selection_as_of_date": "2026-10-17",
        "source_filing_id": f"filing:{year}:{quarter}",
        "selected_source_fact_id": f"fact:{year}:{quarter}",
        "raw_concept_qname": "us-gaap:Revenues",
        "company_canonical_concept_id": "company:revenue",
        "canonical_dimension_signature": (),
        "unit_numerator_measures": ("iso4217:USD",),
        "unit_denominator_measures": (),
        "mapping_review_required": False,
        "context_start_date": start,
        "context_end_date": end,
        "context_instant_date": None,
        "comparative_type": "CURRENT_FOCUS",
        "accession": f"0000000000-{year}-{quarter:06d}",
        "filed_date": f"{year}-04-30",
        "source_snapshot_id": f"snapshot:{year}:{quarter}",
        "context_id": f"context:{year}:{quarter}",
        "source_type": "REPORTED",
        "reported_or_derived": "REPORTED",
    }
    return CompanyAnalysisPanelResult(
        (definition,),
        (binding,),
        (value,),
        {
            "cik": "0000000001",
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "period_class": "QTD_3M",
            "selection_view": "LATEST_REPORTED",
            "selection_as_of_date": "2026-10-17",
        },
    )


def test_public_fiscal_builder_spill_matches_eager_history_records_and_hashes(
    tmp_path: Path,
) -> None:
    first = _panel(2024, 1, "2023-01-01", "2023-03-31")
    second = _panel(2025, 1, "2024-01-01", "2024-03-31")
    values = deepcopy(second.values)
    values[0]["ordered_json_provenance"] = {
        "roles": [
            {"network": "PRE", "edges": ("edge:2", "edge:1")},
            {"network": "DEF", "dimensions": (("axis", "member"),)},
        ],
        "unit": {"numerator": ("iso4217:USD",), "denominator": ()},
    }
    second = replace(second, values=values)
    inputs = (
        FiscalTimeSeriesInput(first, "--12-31"),
        FiscalTimeSeriesInput(second, "--12-31"),
    )
    eager = FiscalTimeSeriesBuilder().build(inputs=inputs)
    spilled = FiscalTimeSeriesBuilder().build_spilled(
        inputs=iter(inputs), spill_root=tmp_path / "spill"
    )
    try:
        for name in ("columns", "rows", "cells"):
            eager_path = tmp_path / "eager" / f"{name}.parquet"
            spilled_path = tmp_path / "spilled" / f"{name}.parquet"
            expected = _write_records(eager_path, getattr(eager, name))
            actual = _write_records(spilled_path, spilled.dataset(name))
            assert actual == expected
            assert tuple(_iter_history_records(spilled_path, actual)) == tuple(
                _iter_history_records(eager_path, expected)
            )
    finally:
        spilled.close(success=True)
