# Price timeline interpretation — 2026-11-17

## Authorization and states

The user authorized in-screen interpretation of historical multiple position and fixed-band
meaning, explained unavailable history, real-screen verification and actual company coverage,
while preserving functionality/data/history. Base main is
`b5d926ed029752702eddec00295676879f50bec9` (PR108). Sole writer branch
`codex/price-timeline-insights`, isolated tree `work/price-timeline-insights-20261117/source`.
The disclosed approved GPT-6.1 Sol fallback owns implementation; separate read-only Astra
reviews its frozen SHA. ROOT owns actual browser staging/acceptance and any later activation.
No push/PR/main merge is authorized. The writer cannot activate runtime; ROOT is authorized
to stage and activate the exact independently verified consumer at18765 after acceptance,
preserving backend19078, old18766, publications and both journals. Root main, old worktrees,
1122protected pins, two journals and17untracked architecture artifacts are preservation bounds.

APPROVED: this scoped implementation. IMPLEMENTED: writer-checked candidate on this branch;
its frozen SHA is supplied at handoff. INDEPENDENTLY_VERIFIED, LOCALLY_ACCEPTED,
RUNTIME_ACCEPTED and MERGED remain separate pending states until specific receipts exist. Follow [delivery workflow](delivery-workflow.md).
The [original timeline contract](price-band-timeseries-20261116.md) and
[analytical plane boundaries](../architecture/analytical-data-model.md) remain authoritative.

## Design intent and component checkpoint

Domain: actual session, financial denominator, disclosed fiscal period, point-in-time eligibility,
rolling quantile boundary, fixed user multiple, source evidence, absent history.
Palette: filing-paper sheet, ivory ledger canvas, ink actual line, slate context, annotation blue
quantile evidence, amber diagnostic state. Signature: one cursor-linked reading strip above the
paired price/ratio plots explains the same date's bucket and denominator-based scenarios.
Reject separate summary card grids, buy/sell badges and invented exact percentiles; retain a
single textual hierarchy, bounded plots and the adjacent272px evidence ledger.

Intent: help an investor read actual history without turning it into investment guidance.
Hierarchy: selected date/multiple and historical bucket first; fixed-band meaning and counts
second; detailed missing ranges behind native disclosure. Palette/depth/surfaces: reuse
paper/ink/slate/blue/amber tokens and quiet borders. Typography: existing local Korean font,
14px reading text, muted12px context; spacing:4px base,8/12/16px grouping. Controls remain
native and keyboard/pointer cursor behavior stays shared. No new application navigation.

## Acceptance contract

- A pure metrics-layer interpretation consumes supplied ratio/quantiles/band rows only.
  Show a quantile bucket bounded by P10/P25/P50/P75/P90, explicit equality and median
  relation. Never manufacture an exact percentile, fair value, forecast or buy/sell signal.
- Current position is unavailable when ratio or its policy eligibility is unavailable, or
  distribution/quantiles are unavailable. Positive eligible fixed-band rows may explain
  a close-price bracket independently of distribution readiness. Identify EPS12m vs BPS,
  actual denominator and the selected positive user assumptions; no recomputation in JS.
- Preserve exact252expected+valid and existing3calendar-year definitions. Explain source/
  calendar coverage independently of the252valid minimum; show valid/required/missing
  counts without promising that waiting N future days fixes history/basis/readiness.
- Show aggregated absent ranges with dates/reasons near the plot, and selected-date reasons
  in the reading strip. Unknown readiness and evaluation16/quote13/ready16 remain distinct;
  no historical current-EPS backfill, zero fills or implicit data preparation.
- Scoped coverage comes from verified reader rows/sessions, not hardcoded company counts
  or109full timeline calculations. Distinguish selectable companies, any eligible historical
  ratio/chart, selected-date eligible ratio and eligible rolling distributions. Metric/policy/
  window/view range and publication identity accompany the aggregate. Current PER12 is
  not a historical-availability count. Final audited counts are recorded after actual checks.
- New metadata is additive. Old timeline snapshots without it reopen/export byte-identically
  and are never mutated or recalculated. The renderer can show existing stored quantiles/
  counts with an explicit legacy-metadata caption; it must not silently borrow current data.
- Source pin checks, bounded caches, all original saves/evidence/exports/comparison and other
  financial/common-market/Q4/history screens stay intact. No producers/accounting definitions,
  file-format migration, financial inputs, Raw downloads or republications change.

Known gaps: actual publication86fad has short/unready/absent valuation histories. Rich current
EPS does not create past eligibility. Quantile buckets are relative to each company's own
historical definition, not accounting equivalence across companies. Legacy saves may lack
new aggregate/interpretation metadata and must state that fact instead of inventing it.

## Inputs, verification and handoff

Actual unchanged publication:
`data/processed/price_metrics/20261116_direct_quarter_eps_ttm_v1/price_metric_manifest.json`,
SHA256 `86fad784c394f29465df8f07501e0ee5b32e24863a9a6b2bac514d2040bdce2d`.
ROOT audits actual coverage independently. Unit tests cover boundary/equal/outside quantiles,
nonpositive/missing eligibility,252vs3y coverage/minimum gaps, original snapshots and cache
pin tampering. Run focused Python plus price/common-market/Q4/history Node, Ruff,
JavaScript syntax and diff checks. ROOT verifies actual1920/1440screens after freeze and
independent PASS. Report frozen SHA, changed files, checks, actual scoped company counts
and remaining limitations; no generated data/evidence/secrets enter the commit.


## Implemented candidate and actual coverage

`price-timeline-interpretation-v1` adds per-point `interpretation`: ratio value, quantile
bucket/equality, median relation, central50 relation, separate sample minimum/expected-gap/
source-coverage fields and a price bracket referencing existing positive fixed-band rows.
No source ratio, quantile, band, historical definition or observation identity is changed.
The strip formats those fields, while old snapshots explicitly say their saved interpretation
summary is absent and retain original charts/values/export. New saved summaries stay stored;
the separate coverage response never mutates the saved result.

`POST /api/price-metrics/coverage` accepts exact `metric`, `view_years`, `window` and
`readiness_policy`, plus optional verified `evidence_context`. For reopened results that token
selects the original reader/publication, never the active reader. Unknown/expired tokens fail
closed. The worker exposes the route; existing bridge prefix routing needs no change.
Prefix counts over verified session/history rows produce a compact per-date company table,
not109full timelines. A four-entry cache still verifies the manifest, every participating
historical artifact and all declared source dependencies before a hit. Current EPS snapshot
availability is intentionally not part of these historical counts.

After the chart is displayed, one async request fetches coverage for its immutable result
scope. Pointer/keyboard date changes use the returned date table without requests. Late
responses cannot update another result; errors show an explicit unavailable state. Reopening
a new saved timeline loads coverage with its original evidence token; legacy saves without
new metadata show an explicit absent-at-save caption and never borrow current aggregates.

Actual unchanged86fad publication, three-year view:

| Historical policy / metric | Selectable | Any ratio in view | Ratio/band inputs2026-11-13 | Distribution252s any/latest | Distribution3y any/latest |
| --- | ---: | ---: | ---: | ---: | ---: |
| Filed-day diagnostic PER |109|10|9|0/0|0/0|
| Filed-day diagnostic BPS PBR |109|60|60|1/1|1/1|
| READY_ONLY PER |109|0|0|0/0|0/0|
| READY_ONLY BPS PBR |109|0|0|0/0|0/0|

MSFT alone currently supplies eligible BPS ribbons:503dates from2024-11-12 for252s,
283dates from2025-10-01 for3y. All those counts are calculated from the chosen reader,
policy/window/view; none are ticker constants or a supported-company limit. Current PER12
and common-equity PBR75 remain separate snapshot facts; they are not these historical
PER9 or BPS60 counts. New coverage results matched ROOT's independent audit for all eight
metric/policy/window scopes. Local cold scope timings4.74–4.86s; repeat verified cache hit
4.61s. This retains complete artifact validation rather than trusting file-stat-only cache
checks, is below the existing35s worker timeout, and never blocks first chart rendering.
Timeline query measured1.81s on the same local pinned data. These are observed timings,
not a general speed claim.

Local evidence:
`work/price-timeline-insights-20261117/evidence/coverage-summary.json`,
`coverage-audit.json`, `service-crosscheck.json` (ROOT independent audit) and
`writer-coverage-crosscheck.json` (new endpoint versus audit). These optional receipts are
not the only statement of normative counts or meaning; the table and rules above suffice
for a new checkout. No real source material was regenerated or republished.

## Writer checks and remaining acceptance

Writer checks:95Python PASS/1explicit cached-fixture SKIP;28price Node,5common-market Node,
6Q4 Node and13history Node PASS (52Node total). Ruff, app/bridge JavaScript syntax and
Git diff checks passed. Python tests cover equality at all five quantiles and ties,
outside buckets, nonpositive/ineligible input, independent coverage/minimum gaps,
fixed-price brackets,252/3y sliding-count equivalence, grouped gaps, all artifact/dependency
checks before cache hits and old/new original-reader snapshot reopen. Node tests cover
formatted governed metadata, unchanged legacy export, cursor no-network behavior, stale
coverage suppression and new-save original-context reload. The history suite uses approved
private loopback/fixture children; no operating journal is involved.

Reproduce focused checks from this isolated tree:

```bash
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m pytest -q tests/screening/test_price_timeline_insights.py tests/screening/test_price_timeline.py tests/screening/test_price_metric_publication.py tests/screening/test_price_related_metrics.py tests/screening/test_reported_quarter_eps.py
node tests/screening/screening_price_metrics.test.cjs
node tests/screening/screening_market_inputs.test.cjs
node tests/screening/screening_revenue_q4_continuity.test.cjs
node tests/screening/screening_history_lifecycle.test.cjs
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m ruff check src/sec_xbrl/metrics/price_timeline.py src/sec_xbrl/screening/price_metric_service.py examples/screening/price_metrics_worker.py tests/screening/test_price_timeline_insights.py
node --check examples/screening/display-assets/app.js
git diff --check
```

Separate Astra review of the frozen source, ROOT's1920/1440 actual browser/API checks,
private old-eight/new-save cold restart and exact export checks, protected1122pins/two
journals preservation and local operating acceptance remain pending. ROOT may activate only
the exact independently verified/accepted consumer; writer performs no activation. Remote
push/PR/main merge is outside this local milestone. No full repository suite or new corpus
qualification is claimed.
