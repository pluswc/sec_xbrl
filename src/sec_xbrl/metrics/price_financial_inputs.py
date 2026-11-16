"""Narrow projection of existing selected analysis; no new financial preparation.

Candidates preserve source meaning. A reviewed declaration is required to bind a
candidate to a valuation role (notably total equity versus common equity, debt
versus total liabilities, and D&A included in operating income).
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import localcontext
from pathlib import Path

from sec_xbrl.analysis import open_analysis, stable
from sec_xbrl.metrics.market_inputs import finite, identity, pinned_json
from sec_xbrl.metrics.price_related import DECIMAL, ROLE_UNITS

QNAME_CANDIDATES = {
    "us-gaap:Assets", "us-gaap:Liabilities", "us-gaap:CommonStocksIncludingAdditionalPaidInCapital",
    "us-gaap:CommonStockValue", "us-gaap:AdditionalPaidInCapitalCommonStock",
    "us-gaap:RetainedEarningsAccumulatedDeficit", "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    "us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "us-gaap:MinorityInterest", "us-gaap:NoncontrollingInterestInConsolidatedEntity",
    "us-gaap:PreferredStockValue", "us-gaap:PreferredStockCarryingValue",
    "us-gaap:CashAndCashEquivalentsAtCarryingValue", "us-gaap:LongTermDebtCurrent",
    "us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt", "us-gaap:ShortTermBorrowings",
    "us-gaap:LongTermDebtAndCapitalLeaseObligations", "us-gaap:FinanceLeaseLiabilityCurrent",
    "us-gaap:FinanceLeaseLiabilityNoncurrent", "us-gaap:FinanceLeaseLiability",
    "us-gaap:OperatingIncomeLoss", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:Revenues",
    "us-gaap:SalesRevenueNet", "us-gaap:DepreciationDepletionAndAmortization",
    "us-gaap:DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    "us-gaap:Depreciation", "us-gaap:AmortizationOfIntangibleAssets",
    "us-gaap:NetCashProvidedByUsedInOperatingActivities", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    # Evidence candidates only: issued shares are never actual shares by default.
    "us-gaap:TreasuryStockValue", "us-gaap:TreasuryStockCommonValue",
    "us-gaap:PreferredStockSharesIssued", "us-gaap:CommonStockSharesIssued",
    "us-gaap:TreasuryStockShares", "us-gaap:TreasuryStockCommonShares",
    "us-gaap:CommercialPaper",
}


def project_additional_candidates(
    pin: dict, *, cik: str, ticker: str, cutoff: str,
    anchor_end: str | None = None, cell_ids: set[str] | None = None,
) -> list[dict]:
    """Project selected cells; optional restrictions apply before trace shard reads.

    Restrictions never change the source selection cutoff or the selected values.
    An explicit cell set must resolve completely within the named candidate scope.
    Omitting both restrictions preserves the original full-history projection.
    """
    manifest = pinned_json(pin)
    if manifest["companies"][ticker]["as_of"] != cutoff:
        raise ValueError("financial selection cutoff differs")
    client = open_analysis(Path(pin["path"]).parent)
    nodes = {n["node_id"]: n for n in client._records(ticker, "LATEST_REPORTED", "nodes")
             if n.get("kind") == "VALUE" and n.get("concept") in QNAME_CANDIDATES}
    cells = [c for c in client._records(ticker, "LATEST_REPORTED", "cells")
             if c["node_id"] in nodes and (anchor_end is None or c.get("end") == anchor_end)
             and (cell_ids is None or c["cell_id"] in cell_ids)]
    if cell_ids is not None and {c["cell_id"] for c in cells} != cell_ids:
        raise ValueError("requested cells do not match candidate anchor/scope")
    shards = defaultdict(set)
    for cell in cells:
        shards["trace_" + stable(cell["cell_id"])[0]].add(cell["cell_id"])
    traces = {t["cell_id"]: t for shard, ids in shards.items()
              for t in client._records(ticker, "LATEST_REPORTED", shard) if t["cell_id"] in ids}
    result = []
    for cell in cells:
        node, trace = nodes[cell["node_id"]], traces.get(cell["cell_id"], {})
        lineage = trace.get("value_lineage") or {}
        reason = None
        value = finite(cell.get("value"))
        if cell.get("status") not in {"REPORTED", "RECAST_REPORTED"} or lineage.get("source_type") not in {"REPORTED", "RECAST_REPORTED"}:
            reason = "DIRECT_REPORTED_INPUT_REQUIRED"
        elif value is None or cell.get("quality_blocking") or cell.get("quality_status") == "BLOCK":
            reason = "VALUE_OR_QUALITY_BLOCKED"
        elif not lineage.get("filed_date") or lineage["filed_date"] > cutoff:
            reason = "SOURCE_AFTER_CUTOFF"
        elif (lineage.get("selection_as_of_date") != cutoff
              or lineage.get("raw_concept_qname") != node["concept"]
              or not lineage.get("selected_source_fact_id") or lineage["selected_source_fact_id"] != cell.get("source_fact_id")
              or not lineage.get("source_filing_id") or not lineage.get("source_snapshot_id")
              or not lineage.get("raw_concept_namespace_uri")
              or not str(lineage.get("company_canonical_concept_id", "")).startswith(f"company:{cik}:")
              or finite(lineage.get("value_numeric")) != value):
            reason = "SOURCE_IDENTITY_NOT_CONFIRMED"
        record = {"cik": cik, "ticker": ticker, "qname": node["concept"],
                  "namespace": lineage.get("raw_concept_namespace_uri"),
                  "value": str(value) if reason is None else None, "source_value": cell.get("value"),
                  "status": "AVAILABLE_REPORTED" if reason is None else "UNAVAILABLE", "reason": reason,
                  "unit": cell.get("unit"), "unit_numerator_measures": lineage.get("unit_numerator_measures"),
                  "unit_denominator_measures": lineage.get("unit_denominator_measures"),
                  "period_class": cell.get("period_class"), "start": cell.get("start"), "end": cell.get("end"),
                  "end_convention": "EXCLUSIVE", "dimensions": node.get("dimensions", []),
                  "filed_date": lineage.get("filed_date"), "source": {"analysis_manifest": pin,
                  "cell_id": cell["cell_id"], "node_id": node["node_id"], "value_lineage": lineage}}
        record["observation_id"] = "price-financial-candidate-" + identity(record)
        result.append(record)
    pinned_json(pin)
    return result


def check_actual_share_sources(rows: list[dict], formula: str) -> None:
    """Reject known issued/WAVG misuse without excluding reviewed custom QNames."""
    if formula == "DIRECT" and rows and (rows[0].get("qname") in {
        "us-gaap:CommonStockSharesIssued", "us-gaap:CommonStockSharesAuthorized",
        "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
        "us-gaap:WeightedAverageNumberOfSharesOutstandingDiluted",
        "us-gaap:WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
    } or str(rows[0].get("input_id", "")).startswith("weighted_average_")):
        raise ValueError("issued/weighted-average shares are not actual outstanding common shares")
    if formula != "SUBTRACT":
        return
    if (len(rows) != 2 or rows[0].get("qname") != "us-gaap:CommonStockSharesIssued"
        or rows[1].get("qname") not in {"us-gaap:TreasuryStockShares", "us-gaap:TreasuryStockCommonShares"}):
        raise ValueError("actual-share subtraction requires exact issued then treasury quantities")

    def scope(row: dict) -> tuple:
        source = row.get("source", {})
        lineage = source.get("value_lineage", source)
        raw_dimensions = row.get("raw_dimensions", lineage.get("raw_dimension_signature"))
        filing = lineage.get("source_filing_id")
        if raw_dimensions is None or not filing or row.get("period_class") != "INSTANT":
            raise ValueError("actual-share subtraction requires full instant source scope")
        if row.get("unit_kind") == "shares":
            units = (["xbrli:shares"], [])
        else:
            def parts(field):
                value = row.get(field, lineage.get(field))
                return json.loads(value) if isinstance(value, str) else value
            units = (parts("unit_numerator_measures"), parts("unit_denominator_measures"))
        if units != (["xbrli:shares"], []):
            raise ValueError("actual-share subtraction requires share quantities")
        return (row.get("cik"), row.get("start"), row.get("end"), row.get("dimensions"), raw_dimensions, filing)

    if scope(rows[0]) != scope(rows[1]):
        raise ValueError("actual-share subtraction source filing/period/full dimensions differ")


def bind_financial_inputs(candidates: list[dict], declarations: list[dict]) -> list[dict]:
    """Bind reviewed exact sources, or explicit evidenced zero, to typed metric roles.

    Arithmetic is restricted to declared SUM/SUBTRACT/PER_SHARE and the existing
    standardized CFO-minus-PPE acquisitions formula. It never reconstructs EPS.
    Evidence pins are verified before use; no synthetic missing-as-zero path exists.
    """
    grouped = defaultdict(list)
    for row in candidates:
        grouped[row["observation_id"]].append(row)
    output = []
    for d in declarations:
        role = d["role"]
        if role not in ROLE_UNITS or not d.get("evidence_pins"):
            raise ValueError("reviewed role/evidence required")
        for pin in d["evidence_pins"]:
            pinned_json(pin)
        refs = d.get("candidate_ids", [])
        if len(refs) != len(set(refs)) or any(len(grouped[r]) != 1 for r in refs):
            raise ValueError("ambiguous/absent financial candidate")
        rows = [grouped[r][0] for r in refs]
        formula = d.get("formula", "DIRECT")
        if role == "diluted_eps_12m" and formula != "DIRECT":
            raise ValueError("EPS direct-only; reuse governed direct-QTD TTM separately")
        if formula not in {"DIRECT", "SUM", "SUBTRACT", "PER_SHARE", "EVIDENCED_ZERO"}:
            raise ValueError("unapproved binding formula")
        if (formula == "DIRECT" and len(rows) != 1 or formula in {"SUBTRACT", "PER_SHARE"} and len(rows) != 2
            or formula == "SUM" and not rows or formula == "EVIDENCED_ZERO" and rows):
            raise ValueError("binding formula arity differs")
        if role == "common_shares":
            check_actual_share_sources(rows, formula)
        if not d.get("known_on") or not d.get("period_end") or not d.get("scope_id"):
            raise ValueError("binding scope/date required")
        if any(r.get("status") not in {"AVAILABLE_REPORTED", "AVAILABLE_DERIVED_SEPARATE"} or finite(r.get("value")) is None
               or r["cik"] != d["cik"] or not r.get("filed_date") or r["filed_date"] > d["known_on"] for r in rows):
            raise ValueError("unavailable/future financial candidate")
        # A reviewed declaration cannot change units, currency or actual period.
        def measures(row, field):
            value = row.get(field)
            return json.loads(value) if isinstance(value, str) else value
        for row in rows:
            if row.get("dimensions") != d.get("dimensions", []):
                raise ValueError("binding cannot change full dimension scope")
            if row.get("period_class") != d.get("period_class"):
                raise ValueError("binding cannot change period class")
            if row.get("unit_kind") == "shares":
                numer, denom = ["xbrli:shares"], []
            elif row.get("unit_kind") == "USD/share":
                numer, denom = ["iso4217:USD"], ["xbrli:shares"]
            else:
                numer, denom = measures(row, "unit_numerator_measures"), measures(row, "unit_denominator_measures")
            expected_denom = ["xbrli:shares"] if ROLE_UNITS[role] == "currency/share" and formula == "DIRECT" else []
            expected_numer = ["xbrli:shares"] if ROLE_UNITS[role] == "shares" else ["iso4217:" + d["currency"]]
            if formula == "PER_SHARE" and row is rows[-1]:
                expected_numer = ["xbrli:shares"]
            if numer != expected_numer or denom != expected_denom:
                raise ValueError("binding cannot change source units")
            if row.get("end") != d["period_end"] or (d.get("period_start") is not None and row.get("start") != d["period_start"]):
                raise ValueError("binding cannot change source period")
        with localcontext(DECIMAL):
            values = [finite(r["value"]) for r in rows]
            if formula == "EVIDENCED_ZERO":
                value = 0
            elif formula == "DIRECT":
                value = values[0]
            elif formula == "SUM":
                value = sum(values)
            elif formula == "SUBTRACT":
                value = values[0] - values[1]
            else:
                if values[-1] <= 0:
                    raise ValueError("positive actual-share denominator required")
                value = values[0] / values[1]
        reported_zero = (role in {"preferred_equity", "nci"} and formula == "DIRECT" and value == 0
                         and rows[0].get("status") == "AVAILABLE_REPORTED")
        record = {**d, "value": str(value), "unit_kind": ROLE_UNITS[role], "status": "AVAILABLE",
                  "reason": None, "dimensions": d.get("dimensions", []), "end_convention": "EXCLUSIVE", "evidenced_zero": formula == "EVIDENCED_ZERO" or reported_zero,
                  "source_kind": "DIRECT_REPORTED" if formula == "DIRECT" else "GOVERNED_ROLE_BINDING",
                  "source_refs": [{"observation_id": r["observation_id"], "source": r.get("source"),
                                   "qname": r.get("qname"), "value": r["value"],
                                   "period_start": r.get("start"), "period_end": r.get("end")} for r in rows]
                                 + [{"evidence_pin": pin} for pin in d["evidence_pins"]]}
        if reported_zero:
            record["zero_evidence_kind"] = "REPORTED_ZERO"
        record["observation_id"] = "price-financial-input-" + identity(record)
        output.append(record)
    return output
