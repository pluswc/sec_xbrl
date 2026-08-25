# M1-IX — Inline XBRL complete Layer 1 ingestion

## Purpose

Make a resolved SEC Inline XBRL package a trustworthy, immutable Layer 1
snapshot.  This milestone corrects a systemic failure mode in which Arelle's
small `factsInInstance` collection was treated as a complete filing although
the model-wide Inline corpus was available in `model.facts`.

It is not an Excel or company-specific milestone.  No metric, canonical
mapping, period classification, or recast decision is made here.

## Expected-result contract

For every successfully materialized filing:

1. The top-level reported Fact corpus is `model.facts` when that collection is
   present. `factsInInstance` is only a compatibility fallback when
   `model.facts` is absent. If both collections disagree, ingestion fails.
2. The snapshot contains all six raw Layer 1 tables plus `role` and
   `relationship`, generated from the same validated Arelle model.
3. `layer1_manifest.json` records source package SHA-256, Fact corpus source
   and count, materialized counts, and parser versions.
   The validated top-level source Fact count must equal the materialized Fact
   count; any extractor omission fails rather than producing a partial view.
4. A taxonomy-resolution, schema-reference, or Inline transformation error,
   or a Fact without a resolved concept, prevents all Snapshot output.
5. A published snapshot is never overwritten. A retry must use a new parser
   version/output location or leave the existing immutable snapshot untouched.
6. Every load, validation, or materialization result produces an append-only
   parse-state JSON event outside the snapshot, keyed by CIK/accession/parser
   version. It records `ARELLE_LOAD`, `VALIDATION`, or `LAYER1_EXTRACT`, its
   outcome, retryability, and failure message. Failed attempts therefore leave
   no snapshot but remain observable and retryable.

These conditions are generic. They do not rely on NVIDIA labels, accession
numbers, or numerical values.

## Taxonomy cache policy

Normal `ArelleFilingLoader` loads with network disabled.  Pass a local
`taxonomy_cache=Path(...)` containing the needed US-GAAP/DEI/SRT and other
taxonomy resources for reproducible offline parsing.

For an explicit, controlled bootstrap in a network-enabled environment use:

```python
model = ArelleFilingLoader.bootstrap_taxonomy_cache(
    resolved_filing,
    destination=Path("/secure/work/extracted/accession"),
    taxonomy_cache=Path("/secure/cache/arelle-taxonomies"),
)
```

The bootstrap is opt-in and must be followed by an offline reload and the
same Layer 1 validation before a production snapshot is trusted. The project
does not commit the resulting third-party taxonomy cache or SEC packages.

## Validation procedure

Unit tests create an Inline-like model where `model.facts` has two reported
facts while `factsInInstance` has one. A successful snapshot must contain two
facts and a manifest declaring `model.facts`; taxonomy/transform failures and
unresolved concepts must create no directory. A deliberately partial extractor
is rejected when its output count differs from the validated source corpus;
the corresponding parse-state event is `LAYER1_EXTRACT` / `FAILED`.

For a cached real filing, execute the following after the standard taxonomy
cache has been explicitly bootstrapped:

1. load the package offline with `ArelleFilingLoader(taxonomy_cache=...)`;
2. call `Layer1Ingestor.load_and_ingest(...)`;
3. compare `layer1_manifest.json.materialized_fact_count` with the non-tuple
   `model.facts` count;
4. query `concept.parquet` and `dimension_fact.parquet` using QName/axis/member
   rather than display labels.

For NVIDIA FY2026 Q3 this procedure is expected to make standard Revenue
Facts and geographic dimensional Revenue Facts queryable only when the
required standard taxonomy resources resolve. Without that cache, the correct
result is an explicit ingestion failure rather than a partial 52-Fact snapshot.

## Baseline evidence and current behaviour

The cached NVIDIA FY2026 Q3 package (`0001045810-25-000230`) demonstrated the
generic failure mode: Arelle exposed 52 `factsInInstance` facts and 1,060
`model.facts` facts. Before M1-IX, the 52-row collection could be saved as if
it were complete. With M1-IX, the same offline load is rejected because it
reports `IOerror`, `missingReferences`, and `invalidTransformation`; no Layer
1 snapshot directory is created.

An attempted bootstrap needs network access to the standard taxonomy hosts.
In the restricted development environment that request returned
`FileNotLoadable`, leaving 1,008 unresolved concepts; this too is rejected.
The automated bootstrap API remains the reproducible resolution path for a
network-enabled controlled environment, followed by an offline verification
run using the populated cache.
