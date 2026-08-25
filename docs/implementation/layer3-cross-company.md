# Layer 3 — Cross-company Semantic Contract

## Purpose
Create comparable analytical categories across companies while preserving accounting and business-model differences.

## Core distinction
- **Accounting equivalence**: concepts genuinely represent the same standardized accounting meaning.
- **Analytical similarity**: values are useful in the same peer-analysis category but are not accounting equivalents.

Do not collapse these into one relation.

## Mapping tables
### `cross_company_concept_map`
- company canonical concept ID
- analytical concept/category ID
- relation type
- confidence
- evidence/method/version

### `cross_company_axis_map`
Normalize comparable decomposition axes such as product/service, geography, operating segment, customer class where justified.

### `cross_company_member_map`
Map company canonical members to analytical categories.

## Relation types
- `EQUIVALENT`
- `SUBCATEGORY_OF`
- `SUPERSET_OF`
- `ANALYTICALLY_SIMILAR`
- `NOT_COMPARABLE`
- `UNRESOLVED`

## Example
- `AMZN_AWS` -> `CLOUD` with `SUBCATEGORY_OF` or analytical grouping
- `GOOGL_GOOGLE_CLOUD` -> `CLOUD`
- `MSFT_INTELLIGENT_CLOUD` -> `CLOUD` only with explicit note that the reportable segment includes more than cloud services

This prevents a peer chart from pretending the raw reported scopes are identical.

## Mapping inputs
- standard/custom taxonomy identity
- label/documentation
- role/disclosure title
- Axis/Domain hierarchy
- related concepts and CAL structure
- company business context
- historical mapping stability
- optionally external validated reference data

## Outputs for analysis
Every comparison row must expose:
- raw ID
- company canonical ID
- cross-company analytical ID
- mapping relation
- confidence
- source filing/period

## Versioning
Cross-company semantics will evolve. All mappings are versioned and analytical outputs record the mapping version used.

## M8 materialization boundary

`sec_xbrl.cross_company.CrossCompanyMapper` consumes explicit Layer 2 company
canonical IDs and produces additive, independently materializable
`cross_company_concept_map`, `cross_company_axis_map`, and
`cross_company_member_map` rows.  Each row has the company canonical source
ID, analytical ID (where applicable), controlled relation, confidence,
evidence, method, review flag, and mapping version.  It does not use label or
value similarity to manufacture a relation.

`ComparisonPanelBuilder` consumes mapped Layer 2 observations and these rows.
Every output retains `source_raw_id`, `company_canonical_id`, `analytical_id`,
`mapping_relation`, `mapping_confidence`, `source_filing_id`, `source_period`,
and `mapping_version`.  Missing mappings become visible `UNRESOLVED` rows;
they are never discarded or upgraded.  `ANALYTICALLY_SIMILAR` remains that
relation in the panel even when it shares an analytical category with an
`EQUIVALENT` or `SUBCATEGORY_OF` row.

## Exact standard-taxonomy baseline

`CrossCompanyMapper.standard_concept_mappings` can create an automatic
`EQUIVALENT` map only for two or more companies that have the exact same
standard QName and the same non-empty taxonomy family, data type, and period
type. It records all supporting filing IDs in the mapping evidence and uses
`EXACT_STANDARD_TAXONOMY_IDENTITY` as the method. This is a narrow identity
rule, not label matching. Repeated filings for one company canonical concept
produce one mapping row with consolidated company-specific filing and raw-ID
evidence, rather than duplicate mapping rows.

Company extension concepts, including cloud-like product or segment labels,
receive no automatic map. They remain visible as `UNRESOLVED` until a reviewed
mapping with scope evidence explicitly assigns `SUBCATEGORY_OF`,
`SUPERSET_OF`, or `ANALYTICALLY_SIMILAR`. An explicit mapping also cannot
silently override a generated standard mapping for the same company canonical
entity; that collision fails validation.
