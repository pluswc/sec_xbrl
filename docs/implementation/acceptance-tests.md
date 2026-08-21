# Acceptance Test Plan

## M0 — Accession adapter
- Existing collector output can be consumed without changing collector internals.
- 10-K/10-Q(/A) accessions map to canonical `FilingRef`.
- malformed or unsupported records fail with explicit adapter errors.

## M1 — Filing package + Arelle load
- Given a cached accession fixture, resolve required SEC filing files.
- Arelle loads without network access in golden tests.
- filing/accession provenance is preserved.

## M2 — Layer 1 extraction
- Concepts preserve QName/namespace/local name and standard/custom status.
- Facts preserve context/unit/value/source.
- dimensions preserve explicit Axis/Member identity.
- typed dimensions are not silently dropped.

## M3 — relationships
- PRE/CAL/DEF remain separate.
- role URI/definition preserved.
- targetRole preserved and traversable.
- no role network is implicitly merged.

## M4 — Anchor traversal
- Major statements produce Anchor Concepts.
- direct dimensional facts are found before heuristic expansion.
- CAL only decomposes parent -> child.
- DEF reaches member leaves without an arbitrary depth cutoff.

## M5 — Disclosure Safety Net
- P0 disclosure can be discovered even without Anchor connection.
- role title alone is not the sole signal.
- text/table/detail links retain provenance.

## M6 — 10-Q period logic
- QTD_3M and YTD_6M/YTD_9M are distinct.
- Cash Flow YTD values are not mislabeled quarter-alone.
- derived Q4 stores source IDs and never overwrites reported FY/YTD.
- missing disclosure != resolved.

## M7 — Layer 2
- same-company mappings are additive to Raw.
- namespace changes do not break a well-supported canonical series.
- segment recast can create a new mapping/version rather than corrupt old history.

## M8 — Layer 3
- analytical grouping preserves raw/company IDs.
- analytical similarity is distinguished from equivalence.
- low-confidence mapping is surfaced, not hidden.

## Golden fixtures
Start with one company that has rich product/geography/segment disclosures, then add:
- one company with substantial custom taxonomy
- one with 52/53-week fiscal calendar
- one with segment recast
- one financial institution for industry overlay

Fixtures should be minimal cached filing packages; bulk archives do not belong in Git.
