"""Command-line operations for prepared screening data and local service."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from sec_xbrl.metrics.screening import publish_screening_metrics
from sec_xbrl.screening.common import read_json, sha256_file
from sec_xbrl.screening.company_descriptions import MANIFEST as DESCRIPTION_MANIFEST
from sec_xbrl.screening.company_descriptions import (
    CompanyDescriptionReader,
    publish_company_descriptions,
    review_company_description_plan,
)
from sec_xbrl.screening.dataset import publish_screening_dataset
from sec_xbrl.screening.dataset_v2 import (
    open_screening_dataset,
    publish_screening_dataset_v2,
)
from sec_xbrl.screening.dataset_v3 import publish_screening_dataset_v3
from sec_xbrl.screening.metric_identity import publish_generic_metric_identity
from sec_xbrl.screening.server import serve
from sec_xbrl.screening.service import ScreeningService
from sec_xbrl.screening.store import STORE_VERSION, ScreeningStore, backup_store, restore_store

_CORE_STORE_TABLES = {
    "store_meta",
    "screen_definitions",
    "screen_revisions",
    "universe_snapshots",
    "screen_runs",
    "decision_events",
    "export_manifests",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sec_xbrl.screening")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="publish an immutable screening dataset")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    metrics = commands.add_parser("metrics", help="publish governed screening metrics")
    metrics.add_argument("--config", type=Path, required=True)
    metrics.add_argument("--destination", type=Path, required=True)
    identity = commands.add_parser(
        "metric-identity", help="publish a generic metric readiness identity"
    )
    identity.add_argument("--config", type=Path, required=True)
    identity.add_argument("--destination", type=Path, required=True)
    prepare_v2 = commands.add_parser("prepare-v2", help="publish a screening dataset v2")
    prepare_v2.add_argument("--config", type=Path, required=True)
    prepare_v2.add_argument("--destination", type=Path, required=True)
    prepare_v3 = commands.add_parser("prepare-v3", help="publish an annual + quarterly dataset v3")
    prepare_v3.add_argument("--config", type=Path, required=True)
    prepare_v3.add_argument("--destination", type=Path, required=True)
    descriptions = commands.add_parser(
        "descriptions-prepare", help="publish governed Korean company-description text"
    )
    descriptions.add_argument("--plan", type=Path, required=True)
    descriptions.add_argument("--dataset", type=Path, required=True)
    descriptions.add_argument("--destination", type=Path)
    descriptions.add_argument("--dry-run", action="store_true")
    description_status = commands.add_parser(
        "descriptions-status", help="verify a pinned company-description publication"
    )
    description_status.add_argument("--publication", type=Path, required=True)
    description_status.add_argument("--manifest-sha256", required=True)
    description_status.add_argument("--dataset", type=Path, required=True)
    status = commands.add_parser("status", help="verify a screening dataset")
    status.add_argument("--dataset", type=Path, required=True)
    server = commands.add_parser("serve", help="start the loopback dashboard")
    server.add_argument("--catalog", type=Path, required=True)
    server.add_argument("--store", type=Path, required=True)
    server.add_argument("--exports", type=Path, required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--descriptions", type=Path)
    server.add_argument("--descriptions-manifest-sha256")
    server.add_argument(
        "--require-existing-store",
        action="store_true",
        help="fail before journal initialization unless --store is an existing valid journal",
    )
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
    elif args.command == "metric-identity":
        result = publish_generic_metric_identity(args.config, args.destination)
        _print({"publication_id": result.publication_id, "root": str(result.root)})
    elif args.command == "prepare-v2":
        result = publish_screening_dataset_v2(args.config, args.destination)
        _print({"publication_id": result.publication_id, "root": str(result.root)})
    elif args.command == "prepare-v3":
        root = publish_screening_dataset_v3(args.config, args.destination)
        _print({"publication_id": open_screening_dataset(root).publication_id, "root": str(root)})
    elif args.command == "descriptions-prepare":
        if args.dry_run:
            result = review_company_description_plan(args.plan, args.dataset)
            _print(result)
            return 2 if result["blocked_count"] else 0
        if args.destination is None:
            raise ValueError("descriptions-prepare requires --destination unless --dry-run")
        result = publish_company_descriptions(args.plan, args.dataset, args.destination)
        _print(
            {
                "publication_id": result.publication_id,
                "root": str(result.root),
                "manifest_sha256": result.manifest_sha256,
            }
        )
    elif args.command == "descriptions-status":
        dataset = open_screening_dataset(args.dataset)
        reader = CompanyDescriptionReader(args.publication, args.manifest_sha256, dataset)
        _print(reader.verify_all())
    elif args.command == "serve":
        catalog = _catalog(args.catalog)
        descriptions = _serve_descriptions(args, catalog)
        if args.require_existing_store:
            _validate_existing_store(args.store)
        service = ScreeningService(
            catalog,
            ScreeningStore(args.store),
            company_descriptions=descriptions,
        )
        _print(
            {
                "event": "screening_service_startup",
                "python": str(Path(sys.executable).absolute()),
                "module": str(Path(__file__).resolve()),
                "catalog": str(args.catalog.absolute()),
                "store": str(args.store.absolute()),
                "exports": str(args.exports.absolute()),
                "require_existing_store": args.require_existing_store,
                "dataset_ids": sorted(catalog),
            }
        )
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
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("dataset_id"), str)
            or not isinstance(row.get("root"), str)
        ):
            raise TypeError("invalid screening catalog entry")
        if row["dataset_id"] in result:
            raise ValueError("duplicate screening catalog dataset ID")
        result[row["dataset_id"]] = Path(row["root"])
    return result


def _validate_existing_store(path: Path) -> None:
    """Validate an existing screening journal without creating or migrating it."""
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise ValueError("screening store path traverses a symlink")
    if not absolute.is_file():
        raise ValueError("required screening store does not exist as a regular file")
    try:
        with sqlite3.connect(f"{absolute.as_uri()}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                detail = result[0] if result else "no result"
                raise ValueError(f"SQLite integrity check failed: {detail}")
            row = connection.execute(
                "SELECT value FROM store_meta WHERE key='version'"
            ).fetchone()
            if row is None or row[0] != STORE_VERSION:
                raise ValueError("unsupported screening store version")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not _CORE_STORE_TABLES <= tables:
                raise ValueError("required screening store is missing core journal tables")
    except sqlite3.Error as exc:
        raise ValueError("required screening store is not a valid screening journal") from exc


def _serve_descriptions(
    args: argparse.Namespace, catalog: dict[str, Path]
) -> CompanyDescriptionReader | None:
    if (args.descriptions is None) != (args.descriptions_manifest_sha256 is None):
        raise ValueError("serve requires both description publication and manifest SHA-256")
    if args.descriptions is None:
        return None
    manifest_path = args.descriptions / DESCRIPTION_MANIFEST
    if sha256_file(manifest_path) != args.descriptions_manifest_sha256:
        raise ValueError("company-description manifest differs from pinned digest")
    manifest = read_json(manifest_path, "company-description manifest")
    dataset_id = manifest.get("dataset_id")
    if dataset_id not in catalog:
        raise ValueError("company-description dataset is absent from the screening catalog")
    dataset = open_screening_dataset(catalog[dataset_id])
    return CompanyDescriptionReader(
        args.descriptions,
        args.descriptions_manifest_sha256,
        dataset,
    )


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), flush=True)
