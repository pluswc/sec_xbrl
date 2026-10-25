from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from sec_xbrl.longitudinal import (
    ExplorationGraphReader,
    Layer1SnapshotInput,
    Layer2MaterializationError,
    Layer2PublicationReader,
    Layer2PublicationValidationError,
    Layer2Publisher,
    Layer2RuleVersions,
    Layer2Run,
    OperationalLayer2Publisher,
)

CIK = "0000320193"
OTHER_CIK = "0001045810"
FILING_ONE = "filing:one"
FILING_TWO = "filing:two"


def _run(version: str = "t3-reference-integrity-v2") -> Layer2Run:
    return Layer2Run(
        version,
        "t3-reference-fixture",
        (
            Layer1SnapshotInput(
                CIK,
                "0000320193-25-000001",
                "10-Q",
                "2025-05-01",
                "2025-03-29",
                "snapshot:one",
                "a" * 64,
            ),
            Layer1SnapshotInput(
                CIK,
                "0000320193-25-000002",
                "10-Q",
                "2025-08-01",
                "2025-06-28",
                "snapshot:two",
                "b" * 64,
            ),
            Layer1SnapshotInput(
                OTHER_CIK,
                "0001045810-25-000001",
                "10-Q",
                "2025-05-02",
                "2025-03-30",
                "snapshot:other",
                "c" * 64,
            ),
        ),
        Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"),
    )


def _node(
    node_id: str,
    *,
    cik: str = CIK,
    filing: str | None = None,
    kind: str = "CONCEPT",
) -> dict[str, object]:
    origin = "STANDARD_AXIS" if kind == "AXIS" else "STANDARD_CONCEPT"
    row: dict[str, object] = {
        "cik": cik,
        "analysis_exploration_node_id": node_id,
        "node_kind": kind,
        "origin": origin,
        "raw_id": f"raw:{node_id}",
        "raw_qname": f"fixture:{node_id}",
        # A structurally valid legacy v1 graph remains readable. The repair
        # rejects broken references rather than banning all historical rows.
        "exploration_graph_rule_version": "analysis-t3-exploration-graph-v1",
    }
    if filing is not None:
        row["source_filing_id"] = filing
    return row


def _edge(
    edge_id: str,
    left: str,
    right: str,
    *,
    cik: str = CIK,
    filing: str | None = None,
    kind: str = "DIMENSION_LENS",
    **values: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "cik": cik,
        "analysis_exploration_edge_id": edge_id,
        "edge_kind": kind,
        "from_node_id": left,
        "to_node_id": right,
        "exploration_graph_rule_version": "analysis-t3-exploration-graph-v1",
        **values,
    }
    if filing is not None:
        row["source_filing_id"] = filing
    return row


def _graph(
    nodes: tuple[dict[str, object], ...],
    edges: tuple[dict[str, object], ...],
) -> dict[str, tuple[dict[str, object], ...]]:
    return {
        "analysis_exploration_node": nodes,
        "analysis_exploration_edge": edges,
    }


def test_valid_legacy_cycle_typed_scope_and_multiple_filings_remain_supported(
    tmp_path: Path,
) -> None:
    datasets = _graph(
        (
            _node("node:a", filing=FILING_ONE),
            _node("node:b", filing=FILING_ONE),
            _node("node:axis", filing=FILING_TWO, kind="AXIS"),
            _node("node:typed", filing=FILING_TWO),
        ),
        (
            _edge("edge:a-b", "node:a", "node:b", filing=FILING_ONE),
            _edge("edge:b-a", "node:b", "node:a", filing=FILING_ONE),
            _edge(
                "edge:typed",
                "node:axis",
                "node:typed",
                filing=FILING_TWO,
                kind="FACT_SCOPE",
                scope_kind="TYPED_AXIS_SCOPED_FACT",
                dimension_type="TYPED",
                typed_member="<fixture:Region>North</fixture:Region>",
            ),
        ),
    )
    published = OperationalLayer2Publisher(tmp_path).publish(_run(), datasets)
    publication = Layer2PublicationReader().load(published.run_root)

    rows = ExplorationGraphReader().traverse(
        publication, root_node_ids=("node:a",)
    )
    assert [row["node"]["analysis_exploration_node_id"] for row in rows] == [
        "node:a",
        "node:b",
    ]
    assert len(publication.records("analysis_exploration_edge")) == 3


@pytest.mark.parametrize("publisher_type", [Layer2Publisher, OperationalLayer2Publisher])
def test_publishers_reject_dangling_endpoint_atomically(
    tmp_path: Path, publisher_type: type[Layer2Publisher | OperationalLayer2Publisher]
) -> None:
    run = _run()
    root = tmp_path / publisher_type.__name__
    with pytest.raises(Layer2MaterializationError, match="does not resolve in the same candidate"):
        publisher_type(root).publish(
            run,
            _graph(
                (_node("node:a", filing=FILING_ONE),),
                (_edge("edge:dangling", "node:a", "node:missing", filing=FILING_ONE),),
            ),
        )
    assert not (root / run.run_version).exists()


@pytest.mark.parametrize(
    "nodes, edge, message",
    [
        (
            (_node("node:a", filing=FILING_ONE), _node("node:b", cik=OTHER_CIK, filing=FILING_ONE)),
            _edge("edge:cross-cik", "node:a", "node:b", filing=FILING_ONE),
            "different CIK",
        ),
        (
            (_node("node:a", filing=FILING_ONE), _node("node:b", filing=FILING_TWO)),
            _edge("edge:cross-filing", "node:a", "node:b", filing=FILING_ONE),
            "filing disagrees",
        ),
    ],
)
def test_endpoint_scope_must_match_edge_scope(
    tmp_path: Path,
    nodes: tuple[dict[str, object], ...],
    edge: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(Layer2MaterializationError, match=message):
        OperationalLayer2Publisher(tmp_path).publish(
            _run(), _graph(nodes, (edge,))
        )


@pytest.mark.parametrize("storage", ["canonical", "operational"])
def test_reader_rejects_tampered_graph_references(
    tmp_path: Path, storage: str
) -> None:
    run = _run()
    datasets = _graph(
        (_node("node:a", filing=FILING_ONE), _node("node:b", filing=FILING_ONE)),
        (_edge("edge:a-b", "node:a", "node:b", filing=FILING_ONE),),
    )
    publisher = (
        Layer2Publisher(tmp_path / storage)
        if storage == "canonical"
        else OperationalLayer2Publisher(tmp_path / storage)
    )
    published = publisher.publish(run, datasets)
    edge_path = published.run_root / CIK / "analysis_exploration_edge"
    if storage == "canonical":
        edge_path = edge_path.with_suffix(".jsonl")
        row = json.loads(edge_path.read_text(encoding="utf-8"))
        row["to_node_id"] = "node:missing"
        edge_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    else:
        edge_path = edge_path.with_suffix(".parquet")
        rows = pl.read_parquet(edge_path).to_dicts()
        rows[0]["to_node_id"] = "node:missing"
        pl.DataFrame(rows, strict=False, infer_schema_length=None).write_parquet(edge_path)

    with pytest.raises(Layer2PublicationValidationError, match="rows fail contract validation"):
        Layer2PublicationReader().load(published.run_root)

    if storage == "operational":
        with pytest.raises(
            Layer2MaterializationError,
            match="existing operational exploration graph fails validation",
        ):
            publisher.publish(run, datasets)


def test_operational_graph_rule_upgrade_requires_new_output_and_run_version(
    tmp_path: Path,
) -> None:
    run = _run()
    datasets = _graph(
        (_node("node:a", filing=FILING_ONE), _node("node:b", filing=FILING_ONE)),
        (_edge("edge:a-b", "node:a", "node:b", filing=FILING_ONE),),
    )
    publisher = OperationalLayer2Publisher(tmp_path)
    publisher.publish(run, datasets)
    upgraded = {
        name: tuple(
            {**row, "exploration_graph_rule_version": "analysis-t3-exploration-graph-v2"}
            for row in rows
        )
        for name, rows in datasets.items()
    }

    with pytest.raises(
        Layer2MaterializationError,
        match="different exploration graph rule version",
    ):
        publisher.publish(run, upgraded)
