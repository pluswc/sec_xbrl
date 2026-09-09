# U4 bounded completion and acceptance

Date: 2026-09-10. Status: **LOCAL_ACCEPTED / NOT MERGED**.

The user authorized the bounded U4 implementation, local commits, independent
verification, and use of the SEC identity stored in the repository-root `.env`.
The identity was loaded only at runtime and is not recorded in source or
artifacts. Product source is frozen at
`3236778e57872b8ea41e421534e4a9d9ea0d58ff`. This later documentation-only
commit records that result; it is not the product-test SHA.

## Accepted scope

U4 now runs the existing discovery, intake, history/review, prepared consumer,
U3 hierarchy/Axis companion, and renderer path from an explicit administrator
request. It snapshots settings and decision histories, records stage provenance,
prepares privately, verifies all outputs, and replaces the consumer pointer
last. Ordinary failures roll back administrator replacements; durable commit
intent and explicit recovery cover interrupted multi-file commits. Exact reviewed
parents can be resumed without broad decision rebinding.

Optional consumer fiscal bounds are distinct from collection scope. The accepted
NFLX run requests FY2023–FY2026 and contains only available 2026 Q1/Q2 columns;
it does not create Q3/Q4 or require a completed FY2026 annual baseline.

The prepared Analytical plane reuses the existing administrative quality
materializer. Exact accession/QName and optional Axis/Member scopes preserve raw
amount, reported/derived status, full dimensions, inputs, and lineage while
publishing separate analytical availability. BLOCK masks values before metrics
and importance, WARN keeps the value and reason, and RELEASE cannot clear a
different issue. A matched-decision ledger proves coverage; an unmatched active
WARN/BLOCK stops in `REVIEW_REQUIRED` before final publication.

## Actual input and evidence distinction

An initial broad intake reported all 14 filings as `REUSED` because the two 2026
snapshots existed elsewhere in Raw storage. It is not live-download evidence.
The lead then used the runtime-authorized SEC identity with empty package/index
storage and produced two `INGESTED` snapshots: NFLX accessions
`0001065280-26-000138` and `0001065280-26-000212`. The final orchestration ran
offline from exact verified copies of the old 12 sources plus those fresh two.
It contains **14 filings / 1,059 source tables**, source as-of 2026-07-17, and
review date 2026-09-10. A sealed writer-summary field `tables: 12` counts
history-manifest metadata entries; it is not the source-table count.

The lead reviewed the new filings as direct standard reported observations. No
new Q4, share, bridge, hierarchy, Axis, cross-accession, or other economic
approval was inferred. The separate quality run applies a synthetic concept-wide
BLOCK to Q2 `us-gaap:Revenues`; it is an administrative test, not an SEC filing
error. It preserves raw USD 12,559,938,000, blocks 11 prepared occurrences,
makes all four dependent metrics unavailable, and leaves 218 usable unrelated
dimensioned Q2 cells unchanged.

## Independent result

The separate read-only verifier reported:

- full pytest: **675 passed / 37 skipped**; Ruff: **PASS**;
- cached six-company hierarchy/Axis regression: **21 passed**;
- normal and quality publications: **16 Axes / 1,778 cells** each;
- browser/API checks against both same-SHA renderings, with zero page errors and
  zero HTTP(S) requests;
- all original U3 **1,483 artifact hashes**, five prior U4 seal hashes, old
  consumers, and prior milestones unchanged.

Operational evidence, relative to the repository root, is retained at:

- `work/u4_live_20260910/independent_final_3236778/VERIFICATION.md`;
- `work/u4_live_20260910/LEAD_ACCEPTANCE.json`;
- `work/u4_live_20260910/final_3236778/{normal,quality}/run/consumer-final`;
- each run's `rendered-frozen/index.html`, plus
  `work/u4_live_20260910/final_3236778/SHA256SUMS`.

Reproduction uses Python 3.12, `PYTHONPATH=src`, explicit admin/workspace,
`as_of=2026-07-17`, `review_as_of=2026-09-10`, FY2023–FY2026 and `offline=True`
for final orchestration. The actual declared inputs are:

- source roots `work/u4_live_20260910/old_baseline_sources` and
  `work/u4_live_20260910/fresh_new_quarters/intake`;
- submissions `work/u4_live_20260910/discovery/submissions`;
- package adapters from the old root to
  `data/raw/trailing_corpus_runs/20260827T051322Z/packages`, and from the fresh
  root to `work/u4_live_20260910/fresh_new_quarters/packages`;
- taxonomy `work/u4_live_20260910/taxonomy`.

These appear as `source_runs`, `submissions_roots`, consumer fiscal bounds, and
the `hierarchy.package_roots`/`hierarchy.taxonomy_cache` keys in each immutable
request and companion-plan snapshot. Run `python -m pytest -q` and
`python -m ruff check --no-cache .`. The actual cached regression is:
`python -m pytest tests/test_axis_timeseries_cached.py
tests/test_hierarchy_cached.py -q`, with `SEC_XBRL_AXIS_BUNDLE`,
`SEC_XBRL_AXIS_SOURCE_BUNDLE`, `SEC_XBRL_HIERARCHY_BUNDLE`, and
`SEC_XBRL_PROJECT_ROOT` set as specified by the
[U3 Axis delivery contract](u3-axis-timeseries-delivery.md). Live collection
additionally requires explicit target/as-of authorization and a runtime
`SEC_USER_AGENT`.

## Limits and historical record

This acceptance does not authorize automatic semantic bridges, economic or
review approval, arbitrary unattended filer operation, U5, remote push, PR, or
merge. New or changed meaning still enters the existing review/exception path.

The 2026-09-09 local-only record at
[U4 local verification and next steps](u4-local-verification-and-next-steps.md)
and earlier failed candidates remain accurate for their dates. Their missing
live evidence and quality-overlay gap were resolved by the later frozen source
and evidence above; they are preserved rather than rewritten as past successes.
