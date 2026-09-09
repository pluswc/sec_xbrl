"""Explicit, recoverable U4 refresh orchestration over existing producers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sec_xbrl.analysis import open_analysis, prepare_catalog
from sec_xbrl.analytics.axis_timeseries import AxisReviewInput, prepare_axis_timeseries
from sec_xbrl.analytics.hierarchy_publication import prepare_hierarchy
from sec_xbrl.company_reports import COMPANY_FIELDS, _csv, _read_csv, read_decisions, refresh
from sec_xbrl.display.hierarchy import render_hierarchy

VERSION = "u4-continuous-refresh-v1"
SOURCE_MODES = {"LIVE", "CACHE", "REUSED", "SYNTHETIC"}
SETTINGS = ("companies.csv", "decisions.csv", "analysis_profiles.json", "target_status.json")
DECISION_HISTORY = "u4_decision_history.json"
SNAPSHOT_FILES = (*SETTINGS, DECISION_HISTORY, "analysis_current.json")
COMMIT_FILES = ("companies.csv", "target_status.json", DECISION_HISTORY, "analysis_current.json")
INTENT = ".continuous-refresh-commit.json"


@dataclass(frozen=True)
class RefreshResult:
    run_root: Path
    publication: Path
    rendered_report: Path
    publication_id: str


def run_continuous_refresh(
    *,
    admin: Path,
    workspace: Path,
    as_of: date,
    review_as_of: date,
    companion_plan: dict[str, Any],
    stage_sources: dict[str, str],
    tickers: tuple[str, ...] | None = None,
    fiscal_start: int | None = None,
    fiscal_end: int | None = None,
    source_runs: tuple[Path, ...] = (),
    submissions_roots: tuple[Path, ...] = (),
    offline: bool = False,
    bootstrap_taxonomy: bool = False,
) -> RefreshResult:
    """Prepare the complete consumer privately and publish its pointer last."""
    admin, workspace = Path(admin).resolve(), Path(workspace).resolve()
    if (admin / INTENT).exists():
        raise ValueError("pending administrator commit; inspect status and recover first")
    if workspace.exists():
        raise ValueError("choose a new U4 workspace")
    _validate_sources(stage_sources)
    _validate_plan(companion_plan)
    # This first check catches an already-invalid administrator before creating
    # run output. Publication policy below is deliberately derived again from
    # the exact copied snapshot, never from this potentially stale read.
    _validate_admin_decision_history(admin, review_as_of)
    run_root = workspace
    private_admin = run_root / "admin"
    private_admin.mkdir(parents=True)
    input_bytes = _snapshot_settings(admin, private_admin)
    active_quality = _validate_admin_decision_history(private_admin, review_as_of)
    request = {
        "version": VERSION,
        "run_id": uuid.uuid4().hex,
        "as_of": as_of.isoformat(),
        "review_as_of": review_as_of.isoformat(),
        "tickers": sorted(t.upper() for t in tickers) if tickers else None,
        "consumer_fiscal_start": fiscal_start,
        "consumer_fiscal_end": fiscal_end,
        "catalog_scope": "ALL_ACTIVE_REGISTERED_COMPANIES",
        "source_runs": [_source_identity(p) for p in source_runs],
        "submissions_roots": [_source_identity(p) for p in submissions_roots],
        "declared_stage_sources": dict(sorted(stage_sources.items())),
        "companion_plan_sha256": _sha_json(companion_plan),
        "settings": {name: _bytes_identity(value) for name, value in input_bytes.items()},
        "effective_admin_quality_decisions": active_quality,
    }
    _write_json(run_root / "request.json", request)
    _write_json(run_root / "companion_plan.snapshot.json", companion_plan)
    _write_json(run_root / "stage_sources.snapshot.json", stage_sources)
    stages: list[dict[str, Any]] = []
    active_stage = "history_review"
    try:
        if unresolved := [row for row in active_quality if row["decision"] in {"WARN", "BLOCK"}]:
            raise ValueError(
                "REVIEW_REQUIRED: final analytical consumer cannot yet attest effective admin "
                f"quality decisions: {json.dumps(unresolved, sort_keys=True)}"
            )
        active_stage = "history_review"
        source_report = refresh(
            private_admin,
            workspace=run_root / "history",
            as_of=as_of,
            review_as_of=review_as_of,
            tickers=tickers,
            source_runs=source_runs,
            submissions_roots=submissions_roots,
            offline=offline,
            bootstrap_taxonomy=bootstrap_taxonomy,
            render_report=False,
        )
        _stage(
            stages,
            "history_review",
            stage_sources,
            source_report,
            observed=_observe_history(private_admin, source_runs, submissions_roots, offline),
        )

        # A targeted collection run still republishes every active registered
        # company, preserving the previous catalogue's usable cohort.
        active_stage = "consumer"
        base = prepare_catalog(
            catalog=private_admin,
            destination=run_root / "consumer-base",
            tickers=None,
            fiscal_start=fiscal_start,
            fiscal_end=fiscal_end,
        )
        _stage(
            stages,
            "consumer",
            stage_sources,
            base,
            observed={"mode": "GENERATED", "from_stage": "history_review"},
        )

        hierarchy_cfg = companion_plan["hierarchy"]
        package_roots = _adapt_package_roots(
            private_admin,
            {str(Path(k)): str(Path(v)) for k, v in hierarchy_cfg["package_roots"].items()},
            run_root / "history" / "packages",
        )
        active_stage = "hierarchy"
        hierarchy = prepare_hierarchy(
            baseline=base,
            destination=run_root / "consumer-hierarchy",
            package_roots=package_roots,
            reviews=hierarchy_cfg["reviews"],
            display_reviews=hierarchy_cfg["display_reviews"],
            decision_cutoff=hierarchy_cfg["decision_cutoff"],
            taxonomy_cache=_optional_path(hierarchy_cfg.get("taxonomy_cache")),
            supplemental_work=run_root / "hierarchy-work",
            reconciliation_reviews=hierarchy_cfg.get("reconciliation_reviews", []),
        )
        _stage(
            stages,
            "hierarchy",
            stage_sources,
            hierarchy,
            observed={"mode": "GENERATED", "package_roots": package_roots},
        )

        axis_inputs = tuple(
            AxisReviewInput(
                ticker=item["ticker"],
                row_id=item["row_id"],
                lens_id=item["lens_id"],
                review_path=Path(item["review_path"]),
                source_panel_path=Path(item["source_panel_path"]),
            )
            for item in companion_plan["axis_reviews"]
        )
        active_stage = "axis"
        final = prepare_axis_timeseries(
            source_bundle=hierarchy,
            destination=run_root / "consumer-final",
            reviews=axis_inputs,
        )
        _stage(
            stages,
            "axis",
            stage_sources,
            final,
            observed={"mode": "GENERATED", "review_inputs": len(axis_inputs)},
        )

        active_stage = "render"
        rendered = run_root / "report"
        render_hierarchy(open_analysis(final), destination=rendered)
        _stage(
            stages,
            "render",
            stage_sources,
            rendered,
            observed={"mode": "GENERATED_FROM_VERIFIED_FINAL_PUBLICATION"},
        )
        active_stage = "verify"
        manifest = _verify_complete(final, rendered)

        active_stage = "commit"
        _assert_settings_unchanged(admin, input_bytes)
        statuses = json.loads((private_admin / "target_status.json").read_text())
        for outcome in statuses.values():
            if outcome.get("status") == "READY":
                outcome["evidence"] = {
                    **outcome.get("evidence", {}),
                    "consumer_bundle": str(final),
                    "publication_id": manifest["publication_id"],
                }
        decision_snapshot = run_root / "settings" / "decisions.csv"
        decision_snapshot.parent.mkdir()
        decision_snapshot.write_bytes(input_bytes["decisions.csv"])
        decision_history = _next_decision_history(input_bytes, decision_snapshot, request["run_id"])
        new_files = {
            "companies.csv": (private_admin / "companies.csv").read_bytes(),
            "target_status.json": _json_bytes(statuses),
            DECISION_HISTORY: _json_bytes(decision_history),
            "analysis_current.json": _json_bytes(
                {"bundle_path": str(final), "publication_id": manifest["publication_id"]}
            ),
        }
        _commit_admin(admin, run_root, input_bytes, new_files)
        active_stage = "finalize"
        _write_json(
            run_root / "run_manifest.json",
            {
                **request,
                "status": "PUBLISHED",
                "stages": stages,
                "publication": _source_identity(final),
                "publication_id": manifest["publication_id"],
            },
        )
        (admin / INTENT).unlink()
        return RefreshResult(run_root, final, rendered, manifest["publication_id"])
    except Exception as exc:
        pending_commit = (admin / INTENT).exists()
        _append_exception(
            run_root,
            stage=active_stage,
            classification=_exception_classification(exc),
            source=_exception_source(run_root, exc),
            impact=(
                "Administrator commit may be partly or fully installed; status reports a pending "
                "intent and recover restores the prior registration/pointer."
                if pending_commit
                else "No completed U4 publication was registered; the prior consumer remains authoritative."
            ),
            next_action=(
                "Run status, then recover the exact pending commit before retrying."
                if pending_commit
                else _next_action(exc)
            ),
        )
        _write_json(
            run_root / "run_manifest.json",
            {
                **request,
                "status": "COMMIT_FINALIZATION_REQUIRED" if pending_commit else "STOPPED",
                "stages": stages,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise


def admin_status(admin: Path) -> dict[str, Any]:
    """Return current publication identity and any interrupted commit."""
    admin = Path(admin)
    pointer = admin / "analysis_current.json"
    return {
        "pointer": json.loads(pointer.read_text()) if pointer.exists() else None,
        "pending_commit": json.loads((admin / INTENT).read_text())
        if (admin / INTENT).exists()
        else None,
    }


def read_exceptions(run_root: Path) -> list[dict[str, Any]]:
    path = Path(run_root) / "exceptions.json"
    return json.loads(path.read_text()) if path.exists() else []


def resume_reviewed_publication(
    *, admin: Path, stopped_run: Path, ticker: str, reviewed_publication: Path
) -> dict[str, Any]:
    """Bind an explicitly reviewed publication only to its exact stopped parent."""
    from sec_xbrl.longitudinal.disclosure_review import ReviewedPublicationReader

    admin, stopped_run = Path(admin), Path(stopped_run)
    ticker = ticker.upper()
    if (admin / INTENT).exists():
        raise ValueError("pending administrator commit; recover before resume")
    old = {name: (admin / name).read_bytes() for name in SNAPSHOT_FILES if (admin / name).exists()}
    if "target_status.json" not in old or "analysis_current.json" not in old:
        raise ValueError("resume requires existing target status and consumer pointer")
    artifacts = [
        path
        for path in stopped_run.rglob("review_refresh_required.json")
        if json.loads(path.read_text()).get("ticker") == ticker
    ]
    if len(artifacts) != 1:
        raise ValueError("resume requires exactly one stopped review artifact for ticker")
    stopped = json.loads(artifacts[0].read_text())
    reviewed = ReviewedPublicationReader(Path(reviewed_publication))
    if (
        Path(reviewed.review_manifest["parent"]).resolve()
        != Path(stopped["prepared_parent"]).resolve()
    ):
        raise ValueError("reviewed publication is not bound to the stopped prepared parent")
    previous = ReviewedPublicationReader(Path(stopped["previous_publication"]))
    # Quarantine is current materialized state and may legitimately shrink
    # after an exact APPROVE. The publisher derives it from these append-only
    # histories, which must remain byte-equivalent as records.
    for name in ("candidates", "decisions", "quality_decisions"):
        prior_rows = {_sha_json(row) for row in previous.records(name)}
        new_rows = {_sha_json(row) for row in reviewed.records(name)}
        if not prior_rows <= new_rows:
            raise ValueError(f"reviewed publication deleted or edited prior {name}")
    companies = _read_csv(admin / "companies.csv", COMPANY_FIELDS, content=old["companies.csv"])
    company = next((row for row in companies if row["ticker"] == ticker), None)
    if company is None:
        raise ValueError("resume ticker is not registered")
    if Path(company["publication"]).resolve() != Path(stopped["previous_publication"]).resolve():
        raise ValueError("stopped run is stale; current registration no longer matches it")
    company["publication"] = str(Path(reviewed_publication).resolve())
    resume_id = uuid.uuid4().hex
    resume_root = stopped_run / ("resume-commit-" + resume_id)
    private = resume_root / "private"
    private.mkdir(parents=True)
    _csv(private / "companies.csv", COMPANY_FIELDS, companies)
    statuses = json.loads(old["target_status.json"])
    statuses[ticker] = {
        "status": "NOT_PREPARED",
        "reason": "EXPLICIT_REVIEWED_PUBLICATION_REGISTERED",
        "evidence": {
            "stopped_run": str(stopped_run.resolve()),
            "prepared_parent": stopped["prepared_parent"],
            "reviewed_publication": str(Path(reviewed_publication).resolve()),
        },
    }
    _assert_settings_unchanged(admin, old)
    _commit_admin(
        admin,
        resume_root,
        old,
        {
            "companies.csv": (private / "companies.csv").read_bytes(),
            "target_status.json": _json_bytes(statuses),
            DECISION_HISTORY: old.get(
                DECISION_HISTORY, _json_bytes({"version": VERSION, "snapshots": []})
            ),
            "analysis_current.json": old["analysis_current.json"],
        },
    )
    result = {
        "ticker": ticker,
        "stopped_run": str(stopped_run.resolve()),
        "prepared_parent": stopped["prepared_parent"],
        "previous_publication": stopped["previous_publication"],
        "reviewed_publication": str(Path(reviewed_publication).resolve()),
        "status": "REGISTERED_FOR_NEW_EXPLICIT_RUN",
    }
    _write_json(stopped_run / f"resume-{ticker}-{resume_id}.json", result)
    (admin / INTENT).unlink()
    return result


def recover_admin(admin: Path) -> None:
    """Roll an interrupted multi-file administrator commit back to old bytes."""
    admin = Path(admin)
    intent_path = admin / INTENT
    if not intent_path.exists():
        raise ValueError("no pending administrator commit")
    intent = json.loads(intent_path.read_text())
    validated: list[tuple[dict[str, Any], Path, bytes | None]] = []
    for entry in intent["files"]:
        target = admin / entry["name"]
        current = target.read_bytes() if target.exists() else None
        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
        allowed = {entry["original_sha256"], entry["replacement_sha256"]}
        if current_hash not in allowed:
            raise ValueError(f"administrator file changed outside pending commit: {entry['name']}")
        if entry["existed"]:
            backup = Path(entry["backup"])
            payload = backup.read_bytes()
            if hashlib.sha256(payload).hexdigest() != entry["original_sha256"]:
                raise ValueError(f"commit backup checksum mismatch: {entry['name']}")
        else:
            payload = None
        validated.append((entry, target, payload))
    for entry, target, payload in reversed(validated):
        if entry["existed"]:
            assert payload is not None
            _replace_bytes(target, payload)
        elif target.exists():
            target.unlink()
    intent_path.unlink()


def _snapshot_settings(admin: Path, private: Path) -> dict[str, bytes]:
    if not (admin / "companies.csv").is_file() or not (admin / "decisions.csv").is_file():
        raise ValueError("administrator is not initialized")
    values: dict[str, bytes] = {}
    for name in SNAPSHOT_FILES:
        path = admin / name
        if path.exists():
            values[name] = path.read_bytes()
            if name in SETTINGS:
                (private / name).write_bytes(values[name])
    # prepare_catalog must publish only to the private catalogue.
    if not (private / "target_status.json").exists():
        (private / "target_status.json").write_text("{}\n")
    _copy_decision_histories(admin, private, values)
    return values


def _validate_admin_decision_history(admin: Path, review_as_of: date) -> list[dict[str, str]]:
    """Validate both legacy run snapshots and durable U4 snapshot references."""
    active = read_decisions(admin, review_as_of=review_as_of)
    current = {
        row["decision_id"]: row
        for row in _read_csv(admin / "decisions.csv", tuple(_decision_fields()))
    }
    index_path = admin / DECISION_HISTORY
    if not index_path.exists():
        return active
    index = json.loads(index_path.read_text())
    if index.get("version") != VERSION or not isinstance(index.get("snapshots"), list):
        raise ValueError("invalid U4 decision history index")
    for entry in index["snapshots"]:
        path = Path(entry["path"])
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise ValueError("U4 decision history snapshot changed")
        for row in _read_csv(path, tuple(_decision_fields()), content=payload):
            if current.get(row["decision_id"]) != row:
                raise ValueError("published U4 decisions cannot be edited or deleted")
    return active


def _copy_decision_histories(admin: Path, private: Path, settings: dict[str, bytes]) -> None:
    """Give existing report validation the same immutable history as real admin."""
    copied: set[str] = set()
    for snapshot in sorted((admin / "runs").glob("*/decisions.csv")):
        relative = snapshot.relative_to(admin)
        destination = private / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(snapshot.read_bytes())
        copied.add(str(snapshot.resolve()))
    if DECISION_HISTORY not in settings:
        return
    index = json.loads(settings[DECISION_HISTORY])
    for entry in index["snapshots"]:
        source = Path(entry["path"])
        if str(source.resolve()) in copied:
            continue
        destination = private / "runs" / ("u4-" + entry["sha256"][:16]) / "decisions.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


def _next_decision_history(
    settings: dict[str, bytes], snapshot: Path, run_id: str
) -> dict[str, Any]:
    if DECISION_HISTORY in settings:
        result = json.loads(settings[DECISION_HISTORY])
    else:
        result = {"version": VERSION, "snapshots": []}
    payload = snapshot.read_bytes()
    result["snapshots"].append(
        {
            "run_id": run_id,
            "path": str(snapshot.resolve()),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    )
    return result


def _decision_fields() -> tuple[str, ...]:
    from sec_xbrl.company_reports import DECISION_FIELDS

    return DECISION_FIELDS


def _assert_settings_unchanged(admin: Path, snapshot: dict[str, bytes]) -> None:
    for name in SNAPSHOT_FILES:
        path = admin / name
        current = path.read_bytes() if path.exists() else None
        expected = snapshot.get(name)
        if current != expected:
            raise ValueError(f"administrator setting changed during run: {name}")


def _commit_admin(
    admin: Path, run_root: Path, old: dict[str, bytes], new: dict[str, bytes]
) -> None:
    backup_root = run_root / "commit-backup"
    backup_root.mkdir()
    entries = []
    for name in COMMIT_FILES:
        prior = old.get(name)
        backup = backup_root / name
        if prior is not None:
            backup.write_bytes(prior)
        entries.append(
            {
                "name": name,
                "existed": prior is not None,
                "backup": str(backup),
                "original_sha256": hashlib.sha256(prior).hexdigest() if prior is not None else None,
                "replacement_sha256": hashlib.sha256(new[name]).hexdigest(),
            }
        )
    intent = {
        "version": VERSION,
        "status": "PENDING_ROLLBACK_ON_RECOVERY",
        "run_root": str(run_root),
        "files": entries,
        "pointer_is_last": True,
    }
    try:
        with (admin / INTENT).open("xb") as stream:
            stream.write(_json_bytes(intent))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("another administrator commit is already pending") from exc
    try:
        for index, name in enumerate(COMMIT_FILES):
            # Recheck files not yet written. This catches an administrator edit
            # arriving after the broader pre-commit settings check.
            for pending in COMMIT_FILES[index:]:
                current_path = admin / pending
                current = current_path.read_bytes() if current_path.exists() else None
                expected = old.get(pending)
                if current != expected:
                    raise ValueError(f"administrator file changed during commit: {pending}")
            _replace_bytes(admin / name, new[name])
    except Exception:
        # Normal exceptions restore all old bytes. A process crash leaves the
        # durable intent for the explicit recovery command.
        recover_admin(admin)
        raise
    # The caller removes the intent only after its success record is durable.


def _replace_bytes(target: Path, payload: bytes) -> None:
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, target)


def _verify_complete(final: Path, rendered: Path) -> dict[str, Any]:
    client = open_analysis(final)
    if not (final / "axis_timeseries_manifest.json").is_file():
        raise ValueError("Axis companion manifest missing")
    if not (rendered / "index.html").is_file():
        raise ValueError("rendered hierarchy entry point missing")
    for ticker, company in client.manifest["companies"].items():
        client.overview(
            ticker, fiscal_start=min(company["years"]), fiscal_end=max(company["years"])
        )
        client.statement_catalog(ticker)
    return client.manifest


def _validate_sources(sources: dict[str, str]) -> None:
    required = {"history_review", "consumer", "hierarchy", "axis", "render"}
    if set(sources) != required or any(value not in SOURCE_MODES for value in sources.values()):
        raise ValueError(
            f"stage_sources requires exactly {sorted(required)} with {sorted(SOURCE_MODES)} values"
        )


def _validate_plan(plan: dict[str, Any]) -> None:
    if set(plan) != {"hierarchy", "axis_reviews"} or not isinstance(plan["axis_reviews"], list):
        raise ValueError("companion plan requires hierarchy and axis_reviews")
    hierarchy = plan["hierarchy"]
    required = {"package_roots", "reviews", "display_reviews", "decision_cutoff"}
    if not isinstance(hierarchy, dict) or not required <= set(hierarchy):
        raise ValueError(f"hierarchy plan requires {sorted(required)}")


def _stage(
    stages: list[dict[str, Any]],
    name: str,
    sources: dict[str, str],
    output: Path,
    *,
    observed: dict[str, Any],
) -> None:
    stages.append(
        {
            "stage": name,
            "declared_source_mode": sources[name],
            "observed": observed,
            "output": _source_identity(output),
        }
    )


def _observe_history(
    admin: Path, source_runs: tuple[Path, ...], submissions_roots: tuple[Path, ...], offline: bool
) -> dict[str, Any]:
    from sec_xbrl.history import open_history_publication

    supplied = {str(Path(path).resolve()) for path in source_runs}
    filings = []
    for row in _read_csv(admin / "companies.csv", COMPANY_FIELDS):
        if row["active"] != "true" or not row["publication"]:
            continue
        reader = open_history_publication(Path(row["publication"]))
        intake_path = Path(reader.manifest["source_intake"])
        intake = json.loads(intake_path.read_text())
        for entry in intake["filings"]:
            if entry["ticker"] != row["ticker"]:
                continue
            source_run = str(Path(entry["source_run"]).resolve())
            filings.append(
                {
                    "ticker": row["ticker"],
                    "accession": entry["filing"]["accession"],
                    "source_run": source_run,
                    "observed_mode": "REUSED_SOURCE_RUN"
                    if source_run in supplied
                    else "GENERATED_SOURCE_RUN",
                }
            )
    return {
        "offline": offline,
        "source_runs": [_source_identity(p) for p in source_runs],
        "submissions_roots": [_source_identity(p) for p in submissions_roots],
        "filings": filings,
    }


def _adapt_package_roots(
    admin: Path, configured: dict[str, str], generated_cache: Path
) -> dict[str, str]:
    from sec_xbrl.history import open_history_publication

    result = {
        str(Path(key).resolve()): str(Path(value).resolve()) for key, value in configured.items()
    }
    for row in _read_csv(admin / "companies.csv", COMPANY_FIELDS):
        if row["active"] != "true" or not row["publication"]:
            continue
        reader = open_history_publication(Path(row["publication"]))
        intake = json.loads(Path(reader.manifest["source_intake"]).read_text())
        for entry in intake["filings"]:
            source_run = str(Path(entry["source_run"]).resolve())
            if source_run not in result:
                result[source_run] = str(generated_cache.resolve())
    return result


def _append_exception(
    run_root: Path,
    *,
    stage: str,
    classification: str,
    source: dict[str, Any],
    impact: str,
    next_action: str,
) -> None:
    path = run_root / "exceptions.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append(
        {
            "exception_id": uuid.uuid4().hex,
            "stage": stage,
            "classification": classification,
            "source": source,
            "impact": impact,
            "next_action": next_action,
        }
    )
    _write_json(path, rows)


def _next_action(exc: Exception) -> str:
    message = str(exc).lower()
    if "review" in message or "candidate" in message or "approval" in message:
        return "Complete exact source review/re-attestation, publish it explicitly, then start a new run."
    if "setting changed" in message:
        return "Inspect the administrator edit and retry from a new exact settings snapshot."
    return "Inspect the retained stage output and exact input, correct it, then start a new run."


def _exception_classification(exc: Exception) -> str:
    message = str(exc).upper()
    if "REVIEW" in message or "APPROVAL" in message or "CANDIDATE" in message:
        return "REVIEW_REQUIRED"
    if "UNSUPPORTED" in message:
        return "UNSUPPORTED"
    if "DISCLOSURE_MISSING" in message:
        return "DISCLOSURE_MISSING"
    if "NOT_PREPARED" in message or "NO PREPARED PUBLICATION" in message:
        return "NOT_PREPARED"
    return "PREPARATION_FAILED"


def _exception_source(run_root: Path, exc: Exception) -> dict[str, Any]:
    review_artifacts = []
    for path in run_root.rglob("review_refresh_required.json"):
        value = json.loads(path.read_text())
        review_artifacts.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "ticker": value.get("ticker"),
                "previous_publication": value.get("previous_publication"),
                "prepared_parent": value.get("prepared_parent"),
                "new_accessions": value.get("new_accessions_requiring_review", []),
            }
        )
    return {
        "request": str(run_root / "request.json"),
        "detail": str(exc),
        "review_artifacts": review_artifacts,
    }


def _source_identity(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.is_file():
        result.update(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size
        )
    elif path.is_dir():
        for candidate in (
            "analysis_manifest.json",
            "history_manifest.json",
            "review_manifest.json",
        ):
            manifest = path / candidate
            if manifest.is_file():
                result.update(
                    manifest=candidate,
                    manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                )
                break
    return result


def _bytes_identity(value: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}


def _sha_json(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--as-of", type=date.fromisoformat, required=True)
    run.add_argument("--review-as-of", type=date.fromisoformat, required=True)
    run.add_argument("--companion-plan", type=Path, required=True)
    run.add_argument("--stage-sources", type=Path, required=True)
    run.add_argument("--ticker", action="append")
    run.add_argument("--fiscal-start", type=int)
    run.add_argument("--fiscal-end", type=int)
    run.add_argument("--source-run", type=Path, action="append", default=[])
    run.add_argument("--submissions-root", type=Path, action="append", default=[])
    run.add_argument("--offline", action="store_true")
    run.add_argument("--bootstrap-taxonomy", action="store_true")
    sub.add_parser("status")
    exceptions = sub.add_parser("exceptions")
    exceptions.add_argument("--run-root", type=Path, required=True)
    resume = sub.add_parser("resume-reviewed")
    resume.add_argument("--stopped-run", type=Path, required=True)
    resume.add_argument("--ticker", required=True)
    resume.add_argument("--reviewed-publication", type=Path, required=True)
    sub.add_parser("recover")
    args = parser.parse_args()
    if args.command == "run":
        result = run_continuous_refresh(
            admin=args.admin,
            workspace=args.workspace,
            as_of=args.as_of,
            review_as_of=args.review_as_of,
            companion_plan=json.loads(args.companion_plan.read_text()),
            stage_sources=json.loads(args.stage_sources.read_text()),
            tickers=tuple(args.ticker) if args.ticker else None,
            fiscal_start=args.fiscal_start,
            fiscal_end=args.fiscal_end,
            source_runs=tuple(args.source_run),
            submissions_roots=tuple(args.submissions_root),
            offline=args.offline,
            bootstrap_taxonomy=args.bootstrap_taxonomy,
        )
        print(result.publication)
    elif args.command == "status":
        print(json.dumps(admin_status(args.admin), ensure_ascii=False, indent=2))
    elif args.command == "exceptions":
        print(json.dumps(read_exceptions(args.run_root), ensure_ascii=False, indent=2))
    elif args.command == "resume-reviewed":
        print(
            json.dumps(
                resume_reviewed_publication(
                    admin=args.admin,
                    stopped_run=args.stopped_run,
                    ticker=args.ticker,
                    reviewed_publication=args.reviewed_publication,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        recover_admin(args.admin)


if __name__ == "__main__":
    main()
