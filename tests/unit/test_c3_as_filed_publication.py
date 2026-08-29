from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.analytics.repository import AnalyticalRepository
from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    AsFiledPublicationPipeline,
    CorpusRelease,
    CorpusReleaseAdapter,
    CorpusSnapshot,
    Layer1SnapshotInput,
    Layer2RuleVersions,
    Layer2Run,
)

RULES = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")


def _release() -> CorpusRelease:
    cik = "0000320193"
    snapshots = tuple(_snapshot(cik, accession, filed, value) for accession, filed, value in (
        ("0000320193-25-000001", "2025-05-01", "100"),
        ("0000320193-25-000002", "2025-06-01", "200"),
    ))
    run = Layer2Run("c3-m1-fixture-v1", "fixture-corpus", tuple(item.input for item in snapshots), RULES)
    return CorpusRelease(Path("/fixture"), "fixture-corpus", (cik,), snapshots, run)


def _snapshot(cik: str, accession: str, filed_date: str, value: str) -> CorpusSnapshot:
    filing_id = f"filing:{accession}"
    suffix = accession[-6:]
    fact_id = f"fact:{suffix}"
    revenue = f"revenue:{suffix}"
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik, "accession": accession, "form": "10-Q", "filed_date": filed_date, "report_date": "2025-03-29", "document_fiscal_year_focus": "2025"},),
        "concept": (
            {"filing_id": filing_id, "raw_concept_id": revenue, "qname": "us-gaap:Revenue", "namespace_uri": "http://fasb.org/us-gaap", "local_name": "Revenue", "period_type": "duration", "data_type": "monetaryItemType", "is_standard": True},
        ),
        "context": ({"filing_id": filing_id, "context_id": "qtd", "period_kind": "DURATION", "start_date": "2024-12-29", "end_date": "2025-03-29", "instant_date": None, "duration_days": 91},),
        "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
        "fact": ({"filing_id": filing_id, "fact_id": fact_id, "raw_concept_id": revenue, "context_id": "qtd", "unit_id": "usd", "value_numeric": value, "value_text": None, "is_nil": False, "source_document": "report.htm", "source_locator": "table:1"},),
        "dimension_fact": (),
        "role": ({"filing_id": filing_id, "role_id": "role:revenue"},),
        "relationship": ({"filing_id": filing_id, "relationship_id": f"rel:{suffix}", "role_id": "role:revenue", "from_raw_concept_id": revenue, "to_raw_concept_id": revenue, "network_type": "PRE"},),
    }
    manifest = Layer1SnapshotManifest(
        1, cik, accession, "10-Q", "fixture", "a" * 64, "fixture", 1, 1, 1, 1, 1, 0, 1, 1, "fixture", "fixture"
    )
    input = Layer1SnapshotInput(cik, accession, "10-Q", filed_date, "2025-03-29", f"snap:{suffix}", hashlib.sha256(accession.encode()).hexdigest())
    return CorpusSnapshot(input, manifest, Path(f"/fixture/{suffix}/layer1_manifest.json"), MappingProxyType({}), MappingProxyType({name: len(rows) for name, rows in tables.items()}), MappingProxyType({name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()}))


def test_c3_m1_publishes_only_as_filed_and_is_admitted_by_consumer_c2(tmp_path: Path) -> None:
    result = AsFiledPublicationPipeline().publish(
        _release(), output_root=tmp_path / "layer2", as_of_date="2025-12-31"
    )
    repository = AnalyticalRepository.from_layer2_publications((result.publication.run_root,))
    facts = repository.get_analytical_facts("0000320193", view="AS_FILED")
    assert len(facts) == 1
    assert facts[0]["value_numeric"] == "100"
    assert facts[0]["selected_fact_id"] == "fact:000001"
    assert facts[0]["view"] == "AS_FILED"
    assert result.publication.output_counts["period_observation"] == 2
    assert result.coverage[0].filing_count == 2
    assert result.coverage[0].views == ("AS_FILED",)
    assert repository.discover_capabilities("0000320193")[0]["source_role_ids"] == ["role:revenue"]


def test_c3_m1_actual_seven_company_corpus_when_cached(tmp_path: Path) -> None:
    root = Path(os.environ.get("SEC_XBRL_CORPUS_ROOT", "data/processed/trailing_corpus_runs/20260827T051322Z"))
    if not root.is_dir():
        pytest.skip("cached seven-company corpus is not available")
    ciks = ("320193", "1045810", "1318605", "2488", "1652044", "1326801", "1065280")
    release = CorpusReleaseAdapter().load(root, corpus_run_id=root.name, ciks=ciks, run_version="c3-m1-golden-v1", rules=RULES)
    result = AsFiledPublicationPipeline().publish(release, output_root=tmp_path / "golden", as_of_date="2026-08-29")
    repository = AnalyticalRepository.from_layer2_publications((result.publication.run_root,))
    assert len(release.snapshots) == 102
    assert {row["cik"] for row in (repository.resolve_company(cik) for cik in ciks)} == set(release.ciks)
    assert {row["view"] for cik in ciks for row in repository.get_analytical_facts(cik, view="AS_FILED")} <= {"AS_FILED"}
    assert all(row.has_observed_or_explicit_coverage for row in result.coverage)
