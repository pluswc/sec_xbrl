"""Command-line operations for prepared screening data and local service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sec_xbrl.metrics.screening import publish_screening_metrics
from sec_xbrl.screening.common import read_json
from sec_xbrl.screening.dataset import publish_screening_dataset
from sec_xbrl.screening.dataset_v2 import (
    open_screening_dataset,
    publish_screening_dataset_v2,
)
from sec_xbrl.screening.server import serve
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import ScreeningStore, backup_store, restore_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sec_xbrl.screening")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="publish an immutable screening dataset")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    metrics = commands.add_parser("metrics", help="publish governed screening metrics")
    metrics.add_argument("--config", type=Path, required=True)
    metrics.add_argument("--destination", type=Path, required=True)
    prepare_v2 = commands.add_parser("prepare-v2", help="publish a screening dataset v2")
    prepare_v2.add_argument("--config", type=Path, required=True)
    prepare_v2.add_argument("--destination", type=Path, required=True)
    status = commands.add_parser("status", help="verify a screening dataset")
    status.add_argument("--dataset", type=Path, required=True)
    server = commands.add_parser("serve", help="start the loopback dashboard")
    server.add_argument("--catalog", type=Path, required=True)
    server.add_argument("--store", type=Path, required=True)
    server.add_argument("--exports", type=Path, required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    backup = commands.add_parser("backup", help="create a consistent journal backup")
    backup.add_argument("--store", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    restore = commands.add_parser("restore", help="restore to a new empty journal path")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = publish_screening_dataset(args.config, args.destination)
        _print({"publication_id": result.publication_id, "root": str(result.root)})
    elif args.command == "status":
        _print(open_screening_dataset(args.dataset).verify_all())
    elif args.command == "metrics":
        result = publish_screening_metrics(args.config, args.destination)
        _print({"publication_id": result.publication_id, "root": str(result.root)})
    elif args.command == "prepare-v2":
        result = publish_screening_dataset_v2(args.config, args.destination)
        _print({"publication_id": result.publication_id, "root": str(result.root)})
    elif args.command == "serve":
        catalog = _catalog(args.catalog)
        service = ScreeningService(catalog, ScreeningStore(args.store))
        serve(service, export_root=args.exports, host=args.host, port=args.port)
    elif args.command == "backup":
        _print({"backup": str(backup_store(args.store, args.destination))})
    else:
        _print({"store": str(restore_store(args.backup, args.destination))})
    return 0


def _catalog(path: Path) -> dict[str, Path]:
    value = read_json(path, "screening dataset catalog")
    if not isinstance(value, dict) or value.get("schema_version") != "screening-catalog-v1":
        raise ValueError("unsupported screening catalog")
    datasets = value.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("screening catalog requires datasets")
    result: dict[str, Path] = {}
    for row in datasets:
        if not isinstance(row, dict) or not isinstance(row.get("dataset_id"), str) or not isinstance(row.get("root"), str):
            raise TypeError("invalid screening catalog entry")
        if row["dataset_id"] in result:
            raise ValueError("duplicate screening catalog dataset ID")
        result[row["dataset_id"]] = Path(row["root"])
    return result


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
