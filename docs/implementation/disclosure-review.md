# Exact disclosure interpretation and reviewed Q4

## Outcome and boundaries

This slice makes a visible filing table usable when its inline member tag does
not express the displayed business identity. It publishes a separate reviewed
basis, retains every raw Fact/Context/Unit/dimension, and never edits the original
history publication. `AS_FILED` queries remain unchanged.

The generic producer is `sec_xbrl.longitudinal.disclosure_review`; administration
is `python -m sec_xbrl.disclosure_review`. There are no AMD cases in the engine.
The task's AMD proposal rows and explicitly authorized decisions are operational
data outside Git, not automatic source-code mappings.

## A and B are independent decisions

- A binds one source cell/Fact to the complete reviewed dimensions and basis.
  It binds filing, snapshot, concept, Context, Unit, dates, value, panel row and
  fiscal column, displayed table and inline locator. The original package ZIP
  must match the immutable Layer1 package hash; XHTML bytes must match the exact
  ZIP member. A copied/altered same-name document is insufficient.
  The selected raw Fact ID must also match the inline ID, source locator and
  one ordinal in the immutable manifest's source-corpus count. This verifies the
  actual Layer1 identity formula without guessing DOM/Arelle ordering or tuple
  positions; duplicate identical numeric/context facts cannot substitute IDs.
- B approves `FY - YTD_9M` for two exact A candidates. Both A approvals must be
  effective and usable. The producer checks company, concept, full reviewed
  dimensions, basis, year/start/end boundaries, numerator-only currency, monetary
  duration and exclusion of common non-additive categories. Amended inputs and
  transition-year periods remain review-required. A 52/53-week year is supported.
- Explicit source-quality issue IDs may be resolved by A; only the task's tagged
  mismatch issues are included in its proposal allowlist. Other BLOCK decisions
  remain effective in the persisted Analytical output and prevent Q4 production.
  RELEASE is not A/B approval. Resolving a tag issue does not erase its history.
- Duplicate approved input pairs fail closed, not first-wins. Direct Q4 has
  priority. A direct value without an interpretation requires review before a
  derived substitute. An approved direct value is compared using reported
  decimals; conflicts are visible on the selected cell and in the review queue.
  Unknown precision is not treated as a successful comparison.

The supported first slice retains the number of dimensions. Arbitrary axis
removal/addition, untagged document observations, inferred allocations, EPS
subtraction, and FY-minus-three-quarters fallback are not implemented.

## Administration

`prepare --parent PATH --locators PATH --rules PATH --package-root PATH
--quality-decisions PATH --destination NEW_PATH` creates immutable candidates
in Parquet, a human review CSV and explicit missing-input inventory. Locator
hints locate source cells; the engine independently rebinds them to Layer1.
Proposal rules carry ticker, source view, fiscal year, displayed label, complete
target dimensions, basis, corroboration and an explicit issue-resolution
allowlist. A rule is a proposal, never an approval. No name/value similarity is
an approval signal. Source evidence/ZIPs are cached by file identity per process;
raw lookup is indexed by company instead of reloading per Fact.

`publish --parent PATH --inventory PATH --decisions CSV --quality-decisions CSV
--review-as-of TIMESTAMP --destination NEW_PATH [--previous-publication PATH]`
creates an immutable reviewed publication. Decisions contain exact candidate ID,
action, previous decision ID, reviewer, reason and timezone-aware actual time.
APPROVE, REJECT, MORE_EVIDENCE and WITHDRAW are distinct. Timestamp ties,
predecessor conflicts, stale source/scope and candidate edits fail validation.
Updates must supply the previous publication; its candidates and decisions must
remain unchanged, with new decisions appended. Independent historical snapshots
can be produced with an earlier explicit cutoff. Neither prior successful output
nor the source is overwritten if a new run fails.

New companies use new configuration/locators and the same commands. New filings
produce new exact candidates and require decisions; single-filing approval is
not extrapolated to future filings. Existing sources/candidates can be reused
without renewed interpretation. Cross-accession automatic approval rules are a
future extension, not silently inferred in this slice. Missing input first
requires the existing history discovery/collection workflow, not fake numbers.

## Persisted consumer contract

`review_manifest.json` pins the immutable parent manifest, review cutoff and
integrity-checked Parquet datasets: `analytical`, `derived`, `candidates`,
`decisions`, `quality_decisions`, `review_queue`. This is a delta publication, not
a rewrite of the full corpus. Derived cells retain both exact A input IDs and
lineage, formula, A/B decision IDs, dates and original values. Quality-blocked
analytical cells expose null availability while preserving the source number in
lineage. Raw source cells selected into the reviewed basis are superseded only
in the reviewed view, not removed from the parent or AS_FILED.

The additional persisted `quarantine` dataset makes any opted-in A candidate
that is pending/rejected/withdrawn unavailable in the reviewed view. This applies
even without an old quality BLOCK, so a known interpretation problem cannot
fall back to a normal raw-tagged value when approval is withdrawn. It is scoped
to the exact candidate source Fact; other parent observations and AS_FILED are
unchanged. Historical review outputs lacking this dataset must be republished
before their reviewed view is consumed (their decision history remains readable).

`history.open_history_publication(path)` is the shared data entry point. The
reviewed reader composes persisted records without parsing or calculating.
Reports use that same reader and record both parent and review manifest hashes.
An earlier report review date cannot consume a later review publication; choose
an earlier immutable publication. Company reports use an inclusive Korean
calendar day, while review publication decisions use exact aware timestamps.

`render --publication PATH --ticker TICKER --destination FILE` renders the
persisted reviewed quarter series. The full company report can also register
the reviewed publication path. Independent dimensional lenses are labeled as
lenses, never fabricated hierarchy edges; parent and child revenues must not be
summed together. Different basis versions remain separate visible tables.

## Acceptance and delivery

Unit tests cover package binding, candidate/period integrity, independent A/B,
same-day history, withdrawal, stale edits, different units, non-additive values,
full dimensions, amendments, fiscal transition, 53 weeks, duplicate pairs,
direct Q4 confirmation/conflict and unrelated quality BLOCK propagation.
The explicit cached AMD run tests 78 source interpretations and 13 Q4 outputs;
the normal NVDA records are the unchanged regression control.

Delivery follows the frozen sole-writer / independent-verifier workflow. This
task freezes a local commit only: remote push/PR is excluded because prior remote
posting authorization was denied. Local completion is not main/remote release.
