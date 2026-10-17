from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl.company_metadata import (
    MANIFEST_NAME as METADATA_MANIFEST,
)
from sec_xbrl.company_metadata import (
    SnapshotInput,
    build_company_metadata,
    publish_company_metadata,
)
from sec_xbrl.history import _write_records
from sec_xbrl.metric_quality import prepare_generic_metric_quality
from sec_xbrl.metrics.screening import (
    MANIFEST as METRIC_MANIFEST,
)
from sec_xbrl.metrics.screening import (
    ScreeningMetricReader,
    publish_screening_metrics,
)
from sec_xbrl.screening.common import digest_value, sha256_file, write_json
from sec_xbrl.screening.dataset import GENERIC_IDENTITY_SOURCE_KIND
from sec_xbrl.screening.dataset_v2 import (
    EXPLICIT_IDENTITY_CONFIG_VERSION as DATASET_CONFIG_VERSION,
)
from sec_xbrl.screening.dataset_v2 import (
    ScreeningDatasetV2Reader,
    publish_screening_dataset_v2,
)
from sec_xbrl.screening.metric_identity import (
    CONFIG_VERSION,
    GenericMetricIdentityReader,
    _quarter_spine,
    publish_generic_metric_identity,
)
from tests.screening.test_screening_metric_publication import _analysis_bundle
from tests.unit.test_source_bindings import (
    _build_ready_histories,
    _fixture,
    _quality_config,
)

FINANCIAL_AS_OF = "2026-10-10"
METADATA_OBSERVATION_CUTOFF = "2026-10-13T23:59:59Z"
COHORT = ({"ticker": "FIVE", "cik": "0000000123"},)


def _mixed_v2_fixture_at_financial_cutoff(tmp_path: Path) -> dict[str, object]:
    first = _fixture(
        tmp_path / "first",
        ticker="FIVE",
        cik="0000000123",
        accession="0000000123-26-000001",
        parser_version="m2-layer1-v5",
    )
    second = _fixture(
        tmp_path / "second",
        ticker="SIX",
        cik="0000000456",
        accession="0000000456-26-000002",
        parser_version="m2-layer1-v6",
    )
    plans: dict[str, Path] = {}
    for ticker, source in (("FIVE", first), ("SIX", second)):
        plan = json.loads(
            (
                Path(source["collection"]).parent
                / f"companies/{ticker}/plan.json"
            ).read_text(encoding="utf-8")
        )
        plan["as_of_date"] = FINANCIAL_AS_OF
        path = tmp_path / f"plans/{ticker}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, plan)
        plans[ticker] = path
    config = tmp_path / "mixed-config.json"
    write_json(
        config,
        {
            "schema_version": 1,
            "universe_id": "mixed-source-binding-fixture",
            "purpose": "financial and metadata cutoff separation fixture",
            "as_of_date": FINANCIAL_AS_OF,
            "source_observed_at": "2026-10-13T00:00:00+00:00",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [
                {"ticker": "FIVE", "cik": "0000000123", "groups": ["fixture"]},
                {"ticker": "SIX", "cik": "0000000456", "groups": ["fixture"]},
            ],
        },
    )
    collection = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "mixed-run",
        existing_plans=plans,
    )
    paths = {
        "collection": collection,
        "packages": tmp_path / "mixed-packages",
        "first": first,
        "second": second,
    }
    _install_intake(paths, "FIVE")
    for source in (first, second):
        package = Path(source["package"])
        destination = Path(paths["packages"]) / package.relative_to(
            Path(source["packages"])
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, destination)
    return paths


def _install_intake(paths: dict[str, object], ticker: str) -> None:
    source = paths["first" if ticker == "FIVE" else "second"]
    assert isinstance(source, dict)
    collection = Path(paths["collection"])
    plan = json.loads(
        (collection.parent / f"companies/{ticker}/plan.json").read_text(
            encoding="utf-8"
        )
    )
    intake = json.loads(Path(source["intake"]).read_text(encoding="utf-8"))
    intake["plan"] = plan
    intake_path = collection.parent / f"companies/{ticker}/intake/history_intake.json"
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        intake_path,
        intake,
    )


def _metadata(tmp_path: Path) -> Path:
    source = tmp_path / "metadata-source/0000000123/root.json"
    source.parent.mkdir(parents=True)
    write_json(
        source,
        {
            "cik": "123",
            "name": "Five Corp",
            "sic": "3571",
            "sicDescription": "Electronic Computers",
            "tickers": ["FIVE"],
            "exchanges": ["Nasdaq"],
            "formerNames": [],
            "filings": {"recent": {"form": ["10-K", "10-Q"]}},
        },
    )
    built = build_company_metadata(
        [SnapshotInput(source, datetime(2026, 10, 13, 1, 2, 3, tzinfo=UTC))]
    )
    return publish_company_metadata(built, tmp_path / "metadata").root


def _quarterly_analysis(
    tmp_path: Path, *, history_root: Path, years: tuple[int, ...]
) -> Path:
    root = _analysis_bundle(
        tmp_path / "quarterly-analysis",
        years,
        ticker="FIVE",
        cik="0000000123",
        financial_as_of=FINANCIAL_AS_OF,
        history_root=history_root,
    )
    manifest_path = root / "analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    columns_path = root / "FIVE/LATEST_REPORTED/columns.parquet"
    columns = tuple(
        {
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "period_class": "QTD_3M",
        }
        for year, quarter in (
            (2024, 4),
            (2025, 1),
            (2025, 2),
            (2025, 3),
            (2025, 4),
            (2026, 1),
            (2026, 2),
            (2026, 3),
        )
    )
    column_info = _write_records(columns_path, columns)
    manifest["publication_id"] = "quarterly-analysis-five-v1"
    manifest["period_mode"] = "QUARTERLY"
    manifest.pop("balance_scope")
    manifest["quarter_source_evidence"] = {
        "included": True,
        "rule_version": "quarter-typed-primary-pre-evidence-v1",
    }
    manifest["companies"]["FIVE"]["views"]["LATEST_REPORTED"]["files"][
        "columns"
    ] = {"path": "FIVE/LATEST_REPORTED/columns.parquet", **column_info}
    write_json(manifest_path, manifest)
    return root


def _publish_identity_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    paths = _mixed_v2_fixture_at_financial_cutoff(tmp_path)
    histories = _build_ready_histories(
        paths, tmp_path, monkeypatch, selected_tickers=("FIVE",)
    )
    quality_config = _quality_config(
        paths,
        histories,
        tmp_path / "quality-config.json",
        companies=COHORT,
    )
    quality_payload = json.loads(quality_config.read_text(encoding="utf-8"))
    quality_payload["financial_as_of"] = FINANCIAL_AS_OF
    write_json(quality_config, quality_payload)
    quality = prepare_generic_metric_quality(
        config_path=quality_config,
        collection_manifest=Path(paths["collection"]),
        package_root=Path(paths["packages"]),
        history_manifests=histories,
        source_index_destination=tmp_path / "quality-indexes",
        source_binding_destination=tmp_path / "quality-bindings",
        destination=tmp_path / "quality",
        producer_revision="e" * 40,
    )
    history_root = histories["FIVE"].parent
    years = (2021, 2022, 2023, 2024, 2025)
    annual = _analysis_bundle(
        tmp_path / "annual-analysis",
        years,
        ticker="FIVE",
        cik="0000000123",
        financial_as_of=FINANCIAL_AS_OF,
        history_root=history_root,
    )
    quarterly = _quarterly_analysis(
        tmp_path, history_root=history_root, years=years
    )
    metadata = _metadata(tmp_path)
    collection = Path(paths["collection"])
    identity_config = tmp_path / "identity-config.json"
    write_json(
        identity_config,
        {
            "schema_version": CONFIG_VERSION,
            "source_kind": GENERIC_IDENTITY_SOURCE_KIND,
            "universe_id": "mixed-source-binding-fixture",
            "financial_as_of": FINANCIAL_AS_OF,
            "metadata_observation_cutoff": METADATA_OBSERVATION_CUTOFF,
            "annual_window": {
                "input_fiscal_years": 5,
                "display_fiscal_years": 4,
            },
            "global_quarter_spine": _quarter_spine(FINANCIAL_AS_OF),
            "collection_scope_mode": "EXPLICIT_SUBSET",
            "collection_scope_companies": list(COHORT),
            "collection_manifest": str(collection),
            "collection_manifest_sha256": sha256_file(collection),
            "metadata_root": str(metadata),
            "metadata_manifest_sha256": sha256_file(
                metadata / METADATA_MANIFEST
            ),
            "quality_root": str(quality.root),
            "quality_manifest_sha256": sha256_file(quality.manifest_path),
            "companies": [
                {
                    **COHORT[0],
                    "input_years": list(years),
                    "display_years": list(years[-4:]),
                    "history_root": str(history_root),
                    "history_manifest_sha256": sha256_file(histories["FIVE"]),
                    "annual_analysis_root": str(annual),
                    "annual_analysis_manifest_sha256": sha256_file(
                        annual / "analysis_manifest.json"
                    ),
                    "quarterly_analysis_root": str(quarterly),
                    "quarterly_analysis_manifest_sha256": sha256_file(
                        quarterly / "analysis_manifest.json"
                    ),
                }
            ],
        },
    )
    identity = publish_generic_metric_identity(
        identity_config, tmp_path / "identity"
    )
    return SimpleNamespace(
        paths=paths,
        histories=histories,
        quality=quality,
        annual=annual,
        quarterly=quarterly,
        metadata=metadata,
        identity_config=identity_config,
        identity=identity,
    )


def test_quality_identity_annual31_dataset_v2_chain_and_subset_stability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    identity = GenericMetricIdentityReader(
        prepared.identity.root,
        manifest_sha256=sha256_file(prepared.identity.manifest_path),
    )
    assert identity.manifest["collection"]["scope_mode"] == "EXPLICIT_SUBSET"
    assert identity.manifest["collection"]["parent_requested_companies"] == 2
    assert identity.manifest["collection"]["scope_ready_companies"] == 1
    assert identity.manifest["financial_as_of"] == "2026-10-10"
    assert identity.manifest["metadata_observation_cutoff"] == (
        METADATA_OBSERVATION_CUTOFF
    )
    assert identity.manifest["metadata"]["scope_observations"] == [
        {
            "ticker": "FIVE",
            "cik": "0000000123",
            "observed_at": "2026-10-13T01:02:03Z",
        }
    ]
    assert identity.manifest["metadata"]["historical_membership_assurance"] is False
    assert identity.manifest["quality"]["assurance_scope"] == (
        "RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY"
    )
    assert identity.manifest["quality"]["full_financial_semantic_assurance"] is False
    assert identity.manifest["quality"]["collector_provenance_assurance"] == (
        "CONFIG_DECLARED_NOT_SOURCE_VERIFIED"
    )
    status = operations.read_universe_status(
        manifest_path=Path(prepared.paths["collection"])
    )
    assert {row.ticker: row.state for row in status.companies} == {
        "FIVE": "READY",
        "SIX": "PREPARED",
    }

    metric_config = tmp_path / "metric-config.json"
    write_json(
        metric_config,
        {
            "schema_version": "screening-metric-config-v2",
            "financial_as_of": FINANCIAL_AS_OF,
            "identity_source": {
                "kind": GENERIC_IDENTITY_SOURCE_KIND,
                "root": str(prepared.identity.root),
                "manifest_sha256": sha256_file(prepared.identity.manifest_path),
            },
            "companies": [
                {
                    **COHORT[0],
                    "analysis_root": str(prepared.annual),
                    "analysis_manifest_sha256": sha256_file(
                        prepared.annual / "analysis_manifest.json"
                    ),
                    "input_years": [2021, 2022, 2023, 2024, 2025],
                    "display_years": [2022, 2023, 2024, 2025],
                }
            ],
        },
    )
    metrics = publish_screening_metrics(metric_config, tmp_path / "metrics")
    metric_reader = ScreeningMetricReader(metrics.root)
    assert metric_reader.verify_governed_sources()["status"] == "PASS"
    assert len(metric_reader.definitions) == 31
    assert len(metric_reader.observations) == 124

    dataset_config = tmp_path / "dataset-config.json"
    write_json(
        dataset_config,
        {
            "schema_version": DATASET_CONFIG_VERSION,
            "dataset_id": "generic-first-five-fixture",
            "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
            "financial_as_of": FINANCIAL_AS_OF,
            "metric_root": str(metrics.root),
            "metric_manifest_sha256": sha256_file(metrics.root / METRIC_MANIFEST),
            "identity_source": {
                "kind": GENERIC_IDENTITY_SOURCE_KIND,
                "root": str(prepared.identity.root),
                "manifest_sha256": sha256_file(prepared.identity.manifest_path),
            },
        },
    )
    dataset = publish_screening_dataset_v2(dataset_config, tmp_path / "dataset-v2")
    dataset_status = ScreeningDatasetV2Reader(dataset.root).verify_all()
    assert dataset_status["company_count"] == 1
    assert dataset_status["definition_count"] == 31
    assert dataset_status["observation_count"] == 124

    _install_intake(prepared.paths, "SIX")
    _build_ready_histories(
        prepared.paths, tmp_path, monkeypatch, selected_tickers=("SIX",)
    )
    assert GenericMetricIdentityReader(prepared.identity.root).publication_id == (
        identity.publication_id
    )
    assert ScreeningDatasetV2Reader(dataset.root).publication_id == dataset.publication_id


@pytest.mark.parametrize(
    "defect",
    (
        "foreign_cik",
        "stale_cutoff",
        "metadata_after_cutoff",
        "future_filing",
        "quality_proof",
        "analysis_parent",
        "top_scope",
    ),
)
def test_identity_rejects_wrong_scope_and_parent_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    prepared = _publish_identity_inputs(tmp_path, monkeypatch)
    if defect in {"foreign_cik", "stale_cutoff", "metadata_after_cutoff"}:
        config = json.loads(prepared.identity_config.read_text(encoding="utf-8"))
        if defect == "foreign_cik":
            config["companies"][0]["cik"] = "0000000999"
            config["collection_scope_companies"][0]["cik"] = "0000000999"
        elif defect == "stale_cutoff":
            config["financial_as_of"] = "2026-10-09"
            config["global_quarter_spine"] = _quarter_spine("2026-10-09")
        else:
            config["metadata_observation_cutoff"] = "2026-10-13T00:00:00Z"
        changed = tmp_path / f"{defect}-config.json"
        write_json(changed, config)
        with pytest.raises(ValueError):
            publish_generic_metric_identity(changed, tmp_path / f"rejected-{defect}")
        assert not (tmp_path / f"rejected-{defect}").exists()
        return

    if defect == "future_filing":
        plan = (
            Path(prepared.paths["collection"]).parent
            / "companies/FIVE/plan.json"
        )
        payload = json.loads(plan.read_text(encoding="utf-8"))
        payload["companies"][0]["filings"][0]["filed_date"] = "2027-01-01"
        write_json(plan, payload)
    elif defect == "quality_proof":
        report = prepared.quality.report_path
        payload = json.loads(report.read_text(encoding="utf-8"))
        payload["full_financial_semantic_assurance"] = True
        write_json(report, payload)
    elif defect == "analysis_parent":
        manifest = prepared.annual / "analysis_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["source_manifest_hashes"]["history_manifest_sha256"] = "0" * 64
        write_json(manifest, payload)
    else:
        manifest = prepared.identity.manifest_path
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["metadata_observation_cutoff"] = "2026-10-14T00:00:00Z"
        identity = {key: value for key, value in payload.items() if key != "publication_id"}
        payload["publication_id"] = (
            "generic-metric-identity-" + digest_value(identity)[:24]
        )
        write_json(manifest, payload)

    with pytest.raises(ValueError):
        GenericMetricIdentityReader(prepared.identity.root)
