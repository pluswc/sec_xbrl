# ADR-002 — Raw First, Canonicalization as Mapping Layers

## Status
Accepted

## Decision
Layer 1 raw identifiers are immutable. Layer 2/3 canonical identities are separate versioned mappings.

## Rationale
Custom XBRL concepts/members can change meaning and taxonomy namespace over time; peer analytical categories can also evolve. Replacing raw identity would make corrections impossible and damage auditability.
