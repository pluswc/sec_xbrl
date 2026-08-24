# AMD · MSFT · META Filing Pilot Charter

## Purpose and fixed scope

This pilot turns the existing M1--M9 capabilities into a reviewable, reproducible
evidence set.  It is a product-validation exercise, not a rewrite of filing
discovery or a claim that all three companies are accounting-equivalent.

The selection is frozen **as of 2026-08-24**.  The six candidate filings are
metadata only in
[`amd-msft-meta-filing-manifest.json`](amd-msft-meta-filing-manifest.json): one
annual 10-K baseline and one subsequent 10-Q current update per company.
`ANNUAL_BASELINE` and `CURRENT_UPDATE` are pilot selection roles, not an
override of fact-level context and period classification.

| Company | Why it is in the pilot | 10-K baseline | 10-Q update |
| --- | --- | --- | --- |
| AMD | Semiconductor business with product, operating-segment, and geography evidence; a 52/53-week fiscal calendar check. | 2025-12-27 | 2026-03-28 |
| MSFT | `Intelligent Cloud` tests the boundary between a reportable segment and a narrower analytical cloud category. | 2025-06-30 | 2026-03-31 |
| META | Advertising-led business plus Family of Apps / Reality Labs tests segment and revenue-breakdown evidence. | 2025-12-31 | 2026-03-31 |

The manifest is the reproducibility entry point.  Its CIK, accession, form,
filed/report dates, selection role, and SEC archive URL must be carried into
the package and Layer 1 provenance.  It deliberately contains no SEC package,
hash, downloaded filing, generated Parquet, or analytical output.

## P0 — discussion-ready charter and manifest

**Evidence/output**

- This charter, the six-record metadata manifest, and network-free validation
  tests.
- A shared set of decision questions for P1--P3 and a Git boundary that keeps
  raw SEC data outside the repository.

**Decision questions**

1. Do the six filings expose enough raw evidence to make company-specific
   revenue, segment, geography/product-service, and P0/P1 disclosure results
   useful to review?
2. Which of the planned peer categories are analytical similarity only, and
   which cannot be supported from as-filed evidence?
3. Is one 10-K plus one 10-Q per company sufficient for the first decision,
   or should a later phase add history/recasts rather than broaden P0?

**Acceptance criteria**

- Exactly six records: AMD, MSFT, META each have one 10-K
  `ANNUAL_BASELINE` and one 10-Q `CURRENT_UPDATE`.
- Each record has a zero-padded CIK, hyphenated accession, required dates,
  selection role, and a matching official SEC archive URL.
- Validation is network-free and does not depend on a downloaded SEC filing.
- The P1--P3 evidence, decisions, non-goals, and Git rules below are explicit.

**Non-goals**

- Downloading, committing, or parsing a package in P0.
- Changing filing discovery, the CI workflow, source contracts, or mappings.
- Declaring the selected companies comparable before evidence is reviewed.

**Git rules**

- P0 changes live on `feature/pilot-amd-msft-meta`; the frozen commit is pushed
  before independent verification.
- Commit only the charter, metadata manifest, tests, implementation, and small
  human-reviewable summaries.  Never commit ZIP/HTML/XBRL caches, package
  manifests containing downloaded artifact hashes, Parquet/DuckDB stores,
  generated dossiers, secrets, or `.env` files.
- Keep raw/cache material under ignored `data/raw/` or `data/cache/`; record its
  accession and content hash only in an approved, small review summary when
  needed.  Do not force-add ignored data.
- No CI YAML change is in scope.  P0 uses the existing CI-equivalent commands
  `uv run ruff check .` and `uv run pytest -q`.

## P1 — six cached, validated packages and as-filed QA matrix

**Evidence/output**

- Six immutable local packages resolved from the manifest, each with the M1
  package/index manifests, SEC URLs, artifact byte sizes and SHA-256 hashes.
- Offline Arelle load results and an as-filed QA matrix: identity, selected
  entry document, package validation, Arelle result, taxonomy/relationship
  presence, and any accession-level failure code.
- The QA matrix is a small committed summary; packages and generated stores
  remain ignored.

**Decision questions**

1. Are all six packages valid and offline-loadable, with no resolver ambiguity?
2. Which accession, if any, needs a documented exception rather than a parser
   workaround?
3. Are the facts, contexts, dimensions, PRE/CAL/DEF roles, and source
   provenance sufficiently present to proceed to extraction?

**Acceptance criteria**

- Six of six packages validate under the package-cache contract, load without
  network access, and preserve manifest identity.
- The QA matrix has one row per accession and evidence for each stated result.
- Any failure is retained as an accession-level result with its contract stage;
  no guessed entry point or altered raw source is accepted.

**Non-goals**

- Bulk EDGAR ingestion, amendments, automatic repairs of filings, or a
  conclusion about accounting comparability.

**Git rules**

- Commit only code/tests and the concise QA matrix.  Keep every downloaded ZIP,
  header, `index.json`, extracted source, Arelle cache, and generated Parquet
  ignored.  Freeze/push before independent verification.

## P2 — three provenance-cited company dossiers

**Evidence/output**

- One dossier per company, based only on the paired P1 packages, with links to
  accession, source document/locator, raw concept/QName, context/period, unit,
  dimensions, role and relationship evidence.
- As-filed statement QA; revenue and available segment/product/geography
  breakdowns; P0/P1 disclosure inventory; and a Layer 2 current-series view
  that keeps `FY`, `QTD_3M`, `YTD_*`, and `INSTANT` separate.
- Mapping candidates and uncertainty log; no raw identity is overwritten.

**Decision questions**

1. What can each company dossier support as reported fact, direct dimensional
   evidence, DEF/CAL/PRE structure, and critical-disclosure evidence?
2. Which company mappings have enough evidence for `SAME`, `RENAMED`, or
   `RECAST`, and which require review?
3. Does the AMD fiscal calendar and each 10-Q context classification behave as
   expected without a calendar-quarter assumption?

**Acceptance criteria**

- Each conclusion is traceable to the stated as-filed evidence and accession.
- Reported and derived values remain distinct; no derived Q4 is created unless
  the period contract permits it.
- A missing 10-Q disclosure is labelled `NOT_REPORTED_THIS_QUARTER`, never
  silently resolved.  Uncertain mappings stay visible and require review.

**Non-goals**

- Investment advice, earnings forecasts, or an assertion that a segment is a
  standalone product metric.

**Git rules**

- Commit compact human-reviewable dossier narratives and mapping evidence only
  after redaction/review; never commit generated table stores or cached sources.
  A material interpretation change requires a new frozen commit and
  independent verification.

## P3 — peer comparison, scope warnings, and backlog

**Evidence/output**

- A peer panel that retains source raw ID, company canonical ID, analytical ID,
  mapping relation/confidence/version, accession, and source period for every
  row.
- Explicit scope warnings: MSFT `Intelligent Cloud` is broader than cloud
  services; AMD, MSFT, and META revenue/segment breakouts may differ in
  business scope, unit of account, and disclosure level.
- A prioritized engineering/mapping backlog with evidence, impact, owner lane,
  and decision needed.  Priorities separate correctness blockers from useful
  later coverage.

**Decision questions**

1. Which peer comparisons are `EQUIVALENT`, `SUBCATEGORY_OF`,
   `ANALYTICALLY_SIMILAR`, `NOT_COMPARABLE`, or `UNRESOLVED`?
2. Are the remaining gaps better resolved by mapping review, another filing,
   parser/traversal work, or a deliberately unavailable metric?
3. Is the panel valuable enough to expand history or the company universe?

**Acceptance criteria**

- Every comparison exposes its provenance and mapping relation; low-confidence
  and unresolved rows remain visible.
- The panel never promotes analytical similarity to accounting equivalence.
- The backlog is prioritized by decision impact and names its evidence gap.

**Non-goals**

- Ranking companies, concealing missing mappings, or adding an inferred cloud
  revenue measure where the filing does not report one.

**Git rules**

- Commit the small comparison narrative, reviewed mapping specifications, and
  backlog.  Keep generated panels/stores and all raw SEC material ignored.
  Freeze/push each review candidate before independent verification.

## Assumptions and unresolved cases

- The manifest’s SEC directory URL is the retrieval authority; P1 verifies the
  package contents, primary document selection, XBRL flags, and hashes rather
  than treating P0 metadata as a cache manifest.
- Microsoft’s 10-K filed date is recorded as 2025-07-30; P1 rechecks all
  selected metadata against the official index/header when constructing the
  immutable cache.
- A one-year baseline/current-update pair is adequate to expose workflow and
  mapping risks, but not to prove long-run continuity, recast history, or
  amendment behavior.
- The pilot does not pre-commit a common revenue, AI, cloud, segment, or
  geography taxonomy.  Those are P2/P3 evidence-led decisions.
