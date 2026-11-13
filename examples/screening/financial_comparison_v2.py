"""Governed board-only comparisons; consumes already verified prepared observations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import pairwise
from typing import Any

from examples.screening import prepare_financial_growth as v1
from sec_xbrl.metrics.quarterly_screening import _exact_sum

SCHEMA = "screening-financial-growth-v2"
RULE = "catalog-prepared-financial-comparison-v2"
PP_FORMULA = {"unit": "PERCENTAGE_POINT", "expression": "current - prior",
              "eligibility": "compatible published PERCENT observations and recursively compatible inputs"}
# Explicit input meaning, not display labels or suffix-based accounting inference.
INPUTS = {
    "gross_margin": ("gross_profit", "revenue"), "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"), "fcf_margin": ("standardized_fcf", "revenue"),
    "standardized_fcf": ("cfo", "capex"), "current_ratio": ("current_assets", "current_liabilities"),
    "liabilities_to_equity": ("liabilities", "equity"), "liabilities_to_assets": ("liabilities", "assets"),
    "net_debt": ("debt", "cash"), "revenue_yoy": ("revenue", "revenue"),
    "revenue_qoq": ("revenue", "revenue"),
}


def annual(row: dict) -> bool:
    return "metric_observation_id" in row


def coordinate(row: dict) -> int | None:
    if annual(row):
        return row["fiscal_year"] * 4 if type(row.get("fiscal_year")) is int else None
    return v1._fiscal_index(row)


def eligible(row: dict, cutoff: str) -> bool:
    if any(row.get(key) is True for key in ("basis_break", "continuity_break", "recast_break", "structural_break",
                                           "ambiguous", "recast_review_required", "mapping_uncertainty")):
        return False
    proxy = {**row, "period_class": "FY"} if annual(row) else row
    if row.get("unit") == "USD":
        return v1._eligible(proxy, cutoff)
    if row.get("unit") != "PERCENT":
        return False
    # Reuse all parent eligibility gates, replacing only the declared unit gate.
    proxy = {**proxy, "unit": "USD", "unit_semantics": ['["iso4217:USD"]', '[]']}
    return v1._eligible(proxy, cutoff)


def assurance(row: dict) -> str | None:
    return v1._assurance({**row, "period_class": "FY"} if annual(row) else row)


def window(row: dict) -> tuple[date, date] | None:
    if row.get("period_class") != "INSTANT":
        return v1._dates(row, row.get("period_class"))
    try:
        end = date.fromisoformat(row["period_end"])
    except (ValueError, TypeError, KeyError):
        return None
    convention = row.get("end_convention", "EXCLUSIVE" if annual(row) else None)
    return (end, end) if row.get("period_start") is None and convention == "EXCLUSIVE" else None


def input_rows(row: dict, by_id: dict[str, dict]) -> list[dict]:
    if not annual(row):
        return (row.get("source_lineage") or {}).get("derivation_inputs") or []
    refs = row.get("input_values") or []
    if row.get("input_observation_ids") != [ref.get("observation_id") for ref in refs]:
        return []
    legs = [by_id.get(ref.get("observation_id")) for ref in refs]
    if any(leg is None or any(ref.get(key) != leg.get(key) for key in
                              ("metric_id", "value", "fiscal_year", "period_class", "period_start", "period_end"))
           for ref, leg in zip(refs, legs)):
        return []
    return legs


def signature(row: dict, cutoff: str, by_id: dict[str, dict], catalog: dict[str, dict],
              seen: frozenset[str] = frozenset()) -> tuple | None:
    identity = v1._id(row)
    if (identity in seen or len(seen) > 16 or not eligible(row, cutoff) or assurance(row) is None
            or window(row) is None):
        return None
    definition = catalog.get(row.get("metric_id"))
    if (definition is None or definition["definition_version"] != v1._version(row)
            or definition.get("unit") != row.get("unit")):
        return None
    if row.get("source_kind") != "DERIVED_METRIC":
        return v1._reported_signature({**row, "period_class": "FY"} if annual(row) else row)
    metric = row["metric_id"]
    base = metric.removeprefix("quarter_").removeprefix("ttm_")
    legs = input_rows(row, by_id)
    if not legs or len({v1._id(leg) for leg in legs}) != len(legs):
        return None
    lineage = row.get("source_lineage") or {}
    rule = definition.get("rule_version")
    if annual(row):
        if (row.get("formula") != definition.get("formula")
                or row.get("arithmetic_rule_version") != definition.get("arithmetic_rule_version")):
            return None
        expected = tuple(definition.get("input_metric_ids") or [])
    else:
        if lineage.get("derivation_rule_version") != rule or lineage.get("formula") != definition.get("formula"):
            return None
        prefix = "quarter_"
        if row["period_class"] == "TTM":
            if row["unit"] == "USD":
                expected = (prefix + base,) * 4
            elif base in INPUTS:
                expected = tuple(prefix + name for name in INPUTS[base] for _ in range(4))
            else:
                return None
        else:
            expected = tuple(prefix + name for name in INPUTS.get(base, ()))
    if not expected or tuple(leg.get("metric_id") for leg in legs) != expected:
        return None
    contract = definition.get("input_contract")
    if contract:
        declared = contract.get("inputs") or []
        expanded = [(item, q) for item in declared for q in range(1, 5)] if row["period_class"] == "TTM" else [(item, None) for item in declared]
        if len(expanded) != len(legs):
            return None
        for leg, (item, q) in zip(legs, expanded):
            role = item.get("input_role") + (f"_Q{q}" if q else "")
            constraint, value = item.get("value_constraint"), v1._amount(leg)
            if (leg.get("metric_id") != item.get("metric_id") or leg.get("input_role") != role
                    or value is None or constraint not in ("FINITE", "NONNEGATIVE", "POSITIVE")
                    or constraint == "NONNEGATIVE" and value < 0 or constraint == "POSITIVE" and value <= 0):
                return None
        if row["unit"] == "PERCENT" and contract.get("denominator_policy") != "STRICTLY_POSITIVE":
            return None
    if any(not v1._same_input_scope({**row, "unit": leg.get("unit")}, leg)
           or assurance(leg) != assurance(row) for leg in legs):
        return None
    # Ratios can span units; monetary inputs themselves must remain USD at scale 0.
    if any(leg.get("unit") != "USD" for leg in legs):
        return None
    if row["unit"] == "PERCENT":
        denominators = legs[4:] if row["period_class"] == "TTM" else legs[1:]
        if (any(v1._amount(leg) is None for leg in denominators)
                or (row["period_class"] == "TTM" and _exact_sum(v1._amount(leg) for leg in denominators) <= 0)
                or (row["period_class"] != "TTM" and any(v1._amount(leg) <= 0 for leg in denominators))):
            return None
    if row["period_class"] == "TTM":
        for offset in range(0, len(legs), 4):
            group = legs[offset:offset + 4]
            windows = [window(leg) for leg in group]
            if (len(group) != 4 or any(w is None for w in windows)
                    or any(coordinate(leg) != coordinate(row) - 3 + index for index, leg in enumerate(group))
                    or any(left[1] != right[0] for left, right in pairwise(windows))
                    or (windows[0][0], windows[-1][1]) != window(row)):
                return None
    elif base in ("revenue_yoy", "revenue_qoq"):
        distance = 1 if base == "revenue_qoq" else 4
        if coordinate(legs[0]) != coordinate(row) or coordinate(legs[1]) != coordinate(row) - distance:
            return None
        if window(legs[0]) != window(row):
            return None
    elif any(window(leg) != window(row) or coordinate(leg) != coordinate(row) for leg in legs):
        return None
    signatures = [signature(leg, cutoff, by_id, catalog, seen | {identity}) for leg in legs]
    if any(part is None for part in signatures):
        return None
    # TTM input identities repeat through the four quarters but never their IDs.
    if row["period_class"] == "TTM":
        if any(any((v1._version(leg), part) != (v1._version(legs[offset]), signatures[offset])
                       for leg, part in zip(legs[offset:offset + 4], signatures[offset:offset + 4]))
               for offset in range(0, len(legs), 4)):
            return None
        signatures = signatures[::4]
    return (v1._version(row), rule, definition.get("formula"),
            tuple((name, part) for name, part in zip(expected[::4] if row["period_class"] == "TTM" else expected, signatures)))


def compare(current: dict, prior: dict | None, cutoff: str, by_id: dict[str, dict],
            catalog: dict[str, dict], ambiguous: bool = False) -> dict:
    result = {"current": v1._reference(current), "prior": v1._reference(prior), "status": "UNAVAILABLE",
              "reason": None, "basis_assurance": None, "delta": None, "yoy": None,
              "negative_magnitude_change": None, "change_pp": None}
    def unavailable(reason: str) -> dict:
        return {**result, "reason": reason}
    if current["metric_id"] == "quarter_calculated_total_liabilities" and current.get("availability_status") == "AVAILABLE":
        return unavailable("SUPPORTED_LINEAGE_NOT_PREPARED")
    if not eligible(current, cutoff):
        return unavailable("CURRENT_UNAVAILABLE")
    if ambiguous:
        return unavailable("AMBIGUOUS_FISCAL_PERIOD")
    if prior is None:
        return unavailable("PRIOR_NOT_PREPARED")
    if not eligible(prior, cutoff):
        return unavailable("PRIOR_UNAVAILABLE")
    if (not v1._same_input_scope(current, prior) or v1._version(current) != v1._version(prior)
            or current["metric_id"] != prior["metric_id"] or current["period_class"] != prior["period_class"]
            or assurance(current) is None or assurance(current) != assurance(prior)):
        return unavailable("INCOMPATIBLE_SCOPE")
    newer, older = window(current), window(prior)
    instant = current["period_class"] == "INSTANT"
    if (newer is None or older is None or coordinate(current) is None or coordinate(prior) is None
            or coordinate(current) - coordinate(prior) != 4
            or any(not 330 <= (a - b).days <= 400 for a, b in zip(newer, older))
            or (not instant and (older[1] > newer[0]
                or current["period_class"] in ("FY", "TTM") and older[1] != newer[0]))):
        return unavailable("INCOMPATIBLE_PERIOD")
    current_signature = signature(current, cutoff, by_id, catalog)
    if current_signature is None or signature(prior, cutoff, by_id, catalog) != current_signature:
        return unavailable("INCOMPATIBLE_SEMANTICS")
    if current["period_class"] == "TTM":
        before, after = input_rows(prior, by_id), input_rows(current, by_id)
        if {v1._id(leg) for leg in before} & {v1._id(leg) for leg in after}:
            return unavailable("INCOMPATIBLE_TTM_LINEAGE")
        result["ttm_input_ids"] = {"current": [v1._id(leg) for leg in after], "prior": [v1._id(leg) for leg in before]}
    result["input_observation_ids"] = {"current": [v1._id(leg) for leg in input_rows(current, by_id)],
                                       "prior": [v1._id(leg) for leg in input_rows(prior, by_id)]}
    if current["unit"] == "PERCENT":
        value = v1._decimal_string(v1._exact_subtract(v1._amount(current), v1._amount(prior)))
        return {**result, "status": "CHANGE_AVAILABLE", "change_pp": value, "delta": value,
                "basis_assurance": assurance(current)}
    return {**result, **v1.compare_amounts(v1._amount(current), v1._amount(prior)), "basis_assurance": assurance(current)}


def build_artifact(parent: Any, manifest_sha256: str) -> dict:
    # Preserve every v1 comparison field exactly, including legacy missing reasons.
    legacy = v1.build_artifact(parent, manifest_sha256)
    catalog = {row["metric_id"]: {**row, "period_class": row.get("period_class") or row.get("observation_basis")}
               for row in [*parent.metric_definitions, *parent.quarter_definitions]}
    by_id = {v1._id(row): row for row in parent.observations}
    cutoff = parent.manifest["financial_as_of"]
    definitions = {}
    companies = {company["cik"]: {} for company in parent.companies}
    for metric, definition in catalog.items():
        kind = definition["unit_kind"]
        if kind not in ("MONEY", "PERCENT"):
            continue
        is_annual = metric in {row["metric_id"] for row in parent.metric_definitions}
        basis = "FY" if is_annual else "TTM" if definition["period_class"] == "TTM" else "QTD_3M"
        definitions[metric] = {"basis": basis, "period_class": definition["period_class"],
                               "definition_version": definition["definition_version"], "unit_kind": kind,
                               "comparison_kind": "PERCENTAGE_POINT" if kind == "PERCENT" else "YOY",
                               "source_rule_version": definition.get("rule_version"),
                               "source_formula": definition.get("formula"),
                               "source_input_contract": definition.get("input_contract"),
                               "source_input_metric_ids": definition.get("input_metric_ids"),
                               "formulas": {"change_pp": PP_FORMULA} if kind == "PERCENT" else v1.FORMULAS}
        source = parent.observations if is_annual else parent.quarter_observations
        rows = [row for row in source if row["metric_id"] == metric]
        fiscal = defaultdict(list)
        for row in rows:
            if coordinate(row) is not None:
                fiscal[(row["cik"], coordinate(row))].append(row)
        for row in rows:
            cik = row["cik"]
            slot = str(row["fiscal_year"]) if is_annual else f"{row['calendar_year']}Q{row['calendar_quarter']}"
            output = companies[cik].setdefault(metric, {})
            if slot in output or v1._version(row) != definition["definition_version"]:
                raise ValueError("duplicate period or mismatched catalog definition")
            if metric in legacy["definitions"]:
                output[slot] = legacy["companies"][cik][metric][slot]
                continue
            point = coordinate(row)
            previous = fiscal[(cik, point - 4)] if point is not None else []
            output[slot] = compare(row, previous[0] if len(previous) == 1 else None, cutoff, by_id, catalog,
                                   point is not None and (len(fiscal[(cik, point)]) != 1 or len(previous) > 1))
    return {**legacy, "schema_version": SCHEMA, "rule_version": RULE, "definitions": definitions, "companies": companies}
