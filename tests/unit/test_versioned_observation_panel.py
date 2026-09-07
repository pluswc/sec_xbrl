from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    CorpusRelease,
    CorpusReleaseAdapter,
    CorpusSnapshot,
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
    VersionedObservationPanelPipeline,
    VersionedObservationPanelReader,
)


def _release() -> CorpusRelease:
    cik = "0000320193"
    snapshots = tuple(
        _snapshot(cik, accession, form, filed_date, value)
        for accession, form, filed_date, value in (
            ("0000320193-25-000001", "10-Q", "2025-05-01", "100"),
            ("0000320193-25-000002", "10-Q/A", "2025-06-01", "120"),
        )
    )
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    return CorpusRelease(
        Path("/fixture"), "fixture", (cik,), snapshots,
        Layer2Run("t1-versioned-fixture-v1", "fixture", tuple(row.input for row in snapshots), rules),
    )


def _snapshot(cik: str, accession: str, form: str, filed_date: str, value: str) -> CorpusSnapshot:
    filing_id, suffix = f"filing:{accession}", accession[-6:]
    revenue, fact = f"revenue:{suffix}", f"fact:{suffix}"
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik, "accession": accession, "form": form, "filed_date": filed_date, "report_date": "2025-03-29", "document_fiscal_year_focus": "2025", "document_fiscal_period_focus": "Q1", "is_amendment": form.endswith("/A")},),
        "concept": ({"filing_id": filing_id, "raw_concept_id": revenue, "qname": "us-gaap:Revenue", "namespace_uri": "http://fasb.org/us-gaap/2024", "local_name": "Revenue", "period_type": "duration", "data_type": "monetaryItemType", "is_standard": True},),
        "context": ({"filing_id": filing_id, "context_id": "qtd", "period_kind": "DURATION", "start_date": "2024-12-29", "end_date": "2025-03-29", "instant_date": None, "duration_days": 91},),
        "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
        "fact": ({"filing_id": filing_id, "fact_id": fact, "raw_concept_id": revenue, "context_id": "qtd", "unit_id": "usd", "value_numeric": value, "value_text": None, "is_nil": False, "source_document": "report.htm", "source_locator": "table:1"},),
        "dimension_fact": (), "role": (), "relationship": (),
    }
    manifest = Layer1SnapshotManifest(1, cik, accession, form, "fixture", "a" * 64, "fixture", 1, 1, 1, 1, 1, 0, 0, 0, "fixture", "fixture")
    input_row = Layer1SnapshotInput(cik, accession, form, filed_date, "2025-03-29", f"snap:{suffix}", hashlib.sha256(accession.encode()).hexdigest())
    frozen = MappingProxyType({name: tuple(MappingProxyType(dict(row)) for row in rows) for name, rows in tables.items()})
    return CorpusSnapshot(input_row, manifest, Path(f"/fixture/{suffix}/layer1_manifest.json"), MappingProxyType({}), MappingProxyType({name: len(rows) for name, rows in tables.items()}), frozen)


def test_t1_preserves_original_and_amendment_for_one_fiscal_period(tmp_path: Path) -> None:
    result = VersionedObservationPanelPipeline().publish(_release(), output_root=tmp_path / "layer2")
    publication = Layer2PublicationReader().load(result.publication.run_root)
    rows = VersionedObservationPanelReader().get_period(
        publication, cik="0000320193", fiscal_year=2025, fiscal_quarter=1, period_class="QTD_3M"
    )
    assert result.reported_observation_count == 2
    assert [row["value_numeric"] for row in rows] == ["100", "120"]
    assert [row["source_version"] for row in rows] == ["ORIGINAL", "AMENDMENT"]
    assert [row["source_is_amendment"] for row in rows] == [False, True]
    assert [row["form"] for row in rows] == ["10-Q", "10-Q/A"]
    assert all(row["source_fact_id"] and row["context_id"] == "qtd" and row["unit_id"] == "usd" for row in rows)
    assert all(row["company_canonical_concept_id"] for row in rows)
    assert set(result.publication.output_counts) == {
        "company_axis_map", "company_concept_map", "company_member_map", "reported_period_observation"
    }


def test_cached_nvda_fy2024_q3_revenue_is_directly_retrievable(tmp_path: Path) -> None:
    root = Path(os.environ.get(
        "SEC_XBRL_CORPUS_ROOT",
        "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/trailing_corpus_runs/20260827T051322Z",
    ))
    if not root.is_dir():
        pytest.skip("cached NVDA corpus is not available")
    rules = Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1")
    release = CorpusReleaseAdapter().load(
        root, corpus_run_id=root.name, ciks=("1045810",),
        run_version="t1-nvda-regression-v1", rules=rules,
    )
    result = VersionedObservationPanelPipeline().publish(release, output_root=tmp_path / "nvda")
    publication = Layer2PublicationReader().load(result.publication.run_root)
    rows = VersionedObservationPanelReader().get_period(
        publication, cik="0001045810", fiscal_year=2024, fiscal_quarter=3, period_class="QTD_3M"
    )
    assert any(
        row["raw_concept_qname"] == "us-gaap:Revenues"
        and row["value_numeric"] == "18120000000"
        and row["accession"] == "0001045810-23-000227"
        and row["context_id"] and row["unit_id"]
        for row in rows
    )
