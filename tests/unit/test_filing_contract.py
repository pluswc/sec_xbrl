from datetime import date

from sec_xbrl.filing.contracts import FilingRef


def test_filing_ref_preserves_accession():
    ref = FilingRef(
        cik="0000320193",
        accession="0000320193-25-000079",
        form="10-K",
        filed_date=date(2025, 10, 31),
    )
    assert ref.accession == "0000320193-25-000079"
    assert ref.cik == "0000320193"
