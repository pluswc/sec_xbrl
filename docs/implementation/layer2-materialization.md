# Layer 2 Physical Materialization Contract (L2-M0)

L2-M0 establishes the **run and publication boundary** for the existing
Analytical plane.  It does not select observations, map concepts, or calculate
metrics.  Those policies remain the responsibility of L2-M1 through L2-M6.

## Run identity and input manifest

Every run is represented by `Layer2Run` and must declare:

- a non-path `run_version` and source `corpus_run_id`;
- every consumed immutable Layer 1 snapshot: CIK, accession, form, filed and
  report date, snapshot ID, manifest SHA-256, and optional parser version.
  All listed filing-identity fields except parser version are mandatory;
- period-rule, mapping, recast-evidence, and selection-rule versions;
- the L2 materialization-contract version.

The stable `run_fingerprint` hashes that complete declaration.  Per-dataset
canonical content hashes separately prove the keys and values, rather than only
the row counts.  A repeated run with identical declaration and rows reuses the
existing publication.  A changed input, rule, key, or value cannot overwrite a
prior `run_version`; it must be published as a separately named run.  The run
manifest records input snapshots, all versions, logical-dataset output counts
and content hashes, validation status, fingerprint, and timestamp.

## Logical datasets and lineage gate

The supported logical dataset names are the L2 plan's `period_observation`,
`company_concept_map`, `company_axis_map`, `company_member_map`,
`structural_change`, `analytical_fact`, `recast_evidence`, and
`capability_inventory`.  The candidate must include `analytical_fact`.

Each row must identify a CIK included in the declared Layer 1 inputs.  An
`analytical_fact` has a unique `analytical_fact_id` and follows this hard gate:

- `REPORTED`, `RECAST_REPORTED`, and `DERIVED_RECAST` require a
  `selected_fact_id`, `view`, `as_of_date`, and `selection_rule_version`.
  Thus a numeric analytical value never appears without a selected raw-Fact
  lineage reference.
- `UNAVAILABLE` requires `unavailable_reason`, and cannot carry a numeric
  value or `selected_fact_id`.

The rule is deliberately stricter than display behavior: an Excel consumer may
format `UNAVAILABLE`, but it cannot turn it into a numeric value or choose a
replacement Fact.

## Physical layout and atomicity

The provisional operational root is ignored by Git:

```text
data/processed/analytical/layer2/<run_version>/
  layer2_run_manifest.json
  <cik>/
    analytical_fact.jsonl
    <other-logical-dataset>.jsonl
```

L2-M0 uses canonical JSON Lines as a dependency-light contract fixture.  It is
not a commitment that later high-volume materialization will remain JSONL; a
Parquet writer may replace the row encoding only while retaining the same
logical records, keys, manifest, and publication semantics.

The publisher validates every supplied row before staging.  It then writes to
`<root>/.staging/` and validates row counts and the manifest before one atomic
directory rename to `<run_version>`.  Any validation or write failure removes
the staging directory and leaves no partial published output.  Existing output
with the same `run_version` is reused only if its fingerprint and counts match;
otherwise publication fails closed.

Layer 1 is read-only input to this boundary.  Generated data under `data/raw`,
`data/processed`, caches, ZIPs, and Parquet are intentionally excluded by
`.gitignore`; only code, tests, and this contract are version controlled.
