from __future__ import annotations

from pathlib import Path

import pytest

from sec_xbrl.screening.common import digest_value, sha256_file, write_json
from sec_xbrl.screening.dataset import (
    COMPANIES,
    MANIFEST,
    METADATA,
    OBSERVATIONS,
    SUPPORT,
    VERSION,
    _observation,
)


@pytest.fixture
def screening_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    root.mkdir()
    companies = [
        _company("0000000001", "ONE", "3674"),
        _company("0000000002", "TWO", "3674"),
        _company("0000000003", "THREE", "9999"),
    ]
    metadata = [
        {"cik": row["cik"], "name": row["name"], "tickers": [row["ticker"]],
         "exchanges": ["Nasdaq"], "sic_code": row["sic_code"], "sic_description": "Test",
         "sic_status": "CLASSIFIED", "metadata_status": "ROOT_OBSERVED",
         "observed_at": "2026-10-08T00:00:00+00:00", "financial_prepared": True}
        for row in companies
    ]
    metadata.append({
        "cik": "0000000004", "name": "UNKNOWN", "tickers": ["UNK"], "exchanges": [],
        "sic_code": None, "sic_description": None, "sic_status": "UNKNOWN_SIC",
        "metadata_status": "CANDIDATE_ONLY", "observed_at": "2026-10-08T00:00:00+00:00",
        "financial_prepared": False,
    })
    source_cells = {
        "0000000001": [_source_cell("0000000001", "revenue", "100", quality=None),
                       _source_cell("0000000001", "cfo", "10", quality=None)],
        "0000000002": [_source_cell("0000000002", "revenue", "40", quality="WARN"),
                       _source_cell("0000000002", "cfo", "5", quality=None)],
        "0000000003": [_source_cell("0000000003", "revenue", None, quality=None,
                                     reason="MULTIPLE_CANDIDATES"),
                       _source_cell("0000000003", "cfo", "3", quality=None)],
    }
    observations = []
    support = []
    for company in companies:
        for metric in ("revenue", "cfo"):
            support.append({"cik": company["cik"], "ticker": company["ticker"],
                            "metric_id": metric, "label": metric,
                            "definition_version": "annual-core-reported-v1",
                            "execution_supported": True, "support_status": "AVAILABLE",
                            "available_periods": 1, "observed_periods": 1, "reason": None})
        for metric in ("revenue_growth", "operating_margin"):
            support.append({"cik": company["cik"], "ticker": company["ticker"],
                            "metric_id": metric, "label": metric,
                            "definition_version": "existing-investor-metric-policy-v1",
                            "execution_supported": False, "support_status": "UNAVAILABLE",
                            "available_periods": 0, "observed_periods": 0,
                            "reason": "ACTUAL_PERIOD_REQUIRED"})
    files = {COMPANIES: companies, METADATA: metadata, SUPPORT: support, OBSERVATIONS: observations}
    for company in companies:
        snapshot = {"snapshot_version": "u5-consumer-export-v1", "context": {"ticker": company["ticker"]},
                    "publication": {"analysis_publication_id": company["analysis_publication_id"]},
                    "source_identity": {}, "display_policy": {},
                    "selection": {"row_ids": ["revenue", "cfo"]}, "columns": [],
                    "rows": [], "warnings": [], "cells": source_cells[company["cik"]]}
        snapshot["context"].update({"view": "LATEST_REPORTED", "as_of": "2026-10-08",
                                    "review_cutoff": None, "period_mode": "ANNUAL"})
        snapshot["snapshot_id"] = digest_value(snapshot)
        company["source_snapshot_id"] = snapshot["snapshot_id"]
        observations.extend(
            _observation(company["cik"], company["ticker"], cell["row_id"], cell, snapshot)
            for cell in source_cells[company["cik"]]
        )
        relative = f"source_snapshots/{company['cik']}/{snapshot['snapshot_id']}.json"
        path = root / relative
        path.parent.mkdir(parents=True)
        write_json(path, snapshot)
        files[relative] = snapshot
    write_json(root / COMPANIES, companies)
    write_json(root / METADATA, metadata)
    write_json(root / SUPPORT, support)
    write_json(root / OBSERVATIONS, observations)
    file_manifest = {
        name: {"sha256": sha256_file(root / name), "size": (root / name).stat().st_size}
        for name in files
    }
    identity = {
        "version": VERSION, "dataset_id": "fixture", "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
        "fixture_policy": "SELF_CONTAINED_TEST_ONLY",
        "financial_as_of": "2026-10-08", "view": "LATEST_REPORTED",
        "configured_ciks": [row["cik"] for row in companies],
        "counts": {"companies": 3, "metadata_candidates": 4, "metric_support": len(support),
                   "observations": len(observations), "source_snapshots": 3},
        "sources": {"metadata": {"publication_id": "company-metadata-fixture"}},
        "versions": {"analysis_versions": ["consumer-focused-analysis-v1"],
                     "source_publications": ["history-fixture"], "review_cutoffs": ["None"]},
        "files": file_manifest,
    }
    write_json(root / MANIFEST, {**identity, "publication_id": "screening-dataset-" + digest_value(identity)[:24]})
    return root


@pytest.fixture
def revision_content() -> dict:
    return {
        "universe": {"mode": "ALL_PREPARED"},
        "predicates": [
            {"metric_id": "revenue", "operator": "GTE", "threshold": "50",
             "definition_version": "annual-core-reported-v1"},
            {"metric_id": "cfo", "operator": "GT", "threshold": "0",
             "definition_version": "annual-core-reported-v1"},
        ],
        "period_policy": {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": 2025},
        "columns": ["ticker", "aggregate", "predicates"],
        "sort": {"column": "ticker", "direction": "ASC"},
    }


def _company(cik: str, ticker: str, sic: str) -> dict:
    return {"cik": cik, "ticker": ticker, "name": f"{ticker} Company", "sic_code": sic,
            "sic_description": "Test", "metadata_status": "ROOT_OBSERVED",
            "metadata_observed_at": "2026-10-08T00:00:00+00:00", "financial_prepared": True,
            "analysis_publication_id": f"analysis-{ticker}", "source_snapshot_id": "pending"}


def _source_cell(
    cik: str, metric: str, value: str | None, *, quality: str | None, reason: str | None = None
) -> dict:
    return {
        "row_id": metric, "fiscal_year": 2025, "fiscal_quarter": 0, "period_class": "FY",
        "start": "2024-01-01", "end": "2025-01-01", "display_value": value, "value": value,
        "unit": [["iso4217:USD"], []], "dimensions": [],
        "status": "REPORTED" if value is not None else "UNAVAILABLE", "reason": reason,
        "quality_status": quality, "quality_reasons": ["SOURCE_WARN"] if quality == "WARN" else [],
        "basis_version": None, "cell_id": f"{cik}-{metric}", "source_fact_id": f"fact-{cik}-{metric}",
        "provenance": {"cell_id": f"{cik}-{metric}", "value_lineage": {
            "source_filing_id": f"{cik}-25-000001", "mapping_review_required": False,
            "concept_mapping_version": "fixture-mapping-v1",
            "selection_rule_version": "fixture-selection-v1",
            "classification_rule_version": "fixture-period-v1",
        }},
    }
