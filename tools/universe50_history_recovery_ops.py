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
import tempfile
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
REPORTED_REUSE_VERSION = "universe50-attested-reported-reuse-v1"
ENGINE_ACCEPTANCE_VERSION = "lead-history-engine-source-acceptance-v1"
ENGINE_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_HISTORY_ENGINE_SOURCE_AND_SYNTHETIC"
FINANCIAL_ACCEPTANCE_VERSION = "universe50-first5-financial-acceptance-v1"
FINANCIAL_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_FIRST5_FINANCIAL"
RUNNER_BASE_SHA = "9b6e7ec906382fba92adb5209c5b439fc7d7d6ba"
ENGINE_BASE_SHA = "8a1b40ab1008fb9109a27b2a5bcea02a257e1694"
FINANCIAL_SOURCE_SHA = "e56c1483a882ce000d0164cc91d561d4cc7bbf67"
REPORTED_GENERATION_SOURCE_SHA = "3a3d7d6492bf7948376cb6795a9ddfe157a8b556"
REPORTED_RECOVERY_SOURCE_SHA = "f222a8b77aefff2adb877f587e59cfd9ac03bf7d"
PRIOR_RECOVERY_SOURCE_SHA = "a02c4aef36a28c3673185ddebefc01efaa8fe0ff"
PRIOR_RECOVERY_SOURCE_TREE = "de682369314a3c74c2e727abfdb68c51c6874f55"
PRIOR_RECOVERY_PROGRAM_SHA256 = "e18b3157a350f6b70a4563a775fd13aa3114f32b18a695d909ed13c1fca77c33"
PRIOR_RECOVERY_RESOURCE_OPS_SHA256 = (
    "5e4a249070e25359ec406c0c727bb0f919ffdd55624936f630e0325a41b3e4f9"
)
PRIOR_RECOVERY_ACCEPTANCE_SHA256 = (
    "8487366d30a29d2d8f225e911ab91f50fb962dbacce07f1edcf71dd168a5a331"
)
PRIOR_RECOVERY_CONFIG_SHA256 = (
    "00f61854cf8a0a84c7ed11d11d07005d16216f56a7d10c3e9524f70645952542"
)
PRIOR_RECOVERY_PREFLIGHT_SHA256 = (
    "aa779aa51cd14dd78bc179412571f3c1bbd1aa5a8575a316269a5f6d605b7f4a"
)
PRIOR_RECOVERY_REQUEST_SHA256 = (
    "8206a0a01dcf813e1cfdfe8f9a657a88b591fe34313027851e7b3c2cb6fb15da"
)
PRIOR_RECOVERY_GO_SHA256 = (
    "5c410067c12fbf49b69809b86a76034063c5312e21a861732ddd306ddf204c21"
)
PRIOR_RECOVERY_SUMMARY_SHA256 = (
    "0c07d38130312434acdcfc40cb87cd66c1c6d0774211884948a5620b9e5ae574"
)
PRIOR_RECOVERY_ACCEPTANCE_VERSION = "lead-history-recovery-source-synthetic-acceptance-v1"
PRIOR_RECOVERY_ACCEPTANCE_STATUS = "LOCALLY_ACCEPTED_HISTORY_RECOVERY_SOURCE_AND_SYNTHETIC"
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
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
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
    if path.is_symlink() or not path.is_file() or path != path.resolve():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path.resolve()


def _directory(path: Path, label: str) -> Path:
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_dir() or path != path.resolve():
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
    if len({row["ticker"] for row in result}) != 50 or len({row["cik"] for row in result}) != 50:
        raise ValueError("exact-50 company identities must be unique")
    if "PEP" in {row["ticker"] for row in result} or "KDP" not in {row["ticker"] for row in result}:
        raise ValueError("exact-50 membership must exclude PEP and include KDP")
    return result


def _validate_reported_reuse_shape(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    expected = {
        "schema_version",
        "mode",
        "universe_id",
        "cik",
        "generation_source_head",
        "recovery_source_head",
        "original_failed_output_root",
        "original_operational_root",
        "operational_roots",
        "source_stage",
        "clean_stage",
        "copy_report",
        "component_report",
        "root_attestation",
        "source_execution_log",
        "intake",
        "plan",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("reported reuse declaration shape differs")
    if (
        value["schema_version"] != REPORTED_REUSE_VERSION
        or value["mode"] != "ATTESTED_REPORTED_STAGE"
        or not isinstance(value["universe_id"], str)
        or not value["universe_id"]
        or not isinstance(value["cik"], str)
        or len(value["cik"]) != 10
        or not value["cik"].isdigit()
        or value["generation_source_head"] != REPORTED_GENERATION_SOURCE_SHA
        or value["recovery_source_head"] != REPORTED_RECOVERY_SOURCE_SHA
    ):
        raise ValueError("reported reuse identity differs")
    for name in ("original_failed_output_root", "original_operational_root"):
        _absolute(value[name], f"reported reuse {name}")
    operational = value["operational_roots"]
    if not isinstance(operational, dict) or set(operational) != {"t1", "t2", "t3", "t4"}:
        raise ValueError("reported reuse operational root set differs")
    for name, declaration in operational.items():
        if not isinstance(declaration, dict) or set(declaration) != {"path", "manifest_sha256"}:
            raise ValueError(f"reported reuse operational root {name} differs")
        _absolute(declaration["path"], f"reported reuse operational root {name}")
        _sha(declaration["manifest_sha256"], f"reported reuse operational root {name}")
    for name in ("source_stage", "clean_stage"):
        declaration = value[name]
        if not isinstance(declaration, dict) or set(declaration) != {"root", "manifest_sha256"}:
            raise ValueError(f"reported reuse {name} differs")
        _absolute(declaration["root"], f"reported reuse {name}")
        _sha(declaration["manifest_sha256"], f"reported reuse {name}")
    for name in (
        "copy_report",
        "component_report",
        "root_attestation",
        "source_execution_log",
        "intake",
        "plan",
    ):
        declaration = value[name]
        if not isinstance(declaration, dict) or set(declaration) != {"path", "sha256"}:
            raise ValueError(f"reported reuse {name} requires exact path and SHA-256")
        _absolute(declaration["path"], f"reported reuse {name}")
        _sha(declaration["sha256"], f"reported reuse {name}")
    return value


def _validate_shape(value: dict[str, Any]) -> dict[str, Any]:
    required = {
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
    }
    if set(value) not in (required, required | {"reported_reuse"}):
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
        if not isinstance(declaration, dict) or set(declaration) not in (
            {"path", "sha256"},
            {"path", "sha256", "legacy_ops"},
            {"path", "sha256", "recovery_ops"},
        ):
            raise ValueError("prior failed attempt declaration differs")
        _absolute(declaration["path"], "prior failed attempt")
        _sha(declaration["sha256"], "prior failed attempt")
    legacy_count = sum("legacy_ops" in declaration for declaration in prior)
    recovery_count = sum("recovery_ops" in declaration for declaration in prior)
    if ticker == "JNJ" and runner["head"] != PRIOR_RECOVERY_SOURCE_SHA and (
        recovery_count > 1 or (legacy_count > 0 and recovery_count != 1)
    ):
        raise ValueError(
            "post-r1 JNJ recovery requires exactly one accepted a02 r1 recovery witness"
        )
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
    reported_reuse = _validate_reported_reuse_shape(value.get("reported_reuse"))
    if reported_reuse is not None and (
        ticker != "JNJ"
        or reported_reuse["universe_id"] != collection["universe_id"]
        or reported_reuse["cik"] != cik
        or engine["head"] != REPORTED_RECOVERY_SOURCE_SHA
    ):
        raise ValueError("reported reuse is outside the approved JNJ source scope")
    return {
        **value,
        "collection": {**collection, "companies": companies},
        "execution_root": str(execution_root),
        "resource_root": str(resource_root),
        "reported_reuse": reported_reuse,
    }


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    path = _regular(path, "History recovery config")
    return _validate_shape(_read_json(path, "History recovery config")), _sha256(path)


def _verify_runner_source(config: dict[str, Any]) -> dict[str, Any]:
    declaration = config["runner"]
    checkout = _directory(Path(declaration["checkout"]), "runner checkout")
    state = _git_state(checkout, declaration["head"], "runner")
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "merge-base",
            "--is-ancestor",
            RUNNER_BASE_SHA,
            declaration["head"],
        ],
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


def _run_canonical_validator(
    script: str,
    arguments: list[str],
    checkout: Path,
    *,
    timeout_seconds: float = 60,
) -> str:
    """Guard the isolated read-only validator even outside a History supervisor."""
    bootstrap = """
import ctypes, os, signal, sys
if not sys.platform.startswith("linux"):
    raise RuntimeError("canonical validator requires Linux parent-death guard")
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), "canonical validator parent-death guard failed")
if os.getppid() != int(os.environ["SEC_XBRL_RECOVERY_VALIDATOR_PARENT_PID"]):
    raise PermissionError("canonical validator parent exited before guard installation")
"""
    env = os.environ.copy()
    env.update(
        PYTHONPATH=os.pathsep.join((str(checkout / "src"), str(checkout))),
        PYTHONDONTWRITEBYTECODE="1",
        POLARS_MAX_THREADS="2",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        SEC_XBRL_RECOVERY_VALIDATOR_PARENT_PID=str(os.getpid()),
    )
    with (
        tempfile.TemporaryFile(mode="w+") as output,
        tempfile.TemporaryFile(mode="w+") as errors,
        tempfile.TemporaryFile(mode="w+") as samples,
    ):
        process = subprocess.Popen(
            [sys.executable, "-c", bootstrap + script, *arguments],
            cwd=checkout,
            env=env,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )
        try:
            code, _peak, stopped, _elapsed = resource_ops.supervise_owned_process(
                process,
                samples,
                limit_kib=LIMIT_KIB,
                timeout_seconds=timeout_seconds,
            )
        except BaseException:
            resource_ops.terminate_owned_process_group(process)
            raise
        errors.seek(0)
        if code or stopped:
            raise ValueError(
                f"canonical financial gate rejected: {stopped or code}: {errors.read().strip()}"
            )
        output.seek(0)
        return output.read()


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
    # This process imports the 8a History engine. Canonical financial validation runs
    # only in an isolated interpreter; no FULL financial execution is invented.
    source = first5.get("source") or {}
    checkout = _directory(
        _absolute(source.get("checkout"), "financial checkout"), "financial checkout"
    )
    _git_state(checkout, FINANCIAL_SOURCE_SHA, "canonical financial validator")
    script = """
import json, sys
from pathlib import Path
from tools import universe50_financial_ops as f
first5_path = f._pin(sys.argv[1], sys.argv[3], "accepted first-five config")
acceptance_path = f._pin(sys.argv[2], sys.argv[4], "accepted first-five acceptance")
a = f._read_json(acceptance_path, "first-five acceptance")
c = f._validate_shape(f._read_json(first5_path, "first-five config"))
f._verify_runtime(c)
if (c["collection_scope_mode"] != "EXPLICIT_SUBSET"
    or f._first5_companies(c) != a["companies"]
    or c["collection"] != a["collection"]
    or c["source"]["head"] != a["source_head"]
    or c["financial_as_of"] != a["financial_as_of"]
    or c["metadata_observation_cutoff"] != a["metadata_observation_cutoff"]):
    raise ValueError("accepted first-five config differs")
stages = list(f.FIRST5_ACCEPTED_STAGES)
if c["metadata"]["mode"] == "PUBLISH_EXACT50":
    stages.insert(0, "metadata")
if set(a["stage_receipts"]) != set(stages):
    raise ValueError("first-five financial stage receipt set differs")
for stage in stages:
    pin = a["stage_receipts"][stage]
    if set(pin) != {"path", "sha256"}:
        raise ValueError("accepted receipt pin differs")
    p = f._pin(pin["path"], pin["sha256"], "accepted receipt")
    r = f._read_json(p, "accepted receipt")
    if (r.get("schema_version") != f.RECEIPT_VERSION or r.get("status") != "PASS"
        or r.get("stage") != stage or r.get("source_head") != a["source_head"]
        or not isinstance(r.get("go_sha256"), str)
        or f.SHA256.fullmatch(r["go_sha256"]) is None):
        raise ValueError("accepted receipt identity differs")
    f._verify_output_receipt(r, stage)
    if [v.get("root") for v in r["outputs"]] != [str(v) for v in f._output_paths(c, stage)]:
        raise ValueError("accepted " + stage + " receipt output roots differ")
expected = f._expected_publication_manifests(c)
if a["publication_manifests"] != expected:
    raise ValueError("first-five accepted publication manifests differ")
if c["metadata"]["mode"] == "EXISTING_PUBLICATION":
    if expected[0]["manifest_sha256"] != c["metadata"]["manifest_sha256"]:
        raise ValueError("accepted metadata manifest differs from config")
print(json.dumps({"stage_receipts": a["stage_receipts"], "publication_manifests": expected}))
"""
    validated = json.loads(
        _run_canonical_validator(
            script,
            [
                str(first5_path),
                str(path),
                value["first5_config"]["sha256"],
                config["first5_financial_acceptance"]["sha256"],
            ],
            checkout,
        )
    )
    _pin(config["first5_financial_acceptance"], "first-five financial acceptance")
    _pin(value["first5_config"], "accepted first-five config")
    receipt_bindings = validated["stage_receipts"]
    manifest_bindings = validated["publication_manifests"]
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "source_head": FINANCIAL_SOURCE_SHA,
        "validation_scope": "CANONICAL_FIRST5_GATE_ONLY",
        "validator_checkout": str(checkout),
        "first5_config": value["first5_config"],
        "companies": cohort,
        "stage_receipts": receipt_bindings,
        "publication_manifests": manifest_bindings,
    }


def _legacy_failure_root(
    config: dict[str, Any],
    attempt: Path,
    failure: dict[str, Any],
    witness: Any,
) -> tuple[Path, dict[str, Any]]:
    """Derive the old OPS destination only from its pinned 56a command contract."""
    if not isinstance(witness, dict) or set(witness) != {"config", "go", "program"}:
        raise ValueError("legacy OPS failure requires config, GO and program pins")
    config_path = _pin(witness["config"], "legacy OPS config")
    go_path = _pin(witness["go"], "legacy OPS GO")
    program = _pin(witness["program"], "legacy OPS program")
    program_sha = "5e4a249070e25359ec406c0c727bb0f919ffdd55624936f630e0325a41b3e4f9"
    if _sha256(program) != program_sha or program.name != "universe50_t3v2_ops.py":
        raise ValueError("legacy OPS program is not accepted 56a source")
    old = _read_json(config_path, "legacy OPS config")
    go = _read_json(go_path, "legacy OPS GO")
    target = config["target"]["ticker"]
    command = failure.get("command")
    if (
        failure.get("schema_version") != "universe50-t3v2-resource-run-v1"
        or failure.get("status") not in {"RSS_LIMIT", "TIMEOUT", "FAIL", "INTERRUPTED"}
        or failure.get("limit_kib") != LIMIT_KIB
        or failure.get("timeout_seconds") != TIMEOUT_SECONDS
        or not isinstance(command, list)
        or len(command) != 9
        or not isinstance(command[0], str)
        or not Path(command[0]).is_absolute()
        or command[1:]
        != [
            str(program),
            "_build-worker",
            "--config",
            str(config_path),
            "--ticker",
            target,
            "--go-file",
            str(go_path),
        ]
    ):
        raise ValueError("legacy OPS failed command identity differs")
    if (
        old.get("schema_version") != "universe50-t3v2-ops-config-v1"
        or old.get("source_sha") != ENGINE_BASE_SHA
        or old.get("first5") != list(FIRST5)
        or old.get("limits") != config["limits"]
        or old.get("collection_root") != str(Path(config["collection"]["manifest"]).parent)
    ):
        raise ValueError("legacy OPS config collection/source differs")
    preflight = _regular(
        Path(old["collection_root"]) / "ops_preflight.json", "legacy OPS preflight"
    )
    proof = _read_json(preflight, "legacy OPS preflight")
    if (
        proof.get("schema_version") != "universe50-t3v2-ops-preflight-v1"
        or proof.get("status") != "PREPARED"
        or proof.get("source_sha") != ENGINE_BASE_SHA
        or proof.get("run_id") != old.get("run_id")
        or proof.get("config") != witness["config"]
        or proof.get("modules", {}).get("program") != witness["program"]
    ):
        raise ValueError("legacy OPS preflight binding differs")
    engine_digest = proof.get("modules", {}).get("engine", {}).get("aggregate_sha256")
    _sha(engine_digest, "legacy engine modules")
    if go != {
        "schema_version": "universe50-t3v2-stage-go-v1",
        "status": "GO",
        "operation": "build-one",
        "run_id": old["run_id"],
        "source_sha": ENGINE_BASE_SHA,
        "ops_config_sha256": _sha256(config_path),
        "preflight_sha256": _sha256(preflight),
        "program_sha256": program_sha,
        "engine_modules_sha256": engine_digest,
        "tickers": [target],
    }:
        raise ValueError("legacy OPS GO binding differs")
    expected_parent = Path(old["collection_root"]) / "execution" / target
    if attempt.parent != expected_parent or not attempt.name.endswith(".summary.json"):
        raise ValueError("legacy OPS failure summary location differs")
    root = (
        _absolute(old.get("history_root"), "legacy History root") / f"{target}-t3v2-{old['run_id']}"
    )
    # Scan the owned legacy execution area so an unpinned second attempt cannot hide.
    expected = {
        Path(row["path"]).resolve()
        for row in config["target"]["approved_prior_failed_attempts"]
        if "legacy_ops" in row
    }
    if set(expected_parent.glob("*.summary.json*")) != expected:
        raise ValueError("unapproved prior legacy OPS attempt")
    return root, {
        "path": str(attempt),
        "sha256": _sha256(attempt),
        "legacy_ops": witness,
        "preflight": {"path": str(preflight), "sha256": _sha256(preflight)},
        "output_root": str(root),
    }


def _verify_prior_recovery_acceptance(
    witness: dict[str, Any], old: dict[str, Any]
) -> dict[str, Any]:
    acceptance_path = _pin(witness["source_acceptance"], "prior recovery source acceptance")
    if _sha256(acceptance_path) != PRIOR_RECOVERY_ACCEPTANCE_SHA256:
        raise ValueError("prior recovery source acceptance is not the accepted a02 artifact")
    acceptance = _read_json(acceptance_path, "prior recovery source acceptance")
    if (
        acceptance.get("schema_version") != PRIOR_RECOVERY_ACCEPTANCE_VERSION
        or acceptance.get("status") != PRIOR_RECOVERY_ACCEPTANCE_STATUS
        or acceptance.get("source_head") != PRIOR_RECOVERY_SOURCE_SHA
        or acceptance.get("source_tree") != PRIOR_RECOVERY_SOURCE_TREE
        or acceptance.get("checkout") != old["runner"]["checkout"]
        or acceptance.get("actual_JNJ_retry_authorized") is not False
    ):
        raise ValueError("prior recovery source acceptance identity differs")
    for key in ("independent_report", "writer_report", "lead_contract"):
        _pin(acceptance.get(key), f"prior recovery acceptance {key}")
    return {"path": str(acceptance_path), "sha256": _sha256(acceptance_path)}


def _verify_prior_engine_snapshot(old: dict[str, Any], snapshot: Any) -> None:
    declaration = old["engine"]
    if not isinstance(snapshot, dict):
        raise TypeError("prior recovery engine snapshot is required")
    acceptance_path = _pin(declaration["source_acceptance"], "prior engine source acceptance")
    acceptance = _read_json(acceptance_path, "prior engine source acceptance")
    hashes = acceptance.get("module_sha256s")
    if (
        acceptance.get("schema_version") != ENGINE_ACCEPTANCE_VERSION
        or acceptance.get("status") != ENGINE_ACCEPTANCE_STATUS
        or acceptance.get("engine_source_head") != declaration["head"]
        or acceptance.get("engine_base_sha") != ENGINE_BASE_SHA
        or acceptance.get("graph_rule_version") != GRAPH_RULE_VERSION
        or not isinstance(hashes, dict)
        or set(hashes) != set(ENGINE_MODULES)
    ):
        raise ValueError("prior recovery engine acceptance differs")
    _pin(acceptance.get("independent_report"), "prior engine independent report")
    checkout = _directory(Path(declaration["checkout"]), "prior recovery engine checkout")
    _git_state(checkout, declaration["head"], "prior recovery engine")
    ancestor = subprocess.run(
        ["git", "-C", str(checkout), "merge-base", "--is-ancestor", ENGINE_BASE_SHA, declaration["head"]],
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("prior recovery engine is not based on accepted 8a")
    expected_files = {}
    for name, relative in ENGINE_MODULES.items():
        path = _regular(checkout / relative, f"prior recovery engine module {name}")
        digest = _sha256(path)
        if digest != _sha(hashes[name], f"prior recovery engine module {name}"):
            raise ValueError(f"prior recovery engine module changed: {name}")
        expected_files[name] = {"path": str(path), "sha256": digest}
    if snapshot != {
        "checkout": str(checkout),
        "head": declaration["head"],
        "base": ENGINE_BASE_SHA,
        "acceptance": {"path": str(acceptance_path), "sha256": _sha256(acceptance_path)},
        "independent_report": acceptance["independent_report"],
        "files": expected_files,
    }:
        raise ValueError("prior recovery engine snapshot differs")


def _recovery_failure_root(
    config: dict[str, Any],
    attempt: Path,
    failure: dict[str, Any],
    witness: Any,
) -> tuple[Path, dict[str, Any]]:
    """Bind an accepted a02 recovery TIMEOUT without treating it as native failure."""
    expected_keys = {"config", "preflight", "request", "go", "program", "source_acceptance"}
    if not isinstance(witness, dict) or set(witness) != expected_keys:
        raise ValueError("recovery OPS failure witness pins differ")
    config_path = _pin(witness["config"], "prior recovery config")
    preflight_path = _pin(witness["preflight"], "prior recovery preflight")
    request_path = _pin(witness["request"], "prior recovery request")
    go_path = _pin(witness["go"], "prior recovery GO")
    program = _pin(witness["program"], "prior recovery program")
    exact_hashes = {
        "config": (config_path, PRIOR_RECOVERY_CONFIG_SHA256),
        "preflight": (preflight_path, PRIOR_RECOVERY_PREFLIGHT_SHA256),
        "request": (request_path, PRIOR_RECOVERY_REQUEST_SHA256),
        "go": (go_path, PRIOR_RECOVERY_GO_SHA256),
        "summary": (attempt, PRIOR_RECOVERY_SUMMARY_SHA256),
    }
    if any(_sha256(path) != expected for path, expected in exact_hashes.values()):
        raise ValueError("prior recovery operational artifact is not the accepted r1 artifact")
    old = _validate_shape(_read_json(config_path, "prior recovery config"))
    if (
        old["runner"]["head"] != PRIOR_RECOVERY_SOURCE_SHA
        or old["runner"]["module_sha256s"]
        != {
            "runner": PRIOR_RECOVERY_PROGRAM_SHA256,
            "resource_ops": PRIOR_RECOVERY_RESOURCE_OPS_SHA256,
        }
    ):
        raise ValueError("prior recovery runner source differs")
    checkout = _directory(Path(old["runner"]["checkout"]), "prior recovery runner checkout")
    _git_state(checkout, PRIOR_RECOVERY_SOURCE_SHA, "prior recovery runner")
    tree = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_program = _regular(checkout / RUNNER_MODULES["runner"], "prior recovery program")
    resource_program = _regular(
        checkout / RUNNER_MODULES["resource_ops"], "prior recovery resource program"
    )
    if (
        tree != PRIOR_RECOVERY_SOURCE_TREE
        or program != expected_program
        or _sha256(program) != PRIOR_RECOVERY_PROGRAM_SHA256
        or _sha256(resource_program) != PRIOR_RECOVERY_RESOURCE_OPS_SHA256
    ):
        raise ValueError("prior recovery program identity differs")
    acceptance_binding = _verify_prior_recovery_acceptance(witness, old)

    if (
        old["financial_as_of"] != config["financial_as_of"]
        or old["first5"] != config["first5"]
        or old["collection"] != config["collection"]
        or old["limits"] != config["limits"]
        or old["resource_root"] != config["resource_root"]
    ):
        raise ValueError("prior recovery collection, cutoff, or resources differ")
    for key in ("ticker", "cik", "plan_sha256", "intake_sha256", "selected_filings"):
        if old["target"][key] != config["target"][key]:
            raise ValueError("prior recovery target scope differs")

    old_paths = _target_paths(old)
    expected_preflight_path = Path(old["execution_root"]) / "preflight.json"
    expected_request_path = Path(old["execution_root"]) / "request.json"
    expected_summary_path = Path(old["execution_root"]) / "execution.summary.json"
    if (
        preflight_path != expected_preflight_path
        or request_path != expected_request_path
        or attempt != expected_summary_path
    ):
        raise ValueError("prior recovery control location differs")
    preflight = _read_json(preflight_path, "prior recovery preflight")
    snapshot = preflight.get("snapshot")
    if not isinstance(snapshot, dict):
        raise TypeError("prior recovery preflight snapshot is required")
    expected_resources = {
        "process_tree_rss_kib": LIMIT_KIB,
        "polars_max_threads": POLARS_THREADS,
        "one_heavy_process": True,
        "timeout_seconds": TIMEOUT_SECONDS,
    }
    config_pin = {"path": str(config_path), "sha256": _sha256(config_path)}
    if (
        set(preflight) != {"schema_version", "status", "config", "snapshot", "resources", "execution"}
        or preflight["schema_version"] != PREFLIGHT_VERSION
        or preflight["status"] != "PREPARED_SOURCE_ONLY"
        or preflight["config"] != config_pin
        or preflight["resources"] != expected_resources
        or preflight["execution"] != "SEPARATE_ROOT_AUTHORED_EXACT_GO_REQUIRED"
    ):
        raise ValueError("prior recovery preflight binding differs")
    runner_snapshot = snapshot.get("runner")
    expected_runner_files = {
        "runner": {"path": str(program), "sha256": PRIOR_RECOVERY_PROGRAM_SHA256},
        "resource_ops": {
            "path": str(resource_program),
            "sha256": PRIOR_RECOVERY_RESOURCE_OPS_SHA256,
        },
    }
    if runner_snapshot != {
        "checkout": str(checkout),
        "head": PRIOR_RECOVERY_SOURCE_SHA,
        "base": RUNNER_BASE_SHA,
        "files": expected_runner_files,
    }:
        raise ValueError("prior recovery runner snapshot differs")
    _verify_prior_engine_snapshot(old, snapshot.get("engine"))
    collection_snapshot = snapshot.get("collection")
    if not isinstance(collection_snapshot, dict):
        raise TypeError("prior recovery collection snapshot is required")
    if (
        collection_snapshot.get("manifest") != old["collection"]["manifest"]
        or collection_snapshot.get("manifest_sha256") != old["collection"]["manifest_sha256"]
        or collection_snapshot.get("universe_id") != old["collection"]["universe_id"]
        or collection_snapshot.get("companies") != old["collection"]["companies"]
        or collection_snapshot.get("selected_filings") != old["collection"]["selected_filings"]
    ):
        raise ValueError("prior recovery collection snapshot differs")
    target_snapshot = collection_snapshot.get("target")
    if not isinstance(target_snapshot, dict):
        raise TypeError("prior recovery target snapshot is required")
    if (
        target_snapshot.get("ticker") != old["target"]["ticker"]
        or target_snapshot.get("cik") != old["target"]["cik"]
        or target_snapshot.get("selected_filings") != old["target"]["selected_filings"]
        or target_snapshot.get("plan") != str(old_paths["plan"])
        or target_snapshot.get("plan_sha256") != old["target"]["plan_sha256"]
        or target_snapshot.get("intake") != str(old_paths["intake"])
        or target_snapshot.get("intake_sha256") != old["target"]["intake_sha256"]
        or target_snapshot.get("destination") != str(old_paths["destination"].absolute())
        or target_snapshot.get("abandoned_output_roots") != old["target"]["abandoned_output_roots"]
    ):
        raise ValueError("prior recovery target snapshot differs")
    prior_snapshot = target_snapshot.get("prior_failed_attempts")
    if not isinstance(prior_snapshot, list) or len(prior_snapshot) != len(
        old["target"]["approved_prior_failed_attempts"]
    ):
        raise ValueError("prior recovery failed-attempt snapshot differs")
    for declaration in old["target"]["approved_prior_failed_attempts"]:
        matches = [
            row
            for row in prior_snapshot
            if row.get("path") == declaration["path"] and row.get("sha256") == declaration["sha256"]
        ]
        if len(matches) != 1 or any(
            matches[0].get(key) != declaration[key]
            for key in ("legacy_ops", "recovery_ops")
            if key in declaration
        ):
            raise ValueError("prior recovery failed-attempt snapshot differs")
    if snapshot.get("first5_financial_acceptance") is not None:
        raise ValueError("prior first-five recovery cannot carry financial acceptance")

    request = _read_json(request_path, "prior recovery request")
    expected_request = {
        "schema_version": REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_ROOT_GO",
        "operation": "recover-history-one",
        "config_sha256": _sha256(config_path),
        "preflight_sha256": _sha256(preflight_path),
        "runner_head": PRIOR_RECOVERY_SOURCE_SHA,
        "engine_head": old["engine"]["head"],
        "collection": collection_snapshot,
        "target": target_snapshot,
        "first5_financial_acceptance": None,
    }
    if request != expected_request:
        raise ValueError("prior recovery request binding differs")
    go = _read_json(go_path, "prior recovery GO")
    expected_go = {
        "schema_version": GO_VERSION,
        "status": "GO",
        "authorized_by": "ROOT_LEAD",
        "operation": "recover-history-one",
        "config_sha256": _sha256(config_path),
        "preflight_sha256": _sha256(preflight_path),
        "request_sha256": _sha256(request_path),
        "runner_head": PRIOR_RECOVERY_SOURCE_SHA,
        "engine_head": old["engine"]["head"],
        "collection_manifest_sha256": old["collection"]["manifest_sha256"],
        "target": target_snapshot,
        "first5_financial_acceptance": None,
    }
    if go != expected_go:
        raise ValueError("prior recovery GO binding differs")

    command = failure.get("command")
    expected_command_tail = [
        str(program),
        "_worker",
        "--config",
        str(config_path),
        "--go-file",
        str(go_path),
    ]
    expected_log = str(attempt.with_suffix(".log"))
    expected_samples = str(attempt.with_suffix(".rss.jsonl"))
    elapsed = failure.get("elapsed_seconds")
    peak = failure.get("peak_process_tree_rss_kib")
    returncode = failure.get("returncode")
    if (
        set(failure)
        != {
            "schema_version",
            "status",
            "returncode",
            "elapsed_seconds",
            "peak_process_tree_rss_kib",
            "limit_kib",
            "timeout_seconds",
            "command",
            "log",
            "samples",
        }
        or failure["schema_version"] != RESOURCE_VERSION
        or failure["status"] != "TIMEOUT"
        or type(returncode) is not int
        or returncode == 0
        or not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or elapsed < TIMEOUT_SECONDS
        or type(peak) is not int
        or not 0 < peak <= LIMIT_KIB
        or failure["limit_kib"] != LIMIT_KIB
        or failure["timeout_seconds"] != TIMEOUT_SECONDS
        or not isinstance(command, list)
        or len(command) != 7
        or not isinstance(command[0], str)
        or not Path(command[0]).is_absolute()
        or command[1:] != expected_command_tail
        or failure["log"] != expected_log
        or failure["samples"] != expected_samples
    ):
        raise ValueError("prior recovery TIMEOUT summary differs")
    _regular(Path(expected_log), "prior recovery log")
    _regular(Path(expected_samples), "prior recovery RSS samples")
    summary_artifacts = set(Path(old["execution_root"]).glob("execution.summary*"))
    if summary_artifacts != {attempt, Path(expected_log), Path(expected_samples)}:
        raise ValueError("unapproved prior recovery attempt")

    root = old_paths["destination"].absolute()
    current_paths = _target_paths(config)
    current_destination = current_paths["destination"].absolute()
    current_execution = Path(config["execution_root"]).absolute()
    for protected in (
        Path(old["execution_root"]).absolute(),
        checkout,
        Path(old["engine"]["checkout"]).absolute(),
    ):
        if any(
            candidate == protected
            or candidate.is_relative_to(protected)
            or protected.is_relative_to(candidate)
            for candidate in (current_destination, current_execution)
        ):
            raise ValueError("new recovery overlaps prior recovery evidence or source")
    return root, {
        "path": str(attempt),
        "sha256": _sha256(attempt),
        "recovery_ops": witness,
        "source_acceptance": acceptance_binding,
        "preflight": {"path": str(preflight_path), "sha256": _sha256(preflight_path)},
        "request": {"path": str(request_path), "sha256": _sha256(request_path)},
        "go": {"path": str(go_path), "sha256": _sha256(go_path)},
        "runner_head": PRIOR_RECOVERY_SOURCE_SHA,
        "engine_head": old["engine"]["head"],
        "execution_root": old["execution_root"],
        "output_root": str(root),
    }


def _target_paths(config: dict[str, Any]) -> dict[str, Path]:
    manifest = Path(config["collection"]["manifest"])
    ticker = config["target"]["ticker"]
    company_root = manifest.parent / "companies" / ticker
    destination = Path(config["target"]["history_parent"]) / config["target"]["history_basename"]
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
        or candidate_identities != {(row["ticker"], row["cik"]) for row in identities}
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
        for path in (
            paths["marker"],
            paths["old_receipt"],
            paths["receipt"],
            paths["destination"],
            *paths["company_root"].glob("history_recovery_receipt-*"),
            *paths["company_root"].glob("ops_build_receipt*"),
            *paths["company_root"].glob("build_manifest*"),
        )
    ):
        raise ValueError("target already has a marker, receipt, READY state, or selected output")
    company_attempts = paths["company_root"] / "operation_attempts"
    actual_attempts = sorted(company_attempts.glob("build-*"))
    declared_attempts = []
    failure_roots = []
    legacy_bindings = []
    recovery_bindings = []
    for declaration_item in target["approved_prior_failed_attempts"]:
        attempt = _pin(
            {k: declaration_item[k] for k in ("path", "sha256")}, "approved prior failed attempt"
        )
        failure = _read_json(attempt, "approved prior failed attempt")
        if "legacy_ops" in declaration_item:
            root, legacy_binding = _legacy_failure_root(
                config, attempt, failure, declaration_item["legacy_ops"]
            )
            legacy_bindings.append(legacy_binding)
        elif "recovery_ops" in declaration_item:
            root, recovery_binding = _recovery_failure_root(
                config, attempt, failure, declaration_item["recovery_ops"]
            )
            recovery_bindings.append(recovery_binding)
        else:
            if (
                attempt.parent != company_attempts
                or failure.get("result", {}).get("status") != "BUILD_FAILED"
            ):
                raise ValueError("prior build attempt is not an exact failed target attempt")
            declared_attempts.append(attempt)
            root_value = failure["result"].get("output_root")
            if "output_root" in failure and failure["output_root"] != root_value:
                raise ValueError("conflicting failed attempt output roots")
            root = _absolute(root_value, "failed attempt output root")
        failure_roots.append(_directory(root, "failed output root"))
    legacy_attempts = sorted(
        (manifest.parent / "execution" / target["ticker"]).glob("*.summary.json*")
    )
    declared_legacy = sorted(Path(row["path"]) for row in legacy_bindings)
    if legacy_attempts != declared_legacy:
        raise ValueError("target contains an unapproved prior legacy OPS attempt")
    if actual_attempts != sorted(declared_attempts):
        raise ValueError("target contains an unapproved prior build attempt")
    expected_state = "BUILD_FAILED" if declared_attempts else "RAW_COMPLETE"
    if row.state != expected_state:
        raise ValueError("target public state differs from approved recovery state")
    destination = paths["destination"].absolute()
    parent = _directory(Path(target["history_parent"]), "history parent")
    if destination != destination.resolve() or Path(target["history_parent"]) != parent:
        raise ValueError("new recovery paths contain symlink or noncanonical ancestry")
    abandoned = [
        _directory(Path(value), "abandoned output root")
        for value in target["abandoned_output_roots"]
    ]
    if len(set(failure_roots)) != len(failure_roots) or sorted(failure_roots) != sorted(abandoned):
        raise ValueError("abandoned roots differ from exact failed attempt output roots")
    execution = Path(config["execution_root"])
    if execution != execution.resolve():
        raise ValueError("execution root has unsafe ancestry")
    for root in abandoned:
        if (
            root == destination
            or root.is_relative_to(destination)
            or parent.is_relative_to(root)
            or execution.is_relative_to(root)
            or root.is_relative_to(execution)
        ):
            raise ValueError("new recovery output overlaps abandoned partial output")
    protected = [
        manifest.parent,
        Path(config["runner"]["checkout"]),
        Path(config["engine"]["checkout"]),
    ]
    payload = getattr(intake, "payload", None) or {}
    protected.extend(
        _absolute(item["source_run"], "intake source run")
        for item in payload.get("filings", [])
        if "source_run" in item
    )
    for root in protected:
        root = root.resolve()
        if (
            destination.is_relative_to(root)
            or root.is_relative_to(destination)
            or execution.is_relative_to(root)
            or root.is_relative_to(execution)
        ):
            raise ValueError("new recovery output overlaps source or collection")
    if execution.is_relative_to(destination) or destination.is_relative_to(execution):
        raise ValueError("recovery evidence and History output overlap")
    # Reject orphan partials from any recovery version, even if no receipt exists.
    known = set(abandoned)
    partials = [
        *parent.glob(f"{target['ticker']}-history-recovery-*"),
        *parent.glob(f"{target['ticker']}-t3v2-*"),
    ]
    for partial in partials:
        if partial.resolve() not in known:
            raise ValueError("unapproved prior recovery partial output")
    abandoned = [str(root) for root in abandoned]
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
            ]
            + legacy_bindings
            + recovery_bindings,
            "abandoned_output_roots": abandoned,
            "destination": str(destination),
            "receipt": str(paths["receipt"]),
        },
    }


def _validate_reported_reuse(
    config: dict[str, Any], collection: dict[str, Any]
) -> dict[str, Any] | None:
    declaration = config["reported_reuse"]
    if declaration is None:
        return None
    target = config["target"]
    paths = _target_paths(config)
    failed_root = _directory(
        Path(declaration["original_failed_output_root"]),
        "reported reuse original failed output root",
    )
    recovery_failures = [
        row
        for row in collection["target"]["prior_failed_attempts"]
        if row.get("runner_head") == PRIOR_RECOVERY_SOURCE_SHA
    ]
    if len(recovery_failures) != 1 or recovery_failures[0].get("output_root") != str(failed_root):
        raise ValueError("reported reuse does not bind the exact accepted R1 failed root")

    operational_root = _directory(
        Path(declaration["original_operational_root"]),
        "reported reuse original operational root",
    )
    operational_pins: dict[str, dict[str, str]] = {}
    for name, item in declaration["operational_roots"].items():
        root = _directory(Path(item["path"]), f"reported reuse operational root {name}")
        expected_root = operational_root / name / operational_root.name
        if root != expected_root:
            raise ValueError("reported reuse operational root path differs")
        manifest = _regular(root / "layer2_run_manifest.json", f"reported reuse {name} manifest")
        digest = _sha256(manifest)
        if digest != item["manifest_sha256"]:
            raise ValueError("reported reuse operational manifest hash differs")
        operational_pins[name] = {"path": str(root), "manifest_sha256": digest}

    source_stage = _directory(
        Path(declaration["source_stage"]["root"]), "reported reuse source stage"
    )
    clean_stage = _directory(
        Path(declaration["clean_stage"]["root"]), "reported reuse clean stage"
    )
    if not source_stage.is_relative_to(failed_root):
        raise ValueError("reported reuse source stage is outside the accepted R1 failed root")
    if clean_stage.is_relative_to(failed_root) or failed_root.is_relative_to(clean_stage):
        raise ValueError("reported reuse clean stage overlaps the immutable failed root")
    destination = Path(collection["target"]["destination"])
    execution = Path(config["execution_root"])
    for immutable in (source_stage, clean_stage, operational_root):
        if (
            destination.is_relative_to(immutable)
            or immutable.is_relative_to(destination)
            or execution.is_relative_to(immutable)
            or immutable.is_relative_to(execution)
        ):
            raise ValueError("reported reuse source overlaps output or execution evidence")
    source_manifest = _regular(
        source_stage / "history_manifest.json", "reported reuse source stage manifest"
    )
    clean_manifest = _regular(
        clean_stage / "history_manifest.json", "reported reuse clean stage manifest"
    )
    source_manifest_sha = _sha256(source_manifest)
    clean_manifest_sha = _sha256(clean_manifest)
    if (
        source_manifest_sha != declaration["source_stage"]["manifest_sha256"]
        or clean_manifest_sha != declaration["clean_stage"]["manifest_sha256"]
        or source_manifest_sha != clean_manifest_sha
    ):
        raise ValueError("reported reuse stage manifest identity differs")
    chunks = source_stage / ".chunks"
    if (
        not chunks.is_dir()
        or chunks.is_symlink()
        or chunks != chunks.resolve()
        or any(chunks.iterdir())
    ):
        raise ValueError("reported reuse source .chunks must exist and be strictly empty")
    if (clean_stage / ".chunks").exists() or (clean_stage / ".chunks").is_symlink():
        raise ValueError("reported reuse clean stage must contain declared files only")

    pins = {
        name: _pin(declaration[name], f"reported reuse {name}")
        for name in (
            "copy_report",
            "component_report",
            "root_attestation",
            "source_execution_log",
            "intake",
            "plan",
        )
    }
    if pins["intake"] != paths["intake"] or pins["plan"] != paths["plan"]:
        raise ValueError("reported reuse plan or intake path differs from collection target")
    if (
        declaration["intake"]["sha256"] != target["intake_sha256"]
        or declaration["plan"]["sha256"] != target["plan_sha256"]
    ):
        raise ValueError("reported reuse plan or intake hash differs from collection target")
    plan = _read_json(pins["plan"], "reported reuse plan")
    intake = _read_json(pins["intake"], "reported reuse intake")
    companies = plan.get("companies")
    if (
        intake.get("complete") is not True
        or intake.get("plan") != plan
        or not isinstance(companies, list)
        or len(companies) != 1
        or companies[0].get("ticker") != target["ticker"]
        or companies[0].get("cik") != target["cik"]
    ):
        raise ValueError("reported reuse plan/intake target identity differs")

    copy_report = _read_json(pins["copy_report"], "reported reuse copy report")
    required_copy = {
        "schema_version": "independent-reported-stage-clean-copy-v1",
        "status": "PASS_DECLARED_FILES_CLEAN_COPY_ONLY",
        "history_ready": False,
        "source_generation_sha": REPORTED_GENERATION_SOURCE_SHA,
        "recovery_source_sha": REPORTED_RECOVERY_SOURCE_SHA,
        "original_failed_output_root": str(failed_root),
        "original_operational_root": str(operational_root),
        "source_stage": {
            "root": str(source_stage),
            "manifest_sha256": source_manifest_sha,
        },
        "clean_stage": {
            "root": str(clean_stage),
            "manifest_sha256": clean_manifest_sha,
        },
        "original_before_after_equal": True,
        "strictly_empty_chunks": True,
    }
    if any(copy_report.get(key) != value for key, value in required_copy.items()):
        raise ValueError("reported reuse clean-copy report identity differs")
    if copy_report.get("fixture_kind") not in {"ACTUAL", "CACHED_TEST", "SYNTHETIC_TEST"}:
        raise ValueError("reported reuse clean-copy fixture kind differs")
    protected_inventory = copy_report.get("protected_inventory")
    if not isinstance(protected_inventory, dict):
        raise TypeError("reported reuse clean-copy protected inventory is missing")
    _pin(protected_inventory, "reported reuse protected inventory")
    copied_files = copy_report.get("copied_files")
    if copy_report.get("copied_file_count") != 37 or not isinstance(copied_files, list):
        raise ValueError("reported reuse clean-copy inventory is incomplete")
    copied: dict[str, str] = {}
    for item in copied_files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("reported reuse copied file declaration differs")
        relative = Path(item["path"])
        digest = _sha(item["sha256"], "reported reuse copied file")
        if relative.is_absolute() or ".." in relative.parts or str(relative) in copied:
            raise ValueError("reported reuse copied file path is unsafe or duplicated")
        copied[str(relative)] = digest
    if len(copied) != 37 or copied.get("history_manifest.json") != clean_manifest_sha:
        raise ValueError("reported reuse clean-copy inventory count differs")
    source_files = {
        str(path.relative_to(source_stage)): _sha256(_regular(path, "reported reuse source file"))
        for path in source_stage.rglob("*")
        if path.is_file()
    }
    clean_files = {
        str(path.relative_to(clean_stage)): _sha256(_regular(path, "reported reuse clean file"))
        for path in clean_stage.rglob("*")
        if path.is_file()
    }
    if source_files != copied or clean_files != copied:
        raise ValueError("reported reuse clean copy is incomplete or differs from its source")

    component = _read_json(pins["component_report"], "reported reuse component report")
    if (
        component.get("schema_version") != "independent-staged-reported-component-audit-v1"
        or component.get("verdict") != "PASS_STAGED_REPORTED_COMPONENT_ONLY"
        or component.get("verification_level") != "FULL_STAGED_REPORTED_PASS"
        or component.get("history_ready") is not False
        or component.get("source_generation_sha") != REPORTED_GENERATION_SOURCE_SHA
        or component.get("recovery_source_sha") != REPORTED_RECOVERY_SOURCE_SHA
        or component.get("original_stage") != required_copy["source_stage"]
        or component.get("copy_report") != declaration["copy_report"]
        or component.get("original_operational_root") != str(operational_root)
        or component.get("operational_roots") != operational_pins
        or component.get("stage_manifest")
        != {"path": str(clean_manifest), "sha256": clean_manifest_sha}
        or component.get("source_intake") != declaration["intake"]
        or component.get("plan") != declaration["plan"]
        or component.get("source_execution_log") != declaration["source_execution_log"]
    ):
        raise ValueError("reported reuse component report binding differs")

    proof = _read_json(pins["root_attestation"], "reported reuse root attestation")
    if (
        proof.get("version") != "reported-stage-recovery-v1"
        or proof.get("status") != "PASS"
        or proof.get("generation_source_identity") != REPORTED_GENERATION_SOURCE_SHA
        or proof.get("recovery_source_identity") != REPORTED_RECOVERY_SOURCE_SHA
        or proof.get("staged_manifest_sha256") != clean_manifest_sha
        or proof.get("intake_sha256") != declaration["intake"]["sha256"]
        or proof.get("plan") != plan
        or proof.get("verification_report") != declaration["component_report"]
        or proof.get("source_execution_log") != declaration["source_execution_log"]
        or proof.get("operational_manifest_sha256")
        != {name: item["manifest_sha256"] for name, item in operational_pins.items()}
    ):
        raise ValueError("reported reuse root attestation binding differs")
    if component.get("input_fingerprint") != proof.get("input_fingerprint"):
        raise ValueError("reported reuse component input fingerprint differs")
    return {
        **declaration,
        "original_failed_output_root": str(failed_root),
        "original_operational_root": str(operational_root),
        "operational_roots": operational_pins,
        "source_stage": required_copy["source_stage"],
        "clean_stage": required_copy["clean_stage"],
    }


def _snapshot(config: dict[str, Any]) -> dict[str, Any]:
    collection = _validate_collection_target(config)
    value = {
        "runner": _verify_runner_source(config),
        "engine": _verify_engine_source(config),
        "collection": collection,
        "first5_financial_acceptance": _verify_financial_acceptance(config),
    }
    reported_reuse = _validate_reported_reuse(config, collection)
    if reported_reuse is not None:
        value["reported_reuse"] = reported_reuse
    return value


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
        "first5_financial_acceptance": preflight_value["snapshot"]["first5_financial_acceptance"],
        "target": preflight_value["snapshot"]["collection"]["target"],
    }
    if preflight_value["snapshot"].get("reported_reuse") is not None:
        value["reported_reuse"] = preflight_value["snapshot"]["reported_reuse"]
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
        "first5_financial_acceptance": preflight_value["snapshot"]["first5_financial_acceptance"],
        "target": preflight_value["snapshot"]["collection"]["target"],
    }
    if preflight_value["snapshot"].get("reported_reuse") is not None:
        expected_request["reported_reuse"] = preflight_value["snapshot"]["reported_reuse"]
    if request != expected_request:
        raise ValueError("History recovery request changed")
    expected_go = {
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
        "first5_financial_acceptance": preflight_value["snapshot"]["first5_financial_acceptance"],
    }
    if preflight_value["snapshot"].get("reported_reuse") is not None:
        expected_go["reported_reuse"] = preflight_value["snapshot"]["reported_reuse"]
    return config, expected_go


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
    reported_reuse = snapshot.get("reported_reuse")
    if reported_reuse is None:
        publication = history.build_history(
            intake_manifest=paths["intake"], output_root=paths["destination"]
        )
    else:
        publication = history.recover_reported_history(
            staged_publication=Path(reported_reuse["clean_stage"]["root"]),
            output_root=paths["destination"],
            intake_manifest=Path(reported_reuse["intake"]["path"]),
            operational_root=Path(reported_reuse["original_operational_root"]),
            attestation=Path(reported_reuse["root_attestation"]["path"]),
            expected_attestation_sha256=reported_reuse["root_attestation"]["sha256"],
            trusted_exclusive_parent=True,
        )
    history.HistoryPublicationReader(publication).verify_all()
    public_receipt_binding = None
    if reported_reuse is not None:
        public_receipt = _regular(
            paths["destination"] / "reported_recovery_receipt.json",
            "public reported recovery receipt",
        )
        public_value = _read_json(public_receipt, "public reported recovery receipt")
        if (
            public_value.get("version") != "reported-stage-recovery-v1"
            or public_value.get("status") != "COMPLETE"
            or public_value.get("generation_source_identity")
            != reported_reuse["generation_source_head"]
            or public_value.get("recovery_source_identity")
            != reported_reuse["recovery_source_head"]
            or public_value.get("source_stage") != reported_reuse["clean_stage"]["root"]
            or public_value.get("source_manifest_sha256")
            != reported_reuse["clean_stage"]["manifest_sha256"]
            or public_value.get("source_intake_sha256") != reported_reuse["intake"]["sha256"]
            or public_value.get("verification_report_sha256")
            != reported_reuse["component_report"]["sha256"]
            or public_value.get("consumer_publication") != str(Path(publication).absolute())
        ):
            raise ValueError("public reported recovery receipt identity differs")
        public_receipt_binding = {
            "path": str(public_receipt),
            "sha256": _sha256(public_receipt),
        }
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
    if reported_reuse is not None:
        receipt["reported_reuse"] = reported_reuse
        receipt["public_reported_recovery_receipt"] = public_receipt_binding
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
