# C3-M5-A — Review Inventory Companion

## Purpose

This is a reviewer work queue, not an analytical selection engine.  It binds
one reader-attested C3-M1 AS_FILED publication to the exact immutable
`CorpusRelease`, and writes only technical candidates and artifact coverage.
It is safe to generate for any company because it makes no company-specific
semantic or recast judgement.

## Datasets

- `q4_review_candidate`: only technically compatible FY/YTD_9M pairs of
  directly reported, duration, ISO-4217 monetary facts in the same full scope.
  The record is `PENDING_SEMANTIC_REVIEW`; it contains no calculated Q4 value,
  formula, or approval declaration.
- `recast_review_candidate`: a later retained current-series observation that
  matches a historical AS_FILED scope but comes from a different filing.  It
  is `PENDING_EVIDENCE_REVIEW`, explicitly says `recast_claim=NOT_MADE`, and
  is not evidence or a new basis.
- `source_artifact_coverage`: source-document/locator coverage for every
  candidate lineage.  Missing retained artifact information is recorded as
  `ARTIFACT_NOT_RETAINED` and `REFERENCE_ONLY`; it is never fabricated.

## Safety contract

The inventory accepts no approval registry.  It does not modify M1 facts,
emit `quarterly_q4_candidate`, calculate FY minus YTD, create a
`CURRENT_COMPARABLE` fact, parse filing prose, or activate any recast.  An
M2 declaration and M3 reviewed evidence registry remain the sole activation
boundaries.

The atomic manifest carries the exact verified M1 fingerprint and manifest
hash plus the exact `CorpusRelease` `Layer2Run` fingerprint.  The reader
checks layout, hashes, all input identities, and rejects altered or mismatched
companions.

## Public use

```python
result = ReviewInventoryMaterializer().materialize(m1_publication, release=release)
published = ReviewInventoryPublisher().publish(
    result, output_root=output_root, run_version="c3-m5-review-v1",
    upstream=m1_publication, release=release,
)
verified = ReviewInventoryPublicationReader().load(
    published.run_root, upstream=m1_publication, release=release,
)
```

The caller must obtain `m1_publication` from `Layer2PublicationReader`; a
manually assembled lookalike object fails closed.

## Korean consumer report

`KoreanReviewInventoryReportGenerator` is a reusable consumer-library output,
not a one-off company report.  For every requested ticker it first calls the
companion reader with its exact reader-attested M1 publication and
`CorpusRelease`; therefore an altered inventory or mismatched upstream cannot
be rendered.  It returns Korean Markdown and structured JSON with candidate
counts, the distinction between technical eligibility and semantic approval,
FY/YTD source lineage, artifact coverage, recast-review interpretation, and
reviewer intake instructions.  Technical IDs remain visible as IDs; the
generator does not invent labels.

The CLI accepts corresponding repeated `--inventory-root`, `--layer2-root`,
and `--ticker` arguments, plus the explicit corpus root/run ID and Markdown /
JSON output paths:

```bash
python -m sec_xbrl.analytics.review_inventory_report \
  --inventory-root /published/c3-m5-aapl \
  --layer2-root /published/c3-m1-aapl \
  --ticker AAPL \
  --corpus-root /corpus/20260827T051322Z \
  --corpus-run-id 20260827T051322Z \
  --output-markdown review.md --output-json review.json
```

The command's ticker scope is caller-provided: it has no embedded company
list.  It never calculates Q4 values, approves semantic declarations, claims
a recast, or activates `CURRENT_COMPARABLE`.
