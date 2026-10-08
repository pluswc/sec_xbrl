"""Offline completion publication for the governed company-universe delivery.

The renderer joins already prepared A, B, and C publications.  It performs no
SEC collection, XBRL parsing, filing selection, or financial calculation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from sec_xbrl import analysis
from sec_xbrl.analytics.reviewed_q4 import ReviewedQ4Reader
from sec_xbrl.collection_operations import load_universe_config, read_universe_status
from sec_xbrl.company_metadata import CompanyMetadataReader

VERSION = "company-universe-delivery-v1"
MANIFEST_NAME = "universe_delivery_manifest.json"
READINESS_JSON = "company_readiness.json"
READINESS_CSV = "company_readiness.csv"
REPORT_HTML = "index.html"
REPRO_README = "README.md"


@dataclass(frozen=True, slots=True)
class UniverseDeliveryPublication:
    """Paths and identity for one immutable completion publication."""

    root: Path
    publication_id: str
    manifest_path: Path
    readiness_json: Path
    readiness_csv: Path
    report_html: Path
    readme: Path


class UniverseDeliveryReader:
    """Defensively read and verify one immutable completion publication."""

    def __init__(self, root: Path, *, allow_staging: bool = False) -> None:
        self.root = Path(root)
        if (
            not self.root.is_dir()
            or self.root.is_symlink()
            or (self.root.name.startswith(".") and ".partial-" in self.root.name and not allow_staging)
        ):
            raise ValueError("completion publication is not a real published directory")
        expected = {
            MANIFEST_NAME,
            READINESS_JSON,
            READINESS_CSV,
            REPORT_HTML,
            REPRO_README,
        }
        children = tuple(self.root.iterdir())
        if {path.name for path in children} != expected or any(
            path.is_symlink() or not path.is_file() for path in children
        ):
            raise ValueError("completion publication file set is invalid")
        self.manifest = _read_json(self.root / MANIFEST_NAME)
        if self.manifest.get("version") != VERSION:
            raise ValueError("unsupported completion publication")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or set(files) != {
            READINESS_JSON,
            READINESS_CSV,
            REPORT_HTML,
            REPRO_README,
        }:
            raise ValueError("completion file manifest is invalid")
        for name, info in files.items():
            path = self.root / name
            if (
                not isinstance(info, dict)
                or info.get("sha256") != _sha256(path)
                or info.get("size") != path.stat().st_size
            ):
                raise ValueError(f"completion output integrity mismatch: {name}")
        identity = {
            key: value for key, value in self.manifest.items() if key != "publication_id"
        }
        expected_id = "universe-delivery-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        if self.manifest.get("publication_id") != expected_id:
            raise ValueError("completion publication identity mismatch")
        self.readiness = _read_json(self.root / READINESS_JSON)
        if (
            self.readiness.get("version") != VERSION
            or self.readiness.get("universe_id") != self.manifest.get("universe_id")
            or self.readiness.get("assessment_state") != self.manifest.get("assessment_state")
        ):
            raise ValueError("completion readiness scope differs from manifest")
        companies = self.readiness.get("companies")
        if not isinstance(companies, list) or not companies or len(companies) != len(
            {row.get("cik") for row in companies if isinstance(row, dict)}
        ):
            raise ValueError("completion readiness contains duplicate company rows")
        self.publication_id = expected_id


@dataclass(frozen=True, slots=True)
class _AnalysisAttestation:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    publication_id: str
    period_mode: str
    companies: tuple[str, ...]
    selection_as_of_dates: tuple[str, ...]
    source_publications: tuple[str, ...]
    manifest: dict[str, Any]


def publish_universe_delivery(
    *,
    config_path: Path,
    collection_manifest: Path,
    metadata_publication: Path,
    destination: Path,
    reviewed_q4_publication: Path | None = None,
    quarterly_analysis: Path | None = None,
    annual_analysis: Path | None = None,
    expected_q4_economic_cells: int = 16,
    expected_q4_view_records: int = 32,
) -> UniverseDeliveryPublication:
    """Validate prepared inputs and atomically publish readiness JSON/CSV/HTML."""
    if type(expected_q4_economic_cells) is not int or expected_q4_economic_cells < 0:
        raise ValueError("expected_q4_economic_cells must be a nonnegative integer")
    if type(expected_q4_view_records) is not int or expected_q4_view_records < 0:
        raise ValueError("expected_q4_view_records must be a nonnegative integer")
    if quarterly_analysis is not None and reviewed_q4_publication is None:
        raise ValueError("quarterly analysis requires its reviewed-Q4 publication")

    config_path = _regular_file(config_path, "universe configuration")
    collection_manifest = _regular_file(collection_manifest, "collection manifest")
    _read_json(config_path)
    config = load_universe_config(config_path)
    if any(company.cik is None for company in config.companies):
        raise ValueError("completion configuration requires an explicit CIK for every company")
    configured_tickers = tuple(company.ticker for company in config.companies)
    configured_ciks = tuple(str(company.cik) for company in config.companies)
    if len(configured_ciks) != len(set(configured_ciks)):
        raise ValueError("completion configuration contains duplicate company CIKs")

    collection_status = read_universe_status(manifest_path=collection_manifest)
    _validate_collection_scope(config, collection_status)
    collection_payload = _read_json(collection_manifest)
    request_path = _regular_file(
        Path(collection_payload["request_path"]), "collection request"
    )
    if collection_payload.get("request_sha256") != _sha256(request_path):
        raise ValueError("collection request digest changed")
    collection_company_sources = _collection_company_sources(
        collection_manifest, collection_payload
    )

    metadata = CompanyMetadataReader(metadata_publication)
    metadata_rows = metadata.list_companies()
    metadata_by_cik = {row.cik: row for row in metadata_rows}
    if len(metadata_by_cik) != len(metadata_rows):
        raise ValueError("metadata publication contains duplicate company rows")
    for company in config.companies:
        row = metadata_by_cik.get(str(company.cik))
        if row is None:
            raise ValueError(f"configured CIK is absent from metadata publication: {company.cik}")
        if company.ticker not in {ticker.upper() for ticker in row.tickers}:
            raise ValueError(f"metadata ticker/CIK differs from configuration: {company.ticker}")

    q4_reader: ReviewedQ4Reader | None = None
    q4_manifest: dict[str, Any] | None = None
    q4_derived: tuple[dict[str, Any], ...] = ()
    q4_exclusions: tuple[dict[str, Any], ...] = ()
    if reviewed_q4_publication is not None:
        q4_reader = ReviewedQ4Reader(reviewed_q4_publication)
        q4_reader.verify_all()
        q4_manifest = q4_reader.manifest
        q4_derived = q4_reader.records("derived")
        q4_exclusions = q4_reader.records("exclusion")
        _validate_q4_scope(
            q4_derived,
            {company.ticker: str(company.cik) for company in config.companies},
        )
        if any(
            row.get("ticker") is not None and row.get("ticker") not in configured_tickers
            for row in q4_exclusions
        ):
            raise ValueError("reviewed-Q4 exclusions contain a foreign ticker")

    quarterly = (
        _attest_analysis(Path(quarterly_analysis), expected_mode="QUARTERLY")
        if quarterly_analysis is not None
        else None
    )
    annual = (
        _attest_analysis(Path(annual_analysis), expected_mode="ANNUAL")
        if annual_analysis is not None
        else None
    )
    _validate_c_analysis_links(
        q4_root=Path(reviewed_q4_publication) if reviewed_q4_publication else None,
        q4_manifest=q4_manifest,
        q4_derived=q4_derived,
        quarterly=quarterly,
        annual=annual,
        configured_tickers=set(configured_tickers),
    )

    report = _readiness_model(
        config_path=config_path,
        config=config,
        collection_manifest=collection_manifest,
        collection_request=request_path,
        collection_company_sources=collection_company_sources,
        collection_status=collection_status,
        metadata=metadata,
        metadata_rows=metadata_rows,
        metadata_by_cik=metadata_by_cik,
        q4_root=Path(reviewed_q4_publication) if reviewed_q4_publication else None,
        q4_manifest=q4_manifest,
        q4_derived=q4_derived,
        q4_exclusions=q4_exclusions,
        quarterly=quarterly,
        annual=annual,
        expected_q4_economic_cells=expected_q4_economic_cells,
        expected_q4_view_records=expected_q4_view_records,
    )
    return _publish(report, Path(destination))


def _validate_collection_scope(config: Any, status: Any) -> None:
    if status.universe_id != config.universe_id:
        raise ValueError("collection universe differs from completion configuration")
    if status.as_of_date != config.as_of_date.isoformat():
        raise ValueError("collection as-of differs from completion configuration")
    if status.source_observed_at != config.source_observed_at:
        raise ValueError("collection observation time differs from completion configuration")
    expected = [(company.ticker, str(company.cik)) for company in config.companies]
    actual = [(row.ticker, row.cik) for row in status.companies]
    if actual != expected:
        raise ValueError("collection ticker/CIK membership differs from configuration")
    if status.requested_companies != len(expected):
        raise ValueError("collection requested-company count differs from configuration")


def _collection_company_sources(
    collection_manifest: Path, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    companies = payload.get("companies")
    if not isinstance(companies, list):
        raise TypeError("collection manifest companies are malformed")
    sources: list[dict[str, Any]] = []
    for company in companies:
        if not isinstance(company, dict) or type(company.get("ticker")) is not str:
            raise ValueError("collection company identity is malformed")
        ticker = company["ticker"]
        root = collection_manifest.parent / "companies" / ticker
        entry: dict[str, Any] = {
            "ticker": ticker,
            "cik": company.get("cik"),
            "plan_status": company.get("plan_status"),
            "plan": None,
        }
        plan_path = root / "plan.json"
        if company.get("plan_status") == "PREPARED":
            plan = _contained_file(
                collection_manifest.parent,
                Path("companies") / ticker / "plan.json",
                f"{ticker} collection plan",
            )
            if company.get("plan_sha256") != _sha256(plan):
                raise ValueError(f"collection plan digest changed: {ticker}")
            entry["plan"] = _source(plan)
        elif plan_path.exists() or plan_path.is_symlink():
            entry["plan"] = _source(
                _contained_file(
                    collection_manifest.parent,
                    Path("companies") / ticker / "plan.json",
                    f"{ticker} failed collection plan",
                )
            )
        intake = root / "intake/history_intake.json"
        if intake.exists() or intake.is_symlink():
            entry["intake"] = _source(
                _contained_file(
                    collection_manifest.parent,
                    Path("companies") / ticker / "intake/history_intake.json",
                    f"{ticker} intake manifest",
                )
            )
        marker = root / "build_manifest.json"
        if marker.exists() or marker.is_symlink():
            marker = _contained_file(
                collection_manifest.parent,
                Path("companies") / ticker / "build_manifest.json",
                f"{ticker} build manifest",
            )
            marker_payload = _read_json(marker)
            entry["build"] = {
                **_source(marker),
                "status": marker_payload.get("status"),
                "publication": marker_payload.get("publication"),
                "history_manifest": marker_payload.get("history_manifest"),
                "history_manifest_sha256": marker_payload.get("history_manifest_sha256"),
            }
        sources.append(entry)
    if len(sources) != len({row["ticker"] for row in sources}):
        raise ValueError("collection source identities contain duplicate tickers")
    return sources


def _validate_q4_scope(
    derived: tuple[dict[str, Any], ...],
    configured_ticker_ciks: dict[str, str],
) -> None:
    if any(row.get("ticker") not in configured_ticker_ciks for row in derived):
        raise ValueError("reviewed-Q4 publication contains a foreign ticker")
    if any(
        row.get("cik") != configured_ticker_ciks.get(str(row.get("ticker")))
        for row in derived
    ):
        raise ValueError("reviewed-Q4 ticker/CIK differs from configuration")
    ticker_ciks: dict[str, str] = {}
    for row in derived:
        previous = ticker_ciks.setdefault(str(row["ticker"]), str(row["cik"]))
        if previous != row["cik"]:
            raise ValueError("reviewed-Q4 ticker resolves to more than one CIK")


def _attest_analysis(root: Path, *, expected_mode: str) -> _AnalysisAttestation:
    root = _real_directory(root, f"{expected_mode.lower()} analysis")
    manifest_path = _regular_file(root / "analysis_manifest.json", "analysis manifest")
    manifest = _read_json(manifest_path)
    if manifest.get("version") != analysis.VERSION:
        raise ValueError("unsupported prepared analysis publication")
    period_mode = manifest.get("period_mode", "QUARTERLY")
    if period_mode != expected_mode:
        raise ValueError(f"prepared analysis period mode is not {expected_mode}")
    publication_id = manifest.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id:
        raise ValueError("prepared analysis publication ID is missing")
    companies = manifest.get("companies")
    if not isinstance(companies, dict) or not companies:
        raise ValueError("prepared analysis contains no companies")
    if len(companies) != len(set(companies)) or any(
        type(ticker) is not str or ticker != ticker.upper() for ticker in companies
    ):
        raise ValueError("prepared analysis company identity is invalid")
    client = analysis.open_analysis(root)
    declared_paths: set[str] = set()
    as_of_dates: set[str] = set()
    source_publications: set[str] = set()
    for ticker, info in companies.items():
        if not isinstance(info, dict) or client.target_status(ticker).get("status") != "READY":
            raise ValueError(f"prepared analysis company is not READY: {ticker}")
        as_of = info.get("as_of")
        if type(as_of) is not str or not as_of:
            raise ValueError(f"prepared analysis selection as-of is missing: {ticker}")
        as_of_dates.add(as_of)
        source = _real_directory(Path(info.get("source_publication", "")), "analysis source")
        source_manifest = _regular_file(source / "history_manifest.json", "history manifest")
        expected_source_sha = manifest.get("source_manifest_hashes", {}).get(
            "history_manifest_sha256"
        )
        if expected_source_sha != _sha256(source_manifest):
            raise ValueError("prepared analysis source history identity changed")
        source_publications.add(str(source))
        views = info.get("views")
        if not isinstance(views, dict) or set(views) != {"AS_FILED", "LATEST_REPORTED"}:
            raise ValueError(f"prepared analysis views are incomplete: {ticker}")
        for view in views.values():
            files = view.get("files") if isinstance(view, dict) else None
            if not isinstance(files, dict) or not files:
                raise ValueError(f"prepared analysis declares no datasets: {ticker}")
            for file_info in files.values():
                relative = _verify_parquet(root, file_info)
                if relative in declared_paths:
                    raise ValueError("prepared analysis repeats a dataset path")
                declared_paths.add(relative)
    return _AnalysisAttestation(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_path),
        publication_id=publication_id,
        period_mode=period_mode,
        companies=tuple(sorted(companies)),
        selection_as_of_dates=tuple(sorted(as_of_dates)),
        source_publications=tuple(sorted(source_publications)),
        manifest=manifest,
    )


def _verify_parquet(root: Path, info: Any) -> str:
    if not isinstance(info, dict) or type(info.get("path")) is not str:
        raise ValueError("prepared analysis dataset declaration is malformed")
    relative = Path(info["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("prepared analysis dataset path is unsafe")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("prepared analysis dataset traverses a symlink")
    path = _regular_file(root / relative, "prepared analysis dataset")
    if not path.resolve().is_relative_to(root):
        raise ValueError("prepared analysis dataset escapes its publication")
    if info.get("sha256") != _sha256(path):
        raise ValueError("prepared analysis dataset digest changed")
    count = info.get("count")
    if type(count) is not int or count < 0:
        raise ValueError("prepared analysis dataset count is invalid")
    try:
        actual = pl.scan_parquet(path).select(pl.len()).collect().item()
    except Exception as exc:
        raise ValueError("prepared analysis dataset is not readable Parquet") from exc
    if actual != count:
        raise ValueError("prepared analysis dataset count changed")
    return str(relative)


def _validate_c_analysis_links(
    *,
    q4_root: Path | None,
    q4_manifest: dict[str, Any] | None,
    q4_derived: tuple[dict[str, Any], ...],
    quarterly: _AnalysisAttestation | None,
    annual: _AnalysisAttestation | None,
    configured_tickers: set[str],
) -> None:
    for publication in (quarterly, annual):
        if publication is not None and set(publication.companies) - configured_tickers:
            raise ValueError("prepared analysis contains a foreign configured ticker")
    q4_tickers = {str(row["ticker"]) for row in q4_derived}
    if quarterly is not None:
        reviewed = quarterly.manifest.get("reviewed_q4")
        if q4_manifest is None or q4_root is None or not isinstance(reviewed, dict):
            raise ValueError("quarterly analysis lacks its declared reviewed-Q4 identity")
        if Path(reviewed.get("publication", "")).resolve() != q4_root.resolve():
            raise ValueError("quarterly analysis references another reviewed-Q4 publication")
        if reviewed.get("publication_id") != q4_manifest.get("publication_id"):
            raise ValueError("quarterly analysis reviewed-Q4 publication ID differs")
        if reviewed.get("review_cutoff") != q4_manifest.get("review_cutoff"):
            raise ValueError("quarterly analysis reviewed-Q4 cutoff differs")
        q4_manifest_path = _regular_file(q4_root / "reviewed_q4_manifest.json", "Q4 manifest")
        if reviewed.get("manifest_sha256") != _sha256(q4_manifest_path):
            raise ValueError("quarterly analysis reviewed-Q4 manifest digest differs")
        if not q4_tickers.issubset(quarterly.companies):
            raise ValueError("quarterly analysis omits a reviewed-Q4 company")
    if annual is not None:
        if annual.manifest.get("reviewed_q4") is not None:
            raise ValueError("annual analysis must remain separate from reviewed Q4")
        if not q4_tickers.issubset(annual.companies):
            raise ValueError("annual analysis omits a reviewed-Q4 company")
    if q4_manifest is not None:
        selection_dates = tuple(sorted(q4_manifest.get("selection_as_of_dates", [])))
        for publication in (quarterly, annual):
            if publication is not None and publication.selection_as_of_dates != selection_dates:
                raise ValueError("prepared analysis selection as-of differs from reviewed Q4")
        expected_history = str(Path(q4_manifest["history_publication"]).resolve())
        for publication in (quarterly, annual):
            if publication is not None and publication.source_publications != (expected_history,):
                raise ValueError("prepared analysis source history differs from reviewed Q4")


def _readiness_model(
    *,
    config_path: Path,
    config: Any,
    collection_manifest: Path,
    collection_request: Path,
    collection_company_sources: list[dict[str, Any]],
    collection_status: Any,
    metadata: CompanyMetadataReader,
    metadata_rows: tuple[Any, ...],
    metadata_by_cik: dict[str, Any],
    q4_root: Path | None,
    q4_manifest: dict[str, Any] | None,
    q4_derived: tuple[dict[str, Any], ...],
    q4_exclusions: tuple[dict[str, Any], ...],
    quarterly: _AnalysisAttestation | None,
    annual: _AnalysisAttestation | None,
    expected_q4_economic_cells: int,
    expected_q4_view_records: int,
) -> dict[str, Any]:
    status_by_ticker = {row.ticker: row for row in collection_status.companies}
    q4_tickers = {str(row["ticker"]) for row in q4_derived}
    quarterly_tickers = set(quarterly.companies) if quarterly else set()
    annual_tickers = set(annual.companies) if annual else set()
    companies: list[dict[str, Any]] = []
    for target in config.companies:
        collection = status_by_ticker[target.ticker]
        master = metadata_by_cik[str(target.cik)]
        peers = metadata.peer_candidates(str(target.cik))
        q4_state = "REVIEWED_SCOPE" if target.ticker in q4_tickers else "OUTSIDE_REVIEWED_Q4_SCOPE"
        quarterly_state = "READY" if target.ticker in quarterly_tickers else "NOT_PREPARED"
        annual_state = "READY" if target.ticker in annual_tickers else "NOT_PREPARED"
        if collection.state not in {"RAW_COMPLETE", "READY"}:
            assessment = "RAW_PENDING" if "FAILED" not in collection.state else "RAW_FAILED"
        elif master.sic_code is None:
            assessment = "INDUSTRY_NOT_CLASSIFIED"
        elif target.ticker in q4_tickers and (quarterly_state != "READY" or annual_state != "READY"):
            assessment = "ANALYSIS_PENDING"
        elif target.ticker in q4_tickers:
            assessment = "ANALYSIS_PREPARED"
        else:
            assessment = "RAW_METADATA_READY"
        companies.append(
            {
                "ticker": target.ticker,
                "metadata_tickers": list(master.tickers),
                "cik": str(target.cik),
                "name": master.name,
                "groups": list(target.groups),
                "sic_code": master.sic_code,
                "sic_description": master.sic_description,
                "metadata_status": master.metadata_status,
                "industry_status": "CLASSIFIED" if master.sic_code is not None else "NOT_CLASSIFIED",
                "sic_peer_candidate_count": len(peers),
                "sic_peer_candidates": [
                    {
                        "cik": peer.cik,
                        "name": peer.name,
                        "tickers": list(peer.tickers),
                    }
                    for peer in peers
                ],
                "collection_state": collection.state,
                "collection_capability": collection.capability,
                "collection_action": collection.action,
                "selected_filings": collection.selected_filings,
                "held_filings": collection.held_filings,
                "pending_filings": collection.pending_filings,
                "failed_filings": collection.failed_filings,
                "report_start": collection.report_start,
                "report_end": collection.report_end,
                "q4_scope": q4_state,
                "quarterly_analysis": quarterly_state,
                "annual_analysis": annual_state,
                "assessment_state": assessment,
            }
        )
    if len(companies) != len({row["cik"] for row in companies}):
        raise ValueError("completion report would contain duplicate company rows")

    economic_keys = {
        (
            row.get("ticker"),
            row.get("cik"),
            row.get("fiscal_year"),
            row.get("member_qname"),
            row.get("mapping_epoch"),
            json.dumps(row.get("canonical_dimension_signature"), sort_keys=True),
            row.get("value_numeric"),
        )
        for row in q4_derived
    }
    q4_count_ready = (
        len(q4_derived) == expected_q4_view_records
        and len(economic_keys) == expected_q4_economic_cells
    )
    raw_complete = all(
        row["collection_state"] in {"RAW_COMPLETE", "READY"} for row in companies
    )
    collection_ready = all(row["collection_state"] == "READY" for row in companies)
    metadata_ready = all(row["sic_code"] is not None for row in companies)
    q4_ready = (
        q4_manifest is not None
        and q4_count_ready
        and set(q4_manifest.get("views", [])) == {"AS_FILED", "LATEST_REPORTED"}
        and all(row.get("status") == "DERIVED" for row in q4_derived)
    )
    quarterly_ready = quarterly is not None
    annual_ready = annual is not None
    failed = any(row["assessment_state"] == "RAW_FAILED" for row in companies)
    overall = (
        "FAILED"
        if failed
        else "READY"
        if collection_ready and metadata_ready and q4_ready and quarterly_ready and annual_ready
        else "PARTIAL"
    )
    classified = sum(row.sic_code is not None for row in metadata_rows)
    metadata_manifest = metadata.manifest
    q4_rows = [
        {
            "ticker": row.get("ticker"),
            "cik": row.get("cik"),
            "selection_view": row.get("selection_view"),
            "selection_as_of_date": row.get("selection_as_of_date"),
            "fiscal_year": row.get("fiscal_year"),
            "member_qname": row.get("member_qname"),
            "value_numeric": row.get("value_numeric"),
            "status": row.get("status"),
            "review_id": row.get("review_id"),
            "source_accessions": row.get("source_accessions"),
            "source_snapshot_ids": row.get("source_snapshot_ids"),
            "source_fact_ids": row.get("source_fact_ids"),
        }
        for row in sorted(
            q4_derived,
            key=lambda item: (
                str(item.get("ticker")),
                int(item.get("fiscal_year", 0)),
                str(item.get("member_qname")),
                str(item.get("selection_view")),
            ),
        )
    ]
    exclusion_rows = [
        {
            "ticker": row.get("ticker"),
            "selection_view": row.get("selection_view"),
            "fiscal_year": row.get("fiscal_year"),
            "member_qname": row.get("member_qname"),
            "reason": row.get("reason"),
            "detail": row.get("detail"),
        }
        for row in q4_exclusions
    ]
    return {
        "version": VERSION,
        "title": "기업·산업·원자료·분석준비·Q4범위",
        "universe_id": config.universe_id,
        "assessment_state": overall,
        "dates": {
            "financial_as_of": config.as_of_date.isoformat(),
            "collection_source_observed_at": config.source_observed_at,
            "metadata_cutoff": metadata_manifest.get("cutoff"),
            "metadata_observed_at": sorted(
                {
                    row.get("observed_at")
                    for row in metadata_manifest.get("selected_inputs", [])
                    if row.get("observed_at")
                }
            ),
            "metadata_candidate_inventory_observed_at": (
                metadata_manifest.get("candidate_inventory", {}).get("observed_at")
                if isinstance(metadata_manifest.get("candidate_inventory"), dict)
                else None
            ),
            "q4_selection_as_of_dates": (
                list(q4_manifest.get("selection_as_of_dates", [])) if q4_manifest else []
            ),
            "q4_review_cutoff": q4_manifest.get("review_cutoff") if q4_manifest else None,
        },
        "assessments": {
            "collection": {
                "state": (
                    "READY"
                    if collection_ready
                    else "RAW_COMPLETE"
                    if raw_complete
                    else "PARTIAL"
                ),
                "requested_companies": collection_status.requested_companies,
                "raw_complete_companies": collection_status.raw_complete_companies,
                "ready_companies": collection_status.ready_companies,
                "selected_filings": collection_status.selected_filings,
                "held_filings": collection_status.held_filings,
                "pending_filings": collection_status.pending_filings,
                "failed_filings": collection_status.failed_filings,
                "reused_filings": collection_status.reused_filings,
                "reused_interpretation": (
                    "REUSED는 이 최종 run에서 검증 후 채택한 상태이며, 원래 외부 baseline과 "
                    "신규 취득 건수를 뜻하지 않습니다."
                ),
            },
            "metadata": {
                "state": "READY" if metadata_ready else "PARTIAL",
                "candidate_issuers": len(metadata_rows),
                "classified_issuers": classified,
                "unclassified_issuers": len(metadata_rows) - classified,
                "pilot_companies": len(companies),
                "pilot_sic_classified": sum(row["sic_code"] is not None for row in companies),
                "coverage_note": "SEC SIC 미분류 후보도 회사 마스터에 유지됩니다.",
            },
            "reviewed_q4": {
                "state": "READY" if q4_ready else "PENDING",
                "expected_economic_cells": expected_q4_economic_cells,
                "economic_cells": len(economic_keys),
                "expected_view_records": expected_q4_view_records,
                "view_records": len(q4_derived),
                "exclusions": len(q4_exclusions),
            },
            "quarterly_analysis": {
                "state": "READY" if quarterly_ready else "PENDING",
                "companies": list(quarterly.companies) if quarterly else [],
                "period_mode": quarterly.period_mode if quarterly else None,
            },
            "annual_analysis": {
                "state": "READY" if annual_ready else "PENDING",
                "companies": list(annual.companies) if annual else [],
                "period_mode": annual.period_mode if annual else None,
            },
        },
        "sources": {
            "config": _source(config_path),
            "collection_manifest": _source(collection_manifest),
            "collection_request": _source(collection_request),
            "collection_companies": collection_company_sources,
            "metadata": {
                **_source(metadata.manifest_path),
                "root": str(metadata.root),
                "publication_id": metadata.publication_id,
            },
            "reviewed_q4": _optional_publication_source(q4_root, q4_manifest),
            "quarterly_analysis": _analysis_source(quarterly),
            "annual_analysis": _analysis_source(annual),
        },
        "companies": companies,
        "reviewed_q4": {
            "rows": q4_rows,
            "exclusions": exclusion_rows,
            "scope_note": "승인된 정확한 FY/YTD-9M 원천쌍만 표시하며 HTML에서 Q4를 계산하지 않습니다.",
        },
        "warnings": [
            "재무 수집 기준일, SEC 메타데이터 관측시각, 분석 선택 기준일, Q4 검토시각은 서로 다른 provenance입니다.",
            "서로 다른 기준일의 값을 동일 기준 횡단면처럼 비교하지 않습니다.",
            "SEC SIC는 동종 후보 신호이며 회계적 동등성을 뜻하지 않습니다.",
            "미검토 segment/geography 및 mapping epoch 범위는 보류 상태로 남습니다.",
            "최종 run의 REUSED 수와 최초 외부 baseline·신규 취득 이력은 서로 다른 provenance입니다.",
        ],
    }


def _optional_publication_source(
    root: Path | None, manifest: dict[str, Any] | None
) -> dict[str, Any] | None:
    if root is None or manifest is None:
        return None
    path = _regular_file(root / "reviewed_q4_manifest.json", "Q4 manifest")
    return {
        **_source(path),
        "root": str(root.resolve()),
        "publication_id": manifest.get("publication_id"),
        "history_publication": manifest.get("history_publication"),
        "history_manifest_sha256": manifest.get("history_manifest_sha256"),
        "source_evidence_path": manifest.get("source_evidence_path"),
        "source_evidence_sha256": manifest.get("source_evidence_sha256"),
        "review_ledger_path": manifest.get("review_ledger_path"),
        "review_ledger_sha256": manifest.get("review_ledger_sha256"),
        "source_snapshots": manifest.get("source_snapshots", []),
    }


def _analysis_source(value: _AnalysisAttestation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "root": str(value.root),
        "manifest_path": str(value.manifest_path),
        "manifest_sha256": value.manifest_sha256,
        "publication_id": value.publication_id,
        "period_mode": value.period_mode,
        "selection_as_of_dates": list(value.selection_as_of_dates),
        "source_publications": list(value.source_publications),
    }


def _source(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _publish(report: dict[str, Any], destination: Path) -> UniverseDeliveryPublication:
    _safe_new_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        json_path = staging / READINESS_JSON
        csv_path = staging / READINESS_CSV
        html_path = staging / REPORT_HTML
        readme_path = staging / REPRO_README
        json_path.write_text(_json(report) + "\n", encoding="utf-8")
        _write_csv(csv_path, report["companies"])
        html_path.write_text(_render_html(report), encoding="utf-8")
        readme_path.write_text(_render_readme(report), encoding="utf-8")
        files = {
            path.name: {"sha256": _sha256(path), "size": path.stat().st_size}
            for path in (json_path, csv_path, html_path, readme_path)
        }
        identity = {
            "version": VERSION,
            "universe_id": report["universe_id"],
            "assessment_state": report["assessment_state"],
            "sources": report["sources"],
            "files": files,
        }
        publication_id = "universe-delivery-" + hashlib.sha256(
            _json(identity).encode("utf-8")
        ).hexdigest()[:24]
        manifest = {**identity, "publication_id": publication_id}
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(_json(manifest) + "\n", encoding="utf-8")
        UniverseDeliveryReader(staging, allow_staging=True)
        os.rename(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    reader = UniverseDeliveryReader(destination)
    return UniverseDeliveryPublication(
        root=destination,
        publication_id=reader.publication_id,
        manifest_path=destination / MANIFEST_NAME,
        readiness_json=destination / READINESS_JSON,
        readiness_csv=destination / READINESS_CSV,
        report_html=destination / REPORT_HTML,
        readme=destination / REPRO_README,
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "ticker",
        "cik",
        "name",
        "sic_code",
        "sic_description",
        "sic_peer_candidate_count",
        "collection_state",
        "selected_filings",
        "held_filings",
        "pending_filings",
        "q4_scope",
        "quarterly_analysis",
        "annual_analysis",
        "assessment_state",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _render_readme(report: dict[str, Any]) -> str:
    lines = [
        "# Company-universe completion publication",
        "",
        f"- Version: `{report['version']}`",
        f"- Universe: `{report['universe_id']}`",
        f"- Assessment: `{report['assessment_state']}`",
        f"- Financial as-of: `{report['dates']['financial_as_of']}`",
        "",
        "This directory was rendered offline from immutable prepared outputs. It does not",
        "collect SEC data, parse XBRL, select facts, or calculate Q4 values.",
        "",
        "## Inputs",
        "",
    ]
    for name, value in report["sources"].items():
        if isinstance(value, dict):
            path = value.get("root") or value.get("path")
            digest = value.get("manifest_sha256") or value.get("sha256")
            lines.append(f"- {name}: `{path}` (`{digest}`)")
        elif isinstance(value, list):
            lines.append(f"- {name}: {len(value)} per-company source attestations in JSON")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            "- `company_readiness.json`: complete joined data and source identities",
            "- `company_readiness.csv`: one row per configured CIK",
            "- `index.html`: Korean completion and scope view",
            "- `universe_delivery_manifest.json`: output hashes and publication identity",
            "",
            "The final-run REUSED count is replay/adoption provenance. Original baseline and",
            "new-acquisition history remains a separate runtime record.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_html(report: dict[str, Any]) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    assessments = report["assessments"]
    cards = "".join(
        f"<article><h2>{esc(label)}</h2><strong>{esc(value['state'])}</strong><p>{esc(detail)}</p></article>"
        for label, value, detail in (
            (
                "원자료 수집",
                assessments["collection"],
                f"회사 {assessments['collection']['raw_complete_companies']}/{assessments['collection']['requested_companies']} · 공시 {assessments['collection']['held_filings']}/{assessments['collection']['selected_filings']}",
            ),
            (
                "회사·산업",
                assessments["metadata"],
                f"후보 {assessments['metadata']['candidate_issuers']} · SIC 분류 {assessments['metadata']['classified_issuers']} · 미분류 {assessments['metadata']['unclassified_issuers']}",
            ),
            (
                "검토 Q4",
                assessments["reviewed_q4"],
                f"경제값 {assessments['reviewed_q4']['economic_cells']}/{assessments['reviewed_q4']['expected_economic_cells']} · view 기록 {assessments['reviewed_q4']['view_records']}/{assessments['reviewed_q4']['expected_view_records']}",
            ),
            (
                "분기 분석",
                assessments["quarterly_analysis"],
                f"준비 회사 {len(assessments['quarterly_analysis']['companies'])}",
            ),
            (
                "연간 분석",
                assessments["annual_analysis"],
                f"준비 회사 {len(assessments['annual_analysis']['companies'])}",
            ),
        )
    )
    company_rows = "".join(
        "<tr>"
        f"<td>{esc(row['ticker'])}</td><td>{esc(row['cik'])}</td><td>{esc(row['name'])}</td>"
        f"<td>{esc(row['sic_code'])} {esc(row['sic_description'])}<br>동일 SIC 후보 {row['sic_peer_candidate_count']}개</td>"
        f"<td>{esc(row['collection_state'])}</td><td>{row['held_filings']}/{row['selected_filings']}</td>"
        f"<td>{esc(row['q4_scope'])}</td><td>{esc(row['quarterly_analysis'])}</td>"
        f"<td>{esc(row['annual_analysis'])}</td><td>{esc(row['assessment_state'])}</td>"
        "</tr>"
        for row in report["companies"]
    )
    q4_rows = "".join(
        "<tr>"
        f"<td>{esc(row['ticker'])}</td><td>{esc(row['selection_view'])}</td>"
        f"<td>FY{esc(row['fiscal_year'])} Q4</td><td>{esc(row['member_qname'])}</td>"
        f"<td>{esc(row['value_numeric'])}</td><td>{esc(row['status'])}</td>"
        f"<td>{esc(', '.join(row['source_accessions'] or []))}</td>"
        "</tr>"
        for row in report["reviewed_q4"]["rows"]
    ) or '<tr><td colspan="7">준비된 검토 Q4 publication이 없습니다.</td></tr>'
    exclusion_rows = "".join(
        "<li>"
        f"{esc(row['ticker'] or '정책')} · {esc(row['selection_view'])} · "
        f"FY{esc(row['fiscal_year'])} · {esc(row['member_qname'])}: {esc(row['reason'])}"
        "</li>"
        for row in report["reviewed_q4"]["exclusions"]
    ) or "<li>기록된 제외 범위 없음</li>"
    warnings = "".join(f"<li>{esc(value)}</li>" for value in report["warnings"])
    dates = report["dates"]
    date_rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"
        for label, value in (
            ("재무 수집 기준일", dates["financial_as_of"]),
            ("수집 source 관측시각", dates["collection_source_observed_at"]),
            ("메타데이터 cutoff", dates["metadata_cutoff"] or "미지정"),
            ("메타데이터 관측시각", ", ".join(dates["metadata_observed_at"])),
            (
                "후보 inventory 관측시각",
                dates["metadata_candidate_inventory_observed_at"] or "미지정",
            ),
            ("분석 선택 기준일", ", ".join(dates["q4_selection_as_of_dates"])),
            ("Q4 검토 cutoff", dates["q4_review_cutoff"] or "미지정"),
        )
    )
    sources = "".join(
        f"<tr><th>{esc(name)}</th><td><code>{esc(value.get('root') or value.get('path'))}</code></td>"
        f"<td><code>{esc(value.get('manifest_sha256') or value.get('sha256'))}</code></td></tr>"
        for name, value in report["sources"].items()
        if isinstance(value, dict)
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(report['title'])}</title><style>
body{{font-family:system-ui,sans-serif;margin:2rem;background:#f4f6f8;color:#17202a}}main{{max-width:1500px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}}article,section{{background:white;border:1px solid #dfe5eb;border-radius:10px;padding:1rem;margin:1rem 0}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}th,td{{border-bottom:1px solid #e7ebef;padding:.55rem;text-align:left;vertical-align:top}}th{{background:#f8fafc}}code{{word-break:break-all}}.warning{{border-left:5px solid #c47b00}}
</style></head><body><main>
<h1>{esc(report['title'])}</h1><p>전체 판정: <strong>{esc(report['assessment_state'])}</strong></p>
<div class="cards">{cards}</div>
<section class="warning"><h2>기준일을 분리해서 읽기</h2><ul>{warnings}</ul>
<table><tbody>{date_rows}</tbody></table></section>
<section><h2>기업·산업·원자료·분석준비</h2><table><thead><tr><th>티커</th><th>CIK</th><th>회사</th><th>SEC SIC</th><th>원자료</th><th>보유/선택</th><th>Q4 범위</th><th>분기</th><th>연간</th><th>판정</th></tr></thead><tbody>{company_rows}</tbody></table></section>
<section><h2>검토된 Q4 범위</h2><p>{esc(report['reviewed_q4']['scope_note'])}</p><table><thead><tr><th>회사</th><th>선택 view</th><th>기간</th><th>구성원</th><th>값</th><th>상태</th><th>원천 accession</th></tr></thead><tbody>{q4_rows}</tbody></table></section>
<section><h2>검토 보류·제외 범위</h2><ul>{exclusion_rows}</ul></section>
<section><h2>Publication source identity</h2><table><tbody>{sources}</tbody></table></section>
</main></body></html>"""


def _safe_new_destination(destination: Path) -> None:
    absolute = destination.absolute()
    for path in (absolute, *absolute.parents):
        if path.is_symlink():
            raise ValueError("completion destination traverses a symlink")
    if destination.exists():
        raise ValueError("completion publication requires a new destination")


def _real_directory(path: Path, label: str) -> Path:
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"{label} is not a real directory: {path}")
    return path.resolve()


def _regular_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path.resolve()


def _contained_file(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path is unsafe")
    root = root.resolve()
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    path = _regular_file(root / relative, label)
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes its publication")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--collection-manifest", type=Path, required=True)
    parser.add_argument("--metadata-publication", type=Path, required=True)
    parser.add_argument("--reviewed-q4-publication", type=Path)
    parser.add_argument("--quarterly-analysis", type=Path)
    parser.add_argument("--annual-analysis", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-q4-economic-cells", type=int, default=16)
    parser.add_argument("--expected-q4-view-records", type=int, default=32)
    args = parser.parse_args()
    publication = publish_universe_delivery(
        config_path=args.config,
        collection_manifest=args.collection_manifest,
        metadata_publication=args.metadata_publication,
        reviewed_q4_publication=args.reviewed_q4_publication,
        quarterly_analysis=args.quarterly_analysis,
        annual_analysis=args.annual_analysis,
        destination=args.destination,
        expected_q4_economic_cells=args.expected_q4_economic_cells,
        expected_q4_view_records=args.expected_q4_view_records,
    )
    print(publication.report_html)


if __name__ == "__main__":
    main()
