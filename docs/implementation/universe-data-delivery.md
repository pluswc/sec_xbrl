# Company-universe data delivery contract

## 1. Authority, status, and baseline

On 2026-10-08 the user authorized implementation of the A/B/C company-universe
delivery described here, including a real initial cohort and tangible local
runtime artifacts.  The implementation baseline is
`201acf9aec2f8183acb7dd843579938db14236cd` on
`codex/company-universe-delivery`.

The current state is **APPROVED for implementation**.  It is not yet
`IMPLEMENTED`, `INDEPENDENTLY_VERIFIED`, `LOCALLY_ACCEPTED`, or `MERGED`.
Those states require their own dated evidence under
[`delivery-workflow.md`](delivery-workflow.md).  This contract does not create a
new architectural Layer and does not replace the M architecture roadmap or U
investor roadmap.

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
source contracts.

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
selected filings: 128 existing source snapshots are expected to be reusable
and 253 filings require new intake.  Every selected accession must become
`RAW_COMPLETE`; a failure blocks only that company's readiness while remaining
visible in aggregate counts.  The metadata threshold
is 21/21 identity coverage with a SIC classification or an explicit unresolved
reason and no duplicate/conflicting identifiers; the current source evidence
contains SIC values for all 21.  The initial C threshold is
exactly 16 lead-approved NVDA cells.  Governed data-quality exclusions,
ambiguous scopes, and unavailable analytical values count as explicit reviewed
outcomes rather than delivery failures; they must remain non-numeric and
traceable.

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
