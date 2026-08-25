# M0 — Data Contract and Release Governance

## 1. Purpose and scope

This is the governing contract for the analysis-data buildout.  It supplements
the existing Layer 1–3 contracts; it does not replace their detailed schemas
or amend historical source-control milestones.

The target flow is:

```text
SEC filing package
  -> Raw / As-filed Layer 1
  -> Analytical Fact selection and dimensional panel
  -> Derived Metric calculation
  -> Display / Excel
```

The first three arrows are data-production boundaries.  The final arrow is a
read-only consumption boundary.  An Excel workbook is an analytical view, not
a parser, canonicalization engine, or source of truth.

## 2. Data planes and ownership

| Plane | Owner and responsibility | Permitted contents | Prohibited behavior |
|---|---|---|---|
| Raw / As-filed (Layer 1) | Filing extraction | Filing metadata, concepts, contexts, units, reported facts, dimensions, roles, relationships, source text/locators | Cross-filing replacement, comparable-value selection, implicit calculation |
| Analytical | Period, longitudinal, and analysis materialization | Selected reported/recast observations, dimensional facts, company-canonical identity, `as_of_date`, comparability and basis metadata | Mutation of Layer 1 or undisclosed calculation |
| Derived Metrics | Calculation service | Rule-versioned calculations and derived-recast values with all inputs | Representation as a directly reported fact |
| Display / Excel | View builder | Formatting, grouping, filtering, formulas that only render already governed analytical values | ZIP parsing, new business-policy derivations, raw-data mutation |

Layer 2 company mappings and Layer 3 peer mappings are mapping services used by
the Analytical plane.  Their versioned mappings remain additive to raw IDs as
required by `layer-model.md`, `layer2-longitudinal.md`, and
`layer3-cross-company.md`.

## 3. Minimum logical entities and grain

Physical stores may vary, but every published record below must be uniquely
addressable and traceable.

| Entity | Minimum grain | Required identity and lineage |
|---|---|---|
| Reported Fact | One fact in one filing/context/unit/concept | `fact_id`, `filing_id`, CIK, accession, form, filed date, report date, raw concept QName/namespace, context, unit, value, source document/locator |
| Dimensional Fact | One reported fact × axis assignment | `fact_id`, raw axis ID, raw member ID or typed member, dimension type/default status; retains its parent Reported Fact lineage |
| Analytical Fact | One selected value for company × period × canonical/raw concept × full dimension signature × analysis view | `analytical_fact_id`, `as_of_date`, `view`, `basis_version`, selection rule/version, selected raw fact ID(s), mapping version(s), comparability status |
| Derived Metric | One calculated metric for company × period × full dimension signature × calculation rule version | `derived_metric_id`, metric ID, formula/rule version, input analytical/raw fact IDs, calculation timestamp, `as_of_date`, basis compatibility result, unavailable reason when absent |

The **full dimension signature** is the sorted set of all explicit axis/member
and typed-dimension assignments.  It may not be reduced to a display label.
Contexts, units, concepts, filing identifiers, and mapping versions are
foreign-key-equivalent lineage references even if stored in Parquet.

## 4. Status, source, and selection taxonomy

`source_type` is mandatory for Analytical Fact and Derived Metric outputs:

| `source_type` | Meaning | Required lineage |
|---|---|---|
| `REPORTED` | Directly reported in the source filing selected for the view | exactly one selected Layer 1 fact ID and its source filing |
| `RECAST_REPORTED` | Directly reported by a later filing as a comparative/recast value | selected fact ID, source filing, original target period, documented recast/basis evidence |
| `DERIVED_RECAST` | Recast-period value calculated only from compatible recast inputs | formula, all input IDs, compatible basis version, derivation rule version |
| `DERIVED_METRIC` | Analytical metric calculated from governed inputs | formula/rule version and all input IDs |
| `UNAVAILABLE` | No safe reported or derived value exists | explicit reason code; no numeric value |

`REPORTED` in this table is an analytical selection status.  Layer 1 always
uses `reported_or_derived = REPORTED` for its source facts as specified in
`layer1-schema.md`.

Rules:

1. **Raw immutability:** an accession's Layer 1 facts are never changed to
   reflect a later filing, amendment, or recast.
2. **As-filed view:** selects only facts that were available in filings filed on
   or before `as_of_date`, without later-recast substitution.
3. **Current / Comparable view:** also respects `as_of_date`; it may select a
   later comparative/recast fact only with a recorded `basis_version` and
   evidence.  The raw earlier observation remains available.
4. **Basis compatibility:** a comparison, aggregation, or derivation must use
   one compatible basis version.  Values from two basis versions must not be
   mixed.  If compatible component facts cannot be identified, output
   `UNAVAILABLE`, not an estimated numeric value.
5. **Recast evidence:** a numerical difference is a candidate, not proof.  A
   `RECAST_REPORTED` selection requires a filing/table/text or reviewed mapping
   evidence record that binds the changed value to a basis/recast explanation.
6. **Period compatibility:** uses the Context-first rules in
   `period-rules.md`; QTD, YTD, FY, Instant, ratios, and non-additive metrics
   are never silently interchanged.

## 5. Data-quality gates and publication states

No plane may publish a `SUCCESS` snapshot while a required gate has failed.
Each run records `expected_count`, `actual_count`, validation rule version,
input identifiers, timestamp, and one of `PENDING`, `SUCCESS`, or `FAILED`.
Failures are retryable and do not mutate prior successful immutable snapshots.

| Gate | Applies to | Expected vs actual check | Failure state / effect |
|---|---|---|---|
| `RAW_CORPUS_COMPLETENESS` | Layer 1 | Expected source fact corpus vs materialized facts, including numeric/text/nil policy and exclusion reasons | `VALIDATION/FAILED`; no partial Layer 1 snapshot is published as success |
| `TAXONOMY_AND_TRANSFORM_RESOLUTION` | Layer 1 | Required taxonomy imports, concepts, and Inline transformations resolve under the declared cache/version | `ARELLE_LOAD` or `VALIDATION/FAILED`; source package remains immutable and retryable |
| `ATOMIC_FILING_SNAPSHOT` | Layer 1 | Facts, contexts, units, dimensions, roles, and PRE/CAL/DEF relationships reference the same filing/package/parser snapshot | `VALIDATION/FAILED`; do not publish facts without their required related snapshot tables |
| `PERIOD_AND_BASIS_COMPATIBILITY` | Analytical / Derived | Candidate components share required period class, dimension signature, unit semantics, and basis version | `UNAVAILABLE`; retain diagnostic reason and inputs considered |
| `FORMULA_LINEAGE` | Derived Metrics | Every numeric output has a formula/rule version and complete input IDs; recomputation is possible | `VALIDATION/FAILED`; derived output is not published |

The filing failure stages in `accession-contract.md` remain authoritative for
discovery/package/parser errors.  This contract adds logical gate names rather
than replacing those stages.

## 6. Release and PR policy

`main` is the passing, merge-ready baseline.  Every milestone follows
`delivery-workflow.md` and this checklist:

1. Create the milestone branch from the latest passing `main`; record the base
   SHA in the PR.
2. Define the milestone's new acceptance checks before implementation.
3. The implementation session is the only writer; it self-tests, commits,
   pushes, and freezes a candidate SHA.
4. An independent verifier reruns the relevant acceptance checks and full
   regression against that frozen SHA and reports `PASS` or `FAIL`.
5. The PR includes artifact/impact comparison between base and candidate:
   schema, counts, key analytical outputs, and display artifacts where in
   scope.  A no-change result is recorded when applicable.
6. Merge into `main` only after the new acceptance checks, full regression,
   impact comparison, review, and CI pass.

### Output-change decision rule

- **Intentional change:** may merge only when the PR records before/after
  values or artifacts, affected key/period, source filing(s), raw fact IDs or
  other provenance, the governing rule change, and the expected user-visible
  effect.  The evidence must show why the new result is more correct.
- **Unexpected change:** is a regression.  It blocks merge until resolved or
  explicitly reclassified as an intentional change with the above evidence.
- **No data claim:** a documentation-only milestone must not claim that prior
  branches or generated outputs have become compliant merely by reference.

PR title and body must be bilingual (Korean and English), use real line
breaks, and be read back after creation as required by `delivery-workflow.md`.

## 7. Dependency, migration, and current branch policy

M0 establishes the contract first.  It does not retrofit historic commits.

- The unmerged `feature/m1-inline-xbrl-completeness` candidate must rebase or
  otherwise align to the M0 merge commit before its PR is approved.
- It must demonstrate at least one successful cached-taxonomy Inline XBRL
  extraction with complete reported and dimensional fact validation.  A
  fail-closed result alone is insufficient for M1 acceptance.
- The successful fixture must be general, contract-driven behavior—not an
  NVIDIA-only exception.  NVIDIA FY2026 Q3 remains a required regression case
  once its compliant cached taxonomy fixture is available.
- Existing feature branches remain subject to their own original contracts;
  they are not silently retroactively certified by M0.  Any adoption PR must
  provide a M0 impact comparison and any needed migration.

## 8. M0 acceptance checklist

- [ ] Data-plane ownership and prohibited responsibilities are documented.
- [ ] Minimum grain, identifiers, provenance, and full dimension signature are
      specified for Reported Fact, Dimensional Fact, Analytical Fact, and
      Derived Metric.
- [ ] `REPORTED`, `RECAST_REPORTED`, `DERIVED_RECAST`, `DERIVED_METRIC`, and
      `UNAVAILABLE` are defined with lineage requirements.
- [ ] As-of, basis-version, raw-immutability, recast-evidence, and compatibility
      rules are documented.
- [ ] All five quality gates define expected/actual checks and failure effects.
- [ ] Release/PR policy includes frozen independent verification, full
      regression, impact comparison, and intentional-change evidence.
- [ ] M1 Inline XBRL dependency and non-retroactive branch policy are explicit.
- [ ] Roadmap and acceptance plan point to this contract without erasing
      historical M0 discovery records.

## 9. Assumptions and deferred cases

- This is a logical contract, not a physical-schema migration.  M1–M7 will
  introduce tables and services incrementally.
- The exact taxonomy-cache distribution, refresh, and security policy belongs
  to the M1 implementation/operations contract, but M1 must supply a
  reproducible offline success case.
- Recast evidence extraction and review workflow are deferred to the
  longitudinal/period milestone; M0 only sets the required outcome.
- Excel cell formulas may assist presentation, but any persisted business metric
  must be governed in the Derived Metrics plane before display.
