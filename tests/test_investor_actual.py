"""Opt-in actual prepared publication verification; never fetches the network."""
import os

import pytest

from sec_xbrl.analysis import open_analysis

pytestmark = pytest.mark.skipif(not os.environ.get("SEC_XBRL_ANALYSIS_BUNDLE"), reason="explicit prepared analysis bundle required")


@pytest.mark.parametrize("ticker,years", [("AMD", (2023, 2025)), ("NVDA", (2024, 2026)), ("MSFT", (2024, 2026)), ("AMZN", (2023, 2025)), ("AAPL", (2023, 2025))])
def test_five_companies_public_query(ticker, years):
    client = open_analysis(os.environ["SEC_XBRL_ANALYSIS_BUNDLE"])
    result = client.overview(ticker, fiscal_start=years[0], fiscal_end=years[1])
    assert len(result["rows"]) <= 25
    assert len(result["context"]["periods"]) == 12
    assert len([c for c in result["cells"] if c["row_id"] == "revenue" and c["value"] is not None]) == 12
    for cell in result["cells"]:
        assert client.trace(cell["cell_id"], context=result["context"])["trace"]["cell_id"] == cell["cell_id"]
    with pytest.raises(ValueError):
        client.overview(ticker, as_of="2000-01-01")


def test_actual_amd_new_cf_and_reviewed_hierarchy():
    client = open_analysis(os.environ["SEC_XBRL_ANALYSIS_BUNDLE"])
    result = client.overview("AMD", fiscal_start=2023, fiscal_end=2025)
    for row, expected in [("repurchases", ["233000000", "256000000", "0"]), ("stock_compensation", ["374000000", "339000000", "486000000"])]:
        values = sorted([c for c in result["cells"] if c["row_id"] == row], key=lambda c: (c["fiscal_year"], c["fiscal_quarter"]))
        assert all(c["value"] is not None for c in values)
        assert [c["value"] for c in values if c["fiscal_quarter"] == 4] == expected
    edges = client._records("AMD", "LATEST_REPORTED", "edges")
    hierarchy = [e for e in edges if e["kind"] == "REVIEWED_DISPLAY_HIERARCHY"]
    assert hierarchy and all(p[0] == 2025 for e in hierarchy for p in e["periods"])
    groups = client.list_breakdowns("revenue", context=result["context"])["groups"]
    group = next(g for g in groups if g.get("basis_version") == "AMD-2023-2024-four-segments")
    branch = client.children(group["node_id"], context=result["context"], limit=100)
    assert len(branch["cells"]) == 32
    assert sorted({(c["fiscal_year"], c["fiscal_quarter"]) for c in branch["columns"]}) == [(y, q) for y in (2023, 2024) for q in (1, 2, 3, 4)]
