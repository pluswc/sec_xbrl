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

## As-of governed selection

Layer 2 keeps all observations and exposes two deterministic selection views;
neither view changes a Layer 1 Fact.

- `AS_FILED`: for each target period, retain the first directly reported
  observation available on or before the requested `as_of_date`.  A later
  comparative value never overwrites that historical result.
- `LATEST_RECAST`: select the latest eligible `basis_version` available on or
  before `as_of_date` for a complete comparable period family.  Every selected
  quarter in that family must use that same basis.  A target period that is
  absent from the chosen basis is emitted as `N/A` / `UNAVAILABLE` with
  `PERIOD_NOT_AVAILABLE_IN_SELECTED_BASIS`; the selector must not fill it from
  an earlier basis.

An observed series row carries `source_raw_fact_id`, `source_filing_id`,
`filed_date`, `period_key`, `period_class`, company canonical concept and full
dimension key, `basis_version`, `source_type`, mapping version/evidence, and
the original Fact lineage.  `source_type` is one of `REPORTED`,
`RECAST_REPORTED`, or `DERIVED_RECAST` before selection.  A selected unavailable
row has `source_type=UNAVAILABLE`, no selected raw Fact ID, and an explicit
reason.

`RECAST_REPORTED` is eligible only with a bound recast evidence ID/payload.
`DERIVED_RECAST` is eligible only with all source Fact IDs and a derivation-rule
version.  Numeric changes, labels, or filing sequence alone do not prove a
recast or make a basis comparable.  Unknown/unsupported basis metadata is
unavailable in `LATEST_RECAST` rather than being guessed.

The selector records `as_of_date`, `view`,
`selection_rule_version=m7-as-of-selection-v1`, selected raw Fact ID, source
type, basis version, and unavailable reason.  It is generic across companies;
company-specific recasts require supplied filing/table/text/review evidence.

### Recast observation materialization

`RecastObservationBuilder` is the analysis-layer adapter between multiple
immutable Layer 1 snapshots and the as-of selector.  It receives Layer 2
observations plus a reviewed `recast_evidence` record; it does not parse a ZIP
or rewrite a Fact.  A recast evidence record binds the later `source_raw_fact_id`
and `source_filing_id` to a `basis_version`, target period, source document and
locator, explicit re-presentation flag, and one or more earlier filing IDs.
Narrative excerpt/table evidence may be retained with the record.

The adapter emits `RECAST_REPORTED` only when the later Fact and at least one
earlier Fact share CIK, company canonical concept, complete canonical
dimension key, unit, period class, and target period; the earlier filing must
actually precede the later one.  A changed value, label, or filing sequence is
not evidence.  Rows without a bound evidence record stay `REPORTED` and remain
available to `AS_FILED`, but have no guessed `basis_version` and cannot enter
`LATEST_RECAST`.  The adapter stores `recast_event_id`, evidence ID/payload,
and prior raw Fact IDs so both histories remain traceable.

## Mapping QA
Every automatic mapping above a materiality threshold must be explainable by stored evidence. Low-confidence mappings remain separate until reviewed or corroborated.

## M7 materialization boundary

`sec_xbrl.longitudinal.CompanyCanonicalizer` consumes copies of ordered Layer
1 filing and concept records and produces additive `company_concept_map`,
`company_axis_map`, `company_member_map`, and `structural_change` rows.  A
mapping row stores the source raw ID, company canonical ID, filing validity
range, relation, method, confidence, evidence, mapping version, continuity
break, and review flag.  It never rewrites Layer 1 identity or facts.

`SeriesBuilder` consumes facts previously enriched with M6 `period_class` and
these mappings.  Its Annual output is 10-K/FY focused; Current output accepts
10-K and 10-Q observations.  Both include `period_class` in the series key, so
QTD, YTD, FY, and instant observations cannot coalesce.  An uncertain map or
unmapped dimensional member is marked `mapping_review_required` rather than
silently joining an existing canonical series.

A documented segment recast is additive: it emits a new `RECAST` mapping
version, new canonical member ID, and `continuity_break=true`, while the prior
mapping keeps its original validity and identity.
# L2-M1 period-observation boundary

`PeriodObservationMaterializer` is the first durable Layer 2 producer.  It
copies each usable Layer 1 Fact into `period_observation` with raw Fact,
filing, Context, Unit, Concept QName, and complete Axis/Member/typed-member
signature lineage.  Context dates and the raw concept period type determine
`QTD_3M`, `YTD_6M`, `YTD_9M`, `FY`, `INSTANT`, or `OTHER_DURATION`; the period
class is part of the raw series identity, so these observations cannot be
mixed before canonical mapping or selection.

A malformed Layer 1 reference is emitted as `period_observation_exclusion`
with a source Fact identity and controlled reason.  It is never silently
dropped.  A Q4 candidate is opt-in: callers must supply reviewed canonical
concept, additivity, `ADDITIVE_AMOUNT` value-kind, structural/recast, and
comparability policy per source Fact.  The shared compatibility gate then also
requires equal units, full dimensions, fiscal year and Context start.  EPS,
weighted-average shares, ratios, margins, averages, and other non-additive
values cannot meet that policy and are never subtraction-derived.
