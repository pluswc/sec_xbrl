# Quarterly 50 investor expansion — 2026-10-25

## Authority and milestone

APPROVED: the user's 2026-10-25 direction authorizes the common 50-company
quarterly financial, TTM and screening implementation and later operator rollout.
This writer implements source and synthetic acceptance only. The root operator owns
cached-input connection, latest SEC refresh and prospective operational release.
No existing publication, receipt, dataset, Raw, journal or live 21-company service
is modified. The implementation uses a separate existing checkout and branch.

## Interface diagnosis and chosen seam

`analysis.default_profile` already has the 21 monetary rows. Existing controlled
standard-statement additive allowlists already cover the extra flow QNames. No
new company mappings or Q4 registry policy is introduced. Missing disclosures,
unsupported derivations, ambiguity and incompatible source scope stay unavailable.
The metric producer owns arithmetic; consumers verify declared inputs and copy
values. Retain manifest v1 and the exact legacy 17 definitions, and declare a new
`quarterly-investor-41-v1` catalog for expanded publications. Producer readers
accept the legacy catalog as well as the declared expanded catalog. An alternative
manifest v2 would duplicate publication wiring without changing the data envelope.

## Acceptance criteria

- 41 definitions: all 31 annual counterparts (21 selected monetary rows and 10
  derived), retained revenue QoQ, five core TTM amounts and four TTM margins.
- Eight completed calendar buckets remain the display grain. Earlier prepared
  inputs feed YoY and TTM; instantaneous balances are never summed.
- TTM amounts sum four eligible contiguous actual fiscal quarters. TTM margins
  divide exact four-quarter numerator sums by revenue sums, never average margins.
- Existing USD, exact decimal, sign, basis, quality, QName, direct combined debt,
  same-filing and QTD scope rules remain fail closed. Standardized FCF is CFO
  less nonnegative PP&E purchase expenditure. Net debt uses only direct combined
  debt, with the existing exact-standard note allowance and typed BS cash.
- Selected bucket financial, growth and TTM conditions, eight-quarter trend,
  saved contexts and annual v1/v2 continue through read-only consumers. No price,
  EPS, PER/PBR or consecutive-N-quarter condition is added.
- Targeted producer, legacy 17-reader, lineage rejection and consumer-flow tests
  pass. No bulk cache scan, old company audit, full History rebuild or performance
  rerun forms part of this source acceptance.

## Readiness and handoff

Raw accepted, History accepted, financial prepared, metrics published and UI ready
are distinct states. Existing root evidence reports History 50 accepted, financial
subset five, 44 period ready and FULL50 false; this implementation does not promote
those states. Source IMPLEMENTED, independent verification, local acceptance, main
merge and actual operational rollout are recorded separately at handoff.

## Implemented source contract

The 21 selected rows retain their annual monetary meanings from
[screening metric definitions](screening-metric-definitions.md), with QTD for
flows and quarter-end INSTANT for balances. Each ID has `quarter_` prepended.
The ten derived counterparts are revenue YoY, gross/operating/net margins,
standardized FCF and its margin, current ratio, liabilities/equity,
liabilities/assets and direct combined net debt. Existing revenue QoQ remains.
The nine TTM outputs are `ttm_revenue`, `ttm_operating_income`, `ttm_net_income`,
`ttm_cfo`, `ttm_standardized_fcf`, `ttm_gross_margin`, `ttm_operating_margin`,
`ttm_net_margin` and `ttm_fcf_margin`.

TTM amount lineage declares one eligible QTD metric and four ordered fiscal
quarters. Standardized FCF retains each quarter's CFO/CAPEX lineage. TTM margin
contract `TTM_PERIOD_SUM_RATIO` retains eight named QTD inputs, four numerator
then four revenue observations, plus exact producer `period_sums`. The consumer
checks finite sums and positive denominator but never recomputes sums or ratios.
No extra public TTM gross-profit amount is needed. Same-filing comparison applies
to each numerator/revenue quarter; different historical quarters can originate
in different filings. Non-null declared basis and both FCF component semantic
identities must agree across quarters. Cycle/depth, input roles, metric identity,
actual periods, USD, mapping, typed PRE evidence and all quality legs are checked.
Debt note allowance retains an exact selected-source locator; cash still requires
primary BS evidence. Absent or unsupported inputs remain explicit unavailable.

Existing 17 definitions retain their exact dictionaries, versions and identity.
New publications declare `quarterly-investor-41-v1` in the unchanged v1 manifest
envelope. Both producer and consumer reopen legacy publications; consumers reject
unknown catalogs, incomplete expanded catalogs and TTM catalog downgrades.
Annual v1/v2, metric identity, quality, dataset v3, service, UI and journal code
need no new arithmetic or routing implementation.

## Implementation verification and remaining gates

IMPLEMENTED source/synthetic candidate: local commit supplied with handoff.
The scoped command below checks producer arithmetic, unchanged legacy definitions,
rehashed invalid provenance, the generic identity → annual31 → dataset v2 →
quarter41 → dataset v3 chain, saved conditions/reopen, trace and eight-quarter
trend. It uses only synthetic/local fixture inputs, not company caches.

```sh
POLARS_MAX_THREADS=2 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python -m pytest \
  tests/screening/test_quarterly50_expansion.py \
  tests/screening/test_quarterly_screening_producer.py \
  tests/screening/test_quarterly_generic_metrics.py \
  tests/screening/test_quarterly_source_validation.py \
  tests/screening/test_screening_quarterly_consumer.py \
  tests/screening/test_generic_metric_identity_contract.py \
  tests/screening/test_generic_metric_identity_integration.py -q --disable-warnings
```

Independent verification, lead local acceptance, main merge, actual 50-company
metric readiness and prospective operational release remain pending. Existing
analysis bundles can be reused byte-for-byte if they contain all 21 monetary
CORE rows, typed quarter evidence and required lookback. Their selection as-of
must equal the new metric publication as-of; the existing API cannot relabel an
old prepared selection with a newer cutoff. Latest discovery/completeness and
new prospective selection need separate operator evidence under the approved rollout.

Writer result: **370 PASS**, one pytest cache-permission warning, in 13.02 s.
Scoped Ruff and `git diff --check`: PASS. The exact original-main 17-definition
catalog from base `669489b5c76b0ee4c419e82c48c6a61289f160cc` was compared directly;
canonical JSON SHA-256 is
`e684c85ea4dea2b183584ef3e62e9663628290ae899246bcf643fab4e38e575d`.
No actual company publication or runtime data was read or written by this writer.

## Additive provenance routing and completed-proof reuse

The first 41-metric source freeze `455b2bae80cf437655de187b9e26494bb39f5f3e`
received independent Sol PASS and lead **SOURCE_SYNTHETIC_LOCALLY_ACCEPTED**.
Its accounting/catalog implementation remains intact. The following additive
source work has separate verification and operational acceptance gates.

The first-five actual attempt exposed repeated detailed storage decoding:
`read_universe_status` visits the full parent collection and completed recovery
`History.validate(routine)` forces `COMPLETED_RECOVERY_COMPATIBILITY` detailed
validation on each open. That attempt was stopped without a new publication or
completed receipt. It is not acceptance evidence or a failed financial formula.

The lead approved a financial-only reuse seam. `read_universe_status` accepts
`validation_mode="financial_sources"`; its default remains `routine`. Only the
exact completed recovery `parent/panels` with the existing public COMPLETE
transaction/PASS full-report gate can use the existing build validator's current
file-digest path. Plan, original intake, views, output root, manifest and declared
payload hashes remain exact. Generic metric quality and identity, including
reopening existing immutable v1 identities, use this path. New/non-recovery
publications retain the existing detailed/routine validation. No arbitrary READY
marker or caller-provided skip callback is accepted. `History.validate` itself
and ordinary/default status behavior are unchanged.

The shared source verifier checks current COMPLETE/PASS/report/rule bindings,
safe physical inventory and every current declared payload byte. It does not
decode already validated History JSON cells again. V1 retained diagnostics are
restricted to known producer spill/chunk/manifest-partial patterns; aliases and
unknown extras fail. The v1 receipt does **not** attest every retained diagnostic
byte. Current invocation source closure binds their complete physical inventory
and bytes at its established freshness points. This is storage/provenance reuse,
not new financial semantic assurance, accounting equivalence or a performance
claim. Existing prepared-source period, USD, basis, quality and metric gates
continue independently.

### Public companion/config contract

For approved replacement History routing, both the generic quality config and
generic identity config may include the same exact immutable declaration:

```json
{"history_selection":{"path":"/absolute/new-run/history-selection.json","sha256":"<64 lowercase hexadecimal characters>"}}
```

The companion is an explicit selection, with no ticker-specific engine behavior:

```json
{
  "schema_version":"accepted-history-selection-v1",
  "collection_manifest":{"path":"/absolute/original/collection_manifest.json","sha256":"<hash>"},
  "companies":[{
    "ticker":"EXAMPLE","cik":"0000001234",
    "acceptance":{"path":"/absolute/existing-lead-acceptance.json","sha256":"<hash>"},
    "recovery_receipt":{"path":"/absolute/existing-READY-recovery.json","sha256":"<hash>"},
    "build_manifest":{"path":"/absolute/accepted-correction/build_manifest.json","sha256":"<hash>"},
    "history_manifest":{"path":"/absolute/accepted-correction/panels/history_manifest.json","sha256":"<hash>"}
  }]
}
```

Entries must be unique and within the configured company scope. Unknown fields,
unsafe/noncanonical aliases, missing historical approval, mismatched company,
collection, recovery status, selected roots/hashes, plan, intake or views fail
closed. Historical approval is the existing
`lead-later45-company-history-acceptance-v1` receipt, status
`LOCALLY_ACCEPTED_COMPANY_HISTORY_ONLY_NOT_FINANCIAL_READY`, `accepted_by=ROOT_LEAD`.
Its exact selected build and recovery references must agree. The existing
`universe50-history-recovery-receipt-v1` must be READY and bind the original
collection, plan/intake, selected manifest and complete declared payload set.
The ordinary build validator still checks the selected marker using the original
plan/intake. No collection mirror, symlink, original marker rewrite, fake legacy
approval or Raw/History rebuild is needed. A current financial operator must use
new configs/publications; old receipts/publications remain unchanged.

Quality preserves original `collection_status` and `collection_build_manifests`
READY evidence and records `selected_history_evidence` separately. Identity keeps
the original collection-build digest and adds selected-build/evidence fields.
Quality and identity must declare the exact same companion; even a different
path to byte-identical companion content is rejected. Readers replay the resolver,
not just an opaque hash. Closure includes companion, original and selected build,
current collection/request/plan/intake, selected History and active source files.

Historical acceptance/recovery receipts and directly referenced approval, audit,
GO, correction and configuration JSON controls are immutable hash-bound evidence
blobs. They are not instructions to reopen old source checkouts, Raw/runtime
inventories or journal state, nor to rerun completed company audits. No freshness
claim is made for old engine/runner checkout code. Current producer source code
remains part of the current invocation closure. The latest-as-of selection seam
is explicitly outside this additive change.

### Additive verification

Run with `POLARS_MAX_THREADS=2 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.`:

```sh
.venv/bin/python -m pytest -p no:cacheprovider \
  tests/screening/test_history_selection.py \
  tests/screening/test_generic_metric_identity_contract.py \
  tests/screening/test_generic_metric_identity_integration.py \
  tests/screening/test_verified_source_closure.py \
  tests/unit/test_source_bindings.py -q --disable-warnings
```

The focused suite exercises default compatibility, original READY versus selected
History state, public quality/identity replay, coherent provenance mismatch,
missing/corrupt COMPLETE/PASS, changed payload bytes, unsafe inventory, declaration
divergence and mid-publication control mutation. A real synthetic completed
recovery records zero detailed callbacks on financial status/source verification;
the default status still invokes its established detailed path. This source/test
result does not accept actual first-five/50 metrics, main merge or live rollout.

Additive writer result: **109 PASS in 28.73 s**, scoped Ruff PASS and
`git diff --check` PASS. Independent verification and lead acceptance of the
additive commit remain pending. No completed actual company audit was rerun.
Actual first-five retry/50-company connection proceeds only after that separate
source freeze is independently accepted.

Later latest-as-of operational risk, not implemented here: a latest HON append
must retain the previously approved effective fiscal-focus corrections in its
accepted prefix. Existing Raw metadata must not silently restore the prior bad
foci; the main append API's correction-overlay handoff needs a separate scoped
assessment. Baseline 50-company connection takes precedence over that phase.


## Ordinary accepted storage reuse — additive source milestone

The 19967586 completed-recovery shortcut covers only publications with the real
engine COMPLETE/PASS gate. Actual metadata showed that most accepted ordinary
History directories do not have that gate. No claim of full-50 performance or
actual readiness follows from those synthetic tests. First-five attempts stopped
without new publications; their completed work and old acceptances remain intact.
The separate sparse-lookback fix bfeea89c63 preserves unavailable earlier inputs
outside the eight display inventory buckets (26 focused tests PASS).

ROOT approved an explicit optional `storage_reuse: {path, sha256}` in new quality
and identity configs. Both must reference the same immutable artifact. No global
registry or legacy-reader constructor override is introduced. Ordinary History
readers and status defaults keep their established strict behavior. Financial
status and source verification may reuse only the exact approved proof, and still
hash every current declared payload and safe physical inventory. They do not
redecode completed typed JSON cells or repeat historical company audits.

`financial-history-storage-reuse-v1` has exactly `schema_version`,
`status: ROOT_APPROVED`, `collection_manifest: {path, sha256}`,
`current_policy_source_sha256s` and `companies`. Exported
`financial_storage_policy_sources()` reports the fixed relevant current module
hashes for ROOT's compatibility assessment; it asserts no old engine source hash
or old checkout freshness. Each company has exact `ticker`, `cik`, and nonempty
`histories`. Each History has exact `acceptance`, `previous_validation`,
`build_manifest`, `history_manifest` pins and `payload_inventory` mapping every
physical relative file to SHA256, including manifest and retained diagnostics.
Unique original and selected History contexts may coexist for the same company;
companies and History paths cannot duplicate. Current original plan, intake,
views and READY build attestation remain bound by the existing validator.

A prior native version-1 full DETAILED/DETAILED_FALLBACK storage receipt is accepted
when its root, manifest and complete declared payload SHA map match. The explicit
normalized alternative `accepted-financial-storage-evidence-v1` has exact `kind`,
`history_manifest`, `build_manifest`, `declared_payload_sha256s`,
`historical_controls` and `schema_version`. `FULL_TYPED_COMPANY_AUDIT` requires
historical acceptance binding the pinned report and exact report company/output
root/PASS metadata. Every selected declared payload must have matching physical
SHA, all records consumed and schema/hash before/after checks in `all_file_results`.
`ACCEPTED_FIRST5_FINANCIAL_CHAIN` requires the accepted first financial config and
its exact company/build/History/plan/intake bindings. Historical controls pin the
prior `acceptance` and `report` or `config`, and may pin completion/seal/recovery
JSON witnesses. They are evidence blobs, without recursion into historical Raw,
protected inventories or old source checkouts. Entry `acceptance` means prior
historical acceptance; the outer ROOT_APPROVED artifact is current approval.
This reuses past evidence and makes no new semantic audit claim.

All current active controls and source inventories remain in the transitive
source closure and full-byte freshness checks. Invalid approval, changed policy,
missing or changed evidence, changed payloads, unknown extras, aliases and duplicate
proofs fail closed. Inputs without a trusted proof retain established validation.

Writer validation: 105 focused tests PASS (30.65 s), including 15 new tests for
native/normalized proof forms, zero typed-decoder callbacks, strict default
fallback, tamper rejection and new quality→identity replay. Metadata-only adapter
checks passed for seven real contexts: first-five TXN, ordinary AMD, late-report
LIN, and both original/corrected HON and CRM. Only pinned JSON report metadata was
read; no actual History cell scan or company audit ran. Independent verification,
ROOT local acceptance and actual full-50 publication remain separate and pending.
