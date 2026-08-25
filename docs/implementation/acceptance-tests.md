# Acceptance Test Plan

## Historical M0 — Accession adapter
- Company submissions payloads can be consumed without changing `XbrlDataLoad`.
- 10-K/10-Q(/A) accessions map to canonical `FilingRef`.
- malformed or unsupported records fail with explicit adapter errors.
- repeated reads are ordered by `(filed_date, accession)` and deterministic.
- raw submissions payloads are immutable; mutable discovery state is separate.

## M0 — Data-plane contract and release governance (current)

The durable model is `../architecture/analytical-data-model.md` and the
executable/inspection checklist is maintained in
`m0-data-contract.md#8-m0-acceptance-checklist`.  PR reviewers must confirm:

- Raw, Analytical, Derived Metrics, and Display responsibilities are distinct;
  Display never parses a filing package or creates policy-bearing values.
- the analytical data model defines logical grain/keys, source selection,
  derived-metric lineage, full dimensions, consumer contract, and the direct-ZIP
  prototype migration boundary.
- Reported Fact, Dimensional Fact, Analytical Fact, and Derived Metric grain,
  identifiers, provenance, and full dimension signature are testable.
- source-type, `as_of_date`, `basis_version`, raw-immutability, and
  `UNAVAILABLE` semantics are specified.
- all data-quality gates define expected/actual checks and publish/failure
  behavior.
- the PR policy requires frozen independent verification, full regression, and
  evidence-backed intentional output changes.
- unmerged M1 Inline XBRL work is not accepted until it aligns to M0 and proves
  a complete network-free success case using a cached taxonomy package or a
  deterministic self-contained contract fixture.

## M1 — Filing package + Arelle load
- Given a cached accession fixture, resolve required SEC filing files.
- Arelle loads without network access in golden tests.
- filing/accession provenance is preserved.
- After M0, an Inline XBRL completeness change additionally proves at least one
  successful network-free extraction with complete reported **and**
  dimensional facts, using a cached taxonomy package or a deterministic
  self-contained contract fixture. A fail-closed validation result alone is
  not M1 success.
- The filing-level expected/actual fact corpus reconciliation, taxonomy and
  transformation resolution, and same-filing atomic fact/relationship snapshot
  gates pass before the snapshot is published as `SUCCESS`.

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
- Every non-tuple Fact from the accepted `model.facts` corpus is materialized
  once, with lossless Fact → Concept/Context/Unit linkage inside one immutable
  filing snapshot.
- Concepts preserve QName/namespace/local name, standard/custom status, and
  resolved taxonomy label/documentation for both Fact concepts and Context
  Axis/Member concepts.
- Facts preserve numeric/text/nil lexical value distinctions, decimals,
  precision, source locator, and Raw null period/comparative classifications.
- dimensions preserve explicit Axis/Member identity and typed-member payload.
- An unresolved Context Axis or explicit Member fails the raw-corpus
  completeness gate and publishes no snapshot; typed members remain preserved
  as their XML payload without requiring a taxonomy Member Concept.
- typed dimensions are not silently dropped.
- materialized raw tables remain separate Parquet files for filing, concept,
  context, unit, fact, and dimension_fact.

## M3 — relationships
- PRE/CAL/DEF remain separate.
- role URI/definition preserved.
- base-set link/arc QName provenance remains separate, so identical endpoint
  arcs from different extended-link networks are not implicitly merged.
- Arelle wildcard base-set aliases do not duplicate a fully specified network;
  a recognized network without a fully specified link/arc QName fails closed.
- targetRole and arc attributes (order, weight, preferred label, usable,
  closed, context element) are preserved and traversable.
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
