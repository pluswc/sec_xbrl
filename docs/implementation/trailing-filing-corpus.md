# Trailing Fiscal-Year Filing Corpus

`TrailingFilingCorpus` is the company-level orchestration boundary after
Filing Discovery.  It accepts an upstream CIK-scoped `AccessionProvider`, not
a ticker-specific list or hard-coded accession values.

For requested `N` fiscal years it selects the latest `N` filed `10-K` annual
baselines by `report_date`, identifies the preceding annual baseline, then
includes every `10-K`, `10-Q`, `10-K/A`, and `10-Q/A` whose report date is after
that predecessor.  This captures all intervening quarterly updates and later
updates following the latest annual baseline without assuming calendar years.

Each filing follows the existing immutable package/cache and atomic Layer 1
path.  A filing failure remains retryable and appears in the corpus manifest.
The corpus does **not** publish its M6/M7 analytical output until every
selected filing has a Layer 1 snapshot; a successful filing snapshot remains
independently immutable and reusable on retry.

Once complete, the orchestrator reads those snapshots, runs M6 period analysis,
M7 canonical mapping/annual-current series construction, and the governed
recast observation boundary.  Reviewed recast evidence remains an explicit
input to the later Layer 2 review path; this orchestration never promotes a
numeric change to a recast by itself.

The run report records selected annual baselines, the fiscal window boundary,
every source accession/form/filed date/report date, source/materialized Fact
counts, failure reasons, retryability, and analysis availability.
