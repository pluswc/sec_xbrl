# Codex Prompt — M0 Accession Adapter

Read `AGENTS.md` and all files under `docs/architecture/` and `docs/implementation/` that are relevant to M0.

Goal: integrate the existing SEC accession collection process without rewriting it.

Do not implement XBRL parsing yet.

Tasks:
1. Inspect the existing accession collector code/output in this repository/workspace.
2. Summarize its current output schema, storage format, idempotency logic, and supported forms.
3. Compare it with `docs/implementation/accession-contract.md`.
4. Implement the smallest adapter that exposes `AccessionProvider.iter_filings()` and yields `FilingRef`.
5. Preserve the collector implementation. If a field is missing but can be enriched later from SEC filing metadata, do not modify the collector merely to add it.
6. Add unit tests based on a small real output sample.
7. Run tests and report:
   - files changed
   - contract fields mapped
   - fields deferred to downstream enrichment
   - assumptions
   - test results
   - any incompatibility that would truly require a collector change

Acceptance criteria:
- 10-K, 10-Q, 10-K/A, 10-Q/A can be represented when present.
- `cik`, `accession`, `form`, `filed_date` are preserved.
- repeated adapter reads are deterministic.
- no new SEC discovery request logic is introduced.
- existing collector internals are not modified unless an incompatibility is first documented.
