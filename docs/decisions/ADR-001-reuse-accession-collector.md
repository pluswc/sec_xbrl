# ADR-001 — Reuse Existing Accession Collector

## Status
Accepted

## Decision
The existing SEC accession discovery process remains the upstream Filing Discovery component. The XBRL project consumes it via an `AccessionProvider` adapter contract.

## Rationale
- discovery logic already exists and is incremental/idempotent
- reimplementation adds risk without analytical value
- parsing and discovery have different failure/idempotency lifecycles
- an adapter keeps the XBRL system independent of the collector's storage format

## Consequences
- parsing maintains its own processing state
- downstream may enrich missing metadata from SEC filing index/package
- future collector changes require only adapter changes if the contract remains stable
