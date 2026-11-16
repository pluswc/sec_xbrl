"""Exact reviewed reported-quarter inputs and separately governed EPS TTM.

Official HTML is not XBRL. Its original null identity/scope is retained, and an
explicit lead-reviewed mapping admits mixed physical formats to one EPS scope.
No collection, ticker policy, synthetic Q4 or historical-ready backdating.
"""
from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from lxml import html

from sec_xbrl.metrics.market_inputs import (
    _derive_market_eps_ttm_core,
    finite,
    identity,
    pinned_json,
)

RULE = "reported-quarter-eps-ttm-reviewed-scope-v1"
MODE = "CURRENT_EVALUATION_WITH_LAGGED_QUOTE"


def _now() -> datetime:
    return datetime.now(UTC)


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("actual source/ready/evaluation time must be aware")
    return parsed.astimezone(UTC)


def _bytes(pin: dict) -> bytes:
    path = Path(pin["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("reported source pin requires an absolute regular file")
    data = path.read_bytes()
    if (hashlib.sha256(data).hexdigest() != pin.get("sha256")
        or pin.get("bytes", len(data)) != len(data)):
        raise ValueError("reported source pin/hash/size differs")
    return data


def _text(node) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _reported_html(record: dict) -> dict:
    if (record.get("source_kind") != "OFFICIAL_REPORTED_HTML_TABLE"
        or record.get("raw_xbrl_identity") is not None or record.get("raw_dimension_signature") is not None
        or record.get("measurement") != "GAAP_DILUTED_TOTAL_EPS"
        or record.get("metric_label") != "Diluted" or record.get("unit_semantics") != "USD/share"
        or record.get("reported_or_derived") != "REPORTED" or record.get("period_class") != "QTD_3M"
        or record.get("end_convention") != "EXCLUSIVE" or record.get("source_document_type") != "EX-99.1"):
        raise ValueError("official quarter requires reviewed GAAP diluted-total3m and null XBRL identity")
    captured = aware(record["actual_captured_at"])
    manifest = pinned_json(record["capture_manifest_pin"])
    files = [p for p in manifest["files"] if p["path"] == record["source_pin"]["path"]]
    if (len(files) != 1 or files[0]["sha256"] != record["source_pin"]["sha256"]
        or aware(files[0]["fetched_at"]) != captured
        or any(manifest.get(k) != record[k] for k in ("cik", "ticker", "accession", "form"))):
        raise ValueError("official capture identity/time differs")
    document = html.fromstring(_bytes(record["source_pin"]))
    locator = record["locator"]
    cells, rows = document.xpath(locator["value_xpath"]), document.xpath(locator["row_xpath"])
    if len(cells) != 1 or len(rows) != 1 or cells[0] not in rows[0].iterdescendants():
        raise ValueError("official exact row/cell locator differs")
    if _text(cells[0]) != locator["raw_cell_text"] or _text(rows[0]) != locator["row_text"]:
        raise ValueError("official reported cell/row text differs")
    text = _text(cells[0]).replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    if finite(text) is None or finite(text) != finite(record["reported_value"]):
        raise ValueError("official reported value differs")
    tables = rows[0].xpath("ancestor::table[1]")
    table_text = _text(tables[0]) if len(tables) == 1 else ""
    if hashlib.sha256(table_text.encode()).hexdigest() != locator["table_text_sha256"]:
        raise ValueError("official reported table/header hash differs")
    headers = locator["table_header_rows"]
    if not any("Three Months Ended" in h for h in headers) or any(h and h not in table_text for h in headers):
        raise ValueError("official3m header evidence differs")
    primary = record["exhibit_identity"]["source_primary_pin"]
    primary_doc = html.fromstring(_bytes(primary))
    links = [(str(a.get("href")), _text(a)) for a in primary_doc.xpath("//a[@href]")]
    if not any(urljoin(primary["url"], href) == record["source_url"] for href, _ in links):
        raise ValueError("official exhibit is not linked by the pinned filing")
    if Path(record["source_pin"]["path"]).name != record["source_document"]:
        raise ValueError("official document locator differs")
    # These are governed unit semantics, not invented Raw unit/context/fact IDs.
    return {"observation_id": record["source_observation_id"], "cik": record["cik"], "ticker": record["ticker"],
            "input_id": "reported_eps_diluted_total", "period_class": "QTD_3M",
            "start": record["period_start"], "end": record["period_end"], "end_convention": "EXCLUSIVE",
            "fiscal_year": record["fiscal_year"], "fiscal_quarter": record["fiscal_quarter"],
            "value": record["reported_value"], "filed_date": record["filed_date"],
            "reported_or_derived": "REPORTED", "status": "AVAILABLE_REPORTED", "unit_kind": "USD/share",
            "unit": ['["iso4217:USD"]', '["xbrli:shares"]'], "qname": None, "namespace": None,
            "dimensions": None, "raw_dimensions": None, "source_kind": record["source_kind"],
            "actual_captured_at": record["actual_captured_at"]}


def _load(config_pin: dict) -> tuple[dict, dict, dict, dict, dict]:
    config = pinned_json(config_pin)
    if config.get("schema_version") != "eps-ttm-run-v1":
        raise ValueError("unsupported EPS TTM run")
    plan, approval = pinned_json(config["plan"]), pinned_json(config["approval"])
    if (plan.get("schema_version") != "eps-ttm-plan-v1"
        or approval.get("schema_version") != "eps-ttm-root-acceptance-v1"
        or approval.get("reviewer") != "ROOT" or approval.get("status") != "APPROVED_FOR_EXACT_DIRECT_QTD_TTM"
        or approval.get("plan") != config["plan"]):
        raise ValueError("exact ROOT EPS TTM plan approval required")
    approved = approval.get("approved_ciks", [])
    if (not approved or len(set(approved)) != len(approved)
        or set(approved) != {c["cik"] for c in plan["companies"]}
        or len(approved) != len(plan["companies"])):
        raise ValueError("EPS approval scope differs")
    held = [h["cik"] for h in plan.get("holds", [])]
    if len(held) != len(set(held)) or set(held) & set(approved):
        raise ValueError("approved and held EPS company scopes overlap")
    for pin in approval.get("evidence_pins", []):
        pinned_json(pin)
    aware(approval["approved_at"])
    decision = pinned_json(plan["evaluation_decision"])
    if (decision.get("reviewer") != "ROOT" or decision.get("status") != "APPROVED_FOR_BOUNDED_IMPLEMENTATION"
        or decision.get("mode") != MODE or decision.get("quote_session") != plan["quote_session"]
        or decision.get("public_financial_information_cutoff") != plan["public_financial_information_cutoff"]
        or decision.get("evaluation_as_of") != plan["requested_as_of"]):
        raise ValueError("EPS current evaluation decision differs")
    pools = {}
    for pin in plan["source_pins"]:
        data = pinned_json(pin)
        rows = data if isinstance(data, list) else data.get("candidates", data.get("observations", []))
        index = {}
        for r in rows:
            oid = r.get("observation_id", r.get("source_observation_id"))
            if oid in index and index[oid] != r:
                raise ValueError("ambiguous reported source identity")
            index[oid] = r
        pools[(pin["path"], pin["sha256"])] = index
    return config, plan, approval, decision, pools


def prepare_ttm(config_pin: dict, *, _recorded_at: str | None = None) -> dict:
    """Materialize approved values; verifier replay retains the recorded actual time."""
    config, plan, approval, decision, pools = _load(config_pin)
    source_records, outputs, latest_source_times = {}, [], [aware(approval["approved_at"]), aware(decision["decided_at"])]
    cutoff = plan["public_financial_information_cutoff"]
    source_review = pinned_json(plan["source_review"])
    if source_review.get("reviewer") != "ROOT" or source_review.get("status") != "SOURCE_AND_SEMANTIC_MAPPING_REVIEWED_FOR_EXACT_PLAN":
        raise ValueError("EPS semantic source review required")
    if source_review.get("reviewed_at"):
        latest_source_times.append(aware(source_review["reviewed_at"]))
    pinned_json(plan["quarter_source_proof"])
    base = pinned_json(plan["base_financial_bundle"])
    for company in plan["companies"]:
        cik = company["cik"]
        cases = [c for c in source_review.get("companies", []) if c.get("cik") == cik]
        if len(cases) != 1:
            raise ValueError("company is outside exact reviewed EPS source scope")
        case = cases[0]
        keys = [(k, k) for k in ("ticker", "security_id", "stock_class_id", "split_basis_id", "target_anchor", "window_start")]
        keys.append(("scope_id", "financial_scope_id"))
        if (any(company.get(k) != case.get(r) for k, r in keys)
            or finite(company["expected_value"]) != finite(case.get("exact_sum"))
            or case.get("unadjusted_GAAP_total_not_continuing_or_normalized") is not True
            or [r["observation_id"] for r in company["input_refs"] if r["kind"] == "XBRL_ANALYTICAL"] != case.get("original_XBRL_observation_ids")
            or [r["observation_id"] for r in company["input_refs"] if r["kind"] == "OFFICIAL_REPORTED_HTML_TABLE"] != case.get("original_HTML_source_ids")):
            raise ValueError("plan differs from exact reviewed EPS company/inputs/basis/window")
        candidates = []
        for index in pools.values():
            candidates.extend(r for r in index.values() if r.get("cik") == cik and r.get("input_id") == "reported_eps_diluted_total")
        unique = {}
        for r in candidates:
            oid = r["observation_id"]
            if oid in unique and unique[oid] != r:
                raise ValueError("conflicting quarterly source records")
            unique[oid] = r
        selected = []
        for ref in company["input_refs"]:
            index = pools.get((ref["source_pin"]["path"], ref["source_pin"]["sha256"]))
            original = index.get(ref["observation_id"]) if index is not None else None
            if original is None or identity(original) != ref["record_sha256"]:
                raise ValueError("exact quarterly source record hash differs")
            row = _reported_html(original) if ref["kind"] == "OFFICIAL_REPORTED_HTML_TABLE" else copy.deepcopy(original)
            if ref["kind"] not in {"XBRL_ANALYTICAL", "OFFICIAL_REPORTED_HTML_TABLE"}:
                raise ValueError("unsupported quarterly source kind")
            if (row["cik"] != cik or row["start"] != ref["period_start"] or row["end"] != ref["period_end"]
                or row.get("filed_date", "9999") > cutoff):
                raise ValueError("quarterly identity/period/public cutoff differs")
            if ref["kind"] == "XBRL_ANALYTICAL":
                refs = [original.get("source", {}), *original.get("analysis_references", [])]
                for source in refs:
                    if source.get("analysis_manifest"):
                        pinned_json(source["analysis_manifest"])
            source_records[row["observation_id"]] = {"input_ref": ref, "original_record": original,
                "reported_comparison_record": row, "physical_scope_preserved": True}
            if row.get("actual_captured_at"):
                latest_source_times.append(aware(row["actual_captured_at"]))
            unique[row["observation_id"]] = row
            selected.append(row)
        mapping = company["scope_mapping"]
        ids = [r["observation_id"] for r in selected]
        if (len(ids) != 4 or len(set(ids)) != 4 or mapping.get("version") != "EXACT_REVIEWED_SOURCE_SCOPE_V1"
            or mapping.get("input_ids") != ids or mapping.get("basis_status") != "COMPATIBLE_NO_RESCALE"
            or not mapping.get("target_eps_scope_id") or plan["source_review"] not in mapping.get("evidence_pins", [])):
            raise ValueError("exact reviewed EPS scope mapping required")
        for pin in mapping["evidence_pins"]:
            pinned_json(pin)
        # Physical HTML null and XBRL dimensions are not a winner policy. A
        # different selected-source identity in the same actual quarter requires
        # a separate exact equivalence review before either may be chosen.
        for row in selected:
            competitors = [r for r in unique.values() if r.get("start") == row["start"]
                           and r.get("end") == row["end"] and r.get("filed_date", "9999") <= cutoff]
            if {r["observation_id"] for r in competitors} != {row["observation_id"]}:
                raise ValueError("AMBIGUOUS_DIRECT_QUARTER_REVIEWED_SCOPE")
        declared = {"cik": cik, "currency": company["currency"], "stock_class_id": company["stock_class_id"],
                    "basis_id": mapping["target_eps_scope_id"], "available_on": aware(approval["approved_at"]).date().isoformat(),
                    "observation_ids": ids, "source_pins": mapping["evidence_pins"]}
        result = _derive_market_eps_ttm_core(list(unique.values()), cik=cik, financial_as_of=cutoff,
            declaration=declared, reviewed_scope_keys={oid: mapping["target_eps_scope_id"] for oid in ids},
            basis_as_of=decision["evaluation_as_of"])
        if (result["status"] != "AVAILABLE_DERIVED_SEPARATE" or result["end"] != company["target_anchor"]
            or result["start"] != company["window_start"]
            or finite(result["value"]) != finite(company["expected_value"])):
            raise ValueError("approved four-quarter mechanics differ: " + str(result.get("reason")))
        anchor = max(a["period_end"] for a in base["financial_anchors"] if a["cik"] == cik and a["known_on"] <= cutoff)
        grants = [g for g in base["compatibility_grants"] if g["cik"] == cik and g["financial_anchor"] == anchor]
        if len(grants) != 1 or anchor != company["target_anchor"]:
            raise ValueError("TTM target is not the exact latest financial grant")
        grant = grants[0]
        if any(company[k] != grant[g] for k, g in (("security_id", "security_id"), ("currency", "currency"),
            ("stock_class_id", "stock_class_id"), ("split_basis_id", "split_basis_id"), ("scope_id", "financial_scope_id"))):
            raise ValueError("TTM current class/currency/split/scope differs")
        known = max(r["filed_date"] for r in selected)
        outputs.append({"role": "diluted_eps_12m", "cik": cik, "ticker": company["ticker"],
            "currency": company["currency"], "scope_id": company["scope_id"], "stock_class_id": company["stock_class_id"],
            "split_basis_id": company["split_basis_id"], "known_on": known, "period_start": result["start"],
            "period_end": result["end"], "period_class": "TTM", "end_convention": "EXCLUSIVE",
            "value": result["value"], "unit_kind": "currency/share", "status": "AVAILABLE", "reason": None,
            "source_kind": "GOVERNED_DIRECT_QTD_TTM", "reported_or_derived": "DERIVED", "definition_version": RULE,
            "formula_id": RULE, "formula": result["formula"], "reviewed_scope_mapping": mapping,
            "source_refs": [{"observation_id": r["observation_id"], "value": r["value"], "period_start": r["start"],
                             "period_end": r["end"], "source_ref": "reported_quarter_sources"} for r in selected],
            "evidence_pins": [config["plan"], config["approval"]], "historical_ready": False})
    stamp = _recorded_at or _now().isoformat()
    ready = aware(stamp)
    if ready > _now() or ready < max(latest_source_times) or ready.date().isoformat() != decision["evaluation_as_of"]:
        raise ValueError("TTM actual readiness is future/before sources/outside approved evaluation day")
    for row in outputs:
        row.update(ready_at=stamp, ready_on=ready.date().isoformat())
        row["observation_id"] = "price-financial-input-" + identity(row)
    for hold in plan.get("holds", []):
        for pin in hold["evidence_pins"]:
            pinned_json(pin)
    return {"schema_version": "governed-direct-quarter-eps-ttm-v1", "rule_version": RULE,
            "config": config_pin, "prepared_at": stamp, "public_cutoff": cutoff, "quote_session": plan["quote_session"],
            "observations": outputs, "reported_quarter_sources": source_records, "holds": plan.get("holds", [])}


def verify_ttm(pin: dict) -> dict:
    data = pinned_json(pin)
    if data.get("schema_version") != "governed-direct-quarter-eps-ttm-v1":
        raise ValueError("unsupported governed EPS TTM artifact")
    if prepare_ttm(data["config"], _recorded_at=data["prepared_at"]) != data:
        raise ValueError("governed EPS TTM artifact differs from exact approved derivation")
    return data


def validated_ttm_rows(bundle: dict) -> dict[str, dict]:
    """Admit only exact replayed EPS rows; all other financial roles stay upstream."""
    governed = [r for r in bundle.get("observations", []) if r.get("source_kind") == "GOVERNED_DIRECT_QTD_TTM"]
    pin = bundle.get("reported_quarter_derivation")
    if not pin:
        if governed:
            raise ValueError("governed quarter EPS requires exact derivation evidence")
        return {}
    artifact = verify_ttm(pin)
    expected = {r["observation_id"]: r for r in artifact["observations"]}
    if len(governed) != len(expected) or {r["observation_id"]: r for r in governed} != expected:
        raise ValueError("bundle EPS differs from approved quarter derivation")
    for row in governed:
        anchors = [a["period_end"] for a in bundle["financial_anchors"]
                   if a["cik"] == row["cik"] and a["known_on"] <= artifact["public_cutoff"]]
        if not anchors or max(anchors) != row["period_end"] or row["role"] != "diluted_eps_12m":
            raise ValueError("governed EPS is not at the current company anchor")
        grants = [g for g in bundle["compatibility_grants"] if g["cik"] == row["cik"]
                  and g["financial_anchor"] == row["period_end"]]
        if len(grants) != 1 or grants[0]["input_ids"].get("diluted_eps_12m") != row["observation_id"]:
            raise ValueError("governed EPS lacks its exact current grant")
        if any(row[k] != grants[0][g] for k, g in (("currency", "currency"), ("stock_class_id", "stock_class_id"),
            ("split_basis_id", "split_basis_id"), ("scope_id", "financial_scope_id"))):
            raise ValueError("governed EPS current scope differs")
    return expected


def validate_current_evaluation(declaration: dict, *, bundle_pin: dict,
                                batch_pin: dict, requested: str, selected: str) -> dict:
    """Verify an exact opt-in policy before current-only readiness is evaluated."""
    policy, approval = pinned_json(declaration["policy"]), pinned_json(declaration["approval"])
    if (policy.get("schema_version") != "eps-current-evaluation-policy-v1" or policy.get("mode") != MODE
        or approval.get("schema_version") != "eps-current-evaluation-root-acceptance-v1"
        or approval.get("reviewer") != "ROOT" or approval.get("status") != "APPROVED_FOR_EXACT_CURRENT_EVALUATION"
        or approval.get("policy") != declaration["policy"] or policy.get("financial_inputs") != bundle_pin
        or policy.get("price_batch") != batch_pin or policy.get("quote_session") != selected
        or policy.get("public_financial_information_cutoff") != selected or policy.get("evaluation_as_of") != requested):
        raise ValueError("exact current EPS evaluation policy differs")
    decision = pinned_json(policy["decision"])
    if (decision.get("reviewer") != "ROOT" or decision.get("status") != "APPROVED_FOR_BOUNDED_IMPLEMENTATION"
        or any(policy.get(k) != decision.get(k) for k in ("mode", "quote_session", "evaluation_as_of", "public_financial_information_cutoff"))):
        raise ValueError("current evaluation differs from ROOT decision")
    bundle = pinned_json(bundle_pin)
    rows = validated_ttm_rows(bundle)
    if bundle.get("reported_quarter_derivation") != policy.get("derivation") or not rows:
        raise ValueError("current evaluation derivation differs")
    artifact = verify_ttm(policy["derivation"])
    plan = pinned_json(pinned_json(artifact["config"])["plan"])
    if plan["evaluation_decision"] != policy["decision"]:
        raise ValueError("evaluation decision differs from derived EPS plan")
    evaluated = aware(policy["evaluation_at"])
    if (evaluated > _now() or evaluated.date().isoformat() != requested
        or evaluated < aware(artifact["prepared_at"]) or aware(approval["approved_at"]) > _now()
        or evaluated < aware(decision["decided_at"])):
        raise ValueError("actual current evaluation time is future/before readiness/outside approved day")
    return {"mode": MODE, "evaluation_as_of": requested, "evaluation_at": policy["evaluation_at"],
            "quote_session": selected, "public_financial_information_cutoff": selected,
            "policy": declaration["policy"], "approval": declaration["approval"],
            "derivation": policy["derivation"], "input_ids": sorted(rows), "backtest_eligible": False}
