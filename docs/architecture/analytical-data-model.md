# Analytical Data Model

## 1. Purpose

This document defines the durable logical model between immutable SEC XBRL
extraction and user-facing analysis.  It answers **which governed data an
analysis consumer reads**, rather than how a milestone is released.  Release
and PR controls remain in `docs/implementation/m0-data-contract.md` and
`ADR-004`.

The platform is provenance-first: every analytical number must be traceable to
a reported XBRL fact, a documented comparable/recast selection, or a rule with
complete inputs.  Excel, APIs, and dashboards consume this model; they are not
parsers or policy engines.

```text
Raw / As-filed Layer 1
  ├─ Reported Fact + Context + Unit + full Dimensions + relationships
  └─ source filing and source locator
             ↓
Analytical plane
  ├─ Analytical Fact selection (AS_FILED or CURRENT_COMPARABLE)
  └─ Dimensional Analytical Fact panel
             ↓
Derived Metrics plane
  └─ governed rule + compatible inputs + formula lineage
             ↓
Consumers: Excel | API | dashboard | research workflow
```

## 2. Plane responsibilities

| Plane | Durable purpose | Examples | Must not do |
|---|---|---|---|
| Raw / As-filed Layer 1 | Preserve each filing's original XBRL meaning | facts, contexts, units, axis/member assignments, roles, relationships, text provenance | replace prior facts with later information or calculate business metrics |
| Analytical | Create an as-of governed panel from raw facts and versioned mappings | a quarterly revenue series, segment/geographic breakdown, current/comparable selection | mutate raw facts or hide an incompatible basis |
| Derived Metrics | Materialize calculations whose formula and inputs are explicit | gross margin, growth, compatible derived Q4, FCF | present a calculation as a directly reported value |
| Consumer | Render or query governed values | Excel earnings model, API response, dashboard chart | parse a filing, select a recast, or invent a calculation policy |

Layer 2 company canonical mappings and Layer 3 cross-company mappings enrich
the Analytical plane.  They never replace raw concept, axis, or member IDs.

## 3. Logical entities, grain, and keys

All physical implementations (Parquet, database, or service) must preserve the
following logical grain and identifiers.

| Entity | Grain | Primary key | Required references |
|---|---|---|---|
| `reported_fact` | one fact in one filing, context, unit, and raw concept | `fact_id` | `filing_id`, raw concept ID, `context_id`, optional `unit_id`, source document/locator |
| `dimensional_fact` | one `reported_fact` × axis assignment | `fact_id` + raw axis ID | raw member ID or typed value, dimension type, default flag |
| `analytical_fact` | one selected value for company × period × concept × full dimension signature × view × as-of date | `analytical_fact_id` | selected `fact_id`, company canonical ID if mapped, mapping version(s), selection rule version |
| `derived_metric` | one calculated metric for company × period × full dimension signature × rule version × as-of date | `derived_metric_id` | metric ID, formula/rule version, ordered input IDs, compatibility result |

### Common key components

- **Company and filing:** CIK, accession, form, `filed_date`, `report_date`,
  package/parser snapshot identifiers.
- **Raw semantic identity:** QName/namespace-aware raw concept ID; never local
  name alone.  Axis/member IDs remain QName-aware.
- **Context and measurement:** Context period, entity, unit, decimals, and
  numeric/text/nil representation.
- **Full dimension signature:** a stable sorted representation of *every*
  explicit axis/member and typed-dimension assignment.  It is a semantic key,
  not a display label.
- **Temporal analysis key:** actual period boundaries plus period class
  (`QTD_3M`, `YTD_6M`, `YTD_9M`, `FY`, `INSTANT`, or controlled alternative).
  Period class comes from Context and the period contract, not the filing label.

`dimensional_fact` is deliberately separate: a fact can have zero, one, or
many assignments, and the same reported concept may be a total or a member
value depending on its complete context.

## 4. Analytical selection model

`analytical_fact` does not copy a raw value without explaining why it was
chosen.  It stores these minimum attributes in addition to the common keys:

| Attribute | Meaning |
|---|---|
| `view` | `AS_FILED` or `CURRENT_COMPARABLE` (future controlled views may be added) |
| `as_of_date` | latest permitted filing date for the selection; never a display-only filter |
| `basis_version` | identified reporting basis, such as a geography methodology version |
| `source_type` | `REPORTED`, `RECAST_REPORTED`, `DERIVED_RECAST`, or `UNAVAILABLE` |
| `selection_rule_version` | deterministic rule or reviewed policy that chose the observation |
| `comparability_status` | compatible, incompatible, uncertain, or controlled equivalent |
| `selected_fact_id` | the raw fact supporting a reported/recast selection; nullable only for unavailable output |
| `evidence_id` | narrative/table/review evidence for a recast or basis change when required |

### Selection rules

1. `AS_FILED` can use only information filed on or before `as_of_date`; later
   comparative values never overwrite earlier raw observations.
2. `CURRENT_COMPARABLE` can use a later directly reported comparative value only
   when recast/basis evidence is bound to the selection.
3. A numerical difference across filings is a candidate signal, not sufficient
   recast proof.
4. Components of an aggregation or derivation must share compatible period,
   unit semantics, full dimension signature, and `basis_version`.
5. If a safe selection cannot be made, publish `UNAVAILABLE` with a reason
   code—never mix old and new bases or create an unlabelled estimate.

This model supports both the immutable historical value and the analysis-ready
current value without collapsing them into one column.

## 5. Derived metrics and derivations

Derived outputs are a separate plane because they have different truth claims.
They must retain:

- `metric_id` and metric-definition version;
- formula or rule version, including sign and scaling convention;
- ordered raw/analytical input IDs and their values at calculation time;
- input selection/mapping versions and `as_of_date`;
- period, unit, dimension, and basis compatibility results;
- calculation timestamp and output status (`DERIVED_METRIC`,
  `DERIVED_RECAST`, or `UNAVAILABLE`).

Examples:

| Output | Valid only when | Output type |
|---|---|---|
| Gross Margin | reported/selected Gross Profit and Revenue have compatible period/basis | `DERIVED_METRIC` |
| Revenue Growth | selected periods share comparable definition and period class | `DERIVED_METRIC` |
| Q4 flow | compatible additive FY and YTD 9M inputs exist | derived value; not valid for EPS, ratios, averages, or non-additive metrics |
| Recast Q2 | compatible recast YTD/QTD components and evidence exist | `DERIVED_RECAST` |

If a company directly reports a metric, that observation remains a Reported
Fact.  A mathematically equivalent calculation is still a separate derived
record and may be used as validation rather than substitution.

## 6. Consumption contract

Consumers receive governed rows—not parser objects or unqualified source ZIP
contents.  A consumer request/output must be able to carry:

- company, period/frequency, selected view, and `as_of_date`;
- analytical or metric ID, value, unit/scaling, and full dimension signature;
- `source_type`, `basis_version`, comparability status, and unavailable reason;
- raw fact/source filing references, mapping versions, formula/input lineage as
  appropriate to the requested detail level.

Excel may apply layout, labels, indentation, conditional formatting, totals,
and presentation-only formulas.  It cannot promote a newly computed value to a
persisted analytical metric, decide a recast is comparable, or fill a missing
value.  The same rule applies to APIs and dashboards.

## 7. Migration and prototype exception

Existing direct-ZIP Excel builders are **legacy/prototype paths** retained only
for comparison and controlled transition.  They are not the target data
architecture and cannot establish a new analytical policy.

Migration occurs in this order:

1. make Layer 1 complete and filing-atomic;
2. materialize governed Analytical Fact and dimensional panel outputs;
3. materialize Derived Metrics with lineage and compatibility checks;
4. switch an Excel/API/dashboard view to consume the governed outputs;
5. compare prototype and governed artifacts, documenting intentional changes
   with source/provenance evidence before retiring the prototype path.

Until a consumer is migrated, its output is explicitly labelled prototype and
must not be used as proof that the durable model has selected or derived a
value correctly.

## 8. Related contracts

- Governance, quality gates, release policy:
  `docs/implementation/m0-data-contract.md`
- Raw schema: `docs/implementation/layer1-schema.md`
- Period and compatible derivation rules: `docs/implementation/period-rules.md`
- Same-company mapping: `docs/implementation/layer2-longitudinal.md`
- Cross-company mapping: `docs/implementation/layer3-cross-company.md`
