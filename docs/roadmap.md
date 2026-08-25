# Implementation Roadmap

## Historical M0 — Repository and accession discovery contracts
The original bootstrap work established repository contracts, CI skeleton, and
the accession adapter.  Its discovery boundary remains governed by
`ADR-003` and `accession-contract.md`; this roadmap does not rewrite its Git
history or claim that prior branches are newly compliant.

## M0 — Data-plane contract and release governance (current)
Deliverables:
- `ADR-004` and `m0-data-contract.md`
- explicit Raw / Analytical / Derived Metrics / Display ownership
- minimum grain, lineage, status, as-of, and basis-version contracts
- data-quality publication gates and milestone release/PR policy
- acceptance and migration policy for subsequent milestones

Exit: a PR can test whether a proposed Layer/analysis/display change satisfies
the agreed contract before it is merged to `main`.

## M1 — Filing package resolver
Input: `FilingRef`
Output: cached filing manifest/package ready for Arelle.

## M2 — Layer 1 core extraction
Concept, context, unit, fact, dimension extraction with QName/namespace provenance.

## M3 — Relationship extraction
Roles + PRE/CAL/DEF + targetRole.

## M4 — Anchor-driven traversal
Major statements -> Anchor -> direct dimensional facts -> DEF/CAL -> related roles.

## M5 — Disclosure Safety Net
Role inventory + P0/P1/P2 classification + deep scan path.

## M6 — 10-K baseline / 10-Q update
Period classification, comparative contexts, amendments, as-filed/latest-recast views, derived-quarter provenance.

## M7 — Layer 2 longitudinal mappings
Company canonical IDs, mapping evidence/versioning, Annual/Current Series.

## M8 — Layer 3 cross-company semantics
Analytical taxonomy, mapping relations/confidence/versioning, peer-comparison panel.

## M9 — Analytical API and future MCP
Only after Layer 1-3 QA stabilizes.

## GitHub workflow
Recommended milestone branches:
- `feature/m0-data-contract`
- `feature/m1-filing-package`
- `feature/m2-layer1-core`
- `feature/m3-relationships`
- `feature/m4-anchor-traversal`
- `feature/m5-disclosure-safety-net`
- `feature/m6-10q-periods`
- `feature/m7-longitudinal`
- `feature/m8-cross-company`

Each PR should include tests and any contract changes required by the
implementation.  It must originate from latest passing `main` and merge only
after its new acceptance checks, full regression, and artifact/impact comparison
pass; see `docs/implementation/m0-data-contract.md`.
