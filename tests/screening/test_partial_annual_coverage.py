"""Versioned coverage admits genuine short histories without fabricating FY rows."""
from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl.metrics import screening
from sec_xbrl.screening import metric_identity as identity
from sec_xbrl.screening.common import sha256_file, write_json
from sec_xbrl.screening.dataset import GENERIC_IDENTITY_SOURCE_KIND
from tests.screening.test_generic_metric_identity_contract import _identity_config


def _partial(years):
    config = _identity_config()
    config["annual_coverage_policy"] = identity.ANNUAL_COVERAGE_POLICY
    company = config["companies"][0]
    company.update(input_years=years, display_years=years[-4:])
    if not years:
        company.update(annual_analysis_root=None, annual_analysis_manifest_sha256=None)
    return config


def _metric_config(tmp_path, years):
    root = tmp_path / "identity"
    root.mkdir()
    manifest = root / identity.MANIFEST_NAME
    write_json(manifest, {"fixture_kind": "SYNTHETIC_PARTIAL_IDENTITY"})
    return {
        "schema_version": screening.EXPLICIT_IDENTITY_CONFIG_VERSION,
        "financial_as_of": "2026-10-25", "annual_coverage_policy": identity.ANNUAL_COVERAGE_POLICY,
        "identity_source": {"kind": GENERIC_IDENTITY_SOURCE_KIND, "root": str(root),
                            "manifest_sha256": sha256_file(manifest)},
        "companies": [{"ticker": "TEST", "cik": "0000000001", "input_years": years, "display_years": years[-4:],
                       "analysis_root": "/analysis" if years else None,
                       "analysis_manifest_sha256": "f" * 64 if years else None}],
    }


@pytest.mark.parametrize("years", [[], [2025], [2023, 2024, 2025], [2021, 2022, 2023, 2024, 2025]])
def test_explicit_coverage_keeps_requested_and_actual_years_separate(years):
    config = identity._validate_config(_partial(years))
    company = config["companies"][0]
    assert company["input_years"] == years and company["display_years"] == years[-4:]
    assert company["annual_coverage"] == identity.annual_coverage(years, years[-4:])
    old = _partial(years)
    old.pop("annual_coverage_policy")
    if len(years) != 5:
        with pytest.raises(ValueError, match="exactly"):
            identity._validate_config(old)
    malformed = _partial(years)
    malformed["annual_coverage_policy"] = "unknown"
    with pytest.raises(ValueError, match="coverage policy"):
        identity._validate_config(malformed)


def test_empty_coverage_rejects_an_annual_parent_or_non_actual_display_year():
    config = _partial([])
    config["companies"][0]["annual_analysis_root"] = "/invented"
    with pytest.raises(ValueError, match="zero annual coverage"):
        identity._validate_config(config)
    config = _partial([2024, 2025])
    config["companies"][0]["display_years"] = [2023, 2024, 2025]
    with pytest.raises(ValueError, match="latest four"):
        identity._validate_config(config)


def test_coverage_is_bound_to_available_history_and_actual_baseline_filings():
    class History:
        def __init__(self):
            self.manifest = {"tables": [{"ticker": "TEST", "period_class": "FY", "view": "LATEST_REPORTED",
                                        "files": {"columns": {}}}],
                             "plan": {"companies": [{"ticker": "TEST", "filings": [{"form": "10-K"}]}]}}

        def _records(self, _):
            return [{"fiscal_year": 2024, "column_status": "AVAILABLE"},
                    {"fiscal_year": 2025, "column_status": "AVAILABLE"},
                    {"fiscal_year": 2023, "column_status": "UNAVAILABLE"}]

    history = History()
    assert identity._available_history_years(history, "TEST") == [2024, 2025]
    history.manifest = copy.deepcopy(history.manifest)
    history.manifest["plan"]["companies"][0]["filings"] = [{"form": "10-Q"}]
    with pytest.raises(ValueError, match="baseline filing"):
        identity._available_history_years(history, "TEST")
    history.manifest["tables"] = []
    assert identity._available_history_years(history, "TEST") == []


def test_zero_baseline_public_metric_publication_has_support_but_no_numeric_rows(tmp_path, monkeypatch):
    config = _metric_config(tmp_path, [])
    coverage = identity.annual_coverage([], [])
    history_sha = "a" * 64
    identity_reader = SimpleNamespace(
        manifest={"financial_as_of": "2026-10-25", "versions": {}}, publication_id="synthetic-partial-identity",
        companies=[{"ticker": "TEST", "cik": "0000000001", "annual_coverage": coverage,
                    "input_years": [], "display_years": [], "history": {"manifest_sha256": history_sha}}],
        annual_analysis_source=lambda cik: identity._no_annual_source(history_sha),
    )
    root = Path(config["identity_source"]["root"])
    monkeypatch.setattr(screening, "_open_identity_source", lambda _: (
        identity_reader, GENERIC_IDENTITY_SOURCE_KIND, root, root / identity.MANIFEST_NAME,
    ))
    config_path = tmp_path / "config.json"
    write_json(config_path, config)
    publication = screening.publish_screening_metrics(config_path, tmp_path / "metrics")
    reader = screening.ScreeningMetricReader(publication.root)
    assert reader.observations == [] and len(reader.support) == 31
    assert all(row["execution_supported"] is False and row["reasons"] == ["NO_ANNUAL_BASELINE"] for row in reader.support)
    assert not (publication.root / "source_snapshots").exists()
    from sec_xbrl.screening import dataset
    monkeypatch.setattr(dataset, "open_screening_identity_source", lambda **_: identity_reader)
    assert reader.verify_governed_sources()["status"] == "PASS"
    bad = copy.deepcopy(config)
    bad.pop("annual_coverage_policy")
    with pytest.raises(ValueError):
        screening._validate_config(bad)
    identity_reader.companies[0]["annual_coverage"] = identity.annual_coverage([2025], [2025])
    with pytest.raises(ValueError, match="governed History identity"):
        reader.verify_governed_sources()


def test_zero_baseline_prospective_selection_verifies_only_existing_quarter_analysis(tmp_path, monkeypatch):
    from sec_xbrl import financial_storage_reuse, prospective_selection

    root = tmp_path / "history"
    root.mkdir()
    manifest = root / "history_manifest.json"
    payload = {"version": "synthetic-history", "tables": [],
               "plan": {"companies": [{"ticker": "TEST", "filings": [{"form": "10-Q"}]}]}}
    write_json(manifest, payload)
    intake = tmp_path / "intake.json"
    write_json(intake, {})
    build = tmp_path / "build.json"
    write_json(build, {"status": "READY", "ticker": "TEST", "intake_manifest": str(intake),
                       "intake_sha256": sha256_file(intake), "publication": str(root),
                       "history_manifest_sha256": sha256_file(manifest), "plan_sha256": "b" * 64})
    company = {"ticker": "TEST", "cik": "0000000001", "history_root": str(root),
               "history_manifest_sha256": sha256_file(manifest), "input_years": [], "display_years": [],
               "annual_coverage": identity.annual_coverage([], []),
               "annual_analysis_root": None, "annual_analysis_manifest_sha256": None,
               "quarterly_analysis_root": str(tmp_path / "quarter"), "quarterly_analysis_manifest_sha256": "c" * 64}
    prospective = SimpleNamespace(companies={"TEST": {"origin_build_manifest": {"path": str(build),
                                                "sha256": sha256_file(build)}}}, storage_reuse=None)
    monkeypatch.setattr(identity, "HistoryPublicationReader", lambda _: SimpleNamespace(manifest=payload))
    monkeypatch.setattr(identity, "verify_financial_history_source", lambda *_, **__: None)
    monkeypatch.setattr(financial_storage_reuse, "storage_history", lambda *_: None)
    monkeypatch.setattr(identity, "_history_files", lambda _: {})
    analysis_calls = []
    monkeypatch.setattr(identity, "_verify_analysis", lambda *_, **kwargs: analysis_calls.append(kwargs["period_mode"]) or {})
    selected_calls = []
    monkeypatch.setattr(prospective_selection, "verify_reselected_analysis",
                        lambda root, **kwargs: selected_calls.append((root, kwargs["period_mode"])))
    result = identity._verify_company_sources(company, "2026-10-25", tmp_path / "collection.json",
                                              prospective=prospective)
    assert analysis_calls == ["QUARTERLY"]
    assert selected_calls == [(Path(company["quarterly_analysis_root"]), "QUARTERLY")]
    assert result["annual_analysis"] == identity._no_annual_source(sha256_file(manifest))
    assert result["history"]["selection_status"] == "SELECTION_EQUIVALENT"
