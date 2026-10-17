#!/usr/bin/env python3
"""Fail-closed exact-50 T3v2 operations runner."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sec_xbrl import collection_operations as ops
from sec_xbrl import history

SOURCE_SHA = "8a1b40ab1008fb9109a27b2a5bcea02a257e1694"
INPUT_HASHES = {
    "universe_config": "badbeb1bae956dcb29edd71787b6bb6e44fb5a359280598907378a45d48086d7",
    "history_matrix": "daddaa7b25809aa67c69556cafe296baf9b01bf510bd4ec694b37ab8e4395ddd",
    "candidate": "cbcf87dd3deedb75035b7bacc752af93d55d96a3f63ed577d416b97b3b994249",
    "independent_raw_report": "85dd76ba38025ef233dcf6f70fb827088c29d5f56203ace5fff65907a1e0afe2",
    "lead_t3_acceptance": "c6e8c993b1c065c11b7ce7ed910587ef4f9809adf300bb030d222830b9d86081",
}
FIRST5 = ("TXN", "HD", "JNJ", "CVX", "NEE")
LIMIT_KIB, TIMEOUT = 16 * 1024 * 1024, 10_800
CONFIG_SCHEMA = "universe50-t3v2-ops-config-v1"
PREFLIGHT_SCHEMA = "universe50-t3v2-ops-preflight-v1"
GO_SCHEMA = "universe50-t3v2-stage-go-v1"
_SUPERVISOR_CAPABILITY = object()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path: Path, value: dict[str, Any], label: str) -> None:
    ops._write_once_json(path, value, label=label)


def identity(path: Path) -> tuple[int, int, int, int]:
    value = path.stat(follow_symlinks=False)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe file: {path}")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@contextmanager
def pinned(path: Path, sha256: str) -> Iterator[dict[str, Any]]:
    path = path.absolute()
    before = identity(path)
    if digest(path) != sha256:
        raise ValueError(f"hash mismatch: {path}")
    yield {"path": str(path), "sha256": sha256, "file_identity": list(before)}
    if identity(path) != before or digest(path) != sha256:
        raise ValueError(f"file changed during validation: {path}")


def modules(config: dict[str, Any]) -> dict[str, Any]:
    engine = Path(config["engine_checkout"]).resolve()
    head = subprocess.run(
        ["git", "-C", str(engine), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(engine), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != SOURCE_SHA or dirty:
        raise ValueError("engine checkout must be clean at accepted 8a1b40a source")
    engine_paths = {
        "collection_operations": engine / "src/sec_xbrl/collection_operations.py",
        "history": engine / "src/sec_xbrl/history.py",
        "exploration_graph": engine / "src/sec_xbrl/longitudinal/exploration_graph.py",
        "materialization": engine / "src/sec_xbrl/longitudinal/materialization.py",
    }
    imported = {
        "collection_operations": Path(ops.__file__).resolve(),
        "history": Path(history.__file__).resolve(),
    }
    if any(imported[name] != engine_paths[name].resolve() for name in imported):
        raise ValueError("imported modules do not come from configured engine_checkout")
    files = {
        name: {"path": str(path.resolve()), "sha256": digest(path)}
        for name, path in engine_paths.items()
    }
    aggregate = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    runner = Path(__file__).resolve()
    return {
        "program": {"path": str(runner), "sha256": digest(runner)},
        "engine": {
            "checkout": str(engine),
            "head": head,
            "clean": True,
            "files": files,
            "aggregate_sha256": aggregate,
        },
    }


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    config = read_json(path)
    if config.get("schema_version") != CONFIG_SCHEMA or config.get("source_sha") != SOURCE_SHA:
        raise ValueError("unsupported config or source SHA")
    if Path(config["collection_root"]).name != config.get("run_id"):
        raise ValueError("collection_root basename must equal run_id")
    if not isinstance(config.get("engine_checkout"), str):
        raise TypeError("engine_checkout is required")
    if config.get("first5") != list(FIRST5):
        raise ValueError("first5 scope differs")
    if config.get("limits") != {
        "process_tree_rss_kib": LIMIT_KIB,
        "polars_max_threads": 2,
        "one_heavy_process": True,
        "timeout_seconds": TIMEOUT,
    }:
        raise ValueError("resource limits differ")
    for name, expected in INPUT_HASHES.items():
        item = config.get("artifacts", {}).get(name)
        if not isinstance(item, dict) or item.get("sha256") != expected:
            raise ValueError(f"non-authoritative artifact: {name}")
    return config, digest(path)


def artifact(config: dict[str, Any], name: str) -> tuple[Path, str]:
    item = config["artifacts"][name]
    return Path(item["path"]).absolute(), item["sha256"]


def validate_authoritative(config: dict[str, Any]) -> dict[str, Any]:
    data, bindings = {}, {}
    for name in INPUT_HASHES:
        path, sha = artifact(config, name)
        with pinned(path, sha) as binding:
            data[name], bindings[name] = read_json(path), binding
    universe, matrix, candidate = data["universe_config"], data["history_matrix"], data["candidate"]
    audit, lead = data["independent_raw_report"], data["lead_t3_acceptance"]
    rows = candidate.get("selection")
    tickers = [row.get("ticker") for row in rows] if isinstance(rows, list) else []
    configured = [row.get("ticker") for row in universe.get("companies", [])]
    if universe.get("as_of_date") != "2026-10-10" or universe.get("collection") != {
        "analytical_fiscal_years": 4,
        "completed_fiscal_years": 5,
        "include_subsequent_quarters": True,
    }:
        raise ValueError("financial cutoff or annual windows differ")
    if len(tickers) != 50 or len(set(tickers)) != 50 or set(tickers) != set(configured):
        raise ValueError("exact-50 membership differs")
    if (
        "PEP" in tickers
        or "KDP" not in tickers
        or sum(row.get("selected_filings", -1) for row in rows) != 1097
    ):
        raise ValueError("PEP/KDP or 1097 filing invariant differs")
    if any(row.get("intake_complete") is not True for row in rows):
        raise ValueError("candidate contains incomplete intake")
    matrix_rows = matrix.get("companies", [])
    if len(matrix_rows) != 49 or {r["ticker"] for r in matrix_rows} != set(tickers) - {"KDP"}:
        raise ValueError("accepted 49 matrix differs")
    if (
        candidate.get("parents", {}).get("accepted_49_input_matrix", {}).get("sha256")
        != INPUT_HASHES["history_matrix"]
    ):
        raise ValueError("candidate does not bind accepted matrix")
    decision = candidate.get("membership_decision", {})
    if (
        decision.get("replacement", {}).get("ticker") != "KDP"
        or decision.get("held_outside_membership", {}).get("ticker") != "PEP"
    ):
        raise ValueError("membership decision differs")
    if (
        audit.get("verdict") != "PASS_ACTUAL_RAW_KDP_ONLY"
        or audit.get("input_selection_verdict") != "PASS_EXACT50_METADATA_INPUT_SELECTION_ONLY"
    ):
        raise ValueError("independent Raw selection is not PASS")
    if (
        audit.get("metadata_correction", {}).get("v2_candidate_sha256") != INPUT_HASHES["candidate"]
        or audit.get("input_selection", {}).get("unique_cik_accessions") != 1097
    ):
        raise ValueError("audit candidate binding differs")
    if (
        lead.get("status") != "LOCALLY_ACCEPTED_T3_SOURCE_AND_CACHED_TINY_ONLY"
        or lead.get("source_sha") != SOURCE_SHA
    ):
        raise ValueError("accepted source binding differs")
    return {"pinned_artifacts": bindings, "tickers": tickers, "selected_filings": 1097}


def preflight_path(config: dict[str, Any]) -> Path:
    return Path(config["collection_root"]) / "ops_preflight.json"


def config_preflight(config_path: Path) -> Path:
    config_path = config_path.absolute()
    config, config_sha = load_config(config_path)
    value = {
        "schema_version": PREFLIGHT_SCHEMA,
        "status": "PREPARED",
        "run_id": config["run_id"],
        "source_sha": SOURCE_SHA,
        "config": {"path": str(config_path), "sha256": config_sha},
        "modules": modules(config),
        "authoritative": validate_authoritative(config),
        "scope": {
            "membership": 50,
            "selected_filings": 1097,
            "first5": list(FIRST5),
            "financial_cutoff": "2026-10-10",
            "annual_input_years": 5,
            "annual_display_years": 4,
            "quarter_input_count": 17,
            "quarter_display_buckets": [
                "2024Q4",
                "2025Q1",
                "2025Q2",
                "2025Q3",
                "2025Q4",
                "2026Q1",
                "2026Q2",
                "2026Q3",
            ],
        },
        "execution": "RAW_AND_HISTORY_REQUIRE_SEPARATE_STAGE_GO",
    }
    write_once(preflight_path(config), value, "operations preflight")
    return preflight_path(config)


def validate_preflight(config_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config_path = config_path.absolute()
    config, sha = load_config(config_path)
    path, value = preflight_path(config), read_json(preflight_path(config))
    if value.get("schema_version") != PREFLIGHT_SCHEMA or value.get("status") != "PREPARED":
        raise ValueError("preflight is not PREPARED")
    if value.get("config") != {"path": str(config_path), "sha256": sha} or value.get(
        "modules"
    ) != modules(config):
        raise ValueError("config or modules changed after preflight")
    validate_authoritative(config)
    return config, value, path


def prepare_new_collection(config_path: Path) -> Path:
    config, _, _ = validate_preflight(config_path)
    universe = read_json(artifact(config, "universe_config")[0])
    candidate = read_json(artifact(config, "candidate")[0])
    universe["universe_id"] = f"exact50-t3v2-{config['run_id']}"
    new_config = Path(config["collection_root"]) / "exact50_collection_config.json"
    write_once(new_config, universe, "fresh exact-50 config")
    result = ops.prepare_universe(
        config_path=new_config,
        run_root=Path(config["collection_root"]),
        existing_plans={r["ticker"]: Path(r["plan"]) for r in candidate["selection"]},
        offline=True,
    )
    status = ops.read_universe_status(manifest_path=result)
    if status.requested_companies != 50 or status.prepared_companies != 50:
        raise ValueError("fresh collection did not prepare exact-50")
    return result


def validate_go(
    config_path: Path, operation: str, tickers: Sequence[str], go_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    config, preflight, preflight_file = validate_preflight(config_path)
    _, config_sha = load_config(config_path)
    expected = {
        "schema_version": GO_SCHEMA,
        "status": "GO",
        "operation": operation,
        "run_id": config["run_id"],
        "source_sha": SOURCE_SHA,
        "ops_config_sha256": config_sha,
        "preflight_sha256": digest(preflight_file),
        "program_sha256": preflight["modules"]["program"]["sha256"],
        "engine_modules_sha256": preflight["modules"]["engine"]["aggregate_sha256"],
        "tickers": list(tickers),
    }
    if read_json(go_path) != expected:
        raise ValueError("GO does not exactly bind stage, scope, source, and inputs")
    return config, preflight


def manifest(config: dict[str, Any]) -> Path:
    value = Path(config["collection_root"]) / "collection_manifest.json"
    if not value.is_file():
        raise ValueError("fresh collection is not prepared")
    return value


def candidate_rows(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path, sha = artifact(config, "candidate")
    with pinned(path, sha):
        return {r["ticker"]: r for r in read_json(path)["selection"]}


def adopt_accepted_raw(config_path: Path, tickers: Sequence[str], go_path: Path) -> Path:
    chosen = tuple(t.upper() for t in tickers)
    config, preflight = validate_go(config_path, "adopt-accepted-raw", chosen, go_path)
    rows, target_manifest = candidate_rows(config), manifest(config)
    run = ops._attest_run(target_manifest)
    for ticker in chosen:
        row = rows[ticker]
        root = target_manifest.parent / "companies" / ticker
        source_plan, source_intake, new_plan = (
            Path(row["plan"]),
            Path(row["intake"]),
            root / "plan.json",
        )
        evidence, adopted = [], []
        if digest(new_plan) != row["plan_sha256"]:
            raise ValueError(f"fresh plan differs: {ticker}")
        with (
            pinned(source_plan, row["plan_sha256"]),
            pinned(source_intake, row["intake_sha256"]) as intake_pin,
        ):
            plan, intake = read_json(source_plan), read_json(source_intake)
            if (
                plan != read_json(new_plan)
                or intake.get("plan") != plan
                or intake.get("complete") is not True
            ):
                raise ValueError(f"source plan/intake differs: {ticker}")
            for outcome in intake.get("filings", []):
                if outcome.get("status") not in {"REUSED", "INGESTED"}:
                    raise ValueError(f"source outcome failed: {ticker}")
                filing, source = outcome["filing"], Path(outcome["source_run"]).absolute()
                layer1 = (
                    source
                    / "snapshots"
                    / filing["cik"]
                    / filing["accession"].replace("-", "")
                    / "layer1_manifest.json"
                )
                before, sha = identity(layer1), digest(layer1)
                snapshot = history._load_history_source_snapshot(
                    layer1.parent, filing["cik"], filing["accession"]
                )
                history._validate_snapshot_plan(snapshot, filing)
                del snapshot
                if identity(layer1) != before or digest(layer1) != sha:
                    raise ValueError("snapshot changed during validation")
                adopted.append(
                    {
                        "ticker": ticker,
                        "filing": filing,
                        "status": "REUSED",
                        "source_run": str(source),
                    }
                )
                evidence.append(
                    {
                        "accession": filing["accession"],
                        "source_run": str(source),
                        "layer1_manifest": str(layer1),
                        "layer1_manifest_sha256": sha,
                        "file_identity": list(before),
                    }
                )
            if len(adopted) != row["selected_filings"]:
                raise ValueError(f"source filing count differs: {ticker}")
            new_intake = root / "intake" / "history_intake.json"
            write_once(
                new_intake,
                {
                    "version": history.HISTORY_VERSION,
                    "plan": plan,
                    "filings": adopted,
                    "complete": True,
                },
                f"{ticker} adopted intake",
            )
        attestation = ops._attest_intake(new_intake, run.plans[ticker])
        if not attestation.complete or attestation.error:
            raise ValueError(f"adopted intake is not complete: {ticker}")
        receipt = {
            "schema_version": "universe50-t3v2-raw-adoption-v1",
            "status": "RAW_COMPLETE",
            "ticker": ticker,
            "source_sha": SOURCE_SHA,
            "program_sha256": preflight["modules"]["program"]["sha256"],
            "engine_modules_sha256": preflight["modules"]["engine"]["aggregate_sha256"],
            "candidate_sha256": INPUT_HASHES["candidate"],
            "source_intake": intake_pin,
            "plan_sha256": row["plan_sha256"],
            "new_intake": str(new_intake.absolute()),
            "new_intake_sha256": digest(new_intake),
            "selected_filings": len(evidence),
            "snapshots": evidence,
        }
        write_once(root / "raw_adoption_receipt.json", receipt, f"{ticker} Raw adoption")
    public = ops.read_universe_status(manifest_path=target_manifest)
    by_ticker = {row.ticker: row for row in public.companies}
    if any(by_ticker[t].state != "RAW_COMPLETE" for t in chosen):
        raise ValueError("public status did not confirm RAW_COMPLETE")
    ops.write_status_outputs(
        manifest_path=target_manifest, output_root=target_manifest.parent / "status"
    )
    return target_manifest.parent / "status" / "collection_status.json"


def validate_bulk_gate(ticker: str, path: Path | None, sha: str | None) -> None:
    if ticker in FIRST5:
        if path is not None or sha is not None:
            raise ValueError("first5 build does not accept a bulk gate")
        return
    if path is None or sha is None:
        raise ValueError("later-45 requires explicit first5 financial acceptance hash")
    with pinned(path, sha):
        gate = read_json(path)
    if gate.get("status") != "LOCALLY_ACCEPTED_FIRST5_FINANCIAL" or gate.get("companies") != list(
        FIRST5
    ):
        raise ValueError("first5 financial acceptance is not exact and locally accepted")


def company_entry(run: Any, ticker: str) -> dict[str, Any]:
    return next(row for row in run.manifest["companies"] if row["ticker"] == ticker)


def validate_existing_build(
    config: dict[str, Any], ticker: str, preflight: dict[str, Any]
) -> Path | None:
    target_manifest = manifest(config)
    run, root = ops._attest_run(target_manifest), target_manifest.parent / "companies" / ticker
    marker_path, receipt_path = root / "build_manifest.json", root / "ops_build_receipt.json"
    destination = Path(config["history_root"]) / f"{ticker}-t3v2-{config['run_id']}"
    if not marker_path.exists() and not receipt_path.exists() and not destination.exists():
        return None
    if not marker_path.is_file() or not receipt_path.is_file():
        raise ValueError(f"partial/unreceipted output refuses reuse: {ticker}")
    intake_path = root / "intake" / "history_intake.json"
    intake, company = ops._attest_intake(intake_path, run.plans[ticker]), company_entry(run, ticker)
    marker = read_json(marker_path)
    error = ops._validate_build_attestation(
        marker,
        ticker=ticker,
        plan=run.plans[ticker],
        plan_sha256=company["plan_sha256"],
        intake_path=intake_path,
        intake=intake,
    )
    if error:
        raise ValueError(f"existing build marker failed actual validation: {error}")
    expected = {
        "schema_version": "universe50-t3v2-build-receipt-v1",
        "status": "READY",
        "ticker": ticker,
        "source_sha": SOURCE_SHA,
        "program_sha256": preflight["modules"]["program"]["sha256"],
        "engine_modules_sha256": preflight["modules"]["engine"]["aggregate_sha256"],
        "build_manifest": str(marker_path.absolute()),
        "build_manifest_sha256": digest(marker_path),
        "output_root": str(destination.absolute()),
        "history_manifest_sha256": marker["history_manifest_sha256"],
        "input_intake_sha256": intake.sha256,
    }
    if read_json(receipt_path) != expected:
        raise ValueError(f"existing build receipt differs: {ticker}")
    return marker_path


def process_tree_rss_kib(root: int) -> int:
    rows: dict[int, tuple[int, int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parent = int((entry / "stat").read_text().split()[3])
            rss = next(
                (
                    int(x.split()[1])
                    for x in (entry / "status").read_text().splitlines()
                    if x.startswith("VmRSS:")
                ),
                0,
            )
            rows[int(entry.name)] = parent, rss
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            pass
    selected, changed = {root}, True
    while changed:
        changed = False
        for pid, (parent, _) in rows.items():
            if parent in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return sum(rows.get(pid, (0, 0))[1] for pid in selected)


@contextmanager
def heavy_lock(root: Path) -> Iterator[None]:
    with (root / ".one-heavy.lock").open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another heavy operation is active") from exc
        yield


def receive_supervisor(config: dict[str, Any]) -> object:
    """Consume the one-shot inherited capability and prove the parent owns the heavy lock."""
    try:
        descriptor = int(os.environ["SEC_XBRL_T3V2_SUPERVISOR_FD"])
        parent_pid = int(os.environ["SEC_XBRL_T3V2_SUPERVISOR_PID"])
        expected = os.environ["SEC_XBRL_T3V2_SUPERVISOR_SHA256"]
    except (KeyError, ValueError) as exc:
        raise PermissionError("worker requires an inherited supervisor capability") from exc
    if os.getppid() != parent_pid:
        raise PermissionError("worker supervisor parent identity differs")
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        token = stream.read(33)
    if len(token) != 32 or hashlib.sha256(token).hexdigest() != expected:
        raise PermissionError("worker supervisor capability is invalid")
    expected_environment = {
        "POLARS_MAX_THREADS": "2",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
    if any(os.environ.get(name) != value for name, value in expected_environment.items()):
        raise PermissionError("worker resource environment differs")
    with (Path(config["collection_root"]) / ".one-heavy.lock").open(
        "a+", encoding="utf-8"
    ) as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(stream, fcntl.LOCK_UN)
            raise PermissionError("worker requires the parent-held heavy lock")
    return _SUPERVISOR_CAPABILITY


def monitor_process(
    process: Any,
    samples: Any,
    *,
    limit_kib: int = LIMIT_KIB,
    timeout_seconds: float = TIMEOUT,
    rss_reader: Any = process_tree_rss_kib,
    clock: Any = time.monotonic,
    sleeper: Any = time.sleep,
    kill_group: Any = os.killpg,
) -> tuple[int, int, str | None, float]:
    """Supervise one process tree; tests inject clocks and process controls."""
    started, peak, stopped = clock(), 0, None
    while process.poll() is None:
        elapsed, rss = clock() - started, rss_reader(process.pid)
        peak = max(peak, rss)
        samples.write(json.dumps({"elapsed_seconds": round(elapsed, 3), "rss_kib": rss}) + "\n")
        samples.flush()
        stopped = (
            "RSS_LIMIT" if rss > limit_kib else "TIMEOUT" if elapsed > timeout_seconds else None
        )
        if stopped:
            kill_group(process.pid, signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                kill_group(process.pid, signal.SIGKILL)
            break
        sleeper(0.25)
    return process.wait(), peak, stopped, clock() - started


def run_guarded_worker(
    config_path: Path,
    ticker: str,
    go_path: Path,
    gate: Path | None,
    gate_sha: str | None,
) -> None:
    config, _, _ = validate_preflight(config_path)
    evidence = Path(config["collection_root"]) / "execution" / ticker
    evidence.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log, samples, summary = (
        evidence / f"{stamp}.log",
        evidence / f"{stamp}.rss.jsonl",
        evidence / f"{stamp}.summary.json",
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_build-worker",
        "--config",
        str(config_path.absolute()),
        "--ticker",
        ticker,
        "--go-file",
        str(go_path.absolute()),
    ]
    if gate is not None and gate_sha is not None:
        command.extend(
            ["--first5-acceptance", str(gate.absolute()), "--first5-acceptance-sha256", gate_sha]
        )
    env = os.environ.copy()
    env.update(
        POLARS_MAX_THREADS="2",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    token = os.urandom(32)
    read_fd, write_fd = os.pipe()
    env.update(
        SEC_XBRL_T3V2_SUPERVISOR_FD=str(read_fd),
        SEC_XBRL_T3V2_SUPERVISOR_PID=str(os.getpid()),
        SEC_XBRL_T3V2_SUPERVISOR_SHA256=hashlib.sha256(token).hexdigest(),
    )
    with log.open("x", encoding="utf-8") as out, samples.open("x", encoding="utf-8") as rss_out:
        try:
            process = subprocess.Popen(
                command,
                stdout=out,
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
        code, peak, stopped, elapsed = monitor_process(process, rss_out)
    result = {
        "schema_version": "universe50-t3v2-resource-run-v1",
        "status": stopped or ("PASS" if code == 0 else "FAIL"),
        "returncode": code,
        "elapsed_seconds": round(elapsed, 3),
        "peak_process_tree_rss_kib": peak,
        "limit_kib": LIMIT_KIB,
        "timeout_seconds": TIMEOUT,
        "command": command,
        "log": str(log),
        "samples": str(samples),
    }
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["status"] != "PASS":
        raise RuntimeError(f"guarded build failed: {result['status']} ({summary})")


def build_worker(
    config_path: Path,
    ticker: str,
    go_path: Path,
    supervisor: object | None,
    gate: Path | None = None,
    gate_sha: str | None = None,
) -> Path:
    config, preflight = validate_go(config_path, "build-one", (ticker,), go_path)
    if supervisor is not _SUPERVISOR_CAPABILITY:
        raise PermissionError("direct worker invocation is unsupported")
    validate_bulk_gate(ticker, gate, gate_sha)
    if ticker not in candidate_rows(config):
        raise ValueError("worker ticker is outside exact-50")
    target_manifest, destination = (
        manifest(config),
        Path(config["history_root"]) / f"{ticker}-t3v2-{config['run_id']}",
    )
    run = ops._attest_run(target_manifest)
    company, root = company_entry(run, ticker), target_manifest.parent / "companies" / ticker
    intake_path, marker_path, receipt_path = (
        root / "intake" / "history_intake.json",
        root / "build_manifest.json",
        root / "ops_build_receipt.json",
    )
    intake = ops._attest_intake(intake_path, run.plans[ticker])
    if (
        not intake.complete
        or intake.error
        or destination.exists()
        or marker_path.exists()
        or receipt_path.exists()
    ):
        raise ValueError("worker requires complete intake and fresh output/marker/receipt")
    publication = history.build_history(intake_manifest=intake_path, output_root=destination)
    marker = ops._create_build_attestation(
        ticker=ticker,
        plan=run.plans[ticker],
        plan_sha256=company["plan_sha256"],
        intake_path=intake_path,
        intake_sha256=intake.sha256 or "",
        destination=destination,
        publication=publication,
        views=("AS_FILED", "LATEST_REPORTED"),
    )
    error = ops._validate_build_attestation(
        marker,
        ticker=ticker,
        plan=run.plans[ticker],
        plan_sha256=company["plan_sha256"],
        intake_path=intake_path,
        intake=intake,
    )
    if error:
        raise ValueError(f"new build attestation invalid: {error}")
    write_once(marker_path, marker, f"{ticker} build")
    receipt = {
        "schema_version": "universe50-t3v2-build-receipt-v1",
        "status": "READY",
        "ticker": ticker,
        "source_sha": SOURCE_SHA,
        "program_sha256": preflight["modules"]["program"]["sha256"],
        "engine_modules_sha256": preflight["modules"]["engine"]["aggregate_sha256"],
        "build_manifest": str(marker_path.absolute()),
        "build_manifest_sha256": digest(marker_path),
        "output_root": str(destination.absolute()),
        "history_manifest_sha256": marker["history_manifest_sha256"],
        "input_intake_sha256": intake.sha256,
    }
    write_once(receipt_path, receipt, f"{ticker} build receipt")
    ops.write_status_outputs(
        manifest_path=target_manifest, output_root=target_manifest.parent / "status"
    )
    return marker_path


def build_one(
    config_path: Path,
    ticker: str,
    go_path: Path,
    gate: Path | None = None,
    gate_sha: str | None = None,
) -> Path:
    ticker = ticker.upper()
    config, preflight = validate_go(config_path, "build-one", (ticker,), go_path)
    validate_bulk_gate(ticker, gate, gate_sha)
    if ticker not in candidate_rows(config):
        raise ValueError("ticker outside exact-50")
    existing = validate_existing_build(config, ticker, preflight)
    if existing:
        return existing
    row = next(
        row
        for row in ops.read_universe_status(manifest_path=manifest(config)).companies
        if row.ticker == ticker
    )
    if (
        row.state != "RAW_COMPLETE"
        or row.selected_filings != row.held_filings
        or row.pending_filings
        or row.failed_filings
    ):
        raise ValueError("build requires RAW_COMPLETE selected=held, pending=failed=0")
    with heavy_lock(Path(config["collection_root"])):
        run_guarded_worker(config_path, ticker, go_path, gate, gate_sha)
    marker = validate_existing_build(config, ticker, preflight)
    if (
        marker is None
        or next(
            r
            for r in ops.read_universe_status(manifest_path=manifest(config)).companies
            if r.ticker == ticker
        ).state
        != "READY"
    ):
        raise ValueError("public status did not attest READY")
    return marker


def scoped_status(config_path: Path, scope: Sequence[str]) -> dict[str, Any]:
    config, _, _ = validate_preflight(config_path)
    value = ops.read_universe_status(manifest_path=manifest(config))
    tickers = tuple(t.upper() for t in scope) or tuple(row.ticker for row in value.companies)
    rows = [row for row in value.companies if row.ticker in tickers]
    if len(rows) != len(tickers):
        raise ValueError("status scope differs from collection")
    return {
        "schema_version": "universe50-t3v2-scope-status-v1",
        "parent_collection_companies": 50,
        "collection_scope_companies": list(tickers),
        "ready_companies": sum(r.state == "READY" for r in rows),
        "raw_complete_companies": sum(r.state in {"RAW_COMPLETE", "READY"} for r in rows),
        "pending_companies": sum(r.state not in {"RAW_COMPLETE", "READY"} for r in rows),
        "selected_filings": sum(r.selected_filings for r in rows),
        "held_filings": sum(r.held_filings for r in rows),
        "pending_filings": sum(r.pending_filings for r in rows),
        "failed_filings": sum(r.failed_filings for r in rows),
        "companies": [ops.asdict(r) for r in rows],
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    for name in ("config-preflight", "prepare-new-collection"):
        item = commands.add_parser(name)
        item.add_argument("--config", type=Path, required=True)
    adopt = commands.add_parser("adopt-accepted-raw")
    adopt.add_argument("--config", type=Path, required=True)
    adopt.add_argument("--ticker", action="append", required=True)
    adopt.add_argument("--go-file", type=Path, required=True)
    build = commands.add_parser("build-one")
    build.add_argument("--config", type=Path, required=True)
    build.add_argument("--ticker", required=True)
    build.add_argument("--go-file", type=Path, required=True)
    build.add_argument("--first5-acceptance", type=Path)
    build.add_argument("--first5-acceptance-sha256")
    show = commands.add_parser("status")
    show.add_argument("--config", type=Path, required=True)
    show.add_argument("--scope-ticker", action="append", default=[])
    worker = commands.add_parser("_build-worker")
    worker.add_argument("--config", type=Path, required=True)
    worker.add_argument("--ticker", required=True)
    worker.add_argument("--go-file", type=Path, required=True)
    worker.add_argument("--first5-acceptance", type=Path)
    worker.add_argument("--first5-acceptance-sha256")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result: Any
    if args.command == "config-preflight":
        result = config_preflight(args.config)
    elif args.command == "prepare-new-collection":
        result = prepare_new_collection(args.config)
    elif args.command == "adopt-accepted-raw":
        result = adopt_accepted_raw(args.config, args.ticker, args.go_file)
    elif args.command == "build-one":
        result = build_one(
            args.config,
            args.ticker,
            args.go_file,
            args.first5_acceptance,
            args.first5_acceptance_sha256,
        )
    elif args.command == "status":
        result = scoped_status(args.config, args.scope_ticker)
    else:
        config, _ = load_config(args.config)
        supervisor = receive_supervisor(config)
        result = build_worker(
            args.config,
            args.ticker.upper(),
            args.go_file,
            supervisor,
            args.first5_acceptance,
            args.first5_acceptance_sha256,
        )
    print(
        json.dumps(result, indent=2, sort_keys=True, default=str)
        if isinstance(result, dict)
        else result
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
