#!/usr/bin/env python3
"""Fail-closed offline orchestration for exact-50 financial publications."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec_xbrl import analysis, company_metadata, metric_quality
from sec_xbrl import collection_operations as collection_ops
from sec_xbrl.metrics import quarterly_screening, screening
from sec_xbrl.screening import dataset_v2, dataset_v3, metric_identity
from sec_xbrl.screening.common import sha256_file
from tools import universe50_package_view as package_view
from tools import universe50_t3v2_ops as resource_ops

CONFIG_VERSION = "universe50-financial-ops-config-v1"
PREFLIGHT_VERSION = "universe50-financial-ops-preflight-v1"
REQUEST_VERSION = "universe50-financial-stage-request-v1"
GO_VERSION = "universe50-financial-stage-go-v1"
RECEIPT_VERSION = "universe50-financial-stage-receipt-v1"
RESOURCE_VERSION = "universe50-financial-resource-run-v1"
FIRST5_ACCEPTANCE_VERSION = "universe50-first5-financial-acceptance-v1"
FIRST5_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_FIRST5_FINANCIAL"
FINANCIAL_AS_OF = "2026-10-10"
METADATA_CUTOFF = "2026-10-13T23:59:59Z"
KDP_ACQUISITION_COMPLETED_AT = "2026-10-13T14:45:00.965796Z"
FIRST5 = ("TXN", "HD", "JNJ", "CVX", "NEE")
GLOBAL_QUARTER_SPINE = (
    (2024, 4),
    (2025, 1),
    (2025, 2),
    (2025, 3),
    (2025, 4),
    (2026, 1),
    (2026, 2),
    (2026, 3),
)
LIMIT_KIB = 16 * 1024 * 1024
POLARS_THREADS = 2
TIMEOUT_SECONDS = 10_800
STAGES = (
    "metadata",
    "annual-analysis",
    "quarterly-analysis",
    "quality",
    "identity",
    "annual-metrics",
    "annual-dataset-v2",
    "quarterly-metrics",
    "combined-dataset-v3",
)
FIRST5_ACCEPTED_STAGES = tuple(stage for stage in STAGES if stage != "metadata")
DEPENDENCIES = {
    "metadata": (),
    "annual-analysis": (),
    "quarterly-analysis": (),
    "quality": (),
    "identity": ("annual-analysis", "quarterly-analysis", "quality"),
    "annual-metrics": ("identity",),
    "annual-dataset-v2": ("annual-metrics",),
    "quarterly-metrics": ("annual-metrics", "quarterly-analysis", "identity"),
    "combined-dataset-v3": ("annual-dataset-v2", "quarterly-metrics"),
}
OUTPUT_KEYS = {
    "metadata": ("metadata",),
    "annual-analysis": ("annual_analysis",),
    "quarterly-analysis": ("quarterly_analysis",),
    "quality": ("quality_indexes", "quality_bindings", "quality"),
    "identity": ("identity",),
    "annual-metrics": ("annual_metrics",),
    "annual-dataset-v2": ("annual_dataset_v2",),
    "quarterly-metrics": ("quarterly_metrics",),
    "combined-dataset-v3": ("combined_dataset_v3",),
}
PINNED_MODULES = {
    "analysis": "src/sec_xbrl/analysis.py",
    "company_metadata": "src/sec_xbrl/company_metadata.py",
    "metric_quality": "src/sec_xbrl/metric_quality.py",
    "metric_identity": "src/sec_xbrl/screening/metric_identity.py",
    "annual_metrics": "src/sec_xbrl/metrics/screening.py",
    "annual_dataset_v2": "src/sec_xbrl/screening/dataset_v2.py",
    "quarterly_metrics": "src/sec_xbrl/metrics/quarterly_screening.py",
    "combined_dataset_v3": "src/sec_xbrl/screening/dataset_v3.py",
    "resource_ops": "tools/universe50_t3v2_ops.py",
    "package_view": "tools/universe50_package_view.py",
    "runner": "tools/universe50_financial_ops.py",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _write_new(path: Path, value: dict[str, Any], label: str) -> Path:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{label} must be new: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path


def _regular(path: Path, label: str) -> Path:
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path.resolve()


def _directory(path: Path, label: str) -> Path:
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a real directory: {path}")
    return path.resolve()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase Git SHA-1")
    return value


def _absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return path


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed.astimezone(UTC)


def _pin(path_value: Any, digest_value: Any, label: str) -> Path:
    path = _regular(Path(path_value), label)
    if sha256_file(path) != _sha(digest_value, f"{label} SHA-256"):
        raise ValueError(f"{label} hash differs")
    return path


def _companies(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("financial scope requires companies")
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise TypeError("financial company entry must be an object")
        ticker, cik = row.get("ticker"), row.get("cik")
        if (
            not isinstance(ticker, str)
            or ticker != ticker.upper()
            or not ticker
            or not isinstance(cik, str)
            or len(cik) != 10
            or not cik.isdigit()
        ):
            raise ValueError(f"invalid company identity at index {index}")
        years, display = row.get("input_years"), row.get("display_years")
        if (
            not isinstance(years, list)
            or len(years) != 5
            or years != sorted(set(years))
            or display != years[-4:]
        ):
            raise ValueError(f"{ticker}: annual window must be 5 input / 4 display")
        quarter_years = row.get("quarter_input_years")
        if (
            not isinstance(quarter_years, list)
            or not quarter_years
            or any(type(year) is not int for year in quarter_years)
            or quarter_years != list(range(quarter_years[0], quarter_years[-1] + 1))
            or quarter_years[0] != years[0]
            or quarter_years[-1] < years[-1]
        ):
            raise ValueError(
                f"{ticker}: quarterly window must be explicit, consecutive, start "
                "with the annual input window, and include its final fiscal year"
            )
        result.append(
            {
                "ticker": ticker,
                "cik": cik,
                "input_years": years,
                "display_years": display,
                "quarter_input_years": quarter_years,
                "history_output_root": str(
                    _absolute_path(
                        row.get("history_output_root"), f"{ticker} history output root"
                    )
                ),
                "history_root": str(
                    _absolute_path(row.get("history_root"), f"{ticker} history root")
                ),
                "build_manifest": str(
                    _absolute_path(
                        row.get("build_manifest"), f"{ticker} build manifest"
                    )
                ),
                "build_manifest_sha256": _sha(
                    row.get("build_manifest_sha256"), f"{ticker} build manifest"
                ),
                "history_manifest_sha256": _sha(
                    row.get("history_manifest_sha256"), f"{ticker} history manifest"
                ),
                "collector_source_commit_sha": _git_sha(
                    row.get("collector_source_commit_sha"),
                    f"{ticker} collector source declaration",
                ),
                "plan_sha256": _sha(row.get("plan_sha256"), f"{ticker} plan"),
                "intake_sha256": _sha(row.get("intake_sha256"), f"{ticker} intake"),
            }
        )
    ordered = sorted(result, key=lambda row: row["cik"])
    if len({row["ticker"] for row in ordered}) != len(ordered) or len(
        {row["cik"] for row in ordered}
    ) != len(ordered):
        raise ValueError("financial company scope contains duplicate identity")
    return ordered


def _validate_shape(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported financial operations config")
    if value.get("financial_as_of") != FINANCIAL_AS_OF:
        raise ValueError("financial cutoff differs")
    date.fromisoformat(value["financial_as_of"])
    if value.get("metadata_observation_cutoff") != METADATA_CUTOFF:
        raise ValueError("metadata observation cutoff differs")
    metadata_cutoff = _timestamp(value["metadata_observation_cutoff"], "metadata cutoff")
    companies = _companies(value.get("companies"))
    tickers = [row["ticker"] for row in companies]
    mode = value.get("collection_scope_mode")
    if mode == "EXPLICIT_SUBSET" and set(tickers) != set(FIRST5):
        raise ValueError("first-five scope must be the exact approved five companies")
    if mode == "FULL" and len(companies) != 50:
        raise ValueError("FULL scope requires exact-50 companies")
    if mode not in {"EXPLICIT_SUBSET", "FULL"}:
        raise ValueError("collection scope mode must be explicit")
    if value.get("first5") != list(FIRST5):
        raise ValueError("approved first-five order differs")
    acceptance = value.get("first5_financial_acceptance")
    if mode == "FULL":
        if not isinstance(acceptance, dict) or set(acceptance) != {"path", "sha256"}:
            raise ValueError("FULL scope requires first-five financial acceptance")
        _absolute_path(acceptance.get("path"), "first-five financial acceptance")
        _sha(acceptance.get("sha256"), "first-five financial acceptance")
    elif acceptance is not None:
        raise ValueError("subset scope cannot declare bulk financial acceptance")
    limits = value.get("limits")
    if limits != {
        "process_tree_rss_kib": LIMIT_KIB,
        "polars_max_threads": POLARS_THREADS,
        "one_heavy_process": True,
        "timeout_seconds": TIMEOUT_SECONDS,
    }:
        raise ValueError("financial resource limits differ")
    collection = value.get("collection") or {}
    _absolute_path(collection.get("manifest"), "collection manifest")
    _sha(collection.get("manifest_sha256"), "collection manifest")
    if collection.get("parent_company_count") != 50:
        raise ValueError("financial parent must be exact-50")
    packages = value.get("package_view") or {}
    _absolute_path(packages.get("root"), "package view root")
    _sha(packages.get("manifest_sha256"), "package view manifest")
    metadata = value.get("metadata") or {}
    metadata_mode = metadata.get("mode")
    if metadata_mode == "EXISTING_PUBLICATION":
        _absolute_path(metadata.get("root"), "existing metadata root")
        _sha(metadata.get("manifest_sha256"), "existing metadata manifest")
    elif metadata_mode == "PUBLISH_EXACT50":
        snapshots = metadata.get("snapshots")
        if not isinstance(snapshots, list) or len(snapshots) != 50:
            raise ValueError("fresh exact-50 metadata requires 50 source snapshots")
        identities = set()
        for index, row in enumerate(snapshots):
            if not isinstance(row, dict):
                raise TypeError("metadata snapshot entry must be an object")
            ticker, cik = row.get("ticker"), row.get("cik")
            if (
                not isinstance(ticker, str)
                or not ticker
                or ticker != ticker.upper()
                or not isinstance(cik, str)
                or len(cik) != 10
                or not cik.isdigit()
            ):
                raise ValueError(f"invalid metadata source identity at index {index}")
            identities.add((ticker, cik))
            _absolute_path(row.get("path"), f"{ticker} metadata snapshot")
            _sha(row.get("sha256"), "metadata snapshot")
            if row.get("source", "sec_submissions") != "sec_submissions":
                raise ValueError("metadata snapshots must be cached SEC submissions roots")
            if _timestamp(row.get("observed_at"), "metadata observed_at") > metadata_cutoff:
                raise ValueError("metadata observation is after its explicit cutoff")
        if len(identities) != 50:
            raise ValueError("fresh metadata source identities must be unique")
        if sum(ticker == "KDP" for ticker, _cik in identities) != 1:
            raise ValueError("fresh metadata sources require exactly one KDP observation")
        kdp = metadata.get("kdp_acquisition_evidence") or {}
        _absolute_path(kdp.get("path"), "KDP acquisition evidence")
        _sha(kdp.get("sha256"), "KDP acquisition evidence")
        if kdp.get("completed_at") != KDP_ACQUISITION_COMPLETED_AT:
            raise ValueError("KDP acquisition completion evidence differs")
        if _timestamp(kdp["completed_at"], "KDP acquisition completed_at") > metadata_cutoff:
            raise ValueError("KDP acquisition is after metadata cutoff")
    else:
        raise ValueError("metadata mode must be explicit")
    outputs = value.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {
        key for keys in OUTPUT_KEYS.values() for key in keys
    }:
        raise ValueError("financial outputs must declare every exact stage root")
    raw_paths = [
        _absolute_path(path, "financial output root") for path in outputs.values()
    ]
    paths = [path.absolute() for path in raw_paths]
    if len(set(paths)) != len(paths):
        raise ValueError("financial output roots must be unique absolute paths")
    source = value.get("source") or {}
    _absolute_path(source.get("checkout"), "integration checkout")
    _git_sha(source.get("head"), "integration source head")
    pins = source.get("module_sha256s")
    if not isinstance(pins, dict) or set(pins) != set(PINNED_MODULES):
        raise ValueError("integration source module pins are incomplete")
    for name, digest in pins.items():
        _sha(digest, f"module pin {name}")
    _absolute_path(value.get("execution_root"), "financial execution root")
    _absolute_path(value.get("resource_root"), "shared resource root")
    return {**value, "companies": companies}


def _verify_runtime(config: dict[str, Any]) -> dict[str, Any]:
    checkout = _directory(Path(config["source"]["checkout"]), "integration checkout")
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != config["source"]["head"] or dirty:
        raise ValueError("integration checkout must be clean at its exact configured HEAD")
    files = {}
    for name, relative in PINNED_MODULES.items():
        path = _regular(checkout / relative, f"module {name}")
        digest = sha256_file(path)
        if digest != config["source"]["module_sha256s"][name]:
            raise ValueError(f"configured module changed: {name}")
        files[name] = {"path": str(path), "sha256": digest}
    imported = {
        "analysis": Path(analysis.__file__).resolve(),
        "company_metadata": Path(company_metadata.__file__).resolve(),
        "metric_quality": Path(metric_quality.__file__).resolve(),
        "metric_identity": Path(metric_identity.__file__).resolve(),
        "annual_metrics": Path(screening.__file__).resolve(),
        "annual_dataset_v2": Path(dataset_v2.__file__).resolve(),
        "quarterly_metrics": Path(quarterly_screening.__file__).resolve(),
        "combined_dataset_v3": Path(dataset_v3.__file__).resolve(),
        "resource_ops": Path(resource_ops.__file__).resolve(),
        "package_view": Path(package_view.__file__).resolve(),
        "runner": Path(__file__).resolve(),
    }
    if any(imported[name] != Path(files[name]["path"]) for name in imported):
        raise ValueError("imported financial modules are outside configured checkout")
    return {"checkout": str(checkout), "head": head, "files": files}


def load_config(path: Path, *, runtime: bool = True) -> tuple[dict[str, Any], str]:
    path = _regular(path, "financial operations config")
    config = _validate_shape(_read_json(path, "financial operations config"))
    if runtime:
        _verify_runtime(config)
    return config, sha256_file(path)


def _manifest_path(root: Path, name: str) -> Path:
    return _regular(root / name, name)


def _metadata_root(config: dict[str, Any]) -> Path:
    metadata = config["metadata"]
    if metadata["mode"] == "EXISTING_PUBLICATION":
        root = _directory(Path(metadata["root"]), "existing metadata publication")
        manifest = _manifest_path(root, company_metadata.MANIFEST_NAME)
        if sha256_file(manifest) != metadata["manifest_sha256"]:
            raise ValueError("existing metadata publication changed")
        company_metadata.CompanyMetadataReader(root)
        return root
    return _directory(Path(config["outputs"]["metadata"]), "fresh metadata publication")


def _first5_companies(config: dict[str, Any]) -> list[dict[str, str]]:
    by_ticker = {row["ticker"]: row for row in config["companies"]}
    if not set(FIRST5) <= set(by_ticker):
        raise ValueError("financial config lacks the exact approved first-five companies")
    return [
        {"ticker": ticker, "cik": by_ticker[ticker]["cik"]} for ticker in FIRST5
    ]


def _expected_publication_manifests(config: dict[str, Any]) -> list[dict[str, str]]:
    metadata_root = (
        Path(config["metadata"]["root"])
        if config["metadata"]["mode"] == "EXISTING_PUBLICATION"
        else Path(config["outputs"]["metadata"])
    )
    values = [
        ("metadata", metadata_root, company_metadata.MANIFEST_NAME),
        ("quality", Path(config["outputs"]["quality"]), metric_quality.MANIFEST_NAME),
        ("identity", Path(config["outputs"]["identity"]), metric_identity.MANIFEST_NAME),
        ("annual_metrics", Path(config["outputs"]["annual_metrics"]), screening.MANIFEST),
        (
            "annual_dataset_v2",
            Path(config["outputs"]["annual_dataset_v2"]),
            dataset_v2.MANIFEST,
        ),
        (
            "quarterly_metrics",
            Path(config["outputs"]["quarterly_metrics"]),
            quarterly_screening.MANIFEST,
        ),
        (
            "combined_dataset_v3",
            Path(config["outputs"]["combined_dataset_v3"]),
            dataset_v3.MANIFEST,
        ),
    ]
    for ticker in FIRST5:
        values.extend(
            (
                (
                    f"annual_analysis:{ticker}",
                    _analysis_root(config, "annual_analysis", ticker),
                    "analysis_manifest.json",
                ),
                (
                    f"quarterly_analysis:{ticker}",
                    _analysis_root(config, "quarterly_analysis", ticker),
                    "analysis_manifest.json",
                ),
            )
        )
    return [
        {
            "name": name,
            "root": str(root),
            "manifest": str(root / filename),
            "manifest_sha256": sha256_file(
                _regular(root / filename, f"accepted {name} manifest")
            ),
        }
        for name, root, filename in values
    ]


def _validate_first5_acceptance(config: dict[str, Any]) -> dict[str, Any] | None:
    if config["collection_scope_mode"] != "FULL":
        if config.get("first5_financial_acceptance") is not None:
            raise ValueError("subset scope cannot declare bulk financial acceptance")
        return None
    declaration = config.get("first5_financial_acceptance") or {}
    if not isinstance(declaration, dict) or set(declaration) != {"path", "sha256"}:
        raise ValueError("FULL scope requires first-five financial acceptance")
    path = _pin(
        declaration.get("path"),
        declaration.get("sha256"),
        "first-five financial acceptance",
    )
    acceptance = _read_json(path, "first-five financial acceptance")
    expected_keys = {
        "schema_version",
        "status",
        "source_head",
        "financial_as_of",
        "metadata_observation_cutoff",
        "collection",
        "companies",
        "first5_config",
        "stage_receipts",
        "publication_manifests",
    }
    if set(acceptance) != expected_keys:
        raise ValueError("first-five financial acceptance shape differs")
    if (
        acceptance.get("schema_version") != FIRST5_ACCEPTANCE_VERSION
        or acceptance.get("status") != FIRST5_ACCEPTANCE_STATUS
        or acceptance.get("source_head") != config["source"]["head"]
        or acceptance.get("financial_as_of") != FINANCIAL_AS_OF
        or acceptance.get("metadata_observation_cutoff") != METADATA_CUTOFF
        or acceptance.get("collection") != config["collection"]
        or acceptance.get("companies") != _first5_companies(config)
    ):
        raise ValueError("first-five financial acceptance scope differs")
    first5_declaration = acceptance.get("first5_config") or {}
    first5_path = _pin(
        first5_declaration.get("path"),
        first5_declaration.get("sha256"),
        "accepted first-five financial config",
    )
    first5 = _validate_shape(_read_json(first5_path, "accepted first-five config"))
    current_first5 = {
        row["ticker"]: row for row in config["companies"] if row["ticker"] in FIRST5
    }
    accepted_first5 = {row["ticker"]: row for row in first5["companies"]}
    if (
        first5["collection_scope_mode"] != "EXPLICIT_SUBSET"
        or _first5_companies(first5) != acceptance["companies"]
        or accepted_first5 != current_first5
        or first5["universe_id"] != config["universe_id"]
        or first5["collection"] != config["collection"]
        or first5["metadata"] != config["metadata"]
        or first5["source"] != config["source"]
        or first5["financial_as_of"] != FINANCIAL_AS_OF
        or first5["metadata_observation_cutoff"] != METADATA_CUTOFF
    ):
        raise ValueError("accepted first-five config differs from FULL execution")
    stages = list(FIRST5_ACCEPTED_STAGES)
    if first5["metadata"]["mode"] == "PUBLISH_EXACT50":
        stages.insert(0, "metadata")
    receipts = acceptance.get("stage_receipts")
    if not isinstance(receipts, dict) or set(receipts) != set(stages):
        raise ValueError("first-five financial stage receipt set differs")
    for stage in stages:
        declaration = receipts[stage]
        if not isinstance(declaration, dict) or set(declaration) != {"path", "sha256"}:
            raise ValueError("first-five financial stage receipt declaration differs")
        receipt_path = _pin(
            declaration["path"], declaration["sha256"], f"accepted {stage} receipt"
        )
        receipt = _read_json(receipt_path, f"accepted {stage} receipt")
        if (
            receipt.get("schema_version") != RECEIPT_VERSION
            or receipt.get("status") != "PASS"
            or receipt.get("stage") != stage
            or receipt.get("source_head") != config["source"]["head"]
            or not isinstance(receipt.get("go_sha256"), str)
            or SHA256.fullmatch(receipt["go_sha256"]) is None
        ):
            raise ValueError(f"accepted {stage} receipt identity differs")
        _verify_output_receipt(receipt, stage)
        if [row.get("root") for row in receipt["outputs"]] != [
            str(root) for root in _output_paths(first5, stage)
        ]:
            raise ValueError(f"accepted {stage} receipt output roots differ")
    expected_manifests = _expected_publication_manifests(first5)
    if acceptance.get("publication_manifests") != expected_manifests:
        raise ValueError("first-five accepted publication manifests differ")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "status": FIRST5_ACCEPTANCE_STATUS,
        "first5_config": {
            "path": str(first5_path),
            "sha256": sha256_file(first5_path),
        },
        "stage_receipts": copy.deepcopy(receipts),
        "publication_manifests": expected_manifests,
    }


def _validate_history_build_binding(
    config: dict[str, Any], company: dict[str, Any]
) -> dict[str, str]:
    ticker = company["ticker"]
    collection = Path(config["collection"]["manifest"])
    expected_marker = collection.parent / "companies" / ticker / "build_manifest.json"
    configured_marker = Path(company["build_manifest"])
    if configured_marker != expected_marker:
        raise ValueError(f"{ticker}: configured build marker path differs")
    marker_path = _pin(
        configured_marker,
        company["build_manifest_sha256"],
        f"{ticker} READY build marker",
    )
    marker = _read_json(marker_path, f"{ticker} READY build marker")
    history_root = Path(company["history_root"])
    history_manifest = _regular(
        history_root / "history_manifest.json", f"{ticker} history manifest"
    )
    history = _read_json(history_manifest, f"{ticker} history manifest")
    plan = history.get("plan") or {}
    if (
        marker.get("status") != "READY"
        or marker.get("ticker") != ticker
        or marker.get("output_root") != company["history_output_root"]
        or marker.get("publication") != str(history_root)
        or marker.get("history_manifest") != str(history_manifest)
        or marker.get("history_manifest_sha256")
        != company["history_manifest_sha256"]
        or marker.get("plan_sha256") != company["plan_sha256"]
        or marker.get("intake_sha256") != company["intake_sha256"]
        or sha256_file(history_manifest) != company["history_manifest_sha256"]
        or plan.get("as_of_date") != FINANCIAL_AS_OF
    ):
        raise ValueError(f"{ticker}: configured history differs from READY build marker")
    return {
        "build_manifest": str(marker_path),
        "build_manifest_sha256": sha256_file(marker_path),
        "history_output_root": company["history_output_root"],
        "history_root": str(history_root),
        "history_manifest": str(history_manifest),
        "history_manifest_sha256": sha256_file(history_manifest),
        "plan_sha256": company["plan_sha256"],
        "intake_sha256": company["intake_sha256"],
    }


def _validate_external_inputs(config: dict[str, Any]) -> dict[str, Any]:
    collection = _pin(
        config["collection"]["manifest"],
        config["collection"]["manifest_sha256"],
        "collection manifest",
    )
    status = collection_ops.read_universe_status(manifest_path=collection)
    if status.requested_companies != 50 or status.as_of_date != FINANCIAL_AS_OF:
        raise ValueError("collection is not an exact-50 parent")
    expected = {(row["ticker"], row["cik"]) for row in config["companies"]}
    actual = {(row.ticker, row.cik) for row in status.companies}
    if not expected <= actual or (
        config["collection_scope_mode"] == "FULL" and expected != actual
    ):
        raise ValueError("collection cohort differs from configured scope")
    by_identity = {(row.ticker, row.cik): row for row in status.companies}
    for identity in expected:
        row = by_identity[identity]
        if (
            row.state != "READY"
            or row.selected_filings != row.held_filings
            or row.pending_filings
            or row.failed_filings
        ):
            raise ValueError(f"{row.ticker}: scoped collection company is not READY")
    package_root = _directory(Path(config["package_view"]["root"]), "package view")
    package_manifest, _receipt = package_view.authenticated_json(
        package_root / package_view.MANIFEST_NAME,
        "package view manifest",
        config["package_view"]["manifest_sha256"],
    )
    if package_manifest.get("company_count") != 50:
        raise ValueError("package view is not exact-50")
    histories = {}
    history_builds = {}
    for company in config["companies"]:
        history_builds[company["ticker"]] = _validate_history_build_binding(
            config, company
        )
        root = _directory(Path(company["history_root"]), f"{company['ticker']} history")
        manifest = _manifest_path(root, "history_manifest.json")
        if sha256_file(manifest) != company["history_manifest_sha256"]:
            raise ValueError(f"{company['ticker']}: history manifest changed")
        histories[company["ticker"]] = str(manifest)
    return {
        "collection_manifest": str(collection),
        "package_view": str(package_root),
        "history_manifests": histories,
        "history_builds": history_builds,
        "first5_financial_acceptance": _validate_first5_acceptance(config),
    }


def _preflight_path(config: dict[str, Any]) -> Path:
    return Path(config["execution_root"]) / "preflight.json"


def preflight(config_path: Path) -> Path:
    config, config_sha = load_config(config_path)
    execution = Path(config["execution_root"]).absolute()
    if execution.exists() or execution.is_symlink():
        raise FileExistsError("financial execution root must be fresh")
    resource_root = _directory(Path(config["resource_root"]), "shared resource root")
    for output in config["outputs"].values():
        if Path(output).exists() or Path(output).is_symlink():
            raise FileExistsError(f"financial output must be fresh: {output}")
    external = _validate_external_inputs(config)
    if config["metadata"]["mode"] == "EXISTING_PUBLICATION":
        _metadata_root(config)
    execution.mkdir(parents=True)
    value = {
        "schema_version": PREFLIGHT_VERSION,
        "status": "PREPARED_SOURCE_ONLY",
        "config": {"path": str(Path(config_path).absolute()), "sha256": config_sha},
        "source": _verify_runtime(config),
        "external_inputs": external,
        "scope": {
            "mode": config["collection_scope_mode"],
            "companies": [
                {"ticker": row["ticker"], "cik": row["cik"]}
                for row in config["companies"]
            ],
            "parent_company_count": 50,
            "financial_as_of": FINANCIAL_AS_OF,
            "metadata_observation_cutoff": METADATA_CUTOFF,
        },
        "resources": {
            "root": str(resource_root),
            "process_tree_rss_kib": LIMIT_KIB,
            "polars_max_threads": POLARS_THREADS,
            "one_heavy_process": True,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "execution": "EACH_STAGE_REQUIRES_SEPARATE_EXACT_GO",
    }
    return _write_new(_preflight_path(config), value, "financial preflight")


def _validated_preflight(config_path: Path) -> tuple[dict[str, Any], str, Path]:
    config, config_sha = load_config(config_path)
    path = _preflight_path(config)
    value = _read_json(path, "financial preflight")
    if (
        value.get("schema_version") != PREFLIGHT_VERSION
        or value.get("status") != "PREPARED_SOURCE_ONLY"
        or value.get("config")
        != {"path": str(Path(config_path).absolute()), "sha256": config_sha}
        or value.get("source") != _verify_runtime(config)
    ):
        raise ValueError("financial preflight changed")
    if value.get("external_inputs") != _validate_external_inputs(config):
        raise ValueError("financial external inputs changed after preflight")
    return config, config_sha, path


def _receipt_path(config: dict[str, Any], stage: str) -> Path:
    return Path(config["execution_root"]) / "receipts" / f"{stage}.json"


def _request_path(config: dict[str, Any], stage: str) -> Path:
    return Path(config["execution_root"]) / "requests" / f"{stage}.json"


def _summary_path(config: dict[str, Any], stage: str) -> Path:
    return Path(config["execution_root"]) / "execution" / f"{stage}.summary.json"


def _output_paths(config: dict[str, Any], stage: str) -> list[Path]:
    return [Path(config["outputs"][key]).absolute() for key in OUTPUT_KEYS[stage]]


def _parent_receipts(config: dict[str, Any], stage: str) -> list[dict[str, str]]:
    result = []
    for parent in DEPENDENCIES[stage]:
        path = _regular(_receipt_path(config, parent), f"{parent} stage receipt")
        receipt = _read_json(path, f"{parent} stage receipt")
        if receipt.get("schema_version") != RECEIPT_VERSION or receipt.get("status") != "PASS":
            raise ValueError(f"{parent} stage is not PASS")
        _verify_output_receipt(receipt, parent)
        result.append({"stage": parent, "path": str(path), "sha256": sha256_file(path)})
    if stage != "metadata" and config["metadata"]["mode"] == "PUBLISH_EXACT50":
        path = _regular(_receipt_path(config, "metadata"), "metadata stage receipt")
        _verify_output_receipt(_read_json(path, "metadata stage receipt"), "metadata")
        if not any(row["stage"] == "metadata" for row in result):
            result.append({"stage": "metadata", "path": str(path), "sha256": sha256_file(path)})
    return sorted(result, key=lambda row: row["stage"])


def request_stage(config_path: Path, stage: str) -> Path:
    if stage not in STAGES:
        raise ValueError("unsupported financial stage")
    config, config_sha, preflight_file = _validated_preflight(config_path)
    acceptance = _validate_first5_acceptance(config)
    if stage == "metadata" and config["metadata"]["mode"] != "PUBLISH_EXACT50":
        raise ValueError("existing metadata publication does not require a stage")
    if _summary_path(config, stage).exists() or _receipt_path(config, stage).exists():
        raise ValueError("financial stage already attempted")
    outputs = _output_paths(config, stage)
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise FileExistsError("financial stage output is not fresh")
    request = {
        "schema_version": REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_GO",
        "stage": stage,
        "source_head": config["source"]["head"],
        "config_sha256": config_sha,
        "preflight_sha256": sha256_file(preflight_file),
        "scope_companies": [
            {"ticker": row["ticker"], "cik": row["cik"]}
            for row in config["companies"]
        ],
        "first5_financial_acceptance": acceptance,
        "parent_receipts": _parent_receipts(config, stage),
        "outputs": [str(path) for path in outputs],
    }
    return _write_new(_request_path(config, stage), request, "financial stage request")


def _expected_go(config: dict[str, Any], config_sha: str, stage: str) -> dict[str, Any]:
    acceptance = _validate_first5_acceptance(config)
    request_path = _regular(_request_path(config, stage), "financial stage request")
    request = _read_json(request_path, "financial stage request")
    expected_request = {
        "schema_version": REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_GO",
        "stage": stage,
        "source_head": config["source"]["head"],
        "config_sha256": config_sha,
        "preflight_sha256": sha256_file(_preflight_path(config)),
        "scope_companies": [
            {"ticker": row["ticker"], "cik": row["cik"]}
            for row in config["companies"]
        ],
        "first5_financial_acceptance": acceptance,
        "parent_receipts": _parent_receipts(config, stage),
        "outputs": [str(path) for path in _output_paths(config, stage)],
    }
    if request != expected_request:
        raise ValueError("financial stage request changed")
    return {
        "schema_version": GO_VERSION,
        "status": "GO",
        "stage": stage,
        "source_head": config["source"]["head"],
        "config_sha256": config_sha,
        "request_sha256": sha256_file(request_path),
        "scope_companies": request.get("scope_companies"),
        "first5_financial_acceptance": acceptance,
        "parent_receipts": _parent_receipts(config, stage),
        "outputs": [str(path) for path in _output_paths(config, stage)],
    }


def _validate_go(config_path: Path, stage: str, go_file: Path) -> dict[str, Any]:
    config, config_sha, _ = _validated_preflight(config_path)
    _validate_first5_acceptance(config)
    if _read_json(go_file, "financial stage GO") != _expected_go(
        config, config_sha, stage
    ):
        raise ValueError("financial stage GO does not exactly bind source, scope and parents")
    return config


def _config_file(config: dict[str, Any], name: str, value: dict[str, Any]) -> Path:
    return _write_new(
        Path(config["execution_root"]) / "configs" / f"{name}.json",
        value,
        f"{name} producer config",
    )


def _analysis_root(config: dict[str, Any], kind: str, ticker: str) -> Path:
    return Path(config["outputs"][kind]) / ticker


def _global_quarter_spine() -> list[dict[str, int]]:
    return [
        {"calendar_year": year, "calendar_quarter": quarter}
        for year, quarter in GLOBAL_QUARTER_SPINE
    ]


def _quarterly_global_quarter_spine() -> list[dict[str, int | str]]:
    return [
        {**bucket, "status": "COMPLETED_BUCKET"}
        for bucket in _global_quarter_spine()
    ]


def _run_metadata(config: dict[str, Any]) -> None:
    metadata = config["metadata"]
    if metadata["mode"] != "PUBLISH_EXACT50":
        raise ValueError("existing metadata does not have a publication stage")
    inputs = []
    cutoff = _timestamp(config["metadata_observation_cutoff"], "metadata cutoff")
    kdp_snapshot_path = None
    for row in metadata["snapshots"]:
        path = _pin(row["path"], row["sha256"], "metadata snapshot")
        if row["ticker"] == "KDP":
            kdp_snapshot_path = path
        inputs.append(
            company_metadata.SnapshotInput(
                path=path,
                observed_at=_timestamp(row["observed_at"], "metadata observed_at"),
                source=row.get("source", "sec_submissions"),
                source_url=row.get("source_url"),
            )
        )
    kdp = metadata["kdp_acquisition_evidence"]
    evidence = _read_json(
        _pin(kdp["path"], kdp["sha256"], "KDP acquisition evidence"),
        "KDP acquisition evidence",
    )
    if (
        not _has_prepare_completion(evidence)
        or kdp_snapshot_path is None
        or not _contains_string(evidence, str(kdp_snapshot_path))
    ):
        raise ValueError(
            "KDP acquisition completion or root submissions path is absent from pinned evidence"
        )
    built = company_metadata.build_company_metadata(inputs, cutoff=cutoff)
    published = company_metadata.publish_company_metadata(
        built, Path(config["outputs"]["metadata"])
    )
    reader = company_metadata.CompanyMetadataReader(published.root)
    status = collection_ops.read_universe_status(
        manifest_path=Path(config["collection"]["manifest"])
    )
    _verify_exact50_metadata_membership(reader.list_companies(), status.companies)


def _verify_exact50_metadata_membership(
    metadata_companies: Sequence[Any], collection_companies: Sequence[Any]
) -> None:
    if len(metadata_companies) != 50 or len(collection_companies) != 50:
        raise ValueError("fresh metadata publication is not exact-50")
    metadata_ciks = {row.cik for row in metadata_companies}
    expected_ciks = {row.cik for row in collection_companies}
    metadata_identities = {
        (ticker, row.cik) for row in metadata_companies for ticker in row.tickers
    }
    expected_identities = {(row.ticker, row.cik) for row in collection_companies}
    if metadata_ciks != expected_ciks or not expected_identities <= metadata_identities:
        raise ValueError("fresh metadata identity differs from exact-50 collection")


def _run_analysis(config: dict[str, Any], *, quarterly: bool) -> None:
    key = "quarterly_analysis" if quarterly else "annual_analysis"
    parent = Path(config["outputs"][key])
    parent.mkdir(parents=True)
    for company in config["companies"]:
        years = (
            company["quarter_input_years"] if quarterly else company["input_years"]
        )
        analysis.prepare_analysis(
            publication=Path(company["history_root"]),
            destination=parent / company["ticker"],
            tickers=(company["ticker"],),
            configuration=(
                None
                if quarterly
                else {company["ticker"]: {"core_rows": screening.expanded_analysis_profile()}}
            ),
            fiscal_start=years[0],
            fiscal_end=years[-1],
            period_mode="QUARTERLY" if quarterly else "ANNUAL",
            include_year_end_balances=not quarterly,
            include_quarter_source_evidence=quarterly,
        )


def _run_quality(config: dict[str, Any]) -> None:
    package_view.verify_package_view(
        Path(config["package_view"]["root"]),
        config["package_view"]["manifest_sha256"],
    )
    provenance = [
        {
            "ticker": row["ticker"],
            "cik": row["cik"],
            "collector_source_commit_sha": row["collector_source_commit_sha"],
            "plan_sha256": row["plan_sha256"],
            "intake_sha256": row["intake_sha256"],
            "history_manifest_sha256": row["history_manifest_sha256"],
        }
        for row in config["companies"]
    ]
    quality_config = _config_file(
        config,
        "quality",
        {
            "schema_version": metric_quality.CONFIG_SCHEMA_VERSION,
            "financial_as_of": FINANCIAL_AS_OF,
            "collection_scope_companies": [
                {"ticker": row["ticker"], "cik": row["cik"]}
                for row in config["companies"]
            ],
            "source_provenance": provenance,
        },
    )
    metric_quality.prepare_generic_metric_quality(
        config_path=quality_config,
        collection_manifest=Path(config["collection"]["manifest"]),
        package_root=Path(config["package_view"]["root"]),
        history_manifests={
            row["ticker"]: Path(row["history_root"]) / "history_manifest.json"
            for row in config["companies"]
        },
        source_index_destination=Path(config["outputs"]["quality_indexes"]),
        source_binding_destination=Path(config["outputs"]["quality_bindings"]),
        destination=Path(config["outputs"]["quality"]),
        producer_revision=config["source"]["head"],
    )


def _run_identity(config: dict[str, Any]) -> None:
    metadata_root = _metadata_root(config)
    quality_root = Path(config["outputs"]["quality"])
    identity_config = _config_file(
        config,
        "identity",
        {
            "schema_version": metric_identity.CONFIG_VERSION,
            "source_kind": metric_identity.SOURCE_KIND,
            "universe_id": config["universe_id"],
            "financial_as_of": FINANCIAL_AS_OF,
            "metadata_observation_cutoff": METADATA_CUTOFF,
            "annual_window": {"input_fiscal_years": 5, "display_fiscal_years": 4},
            "global_quarter_spine": _global_quarter_spine(),
            "collection_scope_mode": config["collection_scope_mode"],
            "collection_scope_companies": [
                {"ticker": row["ticker"], "cik": row["cik"]}
                for row in config["companies"]
            ],
            "collection_manifest": config["collection"]["manifest"],
            "collection_manifest_sha256": config["collection"]["manifest_sha256"],
            "metadata_root": str(metadata_root),
            "metadata_manifest_sha256": sha256_file(
                metadata_root / company_metadata.MANIFEST_NAME
            ),
            "quality_root": str(quality_root),
            "quality_manifest_sha256": sha256_file(
                quality_root / metric_quality.MANIFEST_NAME
            ),
            "companies": [
                {
                    "ticker": row["ticker"],
                    "cik": row["cik"],
                    "input_years": row["input_years"],
                    "display_years": row["display_years"],
                    "history_root": row["history_root"],
                    "history_manifest_sha256": row["history_manifest_sha256"],
                    "annual_analysis_root": str(
                        _analysis_root(config, "annual_analysis", row["ticker"])
                    ),
                    "annual_analysis_manifest_sha256": sha256_file(
                        _analysis_root(config, "annual_analysis", row["ticker"])
                        / "analysis_manifest.json"
                    ),
                    "quarterly_analysis_root": str(
                        _analysis_root(config, "quarterly_analysis", row["ticker"])
                    ),
                    "quarterly_analysis_manifest_sha256": sha256_file(
                        _analysis_root(config, "quarterly_analysis", row["ticker"])
                        / "analysis_manifest.json"
                    ),
                }
                for row in config["companies"]
            ],
        },
    )
    metric_identity.publish_generic_metric_identity(
        identity_config, Path(config["outputs"]["identity"])
    )


def _run_annual_metrics(config: dict[str, Any]) -> None:
    identity_root = Path(config["outputs"]["identity"])
    metric_config = _config_file(
        config,
        "annual-metrics",
        {
            "schema_version": screening.EXPLICIT_IDENTITY_CONFIG_VERSION,
            "financial_as_of": FINANCIAL_AS_OF,
            "identity_source": {
                "kind": metric_identity.SOURCE_KIND,
                "root": str(identity_root),
                "manifest_sha256": sha256_file(
                    identity_root / metric_identity.MANIFEST_NAME
                ),
            },
            "companies": [
                {
                    "ticker": row["ticker"],
                    "cik": row["cik"],
                    "analysis_root": str(
                        _analysis_root(config, "annual_analysis", row["ticker"])
                    ),
                    "analysis_manifest_sha256": sha256_file(
                        _analysis_root(config, "annual_analysis", row["ticker"])
                        / "analysis_manifest.json"
                    ),
                    "input_years": row["input_years"],
                    "display_years": row["display_years"],
                }
                for row in config["companies"]
            ],
        },
    )
    screening.publish_screening_metrics(
        metric_config, Path(config["outputs"]["annual_metrics"])
    )


def _run_annual_dataset(config: dict[str, Any]) -> None:
    metrics_root, identity_root = (
        Path(config["outputs"]["annual_metrics"]),
        Path(config["outputs"]["identity"]),
    )
    path = _config_file(
        config,
        "annual-dataset-v2",
        {
            "schema_version": dataset_v2.EXPLICIT_IDENTITY_CONFIG_VERSION,
            "dataset_id": config["dataset_id"],
            "fixture_kind": "ACTUAL_PREPARED",
            "financial_as_of": FINANCIAL_AS_OF,
            "metric_root": str(metrics_root),
            "metric_manifest_sha256": sha256_file(
                metrics_root / screening.MANIFEST
            ),
            "identity_source": {
                "kind": metric_identity.SOURCE_KIND,
                "root": str(identity_root),
                "manifest_sha256": sha256_file(
                    identity_root / metric_identity.MANIFEST_NAME
                ),
            },
        },
    )
    dataset_v2.publish_screening_dataset_v2(
        path, Path(config["outputs"]["annual_dataset_v2"])
    )


def _run_quarterly_metrics(config: dict[str, Any]) -> None:
    annual_root = Path(config["outputs"]["annual_metrics"])
    path = _config_file(
        config,
        "quarterly-metrics",
        {
            "schema_version": quarterly_screening.CONFIG_VERSION,
            "financial_as_of": FINANCIAL_AS_OF,
            "fixture_kind": "ACTUAL_PREPARED",
            "source_commit_sha": config["source"]["head"],
            "annual_metric_root": str(annual_root),
            "annual_metric_manifest_sha256": sha256_file(
                annual_root / screening.MANIFEST
            ),
            "global_quarter_spine": _quarterly_global_quarter_spine(),
            "companies": [
                {
                    "ticker": row["ticker"],
                    "cik": row["cik"],
                    "analysis_root": str(
                        _analysis_root(config, "quarterly_analysis", row["ticker"])
                    ),
                    "analysis_manifest_sha256": sha256_file(
                        _analysis_root(config, "quarterly_analysis", row["ticker"])
                        / "analysis_manifest.json"
                    ),
                }
                for row in config["companies"]
            ],
        },
    )
    quarterly_screening.publish_quarterly_screening_metrics(
        path, Path(config["outputs"]["quarterly_metrics"])
    )


def _run_combined_dataset(config: dict[str, Any]) -> None:
    annual, quarterly = (
        Path(config["outputs"]["annual_dataset_v2"]),
        Path(config["outputs"]["quarterly_metrics"]),
    )
    path = _config_file(
        config,
        "combined-dataset-v3",
        {
            "schema_version": dataset_v3.CONFIG_VERSION,
            "dataset_id": config["dataset_id"],
            "fixture_kind": "ACTUAL_PREPARED",
            "annual_dataset_root": str(annual),
            "annual_manifest_sha256": sha256_file(annual / dataset_v2.MANIFEST),
            "quarterly_metric_root": str(quarterly),
            "quarterly_manifest_sha256": sha256_file(
                quarterly / quarterly_screening.MANIFEST
            ),
        },
    )
    dataset_v3.publish_screening_dataset_v3(
        path, Path(config["outputs"]["combined_dataset_v3"])
    )


STAGE_HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "metadata": _run_metadata,
    "annual-analysis": lambda config: _run_analysis(config, quarterly=False),
    "quarterly-analysis": lambda config: _run_analysis(config, quarterly=True),
    "quality": _run_quality,
    "identity": _run_identity,
    "annual-metrics": _run_annual_metrics,
    "annual-dataset-v2": _run_annual_dataset,
    "quarterly-metrics": _run_quarterly_metrics,
    "combined-dataset-v3": _run_combined_dataset,
}


def _has_prepare_completion(value: Any) -> bool:
    if isinstance(value, dict):
        operation = any(
            item == "prepare"
            for key, item in value.items()
            if key in {"operation", "action", "stage", "name"}
        )
        if operation and value.get("completed_at") == KDP_ACQUISITION_COMPLETED_AT:
            return True
        return any(_has_prepare_completion(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_prepare_completion(item) for item in value)
    return False


def _contains_string(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, dict):
        return any(_contains_string(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_string(item, expected) for item in value)
    return False


def _output_receipts(config: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    result = []
    for root in _output_paths(config, stage):
        root = _directory(root, f"{stage} output")
        files = [
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
        if not files or any(path.is_symlink() for path in root.rglob("*")):
            raise ValueError(f"{stage} output is empty or contains symlinks")
        result.append({"root": str(root), "files": files})
    return result


def _verify_output_receipt(receipt: dict[str, Any], stage: str) -> None:
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError(f"{stage} output receipt is missing")
    for output in outputs:
        root = _directory(Path(output.get("root", "")), f"{stage} receipt root")
        declared = output.get("files")
        if not isinstance(declared, list) or not declared:
            raise ValueError(f"{stage} receipt file set is missing")
        expected = set()
        for row in declared:
            relative = Path(row.get("relative_path", ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"{stage} receipt path is unsafe")
            path = _regular(root / relative, f"{stage} receipt file")
            if (
                str(path) != row.get("path")
                or sha256_file(path) != row.get("sha256")
                or path.stat().st_size != row.get("size")
            ):
                raise ValueError(f"{stage} output changed")
            expected.add(str(relative))
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if actual != expected or any(path.is_symlink() for path in root.rglob("*")):
            raise ValueError(f"{stage} output file set changed")


def _receive_supervisor(config: dict[str, Any]) -> None:
    try:
        descriptor = int(os.environ["SEC_XBRL_FINANCIAL_SUPERVISOR_FD"])
        parent = int(os.environ["SEC_XBRL_FINANCIAL_SUPERVISOR_PID"])
        expected = os.environ["SEC_XBRL_FINANCIAL_SUPERVISOR_SHA256"]
    except (KeyError, ValueError) as exc:
        raise PermissionError("financial worker requires supervisor capability") from exc
    if os.getppid() != parent:
        raise PermissionError("financial worker supervisor identity differs")
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        token = stream.read(33)
    if len(token) != 32 or hashlib.sha256(token).hexdigest() != expected:
        raise PermissionError("financial worker supervisor capability is invalid")
    if os.environ.get("POLARS_MAX_THREADS") != str(POLARS_THREADS):
        raise PermissionError("financial worker Polars limit differs")
    try:
        with resource_ops.heavy_lock(Path(config["resource_root"])):
            pass
    except ValueError as exc:
        if str(exc) != "another heavy operation is active":
            raise
    else:
        raise PermissionError("financial worker requires the parent-held heavy lock")


def _worker(config_path: Path, stage: str, go_file: Path) -> Path:
    config = _validate_go(config_path, stage, go_file)
    _validate_first5_acceptance(config)
    resource_ops.install_parent_death_guard()
    _receive_supervisor(config)
    STAGE_HANDLERS[stage](config)
    outputs = _output_receipts(config, stage)
    receipt = {
        "schema_version": RECEIPT_VERSION,
        "status": "PASS",
        "stage": stage,
        "source_head": config["source"]["head"],
        "go_sha256": sha256_file(go_file),
        "outputs": outputs,
    }
    return _write_new(_receipt_path(config, stage), receipt, "financial stage receipt")


def _worker_environment(*, read_fd: int, token: bytes) -> dict[str, str]:
    parent = str(os.getpid())
    env = os.environ.copy()
    env.update(
        POLARS_MAX_THREADS=str(POLARS_THREADS),
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        SEC_XBRL_FINANCIAL_SUPERVISOR_FD=str(read_fd),
        SEC_XBRL_FINANCIAL_SUPERVISOR_PID=parent,
        SEC_XBRL_FINANCIAL_SUPERVISOR_SHA256=hashlib.sha256(token).hexdigest(),
        SEC_XBRL_T3V2_SUPERVISOR_PID=parent,
    )
    return env


def run_stage(config_path: Path, stage: str, go_file: Path) -> Path:
    config = _validate_go(config_path, stage, go_file)
    summary = _summary_path(config, stage)
    if summary.exists() or _receipt_path(config, stage).exists():
        raise ValueError("financial stage cannot be retried or overwritten")
    if any(path.exists() or path.is_symlink() for path in _output_paths(config, stage)):
        raise FileExistsError("financial stage output is not fresh")
    summary.parent.mkdir(parents=True, exist_ok=True)
    log, samples = summary.with_suffix(".log"), summary.with_suffix(".rss.jsonl")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--config",
        str(Path(config_path).absolute()),
        "--stage",
        stage,
        "--go-file",
        str(Path(go_file).absolute()),
    ]
    token = os.urandom(32)
    read_fd, write_fd = os.pipe()
    env = _worker_environment(read_fd=read_fd, token=token)
    process = None
    started = time.monotonic()
    try:
        with (
            resource_ops.heavy_lock(Path(config["resource_root"])),
            log.open("x", encoding="utf-8") as output,
            samples.open("x", encoding="utf-8") as rss,
        ):
            try:
                process = subprocess.Popen(
                    command,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=env,
                    pass_fds=(read_fd,),
                )
            finally:
                os.close(read_fd)
            try:
                os.write(write_fd, token)
            finally:
                os.close(write_fd)
            code, peak, stopped, elapsed = resource_ops.supervise_owned_process(
                process,
                rss,
                limit_kib=LIMIT_KIB,
                timeout_seconds=TIMEOUT_SECONDS,
            )
    except BaseException as exc:
        for descriptor in (read_fd, write_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if process is not None and process.poll() is None:
            resource_ops.terminate_owned_process_group(process)
        _write_new(
            summary,
            {
                "schema_version": RESOURCE_VERSION,
                "status": "SUPERVISOR_INTERRUPTED",
                "stage": stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "child_reaped": process is None or process.poll() is not None,
                "log": str(log),
                "samples": str(samples),
            },
            "financial failure summary",
        )
        raise
    result = {
        "schema_version": RESOURCE_VERSION,
        "status": stopped or ("PASS" if code == 0 else "FAIL"),
        "stage": stage,
        "returncode": code,
        "elapsed_seconds": round(elapsed, 3),
        "peak_process_tree_rss_kib": peak,
        "limit_kib": LIMIT_KIB,
        "timeout_seconds": TIMEOUT_SECONDS,
        "command": command,
        "log": str(log),
        "samples": str(samples),
    }
    _write_new(summary, result, "financial resource summary")
    if result["status"] != "PASS":
        raise RuntimeError(f"financial stage failed: {result['status']}")
    return _regular(_receipt_path(config, stage), "financial stage receipt")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("--config", type=Path, required=True)
    request = commands.add_parser("request-stage")
    request.add_argument("--config", type=Path, required=True)
    request.add_argument("--stage", choices=STAGES, required=True)
    run = commands.add_parser("run-stage")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--stage", choices=STAGES, required=True)
    run.add_argument("--go-file", type=Path, required=True)
    worker = commands.add_parser("_worker")
    worker.add_argument("--config", type=Path, required=True)
    worker.add_argument("--stage", choices=STAGES, required=True)
    worker.add_argument("--go-file", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "preflight":
        result = preflight(args.config)
    elif args.command == "request-stage":
        result = request_stage(args.config, args.stage)
    elif args.command == "run-stage":
        result = run_stage(args.config, args.stage, args.go_file)
    else:
        result = _worker(args.config, args.stage, args.go_file)
    print(json.dumps({"path": str(result), "sha256": sha256_file(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
