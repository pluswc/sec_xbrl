# SEC `durweek` parser runtime delivery

## 1. Scope and status

This delivery adds generic parser support for the SEC Inline XBRL
`ixt-sec:durweek` transformation in namespace
`http://www.sec.gov/inlineXBRL/transformation/2015-08-31`. It is a parser
compatibility extension for cached or future SEC filings, not a Deere-specific
rule and not an accounting-policy change.

The authorized implementation changes only the SEC transform registry, its
unit contract, the Layer 1 parser version, and these implementation documents.
It performs no download, cache rewrite, raw snapshot overwrite, analytical
mapping, calculation, or validation suppression.

## 2. Primary rule and implementation contract

The SEC-staff Arelle EDGAR implementation defines `durweek` as a days-only
duration because XML Schema duration has no week component. Its decimal grammar
is:

```text
^[ \t\n\r]*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)[ \t\n\r]*$
```

The implementation multiplies the absolute magnitude by seven, truncates the
result to whole days, and retains a negative sign only when the truncated result
is greater than zero. The primary reference is the SEC-staff
[Arelle EDGAR transform module](https://github.com/Arelle/EDGAR/blob/master/transform/__init__.py),
especially its `durweek`, decimal parsing, and duration rendering functions.

The local `_week_duration` function is deliberately separate from
`_decimal_duration(value, "D")`. The existing day helper rounds half up, while
the SEC week transform truncates. The week helper uses `Decimal` under a local
precision derived from the complete input coefficient, so its result is exact
regardless of the caller's ambient decimal context.

Accepted examples include:

| Input | Output |
| --- | --- |
| `13`, `26`, `39`, `52`, `53` | `P91D`, `P182D`, `P273D`, `P364D`, `P371D` |
| `2.25`, `.5`, `+1.` | `P15D`, `P3D`, `P7D` |
| `-1.5` | `-P10D` |
| `0`, `-0`, `-0.1` | `P0D` |

Only XML whitespace surrounding the number is accepted. Empty input, words,
unit suffixes, exponent notation, comma grouping, non-finite values, repeated
signs, underscores, and non-ASCII digits fail transformation validation.

## 3. Immutable parser identity

`Layer1Extractor.parser_version` advances from `m2-layer1-v2` to
`m2-layer1-v3`. Existing v1/v2 snapshots are unchanged. A retry using v3 writes
to a fresh parser-version destination and remains subject to the same
taxonomy/transform, complete-corpus, and atomic-publication gates in
`m1-inline-xbrl-completeness.md`.

Unknown SEC transformation names remain errors. Registration of `durweek` does
not suppress Arelle validation messages or make a partial filing successful.

## 4. Cached runtime acceptance

The motivating runtime evidence is 19 cached Deere filings whose only diagnosed
registry blocker was `ixt-sec:durweek` on `us-gaap:FiscalPeriodDuration`. The
focused acceptance replay uses two already-extracted primary documents and the
existing local package, index, and taxonomy caches, with network disabled:

- quarterly accession `0001558370-22-001900`, primary document
  `de-20220130x10q.htm`;
- 53-week annual accession `0001104659-25-122321`, primary document
  `de-20251102x10k.htm`.

Each retry must target a fresh `/tmp` destination. Acceptance requires:

1. the SEC registry no longer reports `durweek` as an unknown transformation;
2. `FiscalPeriodDuration` materializes with the transformed duration value;
3. the validated non-tuple source fact count equals the materialized Fact count;
4. all existing taxonomy/transform and atomic Layer 1 gates continue to run;
5. no network bootstrap occurs and no cached or previous snapshot is rewritten.

The full 19-filing operational retry remains a separate lead-run acceptance
step after a frozen commit and independent read-only verification.

### Local cached replay evidence

On 2026-10-08 the implementation writer replayed the two focused filings from
the declared caches with network disabled. The taxonomy cache was copied to a
fresh `/tmp` workspace before parsing so the shared cache could not be mutated.
Each filing used a separate fresh extraction, snapshot, and parse-state root.

| Accession | Source / materialized Facts | `FiscalPeriodDuration` values | Gate result |
| --- | ---: | --- | --- |
| `0001558370-22-001900` | 1,857 / 1,857 | `P91D`, `P91D` | all three gates succeeded |
| `0001104659-25-122321` | 3,236 / 3,236 | `P371D`, `P364D`, `P364D` | all three gates succeeded |

The manifests report parser version `m2-layer1-v3`. The quarterly and annual
package SHA-256 values were respectively
`49faa9793e8417d9d87466a1ac2296aac97aebed0c940a1b4ef9bdc77d828aba`
and `8c7d4dfa825bc853a3329a7c5270df941cc1bd5b764f482ecaa00a66fda5e7ba`.
No `durweek` registry error remained. This is implementation self-test evidence,
not independent verification, local acceptance, or the full 19-filing retry.

## 5. Deferred observations

The existing local implementations of `durday`, `durmonth`, and `duryear` do
not fully mirror every arithmetic detail of the SEC-staff reference. Those
pre-existing discrepancies are separately scoped parser work. This delivery
does not alter them, reinterpret existing snapshots, or infer that their current
outputs are SEC-equivalent.

On 2026-10-08 the user subsequently authorized that separate correction. Its
scope, exact arithmetic and rendering rules, initial `m2-layer1-v4` candidate,
subsequent complete `m2-layer1-v5` migration, and verification gates are governed by the
[SEC numeric-duration conformance delivery](sec-duration-conformance-delivery.md).
This later status does not rewrite the v3 evidence above or mutate its Raw
artifacts.
