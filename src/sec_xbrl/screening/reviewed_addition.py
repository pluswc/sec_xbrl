"""Project the two independently reviewed 2026Q2 values into existing metrics."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.statement_structure import finite_decimal
from sec_xbrl.metrics.quarterly_screening import _observation_id, _support_rows

CONFIG_VERSION = "screening-prepare-reviewed-addition-v1"
_BUCKET = (2026, 2)
_GROSS_MARGIN = "quarter_gross_margin"
_RESEARCH = "quarter_research"
_APPROVED = {
    ("0001318605", _GROSS_MARGIN): ("PERCENT", "CALCULATED_FROM_REPORTED_INPUTS", "MULTIPLE_CANDIDATES"),
    ("0000075362", _RESEARCH): ("USD", "REPORTED", "PRIMARY_STATEMENT_EVIDENCE_MISSING"),
}
_FILING_FIELDS = ("accession", "filed_date", "report_date")
_PERIOD_FIELDS = ("period_start", "period_end", "end_convention")
_BLOCKING = (
    "quality_blocking", "mapping_review_required", "mapping_uncertainty", "ambiguity", "ambiguous",
    "compatibility_failure", "continuity_break", "recast_review_required", "basis_break",
    "structural_break", "recast_break",
)


def read_reviewed_audit(
    pin: dict[str, str], *, cutoff: str, quarter_sha: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    data = Path(pin["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("reviewed metric audit differs from approved pin")
    audit = json.loads(data)
    rows = audit.get("approved_for_this_offline_review")
    if (
        audit.get("status") != "OFFLINE_CANDIDATES_ONLY" or audit.get("calendar_bucket") != "2026Q2"
        or audit.get("financial_as_of") != cutoff or audit.get("quarterly_parent_sha256") != quarter_sha
        or not isinstance(rows, list) or len(rows) != len(_APPROVED)
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise ValueError("reviewed metric audit scope differs from approved quarter")
    by_key = {(row.get("cik"), row.get("metric_id")): row for row in rows}
    if set(by_key) != set(_APPROVED):
        raise ValueError("reviewed metric audit requires exactly the approved cells")
    for key, row in by_key.items():
        value = finite_decimal(row.get("value"))
        filing = row.get("filing")
        inputs = row.get("inputs")
        sources = [row.get("input")]
        if key[1] == _GROSS_MARGIN:
            if not isinstance(inputs, dict) or set(inputs) != {"gross_profit", "revenue"}:
                raise ValueError("reviewed metric audit lacks gross-margin inputs")
            sources = list(inputs.values())
        if (
            (row.get("unit"), row.get("value_kind"), row.get("previous_reason")) != _APPROVED[key]
            or not isinstance(row.get("value"), str) or value is None
            or (key[1] == _RESEARCH and value < 0)
            or not isinstance(filing, dict) or row.get("end_convention") != "EXCLUSIVE"
            or not all(isinstance(filing.get(field), str) and filing[field] for field in (
                *_FILING_FIELDS, "source_snapshot_id",
            ))
            or not all(re.fullmatch(r"[0-9a-f]{64}", str(filing.get(field))) for field in (
                "snapshot_manifest_sha256", "source_intake_sha256", "package_sha256",
            ))
            or not all(_valid_occurrence(source) for source in sources)
        ):
            raise ValueError("reviewed metric audit value or source shape differs")
    return by_key


def reviewed_rows(parent: Any, pin: dict[str, str]) -> tuple[list[dict], list[dict]]:
    cutoff = parent.manifest["financial_as_of"]
    quarter_sha = parent.manifest["parents"]["quarterly"]["manifest_sha256"]
    approved = read_reviewed_audit(pin, cutoff=cutoff, quarter_sha=quarter_sha)
    definitions = {row["metric_id"]: row for row in parent.quarter_definitions}
    periods = {row["cik"]: row for row in parent.quarter_period_inventory if _bucket(row) == _BUCKET}
    current = {
        (row["cik"], row["metric_id"]): row for row in parent.quarter_observations if _bucket(row) == _BUCKET
    }
    companies = {row["cik"]: row for row in parent.companies}
    replacements = {}
    for (cik, metric), item in approved.items():
        old = current.get((cik, metric))
        period = periods.get(cik)
        definition = definitions.get(metric)
        if (
            old is None or period is None or definition is None
            or old["availability_status"] != "UNAVAILABLE" or old.get("value") is not None
            or old.get("reason") != item["previous_reason"] or _blocked(old)
            or old["unit"] != item["unit"] or definition["unit"] != item["unit"]
            or old["definition_version"] != definition["definition_version"]
            or old["period_class"] != definition["observation_basis"] or old["period_class"] != "QTD_3M"
            or old["selection_as_of_date"] != cutoff or old["selection_view"] != "LATEST_REPORTED"
        ):
            raise ValueError("reviewed metric does not replace an eligible missing parent cell")
        _verify_period(item, period, cutoff)
        if metric == _GROSS_MARGIN:
            source, anchors = _gross_margin_sources(item, current, period)
            kind = "DERIVED_METRIC"
        else:
            source = old["source_lineage"]
            _verify_reported(source, item["input"], item, period)
            if any(old.get(field) != period.get(field) for field in (
                *_PERIOD_FIELDS, "fiscal_year", "fiscal_quarter", "filed_date", "report_date",
            )):
                raise ValueError("reviewed research differs from its held fiscal period")
            if (
                item["input"].get("section") != "DISCLOSURE"
                or item["input"].get("qname") != "us-gaap:ResearchAndDevelopmentExpense"
                or finite_decimal(item["input"]["value"]) != finite_decimal(item["value"])
                or source.get("primary_statement_evidence") != []
            ):
                raise ValueError("reviewed research source differs from approved reported note")
            anchors = {"held_research": old["observation_id"]}
            kind = "REPORTED"
        if kind not in definition["allowed_source_kinds"]:
            raise ValueError("reviewed metric source kind differs from existing definition")
        lineage = {
            **source, "approved_audit": pin.copy(), "reviewed_source_evidence": item,
            "original_observation_id": old["observation_id"], "parent_anchor_ids": anchors,
        }
        if kind == "DERIVED_METRIC":
            lineage.update(derivation_rule_version=definition["rule_version"], formula=item["formula"])
        else:
            for key in (
                "accession", "source_snapshot_id", "source_filing_id", "source_fact_id", "source_id",
                "context_id", "unit_id", "raw_concept_qname", "raw_concept_namespace_uri",
                "selected_source_ids", "duration_days",
            ):
                old = old | {key: source[key]}
        replacement = old | {
            "availability_status": "AVAILABLE", "source_kind": kind, "value": item["value"],
            "reason": None, "reasons": [], "source_lineage": lineage,
            **{field: period[field] for field in (*_PERIOD_FIELDS, "filed_date", "report_date", "fiscal_year", "fiscal_quarter")},
        }
        replacement["observation_id"] = _observation_id(replacement)
        replacements[cik, metric] = replacement
    rows = [
        replacements.get((row["cik"], row["metric_id"]), row) if _bucket(row) == _BUCKET else row
        for row in parent.quarter_observations
    ]
    support = {}
    for cik, metric in replacements:
        updated, = _support_rows([companies[cik]], rows, definitions=(definitions[metric],))
        support[cik, metric] = updated
    return [support.get((row["cik"], row["metric_id"]), row) for row in parent.quarter_support], rows


def _verify_period(item: dict, period: dict, cutoff: str) -> None:
    filing = item["filing"]
    if (
        period["bucket_status"] != "PERIOD_AVAILABLE" or item["ticker"] != period["ticker"]
        or any(item.get(field) != period.get(field) for field in _PERIOD_FIELDS)
        or any(filing[field] != period.get(field) for field in _FILING_FIELDS)
        or not filing["report_date"] <= filing["filed_date"] <= cutoff
        or (date.fromisoformat(item["period_end"]) - timedelta(days=1)).isoformat() != filing["report_date"]
        or filing["source_snapshot_id"] != (
            f"l1:{item['cik']}:{filing['accession'].replace('-', '')}:{filing['snapshot_manifest_sha256'][:16]}"
        )
    ):
        raise ValueError("reviewed metric actual fiscal period or filing differs")


def _verify_reported(source: dict, evidence: dict, item: dict, period: dict) -> None:
    filing = item["filing"]
    if (
        source.get("source_kind") != "REPORTED" or source.get("availability_status") != "AVAILABLE"
        or source.get("unit") != "USD" or source.get("dimensions") != [] or _blocked(source)
        or source.get("period_class") != "QTD_3M" or source.get("cik") != item["cik"]
        or any(source.get(field) != period.get(field) for field in _PERIOD_FIELDS)
        or any(source.get(field) != filing[field] for field in (*_FILING_FIELDS, "source_snapshot_id"))
        or any(source.get(field) != evidence.get(proof_field) for field, proof_field in (
            ("source_fact_id", "source_fact_id"), ("context_id", "context_id"), ("unit_id", "unit_id"),
            ("raw_concept_qname", "qname"), ("raw_concept_namespace_uri", "namespace"),
        ))
        or (value := finite_decimal(source.get("value"))) is None or value != finite_decimal(evidence.get("value"))
    ):
        raise ValueError("reviewed metric does not match the prepared reported source")


def _gross_margin_sources(item: dict, current: dict, period: dict) -> tuple[dict, dict]:
    cik = item["cik"]
    gross = current.get((cik, "quarter_gross_profit"))
    revenue = current.get((cik, "quarter_revenue"))
    inputs = item["inputs"]
    numerator, denominator = inputs["gross_profit"], inputs["revenue"]
    if (
        gross is None or revenue is None or revenue["availability_status"] != "UNAVAILABLE"
        or revenue.get("value") is not None or revenue.get("reason") != "MULTIPLE_CANDIDATES" or _blocked(revenue)
        or item.get("formula") != "gross profit * 100 / revenue"
        or numerator.get("qname") != "us-gaap:GrossProfit"
        or denominator.get("qname") != "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        or (value := finite_decimal(denominator.get("value"))) is None or value <= 0
        or numerator.get("section") != "IS" or denominator.get("section") != "IS"
        or any(not numerator.get(field) or numerator[field] != denominator.get(field) for field in (
            "role_id", "table_id", "table_sha256", "source_document_sha256", "context_id", "unit_id",
        ))
        or denominator.get("source_fact_id") not in item.get("same_value_revenue_fact_ids", [])
    ):
        raise ValueError("reviewed gross margin lacks its exact same-statement inputs")
    _verify_reported(gross, numerator, item, period)
    if any(gross.get(field) != period.get(field) for field in ("fiscal_year", "fiscal_quarter")):
        raise ValueError("reviewed gross profit differs from the prepared fiscal period")
    if not any(
        placement.get("role_id") == numerator["role_id"] and "IS" in placement.get("statement_types", [])
        for placement in gross["source_lineage"]["primary_statement_evidence"]
    ):
        raise ValueError("reviewed gross profit differs from the prepared statement role")
    return {}, {"gross_profit": gross["observation_id"], "held_revenue": revenue["observation_id"]}


def _valid_occurrence(source: Any) -> bool:
    return (
        isinstance(source, dict) and all(isinstance(source.get(field), str) and source[field] for field in (
            "source_fact_id", "context_id", "unit_id", "qname", "namespace",
            "table_id", "row_locator", "cell_locator", "inline_id",
        ))
        and all(re.fullmatch(r"[0-9a-f]{64}", str(source.get(field))) for field in (
            "table_sha256", "source_document_sha256",
        ))
    )


def _blocked(row: dict) -> bool:
    return row.get("quality_status") == "BLOCK" or any(row.get(field) for field in _BLOCKING)


def _bucket(row: dict) -> tuple[int, int]:
    return row["calendar_year"], row["calendar_quarter"]
