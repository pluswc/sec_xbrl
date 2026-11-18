"""Offline preparation of effective CAL and reported inputs for EPS validation."""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections import defaultdict
from datetime import date
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sec_xbrl.facts.layer1 import (
    Layer1Extractor,
    _context_row,
    _fact_id,
    _qname_parts,
    select_fact_corpus,
)
from sec_xbrl.filing.contracts import FilingRef
from sec_xbrl.filing.filing_index import ArelleFilingLoader, FilingIndex, ResolvedFiling
from sec_xbrl.filing.layer1_ingestion import Layer1Ingestor
from sec_xbrl.longitudinal.corpus_release import _load_declared_cohort_snapshot
from sec_xbrl.metrics.market_inputs import pinned_json
from sec_xbrl.relationships.layer1 import RelationshipExtractor

SCHEMA = "cal-eps-filing-v1"
FASB_NAMESPACE = re.compile(r"https?://fasb\.org/us-gaap/\d{4}(?:-\d{2}-\d{2})?\Z")
_PARTICIPATING_NAME = re.compile(r"participatingsecurit|twoclass", re.IGNORECASE)

# These amount concepts are relevant counterevidence even when an EPS CAL
# network omits them. Retaining them does not assert a missing adjustment is 0.
EPS_NUMERATOR_ADJUSTMENT_NAMES = frozenset({
    "DividendsPreferredStock", "DividendsPreferredStockCash",
    "DividendsPreferredStockPaidinkind", "DividendsPreferredStockStock",
    "RedeemablePreferredStockDividends", "OtherPreferredStockDividendsAndAdjustments",
    "PreferredStockDividendsAndOtherAdjustments", "PreferredStockDividendsIncomeStatementImpact",
    "PreferredStockAccretionOfRedemptionDiscount", "InterestOnConvertibleDebtNetOfTax",
    "UndistributedEarningsLossAllocatedToParticipatingSecuritiesBasic",
    "UndistributedEarningsLossAllocatedToParticipatingSecuritiesDiluted",
})

EPS_NAMES = frozenset({
    "EarningsPerShareBasic", "EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerBasicShare",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingDiluted",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
    "NetIncomeLoss", "ProfitLoss", "IncomeLossFromContinuingOperations",
    "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsAttributableToParent",
    "IncomeLossFromDiscontinuedOperationsNetOfTax",
    "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
    "IncomeLossFromDiscontinuedOperationsNetOfTaxPerBasicShare",
    "IncomeLossFromDiscontinuedOperationsNetOfTaxPerDilutedShare",
    "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
}) | EPS_NUMERATOR_ADJUSTMENT_NAMES


def _file_sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def is_participating_adjustment(local_name: str) -> bool:
    """Identify the counterevidence retained and checked at the EPS boundary."""
    return _PARTICIPATING_NAME.search(local_name) is not None


def verify_file(pin: dict) -> Path:
    """Return an existing file after verifying exact bytes and local provenance."""
    path = Path(pin["path"])
    if not path.is_absolute() or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("CAL EPS source pin requires an absolute regular file")
    if _file_sha(path) != pin["sha256"]:
        raise ValueError(f"CAL EPS source hash differs: {path}")
    return path


def _unit_key(unit: Any) -> list[list[list[str]]]:
    return [sorted([namespace, local] for namespace, _, local in map(_qname_parts, measures))
            for measures in unit.measures]


def _context_equivalence(filing_id: str, contexts: list[Any]) -> dict[str, str]:
    """Arelle compares period, entity, explicit/typed dimensions and residual context."""
    buckets = defaultdict(list)
    result = {}
    keys = sorted((_context_row(filing_id, c)[0]["context_id"], c) for c in contexts)
    for key, ctx in keys:
        peers = buckets[ctx.contextDimAwareHash]
        representative = next((peer for peer, other in peers if ctx.isEqualTo(other, True)), None)
        if representative is None:
            representative = key
            peers.append((key, ctx))
        result[key] = representative
    return result


def _visible_table(fact: Any) -> dict | None:
    if getattr(fact, "localName", "").lower() != "nonfraction":
        return None
    ancestors = list(fact.iterancestors())
    if any(n.get("hidden") is not None or getattr(n, "localName", "").lower() == "hidden"
           or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", n.get("style", ""), re.IGNORECASE)
           for n in (fact, *ancestors)):
        return None
    row = next((n for n in ancestors if getattr(n, "localName", "").lower() == "tr"), None)
    table = next((n for n in ancestors if getattr(n, "localName", "").lower() == "table"), None)
    if row is None or table is None:
        return None
    tree = table.getroottree()
    return {"table_xpath": tree.getpath(table), "row_xpath": tree.getpath(row), "inline_id": fact.id}


def _select_networks(tables: Any, roots: set[str]) -> tuple[list[dict], set[str]]:
    """Retain a closed parent→child neighborhood in each effective base set."""
    by_network = defaultdict(lambda: defaultdict(list))
    for row in tables.relationships:
        key = (row["role_id"], row["arcrole"], row["link_qname"], row["arc_qname"])
        by_network[key][row["from_raw_concept_id"]].append(row)
    relationships, concepts = {}, set(roots)
    for outgoing in by_network.values():
        frontier = sorted(roots & outgoing.keys())
        seen = set()
        while frontier:
            parent = frontier.pop()
            if parent in seen:
                continue
            seen.add(parent)
            for arc in outgoing[parent]:
                child = arc["to_raw_concept_id"]
                relationships[arc["relationship_id"]] = arc
                concepts.add(child)
                if child in outgoing:
                    frontier.append(child)
    return sorted(relationships.values(), key=lambda r: r["relationship_id"]), concepts


def _projection_roots(concepts: dict[str, dict]) -> set[str]:
    return {key for key, concept in concepts.items()
            if (concept["local_name"] in EPS_NAMES and FASB_NAMESPACE.fullmatch(concept["namespace_uri"]))
            or is_participating_adjustment(concept["local_name"])}


def _member_index(package: Path) -> dict[str, dict]:
    with zipfile.ZipFile(package) as source:
        members = defaultdict(list)
        for member in source.namelist():
            if not member.endswith("/"):
                members[Path(member).name].append(member)
        return {name: {"member": names[0], "sha256": hashlib.sha256(source.read(names[0])).hexdigest()}
                for name, names in members.items() if len(names) == 1}


def _eps_policy_occurrences(model: Any) -> list[dict]:
    result = []
    for fact in select_fact_corpus(model).facts:
        concept = getattr(fact, "concept", None)
        if not getattr(concept, "isTextBlock", False) or getattr(fact, "isNil", False):
            continue
        value = getattr(fact, "value", "")
        if not re.search(r"treasury(?:[-\s]+|&nbsp;)stock(?:[-\s]+|&nbsp;)method", value, re.IGNORECASE):
            continue
        from lxml import html

        text = " ".join(html.fromstring(f"<div>{value}</div>").text_content().split())
        for match in re.finditer(r"treasury[-\s]+stock[-\s]+method", text, re.IGNORECASE):
            snippet = text[max(0, match.start() - 350):match.end() + 350]
            if (re.search(r"earnings\s+per\s+share|dilut\w+\s+(?:\w+\s+){0,4}shares|diluted\s+eps", snippet, re.IGNORECASE)
                and re.search(r"options?|stock[-\s]+based|share[-\s]+based|equity[-\s]+based|restricted\s+stock|awards?", snippet, re.IGNORECASE)):
                result.append({"source_document": fact.modelDocument.basename,
                               "source_locator": f"line:{fact.sourceline}", "inline_id": fact.id,
                               "concept": str(fact.qname), "snippet": snippet})
    return sorted(result, key=lambda x: (x["source_document"], x["source_locator"], x["inline_id"] or "", x["snippet"]))


def _project_model(model: Any, ref: FilingRef, raw: Any, members: dict) -> dict:
    # Reuse the exact Raw parser for identities, fact values and dimensions.
    replay = Layer1Extractor().extract(model, ref)
    filing_id = replay.filing[0]["filing_id"]
    relationships = RelationshipExtractor().extract(model, ref, network_types=frozenset({"CAL"}))
    raw_concepts = {r["raw_concept_id"]: dict(r) for r in raw.records("concept")}
    concepts = {r["raw_concept_id"]: r for r in relationships.concepts} | raw_concepts
    roots = _projection_roots(concepts)
    arcs, retained = _select_networks(relationships, roots)
    for arc in arcs:
        member = members.get(arc["source_document"])
        if not member or not arc["source_locator"]:
            raise ValueError("effective CAL arc lacks an identifiable original package member")
        arc["source_member"] = member
    raw_facts = {r["fact_id"]: r for r in raw.records("fact") if r["raw_concept_id"] in retained}
    raw_contexts = {r["context_id"]: r for r in raw.records("context")}
    raw_units = {r["unit_id"]: r for r in raw.records("unit")}
    replay_contexts = {r["context_id"]: r for r in replay.contexts}
    replay_units = {r["unit_id"]: r for r in replay.units}
    raw_dimensions, replay_dimensions = defaultdict(list), defaultdict(list)
    for row in raw.records("dimension_fact"):
        if row["fact_id"] in raw_facts:
            raw_dimensions[row["fact_id"]].append(dict(row))
    for row in replay.dimension_facts:
        if row["fact_id"] in raw_facts:
            replay_dimensions[row["fact_id"]].append(row)
    raw_bind_fields = ("raw_concept_id", "context_id", "unit_id", "value_numeric", "decimals", "precision",
                       "is_nil", "source_document", "source_locator", "reported_or_derived")
    original_facts = {_fact_id(filing_id, fact, i): fact for i, fact in enumerate(select_fact_corpus(model).facts)}
    context_keys = _context_equivalence(filing_id, list(model.contexts.values()))
    facts, matched = [], set()
    for fact in replay.facts:
        if fact["raw_concept_id"] not in retained:
            continue
        fact_id = fact["fact_id"]
        original = original_facts[fact_id]
        peer = raw_facts.get(fact_id)
        ctx = replay_contexts.get(fact["context_id"])
        if peer is None or any(fact[f] != peer[f] for f in raw_bind_fields):
            raise ValueError("CAL EPS source fact differs from immutable Raw")
        if ctx != raw_contexts.get(fact["context_id"]) or replay_units.get(fact["unit_id"]) != raw_units.get(fact["unit_id"]):
            raise ValueError("CAL EPS source Context or unit differs from immutable Raw")
        if raw_dimensions[fact_id] != replay_dimensions[fact_id]:
            raise ValueError("CAL EPS source dimensions differ from immutable Raw")
        matched.add(fact_id)
        if not ctx or ctx["period_kind"] != "DURATION":
            continue
        dims = [{**r, "axis": [raw_concepts[r["axis_raw_concept_id"]][f] for f in ("namespace_uri", "local_name")],
                 "member": [raw_concepts.get(r["member_raw_concept_id"], {}).get(f) for f in ("namespace_uri", "local_name")]}
                for r in raw_dimensions[fact_id]]
        facts.append({**{key: fact[key] for key in ("fact_id", "raw_concept_id", *raw_bind_fields[1:])},
                      "start": ctx["start_date"], "end": ctx["end_date"], "entity_identifier": ctx["entity_identifier"],
                      "context_key": context_keys[fact["context_id"]], "dimensions": dims,
                      "unit": _unit_key(original.unit) if original.unit is not None else None,
                      "source_table": _visible_table(original)})
    if matched != set(raw_facts):
        raise ValueError("CAL EPS source fact inventory differs from immutable Raw")
    return {"concepts": [concepts[k] for k in sorted(retained)],
            "roles": [r for r in relationships.roles if r["role_id"] in {a["role_id"] for a in arcs}],
            "relationships": arcs, "facts": sorted(facts, key=lambda f: f["fact_id"]),
            "eps_treasury_stock_policy": _eps_policy_occurrences(model)}


def prepare_cal_eps_filing(snapshot: dict, package: dict, *, taxonomy_cache: Path) -> dict:
    """Project one pinned accession with the shared Raw and Arelle CAL extractors."""
    manifest_path = verify_file(snapshot["manifest"])
    manifest = pinned_json(snapshot["manifest"])
    raw = _load_declared_cohort_snapshot(manifest_path.parent, manifest["cik"], manifest["accession"])
    if (snapshot["snapshot_id"] != raw.input.snapshot_id
        or snapshot["table_sha256"] != dict(raw.table_sha256) or package["sha256"] != raw.manifest.package_sha256):
        raise ValueError("CAL EPS package or Raw snapshot identity differs")
    package_path = verify_file(package)
    filing = dict(raw.records("filing")[0])
    ref = FilingRef(filing["cik"], filing["accession"], filing["form"],
                    date.fromisoformat(filing["filed_date"]), date.fromisoformat(filing["report_date"]),
                    filing["primary_document"])
    resolved = ResolvedFiling(ref, FilingIndex(ref.cik, ref.accession, filing["source_url"], ()),
                              package_path, ref.primary_document)
    with TemporaryDirectory(prefix="cal-eps-") as temporary:
        model = ArelleFilingLoader(taxonomy_cache=Path(taxonomy_cache)).load(resolved, Path(temporary))
        try:
            ingestion = Layer1Ingestor(Path(temporary) / "unused")
            ingestion._validate_model(model)
            projection = _project_model(model, ref, raw, _member_index(package_path))
            ingestion._validate_model(model)
        finally:
            controller = model.modelManager.cntlr
            model.close()
            controller.close()
    verify_file(package)
    return {"schema_version": SCHEMA, "snapshot": snapshot, "package": package, "filing": filing,
            "arelle_version": version("arelle-release"), "relationship_parser": RelationshipExtractor.parser_version,
            **projection}


def verify_cal_eps_filing(pin: dict, *, taxonomy_cache: Path) -> dict:
    """Replay an exact prepared projection from its original local SEC package."""
    prepared = pinned_json(pin)
    if prepared.get("schema_version") != SCHEMA or prepared != prepare_cal_eps_filing(
        prepared["snapshot"], prepared["package"], taxonomy_cache=taxonomy_cache
    ):
        raise ValueError("CAL EPS filing projection differs from offline Arelle replay")
    return prepared
