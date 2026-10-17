#!/usr/bin/env python3
"""Source-pinned, fail-closed History recovery orchestration."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sec_xbrl import collection_operations as ops
from sec_xbrl import history
from tools import universe50_t3v2_ops as resource_ops

CONFIG_VERSION = "universe50-history-recovery-config-v1"
PREFLIGHT_VERSION = "universe50-history-recovery-preflight-v1"
REQUEST_VERSION = "universe50-history-recovery-request-v1"
GO_VERSION = "universe50-history-recovery-go-v1"
RECEIPT_VERSION = "universe50-history-recovery-receipt-v1"
RESOURCE_VERSION = "universe50-history-recovery-resource-run-v1"
ENGINE_ACCEPTANCE_VERSION = "lead-history-engine-source-acceptance-v1"
ENGINE_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_HISTORY_ENGINE_SOURCE_AND_SYNTHETIC"
FINANCIAL_ACCEPTANCE_VERSION = "universe50-first5-financial-acceptance-v1"
FINANCIAL_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_FIRST5_FINANCIAL"
RUNNER_BASE_SHA = "9b6e7ec906382fba92adb5209c5b439fc7d7d6ba"
ENGINE_BASE_SHA = "8a1b40ab1008fb9109a27b2a5bcea02a257e1694"
FINANCIAL_SOURCE_SHA = RUNNER_BASE_SHA
GRAPH_RULE_VERSION = "analysis-t3-exploration-graph-v2"
FINANCIAL_AS_OF = "2026-10-10"
METADATA_CUTOFF = "2026-10-13T23:59:59Z"
FIRST5 = ("TXN", "HD", "JNJ", "CVX", "NEE")
LIMIT_KIB = 16 * 1024 * 1024
POLARS_THREADS = 2
TIMEOUT_SECONDS = 10_800
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
RUN_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{5,79}$")
ENGINE_MODULES = {
    "history": "src/sec_xbrl/history.py",
    "fiscal_time_series": "src/sec_xbrl/analytics/fiscal_time_series.py",
    "company_analysis_panel": "src/sec_xbrl/analytics/company_analysis_panel.py",
    "collection_operations": "src/sec_xbrl/collection_operations.py",
    "exploration_graph": "src/sec_xbrl/longitudinal/exploration_graph.py",
    "longitudinal_materialization": "src/sec_xbrl/longitudinal/materialization.py",
    "history_quarters": "src/sec_xbrl/analytics/history_quarters.py",
}
ENGINE_IMPORTS = {
    "history": "sec_xbrl.history",
    "fiscal_time_series": "sec_xbrl.analytics.fiscal_time_series",
    "company_analysis_panel": "sec_xbrl.analytics.company_analysis_panel",
    "collection_operations": "sec_xbrl.collection_operations",
    "exploration_graph": "sec_xbrl.longitudinal.exploration_graph",
    "longitudinal_materialization": "sec_xbrl.longitudinal.materialization",
    "history_quarters": "sec_xbrl.analytics.history_quarters",
}
RUNNER_MODULES = {
    "runner": "tools/universe50_history_recovery_ops.py",
    "resource_ops": "tools/universe50_t3v2_ops.py",
}
FINANCIAL_STAGES = {
    "annual-analysis",
    "quarterly-analysis",
    "quality",
    "identity",
    "annual-metrics",
    "annual-dataset-v2",
    "quarterly-metrics",
    "combined-dataset-v3",
}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _write_new(path: Path, value: dict[str, Any], label: str) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{label} must be new: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase Git SHA-1")
    return value


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return Path(value)


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


def _pin(declaration: Any, label: str) -> Path:
    if not isinstance(declaration, dict) or set(declaration) != {"path", "sha256"}:
        raise ValueError(f"{label} requires exact path and SHA-256")
    path = _regular(_absolute(declaration["path"], label), label)
    if _sha256(path) != _sha(declaration["sha256"], label):
        raise ValueError(f"{label} hash differs")
    return path


def _git_state(checkout: Path, expected: str, label: str) -> dict[str, str]:
    checkout = _directory(checkout, f"{label} checkout")
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
    if head != expected or dirty:
        raise ValueError(f"{label} checkout must be clean at its exact configured HEAD")
    return {"checkout": str(checkout), "head": head}


def _validate_companies(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != 50:
        raise ValueError("recovery config requires exact-50 company identities")
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"ticker", "cik"}:
            raise ValueError("company identity must contain exact ticker and CIK fields")
        ticker, cik = row["ticker"], row["cik"]
        if (
            not isinstance(ticker, str)
            or ticker != ticker.upper()
            or not ticker
            or not isinstance(cik, str)
            or len(cik) != 10
            or not cik.isdigit()
        ):
            raise ValueError("company identity is malformed")
        result.append({"ticker": ticker, "cik": cik})
    if len({row["ticker"] for row in result}) != 50 or len(
        {row["cik"] for row in result}
    ) != 50:
        raise ValueError("exact-50 company identities must be unique")
    if "PEP" in {row["ticker"] for row in result} or "KDP" not in {
        row["ticker"] for row in result
    }:
        raise ValueError("exact-50 membership must exclude PEP and include KDP")
    return result


def _validate_shape(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {
        "schema_version",
        "financial_as_of",
        "first5",
        "runner",
        "engine",
        "collection",
        "target",
        "execution_root",
        "resource_root",
        "limits",
        "first5_financial_acceptance",
    }:
        raise ValueError("History recovery config shape differs")
    if value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported History recovery config")
    if value.get("financial_as_of") != FINANCIAL_AS_OF:
        raise ValueError("History recovery financial cutoff differs")
    if value.get("first5") != list(FIRST5):
        raise ValueError("History recovery first-five cohort differs")
    if value.get("limits") != {
        "process_tree_rss_kib": LIMIT_KIB,
        "polars_max_threads": POLARS_THREADS,
        "one_heavy_process": True,
        "timeout_seconds": TIMEOUT_SECONDS,
    }:
        raise ValueError("History recovery resource limits differ")
    runner = value.get("runner")
    if not isinstance(runner, dict) or set(runner) != {
        "checkout",
        "head",
        "module_sha256s",
    }:
        raise ValueError("runner source declaration differs")
    _absolute(runner["checkout"], "runner checkout")
    _git_sha(runner["head"], "runner HEAD")
    modules = runner.get("module_sha256s")
    if not isinstance(modules, dict) or set(modules) != set(RUNNER_MODULES):
        raise ValueError("runner module pins differ")
    for name in RUNNER_MODULES:
        _sha(modules[name], f"runner module {name}")
    engine = value.get("engine")
    if not isinstance(engine, dict) or set(engine) != {
        "checkout",
        "head",
        "source_acceptance",
    }:
        raise ValueError("engine source declaration differs")
    _absolute(engine["checkout"], "engine checkout")
    _git_sha(engine["head"], "engine HEAD")
    if not isinstance(engine["source_acceptance"], dict):
        raise TypeError("engine source acceptance is required")
    collection = value.get("collection")
    if not isinstance(collection, dict) or set(collection) != {
        "manifest",
        "manifest_sha256",
        "candidate",
        "candidate_sha256",
        "universe_id",
        "parent_company_count",
        "selected_filings",
        "companies",
    }:
        raise ValueError("collection declaration differs")
    _absolute(collection["manifest"], "collection manifest")
    _sha(collection["manifest_sha256"], "collection manifest")
    _absolute(collection["candidate"], "candidate")
    _sha(collection["candidate_sha256"], "candidate")
    if (
        not isinstance(collection["universe_id"], str)
        or not collection["universe_id"]
        or collection["parent_company_count"] != 50
        or collection["selected_filings"] != 1097
    ):
        raise ValueError("collection exact-50 scope differs")
    companies = _validate_companies(collection["companies"])
    target = value.get("target")
    expected_target = {
        "ticker",
        "cik",
        "plan_sha256",
        "intake_sha256",
        "selected_filings",
        "run_version",
        "history_parent",
        "history_basename",
        "approved_prior_failed_attempts",
        "abandoned_output_roots",
    }
    if not isinstance(target, dict) or set(target) != expected_target:
        raise ValueError("History recovery target declaration differs")
    ticker, cik = target["ticker"], target["cik"]
    if {"ticker": ticker, "cik": cik} not in companies:
        raise ValueError("History recovery target is outside exact-50")
    _sha(target["plan_sha256"], "target plan")
    _sha(target["intake_sha256"], "target intake")
    if type(target["selected_filings"]) is not int or target["selected_filings"] <= 0:
        raise ValueError("target selected filing count differs")
    run_version, basename = target["run_version"], target["history_basename"]
    if (
        not isinstance(run_version, str)
        or RUN_VERSION.fullmatch(run_version) is None
        or not isinstance(basename, str)
        or basename != f"{ticker}-history-recovery-{run_version}"
    ):
        raise ValueError("History recovery requires a new explicit run version and basename")
    _absolute(target["history_parent"], "history parent")
    prior = target["approved_prior_failed_attempts"]
    abandoned = target["abandoned_output_roots"]
    if not isinstance(prior, list) or not isinstance(abandoned, list):
        raise TypeError("prior failure declarations must be lists")
    for declaration in prior:
        if not isinstance(declaration, dict) or set(declaration) != {"path", "sha256"}:
            raise ValueError("prior failed attempt declaration differs")
        _absolute(declaration["path"], "prior failed attempt")
        _sha(declaration["sha256"], "prior failed attempt")
    for root in abandoned:
        _absolute(root, "abandoned output root")
    if bool(prior) != bool(abandoned):
        raise ValueError("failed attempts and abandoned outputs must be declared together")
    if prior and ticker != "JNJ":
        raise ValueError("only the approved JNJ failed recovery may carry prior attempts")
    execution_root = _absolute(value.get("execution_root"), "execution root")
    resource_root = _absolute(value.get("resource_root"), "resource root")
    collection_root = Path(collection["manifest"]).absolute().parent
    if resource_root != collection_root:
        raise ValueError("History recovery must share the collection heavy lock")
    acceptance = value.get("first5_financial_acceptance")
    if ticker in FIRST5:
        if acceptance is not None:
            raise ValueError("first-five recovery cannot declare bulk financial acceptance")
    elif not isinstance(acceptance, dict):
        raise ValueError("later-45 recovery requires canonical first-five acceptance")
    return {
        **value,
        "collection": {**collection, "companies": companies},
        "execution_root": str(execution_root),
        "resource_root": str(resource_root),
    }


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    path = _regular(path, "History recovery config")
    return _validate_shape(_read_json(path, "History recovery config")), _sha256(path)


def _verify_runner_source(config: dict[str, Any]) -> dict[str, Any]:
    declaration = config["runner"]
    checkout = _directory(Path(declaration["checkout"]), "runner checkout")
    state = _git_state(checkout, declaration["head"], "runner")
    ancestor = subprocess.run(
        ["git", "-C", str(checkout), "merge-base", "--is-ancestor", RUNNER_BASE_SHA, declaration["head"]],
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("runner source is not based on accepted financial 9b")
    files = {}
    for name, relative in RUNNER_MODULES.items():
        path = _regular(checkout / relative, f"runner module {name}")
        digest = _sha256(path)
        if digest != declaration["module_sha256s"][name]:
            raise ValueError(f"runner module changed: {name}")
        files[name] = {"path": str(path), "sha256": digest}
    imported = {
        "runner": Path(__file__).resolve(),
        "resource_ops": Path(resource_ops.__file__).resolve(),
    }
    if any(imported[name] != Path(files[name]["path"]) for name in imported):
        raise ValueError("recovery runner imports are outside configured runner checkout")
    return {**state, "base": RUNNER_BASE_SHA, "files": files}


def _verify_engine_source(config: dict[str, Any]) -> dict[str, Any]:
    declaration = config["engine"]
    acceptance_path = _pin(declaration["source_acceptance"], "engine source acceptance")
    acceptance = _read_json(acceptance_path, "engine source acceptance")
    if set(acceptance) != {
        "schema_version",
        "status",
        "engine_source_head",
        "engine_base_sha",
        "graph_rule_version",
        "module_sha256s",
        "independent_report",
    }:
        raise ValueError("engine source acceptance shape differs")
    if (
        acceptance["schema_version"] != ENGINE_ACCEPTANCE_VERSION
        or acceptance["status"] != ENGINE_ACCEPTANCE_STATUS
        or acceptance["engine_source_head"] != declaration["head"]
        or acceptance["engine_base_sha"] != ENGINE_BASE_SHA
        or acceptance["graph_rule_version"] != GRAPH_RULE_VERSION
    ):
        raise ValueError("engine source acceptance identity differs")
    report = _pin(acceptance["independent_report"], "engine independent report")
    hashes = acceptance["module_sha256s"]
    if not isinstance(hashes, dict) or set(hashes) != set(ENGINE_MODULES):
        raise ValueError("engine accepted module set differs")
    checkout = _directory(Path(declaration["checkout"]), "engine checkout")
    state = _git_state(checkout, declaration["head"], "engine")
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "merge-base",
            "--is-ancestor",
            ENGINE_BASE_SHA,
            declaration["head"],
        ],
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("engine source is not based on accepted 8a")
    files = {}
    for name, relative in ENGINE_MODULES.items():
        path = _regular(checkout / relative, f"engine module {name}")
        digest = _sha256(path)
        if digest != _sha(hashes[name], f"engine module {name}"):
            raise ValueError(f"engine module changed: {name}")
        imported = Path(importlib.import_module(ENGINE_IMPORTS[name]).__file__).resolve()
        if imported != path:
            raise ValueError(f"engine import path differs: {name}")
        files[name] = {"path": str(path), "sha256": digest}
    return {
        **state,
        "base": ENGINE_BASE_SHA,
        "acceptance": {"path": str(acceptance_path), "sha256": _sha256(acceptance_path)},
        "independent_report": {"path": str(report), "sha256": _sha256(report)},
        "files": files,
    }


def _verify_output_receipt(receipt: dict[str, Any], stage: str) -> list[Path]:
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError(f"accepted {stage} output receipt is missing")
    roots = []
    for output in outputs:
        if not isinstance(output, dict) or set(output) != {"root", "files"}:
            raise ValueError(f"accepted {stage} output shape differs")
        root = _directory(_absolute(output["root"], f"accepted {stage} output"), f"accepted {stage} output")
        declared = output["files"]
        if not isinstance(declared, list) or not declared:
            raise ValueError(f"accepted {stage} output files are missing")
        expected = set()
        for row in declared:
            if not isinstance(row, dict):
                raise TypeError(f"accepted {stage} output file differs")
            relative = Path(str(row.get("relative_path", "")))
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"accepted {stage} output path is unsafe")
            path = _regular(root / relative, f"accepted {stage} output file")
            if (
                str(path) != row.get("path")
                or _sha256(path) != row.get("sha256")
                or path.stat().st_size != row.get("size")
            ):
                raise ValueError(f"accepted {stage} output file changed")
            expected.add(str(relative))
        if len(expected) != len(declared):
            raise ValueError(f"accepted {stage} output contains duplicate file declarations")
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if actual != expected or any(path.is_symlink() for path in root.rglob("*")):
            raise ValueError(f"accepted {stage} output fileset changed")
        roots.append(root)
    return roots


def _verify_financial_acceptance(config: dict[str, Any]) -> dict[str, Any] | None:
    ticker = config["target"]["ticker"]
    if ticker in FIRST5:
        return None
    path = _pin(config["first5_financial_acceptance"], "first-five financial acceptance")
    value = _read_json(path, "first-five financial acceptance")
    if set(value) != {
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
    }:
        raise ValueError("first-five financial acceptance shape differs")
    cohort = [
        row
        for ticker_name in FIRST5
        for row in config["collection"]["companies"]
        if row["ticker"] == ticker_name
    ]
    expected_collection = {
        "manifest": config["collection"]["manifest"],
        "manifest_sha256": config["collection"]["manifest_sha256"],
        "parent_company_count": 50,
    }
    if (
        value["schema_version"] != FINANCIAL_ACCEPTANCE_VERSION
        or value["status"] != FINANCIAL_ACCEPTANCE_STATUS
        or value["source_head"] != FINANCIAL_SOURCE_SHA
        or value["financial_as_of"] != FINANCIAL_AS_OF
        or value["metadata_observation_cutoff"] != METADATA_CUTOFF
        or value["collection"] != expected_collection
        or value["companies"] != cohort
    ):
        raise ValueError("first-five financial acceptance scope differs")
    first5_path = _pin(value["first5_config"], "accepted first-five config")
    first5 = _read_json(first5_path, "accepted first-five config")
    first5_companies = first5.get("companies")
    first5_by_ticker = (
        {row.get("ticker"): row for row in first5_companies}
        if isinstance(first5_companies, list)
        and all(isinstance(row, dict) for row in first5_companies)
        else {}
    )
    if (
        first5.get("schema_version") != "universe50-financial-ops-config-v1"
        or first5.get("collection_scope_mode") != "EXPLICIT_SUBSET"
        or first5.get("financial_as_of") != FINANCIAL_AS_OF
        or first5.get("metadata_observation_cutoff") != METADATA_CUTOFF
        or first5.get("collection") != expected_collection
        or first5.get("source", {}).get("head") != FINANCIAL_SOURCE_SHA
        or not isinstance(first5_companies, list)
        or len(first5_companies) != len(FIRST5)
        or set(first5_by_ticker) != set(FIRST5)
        or [
            {
                "ticker": ticker_name,
                "cik": first5_by_ticker.get(ticker_name, {}).get("cik"),
            }
            for ticker_name in FIRST5
        ]
        != cohort
    ):
        raise ValueError("accepted first-five config differs")
    receipts = value["stage_receipts"]
    if not isinstance(receipts, dict) or not FINANCIAL_STAGES <= set(receipts) or set(
        receipts
    ) - (FINANCIAL_STAGES | {"metadata"}):
        raise ValueError("first-five financial stage receipt set differs")
    output_roots: list[Path] = []
    receipt_bindings = {}
    for stage, declaration in sorted(receipts.items()):
        receipt_path = _pin(declaration, f"accepted {stage} receipt")
        receipt = _read_json(receipt_path, f"accepted {stage} receipt")
        if (
            receipt.get("schema_version") != "universe50-financial-stage-receipt-v1"
            or receipt.get("status") != "PASS"
            or receipt.get("stage") != stage
            or receipt.get("source_head") != FINANCIAL_SOURCE_SHA
            or SHA256.fullmatch(str(receipt.get("go_sha256", ""))) is None
        ):
            raise ValueError(f"accepted {stage} receipt identity differs")
        output_roots.extend(_verify_output_receipt(receipt, stage))
        receipt_bindings[stage] = {
            "path": str(receipt_path),
            "sha256": _sha256(receipt_path),
        }
    names = [
        "metadata",
        "quality",
        "identity",
        "annual_metrics",
        "annual_dataset_v2",
        "quarterly_metrics",
        "combined_dataset_v3",
        *[
            name
            for company in FIRST5
            for name in (f"annual_analysis:{company}", f"quarterly_analysis:{company}")
        ],
    ]
    manifests = value["publication_manifests"]
    if not isinstance(manifests, list) or [row.get("name") for row in manifests] != names:
        raise ValueError("first-five publication manifest set differs")
    manifest_bindings = []
    for row in manifests:
        if not isinstance(row, dict) or set(row) != {
            "name",
            "root",
            "manifest",
            "manifest_sha256",
        }:
            raise ValueError("first-five publication manifest declaration differs")
        root = _directory(_absolute(row["root"], "accepted publication root"), "accepted publication root")
        manifest = _regular(_absolute(row["manifest"], "accepted publication manifest"), "accepted publication manifest")
        if manifest.parent != root or _sha256(manifest) != row["manifest_sha256"]:
            raise ValueError("accepted publication manifest changed")
        if row["name"] != "metadata" and not any(
            manifest.is_relative_to(output_root) for output_root in output_roots
        ):
            raise ValueError("accepted publication is outside accepted stage outputs")
        manifest_bindings.append({**row})
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "source_head": FINANCIAL_SOURCE_SHA,
        "companies": cohort,
        "stage_receipts": receipt_bindings,
        "publication_manifests": manifest_bindings,
    }


def _failed_attempt(value: dict[str, Any]) -> bool:
    statuses = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key in {"status", "plan_status"} and isinstance(nested, str):
                    statuses.append(nested)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return any(status in {"BUILD_FAILED", "FAIL", "FAILED"} for status in statuses)


def _target_paths(config: dict[str, Any]) -> dict[str, Path]:
    manifest = Path(config["collection"]["manifest"])
    ticker = config["target"]["ticker"]
    company_root = manifest.parent / "companies" / ticker
    destination = (
        Path(config["target"]["history_parent"])
        / config["target"]["history_basename"]
    )
    return {
        "company_root": company_root,
        "plan": company_root / "plan.json",
        "intake": company_root / "intake/history_intake.json",
        "marker": company_root / "build_manifest.json",
        "old_receipt": company_root / "ops_build_receipt.json",
        "receipt": company_root
        / f"history_recovery_receipt-{config['target']['run_version']}.json",
        "destination": destination,
    }


def _validate_collection_target(config: dict[str, Any]) -> dict[str, Any]:
    declaration = config["collection"]
    manifest = _regular(Path(declaration["manifest"]), "collection manifest")
    if _sha256(manifest) != declaration["manifest_sha256"]:
        raise ValueError("collection manifest hash differs")
    status = ops.read_universe_status(manifest_path=manifest)
    identities = [{"ticker": row.ticker, "cik": row.cik} for row in status.companies]
    if (
        status.universe_id != declaration["universe_id"]
        or status.as_of_date != FINANCIAL_AS_OF
        or status.requested_companies != 50
        or status.selected_filings != 1097
        or identities != declaration["companies"]
    ):
        raise ValueError("collection exact-50 identity differs")
    candidate_path = _regular(Path(declaration["candidate"]), "candidate")
    if _sha256(candidate_path) != declaration["candidate_sha256"]:
        raise ValueError("candidate hash differs")
    candidate = _read_json(candidate_path, "candidate")
    rows = candidate.get("selection")
    if not isinstance(rows, list) or len(rows) != 50:
        raise ValueError("candidate exact-50 selection differs")
    candidate_by_ticker = {row.get("ticker"): row for row in rows}
    candidate_identities = {
        (row.get("ticker"), row.get("cik")) for row in rows if isinstance(row, dict)
    }
    if (
        set(candidate_by_ticker) != {row["ticker"] for row in identities}
        or candidate_identities
        != {(row["ticker"], row["cik"]) for row in identities}
        or sum(row.get("selected_filings", -1) for row in rows) != 1097
        or "PEP" in candidate_by_ticker
        or "KDP" not in candidate_by_ticker
    ):
        raise ValueError("candidate membership or filing count differs")
    target = config["target"]
    row = next(item for item in status.companies if item.ticker == target["ticker"])
    candidate_row = candidate_by_ticker[target["ticker"]]
    if (
        row.cik != target["cik"]
        or candidate_row.get("cik") != target["cik"]
        or row.selected_filings != target["selected_filings"]
        or row.selected_filings != row.held_filings
        or row.pending_filings
        or row.failed_filings
        or candidate_row.get("selected_filings") != target["selected_filings"]
        or candidate_row.get("plan_sha256") != target["plan_sha256"]
        or candidate_row.get("intake_sha256") != target["intake_sha256"]
    ):
        raise ValueError("target source scope differs")
    paths = _target_paths(config)
    if _sha256(_regular(paths["plan"], "target plan")) != target["plan_sha256"]:
        raise ValueError("target plan hash differs")
    if _sha256(_regular(paths["intake"], "target intake")) != target["intake_sha256"]:
        raise ValueError("target intake hash differs")
    run = ops._attest_run(manifest)
    company = next(item for item in run.manifest["companies"] if item["ticker"] == target["ticker"])
    intake = ops._attest_intake(paths["intake"], run.plans[target["ticker"]])
    if (
        company["plan_sha256"] != target["plan_sha256"]
        or intake.sha256 != target["intake_sha256"]
        or not intake.complete
        or intake.error
    ):
        raise ValueError("target plan or intake attestation differs")
    if row.state == "READY" or any(
        path.exists() or path.is_symlink()
        for path in (paths["marker"], paths["old_receipt"], paths["receipt"], paths["destination"])
    ):
        raise ValueError("target already has a marker, receipt, READY state, or selected output")
    company_attempts = paths["company_root"] / "operation_attempts"
    actual_attempts = sorted(company_attempts.glob("build-*.json"))
    declared_attempts = []
    for declaration_item in target["approved_prior_failed_attempts"]:
        attempt = _pin(declaration_item, "approved prior failed attempt")
        if attempt.parent != company_attempts or not _failed_attempt(
            _read_json(attempt, "approved prior failed attempt")
        ):
            raise ValueError("prior build attempt is not an exact failed target attempt")
        declared_attempts.append(attempt)
    if actual_attempts != declared_attempts:
        raise ValueError("target contains an unapproved prior build attempt")
    expected_state = "BUILD_FAILED" if declared_attempts else "RAW_COMPLETE"
    if row.state != expected_state:
        raise ValueError("target public state differs from approved recovery state")
    destination = paths["destination"].absolute()
    abandoned = []
    for root_value in target["abandoned_output_roots"]:
        root = _directory(Path(root_value), "abandoned output root")
        if root == destination or root.is_relative_to(destination) or destination.is_relative_to(root):
            raise ValueError("new recovery output overlaps abandoned partial output")
        abandoned.append(str(root))
    return {
        "manifest": str(manifest),
        "manifest_sha256": _sha256(manifest),
        "universe_id": status.universe_id,
        "companies": identities,
        "selected_filings": status.selected_filings,
        "target": {
            "ticker": row.ticker,
            "cik": row.cik,
            "state": row.state,
            "selected_filings": row.selected_filings,
            "plan": str(paths["plan"]),
            "plan_sha256": target["plan_sha256"],
            "intake": str(paths["intake"]),
            "intake_sha256": target["intake_sha256"],
            "prior_failed_attempts": [
                {"path": str(path), "sha256": _sha256(path)} for path in declared_attempts
            ],
            "abandoned_output_roots": abandoned,
            "destination": str(destination),
            "receipt": str(paths["receipt"]),
        },
    }


def _snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "runner": _verify_runner_source(config),
        "engine": _verify_engine_source(config),
        "collection": _validate_collection_target(config),
        "first5_financial_acceptance": _verify_financial_acceptance(config),
    }


def _preflight_path(config: dict[str, Any]) -> Path:
    return Path(config["execution_root"]) / "preflight.json"


def _request_path(config: dict[str, Any]) -> Path:
    return Path(config["execution_root"]) / "request.json"


def _summary_path(config: dict[str, Any]) -> Path:
    return Path(config["execution_root"]) / "execution.summary.json"


def preflight(config_path: Path) -> Path:
    config, config_sha = load_config(config_path)
    execution = Path(config["execution_root"])
    if execution.exists() or execution.is_symlink():
        raise FileExistsError("History recovery execution root must be fresh")
    _directory(Path(config["resource_root"]), "shared resource root")
    _directory(Path(config["target"]["history_parent"]), "history parent")
    snapshot = _snapshot(config)
    execution.mkdir(parents=True)
    return _write_new(
        _preflight_path(config),
        {
            "schema_version": PREFLIGHT_VERSION,
            "status": "PREPARED_SOURCE_ONLY",
            "config": {"path": str(Path(config_path).absolute()), "sha256": config_sha},
            "snapshot": snapshot,
            "resources": config["limits"],
            "execution": "SEPARATE_ROOT_AUTHORED_EXACT_GO_REQUIRED",
        },
        "History recovery preflight",
    )


def _validated_preflight(config_path: Path) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    config, config_sha = load_config(config_path)
    path = _regular(_preflight_path(config), "History recovery preflight")
    value = _read_json(path, "History recovery preflight")
    expected = {
        "schema_version": PREFLIGHT_VERSION,
        "status": "PREPARED_SOURCE_ONLY",
        "config": {"path": str(Path(config_path).absolute()), "sha256": config_sha},
        "snapshot": _snapshot(config),
        "resources": config["limits"],
        "execution": "SEPARATE_ROOT_AUTHORED_EXACT_GO_REQUIRED",
    }
    if value != expected:
        raise ValueError("History recovery preflight changed")
    return config, config_sha, path, value


def request_stage(config_path: Path) -> Path:
    config, config_sha, preflight_path, preflight_value = _validated_preflight(config_path)
    if _request_path(config).exists() or _summary_path(config).exists():
        raise ValueError("History recovery request or attempt already exists")
    value = {
        "schema_version": REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_ROOT_GO",
        "operation": "recover-history-one",
        "config_sha256": config_sha,
        "preflight_sha256": _sha256(preflight_path),
        "runner_head": config["runner"]["head"],
        "engine_head": config["engine"]["head"],
        "collection": preflight_value["snapshot"]["collection"],
        "first5_financial_acceptance": preflight_value["snapshot"][
            "first5_financial_acceptance"
        ],
        "target": preflight_value["snapshot"]["collection"]["target"],
    }
    return _write_new(_request_path(config), value, "History recovery request")


def _expected_go(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config, config_sha, preflight_path, preflight_value = _validated_preflight(config_path)
    request_path = _regular(_request_path(config), "History recovery request")
    request = _read_json(request_path, "History recovery request")
    expected_request = {
        "schema_version": REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_ROOT_GO",
        "operation": "recover-history-one",
        "config_sha256": config_sha,
        "preflight_sha256": _sha256(preflight_path),
        "runner_head": config["runner"]["head"],
        "engine_head": config["engine"]["head"],
        "collection": preflight_value["snapshot"]["collection"],
        "first5_financial_acceptance": preflight_value["snapshot"][
            "first5_financial_acceptance"
        ],
        "target": preflight_value["snapshot"]["collection"]["target"],
    }
    if request != expected_request:
        raise ValueError("History recovery request changed")
    return config, {
        "schema_version": GO_VERSION,
        "status": "GO",
        "authorized_by": "ROOT_LEAD",
        "operation": "recover-history-one",
        "config_sha256": config_sha,
        "preflight_sha256": _sha256(preflight_path),
        "request_sha256": _sha256(request_path),
        "runner_head": config["runner"]["head"],
        "engine_head": config["engine"]["head"],
        "collection_manifest_sha256": config["collection"]["manifest_sha256"],
        "target": preflight_value["snapshot"]["collection"]["target"],
        "first5_financial_acceptance": preflight_value["snapshot"][
            "first5_financial_acceptance"
        ],
    }


def _validate_go(config_path: Path, go_path: Path) -> dict[str, Any]:
    config, expected = _expected_go(config_path)
    if _read_json(go_path, "History recovery GO") != expected:
        raise ValueError("History recovery GO does not exactly bind source, scope and inputs")
    return config


def _receive_supervisor(config: dict[str, Any]) -> None:
    try:
        descriptor = int(os.environ["SEC_XBRL_T3V2_SUPERVISOR_FD"])
        parent = int(os.environ["SEC_XBRL_T3V2_SUPERVISOR_PID"])
        expected = os.environ["SEC_XBRL_T3V2_SUPERVISOR_SHA256"]
    except (KeyError, ValueError) as exc:
        raise PermissionError("History recovery worker requires supervisor capability") from exc
    if os.getppid() != parent:
        raise PermissionError("History recovery supervisor identity differs")
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        token = stream.read(33)
    if len(token) != 32 or hashlib.sha256(token).hexdigest() != expected:
        raise PermissionError("History recovery supervisor capability is invalid")
    expected_environment = {
        "POLARS_MAX_THREADS": "2",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    if any(os.environ.get(name) != value for name, value in expected_environment.items()):
        raise PermissionError("History recovery worker resource environment differs")
    try:
        with resource_ops.heavy_lock(Path(config["resource_root"])):
            pass
    except ValueError as exc:
        if str(exc) != "another heavy operation is active":
            raise
    else:
        raise PermissionError("History recovery worker requires parent-held heavy lock")


def _execute_recovery(config: dict[str, Any], go_path: Path) -> Path:
    snapshot = _snapshot(config)
    binding = snapshot["collection"]
    paths = _target_paths(config)
    manifest = Path(config["collection"]["manifest"])
    run = ops._attest_run(manifest)
    ticker = config["target"]["ticker"]
    company = next(row for row in run.manifest["companies"] if row["ticker"] == ticker)
    intake = ops._attest_intake(paths["intake"], run.plans[ticker])
    publication = history.build_history(
        intake_manifest=paths["intake"], output_root=paths["destination"]
    )
    history.HistoryPublicationReader(publication).verify_all()
    marker = ops._create_build_attestation(
        ticker=ticker,
        plan=run.plans[ticker],
        plan_sha256=company["plan_sha256"],
        intake_path=paths["intake"],
        intake_sha256=intake.sha256 or "",
        destination=paths["destination"],
        publication=publication,
        views=("AS_FILED", "LATEST_REPORTED"),
    )
    error = ops._validate_build_attestation(
        marker,
        ticker=ticker,
        plan=run.plans[ticker],
        plan_sha256=company["plan_sha256"],
        intake_path=paths["intake"],
        intake=intake,
    )
    if error:
        raise ValueError(f"new recovery build attestation is invalid: {error}")
    ops._write_once_json(paths["marker"], marker, label=f"{ticker} recovery build")
    status = ops.read_universe_status(manifest_path=manifest)
    row = next(item for item in status.companies if item.ticker == ticker)
    if row.state != "READY":
        raise ValueError("public collection status did not confirm recovered READY")
    receipt = {
        "schema_version": RECEIPT_VERSION,
        "status": "READY",
        "ticker": ticker,
        "cik": config["target"]["cik"],
        "runner_head": config["runner"]["head"],
        "engine_head": config["engine"]["head"],
        "runner_source": snapshot["runner"],
        "engine_source": snapshot["engine"],
        "first5_financial_acceptance": snapshot["first5_financial_acceptance"],
        "collection_manifest": binding["manifest"],
        "collection_manifest_sha256": binding["manifest_sha256"],
        "go": {"path": str(Path(go_path).absolute()), "sha256": _sha256(go_path)},
        "plan_sha256": config["target"]["plan_sha256"],
        "intake_sha256": config["target"]["intake_sha256"],
        "prior_failed_attempts": binding["target"]["prior_failed_attempts"],
        "abandoned_output_roots": binding["target"]["abandoned_output_roots"],
        "output_root": str(paths["destination"].absolute()),
        "publication": str(Path(marker["publication"]).absolute()),
        "build_manifest": str(paths["marker"].absolute()),
        "build_manifest_sha256": _sha256(paths["marker"]),
        "history_manifest_sha256": marker["history_manifest_sha256"],
        "declared_files": marker["declared_files"],
        "financial_as_of": FINANCIAL_AS_OF,
    }
    return _write_new(paths["receipt"], receipt, "History recovery receipt")


RECOVERY_HANDLER: Callable[[dict[str, Any], Path], Path] = _execute_recovery


def _worker(config_path: Path, go_path: Path) -> Path:
    resource_ops.install_parent_death_guard()
    config = _validate_go(config_path, go_path)
    _receive_supervisor(config)
    _snapshot(config)
    return RECOVERY_HANDLER(config, go_path)


def _worker_environment(config: dict[str, Any], read_fd: int, token: bytes) -> dict[str, str]:
    runner = str(Path(config["runner"]["checkout"]).resolve())
    engine = str((Path(config["engine"]["checkout"]) / "src").resolve())
    env = os.environ.copy()
    env.update(
        PYTHONPATH=os.pathsep.join((engine, runner)),
        POLARS_MAX_THREADS="2",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        SEC_XBRL_T3V2_SUPERVISOR_FD=str(read_fd),
        SEC_XBRL_T3V2_SUPERVISOR_PID=str(os.getpid()),
        SEC_XBRL_T3V2_SUPERVISOR_SHA256=hashlib.sha256(token).hexdigest(),
    )
    return env


def run_stage(config_path: Path, go_path: Path) -> Path:
    config = _validate_go(config_path, go_path)
    summary = _summary_path(config)
    paths = _target_paths(config)
    if summary.exists() or paths["receipt"].exists() or paths["marker"].exists():
        raise ValueError("History recovery cannot retry or overwrite an attempted target")
    if paths["destination"].exists() or paths["destination"].is_symlink():
        raise FileExistsError("History recovery destination is not fresh")
    summary.parent.mkdir(parents=True, exist_ok=True)
    log, samples = summary.with_suffix(".log"), summary.with_suffix(".rss.jsonl")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--config",
        str(Path(config_path).absolute()),
        "--go-file",
        str(Path(go_path).absolute()),
    ]
    token = os.urandom(32)
    read_fd, write_fd = os.pipe()
    env = _worker_environment(config, read_fd, token)
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
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "child_reaped": process is None or process.poll() is not None,
                "log": str(log),
                "samples": str(samples),
            },
            "History recovery failure summary",
        )
        raise
    result = {
        "schema_version": RESOURCE_VERSION,
        "status": stopped or ("PASS" if code == 0 else "FAIL"),
        "returncode": code,
        "elapsed_seconds": round(elapsed, 3),
        "peak_process_tree_rss_kib": peak,
        "limit_kib": LIMIT_KIB,
        "timeout_seconds": TIMEOUT_SECONDS,
        "command": command,
        "log": str(log),
        "samples": str(samples),
    }
    _write_new(summary, result, "History recovery resource summary")
    if result["status"] != "PASS":
        raise RuntimeError(f"History recovery failed: {result['status']}")
    return _regular(paths["receipt"], "History recovery receipt")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("--config", type=Path, required=True)
    request_parser = commands.add_parser("request-stage")
    request_parser.add_argument("--config", type=Path, required=True)
    run_parser = commands.add_parser("run-stage")
    run_parser.add_argument("--config", type=Path, required=True)
    run_parser.add_argument("--go-file", type=Path, required=True)
    worker = commands.add_parser("_worker")
    worker.add_argument("--config", type=Path, required=True)
    worker.add_argument("--go-file", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "preflight":
        result = preflight(args.config)
    elif args.command == "request-stage":
        result = request_stage(args.config)
    elif args.command == "run-stage":
        result = run_stage(args.config, args.go_file)
    else:
        result = _worker(args.config, args.go_file)
    print(json.dumps({"path": str(result), "sha256": _sha256(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
