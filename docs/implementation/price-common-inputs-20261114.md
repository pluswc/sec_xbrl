# Price, EPS and shares common inputs — 2026-11-14

Main-delivery authorization (2026-11-14): the user now authorizes review, remote
delivery and main merge of the accepted common-input/assessment/operating UI scope.
This supersedes earlier no-merge-request statements; those remain historical.
PR, required CI and actual main merge are still pending and lead-owned. No merged
status is inferred from local or operating acceptance.

Latest operating status (2026-11-14): product source `9d78a279de` independently
verified, profile artifact independently PASS, Root LIVE_ACCEPTED at
http://127.0.0.1:18765/ (Windows Node PID58984). Original qualified Python
backend19078/source `d1e74d90` was unchanged and not restarted. This is operating
acceptance under the stated limits, not PER approval or main merge. Earlier
no-activation/pending statements below are chronological scope/status records.

Latest overlay status (2026-11-14): implementation `cc3c9e85ab` and actual
assessment v2 independently PASS; Root LOCALLY_ACCEPTED the common assessment
under the limits below. No PER approval, UI/runtime activation or main merge.
Earlier pending-status statements are chronological implementation records.

Status (2026-11-14): source `9540f559703cf7643310a6051a07f6efd1506956`
IMPLEMENTED and independently verified (27 tests PASS); actual109 publication
completed; artifact review PASS and first-slice publication/query LOCALLY_ACCEPTED
by Root under the limitations below. No UI/runtime activation or
main merge has been performed. Earlier implementation-stage statements below
remain the dated scope and writer self-check record. No UI migration,
main merge, live service or journal changes are authorized by this milestone.

The publication projects already governed Analysis VALUE cells for all registered
issuers in an exactly pinned parent universe. It preserves selected Raw fact,
namespace/QName, full dimensions, unit numerator/denominator, actual period,
filing date (day precision), selection and prepared-file references. Basic/diluted,
total/continuing EPS, weighted-average shares, balance-sheet and cover shares remain
different input IDs. A missing field is not zero. Reported observations remain
queryable without a security association or market share-basis declaration.

Prices enter only through an explicitly pinned `canonical-query-price-export-v1`
created by the supplier's CanonicalQuery batch methods, or the equivalent injected
provider adapter. Preserve as-traded and split-adjusted fields separately. The
supplier's six-field security identity has no proven stock class, instrument kind
or currency: retain UNKNOWN rather than infer them. Keep issuer-to-security 1:N,
including unmatched/non-common securities; never pick the first ticker. No vendor
financial facts replace SEC analytical inputs. No valuation ratios are introduced.

`market_eps_diluted_ttm_direct_qtd_v1` is a separately named DERIVED rule: exactly
four directly reported, uniquely selected, consecutive actual QTD diluted-total EPS
observations with identical full dimensional scope/currency and an explicit pinned
same-class/share-basis declaration. The separately named reported
`EarningsPerShareBasicAndDiluted` input is not an alias for diluted-total EPS. Signed EPS, including zero/loss, is summed
exactly. No annual fallback, quarter-times-four, FY-minus-YTD EPS, automatic split
assumption or continuing-EPS substitution is allowed. The old EPS/WAVG
DIRECT_OBSERVATION_ONLY handoff and existing period/calculation rules are unchanged.
Missing quarters, conflicting duplicates, future filings/declarations, incompatible
units/classes/bases and absent evidence produce typed unavailable reasons.

The immutable publication stores small long input/selection rows and source pins,
not copies of complete Raw or History details. Its reader performs no accounting.
It verifies manifest/content hashes and small parent/export/analysis/intake declarations on query.
The producer hashes touched prepared tables through the existing codec and targeted
Raw cover tables; the reader does not rerun Raw or History verification. Actual preparation
completion is an aware timestamp recorded after successful materialization; this is
not historical SEC first availability. Filing dates retain day precision. Financial
cutoff, price observation date, supplier collection time and preparation readiness
are separate; no file mtime or scheduled start stands in for readiness. Lag0 is
unchanged; no new exchange calendar or historical-readiness assumption is introduced.

## Operator interface

`examples/screening/prepare_market_inputs.py publish --config FILE --config-sha256 SHA --output NEWDIR`
uses `screening-market-input-config-v1`: pinned `parent`, `financial_as_of`, pinned
`price_export`, `companies` with CIK/ticker and nullable pinned `annual`/`quarterly`
analysis manifests, optional per-company pinned `intake`, and optional pinned `basis_declarations`.
Both `schema` (operator handoff) and `schema_version` are accepted; conflicting
declarations reject. Cover shares absent from Analysis are projected only from
the latest eligible retained filing(s) in the exact intake. They retain all Raw
class/dimension candidates and are explicitly labelled as-filed, never selected
analytical EPS. Repeated references to one identical selected Raw observation are
deduplicated with all prepared analysis references retained; distinct conflicting
observations do not acquire a winner. Every parent CIK must
appear once. A source company must match the analysis ticker, cutoff and Raw CIK.

Price export fields are `schema_version`, pinned `delivery`, `supplier` versions,
`query` (inclusive start/end and exact requested security IDs), verbatim CanonicalQuery
`lineage`, `securities`, `prices`, aware `created_at`, and `producer` provenance.
Dates are ISO strings. The export is a governed supplier handoff, not independent
verification of Yahoo observations by this repository. The supplier source and
delivery pins must be retained in operator evidence.

Optional `market-eps-share-basis-v1` declarations bind CIK, stock_class_id, currency,
basis_id, exact four input observation IDs, available_on and nonempty source pins.
No declaration is synthesized from an absent corporate-action record.

`query --manifest FILE --sha256 SHA --cik CIK [--input-id ID]` reads published
financial/price/status/selection records. Root owns the actual109 build using exact
retained locators and a pinned supplier export after independent source acceptance.
Only synthetic boundary tests and the existing direct-EPS regression are run here.

## Focused self-check / handoff

New common-input tests18 and existing L2-M6 input-handoff regression9 passed
(27 total); Ruff and `git diff --check` passed. The tests cover synthetic109
publication/reopen, one issuer with multiple securities, missing states, Raw cover
class preservation, exact signed/zero/loss TTM, repeated same-fact references,
conflicts/gaps/future evidence/unit/class rejection and content mutation. No actual
109 publication, completed company audit, price rescan or runtime change was run
by the writer. Root supplies the pinned CanonicalQuery export and exact109
analysis/intake configuration for the separately reviewed real build.

## Actual109 publication handoff — 2026-11-14

Independent source verification passed all27 focused tests on `9540f55970`.
Root completed the actual build from retained inputs without repeating company
collection, History or completed audits. Publication
`screening-market-input-14060399dfa51f22f38e364d` is stored at
`data/processed/market_inputs/20261114_common109/market_input_manifest.json`,
SHA256 `a1b1c8c3e29c92e5fdb2aaf1534dd4024a847b72b31936131f5df5899322ee58`.
It contains109 issuers,13,549 financial input rows,129 observed quotes and132
securities. Build elapsed110.75s, peak RSS2,861,240KiB, output40,342,758 bytes.
The optional local receipt is
`work/price-common-inputs-20261114/ops/publication/acceptance.json`; this tracked
contract records the scope and limitations independently of that receipt.

Available EPS106, weighted-average shares108, cover shares109 and balance-sheet
shares99 count issuers with any retained period/scope. They do not establish
current-period PER coverage or a class-specific security/EPS association. All109
market TTM results remain unavailable with `SHARE_BASIS_UNKNOWN`: no explicit
share-basis declarations were supplied. Annual-minus-YTD EPS remains forbidden;
reported inputs are still independently queryable.

All12 protected input pins, including the original journal, were unchanged.
There was no UI activation, service restart, runtime migration or main merge.
Backend19078 refused HTTP connections in the current environment, so this
handoff makes no operating-service acceptance claim. Root artifact review passed the exact manifest and all five content hashes/counts,
public queries and an AAPL Raw-lineage spot check. Root LOCALLY_ACCEPTED this
first-slice publication/query contract under the stated limitations. This does not
constitute UI, service or main acceptance; later consumer integration remains a
separate decision.

Generic query usage (substitute an actual registered CIK; no ticker-specific rule):

```sh
PYTHONPATH=SOURCE/src PYTHON SOURCE/examples/screening/prepare_market_inputs.py query \
  --manifest PUBLICATION/market_input_manifest.json --sha256 MANIFEST_SHA \
  --cik REGISTERED_CIK --input-id reported_eps_diluted_total
```

## Approved follow-up: small referenced assessment overlay — 2026-11-14

The original109 `SHARE_BASIS_UNKNOWN` results were an early declaration check,
not109 detected stock splits or errors. Preserve the original publication and
four-direct-quarter rule v1 unchanged. This follow-up separates financial EPS
period availability from security/EPS applicability and price/share-basis approval.

`reported_eps_diluted_12m_latest_v1` references already AVAILABLE_REPORTED diluted
EPS for a directly reported FY or explicitly classified TTM interval ending at the
latest eligible **financial report end**, determined from the pinned intake, not
from the latest EPS row. Actual exclusive boundaries and USD/share units must
match. Negative EPS is valid financial data, with positivity for multiples a
separate field. Stale FY, future filings, conflicting same-period values and
unresolved competing filing selections remain unavailable; there is no annual
fallback or annual-minus-YTD calculation. Equivalent appearances within one exact
filing/context/period/full scope/unit/value consolidate all original references.

Four-QTD diagnostics first expose missing direct quarters, gaps, conflicts and
unit/full-scope differences, then report missing share-basis evidence. Distinct
canonical EPS scopes receive separate diagnostics; they are not mislabeled as
conflicting duplicate facts or assigned a winner. Dimension identity uses exact
namespace+QName, preserving original Raw IDs. Neither custom class names nor
versioned custom namespaces are fuzzily equated. These diagnostics do not bypass
legacy v1 declarations or publish an unapproved EPS sum.

Security identity projects only the targeted retained header facts TradingSymbol,
Security12bTitle and SecurityExchangeName from the original cover-source snapshots.
CIK must match both filing and normalized SEC context entity, and ticker must
match the supplier identity exactly. Preserve every matching context, including
stock and note/bond contexts sharing one symbol. An exact reported class identity
is distinct from EPS applicability and split review. Full EPS/header dimensional
scope is required even for a class-match diagnostic; empty EPS dimensions and
singleton issuers never imply class applicability. Custom member instrument kind
remains UNKNOWN unless separately proven. No valuation ratio is published.

The overlay pins the existing common-input manifest and writes only small
assessments plus targeted source pins. Parent financial/price payloads, Raw,
History, journal and prior rules are not reprojected or rewritten. Targeted Raw
row caches are cleared per issuer while immutable pins remain. The overlay reader
delegates original input queries to the parent and exposes `assessment.reported_12m`
and `four_quarter_diagnostic` beside untouched legacy `derived_inputs`.

```sh
PYTHONPATH=SOURCE/src PYTHON SOURCE/examples/screening/prepare_market_inputs.py assess \
  --parent COMMON/market_input_manifest.json --parent-sha256 COMMON_SHA --output NEW_OVERLAY
PYTHONPATH=SOURCE/src PYTHON SOURCE/examples/screening/prepare_market_inputs.py assessment-query \
  --manifest NEW_OVERLAY/market_input_assessment_manifest.json --sha256 OVERLAY_SHA --cik REGISTERED_CIK
```

This is the approved isolated implementation scope. Independent source review,
actual109 overlay publication and local acceptance are subsequent separate steps;
no UI/runtime/main activation is part of this follow-up.

Overlay IMPLEMENTED on the isolated branch: eight new focused synthetic tests
passed, covering latest-anchor/stale/future/negative12m, equivalent and conflicting
references, exact canonical scope, per-class quarterly diagnostics, same-symbol
stock/bond headers and context CIK, append-only overlay/parent delegation and
tamper rejection. Targeted Ruff/diff passed. Prior27 checks are reused; legacy
market_inputs/four-quarter v1 code is unchanged. Writer ran no actual109 overlay
publisher or data job. Independent review and real overlay acceptance remain pending.

### Header routing correction before actual overlay acceptance

The first unaccepted actual overlay v1 exposed an artificial gap for22 issuers:
their cover shares already existed in Analytical cells, so those parent rows did
not contain Raw-fallback manifest fields. Header discovery now independently uses
the exact intake's latest eligible10-K/Q(/A) filed day and retains every same-day
filing. It derives each retained snapshot path and verifies Raw manifest/filing
identity, reusing parent cover-table pins for the same selected filing when
present; otherwise it establishes targeted header-table pins. Financial analysis,
Raw source values and overlay v1 remain unchanged. The new Analytical-cover-only
regression also checks same-day preservation, future/older filing exclusion and
parent-pin tamper rejection. Nine affected overlay tests passed; no actual overlay
publication or prior company audits were run by the writer.


## Actual assessment v2 acceptance — 2026-11-14

Source `cc3c9e85ab181a1450150fc0705703d27e9542ed` and the actual overlay v2
passed independent review. Root LOCALLY_ACCEPTED publication/query assessment,
not PER valuation, UI, operating-service or main integration. Eight original
overlay checks were reused and the routing regression independently passed; the
prior27 common-input checks and completed company audits were not repeated.

Publication `screening-market-assessment-e5875febdf0ae3ca778cdbda`:
`data/processed/market_inputs/20261114_common109_assessment_v2/market_input_assessment_manifest.json`,
SHA256 `ec827bfa25a21b336416e0a2673f69394dd9b9cd2c5a1ce0e88281b1ef2c93fa`.
All109 issuers have reported header matches:128 contexts, including46 explicit
class-identity **contexts**, not46 companies. Twelve issuers have directly
reported12m EPS at their latest financial end (11 positive; LITE negative and
valid financial EPS). Only HON/ABBV have latest four-direct-QTD input windows;
their share-basis approval remains unknown. Other issuers have no direct12m at
their latest financial end, missing/gapped quarters or multiple scopes requiring
selection. No older FY fallback or automatic EPS/security/PER approval was added.

The small overlay is768,474 bytes; actual build2.18s, peak RSS443,288KiB. The
original40,342,758-byte common publication and all18 protected files, including
the original journal, remained byte-identical. Intermediate overlay v1 (header
coverage87 issuers) was never accepted and is retained unchanged. V2 corrects
header routing for Analytical-cover issuers while preserving all109 financial
12m/four-QTD assessments. No runtime or main changes occurred.

Optional local evidence: `work/price-common-inputs-20261114/basis-review/overlay-v2/acceptance.json`
and `coverage109.csv`; the tracked contract records the authoritative limits.
The generic `assess` then `assessment-query` commands above apply to new registered
filers with pinned inputs; there are no issuer exceptions.

## Approved operating consumer connection — 2026-11-14

The user approved operating activation, using only the price project identified
in the requested supplier chat. The supplier confirmed the recommended
`broad-price-oct2026-20261108-r1` delivery, SDK v0.5.1
`24f0b87160f793871f3dfea8faaf43092b1905d7`, external contract1.1.1.
Root verified its package tree `c561a3c9a19c5c08567924516c2458fe6802215c`
equals the already archived exporter package. The existing CanonicalQuery export
and exact delivery/price/security pins are reused, with no new price scan/query.
CanonicalQuery and supplier delivery verification remain required on a future
adoption/replacement, not on each profile request. No provider/scraper replacement
or price-basis calculation is introduced.

The lightweight offline profile asset references the accepted common109 and
assessment v2 and an exactly pinned prepared dataset manifest (or its read snapshot).
For a read snapshot it checks the logical digest and uses the embedded original
prepared identity; it does not open a financial reader factory or grant a source
qualification. The prepared parent's manifest pin, cutoff and issuer set must
match the common-input parent. This connection preserves the qualified operating
Python and its existing snapshot/catalog/history routes.

The optional bridge flags `--market-inputs FILE --market-inputs-sha256 SHA`
serve only a startup-hash-verified `screening-market-input-profile-v1` asset.
`GET /api/market-inputs` reports capability; company GET requires exactly
`dataset_id`, `dataset_publication_id`, `financial_as_of`, `cik`. No auxiliary-owner
fallback, old21 publication, extra fixed/historical period or mismatched scope can
borrow current quotes. The default bridge invocation remains compatible.

The latest-company profile adds a compact worksheet band: trading-day close and
latest directly reported12m EPS, with actual dates. Detailed shares/source candidates
remain in a closed native disclosure, grouped by their governed prepared full-scope
series and period class with latest actual dates. Conflicting values retain an
unavailable reason; no class or recast winner is invented. The initial price is the
unique exact configured CIK+ticker security only; other classes/securities remain
explicit additional candidates. No first supplier row is selected automatically.

The10/25 financial request uses the observed10/23 as-traded close, with an explicit
2-calendar-day difference. It is a frozen historical observation, not today's or
an automatically updated price. Price currency remains UNKNOWN because the supplier
contract has no currency field. EPS remains USD/share and shares remain shares;
financial table/chart million-USD captions are narrowed accordingly. Price dates
are unchanged; inclusive financial display ends are projected from known exclusive
ends upstream. Negative EPS is visible without a positive-PER claim. There are no
valuation formulas, factor reapplications, new charts or screening conditions.

Requests bind company, selected publication, latest/fixed context and request token.
Closing/switching the profile invalidates late success/error rendering. Loading,
missing and error states preserve existing financial detail and saved history.
The existing paper/slate/annotation-blue worksheet tokens and tabular numerals are
reused; no layout system, guidance file or operating-source approval is changed.

Operator recipe (actual root-owned projection/preview/cutover requires frozen-source
independent acceptance; writer has not run an actual data job):

```sh
PYTHONPATH=SOURCE/src PYTHON SOURCE/examples/screening/prepare_market_input_profile.py \
  --assessment ASSESSMENT/market_input_assessment_manifest.json --assessment-sha256 ASSESSMENT_SHA \
  --dataset APPROVED_DATASET_MANIFEST --dataset-sha256 DATASET_SHA --output NEW_PROFILE_ASSET.json
```

Copy that exact asset to the bridge host and add its two flags to the otherwise
retained invocation. Root owns runtime recovery, original/cloned journal checks,
private browser acceptance, current-UI preservation and guarded live cutover.
Implementation/source verification, actual asset acceptance, operating acceptance
and main merge remain separate; no main merge is requested in this milestone.

Operating consumer source self-check: new Python projection3 and Node route/UI4
tests PASS. Two affected existing checks passed (protected financial/persistence
handlers and legacy owner dispatch); other tests were filtered out. JavaScript
syntax, targeted Ruff and diff checks passed. No prior27/overlay9/company audit
or real-data projection was rerun by the writer. Frozen-source independent review
and root-operated asset/private/live acceptance remain pending.


## Actual operating acceptance — 2026-11-14

Source `9d78a279de553141bef5c5dab6ee884aec3ed175` is frozen separately from
this docs-only handoff. Independent source verification passed the new projection/
route/UI boundaries (new7 checks, affected existing checks), and the tiny shared-
table-wrapper regression passed separately. The earlier27 common-input and8
overlay checks were reused; no completed company audits were repeated.

Actual profile asset `work/price-common-inputs-20261114/operating/market-input-profile.json`
has SHA256 `271100cca9f27802088ea4bd262fa73bd9e8635248234c8d348f5831c0bd32f6`,
size1,968,650 bytes. Projection took0.55s with peak RSS231,168KiB. Root and
independent artifact review passed: all109 configured ticker/CIK pairs have109
default prices,12 latest direct12m EPS are available, and class alternatives and
missing states remain explicit. No PER or other valuation ratio is supplied.

The requested supplier chat `01a09991-9bd0-7c20-b3c7-048130610c54` was read and
its official guidance used: SDK0.5.1/contract1.1.1, recommended broad-price-r1,
exact frozen delivery pins and release-tag package-tree equality with the existing
export. No recollection or replacement price query was performed. Financial
cutoff remains2026-10-25; displayed prices are2026-10-23 observations, with currency
UNKNOWN. They are not current or automatically updated quotations.

Private actual checks confirmed MSFT524.51/17.95, AAPL347.73 with missing latest
12m EPS, negative LITE EPS, exact GOOGL identity/class alternatives, fixed-view
hiding and old-scope409 rejection. Desktop1440 and390px checks passed; expanding
shares uses the existing shared table viewport without page errors. Actual live
read-only acceptance confirmed109 companies,14 datasets,12 existing financial
charts and share expansion with zero page errors. Old21 functions, catalog and
journal were preserved; all20 protected file hashes remained identical.

The live URL is http://127.0.0.1:18765/ via Node PID58984; the qualified Python
backend19078 remains the original process/source. The first bridge-switch port-
release race restored the previous source and checked UI hashes; a bounded port
wait allowed the second switch to pass. Financial data was untouched. The owned
private PID7844 was stopped; no worktree or data directories were deleted.

Optional receipt: `work/price-common-inputs-20261114/operating/activation-acceptance.json`.
Windows visual evidence is under `market-inputs-operating-20261114` in the allowed
Oct7 visualization root (`live-browser-acceptance.json` and accepted live PNG).
The generic profile-asset command and two bridge flags above reproduce the
connection from pinned inputs without issuer branches. Implementation, independent
verification, artifact acceptance and LIVE acceptance are complete for this scope;
main is NOT_MERGED and no main merge was requested. No instructions/design-system
files, source modules, tests, runtime or data were changed by this final doc update.


## Main delivery handoff — 2026-11-14

The feature branch is based on main `245a52bc44e16480d99077b3e7bd56252b7d6510`.
This handoff changes only the contract and planning status. Product source
`9d78a279de553141bef5c5dab6ee884aec3ed175` stays frozen; source, examples and tests
are byte-identical to accepted handoff `d6df9aa147a06956778545c1ccce41465a81dee9`.
Previously completed independent source/artifact reviews and actual UI receipts
are reused. No prior27/8/7 checks, company audits, projections or operating
restarts were repeated for this documentation update.

Operating Node PID58984/static bundle, qualified backend19078/source `d1e74d90`,
accepted publications and all20 protected file pins, including the journal, remain
unchanged. New market-input modules confer no native/preparation approval on a
new main source inventory; existing exact source-qualification boundaries remain
fail-closed. Main code delivery is separate from qualifying any future producer
or replacing the immutable operating Python checkout.

The tracked operator commands, scope/price contracts and acceptance limits above
remain the generic handoff. Root owns push, PR, mandatory CI and merge decisions.
At this freeze those remote stages and main merge are pending; the final merge
result/SHA must be established by the PR and Git history, not by this record.
