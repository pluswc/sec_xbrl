"""Project one approved liabilities audit into an additive screening metric."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.statement_structure import finite_decimal
from sec_xbrl.metrics.liability_statement_evidence import RULE_VERSION
from sec_xbrl.metrics.quarterly_screening import _support_rows
from sec_xbrl.screening.common import digest_value, require_cik

CONFIG_VERSION = "screening-prepare-liability-addition-v1"
METRIC_ID = "quarter_calculated_total_liabilities"
DEFINITION_VERSION = "quarter-calculated-total-liabilities-v1"
_DEFINITION = {
    "metric_id": METRIC_ID, "label_ko": "분기말 총부채 (계산값)",
    "definition_version": DEFINITION_VERSION, "rule_version": RULE_VERSION,
    "category": "FINANCIAL_STABILITY", "observation_basis": "INSTANT",
    "unit_kind": "MONEY", "unit": "USD", "canonical_value_scale": "1",
    "allowed_source_kinds": ["DERIVED_METRIC"], "status": "ACTIVE",
    "formula": "Assets - TotalEquity",
}
_APPROVED_BUCKET = (2026, 2)
_APPROVED_COUNT = 6
_UNAVAILABLE = "CALCULATED_LIABILITY_NOT_APPROVED"


def read_approved_audit(
    audit_pin: dict[str, str], *, cutoff: str, company_count: int,
) -> dict[str, dict[str, Any]]:
    """Bind the six persisted observations without reopening the parent."""
    data = Path(audit_pin["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != audit_pin["sha256"]:
        raise ValueError("liability audit differs from approved pin")
    audit = json.loads(data)
    candidates = audit.get("missing_liability_audits")
    if (
        audit.get("calendar_bucket") != "2026Q2" or audit.get("financial_as_of") != cutoff
        or audit.get("company_count") != company_count or not isinstance(candidates, list)
        or not all(isinstance(row, dict) for row in candidates)
    ):
        raise ValueError("liability audit scope differs from the parent")
    approved = [row for row in candidates if row.get("status") == "DERIVED_CANDIDATE"]
    by_cik = {require_cik(row.get("cik")): row for row in approved}
    if len(approved) != _APPROVED_COUNT or len(by_cik) != len(approved):
        raise ValueError("liability audit requires six distinct approved quarterly candidates")
    if any(
        row.get("reason") is not None or row.get("rule_version") != RULE_VERSION
        or row.get("unit") != "USD" or not isinstance(row.get("value"), str)
        or (value := finite_decimal(row["value"])) is None or value < 0
        or not isinstance(row.get("provenance"), dict)
        for row in approved
    ):
        raise ValueError("liability audit candidate shape differs")
    return by_cik


def liability_rows(
    parent: Any, audit_pin: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return a definition and rows for this metric only. No source calculations."""
    cutoff = parent.manifest["financial_as_of"]
    by_cik = read_approved_audit(audit_pin, cutoff=cutoff, company_count=len(parent.companies))
    anchors = {
        (row["cik"], row["metric_id"]): row for row in parent.quarter_observations
        if row["metric_id"] in {"quarter_assets", "quarter_liabilities"}
        and (row["calendar_year"], row["calendar_quarter"]) == _APPROVED_BUCKET
    }
    if any(row["metric_id"] == METRIC_ID for row in parent.quarter_definitions):
        raise ValueError("liability addition would overwrite a parent definition")
    rows = []
    used = set()
    for period in parent.quarter_period_inventory:
        cik = period["cik"]
        bucket = (period["calendar_year"], period["calendar_quarter"])
        item = by_cik.get(cik) if bucket == _APPROVED_BUCKET else None
        record = {
            "cik": cik, "ticker": period["ticker"], "metric_id": METRIC_ID,
            "canonical_metric_id": METRIC_ID, "definition_version": DEFINITION_VERSION,
            "calendar_year": bucket[0], "calendar_quarter": bucket[1],
            "period_class": "INSTANT", "observation_basis": "INSTANT",
            "fiscal_year": None, "fiscal_quarter": None, "period_start": None,
            "period_end": None, "end_convention": None, "filed_date": None, "report_date": None,
            "selection_view": "LATEST_REPORTED", "selection_as_of_date": cutoff,
            "unit": "USD", "dimensions": [], "basis_version": None, "value": None,
            "availability_status": "UNAVAILABLE", "source_kind": "UNAVAILABLE",
            "reason": _UNAVAILABLE, "reasons": [_UNAVAILABLE],
            "quality_status": None, "quality_reasons": [], "quality_blocking": False,
            "source_lineage": {},
        }
        if item is not None:
            original = anchors.get((cik, "quarter_liabilities"))
            assets = anchors.get((cik, "quarter_assets"))
            _verify_candidate(item, period, original, assets, cutoff)
            record.update(
                availability_status="AVAILABLE", source_kind="DERIVED_METRIC", value=item["value"],
                fiscal_year=period["fiscal_year"], fiscal_quarter=period["fiscal_quarter"],
                period_end=period["period_end"], end_convention="EXCLUSIVE",
                filed_date=period["filed_date"], report_date=period["report_date"],
                reason=None, reasons=[],
                source_lineage={
                    "derivation_rule_version": RULE_VERSION,
                    "formula": _DEFINITION["formula"],
                    "approved_audit": audit_pin.copy(),
                    "source_evidence": item,
                    "parent_period_inventory_id": period["inventory_id"],
                    "original_liability_observation_id": original["observation_id"],
                    "parent_assets_observation_id": assets["observation_id"],
                },
            )
            used.add(cik)
        record["observation_id"] = "quarter-liability-addition-" + digest_value(record)[:24]
        rows.append(record)
    if used != set(by_cik):
        raise ValueError("liability audit candidate is outside the parent inventory")
    definition = {**_DEFINITION, "allowed_source_kinds": ["DERIVED_METRIC"]}
    return definition, _support_rows(parent.companies, rows, definitions=(definition,)), rows


def _verify_candidate(
    item: dict, period: dict, original: dict | None, assets: dict | None, cutoff: str,
) -> None:
    if (
        original is None or original.get("availability_status") != "UNAVAILABLE"
        or original.get("value") is not None or original.get("quality_blocking")
        or original.get("quality_status") == "BLOCK"
        or original.get("reason") != "REQUIRED_ITEM_NOT_IN_PREPARED_DATA"
    ):
        raise ValueError("liability candidate is not a missing eligible parent observation")
    proof = item.get("provenance")
    value = finite_decimal(item.get("value"))
    if (
        not isinstance(proof, dict) or item.get("rule_version") != RULE_VERSION
        or not isinstance(item.get("value"), str) or value is None or value < 0
        or item.get("reason") is not None or item.get("unit") != "USD"
        or item.get("ticker") != period["ticker"] or period["bucket_status"] != "PERIOD_AVAILABLE"
        or period.get("end_convention") != "EXCLUSIVE" or type(period.get("fiscal_year")) is not int
        or period.get("fiscal_quarter") not in {"Q1", "Q2", "Q3", "Q4"}
        or item.get("instant") != item.get("instant_exclusive") or item.get("instant") != period["period_end"]
        or item.get("display_date") != period["report_date"]
        or item["display_date"] != (date.fromisoformat(item["instant"]) - timedelta(days=1)).isoformat()
        or item.get("accession") != proof.get("accession") or item.get("accession") != period["accession"]
        or proof.get("filed_date") != period["filed_date"] or not period["report_date"] <= period["filed_date"] <= cutoff
        or not any(
            anchor.get("period_start") is None
            and all(anchor.get(field) == period.get(field) for field in (
                "accession", "period_end", "fiscal_year", "fiscal_quarter", "filed_date", "report_date",
            ))
            for anchor in period["candidate_periods"]
        )
        or proof.get("formula") != _DEFINITION["formula"]
        or finite_decimal(proof.get("liability_component_sum")) != value
        or item.get("package_sha256") != proof.get("package_sha256")
        or not all(re.fullmatch(r"[0-9a-f]{64}", str(item.get(key))) for key in (
            "raw_manifest_sha256", "intake_sha256", "package_sha256",
        ))
    ):
        raise ValueError("liability candidate differs from approved source or actual instant")
    equity = proof.get("equity")
    components = proof.get("liability_components")
    if not isinstance(equity, dict) or not isinstance(components, list) or not components or not all(
        isinstance(component, dict) for component in components
    ):
        raise ValueError("liability candidate lacks source component evidence")
    sources = [proof.get("assets"), proof.get("balance_total"), equity.get("source"),
               *(component.get("source") for component in components)]
    if not all(isinstance(source, dict) and all(source.get(field) for field in (
        "source_fact_id", "raw_concept_id", "raw_concept_qname", "context_id", "row_locator", "cell_locator",
    )) for source in sources):
        raise ValueError("liability candidate lacks bound source fact identities")
    if (
        assets is None or assets.get("availability_status") != "AVAILABLE"
        or assets.get("source_kind") != "REPORTED" or assets.get("period_class") != "INSTANT"
        or assets.get("period_start") is not None or assets.get("end_convention") != "EXCLUSIVE"
        or assets.get("unit") != "USD" or assets.get("dimensions") != []
        or assets.get("quality_blocking") or assets.get("quality_status") == "BLOCK"
        or any(assets.get(field) != period.get(field) for field in (
            "accession", "filed_date", "report_date", "period_end", "fiscal_year", "fiscal_quarter",
        ))
        or (asset_value := finite_decimal(assets.get("value"))) is None
        or asset_value != finite_decimal(proof["assets"].get("value"))
    ):
        raise ValueError("liability candidate differs from the prepared assets anchor")
