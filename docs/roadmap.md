# Implementation Roadmap

## M0 — Repository and contracts
Deliverables:
- AGENTS.md
- docs contracts
- private GitHub repository
- CI skeleton
- accession adapter stub + tests against existing collector sample output

Exit: Codex can read contracts; one accession record flows through adapter.

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
- `feature/m0-accession-adapter`
- `feature/m1-filing-package`
- `feature/m2-layer1-core`
- `feature/m3-relationships`
- `feature/m4-anchor-traversal`
- `feature/m5-disclosure-safety-net`
- `feature/m6-10q-periods`
- `feature/m7-longitudinal`
- `feature/m8-cross-company`

Each PR should include tests and any contract changes required by the implementation.
