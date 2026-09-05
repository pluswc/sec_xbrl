# ADR-005 — Broad Mechanical Period Candidates, Evidence-Based Consumer Selection

## Status

Accepted for the Layer 2 mechanical-Q4 companion.

## Context

Companies disclose duration Facts beyond a fixed set of standard income-statement
Concepts.  These include dimensional products, regions, segments and company
extension Concepts.  Requiring every such Fact to be added to a semantic
allowlist before it can be made available as a quarter candidate would make the
analysis corpus incomplete and require company-by-company policy maintenance.

The prior, narrow M7 branch (`feature/l2-m7-dimensional-q4`) explored a
reviewed standard-Concept allowlist plus a primary Presentation (PRE) gate.
That approach is deliberately **not** part of the M8 mainline change in PR
#61: its commits were removed before the PR was updated.  It remains historical
experimental work, not a prerequisite or a consumer-selection rule.

## Decision

1. Layer 2 first produces broad **mechanical period candidates**.  It may
   derive `QTD_3M = FY - YTD_9M` only for a unique, exact-scope input pair:
   numeric reported duration Facts, a numerator-only Unit, same company,
   canonical Concept, full Dimension signature, basis, Unit semantics and
   actual fiscal boundaries.
2. The mechanical producer has no standard QName allowlist and no PRE-role
   admission gate.  Custom Concepts and Axis/Member Facts are eligible when
   they satisfy the structural conditions.
3. A mechanical candidate is **not** a semantic approval, a metric input, or a
   statement value.  It carries provenance and review flags so a later consumer
   can decide whether it fits its purpose.
4. Consumer selection builds an evidence-based exploration group, rather than
   applying a Q4 producer allowlist.  Its contract is defined in
   `docs/implementation/consumer-exploration-contract.md`.
5. Excel is a consumer only.  It never derives Q4; it displays a reported or
   Layer 2-derived value and its status/lineage as supplied.

## Deferred alternative: 3M aggregation fallback

The possible fallback `Q4 = FY - (Q1_3M + Q2_3M + Q3_3M)` is not implemented.
A full NVDA corpus check found **zero** additional eligible scopes beyond the
direct `FY - YTD_9M` method.  It may be reconsidered only after a future-company
corpus demonstrates a real need, with its own scope, duplicate-input,
comparability and provenance acceptance tests.  It must not be added merely as
a theoretical fallback.

## Consequences

- The corpus retains more company-specific analysis material without claiming
  that all candidates are economically additive or comparable.
- Consumers must explicitly select or exclude candidates using their intended
  analytical purpose and retained evidence.
- A future reviewed/semantic policy may use the same candidates as inputs, but
  it is a separate policy and cannot overwrite mechanical results or Raw Facts.

## References

- `docs/implementation/period-rules.md`
- `docs/implementation/layer2-longitudinal.md`
- `docs/implementation/consumer-exploration-contract.md`
- `docs/decisions/ADR-004-data-planes-and-release-governance.md`
