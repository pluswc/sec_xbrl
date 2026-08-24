"""Produce a conservative, provenance-cited P3 peer review from P2 dossiers.

P2 deliberately stops before Layer 2 company canonicalization.  This runner
therefore makes that absence visible: it does not manufacture canonical IDs or
feed unreviewed observations into the Layer 3 materializer.  A row's raw ID is
the immutable as-filed inline fact locator tuple, and ``UNMAPPED`` is an
explicit status rather than a placeholder for an inferred mapping.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sec_xbrl.pilots.amd_msft_meta_p1 import PilotFiling, load_pilot_manifest
from sec_xbrl.pilots.amd_msft_meta_p2 import CompanyDossier, DossierEvidence, PilotP2Runner

P3_MAPPING_VERSION = "p3-amd-msft-meta-v1"
UNMAPPED_COMPANY_CANONICAL_ID = "UNMAPPED: Layer 2 company canonicalization not materialized"


@dataclass(frozen=True, slots=True)
class PeerComparisonRow:
    """One user-visible, reported observation and its mapping decision."""

    ticker: str
    metric: str
    value: str
    period_class: str
    source_period: str
    source_raw_id: str
    company_canonical_id: str
    analytical_id: str | None
    mapping_relation: str
    mapping_confidence: float
    mapping_version: str
    mapping_evidence: str
    accession: str
    source_document: str | None
    source_locator: str | None
    qname: str | None
    unit: str | None
    dimensions: tuple[str, ...]
    scope_warning: str


@dataclass(frozen=True, slots=True)
class BacklogItem:
    """A decision-oriented gap; no backlog item silently changes a mapping."""

    priority: str
    item_id: str
    lane: str
    owner_lane: str
    evidence_gap: str
    impact: str
    decision_needed: str


@dataclass(frozen=True, slots=True)
class P3PeerReview:
    comparisons: tuple[PeerComparisonRow, ...]
    backlog: tuple[BacklogItem, ...]
    warnings: tuple[str, ...]


class PilotP3Runner:
    """Read the immutable P1 cache through P2 and make P3 limits reviewable."""

    def __init__(self, *, cache_root: Path, p2_runner: PilotP2Runner | None = None) -> None:
        self.p2_runner = p2_runner or PilotP2Runner(cache_root=cache_root)

    def run(self, filings: Iterable[PilotFiling]) -> P3PeerReview:
        dossiers = self.p2_runner.run(filings)
        return build_peer_review(dossiers)


def build_peer_review(dossiers: Iterable[CompanyDossier]) -> P3PeerReview:
    """Build a P3 decision record without asserting an unmaterialized mapping."""
    rows: list[PeerComparisonRow] = []
    for dossier in sorted(dossiers, key=lambda item: item.ticker):
        for evidence in _selected_total_revenue(dossier):
            rows.append(_row(dossier.ticker, "REPORTED_TOTAL_REVENUE", evidence, total=True))
        for evidence in _selected_breakdowns(dossier):
            rows.append(_row(dossier.ticker, _breakdown_metric(evidence), evidence, total=False))
    return P3PeerReview(
        comparisons=tuple(rows),
        backlog=_backlog(),
        warnings=(
            "Rows are reported as-filed facts, not rankings, forecasts, or derived metrics.",
            "P2 supplied no Layer 2 company canonical maps. UNMAPPED is therefore visible on every row; this P3 review does not bypass that contract.",
            "FY, QTD_3M, and YTD_9M remain separate. A value may be read beside another row only when its period class and scope are suitable for the user's question.",
            "AMD Data Center, MSFT Intelligent Cloud/Microsoft Cloud, and Meta Family of Apps/Reality Labs are not automatically peer-equivalent measures.",
        ),
    )


def _selected_total_revenue(dossier: CompanyDossier) -> tuple[DossierEvidence, ...]:
    """Keep the annual baseline and current update classes without comparatives."""
    annual = _latest_by_class(dossier.annual_revenue)
    current = _latest_by_class(dossier.update_revenue)
    return (*annual, *current)


def _selected_breakdowns(dossier: CompanyDossier) -> tuple[DossierEvidence, ...]:
    """Use only the P2-highlighted current-update segment/product disclosures."""
    latest: dict[str, DossierEvidence] = {}
    for evidence in dossier.update_breakdowns:
        metric = _breakdown_metric(evidence)
        if metric == "UNRESOLVED_DIMENSIONAL_REVENUE":
            continue
        prior = latest.get(metric)
        if prior is None or _period_end(evidence) > _period_end(prior):
            latest[metric] = evidence
    return tuple(latest[key] for key in sorted(latest))


def _latest_by_class(records: Iterable[DossierEvidence]) -> tuple[DossierEvidence, ...]:
    latest: dict[str, DossierEvidence] = {}
    for record in records:
        prior = latest.get(record.period_class)
        if prior is None or _period_end(record) > _period_end(prior):
            latest[record.period_class] = record
    return tuple(latest[key] for key in sorted(latest))


def _period_end(evidence: DossierEvidence) -> str:
    return evidence.period.rsplit(" to ", maxsplit=1)[-1]


def _row(ticker: str, metric: str, evidence: DossierEvidence, *, total: bool) -> PeerComparisonRow:
    raw_id = _raw_fact_id(evidence)
    if total:
        relation = "UNRESOLVED"
        confidence = 0.0
        analytical_id = None
        mapping_evidence = (
            "All selected facts use the same standard total-revenue QName and USD unit, "
            "but P2 did not materialize the required Layer 2 company canonical IDs."
        )
        warning = (
            "Company-wide reported revenue can be inspected side by side, but this is not yet a "
            "materialized EQUIVALENT cross-company mapping. Do not mix period classes."
        )
    else:
        relation = "NOT_COMPARABLE"
        confidence = 1.0
        analytical_id = None
        mapping_evidence = "P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers."
        warning = _breakdown_warning(metric)
    return PeerComparisonRow(
        ticker=ticker,
        metric=metric,
        value=evidence.value,
        period_class=evidence.period_class,
        source_period=evidence.period,
        source_raw_id=raw_id,
        company_canonical_id=UNMAPPED_COMPANY_CANONICAL_ID,
        analytical_id=analytical_id,
        mapping_relation=relation,
        mapping_confidence=confidence,
        mapping_version=P3_MAPPING_VERSION,
        mapping_evidence=mapping_evidence,
        accession=evidence.accession,
        source_document=evidence.document,
        source_locator=evidence.locator,
        qname=evidence.qname,
        unit=evidence.unit,
        dimensions=evidence.dimensions,
        scope_warning=warning,
    )


def _raw_fact_id(evidence: DossierEvidence) -> str:
    """Keep a stable source identity when P2 used its narrow inline-fact fallback."""
    return "as-filed-inline-fact:" + ":".join(
        (evidence.accession, evidence.document or "unknown-document", evidence.locator or "unknown-locator")
    )


def _breakdown_metric(evidence: DossierEvidence) -> str:
    dimensions = " ".join(evidence.dimensions)
    if "AdvertisingMember" in dimensions and "FamilyOfAppsMember" in dimensions:
        return "META_FAMILY_OF_APPS_ADVERTISING_REVENUE"
    # The P2 review highlights reportable-segment figures, except for the
    # separately called-out Meta advertising figure. Product/geography rows are
    # still preserved in P2 and deliberately remain out of this compact panel.
    if "srt:ProductOrServiceAxis=" in dimensions:
        return "UNRESOLVED_DIMENSIONAL_REVENUE"
    for marker, metric in (
        ("DatacenterMember", "AMD_DATA_CENTER_REVENUE"),
        ("DataCenterMember", "AMD_DATA_CENTER_REVENUE"),
        ("ClientAndGamingMember", "AMD_CLIENT_AND_GAMING_REVENUE"),
        ("EmbeddedMember", "AMD_EMBEDDED_REVENUE"),
        ("IntelligentCloudMember", "MSFT_INTELLIGENT_CLOUD_REVENUE"),
        ("MicrosoftCloudMember", "MSFT_MICROSOFT_CLOUD_REVENUE"),
        ("FamilyOfAppsMember", "META_FAMILY_OF_APPS_REVENUE"),
        ("RealityLabsMember", "META_REALITY_LABS_REVENUE"),
    ):
        if marker in dimensions:
            return metric
    return "UNRESOLVED_DIMENSIONAL_REVENUE"


def _breakdown_warning(metric: str) -> str:
    warnings = {
        "AMD_DATA_CENTER_REVENUE": "AMD's disclosed Data Center dimension is not automatically a cloud-services metric.",
        "AMD_CLIENT_AND_GAMING_REVENUE": "AMD's combined Client-and-Gaming dimension has no evidenced common peer scope here.",
        "AMD_EMBEDDED_REVENUE": "AMD's Embedded dimension has no evidenced common peer scope here.",
        "MSFT_INTELLIGENT_CLOUD_REVENUE": "Intelligent Cloud is a reportable segment broader than cloud services; it is not a standalone cloud-revenue metric.",
        "MSFT_MICROSOFT_CLOUD_REVENUE": "Microsoft Cloud is an as-filed product/service categorization, not evidenced as equivalent to another issuer's segment or product measure.",
        "META_FAMILY_OF_APPS_REVENUE": "Family of Apps is a Meta reportable segment, not an automatically comparable platform or cloud category.",
        "META_REALITY_LABS_REVENUE": "Reality Labs is a Meta reportable segment, not an automatically comparable hardware or technology category.",
        "META_FAMILY_OF_APPS_ADVERTISING_REVENUE": "Advertising within Family of Apps is both product and segment scoped; it is not comparable to the other issuer breakdowns.",
    }
    return warnings.get(metric, "The dimensional scope is unresolved and must not be used as a peer-equivalent metric.")


def _backlog() -> tuple[BacklogItem, ...]:
    return (
        BacklogItem(
            "P0 — correctness blocker", "P3-BLK-001", "Layer 2 mapping", "Longitudinal mapping review",
            "P2 has exact standard-QName revenue evidence but no materialized company canonical concept maps.",
            "Without canonical IDs, Layer 3 cannot produce a contract-valid EQUIVALENT total-revenue panel.",
            "Approve evidence-backed SAME mappings for each issuer's paired total-revenue concepts, or retain UNMAPPED.",
        ),
        BacklogItem(
            "P0 — correctness blocker", "P3-BLK-002", "Parser provenance", "Layer 1 / parser",
            "P2 uses a narrow inline fallback when Arelle omits visible total-revenue facts; fallback rows retain locators but not Layer 1 fact IDs.",
            "A materialized downstream panel needs a one-to-one raw fact ID bridge without broadening HTML scraping.",
            "Decide whether to fix the Arelle collection path or add a tested, provenance-preserving Layer 1 inline fact bridge.",
        ),
        BacklogItem(
            "P1 — decision coverage", "P3-COV-001", "Scope review", "Cross-company mapping review",
            "MSFT Intelligent Cloud and Microsoft Cloud have different disclosed scopes; AMD and Meta breakdowns use different segment/product axes.",
            "Prevents a misleading cloud, platform, or infrastructure peer chart.",
            "Approve only relation-specific mappings supported by disclosure scope, otherwise retain NOT_COMPARABLE.",
        ),
        BacklogItem(
            "P1 — decision coverage", "P3-COV-002", "History / recasts", "Filing selection and Layer 2",
            "One annual/current pair cannot establish mapping stability, renames, recasts, or continuity across reporting changes.",
            "Limits conclusions to the selected filings and may conceal later comparability breaks.",
            "Select additional annual filings and review documented segment recasts before longitudinal trend comparisons.",
        ),
        BacklogItem(
            "P2 — useful coverage", "P3-COV-003", "Disclosure coverage", "Disclosure taxonomy and mapping review",
            "P2 has selected revenue breakdowns but no reviewed common geography, customer-class, or product/service analytical taxonomy.",
            "Would broaden the panel only after correctness blockers are resolved.",
            "Choose a narrowly defined analytical category and its evidence standard, or explicitly leave the metric unavailable.",
        ),
    )


def render_peer_review(review: P3PeerReview) -> str:
    """Render a compact Markdown decision record with row-level provenance."""
    lines = [
        "# AMD · MSFT · META P3 — peer comparison and backlog",
        "",
        "This P3 review consumes only P2 evidence from the six validated P1 cached filings. It preserves reported values and makes missing Layer 2 mappings visible; it does not rank companies or infer cloud revenue.",
        "",
        "## What can be inspected together",
        "",
        "Company-wide reported revenue uses the same as-filed standard QName and USD unit, but the current P2 boundary has no materialized company canonical IDs. These rows are visible candidates, not an `EQUIVALENT` peer series. FY, QTD_3M, and YTD_9M remain separate.",
        "",
        "## Comparison rows",
        "",
    ]
    for row in review.comparisons:
        dimensions = "; ".join(row.dimensions) if row.dimensions else "none"
        lines += [
            f"### {row.ticker} — `{row.metric}`",
            "",
            f"- Reported value: `{row.value}` (`{row.period_class}`; {row.source_period}; dimensions: {dimensions}).",
            f"- Raw ID: `{row.source_raw_id}`.",
            f"- Company canonical ID: `{row.company_canonical_id}`.",
            f"- Analytical ID: `{row.analytical_id or 'none'}`; relation: `{row.mapping_relation}`; confidence: `{row.mapping_confidence:.2f}`; version: `{row.mapping_version}`.",
            f"- Mapping evidence: {row.mapping_evidence}",
            f"- Source: accession `{row.accession}`; document `{row.source_document}`; locator `{row.source_locator}`; QName `{row.qname}`; unit `{row.unit}`.",
            f"- Scope warning: {row.scope_warning}",
            "",
        ]
    lines += ["## Panel-wide scope warnings", ""] + [f"- {warning}" for warning in review.warnings]
    lines += ["", "## Prioritized backlog", ""]
    for item in review.backlog:
        lines += [
            f"### {item.priority} — `{item.item_id}`",
            "",
            f"- Owner lane: {item.owner_lane} ({item.lane}).",
            f"- Evidence gap: {item.evidence_gap}",
            f"- Impact: {item.impact}",
            f"- Decision needed: {item.decision_needed}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    review = PilotP3Runner(cache_root=args.cache_root).run(load_pilot_manifest(args.manifest))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_peer_review(review), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
