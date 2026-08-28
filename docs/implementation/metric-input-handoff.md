# L2-M6 — Derived Metrics Input Handoff

L2-M6 is the boundary between governed Layer 2 selection and the later
Derived Metrics plane.  It publishes *input candidates and compatibility
diagnostics only*.  It does not calculate, store, or register a metric.

## Inputs and provenance

`MetricInputHandoffMaterializer` consumes selected `analytical_fact` rows.
Every emitted `metric_input_candidate` retains the selected analytical Fact
ID, selected raw Fact ID where one exists, source filing, view, as-of date,
basis version, series/period, full canonical dimension signature, unit,
mapping version, and source type.  `UNAVAILABLE` selected facts retain their
reason rather than being silently dropped.

Roles are recognised from an explicit upstream `metric_input_role`, or from a
named standard QName (for example `us-gaap:GrossProfit`).  Labels and fuzzy
company-extension names are never used to infer a role.  A company extension
therefore needs an explicit, governed role assignment before it can enter a
metric assessment.

## Assessments

| Assessment | Required safe inputs | Result here |
| --- | --- | --- |
| `GROSS_MARGIN` | one Gross Profit and one Revenue with equal company, view, as-of date, series type, period, basis, full dimensions, and unit | eligible inputs or a reasoned unavailable diagnostic |
| `OPERATING_MARGIN` | one Operating Income and one Revenue under the same compatibility checks | eligible inputs or a reasoned unavailable diagnostic |
| `REVENUE_GROWTH` | current Revenue plus an explicitly declared predecessor period, with the same governed compatibility fields | eligible inputs or `PREDECESSOR_PERIOD_NOT_DECLARED` / incompatibility |
| `Q4_FLOW` | a governed `DERIVED_RECAST` QTD candidate with two or more source Facts, derivation rule, and formula | eligibility only; no Q4 value is calculated here |

Period ordering is never guessed from a display key.  Revenue growth needs a
governed `comparison_period_key`; a consumer cannot cause L2-M6 to sort text
labels and infer a predecessor.

EPS and weighted-average shares are `DIRECT_OBSERVATION_ONLY` only when they
retain a directly reported raw Fact (`REPORTED`, or evidence-backed
`RECAST_REPORTED`).  A derived/no-raw-Fact result is `UNAVAILABLE` with
`DIRECT_OBSERVATION_REQUIRED`; its source selection reason is retained
separately.  They can never be accepted as controlled Q4 subtraction inputs.

## Output contract

- `metric_input_candidate`: one recognised selected observation, not a metric
  value. `CANDIDATE`, `UNAVAILABLE`, and `DIRECT_OBSERVATION_ONLY` are
  distinct states.
- `metric_input_compatibility`: one assessment at a governed company/period
  scope. It lists required roles and the ordered analytical/raw input IDs,
  compatibility state, and an explicit unavailable reason when unsafe.

An optional `metric_definition_id` may be supplied from a future governed
definition source.  The materializer does not maintain such a registry, and
the assessment identifiers above are compatibility checks rather than metric
definitions.

The atomic publisher rejects calculated-value fields in either dataset.  A
future Derived Metrics-plane process is responsible for formula versions,
calculation, and durable `derived_metric` records.
