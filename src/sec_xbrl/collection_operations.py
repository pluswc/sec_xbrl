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
import os
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
    pending_filings: int
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
    pending_filings: int
    succeeded_filings: int
    failed_filings: int
    reused_filings: int
    companies: tuple[CompanyStatus, ...]


@dataclass(frozen=True, slots=True)
class _RunAttestation:
    manifest: dict[str, Any]
    request: dict[str, Any]
    config: UniverseConfig
    plans: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _IntakeAttestation:
    payload: dict[str, Any] | None
    sha256: str | None
    complete: bool
    error: str | None
    succeeded: int
    failed: int
    reused: int
    pending: int


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


def _text(value: Any, *, label: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value.strip():
        raise TypeError(f"{label} must be a nonempty JSON string")
    return value.strip()


def _parse_universe_config(payload: dict[str, Any]) -> UniverseConfig:
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("universe config schema_version must be 1")
    universe_id = _text(payload.get("universe_id"), label="universe_id")
    purpose = _text(payload.get("purpose"), label="purpose")
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
        raw_ticker = _text(row.get("ticker"), label="company ticker")
        assert raw_ticker is not None
        ticker = raw_ticker.upper()
        if not SAFE_TICKER.fullmatch(ticker):
            raise ValueError(f"unsafe company ticker: {ticker!r}")
        if ticker in seen:
            raise ValueError("company tickers must be unique")
        seen.add(ticker)
        raw_cik = row.get("cik")
        cik = canonicalize_cik(raw_cik) if raw_cik not in (None, "") else None
        raw_groups = row.get("groups", [])
        if not isinstance(raw_groups, list) or any(
            type(item) is not str or not item.strip() for item in raw_groups
        ):
            raise ValueError(f"groups must be a list of nonempty strings: {ticker}")
        company_purpose = _text(
            row.get("purpose"), label=f"company purpose for {ticker}", optional=True
        )
        companies.append(
            CompanyTarget(
                ticker=ticker,
                cik=cik,
                groups=tuple(dict.fromkeys(item.strip() for item in raw_groups)),
                purpose=company_purpose,
            )
        )
    observed_at = payload.get("source_observed_at")
    if observed_at is not None:
        observed_at = _text(observed_at, label="source_observed_at")
        parsed_observed_at = datetime.fromisoformat(observed_at)
        if parsed_observed_at.tzinfo is None:
            raise ValueError("source_observed_at must include a UTC offset")
    raw_as_of = _text(payload.get("as_of_date"), label="as_of_date")
    assert universe_id is not None and purpose is not None and raw_as_of is not None
    return UniverseConfig(
        universe_id=universe_id,
        purpose=purpose,
        as_of_date=date.fromisoformat(raw_as_of),
        source_observed_at=observed_at,
        completed_fiscal_years=completed,
        analytical_fiscal_years=analytical,
        include_subsequent_quarters=subsequent,
        companies=tuple(companies),
    )


def load_universe_config(path: Path) -> UniverseConfig:
    """Load and validate a company-universe configuration file."""
    return _parse_universe_config(_read_json(path))


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
    if plan.get("version") != history.HISTORY_VERSION:
        raise ValueError(f"unsupported history plan version: {target.ticker}")
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
    for row in filings:
        report_date = row.get("report_date")
        if report_date is not None and type(report_date) is not str:
            raise TypeError(f"plan report dates must be strings: {target.ticker}")
        if report_date is not None:
            date.fromisoformat(report_date)
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


def _config_from_request(request: dict[str, Any]) -> UniverseConfig:
    if request.get("version") != COLLECTION_VERSION:
        raise ValueError("unsupported collection request version")
    if request.get("rule_versions") != COLLECTION_RULE_VERSIONS:
        raise ValueError("collection request rule versions differ")
    return _parse_universe_config(
        {
            "schema_version": 1,
            "universe_id": request.get("universe_id"),
            "purpose": request.get("purpose"),
            "as_of_date": request.get("as_of_date"),
            "source_observed_at": request.get("source_observed_at"),
            "collection": request.get("collection"),
            "companies": request.get("companies"),
        }
    )


def _require_fixed_path(raw: Any, expected: Path, *, root: Path, label: str) -> Path:
    if type(raw) is not str:
        raise TypeError(f"{label} must be an absolute path string")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or path != expected.absolute():
        raise ValueError(f"{label} differs from the fixed run path")
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"{label} escapes the run root")
    return path


def _require_safe_mutation_path(path: Path, *, root: Path, label: str) -> None:
    root = root.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its declared root") from exc
    current = root
    if current.is_symlink():
        raise ValueError(f"{label} has a symlinked mutation path")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} has a symlinked mutation path")


def _reject_unsafe_mutable_descendants(path: Path, *, root: Path, label: str) -> None:
    if not path.exists():
        return
    root_resolved = root.resolve(strict=False)
    pending = [path]
    while pending:
        current = pending.pop()
        if current.is_symlink():
            raise ValueError(f"{label} has a symlinked mutable descendant")
        if not current.resolve(strict=False).is_relative_to(root_resolved):
            raise ValueError(f"{label} has a mutable descendant outside its declared root")
        if not current.is_dir():
            continue
        with os.scandir(current) as entries:
            for entry in entries:
                child = Path(entry.path)
                if entry.is_symlink():
                    raise ValueError(f"{label} has a symlinked mutable descendant")
                if not child.resolve(strict=False).is_relative_to(root_resolved):
                    raise ValueError(
                        f"{label} has a mutable descendant outside its declared root"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(child)


def _preflight_status_paths(output_root: Path) -> None:
    paths = [output_root]
    for name in ("collection_status.json", "company_readiness.csv", "index.html"):
        path = output_root / name
        paths.extend((path, path.with_suffix(path.suffix + ".partial")))
    for path in paths:
        _require_safe_mutation_path(path, root=output_root, label="status output")
    _reject_unsafe_mutable_descendants(
        output_root, root=output_root, label="status output"
    )


def _preflight_run_mutations(run_root: Path, tickers: Sequence[str]) -> None:
    paths = [
        run_root,
        run_root / "companies",
        run_root / "collection_request.json",
        run_root / "collection_request.json.partial",
        run_root / "collection_manifest.json",
        run_root / "collection_manifest.json.partial",
        run_root / "status",
    ]
    for ticker in tickers:
        company_root = run_root / "companies" / ticker
        paths.extend(
            (
                company_root,
                company_root / "plan.json",
                company_root / "plan.json.partial",
                company_root / "plan_identity.json",
                company_root / "plan_identity.json.partial",
                company_root / "company_tickers.json",
                company_root / "company_tickers.json.partial",
                company_root / "submissions",
                company_root / "discovery_state",
                company_root / "intake",
                company_root / "operation_attempts",
                company_root / "build_manifest.json",
                company_root / "build_manifest.json.partial",
            )
        )
    for path in paths:
        _require_safe_mutation_path(path, root=run_root, label="collection run")
    mutable_subtrees = [run_root / "status"]
    for ticker in tickers:
        company_root = run_root / "companies" / ticker
        mutable_subtrees.extend(
            (
                company_root / "submissions",
                company_root / "discovery_state",
                company_root / "intake",
                company_root / "operation_attempts",
            )
        )
    for subtree in mutable_subtrees:
        _reject_unsafe_mutable_descendants(
            subtree, root=run_root, label="collection run"
        )
    _preflight_status_paths(run_root / "status")


def _preflight_publication_paths(output_root: Path, tickers: Sequence[str]) -> None:
    _require_safe_mutation_path(output_root, root=output_root, label="publication root")
    for ticker in tickers:
        destination = output_root / ticker
        _require_safe_mutation_path(destination, root=output_root, label="company publication")
        _reject_unsafe_mutable_descendants(
            destination, root=output_root, label=f"company publication {ticker}"
        )


def _attest_run(manifest_path: Path) -> _RunAttestation:
    """Validate immutable run scope before any operation performs writes."""
    run_root = manifest_path.parent
    expected_manifest = run_root / "collection_manifest.json"
    if manifest_path.absolute() != expected_manifest.absolute():
        raise ValueError("collection manifest must use the fixed run path")
    manifest = _read_json(manifest_path)
    if manifest.get("version") != COLLECTION_VERSION:
        raise ValueError("unsupported collection manifest version")
    request_path = _require_fixed_path(
        manifest.get("request_path"),
        run_root / "collection_request.json",
        root=run_root,
        label="collection request path",
    )
    if not request_path.is_file() or request_path.is_symlink():
        raise ValueError("collection request is missing or unsafe")
    if type(manifest.get("request_sha256")) is not str or _digest(request_path) != manifest["request_sha256"]:
        raise ValueError("collection request integrity mismatch")
    request = _read_json(request_path)
    config = _config_from_request(request)
    rows = manifest.get("companies")
    if not isinstance(rows, list):
        raise TypeError("collection manifest companies must be a list")
    requested_tickers = [target.ticker for target in config.companies]
    manifest_tickers = [row.get("ticker") if isinstance(row, dict) else None for row in rows]
    if manifest_tickers != requested_tickers or len(set(manifest_tickers)) != len(manifest_tickers):
        raise ValueError("collection manifest company membership differs from immutable request")
    plans: dict[str, dict[str, Any]] = {}
    for target, row in zip(config.companies, rows, strict=True):
        if not isinstance(row, dict):
            raise TypeError("collection manifest company entry must be an object")
        if not SAFE_TICKER.fullmatch(target.ticker):
            raise ValueError(f"unsafe company ticker: {target.ticker!r}")
        expected_root = run_root / "companies" / target.ticker
        plan_path = _require_fixed_path(
            row.get("plan_path"),
            expected_root / "plan.json",
            root=run_root,
            label=f"{target.ticker} plan path",
        )
        if row.get("configured_cik") != target.cik:
            raise ValueError(f"configured CIK changed in collection manifest: {target.ticker}")
        if row.get("groups") != list(target.groups) or row.get("purpose") != target.purpose:
            raise ValueError(f"configured metadata changed in collection manifest: {target.ticker}")
        if row.get("plan_status") not in {"PREPARED", "FAILED"}:
            raise ValueError(f"unsupported plan status: {target.ticker}")
        if row["plan_status"] == "FAILED":
            if type(row.get("error")) is not str:
                raise ValueError(f"failed plan must retain an error: {target.ticker}")
            continue
        identity_path = expected_root / "plan_identity.json"
        if not plan_path.is_file() or plan_path.is_symlink():
            raise ValueError(f"immutable history plan is missing or unsafe: {target.ticker}")
        if not identity_path.is_file() or identity_path.is_symlink():
            raise ValueError(f"immutable plan identity is missing or unsafe: {target.ticker}")
        identity = _read_json(identity_path)
        plan_digest = _digest(plan_path)
        if identity != {
            "version": COLLECTION_VERSION,
            "ticker": target.ticker,
            "cik": row.get("cik"),
            "plan_sha256": plan_digest,
        }:
            raise ValueError(f"immutable plan identity differs: {target.ticker}")
        if row.get("plan_sha256") != plan_digest:
            raise ValueError(f"immutable history plan integrity mismatch: {target.ticker}")
        plan = _read_json(plan_path)
        capability = _validate_plan(plan, target, config)
        company = plan["companies"][0]
        if row.get("cik") != canonicalize_cik(company["cik"]):
            raise ValueError(f"plan CIK changed in collection manifest: {target.ticker}")
        if row.get("selected_filings") != len(company["filings"]):
            raise ValueError(f"selected filing count changed in collection manifest: {target.ticker}")
        if row.get("capability") != capability:
            raise ValueError(f"plan capability changed in collection manifest: {target.ticker}")
        if row.get("source_stage") not in {"LIVE", "CACHE", "REUSED"}:
            raise ValueError(f"unsupported source stage: {target.ticker}")
        plans[target.ticker] = plan
    return _RunAttestation(manifest=manifest, request=request, config=config, plans=plans)


_FILING_IDENTITY_FIELDS = ("cik", "accession", "form", "filed_date", "report_date")


def _filing_identity(row: Any) -> tuple[Any, ...] | None:
    if not isinstance(row, dict):
        return None
    return tuple(row.get(field) for field in _FILING_IDENTITY_FIELDS)


def _attest_intake(path: Path, plan: dict[str, Any]) -> _IntakeAttestation:
    selected = len(plan["companies"][0]["filings"])
    if not path.exists():
        return _IntakeAttestation(None, None, False, None, 0, 0, 0, selected)
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError("intake manifest is missing or unsafe")
        payload = _read_json(path)
        if payload.get("version") not in {None, history.HISTORY_VERSION}:
            raise ValueError("unsupported history intake version")
        if payload.get("plan") != plan:
            raise ValueError("intake plan differs from immutable company plan")
        complete = payload.get("complete")
        if type(complete) is not bool:
            raise ValueError("intake complete flag must be boolean")
        outcomes = payload.get("filings")
        if not isinstance(outcomes, list):
            raise TypeError("intake filings must be a list")
        expected = {
            _filing_identity(row) for row in plan["companies"][0]["filings"]
        }
        actual = [_filing_identity(row.get("filing")) if isinstance(row, dict) else None for row in outcomes]
        if any(identity is None for identity in actual) or len(actual) != len(set(actual)):
            raise ValueError("intake contains duplicate or malformed filing outcomes")
        actual_set = set(actual)
        if not actual_set.issubset(expected):
            raise ValueError("intake filing identity is outside the immutable company plan")
        if complete and actual_set != expected:
            raise ValueError("complete intake does not cover the immutable company plan")
        statuses = [row.get("status") for row in outcomes]
        if any(status not in {"INGESTED", "REUSED", "FAILED"} for status in statuses):
            raise ValueError("intake contains an unsupported accession status")
        succeeded = sum(status in {"INGESTED", "REUSED"} for status in statuses)
        failed = sum(status == "FAILED" for status in statuses)
        if complete and (failed or succeeded != selected):
            raise ValueError("complete intake contains failed or missing filing outcomes")
        reused = sum(status == "REUSED" for status in statuses)
        return _IntakeAttestation(
            payload=payload,
            sha256=_digest(path),
            complete=complete,
            error=None,
            succeeded=succeeded,
            failed=failed,
            reused=reused,
            pending=max(selected - succeeded - failed, 0),
        )
    except (OSError, TypeError, ValueError) as exc:
        return _IntakeAttestation(
            payload=None,
            sha256=None,
            complete=False,
            error=str(exc),
            succeeded=0,
            failed=0,
            reused=0,
            pending=selected,
        )


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
    _preflight_run_mutations(run_root, tuple(company.ticker for company in config.companies))
    request_path = run_root / "collection_request.json"
    manifest_path = run_root / "collection_manifest.json"
    if manifest_path.exists():
        _attest_run(manifest_path)
    _write_once_json(request_path, _request_payload(config), label="collection request")
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
    attested = _attest_run(manifest_path)
    manifest = attested.manifest
    _preflight_run_mutations(
        manifest_path.parent, tuple(company.ticker for company in attested.config.companies)
    )
    configured = {company.ticker for company in attested.config.companies}
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
                plan_path=company_root / "plan.json",
                source_runs=_source_runs_for(source_runs, ticker),
                output_run=company_root / "intake",
                package_cache=package_cache,
                index_cache=index_cache,
                taxonomy_cache=taxonomy_cache,
                bootstrap_taxonomy=bootstrap_taxonomy,
            )
            intake_attestation = _attest_intake(intake, attested.plans[ticker])
            if intake_attestation.error:
                raise ValueError(intake_attestation.error)
            result = {
                "status": "RAW_COMPLETE" if intake_attestation.complete else "RAW_PARTIAL",
                "intake_manifest": str(intake.absolute()),
                "intake_sha256": intake_attestation.sha256,
                "complete": intake_attestation.complete,
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


def _declared_publication_files(
    publication: Path, publication_manifest: dict[str, Any]
) -> dict[str, str]:
    infos: list[dict[str, Any]] = []
    tables = publication_manifest.get("tables")
    if not isinstance(tables, list):
        raise TypeError("history publication tables must be a list")
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("files"), dict):
            raise TypeError("history publication table files are malformed")
        infos.extend(table["files"].values())
    if publication_manifest.get("derived_quarter") is not None:
        infos.append(publication_manifest["derived_quarter"])
    declared: dict[str, str] = {}
    for info in infos:
        if not isinstance(info, dict) or type(info.get("path")) is not str or type(info.get("sha256")) is not str:
            raise ValueError("history publication file declaration is malformed")
        relative = Path(info["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in declared:
            raise ValueError("history publication file path is unsafe or duplicated")
        path = publication / relative
        if not path.is_file() or path.is_symlink() or _digest(path) != info["sha256"]:
            raise ValueError("history publication file integrity mismatch")
        declared[str(relative)] = info["sha256"]
    return dict(sorted(declared.items()))


def _create_build_attestation(
    *,
    ticker: str,
    plan: dict[str, Any],
    plan_sha256: str,
    intake_path: Path,
    intake_sha256: str,
    destination: Path,
    publication: Path,
    views: Sequence[str],
) -> dict[str, Any]:
    history.HistoryPublicationReader(publication).verify_all()
    manifest_path = publication / "history_manifest.json"
    publication_manifest = _read_json(manifest_path)
    if publication_manifest.get("plan") != plan:
        raise ValueError("history publication plan differs from immutable company plan")
    if publication_manifest.get("source_intake") != str(intake_path.absolute()):
        raise ValueError("history publication source intake differs")
    if publication_manifest.get("views") != list(views):
        raise ValueError("history publication views differ")
    if not publication.resolve(strict=False).is_relative_to(destination.resolve(strict=False)):
        raise ValueError("history publication escapes the declared output root")
    declared_files = _declared_publication_files(publication, publication_manifest)
    if not declared_files:
        raise ValueError("history publication has no declared data files")
    return {
        "version": COLLECTION_VERSION,
        "status": "READY",
        "ticker": ticker,
        "output_root": str(destination.absolute()),
        "publication": str(publication.absolute()),
        "views": list(views),
        "plan_sha256": plan_sha256,
        "intake_manifest": str(intake_path.absolute()),
        "intake_sha256": intake_sha256,
        "history_manifest": str(manifest_path.absolute()),
        "history_manifest_sha256": _digest(manifest_path),
        "declared_files": declared_files,
        "completed_at": _now(),
    }


def _validate_build_attestation(
    marker: dict[str, Any],
    *,
    ticker: str,
    plan: dict[str, Any],
    plan_sha256: str,
    intake_path: Path,
    intake: _IntakeAttestation,
) -> str | None:
    try:
        if not intake.complete or intake.error or intake.sha256 is None:
            raise ValueError("READY requires a complete validated intake")
        if marker.get("version") != COLLECTION_VERSION or marker.get("status") != "READY":
            raise ValueError("unsupported build attestation")
        if marker.get("ticker") != ticker:
            raise ValueError("build attestation ticker differs")
        if marker.get("plan_sha256") != plan_sha256:
            raise ValueError("build attestation plan differs")
        if marker.get("intake_manifest") != str(intake_path.absolute()):
            raise ValueError("build attestation intake path differs")
        if marker.get("intake_sha256") != intake.sha256:
            raise ValueError("build attestation intake digest differs")
        output_root = Path(marker["output_root"])
        publication = Path(marker["publication"])
        if not output_root.is_absolute() or not publication.is_absolute():
            raise ValueError("build attestation paths must be absolute")
        if not publication.is_dir() or publication.is_symlink():
            raise ValueError("attested history publication is missing or unsafe")
        if not publication.resolve(strict=False).is_relative_to(output_root.resolve(strict=False)):
            raise ValueError("build publication escapes its output root")
        manifest_path = Path(marker["history_manifest"])
        if manifest_path != publication / "history_manifest.json":
            raise ValueError("build history manifest path differs")
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("attested history manifest is missing or unsafe")
        if marker.get("history_manifest_sha256") != _digest(manifest_path):
            raise ValueError("attested history manifest integrity mismatch")
        publication_manifest = _read_json(manifest_path)
        if publication_manifest.get("plan") != plan:
            raise ValueError("attested history publication plan differs")
        if publication_manifest.get("source_intake") != str(intake_path.absolute()):
            raise ValueError("attested history publication intake differs")
        if publication_manifest.get("views") != marker.get("views"):
            raise ValueError("attested history publication views differ")
        declared_files = _declared_publication_files(publication, publication_manifest)
        if not declared_files:
            raise ValueError("attested history publication has no declared data files")
        if marker.get("declared_files") != declared_files:
            raise ValueError("attested history publication file set differs")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return str(exc)
    return None


def build_universe(
    *,
    manifest_path: Path,
    output_root: Path,
    views: Sequence[str] = ("AS_FILED", "LATEST_REPORTED"),
) -> Path:
    """Explicitly publish governed history for raw-complete companies."""
    attested = _attest_run(manifest_path)
    manifest = attested.manifest
    tickers = tuple(company.ticker for company in attested.config.companies)
    _preflight_run_mutations(manifest_path.parent, tickers)
    _preflight_publication_paths(output_root, tickers)
    intake_by_ticker: dict[str, _IntakeAttestation] = {}
    for company in manifest["companies"]:
        if company.get("plan_status") != "PREPARED":
            continue
        ticker = company["ticker"]
        company_root = manifest_path.parent / "companies" / ticker
        intake_path = company_root / "intake" / "history_intake.json"
        intake = _attest_intake(intake_path, attested.plans[ticker])
        intake_by_ticker[ticker] = intake
        marker_path = company_root / "build_manifest.json"
        if marker_path.exists():
            if not marker_path.is_file() or marker_path.is_symlink():
                raise ValueError(f"build attestation is unsafe: {ticker}")
            marker = _read_json(marker_path)
            expected_destination = output_root / ticker
            if marker.get("output_root") != str(expected_destination.absolute()):
                raise ValueError(f"build destination changed for run identity: {ticker}")
            if marker.get("views") != list(views):
                raise ValueError(f"build views changed for run identity: {ticker}")
            error = _validate_build_attestation(
                marker,
                ticker=ticker,
                plan=attested.plans[ticker],
                plan_sha256=company["plan_sha256"],
                intake_path=intake_path,
                intake=intake,
            )
            if error:
                raise ValueError(f"invalid existing build attestation for {ticker}: {error}")
    started_at = _now()
    for company in manifest["companies"]:
        if company.get("plan_status") != "PREPARED":
            continue
        ticker = company["ticker"]
        company_root = manifest_path.parent / "companies" / ticker
        intake = company_root / "intake" / "history_intake.json"
        intake_attestation = intake_by_ticker[ticker]
        if not intake_attestation.complete or intake_attestation.error:
            continue
        marker = company_root / "build_manifest.json"
        destination = output_root / ticker
        if marker.exists():
            prior = _read_json(marker)
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
            result = _create_build_attestation(
                ticker=ticker,
                plan=attested.plans[ticker],
                plan_sha256=company["plan_sha256"],
                intake_path=intake,
                intake_sha256=intake_attestation.sha256 or "",
                destination=destination,
                publication=publication,
                views=views,
            )
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
    company: dict[str, Any],
    *,
    request: dict[str, Any],
    run_root: Path,
    plan: dict[str, Any] | None,
) -> CompanyStatus:
    ticker = company["ticker"]
    company_root = run_root / "companies" / ticker
    filings = plan["companies"][0]["filings"] if plan else []
    selected = len(filings)
    intake_path = company_root / "intake" / "history_intake.json"
    intake = _attest_intake(intake_path, plan) if plan else _IntakeAttestation(
        None, None, False, None, 0, 0, 0, 0
    )
    succeeded = intake.succeeded
    failed = intake.failed
    reused = intake.reused
    held = succeeded
    pending = intake.pending
    build_path = company_root / "build_manifest.json"
    build: dict[str, Any] | None = None
    build_attestation_error: str | None = None
    if build_path.exists() and plan is not None:
        try:
            if not build_path.is_file() or build_path.is_symlink():
                raise ValueError("build attestation is unsafe")
            build = _read_json(build_path)
            build_attestation_error = _validate_build_attestation(
                build,
                ticker=ticker,
                plan=plan,
                plan_sha256=company["plan_sha256"],
                intake_path=intake_path,
                intake=intake,
            )
        except (OSError, TypeError, ValueError) as exc:
            build_attestation_error = str(exc)
    prepare_error = company.get("error") if company.get("plan_status") != "PREPARED" else None
    collect_error = _latest_failed_attempt(company_root, "collect")
    build_attempt_error = _latest_failed_attempt(company_root, "build")
    if prepare_error:
        state, action, error = "PREPARE_FAILED", "PREPARE", prepare_error
    elif intake.error:
        state, action, error = "RAW_FAILED", "RETRY", intake.error
    elif build_attestation_error:
        state, action, error = "BUILD_FAILED", "BUILD", build_attestation_error
    elif build is not None:
        state, action, error = "READY", "NONE", None
    elif build_attempt_error:
        state, action, error = "BUILD_FAILED", "BUILD", build_attempt_error
    elif intake.complete:
        state, action, error = "RAW_COMPLETE", "BUILD_OPTIONAL", None
    elif failed or collect_error:
        state, action, error = "RAW_FAILED", "RETRY", collect_error or "ACCESSION_FAILURE"
    elif succeeded:
        state, action, error = "RAW_PARTIAL", "COLLECT", None
    else:
        state, action, error = "PREPARED", "COLLECT", None
    if succeeded and succeeded == reused:
        source_stage = "REUSED"
    elif succeeded:
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
        pending_filings=pending,
        succeeded_filings=succeeded,
        failed_filings=failed,
        reused_filings=reused,
        report_start=dates[0] if dates else None,
        report_end=dates[-1] if dates else None,
        error=error,
    )


def read_universe_status(*, manifest_path: Path) -> UniverseStatus:
    """Read deterministic status without discovery, SEC, parser, or selection work."""
    attested = _attest_run(manifest_path)
    companies = tuple(
        _company_status(
            company,
            request=attested.request,
            run_root=manifest_path.parent,
            plan=attested.plans.get(company["ticker"]),
        )
        for company in attested.manifest["companies"]
    )
    return UniverseStatus(
        version=COLLECTION_VERSION,
        universe_id=attested.request["universe_id"],
        as_of_date=attested.request["as_of_date"],
        source_observed_at=attested.request.get("source_observed_at"),
        rule_versions=dict(attested.request["rule_versions"]),
        requested_companies=len(attested.config.companies),
        prepared_companies=sum(row.state != "PREPARE_FAILED" for row in companies),
        raw_complete_companies=sum(row.state in {"RAW_COMPLETE", "READY"} for row in companies),
        ready_companies=sum(row.state == "READY" for row in companies),
        failed_companies=sum(row.state in {"PREPARE_FAILED", "RAW_FAILED", "BUILD_FAILED"} for row in companies),
        requested_filings=sum(row.requested_filings for row in companies),
        selected_filings=sum(row.selected_filings for row in companies),
        held_filings=sum(row.held_filings for row in companies),
        pending_filings=sum(row.pending_filings for row in companies),
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
    _preflight_status_paths(output_root)
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
                row.held_filings,
                row.pending_filings,
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
<table><thead><tr><th>Ticker</th><th>CIK</th><th>State</th><th>Capability</th><th>Action</th><th>Selected</th><th>Held</th><th>Pending</th><th>Succeeded</th><th>Failed</th><th>Stage</th><th>Error</th></tr></thead>
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
