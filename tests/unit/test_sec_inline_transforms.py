from __future__ import annotations

from sec_xbrl.filing.sec_inline_transforms import (
    SEC_TRANSFORM_NAMESPACE,
    register_sec_inline_transforms,
)


def test_registers_sec_efm_transforms_used_by_inline_filings() -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()
    transforms = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]

    assert transforms["durday"]("2.1") == "P2D"
    assert transforms["durmonth"]("2.25") == "P2M8D"
    assert transforms["durwordsen"]("twelve months") == "P12M"
    assert transforms["numwordsen"]("nineteen hundred forty-four") == "1944"
    assert transforms["stateprovnameen"]("Delaware") == "DE"
    assert transforms["exchnameen"]("The Nasdaq Stock Market LLC") == "NASDAQ"
    assert transforms["entityfilercategoryen"]("Large accelerated filer") == "Large Accelerated Filer"
