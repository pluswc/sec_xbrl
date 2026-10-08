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

## Publish governed Raw/Quality source bindings

After the fresh v5 raw intake is complete, prepare the source-binding
publication before constructing a `PASS` accuracy assessment:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.source_bindings \
  --collection-manifest /absolute/path/to/20261008_sec_transform_v5/ops_v5/collection_manifest.json \
  --package-root /absolute/path/to/data/raw/universe_runs/20261008_duration_v4/packages \
  --duration-source-index /absolute/path/to/20261008_sec_transform_v5/duration_source_index.json \
  --correction-source-index /absolute/path/to/20261008_sec_transform_v5/supported_lexical_correction_source_index.json \
  --destination /absolute/path/to/20261008_sec_transform_v5/source_bindings_v1 \
  --producer-revision <frozen-integration-commit-sha>
```

The destination must be new.  The producer performs no network requests.  It
opens all planned cached primary documents, rejects changed or incomplete
candidate source claims, and atomically writes `source_documents.json`,
`source_bindings.json`, and `source_binding_manifest.json`.  It binds exact
source IDs, Context references, lexicals, transform namespaces, QNames,
source lines, and source ordinals to v5 Fact, Context, and Concept identities.
It also records the 381 package and primary-member hashes, all snapshot
manifest hashes, and the Fact, Concept, and Context table hashes.

`SourceBindingsReader(root).verify_all()` is the consumer-side check.  It
re-hashes the prepared publication, cached package/member bytes, A request,
snapshot manifests, and Raw tables and recomputes stable identities.  It does
not parse Inline XBRL, load Arelle, normalize a value, or contact SEC.  Run the
producer from the frozen integration revision and independently verify that
revision and publication before referring to it from a `PASS` assessment.

## Publish the integrated completion view

After A, B, and C have produced their immutable outputs, join them without
opening SEC data or rerunning analysis:

```bash
PYTHONPATH=src .venv/bin/python -m sec_xbrl.universe_delivery \
  --config /absolute/path/to/final-pilot-config.json \
  --collection-manifest /absolute/path/to/20261008_sec_transform_v5/ops_v5/collection_manifest.json \
  --metadata-publication /absolute/path/to/company_metadata_v2 \
  --reviewed-q4-publication /absolute/path/to/20261008_sec_transform_v5/q4_delivery_v5/companion \
  --quarterly-analysis /absolute/path/to/20261008_sec_transform_v5/q4_delivery_v5/quarterly \
  --annual-analysis /absolute/path/to/20261008_sec_transform_v5/q4_delivery_v5/annual \
  --accuracy-assessment /absolute/path/to/sec_duration_conformance_assessment.json \
  --source-binding-publication /absolute/path/to/20261008_sec_transform_v5/source_bindings_v1 \
  --destination /absolute/path/to/completion
```

All paths are caller supplied.  The configuration used for completion must
contain an explicit CIK for every requested company.  The publisher rejects a
foreign or stale company/CIK scope, collection as-of, metadata identity,
reviewed-Q4 parent, analytical selection date, period mode, or declared file
digest before creating the destination.

The accuracy input is optional for backward-compatible use on unrelated
cohorts.  It is required for the 2026-10-08 delivery.  `PASS` must bind the
exact A request and fresh v5 381-filing scope, verify actual normalized
duration values including the known AMD `4.55` result, bind every governed
history manifest and one check per planned accession, attest all 104 approved
SEC transform repairs against their source index and fresh v5 Fact/Concept
tables, require zero unapproved foreign changes, reconcile the exact 3,842
duration Facts to external evidence, and
include a separately governed source-binding publication plus its independent
verification evidence.  `BLOCKED` is shown as
an overall block; `PENDING` keeps the publication partial.  Counts without
normalized-value checks are rejected.

The final assessment has this exact shape.  Ellipses below mean repeated
records or all 21 ticker/hash entries; they are not valid literal JSON:

```json
{
  "schema_version": "sec-duration-conformance-assessment-v1",
  "state": "PASS",
  "reason": null,
  "parser_version": "m2-layer1-v5",
  "parser_rule_version": "sec-duration-conformance-v1",
  "supported_lexical_repair_policy": "sec-supported-lexical-repairs-v1",
  "frozen_commit_sha": "c1fdc21a267545c3c67ad4bdce8c74137ee340e1",
  "scope": {
    "universe_id": "pilot-21-20261008-sec-transform-v5",
    "financial_as_of": "2026-10-08",
    "collection_request_sha256": "<sha256>",
    "collection_manifest_sha256": "<sha256>",
    "requested_companies": 21,
    "selected_filings": 381
  },
  "source_packages": {"expected": 381, "verified": 381, "missing": 0},
  "source_binding_publication": {
    "root": "/absolute/path/to/20261008_sec_transform_v5/source_bindings_v1",
    "publication_id": "source-bindings-<identity>",
    "manifest_sha256": "<sha256>",
    "producer_revision": "<frozen-integration-commit-sha>",
    "filing_count": 381,
    "duration_binding_count": 3842,
    "approved_transform_correction_count": 104,
    "independent_verification": {
      "state": "PASS",
      "producer_revision": "<frozen-integration-commit-sha>",
      "evidence_path": "/absolute/path/to/source-binding-verification.json",
      "evidence_sha256": "<sha256>"
    }
  },
  "history_manifest_sha256s": {"AMD": "<sha256>", "...": "..."},
  "ingestion_gates": {
    "TAXONOMY_AND_TRANSFORM_RESOLUTION": "PASS",
    "RAW_CORPUS_COMPLETENESS": "PASS",
    "ATOMIC_FILING_SNAPSHOT": "PASS"
  },
  "invalid_duration_lexical_fails_closed": true,
  "filing_checks": [
    {
      "ticker": "AMD",
      "cik": "0000002488",
      "accession": "0000002488-23-000047",
      "source_package_sha256": "<sha256>",
      "source_primary_sha256": "<sha256>",
      "snapshot_manifest_sha256": "<sha256>",
      "duration_fact_count": 11,
      "normalized_value_mismatches": 0,
      "status": "PASS"
    }
  ],
  "transform_checks": {
    "durday": {"examined": 481, "normalized_value_mismatches": 0},
    "durmonth": {"examined": 391, "normalized_value_mismatches": 0},
    "duryear": {"examined": 2902, "normalized_value_mismatches": 0},
    "durweek": {"examined": 68, "normalized_value_mismatches": 0}
  },
  "source_index": {
    "path": "/absolute/path/to/duration_source_index.json",
    "sha256": "<sha256>",
    "filing_count": 381,
    "duration_fact_count": 3842
  },
  "fact_level_evidence": {
    "path": "/absolute/path/to/duration_fact_checks.json",
    "sha256": "<sha256>",
    "record_count": 3842
  },
  "approved_transform_corrections": {
    "path": "/absolute/path/to/approved_inline_transform_corrections.json",
    "sha256": "<sha256>",
    "record_count": 104,
    "source_index_path": "/absolute/path/to/supported_lexical_correction_source_index.json",
    "source_index_sha256": "<sha256>"
  },
  "normalized_value_checks": [
    {
      "ticker": "AMD",
      "accession": "0000002488-23-000047",
      "fact_id": "fact_a6259d1f828fa6d425c0fd2c",
      "transform": "duryear",
      "lexical_input": "4.55",
      "previous_value": "P4Y7M",
      "expected_value": "P4Y6M18D",
      "actual_value": "P4Y6M18D",
      "status": "PASS"
    }
  ],
  "foreign_change_counts": {
    "non_duration_facts": 0,
    "duration_source_lexicals": 0,
    "monetary_values": 0,
    "contexts": 0,
    "units": 0,
    "dimensions": 0,
    "relationship_keys": 0
  },
  "independent_verification": {
    "state": "PASS",
    "frozen_commit_sha": "c1fdc21a267545c3c67ad4bdce8c74137ee340e1",
    "evidence_path": "/absolute/path/to/verification-report.json",
    "evidence_sha256": "<sha256>"
  },
  "evidence_files": [
    {"path": "/absolute/path/to/duration_source_index.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/duration_fact_checks.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/approved_inline_transform_corrections.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/supported_lexical_correction_source_index.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/source_bindings_v1/source_binding_manifest.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/source-binding-verification.json", "sha256": "<sha256>"},
    {"path": "/absolute/path/to/verification-report.json", "sha256": "<sha256>"}
  ]
}
```

`filing_checks` must contain exactly the 381 unique ticker/CIK/accession tuples
from the immutable collection plans, including zero-duration filings.  Every
path is absolute, every referenced file must exist without a symlink leaf, and
every digest is re-read before the completion destination is created.
The `source_binding_publication` identity and manifest digest must match the
reader input exactly, its embedded A collection digest and filing count must
match the assessment scope, and its independent-verification evidence must be
listed in `evidence_files`.  The consumer compares every duration and approved
correction source field to that governed publication.  Re-hashing the two
candidate JSON inputs together cannot substitute an invented source ID,
Context reference, lexical, primary-document hash, or Fact binding.
`duration_fact_checks.json` is a
`sec-duration-fact-checks-v1` object with `record_count` and a `records` list.
Each record contains ticker, CIK, accession, unique Fact ID, transform,
source ID, source Context reference, v5 Context ID, concept QName, source
lexical, expected normalized value, actual normalized value, and `status:
PASS`.  The source index includes one `duration_facts` record per observed
source Fact with the exact CIK/accession/source ID, stable Fact ID, format namespace/name,
lexical, concept QName, and source Context reference.  The publisher loads all
3,842 records, requires exact source-index coverage, then finds each Fact ID
exactly once in the corresponding v5 snapshot and verifies its normalized raw
and text values, Context ID, reported/non-nil state, and Concept QName.  It
also reconciles the per-filing and per-transform totals to the loaded source
index.

`approved_inline_transform_corrections.json` is a
`sec-approved-inline-transform-corrections-v1` object with `record_count` and
a `records` list.  Every record binds the planned ticker/CIK/accession, stable
source ID, Fact ID, Context ID, concept QName and data type, Inline XBRL source
element type, SEC transform namespace and name, lexical, sign, scale, source
primary-document hash, old `(ixTransformValueError)`, expected and actual raw
value, `actual_is_nil: false`, repair family/rule, value class,
`status: APPROVED`, and an official rule reference.  The four accepted
families are `Nasdaq`→`NASDAQ`, `Idaho`→`ID`, U+2011
`three‑year`/`five‑year`→`P3Y`/`P5Y`, and `nil`→reported numeric zero.  The
last family contains 22 monetary and 10 share values; a source minus sign must
produce raw `-0`, otherwise raw `0`.  The publisher loads the hashed 104-row
source index, requires exact source-field equality, and then verifies every
new Fact and Concept row.  Every other difference remains part of the
zero-valued unapproved foreign-change counts.

One correction record has this exact field shape (the values shown illustrate
a source-signed monetary zero):

```json
{
  "ticker": "PCAR",
  "cik": "0000075362",
  "accession": "<planned-accession>",
  "source_id": "<stable-inline-source-id>",
  "fact_id": "<stable-fact-id>",
  "context_id": "<stable-context-id>",
  "concept_qname": "us-gaap:<source-concept>",
  "concept_data_type_qname": "xbrli:monetaryItemType",
  "source_element_type": "nonFraction",
  "transform_namespace": "http://www.sec.gov/inlineXBRL/transformation/2015-08-31",
  "transform": "numwordsen",
  "lexical_input": "nil",
  "source_scale": "6",
  "source_sign": "-",
  "source_primary_sha256": "<sha256>",
  "previous_raw_value": "(ixTransformValueError)",
  "expected_raw_value": "-0",
  "actual_raw_value": "-0",
  "actual_is_nil": false,
  "repair_family": "SEC_NUMWORDSEN_NIL_ZERO",
  "repair_rule": "sec-inline-2015-numwordsen-nil-zero",
  "value_class": "monetary",
  "status": "APPROVED",
  "rule_reference": "<official SEC staff rule reference>"
}
```

The other exact repair rules are
`sec-inline-2015-exchnameen-nasdaq`,
`sec-inline-2015-stateprovnameen-idaho`, and
`sec-inline-2015-durwordsen-unicode-hyphen`.  Their repair-family values are
`SEC_EXCHNAMEEN_NASDAQ`, `SEC_STATEPROVNAMEEN_IDAHO`, and
`SEC_DURWORDSEN_UNICODE_HYPHEN`; their value classes are `metadata_text`,
`metadata_text`, and `duration` respectively.

The destination contains `index.html`, `company_readiness.json`,
`company_readiness.csv`, `README.md`, and `universe_delivery_manifest.json`.  The JSON keeps
the collection financial as-of, metadata observation/cutoff, historical
analytical selection as-of, and Q4 review cutoff as separate fields.  The Q4
table comes from `ReviewedQ4Reader` records and includes exact source accession,
snapshot, and fact identities; the HTML does not calculate a residual.
It labels the Q4 parent as `CURRENT_A_HISTORY` or
`SEPARATE_APPROVED_REFERENCE`, so reviewed monetary Q4 evidence is not
mistaken for the current A lineage.  This delivery's final C reference is
fresh v5 NVDA history selected as of 2026-09-06; the Q4 review cutoff remains
the separate 2026-10-08 provenance date.

The C paths may be omitted while creating a clearly `PARTIAL` prototype.  A
quarterly bundle cannot be supplied without its exact reviewed-Q4 companion.
The integrated assessment remains `PARTIAL` until every configured A company
has a verified governed-history `READY` publication; `RAW_COMPLETE` is reported
separately and does not imply analysis readiness.
Use a new destination for each prototype or final publication.  Runtime SEC
payloads, Parquet outputs, and generated completion views remain outside Git.
