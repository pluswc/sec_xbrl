from copy import deepcopy

import pytest

from sec_xbrl.metrics.governed_corrections import REVENUE_VERSION, _bridge_from_prepared
from sec_xbrl.metrics.statement_metric_evidence import LEGACY_REVENUE, NEW_REVENUE
from tests.screening.test_statement_metric_evidence import _case


def bridge_case():
    filing, prepared = _case()
    filing.update(form="10-K", filed_date="2026-02-05", report_date="2025-12-31")
    prepared["filings"] = [filing]
    table = prepared["source_tables"][0]
    table.update(section="IS", filing_id=filing["filing_id"])
    prepared["source_statement_rows"][0]["label"] = "Revenues"
    fact = prepared["statement_facts"][0]
    fact["concept"]["qname"] = NEW_REVENUE
    fact.update(fact_id="current", value_numeric="402836000000")
    fact["scope"]["period"].update({"class": "FY", "start": "2025-01-01", "end": "2026-01-01"})
    prior_fact = deepcopy(fact)
    prior_fact.update(fact_id="comparative", context_id="prior-context", value_numeric="350018000000")
    prior_fact["scope"]["period"].update(start="2024-01-01", end="2025-01-01")
    prepared["statement_facts"].append(prior_fact)
    current = {"cik": filing["cik"], "metric_id": "revenue", "metric_definition_version": "annual-core-reported-v1",
        "metric_observation_id": "current-observation", "source_filings": [filing["accession"]],
        "availability_status": "AVAILABLE", "mapping_review_required": False, "source_kind": "REPORTED", "status": "REPORTED",
        "period_class": "FY", "raw_concept_qname": NEW_REVENUE, "raw_concept_is_standard": True,
        "dimensions": [], "unit": "USD", "unit_semantics": [["iso4217:USD"], []], "raw_concept_taxonomy_family": "us-gaap",
        "raw_concept_period_type": "duration", "raw_concept_data_type": "xbrli:monetaryItemType", "view": "LATEST_REPORTED",
        "financial_as_of": "2026-10-25", "fiscal_year": 2025, "period_start": "2025-01-01", "period_end": "2026-01-01",
        "value": "402836000000", "source_fact_ids": ["current"],
        "trace": {"value_lineage": {"filed_date": "2026-02-05"}}}
    current["trace"]["value_lineage"].update(
        selected_source_fact_id=fact["fact_id"], raw_concept_id=fact["raw_concept_id"],
        raw_concept_namespace_uri=fact["concept"]["namespace_uri"], raw_concept_qname=fact["concept"]["qname"],
        context_id=fact["context_id"], source_snapshot_id="raw-snapshot", accession=filing["accession"],
        source_filing_id=filing["filing_id"])
    prior = {**deepcopy(current), "metric_observation_id": "original-prior", "raw_concept_qname": LEGACY_REVENUE,
        "fiscal_year": 2024, "period_start": "2024-01-01", "period_end": "2025-01-01", "value": "350018000000",
        "source_filings": ["original-prior-filing"], "source_fact_ids": ["original-prior-fact"],
        "trace": {"value_lineage": {"filed_date": "2025-02-04"}}}
    original = {"cik": current["cik"], "metric_id": "revenue_yoy", "fiscal_year": 2025,
        "metric_definition_version": "old-yoy", "metric_observation_id": "old-growth", "availability_status": "UNAVAILABLE",
        "diagnostic_reasons": ["SEMANTIC_IDENTITY_MISMATCH"], "source_fact_ids": ["current", "original-prior-fact"],
        "input_observation_ids": [current["metric_observation_id"], prior["metric_observation_id"]], "value": None}
    return {"current": current, "prior": prior, "original": original, "prepared": prepared, "financial_as_of": "2026-10-25", "source_snapshot_id": "raw-snapshot"}


def test_same_filing_primary_bridge_keeps_original_identities_and_exact_arithmetic():
    case = bridge_case()
    before = deepcopy(case)
    result = _bridge_from_prepared(**case)
    assert result["metric_definition_version"] == REVENUE_VERSION
    assert result["value"] == "15.09008108154437771771737453502390"
    assert result["continuity_proof"]["original_prior"] == case["prior"]
    assert result["original_observation"]["id"] == "old-growth"
    assert result["known_on"] == result["proof_available_on"] == "2026-02-05"
    assert case == before
    duplicate = deepcopy(case["prepared"]["statement_facts"][1])
    duplicate["fact_id"] = "equivalent"
    case["prepared"]["statement_facts"].append(duplicate)
    assert _bridge_from_prepared(**case)["value"] == result["value"]


@pytest.mark.parametrize("defect", ["amount", "scope", "quality", "derived", "cutoff", "conflict", "binding", "prior_identity"])
def test_bridge_rejects_unproven_transition(defect):
    case = bridge_case()
    if defect == "amount":
        case["prior"]["value"] = "350019000000"
    elif defect == "scope":
        case["prepared"]["statement_facts"][1]["scope"]["dimensions"] = [["axis", "member"]]
    elif defect == "quality":
        case["prior"]["quality_status"] = "BLOCK"
    elif defect == "derived":
        case["current"]["source_kind"] = "DERIVED_METRIC"
    elif defect == "cutoff":
        case["prepared"]["filings"][0]["filed_date"] = "2026-10-26"
    elif defect == "conflict":
        bad = deepcopy(case["prepared"]["statement_facts"][1]); bad.update(fact_id="conflict", value_numeric="1")
        case["prepared"]["statement_facts"].append(bad)
    elif defect == "binding":
        case["prepared"]["statement_facts"][1]["source_locations"][0]["binding_status"] = "INFERRED"
    else:
        case["original"]["input_observation_ids"][1] = "another-prior"
    with pytest.raises(ValueError):
        _bridge_from_prepared(**case)


def test_latest_actual_quarter_calls_existing_public_builder_and_keeps_ttm(tmp_path, monkeypatch):
    import json
    from datetime import date, timedelta
    from types import SimpleNamespace

    from sec_xbrl import analysis
    from sec_xbrl.metrics.governed_corrections import prepare_latest_quarter
    from sec_xbrl.metrics.quarterly_screening import ARITHMETIC_CATALOG_VERSION
    from sec_xbrl.screening.common import sha256_file, write_json
    from tests.screening.test_quarterly50_expansion import _inputs
    from tests.screening.test_quarterly_screening_producer import AS_OF, CIK, _profile_rows

    def shift(value, key=""):
        if isinstance(value, dict):
            return {k: shift(v, k) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [shift(v, key) for v in value]
        if isinstance(value, str) and len(value) == 10 and value[4:5] == "-" and value[7:8] == "-" and key not in {"as_of", "selection_as_of_date"}:
            return (date.fromisoformat(value) + timedelta(days=2)).isoformat()
        return value

    columns, cells, traces = shift(_inputs())
    for column in columns:
        cell = next(c for c in cells if c["column_id"] == column["fiscal_time_series_column_id"])
        column.update(period_class=cell["period_class"], fiscal_year=cell["fiscal_year"], fiscal_quarter=cell["fiscal_quarter"],
                      column_status="AVAILABLE", actual_start_date=cell["start"])
    data = {"columns": columns, "core_rows": _profile_rows(), "core_cells": cells}
    data.update({f"trace_{digit}": traces if digit == "0" else [] for digit in "0123456789abcdef"})
    files = {}
    for name, rows in data.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(rows))
        files[name] = {"path": path.name, "sha256": sha256_file(path)}
    manifest = tmp_path / "analysis_manifest.json"
    write_json(manifest, {"period_mode": "QUARTERLY", "companies": {"TEST": {"as_of": AS_OF,
        "views": {"LATEST_REPORTED": {"files": files}}}}})
    qpath = tmp_path / "quarterly_screening_metric_manifest.json"
    write_json(qpath, {"financial_as_of": AS_OF, "config": {"catalog_version": ARITHMETIC_CATALOG_VERSION,
        "companies": [{"cik": CIK, "ticker": "TEST", "analysis_root": str(tmp_path), "analysis_manifest_sha256": sha256_file(manifest)}]}})
    monkeypatch.setattr(analysis, "open_analysis", lambda _: SimpleNamespace(_records=lambda _ticker, _view, name: data[name]))
    rows, inventory, touched = prepare_latest_quarter(
        analysis_manifest={"path": str(manifest), "sha256": sha256_file(manifest)}, ticker="TEST", cik=CIK,
        financial_as_of=AS_OF, latest={"fiscal_year": 2026, "fiscal_quarter": 3, "period_start": "2026-07-03",
            "period_end": "2026-10-03", "end_convention": "EXCLUSIVE"},
        quarterly_manifest={"path": str(qpath), "sha256": sha256_file(qpath)})
    assert len(rows) == 41 and len(inventory) == 1 and len(touched) == 19
    assert inventory[0]["calendar_quarter"] == 4
    assert next(r for r in rows if r["metric_id"] == "quarter_revenue")["value"] == "300"
    assert next(r for r in rows if r["metric_id"] == "ttm_revenue")["value"] == "1000"


@pytest.mark.parametrize("module,name", [("sec_xbrl.metrics.governed_corrections", "prepare_revenue_bridge"),
                                         ("sec_xbrl.screening.governed_delta", "publish_governed_delta")])
def test_public_imports_work_in_fresh_process(module, name):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).parents[2]
    env = {**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + str(root)}
    subprocess.run([sys.executable, "-c", f"from {module} import {name}"], env=env, cwd=root, check=True)


@pytest.mark.parametrize("field", ["selected_source_fact_id", "raw_concept_id", "raw_concept_namespace_uri",
                                   "raw_concept_qname", "context_id", "source_snapshot_id", "accession", "source_filing_id"])
@pytest.mark.parametrize("defect", ["missing", "foreign"])
def test_bridge_rejects_unbound_selected_raw_lineage(field, defect):
    case = bridge_case()
    lineage = case["current"]["trace"]["value_lineage"]
    if defect == "missing":
        del lineage[field]
    else:
        lineage[field] = "foreign"
    with pytest.raises(ValueError, match="Raw"):
        _bridge_from_prepared(**case)


@pytest.mark.parametrize("identities", [[], ["current", "current"], [None], [""], "current"])
def test_bridge_requires_nonempty_unique_string_fact_ids(identities):
    case = bridge_case()
    case["current"]["source_fact_ids"] = identities
    with pytest.raises(ValueError, match="current fact"):
        _bridge_from_prepared(**case)


def test_bridge_rejects_raw_snapshot_different_from_pinned_input():
    case = bridge_case()
    case["source_snapshot_id"] = "another-pinned-snapshot"
    with pytest.raises(ValueError, match="pinned occurrence"):
        _bridge_from_prepared(**case)
