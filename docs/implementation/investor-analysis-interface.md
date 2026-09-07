# Prepared investor analysis interface

## Consumer contract

`sec_xbrl.analysis.open_analysis(bundle_or_catalog)` opens an immutable Parquet
consumer bundle, or an administrator catalogue with `analysis_current.json`.
Queries do not collect SEC documents, parse XBRL, reselect filing versions, or
calculate financial values. Datasets are verified/read once per client and
cached. Trace data uses separate partitions, not duplicated inline in every
cell. HTML is a consumer of these exact functions; its JavaScript only opens
prepared branches and formats their already prepared value tables.

```python
from sec_xbrl.analysis import open_analysis

client = open_analysis("/absolute/path/to/catalog")
panel = client.overview("AMD", fiscal_start=2023, fiscal_end=2025)
groups = client.list_breakdowns("revenue", context=panel["context"])
branch = client.children(groups["groups"][0]["node_id"], context=panel["context"])
more = client.children(branch["children"][0]["node_id"],
                       context=panel["context"], path=tuple(branch["path"]))
trace = client.trace(panel["cells"][0]["cell_id"], context=panel["context"])
comparison = client.compare_views("AMD", fiscal_start=2023, fiscal_end=2025)
```

Omitting year bounds returns the latest eight prepared quarters. Explicit year
bounds can include an incomplete year, including a single newly collected
quarter. No empty annual baseline is invented. QTD and INSTANT columns remain
distinct. Every core row is retained even if unavailable. `as_of` and
`review_cutoff`, when supplied, must exactly match the publication: filtering
cells by an earlier date cannot reproduce an earlier selection/review state.
Open the separately prepared historical publication instead. AS_FILED is the
original filing selection; LATEST_REPORTED is the current eligible selection,
not a guarantee of economically comparable recast statements.

Results retain query context, publication, view, actual dates, basis, full unit
and dimensions, status, source identifiers, stable nodes and provenance. A
cursor is scoped to context, node and ancestor path. Follow the returned path
for deeper queries. Cycles terminate without imposing a fixed depth. CAL
networks retain source filing/role; DEF follows targetRole and positive
dimensional arcs while keeping structural nodes distinct from business values.
PRE supplies statement context only, never invented decomposition. Independent
dimensional views cannot be summed. A reviewed display hierarchy needs exact
basis/full dimensions, an evidence hash, reviewer/time, and an explicit source
table allowlist. New filings do not inherit it.

## Preparation and administration

```python
from pathlib import Path
from datetime import date
from sec_xbrl.analysis import prepare_catalog, refresh_analysis

bundle = prepare_catalog(catalog=Path("/admin"), destination=Path("/new/bundle"),
                         tickers=("AMD",), fiscal_start=2023, fiscal_end=2025)
# Explicitly performs discovery / collection / calculations, then prepares
# and publishes the consumer bundle. Never called implicitly by a query.
bundle = refresh_analysis(admin=Path("/admin"), workspace=Path("/new/work"),
                          as_of=date(2026, 9, 8), review_as_of=date(2026, 9, 8),
                          tickers=("AMD",))
```

The catalogue uses existing `company_reports` registration. Optional
`analysis_profiles.json` maps ticker to core rows/order/exact QName choices,
display notes, `breakdown_sources` and separately reviewed `hierarchies`.
`lens_preferences` can match an existing anchor/lens type/role/basis to set its
label, display order or hidden flag; it cannot create a semantic edge.
Profiles have at most 25 unique core rows. A related statement source is labeled
as such: LiabilitiesAndStockholdersEquity is not relabeled as a liabilities
total. Productive-asset cash outflows are not silently equivalent to PPE-only
cash outflows. A new company requires configuration, not engine code changes.

`prepare_analysis(publication=..., destination=..., tickers=...)` is the lower
level single-source producer. It reads governed history plus its declared raw
relationship/concept snapshots only during preparation. Existing source files
and publications remain immutable. `prepare_catalog` resolves per-company
publication paths and atomically publishes a pointer after success.

Reviewed-company refresh attempts exact candidate/source-preserving review
republication, including all old decision/quality histories and quarantines.
If new accessions appear for a reviewed company, or candidate identities no longer bind, it retains new collected/Analytical
artifacts, writes `review_refresh_required.json`, and leaves registrations
unchanged. Rebinding approvals to changed identities, or approving new filing
interpretations, is not inferred from an old one-filing decision.

## Derived values and limits

The standard CF policy additionally permits cash-flow-statement-scoped
repurchases, share compensation and productive-asset purchases. Exact currency,
duration, complete dimensions, fiscal boundaries and source lineage remain
required. Q4 remains FY minus nine-month YTD; FY is never replaced. EPS, share
counts, ratios and arbitrary custom facts are not subtraction candidates.

The investor metric adapter never promotes null basis to COMPATIBLE. A separate
versioned *reported-value arithmetic* result preserves null basis and carries
`REPORTED_VALUES_NOT_RECAST_VALIDATED`; it is not reusable as Q4 compatibility
or CURRENT_COMPARABLE evidence. Negative/zero bases are not ordinary growth
rates. Actual duration differences remain warnings. Margins require exact
period/unit/dimensions and primary-statement evidence for each same-filing input
leg; approved quarter-difference inputs must match their complete source-period
pairs. Financial arithmetic is persisted by the producer, never by HTML.

Not implemented: automatic narrative-to-zero extraction, unrestricted custom
concept bridges, cross-company accounting equivalence, automatic new-filing
semantic approvals, or importance ranking. Missing direct totals are not filled
by an unreviewed Assets-minus-Equity guess. Retained original notes and explicit
review queues are the fallback, not fabricated values.

## Resume a review-stopped refresh

The last successful catalogue pointer remains readable. The failure artifact
identifies the newly prepared parent, new accessions and previous review
publication. Use the existing explicit review workflow, rather than removing
the old review overlay:

```bash
python -m sec_xbrl.disclosure_review prepare --parent NEW_PARENT \
  --locators exact-source-locators.json --rules scoped-review-rules.csv \
  --package-root IMMUTABLE_PACKAGES --quality-decisions quality-history.csv \
  --destination NEW_INVENTORY
```

Review the exact source candidates and record separate A interpretation and B
additive-Q4 decisions with actual knowledge timestamps. Preserve all old
candidates and decision histories when combining the new inventory. Publish
with `publish_review(..., previous_publication=OLD_REVIEW)`; its append-only
checks reject deleted/edited decisions. If old raw sources now bind to different
consumer identities, stop for explicit rebind review—the existing identity is
not silently rewritten. Finally `company_reports.register_company(...,
publication=NEW_REVIEW)` and `prepare_catalog(...)` publish the new consumer
bundle. New accession and changed-concept bridges remain explicit review work,
not a fully automatic refresh capability.
