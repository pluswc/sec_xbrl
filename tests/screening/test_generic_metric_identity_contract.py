from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.metrics.screening import _validate_config as validate_metric_config
from sec_xbrl.screening.dataset_v2 import (
    EXPLICIT_IDENTITY_CONFIG_VERSION as DATASET_V2_IDENTITY_CONFIG_VERSION,
)
from sec_xbrl.screening.dataset_v2 import _validate_config as validate_dataset_v2_config
from sec_xbrl.screening.metric_identity import (
    CONFIG_VERSION,
    SOURCE_KIND,
    _quarter_spine,
)
from sec_xbrl.screening.metric_identity import (
    _validate_config as validate_identity_config,
)


def _identity_config() -> dict:
    company = {
        "ticker": "TEST",
        "cik": "0000000001",
        "input_years": [2021, 2022, 2023, 2024, 2025],
        "display_years": [2022, 2023, 2024, 2025],
        "history_root": "/governed/history",
        "history_manifest_sha256": "1" * 64,
        "annual_analysis_root": "/governed/annual",
        "annual_analysis_manifest_sha256": "2" * 64,
        "quarterly_analysis_root": "/governed/quarterly",
        "quarterly_analysis_manifest_sha256": "3" * 64,
    }
    return {
        "schema_version": CONFIG_VERSION,
        "source_kind": SOURCE_KIND,
        "universe_id": "exact-50",
        "financial_as_of": "2026-10-10",
        "metadata_observation_cutoff": "2026-10-13T23:59:59+00:00",
        "annual_window": {"input_fiscal_years": 5, "display_fiscal_years": 4},
        "global_quarter_spine": _quarter_spine("2026-10-10"),
        "collection_scope_mode": "EXPLICIT_SUBSET",
        "collection_scope_companies": [
            {"ticker": company["ticker"], "cik": company["cik"]}
        ],
        "collection_manifest": "/governed/collection/collection_manifest.json",
        "collection_manifest_sha256": "4" * 64,
        "metadata_root": "/governed/metadata",
        "metadata_manifest_sha256": "5" * 64,
        "quality_root": "/governed/quality",
        "quality_manifest_sha256": "6" * 64,
        "companies": [company],
    }


def test_identity_config_pins_approved_annual_and_quarter_windows() -> None:
    normalized = validate_identity_config(_identity_config())
    assert normalized["source_kind"] == SOURCE_KIND
    assert normalized["collection_scope_mode"] == "EXPLICIT_SUBSET"
    assert normalized["metadata_observation_cutoff"] == "2026-10-13T23:59:59Z"
    assert normalized["global_quarter_spine"] == [
        {"calendar_year": 2024, "calendar_quarter": 4},
        {"calendar_year": 2025, "calendar_quarter": 1},
        {"calendar_year": 2025, "calendar_quarter": 2},
        {"calendar_year": 2025, "calendar_quarter": 3},
        {"calendar_year": 2025, "calendar_quarter": 4},
        {"calendar_year": 2026, "calendar_quarter": 1},
        {"calendar_year": 2026, "calendar_quarter": 2},
        {"calendar_year": 2026, "calendar_quarter": 3},
    ]


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(source_kind="LEGACY_UNIVERSE_DELIVERY"),
        lambda value: value.update(collection_scope_mode="INFER"),
        lambda value: value.pop("metadata_observation_cutoff"),
        lambda value: value.update(metadata_observation_cutoff="2026-10-13T23:59:59"),
        lambda value: value.update(collection_scope_companies=[]),
        lambda value: value.update(
            annual_window={"input_fiscal_years": 4, "display_fiscal_years": 4}
        ),
        lambda value: value["companies"][0].update(
            display_years=[2021, 2022, 2023, 2024]
        ),
        lambda value: value["global_quarter_spine"].pop(),
    ),
)
def test_identity_config_rejects_inference_and_scope_drift(mutate) -> None:
    config = _identity_config()
    mutate(config)
    with pytest.raises(ValueError):
        validate_identity_config(config)


def test_annual_metric_config_v2_requires_one_explicit_identity_source() -> None:
    identity = _identity_config()
    company = identity["companies"][0]
    config = {
        "schema_version": "screening-metric-config-v2",
        "financial_as_of": identity["financial_as_of"],
        "identity_source": {
            "kind": SOURCE_KIND,
            "root": "/governed/identity",
            "manifest_sha256": "7" * 64,
        },
        "companies": [
            {
                "ticker": company["ticker"],
                "cik": company["cik"],
                "analysis_root": company["annual_analysis_root"],
                "analysis_manifest_sha256": company[
                    "annual_analysis_manifest_sha256"
                ],
                "input_years": company["input_years"],
                "display_years": company["display_years"],
            }
        ],
    }
    assert validate_metric_config(config)["identity_source"]["kind"] == SOURCE_KIND

    mixed = deepcopy(config)
    mixed["source_dataset_root"] = "/legacy"
    with pytest.raises(ValueError, match="cannot mix"):
        validate_metric_config(mixed)

    missing_kind = deepcopy(config)
    missing_kind["identity_source"].pop("kind")
    with pytest.raises(ValueError, match="explicit identity source kind"):
        validate_metric_config(missing_kind)


def test_annual_dataset_v2_explicit_identity_schema_is_distinct_from_combined_v3() -> None:
    assert DATASET_V2_IDENTITY_CONFIG_VERSION == "screening-prepare-config-v2-identity-v1"
    config = {
        "schema_version": DATASET_V2_IDENTITY_CONFIG_VERSION,
        "dataset_id": "generic-annual-screening",
        "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
        "financial_as_of": "2026-10-10",
        "metric_root": "/governed/metrics",
        "metric_manifest_sha256": "8" * 64,
        "identity_source": {
            "kind": SOURCE_KIND,
            "root": "/governed/identity",
            "manifest_sha256": "7" * 64,
        },
    }
    assert validate_dataset_v2_config(config)["identity_source"]["kind"] == SOURCE_KIND

    combined_v3 = deepcopy(config)
    combined_v3["schema_version"] = "screening-prepare-config-v3"
    with pytest.raises(ValueError, match="unsupported screening v2 config"):
        validate_dataset_v2_config(combined_v3)

    mixed = deepcopy(config)
    mixed["source_dataset_root"] = "/legacy"
    with pytest.raises(ValueError, match="cannot mix"):
        validate_dataset_v2_config(mixed)
