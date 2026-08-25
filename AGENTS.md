# SEC XBRL Analysis — Agent Instructions

## Project goal
Build a provenance-first SEC XBRL analysis-data platform.  It preserves
as-filed meaning in Raw Layer 1, produces governed Analytical and Derived
Metrics planes, and supports:
1. Layer 1 — Raw / As-filed extraction and relationship reconstruction.
2. Layer 2 — Longitudinal canonicalization within the same company.
3. Layer 3 — Cross-company semantic comparison.

Excel, API, and dashboard views are consumers of governed Analytical and
Derived Metrics data.  They are not SEC parsers, recast-selection engines, or
business-calculation policy engines.

10-K is the annual baseline. 10-Q updates the current state. 10-K/A and 10-Q/A are preserved as amendments and never overwrite raw facts.

## Source of truth
Read these before implementing related code:
- `docs/implementation/delivery-workflow.md` — follow its all-milestone role separation, branch-freeze, independent verification, and PR/CI decision process.
- `docs/architecture/overview.md`
- `docs/architecture/layer-model.md`
- `docs/architecture/analytical-data-model.md` — durable logical data model
  between Raw extraction and consumer views
- `docs/implementation/accession-contract.md`
- `docs/implementation/layer1-schema.md`
- `docs/implementation/traversal-rules.md`
- `docs/implementation/period-rules.md`
- `docs/implementation/layer2-longitudinal.md`
- `docs/implementation/layer3-cross-company.md`
- `docs/implementation/acceptance-tests.md`

## Existing accession collector
Do NOT rewrite accession discovery unless a documented incompatibility is found.
Treat the existing collector as an upstream `Filing Discovery` component.
Consume its output through the contract in `docs/implementation/accession-contract.md`.
If the existing output schema differs, implement an adapter; do not couple XBRL parsing to the collector's internal implementation.

## Core invariants
- Raw SEC data is immutable.
- Preserve CIK, accession, form, filed date, report period, source filing and source file.
- Preserve QName, namespace URI, local name, taxonomy family/version, label, STANDARD/CUSTOM status.
- Preserve Context, period, unit and all Axis/Member dimensions.
- Role networks remain separated.
- Follow `targetRole` when present.
- DEF traversal has no fixed depth limit; stop by semantic termination/cycle control.
- CAL traversal is parent -> child only for decomposition.
- PRE is primarily contextual/validation evidence, not a free graph-expansion edge.
- Reported and derived values are distinct. Never overwrite reported values.
- Raw, Analytical, Derived Metrics, and Display plane boundaries follow
  `docs/architecture/analytical-data-model.md`; release and quality-gate policy
  follows `docs/implementation/m0-data-contract.md`.
- Absence of a disclosure in a 10-Q does not imply resolution.
- Canonical IDs are mappings on top of raw IDs; they never replace raw IDs.
- Cross-company analytical similarity is not accounting equivalence.

## Python conventions
- Python 3.12 target.
- Prefer Polars for tabular transformations.
- Arelle is the XBRL engine.
- Use type hints for public functions.
- Use pytest.
- Unit tests must not require network access.
- Integration tests may use explicit cached fixtures.
- Keep SEC download/cache logic separate from parser/traversal logic.

## Development workflow
Before coding:
1. Read and follow `docs/implementation/delivery-workflow.md`, then read the relevant docs.
2. State the milestone and acceptance criteria being implemented.
3. Identify assumptions and unresolved XBRL cases.
4. Implement the smallest vertical slice.
5. Run unit + relevant integration/golden tests.
6. Report changed files, test results and deviations from contracts.

## Git workflow
- `main` should remain passing.
- Use milestone branches such as `feature/m1-raw-extraction`.
- Prefer milestone-level PRs over very small PRs.
- Keep architecture/rule changes and the corresponding tests in the same PR.
- Never commit bulk SEC archives, generated Parquet stores, caches, secrets or `.env` files.
- When creating or updating a PR body through the GitHub CLI, use real newline characters
  (for example, a body file or shell ANSI-C quoting). Never pass literal `\n` sequences,
  because GitHub will render them as text instead of line breaks.
