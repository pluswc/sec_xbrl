# Company-universe collection operations

The universe wrapper coordinates the existing company-history workflow one
company at a time.  It does not replace SEC discovery, Layer 1 extraction,
period rules, canonicalization, or analytical publication.  The tracked pilot
configuration is
[`examples/universe/pilot_companies.json`](../../examples/universe/pilot_companies.json).

Use Python 3.12 with this checkout's `src` on `PYTHONPATH`.  Keep
`SEC_USER_AGENT` in the runtime environment; commands, manifests, and reports
must not contain its value.

## Prepare immutable company plans

When submissions snapshots are already cached, prepare without network:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations prepare \
  --config examples/universe/pilot_companies.json \
  --run-root data/processed/universe_runs/20261008_initial/collection \
  --submissions-root data/raw/universe_runs/20261008_initial/submissions \
  --offline
```

An existing plan avoids duplicate discovery and is validated against the
configured ticker, optional CIK, `2026-10-08` as-of date, and four-year or
explicit short-history coverage:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations prepare \
  --config examples/universe/pilot_companies.json \
  --run-root data/processed/universe_runs/20261008_initial/collection \
  --existing-plan AMD=/absolute/path/to/AMD/plan.json \
  --existing-plan AAPL=/absolute/path/to/AAPL/plan.json
```

The same run root may be resumed with identical inputs.  A changed request or
changed company plan is refused.  Companies with fewer than four annual
baselines retain an explicit actual report-date plan and receive
`AVAILABLE_PERIODS_ONLY` capability.
Existing wrapper-owned intake, attempt, status, temporary, and publication
paths must be ordinary contained paths.  Symlink redirection fails preflight
before discovery, ingestion, build, attempt logging, or status writes.

Within a run, the wrapper owns these stable paths:

- `companies/<TICKER>/plan.json` and `plan_identity.json` for immutable scope;
- `companies/<TICKER>/intake/history_intake.json` and its snapshot/extraction
  directories for the existing history intake;
- `companies/<TICKER>/operation_attempts/` for append-only wrapper attempts;
  and
- `status/` for the aggregate views.

An intake started directly with a validated precollected plan is adopted at
that exact company intake path.  The wrapper does not copy or rewrite its raw
snapshots.

## Collect raw histories

Collection is serial across companies.  Each accession still uses the existing
immutable package, cache, Arelle, and atomic Layer 1 contracts.  Repeatable
source-run paths permit verified snapshot reuse:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations collect \
  --manifest data/processed/universe_runs/20261008_initial/collection/collection_manifest.json \
  --package-cache data/raw/history_packages \
  --index-cache data/raw/history_indexes \
  --taxonomy-cache data/taxonomy_cache \
  --source-run AMD=/absolute/path/to/prior-amd-run
```

One company's error is recorded without cancelling later companies.  The
command exits nonzero while any company is failed.  Retrying appends operational
attempt records and the underlying history intake archives its prior manifest.
A company reaches `RAW_COMPLETE` only when every filing in its immutable plan
has a successful `INGESTED` or verified `REUSED` outcome.

## Build governed publications

Build is a separate optional phase.  Run it only for the analytical
publications required by the delivery:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations build \
  --manifest data/processed/universe_runs/20261008_initial/collection/collection_manifest.json \
  --output-root data/processed/universe_runs/20261008_initial/history
```

`RAW_COMPLETE` does not mean `READY`.  `READY` requires a successful build
marker for the immutable destination.  A different destination under the same
run identity is refused.

## Inspect without network or parsing

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations status \
  --manifest data/processed/universe_runs/20261008_initial/collection/collection_manifest.json
```

Status reads JSON manifests only.  It does not contact SEC, load Arelle, run
discovery, select facts, or build panels.  It writes deterministic
`collection_status.json`, `company_readiness.csv`, and `index.html` files under
the collection run's `status/` directory.  Counts distinguish selected, held,
pending, succeeded, failed, and reused filings.  Held means validated successful
raw outcomes already available; pending means selected minus validated success
and validated failure.  The company state and next action remain
separate from the capability flag so governed unavailable analytical scopes do
not become collection failures.

Stage labels describe the operational source route: `LIVE` for a live
discovery or newly ingested snapshot, `CACHE` for cached offline discovery, and
`REUSED` for caller-supplied plans or existing Layer 1 snapshots.  The as-of
date and source observation timestamp remain separate fields.
