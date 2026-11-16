# Price-related metrics — execution contract, 2026-11-16

**Latest local delivery state (2026-11-16):** H5 at source
`8e97971d3c253833913edac68fd5705cc0d3f805` has separate helper, fresh-data and
operating-evidence independent PASS plus ROOT local/bounded-live acceptance.
Original PR103 is MERGED in main`b9126a262ce561a45e14ee1bb33f872d36079bee`,
and both original PR/main CI runs succeeded. This H5 follow-up's remote PR,
required CI and main merge are still NOT_PERFORMED at this documentation freeze.
Whole-GOAL completion is not claimed. Earlier preparation/candidate/permission/
PR-pending records below are historical stages superseded by the dated H5 table.

**Frozen-source acceptance record (2026-11-16, before H5 follow-up approval):** all requested families are IMPLEMENTED at
`67cc011c269d023a32c51c8fe10e24b7c2f43a8f`; separate Sol verification PASS;
ROOT LOCALLY_ACCEPTED and LIVE operating acceptance for the frozen source/data
are complete. H5 fresh capture permission, PR, required CI`test` and main merge
remain PENDING. The GOAL is not complete. Earlier pending and FAIL records below
retain their original stage; the final acceptance section records the current state.

## Authority and status

The user has explicitly authorized H0–H5 implementation, tests, separate read-only
verification, operational activation, push/PR/required CI and main merge. This
supersedes the document-only status of the [handoff](../planning/price-related-metrics-goal-handoff-20261116.md).
Lead acceptance, independent verification, operating acceptance and main merge
remain separate. Base: `30d23ef4d2`; branch: `codex/price-related-metrics-goal`.
There is one implementation writer (available Sol); the lead owns accounting
judgment and activation. Existing Raw, publications, journal and Q4 UI are preserved.

## Scope and acceptance

Implement a versioned registry and explicit input lineage for 1/5/21/63/126/252
US-session split-adjusted price returns; 20/60/252 annualized volatility;
latest completed/previous20 relative volume; common market capitalization, PER,
PBR, P/S, earnings yield, standardized FCF yield, EV/Revenue and EV/EBITDA;
user-selected fixed PER/PBR bands and separately named rolling three-year
historical multiple percentiles. Publish immutable additive outputs and serve
screening, comparison, daily time series and bands through one query contract.
Explicit saves pin publication, definition versions, condition and result;
reopening must reject tampering and preserve prior records.

Acceptance requires numerical and failure-path tests, batch supplier call-count
checks, source/publication tamper checks, async/missing/save UI checks, representative
real-input evidence, independent verification and lead operating/main acceptance.
A whole unimplemented family cannot be disguised as unavailable input.
Issuer-specific unavailable outputs retain typed reasons and attempted input IDs.
DCF, feeds, trading and large universe expansion are excluded.

## Approved calculation contract

* US sessions are an explicit, verified source list; no weekday inference, observed
  row shifts, price union calendars, fill or skipping gaps. Every window is complete.
* Returns: `100*(split_adj_close[t]/split_adj_close[t-N]-1)`; price returns,
  excluding dividends. Volatility: sample standard deviation (`ddof=1`) of N
  log returns times `sqrt(252)*100`; N+1 strictly positive closes required.
* Relative volume: latest completed session true-split-compatible volume / mean
  of the preceding20 sessions, excluding current. Zero prior mean is unavailable.
* Daily price as-of grain is separate from fiscal financial periods. Prices are
  never attached to FY labels. All output retains requested and actual price dates.
* PER uses directly reported approved diluted12m EPS or the already governed
  direct-QTD TTM; no FY−9m EPS subtraction. EPS<=0 blocks PER, while earnings
  yield preserves meaningful zero/negative EPS.
* Common market cap requires actual outstanding common ex-treasury shares,
  explicit class/security scope, matching currency and split basis. WAVG, issued,
  free-float and ticker identity are not sufficient. PBR common-cap/common-equity
  and price/BPS routes remain distinct. P/S requires issuer/common scope approval.
* Financial values must be known on the requested date, have exact monetary/unit
  scope and retain selected/raw source IDs. Missing currency/class/basis/evidenced
  zeros never become assumed USD, default common class or zero.
* Standardized FCF retains existing CFO−PPE acquisition definition, never FCFE.
* Historical distributions use point-in-time denominators; current EPS is never
  replayed through history. Historical readiness remains explicit.

## Accepted EV and denominator policy

The user accepted the proposed EV policy on2026-11-16, with definitions retained
for inspection. This is a selected governed policy, not a universal accounting
standard. EV = common market cap + interest-bearing debt (finance leases included
exactly once, operating leases excluded) + explicit preferred equity + explicit
NCI − cash and cash equivalents. Missing components never become0. Every
financing component declares reported carrying value, observed market value, or
an explicitly reviewed book-capital reconciliation residual0; these bases are
not silently equivalent. Preserve actual component dates and reporting precision.

The implemented operating denominator is **영업이익+D&A / operating EBITDA proxy**:
operating income plus reported D&A expense evidenced as included in that operating
income for the exact same period/scope. It is not reported EBITDA or conventional
net-income-based EBITDA. A CFO addback, a tag with “and other”, or finance-ROU
amortization already in depreciation cannot be added again. See the SEC's
[non-GAAP C&DI103.01/103.02](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/non-gaap-financial-measures)
and [CFA price/EV multiple discussion](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples).
The registry, UI and saved evidence retain the proxy route and financing basis.

## Exact representative accounting grants

These grants are explicit data/evidence records, never ticker branches in the
engine. The lead reviewed the selected IDs, underlying complete statements and
notes; each binding must exactly equal the approved pinned proposal.

* MSFT, CIK0000789019, securityUS:MSFT, CommonStockMember, FY2025-07-01–2026-07-01
  exclusive end, filed2026-07-29: diluted EPS17.95, actual outstanding common
  ex-treasury shares7,427,000,000, common equity442,387,000,000,
  revenue331,839,000,000, standardized FCF66,987,000,000
  (=CFO182,935,000,000−PPE acquisition115,948,000,000).
* Debt40,294,000,000 already includes current9,227,000,000 and
  noncurrent31,067,000,000. Finance lease66,594,000,000 is separately in other
  liabilities, giving chosen interest debt106,888,000,000 once. Cash20,935,000,000.
* Preferred/NCI0 are **reviewed complete book-capital reconciliation residuals**
  at million-USD reporting precision, not reported-zero tags or absent-row fill:
  assets758,376m−liabilities315,989m=equity442,387m; common/APIC117,406m
  +retained328,265m−AOCI3,284m=the same442,387m, supported by common-only
  capital rollforward. This permission applies only to this exact scope.
* Operating income155,237,000,000 + depreciation34,300,000,000 + intangible
  amortization4,700,000,000 = proxy194,237,000,000. Do not use the CFO
  “depreciation, amortization and other”38,534,000,000, or add finance-ROU
  amortization5,403,000,000 again.
* Thirteen separate historical capital instants2023-07-01 through2026-07-01
  bind actual common shares and common equity/BPS only. Each exact source
  independently reconciles both capital equations above. Its filed date is the
  knowledge boundary, and the grant expires when a newer financial anchor is
  known. Install the full FY2026 grant once, rather than a competing duplicate.
  No historical EPS/EV scope or historical-ready time is inferred from this grant.

No grant applies before knowledge, after a replaced financial anchor, to another
currency/class/split basis, or to a price with a factor different from the approved1.
The USD capture sidecar and original supplier price/security hashes must agree.
Class identity alone is never EPS approval. Latest direct12m EPS must match the
latest known financial end; retained old FY EPS cannot fill a current interim gap.
Raw exclusive endpoints are retained, while the displayed measurement day is
end−1day. Historical system readiness is unknown, never copied from filed_date.

Optional evidence receipts live under `work/price-related-metrics-20261116/evidence`:
current proposal996f061b / ROOT receipt734d1309; historical proposal92d5a4fd /
ROOT receipt14e66070. The exact normative scope above remains understandable
without that working directory. All48 typed inputs reference the selected/raw
Fact IDs and the exact declarations; no financial/Raw panel was rebuilt.

## Calendar, supplier and refresh boundary

The supplier0.5.1 CanonicalQuery and contract1.1.1 remain authoritative for prices;
it does **not** provide an official session calendar, incremental update API,
class/EPS approval, or historical-ready ledger. One shared offline query returned
107,583 price rows for109 exact registered securities for2022-10-01–2026-10-23.
The input is frozen, requested display day2026-11-16, actual selected quote10/23,
24calendar-day difference; neither current-price nor automatic-update claim.

The standalone calendar producer uses exchange_calendars4.13.2/XNYS and pins its
module/script plus lead calendar-review receipt. Its1035 explicit modeled sessions
cover2022-10-01–2026-11-16. Lead review checked the official2026holidays,
2025-01-09 extraordinary closure, retained early-close sessions and open bank
holidays. This is a reviewed calendar model, not exchange certification. Sources:
[NYSE hours](https://www.nyse.com/trade/hours-calendars),
[2026 calendar](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf),
[2025-01-09 closure](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx).
A security-specific missing bar does not remove a required market session.

The provider's small132-security capture sidecar binds exact price/security hashes
and USD numeric-normalization evidence. Capture-level metadata is not historical
per-date currency/class proof, historical-ready time, or a new quote capture.
One successful adoption verification and one price-batch read are reused for all
metrics; one initial project-runtime adoption attempt failed because PyArrow was
absent, before any price query, and is not counted as successful. Supplier-runtime
export then succeeded. No packages or supplier sources were changed.

A new source version must be explicitly verified/adopted into a new immutable
batch/publication. Price refresh can proceed independently; financial ratios for
a quote after the qualified financial cutoff return
`FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF` until a newly qualified financial state is
available. The old fixed-source financial approval never admits later filings.

## Historical policy and pending external acceptance

The implemented distribution engine supports PER, both PBR routes, P/S,
EV/Revenue and EV/operating proxy, separately from user fixed bands. It uses the
trailing3calendar-year verified session bounds and actual point-in-time inputs,
linear interpolation for10/25/50/75/90percentiles, complete intended calendar/source
coverage and at least252 eligible sessions. Valid/expected/missing counts and
partial coverage are explicit. Historical-ready qualification requires both
financial and price ready evidence; neither capture time nor public filing date
certifies it. Insufficient direct EPS samples remain insufficient.

The user explicitly approved the point-in-time evidence policy on2026-11-16.
`DIAGNOSTIC_FILED_DAY` is now authorized with the separate policy receipt
47a3ad90: use actual filed-day knowledge, exact historical grants and direct EPS,
retain unknown historical ready time and always `backtest_eligible=false`.
`READY_ONLY` remains available and distinct. Filed-day lag0 is a diagnostic
knowledge assumption, not proof a filing was ready before that day's close.
The additive final diagnostic publication preserves previous strict/development
publications. A fresh bounded provider
capture was rejected by automatic approval review and awaits explicit permission;
no indirect capture or new-network workaround was used. Offline immutable replay
is not live-refresh acceptance. H5 fresh-source acceptance remains pending.

## Implementation seam

One producer accepts a shared canonical batch and evidence-bound financial input
bundle and materializes all definitions and results. A separate immutable reader
queries those prepared values; consumers do no accounting arithmetic. This keeps
session, unit, class and denominator policy local and testable. Reusing the old
financial FY registry directly is a viable alternative, but would conflate daily
price grain with financial periods and alter old journal/publication semantics.
The additive publication therefore earns a dedicated adapter, while its UI reuses
the existing investor worksheet tokens, controls and source scope.

## Storage, queries and explicit saves

The shared batch retains price rows once. Long derived rows refer to it by source
key and exact session bounds/ordered-input-ID digest. Per-company/mode Parquet
payloads preserve exact JSON decimals/lineage while compressing repeated metadata;
latest queries never parse daily history. The108 issuers without approved
financial bindings retain typed unavailable intervals with verified expected
session counts. Missing intervals are queryable and visible; no interpolation.

The common reader serves latest screening (including two-sided bounds on the same
metric), multi-company comparison, daily series, fixed user bands and evidence.
The existing company/profile entry transfers the selected CIK only when financial
publication scope matches; the main investor task and Q4/revenue views remain.
Definitions and source pins are under explicit evidence expansion.

A **separate** `price_metric_saves` SQLite journal records only explicit condition
or result saves, notes, exact requests/results, publication/source pins and all
metric-definition versions. Preview/opening a view never saves. A saved condition
reopens a read-only preview under its original reader even if the active publication
changes. Saved results reopen exact prior bytes after pin verification; retained
old reads do not require current producer source hashes. New band computations
require matching declared definitions. Old screening journal/publications are
never migrated, restored, replaced or appended by the price service.

## Reproduction, staging and verification

Use `examples/screening/export_canonical_price_batch.py` in the existing supplier
runtime (stdlib+official SDK only), `prepare_price_sessions.py` in the existing
calendar runtime (stdlib+exchange_calendars), then `prepare_price_metrics.py` in
project Python3.12 for projection, approved exact binding and publishing. Every
output destination is create-only. Existing normalized inputs and batch are reused;
no repeated financial/company audits or raw price capture.

Focused source verification:

```bash
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python -m pytest \
  tests/screening/test_price_related_metrics.py tests/screening/test_price_metric_publication.py \
  tests/screening/test_screening_bridge.py tests/screening/test_market_inputs.py \
  tests/screening/test_market_input_profile.py -q
node tests/screening/screening_price_metrics.test.cjs
node tests/screening/screening_market_inputs.test.cjs
node tests/screening/screening_revenue_q4_continuity.test.cjs
```

Focused Python65PASS; new Node6PASS, existing market/Q4 Node source checks PASS;
Ruff and JavaScript syntax PASS. Actual browser/independent verdicts were pending at that initial self-check
handoff; the final dated acceptance below supersedes that stage.
The initial JSON real publication is a **development numeric smoke only**, not a
runtime candidate; a compact final artifact must come from frozen source and pass
independent review. Full remote CI remains separate; required context is `test`.

`examples/screening/stage_price_metrics_runtime.py` prepares a clone of the
**currently observed** live bundle and overlays only changed app.js/app.css/bridge.
Supply the verified final publication, a new destination under the current writable
Windows visualization root, separate private/live price journals and a new private
legacy-journal backup destination. It emits `private-start.json`, `live-start.json`,
`rollback.json` and `start-runtime.cjs`; it starts/stops nothing. Private default
port18887 must first be checked free. Original backend19078, qualified financial
source, every Q4/market/profile/auxiliary pin and existing history worker stay exact.
The private history worker uses a coherent SQLite backup of the current old journal;
the qualified backend19078 still owns the **real** legacy journal. This is not a
cloned legacy backend. Root's browser harness must reject every mutation except
`/api/price-metrics/*`, whose private worker uses its dedicated private price
journal. Live configuration retains the current original journal. Root owns actual preview,
process identification, activation, preservation comparison and rollback.

Run an emitted command on Windows only after review, for example with the existing
Windows Node executable: `node start-runtime.cjs private-start.json`. For live
activation Root identifies/stops only the actual current frontend, runs the reviewed
live config, checks all14 prior datasets/Q4/history plus new price operations, and
compares preservation metadata. Rollback restarts the exact observed original
frontend command; it never restores an old journal or publication file.

## Delivery status

Source implementation and focused self-checks exist. The compact diagnostic
publication is materialized at
`data/processed/price_metrics/20261116_common109_diagnostic_v3/price_metric_manifest.json`,
SHA256`1fc3fcfaf96ec6960ac2f8f778ba280bdad001bb9b9e8eb19ec8b470394c400a`,
publication`screening-price-metrics-c267c806a18e973734393915`.
It contains109registered issuers,1,079available/1,755unavailable latest outputs;
28registered definitions include fixed bands, which are separately materialized.
MSFT has all10valuation outputs; source10/23 close524.510009765625 gives
PER29.2206133574, PBR8.80571952279, P/S11.7392345159,
EV/Revenue11.9982547034 and EV/operating-proxy20.4980968741.
All independent price families also have actual MSFT observations and the109
security-specific missing rows remain typed.

The real historical PBR diagnostic has754/754eligible verified sessions,
2023-10-23–2026-10-23, P10/P25/P50/P75/P90=
7.5253225478/9.0393392370/10.9669565906/11.8821525546/12.8320406896.
The scalar value is explicitly **median(P50)**, not a current multiple or
percentile rank; distributions/user scenarios are excluded from screening scalars.
Historical PER/P/S/EV have62eligible sessions and remain unavailable below252;
no oldFY EPS is substituted. Diagnostic rows remain backtest-ineligible with
historical ready unknown. The separate BPS route retains its own definition.

The31,077,656-byte compact artifact took64.4seconds to materialize in the measured
local run; peak RSS561,464KiB includes the shared decoded batch. All109 latest
queries over4metrics took0.085/0.086seconds in two measured calls, without reading
daily history. Earlier strictv2 and developmentv1 stay immutable, unactivated.
The single shared batch SHA256 is`d9cd120497a9626de9a1a111525b0b69c43b0d09a6000d3ee555d895ed1a4cad`.

Create-only staging completed under the current Windows visualization root's
`price-metrics-v3-stage`: original livebundle cloned,3changed assets overlaid;
private/live/rollback configs emitted, no process started or stopped. Private
port18887 and separate pricejournal are prepared; original backend19078 and all
old pins remain in the configs. Root's legacy-backend mutation restriction above
still applies. Staging receipt and commands are review artifacts, not activation.

At this artifact handoff, source freeze, independent verification and actual
UI/local/operating acceptance were still pending; their completed states are
recorded separately in the final acceptance below. PR/CI/main and H5 fresh capture
permission remain pending. No whole-goal complete claim.

## Evidence correction after independent FAIL — 2026-11-16

The separate Sol review of frozen`16931be929` found two release-blocking evidence
paths: arbitrary user band IDs were absent from stored publication files, and
saved-A evidence was incorrectly routed through active-readerB. Numeric engines,
all545v3files, all10actual MSFT valuations, all price families and point-in-time
historical arithmetic passed that review. No live activation followed the FAIL.

The correction is limited to the existing reader/service/UI/test seam. Results
now receive an opaque backend-owned evidence context. It binds the original
verified reader and permitted observation IDs; the bounded16-context cache stores
only backend-computed or hash-verified saved scenario rows. The client cannot
submit a calculated value, source path, publication pin or arbitrary row as evidence.
Static current-publication evidence retains its original read-only API contract.
Unknown/expired tokens and cross-result IDs reject rather than falling back to
another publication. A result can be reopened/requeried to get a fresh context.

Explicit save payloads retain their exact original numeric/source hashes and
contain no ephemeral context token. Reopening after a service restart verifies
the original publication and save, then mints a new transport context for that
original reader. Definitions/company captions and all evidence stay with the
saved source, even when current publicationB differs. New active queries switch
back explicitly. The UI rejects late evidence from old source/result contexts
and earlier clicks within the same result.

User multiples11.25/2.25 resolve through their exact backend-generated scenario
rows, including their EPS/BPS and exact quoted numerator. Regular valuation
evidence resolves the single price observation ID/date/security through the
shared pinned batch. Historical P50 evidence resolves its actual daily multiple
IDs, their prices and financial inputs. No source values are reconstructed in
the browser. The historical operating-proxy label remains explicit for its exact
v1definition; diagnostic coverage remains distinct from readiness certification.

The v3 publication pin`1fc3fcfa…c400a` is **reused unchanged**. Its producer evidence
remains the original`16931be929` computation; this correction changes no registry,
formula, input policy, source input, daily value, percentile or saved schema.
Reading retained artifacts does not demand that the current reader file hash equal
the old producer hash. New materialization still enforces its own source freeze.
No supplier verification, batch scan, financial rebuild or price calculation was
repeated for the evidence correction.

Correction checks: focused Python69PASS; new price Node9PASS plus existing
market5/Q4sixPASS (20Node checks combined), Ruff/JavaScript syntax/diff PASS.
Real unchanged-v3 custom bands resolve201.9375 and134.0205668506799515282078901306045
with the exact524.510009765625 quote and one approved EPS/BPS input each.
Historical PBR evidence resolves754daily multiples,754quotes and26financial inputs
in a measured0.11seconds. Separate source-A/source-B tests verify original values,
definitions and quote after restart; client mutations, unknown/cross-result
contexts and source tampering reject. Saved band evidence also survives an active definition
change while new incompatible band computation correctly rejects. Independent
recheck and corrected actual UI acceptance were pending at the correction handoff;
the final dated acceptance below records their completion. The earlier private
preview was preliminary only; Root stopped its owned private process and
preserved the original journal.

The corrected create-only runtime bundle/configs are under the current Windows
visualization root's `price-metrics-evidence-fix-stage`, with fresh private
legacy/price journal paths under `private-preview-evidence-fix`. The live price
journal remains the dedicated new operating path. The existing v3 artifact and
old backend/financial/Q4/profile pins are reused; staging starts/stops nothing.

## Independent, local and live acceptance — 2026-11-16

The lead accepted the exact frozen implementation and unchanged v3 publication
after separate read-only Sol recheck and actual private/live browser verification.
The writer performed no activation. Keep these delivered states separate:

| State | Target and evidence | Result |
| --- | --- | --- |
| IMPLEMENTED | `67cc011c269d023a32c51c8fe10e24b7c2f43a8f`; all28definitions and all requested metric families | Complete |
| INDEPENDENTLY_VERIFIED | Separate Sol recheck of that SHA:69Python/20Node, Ruff/syntax/diff PASS; original545-file/math/PIT checks reused after unchanged-pin confirmation | PASS |
| LOCALLY_ACCEPTED | ROOT acceptance dated2026-11-16, exact source and v3data | Complete |
| LIVE frozen-source/data acceptance | ROOT switched only frontend18765; actual price/evidence/save/reopen and preserved old consumers checked | Complete |
| H5 new-source capture/refresh | Bounded official AAPL/MSFT fresh capture still awaits user permission after automatic-review rejection | PENDING |
| Remote PR / required CI`test` / main merge | Not performed at this acceptance record | PENDING / PENDING / PENDING |
| Whole GOAL | Fresh-source dependency and remote delivery remain | NOT_COMPLETE |

The independently verified v3 manifest remains
`1fc3fcfaf96ec6960ac2f8f778ba280bdad001bb9b9e8eb19ec8b470394c400a`;
publication`screening-price-metrics-c267c806a18e973734393915`.
The correction recheck report SHA256 is
`e09f67c1fc2b8252f070087a77f3ebbc1996f4d7290ef1039214cb0f478c5959`.
ROOT operating receipt SHA256 is
`f70d199ac7eae8f6185c180e1c9f158916c23d85e7348149d9598d359bd95d81`.
Optional detailed report/receipt locators are
`/tmp/price-metrics-independent-recheck-67cc011.md` and
`work/price-related-metrics-20261116/evidence/root-operating-acceptance.json`.
Their absence does not remove the scope, counts, constraints and acceptance states
recorded here. Existing PR101 fullCI3,118PASS/46SKIP is baseline evidence only,
not a new whole-repository CI result for this implementation.

### Exact availability in the accepted live common query

The109-company universe has2,834latest observations across26latest definitions:
1,079AVAILABLE/1,755UNAVAILABLE. Fixed scenarios are separate from those counts.
All28definitions and every family are implemented. Availability is scoped input
and qualification status, never a substitute for an unimplemented engine.

| Family / metric | Available accepted observations |
| --- | --- |
| Price returns1/5/21sessions |109/109 each |
| Price returns63/126/252sessions |108/109,104/109,101/109 respectively |
| Volatility20/60/252sessions |109/109,108/109,101/109 respectively |
| Latest / previous20 relative volume |109/109 |
| Common market cap, PER, PBR, PBR/BPS, P/S, earnings yield, standardized FCF yield, EV, EV/Revenue, EV/operating EBITDA proxy | Each1/109, exact approved MSFT scope |
| Fixed PER / fixed PBR scenarios | Each3available MSFT scenarios;6default band rows total |
| Historical PBR / historical PBR-by-BPS | Each754/754MSFT sessions under approved filed-day diagnostic policy |
| Historical PER, P/S, EV/Revenue, EV/operating EBITDA proxy | MSFT62/754eligible sessions, below252minimum; unavailable with reason |

For the other108issuers, valuation/common-share/currency/split/issuer-scope
bindings have not been approved. This is a governed applicability limitation;
it is not a finding that the underlying SEC Raw data does not exist. Their
historical missing intervals remain explicit. No company-specific absence is
presented as a missing implementation. Strict session gaps/window lengths remain
visible for the price metrics with less than109available observations.

Historical754-session coverage is a **filed-day point-in-time diagnostic**.
Actual historical system readiness remains unknown and backtest eligibility is
false. The scalar is median(P50); it is not a percentile rank or current multiple.
The accepted quote is2026-10-23 for requested display day2026-11-16,24calendar
days stale; financial cutoff2026-10-25; automatic update=false. Live activation
does not convert those fixed inputs into current prices or complete H5.

### Actual operating scope and preservation

At acceptance, frontend`http://127.0.0.1:18765/` ran NodePID52088, replacing the
observed original frontendPID40460. These are dated process observations, not
future process-identity assumptions. The new price worker uses source`67cc011c26`
and a separate operating price journal. Qualified financial source remains
`d1e74d90c98838431740c0e16408d8b4d2623543`, backend19078. Original financial,
Q4/revenue, market profile and auxiliary asset pins remain unchanged.

All14prior datasets,109companies, history version8 and trash count8 are preserved.
The original journal SHA256 remains
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`.
No original journal restoration/replacement, Raw mutation or financial rebuild
occurred. No synthetic test save was written to the live price journal; live
verification was read-only. Actual explicit saves/reopens/notes were exercised
only in the dedicated private price journal. The private legacy-backend mutation
restriction was enforced; a copied history-worker journal never implied a cloned
backend.

Corrected private18887 (observedPID47296) passed actual custom PER11.25/PBR2.25
evidence and exact quote, two-sided PER conditions, explicit condition plus
band-result and memo saves, original-source reopening/export, and cold-service
restart followed by saved-scenario evidence. ROOT checked four Q4 cases against
the original live view and obtained exact equality. Existing market verification
covered4APIcases and3profiles, fixed-year scope and the shares table.

Post-switch live checks confirmed11selected numeric values,6default bands,
252-session series and unchanged market/history behavior. Layout checks at
1920×1080,1440×900,2560×1440,1280×720,960×600 and390×844 had no horizontal
page overflow. These were effective CSS viewport checks; actual browser zoom
was not tested. The accepted probe setup awaited the requested observation ID,
used the final documented compact Q4 caption, paired the old immutable market
case with a current-session decision-date/status/history snapshot, and supplied
the same-Origin header for manual read-only POSTs.

Detailed private/live evidence and screenshots are under the current Windows
visualization root. The accepted live-activation receipt SHA256 is
`5fc47d6b601f6c9abb84a82b0eccf51f0e49ebf0be289aacef391c49e97e6acc`.
The independent/local/live results above apply to source`67cc011c26`; a later
**documentation-only** acceptance commit preserves all source/test/data bytes and
requires only independent document-delta/code-byte-equality review before remote
delivery. No completed source/data/browser checks are repeated for that commit.

## H5 bounded fresh-capture follow-up — authorized preparation, 2026-11-16

The user subsequently explicitly authorized official fresh capture for **AAPL and
MSFT only**, preserving existing inputs and saved records, and requested H5,
necessary operating verification, documentation and main follow-up. This approval
supersedes the earlier permission-pending state for this exact bounded work.
It does not authorize a new109-company capture, new financial qualification,
accounting-policy changes or replacement of the accepted109-company default.

The follow-up uses `codex/price-metrics-h5-refresh`, based on main
`b9126a262ce561a45e14ee1bb33f872d36079bee` (PR103 merge). Existing accepted runtime
and `work/price-related-metrics-20261116/source` remain unchanged. Root owns
capture, original-source preservation, operating changes and acceptance; the
single writer owns the consumer evidence helper and tracked follow-up records.
H5 final acceptance and follow-up remote delivery are not claimed here.

The supplier confirmed SDK0.5.1 has no generic sidecar generation command. Its
previous `reproduce.py` is specific to the old132-security capture; the extraction
rules may be generalized consumer-side. An official delivery check alone does
not prove that a new raw capture belongs to the price snapshot. The new
`prepare_price_capture_evidence.py` runs offline in the supplier runtime without
SEC/Arelle imports and checks exact pinned delivery/price/security/inventory,
canonical selected identities and checkpoint order, the ordered checkpoint/raw
commitment, compressed/decompressed raw bytes, URL symbol/horizon/fallback,
capture timezone, original currency metadata, committed normalizer and reviewed
action source bytes. It performs no price/financial arithmetic or network calls.

Preparation emits create-only `sidecar.json` under the existing
`price-capture-evidence.v1` schema and a separate candidate manifest with
`status=CANDIDATE_UNACCEPTED`,
`origin=CONSUMER_GENERATED_SOURCE_VALIDATION`, and
`supplier_independent_acceptance=false`. The sidecar preserves missing/unsupported
currency explicitly. Consumer generation is not supplier certification.
Independent Sol review must precede a ROOT exact adoption receipt. The helper's
`accept` command requires that receipt to bind the exact candidate, sidecar and
all source pins, rechecks capture/source bytes, and creates a new accepted
manifest. Its `status=accepted` means consumer adoption only; provenance and the
ROOT receipt remain explicit. Existing batch/valuation/source guards are unchanged.

The receipt contract is
`consumer-price-capture-evidence-root-acceptance-v1`, `authority=ROOT`,
`status=ACCEPTED_FOR_BOUNDED_PRICE_CURRENCY_ADOPTION`, with exact `candidate`,
`sidecar` and `source_pins` objects from the candidate (candidate pin includes path,
SHA256 and bytes). The old109 sidecar cannot qualify a new price hash.

A fresh2 candidate was prepared from the new official capture; it remains
unaccepted pending independent review and Root adoption. The candidate manifest
SHA256 is`8a17d6fb1758f2bc55b97af1a49f7887ce1034357643063408bf241a4143e7da`;
spec SHA256 is`0dc295fbc5e59a6b3d8cedb3eacd1ecb3a02954e5480f4675d6a2a3b95af18d0`.
The14network-free helper tests pass source/metadata/checkpoint/raw/action/URL/
timezone/selection mutation rejection, missing/non-USD currency retention,
create-only destinations, exact ROOT acceptance binding and capture mutation
before adoption. These are helper-boundary checks, not H5 completion or a repeated
whole-platform audit. No accepted source, old journal, supplier file or source pin
was modified. Official capture/replay and later publication/UI results will be
recorded only after the lead supplies completed evidence.

The lead's bounded operating plan, still subject to completed private/readonly
verification, is a separate loopback18766two-security worksheet. It will reuse
the accepted bundle, financial backend19078, qualified financial source and
auxiliary assets. The109-company default18765 remains running unchanged. The
bounded view must identify its two-company universe, actual2026-11-13quote and
three-calendar-day staleness for request11/16, automatic_update=false and old
financial cutoff10/25. It is not a refreshed109-company dataset. Private checks
use a copied price journal; operating old-save reopening uses the existing
journal's original pins without writing test records. No worker/asset/accounting
guard change is required. Actual18766activation/acceptance is not claimed yet.

## H5 completion and bounded operating acceptance — 2026-11-16

The lead compared all three separate independent stages with the actual capture,
publication, private browser/cold-restart and bounded operating results, then
accepted H5 locally. This supersedes the earlier H5 permission/candidate/adoption/
operating-pending stages for **US:AAPL and US:MSFT only**. It neither refreshes the
109-company default nor grants newer financial applicability.

### State and remote-delivery separation

| Scope / state | Exact target and dated evidence | Accepted status |
| --- | --- | --- |
| Original H0–H4 implementation/consumer delivery | [PR103](https://github.com/pluswc/sec_xbrl/pull/103), main merge`b9126a262ce561a45e14ee1bb33f872d36079bee` | MERGED |
| Original PR required CI`test` | [Run43743679695](https://github.com/pluswc/sec_xbrl/actions/runs/43743679695),3,201PASS/46SKIP | success |
| Original main CI | [Run43744367922](https://github.com/pluswc/sec_xbrl/actions/runs/43744367922),3,201PASS/46SKIP | success |
| H5 user approval |2026-11-16explicit official bounded AAPL/MSFT capture plus necessary verification/delivery | APPROVED |
| H5 helper implementation | source`8e97971d3c253833913edac68fd5705cc0d3f805`; only new consumer helper/test, no prior producer/worker changes | IMPLEMENTED |
| H5 independent helper/candidate stage |14tracked boundary tests+6independent edge checks, real extraction and official offline replay | PASS |
| H5 independent fresh-data stage | exact ROOT adoption,2068-row batch, immutable fresh2publication and20independent price calculations | PASS |
| H5 independent operating-evidence stage | ROOT browser/process evidence, original SQL/exports/configs/files and preservation independently checked | PASS |
| H5 ROOT final local/bounded operating acceptance | final receipt6250b3db…703f1, source8e97971 and fresh manifest107b39a2…1ec7d | LOCALLY_ACCEPTED_AND_BOUNDED_LIVE |
| This H5 follow-up remote PR / required CI`test` / main merge | Separate next delivery after this docs-only freeze/review | NOT_PERFORMED / NOT_PERFORMED / NOT_PERFORMED |
| Whole GOAL | ROOT final remote-delivery judgment remains separate | NOT_MARKED_COMPLETE |

ROOT rechecked the original PR103/main/CI facts on2026-11-16. Those successful
full-CI counts are the original delivery's actual results; they are not a newly
run CI result for the H5 helper or this documentation-only change.

### Official capture, source evidence and one batch adoption

The official SDK0.5.1/contract1.1.1 performed a **bounded full-history refresh** for
the two authorized securities at1request/second, yielding21,822canonical rows
(AAPL11,574/MSFT10,248). The frozen source period1 is−2208988800, period2/factor
horizon1794873600 and completed-day cutoff is exclusive2026-11-16. The physical
last observation is2026-11-13. Official offline`--from-inventory` replay produced
byte-identical price data at the new source hash below. No supplier repository,
existing canonical snapshot, Raw filing or financial panel was modified.

This is not a true incremental append API: SDK0.5.1 has none. The workflow adopts
one new bounded history snapshot, then one shared canonical batch for all metrics.
It does not claim scheduled/automatic refresh or a fresh109-company universe.
The source/action validation and currency sidecar retain the SDK's unresolved
corporate-action limits; source/currency validation does not certify a complete
action stream, historical ready time, EPS or common-class equivalence.

The explicitly selected session satisfies
`2026-11-13T21:00Z <= capture2026-11-16T00:14:49.518757Z < next2026-11-16T21:00Z`
under the retained XNYS source. Selection uses the actual completed session and
retained capture/coverage evidence, not D−1, weekdays or observed-row fallback.
Request11/16 versus actual11/13 is three-calendar-day staleness.

After independent candidate verification, ROOT accepted the exact consumer
candidate/sidecar/source pins. A separate accepted manifest was created; the
candidate remained unchanged. `origin=CONSUMER_GENERATED_SOURCE_VALIDATION`,
`supplier_independent_acceptance=false` and the exact ROOT receipt remain in the
adopted provenance. The manifest's accepted status means **consumer adoption**,
not supplier certification or supplier independent acceptance.

| Required immutable input/output | Exact SHA256 |
| --- | --- |
| Official fresh delivery manifest |`d34a2b713704730d385fabb841def3f71b12c07b24974fd9d3f3d0e81dd81148`|
| Official fresh price, also exact offline replay |`6122e9bdc92e9d979f5826b432ab5ba0a30516ed68236a6fab744210a56f766a`|
| Exact canonical security master |`26265d9297e47bbdd8a5373512c7a80cbd49ec5338817d0f843e24c50a400554`|
| Consumer candidate manifest / sidecar |`8a17d6fb1758f2bc55b97af1a49f7887ce1034357643063408bf241a4143e7da` / `ba37a15463b06971f37571afbfd97819241cd0adcbc59489d9dee24f960f0a79`|
| Exact ROOT consumer-adoption receipt |`37bd5a16efe0096e3961014ba522d86bd4e116a1b9c074e4d1b32f6f519a732e`|
| Accepted consumer manifest |`3b17b9fe561804ba499ff10ce38c39dacb5d0d824a194c32bc46bd1e9247e3f8`|
| Shared fresh canonical batch |`4e9741e0e4775fbe1ff8253b4bf7e096b2487ee8db12ed5834b11d4bf26a6ea2`|
| Fresh publication config |`ede6ec0733e104ec0e89e834d0cf1dc2564e334c4b4bfb35f9f83c140813fc80`|
| Fresh2publication manifest |`107b39a2ea6c6481733f3817e0a54cbdfd3cfb1a7808fad783b57d0fb511ec7d`|

The new batch contains2068rows=1034per security over2022-10-01–2026-11-13.
Consumer adoption verifies the delivery once and calls official CanonicalQuery
price history once for both IDs. No per-company/metric repetition of the old
supplier full-history scan or adoption check occurred.
The independent data stage compared every source column of all2068rows to the
new official Parquet and recomputed every batch observation ID. All ready_on
values remain null, not substituted with capture time.

The successful external supplier runtime was Python3.11 with PyArrow25.0.1
(`/home/plusbdw/anaconda3/envs/py31114/bin/python`). An independent first attempt
with a different Python3.12/PyArrow19 runtime failed reading the preexisting
security Parquet with`Repetition level histogram size mismatch`; the specified
supplier runtime succeeded. No packages were installed and no compatibility
rewrite occurred. The core SEC project remains Python3.12; its helper unit tests
and publication/query checks use the existing project virtualenv. The standalone
capture helper/exporter do not require SEC/Arelle in the supplier environment.

### Fresh publication availability and cutoff behavior

The accepted separate publication is
`data/processed/price_metrics/20261116_fresh2_diagnostic_v1/price_metric_manifest.json`,
ID`screening-price-metrics-577ab236eef320385d98bd71`, total1,135,342bytes.
It has2issuers×26latest observations=52rows,22AVAILABLE/30UNAVAILABLE, with the
full28definition registry and separately served user scenarios. Definitions,
formulae, session source and financial qualifications are unchanged.

| Fresh bounded result | Actual accepted behavior |
| --- | --- |
|6returns+3volatilities+relative volume for each security | All20available and independently recomputed with the exact approved windows/formulae |
| MSFT10current valuations | All unavailable:`FINANCIAL_CUTOFF_BEFORE_PRICE_AS_OF`;11/13price exceeds qualified10/25financial cutoff |
| AAPL10current valuations | All retain`CLASS_CURRENCY_SPLIT_COMPATIBILITY_NOT_APPROVED`; source USD proof is not class/EPS approval |
| Default PER/PBR scenarios | All12rows across2companies remain unavailable for those financial reasons |
| MSFThistorical PBR and PBR/BPS | Each739/754eligible sessions,15cutoff-blocked sessions, explicit partial diagnostic, P50=10.93243558907872642868996357855939 |
| MSFThistorical PER/P/S/EV-Revenue/EV-operating proxy | Each62/754eligible, below252minimum, typed insufficient-history reason |
| AAPL historical valuation | Explicit754-session scope-not-approved interval |

The fresh historical window is2023-11-13–2026-11-13. PBR's15new missing sessions
are after the old qualified financial cutoff; they are not filled. This
739/754**partial** filed-day diagnostic differs from oldv3's754/754window
2023-10-23–2026-10-23. Neither is a current PBR, percentile rank or historical-ready
certificate; both retain unknown actual ready time and backtest_eligible=false.
The old EPS/financial approval does not admit later filings or newly dated prices.
New financial qualification is a separate future task, not an H5 shortcut.

### Actual source-switch, saved-data preservation and bounded operation

ROOT exercised the private worksheet at18887 with the originalv3, then fresh2,
then a cold service restart. Exactly3existing private SQL rows stayed identical
in all four columns(id,created_at,fullpayloadtext,sha256); no record was added.
The original two-sided PER condition remains`gte10` AND`lte30`. Original band
result201.9375, quote524.510009765625 at2026-10-23, definitions, memo and exports
all reopen under the original source after switching active publication. All3
exports' entire request/result/note and original definition context matched;
export SHA256 is`2f05293c19331ab58a17a3f56786ceeaed3826a735338cde0fc76e79269cca20`.
An explicit new query returns the active fresh source with its cutoff guard.
Owned private processes18632/52460/27680were stopped after those checks.

ROOT then exposed only a **separate bounded2-security worksheet** at
`http://127.0.0.1:18766/`, observed NodePID61996 at acceptance. Original
`http://127.0.0.1:18765/`, PID52088, kept the109-company default unchanged and
was not restarted/replaced. Only three startup arguments differ: frontend port,
price-publication path and price-publication hash. The executable, accepted
bundle/assets, financial backend19078, qualified financial source
`d1e74d90c98838431740c0e16408d8b4d2623543`, price-source-root, journals and all
old auxiliary pins remain the same. Existing company common-input cards continue
to show their original dated source;18766is not a refreshed109-company dataset.
Process IDs here are dated ROOT observations, not future identity assumptions.

Actual18766browser checks passed: exactly2price companies,6comparison rows for
3metrics, new11/13quote evidence, visible3daystaleness/automatic_update=false and
MSFT's financial-cutoff reason. No browser error, blocked mutation attempt, live
test save or legacy-journal mutation occurred. The operating price journal is
shared for original-save pin reopening; test activity used only a private copy.

Before/after status,history,batchavailability,109pricecapability andpricesaves
responses match exactly. Original14datasets,109default price companies, history8
and trash8remain. Protected hashes are unchanged:

- legacy journal:`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`;
- operating price journal:`ba18bf81059b4de96e5028dd1e9a320c37100aa8366fd4b09299d9be7131e8b0`;
- originalv3manifest:`1fc3fcfaf96ec6960ac2f8f778ba280bdad001bb9b9e8eb19ec8b470394c400a`.

Raw SEC, old publications, user records, AGENTS/instructions/skills and original
source/native guards were not changed. No broader financial rebuild or109-company
re-audit accompanied this bounded refresh.

### Independent evidence, observation limits and reuse

The helper stage ran14tracked+6independent boundary checks, actual source
extraction and official byte-identical offline replay. The data stage independently
checked accepted pins, all new batch rows, all10fresh company files plus manifest,
all20fresh price calculations, cutoff/missing rows and PBR quantiles. The operating
stage independently hashed/reviewed the10ROOT evidence files, controller/configs,
read-only original/copied SQL rows and full exports, protected originals and four
runtime code files against frozen source.

**Actual Windows/browser/process actions were performed by ROOT.** The separate
verifier reviewed those pinned observations and independently inspected files,
SQL and configuration; it did not replay the browser/process actions. Its narrow
WSL GET attempts at18765/18766were blocked by the environment with`Operation not
permitted`; no bypass/fallback was used and direct live observation is not claimed.
ROOT separately owns the actual browser results and final local/H5 judgment.

| Acceptance evidence | Exact SHA256 |
| --- | --- |
| Independent helper/candidate PASS |`941c61bb06e5efcbe0d9464c33d6d5b89091f9d1a68337f3a6a87dde98ad570e`|
| Independent adopted batch/publication PASS |`c0654bf7fbe36fa0451dc2d619d1de8ccbd0898fd32642cd15cf9f74964f119d`|
| Independent operating-evidence PASS |`3c5ac882475d07d7b95cc6353068b11cd0af8459034ad1e84b63f022bd925e7e`|
| ROOT fresh publication local acceptance |`3917129691583e264d31e320c5d48bc5161654b502dc91b06e2ae7b17c94cbb0`|
| ROOT operating/preservation acceptance |`6b9a2a12d22ea8376ae9f75468cc707b69ce41fccb3f5aa2d1f5a1c909d3f8fa`|
| ROOT final H5 local/bounded-live acceptance |`6250b3db61107e4eba92964fd6d74244341551b9ce2cfde9a5e66a0fabb703f1`|

Previous69Python/20Node,392baseline source/example/test blob equality,
545-file oldpublication/math/PIT/save checks and original PR103fullCI are reused.
New checks above are distinct from those reused results. No completed source,
consumer-data, browser or helper extraction was rerun for this documentation-only
commit. This H5 branch's remote PR/required CI/main delivery remains a separate
next step; no future successful merge or whole-GOAL completion is asserted here.

### Offline reproduction contract and commands

The required inputs are explicit: exact canonical security master; official
SDK0.5.1 bounded frozen inventory and selected AAPL/MSFT checkpoints/compressed
raw captures; its new delivery/price files; pinned supplier source commit
`24f0b87160f793871f3dfea8faaf43092b1905d7` plus normalizer/action bytes; selected
identity JSON; consumer evidence specification; independent review and exact ROOT
receipt; retained1035-session calendar and financial-input-bundlev3 with their
original accounting/EV/historical approvals. Evidence files/data are required
inputs for replay, not hidden working-plan authority. Do not recreate approvals
by changing a status flag or copying the old sidecar onto a new price hash.

The evidence spec declares `schema_version`, dataset/source labels,
`supplier_root`, `source_commit`, and path/SHA256/bytes pins for delivery,
inventory and selected_securities. Each selected identity contains its full
canonical security_id, CIK, ticker, Yahoo symbol, company name and exchange.
The exact ROOT receipt schema/status/pin objects are defined in the preparation
section above. Candidate preparation and consumer adoption are separate operations.

Use the existing supplier Python3.11/PyArrow25.0.1 for SDK/metadata operations;
use project Python3.12 for the governed publication. With these variables pointing
to their explicitly declared local inputs and **new** output destinations:

```bash
PYTHONPATH="$TASK_SUPPLIER" "$TASK_SUPPLIER_PY" -m market_data_pipeline.cli canonical-price \
  --from-inventory --security-file "$TASK_SECURITY" --raw-root "$TASK_RAW_ROOT" \
  --out "$TASK_NEW_REPLAY"

PYTHONPATH="$TASK_SUPPLIER" "$TASK_SUPPLIER_PY" "$TASK_REPO/examples/screening/prepare_price_capture_evidence.py" prepare \
  --spec "$TASK_SPEC" --sha256 "$TASK_SPEC_SHA" --output "$TASK_NEW_CANDIDATE_DIR"

# After independent review and ROOT exact consumer adoption:
PYTHONPATH="$TASK_SUPPLIER" "$TASK_SUPPLIER_PY" "$TASK_REPO/examples/screening/prepare_price_capture_evidence.py" accept \
  --candidate "$TASK_CANDIDATE_MANIFEST" --candidate-sha256 "$TASK_CANDIDATE_SHA" \
  --acceptance "$TASK_ROOT_RECEIPT" --acceptance-sha256 "$TASK_ROOT_RECEIPT_SHA" \
  --output "$TASK_NEW_ACCEPTED_MANIFEST"

PYTHONPATH="$TASK_SUPPLIER" "$TASK_SUPPLIER_PY" "$TASK_REPO/examples/screening/export_canonical_price_batch.py" \
  --config "$TASK_BATCH_CONFIG" --sha256 "$TASK_BATCH_CONFIG_SHA" --output "$TASK_NEW_BATCH"

PYTHONPATH="$TASK_REPO/src" "$TASK_PROJECT_PY" "$TASK_REPO/examples/screening/prepare_price_metrics.py" publish \
  --config "$TASK_PUBLICATION_CONFIG" --sha256 "$TASK_PUBLICATION_CONFIG_SHA" \
  --output "$TASK_NEW_PUBLICATION_DIR"
```

The batch config supplies the new canonical price directory, new delivery pin,
new sidecar and accepted-manifest pins, exactly the two registered CIK/ticker
identities, start2022-10-01/end2026-11-13. The fresh publication config retains
session sourceSHA`931f5a8788e625d468a763a89ba6141e52ae04f409f3c4d068090e062b0a08a6`
and financial bundleSHA`12a5e7ac2db12e7b1a09aa50b77c8e80b995463bffbe7dfb2d9a4ea1f62c3fc7`,
qualified cutoff10/25 and original EV/diagnostic policy pins. Its selected session
is11/13, requested day11/16, series_start2025-11-13 and historical_start2023-11-13,
with`EXPLICIT_COMPLETED_SESSION` selection and`DIAGNOSTIC_FILED_DAY` policy.

For a source-switch replay, use a SQLite backup of the original price journal in
a private worker, retain that same copy across source switch/cold restart, and
call `reopen(saved_id)`. Pass its newly returned evidence_context with the exact
CIK/observation ID to evidence. Compare original payloads, definitions, quote,
notes and exports; then explicitly query the active source and confirm the cutoff.
Operating acceptance uses the separate18766configuration and readonly probes;
never replace the109default, seed live test records, restore an old journal or
reuse old opaque evidence tokens after restart.
