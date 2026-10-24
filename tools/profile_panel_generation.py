"""Bounded panel-generation fixture extraction and process profiling.

The extraction command reads only one declared Layer 2 publication and writes
one complete reachable component.  The run command never reads the source
publication; it exercises the frozen fixture through panel, fiscal spill,
Parquet staging, finalization, and reload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def _query_paths(root: Path) -> dict[str, Path]:
    run = root.name
    cik = "0001163165"
    return {
        "observations": root / "t1" / run / cik / "reported_period_observation.parquet",
        "nodes": root / "t3" / run / cik / "analysis_exploration_node.parquet",
        "edges": root / "t3" / run / cik / "analysis_exploration_edge.parquet",
        "ledger": root / "t4" / run / cik / "accession_version_ledger" / "ledger.parquet",
    }


def _reachable(
    root: str, outgoing: dict[str, list[dict[str, Any]]]
) -> tuple[set[str], set[str], int]:
    nodes = {root}
    edges: set[str] = set()
    queue = deque([(root, (root,))])
    paths = 0
    while queue:
        node, path = queue.popleft()
        paths += 1
        for edge in outgoing.get(node, ()):
            target = str(edge["to_node_id"])
            if target in path:
                continue
            nodes.add(target)
            edges.add(str(edge["analysis_exploration_edge_id"]))
            queue.append((target, path + (target,)))
    return nodes, edges, paths


def extract_fixture(source_root: Path, output: Path) -> dict[str, Any]:
    import polars as pl

    from sec_xbrl.analytics.company_analysis_panel import _root_selections
    from sec_xbrl.longitudinal import ReportedObservationSelector

    paths = _query_paths(source_root)
    query = {
        "cik": "0001163165",
        "fiscal_year": 2025,
        "fiscal_quarter": 4,
        "period_class": "FY",
        "view": "LATEST_REPORTED",
        "as_of_date": "2026-10-10",
    }
    observations = (
        pl.scan_parquet(paths["observations"])
        .filter(
            (pl.col("comparative_type") == "CURRENT_FOCUS")
            & (pl.col("fiscal_year") == query["fiscal_year"])
            & (pl.col("fiscal_quarter") == query["fiscal_quarter"])
            & (pl.col("period_class") == query["period_class"])
        )
        .collect(engine="streaming")
        .to_dicts()
    )
    ledger = pl.read_parquet(paths["ledger"]).to_dicts()
    selected = [
        dict(row)
        for row in ReportedObservationSelector()
        .select_period(observations=observations, ledger=ledger, **query)
        .rows
        if row["selection_status"] == "SELECTED"
    ]
    node_index = (
        pl.scan_parquet(paths["nodes"])
        .select(
            "analysis_exploration_node_id",
            "node_kind",
            "source_filing_id",
            "source_fact_id",
        )
        .collect(engine="streaming")
    )
    fact_nodes = {
        (str(row["source_filing_id"]), str(row["source_fact_id"])): str(
            row["analysis_exploration_node_id"]
        )
        for row in node_index.iter_rows(named=True)
        if row["node_kind"] == "FACT" and row["source_fact_id"] is not None
    }
    edge_index = (
        pl.scan_parquet(paths["edges"])
        .select("analysis_exploration_edge_id", "from_node_id", "to_node_id")
        .collect(engine="streaming")
        .to_dicts()
    )
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edge_index:
        outgoing[str(edge["from_node_id"])].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda row: str(row["analysis_exploration_edge_id"]))
    candidates = []
    for row in _root_selections(selected):
        fact_key = (
            str(row.get("source_filing_id")),
            str(row.get("selected_source_fact_id")),
        )
        node_id = fact_nodes.get(fact_key)
        if node_id is not None:
            nodes, edges, paths_count = _reachable(node_id, outgoing)
            candidates.append((paths_count, node_id, nodes, edges))
    if not candidates:
        raise RuntimeError("query has no reachable selected root")
    paths_count, root_node_id, component_nodes, component_edges = max(candidates)
    selected_fact_keys = {
        (str(row["source_filing_id"]), str(row["selected_source_fact_id"]))
        for row in selected
        if fact_nodes.get(
            (str(row["source_filing_id"]), str(row["selected_source_fact_id"]))
        )
        in component_nodes
    }
    selected = [
        row
        for row in selected
        if (str(row["source_filing_id"]), str(row["selected_source_fact_id"]))
        in selected_fact_keys
    ]
    roots = _root_selections(selected)
    root_key = (
        str(roots[0].get("source_filing_id")) if roots else "",
        str(roots[0].get("selected_source_fact_id")) if roots else "",
    )
    if len(roots) != 1 or fact_nodes.get(root_key) != root_node_id:
        raise RuntimeError("chosen component is not one complete panel root scope")
    nodes = (
        pl.scan_parquet(paths["nodes"])
        .filter(pl.col("analysis_exploration_node_id").is_in(sorted(component_nodes)))
        .collect(engine="streaming")
        .to_dicts()
    )
    edges = (
        pl.scan_parquet(paths["edges"])
        .filter(pl.col("analysis_exploration_edge_id").is_in(sorted(component_edges)))
        .collect(engine="streaming")
        .to_dicts()
    )
    fixture = {
        "schema_version": "panel-generation-component-fixture-v1",
        "source": {
            "root": str(source_root),
            "files": {
                name: {
                    "relative_path": str(path.relative_to(source_root)),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
                for name, path in paths.items()
            },
            "derivation": (
                "Projected CURRENT_FOCUS FY2025 query; selected the root with the most "
                "complete simple outbound paths; retained every reachable node/edge and "
                "every selected fact in that component. This is not a whole-company sample."
            ),
            "attestation_scope": (
                "Bounded internally attested derived component; not a verification of the "
                "complete source publication or company history."
            ),
        },
        "query": query,
        "root_node_id": root_node_id,
        "counts": {
            "query_observations": len(observations),
            "query_selected": len(selected),
            "component_nodes": len(nodes),
            "component_edges": len(edges),
            "simple_paths": paths_count,
        },
        "selected_rows": selected,
        "nodes": nodes,
        "edges": edges,
    }
    payload = _canonical(fixture) + b"\n"
    if len(payload) > 16 * 1024 * 1024:
        raise RuntimeError("complete component fixture exceeds 16 MiB")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return {
        "path": str(output),
        "sha256": _sha256(output),
        "bytes": len(payload),
        **fixture["counts"],
        "query": query,
        "root_node_id": root_node_id,
    }


class _Metrics:
    def __init__(self) -> None:
        self.seconds: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.counts: dict[str, int] = {}

    def timed(self, name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                self.seconds[name] += time.perf_counter() - started
                self.calls[name] += 1

        return wrapped

    def timed_generator(
        self, name: str, function: Callable[..., Iterator[Any]]
    ) -> Callable[..., Iterator[Any]]:
        def wrapped(*args: Any, **kwargs: Any) -> Iterator[Any]:
            lifetime_started = time.perf_counter()
            iterator = iter(function(*args, **kwargs))
            try:
                while True:
                    active_started = time.perf_counter()
                    try:
                        item = next(iterator)
                    except StopIteration:
                        self.seconds[name] += time.perf_counter() - active_started
                        break
                    except BaseException:
                        self.seconds[name] += time.perf_counter() - active_started
                        raise
                    self.seconds[name] += time.perf_counter() - active_started
                    yield item
            finally:
                close = getattr(iterator, "close", None)
                if close is not None:
                    active_started = time.perf_counter()
                    close()
                    self.seconds[name] += time.perf_counter() - active_started
                self.calls[name] += 1
                self.seconds[f"{name}_generator_lifetime"] += (
                    time.perf_counter() - lifetime_started
                )

        return wrapped


def _publication(fixture: dict[str, Any], root: Path):
    from sec_xbrl.longitudinal import Layer1SnapshotInput, Layer2RuleVersions, Layer2Run
    from sec_xbrl.longitudinal.materialization import _verified_publication

    query = fixture["query"]
    run = Layer2Run(
        "panel-profile",
        "panel-profile",
        (
            Layer1SnapshotInput(
                query["cik"],
                "0001163165-26-000009",
                "10-K",
                "2026-02-17",
                "2025-12-31",
                "panel-profile-snapshot",
                "a" * 64,
            ),
        ),
        Layer2RuleVersions("period", "mapping", "recast", "selection"),
    )
    root.mkdir(parents=True)
    manifest = root / "layer2_run_manifest.json"
    manifest.write_text("{}\n")
    return _verified_publication(
        root,
        manifest,
        run,
        {
            "analysis_exploration_node": fixture["nodes"],
            "analysis_exploration_edge": fixture["edges"],
        },
    )


def run_profile(fixture_path: Path, output: Path) -> dict[str, Any]:
    import polars as pl

    from sec_xbrl import history
    from sec_xbrl.analytics import (
        CompanyAnalysisPanelBuilder,
        FiscalTimeSeriesBuilder,
        FiscalTimeSeriesInput,
        history_quarters,
    )
    from sec_xbrl.analytics import company_analysis_panel as panel_module
    from sec_xbrl.analytics import fiscal_time_series as fiscal_module
    from sec_xbrl.longitudinal import exploration_graph as graph_module

    fixture = json.loads(fixture_path.read_text())
    metrics = _Metrics()
    with tempfile.TemporaryDirectory(prefix="panel-profile-") as directory:
        root = Path(directory)
        graph = _publication(fixture, root / "graph")

        original_plain = graph_module._plain_copy
        plain_depth = 0

        def plain_copy(value: Any) -> Any:
            nonlocal plain_depth
            outer = plain_depth == 0
            started = time.perf_counter() if outer else 0.0
            plain_depth += 1
            try:
                return original_plain(value)
            finally:
                plain_depth -= 1
                if outer:
                    metrics.seconds["traversal_plain_copy"] += time.perf_counter() - started
                    metrics.calls["traversal_plain_copy"] += 1

        original_traverse = graph_module.ExplorationGraphReader.traverse

        def traverse(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            result = original_traverse(*args, **kwargs)
            metrics.seconds["traversal_inclusive"] += time.perf_counter() - started
            metrics.calls["traversal_inclusive"] += 1
            metrics.counts["visited_paths"] = metrics.counts.get("visited_paths", 0) + len(result)
            metrics.counts["returned_paths"] = metrics.counts.get("returned_paths", 0) + len(result)
            metrics.counts["copied_paths"] = metrics.counts.get("copied_paths", 0) + len(result)
            return result

        originals = {
            "plain": graph_module._plain_copy,
            "traverse": graph_module.ExplorationGraphReader.traverse,
            "reported": panel_module._reported_line,
            "deepcopy": panel_module.deepcopy,
            "verify": fiscal_module._FiscalTimeSeriesSpill.verify_integrity,
            "cells": fiscal_module._FiscalTimeSeriesSpill.cells,
            "rows": fiscal_module._FiscalTimeSeriesSpill.rows,
            "resolve": fiscal_module._resolve_cell,
            "unpack": fiscal_module._spill_unpack,
            "dumps": history.json.dumps,
            "write": pl.DataFrame.write_parquet,
            "sink": pl.LazyFrame.sink_parquet,
            "hash": history._sha256_file,
        }
        if hasattr(graph_module, "_walk_paths"):
            originals["walk"] = graph_module._walk_paths
            originals["selected_paths"] = (
                graph_module.ExplorationGraphReader._iter_selected_fact_paths
            )

            def walk_paths(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
                for path in originals["walk"](*args, **kwargs):
                    metrics.counts["visited_paths"] = (
                        metrics.counts.get("visited_paths", 0) + 1
                    )
                    yield path

            def selected_paths(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
                for path in originals["selected_paths"](*args, **kwargs):
                    metrics.counts["returned_paths"] = (
                        metrics.counts.get("returned_paths", 0) + 1
                    )
                    metrics.counts["copied_paths"] = (
                        metrics.counts.get("copied_paths", 0) + 1
                    )
                    yield path

            graph_module._walk_paths = walk_paths
            graph_module.ExplorationGraphReader._iter_selected_fact_paths = selected_paths
        graph_module._plain_copy = plain_copy
        graph_module.ExplorationGraphReader.traverse = traverse
        panel_module._reported_line = metrics.timed("reported_line", originals["reported"])
        panel_module.deepcopy = metrics.timed("panel_deepcopy", originals["deepcopy"])
        fiscal_module._FiscalTimeSeriesSpill.verify_integrity = metrics.timed(
            "spill_verify_integrity", originals["verify"]
        )
        fiscal_module._FiscalTimeSeriesSpill.cells = metrics.timed_generator(
            "cell_reconstruction", originals["cells"]
        )
        fiscal_module._FiscalTimeSeriesSpill.rows = metrics.timed_generator(
            "row_reconstruction", originals["rows"]
        )
        fiscal_module._resolve_cell = metrics.timed("resolve_cell", originals["resolve"])
        fiscal_module._spill_unpack = metrics.timed("spill_unpack", originals["unpack"])
        history.json.dumps = metrics.timed("json_encoding", originals["dumps"])
        pl.DataFrame.write_parquet = metrics.timed("native_parquet_write", originals["write"])
        pl.LazyFrame.sink_parquet = metrics.timed("native_parquet_finalize", originals["sink"])
        history._sha256_file = metrics.timed("final_file_hash", originals["hash"])
        result = None
        staged = []
        total_started = time.perf_counter()
        try:
            started = time.perf_counter()
            panel = CompanyAnalysisPanelBuilder().build(
                selected_rows=fixture["selected_rows"], exploration=graph, **fixture["query"]
            )
            metrics.seconds["panel_build"] = time.perf_counter() - started
            metrics.counts["selected_rows"] = len(fixture["selected_rows"])
            metrics.counts["panel_definitions"] = len(panel.definitions)
            metrics.counts["panel_bindings"] = len(panel.bindings)
            metrics.counts["panel_values"] = len(panel.values)

            started = time.perf_counter()
            result = FiscalTimeSeriesBuilder().build_spilled(
                inputs=(FiscalTimeSeriesInput(panel, None),), spill_root=root / "spill"
            )
            metrics.seconds["fiscal_build_spilled"] = time.perf_counter() - started

            reloaded: dict[str, Any] = {}
            spool_bytes: dict[str, int] = {}
            for name in ("columns", "rows", "cells"):
                path = root / "staged" / f"{name}.parquet"
                records = result.dataset(name)
                if name == "columns":
                    records = tuple(records)
                started = time.perf_counter()
                plan = history._stage_records(path, records)
                metrics.seconds[f"stage_{name}"] = time.perf_counter() - started
                staged.append(plan)
                spool_bytes[name] = getattr(plan, "spool_bytes", 0)
                started = time.perf_counter()
                info = history._finalize_staged_records(plan)
                metrics.seconds[f"finalize_{name}"] = time.perf_counter() - started
                started = time.perf_counter()
                reloaded[name] = history_quarters._read_staged_records(path, info)
                metrics.seconds[f"reload_{name}"] = time.perf_counter() - started
            result_counts = dict(result.counts)
            started = time.perf_counter()
            result.close(success=True)
            metrics.seconds["success_close"] = time.perf_counter() - started
            result = None
            metrics.seconds["total"] = time.perf_counter() - total_started
            artifact_bytes = sum(path.stat().st_size for path in (root / "staged").glob("*.parquet"))
            fingerprint = hashlib.sha256(_canonical(reloaded)).hexdigest()
            report = {
                "schema_version": "panel-generation-process-profile-v1",
                "fixture": {
                    "path": str(fixture_path),
                    "sha256": _sha256(fixture_path),
                    "counts": fixture["counts"],
                    "query": fixture["query"],
                    "root_node_id": fixture["root_node_id"],
                },
                "seconds": dict(sorted(metrics.seconds.items())),
                "calls": dict(sorted(metrics.calls.items())),
                "counts": metrics.counts,
                "output": {
                    "fingerprint": fingerprint,
                    "counts": result_counts,
                    "artifact_bytes": artifact_bytes,
                    "temporary_spool_bytes": spool_bytes,
                    "peak_temporary_spool_bytes": max(spool_bytes.values(), default=0),
                },
                "notes": {
                    "top_level_seconds_are_exclusive_phases": True,
                    "instrumented_subphase_seconds_are_inclusive_within_their_parent": True,
                    "no_sum_of_top_level_and_subphase_seconds": True,
                },
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return report
        finally:
            graph_module._plain_copy = originals["plain"]
            graph_module.ExplorationGraphReader.traverse = originals["traverse"]
            if "walk" in originals:
                graph_module._walk_paths = originals["walk"]
                graph_module.ExplorationGraphReader._iter_selected_fact_paths = originals[
                    "selected_paths"
                ]
            panel_module._reported_line = originals["reported"]
            panel_module.deepcopy = originals["deepcopy"]
            fiscal_module._FiscalTimeSeriesSpill.verify_integrity = originals["verify"]
            fiscal_module._FiscalTimeSeriesSpill.cells = originals["cells"]
            fiscal_module._FiscalTimeSeriesSpill.rows = originals["rows"]
            fiscal_module._resolve_cell = originals["resolve"]
            fiscal_module._spill_unpack = originals["unpack"]
            history.json.dumps = originals["dumps"]
            pl.DataFrame.write_parquet = originals["write"]
            pl.LazyFrame.sink_parquet = originals["sink"]
            history._sha256_file = originals["hash"]
            if result is not None:
                result.close(success=False)
            for plan in staged:
                plan.cleanup()


def run_workload(fixture_path: Path, output: Path) -> dict[str, Any]:
    """Run the complete bounded process without detail instrumentation."""
    from sec_xbrl import history
    from sec_xbrl.analytics import (
        CompanyAnalysisPanelBuilder,
        FiscalTimeSeriesBuilder,
        FiscalTimeSeriesInput,
        history_quarters,
    )

    fixture = json.loads(fixture_path.read_text())
    result = None
    staged = []
    with tempfile.TemporaryDirectory(prefix="panel-workload-") as directory:
        root = Path(directory)
        graph = _publication(fixture, root / "graph")
        started = time.perf_counter()
        try:
            panel = CompanyAnalysisPanelBuilder().build(
                selected_rows=fixture["selected_rows"],
                exploration=graph,
                **fixture["query"],
            )
            result = FiscalTimeSeriesBuilder().build_spilled(
                inputs=(FiscalTimeSeriesInput(panel, None),),
                spill_root=root / "spill",
            )
            reloaded: dict[str, Any] = {}
            file_info: dict[str, Any] = {}
            spool_bytes: dict[str, int] = {}
            for name in ("columns", "rows", "cells"):
                path = root / "staged" / f"{name}.parquet"
                records = result.dataset(name)
                if name == "columns":
                    records = tuple(records)
                plan = history._stage_records(path, records)
                staged.append(plan)
                spool_bytes[name] = getattr(plan, "spool_bytes", 0)
                info = history._finalize_staged_records(plan)
                file_info[name] = {
                    **info,
                    "bytes": path.stat().st_size,
                }
                reloaded[name] = history_quarters._read_staged_records(path, info)
            counts = dict(result.counts)
            result.close(success=True)
            result = None
            elapsed = time.perf_counter() - started
            report = {
                "schema_version": "panel-generation-workload-v1",
                "fixture_sha256": _sha256(fixture_path),
                "source": str(Path(history.__file__).resolve()),
                "seconds": elapsed,
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "output": {
                    "fingerprint": hashlib.sha256(_canonical(reloaded)).hexdigest(),
                    "counts": counts,
                    "files": file_info,
                    "artifact_bytes": sum(info["bytes"] for info in file_info.values()),
                    "temporary_spool_bytes": spool_bytes,
                    "peak_temporary_spool_bytes": max(spool_bytes.values(), default=0),
                },
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return report
        finally:
            if result is not None:
                result.close(success=False)
            for plan in staged:
                plan.cleanup()


def compare_workloads(
    fixture_path: Path,
    baseline_source: Path,
    candidate_source: Path,
    output: Path,
    *,
    rotations: int,
) -> dict[str, Any]:
    """Run alternating fresh processes and require complete semantic equality."""
    runs: dict[str, list[dict[str, Any]]] = {"baseline": [], "candidate": []}
    directory = output.parent / f".{output.stem}-runs"
    directory.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    for rotation in range(rotations):
        order = ("baseline", "candidate") if rotation % 2 == 0 else ("candidate", "baseline")
        for arm in order:
            source = baseline_source if arm == "baseline" else candidate_source
            result_path = directory / f"{rotation:02d}-{arm}.json"
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = str(source)
            command = [
                sys.executable,
                "-B",
                str(script),
                "run-workload",
                "--fixture",
                str(fixture_path),
                "--output",
                str(result_path),
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            deadline = time.monotonic() + 30
            watched_peak_rss_kib = 0
            while process.poll() is None:
                status = Path(f"/proc/{process.pid}/status")
                try:
                    for line in status.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            watched_peak_rss_kib = max(
                                watched_peak_rss_kib, int(line.split()[1])
                            )
                            break
                except FileNotFoundError:
                    pass
                if watched_peak_rss_kib > 1024 * 1024:
                    process.kill()
                    process.communicate()
                    raise RuntimeError(f"{arm} workload exceeded 1 GiB RSS")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise TimeoutError(f"{arm} workload exceeded 30 seconds")
                time.sleep(0.005)
            stdout, stderr = process.communicate()
            completed = subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
            completed.check_returncode()
            run = json.loads(result_path.read_text())
            run["rotation"] = rotation
            run["stdout"] = completed.stdout.strip()
            run["exit_code"] = completed.returncode
            run["watchdog_peak_rss_kib"] = watched_peak_rss_kib
            runs[arm].append(run)
    baseline_outputs = [run["output"] for run in runs["baseline"]]
    candidate_outputs = [run["output"] for run in runs["candidate"]]
    if any(value != baseline_outputs[0] for value in baseline_outputs[1:]):
        raise ValueError("baseline workload output changed across rotations")
    if any(value != candidate_outputs[0] for value in candidate_outputs[1:]):
        raise ValueError("candidate workload output changed across rotations")
    comparable_keys = ("fingerprint", "counts", "files", "artifact_bytes")
    if any(
        baseline_outputs[0][key] != candidate_outputs[0][key]
        for key in comparable_keys
    ):
        raise ValueError("candidate workload output differs from baseline")

    def summary(arm: str) -> dict[str, Any]:
        seconds = [run["seconds"] for run in runs[arm]]
        rss = [run["peak_rss_kib"] for run in runs[arm]]
        return {
            "seconds": seconds,
            "median_seconds": statistics.median(seconds),
            "peak_rss_kib": rss,
            "median_peak_rss_kib": statistics.median(rss),
        }

    report = {
        "schema_version": "panel-generation-paired-v1",
        "fixture": {"path": str(fixture_path), "sha256": _sha256(fixture_path)},
        "rotations": rotations,
        "limits": {"timeout_seconds_per_process": 30, "rss_kib": 1024 * 1024},
        "baseline": summary("baseline"),
        "candidate": summary("candidate"),
        "semantic_output": {
            key: baseline_outputs[0][key] for key in comparable_keys
        },
        "temporary_spool_bytes": candidate_outputs[0]["temporary_spool_bytes"],
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--source-root", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--fixture", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    workload = commands.add_parser("run-workload")
    workload.add_argument("--fixture", type=Path, required=True)
    workload.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--fixture", type=Path, required=True)
    compare.add_argument("--baseline-source", type=Path, required=True)
    compare.add_argument("--candidate-source", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--rotations", type=int, default=3)
    args = parser.parse_args()
    if args.command == "extract":
        print(json.dumps(extract_fixture(args.source_root, args.output), sort_keys=True))
    elif args.command == "run":
        report = run_profile(args.fixture, args.output)
        print(json.dumps({"output": str(args.output), "total_seconds": report["seconds"]["total"]}))
    elif args.command == "run-workload":
        report = run_workload(args.fixture, args.output)
        print(json.dumps({"output": str(args.output), "total_seconds": report["seconds"]}))
    else:
        report = compare_workloads(
            args.fixture,
            args.baseline_source,
            args.candidate_source,
            args.output,
            rotations=args.rotations,
        )
        print(json.dumps({"output": str(args.output), "rotations": report["rotations"]}))


if __name__ == "__main__":
    main()
