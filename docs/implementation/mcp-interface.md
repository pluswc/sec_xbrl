# Future XBRL MCP Interface (Post Layer 3)

This is a future-facing contract. Do not build the MCP before Layers 1-3 and analytical views are stable.

## Core tools
1. `resolve_company(ticker|cik|name)`
2. `get_financial_statement(company, statement, period, view)`
3. `get_fact_series(company, concept, frequency, start, end, view)`
4. `get_breakdown(company, concept, period, breakdown_type=None)`
5. `compare_companies(companies, concept_or_metric, period_or_range, mapping_version=None)`
6. `get_disclosure(company, topic, period=None)`
7. `get_disclosure_changes(company, baseline, current)`
8. `trace_fact(fact_id)`
9. `get_relationship_graph(company, concept, period, network_types=[...])`

## Common response requirements
Return provenance whenever available:
- CIK/accession/form/filed date/period
- reported vs derived
- source fact IDs/formula for derived values
- raw QName/namespace and STANDARD/CUSTOM
- company canonical ID
- cross-company analytical ID
- mapping relation/confidence/version

## Design principle
MCP exposes stable analytical capabilities, not the internal parser object model. Raw tracing is available through dedicated diagnostic tools.
