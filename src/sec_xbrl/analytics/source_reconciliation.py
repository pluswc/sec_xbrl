"""Bounded reviewed source equations with explicitly reviewed dimension changes."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sec_xbrl.analytics.statement_structure import finite_decimal, stable_id, validate_fact

VERSION = "h1-reviewed-source-reconciliation-v1"


def materialize_source_reconciliations(*, facts: list[dict], tables: list[dict], reviews: list[dict], decision_cutoff: str) -> list[dict]:
    """No automatic cross-dimension equation discovery, balancing or residuals."""
    by_id = {f["fact_id"]: f for f in facts}
    table_index = {(t["source_document_sha256"], t["table_locator"], t["table_sha256"]): t for t in tables}
    cutoff = datetime.fromisoformat(decision_cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("reconciliation cutoff needs timezone")
    output = []
    for review in reviews:
        if any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("review_id", "reviewer")):
            raise ValueError("explicit source reconciliation review required")
        reviewed_at = datetime.fromisoformat(review["reviewed_at"])
        if reviewed_at.tzinfo is None or reviewed_at > cutoff:
            raise ValueError("invalid source reconciliation review timestamp")
        table = table_index.get((review["source_document_sha256"], review["table_locator"], review["table_sha256"]))
        if not table:
            raise ValueError("reconciliation exact source table not found")
        bindings = [review["parent"], *review["inputs"]]
        ids = [b["fact_id"] for b in bindings]
        if len(ids) != len(set(ids)) or not review["inputs"]:
            raise ValueError("reconciliation repeats an input or parent")
        parent = by_id.get(review["parent"]["fact_id"])
        if parent is None:
            raise ValueError("reconciliation parent missing")
        for binding in bindings:
            f = by_id.get(binding["fact_id"])
            if f is None:
                raise ValueError("reconciliation input missing")
            validate_fact(f)
            if f["scope"] != binding["scope"] or f.get("is_nil") or f.get("reported_or_derived") != "REPORTED" or finite_decimal(f["value_numeric"]) is None:
                raise ValueError("reconciliation exact reviewed scope/value unavailable")
            if {k: v for k, v in f["scope"].items() if k != "dimensions"} != {k: v for k, v in parent["scope"].items() if k != "dimensions"}:
                raise ValueError("reconciliation company/filing/period/unit/view/asof/basis mismatch")
            if not any(loc["table_id"] == table["table_id"] and loc["inline_id"] == binding["inline_id"] and loc["row_locator"] == binding["row_locator"] for loc in f["source_locations"]):
                raise ValueError("reconciliation inline/row binding mismatch")
        identities = [stable_id(by_id[b["fact_id"]]["raw_concept_id"], b["scope"]) for b in review["inputs"]]
        if len(identities) != len(set(identities)):
            raise ValueError("reconciliation alias input duplicates the same full raw scope")
        inputs, total = [], Decimal(0)
        for binding in review["inputs"]:
            f = by_id[binding["fact_id"]]
            weight = finite_decimal(binding["weight"])
            if weight is None:
                raise ValueError("reconciliation weight nonfinite")
            contribution = weight * Decimal(f["value_numeric"])
            total += contribution
            inputs.append({**binding, "value": f["value_numeric"], "contribution": str(contribution), "child_fact_id": f["fact_id"], "status": "AVAILABLE"})
        difference = total - Decimal(parent["value_numeric"])
        output.append({"calculation_check_id": stable_id(VERSION, review), "check_version": VERSION,
                       "relationship_type": "REVIEWED_SOURCE_RECONCILIATION", "source_table_id": table["table_id"],
                       "source_document_sha256": table["source_document_sha256"], "table_locator": table["table_locator"],
                       "parent_fact_id": parent["fact_id"], "parent_value": parent["value_numeric"], "scope": parent["scope"],
                       "inputs": inputs, "calculated_value": str(total), "difference_calculated_minus_reported": str(difference),
                       "status": "MATCH" if difference == 0 else "MISMATCH", "rounding_tolerance": None,
                       "review": review, "decision_cutoff": decision_cutoff, "share_eligibility_status": "NOT_AUTHORIZED",
                       "check_basis": "EXACT_REVIEWED_SOURCE_EQUATION_WITH_EXPLICIT_PER_INPUT_DIMENSIONS"})
    return output
