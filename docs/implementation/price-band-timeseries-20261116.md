# Price bands and rolling distributions — 2026-11-16

## Authorization, scope and status

The user approved implementation of the reviewed V3 temporal price analysis on actual
companies, preservation of existing functionality/data/history, and actual UI verification.
This contract records the lead's accepted implementation decisions. It supersedes the
mockup's proposed default 3-year distribution window with the explicitly approved new
252-session definition below. Synthetic mockup data is never a product data mode.

Baseline: main `75ac14efb8` (PR106), isolated branch `codex/price-band-timeseries`,
worktree `work/price-band-timeseries-20261116/source`. No push/PR/main merge is authorized
by this milestone. The lead owns runtime staging/activation, accounting judgment and
acceptance. One implementation writer uses GPT-6.1 Sol because the written GPT-5.6 Sol
default is unavailable; that disclosed fallback was approved. A separate Astra performs
read-only independent verification after the writer freezes a local commit, following
[delivery workflow](delivery-workflow.md).

| State | Evidence |
| --- | --- |
| PROPOSED | Reviewed V3 mockup: price/fixed bands above actual multiple/rolling quantiles |
| APPROVED | User implementation authorization; lead's 252-session/3-year and preservation decisions |
| IMPLEMENTED | Candidate source on the isolated branch; final frozen SHA supplied at handoff |
| INDEPENDENTLY_VERIFIED | Pending separate verifier on frozen SHA |
| LOCALLY_ACCEPTED | Pending lead judgment |
| RUNTIME_ACCEPTED | Pending lead's private/operating API and browser verification |
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
