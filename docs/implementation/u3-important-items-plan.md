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
