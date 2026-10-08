from __future__ import annotations

from decimal import localcontext

import pytest

from sec_xbrl.facts.layer1 import Layer1Extractor
from sec_xbrl.filing.sec_inline_transforms import (
    SEC_TRANSFORM_NAMESPACE,
    register_sec_inline_transforms,
)


def test_registers_sec_efm_transforms_used_by_inline_filings() -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()
    transforms = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]

    assert transforms["durday"]("2.1") == "P2D"
    assert transforms["durweek"]("13") == "P91D"
    assert transforms["durmonth"]("2.25") == "P2M8D"
    assert transforms["durwordsen"]("twelve months") == "P12M"
    assert transforms["numwordsen"]("nineteen hundred forty-four") == "1944"
    assert transforms["stateprovnameen"]("Delaware") == "DE"
    assert transforms["exchnameen"]("The Nasdaq Stock Market LLC") == "NASDAQ"
    assert transforms["entityfilercategoryen"]("Large accelerated filer") == "Large Accelerated Filer"


def test_durweek_support_has_distinct_immutable_layer1_parser_version() -> None:
    assert Layer1Extractor.parser_version == "m2-layer1-v3"


@pytest.mark.parametrize(
    ("source", "expected"),
    (("☐", "false"), ("☑", "true"), ("☒", "true")),
)
def test_registers_sec_bool_ballot_box_transform(source: str, expected: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    assert FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["boolballotbox"](source) == expected


@pytest.mark.parametrize("source", ("", " ", "true", "X", "☒x"))
def test_sec_bool_ballot_box_rejects_unsupported_values(source: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    with pytest.raises(ValueError, match="unsupported SEC bool ballot box"):
        FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["boolballotbox"](source)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("13", "P91D"),
        ("26", "P182D"),
        ("39", "P273D"),
        ("52", "P364D"),
        ("53", "P371D"),
        ("2.25", "P15D"),
        ("-1.5", "-P10D"),
        (".5", "P3D"),
        ("+1.", "P7D"),
        ("0", "P0D"),
        ("-0", "P0D"),
        ("-0.1", "P0D"),
        (" \t\n+13.0\r ", "P91D"),
    ),
)
def test_sec_durweek_uses_days_only_and_truncates_fractional_days(
    source: str, expected: str
) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    assert FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durweek"](source) == expected


@pytest.mark.parametrize(
    "source",
    (
        "",
        " \t\n\r ",
        "words",
        "13 weeks",
        "1e3",
        "1,000",
        "NaN",
        "Infinity",
        "+-1",
        "--1",
        "1_000",
        "١٣",
        "１２",
    ),
)
def test_sec_durweek_rejects_values_outside_sec_decimal_grammar(source: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    with pytest.raises(ValueError, match="unsupported SEC week duration"):
        FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durweek"](source)


def test_sec_durweek_is_exact_under_small_ambient_decimal_precision() -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()
    lexical = "123456789012345678901234567890.9"

    with localcontext() as context:
        context.prec = 2
        actual = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durweek"](lexical)

    assert actual == "P864197523086419752308641975236D"
