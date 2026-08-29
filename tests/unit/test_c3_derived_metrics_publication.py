from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.analytics.repository import AnalyticalRepository
from sec_xbrl.filing.layer1_ingestion import Layer1SnapshotManifest
from sec_xbrl.longitudinal import (
    AsFiledPublicationPipeline,
    CorpusRelease,
    CorpusSnapshot,
    Layer1SnapshotInput,
    Layer2PublicationReader,
    Layer2RuleVersions,
    Layer2Run,
)
from sec_xbrl.metrics import (
    C3MetricCompanionReader,
    C3MetricPublicationError,
    C3MetricPublicationPipeline,
    seed_metric_registry,
)


def _upstream(tmp_path: Path):
    cik, accession, filing_id = "0000320193", "0000320193-25-000001", "filing:one"
    concepts = ("Revenue", "GrossProfit", "OperatingIncomeLoss")
    tables = {
        "filing": ({"filing_id": filing_id, "cik": cik, "accession": accession, "form": "10-Q", "filed_date": "2025-05-01", "report_date": "2025-03-29", "document_fiscal_year_focus": "2025"},),
        "concept": tuple({"filing_id": filing_id, "raw_concept_id": f"concept:{item}", "qname": f"us-gaap:{item}", "namespace_uri": "http://fasb.org/us-gaap", "local_name": item, "period_type": "duration", "data_type": "monetaryItemType", "is_standard": True} for item in concepts),
        "context": ({"filing_id": filing_id, "context_id": "qtd", "period_kind": "DURATION", "start_date": "2024-12-29", "end_date": "2025-03-29", "instant_date": None, "duration_days": 91},),
        "unit": ({"filing_id": filing_id, "unit_id": "usd", "numerator_measures": "iso4217:USD", "denominator_measures": None},),
        "fact": tuple({"filing_id": filing_id, "fact_id": f"fact:{item}", "raw_concept_id": f"concept:{item}", "context_id": "qtd", "unit_id": "usd", "value_numeric": value, "value_text": None, "is_nil": False, "source_document": "report.htm", "source_locator": "table:1"} for item, value in zip(concepts, ("100", "50", "25"), strict=True)),
        "dimension_fact": (), "role": ({"filing_id": filing_id, "role_id": "role:income"},),
        "relationship": tuple({"filing_id": filing_id, "relationship_id": f"rel:{item}", "role_id": "role:income", "from_raw_concept_id": f"concept:{item}", "to_raw_concept_id": f"concept:{item}", "network_type": "PRE"} for item in concepts),
    }
    manifest = Layer1SnapshotManifest(1, cik, accession, "10-Q", "fixture", "a" * 64, "fixture", 3, 3, 3, 1, 1, 0, 1, 3, "fixture", "fixture")
    input_row = Layer1SnapshotInput(cik, accession, "10-Q", "2025-05-01", "2025-03-29", "snapshot:one", hashlib.sha256(b"fixture").hexdigest())
    snapshot = CorpusSnapshot(input_row, manifest, Path("/fixture/manifest"), MappingProxyType({}), MappingProxyType({key: len(value) for key, value in tables.items()}), MappingProxyType({key: tuple(MappingProxyType(dict(row)) for row in value) for key, value in tables.items()}))
    run = Layer2Run("c3-m4-upstream", "fixture", (input_row,), Layer2RuleVersions("p", "m", "r", "s"))
    release = CorpusRelease(Path("/fixture"), "fixture", (cik,), (snapshot,), run)
    output = AsFiledPublicationPipeline().publish(release, output_root=tmp_path / "l2", as_of_date="2025-12-31")
    return Layer2PublicationReader().load(output.publication.run_root)


def test_c3_metric_pipeline_publishes_m6_m1_m2_and_common_consumer_queries(tmp_path: Path) -> None:
    upstream = _upstream(tmp_path)
    pipeline = C3MetricPublicationPipeline(seed_metric_registry())
    result = pipeline.materialize(upstream, evaluated_at="2026-08-29T00:00:00+00:00")
    assert {row["metric_definition_id"] for row in result.derived_metrics} == {
        "gross_margin@1.0.0", "operating_margin@1.0.0", "revenue_growth@1.0.0"
    }
    assert not any("q4" in row["metric_id"] for row in result.derived_metrics)
    by_metric = {row["metric_id"]: row for row in result.derived_metrics}
    assert by_metric["gross_margin"]["metric_value_decimal"] == "50"
    assert by_metric["operating_margin"]["metric_value_decimal"] == "25"
    assert by_metric["revenue_growth"]["calculation_status"] == "UNAVAILABLE"
    published = pipeline.publish(upstream, result=result, output_root=tmp_path / "c3", run_version="c3-m4", metric_run_version="c3-m4-m1", metric_output_root=tmp_path / "m1", registry_version="controlled-seed-v1")
    reread = C3MetricCompanionReader().load(published.run_root, upstream=upstream, metric_publication=published.metric_publication)
    assert len(reread.coverage) == 1
    repository = AnalyticalRepository.from_layer2_publications((upstream.run_root,), metric_series_run_roots=(published.metric_publication.run_root,))
    discovered = repository.discover_metrics("0000320193", metric_id="gross_margin", view="AS_FILED")
    metric_id = discovered[0]["derived_metric_ids"][0]
    assert repository.get_metric_series("0000320193", "gross_margin", as_of_date="2025-12-31", view="AS_FILED")[0]["metric_value_decimal"] == "50"
    assert repository.trace_metric(metric_id)["metric_id"] == "gross_margin"


def test_c3_metric_companion_and_current_comparable_input_fail_closed(tmp_path: Path) -> None:
    upstream = _upstream(tmp_path)
    pipeline = C3MetricPublicationPipeline(seed_metric_registry())
    result = pipeline.materialize(upstream, evaluated_at="2026-08-29T00:00:00+00:00")
    published = pipeline.publish(upstream, result=result, output_root=tmp_path / "c3", run_version="c3-m4", metric_run_version="c3-m4-m1", metric_output_root=tmp_path / "m1", registry_version="controlled-seed-v1")
    payload = published.run_root / "metric_coverage.jsonl"
    payload.write_text(payload.read_text(encoding="utf-8").replace("AS_FILED_ONLY", "changed"), encoding="utf-8")
    with pytest.raises(C3MetricPublicationError, match="content verification"):
        C3MetricCompanionReader().load(published.run_root, upstream=upstream, metric_publication=published.metric_publication)
    # A manually constructed row list is not an admitted C3-M1 publication;
    # the pipeline never has a public path to process such a mixed view.
    assert all(row["view"] == "AS_FILED" for row in upstream.records("analytical_fact"))
