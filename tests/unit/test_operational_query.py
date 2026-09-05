from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

# The existing T1 fixture is intentionally reused: this test's setup is a
# publication step, while every assertion below is against consumption only.
from test_versioned_observation_panel import _release

from sec_xbrl.analytics import (
    OperationalAnalyticsQueryError,
    OperationalAnalyticsQueryService,
    OperationalPublicationRoots,
    OperationalQueryScope,
)
from sec_xbrl.longitudinal import (
    AccessionVersionLedgerPipeline,
    ExplorationGraphPipeline,
    Layer2PublicationReader,
    Layer2Publisher,
    OperationalLayer2Publisher,
    VersionedObservationPanelPipeline,
)


def _roots(tmp_path: Path, *, run_version: str | None = None) -> OperationalPublicationRoots:
    release = _release()
    if run_version is not None:
        release = replace(release, layer2_run=replace(release.layer2_run, run_version=run_version))
    observations = VersionedObservationPanelPipeline().publish(
        release, output_root=tmp_path / "t1"
    ).publication
    relationships = OperationalLayer2Publisher(tmp_path / "t2").publish(
        release.layer2_run, {"filing_relationship_edge": ()}
    )
    reader = Layer2PublicationReader()
    graph = ExplorationGraphPipeline().publish(
        reader.load(observations.run_root), reader.load(relationships.run_root), output_root=tmp_path / "t3"
    ).publication
    ledger = AccessionVersionLedgerPipeline().publish(
        release, output_root=tmp_path / "t4"
    ).publication
    return OperationalPublicationRoots(
        observations.run_root, relationships.run_root, graph.run_root, ledger.run_root
    )


def _scope() -> OperationalQueryScope:
    return OperationalQueryScope(
        cik="0000320193", fiscal_year=2025, fiscal_quarter=1,
        period_class="QTD_3M", view="LATEST_REPORTED", as_of_date="2025-06-01",
    )


def test_operational_query_reads_published_roots_without_republishing_and_caches(tmp_path, monkeypatch) -> None:
    roots = _roots(tmp_path)
    service = OperationalAnalyticsQueryService(roots)

    def no_publish(*args, **kwargs):
        raise AssertionError("operational consumer must not publish or rebuild")

    monkeypatch.setattr(OperationalLayer2Publisher, "publish", no_publish)
    first = service.company_panel(_scope())
    second = service.company_panel(_scope())
    assert [row["value_numeric"] for row in first.values] == ["120"]
    assert [row["value_numeric"] for row in second.values] == ["120"]
    assert service.cache_info()["hits"] >= 1
    assert service.cache_info()["panels"] == 1

    # Public results never expose the cache's mutable data.
    first.values[0]["value_numeric"] = "corrupt"
    assert service.company_panel(_scope()).values[0]["value_numeric"] == "120"


def test_operational_query_composes_t6_and_t7_from_the_same_published_roots(tmp_path, monkeypatch) -> None:
    roots = _roots(tmp_path)
    service = OperationalAnalyticsQueryService(roots)
    monkeypatch.setattr(
        OperationalLayer2Publisher, "publish",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not publish")),
    )
    pivot = service.company_pivot((_scope(),))
    metrics = service.quarterly_metrics((_scope(),))
    assert len(pivot.cells) == 1
    assert pivot.cells[0]["value_numeric"] == "120"
    assert metrics.scope["quarterly_derived_metrics_version"]
    assert service.cache_info()["pivots"] == 1


def test_operational_query_rejects_roots_with_different_immutable_input_runs(tmp_path) -> None:
    roots = _roots(tmp_path / "left")
    other = _roots(tmp_path / "right", run_version="different-immutable-run")
    mismatched = OperationalPublicationRoots(
        roots.reported_observations, roots.relationships, roots.exploration_graph, other.accession_ledger
    )
    with pytest.raises(OperationalAnalyticsQueryError, match="identical immutable"):
        OperationalAnalyticsQueryService(mismatched)


def test_operational_query_rejects_a_valid_canonical_jsonl_publication(tmp_path) -> None:
    roots = _roots(tmp_path)
    release = _release()
    verified = Layer2PublicationReader().load(roots.reported_observations)
    jsonl = Layer2Publisher(tmp_path / "jsonl").publish(
        release.layer2_run,
        {name: verified.records(name) for name in verified.datasets},
    )
    mismatched = OperationalPublicationRoots(
        jsonl.run_root, roots.relationships, roots.exploration_graph, roots.accession_ledger
    )
    with pytest.raises(OperationalAnalyticsQueryError, match="parquet-operational-v1"):
        OperationalAnalyticsQueryService(mismatched)
