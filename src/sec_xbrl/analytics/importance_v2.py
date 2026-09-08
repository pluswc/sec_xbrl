"""Versioned U3-R evidence. Five signals, no score and no v1 mutation."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sec_xbrl.analytics.importance import _amount
from sec_xbrl.analytics.investor_metrics import ratio
from sec_xbrl.analytics.statement_structure import finite_decimal, stable_id, validate_fact

POLICY_VERSION = "u3r-important-items-v2"
POLICY = {"share_percent": "10", "share_change_pp": "5", "yoy_percent": "25",
          "parent_scale_percent": "1", "amount_top": 3,
          "rationale": "AMD Q3 2024 Embedded -25.42%/-316m and Client +29.46%/+428m; display defaults, not accounting materiality"}


def evidence(value=None, *, reason=None, inputs=(), denominator=None, current_period=None, comparison_period=None):
    return {"value": None if value is None else str(value), "status": "AVAILABLE" if value is not None else "UNAVAILABLE",
            "reason": reason if reason is not None or value is not None else "INPUT_NOT_AVAILABLE", "input_ids": list(inputs), "denominator": denominator,
            "current_period": current_period, "comparison_period": comparison_period}


def evaluate_signals(*, amount, amount_rank=None, delta=None, rate=None, share=None, share_delta=None, scale=None) -> tuple[list, list]:
    """Pure threshold seam tested independently with Decimal boundary adversaries."""
    reasons, warnings = [], []
    if finite_decimal(amount) is not None and amount_rank is not None and amount_rank <= POLICY["amount_top"]:
        reasons.append("TOP_3_COMPARABLE_AMOUNT")
    if finite_decimal(share) is not None and Decimal(str(share)) >= Decimal(POLICY["share_percent"]):
        reasons.append("REVIEWED_SHARE_AT_LEAST_10_PERCENT")
    if finite_decimal(share_delta) is not None and abs(Decimal(str(share_delta))) >= Decimal(POLICY["share_change_pp"]):
        reasons.append("REVIEWED_SHARE_CHANGE_AT_LEAST_5_PP")
    if finite_decimal(rate) is not None and abs(Decimal(str(rate))) >= Decimal(POLICY["yoy_percent"]):
        if finite_decimal(scale) is not None and Decimal(str(scale)) > 0 and finite_decimal(delta) is not None:
            if abs(Decimal(str(delta))) * 100 >= Decimal(str(scale)) * Decimal(POLICY["parent_scale_percent"]):
                reasons.append("YOY_25_PERCENT_AND_PARENT_SCALE_1_PERCENT")
            else:
                warnings.append("SMALL_BASE_OR_SMALL_ABSOLUTE_CHANGE")
        else:
            warnings.append("EXACT_POSITIVE_REFERENCE_SCALAR_UNAVAILABLE")
    return reasons, warnings


def _period(cell):
    return {k: cell.get(k) for k in ("fiscal_year", "fiscal_quarter", "period_class", "start", "end")} if cell else None


def _scale(current, parent):
    if not current or not parent or _amount(current) is None or _amount(parent) is None or _amount(parent) <= 0:
        return None
    required = ("ticker", "selection_view", "as_of", "start", "end", "period_class", "unit", "source_filing_ids")
    if current.get("basis_version") != parent.get("basis_version"):
        return None
    if any(current.get(k) is None or current.get(k) != parent.get(k) for k in required):
        return None
    # A scale can be a disclosed ancestor scalar, with all of its dimensions
    # present in the child. This is NOT an economic-composition assertion.
    if any(d not in (current.get("dimensions") or []) for d in parent.get("dimensions") or []):
        return None
    if len(parent["source_filing_ids"]) != 1:
        return None
    return parent


def materialize_analytical_v2(*, nodes, edges, cells, core_cells) -> list[dict]:
    by_node = {n["node_id"]: n for n in nodes}
    index, core_index, children, periods = defaultdict(list), defaultdict(list), defaultdict(set), defaultdict(set)
    for c in cells:
        index[(c["node_id"], c["fiscal_year"], c["fiscal_quarter"])].append(c)
    for c in core_cells:
        core_index[(c["row_id"], c["fiscal_year"], c["fiscal_quarter"])].append(c)
    for edge in edges:
        children[edge["parent_id"]].add(edge["child_id"])
        periods[(edge["parent_id"], edge["child_id"])].update(tuple(p) for p in edge["periods"])
    result = []
    for pid, child_ids in children.items():
        parent = by_node[pid]
        for period in sorted(set.union(*(periods[(pid, cid)] for cid in child_ids))):
            candidates = index.get((parent.get("value_node_id") or pid, *period), [])
            if not candidates and parent.get("anchor_row_id"):
                candidates = core_index.get((parent["anchor_row_id"], *period), [])
            parent_cell = candidates[0] if len(candidates) == 1 else None
            selected = {}
            for cid in sorted(child_ids):
                candidates = index.get((by_node[cid].get("value_node_id") or cid, *period), [])
                if period in periods[(pid, cid)] and len(candidates) == 1:
                    selected[cid] = candidates[0]
            # Deduplicate aliases by underlying cell for ranking only; values
            # remain individually addressable and never summed.
            ranked = defaultdict(dict)
            for cid, c in selected.items():
                if _amount(c) is not None:
                    key = stable_id(c["ticker"], c["selection_view"], c["as_of"], c["unit"], c["period_class"], c["start"], c["end"],
                                    c.get("basis_version"), [d[0] for d in c.get("dimensions") or []])
                    ranked[key][c["cell_id"]] = abs(_amount(c))
            ranks = {cell_id: n + 1 for group in ranked.values() for n, (cell_id, _) in enumerate(sorted(group.items(), key=lambda x: (-x[1], x[0])))}
            for cid in sorted(child_ids):
                c = selected.get(cid)
                previous_period = (period[0] - 1, period[1])
                previous_candidates = index.get((by_node[cid].get("value_node_id") or cid, *previous_period), [])
                prior = previous_candidates[0] if len(previous_candidates) == 1 and previous_period in periods[(pid, cid)] else None
                change = ratio(c, prior, metric="YOY", growth=True) if c else {"reason": "REFERENCE_PERIOD_UNAVAILABLE"}
                # ratio's compatibility gate is retained; an invalid duration
                # can otherwise leave an absolute_change attached to a failure.
                delta = change.get("absolute_change") if change.get("reason") in {None, "ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE"} else None
                scalar = _scale(c, parent_cell)
                value = _amount(c) if c else None
                reasons, warnings = evaluate_signals(amount=value, amount_rank=ranks.get(c["cell_id"]) if c else None,
                                                    delta=delta, rate=change.get("value"), scale=scalar["value"] if scalar else None)
                if change.get("reason"):
                    warnings.append(change["reason"])
                if c and c.get("reason"):
                    warnings.append(c["reason"])
                if not c:
                    warnings.append("NOT_REPORTED_IN_REFERENCE_PERIOD_NO_BACKFILL")
                inputs = [x["cell_id"] for x in (c, prior) if x]
                common = {"current_period": _period(c), "comparison_period": _period(prior)}
                result.append({"importance_id": stable_id(POLICY_VERSION, pid, cid, period), "policy_version": POLICY_VERSION,
                               "parent_id": pid, "child_id": cid, "fiscal_year": period[0], "fiscal_quarter": period[1],
                               "current_cell_id": c["cell_id"] if c else None, "comparison_cell_id": prior["cell_id"] if prior else None,
                               "selection_view": c["selection_view"] if c else None, "as_of": c["as_of"] if c else None,
                               "amount": evidence(value, inputs=[c["cell_id"]] if c else [], **common),
                               "amount_rank": ranks.get(c["cell_id"]) if c else None,
                               "amount_change": evidence(delta, reason=change.get("reason") if delta is None else None, inputs=inputs, **common),
                               "rate_change": evidence(change.get("value"), reason=change.get("reason"), inputs=inputs,
                                                       denominator={"cell_id": prior["cell_id"], "value": prior["value"]} if prior else None, **common),
                               "share": evidence(reason="NO_EXACT_REVIEWED_DECOMPOSITION", **common),
                               "share_change_pp": evidence(reason="NO_TWO_PERIOD_SAME_ECONOMIC_SCOPE_REVIEW", **common),
                               "scale_evidence": scalar, "comparison_evidence": change.get("comparison_evidence"),
                               "reasons": reasons, "warnings": sorted(set(warnings)), "evidence_kind": "GOVERNED_ANALYTICAL_INPUTS"})
    return result


def reviewed_raw_shares(*, facts: list[dict], tables: list[dict], reviews: list[dict], decision_cutoff: str) -> list[dict]:
    """Hash-bound review of explicit source table cells; no QName or ticker rules.

    Every member of both complete reviewed compositions must be present and
    positive in an identical exact scope. The separate economic_scope_id is
    required to permit a comparison of shares across two approved periods.
    """
    by_id = {f["fact_id"]: f for f in facts}
    table_index = {(t["source_document_sha256"], t["table_locator"]): t for t in tables}
    cutoff = datetime.fromisoformat(decision_cutoff)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("decision cutoff must be timezone-aware")
    validated = []
    for review in reviews:
        if any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("review_id", "reviewer", "economic_scope_id", "parent_fact_id")) or review.get("complete") is not True or review.get("exclusive") is not True:
            raise ValueError("economic share needs explicit complete/exclusive scope review")
        timestamp = datetime.fromisoformat(review["reviewed_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp > cutoff:
            raise ValueError("economic review is after decision cutoff")
        table = table_index.get((review["source_document_sha256"], review["table_locator"]))
        if not table or table["table_sha256"] != review["table_sha256"]:
            raise ValueError("economic review source table mismatch")
        ids = [review["parent_fact_id"], *review["child_fact_ids"]]
        if len(ids) != len(set(ids)) or len(ids) < 2 or any(i not in by_id for i in ids):
            raise ValueError("review duplicate/missing fact binding")
        parent, *children = [by_id[i] for i in ids]
        for f in [parent, *children]:
            validate_fact(f)
            if f.get("is_nil") or f.get("reported_or_derived") != "REPORTED":
                raise ValueError("review requires nonnil reported raw facts")
            if f["scope"] != review["scope"] or f["scope"] != parent["scope"] or finite_decimal(f["value_numeric"]) is None or Decimal(f["value_numeric"]) <= 0:
                raise ValueError("economic review requires exact positive complete scope")
            expected = review["source_cells"][f["fact_id"]]
            if not any(loc["table_id"] == table["table_id"] and loc["inline_id"] == expected["inline_id"] and loc["row_locator"] == expected["row_locator"] for loc in f["source_locations"]):
                raise ValueError("economic review does not bind exact source cell")
        if sum(Decimal(c["value_numeric"]) for c in children) != Decimal(parent["value_numeric"]):
            raise ValueError("reviewed economic composition does not reconcile")
        if len({c["raw_concept_id"] for c in children}) != len(children):
            raise ValueError("same economic child counted twice")
        for child in children:
            validated.append((review, parent, child, Decimal(child["value_numeric"]) / Decimal(parent["value_numeric"]) * 100))
    records = []
    for review, parent, child, share in validated:
        period = child["scope"]["period"]
        previous = [(r, p, c, v) for r, p, c, v in validated if r["economic_scope_id"] == review["economic_scope_id"]
                    and c["raw_concept_id"] == child["raw_concept_id"] and c["filing_id"] == child["filing_id"]
                    and c["scope"]["period"]["class"] == period["class"]
                    and 330 <= (date.fromisoformat(period["end"]) - date.fromisoformat(c["scope"]["period"]["end"])).days <= 400]
        previous = [item for item in previous if _same_share_comparison((review, parent, child), item[:3], by_id)]
        prior = previous[0] if len(previous) == 1 else None
        delta_share = share - prior[3] if prior else None
        value = Decimal(child["value_numeric"])
        delta = value - Decimal(prior[2]["value_numeric"]) if prior else None
        rate = delta / Decimal(prior[2]["value_numeric"]) * 100 if prior else None
        reasons, warnings = evaluate_signals(amount=value, share=share, share_delta=delta_share, delta=delta, rate=rate, scale=parent["value_numeric"])
        common = {"current_period": period, "comparison_period": prior[2]["scope"]["period"] if prior else None}
        records.append({"importance_id": stable_id(POLICY_VERSION, review["review_id"], child["fact_id"]),
                        "policy_version": POLICY_VERSION, "current_fact_id": child["fact_id"], "parent_fact_id": parent["fact_id"],
                        "comparison_fact_id": prior[2]["fact_id"] if prior else None,
                        "selection_view": "RAW_AS_FILED", "scope": child["scope"], "review": review,
                        "prior_review": prior[0] if prior else None, "decision_cutoff": decision_cutoff,
                        "amount": evidence(value, inputs=[child["fact_id"]], **common),
                        "amount_change": evidence(delta, reason=None if prior else "NO_COMPATIBLE_PRIOR_REVIEW", inputs=[child["fact_id"], prior[2]["fact_id"]] if prior else [child["fact_id"]], **common),
                        "rate_change": evidence(rate, reason=None if prior else "NO_COMPATIBLE_PRIOR_REVIEW", inputs=[child["fact_id"], prior[2]["fact_id"]] if prior else [child["fact_id"]], denominator={"fact_id": prior[2]["fact_id"], "value": prior[2]["value_numeric"]} if prior else None, **common),
                        "share": evidence(share, inputs=[child["fact_id"], parent["fact_id"]], denominator={"fact_id": parent["fact_id"], "value": parent["value_numeric"]}, **common),
                        "share_change_pp": evidence(delta_share, reason=None if prior else "NO_SAME_ECONOMIC_SCOPE_PRIOR_REVIEW", inputs=[child["fact_id"], parent["fact_id"], prior[2]["fact_id"], prior[1]["fact_id"]] if prior else [child["fact_id"], parent["fact_id"]], denominator={"current": {"fact_id": parent["fact_id"], "value": parent["value_numeric"]}, "prior": {"fact_id": prior[1]["fact_id"], "value": prior[1]["value_numeric"]} if prior else None}, **common),
                        "reasons": reasons, "warnings": warnings, "evidence_kind": "REVIEWED_ACTUAL_SOURCE_CELLS"})
    return records


def _same_share_comparison(current, previous, facts) -> bool:
    review, parent, child = current
    prior_review, prior_parent, prior_child = previous
    if any(review[k] != prior_review[k] for k in ("source_document_sha256", "table_locator", "table_sha256", "economic_scope_id")):
        return False
    if parent["raw_concept_id"] != prior_parent["raw_concept_id"]:
        return False
    if {facts[i]["raw_concept_id"] for i in review["child_fact_ids"]} != {facts[i]["raw_concept_id"] for i in prior_review["child_fact_ids"]}:
        return False
    for a, b in ((parent, prior_parent), (child, prior_child)):
        if {k: v for k, v in a["scope"].items() if k != "period"} != {k: v for k, v in b["scope"].items() if k != "period"}:
            return False
        p, q = a["scope"]["period"], b["scope"]["period"]
        if p["class"] != "QTD_3M" or q["class"] != "QTD_3M" or p["type"] != "duration" or q["type"] != "duration":
            return False
        if not all(75 <= (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days <= 105 for x in (p, q)):
            return False
        if not all(330 <= (date.fromisoformat(p[k]) - date.fromisoformat(q[k])).days <= 400 for k in ("start", "end")):
            return False
    return True


def materialize_raw_statement_v2(*, facts: list[dict], tables: list[dict], rows: list[dict], checks: list[dict], reviewed: list[dict]) -> list[dict]:
    """Same-source standard monetary arithmetic, explicitly not recast approval.

    Custom concepts retain amounts but do not gain a comparison basis from a
    shared label or source column. No FY/YTD growth rule is introduced.
    """
    by_id = {f["fact_id"]: f for f in facts}
    reviewed_by_fact = {r["current_fact_id"]: r for r in reviewed}
    results = []
    for table in tables:
        if table["section"] == "DISCLOSURE":
            continue
        table_rows = [r for r in rows if r["table_id"] == table["table_id"]]
        ids = {i["fact_id"] for r in table_rows for c in r["cells"] for i in c["inline_facts"] if i["fact_id"]}
        selected = [by_id[i] for i in sorted(ids)]
        source_row = {i["fact_id"]: r for r in table_rows for c in r["cells"] for i in c["inline_facts"] if i["fact_id"]}
        groups = defaultdict(dict)
        for f in selected:
            unit = f["scope"]["unit"]
            if (f["concept"]["data_type"] != "xbrli:monetaryItemType" or f["is_nil"] or finite_decimal(f["value_numeric"]) is None
                    or len(unit["numerator"]) != 1 or not unit["numerator"][0].startswith("iso4217:") or unit["denominator"]):
                continue
            key = stable_id(f["scope"], source_row[f["fact_id"]]["parent_row_id"])
            groups[key][f["fact_id"]] = abs(Decimal(f["value_numeric"]))
        rank = {fid: n+1 for group in groups.values() for n, (fid, _) in enumerate(sorted(group.items(), key=lambda item: (-item[1], item[0])))}
        for f in selected:
            if f["fact_id"] not in rank:
                continue
            scope, concept = f["scope"], f["concept"]
            period = scope["period"]
            reference = max((g["scope"]["period"]["end"] or g["scope"]["period"]["instant"] for g in selected if g["scope"]["period"]["class"] == period["class"]), default=None)
            previous = []
            approved_standard = (concept["is_standard"] and concept["taxonomy_family"] == "us-gaap"
                                 and concept["namespace_uri"] in {f"http://fasb.org/us-gaap/{concept['taxonomy_version']}", f"https://fasb.org/us-gaap/{concept['taxonomy_version']}"})
            if approved_standard and period["class"] == "QTD_3M":
                for other in selected:
                    op = other["scope"]["period"]
                    if other["raw_concept_id"] != f["raw_concept_id"] or op["class"] != "QTD_3M" or other["is_nil"]:
                        continue
                    if {k: v for k, v in other["scope"].items() if k != "period"} != {k: v for k, v in scope.items() if k != "period"}:
                        continue
                    if not all(75 <= (date.fromisoformat(p["end"])-date.fromisoformat(p["start"])).days <= 105 for p in (op, period)):
                        continue
                    if all(330 <= (date.fromisoformat(period[k])-date.fromisoformat(op[k])).days <= 400 for k in ("start", "end")):
                        previous.append(other)
            prior = previous[0] if len(previous) == 1 else None
            prior_value = finite_decimal(prior["value_numeric"]) if prior else None
            value = Decimal(f["value_numeric"])
            delta = value - prior_value if prior_value is not None else None
            rate = delta / prior_value * 100 if delta is not None and prior_value > 0 and value >= 0 else None
            if not approved_standard:
                comparison_reason = "CUSTOM_COMPARISON_NOT_APPROVED"
            elif period["class"] != "QTD_3M":
                comparison_reason = "GROWTH_POLICY_NOT_APPROVED_FOR_PERIOD_CLASS"
            elif len(previous) > 1:
                comparison_reason = "AMBIGUOUS_SAME_TABLE_PRIOR"
            elif prior is None:
                comparison_reason = "NO_EXACT_SAME_TABLE_PRIOR"
            elif prior_value is None:
                comparison_reason = "NONFINITE_OR_NONNUMERIC_PRIOR"
            else:
                comparison_reason = None
            rate_reason = comparison_reason or ("ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE" if rate is None else None)
            scalar_candidates = {check["parent_fact_id"] for check in checks if check["source_table_id"] == table["table_id"] and check["status"] == "MATCH"
                                 and any(i["child_fact_id"] == f["fact_id"] for i in check["inputs"])
                                 and check["parent_fact_id"] in by_id and finite_decimal(check["parent_value"]) is not None and Decimal(check["parent_value"]) > 0}
            scalar = by_id[next(iter(scalar_candidates))] if len(scalar_candidates) == 1 else None
            reasons, warnings = evaluate_signals(amount=value, amount_rank=rank[f["fact_id"]], delta=delta, rate=rate, scale=scalar["value_numeric"] if scalar else None)
            if prior and (date.fromisoformat(period["end"])-date.fromisoformat(period["start"])).days != (date.fromisoformat(prior["scope"]["period"]["end"])-date.fromisoformat(prior["scope"]["period"]["start"])).days:
                warnings.append("ACTUAL_DURATION_DIFFERS")
            common = {"current_period": period, "comparison_period": prior["scope"]["period"] if prior else None}
            inputs = [f["fact_id"], prior["fact_id"]] if prior else [f["fact_id"]]
            row = {"importance_id": stable_id(POLICY_VERSION, table["table_id"], f["fact_id"]), "policy_version": POLICY_VERSION,
                   "table_id": table["table_id"], "current_fact_id": f["fact_id"], "comparison_fact_id": prior["fact_id"] if prior else None,
                   "selection_view": "RAW_AS_FILED", "scope": scope, "reference_period_end": reference,
                   "is_reference_period": (period["end"] or period["instant"]) == reference,
                   "amount": evidence(value, inputs=[f["fact_id"]], **common), "amount_rank": rank[f["fact_id"]],
                   "amount_change": evidence(delta, reason=comparison_reason, inputs=inputs, **common),
                   "rate_change": evidence(rate, reason=rate_reason, inputs=inputs, denominator={"fact_id": prior["fact_id"], "value": prior["value_numeric"]} if prior else None, **common),
                   "share": evidence(reason="NO_EXACT_REVIEWED_DECOMPOSITION", **common),
                   "share_change_pp": evidence(reason="NO_TWO_PERIOD_SAME_ECONOMIC_SCOPE_REVIEW", **common),
                   "scale_evidence": {"fact_id": scalar["fact_id"], "value": scalar["value_numeric"], "scope": scalar["scope"], "purpose": "MONETARY_SCALE_NOT_COMPOSITION"} if scalar else None,
                   "comparison_evidence": "SAME_TABLE_SAME_RAW_STANDARD_CONCEPT_REPORTED_ARITHMETIC_NOT_RECAST_VALIDATED" if prior else None,
                   "reasons": reasons, "warnings": sorted({*warnings, *([rate_reason] if rate_reason else []), "REPORTED_ARITHMETIC_NOT_RECAST_VALIDATED"}),
                   "evidence_kind": "ACTUAL_SAME_TABLE_RAW_STANDARD_ARITHMETIC"}
            if f["fact_id"] in reviewed_by_fact:
                review_row = reviewed_by_fact[f["fact_id"]]
                row.update({k: review_row[k] for k in ("share", "share_change_pp", "review", "prior_review", "decision_cutoff")})
                row["reasons"] = sorted({*row["reasons"], *review_row["reasons"]})
                row["evidence_kind"] = "REVIEWED_ACTUAL_SOURCE_CELLS"
            results.append(row)
    return results
