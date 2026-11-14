# Price, EPS and shares common inputs — 2026-11-14

Status: IMPLEMENTED on the isolated milestone branch; independent review,
actual publication and local acceptance are separate pending steps. No UI migration,
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
