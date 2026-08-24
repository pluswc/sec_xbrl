# Analytical API and Future XBRL MCP Interface

## M9 implemented boundary

M9 implements an **in-process** analytical boundary at
`sec_xbrl.analytics.AnalyticalRepository`. It is not an MCP server and does
not define transport, tool registration, authentication, or serialization. An
MCP adapter may later expose these stable methods after analytical views prove
stable.

The repository accepts independently materialized Layer 1 company/filing/
concept/fact records, Layer 2 company-canonical series, and Layer 3 comparison
panels. Inputs are copied at construction and query results are deep copies. It
never mutates supplied records or exposes Arelle/parser objects.

### Implemented methods

1. `resolve_company(selector)` resolves an exact CIK (zero-padding is
   tolerated), ticker, company canonical ID, or normalized exact name. No
   match raises `CompanyNotFoundError`; multiple distinct matches raise
   `CompanyAmbiguousError`.
2. `get_fact_series(company, concept, frequency=None, start=None, end=None,
   view=None)` returns Layer 2 records for one resolved company and exact
   concept selector. `frequency` matches `period_class`; `view` matches
   `series_type`; ISO date limits apply to source/report/end periods. It never
   combines QTD/YTD/FY/instant classes.
3. `compare_companies(companies, concept_or_metric, period_or_range=None,
   mapping_version=None)` returns visible Layer 3 panel rows. A range is an
   inclusive `(start, end)` tuple; a scalar selects exactly that period.
   `ANALYTICALLY_SIMILAR`, `UNRESOLVED`, and low-confidence rows remain visible.
4. `trace_fact(fact_id)` returns a supplied reported or derived fact with
   provenance enrichment. Missing IDs raise `FactNotFoundError`.

All selectors are exact by design; this boundary does not use label similarity
to assert financial meaning.

### Response provenance

Every returned fact, series, or comparison row keeps supplied data and is
enriched from Layer 1 filing/concept records where available:

- `cik`, `accession`, `form`, `filed_date`, `report_period`;
- `reported_or_derived`, supplied `source_fact_ids`, and
  `derivation_formula`/`formula` for derived values;
- `raw_concept_id`/`source_raw_id`, `qname`, `namespace_uri`, `local_name`,
  `is_standard`, and `is_custom`;
- `company_canonical_id`/`company_canonical_concept_id`; and
- `analytical_id`, `mapping_relation`, `mapping_confidence`, and
  `mapping_version` for cross-company records.

Missing source fields remain missing; M9 does not invent provenance or upgrade
mapping relations. Lookup errors are part of this in-process contract and can
map to MCP error responses later.

## Deferred future MCP surface

1. `get_financial_statement(company, statement, period, view)`
2. `get_breakdown(company, concept, period, breakdown_type=None)`
3. `get_disclosure(company, topic, period=None)`
4. `get_disclosure_changes(company, baseline, current)`
5. `get_relationship_graph(company, concept, period, network_types=[...])`

MCP must expose stable analytical capabilities, not an internal parser object
model. Raw tracing remains a dedicated diagnostic capability.
