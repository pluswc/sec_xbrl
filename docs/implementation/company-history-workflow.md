# Company history intake and persisted fiscal panels

## Completion contract

**Feature complete** means arbitrary resolved tickers plus an explicit report-date
window (or recent annual-baseline count) can pass discovery, resumable Layer 1
intake, governed publication, and an offline persisted-panel query. Tests of
this code do not prove that a particular requested corpus was collected.

**Run complete** means every accession in that run's immutable plan passed the
Layer 1 gates, every operational publication agrees on those raw inputs, and
the persisted fiscal panels were verified and reloaded. Failed downloads or
parses cannot become `MISSING_HISTORY`, and incomplete intake exits nonzero.
Neither status means every potential metric has a reported quarterly value.

## Reusable interface

Use Python 3.12 with this source revision on the import path. Network stages
read the already-authorized SEC contact identity from `SEC_USER_AGENT`; do not
write this value to commands saved in source, manifests, or logs. Paths below
are user-selected output locations, not fixed ticker-specific paths.

```bash
python -m sec_xbrl.history discover --tickers NVDA AMD MSFT \
  --workspace work/my-history --as-of 2026-09-06 \
  --report-start 2023-01-01 --report-end 2026-09-06
python -m sec_xbrl.history ingest --plan work/my-history/plan.json \
  --output-run data/processed/history_runs/my-history \
  --package-cache data/raw/history_packages --index-cache data/raw/history_indexes \
  --taxonomy-cache data/taxonomy_cache --bootstrap-taxonomy
python -m sec_xbrl.history build \
  --intake-manifest data/processed/history_runs/my-history/history_intake.json \
  --output-root data/processed/analytical/history/my-history
python -m sec_xbrl.history query \
  --publication data/processed/analytical/history/my-history/panels \
  --ticker NVDA --period-class QTD_3M --view LATEST_REPORTED
```

Discovery also accepts `--recent-fiscal-years 3` instead of the two report
bounds, and repeatable `--submissions-root` paths with `--offline` for cached
discovery. Report bounds refer to actual SEC report dates, not calendar labels
assigned to company quarters. `--as-of` independently limits filing availability.
Repeated `--source-run` options on intake reuse verified snapshots from earlier
runs without copying raw tables or fabricating new source manifests.

An existing plan cannot be replaced with a different scope. Use a new workspace
for a later as-of date or changed interval. Ingestion retries archive their old
manifest and append accession outcomes. Arelle first loads offline; explicit
bootstrap permission allows cache population after failure, followed by a
separate offline load. Each extraction attempt has its own directory.

## Published output and interpretation

T1–T4 are built once per declared cohort and verified before reuse. `panels/`
contains a publication manifest plus `CIK/view/period_class/{columns,rows,cells}.parquet`.
Scalar values are typed Parquet fields; nested provenance is JSON-valued columns,
not JSONL copies of the complete dataset. Integrity hashes are per output file,
not per analytical row. The query command reads only these persisted tables:
it does not contact SEC, parse filings, select versions, or rebuild a panel.

The default company-history panel contains `CURRENT_FOCUS` observations, so a
prior-year comparative number is not mislabeled with the newer filing's fiscal
year. All comparative observations remain in T1; the manifest reports the
excluded-from-default-view count by CIK. `AS_FILED` and `LATEST_REPORTED` remain
separate views; the latter is not an evidence-backed recast view. It includes
eligible directly reported amendments without treating a partial amendment as
a replacement for every fact in the original filing.

QTD, YTD6M, YTD9M, FY and instant series remain separate. The latest incomplete
year stops at its latest collected fiscal quarter, rather than inventing future
missing columns. Expected coverage comes only from verified filing form and DEI
fiscal focus. A 12-month note fact in a 10-Q may have duration class `FY`, but
does not establish annual filing completion; inspect its actual boundaries.
A complete annual year exposes Q1–Q4; absent quarterly Q4 is
`UNAVAILABLE / DERIVATION_NOT_MATERIALIZED`, not absent ingestion and not a
reported FY substitute. This workflow currently publishes reported series only;
governed Q4 and quarterly cash-flow derivation are not materialized by it.

Rows retain full dimensions, standard/custom classification, canonical mapping
and navigation lineage. Same raw fact repeated across navigation paths coalesces
without losing those paths. Equal-scope unresolved value conflicts remain
unavailable cells. Four-statement PRE membership is preference evidence after
version and period agreement, not permission to override a different context.
Calendar comparability retains actual boundaries and the existing fiscal-month
signal; it is not complete fiscal-calendar-regime detection. Growth, ratios and
cross-company semantic comparison are not computed by this workflow.

Custom facts are available with raw identity and mapping review state, but their
presence is not proof of aligned custom-concept continuity across quarters.
The five-company QTD run did not demonstrate a custom-concept row joined across
multiple columns. No label-only mapping is introduced to manufacture continuity.

`repair-coverage --publication OLD --destination NEW` is a narrow migration for
the initial run's erroneous synthetic future columns: it revalidates the raw
filing metadata, removes only unbacked empty quarterly columns, and preserves
every actual row/cell. It never replaces the old publication or reselects facts.
The new manifest records the old path, manifest digest and removed columns.

The implementation must be independently verified on a frozen revision before
release. Operational run results are reported separately with actual filing,
company, period and row counts; a code commit alone is not execution evidence.
