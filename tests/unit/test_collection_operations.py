from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sec_xbrl import collection_operations as operations
from sec_xbrl.filing.trailing_corpus import TrailingCorpusError


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _config(path: Path, *tickers: str, as_of: str = "2026-10-08") -> Path:
    return _write(
        path,
        {
            "schema_version": 1,
            "universe_id": "unit-cohort",
            "purpose": "network-free collection operations tests",
            "as_of_date": as_of,
            "source_observed_at": "2026-10-08T01:02:03+00:00",
            "collection": {
                "completed_fiscal_years": 4,
                "analytical_fiscal_years": 3,
                "include_subsequent_quarters": True,
            },
            "companies": [
                {"ticker": ticker, "cik": str(index + 1), "groups": ["test"]}
                for index, ticker in enumerate(tickers)
            ],
        },
    )


def _filing(cik: str, accession: str, form: str, filed: str, report: str) -> dict[str, object]:
    return {
        "cik": cik,
        "accession": accession,
        "form": form,
        "filed_date": filed,
        "report_date": report,
        "primary_document": None,
        "is_xbrl": True,
        "is_inline_xbrl": True,
        "source": "unit",
    }


def _full_plan(path: Path, ticker: str, cik: str, *, as_of: str = "2026-10-08") -> Path:
    filings = [
        _filing(cik, f"{cik}-2{year}-000001", "10-K", f"20{year}-02-01", f"20{year - 1}-12-31")
        for year in range(23, 27)
    ]
    filings.append(_filing(cik, f"{cik}-26-000002", "10-Q", "2026-05-01", "2026-03-31"))
    return _write(
        path,
        {
            "version": "company-history-v1",
            "as_of_date": as_of,
            "report_start": None,
            "report_end": None,
            "recent_fiscal_years": 4,
            "companies": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "name": f"{ticker} Inc.",
                    "submissions": [],
                    "filings": filings,
                }
            ],
        },
    )


def _short_plan(path: Path, ticker: str, cik: str) -> Path:
    filings = [
        _filing(cik, f"{cik}-25-000001", "10-K", "2025-03-01", "2024-12-31"),
        _filing(cik, f"{cik}-26-000001", "10-K", "2026-03-01", "2025-12-31"),
        _filing(cik, f"{cik}-26-000002", "10-Q", "2026-05-01", "2026-03-31"),
    ]
    return _write(
        path,
        {
            "version": "company-history-v1",
            "as_of_date": "2026-10-08",
            "report_start": "2024-12-31",
            "report_end": "2026-03-31",
            "recent_fiscal_years": None,
            "companies": [
                {
                    "ticker": ticker,
                    "cik": cik,
                    "name": f"{ticker} Newco",
                    "submissions": [],
                    "filings": filings,
                }
            ],
        },
    )


def test_pilot_configuration_is_external_and_has_approved_scope() -> None:
    root = Path(__file__).parents[2]
    config = operations.load_universe_config(root / "examples/universe/pilot_companies.json")
    assert len(config.companies) == 21
    assert config.as_of_date == date(2026, 10, 8)
    assert config.completed_fiscal_years == 4
    assert config.analytical_fiscal_years == 3
    assert {company.ticker for company in config.companies} >= {"AMD", "NVDA", "AVGO", "KO"}


@pytest.mark.parametrize("ticker", ("../escape", "AAA/BBB", "AAA\\BBB", ".", "..", "A B"))
def test_unsafe_ticker_is_rejected_before_filesystem_writes(tmp_path: Path, ticker: str) -> None:
    config = _config(tmp_path / "config.json", ticker)
    run_root = tmp_path / "run"
    with pytest.raises(ValueError, match="unsafe company ticker"):
        operations.prepare_universe(config_path=config, run_root=run_root)
    assert not run_root.exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("ticker", ("BRK.B", "BF-B"))
def test_safe_punctuation_in_ticker_is_supported(tmp_path: Path, ticker: str) -> None:
    config = operations.load_universe_config(_config(tmp_path / "config.json", ticker))
    assert config.companies[0].ticker == ticker


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("completed_fiscal_years", "4", TypeError),
        ("completed_fiscal_years", True, TypeError),
        ("analytical_fiscal_years", 3.0, TypeError),
        ("include_subsequent_quarters", 1, ValueError),
    ),
)
def test_collection_window_types_are_strict(
    tmp_path: Path, field: str, value: object, error: type[Exception]
) -> None:
    path = _config(tmp_path / "config.json", "AAA")
    payload = json.loads(path.read_text())
    payload["collection"][field] = value
    _write(path, payload)
    with pytest.raises(error):
        operations.load_universe_config(path)


def test_existing_plan_is_reused_without_discovery_and_plan_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.json", "AAA")
    plan = _full_plan(tmp_path / "external" / "plan.json", "AAA", "0000000001")
    monkeypatch.setattr(
        operations.history,
        "discover_history",
        lambda **kwargs: pytest.fail("existing plan must avoid discovery"),
    )
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "run",
        existing_plans={"AAA": plan},
    )
    status = operations.read_universe_status(manifest_path=manifest)
    assert status.prepared_companies == 1
    assert status.companies[0].source_stage == "REUSED"
    assert status.companies[0].held_filings == 5

    local_plan = tmp_path / "run/companies/AAA/plan.json"
    changed = json.loads(local_plan.read_text())
    changed["companies"][0]["filings"][0]["accession"] = "changed"
    _write(local_plan, changed)
    operations.prepare_universe(config_path=config, run_root=tmp_path / "run")
    failed = operations.read_universe_status(manifest_path=manifest).companies[0]
    assert failed.state == "PREPARE_FAILED"
    assert "immutable history plan changed" in str(failed.error)


def test_collection_request_refuses_changed_as_of_under_same_identity(tmp_path: Path) -> None:
    plan = _full_plan(tmp_path / "plan.json", "AAA", "0000000001")
    run = tmp_path / "run"
    operations.prepare_universe(
        config_path=_config(tmp_path / "first.json", "AAA"),
        run_root=run,
        existing_plans={"AAA": plan},
    )
    with pytest.raises(ValueError, match="collection request already exists with different scope"):
        operations.prepare_universe(
            config_path=_config(tmp_path / "changed.json", "AAA", as_of="2026-10-07"),
            run_root=run,
        )


def test_short_history_uses_explicit_actual_report_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.json", "NEW")
    calls: list[dict[str, object]] = []

    def discover(**kwargs: object) -> Path:
        calls.append(kwargs)
        if kwargs.get("recent_fiscal_years") == 4:
            raise TrailingCorpusError("only two annual baselines")
        return _short_plan(Path(kwargs["workspace"]) / "plan.json", "NEW", "0000000001")

    monkeypatch.setattr(operations.history, "discover_history", discover)
    monkeypatch.setattr(
        operations,
        "_available_report_window",
        lambda *args, **kwargs: (date(2024, 12, 31), date(2026, 3, 31)),
    )
    manifest = operations.prepare_universe(config_path=config, run_root=tmp_path / "run")
    row = operations.read_universe_status(manifest_path=manifest).companies[0]
    assert row.capability == "AVAILABLE_PERIODS_ONLY"
    assert row.report_start == "2024-12-31"
    assert row.report_end == "2026-03-31"
    assert calls[1]["offline"] is True
    assert calls[1]["report_start"] == date(2024, 12, 31)


def test_collect_isolates_failures_retries_and_reconciles_reuse_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.json", "AAA", "BBB")
    plans = {
        "AAA": _full_plan(tmp_path / "plans/AAA.json", "AAA", "0000000001"),
        "BBB": _full_plan(tmp_path / "plans/BBB.json", "BBB", "0000000002"),
    }
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "run",
        existing_plans=plans,
    )
    calls: list[str] = []
    received_source_runs: dict[str, tuple[Path, ...]] = {}
    retry = False

    def ingest(**kwargs: object) -> Path:
        ticker = Path(kwargs["plan_path"]).parent.name
        calls.append(ticker)
        received_source_runs[ticker] = tuple(kwargs["source_runs"])
        plan = json.loads(Path(kwargs["plan_path"]).read_text())
        outcomes = []
        for index, filing in enumerate(plan["companies"][0]["filings"]):
            failed = ticker == "BBB" and index == 0 and not retry
            outcomes.append(
                {
                    "ticker": ticker,
                    "filing": filing,
                    "status": "FAILED" if failed else ("REUSED" if ticker == "AAA" else "INGESTED"),
                    **({"error": "unit failure"} if failed else {}),
                }
            )
        result = Path(kwargs["output_run"]) / "history_intake.json"
        _write(
            result,
            {
                "plan": plan,
                "filings": outcomes,
                "complete": all(row["status"] != "FAILED" for row in outcomes),
            },
        )
        return result

    monkeypatch.setattr(operations.history, "ingest_history", ingest)
    operations.collect_universe(
        manifest_path=manifest,
        package_cache=tmp_path / "packages",
        index_cache=tmp_path / "indexes",
        taxonomy_cache=tmp_path / "taxonomy",
        source_runs={"AAA": (tmp_path / "prior-aaa",)},
    )
    first = operations.read_universe_status(manifest_path=manifest)
    assert calls == ["AAA", "BBB"]
    assert received_source_runs["AAA"] == (tmp_path / "prior-aaa",)
    assert first.raw_complete_companies == 1
    assert first.failed_companies == 1
    assert first.reused_filings == 5
    assert first.succeeded_filings == 9
    assert first.failed_filings == 1

    retry = True
    operations.collect_universe(
        manifest_path=manifest,
        package_cache=tmp_path / "packages",
        index_cache=tmp_path / "indexes",
        taxonomy_cache=tmp_path / "taxonomy",
    )
    second = operations.read_universe_status(manifest_path=manifest)
    assert second.raw_complete_companies == 2
    assert second.failed_companies == 0
    assert len(list((tmp_path / "run/companies/BBB/operation_attempts").glob("collect-*.json"))) == 2


def test_status_is_offline_and_outputs_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.json", "AAA")
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "run",
        existing_plans={"AAA": _full_plan(tmp_path / "plan.json", "AAA", "0000000001")},
    )
    monkeypatch.setattr(
        operations.history,
        "discover_history",
        lambda **kwargs: pytest.fail("status must not discover"),
    )
    monkeypatch.setattr(
        operations.history,
        "ingest_history",
        lambda **kwargs: pytest.fail("status must not ingest"),
    )
    monkeypatch.setattr(
        operations.history,
        "build_history",
        lambda **kwargs: pytest.fail("status must not build"),
    )
    paths = operations.write_status_outputs(manifest_path=manifest, output_root=tmp_path / "out")
    before = [path.read_bytes() for path in paths]
    operations.write_status_outputs(manifest_path=manifest, output_root=tmp_path / "out")
    assert [path.read_bytes() for path in paths] == before


def test_status_rejects_mismatched_preexisting_intake(tmp_path: Path) -> None:
    config = _config(tmp_path / "config.json", "AAA")
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "run",
        existing_plans={"AAA": _full_plan(tmp_path / "plan.json", "AAA", "0000000001")},
    )
    plan = json.loads((tmp_path / "run/companies/AAA/plan.json").read_text())
    wrong = json.loads(json.dumps(plan))
    wrong["companies"][0]["filings"][0]["accession"] = "different-accession"
    _write(
        tmp_path / "run/companies/AAA/intake/history_intake.json",
        {
            "plan": wrong,
            "complete": True,
            "filings": [
                {"filing": row, "status": "REUSED"}
                for row in wrong["companies"][0]["filings"]
            ],
        },
    )
    row = operations.read_universe_status(manifest_path=manifest).companies[0]
    assert row.state == "RAW_FAILED"
    assert row.action == "RETRY"
    assert "differs from immutable company plan" in str(row.error)


def test_raw_complete_is_distinct_from_ready_and_build_failures_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.json", "AAA", "BBB")
    manifest = operations.prepare_universe(
        config_path=config,
        run_root=tmp_path / "run",
        existing_plans={
            "AAA": _full_plan(tmp_path / "AAA.json", "AAA", "0000000001"),
            "BBB": _full_plan(tmp_path / "BBB.json", "BBB", "0000000002"),
        },
    )

    def ingest(**kwargs: object) -> Path:
        plan = json.loads(Path(kwargs["plan_path"]).read_text())
        ticker = plan["companies"][0]["ticker"]
        result = Path(kwargs["output_run"]) / "history_intake.json"
        _write(
            result,
            {
                "plan": plan,
                "complete": True,
                "filings": [
                    {"ticker": ticker, "filing": filing, "status": "REUSED"}
                    for filing in plan["companies"][0]["filings"]
                ],
            },
        )
        return result

    monkeypatch.setattr(operations.history, "ingest_history", ingest)
    operations.collect_universe(
        manifest_path=manifest,
        package_cache=tmp_path / "packages",
        index_cache=tmp_path / "indexes",
        taxonomy_cache=tmp_path / "taxonomy",
    )
    raw = operations.read_universe_status(manifest_path=manifest)
    assert raw.raw_complete_companies == 2
    assert raw.ready_companies == 0
    assert {row.action for row in raw.companies} == {"BUILD_OPTIONAL"}

    def build(**kwargs: object) -> Path:
        ticker = Path(kwargs["output_root"]).name
        if ticker == "BBB":
            raise ValueError("publication rejected")
        publication = Path(kwargs["output_root"]) / "panels"
        publication.mkdir(parents=True)
        return publication

    monkeypatch.setattr(operations.history, "build_history", build)
    operations.build_universe(
        manifest_path=manifest,
        output_root=tmp_path / "publications",
    )
    built = operations.read_universe_status(manifest_path=manifest)
    assert built.ready_companies == 1
    assert built.failed_companies == 1
    assert {row.ticker: row.state for row in built.companies} == {
        "AAA": "READY",
        "BBB": "BUILD_FAILED",
    }


def test_existing_plan_rejects_cik_asof_and_coverage_mismatch(tmp_path: Path) -> None:
    config = operations.load_universe_config(_config(tmp_path / "config.json", "AAA"))
    target = config.companies[0]
    wrong_cik = json.loads(_full_plan(tmp_path / "wrong-cik.json", "AAA", "0000000002").read_text())
    with pytest.raises(ValueError, match="CIK differs"):
        operations._validate_plan(wrong_cik, target, config)
    wrong_asof = json.loads(
        _full_plan(tmp_path / "wrong-asof.json", "AAA", "0000000001", as_of="2026-10-07").read_text()
    )
    with pytest.raises(ValueError, match="as-of differs"):
        operations._validate_plan(wrong_asof, target, config)
    wrong_coverage = json.loads(_short_plan(tmp_path / "short.json", "AAA", "0000000001").read_text())
    wrong_coverage["report_start"] = None
    with pytest.raises(ValueError, match="explicit short-history"):
        operations._validate_plan(wrong_coverage, target, config)
