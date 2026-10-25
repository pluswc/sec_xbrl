# Company-universe data delivery contract

## 1. Authority, status, and baseline

On 2026-10-08 the user authorized implementation of the A/B/C company-universe
delivery described here, including a real initial cohort and tangible local
runtime artifacts.  The implementation baseline is
`201acf9aec2f8183acb7dd843579938db14236cd` on
`codex/company-universe-delivery`.

The current delivery state is **LOCALLY_ACCEPTED** as of 2026-10-08.  A
candidate `24df803`, B candidate `1e5a398`, parser compatibility candidate
`192ee424`, C repair candidate `9646771`, numeric-duration conformance and
fail-closed candidate `9b2c402`, and the broader SEC supported-lexical and
exact word-duration grammar repair `c1fdc21` passed their separate independent
verification.  The governed source-binding producer at `eff3bff3` and final
consumer at `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7` also passed independent
verification.  The accepted local publication is
`universe-delivery-1c4337ffe69e81ae8b4ecc61`, bound by manifest SHA-256
`d20188610b699b960fcac4b34fc1c08d0073b6d346bc7d2026df3966fc6ccb29`.
The first combined candidate `f897045` remains
historical evidence and is not accepted because the subsequent raw-accuracy
audit found nonconforming numeric-duration values.  It was superseded and is
not the accepted source or runtime.  Current evidence and remaining remote
workflow states are in
[`universe-data-delivery-completion.md`](universe-data-delivery-completion.md)
under the state rules of [`delivery-workflow.md`](delivery-workflow.md).  This
contract does not create a new architectural Layer and does not replace the M
architecture roadmap or U investor roadmap.

On 2026-10-08 the user then authorized the SEC numeric-duration standards
correction and fresh data generation.  The old v2/v3 raw snapshots, histories,
and combined artifacts remain immutable.  This delivery now also requires a
fresh `m2-layer1-v5` replay of all 381 selected source packages, fresh governed
histories, and an assessment that verifies normalized duration values against
the approved duration rule plus the bounded supported-lexical repairs.  Matching
filing counts alone cannot clear this gate.
The parser and fail-closed ingestion contract is
[`sec-duration-conformance-delivery.md`](sec-duration-conformance-delivery.md).

Combined integration candidate `7c7122a` is also historical evidence rather
than an accepted candidate.  Independent verification proved that its two
assessment JSON inputs could be changed together and re-hashed without an
independent binding to the cached primary-document fields.  The authorized
repair adds a separate governed Raw/Quality source-binding publication before
the completion consumer.  The replacement producer and reader passed
independent verification, the actual v5 runtime and browser delivery passed,
and the lead locally accepted the joined publication.  Push, PR, remote CI,
merge, and deployment remain pending and were not authorized by this local
delivery.

## 2. Authorized A/B/C delivery

### A — Collection operations and the common delivery contract

A adds a reusable company-level operations wrapper around the existing
`sec_xbrl.history` discovery, intake, and publication functions.  The wrapper
coordinates companies independently, defaults network work to serial
execution, records immutable plans and append-only attempts, and exposes an
offline status read.  It must preserve the existing Filing Discovery,
package/cache, Arelle, Layer 1, period-selection, recast, and accounting
semantics.

Tracked artifacts are:

- `src/sec_xbrl/collection_operations.py` with public prepare, collect, build,
  and status operations plus `python -m sec_xbrl.collection_operations`;
- network-free unit coverage in `tests/unit/test_collection_operations.py`;
- `examples/universe/pilot_companies.json`, which keeps the company list out of
  engine code; and
- `docs/usage/company-universe-operations.md`.

Runtime artifacts include one immutable plan and intake history per company,
an aggregate deterministic status manifest, machine-readable JSON and CSV,
and a human-readable HTML summary.  A later integration step may link those
artifacts with B and C in one local completion view without changing their
source contracts.  That prepared-output integration is implemented by
`src/sec_xbrl/universe_delivery.py`; its acceptance remains separate from A's
already verified component candidate.

### B — Company master and SIC classification publication

B publishes company identity and industry evidence from immutable SEC
submissions snapshots.  Its agreed public boundary is:

```python
SnapshotInput(path, observed_at, source="sec_submissions", source_url=None)
build_company_metadata(
    snapshot_paths,
    *,
    observed_at,
    cutoff,
    candidate_inventory=None,
    sic_reference_path=None,
)
publish_company_metadata(build, destination)
CompanyMetadataReader(root).list_companies(UniverseFilter(...))
CompanyMetadataReader(root).peer_candidates(cik)
```

The publication contains `companies.parquet`, `company_identifiers.parquet`,
`industry_classifications.parquet`, and `company_metadata_manifest.json`.
Observed-at source time remains distinct from the analytical as-of date.  An
industry label or peer candidate is classification evidence; it does not make
two accounting concepts equivalent.

### C — Reviewed dimensional Q4 companion and period consumer connection

C produces an immutable `reviewed_q4_manifest.json` with candidate, exclusion,
review, and derived records backed by an exact-source approval ledger.  It
connects approved quarterly values to the quarterly consumer publication and
publishes FY consumer output under a separate label.  The initial evidence
target is 16 exact approved NVDA product-revenue Q4 cells across FY2024–FY2026;
unresolved scopes remain explicit and unavailable.

The user authorized this delivery objective.  Each accounting scope still
requires the lead's source-evidence approval before it may enter the approval
ledger or produce a governed value.  C may not remove the existing
undimensioned core guard or promote mechanical candidates automatically.

## 3. Initial input scope

The tracked pilot configuration contains these 21 requested tickers:
AMD, AAPL, MSFT, AMZN, NVDA, NFLX, TSLA, META, GOOGL, AVGO, INTC, MU, QCOM,
WMT, COST, TGT, CAT, DE, PCAR, PG, and KO.  Tickers and optional resolved CIKs
belong in external configuration or a company-master publication, never in the
collection or analysis engines.

The run uses these explicit boundaries:

- analytical as-of date: `2026-10-08`;
- collection coverage: the most recent four completed fiscal years plus
  subsequently filed quarters available by the as-of date;
- default analytical comparison window: the most recent three completed
  fiscal years, with the current incomplete fiscal year shown only through its
  collected filing focus; and
- source observation timestamp: recorded independently for every submissions
  snapshot or metadata input.

Actual SEC `report_date` and filing metadata determine coverage.  Calendar-year
substitution is prohibited.  A new IPO or other short-history filer is retained
with the periods actually available and an `AVAILABLE_PERIODS_ONLY` capability
status.  It is not dropped because four annual baselines do not exist.  This
requires an explicit supported report-date window selected from actual filing
inventory.  If an analysis needs a predecessor annual baseline, that filing is
a supplemental, explicit plan input; the existing trailing selector treats a
predecessor as an exclusive boundary and does not collect it as a selected
baseline.

## 4. Source, runtime, and repository boundary

Code, contracts, tests, the small pilot configuration, and small acceptance
summaries are tracked.  SEC payloads, filing packages, taxonomy caches, Layer 1
snapshots, Parquet publications, and generated delivery views remain runtime
data outside Git.  The initial integrated delivery belongs under an ignored
path such as `data/processed/universe_runs/<run-id>/` and contains:

- `completion/index.html`;
- company-readiness JSON and CSV;
- collection plans, intake manifests, attempts, and aggregate status;
- the B metadata publication;
- the C Q4 table and exact source trace; and
- a reproducible runtime README with source revision, commands, input
  locations, as-of date, source observation times, and rule versions.

The supported-transform migration uses a new ignored root
`data/processed/universe_runs/20261008_sec_transform_v5/` for its operations,
fresh Layer 1 snapshots, governed histories, Q4 publications, evidence, and
completion view.  The accepted runtime subroots are `operations_v5`,
`source_bindings_v1`, `analysis_history_v5`, `q4_delivery_v5`, and
`completion`.  It reuses the immutable cached source packages under
`data/raw/universe_runs/20261008_duration_v4/` without rewriting them.  It does
not rewrite or delete the earlier
operations, raw, retry, analysis, Q4, or completion artifacts.

No runtime report may embed `SEC_USER_AGENT`, secrets, or mutable cache
contents.  Runtime evidence identifies source paths or content digests and
stage labels `LIVE`, `CACHE`, or `REUSED`.  Reuse is verified against the
planned CIK, accession, form, filed date, and report date; discovery completion
alone is never parse success.

## 5. A operational contract

Preparation reads the external cohort configuration and creates one company
workspace and immutable history plan per company.  A caller may provide an
already written plan, in which case collection reuses it without discovery.
Changing a plan under the same identity is refused.  Preparation failure for
one company is recorded and does not prevent other companies from preparing.
Before any wrapper write or delegated ingest/build call, the operation verifies
that the request contains the exact company membership, every company path is
the fixed safe path under the run root, and no wrapper-owned run, intake,
attempt, status, destination, or temporary-file path traverses a symlink.  A
separate caller-declared publication root is permitted, but it and every
generated company child must remain free of internal symlink redirection.

Collection calls the existing `ingest_history` contract per prepared company.
The default network scheduler is serial so existing SEC client throttles remain
authoritative.  Independent computation over already captured metadata may be
parallelized, but Arelle must not be shared unsafely and the wrapper must not
launch uncoordinated request processes.  An existing verified snapshot may be
reused from a declared source run.  Every retry appends an attempt record and
retains the previous outcome.

Collection and build accept an optional nonempty, unique subset of safe tickers
from the attested request.  The subset narrows only that invocation's company
loop; the immutable request, company manifest, full-run preflight, and aggregate
status continue to cover the complete cohort.  This permits one-company
processes so parser or publication memory is released between companies.  An
unknown, duplicate, unsafe, or empty subset fails before any wrapper write or
delegated ingest/build call.  Every selected-company attempt records both the
operation subset and full request ticker list.  Omitting the subset preserves
the serial all-company behavior.

Build is an explicit optional phase.  A complete raw intake is
`RAW_COMPLETE`; it becomes `READY` only after requested governed publications
are built and verified.  An incomplete company never appears as successful or
ready.  A failed raw accession remains a retryable error and may not be
converted to a missing disclosure, unavailable analytical value, or zero.

Status reads only manifests and generated summaries.  It never calls SEC,
Arelle, discovery, ingestion, selection, or publication code.  Counts are
deterministic and include requested, planned/selected, held, succeeded,
failed, pending, and reused filings, along with CIK, ticker, requested dates, actual
available report-date range, current action, source stage, as-of date, source
observation time when supplied, and applicable rule/version identifiers.
`held_filings` is the number of validated successful `REUSED` or `INGESTED`
outcomes already available.  `pending_filings` is selected minus validated
successful and validated failed outcomes.  Invalid, duplicate, extra, or
out-of-scope outcomes are quarantined and do not increase any success count.

A `READY` build marker attests the exact plan and intake digests, history
manifest digest, and every declared publication file and digest.  Build verifies
the publication through `HistoryPublicationReader.verify_all()` before writing
that marker.  Ordinary status performs only offline manifest, path, existence,
scope, and digest checks; it does not invoke SEC, Arelle, selection, or
calculation.

### Duration-conformance assessment

The integrated publisher accepts an optional
`sec-duration-conformance-assessment-v1` JSON input for backward compatibility
with unrelated cohorts.  It is mandatory for this 2026-10-08 delivery.  Its
scope must equal the immutable A universe ID, financial as-of date, collection
request and collection-manifest SHA-256 values, requested-company count,
selected-filing count, and every governed-history manifest digest.

Before a `PASS` assessment can be consumed, the offline Raw/Quality producer
`sec_xbrl.source_bindings.publish_source_bindings` must publish an immutable
`sec-source-bindings-v1` directory.  It scans every planned cached primary
document outside the renderer, verifies the exact package and primary-member
bytes, and binds the source ID, Context reference, source lexical, transform
namespace/name, source QName, line and model row ordinal to the deterministic
Filing, Fact, Context, and Concept identities in the corresponding v5 Raw
tables.  It fails closed on an omitted, extra, duplicated, changed, unresolved,
or foreign source claim.  Its manifest covers the exact A request and
collection digests, all 381 packages, all 381 snapshot manifests, and the
Fact, Concept, and Context table hashes.

`SourceBindingsReader.verify_all()` is the completion-side trust boundary.  It
does not parse Inline XBRL, invoke Arelle, contact SEC, or normalize a value.
It verifies the separately prepared publication, cached package and primary
member digests, immutable collection membership, v5 table digests, and stable
Raw identities.  The assessment must name that publication ID and manifest
SHA-256 and include a `PASS` independent-verification record for its frozen
producer revision.  The candidate duration and correction JSON records must
then equal the governed bindings.  Re-hashing those two candidate JSON files
together cannot change a source ID, Context reference, lexical, primary hash,
or Fact binding accepted by the consumer.  Cryptographic signing and secret
key infrastructure are outside this local contract; a forged replacement of
the independently accepted publication and all of its declared parent inputs
is outside the stated trust boundary.

A `PASS` assessment binds `m2-layer1-v5`, duration rule
`sec-duration-conformance-v1`, supported-lexical policy
`sec-supported-lexical-repairs-v1`, the frozen 40-character source commit, all 381
verified source packages with none missing, and independent verification of
that same commit.  It declares SHA-256 identities for its evidence files and
must prove:

- one unique `PASS` check for every accession in the immutable A plans,
  including its source-package hash, v5 snapshot-manifest hash, duration-Fact
  count, and zero normalized mismatches, including filings with zero duration
  Facts;
- `TAXONOMY_AND_TRANSFORM_RESOLUTION`, `RAW_CORPUS_COMPLETENESS`, and
  `ATOMIC_FILING_SNAPSHOT` all pass, including fail-closed handling of an
  invalid duration lexical value;
- per-transform `durday`, `durmonth`, `duryear`, and `durweek`
  normalized-value mismatch counts are zero;
- actual normalized-value checks equal their expected values, including AMD
  accession `0000002488-23-000047`, source `4.55`, old `P4Y7M`, and corrected
  `P4Y6M18D`; and
- unapproved foreign-change counts are zero for non-duration facts, duration source
  lexicals, monetary values, Contexts, Units, dimensions, and relationship
  keys.

The fail-closed replay exposed 104 preexisting valid SEC lexicals that the local
helpers did not support: 48 `exchnameen` `Nasdaq` values, 19
`stateprovnameen` `Idaho` values, five `durwordsen` values containing U+2011,
and 32 `numwordsen` `nil` zeros.  An allowed repair must appear in the distinct
hashed `sec-approved-inline-transform-corrections-v1` record set and match the
hashed 104-row source index.  The publisher checks every record against the
actual v5 Fact and Concept tables, including planned CIK/accession, stable
source ID, Fact ID, Context ID, source QName, concept data type, Inline XBRL
element type, transform namespace/name, lexical, sign, scale, primary-document
hash, old sentinel, expected raw value, actual raw value, `is_nil=false`, and
the exact named repair policy.  The numeric corrections are reported as 22
monetary zeros and 10 share zeros; they are reported values, not XBRL nil.
This bounded allowlist does not relax the zero count for every unapproved
difference, and old snapshots retain the sentinel unchanged.

For the 381-filing cohort, the exact verified source index contains 3,842
duration Facts: 481 `durday`, 391 `durmonth`, 2,902 `duryear`, and 68 `durweek`.
The per-filing and per-transform totals must reconcile to those exact counts.
The assessment binds the 381-row filing index, its 3,842 source-Fact entries,
and external fact-level evidence by path and SHA-256.  Every source entry must
match CIK/accession/source ID/stable Fact ID/format/lexical and every evidence Fact ID must
exist exactly once in the corresponding v5 snapshot with the declared
normalized raw/text value, Context, reported/non-nil state, and Concept QName.
This prevents a partial scan, invented Fact ID, or self-consistent but false
value declaration from being reported as conformance.  The separate governed
source-binding publication also prevents a self-consistent re-hash of both
candidate evidence files from replacing the actual cached source fields.

`BLOCKED` is an overall delivery block and `PENDING` keeps the overall delivery
partial.  Both require an explicit reason.  Omitting the assessment preserves
the API behavior for other callers, but cannot be used for this cohort's final
publication.  The completion manifest records the assessment and every
declared evidence digest; the HTML displays its state, parser version, and
frozen commit.

## 6. Acceptance gates

### A gates

1. An external configuration drives all companies; engine code has no pilot
   ticker branches.
2. Offline tests prove immutable plan reuse and plan-drift refusal, independent
   company failures, retry history, source-run reuse, as-of handling, and
   available-period short-history behavior.
3. A failed company does not cancel another company, while its incomplete raw
   history cannot become `RAW_COMPLETE` or `READY`.
4. Aggregate status counts reconcile exactly to company plans and accession
   outcomes.  Repeated offline status reads are byte-deterministic for unchanged
   manifests.
5. Network collection is serial by default, and status performs no network or
   parser work.
6. Offline tests prove that a validated company subset changes only the invoked
   collection/build loop, preserves full-cohort counts and other-company state,
   and rejects invalid scope before calls or writes.
7. Relevant history-workflow tests and Ruff pass at a frozen commit.

### B gates

1. Published identity and SIC rows retain snapshot path/digest, source,
   observed-at time, and any source URL.
2. Every requested company is represented or has an explicit unresolved
   reason; duplicate/conflicting identifiers fail closed.
3. Publication files and manifest are immutable, integrity checked, and
   reloadable offline through `CompanyMetadataReader`.
4. Peer candidates remain traceable classifications and never alter company
   facts or canonical accounting mappings.

### C gates

1. Every derived Q4 value traces to exact approved FY and YTD-9M sources, full
   dimensions, compatible units/basis, formula, rule version, reviewer decision,
   and approval-ledger identity.
2. Excluded, ambiguous, and unresolved scopes remain explicit; none receives a
   numeric derived value.
3. The initial 16-cell NVDA target is reconciled to exact source evidence and
   approved by the lead before publication.
4. Existing undimensioned core and mechanical-candidate behavior remains
   unchanged.  FY and quarterly consumer outputs remain distinctly labelled.

### Common delivery gates

The three streams retain Raw, Analytical, Derived Metrics, and Display plane
boundaries from [`m0-data-contract.md`](m0-data-contract.md).  Runtime execution
reports actual company, filing, period, row, success, and failure counts and is
separate from code implementation evidence.  A frozen implementation commit
requires independent read-only verification before local acceptance.  Push,
PR, CI, merge, and main status remain outside this currently authorized local
delivery unless separately approved.

The initial collection threshold is 21/21 immutable company plans covering 381
selected filings: acquisition history records 128 existing source snapshots
and 253 new intake filings.  Every selected accession must become
`RAW_COMPLETE`; a failure blocks only that company's readiness while remaining
visible in aggregate counts.  The metadata threshold
is 21/21 identity coverage with a SIC classification or an explicit unresolved
reason and no duplicate/conflicting identifiers; the current source evidence
contains SIC values for all 21.  The initial C threshold is
exactly 16 lead-approved NVDA cells.  Governed data-quality exclusions,
ambiguous scopes, and unavailable analytical values count as explicit reviewed
outcomes rather than delivery failures; they must remain non-numeric and
traceable.

The duration-conformance threshold is a `PASS` assessment for the exact fresh
381-filing v5 cohort.  Structural completion, unchanged counts, or a zero-error
parse run without normalized-value comparisons does not satisfy this gate.

The accepted runtime met these gates with 21/21 raw and governed histories
ready, 381 held filings, zero failed or pending filings, 741 verified history
Parquet files, 21 pilot SIC classifications, 3,842 verified duration facts,
104 approved transform corrections, zero unapproved foreign changes, and the
approved C threshold of 16 economic values represented by 32 view records.
The B master retains 8,016 candidates, including 7,995 explicit unclassified
issuers.  Exact source identities, runtime counts, browser evidence, remaining
accounting limits, and the accepted completion manifest are recorded in
[`universe-data-delivery-completion.md`](universe-data-delivery-completion.md).

## 7. Assumptions and unresolved cases

- The 21-ticker file is an initial configuration, not the supported-company
  boundary.
- Resolved CIKs may be omitted until discovery or B supplies evidence; any
  configured CIK must be checked against discovered metadata.
- Four completed annual baselines may not exist for a short-history filer;
  retaining its explicit actual report-date window is the approved fallback.
- A supplemental predecessor is collected only when a named analytical need
  requires it and the plan records why it was added.
- Company history publication is optional during A collection.  No status
  claims analysis capability until the requested build outputs verify.
- Individual C review decisions remain lead-owned accounting judgments even
  though C's delivery implementation is authorized.
