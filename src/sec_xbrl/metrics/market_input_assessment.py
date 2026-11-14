"""Read-side assessments over immutable reported inputs, not valuation calculations."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sec_xbrl.metrics.market_inputs import _unit, encoded, finite, pinned_json

REPORTED_12M = "reported_eps_diluted_12m_latest_v1"
CLASS_AXIS = "us-gaap:StatementClassOfStockAxis"
HEADER_QNAMES = {"dei:TradingSymbol", "dei:Security12bTitle", "dei:SecurityExchangeName"}


def latest_financial_anchor(intake: dict, cik: str, cutoff: str) -> dict:
    eligible = [
        e["filing"]
        for e in intake["filings"]
        if e["filing"]["cik"] == cik
        and e["status"] in {"INGESTED", "REUSED"}
        and e["filing"]["form"] in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
        and e["filing"]["filed_date"] <= cutoff
        and e["filing"].get("report_date")
        and e["filing"]["report_date"] <= cutoff
    ]
    if not eligible:
        return {"end": None, "reason": "NO_ELIGIBLE_FINANCIAL_REPORT", "filings": []}
    latest = max(f["report_date"] for f in eligible)
    return {
        "end": (date.fromisoformat(latest) + timedelta(days=1)).isoformat(),
        "report_date": latest,
        "end_convention": "EXCLUSIVE",
        "reason": None,
        "filings": [f for f in eligible if f["report_date"] == latest],
    }


def canonical_dimensions(dimensions: list, concepts: dict) -> list | None:
    """Resolve exact namespaces/QNames; Raw concept IDs are never class identities."""
    result = []
    for dim in dimensions:
        if not isinstance(dim, list) or len(dim) != 5:
            return None
        axis, member, typed, kind, default = dim
        a, m = concepts.get(axis), concepts.get(member) if member is not None else None
        if not a or not a.get("namespace_uri") or not a.get("qname"):
            return None
        if member is not None and (not m or not m.get("namespace_uri") or not m.get("qname")):
            return None
        result.append(
            [
                a["namespace_uri"],
                a["qname"],
                m["namespace_uri"] if m else None,
                m["qname"] if m else None,
                typed,
                kind,
                default,
            ]
        )
    return sorted(result, key=encoded)


def _usd_eps(row: dict) -> bool:
    unit = row.get("unit")
    return (
        row.get("unit_kind") == "USD/share"
        and isinstance(unit, list)
        and len(unit) == 2
        and _unit(
            {"unit_numerator_measures": unit[0], "unit_denominator_measures": unit[1]}, "USD/share"
        )
    )


def _scope(row: dict) -> object:
    dims = row.get("canonical_dimensions")
    if dims is None:
        return None
    return [dims, row.get("unit")]


def _equivalent_groups(rows: list[dict]) -> list[list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        source = row["source"]
        # Only equivalent appearances in one filing/context can consolidate.
        key = encoded(
            [
                source.get("source_snapshot_id"),
                source.get("source_filing_id"),
                source.get("context_id"),
                row.get("namespace"),
                row.get("qname"),
                row.get("start"),
                row.get("end"),
                row.get("period_class"),
                _scope(row),
            ]
        )
        grouped[(key, finite(row.get("value")))].append(row)
    return list(grouped.values())


def assess_reported_12m(rows: list[dict], anchor: dict, cutoff: str) -> dict:
    result = {
        "input_id": REPORTED_12M,
        "status": "UNAVAILABLE",
        "reason": None,
        "value": None,
        "anchor": anchor,
        "observation_ids": [],
        "reported_or_derived": "REPORTED",
    }
    if not anchor.get("end"):
        return dict(result, reason=anchor["reason"])
    eps = [r for r in rows if r["input_id"] == "reported_eps_diluted_total"]
    matching = [
        r
        for r in eps
        if r.get("end") == anchor["end"]
        and r.get("period_class") in {"FY", "TTM"}
        and r.get("status") == "AVAILABLE_REPORTED"
        and r.get("reported_or_derived") == "REPORTED"
        and r.get("filed_date")
        and r["filed_date"] <= cutoff
        and r.get("end_convention") == "EXCLUSIVE"
        and r.get("unit_kind") == "USD/share"
        and finite(r.get("value")) is not None
    ]
    matching = [
        r
        for r in matching
        if r.get("start")
        and 350 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 378
    ]
    if not matching:
        return dict(result, reason="NO_DIRECT_12M_AT_LATEST_FINANCIAL_END")
    if any(not _usd_eps(r) for r in matching):
        return dict(result, reason="UNIT_NOT_COMPATIBLE")
    if any(_scope(r) is None for r in matching):
        return dict(result, reason="DIMENSION_IDENTITY_NOT_CONFIRMED")
    groups = _equivalent_groups(matching)
    if len(groups) != 1:
        return dict(
            result,
            reason="AMBIGUOUS_REPORTED_12M",
            observation_ids=sorted(r["observation_id"] for r in matching),
        )
    row = groups[0][0]
    return {
        **result,
        "status": "AVAILABLE_REPORTED",
        "reason": None,
        "value": row["value"],
        "start": row["start"],
        "end": row["end"],
        "period_class": row["period_class"],
        "canonical_dimensions": row["canonical_dimensions"],
        "unit": row["unit"],
        "positive_for_multiple": finite(row["value"]) > 0,
        "observation_ids": sorted(r["observation_id"] for r in groups[0]),
        "valuation_binding_status": "NOT_ASSESSED",
    }


def _assess_four_quarter_scope(rows: list[dict], anchor: dict, cutoff: str) -> dict:
    result = {
        "rule": "market_eps_diluted_ttm_direct_qtd_v1",
        "financial_input_status": "UNAVAILABLE",
        "reason": None,
        "observation_ids": [],
        "basis_status": "NOT_ASSESSED",
        "value": None,
    }
    if not anchor.get("end"):
        return dict(result, reason=anchor["reason"])
    end = date.fromisoformat(anchor["end"])
    candidates = [
        r
        for r in rows
        if r["input_id"] == "reported_eps_diluted_total"
        and r.get("period_class") == "QTD_3M"
        and r.get("end")
        and 0 <= (end - date.fromisoformat(r["end"])).days < 378
    ]
    if not candidates:
        return dict(result, reason="NO_DIRECT_QTD_EPS")
    direct = [
        r
        for r in candidates
        if r.get("status") == "AVAILABLE_REPORTED"
        and r.get("reported_or_derived") == "REPORTED"
        and r.get("filed_date")
        and r["filed_date"] <= cutoff
        and finite(r.get("value")) is not None
    ]
    periods = defaultdict(list)
    for row in direct:
        periods[(row.get("start"), row["end"])].append(row)
    latest_periods = sorted(periods, key=lambda p: (p[1], p[0] or ""))[-4:]
    if len(latest_periods) != 4 or latest_periods[-1][1] != anchor["end"]:
        return dict(
            result,
            reason="MISSING_DIRECT_QUARTER",
            present_periods=[list(p) for p in latest_periods],
        )
    selected = []
    for period in latest_periods:
        group = _equivalent_groups(periods[period])
        if len(group) != 1:
            return dict(result, reason="AMBIGUOUS_DIRECT_QUARTER")
        selected.append(group[0])
    representatives = [g[0] for g in selected]
    for i, row in enumerate(representatives):
        if (
            not row.get("start")
            or row.get("end_convention") != "EXCLUSIVE"
            or not 75
            <= (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
            <= 105
            or i
            and representatives[i - 1]["end"] != row["start"]
        ):
            return dict(result, reason="QUARTER_GAP")
    if any(_scope(r) is None for r in representatives):
        return dict(result, reason="DIMENSION_IDENTITY_NOT_CONFIRMED")
    if any(not _usd_eps(r) for r in representatives):
        return dict(result, reason="UNIT_NOT_COMPATIBLE")
    if len({encoded(_scope(r)) for r in representatives}) != 1:
        return dict(result, reason="SCOPE_OR_UNIT_NOT_COMPATIBLE")
    return {
        **result,
        "financial_input_status": "FOUR_DIRECT_QUARTERS_PRESENT",
        "reason": "SHARE_BASIS_UNKNOWN",
        "basis_status": "UNKNOWN",
        "observation_ids": sorted(r["observation_id"] for g in selected for r in g),
    }


def assess_four_quarters(rows: list[dict], anchor: dict, cutoff: str) -> dict:
    scopes = defaultdict(list)
    end = date.fromisoformat(anchor["end"]) if anchor.get("end") else None
    for row in rows:
        if (
            row["input_id"] == "reported_eps_diluted_total"
            and row.get("period_class") == "QTD_3M"
            and end is not None
            and row.get("end")
            and 0 <= (end - date.fromisoformat(row["end"])).days < 378
        ):
            scopes[encoded(_scope(row))].append(row)
    if len(scopes) <= 1:
        return _assess_four_quarter_scope(rows, anchor, cutoff)
    series = []
    for scope_rows in scopes.values():
        series.append(
            {
                "canonical_dimensions": scope_rows[0].get("canonical_dimensions"),
                "unit": scope_rows[0].get("unit"),
                **_assess_four_quarter_scope(scope_rows, anchor, cutoff),
            }
        )
    return {
        "rule": "market_eps_diluted_ttm_direct_qtd_v1",
        "financial_input_status": "MULTIPLE_REPORTED_EPS_SCOPES",
        "reason": "SCOPE_SELECTION_REQUIRED",
        "basis_status": "NOT_ASSESSED",
        "value": None,
        "observation_ids": [],
        "series": series,
    }


def _entity_cik(identifier: str) -> str | None:
    match = re.fullmatch(r"https?://www\.sec\.gov/CIK:([0-9]{1,10})", identifier or "")
    return match.group(1).zfill(10) if match else None


def class_identity(dimensions: list | None) -> list | None:
    if dimensions is None:
        return None
    matches = [
        d
        for d in dimensions
        if d[1] == CLASS_AXIS and re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}", d[0])
    ]
    return matches[0] if len(matches) == 1 else None


def link_security_headers(
    *,
    cik: str,
    securities: list[dict],
    filing: dict,
    concepts: dict,
    facts: list[dict],
    contexts: dict,
    dimensions: list[dict],
    source: dict,
) -> list[dict]:
    """All exact same-context header matches survive, including bond contexts."""
    by_context = defaultdict(lambda: defaultdict(list))
    fact_dims = defaultdict(list)
    for dim in dimensions:
        fact_dims[dim["fact_id"]].append(
            [
                dim["axis_raw_concept_id"],
                dim["member_raw_concept_id"],
                dim["typed_member"],
                dim["dimension_type"],
                str(dim["is_default_member"]).lower(),
            ]
        )
    for fact in facts:
        concept = concepts.get(fact["raw_concept_id"], {})
        qname = concept.get("qname")
        context = contexts.get(fact["context_id"], {})
        if (
            qname in HEADER_QNAMES
            and concept.get("is_standard") is True
            and concept.get("taxonomy_family") == "dei"
            and re.fullmatch(
                r"https?://xbrl.sec.gov/dei/[0-9]{4}", concept.get("namespace_uri", "")
            )
            and fact.get("filing_id") == filing["filing_id"]
            and context.get("filing_id") == filing["filing_id"]
            and _entity_cik(context.get("entity_identifier")) == cik
            and not fact.get("is_nil")
            and fact.get("value_text")
        ):
            by_context[fact["context_id"]][qname].append(fact)
    links = []
    for security in securities:
        if security["cik"] != cik:
            continue
        for context_id, roles in by_context.items():
            symbols = [
                f
                for f in roles["dei:TradingSymbol"]
                if f["value_text"].strip() == security["ticker"]
            ]
            if not symbols:
                continue
            dims = canonical_dimensions(fact_dims[symbols[0]["fact_id"]], concepts)
            coherent = all(
                canonical_dimensions(fact_dims[f["fact_id"]], concepts) == dims
                for values in roles.values()
                for f in values
            )
            titles = sorted({f["value_text"].strip() for f in roles["dei:Security12bTitle"]})
            exchanges = sorted({f["value_text"].strip() for f in roles["dei:SecurityExchangeName"]})
            cls = class_identity(dims) if coherent else None
            standard_common = (
                cls is not None
                and any(
                    c.get("namespace_uri") == cls[2]
                    and c.get("qname") == cls[3]
                    and c.get("is_standard") is True
                    and c.get("taxonomy_family") == "us-gaap"
                    for c in concepts.values()
                )
                and re.fullmatch(r"https?://fasb.org/us-gaap/[0-9]{4}", cls[2] or "")
                and cls[3]
                in {
                    "us-gaap:CommonStockMember",
                    "us-gaap:CommonClassAMember",
                    "us-gaap:CommonClassBMember",
                }
            )
            links.append(
                {
                    "security_id": security["security_id"],
                    "ticker": security["ticker"],
                    "context_id": context_id,
                    "context": contexts[context_id],
                    "class_identity": cls,
                    "canonical_dimensions": dims,
                    "raw_dimensions": fact_dims[symbols[0]["fact_id"]],
                    "status": "REPORTED_CLASS_IDENTITY"
                    if cls
                    and coherent
                    and len(titles) == 1
                    and len({f["value_text"].strip() for f in roles["dei:TradingSymbol"]}) == 1
                    else "HEADER_MATCH_CLASS_UNCONFIRMED",
                    "titles": titles,
                    "exchanges": exchanges,
                    "instrument_kind": "COMMON_STOCK" if standard_common else "UNKNOWN",
                    "eps_applicability": "NOT_CONFIRMED",
                    "split_review": "UNKNOWN",
                    "fact_ids": sorted({f["fact_id"] for values in roles.values() for f in values}),
                    "source": source,
                }
            )
    return links


class RawAssessmentTables:
    """Only touched retained tables; no History or complete Raw audit is opened."""

    def __init__(self):
        self.cache = {}
        self.pins = {}

    def records(self, root: Path, name: str, expected: dict | None = None) -> list[dict]:
        import polars as pl

        path = root / (name + ".parquet")
        key = str(path)
        if key not in self.cache:
            if not path.is_absolute() or path.is_symlink():
                raise ValueError("unsafe targeted Raw table")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected is not None and (expected["path"] != key or expected["sha256"] != before):
                raise ValueError("targeted Raw source differs from parent pin")
            records = pl.read_parquet(path).to_dicts()
            if hashlib.sha256(path.read_bytes()).hexdigest() != before:
                raise ValueError("targeted Raw source changed")
            self.cache[key] = records
            self.pins[key] = {"path": key, "sha256": before}
        elif expected is not None and expected != self.pins[key]:
            raise ValueError("conflicting targeted Raw pin")
        return self.cache[key]


def assess_company(
    rows: list[dict],
    securities: list[dict],
    *,
    cik: str,
    financial_as_of: str,
    intake_pin: dict,
    tables: RawAssessmentTables,
) -> dict:
    intake = pinned_json(intake_pin)
    anchor = latest_financial_anchor(intake, cik, financial_as_of)
    entries = {
        e["filing"]["accession"]: e
        for e in intake["filings"]
        if e["filing"]["cik"] == cik
        and e["status"] in {"INGESTED", "REUSED"}
        and e["filing"]["filed_date"] <= financial_as_of
    }
    enriched = []
    for row in rows:
        if row["input_id"] != "reported_eps_diluted_total":
            continue
        copied = dict(row)
        dims = row.get("raw_dimensions")
        if dims == []:
            copied["canonical_dimensions"] = []
        elif isinstance(dims, list) and row["source"].get("accession") in entries:
            entry = entries[row["source"]["accession"]]
            root = (
                Path(entry["source_run"])
                / "snapshots"
                / cik
                / entry["filing"]["accession"].replace("-", "")
            )
            concepts = {r["raw_concept_id"]: r for r in tables.records(root, "concept")}
            copied["canonical_dimensions"] = canonical_dimensions(dims, concepts)
        else:
            copied["canonical_dimensions"] = None
        enriched.append(copied)
    headers = []
    header_entries = [
        e for e in entries.values() if e["filing"]["form"] in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
    ]
    latest_filed = max((e["filing"]["filed_date"] for e in header_entries), default=None)
    retained_cover_sources = {
        r["source"]["raw_manifest"]["path"]: r["source"]
        for r in rows
        if r["input_id"] == "outstanding_common_shares_cover" and r["source"].get("raw_manifest")
    }
    for entry in header_entries:
        ref = entry["filing"]
        if ref["filed_date"] != latest_filed:
            continue
        root = Path(entry["source_run"]) / "snapshots" / cik / ref["accession"].replace("-", "")
        manifest_path = root / "layer1_manifest.json"
        retained = retained_cover_sources.get(str(manifest_path), {})
        manifest_pin = retained.get("raw_manifest") or {
            "path": str(manifest_path),
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
        manifest = pinned_json(manifest_pin)
        if manifest["cik"] != cik or manifest["accession"] != ref["accession"]:
            raise ValueError("header source outside exact issuer/intake")
        pins = retained.get("raw_tables", {})
        filings = tables.records(root, "filing", pins.get("filing"))
        if (
            len(filings) != 1
            or any(
                filings[0].get(k) != ref.get(k) for k in ("cik", "accession", "filed_date", "form")
            )
            or manifest.get("form") != ref["form"]
        ):
            raise ValueError("header filing identity mismatch")
        filing = filings[0]
        concepts = {
            r["raw_concept_id"]: r for r in tables.records(root, "concept", pins.get("concept"))
        }
        facts = tables.records(root, "fact", pins.get("fact"))
        contexts = {
            r["context_id"]: r for r in tables.records(root, "context", pins.get("context"))
        }
        dimensions = tables.records(root, "dimension_fact", pins.get("dimension_fact"))
        source = {
            "intake": intake_pin,
            "raw_manifest": manifest_pin,
            "raw_tables": {
                name: tables.pins[str(root / (name + ".parquet"))]
                for name in ("filing", "concept", "fact", "context", "dimension_fact")
            },
            "source_filing_id": filing["filing_id"],
            "accession": ref["accession"],
            "selection": "LATEST_ELIGIBLE_FILING_ALL_SAME_DAY",
        }
        links = link_security_headers(
            cik=cik,
            securities=securities,
            filing=filing,
            concepts=concepts,
            facts=facts,
            contexts=contexts,
            dimensions=dimensions,
            source=source,
        )
        for link in links:
            cls = link["class_identity"]
            matches = [
                r["observation_id"]
                for r in enriched
                if cls is not None
                and r.get("canonical_dimensions") == link["canonical_dimensions"]
                and r["status"] == "AVAILABLE_REPORTED"
            ]
            link["explicit_class_eps_observation_ids"] = sorted(matches)
            if matches:
                link["eps_applicability"] = "EXPLICIT_CLASS_MATCH_ONLY_BASIS_NOT_APPROVED"
        headers.extend(links)
    return {
        "cik": cik,
        "financial_anchor": anchor,
        "reported_12m": assess_reported_12m(enriched, anchor, financial_as_of),
        "four_quarter_diagnostic": assess_four_quarters(enriched, anchor, financial_as_of),
        "security_header_links": headers,
        "security_status": [
            {
                "security_id": s["security_id"],
                "reason": None
                if any(h["security_id"] == s["security_id"] for h in headers)
                else "NO_EXACT_REPORTED_HEADER_MATCH",
                "eps_applicability": "NOT_APPROVED",
                "split_review": "UNKNOWN",
            }
            for s in securities
            if s["cik"] == cik
        ],
    }
