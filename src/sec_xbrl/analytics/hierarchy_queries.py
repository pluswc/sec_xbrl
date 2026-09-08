"""Read-only projections of prepared hierarchy datasets. No producer imports."""
from __future__ import annotations

import copy
from collections import defaultdict


def statement_catalog(client, ticker: str, *, section: str | None = None) -> dict:
    tables = client._hierarchy_records(ticker, "source_tables")
    if section is not None:
        tables = [t for t in tables if t["section"] == section]
    return copy.deepcopy({"publication_id": client.manifest["publication_id"], "ticker": ticker.upper(),
                          "tables": tables, "decision_cutoff": client.manifest["decision_cutoff"],
                          "warnings": client.manifest["companies"][ticker.upper()]["hierarchy"]["warnings"]})


def statement(client, ticker: str, table_id: str) -> dict:
    tables = [t for t in client._hierarchy_records(ticker, "source_tables") if t["table_id"] == table_id]
    if len(tables) != 1:
        raise ValueError("table is not uniquely prepared for this company")
    table = tables[0]
    filing_id = table["filing_id"]
    rows = [r for r in client._hierarchy_records(ticker, "source_statement_rows", filing_id) if r["table_id"] == table_id]
    # Sets deduplicate references, not reported observations with distinct IDs.
    ids = {r["fact_id"] for row in rows for c in row["cells"] for r in c["inline_facts"] if r["fact_id"]}
    facts = [f for f in client._hierarchy_records(ticker, "statement_facts", filing_id) if f["fact_id"] in ids]
    checks = [c for c in client._hierarchy_records(ticker, "calculation_checks", filing_id)
              if c["parent_fact_id"] in ids or (c["network_identity"]["role_id"] == table["role_id"] and c["status"] == "MISSING_PARENT")]
    pre = [p for p in client._hierarchy_records(ticker, "statement_rows", filing_id) if p["network_identity"]["role_id"] == table["role_id"]]
    raw_ids = {f["raw_concept_id"] for f in facts}
    importance = [r for r in client._hierarchy_records(ticker, "raw_importance_v2", filing_id) if r["current_fact_id"] in ids]
    return copy.deepcopy({"publication_id": client.manifest["publication_id"], "table": table, "rows": rows, "facts": facts,
                          "checks": checks, "pre_rows": pre, "pre_not_in_html": [p["row_id"] for p in pre if p["raw_concept_id"] not in raw_ids],
                          "importance": importance, "warnings": client.manifest["companies"][ticker.upper()]["hierarchy"]["warnings"]})


def axes(client, ticker: str, filing_id: str, *, raw_concept_id: str | None = None) -> dict:
    facts = client._hierarchy_records(ticker, "statement_facts", filing_id)
    if raw_concept_id and raw_concept_id not in {f["raw_concept_id"] for f in facts}:
        raise ValueError("concept is not prepared in this filing")
    result = {}
    for fact in facts:
        if raw_concept_id and fact["raw_concept_id"] != raw_concept_id:
            continue
        for d in fact["scope"]["dimensions"]:
            lens = result.setdefault(d["axis"], {"axis_id": d["axis"], "qname": d["axis_qname"], "members": {}})
            key = (d["member"], d["typed_value"], d["is_default"])
            lens["members"][key] = {"member_id": d["member"], "qname": d["member_qname"], "typed_value": d["typed_value"], "is_default": d["is_default"]}
    return copy.deepcopy({"filing_id": filing_id, "raw_concept_id": raw_concept_id,
                          "axes": [{**lens, "members": list(lens["members"].values())} for lens in result.values()],
                          "warning": "독립 Axis. 전체 차원 조합이 다른 값은 합산하지 않습니다."})


def member_metrics(client, ticker: str, filing_id: str, *, axis_id: str, member_id: str | None,
                   typed_value: str | None = None, raw_concept_id: str | None = None) -> dict:
    known = axes(client, ticker, filing_id)
    lenses = [a for a in known["axes"] if a["axis_id"] == axis_id]
    if len(lenses) != 1 or not any(m["member_id"] == member_id and m["typed_value"] == typed_value for m in lenses[0]["members"]):
        raise ValueError("axis/member is not a known prepared filing scope")
    all_facts = client._hierarchy_records(ticker, "statement_facts", filing_id)
    if raw_concept_id and raw_concept_id not in {f["raw_concept_id"] for f in all_facts}:
        raise ValueError("concept is not prepared in this filing")
    facts = [f for f in all_facts
             if (not raw_concept_id or f["raw_concept_id"] == raw_concept_id) and any(
                 d["axis"] == axis_id and d["member"] == member_id and d["typed_value"] == typed_value for d in f["scope"]["dimensions"])]
    paths = [p for p in client._hierarchy_records(ticker, "member_paths", filing_id) if p["axis_id"] == axis_id]
    return copy.deepcopy({"filing_id": filing_id, "axis_id": axis_id, "member_id": member_id,
                          "facts": facts, "member_paths": paths, "aggregation_status": "NOT_AUTHORIZED",
                          "status": "DISCLOSED" if facts else "NOT_DISCLOSED_IN_THIS_FILING",
                          "warnings": ["공시된 지표와 전체 차원만 반환합니다. 세그먼트 손익의 정의는 연결 영업이익과 같다고 가정하지 않습니다."]})


def pre_table(client, ticker: str, table_id: str) -> dict:
    """One ordered PRE table, with all Raw contexts kept in each row's cells."""
    panel = statement(client, ticker, table_id)
    filing_id = panel["table"]["filing_id"]
    facts = client._hierarchy_records(ticker, "statement_facts", filing_id)
    by_concept = defaultdict(list)
    for fact in facts:
        if not fact["scope"]["dimensions"]:
            by_concept[fact["raw_concept_id"]].append(fact)
    for row in panel["pre_rows"]:
        row["facts"] = copy.deepcopy(by_concept[row["raw_concept_id"]])
        row["protected"] = bool(row["cycle"]) or any(f["calculation_check_ids"] for f in row["facts"])
    return panel
