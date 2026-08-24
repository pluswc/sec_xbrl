"""Produce compact, provenance-cited P2 company dossiers from cached P1 packages.

This is a read-only consumer of the immutable P1 cache.  It intentionally
creates no parquet snapshot and makes no Layer 2 mapping or derived-Q4 claim.
"""

from __future__ import annotations

import argparse
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sec_xbrl.disclosure.safety_net import DisclosureSafetyNet
from sec_xbrl.facts.layer1 import Layer1Extractor
from sec_xbrl.filing.filing_index import ArelleFilingLoader
from sec_xbrl.periods.logic import DisclosureStateTracker, PeriodClassifier
from sec_xbrl.pilots.amd_msft_meta_p1 import (
    PilotFiling,
    _with_primary_document,
    load_pilot_manifest,
)
from sec_xbrl.relationships.layer1 import RelationshipExtractor


class CachedOnlyFetcher:
    """Fail closed if a P2 run would require a download."""

    def fetch(self, url: str) -> bytes:
        raise RuntimeError(f"P2 requires an existing validated P1 cache; download refused: {url}")


@dataclass(frozen=True, slots=True)
class DossierEvidence:
    label: str
    value: str
    period_class: str
    period: str
    dimensions: tuple[str, ...]
    accession: str
    document: str | None
    locator: str | None
    qname: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class CompanyDossier:
    company: str
    ticker: str
    annual_accession: str
    update_accession: str
    annual_revenue: tuple[DossierEvidence, ...]
    update_revenue: tuple[DossierEvidence, ...]
    annual_breakdowns: tuple[DossierEvidence, ...]
    update_breakdowns: tuple[DossierEvidence, ...]
    disclosure_states: tuple[tuple[str, str], ...]
    statement_qa: tuple[str, ...]
    warnings: tuple[str, ...]


class PilotP2Runner:
    """Read cached packages and create evidence objects suitable for a dossier."""

    def __init__(self, *, cache_root: Path, model_loader: ArelleFilingLoader | None = None) -> None:
        self.cache_root = cache_root
        self.model_loader = model_loader or ArelleFilingLoader()

    def run(self, filings: Iterable[PilotFiling]) -> tuple[CompanyDossier, ...]:
        grouped: dict[str, list[PilotFiling]] = defaultdict(list)
        for filing in filings:
            grouped[filing.ticker].append(filing)
        return tuple(self._company(rows) for _, rows in sorted(grouped.items()))

    def _company(self, filings: list[PilotFiling]) -> CompanyDossier:
        by_role = {row.selection_role: row for row in filings}
        annual = self._extract(by_role["ANNUAL_BASELINE"])
        update = self._extract(by_role["CURRENT_UPDATE"])
        annual_revenue, annual_breakdowns = _revenue_evidence(**annual)
        update_revenue, update_breakdowns = _revenue_evidence(**update)
        annual_topics = _topics(annual["disclosures"].disclosure_index)
        update_topics = _topics(update["disclosures"].disclosure_index)
        tracker = DisclosureStateTracker()
        states = tuple(
            (topic, str(tracker.next_state("BASELINE", reported=topic in update_topics)))
            for topic in sorted(annual_topics | update_topics)
        )
        p = by_role["ANNUAL_BASELINE"]
        return CompanyDossier(
            company=p.company,
            ticker=p.ticker,
            annual_accession=p.filing.accession,
            update_accession=by_role["CURRENT_UPDATE"].filing.accession,
            annual_revenue=annual_revenue,
            update_revenue=update_revenue,
            annual_breakdowns=annual_breakdowns,
            update_breakdowns=update_breakdowns,
            disclosure_states=states,
            statement_qa=_statement_qa(annual["relationships"].roles, update["relationships"].roles),
            warnings=(
                "All values are reported facts; this runner creates no derived Q4 or inferred metric.",
                "A topic absent from the 10-Q is NOT_REPORTED_THIS_QUARTER, not resolved.",
                "Breakdowns are as-filed dimensional observations; they are not cross-company mappings.",
            ),
        )

    def _extract(self, pilot: PilotFiling) -> dict[str, Any]:
        from sec_xbrl.filing.filing_index import FilingIndexCache, FilingPackageResolver
        from sec_xbrl.filing.package_cache import AccessionPackageCache

        resolver = FilingPackageResolver(
            AccessionPackageCache(self.cache_root / "packages"),
            FilingIndexCache(self.cache_root / "filing-indexes"),
        )
        filing = _with_primary_document(pilot.filing, resolver.package_cache.package_dir(pilot.filing))
        resolved = resolver.resolve(filing, CachedOnlyFetcher())
        inline_facts = _inline_revenue_facts(resolved.zip_path, resolved.entrypoint_name, filing.accession)
        with TemporaryDirectory(prefix="p2-arelle-") as temp:
            model = self.model_loader.load(resolved, Path(temp))
            raw = Layer1Extractor().extract(model, filing, source_url=resolved.index.source_url)
            relationships = RelationshipExtractor().extract(model, filing)
        facts = PeriodClassifier().classify(
            filing=raw.filing[0], concepts=raw.concepts, contexts=raw.contexts, facts=raw.facts
        )
        disclosures = DisclosureSafetyNet().build(
            roles=relationships.roles, relationships=relationships.relationships,
            concepts=raw.concepts, facts=facts,
        )
        return {"raw": raw, "facts": facts, "relationships": relationships, "disclosures": disclosures,
                "accession": filing.accession, "inline_facts": inline_facts}


def _revenue_evidence(*, raw: Any, facts: Iterable[Mapping[str, Any]], accession: str, inline_facts: tuple[DossierEvidence, ...] = (), **_: Any) -> tuple[tuple[DossierEvidence, ...], tuple[DossierEvidence, ...]]:
    concepts = {str(row["raw_concept_id"]): row for row in raw.concepts}
    contexts = {str(row["context_id"]): row for row in raw.contexts}
    units = {str(row["unit_id"]): row for row in raw.units}
    dims: dict[str, list[str]] = defaultdict(list)
    for row in raw.dimension_facts:
        axis = concepts.get(str(row["axis_raw_concept_id"]), {}).get("qname", "unknown-axis")
        member = concepts.get(str(row.get("member_raw_concept_id")), {}).get("qname", row.get("typed_member") or "typed")
        dims[str(row["fact_id"])].append(f"{axis}={member}")
    candidates = [row for row in facts if _is_revenue(concepts.get(str(row["raw_concept_id"]), {})) and row.get("value_numeric") is not None]
    evidence = tuple(sorted((_evidence(row, concepts, contexts, units, dims, accession) for row in candidates), key=lambda x: (x.period, x.label, x.dimensions)))
    # The P1 QA uses Arelle's instance fact collection.  A filing can contain
    # an inline fact that is visible in the as-filed document but omitted from
    # that collection due to a loader limitation.  Preserve that limitation
    # openly and use a narrow, direct inline scan only for exact revenue facts.
    evidence = tuple(row for row in evidence if _is_total_revenue_qname(row.qname)) + inline_facts
    totals = tuple(row for row in evidence if not row.dimensions)
    breakdowns = tuple(row for row in evidence if row.dimensions)
    return totals, breakdowns


def _is_revenue(concept: Mapping[str, Any]) -> bool:
    name = " ".join(str(concept.get(key) or "") for key in ("local_name", "label")).lower()
    return "revenue" in name and "cost" not in name and "deferred" not in name and "remaining" not in name and "percentage" not in name


def _is_total_revenue_qname(qname: str | None) -> bool:
    return bool(qname and qname.split(":")[-1] in {"RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"})


def _inline_revenue_facts(zip_path: Path, entrypoint: str, accession: str) -> tuple[DossierEvidence, ...]:
    """Read exact revenue facts from the selected as-filed inline document.

    This deliberately has no generic HTML scraping behavior: it accepts only
    three standard revenue QNames and retains the inline fact id as locator.
    """
    from lxml import etree

    with zipfile.ZipFile(zip_path) as archive:
        content = archive.read(entrypoint)
    root = etree.fromstring(content, etree.HTMLParser())
    contexts: dict[str, tuple[str, tuple[str, ...]]] = {}
    for node in (item for item in root.iter() if str(item.tag).split(":")[-1].lower() == "context"):
        identifier = node.get("id")
        if not identifier:
            continue
        children = {str(item.tag).split(":")[-1].lower(): "".join(item.itertext()).strip() for item in node.iter()}
        start = children.get("startdate") or None
        end = children.get("enddate") or None
        instant = children.get("instant") or None
        members = tuple(sorted(
            f"{member.get('dimension')}={''.join(member.itertext()).strip()}"
            for member in node.iter() if str(member.tag).split(":")[-1].lower() == "explicitmember"
        ))
        period = instant or f"{start} to {end}"
        contexts[identifier] = (period, members)
    units = {
        node.get("id"): " * ".join("".join(item.itertext()).strip() for item in node.iter() if str(item.tag).split(":")[-1].lower() == "measure")
        for node in root.iter() if str(node.tag).split(":")[-1].lower() == "unit" and node.get("id")
    }
    result: list[DossierEvidence] = []
    for node in (item for item in root.iter() if str(item.tag).split(":")[-1].lower() == "nonfraction"):
        qname = node.get("name")
        if not _is_total_revenue_qname(qname):
            continue
        context_ref = node.get("contextRef") or node.get("contextref")
        if context_ref not in contexts:
            continue
        raw = "".join(node.itertext()).strip().replace(",", "")
        if not raw:
            continue
        period, dimensions = contexts[context_ref]
        period_class = "INSTANT" if " to " not in period else _inline_period_class(period)
        result.append(DossierEvidence(
            label="Revenue from contracts with customers" if qname and qname.endswith("RevenueFromContractWithCustomerExcludingAssessedTax") else str(qname),
            value=_scaled_value(raw, node.get("scale")), period_class=period_class, period=period, dimensions=dimensions, accession=accession,
            document=entrypoint, locator=f"inline-id:{node.get('id')}", qname=qname,
            unit=units.get(node.get("unitRef") or node.get("unitref")),
        ))
    unique = {(row.qname, row.period, row.dimensions, row.value): row for row in result}
    return tuple(sorted(unique.values(), key=lambda row: (row.period, row.dimensions, row.value)))


def _inline_period_class(period: str) -> str:
    from datetime import date

    start, end = (date.fromisoformat(item) for item in period.split(" to "))
    days = (end - start).days
    if 75 <= days <= 105:
        return "QTD_3M"
    if 160 <= days <= 205:
        return "YTD_6M"
    if 250 <= days <= 300:
        return "YTD_9M"
    if 350 <= days <= 378:
        return "FY"
    return "OTHER_DURATION"


def _scaled_value(raw: str, scale: str | None) -> str:
    """Keep the inline lexical number and its declared XBRL scale together."""
    return raw if not scale or scale == "0" else f"{raw} × 10^{scale}"


def _evidence(row: Mapping[str, Any], concepts: Mapping[str, Mapping[str, Any]], contexts: Mapping[str, Mapping[str, Any]], units: Mapping[str, Mapping[str, Any]], dims: Mapping[str, list[str]], accession: str) -> DossierEvidence:
    concept = concepts[str(row["raw_concept_id"])]
    context = contexts.get(str(row.get("context_id")), {})
    unit = units.get(str(row.get("unit_id")), {})
    period = context.get("instant_date") or f"{context.get('start_date')} to {context.get('end_date')}"
    return DossierEvidence(
        label=str(concept.get("label") or concept.get("local_name")), value=str(row["value_numeric"]),
        period_class=str(row.get("period_class")), period=str(period),
        dimensions=tuple(sorted(dims.get(str(row["fact_id"]), []))), accession=accession,
        document=row.get("source_document"), locator=row.get("source_locator"), qname=concept.get("qname"),
        unit=unit.get("raw_representation"),
    )


def _topics(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {str(row["critical_topic"]) for row in rows if row.get("critical_topic") and row.get("priority") in {"P0", "P1"}}


def _statement_qa(*role_sets: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        f"{role.get('role_definition') or role.get('role_uri')} ({role.get('role_category')})"
        for roles in role_sets for role in roles if role.get("role_category") == "STATEMENT"
    )


def render_dossiers(dossiers: Iterable[CompanyDossier]) -> str:
    """Render a small, reviewable Markdown report with fact-level citations."""
    lines = ["# AMD · MSFT · META P2 company dossiers", "", "This report is generated from the six validated P1 cached packages. Values are as filed and provenance-cited; no derived Q4, forecast, or peer-equivalence claim is made.", ""]
    for dossier in dossiers:
        lines += [f"## {dossier.ticker} — {dossier.company}", "", f"Annual baseline: `{dossier.annual_accession}`. Current update: `{dossier.update_accession}`.", "", "### Reported revenue", ""]
        for heading, records in (("Annual baseline", dossier.annual_revenue), ("Current update", dossier.update_revenue)):
            lines += [f"#### {heading}", ""]
            lines += _render_records(records) or ["No un-dimensioned revenue fact was selected; see scope warning.", ""]
        lines += ["### Reported revenue breakdowns", ""]
        lines += _render_records(dossier.annual_breakdowns + dossier.update_breakdowns) or ["No revenue fact with explicit dimensions was selected.", ""]
        lines += ["### P0/P1 disclosure inventory state", ""]
        lines += [f"- `{topic}`: `{state}`" for topic, state in dossier.disclosure_states]
        lines += ["", "### Statement QA", ""] + [f"- {item}" for item in dossier.statement_qa]
        lines += ["", "### Scope warnings", ""] + [f"- {item}" for item in dossier.warnings] + [""]
    return "\n".join(lines) + "\n"


def _render_records(records: Iterable[DossierEvidence]) -> list[str]:
    result: list[str] = []
    for row in records:
        dimensions = "; ".join(row.dimensions) if row.dimensions else "none"
        result += [f"- {row.label}: `{row.value}` ({row.period_class}, {row.period}; dimensions: {dimensions}).", f"  Evidence: accession `{row.accession}`; `{row.document}` {row.locator}; QName `{row.qname}`; unit `{row.unit}`.", ""]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = render_dossiers(PilotP2Runner(cache_root=args.cache_root).run(load_pilot_manifest(args.manifest)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
