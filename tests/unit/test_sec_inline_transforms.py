from __future__ import annotations

from decimal import localcontext

import pytest

from sec_xbrl.facts.layer1 import Layer1Extractor
from sec_xbrl.filing.sec_inline_transforms import (
    SEC_TRANSFORM_NAMESPACE,
    _decimal_duration,
    register_sec_inline_transforms,
)


def test_registers_sec_efm_transforms_used_by_inline_filings() -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()
    transforms = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]

    assert transforms["durday"]("2.1") == "P2DT2H"
    assert transforms["durweek"]("13") == "P91D"
    assert transforms["durmonth"]("2.25") == "P2M7D"
    assert transforms["duryear"]("4.55") == "P4Y6M18D"
    assert transforms["durwordsen"]("twelve months") == "P12M"
    assert transforms["numwordsen"]("nineteen hundred forty-four") == "1944"
    assert transforms["stateprovnameen"]("Delaware") == "DE"
    assert transforms["exchnameen"]("The Nasdaq Stock Market LLC") == "NASDAQ"
    assert transforms["entityfilercategoryen"]("Large accelerated filer") == "Large Accelerated Filer"


def test_duration_conformance_has_distinct_immutable_layer1_parser_version() -> None:
    assert Layer1Extractor.parser_version == "m2-layer1-v4"


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("4.55", "P4Y6M18D"),
        ("-4.55", "-P4Y6M18D"),
        ("2.74", "P2Y8M26D"),
        ("5.98", "P5Y11M23D"),
        ("0.999", "P0Y11M30D"),
        ("0.01", "P0Y3D"),
        ("1", "P1Y"),
        ("-1", "-P1Y"),
        ("0", "P0Y"),
        ("-0", "P0Y"),
        ("-0.001", "P0Y"),
    ),
)
def test_sec_duryear_uses_sec_component_truncation(source: str, expected: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    assert FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["duryear"](source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("1.5", "P1M15D"),
        ("-1.5", "-P1M15D"),
        ("0.5", "P0M15D"),
        ("2", "P2M"),
        ("-2", "-P2M"),
        ("0", "P0M"),
        ("-0", "P0M"),
        ("-0.001", "P0M"),
    ),
)
def test_sec_durmonth_uses_sec_component_truncation(source: str, expected: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    assert FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durmonth"](source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("2.5", "P2DT12H"),
        ("-2.5", "-P2DT12H"),
        ("0.1", "P0DT2H"),
        ("2", "P2D"),
        ("-2", "-P2D"),
        ("0", "P0D"),
        ("-0", "P0D"),
        ("-0.001", "P0D"),
    ),
)
def test_sec_durday_uses_sec_component_truncation(source: str, expected: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    assert FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durday"](source) == expected


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


@pytest.mark.parametrize("transform_name", ("durday", "durmonth", "duryear"))
@pytest.mark.parametrize(
    "source",
    (
        "",
        " \t\n\r ",
        "words",
        "13 days",
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
def test_sec_numeric_durations_reject_values_outside_sec_decimal_grammar(
    transform_name: str, source: str
) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    with pytest.raises(ValueError, match=r"unsupported SEC .* duration"):
        FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE][transform_name](source)


@pytest.mark.parametrize("transform_name", ("durday", "durweek", "durmonth", "duryear"))
def test_sec_numeric_durations_reject_non_string_input(transform_name: str) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    with pytest.raises(ValueError, match=r"unsupported SEC .* duration"):
        FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE][transform_name](13)  # type: ignore[arg-type]


def test_sec_decimal_duration_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="unsupported SEC duration unit"):
        _decimal_duration("1", "W")


@pytest.mark.parametrize(
    ("transform_name", "expected"),
    (
        ("durday", "P2DT12H"),
        ("durweek", "P17D"),
        ("durmonth", "P2M15D"),
        ("duryear", "P2Y6M"),
    ),
)
def test_sec_numeric_durations_allow_only_surrounding_xml_whitespace(
    transform_name: str, expected: str
) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    actual = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE][transform_name](
        " \t\n+2.5\r "
    )
    assert actual == expected


def test_sec_durweek_is_exact_under_small_ambient_decimal_precision() -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()
    lexical = "123456789012345678901234567890.9"

    with localcontext() as context:
        context.prec = 2
        actual = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE]["durweek"](lexical)

    assert actual == "P864197523086419752308641975236D"


@pytest.mark.parametrize(
    ("transform_name", "lexical", "expected"),
    (
        ("duryear", "123456789012345678901234567890.55", "P123456789012345678901234567890Y6M18D"),
        ("durmonth", "123456789012345678901234567890.5", "P123456789012345678901234567890M15D"),
        ("durday", "123456789012345678901234567890.5", "P123456789012345678901234567890DT12H"),
    ),
)
def test_sec_numeric_durations_are_exact_under_small_ambient_decimal_precision(
    transform_name: str, lexical: str, expected: str
) -> None:
    from arelle import FunctionIxt

    register_sec_inline_transforms()

    with localcontext() as context:
        context.prec = 2
        actual = FunctionIxt.ixtNamespaceFunctions[SEC_TRANSFORM_NAMESPACE][transform_name](lexical)

    assert actual == expected
