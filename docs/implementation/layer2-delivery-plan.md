# Layer 2 Delivery Plan — Longitudinal Analytical Materialization

> **Planning baseline / 계획 기준선.** This document records the currently
> agreed Layer 2 delivery proposal.  It does not alter an existing contract or
> claim that the described durable outputs exist today.  It requires explicit
> scope confirmation before expansion beyond the milestones below; once
> confirmed, its acceptance criteria are the delivery baseline.

## 1. Purpose and boundary

Layer 2 makes an individual company's immutable Layer 1 observations usable
as governed time series.  It is **within the existing Analytical plane**, not
a new architectural Layer.  It adds company-canonical mappings, period-aware
observations, governed selection, and capability information without changing
a raw Fact, Context, Unit, Dimension, filing, or relationship.

The intended user path is:

```text
company
  -> available statements, disclosures, axes, and members
  -> quarterly or annual series, with an as-of selection view
  -> comparability/unavailable reason and complete source lineage
```

Layer 2 is complete for this delivery sequence when a consumer can discover
what a company has actually reported, retrieve its company-internal annual or
current series, choose `AS_FILED` or the governed comparable/recast view, and
trace every selected value (or `UNAVAILABLE` result) back to its Layer 1
Fact, filing, mapping, and selection evidence.

This plan does **not** introduce a fourth Layer.  It follows the existing
Analytical-plane model in
[analytical-data-model.md](../architecture/analytical-data-model.md), the
same-company mapping contract in
[layer2-longitudinal.md](layer2-longitudinal.md), and the period rules in
[period-rules.md](period-rules.md).

### Explicit exclusions

- Layer 3 cross-company semantic mapping, peer panels, peer averages, ranks,
  or other cross-company metrics.
- A durable Derived Metrics registry or stored metric values.  Layer 2 can
  publish safe, compatible **inputs** and eligibility results only.
- Excel, API, or dashboard policy generation.  Those consumers read governed
  output; they do not create selection, recast, or metric policy.
- Mutation, replacement, or deletion of any Layer 1 raw snapshot.

## 2. Current baseline and corpus role

The current Layer 1 baseline is the recent-three-fiscal-year corpus for seven
companies: **AAPL (the requested `APPL` ticker), NVDA, TSLA, AMD, GOOGL, META,
and NFLX**.  It contains 102 successfully published filing snapshots.  The
corpus is Layer 2 input and external-to-Git operational data; no SEC package,
taxonomy cache, generated Parquet, or corpus output belongs in source control.

The initial focused validation cases are:

- **AAPL:** income-statement series and Product/Service plus geography
  dimensional disclosures.
- **NVDA:** business segment, market-platform, and geography disclosures;
  also the recast-selection golden case below.
- **TSLA, AMD, GOOGL, META, NFLX:** generality regression cases for period
  structures, company extensions, and observed dimensions.  They must not be
  treated as a pre-defined common disclosure template.

The 102-filing count proves Layer 1 corpus availability only.  It does not
prove that a concept/member is mapped, comparable, selected, or eligible for a
metric.

## 3. Common delivery rules

Every Layer 2 materialization must:

- read Layer 1 snapshots as immutable inputs;
- use QName-aware raw concept/axis/member identity and the full dimension
  signature, never labels alone;
- retain CIK, accession, form, `filed_date`, report period, source Fact ID,
  source filing ID, parser/package identity, and source locator;
- keep `QTD_3M`, `YTD_6M`, `YTD_9M`, `FY`, and `INSTANT` separate;
- distinguish reported, recast-reported, derived-recast, and unavailable
  output with explicit lineage;
- publish a run manifest containing input snapshot identities, mapping and
  selection-rule versions, output counts, validation results, and timestamp;
- build under a staging location and publish only after all required gates
  pass.  A failed run must not publish a partial analytical result;
- be deterministic for the same inputs and rule versions.  A new rule or
  mapping version creates a separate result; it does not overwrite prior
  analytical output.

The exact physical engine may be Parquet, a database, or a service, but its
records must preserve the logical grain and provenance in the existing
Analytical Data Model.  The provisional output root is
`data/processed/analytical/layer2/<run_version>/<cik>/`; it is an ignored
operational location, not a repository artifact.

## 4. Logical output set

The following names describe required logical datasets, not a claim that they
are already materialized:

| Logical dataset | Purpose | Minimum provenance |
| --- | --- | --- |
| `period_observation` | A Layer 1 Fact classified by actual Context period and comparative role; may include a governed Q4 derived candidate. | raw Fact/filing/context/unit/dimension IDs, period class/key, classification/derivation rule version |
| `period_observation_exclusion` | Explicit account of a source Fact that cannot safely form an observation. | source Fact/filing identity, exclusion reason, classification-rule version |
| `company_concept_map` | Raw Concept to company canonical Concept mapping. | source/raw and canonical IDs, relation, validity, method, confidence, evidence, version, review flag |
| `company_axis_map` | Raw Axis to company canonical Axis mapping. | same mapping provenance as above |
| `company_member_map` | Raw Member to company canonical Member mapping. | same mapping provenance as above, including parent/domain evidence where relevant |
| `structural_change` | Company-internal semantic or disclosure-structure change event. | event type, affected raw/canonical IDs, filing/period, evidence, mapping version |
| `analytical_fact` | A selected reported/recast value or an explicit unavailable result. | selected Fact ID (unless unavailable), view/as-of/basis/source type, mapping and selection-rule versions, evidence/reason |
| `recast_evidence` | Reviewed evidence binding a later directly reported/derived observation to a changed basis and target period. | later and prior Fact/filing IDs, basis, source document/locator, narrative/table/review evidence |
| `capability_inventory` | What the company can safely expose by statement, disclosure, dimension, period, and Metric-input eligibility. | discovery/mapping/selection versions, coverage/status, source role/concept/member/filing references |

The durable `analytical_fact.view` contract uses `AS_FILED` and
`CURRENT_COMPARABLE`.  Existing M7 selection code and the longitudinal
contract call the evidence-backed selection mechanism `LATEST_RECAST`.
`LATEST_RECAST` is therefore the governed implementation mechanism that feeds
the durable consumer view `CURRENT_COMPARABLE`; this plan preserves its
existing evidence and no-basis-mixing rules rather than creating a third view.

## 5. Milestones and acceptance criteria

### L2-M0 — Physical materialization contract and run boundary

**Objective.** Define the durable storage, run, version, and publication
contract for Layer 2 outputs before generating analytical data.

**Outputs.** A schema/manifest contract for the logical output set; partition
and run-version policy; staging-to-publish behavior; idempotency and failure
semantics.

**Required inputs/provenance.** Layer 1 snapshot manifest and filing identity;
period, mapping, recast, and selection-rule versions; input corpus run
identity.

**Acceptance criteria.**

- Every `analytical_fact` has a selected raw Fact ID or an explicit
  `UNAVAILABLE` reason; it never has an unexplained numeric value.
- Output manifest records all input snapshots and rule/mapping/evidence
  versions required to reproduce the result.
- Re-running identical inputs and versions yields identical keys, values, and
  counts; a changed rule/version is separately identifiable.
- Raw data remains untouched, and failed runs publish no partial output.
- The contract distinguishes operational generated data from Git-tracked
  source, documentation, and tests.

**Implemented boundary.** The executable L2-M0 contract is documented in
[`layer2-materialization.md`](layer2-materialization.md).  It provides the
typed run/input/version manifest and atomic publisher only; it makes no claim
that L2-M1 through L2-M6 datasets have been populated from the corpus yet.

### L2-M1 — Period observation materialization

**Objective.** Turn every eligible Layer 1 Fact into a period-aware
observation before it is considered for a time series.

**Outputs.** `period_observation`, including `QTD_3M`, `YTD_6M`, `YTD_9M`,
`FY`, `INSTANT`, `OTHER_DURATION`, comparative type, and controlled Q4
derived candidates.

**Required inputs/provenance.** Layer 1 Fact, Context, Unit, full dimension
signature, filing metadata, concept period type, and the period-rule version.

**Acceptance criteria.**

- No source Fact is silently discarded: it produces an observation or a
  recorded exclusion reason.
- QTD, YTD, FY, and Instant observations cannot share a series identity.
- A Q4 candidate exists only when the existing additive, unit, dimension,
  fiscal-calendar, structural, and recast compatibility conditions pass; it
  records both source Fact IDs, formula, and derivation-rule version.
- EPS, weighted-average shares, ratios, margins, averages, and other
  non-additive values are never Q4-derived by subtraction.
- AAPL, NVDA, and TSLA three-year inputs demonstrate complete classification
  coverage or explicit exclusions.

### L2-M2 — Company canonical mapping and structural-change QA

**Objective.** Connect same-company raw Concepts, Axes, and Members across
filings only when the continuity evidence supports it.

**Outputs.** `company_concept_map`, `company_axis_map`, `company_member_map`,
and `structural_change` with review state.

**Required inputs/provenance.** Ordered Layer 1 concepts, dimensions, roles,
PRE/CAL/DEF evidence, labels/documentation, Context/unit semantics, and
documented recast evidence where applicable.

**Acceptance criteria.**

- Only the contract relations `SAME`, `RENAMED`, `RECAST`, `SPLIT`, `MERGED`,
  and `UNCERTAIN` are used, with method, confidence, validity range, evidence,
  mapping version, continuity-break, and review information.
- String similarity or value continuity alone cannot confirm `SAME`.
- `UNCERTAIN`, unmapped, split, or merged items do not silently coalesce into
  an existing canonical series.
- Structural events include applicable new Concept/Axis/Member, member rename,
  segment recast, split, merge, role restructure, or unknown change.
- AAPL Product/Service and NVDA Segment/Geography mappings are explainable
  from raw IDs and retained evidence.

### L2-M3 — Annual and Current company series

**Objective.** Materialize company-internal canonical time-series candidates
without making a recast selection that lacks evidence.

**Outputs.** Annual (10-K/FY-focused) and Current (10-K plus 10-Q) series
keys/candidates feeding `analytical_fact` selection.

**Required inputs/provenance.** `period_observation`, company mappings and
their version/review state, full canonical dimension signature, unit
semantics, and source filing lineage.

**Acceptance criteria.**

- Series key includes CIK, company canonical Concept, full canonical
dimension key, unit semantics, actual period boundaries, period class, and
Annual/Current type.
- Annual views are 10-K/FY-oriented; Current views retain 10-K baseline plus
10-Q updates, and never mix period classes.
- A current member ordering can be produced by its latest available quarter
value descending, without changing the series data.
- AAPL, NVDA, and TSLA can reproduce three-year income-statement and observed
Revenue-breakdown candidates with source Fact, filing, and mapping-version
drill-down.

**Implemented boundary.** `CompanySeriesMaterializer` publishes the atomic
publisher-ready Annual/Current candidate datasets.  It does not select an
`analytical_fact`, infer a recast, calculate a Metric, or make an Excel view;
those remain L2-M4 and later consumer responsibilities.

### L2-M4 — As-of selection and recast/basis control

**Objective.** Select governed values without overwriting history or mixing
incompatible reporting bases.

**Outputs.** `recast_evidence` and selected `analytical_fact` rows for
`AS_FILED`, `CURRENT_COMPARABLE` (implemented through the existing
`LATEST_RECAST` selection mechanism), and `UNAVAILABLE` results.

**Required inputs/provenance.** Candidate Annual/Current observations, actual
`filed_date`, target period, basis version, reviewed filing/table/text
evidence, mapping version, and selection-rule version.

**Acceptance criteria.**

- `AS_FILED` selects only information available on or before `as_of_date`;
  later comparative observations never overwrite raw history.
- `CURRENT_COMPARABLE`, through `LATEST_RECAST`, selects a single
  evidence-backed basis for a comparable period family.  It cannot infer a
  recast from differing numbers, labels, or filing order alone.
- A `RECAST_REPORTED` value has bound Fact/filing/basis/evidence lineage; a
  `DERIVED_RECAST` value additionally has compatible input IDs and a rule
  version.
- If a selected basis has no compatible value for a target period, publish
  `UNAVAILABLE` with `PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS` (or another
  explicit reason), never a mixed-basis value.
- The NVIDIA FY2026 geography case in
  [nvidia-fy2026-geography-golden-case.md](nvidia-fy2026-geography-golden-case.md)
  is a mandatory generic golden test: original Q1/Q2 remain AS_FILED; only
  evidence-bound new-basis periods enter `CURRENT_COMPARABLE` through
  `LATEST_RECAST`; unsupported Q2/Q4 recast values remain unavailable; no
  annual value combines old Q1/Q2 with new Q3/Q4.

### L2-M5 — Capability inventory and governed discovery

**Objective.** Let a user discover what can be analysed for a company before
requesting a series or an Excel view.

**Outputs.** `capability_inventory` and a governed query/service boundary for
statement, disclosure, dimension, period, comparability, and metric-input
coverage.

**Required inputs/provenance.** Layer 1 statement/disclosure discovery,
roles, facts, dimensions, Layer 2 period/mapping/selection output, and
coverage rules.

**Acceptance criteria.**

- The inventory distinguishes **not reported**, **processing unavailable**,
  **mapping review required**, and **not comparable**; it never uses one
  generic missing status for all cases.
- It lists only observed/reportable company-specific Axis/Member structures;
  it does not invent a standard Product, Segment, or Geography template.
- Each result can drill to Concept, Axis/Member, role/disclosure, source Fact,
  and filing evidence.
- The seven-company corpus supplies coverage output; AAPL and NVDA validate
  the focused dimensional cases.
- Excel/API consumers may read the inventory but do not generate it.

**Implemented boundary.** `CapabilityInventoryMaterializer` produces only
observed company Concept and Axis/Member capabilities, while
`CapabilityInventoryQuery` exposes a read-only discovery boundary.  The
status and drill-down contract is defined in
[`capability-inventory.md`](capability-inventory.md).

### L2-M6 — Derived Metrics input handoff

**Objective.** Publish compatible input candidates and eligibility diagnostics
for the separate Derived Metrics plane.

**Outputs.** Metric-input candidate/compatibility records linked to
`analytical_fact`, plus `UNAVAILABLE` reasons where inputs are unsafe.

**Required inputs/provenance.** Selected Layer 2 values, period/basis/unit/full
dimension compatibility results, and Metric-definition identifiers where a
definition already exists.

**Acceptance criteria.**

- Candidate inputs retain selected Fact/filing, view, as-of date, basis,
  period, dimension signature, mapping version, and compatibility result.
- Gross Margin, Operating Margin, Revenue Growth, and controlled Q4 flow can
  be assessed for input eligibility; directly reported EPS and weighted-average
  shares remain direct observations rather than reverse-engineered inputs.
- Incompatible/missing inputs publish a reasoned unavailable result, not a
  calculation.
- L2-M6 neither calculates/stores a durable `derived_metric` value nor creates
  a Metric registry.  Those are follow-on Derived Metrics-plane work.

**Implemented boundary.** `MetricInputHandoffMaterializer` publishes
`metric_input_candidate` and `metric_input_compatibility` records from
selected `analytical_fact` rows.  It assesses Gross Margin, Operating Margin,
Revenue Growth, and controlled Q4 flow eligibility without calculating a
metric.  Its role, provenance, compatibility, direct EPS/share, and no-metric
output rules are defined in
[`metric-input-handoff.md`](metric-input-handoff.md).

## 6. Dependency and delivery order

```text
L2-M0
  -> L2-M1 -> L2-M2 -> L2-M3 -> L2-M4 -> L2-M5 -> L2-M6
```

Mapping investigation (L2-M2) and recast-evidence research (L2-M4) can begin
while adjacent work is in progress, but an output cannot be published as a
governed comparable series until its required mapping and basis checks have
passed.  Each milestone follows the implementation, frozen independent
verification, PR/CI, and merge procedure in
[delivery-workflow.md](delivery-workflow.md).

## 7. Relationship to existing M7 code

Existing M7 code establishes company mapping, Annual/Current candidate-series,
and governed selection logic.  It is not evidence that the durable Layer 2
datasets, run manifests, capability inventory, or Derived Metrics handoff in
this plan have been materialized.  This delivery sequence is therefore the
next work required to turn those contracts and in-memory logic into governed,
consumer-ready analytical data.
