# Layer Model

## Layer 1 — Raw / As-filed
Source of truth for each filing.

Stores:
- filing metadata and accession provenance
- concepts with QName/namespace/taxonomy metadata
- facts and contexts
- units
- dimensional Axis/Member assignments
- role metadata
- PRE/CAL/DEF relationships and targetRole
- labels/documentation
- reported vs derived provenance

No cross-filing semantic merging is allowed.

## Layer 2 — Longitudinal Canonical
Purpose: stable same-company time series.

Examples:
- `aapl:IPhoneMember` in different yearly taxonomy namespaces -> one company canonical member when evidence supports continuity.
- old segment names -> new/recast segment identities with temporal validity.

Required mapping evidence:
- local name
- label/documentation
- Axis identity
- Domain/parent hierarchy
- role/disclosure context
- unit/period type
- value continuity and recast evidence when relevant

Outputs:
- company canonical concept/axis/member IDs
- mapping method
- confidence
- valid-from / valid-to filing or period
- mapping evidence
- continuity break flags

Layer 2 maintains separate analytical series:
- Annual Series: 10-K oriented
- Current Series: 10-K + 10-Q, period-class aware

## Layer 3 — Cross-company Semantic
Purpose: peer comparison without claiming false accounting equivalence.

Examples:
- company-specific cloud business members -> analytical category `CLOUD`
- geography members -> normalized geography groups
- service/product classifications -> comparable analytical families

Every mapping records:
- raw/company canonical source ID
- target analytical category
- relation type: `EQUIVALENT`, `SUBCATEGORY`, `ANALYTICALLY_SIMILAR`, `NOT_COMPARABLE`
- mapping method
- confidence
- evidence
- reviewer/version metadata

### Critical rule
`AWS`, `Google Cloud`, and `Intelligent Cloud` may belong to a common analytical group, but they are not therefore the same accounting concept.

## Graph vs Panel
- **Graph** explains meaning and structure: Concept/Role/Axis/Member/DEF/CAL.
- **Panel** supports calculations: Company x Period x Canonical Concept x Axis/Member x Value.
