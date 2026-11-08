from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.reviewed_addition import reviewed_rows

AS_OF = "2026-10-25"
SHA = "b" * 64
START, END = "2026-04-01", "2026-07-01"
TSLA, PCAR = "0001318605", "0000075362"


def _fixture():
    companies, inventory, audit_rows, rows, definitions, support = [], [], [], [], [], []
    for cik, ticker, metric, amount, unit, kind, reason in (
        (TSLA, "TSLA", "quarter_gross_margin", "16.826", "PERCENT", "DERIVED_METRIC", "MULTIPLE_CANDIDATES"),
        (PCAR, "PCAR", "quarter_research", "114300000", "USD", "REPORTED", "PRIMARY_STATEMENT_EVIDENCE_MISSING"),
    ):
        company = {"cik": cik, "ticker": ticker}
        companies.append(company)
        filing = {"accession": f"{cik}-26-000001", "filed_date": "2026-07-23", "report_date": "2026-06-30",
                  "source_snapshot_id": f"l1:{cik}:{cik}26000001:{SHA[:16]}",
                  **dict.fromkeys(("snapshot_manifest_sha256", "source_intake_sha256", "package_sha256"), SHA)}
        period = {"period_start": START, "period_end": END, "end_convention": "EXCLUSIVE"}
        fiscal = {"fiscal_year": 2027, "fiscal_quarter": "Q2"}
        coordinates = {"calendar_year": 2026, "calendar_quarter": 2}
        inventory.append({**company, **period, **filing, **fiscal, **coordinates, "bucket_status": "PERIOD_AVAILABLE"})
        definition = {"metric_id": metric, "definition_version": "same-v1", "rule_version": "same-rule",
                      "unit": unit, "allowed_source_kinds": [kind], "observation_basis": "QTD_3M"}
        definitions.append(definition)
        row = {**company, **coordinates, **period, **fiscal, **filing, "metric_id": metric, "unit": unit,
               "availability_status": "UNAVAILABLE", "value": None, "reason": reason,
               "definition_version": "same-v1", "source_kind": "UNAVAILABLE", "period_class": "QTD_3M",
               "observation_id": "old-" + metric, "selection_as_of_date": AS_OF, "selection_view": "LATEST_REPORTED"}
        item = {**company, **period, "metric_id": metric, "value": amount, "unit": unit,
                "value_kind": "CALCULATED_FROM_REPORTED_INPUTS" if kind == "DERIVED_METRIC" else kind,
                "previous_reason": reason, "filing": filing}
        proof = {"source_fact_id": "gross-or-research", "context_id": "ctx", "unit_id": "usd",
                 "qname": "us-gaap:GrossProfit" if cik == TSLA else "us-gaap:ResearchAndDevelopmentExpense",
                 "namespace": "http://fasb.org/us-gaap/2026", "section": "IS" if cik == TSLA else "DISCLOSURE",
                 "value": "4751000000" if cik == TSLA else amount, "role_id": "statement",
                 "table_id": "table", "table_sha256": SHA, "source_document_sha256": SHA,
                 "row_locator": "/table/tr", "cell_locator": "/table/tr/td", "inline_id": "ix"}
        source = {**company, **period, **filing, **fiscal,
                  **{field: proof[field] for field in ("source_fact_id", "context_id", "unit_id", "value")},
                  "raw_concept_qname": proof["qname"], "raw_concept_namespace_uri": proof["namespace"],
                  "availability_status": "AVAILABLE", "source_kind": "REPORTED", "unit": "USD",
                  "period_class": "QTD_3M", "dimensions": [], "source_filing_id": "filing",
                  "source_id": "source", "selected_source_ids": ["source"], "duration_days": 91,
                  "primary_statement_evidence": []}
        if cik == TSLA:
            gross = {**row, **source, "metric_id": "quarter_gross_profit", "observation_id": "gross-anchor",
                     "source_lineage": {"primary_statement_evidence": [
                         {"role_id": "statement", "statement_types": ["IS"]},
                     ]}}
            rows.extend([gross, {**row, "metric_id": "quarter_revenue", "observation_id": "held-revenue"}])
            denominator = {**proof, "source_fact_id": "revenue", "value": "28236000000",
                           "qname": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"}
            item.update(inputs={"gross_profit": proof, "revenue": denominator},
                        formula="gross profit * 100 / revenue", same_value_revenue_fact_ids=["revenue"])
        else:
            row["source_lineage"] = source
            item["input"] = proof
        rows.extend([row, {**row, "calendar_quarter": 3, "observation_id": "later-" + metric}])
        audit_rows.append(item)
        support.append({**company, "metric_id": metric, "available_bucket_count": 0})
    parent = SimpleNamespace(
        manifest={"financial_as_of": AS_OF, "parents": {"quarterly": {"manifest_sha256": SHA}}},
        companies=companies, quarter_period_inventory=inventory, quarter_observations=rows,
        quarter_definitions=definitions, quarter_support=support,
    )
    audit = {"status": "OFFLINE_CANDIDATES_ONLY", "financial_as_of": AS_OF, "calendar_bucket": "2026Q2",
             "quarterly_parent_sha256": SHA, "approved_for_this_offline_review": audit_rows}
    return parent, audit


def _pin(tmp_path, audit):
    path = tmp_path / "review.json"
    write_json(path, audit)
    return {"path": str(path), "sha256": sha256_file(path)}


def test_two_cells_keep_existing_metrics_periods_and_original_data(tmp_path):
    parent, audit = _fixture()
    old = deepcopy(parent)
    support, rows = reviewed_rows(parent, _pin(tmp_path, audit))
    changed = [new for new, previous in zip(rows, parent.quarter_observations, strict=True) if new is not previous]
    assert [(row["metric_id"], row["value"], row["source_kind"]) for row in changed] == [
        ("quarter_gross_margin", "16.826", "DERIVED_METRIC"), ("quarter_research", "114300000", "REPORTED"),
    ]
    assert all(row["fiscal_year"] == 2027 and row["period_end"] == END for row in changed)
    assert all(row["definition_version"] == "same-v1" for row in changed)
    assert changed[1]["source_lineage"]["primary_statement_evidence"] == []
    assert [row["available_bucket_count"] for row in support] == [1, 1]
    assert parent == old


@pytest.mark.parametrize("defect", ("unknown_cell", "wrong_quarter", "gross_fact", "held_fact", "quality_block", "already_available"))
def test_reviewed_scope_rejects_other_cells_or_anchor_conflicts(tmp_path, defect):
    parent, audit = _fixture()
    if defect == "unknown_cell":
        audit["approved_for_this_offline_review"][0]["cik"] = "0000000001"
    elif defect == "wrong_quarter":
        audit["calendar_bucket"] = "2026Q3"
    elif defect == "gross_fact":
        audit["approved_for_this_offline_review"][0]["inputs"]["gross_profit"]["source_fact_id"] = "unknown"
    elif defect == "held_fact":
        audit["approved_for_this_offline_review"][1]["input"]["source_fact_id"] = "unknown"
    elif defect == "quality_block":
        parent.quarter_observations[2]["quality_blocking"] = True
    elif defect == "already_available":
        parent.quarter_observations[2].update(availability_status="AVAILABLE", value="1")
    with pytest.raises(ValueError, match="reviewed"):
        reviewed_rows(parent, _pin(tmp_path, audit))
