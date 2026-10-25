"""Compare legacy and single-pass history ID/reference validation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from time import perf_counter

from sec_xbrl import history

ARMS = ("baseline", "candidate")


def _fixture_factory(path: Path):
    spec = importlib.util.spec_from_file_location("history_profile_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load history validation fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._fixture


def _add_quarter(publication: Path) -> dict[str, int]:
    manifest_path = publication / "history_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table = manifest["tables"][1]
    reader = history.HistoryPublicationReader(publication)
    columns = list(reader._records(table["files"]["columns"]))
    rows = list(reader._records(table["files"]["rows"]))
    cells = list(reader._records(table["files"]["cells"]))
    column_id = "column-1-added-2026-q3"
    columns.append({
        "fiscal_time_series_column_id": column_id,
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
        "period_class": "QTD_3M",
    })
    for index, row in enumerate(rows):
        cells.append({
            "fiscal_time_series_cell_id": f"cell-1-added-{index}",
            "fiscal_time_series_row_id": row["fiscal_time_series_row_id"],
            "fiscal_time_series_column_id": column_id,
            "value_lineage": {
                "value_numeric": "109417000000" if index == 0 else str(1000 + index),
                "source_fact_ids": [f"fact-aapl-shape-{index}"],
                "candidate_lineage": [{
                    "accession": "0000320193-26-000020",
                    "raw_concept_qname": (
                        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                    ),
                    "source_fact_id": f"fact-aapl-shape-{index}",
                }],
            },
        })
    for role, records in (("columns", columns), ("cells", cells)):
        info = table["files"][role]
        path = publication / info["path"]
        path.unlink()
        written = history._write_records(path, tuple(records))
        table["files"][role] = {**written, "path": info["path"]}
    manifest_path.unlink()
    history._write_json(manifest_path, manifest)
    return {
        "unchanged_rows": len(rows),
        "prior_columns": len(columns) - 1,
        "added_columns": 1,
        "prior_cells": len(cells) - len(rows),
        "added_cells": len(rows),
        "other_tables_unchanged": len(manifest["tables"]) - 1,
    }


def _declarations(root: Path) -> list[tuple[str, str, int, tuple[str, ...]]]:
    manifest = json.loads((root / "history_manifest.json").read_text(encoding="utf-8"))
    return [
        (info["path"], info["sha256"], info["count"], tuple(info["json_fields"]))
        for table in manifest["tables"]
        for info in table["files"].values()
    ]


def _worker(publication: Path, state_root: Path, *, seed: bool) -> None:
    import polars as _polars  # noqa: F401 -- equal pre-import boundary for both arms

    if seed:
        history.HistoryPublicationReader(publication).validate(state_root=state_root)
        print(json.dumps({"seeded": True}))
        return
    started = perf_counter()
    result = history.HistoryPublicationReader(publication).validate(state_root=state_root)
    elapsed = perf_counter() - started
    print(json.dumps({
        "elapsed_seconds": elapsed,
        "level": result.level,
        "checked_files": list(result.checked_files),
        "hashed_files": list(result.hashed_files),
        "sampled_rows": result.sampled_rows,
        "decoded_json_values": result.decoded_json_values,
        "declaration_sha256": hashlib.sha256(repr(_declarations(publication)).encode()).hexdigest(),
    }, sort_keys=True))


def _run(command: list[str], env: dict[str, str], *, supervise: bool) -> tuple[dict, int]:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    peak = 0
    started = time.monotonic()
    while process.poll() is None:
        if time.monotonic() - started > 30:
            process.kill()
            raise TimeoutError("history validation benchmark child exceeded 30 seconds")
        if supervise:
            try:
                status = Path(f"/proc/{process.pid}/status").read_text(encoding="utf-8")
                line = next(row for row in status.splitlines() if row.startswith("VmRSS:"))
                peak = max(peak, int(line.split()[1]))
                if peak > 1024 * 1024:
                    process.kill()
                    raise MemoryError("history validation benchmark child exceeded 1 GiB RSS")
            except (FileNotFoundError, StopIteration):
                pass
        time.sleep(0.005)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr)
    return json.loads(stdout), peak


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--publication", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        if args.publication is None or args.state_root is None:
            parser.error("worker paths required")
        _worker(args.publication, args.state_root, seed=args.seed)
        return
    if args.repo is None or args.baseline_repo is None or args.output is None:
        parser.error("parent paths required")
    workspace = args.output.parent / "prepared_workspace"
    if workspace.exists() or args.output.exists():
        raise FileExistsError("benchmark output already exists")
    workspace.mkdir(parents=True)
    fixture = _fixture_factory(args.repo / "tools" / "profile_history_validation.py")
    canonical_baseline = fixture(workspace / "canonical-baseline")
    canonical_changed = workspace / "canonical-added-quarter"
    shutil.copytree(canonical_baseline, canonical_changed)
    change_shape = _add_quarter(canonical_changed)
    sources = {"baseline": args.baseline_repo, "candidate": args.repo}
    rows = []
    for rotation in range(3):
        order = ARMS if rotation % 2 == 0 else tuple(reversed(ARMS))
        for arm in order:
            run_root = workspace / f"rotation-{rotation + 1}" / arm
            prior = run_root / "prior"
            changed = run_root / "added-quarter"
            state = run_root / "state"
            shutil.copytree(canonical_baseline, prior)
            shutil.copytree(canonical_changed, changed)
            source = sources[arm]
            env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(source / "src"),
            }
            seed_command = [
                sys.executable, "-B", str(Path(__file__).absolute()), "--worker", "--seed",
                "--publication", str(prior), "--state-root", str(state),
            ]
            _run(seed_command, env, supervise=False)
            command = [
                sys.executable, "-B", str(Path(__file__).absolute()), "--worker",
                "--publication", str(changed), "--state-root", str(state),
            ]
            result, peak = _run(command, env, supervise=True)
            rows.append({**result, "arm": arm, "rotation": rotation + 1,
                         "supervisor_observed_peak_rss_kib": peak})
    declaration_hashes = {row["declaration_sha256"] for row in rows}
    if len(declaration_hashes) != 1:
        raise RuntimeError("benchmark arms did not consume identical declarations")
    payload = {
        "version": 1,
        "rotations": 3,
        "source": {
            "baseline": "d188552b7dc6207607b77bbaf83ff50ac744fea3",
            "candidate": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=args.repo, text=True
            ).strip() + "+working-tree-ID-FK-change",
        },
        "boundary": (
            "Parent prepares identical publication copies and source-specific prior state; "
            "fresh child pre-imports Polars, then runs only HistoryPublicationReader.validate."
        ),
        "rss": {
            "sampling_interval_ms": 5,
            "limitation": "Sampled maximum can miss a shorter transient peak; not a kernel-exact peak.",
        },
        "fixture": "Frozen nested fixture with one column and 24 cells appended to one table",
        "change_shape": change_shape,
        "rows": rows,
        "limits": {"child_timeout_seconds": 30, "child_rss_limit_kib": 1024 * 1024},
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
