# Implementation Roadmap

Planning entry: [planning registry](planning/README.md). This M roadmap describes
architecture/delivery goals; its milestone headings and historical next-step
notes are not a current completion or merge ledger. Investor usage stages U1–U5
are maintained in the [investor roadmap](planning/investor-analysis-roadmap.md).
Read the registry's separate proposal/approval/implementation/verification/local
acceptance/merge status and the linked execution contracts before starting work.

As recorded on 2026-09-09: U1/U2 are merged through PR #62 at
`7f8cc5232d0df3d4c184de55827111e599b94dbd`; U3 is locally accepted at
`3098be6db7622f2ec444a9979732b7dfaa685641` with closeout documentation at
`32212caba5daf8273663d70ba3075db5d1d56fc7`, and is **not in main**. U4
“계속 갱신” was subsequently locally accepted on 2026-09-10 at product SHA
`3236778e57872b8ea41e421534e4a9d9ea0d58ff`; see the
[U4 acceptance record](implementation/u4-completion-and-acceptance.md). It is
not in `main`. U5 “보관·공유” is locally accepted at product SHA
`8867229455f9441807117a4a4a3e1ebaa8ae7eee` and remains unmerged; see
[U5 completion and acceptance](implementation/u5-completion-and-acceptance.md).

## Historical M0 — Repository and accession discovery contracts
The original bootstrap work established repository contracts, CI skeleton, and
the accession adapter.  Its discovery boundary remains governed by
`ADR-003` and `accession-contract.md`; this roadmap does not rewrite its Git
history or claim that prior branches are newly compliant.

## M0 — Data-plane contract and release governance (current)
Deliverables:
- `ADR-004` and `m0-data-contract.md`
- `architecture/analytical-data-model.md`
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

The M7 code and contract exist, but durable Layer 2 materialization is the
next delivery sequence: [Layer 2 delivery plan](implementation/layer2-delivery-plan.md).
It covers period observations, governed company series and as-of selection,
capability discovery, and Derived Metrics **input** handoff.  It does not
claim that those durable outputs already exist or add a new architectural
Layer.

## M8 — Layer 3 cross-company semantics
Analytical taxonomy, mapping relations/confidence/versioning, peer-comparison panel.

## M9 — Consumer APIs and governed views
M9 migrates Excel/API/dashboard consumers to governed Analytical and Derived
Metrics outputs after the necessary Layer 1–3 and analytical-data QA is stable.

Consumer C0/C1 first establishes a common **Consumer Data Access Layer**: a
storage-agnostic library/adapter contract implemented today by the
publication-backed `AnalyticalRepository`. It is not an Excel-specific or HTTP
API requirement. Future DB/Parquet and optional transport adapters preserve
the contract; a governed Excel view is a later consumer migration.

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
