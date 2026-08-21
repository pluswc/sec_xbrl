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
