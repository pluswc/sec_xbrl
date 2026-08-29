# Derived Metrics M1 — Materialization Contract

## Boundary

M1 materializes an immutable `derived_metric` record **only** after two
separate controls have passed:

1. an active M0 `MetricDefinition` validates an `ELIGIBLE` L2-M6 candidate
   and compatibility record; and
2. every named candidate has one selected Layer 2 observation value whose
   analytical Fact ID and full governed provenance equal that candidate.

The second input is a value payload for an already-selected `analytical_fact`.
It is not a new semantic lookup: M1 does not inspect a QName, label, display
row, or raw Fact to decide what Revenue, Gross Profit, or another role means.
That decision remains M6's governed handoff.

## Initial numerical definitions

| Definition | Formula | Output |
| --- | --- | --- |
| `gross_margin@1.0.0` | Gross Profit / Revenue | percent (`40`, not `0.40`) |
| `operating_margin@1.0.0` | Operating Income / Revenue | percent |
| `revenue_growth@1.0.0` | Current Revenue / declared Prior Revenue − 1 | percent |

Calculations use finite `Decimal` values.  Both ratios and growth rates are
stored as percentage points (multiplied by 100), which is part of this formula
version's output convention.  Zero denominators, absent values, duplicate
bindings, mismatched provenance, or non-eligible diagnostics fail closed.  M1
publishes an immutable `UNAVAILABLE` record with the diagnostic, input lineage
when candidates were considered, and an explicit reason, but no numeric value.
When M6 found **no compatible input candidates**, the record deliberately has
no source input values or IDs and declares
`input_lineage_status=NO_COMPATIBLE_INPUTS`. It retains the definition/version,
full governed scope, M6 compatibility ID/status, required roles, diagnostic
reason, and publication provenance; it never fabricates raw-Fact lineage.
This status is admitted only when the upstream M6 diagnostic is
`compatibility_status=UNAVAILABLE` with the approved
`REQUIRED_INPUT_NOT_AVAILABLE` reason. An empty `ELIGIBLE` diagnostic is an
invalid handoff, not an M1 unavailable default.
Available records declare `input_lineage_status=COMPLETE` and preserve the
exact M6 candidate IDs and assessment role bindings used in the calculation.
Available and unavailable records
are both marked `source_type=DERIVED_METRIC`; an available record has a
`calculated_at` timestamp while an unavailable evaluation retains
`evaluated_at` and has `calculated_at=null`.

`q4_flow_eligibility@1.0.0` remains `ELIGIBILITY_ONLY` in the M0 registry, so
M1 does not publish a Q4 metric value from it.  EPS and weighted-average shares
remain direct observations and are not calculated or reverse engineered here.

## Record lineage

Every available output includes its definition and formula versions, chosen
compatibility diagnostic, company/view/as-of/basis/period/dimension/unit/map
scope, ordered input candidate and analytical Fact IDs, selected raw Fact IDs,
source Fact IDs, source filing, source type, and the exact Decimal operands.
Raw and Layer 2 records are never updated by this process.

## Publication

The provisional ignored operational layout is:

```text
data/processed/analytical/derived_metrics/<run_version>/
  derived_metrics_run_manifest.json
  derived_metric.jsonl
```

`DerivedMetricsRun` declares the consumed Layer 2 run fingerprint and the
registry contract/version.  The publisher hashes that declaration and the
canonical output.  It stages, validates, and atomically renames the directory.
An identical run reuses its output; changed content or inputs under the same
run version fail closed.

M1 creates no consumer API, Excel formula, cross-company comparison, or
same-company metric series selection.  Those remain later milestones.
