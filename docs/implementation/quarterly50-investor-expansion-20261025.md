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

## Independent P1 return and origin History closure repair

Independent review of 9477b401f9d8111cf95216ec34357c3921c2481d returned FAIL:
with optional storage_reuse omitted, governed origin History payloads were checked
at resolution but missing from the later batch byte/inventory boundary. The
reviewer's two-target synthetic probe mutated an origin Parquet after staging and
both outputs incorrectly published. The earlier passing synthetic results did not
cover that branch; they are not acceptance of this missing boundary. ROOT preserves
the original failed report and requires a separate independent repair result.

Every selected origin History now contributes all governed manifest-declared
payload hashes and exact safe topology independently of prior-check optimization.
No-storage, v1, or a partial registry without that exact origin entry retains the
strict physical-byte policy, including recognized retained diagnostic bodies.
Only an explicit verified v2 entry may exclude those bodies, preserving their
safe exact inventory. Unknown files, empty directories, aliases, special entries
or missing inputs fail closed. Distinct provenance roles sharing one physical
path are hashed once at the commit boundary; conflicting pins reject.

Repair validation: 10 relevant tests PASS in 4.97 s (16 unrelated prospective
cases deselected), including six new no-storage/partial-registry/explicit-v2
cases. Core mutation, unknown file, alias and retained-diagnostic mutation prevent
both target publications without storage; an uncovered partial registry does not
imply v2 exclusion; explicit v2 diagnostic-only body mutation remains eligible.
Ruff/diff PASS. No actual input audit, old validation rerun, accounting change or
TTM policy change. Independent rerun of the original failure probe and ROOT
acceptance remain pending for the repair freeze.


## Scoped period-label CSS correction and ROOT baseline report

ROOT observed the global first-cell checkbox width leaking into quarter detail
and peer series tables. The 34px width is now scoped to `#result-body td:first-child`;
`.series-table` uses `word-break: keep-all`. This keeps Korean quarter labels
readable while preserving existing palette, paper surfaces, border depth,
11px metadata, 9×12px cell padding and spacing. No layout redesign or design-system
instruction changes are made. ROOT owns desktop/compact visual overlay checks on
the already loaded private baseline page; no data or audit rerun is needed.

ROOT reported all six baseline stages COMPLETE on immutable source 1edec6:
quality, identity, annual31 metrics, annual dataset, quarterly41 metrics and
combined v3. The final previously uncompleted v3 attempt passed in 233.24 s,
peak 11539400 KiB, after disabling an optional periodic faulthandler dump in the
operator following SIGSEGV11. No product/data fix was requested for that runtime
event. Private cloned-journal UI checks passed 50-target quarterly revenue/YoY
execution (38 pass, 3 fail, 9 undetermined), eight-quarter detail and peer
comparison, explicit save, and reopen of the original 21-company result context.
Backend restart preserved exact condition/result reopen without extra records.
Original catalog/journal hashes were unchanged. These are ROOT-reported baseline
operational results, not independent acceptance of the phase3 repair.

TTM actual availability remains zero and execution is NOT accepted; the human
basis-policy decision is pending. Latest12 Raw, latest50 metadata, new1109
canonical control intakes and package view are prepared. Latest12 History and
prospective38 actual execution remain held for final source review and that
policy decision. No completed old company audit or baseline stage is repeated.


## Independent repair PASS and selected-period caption

ROOT reported independent PASS for the P1 repair at
865d6a1d589a9241b9ae274164d3859cf52d5ee4, including the previously failing optional
no-storage boundary. The original 9477 FAIL report remains historical evidence;
the repair is separately verified, rather than retroactively relabeled.

A final actual criteria observation found every non-instant metric captioned as
annual. The criteria hint now uses the governed
`observation_basis || period_class`: INSTANT → 기말잔액, QTD_3M → 분기실적,
TTM → 최근4분기, with the existing annual fallback 연간실적. No financial
calculation, metric definition or source API changes. Existing interface hierarchy,
palette, depth, Korean type and spacing remain. Existing UI checks pass; ROOT
owns the three actual DOM caption checks by final-JS overlay, without restarting
the backend or rereading Raw. Baseline quarterly/YoY UAT remains accepted as
reported above. TTM strict basis policy, its unaccepted execution status and the
human policy question remain unchanged; actual latest12 builds remain held.


## 2026-10-26 final local handoff — source accepted; policy decision required

ROOT accepted source freeze `d3591dccf1287c7231221372d6c80b8675209ad2` as
`SOURCE_SYNTHETIC_LOCALLY_ACCEPTED_NOT_LATEST_ACTUAL_OR_TTM_RELEASE` after the
independent repair PASS at `865d6a1d589a9241b9ae274164d3859cf52d5ee4` and final
caption/UI PASS at d359. The original 9477 P1 FAIL remains preserved separately.
The final handoff commit is documentation only: accepted Python/source/test bytes
remain d359, so this status update does not create another producer code identity
transition.

ROOT accepted the baseline at
`1edec6d8ad682ae2dabb82b02b9986068d91e7e4` as
`LOCALLY_ACCEPTED_BASELINE_NON_TTM_CONNECTION`. All six actual stages completed:
quality, identity, annual31 metrics, annual dataset, quarterly41 metrics and v3.
Private 50-company quarterly revenue/YoY creation, restart/reopen and the original
21-company saved-context reopen passed, preserving original catalog/journal and
live21 hashes. Explicit save remains the only persistent user action.

The final d359 front-end CSS/JS overlay on that already accepted 1edec6 baseline
backend passed actual visual/DOM checks at 1464, 768 and 390px. First period-column
widths were 234, 234 and 121px respectively; Korean periods remained readable.
All four governed basis captions (instant, quarter, TTM and annual fallback) were
correct. These checks establish the scoped front-end corrections against the
baseline backend; they are **not** latest full-stack/end-to-end acceptance, and do
not accept TTM execution or make unavailable values available.

The human TTM basis-policy choice is **REQUIRED AND PENDING**. Actual nine-TTM
availability remains zero under the unchanged strict declared-basis contract.
No new arithmetic-only compatibility policy or invented basis label is approved.
Latest12 History and prospective38 actual execution are **NOT STARTED**: they stay
held to avoid repeating global producer code-identity checks if the required TTM
choice changes source. Latest12 Raw, latest50 metadata, all1109 new canonical
control intakes and the package view are already prepared and preserved.

No live21 switch, original catalog/journal mutation, main merge, push, instruction
or design-system edit, or deletion accompanies this handoff. Required next action
is the human policy choice; any accounting/source implementation follows its own
approval, freeze and independent verification before latest actual execution.

Optional operator records are
`work/quarterly50_expansion_20261025/lead_phase3_source_acceptance.json` and
`work/quarterly50_expansion_20261025/lead_baseline_quarterly_connection_acceptance.json`.
They supplement this tracked, self-contained status and are not prerequisites or
sole authority for understanding scope, acceptance or outstanding decisions.

## 2026-10-28 approved arithmetic TTM version — implementation contract

The user explicitly selected “산술 TTM을 별도 버전으로 제공 (권장)” and authorized
the recommended execution sequence. This resolves the required policy choice;
implementation, independent verification, actual latest execution and release
remain separate states. The sole writer implements a new
`quarterly-investor-41-arithmetic-ttm-v2` catalog. Existing strict17/41 definitions,
versions, saved results and their exact meaning remain unchanged. Rewriting the
strict catalog would have a smaller immediate diff but would change historical
contracts; it is rejected in favor of explicit version selection.

Acceptance: all nine TTM definitions receive new definition/rule identities and
an explicit declared-equal-or-all-null arithmetic basis policy. Four consecutive
actual fiscal QTD observations must match CIK, selected view/cutoff, unit,
dimensions, semantic item identity/mapping and compatible versions. Equal
nonempty basis retains declared-basis assurance; four null bases may use only
ARITHMETIC_ONLY_NOT_RECAST_VALIDATED, preserving null basis_version. Mixed,
empty or mismatched basis and explicit recast, continuity, structural, review or
quality problems remain unavailable. FCF requires compatible CFO and CAPEX
components in all four quarters. TTM margins are ratios of four-quarter sums.
Missing input, QTD/YTD confusion, balance summation, FY+YTD fallback and consumer
or UI calculation remain prohibited.

The producer owns arithmetic; consumer readers verify the new declared catalog,
input contracts and complete source/derived lineage. New publication selection
is explicit via config/catalog API; default remains strict. User-facing text is
“최근4분기” and a brief arithmetic-basis explanation, retaining saved-context
reopen behavior. Focused positive/negative, mixed-leg, consumer and legacy tests
plus a small reused fixture strict/new comparison precede freeze. Completed
company audits and full cached-history preparation are not repeated. Relevant
code/source compatibility registries must be freshly approved against the final
source before latest12/38 operations; original registries and receipts stay fixed.

### Arithmetic catalog implementation and exact operator interface

Source changes are limited to the quarterly producer/catalog and its read-only
quarterly consumer. The existing service forwards definition.description, so no
front-end or source API patch is needed. Definitions describe “최근4분기” with a
brief arithmetic-only explanation; margins explicitly describe an item-sum over
revenue-sum ratio. No fabricated basis_version is emitted.

Select the new version in a NEW quarterly publisher config; preserve original
configs, publications, dataset entries and saved journals:

```json
{
  "schema_version": "quarterly-screening-metric-config-v1",
  "catalog_version": "quarterly-investor-41-arithmetic-ttm-v2",
  "financial_as_of": "2026-10-25",
  "source_commit_sha": "<final frozen 40-character source SHA>",
  "annual_metric_root": "<new exact-cutoff annual metric root>",
  "annual_metric_manifest_sha256": "<that annual manifest SHA256>",
  "companies": [
    {
      "ticker": "<ticker>",
      "cik": "<10-digit CIK>",
      "analysis_root": "<new current-cutoff prepared quarterly analysis root>",
      "analysis_manifest_sha256": "<that analysis manifest SHA256>"
    }
  ]
}
```

```sh
python -m sec_xbrl.metrics.quarterly_screening publish \
  --config NEW-quarterly-config.json --destination NEW-quarterly-publication \
  --catalog-version quarterly-investor-41-arithmetic-ttm-v2
python -m sec_xbrl.metrics.quarterly_screening status \
  --publication NEW-quarterly-publication
```

The optional CLI flag asserts the same selection as config.catalog_version;
a mismatch fails before publication. Omitting the config selector preserves
strict `quarterly-investor-41-v1`. The Python publication API is unchanged:
`publish_quarterly_screening_metrics(config_path, destination)`. The small pure
prepared-input API accepts
`build_quarterly_company_records(..., catalog_version=ARITHMETIC_CATALOG_VERSION)`;
`quarterly_metric_definitions(ARITHMETIC_CATALOG_VERSION)` returns its exact
41 declarations. Neither API selects SEC filings or rebuilds History.

The nine TTM definitions declare
`basis_policy=DECLARED_EQUAL_OR_ALL_NULL_ARITHMETIC_V1`. Amounts use
`definition_version=quarter-ttm-arithmetic-v2` and
`rule_version=quarter-ttm-contiguous-arithmetic-v2`. The four margins use
`quarter-ttm-{gross|operating|net|fcf}-margin-arithmetic-v2` for both identities.
Equal nonempty basis has `DECLARED_BASIS:<original basis>` assurance; all-null
basis has `ARITHMETIC_ONLY_NOT_RECAST_VALIDATED` assurance and retains null.
All other 32 definitions and their observation payloads are unchanged. The
consumer requires the exact new catalog/version/basis contract, checks every
raw/derived dependency and scope, and never recalculates the published sum or
ratio. Rehashed policy downgrades, invented assurance, nested FCF basis/quality
corruption and YTD legs reject. Existing saved dataset context remains pinned;
new TTM execution uses its new definition version and a new publication.

### Reuse boundaries and source freeze sequencing

This change does not modify the relevant History/analysis policy modules hashed
by financial_storage_policy_sources or prospective_policy_sources. ROOT can
compare those exact helper outputs when assembling the final pinned
compatibility artifacts; no compatibility meaning is inferred from a version
label and no original registry or receipt is edited. Existing prepared analyses
and approved storage evidence remain reusable under their existing exact byte,
profile, review, completeness and policy proof contracts.

The actual History.validate and T1–T4 producer code identities still hash the
whole source package, so these two changed Python modules change those identities.
Bind the final frozen source to the latest12 migration options and generate
current routine validation reports/ROOT approvals after the final freeze, before
quality consumers reuse them. Actual latest12/38 preparation was held before this
change, so no just-completed build must be repeated. New actual artifacts,
current/old-collection storage registries, prospective selection/configs and
quarterly publications remain ROOT-owned and must bind the final source and exact
2026-10-25 selection cutoff as appropriate.

ROOT's 2026-10-28 fresh submissions discovery fetched all 50 companies and compared
all 5,842 candidate filing records, including older filings, with the preserved
2026-10-25 snapshots: inventories were identical. The ready 1109-filing canonical
collection therefore retains selection cutoff 2026-10-25; freshness observation
2026-10-28 is separate. No new Raw extraction or old company audit follows from
that unchanged inventory.

### Small reused-fixture evidence and remaining acceptance

On the existing 15-quarter prepared fixture with all basis values null, strict
TTM stays unavailable while all nine new TTM metrics are available. At 2026Q3 the
new values are revenue1000, operating income55, net income40, CFO160, standardized
FCF120; margins are gross30%, operating5.5%, net4%, FCF12%. Gross margin uses
300/1000, rather than the 25% mean of quarterly percentages. Quarter-end cash
remains40 and is never summed. Eligible M8-derived Q4 retains its two complete
reported anchors and actual 1200 four-quarter revenue sum. This is small-fixture
source evidence, not an AMD actual-data or 50-company readiness assertion.

Direct comparison against accepted source e0b6/d359 confirmed identical strict17
and strict41 definitions and identical null-basis strict observations/inventory.
The frozen strict41 definition digest is
`1e1a64235d1b39eca4fe4a45b3362b94764a2d89836e637a234810d1b5aae25c`;
that strict fixture result digest is
`c5183a7e9ed2b5ca42ba70c47c11decfbcb97e7f8659050aec1b7069f3ce2903`.
New config/CLI selection, both readers, new TTM screening/trace/eight-quarter
series and old saved-result context are covered by focused tests. Producer and
consumer retain the existing decimal, money, sign, source-eligibility, bounded
lineage and denominator policies. Actual latest12/38 execution, independent
verification, local release acceptance and main merge are still separate and
pending; the 2026-10-28 user decision authorizes this implementation, not an
unmeasured actual performance/readiness claim.

Writer validation: new arithmetic-catalog focused tests **29 PASS in 6.63 s**;
existing quarterly41/legacy tests **26 PASS in 5.82 s**. Public config/CLI and
saved-context checks are included in the new set. Accepted strict-source direct
equality and golden checks PASS; Ruff/diff and changed-document links PASS.
No large screening suite, old company audit, actual AMD data revalidation, Raw
parse or actual latest12/38 operator was run by the writer. This is IMPLEMENTED
and SELF_VERIFIED source pending ROOT's separate independent review and actual
operator acceptance.

## Arithmetic TTM independent P2 return and exact input-binding repair

Independent review of c17ef6adaaeadd939ed16bbde90e72bb1061800d returned Standards
PASS with zero findings, but Spec FAIL with one P2: the new amount definitions'
input_metric_id was trusted instead of checked against the approved fixed item.
The original Spec FAIL report remains preserved (optional operator record
`independent_arithmetic_ttm_spec_c17ef6.json`, SHA256
`6c25d0ff98a64400faa7e4266b14de4f3104fbbfdfda616aac903af294340ba9`).
The writer first reproduced its exact coherent, rehashed operating-income swap:
ttm_operating_income incorrectly accepted revenue inputs and value1000 instead
of55. Only temporary synthetic data was changed for reproduction.

The repair adds a **new-catalog-only** fixed amount contract:

| Amount metric | Required input metric |
| --- | --- |
| ttm_revenue | quarter_revenue |
| ttm_operating_income | quarter_operating_income |
| ttm_net_income | quarter_net_income |
| ttm_cfo | quarter_cfo |
| ttm_standardized_fcf | quarter_standardized_fcf |

Producer arithmetic, all definition bytes, normal results and existing strict
reader branches are unchanged. The repaired original probe rejects before
consumption with “arithmetic TTM amount requires its exact governed input metric”.
All five coherent rehashed amount swaps now have negative regression coverage.
The exact probe plus 10 focused amount-contract/positive-reader/materialized-value/
CLI/strict-golden cases PASS (10 tests in3.17s, 24 unrelated new-catalog cases
deselected). Ruff/diff PASS. Previous29/26 suites were not blindly repeated and no
actual company audit or latest12 build ran. A new independent repair review and
ROOT acceptance are required; c17's failed report is not retroactively relabeled.
Final whole-package migration/native identities must bind the new frozen source,
while prepared c17 snapshots, controls and evidence remain preserved.


## 2026-10-28 operational handoff snapshot — source accepted, latest incomplete

This is the ROOT-reported handoff-time snapshot, not a full50/latest completion
or release declaration. Source
`451205b08fed2617d6e04f3c209e1a21b8aa9f29` received independent Standards and Spec
repair PASS, then ROOT local acceptance
`LOCALLY_ACCEPTED_SOURCE_NOT_ACTUAL_RELEASE`. The original c17 Spec FAIL remains
preserved separately. The writer's following update is documentation only;
Python/source/test bytes remain exactly the accepted451 snapshot.

ROOT completed a bounded actual-prepared AMD calculation using the preserved
2026-10-10 baseline scope, 2026Q2: all nine new arithmetic TTM observations were
AVAILABLE, with TTM revenue41305000000. Calculation took0.5007s, peak189628KiB.
Its status is `ACTUAL_PREPARED_CALCULATION_PASS_NOT_FINANCIAL_OR_UI_RELEASE`.
This establishes an actual-input calculation sample, not latest financial
publication, 50-company readiness, final UAT or live acceptance.

Latest strict append progressed on source451: NFLX History append completed in
163.35s, peak2198416KiB, annual analysis8.19s and quarterly analysis20.96s.
NFLX, META, PG, TXN and LRCX completed their append/annual/quarter preparation.
The remaining safe nine-company cohort was still running at handoff (GE was the
current company). These per-company preparation results do not imply complete
latest financial metrics or consumer readiness.

The 38-company prospective proof passed in45.88s, peak329436KiB. Its first
attempt correctly rejected a submissions snapshot-list order mismatch against
the canonical plans. ROOT asserted identical file sets, then created a separate
canonical-order summary and separate policy/config_r2; the original inputs and
failed attempt were preserved. The corrected proof passed without changing
producer source or accounting policy. The batch remained in staging at handoff:
17 annual and16 quarterly targets staged, DUK quarterly processing in progress.
No target batch had yet been publicly exposed, so this is not38 prepared
publications READY or latest end-to-end acceptance.

### Separate required decision: three historical input-order mismatches

TSLA's strict prefix gate rejected reuse. Read-only diagnosis established that
its historical25 input contents/identities match the corresponding prior inputs
within the current26, but the historical T1 input list uses accession order while
the current list uses chronological order. The same historical nonchronological
order difference affects IBM and UNP; it does not affect the other nine latest
companies. The original strict gate is retained and no hidden full fallback ran.

Only TSLA, IBM and UNP are held for the user's required choice between:

- Generate NEW current-cutoff History for these three from existing immutable Raw
  through the existing full API, preserving original History, analyses and audits
  (ROOT's recommendation, with no source change).
- First implement and independently verify append support for permuted historical
  input order under a separate explicit source contract.

The answer had not arrived at this snapshot. Full generation/fallback for the
three is **not yet authorized** and must not be inferred from source451 acceptance
or from continuing the safe nine-company cohort. Existing Raw, original History,
accepted analyses and old company audits remain preserved.

### Remote CI, protected runtime and remaining acceptance

ROOT pushed source451 and created/attached draft
[PR67](https://github.com/pluswc/sec_xbrl/pull/67). Its required test CI passed in
4m13s, [run40684132845, job122802058728](https://github.com/pluswc/sec_xbrl/actions/runs/40684132845/job/122802058728).
CI acceptance applies to source451; it does not substitute for actual latest
financial/UAT acceptance. The writer's docs-only handoff commit is local and
unpublished, avoiding another CI run. Main merge and live runtime changes remain
unperformed until actual50 refresh and UAT are accepted.

ROOT rechecked protected catalog/journal hashes against the pre-work pins: they
remain identical, and live21 is unchanged. Remaining work includes the required
three-company decision and authorized disposition, completion/publication of the
safe cohort and38 batch, final latest financial publication/TTM availability,
end-to-end private UAT and separate release/main decisions. The completed baseline
and original approvals are not rerun or overwritten by this status update.

Optional operator evidence in `work/quarterly50_expansion_20261025/`:
`lead_arithmetic_ttm_source_acceptance_451205b0.json`,
`actual_amd_arithmetic_ttm_451205b0.json`, and
`latest12_historical_order_inventory_20261028.json`.
These supplement the tracked status/decision boundaries above and are not its
sole authority or a prerequisite for understanding the checkout.

## 2026-10-30 상태 후속 — 사용자 결정 해소, 49개사 준비 및 JNJ 진행 중

이 절은 앞선 날짜별 스냅샷 이후의 상태를 추가한다. 앞선 승인 대기와 진행 중
기록은 당시 상태로 보존하며, 완료되지 않은 실제 발행이나 출시를 소급하여
승인하지 않는다. 제품 source freeze는 계속
`451205b08fed2617d6e04f3c209e1a21b8aa9f29`이고 이번 변경은 문서만이다.

사용자는 2026-10-29 TSLA·IBM·UNP 세 회사에 한하여 기존 불변 Raw와 정상 공개
full API를 이용한 새 current-cutoff History 생성을 승인했다. 기존 결과와 회사별
감사 증거는 보존하며, 순서 순열을 허용하는 append 코드나 숨은 fallback은
추가하지 않았다. 이로써 앞선 세 회사의 필수 사용자 결정 대기는 해소됐다.
TSLA·IBM·UNP와 NEE는 모두 연간·분기 분석 준비를 완료했다.

38개사 prospective batch도 실제 PASS로 완료됐다(1667.75초). 기존에 완료한
7개 증분 회사와 위 4개사를 합쳐 현재 49개사의 연간·분기 분석이 준비됐다.
이는 입력 분석 준비 상태이며, current50 금융·지표·데이터셋 발행 완료를 뜻하지
않는다.

JNJ만 미완료다. 첫 시도는 AS_FILED reported 6개 구간을 완료하고
LATEST_REPORTED/FY 인코딩으로 진행한 뒤 3600초 시간 guard에 도달했다.
완성된 reported-stage manifest가 없어 해당 6개 구간의 공개 resume는 불가능하다.
ROOT는 현재 23개 filing의 fingerprint와 일치하는 완료 T1–T4를 재사용하는 정상
공개 빌드를 단 1회 승인했다. 기존 약 11GiB partial은 보존하고 별도 새 partial에
reported stage를 다시 생성하며, 제품 코드·회계 정책·옛 회사 감사는 변경하거나
재실행하지 않는다. 재시도는 2026-10-30 00:08 KST에 시작했고 이 스냅샷에서는
아직 진행 중이다. 운영 상한은 10800초, RAM 16GiB, 최소 여유 공간 8GiB이며,
구간별 진행을 계측한다. 이 예산은 AS_FILED 약 54분과 다음 view·quarter 처리
여유에 근거한 상한이지 완료시간 보장이 아니다.

남은 수락 범위는 JNJ 준비 완료, current50의 6개 발행 단계 전체, 새 산술 TTM을
포함한 private UAT, 별도의 main merge와 live 적용이다. 모두 여전히 pending이다.
앞서 완료한 baseline 발행·private UAT와 source451의 독립 검토·CI PASS는 이
latest/current50 수락과 구분한다. 기존 Raw·History·분석·감사 및 live21의 보호된
catalog/journal은 보존한다. 이번 문서 커밋은 로컬에만 남기며 push하지 않는다.

보조 운영 증거는 `work/quarterly50_expansion_20261025/`의
`full_history_three_user_approval_20261029.json`,
`jnj_completed_roots_resume_approval_20261030.json` 및
`latest_execution_451205b0/items/{TSLA,IBM,UNP,NEE}-quarterly.json`이다.
이 파일들은 위 추적 문서의 승인·미완료 경계를 보충하며 단독 권위나 필수 읽기
자료가 아니다.

## 2026-10-30 상태 후속 — 100개 분석·quality 완료, identity 보정 승인 대기

이 부록은 앞선 49개사 준비·JNJ 진행 중 스냅샷 이후의 상태다. 이전 날짜별
기록과 문서 커밋 `42fe27f859628afd00c670560db0a8b980bbda2f`의 당시 상태는
보존한다. 제품 source freeze는 계속
`451205b08fed2617d6e04f3c209e1a21b8aa9f29`이며 이 변경은 문서만이다.

JNJ의 정상 공개 빌드는 현재 23개 filing의 완료 T1–T4를 재사용하여 PASS로
완료됐다. History 처리 시간은 8938.42초, peak4546912KiB였고 연간 분석68.31초,
분기 분석389.53초로 각각 PASS다. 이에 따라 current50의 연간·분기 분석 총
100개가 모두 PASS로 준비됐다. 기존 partial과 완료 보고서는 보존하며 다시
생성하거나 옛 회사 감사를 재실행하지 않는다.

current50 발행의 quality 단계도 276.40초, peak11299012KiB로 PASS다. identity는
첫 시도에서 RAM16GiB 운영 guard로 중단됐다. ROOT는 RAM24GiB 예산과 시스템
가용 메모리 최소4GiB guard로 identity만 다시 실행했고, 161.06초,
peak19078096KiB에서 실제 `ValueError`가 발생했다. 이 두 번째 결과는 단순 자원
guard 중단과 구분한다. 완료된 quality와 100개 분석은 보존하며 재생성하지 않는다.

제한된 읽기 전용 최초 차이 진단은 AAPL / ANNUAL / AS_FILED / `trace_0`의
첫 행에서, 기대 dict에는 `availability_note` 키가 없고 실제 재독출 dict에는
`availability_note=None`이 추가되어 있음을 확인했다. 이 관측만으로 실제 금융
값의 차이라고 확정하지 않는다. 원본 trace shard를 새 ID로 재분할할 때 Parquet
열 합집합이 누락 키를 null로 채우고, 소비자가 저장 전 dict와 정확 비교하는
transport shape 차이가 확인된 원인이다. 다른 완료 회사의 검증을 반복하지 않았다.

권장 보정 제안은 dataset의 최상위 열 합집합 안에서만 누락 키를 null로
정규화하고 실제 열 집합을 정확히 검증하는 것이다. 중첩 lineage·값·행 개수와
순서는 그대로 정확 비교한다. 소스 변경에 대해서는 원본451 보고서와 소스 증거를
보존하고, 승인된 정확한 코드 변경 및 동일 정책·입력에 한정한 명시적 code/source
compatibility 전이 증거를 결속하는 방안을 제안했다. 검증 생략, 보고서 rewrite,
임의 추가 열 무시 또는 회계 의미 변경을 허용하는 제안이 아니다.

ROOT는 위 형식 비교 보정과 명시적 호환성 증거에 대한 사용자 승인 질문을
보냈으며, 이 스냅샷에서는 답변 대기 중이다. **이 보정 범위는 아직 구현 승인을
받지 않았다.** 제품 코드·테스트·지침은 변경하지 않았으며 새 보정 구현이나
데이터 재생성도 실행하지 않았다.

identity를 포함한 quality 이후 나머지 5개 발행 단계, private current50 UAT,
별도의 main merge와 live 적용은 모두 pending이다. ROOT가 준비한 live operator와
새 UAT harness도 아직 실행하지 않았다. baseline 및 source451 수락은 이 미완료
current50 발행·UAT·운영 적용을 대신하지 않는다.

보조 증거는 `work/quarterly50_expansion_20261025/`의
`latest50_identity_current_451205b0.log`,
`latest50_identity_resume24_20261030.log`,
`publish_latest50_pipeline_20261030.log` 및
`reselection_first_difference_20261030.json`이다. 위 기록은 추적 문서의 상태와
승인 경계를 보충하며 단독 권위나 필수 읽기 자료가 아니다.

## 2026-11-02 승인 및 구현 — nullable transport 비교와 명시적 소스 전이

사용자는 2026-11-02 「형식 검사·호환성 근거 보정 후 계속」을 승인했다. 앞선
2026-10-30 승인 대기 기록은 당시 상태로 보존한다. 이번 범위는 값이나 회계
선택을 바꾸지 않는 재선택 transport 비교와, 완료된451 증거를 정확한 새 소비자
소스로 연결하는 선택적 증거다. 기준일은 계속 2026-10-25이며 새 수집은 없다.
기존50 History·100개 분석·quality·보고서·Raw·journal·live21은 불변이다.

수락 조건은 다음과 같다.

- 기대 dataset 전체의 최상위 키 합집합과 실제 Parquet 열 집합이 정확히 같아야
  한다. 합집합 안의 누락 키만 행별 `None`으로 비교하며 원본 dict는 수정하지
  않는다. 전체 정규화 복사본을 추가하지 않는다. 값·중첩 키·행 순서·행 개수,
  알 수 없는 추가 열(모두 null인 열과 빈 테이블의 열 포함)은 그대로 거부한다.
- 전이 증거가 없으면 기존 source/code identity 일치 검사를 유지한다. 증거가
  있으면 원본451 전체 Python 소스 inventory와 bytes, 현재 전체 inventory,
  정확한 허용 변경파일과 전후 SHA, 동일 rules, 각 기존 native report·build·
  History·declared payload pin을 검증한다. ROOT 승인 없는 변경, 전이 역방향,
  미래의 추가 변경, History/Raw/회계 선택/규칙 파일 변경은 허용하지 않는다.
- 기존38 prospective manifest·정책·origin registry와 quality의 선언·controls·
  결과 equality는 그대로 재검증한다. 새 전이 증거는 새 identity config와
  현재 source closure에 별도로 결속한다. 기존 보고서/marker rewrite, 검증
  생략, quality 재발행이나 분석 재생성으로 해결하지 않는다.

`prospective_selection.py`의 비교만 nullable 최상위 열 형태를 보정한다.
`financial_source_compatibility.py`는 directed 증거 검증과 proposal 생성을 맡는다.
`financial_storage_reuse.py`는 선택적 검증 객체를 받아 기존 native report의
정확한451 code identity를 현재 동일 rules 아래 연결한다. quality/identity와
verified source closure는 이 증거를 전달하고 모든 source/evidence bytes의 현재
신선도를 결속한다. 전이 검증 객체는 resolver가 발행한 issuer/seal이 필요하며
호출자가 만든 임의 객체는 거부한다. 기존 routine 검증기 자체는 변경하지 않는다.

### 새 증거 및 호출 계약

새 identity config에만 아래 선언을 추가하고 기존 quality root와 SHA를 그대로
참조한다. 기존 quality config나 publication을 수정하지 않는다.

```json
"source_compatibility": {
  "path": "/absolute/governed/source-compatibility.json",
  "sha256": "<exact packet SHA-256>"
}
```

ROOT는 최종 동결 소스를 로드한 뒤 다음 공개 proposal 함수를 사용한다. 함수는
metadata와 소스 bytes만 읽으며 쓰기·회사 검증 재실행·승인을 수행하지 않는다.

```python
from sec_xbrl.financial_source_compatibility import prepare_source_compatibility_packet

packet = prepare_source_compatibility_packet(
    origin_source_root=source451_root,  # .../src/sec_xbrl
    preserved_controls=[quality_manifest_pin, prospective_manifest_pin,
                        origin_storage_registry_pin, current12_storage_registry_pin],
    routine_histories=[
        {"report": report_pin, "build_manifest": build_pin,
         "history_manifest": history_pin},
        # Each of the 12 exact completed native reports is explicit.
    ],
)
# ROOT reviews the exact source diff and packet, then explicitly approves a NEW
# artifact by changing packet["status"] from PROPOSED to ROOT_APPROVED.
```

packet schema는 `financial-source-compatibility-v1`이다. 정확한 필드는
`schema_version`, `status`, `origin_revision`(451 전체 SHA), `origin_source_root`,
`origin_source_sha256s`, `current_source_sha256s`, `approved_changes`,
`preserved_controls`, `routine_histories`다. inventory 키는 package 상대 Python
파일명이며 값은 SHA-256이다. 각 변경은 `origin`/`current` SHA를 명시한다.
각 routine 항목은 `report`, `build_manifest`, `history_manifest` pin과
`declared_payload_sha256s`, `rules`, `origin_code_identity`,
`current_code_identity`를 포함한다. 중복 pin/report와 unsafe source alias는
거부한다. 기존 code identity는 digest 목록만으로 추정하지 않고 원본451의
hash-bound 소스 bytes와 정확한 기존 identity 알고리즘으로 재계산한다.

따라서 **원본451 코드 snapshot은 명시적인 필수 증거 입력**이다. ROOT는 선택적
work snapshot과 분리한 `data/processed/source_evidence/<451 SHA>/src/sec_xbrl`
같은 governed 위치에 동일 bytes를 복사·hash 대조해 보존할 수 있다. 특정 경로는
엔진에 하드코딩하지 않는다. 이는 과거 runtime/checkout의 신선도나 새 semantic
감사를 주장하지 않으며, 승인된 불변 소스 증거 bytes를 검사하는 계약이다.
새 artifact와 새 config는 새 경로에 기록한다. 새 identity를 다음 기존 공개
함수로 발행하면 기존 quality를 위 증거 아래 다시 읽는다.

```python
from sec_xbrl.screening.metric_identity import publish_generic_metric_identity

publication = publish_generic_metric_identity(new_identity_config, new_identity_destination)
```

이 구현의 자체 검사는 새 synthetic 경계와 인접 기본 경로, 실제 AAPL 연간 한
건으로 제한한다. 완료된 회사 감사·100개 분석·quality 생성은 반복하지 않는다.
독립 검토와 ROOT 인수는 별도이며, current50 identity 이후 발행·private UAT·
main merge·live 적용 완료를 이 코드 구현만으로 선언하지 않는다.

자체 focused synthetic 결과: 신규20개와 인접 기존 기본 경로2개, 총22개 PASS
(6.91초). 새 identity의 public publish/reopen이 기존 quality·native report bytes를
보존하는 것, 기존 prospective+origin registry controls equality, commit 경계의
전이 packet 변조 거부를 포함한다. 미승인 validator 변경·역방향·규칙/report/
payload 변조·미래 추가 변경·알 수 없는 control·source alias·위조 객체도 거부했다.
Ruff와 `git diff --check`는 PASS다. 큰 기존 suite나 완료 회사 감사는 반복하지
않았다. 실제 AAPL 연간 한 건의 동결 후 회귀와 별도 독립 검토는 아직 다음 단계다.

### 2026-11-02 동결 및 실제 한 건 회귀 결과

제품 소스는 `9846357496e3deca84a66ee082dc7bd3d154606f`에 로컬 동결했다.
그 뒤 실제 AAPL ANNUAL의 declared view 전체(AS_FILED 포함)에서 공개
`verify_reselected_analysis` 비교가 PASS했다. 2026-10-25 기존 selection pin과
AAPL 현재·원본 분석 manifest pin을 확인한 뒤 해당 한 건만 비교했으며,
전체 cohort proof replay나 publication/data 쓰기는 하지 않았다. 처리1.7717초,
peak538588KiB였다. 앞서 확인된 `trace_0` 최상위 null padding 차이는 허용하되
동일 dataset의 나머지 값과 구조를 그대로 비교한 실제 회귀다. 이는 current50
identity 발행이나 전체 UAT PASS 선언은 아니다.

자체 synthetic 명령은 다음과 같다(`POLARS_MAX_THREADS=2`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src:.`).

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/screening/test_financial_source_compatibility.py \
  tests/screening/test_prospective_selection.py::test_prospective_selection_new_event_preserves_raw_and_old_bundle \
  tests/screening/test_financial_storage_reuse.py::test_current_routine_v2_reuses_completed_light_checks_without_full_typed_claim
```

최종 소스의 독립 읽기 전용 검토와 ROOT 인수는 아직 별도 절차다. ROOT는 검토
수락 후 최종 동결 소스에서 새 packet을 생성·명시적으로 승인하고, 새 identity
config/destination으로 기존 quality를 참조하여 미완료 단계만 진행한다. 원본451
소스·보고서·quality와 실패 로그는 보존한다. 이 문서 결과 후속 커밋은 제품
소스를 바꾸지 않으며 push/main/live 적용도 수행하지 않는다.
