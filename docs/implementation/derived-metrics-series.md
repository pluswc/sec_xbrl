# Derived Metrics M2 — Same-Company Series and Governed Read Boundary

## Boundary

M2 turns immutable M1 `derived_metric` records into durable, same-company
metric-series **candidates** and selects them through a read-only query
boundary. It never runs a metric formula, rebinds an input, edits a M1 record,
or infers a metric from an XBRL label or concept.

M2 admits data only by loading an M1 publication directory containing its
`derived_metric.jsonl` and adjacent run manifest. Before candidates are made,
it verifies the M1 run declaration fingerprint and the JSONL row count/content
hash against the manifest. A candidate retains `run_version`, run fingerprint,
Layer 2 run fingerprint, registry contract/version, the full M1 record, input
lineage, and source lineage. A bare row list, invented manifest, missing row,
or altered/extra JSONL row is rejected rather than presented as an untraceable
metric series.

## Candidate grain

The candidate identity includes:

- CIK;
- Metric definition ID **and version**;
- full company canonical dimension key;
- input unit and metric-output semantics;
- series type, period class, and period key;
- governed view (`AS_FILED` or `CURRENT_COMPARABLE`); and
- explicit basis version, metric revision/as-of date, and immutable
  `derived_metric_id`.

Thus QTD, YTD, FY, and INSTANT cannot coalesce; neither can as-filed versus
comparable records, basis versions, or definition versions. `metric_series_key`
is a stable ID of that full identity. `metric_series_family_key` removes only
the target period, basis, revision and as-of fields for governed selection.
It still retains CIK, definition version, full dimensions, units, period class,
series type, and view.

## As-of selection

The caller must state both `view` and `as_of_date`.

- `AS_FILED` selects the earliest visible immutable M1 revision for each exact
  period in the as-filed family. Later calculation/revision output does not
  overwrite it.
- `CURRENT_COMPARABLE` accepts only M1 records that were materialized from the
  governed L2 `CURRENT_COMPARABLE` view. It selects one latest available
  explicit basis for the family using a stable tuple of revision as-of date,
  evaluation timestamp, calculation timestamp, and immutable metric ID. Every
  `RECAST_REPORTED` input retains a recast-evidence ID; every `DERIVED_RECAST`
  input retains source Facts and its derivation-rule version. If that basis
  lacks a target period, it emits
  `UNAVAILABLE` with `PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS`; it never fills
  from another basis.
- An unavailable M1 record remains unavailable with its reason. If no
  available comparable basis exists, every observed target period is returned
  unavailable with `NO_AVAILABLE_METRIC_IN_COMPARABLE_BASIS`.

The M1 record's `as_of_date` is the visibility ceiling: it represents the
governed Layer 2 selection date of the metric inputs. Calculation time is
retained as audit metadata but is not a substitute filing/as-of date.

## Read-only consumer interface

`AnalyticalRepository.get_metric_series()` accepts a company selector, metric
ID or definition ID, explicit `view`, explicit `as_of_date`, and optional
period class/range/definition version filters. It consumes already-built M2
candidates loaded from verified M1 publication roots only. It cannot calculate
a metric, create an input handoff, silently pick a basis, or modify a source
record.

This is a same-company boundary only. Cross-company metric comparability,
Excel presentation, metric capability inventory, and new formula definitions
remain separate follow-on work.
