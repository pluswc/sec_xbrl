from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import universe50_financial_ops as runner


def _config(tmp_path: Path) -> dict:
    companies = [
        {
            "ticker": ticker,
            "cik": f"{index:010d}",
            "input_years": [2021, 2022, 2023, 2024, 2025],
            "display_years": [2022, 2023, 2024, 2025],
            "history_root": str(tmp_path / f"history/{ticker}"),
            "history_manifest_sha256": "1" * 64,
            "collector_source_commit_sha": "a" * 40,
            "plan_sha256": "2" * 64,
            "intake_sha256": "3" * 64,
        }
        for index, ticker in enumerate(runner.FIRST5, start=1)
    ]
    output_names = {key for keys in runner.OUTPUT_KEYS.values() for key in keys}
    return {
        "schema_version": runner.CONFIG_VERSION,
        "universe_id": "exact50-t3v2-fixture",
        "dataset_id": "exact50-first5-fixture",
        "financial_as_of": runner.FINANCIAL_AS_OF,
        "metadata_observation_cutoff": runner.METADATA_CUTOFF,
        "collection_scope_mode": "EXPLICIT_SUBSET",
        "first5": list(runner.FIRST5),
        "companies": companies,
        "collection": {
            "manifest": str(tmp_path / "collection_manifest.json"),
            "manifest_sha256": "4" * 64,
            "parent_company_count": 50,
        },
        "package_view": {
            "root": str(tmp_path / "packages"),
            "manifest_sha256": "5" * 64,
        },
        "metadata": {
            "mode": "EXISTING_PUBLICATION",
            "root": str(tmp_path / "metadata"),
            "manifest_sha256": "6" * 64,
        },
        "source": {
            "checkout": str(tmp_path / "checkout"),
            "head": "b" * 40,
            "module_sha256s": {name: "7" * 64 for name in runner.PINNED_MODULES},
        },
        "outputs": {
            name: str(tmp_path / "outputs" / name) for name in output_names
        },
        "execution_root": str(tmp_path / "execution"),
        "resource_root": str(tmp_path / "resource"),
        "limits": {
            "process_tree_rss_kib": runner.LIMIT_KIB,
            "polars_max_threads": runner.POLARS_THREADS,
            "one_heavy_process": True,
            "timeout_seconds": runner.TIMEOUT_SECONDS,
        },
    }


def test_config_requires_explicit_first5_cutoffs_and_all_module_pins(
    tmp_path: Path,
) -> None:
    value = _config(tmp_path)
    normalized = runner._validate_shape(value)
    assert [row["ticker"] for row in normalized["companies"]] == list(runner.FIRST5)

    for mutate, match in (
        (lambda row: row.update(financial_as_of="2026-10-09"), "financial cutoff"),
        (
            lambda row: row.update(metadata_observation_cutoff="2026-10-13T00:00:00Z"),
            "metadata observation cutoff",
        ),
        (lambda row: row["source"]["module_sha256s"].pop("runner"), "module pins"),
        (lambda row: row.update(first5=list(reversed(runner.FIRST5))), "first-five"),
    ):
        changed = json.loads(json.dumps(value))
        mutate(changed)
        with pytest.raises(ValueError, match=match):
            runner._validate_shape(changed)


def test_fresh_metadata_requires_exact50_and_pinned_kdp_acquisition(
    tmp_path: Path,
) -> None:
    value = _config(tmp_path)
    value["metadata"] = {
        "mode": "PUBLISH_EXACT50",
        "snapshots": [
            {
                "ticker": "KDP" if index == 50 else f"T{index}",
                "cik": f"{index:010d}",
                "path": str(tmp_path / f"metadata/{index}.json"),
                "sha256": "8" * 64,
                "observed_at": "2026-10-13T12:00:00Z",
            }
            for index in range(1, 51)
        ],
        "kdp_acquisition_evidence": {
            "path": str(tmp_path / "kdp-operation.json"),
            "sha256": "9" * 64,
            "completed_at": runner.KDP_ACQUISITION_COMPLETED_AT,
        },
    }
    runner._validate_shape(value)
    value["metadata"]["snapshots"][0]["observed_at"] = "2026-10-14T00:00:00Z"
    with pytest.raises(ValueError, match="after its explicit cutoff"):
        runner._validate_shape(value)


def test_fresh_metadata_must_match_exact50_collection_identity() -> None:
    collection = [
        SimpleNamespace(ticker=f"T{index}", cik=f"{index:010d}")
        for index in range(1, 51)
    ]
    metadata = [
        SimpleNamespace(tickers=(f"T{index}",), cik=f"{index:010d}")
        for index in range(1, 51)
    ]
    runner._verify_exact50_metadata_membership(metadata, collection)

    metadata[-1] = SimpleNamespace(tickers=("OTHER",), cik="0000000050")
    with pytest.raises(ValueError, match="differs from exact-50 collection"):
        runner._verify_exact50_metadata_membership(metadata, collection)


def test_kdp_acquisition_evidence_binds_prepare_completion_and_root_path(
    tmp_path: Path,
) -> None:
    root = str((tmp_path / "KDP.json").resolve())
    evidence = {
        "source": {"submissions_root": root},
        "operation_attempts": [
            {
                "operation": "prepare",
                "completed_at": runner.KDP_ACQUISITION_COMPLETED_AT,
            }
        ],
    }
    assert runner._has_prepare_completion(evidence)
    assert runner._contains_string(evidence, root)
    assert not runner._contains_string(evidence, str(tmp_path / "OTHER.json"))


def test_stage_go_exactly_binds_request_scope_parents_and_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = runner._validate_shape(_config(tmp_path))
    execution = Path(config["execution_root"])
    execution.mkdir()
    preflight = execution / "preflight.json"
    preflight.write_text("{}\n", encoding="utf-8")
    config_sha = "a" * 64
    monkeypatch.setattr(
        runner,
        "_validated_preflight",
        lambda _: (config, config_sha, preflight),
    )
    request = {
        "schema_version": runner.REQUEST_VERSION,
        "status": "AWAITING_EXPLICIT_GO",
        "stage": "annual-analysis",
        "source_head": config["source"]["head"],
        "config_sha256": config_sha,
        "preflight_sha256": runner.sha256_file(preflight),
        "scope_companies": [
            {"ticker": row["ticker"], "cik": row["cik"]}
            for row in config["companies"]
        ],
        "parent_receipts": [],
        "outputs": [str(Path(config["outputs"]["annual_analysis"]).absolute())],
    }
    request_path = runner._request_path(config, "annual-analysis")
    runner._write_new(request_path, request, "request")
    go = runner._expected_go(config, config_sha, "annual-analysis")
    go_path = tmp_path / "go.json"
    go_path.write_text(json.dumps(go), encoding="utf-8")
    assert runner._validate_go(tmp_path / "config.json", "annual-analysis", go_path) == config
    go["outputs"] = [str(tmp_path / "different")]
    go_path.write_text(json.dumps(go), encoding="utf-8")
    with pytest.raises(ValueError, match="does not exactly bind"):
        runner._validate_go(tmp_path / "config.json", "annual-analysis", go_path)


def test_direct_worker_is_rejected_before_producer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def producer(_: dict) -> None:
        nonlocal called
        called = True

    config = _config(tmp_path)
    monkeypatch.setattr(runner, "_validate_go", lambda *args: config)
    monkeypatch.setattr(runner.resource_ops, "install_parent_death_guard", lambda: None)
    monkeypatch.setitem(runner.STAGE_HANDLERS, "annual-analysis", producer)
    with pytest.raises(PermissionError, match="supervisor capability"):
        runner._worker(tmp_path / "config", "annual-analysis", tmp_path / "go")
    assert called is False


def test_analysis_stage_uses_public_api_with_approved_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = runner._validate_shape(_config(tmp_path))
    calls = []

    def prepare_analysis(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(runner.analysis, "prepare_analysis", prepare_analysis)
    monkeypatch.setattr(runner.screening, "expanded_analysis_profile", lambda: [{"row_id": "x"}])
    runner._run_analysis(config, quarterly=False)
    assert len(calls) == 5
    assert all(call["period_mode"] == "ANNUAL" for call in calls)
    assert all(call["include_year_end_balances"] is True for call in calls)
    assert all(call["include_quarter_source_evidence"] is False for call in calls)

    calls.clear()
    runner._run_analysis(config, quarterly=True)
    assert len(calls) == 5
    assert all(call["period_mode"] == "QUARTERLY" for call in calls)
    assert all(call["include_quarter_source_evidence"] is True for call in calls)
    assert all(call["include_year_end_balances"] is False for call in calls)


def test_worker_requires_parent_held_shared_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_fd, write_fd = runner.os.pipe()
    token = b"x" * 32
    runner.os.write(write_fd, token)
    runner.os.close(write_fd)
    monkeypatch.setenv("SEC_XBRL_FINANCIAL_SUPERVISOR_FD", str(read_fd))
    monkeypatch.setenv("SEC_XBRL_FINANCIAL_SUPERVISOR_PID", "123")
    monkeypatch.setenv(
        "SEC_XBRL_FINANCIAL_SUPERVISOR_SHA256", runner.hashlib.sha256(token).hexdigest()
    )
    monkeypatch.setenv("POLARS_MAX_THREADS", "2")
    monkeypatch.setattr(runner.os, "getppid", lambda: 123)

    @contextmanager
    def unlocked(_: Path):
        yield

    monkeypatch.setattr(runner.resource_ops, "heavy_lock", unlocked)
    with pytest.raises(PermissionError, match="parent-held heavy lock"):
        runner._receive_supervisor({"resource_root": str(tmp_path)})


def test_parent_receipt_rejects_mutated_output(
    tmp_path: Path,
) -> None:
    root = tmp_path / "output"
    root.mkdir()
    payload = root / "manifest.json"
    payload.write_text("one", encoding="utf-8")
    receipt = {
        "outputs": [
            {
                "root": str(root.resolve()),
                "files": [
                    {
                        "path": str(payload.resolve()),
                        "relative_path": "manifest.json",
                        "sha256": runner.sha256_file(payload),
                        "size": payload.stat().st_size,
                    }
                ],
            }
        ]
    }
    runner._verify_output_receipt(receipt, "parent")
    payload.write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="output changed"):
        runner._verify_output_receipt(receipt, "parent")


def test_runner_has_no_network_calculation_or_automatic_retry() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "SECArchiveClient" not in source
    assert "collect_universe" not in source
    assert "automatic retry" not in source.lower()
    assert "DERIVED_METRIC" not in source
    assert "metric_identity._quarter_spine" not in source
