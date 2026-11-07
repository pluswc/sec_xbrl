"""Offline exact-source proof for a candidate total-liabilities observation."""
from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from sec_xbrl.analytics.calculation11 import ARCROLE as CALCULATION_11
from sec_xbrl.analytics.statement_structure import NETWORK_FIELDS, finite_decimal
from sec_xbrl.metrics.quarterly_screening import _exact_subtract, _exact_sum
from sec_xbrl.relationships.layer1 import _CALCULATION_ARCROLE
from sec_xbrl.screening.common import require_cik

RULE_VERSION = "exact-primary-balance-sheet-liabilities-candidate-v1"
_ASSETS = "us-gaap:Assets"
_BALANCE_TOTAL = "us-gaap:LiabilitiesAndStockholdersEquity"
_LIABILITIES = "us-gaap:Liabilities"
_EQUITY = "us-gaap:StockholdersEquity"
_TOTAL_EQUITY = "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
_NCI = {"us-gaap:MinorityInterest", "us-gaap:NoncontrollingInterestInConsolidatedEntity"}
_COMMITMENTS = "us-gaap:CommitmentsAndContingencies"
_CURRENT = "us-gaap:LiabilitiesCurrent"
_NONCURRENT = "us-gaap:LiabilitiesNoncurrent"
_DEBT = "us-gaap:LongTermDebtNoncurrent"
_DEBT_AND_LEASE = "us-gaap:LongTermDebtAndCapitalLeaseObligations"
_TYPED_STANDARD_COMPONENTS = {
    "us-gaap:DeferredIncomeTaxLiabilitiesNet": {"deferred tax liabilities", "deferred income tax liabilities"},
    _DEBT_AND_LEASE: {"long-term debt"},
}
_LEASE_COMPONENTS = {
    "us-gaap:OperatingLeaseLiabilityNoncurrent", "us-gaap:FinanceLeaseLiabilityNoncurrent",
}
_LIABILITY_COMPONENTS = {
    _CURRENT, _NONCURRENT, _DEBT, "us-gaap:OtherLiabilitiesNoncurrent",
    *_LEASE_COMPONENTS,
}
_CUSTOM_LEASE = "LONG_TERM_LEASE_LIABILITIES"
_USD = {"numerator": ["iso4217:USD"], "denominator": []}
Occurrence = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]


class _Unproven(ValueError):
    """Expected, fail-closed outcome for insufficient statement evidence."""


def derive_total_liabilities_candidate(
    prepared: dict[str, Any], *, cik: str, instant: str,
) -> dict[str, Any]:
    """Read one prepared filing. The requested instant uses Raw's date convention."""
    cik = require_cik(cik)
    instant = date.fromisoformat(instant).isoformat()
    result = {"rule_version": RULE_VERSION, "cik": cik, "instant": instant, "unit": "USD"}
    try:
        return result | _evaluate(prepared, cik, instant)
    except _Unproven as error:
        return result | {"status": "UNAVAILABLE", "reason": str(error), "value": None, "provenance": None}


def _evaluate(prepared: dict[str, Any], cik: str, instant: str) -> dict[str, Any]:
    filing = _one(prepared["filings"], "FILING_SCOPE_NOT_UNIQUE")
    if filing["cik"] != cik:
        raise _Unproven("FILING_SCOPE_MISMATCH")
    table = _one([
        table for table in prepared["source_tables"]
        if table["section"] == "BS" and table["filing_id"] == filing["filing_id"] and table.get("role_id")
    ], "PRIMARY_BALANCE_SHEET_NOT_UNIQUE")
    facts = [
        fact for fact in prepared["statement_facts"]
        if _in_scope(fact, filing["filing_id"], cik, instant)
    ]
    rows = {row["row_id"]: row for row in prepared["source_statement_rows"] if row["table_id"] == table["table_id"]}
    paths = {path["row_id"]: path for path in prepared["statement_rows"]}
    occurrences = [
        (fact, location, rows[location["row_id"]])
        for fact in facts for location in fact["source_locations"]
        if location["table_id"] == table["table_id"] and location["row_id"] in rows
    ]
    by_qname: dict[str, list[Occurrence]] = defaultdict(list)
    by_concept: dict[str, list[Occurrence]] = defaultdict(list)
    for occurrence in occurrences:
        fact = occurrence[0]
        by_qname[fact["concept"]["qname"]].append(occurrence)
        by_concept[fact["raw_concept_id"]].append(occurrence)
    provenance = {
        "accession": filing["accession"], "filing_id": filing["filing_id"],
        "filed_date": filing["filed_date"], "package_sha256": filing["package_hash"],
        "statement_role_id": table["role_id"], "source_table_id": table["table_id"],
        "source_document": table["source_document"], "source_document_sha256": table["source_document_sha256"],
        "source_table_sha256": table["table_sha256"],
    }
    if any(fact["concept"]["qname"] == _LIABILITIES for fact in facts):
        direct = _one(by_qname[_LIABILITIES], "REPORTED_LIABILITIES_NOT_UNIQUE")
        value = _numeric(direct, facts, table, paths)
        if not _standard(direct[0]) or value < 0:
            raise _Unproven("REPORTED_LIABILITIES_INVALID")
        return {"status": "REPORTED", "reason": None, "value": str(value),
                "provenance": provenance | {"reported": _source(direct)}}

    assets = _one(by_qname[_ASSETS], "ASSETS_NOT_UNIQUE")
    balance = _one(by_qname[_BALANCE_TOTAL], "BALANCE_TOTAL_NOT_UNIQUE")
    if not _standard(assets[0]) or not _standard(balance[0]) or assets[0]["scope"] != balance[0]["scope"]:
        raise _Unproven("BALANCE_TOTAL_SCOPE_MISMATCH")
    if any(len(by_qname[qname]) > 1 for qname in {_EQUITY, _TOTAL_EQUITY, *_NCI}):
        raise _Unproven("TOTAL_EQUITY_NOT_UNIQUE")
    role_uri = _typed_role(balance, table, paths)
    asset_value = _numeric(assets, facts, table, paths, role_uri=role_uri)
    balance_value = _numeric(balance, facts, table, paths)
    if asset_value < 0 or asset_value != balance_value:
        raise _Unproven("BALANCE_TOTAL_NOT_RECONCILED")
    if (any(_temporary_equity(fact["concept"]["qname"], "") for fact in facts)
        or any(_temporary_equity("", row["label"]) for _, _, row in occurrences)):
        raise _Unproven("TEMPORARY_OR_REDEEMABLE_EQUITY_PRESENT")

    arcs = _calculation_arcs(prepared, filing, table, role_uri, balance[0]["raw_concept_id"])
    components = {}
    ignored = []
    for arc in arcs:
        child = _one(by_concept[arc["to_raw_concept_id"]], "CALCULATION_CHILD_NOT_UNIQUE")
        fact, _, row = child
        qname = fact["concept"]["qname"]
        if len(by_qname[qname]) != 1:
            raise _Unproven("CALCULATION_CHILD_NOT_UNIQUE")
        if qname == _COMMITMENTS and _is_note_reference(child, balance, table, paths, facts):
            ignored.append({"source": _source(child), "relationship": deepcopy(arc)})
            continue
        if fact["scope"] != balance[0]["scope"]:
            raise _Unproven("CALCULATION_CHILD_SCOPE_MISMATCH")
        label = _normal_label(row["label"])
        if _standard(fact) and (
            qname in {*_LIABILITY_COMPONENTS, _EQUITY, _TOTAL_EQUITY}
            or label in _TYPED_STANDARD_COMPONENTS.get(qname, ())
        ):
            kind = qname
        elif (fact["concept"].get("is_custom") is True and fact["concept"].get("is_standard") is False
              and label == "long-term lease liabilities"):
            kind = _CUSTOM_LEASE
        else:
            raise _Unproven("UNKNOWN_CALCULATION_CHILD")
        value = _numeric(child, facts, table, paths, role_uri=role_uri)
        if kind in components or (kind not in {_EQUITY, _TOTAL_EQUITY} and value < 0):
            raise _Unproven("INVALID_LIABILITY_COMPONENT")
        components[kind] = (value, {"source": _source(child), "relationship": deepcopy(arc)})

    equity_types = {_EQUITY, _TOTAL_EQUITY} & components.keys()
    equity_type = _one(list(equity_types), "TOTAL_EQUITY_NOT_UNIQUE")
    if equity_type == _EQUITY and (
        any(fact["concept"]["qname"] in _NCI for fact in facts)
        or any(re.search(r"non[ -]?controlling|minority interest", _normal_label(row["label"]))
               for _, _, row in occurrences)
    ):
        raise _Unproven("TOTAL_EQUITY_INCLUDING_NCI_REQUIRED")
    if equity_type == _EQUITY and by_qname[_TOTAL_EQUITY]:
        raise _Unproven("TOTAL_EQUITY_NOT_UNIQUE")
    equity, equity_proof = components.pop(equity_type)
    liability_types = set(components)
    if (
        _CURRENT not in liability_types
        or len(liability_types) < 2
        or (_NONCURRENT in liability_types and liability_types != {_CURRENT, _NONCURRENT})
        or (_CUSTOM_LEASE in liability_types and bool(_LEASE_COMPONENTS & liability_types))
        or (_DEBT_AND_LEASE in liability_types and bool(({_DEBT, _CUSTOM_LEASE} | _LEASE_COMPONENTS) & liability_types))
    ):
        raise _Unproven("LIABILITY_COMPONENT_SCOPE_NOT_PROVEN")
    residual = _exact_subtract(asset_value, equity)
    subtotal = _exact_sum(value for value, _ in components.values())
    if residual < 0 or residual != subtotal or _exact_sum((subtotal, equity)) != balance_value:
        raise _Unproven("LIABILITY_COMPONENTS_DO_NOT_RECONCILE")
    return {
        "status": "DERIVED_CANDIDATE", "reason": None, "value": str(residual),
        "provenance": provenance | {
            "formula": "Assets - TotalEquity",
            "assets": _source(assets), "balance_total": _source(balance), "equity": equity_proof,
            "liability_components": [
                {"classification": kind, **proof} for kind, (_, proof) in components.items()
            ],
            "nonnumeric_note_references": ignored, "liability_component_sum": str(subtotal),
        },
    }


def _one(items: list, reason: str) -> Any:
    if len(items) != 1:
        raise _Unproven(reason)
    return items[0]


def _in_scope(fact: dict, filing_id: str, cik: str, instant: str) -> bool:
    scope = fact["scope"]
    entity = str(fact["context"].get("entity_identifier") or "")
    return (
        fact["filing_id"] == scope["filing_id"] == filing_id and scope["cik"] == cik
        and scope["view"] == "RAW_AS_FILED" and scope["basis"] == f"RAW:{filing_id}"
        and scope["period"] == {"type": "instant", "class": "INSTANT", "start": None, "end": None, "instant": instant}
        and scope["dimensions"] == [] and fact["reported_or_derived"] == "REPORTED"
        and re.fullmatch(r"https?://www\.sec\.gov/CIK:[0-9]{1,10}", entity) is not None
        and entity.rsplit(":", 1)[-1].zfill(10) == cik
    )


def _standard(fact: dict) -> bool:
    concept = fact["concept"]
    return (
        concept["is_standard"] is True
        and re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", str(concept["namespace_uri"])) is not None
    )


def _typed_role(occurrence: Occurrence, table: dict, paths: dict) -> str:
    fact, location, row = occurrence
    if (
        location["binding_status"] != "EXACT_RAW_ID" or row["coverage_status"] != "INCLUDED"
        or location["source_document_sha256"] != table["source_document_sha256"]
        or row["source_document_sha256"] != table["source_document_sha256"]
        or row["filing_id"] != fact["filing_id"]
        or not location.get("row_locator") or not location.get("cell_locator")
    ):
        raise _Unproven("PRIMARY_ROW_BINDING_NOT_PROVEN")
    roles = {
        path["network_identity"]["role_uri"]
        for path_id in row["pre_path_ids"] if (path := paths.get(path_id))
        and path["section"] == "BS" and path["raw_concept_id"] == fact["raw_concept_id"]
        and path["network_identity"]["role_id"] == table["role_id"] and not path["cycle"]
    }
    return _one(list(roles), "PRIMARY_ROW_ROLE_NOT_PROVEN")


def _numeric(
    occurrence: Occurrence, facts: list[dict], table: dict, paths: dict, *, role_uri: str | None = None,
) -> Decimal:
    fact, _, _ = occurrence
    typed_role = _typed_role(occurrence, table, paths)
    if role_uri is not None and typed_role != role_uri:
        raise _Unproven("PRIMARY_ROW_ROLE_NOT_PROVEN")
    value = finite_decimal(fact["value_numeric"])
    if (value is None or fact["is_nil"] or fact["scope"]["unit"] != _USD
        or fact["concept"]["period_type"] != "instant"
        or "monetary" not in str(fact["concept"]["data_type"]).casefold()):
        raise _Unproven("INVALID_PRIMARY_MONETARY_FACT")
    if any(peer["raw_concept_id"] == fact["raw_concept_id"] and peer["scope"] == fact["scope"]
           and (peer["is_nil"] or finite_decimal(peer["value_numeric"]) != value)
           for peer in facts):
        raise _Unproven("CONFLICTING_SAME_SCOPE_RAW_FACT")
    return value


def _calculation_arcs(prepared: dict, filing: dict, table: dict, role_uri: str, parent: str) -> list[dict]:
    arcs = [
        arc for arc in prepared["statement_relationships"]
        if arc["network_type"] == "CAL" and arc["filing_id"] == filing["filing_id"]
        and arc["role_id"] == table["role_id"] and arc["from_raw_concept_id"] == parent
    ]
    if (
        not arcs or len({tuple(arc[field] for field in NETWORK_FIELDS) for arc in arcs}) != 1
        or len({arc["to_raw_concept_id"] for arc in arcs}) != len(arcs)
        or len({arc["relationship_id"] for arc in arcs}) != len(arcs)
        or any(arc["role_uri"] != role_uri or finite_decimal(arc["weight"]) != 1
               or arc.get("target_role_uri") or not _attested_calculation_arc(arc, filing) for arc in arcs)
    ):
        raise _Unproven("CALCULATION_NETWORK_NOT_PROVEN")
    return sorted(arcs, key=lambda arc: arc["relationship_id"])


def _attested_calculation_arc(arc: dict, filing: dict) -> bool:
    if arc["arcrole"] == _CALCULATION_ARCROLE:
        return arc.get("evidence_origin") == "IMMUTABLE_RAW_SNAPSHOT"
    return (
        arc["arcrole"] == CALCULATION_11
        and arc.get("evidence_origin") == "ADDITIVE_ARELLE_CALCULATION_1_1"
        and arc.get("source_package_sha256") == filing["package_hash"]
        and arc.get("policy_version") == "h1-supplemental-cal11-v1"
        and isinstance(arc.get("source_document"), str)
        and arc.get("source_document_sha256") == (arc.get("source_members_sha256") or {}).get(
            PurePosixPath(arc["source_document"]).name
        )
        and re.fullmatch(r"[0-9a-f]{64}", str(arc.get("source_document_sha256"))) is not None
    )


def _is_note_reference(
    occurrence: Occurrence, balance: Occurrence, table: dict, paths: dict, facts: list[dict],
) -> bool:
    fact, _, row = occurrence
    if (
        not _standard(fact) or not fact["is_nil"] or fact["value_numeric"] is not None
        or fact["value_text"] is not None or fact["scope"] != balance[0]["scope"]
        or not re.fullmatch(r"(?:commitments and )?contingencies \((?:see )?note [0-9]+[a-z]?\)",
                            _normal_label(row["label"]))
        or any(peer["raw_concept_id"] == fact["raw_concept_id"] and peer["scope"] == fact["scope"]
               and (not peer["is_nil"] or peer["value_numeric"] is not None or peer["value_text"] is not None)
               for peer in facts)
    ):
        return False
    return _typed_role(occurrence, table, paths) == _typed_role(balance, table, paths)


def _normal_label(label: str) -> str:
    return " ".join(label.casefold().split())


def _temporary_equity(qname: str, label: str) -> bool:
    return bool(re.search(r"redeemable|mezzanine|temporary\s*equity", qname.casefold() + " " + _normal_label(label)))


def _source(occurrence: Occurrence) -> dict[str, Any]:
    fact, location, row = occurrence
    return {
        "source_fact_id": fact["fact_id"], "raw_concept_id": fact["raw_concept_id"],
        "raw_concept_qname": fact["concept"]["qname"], "raw_concept_namespace_uri": fact["concept"]["namespace_uri"],
        "context_id": fact["context_id"], "unit_id": fact["unit_id"],
        "value": fact["value_numeric"], "is_nil": fact["is_nil"], "row_label": row["label"],
        "row_id": row["row_id"], "row_locator": location["row_locator"],
        "cell_locator": location["cell_locator"], "inline_id": location["inline_id"],
    }
