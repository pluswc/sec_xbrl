# Codex Prompt — M0 Accession Adapter

Read `AGENTS.md` and all files under `docs/architecture/` and `docs/implementation/` that are relevant to M0.

Goal: implement the current project's company-scoped SEC submissions discovery
without modifying `XbrlDataLoad`. The prior project is reference-only for SEC
request/download behavior.

Do not implement XBRL parsing yet.

Tasks:
1. Define company targets and canonicalize CIKs to 10 digits.
2. Cache each SEC submissions response immutably by content hash; keep mutable
   discovery state separate.
3. Read current and referenced historical submissions files, then normalize them
   through `AccessionProvider.iter_filings()` into `FilingRef`.
4. Preserve directly supplied optional metadata; leave absent metadata `None`.
5. Add unit tests using compact local SEC submissions samples.
6. Run tests and report:
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
- no daily-index discovery, ZIP download, package resolution, Arelle load, or
  Layer 1 parsing is introduced.
- `XbrlDataLoad` is not modified.
- no ZIP download, package resolution, Arelle load, or Layer 1 parsing is added.
