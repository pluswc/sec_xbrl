"""Small, read-only investor analysis functions over a prepared Parquet bundle.

Use prepare_analysis/refresh_analysis separately. Queries never open SEC/raw
files, select a filing version, infer relationships or calculate metrics.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.importance import (
    DEFAULT_TOP,
    POLICY_ID,
    POLICY_VERSION,
    materialize_importance,
)
from sec_xbrl.analytics.investor_metrics import materialize_metrics
from sec_xbrl.history import HistoryPublicationReader, _write_records, open_history_publication

VERSION = "consumer-focused-analysis-v1"
CORE = [
    ("revenue", "매출", "IS", "QTD_3M", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]),
    ("cost", "매출원가", "IS", "QTD_3M", ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
    ("gross_profit", "매출총이익", "IS", "QTD_3M", ["GrossProfit"]),
    ("research", "연구개발비", "IS", "QTD_3M", ["ResearchAndDevelopmentExpense"]),
    ("operating_income", "영업이익", "IS", "QTD_3M", ["OperatingIncomeLoss"]),
    ("net_income", "순이익", "IS", "QTD_3M", ["NetIncomeLoss"]),
    ("eps", "희석 주당이익", "IS", "QTD_3M", ["EarningsPerShareDiluted"]),
    ("cfo", "영업활동 현금흐름", "CF", "QTD_3M", ["NetCashProvidedByUsedInOperatingActivities"]),
    ("capex", "유형자산 취득 지출", "CF", "QTD_3M", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("cfi", "투자활동 현금흐름", "CF", "QTD_3M", ["NetCashProvidedByUsedInInvestingActivities"]),
    ("cff", "재무활동 현금흐름", "CF", "QTD_3M", ["NetCashProvidedByUsedInFinancingActivities"]),
    ("cash", "현금 및 현금성자산", "BS", "INSTANT", ["CashAndCashEquivalentsAtCarryingValue"]),
    ("assets", "자산", "BS", "INSTANT", ["Assets"]),
    ("current_assets", "유동자산", "BS", "INSTANT", ["AssetsCurrent"]),
    ("receivables", "매출채권", "BS", "INSTANT", ["AccountsReceivableNetCurrent"]),
    ("inventory", "재고자산", "BS", "INSTANT", ["InventoryNet"]),
    ("liabilities", "부채", "BS", "INSTANT", ["Liabilities"]),
    ("current_liabilities", "유동부채", "BS", "INSTANT", ["LiabilitiesCurrent"]),
    ("debt", "장단기 차입금", "BS", "INSTANT", ["DebtLongtermAndShorttermCombinedAmount"]),
    ("equity", "자본", "EQ", "INSTANT", ["StockholdersEquity"]),
    ("shares", "발행 보통주 수", "EQ", "INSTANT", ["CommonStockSharesOutstanding"]),
    ("repurchases", "자사주 취득 지출", "EQ", "QTD_3M", ["PaymentsForRepurchaseOfCommonStock"]),
    ("stock_compensation", "주식보상비용", "EQ", "QTD_3M", ["ShareBasedCompensation"]),
]


def stable(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def display_name(value: str) -> str:
    local = str(value).split(":")[-1]
    local = re.sub(r"(?:Member|Axis|Domain)$", "", local)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local)


def default_profile() -> list[dict]:
    return [{"row_id": key, "label": label, "section": section, "period_class": period,
             "concepts": ["us-gaap:" + q for q in concepts], "required": True}
            for key, label, section, period, concepts in CORE]


def _apply_lens_preferences(nodes: dict[str, dict], preferences: list[dict]) -> None:
    """Only customize existing display nodes; never create edges or identity."""
    allowed = {"lens_type", "role_uri", "basis_version", "anchor_row_id", "node_id", "axis_signature"}
    for preference in preferences:
        selectors = preference.get("match", {})
        if not selectors or set(selectors) - allowed:
            raise ValueError("lens preference needs explicit supported selectors")
        signature = selectors.get("axis_signature")
        if "axis_signature" in selectors and (not isinstance(signature, list) or not all(isinstance(a, str) for a in signature) or len(signature) != len(set(signature))):
            raise ValueError("axis_signature must be a unique complete list of axis identities")
        for node in nodes.values():
            if node["kind"] != "LENS":
                continue
            dimensions = node.get("dimensions") or []
            axes = [d if isinstance(d, str) else d[0] for d in dimensions]
            if all(sorted(axes) == sorted(v) if k == "axis_signature" else node.get(k) == v for k, v in selectors.items()):
                node.update({k: preference[k] for k in ("label", "display_order", "hidden") if k in preference})


def _table(root: Path, info: dict) -> list[dict]:
    proxy = object.__new__(HistoryPublicationReader)
    proxy.root = root
    return list(proxy._records(info))


class AnalysisClient:
    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.is_symlink() or self.root.name.startswith(".partial-"):
            raise ValueError("unpublished analysis bundle")
        self.manifest = json.loads((self.root / "analysis_manifest.json").read_text())
        if self.manifest["version"] != VERSION:
            raise ValueError("unsupported analysis bundle")
        self._cache: dict[tuple, list[dict]] = {}
        from sec_xbrl.analytics.axis_timeseries_queries import load_axis_manifest
        self.axis_manifest = load_axis_manifest(self.root, self.manifest)
        self._axis_cache: dict[tuple, dict[str, Any]] = {}

    def _records(self, ticker: str, view: str, name: str) -> list[dict]:
        key = (ticker.upper(), view, name)
        if key not in self._cache:
            try:
                info = self.manifest["companies"][key[0]]["views"][view]["files"][name]
            except KeyError as exc:
                raise ValueError("requested company/view/dataset is not prepared") from exc
            self._cache[key] = _table(self.root, info)
        return self._cache[key]

    def _context(self, ticker: str, view: str, *, fiscal_start: int | None = None,
                 fiscal_end: int | None = None, as_of: str | None = None,
                 review_cutoff: str | None = None, recent_quarters: int = 8) -> dict:
        ticker = ticker.upper()
        info = self.manifest["companies"].get(ticker)
        if info is None or view not in info["views"]:
            raise ValueError("company/view not prepared")
        if as_of is not None and as_of != info["as_of"]:
            raise ValueError("as_of needs an exact prepared publication, not a query-time date filter")
        if review_cutoff is not None and review_cutoff != info["review_cutoff"]:
            raise ValueError("review_cutoff needs an exact prepared publication")
        if (fiscal_start is None) != (fiscal_end is None) or recent_quarters < 1:
            raise ValueError("supply both fiscal year bounds, or a positive recent quarter count")
        columns = self._records(ticker, view, "columns")
        periods = sorted({(c["fiscal_year"], c["fiscal_quarter"]) for c in columns})
        if fiscal_start is not None:
            if fiscal_start > fiscal_end or set(range(fiscal_start, fiscal_end+1)) - {y for y, q in periods}:
                raise ValueError("requested fiscal years not prepared")
            periods = [p for p in periods if fiscal_start <= p[0] <= fiscal_end]
        else:
            periods = periods[-recent_quarters:]
        context = {"ticker": ticker, "view": view, "as_of": info["as_of"], "review_cutoff": info["review_cutoff"],
                   "periods": [list(p) for p in periods], "publication_id": self.manifest["publication_id"],
                   "source_publication": info["source_publication"]}
        context["context_id"] = stable(context)
        return context

    def _validate_context(self, context: dict) -> tuple[str, str, set[tuple[int, int]]]:
        if context.get("publication_id") != self.manifest["publication_id"] or context.get("context_id") != stable({k: v for k, v in context.items() if k != "context_id"}):
            raise ValueError("stale or modified query context")
        ticker, view = context["ticker"], context["view"]
        info = self.manifest["companies"][ticker]
        if context["as_of"] != info["as_of"] or context["review_cutoff"] != info["review_cutoff"]:
            raise ValueError("query cutoff mismatch")
        return ticker, view, {tuple(p) for p in context["periods"]}

    def overview(self, ticker: str, *, fiscal_start: int | None = None, fiscal_end: int | None = None,
                 view: str = "LATEST_REPORTED", as_of: str | None = None, review_cutoff: str | None = None,
                 profile: str = "core", recent_quarters: int = 8) -> dict:
        if profile != "core":
            raise ValueError("profile not prepared")
        context = self._context(ticker, view, fiscal_start=fiscal_start, fiscal_end=fiscal_end, as_of=as_of,
                                review_cutoff=review_cutoff, recent_quarters=recent_quarters)
        ticker, view, periods = self._validate_context(context)
        selected = lambda rows: [r for r in rows if (r["fiscal_year"], r["fiscal_quarter"]) in periods]
        return copy.deepcopy({"context": context, "rows": self._records(ticker, view, "core_rows"),
                              "columns": selected(self._records(ticker, view, "columns")),
                              "cells": selected(self._records(ticker, view, "core_cells")),
                              "metrics": selected(self._records(ticker, view, "metrics")),
                              "warnings": ["LATEST_REPORTED는 재작성 비교가능 확정이 아닙니다.", "분기 금액과 기말 잔액은 별도 기간 종류입니다."]})

    def list_breakdowns(self, row_id: str, *, context: dict, include_hidden: bool = False) -> dict:
        ticker, view, periods = self._validate_context(context)
        groups = [n for n in self._records(ticker, view, "nodes") if n.get("anchor_row_id") == row_id and n["kind"] == "LENS" and (include_hidden or not n.get("hidden"))]
        edges = self._records(ticker, view, "edges")
        groups = [g for g in groups if any(e["parent_id"] == g["node_id"] and any(tuple(p) in periods for p in e["periods"]) for e in edges)]
        groups.sort(key=lambda g: (g.get("display_order") or 0, g.get("label") or "", g["node_id"]))
        return copy.deepcopy({"context": context, "groups": groups, "warning": "서로 다른 관점은 합산하지 않습니다."})

    def children(self, node_id: str, *, context: dict, cursor: str | None = None, limit: int = 5,
                 path: tuple[str, ...] = (), selection: str = "important",
                 reference_period: tuple[int, int] | None = None) -> dict:
        ticker, view, periods = self._validate_context(context)
        requested_periods = set(periods)
        if not 1 <= limit <= 1000 or node_id in path or selection not in {"important", "all"}:
            raise ValueError("invalid page size or cycle in exploration path")
        nodes = {n["node_id"]: n for n in self._records(ticker, view, "nodes")}
        if node_id not in nodes:
            raise ValueError("node not in requested company/view")
        edges = [e for e in self._records(ticker, view, "edges") if any(tuple(p) in periods for p in e["periods"])]
        # A deeper traversal cannot regain periods unsupported by its ancestor
        # path merely because a node is also used by another quarter's graph.
        chain = (*path, node_id)
        for parent, child in pairwise(chain):
            periods &= {tuple(p) for e in edges if e["parent_id"] == parent and e["child_id"] == child for p in e["periods"]}
        edges = [e for e in edges if any(tuple(p) in periods for p in e["periods"])]
        linked_all = sorted({e["child_id"] for e in edges if e["parent_id"] == node_id and e["child_id"] not in (*path, node_id)})
        if reference_period is None:
            reference_period = max(requested_periods)
        if not isinstance(reference_period, (tuple, list)) or len(reference_period) != 2 or any(not isinstance(value, int) or isinstance(value, bool) for value in reference_period):
            raise ValueError("malformed reference period")
        if tuple(reference_period) not in requested_periods:
            raise ValueError("reference period is outside the prepared query context")
        importance, legacy = self._importance(ticker, view, node_id, periods, tuple(reference_period), linked_all)
        critical = {"USER_PINNED", "SIGN_TRANSITION", "BASIS_WARNING", "CRITICAL_SOURCE_WARNING",
                    "ABRUPT_RATE_AND_MATERIAL_CHANGE", "REFERENCE_PERIOD_UNAVAILABLE_FORMER_TOP_AMOUNT"}
        selecting = {*critical, "TOP_AMOUNT", "STRUCTURAL_NAVIGATION"}
        selected_reasons: dict[str, list[str]] = {}
        display_importance: dict[str, dict | None] = {}
        fallback_keys: dict[str, tuple] = {}
        for child_id in linked_all:
            current = importance.get((child_id, tuple(reference_period)))
            reasons = list(current.get("reasons", [])) if current else []
            history = [importance.get((child_id, period)) or {} for period in periods]
            if any(row.get("pinned") for row in history):
                reasons.append("USER_PINNED")
            historical = [(period, importance.get((child_id, period))) for period in periods if period < tuple(reference_period)
                          and (importance.get((child_id, period)) or {}).get("present")]
            latest_historical = max(historical, default=(None, None), key=lambda row: row[0] or (-1, -1))
            historical_top = latest_historical[1] is not None and (latest_historical[1].get("amount_rank") or DEFAULT_TOP + 1) <= DEFAULT_TOP
            if (current is None or not current.get("present")) and historical_top:
                reasons.append("REFERENCE_PERIOD_UNAVAILABLE_FORMER_TOP_AMOUNT")
                display_importance[child_id] = {**latest_historical[1], "requested_reference_period": list(reference_period),
                                                "ordering_reference_period": list(latest_historical[0]),
                                                "reference_period_status": "UNAVAILABLE"}
                fallback_keys[child_id] = (-latest_historical[0][0], -latest_historical[0][1],
                                           latest_historical[1].get("amount_rank") or 10**9, child_id)
            else:
                display_importance[child_id] = current
            selected_reasons[child_id] = sorted(set(reasons))
        if selection == "all" or legacy:
            linked = linked_all
        else:
            linked = [child_id for child_id in linked_all if set(selected_reasons[child_id]) & selecting and (
                not (importance.get((child_id, tuple(reference_period))) or {}).get("presentation_excluded")
                or bool(set(selected_reasons[child_id]) & critical)
            )]
        linked.sort(key=lambda child_id: (
            child_id in fallback_keys,
            (importance.get((child_id, tuple(reference_period))) or {}).get("amount_rank") or 10**9,
            fallback_keys.get(child_id, (0, 0, 0, child_id)), child_id,
        ))
        offset = 0
        scope = stable(context, node_id, path, POLICY_VERSION if not legacy else "legacy-node-order", selection, reference_period)
        if cursor:
            try:
                payload = json.loads(cursor)
                offset = payload["offset"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError("malformed cursor") from exc
            if payload.get("scope") != scope:
                raise ValueError("cursor belongs to another query/path")
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise ValueError("invalid cursor")
        ids = linked[offset:offset+limit]
        allowed = {(e["child_id"], *p) for e in edges if e["parent_id"] == node_id and e["child_id"] in ids for p in e["periods"] if tuple(p) in periods}
        values = [dict(c, node_id=i) for i in ids for c in self._records(ticker, view, "cells")
                  if c["node_id"] == (nodes[i].get("value_node_id") or i) and (i, c["fiscal_year"], c["fiscal_quarter"]) in allowed]
        result = [{**nodes[i], "has_children": any(e["parent_id"] == i and e["child_id"] not in (*path, node_id) for e in edges),
                   "importance": copy.deepcopy(display_importance.get(i)),
                   "importance_history": copy.deepcopy(sorted(
                       [row for (child_id, _), row in importance.items() if child_id == i],
                       key=lambda row: (row["fiscal_year"], row["fiscal_quarter"]), reverse=True)),
                   "importance_reasons": selected_reasons[i]} for i in ids]
        active_years = {p[0] for e in edges if e["parent_id"] == node_id for p in e["periods"] if tuple(p) in periods}
        kinds = {nodes[i].get("period_class") for i in ids} - {None}
        columns = sorted([c for c in self._records(ticker, view, "columns") if (c["fiscal_year"], c["fiscal_quarter"]) in periods and c["fiscal_year"] in active_years and (not kinds or c["period_class"] in kinds)], key=lambda c: (c["period_class"], c["fiscal_year"], c["fiscal_quarter"]))
        parent = nodes[node_id]
        parent_cells = [c for c in self._records(ticker, view, "cells") if c["node_id"] == (parent.get("value_node_id") or node_id) and (c["fiscal_year"], c["fiscal_quarter"]) in periods]
        if parent["kind"] == "LENS" and not parent.get("source_parent_concept"):
            parent_cells = [c for c in self._records(ticker, view, "core_cells") if c["row_id"] == parent.get("anchor_row_id") and (c["fiscal_year"], c["fiscal_quarter"]) in periods]
        excluded = [child_id for child_id in linked_all if child_id not in linked]
        ordinary_warnings = [{"child_id": child_id, "warnings": (importance.get((child_id, tuple(reference_period))) or {}).get("warnings", [])}
                             for child_id in excluded if (importance.get((child_id, tuple(reference_period))) or {}).get("warnings")]
        return copy.deepcopy({"context": context, "parent": nodes[node_id], "children": result, "cells": values,
                              "columns": columns, "parent_cells": parent_cells,
                              "path": [*path, node_id], "hidden_count": max(0, len(linked)-offset-len(ids)),
                              "excluded_count": len(excluded), "excluded": [{"child_id": i, "reasons": ["PRESENTATION_EXCLUDED"] if (importance.get((i, tuple(reference_period))) or {}).get("presentation_excluded") else ["OUTSIDE_IMPORTANT_SELECTION"]} for i in excluded],
                              "excluded_warnings": ordinary_warnings,
                              "selection": selection, "reference_period": list(reference_period),
                              "importance_policy": {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION, "legacy_fallback": legacy},
                              "next_cursor": json.dumps({"scope": scope, "offset": offset+limit}) if offset+limit < len(linked) else None,
                              "evidence": [e for e in edges if e["parent_id"] == node_id and e["child_id"] in ids]})

    def _importance(self, ticker: str, view: str, parent_id: str, periods: set[tuple[int, int]],
                    reference_period: tuple[int, int], linked: list[str]) -> tuple[dict[tuple[str, tuple[int, int]], dict], bool]:
        files = self.manifest["companies"][ticker]["views"][view]["files"]
        if "importance" not in files:
            # Explicit compatibility path for immutable pre-U3 publications.
            return {}, True
        records = self._records(ticker, view, "importance")
        selected = {(row["child_id"], (row["fiscal_year"], row["fiscal_quarter"])): row for row in records
                    if row["parent_id"] == parent_id and (row["fiscal_year"], row["fiscal_quarter"]) in periods and row["child_id"] in linked}
        return selected, False

    def _hierarchy_records(self, ticker: str, name: str, filing_id: str | None = None) -> list[dict]:
        key = (ticker.upper(), "HIERARCHY", filing_id, name)
        if key not in self._cache:
            try:
                info = self.manifest["companies"][ticker.upper()]["hierarchy"]
                files = info["filings"][filing_id]["files"] if filing_id else info["files"]
                self._cache[key] = _table(self.root, files[name])
            except KeyError as exc:
                raise ValueError("hierarchy dataset not prepared in this publication") from exc
        return self._cache[key]

    def statement_catalog(self, ticker: str, *, section: str | None = None) -> dict:
        from sec_xbrl.analytics.hierarchy_queries import statement_catalog
        return statement_catalog(self, ticker, section=section)

    def statement(self, ticker: str, table_id: str) -> dict:
        from sec_xbrl.analytics.hierarchy_queries import statement
        return statement(self, ticker, table_id)

    def pre_table(self, ticker: str, table_id: str) -> dict:
        from sec_xbrl.analytics.hierarchy_queries import pre_table
        return pre_table(self, ticker, table_id)

    def axes(self, ticker: str, filing_id: str, *, raw_concept_id: str | None = None) -> dict:
        from sec_xbrl.analytics.hierarchy_queries import axes
        return axes(self, ticker, filing_id, raw_concept_id=raw_concept_id)

    def member_metrics(self, ticker: str, filing_id: str, *, axis_id: str, member_id: str | None,
                       typed_value: str | None = None, raw_concept_id: str | None = None) -> dict:
        from sec_xbrl.analytics.hierarchy_queries import member_metrics
        return member_metrics(self, ticker, filing_id, axis_id=axis_id, member_id=member_id,
                              typed_value=typed_value, raw_concept_id=raw_concept_id)

    def importance_v2(self, ticker: str, *, view: str = "LATEST_REPORTED") -> dict:
        return copy.deepcopy({"policy": self.manifest["importance_v2_policy"],
                              "records": self._records(ticker, view, "importance_v2")})

    def axis_timeseries(self, ticker: str, lens_id: str, *, context: dict[str, Any]) -> dict[str, Any]:
        from sec_xbrl.analytics.axis_timeseries_queries import axis_timeseries
        return axis_timeseries(self, ticker, lens_id, context=context)

    def overview_snapshot(self, ticker: str, **selection: Any) -> dict[str, Any]:
        """Create a canonical U5 snapshot from one prepared overview response."""
        from sec_xbrl.consumer.export import prepare_overview_snapshot

        return prepare_overview_snapshot(self, ticker, **selection)

    def axis_snapshot(self, ticker: str, lens_id: str, *, context: dict[str, Any],
                      **selection: Any) -> dict[str, Any]:
        """Create a canonical U5 snapshot from one prepared Axis response."""
        from sec_xbrl.consumer.export import prepare_axis_snapshot

        return prepare_axis_snapshot(self, ticker, lens_id, context=context, **selection)

    def _axis_json(self, relative: str, expected_sha256: str) -> dict[str, Any]:
        identity = self.axis_manifest or {}
        key = (identity.get("publication_id"), identity.get("decision_cutoff"), relative, expected_sha256)
        if key not in self._axis_cache:
            path = self.root / relative
            if not path.is_file() or path.is_symlink() or self.root.resolve() not in path.resolve().parents:
                raise ValueError("axis review path is outside the publication")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != expected_sha256:
                raise ValueError("axis review checksum mismatch")
            self._axis_cache[key] = json.loads(payload)
        return copy.deepcopy(self._axis_cache[key])

    def target_status(self, ticker: str) -> dict:
        """Return the persisted preparation outcome without interpreting absence."""
        ticker = ticker.upper()
        outcome = self.manifest.get("targets", {}).get(ticker)
        if outcome is None and ticker in self.manifest.get("companies", {}):
            outcome = {"status": "READY", "reason": None}
        if outcome is None:
            raise ValueError("target is not registered in this catalogue publication")
        return copy.deepcopy({"ticker": ticker, **outcome})

    def trace(self, cell_id: str, *, context: dict) -> dict:
        ticker, view, periods = self._validate_context(context)
        rows = self._records(ticker, view, "trace_" + stable(cell_id)[0])
        found = [r for r in rows if r["cell_id"] == cell_id and (r["fiscal_year"], r["fiscal_quarter"]) in periods]
        if len(found) != 1:
            raise ValueError("cell not uniquely present in query context")
        return copy.deepcopy({"context": context, "trace": found[0]})

    def compare_views(self, ticker: str, *, fiscal_start: int, fiscal_end: int) -> dict:
        before = self.overview(ticker, fiscal_start=fiscal_start, fiscal_end=fiscal_end, view="AS_FILED")
        after = self.overview(ticker, fiscal_start=fiscal_start, fiscal_end=fiscal_end, view="LATEST_REPORTED")
        return {"as_filed": before, "latest_reported": after,
                "warning": "원공시와 현재 선택값을 병렬 조회합니다. 차이가 곧 오류·재작성 또는 비교가능성을 뜻하지 않습니다."}


def open_analysis(root: Path | str) -> AnalysisClient:
    root = Path(root)
    if (root / "analysis_current.json").is_file():
        root = Path(json.loads((root / "analysis_current.json").read_text())["bundle_path"])
    return AnalysisClient(root)


def _raw_material(reader, ticker: str) -> tuple[dict, list[dict]]:
    from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
    intake = json.loads(Path(reader.manifest["source_intake"]).read_text())
    concepts, relationships = {}, []
    for entry in intake["filings"]:
        if entry["ticker"] != ticker:
            continue
        ref = entry["filing"]
        snapshot = _load_declared_cohort_snapshot(Path(entry["source_run"]) / "snapshots" / ref["cik"] / ref["accession"].replace("-", ""), ref["cik"], ref["accession"])
        concepts.update({r["raw_concept_id"]: r for r in snapshot.records("concept")})
        roles = {r["role_id"]: r for r in snapshot.records("role")}
        relationships.extend({**r, "role_uri": roles[r["role_id"]]["role_uri"], "role_definition": roles[r["role_id"]]["role_definition"]} for r in snapshot.records("relationship"))
    return concepts, relationships


def _compact(cell: dict, row: dict, column: dict, *, ticker: str, view: str, node_id: str) -> dict:
    lineage = cell["value_lineage"]
    basis = lineage.get("basis_version")
    unit = [lineage.get("unit_numerator_measures"), lineage.get("unit_denominator_measures")]
    dimensions = lineage.get("analytical_dimensions") or lineage.get("canonical_dimension_signature") or []
    definition_scope = None
    if basis:
        definition_scope = basis
    elif (not dimensions and lineage.get("mapping_review_required") is False
          and lineage.get("raw_concept_is_standard") is True and lineage.get("raw_concept_taxonomy_family") == "us-gaap"
          and lineage.get("raw_concept_data_type") == "xbrli:monetaryItemType"
          and row.get("row_identity", [None])[0] == "JOIN" and cell.get("comparability_status") in {"BASELINE", "COMPARABLE", "COMPATIBLE_INPUTS"}):
        definition_scope = "REPORTED_ARITHMETIC_ONLY_V1:" + str(lineage.get("company_canonical_concept_id"))
    source_filings = sorted({str(l.get("source_filing_id")) for l in lineage.get("source_inputs", []) or [lineage]})
    return {"cell_id": cell["fiscal_time_series_cell_id"], "row_id": row["fiscal_time_series_row_id"], "node_id": node_id,
            "column_id": column["fiscal_time_series_column_id"], "fiscal_year": column["fiscal_year"], "fiscal_quarter": column["fiscal_quarter"],
            "period_class": column["period_class"], "start": lineage.get("context_start_date"), "end": lineage.get("context_end_date") or lineage.get("context_instant_date"),
            "value": cell.get("value_numeric"), "unit": unit, "dimensions": dimensions, "basis_version": basis,
            "comparison_scope": definition_scope, "margin_scope": None,
            "source_filing_ids": source_filings, "monetary": lineage.get("raw_concept_data_type") == "xbrli:monetaryItemType",
            "status": cell["value_status"], "reason": cell.get("resolution_reason") or cell.get("comparability_reason"),
            "reviewed": bool(lineage.get("interpretation_decision_id")),
            "selection_view": view, "as_of": lineage.get("selection_as_of_date"), "ticker": ticker,
            "semantic_id": lineage.get("company_canonical_concept_id"), "source_fact_id": lineage.get("selected_source_fact_id")}


def _materialize_prepared_quality(
    *,
    ticker: str,
    compact: dict,
    source_cell: dict,
    concepts: dict,
    decisions: list[dict[str, str]],
    matched: set[str],
) -> None:
    """Apply the existing administrative overlay to one analytical cell."""
    from sec_xbrl.company_reports import materialize_quality

    lineage = source_cell.get("value_lineage", {})
    dimensions = [
        {
            "axis": concepts.get(dim[0], {}).get("qname", dim[0]),
            "member": concepts.get(dim[1], {}).get("qname", dim[1]),
            "typed_member": dim[2],
            "dimension_type": dim[3],
            "is_default": dim[4],
        }
        for dim in lineage.get("raw_dimension_signature", [])
    ]
    inputs = lineage.get("source_inputs", []) or [lineage]
    source_scopes = [
        {
            "accession": source.get("accession"),
            "concept": source.get("raw_concept_qname"),
            "resolved_issue_ids": source.get("resolved_issue_ids", []),
            "dimensions": [
                {
                    "axis": concepts.get(dim[0], {}).get("qname", dim[0]),
                    "member": concepts.get(dim[1], {}).get("qname", dim[1]),
                }
                for dim in source.get("raw_dimension_signature", [])
            ],
        }
        for source in inputs
    ]
    # Match only the explicit source scopes below. They carry resolved issue
    # identities for direct, interpreted, and derived observations.
    quality_lineage = {**lineage, "accession": None}
    overlay = materialize_quality(
        ticker=ticker,
        cell={**source_cell, "value_lineage": quality_lineage},
        dimensions=dimensions,
        decisions=decisions,
        source_scopes=source_scopes,
    )
    matched.update(row["decision_id"] for row in overlay["decisions"])
    compact.update(
        raw_value=compact.get("value"),
        raw_text=source_cell.get("value_text"),
        analytical_value=overlay["analytical_value"],
        analytical_text=overlay["analytical_text"],
        quality_status=overlay["quality_status"],
        quality_reasons=overlay["quality_reasons"],
        quality_decisions=overlay["decisions"],
        value=overlay["analytical_value"],
    )




def prepare_analysis(*, publication: Path, destination: Path, tickers: tuple[str, ...],
                     configuration: dict | None = None, fiscal_years: int = 3,
                     fiscal_start: int | None = None, fiscal_end: int | None = None,
                     quality_decisions: list[dict[str, str]] | None = None) -> Path:
    """Materialize a consumer bundle. This is the only raw-reading/build boundary."""
    if destination.exists() or fiscal_years < 1:
        raise ValueError("new destination and positive fiscal scope required")
    configuration = copy.deepcopy(configuration or {})
    reader = open_history_publication(publication)
    staging = destination.parent / (".partial-" + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    source_hashes = {"history_manifest_sha256": hashlib.sha256((reader.root / "history_manifest.json").read_bytes()).hexdigest()}
    if (publication / "review_manifest.json").exists():
        source_hashes["review_manifest_sha256"] = hashlib.sha256((publication / "review_manifest.json").read_bytes()).hexdigest()
    quality_decisions = copy.deepcopy(quality_decisions or [])
    manifest = {"version": VERSION, "publication_id": uuid.uuid4().hex, "companies": {}, "targets": {},
                "configuration": configuration, "source_manifest_hashes": source_hashes}
    if quality_decisions:
        manifest["quality_overlay"] = {"version": "admin-quality-v1", "matched_decision_ids": []}
    matched_quality: set[str] = set()
    for ticker in tickers:
        ticker = ticker.upper()
        settings = configuration.get(ticker, {})
        profile = settings.get("core_rows", default_profile())
        if len(profile) > 25 or len({r["row_id"] for r in profile}) != len(profile):
            raise ValueError("core profile must have at most 25 unique rows")
        concepts, relationships = _raw_material(reader, ticker)
        if (fiscal_start is None) != (fiscal_end is None):
            raise ValueError("both explicit fiscal year bounds required")
        if fiscal_start is not None:
            years = list(range(fiscal_start, fiscal_end+1))
        else:
            annual_tables = [t for t in reader.manifest["tables"] if t["ticker"] == ticker and t["period_class"] == "FY"]
            source_columns = reader.load(ticker=ticker, period_class="FY").columns if annual_tables else reader.load(ticker=ticker).columns
            years = sorted({c["fiscal_year"] for c in source_columns if c.get("column_status") == "AVAILABLE"})[-fiscal_years:]
        if not years:
            raise ValueError("no prepared fiscal periods")
        info = {"views": {}, "source_publication": str(publication.absolute()), "as_of": None,
                "review_cutoff": getattr(reader, "review_manifest", {}).get("review_as_of"), "years": years}
        manifest["companies"][ticker] = info
        manifest["targets"][ticker] = {"status": "READY", "reason": None,
                                       "evidence": {"source_publication": str(publication.absolute())}}
        for view in ("AS_FILED", "LATEST_REPORTED"):
            columns, cells, traces, nodes, edges, core_cells = [], [], [], {}, {}, []
            source_index: dict[tuple, list[tuple]] = defaultdict(list)
            panels = {}
            for period in ("QTD_3M", "INSTANT"):
                panel = reader.load(ticker=ticker, period_class=period, view=view)
                panels[period] = panel
                info["as_of"] = panel.scope["selection_as_of_date"]
                selected_columns = {c["fiscal_time_series_column_id"]: c for c in panel.columns if c["fiscal_year"] in years}
                columns.extend(selected_columns.values())
                rows = {r["fiscal_time_series_row_id"]: r for r in panel.rows}
                for cell in panel.cells:
                    if cell["fiscal_time_series_column_id"] not in selected_columns:
                        continue
                    row = rows[cell["fiscal_time_series_row_id"]]
                    lineage = cell["value_lineage"]
                    column = selected_columns[cell["fiscal_time_series_column_id"]]
                    nid = stable(ticker, view, period, row["fiscal_time_series_row_id"])
                    compact = _compact(cell, row, column, ticker=ticker, view=view, node_id=nid)
                    if quality_decisions:
                        _materialize_prepared_quality(ticker=ticker, compact=compact, source_cell=cell, concepts=concepts,
                                                      decisions=quality_decisions, matched=matched_quality)
                    cells.append(compact)
                    trace = {"cell_id": compact["cell_id"], "fiscal_year": column["fiscal_year"], "fiscal_quarter": column["fiscal_quarter"],
                             "value_lineage": lineage, "source_publication": str(publication.absolute()),
                             "definition": {k: row.get(k) for k in ("raw_concept_qname", "canonical_dimension_signature", "basis_version")}}
                    if quality_decisions:
                        trace["quality_overlay"] = {key: copy.deepcopy(compact[key]) for key in
                                                    ("quality_status", "quality_reasons", "quality_decisions",
                                                     "raw_value", "raw_text", "analytical_value", "analytical_text")}
                    traces.append(trace)
                    raw_dimensions = [[concepts.get(d[0], {}).get("qname", d[0]), concepts.get(d[1], {}).get("qname", d[1]), *d[2:]] for d in lineage.get("raw_dimension_signature", [])]
                    displayed = lineage.get("analytical_dimensions") or raw_dimensions
                    meaningful_members = [d[1] for d in displayed if d[1] and str(d[1]).split(":")[-1] != "OperatingSegmentsMember"]
                    nodes[nid] = {"node_id": nid, "kind": "VALUE", "label": " / ".join(display_name(m) for m in meaningful_members) or display_name(row["raw_concept_qname"]),
                                  "row_id": row["fiscal_time_series_row_id"], "concept": row["raw_concept_qname"],
                                  "canonical_concept_id": lineage.get("company_canonical_concept_id"),
                                  "dimensions": displayed, "basis_version": lineage.get("basis_version"),
                                  "period_class": period, "mapping_review_required": row.get("mapping_review_required")}
                    nodes[nid]["origin_kind"] = "STANDARD" if lineage.get("raw_concept_is_standard") else "CUSTOM"
                    raw_key = (lineage.get("source_filing_id"), lineage.get("raw_concept_id"))
                    source_index[raw_key].append((nid, compact, lineage.get("raw_dimension_signature", [])))
            # Core row selection uses declared exact concept identities, never a
            # dimensioned note or a guessed subtotal. Competing observations fail.
            for spec in profile:
                for column in [c for c in columns if c["period_class"] == spec["period_class"]]:
                    matches = [c for c in cells if c["column_id"] == column["fiscal_time_series_column_id"] and not nodes[c["node_id"]]["dimensions"] and nodes[c["node_id"]]["concept"] in spec["concepts"]]
                    unique = {(c["source_fact_id"] or c["cell_id"], c["value"], str(c["unit"])): c for c in matches}
                    chosen = next(iter(unique.values())) if len(unique) == 1 else None
                    if chosen:
                        core_cells.append({**chosen, "row_id": spec["row_id"]})
                    else:
                        core_cells.append({"row_id": spec["row_id"], "cell_id": "missing:" + stable(ticker, view, spec["row_id"], column), "node_id": None,
                                           "column_id": column["fiscal_time_series_column_id"], "fiscal_year": column["fiscal_year"], "fiscal_quarter": column["fiscal_quarter"],
                                           "period_class": spec["period_class"], "value": None, "status": "UNAVAILABLE", "reason": "MULTIPLE_CANDIDATES" if matches else "REQUIRED_ITEM_NOT_IN_PREPARED_DATA",
                                           "unit": [], "comparison_scope": None, "margin_scope": None, "basis_version": None, "dimensions": [], "as_of": info["as_of"], "selection_view": view, "ticker": ticker})
            def add_edge(parent_id, child_id, kind, period, evidence, edges=edges):
                eid = stable(parent_id, child_id, kind, evidence)
                edges.setdefault(eid, {"edge_id": eid, "parent_id": parent_id, "child_id": child_id, "kind": kind, "periods": [], "evidence": evidence})
                if period not in edges[eid]["periods"]:
                    edges[eid]["periods"].append(period)
            graph_anchors = list(core_cells)
            for link in settings.get("breakdown_sources", []):
                if link["row_id"] not in {r["row_id"] for r in profile}:
                    raise ValueError("related statement link needs an existing core row")
                graph_anchors.extend({**c, "row_id": link["row_id"], "related_source_label": link["label"]}
                                     for c in cells if nodes[c["node_id"]]["concept"] == link["concept"] and not nodes[c["node_id"]]["dimensions"])
            for spec in profile:
                anchors = [c for c in core_cells if c["row_id"] == spec["row_id"] and c.get("node_id")]
                for anchor in anchors:
                    for child in cells:
                        node = nodes[child["node_id"]]
                        if child["column_id"] != anchor["column_id"] or not node["dimensions"] or child["semantic_id"] != anchor["semantic_id"]:
                            continue
                        axes = sorted(d[0] for d in node["dimensions"])
                        lens_id = stable(ticker, view, spec["row_id"], axes, node["basis_version"])
                        nodes[lens_id] = {"node_id": lens_id, "kind": "LENS", "anchor_row_id": spec["row_id"],
                                          "label": " / ".join(display_name(a) for a in axes), "lens_type": "DIMENSIONAL_VIEW", "basis_version": node["basis_version"], "dimensions": axes}
                        add_edge(lens_id, child["node_id"], "OBSERVED_DIMENSION", [child["fiscal_year"], child["fiscal_quarter"]], {"source_fact_id": child["source_fact_id"], "source_cell_id": child["cell_id"]})
            # CAL only: direction, role and full same-context dimension signature
            # are preserved; PRE adjacency never becomes numerical decomposition.
            for rel in relationships:
                if rel["network_type"] != "CAL":
                    continue
                parents = source_index.get((rel["filing_id"], rel["from_raw_concept_id"]), [])
                children = source_index.get((rel["filing_id"], rel["to_raw_concept_id"]), [])
                for pn, pc, pd in parents:
                    for cn, cc, cd in children:
                        if pc["column_id"] != cc["column_id"] or pd != cd or pn == cn:
                            continue
                        evidence = {k: rel.get(k) for k in ("relationship_id", "role_id", "filing_id", "weight", "arcrole", "target_role_uri")}
                        role = rel["role_uri"]
                        scoped_parent, scoped_child = stable("CAL", rel["filing_id"], role, pn), stable("CAL", rel["filing_id"], role, cn)
                        nodes[scoped_parent] = {**nodes[pn], "node_id": scoped_parent, "value_node_id": pn, "network_scope": ["CAL", role]}
                        nodes[scoped_child] = {**nodes[cn], "node_id": scoped_child, "value_node_id": cn, "network_scope": ["CAL", role]}
                        add_edge(scoped_parent, scoped_child, "CAL_CHILD", [pc["fiscal_year"], pc["fiscal_quarter"]], evidence)
                        for core in graph_anchors:
                            if core.get("node_id") == pn:
                                lens_id = stable(ticker, view, core["row_id"], role)
                                nodes[lens_id] = {"node_id": lens_id, "kind": "LENS", "anchor_row_id": core["row_id"], "label": core.get("related_source_label") or rel["role_definition"], "lens_type": "RELATED_STATEMENT_COMPOSITION" if core.get("related_source_label") else "CAL_DECOMPOSITION", "role_uri": role, "dimensions": [], "source_parent_concept": nodes[pn]["concept"]}
                                add_edge(lens_id, scoped_child, "CAL_CHILD", [pc["fiscal_year"], pc["fiscal_quarter"]], evidence)
            _definition_graph(graph_anchors, cells, traces, nodes, relationships, concepts, add_edge, ticker=ticker, view=view)
            _reviewed_hierarchies(settings.get("hierarchies", []), nodes, cells, traces, add_edge, view=view, review_cutoff=info["review_cutoff"])
            # A primary statement presentation network supplies context only;
            # it never creates decomposition edges. Margin role pairs remain
            # explicitly allowlisted in the metric producer.
            statement_roles = defaultdict(set)
            for rel in relationships:
                definition = (rel.get("role_definition") or "").lower()
                if rel["network_type"] == "PRE" and "statement" in definition and any(word in definition for word in ("income", "operation", "earning")) and "detail" not in definition:
                    for raw_id in (rel["from_raw_concept_id"], rel["to_raw_concept_id"]):
                        statement_roles[(rel["filing_id"], raw_id)].add(rel["role_uri"])
            trace_index = {t["cell_id"]: t["value_lineage"] for t in traces}
            for cell in core_cells:
                raw = trace_index.get(cell["cell_id"], {})
                inputs = raw.get("source_inputs") or [raw]
                role_sets = [statement_roles.get((i.get("source_filing_id"), i.get("raw_concept_id")), set()) for i in inputs]
                roles = set.union(*role_sets) if role_sets and all(role_sets) else set()
                cell["statement_roles"] = sorted(roles)
                cell["statement_evidence"] = {i.get("source_filing_id"): sorted(rs) for i, rs in zip(inputs, role_sets)}
                eligible = cell.get("status") == "REPORTED" or (cell.get("status") == "DERIVED" and raw.get("source_type") == "DERIVED_QUARTER" and raw.get("policy_registry") == "CONTROLLED_STANDARD_STATEMENT_ALLOWLIST")
                if roles and eligible and not cell.get("dimensions"):
                    cell["margin_scope"] = "SAME_STATEMENT_INPUT_PERIODS:" + stable(sorted((i.get("source_filing_id"), i.get("context_start_date"), i.get("context_end_date")) for i in inputs))
                if cell["cell_id"].startswith("missing:"):
                    spec = next(r for r in profile if r["row_id"] == cell["row_id"])
                    cell["availability_note"] = spec.get("availability_note") or ("주당이익은 연간에서 누적 값을 빼서 Q4를 만들 수 없습니다." if cell["row_id"] == "eps" and cell["fiscal_quarter"] == 4 else "동일 범위의 직접 보고 값 또는 승인된 분기 계산 값이 없습니다. 원문 관련 구성을 확인하세요.")
                    traces.append({"cell_id": cell["cell_id"], "fiscal_year": cell["fiscal_year"], "fiscal_quarter": cell["fiscal_quarter"], "value_lineage": {"status": cell["status"], "reason": cell["reason"]}, "source_publication": str(publication.absolute())})
                    traces[-1]["availability_note"] = cell["availability_note"]
                    if spec.get("availability_evidence"):
                        evidence_path = Path(spec["availability_evidence"])
                        traces[-1]["availability_evidence"] = {"path": str(evidence_path.absolute()), "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()}
            metrics = materialize_metrics(core_cells)
            _apply_lens_preferences(nodes, settings.get("lens_preferences", []))
            importance = materialize_importance(nodes=list(nodes.values()), edges=list(edges.values()), cells=cells,
                                                core_cells=core_cells, configuration=settings.get("importance", {}),
                                                review_cutoff=info["review_cutoff"], traces=traces)
            files = {}
            datasets = {"columns": columns, "core_rows": profile, "core_cells": core_cells, "cells": cells,
                        "nodes": list(nodes.values()), "edges": list(edges.values()), "metrics": metrics,
                        "importance": importance}
            for digit in "0123456789abcdef":
                datasets["trace_" + digit] = [t for t in traces if stable(t["cell_id"])[0] == digit]
            for name, records in datasets.items():
                relative = f"{ticker}/{view}/{name}.parquet"
                files[name] = {"path": relative, **_write_records(staging / relative, tuple(records))}
            info["views"][view] = {"files": files}
    if quality_decisions:
        manifest["quality_overlay"]["matched_decision_ids"] = sorted(matched_quality)
    (staging / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    staging.rename(destination)
    return destination


def _definition_graph(core_cells, cells, traces, nodes, relationships, concepts, add_edge, *, ticker, view):
    """Persist positive DEF paths, retaining structural nodes and targetRole.

    These are disclosure navigation paths, not additive business hierarchies.
    Values attach only to a fact's exact full context in the same filing.
    """
    positive = {"all", "hypercube-dimension", "dimension-domain", "domain-member"}
    outgoing = defaultdict(list)
    for rel in relationships:
        if rel["network_type"] == "DEF" and rel["arcrole"].rsplit("/", 1)[-1] in positive:
            outgoing[(rel["filing_id"], rel["role_uri"], rel["from_raw_concept_id"])].append(rel)
    lineage = {t["cell_id"]: t["value_lineage"] for t in traces}
    by_period = defaultdict(list)
    for cell in cells:
        by_period[cell["column_id"]].append(cell)
    for anchor in core_cells:
        if not anchor.get("node_id"):
            continue
        source = lineage[anchor["cell_id"]]
        filing, primary = source.get("source_filing_id"), source.get("raw_concept_id")
        roles = {role for f, role, concept in outgoing if f == filing and concept == primary}
        for child in by_period[anchor["column_id"]]:
            target = lineage[child["cell_id"]]
            dims = target.get("raw_dimension_signature", [])
            if not dims or target.get("source_filing_id") != filing or target.get("raw_concept_id") != primary:
                continue
            axes, members = {d[0] for d in dims}, {d[1] for d in dims if d[1]}
            for role in roles:
                scope = stable(filing, role, dims, anchor["period_class"])
                lens = stable(ticker, view, anchor["row_id"], "DEF", role, dims)
                period = [child["fiscal_year"], child["fiscal_quarter"]]
                pending, seen, staged, reachable = [(role, primary, lens)], set(), [], False
                while pending:
                    current_role, concept, parent = pending.pop()
                    if (current_role, concept) in seen:
                        continue
                    seen.add((current_role, concept))
                    for rel in outgoing.get((filing, current_role, concept), []):
                        arc = rel["arcrole"].rsplit("/", 1)[-1]
                        to = rel["to_raw_concept_id"]
                        if arc == "hypercube-dimension" and to not in axes:
                            continue
                        next_role = rel.get("target_role_uri") or current_role
                        nid = stable("DEF", scope, next_role, to)
                        evidence = {k: rel.get(k) for k in ("relationship_id", "filing_id", "role_uri", "arcrole", "target_role_uri", "usable", "closed", "context_element")}
                        staged.append((parent, nid, evidence))
                        nodes[nid] = {"node_id": nid, "kind": "STRUCTURAL", "label": display_name(concepts.get(to, {}).get("qname", to)), "lens_type": "DEF_DISCLOSURE", "dimensions": dims, "role_uri": next_role, "source_filing_id": filing, "period_class": anchor["period_class"]}
                        if to in members and rel.get("usable") not in (False, "false"):
                            staged.append((nid, child["node_id"], {"source_cell_id": child["cell_id"], "full_dimensions": dims, "filing_id": filing}))
                            reachable = True
                        pending.append((next_role, to, nid))
                if reachable:
                    nodes[lens] = {"node_id": lens, "kind": "LENS", "anchor_row_id": anchor["row_id"], "label": "주석 차원 구조 · " + role.rsplit("/", 1)[-1], "lens_type": "DEF_DISCLOSURE", "role_uri": role, "dimensions": dims}
                    # Keep only paths leading to observed values, including
                    # alternate role paths; visited states control cycles.
                    useful = {child["node_id"]}
                    while True:
                        expanded = useful | {p for p, c, e in staged if c in useful}
                        if expanded == useful:
                            break
                        useful = expanded
                    for parent, child_id, evidence in staged:
                        if parent in useful and child_id in useful:
                            add_edge(parent, child_id, "DEF_DISCLOSURE", period, evidence)


def _reviewed_hierarchies(rules, nodes, cells, traces, add_edge, *, view, review_cutoff):
    if view == "AS_FILED":
        return
    trace_index = {t["cell_id"]: t["value_lineage"] for t in traces}
    for rule in rules:
        if not all(rule.get(k) for k in ("basis_version", "parent_dimensions", "child_dimensions", "reviewer", "known_at", "evidence", "source_tables")):
            raise ValueError("hierarchy needs a separate explicit source review")
        from datetime import datetime
        if not review_cutoff or datetime.fromisoformat(rule["known_at"]) > datetime.fromisoformat(review_cutoff):
            raise ValueError("hierarchy review is later than prepared review cutoff")
        evidence = Path(rule["evidence"])
        if not evidence.is_file() or hashlib.sha256(evidence.read_bytes()).hexdigest() != rule.get("evidence_sha256"):
            raise ValueError("hierarchy review evidence changed")
        parents = [c for c in cells if nodes[c["node_id"]]["basis_version"] == rule["basis_version"] and nodes[c["node_id"]]["dimensions"] == rule["parent_dimensions"]]
        children = [c for c in cells if nodes[c["node_id"]]["basis_version"] == rule["basis_version"] and nodes[c["node_id"]]["dimensions"] == rule["child_dimensions"]]
        for parent in parents:
            for child in children:
                if parent["column_id"] != child["column_id"] or parent["semantic_id"] != child["semantic_id"]:
                    continue
                lp, lc = trace_index[parent["cell_id"]], trace_index[child["cell_id"]]
                ep, ec = lp.get("reviewed_source_evidence", {}), lc.get("reviewed_source_evidence", {})
                if [ep.get("source_file_sha256"), ep.get("table_locator")] not in rule["source_tables"]:
                    continue
                if not lp.get("interpretation_decision_id") or not lc.get("interpretation_decision_id") or ep.get("source_file_sha256") != ec.get("source_file_sha256") or ep.get("table_locator") != ec.get("table_locator"):
                    raise ValueError("hierarchy is not bound to the same reviewed source table")
                add_edge(parent["node_id"], child["node_id"], "REVIEWED_DISPLAY_HIERARCHY", [parent["fiscal_year"], parent["fiscal_quarter"]], rule)


def prepare_catalog(*, catalog: Path, destination: Path, tickers: tuple[str, ...] | None = None,
                    fiscal_start: int | None = None, fiscal_end: int | None = None,
                    quality_decisions: list[dict[str, str]] | None = None) -> Path:
    """Prepare registered company sources; callers need not know source paths."""
    import csv
    if destination.exists():
        raise ValueError("choose a new immutable bundle destination")
    with (catalog / "companies.csv").open(encoding="utf-8-sig", newline="") as stream:
        companies = list(csv.DictReader(stream))
    selected = [c for c in companies if c["active"] == "true" and (tickers is None or c["ticker"] in {t.upper() for t in tickers})]
    if not selected or (tickers and {t.upper() for t in tickers} - {c["ticker"] for c in selected}):
        raise ValueError("requested companies not registered/active")
    config_path = catalog / "analysis_profiles.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    staging = destination.parent / (".partial-" + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    status_path = catalog / "target_status.json"
    statuses = json.loads(status_path.read_text()) if status_path.exists() else {}
    targets = {company["ticker"]: (copy.deepcopy(statuses[company["ticker"]])
               if statuses.get(company["ticker"], {}).get("status") in {"UNSUPPORTED", "PREPARATION_FAILED", "REVIEW_REQUIRED", "DISCLOSURE_MISSING"}
               else {"status": "NOT_PREPARED", "reason": "NOT_INCLUDED_IN_PREPARED_BUNDLE",
                     "evidence": {"registered_source_publication": company.get("publication") or None}})
               for company in companies}
    manifest = {"version": VERSION, "publication_id": uuid.uuid4().hex, "companies": {}, "targets": targets,
                "configuration": config}
    for company in selected:
        ticker = company["ticker"]
        sub = staging / ticker
        if not company.get("publication"):
            from sec_xbrl.company_reports import set_target_status
            set_target_status(catalog, ticker=ticker, status="NOT_PREPARED", reason="REGISTERED_COLLECTION_TARGET")
            raise ValueError(f"{ticker}: registered target has no prepared publication")
        try:
            prepare_analysis(publication=Path(company["publication"]), destination=sub, tickers=(ticker,), configuration=config,
                             fiscal_years=int(company["recent_fiscal_years"]),
                             fiscal_start=fiscal_start if fiscal_start is not None else int(company["fiscal_start"]) if company.get("fiscal_start") else None,
                             fiscal_end=fiscal_end if fiscal_end is not None else int(company["fiscal_end"]) if company.get("fiscal_end") else None,
                             quality_decisions=quality_decisions)
        except Exception as exc:
            from sec_xbrl.company_reports import set_target_status
            prior = statuses.get(ticker, {})
            if prior.get("status") != "REVIEW_REQUIRED":
                set_target_status(catalog, ticker=ticker, status="PREPARATION_FAILED", reason=str(exc),
                                  evidence={"source_publication": company["publication"]})
            raise
        child = json.loads((sub / "analysis_manifest.json").read_text())
        info = child["companies"][ticker]
        info["source_manifest_hashes"] = child["source_manifest_hashes"]
        for view in info["views"].values():
            for file in view["files"].values():
                file["path"] = ticker + "/" + file["path"]
        manifest["companies"][ticker] = info
        if child.get("quality_overlay"):
            overlay = manifest.setdefault("quality_overlay", {"version": "admin-quality-v1", "matched_decision_ids": []})
            overlay["matched_decision_ids"].extend(child["quality_overlay"]["matched_decision_ids"])
        if manifest["targets"].get(ticker, {}).get("status") != "REVIEW_REQUIRED":
            manifest["targets"][ticker] = {"status": "READY", "reason": None,
                                           "evidence": {"source_publication": info["source_publication"]}}
    if manifest.get("quality_overlay"):
        manifest["quality_overlay"]["matched_decision_ids"] = sorted(set(manifest["quality_overlay"]["matched_decision_ids"]))
    (staging / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    staging.rename(destination)
    # Publish the lightweight catalogue pointer only after the entire bundle
    # exists. Existing immutable bundles remain selectable by their own path.
    pointer = catalog / (".analysis-current-" + uuid.uuid4().hex)
    pointer.write_text(json.dumps({"bundle_path": str(destination.absolute()), "publication_id": manifest["publication_id"]}))
    pointer.replace(catalog / "analysis_current.json")
    from sec_xbrl.company_reports import set_target_status
    for company in selected:
        ticker = company["ticker"]
        if manifest["targets"][ticker]["status"] != "REVIEW_REQUIRED":
            set_target_status(catalog, ticker=ticker, status="READY", reason=None,
                              evidence={"consumer_bundle": str(destination.absolute()),
                                        "publication_id": manifest["publication_id"]})
    return destination


def refresh_analysis(*, admin: Path, workspace: Path, as_of: date, review_as_of: date,
                     tickers: tuple[str, ...] | None = None, fiscal_start: int | None = None,
                     fiscal_end: int | None = None, **kwargs) -> Path:
    """Explicit collection/build operation, separate from all query methods."""
    from sec_xbrl.company_reports import refresh
    refresh(admin, workspace=workspace, as_of=as_of, review_as_of=review_as_of, tickers=tickers, **kwargs)
    return prepare_catalog(catalog=admin, destination=workspace / ("consumer-" + uuid.uuid4().hex), tickers=tickers,
                           fiscal_start=fiscal_start, fiscal_end=fiscal_end)


def render_analysis(client: AnalysisClient, *, ticker: str, destination: Path, fiscal_start: int, fiscal_end: int) -> None:
    from sec_xbrl.company_reports import _end
    data = client.overview(ticker, fiscal_start=fiscal_start, fiscal_end=fiscal_end)
    esc = lambda v: html.escape(str(v))
    traces, branches = {}, {}
    def number(cell):
        cell["display_end"] = _end(cell.get("end"))
        cid = cell["cell_id"]
        if cid not in traces:
            traces[cid] = client.trace(cid, context=data["context"])["trace"]
        value = "—" if cell["value"] is None else f"{Decimal(cell['value']) / 1000000:,.1f}" if cell["unit"] == ['["iso4217:USD"]', '[]'] else str(cell["value"])
        mark = " D" if cell.get("status") == "DERIVED" else ""
        mark += " 검토" if cell.get("reviewed") else ""
        title = cell.get("availability_note") or "출처와 판단 근거"
        return f'<button class="number" data-cell="{esc(cid)}" title="{esc(title)}">{esc(value)}</button><small>{mark}</small>'
    chunks = ["<!doctype html><meta charset='utf-8'><style>body{font:15px system-ui,'Malgun Gothic',sans-serif;margin:24px;color:#183044;background:#f7f9fc}table{border-collapse:collapse;background:white;font-size:13px}td,th{padding:8px;border:1px solid #dce3ea;text-align:right;min-width:85px}th:first-child{text-align:left;position:sticky;left:0;background:white}pre{white-space:pre-wrap;max-width:900px}details{margin:10px 0;padding:8px;background:white}summary{cursor:pointer}.scroll{overflow:auto}.number{border:0;background:transparent;color:#075eac;cursor:pointer;font:inherit}small{color:#647586}dialog{max-width:85vw;max-height:80vh;border:1px solid #aab}h2{margin-top:32px}</style>", f"<h1>{esc(ticker)} 핵심 재무 분석</h1>", f"<p>FY{fiscal_start}–{fiscal_end} · 현재 선택 공시 기준 · 백만 USD(주당·주식 수 제외)</p>", "<p>공시값 산술 비교는 경제적 동일성·재작성 검증이 아닙니다. — 표시는 숫자를 임의 보완하지 않은 항목입니다. 숫자를 누르면 근거를 볼 수 있습니다.</p>", f"<details><summary>조회 범위와 발행본</summary><pre>{esc(json.dumps(data['context'],ensure_ascii=False,indent=2))}</pre></details>"]
    chunks.extend([f"<title>{esc(ticker)} 핵심 재무 분석 · FY{fiscal_start}–{fiscal_end}</title>", '<label>산술 비교: <select id="comparison"><option value="YOY">전년 동기</option><option value="QOQ">전분기</option><option value="NONE">숨김</option></select></label><style>[data-metric="QOQ"]{display:none}</style>'])
    chunks.append(f'<p><small>공시 기준 {esc(data["context"]["as_of"])} · 검토 기준 {esc(data["context"]["review_cutoff"] or "별도 검토 없음")} · D: 계산된 분기 · 검토: 원문 표 기준 확인</small></p>')
    for period in ("QTD_3M", "INSTANT"):
        cols = [c for c in data["columns"] if c["period_class"] == period]
        chunks.append(f"<h2>{'분기 금액' if period == 'QTD_3M' else '기말 잔액'}</h2><div class='scroll'><table><tr><th>항목</th>" + "".join(f"<th>{esc(c['fiscal_label'])}<br><small>{esc(_end(c.get('actual_end_date') or c.get('actual_instant_date')))}</small></th>" for c in cols) + "</tr>")
        for row in [r for r in data["rows"] if r["period_class"] == period]:
            chunks.append(f"<tr><th>{esc(row['label'])}</th>")
            for col in cols:
                cell = next(c for c in data["cells"] if c["row_id"] == row["row_id"] and c["column_id"] == col["fiscal_time_series_column_id"])
                value = number(cell)
                for key, label in (("YOY", "전년"), ("QOQ", "전분기"), ("GROSS_MARGIN", "매출총이익률"), ("OPERATING_MARGIN", "영업이익률")):
                    metric = next((m for m in data["metrics"] if m["row_id"] == row["row_id"] and m["column_id"] == cell["column_id"] and m["metric_id"] == key), None)
                    if metric and metric["value"] is not None:
                        value += f'<small data-metric="{key}"><br>{label} {Decimal(metric["value"]):,.1f}%</small>'
                        traces[cell["cell_id"]].setdefault("displayed_metrics", {})[key] = metric
                chunks.append(f"<td>{value}</td>")
            chunks.append("</tr>")
        chunks.append("</table></div>")
    chunks.append("<h2>필요한 구성만 펼쳐보기</h2><p>기준 분기의 금액 상위 5개와 중요한 변화·경고를 먼저 봅니다. 구성비는 별도 경제적 분해 검토가 없으면 계산하지 않습니다.</p>")
    for selection, selection_label in (("important", "중요 항목"), ("all", "모든 항목·숨긴 관점 포함")):
      chunks.append(f"<details class='selection'><summary>{selection_label}</summary>")
      for row in data["rows"]:
        groups = client.list_breakdowns(row["row_id"], context=data["context"], include_hidden=selection == "all")["groups"]
        if not groups:
            continue
        chunks.append(f"<details><summary>{esc(row['label'])} · {len(groups)}개 관점</summary>")
        for group in groups:
            chunks.append(f'<details class="branch" data-node="{stable(group["node_id"], (), selection)}"><summary>{esc(group["label"])} · {esc(group.get("basis_version") or group["lens_type"])}</summary></details>')
            pending = [(group["node_id"], (), selection)]
            while pending:
                nid, path, branch_selection = pending.pop()
                branch_key = stable(nid, path, branch_selection)
                if branch_key in branches:
                    continue
                result = client.children(nid, context=data["context"], limit=1000, path=path, selection=branch_selection)
                all_children, all_cells = list(result["children"]), list(result["cells"])
                while result["next_cursor"]:
                    result = client.children(nid, context=data["context"], cursor=result["next_cursor"], limit=1000, path=path, selection=branch_selection)
                    all_children.extend(result["children"])
                    all_cells.extend(result["cells"])
                for cell in [*all_cells, *result["parent_cells"]]:
                    cell["display_value"] = number(cell)
                for child in all_children:
                    child["branch_key"] = stable(child["node_id"], (*path, nid), branch_selection)
                branches[branch_key] = {"children": all_children, "cells": all_cells, "columns": result["columns"], "parent_cells": result["parent_cells"],
                                        "excluded_count": result["excluded_count"], "excluded_warnings": result["excluded_warnings"], "selection": branch_selection}
                pending.extend((c["node_id"], (*path, nid), branch_selection) for c in all_children if c["has_children"])
        chunks.append("</details>")
      chunks.append("</details>")
    payload = json.dumps({"branches": branches, "traces": traces}, ensure_ascii=False).replace("<", "\\u003c")
    chunks.append('<dialog id="trace"><button id="close">닫기</button><pre></pre></dialog><script type="application/json" id="bundle">' + payload + '</script>')
    chunks.append("""<script>
const D=JSON.parse(document.querySelector('#bundle').textContent), modal=document.querySelector('#trace');
document.querySelector('#comparison').onchange=e=>document.querySelectorAll('[data-metric="YOY"],[data-metric="QOQ"]').forEach(n=>n.style.display=n.dataset.metric===e.target.value?'inline':'none');
document.querySelector('#close').onclick=()=>modal.close();
document.addEventListener('click',e=>{let b=e.target.closest('[data-cell]');if(b){modal.querySelector('pre').textContent=JSON.stringify(D.traces[b.dataset.cell],null,2);modal.showModal();}});
function expand(el){if(el.dataset.loaded)return;el.dataset.loaded='1';let id=el.dataset.node,path=JSON.parse(el.dataset.path||'[]');if(path.includes(id)){el.append('순환 경로: 탐색 종료');return;}
let data=D.branches[id];if(!data)return;let offset=0;
function tableFor(cells){let box=document.createElement('div');box.className='scroll';let table=document.createElement('table'),head=document.createElement('tr'),row=document.createElement('tr');let kind=cells[0]?.period_class;for(let col of data.columns.filter(c=>!kind||c.period_class===kind)){let c=cells.find(x=>x.column_id===col.fiscal_time_series_column_id),th=document.createElement('th'),td=document.createElement('td');th.textContent='FY'+col.fiscal_year+' Q'+col.fiscal_quarter;td.innerHTML=c?c.display_value:'—';td.title=c?(c.start||'')+' ~ '+c.display_end+' · '+c.status:'이 경로에 해당 기간 관측 없음';head.append(th);row.append(td);}table.append(head,row);box.append(table);return box;}
if(data.parent_cells.length){let caption=document.createElement('p');caption.textContent='상위 항목의 값(관점별 수치는 서로 합산하지 않음)';el.append(caption,tableFor(data.parent_cells));}
if(data.excluded_count){let note=document.createElement('p');note.textContent=data.excluded_count+'개 항목은 현재 중요 항목 목록에서 제외됨';el.append(note);}
function page(){let group=data.children.slice(offset,offset+5);offset+=group.length;
for(let n of group){let det=document.createElement('details'),summary=document.createElement('summary'),ev=n.importance||{},labels={TOP_AMOUNT:'금액 상위',USER_PINNED:'고정 항목',SIGN_TRANSITION:'손익 부호 전환',BASIS_WARNING:'보고 기준 변경',CRITICAL_SOURCE_WARNING:'원천 검토 경고',ABRUPT_RATE_AND_MATERIAL_CHANGE:'큰 금액·비율 변화',REFERENCE_PERIOD_UNAVAILABLE_FORMER_TOP_AMOUNT:'최신 분기 값 미준비 · 과거 주요 항목',STRUCTURAL_NAVIGATION:'세부 경로'};summary.textContent=n.label+' · '+(n.importance_reasons||[]).map(x=>labels[x]||x).join(', ')+(ev.parent_share===null?' · 구성비 검토 필요':ev.parent_share?' · 구성비 '+Number(ev.parent_share).toFixed(1)+'%':'');det.append(summary);
let cells=data.cells.filter(c=>c.node_id===n.node_id);if(cells.length)det.append(tableFor(cells));
let reason=document.createElement('p');reason.textContent=(n.importance_reasons||[]).map(x=>labels[x]||x).join(' · ');det.append(reason);
let proof=document.createElement('details'),proofTitle=document.createElement('summary'),evidence=document.createElement('pre');proofTitle.textContent='중요도 판단 근거';evidence.textContent=JSON.stringify({importance_reasons:n.importance_reasons,reference_importance:ev,importance_history:n.importance_history},null,2);proof.append(proofTitle,evidence);det.append(proof);
if(n.has_children){det.classList.add('branch');det.dataset.node=n.branch_key;det.dataset.path=JSON.stringify([...path,id]);}el.append(det);}
if(offset<data.children.length){let more=document.createElement('button');more.textContent='다음 5개 펼치기 ('+(data.children.length-offset)+'개 남음)';more.onclick=()=>{more.remove();page();};el.append(more);}}
page();}
document.addEventListener('toggle',e=>{if(e.target.open&&e.target.classList.contains('branch'))expand(e.target)},true);
</script>""")
    destination.write_text("\n".join(chunks), encoding="utf-8")


def render_catalog(client: AnalysisClient, *, destination: Path) -> Path:
    """Render the same public overview/exploration outputs for a catalogue."""
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for ticker, info in client.manifest["companies"].items():
        render_analysis(client, ticker=ticker, destination=destination / (ticker + ".html"), fiscal_start=min(info["years"]), fiscal_end=max(info["years"]))
        rows.append(f'<li><a href="{html.escape(ticker)}.html">{html.escape(ticker)} · FY{min(info["years"])}–{max(info["years"])}</a> · 공시 기준 {html.escape(info["as_of"])}</li>')
    target = destination / "index.html"
    target.write_text('<!doctype html><meta charset="utf-8"><title>기업별 핵심 재무 분석</title><style>body{font:17px system-ui;margin:48px;line-height:1.8}a{color:#075eac}</style><h1>기업별 핵심 재무 분석</h1><p>핵심 요약에서 필요한 세부 항목과 원문 근거를 펼쳐볼 수 있습니다.</p><ul>' + ''.join(rows) + '</ul><p>모든 공백이 해소된 자료는 아닙니다. 공시 항목 변경·서술의 숫자 전환 등 미승인 범위는 사유를 표시하며 숫자를 임의 보완하지 않습니다. D는 계산 분기, 검토는 원문 표 기준 확인입니다.</p>', encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--configuration", type=Path)
    parser.add_argument("--fiscal-start", type=int)
    parser.add_argument("--fiscal-end", type=int)
    args = parser.parse_args()
    config = json.loads(args.configuration.read_text()) if args.configuration else None
    print(prepare_analysis(publication=args.publication, destination=args.destination, tickers=tuple(args.tickers), configuration=config,
                           fiscal_start=args.fiscal_start, fiscal_end=args.fiscal_end))


if __name__ == "__main__":
    main()
