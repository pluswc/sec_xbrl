from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sec_xbrl.screening.common import digest_value
from sec_xbrl.screening.service import _validate_period_policy
from sec_xbrl.screening.store import _revision_content

ANNUAL_REVISION = {
    "universe": {"mode": "ALL_PREPARED"},
    "predicates": [
        {
            "metric_id": "revenue",
            "operator": "GTE",
            "threshold": "50000000000",
            "definition_version": "annual-core-reported-v1",
        }
    ],
    "period_policy": {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": 2025},
    "columns": ["ticker", "name", "sic_code", "aggregate", "predicates"],
    "sort": {"column": "ticker", "direction": "ASC"},
}


def test_quarter_policy_is_additive_and_annual_revision_identity_is_unchanged() -> None:
    expected = "9048ff2a509e2d19cd3d9cef5f23ed94473fcde9936bc70626d6971f99ab8e82"
    original = copy.deepcopy(ANNUAL_REVISION)

    _validate_period_policy(original["period_policy"])
    normalized = _revision_content(original)

    assert normalized == ANNUAL_REVISION
    assert digest_value(normalized) == expected
    _validate_period_policy(
        {
            "mode": "FIXED_CALENDAR_QUARTER_END",
            "calendar_year": 2026,
            "calendar_quarter": 2,
        }
    )


@pytest.mark.parametrize(
    "policy",
    [
        {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2026},
        {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": 2026, "calendar_quarter": 0},
        {"mode": "FIXED_CALENDAR_QUARTER_END", "calendar_year": True, "calendar_quarter": 2},
        {
            "mode": "FIXED_CALENDAR_QUARTER_END",
            "calendar_year": 2026,
            "calendar_quarter": 2,
            "fiscal_quarter": 2,
        },
    ],
)
def test_quarter_policy_rejects_incomplete_or_fiscal_label_inputs(policy: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="calendar quarter-end"):
        _validate_period_policy(policy)

from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader


def test_wire_v2_is_rejected_for_cross_record_source_contradictions() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "screening_quarterly_wire_v2"
    with pytest.raises(ValueError, match="source|filing"):
        QuarterlyScreeningMetricReader(
            root,
            manifest_sha256="fa743d5d24a228e7f4fd5c541127361f17046f3574184c4b2f17de72252143e3",
        )


def test_superseded_wire_fixture_rejects_noncanonical_ttm_namespace() -> None:
    with pytest.raises(ValueError, match="prefixed"):
        QuarterlyScreeningMetricReader(
            "/tmp/universe50-quarterly-schema-v1",
            manifest_sha256="ff57954804c9866f568903580e368021e0a3ad27f1e3e7ce76fddafa476825f5",
        )
