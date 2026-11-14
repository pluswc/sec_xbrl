"""Enrich a pinned revenue asset with separate ROOT-reviewed Q4 grants only."""
from __future__ import annotations

import argparse
import copy
import json
import os
from decimal import Decimal, localcontext
from pathlib import Path

import polars as pl

from examples.screening.prepare_revenue_breakdowns import _bounded_payload, _source
from sec_xbrl.analytics.quarterly_derived_metrics import percentage_result
from sec_xbrl.analytics.revenue_q4_continuity import (
    RATIO_RULE,
    REVIEW_VERSION,
    RULE_VERSION,
    _digest,
    _input_problem,
    derive_reviewed_q4,
    exact_difference,
)
from sec_xbrl.analytics.revenue_quarters import ASSURANCE, REVENUE_QNAMES, _problem
from sec_xbrl.screening.common import (
    canonical_json,
    regular_file,
    safe_new_destination,
    sha256_file,
)

SCHEMA = "reviewed-revenue-q4-continuity-companion-v1"


def _pin(pin: dict) -> bytes:
    path = regular_file(Path(pin["path"]), "reviewed revenue input")
    data = path.read_bytes()
    import hashlib
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("reviewed revenue input differs from its exact pin")
    return data


def _target(asset: dict, target: dict) -> tuple[dict, dict | None, dict, int, dict]:
    if target.get("fiscal_quarter") != 4:
        raise ValueError("review grants are restricted to explicit Q4 targets")
    view = asset["companies"][target["cik"]]["quarterly"]
    matches = [(index, period) for index, period in enumerate(view["periods"])
               if (period["fiscal_year"], period["fiscal_quarter"]) == (target["fiscal_year"], target["fiscal_quarter"])]
    if len(matches) != 1:
        raise ValueError("review target quarter is not uniquely prepared")
    index, period = matches[0]
    if target["group"] == "totals":
        return view, None, period, index, view["totals"][index]
    rows = [row for row in view["groups"][target["group"]]
            if row["id"] == target["row_id"] and row["mapping_epoch"] == target["mapping_epoch"]]
    if len(rows) != 1:
        raise ValueError("review target full row/epoch is not uniquely prepared")
    row, = rows
    return view, row, period, index, row["cells"][index]


def _evidence(grant: dict, files: dict) -> None:
    items = grant.get("evidence")
    if not isinstance(items, list) or not items or any(not isinstance(item, dict)
        or item.get("file_id") not in files or not item.get("locator") or not item.get("assertion") for item in items):
        raise ValueError("review grant lacks exact registered disclosure evidence")


def _load_sources(review: dict, baseline: dict, consumed: list[dict]) -> tuple[list[dict], dict[tuple[str, str, str], str]]:
    inventory = json.loads(_pin(review["source_inventory"]))
    ciks = {link["cik"] for link in review["amount_links"]}
    ciks.update(grant["target"]["cik"] for key in ("projection_grants", "share_grants", "yoy_grants", "hold_grants") for grant in review.get(key, []))
    rows, names = [], {}
    for cik in sorted(ciks):
        source = inventory[cik]
        pins = [source[key] for key in ("analysis", "history", "t1_manifest", "t2_manifest")]
        pins += list(source["t1_files"].values())
        for pin in pins:
            _pin(pin)
            consumed.append(pin)
        history = json.loads(_pin(source["history"]))
        panel = json.loads(_pin(source["t1_manifest"]))
        expected = baseline["companies"][cik]["quarterly"]["ratio_evidence"]
        if (expected["history_manifest_sha256"] != source["history"]["sha256"]
            or expected["reported_panel_manifest_sha256"] != source["t1_manifest"]["sha256"]
            or expected["reported_observations_sha256"] != source["t1_files"]["reported_period_observation"]["sha256"]
            or history["input_fingerprint"] != panel["run_fingerprint"]):
            raise ValueError("review source inventory differs from the exact baseline reported panel")
        for kind in ("company_axis_map", "company_member_map"):
            for mapping in pl.read_parquet(source["t1_files"][kind]["path"]).to_dicts():
                key = (cik, mapping["source_filing_id"], mapping["source_raw_concept_id"])
                if key in names and names[key] != mapping["source_qname"]:
                    raise ValueError("raw source name is ambiguous in its filing")
                names[key] = mapping["source_qname"]
        frame = pl.scan_parquet(source["t1_files"]["reported_period_observation"]["path"]).filter(
            (pl.col("cik") == cik) & pl.col("raw_concept_qname").is_in(sorted(REVENUE_QNAMES))
            & pl.col("period_class").is_in(["FY", "YTD_9M", "QTD_3M"])
        ).collect()
        rows.extend(frame.to_dicts())
    return rows, names


def _review_source(row: dict, cik: str, cutoff: str) -> dict | None:
    # Add only the source selector expected by the existing trace formatter.
    return _source({**row, "selected_source_fact_id": row["source_fact_id"]}, cik, cutoff)


def _period(record: dict) -> tuple:
    return record["cik"], record["context_start_date"], record["context_end_date"]


def _basis(records: list[dict]) -> bool:
    inputs = [row for record in records for row in record["source_inputs"]]
    return all(len({row.get(key) for row in inputs}) == 1 for key in ("basis_version", "structural_version", "recast_version"))


def _percentage(top: str, bottom: str, *, yoy: bool) -> str:
    # The existing revenue ratio helper and its published Decimal precision are retained.
    with localcontext() as context:
        context.prec = 28
        return str(percentage_result(Decimal(top), Decimal(bottom), subtract_one=yoy))


def enrich(review: dict, baseline: dict, old: dict, observations: list[dict], *, scope_names: dict | None = None) -> tuple[dict, dict]:
    """Pure projection entry: all business arithmetic remains outside the UI."""
    if (review.get("schema_version") != REVIEW_VERSION or review.get("authority") != "ROOT"
        or review.get("status") != "ROOT_APPROVED" or review.get("financial_as_of") != baseline["financial_as_of"]):
        raise ValueError("exact ROOT-approved revenue continuity review required")
    for field in ("dataset_id", "dataset_publication_id", "dataset_manifest_sha256", "financial_as_of"):
        if old.get(field) != baseline.get(field):
            raise ValueError("baseline revenue companion scope differs")
    for key in ("amount_links", "projection_grants", "share_grants", "yoy_grants", "hold_grants"):
        for grant in review.get(key, []):
            _evidence(grant, review["evidence_files"])
    output = copy.deepcopy(baseline)
    metrics, exclusions = derive_reviewed_q4(observations, review["amount_links"], cutoff=review["financial_as_of"])
    amounts = {metric["amount_id"]: metric for metric in metrics}
    original = {row["period_observation_id"]: row for row in observations}
    if len(original) != len(observations):
        raise ValueError("ambiguous original observation identity")
    old_metrics = {metric["derived_metric_id"]: metric for company in old["companies"].values() for metric in company["derived_metrics"]}
    by_fact = {(row["source_snapshot_id"], row["source_fact_id"]): row for row in observations}

    def record(reference: dict) -> dict:
        if set(reference) == {"amount_id"}:
            value = amounts.get(reference["amount_id"])
            if value is None:
                raise ValueError("reviewed amount is unavailable; dependent grant cannot proceed")
            return value
        if set(reference) != {"derived_metric_id"} or reference["derived_metric_id"] not in old_metrics:
            raise ValueError("ratio reference is not an exact approved amount")
        metric = copy.deepcopy(old_metrics[reference["derived_metric_id"]])
        inputs = []
        for source in metric["source_inputs"]:
            row = original.get(source["period_observation_id"])
            if row is None or any(source.get(key) != value for key, value in row.items()) or _problem(row, review["financial_as_of"]):
                raise ValueError("existing Q4 source differs from confirmed original T1 scope")
            inputs.append(row)
        if len(inputs) != 2 or exact_difference(inputs[0]["value_numeric"], inputs[1]["value_numeric"]) != metric["value_numeric"]:
            raise ValueError("existing Q4 arithmetic or source pair differs")
        metric["source_inputs"] = inputs
        return metric

    def target_scope(row: dict, metric: dict) -> None:
        if scope_names is None:
            raise ValueError("exact raw axis/member map is required for target binding")
        source = metric["source_inputs"][-1]
        actual = {}
        for dimension in source["raw_dimension_signature"]:
            axis, member = [scope_names.get((source["cik"], source["source_filing_id"], identity)) for identity in dimension[:2]]
            if not axis or not member or axis in actual:
                raise ValueError("source full raw scope is not uniquely named")
            actual[axis] = member
        expected = {**row["axis_members"], **(row.get("fixed_axis_members") or {})}
        if actual != expected:
            raise ValueError("target full axis/member scope differs from original filing fact")

    for metric in metrics:
        named = []
        for source in metric["source_inputs"]:
            if scope_names is None:
                raise ValueError("full raw name maps are required for reviewed scope correspondence")
            pairs = [(scope_names.get((source["cik"], source["source_filing_id"], dim[0])),
                      scope_names.get((source["cik"], source["source_filing_id"], dim[1]))) for dim in source["raw_dimension_signature"]]
            if any(not axis or not member for axis, member in pairs) or len({axis for axis, _ in pairs}) != len(pairs):
                raise ValueError("reviewed source raw axis/member names are incomplete")
            named.append(dict(pairs))
        if set(named[0]) != set(named[1]) or metric["review_link"]["relation"] == "SAME" and named[0] != named[1]:
            raise ValueError("reviewed SAME/RENAMED full scope correspondence differs from source maps")

    projected = {}
    for grant in review["projection_grants"]:
        metric = record({"amount_id": grant["amount_id"]})
        if metric["comparison_only"]:
            raise ValueError("comparison-only prior may not overwrite historical display")
        view, row, period, index, cell = _target(output, grant["target"])
        if row is None or metric["fiscal_year"] != period["fiscal_year"] or _period(metric) != (grant["target"]["cik"], period["period_start"], period["period_end"]):
            raise ValueError("reviewed Q4 does not match exact target period")
        target_scope(row, metric)
        previous_reason = cell.get("reason")
        if cell.get("value") is not None or cell.get("reason") == "COMPETING_PREPARED_SCOPE":
            raise ValueError("direct or competing Q4 has precedence")
        peers = [other["cells"][index] for group in view["groups"].values() for other in group
                 if other["axis_members"] == row["axis_members"] and (other["cells"][index].get("value") is not None
                     or other["cells"][index].get("reason") == "COMPETING_PREPARED_SCOPE")]
        if peers:
            raise ValueError("another direct/derived or competing scope has precedence")
        if grant.get("connect_previous"):
            previous = grant.get("previous")
            if not previous or index == 0 or previous.get("cell_id") != row["cells"][index - 1].get("cell_id"):
                raise ValueError("explicit prior cell evidence is required for a chart epoch connection")
        sources = [_review_source(source, metric["cik"], review["financial_as_of"]) for source in metric["source_inputs"]]
        if not all(sources):
            raise ValueError("reviewed source trace is not qualified")
        row["cells"][index] = {"value": metric["value_numeric"], "status": "DERIVED", "reason": None,
            "cell_id": metric["derived_metric_id"], "sources": sources, "share": None, "yoy": None,
            "derivation_rule_version": RULE_VERSION, "formula": "FY - YTD_9M", "basis_assurance": ASSURANCE,
            "continuity_review_id": metric["amount_id"], "connect_previous": grant.get("connect_previous") is True, "connect_next": False,
            "ratio_hold_reason": "Q4_RATIO_REVIEW_NOT_GRANTED"}
        summaries = view.get("availability", {}).get(grant["target"]["group"], [])
        if summaries:
            summary = summaries[index]
            summary["available_count"] += 1
            if summary.get("gap_counts", {}).get(previous_reason, 0) > 0:
                summary["gap_counts"][previous_reason] -= 1
                if not summary["gap_counts"][previous_reason]:
                    del summary["gap_counts"][previous_reason]
        projected[metric["amount_id"]] = grant["target"]

    diagnostics = []
    for grant in review.get("hold_grants", []):
        if grant.get("reason") != "Q4_SOURCE_TAG_PRESENTATION_CONFLICT":
            raise ValueError("unsupported explicit review diagnostic")
        view, row, _, index, cell = _target(output, grant["target"])
        if row is None or cell.get("value") is not None:
            raise ValueError("source diagnostic may only refine an exact existing null component")
        sources = []
        for identity in grant.get("source_observation_ids", []):
            source = original.get(identity)
            if source is None or source["cik"] != grant["target"]["cik"]:
                raise ValueError("diagnostic original observation differs")
            reference = _review_source(source, source["cik"], review["financial_as_of"])
            if reference and reference not in sources:
                sources.append(reference)
        previous_reason = cell.get("reason")
        cell["reason"] = grant["reason"]
        cell["review_hold"] = {"reason": grant["reason"], "evidence": copy.deepcopy(grant["evidence"]), "sources": sources}
        summaries = view.get("availability", {}).get(grant["target"]["group"], [])
        if summaries:
            counts = summaries[index].setdefault("gap_counts", {})
            if counts.get(previous_reason, 0):
                counts[previous_reason] -= 1
                if not counts[previous_reason]:
                    del counts[previous_reason]
            counts[grant["reason"]] = counts.get(grant["reason"], 0) + 1
        diagnostics.append(copy.deepcopy(grant))

    ratio_records = []
    def numerator(grant):
        target = grant["target"]
        _, row, period, _, cell = _target(output, target)
        source = record(grant.get("numerator", grant.get("current")))
        if source["fiscal_year"] != period["fiscal_year"] or cell["cell_id"] != source["derived_metric_id"] or cell["value"] != source["value_numeric"] or _period(source) != (target["cik"], period["period_start"], period["period_end"]):
            raise ValueError("ratio numerator differs from exact projected Q4")
        target_scope(row, source)
        return source, row, cell

    def parent_record(reference):
        if set(reference) == {"amount_id"}:
            parent = record(reference)
            target = projected.get(reference["amount_id"])
            if target is None:
                raise ValueError("reviewed ratio parent lacks an explicit projection")
            _, row, _, _, _ = _target(output, target)
            return parent, row
        _, row, period, _, cell = _target(baseline, reference["target"])
        if reference["cell_id"] != cell.get("cell_id") or reference["cell_sha256"] != _digest(cell) or cell.get("value") is None:
            raise ValueError("ratio parent differs from exact pinned baseline cell")
        sources = [by_fact.get((source["snapshot_id"], source["fact_id"])) for source in cell["sources"]]
        if any(source is None or _input_problem(source, review["financial_as_of"]) or source.get("mapping_review_required") for source in sources):
            raise ValueError("ratio parent source is not qualified")
        if any(source["cik"] != reference["target"]["cik"] for source in sources):
            raise ValueError("ratio parent company differs")
        if len(sources) == 2:
            if (sources[0].get("comparative_type"), sources[1].get("comparative_type")) != ("CURRENT_FOCUS", "CURRENT_FOCUS") or sources[0]["fiscal_year"] != sources[1]["fiscal_year"] or sources[0]["context_start_date"] != sources[1]["context_start_date"]:
                raise ValueError("ratio parent fiscal window differs")
            if (sources[0]["period_class"], sources[1]["period_class"]) != ("FY", "YTD_9M") or sources[0]["canonical_dimension_signature"] != sources[1]["canonical_dimension_signature"] or sources[0]["company_canonical_concept_id"] != sources[1]["company_canonical_concept_id"]:
                raise ValueError("ratio parent lacks a confirmed FY/YTD9 scope")
            value = exact_difference(sources[0]["value_numeric"], sources[1]["value_numeric"])
            start, end = sources[1]["context_end_date"], sources[0]["context_end_date"]
        elif len(sources) == 1 and sources[0]["period_class"] == "QTD_3M":
            value = sources[0]["value_numeric"]
            start, end = sources[0]["context_start_date"], sources[0]["context_end_date"]
        else:
            raise ValueError("ratio parent source pair is not unique")
        from datetime import date
        if Decimal(value) != Decimal(cell["value"]) or (start, end) != (period["period_start"], period["period_end"]) or not 75 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 105:
            raise ValueError("ratio parent actual period or value differs")
        parent = {"cik": reference["target"]["cik"], "context_start_date": start, "context_end_date": end,
                  "value_numeric": value, "source_inputs": sources}
        if row is None:
            if any(source["raw_dimension_signature"] or source["canonical_dimension_signature"] for source in sources):
                raise ValueError("consolidated denominator source must be undimensioned")
        else:
            target_scope(row, parent)
        return {"cik": reference["target"]["cik"], "context_start_date": start, "context_end_date": end,
                "value_numeric": value, "source_inputs": sources}, row

    def share_revenue_scope(source: dict, parent: dict) -> bool:
        numerator_inputs, parent_inputs = source["source_inputs"], parent["source_inputs"]
        comparisons = list(zip(numerator_inputs, parent_inputs, strict=True)) if len(numerator_inputs) == len(parent_inputs) else [(numerator_inputs[0], parent_inputs[0])]
        for numerator_input, parent_input in comparisons:
            if any(numerator_input.get(key) != parent_input.get(key) for key in
                ("raw_concept_qname", "raw_concept_namespace_uri", "unit_numerator_measures", "unit_denominator_measures")):
                return False
            if numerator_input.get("source_filing_id") != parent_input.get("source_filing_id"):
                return False  # No cross-filing denominator bridge has been approved.
            if any(numerator_input.get(key) != parent_input.get(key) for key in
                ("raw_concept_id", "source_snapshot_id", "accession")):
                return False
            if len(numerator_inputs) == len(parent_inputs) and any(numerator_input.get(key) != parent_input.get(key) for key in
                ("context_start_date", "context_end_date", "period_class")):
                return False
        return True

    def disclosed_fixed_total(grant: dict, row: dict, parent: dict, parent_row: dict | None) -> bool:
        qualifier = {"srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember"}
        evidence_hashes = {review["evidence_files"][item["file_id"]].get("sha256") for item in grant["evidence"]}
        return (grant.get("denominator_relation") == "DISCLOSED_FIXED_SCOPE_TOTAL_EQUIVALENCE"
            and grant["target"]["group"] == "segments" and row.get("scope") is None
            and set(row["axis_members"]) == {"us-gaap:StatementBusinessSegmentsAxis", "srt:ConsolidationItemsAxis"}
            and row["axis_members"].get("srt:ConsolidationItemsAxis") == qualifier["srt:ConsolidationItemsAxis"]
            and row.get("fixed_axis_members") == qualifier and parent_row is None
            and grant["denominator"].get("target", {}).get("group") == "totals"
            and len(parent["source_inputs"]) == 2
            and grant.get("denominator_source_fact_ids") == [source["source_fact_id"] for source in parent["source_inputs"]]
            and len(evidence_hashes - {None}) >= 2)

    for grant in review["share_grants"]:
        source, row, cell = numerator(grant)
        parent, parent_row = parent_record(grant["denominator"])
        disclosed_parent = disclosed_fixed_total(grant, row, parent, parent_row)
        reason = None
        if _period(source) != _period(parent) or not _basis([source, parent]):
            reason = "Q4_SHARE_PARENT_PERIOD_OR_BASIS_MISMATCH"
        elif not share_revenue_scope(source, parent):
            reason = "Q4_SHARE_REVENUE_CONCEPT_OR_FILING_MISMATCH"
        elif (row.get("fixed_axis_members") != (parent_row or {}).get("fixed_axis_members") and not disclosed_parent) or row.get("scope") and (parent_row is None or parent_row.get("member") != row["scope"]):
            reason = "Q4_SHARE_FIXED_PARENT_SCOPE_MISMATCH"
        elif not row.get("scope") and parent_row is not None:
            reason = "Q4_SHARE_PARENT_SCOPE_MISMATCH"
        elif Decimal(parent["value_numeric"]) <= 0 or not 0 <= Decimal(source["value_numeric"]) <= Decimal(parent["value_numeric"]):
            reason = "Q4_SHARE_PARENT_OR_NUMERATOR_NOT_ELIGIBLE"
        cell["q4_ratio_reviewed"] = True
        if reason:
            cell.setdefault("ratio_holds", {})["share"] = reason
            exclusions.append({"target": grant["target"], "reason": reason})
            continue
        if cell.get("share") is not None:
            raise ValueError("existing non-null ratio must not be replaced")
        cell["share"] = _percentage(source["value_numeric"], parent["value_numeric"], yoy=False)
        cell.setdefault("ratios", {})["share"] = {"denominator": "DISCLOSED_FIXED_SCOPE_TOTAL" if disclosed_parent else "SEGMENT_SUBTOTAL" if row.get("scope") else "CONSOLIDATED",
            **({"denominator_relation": grant["denominator_relation"], "denominator_source_fact_ids": grant["denominator_source_fact_ids"]} if disclosed_parent else {}),
            "derivation_rule_version": RATIO_RULE, "parent_value": parent["value_numeric"], "basis_assurance": ASSURANCE,
            "source_fact_ids": [item["source_fact_id"] for item in parent["source_inputs"]]}
        ratio_records.append({"kind": "share", "grant": grant, "value": cell["share"], "inputs": [source, parent]})

    for grant in review["yoy_grants"]:
        current, _, cell = numerator(grant)
        prior = record(grant["prior"])
        left, right = current["source_inputs"], prior["source_inputs"]
        same_paired_scope = len(left) == len(right) == 2 and all(row.get("comparative_type") == "CURRENT_FOCUS" for row in left) and all(row.get("comparative_type") == "PRIOR_YEAR_COMPARABLE" for row in right) and all(
            (a["source_snapshot_id"], a["source_filing_id"], a["raw_concept_id"], a["raw_dimension_signature"]) ==
            (b["source_snapshot_id"], b["source_filing_id"], b["raw_concept_id"], b["raw_dimension_signature"])
            for a, b in zip(left, right, strict=True))
        same_confirmed_scope = all(not row.get("mapping_review_required") for row in [*left, *right]) and all(
            (row["company_canonical_concept_id"], row["canonical_dimension_signature"]) ==
            (left[0]["company_canonical_concept_id"], left[0]["canonical_dimension_signature"]) for row in [*left, *right])
        from datetime import date
        period_ok = current["fiscal_year"] == prior["fiscal_year"] + 1 and all(330 <= (date.fromisoformat(a) - date.fromisoformat(b)).days <= 400
            for a, b in zip(_period(current)[1:], _period(prior)[1:], strict=True))
        if (current["cik"] != prior["cik"] or not period_ok or not _basis([current, prior])
            or not (same_paired_scope or same_confirmed_scope) or Decimal(current["value_numeric"]) < 0 or Decimal(prior["value_numeric"]) <= 0):
            cell["q4_ratio_reviewed"] = True
            cell.setdefault("ratio_holds", {})["yoy"] = "Q4_YOY_COMPARABLE_PRIOR_NOT_QUALIFIED"
            exclusions.append({"target": grant["target"], "reason": "Q4_YOY_COMPARABLE_PRIOR_NOT_QUALIFIED"})
            continue
        if cell.get("yoy") is not None:
            raise ValueError("existing non-null ratio must not be replaced")
        cell["q4_ratio_reviewed"] = True
        cell["yoy"] = _percentage(current["value_numeric"], prior["value_numeric"], yoy=True)
        cell.setdefault("ratios", {})["yoy"] = {"prior_period_start": prior["context_start_date"], "prior_period_end": prior["context_end_date"],
            "derivation_rule_version": RATIO_RULE, "basis_assurance": ASSURANCE,
            "comparison_policy": "PAIRED_FILINGS_CURRENT_COMPARATIVES" if same_paired_scope else "CONFIRMED_SCOPE_ARITHMETIC",
            "current_value": current["value_numeric"], "prior_value": prior["value_numeric"],
            "current_period_start": current["context_start_date"], "current_period_end": current["context_end_date"],
            "prior_comparison_only": prior.get("comparison_only", False),
            "input_periods": [{"source_fact_id": row["source_fact_id"], "period_start": row["context_start_date"],
                               "period_end": row["context_end_date"], "comparative_type": row["comparative_type"]} for row in [*left, *right]],
            "current_source_fact_ids": current["source_fact_ids"], "prior_source_fact_ids": prior["source_fact_ids"],
            "prior_sources": [_review_source(source, prior["cik"], review["financial_as_of"]) for source in prior["source_inputs"]]}
        ratio_records.append({"kind": "yoy", "grant": grant, "value": cell["yoy"], "inputs": [current, prior]})

    # The enrichment contract never changes any accepted amount or reported ratio.
    for cik, company in baseline["companies"].items():
        if output["companies"][cik].get("annual") != company.get("annual"):
            raise ValueError("annual baseline changed during Q4 enrichment")
        before, after = company["quarterly"], output["companies"][cik]["quarterly"]
        if before["periods"] != after["periods"] or before["totals"] != after["totals"]:
            raise ValueError("baseline period or consolidated total changed")
        for group, rows in before["groups"].items():
            for old_row, new_row in zip(rows, after["groups"][group], strict=True):
                if {key: value for key, value in old_row.items() if key != "cells"} != {key: value for key, value in new_row.items() if key != "cells"}:
                    raise ValueError("baseline row identity/hierarchy changed")
                for old_cell, new_cell in zip(old_row["cells"], new_row["cells"], strict=True):
                    if old_cell.get("value") is not None and any(old_cell.get(key) != new_cell.get(key) for key in ("value", "status", "cell_id", "sources")):
                        raise ValueError("accepted amount/source baseline changed")
                    if any(old_cell.get(key) is not None and old_cell.get(key) != new_cell.get(key) for key in ("share", "yoy")):
                        raise ValueError("accepted non-null ratio changed")
    return output, {"schema_version": SCHEMA, "rule_version": RULE_VERSION, "ratio_rule_version": RATIO_RULE,
        "financial_as_of": baseline["financial_as_of"], "derived_metrics": metrics, "ratio_records": ratio_records, "diagnostics": diagnostics, "exclusions": exclusions}


def publish(review_pin: dict, output: Path, derived_output: Path) -> dict:
    review = json.loads(_pin(review_pin))
    if review.get("schema_version") != REVIEW_VERSION or review.get("authority") != "ROOT" or review.get("status") != "ROOT_APPROVED":
        raise ValueError("exact ROOT-approved revenue continuity review required")
    source_root = Path(__file__).resolve().parents[2]
    implementation = [{"path": str(path), "sha256": sha256_file(path)} for path in
        [*sorted((source_root / "src/sec_xbrl").rglob("*.py")), Path(__file__).resolve(),
         source_root / "examples/screening/prepare_revenue_breakdowns.py"]]
    consumed = [review_pin, review["baseline_asset"], review["baseline_companion"], review["source_inventory"], *review["evidence_files"].values()]
    for pin in consumed:
        _pin(pin)
    destination, companion_path = safe_new_destination(output, "new revenue asset"), safe_new_destination(derived_output, "new reviewed Q4 companion")
    if destination == companion_path:
        raise ValueError("asset and companion require separate new destinations")
    baseline, old = json.loads(_pin(review["baseline_asset"])), json.loads(_pin(review["baseline_companion"]))
    ciks = {link["cik"] for link in review["amount_links"]}
    ciks.update(grant["target"]["cik"] for key in ("projection_grants", "share_grants", "yoy_grants", "hold_grants") for grant in review.get(key, []))
    asset, companion = baseline, None
    for cik in sorted(ciks):
        selected = {**review, "amount_links": [link for link in review["amount_links"] if link["cik"] == cik]}
        for key in ("projection_grants", "share_grants", "yoy_grants", "hold_grants"):
            selected[key] = [grant for grant in review.get(key, []) if grant["target"]["cik"] == cik]
        observations, scope_names = _load_sources(selected, baseline, consumed)
        asset, result = enrich(selected, asset, old, observations, scope_names=scope_names)
        if companion is None:
            companion = result
        else:
            for key in ("derived_metrics", "ratio_records", "diagnostics", "exclusions"):
                companion[key].extend(result[key])
    if companion is None:
        raise ValueError("review requires at least one explicitly scoped grant")
    companion["review_sha256"] = review_pin["sha256"]
    companion["input_pins"] = consumed
    companion["implementation_pins"] = implementation
    body = (canonical_json(companion) + "\n").encode()
    import hashlib
    proof = {"schema_version": SCHEMA, "rule_version": RULE_VERSION, "ratio_rule_version": RATIO_RULE,
             "review_sha256": review_pin["sha256"], "companion_sha256": hashlib.sha256(body).hexdigest()}
    for cik in {grant["target"]["cik"] for key in ("projection_grants", "share_grants", "yoy_grants", "hold_grants") for grant in review.get(key, [])}:
        asset["companies"][cik]["quarterly"]["q4_continuity"] = proof
    encoded_asset = _bounded_payload(asset)
    for pin in [*consumed, *implementation]:
        _pin(pin)
    if {pin["path"] for pin in implementation if pin["path"].endswith(".py") and str(source_root / "src/sec_xbrl") in pin["path"]} != {str(path) for path in (source_root / "src/sec_xbrl").rglob("*.py")}:
        raise ValueError("enrichment implementation source inventory changed")
    # Stage all bytes first; install without replacing any pre-existing output.
    from tempfile import NamedTemporaryFile
    staged = []
    try:
        for path, data in ((companion_path, body), (destination, encoded_asset)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary.write(data)
                staged.append((path, Path(temporary.name)))
        for path, temporary in staged:
            os.link(temporary, path)
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)
    return {"asset_sha256": sha256_file(destination), "companion_sha256": sha256_file(companion_path),
            "derived_count": len(companion["derived_metrics"]), "ratio_count": len(companion["ratio_records"]), "exclusions": companion["exclusions"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--derived-output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish({"path": args.review, "sha256": args.review_sha256}, args.output, args.derived_output)))


if __name__ == "__main__":
    main()
