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
- `OTHER_DURATION`
- `INSTANT`

Use fiscal calendar and actual days; do not assume calendar quarters.

## PR-005 — 3M and YTD never mixed
A Q2 3M revenue and Q2 6M YTD revenue are distinct observations.

## PR-006 — Cash flow caution
10-Q cash-flow facts are often YTD. A quarterly flow may be derived only by subtraction of compatible additive facts.

## PR-007 — Derived Q4
Potentially `FY - YTD_9M`, but only when:
- same canonical concept
- same dimensional context
- compatible units
- additive duration fact
- no structural/recast incompatibility

Never use simple subtraction for EPS, margins, ratios, averages or non-additive metrics.

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
classification uses the Context's actual start/end days, with FY accepting
350–378 days to cover 52/53-week fiscal years.  Q4 derivation requires an
explicit `canonical_concept_id`, `is_additive=true`, equal dimensional context,
units, fiscal year, identical FY/YTD Context start date, and
structural/recast/comparability metadata. A fiscal-calendar change must be
represented by a differing `comparability_flag`, which rejects derivation
rather than silently bridging the change. A derived
record adds `formula`, `source_fact_ids`, and `derivation_rule_version` and is
always distinct from its reported sources.
