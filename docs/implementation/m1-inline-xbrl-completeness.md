# M1-IX — Inline XBRL complete Layer 1 ingestion

## Purpose

Make a resolved SEC Inline XBRL package a trustworthy, immutable Layer 1
snapshot.  This milestone corrects a systemic failure mode in which Arelle's
small `factsInInstance` collection was treated as a complete filing although
the model-wide Inline corpus was available in `model.facts`.

It is not an Excel or company-specific milestone.  No metric, canonical
mapping, period classification, or recast decision is made here.

## Raw Layer 1 collection scope / Raw Layer 1 수집 범위

### Included / 포함

For a resolved filing, Raw Layer 1 ingests **every top-level reported Fact**
available in the validated Arelle `model.facts` corpus. This is a filing-wide
preservation rule, not a financial-statement filter. It includes numeric,
text, nil, and DEI Facts; Facts in each of the four primary financial
statements; and every tagged Fact in notes and other disclosures. Each Fact
keeps its Context, Unit where applicable, all explicit or typed dimensions,
source document/locator, and QName-aware concept identity. The same filing
snapshot also preserves PRE, CAL, and DEF role relationships.

해결된 공시에 대해 Raw Layer 1은 검증된 Arelle `model.facts` corpus에
존재하는 **모든 최상위 보고 Fact**를 적재한다. 이는 재무제표만 선택하는
필터가 아니라 filing 전체를 보존하는 규칙이다. 수치·텍스트·nil·DEI Fact,
4개 주요 재무제표의 Fact, 주석 및 기타 공시에서 태그된 모든 Fact를
포함한다. 각 Fact에는 Context, 해당 시 Unit, 모든 explicit/typed dimension,
원천 문서·위치, QName 기반 concept identity를 보존한다. 같은 filing
snapshot에는 PRE·CAL·DEF role relationship도 보존한다.

### Excluded / 제외

Tuple containers are structural containers, not top-level reported Facts, and
are excluded from the Raw Fact count. Untagged HTML narrative is not a Fact
and is outside this Fact-ingestion boundary. Canonical mapping, period or
comparative classification, recast selection, derived values/metrics, and
statement/note selection are later-layer responsibilities; they are never
created by Raw ingestion.

Tuple container는 구조적 container일 뿐 최상위 보고 Fact가 아니므로 Raw
Fact count에서 제외한다. 태그되지 않은 HTML narrative는 Fact가 아니며 이
Fact 적재 경계 밖이다. Canonical mapping, 기간·비교기간 분류, recast 선택,
derived value/metric, 재무제표·주석 선택은 모두 후속 Layer의 책임이며 Raw
적재 단계에서 생성하지 않는다.

### Downstream responsibility / 후속 처리 책임

The four-statement and note/disclosure views are built later by analytical
traversal and filtering over the complete Raw snapshot. They must not be used
as an ingestion-time filter, because doing so would discard as-filed evidence
that may be material to a later question.

4개 재무제표 및 주석·공시 view는 완전한 Raw snapshot을 대상으로 후속
analytical traversal과 filter가 구성한다. 이들은 적재 시점 filter가 되어서는
안 된다. 그렇지 않으면 이후 분석 질문에 중요한 as-filed evidence를 버릴 수
있기 때문이다.

### Completeness and fail-closed meaning / 완전성 및 fail-closed 의미

A successful snapshot means the validated top-level source corpus and the
materialized Raw Fact count are equal after only the declared tuple-container
exclusion, and all required Fact/Context/Unit/dimension/relationship tables
are atomically published from the same filing/model. It does **not** mean that
every Fact is analytically selected or comparable. Fail-closed means no
successful snapshot is published if this preservation contract cannot be
proven; an accession-level retryable parse-state records the failure instead.

성공 snapshot은 선언된 tuple-container 제외 외에는 검증된 최상위 source
corpus와 materialized Raw Fact count가 같고, 필수 Fact·Context·Unit·dimension·
relationship table이 동일 filing/model에서 원자적으로 발행되었음을 뜻한다.
이는 모든 Fact가 분석상 선택 가능하거나 비교 가능하다는 뜻은 아니다.
Fail-closed는 이 보존 계약을 증명할 수 없으면 성공 snapshot을 발행하지 않고,
대신 accession 단위의 재시도 가능한 parse-state에 실패를 남긴다는 뜻이다.

## Expected-result contract

For every successfully materialized filing:

1. The top-level reported Fact corpus is `model.facts` when that collection is
   present. `factsInInstance` is only a compatibility fallback when
   `model.facts` is absent. If both collections disagree, ingestion fails.
2. The snapshot contains all six raw Layer 1 tables plus `role` and
   `relationship`, generated from the same validated Arelle model.
3. `layer1_manifest.json` records source package SHA-256, Fact corpus source
   and count, materialized counts, and parser versions.
   The validated top-level source Fact count must equal the materialized Fact
   count; any extractor omission fails rather than producing a partial view.
4. A taxonomy-resolution, schema-reference, or Inline transformation error,
   or a Fact without a resolved concept, prevents all Snapshot output.
5. A published snapshot is never overwritten. A retry must use a new parser
   version/output location or leave the existing immutable snapshot untouched.
6. Every load, validation, or materialization result produces an append-only
   parse-state JSON event outside the snapshot, keyed by CIK/accession/parser
   version. It records `ARELLE_LOAD`, `VALIDATION`, or `LAYER1_EXTRACT`, its
   outcome, retryability, and failure message. Failed attempts therefore leave
   no snapshot but remain observable and retryable.

## M0 quality-gate evidence

Each parse-state event records the M0 gate name, expected/actual counts where
applicable, `m1-inline-xbrl-completeness-v1` validation-rule version, source
identifiers, and timestamp. A successful publication records all three Layer 1
gates:

| Gate | Expected / actual | Success condition |
| --- | --- | --- |
| `TAXONOMY_AND_TRANSFORM_RESOLUTION` | Not a count gate | Every selected Fact has a resolved concept and Arelle has no taxonomy/reference/Inline transform failure. |
| `RAW_CORPUS_COMPLETENESS` | top-level `model.facts` count / materialized Fact count | Exact equality after declared tuple exclusion. |
| `ATOMIC_FILING_SNAPSHOT` | 8 required tables / 8 published tables | Fact, Context, Unit, Dimension, Concept, Filing, Role, and Relationship tables plus their manifest are published by one atomic rename. |

On failure the corresponding event is `FAILED` and retryable; no accession
snapshot directory is published.

These conditions are generic. They do not rely on NVIDIA labels, accession
numbers, or numerical values.

## Taxonomy cache policy

Normal `ArelleFilingLoader` loads with network disabled.  Pass a local
`taxonomy_cache=Path(...)` containing the needed US-GAAP/DEI/SRT and other
taxonomy resources for reproducible offline parsing.

For an explicit, controlled bootstrap in a network-enabled environment use:

```python
model = ArelleFilingLoader.bootstrap_taxonomy_cache(
    resolved_filing,
    destination=Path("/secure/work/extracted/accession"),
    taxonomy_cache=Path("/secure/cache/arelle-taxonomies"),
)
```

The bootstrap is opt-in and must be followed by an offline reload and the
same Layer 1 validation before a production snapshot is trusted. The project
does not commit the resulting third-party taxonomy cache or SEC packages.

### SEC Inline transformation runtime

`arelle-release` supplies XBRL Transformation Registry versions 1–5 but does
not register the SEC EFM `http://www.sec.gov/inlineXBRL/transformation/2015-08-31`
namespace. `ArelleFilingLoader` therefore registers the supported SEC EFM
transform functions before every bootstrap and offline load. This is a parser
runtime dependency rather than a taxonomy-cache artifact. Unsupported SEC
transform names still fail closed; registration does not suppress validation.

## Validation procedure

Unit tests create an Inline-like model where `model.facts` has two reported
facts while `factsInInstance` has one. A successful snapshot must contain two
facts and a manifest declaring `model.facts`; taxonomy/transform failures and
unresolved concepts must create no directory. A deliberately partial extractor
is rejected when its output count differs from the validated source corpus;
the corresponding parse-state event is `LAYER1_EXTRACT` / `FAILED`.

A separate dependency-free contract fixture represents a standard revenue Fact
with an explicit geography Axis/Member and a DEF relation. It must publish one
dimensional Fact assignment and one relationship in the same snapshot. This is
the offline M1 success proof; it exercises the generic path without claiming a
network bootstrap or a company-specific cached taxonomy result.

## Evidence classes

The deterministic unit fixture is a code-contract check only: it proves the
complete corpus, dimensional Fact, relationship, atomic-snapshot, and
fail-closed paths without network access. It is not evidence that a real SEC
taxonomy package resolved.

Real-ticker integration evidence is kept outside Git and records, for NVDA,
AAPL, and AMZN, one selected accession, package hash, taxonomy-cache identity,
`model.facts` and materialized Fact counts, quality-gate outcomes, and whether
a snapshot was published. Each ticker therefore has a deterministic observed
outcome: complete `SUCCESS` or a retryable, provenance-preserving
fail-closed state. M1 release evidence requires at least one real SEC filing
to reach complete `SUCCESS`; a restricted environment that cannot bootstrap a
taxonomy cache records its limitation rather than turning a partial corpus into
a success claim.

For a cached real filing, execute the following after the standard taxonomy
cache has been explicitly bootstrapped:

1. load the package offline with `ArelleFilingLoader(taxonomy_cache=...)`;
2. call `Layer1Ingestor.load_and_ingest(...)`;
3. compare `layer1_manifest.json.materialized_fact_count` with the non-tuple
   `model.facts` count;
4. query `concept.parquet` and `dimension_fact.parquet` using QName/axis/member
   rather than display labels.

For NVIDIA FY2026 Q3 this procedure is expected to make standard Revenue
Facts and geographic dimensional Revenue Facts queryable only when the
required standard taxonomy resources resolve. Without that cache, the correct
result is an explicit ingestion failure rather than a partial 52-Fact snapshot.

## Baseline evidence and current behaviour

The cached NVIDIA FY2026 Q3 package (`0001045810-25-000230`) demonstrated the
generic failure mode: Arelle exposed 52 `factsInInstance` facts and 1,060
`model.facts` facts. Before M1-IX, the 52-row collection could be saved as if
it were complete. With M1-IX, the same offline load is rejected because it
reports `IOerror`, `missingReferences`, and `invalidTransformation`; no Layer
1 snapshot directory is created.

An attempted bootstrap needs network access to the standard taxonomy hosts.
In the restricted development environment that request returned
`FileNotLoadable`, leaving 1,008 unresolved concepts; this too is rejected.
The automated bootstrap API remains the reproducible resolution path for a
network-enabled controlled environment, followed by an offline verification
run using the populated cache.
