from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics.liability_statement_evidence import RULE_VERSION
from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader
from sec_xbrl.screening.liability_addition import DEFINITION_VERSION, METRIC_ID, liability_rows
from sec_xbrl.screening.service import ScreeningService


def _projection_fixture(tmp_path):
    cutoff = "2026-10-25"
    parent = ScreeningDatasetV3Reader.__new__(ScreeningDatasetV3Reader)
    parent.manifest = {"dataset_id": "added", "financial_as_of": cutoff, "fixture_kind": "SYNTHETIC",
                       "sources": {"metadata": {"publication_id": "metadata"}}}
    parent.publication_id = "base-publication"
    parent.companies = [{"cik": str(index).zfill(10), "ticker": f"T{index}", "name": f"Company {index}"}
                        for index in range(1, 8)]
    parent.quarter_definitions = []
    parent.quarter_support = []
    parent.quarter_observations = []
    parent.quarter_period_inventory = []
    candidates = []
    for index, company in enumerate(parent.companies, 1):
        cik = company["cik"]
        for quarter, end, report, filed in (
            (2, "2026-07-01", "2026-06-30", "2026-07-30"),
            (3, "2026-10-01", "2026-09-30", "2026-10-20"),
        ):
            accession = f"{cik}-26-{quarter:06}"
            period = {"accession": accession, "filed_date": filed, "report_date": report,
                      "fiscal_year": 2027, "fiscal_quarter": f"Q{quarter}", "period_end": end}
            parent.quarter_period_inventory.append(
                {**company, **period, "inventory_id": f"period-{cik}-{quarter}", "calendar_year": 2026,
                 "calendar_quarter": quarter, "bucket_status": "PERIOD_AVAILABLE", "end_convention": "EXCLUSIVE",
                 "candidate_periods": [{**period, "period_start": None}]}
            )
        parent.quarter_observations.append({
            "cik": cik, "metric_id": "quarter_liabilities", "calendar_year": 2026,
            "calendar_quarter": 2, "observation_id": f"old-{cik}", "availability_status": "UNAVAILABLE",
            "reason": "REQUIRED_ITEM_NOT_IN_PREPARED_DATA", "value": None,
        })
        parent.quarter_observations.append({
            "cik": cik, "metric_id": "quarter_assets", "calendar_year": 2026, "calendar_quarter": 2,
            "observation_id": f"assets-{cik}", "availability_status": "AVAILABLE", "source_kind": "REPORTED",
            "period_class": "INSTANT", "period_start": None, "end_convention": "EXCLUSIVE",
            "unit": "USD", "dimensions": [], "value": "100", "period_end": "2026-07-01", "fiscal_year": 2027,
            "fiscal_quarter": "Q2", "accession": f"{cik}-26-000002", "filed_date": "2026-07-30",
            "report_date": "2026-06-30",
        })
        if index == 7:
            continue
        digest = "a" * 64
        source = {"source_fact_id": f"fact-{cik}", "raw_concept_id": "concept",
                  "raw_concept_qname": "us-gaap:Assets", "context_id": "instant",
                  "row_locator": "/table/tr", "cell_locator": "/table/tr/td", "value": "100"}
        proof = {"accession": f"{cik}-26-000002", "filed_date": "2026-07-30", "package_sha256": digest,
                 "liability_component_sum": str(index), "formula": "Assets - TotalEquity", "assets": source,
                 "balance_total": source, "equity": {"source": source}, "liability_components": [{"source": source}]}
        candidates.append({
            **company, "status": "DERIVED_CANDIDATE", "reason": None, "rule_version": RULE_VERSION,
            "unit": "USD", "value": str(index), "instant": "2026-07-01", "instant_exclusive": "2026-07-01",
            "display_date": "2026-06-30", "accession": proof["accession"], "provenance": proof,
            **dict.fromkeys(("raw_manifest_sha256", "intake_sha256", "package_sha256"), digest),
        })
    audit = {"financial_as_of": cutoff, "calendar_bucket": "2026Q2", "company_count": 7,
             "missing_liability_audits": candidates, "amazon_annual_check": candidates[0]}
    return parent, audit, tmp_path / "audit.json"


def _pin_audit(path, audit):
    write_json(path, audit)
    return {"path": str(path), "sha256": sha256_file(path)}


def test_added_metric_exactly_six_at_fixed_period_and_absent_at_newer_latest(tmp_path):
    parent, audit, path = _projection_fixture(tmp_path)
    original_rows = deepcopy(parent.quarter_observations)
    definition, support, rows = liability_rows(parent, _pin_audit(path, audit))
    overlay = ScreeningDatasetV3Reader.__new__(ScreeningDatasetV3Reader)
    overlay.manifest = parent.manifest
    overlay.publication_id = "overlay-publication"
    overlay.companies = parent.companies
    overlay.annual = SimpleNamespace(company=lambda cik: next(row for row in overlay.companies if row["cik"] == cik))
    overlay.quarter_period_inventory = parent.quarter_period_inventory
    overlay.quarter_definitions = [definition]
    overlay.quarter_support = support
    overlay.quarter_observations = [*parent.quarter_observations, *rows]
    service = ScreeningService.__new__(ScreeningService)
    service.datasets = {"added": overlay}
    fixed = service.quarter_explorer("added", calendar_year=2026, calendar_quarter=2)
    assert [row["metrics"][METRIC_ID]["value"] for row in fixed["rows"]] == ["1", "2", "3", "4", "5", "6", None]
    latest = service.quarter_explorer("added", latest=True)
    assert all(row["metrics"][METRIC_ID]["value"] is None for row in latest["rows"])
    observation = fixed["rows"][0]["metrics"][METRIC_ID]
    assert observation["source_kind"] == "DERIVED_METRIC"
    assert observation["fiscal_year"] == 2027
    assert observation["source_lineage"]["source_evidence"] == audit["missing_liability_audits"][0]
    content = {"universe": {"mode": "ALL_PREPARED"}, "columns": ["company"],
               "sort": {"column": "ticker", "direction": "ASC"},
               "predicates": [{"metric_id": METRIC_ID, "definition_version": DEFINITION_VERSION,
                               "operator": "GTE", "threshold": "4"}],
               "period_policy": {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2026, "calendar_quarter": 2}}
    assert service._evaluate(content, "added")["counts"] == {
        "pass": 3, "fail": 3, "undetermined": 1, "target": 7, "quality_block": 0,
    }
    content["period_policy"] = {
        "mode": "LATEST_COMPANY_QUARTER_V1",
        "availability": service.batch_availability(mode="PREPARED_SIMULATION", dataset_id="added"),
    }
    assert service._evaluate(content, "added")["counts"]["undetermined"] == 7
    ciks = [company["cik"] for company in parent.companies[:2]]
    compared = service.quarter_comparison(
        "added", ciks=ciks, metric_id=METRIC_ID, calendar_year=2026, calendar_quarter=2,
    )
    assert [row["observation"]["value"] for row in compared["rows"]] == ["1", "2"]
    series = service.quarter_series("added", cik=ciks[0], metric_id=METRIC_ID)
    assert [row["value"] for row in series["observations"]] == ["1", None]
    assert parent.quarter_observations == original_rows
    assert len(rows) == 14


@pytest.mark.parametrize("defect", ("changed_artifact", "shifted_instant", "duplicate", "existing_value", "quality_block", "asset_mismatch"))
def test_rejects_scope_and_approval_mismatch(tmp_path, defect):
    parent, audit, path = _projection_fixture(tmp_path)
    if defect == "shifted_instant":
        audit["missing_liability_audits"][0]["instant"] = "2026-10-01"
    elif defect == "duplicate":
        audit["missing_liability_audits"][-1] = audit["missing_liability_audits"][0]
    elif defect == "existing_value":
        parent.quarter_observations[0].update(value="1", availability_status="AVAILABLE")
    elif defect == "quality_block":
        parent.quarter_observations[0]["quality_blocking"] = True
    elif defect == "asset_mismatch":
        parent.quarter_observations[1]["value"] = "101"
    pin = _pin_audit(path, audit)
    if defect == "changed_artifact":
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="liability"):
        liability_rows(parent, pin)
