from __future__ import annotations

import os
from pathlib import Path

import pytest

from sec_xbrl.discovery import CompanyDisclosureDiscovery

_SNAPSHOT = os.environ.get("SEC_XBRL_AAPL_SNAPSHOT")


@pytest.mark.skipif(
    not _SNAPSHOT or not Path(_SNAPSHOT).is_dir(),
    reason="requires an explicitly cached current AAPL Layer 1 snapshot",
)
def test_aapl_income_statement_hierarchy_and_revenue_note_are_evidence_bound() -> None:
    result = CompanyDisclosureDiscovery().discover_snapshot(Path(_SNAPSHOT), statement_type="IS")

    assert result.filing["cik"] == "0000320193"
    assert result.statement_hierarchy
    assert all(row["parent_metadata_status"] == "PRESENT" for row in result.statement_hierarchy)
    assert all(row["child_metadata_status"] == "PRESENT" for row in result.statement_hierarchy)
    assert all(row["parent_qname"] and row["child_qname"] for row in result.statement_hierarchy)

    revenue_notes = [
        row for row in result.related_roles if "Disclosure - Revenue - Disaggregated Net Sales" in str(row["role_definition"])
    ]
    assert revenue_notes
    assert {row["anchor_qname"] for row in revenue_notes} == {
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    }
