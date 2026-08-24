# SEC XBRL Analysis

A layered SEC XBRL analytical pipeline for detailed financial statement decomposition, longitudinal analysis, and cross-company comparison.

## Scope
- 10-K = annual structural baseline
- 10-Q = current-quarter update
- 10-K/A, 10-Q/A = preserved amendments
- XBRL facts + Context + Dimension + Role + DEF/CAL/PRE relationships
- Critical Disclosure safety net
- Standard vs company-custom taxonomy distinction

## Layer model
1. **Layer 1 — Raw / As-filed**: preserve exact filing meaning and provenance.
2. **Layer 2 — Longitudinal Canonical**: connect equivalent company-specific concepts/members over time.
3. **Layer 3 — Cross-company Semantic**: map company-specific structures into comparable analytical categories with explicit confidence.

## Existing accession process
This project assumes accession discovery already exists. The downstream pipeline consumes that output via an adapter contract rather than reimplementing discovery. See `docs/implementation/accession-contract.md`.

## Initial milestones
- M0: repository/contracts/fixtures
- M1: Filing package resolver + Arelle loading
- M2: Layer 1 fact/concept/context/dimension extraction
- M3: Role + DEF/CAL/PRE relationship extraction
- M4: Anchor-driven traversal
- M5: Disclosure Safety Net
- M6: 10-K/10-Q period normalization and Current Series
- M7: Layer 2 longitudinal mappings
- M8: Layer 3 cross-company mappings
- M9: analytical views + future MCP facade

See `docs/roadmap.md`.

## AMD · MSFT · META Excel review workbook

The pilot's user-facing deliverable is a locally generated Excel workbook. It
is a presentation of the P2 dossier and P3 peer-review evidence, not a new
mapping or calculation layer. It keeps annual, quarter-to-date, and
year-to-date observations in separate `Period class` rows and makes both
`UNRESOLVED` and `NOT_COMPARABLE` mapping decisions visible.

With the existing validated P1 cache, generate the ignored local artifact:

```bash
uv run python -m sec_xbrl.pilots.amd_msft_meta_excel \
  --manifest docs/pilots/amd-msft-meta-filing-manifest.json \
  --cache-root data/cache/pilots/amd-msft-meta \
  --output artifacts/AMD_MSFT_META_pilot.xlsx
```

The workbook contains `Overview`, `Company_Status`, `Revenue_Breakdowns`,
`Disclosure_Status`, `Peer_Comparison`, `Source_Trace`, and `Backlog` sheets.
All tabular sheets have frozen headers and filters. `Source_Trace` preserves
the raw fact ID, company canonical ID, analytical ID, mapping relation,
confidence/version, period, dimensions, and as-filed source locator. SEC
filing links are clickable; workbook generation performs no download.

The three reported-value sheets (`Revenue_Breakdowns`, `Peer_Comparison`, and
`Source_Trace`) provide a calculable Excel `Numeric value` together with the
unaltered `As-filed display`, `Unit`, and `Scale`. For example, `3605 × 10^6`
is stored as numeric `3,605,000,000` while its original display and scale `6`
remain visible. A missing scale is distinct from an explicitly reported scale
of `0`; neither representation changes a mapping, scope, or period class.

The source cache is intentionally required and must already have passed P1.
The generated `.xlsx` is ignored, and neither it nor raw SEC packages should
be committed. See [the P2 dossier review](docs/pilots/amd-msft-meta-p2-dossiers.md)
and [the P3 peer review](docs/pilots/amd-msft-meta-p3-peer-review.md) for the
evidence and limitations behind the workbook.

To export the committed P2/P3 review result when the local raw cache is not
available, replace `--cache-root ...` with:

```bash
--p2-summary docs/pilots/amd-msft-meta-p2-dossiers.md \
--p3-summary docs/pilots/amd-msft-meta-p3-peer-review.md
```

That review-summary mode does not re-extract facts; it makes the committed,
reviewed P2/P3 evidence directly viewable in Excel.

The workbook also includes `Revenue_Dashboard` (current `QTD_3M` reported
total-revenue display only) and `Revenue_Structure` (reported totals plus the
existing selected breakdowns). See
[the dashboard scope](docs/pilots/amd-msft-meta-revenue-dashboard.md) for the
depth semantics and relationship-evidence limitations.
