"""Exact as-filed statement occurrences for governed metric continuity."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.statement_structure import finite_decimal

PRODUCTIVE_ASSETS = "us-gaap:PaymentsToAcquireProductiveAssets"
LEGACY_REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
NEW_REVENUE = "us-gaap:Revenues"
STATEMENT_EVIDENCE_VERSION = "statement-metric-occurrence-v1"
CONTINUITY_CATALOG = "quarterly-investor-41-statement-continuity-v3"
CAPEX_POLICY = "EXACT_PRIMARY_PP_AND_E_PURCHASE_V1"
REVENUE_POLICY = "EXACT_PRIMARY_REVENUE_OVERLAP_V1"
STANDARD_CAPEX = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
OccurrenceIndex = dict[tuple[str, str], dict[str, Any]]

_OCCURRENCE_RULES = {
    PRODUCTIVE_ASSETS: ("CF", "purchases of property and equipment", {"QTD_3M", "YTD_6M", "YTD_9M", "FY"}),
    LEGACY_REVENUE: ("IS", "revenues", {"QTD_3M"}),
    NEW_REVENUE: ("IS", "revenues", {"QTD_3M"}),
}


def build_statement_metric_evidence(
    *,
    entry: dict[str, Any],
    package_root: Path,
    snapshot_manifest_sha256: str,
    snapshot_table_sha256: Mapping[str, str],
    financial_as_of: str,
) -> tuple[dict[str, Any], ...]:
    """Reopen one pinned Raw snapshot and its verified primary Inline document."""
    from sec_xbrl.analytics.statement_source import prepare_filing, read_primary_document
    from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
    from sec_xbrl.screening.common import regular_file, require_cik, sha256_file

    ref = entry["filing"]
    cik = require_cik(ref["cik"])
    accession = ref["accession"]
    if not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        raise ValueError("statement evidence requires a valid accession")
    if date.fromisoformat(ref["filed_date"]) > date.fromisoformat(financial_as_of):
        raise ValueError("statement evidence filing is after cutoff")
    directory = Path(entry["source_run"]) / "snapshots" / cik / accession.replace("-", "")
    manifest = regular_file(directory / "layer1_manifest.json", "statement evidence Raw manifest")
    if sha256_file(manifest) != snapshot_manifest_sha256:
        raise ValueError("statement evidence Raw manifest differs from pin")
    snapshot = _load_declared_cohort_snapshot(directory, cik, accession)
    if snapshot.input.manifest_sha256 != snapshot_manifest_sha256:
        raise ValueError("statement evidence Raw manifest changed during verification")
    if snapshot.table_sha256 != snapshot_table_sha256:
        raise ValueError("statement evidence Raw tables differ from pins")
    filing, = snapshot.records("filing")
    if any(filing[field] != ref[field] for field in ("form", "filed_date", "report_date", "primary_document")):
        raise ValueError("statement evidence Raw scope differs from declared filing")
    if filing["form"] not in {"10-K", "10-Q"}:
        return ()
    document = read_primary_document(entry=entry, filing=filing, package_root=package_root)
    prepared = prepare_filing(snapshot=snapshot, document=document, as_of=financial_as_of)
    return _statement_occurrences(
        prepared,
        filing=filing,
        snapshot_id=snapshot.input.snapshot_id,
        snapshot_manifest_sha256=snapshot_manifest_sha256,
    )


def _statement_occurrences(
    prepared: dict[str, list[dict]],
    *,
    filing: dict[str, Any],
    snapshot_id: str,
    snapshot_manifest_sha256: str,
) -> tuple[dict[str, Any], ...]:
    tables = {row["table_id"]: row for row in prepared["source_tables"]}
    rows = {row["row_id"]: row for row in prepared["source_statement_rows"]}
    paths = {row["row_id"]: row for row in prepared["statement_rows"]}
    candidates: dict[tuple[str, str, str], list[dict[str, Any] | None]] = defaultdict(list)
    raw_aspects: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in prepared["statement_facts"]:
        if fact["concept"]["qname"] in {LEGACY_REVENUE, NEW_REVENUE}:
            raw_aspects[_fact_aspects(fact)].append(fact)
    for fact in prepared["statement_facts"]:
        concept, scope = fact["concept"], fact["scope"]
        qname = concept["qname"]
        rule = _OCCURRENCE_RULES.get(qname)
        if rule is None or scope["dimensions"] != [] or scope["unit"] != {
            "numerator": ["iso4217:USD"], "denominator": [],
        }:
            continue
        section, label, period_classes = rule
        period = scope["period"]
        namespace = concept["namespace_uri"]
        value = finite_decimal(fact["value_numeric"])
        entity = str(fact["context"].get("entity_identifier") or "")
        if (
            not re.fullmatch(r"https?://www\.sec\.gov/CIK:[0-9]{1,10}", entity)
            or entity.rsplit(":", 1)[-1].zfill(10) != filing["cik"]
            or period["type"] != "duration"
            or period["class"] not in period_classes
            or not period["start"] or not period["end"]
            or value is None
            or fact["is_nil"] or fact["reported_or_derived"] != "REPORTED"
            or concept["is_standard"] is not True or concept["period_type"] != "duration"
            or "monetary" not in str(concept["data_type"]).casefold()
            or not re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", str(namespace))
        ):
            continue
        same_aspects = raw_aspects.get(_fact_aspects(fact), [fact])
        if any(_fact_payload(item) != _fact_payload(fact) for item in same_aspects):
            continue
        for location in fact["source_locations"]:
            table, row = tables[location["table_id"]], rows[location["row_id"]]
            if table["section"] != section:
                continue
            key = (qname, period["start"], period["end"])
            if (
                location["binding_status"] != "EXACT_RAW_ID"
                or row["coverage_status"] != "INCLUDED"
                or row["label"].casefold() != label
                or (qname == PRODUCTIVE_ASSETS and value < 0)
                or not any(
                    paths[path_id]["raw_concept_id"] == fact["raw_concept_id"]
                    and paths[path_id]["network_identity"]["role_id"] == table["role_id"]
                    and not paths[path_id]["cycle"]
                    for path_id in row["pre_path_ids"]
                )
            ):
                candidates[key].append(None)
                continue
            candidates[key].append({
                "version": STATEMENT_EVIDENCE_VERSION,
                "cik": filing["cik"],
                "accession": filing["accession"],
                "source_filing_id": filing["filing_id"],
                "filed_date": filing["filed_date"],
                "report_date": filing["report_date"],
                "source_snapshot_id": snapshot_id,
                "snapshot_manifest_sha256": snapshot_manifest_sha256,
                "package_sha256": filing["package_hash"],
                "source_document": table["source_document"],
                "source_document_sha256": table["source_document_sha256"],
                "source_table_sha256": table["table_sha256"],
                "source_table_id": table["table_id"],
                "source_row_id": row["row_id"],
                "source_fact_id": fact["fact_id"],
                "equivalent_source_fact_ids": sorted(item["fact_id"] for item in same_aspects),
                "decimals": fact.get("decimals"),
                "precision": fact.get("precision"),
                "context_id": fact["context_id"],
                "unit_id": fact["unit_id"],
                "raw_concept_id": fact["raw_concept_id"],
                "raw_concept_qname": qname,
                "raw_concept_namespace_uri": namespace,
                "value": str(value),
                "period_class": period["class"],
                "period_start": period["start"],
                "period_end": period["end"],
                "end_convention": "EXCLUSIVE",
                "unit": "USD",
                "dimensions": [],
                "statement_type": section,
                "statement_role_id": table["role_id"],
                "row_label": row["label"],
                "table_locator": location["table_locator"],
                "row_locator": location["row_locator"],
                "cell_locator": location["cell_locator"],
                "inline_id": location["inline_id"],
            })
    return tuple(
        matches[0] for _, matches in sorted(candidates.items())
        if len(matches) == 1 and matches[0] is not None
    )


def _fact_aspects(fact: dict[str, Any]) -> tuple[str, str, str]:
    return fact["raw_concept_id"], fact["context_id"], fact["unit_id"]


def _fact_payload(fact: dict[str, Any]) -> tuple[Any, ...]:
    return (
        fact["value_numeric"], fact.get("raw_value"), fact.get("decimals"), fact.get("precision"),
        fact["is_nil"], fact["reported_or_derived"], fact["scope"]["dimensions"],
    )


def read_statement_metric_evidence(pin: dict[str, Any], financial_as_of: str) -> OccurrenceIndex:
    """Read prepared occurrences from an independently pinned immutable artifact."""
    from sec_xbrl.screening.common import regular_file, require_cik

    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
        raise ValueError("statement metric evidence requires an exact file pin")
    path = regular_file(Path(pin["path"]), "statement metric evidence")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("statement metric evidence differs from pin")
    payload = json.loads(data)
    if (not isinstance(payload, dict) or payload.get("version") != STATEMENT_EVIDENCE_VERSION
        or payload.get("financial_as_of") != financial_as_of
        or not isinstance(payload.get("records"), list)):
        raise ValueError("statement metric evidence envelope differs")
    cutoff = date.fromisoformat(financial_as_of)
    result: OccurrenceIndex = {}
    for item in payload["records"]:
        if not isinstance(item, dict) or item.get("version") != STATEMENT_EVIDENCE_VERSION:
            raise ValueError("statement occurrence version differs")
        rule = _OCCURRENCE_RULES.get(item.get("raw_concept_qname"))
        value = finite_decimal(item.get("value"))
        if (
            rule is None or item.get("statement_type") != rule[0]
            or str(item.get("row_label")).casefold() != rule[1]
            or item.get("period_class") not in rule[2] or item.get("end_convention") != "EXCLUSIVE"
            or item.get("dimensions") != [] or item.get("unit") != "USD"
            or not isinstance(item.get("value"), str) or value is None
            or (item["raw_concept_qname"] == PRODUCTIVE_ASSETS and value < 0)
            or not re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", str(item.get("raw_concept_namespace_uri")))
            or not all(re.fullmatch(r"[0-9a-f]{64}", str(item.get(field))) for field in (
                "snapshot_manifest_sha256", "package_sha256", "source_document_sha256", "source_table_sha256",
            ))
            or not all(isinstance(item.get(field), str) and item[field] for field in (
                "accession", "source_filing_id", "source_snapshot_id", "source_fact_id",
                "raw_concept_id", "context_id", "unit_id", "source_document", "statement_role_id",
                "source_table_id", "source_row_id", "table_locator", "row_locator", "cell_locator",
            ))
        ):
            raise ValueError("statement occurrence scope is invalid")
        cik = require_cik(item["cik"])
        accession = item["accession"]
        start, end, filed, report = (date.fromisoformat(item[field]) for field in (
            "period_start", "period_end", "filed_date", "report_date",
        ))
        if (not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
            or item["source_snapshot_id"] != f"l1:{cik}:{accession.replace('-', '')}:{item['snapshot_manifest_sha256'][:16]}"
            or not start < end or end - timedelta(days=1) > report
            or not report <= filed <= cutoff):
            raise ValueError("statement occurrence dates or snapshot identity differ")
        identities = item.get("equivalent_source_fact_ids")
        if (
            not isinstance(identities, list)
            or not all(isinstance(identity, str) and identity for identity in identities)
            or identities != sorted(set(identities))
            or item["source_fact_id"] not in identities
            or (item["raw_concept_qname"] == PRODUCTIVE_ASSETS and len(identities) != 1)
        ):
            raise ValueError("statement occurrence Raw fact equivalences differ")
        for fact_id in identities:
            key = (item["source_snapshot_id"], fact_id)
            if key in result:
                raise ValueError("statement occurrence identity is duplicated")
            result[key] = item
    return result


def matching_statement_occurrence(
    source: dict[str, Any], evidence: OccurrenceIndex,
) -> dict[str, Any] | None:
    """Bind the selected source, not a coincidentally equal number in the artifact."""
    item = evidence.get((source.get("source_snapshot_id"), source.get("source_fact_id")))
    if (item is None or source.get("source_kind") != "REPORTED"
        or source.get("source_id") != f"{source.get('source_snapshot_id')}:{source.get('source_fact_id')}"):
        return None
    fields = (
        "cik", "accession", "source_filing_id", "context_id", "unit_id",
        "raw_concept_qname", "raw_concept_namespace_uri", "filed_date", "report_date",
        "period_class", "period_start", "period_end", "end_convention", "unit", "dimensions",
    )
    if any(source.get(field) != item[field] for field in fields):
        return None
    if finite_decimal(source.get("value")) != finite_decimal(item["value"]):
        return None
    return item


def revenue_transition_proof(inputs: list[dict[str, Any]], evidence: OccurrenceIndex) -> dict[str, Any] | None:
    """Permit one old-to-new transition at an exactly re-presented preceding quarter."""
    anchors = []
    for item in inputs:
        lineage = item["source_lineage"]
        if item["source_kind"] == "DERIVED_QUARTER":
            raw = lineage["derivation_inputs"]
            if len({source["raw_concept_qname"] for source in raw}) != 1:
                return None
            endpoint = [source for source in raw if source["period_end"] == item["period_end"]]
            if len(endpoint) != 1:
                return None
            lineage = endpoint[0]
        anchors.append(lineage)
    qnames = [source["raw_concept_qname"] for source in anchors]
    if NEW_REVENUE not in qnames:
        return None
    pivot = qnames.index(NEW_REVENUE)
    if pivot == 0 or qnames != [LEGACY_REVENUE] * pivot + [NEW_REVENUE] * (4 - pivot):
        return None
    for group in (inputs[:pivot], inputs[pivot:]):
        if len({(item.get("company_canonical_concept_id"), item.get("canonical_mapping_version")) for item in group}) != 1:
            return None
    if inputs[pivot - 1]["source_kind"] != "REPORTED" or inputs[pivot]["source_kind"] != "REPORTED":
        return None
    old = matching_statement_occurrence(anchors[pivot - 1], evidence)
    first_new = matching_statement_occurrence(anchors[pivot], evidence)
    if old is None or first_new is None:
        return None
    # If multiple later filings disagree about the same new-tag overlap, hold it.
    overlaps = [
        item for item in evidence.values()
        if item["cik"] == old["cik"] and item["raw_concept_qname"] == NEW_REVENUE
        and item["period_class"] == "QTD_3M"
        and (item["period_start"], item["period_end"]) == (old["period_start"], old["period_end"])
        and item["filed_date"] >= first_new["filed_date"]
        and item["source_filing_id"] != old["source_filing_id"]
    ]
    if not overlaps or any(finite_decimal(item["value"]) != finite_decimal(old["value"]) for item in overlaps):
        return None
    comparative = min(overlaps, key=lambda item: (item["filed_date"], item["accession"], item["source_fact_id"]))
    return {
        "policy": REVENUE_POLICY,
        "proof_available_on": max(item["filed_date"] for item in (old, first_new, comparative)),
        "old_occurrence": old,
        "elected_old_fact_id": anchors[pivot - 1]["source_fact_id"],
        "first_new_occurrence": first_new,
        "elected_first_new_fact_id": anchors[pivot]["source_fact_id"],
        "new_comparative_occurrence": comparative,
    }
