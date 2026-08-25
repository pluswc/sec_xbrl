# ADR-004 — Data planes and milestone release governance

## Status

Accepted

## Context

The project has established contracts for accession discovery, raw Layer 1,
longitudinal mapping, and cross-company mapping.  It also needs an explicit
boundary between immutable XBRL data, analysis-ready selections/calculations,
and display artifacts.  Without this boundary, an Excel builder can become a
second parser or can silently apply period, recast, and calculation policy.

An earlier repository-bootstrap milestone called “M0 — Accession adapter”
already exists in the historical roadmap and acceptance plan.  This ADR does
not rewrite that history.  It defines the current M0 governance and data
contract milestone that all subsequent work, including unmerged work, must
conform to.

## Decision

1. The pipeline has four separately owned data planes: Raw / As-filed Layer 1,
   Analytical, Derived Metrics, and Display.
2. Layer 1 is immutable and stores only filing-local, as-filed observations and
   their XBRL provenance.  It never selects a later value for an earlier period.
3. The Analytical plane selects or materializes analysis-ready reported and
   comparable observations with an explicit `as_of_date` and `basis_version`.
   It is additive to Layer 1 and never overwrites it.
4. The Derived Metrics plane records formula outputs separately from both
   reported and analytical observations, including formula and input lineage.
5. Excel and other display outputs consume only the Analytical and Derived
   Metrics plane.  They do not parse SEC ZIP/Inline XBRL files and do not
   create policy-bearing values.
6. A milestone branch starts from the latest passing `main`.  It may merge only
   after its acceptance checks, full regression, and before/after artifact
   impact comparison pass.  Intentional output changes require source and
   provenance evidence; unexpected changes are regressions.

## Consequences

- M1 Inline XBRL completeness remains an unmerged candidate.  It must align to
  this contract after M0 merges and demonstrate a successful, taxonomy-cache
  backed complete filing—not merely fail closed—before an M1 PR may merge.
- Previous feature branches are historical implementation candidates, not
  retroactively certified as compliant by this ADR.
- New physical schemas may be introduced incrementally, but must implement the
  logical identifiers, provenance, status, and quality gates in the associated
  contract before being exposed to analysis or display.

## References

- `docs/implementation/m0-data-contract.md`
- `docs/architecture/analytical-data-model.md`
- `docs/architecture/layer-model.md`
- `docs/implementation/layer1-schema.md`
- `docs/implementation/period-rules.md`
- `docs/implementation/layer2-longitudinal.md`
