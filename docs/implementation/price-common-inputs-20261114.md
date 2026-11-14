# Price, EPS and shares common inputs — 2026-11-14

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
