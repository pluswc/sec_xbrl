"""Prospective exact-cutoff selection over complete unchanged synthetic inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sec_xbrl import analysis, history, metric_quality
from sec_xbrl import collection_operations as operations
from sec_xbrl.prospective_selection import (
    analysis_selection_policy,
    prepare_reselected_analysis,
    prospective_policy_sources,
    prospective_raw_inventory,
    prospective_rule_versions,
    publish_prospective_selection,
    resolve_prospective_selection,
    verify_reselected_analysis,
)
from sec_xbrl.screening import metric_identity
from sec_xbrl.screening.common import sha256_file, write_json
from tests.screening import test_generic_metric_identity_integration as fixtures

CURRENT = "2026-10-25"


def _pin(path):
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def _fixture(tmp_path, monkeypatch, *, extra_filing=None):
    # Construct canonical SEC-provider FilingRef fixtures before the tested
    # immutable publications exist; the Raw tables themselves remain unchanged.
    original_fixture = fixtures._fixture

    def sec_fixture(*args, **kwargs):
        paths = original_fixture(*args, **kwargs)
        collection = Path(paths["collection"])
        parent = json.loads(collection.read_text())
        plan_path = Path(parent["companies"][0]["plan_path"])
        plan = json.loads(plan_path.read_text())
        for filing in plan["companies"][0]["filings"]:
            filing["source"] = "sec_submissions"
        write_json(plan_path, plan)
        intake_path = Path(paths["intake"])
        intake = json.loads(intake_path.read_text())
        for filing in intake["plan"]["companies"][0]["filings"]:
            filing["source"] = "sec_submissions"
        for outcome in intake["filings"]:
            outcome["filing"]["source"] = "sec_submissions"
        write_json(intake_path, intake)
        import polars as pl

        from sec_xbrl.longitudinal.corpus_release import RAW_TABLES

        for name in RAW_TABLES:
            table = Path(paths["snapshot"]) / f"{name}.parquet"
            if not table.exists():
                pl.DataFrame().write_parquet(table)
        return paths

    with monkeypatch.context() as context:
        context.setattr(fixtures, "_fixture", sec_fixture)
        prepared = fixtures._publish_identity_inputs(tmp_path, context)
    collection = Path(prepared.paths["collection"])
    plans = {}
    current_plans = {}
    summary_rows = []
    for row in json.loads(collection.read_text())["companies"]:
        ticker, cik = row["ticker"], row["cik"]
        plan = json.loads(Path(row["plan_path"]).read_text())
        filing = plan["companies"][0]["filings"][0]
        root = {
            "cik": int(cik),
            "tickers": [ticker],
            "filings": {
                "files": [],
                "recent": {
                    "accessionNumber": [filing["accession"]],
                    "filingDate": [filing["filed_date"]],
                    "reportDate": [filing["report_date"]],
                    "form": [filing["form"]],
                    "primaryDocument": [filing["primary_document"]],
                    "isXBRL": [1],
                    "isInlineXBRL": [1],
                },
            },
        }
        if extra_filing is not None and ticker == "FIVE":
            extra = {"accessionNumber":"0000000123-26-999999","filingDate":"2026-10-20",
                     "reportDate":"2025-12-31","form":extra_filing,"primaryDocument":"extra.htm",
                     "isXBRL":1,"isInlineXBRL":1}
            for key, value in extra.items():
                root["filings"]["recent"][key].append(value)
        source = tmp_path / f"discovery/{cik}/temporary.json"
        source.parent.mkdir(parents=True)
        write_json(source, root)
        snapshot = source.with_name(sha256_file(source) + ".json")
        source.rename(snapshot)
        plan["as_of_date"] = CURRENT
        plan["companies"][0]["submissions"] = [str(snapshot)]
        path = tmp_path / f"latest-plans/{ticker}.json"
        path.parent.mkdir(exist_ok=True)
        write_json(path, plan)
        plans[ticker] = path
        current_plans[ticker] = plan
        summary_rows.append(
            {"ticker": ticker, "cik": cik, "status": "FETCHED", "submissions": [str(snapshot)]}
        )
    config = json.loads((tmp_path / "mixed-config.json").read_text())
    config.update(as_of_date=CURRENT, source_observed_at="2026-10-25T00:00:00+00:00")
    latest_config = tmp_path / "latest-config.json"
    write_json(latest_config, config)
    latest = operations.prepare_universe(
        config_path=latest_config, run_root=tmp_path / "latest", existing_plans=plans
    )
    paths = {**prepared.paths, "collection": latest}
    fixtures._install_intake(paths, "FIVE")
    summary = tmp_path / "discovery-summary.json"
    write_json(summary, {"cutoff": CURRENT, "companies": summary_rows})
    origin_manifests = {
        mode: root / "analysis_manifest.json"
        for mode, root in (("ANNUAL", prepared.annual), ("QUARTERLY", prepared.quarterly))
    }
    for path in origin_manifests.values():
        value = json.loads(path.read_text())
        value["configuration"] = {}
        write_json(path, value)
    policy = tmp_path / "root-policy-compatibility.json"
    write_json(
        policy,
        {
            "schema_version": "prospective-policy-compatibility-v1",
            "status": "ROOT_APPROVED",
            "origin_analyses": {mode: _pin(path) for mode, path in origin_manifests.items()},
            "current_policy_source_sha256s": prospective_policy_sources(),
            "rules": prospective_rule_versions(),
            "current_collection": _pin(latest),
            "financial_as_of": CURRENT,
            "discovery_summary": _pin(summary),
            "raw_inventory": prospective_raw_inventory(latest, "FIVE", fixtures.COHORT[0]["cik"]),
            **{
                mode: analysis_selection_policy(json.loads(path.read_text()), "FIVE")
                for mode, path in origin_manifests.items()
            },
        },
    )
    from sec_xbrl.financial_storage_reuse import financial_storage_policy_sources

    build_path = collection.parent / "companies/FIVE/build_manifest.json"
    build = json.loads(build_path.read_text())
    root = prepared.histories["FIVE"].parent
    prior = tmp_path / "prior-native-storage.json"
    write_json(
        prior,
        {
            "version": 1,
            "full_storage_validation": True,
            "validation_level": "DETAILED",
            "publication_root": str(root),
            "manifest_sha256": sha256_file(prepared.histories["FIVE"]),
            "files": {name: {"sha256": digest} for name, digest in build["declared_files"].items()},
        },
    )
    acceptance = tmp_path / "origin-storage-acceptance.json"
    write_json(acceptance, {"accepted_by": "ROOT_LEAD", "fixture_kind": "SYNTHETIC"})
    storage = tmp_path / "origin-storage-reuse.json"
    write_json(
        storage,
        {
            "schema_version": "financial-history-storage-reuse-v1",
            "status": "ROOT_APPROVED",
            "collection_manifest": _pin(collection),
            "current_policy_source_sha256s": financial_storage_policy_sources(),
            "companies": [
                {
                    **fixtures.COHORT[0],
                    "histories": [
                        {
                            "acceptance": _pin(acceptance),
                            "previous_validation": _pin(prior),
                            "build_manifest": _pin(build_path),
                            "history_manifest": _pin(prepared.histories["FIVE"]),
                            "payload_inventory": {
                                str(path.relative_to(root)): sha256_file(path)
                                for path in root.rglob("*")
                                if path.is_file()
                            },
                        }
                    ],
                }
            ],
        },
    )
    prospective_config = tmp_path / "prospective-config.json"
    write_json(
        prospective_config,
        {
            "schema_version": "prospective-selection-config-v1",
            "current_collection": _pin(latest),
            "financial_as_of": CURRENT,
            "discovery_summary": _pin(summary),
            "storage_reuse": _pin(storage),
            "companies": [
                {
                    **fixtures.COHORT[0],
                    "origin_collection": _pin(collection),
                    "origin_history_manifest": _pin(prepared.histories["FIVE"]),
                    "origin_annual_analysis": _pin(origin_manifests["ANNUAL"]),
                    "origin_quarterly_analysis": _pin(origin_manifests["QUARTERLY"]),
                    "current_policy": _pin(policy),
                }
            ],
        },
    )
    return prepared, latest, prospective_config


def test_prospective_selection_new_event_preserves_raw_and_old_bundle(tmp_path, monkeypatch):
    prepared, latest, config = _fixture(tmp_path, monkeypatch)
    original = (prepared.annual / "analysis_manifest.json").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("History/analysis builder must not run")

    monkeypatch.setattr(history, "build_history", forbidden)
    monkeypatch.setattr(analysis, "prepare_analysis", forbidden)
    manifest = publish_prospective_selection(config_path=config, destination=tmp_path / "selection")
    selection = resolve_prospective_selection(
        _pin(manifest), collection_manifest=latest, scope_companies=list(fixtures.COHORT)
    )
    assert not any(key.startswith("CURRENT_SOURCE:") for key in selection.controls)
    assert selection.companies["FIVE"]["collection_status"] == "RAW_COMPLETE"
    assert selection.companies["FIVE"]["selection_status"] == "SELECTION_EQUIVALENT"
    for mode in ("ANNUAL", "QUARTERLY"):
        root = prepare_reselected_analysis(
            prospective_selection=_pin(manifest),
            ticker="FIVE",
            period_mode=mode,
            destination=tmp_path / f"reselected-{mode}",
        )
        verify_reselected_analysis(root, selection=selection, ticker="FIVE", period_mode=mode)
        current = analysis.AnalysisClient(root)
        origin = analysis.AnalysisClient(
            prepared.annual if mode == "ANNUAL" else prepared.quarterly
        )
        assert current.manifest["companies"]["FIVE"]["as_of"] == CURRENT
        assert current.manifest["publication_id"] != origin.manifest["publication_id"]
        old = origin._records("FIVE", "LATEST_REPORTED", "core_cells")[0]
        new = current._records("FIVE", "LATEST_REPORTED", "core_cells")[0]
        assert new["cell_id"] != old["cell_id"]
        assert new["origin_prepared_cell_id"] == old["cell_id"]
        for key in ("value", "unit", "start", "end", "source_fact_id"):
            assert new.get(key) == old.get(key)
        with pytest.raises(ValueError):
            origin._context("FIVE", "LATEST_REPORTED", as_of=CURRENT)
    assert (prepared.annual / "analysis_manifest.json").read_bytes() == original
    assert not (latest.parent / "companies/FIVE/build_manifest.json").exists()


@pytest.mark.parametrize(
    "defect",
    ["policy", "review", "raw", "amendment", "late_old_filing", "wrong_spine", "snapshot_omission"],
)
def test_prospective_selection_rejects_incomplete_or_changed_inputs(tmp_path, monkeypatch, defect):
    prepared, latest, path = _fixture(tmp_path, monkeypatch)
    config = json.loads(path.read_text())
    entry = config["companies"][0]
    if defect in {"policy", "review"}:
        policy_path = Path(entry["current_policy"]["path"])
        policy = json.loads(policy_path.read_text())
        if defect == "policy":
            policy["current_policy_source_sha256s"]["src/sec_xbrl/history.py"] = "0" * 64
        else:
            policy["ANNUAL"]["review_cutoff"] = "2026-10-25T00:00:00Z"
        write_json(policy_path, policy)
        entry["current_policy"] = _pin(policy_path)
    elif defect == "raw":
        source = prepared.paths["first"]["snapshot"]
        (Path(source) / "fact.parquet").write_bytes(b"changed")
    elif defect == "wrong_spine":
        config["financial_as_of"] = "2027-01-02"
    else:
        plan_path = latest.parent / "companies/FIVE/plan.json"
        plan = json.loads(plan_path.read_text())
        snapshot = Path(plan["companies"][0]["submissions"][0])
        payload = json.loads(snapshot.read_text())
        if defect == "snapshot_omission":
            summary_path = Path(config["discovery_summary"]["path"])
            summary = json.loads(summary_path.read_text())
            summary["companies"][0]["submissions"] = []
            write_json(summary_path, summary)
            config["discovery_summary"] = _pin(summary_path)
        else:
            recent = payload["filings"]["recent"]
            extra = {
                "accessionNumber": "0000000123-26-999999",
                "filingDate": "2026-10-20",
                "reportDate": "2025-12-31",
                "form": "10-K/A" if defect == "amendment" else "10-Q",
                "primaryDocument": "extra.htm",
                "isXBRL": 1,
                "isInlineXBRL": 1,
            }
            for key, value in extra.items():
                recent[key].append(value)
            write_json(snapshot, payload)  # content-addressed hash tamper itself must fail
    write_json(path, config)
    with pytest.raises((ValueError, OSError)):
        publish_prospective_selection(config_path=path, destination=tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_current_prospective_quality_identity_annual31_quarter41_and_v3(tmp_path, monkeypatch):
    prepared, latest, config_path = _fixture(tmp_path, monkeypatch)
    config = json.loads(config_path.read_text())

    def forbidden(*args, **kwargs):
        raise AssertionError("accepted History typed decoder/builder must not run")

    monkeypatch.setattr(history.HistoryPublicationReader, "verify_all", forbidden)
    monkeypatch.setattr(history, "build_history", forbidden)
    selection = publish_prospective_selection(
        config_path=config_path, destination=tmp_path / "current-selection"
    )
    roots = {
        mode: prepare_reselected_analysis(
            prospective_selection=_pin(selection),
            ticker="FIVE",
            period_mode=mode,
            destination=tmp_path / f"current-{mode}",
        )
        for mode in ("ANNUAL", "QUARTERLY")
    }
    quality_config = json.loads((tmp_path / "quality-config.json").read_text())
    quality_config.update(
        financial_as_of=CURRENT,
        prospective_selection=_pin(selection),
        storage_reuse=config["storage_reuse"],
    )
    quality_config["source_provenance"][0].update(
        plan_sha256=sha256_file(latest.parent / "companies/FIVE/plan.json"),
        intake_sha256=sha256_file(latest.parent / "companies/FIVE/intake/history_intake.json"),
    )
    quality_path = tmp_path / "current-quality-config.json"
    write_json(quality_path, quality_config)
    quality = metric_quality.prepare_generic_metric_quality(
        config_path=quality_path,
        collection_manifest=latest,
        package_root=Path(prepared.paths["packages"]),
        history_manifests=prepared.histories,
        source_index_destination=tmp_path / "current-indexes",
        source_binding_destination=tmp_path / "current-bindings",
        destination=tmp_path / "current-quality",
        producer_revision="d" * 40,
    )
    reader = metric_quality.GenericMetricQualityReader(quality.root)
    assert reader.manifest["collection_status"][0]["state"] == "RAW_COMPLETE"
    assert (
        reader.manifest["collection_status"][0]["build_evidence_kind"] == "ORIGIN_ACCEPTED_HISTORY"
    )
    identity_config = json.loads(prepared.identity_config.read_text())
    identity_config.update(
        financial_as_of=CURRENT,
        collection_manifest=str(latest),
        collection_manifest_sha256=sha256_file(latest),
        prospective_selection=_pin(selection),
        storage_reuse=config["storage_reuse"],
        quality_root=str(quality.root),
        quality_manifest_sha256=sha256_file(quality.manifest_path),
    )
    identity_config["companies"][0].update(
        annual_analysis_root=str(roots["ANNUAL"]),
        annual_analysis_manifest_sha256=sha256_file(roots["ANNUAL"] / "analysis_manifest.json"),
        quarterly_analysis_root=str(roots["QUARTERLY"]),
        quarterly_analysis_manifest_sha256=sha256_file(
            roots["QUARTERLY"] / "analysis_manifest.json"
        ),
    )
    # A mixed current/origin registry lookup must use the accepted origin proof
    # for this equivalent company, even when another proof covers current builds.
    from types import SimpleNamespace
    prospective = resolve_prospective_selection(_pin(selection), collection_manifest=latest,
                                                scope_companies=list(fixtures.COHORT))
    empty_current = SimpleNamespace(companies={})
    metric_identity._verify_company_sources(identity_config["companies"][0], CURRENT, latest,
                                           storage_reuse=empty_current, prospective=prospective)
    metric_quality._validate_histories(history_manifests=prepared.histories,
        expected_companies=(fixtures.COHORT[0],),
        provenance={(row["ticker"],row["cik"]):row for row in quality_config["source_provenance"]},
        financial_as_of=CURRENT, readiness=tuple(reader.manifest["collection_status"]),
        storage_reuse=empty_current, prospective=prospective)
    identity_path = tmp_path / "current-identity-config.json"
    write_json(identity_path, identity_config)
    from sec_xbrl import prospective_selection as producer
    resolver = producer._resolve_config
    resolutions = []
    def counted_resolution(*args, **kwargs):
        resolutions.append(True)
        return resolver(*args, **kwargs)
    monkeypatch.setattr(producer, "_resolve_config", counted_resolution)
    identity = metric_identity.publish_generic_metric_identity(
        identity_path, tmp_path / "current-identity"
    )
    assert len(resolutions) == 1
    identity_reader = metric_identity.GenericMetricIdentityReader(identity.root)
    assert len(resolutions) == 2
    assert identity_reader.manifest["financial_as_of"] == CURRENT
    assert identity_reader.manifest["collection"]["scope_ready_companies"] == 0
    assert identity_reader.manifest["collection"]["scope_selection_equivalent_companies"] == 1
    identity_source = {
        "kind": fixtures.GENERIC_IDENTITY_SOURCE_KIND,
        "root": str(identity.root),
        "manifest_sha256": sha256_file(identity.manifest_path),
    }
    annual_config = tmp_path / "current-annual-metric-config.json"
    write_json(
        annual_config,
        {
            "schema_version": "screening-metric-config-v2",
            "financial_as_of": CURRENT,
            "identity_source": identity_source,
            "companies": [
                {
                    **fixtures.COHORT[0],
                    "analysis_root": str(roots["ANNUAL"]),
                    "analysis_manifest_sha256": sha256_file(
                        roots["ANNUAL"] / "analysis_manifest.json"
                    ),
                    "input_years": [2021, 2022, 2023, 2024, 2025],
                    "display_years": [2022, 2023, 2024, 2025],
                }
            ],
        },
    )
    annual = fixtures.publish_screening_metrics(annual_config, tmp_path / "current-annual-metrics")
    assert len(fixtures.ScreeningMetricReader(annual.root).definitions) == 31
    dataset_config = tmp_path / "current-dataset-v2-config.json"
    write_json(
        dataset_config,
        {
            "schema_version": fixtures.DATASET_CONFIG_VERSION,
            "dataset_id": "current-prospective-fixture",
            "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
            "financial_as_of": CURRENT,
            "metric_root": str(annual.root),
            "metric_manifest_sha256": sha256_file(annual.root / fixtures.METRIC_MANIFEST),
            "identity_source": identity_source,
        },
    )
    dataset = fixtures.publish_screening_dataset_v2(dataset_config, tmp_path / "current-v2")
    quarter_config = tmp_path / "current-quarter-metric-config.json"
    write_json(
        quarter_config,
        {
            "schema_version": "quarterly-screening-metric-config-v1",
            "financial_as_of": CURRENT,
            "source_commit_sha": "d" * 40,
            "annual_metric_root": str(annual.root),
            "annual_metric_manifest_sha256": sha256_file(annual.root / fixtures.METRIC_MANIFEST),
            "companies": [
                {
                    **fixtures.COHORT[0],
                    "analysis_root": str(roots["QUARTERLY"]),
                    "analysis_manifest_sha256": sha256_file(
                        roots["QUARTERLY"] / "analysis_manifest.json"
                    ),
                }
            ],
        },
    )
    quarter = fixtures.publish_quarterly_screening_metrics(
        quarter_config, tmp_path / "current-quarter-metrics"
    )
    assert len(fixtures.QuarterlyMetricReader(quarter.root).definitions) == 41
    v3_config = tmp_path / "current-v3-config.json"
    write_json(
        v3_config,
        {
            "schema_version": fixtures.DATASET_V3_CONFIG_VERSION,
            "dataset_id": "current-prospective-fixture",
            "fixture_kind": "SYNTHETIC_ERROR_FIXTURE",
            "annual_dataset_root": str(dataset.root),
            "annual_manifest_sha256": sha256_file(dataset.manifest_path),
            "quarterly_metric_root": str(quarter.root),
            "quarterly_manifest_sha256": sha256_file(quarter.root / fixtures.QUARTERLY_MANIFEST),
        },
    )
    v3 = fixtures.publish_screening_dataset_v3(v3_config, tmp_path / "current-v3")
    assert fixtures.ScreeningDatasetV3Reader(v3).verify_all()["company_count"] == 1


def test_batch_reselection_resolves_once_for_both_modes_and_verifies_locally(tmp_path, monkeypatch):
    from sec_xbrl import prospective_selection as producer

    _, latest, config = _fixture(tmp_path, monkeypatch)
    manifest = publish_prospective_selection(config_path=config, destination=tmp_path / "selection")
    original = producer._resolve_config
    calls = []

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(producer, "_resolve_config", counted)
    roots = producer.prepare_reselected_analysis_batch(
        prospective_selection=_pin(manifest),
        destinations={"FIVE": {mode: tmp_path / mode for mode in ("ANNUAL", "QUARTERLY")}},
    )
    assert len(calls) == 1
    selection = resolve_prospective_selection(
        _pin(manifest), collection_manifest=latest, scope_companies=list(fixtures.COHORT)
    )
    calls.clear()
    for mode, root in roots["FIVE"].items():
        verify_reselected_analysis(root, selection=selection, ticker="FIVE", period_mode=mode)
    assert calls == []
    from dataclasses import replace

    with pytest.raises(ValueError, match="untrusted or mutated"):
        producer.checked_prospective_selection(
            replace(selection, financial_as_of="2026-10-26"),
            declaration=_pin(manifest),
            collection_manifest=latest,
        )


@pytest.mark.parametrize("changed", ["raw", "history", "inventory"])
def test_batch_commit_rechecks_all_inputs_before_publishing_any_target(
    tmp_path, monkeypatch, changed
):
    from sec_xbrl import prospective_selection as producer

    prepared, _, config = _fixture(tmp_path, monkeypatch)
    manifest = publish_prospective_selection(config_path=config, destination=tmp_path / "selection")
    stage = producer._stage_reselected_analysis
    calls = []

    def mutate_after_staging(*args, **kwargs):
        result = stage(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            if changed == "raw":
                path = Path(prepared.paths["first"]["snapshot"]) / "fact.parquet"
            elif changed == "history":
                root = prepared.histories["FIVE"].parent
                path = next(path for path in root.rglob("*.parquet") if path.is_file())
            else:
                path = prepared.histories["FIVE"].parent / "unexpected.json"
            path.write_bytes(b"changed-after-proof")
        return result

    monkeypatch.setattr(producer, "_stage_reselected_analysis", mutate_after_staging)
    with pytest.raises(ValueError):
        producer.prepare_reselected_analysis_batch(
            prospective_selection=_pin(manifest),
            destinations={"FIVE": {mode: tmp_path / mode for mode in ("ANNUAL", "QUARTERLY")}},
        )
    assert len(calls) == 2
    assert not (tmp_path / "ANNUAL").exists()
    assert not (tmp_path / "QUARTERLY").exists()


@pytest.mark.parametrize(
    "defect", ["omitted_archive", "bad_count", "bad_dates", "duplicate_archive"]
)
def test_submissions_archive_completeness_is_one_to_one(defect):
    from sec_xbrl.prospective_selection import _check_submissions_completeness

    root = {
        "cik": 123,
        "filings": {
            "recent": {},
            "files": [
                {
                    "name": "CIK123-submissions-001.json",
                    "filingCount": 1,
                    "filingFrom": "2020-01-01",
                    "filingTo": "2020-12-31",
                }
            ],
        },
    }
    archive = {"accessionNumber": ["0000000123-20-000001"], "filingDate": ["2020-01-02"]}
    _check_submissions_completeness([root, archive], "0000000123")
    if defect == "omitted_archive":
        snapshots = [root]
    elif defect == "bad_count":
        root["filings"]["files"][0]["filingCount"] = 2
        snapshots = [root, archive]
    elif defect == "bad_dates":
        archive["filingDate"] = ["2021-01-02"]
        snapshots = [root, archive]
    else:
        snapshots = [root, archive, archive]
    with pytest.raises(ValueError):
        _check_submissions_completeness(snapshots, "0000000123")


@pytest.mark.parametrize("extra", ["10-K/A", "10-Q"])
def test_complete_coherently_pinned_submissions_cannot_omit_new_eligible_filing(tmp_path, monkeypatch, extra):
    _, _, config = _fixture(tmp_path, monkeypatch, extra_filing=extra)
    # All current snapshot names, plan, intake, collection and ROOT compatibility
    # pins are coherent. The existing selector must still find the omitted item.
    with pytest.raises(ValueError, match="omits or changes eligible"):
        publish_prospective_selection(config_path=config, destination=tmp_path/"rejected")


def test_batch_checks_invocation_local_producer_bytes_before_commit(tmp_path, monkeypatch):
    from sec_xbrl import prospective_selection as producer
    _, _, config = _fixture(tmp_path, monkeypatch)
    manifest=publish_prospective_selection(config_path=config,destination=tmp_path/"selection")
    source_pins=producer._producer_source_pins
    calls=[]
    def changed_before_commit():
        result=source_pins();calls.append(True)
        if len(calls)==2:
            name=next(iter(result));result[name]={**result[name],"sha256":"0"*64}
        return result
    monkeypatch.setattr(producer,"_producer_source_pins",changed_before_commit)
    with pytest.raises(ValueError,match="producer sources changed"):
        producer.prepare_reselected_analysis_batch(prospective_selection=_pin(manifest),destinations={"FIVE":{
            mode:tmp_path/mode for mode in ("ANNUAL","QUARTERLY")}})
    assert len(calls)==2
    assert not (tmp_path/"ANNUAL").exists()
    assert not (tmp_path/"QUARTERLY").exists()
