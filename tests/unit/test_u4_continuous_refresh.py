from __future__ import annotations

import json
import runpy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sec_xbrl import continuous_refresh as u4
from sec_xbrl.company_reports import COMPANY_FIELDS, DECISION_FIELDS, _csv

SOURCES = {
    name: "SYNTHETIC" for name in ("history_review", "consumer", "hierarchy", "axis", "render")
}
PLAN = {
    "hierarchy": {
        "package_roots": {},
        "reviews": [],
        "display_reviews": [],
        "decision_cutoff": "2026-09-09T00:00:00+00:00",
    },
    "axis_reviews": [],
}


def _admin(root: Path) -> dict[str, bytes]:
    root.mkdir()
    _csv(
        root / "companies.csv",
        COMPANY_FIELDS,
        [
            {
                "active": "true",
                "ticker": "AAA",
                "recent_fiscal_years": "3",
                "fiscal_start": "2023",
                "fiscal_end": "2025",
                "publication": "/old/aaa",
            },
            {
                "active": "true",
                "ticker": "BBB",
                "recent_fiscal_years": "3",
                "fiscal_start": "2023",
                "fiscal_end": "2025",
                "publication": "/old/bbb",
            },
        ],
    )
    _csv(root / "decisions.csv", DECISION_FIELDS, [])
    (root / "analysis_profiles.json").write_text('{"AAA":{"core_rows":["revenue"]}}')
    (root / "target_status.json").write_text('{"AAA":{"status":"READY"},"BBB":{"status":"READY"}}')
    (root / "analysis_current.json").write_text(
        '{"bundle_path":"/old/bundle","publication_id":"old"}'
    )
    return {name: (root / name).read_bytes() for name in (*u4.SETTINGS, "analysis_current.json")}


def _quality_decision(decision_id: str, decision: str, known_at: str) -> dict[str, str]:
    return {
        "decision_id": decision_id,
        "issue_id": "issue-1",
        "ticker": "AAA",
        "accession": "0000000001-26-000001",
        "concept": "us-gaap:Revenue",
        "axis": "",
        "member": "",
        "decision": decision,
        "reviewer": "reviewer",
        "reason": "exact source check",
        "evidence": "/evidence/source.json",
        "known_at": known_at,
    }


def _producer_mocks(admin: Path, *, fail: str | None = None):
    def refresh(private, **kwargs):
        if fail == "refresh":
            raise RuntimeError("refresh failed")
        rows = (private / "companies.csv").read_text().replace("/old/aaa", "/new/aaa")
        (private / "companies.csv").write_text(rows)
        out = kwargs["workspace"] / "source-report"
        out.mkdir(parents=True)
        return out

    def directory(name):
        def call(**kwargs):
            if fail == name:
                raise RuntimeError(f"{name} failed")
            destination = kwargs["destination"]
            destination.mkdir(parents=True)
            return destination

        return call

    def render(client, *, destination, source_commit=None):
        if fail == "render":
            raise RuntimeError("render failed")
        destination.mkdir()
        (destination / "index.html").write_text("ok")

    return (
        patch.object(u4, "refresh", side_effect=refresh),
        patch.object(u4, "prepare_catalog", side_effect=directory("catalog")),
        patch.object(u4, "prepare_hierarchy", side_effect=directory("hierarchy")),
        patch.object(u4, "prepare_axis_timeseries", side_effect=directory("axis")),
        patch.object(u4, "render_hierarchy", side_effect=render),
        patch.object(u4, "open_analysis", return_value=object()),
        patch.object(u4, "_verify_complete", return_value={"publication_id": "new-publication"}),
        patch.object(u4, "_observe_history", return_value={"filings": [], "offline": True}),
        patch.object(
            u4, "_adapt_package_roots", side_effect=lambda admin, configured, generated: configured
        ),
    )


def _run(admin: Path, workspace: Path, *, tickers=("AAA",), **kwargs):
    return u4.run_continuous_refresh(
        admin=admin,
        workspace=workspace,
        as_of=date(2026, 9, 9),
        review_as_of=date(2026, 9, 8),
        companion_plan=PLAN,
        stage_sources=SOURCES,
        tickers=tickers,
        offline=True,
        **kwargs,
    )


def test_complete_run_publishes_final_companion_last_and_keeps_catalog_cohort(
    tmp_path: Path,
) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)
    with (
        mocks[0] as refresh_mock,
        mocks[1] as catalog,
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
    ):
        result = _run(admin, tmp_path / "run")
    assert result.publication == (tmp_path / "run" / "consumer-final").resolve()
    assert json.loads((admin / "analysis_current.json").read_text())["bundle_path"] == str(
        result.publication
    )
    assert b"/new/aaa" in (admin / "companies.csv").read_bytes()
    assert b"/old/bbb" in (admin / "companies.csv").read_bytes()
    assert (admin / "decisions.csv").read_bytes() == old["decisions.csv"]
    assert catalog.call_args.kwargs["tickers"] is None
    assert refresh_mock.call_args.kwargs["render_report"] is False
    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text())
    assert manifest["status"] == "PUBLISHED"
    assert [stage["declared_source_mode"] for stage in manifest["stages"]] == ["SYNTHETIC"] * 5


def test_consumer_fiscal_bounds_are_exact_and_do_not_change_collection_scope(
    tmp_path: Path,
) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    mocks = _producer_mocks(admin)
    with (
        mocks[0] as refresh_mock,
        mocks[1] as catalog,
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
    ):
        _run(admin, tmp_path / "run", fiscal_start=2023, fiscal_end=2026)
    assert catalog.call_args.kwargs["fiscal_start"] == 2023
    assert catalog.call_args.kwargs["fiscal_end"] == 2026
    assert "fiscal_start" not in refresh_mock.call_args.kwargs
    assert "fiscal_end" not in refresh_mock.call_args.kwargs
    request = json.loads((tmp_path / "run" / "request.json").read_text())
    assert request["consumer_fiscal_start"] == 2023
    assert request["consumer_fiscal_end"] == 2026


def test_second_run_rejects_edit_to_first_u4_decision_snapshot(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    block = _quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")
    release = _quality_decision("release", "RELEASE", "2026-09-02T00:00:00+09:00")
    _csv(admin / "decisions.csv", DECISION_FIELDS, [block, release])
    mocks = _producer_mocks(admin)
    with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6], mocks[7], mocks[8]:
        _run(admin, tmp_path / "first")
    assert (admin / u4.DECISION_HISTORY).is_file()
    _csv(
        admin / "decisions.csv",
        DECISION_FIELDS,
        [dict(block, reason="edited published reason"), release],
    )
    with (
        patch.object(u4, "refresh", side_effect=AssertionError("producer")),
        pytest.raises(ValueError, match="published U4 decisions cannot be edited or deleted"),
    ):
        _run(admin, tmp_path / "second")
    assert not (tmp_path / "second").exists()


def test_company_refresh_can_skip_legacy_complete_year_report(tmp_path: Path, monkeypatch) -> None:
    from sec_xbrl import company_reports as cr

    cr.register_company(tmp_path, ticker="AAA", recent_fiscal_years=3)
    for name, result in (
        ("discover_history", tmp_path / "plan"),
        ("ingest_history", tmp_path / "intake"),
        ("build_history", tmp_path / "panels"),
    ):
        monkeypatch.setattr(cr.history, name, lambda _result=result, **kwargs: _result)
    monkeypatch.setattr(cr, "report", lambda *args, **kwargs: pytest.fail("legacy report called"))
    result = cr.refresh(
        tmp_path,
        as_of=date(2026, 9, 9),
        review_as_of=date(2026, 9, 9),
        workspace=tmp_path / "work",
        offline=True,
        render_report=False,
    )
    assert result.parent == tmp_path / "work"


@pytest.mark.parametrize(
    ("failure", "expected_stage"),
    [
        ("refresh", "history_review"),
        ("catalog", "consumer"),
        ("hierarchy", "hierarchy"),
        ("axis", "axis"),
        ("render", "render"),
    ],
)
def test_producer_failure_preserves_all_administrator_bytes(
    tmp_path: Path, failure: str, expected_stage: str
) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin, fail=failure)
    with (
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
        pytest.raises(RuntimeError),
    ):
        _run(admin, tmp_path / "run")
    assert {name: (admin / name).read_bytes() for name in old} == old
    exception = u4.read_exceptions(tmp_path / "run")[0]
    assert exception["stage"] == expected_stage
    assert exception["source"]["request"].endswith("request.json")
    assert exception["impact"] and exception["next_action"]


def test_legacy_published_decision_deletion_stops_before_any_producer(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    legacy = admin / "runs" / "old" / "decisions.csv"
    legacy.parent.mkdir(parents=True)
    _csv(
        legacy, DECISION_FIELDS, [_quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")]
    )
    with (
        patch.object(u4, "refresh", side_effect=AssertionError("producer")),
        pytest.raises(ValueError, match="published decisions cannot be edited or deleted"),
    ):
        _run(admin, tmp_path / "run")
    assert not (tmp_path / "run").exists()
    assert {name: (admin / name).read_bytes() for name in old} == old


def test_legacy_histories_are_copied_and_release_allows_refresh(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    block = _quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")
    release = _quality_decision("release", "RELEASE", "2026-09-02T00:00:00+09:00")
    legacy = admin / "runs" / "old" / "decisions.csv"
    legacy.parent.mkdir(parents=True)
    _csv(legacy, DECISION_FIELDS, [block])
    _csv(admin / "decisions.csv", DECISION_FIELDS, [block, release])
    private = tmp_path / "private"
    private.mkdir()
    u4._snapshot_settings(admin, private)
    from sec_xbrl.company_reports import read_decisions

    assert read_decisions(private, review_as_of=date(2026, 9, 9))[0]["decision"] == "RELEASE"


def test_effective_block_stops_with_exact_review_exception(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    block = _quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")
    _csv(admin / "decisions.csv", DECISION_FIELDS, [block])
    old["decisions.csv"] = (admin / "decisions.csv").read_bytes()
    with (
        patch.object(u4, "refresh", side_effect=AssertionError("producer")),
        pytest.raises(ValueError, match="cannot yet attest effective admin quality decisions"),
    ):
        _run(admin, tmp_path / "run")
    exception = u4.read_exceptions(tmp_path / "run")[0]
    assert exception["classification"] == "REVIEW_REQUIRED"
    assert "0000000001-26-000001" in exception["source"]["detail"]
    assert {name: (admin / name).read_bytes() for name in old} == old


def test_quality_gate_uses_exact_snapshot_when_decision_changes_after_precheck(
    tmp_path: Path,
) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    block = _quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")
    original_snapshot = u4._snapshot_settings

    def change_then_snapshot(real_admin, private):
        _csv(admin / "decisions.csv", DECISION_FIELDS, [block])
        return original_snapshot(real_admin, private)

    with (
        patch.object(u4, "_snapshot_settings", side_effect=change_then_snapshot),
        patch.object(u4, "refresh", side_effect=AssertionError("producer")),
        pytest.raises(ValueError, match="cannot yet attest effective admin quality decisions"),
    ):
        _run(admin, tmp_path / "run")
    request = json.loads((tmp_path / "run" / "request.json").read_text())
    assert request["effective_admin_quality_decisions"] == [block]
    assert u4.read_exceptions(tmp_path / "run")[0]["classification"] == "REVIEW_REQUIRED"


def test_quality_gate_uses_exact_released_snapshot_after_precheck(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    block = _quality_decision("block", "BLOCK", "2026-09-01T00:00:00+09:00")
    release = _quality_decision("release", "RELEASE", "2026-09-02T00:00:00+09:00")
    original_snapshot = u4._snapshot_settings

    def change_then_snapshot(real_admin, private):
        _csv(admin / "decisions.csv", DECISION_FIELDS, [block, release])
        return original_snapshot(real_admin, private)

    mocks = _producer_mocks(admin)
    with (
        patch.object(u4, "_snapshot_settings", side_effect=change_then_snapshot),
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
    ):
        _run(admin, tmp_path / "run")
    request = json.loads((tmp_path / "run" / "request.json").read_text())
    assert request["effective_admin_quality_decisions"] == [release]


def test_concurrent_profile_edit_is_retained_and_stops_publish(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)

    def edit_during_render(client, *, destination, source_commit=None):
        destination.mkdir()
        (destination / "index.html").write_text("ok")
        (admin / "analysis_profiles.json").write_text('{"administrator":"new edit"}')

    with (
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        patch.object(u4, "render_hierarchy", side_effect=edit_during_render),
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
        pytest.raises(ValueError, match="setting changed"),
    ):
        _run(admin, tmp_path / "run")
    assert (admin / "analysis_profiles.json").read_text() == '{"administrator":"new edit"}'
    for name in ("companies.csv", "decisions.csv", "target_status.json", "analysis_current.json"):
        assert (admin / name).read_bytes() == old[name]


def test_concurrent_pointer_edit_is_retained_and_stops_publish(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)

    def edit_during_render(client, *, destination, source_commit=None):
        destination.mkdir()
        (destination / "index.html").write_text("ok")
        (admin / "analysis_current.json").write_text('{"publication_id":"other-admin"}')

    with (
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        patch.object(u4, "render_hierarchy", side_effect=edit_during_render),
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
        pytest.raises(ValueError, match="setting changed"),
    ):
        _run(admin, tmp_path / "run")
    assert (admin / "analysis_current.json").read_text() == '{"publication_id":"other-admin"}'
    for name in ("companies.csv", "decisions.csv", "target_status.json"):
        assert (admin / name).read_bytes() == old[name]


@pytest.mark.parametrize("failed_name", u4.COMMIT_FILES)
def test_each_normal_admin_replacement_failure_rolls_back(tmp_path: Path, failed_name: str) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)
    real_replace = u4.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(target).parent == admin and Path(target).name == failed_name and not failed:
            failed = True
            raise OSError("injected replacement fault")
        return real_replace(source, target)

    with (
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
        patch.object(u4.os, "replace", side_effect=fail_once),
        pytest.raises(OSError),
    ):
        _run(admin, tmp_path / "run")
    assert {name: (admin / name).read_bytes() for name in old} == old
    assert not (admin / u4.INTENT).exists()


def test_crash_intent_recovery_rejects_unrelated_edit_then_restores(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    run = tmp_path / "run"
    run.mkdir()
    replacement = {name: f'{{"new":"{name}"}}'.encode() for name in u4.COMMIT_FILES}
    real_replace = u4.os.replace

    class Crash(BaseException):
        pass

    def crash_on_status(source, target):
        if Path(target).parent == admin and Path(target).name == "target_status.json":
            raise Crash
        return real_replace(source, target)

    with patch.object(u4.os, "replace", side_effect=crash_on_status), pytest.raises(Crash):
        u4._commit_admin(admin, run, old, replacement)
    assert u4.admin_status(admin)["pending_commit"] is not None
    (admin / "companies.csv").write_text("external edit")
    with pytest.raises(ValueError, match="outside pending commit"):
        u4.recover_admin(admin)
    (admin / "companies.csv").write_bytes(replacement["companies.csv"])
    u4.recover_admin(admin)
    assert {name: (admin / name).read_bytes() for name in old} == old
    assert not (admin / u4.INTENT).exists()


def test_recovery_prevalidates_every_file_before_rollback(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    run = tmp_path / "run"
    run.mkdir()
    replacement = {name: f'{{"new":"{name}"}}'.encode() for name in u4.COMMIT_FILES}
    real_replace = u4.os.replace

    class Crash(BaseException):
        pass

    def crash_on_pointer(source, target):
        if Path(target).parent == admin and Path(target).name == "analysis_current.json":
            raise Crash
        return real_replace(source, target)

    with patch.object(u4.os, "replace", side_effect=crash_on_pointer), pytest.raises(Crash):
        u4._commit_admin(admin, run, old, replacement)
    before = {name: (admin / name).read_bytes() for name in u4.COMMIT_FILES}
    (admin / "analysis_current.json").write_text("unrelated pointer")
    with pytest.raises(ValueError, match="outside pending commit"):
        u4.recover_admin(admin)
    assert (admin / "companies.csv").read_bytes() == before["companies.csv"]
    assert (admin / "target_status.json").read_bytes() == before["target_status.json"]


def test_second_commit_cannot_overwrite_pending_intent(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    run = tmp_path / "run"
    run.mkdir()
    (admin / u4.INTENT).write_text('{"existing":"intent"}')
    new = {name: b"new" for name in u4.COMMIT_FILES}
    with pytest.raises(ValueError, match="already pending"):
        u4._commit_admin(admin, run, old, new)
    assert (admin / u4.INTENT).read_text() == '{"existing":"intent"}'


def test_success_record_failure_leaves_truthful_recoverable_commit(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)
    real_write = u4._write_json

    def fail_published(path, value):
        if path.name == "run_manifest.json" and value.get("status") == "PUBLISHED":
            raise OSError("journal disk fault")
        return real_write(path, value)

    with (
        mocks[0],
        mocks[1],
        mocks[2],
        mocks[3],
        mocks[4],
        mocks[5],
        mocks[6],
        mocks[7],
        mocks[8],
        patch.object(u4, "_write_json", side_effect=fail_published),
        pytest.raises(OSError),
    ):
        _run(admin, tmp_path / "run")
    assert u4.admin_status(admin)["pending_commit"] is not None
    assert (
        json.loads((tmp_path / "run" / "run_manifest.json").read_text())["status"]
        == "COMMIT_FINALIZATION_REQUIRED"
    )
    assert (
        json.loads((admin / "analysis_current.json").read_text())["publication_id"]
        == "new-publication"
    )
    u4.recover_admin(admin)
    assert {name: (admin / name).read_bytes() for name in old} == old


def test_resume_requires_exact_stopped_parent_and_preserves_histories(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    stopped_run = tmp_path / "stopped"
    artifact = stopped_run / "history" / "AAA" / "review_refresh_required.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps(
            {
                "ticker": "AAA",
                "prepared_parent": str(tmp_path / "parent"),
                "previous_publication": "/old/aaa",
            }
        )
    )
    prior = {
        "candidates": ({"id": "c1"},),
        "decisions": ({"id": "d1"},),
        "quality_decisions": ({"id": "q1"},),
        "quarantine": ({"id": "old-state"},),
    }
    current = {**prior, "decisions": (*prior["decisions"], {"id": "d2"}), "quarantine": ()}

    def reader(path):
        records = prior if str(path) == "/old/aaa" else current
        return SimpleNamespace(
            review_manifest={"parent": str(tmp_path / "parent")}, records=lambda name: records[name]
        )

    with patch(
        "sec_xbrl.longitudinal.disclosure_review.ReviewedPublicationReader", side_effect=reader
    ):
        result = u4.resume_reviewed_publication(
            admin=admin,
            stopped_run=stopped_run,
            ticker="AAA",
            reviewed_publication=tmp_path / "new-review",
        )
    assert result["prepared_parent"] == str(tmp_path / "parent")
    assert str(tmp_path / "new-review") in (admin / "companies.csv").read_text()
    assert json.loads((admin / "target_status.json").read_text())["AAA"]["status"] == "NOT_PREPARED"


def test_resume_rejects_review_of_unrelated_parent(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    stopped_run = tmp_path / "stopped"
    artifact = stopped_run / "review_refresh_required.json"
    stopped_run.mkdir()
    artifact.write_text(
        json.dumps(
            {
                "ticker": "AAA",
                "prepared_parent": str(tmp_path / "parent"),
                "previous_publication": "/old/aaa",
            }
        )
    )
    unrelated = SimpleNamespace(review_manifest={"parent": str(tmp_path / "other")})
    with (
        patch(
            "sec_xbrl.longitudinal.disclosure_review.ReviewedPublicationReader",
            return_value=unrelated,
        ),
        pytest.raises(ValueError, match="stopped prepared parent"),
    ):
        u4.resume_reviewed_publication(
            admin=admin,
            stopped_run=stopped_run,
            ticker="AAA",
            reviewed_publication=tmp_path / "new-review",
        )
    assert {name: (admin / name).read_bytes() for name in old} == old


def test_resume_concurrent_setting_edit_is_not_overwritten(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    stopped_run = tmp_path / "stopped"
    stopped_run.mkdir()
    (stopped_run / "review_refresh_required.json").write_text(
        json.dumps(
            {
                "ticker": "AAA",
                "prepared_parent": str(tmp_path / "parent"),
                "previous_publication": "/old/aaa",
            }
        )
    )
    records = {name: () for name in ("candidates", "decisions", "quality_decisions")}

    def reader(path):
        if str(path) != "/old/aaa":
            (admin / "analysis_profiles.json").write_text('{"concurrent":"edit"}')
        return SimpleNamespace(
            review_manifest={"parent": str(tmp_path / "parent")}, records=lambda name: records[name]
        )

    with (
        patch(
            "sec_xbrl.longitudinal.disclosure_review.ReviewedPublicationReader", side_effect=reader
        ),
        pytest.raises(ValueError, match="setting changed"),
    ):
        u4.resume_reviewed_publication(
            admin=admin,
            stopped_run=stopped_run,
            ticker="AAA",
            reviewed_publication=tmp_path / "new-review",
        )
    assert (admin / "analysis_profiles.json").read_text() == '{"concurrent":"edit"}'
    for name in ("companies.csv", "decisions.csv", "target_status.json", "analysis_current.json"):
        assert (admin / name).read_bytes() == old[name]


def test_resume_accepts_real_publish_review_chain(tmp_path: Path, monkeypatch) -> None:
    disclosure_tests = runpy.run_path("tests/test_disclosure_review.py")
    corpus = disclosure_tests["corpus"].__wrapped__(tmp_path, monkeypatch)
    publish = disclosure_tests["publish"]
    previous = publish(corpus, tmp_path / "old-review")
    reviewed = publish(corpus, tmp_path / "new-review", previous_publication=previous)
    admin = tmp_path / "admin"
    _admin(admin)
    (admin / "companies.csv").write_text(
        (admin / "companies.csv").read_text().replace("/old/aaa", str(previous.resolve()))
    )
    stopped_run = tmp_path / "stopped"
    stopped_run.mkdir()
    (stopped_run / "review_refresh_required.json").write_text(
        json.dumps(
            {
                "ticker": "AAA",
                "prepared_parent": str(corpus[0]),
                "previous_publication": str(previous),
            }
        )
    )
    result = u4.resume_reviewed_publication(
        admin=admin, stopped_run=stopped_run, ticker="AAA", reviewed_publication=reviewed
    )
    assert result["status"] == "REGISTERED_FOR_NEW_EXPLICIT_RUN"
    assert str(reviewed.resolve()) in (admin / "companies.csv").read_text()


def test_invalid_stage_provenance_rejected_before_workspace_creation(tmp_path: Path) -> None:
    admin = tmp_path / "admin"
    _admin(admin)
    with pytest.raises(ValueError, match="stage_sources"):
        u4.run_continuous_refresh(
            admin=admin,
            workspace=tmp_path / "run",
            as_of=date(2026, 9, 9),
            review_as_of=date(2026, 9, 9),
            companion_plan=PLAN,
            stage_sources={"history_review": "LIVE"},
        )
    assert not (tmp_path / "run").exists()
