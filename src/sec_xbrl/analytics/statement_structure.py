"""Producer-side exact-scope signed CAL checks; no economic-share inference."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

CAL_CHECK_VERSION = "h1-signed-calculation-v1"
NETWORK_FIELDS = ("filing_id", "role_id", "role_uri", "arcrole", "link_qname", "arc_qname")
SCOPE_FIELDS = {"cik", "filing_id", "period", "unit", "dimensions", "view", "as_of", "basis"}


def stable_id(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def finite_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def validate_fact(fact: Mapping[str, Any]) -> None:
    """Validate the RAW_AS_FILED normalized contract, including explicit nulls.

    Canonical IDs are not invented: this arithmetic seam intentionally requires
    raw filing-scoped concept identity. Governed derived values are separate.
    """
    for key in ("fact_id", "filing_id", "raw_concept_id", "canonical_identity"):
        if not isinstance(fact.get(key), str) or not fact[key]:
            raise ValueError(f"CAL fact missing {key}")
    scope = fact.get("scope")
    if not isinstance(scope, Mapping) or not SCOPE_FIELDS <= scope.keys():
        raise ValueError("CAL fact requires complete normalized scope")
    if (scope["filing_id"] != fact["filing_id"]
            or scope["view"] != "RAW_AS_FILED"
            or scope["basis"] != "RAW:" + fact["filing_id"]
            or fact["canonical_identity"] != "RAW:" + fact["raw_concept_id"]):
        raise ValueError("CAL raw identity/view/basis mismatch")
    if not isinstance(scope["cik"], str) or len(scope["cik"]) != 10 or not scope["cik"].isdigit():
        raise ValueError("CAL requires normalized CIK")
    date.fromisoformat(scope["as_of"])
    period = scope["period"]
    if not isinstance(period, Mapping) or not {"type", "start", "end", "instant", "class"} <= period.keys():
        raise ValueError("CAL requires complete period")
    if period["class"] not in {"INSTANT", "QTD_3M", "YTD_6M", "YTD_9M", "FY", "TTM", "OTHER_DURATION"}:
        raise ValueError("CAL requires period class")
    if (period["type"] == "instant") != (period["class"] == "INSTANT"):
        raise ValueError("period type/class mismatch")
    if period["type"] == "instant":
        date.fromisoformat(period["instant"])
        if period["start"] is not None or period["end"] is not None:
            raise ValueError("instant cannot carry duration")
    elif period["type"] == "duration":
        if date.fromisoformat(period["start"]) >= date.fromisoformat(period["end"]) or period["instant"] is not None:
            raise ValueError("invalid duration")
    else:
        raise ValueError("unsupported CAL period")
    unit = scope["unit"]
    if not isinstance(unit, Mapping) or set(unit) != {"numerator", "denominator"}:
        raise ValueError("CAL requires full unit semantics")
    for key in unit:
        if not isinstance(unit[key], list) or any(not isinstance(v, str) or not v for v in unit[key]):
            raise ValueError("invalid unit measures")
    if not unit["numerator"]:
        raise ValueError("unit numerator is required")
    dimensions = scope["dimensions"]
    if not isinstance(dimensions, list):
        raise TypeError("complete dimensions are required")
    axes = set()
    for dim in dimensions:
        if not isinstance(dim, Mapping) or not {"axis", "member", "typed_value", "is_default"} <= dim.keys():
            raise ValueError("incomplete dimension assignment")
        if not isinstance(dim["axis"], str) or not dim["axis"] or dim["axis"] in axes:
            raise ValueError("duplicate/missing axis")
        if not isinstance(dim["is_default"], bool) or (dim["member"] is None) == (dim["typed_value"] is None):
            raise ValueError("invalid explicit/typed dimension")
        if any(v is not None and (not isinstance(v, str) or not v.strip()) for v in (dim["member"], dim["typed_value"])):
            raise ValueError("empty or invalid dimension value")
        axes.add(dim["axis"])


def materialize_signed_calculation_checks(
    *, facts: Iterable[Mapping[str, Any]], relationships: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep base sets separate, reject conflicting identities and duplicate arcs.

    Exact duplicate fact payloads represent repeated evidence, not two inputs.
    Distinct fact identities in the same scope are ambiguous, even if equal.
    Missing parents are emitted for each network, never silently validated.
    """
    by_id: dict[str, dict] = {}
    by_concept: dict[tuple, list[dict]] = defaultdict(list)
    for source in facts:
        fact = dict(source)
        validate_fact(fact)
        if fact["fact_id"] in by_id:
            if by_id[fact["fact_id"]] != fact:
                raise ValueError("conflicting payload for same fact_id")
            continue
        by_id[fact["fact_id"]] = fact
        by_concept[(fact["filing_id"], fact["raw_concept_id"])].append(fact)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for source in relationships:
        arc = dict(source)
        if arc.get("network_type") != "CAL":
            continue
        for field in (*NETWORK_FIELDS, "relationship_id", "from_raw_concept_id", "to_raw_concept_id"):
            if not isinstance(arc.get(field), str) or not arc[field]:
                raise ValueError("CAL relationship requires full filing/base-set identity")
        grouped[(*[arc[k] for k in NETWORK_FIELDS], arc["from_raw_concept_id"])].append(arc)
    results = []
    for key, arcs in sorted(grouped.items()):
        parents = by_concept.get((key[0], key[-1]), [])
        if not parents:
            results.append(_check(None, arcs, by_concept))
        for parent in sorted(parents, key=lambda r: r["fact_id"]):
            result = _check(parent, arcs, by_concept)
            peers = [p["fact_id"] for p in parents if p["scope"] == parent["scope"]]
            result["parent_candidate_fact_ids"] = peers
            if len(peers) > 1:
                result["status"] = "AMBIGUOUS_PARENT"
                result["issues"].append("AMBIGUOUS_PARENT")
                result["calculated_value"] = None
                result["difference_calculated_minus_reported"] = None
            results.append(result)
    return results


def _check(parent: dict | None, arcs: list[dict], by_concept: Mapping) -> dict:
    network = {key: arcs[0][key] for key in NETWORK_FIELDS}
    issues = []
    if parent is None:
        issues.append("MISSING_PARENT")
    parent_value = finite_decimal(parent.get("value_numeric")) if parent else None
    if parent and (parent.get("is_nil") or parent_value is None):
        issues.append("NONFINITE_OR_NIL_PARENT")
    if len({a["to_raw_concept_id"] for a in arcs}) != len(arcs) or len({a["relationship_id"] for a in arcs}) != len(arcs):
        issues.append("DUPLICATE_RELATIONSHIP_INPUT")
    inputs, used, total = [], set(), Decimal(0)
    for arc in sorted(arcs, key=lambda a: (finite_decimal(a.get("order")) or Decimal(0), a["relationship_id"])):
        candidates = by_concept.get((arc["filing_id"], arc["to_raw_concept_id"]), [])
        exact = [c for c in candidates if parent and c["scope"] == parent["scope"]]
        weight = finite_decimal(arc.get("weight"))
        item = {"relationship_id": arc["relationship_id"], "child_raw_concept_id": arc["to_raw_concept_id"],
                "weight": str(weight) if weight is not None else None,
                "candidate_fact_ids": [c["fact_id"] for c in candidates],
                "exact_fact_ids": [c["fact_id"] for c in exact], "child_fact_id": None,
                "value": None, "contribution": None, "status": "AVAILABLE"}
        if weight is None:
            item["status"] = "INVALID_WEIGHT"
        elif not exact:
            item["status"] = "INCOMPATIBLE_SCOPE" if candidates else "MISSING_INPUT"
        elif len(exact) != 1:
            item["status"] = "AMBIGUOUS_INPUT"
        else:
            child = exact[0]
            item.update(child_fact_id=child["fact_id"], value=child.get("value_numeric"))
            value = finite_decimal(child.get("value_numeric"))
            if child["fact_id"] in used:
                item["status"] = "DUPLICATE_FACT_INPUT"
            elif child.get("is_nil") or value is None:
                item["status"] = "NONFINITE_OR_NIL_INPUT"
            else:
                item["contribution"] = str(weight * value)
                total += weight * value
            used.add(child["fact_id"])
        if item["status"] != "AVAILABLE":
            issues.append(item["status"])
        inputs.append(item)
    return {"calculation_check_id": stable_id(network, parent["fact_id"] if parent else None, arcs[0]["from_raw_concept_id"]),
            "check_version": CAL_CHECK_VERSION, "network_identity": network,
            "parent_raw_concept_id": arcs[0]["from_raw_concept_id"],
            "parent_fact_id": parent["fact_id"] if parent else None,
            "parent_value": parent.get("value_numeric") if parent else None,
            "scope": parent["scope"] if parent else None, "inputs": inputs,
            "calculated_value": str(total) if not issues else None,
            "difference_calculated_minus_reported": str(total - parent_value) if not issues else None,
            "status": issues[0] if issues else "MATCH" if total == parent_value else "MISMATCH",
            "issues": sorted(set(issues)), "rounding_tolerance": None,
            "share_eligibility_status": "REVIEW_REQUIRED",
            "share_eligibility_reason": "CAL_EQUALITY_DOES_NOT_APPROVE_ECONOMIC_COMPOSITION"}
