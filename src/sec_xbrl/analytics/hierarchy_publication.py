"""Explicit producer for additive H1/U3-R publication beside frozen U3 v1."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sec_xbrl.analysis import open_analysis
from sec_xbrl.analytics.importance_v2 import (
    POLICY,
    POLICY_VERSION,
    materialize_analytical_v2,
    reviewed_raw_shares,
)
from sec_xbrl.analytics.statement_source import (
    apply_display_reviews,
    prepare_filing,
    read_primary_document,
)
from sec_xbrl.history import _write_records, open_history_publication
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot

VERSION = "h1-h2-source-hierarchy-v1"


def prepare_hierarchy(*, baseline: Path, destination: Path, package_roots: dict[str, str],
                      reviews: list[dict], display_reviews: list[dict], decision_cutoff: str) -> Path:
    """Publish full attested filing contexts; never rerun discovery or v1 policy.

    Source selection is the existing history intake and as-of. The separately
    supplied decision cutoff applies only to new reviews, never retroactively
    to the old source/recast-selection cutoff.
    """
    if destination.exists():
        raise ValueError("new immutable destination required")
    datetime.fromisoformat(decision_cutoff)
    source = open_analysis(baseline)
    # Verify all persisted v1 datasets before copying bytes.
    for ticker, company in source.manifest["companies"].items():
        for view, vi in company["views"].items():
            for name in vi["files"]:
                source._records(ticker, view, name)
    staging = destination.parent / (".partial-" + uuid.uuid4().hex)
    shutil.copytree(baseline, staging)
    manifest = copy.deepcopy(source.manifest)
    manifest.update(publication_id=uuid.uuid4().hex, hierarchy_version=VERSION,
                    baseline_publication_id=source.manifest["publication_id"],
                    baseline_manifest_sha256=hashlib.sha256((baseline / "analysis_manifest.json").read_bytes()).hexdigest(),
                    decision_cutoff=decision_cutoff, importance_v2_policy={"version": POLICY_VERSION, **POLICY})
    applied_display, applied_economic = set(), set()
    for ticker, info in manifest["companies"].items():
        reader = open_history_publication(Path(info["source_publication"]))
        intake_path = Path(reader.manifest["source_intake"])
        intake = json.loads(intake_path.read_text())
        hierarchy = {"files": {}, "filings": {}, "source_intake_sha256": hashlib.sha256(intake_path.read_bytes()).hexdigest(),
                     "source_selection_as_of": info["as_of"], "source_review_cutoff": info["review_cutoff"],
                     "decision_cutoff": decision_cutoff, "warnings": [
                         "원공시 기간·단위·전체 차원을 유지합니다. FY/YTD/QTD/기말을 합산하지 않습니다.",
                         "PRE 표시는 CAL 가감 검증 또는 경제적 구성비 승인이 아닙니다.",
                         "Axis 간 합산·Member 부모/자식 중복 합산은 제공하지 않습니다.",
                         "최신 공시에 없는 주석은 해소·0·현재값으로 대체하지 않습니다.",
                         "LATEST_REPORTED는 CURRENT_COMPARABLE 승인이 아닙니다."]}
        info["hierarchy"] = hierarchy
        catalog = []
        seen = set()
        for entry in intake["filings"]:
            ref = entry["filing"]
            if entry["ticker"] != ticker or ref["filed_date"] > info["as_of"]:
                continue
            identity = (ref["cik"], ref["accession"])
            if identity in seen:
                raise ValueError("duplicate history intake filing")
            seen.add(identity)
            run = Path(entry["source_run"])
            snapshot = _load_declared_cohort_snapshot(run / "snapshots" / ref["cik"] / ref["accession"].replace("-", ""), *identity)
            filing = dict(next(iter(snapshot.records("filing"))))
            if entry["source_run"] not in package_roots:
                raise ValueError("explicit upstream package root adapter required")
            doc = read_primary_document(entry=entry, filing=filing, package_root=Path(package_roots[entry["source_run"]]))
            data = prepare_filing(snapshot=snapshot, document=doc, as_of=info["as_of"])
            applied_display.update(apply_display_reviews(rows=data["source_statement_rows"], tables=data["source_tables"], pre=data["statement_rows"], reviews=display_reviews, decision_cutoff=decision_cutoff))
            scoped = [r for r in reviews if r["scope"]["filing_id"] == filing["filing_id"]]
            data["raw_importance_v2"] = reviewed_raw_shares(facts=data["statement_facts"], tables=data["source_tables"], reviews=scoped, decision_cutoff=decision_cutoff)
            applied_economic.update(r["review_id"] for r in scoped)
            catalog.extend(data["source_tables"])
            files = {}
            for name, records in data.items():
                relative = Path("hierarchy") / ticker / filing["filing_id"] / (name + ".parquet")
                files[name] = {"path": str(relative), **_write_records(staging / relative, tuple(records))}
            hierarchy["filings"][filing["filing_id"]] = {"filing": filing, "files": files,
                                                       "snapshot_manifest_sha256": hashlib.sha256((run / "snapshots" / ref["cik"] / ref["accession"].replace("-", "") / "layer1_manifest.json").read_bytes()).hexdigest()}
        catalog.sort(key=lambda t: (t["filing"]["report_date"], t["filing"]["filed_date"], t["filing"]["accession"], -t["table_order"]), reverse=True)
        relative = Path("hierarchy") / ticker / "source_tables.parquet"
        hierarchy["files"]["source_tables"] = {"path": str(relative), **_write_records(staging / relative, tuple(catalog))}
        for view in info["views"]:
            rows = materialize_analytical_v2(**{name: source._records(ticker, view, name) for name in ("nodes", "edges", "cells", "core_cells")})
            relative = Path("hierarchy") / ticker / view / "importance_v2.parquet"
            info["views"][view]["files"]["importance_v2"] = {"path": str(relative), **_write_records(staging / relative, tuple(rows))}
        print(f"{ticker}: {len(hierarchy['filings'])} filings, {len(catalog)} original tables prepared", flush=True)
    if applied_display != {r["review_id"] for r in display_reviews} or applied_economic != {r["review_id"] for r in reviews}:
        raise ValueError("every approved review must bind an included source")
    (staging / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    staging.rename(destination)
    return destination
