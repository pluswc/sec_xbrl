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


def _run(admin: Path, workspace: Path, *, tickers=("AAA",)):
    return u4.run_continuous_refresh(
        admin=admin,
        workspace=workspace,
        as_of=date(2026, 9, 9),
        review_as_of=date(2026, 9, 8),
        companion_plan=PLAN,
        stage_sources=SOURCES,
        tickers=tickers,
        offline=True,
    )


def test_complete_run_publishes_final_companion_last_and_keeps_catalog_cohort(
    tmp_path: Path,
) -> None:
    admin = tmp_path / "admin"
    old = _admin(admin)
    mocks = _producer_mocks(admin)
    with (
        mocks[0],
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
    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text())
    assert manifest["status"] == "PUBLISHED"
    assert [stage["declared_source_mode"] for stage in manifest["stages"]] == ["SYNTHETIC"] * 5


@pytest.mark.parametrize("failure", ["refresh", "catalog", "hierarchy", "axis", "render"])
def test_producer_failure_preserves_all_administrator_bytes(tmp_path: Path, failure: str) -> None:
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
    assert exception["source"]["request"].endswith("request.json")
    assert exception["impact"] and exception["next_action"]


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
