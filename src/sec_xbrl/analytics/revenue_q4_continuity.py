"""Separately reviewed revenue Q4 continuity; never modifies original mappings.

A review endpoint preserves the original T1 scope, including its review flag.
The enrichment publisher is the only caller allowed to consume ROOT grants.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

REVIEW_VERSION = "revenue-q4-continuity-review-v1"
RULE_VERSION = "reviewed-revenue-scope-fy-ytd9-q4-v1"
RATIO_RULE = "reviewed-revenue-q4-paired-input-ratios-v1"
SCOPE_FIELDS = (
    "cik", "source_fact_id", "source_snapshot_id", "source_filing_id", "accession",
    "raw_concept_id", "raw_concept_qname", "raw_concept_namespace_uri",
    "raw_dimension_signature", "company_canonical_concept_id", "canonical_dimension_signature",
    "concept_mapping_id", "concept_mapping_version", "dimension_mapping_ids", "mapping_review_required",
    "basis_version", "structural_version", "recast_version", "unit_numerator_measures", "unit_denominator_measures",
    "context_id", "period_class", "comparative_type", "fiscal_year", "fiscal_quarter",
    "context_start_date", "context_end_date", "filed_date",
)


def review_endpoint(row: dict[str, Any]) -> dict[str, Any]:
    """Create an exact reference for human review; it grants no financial permission."""
    return {"observation_id": row["period_observation_id"], "observation_sha256": hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
            "scope": {key: deepcopy(row.get(key)) for key in SCOPE_FIELDS}}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _endpoint(reference: dict, by_id: dict[str, dict]) -> dict:
    row = by_id.get(reference.get("observation_id"))
    if row is None or reference != review_endpoint(row):
        raise ValueError("review endpoint differs from the exact original T1 observation/scope")
    return row


def _input_problem(row: dict, cutoff: str) -> str | None:
    """Original mapping flags remain intact; ROOT grants cover only their exact scope."""
    import re
    from datetime import date
    from decimal import Decimal, InvalidOperation

    from sec_xbrl.analytics.revenue_quarters import REVENUE_QNAMES

    dims, raw = row.get("canonical_dimension_signature"), row.get("raw_dimension_signature")
    if (not row.get("company_canonical_concept_id") or not row.get("concept_mapping_id")
        or not isinstance(dims, list) or not isinstance(raw, list) or len(dims) != len(raw)
        or len(row.get("dimension_mapping_ids") or []) != len(dims)
        or any(len(dim) != 5 or dim[2:] != [None, "EXPLICIT", "false"] or not dim[0] or not dim[1] for dim in [*dims, *raw])
        or any(not isinstance(pair, list) or len(pair) != 2 or not all(pair) for pair in row.get("dimension_mapping_ids") or [])):
        return "Q4_REVIEW_INPUT_SCOPE_INCOMPLETE"
    if any(row.get(key) for key in ("quality_blocking", "continuity_break", "recast_review_required", "structural_break",
            "recast_break", "basis_break", "compatibility_failure", "ambiguity", "ambiguous")) or row.get("quality_status") == "BLOCK":
        return "Q4_INPUT_QUALITY_OR_CONTINUITY_HELD"
    if (row.get("raw_concept_qname") not in REVENUE_QNAMES or row.get("raw_concept_is_standard") is not True
        or re.fullmatch(r"https?://fasb.org/us-gaap/\d{4}", str(row.get("raw_concept_namespace_uri"))) is None
        or row.get("raw_concept_period_type") != "duration" or "monetary" not in str(row.get("raw_concept_data_type", "")).lower()
        or row.get("context_period_kind") != "DURATION" or row.get("is_nil") is not False
        or row.get("reported_or_derived") != "REPORTED" or row.get("source_is_amendment")
        or row.get("unit_numerator_measures") != '["iso4217:USD"]' or row.get("unit_denominator_measures") != '[]'
        or not row.get("filed_date") or row["filed_date"] > cutoff
        or not all(row.get(key) for key in ("source_fact_id", "source_filing_id", "source_snapshot_id", "accession"))):
        return "Q4_INPUT_NOT_QUALIFIED"
    try:
        if not Decimal(str(row["value_numeric"])).is_finite():
            return "Q4_INPUT_NOT_QUALIFIED"
        days = (date.fromisoformat(row["context_end_date"]) - date.fromisoformat(row["context_start_date"])).days
        bounds = {"FY": (350, 378), "YTD_9M": (255, 290), "QTD_3M": (75, 105)}.get(row["period_class"], (1, 0))
        if not bounds[0] <= days <= bounds[1] or row.get("context_duration_days") != days:
            return "Q4_INPUT_PERIOD_NOT_QUALIFIED"
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return "Q4_INPUT_NOT_QUALIFIED"
    return None


def exact_difference(first: str, second: str) -> str:
    """Decimal subtraction with enough coefficient precision for every input digit."""
    from decimal import Decimal, localcontext

    left, right = Decimal(first), Decimal(second)
    if not left.is_finite() or not right.is_finite():
        raise ValueError("finite difference inputs required")
    with localcontext() as context:
        context.prec = max(1, max(left.adjusted(), right.adjusted()) - min(left.as_tuple().exponent, right.as_tuple().exponent) + 3)
        value = left - right
    return "0" if not value else format(value, "f")


def derive_reviewed_q4(observations: list[dict], links: list[dict], *, cutoff: str) -> tuple[list[dict], list[dict]]:
    """Consume exact independently approved links, leaving every original row unchanged."""
    from datetime import date

    from sec_xbrl.analytics.revenue_quarters import ASSURANCE

    by_id = {}
    for row in observations:
        identity = row["period_observation_id"]
        if identity in by_id:
            raise ValueError("original observation identity is duplicated")
        by_id[identity] = row
    seen, pairs, metrics, exclusions = set(), set(), [], []
    for link in links:
        identity = link.get("id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("review amount link ID is missing or duplicated")
        seen.add(identity)
        if link.get("relation") not in {"SAME", "RENAMED"} or not link.get("evidence"):
            raise ValueError("explicit SAME/RENAMED disclosure evidence required")
        annual, nine = _endpoint(link["annual"], by_id), _endpoint(link["ytd9"], by_id)
        pair = (annual["period_observation_id"], nine["period_observation_id"])
        if pair in pairs:
            raise ValueError("one reviewed input pair is declared more than once")
        pairs.add(pair)
        period = link["period"]
        reason = next((value for row in (annual, nine) if (value := _input_problem(row, cutoff))), None)
        if reason is None and ((annual["period_class"], nine["period_class"]) != ("FY", "YTD_9M")
            or annual["cik"] != link.get("cik") or nine["cik"] != annual["cik"]
            or annual["raw_concept_qname"] != nine["raw_concept_qname"]
            or len(annual["raw_dimension_signature"]) != len(nine["raw_dimension_signature"])
            or any(annual.get(key) != nine.get(key) for key in ("basis_version", "structural_version", "recast_version"))):
            reason = "Q4_REVIEW_SCOPE_OR_BASIS_MISMATCH"
        try:
            if reason is None:
                focus = annual.get("fiscal_year")
                kind = annual.get("comparative_type")
                if (kind != nine.get("comparative_type") or focus != nine.get("fiscal_year")
                    or kind not in {"CURRENT_FOCUS", "PRIOR_YEAR_COMPARABLE"}
                    or focus != period["fiscal_year"] + int(kind == "PRIOR_YEAR_COMPARABLE")
                    or annual.get("fiscal_quarter") != 4 or nine.get("fiscal_quarter") != 3
                    or period["fiscal_quarter"] != 4
                    or annual["context_start_date"] != nine["context_start_date"]
                    or period["period_start"] != nine["context_end_date"] or period["period_end"] != annual["context_end_date"]
                    or not 75 <= (date.fromisoformat(period["period_end"]) - date.fromisoformat(period["period_start"])).days <= 105):
                    reason = "Q4_REVIEW_ACTUAL_PERIOD_MISMATCH"
        except (KeyError, TypeError, ValueError):
            reason = "Q4_REVIEW_ACTUAL_PERIOD_MISMATCH"
        if reason:
            exclusions.append({"amount_id": identity, "reason": reason, "source_fact_ids": [annual["source_fact_id"], nine["source_fact_id"]]})
            continue
        body = {"amount_id": identity, "cik": annual["cik"], "fiscal_year": period["fiscal_year"], "fiscal_quarter": 4,
                "context_start_date": period["period_start"], "context_end_date": period["period_end"], "period_class": "QTD_3M",
                "value_numeric": exact_difference(annual["value_numeric"], nine["value_numeric"]),
                "formula": "FY - YTD_9M", "derivation_rule_version": RULE_VERSION,
                "source_type": "DERIVED_QUARTER", "reported_or_derived": "DERIVED", "basis_assurance": ASSURANCE,
                "source_fact_ids": [annual["source_fact_id"], nine["source_fact_id"]],
                "source_inputs": [deepcopy(annual), deepcopy(nine)], "review_link": deepcopy(link),
                "comparison_only": annual["comparative_type"] == "PRIOR_YEAR_COMPARABLE"}
        metrics.append({**body, "derived_metric_id": "reviewed-revenue-q4:" + _digest(body)})
    return metrics, exclusions
