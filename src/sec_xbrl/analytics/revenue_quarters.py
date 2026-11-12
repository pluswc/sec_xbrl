"""Governed, conservative dimensional standard-revenue Q4 residuals.

Consumes exact pinned T1 observations. It never reparses Raw or changes the
existing reviewed-Q4 or core quarterly policy. Display consumes its records.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from sec_xbrl.analytics.history_quarters import _derive_additive_difference
from sec_xbrl.analytics.statement_structure import finite_decimal

RULE_VERSION = "confirmed-dimensional-revenue-fy-ytd9-q4-v1"
REVENUE_QNAMES = frozenset({"us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"})
ASSURANCE = "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"


def scope_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Exact company canonical scope, including every explicit dimension."""
    return (str(row.get("cik")), str(row.get("company_canonical_concept_id")),
            json.dumps(sorted(row.get("canonical_dimension_signature") or []), separators=(",", ":")))


def _problem(row: dict[str, Any], cutoff: str) -> str | None:
    dims = row.get("canonical_dimension_signature")
    raw_dims = row.get("raw_dimension_signature")
    if (row.get("mapping_review_required") is not False or not row.get("company_canonical_concept_id")
            or not row.get("concept_mapping_id") or not isinstance(dims, list) or not isinstance(raw_dims, list)
            or len(dims) != len(raw_dims) or len(row.get("dimension_mapping_ids") or []) != len(dims)
            or any(not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(value, str) and value for value in pair)
                   for pair in row.get("dimension_mapping_ids") or [])
            or any(len(dim) != 5 or dim[2:] != [None, "EXPLICIT", "false"] or not dim[0] or not dim[1] for dim in dims)):
        return "Q4_MAPPING_REVIEW_REQUIRED"
    if any(row.get(field) for field in ("quality_blocking", "continuity_break", "recast_review_required", "structural_break",
                                          "recast_break", "basis_break", "compatibility_failure", "ambiguity", "ambiguous")) or row.get("quality_status") == "BLOCK":
        return "Q4_INPUT_QUALITY_OR_CONTINUITY_HELD"
    if (row.get("raw_concept_qname") not in REVENUE_QNAMES or row.get("raw_concept_is_standard") is not True
            or re.fullmatch(r"https?://fasb.org/us-gaap/\d{4}", str(row.get("raw_concept_namespace_uri"))) is None
            or row.get("raw_concept_period_type") != "duration" or "monetary" not in str(row.get("raw_concept_data_type", "")).lower()
            or row.get("context_period_kind") != "DURATION" or row.get("is_nil") is not False
            or row.get("reported_or_derived") != "REPORTED" or row.get("comparative_type") != "CURRENT_FOCUS"
            or row.get("unit_numerator_measures") != '["iso4217:USD"]' or row.get("unit_denominator_measures") != '[]'
            or finite_decimal(row.get("value_numeric")) is None or not row.get("source_fact_id") or not row.get("source_snapshot_id")
            or not row.get("filed_date") or row["filed_date"] > cutoff or row.get("source_is_amendment")):
        return "Q4_INPUT_NOT_QUALIFIED"
    try:
        days = (date.fromisoformat(row["context_end_date"]) - date.fromisoformat(row["context_start_date"])).days
        valid_days = 350 <= days <= 378 if row["period_class"] == "FY" else 255 <= days <= 290
        if not valid_days or row.get("context_duration_days") != days:
            return "Q4_INPUT_PERIOD_NOT_QUALIFIED"
    except (KeyError, TypeError, ValueError):
        return "Q4_INPUT_PERIOD_NOT_QUALIFIED"
    return None


def _lineage(row: dict[str, Any], cutoff: str) -> dict[str, Any]:
    return {**row, "source_type": "REPORTED", "selected_source_fact_id": row["source_fact_id"],
            "selection_view": "LATEST_REPORTED", "selection_as_of_date": cutoff}


def derive_revenue_q4(observations: Iterable[dict[str, Any]], *, cutoff: str) -> tuple[list[dict], list[dict]]:
    """Produce distinct Derived records and explicit exclusions, never estimates."""
    groups: dict[tuple, list] = defaultdict(list)
    for row in observations:
        if (row.get("period_class") in {"FY", "YTD_9M"} and row.get("raw_concept_qname") in REVENUE_QNAMES
                and row.get("comparative_type") == "CURRENT_FOCUS" and row.get("filed_date", "") <= cutoff
                and (row.get("raw_dimension_signature") or row.get("canonical_dimension_signature"))):
            groups[(*scope_key(row), row["fiscal_year"])].append(row)
    derived, exclusions = [], []
    for key, rows in groups.items():
        annual = [row for row in rows if row["period_class"] == "FY"]
        nine = [row for row in rows if row["period_class"] == "YTD_9M"]
        reason = next((_problem(row, cutoff) for row in rows if _problem(row, cutoff)), None)
        if reason is None:
            reason = "Q4_MISSING_ANNUAL_INPUT" if not annual else "Q4_MISSING_YTD9_INPUT" if not nine else "Q4_AMBIGUOUS_INPUTS" if len(annual) != 1 or len(nine) != 1 else None
        metric = None
        if reason is None:
            left, right = annual[0], nine[0]
            if left["raw_concept_qname"] != right["raw_concept_qname"]:
                reason = "Q4_INPUT_CONCEPT_MISMATCH"
            else:
                metric = _derive_additive_difference(_lineage(left, cutoff), _lineage(right, cutoff), quarter=4, rule_version=RULE_VERSION)
                if metric is None:
                    reason = "Q4_INPUT_SCOPE_OR_PERIOD_MISMATCH"
        identity = {"cik": key[0], "company_canonical_concept_id": key[1],
                    "canonical_dimension_signature": json.loads(key[2]), "fiscal_year": key[3]}
        if metric is None:
            exclusions.append({**identity, "reason": reason, "source_fact_ids": [row["source_fact_id"] for row in rows]})
        else:
            derived.append({**metric, **identity, "basis_assurance": ASSURANCE,
                            "basis_absent": all(row.get("basis_version") is None for row in (annual[0], nine[0])),
                            "policy_registry": "STANDARD_REVENUE_FULL_CONFIRMED_SCOPE",
                            "semantic_review_state": "GOVERNED_REVENUE_ADDITIVE_AMOUNT"})
    return derived, exclusions
