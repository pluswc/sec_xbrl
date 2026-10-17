# 50사 generic metric Raw 품질 전달 계약

기준일: **2026-10-17**
현재 상태: **APPROVED / IMPLEMENTED CANDIDATE / INDEPENDENT VERIFICATION PENDING**

## 1. 승인 범위와 주장

사용자는 generic metric identity에 필요한 별도 준비 완료 검증 경로를 승인했고,
리드는 기존 manual dimensional-Q4·legacy `UniverseDelivery`·`source-bindings-v1`
의미를 바꾸지 않는 Raw 품질 하위 마일스톤을 승인했다. 이 구현의 보증 범위는
정확히 `RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY`이며
`full_financial_semantic_assurance=false`다.

PASS는 선택된 cohort의 모든 planned filing에 대해 다음을 증명한다.

- 불변 collection request·manifest, plan, intake, package, primary document,
  Layer 1 snapshot manifest와 Fact/Concept/Context table hash가 연결돼 있다.
- snapshot manifest의 실제 parser version이 알려진 `m2-layer1-v5` 또는
  `m2-layer1-v6` profile과 정확히 일치한다. v5를 v6로 바꾸거나 unknown/self-declared
  profile을 허용하지 않는다.
- SEC `durday`, `durmonth`, `duryear`, `durweek` source와 승인된 lexical repair
  source를 primary document에서 독립 전수 스캔하고 후보 index와 exact 대조한다.
- 각 source는 stable filing/fact/context/concept identity와 Raw 값에 다시 결합되고,
  source 누락 0건·정규화 불일치 0건이다.
- accepted company history는 public READY build marker가 가리키는 exact manifest
  path/hash와 같아야 하고, 그 manifest의 schema·cutoff·plan·intake·dataset hash를 다시
  검사한다.
- `collector_source_commit_sha`는 config가 제공한 회사 단위 선언값이다.
  publication은 이를 `CONFIG_DECLARED_NOT_SOURCE_VERIFIED`로 명시하며, authoritative
  source-run creator 또는 filing별 collector commit을 검증했다고 주장하지 않는다.
  parser profile의 승인 엔진 source commit과도 별개다.

이 PASS는 재무 metric 선택, 기간 의미, mapping, quarter 계산, 회계적 비교 가능성이나
50사 전체 재무 정확성을 주장하지 않는다. 기존 110 numeric Raw 표본 보고서도 이 PASS를
대신하지 않는다.

## 2. wide parent와 명시적 quality cohort

운영은 처음부터 exact-50 공통 immutable collection request·manifest를 만들고 회사별
`selected_tickers` build를 추가한다. quality config의
`collection_scope_companies`는 필수다. 전체 parent와 같으면 `FULL`, 진부분집합이면
`EXPLICIT_SUBSET`으로 저장한다. 생략·빈 범위·중복·parent 밖 회사·암묵적 filtering은
거부한다.

first-five quality는 정확히 그 다섯 회사만 각각 다음 조건을 만족해야 한다.

- public `read_universe_status` 상태가 `READY`
- `selected_filings == held_filings`
- `pending_filings == 0`, `failed_filings == 0`
- config와 accepted history가 exact cohort와 일치

범위 밖 45사의 미완료 상태는 first-five PASS로 승격되지 않는다. publication은 parent
전체 membership/hash와 quality cohort membership/hash를 모두 보존한다. 최종 exact-50
quality는 cohort가 parent 전체와 같고 50사 모두 위 조건을 통과해야 한다.
각 cohort 회사의 검증된 build manifest 경로·SHA-256과 READY count 증거도 publication
identity에 포함하고 reader 재개봉에서 다시 계산한다.
`EXPLICIT_SUBSET`에서는 immutable parent request·manifest와 전체 membership만 전수
검증하고, plan·intake·snapshot·package·source는 선택 cohort만 materialize한다. 따라서
범위 밖 회사가 `PREPARED`이고 intake가 아직 없어도 선택 cohort의 READY 검증을 막지
않으며, 그 회사를 PASS scope에 포함하지도 않는다.

## 3. 공개 입력과 실행

`generic-metric-quality-config-v1`은 다음 필드를 요구한다.

```json
{
  "schema_version": "generic-metric-quality-config-v1",
  "financial_as_of": "2026-10-10",
  "collection_scope_companies": [
    {"ticker": "TXN", "cik": "0000097476"}
  ],
  "source_provenance": [
    {
      "ticker": "TXN",
      "cik": "0000097476",
      "collector_source_commit_sha": "<40-hex company config declaration>",
      "plan_sha256": "<64-hex>",
      "intake_sha256": "<64-hex>",
      "history_manifest_sha256": "<64-hex>"
    }
  ]
}
```

공개 offline entry는 `python -m sec_xbrl.metric_quality`다. 필수 인자는 config,
collection manifest, cached package root, cohort의 반복
`--history-manifest TICKER=PATH`, 세 개의 fresh destination(source index, source
binding v2, quality), producer revision이다. 네트워크와 DB를 사용하지 않는다.

실행 순서는 다음과 같다.

1. `write_source_indexes_v2`가 cached package와 Raw snapshot에서 완전 후보 index를 만든다.
2. `publish_source_bindings_v2`가 후보를 신뢰하지 않고 모든 planned primary document를
   다시 전수 스캔해 exact source set과 Raw table을 결합한다.
3. `publish_generic_metric_quality`가 public collection status, accepted histories,
   v2 reader 재개봉, 모든 normalized value를 검사하고 fresh atomic quality publication을
   만든다. 실패하면 quality destination을 발행하지 않는다.

각 destination은 기존 경로를 덮어쓰지 않는다. 이전 source index나 binding이 성공했고
후속 quality가 실패할 수 있으나, 실패한 quality를 PASS publication으로 만들지는 않는다.

현재 source-binding v2는 선택된 모든 filing package가 하나의 고정 `package_root` 아래
`<cik>/<accession-no-dashes>/<accession>-xbrl.zip`에 있는 view를 요구한다. 여러 cache를
암묵 탐색하거나 복사하지 않는다. 운영 adapter가 별도 view를 만들 때는 authoritative
Layer 1 manifest의 package SHA-256과 전수 대조하고 원본 경로/hash/selection receipt를
보존해야 한다.

## 4. reader와 identity 연결

공개 reader 계약은 다음과 같다.

```python
reader = GenericMetricQualityReader(root, manifest_sha256=expected_sha256)
reader.publication_id
reader.manifest
reader.manifest_path
reader.verify_sources(
    collection_manifest=collection_manifest,
    history_manifest_sha256s=history_hashes,
    financial_as_of="2026-10-10",
    expected_companies=companies,
)
```

constructor는 exact file set, manifest hash, immutable identity와 basic PASS proof를
검증한다. `verify_sources`는 parent collection·cohort·READY-attested history·producer가
전수 스캔해 고정한 complete source index·source binding·cached package hash·Raw tables를
다시 열어 같은 conformance report가 재현되는지 확인한다. reader는 SEC inline 문서를
재파싱하지 않는다. inline 전수 스캔은 offline producer 단계에만 있다.
generic metric identity는 이 publication을 source kind와 함께 pin할 수 있지만,
legacy completion으로 fallback하거나 v1 reader가 v2를 묵시적으로 읽지는 않는다.

## 5. 구현 범위와 수락

변경 범위는 `src/sec_xbrl/source_bindings.py`의 명시적 v2 API,
`src/sec_xbrl/metric_quality.py`, 좁은 합성 test와 이 문서다. consumer dataset,
metric/screening/CLI history, Raw parser, quarter 계산, UI/store/service,
legacy universe delivery gate는 변경하지 않는다.

합성 자체 검증은 mixed v5/v6, full/subset scope, unknown parser, v1/v2 오분류,
외부 cohort 미승격, 범위 밖 pending/missing intake, history 추가/누락 및 같은 회사의
READY-unbound 위조 history, reader inline-parse sentinel, cutoff, Raw normalized-value mismatch,
fresh failure-no-quality-publication을 포함한다. 실제 SEC/재무 payload 실행과 full
financial semantic assurance는 이 후보의 수락 증거가 아니다. 구현 commit을 동결한 뒤
별도 읽기 전용 검증자가 relevant test·Ruff·diff 및 public offline positive path를 다시
실행하고 리드가 결과를 수락하기 전까지 상태는 `INDEPENDENT VERIFICATION PENDING`이다.
