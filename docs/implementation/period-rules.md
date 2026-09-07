# 10-K / 10-Q Period Contract

## PR-001 — Filing role
- 10-K = Annual Baseline
- 10-Q = Current Update
- amendments preserved separately

## PR-002 — Context over filing
A filing can contain many periods. Fact identity/period classification comes from its Context, not merely from the filing's fiscal period focus.

## PR-003 — Instant vs Duration
Classify using concept period type + Context dates.

## PR-004 — Duration classes
Initial controlled vocabulary:
- `QTD_3M`
- `YTD_6M`
- `YTD_9M`
- `FY`
- `TTM`
- `OTHER_DURATION`
- `INSTANT`

Use fiscal calendar and actual days; do not assume calendar quarters. `FY`
requires both annual-start alignment and fiscal-year-end evidence from annual
filing focus or DEI fiscal calendar. A 350–378-day duration is only a candidate,
not proof. The ±7-day boundary tolerance accommodates 52/53-week calendars.
`TTM` requires positive rolling evidence: an annual-length interval ending at
the current interim filing focus and away from the DEI fiscal-year end.
Without sufficient boundary evidence use `OTHER_DURATION` with a reason.

## PR-005 — 3M and YTD never mixed
A Q2 3M revenue and Q2 6M YTD revenue are distinct observations.

## PR-006 — Cash flow caution
10-Q cash-flow facts are often YTD. A quarterly flow may be derived only by subtraction of compatible additive facts.

## PR-007 — Derived Q4
The reviewed Q4 policy may use `FY - YTD_9M` only when:
- same canonical concept
- same dimensional context
- compatible units
- additive duration fact
- no structural/recast incompatibility

Never use simple subtraction for EPS, margins, ratios, averages or non-additive metrics.

### M8 mechanical Q4 companion

Layer 2 also publishes a separate **mechanical candidate** companion.  Its
purpose is to make broad, company-specific analysis material available; it is
not a semantic approval and it never changes a Raw Fact, `analytical_fact`, or
the reviewed Q4-policy companion.

It admits an `AS_FILED` / `REPORTED` FY and YTD-9M pair when each raw source is
numeric, its Concept is `duration`, its Unit has at least one numerator measure
and no denominator measure, and the following full scope is exact:

```text
CIK + company canonical Concept + full Dimension signature + basis version
+ unit semantics + actual fiscal-year start/end boundaries
```

The FY and YTD-9M must have the same actual start date, the YTD end must be
before the FY end, and exactly one compatible pair may exist for the actual FY
end.  The output is `QTD_3M = FY - YTD_9M`, with every input analytical Fact,
raw Fact, filing ID, formula, rule version, and a `MECHANICAL_CANDIDATE_REVIEW_REQUIRED`
selection status.  Duplicate compatible inputs fail closed as
`Q4_AMBIGUOUS_COMPATIBLE_INPUT_PAIR` with full implicated lineage.

No standard QName allowlist or PRE role gate applies here.  Custom Concepts and
dimensioned facts are admitted.  Instead, the companion retains flags such as
`CUSTOM_CONCEPT`, `DIMENSIONED`, `PURE_UNIT`, `SHARES_UNIT`,
`PRIMARY_STATEMENT_PRE_ABSENT`, and `RECAST_SENSITIVE`; consumers decide whether
to use a candidate.  A denominator-bearing Unit (for example USD/shares) is not
a mechanical candidate.

This broad companion is the current Layer 2 direction for period candidates;
it does not adopt the experimental narrow M7 reviewed-allowlist/PRE-gate
approach.  `FY - (Q1_3M + Q2_3M + Q3_3M)` is also deferred: the NVDA full-corpus
check found no extra eligible scope beyond direct `FY - YTD_9M`.  Reconsider it
only when a future-company corpus supplies a concrete case and dedicated
provenance/compatibility tests.

## PR-008 — Provenance
Derived facts store:
- `reported_or_derived = DERIVED`
- formula
- source fact IDs
- derivation rule version

They never overwrite reported facts.

## PR-009 — Comparative periods
Classify facts as current-focus, prior-year comparable, prior-FY balance, or other comparative context. One filing is not one period.

## PR-010 — As-filed vs latest-recast
Raw keeps every observation. Analytical views expose at least:
- `AS_FILED`
- `LATEST_RECAST`

Value changes are not automatically labeled restatements without evidence.

## PR-011 — Disclosure state
For Critical Disclosures:
- `BASELINE`
- `NEW`
- `CHANGED`
- `REPORTED_UNCHANGED`
- `NOT_REPORTED_THIS_QUARTER`
- `RESOLVED`

`NOT_REPORTED_THIS_QUARTER` is never automatically converted to `RESOLVED`.

## PR-012 — Fiscal calendars
Use DEI fiscal-year/period fields + actual Context periods. Support 52/53-week years and fiscal-year changes with comparability flags.

## M6 analytical output boundary
M6 copies raw fact rows into an analytical period result and fills `period_class`
and `comparative_type`; it does not mutate the M2 Parquet snapshot.  Duration
classification uses the Context's actual start/end days. Version
`m6-fiscal-boundaries-v2` additionally requires annual boundary evidence before
an annual-length interval becomes FY; TTM is never a fiscal annual input.
Normal reported observations retain the classification reason/version.
Q4 derivation requires an
explicit `canonical_concept_id`, `is_additive=true`, equal dimensional context,
units, fiscal year, identical FY/YTD Context start date, and
structural/recast/comparability metadata. A fiscal-calendar change must be
represented by a differing `comparability_flag`, which rejects derivation
rather than silently bridging the change. A derived
record adds `formula`, `source_fact_ids`, and `derivation_rule_version` and is
always distinct from its reported sources.

## Connected core-quarter consumer publication

The company-history producer now materializes a separate `derived_quarter`
Parquet dataset and connects those values to the persisted consumer panel.
The normal history build performs this step; load/query never calculates.
The controlled standard statement allowlists in `q4_policy_registry` authorize
only undimensioned monetary duration values with official annual FASB identity,
main-statement PRE evidence, resolved canonical identity and exact currency
semantics. Custom, dimensioned, EPS, share, ratio and average values remain
reported-only in this governed core companion. The broad mechanical candidate
companion remains a separate review-required product.

Quarterly differences are Q4=`FY-YTD_9M`, Q3=`YTD_9M-YTD_6M`, and
Q2=`YTD_6M-QTD_3M(Q1)`. A unique pair must share company canonical identity,
complete dimensions, unit, view/as-of, actual fiscal start, and any declared
basis/structural/recast versions; endpoint differences must be 75–105 days.
Inputs filed after the requested as-of, mapping uncertainty and explicit basis
breaks reject derivation. No evidence-backed recast equivalence is implied by
the absence of a documented break. Directly reported quarter cells take
precedence. A materialized unavailable/conflicting direct cell also remains
untouched; subtraction fills absent coordinates, not failed direct selections.
Balance-sheet year-end is an instant, never subtraction-derived.

Raw Arelle context endpoints are exclusive: a derived quarter begins at the
earlier cumulative endpoint, and duration is end minus start (no added day).
Every derivative keeps both raw Fact/filing/accession inputs, selected input
values and dates, formula, policy/rule version and compatibility statement.
Unavailable underlying disclosures remain unavailable; an absent gross-profit
concept is not invented by subtracting costs from revenue in this workflow.
