"""Focused contract guards for C3-M5 scoped-policy public surfaces."""
from sec_xbrl.longitudinal.q4_policy_registry import (
    CASH_FLOW_ALLOWLIST,
    INCOME_ALLOWLIST,
    _allowed,
    _role_category,
)


def test_registry_never_admits_custom_or_unreviewed_qname() -> None:
    assert _allowed({"namespace_uri": "http://fasb.org/us-gaap/2024", "local_name": "GrossProfit"})
    assert not _allowed({"namespace_uri": "http://example.com/custom", "local_name": "GrossProfit"})
    assert not _allowed({"namespace_uri": "http://fasb.org/us-gaap/2024", "local_name": "ArbitraryRevenue"})
    assert "GrossProfit" in INCOME_ALLOWLIST
    assert "PaymentsToAcquirePropertyPlantAndEquipment" in CASH_FLOW_ALLOWLIST


def test_role_classifier_excludes_notes_and_accepts_primary_statement_roles() -> None:
    assert _role_category("Consolidated Statements of Operations") == "INCOME_OPERATIONS"
    assert _role_category("Consolidated Statements of Cash Flows") == "CASH_FLOWS"
    assert _role_category("Income Taxes Note") is None
