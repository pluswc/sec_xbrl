# Company history intake and persisted fiscal panels

## Completion contract

**Feature complete** means arbitrary resolved tickers plus an explicit report-date
window (or recent annual-baseline count) can pass discovery, resumable Layer 1
intake, governed publication, and an offline persisted-panel query. Tests of
this code do not prove that a particular requested corpus was collected.

**Run complete** means every accession in that run's immutable plan passed the
Layer 1 gates, every operational publication agrees on those raw inputs, and
the persisted fiscal panels were verified and reloaded. Failed downloads or
parses cannot become `MISSING_HISTORY`, and incomplete intake exits nonzero.
Neither status means every potential metric has a reported quarterly value.

## Reusable interface

Use Python 3.12 with this source revision on the import path. Network stages
read the already-authorized SEC contact identity from `SEC_USER_AGENT`; do not
write this value to commands saved in source, manifests, or logs. Paths below
are user-selected output locations, not fixed ticker-specific paths.

```bash
python -m sec_xbrl.history discover --tickers NVDA AMD MSFT \
  --workspace work/my-history --as-of 2026-09-06 \
  --report-start 2023-01-01 --report-end 2026-09-06
python -m sec_xbrl.history ingest --plan work/my-history/plan.json \
  --output-run data/processed/history_runs/my-history \
  --package-cache data/raw/history_packages --index-cache data/raw/history_indexes \
  --taxonomy-cache data/taxonomy_cache --bootstrap-taxonomy
python -m sec_xbrl.history build \
  --intake-manifest data/processed/history_runs/my-history/history_intake.json \
  --output-root data/processed/analytical/history/my-history
python -m sec_xbrl.history query \
  --publication data/processed/analytical/history/my-history/panels \
  --ticker NVDA --period-class QTD_3M --view LATEST_REPORTED
```

Discovery also accepts `--recent-fiscal-years 3` instead of the two report
bounds, and repeatable `--submissions-root` paths with `--offline` for cached
discovery. Report bounds refer to actual SEC report dates, not calendar labels
assigned to company quarters. `--as-of` independently limits filing availability.
Repeated `--source-run` options on intake reuse verified snapshots from earlier
runs without copying raw tables or fabricating new source manifests.

An existing plan cannot be replaced with a different scope. Use a new workspace
for a later as-of date or changed interval. Ingestion retries archive their old
manifest and append accession outcomes. Arelle first loads offline; explicit
bootstrap permission allows cache population after failure, followed by a
separate offline load. Each extraction attempt has its own directory.

## Published output and interpretation

T1–T4 are built once per declared cohort and verified before reuse. `reported-panels/`
keeps selected reported values; the default build then materializes the
approved-core quarter companion and returns `panels/` for consumers. `panels/`
contains a publication manifest plus `CIK/view/period_class/{columns,rows,cells}.parquet`.
Scalar values are typed Parquet fields; nested provenance is JSON-valued columns,
not JSONL copies of the complete dataset. Integrity hashes are per output file,
not per analytical row. The query command reads only these persisted tables:
it does not contact SEC, parse filings, select versions, or rebuild a panel.

The default company-history panel contains `CURRENT_FOCUS` observations, so a
prior-year comparative number is not mislabeled with the newer filing's fiscal
year. All comparative observations remain in T1; the manifest reports the
excluded-from-default-view count by CIK. `AS_FILED` and `LATEST_REPORTED` remain
separate views; the latter is not an evidence-backed recast view. It includes
eligible directly reported amendments without treating a partial amendment as
a replacement for every fact in the original filing.

QTD, YTD6M, YTD9M, FY, TTM and instant series remain separate. The latest incomplete
year stops at its latest collected fiscal quarter, rather than inventing future
missing columns. Expected coverage comes only from verified filing form and DEI
fiscal focus. Annual-length note facts require fiscal-boundary evidence to be
FY; rolling annual values ending at interim focus become TTM. Neither TTM nor
an ambiguous annual duration establishes annual filing completion.
A complete annual year exposes Q1–Q4; absent quarterly Q4 is
`UNAVAILABLE / DERIVATION_NOT_MATERIALIZED`, not absent ingestion and not a
reported FY substitute. The connected producer fills eligible standard core
Q4 and missing cash-flow Q2/Q3 by governed cumulative differences, retaining
reported and derived lineage separately. Unsupported/ambiguous cases remain
unavailable; this is not a guarantee that every XBRL concept has four values.

Rows retain full dimensions, standard/custom classification, canonical mapping
and navigation lineage. Same raw fact repeated across navigation paths coalesces
without losing those paths. Equal-scope unresolved value conflicts remain
unavailable cells. Four-statement PRE membership is preference evidence after
version and period agreement, not permission to override a different context.
Calendar comparability retains actual boundaries and the existing fiscal-month
signal; it is not complete fiscal-calendar-regime detection. Growth, ratios and
cross-company semantic comparison are not computed by this workflow.

Custom facts are available with raw identity and mapping review state, but their
presence is not proof of aligned custom-concept continuity across quarters.
The earlier reported-only five-company run did not demonstrate a custom-concept
row joined across multiple columns. Custom continuity v3 rebuilds those series
using qualified raw-role and neighboring concept evidence, retaining uncertain
changes as separate rows. No label-only mapping is introduced. Operational
before/after counts must distinguish numeric monetary custom series from text,
resource nodes, and standard concepts shown under custom members.

`repair-coverage --publication OLD --destination NEW` is a narrow migration for
the initial run's erroneous synthetic future columns: it revalidates the raw
filing metadata, removes only unbacked empty quarterly columns, and preserves
every actual row/cell. It never replaces the old publication or reselects facts.
The new manifest records the old path, manifest digest and removed columns.

The earlier reported-only release can be upgraded without repeating T5 graph
traversal using `python -m sec_xbrl.analytics.history_quarters --publication OLD
--output-root NEW`. It builds fresh correctly classified T1–T4, re-attests every
selected cell to those raw observations, repartitions FY/TTM, and materializes
the same core-quarter producer used by the default build. Previous candidate
lineage is explicitly labeled prior-publication evidence. Existing publications
and raw stores are never overwritten.

The implementation must be independently verified on a frozen revision before
release. Operational run results are reported separately with actual filing,
company, period and row counts; a code commit alone is not execution evidence.

## Complete reported-stage recovery (2026-10-13 technical exception)

`recover_reported_history` / `recover-reported` is a producer recovery boundary,
not a reader permission to consume failed partial publications. It is limited
to a **complete reported-only stage independently verified in full**. Failed
Raw intake, missing chunks, incomplete tables, and policy-held filings remain
ineligible. The lead authorized this narrow exception after repeated actual
JNJ high-memory failures. The latest observed failure left all 12 reported
panels and a staged manifest, without the publication rename, and exited by
SIGKILL 137 at about 29.58 GiB peak RSS. A verifier-phase memory failure is a
strong control-flow inference, not a traced stack or confirmed kernel OOM diagnosis. The implementation role was explicitly escalated to Astra;
a separate Astra must independently verify the frozen candidate. This records
a role decision, not a measured model speed/cost/quality claim.

The public Python signature is:

```python
recover_reported_history(
    *, staged_publication: Path, output_root: Path, intake_manifest: Path,
    operational_root: Path, attestation: Path, expected_attestation_sha256: str,
    trusted_exclusive_parent: bool,
) -> Path
```

The caller supplies an **external independently pinned attestation file and its
expected SHA-256**. Do not generate the expected attestation solely by reading
the stage being recovered. The independent verifier must compare the complete
source execution inventory, decode every field of every declared record,
compare ordered execution logs and applicable authenticated prefix evidence,
and attest all original intake/Raw/T1–T4 identities before issuing `PASS`.
The attestation JSON has these required fields:

- `version`: `reported-stage-recovery-v1`; `status`: `PASS`.
- `generation_source_identity`, `recovery_source_identity`: distinct execution
  identities expressed as full 40-character Git SHAs. They may be equal if the
  same source produced and recovered a future run; neither changes parser
  identities in Raw or operational publications.
- `staged_manifest_sha256`, `intake_sha256`, `input_fingerprint`.
- `plan`: exact original plan, including companies/CIKs/filing inventory and
  `as_of_date`; `views`: exact ordered original views.
- `tables`: exact ordered original table declarations, including identity,
  scope and all three `columns`/`rows`/`cells` file declarations. Each file
  includes its original `path`, `sha256`, `count`, `json_fields`, plus `schema`
  as ordered `[column_name, str(polars_dtype)]` pairs. All expected paths must
  be `CIK/view/period_class/name.parquet`. No inferred missing tables are allowed.
- `operational_manifest_sha256`: independently pinned `t1`, `t2`, `t3`, `t4`
  manifest digests at the **original** operational root.
- `verification_report`, `source_execution_log`: each contains a `path` and
  `sha256`. The log's ordered `PANEL_WRITTEN` JSON records must exactly agree
  with table identities and row/cell counts. Other log lines may be non-JSON.
  The report must also satisfy the full component contract below; byte-only,
  metadata-only, unbound or incomplete reports cannot authorize recovery.
- `required_prefixes`: ordered list of `{path, count, expected_sha256}` for
  externally authenticated prefix controls; use `[]` only when the independent
  execution contract requires no prefix comparison.

The independently pinned verification report must contain:

- `schema_version`: `independent-staged-reported-component-audit-v1`;
  `verdict`: `PASS_STAGED_REPORTED_COMPONENT_ONLY`;
  `verification_level`: `FULL_STAGED_REPORTED_PASS`; `history_ready`: `false`.
- `fixture_kind`: `ACTUAL`, `CACHED_TEST` or `SYNTHETIC_TEST`, explicitly
  distinguishing real component evidence from test fixture assertions.
- `source_generation_sha`, `stage_manifest.sha256`, `source_intake.sha256`,
  `input_fingerprint`, matching the pinned attestation exactly.
- `counts.tables`, `counts.stage_files`, matching the complete expected inventory.
- `full_verification`, with all five booleans true:
  `all_reported_files_fully_decoded`, `all_ordered_records_hashed`,
  `all_json_fields_decoded`, `all_physical_hashes_verified`,
  `all_schema_counts_verified`.
- `verified_files`, in manifest table order then `columns`, `rows`, `cells`
  order: each exact attested file declaration (including physical schema),
  plus `ordered_full_record_sha256` from the independent complete-record audit.
  The report binds that digest to the exact file SHA/schema/count. Recovery
  independently rehashes the bytes and decodes every JSON record; it does not
  reinterpret the independent auditor's digest encoding. The actual component
  auditor hashes ordered typed raw records (including exact encoded JSON text)
  and separately validates all nested JSON. Test reports label their fixtures
  and hash the complete ordered decoded fixture records.
- `prefix_checks`: exactly one result per `required_prefixes` entry, preserving
  its fields and adding `actual_sha256` equal to `expected_sha256` and
  `status: PASS`. Missing, incomplete or mismatched prefix controls fail closed.

These checks prevent accidentally using a byte-only report in place of full
component evidence. Independence and the expected attestation hash remain an
external workflow trust boundary; the program cannot determine who authored a
report. An unbound draft is not executable recovery authorization.

For the failed JNJ execution, completeness means 12 tables and 36 payload files.
These numbers are an execution-specific expected inventory, not hard-coded
company or period policy. Other complete executions require their independently
established exact inventory.

Use the frozen, independently accepted source revision on `PYTHONPATH`:

```bash
python -m sec_xbrl.history recover-reported \
  --trusted-exclusive-parent \
  --staged-publication /absolute/original/.panels.partial-complete \
  --output-root /absolute/new-recovery-run \
  --intake-manifest /absolute/original/history_intake.json \
  --operational-root /absolute/original-operational-run \
  --attestation /absolute/independent/attestation.json \
  --expected-attestation-sha256 EXTERNALLY_PINNED_ATTESTATION_SHA256
```

The program verifies the complete stage inventory and file hashes, physical
schemas, counts and all declared JSON fields; validates the complete selected
Raw release using the existing adapter and each T1–T4 root with the public
reader; then copies the original manifest and payload bytes into a **new**
staging root. It repeats full copied-stage checks, atomically publishes
`reported-panels`, and invokes the existing quarter producer with the exact
original `operational_root`. The source failed stage is never renamed,
promoted, relabeled or modified. An output inside an immutable source root is
rejected. Existing output roots are rejected.

The returned path is the new `panels` publication. A sibling
`reported_recovery_receipt.json` records the pinned attestation, original stage
manifest/intake hashes, original generation source, recovery source and output
paths. It does not alter the original reported manifest bytes. The quarter
manifest's `supersedes_publication` identifies the new reported parent while
its `source_manifest_sha256` still identifies the unchanged original manifest.
Recovery failures preserve the new transaction and all workspaces/chunks. No
recovery artifact tree is recursively deleted, even when ownership still appears
unchanged. The default public history reader denies the entire recovery subtree
until its validated COMPLETE receipt exists. Presence of `panels` or a consumer
manifest alone is not completion. The old failure evidence and source stage
remain unchanged. See the dated retention decision below.

### Memory and verification limits

`HistoryPublicationReader.load` and `_records` keep their eager tuple/scalar
contract. `verify_all` returns `None`, reads every declared reported and derived
file, and fully JSON-decodes every declared field in every record. File hash
failure precedes row-count failure, which precedes JSON-schema/decode failure.
All path components, including ancestors and the manifest, reject symlinks.
Unknown/duplicated/non-string JSON field declarations fail closed.

Verification uses fresh nonparallel, low-memory Polars scans of 32-row slices,
with exact slice count and physical schema checks. It does not use background
batch prefetch, sampling or field projection. Producer files use 32-row groups.
The bound applies to retained encoded rows; a single large nested record and
native Parquet page/dictionary buffers can exceed it. It is **not a universal
byte/RSS cap for arbitrary Parquet files**. Actual resource-gated verification
is still required before accepting a large execution.

Build-only graph/period/ledger owners are released before verification and
quarter production. Quarter source-result, partition, candidate and assembly
lifetimes are scoped separately. Encoded staging owns all fields before native
merges, and boundary reconstruction iterates full decoded cell batches.
Accounting rules, values, dimensions, IDs, candidate provenance and ordering
remain governed by the existing producer contracts.


### Recovery trust and transaction repair after source 655 review

The old `65513173…` candidate failed independent review for hash/read and
rollback ownership races. The attestation/report schema remains unchanged. The later retention decision
below adds an explicit trusted-parent API/CLI acknowledgment. Evidence JSON and the execution log are now read through no-follow
handles once, hashed as immutable bytes, and parsed from those same bytes.
Original reported manifest bytes are copied from that authenticated buffer.
Pinned inode/size/mtime/ctime and ancestor identities reject later exchanges or
mutations before completion. Raw snapshot and T1–T4 trees are pinned around the
existing public validators; returned operational manifest hashes must match the
expected pins. No parser, schema, accounting or derivation policy changes.

The destination's parent must already exist. Recovery exclusively creates the
absent leaf via its held parent directory handle, retains its directory inode
and handle, and checks ownership before writes, renames and receipts. The later
retention decision removes rollback deletion entirely.
Copies use no-follow source descriptors, hash the actual bytes streamed to new
exclusive destination files, and check source identity before and after copying.
Copied and reported manifests are rebound to their authenticated bytes. Scoped
storage guards check source/output identity around quarter writing and final
publication. They are inactive during ordinary history operations.

Destination roots inside the failed stage, original operational root or any
intake Raw source root are rejected. An existing requested output is rejected.
Moved roots are left for explicit inspection. Linux no-follow and directory-FD
facilities are required. No files are searched for or removed to repair an
exchanged pathname. The initial directory binding has the explicit trusted-parent
boundary defined below; mkdir/open is not claimed to provide atomic ownership.

The source and output locations remain subject to the operational immutable-input
and single-writer contracts. Identity guards detect exchanges at the validation
and mutation boundaries; they are not a filesystem lock or a guarantee against
an adversarial process continuously modifying the same user's files.


### 2026-10-13 retention and NOT_READY decision after source b0aa FAIL

Independent `b0aa40d…` review found two remaining P1 ownership races: replacement
between successful mkdir and first open, and a replaced child deleted by recursive
rollback. Its FAIL report SHA is
`8a8b786795a83e8c3b67185b31f0013a7a9fb296aaab841c9a49f4db8a486947`.
Both prior FAIL reports and their artifacts remain immutable. The lead authorized
this narrower nonaccounting technical change under the existing 50-company task;
it changes failure retention/readiness only, not Raw, values, accounting, period,
source selection, scope or financial release policy.

The operator must pass `trusted_exclusive_parent=True` (CLI
`--trusted-exclusive-parent`) and ensure exclusive sole-writer use of the existing
parent during initial creation. The program requires that parent to be owned by
the effective user and not group/world writable; a dedicated mode-0700 parent is
recommended. This is an operator contract, not a new interactive permission flow.
A nonempty replacement is rejected before any transaction writes. Root, ancestor
and captured descendant identities are checked at storage boundaries thereafter.
No existing destination files are overwritten. **An empty same-UID replacement
between mkdir and the first identity capture is outside this supported trust
boundary.** Portable mkdir/open cannot prove atomic creation ownership. Protection
against such an adversarial same-user process requires separately isolated OS
ownership and is not claimed by this implementation.

Before any reported payload is copied, recovery creates a permanent
`.history-recovery-<transaction SHA256>/transaction.json` control directory and
immutable NOT_READY metadata. Its hash-named parent binds the exact bytes, root
inode/path, token, source-generation/recovery identities, attestation/report hashes
and input fingerprint. Missing or malformed metadata fails closed once that
control directory exists. Recovery metadata is not to be removed or edited;
removing every trace of recovery metadata to disguise the root as a legacy
publication violates the immutable-output/sole-writer contract.

All default `HistoryPublicationReader` and `open_history_publication` access to
that root or descendants is denied until the COMPLETE gate validates. This also
applies to `allow_staging=True`, existing reader `load`/`verify_all` calls, and
consumer APIs using those public readers. It is an API boundary, not a restriction
on arbitrary operating-system reads. Internal reported/quarter verification uses
an explicit root-bound capability, valid only in the active recovery context;
there is no unscoped staging bypass. Legacy non-recovery reads are unchanged.

After full reported and quarter verification, expected consumer provenance and
source/root/descendant checks, the program atomically creates
`reported_recovery_receipt.json` with an exclusive hard link from a new immutable
temporary receipt. An existing receipt is never replaced. The receipt binds the
transaction token/hash, authenticated source/report identities and both manifest
hashes. Default reads check those bindings. Reported manifest/payload bytes remain
identical; quarter parent paths remain the intended final output paths.

Failures retain all newly created artifacts with no COMPLETE gate. Even an already
written final consumer manifest remains NOT_READY. Recovery disables recursive
cleanup, including TemporaryDirectory finalizers and quarter `.chunks` deletion.
Publication directory renames use Linux `renameat2(RENAME_NOREPLACE)`; absent
support fails closed with retained artifacts. Recovery JSON publication also uses
exclusive creation/linking rather than replacing existing files.
Successful recovery also retains these diagnostic chunks plus temporary JSON and
receipt files, increasing disk usage beyond the declared payload. Paths include
`panels/.chunks`, nested `.<file>.chunks-*` and `.receipt.partial-*`; they are not
extra declared tables. No automatic deletion or cleanup is authorized. Outside
recovery, existing workspace cleanup behavior remains unchanged. The superseded
acceptance condition “no failed output directory remains” is now “failed artifacts
remain non-consumable, no COMPLETE is published, and no source/unrelated data is
overwritten or deleted.” New source freeze, independent PASS and lead GO remain
required before actual recovery.


### 2026-10-13 complete-reader gate repair after source 721 FAIL

Independent source `7218940…` review found three gate defects: a structurally
bound COMPLETE receipt could disguise reported-only tables as a completed
consumer; a dangling receipt symlink could fall through to legacy behavior;
and some immutable receipt locators/version fields were not compared. The FAIL
report SHA is
`9ad160be37b8c5d07aec2301625c570540ce39a095dfd2e16b08dbbaf0224a33`.
That report and all previous source/failure evidence remain unchanged. The lead
authorized this technical gate repair within the same nonaccounting scope.

The producer and default gate now share the governed completed-consumer predicate:
reported-only source kind, exact parent manifest hash and locator, matching
plan/views/intake/fingerprint/operational parents, active period/derivation rule
identities, completed quarterly status, complete nonduplicated company/view table
inventory, and a valid declared derived-quarter artifact with its own hash,
physical ordered field/type/JSON declaration schema of the selected quarter-rule
producer and count. A valid zero-row governed derived file is
allowed; absence of the artifact or reported-only status is not completion.
This predicate uses metadata and native row count, not eager whole-record decode.
Existing full bounded `verify_all` remains responsible for full declared-record
JSON integrity. It does not recompute accounting in the reader.

The control directory also retains the exact authenticated `attestation.json`
and `verification_report.json` byte buffers. Their immutable transaction hashes
bind them. Default gates recheck the existing FULL_STAGED_REPORTED report contract,
source generation/input fingerprint and exact reported inventory from these local
copies. Consumer reads therefore do not depend on reopening external attestation
or report locators. Report locator fields remain optional under the existing
report schema; if present, they must match the original source stage/intake.
No new actual attestation or original source report is generated by this repair.

Receipt and transaction key sets are exact: missing/extra fields, differing
version/attestation/source-stage locators, incorrect string/hash/token/inode scalar
types, and duplicate or non-standard JSON scalars are rejected. JSON is parsed
from the same stable authenticated buffers used for its integrity checks. The
full default gate also runs on the new temporary receipt before the exclusive
atomic commit, so the producer cannot commit a receipt its default reader rejects.

Identifier detection uses lstat/lexists semantics: dangling receipt/control
symlinks, directories in place of files, and retained `.receipt.partial-*` entries
cannot disguise a failed transaction as a legacy publication. Unsafe symbolic
ancestors fail closed. Removing every recovery identifier is still outside the
explicit immutable-output/sole-writer boundary; no registry/xattr/platform-isolation
claim is added. Recovery artifact retention, the trusted-parent acknowledgment,
source-generation identity, reported bytes, quarter values and normal legacy
reader behavior remain unchanged. New independent source PASS and lead GO are
still required before any actual recovery.
