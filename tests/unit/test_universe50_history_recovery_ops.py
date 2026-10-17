from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import universe50_history_recovery_ops as runner


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _companies() -> list[dict[str, str]]:
    tickers = [*runner.FIRST5, "KDP", *(f"X{index:02d}" for index in range(6, 50))]
    return [
        {"ticker": ticker, "cik": f"{index:010d}"}
        for index, ticker in enumerate(tickers, start=1)
    ]


def _config(tmp_path: Path, *, ticker: str = "JNJ") -> dict:
    companies = _companies()
    identity = next(row for row in companies if row["ticker"] == ticker)
    collection_root = tmp_path / "collection"
    return {
        "schema_version": runner.CONFIG_VERSION,
        "financial_as_of": runner.FINANCIAL_AS_OF,
        "first5": list(runner.FIRST5),
        "runner": {
            "checkout": str(tmp_path / "runner"),
            "head": "a" * 40,
            "module_sha256s": {name: "1" * 64 for name in runner.RUNNER_MODULES},
        },
        "engine": {
            "checkout": str(tmp_path / "engine"),
            "head": "b" * 40,
            "source_acceptance": {
                "path": str(tmp_path / "engine-acceptance.json"),
                "sha256": "2" * 64,
            },
        },
        "collection": {
            "manifest": str(collection_root / "collection_manifest.json"),
            "manifest_sha256": "3" * 64,
            "candidate": str(tmp_path / "candidate.json"),
            "candidate_sha256": "4" * 64,
            "universe_id": "exact50-t3v2-20261017-e",
            "parent_company_count": 50,
            "selected_filings": 1097,
            "companies": companies,
        },
        "target": {
            **identity,
            "plan_sha256": "5" * 64,
            "intake_sha256": "6" * 64,
            "selected_filings": 22,
            "run_version": "bounded-memory-v1",
            "history_parent": str(tmp_path / "history"),
            "history_basename": f"{ticker}-history-recovery-bounded-memory-v1",
            "approved_prior_failed_attempts": [],
            "abandoned_output_roots": [],
        },
        "execution_root": str(tmp_path / "execution"),
        "resource_root": str(collection_root),
        "limits": {
            "process_tree_rss_kib": runner.LIMIT_KIB,
            "polars_max_threads": runner.POLARS_THREADS,
            "one_heavy_process": True,
            "timeout_seconds": runner.TIMEOUT_SECONDS,
        },
        "first5_financial_acceptance": None,
    }


def test_config_requires_exact_new_target_and_canonical_later45_gate(
    tmp_path: Path,
) -> None:
    first5 = _config(tmp_path)
    assert runner._validate_shape(first5)["target"]["ticker"] == "JNJ"

    duplicate = json.loads(json.dumps(first5))
    duplicate["target"]["history_basename"] = "JNJ-old-output"
    with pytest.raises(ValueError, match="run version and basename"):
        runner._validate_shape(duplicate)

    extra = json.loads(json.dumps(first5))
    extra["implicit_retry"] = True
    with pytest.raises(ValueError, match="config shape"):
        runner._validate_shape(extra)

    later = _config(tmp_path, ticker="X06")
    with pytest.raises(ValueError, match="later-45"):
        runner._validate_shape(later)
    later["first5_financial_acceptance"] = {
        "path": str(tmp_path / "first5-acceptance.json"),
        "sha256": "7" * 64,
    }
    assert runner._validate_shape(later)["target"]["ticker"] == "X06"


def _materialize_collection_target(
    config: dict, monkeypatch: pytest.MonkeyPatch, *, prior_failure: bool = False
) -> tuple[dict, SimpleNamespace]:
    collection = config["collection"]
    manifest = _write(Path(collection["manifest"]), {"fixture": True})
    collection["manifest_sha256"] = runner._sha256(manifest)
    counts = [22] * 49 + [19]
    candidate_rows = []
    status_rows = []
    for identity, count in zip(collection["companies"], counts, strict=True):
        is_target = identity["ticker"] == config["target"]["ticker"]
        candidate_rows.append(
            {
                **identity,
                "selected_filings": count,
                "plan_sha256": config["target"]["plan_sha256"] if is_target else "a" * 64,
                "intake_sha256": config["target"]["intake_sha256"] if is_target else "b" * 64,
            }
        )
        status_rows.append(
            SimpleNamespace(
                **identity,
                state=("BUILD_FAILED" if prior_failure else "RAW_COMPLETE")
                if is_target
                else "PREPARED",
                selected_filings=count,
                held_filings=count if is_target else 0,
                pending_filings=0 if is_target else count,
                failed_filings=0,
            )
        )
        if is_target:
            config["target"]["selected_filings"] = count
    candidate = _write(Path(collection["candidate"]), {"selection": candidate_rows})
    collection["candidate_sha256"] = runner._sha256(candidate)
    paths = runner._target_paths(config)
    plan = _write(paths["plan"], {"as_of_date": runner.FINANCIAL_AS_OF})
    intake = _write(
        paths["intake"], {"complete": True, "plan": json.loads(plan.read_text())}
    )
    config["target"]["plan_sha256"] = runner._sha256(plan)
    config["target"]["intake_sha256"] = runner._sha256(intake)
    candidate_payload = json.loads(candidate.read_text())
    target_row = next(
        row
        for row in candidate_payload["selection"]
        if row["ticker"] == config["target"]["ticker"]
    )
    target_row["plan_sha256"] = config["target"]["plan_sha256"]
    target_row["intake_sha256"] = config["target"]["intake_sha256"]
    _write(candidate, candidate_payload)
    collection["candidate_sha256"] = runner._sha256(candidate)
    Path(config["target"]["history_parent"]).mkdir()
    Path(config["resource_root"]).mkdir(exist_ok=True)
    if prior_failure:
        attempt = _write(
            paths["company_root"] / "operation_attempts/build-failed.json",
            {"result": {"status": "BUILD_FAILED"}},
        )
        abandoned = Path(config["target"]["history_parent"]) / "old-partial"
        abandoned.mkdir()
        config["target"]["approved_prior_failed_attempts"] = [
            {"path": str(attempt), "sha256": runner._sha256(attempt)}
        ]
        config["target"]["abandoned_output_roots"] = [str(abandoned)]
    status = SimpleNamespace(
        universe_id=collection["universe_id"],
        as_of_date=runner.FINANCIAL_AS_OF,
        requested_companies=50,
        selected_filings=1097,
        companies=tuple(status_rows),
    )
    target = config["target"]
    run = SimpleNamespace(
        manifest={
            "companies": [
                {"ticker": target["ticker"], "plan_sha256": target["plan_sha256"]}
            ]
        },
        plans={target["ticker"]: json.loads(plan.read_text())},
    )
    monkeypatch.setattr(
        runner.ops, "read_universe_status", lambda **_: status, raising=False
    )
    monkeypatch.setattr(runner.ops, "_attest_run", lambda _: run, raising=False)
    monkeypatch.setattr(
        runner.ops,
        "_attest_intake",
        lambda *_: SimpleNamespace(
            sha256=target["intake_sha256"], complete=True, error=None
        ),
        raising=False,
    )
    return config, status


def test_target_reopens_exact_collection_and_allows_only_pinned_jnj_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(
        _config(tmp_path), monkeypatch, prior_failure=True
    )
    binding = runner._validate_collection_target(runner._validate_shape(config))
    assert binding["target"]["state"] == "BUILD_FAILED"
    assert binding["target"]["destination"].endswith(
        "JNJ-history-recovery-bounded-memory-v1"
    )

    extra = _write(
        Path(config["collection"]["manifest"]).parent
        / "companies/JNJ/operation_attempts/build-unpinned.json",
        {"result": {"status": "BUILD_FAILED"}},
    )
    assert extra.is_file()
    with pytest.raises(ValueError, match="unapproved prior build attempt"):
        runner._validate_collection_target(runner._validate_shape(config))


def test_target_rejects_candidate_company_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    candidate = Path(config["collection"]["candidate"])
    payload = json.loads(candidate.read_text())
    payload["selection"][0]["cik"] = "9999999999"
    _write(candidate, payload)
    config["collection"]["candidate_sha256"] = runner._sha256(candidate)
    with pytest.raises(ValueError, match="candidate membership"):
        runner._validate_collection_target(runner._validate_shape(config))


def test_target_rejects_existing_marker_receipt_or_selected_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    paths = runner._target_paths(config)
    paths["marker"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already has"):
        runner._validate_collection_target(runner._validate_shape(config))


def _receipt(root: Path, stage: str) -> tuple[Path, dict]:
    files = [
        {
            "path": str(path.resolve()),
            "relative_path": str(path.relative_to(root)),
            "sha256": runner._sha256(path),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    value = {
        "schema_version": "universe50-financial-stage-receipt-v1",
        "status": "PASS",
        "stage": stage,
        "source_head": runner.FINANCIAL_SOURCE_SHA,
        "go_sha256": "c" * 64,
        "outputs": [{"root": str(root.resolve()), "files": files}],
    }
    path = _write(root.parent / "receipts" / f"{stage}.json", value)
    return path, value


def _materialize_financial_acceptance(config: dict, tmp_path: Path) -> Path:
    cohort = [
        row
        for ticker in runner.FIRST5
        for row in config["collection"]["companies"]
        if row["ticker"] == ticker
    ]
    expected_collection = {
        "manifest": config["collection"]["manifest"],
        "manifest_sha256": config["collection"]["manifest_sha256"],
        "parent_company_count": 50,
    }
    roots = {stage: tmp_path / "accepted" / stage for stage in runner.FINANCIAL_STAGES}
    manifest_rows = []
    metadata = _write(tmp_path / "accepted/metadata/company_metadata_manifest.json", {})
    manifest_rows.append(
        {
            "name": "metadata",
            "root": str(metadata.parent),
            "manifest": str(metadata),
            "manifest_sha256": runner._sha256(metadata),
        }
    )
    simple = {
        "quality": "generic_metric_quality_manifest.json",
        "identity": "generic_metric_identity_manifest.json",
        "annual-metrics": "screening_metric_manifest.json",
        "annual-dataset-v2": "screening_dataset_manifest.json",
        "quarterly-metrics": "quarterly_screening_metric_manifest.json",
        "combined-dataset-v3": "screening_dataset_v3_manifest.json",
    }
    names = {
        "quality": "quality",
        "identity": "identity",
        "annual-metrics": "annual_metrics",
        "annual-dataset-v2": "annual_dataset_v2",
        "quarterly-metrics": "quarterly_metrics",
        "combined-dataset-v3": "combined_dataset_v3",
    }
    for stage, filename in simple.items():
        manifest = _write(roots[stage] / filename, {"stage": stage})
        manifest_rows.append(
            {
                "name": names[stage],
                "root": str(manifest.parent),
                "manifest": str(manifest),
                "manifest_sha256": runner._sha256(manifest),
            }
        )
    analysis_manifests: dict[tuple[str, str], Path] = {}
    for ticker in runner.FIRST5:
        for stage, prefix in (
            ("annual-analysis", "annual_analysis"),
            ("quarterly-analysis", "quarterly_analysis"),
        ):
            manifest = _write(
                roots[stage] / ticker / "analysis_manifest.json",
                {"stage": stage, "ticker": ticker},
            )
            analysis_manifests[(ticker, prefix)] = manifest
    for ticker in runner.FIRST5:
        for prefix in ("annual_analysis", "quarterly_analysis"):
            manifest = analysis_manifests[(ticker, prefix)]
            manifest_rows.append(
                {
                    "name": f"{prefix}:{ticker}",
                    "root": str(manifest.parent),
                    "manifest": str(manifest),
                    "manifest_sha256": runner._sha256(manifest),
                }
            )
    receipts = {}
    for stage in sorted(runner.FINANCIAL_STAGES):
        path, _ = _receipt(roots[stage], stage)
        receipts[stage] = {"path": str(path), "sha256": runner._sha256(path)}
    first5_config = _write(
        tmp_path / "accepted/first5-config.json",
        {
            "schema_version": "universe50-financial-ops-config-v1",
            "collection_scope_mode": "EXPLICIT_SUBSET",
            "financial_as_of": runner.FINANCIAL_AS_OF,
            "metadata_observation_cutoff": runner.METADATA_CUTOFF,
            "collection": expected_collection,
            "source": {"head": runner.FINANCIAL_SOURCE_SHA},
            "companies": list(reversed(cohort)),
        },
    )
    acceptance = _write(
        tmp_path / "accepted/first5-acceptance.json",
        {
            "schema_version": runner.FINANCIAL_ACCEPTANCE_VERSION,
            "status": runner.FINANCIAL_ACCEPTANCE_STATUS,
            "source_head": runner.FINANCIAL_SOURCE_SHA,
            "financial_as_of": runner.FINANCIAL_AS_OF,
            "metadata_observation_cutoff": runner.METADATA_CUTOFF,
            "collection": expected_collection,
            "companies": cohort,
            "first5_config": {
                "path": str(first5_config),
                "sha256": runner._sha256(first5_config),
            },
            "stage_receipts": receipts,
            "publication_manifests": manifest_rows,
        },
    )
    config["first5_financial_acceptance"] = {
        "path": str(acceptance),
        "sha256": runner._sha256(acceptance),
    }
    return acceptance


def test_later45_gate_requires_canonical_object_cohort_receipts_and_publications(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, ticker="X06")
    manifest = _write(Path(config["collection"]["manifest"]), {})
    config["collection"]["manifest_sha256"] = runner._sha256(manifest)
    acceptance = _materialize_financial_acceptance(config, tmp_path)
    binding = runner._verify_financial_acceptance(runner._validate_shape(config))
    assert binding is not None
    assert binding["source_head"] == runner.FINANCIAL_SOURCE_SHA
    assert len(binding["publication_manifests"]) == 17

    payload = json.loads(acceptance.read_text())
    payload["companies"] = list(runner.FIRST5)
    _write(acceptance, payload)
    config["first5_financial_acceptance"]["sha256"] = runner._sha256(acceptance)
    with pytest.raises(ValueError, match="scope differs"):
        runner._verify_financial_acceptance(runner._validate_shape(config))


def test_preflight_request_and_go_reopen_exact_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    Path(config["resource_root"]).mkdir()
    Path(config["target"]["history_parent"]).mkdir()
    config_path = _write(tmp_path / "config.json", config)
    snapshot = {
        "runner": {"head": config["runner"]["head"]},
        "engine": {"head": config["engine"]["head"]},
        "collection": {"target": {"ticker": "JNJ", "cik": "0000000003"}},
        "first5_financial_acceptance": None,
    }
    monkeypatch.setattr(runner, "_snapshot", lambda _: snapshot)
    preflight = runner.preflight(config_path)
    request = runner.request_stage(config_path)
    _, expected_go = runner._expected_go(config_path)
    go = _write(tmp_path / "root-go.json", expected_go)
    assert runner._validate_go(config_path, go)["target"]["ticker"] == "JNJ"

    changed = json.loads(request.read_text())
    changed["target"]["cik"] = "9999999999"
    _write(request, changed)
    with pytest.raises(ValueError, match="request changed"):
        runner._validate_go(config_path, go)
    assert preflight.is_file()


def test_execute_recovery_uses_public_history_and_writes_typed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    config = runner._validate_shape(config)
    binding = runner._validate_collection_target(config)
    paths = runner._target_paths(config)
    go = _write(tmp_path / "root-go.json", {"authorized_by": "ROOT_LEAD"})
    calls: list[tuple[Path, Path]] = []

    def build_history(*, intake_manifest: Path, output_root: Path) -> Path:
        calls.append((intake_manifest, output_root))
        publication = output_root / "panels"
        _write(publication / "history_manifest.json", {"state": "READY"})
        return publication

    class Reader:
        def __init__(self, publication: Path) -> None:
            self.publication = publication

        def verify_all(self) -> None:
            assert (self.publication / "history_manifest.json").is_file()

    marker = {
        "publication": str(paths["destination"] / "panels"),
        "history_manifest_sha256": "d" * 64,
        "declared_files": [{"relative_path": "history_manifest.json"}],
    }
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda _: {
            "runner": {"head": config["runner"]["head"], "files": {}},
            "engine": {"head": config["engine"]["head"], "files": {}},
            "collection": binding,
            "first5_financial_acceptance": None,
        },
    )
    monkeypatch.setattr(runner.history, "build_history", build_history, raising=False)
    monkeypatch.setattr(
        runner.history, "HistoryPublicationReader", Reader, raising=False
    )
    monkeypatch.setattr(
        runner.ops, "_create_build_attestation", lambda **_: marker, raising=False
    )
    monkeypatch.setattr(
        runner.ops,
        "_validate_build_attestation",
        lambda *_, **__: None,
        raising=False,
    )
    monkeypatch.setattr(
        runner.ops,
        "_write_once_json",
        lambda path, value, **_: _write(path, value),
        raising=False,
    )
    monkeypatch.setattr(
        runner.ops,
        "read_universe_status",
        lambda **_: SimpleNamespace(
            companies=(SimpleNamespace(ticker="JNJ", state="READY"),)
        ),
        raising=False,
    )
    receipt_path = runner._execute_recovery(config, go)
    receipt = json.loads(receipt_path.read_text())
    assert calls == [(paths["intake"], paths["destination"])]
    assert receipt["schema_version"] == runner.RECEIPT_VERSION
    assert receipt["runner_source"]["head"] == config["runner"]["head"]
    assert receipt["engine_source"]["head"] == config["engine"]["head"]
    assert receipt["publication"].endswith("/panels")
    assert not paths["old_receipt"].exists()


def test_clean_runner_and_engine_imports_are_separate_from_financial_modules(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[2]
    runner_checkout = tmp_path / "runner"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(repository), str(runner_checkout)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(runner_checkout), "checkout", runner.RUNNER_BASE_SHA],
        check=True,
        capture_output=True,
    )
    shutil.copy2(Path(runner.__file__), runner_checkout / runner.RUNNER_MODULES["runner"])
    subprocess.run(
        ["git", "-C", str(runner_checkout), "add", runner.RUNNER_MODULES["runner"]],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(runner_checkout),
            "-c",
            "user.name=Recovery Test",
            "-c",
            "user.email=recovery-test@example.invalid",
            "commit",
            "-m",
            "test recovery runner",
        ],
        check=True,
        capture_output=True,
    )
    runner_head = subprocess.run(
        ["git", "-C", str(runner_checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    engine = tmp_path / "engine"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(repository), str(engine)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(engine), "checkout", "--detach", runner.ENGINE_BASE_SHA],
        check=True,
        capture_output=True,
    )
    report = _write(tmp_path / "independent-report.json", {"verdict": "PASS"})
    hashes = {
        name: runner._sha256(engine / relative)
        for name, relative in runner.ENGINE_MODULES.items()
    }
    acceptance = _write(
        tmp_path / "engine-acceptance.json",
        {
            "schema_version": runner.ENGINE_ACCEPTANCE_VERSION,
            "status": runner.ENGINE_ACCEPTANCE_STATUS,
            "engine_source_head": runner.ENGINE_BASE_SHA,
            "engine_base_sha": runner.ENGINE_BASE_SHA,
            "graph_rule_version": runner.GRAPH_RULE_VERSION,
            "module_sha256s": hashes,
            "independent_report": {
                "path": str(report),
                "sha256": runner._sha256(report),
            },
        },
    )
    declaration = _write(
        tmp_path / "declaration.json",
        {
            "runner": {
                "checkout": str(runner_checkout),
                "head": runner_head,
                "module_sha256s": {
                    name: runner._sha256(runner_checkout / relative)
                    for name, relative in runner.RUNNER_MODULES.items()
                },
            },
            "engine": {
                "checkout": str(engine),
                "head": runner.ENGINE_BASE_SHA,
                "source_acceptance": {
                    "path": str(acceptance),
                    "sha256": runner._sha256(acceptance),
                },
            }
        },
    )
    script = (
        "import json,sys; from pathlib import Path; "
        "from tools import universe50_history_recovery_ops as r; "
        "d=json.loads(Path(sys.argv[1]).read_text()); "
        "u=r._verify_runner_source(d); v=r._verify_engine_source(d); "
        "assert Path(r.__file__).is_relative_to(Path(d['runner']['checkout'])); "
        "assert Path(r.ops.__file__).is_relative_to(Path(d['engine']['checkout'])); "
        "assert 'sec_xbrl.metric_quality' not in sys.modules; "
        "print(u['head'], v['head'])"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(engine / "src"), str(runner_checkout))
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(declaration)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=runner_checkout,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{runner_head} {runner.ENGINE_BASE_SHA}"


def test_source_has_no_financial_runner_import_or_network_path() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "universe50_financial_ops" not in source
    assert "SECArchiveClient" not in source
    assert "collect_universe(" not in source


def test_direct_worker_rejects_before_recovery_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def handler(config: dict, go: Path) -> Path:
        nonlocal called
        called = True
        return tmp_path / "receipt"

    monkeypatch.setattr(runner, "RECOVERY_HANDLER", handler)
    monkeypatch.delenv("SEC_XBRL_T3V2_SUPERVISOR_PID", raising=False)
    with pytest.raises(PermissionError, match="supervisor"):
        runner._worker(tmp_path / "config", tmp_path / "go")
    assert called is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux operations contract")
def test_real_guarded_tiny_child_reaches_recovery_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {"resource_root": str(tmp_path)}
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(runner, "_validate_go", lambda *_: config)
    monkeypatch.setattr(runner, "_snapshot", lambda _: {})
    monkeypatch.setattr(
        runner,
        "RECOVERY_HANDLER",
        lambda *_: _write(receipt, {"status": "REACHED"}),
    )
    token = os.urandom(32)
    token_read, token_write = os.pipe()
    result_read, result_write = os.pipe()
    with runner.resource_ops.heavy_lock(tmp_path):
        pid = os.fork()
        if pid == 0:
            try:
                os.close(token_write)
                os.close(result_read)
                os.environ.update(
                    POLARS_MAX_THREADS="2",
                    OMP_NUM_THREADS="1",
                    OPENBLAS_NUM_THREADS="1",
                    MKL_NUM_THREADS="1",
                    NUMEXPR_NUM_THREADS="1",
                    SEC_XBRL_T3V2_SUPERVISOR_FD=str(token_read),
                    SEC_XBRL_T3V2_SUPERVISOR_PID=str(os.getppid()),
                    SEC_XBRL_T3V2_SUPERVISOR_SHA256=runner.hashlib.sha256(
                        token
                    ).hexdigest(),
                )
                result = runner._worker(tmp_path / "config", tmp_path / "go")
                os.write(result_write, str(result).encode())
                os._exit(0)
            except Exception:  # noqa: BLE001 - child reports only its exit status
                os._exit(70)
        os.close(token_read)
        os.close(result_write)
        os.write(token_write, token)
        os.close(token_write)
        result = os.read(result_read, 4096)
        os.close(result_read)
        _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert Path(result.decode()) == receipt
    assert json.loads(receipt.read_text()) == {"status": "REACHED"}


@pytest.mark.parametrize("stopped", ("RSS_LIMIT", "TIMEOUT"))
def test_guarded_stage_records_resource_stop_and_never_returns_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stopped: str,
) -> None:
    config = _config(tmp_path)
    Path(config["resource_root"]).mkdir()
    paths = runner._target_paths(config)
    monkeypatch.setattr(runner, "_validate_go", lambda *_: config)
    monkeypatch.setattr(runner, "_worker_environment", lambda *_: os.environ.copy())
    monkeypatch.setattr(runner.os, "write", lambda *_: 32)

    class Process:
        pid = 123

        def poll(self):
            return 1

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        runner.resource_ops,
        "supervise_owned_process",
        lambda *args, **kwargs: (-9, runner.LIMIT_KIB + 1, stopped, 1.0),
    )
    with pytest.raises(RuntimeError, match=stopped):
        runner.run_stage(tmp_path / "config", tmp_path / "go")
    summary = json.loads(runner._summary_path(config).read_text())
    assert summary["status"] == stopped
    assert not paths["receipt"].exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux operations contract")
def test_interrupted_supervisor_terminates_and_reaps_owned_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    Path(config["resource_root"]).mkdir()
    paths = runner._target_paths(config)
    monkeypatch.setattr(runner, "_validate_go", lambda *_: config)
    monkeypatch.setattr(runner, "_worker_environment", lambda *_: os.environ.copy())
    original_popen = subprocess.Popen
    child: subprocess.Popen | None = None

    def sleeping_child(*args, **kwargs):
        nonlocal child
        child = original_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=True,
            env=kwargs["env"],
            pass_fds=kwargs["pass_fds"],
        )
        return child

    monkeypatch.setattr(runner.subprocess, "Popen", sleeping_child)
    monkeypatch.setattr(
        runner.resource_ops,
        "supervise_owned_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run_stage(tmp_path / "config", tmp_path / "go")
    assert child is not None and child.poll() is not None
    summary = json.loads(runner._summary_path(config).read_text())
    assert summary["status"] == "SUPERVISOR_INTERRUPTED"
    assert summary["child_reaped"] is True
    assert not paths["receipt"].exists()
