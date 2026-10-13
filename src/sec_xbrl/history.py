"""Resumable company-history intake and publication, using the existing engines.

Run ``python -m sec_xbrl.history --help`` for the staged command interface.
SEC identity is supplied only through SEC_USER_AGENT at runtime.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import stat
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
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
from sec_xbrl.longitudinal.canonical import MAPPING_VERSION
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
from sec_xbrl.longitudinal.materialization import Layer2RuleVersions

HISTORY_VERSION = "company-history-v1"
_SUPPORTED_HISTORY_SOURCE_PARSER_VERSIONS = frozenset(
    {"m2-layer1-v5", "m2-layer1-v6"}
)
_RECORD_WRITE_BATCH_SIZE = 32
_RECORD_WRITE_BATCH_BYTES = 8 * 1024 * 1024


def _history_layer2_rule_versions() -> Layer2RuleVersions:
    """Declare the active policies in every newly built history run."""
    return Layer2RuleVersions(
        "period-fiscal-boundaries-v2",
        MAPPING_VERSION,
        "recast-v1",
        "selection-v1",
    )


def _write_json(path: Path, payload: Any) -> None:
    _check_history_storage(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    _check_history_storage(temporary)
    data = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    if _retain_history_artifacts():
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(data)
        _check_history_storage(path)
        os.link(temporary, path, follow_symlinks=False)
    else:
        temporary.write_text(data, encoding="utf-8")
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
                    snapshots = [_load_history_source_snapshot(root / "snapshots" / ref.cik / ref.accession.replace("-", ""), ref.cik, ref.accession) for root in existing]
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
                    snapshot = _load_history_source_snapshot(ingestor.snapshot_dir(resolved), ref.cik, ref.accession)
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


def _load_history_source_snapshot(directory: Path, cik: str, accession: str) -> Any:
    """Fully verify an eligible same-schema v5/v6 source-run snapshot."""
    snapshot = _load_declared_cohort_snapshot(directory, cik, accession)
    parser_version = snapshot.input.parser_version
    if parser_version not in _SUPPORTED_HISTORY_SOURCE_PARSER_VERSIONS:
        raise ValueError(
            "history source snapshot requires an eligible Layer 1 parser version: "
            f"{parser_version}"
        )
    return snapshot


def _validate_release_snapshot_plans(
    release: Any, planned: dict[tuple[str, str], dict[str, Any]]
) -> None:
    """Validate every snapshot without retaining the final loop item in the caller."""
    for snapshot in release.snapshots:
        key = (snapshot.input.cik, snapshot.input.accession)
        _validate_snapshot_plan(snapshot, planned[key])


def _validate_existing_operational_roots(
    reader: Any, roots: dict[str, Path], input_fingerprint: str
) -> None:
    """Validate reusable roots without retaining the final loaded publication."""
    for root in (path for path in roots.values() if path.exists()):
        existing = reader.load(root)
        if existing.identity["layer2_run_fingerprint"] != input_fingerprint:
            raise ValueError("existing operational publication uses different inputs or active rules")
        del existing


def _validate_active_publications(
    publications: tuple[Any, ...], input_fingerprint: str
) -> None:
    """Attest every active T1-T4 root before callers release dead inputs."""
    for publication in publications:
        if publication.identity["layer2_run_fingerprint"] != input_fingerprint:
            raise ValueError("existing operational publication belongs to different raw inputs")


def _partition_current_observations(
    observations: Any,
) -> tuple[dict[tuple[Any, ...], list[dict[str, Any]]], dict[str, int]]:
    """Copy the exact CURRENT_FOCUS partition, then permit T1 to be released."""
    if not observations.is_reader_attested:
        raise ValueError("reported observations must be reader-attested")
    dataset = "reported_period_observation"
    if dataset not in observations.datasets:
        raise ValueError("T1 publication has no reported observations")
    periods: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    comparative_counts: dict[str, int] = defaultdict(int)
    for source in observations.datasets[dataset]:
        row = dict(source)
        if row.get("comparative_type") != "CURRENT_FOCUS":
            comparative_counts[str(row["cik"])] += 1
            continue
        key = (
            row["cik"],
            row.get("fiscal_year"),
            row.get("fiscal_quarter"),
            row.get("period_class"),
        )
        periods[key].append(row)
    return periods, dict(comparative_counts)


def _company_ledgers(ledger_publication: Any, ciks: tuple[str, ...]) -> dict[str, tuple[dict[str, Any], ...]]:
    """Copy the small per-company ledgers before releasing the full T4 publication."""
    from sec_xbrl.longitudinal import AccessionVersionLedgerReader

    reader = AccessionVersionLedgerReader()
    return {cik: reader.get_company(ledger_publication, cik=cik) for cik in ciks}


def _build_fiscal_time_series(
    builder: Any, inputs: list[Any], expected_periods: list[Any]
) -> Any:
    """Build an independent result, then release the source panels immediately."""
    try:
        return builder.build(inputs=inputs, expected_periods=expected_periods)
    finally:
        inputs.clear()


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
        CohortReleaseAdapter,
        CohortSnapshotReference,
        CohortSource,
        ExplorationGraphPipeline,
        FilingRelationshipIndexPipeline,
        Layer2PublicationReader,
        ReportedObservationSelector,
        VersionedObservationPanelPipeline,
    )
    if not views or len(set(views)) != len(views) or set(views) - {"AS_FILED", "LATEST_REPORTED"}:
        raise ValueError("views must be distinct AS_FILED/LATEST_REPORTED")
    intake = json.loads(intake_manifest.read_text())
    _validate_intake(intake)
    plan = intake["plan"]
    grouped: dict[Path, list[Any]] = defaultdict(list)
    for item in intake["filings"]:
        grouped[Path(item["source_run"])].append(CohortSnapshotReference(item["filing"]["cik"], item["filing"]["accession"]))
    run_id = output_root.name
    release = CohortReleaseAdapter().load(
        tuple(CohortSource(root, root.name, tuple(refs)) for root, refs in grouped.items()),
        cohort_id=run_id, ciks=tuple(company["cik"] for company in plan["companies"]), run_version=run_id,
        rules=_history_layer2_rule_versions(),
    )
    planned = {(item["filing"]["cik"], item["filing"]["accession"]): item["filing"] for item in intake["filings"]}
    _validate_release_snapshot_plans(release, planned)
    input_fingerprint = release.layer2_run.fingerprint
    snapshot_count = len(release.snapshots)
    reader = Layer2PublicationReader()
    roots = {name: output_root / name / run_id for name in ("t1", "t2", "t3", "t4")}
    _validate_existing_operational_roots(reader, roots, input_fingerprint)
    destination = output_root / "reported-panels"
    if destination.exists() and not roots_only:
        history_reader = HistoryPublicationReader(destination)
        if history_reader.manifest["plan"] != plan or tuple(history_reader.manifest["views"]) != views:
            raise ValueError("history publication scope differs; choose a new output root")
        if history_reader.manifest.get("input_fingerprint") != input_fingerprint:
            raise ValueError("existing history publication uses different inputs or active rules")
        declared_roots = history_reader.manifest.get("operational_roots") or {}
        if set(declared_roots) != set(roots) or any(
            not roots[name].is_dir()
            or Path(declared_roots[name]).resolve() != roots[name].resolve()
            for name in roots
        ):
            raise ValueError("existing history publication has incomplete operational roots")
        del release
        gc.collect()
        history_reader.verify_all()
        from sec_xbrl.analytics.history_quarters import publish_quarter_history
        consumer = output_root / "panels"
        if consumer.exists():
            consumer_reader = HistoryPublicationReader(consumer)
            if consumer_reader.manifest.get("input_fingerprint") != input_fingerprint:
                raise ValueError("existing quarter history uses different inputs or active rules")
            consumer_reader.verify_all()
            return consumer
        # The immutable Layer 2 roots and reported publication now carry every
        # required input identity.  Do not retain the Raw cohort while the
        # additive quarter publisher performs its own verified reads.
        return publish_quarter_history(publication=destination, output_root=output_root, reuse_roots=True)
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
    _validate_active_publications(
        (observations, relationships, graph, ledger_pub), input_fingerprint
    )
    # T2 was needed to construct or validate T3.  T5 traverses the verified T3
    # publication and does not read T2 again.
    del relationships
    print(json.dumps({"stage": "OPERATIONAL_ROOTS_READY", "filings": snapshot_count}), flush=True)
    if roots_only:
        return output_root
    filing_by_id = {str(row["filing_id"]): row for row in release.records("filing")}
    # T1-T4 have been validated against the active run fingerprint, and the
    # only remaining release data needed by reported panels is the small
    # filing index above.  Releasing the cohort here avoids retaining every
    # immutable Raw snapshot beside T1/T3 panel materialization.
    del release
    periods, comparative_counts = _partition_current_observations(observations)
    del observations
    ciks = tuple(str(company["cik"]) for company in plan["companies"])
    ledgers_by_cik = _company_ledgers(ledger_pub, ciks)
    del ledger_pub
    builder = CompanyAnalysisPanelBuilder()
    selector = ReportedObservationSelector()
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".panels.partial-", dir=output_root))
    tables = []
    for company in plan["companies"]:
        cik, ticker = company["cik"], company["ticker"]
        coverage_keys = _filing_coverage_keys(tuple(filing_by_id.values()), cik)
        ledger = ledgers_by_cik[cik]
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
                result = _build_fiscal_time_series(
                    FiscalTimeSeriesBuilder(), inputs, expected
                )
                # The result owns deep copies of every persisted definition,
                # binding, value and candidate path.  Do not retain the source
                # panels or the last selection aliases during serialization.
                del inputs, selected, panel
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
                counts = {
                    name: len(getattr(result, name))
                    for name in ("columns", "rows", "cells")
                }
                staged_files: dict[str, _StagedRecordWrite] = {}
                try:
                    for name in ("columns", "rows", "cells"):
                        path = staging / relative / f"{name}.parquet"
                        staged_files[name] = _stage_records(
                            path, getattr(result, name)
                        )
                    # Each staged write plan owns only schema, counts, paths and
                    # its TemporaryDirectory.  The source panels and selection
                    # aliases were released above; now release the result before
                    # any whole-table native merge.
                    del result
                    gc.collect()
                    for name in ("columns", "rows", "cells"):
                        staged = staged_files[name]
                        info = _finalize_staged_records(staged)
                        table["files"][name] = {
                            **info,
                            "path": str(relative / staged.path.name),
                        }
                finally:
                    for staged in staged_files.values():
                        staged.cleanup()
                tables.append(table)
                print(json.dumps({"stage": "PANEL_WRITTEN", "ticker": ticker, "view": view,
                                  "period_class": period_class, "rows": counts["rows"],
                                  "cells": counts["cells"]}), flush=True)
    manifest = {"version": HISTORY_VERSION, "plan": plan, "views": views, "tables": tables,
                "source_intake": str(intake_manifest.absolute()),
                "operational_roots": {key: str(path.absolute()) for key, path in roots.items()},
                "input_fingerprint": input_fingerprint,
                "comparative_scope": "CURRENT_FOCUS",
                "comparative_observations_retained_in_t1": dict(comparative_counts),
                "quarterly_derivation_status": "NOT_MATERIALIZED_REPORTED_SERIES_ONLY"}
    _write_json(staging / "history_manifest.json", manifest)
    # Storage validation and the quarter producer need none of the build graph.
    del graph, periods, ledgers_by_cik, ledger, filing_by_id, builder, selector
    gc.collect()
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
        snapshot = _load_history_source_snapshot(directory, record["cik"], record["accession"])
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


@dataclass
class _StagedRecordWrite:
    """Small ownership plan for bounded chunks awaiting their final merge."""

    path: Path
    count: int
    json_fields: tuple[str, ...]
    schema: Any
    chunk_paths: tuple[Path, ...]
    workspace: Any | None

    def cleanup(self) -> None:
        if self.workspace is not None:
            _cleanup_history_workspace(self.workspace)
            self.workspace = None


def _stage_records(
    path: Path, records: tuple[dict[str, Any], ...]
) -> _StagedRecordWrite:
    import polars as pl

    _check_history_storage(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_fields = sorted({key for row in records for key, value in row.items() if isinstance(value, (dict, list, tuple))})
    if not records:
        return _StagedRecordWrite(path, 0, (), pl.Schema(), (), None)
    # json_fields is table-global: if a later row makes a field nested,
    # earlier scalar values in that field must also be JSON encoded.  Infer
    # bounded local schemas, resolve their global super-schema without
    # retaining values, then encode each original batch directly against
    # that global schema.  This prevents an early int/float or bool/int
    # batch from losing its original representation before a late string
    # promotes the complete column to String.
    schemas = []
    for start in range(0, len(records), _RECORD_WRITE_BATCH_SIZE):
        batch = records[start : start + _RECORD_WRITE_BATCH_SIZE]
        schemas.append(
            pl.from_dicts(
                _schema_record_batch(batch, json_fields),
                infer_schema_length=None,
            ).schema
        )
    global_schema = pl.concat(
        [pl.DataFrame(schema=schema).lazy() for schema in schemas],
        how="diagonal_relaxed",
    ).collect_schema()
    workspace = tempfile.TemporaryDirectory(
        prefix=f".{path.name}.chunks-", dir=path.parent
    )
    chunk_paths: list[Path] = []
    try:
        chunk_directory = Path(workspace.name)
        for encoded_batch, _encoded_bytes in _iter_encoded_record_batches(
            records, json_fields
        ):
            chunk_path = chunk_directory / f"{len(chunk_paths):08d}.parquet"
            _check_history_storage(chunk_path)
            pl.from_dicts(
                encoded_batch,
                schema=global_schema,
                infer_schema_length=None,
            ).write_parquet(
                chunk_path, row_group_size=_RECORD_WRITE_BATCH_SIZE
            )
            chunk_paths.append(chunk_path)
    except BaseException:
        _cleanup_history_workspace(workspace)
        raise
    return _StagedRecordWrite(
        path,
        len(records),
        tuple(json_fields),
        global_schema,
        tuple(chunk_paths),
        workspace,
    )


def _finalize_staged_records(staged: _StagedRecordWrite) -> dict[str, Any]:
    import polars as pl

    try:
        _check_history_storage(staged.path)
        if not staged.chunk_paths:
            pl.DataFrame().write_parquet(staged.path)
        else:
            pl.concat(
                [pl.scan_parquet(chunk_path) for chunk_path in staged.chunk_paths],
                how="vertical",
            ).sink_parquet(
                staged.path,
                maintain_order=True,
                row_group_size=_RECORD_WRITE_BATCH_SIZE,
            )
        return {
            "count": staged.count,
            "json_fields": list(staged.json_fields),
            "sha256": _sha256_file(staged.path),
        }
    finally:
        staged.cleanup()


def _write_records(path: Path, records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Compatibility wrapper that stages, releases its input alias, then merges."""
    staged = _stage_records(path, records)
    del records
    return _finalize_staged_records(staged)


def _schema_record_batch(
    batch: tuple[dict[str, Any], ...], json_fields: list[str]
) -> list[dict[str, Any]]:
    """Represent types without serializing nested payloads or retaining text."""
    return [
        {
            key: _schema_value(key, value, json_fields)
            for key, value in row.items()
        }
        for row in batch
    ]


def _schema_value(key: str, value: Any, json_fields: list[str]) -> Any:
    if value is None:
        return None
    if key in json_fields or isinstance(value, str):
        return ""
    if isinstance(value, bytes):
        return b""
    if isinstance(value, bytearray):
        return bytearray()
    return value


def _iter_encoded_record_batches(
    records: tuple[dict[str, Any], ...], json_fields: list[str]
):
    """Yield bounded encoded batches; one indivisible row may exceed the cap."""
    batch: list[dict[str, Any]] = []
    batch_bytes = 0
    for row in records:
        encoded = {
            key: json.dumps(value, sort_keys=True, default=str)
            if key in json_fields and value is not None
            else value
            for key, value in row.items()
        }
        encoded_bytes = _encoded_record_size(encoded, json_fields)
        if batch and (
            len(batch) >= _RECORD_WRITE_BATCH_SIZE
            or batch_bytes + encoded_bytes > _RECORD_WRITE_BATCH_BYTES
        ):
            yield batch, batch_bytes
            batch, batch_bytes = [], 0
        batch.append(encoded)
        batch_bytes += encoded_bytes
        if batch_bytes >= _RECORD_WRITE_BATCH_BYTES:
            yield batch, batch_bytes
            batch, batch_bytes = [], 0
    if batch:
        yield batch, batch_bytes


def _encoded_record_size(
    encoded: dict[str, Any], json_fields: list[str]
) -> int:
    """Bound encoded/native string input without allocating a second byte copy."""
    total = 0
    for key, value in encoded.items():
        if isinstance(value, str):
            # json.dumps uses ensure_ascii=True by default, so JSON field
            # character count is its exact encoded byte count.  Four bytes per
            # character is a conservative bound for other Unicode strings.
            total += len(value) if key in json_fields else 4 * len(value)
        elif isinstance(value, (bytes, bytearray)):
            total += len(value)
    return total


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_symlink_components(path: Path) -> None:
    """Reject symlinks at every level, including publication ancestors."""
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("symlink history path is not consumable")


def _history_dataset_path(root: Path, info: dict[str, Any]) -> Path:
    relative = Path(info["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("unsafe history dataset path")
    path = root / relative
    _reject_symlink_components(path)
    if not path.is_file() or _sha256_file(path) != info["sha256"]:
        raise ValueError("history dataset integrity mismatch")
    return path


def _iter_history_records(path: Path, info: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Decode every field in order, with at most 32 encoded rows per scan.

    Hash attestation belongs to the caller. A fresh nonparallel, low-memory
    scan for each slice avoids a background iterator prefetching later groups.
    The producer writes 32-row groups; native memory still includes the current
    Parquet page/dictionary and an indivisible large row. This is a row bound,
    not a promise that arbitrary external Parquet pages have bounded bytes.
    """
    import polars as pl

    frame = pl.scan_parquet(path, parallel="none", low_memory=True, rechunk=False)
    schema = frame.collect_schema()
    count = frame.select(pl.len()).collect(engine="streaming").item()
    if type(info["count"]) is not int or count != info["count"]:
        raise ValueError("history dataset row count mismatch")
    declared = info.get("json_fields")
    if (not isinstance(declared, list)
        or not all(isinstance(field, str) for field in declared)
        or len(set(declared)) != len(declared)
        or any(field not in schema or schema[field] not in (pl.String, pl.Null)
               for field in declared)):
        raise ValueError("history dataset JSON schema mismatch")
    for start in range(0, count, _RECORD_WRITE_BATCH_SIZE):
        batch = frame.slice(start, _RECORD_WRITE_BATCH_SIZE).collect(engine="streaming")
        if batch.schema != schema or batch.height != min(_RECORD_WRITE_BATCH_SIZE, count-start):
            raise ValueError("history dataset batch schema/count mismatch")
        # iter_rows avoids a second list containing the entire encoded batch.
        for row in batch.iter_rows(named=True, buffer_size=1):
            yield {key: json.loads(value) if key in declared and value is not None else value
                   for key, value in row.items()}
        del batch


def open_history_publication(root: Path):
    """Common persisted-data reader, including reviewed disclosure publications."""
    _check_recovery_access(root)
    if (root / "review_manifest.json").exists():
        from sec_xbrl.longitudinal.disclosure_review import ReviewedPublicationReader
        return ReviewedPublicationReader(root)
    return HistoryPublicationReader(root)


class HistoryPublicationReader:
    """Reload persisted fiscal tables only: no SEC, Arelle, selection or build."""

    def __init__(self, root: Path, *, allow_staging: bool = False, _recovery_access: Any = None) -> None:
        self.root = Path(root)
        self._recovery_access = _recovery_access
        _check_recovery_access(self.root, _recovery_access)
        if self.root.is_symlink() or (".partial-" in self.root.name and not allow_staging):
            raise ValueError("partial or symlink history publication is not consumable")
        _reject_symlink_components(self.root / "history_manifest.json")
        self.manifest = json.loads((self.root / "history_manifest.json").read_text())
        if self.manifest.get("version") != HISTORY_VERSION:
            raise ValueError("unsupported history publication version")

    def _records(self, info: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        import polars as pl
        _check_recovery_access(self.root, getattr(self, "_recovery_access", None))
        path = _history_dataset_path(self.root, info)
        records = pl.read_parquet(path).to_dicts()
        if len(records) != info["count"]:
            raise ValueError("history dataset row count mismatch")
        return tuple({key: json.loads(value) if key in info["json_fields"] and value is not None else value
                      for key, value in row.items()} for row in records)

    def verify_all(self) -> None:
        _check_recovery_access(self.root, getattr(self, "_recovery_access", None))
        for table in self.manifest["tables"]:
            for info in table["files"].values():
                for _record in _iter_history_records(_history_dataset_path(self.root, info), info):
                    pass
        if self.manifest.get("derived_quarter"):
            info = self.manifest["derived_quarter"]
            for _record in _iter_history_records(_history_dataset_path(self.root, info), info):
                pass

    def load(self, *, ticker: str, period_class: str = "QTD_3M", view: str = "LATEST_REPORTED"):
        from sec_xbrl.analytics import FiscalTimeSeriesResult
        matches = [table for table in self.manifest["tables"] if table["ticker"] == ticker.upper()
                   and table["period_class"] == period_class and table["view"] == view]
        if len(matches) != 1:
            raise ValueError("requested ticker/period class/view is not published")
        table = matches[0]
        return FiscalTimeSeriesResult(**{name: self._records(table["files"][name]) for name in ("columns", "rows", "cells")}, scope=table["scope"])


def _recovery_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _open_recovery_path(path: Path, flags: int = os.O_RDONLY) -> int:
    """Open through no-follow directory handles, never a symlink ancestor."""
    path = path.absolute()
    if ".." in path.parts:
        raise ValueError("unsafe recovery path")
    if path == Path(path.anchor):
        return os.open(path.anchor, flags | os.O_NOFOLLOW)
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return os.open(path.name, flags | os.O_NOFOLLOW, dir_fd=fd)
    finally:
        os.close(fd)


class _RecoveryPins:
    """Immutable evidence buffers plus identity guards for later public reads."""

    def __init__(self) -> None:
        self.files: dict[Path, tuple[int, ...]] = {}
        self.directories: dict[Path, tuple[int, int]] = {}

    def directory(self, path: Path) -> None:
        for parent in (path.absolute(), *path.absolute().parents):
            value = parent.lstat()
            if not stat.S_ISDIR(value.st_mode):
                raise ValueError("recovery source directory is unsafe")
            identity = (value.st_dev, value.st_ino)
            if parent in self.directories and self.directories[parent] != identity:
                raise ValueError("recovery source directory identity changed")
            self.directories[parent] = identity

    def file(self, path: Path) -> None:
        path = path.absolute()
        self.directory(path.parent)
        value = path.lstat()
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("recovery source file is unsafe")
        identity = _recovery_stat_identity(value)
        if path in self.files and self.files[path] != identity:
            raise ValueError("recovery source file identity/content changed")
        self.files[path] = identity

    def tree(self, root: Path) -> None:
        self.directory(root)
        for path in root.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                self.directory(path)
            else:
                self.file(path)

    def check(self) -> None:
        try:
            for path, identity in self.directories.items():
                value = path.lstat()
                if not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != identity:
                    raise ValueError("recovery source directory identity changed")
            for path, identity in self.files.items():
                value = path.lstat()
                if not stat.S_ISREG(value.st_mode) or _recovery_stat_identity(value) != identity:
                    raise ValueError("recovery source file identity/content changed")
        except OSError as exc:
            raise ValueError("recovery pinned source path disappeared") from exc

    def read(self, path: Path, expected_sha256: str | None, label: str) -> bytes:
        self.file(path)
        with os.fdopen(_open_recovery_path(path), "rb") as stream:
            if _recovery_stat_identity(os.fstat(stream.fileno())) != self.files[path.absolute()]:
                raise ValueError("recovery source file exchanged before read")
            data = stream.read()
            if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
                raise ValueError(f"recovery {label} hash mismatch")
            if _recovery_stat_identity(os.fstat(stream.fileno())) != self.files[path.absolute()]:
                raise ValueError("recovery source file changed during read")
        self.check()
        return data


class _RecoveryOutput:
    """Retained transaction under an explicitly trusted exclusive parent."""

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.bindings: dict[Path, tuple[int, int]] = {}
        self.marker_pins = _RecoveryPins()
        self.parents = _RecoveryPins()
        self.parents.directory(self.root.parent)
        self.parent_fd = _open_recovery_path(self.root.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.fd = -1
        try:
            self.parents.check()
            parent_stat = os.fstat(self.parent_fd)
            if parent_stat.st_uid != os.geteuid() or parent_stat.st_mode & 0o022:
                raise ValueError("recovery requires a user-owned non-shared trusted parent")
            # mkdir is the exclusive reservation; an earlier exists() check
            # never confers cleanup ownership over a concurrent creator.
            os.mkdir(self.root.name, mode=0o700, dir_fd=self.parent_fd)
            self.fd = os.open(self.root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=self.parent_fd)
            value = os.fstat(self.fd)
            self.identity = (value.st_dev, value.st_ino)
            if os.listdir(self.fd):
                raise ValueError("recovery initial root is not empty; ownership unproven")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        try:
            self.parents.check()
            value = os.stat(self.root.name, dir_fd=self.parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != self.identity:
                raise ValueError("recovery output ownership changed; transaction left untouched")
            self.marker_pins.check()
            for path, identity in self.bindings.items():
                child = path.lstat()
                if not stat.S_ISDIR(child.st_mode) or (child.st_dev, child.st_ino) != identity:
                    raise ValueError("recovery descendant identity changed")
            # First capture relies on the declared sole-writer parent contract.
            # Later exchanges cannot silently become a new directory binding.
            for path in self.root.rglob("*"):
                child = path.lstat()
                if stat.S_ISLNK(child.st_mode):
                    raise ValueError("recovery output symlink is unsafe")
                if stat.S_ISDIR(child.st_mode):
                    self.bindings.setdefault(path, (child.st_dev, child.st_ino))
        except (OSError, ValueError) as exc:
            raise ValueError("recovery output ownership changed; transaction left untouched") from exc

    def create_file(self, relative: Path) -> int:
        self.check()
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe recovery output path")
        fd = os.dup(self.fd)
        try:
            for name in relative.parts[:-1]:
                self.check()
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            self.check()
            return os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600, dir_fd=fd)
        finally:
            os.close(fd)

    def write(self, relative: Path, data: bytes) -> None:
        with os.fdopen(self.create_file(relative), "wb") as stream:
            stream.write(data)
        self.check()

    def rename(self, source: Path, destination: Path) -> None:
        self.check()
        if destination.exists():
            raise ValueError("recovery refuses an existing destination")
        source = source.absolute()
        destination = destination.absolute()
        source_relative = source.relative_to(self.root)
        destination_relative = destination.relative_to(self.root)
        bindings = {path: identity for path, identity in self.bindings.items()
                    if path == source or path.is_relative_to(source)}
        # Linux RENAME_NOREPLACE avoids deleting even an empty directory
        # inserted at the destination after the earlier existence check.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise ValueError("recovery requires Linux renameat2 RENAME_NOREPLACE")
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(self.fd, os.fsencode(source_relative), self.fd, os.fsencode(destination_relative), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
        for path, identity in bindings.items():
            del self.bindings[path]
            self.bindings[destination / path.relative_to(source)] = identity
        self.check()

    def mark_pending(self, metadata: dict[str, Any], attestation_bytes: bytes, report_bytes: bytes) -> None:
        self.transaction = {**metadata, "status": "NOT_READY", "token": uuid.uuid4().hex,
                            "output_root": str(self.root), "root_identity": list(self.identity)}
        data = (json.dumps(self.transaction, indent=2, sort_keys=True) + "\n").encode()
        self.marker_sha256 = hashlib.sha256(data).hexdigest()
        relative = Path(_RECOVERY_CONTROL_PREFIX + self.marker_sha256) / "transaction.json"
        self.write(relative, data)
        self.marker_pins.file(self.root / relative)
        for name, data in (("attestation.json", attestation_bytes), ("verification_report.json", report_bytes)):
            artifact = relative.parent / name
            self.write(artifact, data)
            self.marker_pins.file(self.root / artifact)
        self.check()

    def commit(self, receipt: dict[str, Any]) -> None:
        self.check()
        temporary = Path(f".receipt.partial-{uuid.uuid4().hex}")
        data = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        self.write(temporary, data)
        self.check()
        _validate_recovery_gate(self.root, self.root / (_RECOVERY_CONTROL_PREFIX + self.marker_sha256),
                                self.root / temporary)
        self.check()
        # Hard-link creation is atomic and refuses any existing final entry.
        # Retain the temporary receipt as diagnostic evidence too.
        os.link(temporary.name, "reported_recovery_receipt.json",
                src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        os.close(self.parent_fd)


def _copy_recovery_payload(source: Path, relative: Path, expected_sha256: str,
                           pins: _RecoveryPins, output: _RecoveryOutput) -> None:
    pins.check()
    pins.file(source)
    expected_identity = pins.files[source.absolute()]
    with os.fdopen(_open_recovery_path(source), "rb") as incoming:
        if _recovery_stat_identity(os.fstat(incoming.fileno())) != expected_identity:
            raise ValueError("recovery payload identity changed before copy")
        digest = hashlib.sha256()
        with os.fdopen(output.create_file(relative), "wb") as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                output.check()
                digest.update(block)
                outgoing.write(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("recovery copied payload hash mismatch")
        if _recovery_stat_identity(os.fstat(incoming.fileno())) != expected_identity:
            raise ValueError("recovery payload changed during copy")
    pins.check()
    output.check()


_HISTORY_STORAGE_GUARD: ContextVar[Any] = ContextVar("history_storage_guard", default=None)


def _check_history_storage(path: Path | None = None) -> None:
    guard = _HISTORY_STORAGE_GUARD.get()
    if guard is not None:
        guard(path)


def _cleanup_history_workspace(workspace: Any) -> None:
    if _HISTORY_STORAGE_GUARD.get() is not None:
        # Recovery never recursively deletes artifact trees, even on success.
        workspace._finalizer.detach()
        return
    workspace.cleanup()


_RECOVERY_CONTROL_PREFIX = ".history-recovery-"
_RECOVERY_OUTPUT: ContextVar[Any] = ContextVar("recovery_output", default=None)


def _retain_history_artifacts() -> bool:
    return _RECOVERY_OUTPUT.get() is not None


def _rename_history_directory(source: Path, destination: Path) -> None:
    output = _RECOVERY_OUTPUT.get()
    if output is None:
        source.rename(destination)
    else:
        _check_history_storage(source)
        output.rename(source, destination)


def _recovery_json(data: bytes) -> dict[str, Any]:
    """Reject ambiguous/non-standard trust JSON and parse the authenticated bytes."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate recovery JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-standard recovery JSON scalar: {value}")

    result = json.loads(data, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(result, dict):
        raise TypeError("recovery trust JSON must be an object")
    return result


def _validate_recovery_file_declaration(info: Any, expected_path: str) -> None:
    if (not isinstance(info, dict) or set(info) != {"path", "count", "json_fields", "sha256"}
        or type(info["path"]) is not str or info["path"] != expected_path
        or type(info["count"]) is not int or info["count"] < 0
        or type(info["sha256"]) is not str or len(info["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in info["sha256"])
        or type(info["json_fields"]) is not list
        or any(type(k) is not str for k in info["json_fields"])
        or len(set(info["json_fields"])) != len(info["json_fields"])):
        raise ValueError("recovery consumer file declaration is invalid")


def _validate_completed_recovery_consumer(reported, consumer, reported_root, consumer_root, source_hash):
    """One producer/default-reader completion predicate, without eager records."""
    import polars as pl

    from sec_xbrl.analytics.history_quarters import PERIOD_RULE, QUARTER_RULE

    if (reported.get("version") != HISTORY_VERSION or consumer.get("version") != HISTORY_VERSION
        or reported.get("derived_quarter") is not None
        or reported.get("quarterly_derivation_status") != "NOT_MATERIALIZED_REPORTED_SERIES_ONLY"
        or any(consumer.get(key) != reported.get(key) for key in
               ("plan", "views", "source_intake", "input_fingerprint", "operational_roots"))
        or consumer.get("source_manifest_sha256") != source_hash
        or consumer.get("supersedes_publication") != str(reported_root.absolute())
        or consumer.get("quarterly_derivation_status") != "APPROVED_STANDARD_ADDITIVE_CORE_CONNECTED"
        or consumer.get("period_rule") != PERIOD_RULE or consumer.get("derivation_rule") != QUARTER_RULE):
        raise ValueError("recovery consumer provenance or completion differs")
    changes = consumer.get("period_reclassification_counts")
    if not isinstance(changes, dict) or any(type(v) is not int or v < 0 for v in changes.values()):
        raise ValueError("recovery consumer classification evidence is invalid")
    tables = consumer.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("recovery consumer table inventory is incomplete")
    identities = []
    for table in tables:
        identities.append((table["cik"], table["ticker"], table["view"], table["period_class"]))
        if set(table["files"]) != {"columns", "rows", "cells"} or not isinstance(table["scope"], dict):
            raise ValueError("recovery consumer table contract differs")
        for name, info in table["files"].items():
            _validate_recovery_file_declaration(info, str(Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet"))
    expected_pairs = {(t["cik"], t["ticker"], t["view"]) for t in reported["tables"]}
    if len(set(identities)) != len(identities) or {i[:3] for i in identities} != expected_pairs:
        raise ValueError("recovery consumer scope is incomplete or duplicated")
    info = consumer.get("derived_quarter")
    _validate_recovery_file_declaration(info, "derived_quarter.parquet")
    path = _history_dataset_path(consumer_root, info)
    frame = pl.scan_parquet(path, parallel="none", low_memory=True, rechunk=False)
    schema = frame.collect_schema()
    # Physical contract of the already-selected QUARTER_RULE producer. This
    # validates persisted shape; it does not derive or reinterpret values.
    derived_fields = (
        "derived_metric_id", "derivation_rule_version", "formula", "fiscal_quarter", "value_numeric",
        "context_start_date", "context_end_date", "period_class", "source_fact_ids", "source_filing_ids",
        "source_accessions", "source_inputs", "source_type", "reported_or_derived", "semantic_review_state",
        "policy_registry", "basis_compatibility", "cik", "ticker", "fiscal_year", "view",
    )
    if info["count"] == 0:
        if len(schema) or info["json_fields"]:
            raise ValueError("recovery empty derived-quarter schema differs")
    elif (tuple(schema) != derived_fields
          or info["json_fields"] != ["source_accessions", "source_fact_ids", "source_filing_ids", "source_inputs"]
          or any(dtype not in ((pl.Int64, pl.Null) if field in {"fiscal_year", "fiscal_quarter"}
                               else (pl.String, pl.Null)) for field, dtype in schema.items())):
        raise ValueError("recovery governed derived-quarter physical schema differs")
    if (frame.select(pl.len()).collect(engine="streaming").item() != info["count"]
        or any(field not in schema or schema[field] not in (pl.String, pl.Null) for field in info["json_fields"])):
        raise ValueError("recovery consumer derived-quarter schema/count differs")


_RECOVERY_COMMON_FIELDS = frozenset({
    "version", "attestation", "attestation_sha256", "generation_source_identity", "recovery_source_identity",
    "source_stage", "source_manifest_sha256", "source_intake_sha256", "verification_report_sha256", "input_fingerprint",
})


def _validate_recovery_gate(parent, control, receipt_path):
    pins = _RecoveryPins()
    expected = control.name.removeprefix(_RECOVERY_CONTROL_PREFIX)
    marker = _recovery_json(pins.read(control / "transaction.json", expected, "transaction marker"))
    receipt = _recovery_json(pins.read(receipt_path, None, "completion receipt"))
    if (set(marker) != _RECOVERY_COMMON_FIELDS | {"status", "token", "output_root", "root_identity"}
        or set(receipt) != _RECOVERY_COMMON_FIELDS | {"status", "transaction_sha256", "transaction_token",
            "reported_publication", "consumer_publication", "consumer_manifest_sha256"}
        or any(type(marker[k]) is not str or not marker[k] or type(receipt[k]) is not str
               or receipt[k] != marker[k] for k in _RECOVERY_COMMON_FIELDS)
        or marker["version"] != "reported-stage-recovery-v1"
        or marker["status"] != "NOT_READY" or receipt["status"] != "COMPLETE"):
        raise ValueError("recovery receipt/transaction exact contract differs")
    for key, length in (("attestation_sha256", 64), ("source_manifest_sha256", 64),
                        ("source_intake_sha256", 64), ("verification_report_sha256", 64),
                        ("generation_source_identity", 40), ("recovery_source_identity", 40)):
        if len(marker[key]) != length or any(c not in "0123456789abcdef" for c in marker[key]):
            raise ValueError("invalid recovery identity scalar")
    if (type(marker["token"]) is not str or len(marker["token"]) != 32
        or any(c not in "0123456789abcdef" for c in marker["token"])
        or type(marker["root_identity"]) is not list or len(marker["root_identity"]) != 2
        or any(type(v) is not int or v < 0 for v in marker["root_identity"])
        or any(type(marker[k]) is not str or not Path(marker[k]).is_absolute() or ".." in Path(marker[k]).parts
               for k in ("attestation", "source_stage", "output_root"))):
        raise ValueError("invalid recovery token/root/locator scalar")
    current = parent.stat()
    if (marker["output_root"] != str(parent) or marker["root_identity"] != [current.st_dev, current.st_ino]
        or receipt["transaction_sha256"] != expected or receipt["transaction_token"] != marker["token"]
        or receipt["reported_publication"] != str(parent / "reported-panels")
        or receipt["consumer_publication"] != str(parent / "panels")
        or type(receipt["consumer_manifest_sha256"]) is not str or len(receipt["consumer_manifest_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in receipt["consumer_manifest_sha256"])):
        raise ValueError("recovery receipt identity/publication mismatch")
    proof = _recovery_json(pins.read(control / "attestation.json", marker["attestation_sha256"], "attestation"))
    report = _recovery_json(pins.read(control / "verification_report.json", marker["verification_report_sha256"], "full report"))
    _validate_recovery_report(proof, report)
    if (proof.get("version") != marker["version"] or proof.get("status") != "PASS"
        or any(proof.get(k) != marker[k] for k in ("generation_source_identity", "recovery_source_identity", "input_fingerprint"))
        or proof.get("staged_manifest_sha256") != marker["source_manifest_sha256"]
        or proof.get("intake_sha256") != marker["source_intake_sha256"]
        or proof["verification_report"]["sha256"] != marker["verification_report_sha256"]
        or report["stage_manifest"].get("path", str(Path(marker["source_stage"]) / "history_manifest.json"))
           != str(Path(marker["source_stage"]) / "history_manifest.json")):
        raise ValueError("recovery gate full-report source binding differs")
    reported = _recovery_json(pins.read(parent / "reported-panels" / "history_manifest.json", receipt["source_manifest_sha256"], "reported manifest"))
    consumer = _recovery_json(pins.read(parent / "panels" / "history_manifest.json", receipt["consumer_manifest_sha256"], "consumer manifest"))
    expected_tables = [{**table, "files": {name: {k: v for k, v in info.items() if k != "schema"}
                       for name, info in table["files"].items()}} for table in proof["tables"]]
    if (reported["tables"] != expected_tables
        or any(reported.get(k) != proof[k] for k in ("plan", "views", "input_fingerprint"))
        or reported["source_intake"] != report["source_intake"].get("path", reported["source_intake"])):
        raise ValueError("recovery gate reported execution scope differs")
    _validate_completed_recovery_consumer(reported, consumer, parent / "reported-panels", parent / "panels", receipt["source_manifest_sha256"])
    pins.check()


def _check_recovery_access(root: Path, capability: Any = None) -> None:
    """A staging flag never overrides a recovery transaction's readiness gate."""
    root = Path(root).absolute()
    _reject_symlink_components(root)
    for parent in (root, *root.parents):
        if not parent.is_dir():
            continue
        controls = list(parent.glob(_RECOVERY_CONTROL_PREFIX + "*"))
        receipt_path = parent / "reported_recovery_receipt.json"
        if not controls and not os.path.lexists(receipt_path) and not list(parent.glob(".receipt.partial-*")):
            continue
        if capability is not None and capability is _RECOVERY_OUTPUT.get() and parent == capability.root:
            _check_history_storage(root)
            return
        try:
            if len(controls) != 1 or controls[0].is_symlink() or not controls[0].is_dir():
                raise ValueError("missing/ambiguous recovery transaction marker")
            _validate_recovery_gate(parent, controls[0], receipt_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("recovery transaction is NOT_READY or its completion gate is invalid") from exc



def _validate_recovery_sources(intake, operational_root, expected_fingerprint, expected_roots, pins=None):
    """Use the existing Raw adapter and public T1-T4 readers, without rebuilding."""
    from sec_xbrl.longitudinal import (
        CohortReleaseAdapter,
        CohortSnapshotReference,
        CohortSource,
        Layer2PublicationReader,
    )
    pins = pins or _RecoveryPins()
    grouped = defaultdict(list)
    for item in intake["filings"]:
        pins.tree(Path(item["source_run"]) / "snapshots" / item["filing"]["cik"]
                  / item["filing"]["accession"].replace("-", ""))
        grouped[Path(item["source_run"])].append(
            CohortSnapshotReference(item["filing"]["cik"], item["filing"]["accession"])
        )
    release = CohortReleaseAdapter().load(
        tuple(CohortSource(root, root.name, tuple(refs)) for root, refs in grouped.items()),
        cohort_id=operational_root.name,
        ciks=tuple(company["cik"] for company in intake["plan"]["companies"]),
        run_version=operational_root.name, rules=_history_layer2_rule_versions(),
    )
    _validate_release_snapshot_plans(release, {
        (item["filing"]["cik"], item["filing"]["accession"]): item["filing"]
        for item in intake["filings"]
    })
    pins.check()
    if release.layer2_run.fingerprint != expected_fingerprint:
        raise ValueError("recovery Raw inputs or active rules differ")
    del release
    gc.collect()
    if set(expected_roots) != {"t1", "t2", "t3", "t4"}:
        raise ValueError("recovery requires all four independently pinned operational roots")
    roots = {}
    for name in ("t1", "t2", "t3", "t4"):
        root = operational_root / name / operational_root.name
        manifest = root / Layer2PublicationReader.manifest_name
        pins.tree(root)
        pins.read(manifest, expected_roots[name], "operational manifest")
        existing = Layer2PublicationReader().load(root)
        pins.check()
        if existing.identity.get("layer2_manifest_sha256") != expected_roots[name]:
            raise ValueError("recovery operational reader manifest identity mismatch")
        if existing.identity["layer2_run_fingerprint"] != expected_fingerprint:
            raise ValueError("recovery operational input fingerprint mismatch")
        roots[name] = str(root.absolute())
        del existing
    gc.collect()
    return roots


def _validate_recovery_inventory(reader, expected_tables):
    import polars as pl

    if not isinstance(expected_tables, list) or not expected_tables:
        raise ValueError("recovery requires an independently pinned complete table inventory")
    expected_manifest_tables = []
    paths = {"history_manifest.json"}
    identities = set()
    for table in expected_tables:
        identity = (table["cik"], table["ticker"], table["view"], table["period_class"])
        if identity in identities or set(table["files"]) != {"columns", "rows", "cells"}:
            raise ValueError("recovery table inventory is incomplete or duplicated")
        identities.add(identity)
        files = {}
        for name, info in table["files"].items():
            relative = str(Path(table["cik"]) / table["view"] / table["period_class"] / f"{name}.parquet")
            if info["path"] != relative or relative in paths:
                raise ValueError("recovery dataset inventory path mismatch")
            paths.add(relative)
            path = _history_dataset_path(reader.root, info)
            schema = [[key, str(dtype)] for key, dtype in pl.read_parquet_schema(path).items()]
            if schema != info["schema"]:
                raise ValueError("recovery physical schema mismatch")
            files[name] = {key: value for key, value in info.items() if key != "schema"}
        expected_manifest_tables.append({**table, "files": files})
    if reader.manifest["tables"] != expected_manifest_tables:
        raise ValueError("recovery manifest differs from expected table inventory")
    expected_dirs = {str(parent) for item in paths for parent in Path(item).parents if str(parent) != "."}
    actual_files, actual_dirs = set(), set()
    for path in reader.root.rglob("*"):
        _reject_symlink_components(path)
        relative = str(path.relative_to(reader.root))
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_dirs.add(relative)
        else:
            raise ValueError("recovery unexpected filesystem entry")
    if actual_files != paths or actual_dirs != expected_dirs:
        raise ValueError("recovery unexpected or missing staged files/directories")
    return paths


def _validate_recovery_report(proof: dict[str, Any], report: dict[str, Any] | None = None) -> None:
    """Require pinned full component evidence, never a byte-only integrity report."""
    if report is None:
        evidence = proof["verification_report"]
        report = json.loads(_RecoveryPins().read(Path(evidence["path"]), evidence["sha256"], "independent report"))
    required_flags = (
        "all_reported_files_fully_decoded", "all_ordered_records_hashed",
        "all_json_fields_decoded", "all_physical_hashes_verified", "all_schema_counts_verified",
    )
    if (report.get("schema_version") != "independent-staged-reported-component-audit-v1"
        or report.get("verdict") != "PASS_STAGED_REPORTED_COMPONENT_ONLY"
        or report.get("verification_level") != "FULL_STAGED_REPORTED_PASS"
        or report.get("fixture_kind") not in {"ACTUAL", "CACHED_TEST", "SYNTHETIC_TEST"}
        or report.get("history_ready") is not False
        or any(report.get("full_verification", {}).get(key) is not True for key in required_flags)):
        raise ValueError("recovery report does not attest full staged-reported verification")
    if (report.get("source_generation_sha") != proof["generation_source_identity"]
        or report.get("stage_manifest", {}).get("sha256") != proof["staged_manifest_sha256"]
        or report.get("source_intake", {}).get("sha256") != proof["intake_sha256"]
        or report.get("input_fingerprint") != proof["input_fingerprint"]):
        raise ValueError("recovery report source identity mismatch")
    expected = [table["files"][name] for table in proof["tables"]
                for name in ("columns", "rows", "cells")]
    counts = report.get("counts", {})
    if (type(counts.get("tables")) is not int or counts["tables"] != len(proof["tables"])
        or type(counts.get("stage_files")) is not int or counts["stage_files"] != len(expected)):
        raise ValueError("recovery report incomplete inventory counts")
    verified = report.get("verified_files")
    if not isinstance(verified, list) or len(verified) != len(expected):
        raise ValueError("recovery report incomplete full-record inventory")
    for actual, info in zip(verified, expected, strict=True):
        digest = actual.get("ordered_full_record_sha256")
        if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or {k: v for k, v in actual.items() if k != "ordered_full_record_sha256"} != info):
            raise ValueError("recovery report ordered-record inventory mismatch")
    prefixes = proof.get("required_prefixes")
    checks = report.get("prefix_checks")
    if not isinstance(prefixes, list) or not isinstance(checks, list) or len(prefixes) != len(checks):
        raise ValueError("recovery report incomplete required prefix verification")
    by_path = {info["path"]: info for info in expected}
    for prefix, check in zip(prefixes, checks, strict=True):
        digest = prefix.get("expected_sha256")
        if (prefix.get("path") not in by_path or type(prefix.get("count")) is not int
            or not 0 < prefix["count"] <= by_path[prefix["path"]]["count"]
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or check != {**prefix, "actual_sha256": digest, "status": "PASS"}):
            raise ValueError("recovery report required prefix mismatch")


def recover_reported_history(
    *, staged_publication: Path, output_root: Path, intake_manifest: Path,
    operational_root: Path, attestation: Path, expected_attestation_sha256: str,
    trusted_exclusive_parent: bool,
) -> Path:
    """Copy an independently attested complete stage into a new transaction.

    The caller pins an external attestation SHA; the stage cannot authorize
    itself. Original failed bytes and generation identity remain immutable.
    See company-history-workflow.md for the v1 attestation contract.
    """
    from sec_xbrl.analytics.history_quarters import publish_quarter_history

    if trusted_exclusive_parent is not True:
        raise ValueError("recovery requires explicit trusted exclusive parent acknowledgment")
    for path in (staged_publication, output_root, intake_manifest, operational_root, attestation):
        _reject_symlink_components(path)
    if output_root.exists():
        raise ValueError("recovery requires a new immutable output root")
    if any(output_root.resolve().is_relative_to(root.resolve())
           for root in (staged_publication, operational_root)):
        raise ValueError("recovery output cannot modify an immutable source root")
    pins = _RecoveryPins()
    attestation_bytes = pins.read(attestation, expected_attestation_sha256, "attestation")
    proof = _recovery_json(attestation_bytes)
    if proof.get("version") != "reported-stage-recovery-v1" or proof.get("status") != "PASS":
        raise ValueError("recovery requires an independent complete-stage PASS")
    # These identities identify two separate executions. Neither rewrites the
    # generation source or parser identity recorded by the immutable inputs.
    for key in ("generation_source_identity", "recovery_source_identity"):
        value = proof.get(key)
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("recovery requires pinned generation and recovery source identities")
    evidence_bytes = {}
    for key in ("verification_report", "source_execution_log"):
        evidence = proof[key]
        evidence_bytes[key] = pins.read(Path(evidence["path"]), evidence["sha256"], "independent evidence")
    _validate_recovery_report(proof, _recovery_json(evidence_bytes["verification_report"]))
    manifest_path = staged_publication / "history_manifest.json"
    manifest_bytes = pins.read(manifest_path, proof["staged_manifest_sha256"], "staged manifest")
    intake = json.loads(pins.read(intake_manifest, proof["intake_sha256"], "source intake"))
    _validate_intake(intake)
    source_roots = [staged_publication, operational_root,
                    *(Path(item["source_run"]) for item in intake["filings"])]
    if any(output_root.resolve().is_relative_to(root.resolve()) for root in source_roots):
        raise ValueError("recovery output cannot modify an immutable source root")
    pins.tree(staged_publication)
    reader = HistoryPublicationReader(staged_publication, allow_staging=True)
    pins.check()
    manifest = json.loads(manifest_bytes)
    if reader.manifest != manifest:
        raise ValueError("recovery stage reader differs from pinned manifest bytes")
    if (manifest.get("derived_quarter") is not None
        or manifest.get("quarterly_derivation_status") != "NOT_MATERIALIZED_REPORTED_SERIES_ONLY"
        or manifest["plan"] != proof["plan"] or intake["plan"] != proof["plan"]
        or manifest["views"] != proof["views"]
        or manifest["input_fingerprint"] != proof["input_fingerprint"]
        or Path(manifest["source_intake"]).absolute() != intake_manifest.absolute()):
        raise ValueError("recovery source plan/views/intake/identity mismatch")
    views = proof["views"]
    companies = proof["plan"]["companies"]
    if (not views or len(set(views)) != len(views)
        or set(views) - {"AS_FILED", "LATEST_REPORTED"}
        or not proof["plan"].get("as_of_date") or not companies):
        raise ValueError("recovery expected plan or views are invalid")
    expected_pairs = {(c["cik"], c["ticker"], view) for c in companies for view in views}
    actual_pairs = {(t["cik"], t["ticker"], t["view"]) for t in proof["tables"]}
    if expected_pairs != actual_pairs:
        raise ValueError("recovery company/view inventory mismatch")
    paths = _validate_recovery_inventory(reader, proof["tables"])
    expected_logs = [
        {"stage": "PANEL_WRITTEN", "ticker": t["ticker"], "view": t["view"],
         "period_class": t["period_class"], "rows": t["files"]["rows"]["count"],
         "cells": t["files"]["cells"]["count"]}
        for t in proof["tables"]
    ]
    logs = []
    for line in evidence_bytes["source_execution_log"].splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("stage") == "PANEL_WRITTEN":
            logs.append(record)
    if logs != expected_logs:
        raise ValueError("recovery ordered completed-panel log inventory mismatch")
    reader.verify_all()
    roots = _validate_recovery_sources(
        intake, operational_root, proof["input_fingerprint"], proof["operational_manifest_sha256"], pins
    )
    if manifest.get("operational_roots") != roots:
        raise ValueError("recovery operational roots differ from original generation")
    pins.check()
    output = _RecoveryOutput(output_root)
    reported_pins = None
    receipt = {
        "version": "reported-stage-recovery-v1",
        "attestation": str(attestation.absolute()),
        "attestation_sha256": expected_attestation_sha256,
        "generation_source_identity": proof["generation_source_identity"],
        "recovery_source_identity": proof["recovery_source_identity"],
        "source_stage": str(staged_publication.absolute()),
        "source_manifest_sha256": proof["staged_manifest_sha256"],
        "source_intake_sha256": proof["intake_sha256"],
        "verification_report_sha256": proof["verification_report"]["sha256"],
        "input_fingerprint": proof["input_fingerprint"],
    }

    def guard(path: Path | None = None) -> None:
        output.check()
        pins.check()
        if reported_pins is not None:
            reported_pins.check()
        if path is not None:
            _reject_symlink_components(path)
            if not path.absolute().is_relative_to(output.root):
                raise ValueError("recovery writer path escapes its owned output")
            if path.is_file():
                raise ValueError("recovery refuses to overwrite an existing file")

    token = _HISTORY_STORAGE_GUARD.set(guard)
    access_token = _RECOVERY_OUTPUT.set(output)
    try:
        output.mark_pending(receipt, attestation_bytes, evidence_bytes["verification_report"])
        output.check()
        stage_name = f".panels.partial-{uuid.uuid4().hex}"
        os.mkdir(stage_name, mode=0o700, dir_fd=output.fd)
        staging = output_root / stage_name
        output.write(Path(stage_name) / "history_manifest.json", manifest_bytes)
        payloads = {info["path"]: info for table in proof["tables"] for info in table["files"].values()}
        for relative in sorted(paths - {"history_manifest.json"}):
            _copy_recovery_payload(staged_publication / relative, Path(stage_name) / relative,
                                   payloads[relative]["sha256"], pins, output)
        pins.check()
        output.check()
        copied_pins = _RecoveryPins()
        copied_pins.tree(staging)
        copied_bytes = copied_pins.read(staging / "history_manifest.json", proof["staged_manifest_sha256"], "copied manifest")
        copied = HistoryPublicationReader(staging, allow_staging=True, _recovery_access=output)
        copied_pins.check()
        if copied.manifest != json.loads(copied_bytes):
            raise ValueError("recovery copied reader differs from pinned manifest bytes")
        _validate_recovery_inventory(copied, proof["tables"])
        copied.verify_all()
        copied_pins.check()
        reported = output_root / "reported-panels"
        output.check()
        pins.check()
        output.rename(staging, reported)
        output.check()
        reported_pins = _RecoveryPins()
        reported_pins.tree(reported)
        reported_pins.read(reported / "history_manifest.json", proof["staged_manifest_sha256"], "published manifest")
        guard()
        result = publish_quarter_history(
            publication=reported, output_root=output_root, operational_root=operational_root,
            _recovery_access=output,
        )
        guard()
        if result.absolute() != output.root / "panels":
            raise ValueError("recovery quarter publisher returned an unexpected path")
        consumer_pins = _RecoveryPins()
        consumer_pins.tree(result)
        consumer = HistoryPublicationReader(result, _recovery_access=output)
        consumer.verify_all()
        _validate_completed_recovery_consumer(manifest, consumer.manifest, reported, result,
                                              proof["staged_manifest_sha256"])
        consumer_pins.check()
        guard()
        receipt.update(status="COMPLETE", transaction_sha256=output.marker_sha256,
                       transaction_token=output.transaction["token"],
                       reported_publication=str(reported.absolute()), consumer_publication=str(result.absolute()),
                       consumer_manifest_sha256=_sha256_file(result / "history_manifest.json"))
        consumer_pins.check()
        guard()
        output.commit(receipt)
        return result
    except BaseException:
        # Preserve all artifacts. Ownership uncertainty never authorizes deletion.
        guard()
        raise
    finally:
        _RECOVERY_OUTPUT.reset(access_token)
        _HISTORY_STORAGE_GUARD.reset(token)
        output.close()


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
    recovery = commands.add_parser("recover-reported")
    recovery.add_argument("--trusted-exclusive-parent", action="store_true", required=True)
    recovery.add_argument("--staged-publication", type=Path, required=True)
    recovery.add_argument("--output-root", type=Path, required=True)
    recovery.add_argument("--intake-manifest", type=Path, required=True)
    recovery.add_argument("--operational-root", type=Path, required=True)
    recovery.add_argument("--attestation", type=Path, required=True)
    recovery.add_argument("--expected-attestation-sha256", required=True)
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
    elif args.command == "recover-reported":
        result = recover_reported_history(
            trusted_exclusive_parent=args.trusted_exclusive_parent,
            staged_publication=args.staged_publication, output_root=args.output_root,
            intake_manifest=args.intake_manifest, operational_root=args.operational_root,
            attestation=args.attestation, expected_attestation_sha256=args.expected_attestation_sha256,
        )
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
    # Quarter producers import sec_xbrl.history. Run the CLI in that same
    # module so scoped recovery capabilities/guards have a single owner;
    # executing recovery in __main__ would create separate ContextVars.
    from sec_xbrl.history import main as canonical_main

    canonical_main()
