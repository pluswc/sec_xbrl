"""Reusable company report administration: init, register, report, refresh.

Reports only render verified publications; refresh delegates collection and
calculation to the existing history workflow. Quality decisions are an additive
materialized overlay, not edits to reported facts or canonical mappings.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sec_xbrl import history
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot

VERSION = "company-reports-v1"
REVIEW_TIMEZONE = timezone(timedelta(hours=9))
COMPANY_FIELDS = ("active", "ticker", "recent_fiscal_years", "fiscal_start", "fiscal_end", "publication")
DECISION_FIELDS = ("decision_id", "issue_id", "ticker", "accession", "concept", "axis", "member",
                   "decision", "reviewer", "reason", "evidence", "known_at")
SECTIONS = {"IS": "손익계산서", "BS": "재무상태표", "CF": "현금흐름표", "EQ": "자본변동표"}
PERIODS = {"QTD_3M": "분기", "FY": "연간", "YTD_6M": "6개월 누적", "YTD_9M": "9개월 누적", "INSTANT": "기말 잔액"}
TARGET_STATUSES = {"UNSUPPORTED", "PREPARATION_FAILED", "NOT_PREPARED", "REVIEW_REQUIRED", "DISCLOSURE_MISSING", "READY"}
LABELS = {"Revenues": "매출", "RevenueFromContractWithCustomerExcludingAssessedTax": "매출",
          "OperatingIncomeLoss": "영업이익", "NetIncomeLoss": "순이익", "GrossProfit": "매출총이익",
          "Assets": "자산", "Liabilities": "부채", "StockholdersEquity": "자본",
          "NetCashProvidedByUsedInOperatingActivities": "영업활동 현금흐름",
          "NetCashProvidedByUsedInInvestingActivities": "투자활동 현금흐름",
          "NetCashProvidedByUsedInFinancingActivities": "재무활동 현금흐름",
          "CostOfRevenue": "매출원가", "ResearchAndDevelopmentExpense": "연구개발비",
          "SellingGeneralAndAdministrativeExpense": "판매관리비"}
DISPLAY_ORDER = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "CostOfRevenue",
                 "CostOfGoodsAndServicesSold", "GrossProfit", "ResearchAndDevelopmentExpense",
                 "SellingGeneralAndAdministrativeExpense", "OperatingExpenses", "OperatingIncomeLoss",
                 "InterestExpense", "IncomeTaxExpenseBenefit", "NetIncomeLoss", "Assets", "Liabilities",
                 "StockholdersEquity", "NetCashProvidedByUsedInOperatingActivities",
                 "NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInFinancingActivities")


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_csv(path: Path, fields: tuple[str, ...], content: bytes | None = None) -> list[dict[str, str]]:
    with io.StringIO((content if content is not None else path.read_bytes()).decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f"invalid columns: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("malformed CSV row")
    return rows


def _csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]], *, safe: bool = False) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            values = {key: row.get(key, "") for key in fields}
            if safe:
                values = {key: ("'" + value if isinstance(value, str) and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))) else value)
                          for key, value in values.items()}
            writer.writerow(values)


def init_admin(root: Path) -> None:
    """Create empty editable company and append-only quality decision registers."""
    root.mkdir(parents=True, exist_ok=True)
    for name, fields in (("companies.csv", COMPANY_FIELDS), ("decisions.csv", DECISION_FIELDS)):
        if not (root / name).exists():
            _csv(root / name, fields, [])
    if not (root / "target_status.json").exists():
        _json(root / "target_status.json", {})


def set_target_status(root: Path, *, ticker: str, status: str, reason: str | None,
                      evidence: dict[str, Any] | None = None) -> None:
    """Persist an explicit administrator/preparation outcome without inferring absence."""
    if status not in TARGET_STATUSES or status in {"DISCLOSURE_MISSING", "REVIEW_REQUIRED"} and not evidence:
        raise ValueError("target outcome or required evidence is invalid")
    init_admin(root)
    path = root / "target_status.json"
    values = json.loads(path.read_text())
    values[ticker.upper()] = {"status": status, "reason": reason, "evidence": evidence}
    temporary = root / (".target-status-" + uuid.uuid4().hex)
    _json(temporary, values)
    temporary.replace(path)


def read_target_status(root: Path, *, ticker: str) -> dict[str, Any]:
    """Read an administrator target outcome before any consumer bundle exists."""
    path = root / "target_status.json"
    outcome = json.loads(path.read_text()).get(ticker.upper()) if path.exists() else None
    if outcome is None:
        raise ValueError("target is not registered")
    return {"ticker": ticker.upper(), **outcome}


def register_company(root: Path, *, ticker: str, publication: Path | None = None,
                     recent_fiscal_years: int = 3, fiscal_start: int | None = None,
                     fiscal_end: int | None = None, active: bool = True) -> None:
    """Register/update a company without source code changes."""
    init_admin(root)
    ticker = ticker.upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,15}", ticker):
        raise ValueError("invalid ticker")
    if recent_fiscal_years < 1 or (fiscal_start is None) != (fiscal_end is None):
        raise ValueError("invalid fiscal scope")
    if fiscal_start is not None and fiscal_start > fiscal_end:
        raise ValueError("invalid fiscal range")
    current = _read_csv(root / "companies.csv", COMPANY_FIELDS)
    previous = next((row for row in current if row["ticker"] == ticker), {})
    rows = [row for row in current if row["ticker"] != ticker]
    rows.append(dict(zip(COMPANY_FIELDS, ("true" if active else "false", ticker, str(recent_fiscal_years),
                                         fiscal_start or "", fiscal_end or "", str(publication.absolute()) if publication else previous.get("publication", "")))))
    _csv(root / "companies.csv", COMPANY_FIELDS, rows)
    prior_status = json.loads((root / "target_status.json").read_text()).get(ticker, {})
    if prior_status.get("status") != "REVIEW_REQUIRED":
        set_target_status(root, ticker=ticker, status="NOT_PREPARED",
                          reason="SOURCE_REGISTERED" if publication or previous.get("publication") else "REGISTERED_COLLECTION_TARGET",
                          evidence={"source_publication": str(publication.absolute())} if publication else None)


def read_decisions(root: Path, *, review_as_of: date, content: bytes | None = None) -> list[dict[str, str]]:
    """Validate append-only decisions and resolve issue-specific effective state."""
    decisions = _read_csv(root / "decisions.csv", DECISION_FIELDS, content)
    ids: dict[str, dict[str, str]] = {}
    scopes: dict[str, tuple[str, ...]] = {}
    for row in decisions:
        if any(not row[key].strip() for key in ("decision_id", "issue_id", "ticker", "accession", "concept", "reviewer", "reason", "evidence", "known_at")):
            raise ValueError("quality decision requires identity, exact scope, reviewer, reason and evidence")
        if row["decision"] not in {"WARN", "BLOCK", "RELEASE"} or bool(row["axis"]) != bool(row["member"]):
            raise ValueError("invalid decision or dimension scope")
        _decision_time(row["known_at"])
        if row["decision_id"] in ids:
            raise ValueError("duplicate decision ID")
        ids[row["decision_id"]] = row
        scope = tuple(row[key] for key in ("ticker", "accession", "concept", "axis", "member"))
        if row["issue_id"] in scopes and scopes[row["issue_id"]] != scope:
            raise ValueError("issue scope cannot change")
        scopes[row["issue_id"]] = scope
    for snapshot in (root / "runs").glob("*/decisions.csv"):
        if snapshot.parent.name.startswith(".partial-"):
            continue
        previous = _read_csv(snapshot, DECISION_FIELDS)
        if any(ids.get(row["decision_id"]) != row for row in previous):
            raise ValueError("published decisions cannot be edited or deleted; append a new decision")
    by_issue: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in decisions:
        by_issue[row["issue_id"]].append(row)
    active = []
    for rows in by_issue.values():
        rows.sort(key=lambda row: _decision_time(row["known_at"]))
        if len({_decision_time(row["known_at"]) for row in rows}) != len(rows):
            raise ValueError("issue decision timestamp tie; use the actual distinct decision time")
        if rows[0]["decision"] == "RELEASE":
            raise ValueError("RELEASE requires an earlier issue decision")
        cutoff = datetime.combine(review_as_of + timedelta(days=1), time.min, REVIEW_TIMEZONE)
        eligible = [row for row in rows if _decision_time(row["known_at"]) < cutoff]
        if eligible:
            active.append(eligible[-1])
    return active


def _decision_time(value: str) -> datetime:
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.min, REVIEW_TIMEZONE)
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("decision timestamps require an explicit timezone")
    return result


def materialize_quality(*, ticker: str, cell: dict[str, Any], dimensions: list[dict[str, Any]],
                        decisions: list[dict[str, str]], source_scopes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Produce separately persisted analytical availability; never alter raw value."""
    lineage = cell.get("value_lineage", {})
    scopes = [{"accession": lineage.get("accession"), "concept": lineage.get("raw_concept_qname"), "dimensions": dimensions}, *(source_scopes or [])]
    matched = [row for row in decisions if row["ticker"] == ticker and any(
               row["accession"] == scope["accession"] and row["concept"] == scope["concept"]
               and row["issue_id"] not in scope.get("resolved_issue_ids", [])
               and (not row["axis"] or any(d["axis"] == row["axis"] and d["member"] == row["member"] for d in scope["dimensions"])) for scope in scopes)]
    blocked = any(row["decision"] == "BLOCK" for row in matched)
    warnings = [row["reason"] for row in matched if row["decision"] != "RELEASE"]
    if lineage.get("mapping_review_required"):
        warnings.append("항목 연결 검토 필요: 기간 간 같은 의미로 확정되지 않음")
    reason = cell.get("resolution_reason")
    if cell.get("comparability_status") not in {"COMPATIBLE_INPUTS", "COMPARABLE", "BASELINE"}:
        reason = reason or cell.get("comparability_reason")
    if reason:
        warnings.append(str(reason))
    unavailable = cell.get("value_numeric") is None and cell.get("value_text") is None
    if unavailable:
        warnings.append("이 조회에서 대응 값 없음: " + str(cell.get("value_status", "UNKNOWN")))
    return {"quality_status": "BLOCK" if blocked else "UNAVAILABLE" if unavailable else "WARN" if warnings else "AVAILABLE",
            "analytical_value": None if blocked else cell.get("value_numeric"),
            "analytical_text": None if blocked else cell.get("value_text"),
            "quality_reasons": warnings, "decisions": matched}


def _raw_index(reader: history.HistoryPublicationReader, ticker: str) -> tuple[dict, dict]:
    intake = json.loads(Path(reader.manifest["source_intake"]).read_text())
    concepts, facts = {}, {}
    for entry in intake["filings"]:
        if entry["ticker"] != ticker:
            continue
        ref = entry["filing"]
        snapshot = _load_declared_cohort_snapshot(Path(entry["source_run"]) / "snapshots" / ref["cik"] / ref["accession"].replace("-", ""), ref["cik"], ref["accession"])
        concepts.update({row["raw_concept_id"]: row for row in snapshot.records("concept")})
        facts.update({row["fact_id"]: row for row in snapshot.records("fact")})
    return concepts, facts


def _label(qname: str) -> str:
    local = qname.split(":")[-1]
    return LABELS.get(local, re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local))


def _end(value: str | None) -> str:
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat() if value else ""


def _years(reader: history.HistoryPublicationReader, company: dict[str, str]) -> list[int]:
    panel = reader.load(ticker=company["ticker"], period_class="FY")
    years = sorted({int(col["fiscal_year"]) for col in panel.columns if col.get("column_status") == "AVAILABLE"})
    if company["fiscal_start"]:
        requested = list(range(int(company["fiscal_start"]), int(company["fiscal_end"]) + 1))
    else:
        count = int(company["recent_fiscal_years"])
        if count < 1:
            raise ValueError("recent fiscal years must be positive")
        requested = years[-count:]
        if len(requested) != count:
            raise ValueError("insufficient completed fiscal years; run refresh/intake")
    if not requested or set(requested) - set(years):
        raise ValueError("requested fiscal years not published; run refresh/intake")
    return requested


def _company_data(company: dict[str, str], decisions: list[dict[str, str]], review_as_of: date | None = None) -> dict[str, Any]:
    ticker = company["ticker"]
    if not company["publication"]:
        raise ValueError(f"{ticker}: no publication; run refresh to collect/build first")
    reader = history.open_history_publication(Path(company["publication"]))
    if hasattr(reader, "review_manifest") and review_as_of is not None:
        cutoff = datetime.combine(review_as_of + timedelta(days=1), time.min, REVIEW_TIMEZONE)
        if _decision_time(reader.review_manifest["review_as_of"]) >= cutoff:
            raise ValueError("review publication is newer than requested review date; select an earlier immutable publication")
    years = _years(reader, company)
    concepts, facts = _raw_index(reader, ticker)
    tables, quality = [], []
    for period_class in PERIODS:
        matches = [table for table in reader.manifest["tables"] if table["ticker"] == ticker and table["period_class"] == period_class and table["view"] == "LATEST_REPORTED"]
        if not matches:
            continue
        panel = reader.load(ticker=ticker, period_class=period_class)
        columns = [dict(col, display_end_date=_end(col.get("actual_end_date") or col.get("actual_instant_date")))
                   for col in panel.columns if col["fiscal_year"] in years]
        if period_class == "QTD_3M" and {(col["fiscal_year"], col["fiscal_quarter"]) for col in columns} != {(year, q) for year in years for q in range(1, 5)}:
            raise ValueError("requested quarterly coverage incomplete; refresh/build required")
        selected = {col["fiscal_time_series_column_id"] for col in columns}
        cells = []
        for cell in panel.cells:
            if cell["fiscal_time_series_column_id"] not in selected:
                continue
            lineage = cell.get("value_lineage", {})
            for source in lineage.get("source_inputs", []) or [lineage]:
                if cell["value_status"] not in {"REPORTED", "DERIVED"}:
                    continue
                fact = facts.get(source.get("selected_source_fact_id"))
                concept = concepts.get(source.get("raw_concept_id"))
                if not fact or not concept or fact["raw_concept_id"] != source["raw_concept_id"] or fact["filing_id"] != source.get("source_filing_id"):
                    raise ValueError("selected source fact/concept does not resolve in declared raw snapshot")
                if concept["qname"] != source.get("raw_concept_qname"):
                    raise ValueError("selected source QName disagrees with raw concept")
                if any(dim[0] not in concepts or (dim[1] is not None and dim[1] not in concepts) for dim in source.get("raw_dimension_signature", [])):
                    raise ValueError("selected dimensions unresolved in declared raw snapshot")
                if any(concepts[raw_id]["filing_id"] != source["source_filing_id"] for dim in source.get("raw_dimension_signature", []) for raw_id in dim[:2] if raw_id is not None):
                    raise ValueError("selected dimension belongs to a different filing")
            dimensions = [{"axis": concepts.get(dim[0], {}).get("qname", dim[0]),
                           "member": concepts.get(dim[1], {}).get("qname", dim[1]),
                           "typed_member": dim[2], "dimension_type": dim[3], "is_default": dim[4]}
                          for dim in lineage.get("raw_dimension_signature", [])]
            source_scopes = [{"accession": source.get("accession"), "concept": source.get("raw_concept_qname"),
                              "resolved_issue_ids": source.get("resolved_issue_ids", []),
                              "dimensions": [{"axis": concepts.get(dim[0], {}).get("qname", dim[0]), "member": concepts.get(dim[1], {}).get("qname", dim[1])}
                                             for dim in source.get("raw_dimension_signature", [])]} for source in lineage.get("source_inputs", []) or [lineage]]
            # Quality scopes remain RAW; displayed dimensions come only from the
            # persisted, separately approved Analytical interpretation below.
            quality_lineage = {**lineage, "accession": None} if lineage.get("interpretation_decision_id") else lineage
            quality_cell = {**cell, "value_lineage": quality_lineage}
            overlay = materialize_quality(ticker=ticker, cell=quality_cell, dimensions=dimensions, decisions=decisions, source_scopes=source_scopes)
            if lineage.get("analytical_dimensions"):
                dimensions = [{"axis": d[0], "member": d[1], "typed_member": d[2], "dimension_type": d[3], "is_default": d[4]}
                              for d in lineage["analytical_dimensions"]]
                overlay["quality_reasons"].append("공시 화면 기준 검토 완료 · 원래 태그와 판단 근거 보존")
            quality.append({"cell_id": cell["fiscal_time_series_cell_id"], **overlay})
            cells.append({"cell_id": cell["fiscal_time_series_cell_id"], "row_id": cell["fiscal_time_series_row_id"],
                          "column_id": cell["fiscal_time_series_column_id"], "raw_value": cell.get("value_numeric"),
                          "raw_text": cell.get("value_text"), "value_status": cell["value_status"], **overlay,
                          "dimensions": dimensions, "lineage": lineage, "binding": cell.get("binding", {}),
                          "raw_fact": facts.get(lineage.get("selected_source_fact_id")),
                          "unavailable_reason": cell.get("resolution_reason") or cell.get("comparability_reason")})
        ids = {cell["row_id"] for cell in cells}
        rows = []
        for row in panel.rows:
            if row["fiscal_time_series_row_id"] not in ids:
                continue
            evidence = [edge for cell in cells if cell["row_id"] == row["fiscal_time_series_row_id"]
                        for edge in cell["binding"].get("primary_statement_evidence", [])]
            sections = sorted({kind for edge in evidence for kind in edge.get("statement_types", [])})
            rows.append({"row_id": row["fiscal_time_series_row_id"], "qname": row["raw_concept_qname"],
                         "company_canonical_concept_id": row.get("company_canonical_concept_id"),
                         "label": _label(row["raw_concept_qname"]) + (" [검토 기준: " + row["basis_version"] + "]" if row.get("reviewed_interpretation") else " [원문 태그 기준]" if row.get("raw_tag_view") and row.get("canonical_dimension_signature") else ""), "line_class": row["line_class"],
                         "sections": sections, "dimensioned": bool(row.get("canonical_dimension_signature")),
                         "mapping_review_required": row.get("mapping_review_required"),
                         "navigation": row.get("first_definition", {}).get("relationship_navigation", [])})
        rows.sort(key=lambda row: (DISPLAY_ORDER.index(row["qname"].split(":")[-1]) if row["qname"].split(":")[-1] in DISPLAY_ORDER else len(DISPLAY_ORDER), row["label"], row["row_id"]))
        tables.append({"period_class": period_class, "scope": panel.scope, "columns": columns, "rows": rows, "cells": cells})
    return {"ticker": ticker, "years": years, "publication": company["publication"],
            "source_manifest_sha256": hashlib.sha256((reader.root / "history_manifest.json").read_bytes()).hexdigest(),
            "review_manifest_sha256": hashlib.sha256((Path(company["publication"]) / "review_manifest.json").read_bytes()).hexdigest() if hasattr(reader, "review_manifest") else None,
            "interpretation_review_as_of": reader.review_manifest["review_as_of"] if hasattr(reader, "review_manifest") else None,
            "tables": tables, "quality_overlay": quality}


def _number(cell: dict[str, Any]) -> str:
    if cell["quality_status"] == "BLOCK":
        return "확인 필요 ⛔"
    value = cell["analytical_value"]
    if value is None:
        return "텍스트 (출처 보기)" if cell["analytical_text"] else "— 확인 필요"
    unit = cell["lineage"].get("unit_numerator_measures")
    denominator = cell["lineage"].get("unit_denominator_measures")
    text = f"{Decimal(value) / 1000000:,.3f}" if unit == '["iso4217:USD"]' and denominator == "[]" else str(value)
    return text + (" D" if cell["value_status"] == "DERIVED" else "") + (" ⚠" if cell["quality_status"] == "WARN" else "")


def _display_unit(cell: dict[str, Any]) -> str:
    lineage = cell.get("lineage", {})
    numerator = lineage.get("unit_numerator_measures")
    denominator = lineage.get("unit_denominator_measures")
    if numerator == '["iso4217:USD"]' and denominator == "[]":
        return "백만 USD"
    def names(value: Any) -> str:
        entries = json.loads(value) if isinstance(value, str) else value or []
        return " × ".join({"xbrli:shares": "주", "xbrli:pure": "비율·배수(원값)"}.get(item, item.split(":")[-1]) for item in entries)
    top, bottom = names(numerator), names(denominator)
    return (top + (" / " + bottom if bottom else "")) or "단위 미제공"


def render_company(data: dict[str, Any], destination: Path, review_as_of: date) -> None:
    """Render already materialized quality/values; no analytical calculations."""
    esc = lambda value: html.escape(str(value), quote=True)
    chunks = ["<!doctype html><html lang='ko'><meta charset='utf-8'><title>" + esc(data["ticker"]) + " 재무 분석</title>",
              "<style>body{font:15px system-ui,'Malgun Gothic','Noto Sans CJK KR',sans-serif;margin:24px;color:#172230}table{border-collapse:collapse;font-size:12px}th,td{padding:7px;border:1px solid #ddd;white-space:nowrap;text-align:right}th:first-child{text-align:left;position:sticky;left:0;background:#fff;max-width:260px;white-space:normal;overflow-wrap:anywhere;min-width:210px}details{margin:14px 0}summary{cursor:pointer;font-weight:bold}.scroll{overflow:auto}a{color:#1764a0}:target{background:#fff0ba}</style>",
              f"<h1>{esc(data['ticker'])} 최근 완료된 {len(data['years'])}개 회계연도</h1>",
              f"<p>FY {esc(data['years'])} · 관리자 검토 기준 {review_as_of} · 금액은 백만 USD(그 외 단위는 출처 참조). D: 계산된 분기, ⚠: 비교 주의, ⛔: 분석 사용 보류.</p>",
              "<p>보유 자료를 조회한 결과이며 SEC 최신 재수집을 의미하지 않습니다. 빈칸은 0이 아닙니다. 기업별 세부항목의 Q4를 임의로 계산하지 않습니다.</p>",
              "<p><a href='cells.csv'>전체 값 CSV</a> · <a href='data.json'>전체 출처·원문 값</a> · <a href='review_queue.csv'>관리자 검토 대기 목록</a></p>",
              "<script>function reveal(id){const e=document.getElementById(id);if(e){let p=e.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}e.scrollIntoView();}}</script>"]
    csv_rows = []
    for table in data["tables"]:
        chunks.append(f"<h2>{esc(PERIODS[table['period_class']])}</h2><p>공시 조회 기준: {esc(table['scope']['selection_as_of_date'])}</p>")
        index = {(cell["row_id"], cell["column_id"]): cell for cell in table["cells"]}
        representatives = {cell["row_id"]: cell for cell in table["cells"]}
        for section, title in [*SECTIONS.items(), ("DETAIL", "기업별 세부항목·주석 전체")]:
            rows = [row for row in table["rows"] if row["dimensioned"] or not set(row["sections"]).intersection(SECTIONS)] if section == "DETAIL" else [row for row in table["rows"] if section in row["sections"] and not row["dimensioned"]]
            chunks.append(f"<details {'open' if section == 'IS' and table['period_class'] == 'QTD_3M' else ''}><summary>{esc(title)} ({len(rows)}행)</summary><div class='scroll'><table><tr><th>항목</th>")
            for col in table["columns"]:
                chunks.append(f"<th>{esc(col['fiscal_label'])}<br>{esc(col['display_end_date'])}</th>")
            chunks.append("</tr>")
            for row in rows:
                representative = representatives.get(row["row_id"], {})
                dims = "; ".join(f"{_label(d['axis'])}: {_label(d['member'] or '')}" for d in representative.get("dimensions", []))
                origin = {"COMMON_GAAP": "공통 회계항목", "COMPANY_CUSTOM": "기업별 항목"}.get(row["line_class"], "기타 항목")
                anchor = table["period_class"] + "-" + row["row_id"] + "-" + section
                links = []
                if not row["dimensioned"] and row.get("company_canonical_concept_id"):
                    related = [item for item in table["rows"] if item["dimensioned"] and item.get("company_canonical_concept_id") == row["company_canonical_concept_id"]]
                    for item in related:
                        target = table["period_class"] + "-" + item["row_id"] + "-DETAIL"
                        # IDs originate in verified producer; JSON string escaping is
                        # still required when placed inside an HTML event attribute.
                        action = "reveal(" + json.dumps(target) + ")"
                        member_labels = "; ".join(_label(dim["member"] or dim.get("typed_member") or "") for dim in representatives.get(item["row_id"], {}).get("dimensions", []))
                        links.append(f"<a href='#{esc(target)}' onclick='{esc(action)}'>{esc(member_labels or item['label'])}</a>")
                navigation = f"<details><summary>관련 세부항목 {len(links)}개</summary>{' · '.join(links)}</details>" if links else ""
                chunks.append(f"<tr id='{esc(anchor)}'><th title='{esc(row['qname'])}'>{esc(row['label'])}<br><small>{esc(dims)} · {esc(origin)} · {esc(_display_unit(representative))}</small>{navigation}</th>")
                for col in table["columns"]:
                    cell = index.get((row["row_id"], col["fiscal_time_series_column_id"]))
                    if not cell:
                        reason = "이 조회에서 대응 값 없음"
                        if table["period_class"] == "QTD_3M" and col["fiscal_quarter"] == 4 and (row["line_class"] == "COMPANY_CUSTOM" or row["dimensioned"]):
                            reason += "; 기업별 세부항목 분기 계산 미승인/미제공"
                        chunks.append(f"<td title='{esc(reason)}'>— 값 없음</td>")
                        continue
                    detail = {"선택/계산된 값": cell["raw_value"], "주의": cell["quality_reasons"], "계산식": cell["lineage"].get("formula"),
                              "공시": cell["lineage"].get("accession") or cell["lineage"].get("source_accessions"),
                              "단위": cell["lineage"].get("unit_numerator_measures"), "분모 단위": cell["lineage"].get("unit_denominator_measures"),
                              "출처 ID": cell["cell_id"], "전체 출처": "data.json에서 출처 ID로 검색"}
                    chunks.append(f"<td><details><summary>{esc(_number(cell))}</summary><pre style='text-align:left;white-space:pre-wrap;max-width:420px'>{esc(json.dumps(detail, ensure_ascii=False, indent=2))}</pre></details></td>")
                chunks.append("</tr>")
            chunks.append("</table></div></details>")
        row_index = {row["row_id"]: row for row in table["rows"]}
        col_index = {col["fiscal_time_series_column_id"]: col for col in table["columns"]}
        for cell in table["cells"]:
            row = row_index[cell["row_id"]]
            csv_rows.append({"ticker": data["ticker"], "period_class": table["period_class"], "period": col_index[cell["column_id"]]["fiscal_label"],
                             "row_id": cell["row_id"], "concept": row["qname"], "dimensions": json.dumps(cell["dimensions"], ensure_ascii=False),
                             "value": Decimal(cell["analytical_value"]) if cell["analytical_value"] is not None else None, "status": cell["value_status"], "quality": cell["quality_status"],
                             "reason": "; ".join(cell["quality_reasons"]), "accession": cell["lineage"].get("accession", ""),
                             "unit": str(cell["lineage"].get("unit_numerator_measures", "")), "cell_id": cell["cell_id"]})
    chunks.append("</html>")
    destination.mkdir(parents=True)
    (destination / "index.html").write_text("\n".join(chunks), encoding="utf-8")
    _json(destination / "data.json", data)
    _csv(destination / "cells.csv", ("ticker", "period_class", "period", "row_id", "concept", "dimensions", "value", "status", "quality", "reason", "accession", "unit", "cell_id"), csv_rows, safe=True)
    queue = {}
    for table in data["tables"]:
        for cell in table["cells"]:
            if cell["quality_status"] not in {"WARN", "BLOCK"} or not cell["lineage"].get("accession"):
                continue
            existing = [item for item in cell["decisions"] if item["decision"] != "RELEASE"]
            if existing:
                for item in existing:
                    queue[item["issue_id"]] = {**item, "decision_id": "", "decision": "", "reviewer": "", "known_at": "",
                                              "current_status": cell["quality_status"], "source_cell_id": cell["cell_id"]}
                continue
            for dimension in cell["dimensions"] or [{"axis": "", "member": ""}]:
                if dimension.get("typed_member"):
                    continue  # typed review cannot pretend to be an explicit member scope
                scope = (data["ticker"], cell["lineage"]["accession"], cell["lineage"].get("raw_concept_qname", ""), dimension["axis"], dimension["member"])
                key = hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:20]
                queue[key] = {**dict.fromkeys(DECISION_FIELDS, ""), "issue_id": "review-" + key,
                              **dict(zip(("ticker", "accession", "concept", "axis", "member"), scope)),
                              "reason": "; ".join(cell["quality_reasons"]), "current_status": cell["quality_status"],
                              "source_cell_id": cell["cell_id"]}
    _csv(destination / "review_queue.csv", (*DECISION_FIELDS, "current_status", "source_cell_id"), list(queue.values()), safe=True)


def report(root: Path, *, review_as_of: date) -> Path:
    """Create an immutable run from current admin settings and cached publications."""
    settings = {name: (root / name).read_bytes() for name in ("companies.csv", "decisions.csv")}
    decisions = read_decisions(root, review_as_of=review_as_of, content=settings["decisions.csv"])
    companies = _read_csv(root / "companies.csv", COMPANY_FIELDS, settings["companies.csv"])
    _validate_companies(companies)
    active = [row for row in companies if row["active"] == "true"]
    if not active:
        raise ValueError("no active companies")
    data = [_company_data(company, decisions, review_as_of) for company in active]
    run_id = uuid.uuid4().hex
    staging = root / "runs" / (".partial-" + run_id)
    staging.mkdir(parents=True)
    for name in ("companies.csv", "decisions.csv"):
        (staging / name).write_bytes(settings[name])
    for company in data:
        render_company(company, staging / company["ticker"], review_as_of)
    _json(staging / "manifest.json", {"version": VERSION, "review_as_of": review_as_of, "mode": "EXISTING_PUBLICATION_ONLY",
                                    "companies": [{key: company[key] for key in ("ticker", "years", "publication", "source_manifest_sha256")} for company in data]})
    (staging / "index.html").write_text("<meta charset='utf-8'><h1>기업별 재무 분석</h1>" + "".join(f"<p><a href='{html.escape(c['ticker'])}/index.html'>{html.escape(c['ticker'])}</a></p>" for c in data), encoding="utf-8")
    final = root / "runs" / run_id
    staging.rename(final)
    return final


def refresh(root: Path, *, as_of: date, review_as_of: date, workspace: Path,
            source_runs: tuple[Path, ...] = (), submissions_roots: tuple[Path, ...] = (),
            offline: bool = False, bootstrap_taxonomy: bool = False,
            tickers: tuple[str, ...] | None = None, render_report: bool = True) -> Path:
    """Collect/build using the existing history workflow, then use the same report path."""
    original_settings = (root / "companies.csv").read_bytes()
    companies = _read_csv(root / "companies.csv", COMPANY_FIELDS, original_settings)
    _validate_companies(companies)
    if tickers and {t.upper() for t in tickers} - {c["ticker"] for c in companies if c["active"] == "true"}:
        raise ValueError("requested refresh companies not active/registered")
    run = workspace / uuid.uuid4().hex
    for company in companies:
        if company["active"] != "true" or (tickers and company["ticker"] not in {t.upper() for t in tickers}):
            continue
        # Explicit fiscal label ranges still need discovery through latest FY:
        # load enough annual baselines, then report validates exact fiscal labels.
        count = int(company["recent_fiscal_years"])
        if company["fiscal_start"]:
            count = max(count, as_of.year - int(company["fiscal_start"]) + 2)
        scope = run / company["ticker"]
        try:
            plan = history.discover_history(workspace=scope / "discovery", tickers=(company["ticker"],), as_of=as_of,
                                            recent_fiscal_years=count, submissions_roots=submissions_roots, offline=offline)
            intake = history.ingest_history(plan_path=plan, source_runs=source_runs, output_run=scope / "intake",
                                            package_cache=workspace / "packages", index_cache=workspace / "indices",
                                            taxonomy_cache=workspace / "taxonomy", bootstrap_taxonomy=bootstrap_taxonomy)
            publication = history.build_history(intake_manifest=intake, output_root=scope / "analytical")
        except Exception as exc:
            set_target_status(root, ticker=company["ticker"], status="PREPARATION_FAILED", reason=str(exc),
                              evidence={"stage_root": str(scope.absolute())})
            raise
        if company.get("publication") and (Path(company["publication"]) / "review_manifest.json").exists():
            # Preserve exact-source decisions and quarantines. New filing
            # identities never inherit a one-off interpretation approval.
            from datetime import datetime, time

            from sec_xbrl.longitudinal.disclosure_review import (
                ReviewedPublicationReader,
                publish_review,
            )
            old = ReviewedPublicationReader(Path(company["publication"]))
            new_accessions = []
            try:
                old_intake = json.loads(Path(old.manifest["source_intake"]).read_text())
                new_manifest = json.loads((publication / "history_manifest.json").read_text())
                new_intake = json.loads(Path(new_manifest["source_intake"]).read_text())
                known = {entry["filing"]["accession"] for entry in old_intake["filings"] if entry["ticker"] == company["ticker"]}
                new_accessions = sorted({entry["filing"]["accession"] for entry in new_intake["filings"] if entry["ticker"] == company["ticker"]} - known)
                if new_accessions:
                    raise ValueError("new filing interpretation needs explicit review; old exact approvals cannot expand")
                publication = publish_review(
                    parent=publication, destination=scope / "reviewed",
                    candidates=list(old.records("candidates")),
                    decisions=list(old.records("decisions")),
                    quality_decisions=list(old.records("quality_decisions")),
                    review_as_of=datetime.combine(review_as_of, time.max, UTC),
                    previous_publication=Path(company["publication"]),
                )
            except ValueError as exc:
                # Registration is committed only after every company succeeds.
                # Keep collected/new Analytical data available for the admin.
                (scope / "review_refresh_required.json").write_text(json.dumps({
                    "ticker": company["ticker"], "status": "REVIEW_REBIND_REQUIRED",
                    "previous_publication": company["publication"],
                    "prepared_parent": str(publication.absolute()), "reason": str(exc),
                    "new_accessions_requiring_review": new_accessions,
                    "policy": "EXACT_SOURCE_APPROVAL_ONLY_REGISTRATION_UNCHANGED",
                }, indent=2))
                set_target_status(root, ticker=company["ticker"], status="REVIEW_REQUIRED", reason=str(exc),
                                  evidence={"prepared_parent": str(publication.absolute()),
                                            "new_accessions": new_accessions})
                raise ValueError(f"{company['ticker']}: review rebind required; previous registration preserved; prepared data: {scope}") from exc
        company["publication"] = str(publication.absolute())
        set_target_status(root, ticker=company["ticker"], status="NOT_PREPARED",
                          reason="ANALYTICAL_READY_CONSUMER_NOT_PREPARED",
                          evidence={"source_publication": company["publication"]})
    if (root / "companies.csv").read_bytes() != original_settings:
        raise ValueError("company settings changed during refresh; generated history retained, retry with current settings")
    _csv(root / "companies.csv", COMPANY_FIELDS, companies)
    return report(root, review_as_of=review_as_of) if render_report else run


def _validate_companies(companies: list[dict[str, str]]) -> None:
    if len({row["ticker"] for row in companies}) != len(companies):
        raise ValueError("duplicate ticker")
    for row in companies:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,15}", row["ticker"]) or row["active"] not in {"true", "false"}:
            raise ValueError("invalid ticker or active setting")
        if int(row["recent_fiscal_years"]) < 1 or bool(row["fiscal_start"]) != bool(row["fiscal_end"]):
            raise ValueError("invalid fiscal scope")
        if row["fiscal_start"] and not 1900 <= int(row["fiscal_start"]) <= int(row["fiscal_end"]) <= 9999:
            raise ValueError("invalid fiscal range")
        if row["publication"] and not Path(row["publication"]).is_absolute():
            raise ValueError("publication path must be absolute")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    register = sub.add_parser("register")
    register.add_argument("ticker")
    register.add_argument("--publication", type=Path)
    register.add_argument("--years", type=int, default=3)
    register.add_argument("--fiscal-start", type=int)
    register.add_argument("--fiscal-end", type=int)
    for command in ("report", "refresh"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--review-as-of", type=date.fromisoformat, required=True)
        if command == "refresh":
            cmd.add_argument("--as-of", type=date.fromisoformat, required=True)
            cmd.add_argument("--workspace", type=Path, required=True)
            cmd.add_argument("--source-run", type=Path, action="append", default=[])
            cmd.add_argument("--submissions-root", type=Path, action="append", default=[])
            cmd.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        init_admin(args.admin)
    elif args.command == "register":
        register_company(args.admin, ticker=args.ticker, publication=args.publication, recent_fiscal_years=args.years,
                         fiscal_start=args.fiscal_start, fiscal_end=args.fiscal_end)
    elif args.command == "report":
        print(report(args.admin, review_as_of=args.review_as_of))
    else:
        print(refresh(args.admin, as_of=args.as_of, review_as_of=args.review_as_of, workspace=args.workspace,
                      source_runs=tuple(args.source_run), submissions_roots=tuple(args.submissions_root), offline=args.offline))


if __name__ == "__main__":
    main()
