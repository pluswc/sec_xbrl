# C3-M0 — Raw Corpus Release Input Adapter

## Purpose

`CorpusReleaseAdapter` is the operational boundary between an explicitly named
trailing Layer 1 corpus and a future governed Layer 2 materialization.  It is
not a parser and it does not create analytical observations.  Its output is a
typed immutable `CorpusRelease` containing the complete selected raw snapshots
and the exact `Layer2Run` declaration later producers must use.

```text
explicit corpus root + corpus_run_id + exact CIK scope
  -> verify corpus summary and every atomic Layer 1 snapshot
  -> CorpusRelease (raw tables and hashes) + Layer2Run
  -> C3-M1/L2 orchestration (future)
```

The caller supplies the root, `corpus_run_id`, CIK set, `run_version`, and all
Layer 2 rule versions.  The adapter never selects a “latest” run.

## What is verified and retained

For each selected CIK, the adapter requires an `AVAILABLE` corpus report and
a `PUBLISHED`, count-matching integrity row for every filing.  It verifies:

- an exact eight-table Layer 1 snapshot layout: `filing`, `concept`,
  `context`, `unit`, `fact`, `dimension_fact`, `role`, and `relationship`;
- non-symlink, non-partial snapshot and manifest paths;
- Layer 1 manifest identity and manifest/table count consistency;
- filing-table identity plus same-filing references in all applicable raw
  tables;
- byte SHA-256 values before and after every Parquet read, retaining those
  hashes and immutable copied records in the release;
- deterministic snapshot order and a deterministic `Layer2Run` input list.

`snapshot_id` is constructed from the immutable CIK/accession directory
identity and manifest SHA-256.  Existing Layer 1 manifests do not have a
separate snapshot-id field, so this is a reproducible adapter identifier—not
a replacement for raw filing identity.  Amendments remain distinct because
accession and form are both preserved.

The existing Layer 1 manifest has counts but no table-content hashes.  The
adapter therefore verifies its declared counts and computes byte hashes while
admitting a release; a later producer uses the immutable in-memory release,
rather than rereading unverified source files.  A future Layer 1 manifest
version may add persisted table hashes without changing this contract.

## Public usage

```python
from pathlib import Path
from sec_xbrl.longitudinal import CorpusReleaseAdapter, Layer2RuleVersions

release = CorpusReleaseAdapter().load(
    Path("data/processed/trailing_corpus_runs/20260827T051322Z"),
    corpus_run_id="20260827T051322Z",
    ciks=("0000320193", "0001045810"),
    run_version="c3-m1-example-v1",
    rules=Layer2RuleVersions("period-v1", "mapping-v1", "recast-v1", "selection-v1"),
)
run = release.layer2_run
facts = release.snapshot_records(run.inputs[0].snapshot_id, "fact")
```

Returned `records()` methods make independent copies.  The retained tables,
hashes, snapshots, and run declaration are immutable.

## Non-goals and C3-M1

C3-M0 does **not** select periods or recasts, classify facts, map concepts,
build capabilities, calculate Metrics, write an L2 publication, mutate raw
data, or serve Excel.  It also deliberately does not call the old
`TrailingFilingCorpus._build_analysis` helper, which was a transient legacy
analysis path and omitted required raw tables.

C3-M1 consumes `CorpusRelease` through `AsFiledPublicationPipeline` to
orchestrate the already-governed L2-M1 through L2-M5 producers and atomic
publication boundary. It retains this exact input declaration and does not
bypass the adapter by reading arbitrary raw Parquet paths. Its initial durable
output is AS_FILED only; comparable/recast, Q4 flow, and Derived Metrics remain
later controlled work. See [C3-M1 AS_FILED publication](c3-as-filed-publication.md).
