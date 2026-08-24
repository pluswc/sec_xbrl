from sec_xbrl.pilots.amd_msft_meta_p2 import (
    CompanyDossier,
    DossierEvidence,
    _inline_period_class,
    _is_total_revenue_qname,
    _scaled_value,
    render_dossiers,
)


def test_inline_revenue_selection_is_deliberately_narrow() -> None:
    assert _is_total_revenue_qname("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert not _is_total_revenue_qname("amd:RevenueRemainingPerformanceObligation12months")


def test_inline_value_preserves_declared_scale_and_context_period_class() -> None:
    assert _scaled_value("34639", "6") == "34639 × 10^6"
    assert _inline_period_class("2024-12-29 to 2025-12-27") == "FY"
    assert _inline_period_class("2025-12-28 to 2026-03-28") == "QTD_3M"


def test_rendered_dossier_keeps_fact_disclosure_relationship_and_period_evidence() -> None:
    evidence = DossierEvidence(
        label="Revenue", value="10 × 10^6", period_class="QTD_3M", period="2026-01-01 to 2026-03-31",
        dimensions=("us-gaap:StatementBusinessSegmentsAxis=example:SegmentMember",),
        accession="0000000000-26-000001", document="example.htm", locator="inline-id:f-1",
        qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", unit="iso4217:USD",
    )
    report = render_dossiers((CompanyDossier(
        company="Example Corp.", ticker="EX", annual_accession="0000000000-25-000001",
        update_accession="0000000000-26-000001", annual_revenue=(), update_revenue=(evidence,),
        annual_breakdowns=(), update_breakdowns=(evidence,),
        disclosure_states=(("REVENUE_RECOGNITION", "NOT_REPORTED_THIS_QUARTER"),),
        statement_qa=("Statement - Income (STATEMENT)",),
        relationship_qa=("Accession `0000000000-26-000001`: 1 statement roles; PRE=2, CAL=0, DEF=3 as-filed relationships.",),
        warnings=("No derived Q4.",),
    ),))

    for required in (
        "QTD_3M", "0000000000-26-000001", "example.htm", "inline-id:f-1", "QName",
        "iso4217:USD", "SegmentMember", "NOT_REPORTED_THIS_QUARTER", "PRE=2, CAL=0, DEF=3",
        "Current-series raw view",
    ):
        assert required in report
