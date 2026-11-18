# Price timeline interpretation — 2026-11-17

## Authorization and states

The user authorized in-screen interpretation of historical multiple position and fixed-band
meaning, explained unavailable history, real-screen verification and actual company coverage,
while preserving functionality/data/history. Base main is
`b5d926ed029752702eddec00295676879f50bec9` (PR108). Sole writer branch
`codex/price-timeline-insights`, isolated tree `work/price-timeline-insights-20261117/source`.
The disclosed approved GPT-6.1 Sol fallback owns implementation; separate read-only Astra
reviews its frozen SHA. ROOT owns actual browser staging/acceptance and any later activation.
The original2026-11-17 local authorization excluded remote delivery and allowed ROOT
activation only after independent acceptance. The2026-11-18 remote-approval section below
supersedes that earlier no-remote state. The new remote task excludes main merge and further
operating activation; the writer never activates runtime. Root main, old worktrees,
1122protected pins, two journals and17untracked architecture artifacts are preservation bounds.

Historical2026-11-17 local states (new integration gates are separate below):
APPROVED: that scoped implementation. IMPLEMENTED and INDEPENDENTLY_VERIFIED: product
`c7241f94d9a5f4df4d3c3207ea7d5c73997fe4f8`, separate read-only Astra PASS.
LOCALLY_ACCEPTED and RUNTIME_ACCEPTED: ROOT PASS at2026-11-16T15:25:28.099790Z
(2026-11-17KST); final receipts below. MERGED: not performed or requested for this milestone.
Earlier candidate/pending statements below describe their historical stages. Follow [delivery workflow](delivery-workflow.md).
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


## Final local and operating acceptance — 2026-11-17

ROOT accepted **product `c7241f94d9a5f4df4d3c3207ea7d5c73997fe4f8`** after separate
Astra frozen-source PASS, at `2026-11-16T15:25:28.099790+00:00` (2026-11-17KST).
This final update changes only tracked documentation; product/tests remain byte-identical
to c724. The preceding pending clauses are historical and do not supersede this final state.

| Stage | Final evidence |
| --- | --- |
| Implemented product |c7241f94d9a5f4df4d3c3207ea7d5c73997fe4f8|
| Independent source/actual-data review |Separate read-only Astra PASS;95Python/1cachedSKIP,52Node, Ruff/syntax/diff and original-pin probes PASS|
| ROOT actual browser/API |1920×1080/1440×900, selected-date interpretation/cursor/coverage/gaps PASS with zero live UI errors|
| ROOT local/operating |18765/PID55536, previous38488; unchanged pub86fad and original backend19078/native14/18766|
| Remote/main |Not requested or performed; main b5d926ed029752702eddec00295676879f50bec9 unchanged|

Verified evidence locators:

- `work/price-timeline-insights-20261117/evidence/root-final-acceptance.json`, SHA256
  `8201885ee37954b8d0c950a255af1e971cdfc2ba497b98e36228463b4fb26aba`.
- `work/price-timeline-insights-20261117/evidence/independent-insights-c7241f9.md`, SHA256
  `ef012c778b04dba7756eb764173e68b9e76589e108714d2fb88f06d10509666a`.
- Independent actual coverage summary SHA256
  `c2d1b2f9916922bbdc9c487a1d4e98a962c509d3093ef9d257a30497d712f439`.

ROOT verified the live MSFT latest P50–P75 bucket, median/central50 relation and8–10fixed
band bracket; the first historical date's1valid/252required/251shortfall; the separate3y
source-coverage gap despite minimum samples being met; READY_ONLYzero scope counts;
NVDA PER input gap; original/current evaluation-date separation; and shared mouse/keyboard
cursor/evidence. All eight actual coverage scopes match the table above.109selectable,
historical PER10any/9latest/0distributions and BPS60any/latest/1distribution remain distinct
from current PER12. MSFT's754BPS points retain503eligible252s and283eligible3y points.

Private clones preserved all eight original SQL rows exactly, including notes/definitions/
payloads. One explicit new UI timeline save made nine; actual cold restart63660→20772
retained them and both new and legacy exports exactly. New saved summaries reload coverage
against their original evidence context; legacy snapshots retain their absent-at-save
caption and original values. Operating price saves remain0, legacy trash8, and there were
**zero operating test saves**. Both original journals remain exact with integrity `ok`.
All1122protected files and17untracked architecture artifacts are preserved. Current2834price
observations/1335available and all prior fields of two MSFT timelines are hash-identical to
baseline; no source/denominator/ratio/quantile or accounting policy changed.

The active immutable source archive is
`work/price-timeline-insights-20261117/accepted-source-c7241f94d9`. Operating18765/PID55536
uses its price worker and exact frozen assets. Backend19078/PID1477655 and native14 remain
unchanged; old18766two-company view remains unchanged. ROOT performed activation and final
read-only checks; the writer only records the verified receipt.

Windows staging/config/evidence root:
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/price-timeline-insights-20261117`.
Its `commands-receipt.json` pins source, original publication and `private-start.json` /
`live-start.json` exact configurations; SHA256
`c70d165a2af7c318f8f5e3cf569b1feb26e085e017486d18143752d2519f0e7b`.
`live-c724-running.json` records the active exact command; assets match c724. Representative
actual screenshots under that same absolute root are `msft-latest-1920-live.png`,
`msft-latest-1440-live.png`, `msft-first-date-1440-live.png` and `nvda-per-gap-1440-live.png`.
`ui-live.json`, `values-live.json`, `existing-functions.json` and `final-health.json` record
actual API/UI/legacy-function and final health checks. These local locators supplement the
tracked rules/counts/status rather than replacing them.

The focused reproduction commands above remain valid. Under delivery-workflow section0,
this documentation-only follow-up checks receipt hashes, content/links/diff and product
source equality; it does not rerun unchanged product tests or perform runtime actions.
Final documentation freeze is reviewed separately. No push, PR, remote CI or main merge was
requested/performed, and no new financial inputs, Raw capture or publication was created.


## Authorized remote delivery and latest-main integration — 2026-11-18

The user now authorizes remote delivery (push and PR) of timeline interpretation, gap guidance
and scoped company counts after checking latest main and preserving existing functionality,
data and history. ROOT owns push/PR/CI and private-browser acceptance. This new scope does
**not** authorize main merge or an operating restart/activation. The same disclosed approved
GPT-6.1 Sol fallback remains sole integration writer; separate Astra reviews the new frozen
SHA. Earlier local acceptance/no-remote/PENDING records are dated history, not permission
to bypass the new integration gate.

ROOT fetched **`origin/main 0b18528d8750f217a2cc73d88bdfba5c267f1898`**, containing PR109's
accepted Q4 EPS product6c4 and PR110's delivery documentation. The writer normally merges
that exact main into existing `codex/price-timeline-insights` from documentation head
`99996ce42af5c9566df43593e279c6cded61162a`; no rebase, force or history rewrite is used.
Conflicts are only planning append history and appended Node tests: both sides are retained.
The app auto-merge retains Q4 typed labels, selected-Q4 evidence, KST ready-time display and
`GOVERNED_Q4_COMPONENT_TTM` flags alongside c724's interpretation/coverage/reopen logic.

| New delivery gate | State at integration freeze |
| --- | --- |
| User remote authorization |Push/PR approved; main merge/operating activation excluded|
| Local normal integration |Implemented/writer-checked; exact two-parent SHA supplied at handoff|
| Independent integrated-source review |PASS on a8ce54c171b1d58592ad34195f02eaf658cb0c11; report below|
| ROOT integrated local/private browser acceptance |PENDING; operating read-only baseline is separate|
| Remote push / PR / required CI |PENDING ROOT execution and actual receipts|
| Insights main merge |Not performed or authorized by this remote-only task|

### Preserved code and current operating limitation

All Q4 producer/readiness/current-evaluation/publication code, its fixtures/tests and main's
architecture/period contracts remain byte-identical to fetched main. No new accounting
meaning, EPS policy, producer preparation, inputs, Raw collection or republication is added.
The c724 interpretation module, service/coverage source checks, worker route, CSS and Python
insight tests remain byte-identical to99996ce/c724.252complete vs3y policies, source-scoped
identities, READY_ONLY, bounded caches, async/stale guards and original saved-source
reopen/export behavior are retained. Other financial/common-market/Q4/history UI remains.

**Current operating baseline has a P1 source-composition gap.** ROOT's read-only check found
18765/NativePID60968 uses the accepted6c4 price worker with a c724-based UI overlay, but that
worker returns no `interpretation_definition`/per-point summary and `/coverage` returns404.
This is not a claim that current live insights are normal. The merged source restores those
code paths together with Q4 behavior when a consumer uses this integrated source, as verified
privately; it does not change the operating process in this task. The previous17th-day c724
local/operating acceptance above remains true for that earlier composition/publication.

ROOT's baseline locator is
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/price-insights-remote-delivery-20261118/operating-insights-before.json`.
The operating source is
`work/common-q4-eps-reconstruction-20261118/accepted-source-6c4c9a57e5/src`.
Preservation baseline `work/price-timeline-insights-20261117/remote-delivery-20261118/evidence/preservation-baseline.json`
protects1675files, two original journals and17untracked architecture artifacts. Backend19078,
native14 and separate18766 remain outside writer mutations. ROOT prepares a private union
clone of14old records for new-save/cold restart/export checks; no original database is written.

### Actual current publication and private comparisons

Current input is existing
`data/processed/price_metrics/20261118_common_q4_eps_v2/price_metric_manifest.json`,
SHA256 **`8a5bf28974f3f7f01ebae3985c0664ee458ee0e081444797b41438169035d3d6`**,
publication ID `screening-price-metrics-dc58939be9ad198d7883fa7e`.
Actual2834rows contain1337available/1497unavailable; current PER/EY companies are13,
including AMZN EPS12.37/PER21.55699302038071139854486661277284. Current common-equity
PBR75 and BPS PBR60 remain distinct. Financial326observations preserve the prior325.
Earlier86fad/currentPER12 statements above are dated historical evidence, not current counts.

Writer read-only/new-temporary-journal probes verified:

- All2834current observation fields match latest main exactly; five current band/evidence
  routes (AMZN/MSFT/NVDA/ABBV/HON) match main exactly, including typed Q4 context, original
  direct-EPS priority, AMZN selected-Q4 proof and historical/backtest-ineligible flags.
- Five timelines' original fields (MSFT BPS/PER, NVDA/ABBV/AMZN PER) match both main and
  accepted c724 on the new publication. New current EPS does not appear in historical
  evaluation context or backfill the13th-session PER/bands; MSFT BPS retains503eligible252s.
- All eight new-publication metric/policy/window coverage scopes were recalculated and match
  c724's same-source aggregate hashes: diagnostic PER any10/latest9/distributions0; BPS
  any60/latest60/distributions1; READY_ONLY all0. These are re-audited historical counts,
  not an inference from currentPER13.109companies remain selectable; view range is3years.
- Four actual old977/86 query/timeline snapshots and two new8a5 query/timeline snapshots
  reopen exactly after private service restart, preserving notes, source pins and new
  original evaluation context. This uses a newly created temporary SQLite clone only;
  no prior receipt database or live journal is written. UI export shape/original-context
  behavior passes the retained Node regressions; ROOT separately owns actual private
  browser export/cold restart acceptance of its14old+new1 union.

Probe evidence:
`work/price-timeline-insights-20261117/evidence/writer-main110-integration.json`, SHA256
`c67ec177434d3eba99ac18a6aff7b0d08ea1ca726e81c7c013fd6fbd0cd3a65f`. This probe reads pinned prepared inputs and invokes consumers; it does not
prepare producer data. Full data preparation/Raw qualification is not repeated.

### Fresh missing-metadata UI correction and deployment obligation

The live composition finding exposed a misleading fallback: a fresh request with missing
worker metadata was described as “saved at the time.” The narrow integration correction
gates the legacy caption on `priceWorksheet.readonly`. Fresh absent metadata now says the
selected-date summary/company aggregate could not be loaded and refers to original values/
evidence; it neither claims an old save nor waits permanently. Read-only legacy reopen keeps
its original caption and unchanged result/export bytes. Fully supported fresh results are
unchanged. A focused fresh-versus-legacy Node regression passes. Only this UI-copy branch
changed after the Python/other Node checks; the30-test price suite, syntax and diff were
rerun. No financial calculation or source-selection change was made.

Any later deployment handoff must verify **both** fresh per-point interpretation metadata
and successful `/coverage` from the same integrated UI/worker/publication scope. Asset hashes
alone do not prove that composition. ROOT will verify an immutable private candidate before
remote delivery; this task does not restart or repair the currently operating P1 composition.

### Checks and remote handoff boundaries

Focused **147Python PASS/1explicit cached-fixture SKIP**, plus30price +5common-market
+6Q4 +13history = **54Node PASS**. Ruff, app/bridge/test JavaScript syntax, relative links
and diff checks passed. History uses narrowly approved temporary loopback/fixture children.
No full repository test-suite or new CI result is claimed. Reproduce the prior focused
commands with `tests/screening/test_q4_eps_reconstruction.py` added to the Python invocation;
the four Node entry points and Ruff/syntax commands above remain applicable. Source comparison:

```bash
git diff origin/main -- src/sec_xbrl/metrics/price_related.py src/sec_xbrl/metrics/q4_eps_reconstruction.py src/sec_xbrl/metrics/company_valuation_readiness.py src/sec_xbrl/metrics/reported_quarter_eps.py src/sec_xbrl/screening/price_metric_publication.py examples/screening/prepare_q4_eps_reconstruction.py tests/screening/test_q4_eps_reconstruction.py
git diff 99996ce42a -- src/sec_xbrl/metrics/price_timeline.py src/sec_xbrl/screening/price_metric_service.py examples/screening/price_metrics_worker.py examples/screening/display-assets/app.css tests/screening/test_price_timeline_insights.py
git diff --check
```

Both source comparisons are empty. The normal merge freezes only tracked feature/inherited
main changes and these contracts; generated data/evidence/archives/journals/secrets are excluded.
ROOT receives the frozen merge SHA for separate independent review, private actual browser
acceptance and authorized push/PR/required CI. No push, PR, main merge or runtime change is
performed by the writer. The unchanged operating P1 composition gap remains explicitly
bounded until a separately authorized operating decision; remote code delivery alone does
not assert activation or repair of that live process.


### Independent integration PASS and locator correction — 2026-11-18

Separate read-only Astra review passed frozen product
`a8ce54c171b1d58592ad34195f02eaf658cb0c11`. Report:
`work/price-timeline-insights-20261117/remote-delivery-20261118/evidence/independent-a8ce54c.md`,
SHA256 `f312aadc23a75efea5042e3a8e131452c8def0254367f561eb806291c1eda357`.
This documentation-only successor corrects the preservation-baseline evidence directory;
product/tests remain byte-identical to a8ce. Earlier independent-PENDING statements describe
the preceding integration stage.

ROOT's private18889 before-restart browser checks passed:14original snapshots plus one new
save (15total), exact current AMZN Q4 values/evidence, interpretation/gap/company counts,
new-save original-context coverage and old exports, with zero errors. Private cold-restart
verification and final ROOT integrated acceptance are still pending; no completed cold
restart is claimed here. Push/PR/required CI/main remain pending, and no operating activation
or remote action occurs in this documentation step. Content/link/diff/product-equality checks
are sufficient for this documentation-only freeze under delivery-workflow section0.
