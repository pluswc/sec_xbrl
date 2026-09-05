# C3-M1 — Deterministic AS_FILED Publication

## Purpose

`AsFiledPublicationPipeline` turns one explicit, already verified
`CorpusRelease` into one atomic operational Layer 2 publication that Consumer
C2 can read. It composes L2-M1 period classification, L2-M2 mapping, L2-M3
in-memory candidates, and L2-M4 AS_FILED selection. It adds no analytical
policy.

```text
explicit CorpusRelease + explicit as_of_date + explicit output root
  -> period observations and explicit exclusions
  -> same-company maps and pre-selection candidates
  -> AS_FILED facts + required company maps only
  -> atomic Parquet operational publication
  -> Consumer C2 / Consumer Data Access Layer
```

The release's `Layer2Run` is used unchanged.  It contains the exact input
snapshots and governed rule versions, so the pipeline neither scans for a
latest corpus nor rereads arbitrary raw paths.

## Public usage

```python
release = CorpusReleaseAdapter().load(
    corpus_root,
    corpus_run_id="20260827T051322Z",
    ciks=("320193", "1045810"),
    run_version="c3-as-filed-20260829-v1",
    rules=rules,
)
result = AsFiledPublicationPipeline().publish(
    release,
    output_root=Path("data/processed/analytical/layer2"),
    as_of_date="2026-08-29",
)
repository = AnalyticalRepository.from_layer2_publications((result.publication.run_root,))
```

`as_of_date` is an explicit ISO date and enters the governed AS_FILED
selection. It is not a consumer-side display filter.

## Published datasets and safety boundary

The operational run includes company concept/axis/member mappings and
`analytical_fact` only. `analytical_fact` contains only `AS_FILED` rows.
Period observations, series candidates, structural-change events, capability
inventory, and comparable/recast outputs are separate diagnostic or feature
builds rather than mandatory point-query publication data.

- A later comparative value cannot overwrite the first directly reported
  AS_FILED observation.
- Amendments remain separate immutable release snapshots and retain accession,
  filing, raw Fact, Context, unit, dimensions, and filing lineage.
- Each available consumer-facing AS_FILED fact copies `form`, `accession`,
  `report_date`, raw `context_id`, and raw `unit_id` from its exact selected
  Layer 1 Fact and filing. An unavailable fact has no selected raw Fact and
  leaves these raw-reference fields null rather than borrowing them from a
  competing candidate.
- No recast evidence is supplied and no `CURRENT_COMPARABLE` output is
  published.
- C3-M1 passes no Q4 policy to L2-M1. It never derives residual Q4, including
  for EPS, weighted-average shares, ratios, margins, or other non-additive
  values.
- Facts that cannot be classified or become a safe candidate are represented
  in explicit period/series exclusions. A collision at M4's consumer identity
  becomes an `UNAVAILABLE` AS_FILED fact with
  `AMBIGUOUS_AS_FILED_SELECTION_IDENTITY`; competing raw candidates stay in
  the publication rather than being selected by order.

## Coverage report

The result exposes one `CompanyCoverage` per requested CIK: filing count,
analytical fact count, explicit exclusion counts, observed period classes and
views, and source-type counts. It is coverage metadata, not a `NOT_REPORTED`
statement. Capability discovery is a separate build.

## Deliberate limitations and next steps

C3-M1 does not publish Q4 flow, `CURRENT_COMPARABLE`, evidence-backed recasts,
Derived Metrics, business analysis templates, or Excel work. C3-M2 may add a
controlled current/comparable publication only with reviewed recast evidence;
C3-M3 may connect governed Derived Metric releases; C3-M4 may build a first
consumer analysis scenario/view on the common data-access layer.
