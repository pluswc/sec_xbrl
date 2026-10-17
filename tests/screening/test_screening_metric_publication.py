from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from sec_xbrl.analysis import VERSION as ANALYSIS_VERSION
from sec_xbrl.analysis import stable
from sec_xbrl.history import _write_records
from sec_xbrl.metrics.screening import (
    MANIFEST as METRIC_MANIFEST,
)
from sec_xbrl.metrics.screening import (
    ScreeningMetricReader,
    _company_year_windows,
    _validate_source_year_windows,
    expanded_analysis_profile,
    publish_screening_metrics,
)
from sec_xbrl.metrics.screening import (
    _validate_config as _validate_metric_config,
)
from sec_xbrl.screening.common import canonical_json, digest_value, sha256_file
from sec_xbrl.screening.dataset_v2 import (
    ScreeningDatasetV2Reader,
    publish_screening_dataset_v2,
)
from sec_xbrl.screening.dataset_v3 import (
    ScreeningDatasetV3Reader,
    publish_screening_dataset_v3,
)
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore


class _IdentityDataset:
    companies: ClassVar[list[dict]] = [
        {"cik": "0000000001", "ticker": "TEST", "name": "Test Inc.", "sic_code": "3571"}
    ]
    metadata: ClassVar[list[dict]] = [
        {
            "cik": "0000000001", "name": "Test Inc.", "tickers": ["TEST"],
            "sic_code": "3571", "sic_description": "Electronic Computers",
            "financial_prepared": True,
        },
        {
            "cik": "0000000002", "name": "Unknown Co.", "tickers": ["UNK"],
            "sic_code": None, "sic_description": None, "financial_prepared": False,
        },
    ]

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.publication_id = "identity-source-v1"
        self.manifest = {
            "publication_id": self.publication_id,
            "financial_as_of": "2026-10-08",
            "versions": {"parser_version": "m2-layer1-v5", "concept_mapping_versions": ["mapping-v1"]},
            "sources": {"metadata": {"publication_id": "metadata-v1"}},
        }

    def verify_all(self) -> dict:
        return {"publication_id": self.publication_id}


def _analysis_bundle(
    root: Path,
    years: tuple[int, ...] = (2024, 2025),
    *,
    ticker: str = "TEST",
    cik: str = "0000000001",
    financial_as_of: str = "2026-10-08",
    history_root: Path | None = None,
) -> Path:
    profile = expanded_analysis_profile()
    rows = []
    cells = []
    traces = {digit: [] for digit in "0123456789abcdef"}
    qnames = {row["row_id"]: row["concepts"][0] for row in profile}
    statement = {
        row["row_id"]: row["section"]
        for row in profile
    }
    for row in profile:
        rows.append(
            {
                "row_id": row["row_id"],
                "label": row["label"],
                "period_class": row["period_class"],
            }
        )
        for year in years:
            cell_id = f"cell-{row['row_id']}-{year}"
            start = f"{year - 1}-12-31" if row["period_class"] == "FY" else None
            end = f"{year}-12-29"
            qname = qnames[row["row_id"]]
            evidence = [
                {
                    "statement_types": [statement[row["row_id"]]],
                    "source_relationship_edge_id": f"edge-{row['row_id']}",
                    "accession": f"{cik}-{year}-000001",
                }
            ]
            cell = {
                "row_id": row["row_id"],
                "cell_id": cell_id,
                "fiscal_year": year,
                "fiscal_quarter": 4,
                "period_class": row["period_class"],
                "start": start,
                "end": end,
                "value": "100",
                "status": "REPORTED",
                "quality_status": None,
                "quality_reasons": [],
                "unit": ['["iso4217:USD"]', "[]"],
                "dimensions": [],
                "basis_version": None,
                "semantic_id": qname,
                "source_fact_id": f"fact-{row['row_id']}-{year}",
                "primary_statement_evidence": evidence,
            }
            cells.append(cell)
            lineage = {
                "accession": f"{cik}-{year}-000001",
                "source_filing_id": f"filing-{year}",
                "selected_source_fact_id": cell["source_fact_id"],
                "raw_concept_qname": qname,
                "raw_concept_taxonomy_family": "us-gaap",
                "raw_concept_data_type": "xbrli:monetaryItemType",
                "raw_concept_period_type": "duration" if row["period_class"] == "FY" else "instant",
                "raw_concept_is_standard": True,
                "company_canonical_concept_id": qname,
                "mapping_review_required": False,
                "concept_mapping_version": "mapping-v1",
                "selection_rule_version": "selection-v1",
                "classification_rule_version": "period-v1",
                "context_start_date": start,
                "context_end_date": end if row["period_class"] == "FY" else None,
                "context_instant_date": end if row["period_class"] == "INSTANT" else None,
                "primary_statement_evidence": evidence,
            }
            trace = {"cell_id": cell_id, "value_lineage": lineage}
            traces[stable(cell_id)[0]].append(trace)
    files = {}
    datasets = {"core_rows": rows, "core_cells": cells}
    datasets.update({f"trace_{digit}": traces[digit] for digit in traces})
    for name, records in datasets.items():
        relative = f"{ticker}/LATEST_REPORTED/{name}.parquet"
        files[name] = {"path": relative, **_write_records(root / relative, tuple(records))}
    manifest = {
        "version": ANALYSIS_VERSION,
        "publication_id": "expanded-analysis-v1",
        "period_mode": "ANNUAL",
        "balance_scope": {"included": True, "rule_version": "annual-exact-year-end-instant-v1"},
        "companies": {
            ticker: {
                "as_of": financial_as_of, "years": list(years),
                "views": {"LATEST_REPORTED": {"files": files}},
            }
        },
    }
    if history_root is not None:
        history_root = history_root.resolve()
        manifest["source_manifest_hashes"] = {
            "history_manifest_sha256": sha256_file(
                history_root / "history_manifest.json"
            )
        }
        manifest["companies"][ticker]["source_publication"] = str(history_root)
    (root / "analysis_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _prepare_metric_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    years: tuple[int, ...] = (2024, 2025),
    input_years: list[int] | None = None,
    display_years: list[int] | None = None,
) -> SimpleNamespace:
    analysis = _analysis_bundle(tmp_path / "analysis", years)
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "screening_dataset_manifest.json").write_text("{}")
    monkeypatch.setattr("sec_xbrl.screening.dataset.ScreeningDatasetReader", _IdentityDataset)
    company = {
        "ticker": "TEST",
        "cik": "0000000001",
        "analysis_root": str(analysis),
        "analysis_manifest_sha256": sha256_file(analysis / "analysis_manifest.json"),
    }
    if input_years is not None or display_years is not None:
        company.update(input_years=input_years, display_years=display_years)
    config = tmp_path / "metric-config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "screening-metric-config-v1",
                "financial_as_of": "2026-10-08",
                "source_dataset_root": str(identity),
                "source_dataset_manifest_sha256": sha256_file(
                    identity / "screening_dataset_manifest.json"
                ),
                "companies": [company],
            }
        )
    )
    metrics = tmp_path / "metrics"
    publish_screening_metrics(config, metrics)
    return SimpleNamespace(
        root=tmp_path, analysis=analysis, identity=identity, config=config, metrics=metrics
    )


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch):
    return _prepare_metric_publication(tmp_path, monkeypatch)


def test_metric_publication_roundtrip_and_31_definition_coverage(prepared) -> None:
    reader = ScreeningMetricReader(prepared.metrics)
    status = reader.verify_all()
    assert reader.verify_governed_sources()["status"] == "PASS"
    assert status["definitions"] == 31
    assert status["observations"] == 62
    assert {row["fiscal_year"] for row in reader.observations} == {2024, 2025}
    assert "input_years" not in reader.manifest["config"]["companies"][0]
    assert "display_years" not in reader.manifest["sources"][0]
    assert len(reader.support) == 31
    assert all(row["execution_supported"] for row in reader.support)
    versions = {row["metric_id"]: row["definition_version"] for row in reader.definitions}
    assert versions["revenue"] == "annual-core-reported-v1"
    assert versions["cfo"] == "annual-core-reported-v1"
    assert versions["operating_income"] == "annual-core-reported-v1"
    assert versions["net_income"] == "annual-core-reported-v1"
    assert next(row for row in reader.observations if row["metric_id"] == "current_ratio")["unit"] == "PERCENT"


def test_annual_five_input_four_display_opens_through_v2_and_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare_metric_publication(
        tmp_path,
        monkeypatch,
        years=(2021, 2022, 2023, 2024, 2025),
        input_years=[2021, 2022, 2023, 2024, 2025],
        display_years=[2022, 2023, 2024, 2025],
    )
    metric_reader = ScreeningMetricReader(prepared.metrics)
    assert metric_reader.verify_governed_sources()["status"] == "PASS"
    assert {row["fiscal_year"] for row in metric_reader.observations} == {
        2022,
        2023,
        2024,
        2025,
    }
    assert metric_reader.manifest["config"]["companies"][0]["input_years"] == [
        2021,
        2022,
        2023,
        2024,
        2025,
    ]
    assert metric_reader.manifest["sources"][0]["display_years"] == [
        2022,
        2023,
        2024,
        2025,
    ]
    first_yoy = next(
        row
        for row in metric_reader.observations
        if row["metric_id"] == "revenue_yoy" and row["fiscal_year"] == 2022
    )
    assert first_yoy["availability_status"] == "AVAILABLE"
    published_ids = {row["metric_observation_id"] for row in metric_reader.observations}
    assert len(first_yoy["input_observation_ids"]) == 2
    assert any(identifier not in published_ids for identifier in first_yoy["input_observation_ids"])

    monkeypatch.setattr("sec_xbrl.screening.dataset_v2.ScreeningDatasetReader", _IdentityDataset)
    v2_config = tmp_path / "v2-config.json"
    v2_config.write_text(
        json.dumps(
            {
                "schema_version": "screening-prepare-config-v2",
                "dataset_id": "windowed-v2",
                "fixture_kind": "ACTUAL_PREPARED",
                "financial_as_of": "2026-10-08",
                "metric_root": str(prepared.metrics),
                "metric_manifest_sha256": sha256_file(
                    prepared.metrics / "screening_metric_manifest.json"
                ),
                "source_dataset_root": str(prepared.identity),
                "source_dataset_manifest_sha256": sha256_file(
                    prepared.identity / "screening_dataset_manifest.json"
                ),
            }
        )
    )
    v2_root = tmp_path / "dataset-v2"
    publish_screening_dataset_v2(v2_config, v2_root)
    annual = ScreeningDatasetV2Reader(v2_root)
    assert {row["fiscal_year"] for row in annual.observations} == {2022, 2023, 2024, 2025}

    quarter_root = tmp_path / "quarter"
    quarter_root.mkdir()
    quarter_manifest = quarter_root / "quarterly_screening_metric_manifest.json"
    quarter_manifest.write_text("{}")
    annual_metrics = annual.manifest["sources"]["metrics"]

    class _QuarterlyDataset:
        def __init__(self, root: Path | str, manifest_sha256: str | None = None):
            assert Path(root) == quarter_root
            assert manifest_sha256 in {None, sha256_file(quarter_manifest)}
            self.publication_id = "quarter-window-test-v1"
            self.manifest = {
                "publication_id": self.publication_id,
                "financial_as_of": "2026-10-08",
                "universe": {"ciks": ["0000000001"]},
                "annual_parent": {
                    "schema_version": "screening-metric-publication-v1",
                    "publication_id": annual_metrics["publication_id"],
                    "manifest_sha256": annual_metrics["manifest_sha256"],
                    "company_membership_sha256": hashlib.sha256(
                        b"0000000001\n"
                    ).hexdigest(),
                },
            }
            self.definitions = []
            self.support = []
            self.observations = []
            self.period_inventory = []

    monkeypatch.setattr(
        "sec_xbrl.screening.dataset_v3.QuarterlyScreeningMetricReader",
        _QuarterlyDataset,
    )
    v3_config = tmp_path / "v3-config.json"
    v3_config.write_text(
        json.dumps(
            {
                "schema_version": "screening-prepare-config-v3",
                "dataset_id": "windowed-v3",
                "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
                "annual_dataset_root": str(v2_root),
                "annual_manifest_sha256": sha256_file(
                    v2_root / "screening_dataset_manifest.json"
                ),
                "quarterly_metric_root": str(quarter_root),
                "quarterly_manifest_sha256": sha256_file(quarter_manifest),
            }
        )
    )
    v3_root = tmp_path / "dataset-v3"
    publish_screening_dataset_v3(v3_config, v3_root)
    v3 = ScreeningDatasetV3Reader(v3_root)
    assert {row["fiscal_year"] for row in v3.observations} == {2022, 2023, 2024, 2025}


def test_annual_window_config_and_source_scope_fail_closed() -> None:
    base = {
        "schema_version": "screening-metric-config-v1",
        "financial_as_of": "2026-10-08",
        "source_dataset_root": "/identity",
        "source_dataset_manifest_sha256": "a" * 64,
        "companies": [
            {
                "ticker": "TEST",
                "cik": "0000000001",
                "analysis_root": "/analysis",
                "analysis_manifest_sha256": "b" * 64,
                "input_years": [2021, 2022, 2023, 2024, 2025],
                "display_years": [2022, 2023, 2024, 2025],
            }
        ],
    }
    assert _validate_metric_config(base) == base
    for field, value, message in (
        ("display_years", None, "declared together"),
        ("display_years", [2021, 2022, 2023, 2024], "latest ordered subset"),
        ("input_years", [2020, 2021, 2022, 2023, 2024, 2025], "integer fiscal years"),
        ("input_years", [2021, 2022, True, 2024, 2025], "integer fiscal years"),
    ):
        attacked = json.loads(json.dumps(base))
        if value is None:
            attacked["companies"][0].pop(field)
        else:
            attacked["companies"][0][field] = value
        with pytest.raises(ValueError, match=message):
            _validate_metric_config(attacked)

    company = base["companies"][0]
    assert _company_year_windows(company, [2021, 2022, 2023, 2024, 2025]) == (
        [2021, 2022, 2023, 2024, 2025],
        [2022, 2023, 2024, 2025],
    )
    with pytest.raises(ValueError, match="prepared years differ"):
        _company_year_windows(company, [2022, 2023, 2024, 2025])
    with pytest.raises(ValueError, match="declaration changed"):
        _validate_source_year_windows(company, {})
    with pytest.raises(ValueError, match="year windows changed"):
        _validate_source_year_windows(
            company,
            {
                "input_years": [2021, 2022, 2023, 2024, 2025],
                "display_years": [2021, 2022, 2023, 2024],
            },
        )


def test_metric_reader_rejects_coordinated_output_rehash_and_parent_change(prepared) -> None:
    observations_path = prepared.metrics / "metric_observations.json"
    observations = json.loads(observations_path.read_text())
    next(row for row in observations if row["availability_status"] == "AVAILABLE")["value"] = "999"
    observations_path.write_text(canonical_json(observations) + "\n")
    manifest_path = prepared.metrics / METRIC_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    declared = next(row for row in manifest["files"] if row["path"] == "metric_observations.json")
    declared.update(sha256=hashlib.sha256(observations_path.read_bytes()).hexdigest(), size=observations_path.stat().st_size)
    manifest["publication_id"] = "screening-metrics-" + digest_value(
        {
            "config": manifest["config"],
            "definitions": json.loads((prepared.metrics / "metric_definitions.json").read_text()),
            "observations": observations,
            "support": json.loads((prepared.metrics / "metric_support.json").read_text()),
            "sources": manifest["sources"],
        }
    )[:24]
    manifest_path.write_text(canonical_json(manifest) + "\n")
    reader = ScreeningMetricReader(prepared.metrics)
    with pytest.raises(ValueError, match="differ from governed prepared inputs"):
        reader.verify_governed_sources()


def test_metric_reader_rejects_changed_prepared_parent(prepared) -> None:
    cells = prepared.analysis / "TEST/LATEST_REPORTED/core_cells.parquet"
    cells.write_bytes(cells.read_bytes() + b"tamper")
    reader = ScreeningMetricReader(prepared.metrics)
    with pytest.raises(ValueError, match="data hash mismatch"):
        reader.verify_governed_sources()


def test_publishers_require_exact_declared_parent_manifest_hashes(
    prepared, monkeypatch
) -> None:
    bad_metric_config = prepared.root / "bad-metric-config.json"
    metric_config = json.loads(prepared.config.read_text())
    metric_config["source_dataset_manifest_sha256"] = "0" * 64
    bad_metric_config.write_text(json.dumps(metric_config))
    with pytest.raises(ValueError, match="identity source manifest differs"):
        publish_screening_metrics(bad_metric_config, prepared.root / "bad-metrics")

    monkeypatch.setattr("sec_xbrl.screening.dataset_v2.ScreeningDatasetReader", _IdentityDataset)
    bad_v2_config = prepared.root / "bad-v2-config.json"
    bad_v2_config.write_text(
        json.dumps(
            {
                "schema_version": "screening-prepare-config-v2",
                "dataset_id": "bad-v2",
                "fixture_kind": "ACTUAL_PREPARED",
                "financial_as_of": "2026-10-08",
                "metric_root": str(prepared.metrics),
                "metric_manifest_sha256": "0" * 64,
                "source_dataset_root": str(prepared.identity),
                "source_dataset_manifest_sha256": sha256_file(
                    prepared.identity / "screening_dataset_manifest.json"
                ),
            }
        )
    )
    with pytest.raises(ValueError, match="metric manifest differs"):
        publish_screening_dataset_v2(bad_v2_config, prepared.root / "bad-v2")


def test_dataset_v2_catalog_old_revision_and_instant_predicate(prepared, monkeypatch) -> None:
    monkeypatch.setattr("sec_xbrl.screening.dataset_v2.ScreeningDatasetReader", _IdentityDataset)
    config = prepared.root / "v2-config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "screening-prepare-config-v2",
                "dataset_id": "expanded-v2",
                "fixture_kind": "ACTUAL_PREPARED",
                "financial_as_of": "2026-10-08",
                "metric_root": str(prepared.metrics),
                "metric_manifest_sha256": sha256_file(
                    prepared.metrics / "screening_metric_manifest.json"
                ),
                "source_dataset_root": str(prepared.identity),
                "source_dataset_manifest_sha256": sha256_file(
                    prepared.identity / "screening_dataset_manifest.json"
                ),
            }
        )
    )
    destination = prepared.root / "dataset-v2"
    publish_screening_dataset_v2(config, destination)
    reader = ScreeningDatasetV2Reader(destination)
    assert reader.verify_all()["definition_count"] == 31

    service = ScreeningService.__new__(ScreeningService)
    service.datasets = {"expanded-v2": reader}
    service.store = ScreeningStore(prepared.root / "journal.sqlite")
    catalog = service.metric_catalog("expanded-v2")
    assert len(catalog) == 31
    current_ratio = next(row for row in catalog if row["metric_id"] == "current_ratio")
    assert current_ratio["category"] == "FINANCIAL_STABILITY"
    assert current_ratio["unit_kind"] == "PERCENT"
    assert current_ratio["coverage"] == {
        "companies_available": 1, "companies_total": 1, "periods_available": 2,
    }
    screen = service.create_screen(
        "legacy revenue and instant ratio",
        {
            "universe": {"mode": "ALL_PREPARED"},
            "period_policy": {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": 2025},
            "predicates": [
                {"metric_id": "revenue", "operator": "GTE", "threshold": "0", "definition_version": "annual-core-reported-v1"},
                {"metric_id": "current_ratio", "operator": "GTE", "threshold": "100", "definition_version": "screening-current-ratio-v1"},
            ],
            "columns": ["company", "aggregate", "predicates"],
            "sort": {"column": "cik", "direction": "ASC"},
        },
    )
    run = service.execute(screen["revision_id"], "expanded-v2")
    assert run["counts"] == {"fail": 0, "pass": 1, "undetermined": 0, "target": 1, "quality_block": 0}
    assert {row["observation"]["period_class"] for row in run["rows"][0]["predicates"]} == {"FY", "INSTANT"}

    attacks = {
        "as-of": lambda manifest: manifest.update(financial_as_of="2099-01-01"),
        "publication": lambda manifest: manifest.update(publication_id="screening-dataset-forged"),
        "fixture": lambda manifest: manifest.update(fixture_kind="SYNTHETIC_ERROR_FIXTURE"),
        "ciks": lambda manifest: manifest.update(configured_ciks=[]),
        "companies": lambda manifest: manifest.update(configured_companies=[]),
        "count": lambda manifest: manifest.update(company_count=99),
        "source": lambda manifest: manifest["sources"]["metrics"].update(
            publication_id="screening-metrics-forged"
        ),
        "versions": lambda manifest: manifest.update(versions={}),
    }
    for name, mutate in attacks.items():
        attacked = prepared.root / f"dataset-v2-{name}"
        shutil.copytree(destination, attacked)
        manifest_path = attacked / "screening_dataset_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        mutate(manifest)
        manifest_path.write_text(canonical_json(manifest) + "\n")
        with pytest.raises(ValueError):
            ScreeningDatasetV2Reader(attacked)

    copied_config = prepared.root / "copied-v2-config.json"
    copied_config.write_bytes(config.read_bytes())
    attacked = prepared.root / "dataset-v2-config-path"
    shutil.copytree(destination, attacked)
    manifest_path = attacked / "screening_dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config_path"] = str(copied_config)
    manifest_path.write_text(canonical_json(manifest) + "\n")
    with pytest.raises(ValueError, match="publication identity"):
        ScreeningDatasetV2Reader(attacked)


def test_dataset_v2_reader_does_not_recompute_financial_formulas(prepared, monkeypatch) -> None:
    monkeypatch.setattr("sec_xbrl.screening.dataset_v2.ScreeningDatasetReader", _IdentityDataset)
    config = prepared.root / "v2-no-recompute-config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "screening-prepare-config-v2",
                "dataset_id": "expanded-no-recompute-v2",
                "fixture_kind": "ACTUAL_PREPARED",
                "financial_as_of": "2026-10-08",
                "metric_root": str(prepared.metrics),
                "metric_manifest_sha256": sha256_file(
                    prepared.metrics / "screening_metric_manifest.json"
                ),
                "source_dataset_root": str(prepared.identity),
                "source_dataset_manifest_sha256": sha256_file(
                    prepared.identity / "screening_dataset_manifest.json"
                ),
            }
        )
    )
    destination = prepared.root / "dataset-no-recompute-v2"
    publish_screening_dataset_v2(config, destination)

    def forbidden(*args, **kwargs):
        raise AssertionError("consumer must not recompute a financial formula")

    monkeypatch.setattr("sec_xbrl.metrics.screening._derived_observations", forbidden)
    assert ScreeningDatasetV2Reader(destination).verify_all()["definition_count"] == 31

