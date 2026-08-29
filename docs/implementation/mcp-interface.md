# Analytical Consumer API and Future XBRL MCP Interface

## Consumer C0 implemented boundary

Consumer C0 extends the existing M9 **in-process** analytical boundary at
`sec_xbrl.analytics.AnalyticalRepository`. It is not an MCP server and does
not define transport, tool registration, authentication, or serialization. An
MCP adapter may later expose these stable methods after analytical views prove
stable.

The repository accepts independently materialized Layer 1 company/filing/
concept/fact records, Layer 2 company-canonical series and capability inventory,
hash-verified Derived Metrics M1/M2 publication roots, and Layer 3 comparison
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
5. `discover_capabilities(company, *, raw_concept_id=None,
   axis_raw_concept_id=None, member_raw_concept_id=None, period_class=None)`
   resolves the public company selector first, then delegates exact filtering
   and `NOT_REPORTED` behavior to the supplied L2-M5 capability inventory. A
   company with no supplied inventory raises `CapabilityInventoryNotFoundError`.
   It returns only observed capability/status/provenance rows and never creates
   a product, segment, geography, or statement template.
6. `trace_metric(derived_metric_id)` returns one full stored metric record only
   when it was loaded from a hash-verified M1 publication through the M2
   materializer. Missing IDs raise `DerivedMetricNotFoundError`; conflicting
   verified records for one immutable ID raise `DerivedMetricConflictError`.
   The method never calculates, selects, or infers a metric.

`get_metric_series()` keeps its explicit `view` and `as_of_date` request
requirements. It admits only candidates loaded from verified M1 publication
roots, and therefore does not accept a convenient row list, a bare manifest,
or an unverified file path.

### Consumer C0 request fields

| Method | Required request fields | Optional exact filters |
| --- | --- | --- |
| `resolve_company` | `selector` | — |
| `get_fact_series` | `company`, `concept` | `frequency`, `start`, `end`, `view` |
| `discover_capabilities` | `company` | raw Concept, Axis, Member, `period_class` |
| `get_metric_series` | `company`, metric ID/definition ID, `view`, `as_of_date` | `frequency`, period range, definition version |
| `trace_fact` | `fact_id` | — |
| `trace_metric` | `derived_metric_id` | — |
| `compare_companies` | company selectors, concept/metric | period/range, mapping version |

All selectors are exact.  A public company selector may be CIK (zero-padding
is tolerated), ticker, company canonical ID, or normalized exact company name;
it is resolved before a capability query reads the company-local inventory.

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

Capability responses preserve the M5 status exactly: `AVAILABLE`,
`PROCESSING_UNAVAILABLE`, `MAPPING_REVIEW_REQUIRED`, and `NOT_COMPARABLE` are
stored observed states. `NOT_REPORTED` remains an explicit query result for a
known company and exact requested structure; it is not persisted as a generic
missing disclosure. All source Fact/Filing/role/disclosure/document/locator
fields remain as supplied.

Metric responses preserve the stored calculation status, value or null value,
unavailable reason, formula/definition version, ordered input lineage, mapping
versions, governed view/as-of/basis, and M1 publication provenance. A consumer
does not receive a substituted basis or a calculated fallback for an
unavailable metric.

Missing source fields remain missing; Consumer C0 does not invent provenance,
upgrade mapping relations, or select between conflicting metric records.
Lookup errors are part of this in-process contract and can map to MCP error
responses later.

### Explicit non-goals

- No MCP transport, authentication, tool registration, or response wire format.
- No Excel/dashboard generation or layout policy.
- No SEC/ZIP/Arelle/parser access from the consumer boundary.
- No recast, mapping, period, capability, or formula policy; those decisions
  remain in governed upstream publications.
- No cross-company metric-comparability claim.

## Next consumer scope and deferred MCP surface

The next consumer milestone may define a transport adapter and migrate a
specific Excel/API/dashboard view to these read-only methods. It must not add
new analytical selection or calculation behavior merely for presentation.

1. `get_financial_statement(company, statement, period, view)`
2. `get_breakdown(company, concept, period, breakdown_type=None)`
3. `get_disclosure(company, topic, period=None)`
4. `get_disclosure_changes(company, baseline, current)`
5. `get_relationship_graph(company, concept, period, network_types=[...])`

MCP must expose stable analytical capabilities, not an internal parser object
model. Raw tracing remains a dedicated diagnostic capability.
