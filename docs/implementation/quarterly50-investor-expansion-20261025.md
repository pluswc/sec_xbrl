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


## Approved phase 3 prospective selection (source implemented; acceptance pending)

ROOT approved the source-only next slice after independent acceptance of
19967586. The original collections, History, prepared bundles and receipts remain
immutable. A new canonical collection proves current complete eligible filings;
a prospective companion may identify an unchanged accepted History as
SELECTION_EQUIVALENT while its collection remains RAW_COMPLETE. New compact
analysis publications have the exact current cutoff and explicit origin links.
Ordinary AnalysisClient and metric parent cutoff checks remain strict.

Reuse requires exact complete eligible inventories, current Raw digests, unchanged
completed calendar spine, profiles, review and quality settings, and explicit
ROOT policy compatibility evidence pinned to each origin analysis manifest.
Legacy v1 manifests did not retain selector source hashes: no historical code
hash equality or old checkout freshness is asserted. The compatibility approval
binds relevant current selector/mapper/period policy module hashes and exact
origin configuration, quality overlay, review cutoff and rules. ROOT materializes
actual approvals only after source freeze and independent policy seam review.

Changed inventories use the existing strict one-filing append proof, with
`require_append_reuse=True` prohibiting full fallback. Changed as-of rebuilds
current selected tables; it cannot claim the fixed-cutoff quarter fast path.
Approved fiscal focus corrections are applied to analytical filing copies after
Raw validation and before observation, ledger and coverage construction; Raw
records are unchanged. Exact correction artifact and source evidence hashes are
required. No new correction approval is inferred.


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


## Explicit v2 financial input scope — separate additive milestone

ROOT accepted e3ace1b7e2 source/synthetic after the combined ordinary selected
History regression repaired bcbc4ab591. The actual full-50 attempt then exposed an
IO scope issue and stopped before publication: 100.35 GiB of approved physical
History inventories included 94.03 GiB of nonconsumed retained producer diagnostics
and 6.32 GiB of governed manifests/payloads. No actual v1 performance or full-50
publication acceptance is claimed. Existing data and diagnostics remain preserved.

ROOT approved `financial-history-storage-reuse-v2` as an explicit new input scope.
Its fields are the same as v1 plus exact
`diagnostic_policy: NONCONSUMED_TOPOLOGY_ONLY`. Each History entry adds
`retained_diagnostics`, a sorted unique list of recognized relative diagnostic file
paths. `payload_inventory` must contain exactly `history_manifest.json` and all
current build-declared table/derived files, with full SHA256 hashes. The exact
union must match the safe physical file inventory. Known retained partial/spill
producer diagnostics are preserved, but their bodies, sizes and content hashes
are neither financial inputs nor financial freshness claims. Unknown files,
aliases, unsafe topology, missing declared files, missing diagnostic members and
changed governed bytes still fail closed. V1 and ordinary default physical
verification behavior remain unchanged.

The active financial source closure includes every governed input byte and all
active controls/source bindings/Raw inputs. For v2 only, retained diagnostic
bodies are excluded from file hashing; their safe names and physical topology
remain monitored at freshness boundaries. Diagnostic content changes alone cannot
change selected financial results. This policy does not relax any governed
History, Raw, plan, intake, endpoint, mapping, period, or analysis identity.

Financial preflight resolves an immutable, sealed per-invocation storage proof
once and passes it through status, selected History and source verification.
Identity can pass the same exact bound proof into quality source replay. Proof
mutation, wrong parents and wrong declarations are rejected; no global cache or
persistent skip capability exists. Full current-byte freshness boundaries remain.

Writer validation: 89 focused tests PASS in 26.25 s; 29 storage tests include v1
compatibility, explicit v2 no-diagnostic-hash assertions, stable financial closure
fingerprints across diagnostic body mutation, combined original/selected ordinary
routing, topology/core/approval tamper rejection and one resolution per preflight.
Ruff and diff checks PASS. Independent review, current ROOT compatibility approval
and actual baseline full-50 connection remain separate from these source tests.
The expected byte-scope reduction is measured from existing inventory metadata;
no new runtime improvement is asserted before the operator run.

Baseline uses its frozen v2 source and immutable v2 approval artifact. Later phase3
History/collector changes intentionally require a NEW ROOT compatibility registry
bound to the final phase3 source; accepted payload hashes may be reused, while the
baseline registry and old receipts remain immutable.


## Strict append and approved correction carryforward — source slice

This separate phase3 source slice exposes `build_history(require_append_reuse=True)`
and a public `build_universe(history_build_options=...)` forwarding boundary.
Without options all existing defaults remain. With options, keys must match the
exact selected ticker scope, and every entry requires `previous_history_manifest`
and `previous_reuse_evidence` path/SHA256 pins plus `require_append_reuse: true`.
An optional `fiscal_focus_corrections` path/SHA256 pin forwards the existing approved
correction artifact. The collector checks pins before and after the producer,
requires the exact strict reuse result, writes its genuine READY attestation, and
replays active control pins in later status/source closure checks. It does not
fabricate READY markers for the unchanged 38 companies.

A failed prefix, changed rules or other append proof error raises before full
producers when require_append_reuse is true. Legacy callers retain their existing
explicitly reported full fallback behavior. The current cutoff change conservatively
rebuilds current History selection tables; no fixed-cutoff quarter fast path is
claimed. T1–T4 prefix inputs still require the established exact one-filing suffix
and pinned migration/code compatibility proof.

The accession-scoped fiscal focus registry is ported from accepted source
fbbe26203c4976fdc4867d27eeec180be930b98b. No new company correction or approval is
inferred. Its existing v1/v2 artifact/approval/source/inline-context checks remain.
After Raw validation the producer applies the exact approved registry once to
analytical filing copies, feeding observations, append ledger inputs and coverage.
Raw records remain immutable; reported/effective focus and artifact lineage stay
separate. The period rule is exactly `period-fiscal-boundaries-v2+fiscal-focus:`
plus the ORIGINAL artifact SHA, matching accepted corrected prefixes. A different
artifact SHA rejects reuse; the adapter cannot silently full-fallback.

Validation: 27 focused tests PASS in 0.42 s, including generic synthetic CIK and
accession correction fixtures, effective coverage/ledger copies, same approved
rule equality versus changed-hash rejection, public collector READY/control
forwarding and no-full-producer callback on required append failure. Relevant
existing incremental prefix tests pass. Ruff/diff PASS. This is source-only;
independent acceptance and actual 12-company builds remain pending.

ROOT will wait for the final prospective source freeze before building the 12.
The all-package producer identity would change as later source is added, so this
intermediate freeze is not an instruction to rerun completed validation. New
compatibility/migration controls bind the final immutable source without rewriting
baseline registries, historical approvals or receipts. Public build operations
remain sequential against their shared collection status output; no concurrency
API is added.

## Prospective batch and current routine reuse — final phase 3 source contract

The public producer is `sec_xbrl.prospective_selection`:

- `publish_prospective_selection(config_path=Path, destination=Path)` writes a new
  `prospective_selection_manifest.json` after complete proof replay.
- `prepare_reselected_analysis_batch(prospective_selection={path, sha256},
  destinations={ticker: {ANNUAL: Path, QUARTERLY: Path}})` resolves that proof once
  for the whole batch, stages every requested target, rechecks all current active
  control, Raw, governed History, origin analysis and producer code bytes plus exact
  source/Raw/History topology, then exposes the new targets. The single-target
  `prepare_reselected_analysis` delegates to this boundary. No caller-supplied
  trusted proof or global reuse cache exists. A filesystem rename failure can leave
  new targets for diagnosis; no cross-directory atomic transaction is claimed.

The config schema is `prospective-selection-config-v1`, with exact
`current_collection`, `discovery_summary` path/SHA pins, `financial_as_of`, optional
origin `storage_reuse` pin, and explicit companies. Each company supplies ticker,
CIK, `origin_collection`, `origin_history_manifest`, `origin_annual_analysis`,
`origin_quarterly_analysis`, `current_policy` pins and optional
`origin_history_selection`. A shared accepted selection companion is replayed
once against its original complete company scope, preserving its exact existing
approval/recovery/build pins. No original marker or receipt is rewritten.

Each `current_policy` artifact has schema
`prospective-policy-compatibility-v1`, status `ROOT_APPROVED`, exact
`origin_analyses` pins, `current_collection`, `financial_as_of`,
`discovery_summary`, `raw_inventory`, `current_policy_source_sha256s`, `rules`,
and `ANNUAL`/`QUARTERLY` selection settings. Exported helpers
`prospective_policy_sources`, `prospective_rule_versions`,
`prospective_raw_inventory` and `analysis_selection_policy` define those exact
fields. ROOT approval must bind the current collection/cutoff/completeness proof,
not just an origin analysis. Missing legacy selector hashes remain explicitly
unknown; current producer closure is distinct from this historical compatibility
assessment.

Completeness reuses the existing SEC submissions adapter and filing selector.
Content-addressed root/archive snapshots must cover the root's complete archive
membership, counts and date ranges one-to-one. Current eligible FilingRefs and
Raw origin locators must exactly equal the original inventory. An omitted
amendment or newly filed older-period filing fails even when every new control
pin is internally coherent. Cutoff advancement must remain inside the same
completed calendar-quarter display spine. Profiles, review cutoff, quality overlay
and rule versions require exact approved equality.

Prepared publications receive new publication IDs, selection-event IDs and
prepared cell IDs. They preserve origin prepared IDs and the original trace in
explicit origin links. Raw/History fact IDs, contexts, units, actual periods and
values stay unchanged. New selection cutoff, original selection cutoff and
actual financial period dates are separate. Consumers still require exact new
analysis as-of; no blanket earlier-than-cutoff exception is introduced. Identity
per-company replay checks only that company's prepared bundle; it does not
resolve all companies again. A sealed invocation proof is forwarded to nested
quality verification. Source closure snapshots capture declarations and bytes;
the governed reader performs the complete semantic proof replay once, and the
existing before/after/publish freshness boundaries remain.

Both new quality and identity configs pin the same optional
`prospective_selection`. Their optional `storage_reuse` may pin a current-collection
v2 registry for the 12 new READY builds, while the prospective config pins an
original-collection registry for unchanged accepted History. Each History lookup
uses only its exact manifest-bound entry from the corresponding verified proof.
The new collection truthfully reports RAW_COMPLETE for unchanged companies,
History SELECTION_EQUIVALENT separately, and current prepared analysis READY;
actual new builds retain genuine READY markers. Financial readiness counts
separate READY and selection-equivalent companies.

The additional normalized evidence kind `ACCEPTED_CURRENT_ROUTINE_HISTORY` is
accepted ONLY within explicit financial storage-proof v2. Its existing
`accepted-financial-storage-evidence-v1` wrapper envelope pins history/build,
exact declared payload hashes, and `historical_controls={acceptance, report}`.
The acceptance JSON must equal `{status: ROOT_APPROVED,
kind: ACCEPTED_CURRENT_ROUTINE_HISTORY, build_manifest: <pin>,
history_manifest: <pin>, validation_report: <pin>}`. The native report must match
that genuine READY marker's storage_validation report/level/reason, current
public History.validate code identity/rules, scope, manifest, declared file set,
counts, schema metadata, current file identities and complete checked/reused
coverage. Parquet schema fingerprints are checked from metadata without decoding
cells. Only completed ROUTINE_INITIAL/CHANGED/UNCHANGED levels are eligible;
full_storage_validation and semantic_validation remain false. This reuses normal
completed lightweight validation and makes no full typed audit claim. Changed
controls, producer identity, payload, schema or inventory fail closed. V1 and
ordinary public History validation defaults remain unchanged. ROOT creates new
final-source compatibility/migration registries; baseline registries remain fixed.

## Actual compatibility findings and release limits

The accepted UNP source-binding fix filters relevance with the existing duration
and correction transform/lexical allowlists before requiring a source id. Nine
unrelated optional-id SEC metadata tags no longer block financial quality;
in-scope missing-id rows still reject. The accepted PCAR signed-zero fix applies
the already-declared source sign to numwordsen lexical nil zero. Exact Raw,
numeric, text and nil conformance remains; no allowlist or Raw values change.
ROOT preserved the completed 1097-filing source indexes/bindings and published
quality using those same outputs, without XML regeneration.

ROOT reported actual baseline quality, identity, annual 31 metrics, annual dataset
and quarterly 41 publication PASS. Actual availability inspection found all nine
TTM metrics unavailable because reported/derived quarterly inputs carry no
nonempty declared basis_version. Canonical mapping, unit and contiguous dates do
not establish reviewed accounting basis. Existing legacy quarter/QoQ arithmetic
has a separate arithmetic-only assurance, but the TTM contract remains stricter.
TTM operational release is therefore paused pending a separately approved basis
compatibility policy or genuine upstream reviewed basis evidence. No basis label
is fabricated and no TTM arithmetic policy is changed by this phase 3 slice.
Combined v3 actual acceptance and latest 12/38 execution remain ROOT-owned.


Final phase 3 source validation: 150 focused tests PASS in 49.02 s, including
19 prospective tests and 12 current-routine evidence tests. Coverage includes one
whole-proof replay per batch/identity invocation, local per-company replay,
precommit Raw/History mutation and inventory rejection, coherently pinned omitted
amendment/late filing rejection, archive membership, current-code/native file
metadata and schema rejection, callback-free completed routine reuse, mixed
current/origin proof routing, the exact-cutoff quality → identity → annual31 →
quarter41 → v3 flow, and affected legacy source-closure/identity/selection
contracts. Ruff and diff checks PASS. The previously frozen strict append slice
4064fad1beeaa065062c327a895d8eb009ae7eef also received independent PASS and ROOT
source acceptance. This final additive source freeze still requires separate
independent read-only review and ROOT acceptance before actual latest execution;
no main merge, live runtime release or TTM operational acceptance is claimed.


Producer source-file pins for the batch commit check are invocation-local.
Persisted compatibility uses relative module hashes, so relocation of identical
accepted code from an immutable operator snapshot to the final runtime does not
change prospective proof identity. Consumer source closure still binds the full
current runtime code independently. No historical source freshness claim follows.

The final portability/freshness correction passed 32 focused prospective/current-
routine cases in 12.68 s (29 previously accepted storage cases deselected),
including the new producer-code mutation-before-commit guard. The prior full
150-case affected-contract run remains applicable; this additive correction has
20 prospective cases. No actual company semantic validation was repeated.


ROOT's private baseline UI observation found the expected unavailable-metric
execution rejection exposed its English backend text. A scoped display mapping
now renders the known `metric is unavailable for execution:` error in Korean:
“현재 자료에서 실행할 수 없는 지표가 포함돼 있습니다. 사용 가능한 지표를 선택해 주세요.”
Backend errors, execution validation and TTM availability policy are unchanged.
This is a presentation correction, not TTM execution acceptance.
