from __future__ import annotations

import hashlib
import json
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
    expanded_analysis_profile,
    publish_screening_metrics,
)
from sec_xbrl.screening.common import canonical_json, digest_value, sha256_file
from sec_xbrl.screening.dataset_v2 import (
    ScreeningDatasetV2Reader,
    publish_screening_dataset_v2,
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


def _analysis_bundle(root: Path) -> Path:
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
        for year in (2024, 2025):
            cell_id = f"cell-{row['row_id']}-{year}"
            start = f"{year - 1}-12-31" if row["period_class"] == "FY" else None
            end = f"{year}-12-29"
            qname = qnames[row["row_id"]]
            evidence = [{"statement_types": [statement[row["row_id"]]], "source_relationship_edge_id": f"edge-{row['row_id']}"}]
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
                "accession": f"0000000001-{year}-000001",
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
        relative = f"TEST/LATEST_REPORTED/{name}.parquet"
        files[name] = {"path": relative, **_write_records(root / relative, tuple(records))}
    manifest = {
        "version": ANALYSIS_VERSION,
        "publication_id": "expanded-analysis-v1",
        "period_mode": "ANNUAL",
        "balance_scope": {"included": True, "rule_version": "annual-exact-year-end-instant-v1"},
        "companies": {
            "TEST": {
                "as_of": "2026-10-08", "years": [2024, 2025],
                "views": {"LATEST_REPORTED": {"files": files}},
            }
        },
    }
    (root / "analysis_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch):
    analysis = _analysis_bundle(tmp_path / "analysis")
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "screening_dataset_manifest.json").write_text("{}")
    monkeypatch.setattr("sec_xbrl.screening.dataset.ScreeningDatasetReader", _IdentityDataset)
    config = tmp_path / "metric-config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "screening-metric-config-v1",
                "financial_as_of": "2026-10-08",
                "source_dataset_root": str(identity),
                "companies": [
                    {
                        "ticker": "TEST", "cik": "0000000001", "analysis_root": str(analysis),
                        "analysis_manifest_sha256": sha256_file(analysis / "analysis_manifest.json"),
                    }
                ],
            }
        )
    )
    metrics = tmp_path / "metrics"
    publish_screening_metrics(config, metrics)
    return SimpleNamespace(root=tmp_path, analysis=analysis, identity=identity, config=config, metrics=metrics)


def test_metric_publication_roundtrip_and_31_definition_coverage(prepared) -> None:
    reader = ScreeningMetricReader(prepared.metrics)
    status = reader.verify_all()
    assert reader.verify_governed_sources()["status"] == "PASS"
    assert status["definitions"] == 31
    assert status["observations"] == 62
    assert len(reader.support) == 31
    assert all(row["execution_supported"] for row in reader.support)
    versions = {row["metric_id"]: row["definition_version"] for row in reader.definitions}
    assert versions["revenue"] == "annual-core-reported-v1"
    assert versions["cfo"] == "annual-core-reported-v1"
    assert versions["operating_income"] == "annual-core-reported-v1"
    assert versions["net_income"] == "annual-core-reported-v1"
    assert next(row for row in reader.observations if row["metric_id"] == "current_ratio")["unit"] == "PERCENT"


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
                "source_dataset_root": str(prepared.identity),
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
                "source_dataset_root": str(prepared.identity),
            }
        )
    )
    destination = prepared.root / "dataset-no-recompute-v2"
    publish_screening_dataset_v2(config, destination)

    def forbidden(*args, **kwargs):
        raise AssertionError("consumer must not recompute a financial formula")

    monkeypatch.setattr("sec_xbrl.metrics.screening._derived_observations", forbidden)
    assert ScreeningDatasetV2Reader(destination).verify_all()["definition_count"] == 31

