# Company-universe delivery completion record

## Status

This record covers the approved 2026-10-08 A/B/C delivery.  The lead marked
the final local product **LOCALLY_ACCEPTED** on 2026-10-08 at frozen source
`8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`.  The accepted completion
publication is `universe-delivery-1c4337ffe69e81ae8b4ecc61`; its
`universe_delivery_manifest.json` SHA-256 is
`d20188610b699b960fcac4b34fc1c08d0073b6d346bc7d2026df3966fc6ccb29`.
The publication reports `READY`.

This is a local acceptance state.  Push, PR, remote CI, merge, and deployment
were not authorized in this delivery and remain pending.  `main` remains at
the implementation baseline
`201acf9aec2f8183acb7dd843579938db14236cd`; runtime data remains ignored and
was not added to Git.

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
candidate passed independent verification.  The governed source-binding
producer replacement at `eff3bff3e61f46ed040e12a102ebeed994bad7cc` and the
final consumer correction at `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`
also passed separate independent verification.

Combined candidate `f897045f122463a3754cc5d3e765ceee77d956d7` remains
historical implementation evidence.  A subsequent raw audit found the
numeric-duration accuracy blocker, so it is not a final accepted source or
runtime publication.  The user authorized the standards correction and fresh
v5 data generation.  The duration arithmetic, fail-closed gate, four-family
supported-lexical repair, exact word-duration grammar, 381-filing migration,
and final publication were subsequently verified and accepted.
Combined candidate `7c7122a62ba33a933b8a3d7ff56b526fd00e509d` is also
historical evidence.  Its independent review found that the source index and
fact evidence could be changed together and re-hashed while retaining a real
v5 Fact row.  The replacement adds a governed Raw/Quality source-binding
producer and reader.  Independent verification reproduced the producer files,
rejected the prior self-rehash attack, and bound the final assessment to the
accepted publication before local acceptance.

## Accepted runtime evidence

The immutable runtime root is
`data/processed/universe_runs/20261008_sec_transform_v5/`.  The accepted
completion manifest binds the following results:

- A has 21/21 `RAW_COMPLETE` and 21/21 governed histories `READY`, covering
  381 selected and held filings with zero failed or pending filings.  The
  verifier checked 741 declared history Parquet files and their row counts.
- The first intake history comprised 128 already available source snapshots
  and 253 new acquisitions.  The fresh v5 replay parsed all 381 cached source
  packages offline.  Its completion `reused_filings: 0` describes this final
  run and does not replace that acquisition history.
- Raw accuracy is `PASS` for 3,842 duration facts: 2,902 `duryear`, 391
  `durmonth`, 481 `durday`, and 68 `durweek`.  The separately governed source
  binding is `source-bindings-b08f848a24c831a5812f9e7a`, manifest SHA-256
  `87873702ddf8b307bda08430e083acb33da36024d9ddaa669f35016d9377d1b4`.
- The 104 approved supported-lexical repairs comprise 48 Nasdaq exchange
  values, 19 Idaho state values, five Unicode-hyphen duration words, and 32
  reported numeric zeros.  The zeros comprise 22 monetary and 10 share facts,
  including three source-signed `-0` values.  Unapproved foreign changes are
  zero.
- B preserves all 8,016 candidate issuers: 21 pilot issuers have SEC SIC
  classifications and 7,995 candidates remain explicitly unclassified.  This
  is candidate coverage, not global SIC coverage or accounting equivalence.
- C uses a fresh v5 NVDA 14-filing historical reference selected as of
  2026-09-06.  Its review cutoff is
  `2026-10-08T07:28:02.487928+00:00` (16:28:02 KST).  The accepted source pair
  evidence exactly matches 32 prior monetary Facts and six revenue text
  blocks, including Context, Unit, full dimensions, period, and basis.
- C publishes 32 view records representing 16 distinct approved economic Q4
  values.  Ten exclusions remain visible: six exact FY2025 mapping scopes and
  four policy notes.  Unreviewed geography, segment, and operating-income
  scopes remain outside the approved accounting scope.
- Quarterly and annual outputs remain separate.  The verifier checked 16
  exports: JSON, CSV, XLSX, and HTML for both `AS_FILED` and
  `LATEST_REPORTED`, in quarterly and annual modes.

The collection financial as-of date is 2026-10-08.  The C analytical reference
date is 2026-09-06, and the Q4 review cutoff is the timestamp above.  The
accepted report keeps these dates separate and does not present them as a
same-date cross-company panel.  The collection source observation time is
`2026-10-08T01:15:07.740987+00:00`; the B candidate inventory observation time
is `2026-10-08T01:32:29.603469Z`, and B retains its individual submissions
snapshot observation times rather than replacing them with the financial
as-of date.

The final Chromium audit passed DOM, selector, trace-dialog, context, API, and
export equality checks with no page errors or external requests.  The accepted
browser paths are `q4_delivery_v5/quarterly_report.html` and
`q4_delivery_v5/annual_report.html`.  The original extensionless files had
been served as `text/plain`; that browser failure is retained as evidence, and
byte-identical `.html` copies passed as `text/html`.  Screenshot capture timed
out, so no screenshot acceptance is claimed.

The accepted `completion/index.html` SHA-256 is
`87fd2d4d43c6ea4e0be4b8a67a69e0beac5369b5b80b5a5492a36fa0a6adf858`.
The quarterly and annual browser report SHA-256 values are respectively
`12484e92c4d5176159e5c90788a09080f8474ef7bc89a3da48b231fbe57f725b`
and `455397b57048a20c3f8433a0086197deb193f21eca4805d76d4b069087cf955c`.
The reviewed-Q4, quarterly-analysis, and annual-analysis manifest SHA-256
values are respectively
`fa42e268238d0d1ed5011c4b977f3ff1b40cae134a98eafc52314c78afba105c`,
`7249e5dac2f4cc73a3b6e68301d94e624e163bd3f178d07f7fefdf790762d4ff`,
and `e52bc361de0b8d06c3c3b499a8fe897ae2aa4559a909b2e20e05409ad9c25c73`.

Independent evidence is preserved under the runtime root:

- `verification/parser/verification-report.json` — parser source candidate
  `c1fdc21a267545c3c67ad4bdce8c74137ee340e1`, PASS with 1,160 passed,
  30 skipped, 482 focused tests, seven real replays, and Ruff PASS;
- `verification/integration/verification-report.json` — source-binding
  producer `eff3bff3e61f46ed040e12a102ebeed994bad7cc`, PASS with 1,276 passed,
  31 skipped, 29 focused tests, and Ruff PASS;
- `verification/final_consumer/verification-report.json` — final source
  `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`, PASS with 1,288 passed,
  31 skipped, 41 focused tests, and Ruff PASS; and
- `verification/final_runtime/verification-report.json` — actual joined
  runtime and browser PASS, SHA-256
  `fe82f679bbea6c764a074802fa1c13e8e867d936722accb39ac1d70cdb488150`.

The migration preservation audit found zero changes across 4,142 protected
old/v4 snapshot and evidence files.  A/history source remained unchanged from
its independently verified component.  During the serial company builds, the
combined CAT process reached about 26 GB RSS after completing its publication;
it was interrupted cleanly, then a new one-company process verified and
adopted the already built artifact.  The cohort progressed from 17 to 21
`READY` companies without changing that output.  This is the operational use
case for the validated `--ticker` subset and process-level memory release.

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

The runtime roots are caller inputs, not constants in the renderer.  The
accepted run is under
`data/processed/universe_runs/20261008_sec_transform_v5/`, including fresh
`operations_v5`, `source_bindings_v1`, `analysis_history_v5`, `q4_delivery_v5`, and
`completion` roots
declared by the runtime manifests.  Cached source packages remain read-only under the separate ignored
`data/raw/universe_runs/20261008_duration_v4/` boundary.  The unaffected B
`company_metadata_v2` publication is preserved under the accepted v5 runtime
root and consumed read-only by the completion publisher.
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

All local completion gates above passed at the frozen source and publication
identities in this record.  PR, remote CI, merge, and deployment remain
unperformed workflow states; this acceptance does not change them.
