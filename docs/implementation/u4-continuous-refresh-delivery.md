# U4 continuous refresh — implementation delivery contract

Date: 2026-09-09. Status: **implementation authorized; local verification in
progress**. The current user authorization supersedes the historical
document-only sentence in the proposal for this bounded implementation. It does
not authorize a live SEC target, remote push, PR, merge, scheduler, Excel, or a
new economic approval.

## Milestone and acceptance boundary

U4 joins the existing company registration, history refresh, exact disclosure
review reuse, consumer preparation, U3 hierarchy/Axis companion preparation,
and H2 renderer into one explicit administrator run. The producer receives an
exact source `as_of`, inclusive review date, selected tickers, source/cache
inputs, and an explicit U3 plan. Queries continue to read only a completed
publication.

The run copies the editable administrator inputs to a private run directory and
executes existing producers there. It records hashes of the settings snapshot
and labels every stage `LIVE`, `CACHE`, `REUSED`, or `SYNTHETIC`. The base
consumer, hierarchy companion, Axis companion, and rendered screen must all
open and verify before the registered consumer pointer can change.

An old disclosure-review publication is republished only through the existing
exact source/candidate path. Its decisions, quality history, and quarantine are
append-only. A new accession or stale source stops in `REVIEW_REQUIRED`. An old
Axis review is also publication-bound: failure to bind the new publication is
returned for manual re-attestation, never repaired by changing its JSON.
Configuration may choose among existing exact identities and presentation
preferences; it cannot create semantic edges or accounting meaning.

## Publication and failure contract

The real administrator is unchanged while producers run. Success commits the
new company registrations and target status, then writes
`analysis_current.json` last. Before committing, the implementation compares
the live settings with their input hashes, so a concurrent administrator edit
fails without being overwritten.

Several files cannot be replaced as one filesystem transaction. A normal
replacement exception rolls back every file already replaced. A durable commit
intent and byte-for-byte backups allow `status` to report, and `recover` to roll
back, a process crash. Until the final pointer replacement, an existing reader
continues to resolve the old bundle. A crash after that replacement can still
leave a pending intent; recovery deliberately restores the complete old
registration and pointer rather than guessing success.

Every stopped run appends a structured exception with the stage, exact source
paths/identities supplied to that stage, impact, and next action. Generated Raw,
Analytical, and private administration artifacts are retained for review. No
failure becomes `DISCLOSURE_MISSING`, and no incomplete bundle is registered.
Resume means completing the explicit disclosure/Axis review, registering that
reviewed immutable publication, and starting a new run with exact inputs. It
does not broadly rebind an old decision.

## Inputs, outputs, and excluded meanings

The Python and CLI entry point is `sec_xbrl.continuous_refresh`. `run` requires
new workspace storage, dates, a provenance JSON object, and a companion-plan
JSON object. The companion plan passes the already approved hierarchy/display/
source-reconciliation reviews and exact package-root adapters to the existing
U3 producer, followed by exact Axis review inputs and the existing renderer.
`status`, `exceptions`, and `recover` inspect or recover administrator state.
`resume-reviewed` accepts only a reviewed publication whose parent is the exact
stopped prepared parent, whose prior candidate/decision/quality histories remain,
and whose current registration still names the stopped prior publication.

A targeted history refresh still prepares every active registered company for
the final catalogue, so refreshing one ticker cannot silently remove the other
current companies. The cached writer run used NFLX source/review cutoff
2026-01-23 and reused 12 exact accessions from the trailing-corpus source. It
produced a new base consumer, a 12-filing/913-table hierarchy, an Axis companion,
and the same H2 renderer. Its manifest separates declared modes from observed
per-accession source-run identities. This is cached re-preparation without
economic reviews, not live collection or new-accession approval.

The existing six-company companion suite is a separate cached regression. Old
approved Axis evidence remains publication-bound and is not dropped to force a
new six-company producer success.

The implementation does not infer Q4, share, hierarchy, reconciliation, or
cross-accession approvals. It does not change discovery, parsing, period rules,
Layer 2 selection, or review economics. Unit tests use synthetic producer
doubles and explicit fault points. Cached six-company evidence and one live new
filing are reported separately; U4 remains incomplete until the lead supplies
and accepts the new-filing evidence.

Every legacy `admin/runs/*/decisions.csv` snapshot is copied into the private
administrator before refresh validation. Successful U4 runs also append an
integrity-checked external decision snapshot to `u4_decision_history.json`.
Deletion or editing fails before any producer runs; a later exact `RELEASE` may
proceed while retaining the preceding WARN/BLOCK row. The registry index is
committed and recovered with company/status files before the final pointer.

The existing prepared analysis producer does not materialize arbitrary active
administrator quality WARN/BLOCK decisions. U4 therefore stops with an exact
`REVIEW_REQUIRED` exception instead of publishing a consumer that might ignore
one. Building a general quality overlay is outside this delivery. Effective
RELEASE histories and empty quality histories can continue.

`company_reports.refresh(..., render_report=False)` is a backwards-compatible
producer option used by U4. It avoids the older complete-year HTML report gate
after history build, so a legitimate current incomplete year can reach
`prepare_catalog`; the default remains `True`. Final U4 display still uses the
same H1/H2 renderer after all companions are complete. No missing quarter or Q4
is invented by this option.
