"""Profile bounded synthetic History storage paths without SEC data."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from sec_xbrl import history


class JsonLineSequence(Sequence[dict[str, Any]]):
    """A reiterable disk-backed fixture that counts full reads and decodes."""

    def __init__(self, path: Path, count: int) -> None:
        self.path = path
        self.count = count
        self.iterations = 0
        self.decodes = 0

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> dict[str, Any]:
        raise TypeError("profile fixture supports sequential iteration only")

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.iterations += 1
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                self.decodes += 1
                yield json.loads(line)


def _fixture(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8") as target:
        for index in range(count):
            row: dict[str, Any] = {
                "id": f"row-{index:05d}",
                "number": index + 0.25,
                "flag": index % 2 == 0,
                "optional": None if index % 5 == 0 else index,
            }
            if index >= count // 2:
                row["late_nested"] = {"index": index, "tags": ["a", "b"]}
            elif index % 3:
                row["late_nested"] = index
            target.write(json.dumps(row, sort_keys=True) + "\n")


def _legacy_stage(path: Path, records: JsonLineSequence) -> dict[str, Any]:
    """Baseline three-pass staging retained only for synthetic comparison."""
    import polars as pl

    ordered_json_fields = sorted(
        {
            key
            for row in records
            for key, value in row.items()
            if isinstance(value, (dict, list, tuple))
        }
    )
    schemas = [
        pl.from_dicts(
            history._schema_record_batch(batch, ordered_json_fields),
            infer_schema_length=None,
        ).schema
        for batch in history._iter_record_batches(records)
    ]
    global_schema = pl.concat(
        [pl.DataFrame(schema=schema).lazy() for schema in schemas],
        how="diagonal_relaxed",
    ).collect_schema()
    workspace = tempfile.TemporaryDirectory(prefix="profile-history-chunks-", dir=path.parent)
    chunks: list[Path] = []
    try:
        for encoded_batch, _ in history._iter_encoded_record_batches(
            records, ordered_json_fields
        ):
            chunk = Path(workspace.name) / f"{len(chunks):08d}.parquet"
            pl.from_dicts(
                encoded_batch, schema=global_schema, infer_schema_length=None
            ).write_parquet(chunk, row_group_size=history._RECORD_WRITE_BATCH_SIZE)
            chunks.append(chunk)
        pl.concat([pl.scan_parquet(chunk) for chunk in chunks], how="vertical").sink_parquet(
            path,
            maintain_order=True,
            row_group_size=history._RECORD_WRITE_BATCH_SIZE,
        )
    finally:
        workspace.cleanup()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "json_fields": ordered_json_fields,
    }


def _timed_stage(kind: str, root: Path, fixture: Path, count: int) -> dict[str, Any]:
    records = JsonLineSequence(fixture, count)
    output = root / f"{kind}.parquet"
    started = time.perf_counter()
    if kind == "baseline":
        result = _legacy_stage(output, records)
    else:
        staged = history._stage_records(output, records)
        result = history._finalize_staged_records(staged)
    return {
        "seconds": time.perf_counter() - started,
        "iterations": records.iterations,
        "record_decodes": records.decodes,
        "sha256": result["sha256"],
        "json_fields": result["json_fields"],
        "bytes": output.stat().st_size,
    }


def _profile_h1(root: Path, files: int = 10_332, directories: int = 72) -> dict[str, Any]:
    tree = root / "h1-tree"
    tree.mkdir()
    for index in range(directories):
        (tree / f"d-{index:03d}").mkdir()
    for index in range(files):
        (tree / f"d-{index % directories:03d}" / f"f-{index:05d}").touch()
    started = time.perf_counter()
    visits = 0
    for path in tree.rglob("*"):
        path.lstat()
        visits += 1
    return {
        "files": files,
        "directories": directories,
        "visited_entries": visits,
        "one_scan_seconds": time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=int, default=4096)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="history-storage-profile-") as temporary:
        root = Path(temporary)
        fixture = root / "records.jsonl"
        _fixture(fixture, args.records)
        results = {
            "scope": "synthetic-source-only",
            "records": args.records,
            "h1": _profile_h1(root),
            "h2": {
                "baseline": _timed_stage("baseline", root, fixture, args.records),
                "candidate_production": _timed_stage("candidate", root, fixture, args.records),
            },
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
