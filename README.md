# SEC XBRL Analysis

A layered SEC XBRL analytical pipeline for detailed financial statement decomposition, longitudinal analysis, and cross-company comparison.

## Scope
- 10-K = annual structural baseline
- 10-Q = current-quarter update
- 10-K/A, 10-Q/A = preserved amendments
- XBRL facts + Context + Dimension + Role + DEF/CAL/PRE relationships
- Critical Disclosure safety net
- Standard vs company-custom taxonomy distinction

## Layer model
1. **Layer 1 — Raw / As-filed**: preserve exact filing meaning and provenance.
2. **Layer 2 — Longitudinal Canonical**: connect equivalent company-specific concepts/members over time.
3. **Layer 3 — Cross-company Semantic**: map company-specific structures into comparable analytical categories with explicit confidence.

## Existing accession process
This project assumes accession discovery already exists. The downstream pipeline consumes that output via an adapter contract rather than reimplementing discovery. See `docs/implementation/accession-contract.md`.

## Initial milestones
- M0: repository/contracts/fixtures
- M1: Filing package resolver + Arelle loading
- M2: Layer 1 fact/concept/context/dimension extraction
- M3: Role + DEF/CAL/PRE relationship extraction
- M4: Anchor-driven traversal
- M5: Disclosure Safety Net
- M6: 10-K/10-Q period normalization and Current Series
- M7: Layer 2 longitudinal mappings
- M8: Layer 3 cross-company mappings
- M9: analytical views + future MCP facade

See `docs/roadmap.md`.
