# Acceptance Test Plan

## M0 — Accession adapter
- Company submissions payloads can be consumed without changing `XbrlDataLoad`.
- 10-K/10-Q(/A) accessions map to canonical `FilingRef`.
- malformed or unsupported records fail with explicit adapter errors.
- repeated reads are ordered by `(filed_date, accession)` and deterministic.
- raw submissions payloads are immutable; mutable discovery state is separate.

## M1 — Filing package + Arelle load
- Given a cached accession fixture, resolve required SEC filing files.
- Arelle loads without network access in golden tests.
- filing/accession provenance is preserved.

### M1A — Package cache
- ZIP and index-header artifacts are cached under the filing CIK/accession.
- every artifact has URL, byte size, and SHA-256 in an immutable manifest.
- a valid manifest is a network-free cache hit; partial or corrupt content fails
  validation and is never treated as a valid package.
- download is published atomically only after all artifacts validate.

### M1B — Legacy package adoption
- The read-only legacy `data/{index_date}/{accession}` layout is consumed only
  through its index metadata and files; no legacy source code or files change.
- Only packages with matching CIK/accession/form, both required artifacts, a
  valid ZIP, and calculated SHA-256 values are adopted.
- Adopted manifests identify `legacy_xbrl_data_load` as their source.
- Missing, corrupt, ambiguous, or mismatched packages produce explicit
  accession-level rejection codes and leave no published destination package.

## M2 — Layer 1 extraction
- Concepts preserve QName/namespace/local name and standard/custom status.
- Facts preserve context/unit/value/source.
- dimensions preserve explicit Axis/Member identity.
- typed dimensions are not silently dropped.
- materialized raw tables remain separate Parquet files for filing, concept,
  context, unit, fact, and dimension_fact.

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
