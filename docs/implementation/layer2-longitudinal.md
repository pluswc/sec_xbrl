# Layer 2 — Longitudinal Canonical Contract

## Purpose
Connect the same company's economic concepts, axes and members across 10-K/10-Q filings without changing Layer 1 raw identity.

## Mapping entities
- `company_concept_map`
- `company_axis_map`
- `company_member_map`

Each mapping contains:
- source raw ID
- company canonical ID
- valid-from / valid-to filing or period
- relation (`SAME`, `RENAMED`, `RECAST`, `SPLIT`, `MERGED`, `UNCERTAIN`)
- method
- confidence
- evidence payload
- mapping version

## Matching evidence hierarchy
1. exact standard taxonomy identity + compatible context semantics
2. same company local name + same axis/domain/role + label match
3. documented recast/reclassification relationship
4. structural similarity (DEF/CAL/Role)
5. value/series continuity as supporting evidence only
6. text/semantic similarity as lower-confidence support

Never confirm identity from string similarity alone.

## Structural change events
Detect and persist:
- `NEW_CONCEPT`
- `NEW_AXIS`
- `NEW_MEMBER`
- `MEMBER_RENAME`
- `SEGMENT_RECAST`
- `SPLIT`
- `MERGE`
- `ROLE_RESTRUCTURE`
- `UNKNOWN_CHANGE`

## Annual Series
10-K-centered, prioritizes FY facts and annual breakdowns.

## Current Series
10-K baseline + subsequent 10-Q updates. Period class is part of the series key; QTD/YTD/Instant are never mixed.

## Mapping QA
Every automatic mapping above a materiality threshold must be explainable by stored evidence. Low-confidence mappings remain separate until reviewed or corroborated.
