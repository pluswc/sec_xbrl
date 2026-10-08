# SEC numeric-duration conformance delivery

## 1. Authority, scope, and current status

On 2026-10-08 the lead reported that Raw Layer 1 had normalized some SEC
numeric-duration Facts differently from the SEC-staff transform reference and
proposed a standard correction plus fresh-version reprocessing. The user
authorized that bounded repair with: `진행해줘. 큰 문제는 아닌것 같네`.

This delivery is therefore **APPROVED for local implementation**. It corrects
the generic SEC Inline XBRL `durday`, `durmonth`, and `duryear` transforms and
applies the already-governed strict numeric lexical contract to all four
numeric-duration transforms, including `durweek`. The later fail-closed cohort
diagnostic also corrects four supported SEC-staff lexical forms that the
partial local transform registry had omitted. It advances the Layer 1 parser
identity so corrected Facts can be written only as a fresh immutable history.
Implementation, independent verification, local acceptance, PR, CI, merge,
and operational cohort reprocessing remain separate states.

This delivery does not change filing discovery, source packages, Context
dates, period classification, Q4 derivation or other business policy,
analytical mappings, metadata enrichment, or dashboards. Other than the four
named supported lexical forms in Section 6, it does not change non-numeric
duration Inline transforms. It does not overwrite an old Raw snapshot or
reinterpret a reported Fact as derived. The source lexical value remains in
the immutable primary document and is reachable through the Fact's source
document/locator trace; the normalized value remains a reported XBRL value.

## 2. Defect and primary reference

The confirmed example is AMD accession `0000002488-23-000047`, concept
`us-gaap:SharebasedCompensationArrangementBySharebasedPaymentAwardFairValueAssumptionsExpectedTerm1`.
Its Inline source lexical value is `4.55`. Parser v3 stored `P4Y7M`; applying
the SEC-staff algorithm produces `P4Y6M18D`.

The normative implementation reference is the SEC-staff maintained
[Arelle EDGAR transform module](https://github.com/Arelle/EDGAR/blob/master/transform/__init__.py),
specifically `duryear`, `durmonth`, `durweek`, `durday`, `getValue`,
`decimalValuePattern`, and `durationValue`. The local implementation preserves
that transform structure and rendering behavior while using exact decimal
arithmetic so caller Decimal settings cannot alter a result.

## 3. Numeric lexical and arithmetic contract

All four transforms accept only a Python `str` matching this complete ASCII
decimal grammar, with XML whitespace allowed only around the number:

```text
^[ \t\n\r]*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)[ \t\n\r]*$
```

Empty input, non-string input, words, a unit suffix, exponent notation, comma
grouping, underscores, non-finite values, repeated signs, and non-ASCII digits
are rejected. A transform never guesses a default unit; an unsupported unit is
an error.

After parsing, arithmetic uses the absolute magnitude `n`. `int` below means
truncation toward zero; because `n` and intermediate components are
non-negative, it is equivalent to taking the mathematical floor.

```text
duryear:
  years = int(n)
  raw_months = (n - years) * 12
  months = int(raw_months)
  days = int((raw_months - months) * 30.4375)

durmonth:
  months = int(n)
  days = int((n - months) * 30.4375)

durweek:
  days = int(n * 7)

durday:
  days = int(n)
  hours = int((n - days) * 24)
```

No component is rounded half up. Smaller fractional components after the
declared final unit are truncated. Components are not normalized into a
different larger unit: twelve rendered months do not silently become one year,
and 365 rendered days do not silently become one year.

The SEC-staff reference currently parses through binary `float`. This delivery
uses `Decimal` with a local precision derived from the complete coefficient and
the fixed multipliers. That choice implements the stated decimal algorithm
exactly and deterministically for SEC decimal lexical input, including all
observed two-decimal duration values, without inheriting binary-float boundary
artifacts or the caller's ambient Decimal precision. Acceptance fixes the
reference results for the observed values `4.55`, `2.74`, and `5.98` and for
boundary-oriented unit cases. A future requirement to reproduce a binary-float
artifact would require separate evidence and approval.

## 4. SEC duration rendering contract

The renderer retains the units supplied by the selected transform:

- year values can render years, months, and days;
- month values can render months and days;
- week values render days only;
- day values can render days and hours, with `T` before hours.

Zero smaller components are omitted according to the SEC-staff
`durationValue` behavior, while the first applicable zero unit identifies an
all-zero result. Thus `0.1` day is `P0DT2H`, `0.5` month is `P0M15D`, and
`0.01` year is `P0Y3D`. Exact zero renders as `P0Y`, `P0M`, or `P0D` according
to the transform. A negative sign is retained only when at least one rendered
component is nonzero, so negative inputs whose components all truncate to zero
produce the same positive zero spelling.

Required examples include:

| Transform | Source | Result |
| --- | ---: | --- |
| `duryear` | `4.55` | `P4Y6M18D` |
| `duryear` | `2.74` | `P2Y8M26D` |
| `duryear` | `5.98` | `P5Y11M23D` |
| `durmonth` | `1.5` | `P1M15D` |
| `durday` | `2.5` | `P2DT12H` |
| `duryear` | `-0.001` | `P0Y` |
| `durmonth` | `-0.001` | `P0M` |
| `durday` | `-0.001` | `P0D` |

## 5. Immutable parser-version migration

The numeric-duration candidate first advanced `Layer1Extractor.parser_version`
from `m2-layer1-v3` to `m2-layer1-v4`. The cohort diagnostic then found four
supported lexical gaps after 38 partial v4 snapshots had been written for AMD
and Apple. The complete candidate therefore advances again to
`m2-layer1-v5`. Existing v1 through v4 source packages, snapshots, manifests,
and parse-state history remain byte-identical and readable. The complete
normalization is produced only by a fresh v5 destination; no in-place Raw
correction is permitted and the partial v4 histories are not accepted as the
21-company result.

Every v5 replay remains subject to the existing
`TAXONOMY_AND_TRANSFORM_RESOLUTION`, `RAW_CORPUS_COMPLETENESS`, and
`ATOMIC_FILING_SNAPSHOT` gates. An invalid duration lexical value or unknown
transform fails closed. The parser-version change does not relax taxonomy
resolution, Fact completeness, relationship integrity, or atomic publication.

The expected intentional differences from the same filing under an earlier
parser version are only:

1. normalized values of Facts that use `durday`, `durmonth`, or `duryear` and
   whose prior local result differs from this contract; and
2. normalized values for the four supported lexical repairs enumerated in
   Section 6; and
3. parser-version provenance and identifiers derived from that version where
   the immutable schema requires it.

Fact source lexicals, monetary and other numeric values, reported source type,
Context and Unit records, dimensions, and relationship keys must otherwise
compare equal. Any foreign type change blocks acceptance.

## 6. Acceptance and evidence

### Unit and regression gates

Focused unit tests cover the required observed year values, fractional month
and day values, positive/negative/exact/tiny-zero rendering, unchanged exact
integer behavior, strict grammar rejection for all four transforms, invalid
unit rejection, and arithmetic under a deliberately small ambient Decimal
precision. Existing non-duration transforms and `durweek` behavior remain
covered. The focused test, full offline test suite, and Ruff must pass against
the same frozen commit.

### Cached filing replay

Implementation self-test replays these already-cached primary documents with
network disabled, a copied taxonomy cache, and separate fresh `/tmp` v4
destinations:

- one AMD quarterly filing;
- the AMD annual filing containing the confirmed `4.55` year value;
- one NVIDIA annual filing;
- the Deere 53-week annual filing used by the `durweek` delivery.

The original cached packages, taxonomy cache, and earlier snapshots remain
unchanged. Each replay must pass the same complete-corpus, taxonomy/transform,
and atomic gates. A before/after comparison must identify only the allowed
duration values and parser provenance; monetary values, Context/Unit/dimension
records, and relationship keys must compare equal. The report records exact
accessions, package hashes, counts, duration changes, commands, and any cache
or environment limitation without claiming live SEC validation.

The current audit scope recorded before implementation scanned 355 primary
documents, found 2,440 `duryear` uses and 825 input occurrences whose prior
local result differs from this contract, with 26 older MSFT/AMZN package roots
not yet inspected. Observed integer `durmonth` and `durday` cases do not change,
but their fractional helpers were nonconforming and are corrected generically.
These discovery counts define impact evidence, not permission to mutate those
histories.

The writer also compared the exact-Decimal implementation with a direct local
translation of the SEC-staff binary-float functions for every distinct lexical
input in that audit: 350 `duryear`, 27 `durmonth`, and 136 `durday` values.
There were zero output differences, so the deterministic arithmetic choice
does not change any observed cached input relative to the primary runtime.

### Implementation self-test evidence — 2026-10-08

The implementation writer used Python 3.12.13, `arelle-release` 2.44.4,
Polars 1.43.2, pytest 9.1.1, and Ruff 0.16.4. The source taxonomy cache was
copied before parsing and the copy alone was supplied to Arelle in offline
mode. At the time of the copy, the source cache contained 153 files and
42,651,194 bytes; a deterministic relative-path-and-content tree digest was
`8ff9b895b4fdc72f9ae6d7e1525dabcfad4859825eba7368b71c5598503377ae`.

Each package was replayed into a separate fresh temporary v4 snapshot. No
source package, source taxonomy cache, or previous snapshot was a write
destination.

| Filing | Package SHA-256 | Source / materialized Facts | Corrected duration Facts | Gates |
| --- | --- | ---: | ---: | --- |
| AMD `0000002488-23-000076` (10-Q) | `26d36302714a6542e358ff49e4acc656dda3ddfb42481b9266c953bb644f13be` | 742 / 742 | 0 | all three succeeded |
| AMD `0000002488-23-000047` | `019d9c14883d14e9b65ccf3c70de0c8bd79faa827eaf5e6172ff33dfbd9bd182` | 1,378 / 1,378 | 11 | all three succeeded |
| NVIDIA `0001045810-25-000023` | `483c0b2c3c632a19019cbe4574057261938353b01db0edee79625f754afd1dac` | 1,417 / 1,417 | 12 | all three succeeded |
| Deere `0001104659-25-122321` | `8c7d4dfa825bc853a3329a7c5270df941cc1bd5b764f482ecaa00a66fda5e7ba` | 3,236 / 3,236 | 3 | all three succeeded |

The AMD 10-Q was a no-value-change control: all Fact rows were equal and only
the Filing parser provenance advanced. In the AMD annual filing, the confirmed
rows changed `P4Y7M` to `P4Y6M18D` for lexical `4.55`,
`P2Y9M` to `P2Y8M26D` for `2.74`, and `P5Y12M` to `P5Y11M23D` for `5.98`.
Across all four filings, Fact ID sets and every numeric value were equal.
Concept, Context, Unit, dimension-Fact, Role, and Relationship tables were
row-equal to the prior v2/v3 snapshots. No Fact column outside `raw_value` and
`value_text` changed, and the only Filing-table change was `parser_version` to
`m2-layer1-v4`. This demonstrates the intended value/provenance boundary and
zero foreign-type changes for the four cached inputs.

The focused transform test reported 115 passed. The complete offline suite
reported 795 passed and 37 skipped, and repository-wide Ruff reported no
findings. These are writer self-test results for the local candidate, not
independent verification or cohort acceptance. The skipped tests retain their
existing optional/cache/environment semantics; this run did not download a
filing or bootstrap a taxonomy.

### First independent verification finding and corrective candidate

Independent verification of commit
`d3e431301ce15e959d895dc6f67c9618e0fb9d50` returned **FAIL** on one
fail-closed gate while its arithmetic, cached replay, adversarial lexical, and
preservation checks passed. In a temporary copy of AMD
`0000002488-23-000047`, the verifier changed the `duryear` source from `4.55`
to `4.55years`. Arelle exposed `xmlSchema:valueError`, set the target Fact to
`xValid=INVALID`, and returned its `(ixTransformValueError)` sentinel, but the
ingestor published 1,378 Facts and recorded success. That commit is not an
accepted candidate and its result remains preserved as the first verification
record.

The corrective candidate expands only the existing Layer 1
taxonomy/transform validity gate. Before acceptance it forces each selected
Fact value to be evaluated, then rejects:

- the existing taxonomy, reference, and transformation errors;
- `xmlSchema:valueError` and transformation-value error codes;
- any source Fact whose Arelle `xValid` state is `INVALID`;
- Arelle's internal `InvalidValue` transformation sentinel; and
- an exception raised while lazily evaluating a Fact value.

The gate runs again immediately after extraction and before table writes, so a
lazy error cannot become a normal numeric or text Raw Fact. A gate failure
writes one retryable `TAXONOMY_AND_TRANSFORM_RESOLUTION` failure and publishes
no snapshot. It does not treat every Arelle warning as fatal; an ordinary
calculation inconsistency remains permissible model evidence.

The writer reran the verifier's offline mutation with network access denied.
The unknown namespace, unknown transform name, and invalid `4.55years` cases
each produced one retryable taxonomy/transform failure, zero successful state
events, and zero published Parquet tables. The unchanged `4.55` Fact remained
`P4Y6M18D` with `reported_or_derived=REPORTED`. Fresh corrected-gate replays of
the four cached filings again completed at 742/742, 1,378/1,378, 1,417/1,417,
and 3,236/3,236 Facts. The combined focused ingestion/transform tests reported
131 passed; the complete offline suite reported 802 passed and 37 skipped; and
repository-wide Ruff reported no findings. These are corrective writer
self-tests. A new frozen commit still requires a complete independent
read-only verification and `PASS` before cohort reprocessing or acceptance.

### Cohort diagnostic and four supported SEC lexical repairs

The first approved 21-company v4 replay passed AMD and Apple, then stopped on
all 16 Microsoft filings. Each filing reported three `xmlSchema:valueError`
events. Read-only diagnosis of Microsoft accession
`0001564590-22-035087` showed that the gate was working as specified: three
reported `dei:SecurityExchangeName` Facts used `ixt-sec:exchnameen` with source
lexical `Nasdaq`, and Arelle exposed each as `xValid=INVALID` with an
`(ixTransformValueError)` sentinel. The local exchange-name table omitted the
bare `Nasdaq` form even though the SEC-staff `exchnameen` grammar accepts it
and returns `NASDAQ`.

The legacy snapshot inventory then found 104 transformation-error sentinels in
the full cohort. Source inspection and the SEC-staff transform reference showed
that all 104 use supported source lexical forms omitted by the partial local
implementation:

| Transform | Source lexical | Required result | Affected Facts |
| --- | --- | --- | ---: |
| `exchnameen` | bare `Nasdaq` | `NASDAQ` | 48 |
| `stateprovnameen` | `Idaho` | `ID` | 19 |
| `durwordsen` | `three‑year` / `five‑year` with U+2011 | `P3Y` / `P5Y` | 5 |
| `numwordsen` | `nil` | `0` | 32 |

The SEC-staff reference governs these results: its exchange grammar accepts a
bare Nasdaq name; its state/province table maps Idaho to `ID`; its English
duration grammar accepts ASCII and the listed Unicode hyphen characters; and
its English-number zero grammar accepts `nil`, including its case variants and
surrounding XML whitespace. The repair adds only these supported forms to the
existing local transform paths. It does not broaden the state catalog or word
grammar beyond that bounded evidence.

Unsupported exchange, state, English-duration, and English-number lexicals
still raise a transform error and therefore fail the existing Fact-validity
and atomic-publication gates. The repair does not relax
`xmlSchema:valueError`, `xValid`, or sentinel checks and does not change any
numeric-duration arithmetic.

Before implementation the writer scanned all 381 cached primary documents in
the approved cohort source index. It resolved 158,373 formatted Facts across
30 namespace/local transform forms in the SEC and standard 2015, 2020, and
2022 transformation namespaces, with no unknown format QName or namespace.
The old sentinel inventory contained only the four SEC transform cases above;
it contained no standard-namespace transformation sentinel. Nested PCAR
Inline Facts explain why 23 displayed `nil` strings represent 32 distinct
reported Facts and Contexts. The source-bound audit matched all 104 old Fact
ordinals and IDs back to the primary documents with zero missing matches. Of
the 32 PCAR `nil` Facts, three carry `sign="-"` and `scale="6"`; v5 preserves
those source attributes and Arelle's normalized negative-zero spelling rather
than replacing every `nil` occurrence with an invented unsigned literal.

Acceptance covers each supported form, case/XML-whitespace behavior where the
reference allows it, every reference hyphen character used by `durwordsen`,
and unknown-value rejection. At least six fresh offline cached replays cover
Microsoft, Micron, Meta, NVIDIA's 2026 annual filing, a PACCAR filing with
`nil`, and AMD's confirmed `4.55` duration filing. The expected foreign-type
exceptions are limited to the repaired Fact value fields: 48 exchange values
become `NASDAQ`, 19 state values become `ID`, five word-duration values become
XSD durations, and 32 source-bound numeric Facts change from a null/error
sentinel to numeric zero, including three normalized negative-zero values.
Fact identity, source sign and scale, source provenance, Contexts, Units,
dimensions, relationships, and every other Fact field must compare equal. Any
other field or type change blocks acceptance.

The invalid-duration and unknown-transform mutation gates remain required. A
temporary unknown exchange, state, English-duration, or English-number lexical
must likewise fail without a snapshot or success state. The resulting v5
commit supersedes the earlier frozen candidates and requires a new independent
read-only `PASS` before cohort continuation into a fresh
`20261008_sec_transform_v5` history.

### v5 implementation self-test evidence — 2026-10-08

The writer replayed seven cached filings with network access denied and a
private copy of the taxonomy cache. Each replay wrote a separate fresh v5
snapshot and three successful quality-gate states. Source Fact counts equaled
materialized counts:

| Filing | Package SHA-256 | Facts | Supported lexical repairs | Other approved duration changes |
| --- | --- | ---: | ---: | ---: |
| MSFT `0001564590-22-035087` | `bc2fb61221c8f4ed3d768ca9ed06f085a1d8551aac47e3f5c2acf7fa630e1bdd` | 1,191 | 3 | 0 |
| MU `0000723125-22-000004` | `a508e7aa886b55cb27c5fa7d6392b0a3a195c8e423c6c5408b91d237abe7fee7` | 881 | 1 | 0 |
| META `0001326801-23-000013` | `9937d23121deb36538a7b7f05f0e9287c2fe4846236e3a3528b9fb400fdeb2c5` | 1,247 | 1 | 5 |
| NVDA `0001045810-26-000021` | `93baf1f59fe44d113e97f5f0f89d3c6a9fcb4df01f4614e9d73042f54e127906` | 1,305 | 1 | 14 |
| PCAR `0001193125-26-191499` | `2dc502ceaec8f7019f072de8483dc18cfeaaca7998f5d52f4136c9d11970c68d` | 1,453 | 4 | 1 |
| PCAR `0000950170-24-118960` | `5bd229d84415560fe1acefdb1491167fc3ce6b100f214c3b8d1b3e6a23ec2526` | 1,677 | 2 | 1 |
| AMD `0000002488-23-000047` | `019d9c14883d14e9b65ccf3c70de0c8bd79faa827eaf5e6172ff33dfbd9bd182` | 1,378 | 0 | 11 |

The two PACCAR replays include ordinary zero and a source Fact with
`sign="-"` and `scale="6"`; their new numeric/raw values were respectively
`0` and `-0`. Every supported correction matched its source-bound Fact ID.
All other Fact columns were equal except the already-approved duration value
columns, every non-Fact table was row-equal, and the Filing table differed
only in `parser_version=m2-layer1-v5`. Source snapshots, packages, and the
shared taxonomy cache remained unchanged.

Separate temporary package mutations replaced the four supported source forms
with `Mystery Exchange`, `Atlantis`, `three_year`, and `nilly`. Each model
reported `xmlSchema:valueError`; ingestion wrote one retryable failure, zero
success states, and zero Parquet tables.

The focused transform/ingestion suite reported 161 passed. The complete
offline suite reported 832 passed and 37 skipped, repository-wide Ruff passed,
and `git diff --check` reported no errors. These are writer self-test results;
the v5 commit still requires an independent read-only verification result.

After the writer freezes a commit, a separate Astra verifier must perform
read-only independent verification and report `PASS` or `FAIL`. Only after that
result may the lead decide whether to run the approved A/B/C cohort
reprocessing into fresh v5 histories. Push, PR, CI, merge, old-Raw overwrite,
and local acceptance are not part of this writer delivery.

## 7. Assumptions and unresolved cases

- The SEC-staff transform module is the governing runtime reference for this
  SEC namespace; this change does not claim a new Transformation Registry rule.
- Observed SEC numeric-duration lexicals fit the strict ASCII decimal grammar.
  Unsupported lexicals remain explicit validation failures.
- The impact scan covers the 381 cached primary documents in the approved
  cohort source index; it does not infer behavior for an uncached filing.
- This parser correction does not decide whether a duration Fact is a fiscal
  quarter, fiscal year, expected life, or another business period. Context and
  analytical period policy continue to own those meanings.
