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

For bounded memory use, select one or more companies with repeatable `--ticker`
arguments.  Each command still validates the full immutable request and writes
the aggregate 21-company status, while ingestion runs only for the selected
companies:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations collect \
  --manifest data/processed/universe_runs/20261008_initial/collection/collection_manifest.json \
  --package-cache data/raw/history_packages \
  --index-cache data/raw/history_indexes \
  --taxonomy-cache data/taxonomy_cache \
  --ticker AMD
```

Run each company in a separate process when parser memory should be released
between companies.  Repeat the same command for a retry; the immutable intake
and append-only attempt history determine what can be reused.  The selected
ticker list and the full request ticker list are recorded in every new
operation attempt.  An empty, duplicate, unsafe, or unconfigured selection is
rejected before any write.  Without `--ticker`, collection retains its serial
all-company behavior.

One company's error is recorded without cancelling later companies.  The
full-cohort command exits nonzero while any company is incomplete or failed; a
filtered command bases its exit code on the selected companies while its status
files continue to report the full cohort.  Retrying appends operational attempt
records and the underlying history intake archives its prior manifest.  A
company reaches `RAW_COMPLETE` only when every filing in its immutable plan has
a successful `INGESTED` or verified `REUSED` outcome.

## Build governed publications

Build is a separate optional phase.  Run it only for the analytical
publications required by the delivery:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.collection_operations build \
  --manifest data/processed/universe_runs/20261008_initial/collection/collection_manifest.json \
  --output-root data/processed/universe_runs/20261008_initial/history \
  --ticker AMD
```

`RAW_COMPLETE` does not mean `READY`.  `READY` requires a successful build
marker for the immutable destination.  A different destination under the same
run identity is refused.  Repeat `--ticker` to select several companies, or
omit it for the original serial all-company build.  Separate one-company build
processes bound peak memory and preserve the full request and aggregate status.

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

## Publish the integrated completion view

After A, B, and C have produced their immutable outputs, join them without
opening SEC data or rerunning analysis:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.universe_delivery \
  --config /absolute/path/to/final-pilot-config.json \
  --collection-manifest /absolute/path/to/operations_final/collection_manifest.json \
  --metadata-publication /absolute/path/to/company_metadata_v2 \
  --reviewed-q4-publication /absolute/path/to/q4_delivery/companion \
  --quarterly-analysis /absolute/path/to/q4_delivery/quarterly \
  --annual-analysis /absolute/path/to/q4_delivery/annual \
  --destination /absolute/path/to/completion
```

All paths are caller supplied.  The configuration used for completion must
contain an explicit CIK for every requested company.  The publisher rejects a
foreign or stale company/CIK scope, collection as-of, metadata identity,
reviewed-Q4 parent, analytical selection date, period mode, or declared file
digest before creating the destination.

The destination contains `index.html`, `company_readiness.json`,
`company_readiness.csv`, `README.md`, and `universe_delivery_manifest.json`.  The JSON keeps
the collection financial as-of, metadata observation/cutoff, historical
analytical selection as-of, and Q4 review cutoff as separate fields.  The Q4
table comes from `ReviewedQ4Reader` records and includes exact source accession,
snapshot, and fact identities; the HTML does not calculate a residual.

The C paths may be omitted while creating a clearly `PARTIAL` prototype.  A
quarterly bundle cannot be supplied without its exact reviewed-Q4 companion.
The integrated assessment remains `PARTIAL` until every configured A company
has a verified governed-history `READY` publication; `RAW_COMPLETE` is reported
separately and does not imply analysis readiness.
Use a new destination for each prototype or final publication.  Runtime SEC
payloads, Parquet outputs, and generated completion views remain outside Git.
