# Reviewed dimensional Q4 delivery contract

## 1. Authority, status, and baseline

On 2026-10-08 the user authorized implementation of the reviewed dimensional
Q4 companion and a separately labelled annual consumer bundle. The implementation
baseline is `201acf9aec2f8183acb7dd843579938db14236cd` on
`codex/reviewed-dimensional-q4`.

The current state is **APPROVED for implementation**. It is not yet
`IMPLEMENTED`, `INDEPENDENTLY_VERIFIED`, `LOCALLY_ACCEPTED`, or `MERGED`.
Those states require separate evidence under
[`delivery-workflow.md`](delivery-workflow.md).

## 2. Reviewed Q4 scope

The producer accepts an existing immutable history publication, a complete
source-pair evidence document, and a caller-supplied review ledger. It emits an
immutable companion publication containing:

- `reviewed_q4_candidate.parquet`, retaining every source-attested exact FY and
  YTD-9M structural pair considered by this run;
- `reviewed_q4_exclusion.parquet`, retaining every rejected or unreviewed pair
  and its precise reason;
- `reviewed_q4_review.parquet`, retaining only decisions that revalidate against
  the exact evidence and source publication; and
- `reviewed_q4_derived.parquet`, retaining only approved Q4 residuals.

`reviewed_q4_manifest.json` binds those datasets to the complete input files,
the parent history manifest, the selection view and as-of date, and each source
snapshot manifest. The reader verifies all hashes and rejects moved, changed,
partial, or symlinked publications.

An approval binds company, fiscal year, view, as-of date, mapping epoch, full
raw and canonical dimensions, concept, numerator-only monetary unit, actual
period dates, FY and YTD raw Fact and filing identities, source snapshots,
evidence table identities, reviewer, review time, purpose, policy version,
additivity judgment, basis judgment, formula, and approved result. Missing or
nonmatching approval remains unavailable and review-required.

The initial runtime target is the 16 lead-approved NVDA product-revenue source
pairs in each of `AS_FILED` and `LATEST_REPORTED`, for 32 view-specific
decisions. The retained analytical as-of date is `2026-09-06`; the later source
collection or review time never relabels the analytical selection.

## 3. Explicit exclusions

The producer does not approve FY2025 Data Center, Compute, or Networking because
their observed mappings use different epochs or require mapping review. It does
not approve segment, segment operating-income, or geography scopes. Geography
has a real billing-location to headquarters-location basis change. It also
rejects label bridges, Q1+Q2+Q3 aggregation, EPS, shares, ratios, pure units,
denominator units, non-additive values, view substitution, as-of substitution,
changed dimensions, changed dates, changed mappings, and changed source Facts.

Compute and Networking are nested inside Data Center for FY2026. Their approved
individual values may be displayed, but they may never be added to Data Center.
The top-level reviewed sums are USD 22,103 million for FY2024 and USD 68,127
million for FY2026.

The existing `history_quarters.approved_additive` guard, existing mechanical-Q4
candidate records, Raw publications, and existing history publications are not
changed or reclassified. This companion is a separate reviewed producer and
does not impersonate earlier candidate identifiers.

## 4. Consumer connection

`prepare_analysis` retains its existing quarterly default. When an explicit
reviewed-Q4 publication is supplied, it verifies the companion and fills only
an absent Q4 coordinate whose exact row identity, mapping epoch, dimensions,
view, as-of date, and source parent publication match. A directly reported or
already materialized coordinate always wins; conflicting or unavailable cells
are never overwritten. Prepared cells retain the source mapping epoch and carry
the reviewed formula, both source inputs, review, and source-table evidence in
their trace. Relevant exclusions refine an unavailable reason without asserting
that the disclosure is missing.

Queries, HTML, snapshots, CSV, and XLSX only read the prepared result. They do
not calculate Q4.

## 5. Annual consumer mode

An explicit `ANNUAL` preparation mode loads FY duration panels only and publishes
to its own destination and publication identity with `period_mode: ANNUAL`.
The default remains `QUARTERLY`, loading `QTD_3M` and `INSTANT` as before.
Annual and quarterly lenses are never co-located because existing lens IDs do
not include the period class. FY axis time-series queries are permitted only in
an annual bundle and mixed period classes fail closed. Annual columns display as
`FY2024`, never `FY2024 Q4`.

Existing quarterly reviews do not imply annual review. Existing ratio, QoQ, and
YoY policies remain unchanged; where they do not support annual input, the
result remains unavailable rather than introducing a new annual metric policy.

## 6. Acceptance gates

1. An approved derived record revalidates the complete exact source pair,
   parent publication identity, raw snapshot identities, review fields, formula,
   and expected result. Tampering or parent drift fails closed.
2. Missing decisions and every stated excluded scope remain nonnumeric and carry
   a specific review-required or exclusion reason.
3. Directly reported/materialized cells take precedence over the companion.
4. Existing quarterly preparation without a companion is unchanged.
5. Annual output is isolated, labelled `ANNUAL`, contains FY duration data only,
   and permits FY-only axis queries while rejecting mixed classes.
6. Synthetic tests cover approval, tampering, parent drift, full scope, units,
   dates, mapping, future-as-of, direct-cell precedence, quarterly compatibility,
   and annual isolation and labels.
7. A cached integration run traces all 32 approved view-specific decisions to
   16 economic Q4 cells per view through source, review, producer, API, snapshot,
   and XLSX without network access.
8. Focused tests and Ruff pass at a frozen local commit before independent
   read-only verification. Push, PR, CI, and merge remain outside this delivery.

## 7. Runtime inputs

The first approved inputs are external runtime evidence and are never copied
into engine code:

- history: `data/processed/analytical/history/five_company_custom_continuity_v5/panels`;
- source pairs: `data/processed/universe_runs/20261008_initial/q4_lead_review/source_pairs.json`;
- approval ledger: `data/processed/universe_runs/20261008_initial/q4_lead_review/lead_approval.json`; and
- snapshots: `data/processed/trailing_corpus_runs/20260827T051322Z/snapshots/<cik>/<accession-without-dashes>`.

The runtime guide records exact commands and destination paths. Runtime data,
SEC payloads, Parquet output, reports, and XLSX files remain outside Git.
