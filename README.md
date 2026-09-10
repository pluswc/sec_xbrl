# SEC XBRL Analysis

A provenance-first SEC XBRL analysis-data platform.  It turns immutable,
as-filed XBRL into governed analytical facts and derived metrics that can power
earnings models, APIs, dashboards, and research workflows without losing the
original filing meaning.

## Scope
- 10-K = annual structural baseline
- 10-Q = current-quarter update
- 10-K/A, 10-Q/A = preserved amendments
- XBRL facts + Context + Dimension + Role + DEF/CAL/PRE relationships
- Critical Disclosure safety net
- Standard vs company-custom taxonomy distinction

## Data planes and consumers

```text
SEC XBRL filing
  -> Raw / As-filed Layer 1
  -> Analytical Facts + dimensional panel
  -> Derived Metrics
  -> Excel | API | dashboard | research workflow
```

1. **Raw / As-filed Layer 1** preserves exact filing meaning and provenance.
2. **Analytical** selects governed `AS_FILED` or `CURRENT_COMPARABLE` facts
   with explicit as-of date, basis version, and source lineage.
3. **Derived Metrics** keeps calculations separate, with rule and input lineage.
4. **Consumers** display or query governed outputs; they do not parse SEC
   files, choose recasts, or create analytical policy.

Layer 2 connects company-specific concepts/members over time; Layer 3 maps
them to peer-analysis categories with explicit confidence.  Both are additive
mappings over Raw identity.

See `docs/architecture/analytical-data-model.md` for the durable logical model
and `docs/implementation/m0-data-contract.md` for quality and release policy.
For evidence-based discovery of company-specific products, segments, regions
and related details, see `docs/implementation/consumer-exploration-contract.md`.

## Investor use and exports

The governed consumer API now provides the U1 core overview, U2/U3 breakdown
and Axis exploration, cell trace, and U5 canonical JSON/CSV/HTML/XLSX exports.
The offline hierarchy screen saves the selected prepared table without parsing
SEC files or inventing accounting policy. Direct-ZIP Excel builders remain
legacy/prototype paths; the governed U5 workbook consumes the canonical
prepared snapshot.

Start with the [Korean investor usage guide](docs/usage/investor-analysis.md).
It distinguishes a ready bundle from U4 registration/preparation and includes
working overview, Axis, trace, export and offline-render examples. Current
integration status is tracked in
[U3–U5 main delivery](docs/implementation/u3-u5-main-delivery.md).

## Existing accession process
This project assumes accession discovery already exists. The downstream pipeline consumes that output via an adapter contract rather than reimplementing discovery. See `docs/implementation/accession-contract.md`.

## Development and test environment

Use the repository's Python 3.12 environment managed by `uv`, matching CI.
It installs `arelle-release`, which is required by parser and Inline-transform
tests. Do not substitute an arbitrary system or Conda environment merely
because it has `pytest` installed.

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
```

## Milestones
- M0: data-plane contract and release governance
- M1: Filing package resolver + Arelle loading
- M2: Layer 1 fact/concept/context/dimension extraction
- M3: Role + DEF/CAL/PRE relationship extraction
- M4: Anchor-driven traversal
- M5: Disclosure Safety Net
- M6: period, as-of/recast compatibility, and analytical selection foundations
- M7: Layer 2 longitudinal mappings and analysis-ready company series
- M8: Layer 3 cross-company mappings and comparable analytical panel
- M9: consumer APIs and governed Excel/dashboard migration

See `docs/roadmap.md`.
