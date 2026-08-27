"""SEC-specific Inline XBRL transformations missing from arelle-release.

The SEC EFM defines these transformations in the 2015-08-31 namespace.  They
are executable parser dependencies, not filing-taxonomy resources, so they are
registered before both online bootstrap and offline Arelle loads.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

SEC_TRANSFORM_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"

_NUMBER_WORDS = {
    "zero": 0, "no": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_STATE_CODES = {
    "delaware": "DE", "california": "CA", "washington": "WA", "new york": "NY",
    "texas": "TX", "virginia": "VA", "massachusetts": "MA", "new jersey": "NJ",
    "pennsylvania": "PA", "florida": "FL", "illinois": "IL", "colorado": "CO",
    "connecticut": "CT", "maryland": "MD", "minnesota": "MN", "michigan": "MI",
    "ohio": "OH", "north carolina": "NC", "georgia": "GA", "arizona": "AZ",
    "nevada": "NV", "oregon": "OR", "utah": "UT", "ontario": "ON",
}
_EXCHANGE_CODES = {
    "nasdaq global select market": "NASDAQ", "nasdaq stock market": "NASDAQ",
    "new york stock exchange": "NYSE",
    "nyse american": "NYSEAMER", "nyse arca": "NYSEArca",
}
_FILER_CATEGORIES = {
    "large accelerated filer": "Large Accelerated Filer",
    "accelerated filer": "Accelerated Filer",
    "non-accelerated filer": "Non-accelerated Filer",
    "smaller reporting company": "Smaller Reporting Company",
    "emerging growth company": "Emerging Growth Company",
}


def register_sec_inline_transforms() -> None:
    """Register the SEC EFM transforms for the installed Arelle process."""
    from arelle import FunctionIxt

    registry: dict[str, Callable[[str], str]] = {
        "durday": lambda value: _decimal_duration(value, "D"),
        "durmonth": lambda value: _decimal_duration(value, "M"),
        "duryear": lambda value: _decimal_duration(value, "Y"),
        "durwordsen": _word_duration,
        "numwordsen": _word_number,
        "stateprovnameen": lambda value: _lookup(value, _STATE_CODES, "state/province"),
        "exchnameen": lambda value: _lookup(_normalize_exchange(value), _EXCHANGE_CODES, "exchange"),
        "entityfilercategoryen": lambda value: _lookup(value, _FILER_CATEGORIES, "filer category"),
        "boolballotbox": _bool_ballot_box,
    }
    FunctionIxt.ixtNamespaceFunctions.setdefault(SEC_TRANSFORM_NAMESPACE, {}).update(registry)


def _decimal_duration(value: str, unit: str) -> str:
    number = Decimal(value.strip())
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    whole = int(magnitude)
    fraction = magnitude - whole
    if unit == "D":
        return f"{sign}P{int(magnitude.to_integral_value(rounding=ROUND_HALF_UP))}D"
    if unit == "M":
        whole_months = int(magnitude)
        days = int(((magnitude - whole_months) * 30).to_integral_value(rounding=ROUND_HALF_UP))
        return f"{sign}P{whole_months}M" if days == 0 else f"{sign}P{whole_months}M{days}D"
    months = int((fraction * 12).to_integral_value(rounding=ROUND_HALF_UP))
    return f"{sign}P{whole}Y" if months == 0 else f"{sign}P{whole}Y{months}M"


def _word_number(value: str) -> str:
    tokens = re.findall(r"[a-z]+|\d+", value.casefold())
    if not tokens:
        raise ValueError("empty English number")
    total = current = 0
    for token in tokens:
        if token == "and":
            continue
        if token.isdigit():
            current += int(token)
        elif token in _NUMBER_WORDS:
            current += _NUMBER_WORDS[token]
        elif token in _SCALES:
            current = max(1, current) * _SCALES[token]
            if _SCALES[token] >= 1000:
                total += current
                current = 0
        else:
            raise ValueError(f"unsupported English number token: {token}")
    return str(total + current)


def _word_duration(value: str) -> str:
    normalized = value.casefold().replace("-", " ")
    match = re.findall(r"((?:[a-z]+|\d+)(?:\s+(?:[a-z]+|\d+))*)\s+(years?|months?|days?)", normalized)
    if not match:
        raise ValueError(f"unsupported English duration: {value}")
    components: dict[str, int] = {"Y": 0, "M": 0, "D": 0}
    for amount, label in match:
        unit = "Y" if label.startswith("year") else "M" if label.startswith("month") else "D"
        components[unit] += int(_word_number(amount))
    result = "P" + (f"{components['Y']}Y" if components["Y"] else "") + (f"{components['M']}M" if components["M"] else "") + (f"{components['D']}D" if components["D"] else "")
    return result if result != "P" else "P0D"


def _lookup(value: str, mapping: dict[str, str], label: str) -> str:
    key = " ".join(value.casefold().split())
    if key not in mapping:
        raise ValueError(f"unsupported SEC {label}: {value}")
    return mapping[key]


def _bool_ballot_box(value: str) -> str:
    """Translate the SEC EFM ballot-box glyphs to XML Schema booleans.

    The SEC ``boolballotbox`` transform accepts only the three ballot-box
    characters.  Reject every other input so an unexpected filing value remains
    a validation failure rather than being silently treated as ``false``.
    """
    normalized = value.strip()
    mapping = {"☐": "false", "☑": "true", "☒": "true"}
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported SEC bool ballot box: {value}") from exc


def _normalize_exchange(value: str) -> str:
    key = " ".join(re.sub(r"\b(the|llc|inc)\b|[.,]", "", value.casefold()).split())
    return key
