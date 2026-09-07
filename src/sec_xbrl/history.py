"""Resumable company-history intake and publication, using the existing engines.

Run ``python -m sec_xbrl.history --help`` for the staged command interface.
SEC identity is supplied only through SEC_USER_AGENT at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Any

from sec_xbrl.filing.company_discovery import (
    SUPPORTED_FORMS,
    CompanySubmissionsAccessionProvider,
    CompanySubmissionsCollector,
    DiscoveryStateStore,
    SECSubmissionsClient,
    SubmissionsSnapshotStore,
    canonicalize_cik,
)
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndexCache, FilingPackageResolver
from sec_xbrl.filing.layer1_ingestion import Layer1Ingestor
from sec_xbrl.filing.package_cache import AccessionPackageCache, SECArchiveClient
from sec_xbrl.filing.trailing_corpus import select_trailing_fiscal_filings
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot

HISTORY_VERSION = "company-history-v1"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ref_record(ref: FilingRef) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(ref), default=str))


def _read_ref(row: dict[str, Any]) -> FilingRef:
    return FilingRef(**{**row, "filed_date": date.fromisoformat(row["filed_date"]),
                       "report_date": date.fromisoformat(row["report_date"]) if row.get("report_date") else None})


def _user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value:
        raise ValueError("SEC_USER_AGENT environment variable is required for network requests")
    return value


def select_history_filings(refs: tuple[FilingRef, ...], *, as_of: date,
                           report_start: date | None = None, report_end: date | None = None,
                           recent_fiscal_years: int | None = None) -> tuple[FilingRef, ...]:
    """Use explicit actual report dates, or the existing annual-baseline policy."""
    if (recent_fiscal_years is not None and (report_start is not None or report_end is not None)) or (
        recent_fiscal_years is None and (report_start is None or report_end is None)
    ):
        raise ValueError("provide report_start/report_end or recent_fiscal_years, exclusively")
    eligible = tuple(ref for ref in refs if ref.filed_date <= as_of)
    if recent_fiscal_years is not None:
        return select_trailing_fiscal_filings(eligible, fiscal_years=recent_fiscal_years)[0]
    if report_start > report_end:
        raise ValueError("report_start must not exceed report_end")
    return tuple(ref for ref in eligible if ref.report_date is not None and report_start <= ref.report_date <= report_end)


def discover_history(*, workspace: Path, tickers: tuple[str, ...], as_of: date,
                     submissions_roots: tuple[Path, ...] = (), offline: bool = False,
                     report_start: date | None = None, report_end: date | None = None,
                     recent_fiscal_years: int | None = None) -> Path:
    """Resolve arbitrary tickers from SEC payloads, then reuse Filing Discovery."""
    requested = tuple(dict.fromkeys(ticker.strip().upper() for ticker in tickers))
    if not requested or any(not ticker for ticker in requested):
        raise ValueError("at least one ticker is required")
    roots = submissions_roots + (workspace / "submissions",)
    by_cik: dict[str, list[Path]] = defaultdict(list)
    companies: dict[str, dict[str, str]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not isinstance(payload, dict):
                continue
            raw_cik = payload.get("cik")
            if raw_cik is None and path.parent.name.isdigit():
                raw_cik = path.parent.name
            if raw_cik is None or not ("filings" in payload or "accessionNumber" in payload):
                continue
            cik = canonicalize_cik(raw_cik)
            by_cik[cik].append(path)
            for ticker in payload.get("tickers", []):
                if ticker.upper() in requested:
                    companies[ticker.upper()] = {"cik": cik, "ticker": ticker.upper(), "name": payload.get("name", "")}
    client = None
    missing = set(requested) - set(companies)
    if missing and not offline:
        client = SECSubmissionsClient(user_agent=_user_agent())
        ticker_path = workspace / "company_tickers.json"
        if not ticker_path.exists():
            payload = json.loads(client.fetch("https://www.sec.gov/files/company_tickers.json"))
            _write_json(ticker_path, payload)
        for row in json.loads(ticker_path.read_text()).values():
            if row["ticker"].upper() in missing:
                ticker = row["ticker"].upper()
                companies[ticker] = {"cik": canonicalize_cik(row["cik_str"]), "ticker": ticker, "name": row["title"]}
    if set(requested) - set(companies):
        raise ValueError("ticker resolution unavailable: " + ", ".join(sorted(set(requested) - set(companies))))
    records = []
    for ticker in requested:
        company = companies[ticker]
        cik = company["cik"]
        if not offline:
            client = client or SECSubmissionsClient(user_agent=_user_agent())
            by_cik[cik] = list(CompanySubmissionsCollector(client, SubmissionsSnapshotStore(workspace / "submissions"),
                                                        DiscoveryStateStore(workspace / "discovery_state")).collect(cik))
        refs = tuple(CompanySubmissionsAccessionProvider(by_cik[cik], cik=cik).iter_filings(forms=set(SUPPORTED_FORMS)))
        selected = select_history_filings(refs, as_of=as_of, report_start=report_start,
                                          report_end=report_end, recent_fiscal_years=recent_fiscal_years)
        if not selected:
            raise ValueError(f"no filings in requested history: {ticker}")
        records.append({**company, "submissions": [str(path.absolute()) for path in by_cik[cik]],
                        "filings": [_ref_record(ref) for ref in selected]})
    result = workspace / "plan.json"
    payload = {"version": HISTORY_VERSION, "as_of_date": as_of.isoformat(),
               "report_start": report_start, "report_end": report_end,
               "recent_fiscal_years": recent_fiscal_years, "companies": records}
    if result.exists() and json.loads(result.read_text()) != json.loads(json.dumps(payload, default=str)):
        raise ValueError("history plan already exists with different scope; choose a new workspace")
    _write_json(result, payload)
    return result


def ingest_history(*, plan_path: Path, source_runs: tuple[Path, ...], output_run: Path,
                   package_cache: Path, index_cache: Path, taxonomy_cache: Path,
                   bootstrap_taxonomy: bool = False) -> Path:
    """Resume per accession; accepted snapshots are verified in place and reused."""
    plan = json.loads(plan_path.read_text())
    manifest_path = output_run / "history_intake.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["plan"] != plan:
        raise ValueError("intake run belongs to a different plan")
    if manifest_path.exists():
        _write_json(output_run / "history_attempts" / f"manifest-{uuid.uuid4().hex}.json",
                    json.loads(manifest_path.read_text()))
    outcomes = []
    roots = tuple(dict.fromkeys((*source_runs, output_run)))
    resolver = FilingPackageResolver(AccessionPackageCache(package_cache), FilingIndexCache(index_cache))
    ingestor = Layer1Ingestor(output_run / "snapshots")
    client = None
    for company in plan["companies"]:
        for record in company["filings"]:
            ref = _read_ref(record)
            outcome: dict[str, Any] = {"ticker": company["ticker"], "filing": record}
            try:
                existing = [root for root in roots if (root / "snapshots" / ref.cik / ref.accession.replace("-", "") / "layer1_manifest.json").exists()]
                if existing:
                    snapshots = [_load_declared_cohort_snapshot(root / "snapshots" / ref.cik / ref.accession.replace("-", ""), ref.cik, ref.accession) for root in existing]
                    for snapshot in snapshots:
                        _validate_snapshot_plan(snapshot, record)
                    if len({snapshot.input.manifest_sha256 for snapshot in snapshots}) > 1:
                        raise ValueError("multiple different snapshots exist for this accession")
                    source = existing[0]
                    outcome.update(status="REUSED", source_run=str(source.absolute()))
                else:
                    client = client or SECArchiveClient(user_agent=_user_agent())
                    resolved = resolver.resolve(ref, client)
                    extraction = output_run / "extracted" / ref.cik / ref.accession.replace("-", "") / uuid.uuid4().hex
                    loader = ArelleFilingLoader(taxonomy_cache=taxonomy_cache)
                    try:
                        ingestor.load_and_ingest(resolved, loader, extraction / "offline-first")
                    except Exception:
                        if not bootstrap_taxonomy:
                            raise
                        model = ArelleFilingLoader.bootstrap_taxonomy_cache(resolved, extraction / "bootstrap", taxonomy_cache)
                        try:
                            ingestor._validate_model(model)
                        finally:
                            model.close()
                        ingestor.load_and_ingest(resolved, loader, extraction / "offline-retry")
                    snapshot = _load_declared_cohort_snapshot(ingestor.snapshot_dir(resolved), ref.cik, ref.accession)
                    _validate_snapshot_plan(snapshot, record)
                    outcome.update(status="INGESTED", source_run=str(output_run.absolute()))
            except Exception as exc:  # noqa: BLE001 - accession-level resumable audit boundary
                outcome.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
            outcomes.append(outcome)
            _write_json(output_run / "history_attempts" / f"{uuid.uuid4().hex}.json", outcome)
            _write_json(manifest_path, {"version": HISTORY_VERSION, "plan": plan, "filings": outcomes,
                                       "complete": len(outcomes) == sum(len(c["filings"]) for c in plan["companies"])
                                       and all(row["status"] != "FAILED" for row in outcomes)})
            print(json.dumps({"ticker": company["ticker"], "accession": ref.accession, "status": outcome["status"],
                              "processed": len(outcomes)}, sort_keys=True), flush=True)
    return manifest_path


def _validate_snapshot_plan(snapshot: Any, record: dict[str, Any]) -> None:
    filings = snapshot.records("filing")
    if len(filings) != 1 or any(
        str(filings[0].get(key)) != str(record[key])
        for key in ("cik", "accession", "form", "filed_date", "report_date")
        if record.get(key) is not None
    ):
        raise ValueError("snapshot filing metadata disagrees with requested history plan")


def _validate_intake(intake: dict[str, Any]) -> None:
    expected = {(company["cik"], row["accession"]) for company in intake["plan"]["companies"] for row in company["filings"]}
    actual = [(row["filing"]["cik"], row["filing"]["accession"]) for row in intake["filings"]]
    if not intake.get("complete") or len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("all planned filings must be ingested before publishing history")
    if any(row["status"] not in {"REUSED", "INGESTED"} for row in intake["filings"]):
        raise ValueError("failed ingestion cannot be published as missing history")


def build_history(*, intake_manifest: Path, output_root: Path,
                  views: tuple[str, ...] = ("AS_FILED", "LATEST_REPORTED"), roots_only: bool = False) -> Path:
    """Publish all history once; materialize fiscal pivots for offline reload."""
    from sec_xbrl.analytics import (
        CompanyAnalysisPanelBuilder,
        FiscalTimeSeriesBuilder,
        FiscalTimeSeriesInput,
    )
    from sec_xbrl.longitudinal import (
        AccessionVersionLedgerPipeline,
        AccessionVersionLedgerReader,
        CohortReleaseAdapter,
        CohortSnapshotReference,
        CohortSource,
        ExplorationGraphPipeline,
        FilingRelationshipIndexPipeline,
        Layer2PublicationReader,
        Layer2RuleVersions,
        ReportedObservationSelector,
        VersionedObservationPanelPipeline,
    )
    if not views or len(set(views)) != len(views) or set(views) - {"AS_FILED", "LATEST_REPORTED"}:
        raise ValueError("views must be distinct AS_FILED/LATEST_REPORTED")
    intake = json.loads(intake_manifest.read_text())
    _validate_intake(intake)
    plan = intake["plan"]
    destination = output_root / "reported-panels"
    if destination.exists() and not roots_only:
        reader = HistoryPublicationReader(destination)
        if reader.manifest["plan"] != plan or tuple(reader.manifest["views"]) != views:
            raise ValueError("history publication scope differs; choose a new output root")
        reader.verify_all()
        from sec_xbrl.analytics.history_quarters import publish_quarter_history
        consumer = output_root / "panels"
        if consumer.exists():
            HistoryPublicationReader(consumer).verify_all()
            return consumer
        return publish_quarter_history(publication=destination, output_root=output_root, reuse_roots=True)
    grouped: dict[Path, list[Any]] = defaultdict(list)
    for item in intake["filings"]:
        grouped[Path(item["source_run"])].append(CohortSnapshotReference(item["filing"]["cik"], item["filing"]["accession"]))
    run_id = output_root.name
    release = CohortReleaseAdapter().load(
        tuple(CohortSource(root, root.name, tuple(refs)) for root, refs in grouped.items()),
        cohort_id=run_id, ciks=tuple(company["cik"] for company in plan["companies"]), run_version=run_id,
        rules=Layer2RuleVersions("period-fiscal-boundaries-v2", "mapping-v1", "recast-v1", "selection-v1"),
    )
    planned = {(item["filing"]["cik"], item["filing"]["accession"]): item["filing"] for item in intake["filings"]}
    for snapshot in release.snapshots:
        _validate_snapshot_plan(snapshot, planned[(snapshot.input.cik, snapshot.input.accession)])
    reader = Layer2PublicationReader()
    roots = {name: output_root / name / run_id for name in ("t1", "t2", "t3", "t4")}
    # Existing verified roots are reused without rerunning their producers.
    if not roots["t1"].exists():
        print(json.dumps({"stage": "BUILD_T1"}), flush=True)
        VersionedObservationPanelPipeline().publish(release, output_root=output_root / "t1")
    if not roots["t2"].exists():
        print(json.dumps({"stage": "BUILD_T2"}), flush=True)
        FilingRelationshipIndexPipeline().publish(release, output_root=output_root / "t2")
    observations = reader.load(roots["t1"])
    relationships = reader.load(roots["t2"])
    if not roots["t3"].exists():
        print(json.dumps({"stage": "BUILD_T3"}), flush=True)
        ExplorationGraphPipeline().publish(observations, relationships, output_root=output_root / "t3")
    if not roots["t4"].exists():
        print(json.dumps({"stage": "BUILD_T4"}), flush=True)
        AccessionVersionLedgerPipeline().publish(release, output_root=output_root / "t4")
    graph = reader.load(roots["t3"])
    ledger_pub = reader.load(roots["t4"])
    for publication in (observations, relationships, graph, ledger_pub):
        if publication.identity["layer2_run_fingerprint"] != release.layer2_run.fingerprint:
            raise ValueError("existing operational publication belongs to different raw inputs")
    print(json.dumps({"stage": "OPERATIONAL_ROOTS_READY", "filings": len(release.snapshots)}), flush=True)
    if roots_only:
        return output_root
    periods: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    comparative_counts: dict[str, int] = defaultdict(int)
    for row in observations.records("reported_period_observation"):
        if row.get("comparative_type") != "CURRENT_FOCUS":
            comparative_counts[str(row["cik"])] += 1
            continue
        periods[(row["cik"], row.get("fiscal_year"), row.get("fiscal_quarter"), row.get("period_class"))].append(row)
    filing_by_id = {str(row["filing_id"]): row for row in release.records("filing")}
    builder = CompanyAnalysisPanelBuilder()
    selector = ReportedObservationSelector()
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".panels.partial-", dir=output_root))
    tables = []
    for company in plan["companies"]:
        cik, ticker = company["cik"], company["ticker"]
        coverage_keys = _filing_coverage_keys(tuple(filing_by_id.values()), cik)
        ledger = AccessionVersionLedgerReader().get_company(ledger_pub, cik=cik)
        keys = sorted((key for key in periods if key[0] == cik and key[1] is not None), key=repr)
        for view in views:
            for period_class in sorted({key[3] for key in keys}):
                inputs = []
                scoped = [key for key in keys if key[3] == period_class]
                for _, year, quarter, _ in scoped:
                    selected = selector.select_period(
                        observations=periods[(cik, year, quarter, period_class)], ledger=ledger,
                        cik=cik, fiscal_year=year, fiscal_quarter=quarter, period_class=period_class,
                        as_of_date=plan["as_of_date"], view=view,
                    )
                    panel = builder.build(selected_rows=selected.rows, exploration=graph, cik=cik,
                                          fiscal_year=year, fiscal_quarter=quarter, period_class=period_class,
                                          view=view, as_of_date=plan["as_of_date"])
                    fiscal_ends = {filing_by_id[str(v["source_filing_id"])].get("fiscal_year_end")
                                   for v in panel.values if v.get("source_filing_id") in filing_by_id}
                    # DEI day may roll in 52/53-week years. Preserve uncertainty
                    # if distinct reported calendars occur in one selected panel.
                    fiscal_end = next(iter(fiscal_ends)) if len(fiscal_ends) == 1 else None
                    inputs.append(FiscalTimeSeriesInput(panel, fiscal_end))
                if not inputs:
                    continue
                expected = []
                if period_class == "QTD_3M":
                    expected = _expected_quarters(coverage_keys)
                result = FiscalTimeSeriesBuilder().build(inputs=inputs, expected_periods=expected)
                annual_years = {key[1] for key in coverage_keys if key[3] == "FY"}
                result = replace(result, columns=tuple(
                    {**column, "column_status": "UNAVAILABLE", "column_reason": "DERIVATION_NOT_MATERIALIZED",
                     "comparability_reason": "DERIVATION_NOT_MATERIALIZED"}
                    if column["column_status"] == "MISSING_HISTORY" and column["fiscal_quarter"] == 4
                    and column["fiscal_year"] in annual_years and period_class == "QTD_3M" else column
                    for column in result.columns
                ))
                relative = Path(cik) / view / period_class
                table = {"ticker": ticker, "cik": cik, "view": view, "period_class": period_class,
                         "scope": result.scope, "files": {}}
                for name in ("columns", "rows", "cells"):
                    path = staging / relative / f"{name}.parquet"
                    info = _write_records(path, getattr(result, name))
                    table["files"][name] = {**info, "path": str(relative / path.name)}
                tables.append(table)
                print(json.dumps({"stage": "PANEL_WRITTEN", "ticker": ticker, "view": view,
                                  "period_class": period_class, "rows": len(result.rows), "cells": len(result.cells)}), flush=True)
    manifest = {"version": HISTORY_VERSION, "plan": plan, "views": views, "tables": tables,
                "source_intake": str(intake_manifest.absolute()),
                "operational_roots": {key: str(path.absolute()) for key, path in roots.items()},
                "input_fingerprint": release.layer2_run.fingerprint,
                "comparative_scope": "CURRENT_FOCUS",
                "comparative_observations_retained_in_t1": dict(comparative_counts),
                "quarterly_derivation_status": "NOT_MATERIALIZED_REPORTED_SERIES_ONLY"}
    _write_json(staging / "history_manifest.json", manifest)
    # Audit the complete persisted output before its atomic publication.
    HistoryPublicationReader(staging, allow_staging=True).verify_all()
    staging.rename(destination)
    from sec_xbrl.analytics.history_quarters import publish_quarter_history
    return publish_quarter_history(publication=destination, output_root=output_root, reuse_roots=True)


def _expected_quarters(keys: list[tuple[Any, ...]]) -> list[Any]:
    """No future quarters for an incomplete fiscal year."""
    from sec_xbrl.analytics import FiscalPeriod
    annual = {key[1] for key in keys if key[3] == "FY"}
    latest: dict[int, int] = {}
    for _, year, quarter, _ in keys:
        if year is not None and quarter in (1, 2, 3, 4):
            latest[year] = max(latest.get(year, 0), quarter)
    return [FiscalPeriod(year, quarter, "QTD_3M")
            for year in sorted(set(latest) | annual)
            for quarter in range(1, (4 if year in annual else latest[year]) + 1)]


def _filing_coverage_keys(filings: tuple[dict[str, Any], ...], cik: str) -> list[tuple[Any, ...]]:
    """Coverage is filing focus, never the duration of a note fact."""
    keys = []
    for filing in filings:
        if filing.get("cik") != cik:
            continue
        year = filing.get("document_fiscal_year_focus")
        focus = filing.get("document_fiscal_period_focus")
        form = str(filing.get("form", "")).removesuffix("/A")
        if year is None or not str(year).isdigit():
            continue
        if form == "10-K" and focus == "FY":
            keys.append((cik, int(year), 4, "FY"))
        elif form == "10-Q" and focus in {"Q1", "Q2", "Q3", "Q4"}:
            keys.append((cik, int(year), int(focus[1]), "QTD_3M"))
    return keys


def repair_history_coverage(*, publication: Path, destination: Path) -> Path:
    """Republish only corrected empty coverage columns; never reselect a value."""
    reader = HistoryPublicationReader(publication)
    reader.verify_all()
    if destination.exists():
        raise ValueError("coverage repair requires a new immutable destination")
    intake = json.loads(Path(reader.manifest["source_intake"]).read_text())
    _validate_intake(intake)
    if intake["plan"] != reader.manifest["plan"]:
        raise ValueError("coverage repair intake disagrees with original publication")
    filings = []
    for item in intake["filings"]:
        record = item["filing"]
        directory = Path(item["source_run"]) / "snapshots" / record["cik"] / record["accession"].replace("-", "")
        snapshot = _load_declared_cohort_snapshot(directory, record["cik"], record["accession"])
        _validate_snapshot_plan(snapshot, record)
        filings.extend(snapshot.records("filing"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".panels.partial-", dir=destination.parent))
    tables, removed = [], []
    for table in reader.manifest["tables"]:
        result = reader.load(ticker=table["ticker"], period_class=table["period_class"], view=table["view"])
        if table["period_class"] == "QTD_3M":
            expected = {(p.fiscal_year, p.fiscal_quarter) for p in _expected_quarters(_filing_coverage_keys(tuple(filings), table["cik"]))}
            remove_ids = {column["fiscal_time_series_column_id"] for column in result.columns
                          if (column["fiscal_year"], column["fiscal_quarter"]) not in expected
                          and column["column_status"] in {"MISSING_HISTORY", "UNAVAILABLE"}}
            if any(cell["fiscal_time_series_column_id"] in remove_ids for cell in result.cells):
                raise ValueError("coverage repair cannot discard any materialized cell")
            removed.extend({"ticker": table["ticker"], "view": table["view"], **column}
                           for column in result.columns if column["fiscal_time_series_column_id"] in remove_ids)
            result = replace(result, columns=tuple(column for column in result.columns if column["fiscal_time_series_column_id"] not in remove_ids))
        updated = {**table, "files": {}}
        for name in ("columns", "rows", "cells"):
            relative = Path(table["files"][name]["path"])
            updated["files"][name] = {**_write_records(staging / relative, getattr(result, name)), "path": str(relative)}
        tables.append(updated)
    manifest = {**reader.manifest, "tables": tables, "coverage_rule": "VERIFIED_FILING_FOCUS_V2",
                "supersedes_publication": str(publication.absolute()), "removed_synthetic_columns": removed,
                "source_manifest_sha256": hashlib.sha256((publication / "history_manifest.json").read_bytes()).hexdigest()}
    _write_json(staging / "history_manifest.json", manifest)
    HistoryPublicationReader(staging, allow_staging=True).verify_all()
    staging.rename(destination)
    return destination


def _write_records(path: Path, records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    import polars as pl
    path.parent.mkdir(parents=True, exist_ok=True)
    json_fields = sorted({key for row in records for key, value in row.items() if isinstance(value, (dict, list, tuple))})
    encoded = [{key: json.dumps(value, sort_keys=True, default=str) if key in json_fields and value is not None else value
                for key, value in row.items()} for row in records]
    frame = pl.from_dicts(encoded, infer_schema_length=None) if encoded else pl.DataFrame()
    frame.write_parquet(path)
    return {"count": len(records), "json_fields": json_fields, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class HistoryPublicationReader:
    """Reload persisted fiscal tables only: no SEC, Arelle, selection or build."""

    def __init__(self, root: Path, *, allow_staging: bool = False) -> None:
        self.root = Path(root)
        if self.root.is_symlink() or (".partial-" in self.root.name and not allow_staging):
            raise ValueError("partial or symlink history publication is not consumable")
        self.manifest = json.loads((self.root / "history_manifest.json").read_text())
        if self.manifest.get("version") != HISTORY_VERSION:
            raise ValueError("unsupported history publication version")

    def _records(self, info: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        import polars as pl
        relative = Path(info["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe history dataset path")
        path = self.root / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("history dataset integrity mismatch")
        records = pl.read_parquet(path).to_dicts()
        if len(records) != info["count"]:
            raise ValueError("history dataset row count mismatch")
        return tuple({key: json.loads(value) if key in info["json_fields"] and value is not None else value
                      for key, value in row.items()} for row in records)

    def verify_all(self) -> None:
        for table in self.manifest["tables"]:
            for info in table["files"].values():
                self._records(info)
        if self.manifest.get("derived_quarter"):
            self._records(self.manifest["derived_quarter"])

    def load(self, *, ticker: str, period_class: str = "QTD_3M", view: str = "LATEST_REPORTED"):
        from sec_xbrl.analytics import FiscalTimeSeriesResult
        matches = [table for table in self.manifest["tables"] if table["ticker"] == ticker.upper()
                   and table["period_class"] == period_class and table["view"] == view]
        if len(matches) != 1:
            raise ValueError("requested ticker/period class/view is not published")
        table = matches[0]
        return FiscalTimeSeriesResult(**{name: self._records(table["files"][name]) for name in ("columns", "rows", "cells")}, scope=table["scope"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover")
    discover.add_argument("--tickers", nargs="+", required=True)
    discover.add_argument("--workspace", type=Path, required=True)
    discover.add_argument("--as-of", type=date.fromisoformat, required=True)
    discover.add_argument("--report-start", type=date.fromisoformat)
    discover.add_argument("--report-end", type=date.fromisoformat)
    discover.add_argument("--recent-fiscal-years", type=int)
    discover.add_argument("--submissions-root", action="append", type=Path, default=[])
    discover.add_argument("--offline", action="store_true")
    intake = commands.add_parser("ingest")
    intake.add_argument("--plan", type=Path, required=True)
    intake.add_argument("--source-run", action="append", type=Path, default=[])
    intake.add_argument("--output-run", type=Path, required=True)
    intake.add_argument("--package-cache", type=Path, required=True)
    intake.add_argument("--index-cache", type=Path, required=True)
    intake.add_argument("--taxonomy-cache", type=Path, required=True)
    intake.add_argument("--bootstrap-taxonomy", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("--intake-manifest", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--views", nargs="+", default=["AS_FILED", "LATEST_REPORTED"])
    query = commands.add_parser("query")
    query.add_argument("--publication", type=Path, required=True)
    query.add_argument("--ticker", required=True)
    query.add_argument("--period-class", default="QTD_3M")
    query.add_argument("--view", default="LATEST_REPORTED")
    query.add_argument("--concept")
    repair = commands.add_parser("repair-coverage")
    repair.add_argument("--publication", type=Path, required=True)
    repair.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "discover":
        result = discover_history(workspace=args.workspace, tickers=tuple(args.tickers), as_of=args.as_of,
                                  report_start=args.report_start, report_end=args.report_end,
                                  recent_fiscal_years=args.recent_fiscal_years,
                                  submissions_roots=tuple(args.submissions_root), offline=args.offline)
    elif args.command == "ingest":
        result = ingest_history(plan_path=args.plan, source_runs=tuple(args.source_run), output_run=args.output_run,
                                package_cache=args.package_cache, index_cache=args.index_cache,
                                taxonomy_cache=args.taxonomy_cache, bootstrap_taxonomy=args.bootstrap_taxonomy)
        if not json.loads(result.read_text())["complete"]:
            print(result)
            raise SystemExit(1)
    elif args.command == "build":
        result = build_history(intake_manifest=args.intake_manifest, output_root=args.output_root, views=tuple(args.views))
    elif args.command == "repair-coverage":
        result = repair_history_coverage(publication=args.publication, destination=args.destination)
    else:
        from sec_xbrl.analytics import FiscalTimeSeriesQuery
        result = HistoryPublicationReader(args.publication).load(ticker=args.ticker, period_class=args.period_class, view=args.view)
        matrix = FiscalTimeSeriesQuery(result).matrix()
        print(json.dumps({"columns": result.columns, "rows": [row for row in matrix if args.concept is None
                         or row["row"].get("raw_concept_qname") == args.concept]}, default=str))
        return
    print(result)


if __name__ == "__main__":
    main()
