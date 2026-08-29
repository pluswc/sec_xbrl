# C3-M4 — Governed Derived Metrics Publication

## Purpose

C3-M4 connects exactly one reader-attested C3-M1 `AS_FILED` Layer 2
publication to the pre-existing L2-M6 handoff, Derived Metrics M1 publication,
and M2 same-company series reader.  It is reusable for every company in the
C3 release; it is not an Excel implementation or a new metric engine.

```text
verified C3-M1 AS_FILED publication
  -> L2-M6 candidate + compatibility handoff
  -> existing versioned Metric Registry and M1 materializer
  -> atomic M1 metric release
  -> existing M2 manifest/hash-verified series admission
  -> C3 handoff + coverage companion
```

The pipeline accepts no manually constructed `VerifiedLayer2Publication`, no
mixed `CURRENT_COMPARABLE` facts, and no arbitrary row list.  The C3-M1
publication must have been read by `Layer2PublicationReader`, and its Layer 2
run and manifest identities are copied into the companion and M1 run.

## Metric scope

The controlled registry definitions are reused unchanged:

- `gross_margin@1.0.0`
- `operating_margin@1.0.0`
- `revenue_growth@1.0.0`

Only an M6 `ELIGIBLE` diagnostic with exact selected observation provenance
may result in a numeric record.  A missing Gross Profit, a missing declared
predecessor, mismatched dimensions/basis/unit, an absent value, or any other
failed M6/M1 gate becomes an immutable `UNAVAILABLE` record with a reason.
The pipeline never substitutes an operating expense or another nearby concept
for Gross Profit; this is particularly important for companies whose filings
do not report that line directly.

`q4_flow_eligibility@1.0.0` remains eligibility-only.  C3-M4 emits no Q4
metric value and does not make a display-order subtraction.  EPS and weighted
average shares remain direct observations and are not derived here.

## Publication and consumer use

M1's existing atomic publisher writes the authoritative metric release and
its content-hashed manifest.  The C3 companion atomically stores the exact
M6 candidates, compatibility diagnostics, and one coverage row per requested
CIK.  The companion reader verifies both its upstream C3-M1 identity and the
M1 manifest fingerprint/hash before returning any rows.  It also re-runs M2
admission, so a changed `derived_metric.jsonl` cannot be used.

Consumers use the existing `AnalyticalRepository` with the verified C3-M1
root and M1 metric root.  `discover_metrics`, `get_metric_series`, and
`trace_metric` therefore operate only on M2-admitted records; neither needs
manual metric rows or re-evaluates a formula.

## Known limits

This release is `AS_FILED` only.  It does not produce a current/comparable
metric without a separately reviewed C3-M3 evidence companion.  It does not
declare new quarterly semantics, infer a predecessor, add custom-company
metric roles, create a cross-company equivalence, or define Excel output.
