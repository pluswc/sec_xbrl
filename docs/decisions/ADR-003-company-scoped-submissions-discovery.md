# ADR-003 — Company-scoped submissions discovery

## Status

Accepted

## Decision

`sec_xbrl` discovers filings per configured company CIK using SEC submissions
metadata. It caches source responses immutably by content hash and keeps
mutable discovery state separately. `XbrlDataLoad` remains unmodified and is a
reference for SEC request and package-download behavior only.

## Drivers

- Company is the intended unit for controlled expansion.
- A date-range scan repeatedly processes unrelated companies.
- Raw SEC payloads, discovery state, package state, and parser state have
  distinct lifecycles.

## Consequences

- Historical submissions files referenced by the root submissions payload are
  included in discovery.
- M0 has no ZIP download, package resolution, Arelle, or Layer 1 scope.
- M1 owns accession package caching and parser state remains independent.
