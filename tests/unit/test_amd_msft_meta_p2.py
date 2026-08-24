from sec_xbrl.pilots.amd_msft_meta_p2 import (
    _inline_period_class,
    _is_total_revenue_qname,
    _scaled_value,
)


def test_inline_revenue_selection_is_deliberately_narrow() -> None:
    assert _is_total_revenue_qname("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert not _is_total_revenue_qname("amd:RevenueRemainingPerformanceObligation12months")


def test_inline_value_preserves_declared_scale_and_context_period_class() -> None:
    assert _scaled_value("34639", "6") == "34639 × 10^6"
    assert _inline_period_class("2024-12-29 to 2025-12-27") == "FY"
    assert _inline_period_class("2025-12-28 to 2026-03-28") == "QTD_3M"
