# Company-universe delivery completion record

## Status

This record covers the approved 2026-10-08 A/B/C delivery.  It records the
feature-branch implementation and the checks still required before local
acceptance or merge.  It does not mark the delivery locally accepted, merged,
or deployed.

The independently verified component candidates are:

- A collection operations: `24df8030d6a0c7771f9f7a1d3f8eb73ee9d3f03b`;
- B company master and SEC SIC publication: source candidate
  `1e5a398712d8423f1f6a45d08e233d52854021b6`; and
- SEC `durweek` parser compatibility: source candidate
  `192ee4243e469ff120f33debae7e965d0dd1ce9f`;
- C reviewed Q4: source candidate
  `964677136ef15c0bea833b2cfb3cd89dcd749380`; and
- SEC numeric-duration conformance and fail-closed ingestion: source candidate
  `9b2c4022c64dee2327da082a38777684c96271be`; and
- exact SEC supported-lexical and word-duration grammar: final source
  candidate `c1fdc21a267545c3c67ad4bdce8c74137ee340e1`.

The subsequent complete old-sentinel audit found 104 valid SEC supported
lexicals across four bounded transform families.  Their `m2-layer1-v5` source
candidate passed independent verification.  This replacement integration,
fresh runtime, and final joined publication still require separate verification;
the prior v4 candidate remains evidence rather than final acceptance.

Combined candidate `f897045f122463a3754cc5d3e765ceee77d956d7` remains
historical implementation evidence.  A subsequent raw audit found the
numeric-duration accuracy blocker, so it is not a final accepted source or
runtime publication.  The user authorized the standards correction and fresh
v5 data generation.  The duration arithmetic, fail-closed gate, four-family
supported-lexical repair, and exact word-duration grammar passed independent
verification; the 381-filing v5 migration, updated combined integration, and
final runtime publication remain pending.
Combined candidate `7c7122a62ba33a933b8a3d7ff56b526fd00e509d` is also
historical evidence.  Its independent review found that the source index and
fact evidence could be changed together and re-hashed while retaining a real
v5 Fact row.  The replacement adds a governed Raw/Quality source-binding
producer and reader; its frozen source, independent verification, runtime
publication, and joined acceptance remain pending.
Runtime completion counts and the final report identity remain **PENDING**
until the fresh operations, duration-conformance assessment, metadata,
reviewed-Q4, quarterly, and annual publications have all been verified
together.

## Completion publication

`sec_xbrl.universe_delivery.publish_universe_delivery` reads prepared outputs
only and publishes a new immutable completion directory containing:

- `company_readiness.json`, the governed joined data model;
- `company_readiness.csv`, one row per configured CIK;
- `index.html`, the Korean human-readable view titled
  **기업·산업·원자료·분석준비·Q4범위**;
- `README.md`, the offline input/output and provenance guide; and
- `universe_delivery_manifest.json`, which binds those files to their source
  paths, publication IDs, and SHA-256 digests.

`UniverseDeliveryReader` verifies the exact five-file set, every output digest
and size, the publication identity, the readiness scope, and unique company
CIK grain before the directory is exposed as a completion publication.

The renderer calls the existing A status reader, B metadata reader, reviewed-Q4
reader, and prepared analysis client.  It does not call SEC, Arelle, filing
selection, the history builder, or a financial calculation producer.  Q4 rows
come from the immutable reviewed-Q4 publication; the HTML renderer never
subtracts FY and YTD values.

The separate `sec_xbrl.source_bindings` producer is the only new step that
opens cached primary XHTML.  It publishes `source_documents.json`,
`source_bindings.json`, and `source_binding_manifest.json` atomically after
binding exact source fields to v5 Raw identities.  The completion process uses
`SourceBindingsReader`, which verifies prepared digests, cached bytes, and Raw
table identities without parsing XHTML, invoking Arelle, contacting SEC, or
recomputing a transform.  A `PASS` assessment names the exact source-binding
publication ID and manifest digest and includes independent-verification
evidence for its frozen producer revision.

Before writing, the publisher verifies:

1. the external configuration has explicit, unique CIKs and matches the exact
   A universe, ticker order, CIKs, financial as-of date, and observation time;
2. every configured CIK exists once in B and its configured ticker is one of
   that CIK's identifiers, while additional ticker aliases remain on the same
   company row;
3. every B Parquet file, identity, row grain, candidate-only issuer, and
   classified or unclassified state passes `CompanyMetadataReader` checks;
4. any supplied C companion passes its parent-history, evidence-ledger,
   snapshot, file, row-count, review-cutoff, selection-view, ticker, and CIK
   checks;
5. quarterly and annual bundles have the required separate period modes, all
   declared Parquet hashes and row counts, the same historical analytical
   selection scope, and the exact C parent publication identity; and
6. when supplied, the duration-conformance assessment matches the exact A
   scope, governed-history manifests, and evidence hashes; `PASS` additionally
   proves fail-closed ingestion gates, normalized values, the known AMD
   regression, all source-bound supported-lexical corrections, zero unapproved
   foreign changes, a separately prepared and independently verified governed
   source-binding publication, and independent verification;
   and
7. no output company row is duplicated by a ticker alias.

Unknown SIC candidates remain in the B master and count as unclassified.  The
completion report states candidate, classified, unclassified, and pilot
classified counts separately; it does not describe pilot SIC coverage as
global SEC coverage or accounting equivalence.

## Date and scope labels

The report persists and displays these independently:

- A financial collection as-of date;
- A collection source observation time;
- B metadata observation times and optional cutoff;
- C historical analytical selection as-of date; and
- C review cutoff.

The report explicitly prohibits reading different dates as one same-date
cross-company panel.  The initial reviewed Q4 threshold is 16 economic values
and 32 view-specific records.  Structured exclusions, including FY2025 mapping
epoch cases, and unreviewed segment/geography scopes remain visible exclusions;
they are not converted to zero or treated as a failed raw filing.

The report also labels whether the reviewed-Q4 parent is a current A governed
history or a separate approved historical reference.  A separate reference is
never presented as fresh v5 lineage.  Final C must use a fresh v5 NVDA
historical reference as of 2026-09-06 and separately preserve the 2026-10-08
Q4 review cutoff.  Its monetary source facts must match that reference; the
assessment separately discloses the 22 approved `numwordsen` monetary zeros and
requires zero unapproved monetary differences.

The final-run A `REUSED` count means the new run verified and adopted existing
raw snapshots.  It does not restate how many filings originally came from an
external baseline versus a new acquisition.  That acquisition history belongs
in the final runtime README and source attempt records and must remain separate
from replay/adoption status.

## Runtime completion gate

The intended runtime roots are caller inputs, not constants in the renderer.
For the current run they are expected under
`data/processed/universe_runs/20261008_sec_transform_v5/`, including fresh
`ops_v5`, `source_bindings_v1`, `analysis_history_v5`, `q4_delivery_v5`, and
`completion_v5` roots
declared by the runtime manifests.  Cached source packages remain read-only under the separate ignored
`data/raw/universe_runs/20261008_duration_v4/` boundary.  The unaffected B
`company_metadata_v2` publication is reused read-only from the initial run.
Earlier `operations_final`, raw, analysis, Q4, and report artifacts remain
preserved.  Their existence here is not asserted by this tracked document.

Local completion requires a newly generated completion publication whose
manifest and readiness data prove:

- exact configured company/CIK membership without duplicate rows;
- complete A raw intake plus a verified governed-history `READY` publication
  for every configured company (raw completion alone remains a green
  foundation with overall `PARTIAL` status);
- a scope-bound `PASS` duration-conformance assessment that validates actual
  normalized values across the fresh 381-filing v5 cohort, preserves source
  lexicals, binds all v5 snapshot manifests plus the 3,842-Fact external
  duration evidence, verifies the 104 supported-lexical repairs against the
  source index and actual Fact/Concept tables, discloses 22 monetary and 10
  share zeros, and reports zero unapproved foreign changes;
- a `sec-source-bindings-v1` Raw/Quality publication that scans the exact 381
  cached primary documents outside the renderer, binds all 3,842 duration
  sources and 104 approved correction sources to v5 Raw identities, records
  the package, primary-member, snapshot-manifest, Fact, Concept, and Context
  table digests, and passes independent verification at its frozen producer
  revision;
- B identity and SEC SIC present for every pilot company, with an explicit
  status for all broader candidate issuers;
- the approved reviewed-Q4 economic/view thresholds plus explicit exclusions;
- separate verified quarterly and annual prepared bundles; and
- focused tests, the full network-free regression suite, Ruff, and an
  independent read-only verification at the frozen integration SHA.

The final runtime counts, publication ID, frozen integration SHA, independent
verification result, local acceptance, PR, CI, and merge fields will be added
only after those events occur.
