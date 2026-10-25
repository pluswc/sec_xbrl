from __future__ import annotations

import json
import os
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import universe50_financial_ops as runner


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _config(tmp_path: Path) -> dict:
    companies = [
        {
            "ticker": ticker,
            "cik": f"{index:010d}",
            "input_years": [2021, 2022, 2023, 2024, 2025],
            "display_years": [2022, 2023, 2024, 2025],
            "quarter_input_years": [2021, 2022, 2023, 2024, 2025, 2026],
            "history_output_root": str(tmp_path / f"history/{ticker}"),
            "history_root": str(tmp_path / f"history/{ticker}"),
            "build_manifest": str(
                tmp_path / f"collection/companies/{ticker}/build_manifest.json"
            ),
            "build_manifest_sha256": "0" * 64,
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
            "manifest": str(tmp_path / "collection/collection_manifest.json"),
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


def _materialize_first5_acceptance(tmp_path: Path) -> dict:
    first5 = runner._validate_shape(_config(tmp_path))
    metadata_root = Path(first5["metadata"]["root"])
    _write_json(metadata_root / runner.company_metadata.MANIFEST_NAME, {"fixture": True})
    manifests = (
        ("quality", "quality", runner.metric_quality.MANIFEST_NAME),
        ("identity", "identity", runner.metric_identity.MANIFEST_NAME),
        ("annual_metrics", "annual_metrics", runner.screening.MANIFEST),
        ("annual_dataset_v2", "annual_dataset_v2", runner.dataset_v2.MANIFEST),
        ("quarterly_metrics", "quarterly_metrics", runner.quarterly_screening.MANIFEST),
        ("combined_dataset_v3", "combined_dataset_v3", runner.dataset_v3.MANIFEST),
    )
    for name, key, filename in manifests:
        _write_json(Path(first5["outputs"][key]) / filename, {"name": name})
    for ticker in runner.FIRST5:
        for key in ("annual_analysis", "quarterly_analysis"):
            _write_json(
                Path(first5["outputs"][key]) / ticker / "analysis_manifest.json",
                {"name": f"{key}:{ticker}"},
            )
    for key in ("quality_indexes", "quality_bindings"):
        _write_json(Path(first5["outputs"][key]) / "fixture.json", {"key": key})
    first5_path = _write_json(tmp_path / "first5-config.json", first5)
    stages = list(runner.FIRST5_ACCEPTED_STAGES)
    receipts = {}
    for stage in stages:
        receipt = {
            "schema_version": runner.RECEIPT_VERSION,
            "status": "PASS",
            "stage": stage,
            "source_head": first5["source"]["head"],
            "go_sha256": "a" * 64,
            "outputs": runner._output_receipts(first5, stage),
        }
        path = _write_json(tmp_path / f"accepted-receipts/{stage}.json", receipt)
        receipts[stage] = {"path": str(path), "sha256": runner.sha256_file(path)}
    acceptance = {
        "schema_version": runner.FIRST5_ACCEPTANCE_VERSION,
        "status": runner.FIRST5_ACCEPTANCE_STATUS,
        "source_head": first5["source"]["head"],
        "financial_as_of": runner.FINANCIAL_AS_OF,
        "metadata_observation_cutoff": runner.METADATA_CUTOFF,
        "collection": first5["collection"],
        "companies": runner._first5_companies(first5),
        "first5_config": {
            "path": str(first5_path),
            "sha256": runner.sha256_file(first5_path),
        },
        "stage_receipts": receipts,
        "publication_manifests": runner._expected_publication_manifests(first5),
    }
    acceptance_path = _write_json(tmp_path / "first5-acceptance.json", acceptance)
    full = _config(tmp_path)
    full["collection_scope_mode"] = "FULL"
    for index in range(6, 51):
        ticker = f"X{index:02d}"
        full["companies"].append(
            {
                "ticker": ticker,
                "cik": f"{index:010d}",
                "input_years": [2021, 2022, 2023, 2024, 2025],
                "display_years": [2022, 2023, 2024, 2025],
                "quarter_input_years": [2021, 2022, 2023, 2024, 2025, 2026],
                "history_output_root": str(tmp_path / f"history/{ticker}"),
                "history_root": str(tmp_path / f"history/{ticker}/panels"),
                "build_manifest": str(
                    tmp_path / f"collection/companies/{ticker}/build_manifest.json"
                ),
                "build_manifest_sha256": "0" * 64,
                "history_manifest_sha256": "1" * 64,
                "collector_source_commit_sha": "a" * 40,
                "plan_sha256": "2" * 64,
                "intake_sha256": "3" * 64,
            }
        )
    full["outputs"] = {
        key: str(tmp_path / "full-outputs" / key) for key in full["outputs"]
    }
    full["first5_financial_acceptance"] = {
        "path": str(acceptance_path),
        "sha256": runner.sha256_file(acceptance_path),
    }
    return runner._validate_shape(full)


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


@pytest.mark.parametrize(
    "quarter_years",
    (
        None,
        [],
        [2022, 2023, 2024, 2025, 2026],
        [2021, 2022, 2024, 2025, 2026],
        [2021, 2022, 2023, 2024],
        [2021, 2022, True, 2024, 2025, 2026],
    ),
)
def test_config_rejects_implicit_or_incomplete_quarter_fiscal_window(
    tmp_path: Path, quarter_years: object
) -> None:
    value = _config(tmp_path)
    value["companies"][0]["quarter_input_years"] = quarter_years
    with pytest.raises(ValueError, match="quarterly window"):
        runner._validate_shape(value)


def test_full_scope_requires_exact_immutable_first5_financial_acceptance(
    tmp_path: Path,
) -> None:
    full = _materialize_first5_acceptance(tmp_path)
    binding = runner._validate_first5_acceptance(full)
    assert binding is not None
    assert binding["status"] == runner.FIRST5_ACCEPTANCE_STATUS
    assert set(binding["stage_receipts"]) == set(runner.FIRST5_ACCEPTED_STAGES)

    missing = _config(tmp_path / "missing")
    missing["collection_scope_mode"] = "FULL"
    missing["companies"] = full["companies"]
    with pytest.raises(ValueError, match="requires first-five"):
        runner._validate_shape(missing)

    acceptance_path = Path(full["first5_financial_acceptance"]["path"])
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["source_head"] = "c" * 40
    _write_json(acceptance_path, acceptance)
    with pytest.raises(ValueError, match="hash differs"):
        runner._validate_first5_acceptance(full)


@pytest.mark.parametrize(
    ("defect", "match"),
    (
        ("source", "scope differs"),
        ("cohort", "scope differs"),
        ("parent", "scope differs"),
        ("receipt_set", "receipt set differs"),
        ("publication", "publication manifests differ"),
    ),
)
def test_full_acceptance_rejects_rehashed_wrong_scope_or_partial_evidence(
    tmp_path: Path, defect: str, match: str
) -> None:
    full = _materialize_first5_acceptance(tmp_path)
    acceptance_path = Path(full["first5_financial_acceptance"]["path"])
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if defect == "source":
        acceptance["source_head"] = "c" * 40
    elif defect == "cohort":
        acceptance["companies"] = list(reversed(acceptance["companies"]))
    elif defect == "parent":
        acceptance["collection"]["parent_company_count"] = 49
    elif defect == "receipt_set":
        acceptance["stage_receipts"].pop("quality")
    else:
        acceptance["publication_manifests"][0]["manifest_sha256"] = "0" * 64
    acceptance_path.write_text(
        json.dumps(acceptance, sort_keys=True) + "\n", encoding="utf-8"
    )
    full["first5_financial_acceptance"]["sha256"] = runner.sha256_file(
        acceptance_path
    )
    with pytest.raises(ValueError, match=match):
        runner._validate_first5_acceptance(full)


def test_full_request_rechecks_first5_acceptance_even_after_mocked_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = _materialize_first5_acceptance(tmp_path)
    preflight = _write_json(Path(full["execution_root"]) / "preflight.json", {})
    monkeypatch.setattr(
        runner,
        "_validated_preflight",
        lambda _: (full, "d" * 64, preflight),
    )
    acceptance_path = Path(full["first5_financial_acceptance"]["path"])
    acceptance_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash differs"):
        runner.request_stage(tmp_path / "config.json", "annual-analysis")


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


def test_selected_history_must_match_exact_ready_build_marker(tmp_path: Path) -> None:
    value = _config(tmp_path)
    company = value["companies"][0]
    ticker = company["ticker"]
    output_root = tmp_path / f"history-output/{ticker}"
    publication = output_root / "panels"
    history_manifest = _write_json(
        publication / "history_manifest.json",
        {"plan": {"as_of_date": runner.FINANCIAL_AS_OF}},
    )
    company["history_output_root"] = str(output_root)
    company["history_root"] = str(publication)
    company["history_manifest_sha256"] = runner.sha256_file(history_manifest)
    marker_path = Path(company["build_manifest"])
    marker = {
        "status": "READY",
        "ticker": ticker,
        "output_root": str(output_root),
        "publication": str(publication),
        "history_manifest": str(history_manifest),
        "history_manifest_sha256": company["history_manifest_sha256"],
        "plan_sha256": company["plan_sha256"],
        "intake_sha256": company["intake_sha256"],
    }
    _write_json(marker_path, marker)
    company["build_manifest_sha256"] = runner.sha256_file(marker_path)
    config = runner._validate_shape(value)
    bound = runner._validate_history_build_binding(config, config["companies"][0])
    assert bound["history_root"] == str(publication)
    assert bound["history_output_root"] == str(output_root)

    unrelated = tmp_path / f"unrelated/{ticker}/panels"
    unrelated_manifest = _write_json(
        unrelated / "history_manifest.json",
        {"plan": {"as_of_date": runner.FINANCIAL_AS_OF}},
    )
    config["companies"][0]["history_root"] = str(unrelated)
    config["companies"][0]["history_manifest_sha256"] = runner.sha256_file(
        unrelated_manifest
    )
    with pytest.raises(ValueError, match="differs from READY build marker"):
        runner._validate_history_build_binding(config, config["companies"][0])


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
        "first5_financial_acceptance": None,
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
    monkeypatch.setitem(runner.STAGE_HANDLERS, "annual-analysis", producer)
    monkeypatch.delenv("SEC_XBRL_T3V2_SUPERVISOR_PID", raising=False)
    with pytest.raises(PermissionError, match="supervisor"):
        runner._worker(tmp_path / "config", "annual-analysis", tmp_path / "go")
    assert called is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux operations contract")
def test_real_supervised_financial_child_reaches_producer_without_guard_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = runner._validate_shape(_config(tmp_path))
    Path(config["resource_root"]).mkdir()

    def producer(value: dict) -> None:
        output = Path(value["outputs"]["annual_analysis"])
        output.mkdir(parents=True)
        (output / "producer-reached.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_validate_go", lambda *args: config)
    monkeypatch.setitem(runner.STAGE_HANDLERS, "annual-analysis", producer)
    go_file = _write_json(tmp_path / "go", {"status": "GO"})
    token = os.urandom(32)
    token_read, token_write = os.pipe()
    result_read, result_write = os.pipe()
    with runner.resource_ops.heavy_lock(Path(config["resource_root"])):
        pid = os.fork()
        if pid == 0:
            try:
                os.close(token_write)
                os.close(result_read)
                parent = str(os.getppid())
                os.environ.update(
                    SEC_XBRL_FINANCIAL_SUPERVISOR_FD=str(token_read),
                    SEC_XBRL_FINANCIAL_SUPERVISOR_PID=parent,
                    SEC_XBRL_FINANCIAL_SUPERVISOR_SHA256=runner.hashlib.sha256(
                        token
                    ).hexdigest(),
                    SEC_XBRL_T3V2_SUPERVISOR_PID=parent,
                    POLARS_MAX_THREADS="2",
                )
                receipt = runner._worker(
                    tmp_path / "config", "annual-analysis", go_file
                )
                os.write(result_write, str(receipt).encode())
                os._exit(0)
            except Exception as exc:  # noqa: BLE001 - child must return diagnostics
                os.write(result_write, (repr(exc) + "\n" + traceback.format_exc()).encode())
                os._exit(70)
        os.close(token_read)
        os.close(result_write)
        os.write(token_write, token)
        os.close(token_write)
        result = os.read(result_read, 4096)
        os.close(result_read)
        _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, result.decode()
    receipt = Path(result.decode())
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "PASS"
    assert (Path(config["outputs"]["annual_analysis"]) / "producer-reached.json").is_file()


def test_financial_supervisor_exports_ops_parent_guard_namespace() -> None:
    env = runner._worker_environment(read_fd=17, token=b"x" * 32)
    assert env["SEC_XBRL_FINANCIAL_SUPERVISOR_PID"] == str(os.getpid())
    assert env["SEC_XBRL_T3V2_SUPERVISOR_PID"] == str(os.getpid())
    assert env["SEC_XBRL_FINANCIAL_SUPERVISOR_FD"] == "17"


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
    assert {(call["fiscal_start"], call["fiscal_end"]) for call in calls} == {
        (2021, 2025)
    }

    calls.clear()
    config["companies"][0]["quarter_input_years"].append(2027)
    runner._run_analysis(config, quarterly=True)
    assert len(calls) == 5
    assert all(call["period_mode"] == "QUARTERLY" for call in calls)
    assert all(call["include_quarter_source_evidence"] is True for call in calls)
    assert all(call["include_year_end_balances"] is False for call in calls)
    assert calls[0]["fiscal_start"] == 2021
    assert calls[0]["fiscal_end"] == 2027
    assert {(call["fiscal_start"], call["fiscal_end"]) for call in calls[1:]} == {
        (2021, 2026)
    }


def test_quarterly_stage_adapts_completed_bucket_spine_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = runner._validate_shape(_config(tmp_path))
    captured: dict[str, object] = {}

    def capture_config(
        _config: dict, name: str, value: dict[str, object]
    ) -> Path:
        assert name == "quarterly-metrics"
        captured.update(value)
        return tmp_path / "quarterly-metrics.json"

    monkeypatch.setattr(runner, "_config_file", capture_config)
    monkeypatch.setattr(runner, "sha256_file", lambda _path: "8" * 64)
    monkeypatch.setattr(
        runner.quarterly_screening,
        "publish_quarterly_screening_metrics",
        lambda _config_path, _destination: None,
    )

    runner._run_quarterly_metrics(config)
    normalized = runner.quarterly_screening._validate_config(captured)
    assert normalized["global_quarter_spine"] == [
        {
            "calendar_year": year,
            "calendar_quarter": quarter,
            "status": "COMPLETED_BUCKET",
        }
        for year, quarter in runner.GLOBAL_QUARTER_SPINE
    ]
    assert runner._global_quarter_spine() == [
        {"calendar_year": year, "calendar_quarter": quarter}
        for year, quarter in runner.GLOBAL_QUARTER_SPINE
    ]

    for mutate in (
        lambda spine: spine[0].update(status="BUILDING"),
        lambda spine: spine[0].update(calendar_year=2023),
    ):
        changed = json.loads(json.dumps(captured))
        mutate(changed["global_quarter_spine"])
        with pytest.raises(ValueError, match="completed cutoff buckets"):
            runner.quarterly_screening._validate_config(changed)


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
