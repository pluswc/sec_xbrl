# C3-M2 — Governed Quarterly Period Policy

## Purpose

C3-M2 is a small companion release after C3-M1.  It makes two line-level
decisions explicit for the seven-company AS_FILED scenario:

1. whether an FY and YTD_9M pair may be subtracted to expose a derived Q4
   flow; and
2. whether an observed line has a declared predecessor period in the same
   comparable scope.

It does not modify C3-M1 `analytical_fact`, produce a growth Metric, select a
`CURRENT_COMPARABLE` value, or infer a disclosure from a missing period.

## Input and release boundary

The materializer accepts only a `VerifiedLayer2Publication` read by Consumer
C2 and the exact `CorpusRelease` used for its `Layer2Run`.  Their fingerprints
must match.  Every selected source Fact is checked again against the immutable
raw release.  This keeps the policy result auditable while avoiding an
unnecessary expansion of the existing Layer 2 publication contract.

The result has three deterministic companion datasets:

- `quarterly_q4_candidate` — a distinct derived Q4 candidate with formula,
  declaration version, analytical Fact IDs, raw Fact IDs, and filing IDs;
- `quarterly_q4_exclusion` — an explicit non-eligibility reason; and
- `predecessor_period_linkage` — either a same-scope predecessor ID or
  `PREDECESSOR_PERIOD_NOT_DECLARED`.

## Q4 policy

No concept is Q4-eligible by default.  A `QuarterlySemanticDeclaration` must
positively declare its company-canonical concept as
`REVIEWED_ADDITIVE_AMOUNT` / `ADDITIVE_AMOUNT` / additive.  Each source is
also required to be a directly reported AS_FILED monetary duration Fact with
exactly one ISO 4217 numerator currency measure, no denominator measure, and
raw lineage.  Multiple currencies, EPS, weighted shares, ratios,
margins, averages, instant/balance-sheet values, text, and unknown semantics
therefore fail closed.

Both sources must have identical company, canonical concept, complete
dimension key, basis version, and unit semantics.  Their fiscal start date
must match and the YTD_9M endpoint must precede the FY endpoint.  The output
is `FY - YTD_9M`, never an overwrite of reported data.

## Predecessor policy

Predecessors are links, not calculations.  A link is emitted only within the
same company, canonical concept, complete dimensions, basis, unit, and exact
period class (`QTD_3M` or `FY`).  The first observed line in a scope is
explicitly unavailable.  The policy does not call this revenue growth or
assume a missing predecessor was not reported.

## Limits

This milestone is AS_FILED only and declares eligibility only.  A future
consumer or metric materializer may consume this governed result, but must not
re-derive Q4 or predecessor choice from display order, labels, or Excel.
