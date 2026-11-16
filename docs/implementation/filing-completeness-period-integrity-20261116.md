# Filing completeness and period integrity — 2026-11-16

## Approval and boundaries

APPROVED / IMPLEMENTED / INDEPENDENTLY_VERIFIED / LOCALLY_ACCEPTED by ROOT
on 2026-11-16, code freeze `b713c765f6a6db688486731df4768a79e1a8fb73`.
The documentation-only completion commit does not change that code. Actual private
cached outputs are accepted under the bounds below; live code activation and
native qualification inheritance are not performed. Baseline `b9126a262ce561a45e14ee1bb33f872d36079bee`, branch
`codex/filing-completeness-periods`. The sole writer implements; a separate reviewer
verifies the frozen SHA; ROOT owns actual cached preparation, remote push/PR and CI.
A separate PR is authorized; main merge and live republication are outside scope.

P0 has three parts: complete same-accession Inline XBRL document-set loading;
fail-closed analytical fiscal coordinates when reported focus conflicts with actual
periods; explicit reviewed fiscal calendars for nonstandard derived quarters.

Raw ZIPs, existing v5-v7 snapshots/IDs, Analytical/Derived publications, approval
pins, journal/history and runtime remain immutable. No ticker/filename-suffix
heuristics, SEC collection, UI/market changes, guard widening or automatic native
qualification inheritance. A new parser snapshot is a separate output. Existing
normal single-document loading and default quarter bounds remain supported.

## Acceptance

- Discover Inline documents from actual XML namespaces/targets/resources in the
  exact accession package; use Arelle IXDS for cross-document contexts/units and
  continuations. Reject unsafe/duplicate ZIP entries, ambiguous targets, conflicting
  IDs/resources, missing references and cyclic continuations. Record pinned per-
  document expected/loaded coverage and extracted Fact counts. Preserve precise
  per-document source provenance. Multi-document completeness is not established
  merely by comparing a partial model's Fact count with its own extracted rows.
- Preserve STX's reported focus, never infer an effective FY from calendar year.
  Unapproved fiscal-coordinate conflicts block new analysis/derivation. Exact
  accession/source/ROOT-approved v1 corrections remain the only correction path;
  HON-specific v2 is not broadened. Actual STX correction is ROOT-owned.
- Nonstandard YTD252/Q4112 requires an exact reviewed calendar: company/FY,
  start/end, contiguous four quarters, cutoff, source/evidence/approval pins and
  explicit 12/12/12/16-week or approved 53-week layout. No implicit wider day
  bounds. Existing additive, full-scope/unit/basis/recast/uniqueness guards remain.
  EPS/ratios/averages never acquire subtraction eligibility. Unsupported/partial
  calendars remain diagnostic. No-calendar behavior remains unchanged.

## Verification and reproduction

Synthetic unit and real offline Arelle integration fixtures cover document sets,
single-document parity, negative references/targets/IDs/continuations, fiscal
conflict/correction, and exact calendar permission and rejection. Run relevant
pytest, Ruff and diff checks before freezing. ROOT then runs cached IBM2024/2025,
STX and COST in new private output directories with the existing taxonomy cache;
no original cache/snapshot/publication is overwritten. Final commands and input
schema are recorded with the implementation freeze. Source and data acceptance
remain separate; this milestone does not claim increased actual company coverage.

## Implemented interfaces (candidate, not independently accepted)

Arelle loading is split at `filing.inline_document_set`: package discovery and
strict local-reference checks establish the set; the installed IXDS plugin owns
its actual XBRL interpretation. The alternative of merging separately loaded
models is rejected because contexts/units/continuations and target identities
would be reconstructed outside Arelle. Unrelated same-target instances, multiple
targets and tuple-bearing sets currently fail explicitly; they are not silently
combined or accepted as complete. Per-document Fact counts exclude footnotes and
continuations, which have separate inventory counts. Both normal loader and direct
public ingestion recheck package/model document hashes and actual Fact coverage.
Parser v8 does not enter the existing history/native approved parser allowlists.

The gross-year conflict detector is a diagnostic gate, not a fiscal calendar
inference. The existing exact v1 correction registry is unchanged. No actual STX
correction is supplied by this implementation; effective FY2025 remains a reviewed
proposal requiring the existing explicit approval, while Raw DEI2027 is retained.

The typed `FiscalCalendarRegistry` validates source and approval files on load.
Public batch entry/exit boundaries recheck pins; individual date predicates do
not rehash the same large ZIP for each observation. Original source rows are never
modified. Core/revenue default paths keep their old results; new calendar paths
have distinct rule/proof identities and retain all ordinary additivity/scope/
unit/basis/recast/unique-source gates. Existing M6 broad mechanical candidates
have their historical 60..120 residual tolerance; this task neither expands nor
relabels them as governed core permission. New calendar companion ratios remain
explicitly UNPREPARED, requiring separate parent/prior eligibility.

### ROOT cached reproduction

Use this branch's `src` and the repository's existing Python environment with
`POLARS_MAX_THREADS=2`; do not point a writer at an existing snapshot destination.
For IBM, ROOT's cached `probe_ibm.py` can switch only PYTHONPATH to this frozen
source and use a new output directory, existing exact package pins and
`data/taxonomy_cache`. `ArelleFilingLoader.load(resolved, fresh_extract_dir)` and
`Layer1Ingestor(fresh_snapshot_root).ingest(resolved, model)` expose the manifest
inventory and preserve each Fact's document/locator. ROOT's v7 baseline is a
separate comparison, not a successful complete multi-document extraction.

For a new COST companion:

```bash
PYTHONPATH=/absolute/frozen/source/src:/absolute/frozen/source POLARS_MAX_THREADS=2 \
  /absolute/repository/.venv/bin/python -m examples.screening.prepare_reviewed_calendar_q4 \
  --observations /absolute/pinned/reported_period_observation.parquet \
  --observations-sha256 EXACT_SHA256 \
  --calendars /absolute/pinned/calendars.json --calendars-sha256 EXACT_SHA256 \
  --output /absolute/new/reviewed-calendar-q4.json
```

Registry JSON has `schema_version: reviewed-fiscal-calendar-v1`, `financial_as_of`,
and `calendars`. Each entry has `calendar_id`, ten-digit `cik`, integer
`fiscal_year`, `financial_as_of`, `start_date`, four exclusive `quarter_end_dates`,
`quarter_weeks`, pinned `source_pins`, `evidence` (`source_index`, `locator`,
`assertion`) and pinned `approval`. Approval JSON is exactly
`schema_version: root-fiscal-calendar-approval-v1`, `authority: ROOT`,
`status: APPROVED`, `calendar_sha256`: SHA-256 of UTF-8 canonical JSON of that entry
without `approval` (sorted keys, compact separators, ensure_ascii=false).
Only new output paths are permitted. ROOT owns actual approvals and source/data
acceptance. Mapping uncertainty can legitimately leave COST components held even
when their calendar is valid; this PR does not claim actual coverage expansion.

## Handoff and later design work

This P0 stays in the present session through its separate PR. A later design
session is recommended only after source/period status and actual acceptance are
settled. Handoff must distinguish missing source preparation, unresolved mapping,
calendar-qualified temporal bounds and independently unprepared share/YoY admission.
A proposed future design acceptance criterion does not authorize implementation.
This PR changes no UI code or layout and does not claim the remaining 59-company
revenue coverage work is complete.

## Writer verification at first freeze

Related pytest **264 PASS** (1.24 seconds), `ruff check .` and `git diff --check`
PASS. The tests use synthetic packages and actual offline Arelle; writer has not
executed the cached IBM/COST/STX approval inputs or published actual data.
The separate physical Layer 2 subset was 25 PASS (not 32); its conflict-exclusion
roundtrip is also included in the final combined count. Existing transform/error
lexical tests remain; invalid continuation tests now assert earlier preflight
rejection and parse-state failure rather than waiting for Arelle value evaluation.
Dummy non-ZIP ingestion fixtures were replaced with tiny real ZIPs to exercise
the new package verification boundary without weakening the gate.

```bash
PYTHONPATH=src:. POLARS_MAX_THREADS=2 /absolute/repository/.venv/bin/python -m pytest \
 tests/unit/test_filing_index.py tests/unit/test_layer1_ingestion.py \
 tests/unit/test_layer1.py tests/unit/test_relationship_layer1.py \
 tests/integration/test_inline_document_set.py \
 tests/integration/test_sec_inline_metadata_transforms.py \
 tests/integration/test_sec_duration_hour_ingestion.py \
 tests/unit/test_period_logic.py tests/unit/test_period_observation_materialization.py \
 tests/unit/test_fiscal_focus_correction.py tests/unit/test_fiscal_coordinate_integrity.py \
 tests/unit/test_reviewed_fiscal_calendar.py tests/unit/test_revenue_quarters.py \
 tests/unit/test_revenue_q4_continuity.py tests/unit/test_history_quarters.py \
 tests/unit/test_layer2_materialization.py \
 tests/screening/test_revenue_q4_enrichment.py tests/screening/test_revenue_breakdowns.py -q
```

Local logs: `/tmp/filing-p0-final-pytest.log`, `/tmp/filing-p0-physical.log`,
`/tmp/filing-p0-cli-help.log`. No full-suite/Node/CI pass is claimed: UI is unchanged
and ROOT owns separate PR/CI and actual evidence. Independent validation, cached
source/data acceptance, remote delivery and main merge have not been performed.

## Independent return: conflicting DEI metadata — 2026-11-16

The first freeze `0020d8c578` received **FAIL / P1**: Arelle can load conflicting
DEI declarations without reporting an error. The previous extraction loop chose
the last value for filing metadata, potentially concealing a fiscal-focus conflict.
The cached IBM/STX/COST observations reported for that freeze remain historical
stage evidence and do not establish acceptance of the corrected candidate.

The correction rejects differing declarations of DocumentFiscalYearFocus,
DocumentFiscalPeriodFocus, CurrentFiscalYearEndDate, DocumentPeriodEndDate,
DocumentType, EntityCentralIndexKey and AmendmentFlag before publication. Document,
Fact ID, Context or declaration order cannot select a winner. Nil and non-nil are
distinct. Exact same lexical-value/nil-state duplicates are permitted deterministically:
the consumer value is unique and every original Fact/document/context remains in
Raw output. No effective year or metadata precedence is inferred.

Actual offline Arelle regressions load two documents with different Fact IDs and
same/different Contexts; Arelle reports no errors but ingestion must reject all
seven critical metadata conflicts. An identical-value case publishes both Raw
facts and one unique filing value. The corrected source requires new independent
verification and ROOT cached rechecks; no actual data was republished by writer.

P1 수정 후 전체 관련 pytest **279 PASS**(3.22초), Ruff/diff PASS. 최종 로그는
`/tmp/filing-p0-metadata-final.log`다. 이전 동결의 검증 결과와 이 후보의 재검증을
구분하며 현재 독립 검증·실자료 재인수는 대기다.

## Final ROOT local acceptance — 2026-11-16

ROOT's authoritative decision is
`/home/plusbdw/user_work/projects/sec_xbrl/work/filing-completeness-periods-20261116/root-local-acceptance-b713c76.json`
and the reports beside it. Separate independent review of `b713c765f6` passed
**279 pytest / Ruff / diff** and the 675-file preservation check. ROOT executed
the actual cached preparation and operating read-only comparisons; writer did
not execute these actual inputs or alter runtime/data/journals.

| Gate | Actual result and bounds |
| --- | --- |
| IBM FY2024 | New private complete v8 snapshot: 4,224 Facts, 132 revenue Facts, SUCCESS, model errors 0. |
| IBM FY2025 | New private complete v8 snapshot: 3,970 Facts, 135 revenue Facts, SUCCESS, model errors 0. |
| Raw provenance | All fields and Fact IDs of the original primary-document 241/199 Facts remain identical; raw foreign keys and each document's expected = loaded = extracted counts pass. Original snapshots and ZIPs remain unchanged. |
| STX | All 1,382 original Raw Facts are accounted for as new Layer 2 `FISCAL_FOCUS_REPORT_DATE_CONFLICT` exclusions. Reported focus 2027 and effective null remain explicit. The proposed effective FY and existing HUMAN correction route were not applied or relaxed. |
| COST FY2025/FY2026 | Separate ROOT-reviewed temporal 364/252/112-day calendar permission passes. Actual new companion has **0 derived / 32 holds**: mapping review 28, missing YTD9 4. Calendar permission does not override those gates. Existing output overwrite is refused and ratio remains UNPREPARED. No actual 53-week calculation is claimed. |
| Existing UI | At 18765, 11 price values, four market responses and three profiles match before/after, including the retained 252-day series. AMD/AAPL/NVDA Q4 four cases at 1440/1920/390 pass with errors 0. These checks establish preservation of the existing operating consumer; they do not mean v8 was deployed. |
| Preservation | Both existing journals retain hashes, SQL table counts and integrity checks; all 675 pinned files match. No source approval/native qualification boundary was widened. |

Only **new private cached preparation** was accepted. There was no live code
switch, operating republication or automatic qualification of v8 as an existing
native source. Raw/reporting anomalies remain evidence-backed holds rather than
silently repaired data. Mapping and independent ratio admission remain follow-up
work; this is not a coverage-completion or UI-redesign claim.

ROOT refetched origin/main and found `b9126a262ce561a45e14ee1bb33f872d36079bee`
unchanged, with no new integration required at this handoff. Push, separate PR
creation and CI are still pending ROOT execution. Main merge was not requested
or performed. Earlier pending/FAIL records above are retained as historical
stages; the final accepted implementation is explicitly `b713c765f6`.
