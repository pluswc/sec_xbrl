# U3 follow-up: governed statement and segment hierarchy

Status: implementation plan for H1, U3-R, H2, and H3  
Baseline: immutable U3 commit `09309c80700fed2115e2b18eddd2c21dc5e200e3`  
Implementation branch: `codex/u3-followup-hierarchy`

## Scope and acceptance

This follow-up adds a new immutable publication beside U3 v1. It does not
rewrite U3 importance rows, source facts, old bundles, or old HTML. The work
uses the existing preparation boundary so consumer queries and HTML never open
SEC packages, run history selection, or calculate accounting results.

H1 publishes both independently enumerated primary-HTML table rows and PRE row
paths for income statements, balance sheets, and cash-flow statements. HTML
rows retain source-document/table/row locators and the validated document hash,
including headings, groups, blank cells, nonnumeric rows, subtotals, and rows
without a usable fact. PRE coverage and rendered-HTML coverage are separate;
their differences remain explicit. H1 links exact Raw as-filed FY, YTD, QTD,
and instant facts in separate period contexts, and separately exposes the
governed quarterly analytical view with its selection metadata. PRE display
paths, CAL arithmetic, DEF dimension
paths, and reviewed display hierarchies retain distinct relationship types.
CAL checks preserve the signed weight, every available input, calculated value,
reported parent, exact difference, and a closed status vocabulary. A CAL match
does not approve a positive-parent economic composition or a share.

U3-R publishes `u3r-important-items-v2` records separately from U3 v1. Each
amount, share, amount-change, rate-change, and share-change signal has its own
status, reason, inputs, current period, comparison period, and denominator.
The lead approved these transparent, versioned v2 display defaults after
source comparison:

- reviewed economic share: at least 10 percent;
- comparable reviewed share change: at least 5 percentage points;
- comparable year-over-year absolute rate: at least 25 percent, together with
  an absolute monetary change of at least 1 percent of an exact positive
  disclosed reference scalar.
- amount display signal: the top three exact comparable monetary children.

The reference scalar is only a scale test. It is not approval that the item is
an economic child of the scalar. Missing or incompatible exact denominators
remain unavailable. Zero and negative bases, sign transitions, basis changes,
and absent filing-scoped members retain explicit states. No fallback sum,
normalization, synthetic residual, similarly named member join, or future
period fill is allowed.

These defaults are analytical display rules, not accounting materiality
standards or optimized cutoffs. No industry override, quarter-over-quarter
growth, or annual-growth policy is introduced in this version. Actual AMD Q3
Embedded and Client changes show why the old 50 percent rate condition misses
large monetary moves. Actual NVDA OpEx provides reviewed two-period share
evidence, but not a five-point share-change trigger. Rank-six share,
share-change-only, threshold boundaries, and tiny-base rejection remain
explicitly synthetic policy evidence.

H2 reads the H1 and U3-R datasets through `AnalysisClient`. It offers one
ordered table with nested rows, depth controls, restored hidden rows, stable
subtotals, calculation evidence, independent Axis lenses, and member metric
lookup. Folding changes only visibility. It never changes values or checks.

H3 covers the five-company regression cohort and cached NFLX outside-cohort
publication. Real-cache evidence is reported separately from synthetic edge
cases. It checks NVDA operating expense arithmetic, MSFT's separately disclosed
expense structure, AMD reviewed member hierarchy and restructuring, NVDA's
FY2026 Q3-only Data Center disclosure, exact-axis isolation, member duplicate
protection, API/HTML agreement, producer and network blocking at query time,
and byte hashes of every original U3 file.

## Implementation seam

`prepare_analysis` remains the only Raw/history-reading boundary. It verifies
the immutable accession package manifest and XBRL ZIP before opening the
filing-discovery-declared primary document. After it loads immutable Raw facts,
contexts, units, dimensions, concepts and fully qualified relationships and
compacts selected analytical cells, an H1 materializer produces these
immutable datasets:

- `source_statement_rows`: independently enumerated HTML rows and coverage;
- `statement_rows`: filing/base-set/role/path-scoped PRE rows with source order;
- `statement_cells`: exact Raw as-filed and governed analytical value links;
- `statement_relationships`: typed PRE and CAL evidence;
- `calculation_checks`: signed arithmetic and independent share eligibility;
- `row_coverage`: included, structural, unprepared, and excluded row status;
- `statement_contexts`: explicit period/filing/role choices used by H2;
- `importance_v2`: separate U3-R evidence records.

Existing `nodes` and `edges` remain the source for independent Axis lenses,
DEF member paths, and reviewed display hierarchy. Existing U3 `importance`
remains readable byte-for-byte in old bundles and unchanged in the new source
contract.

## Assumptions and unresolved cases

- H1 keeps Raw as-filed FY, YTD, QTD, and instant contexts separate from the
  governed quarterly analytical view. It does not mix or derive them.
- Source precision is not present in compact cells. Arithmetic therefore has
  no guessed tolerance: exact zero difference is a match.
- A derived Q4 with multiple filing inputs is not a same-filing CAL check.
- Capital-change statements and disclosure-note tables are outside H1's
  selected statement-table scope. Their row-level exclusion is recorded when
  the role or source table can be classified.
- Actual economic share approval needs an exact, hash-bound source review.
  Until such evidence is supplied and accepted by the lead, actual shares stay
  `REVIEW_REQUIRED`; synthetic tests alone do not authorize a company rule.
- A latest filing without a prior filing-scoped member remains absent, not zero.
  Raw member names are never used to infer a longitudinal join.

## Verification and freeze

The implementation writer runs focused tests, the full pytest suite with the
cache provider disabled, Ruff without cache, six-company cached preparation
and probes, an actual browser probe, old-file hash comparison, and query-side
producer/network blocking. Generated output is published under a new immutable
`work/u3_followup_complete` directory. Explicit source/test/doc paths are
committed locally, and the final local SHA is frozen for a separate read-only
verifier. Push, PR creation, CI, and merge are excluded from this run.
