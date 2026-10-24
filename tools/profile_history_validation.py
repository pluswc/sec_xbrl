"""Compare detailed and routine history-publication storage validation."""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from sec_xbrl import history

ARMS = ("detailed", "routine-initial", "routine-unchanged", "routine-changed", "code-change")


def _fixture(root: Path, *, changed: bool = False) -> Path:
    tables = []
    for table_index in range(3):
        relative = Path("0000000001") / "LATEST_REPORTED" / f"TABLE_{table_index}"
        row_ids = tuple(f"row-{table_index}-{index}" for index in range(24))
        column_ids = tuple(f"column-{table_index}-{index}" for index in range(8))
        records = {
            "columns": tuple(
                {"fiscal_time_series_column_id": column_id, "fiscal_year": 2019 + index,
                 "fiscal_quarter": index % 4 + 1, "period_class": "QTD_3M"}
                for index, column_id in enumerate(column_ids)
            ),
            "rows": tuple(
                {"fiscal_time_series_row_id": row_id, "definition": {
                    "label": f"Financial row {index}", "roles": ["STATEMENT", "DISCLOSURE"],
                    "provenance": {"qname": f"us-gaap:Fixture{index}", "ordinal": index}}}
                for index, row_id in enumerate(row_ids)
            ),
            "cells": tuple(
                {"fiscal_time_series_cell_id": f"cell-{table_index}-{index}",
                 "fiscal_time_series_row_id": row_ids[index % len(row_ids)],
                 "fiscal_time_series_column_id": column_ids[index % len(column_ids)],
                 "value_lineage": {"value_numeric": str(index + (1 if changed and table_index == 1 else 0)),
                    "source_fact_ids": [f"fact-{table_index}-{index}"],
                    "candidate_lineage": [{"source": f"filing-{candidate}",
                        "dimensions": [["Axis", f"Member-{candidate}"]]}
                        for candidate in range(12)]}}
                for index in range(384)
            ),
        }
        files = {}
        for role, rows in records.items():
            path = root / relative / f"{role}.parquet"
            info = history._write_records(path, rows)
            files[role] = {**info, "path": str(relative / path.name)}
        tables.append({"ticker": "TEST", "cik": "0000000001", "view": "LATEST_REPORTED",
                       "period_class": f"TABLE_{table_index}", "scope": {"fixture": "nested"},
                       "files": files})
    history._write_json(root / "history_manifest.json", {
        "version": history.HISTORY_VERSION,
        "plan": {"companies": [{"ticker": "TEST", "cik": "0000000001"}]},
        "views": ["LATEST_REPORTED"], "source_intake": str(root.parent / "intake.json"),
        "input_fingerprint": "bounded-nested-fixture", "tables": tables,
    })
    return root


def _worker(arm: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="history-validation-profile-") as temporary:
        workspace = Path(temporary)
        state = workspace / "state"
        baseline = _fixture(workspace / "baseline")
        reader = history.HistoryPublicationReader(baseline)
        if arm in {"routine-unchanged", "routine-changed", "code-change"}:
            reader.validate(state_root=state)
        target = baseline
        if arm == "routine-changed":
            target = _fixture(workspace / "changed", changed=True)
        if arm == "code-change":
            state_path = next(state.glob("*.json"))
            payload = json.loads(state_path.read_text())
            payload["code_identity"] = "changed-source-identity"
            state_path.write_text(json.dumps(payload), encoding="utf-8")
        start = perf_counter()
        if arm == "detailed":
            history.HistoryPublicationReader(target).verify_all()
            result = None
        else:
            result = history.HistoryPublicationReader(target).validate(state_root=state)
        elapsed = perf_counter() - start
        manifest = json.loads((target / "history_manifest.json").read_text())
        ordered = [
            (info["path"], info["sha256"], info["count"], tuple(info["json_fields"]))
            for table in manifest["tables"] for info in table["files"].values()
        ]
        return {
            "arm": arm,
            "elapsed_seconds": elapsed,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "publication_fingerprint": __import__("hashlib").sha256(repr(ordered).encode()).hexdigest(),
            "validation_level": "DETAILED" if result is None else result.level,
            "checked_files": len(ordered) if result is None else len(result.checked_files),
            "hashed_files": len(ordered) if result is None else len(result.hashed_files),
            "sampled_rows": sum(item[2] for item in ordered) if result is None else result.sampled_rows,
            "decoded_json_values": -1 if result is None else result.decoded_json_values,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=ARMS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rotations", type=int, default=3)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.worker), sort_keys=True))
        return
    if args.output is None or args.rotations != 3:
        parser.error("parent mode requires --output and exactly three rotations")
    rows = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for _rotation in range(args.rotations):
        for arm in ARMS:
            completed = subprocess.run(
                [sys.executable, "-B", __file__, "--worker", arm], check=True,
                text=True, capture_output=True, env=env, timeout=30,
            )
            rows.append(json.loads(completed.stdout))
    fingerprints = {row["publication_fingerprint"] for row in rows if row["arm"] != "routine-changed"}
    if len(fingerprints) != 1:
        raise RuntimeError("validation arms did not consume identical publication declarations")
    payload = {
        "version": 1,
        "fixture": "bounded nested provenance; 3 tables x (8 columns, 24 rows, 384 cells)",
        "rotations": args.rotations,
        "rows": rows,
        "limits": {"child_timeout_seconds": 30, "completed_company_revalidation": False},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
