# C3-M1 — Deterministic AS_FILED Publication

## Purpose

`AsFiledPublicationPipeline` turns one explicit, already verified
`CorpusRelease` into one atomic Layer 2 publication that Consumer C2 can read.
It composes existing L2-M1 period classification, L2-M2 mapping, L2-M3 series,
L2-M4 AS_FILED selection, L2-M5 capability inventory, and the L2-M0 publisher.
It adds no analytical policy.

```text
explicit CorpusRelease + explicit as_of_date + explicit output root
  -> period observations and explicit exclusions
  -> same-company maps and pre-selection candidates
  -> AS_FILED facts only + observed capability inventory
  -> atomic Layer2Publisher publication
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

The atomic run includes period observations and their exclusions, mapping and
structural-change records, Annual/Current series candidates and exclusions,
`analytical_fact`, and `capability_inventory`. `analytical_fact` contains only
`AS_FILED` rows.

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
- Capability rows are based only on observed candidates. Direct relationship
  role IDs are copied when present; a disclosure is never inferred. Typed
  dimensions remain in the full fact/series key and are not falsely emitted as
  member capabilities under the current Axis/Member inventory schema.

## Coverage report

The result exposes one `CompanyCoverage` per requested CIK: filing count,
analytical fact count, explicit exclusion counts, capability count, observed
period classes/views, source-type counts, and capability-status counts. It is
coverage metadata, not a `NOT_REPORTED` statement. `NOT_REPORTED` remains a
query-time result of the capability contract only.

## Deliberate limitations and next steps

C3-M1 does not publish Q4 flow, `CURRENT_COMPARABLE`, evidence-backed recasts,
Derived Metrics, business analysis templates, or Excel work. C3-M2 may add a
controlled current/comparable publication only with reviewed recast evidence;
C3-M3 may connect governed Derived Metric releases; C3-M4 may build a first
consumer analysis scenario/view on the common data-access layer.
