#!/usr/bin/env python3
"""Serial, resumable company preparation through the existing governed producers."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from sec_xbrl import analysis, collection_operations
from sec_xbrl.metrics.screening import expanded_analysis_profile
from sec_xbrl.screening.common import (
    canonical_json,
    contained_file,
    real_directory,
    regular_file,
    require_cik,
    require_ticker,
    sha256_file,
)
from tools import universe50_t3v2_ops as resource_ops

VERSION = "nasdaq100-company-ops-v1"
STAGES = ("collect", "history", "annual", "quarterly")
LIMIT_KIB = 16 * 1024 * 1024
MIN_FREE_BYTES = 16 * 1024**3
MIN_AVAILABLE_KIB = 4 * 1024**2
TIMEOUT_SECONDS = 3600
SOURCE = Path(__file__).resolve().parents[1]
PROJECT = Path(subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=SOURCE, text=True).strip()).resolve().parent


def _json(path: Path) -> dict:
    value = json.loads(regular_file(path, "operator JSON").read_bytes())
    if not isinstance(value, dict):
        raise TypeError("operator JSON must be an object")
    return value


def _new(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(payload) + "\n")
    return path


def _pin(declaration: dict) -> Path:
    if set(declaration) != {"path", "sha256"} or not Path(declaration["path"]).is_absolute():
        raise ValueError("operator pin requires absolute path and SHA-256")
    path = regular_file(Path(declaration["path"]), "operator pinned input")
    if sha256_file(path) != declaration["sha256"]:
        raise ValueError("operator input differs from pin")
    return path


def load_config(path: Path, expected_sha256: str) -> dict:
    config = _json(_pin({"path": str(path.absolute()), "sha256": expected_sha256}))
    required = {"schema_version", "operator_sha256", "identity", "universe_config", "run_root", "work_root",
                "history_root", "analysis_root", "submissions_roots", "package_cache", "index_cache",
                "taxonomy_cache", "companies", "collection_manifest"}
    if set(config) != required or config["schema_version"] != VERSION:
        raise ValueError("unsupported Nasdaq operator configuration")
    if sha256_file(Path(__file__).resolve()) != config["operator_sha256"]:
        raise ValueError("operator source differs from configured freeze")
    identity = _json(_pin(config["identity"]))
    confirmed = {(row["ticker"], row.get("cik")) for row in identity["securities"]
                 if row["status"] in {"SUPPORTED_K_Q", "SUPPORTED_PARTIAL_K_Q"}}
    universe_path = _pin(config["universe_config"])
    collection_manifest = _pin(config["collection_manifest"])
    universe = collection_operations.load_universe_config(universe_path)
    if universe.completed_fiscal_years != 5 or universe.analytical_fiscal_years != 4:
        raise ValueError("operator requires the approved five-input/four-display fiscal window")
    if universe.as_of_date != date(2026, 10, 25):
        raise ValueError("first expansion must preserve the approved financial cutoff")
    companies = config["companies"]
    if not isinstance(companies, list) or not companies:
        raise ValueError("operator requires confirmed supported companies")
    targets = {(row.ticker, row.cik) for row in universe.companies}
    actual = []
    for row in companies:
        if set(row) - {"ticker", "cik", "source_runs", "history_build_options"} or not {"ticker", "cik", "source_runs"} <= set(row):
            raise ValueError("invalid supported company declaration")
        ticker, cik = require_ticker(row["ticker"]), require_cik(row["cik"])
        actual.append((ticker, cik))
        if ticker != row["ticker"] or not isinstance(row["source_runs"], list):
            raise ValueError("operator company identity is not canonical")
        for source in row["source_runs"]:
            real_directory(Path(source), "reused intake")
    if not set(actual) <= confirmed:
        raise ValueError("operator company is not confirmed as supported in pinned SEC identity evidence")
    if set(actual) != targets or len(actual) != len(targets) or len({cik for _, cik in actual}) != len(actual):
        raise ValueError("operator companies differ from unique CIK collection scope")
    for key in ("run_root", "work_root", "history_root", "analysis_root", "package_cache", "index_cache", "taxonomy_cache"):
        candidate = Path(config[key])
        if not candidate.is_absolute() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
            raise ValueError("operator paths must be explicit absolute non-alias paths")
    scopes = {
        "run_root": PROJECT / "data/raw/nasdaq100_20261111",
        "work_root": PROJECT / "work/nasdaq100-expansion-20261111",
        "history_root": PROJECT / "data/processed/nasdaq100_20261111",
        "analysis_root": PROJECT / "data/processed/nasdaq100_20261111",
        "package_cache": PROJECT / "data/raw/nasdaq100_20261111",
        "index_cache": PROJECT / "data/raw/nasdaq100_20261111",
    }
    if any(not Path(config[key]).is_relative_to(scope) or Path(config[key]) == scope for key, scope in scopes.items()):
        raise ValueError("operator mutation root is outside the authorized expansion scope")
    if not config["submissions_roots"]:
        raise ValueError("operator requires captured offline submissions")
    for item in config["submissions_roots"]:
        real_directory(Path(item), "offline submissions")
    run = Path(config["run_root"])
    if collection_manifest != run / "collection_manifest.json":
        raise ValueError("collection manifest pin differs from the declared run")
    if run == Path(config["work_root"]) or run == Path(config["history_root"]) or run == Path(config["analysis_root"]):
        raise ValueError("operator output stages must have separate roots")
    return config


def _identity(config_path: Path, expected: str, ticker: str, stage: str) -> dict:
    return {"config": {"path": str(config_path.absolute()), "sha256": expected}, "ticker": ticker, "stage": stage}


def _completion(config: dict, ticker: str, stage: str) -> Path:
    return Path(config["work_root"]) / "completed" / ticker / f"{stage}.json"


def _verify_completion(path: Path, identity: dict) -> dict:
    payload = _json(path)
    if payload.get("status") != "PASS" or payload.get("identity") != identity:
        raise ValueError("operator completion scope differs")
    for pin in payload["outputs"]:
        _pin(pin)
    return payload


def _accepted_scratch(config: dict, ticker: str) -> dict:
    """Remove only this new intake's extraction after the ingestor accepted its Raw."""
    intake = Path(config["run_root"]) / "companies" / ticker / "intake"
    if intake.resolve() != intake:
        raise ValueError("new intake path traverses an alias")
    result = _json(intake / "history_intake.json")
    removed, allocated = [], 0
    for row in result["filings"]:
        filing = row["filing"]
        if row["status"] not in {"INGESTED", "REUSED"} or Path(row["source_run"]) != intake:
            continue
        cik = require_cik(filing["cik"])
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", filing["accession"]):
            raise ValueError("accepted accession is not canonical")
        accession = filing["accession"].replace("-", "")
        snapshot = contained_file(intake, f"snapshots/{cik}/{accession}/layer1_manifest.json", "accepted Raw snapshot")
        scratch = intake / "extracted" / cik / accession
        if not scratch.exists():
            continue
        real_directory(scratch, "new extraction")
        descendants = [scratch, *scratch.rglob("*")]
        if any(path.is_symlink() for path in descendants):
            raise ValueError("new extraction contains an unexpected alias")
        allocated += sum(path.stat().st_blocks * 512 for path in descendants)
        removed.append({"path": str(scratch), "accepted_raw_manifest_sha256": sha256_file(snapshot)})
        shutil.rmtree(scratch)
    return {"removed": removed, "allocated_bytes": allocated}


def _work(config: dict, ticker: str, stage: str) -> tuple[list[Path], dict]:
    company, = [row for row in config["companies"] if row["ticker"] == ticker]
    manifest = Path(config["run_root"]) / "collection_manifest.json"
    company_root = Path(config["run_root"]) / "companies" / ticker
    extra = {}
    if stage == "collect":
        intake = company_root / "intake" / "history_intake.json"
        plan = _json(company_root / "plan.json")
        prior = collection_operations._attest_intake(intake, plan)
        if prior.complete and not prior.error:
            extra["adopted_existing_raw"] = True
        else:
            collection_operations.collect_universe(
                manifest_path=manifest, package_cache=Path(config["package_cache"]), index_cache=Path(config["index_cache"]),
                taxonomy_cache=Path(config["taxonomy_cache"]), source_runs={ticker: tuple(map(Path, company["source_runs"]))},
                selected_tickers=(ticker,),
            )
        attested = collection_operations._attest_intake(intake, _json(company_root / "plan.json"))
        if attested.error:
            raise ValueError("company Raw intake attestation failed")
        extra["scratch_cleanup"] = _accepted_scratch(config, ticker)
        if not attested.complete:
            raise ValueError("company Raw intake is incomplete; accession outcomes remain resumable")
        return [intake], extra
    if stage == "history":
        options = company.get("history_build_options")
        collection_operations.build_universe(
            manifest_path=manifest, output_root=Path(config["history_root"]), selected_tickers=(ticker,),
            validation_mode="routine", history_build_options={ticker: options} if options is not None else None,
        )
        marker_path = company_root / "build_manifest.json"
        marker = _json(marker_path)
        if marker.get("status") != "READY":
            raise ValueError("company History has no accepted build completion")
        return [marker_path, regular_file(Path(marker["history_manifest"]), "completed History")], extra
    marker = _json(company_root / "build_manifest.json")
    publication = Path(marker["publication"])
    annual = stage == "annual"
    destination = Path(config["analysis_root"]) / stage / ticker
    if annual and not any(row["form"] in {"10-K", "10-K/A"}
                          for row in _json(company_root / "plan.json")["companies"][0]["filings"]):
        return [Path(marker["history_manifest"])], {"availability": "UNAVAILABLE_NO_ANNUAL_BASELINE"}
    if destination.exists():
        raise ValueError("unreceipted analysis destination exists; retain it for explicit recovery")
    analysis.prepare_analysis(
        publication=publication, destination=destination, tickers=(ticker,), fiscal_years=5,
        configuration={ticker: {"core_rows": expanded_analysis_profile()}} if annual else None,
        period_mode="ANNUAL" if annual else "QUARTERLY", include_year_end_balances=annual,
        include_quarter_source_evidence=not annual,
    )
    return [destination / "analysis_manifest.json"], extra


def _worker(config_path: Path, expected: str, ticker: str, stage: str, attempt: Path) -> None:
    resource_ops.install_parent_death_guard()
    config = load_config(config_path, expected)
    outputs, extra = _work(config, ticker, stage)
    _new(attempt / "outputs.json", {
        "outputs": [{"path": str(path.absolute()), "sha256": sha256_file(path)} for path in outputs], **extra,
    })


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(PYTHONPATH=str(SOURCE / "src") + os.pathsep + str(SOURCE), POLARS_MAX_THREADS="2",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               SEC_XBRL_T3V2_SUPERVISOR_PID=str(os.getpid()))
    if not env.get("SEC_USER_AGENT"):
        path = SOURCE / ".env"
        if not path.exists():
            path = PROJECT / ".env"
        if path.is_file():
            for line in path.read_text().splitlines():
                key, separator, value = line.removeprefix("export ").partition("=")
                if separator and key.strip() == "SEC_USER_AGENT":
                    env[key.strip()] = value.strip().strip("\"'")
    return env


def run_stage(config_path: Path, expected: str, ticker: str, stage: str) -> Path:
    config = load_config(config_path, expected)
    work = Path(config["work_root"])
    work.mkdir(parents=True, exist_ok=True)
    with resource_ops.heavy_lock(work):
        return _run_locked_stage(config_path, expected, ticker, stage)


def _run_locked_stage(config_path: Path, expected: str, ticker: str, stage: str) -> Path:
    config = load_config(config_path, expected)
    if stage not in STAGES or ticker not in {row["ticker"] for row in config["companies"]}:
        raise ValueError("unknown operator stage or company")
    identity = _identity(config_path, expected, ticker, stage)
    receipt = _completion(config, ticker, stage)
    if receipt.exists():
        _verify_completion(receipt, identity)
        return receipt
    for prerequisite in STAGES[:STAGES.index(stage)]:
        _verify_completion(_completion(config, ticker, prerequisite), _identity(config_path, expected, ticker, prerequisite))
    work = Path(config["work_root"])
    attempt = work / "attempts" / ticker / stage / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    started_at = datetime.now(UTC).isoformat()
    before = shutil.disk_usage(work).free
    if before < MIN_FREE_BYTES:
        raise RuntimeError("insufficient free disk before company stage")
    command = [sys.executable, "-m", "tools.nasdaq100_ops", "_worker", "--config", str(config_path.absolute()),
               "--config-sha256", expected, "--ticker", ticker, "--stage", stage, "--attempt", str(attempt)]
    status, peak, code = "INTERRUPTED", 0, None
    started = time.monotonic()
    try:
        with (
            (attempt / "worker.log").open("x") as log,
            (attempt / "rss.jsonl").open("x") as samples,
            subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=SOURCE,
                             env=_environment(), start_new_session=True) as process,
        ):
            def memory(pid):
                if shutil.disk_usage(work).free < MIN_FREE_BYTES:
                    raise RuntimeError("minimum free disk reached during company stage")
                available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                                 if line.startswith("MemAvailable:"))
                if available < MIN_AVAILABLE_KIB:
                    raise RuntimeError("minimum available RAM reached during company stage")
                return resource_ops.process_tree_rss_kib(pid)

            code, peak, stopped, _elapsed = resource_ops.supervise_owned_process(
                process, samples, limit_kib=LIMIT_KIB, timeout_seconds=TIMEOUT_SECONDS, rss_reader=memory,
            )
            status = stopped or ("PASS" if code == 0 else "FAIL")
    finally:
        _new(attempt / "resource.json", {
            "identity": identity, "status": status, "returncode": code, "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(), "elapsed_seconds": time.monotonic() - started,
            "peak_process_tree_rss_kib": peak, "free_bytes_before": before, "free_bytes_after": shutil.disk_usage(work).free,
        })
    if status != "PASS":
        raise RuntimeError(f"company stage failed with {status}; see {attempt}")
    result = _json(attempt / "outputs.json")
    return _new(receipt, {"schema_version": VERSION, "status": "PASS", "identity": identity, **result,
                          "resource_receipt": str(attempt / "resource.json")})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-stage", "_worker"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--ticker")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--attempt", type=Path)
    args = parser.parse_args()
    if args.command == "run-stage":
        print(run_stage(args.config, args.config_sha256, args.ticker, args.stage))
    else:
        _worker(args.config, args.config_sha256, args.ticker, args.stage, args.attempt)


if __name__ == "__main__":
    main()
