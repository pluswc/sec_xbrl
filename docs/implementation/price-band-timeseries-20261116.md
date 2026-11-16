# Price bands and rolling distributions — 2026-11-16

## Authorization, scope and status

The user approved implementation of the reviewed V3 temporal price analysis on actual
companies, preservation of existing functionality/data/history, and actual UI verification.
This contract records the lead's accepted implementation decisions. It supersedes the
mockup's proposed default 3-year distribution window with the explicitly approved new
252-session definition below. Synthetic mockup data is never a product data mode.

Original local baseline: main `75ac14efb8` (PR106), isolated branch `codex/price-band-timeseries`,
worktree `work/price-band-timeseries-20261116/source`. The original authorization was local
only; the later remote-integration section records the new push/PR authorization. Main merge
and further runtime activation remain outside that new scope. The lead owns runtime staging/activation, accounting judgment and
acceptance. One implementation writer uses GPT-6.1 Sol because the written GPT-5.6 Sol
default is unavailable; that disclosed fallback was approved. A separate Astra performs
read-only independent verification after the writer freezes a local commit, following
[delivery workflow](delivery-workflow.md).

The following table records the previously accepted local product; the new integration
candidate and its pending remote gates are recorded in the final section.

| State | Evidence |
| --- | --- |
| PROPOSED | Reviewed V3 mockup: price/fixed bands above actual multiple/rolling quantiles |
| APPROVED | User implementation authorization; lead's 252-session/3-year and preservation decisions |
| IMPLEMENTED | Final product `aabadc222e7149ec177a47b92f9de0ad5e99b04e`; calculation/worker/bridge/appJS identical to accepted183a |
| INDEPENDENTLY_VERIFIED | Separate read-only Astra PASS on final product `aabadc222e`; both dated report hashes below |
| LOCALLY_ACCEPTED | ROOT PASS, 2026-11-16T08:17:57.959Z; refined final receipt below |
| RUNTIME_ACCEPTED | ROOT PASS at18765, PID36476; productaabadc immutable source, existing financial backend preserved |
| MERGED | Not performed; no remote delivery authorized |

## Data and meaning

Use the existing immutable publication
`data/processed/price_metrics/20261116_company109_valuations_v2/price_metric_manifest.json`,
SHA256 `9774ca17e449cc484da809dece739eba0da1f08655b52a9a616ebfa5677f9f03`.
Its source pins own actual prices, verified US sessions and eligible financial inputs.
All 109 companies remain selectable; data availability comes from each published row.
PER9/PBR75/BPS60 are current-publication availability counts, not historical ribbon
eligibility or a supported-company boundary. No raw collection, financial preparation,
new valuation binding, network capture, or qualification promotion is authorized here.
Financial anchors, known dates and original gap statuses remain unchanged.

The service reads each day's published `per` or `pbr_bps` observation and its exact linked
EPS12-month or BPS input ID. Shared metrics-layer fixed-band logic multiplies that input
by the user's positive fixed multiples. It never infers a denominator from price/ratio,
replays the latest denominator into history, or conflates BPS-based PBR with common-equity
PBR. The original Raw, reported and published observations are untouched.
Nonpositive, missing and incompatible observations remain gaps. `READY_ONLY` also masks
unready per-date ratios and fixed bands; original published historical rows stay in the
result as provenance and do not become ready merely because a timeline exists.

## Rolling definitions and windows

`price-band-timeseries-v1:rolling252s` is a new, distinct metrics-layer definition.
At each actual session t it selects exactly the most recent 252 expected verified US
sessions through t inclusive. It requires full source/calendar coverage and **252 valid,
positive, policy-eligible observations** in that exact window. A missing or unready session
prevents quantiles; partial windows never produce a ribbon. Linear interpolation uses
index `(N-1)*q` for P10/P25/P50/P75/P90 and the existing 34-digit Decimal context.
Future rows cannot enter a historical window. Window start/end, valid/expected/missing
counts, minimum252, policy, definition version and diagnostic state accompany each point.

The optional `3y` window delegates unchanged to the existing
`price-related-metrics-v1:historical_{metric}_percentiles_3y` definition: trailing three
calendar years, full intended calendar/source coverage and minimum252 eligible samples.
Its existing partial-valid-sample policy is retained, never silently relabeled as252s.
A separate 1/3-calendar-year **view range** clips displayed dates only; it does not change
the calculation history. With only three years of actual input, most 3y points can be
unavailable. Their reasons/counts remain visible; the last quantile is never stretched
backward to invent a historical ribbon.

`DIAGNOSTIC_FILED_DAY` is prominently diagnostic and backtest-ineligible. It requires
the existing publication's diagnostic authorization. `READY_ONLY` uses only explicit
`historical_ready is True`. Neither policy promotes historical readiness or resolves
stale financial inputs. A whole timeline conservatively claims no backtest qualification;
individual distribution points retain their own eligibility metadata.

## Interface and result contract

`POST /api/price-metrics/timeline` accepts exactly one `cik`, `metric` (`per`/`pbr_bps`),
1–6 `multiples`, `view_years` (1/3), `window` (`252s`/`3y`), and optional
`readiness_policy`. Default is BPS,3-year view,252-session calculation, existing publication
readiness policy. The reader verifies exact historical artifact and source pins before
computation or a bounded four-entry service-cache hit. Cache keys include publication,
parameters and new definition. No companion publication/migration is needed.

The result pins its publication, sources, historical rows, parameters and calculation
definition and contains ordered per-date points with original close, ratio, compact
financial denominator metadata, fixed-band outputs and distribution output. Financial
proof is not copied per date×multiple: bands carry compact input lineage; expanded evidence
continues through the existing verified ratio-evidence operation. Each distribution's
input-reference predicate plus window, readiness policy and shared original historical rows
identifies its exact input set; a content hash of the original ordered distribution legs
provides a reproducible integrity check. No client-side financial calculation occurs.

The analysis view has a searchable real-company picker with an explicit placeholder.
Existing single-company selection carries over; an empty selection asks for a real company,
and multiple selected companies are never silently reduced to the first. The price plot and
rolling multiple plot share x coordinates, pointer cursor and native range keyboard control.
Units/legends/readout stay nearby; EPS/BPS identity changes have vertical event marks.
A successful explicit analysis scrolls to the paired plots; a nearby “분석 조건으로” link
returns to the selector. The selected-date ledger includes actual denominator value, financial period, known/ready
dates, window counts and an exact evidence action. Separate timeline assumptions default to
PBR2/4/6/8/10 and PER10/15/20/25/30; these are editable user scenarios, never forecasts.
Existing top-level navigation/financial detail/2–4-company comparison remain. Advanced
price metrics, conditions and legacy fixed-day bands stay accessible in a collapsed section;
the analysis result is outside and before it.

Explicit timeline RESULT saves use the existing append-only price journal schema and
capture the complete result/definition/parameters. Reopen verifies original pins and
returns the stored result without re-running a newer definition. Original query/screen/bands
save and export formats are unchanged; legacy financial and price journals are not migrated.
Evidence contexts retain the existing bounded16-session behavior; expired contexts require
reopening/re-querying the same saved result.

## Verification and preservation

Writer focused checks: 48 Python tests (timeline, publication, existing metrics),21 Node
worksheet tests, Ruff and JavaScript syntax passed. Tests cover full252/no-future/negative/
missing/unready history, unchanged3y definition, custom/nonpositive bands, old/new private
journal reopen, cursor sync, missing ribbons, explicit selection and stale requests.
Actual pinned MSFT/AAPL/COST/NVDA × PER/BPS eight requests and eight private RESULT
save/reopen-after-service-restart checks passed. MSFT BPS has754 valid ratio days and503
eligible252-session distribution points; the other seven tested routes have no eligible
ribbon. Payloads with five multiples were5.55–6.40MB, cold local computation0.88–1.36s;
these observations are not a speed claim. Evidence receipt is local
`work/price-band-timeseries-20261116/evidence/writer-actual-readonly-validation.json`.
Worker response cap remains32MiB. Actual preview exposed the bridge's original base64
regex throwing a stack overflow on5MB+ replies. A bounded linear ASCII/padding/decoded-size
validator replaces it for the shared history/price worker protocol; regression tests cover
5MiB payloads, malformed interior/padding, exact32MiB and32MiB+1 decoded body. Existing
protocol/size boundaries remain unchanged. The existing history lifecycle suite also passed13
checks with loopback permission; its first sandboxed run failed on environment socket/child
restrictions, not a passing result. Lead private Windows18892 preview confirmed actual MSFT754points/503eligible252s points,
latest523.88USD/BPS63.35/ratio8.27/P50 8.10 and no API/browser errors after the transport fix.
The writer inspected the actual1920 chart capture; the final navigation polish scrolls only
a successful current explicit timeline request into its analysis heading, with a nearby
return link to conditions. Stale responses cannot scroll. Axis text adapts at large desktop
widths while retaining16px SVG text at smaller desktop widths. Final1920×1080/1440×900
visual acceptance, private-journal checks and operating activation remain lead-owned
separate evidence.

Reproduce from the isolated source with root virtualenv and explicit source import path:

```bash
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m pytest -q tests/screening/test_price_timeline.py tests/screening/test_price_metric_publication.py tests/screening/test_price_related_metrics.py
node tests/screening/screening_price_metrics.test.cjs
node --check examples/screening/display-assets/app.js
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m ruff check src/sec_xbrl/metrics/price_timeline.py src/sec_xbrl/metrics/price_related.py src/sec_xbrl/screening/price_metric_service.py examples/screening/price_metrics_worker.py tests/screening/test_price_timeline.py
git diff --check
```

Original109 financial/backend19078, qualifiedd1e/native14,14datasets, prior legacy+price
journals, and older published sources are preserved. This change does not restart or activate
an operating runtime. Historical meaning, cross-company equivalence and raw source scope
remain governed by the [analytical model](../architecture/analytical-data-model.md),
[price contract](price-related-metrics-20261116.md) and
[company-readiness contract](company-valuation-readiness-20261116.md).


## Independent finding correction — distribution identity

The initial frozen candidate `4d288152d7ae6b708f5ecd2fcd8209dfe6cf80f5` was not accepted:
independent review found that new252-session distribution identities omitted company,
security and metric. Empty same-day windows could consequently share an observation ID
across companies or PER/BPS. The correction includes explicit `cik`, `security_id` and
`metric_id` in the output before hashing. Numerical, window, readiness and original3y
policies remain unchanged. Regression covers two companies × two metrics with empty
same-day windows, an additional security scope, distinct IDs across scopes and deterministic
same-request output. The corrected candidate requires a new frozen SHA and independent
review; no runtime acceptance or main delivery is inferred from this correction.

Correction checks:49 focused Python tests,21 worksheet Node tests, Ruff, app JavaScript
syntax and diff checks passed. The earlier13 history checks were not repeated because this
correction changes only distribution identity, its regression and this contract.


## Final independent, local and operating acceptance — 2026-11-16

ROOT accepted product **`183a55506b0c1f6e3f4d1a3eb212099de112d7ae`** locally and in the
operating consumer at `2026-11-16T08:08:06.891Z`, after separate read-only Astra PASS.
This final update changes documentation only; product source/tests remain byte-identical
to that accepted product. Earlier pending statements and the failed4d identity review above
are historical stages, superseded by this dated evidence rather than erased.

Evidence locators (local immutable receipts, not prerequisites for understanding the contract):

- `work/price-band-timeseries-20261116/evidence/root-final-acceptance.json`, SHA256
  `6da0bc52bc7405c4b2e65d5dd0d39e64ece98a5905b6d30482d157f069b04536`.
- `work/price-band-timeseries-20261116/evidence/independent-183a.md`, SHA256
  `16df07d66fb33cd56fe48bc060c62e2de676e3ec755df2436d83c5c2fe211cc3`.

The independent reviewer reran49 focused Python,21 price Node and13 history Node tests,
Ruff, JavaScript syntax, diff checks and actual pinned-source probes: all PASS. The reviewer
confirmed distinct deterministic scoped distribution IDs, unchanged numerical/window/3y
rules, exact1-year suffix of3-year data, cache-source validation and original snapshot reopen.
This is focused verification, not a full repository suite or financial/native14 requalification.

ROOT verified the actual Windows transport and1920×1080/1440×900 paired plots/cursors,
keyboard/date readout and evidence with no browser/API errors. At1440 the measured actual
axis font was13.568px. MSFT BPS has754 ratio points and503 eligible252-session distributions;
latest actual close523.88USD/share, BPS63.35USD/share, ratio8.27 and P50 8.10. AAPL PER has9
eligible ratio days, NVDA BPS remains unavailable, READY_ONLY masks unconfirmed history,
and the original3y option remains separate. These are data availability observations, not
expanded qualification, investment guidance or fabricated ribbon coverage.

Private journal clones preserved all five original SQL records exactly, including payloads,
notes and definitions. One explicitly saved timeline made six records, all preserved across
an actual cold restart; its reopened export bytes were identical (SHA256
`5be7983e2313e0f87d1f569c342e8aaf2521bfc8553d2f166c274d95a6ddfa25`).
Operating journals received **zero test saves** and contain zero price user-save records;
legacy trash remains8. Both journals have `integrity=ok` and exact original tables.

Operating consumer:18765, PID60604, immutable price source archive
`work/price-band-timeseries-20261116/accepted-source-183a55506b`. Windows assets/bridge:
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/price-band-timeseries-20261116/candidate-183a55506b`.
Rollback command is that candidate directory's `rollback.json`. The original financial
source/backend19078, qualifiedd1e/native14,14datasets,109financial rows and2834price
observations remain exactly the baseline. All555protected-file hashes are unchanged;
Raw, financial bindings, publications and prior journal history were not rewritten.

ROOT performed activation and final read-only acceptance; the writer only records its receipt.
No push, PR, remote CI or main merge was performed or requested. Main remains
`75ac14efb8`. Any later remote delivery requires a separate authorized decision; this local
and operating acceptance does not imply main delivery. The final documentation commit is
separately frozen for read-only verification of this status and unchanged product bytes.


## Static ledger CSS refinement — 2026-11-16, pending revalidation

The accepted product183a and final documentation95735429e8 above describe their exact
accepted states. A later actual operating chart capture exposed global sidebar styles
(`aside` height100vh/stacking/overflow) leaking into the static timeline readout, stretching
the paired-chart layout to1096px despite roughly760px of actual content. This small CSS
refinement explicitly resets readout height:auto, max-height:none, min-height:0,
z-index:auto and overflow:visible. Numerical rules, source inputs, journals and product
calculation logic are unchanged. A focused CSS regression asserts the static-ledger resets;
actual1920/1440browser geometry and unchanged cursor/evidence behavior require ROOT's
independent revalidation before the refinement gains local/operating acceptance. Writer
performs no runtime activation. The prior accepted183a runtime remains the baseline until
ROOT explicitly adopts this new frozen candidate.

Refinement checks:22 price Node tests, app JavaScript syntax and diff checks passed.
Python/Ruff were not repeated because no Python or numerical source changed.


## Refined final independent, local and operating acceptance — 2026-11-16

The final product is **`aabadc222e7149ec177a47b92f9de0ad5e99b04e`**. Separate read-only
Astra verification and ROOT local/operating acceptance passed at
`2026-11-16T08:17:57.959Z`. This supersedes the preceding CSS-refinement pending state;
183a/957 acceptance and earlier pending records remain accurate historical stages.
The present final status update is documentation only, with no further product/test edits.

- Final receipt: `work/price-band-timeseries-20261116/evidence/root-refined-final-acceptance.json`,
  SHA256 `753e059c69f5b1e37a9256b0b8b4927643d4b7d7592c4d135f26cda87607a0ce`.
- Final independent report: `work/price-band-timeseries-20261116/evidence/independent-aabadc.md`,
  SHA256 `85c98dded1749be1a8ad264a0299324943818bd260d8db3349a661ac451e1418`.

The accepted source evidence covers49 Python,22 price Node and13 history Node PASS.
All Python calculation code, worker, bridge and app JavaScript remain byte-identical to
accepted183a. The static readout resets now pass actual geometry checks: at1920×1080,
readout781.94px/layout797.94px; at1440×900, readout628px/layout644px. Static positioning,
auto stacking, visible overflow and no maximum-height restriction prevent the inherited
drawer height/z-order defect. Actual operating browser/API and shared cursor/evidence
checks pass without errors. The earlier private five-original-plus-one-explicit-save,
actual cold restart and identical export receipt remains valid because those paths and
calculation bytes are unchanged (receipt SHA256 `6da0bc52bc7405c4b2e65d5dd0d39e64ece98a5905b6d30482d157f069b04536`).

Operating18765 now uses PID36476 and immutable archive
`work/price-band-timeseries-20261116/accepted-source-aabadc222e`. Its Windows bundle and
rollback command are under
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/price-band-timeseries-20261116/candidate-aabadc222e`;
`rollback.json` returns to the preceding accepted183a operating configuration.
ROOT performed activation; the writer records the verified receipt only.

Final operating checks preserve109financial rows,14datasets and2834price observations
exactly,555protected-file hashes, both prior journals and trash8. There were zero operating
test saves and zero price user-save records. The original financial source/backend19078,
qualifiedd1e/native14, source publication and accounting/readiness boundaries remain intact.
MSFT BPS754points/503eligible252-session distributions and previously documented gap
behavior are unchanged. No remote push, PR, CI or main merge occurred; main remains
`75ac14efb8`. Final documentation verification may use content/link/diff/source-equality
checks under delivery-workflow section0 without repeating unchanged product tests.


## Authorized remote delivery and PR107 integration — 2026-11-16

The user now authorizes pushing the timeline improvement and creating a PR after checking
latest main and preserving existing functionality, data and history. Earlier “remote not
requested/not authorized” records describe their historical stages and do not override this
new authorization. ROOT owns push, PR and CI decisions. The sole implementation writer
remains the disclosed approved GPT-6.1 Sol fallback; a separate Astra independently reviews
the new frozen SHA. **Main merge, force-push/history rewrite, further runtime activation,
Raw/network work, dataset regeneration and republication are not authorized.**

ROOT fetched `origin/main` at **`b8a2088e171a832e63223ddd4906ea430e57145d`**, merged PR107
(direct reported-quarter EPS TTM). The writer performed a normal merge into existing
`codex/price-band-timeseries` from timeline documentation head
`0c982867cb3ea6ed51d062628a878c3f0e97e43b`; no rebase or history replacement occurred.
The original main checkout and its17untracked architecture artifacts remain untouched.

| New delivery gate | State |
| --- | --- |
| User authorization | Push/PR approved; main merge/runtime changes excluded |
| Local integration | Implemented and writer-checked; exact merge commit supplied at freeze |
| Independent integrated-source verification | Pending on new frozen SHA; prior acceptances are comparison evidence only |
| Integrated local acceptance | Pending ROOT judgment after independent review |
| Operating state | Existing separately accepted local runtime5c37 remains unchanged; no restart by writer |
| Remote push / PR / required CI | Pending ROOT execution and actual receipts |
| Timeline main merge | Not performed or authorized; PR107 itself is already in the fetched main |

### Scope resolution and preserved boundaries

Conflicts were limited to planning append records, the shared fixed-band refactor and
appended Node tests. Both planning histories and both test groups are retained. Main's
`current_eps_evaluation`, `historical_ready=false`, `backtest_eligible=false` and
`eps_diagnostic` propagate through `fixed_multiple_bands_for_ratio` only when the base
observation carries the corresponding context. This preserves current EPS fixed-band
provenance and HON's reviewed basis hold. Historical timelines still read the pinned
`historical` rows; they never gain current-evaluation flags or an exemption from the
original price-date readiness guard. No FY replay, current denominator replay, new scope
approval or historical backfill is introduced.

Main's new reported-quarter EPS module, financial bindings/readiness checks and
`price_metric_publication.py` are preserved unchanged. UI source-context/reopen/export
changes retain main's evaluation16/quote13 distinction alongside timeline controls.
Existing252-session/3y definitions, company/security/metric identity, typed lineage,
READY_ONLY gaps, bounded cache, original saves/exports, large-base64 transport,
static-ledger geometry and other financial/Q4/common-market views remain intact.

All product files under `src/` and `examples/` compare byte-identical to the separately
accepted combined runtime **`5c37c0896169f29083ec8a1825c8e5f4e29e329c`**, whose read-only
source is `work/reported-quarter-eps-ttm-20261116/runtime-source-integration-v1`.
That includes the seven timeline product files and all main EPS product changes. Of the
two related timeline test files, the Node file differs only in placement of main's retained
two EPS tests; Python carries the runtime's current-vs-historical regression and adds HON
band diagnostic assertions. This comparison is evidence, not a fresh accounting approval
or automatic inheritance of runtime acceptance to a new source SHA.

### Current actual pinned data and private checks

Use the existing publication, without rewriting it:
`data/processed/price_metrics/20261116_direct_quarter_eps_ttm_v1/price_metric_manifest.json`,
SHA256 **`86fad784c394f29465df8f07501e0ee5b32e24863a9a6b2bac514d2040bdce2d`**.
Its109×26 observations are2834rows:1335available/1499unavailable. Current PER/EY12 includes
reviewed MSFT EPS19.16, NVDA7.91 and ABBV5.81; HON remains a per-share-basis hold.
Evaluation date16, quote/public-information cutoff13 and actual preparation date16 remain
separate. Current availability never certifies historical preparation.

Writer read-only/private probes compared the same publication across fetched main,
accepted runtime and merged source. All2834latest rows and four current band results
(MSFT/NVDA/ABBV/HON) matched exactly. Five timelines (those four PER routes and MSFT BPS)
matched the accepted runtime exactly. Current TTM13th-session PER/bands remain null,
linked denominators retain ready16, and historical ratio rows contain no current-EPS
context. MSFT BPS retains754points/503eligible252-session distributions and the same P50.
A private temporary journal reopened both old977-publication and new86-publication
snapshots exactly after service restart; original notes/source context were retained.
No operating journal writes or test saves were made. The probe's first assertion looked
for `ready_on` on a compact ratio rather than its linked denominator; correcting that
probe field location passed without changing product code.

Local probe receipt:
`work/price-band-timeseries-20261116/evidence/writer-main107-integration-probe.json`,
SHA256 `7a6dab213630b47ee5271cf63338d40c19a80425749ea47dc375f83029149682`. ROOT separately owns actual HTTP/runtime-preservation
checks, current journal/pin inventories and any remote delivery decision.

### Integration validation and handoff

Writer checks: **158Python PASS/1SKIP**,24price Node +5common-market Node +6Q4 Node
+13history Node = **48Node PASS**, Ruff, app/Node-test syntax and diff checks PASS.
The skipped test is the opt-in private cached producer fixture; its cached inputs were not
reprepared here. Actual pinned consumer comparisons above passed separately. History
checks used narrowly approved local loopback/fixture-child permission. No full repository
suite, repeated Raw capture, fresh corpus qualification or remote CI result is claimed.

Relevant reproduction, from the isolated tree with its `src` on `PYTHONPATH`:

```bash
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m pytest -q tests/screening/test_price_timeline.py tests/screening/test_price_metric_publication.py tests/screening/test_price_related_metrics.py tests/screening/test_reported_quarter_eps.py tests/screening/test_price_capture_evidence.py tests/screening/test_market_inputs.py tests/screening/test_market_input_profile.py tests/screening/test_market_input_assessment.py tests/screening/test_company_valuation_readiness.py tests/screening/test_company_valuation_fresh_preparation.py tests/screening/test_company_valuation_bindings.py
node tests/screening/screening_price_metrics.test.cjs
node tests/screening/screening_market_inputs.test.cjs
node tests/screening/screening_revenue_q4_continuity.test.cjs
node tests/screening/screening_history_lifecycle.test.cjs
git diff 5c37c0896169f29083ec8a1825c8e5f4e29e329c -- src examples
git diff --check
```

Only tracked implementation/tests/contracts belong in the merge commit; generated data,
local receipts, journals, archives and secrets remain outside it. The writer freezes the
normal merge SHA and stops for independent review. ROOT performs authorized push/PR and
reports actual required-CI status; this document does not infer those actions occurred.
