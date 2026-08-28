# Derived Metrics M0 — Definition Registry

## Boundary

This milestone creates the governed, versioned **definition registry** for the
Derived Metrics plane.  It does **not** calculate a metric, select a raw Fact,
infer a role from a label, or publish `derived_metric` values.

The only numerical-input boundary is L2-M6's `metric_input_candidate` and
`metric_input_compatibility`.  Raw concepts, labels, and display fields are
not registry inputs.  Therefore a definition never claims that a company
extension is Revenue, Gross Profit, or another role merely from its name.

## Contract

Each `MetricDefinition` is immutable in use and has:

- `metric_id@version`, status (`DRAFT`, `ACTIVE`, `DEPRECATED`), source,
  reviewer, review date, and change note;
- category: `DERIVED` or `DIRECT_OBSERVATION`;
- ordered L2-M6 input roles, period/basis/dimension compatibility policies,
  output unit semantics and output semantics;
- declarative formula metadata for a derived definition only.  Its expression
  is audit metadata, never executable code;
- metric dependencies, validated as an acyclic graph; and
- a direct-observation policy.  EPS and weighted-average shares cannot have a
  formula and accept only selected `REPORTED` or evidence-bound
  `RECAST_REPORTED` raw-Fact observations.

Definition IDs are versioned rather than overwritten.  There can be one active
version for each metric ID; older versions stay `DEPRECATED` so prior materialized
values can keep their original definition provenance.

`MetricRegistry.validate_handoff()` accepts only an eligible L2-M6 compatibility
record plus the corresponding candidate records for a derived definition.
`validate_direct_observation()` is the explicit candidate-only path for EPS and
shares, because L2-M6 deliberately does not manufacture a ratio diagnostic for
them.  Both paths reject value-bearing
fields (`value`, `metric_value`, `calculated_value`, `formula_result`, and
`derived_metric_id`), raw-concept/label inference, duplicate candidates,
wrong input-role order, mismatched definition IDs, non-eligible diagnostics,
and incompatible direct-observation sources.  Validation is deliberately not
calculation and returns no numeric result.

## Controlled initial definitions

| Definition ID | Category | Required L2-M6 roles | Output |
| --- | --- | --- | --- |
| `gross_margin@1.0.0` | Derived | `GROSS_PROFIT`, `REVENUE` | percent ratio |
| `operating_margin@1.0.0` | Derived | `OPERATING_INCOME`, `REVENUE` | percent ratio |
| `revenue_growth@1.0.0` | Derived | `CURRENT_REVENUE`, `PRIOR_REVENUE` | percent growth rate |
| `q4_flow_eligibility@1.0.0` | Derived | `CONTROLLED_Q4_FLOW` | eligibility only; no value |
| `eps@1.0.0` | Direct observation | `EPS` | per-share reported observation |
| `weighted_average_shares@1.0.0` | Direct observation | `WEIGHTED_AVERAGE_SHARES` | reported shares observation |

This is a small controlled seed, not an assertion that every company exposes
each role.  The L2 capability inventory and M6 diagnostics determine what is
actually available for a company and period.

## Follow-on milestones

1. **DM-M1 — Derived metric materialization.** Consume one definition and
   eligible M6 handoff plus selected L2 observation values, calculate an
   immutable `derived_metric` row with formula/input lineage.  See
   [the M1 materialization contract](derived-metrics-materialization.md).
2. **DM-M2 — Series and as-of metric selection.** Build same-company metric
   series from immutable M1 records without mixing periods, bases, or
   definition versions; provide the governed read-only query boundary.
3. **DM-M3 — Definition governance and approved mappings.** Add reviewed
   company/standard role assignments and definition lifecycle review without
   changing L1 raw identity.
4. **DM-M4 — Metric capability.** Expose available metric definitions and
   diagnostics to Excel/API; consumers remain read-only.
5. **DM-M5 — Cross-company metric comparability.** Apply Layer 3 mappings and
   explicitly distinguish comparable, similar, and unavailable peer metrics.

## M0 acceptance tests

- Every seed has identity/version/status, audit metadata, role contract,
  compatibility policy, output semantics, and the appropriate formula/direct
  policy.
- Duplicate versions, multiple active versions, missing governance, unknown or
  cyclic dependencies, and invalid direct/derived forms are rejected.
- Registry validation consumes only L2-M6 candidate/compatibility contracts;
  it rejects calculated values, raw inference, non-eligible diagnostics, and
  wrong role/schema combinations.
- EPS and weighted-average shares reject derived/no-lineage candidates.
- No `derived_metric` output or formula execution exists in this milestone.
