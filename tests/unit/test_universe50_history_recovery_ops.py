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
        {"ticker": ticker, "cik": f"{index:010d}"} for index, ticker in enumerate(tickers, start=1)
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
        "reported_reuse": None,
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
    plan = _write(
        paths["plan"],
        {
            "as_of_date": runner.FINANCIAL_AS_OF,
            "companies": [
                {
                    "ticker": config["target"]["ticker"],
                    "cik": config["target"]["cik"],
                    "filings": [],
                }
            ],
        },
    )
    intake = _write(paths["intake"], {"complete": True, "plan": json.loads(plan.read_text())})
    config["target"]["plan_sha256"] = runner._sha256(plan)
    config["target"]["intake_sha256"] = runner._sha256(intake)
    candidate_payload = json.loads(candidate.read_text())
    target_row = next(
        row for row in candidate_payload["selection"] if row["ticker"] == config["target"]["ticker"]
    )
    target_row["plan_sha256"] = config["target"]["plan_sha256"]
    target_row["intake_sha256"] = config["target"]["intake_sha256"]
    _write(candidate, candidate_payload)
    collection["candidate_sha256"] = runner._sha256(candidate)
    Path(config["target"]["history_parent"]).mkdir()
    Path(config["resource_root"]).mkdir(exist_ok=True)
    if prior_failure:
        abandoned = Path(config["target"]["history_parent"]) / "old-partial"
        attempt = _write(
            paths["company_root"] / "operation_attempts/build-failed.json",
            {"result": {"status": "BUILD_FAILED", "output_root": str(abandoned)}},
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
            "companies": [{"ticker": target["ticker"], "plan_sha256": target["plan_sha256"]}]
        },
        plans={target["ticker"]: json.loads(plan.read_text())},
    )
    monkeypatch.setattr(runner.ops, "read_universe_status", lambda **_: status, raising=False)
    monkeypatch.setattr(runner.ops, "_attest_run", lambda _: run, raising=False)
    monkeypatch.setattr(
        runner.ops,
        "_attest_intake",
        lambda *_: SimpleNamespace(sha256=target["intake_sha256"], complete=True, error=None),
        raising=False,
    )
    return config, status


def test_target_reopens_exact_collection_and_allows_only_pinned_jnj_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch, prior_failure=True)
    binding = runner._validate_collection_target(runner._validate_shape(config))
    assert binding["target"]["state"] == "BUILD_FAILED"
    assert binding["target"]["destination"].endswith("JNJ-history-recovery-bounded-memory-v1")

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


@pytest.fixture(scope="module")
def canonical_checkout(tmp_path_factory):
    checkout = tmp_path_factory.mktemp("canonical9b") / "checkout"
    source = Path(runner.__file__).parents[1]
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(source), str(checkout)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", "--quiet", runner.FINANCIAL_SOURCE_SHA], check=True
    )
    return checkout


@pytest.fixture(scope="module")
def prior_recovery_checkout(tmp_path_factory):
    checkout = tmp_path_factory.mktemp("prior-recovery-a02") / "checkout"
    source = Path(runner.__file__).parents[1]
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(source), str(checkout)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", "--quiet", runner.PRIOR_RECOVERY_SOURCE_SHA],
        check=True,
    )
    return checkout


def _materialize_financial_acceptance(config: dict, tmp_path: Path, checkout: Path) -> Path:
    # Only a genuine-shaped first-five config is constructed; no future 45 pins.
    from tests.unit.test_universe50_financial_ops import _config as financial_config
    from tools import universe50_financial_ops as financial

    first5 = financial_config(tmp_path / "accepted")
    first5["collection"] = {
        k: config["collection"][k] for k in ("manifest", "manifest_sha256", "parent_company_count")
    }
    first5["source"] = {
        "checkout": str(checkout),
        "head": runner.FINANCIAL_SOURCE_SHA,
        "module_sha256s": {
            name: runner._sha256(checkout / relative)
            for name, relative in financial.PINNED_MODULES.items()
        },
    }
    metadata = _write(
        Path(first5["metadata"]["root"]) / financial.company_metadata.MANIFEST_NAME,
        {"synthetic": True},
    )
    first5["metadata"]["manifest_sha256"] = runner._sha256(metadata)
    for key, filename in (
        ("quality", financial.metric_quality.MANIFEST_NAME),
        ("identity", financial.metric_identity.MANIFEST_NAME),
        ("annual_metrics", financial.screening.MANIFEST),
        ("annual_dataset_v2", financial.dataset_v2.MANIFEST),
        ("quarterly_metrics", financial.quarterly_screening.MANIFEST),
        ("combined_dataset_v3", financial.dataset_v3.MANIFEST),
        ("quality_indexes", "fixture.json"),
        ("quality_bindings", "fixture.json"),
    ):
        _write(Path(first5["outputs"][key]) / filename, {"synthetic": key})
    for ticker in runner.FIRST5:
        for key in ("annual_analysis", "quarterly_analysis"):
            _write(
                Path(first5["outputs"][key]) / ticker / "analysis_manifest.json",
                {"synthetic": ticker},
            )
    receipts = {}
    for stage in financial.FIRST5_ACCEPTED_STAGES:
        receipt = {
            "schema_version": financial.RECEIPT_VERSION,
            "status": "PASS",
            "stage": stage,
            "source_head": runner.FINANCIAL_SOURCE_SHA,
            "go_sha256": "a" * 64,
            "outputs": financial._output_receipts(first5, stage),
        }
        path = _write(tmp_path / "accepted-receipts" / f"{stage}.json", receipt)
        receipts[stage] = {"path": str(path), "sha256": runner._sha256(path)}
    first5_path = _write(tmp_path / "first5-config.json", first5)
    path = _write(
        tmp_path / "first5-acceptance.json",
        {
            "schema_version": runner.FINANCIAL_ACCEPTANCE_VERSION,
            "status": runner.FINANCIAL_ACCEPTANCE_STATUS,
            "source_head": runner.FINANCIAL_SOURCE_SHA,
            "financial_as_of": runner.FINANCIAL_AS_OF,
            "metadata_observation_cutoff": runner.METADATA_CUTOFF,
            "collection": first5["collection"],
            "companies": financial._first5_companies(first5),
            "first5_config": {"path": str(first5_path), "sha256": runner._sha256(first5_path)},
            "stage_receipts": receipts,
            "publication_manifests": financial._expected_publication_manifests(first5),
        },
    )
    config["first5_financial_acceptance"] = {"path": str(path), "sha256": runner._sha256(path)}
    return path


def test_later45_gate_requires_canonical_object_cohort_receipts_and_publications(
    tmp_path: Path,
    canonical_checkout: Path,
) -> None:
    config = _config(tmp_path, ticker="X06")
    manifest = _write(Path(config["collection"]["manifest"]), {})
    config["collection"]["manifest_sha256"] = runner._sha256(manifest)
    acceptance = _materialize_financial_acceptance(config, tmp_path, canonical_checkout)
    binding = runner._verify_financial_acceptance(runner._validate_shape(config))
    assert binding is not None
    assert runner.RUNNER_BASE_SHA == "9b6e7ec906382fba92adb5209c5b439fc7d7d6ba"
    assert runner.FINANCIAL_SOURCE_SHA == "fd9a17910a7b1cfbb4e71e2ded6f4bc23cda686e"
    assert runner.FINANCIAL_SOURCE_SHA != runner.RUNNER_BASE_SHA
    assert binding["source_head"] == runner.FINANCIAL_SOURCE_SHA
    assert len(binding["publication_manifests"]) == 17

    payload = json.loads(acceptance.read_text())
    payload["companies"] = list(runner.FIRST5)
    _write(acceptance, payload)
    config["first5_financial_acceptance"]["sha256"] = runner._sha256(acceptance)
    with pytest.raises(ValueError, match="scope differs"):
        runner._verify_financial_acceptance(runner._validate_shape(config))


def test_later45_gate_rejects_old_9b_financial_source(
    tmp_path: Path,
    canonical_checkout: Path,
) -> None:
    config = _config(tmp_path, ticker="X06")
    manifest = _write(Path(config["collection"]["manifest"]), {})
    config["collection"]["manifest_sha256"] = runner._sha256(manifest)
    acceptance = _materialize_financial_acceptance(config, tmp_path, canonical_checkout)
    payload = json.loads(acceptance.read_text())
    payload["source_head"] = runner.RUNNER_BASE_SHA
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
        "reported_reuse": {"binding": "exact-reported-stage"},
    }
    monkeypatch.setattr(runner, "_snapshot", lambda _: snapshot)
    preflight = runner.preflight(config_path)
    request = runner.request_stage(config_path)
    _, expected_go = runner._expected_go(config_path)
    go = _write(tmp_path / "root-go.json", expected_go)
    assert runner._validate_go(config_path, go)["target"]["ticker"] == "JNJ"
    assert json.loads(request.read_text())["reported_reuse"] == snapshot["reported_reuse"]
    assert expected_go["reported_reuse"] == snapshot["reported_reuse"]

    changed = json.loads(request.read_text())
    changed["target"]["cik"] = "9999999999"
    _write(request, changed)
    with pytest.raises(ValueError, match="request changed"):
        runner._validate_go(config_path, go)
    assert preflight.is_file()


def test_cli_preflight_and_request_preserve_optional_reported_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)
    Path(config["resource_root"]).mkdir()
    Path(config["target"]["history_parent"]).mkdir()
    config_path = _write(tmp_path / "config.json", config)
    reuse = {"mode": "ATTESTED_REPORTED_STAGE", "binding": "synthetic-cli"}
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda _: {
            "runner": {"head": config["runner"]["head"]},
            "engine": {"head": config["engine"]["head"]},
            "collection": {"target": {"ticker": "JNJ", "cik": "0000000003"}},
            "first5_financial_acceptance": None,
            "reported_reuse": reuse,
        },
    )
    assert runner.main(["preflight", "--config", str(config_path)]) == 0
    preflight_output = json.loads(capsys.readouterr().out)
    assert Path(preflight_output["path"]).is_file()
    assert runner.main(["request-stage", "--config", str(config_path)]) == 0
    request_output = json.loads(capsys.readouterr().out)
    request = json.loads(Path(request_output["path"]).read_text())
    assert request["reported_reuse"] == reuse
    _, go = runner._expected_go(config_path)
    assert go["reported_reuse"] == reuse


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
            "reported_reuse": None,
        },
    )
    monkeypatch.setattr(runner.history, "build_history", build_history, raising=False)
    monkeypatch.setattr(runner.history, "HistoryPublicationReader", Reader, raising=False)
    monkeypatch.setattr(runner.ops, "_create_build_attestation", lambda **_: marker, raising=False)
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
        lambda **_: SimpleNamespace(companies=(SimpleNamespace(ticker="JNJ", state="READY"),)),
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


def test_execute_attested_reuse_calls_real_public_recovery_and_retains_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_history_recovery import _recovery_fixture

    kwargs, proof = _recovery_fixture(tmp_path / "public", monkeypatch)
    source_stage = kwargs["staged_publication"]
    (source_stage / ".chunks").mkdir()
    clean_stage = tmp_path / "clean-stage"
    shutil.copytree(source_stage, clean_stage, ignore=shutil.ignore_patterns(".chunks"))
    Path(kwargs["operational_root"]).mkdir(exist_ok=True)
    report_path = Path(proof["verification_report"]["path"])
    report = json.loads(report_path.read_text())
    proof["generation_source_identity"] = runner.REPORTED_GENERATION_SOURCE_SHA
    proof["recovery_source_identity"] = runner.REPORTED_RECOVERY_SOURCE_SHA
    report.update(
        source_generation_sha=runner.REPORTED_GENERATION_SOURCE_SHA,
        recovery_source_sha=runner.REPORTED_RECOVERY_SOURCE_SHA,
    )
    _write(report_path, report)
    proof["verification_report"]["sha256"] = runner._sha256(report_path)
    attestation = kwargs["attestation"]
    _write(attestation, proof)

    config, _ = _materialize_collection_target(_config(tmp_path / "runner"), monkeypatch)
    config = runner._validate_shape(config)
    binding = runner._validate_collection_target(config)
    paths = runner._target_paths(config)
    reuse = {
        "generation_source_head": runner.REPORTED_GENERATION_SOURCE_SHA,
        "recovery_source_head": runner.REPORTED_RECOVERY_SOURCE_SHA,
        "clean_stage": {
            "root": str(clean_stage),
            "manifest_sha256": runner._sha256(clean_stage / "history_manifest.json"),
        },
        "component_report": {
            "path": str(report_path),
            "sha256": runner._sha256(report_path),
        },
        "root_attestation": {
            "path": str(attestation),
            "sha256": runner._sha256(attestation),
        },
        "intake": {
            "path": str(kwargs["intake_manifest"]),
            "sha256": runner._sha256(kwargs["intake_manifest"]),
        },
        "original_operational_root": str(kwargs["operational_root"]),
    }
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda _: {
            "runner": {"synthetic_authorization_only": True},
            "engine": {"synthetic_authorization_only": True},
            "collection": binding,
            "first5_financial_acceptance": None,
            "reported_reuse": reuse,
        },
    )
    marker = {
        "publication": str(paths["destination"] / "panels"),
        "history_manifest_sha256": "d" * 64,
        "declared_files": {"history_manifest.json": "e" * 64},
    }
    monkeypatch.setattr(runner.ops, "_create_build_attestation", lambda **_: marker)
    monkeypatch.setattr(runner.ops, "_validate_build_attestation", lambda *_, **__: None)
    monkeypatch.setattr(
        runner.ops,
        "_write_once_json",
        lambda path, value, **_: _write(path, value),
    )
    monkeypatch.setattr(
        runner.ops,
        "read_universe_status",
        lambda **_: SimpleNamespace(companies=(SimpleNamespace(ticker="JNJ", state="READY"),)),
    )
    go = _write(tmp_path / "reuse-go.json", {"authorized_by": "ROOT_LEAD"})
    receipt_path = runner._execute_recovery(config, go)
    receipt = json.loads(receipt_path.read_text())
    public_receipt = json.loads(
        (paths["destination"] / "reported_recovery_receipt.json").read_text()
    )
    assert public_receipt["status"] == "COMPLETE"
    assert receipt["status"] == "READY"
    assert receipt["reported_reuse"]["original_operational_root"] == str(
        kwargs["operational_root"]
    )
    assert receipt["public_reported_recovery_receipt"]["sha256"] == runner._sha256(
        paths["destination"] / "reported_recovery_receipt.json"
    )
    runner.history.HistoryPublicationReader(Path(receipt["publication"])).verify_all()


def test_attested_reuse_rejects_incomplete_public_receipt_before_ready_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    config = runner._validate_shape(config)
    binding = runner._validate_collection_target(config)
    paths = runner._target_paths(config)
    evidence = _write(tmp_path / "component.json", {"synthetic": True})
    intake = _write(tmp_path / "reuse-intake.json", {"synthetic": True})
    attestation = _write(tmp_path / "attestation.json", {"synthetic": True})
    clean = tmp_path / "clean"
    clean.mkdir()
    reuse = {
        "generation_source_head": runner.REPORTED_GENERATION_SOURCE_SHA,
        "recovery_source_head": runner.REPORTED_RECOVERY_SOURCE_SHA,
        "clean_stage": {"root": str(clean), "manifest_sha256": "a" * 64},
        "component_report": {"path": str(evidence), "sha256": runner._sha256(evidence)},
        "root_attestation": {
            "path": str(attestation),
            "sha256": runner._sha256(attestation),
        },
        "intake": {"path": str(intake), "sha256": runner._sha256(intake)},
        "original_operational_root": str(tmp_path / "operational"),
    }
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda _: {
            "runner": {},
            "engine": {},
            "collection": binding,
            "first5_financial_acceptance": None,
            "reported_reuse": reuse,
        },
    )

    def recover(**_):
        publication = paths["destination"] / "panels"
        _write(publication / "history_manifest.json", {})
        _write(
            paths["destination"] / "reported_recovery_receipt.json",
            {"version": "reported-stage-recovery-v1", "status": "NOT_READY"},
        )
        return publication

    class Reader:
        def __init__(self, _):
            pass

        def verify_all(self):
            return None

    monkeypatch.setattr(runner.history, "recover_reported_history", recover)
    monkeypatch.setattr(runner.history, "HistoryPublicationReader", Reader)
    monkeypatch.setattr(
        runner.ops,
        "_create_build_attestation",
        lambda **_: pytest.fail("READY marker attempted before public receipt validation"),
    )
    with pytest.raises(ValueError, match="public reported recovery receipt identity"):
        runner._execute_recovery(config, _write(tmp_path / "go.json", {}))
    assert not paths["marker"].exists()
    assert not paths["receipt"].exists()


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
        name: runner._sha256(engine / relative) for name, relative in runner.ENGINE_MODULES.items()
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
            },
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
    env["PYTHONPATH"] = os.pathsep.join((str(engine / "src"), str(runner_checkout)))
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
    import ast

    imports = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not any("universe50_financial_ops" in ast.unparse(node) for node in imports)
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
                    SEC_XBRL_T3V2_SUPERVISOR_SHA256=runner.hashlib.sha256(token).hexdigest(),
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


@pytest.mark.parametrize(
    "mutation",
    [
        "outputs_missing",
        "quality_rebound",
        "quality_indexes_rebound",
        "metadata_rebound",
        "metadata_hash",
        "manifest_swap",
        "missing_receipt",
        "extra_receipt",
        "fileset",
        "shape",
    ],
)
def test_canonical_gate_rejects_rehashed_broken_bindings(tmp_path, canonical_checkout, mutation):
    config = _config(tmp_path, ticker="X06")
    path = _materialize_financial_acceptance(config, tmp_path, canonical_checkout)
    acceptance = json.loads(path.read_text())
    first_path = Path(acceptance["first5_config"]["path"])
    first = json.loads(first_path.read_text())
    if mutation == "outputs_missing":
        del first["outputs"]
    elif mutation in {"quality_rebound", "quality_indexes_rebound"}:
        first["outputs"][mutation.removesuffix("_rebound")] = str(tmp_path / "foreign-output")
    elif mutation == "metadata_rebound":
        first["metadata"]["root"] = first["outputs"]["quality"]
    elif mutation == "metadata_hash":
        first["metadata"]["manifest_sha256"] = "0" * 64
    elif mutation == "manifest_swap":
        acceptance["publication_manifests"][1], acceptance["publication_manifests"][2] = (
            acceptance["publication_manifests"][2],
            acceptance["publication_manifests"][1],
        )
    elif mutation == "missing_receipt":
        del acceptance["stage_receipts"]["quality"]
    elif mutation == "extra_receipt":
        acceptance["stage_receipts"]["metadata"] = acceptance["stage_receipts"]["quality"]
    elif mutation == "fileset":
        _write(Path(first["outputs"]["quality"]) / "unreceipted.json", {})
    else:
        del first["package_view"]
    _write(first_path, first)
    acceptance["first5_config"]["sha256"] = runner._sha256(first_path)
    _write(path, acceptance)
    config["first5_financial_acceptance"]["sha256"] = runner._sha256(path)
    with pytest.raises(ValueError, match="canonical financial gate rejected"):
        runner._verify_financial_acceptance(config)


@pytest.mark.parametrize(
    "name",
    [
        "history_recovery_receipt-previous-v1.json",
        "ops_build_receipt.json",
        "build_manifest.json",
        "build_manifest.json.partial",
        "history_recovery_receipt-old.json.partial",
    ],
)
def test_all_prior_receipts_and_markers_block_new_version(tmp_path, monkeypatch, name):
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    _write(runner._target_paths(config)["company_root"] / name, {"orphan": True})
    with pytest.raises(ValueError, match="already has"):
        runner._validate_collection_target(config)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_abandoned",
        "descendant",
        "missing_root",
        "symlink_ancestor",
        "orphan_partial",
        "evidence_descendant",
        "conflicting_root",
    ],
)
def test_failed_root_binding_and_ancestry_are_closed(tmp_path, monkeypatch, mutation):
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch, prior_failure=True)
    failed = Path(config["target"]["abandoned_output_roots"][0])
    if mutation == "wrong_abandoned":
        other = tmp_path / "unrelated"
        other.mkdir()
        config["target"]["abandoned_output_roots"] = [str(other)]
    elif mutation == "descendant":
        child = failed / "fresh-child"
        child.mkdir()
        config["target"]["history_parent"] = str(child)
    elif mutation == "missing_root":
        pin = config["target"]["approved_prior_failed_attempts"][0]
        _write(Path(pin["path"]), {"status": "BUILD_FAILED"})
        pin["sha256"] = runner._sha256(Path(pin["path"]))
    elif mutation == "evidence_descendant":
        config["execution_root"] = str(failed / "evidence")
    elif mutation == "conflicting_root":
        pin = config["target"]["approved_prior_failed_attempts"][0]
        value = json.loads(Path(pin["path"]).read_text())
        value["output_root"] = str(tmp_path)
        _write(Path(pin["path"]), value)
        pin["sha256"] = runner._sha256(Path(pin["path"]))
    elif mutation == "symlink_ancestor":
        link = tmp_path / "link"
        link.symlink_to(failed, target_is_directory=True)
        (failed / "child").mkdir()
        config["target"]["history_parent"] = str(link / "child")
    else:
        (Path(config["target"]["history_parent"]) / "JNJ-history-recovery-older-v1").mkdir()
    with pytest.raises(ValueError):
        runner._validate_collection_target(config)


def test_real_synthetic_public_history_attestation_ready_and_typed_receipt(tmp_path, monkeypatch):
    """One tiny synthetic filing, real public build/reader/attestation/status.

    Only the exact-50/source authorization snapshot is substituted: a one-company
    unit fixture cannot claim the real universe or a lead-approved source HEAD.
    """
    from dataclasses import asdict, replace

    import polars as pl

    from tests.unit.test_exploration_graph import _release

    synthetic = _release().snapshots[0]
    source = tmp_path / "synthetic-raw"
    raw_dir = (
        source / "snapshots" / synthetic.input.cik / synthetic.input.accession.replace("-", "")
    )
    raw_dir.mkdir(parents=True)
    for name in synthetic.tables:
        rows = [dict(row) for row in synthetic.records(name)]
        if name == "unit":
            for row in rows:
                row.update(numerator_measures='["iso4217:USD"]', denominator_measures="[]")
        pl.DataFrame(rows).write_parquet(raw_dir / f"{name}.parquet")
    raw_manifest = replace(
        synthetic.manifest,
        source_fact_count=3,
        materialized_fact_count=3,
        concept_count=5,
        context_count=1,
        unit_count=1,
    )
    _write(raw_dir / "layer1_manifest.json", asdict(raw_manifest))
    filing = {
        key: synthetic.records("filing")[0][key]
        for key in ("cik", "accession", "form", "filed_date", "report_date")
    }
    plan = {
        "version": runner.history.HISTORY_VERSION,
        "as_of_date": runner.FINANCIAL_AS_OF,
        "report_start": filing["report_date"],
        "report_end": filing["report_date"],
        "recent_fiscal_years": None,
        "companies": [{"ticker": "SYN", "cik": synthetic.input.cik, "filings": [filing]}],
    }
    universe_config = _write(
        tmp_path / "tiny-universe.json",
        {
            "schema_version": 1,
            "universe_id": "tiny-synthetic-recovery",
            "purpose": "synthetic test",
            "as_of_date": runner.FINANCIAL_AS_OF,
            "source_observed_at": "2026-10-10T00:00:00Z",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [{"ticker": "SYN", "cik": synthetic.input.cik}],
        },
    )
    manifest = runner.ops.prepare_universe(
        config_path=universe_config,
        run_root=tmp_path / "collection",
        existing_plans={"SYN": _write(tmp_path / "tiny-plan.json", plan)},
        offline=True,
    )
    config = _config(tmp_path)
    config["collection"]["manifest"] = str(manifest)
    config["target"].update(
        ticker="SYN",
        cik=synthetic.input.cik,
        history_basename="SYN-history-recovery-bounded-memory-v1",
        selected_filings=1,
    )
    paths = runner._target_paths(config)
    _write(
        paths["intake"],
        {
            "version": runner.history.HISTORY_VERSION,
            "complete": True,
            "plan": plan,
            "filings": [
                {"ticker": "SYN", "filing": filing, "source_run": str(source), "status": "REUSED"}
            ],
        },
    )
    config["target"]["plan_sha256"] = runner._sha256(paths["plan"])
    config["target"]["intake_sha256"] = runner._sha256(paths["intake"])
    before = {str(p): runner._sha256(p) for p in source.rglob("*") if p.is_file()}
    assert (
        runner.ops.read_universe_status(manifest_path=manifest).companies[0].state == "RAW_COMPLETE"
    )
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda _: {
            "runner": {"synthetic_authorization_only": True},
            "engine": {"synthetic_authorization_only": True},
            "first5_financial_acceptance": None,
            "reported_reuse": None,
            "collection": {
                "manifest": str(manifest),
                "manifest_sha256": runner._sha256(manifest),
                "target": {"prior_failed_attempts": [], "abandoned_output_roots": []},
            },
        },
    )
    receipt_path = runner._execute_recovery(
        config, _write(tmp_path / "tiny-go.json", {"synthetic": True})
    )
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema_version"] == runner.RECEIPT_VERSION
    assert receipt["status"] == "READY"
    assert runner.ops.read_universe_status(manifest_path=manifest).companies[0].state == "READY"
    reader = runner.history.HistoryPublicationReader(Path(receipt["publication"]))
    reader.verify_all()
    assert reader.manifest["tables"]
    assert any(table["files"]["cells"]["count"] for table in reader.manifest["tables"])
    assert receipt["build_manifest_sha256"] == runner._sha256(paths["marker"])
    assert before == {str(p): runner._sha256(p) for p in source.rglob("*") if p.is_file()}
    assert not paths["old_receipt"].exists()


def _legacy_fixture(config, checkout):
    root = Path(config["collection"]["manifest"]).parent
    ticker = config["target"]["ticker"]
    old = {
        "schema_version": "universe50-t3v2-ops-config-v1",
        "run_id": "old-exact50-run",
        "source_sha": runner.ENGINE_BASE_SHA,
        "first5": list(runner.FIRST5),
        "collection_root": str(root),
        "history_root": str(root.parent / "failed-history"),
        "limits": config["limits"],
    }
    config_path = _write(root.parent / "legacy-config.json", old)
    program = checkout / "tools/universe50_t3v2_ops.py"
    witness = {
        "config": {"path": str(config_path), "sha256": runner._sha256(config_path)},
        "program": {"path": str(program), "sha256": runner._sha256(program)},
    }
    preflight = _write(
        root / "ops_preflight.json",
        {
            "schema_version": "universe50-t3v2-ops-preflight-v1",
            "status": "PREPARED",
            "source_sha": runner.ENGINE_BASE_SHA,
            "run_id": old["run_id"],
            "config": witness["config"],
            "modules": {"program": witness["program"], "engine": {"aggregate_sha256": "b" * 64}},
        },
    )
    go = _write(
        root.parent / "legacy-go.json",
        {
            "schema_version": "universe50-t3v2-stage-go-v1",
            "status": "GO",
            "operation": "build-one",
            "run_id": old["run_id"],
            "source_sha": runner.ENGINE_BASE_SHA,
            "ops_config_sha256": runner._sha256(config_path),
            "preflight_sha256": runner._sha256(preflight),
            "program_sha256": runner._sha256(program),
            "engine_modules_sha256": "b" * 64,
            "tickers": [ticker],
        },
    )
    witness["go"] = {"path": str(go), "sha256": runner._sha256(go)}
    summary = _write(
        root / "execution" / ticker / "prior.summary.json",
        {
            "schema_version": "universe50-t3v2-resource-run-v1",
            "status": "RSS_LIMIT",
            "returncode": -15,
            "limit_kib": runner.LIMIT_KIB,
            "timeout_seconds": runner.TIMEOUT_SECONDS,
            "command": [
                sys.executable,
                str(program),
                "_build-worker",
                "--config",
                str(config_path),
                "--ticker",
                ticker,
                "--go-file",
                str(go),
            ],
        },
    )
    failed = Path(old["history_root"]) / f"{ticker}-t3v2-{old['run_id']}"
    failed.mkdir(parents=True)
    config["target"]["approved_prior_failed_attempts"] = [
        {"path": str(summary), "sha256": runner._sha256(summary), "legacy_ops": witness}
    ]
    config["target"]["abandoned_output_roots"] = [str(failed)]
    return summary, witness, failed


def _prior_recovery_fixture(
    tmp_path,
    monkeypatch,
    prior_recovery_checkout,
    canonical_checkout,
):
    config, _ = _materialize_collection_target(_config(tmp_path), monkeypatch)
    legacy_summary, legacy_witness, legacy_failed = _legacy_fixture(
        config, canonical_checkout
    )
    old = json.loads(json.dumps(config))
    old["target"].update(
        run_version="accepted-prior-r1",
        history_parent=str(tmp_path / "prior-history"),
        history_basename="JNJ-history-recovery-accepted-prior-r1",
    )
    Path(old["target"]["history_parent"]).mkdir()
    old["execution_root"] = str(tmp_path / "prior-execution")
    old["runner"] = {
        "checkout": str(prior_recovery_checkout),
        "head": runner.PRIOR_RECOVERY_SOURCE_SHA,
        "module_sha256s": {
            name: runner._sha256(prior_recovery_checkout / relative)
            for name, relative in runner.RUNNER_MODULES.items()
        },
    }
    engine_report = _write(tmp_path / "prior-engine-independent.json", {"verdict": "PASS"})
    engine_hashes = {
        name: runner._sha256(prior_recovery_checkout / relative)
        for name, relative in runner.ENGINE_MODULES.items()
    }
    engine_acceptance = _write(
        tmp_path / "prior-engine-acceptance.json",
        {
            "schema_version": runner.ENGINE_ACCEPTANCE_VERSION,
            "status": runner.ENGINE_ACCEPTANCE_STATUS,
            "engine_source_head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "engine_base_sha": runner.ENGINE_BASE_SHA,
            "graph_rule_version": runner.GRAPH_RULE_VERSION,
            "module_sha256s": engine_hashes,
            "independent_report": {
                "path": str(engine_report),
                "sha256": runner._sha256(engine_report),
            },
        },
    )
    old["engine"] = {
        "checkout": str(prior_recovery_checkout),
        "head": runner.PRIOR_RECOVERY_SOURCE_SHA,
        "source_acceptance": {
            "path": str(engine_acceptance),
            "sha256": runner._sha256(engine_acceptance),
        },
    }
    old = runner._validate_shape(old)
    collection_binding = runner._validate_collection_target(old)

    acceptance_pins = {}
    for name in ("independent_report", "writer_report", "lead_contract"):
        path = _write(tmp_path / f"prior-recovery-{name}.json", {"status": "PASS"})
        acceptance_pins[name] = {"path": str(path), "sha256": runner._sha256(path)}
    source_acceptance = _write(
        tmp_path / "prior-recovery-source-acceptance.json",
        {
            "schema_version": runner.PRIOR_RECOVERY_ACCEPTANCE_VERSION,
            "status": runner.PRIOR_RECOVERY_ACCEPTANCE_STATUS,
            "source_head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "source_tree": runner.PRIOR_RECOVERY_SOURCE_TREE,
            "checkout": str(prior_recovery_checkout),
            **acceptance_pins,
            "actual_JNJ_retry_authorized": False,
        },
    )
    monkeypatch.setattr(
        runner, "PRIOR_RECOVERY_ACCEPTANCE_SHA256", runner._sha256(source_acceptance)
    )
    old_config = _write(tmp_path / "prior-recovery-config.json", old)
    program = prior_recovery_checkout / runner.RUNNER_MODULES["runner"]
    resource_program = prior_recovery_checkout / runner.RUNNER_MODULES["resource_ops"]
    engine_files = {
        name: {
            "path": str(prior_recovery_checkout / relative),
            "sha256": engine_hashes[name],
        }
        for name, relative in runner.ENGINE_MODULES.items()
    }
    snapshot = {
        "runner": {
            "checkout": str(prior_recovery_checkout),
            "head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "base": runner.RUNNER_BASE_SHA,
            "files": {
                "runner": {
                    "path": str(program),
                    "sha256": runner.PRIOR_RECOVERY_PROGRAM_SHA256,
                },
                "resource_ops": {
                    "path": str(resource_program),
                    "sha256": runner.PRIOR_RECOVERY_RESOURCE_OPS_SHA256,
                },
            },
        },
        "engine": {
            "checkout": str(prior_recovery_checkout),
            "head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "base": runner.ENGINE_BASE_SHA,
            "acceptance": old["engine"]["source_acceptance"],
            "independent_report": {
                "path": str(engine_report),
                "sha256": runner._sha256(engine_report),
            },
            "files": engine_files,
        },
        "collection": collection_binding,
        "first5_financial_acceptance": None,
    }
    preflight = _write(
        Path(old["execution_root"]) / "preflight.json",
        {
            "schema_version": runner.PREFLIGHT_VERSION,
            "status": "PREPARED_SOURCE_ONLY",
            "config": {"path": str(old_config), "sha256": runner._sha256(old_config)},
            "snapshot": snapshot,
            "resources": {
                "process_tree_rss_kib": runner.LIMIT_KIB,
                "polars_max_threads": runner.POLARS_THREADS,
                "one_heavy_process": True,
                "timeout_seconds": runner.TIMEOUT_SECONDS,
            },
            "execution": "SEPARATE_ROOT_AUTHORED_EXACT_GO_REQUIRED",
        },
    )
    request = _write(
        Path(old["execution_root"]) / "request.json",
        {
            "schema_version": runner.REQUEST_VERSION,
            "status": "AWAITING_EXPLICIT_ROOT_GO",
            "operation": "recover-history-one",
            "config_sha256": runner._sha256(old_config),
            "preflight_sha256": runner._sha256(preflight),
            "runner_head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "engine_head": old["engine"]["head"],
            "collection": collection_binding,
            "target": collection_binding["target"],
            "first5_financial_acceptance": None,
        },
    )
    go = _write(
        tmp_path / "prior-recovery-go.json",
        {
            "schema_version": runner.GO_VERSION,
            "status": "GO",
            "authorized_by": "ROOT_LEAD",
            "operation": "recover-history-one",
            "config_sha256": runner._sha256(old_config),
            "preflight_sha256": runner._sha256(preflight),
            "request_sha256": runner._sha256(request),
            "runner_head": runner.PRIOR_RECOVERY_SOURCE_SHA,
            "engine_head": old["engine"]["head"],
            "collection_manifest_sha256": old["collection"]["manifest_sha256"],
            "target": collection_binding["target"],
            "first5_financial_acceptance": None,
        },
    )
    summary = Path(old["execution_root"]) / "execution.summary.json"
    _write(
        summary,
        {
            "schema_version": runner.RESOURCE_VERSION,
            "status": "TIMEOUT",
            "returncode": -15,
            "elapsed_seconds": runner.TIMEOUT_SECONDS + 1.25,
            "peak_process_tree_rss_kib": 4_795_900,
            "limit_kib": runner.LIMIT_KIB,
            "timeout_seconds": runner.TIMEOUT_SECONDS,
            "command": [
                sys.executable,
                str(program),
                "_worker",
                "--config",
                str(old_config),
                "--go-file",
                str(go),
            ],
            "log": str(summary.with_suffix(".log")),
            "samples": str(summary.with_suffix(".rss.jsonl")),
        },
    )
    summary.with_suffix(".log").write_text("synthetic timeout\n", encoding="utf-8")
    summary.with_suffix(".rss.jsonl").write_text(
        json.dumps({"elapsed_seconds": 1.0, "process_tree_rss_kib": 1024}) + "\n",
        encoding="utf-8",
    )
    failed = runner._target_paths(old)["destination"]
    failed.mkdir()
    witness = {
        "config": {"path": str(old_config), "sha256": runner._sha256(old_config)},
        "preflight": {"path": str(preflight), "sha256": runner._sha256(preflight)},
        "request": {"path": str(request), "sha256": runner._sha256(request)},
        "go": {"path": str(go), "sha256": runner._sha256(go)},
        "program": {"path": str(program), "sha256": runner._sha256(program)},
        "source_acceptance": {
            "path": str(source_acceptance),
            "sha256": runner._sha256(source_acceptance),
        },
    }
    config["target"]["approved_prior_failed_attempts"].append(
        {"path": str(summary), "sha256": runner._sha256(summary), "recovery_ops": witness}
    )
    config["target"]["abandoned_output_roots"].append(str(failed))
    for name, path in (
        ("CONFIG", old_config),
        ("PREFLIGHT", preflight),
        ("REQUEST", request),
        ("GO", go),
        ("SUMMARY", summary),
    ):
        monkeypatch.setattr(
            runner, f"PRIOR_RECOVERY_{name}_SHA256", runner._sha256(path)
        )
    return config, {
        "old": old,
        "old_config": old_config,
        "preflight": preflight,
        "request": request,
        "go": go,
        "summary": summary,
        "failed": failed,
        "source_acceptance": source_acceptance,
        "witness": witness,
        "legacy_summary": legacy_summary,
        "legacy_witness": legacy_witness,
        "legacy_failed": legacy_failed,
    }


def _reported_reuse_fixture(
    tmp_path,
    monkeypatch,
    prior_recovery_checkout,
    canonical_checkout,
):
    config, prior = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    failed = prior["failed"]
    source_stage = failed / ".panels.partial-reported"
    (source_stage / ".chunks").mkdir(parents=True)
    _write(source_stage / "history_manifest.json", {"reported": True})
    for index in range(36):
        path = source_stage / f"table-{index // 3:02d}" / f"part-{index:02d}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"reported-{index}\n".encode())
    clean_stage = tmp_path / "clean-reported-stage"
    shutil.copytree(source_stage, clean_stage, ignore=shutil.ignore_patterns(".chunks"))
    copied_files = [
        {
            "path": str(path.relative_to(clean_stage)),
            "sha256": runner._sha256(path),
        }
        for path in sorted(clean_stage.rglob("*"))
        if path.is_file()
    ]
    operational_root = failed / "original-operational"
    operational_roots = {}
    for name in ("t1", "t2", "t3", "t4"):
        root = operational_root / name / operational_root.name
        manifest = _write(root / "layer2_run_manifest.json", {"stage": name})
        operational_roots[name] = {
            "path": str(root),
            "manifest_sha256": runner._sha256(manifest),
        }
    protected = _write(tmp_path / "protected-inventory.json", {"status": "UNCHANGED"})
    source_log = tmp_path / "source-execution.log"
    source_log.write_text("synthetic source execution\n", encoding="utf-8")
    stage_pin = {
        "root": str(source_stage),
        "manifest_sha256": runner._sha256(source_stage / "history_manifest.json"),
    }
    clean_pin = {
        "root": str(clean_stage),
        "manifest_sha256": runner._sha256(clean_stage / "history_manifest.json"),
    }
    copy_report = _write(
        tmp_path / "copy-report.json",
        {
            "schema_version": "independent-reported-stage-clean-copy-v1",
            "status": "PASS_DECLARED_FILES_CLEAN_COPY_ONLY",
            "fixture_kind": "SYNTHETIC_TEST",
            "history_ready": False,
            "source_generation_sha": runner.REPORTED_GENERATION_SOURCE_SHA,
            "recovery_source_sha": runner.REPORTED_RECOVERY_SOURCE_SHA,
            "original_failed_output_root": str(failed),
            "original_operational_root": str(operational_root),
            "source_stage": stage_pin,
            "clean_stage": clean_pin,
            "copied_file_count": 37,
            "copied_files": copied_files,
            "original_before_after_equal": True,
            "strictly_empty_chunks": True,
            "protected_inventory": {
                "path": str(protected),
                "sha256": runner._sha256(protected),
            },
        },
    )
    copy_pin = {"path": str(copy_report), "sha256": runner._sha256(copy_report)}
    plan = runner._target_paths(config)["plan"]
    intake = runner._target_paths(config)["intake"]
    plan_pin = {"path": str(plan), "sha256": runner._sha256(plan)}
    intake_pin = {"path": str(intake), "sha256": runner._sha256(intake)}
    log_pin = {"path": str(source_log), "sha256": runner._sha256(source_log)}
    component = _write(
        tmp_path / "component-report.json",
        {
            "schema_version": "independent-staged-reported-component-audit-v1",
            "verdict": "PASS_STAGED_REPORTED_COMPONENT_ONLY",
            "fixture_kind": "SYNTHETIC_TEST",
            "verification_level": "FULL_STAGED_REPORTED_PASS",
            "history_ready": False,
            "source_generation_sha": runner.REPORTED_GENERATION_SOURCE_SHA,
            "recovery_source_sha": runner.REPORTED_RECOVERY_SOURCE_SHA,
            "original_stage": stage_pin,
            "copy_report": copy_pin,
            "original_operational_root": str(operational_root),
            "operational_roots": operational_roots,
            "stage_manifest": {
                "path": str(clean_stage / "history_manifest.json"),
                "sha256": clean_pin["manifest_sha256"],
            },
            "source_intake": intake_pin,
            "plan": plan_pin,
            "source_execution_log": log_pin,
            "input_fingerprint": "synthetic-fingerprint",
        },
    )
    component_pin = {"path": str(component), "sha256": runner._sha256(component)}
    proof = _write(
        tmp_path / "root-attestation.json",
        {
            "version": "reported-stage-recovery-v1",
            "status": "PASS",
            "generation_source_identity": runner.REPORTED_GENERATION_SOURCE_SHA,
            "recovery_source_identity": runner.REPORTED_RECOVERY_SOURCE_SHA,
            "staged_manifest_sha256": clean_pin["manifest_sha256"],
            "intake_sha256": intake_pin["sha256"],
            "plan": json.loads(plan.read_text()),
            "verification_report": component_pin,
            "source_execution_log": log_pin,
            "operational_manifest_sha256": {
                name: value["manifest_sha256"] for name, value in operational_roots.items()
            },
            "input_fingerprint": "synthetic-fingerprint",
        },
    )
    config["engine"]["head"] = runner.REPORTED_RECOVERY_SOURCE_SHA
    config["reported_reuse"] = {
        "schema_version": runner.REPORTED_REUSE_VERSION,
        "mode": "ATTESTED_REPORTED_STAGE",
        "universe_id": config["collection"]["universe_id"],
        "cik": config["target"]["cik"],
        "generation_source_head": runner.REPORTED_GENERATION_SOURCE_SHA,
        "recovery_source_head": runner.REPORTED_RECOVERY_SOURCE_SHA,
        "original_failed_output_root": str(failed),
        "original_operational_root": str(operational_root),
        "operational_roots": operational_roots,
        "source_stage": stage_pin,
        "clean_stage": clean_pin,
        "copy_report": copy_pin,
        "component_report": component_pin,
        "root_attestation": {"path": str(proof), "sha256": runner._sha256(proof)},
        "source_execution_log": log_pin,
        "intake": intake_pin,
        "plan": plan_pin,
    }
    return config, prior, {
        "clean_stage": clean_stage,
        "copy_report": copy_report,
        "component": component,
        "proof": proof,
        "source_log": source_log,
    }


def test_attested_reported_reuse_binds_exact_r1_witness_and_component(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, _, _ = _reported_reuse_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    config = runner._validate_shape(config)
    collection = runner._validate_collection_target(config)
    reuse = runner._validate_reported_reuse(config, collection)
    assert reuse is not None
    assert reuse["original_failed_output_root"] == next(
        row["output_root"]
        for row in collection["target"]["prior_failed_attempts"]
        if row.get("runner_head") == runner.PRIOR_RECOVERY_SOURCE_SHA
    )
    assert reuse["clean_stage"]["manifest_sha256"] == reuse["source_stage"][
        "manifest_sha256"
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_attestation",
        "changed_file",
        "foreign_root",
        "incomplete_copy",
        "component",
        "source_execution",
        "plan",
        "cik",
        "universe",
        "omitted_field",
    ],
)
def test_attested_reported_reuse_rejects_foreign_incomplete_or_omitted_binding(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout, mutation
):
    config, prior, evidence = _reported_reuse_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    reuse = config["reported_reuse"]
    if mutation == "foreign_attestation":
        proof = json.loads(evidence["proof"].read_text())
        proof["generation_source_identity"] = "f" * 40
        _write(evidence["proof"], proof)
        reuse["root_attestation"]["sha256"] = runner._sha256(evidence["proof"])
    elif mutation == "changed_file":
        next(evidence["clean_stage"].glob("**/*.parquet")).write_bytes(b"changed\n")
    elif mutation == "foreign_root":
        reuse["original_failed_output_root"] = str(prior["legacy_failed"])
    elif mutation == "incomplete_copy":
        report = json.loads(evidence["copy_report"].read_text())
        report["copied_files"].pop()
        report["copied_file_count"] = 36
        _write(evidence["copy_report"], report)
        reuse["copy_report"]["sha256"] = runner._sha256(evidence["copy_report"])
    elif mutation == "component":
        report = json.loads(evidence["component"].read_text())
        report["history_ready"] = True
        _write(evidence["component"], report)
        reuse["component_report"]["sha256"] = runner._sha256(evidence["component"])
    elif mutation == "source_execution":
        foreign = tmp_path / "foreign-source.log"
        foreign.write_text("foreign\n", encoding="utf-8")
        reuse["source_execution_log"] = {
            "path": str(foreign),
            "sha256": runner._sha256(foreign),
        }
    elif mutation == "plan":
        foreign = _write(tmp_path / "foreign-plan.json", {"companies": []})
        reuse["plan"] = {"path": str(foreign), "sha256": runner._sha256(foreign)}
    elif mutation == "cik":
        reuse["cik"] = "9999999999"
    elif mutation == "universe":
        reuse["universe_id"] = "foreign-universe"
    else:
        reuse.pop("copy_report")
    with pytest.raises((KeyError, TypeError, ValueError)):
        shaped = runner._validate_shape(config)
        collection = runner._validate_collection_target(shaped)
        runner._validate_reported_reuse(shaped, collection)


def test_accepted_a02_recovery_timeout_binds_exact_second_abandoned_root(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, fixture = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    binding = runner._validate_collection_target(runner._validate_shape(config))
    assert binding["target"]["state"] == "RAW_COMPLETE"
    assert binding["target"]["abandoned_output_roots"] == config["target"][
        "abandoned_output_roots"
    ]
    assert len(binding["target"]["prior_failed_attempts"]) == 2
    recovery = next(
        row for row in binding["target"]["prior_failed_attempts"] if "recovery_ops" in row
    )
    legacy = next(
        row for row in binding["target"]["prior_failed_attempts"] if "legacy_ops" in row
    )
    assert recovery["runner_head"] == runner.PRIOR_RECOVERY_SOURCE_SHA
    assert recovery["output_root"] == str(fixture["failed"])
    assert recovery["execution_root"] == fixture["old"]["execution_root"]
    assert legacy["output_root"] == str(fixture["legacy_failed"])


def test_post_r1_jnj_rejects_recovery_timeout_and_root_omitted_together(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, _ = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    removed_attempt = config["target"]["approved_prior_failed_attempts"].pop()
    removed_root = config["target"]["abandoned_output_roots"].pop()
    assert "recovery_ops" in removed_attempt
    assert removed_root.endswith("JNJ-history-recovery-accepted-prior-r1")
    with pytest.raises(ValueError, match="exactly one accepted a02 r1"):
        runner._validate_collection_target(runner._validate_shape(config))


def test_post_r1_jnj_rejects_duplicate_recovery_timeout_witness(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, _ = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    config["target"]["approved_prior_failed_attempts"].append(
        json.loads(json.dumps(config["target"]["approved_prior_failed_attempts"][-1]))
    )
    with pytest.raises(ValueError, match="exactly one accepted a02 r1"):
        runner._validate_shape(config)


def test_post_r1_jnj_rejects_all_failure_declarations_and_roots_omitted(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, fixture = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    config["target"]["approved_prior_failed_attempts"] = []
    config["target"]["abandoned_output_roots"] = []
    assert fixture["legacy_summary"].is_file()
    assert fixture["summary"].is_file()
    with pytest.raises(ValueError, match="unapproved prior legacy OPS attempt"):
        runner._validate_collection_target(runner._validate_shape(config))


@pytest.mark.parametrize(
    "mutation",
    [
        "summary_hash",
        "summary_status",
        "summary_returncode",
        "summary_command",
        "config_collection",
        "config_cik",
        "config_filing_count",
        "config_cutoff",
        "config_plan",
        "config_resources",
        "preflight",
        "request",
        "go",
        "program",
        "source_acceptance",
        "foreign_witness",
        "foreign_target",
        "omitted_failure",
        "omitted_root",
        "wrong_root",
        "overlap",
        "missing_log",
        "unpinned_summary",
    ],
)
def test_prior_recovery_timeout_rejects_mutated_unpinned_or_overlapping_witness(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout, mutation
):
    config, fixture = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    declaration = config["target"]["approved_prior_failed_attempts"][-1]
    witness = declaration["recovery_ops"]
    if mutation.startswith("summary_"):
        payload = json.loads(fixture["summary"].read_text())
        if mutation == "summary_hash":
            payload["elapsed_seconds"] += 1
        elif mutation == "summary_status":
            payload["status"] = "PASS"
        elif mutation == "summary_returncode":
            payload["returncode"] = 0
        else:
            payload["command"][2] = "build-history"
        _write(fixture["summary"], payload)
        if mutation != "summary_hash":
            declaration["sha256"] = runner._sha256(fixture["summary"])
    elif mutation.startswith("config_"):
        payload = json.loads(fixture["old_config"].read_text())
        if mutation == "config_collection":
            payload["collection"]["universe_id"] = "foreign-universe"
        elif mutation == "config_cik":
            payload["target"]["cik"] = "9999999999"
        elif mutation == "config_filing_count":
            payload["target"]["selected_filings"] -= 1
        elif mutation == "config_cutoff":
            payload["financial_as_of"] = "2026-10-11"
        elif mutation == "config_plan":
            payload["target"]["plan_sha256"] = "0" * 64
        else:
            payload["limits"]["timeout_seconds"] -= 1
        _write(fixture["old_config"], payload)
        witness["config"]["sha256"] = runner._sha256(fixture["old_config"])
    elif mutation in {"preflight", "request", "go"}:
        path = fixture[mutation]
        payload = json.loads(path.read_text())
        payload["status"] = "CHANGED"
        _write(path, payload)
        witness[mutation]["sha256"] = runner._sha256(path)
    elif mutation == "program":
        foreign = tmp_path / "foreign-recovery-program.py"
        shutil.copy2(witness["program"]["path"], foreign)
        witness["program"] = {"path": str(foreign), "sha256": runner._sha256(foreign)}
    elif mutation == "source_acceptance":
        payload = json.loads(fixture["source_acceptance"].read_text())
        payload["status"] = "REVOKED"
        _write(fixture["source_acceptance"], payload)
        witness["source_acceptance"]["sha256"] = runner._sha256(
            fixture["source_acceptance"]
        )
    elif mutation == "foreign_witness":
        declaration["path"] = str(fixture["legacy_summary"])
        declaration["sha256"] = runner._sha256(fixture["legacy_summary"])
    elif mutation == "foreign_target":
        config["target"]["cik"] = "9999999999"
    elif mutation == "omitted_failure":
        config["target"]["approved_prior_failed_attempts"].pop()
    elif mutation == "omitted_root":
        config["target"]["abandoned_output_roots"].pop()
    elif mutation == "wrong_root":
        wrong = tmp_path / "wrong-abandoned-root"
        wrong.mkdir()
        config["target"]["abandoned_output_roots"][-1] = str(wrong)
    elif mutation == "overlap":
        config["execution_root"] = str(Path(fixture["old"]["execution_root"]) / "retry")
    elif mutation == "missing_log":
        fixture["summary"].with_suffix(".log").unlink()
    else:
        _write(fixture["summary"].with_name("execution.summary.unpinned.json"), {"status": "TIMEOUT"})
    with pytest.raises((ValueError, TypeError)):
        runner._validate_collection_target(runner._validate_shape(config))


def test_legacy56a_summary_without_output_root_binds_exact_abandoned_tree(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
):
    config, fixture = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    summary = fixture["legacy_summary"]
    failed = fixture["legacy_failed"]
    assert "output_root" not in json.loads(summary.read_text())
    binding = runner._validate_collection_target(runner._validate_shape(config))
    legacy = next(
        row for row in binding["target"]["prior_failed_attempts"] if "legacy_ops" in row
    )
    assert legacy["output_root"] == str(failed)
    assert (
        binding["target"]["state"] == "RAW_COMPLETE"
    )  # old OPS never wrote a native build attempt


@pytest.mark.parametrize(
    "mutation",
    [
        "unbound",
        "wrong_root",
        "inside_root",
        "command",
        "config",
        "go",
        "preflight",
        "orphan_summary",
        "program",
    ],
)
def test_legacy_failure_rejects_unbound_changed_or_overlapping_attempt(
    tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout, mutation
):
    config, fixture = _prior_recovery_fixture(
        tmp_path, monkeypatch, prior_recovery_checkout, canonical_checkout
    )
    summary = fixture["legacy_summary"]
    witness = fixture["legacy_witness"]
    failed = fixture["legacy_failed"]
    if mutation == "unbound":
        config["target"]["approved_prior_failed_attempts"].pop(0)
        config["target"]["abandoned_output_roots"].pop(0)
    elif mutation == "wrong_root":
        config["target"]["abandoned_output_roots"] = [str(tmp_path)]
    elif mutation == "inside_root":
        child = failed / "fresh"
        child.mkdir()
        config["target"]["history_parent"] = str(child)
    elif mutation == "command":
        value = json.loads(summary.read_text())
        value["command"][6] = "HD"
        _write(summary, value)
        config["target"]["approved_prior_failed_attempts"][0]["sha256"] = runner._sha256(summary)
    elif mutation in {"config", "go", "program"}:
        foreign = _write(tmp_path / "foreign.json", {})
        witness[mutation] = {"path": str(foreign), "sha256": runner._sha256(foreign)}
    elif mutation == "preflight":
        _write(Path(config["collection"]["manifest"]).parent / "ops_preflight.json", {})
    else:
        _write(summary.parent / "orphan.summary.json", {"status": "RSS_LIMIT"})
    with pytest.raises(ValueError):
        runner._validate_collection_target(runner._validate_shape(config))


@pytest.mark.parametrize("stop", ["timeout", "interrupt", "rss"])
def test_real_validator_child_owned_cleanup(tmp_path, monkeypatch, stop):
    import time

    pid_file = tmp_path / "validator.pid"
    script = f"\nfrom pathlib import Path\nimport os, time\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n"
    supervise = runner.resource_ops.supervise_owned_process
    owned = []

    def monitor(process, samples, **kwargs):
        owned.append(process)
        end = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert pid_file.exists()
        if stop == "interrupt":
            raise KeyboardInterrupt
        if stop == "rss":
            kwargs["rss_reader"] = lambda _: runner.LIMIT_KIB + 1
        return supervise(process, samples, **kwargs)

    monkeypatch.setattr(runner.resource_ops, "supervise_owned_process", monitor)
    with pytest.raises(KeyboardInterrupt if stop == "interrupt" else ValueError):
        runner._run_canonical_validator(script, [], tmp_path, timeout_seconds=0.05)
    assert len(owned) == 1
    assert owned[0].poll() is not None
    assert not Path(f"/proc/{owned[0].pid}").exists()


def test_real_validator_child_dies_after_abrupt_parent_exit(tmp_path):
    import signal
    import time

    pid_file = tmp_path / "validator.pid"
    child = f"\nfrom pathlib import Path\nimport os, time\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n"
    parent_script = (
        "from pathlib import Path\nfrom tools import universe50_history_recovery_ops as r\n"
        f"r._run_canonical_validator({child!r}, [], Path({str(tmp_path)!r}))\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", parent_script])
    pid = None
    try:
        end = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < end:
            time.sleep(0.02)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        parent.kill()
        parent.wait(timeout=5)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            stat = Path(f"/proc/{pid}/stat")
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("canonical validator survived parent death")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if (
            pid
            and Path(f"/proc/{pid}/stat").exists()
            and Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
        ):
            os.kill(pid, signal.SIGKILL)
