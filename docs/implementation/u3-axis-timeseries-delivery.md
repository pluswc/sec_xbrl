# U3 Axis quarterly table — local delivery

This increment resumes the existing untested U3 draft at base
`0ae20ade4c2d5373a1f1fc9206d0922a424201ee` in the sole-writer
`codex/u3-axis-timeseries` worktree. The lead escalated implementation after
scope/period/source validation defects in the previous draft. The user authorized
this replacement writer and a separate read-only verifier. Local commit/freeze
replaces the remote push prerequisite: no push, PR, merge, Excel, platform,
new-industry, parser or Raw changes are authorized. Independent final acceptance
belongs to the separate verifier/lead; writer checks are self-verification.

## API and identity

`AnalysisClient.axis_timeseries(ticker, lens_id, context=overview['context'])`
returns the metric total, **all** eligible prepared member nodes, shared fiscal
quarter columns, one explicit cell per row/column, exact trace, prepared
importance/reasons/warnings, and applicable prepared source checks. It pages
through `children(selection='all')` until completion, bypassing the display top-N
selection. Unknown company, foreign context, non-dimensional lens, duplicate
cells, repeated pages and mixed period classes fail closed. The supported axis
period classes are QTD_3M and INSTANT; YTD/FY are never relabelled as quarters.

`rows[*].prepared_node_id`, `mapping_epoch`, `prepared_node`, full dimensions and
basis remain intact. Identical labels or QNames never merge nodes. Missing
coordinates have value null and UNAVAILABLE, never zero. Existing reported and
derived cells, including governed core Q4, are copied unchanged. No query-time
monetary calculation, filing/recast selection, new custom Q4 or continuity bridge
is introduced. Source-less synthetic null cells explicitly carry their reason.

Each response has `publication` and `axis_context`, binding the original analysis
publication plus the distinct axis companion publication ID and decision cutoff.
Every reviewed relationship and source comparison carries this same identity.
The old overview context remains compatible and does **not** alone attest a new
axis review. Review caches include companion ID, cutoff, relative path and
expected checksum. Returned nested evidence is defensively copied.

## Additive preparation and bounded review

`analytics.axis_timeseries.prepare_axis_timeseries` copies every old bundle file
byte-for-byte and writes only `axis_timeseries_manifest.json` and `axis_reviews/`
with original review/panel bytes and prepared exact checks. Dataset hashes are
verified before copying; unsafe paths, symlinks, nested destinations and
companion-on-companion inputs reject. This is a preparation operation, separate
from the read-only API. Old publication IDs, source/as-of/review cutoffs and
all analytical datasets remain unchanged. The new decision timestamp is aware,
actual and no earlier than the supplied review.

`AxisReviewInput` explicitly binds ticker, anchor row, dimensional lens and two
input files. A supplied panel must equal the checksum-attested existing
`AnalysisClient.statement()` result, not merely agree with a supplied review.
Each approved equation requires exact table/document identity, row occurrences,
filing/CIK, concept, actual QTD period, unit, full dimensional scope, Raw view,
as-of and basis, reported finite numeric values, unique fact/row/scope bindings,
and unweighted zero-difference composition. Preparation alone verifies arithmetic.
No share policy, global CAL relation or accounting equivalence is granted.

The exact lead approval for NVDA accession `0001045810-25-000230`, table
`7c6aec59e597e8cae0da3ed1`, covers sixteen reported facts and four QTD equations:
Revenue = Data Center + Gaming + Professional Visualization + Automotive + OEM
and Other; Data Center = Compute + Networking, each in current and prior
three-month columns. Two current equations attach to the exact selected
Analytical Raw IDs. Different historically selected prior IDs are not replaced:
the prior two equations remain SOURCE_COMPARISON_ONLY. Exact bindings compare
selected value/status, filing, accession, raw concept, dates, unit and full raw
dimension signature using prepared trace evidence. Unapproved relationships stay
DIMENSIONAL_VIEW_MEMBERSHIP_NOT_EQUATION. Nested components never become extra
inputs to the revenue equation.

## Display

Analytical is the default. Rows run top-to-bottom and quarters left-to-right in
real HTML table cells with shared column geometry and horizontal scrolling.
The sticky metric label includes **구성 보기** for immediate entry into its first
prepared Axis, and visible metric/Axis controls allow switching without choosing
a member. Existing source, PRE and member inspection controls remain available.

All mapping epochs remain visible with observed fiscal periods, review/basis
status and a short prepared node identifier beside the original label. Exact
reviewed current nodes use the approved source order and nested DC hierarchy;
other epochs follow with their actual coverage. The total is contextual, not a
claim that all historical rows are simultaneous addends. Totals, reviewed
subtotals, warnings and required ancestor paths survive collapse; restore exposes
all rows. Original prepared importance reasons remain inspectable and visible.

Only the exactly applicable quarter receives a compact equation count/status/
difference badge. Named formulas remain in its title, inspector and the wider
review comparison area. A **검토된 원문 구성 비교** jump sits beside Axis controls.
That separate fixed two-period table identifies its own form, accession, report
and filing dates, direct source link, companion ID and cutoff. Its eight rows
(total plus seven members) are source-scoped and explicitly do not replace
historical Analytical selections. Duration endpoints remain exclusive. Source/
PRE transitions restore the original header DOM, period labels and controls.

## Verification and resumed baseline limits

`tests/unit/test_axis_timeseries.py` uses synthetic data for >1000 pagination,
null versus zero, duplicate labels/epochs, company/lens/period/cell rejection,
source attestation and full-scope failures, unsafe publication inputs and
companion cache identity. `tests/test_axis_timeseries_cached.py` is opt-in actual
six-company evidence: all eligible nodes and exact values/traces, known NVDA
38 nodes/7 labels, four bounded equations, source comparison, old bundle bytes
and old overview equality. AMD reorganization and source warnings remain covered
by `tests/test_hierarchy_cached.py`. AMD's prepared rank>5 records belong to other
branches, not this axis cohort; that legacy all-selection inspection is tested
without claiming a rank>5 actual Axis fixture. The synthetic pagination case
covers a large Axis. Runtime rules were not relaxed for fixture assumptions.

The cached hierarchy test always compares old v1 manifest hashes and actual
records. Extra historical hashes are optional through
`SEC_XBRL_HIERARCHY_BASELINE_HASHES`; explicitly supplied hashes must be nonempty
and all match. The original `/tmp` 831-file list and the previous 29,238-file
preflight did not survive environment restart. They are not recreated or claimed
as checked. The durable lead 1,469-file baseline is separate resumed evidence,
with independent reconstruction owned by the verifier.

Run from the new tree with root `.venv/bin/python`, `PYTHONPATH=src`,
`PYTHONDONTWRITEBYTECODE=1`, pytest `-p no:cacheprovider` and a new completion-dir
`--basetemp`. Set `SEC_XBRL_AXIS_BUNDLE`, `SEC_XBRL_AXIS_SOURCE_BUNDLE`,
`SEC_XBRL_HIERARCHY_BUNDLE` and `SEC_XBRL_PROJECT_ROOT` for actual-cache tests.
`tests/browser/axis_timeseries.mjs` uses explicit local HTML, Playwright and
Chromium environment paths, blocks HTTP(S), and checks every rendered Axis cell,
true header/body geometry, visible epochs, protected collapse/restore and source
mode restoration for all six companies. `hierarchy_regression.mjs` preserves
F1–F4 checks with the new column geometry and default mode.

Generated bundle/HTML, reports, commands and final local SHA are recorded only
under `work/u3_axis_timeseries_complete`. That directory's FREEZE.json is the
independent verification target; old bundles, HTML and worktrees are immutable.
