"""Prepare exact disclosure candidates, review decisions, publish and render.

Rules describe proposals only. Every published interpretation/calculation needs
an explicit decision on the generated immutable candidate ID.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.history import HistoryPublicationReader, _write_records
from sec_xbrl.longitudinal.disclosure_review import (
    DECISION_FIELDS,
    ReviewedPublicationReader,
    candidate_record,
    interpretation_candidate,
    publish_review,
    q4_candidate,
    raw_index,
    read_decision_csv,
    source_evidence,
    timestamp,
)

RULE_FIELDS = ("ticker", "source_view", "fiscal_year", "display_label", "basis_version",
               "target_dimensions", "corroboration", "resolved_issue_ids")


def prepare(*, parent: Path, locators: Path, rules: Path, destination: Path,
            package_roots: list[Path], quality_decisions: Path | None = None) -> Path:
    """Automatically bind locator hints to verified sources and propose A/B.

    Explicit rules are editable proposal configuration, never auto-approval.
    Unmatched source periods are listed; no Q4 is synthesized at preparation.
    """
    if destination.exists():
        raise ValueError("candidate inventory already exists")
    reader = HistoryPublicationReader(parent)
    hints = json.loads(locators.read_text())
    with rules.open(encoding="utf-8-sig", newline="") as stream:
        configuration = csv.DictReader(stream)
        if tuple(configuration.fieldnames or ()) != RULE_FIELDS:
            raise ValueError("invalid proposal rule columns")
        rule_rows = list(configuration)
    quality = []
    if quality_decisions:
        with quality_decisions.open(encoding="utf-8-sig", newline="") as stream:
            quality = list(csv.DictReader(stream))
    candidates, unavailable = [], []
    raw, panels = {}, {}
    for rule in rule_rows:
        ticker = rule["ticker"]
        if ticker not in raw:
            raw[ticker] = raw_index(reader, ticker)
        concepts, facts = raw[ticker]
        found = []
        for period in ("QTD_3M", "YTD_6M", "YTD_9M", "FY"):
            key = (ticker, period, rule["source_view"])
            if key not in panels:
                panels[key] = reader.load(ticker=ticker, period_class=period, view=rule["source_view"])
            panel = panels[key]
            columns = {c["fiscal_time_series_column_id"]: c for c in panel.columns}
            rows = {r["fiscal_time_series_row_id"]: r for r in panel.rows}
            for cell in panel.cells:
                col = columns[cell["fiscal_time_series_column_id"]]
                if col["fiscal_year"] != int(rule["fiscal_year"]) or cell["value_status"] != "REPORTED":
                    continue
                lineage = cell["value_lineage"]
                matching = [h for h in hints if h["accession"].replace("-", "") == lineage["accession"].replace("-", "")
                            and h["label"] == rule["display_label"]
                            and _stable_id("context", lineage["source_filing_id"], h["context_ref"]) == lineage["context_id"]]
                if not matching:
                    continue
                # A source locator hint is not authoritative: concept/context,
                # complete dimensions, value, unit and dates are revalidated.
                validated = []
                raw_fact = facts[lineage["selected_source_fact_id"]]
                packages = [root / raw_fact["source_cik"] / lineage["accession"].replace("-", "") / (lineage["accession"] + "-xbrl.zip") for root in package_roots]
                packages = [p for p in packages if p.is_file()]
                if not packages:
                    raise ValueError("original source package unavailable; collect/reuse Layer1 package first")
                for hint in matching:
                    try:
                        evidence = source_evidence(file=Path(hint["file"]), inline_fact_id=hint["inline_fact_id"],
                                                   lineage=lineage, raw_fact=raw_fact, concepts=concepts, package_zip=packages[0])
                    except ValueError:
                        continue
                    validated.append(evidence)
                if len(validated) != 1:
                    if validated:
                        unavailable.append({"ticker": ticker, "label": rule["display_label"], "period": col["fiscal_label"], "reason": "AMBIGUOUS_SOURCE_CELL"})
                    continue
                dims = [(concepts[d[0]]["qname"], concepts[d[1]]["qname"]) for d in lineage["raw_dimension_signature"]]
                allowed_issues = set(json.loads(rule["resolved_issue_ids"]))
                issues = sorted({q["issue_id"] for q in quality if q["issue_id"] in allowed_issues and q["ticker"] == ticker and q["accession"] == lineage["accession"] and q["concept"] == lineage["raw_concept_qname"] and (q["axis"], q["member"]) in dims})
                candidate = interpretation_candidate(ticker=ticker, view=rule["source_view"], cell=cell,
                                                     row=rows[cell["fiscal_time_series_row_id"]], column=col,
                                                     evidence=validated[0], target_dimensions=json.loads(rule["target_dimensions"]),
                                                     basis_version=rule["basis_version"], resolved_issue_ids=issues,
                                                     corroboration=rule["corroboration"])
                candidates.append(candidate)
                found.append(candidate)
        for p in ("FY", "YTD_9M"):
            if not any(c["period_class"] == p for c in found):
                unavailable.append({"ticker": ticker, "label": rule["display_label"], "period": rule["fiscal_year"], "reason": p + "_INPUT_NOT_BOUND"})
        annual = [c for c in found if c["period_class"] == "FY"]
        ytd = [c for c in found if c["period_class"] == "YTD_9M"]
        if len(annual) == len(ytd) == 1:
            candidates.append(q4_candidate(annual=annual[0], ytd=ytd[0], evidence=rule["corroboration"]))
    unique = {c["candidate_id"]: c for c in candidates}
    destination.mkdir(parents=True)
    info = _write_records(destination / "candidates.parquet", tuple(unique.values()))
    (destination / "inventory.json").write_text(json.dumps({"path": "candidates.parquet", **info}, indent=2))
    with (destination / "review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = (*DECISION_FIELDS, "kind", "ticker", "display_label", "period", "source", "basis", "proposed_inputs")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for c in unique.values():
            row = {**dict.fromkeys(DECISION_FIELDS, ""), "candidate_id": c["candidate_id"], "kind": c["kind"], "ticker": c["ticker"],
                             "display_label": c.get("evidence", {}).get("display_label") if isinstance(c["evidence"], dict) else "Q4",
                             "period": str(c.get("fiscal_year", "")) + " " + c.get("period_class", ""),
                             "source": c["evidence"].get("source_file") if isinstance(c["evidence"], dict) else c["evidence"],
                             "basis": c.get("basis_version", ""), "proposed_inputs": str([c.get("annual_candidate_id"), c.get("ytd_candidate_id")])}
            writer.writerow({key: "'" + value if isinstance(value, str) and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))) else value for key, value in row.items()})
    (destination / "unavailable.json").write_text(json.dumps(unavailable, indent=2))
    return destination


def read_inventory(path: Path) -> list[dict]:
    proxy = object.__new__(HistoryPublicationReader)
    proxy.root = path
    return [candidate_record(r) for r in proxy._records(json.loads((path / "inventory.json").read_text()))]


def render_reviewed(publication: Path, destination: Path, ticker: str) -> None:
    """Render the common persisted reader, never create/move/calculate values."""
    reader = ReviewedPublicationReader(publication)
    panel = reader.load(ticker=ticker)
    rows = [r for r in panel.rows if r.get("reviewed_interpretation")]
    esc = lambda v: html.escape(str(v))
    chunks = ["<!doctype html><meta charset='utf-8'><title>검토된 부문 매출</title><style>body{font:16px system-ui,'Malgun Gothic',sans-serif;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:10px;text-align:right}th:first-child{text-align:left}small{color:#666}</style>",
              f"<h1>{esc(ticker)} 공시 화면 기준 검토 자료</h1><p>백만 USD · D: 승인된 Q4 계산 · 빈칸은 해당 기준으로 제공하지 않는 기간입니다.</p><p>서로 다른 사업 구분은 별도 표입니다. 상위 부문과 그 하위 항목을 중복 합산하지 마십시오.</p>"]
    for basis in sorted({r["basis_version"] for r in rows}):
        selected = [r for r in rows if r["basis_version"] == basis]
        ids = {r["fiscal_time_series_row_id"] for r in selected}
        cells = [c for c in panel.cells if c["fiscal_time_series_row_id"] in ids]
        column_ids = {c["fiscal_time_series_column_id"] for c in cells}
        columns = [c for c in panel.columns if c["fiscal_time_series_column_id"] in column_ids]
        chunks.append(f"<h2>{esc(basis)}</h2><table><tr><th>부문 / 세부 사업</th>" + "".join(f"<th>{esc(c['fiscal_label'])}<br><small>{esc((date.fromisoformat(c['actual_end_date']) - timedelta(days=1)).isoformat())}</small></th>" for c in columns) + "</tr>")
        for row in sorted(selected, key=lambda r: str(r["canonical_dimension_signature"])):
            dims = row["canonical_dimension_signature"]
            # Dimensions are independent lenses, not automatically graph edges.
            names = {"analysis:OperatingSegment": "보고 부문", "analysis:BusinessWithinSegment": "하위 사업", "srt:ConsolidationItemsAxis": "연결 구분"}
            display_dims = sorted(dims, key=lambda d: list(names).index(d[0]) if d[0] in names else len(names))
            chunks.append("<tr><th>" + "<br>".join(esc(names.get(d[0], d[0]) + ": " + ("보고 부문 합계 범위" if d[1] == "us-gaap:OperatingSegmentsMember" else d[1])) for d in display_dims) + "</th>")
            for column in columns:
                found = [c for c in cells if c["fiscal_time_series_row_id"] == row["fiscal_time_series_row_id"] and c["fiscal_time_series_column_id"] == column["fiscal_time_series_column_id"]]
                if len(found) != 1:
                    chunks.append("<td>—</td>")
                    continue
                cell = found[0]
                value = f"{Decimal(cell['value_numeric']) / 1000000:,.0f}" if cell["value_numeric"] is not None else "검토 보류"
                lineage = cell["value_lineage"]
                detail = {"출처": lineage.get("source_accessions") or lineage.get("accession"),
                          "해석 승인": lineage.get("interpretation_decision_id"), "계산 승인": lineage.get("calculation_decision_id"),
                          "원문 근거": lineage.get("reviewed_source_evidence"), "원래 차원": lineage.get("raw_dimension_signature"),
                          "계산식": lineage.get("formula"), "계산 입력": lineage.get("source_analytical_ids")}
                chunks.append(f"<td><details><summary>{esc(value)}{' D' if cell['value_status'] == 'DERIVED' else ''}</summary><pre style='white-space:pre-wrap;max-width:350px'>{esc(json.dumps(detail,ensure_ascii=False,indent=2))}</pre></details></td>")
            chunks.append("</tr>")
        chunks.append("</table>")
    destination.write_text("\n".join(chunks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for name in ("parent", "locators", "rules", "destination"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--quality-decisions", type=Path)
    prep.add_argument("--package-root", dest="package_roots", type=Path, action="append", required=True)
    pub = sub.add_parser("publish")
    for name in ("parent", "inventory", "decisions", "destination"):
        pub.add_argument("--" + name, type=Path, required=True)
    pub.add_argument("--review-as-of", type=timestamp, required=True)
    pub.add_argument("--previous-publication", type=Path)
    pub.add_argument("--quality-decisions", type=Path, required=True)
    render = sub.add_parser("render")
    render.add_argument("--publication", type=Path, required=True)
    render.add_argument("--destination", type=Path, required=True)
    render.add_argument("--ticker", required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "prepare":
        print(prepare(**args))
    elif command == "publish":
        args["candidates"] = read_inventory(args.pop("inventory"))
        args["decisions"] = read_decision_csv(args["decisions"])
        with args["quality_decisions"].open(encoding="utf-8-sig", newline="") as stream:
            args["quality_decisions"] = list(csv.DictReader(stream))
        print(publish_review(**args))
    else:
        render_reviewed(**args)


if __name__ == "__main__":
    main()
