# U3 important-items analysis plan

## Purpose and status

U3 makes important financial items easy to find in the order **core item →
relevant view → important child → value and source evidence**. Within-company
history takes priority over cross-company ranking, and the policy applies to
revenue, expense, cash flow, assets, liabilities, and equity while preserving
the distinction between standard and company custom concepts.

This document is the durable requirement and acceptance plan. It does not claim
that U3, arbitrary-ticker onboarding, the status representation below, or any
draft threshold has been implemented. Optional local evidence locators may be
recorded in `work/U3_HANDOFF.md`; they are not normative dependencies.

## Product scope and invariants

- The existing five companies are regression samples. Any filer covered by the
  SEC/form contracts can be registered, prepared, and queried through the same
  administrator configuration and consumer API without ticker-specific engine
  code or per-ticker conditionals.
- A generic parser, traversal, preparation, or display defect exposed by a new
  company may be fixed generically. Company-specific concept selection, display
  preferences, and accounting interpretations belong in configuration and
  explicit administrator review. A newly encountered custom disclosure is
  handled by a manually scoped review, not a ticker exception or inferred
  approval.
- Current support follows the repository contracts for 10-K, 10-Q, 10-K/A, and
  10-Q/A. It does not guarantee full financial-institution, foreign-issuer,
  taxonomy, or custom-disclosure coverage.
- Raw, reported, derived, reviewed, and display values retain their existing
  provenance and plane boundaries. An importance filter never fabricates,
  rewrites, or hides the recoverability of source values and decisions.
- Consumer queries only select, sort, page, and trace prepared results. They do
  not collect SEC data, parse XBRL, calculate financial values, or make review
  decisions. Registration, collection, calculation, review, and publication are
  explicit preparation or administrator operations.

## U3-A — policy and API contract

Before implementation, approve the ranking and eligibility decisions using
actual examples. Thresholds, weights, limits, and new function parameters are
drafts until that decision is recorded.

### Approved policy decision — 2026-09-08

Preparation uses policy `important-financial-items` version
`u3-important-items-v1`. The reference is the latest quarter in the requested
context, even when a branch has no value in that quarter. Ranking is by absolute
amount within the exact parent, view, period class and complete currency unit;
ties use stable `node_id`. Current-reference rows precede historical fallback
rows. When the reference has no prepared observation, a former top-five item is
identified as `REFERENCE_PERIOD_UNAVAILABLE_FORMER_TOP_AMOUNT`, retains its
latest historical evidence period/rank/cell, and is never shown as a current
zero or called a disappeared disclosure.

The default contains current top-five amounts, exact-node pins, critical source
or review warnings, sign transitions, incompatible reporting-basis breaks,
rate changes of at least 50 percent whose absolute change also ranks in the top
five, the historical fallback above, and structural navigation needed to reach
those items. Amount-change rank and small-base/high-rate change remain separate
evidence and do not alone promote an item. Presentation exclusions cannot hide
a pin or critical warning. The all-items path recovers excluded items, hidden
views, warnings and reasons.

Actual NVDA FY2026 Q3 evidence exposed the identifier-order defect. In its
`ProductOrServiceAxis` revenue lens, Data Center was USD 51.215 billion, Compute
USD 43.028 billion, Networking USD 8.187 billion, Gaming USD 4.265 billion,
Professional Visualization USD 0.760 billion, Automotive USD 0.592 billion,
and OEM and Other USD 0.174 billion. Stable node order had placed OEM and Other
before Data Center. Compute and Networking overlap the Data Center presentation,
so this evidence approves magnitude ordering and also demonstrates why the lens
must not be treated as an additive decomposition.

Parent share requires a separate administrator-reviewed complete and mutually
exclusive economic-decomposition record. It binds exact parent/child cells,
explicit full-dimension scopes, actual periods, period class, unit,
classification basis, corresponding filing/source-period pairs, reviewer,
review time, and an immutable evidence-file hash. CAL, co-presentation,
observed dimensions, and reviewed display hierarchy are insufficient.
Zero/negative parents, offsets, nils, duplicates, incomplete sets, and
unit/period/basis/source mismatches stay unavailable. Values above 100 percent
are warned without normalization, and no residual is invented.

The design must:

1. Preserve separate, explainable reasons for amount, parent share, amount
   change, and rate change rather than collapsing them into an unexplained score.
2. Define the ranking reference period and stable historical row ordering,
   including a counterexample for a large item that disappears during the range.
3. Define how the default top items, user-pinned items, warnings, and abrupt
   changes interact; return excluded counts/reasons and an all-items path.
4. Compute parent share only for an evidenced economic inclusion relationship
   with matching company, view, period, unit, full dimensions, classification
   basis, eligible filing selection, and—when derived—complete source-period
   pairs. Co-presentation or a CAL edge alone is not proof of a complete,
   mutually exclusive decomposition.
5. Return an unavailable reason for zero/negative parents, offsets, incomplete or
   duplicate decomposition, nil, mismatched units/periods, and incompatible
   bases. Do not normalize shares over 100%, force totals to balance, or invent a
   residual outside an eligible decomposition.
6. Distinguish base effects, small-amount/high-rate changes, loss-to-profit
   transitions, and reporting-basis changes. Never promote an unknown basis to
   `COMPATIBLE` or remove existing reported-arithmetic warnings.
7. Scope cursors to the selection policy, reference period, filters, context,
   node, and ancestor path, while preserving existing public calls.

## U3-B — prepared evidence and consumer views

Persist eligible shares, change measures, ranks, reason codes, policy identity,
warnings, and source lineage during preparation. Connect Python and HTML views to
the same prepared result. Company profiles may control labels, ordering, pinned
or excluded presentation, and exact existing concept/view selection; they may
not create relationships, approve accounting meaning, or alter governed values.

Publish new results immutably and leave existing publications readable. Hidden
items and critical warnings remain recoverable through the API and UI. Preserve
QTD versus instant periods, Q4 source pairs, source filing/role, complete units
and dimensions, review history, and traceability.

## U3-C — arbitrary-company end-to-end acceptance

Completion requires both the five-company regression cohort and at least one
real SEC filer outside that cohort. The outside filer must be onboarded without
ticker-specific engine edits, then pass:

1. administrator registration with an explicit period and configuration;
2. real collection or an explicitly identified cached Layer 1 source;
3. governed analysis and immutable consumer preparation;
4. lookup through the same public consumer API used by existing companies;
5. a period/configuration refresh that preserves the prior publication and does
   not change existing-company results.

A synthetic ticker, a `TEST` fixture, or recollecting one already-used AAPL
filing does not prove new-company end-to-end support. The acceptance record must
identify which stages used live SEC input and which used an explicit cache.

For every target, distinguish unsupported scope, preparation failure, supported
but not prepared, administrator review required, and actual disclosure absence.
The exact persisted enum/API is to be designed, but semantic collapse is not
allowed. Data not yet held is a collection target, never evidence of a missing
disclosure.

## Verification and completion report

Verify important children and reasons in the same API and actual UI, and
independently recompute eligible shares. Cover zero/negative parents,
duplicates/multiple axes, basis changes, disappearing items, Q4, invalid cursors,
and unit/period mismatch. Confirm that configuration changes do not alter data or
meaning, hidden values and warnings remain recoverable, and original values,
sources, approvals, and existing company outputs are unchanged.

Run focused and regression tests with query-side producer/network blocking. A
frozen commit receives independent read-only verification under
`docs/implementation/delivery-workflow.md`. Report code completion, real-data
completion, unsupported/failed/not-prepared/review-required/missing states, and
remote publication separately.

Excluded unless separately approved: narrative-to-zero inference, unrestricted
custom bridges, EPS Q4, automatic approval of new-filing meaning, an ad hoc
historical `as_of` reselection, cumulative overview mode, Excel output, and a
claim of comprehensive financial-sector or foreign-issuer support.

## Staged implementation evidence (2026-09-08)

The five-company pre-freeze build preserved the existing columns, core rows,
core cells, cells, metrics and trace datasets byte-for-byte while adding U3
datasets. With producer functions and socket connection blocked, the same API
returned default eight-quarter and explicit twelve-quarter views, nested AMD
reviewed hierarchy/Q4 values, and traces for all five companies. The local
optional record is `work/u3_final_five/consumer_probe.json`; it is acceptance
evidence, not a normative input.

NFLX (CIK 0001065280) supplied the outside-cohort case using 12 real SEC filing
snapshots from the explicit cached Layer 1 run
`data/processed/trailing_corpus_runs/20260827T051322Z`. Generic registration,
offline discovery/reuse, governed history, immutable FY2023–2025 preparation,
the common consumer API, and a separate FY2024–2025 refresh passed. Reopening
the earlier bundle after refresh preserved its manifest hashes and periods.
No live SEC request was used in this acceptance run; every filing input was the
identified cache. No NFLX custom meaning or economic decomposition was
automatically approved, so such shares and interpretations remain review
required. The optional detailed record is
`work/u3_acceptance_nflx/EVIDENCE.md`. Frozen-commit independent verification
and remote publication remain separate completion gates.

## Corrective candidate after independent rejection (2026-09-08)

Independent verification of local candidate `d5bc5406a74a70079847850f53e4ee863cb61e2d`
found duplicate underlying child values, unvalidated derived source intervals,
and truthy non-boolean review completeness could incorrectly produce shares.
The lead escalated the sole implementation role from Sol to Astra because
repeated corrections had left semantic omissions; the separate Astra verifier
remains read-only. This records a task-specific escalation, not a model ranking.

The corrective producer rejects aliases of the same cell/value node, raw Fact,
or complete concept/dimension/source scope. Ambiguous core-parent candidates
also fail closed. Review completeness must be boolean `true`; reviewer and
other evidence identifiers must be nonempty strings, and both review time and
publication cutoff must be timezone-aware with review no later than cutoff.
Missing, malformed, or unreadable evidence cannot authorize shares.

Reported duration/instant sources must correspond to the displayed actual
boundaries. Derived shares require an existing governed core cumulative rule
(Q2=6M−Q1, Q3=9M−6M, Q4=FY−9M), or separately reviewed disclosure Q4 rule,
with its approval/status/formula metadata, exactly two ordered source legs,
compatible full scopes, finite matching arithmetic, shared fiscal start and
correct exclusive output endpoints. The 75–105-day quarter window preserves
52/53-week calendars. Mechanical candidates and metadata-free subtraction
cannot authorize a share. No new company review is created by this change.

The HTML child first shows values and a short human-readable importance reason.
Complete reference/history evidence and exact reason codes remain accessible
under the initially collapsed “중요도 판단 근거” control. Local commit freeze,
independent rerun, real-cache artifacts, and remote publication are separate
gates. Remote push was rejected by automatic approval review for lack of
external-publishing authorization; this corrective work does not retry it.
