"""Company-level operations around the existing history workflow.

This module owns orchestration records only.  Filing discovery, package
resolution, Layer 1 ingestion, period policy, and analytical publication remain
owned by :mod:`sec_xbrl.history` and its existing dependencies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec_xbrl import history
from sec_xbrl.filing.company_discovery import (
    SUPPORTED_FORMS,
    CompanySubmissionsAccessionProvider,
    canonicalize_cik,
)
from sec_xbrl.filing.trailing_corpus import TrailingCorpusError

COLLECTION_VERSION = "company-universe-collection-v1"
COLLECTION_RULE_VERSIONS = {
    "collection": COLLECTION_VERSION,
    "history": history.HISTORY_VERSION,
    "period": "m6-fiscal-boundaries-v2",
}
SAFE_TICKER = re.compile(r"^[A-Z0-9](?:[A-Z0-9.^-]{0,18}[A-Z0-9])?$")


@dataclass(frozen=True, slots=True)
class CompanyTarget:
    """One externally configured company target."""

    ticker: str
    cik: str | None
    groups: tuple[str, ...]
    purpose: str | None = None


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    """Validated collection configuration, independent from engine code."""

    universe_id: str
    purpose: str
    as_of_date: date
    source_observed_at: str | None
    completed_fiscal_years: int
    analytical_fiscal_years: int
    include_subsequent_quarters: bool
    companies: tuple[CompanyTarget, ...]


@dataclass(frozen=True, slots=True)
class CompanyStatus:
    """Offline status for one configured company."""

    ticker: str
    cik: str | None
    state: str
    capability: str
    action: str
    source_stage: str | None
    as_of_date: str
    source_observed_at: str | None
    requested_filings: int
    selected_filings: int
    held_filings: int
    succeeded_filings: int
    failed_filings: int
    reused_filings: int
    report_start: str | None
    report_end: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class UniverseStatus:
    """Deterministic aggregate status produced only from local manifests."""

    version: str
    universe_id: str
    as_of_date: str
    source_observed_at: str | None
    rule_versions: dict[str, str]
    requested_companies: int
    prepared_companies: int
    raw_complete_companies: int
    ready_companies: int
    failed_companies: int
    requested_filings: int
    selected_filings: int
    held_filings: int
    succeeded_filings: int
    failed_filings: int
    reused_filings: int
    companies: tuple[CompanyStatus, ...]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return payload


def _write_once_json(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if _read_json(path) != json.loads(json.dumps(payload, default=str)):
            raise ValueError(f"{label} already exists with different scope")
        return
    _write_json(path, payload)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_universe_config(path: Path) -> UniverseConfig:
    """Load and validate a company-universe configuration file."""
    payload = _read_json(path)
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("universe config schema_version must be 1")
    universe_id = str(payload.get("universe_id", "")).strip()
    purpose = str(payload.get("purpose", "")).strip()
    if not universe_id or not purpose:
        raise ValueError("universe_id and purpose are required")
    collection = payload.get("collection")
    if not isinstance(collection, dict):
        raise TypeError("collection configuration is required")
    completed = collection.get("completed_fiscal_years")
    analytical = collection.get("analytical_fiscal_years")
    subsequent = collection.get("include_subsequent_quarters")
    if type(completed) is not int or type(analytical) is not int:
        raise TypeError("fiscal-year windows must be JSON integers")
    if completed < 1 or analytical < 1 or analytical > completed:
        raise ValueError("fiscal-year windows must satisfy 1 <= analytical <= completed")
    if subsequent is not True:
        raise ValueError("include_subsequent_quarters must be true")
    raw_companies = payload.get("companies")
    if not isinstance(raw_companies, list) or not raw_companies:
        raise ValueError("at least one configured company is required")
    companies = []
    seen: set[str] = set()
    for row in raw_companies:
        if not isinstance(row, dict):
            raise TypeError("every company configuration must be an object")
        ticker = str(row.get("ticker", "")).strip().upper()
        if not SAFE_TICKER.fullmatch(ticker):
            raise ValueError(f"unsafe company ticker: {ticker!r}")
        if ticker in seen:
            raise ValueError("company tickers must be unique")
        seen.add(ticker)
        raw_cik = row.get("cik")
        cik = canonicalize_cik(raw_cik) if raw_cik not in (None, "") else None
        raw_groups = row.get("groups", [])
        if not isinstance(raw_groups, list) or any(not str(item).strip() for item in raw_groups):
            raise ValueError(f"groups must be a list of nonempty strings: {ticker}")
        companies.append(
            CompanyTarget(
                ticker=ticker,
                cik=cik,
                groups=tuple(dict.fromkeys(str(item).strip() for item in raw_groups)),
                purpose=str(row["purpose"]).strip() if row.get("purpose") else None,
            )
        )
    observed_at = payload.get("source_observed_at")
    if observed_at is not None:
        parsed_observed_at = datetime.fromisoformat(str(observed_at))
        if parsed_observed_at.tzinfo is None:
            raise ValueError("source_observed_at must include a UTC offset")
    return UniverseConfig(
        universe_id=universe_id,
        purpose=purpose,
        as_of_date=date.fromisoformat(str(payload["as_of_date"])),
        source_observed_at=str(observed_at) if observed_at is not None else None,
        completed_fiscal_years=completed,
        analytical_fiscal_years=analytical,
        include_subsequent_quarters=subsequent,
        companies=tuple(companies),
    )


def _request_payload(config: UniverseConfig) -> dict[str, Any]:
    return {
        "version": COLLECTION_VERSION,
        "universe_id": config.universe_id,
        "purpose": config.purpose,
        "as_of_date": config.as_of_date.isoformat(),
        "source_observed_at": config.source_observed_at,
        "collection": {
            "completed_fiscal_years": config.completed_fiscal_years,
            "analytical_fiscal_years": config.analytical_fiscal_years,
            "include_subsequent_quarters": config.include_subsequent_quarters,
        },
        "companies": [asdict(company) for company in config.companies],
        "rule_versions": COLLECTION_RULE_VERSIONS,
    }


def _validate_plan(plan: dict[str, Any], target: CompanyTarget, config: UniverseConfig) -> str:
    if plan.get("as_of_date") != config.as_of_date.isoformat():
        raise ValueError(f"plan as-of differs from configuration: {target.ticker}")
    companies = plan.get("companies")
    if not isinstance(companies, list) or len(companies) != 1:
        raise ValueError(f"one company is required in each plan: {target.ticker}")
    company = companies[0]
    if str(company.get("ticker", "")).upper() != target.ticker:
        raise ValueError(f"plan ticker differs from configuration: {target.ticker}")
    cik = canonicalize_cik(company.get("cik"))
    if target.cik is not None and cik != target.cik:
        raise ValueError(f"plan CIK differs from configuration: {target.ticker}")
    filings = company.get("filings")
    if not isinstance(filings, list) or not filings:
        raise ValueError(f"plan contains no selected filings: {target.ticker}")
    if any(date.fromisoformat(row["filed_date"]) > config.as_of_date for row in filings):
        raise ValueError(f"plan contains filings after as-of: {target.ticker}")
    if any(canonicalize_cik(row.get("cik")) != cik for row in filings):
        raise ValueError(f"plan filing CIK differs from company CIK: {target.ticker}")
    if any(row.get("form") not in SUPPORTED_FORMS for row in filings):
        raise ValueError(f"plan contains an unsupported filing form: {target.ticker}")
    accessions = [row.get("accession") for row in filings]
    if any(not accession for accession in accessions) or len(accessions) != len(set(accessions)):
        raise ValueError(f"plan accessions must be nonempty and unique: {target.ticker}")
    annual_dates = {
        row.get("report_date")
        for row in filings
        if row.get("form") == "10-K" and row.get("report_date")
    }
    if plan.get("recent_fiscal_years") == config.completed_fiscal_years:
        supplemental = plan.get("supplemental_predecessor_annual_baseline")
        expected_annuals = config.completed_fiscal_years + (1 if supplemental else 0)
        if len(annual_dates) != expected_annuals:
            raise ValueError(f"plan annual baseline count differs from configuration: {target.ticker}")
        if supplemental:
            if not isinstance(supplemental, dict) or not supplemental.get("accession") or not supplemental.get("reason"):
                raise ValueError(f"supplemental predecessor requires accession and reason: {target.ticker}")
            selected_accessions = {row.get("accession") for row in filings}
            if supplemental["accession"] not in selected_accessions:
                raise ValueError(f"supplemental predecessor is not selected: {target.ticker}")
        return "FULL_WINDOW"
    explicit = plan.get("report_start") is not None and plan.get("report_end") is not None
    if not explicit or len(annual_dates) >= config.completed_fiscal_years:
        raise ValueError(
            f"plan must request {config.completed_fiscal_years} fiscal years or an explicit short-history window: {target.ticker}"
        )
    report_dates = [row.get("report_date") for row in filings if row.get("report_date")]
    if not report_dates or min(report_dates) < str(plan["report_start"]) or max(report_dates) > str(plan["report_end"]):
        raise ValueError(f"short-history filings exceed explicit report-date bounds: {target.ticker}")
    return "AVAILABLE_PERIODS_ONLY"


def _copy_existing_plan(
    source: Path, destination: Path, target: CompanyTarget, config: UniverseConfig
) -> tuple[Path, str]:
    plan = _read_json(source)
    capability = _validate_plan(plan, target, config)
    _write_once_json(destination, plan, label=f"{target.ticker} history plan")
    return destination, capability


def _available_report_window(
    target: CompanyTarget,
    *,
    roots: Sequence[Path],
    workspace: Path,
    as_of: date,
) -> tuple[date, date]:
    paths_by_cik: dict[str, list[Path]] = {}
    ticker_ciks: set[str] = set()
    for root in (*roots, workspace / "submissions"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            try:
                payload = _read_json(path)
                raw_cik = payload.get("cik")
                if raw_cik is None and path.parent.name.isdigit():
                    raw_cik = path.parent.name
                if raw_cik is None or not ("filings" in payload or "accessionNumber" in payload):
                    continue
                cik = canonicalize_cik(raw_cik)
            except (OSError, TypeError, ValueError, KeyError):
                continue
            paths_by_cik.setdefault(cik, []).append(path)
            tickers = {str(item).upper() for item in payload.get("tickers", [])}
            if target.ticker in tickers or target.cik == cik:
                ticker_ciks.add(cik)
    if len(ticker_ciks) != 1:
        raise ValueError(f"cannot resolve one cached CIK for short history: {target.ticker}")
    cik = next(iter(ticker_ciks))
    refs = CompanySubmissionsAccessionProvider(paths_by_cik[cik], cik=cik).iter_filings(
        forms=set(SUPPORTED_FORMS)
    )
    dates = sorted(
        ref.report_date
        for ref in refs
        if ref.filed_date <= as_of and ref.report_date is not None
    )
    if not dates:
        raise ValueError(f"no supported actual report dates for short history: {target.ticker}")
    return dates[0], dates[-1]


def _append_attempt(root: Path, operation: str, payload: dict[str, Any]) -> None:
    attempt_id = uuid.uuid4().hex
    record = {
        "version": COLLECTION_VERSION,
        "operation": operation,
        "attempt_id": attempt_id,
        **payload,
    }
    _write_json(root / "operation_attempts" / f"{operation}-{attempt_id}.json", record)


def prepare_universe(
    *,
    config_path: Path,
    run_root: Path,
    submissions_roots: Sequence[Path] = (),
    offline: bool = False,
    existing_plans: Mapping[str, Path] | None = None,
) -> Path:
    """Prepare or resume one immutable history plan per configured company.

    Caller-supplied plans avoid discovery.  A company with fewer than the
    requested annual baselines falls back to an explicit actual report-date
    window using already captured submissions metadata.
    """
    config = load_universe_config(config_path)
    supplied = {ticker.upper(): Path(path) for ticker, path in (existing_plans or {}).items()}
    unknown = set(supplied) - {company.ticker for company in config.companies}
    if unknown:
        raise ValueError("existing plans contain unconfigured tickers: " + ", ".join(sorted(unknown)))
    request_path = run_root / "collection_request.json"
    _write_once_json(request_path, _request_payload(config), label="collection request")
    manifest_path = run_root / "collection_manifest.json"
    previous = _read_json(manifest_path) if manifest_path.exists() else {"companies": []}
    previous_by_ticker = {row["ticker"]: row for row in previous.get("companies", [])}
    companies: list[dict[str, Any]] = []
    started_at = _now()
    for target in config.companies:
        company_root = run_root / "companies" / target.ticker
        plan_path = company_root / "plan.json"
        identity_path = company_root / "plan_identity.json"
        prior = previous_by_ticker.get(target.ticker, {})
        entry: dict[str, Any] = {
            "ticker": target.ticker,
            "configured_cik": target.cik,
            "groups": list(target.groups),
            "purpose": target.purpose,
            "plan_path": str(plan_path.absolute()),
            "plan_status": "FAILED",
            "capability": prior.get("capability", "UNKNOWN"),
            "source_stage": prior.get("source_stage"),
        }
        try:
            if plan_path.exists():
                if identity_path.exists() and _read_json(identity_path).get("plan_sha256") != _digest(plan_path):
                    raise ValueError(f"immutable history plan changed: {target.ticker}")
                if target.ticker in supplied and _read_json(supplied[target.ticker]) != _read_json(plan_path):
                    raise ValueError(f"different caller plan supplied for run identity: {target.ticker}")
                plan = _read_json(plan_path)
                capability = _validate_plan(plan, target, config)
                stage = prior.get("source_stage") or "REUSED"
            elif target.ticker in supplied:
                _, capability = _copy_existing_plan(supplied[target.ticker], plan_path, target, config)
                plan = _read_json(plan_path)
                stage = "REUSED"
            else:
                try:
                    discovered = history.discover_history(
                        workspace=company_root,
                        tickers=(target.ticker,),
                        as_of=config.as_of_date,
                        submissions_roots=tuple(submissions_roots),
                        offline=offline,
                        recent_fiscal_years=config.completed_fiscal_years,
                    )
                    plan = _read_json(discovered)
                    capability = _validate_plan(plan, target, config)
                except TrailingCorpusError:
                    report_start, report_end = _available_report_window(
                        target,
                        roots=tuple(submissions_roots),
                        workspace=company_root,
                        as_of=config.as_of_date,
                    )
                    discovered = history.discover_history(
                        workspace=company_root,
                        tickers=(target.ticker,),
                        as_of=config.as_of_date,
                        submissions_roots=tuple(submissions_roots),
                        offline=True,
                        report_start=report_start,
                        report_end=report_end,
                    )
                    plan = _read_json(discovered)
                    capability = _validate_plan(plan, target, config)
                stage = "CACHE" if offline else "LIVE"
            company = plan["companies"][0]
            _write_once_json(
                identity_path,
                {
                    "version": COLLECTION_VERSION,
                    "ticker": target.ticker,
                    "cik": canonicalize_cik(company["cik"]),
                    "plan_sha256": _digest(plan_path),
                },
                label=f"{target.ticker} plan identity",
            )
            entry.update(
                cik=canonicalize_cik(company["cik"]),
                plan_status="PREPARED",
                capability=capability,
                source_stage=stage,
                selected_filings=len(company["filings"]),
                plan_sha256=_digest(plan_path),
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - company-level isolation is the contract.
            entry.update(error_type=type(exc).__name__, error=str(exc))
        companies.append(entry)
        _append_attempt(
            company_root,
            "prepare",
            {
                "started_at": started_at,
                "completed_at": _now(),
                "result": entry,
            },
        )
    manifest = {
        "version": COLLECTION_VERSION,
        "request_path": str(request_path.absolute()),
        "request_sha256": _digest(request_path),
        "companies": companies,
    }
    _write_json(manifest_path, manifest)
    write_status_outputs(manifest_path=manifest_path, output_root=run_root / "status")
    return manifest_path


def _source_runs_for(
    source_runs: Mapping[str, Sequence[Path]] | None, ticker: str
) -> tuple[Path, ...]:
    return tuple(Path(path) for path in (source_runs or {}).get(ticker, ()))


def collect_universe(
    *,
    manifest_path: Path,
    package_cache: Path,
    index_cache: Path,
    taxonomy_cache: Path,
    source_runs: Mapping[str, Sequence[Path]] | None = None,
    bootstrap_taxonomy: bool = False,
) -> Path:
    """Run serial per-company Layer 1 intake while isolating company failures."""
    manifest = _read_json(manifest_path)
    configured = {company["ticker"] for company in manifest["companies"]}
    unknown = set(source_runs or {}) - configured
    if unknown:
        raise ValueError("source runs contain unconfigured tickers: " + ", ".join(sorted(unknown)))
    started_at = _now()
    for company in manifest["companies"]:
        if company.get("plan_status") != "PREPARED":
            continue
        ticker = company["ticker"]
        company_root = manifest_path.parent / "companies" / ticker
        result: dict[str, Any]
        try:
            intake = history.ingest_history(
                plan_path=Path(company["plan_path"]),
                source_runs=_source_runs_for(source_runs, ticker),
                output_run=company_root / "intake",
                package_cache=package_cache,
                index_cache=index_cache,
                taxonomy_cache=taxonomy_cache,
                bootstrap_taxonomy=bootstrap_taxonomy,
            )
            payload = _read_json(intake)
            result = {
                "status": "RAW_COMPLETE" if payload.get("complete") else "RAW_FAILED",
                "intake_manifest": str(intake.absolute()),
                "complete": bool(payload.get("complete")),
            }
        except Exception as exc:  # noqa: BLE001 - company-level isolation is the contract.
            result = {
                "status": "RAW_FAILED",
                "complete": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        _append_attempt(
            company_root,
            "collect",
            {"started_at": started_at, "completed_at": _now(), "result": result},
        )
    write_status_outputs(manifest_path=manifest_path, output_root=manifest_path.parent / "status")
    return manifest_path.parent / "status" / "collection_status.json"


def build_universe(
    *,
    manifest_path: Path,
    output_root: Path,
    views: Sequence[str] = ("AS_FILED", "LATEST_REPORTED"),
) -> Path:
    """Explicitly publish governed history for raw-complete companies."""
    manifest = _read_json(manifest_path)
    started_at = _now()
    for company in manifest["companies"]:
        ticker = company["ticker"]
        company_root = manifest_path.parent / "companies" / ticker
        intake = company_root / "intake" / "history_intake.json"
        if not intake.exists() or not _read_json(intake).get("complete"):
            continue
        marker = company_root / "build_manifest.json"
        destination = output_root / ticker
        if marker.exists():
            prior = _read_json(marker)
            if prior.get("output_root") != str(destination.absolute()):
                raise ValueError(f"build destination changed for run identity: {ticker}")
            if prior.get("views") != list(views):
                raise ValueError(f"build views changed for run identity: {ticker}")
            result = {**prior, "reused": True}
            _append_attempt(
                company_root,
                "build",
                {"started_at": started_at, "completed_at": _now(), "result": result},
            )
            continue
        try:
            publication = history.build_history(
                intake_manifest=intake,
                output_root=destination,
                views=tuple(views),
            )
            result = {
                "version": COLLECTION_VERSION,
                "status": "READY",
                "output_root": str(destination.absolute()),
                "publication": str(publication.absolute()),
                "views": list(views),
                "completed_at": _now(),
            }
            _write_once_json(marker, result, label=f"{ticker} build")
        except Exception as exc:  # noqa: BLE001 - company-level isolation is the contract.
            result = {
                "status": "BUILD_FAILED",
                "output_root": str(destination.absolute()),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        _append_attempt(
            company_root,
            "build",
            {"started_at": started_at, "completed_at": _now(), "result": result},
        )
    write_status_outputs(manifest_path=manifest_path, output_root=manifest_path.parent / "status")
    return manifest_path.parent / "status" / "collection_status.json"


def _latest_failed_attempt(company_root: Path, operation: str) -> str | None:
    attempts = tuple((company_root / "operation_attempts").glob(f"{operation}-*.json"))
    if not attempts:
        return None
    records = tuple(_read_json(path) for path in attempts)
    latest = max(
        records,
        key=lambda row: (str(row.get("completed_at", "")), str(row.get("attempt_id", ""))),
    )
    result = latest.get("result", {})
    if result.get("status") in {"RAW_FAILED", "BUILD_FAILED"} or result.get("plan_status") == "FAILED":
        return result.get("error") or result.get("status")
    return None


def _company_status(
    company: dict[str, Any], *, request: dict[str, Any], run_root: Path
) -> CompanyStatus:
    ticker = company["ticker"]
    company_root = run_root / "companies" / ticker
    plan_path = Path(company["plan_path"])
    plan: dict[str, Any] | None = None
    plan_error: str | None = None
    if company.get("plan_status") == "PREPARED":
        identity_path = company_root / "plan_identity.json"
        try:
            if not plan_path.exists() or not identity_path.exists():
                raise ValueError("immutable plan or identity is missing")
            identity = _read_json(identity_path)
            plan_digest = _digest(plan_path)
            if identity.get("plan_sha256") != plan_digest or company.get("plan_sha256") != plan_digest:
                raise ValueError("immutable history plan integrity mismatch")
            plan = _read_json(plan_path)
        except (OSError, TypeError, ValueError) as exc:
            plan_error = str(exc)
    filings = plan["companies"][0]["filings"] if plan else []
    selected = len(filings)
    intake_path = company_root / "intake" / "history_intake.json"
    intake = _read_json(intake_path) if intake_path.exists() else None
    outcomes = intake.get("filings", []) if intake else []
    intake_error: str | None = None
    if intake is not None and plan is not None:
        expected = {
            (str(row.get("cik")), str(row.get("accession")))
            for row in filings
        }
        actual = [
            (str(row.get("filing", {}).get("cik")), str(row.get("filing", {}).get("accession")))
            for row in outcomes
        ]
        if intake.get("plan") != plan:
            intake_error = "intake plan differs from immutable company plan"
        elif len(actual) != len(set(actual)) or set(actual) != expected:
            intake_error = "intake accession outcomes differ from immutable company plan"
        elif any(row.get("status") not in {"INGESTED", "REUSED", "FAILED"} for row in outcomes):
            intake_error = "intake contains an unsupported accession status"
    succeeded = sum(row.get("status") in {"INGESTED", "REUSED"} for row in outcomes)
    failed = sum(row.get("status") == "FAILED" for row in outcomes)
    reused = sum(row.get("status") == "REUSED" for row in outcomes)
    held = max(selected - succeeded - failed, 0)
    build_path = company_root / "build_manifest.json"
    build = _read_json(build_path) if build_path.exists() else None
    prepare_error = (
        company.get("error") if company.get("plan_status") != "PREPARED" else plan_error
    )
    collect_error = _latest_failed_attempt(company_root, "collect")
    build_error = _latest_failed_attempt(company_root, "build")
    if prepare_error:
        state, action, error = "PREPARE_FAILED", "PREPARE", prepare_error
    elif intake_error:
        state, action, error = "RAW_FAILED", "RETRY", intake_error
    elif build and build.get("status") == "READY":
        state, action, error = "READY", "NONE", None
    elif build_error:
        state, action, error = "BUILD_FAILED", "BUILD", build_error
    elif intake and intake.get("complete") and failed == 0 and succeeded == selected:
        state, action, error = "RAW_COMPLETE", "BUILD_OPTIONAL", None
    elif failed or collect_error:
        state, action, error = "RAW_FAILED", "RETRY", collect_error or "ACCESSION_FAILURE"
    elif outcomes:
        state, action, error = "RAW_PARTIAL", "COLLECT", None
    else:
        state, action, error = "PREPARED", "COLLECT", None
    if outcomes and all(row.get("status") == "REUSED" for row in outcomes):
        source_stage = "REUSED"
    elif any(row.get("status") == "INGESTED" for row in outcomes):
        source_stage = "LIVE"
    else:
        source_stage = company.get("source_stage")
    dates = sorted(row["report_date"] for row in filings if row.get("report_date"))
    cik = company.get("cik")
    if cik is None and plan:
        cik = plan["companies"][0].get("cik")
    return CompanyStatus(
        ticker=ticker,
        cik=cik,
        state=state,
        capability=company.get("capability", "UNKNOWN"),
        action=action,
        source_stage=source_stage,
        as_of_date=request["as_of_date"],
        source_observed_at=request.get("source_observed_at"),
        requested_filings=selected,
        selected_filings=selected,
        held_filings=held,
        succeeded_filings=succeeded,
        failed_filings=failed,
        reused_filings=reused,
        report_start=dates[0] if dates else None,
        report_end=dates[-1] if dates else None,
        error=error,
    )


def read_universe_status(*, manifest_path: Path) -> UniverseStatus:
    """Read deterministic status without discovery, SEC, parser, or selection work."""
    manifest = _read_json(manifest_path)
    if manifest.get("version") != COLLECTION_VERSION:
        raise ValueError("unsupported collection manifest version")
    request_path = Path(manifest["request_path"])
    if _digest(request_path) != manifest["request_sha256"]:
        raise ValueError("collection request integrity mismatch")
    request = _read_json(request_path)
    companies = tuple(
        _company_status(company, request=request, run_root=manifest_path.parent)
        for company in manifest["companies"]
    )
    return UniverseStatus(
        version=COLLECTION_VERSION,
        universe_id=request["universe_id"],
        as_of_date=request["as_of_date"],
        source_observed_at=request.get("source_observed_at"),
        rule_versions=dict(request["rule_versions"]),
        requested_companies=len(companies),
        prepared_companies=sum(row.state != "PREPARE_FAILED" for row in companies),
        raw_complete_companies=sum(row.state in {"RAW_COMPLETE", "READY"} for row in companies),
        ready_companies=sum(row.state == "READY" for row in companies),
        failed_companies=sum(row.state in {"PREPARE_FAILED", "RAW_FAILED", "BUILD_FAILED"} for row in companies),
        requested_filings=sum(row.requested_filings for row in companies),
        selected_filings=sum(row.selected_filings for row in companies),
        held_filings=sum(row.held_filings for row in companies),
        succeeded_filings=sum(row.succeeded_filings for row in companies),
        failed_filings=sum(row.failed_filings for row in companies),
        reused_filings=sum(row.reused_filings for row in companies),
        companies=companies,
    )


def _status_dict(status: UniverseStatus) -> dict[str, Any]:
    return asdict(status)


def write_status_outputs(*, manifest_path: Path, output_root: Path) -> tuple[Path, Path, Path]:
    """Persist deterministic JSON, CSV, and HTML views of offline status."""
    status = read_universe_status(manifest_path=manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "collection_status.json"
    csv_path = output_root / "company_readiness.csv"
    html_path = output_root / "index.html"
    _write_json(json_path, _status_dict(status))
    columns = tuple(CompanyStatus.__dataclass_fields__)
    temporary_csv = csv_path.with_suffix(".csv.partial")
    with temporary_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in status.companies:
            writer.writerow(asdict(row))
    temporary_csv.replace(csv_path)
    heading = (
        f"{status.universe_id}: {status.ready_companies} ready, "
        f"{status.raw_complete_companies} raw complete, {status.failed_companies} failed"
    )
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value if value is not None else ''))}</td>"
            for value in (
                row.ticker,
                row.cik,
                row.state,
                row.capability,
                row.action,
                row.selected_filings,
                row.succeeded_filings,
                row.failed_filings,
                row.source_stage,
                row.error,
            )
        )
        + "</tr>"
        for row in status.companies
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(status.universe_id)}</title>
<style>body{{font-family:system-ui;margin:2rem}}table{{border-collapse:collapse}}th,td{{border:1px solid #bbb;padding:.4rem;text-align:left}}th{{background:#eee}}</style></head>
<body><h1>{html.escape(heading)}</h1><p>As of {html.escape(status.as_of_date)}</p>
<table><thead><tr><th>Ticker</th><th>CIK</th><th>State</th><th>Capability</th><th>Action</th><th>Selected</th><th>Succeeded</th><th>Failed</th><th>Stage</th><th>Error</th></tr></thead>
<tbody>{rows}</tbody></table></body></html>
"""
    temporary_html = html_path.with_suffix(".html.partial")
    temporary_html.write_text(document, encoding="utf-8")
    temporary_html.replace(html_path)
    return json_path, csv_path, html_path


def _keyed_paths(values: Sequence[str], *, repeated: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("expected TICKER=PATH")
        ticker, raw_path = value.split("=", 1)
        ticker = ticker.strip().upper()
        if repeated:
            result.setdefault(ticker, []).append(Path(raw_path))
        elif ticker in result:
            raise ValueError(f"duplicate path for ticker: {ticker}")
        else:
            result[ticker] = Path(raw_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--run-root", type=Path, required=True)
    prepare.add_argument("--submissions-root", action="append", type=Path, default=[])
    prepare.add_argument("--existing-plan", action="append", default=[])
    prepare.add_argument("--offline", action="store_true")
    collect = commands.add_parser("collect")
    collect.add_argument("--manifest", type=Path, required=True)
    collect.add_argument("--package-cache", type=Path, required=True)
    collect.add_argument("--index-cache", type=Path, required=True)
    collect.add_argument("--taxonomy-cache", type=Path, required=True)
    collect.add_argument("--source-run", action="append", default=[])
    collect.add_argument("--bootstrap-taxonomy", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--views", nargs="+", default=["AS_FILED", "LATEST_REPORTED"])
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--manifest", type=Path, required=True)
    status_parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_universe(
            config_path=args.config,
            run_root=args.run_root,
            submissions_roots=tuple(args.submissions_root),
            offline=args.offline,
            existing_plans=_keyed_paths(args.existing_plan, repeated=False),
        )
        status = read_universe_status(manifest_path=result)
    elif args.command == "collect":
        result = collect_universe(
            manifest_path=args.manifest,
            package_cache=args.package_cache,
            index_cache=args.index_cache,
            taxonomy_cache=args.taxonomy_cache,
            source_runs=_keyed_paths(args.source_run, repeated=True),
            bootstrap_taxonomy=args.bootstrap_taxonomy,
        )
        status = read_universe_status(manifest_path=args.manifest)
    elif args.command == "build":
        result = build_universe(
            manifest_path=args.manifest,
            output_root=args.output_root,
            views=tuple(args.views),
        )
        status = read_universe_status(manifest_path=args.manifest)
    else:
        output_root = args.output_root or args.manifest.parent / "status"
        result = write_status_outputs(manifest_path=args.manifest, output_root=output_root)[0]
        status = read_universe_status(manifest_path=args.manifest)
    print(result)
    if args.command == "prepare" and any(row.state == "PREPARE_FAILED" for row in status.companies):
        raise SystemExit(1)
    if args.command == "collect" and any(
        row.state not in {"RAW_COMPLETE", "READY"} for row in status.companies
    ):
        raise SystemExit(1)
    if args.command == "build" and any(row.state != "READY" for row in status.companies):
        raise SystemExit(1)
    if args.command == "status" and status.failed_companies:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
