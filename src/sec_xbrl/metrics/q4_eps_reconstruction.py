"""Offline, evidence-bound Q4 EPS components. Raw and reported EPS remain intact.

The policy is global; accounting evidence binds exact source facts, not tickers or
wanted answers. A numerical match never proves share or numerator accounting.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import importlib
import json
import re
import sys
from collections import OrderedDict, defaultdict
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from lxml import html

from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
from sec_xbrl.metrics.market_inputs import encoded, finite, identity

PRODUCER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_PROPOSAL_CACHE: OrderedDict[str, dict] = OrderedDict()
_DOCUMENT_CACHE: OrderedDict[str, object] = OrderedDict()
_JSON_CACHE: OrderedDict[str, object] = OrderedDict()
_VERIFIED_ARTIFACT_CACHE: OrderedDict[str, dict] = OrderedDict()
_MATCH_CACHE: OrderedDict[tuple, object] = OrderedDict()
_SOURCE_OPERATION: ContextVar[dict | None] = ContextVar("q4_source_operation", default=None)

RULE = "common-q4-eps-components-v1"
SOURCE_KIND = "GOVERNED_Q4_COMPONENT_TTM"
MODE = "CURRENT_EVALUATION_WITH_LAGGED_QUOTE"
ROLES = {
    "EarningsPerShareBasic": "basic_eps",
    "EarningsPerShareDiluted": "diluted_eps",
    "WeightedAverageNumberOfSharesOutstandingBasic": "basic_shares",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "diluted_shares",
    "WeightedAverageNumberOfSharesOutstandingDiluted": "diluted_shares",
    "NetIncomeLossAvailableToCommonStockholdersBasic": "basic_numerator",
    "NetIncomeLossAvailableToCommonStockholdersDiluted": "diluted_numerator",
    "NetIncomeLoss": "parent_numerator",
}
DILUTION_CLAIMS = ("continuing_control", "quarter_loss", "potential_share_population",
                   "treasury_stock", "if_converted", "participating_adjustments")
NUMERATOR_CLAIMS = ("preferred_adjustments", "participating_allocations", "noncontrolling_interests")
FASB = re.compile(r"https?://fasb\.org/us-gaap/(\d{4}(?:-\d{2}-\d{2})?)\Z")


def _source_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _SOURCE_OPERATION.get() is not None:
            return function(*args, **kwargs)
        state = {"pins": {}}
        token = _SOURCE_OPERATION.set(state)
        try:
            result = function(*args, **kwargs)
            for pin in state["pins"].values():
                _bytes(pin)  # Reject a source changed during the operation.
            return result
        finally:
            _SOURCE_OPERATION.reset(token)
    return wrapped


def _verify_once(pin: dict) -> None:
    state = _SOURCE_OPERATION.get()
    key = (pin["path"], pin["sha256"])
    if state is None or key not in state["pins"]:
        _bytes(pin)
        if state is not None:
            state["pins"][key] = pin


def _cache_match(key: tuple, value: object) -> None:
    _MATCH_CACHE[key] = value
    _MATCH_CACHE.move_to_end(key)
    while len(_MATCH_CACHE) > 8192:
        _MATCH_CACHE.popitem(last=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Q4 evidence/ready/evaluation time must be timezone aware")
    return parsed.astimezone(UTC)


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _parts(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _interval(value: str, decimals: object) -> list[Decimal] | None:
    v = finite(value)
    if v is None:
        return None
    if decimals == "INF":
        return [v, v]
    try:
        d = int(str(decimals))
        if str(d) != str(decimals) or not -100 <= d <= 100:
            return None
    except (ValueError, TypeError):
        return None
    radius = Decimal(5).scaleb(-d - 1)
    return [v-radius, v+radius]


def _sub(a: list, b: list) -> list:
    return [a[0]-b[1], a[1]-b[0]]


def _mul(a: list, k: Decimal) -> list:
    return sorted([a[0]*k, a[1]*k])


def _div(a: list, b: list) -> list | None:
    if b[0] <= 0 <= b[1]:
        return None
    xs = [x/y for x in a for y in b]
    return [min(xs), max(xs)]


def _compatible(a: list, b: list) -> bool:
    """Require overlap beyond uncertain rounding boundaries; preserve exact INF points."""
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    if lo < hi:
        return True
    return (a[0] == a[1] and b[0] < a[0] < b[1]
            or b[0] == b[1] and a[0] < b[0] < a[1]
            or a[0] == a[1] == b[0] == b[1])


def _serial(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {k: _serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serial(v) for v in value]
    return value


def _bounds(row: dict) -> list[Decimal] | None:
    iv = row.get("interval")
    return [Decimal(v) for v in iv] if iv else None


def _bytes(pin: dict) -> bytes:
    path = Path(pin["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("Q4 source pin requires a regular absolute path")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin.get("sha256"):
        raise ValueError("Q4 source hash differs")
    state = _SOURCE_OPERATION.get()
    if state is not None:
        state["pins"][(pin["path"], pin["sha256"])] = pin
    return data


def _xpath(node: object) -> str:
    """A literal-colon HTML tag is not an XPath namespace prefix."""
    segments = []
    for element in (node, *node.iterancestors()):
        tag = str(element.tag)
        step = "*[name()='"+tag+"']" if ":" in tag else tag
        parent = element.getparent()
        if parent is not None:
            siblings = [c for c in parent if c.tag == element.tag]
            if len(siblings) > 1:
                step += "["+str(siblings.index(element)+1)+"]"
        segments.append(step)
    return "/"+"/".join(reversed(segments))


def _text(node: object) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _json(pin: dict) -> object:
    """Private read-only parsed input cache; public results are defensive copies."""
    data = _bytes(pin)
    key = pin["sha256"]
    if key in _JSON_CACHE:
        _JSON_CACHE.move_to_end(key)
        return _JSON_CACHE[key]
    value = json.loads(data)
    if len(data) >= 1024*1024:
        _JSON_CACHE[key] = value
        while len(_JSON_CACHE) > 4:
            _JSON_CACHE.popitem(last=False)
    return value


def _recheck_pins(value: object) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            _verify_once(value)
        for child in value.values():
            _recheck_pins(child)
    elif isinstance(value, list):
        for child in value:
            _recheck_pins(child)


def _document(pin: dict) -> object:
    _verify_once(pin)
    key = pin["sha256"]
    if key not in _DOCUMENT_CACHE:
        _DOCUMENT_CACHE[key] = html.fromstring(_bytes(pin))
        while len(_DOCUMENT_CACHE) > 8:
            _DOCUMENT_CACHE.popitem(last=False)
    _DOCUMENT_CACHE.move_to_end(key)
    return _DOCUMENT_CACHE[key]


def _cite(citations: list[dict]) -> None:
    if not citations:
        raise ValueError("accounting claim requires original document citations")
    for citation in citations:
        _verify_once(citation["source_pin"])
        key = ("citation", citation["source_pin"]["sha256"], citation["xpath"], citation.get("expected_text"))
        if key in _MATCH_CACHE:
            _MATCH_CACHE.move_to_end(key)
            continue
        document = _document(citation["source_pin"])
        nodes = document.xpath(citation["xpath"])
        if (len(nodes) != 1 or not hasattr(nodes[0], "itertext")
            or not citation.get("expected_text") or _text(nodes[0]) != citation["expected_text"]):
            raise ValueError("accounting source locator/text differs")
        _cache_match(key, True)


def _official(record: dict) -> dict:
    """Verify a retained official table cell without inventing XBRL identities."""
    document = _document(record["source_pin"])
    loc = record["locator"]
    cells, rows = document.xpath(loc["value_xpath"]), document.xpath(loc["row_xpath"])
    if (len(cells) != 1 or len(rows) != 1 or cells[0] not in rows[0].iterdescendants()
        or _text(cells[0]) != loc["raw_cell_text"] or _text(rows[0]) != loc["row_text"]):
        raise ValueError("official component exact cell/row differs")
    if not _visible(cells[0]):
        raise ValueError("official component source cell is hidden")
    _official_cell_period(record, cells[0], rows[0])
    tables = rows[0].xpath("ancestor::table[1]")
    table = _text(tables[0]) if len(tables) == 1 else ""
    if (hashlib.sha256(table.encode()).hexdigest() != loc["table_text_sha256"]
        or not loc.get("headers") or any(h not in table for h in loc["headers"])):
        raise ValueError("official component table/header differs")
    scale = record.get("scale", 0)
    if not isinstance(scale, int) or not -12 <= scale <= 12:
        raise ValueError("unsupported official component scale")
    value = finite(loc["raw_cell_text"].replace("$", "").replace(",", "").replace("(", "-").replace(")", ""))
    if value is None or value.scaleb(scale) != finite(record["value"]):
        raise ValueError("official component value/scale differs")
    if record["role"] not in set(ROLES.values()) or record["role"] == "parent_numerator":
        raise ValueError("official EPS component requires explicit measurement role")
    for field in ("cik", "ticker", "accession", "form", "filed_date", "report_date", "source_document", "source_url"):
        if not record.get(field):
            raise ValueError("official component provenance missing: " + field)
    if not record["source_url"].startswith("https://www.sec.gov/Archives/"):
        raise ValueError("official component requires a retained SEC source URL")
    _aware(record["captured_at"])
    _days(record["start"], record["end"])
    row = copy.deepcopy(record)
    row.update(fact_key="official:"+record["source_record_id"], source_kind="OFFICIAL_REPORTED_TABLE",
               raw_fact_id=None, namespace=None, qname=None, local_name=None,
               end_convention="EXCLUSIVE")
    return row


def _raw_rows(config: dict, companies: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Reuse the complete atomic Layer 1 verifier, then project a narrow corpus."""
    result, filings, snapshots = [], [], []
    if config.get("base_product_projection"):
        base = _json(config["base_product_projection"])
        _accepted_projection(config["base_product_projection"], config["base_projection_acceptance"], base)
        _verify_projection_closure(base)
        base_config = _json(base["config"])
        previous = {c["cik"]: c for c in _json(base_config["registry"])["companies"]}
        if base["public_cutoff"] != config["public_cutoff"]:
            raise ValueError("source projection reuse cannot change public cutoff")
        unchanged = {c["cik"] for c in companies if previous.get(c["cik"]) == c}
        result = [copy.deepcopy(r) for r in base["source_rows"] if r["cik"] in unchanged and r["source_kind"] == "RAW_XBRL"]
        snapshots = [copy.deepcopy(x) for x in base["snapshots"] if x["snapshot_id"].split(":")[1] in unchanged]
        if base.get("source_filings") is not None:
            filings = [copy.deepcopy(f) for f in base["source_filings"] if f["cik"] in unchanged]
        else:
            # Initial product extraction preceded the optional filing projection.
            # Read only the already hash-verified small filing tables, never facts.
            import polars as pl
            tickers = {c["cik"]: c["ticker"] for c in companies}
            for snapshot in snapshots:
                filing = pl.read_parquet(Path(snapshot["manifest"]["path"]).parent / "filing.parquet").to_dicts()[0]
                filings.append(dict(filing, ticker=tickers[filing["cik"]]))
        companies_to_read = [c for c in companies if c["cik"] not in unchanged]
    else:
        companies_to_read = companies
    seen = {(f["cik"], f["accession"]) for f in filings}
    for company in companies_to_read:
        cik = company["cik"]
        intake = _json(company["intake"])
        if intake.get("complete") is not True:
            raise ValueError("company intake is incomplete")
        for entry in sorted(intake["filings"], key=lambda e: (e["filing"]["filed_date"], e["filing"]["accession"])):
            filing = entry["filing"]
            if filing["cik"] != cik:
                raise ValueError("intake CIK differs from registry")
            if filing["filed_date"] > config["public_cutoff"]:
                continue
            key = (cik, filing["accession"])
            if key in seen:
                raise ValueError("duplicate registered filing")
            seen.add(key)
            directory = Path(entry["source_run"]) / "snapshots" / cik / filing["accession"].replace("-", "")
            snapshot = _load_declared_cohort_snapshot(directory, cik, filing["accession"])
            raw_filing = snapshot.records("filing")[0]
            if any(str(raw_filing.get(k)) != str(filing.get(k)) for k in ("cik", "accession", "form", "filed_date", "report_date")):
                raise ValueError("registered raw filing provenance differs")
            filings.append(dict(raw_filing, ticker=company["ticker"]))
            snapshots.append({"snapshot_id": snapshot.input.snapshot_id,
                              "manifest": {"path": str(snapshot.manifest_path), "sha256": snapshot.input.manifest_sha256},
                              "table_sha256": dict(snapshot.table_sha256)})
            concepts = {r["raw_concept_id"]: r for r in snapshot.records("concept")}
            contexts = {r["context_id"]: r for r in snapshot.records("context")}
            units = {r["unit_id"]: r for r in snapshot.records("unit")}
            dimensions = defaultdict(list)
            for r in snapshot.records("dimension_fact"):
                axis = concepts[r["axis_raw_concept_id"]]
                member = concepts.get(r.get("member_raw_concept_id"), {})
                dimensions[r["fact_id"]].append({"axis": [axis["namespace_uri"], axis["local_name"]],
                    "member": [member.get("namespace_uri"), member.get("local_name")],
                    "typed_member": r.get("typed_member"), "dimension_type": r["dimension_type"],
                    "is_default_member": r.get("is_default_member", False)})
            for fact in snapshot.records("fact"):
                concept = concepts[fact["raw_concept_id"]]
                role = ROLES.get(concept.get("local_name"))
                if not role or finite(fact.get("value_numeric")) is None:
                    continue
                ctx = contexts.get(fact.get("context_id"), {})
                unit = units.get(fact.get("unit_id"), {})
                if not ctx.get("start_date") or not ctx.get("end_date"):
                    continue
                dims = sorted(dimensions[fact["fact_id"]], key=lambda d: encoded(d))
                if len(dims) != ctx.get("dimension_count"):
                    raise ValueError("raw full dimension count differs")
                row = {"cik": cik, "ticker": company["ticker"], "accession": filing["accession"],
                    "form": filing["form"], "filed_date": filing["filed_date"], "report_date": filing["report_date"],
                    "fact_key": snapshot.input.snapshot_id+":"+fact["fact_id"], "raw_fact_id": fact["fact_id"],
                    "source_snapshot_id": snapshot.input.snapshot_id, "raw_concept_id": fact["raw_concept_id"],
                    "context_id": fact["context_id"], "unit_id": fact["unit_id"], "qname": concept["qname"],
                    "namespace": concept["namespace_uri"], "local_name": concept["local_name"],
                    "taxonomy_family": concept.get("taxonomy_family"), "taxonomy_version": concept.get("taxonomy_version"),
                    "label": concept.get("label"), "data_type": concept.get("data_type"),
                    "period_type": concept.get("period_type"), "is_standard": concept.get("is_standard"),
                    "reported_or_derived": fact.get("reported_or_derived"), "role": role,
                    "start": ctx["start_date"], "end": ctx["end_date"], "end_convention": "EXCLUSIVE",
                    "entity_identifier": ctx.get("entity_identifier"), "dimensions": dims,
                    "unit": [_parts(unit.get("numerator_measures")), _parts(unit.get("denominator_measures"))],
                    "value": fact["value_numeric"], "decimals": fact.get("decimals"),
                    "source_document": fact.get("source_document"), "source_locator": fact.get("source_locator"),
                    "source_kind": "RAW_XBRL", "raw_directory": str(directory)}
                result.append(row)
    if config.get("official_components"):
        registered = {c["cik"]: c["ticker"] for c in companies}
        for record in _json(config["official_components"])["records"]:
            row = _official(record)
            if registered.get(row["cik"]) != row["ticker"]:
                raise ValueError("official component is outside registry")
            if row["filed_date"] <= config["public_cutoff"]:
                result.append(row)
    if len({r["fact_key"] for r in result}) != len(result):
        raise ValueError("duplicate source fact identity")
    return sorted(result, key=lambda r: r["fact_key"]), sorted(filings, key=lambda r: (r["cik"], r["accession"])), snapshots


def _source_reason(row: dict, role: str) -> str | None:
    expected = [["iso4217:USD"], ["xbrli:shares"]] if role.endswith("_eps") else (
        [["xbrli:shares"], []] if role.endswith("_shares") else [["iso4217:USD"], []])
    if row["unit"] != expected:
        return "COMPONENT_UNIT_MISMATCH"
    if row["source_kind"] == "RAW_XBRL":
        if (not FASB.fullmatch(row.get("namespace") or "") or row.get("taxonomy_family") != "us-gaap"
            or row.get("is_standard") is not True or row.get("period_type") != "duration"
            or row.get("reported_or_derived") != "REPORTED" or not row.get("data_type")):
            return "OFFICIAL_STANDARD_SEMANTICS_NOT_CONFIRMED"
        entity = str(row.get("entity_identifier", "")).split(":")[-1].zfill(10)
        if entity != row["cik"]:
            return "CONTEXT_ENTITY_MISMATCH"
    return None


def _selection_index(rows: list[dict]) -> dict[tuple, list[dict]]:
    index = defaultdict(list)
    for row in rows:
        index[(row["cik"], row["start"], row["end"], row["role"], encoded(row["dimensions"]))].append(row)
    return dict(index)


def _select(rows: list[dict] | dict[tuple, list[dict]], cik: str, start: str, end: str, role: str, dimensions: list) -> dict:
    found = (list(rows.get((cik, start, end, role, encoded(dimensions)), [])) if isinstance(rows, dict) else
             [r for r in rows if (r["cik"], r["start"], r["end"], r["role"], r["dimensions"])
              == (cik, start, end, role, dimensions)])
    if not found:
        return {"status": "MISSING", "reason": "COMPONENT_NOT_RETAINED", "sources": []}
    # Amendments never silently overwrite original facts in this current policy.
    found = [r for r in found if r["form"] in {"10-K", "10-Q", "8-K"}]
    if not found:
        return {"status": "HOLD", "reason": "AMENDMENT_ONLY_SOURCE", "sources": []}
    latest = max(r["filed_date"] for r in found)
    found = sorted([r for r in found if r["filed_date"] == latest], key=lambda r: r["fact_key"])
    result = {"status": "HOLD", "reason": None, "sources": found}
    reasons = {_source_reason(r, role) for r in found} - {None}
    if reasons:
        return dict(result, reason=min(reasons))
    semantics = {(r["accession"], r["local_name"], encoded(r["unit"]), r.get("namespace")) for r in found}
    if len(semantics) != 1:
        return dict(result, reason="AMBIGUOUS_COMPONENT_SOURCE_IDENTITY")
    intervals = [_interval(r["value"], r.get("decimals")) for r in found]
    if any(iv is None for iv in intervals):
        return dict(result, reason="SOURCE_ROUNDING_PRECISION_UNKNOWN")
    lo, hi = max(iv[0] for iv in intervals), min(iv[1] for iv in intervals)
    if lo > hi:
        return dict(result, reason="CONFLICTING_COMPONENT_DUPLICATES")
    # Precision first, stable identity tie; never choose a point to fit EPS.
    ranked = sorted(zip(found, intervals, strict=True), key=lambda p: (p[1][1]-p[1][0], p[0]["fact_key"]))
    chosen = ranked[0][0]
    point = Decimal(chosen["value"])
    if not lo <= point <= hi:
        return dict(result, reason="DUPLICATE_POINT_OUTSIDE_PRECISION_INTERSECTION")
    return dict(result, status="AVAILABLE", reason=None, value=str(point), interval=[str(lo), str(hi)],
                selected_fact_key=chosen["fact_key"], duplicate_rule="SAME_ACCESSION_SEMANTICS_PRECISION_THEN_IDENTITY")


def _source_keys(components: dict) -> list[str]:
    return sorted({r["fact_key"] for c in components.values() for r in c.get("sources", [])})


@_source_operation
def propose_q4_eps(config_pin: dict) -> dict:
    """Discover every registered company without accounting admission or I/O writes."""
    config = _json(config_pin)
    cache_key = identity(config_pin)
    cached = _PROPOSAL_CACHE.get(cache_key)
    if cached is not None:
        _verify_projection_closure(cached)
        return copy.deepcopy(cached)
    if config.get("schema_version") != "common-q4-eps-config-v1":
        raise ValueError("unsupported Q4 EPS config")
    date.fromisoformat(config["public_cutoff"])
    registry = _json(config["registry"])
    companies = sorted(registry["companies"], key=lambda c: c["cik"])
    if len({c["cik"] for c in companies}) != len(companies) or any(not re.fullmatch(r"\d{10}", c["cik"]) for c in companies):
        raise ValueError("unique canonical registered CIKs required")
    _json(config["base_financial_bundle"])
    rows, filings, snapshots = _raw_rows(config, companies)
    candidates, holds = [], []
    selection_index = _selection_index(rows)
    company_rows = defaultdict(list)
    filing_rows = defaultdict(list)
    for row in rows:
        company_rows[row["cik"]].append(row)
        filing_rows[(row["cik"], row["accession"])].append(row)
    for company in companies:
        cik = company["cik"]
        issuer_rows = company_rows[cik]
        annuals = [f for f in filings if f["cik"] == cik and f["form"] == "10-K"
                   and str(f.get("document_fiscal_period_focus", "")).upper() == "FY"]
        windows = set()
        for annual in annuals:
            end = (date.fromisoformat(annual["report_date"])+timedelta(days=1)).isoformat()
            starts = {r["start"] for r in filing_rows[(cik, annual["accession"])] if r["end"] == end and 350 <= _days(r["start"], end) <= 378}
            for start in starts:
                qstarts = {r["end"] for r in issuer_rows if r["start"] == start
                           and 245 <= _days(start, r["end"]) <= 300 and 75 <= _days(r["end"], end) <= 105}
                windows.update((start, qstart, end) for qstart in qstarts)
        if not windows:
            holds.append({"cik": cik, "ticker": company["ticker"], "reason": "NO_RETAINED_FY_9M_CONTEXT_WINDOW"})
        for start, qstart, end in sorted(windows):
            dimensions = {encoded(r["dimensions"]) for r in issuer_rows if r["start"] == start
                          and r["end"] in {qstart, end}}
            for scope in sorted(dimensions):
                dims = json.loads(scope)
                for flavor in ("basic", "diluted"):
                    components = {}
                    for name, s, e in (("FY", start, end), ("9M", start, qstart), ("Q4", qstart, end)):
                        for kind in ("numerator", "shares", "eps"):
                            c = _select(selection_index, cik, s, e, flavor+"_"+kind, dims)
                            if kind == "numerator" and c["status"] == "MISSING":
                                c = _select(selection_index, cik, s, e, "parent_numerator", dims)
                            components[name+"_"+kind] = c
                    row = {"cik": cik, "ticker": company["ticker"], "flavor": flavor,
                           "fy_start": start, "q4_start": qstart, "fy_end": end,
                           "dimensions": dims, "components": components,
                           "source_fact_keys": _source_keys(components), "status": "ACCOUNTING_REVIEW_REQUIRED"}
                    row["candidate_id"] = "q4-eps-candidate-"+identity(row)
                    candidates.append(row)
    output = {"schema_version": "common-q4-eps-proposal-v1", "rule_version": RULE, "config": config_pin,
            "producer_sha256": PRODUCER_SHA256,
            "public_cutoff": config["public_cutoff"], "registered_companies": [{"cik": c["cik"], "ticker": c["ticker"]} for c in companies],
            "snapshots": sorted(snapshots, key=lambda x: x["snapshot_id"]), "source_filings": filings,
            "source_rows": rows, "candidates": candidates, "holds": holds}
    _PROPOSAL_CACHE[cache_key] = copy.deepcopy(output)
    while len(_PROPOSAL_CACHE) > 1:
        _PROPOSAL_CACHE.popitem(last=False)
    return output


def _verify_projection_closure(proposal: dict, selected_fact_keys: set[str] | None = None) -> None:
    """Hash actual bytes on every use; cache reuse never trusts stat/mtime alone."""
    config = _json(proposal["config"])
    registry = _json(config["registry"])
    for company in registry["companies"]:
        _json(company["intake"])
    _json(config["base_financial_bundle"])
    if config.get("official_components"):
        _json(config["official_components"])
    selected_rows = [r for r in proposal["source_rows"] if selected_fact_keys is None or r["fact_key"] in selected_fact_keys]
    snapshot_ids = {r.get("source_snapshot_id") for r in selected_rows}
    for snapshot in proposal["snapshots"]:
        if selected_fact_keys is not None and snapshot["snapshot_id"] not in snapshot_ids:
            continue
        _bytes(snapshot["manifest"])
        directory = Path(snapshot["manifest"]["path"]).parent
        for table, sha in snapshot["table_sha256"].items():
            _bytes({"path": str(directory / (table+".parquet")), "sha256": sha})
    for row in selected_rows:
        if row.get("source_pin"):
            _bytes(row["source_pin"])


def _accepted_projection(proposal_pin: dict, receipt_pin: dict, proposal: dict) -> None:
    receipt = _json(receipt_pin)
    if (receipt.get("schema_version") != "common-q4-eps-source-projection-acceptance-v1"
        or receipt.get("reviewer") != "ROOT" or receipt.get("status") != "ACCEPTED_EXACT_PRODUCT_SOURCE_PROJECTION"
        or receipt.get("proposal") != proposal_pin or receipt.get("config") != proposal["config"]
        or receipt.get("snapshot_inventory_sha256") != identity(proposal["snapshots"])):
        raise ValueError("governed product source projection acceptance differs")
    producer = receipt.get("producer", {})
    if proposal.get("producer_sha256"):
        if producer != {"kind": "EMBEDDED_PRODUCT_SOURCE_SHA256", "sha256": proposal["producer_sha256"]}:
            raise ValueError("accepted projection producer stamp differs")
    elif producer != {"kind": "ROOT_ATTESTED_UNSTAMPED_PRODUCT_EXTRACTION"}:
        raise ValueError("unstamped product projection requires explicit legacy ROOT attestation")
    review = _json(receipt["independent_verification"])
    if (review.get("status") != "PASS" or review.get("proposal") != proposal_pin
        or review.get("scope") != "PRODUCT_RAW_SOURCE_PROJECTION"):
        raise ValueError("source projection requires independent exact product extraction verification")
    if _aware(receipt["approved_at"]) > _now():
        raise ValueError("source projection acceptance is future")


def _validated_proposal(run: dict, proposal: dict, evidence: dict) -> None:
    receipt_pin = run.get("source_projection_acceptance")
    if not receipt_pin:
        if proposal != propose_q4_eps(proposal["config"]):
            raise ValueError("Q4 proposal differs from replayed original sources")
        return
    _accepted_projection(run["proposal"], receipt_pin, proposal)
    selected = {key for case in evidence["cases"] for key in case.get("source_fact_keys", [])+case.get("ttm_source_fact_keys", [])}
    _verify_projection_closure(proposal, selected)


def _claims(case: dict) -> dict[str, dict]:
    claims = case.get("claims", [])
    index = {c["claim"]: c for c in claims}
    if len(index) != len(claims):
        raise ValueError("duplicate accounting claim")
    for claim in claims:
        _cite(claim["citations"])
    for bridge in ("numerator_bridge", "dilution_bridge"):
        for citations in case.get(bridge, {}).values():
            _cite(citations)
    return index


def _reconcile(value_interval: list | None, reference: dict) -> dict:
    if reference.get("status") != "AVAILABLE":
        return {"status": "REFERENCE_UNAVAILABLE", "reason": reference.get("reason")}
    iv = _bounds(reference)
    if not value_interval or not iv:
        return {"status": "ROUNDING_PRECISION_UNKNOWN"}
    status = "ROUNDING_COMPATIBLE" if _compatible(value_interval, iv) else "MISMATCH"
    return _serial({"status": status, "derived_interval": value_interval,
                    "reported_interval": iv, "reference_fact_keys": _source_keys({"ref": reference})})


def _weights(candidate: dict, method: str) -> tuple[Decimal, Decimal, Decimal]:
    if method == "DAY":
        return tuple(Decimal(_days(s, e)) for s, e in (
            (candidate["fy_start"], candidate["fy_end"]),
            (candidate["fy_start"], candidate["q4_start"]),
            (candidate["q4_start"], candidate["fy_end"])))
    if method == "EQUAL_QUARTER":
        return Decimal(4), Decimal(3), Decimal(1)
    if method == "MONTH":
        def months(s: str, e: str) -> Decimal:
            a, b = date.fromisoformat(s), date.fromisoformat(e)
            if a.day != b.day:
                raise ValueError("MONTH weight requires exact aligned month boundaries")
            return Decimal((b.year-a.year)*12+b.month-a.month)
        return months(candidate["fy_start"], candidate["fy_end"]), months(candidate["fy_start"], candidate["q4_start"]), months(candidate["q4_start"], candidate["fy_end"])
    raise ValueError("unsupported declared share-weight convention")


def _cumulative_diagnostic(candidate: dict, method: str | None) -> dict:
    """Mechanical comparison is retained even when dilution additivity is unproven."""
    components = candidate["components"]
    keys = ["FY_numerator", "9M_numerator", "FY_shares", "9M_shares"]
    output = {"status": "NUMERIC_DIAGNOSTIC_ONLY", "accounting_qualified": False,
              "weight_method": method, "source_fact_keys": _source_keys({k: components[k] for k in keys})}
    unavailable = [k for k in keys if components[k]["status"] != "AVAILABLE"]
    if unavailable:
        return dict(output, status="HOLD", reason="CUMULATIVE_COMPONENTS_UNAVAILABLE", missing_components=unavailable)
    if method not in {"DAY", "MONTH", "EQUAL_QUARTER"}:
        return dict(output, status="HOLD", reason="WEIGHT_CONVENTION_NOT_DECLARED")
    with localcontext() as ctx:
        ctx.prec = 80
        try:
            a, b, c = _weights(candidate, method)
        except ValueError:
            return dict(output, status="HOLD", reason="WEIGHT_BOUNDARIES_NOT_SUPPORTED")
        nf, nn, wf, wn = (components[k] for k in keys)
        n = Decimal(nf["value"])-Decimal(nn["value"])
        w = (Decimal(wf["value"])*a-Decimal(wn["value"])*b)/c
        ni = _sub(_bounds(nf), _bounds(nn))
        wi = _mul(_sub(_mul(_bounds(wf), a), _mul(_bounds(wn), b)), Decimal(1)/c)
        iv = _div(ni, wi) if wi[0] > 0 else None
        output.update(numerator=str(n), weighted_shares=str(w), numerator_interval=_serial(ni),
                      weighted_shares_interval=_serial(wi), value=str(n/w) if w > 0 else None,
                      eps_interval=_serial(iv),
                      direct_numerator_comparison=_reconcile(ni, components["Q4_numerator"]),
                      direct_shares_comparison=_reconcile(wi, components["Q4_shares"]),
                      direct_eps_comparison=_reconcile(iv, components["Q4_eps"]))
    return output


def _qualify(candidate: dict, case: dict | None) -> dict:
    result = {k: copy.deepcopy(candidate[k]) for k in ("candidate_id", "cik", "ticker", "flavor", "fy_start", "q4_start", "fy_end", "dimensions", "source_fact_keys")}
    result.update(status="HOLD", reason=None, value=None, reported_or_derived="DERIVED",
                  rule_version=RULE, components=candidate["components"],
                  component_availability={k: {"status": c["status"], "reason": c.get("reason")} for k, c in candidate["components"].items()},
                  cumulative_reconstruction_diagnostic=_cumulative_diagnostic(candidate, case.get("weight_method") if case else "DAY"))
    def hold(reason: str) -> dict:
        return dict(result, reason=reason)
    if case is None:
        return hold("ACCOUNTING_SOURCE_PATTERN_OR_REVIEW_NOT_AVAILABLE")
    if case.get("source_fact_keys") != candidate["source_fact_keys"]:
        raise ValueError("accounting evidence differs from exact candidate source facts")
    claims = _claims(case)
    required = {"SAME_CLASS_SPLIT_RECAST_BASIS", "COMPATIBLE_SOURCE_VINTAGE", "COMMON_NUMERATOR_ATTRIBUTION"}
    if required-set(claims):
        return hold("ACCOUNTING_CLAIMS_MISSING:"+",".join(sorted(required-set(claims))))
    if any(not case.get(k) for k in ("stock_class_id", "split_basis_id", "financial_scope_id")):
        return hold("ACCOUNTING_CLASS_SPLIT_SCOPE_UNKNOWN")
    components = candidate["components"]
    for key in ("Q4_numerator", "Q4_shares", "Q4_eps"):
        if components[key]["status"] == "HOLD":
            return hold(key+":"+str(components[key].get("reason")))
    direct = all(components["Q4_"+k]["status"] == "AVAILABLE" for k in ("numerator", "shares"))
    route = "DIRECT_Q4_COMPONENTS" if direct else "CUMULATIVE_COMPONENT_RECONSTRUCTION"
    result.update(route=route, accounting_evidence=case,
                  cumulative_reconstruction_diagnostic=_cumulative_diagnostic(candidate, case.get("weight_method")))
    required_components = ["Q4_numerator", "Q4_shares"] if direct else ["FY_numerator", "9M_numerator", "FY_shares", "9M_shares"]
    required_filings = {(s["cik"], s["accession"]) for key in required_components for s in components[key]["sources"]}
    all_citations = [c for claim in case["claims"] for c in claim["citations"]]
    all_citations += [c for bridge in ("numerator_bridge", "dilution_bridge") for cs in case.get(bridge, {}).values() for c in cs]
    cited_filings = {(c.get("cik"), c.get("accession")) for c in all_citations}
    if not required_filings <= cited_filings:
        return hold("ACCOUNTING_EVIDENCE_COMPONENT_FILING_COVERAGE_INCOMPLETE")
    for key in required_components:
        if components[key]["status"] != "AVAILABLE":
            return hold(key+":"+str(components[key].get("reason")))
    if any(s.get("role") == "parent_numerator" for key in required_components for s in components[key]["sources"]):
        bridge = case.get("numerator_bridge", {})
        if any(not bridge.get(k) for k in NUMERATOR_CLAIMS):
            return hold("COMMON_NUMERATOR_COMPLETE_ADJUSTMENT_BRIDGE_REQUIRED")
    with localcontext() as ctx:
        ctx.prec = 80
        if direct:
            if "DIRECT_Q4_RECONCILIATION_COMPONENTS" not in claims:
                return hold("DIRECT_Q4_COMPONENT_ACCOUNTING_PROOF_REQUIRED")
            n, w = Decimal(components["Q4_numerator"]["value"]), Decimal(components["Q4_shares"]["value"])
            ni, wi = _bounds(components["Q4_numerator"]), _bounds(components["Q4_shares"])
            formula = "Q4_REPORTED_COMMON_NUMERATOR / Q4_REPORTED_WEIGHTED_AVERAGE_SHARES"
        else:
            if "PERIOD_TIME_WEIGHTED_COMMON_SHARES" not in claims:
                return hold("TIME_WEIGHTED_SHARE_POLICY_NOT_PROVEN")
            method = case.get("weight_method")
            if method != "DAY" and "EXPLICIT_WEIGHT_CONVENTION" not in claims:
                return hold("EXPLICIT_WEIGHT_CONVENTION_NOT_PROVEN")
            if (candidate["flavor"] == "diluted"
                and ("CUMULATIVE_DILUTION_ADDITIVITY_PROVEN" not in claims
                     or any(not case.get("dilution_bridge", {}).get(k) for k in DILUTION_CLAIMS))):
                return hold("DILUTED_CUMULATIVE_ADDITIVITY_NOT_PROVEN")
            a, b, c = _weights(candidate, method)
            if a != b+c or min(a, b, c) <= 0:
                return hold("WEIGHT_BOUNDARIES_INCOMPATIBLE")
            nf, nn = components["FY_numerator"], components["9M_numerator"]
            wf, wn = components["FY_shares"], components["9M_shares"]
            n = Decimal(nf["value"])-Decimal(nn["value"])
            w = (Decimal(wf["value"])*a-Decimal(wn["value"])*b)/c
            ni, wi = _sub(_bounds(nf), _bounds(nn)), _mul(_sub(_mul(_bounds(wf), a), _mul(_bounds(wn), b)), Decimal(1)/c)
            result.update(weight_method=method, weights=[str(a), str(b), str(c)])
            formula = "(FY_COMMON_NUMERATOR - 9M_COMMON_NUMERATOR) / ((FY_WAVG * FY_WEIGHT - 9M_WAVG * 9M_WEIGHT) / Q4_WEIGHT)"
            cumulative = {}
            for period in ("FY", "9M"):
                pn, pw = components[period+"_numerator"], components[period+"_shares"]
                pwi = _bounds(pw)
                expected = _div(_bounds(pn), pwi) if pwi and pwi[0] > 0 else None
                cumulative[period] = _reconcile(expected, components[period+"_eps"])
            result["cumulative_reconciliation"] = cumulative
            if any(r["status"] == "MISMATCH" for r in cumulative.values()):
                return dict(result, status="FAIL", reason="CUMULATIVE_REPORTED_EPS_MISMATCH")
            if any(r["status"] != "ROUNDING_COMPATIBLE" for r in cumulative.values()):
                return hold("CUMULATIVE_REPORTED_EPS_REFERENCE_INCOMPLETE")
        result.update(numerator=str(n), weighted_shares=str(w), numerator_interval=_serial(ni),
                      weighted_shares_interval=_serial(wi), formula=formula)
        if w <= 0 or not wi or wi[0] <= 0:
            return hold("WEIGHTED_AVERAGE_SHARE_DENOMINATOR_NONPOSITIVE_OR_UNCERTAIN")
        iv = _div(ni, wi)
        point = n/w
        reference = components["Q4_eps"]
        comparison = _reconcile(iv, reference)
        result.update(reconstructed_value=str(point), eps_interval=_serial(iv), direct_comparison=comparison,
                      rounding_status="SOURCE_DECIMALS_INTERVAL_PROPAGATED")
        if comparison["status"] == "MISMATCH":
            return dict(result, status="FAIL", reason="DIRECT_Q4_EPS_ROUNDING_MISMATCH")
        # A directly reported Q4 EPS is the selected quarter; N/W stays validation.
        selected = reference["value"] if reference["status"] == "AVAILABLE" else str(point)
        selected_interval = reference["interval"] if reference["status"] == "AVAILABLE" else _serial(iv)
        result.update(status="QUALIFIED", reason=None, value=selected, selected_eps_interval=selected_interval,
                      selected_source_type="REPORTED_Q4_EPS" if reference["status"] == "AVAILABLE" else "DERIVED_Q4_EPS",
                      known_on=max(s["filed_date"] for key in required_components+["Q4_eps"] for s in components[key]["sources"]))
    return result


def _quarter_sources(proposal: dict, row: dict, anchor: str, *, issuer_rows: list[dict] | None = None,
                     selection_index: dict | None = None) -> list[dict]:
    """One Q4 plus adjacent direct quarters; never FY EPS or an annual proxy."""
    pool = issuer_rows if issuer_rows is not None else proposal["source_rows"]
    selected_pool = selection_index if selection_index is not None else pool
    cik, dims, end = row["cik"], row["dimensions"], row["fy_end"]
    quarters = [{"start": row["q4_start"], "end": end, "value": row["value"],
                 "interval": row["selected_eps_interval"], "source_type": row["selected_source_type"],
                 "candidate_id": row["candidate_id"], "source_fact_keys": row["source_fact_keys"]}]
    while end < anchor and len(quarters) < 4:
        ends = sorted({r["end"] for r in pool if r["cik"] == cik and r["start"] == end
                       and r["role"] == "diluted_eps" and r["dimensions"] == dims
                       and 75 <= _days(end, r["end"]) <= 105 and r["end"] <= anchor})
        if len(ends) != 1:
            return []
        selected = _select(selected_pool, cik, end, ends[0], "diluted_eps", dims)
        if selected["status"] != "AVAILABLE":
            return []
        quarters.append({"start": end, "end": ends[0], "value": selected["value"],
                         "interval": selected["interval"], "source_type": "REPORTED_QTD_EPS",
                         "source_fact_keys": _source_keys({"selected": selected})})
        end = ends[0]
    while end == anchor and len(quarters) < 4:
        start = quarters[0]["start"]
        starts = sorted({r["start"] for r in pool if r["cik"] == cik and r["end"] == start
                         and r["role"] == "diluted_eps" and r["dimensions"] == dims
                         and 75 <= _days(r["start"], start) <= 105})
        if len(starts) != 1:
            return []
        selected = _select(selected_pool, cik, starts[0], start, "diluted_eps", dims)
        if selected["status"] != "AVAILABLE":
            return []
        quarters.insert(0, {"start": starts[0], "end": start, "value": selected["value"],
                           "interval": selected["interval"], "source_type": "REPORTED_QTD_EPS",
                           "source_fact_keys": _source_keys({"selected": selected})})
    return quarters if len(quarters) == 4 and end == anchor else []


def _ttm(proposal: dict, qualified: list[dict], base: dict, cases: dict, run: dict,
         prepared: str, cutoff: str) -> tuple[list[dict], list[dict]]:
    observations, holds = [], []
    selection_index = _selection_index(proposal["source_rows"])
    issuer_rows = defaultdict(list)
    for source in proposal["source_rows"]:
        issuer_rows[source["cik"]].append(source)
    for row in qualified:
        if row["flavor"] != "diluted" or row["status"] != "QUALIFIED":
            continue
        cik = row["cik"]
        anchors = [a["period_end"] for a in base["financial_anchors"] if a["cik"] == cik and a["known_on"] <= cutoff]
        grants = [g for g in base["compatibility_grants"] if g["cik"] == cik and anchors and g["financial_anchor"] == max(anchors)]
        if len(grants) != 1:
            holds.append({"cik": cik, "reason": "EXACT_APPROVED_CURRENT_GRANT_NOT_AVAILABLE", "candidate_id": row["candidate_id"]})
            continue
        grant, case = grants[0], cases[row["candidate_id"]]
        if grant["input_ids"].get("diluted_eps_12m"):
            continue  # Existing direct FY/TTM role is never replaced.
        quarters = _quarter_sources(proposal, row, grant["financial_anchor"], issuer_rows=issuer_rows[cik], selection_index=selection_index)
        reason = None
        if not quarters or not 350 <= _days(quarters[0]["start"], quarters[-1]["end"]) <= 378:
            reason = "EXACT_CURRENT_FOUR_QUARTER_WINDOW_NOT_AVAILABLE"
        elif any(case.get(k) != grant.get(g) for k, g in (("stock_class_id", "stock_class_id"),
                 ("split_basis_id", "split_basis_id"), ("financial_scope_id", "financial_scope_id"))):
            reason = "CURRENT_GRANT_CLASS_SPLIT_SCOPE_MISMATCH"
        elif ("TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" not in {c["claim"] for c in case["claims"]}
              or case.get("ttm_source_fact_keys") != sorted({key for q in quarters for key in q["source_fact_keys"]})):
            reason = "FOUR_QUARTER_ACCOUNTING_BASIS_EVIDENCE_NOT_PROVEN"
        if reason:
            holds.append({"cik": cik, "reason": reason, "candidate_id": row["candidate_id"]})
            continue
        keys = sorted({key for q in quarters for key in q["source_fact_keys"]})
        source_rows = [r for r in proposal["source_rows"] if r["fact_key"] in keys]
        ttm_claim = next(c for c in case["claims"] if c["claim"] == "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE")
        cited = {(c.get("cik"), c.get("accession")) for c in ttm_claim["citations"]}
        if not {(r["cik"], r["accession"]) for r in source_rows} <= cited:
            holds.append({"cik": cik, "reason": "TTM_SOURCE_FILING_EVIDENCE_COVERAGE_INCOMPLETE", "candidate_id": row["candidate_id"]})
            continue
        basis = _basis_bridge(proposal, row, grant, source_rows, cutoff)
        if basis["status"] != "VERIFIED":
            holds.append({"cik": cik, "reason": basis["reason"], "candidate_id": row["candidate_id"], "basis_bridge": basis})
            continue
        with localcontext() as ctx:
            ctx.prec = 80
            value = sum((Decimal(q["value"]) for q in quarters), Decimal(0))
            interval = [sum((Decimal(q["interval"][i]) for q in quarters), Decimal(0)) for i in (0, 1)]
        output = {"role": "diluted_eps_12m", "cik": cik, "ticker": row["ticker"],
            "currency": grant["currency"], "scope_id": grant["financial_scope_id"],
            "stock_class_id": grant["stock_class_id"], "split_basis_id": grant["split_basis_id"],
            "known_on": max(r["filed_date"] for r in source_rows), "period_start": quarters[0]["start"],
            "period_end": quarters[-1]["end"], "period_class": "TTM", "end_convention": "EXCLUSIVE",
            "value": str(value), "eps_interval": _serial(interval), "unit_kind": "currency/share",
            "status": "AVAILABLE", "reason": None, "source_kind": SOURCE_KIND,
            "reported_or_derived": "DERIVED", "definition_version": RULE, "formula_id": RULE,
            "formula": "SUM(FOUR_COMPATIBLE_QTD_EPS_WITH_VERIFIED_Q4_COMPONENTS)",
            "source_refs": quarters, "evidence_pins": [run["policy"], run["accounting_evidence"]],
            "q4_candidate_id": row["candidate_id"], "basis_bridge": basis, "historical_ready": False,
            "ready_at": prepared, "ready_on": _aware(prepared).date().isoformat()}
        output["observation_id"] = "price-financial-input-"+identity(output)
        observations.append(output)
    # Two eligible windows never win by order.
    duplicate_ciks = {c for c in {r["cik"] for r in observations} if sum(r["cik"] == c for r in observations) > 1}
    observations = [r for r in observations if r["cik"] not in duplicate_ciks]
    holds.extend({"cik": c, "reason": "AMBIGUOUS_QUALIFIED_CURRENT_TTM_WINDOW"} for c in sorted(duplicate_ciks))
    return observations, holds


@_source_operation
def qualify_q4_eps(run_pin: dict, *, _recorded_at: str | None = None) -> dict:
    """Validate original facts/accounting/uncertainty, retaining every HOLD/FAIL."""
    run = _json(run_pin)
    if run.get("schema_version") != "common-q4-eps-run-v1":
        raise ValueError("unsupported Q4 EPS qualification run")
    proposal = _json(run["proposal"])
    config = _json(proposal["config"])
    policy, evidence, decision = (_json(run[k]) for k in ("policy", "accounting_evidence", "evaluation_decision"))
    _validated_proposal(run, proposal, evidence)
    if (policy.get("schema_version") != "common-q4-eps-policy-v1" or policy.get("rule_version") != RULE
        or policy.get("reviewer") != "ROOT" or policy.get("status") != "APPROVED_GLOBAL_RULE"):
        raise ValueError("ROOT global component accounting policy approval required")
    if (evidence.get("schema_version") != "common-q4-eps-accounting-evidence-v1"
        or evidence.get("reviewer") != "ROOT" or evidence.get("status") != "REVIEWED_SOURCE_ACCOUNTING_EVIDENCE"):
        raise ValueError("original accounting evidence review required")
    if (decision.get("reviewer") != "ROOT" or decision.get("status") != "APPROVED_FOR_BOUNDED_IMPLEMENTATION"
        or decision.get("mode") != MODE or decision.get("public_financial_information_cutoff") != proposal["public_cutoff"]
        or decision.get("quote_session") != proposal["public_cutoff"]):
        raise ValueError("exact current evaluation decision required")
    if evidence.get("grammar") and evidence != discover_accounting_evidence(
        run["proposal"], evidence["grammar"], evidence["source_catalog"]):
        raise ValueError("automatic accounting evidence differs from original source grammar replay")
    cases = {c["candidate_id"]: c for c in evidence["cases"]}
    candidates = {c["candidate_id"]: c for c in proposal["candidates"]}
    if len(cases) != len(evidence["cases"]) or not set(cases) <= set(candidates):
        raise ValueError("absent or duplicate accounting candidate identity")
    prepared = _recorded_at or _now().isoformat()
    ready = _aware(prepared)
    times = [_aware(policy["approved_at"]), _aware(evidence["reviewed_at"]), _aware(decision["decided_at"])]
    times += [_aware(r["captured_at"]) for r in proposal["source_rows"] if r.get("captured_at")]
    if (ready > _now() or ready < max(times) or ready.astimezone(ZoneInfo(decision.get("evaluation_timezone", "UTC"))).date().isoformat() != decision["evaluation_as_of"]
        or any(t > _now() for t in times)):
        raise ValueError("Q4 actual ready time precedes evidence/is future/outside evaluation day")
    base = _json(config["base_financial_bundle"])
    source_index = {r["fact_key"]: r for r in proposal["source_rows"]}
    results = [_qualify(c, cases.get(c["candidate_id"])) for c in proposal["candidates"]]
    for row in results:
        row["source_review_holds"] = [copy.deepcopy(h) for h in evidence.get("holds", []) if h.get("candidate_id") == row["candidate_id"]]
        row["component_validation_status"] = "VALIDATED" if row["status"] == "QUALIFIED" else "NOT_QUALIFIED"
        row["source_equation_status"] = "NOT_VALIDATED"
        row["source_basis_status"] = "NOT_VALIDATED"
        if row["status"] == "QUALIFIED":
            structure = _source_equation_gate(candidates[row["candidate_id"]], config)
            row["source_equation_validation"] = structure
            row["source_equation_status"] = structure["status"]
            if structure["status"] != "VERIFIED":
                row.update(status="HOLD", reason=structure["reason"], value=None)
                continue
            anchors = [a["period_end"] for a in base["financial_anchors"] if a["cik"] == row["cik"] and a["known_on"] <= proposal["public_cutoff"]]
            grants = [g for g in base["compatibility_grants"] if g["cik"] == row["cik"] and anchors and g["financial_anchor"] == max(anchors)]
            if len(grants) != 1:
                row.update(status="HOLD", reason="LOCAL_Q4_SOURCE_BASIS_CURRENT_BINDING_NOT_AVAILABLE", value=None)
                continue
            local_sources = [source_index[k] for k in row["source_fact_keys"]]
            basis = _basis_bridge(proposal, row, grants[0], local_sources, proposal["public_cutoff"])
            row["local_source_basis"] = basis
            row["source_basis_status"] = basis["status"]
            if basis["status"] != "VERIFIED":
                row.update(status="HOLD", reason=basis["reason"], value=None)
    for row in results:
        if row["status"] != "QUALIFIED" or row["flavor"] != "diluted":
            continue
        direct_basic = _select(proposal["source_rows"], row["cik"], row["q4_start"], row["fy_end"], "basic_shares", row["dimensions"])
        basic_intervals = [_bounds(direct_basic)] if direct_basic["status"] == "AVAILABLE" else []
        basic_intervals += [[Decimal(v) for v in b["weighted_shares_interval"]] for b in results
            if b["status"] == "QUALIFIED" and b["flavor"] == "basic"
            and all(b[k] == row[k] for k in ("cik", "fy_start", "q4_start", "fy_end", "dimensions"))]
        if any(Decimal(row["weighted_shares_interval"][1]) < b[0] for b in basic_intervals):
            row.update(status="FAIL", reason="DILUTED_SHARES_BELOW_BASIC_ALLOWING_SOURCE_ROUNDING", value=None)
    observations, holds = _ttm(proposal, results, base, cases, run, prepared, proposal["public_cutoff"])
    retained_keys = {key for r in observations for q in r["source_refs"] for key in q["source_fact_keys"]}
    for result in results:
        result.pop("components", None)  # Full immutable components resolve through source_projection.
    return copy.deepcopy({"schema_version": "governed-common-q4-eps-v1", "rule_version": RULE, "config": run_pin,
            "source_projection": run["proposal"], "prepared_at": prepared, "public_cutoff": proposal["public_cutoff"],
            "evaluation_decision": run["evaluation_decision"], "base_financial_bundle": config["base_financial_bundle"],
            "quarter_results": results, "observations": observations,
            "source_rows": [r for r in proposal["source_rows"] if r["fact_key"] in retained_keys],
            "holds": proposal["holds"]+holds})


@_source_operation
def verify_q4_eps(pin: dict) -> dict:
    data = _json(pin)
    if data.get("schema_version") != "governed-common-q4-eps-v1":
        raise ValueError("unsupported governed component EPS artifact")
    cached = _VERIFIED_ARTIFACT_CACHE.get(pin["sha256"])
    if cached is not None:
        run = _json(data["config"])
        proposal, evidence = _json(run["proposal"]), _json(run["accounting_evidence"])
        _validated_proposal(run, proposal, evidence)
        inputs = [run, _json(proposal["config"]), evidence,
                  _json(run["policy"]), _json(run["evaluation_decision"])]
        for value in [cached, *inputs]:
            _recheck_pins(value)
        if evidence.get("grammar"):
            _recheck_pins(_json(evidence["grammar"]))
            _json(evidence["source_catalog"])
        if _aware(data["prepared_at"]) > _now():
            raise ValueError("component EPS ready time is future")
        _VERIFIED_ARTIFACT_CACHE.move_to_end(pin["sha256"])
        return copy.deepcopy(cached)
    if qualify_q4_eps(data["config"], _recorded_at=data["prepared_at"]) != data:
        raise ValueError("component EPS artifact differs from replayed facts/policy/evidence")
    _VERIFIED_ARTIFACT_CACHE[pin["sha256"]] = copy.deepcopy(data)
    while len(_VERIFIED_ARTIFACT_CACHE) > 4:
        _VERIFIED_ARTIFACT_CACHE.popitem(last=False)
    return copy.deepcopy(data)


@_source_operation
def validated_q4_ttm_rows(bundle: dict) -> dict[str, dict]:
    rows = [r for r in bundle.get("observations", []) if r.get("source_kind") == SOURCE_KIND]
    pin = bundle.get("q4_component_derivation")
    if not pin:
        if rows:
            raise ValueError("component EPS requires exact replayed derivation")
        return {}
    artifact = verify_q4_eps(pin)
    expected = {r["observation_id"]: r for r in artifact["observations"]}
    if len(rows) != len(expected) or {r["observation_id"]: r for r in rows} != expected:
        raise ValueError("component EPS bundle differs from verified derivation")
    for row in rows:
        grants = [g for g in bundle["compatibility_grants"] if g["cik"] == row["cik"] and g["financial_anchor"] == row["period_end"]]
        anchors = [a["period_end"] for a in bundle["financial_anchors"] if a["cik"] == row["cik"] and a["known_on"] <= artifact["public_cutoff"]]
        if (not anchors or max(anchors) != row["period_end"] or len(grants) != 1
            or grants[0]["input_ids"].get("diluted_eps_12m") != row["observation_id"]
            or any(row[k] != grants[0][g] for k, g in (("currency", "currency"), ("stock_class_id", "stock_class_id"),
                    ("split_basis_id", "split_basis_id"), ("scope_id", "financial_scope_id")))):
            raise ValueError("component EPS current grant/anchor/basis differs")
    return expected


@_source_operation
def augment_q4_eps_ttm(pin: dict) -> dict:
    artifact = verify_q4_eps(pin)
    bundle = copy.deepcopy(_json(artifact["base_financial_bundle"]))
    existing = {r["observation_id"] for r in bundle["observations"]}
    if bundle.get("q4_component_derivation"):
        raise ValueError("component EPS derivation already exists")
    for row in artifact["observations"]:
        grants = [g for g in bundle["compatibility_grants"] if g["cik"] == row["cik"] and g["financial_anchor"] == row["period_end"]]
        if (row["observation_id"] in existing or len(grants) != 1
            or grants[0]["input_ids"].get("diluted_eps_12m")):
            raise ValueError("component EPS cannot replace an existing input/grant role")
        grants[0]["input_ids"]["diluted_eps_12m"] = row["observation_id"]
        grants[0]["evidence_pins"].append(pin)
        bundle["observations"].append(row)
    bundle["q4_component_derivation"] = pin
    diagnostics = list(bundle.get("current_eps_diagnostics", []))
    bound = {g["cik"] for g in bundle["compatibility_grants"] if g["input_ids"].get("diluted_eps_12m")}
    for cik in sorted({r["cik"] for r in artifact["quarter_results"]}-bound):
        relevant = [r for r in artifact["quarter_results"] if r["cik"] == cik and r["flavor"] == "diluted"]
        latest = max(r["fy_end"] for r in relevant)
        rejected = [r for r in relevant if r["fy_end"] == latest and r["status"] != "QUALIFIED"]
        ttm_holds = [r for r in artifact["holds"] if r["cik"] == cik]
        if rejected or ttm_holds:
            diagnostics.append({"cik": cik, "reason": "Q4_EPS_ACCOUNTING_OR_WINDOW_NOT_QUALIFIED",
                "details": [{"candidate_id": r.get("candidate_id"), "reason": r["reason"]} for r in rejected+ttm_holds],
                "evidence_pins": [pin]})
    bundle["current_eps_diagnostics"] = diagnostics
    validated_q4_ttm_rows(bundle)
    return bundle


@_source_operation
def discover_accounting_evidence(proposal_pin: dict, grammar_pin: dict,
                                 source_catalog_pin: dict) -> dict:
    """Apply a ROOT-reviewed, company-independent disclosure grammar.

    A grammar author owns the accounting meaning of its patterns. The scanner
    only emits a case when every required pattern resolves in every implicated
    source filing. New registered companies use these same rules. Unsupported
    layouts remain explicit; no candidate is approved by an issuer name.
    """
    proposal, grammar, catalog = (_json(p) for p in (proposal_pin, grammar_pin, source_catalog_pin))
    if (grammar.get("schema_version") != "common-q4-eps-evidence-grammar-v1"
        or grammar.get("reviewer") != "ROOT" or grammar.get("status") != "APPROVED_GLOBAL_SOURCE_GRAMMAR"):
        raise ValueError("ROOT global source grammar approval required")
    _aware(grammar["approved_at"])
    config = _json(proposal["config"])
    base = _json(config["base_financial_bundle"])
    docs = defaultdict(list)
    for entry in catalog["documents"]:
        docs[(entry["cik"], entry["accession"])].append(entry["source_pin"])
    rules = grammar["rules"]
    allowed = {"rule_id", "route", "weight_method", "claims", "numerator_bridge", "dilution_bridge"}
    for rule in rules:
        for pattern in rule.get("claims", []):
            if "optional_if_scope_empty" in pattern and type(pattern["optional_if_scope_empty"]) is not bool:
                raise ValueError("optional_if_scope_empty must be a boolean")
            if set(pattern)-{"claim", "xpath", "text_pattern", "filing_scope", "optional_if_scope_empty"}:
                raise ValueError("unsupported accounting grammar selector")
            if pattern.get("optional_if_scope_empty") and (pattern.get("claim") != "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" or pattern.get("filing_scope", "TTM_FILINGS") != "TTM_FILINGS"):
                raise ValueError("only the TTM-window claim may be optional for an empty TTM scope")
        if any(pattern.get("optional_if_scope_empty") for bridge in ("numerator_bridge", "dilution_bridge") for pattern in rule.get(bridge, {}).values()):
            raise ValueError("accounting bridge claims cannot be optional for an empty scope")
    if any(set(rule)-allowed or not rule.get("rule_id") for rule in rules):
        raise ValueError("global grammar cannot contain company-specific selectors or overrides")
    def match(pattern: dict, filings: set[tuple[str, str]]) -> list[dict] | None:
        if set(pattern)-{"xpath", "text_pattern", "claim", "filing_scope", "optional_if_scope_empty"}:
            raise ValueError("unsupported accounting grammar selector")
        if not filings:
            return None
        found = []
        regex = re.compile(pattern["text_pattern"], re.IGNORECASE)
        for filing in sorted(filings):
            citations = []
            for pin in docs.get(filing, []):
                _verify_once(pin)
                cache_key = ("pattern", pin["sha256"], pattern["xpath"], pattern["text_pattern"])
                if cache_key not in _MATCH_CACHE:
                    document = _document(pin)
                    matches = [(_xpath(node), _text(node)) for node in document.xpath(pattern["xpath"])
                               if hasattr(node, "itertext") and regex.search(_text(node))]
                    _cache_match(cache_key, matches)
                for xpath, text in _MATCH_CACHE[cache_key]:
                    citations.append({"cik": filing[0], "accession": filing[1],
                                      "source_pin": pin, "xpath": xpath, "expected_text": text})
            if not citations:
                return None
            found.extend(citations)
        return found
    cases, holds = [], []
    selection_index = _selection_index(proposal["source_rows"])
    issuer_rows = defaultdict(list)
    for source in proposal["source_rows"]:
        issuer_rows[source["cik"]].append(source)
    for candidate in proposal["candidates"]:
        direct_components = all(candidate["components"]["Q4_"+k]["status"] == "AVAILABLE" for k in ("numerator", "shares"))
        required = ["Q4_numerator", "Q4_shares"] if direct_components else ["FY_numerator", "9M_numerator", "FY_shares", "9M_shares"]
        unavailable = {k: {"status": candidate["components"][k]["status"], "reason": candidate["components"][k].get("reason")} for k in required if candidate["components"][k]["status"] != "AVAILABLE"}
        if unavailable:
            holds.append({"candidate_id": candidate["candidate_id"], "reason": "COMPONENT_INPUT_NOT_AVAILABLE_FOR_ACCOUNTING_PATTERN", "component_availability": unavailable})
            continue

        grants = [g for g in base["compatibility_grants"] if g["cik"] == candidate["cik"]]
        if not grants:
            holds.append({"candidate_id": candidate["candidate_id"], "reason": "EXISTING_ACCOUNTING_GRANT_NOT_AVAILABLE_FOR_SOURCE_DISCOVERY"})
            continue
        newest = max(g["financial_anchor"] for g in grants)
        grants = [g for g in grants if g["financial_anchor"] == newest]
        if len(grants) != 1:
            holds.append({"candidate_id": candidate["candidate_id"], "reason": "AMBIGUOUS_EXISTING_ACCOUNTING_GRANT"})
            continue
        grant = grants[0]
        found_cases = []
        for rule in rules:
            direct = all(candidate["components"]["Q4_"+k]["status"] == "AVAILABLE" for k in ("numerator", "shares"))
            if rule.get("route") != ("DIRECT_Q4_COMPONENTS" if direct else "CUMULATIVE_COMPONENT_RECONSTRUCTION"):
                continue
            case = {"candidate_id": candidate["candidate_id"], "source_fact_keys": candidate["source_fact_keys"],
                    "stock_class_id": grant["stock_class_id"], "split_basis_id": grant["split_basis_id"],
                    "financial_scope_id": grant["financial_scope_id"], "weight_method": rule.get("weight_method", "DAY"),
                    "grammar_rule_id": rule["rule_id"], "claims": []}
            failed = False
            failures = []
            component_names = ["Q4_numerator", "Q4_shares"] if direct else ["FY_numerator", "9M_numerator", "FY_shares", "9M_shares"]
            def filing_set(names: list[str], form: str | None = None, candidate: dict = candidate) -> set[tuple[str, str]]:
                return {(r["cik"], r["accession"]) for name in names
                        for r in candidate["components"][name].get("sources", [])
                        if form is None or r["form"] == form}
            scopes = {"COMPONENT_FILINGS": filing_set(component_names),
                      "ANNUAL_FILINGS": filing_set(["FY_numerator", "FY_shares"], "10-K"),
                      "QUARTERLY_FILINGS": filing_set(["9M_numerator", "9M_shares"], "10-Q"),
                      "DIRECT_Q4_FILINGS": filing_set(["Q4_numerator", "Q4_shares", "Q4_eps"])}
            # Include all four-quarter source filings in the basis pattern scan.
            fake = dict(candidate, value="0", selected_eps_interval=["0", "0"], selected_source_type="DERIVED_Q4_EPS")
            quarters = _quarter_sources(proposal, fake, grant["financial_anchor"], issuer_rows=issuer_rows[candidate["cik"]], selection_index=selection_index)
            ttm_keys = sorted({key for q in quarters for key in q["source_fact_keys"]})
            all_sources = [r for r in proposal["source_rows"] if r["fact_key"] in ttm_keys]
            scopes["TTM_FILINGS"] = {(r["cik"], r["accession"]) for r in all_sources} if quarters else set()
            def scoped_match(pattern: dict, label: str, scopes: dict = scopes,
                             failures: list = failures, rule_id: str = rule["rule_id"]) -> list[dict] | None:
                name = pattern.get("filing_scope", "TTM_FILINGS" if label == "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" else "COMPONENT_FILINGS")
                if name not in scopes:
                    raise ValueError("unsupported accounting filing scope: "+name)
                if pattern.get("optional_if_scope_empty") and (label != "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" or name != "TTM_FILINGS"):
                    raise ValueError("only the TTM-window claim may be optional for an empty TTM scope")
                citations = match(pattern, scopes[name])
                if not citations:
                    failures.append({"rule_id": rule_id, "claim": label, "filing_scope": name,
                                     "reason": "SOURCE_SCOPE_EMPTY" if not scopes[name] else "SOURCE_PATTERN_NOT_MATCHED_IN_EVERY_SCOPED_FILING",
                                     "filings": [list(f) for f in sorted(scopes[name])]})
                return citations
            for pattern in rule["claims"]:
                if pattern.get("optional_if_scope_empty"):
                    if pattern["claim"] != "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" or pattern.get("filing_scope", "TTM_FILINGS") != "TTM_FILINGS":
                        raise ValueError("only the TTM-window claim may be optional for an empty TTM scope")
                    if not scopes["TTM_FILINGS"]:
                        continue
                citations = scoped_match(pattern, pattern["claim"])
                if not citations:
                    failed = True
                    continue
                case["claims"].append({"claim": pattern["claim"], "filing_scope": pattern.get("filing_scope", "TTM_FILINGS" if pattern["claim"] == "TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE" else "COMPONENT_FILINGS"), "citations": citations})
            if failed:
                holds.append({"candidate_id": candidate["candidate_id"], "reason": "SOURCE_GRAMMAR_SCOPE_NOT_SUPPORTED", "details": failures})
                continue
            case["ttm_source_fact_keys"] = ttm_keys
            for bridge in ("numerator_bridge", "dilution_bridge"):
                case[bridge] = {}
                for name, pattern in rule.get(bridge, {}).items():
                    citations = scoped_match(pattern, bridge+":"+name)
                    if not citations:
                        failed = True
                        continue
                    case[bridge][name] = citations
            citations = [c for claim in case["claims"] for c in claim["citations"]]
            citations += [c for bridge in ("numerator_bridge", "dilution_bridge") for cs in case.get(bridge, {}).values() for c in cs]
            cited = {(c["cik"], c["accession"]) for c in citations}
            if not scopes["COMPONENT_FILINGS"] <= cited:
                failed = True
                failures.append({"rule_id": rule["rule_id"], "reason": "ACCOUNTING_EVIDENCE_COMPONENT_FILING_COVERAGE_INCOMPLETE"})
            if not failed:
                found_cases.append(case)
            else:
                holds.append({"candidate_id": candidate["candidate_id"], "reason": "SOURCE_GRAMMAR_SCOPE_NOT_SUPPORTED", "details": failures})
        if len(found_cases) == 1:
            cases.extend(found_cases)
        else:
            holds.append({"candidate_id": candidate["candidate_id"], "reason": "SOURCE_GRAMMAR_UNSUPPORTED" if not found_cases else "AMBIGUOUS_SOURCE_ACCOUNTING_GRAMMAR"})
    return copy.deepcopy({"schema_version": "common-q4-eps-accounting-evidence-v1", "reviewer": "ROOT",
            "status": "REVIEWED_SOURCE_ACCOUNTING_EVIDENCE", "reviewed_at": grammar["approved_at"],
            "grammar": grammar_pin, "source_catalog": source_catalog_pin, "proposal": proposal_pin,
            "cases": cases, "holds": holds})


@_source_operation
def validate_component_current_evaluation(declaration: dict, *, bundle_pin: dict,
                                          batch_pin: dict, requested: str, selected: str) -> dict:
    """v2 current-only policy can retain old reported TTM and add verified Q4 TTM."""
    policy, approval = _json(declaration["policy"]), _json(declaration["approval"])
    if (policy.get("schema_version") != "eps-current-evaluation-policy-v2" or policy.get("mode") != MODE
        or approval.get("schema_version") != "eps-current-evaluation-root-acceptance-v1"
        or approval.get("reviewer") != "ROOT" or approval.get("status") != "APPROVED_FOR_EXACT_CURRENT_EVALUATION"
        or approval.get("policy") != declaration["policy"] or policy.get("financial_inputs") != bundle_pin
        or policy.get("price_batch") != batch_pin or policy.get("quote_session") != selected
        or policy.get("public_financial_information_cutoff") != selected or policy.get("evaluation_as_of") != requested):
        raise ValueError("exact component current evaluation policy differs")
    decision = _json(policy["decision"])
    if (decision.get("reviewer") != "ROOT" or decision.get("status") != "APPROVED_FOR_BOUNDED_IMPLEMENTATION"
        or any(policy.get(k) != decision.get(k) for k in ("mode", "quote_session", "evaluation_as_of", "public_financial_information_cutoff"))
        or policy.get("evaluation_timezone", "UTC") != decision.get("evaluation_timezone", "UTC")):
        raise ValueError("current component evaluation differs from ROOT decision")
    bundle = _json(bundle_pin)
    from sec_xbrl.metrics.reported_quarter_eps import validated_ttm_rows, verify_ttm
    rows = {**validated_ttm_rows(bundle), **validated_q4_ttm_rows(bundle)}
    derivations = {k: bundle[k] for k in ("reported_quarter_derivation", "q4_component_derivation") if bundle.get(k)}
    if policy.get("derivations") != derivations or not rows or "q4_component_derivation" not in derivations:
        raise ValueError("current component evaluation derivation set differs")
    artifacts = [verify_q4_eps(derivations["q4_component_derivation"])]
    if artifacts[0]["evaluation_decision"] != policy["decision"]:
        raise ValueError("component derivation decision differs")
    if "reported_quarter_derivation" in derivations:
        artifacts.append(verify_ttm(derivations["reported_quarter_derivation"]))
    evaluated = _aware(policy["evaluation_at"])
    if (evaluated > _now() or evaluated.astimezone(ZoneInfo(policy.get("evaluation_timezone", "UTC"))).date().isoformat() != requested
        or evaluated < max(_aware(a["prepared_at"]) for a in artifacts)
        or _aware(approval["approved_at"]) > _now() or evaluated < _aware(approval["approved_at"])
        or evaluated < _aware(decision["decided_at"])):
        raise ValueError("current component evaluation time precedes evidence/is future/outside day")
    return {"mode": MODE, "evaluation_as_of": requested, "evaluation_at": policy["evaluation_at"],
            "quote_session": selected, "public_financial_information_cutoff": selected,
            "evaluation_timezone": policy.get("evaluation_timezone", "UTC"),
            "eps_input_admission_policy_version": RULE,
            "policy": declaration["policy"], "approval": declaration["approval"],
            "derivations": derivations, "input_ids": sorted(rows), "backtest_eligible": False}


def _supplier_replay(normalizer_pin: dict, payload: bytes, security: dict,
                     period1: int, period2: int, reviewed_blob: bytes) -> tuple[list, dict]:
    """Use the existing pinned supplier normalizer; never collect or modify it."""
    _bytes(normalizer_pin)
    supplier_root = str(Path(normalizer_pin["path"]).parents[1])
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, supplier_root)
    try:
        module = importlib.import_module("market_data_pipeline.price")
        if Path(module.__file__).resolve() != Path(normalizer_pin["path"]).resolve():
            raise ValueError("supplier normalizer import differs from accepted source pin")
        return module.normalize_yahoo_chart_capture(payload, security=security,
            requested_period1=period1, requested_period2=period2,
            reviewed_actions=module._reviewed_index(reviewed_blob))
    finally:
        sys.path.remove(supplier_root)
        sys.dont_write_bytecode = previous


def _official_identity_element(node: object, local_name: str, namespace: str) -> bool:
    tag = str(node.tag)
    return ":" in tag and tag.split(":", 1)[1].lower() == local_name.lower() and _source_namespace(node, tag.split(":", 1)[0]) == namespace


def _cover_issuer_identity(document: object, entry: dict, filing: tuple[str, str]) -> dict:
    """A hidden DEI CIK is legitimate metadata; its QName and Context must agree."""
    identities, citations = set(), []
    xbrli = "http://www.xbrl.org/2003/instance"
    for node in document.xpath("//*[@name]"):
        name = node.get("name", "")
        if ":" not in name or name.split(":", 1)[1] != "EntityCentralIndexKey":
            continue
        namespace = _source_namespace(node, name.split(":", 1)[0])
        if not re.fullmatch(r"https?://xbrl\.sec\.gov/dei/\d{4}(?:-\d{2}-\d{2})?", namespace or ""):
            continue
        lexical = re.sub(r"\s", "", _text(node))
        cik = lexical.zfill(10) if re.fullmatch(r"\d{1,10}", lexical) else None
        contexts = [c for c in document.xpath("//*[@id]") if c.get("id") == node.get("contextref")
                    and _official_identity_element(c, "context", xbrli)]
        identifiers = [i for context in contexts for entity in context
                       if _official_identity_element(entity, "entity", xbrli)
                       for i in entity if _official_identity_element(i, "identifier", xbrli)]
        identifier_texts = [re.sub(r"\s", "", _text(i)) for i in identifiers]
        context_ciks = {v.zfill(10) if re.fullmatch(r"\d{1,10}", v) else None for v in identifier_texts}
        if cik != filing[0] or len(contexts) != 1 or len(identifiers) != 1 or context_ciks != {filing[0]}:
            return {"status": "HOLD", "reason": "OFFICIAL_DEI_CIK_CONTEXT_IDENTITY_MISMATCH"}
        identities.add(cik)
        citation = {"cik": filing[0], "accession": filing[1], "source_pin": entry["source_pin"],
                    "xpath": _xpath(node), "expected_text": _text(node), "qname": name,
                    "namespace_uri": namespace, "context_ref": node.get("contextref"),
                    "normalized_cik": cik, "hidden_metadata": not _visible(node)}
        identifier_citation = {"cik": filing[0], "accession": filing[1], "source_pin": entry["source_pin"],
                               "xpath": _xpath(identifiers[0]), "expected_text": _text(identifiers[0]),
                               "namespace_uri": xbrli, "identity_role": "CONTEXT_ENTITY_IDENTIFIER",
                               "context_ref": node.get("contextref"), "normalized_cik": cik}
        _cite([citation, identifier_citation])
        citations.extend([citation, identifier_citation])
    if identities != {filing[0]}:
        return {"status": "HOLD", "reason": "OFFICIAL_DEI_CIK_NOT_AVAILABLE"}
    return {"status": "VERIFIED", "citations": citations}


def _single_common_cover(documents: list[dict], filing: tuple[str, str]) -> dict:
    titles, refs, issuer_refs = set(), [], []
    for entry in documents:
        if (entry["cik"], entry["accession"]) != filing:
            continue
        doc = _document(entry["source_pin"])
        for node in doc.xpath("//*[@name]"):
            name = node.get("name", "")
            if name.split(":")[-1] != "Security12bTitle" or ":" not in name or not _visible(node):
                continue
            prefix = name.split(":")[0]
            namespace = next((n.get("xmlns:"+prefix) for n in (node, *node.iterancestors()) if n.get("xmlns:"+prefix)), None)
            if not re.fullmatch(r"https?://xbrl\.sec\.gov/dei/\d{4}(?:-\d{2}-\d{2})?", namespace or ""):
                continue
            title = _text(node)
            normalized = " ".join(title.lower().split())
            if re.search(r"\b(notes?|bonds?|debentures?)\b", normalized) and not re.search(r"\b(common|preferred|ordinary)\b", normalized):
                continue  # Debt securities are not additional common equity classes.
            issuer = _cover_issuer_identity(doc, entry, filing)
            if issuer["status"] != "VERIFIED":
                titles.add("SOURCE_ISSUER_IDENTITY_NOT_CONFIRMED")
                continue
            issuer_refs.extend(issuer["citations"])
            if (not re.search(r"\bcommon\s+(stock|shares)\b", normalized)
                or re.search(r"\b(class|preferred|depositary|deposit[oa]ry|ads|ordinary)\b", normalized)):
                titles.add("UNSUPPORTED:"+normalized)
            else:
                titles.add("SINGLE_COMMON_CLASS")
            refs.append({"cik": filing[0], "accession": filing[1], "source_pin": entry["source_pin"],
                         "xpath": _xpath(node), "expected_text": title})
    if titles != {"SINGLE_COMMON_CLASS"}:
        return {"status": "HOLD", "reason": "SINGLE_COMMON_CLASS_DEI_COVER_NOT_CONFIRMED", "filing": list(filing), "titles": sorted(titles)}
    issuer_refs = list({(c["source_pin"]["path"], c["xpath"]): c for c in issuer_refs}.values())
    return {"status": "VERIFIED", "citations": refs, "issuer_identity_citations": issuer_refs}


def _comparative_conflicts(proposal: dict, source_rows: list[dict]) -> list[dict]:
    conflicts = []
    index = _selection_index(proposal["source_rows"])
    for row in source_rows:
        if row["source_kind"] != "RAW_XBRL" or not row["role"].endswith(("_eps", "_shares", "_numerator")):
            continue
        key = (row["cik"], row["start"], row["end"], row["role"], encoded(row["dimensions"]))
        peers = index.get(key, [])
        iv = _interval(row["value"], row.get("decimals"))
        for peer in peers:
            if peer["accession"] == row["accession"]:
                continue
            piv = _interval(peer["value"], peer.get("decimals"))
            if (peer["unit"] != row["unit"] or iv is None or piv is None or not _compatible(iv, piv)):
                conflicts.append({"source_fact_key": row["fact_key"], "comparative_fact_key": peer["fact_key"]})
    return conflicts


def _current_grant_binding(grant: dict) -> dict | None:
    for pin in grant.get("evidence_pins", []):
        receipt = _json(pin)
        if (receipt.get("schema_version") != "price-metrics-root-binding-acceptance-v1"
            or receipt.get("reviewer") != "ROOT" or receipt.get("status") != "APPROVED_FOR_EXACT_TYPED_BINDING"
            or receipt.get("security_id") != grant["security_id"] or not receipt.get("proposal")):
            continue
        proposal = _json(receipt["proposal"])
        for declaration in proposal.get("declarations", []):
            if (declaration.get("role") == "common_shares"
                and declaration.get("share_measure") == "OUTSTANDING_COMMON_EX_TREASURY"
                and declaration.get("dimensions") == []
                and declaration.get("cik") == grant["cik"]
                and declaration.get("period_end") == grant["financial_anchor"]
                and all(declaration.get(k) == grant.get(g) for k, g in (("stock_class_id", "stock_class_id"),
                    ("split_basis_id", "split_basis_id"), ("scope_id", "financial_scope_id")))):
                return {"acceptance": pin, "proposal": receipt["proposal"], "stock_class_id": grant["stock_class_id"]}
    return None


def _basis_bridge(proposal: dict, row: dict, grant: dict, source_rows: list[dict], cutoff: str) -> dict:
    """Verify the retained price-event scope plus SEC class/recast source basis.

    The supplier inventory covers reported split candidates, not all corporate
    actions. SEC accounting evidence remains necessary for reporting recasts.
    """
    config = _json(proposal["config"])
    result = {"status": "HOLD", "source_fact_keys": sorted(r["fact_key"] for r in source_rows),
              "start": row["fy_start"], "end": cutoff, "security_id": grant["security_id"]}
    def hold(reason: str, **details: object) -> dict:
        return dict(result, reason=reason, **details)
    if not config.get("basis_price_batch") or not config.get("source_catalog"):
        return hold("SOURCE_CLASS_SPLIT_RECAST_BASIS_BRIDGE_NOT_AVAILABLE")
    claims = {c["claim"] for c in row["accounting_evidence"]["claims"]}
    if "SOURCE_REPORTING_BASIS_REVIEW_SUPPORTED" not in claims:
        return hold("SOURCE_REPORTING_BASIS_REVIEW_NOT_SUPPORTED")
    if any(row["accounting_evidence"].get(k) != grant.get(g) for k, g in (("stock_class_id", "stock_class_id"),
            ("split_basis_id", "split_basis_id"), ("financial_scope_id", "financial_scope_id"))):
        return hold("CURRENT_GRANT_CLASS_SPLIT_SCOPE_MISMATCH")
    binding = _current_grant_binding(grant)
    if binding is None:
        return hold("EXISTING_GRANT_CLASS_SCOPE_ACCEPTANCE_NOT_BOUND")
    catalog = _json(config["source_catalog"])
    covers = [_single_common_cover(catalog["documents"], f) for f in sorted({(r["cik"], r["accession"]) for r in source_rows})]
    if any(c["status"] != "VERIFIED" for c in covers):
        return hold("SEC_SOURCE_COMMON_CLASS_COVER_INCOMPLETE", covers=covers)
    visible_sources = [_visible_raw_binding(r, catalog["documents"]) for r in source_rows if r["source_kind"] == "RAW_XBRL"]
    if any(r["status"] != "VERIFIED" for r in visible_sources):
        return hold("VISIBLE_SOURCE_FACT_PERIOD_UNIT_VALUE_BINDING_INCOMPLETE", source_bindings=visible_sources)
    conflicts = _comparative_conflicts(proposal, source_rows)
    if conflicts:
        return hold("REPORTED_EPS_SHARE_COMPARATIVE_BASIS_CONFLICT", conflicts=conflicts)
    batch = _json(config["basis_price_batch"])
    if (batch.get("schema_version") != "price-metric-canonical-batch-v1"
        or batch.get("query", {}).get("start_date", "9999") > row["fy_start"]
        or batch.get("query", {}).get("end_date", "0000") < cutoff):
        return hold("BASIS_PRICE_BATCH_RANGE_INCOMPLETE")
    securities = [s for s in batch["securities"] if s["security_id"] == grant["security_id"] and s["cik"] == row["cik"] and s["ticker"] == row["ticker"]]
    if len(securities) != 1 or not batch.get("currency_evidence") or not batch.get("currency_manifest"):
        return hold("EXACT_BASIS_SECURITY_OR_CAPTURE_EVIDENCE_NOT_AVAILABLE")
    security = securities[0]
    sidecar, accepted = _json(batch["currency_evidence"]), _json(batch["currency_manifest"])
    if (accepted.get("status") != "accepted" or accepted.get("manifest_contract") != "price-capture-evidence-delivery.v1"
        or accepted["artifacts"]["sidecar.json"]["sha256"] != batch["currency_evidence"]["sha256"]
        or sidecar.get("schema_contract") != "price-capture-evidence.v1"
        or sidecar["input_pins"]["price.parquet"]["sha256"] != batch["lineage"]["sha256"]
        or sidecar["input_pins"]["security.parquet"]["sha256"] != batch["lineage"]["security_sha256"]):
        raise ValueError("basis sidecar differs from accepted canonical price batch")
    pins = sidecar["input_pins"]
    for name in ("price.parquet", "security.parquet", "inventory_manifest", "reviewed_actions", "normalizer_source"):
        _bytes(pins[name])
    inventory = _json(pins["inventory_manifest"])
    captures = [c for c in sidecar["securities"] if c["security_id"] == security["security_id"]]
    if len(captures) != 1:
        return hold("EXACT_BASIS_CAPTURE_NOT_AVAILABLE")
    capture = captures[0]
    cp_pin = {"path": capture["checkpoint_path"], "sha256": capture["checkpoint_sha256"]}
    checkpoint = _json(cp_pin)
    if any(checkpoint.get(k) != v for k, v in (("security_id", security["security_id"]), ("yahoo_symbol", security["yahoo_symbol"]),
            ("status", "ok"), ("raw_sha256", capture["raw_sha256"]), ("requested_period1", capture["requested_period1"]))):
        raise ValueError("basis raw checkpoint identity differs")
    period1, period2 = capture["requested_period1"], sidecar["factor_horizon_period2"]
    url = urlparse(capture["request_url"])
    query = parse_qs(url.query)
    if (checkpoint["url"] != capture["request_url"] or inventory.get("events") != "splits"
        or url.scheme != "https" or url.netloc != "query1.finance.yahoo.com"
        or unquote(url.path) != "/v8/finance/chart/"+security["yahoo_symbol"]
        or query != {"period1": [str(period1)], "period2": [str(period2)], "interval": ["1d"], "events": ["splits"], "includeAdjustedClose": ["false"]}
        or datetime.fromtimestamp(period1, UTC).date().isoformat() > row["fy_start"]
        or datetime.fromtimestamp(period2, UTC).date().isoformat() <= cutoff):
        return hold("BASIS_EVENT_CAPTURE_REQUEST_RANGE_OR_SEMANTICS_INCOMPLETE")
    compressed_pin = {"path": capture["raw_path"], "sha256": capture["compressed_raw_sha256"]}
    payload = gzip.decompress(_bytes(compressed_pin))
    if hashlib.sha256(payload).hexdigest() != capture["raw_sha256"]:
        raise ValueError("basis raw response decompressed hash differs")
    dependencies = config.get("basis_normalizer_dependencies", {})
    package = Path(pins["normalizer_source"]["path"]).parent
    required_dependencies = {"__init__.py", "adapters/yahoo_price.py", "security.py"}
    if (package / "adapters/__init__.py").exists():
        required_dependencies.add("adapters/__init__.py")
    if set(dependencies) != required_dependencies:
        return hold("SUPPLIER_NORMALIZER_EXECUTION_CLOSURE_NOT_PINNED")
    for relative, dependency in dependencies.items():
        if Path(dependency["path"]) != package / relative:
            raise ValueError("supplier normalizer dependency path differs")
        _bytes(dependency)
    normalized, diagnostic = _supplier_replay(pins["normalizer_source"], payload, security, period1, period2, _bytes(pins["reviewed_actions"]))
    if diagnostic.get("status") != "ok" or diagnostic.get("source_sha256") != capture["raw_sha256"]:
        return hold("SUPPLIER_BASIS_NORMALIZATION_NOT_VERIFIED")
    raw = json.loads(payload)["chart"]["result"][0]
    tz = ZoneInfo(raw["meta"]["exchangeTimezoneName"])
    if raw["meta"].get("symbol", "").upper() != security["yahoo_symbol"].upper():
        raise ValueError("basis response symbol differs")
    relevant_events = []
    for key, event in (raw.get("events") or {}).get("splits", {}).items():
        try:
            day = datetime.fromtimestamp(int(event["date"]), tz).date().isoformat()
            keyday = datetime.fromtimestamp(int(key), tz).date().isoformat()
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            return hold("BASIS_SPLIT_EVENT_DATE_UNKNOWN")
        if row["fy_start"] <= day <= cutoff or row["fy_start"] <= keyday <= cutoff:
            relevant_events.append({"key": key, "event": event, "exchange_day": day})
    # No net-factor shortcut: an offsetting split pair and unknown events still hold.
    if relevant_events:
        return hold("SPLIT_OR_UNKNOWN_CANDIDATE_IN_EPS_BASIS_WINDOW", events=relevant_events)
    selected_prices = [p for p in batch["prices"] if p["security_id"] == security["security_id"] and row["fy_start"] <= p["trade_date"] <= cutoff]
    canonical = {p["trade_date"].isoformat(): p for p in normalized if row["fy_start"] <= p["trade_date"].isoformat() <= cutoff}
    if (not selected_prices or max(p["trade_date"] for p in selected_prices) != cutoff
        or any(finite(p.get("split_factor")) != 1 for p in selected_prices)
        or any(day not in canonical or finite(canonical[day].get("split_factor")) != 1 for day in [p["trade_date"] for p in selected_prices])):
        return hold("BASIS_CANONICAL_SPLIT_FACTOR_NOT_EXACT_ONE_OR_COVERAGE_INCOMPLETE")
    return dict(result, status="VERIFIED", reason=None, price_batch=config["basis_price_batch"],
                source_catalog=config["source_catalog"], covers=covers,
                current_grant_binding=binding, source_bindings=visible_sources,
                capture_pins=[batch["currency_evidence"], batch["currency_manifest"], cp_pin, compressed_pin, *pins.values(), *dependencies.values()],
                event_scope="RETAINED_YAHOO_SPLIT_CANDIDATES_NOT_ALL_CORPORATE_ACTION_CERTIFICATION",
                known_old_event_count=len((raw.get("events") or {}).get("splits", {})),
                source_reporting_basis_claim="SOURCE_REPORTING_BASIS_REVIEW_SUPPORTED")


def _visible(node: object) -> bool:
    return not any(str(n.tag).split(":")[-1].lower() == "hidden" or n.get("hidden") is not None
                   or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", n.get("style", ""), re.IGNORECASE)
                   for n in (node, *node.iterancestors()))


def _official_cell_period(record: dict, cell: object, row: object) -> None:
    """Bind a cell to its logical column's duration and end-date headers."""
    table = row.xpath("ancestor::table[1]")
    if len(table) != 1:
        raise ValueError("official component requires one source table")
    selected = cell
    while selected.getparent() is not row:
        selected = selected.getparent()
        if selected is None:
            raise ValueError("official component value is outside its row")
    column = 0
    for c in row.xpath("./td|./th"):
        if c is selected:
            break
        column += int(c.get("colspan", "1"))
    headers = []
    for tr in table[0].xpath("./tr|./tbody/tr"):
        if tr is row:
            break
        position = 0
        for c in tr.xpath("./td|./th"):
            width = int(c.get("colspan", "1"))
            if position <= column < position+width:
                headers.append(_text(c))
            position += width
    header = " ".join(headers)
    months = re.findall(r"\b(Three|Six|Nine|Twelve)\s+Months\s+Ended\s+([A-Za-z]+)\s+(\d{1,2})", header, re.IGNORECASE)
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", header))
    # Small synthetic adapters can provide an explicit complete date in the same header.
    if not months:
        raise ValueError("official component period header is not supported for its selected column")
    end = date.fromisoformat(record["end"])-timedelta(days=1)
    expected = "three" if 75 <= _days(record["start"], record["end"]) <= 105 else "nine" if 245 <= _days(record["start"], record["end"]) <= 300 else "twelve" if 350 <= _days(record["start"], record["end"]) <= 378 else None
    valid = False
    for duration, month, day in months:
        try:
            parsed = datetime.strptime(month+" "+day, "%B %d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if duration.lower() == expected and parsed.month == end.month and parsed.day == end.day and str(end.year) in years:
            valid = True
    if not valid:
        raise ValueError("official component selected column period differs from source Context")


def _closed_eps_section(table: object) -> dict:
    rows = table.xpath("./tr|./tbody/tr")
    labels = []
    for tr in rows:
        texts = [_text(c) for c in tr.xpath("./td|./th")]
        text = next((t for t in texts if re.search(r"[A-Za-z]", t)), "")
        if text:
            labels.append((tr, " ".join(text.lower().replace("−", "-").split())))
    starts = [i for i, (_, label) in enumerate(labels) if re.fullmatch(r"net income(?:\s*\(loss\))?", label)]
    patterns = [r"net income(?:\s*\(loss\))?", r"basic earnings per share", r"diluted earnings per share",
                r"weighted[- ]average shares used in computation of earnings per share:?", r"basic", r"diluted"]
    for start in starts:
        section = labels[start:]
        if len(section) == 6 and all(re.fullmatch(pattern, label) for pattern, (_, label) in zip(patterns, section, strict=True)):
            return {"status": "VERIFIED", "rule": "SINGLE_COMMON_NI_BASIC_DILUTED_CLOSED_SECTION_V1",
                    "table_xpath": _xpath(table), "row_xpaths": [_xpath(tr) for tr, _ in section]}
    return {"status": "HOLD", "reason": "CLOSED_COMMON_NET_INCOME_EPS_EQUATION_NOT_SUPPORTED",
            "observed_labels": [label for _, label in labels]}


def _ix_period(document: object, node: object, source: dict) -> bool:
    context_id = node.get("contextref")
    contexts = [c for c in document.xpath("//*[@id]") if c.get("id") == context_id and str(c.tag).split(":")[-1].lower() == "context"]
    if len(contexts) != 1:
        return False
    context = contexts[0]
    elements = {str(c.tag).split(":")[-1].lower(): _text(c) for c in context.iterdescendants()}
    if any(str(c.tag).split(":")[-1].lower() in {"explicitmember", "typedmember"} for c in context.iterdescendants()):
        return False
    try:
        end = (date.fromisoformat(elements["enddate"])+timedelta(days=1)).isoformat()
    except (KeyError, ValueError):
        return False
    return (elements.get("startdate") == source["start"] and end == source["end"]
            and elements.get("identifier", "").zfill(10) == source["cik"] and source["dimensions"] == [])


def _source_equation_gate(candidate: dict, config: dict) -> dict:
    """An exact, visible closed EPS equation, never word co-occurrence alone."""
    if not config.get("source_catalog"):
        return {"status": "HOLD", "reason": "SOURCE_EPS_EQUATION_CATALOG_NOT_AVAILABLE"}
    catalog = _json(config["source_catalog"])
    components = candidate["components"]
    direct = all(components["Q4_"+k]["status"] == "AVAILABLE" for k in ("numerator", "shares"))
    names = ["Q4_numerator"] if direct else ["FY_numerator", "9M_numerator"]
    bindings, failures = [], []
    for name in names:
        for source in components[name]["sources"]:
            # Explicit common-numerator tags are candidates, not final EPS proof.
            # They must bind to this same supported, complete visible equation.
            matched = []
            documents = [d for d in catalog["documents"] if (d["cik"], d["accession"]) == (source["cik"], source["accession"])]
            if source["source_kind"] == "OFFICIAL_REPORTED_TABLE":
                documents = [{"source_pin": source["source_pin"]}]
            for entry in documents:
                doc = _document(entry["source_pin"])
                if source["source_kind"] == "OFFICIAL_REPORTED_TABLE":
                    cells = doc.xpath(source["locator"]["value_xpath"])
                else:
                    cells = []
                    for node in doc.xpath("//*[@name]"):
                        qname = node.get("name", "")
                        if (":" not in qname or qname.split(":")[-1] != source["local_name"]
                            or _source_namespace(node, qname.split(":")[0]) != source["namespace"]
                            or not _visible(node) or not _ix_period(doc, node, source)):
                            continue
                        lexical = _text(node).replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
                        value = finite(lexical)
                        if value is not None:
                            value = value.scaleb(int(node.get("scale", "0")))
                            if node.get("sign") == "-":
                                value = -value
                        if value == finite(source["value"]):
                            cells.append(node)
                for cell in cells:
                    if not _visible(cell):
                        continue
                    tables = cell.xpath("ancestor::table[1]")
                    if len(tables) != 1:
                        continue
                    structure = _closed_eps_section(tables[0])
                    source_row = cell.xpath("ancestor::tr[1]")
                    if (structure["status"] == "VERIFIED" and len(source_row) == 1
                        and _xpath(source_row[0]) == structure["row_xpaths"][0]):
                        matched.append({"source_fact_key": source["fact_key"], "source_pin": entry["source_pin"],
                            "cell_xpath": _xpath(cell), "period_start": source["start"],
                            "period_end": source["end"], "value": source["value"], **structure})
            if matched:
                bindings.extend(matched)
            else:
                failures.append({"source_fact_key": source["fact_key"], "reason": "PARENT_COMMON_NUMERATOR_VISIBLE_CLOSED_EQUATION_NOT_BOUND"})
    return {"status": "HOLD" if failures else "VERIFIED", "reason": "SOURCE_EPS_NUMERATOR_EQUATION_NOT_PROVEN" if failures else None,
            "bindings": bindings, "failures": failures}


def _source_namespace(node: object, prefix: str) -> str | None:
    return next((n.get("xmlns:"+prefix) for n in (node, *node.iterancestors()) if n.get("xmlns:"+prefix)), None)


def _visible_raw_binding(source: dict, documents: list[dict]) -> dict:
    bindings = []
    for entry in documents:
        if (entry["cik"], entry["accession"]) != (source["cik"], source["accession"]):
            continue
        _verify_once(entry["source_pin"])
        cache_key = ("raw_visible", entry["source_pin"]["sha256"], source["namespace"], source["local_name"],
                     source["start"], source["end"], source["cik"], encoded(source["dimensions"]), encoded(source["unit"]), source["value"])
        if cache_key in _MATCH_CACHE:
            bindings.extend([{**b, "source_fact_key": source["fact_key"]} for b in _MATCH_CACHE[cache_key]])
            continue
        doc = _document(entry["source_pin"])
        found = []
        for node in doc.xpath("//*[@name]"):
            qname = node.get("name", "")
            if (":" not in qname or qname.split(":")[-1] != source["local_name"]
                or _source_namespace(node, qname.split(":")[0]) != source["namespace"]
                or not _visible(node) or not _ix_period(doc, node, source)):
                continue
            lexical = _text(node).replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
            value = finite(lexical)
            if value is not None:
                value = value.scaleb(int(node.get("scale", "0")))
                if node.get("sign") == "-":
                    value = -value
            if value != finite(source["value"]):
                continue
            units = [u for u in doc.xpath("//*[@id]") if u.get("id") == node.get("unitref") and str(u.tag).split(":")[-1].lower() == "unit"]
            if len(units) != 1:
                continue
            actual = [[], []]
            for measure in units[0].iterdescendants():
                if str(measure.tag).split(":")[-1].lower() != "measure":
                    continue
                text = _text(measure)
                if ":" not in text:
                    continue
                prefix, local = text.split(":", 1)
                uri = _source_namespace(measure, prefix)
                normalized = "iso4217:USD" if local == "USD" and uri == "http://www.xbrl.org/2003/iso4217" else "xbrli:shares" if local == "shares" and uri == "http://www.xbrl.org/2003/instance" else None
                if normalized is None:
                    continue
                denominator = any(str(a.tag).split(":")[-1].lower() == "unitdenominator" for a in measure.iterancestors())
                actual[1 if denominator else 0].append(normalized)
            if actual == source["unit"]:
                found.append({"source_fact_key": source["fact_key"], "source_pin": entry["source_pin"],
                              "xpath": _xpath(node), "period_start": source["start"],
                              "period_end": source["end"], "value": source["value"], "unit": source["unit"]})
        _cache_match(cache_key, found)
        bindings.extend(found)
    return {"status": "VERIFIED" if bindings else "HOLD", "source_fact_key": source["fact_key"],
            "bindings": bindings, "reason": None if bindings else "VISIBLE_RAW_SOURCE_CELL_NOT_BOUND"}
