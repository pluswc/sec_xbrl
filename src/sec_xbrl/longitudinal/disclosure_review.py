"""Exact-source disclosure interpretation and separately approved Q4 publication.

Approval is an append-only decision on an immutable candidate, never a company
wide tag replacement. This producer performs policy; the reader only loads its
persisted Analytical / Derived records alongside the immutable parent panels.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sec_xbrl.facts.layer1 import _stable_id
from sec_xbrl.history import HistoryPublicationReader, _write_records

VERSION = "disclosure-review-v1"
DECISION_FIELDS = ("decision_id", "previous_decision_id", "candidate_id", "action",
                   "reviewer", "reason", "known_at")
SCOPE_FIELDS = ("accession", "source_snapshot_id", "source_filing_id", "selected_source_fact_id",
                "raw_concept_id", "context_id", "unit_id", "raw_dimension_signature",
                "context_start_date", "context_end_date", "context_instant_date",
                "unit_numerator_measures", "unit_denominator_measures", "value_numeric")


def candidate_record(record: dict) -> dict:
    """Restore discriminated records after Parquet's nullable union columns."""
    fields = ("kind", "ticker", "source_view", "source_cell_id", "source_row_id", "scope", "period_class",
              "fiscal_year", "fiscal_quarter", "column_id", "target_dimensions", "basis_version", "evidence",
              "corroboration", "resolved_issue_ids", "candidate_id") if record["kind"] == "A" else (
                  "kind", "ticker", "annual_candidate_id", "ytd_candidate_id", "formula", "value_kind", "evidence", "candidate_id")
    if record["kind"] not in {"A", "B"} or any(k not in record for k in fields):
        raise ValueError("invalid candidate kind/schema")
    if any(k not in fields and v is not None for k, v in record.items()):
        raise ValueError("unexpected candidate field")
    return {k: record[k] for k in fields}


def identity(value: Any) -> str:
    """Small candidate/scope identity, not a serialization of the whole corpus."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("review timestamps require a timezone")
    return result


@lru_cache(maxsize=24)
def _document(path: str, mtime: int, size: int):
    from lxml import etree
    file = Path(path)
    return (etree.parse(str(file), etree.XMLParser(resolve_entities=False, no_network=True)),
            hashlib.sha256(file.read_bytes()).hexdigest())


def document(file: Path):
    stat = file.stat()
    return _document(str(file.absolute()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _package_member(package: str, mtime: int, size: int, member: str) -> tuple[str, str]:
    path = Path(package)
    package_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name == member]
        if len(names) != 1:
            raise ValueError("source document not unique in original package")
        member_digest = hashlib.sha256(archive.read(names[0])).hexdigest()
    return package_digest, member_digest


def source_evidence(*, file: Path, inline_fact_id: str, lineage: dict,
                    raw_fact: dict, concepts: dict, package_zip: Path) -> dict:
    """Validate an exact visible table cell against its immutable raw Fact.

    Parsing is evidence collection only. No label is automatically approved.
    Unknown transformations and ambiguous/hidden/non-table facts fail closed.
    """
    from lxml import etree
    tree, digest = document(file)
    stat = package_zip.stat()
    package_digest, member_digest = _package_member(str(package_zip.absolute()), stat.st_mtime_ns, stat.st_size, raw_fact["source_document"])
    if package_digest != raw_fact["source_package_sha256"] or member_digest != digest:
        raise ValueError("source display file is not the original Layer1 package member")
    matches = tree.xpath('//*[@id=$id]', id=inline_fact_id)
    if len(matches) != 1:
        raise ValueError("inline fact locator is ambiguous or missing")
    fact = matches[0]
    # Layer1 IDs include the Arelle corpus ordinal. Search the manifest-bounded
    # ordinal domain, not guessed DOM order (tuples can leave ordinal gaps).
    # This binds the precise inline ID even if several facts share semantics.
    count = raw_fact.get("source_fact_count")
    if not isinstance(count, int) or count < 1 or not any(
            _stable_id("fact", lineage["source_filing_id"], inline_fact_id,
                       raw_fact.get("source_locator") or "", ordinal) == raw_fact.get("fact_id")
            for ordinal in range(count)):
        raise ValueError("inline ID does not bind to the selected raw Fact ID")
    if etree.QName(fact).localname != "nonFraction" or any(
            etree.QName(p).localname == "hidden" for p in fact.iterancestors()):
        raise ValueError("visible numeric inline fact required")
    if fact.get("format", "").split(":")[-1] not in {"", "num-dot-decimal", "numdotdecimal"}:
        raise ValueError("unsupported inline transformation needs evidence review")
    context_ref = fact.get("contextRef")
    if _stable_id("context", lineage["source_filing_id"], context_ref) != raw_fact["context_id"]:
        raise ValueError("inline Context does not bind to raw Fact")
    if fact.get("name") != lineage["raw_concept_qname"] or raw_fact["raw_concept_id"] != lineage["raw_concept_id"]:
        raise ValueError("inline Concept does not bind to raw Fact")
    value = Decimal("".join(fact.itertext()).replace(",", "").strip())
    value *= Decimal(10) ** int(fact.get("scale", "0"))
    value *= -1 if fact.get("sign") == "-" else 1
    if value != Decimal(raw_fact["value_numeric"]) or value != Decimal(lineage["value_numeric"]):
        raise ValueError("inline number does not equal raw selected number")
    contexts = tree.xpath('//*[local-name()="context" and @id=$id]', id=context_ref)
    if len(contexts) != 1:
        raise ValueError("ambiguous inline Context")
    explicit = sorted((e.get("dimension"), e.text) for e in contexts[0].xpath('.//*[local-name()="explicitMember"]'))
    expected = sorted((concepts[d[0]]["qname"], concepts[d[1]]["qname"])
                      for d in lineage["raw_dimension_signature"] if d[3] == "EXPLICIT")
    if explicit != expected or contexts[0].xpath('.//*[local-name()="typedMember"]'):
        raise ValueError("full dimensions do not match (typed evidence requires separate review)")
    start = contexts[0].xpath('string(.//*[local-name()="startDate"])')
    end = contexts[0].xpath('string(.//*[local-name()="endDate"])')
    if start != lineage["context_start_date"] or (date.fromisoformat(end) + timedelta(days=1)).isoformat() != lineage["context_end_date"]:
        raise ValueError("inline period does not match raw period")
    units = tree.xpath('//*[local-name()="unit" and @id=$id]', id=fact.get("unitRef"))
    if len(units) != 1 or units[0].xpath('.//*[local-name()="divide"]'):
        raise ValueError("unsupported evidence Unit")
    measures = sorted(e.text for e in units[0].xpath('.//*[local-name()="measure"]'))
    if measures != sorted(json.loads(lineage["unit_numerator_measures"])) or json.loads(lineage["unit_denominator_measures"]):
        raise ValueError("inline Unit differs from raw Unit")
    tr = next((p for p in fact.iterancestors() if etree.QName(p).localname == "tr"), None)
    table = next((p for p in fact.iterancestors() if etree.QName(p).localname == "table"), None)
    if tr is None or table is None:
        raise ValueError("source is not a table observation")
    cells = tr.xpath('./*[local-name()="td" or local-name()="th"]')
    label = " ".join("".join(cells[0].itertext()).split())
    return {"source_file": str(file.absolute()), "source_file_sha256": digest,
            "source_package_zip": str(package_zip.absolute()), "source_package_sha256": package_digest,
            "inline_fact_id": inline_fact_id, "context_ref": context_ref,
            "table_locator": tree.getpath(table), "fact_locator": tree.getpath(fact),
            "display_label": label, "row_text": " ".join("".join(tr.itertext()).split()),
            "context_start": start, "context_end_inclusive": end,
            "decimals": raw_fact.get("decimals"), "validation": "RAW_FACT_BOUND"}


def interpretation_candidate(*, ticker: str, view: str, cell: dict, row: dict,
                             column: dict, evidence: dict, target_dimensions: list,
                             basis_version: str, resolved_issue_ids: list[str] | None = None,
                             corroboration: str) -> dict:
    """Prepare a reviewable exact-fact candidate; does not approve it."""
    lineage = cell["value_lineage"]
    if cell["value_status"] != "REPORTED" or not evidence.get("validation") == "RAW_FACT_BOUND":
        raise ValueError("interpretation requires a reported raw-bound observation")
    if not basis_version or not corroboration or not target_dimensions:
        raise ValueError("reviewed basis, dimensions and corroborating evidence are required")
    if len(target_dimensions) != len(lineage["raw_dimension_signature"]):
        raise ValueError("interpretation must retain every dimension; hierarchy restructuring needs separate contract")
    if len({d[0] for d in target_dimensions}) != len(target_dimensions) or any(len(d) != 5 for d in target_dimensions):
        raise ValueError("invalid full target dimensions")
    result = {"kind": "A", "ticker": ticker, "source_view": view,
              "source_cell_id": cell["fiscal_time_series_cell_id"],
              "source_row_id": row["fiscal_time_series_row_id"],
              "scope": {k: lineage.get(k) for k in SCOPE_FIELDS},
              "period_class": column["period_class"], "fiscal_year": column["fiscal_year"],
              "fiscal_quarter": column["fiscal_quarter"], "column_id": column["fiscal_time_series_column_id"],
              "target_dimensions": sorted(target_dimensions), "basis_version": basis_version,
              "evidence": evidence, "corroboration": corroboration,
              "resolved_issue_ids": resolved_issue_ids or []}
    result["candidate_id"] = identity(result)
    return result


def q4_candidate(*, annual: dict, ytd: dict, evidence: str) -> dict:
    """Prepare B candidate with exact independently approved A inputs."""
    if not evidence:
        raise ValueError("Q4 comparability evidence required")
    result = {"kind": "B", "ticker": annual["ticker"], "annual_candidate_id": annual["candidate_id"],
              "ytd_candidate_id": ytd["candidate_id"], "formula": "FY - YTD_9M",
              "value_kind": "ADDITIVE_AMOUNT", "evidence": evidence}
    result["candidate_id"] = identity(result)
    return result


def effective_decisions(decisions: list[dict], candidates: list[dict], *, as_of: datetime,
                        previous: list[dict] = ()) -> dict[str, dict]:
    """Resolve immutable chains, including withdrawal and actual same-day times."""
    if as_of.tzinfo is None:
        raise ValueError("review as-of requires a timezone")
    candidate_ids = {c["candidate_id"] for c in candidates}
    for candidate in candidates:
        candidate_record(candidate)
    if len(candidate_ids) != len(candidates) or any(identity({k: v for k, v in c.items() if k != "candidate_id"}) != c["candidate_id"] for c in candidates):
        raise ValueError("candidate changed after preparation")
    by_id = {d["decision_id"]: d for d in decisions}
    if len(by_id) != len(decisions) or any(by_id.get(d["decision_id"]) != d for d in previous):
        raise ValueError("published decisions cannot be changed/deleted")
    grouped: dict[str, list[dict]] = {}
    for decision in decisions:
        if decision["candidate_id"] not in candidate_ids or any(not decision.get(k) for k in ("decision_id", "reviewer", "reason", "known_at")):
            raise ValueError("decision requires current candidate, reviewer, reason and time")
        if decision["action"] not in {"APPROVE", "REJECT", "MORE_EVIDENCE", "WITHDRAW"}:
            raise ValueError("unsupported decision action")
        timestamp(decision["known_at"])
        grouped.setdefault(decision["candidate_id"], []).append(decision)
    active = {}
    for candidate_id, chain in grouped.items():
        chain.sort(key=lambda d: timestamp(d["known_at"]))
        predecessor = ""
        last_time = None
        for decision in chain:
            current = timestamp(decision["known_at"])
            if decision.get("previous_decision_id", "") != predecessor or current == last_time:
                raise ValueError("decision chain predecessor/time conflict")
            if not predecessor and decision["action"] == "WITHDRAW":
                raise ValueError("cannot withdraw a nonexistent decision")
            if current <= as_of:
                active[candidate_id] = decision
            predecessor, last_time = decision["decision_id"], current
    return active


def _q4_gate(annual: dict, ytd: dict, candidates: dict, b: dict) -> str | None:
    a, y = candidates[b["annual_candidate_id"]], candidates[b["ytd_candidate_id"]]
    if b.get("formula") != "FY - YTD_9M" or b.get("value_kind") != "ADDITIVE_AMOUNT" or b["ticker"] != a["ticker"]:
        return "Q4_INVALID_POLICY_SCOPE"
    if a["period_class"] != "FY" or y["period_class"] != "YTD_9M":
        return "Q4_WRONG_PERIOD_CLASS"
    if any(a[k] != y[k] for k in ("ticker", "target_dimensions", "basis_version", "fiscal_year")):
        return "Q4_INCOMPATIBLE_REVIEWED_SCOPE"
    al, yl = annual["value_lineage"], ytd["value_lineage"]
    for key in ("company_canonical_concept_id", "unit_numerator_measures", "unit_denominator_measures", "context_start_date"):
        if not al.get(key) or al[key] != yl.get(key):
            return "Q4_INCOMPATIBLE_INPUTS"
    if al.get("raw_concept_period_type") != "duration" or yl.get("raw_concept_period_type") != "duration":
        return "Q4_NOT_DURATION"
    if any(l.get("raw_concept_data_type") != "xbrli:monetaryItemType" for l in (al, yl)):
        return "Q4_NOT_MONETARY"
    numerator = json.loads(al["unit_numerator_measures"])
    if len(numerator) != 1 or not numerator[0].startswith("iso4217:") or json.loads(al["unit_denominator_measures"]):
        return "Q4_NON_ADDITIVE_UNIT"
    if any(re.search(r"pershare|earningspershare|average|ratio|margin|percent", l["raw_concept_qname"], re.IGNORECASE) for l in (al, yl)):
        return "Q4_NON_ADDITIVE_CONCEPT"
    start, fy_end, ytd_end = map(date.fromisoformat, (al["context_start_date"], al["context_end_date"], yl["context_end_date"]))
    if not (350 <= (fy_end-start).days <= 378 and 250 <= (ytd_end-start).days <= 287 and 75 <= (fy_end-ytd_end).days <= 105):
        return "Q4_FISCAL_TRANSITION_OR_BOUNDARY_MISMATCH"
    if any(l.get("ledger_lineage", {}).get("ledger_is_amendment") for l in (al, yl)):
        return "Q4_AMENDMENT_BASIS_REVIEW_REQUIRED"
    return None


def raw_index(reader: HistoryPublicationReader, ticker: str) -> tuple[dict, dict]:
    from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
    intake = json.loads(Path(reader.manifest["source_intake"]).read_text())
    concepts, facts = {}, {}
    for entry in intake["filings"]:
        if entry["ticker"] != ticker:
            continue
        ref = entry["filing"]
        snapshot = _load_declared_cohort_snapshot(Path(entry["source_run"]) / "snapshots" / ref["cik"] / ref["accession"].replace("-", ""), ref["cik"], ref["accession"])
        concepts.update({r["raw_concept_id"]: r for r in snapshot.records("concept")})
        facts.update({r["fact_id"]: {**r, "source_package_sha256": snapshot.manifest.package_sha256,
                                    "source_fact_count": snapshot.manifest.source_fact_count,
                                    "source_cik": ref["cik"], "source_accession": ref["accession"]}
                      for r in snapshot.records("fact")})
    return concepts, facts


def effective_quality(rows: list[dict], as_of: datetime) -> dict[str, dict]:
    active, identities, scopes, times = {}, set(), {}, set()
    for q in sorted(rows, key=lambda q: timestamp(q["known_at"] if len(q["known_at"]) > 10 else q["known_at"] + "T00:00:00+09:00")):
        known = timestamp(q["known_at"] if len(q["known_at"]) > 10 else q["known_at"] + "T00:00:00+09:00")
        scope = tuple(q[k] for k in ("ticker", "accession", "concept", "axis", "member"))
        if q["decision_id"] in identities or (q["issue_id"], known) in times or q["decision"] not in {"WARN", "BLOCK", "RELEASE"}:
            raise ValueError("invalid quality decision identity/time/action")
        if q["issue_id"] in scopes and scopes[q["issue_id"]] != scope:
            raise ValueError("quality issue scope changed")
        if q["decision"] == "RELEASE" and q["issue_id"] not in scopes:
            raise ValueError("quality RELEASE is not interpretation approval")
        identities.add(q["decision_id"])
        scopes[q["issue_id"]] = scope
        times.add((q["issue_id"], known))
        if known <= as_of:
            active[q["issue_id"]] = q
    return active


def publish_review(*, parent: Path, destination: Path, candidates: list[dict],
                   decisions: list[dict], review_as_of: datetime,
                   previous_publication: Path | None = None,
                   quality_decisions: list[dict] = ()) -> Path:
    """Materialize exact-source interpretation and independently approved Q4."""
    if destination.exists():
        raise ValueError("review publication already exists")
    reader = HistoryPublicationReader(parent)
    previous = []
    if previous_publication:
        old = ReviewedPublicationReader(previous_publication)
        previous = list(old.records("decisions"))
        old_candidates = {c["candidate_id"]: c for c in old.records("candidates")}
        new_candidates = {c["candidate_id"]: c for c in candidates}
        if any(new_candidates.get(k) != c for k, c in old_candidates.items()):
            raise ValueError("published candidates cannot be edited/deleted")
    active = effective_decisions(decisions, candidates, as_of=review_as_of, previous=previous)
    quality_active = effective_quality(quality_decisions, review_as_of)
    if previous_publication:
        current_quality = {q["decision_id"]: q for q in quality_decisions}
        if any(current_quality.get(q["decision_id"]) != q for q in old.records("quality_decisions")):
            raise ValueError("published quality decisions cannot change/disappear")
    candidate_index = {c["candidate_id"]: c for c in candidates}
    panels, raw = {}, {}
    interpreted, derived, queue, quarantine = [], [], [], []
    accepted: dict[str, dict] = {}
    approved_sources: set[tuple] = set()
    for candidate in candidates:
        if candidate["kind"] != "A":
            continue
        key = (candidate["ticker"], candidate["period_class"], candidate["source_view"])
        if key not in panels:
            panels[key] = reader.load(ticker=key[0], period_class=key[1], view=key[2])
        panel = panels[key]
        cells = [c for c in panel.cells if c["fiscal_time_series_cell_id"] == candidate["source_cell_id"]]
        if len(cells) != 1 or {k: cells[0]["value_lineage"].get(k) for k in SCOPE_FIELDS} != candidate["scope"]:
            raise ValueError("stale source candidate")
        original = cells[0]
        columns = [c for c in panel.columns if c["fiscal_time_series_column_id"] == original["fiscal_time_series_column_id"]]
        if len(columns) != 1 or any(candidate[k] != columns[0][k] for k in ("period_class", "fiscal_year", "fiscal_quarter")) or candidate["column_id"] != original["fiscal_time_series_column_id"] or candidate["source_row_id"] != original["fiscal_time_series_row_id"]:
            raise ValueError("candidate period/row binding changed")
        evidence = candidate["evidence"]
        if document(Path(evidence["source_file"]))[1] != evidence["source_file_sha256"]:
            raise ValueError("source evidence changed during review")
        if candidate["ticker"] not in raw:
            raw[candidate["ticker"]] = raw_index(reader, candidate["ticker"])
        concepts, facts = raw[candidate["ticker"]]
        raw_fact = facts[original["value_lineage"]["selected_source_fact_id"]]
        if Path(evidence["source_file"]).name != raw_fact["source_document"]:
            raise ValueError("evidence source document mismatch")
        rebound = source_evidence(file=Path(evidence["source_file"]), inline_fact_id=evidence["inline_fact_id"], lineage=original["value_lineage"], raw_fact=raw_fact, concepts=concepts, package_zip=Path(evidence.get("source_package_zip", evidence["source_file"])))
        if rebound != evidence:
            raise ValueError("evidence no longer binds to candidate")
        source_row = next(r for r in panel.rows if r["fiscal_time_series_row_id"] == candidate["source_row_id"])
        rebuilt = interpretation_candidate(ticker=candidate["ticker"], view=candidate["source_view"], cell=original,
                                           row=source_row, column=columns[0], evidence=rebound,
                                           target_dimensions=candidate["target_dimensions"], basis_version=candidate["basis_version"],
                                           resolved_issue_ids=candidate["resolved_issue_ids"], corroboration=candidate["corroboration"])
        if rebuilt != candidate:
            raise ValueError("invalid candidate scope")
        decision = active.get(candidate["candidate_id"], {})
        if decision.get("action") != "APPROVE":
            reason = "INTERPRETATION_" + decision.get("action", "REVIEW_REQUIRED")
            queue.append({"candidate_id": candidate["candidate_id"], "kind": "A", "reason": reason})
            # Persist quarantine independently of successful interpretations.
            # Otherwise a withdrawal could fall through to a mis-tagged raw
            # value in the parent LATEST view, bypassing report-only masking.
            quarantine.append({"ticker": candidate["ticker"], "period_class": candidate["period_class"],
                               "source_fact_id": original["value_lineage"]["selected_source_fact_id"],
                               "candidate_id": candidate["candidate_id"], "decision_id": decision.get("decision_id"),
                               "value_numeric": None, "value_text": None, "value_status": "UNAVAILABLE",
                               "source_type": "UNAVAILABLE", "resolution_reason": reason})
            continue
        if timestamp(decision["known_at"]).date() < date.fromisoformat(original["value_lineage"]["filed_date"]):
            raise ValueError("interpretation approval predates filing")
        source_key = (candidate["ticker"], original["value_lineage"]["selected_source_fact_id"],
                      candidate["basis_version"], candidate["period_class"])
        if source_key in approved_sources:
            raise ValueError("competing approved interpretations of one source Fact in the same basis")
        approved_sources.add(source_key)
        cell = {k: copy.deepcopy(original.get(k)) for k in ("fiscal_time_series_cell_id", "fiscal_time_series_row_id", "fiscal_time_series_column_id", "value_status", "value_numeric", "value_text", "value_lineage", "binding")}
        row_id = "reviewed-row:" + identity((candidate["ticker"], cell["value_lineage"]["company_canonical_concept_id"], candidate["target_dimensions"], candidate["basis_version"], cell["value_lineage"]["unit_numerator_measures"]))[:24]
        cell.update(fiscal_time_series_cell_id="reviewed-cell:" + candidate["candidate_id"], fiscal_time_series_row_id=row_id,
                    comparability_status="REVIEWED_BASIS", comparability_reason=None)
        lineage = cell["value_lineage"]
        lineage.update(interpretation_decision_id=decision["decision_id"], interpretation_candidate_id=candidate["candidate_id"],
                       analytical_fact_id=cell["fiscal_time_series_cell_id"],
                       interpretation_known_at=decision["known_at"], basis_version=candidate["basis_version"],
                       analytical_dimensions=candidate["target_dimensions"], reviewed_source_evidence=evidence,
                       resolved_issue_ids=candidate["resolved_issue_ids"], mapping_review_required=False)
        source_dimensions = [(concepts[d[0]]["qname"], concepts[d[1]]["qname"]) for d in lineage["raw_dimension_signature"]]
        blocks = [q["issue_id"] for q in quality_active.values() if q["decision"] == "BLOCK"
                  and q["ticker"] == candidate["ticker"] and q["accession"] == lineage["accession"]
                  and q["concept"] == lineage["raw_concept_qname"]
                  and (not q["axis"] or (q["axis"], q["member"]) in source_dimensions)
                  and q["issue_id"] not in candidate["resolved_issue_ids"]]
        lineage["unresolved_quality_issue_ids"] = blocks
        if blocks:
            cell.update(value_numeric=None, value_status="UNAVAILABLE", resolution_reason="UNRESOLVED_SOURCE_QUALITY_BLOCK")
            lineage.update(source_type="UNAVAILABLE", reported_source_type="REPORTED")
        record = {"ticker": candidate["ticker"], "period_class": candidate["period_class"],
                  "source_cell_id": candidate["source_cell_id"], "candidate_id": candidate["candidate_id"],
                  "source_fact_id": lineage["selected_source_fact_id"],
                  "row_id": row_id, "cell": cell, "suppress_source": True}
        interpreted.append(record)
        accepted[candidate["candidate_id"]] = cell
    occupied = set()
    for r in interpreted:
        key = (r["ticker"], r["period_class"], r["row_id"], r["cell"]["fiscal_time_series_column_id"])
        if key in occupied:
            raise ValueError("ambiguous approved observations for the same reviewed period")
        occupied.add(key)
    b_keys: dict[tuple, int] = {}
    for b in candidates:
        if b["kind"] == "B" and active.get(b["candidate_id"], {}).get("action") == "APPROVE":
            if b["annual_candidate_id"] not in candidate_index or b["ytd_candidate_id"] not in candidate_index:
                raise ValueError("B references missing A candidate")
            a = candidate_index[b["annual_candidate_id"]]
            key = (a["ticker"], a["fiscal_year"], a["basis_version"], identity(a["target_dimensions"]), a["scope"]["raw_concept_id"])
            b_keys[key] = b_keys.get(key, 0) + 1
    for candidate in candidates:
        if candidate["kind"] != "B":
            continue
        decision = active.get(candidate["candidate_id"], {})
        ids = (candidate["annual_candidate_id"], candidate["ytd_candidate_id"])
        reason = None
        if decision.get("action") != "APPROVE":
            reason = "Q4_CALCULATION_REVIEW_REQUIRED"
        elif not all(i in accepted for i in ids):
            reason = "Q4_INTERPRETATION_NOT_APPROVED"
        elif any(accepted[i]["value_numeric"] is None for i in ids):
            reason = "Q4_INPUT_QUALITY_BLOCKED"
        else:
            reason = _q4_gate(accepted[ids[0]], accepted[ids[1]], candidate_index, candidate)
            if any(timestamp(decision["known_at"]).date() < date.fromisoformat(accepted[i]["value_lineage"]["filed_date"]) for i in ids):
                raise ValueError("calculation approval predates its source filing")
            a = candidate_index[ids[0]]
            key = (a["ticker"], a["fiscal_year"], a["basis_version"], identity(a["target_dimensions"]), a["scope"]["raw_concept_id"])
            if b_keys[key] > 1:
                reason = "Q4_AMBIGUOUS_COMPATIBLE_INPUT_PAIR"
        if reason:
            queue.append({"candidate_id": candidate["candidate_id"], "kind": "B", "reason": reason})
            continue
        annual, ytd = (accepted[i] for i in ids)
        a = candidate_index[ids[0]]
        panel = reader.load(ticker=candidate["ticker"])
        cols = [c for c in panel.columns if c["fiscal_year"] == a["fiscal_year"] and c["fiscal_quarter"] == 4]
        if len(cols) != 1:
            queue.append({"candidate_id": candidate["candidate_id"], "kind": "B", "reason": "Q4_COLUMN_NOT_UNIQUE"})
            continue
        value = str(Decimal(annual["value_numeric"]) - Decimal(ytd["value_numeric"]))
        unreviewed_direct = [c for c in panel.cells if c["value_status"] == "REPORTED"
                             and c["fiscal_time_series_column_id"] == cols[0]["fiscal_time_series_column_id"]
                             and c["value_lineage"].get("company_canonical_concept_id") == annual["value_lineage"]["company_canonical_concept_id"]
                             and c["value_lineage"].get("canonical_dimension_signature") == annual["value_lineage"].get("canonical_dimension_signature")
                             and c["value_lineage"].get("unit_numerator_measures") == annual["value_lineage"]["unit_numerator_measures"]
                             and c["value_lineage"].get("selected_source_fact_id") not in {r["source_fact_id"] for r in interpreted}]
        if unreviewed_direct:
            queue.append({"candidate_id": candidate["candidate_id"], "kind": "B", "reason": "DIRECT_Q4_INTERPRETATION_REQUIRED"})
            continue
        cell = copy.deepcopy(annual)
        lineage = cell["value_lineage"]
        lineage.update(source_type="DERIVED_METRIC", value_status="DERIVED", value_numeric=value,
                       derived_metric_id="reviewed-q4:" + candidate["candidate_id"], metric_id="QUARTERLY_ADDITIVE_FLOW",
                       metric_definition_version=VERSION, calculation_timestamp=datetime.now().astimezone().isoformat(),
                       compatibility_result="COMPATIBLE_INPUTS",
                       context_start_date=ytd["value_lineage"]["context_end_date"], period_class="QTD_3M",
                       formula="FY - YTD_9M", calculation_decision_id=decision["decision_id"],
                       derivation_rule_version=VERSION, source_inputs=[annual["value_lineage"], ytd["value_lineage"]],
                       source_accessions=[annual["value_lineage"]["accession"], ytd["value_lineage"]["accession"]],
                       selected_source_fact_id=None, accession=None,
                       source_analytical_ids=[annual["fiscal_time_series_cell_id"], ytd["fiscal_time_series_cell_id"]])
        cell.update(fiscal_time_series_cell_id="reviewed-q4:" + candidate["candidate_id"],
                    fiscal_time_series_column_id=cols[0]["fiscal_time_series_column_id"],
                    value_status="DERIVED", value_numeric=value)
        key = (candidate["ticker"], "QTD_3M", cell["fiscal_time_series_row_id"], cell["fiscal_time_series_column_id"])
        if key in occupied:
            direct = [r["cell"] for r in interpreted if r["ticker"] == candidate["ticker"] and r["period_class"] == "QTD_3M" and r["row_id"] == cell["fiscal_time_series_row_id"] and r["cell"]["fiscal_time_series_column_id"] == cell["fiscal_time_series_column_id"]]
            precision = [c["value_lineage"]["reviewed_source_evidence"].get("decimals") for c in [annual, ytd, *direct]]
            if any(d is None or (d != "INF" and not re.fullmatch(r"-?\d+", str(d))) for d in precision):
                status = "DIRECT_Q4_PRECISION_REVIEW_REQUIRED"
            else:
                tolerance = sum((Decimal(0) if d == "INF" else Decimal(10) ** -int(d) / 2 for d in precision), Decimal(0))
                status = "DIRECT_Q4_CONFIRMED" if len(direct) == 1 and abs(Decimal(direct[0]["value_numeric"]) - Decimal(value)) <= tolerance else "DIRECT_Q4_CONFLICT"
            if status != "DIRECT_Q4_CONFIRMED":
                for d in direct:
                    d.update(comparability_status="CONFLICT", resolution_reason=status)
            queue.append({"candidate_id": candidate["candidate_id"], "kind": "B", "reason": status})
            continue
        occupied.add(key)
        derived.append({"ticker": candidate["ticker"], "period_class": "QTD_3M", "source_cell_id": None,
                        "candidate_id": candidate["candidate_id"], "row_id": cell["fiscal_time_series_row_id"],
                        "cell": cell, "suppress_source": False})
    staging = destination.parent / (".partial-" + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    tables = {}
    for name, records in (("analytical", interpreted), ("derived", derived), ("quarantine", quarantine), ("review_queue", queue), ("candidates", candidates), ("decisions", decisions), ("quality_decisions", quality_decisions)):
        tables[name] = {"path": name + ".parquet", **_write_records(staging / (name + ".parquet"), tuple(records))}
    manifest = {"version": VERSION, "parent": str(parent.absolute()),
                "availability_policy_version": "inactive-interpretation-quarantine-v1",
                "parent_manifest_sha256": hashlib.sha256((parent / "history_manifest.json").read_bytes()).hexdigest(),
                "review_as_of": review_as_of.isoformat(), "tables": tables}
    (staging / "review_manifest.json").write_text(json.dumps(manifest, indent=2))
    staging.rename(destination)
    return destination


class ReviewedPublicationReader:
    """Read-only composition of persisted records; never approval or arithmetic."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink() or root.name.startswith(".partial-"):
            raise ValueError("unpublished review data")
        self.review_root = root
        self.review_manifest = json.loads((root / "review_manifest.json").read_text())
        if self.review_manifest["version"] != VERSION:
            raise ValueError("unsupported review publication")
        self.parent = HistoryPublicationReader(Path(self.review_manifest["parent"]))
        self.root, self.manifest = self.parent.root, self.parent.manifest
        if hashlib.sha256((self.root / "history_manifest.json").read_bytes()).hexdigest() != self.review_manifest["parent_manifest_sha256"]:
            raise ValueError("review parent publication changed")

    def records(self, name: str) -> tuple[dict, ...]:
        proxy = object.__new__(HistoryPublicationReader)
        proxy.root = self.review_root
        records = proxy._records(self.review_manifest["tables"][name])
        return tuple(candidate_record(r) for r in records) if name == "candidates" else records

    def load(self, *, ticker: str, period_class: str = "QTD_3M", view: str = "LATEST_REPORTED"):
        from sec_xbrl.analytics import FiscalTimeSeriesResult
        base = self.parent.load(ticker=ticker, period_class=period_class, view=view)
        if view != "LATEST_REPORTED":
            return base  # Raw/as-filed consumer remains unchanged.
        if "quarantine" not in self.review_manifest["tables"]:
            raise ValueError("legacy reviewed publication requires republication with persisted quarantine")
        additions = [r for name in ("analytical", "derived") for r in self.records(name)
                     if r["ticker"] == ticker.upper() and r["period_class"] == period_class]
        suppressed = {r["source_fact_id"] for r in additions if r["suppress_source"]}
        cells = [c for c in base.cells if c.get("value_lineage", {}).get("selected_source_fact_id") not in suppressed]
        quarantine = {r["source_fact_id"]: r for r in self.records("quarantine")
                      if r["ticker"] == ticker.upper() and r["period_class"] == period_class}
        cells = [dict(c, value_numeric=q["value_numeric"], value_text=q["value_text"], value_status=q["value_status"],
                      resolution_reason=q["resolution_reason"], comparability_status="REVIEW_REQUIRED",
                      value_lineage={**c["value_lineage"], "source_type": q["source_type"],
                                     "interpretation_quarantine": q})
                 if (q := quarantine.get(c.get("value_lineage", {}).get("selected_source_fact_id"))) else c for c in cells]
        cells.extend(r["cell"] for r in additions)
        rows = [dict(r, raw_tag_view=True) for r in base.rows]
        seen = set()
        for record in additions:
            if record["row_id"] in seen:
                continue
            seen.add(record["row_id"])
            lineage = record["cell"]["value_lineage"]
            rows.append({"fiscal_time_series_row_id": record["row_id"],
                         "raw_concept_qname": lineage["raw_concept_qname"],
                         "company_canonical_concept_id": lineage["company_canonical_concept_id"],
                         "canonical_dimension_signature": lineage["analytical_dimensions"],
                         "line_class": "COMMON_GAAP" if lineage["raw_concept_is_standard"] else "COMPANY_CUSTOM",
                         "mapping_review_required": False, "basis_version": lineage["basis_version"],
                         "reviewed_interpretation": True, "first_definition": {}})
        return FiscalTimeSeriesResult(columns=base.columns, rows=tuple(rows), cells=tuple(cells),
                                      scope={**base.scope, "review_as_of": self.review_manifest["review_as_of"]})


def read_decision_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != DECISION_FIELDS:
            raise ValueError("invalid interpretation decision columns")
        return list(reader)
