"""Evidence-bound producer helpers; existing definitions and publications stay immutable."""
from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta
from decimal import localcontext
from pathlib import Path

from sec_xbrl.analytics.quarterly_derived_metrics import percentage_result
from sec_xbrl.analytics.statement_structure import finite_decimal
from sec_xbrl.metrics.screening import DECIMAL_CONTEXT, _basis_compatibility, _is_usd_unit
from sec_xbrl.metrics.statement_metric_evidence import (
    LEGACY_REVENUE,
    NEW_REVENUE,
    _fact_aspects,
    _fact_payload,
)

REVENUE_VERSION = "annual-revenue-yoy-same-filing-continuity-v2"
BRIDGE_RULE = "same-filing-primary-revenue-exact-prior-v1"
LATEST_RULE = "published-latest-actual-company-quarter-v1"


def quarter_name(value: int | str) -> str:
    if type(value) is int and 1 <= value <= 4:
        return f"Q{value}"
    if value in {"Q1", "Q2", "Q3", "Q4"}:
        return value
    raise ValueError("actual fiscal quarter coordinate is invalid")


def checked_file(pin: dict) -> Path:
    from sec_xbrl.screening.common import regular_file, sha256_file

    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"} or not isinstance(pin["path"], str):
        raise ValueError("governed correction requires an explicit file pin")
    path = Path(pin["path"])
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("governed correction pin must be absolute without aliases")
    path = regular_file(path, "governed correction input")
    if sha256_file(path) != pin["sha256"]:
        raise ValueError("governed correction input differs from pin")
    return path


def observation_identity(row: dict) -> str:
    from sec_xbrl.screening.common import digest_value

    return "screening-metric-observation-" + digest_value({key: value for key, value in row.items()
                                                         if key != "metric_observation_id"})[:24]


def adopt_revenue_version(row: dict) -> dict:
    from sec_xbrl.screening.common import digest_value

    result = copy.deepcopy(row)
    result["metric_definition_version"] = REVENUE_VERSION
    result["original_observation"] = {"id": row["metric_observation_id"], "definition_version": row["metric_definition_version"]}
    result["metric_observation_id"] = "screening-metric-observation-" + digest_value({
        "rule": "definition-version-adoption-v1", "original": row["metric_observation_id"],
        "definition_version": REVENUE_VERSION})[:24]
    return result


def prepare_revenue_bridge(*, current: dict, prior: dict, original: dict, raw: dict,
                           package_root: Path, financial_as_of: str) -> dict:
    """Bind typed primary facts by reopening only the explicitly pinned retained Raw."""
    from sec_xbrl.analytics.statement_source import prepare_filing, read_primary_document
    from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot

    manifest_path = checked_file(raw["manifest"])
    entry = raw["entry"]
    ref = entry["filing"]
    expected = Path(entry["source_run"]) / "snapshots" / ref["cik"] / ref["accession"].replace("-", "")
    if manifest_path != expected / "layer1_manifest.json":
        raise ValueError("revenue bridge Raw parent differs")
    snapshot = _load_declared_cohort_snapshot(expected, ref["cik"], ref["accession"])
    if snapshot.input.manifest_sha256 != raw["manifest"]["sha256"] or snapshot.table_sha256 != raw["table_sha256"]:
        raise ValueError("revenue bridge Raw inventory differs")
    filing, = snapshot.records("filing")
    if any(filing[key] != ref[key] for key in ("cik", "accession", "form", "filed_date", "report_date", "primary_document")):
        raise ValueError("revenue bridge Raw filing differs")
    document = read_primary_document(entry=entry, filing=filing, package_root=package_root)
    prepared = prepare_filing(snapshot=snapshot, document=document, as_of=financial_as_of)
    result = _bridge_from_prepared(current=current, prior=prior, original=original,
                                   prepared=prepared, financial_as_of=financial_as_of)
    result["continuity_proof"]["raw"] = copy.deepcopy(raw)
    result["continuity_proof"]["snapshot_id"] = snapshot.input.snapshot_id
    result["trace"] = {"rule_version": BRIDGE_RULE, "continuity_proof": copy.deepcopy(result["continuity_proof"])}
    result["metric_observation_id"] = observation_identity(result)
    return result


def _bridge_from_prepared(*, current: dict, prior: dict, original: dict,
                          prepared: dict, financial_as_of: str) -> dict:
    """A changed QName is admitted only through the current filing's exact comparative."""
    filing, = prepared["filings"]
    cutoff = date.fromisoformat(financial_as_of)
    if (filing["form"] not in {"10-K", "10-K/A"}
            or date.fromisoformat(filing["filed_date"]) > cutoff or filing["cik"] != current["cik"]
            or current["cik"] != prior["cik"] or original["cik"] != current["cik"]
            or current["source_filings"] != [filing["accession"]]
            or original["availability_status"] != "UNAVAILABLE"
            or set(original.get("diagnostic_reasons", [])) != {"SEMANTIC_IDENTITY_MISMATCH"}
            or original["metric_id"] != "revenue_yoy"):
        raise ValueError("revenue bridge original scope or cutoff differs")
    for row in (current, prior):
        if (row["availability_status"] != "AVAILABLE" or row.get("quality_blocking")
                or row.get("quality_status") == "BLOCK" or row.get("mapping_review_required") is not False
                or row["metric_id"] != "revenue" or row["period_class"] != "FY"
                or row.get("source_kind") != "REPORTED" or row.get("status") != "REPORTED"
                or row["raw_concept_qname"] not in {LEGACY_REVENUE, NEW_REVENUE}
                or row.get("raw_concept_is_standard") is not True or row.get("dimensions") != []
                or row.get("unit") != "USD" or not _is_usd_unit(row.get("unit_semantics"))
                or row.get("raw_concept_taxonomy_family") != "us-gaap"
                or row.get("raw_concept_period_type") != "duration"
                or "monetary" not in str(row.get("raw_concept_data_type")).casefold()
                or row.get("view") != "LATEST_REPORTED" or row.get("financial_as_of") != financial_as_of):
            raise ValueError("revenue bridge requires available consolidated reported revenue")
    if (current["fiscal_year"] != prior["fiscal_year"] + 1
            or original["fiscal_year"] != current["fiscal_year"]
            or _basis_compatibility((current, prior)) is None
            or current["unit_semantics"] != prior["unit_semantics"]
            or original["input_observation_ids"] != [current["metric_observation_id"], prior["metric_observation_id"]]):
        raise ValueError("revenue bridge original input identities differ")
    for row in (current, prior):
        if not 350 <= (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days <= 378:
            raise ValueError("revenue bridge FY duration differs")
    if not 330 <= (date.fromisoformat(current["period_end"]) - date.fromisoformat(prior["period_end"])).days <= 400:
        raise ValueError("revenue bridge consecutive FY ends differ")
    top, bottom = finite_decimal(current["value"]), finite_decimal(prior["value"])
    if top is None or bottom is None or top < 0 or bottom <= 0:
        raise ValueError("revenue bridge requires nonnegative current and positive prior")
    current_evidence = _primary_revenue(prepared, filing, current, current["raw_concept_qname"])
    prior_evidence = _primary_revenue(prepared, filing, prior, current["raw_concept_qname"])
    current_ids = {identity for item in current_evidence for identity in item["equivalent_fact_ids"]}
    if not set(current["source_fact_ids"]) <= current_ids:
        raise ValueError("revenue bridge current fact is not the exact typed primary occurrence")
    concept_ids = {item["raw_concept_id"] for item in (*current_evidence, *prior_evidence)}
    if len(concept_ids) != 1:
        raise ValueError("revenue bridge comparative concept differs")
    filed_dates = [filing["filed_date"]]
    for row in (current, prior):
        lineage = (row.get("trace") or {}).get("value_lineage") or {}
        filed = lineage.get("filed_date")
        if not isinstance(filed, str):
            raise TypeError("revenue bridge original filing availability is unknown")
        if date.fromisoformat(filed) > cutoff:
            raise ValueError("revenue bridge original filing is after cutoff")
        filed_dates.append(filed)
    result = adopt_revenue_version(original)
    with localcontext(DECIMAL_CONTEXT):
        value = str(percentage_result(top, bottom, subtract_one=True))
    result.update(value=value, availability_status="AVAILABLE",
                  unavailable_reason=None, diagnostic_reasons=[], status="DERIVED_METRIC",
                  compatibility=BRIDGE_RULE, comparability_policy=BRIDGE_RULE,
                  proof_available_on=filing["filed_date"], known_on=max(filed_dates))
    result["continuity_proof"] = {"rule_version": BRIDGE_RULE, "current": copy.deepcopy(current),
                                  "original_prior": copy.deepcopy(prior), "current_primary": current_evidence,
                                  "same_filing_prior_primary": prior_evidence, "filing": copy.deepcopy(filing)}
    result["source_fact_ids"] = sorted(set(result["source_fact_ids"]) | {
        item["fact_id"] for item in prior_evidence})
    result["trace"] = {"rule_version": BRIDGE_RULE, "continuity_proof": copy.deepcopy(result["continuity_proof"])}
    result["metric_observation_id"] = observation_identity(result)
    return result


def _primary_revenue(prepared: dict, filing: dict, observation: dict, qname: str) -> list[dict]:
    from sec_xbrl.screening.common import canonical_json

    tables = {row["table_id"]: row for row in prepared["source_tables"]}
    rows = {row["row_id"]: row for row in prepared["source_statement_rows"]}
    paths = {row["row_id"]: row for row in prepared["statement_rows"]}
    selected = []
    facts = []
    for fact in prepared["statement_facts"]:
        scope, concept = fact["scope"], fact["concept"]
        period = scope["period"]
        if (concept["qname"] != qname or period.get("start") != observation["period_start"]
                or period.get("end") != observation["period_end"] or scope["dimensions"] != []):
            continue
        if (scope["unit"] != {"numerator": ["iso4217:USD"], "denominator": []}
                or period["type"] != "duration" or period["class"] != "FY"
                or concept["is_standard"] is not True or concept["period_type"] != "duration"
                or "monetary" not in str(concept["data_type"]).casefold()
                or not re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", concept["namespace_uri"])
                or str(fact["context"].get("entity_identifier", "")).rsplit(":", 1)[-1].zfill(10) != filing["cik"]
                or fact["is_nil"] or fact["reported_or_derived"] != "REPORTED"
                or finite_decimal(fact["value_numeric"]) != finite_decimal(observation["value"])):
            raise ValueError("revenue bridge conflicting reported scope or amount")
        facts.append(fact)
    for fact in facts:
        equivalents = [other for other in facts if _fact_aspects(other) == _fact_aspects(fact)]
        if any(_fact_payload(other) != _fact_payload(fact) for other in equivalents):
            raise ValueError("revenue bridge conflicting duplicate Raw facts")
        for location in fact["source_locations"]:
            table, row = tables[location["table_id"]], rows[location["row_id"]]
            if table["section"] != "IS":
                continue
            if (table["filing_id"] != filing["filing_id"] or location["binding_status"] != "EXACT_RAW_ID"
                    or row["coverage_status"] != "INCLUDED" or row["label"].strip().casefold() not in {"revenues", "total revenues"}
                    or not any(paths[key]["raw_concept_id"] == fact["raw_concept_id"]
                               and paths[key]["network_identity"]["role_id"] == table["role_id"]
                               and not paths[key]["cycle"] for key in row["pre_path_ids"])):
                raise ValueError("revenue bridge primary statement occurrence is not exact")
            selected.append({"fact_id": fact["fact_id"], "equivalent_fact_ids": sorted(x["fact_id"] for x in equivalents),
                             "raw_concept_id": fact["raw_concept_id"], "concept": copy.deepcopy(fact["concept"]),
                             "scope": copy.deepcopy(fact["scope"]), "context_id": fact["context_id"],
                             "unit_id": fact["unit_id"], "value": fact["value_numeric"],
                             "table": copy.deepcopy(table), "row": copy.deepcopy(row), "location": copy.deepcopy(location)})
    if not selected:
        raise ValueError("revenue bridge exact typed primary comparative is absent")
    return sorted(selected, key=canonical_json)


def prepare_latest_quarter(*, analysis_manifest: dict, ticker: str, cik: str,
                           financial_as_of: str, latest: dict, quarterly_manifest: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Produce only the requested actual company quarter using the normal public builder."""
    from sec_xbrl.analysis import open_analysis
    from sec_xbrl.metrics.quarterly_screening import (
        CATALOG_VERSION,
        build_quarterly_company_records,
    )
    from sec_xbrl.metrics.statement_metric_evidence import (
        CONTINUITY_CATALOG,
        read_statement_metric_evidence,
    )
    from sec_xbrl.screening.common import contained_file

    manifest_path = checked_file(analysis_manifest)
    manifest = json.loads(manifest_path.read_bytes())
    scope = manifest["companies"][ticker]
    if scope["as_of"] != financial_as_of or manifest.get("period_mode", "QUARTERLY") != "QUARTERLY":
        raise ValueError("latest quarter analysis scope differs")
    qpath = checked_file(quarterly_manifest)
    qmanifest = json.loads(qpath.read_bytes())
    company, = [row for row in qmanifest["config"]["companies"] if row["cik"] == cik and row["ticker"] == ticker]
    if (qmanifest["financial_as_of"] != financial_as_of or Path(company["analysis_root"]) != manifest_path.parent
            or company["analysis_manifest_sha256"] != analysis_manifest["sha256"]):
        raise ValueError("latest quarter owner analysis differs")
    files = scope["views"]["LATEST_REPORTED"]["files"]
    touched = []
    for name in ("columns", "core_rows", "core_cells", *(f"trace_{digit}" for digit in "0123456789abcdef")):
        declaration = files[name]
        path = contained_file(manifest_path.parent, declaration["path"], "latest quarter source")
        checked_file({"path": str(path), "sha256": declaration["sha256"]})
        touched.append({"path": str(path), "sha256": declaration["sha256"]})
    client = open_analysis(manifest_path.parent)
    columns, rows, cells = (client._records(ticker, "LATEST_REPORTED", name) for name in ("columns", "core_rows", "core_cells"))
    candidates = [row for row in columns if row.get("period_class") == "QTD_3M" and row.get("column_status") == "AVAILABLE"]
    dated = [row for row in candidates if row.get("actual_start_date") and row.get("actual_end_date")]
    if not dated:
        raise ValueError("latest quarter has no dated source")
    end = max(row["actual_end_date"] for row in dated)
    choices = {(row["fiscal_year"], quarter_name(row["fiscal_quarter"]), row["actual_start_date"], row["actual_end_date"])
               for row in dated if row["actual_end_date"] == end}
    expected = (latest["fiscal_year"], quarter_name(latest["fiscal_quarter"]), latest["period_start"], latest["period_end"])
    if (choices != {expected} or any((row["fiscal_year"], quarter_name(row["fiscal_quarter"])) >= expected[:2]
                                   for row in candidates if row not in dated)
            or latest["end_convention"] != "EXCLUSIVE"
            or date.fromisoformat(end) > date.fromisoformat(financial_as_of) + timedelta(days=1)):
        raise ValueError("latest quarter actual source period is unresolved")
    traces = [row for digit in "0123456789abcdef" for row in client._records(ticker, "LATEST_REPORTED", f"trace_{digit}")]
    inclusive = date.fromisoformat(end) - timedelta(days=1)
    bucket = {"calendar_year": inclusive.year, "calendar_quarter": (inclusive.month - 1) // 3 + 1,
              "status": "ACTUAL_COMPLETED_COMPANY_PERIOD"}
    catalog = qmanifest["config"].get("catalog_version", CATALOG_VERSION)
    if catalog == CONTINUITY_CATALOG:
        touched.append(qmanifest["config"]["statement_metric_evidence"])
    evidence = read_statement_metric_evidence(qmanifest["config"]["statement_metric_evidence"], financial_as_of) if catalog == CONTINUITY_CATALOG else None
    observations, inventory = build_quarterly_company_records(
        ticker=ticker, cik=cik, financial_as_of=financial_as_of, columns=columns, rows=rows, cells=cells,
        traces=traces, spine=[bucket], catalog_version=catalog, statement_evidence=evidence)
    if len(inventory) != 1 or inventory[0]["bucket_status"] != "PERIOD_AVAILABLE":
        raise ValueError("latest quarter has no unique prepared period")
    period = inventory[0]
    if (quarter_name(period["fiscal_quarter"]) != quarter_name(latest["fiscal_quarter"])
            or any(period.get(key) != latest.get(key) for key in ("fiscal_year", "period_start", "period_end"))):
        raise ValueError("latest quarter prepared period differs from source header")
    if not period.get("filed_date") or period["filed_date"] > financial_as_of:
        raise ValueError("latest quarter source filing is after cutoff or unknown")
    return observations, inventory, touched
