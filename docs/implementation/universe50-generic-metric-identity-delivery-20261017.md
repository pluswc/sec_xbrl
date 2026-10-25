# 50사 generic metric identity 전달 계약 — 2026-10-17

## 결정과 상태

2026-10-17 사용자는
[제안서](universe50-generic-metric-identity-proposal-20261017.md)의 권장안 A,
즉 기존 manual dimensional-Q4 completion과 분리된
`generic-metric-identity-attestation-v1` 경로를 명시적으로 승인했다. 승인 원문 증거는
로컬 운영 기록
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/generic_metric_identity_user_approval.json`
(SHA-256 `1c03f014a692e3e54c5596c2d4e5dfacbc7e3a23e36372d8648514f9c23b3bb6`)에
보존한다. 제안서는 당시 `PROPOSED` 상태 기록으로 수정하지 않는다.

| 단계 | 현재 상태 |
| --- | --- |
| 범위 승인 | **APPROVED** — 권장안 A의 로컬 코드·합성 fresh fixture 구현 |
| generic identity 구현 | final `6470e0b8dc30f8df3c2229e511fae79195530f4b` |
| mixed v5/v6 Raw/Quality producer | `c70087dccd6337268110417da11c11298ddae303`; 독립 PASS와 리드 source/synthetic 로컬 수락 완료 |
| actual first-five/50사 발행 | **NOT_READY / 미승인** |
| 독립 검증 | quality `c70087d`와 identity `6470e0b` 모두 **PASS** |
| 로컬 인수 | quality·identity source/synthetic 수락; actual 인수 미수행 |
| push·PR·main 병합 | 미수행 |

구현 존재, 독립 검증, 리드의 로컬 인수와 main 병합을 서로 대신 쓰지 않는다.

## 구현 범위와 관계

새 identity는 명시적 source kind
`GENERIC_METRIC_IDENTITY_ATTESTATION`으로만 열린다. annual metric config v2는 identity
source kind, root와 manifest SHA-256을 모두 명시한다. legacy config v1과 기존
`ScreeningDatasetReader` publication은 기존 경로로 계속 열리며, 파일 모양·경로를 보고
새 경로로 추론하거나 두 경로 사이에서 fallback하지 않는다.

의존 순서는 다음과 같다.

`generic identity → annual metrics 31 → annual dataset v2 → quarterly metrics 17 → dataset v3`

identity는 collection, metadata, Raw/Quality, 회사별 history, annual analysis와 quarterly
analysis까지만 부모로 고정한다. quarterly metric은 identity의 입력이 아니다. 기존
quarterly producer는 annual metric을 부모로 두므로 이 구조에는 의존 순환이 없다.

운영 parent는 처음부터 exact-50 immutable collection request/manifest다. first-five gate는
`collection_scope_mode=EXPLICIT_SUBSET`과 5개 CIK/ticker를 config에 명시해 parent
membership의 진부분집합임을 증명한다. parent 50 membership/hash는 고정하지만 범위 밖
45사의 가변 build 상태를 first-five 완료로 주장하거나 identity에 섞지 않는다. 선택된
5사의 build marker/history hash를 별도로 고정하므로 나머지 45사 진행은 first-five
identity를 바꾸지 않는다. 최종 50사 발행은 `FULL` mode에서만 가능하며 50개 회사 전부의
동일 gate를 요구한다. implicit filtering이나 fallback은 없다.

## 필수 입력과 fail-closed 조건

identity producer와 reader는 발행 때와 다시 열 때 다음을 모두 검증한다.

- config에 exact universe ID, scoped CIK/ticker membership, financial cutoff, 별도
  `metadata_observation_cutoff`, collection scope mode와 source kind가 있다.
- `read_universe_status`가 같은 collection manifest를 다시 검증한다. scoped 회사는 모두
  `READY`, `selected == held`, pending/failed 0이다. `SOURCE_READY`와 같은 단일 boolean은
  사용하지 않는다. `FULL`은 parent membership 전체가 scoped membership과 같아야 한다.
- metadata publication identity와 hash가 일치하고 각 scoped CIK/ticker 관찰 timestamp가
  timezone offset을 포함한 ISO 8601 형식이며 명시한 `metadata_observation_cutoff` 이후가
  아니다. `financial_as_of`를 metadata 관측 기준으로 암묵 재사용하지 않는다.
- 회사별 collection build가 가리키는 history root, build marker hash와 history manifest
  hash가 config와 같고 history reader가 선언한 모든 파일을 검증한다.
- annual analysis는 exact history 부모, `ANNUAL`, 5개 입력 FY, latest 4개 표시 FY와
  `annual-exact-year-end-instant-v1`을 고정한다.
- quarterly analysis는 exact history 부모, `QUARTERLY`, 선언된 data file 전부와
  `quarter-typed-primary-pre-evidence-v1`을 고정한다. 최근 8개 완료 calendar bucket은
  cutoff로 결정한 `2024Q4–2026Q3`이다.
- 별도 `GenericMetricQualityReader`가 exact collection/history/scoped company/cutoff와
  실제 filing별 parser v5/v6, parser/rule/source bytes, source binding과 재현 증거를 확인한
  `PASS`여야 한다. 보증 범위는 `RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY`이고
  full financial semantic assurance를 주장하지 않는다. 회사 단위
  `collector_source_commit_sha`는 `CONFIG_DECLARED_NOT_SOURCE_VERIFIED` 선언값으로만
  보존하며 filing별 authoritative creator 검증으로 해석하지 않는다.
- config, 모든 root, manifest SHA-256, declared data-file hash, publication ID와 rule/version을
  최종 identity에 고정한다. 어느 하나라도 없어지거나 바뀌면 발행·재열기를 거부한다.

quality publication은 기존 duration 및 supported-lexical transform source-conformance와
동등한 강도의 별도 additive producer가 담당한다. legacy
`UniverseDelivery`, `SourceBindingsReader` v1과 parser version 상수는 변경하지 않는다.
Raw exact-50 수락, 110 numeric 표본, source-only shape 검사를 quality `PASS`나 재무 의미
전체 `PASS`로 승격하지 않는다.

`financial_as_of=2026-10-10`과 current metadata 관측일 2026-10-13은 서로 다른
시간축이다. 별도 metadata cutoff 결정은 로컬 운영 기록
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_metadata_observation_decision.json`
(SHA-256 `3aeb08f12d31b05e3ca744f789c1fbcd3e513707bcfbd185f3f20e0ed1507385`)에
보존한다. identity는 config, top-level scope와 metadata block에 정규화된 cutoff와 각
scoped 관측 timestamp를 고정하고 `historical_membership_assurance=false`를 명시한다.
이 current metadata pin은 2026-10-10 당시 universe membership을 역사적으로 증명하지
않는다.

## 허용 변경과 금지 범위

허용 파일은 `screening/metric_identity.py`, 명시 source-kind 연결을 위한
`screening/dataset.py`, `screening/dataset_v2.py`, `screening/cli.py`,
`metrics/screening.py`, 좁은 합성 unit/integration tests와 이 계약·등록부다. annual dataset
wrapper의 명시 identity 설정은 독립 schema `screening-prepare-config-v2-identity-v1`을
사용하고 기존 combined dataset v3 schema는 그대로 둔다. mixed v5/v6 quality producer는
별도 전달 계약과 단일 작성자 범위에서만 변경한다.

다음은 이 identity 변경에서 수정하지 않는다.

- `universe_delivery.py`, `reviewed_q4.py`, 기존 source-binding v1 validator
- Raw parser, history/analysis/quarter 계산 정책, UI/store/service와 journal
- 기존 v1/v2/v3 publication, 21사 native UI와 e842 저장·재열기 산출물
- actual SEC/network, bulk regeneration, DB와 live UI

## 수락과 재현

동결 후보는 narrow unit/integration negative tests, 기존 screening regression, Ruff와
diff 검사를 통과해야 한다. 최소 negative 범위는 다른 CIK/ticker/cutoff, future filing,
collection 미완료, stale config, parent/cohort 혼합, history/analysis/quality parent hash 변경,
malformed quality proof, source-kind 혼합·fallback과 재열기 후 외부 파일 변경이다.

별도 Astra 읽기 전용 검증자는 동결된 identity와 quality 커밋을 정상 통합한 동일 SHA에서
위 계약, fresh synthetic publication과 회귀를 독립 실행했다. identity `6470e0b`는 PASS와
source/synthetic 로컬 수락을 받았다. 이 결과만으로 actual first-five/50사 identity와
annual/quarterly dataset은 준비 완료가 되지 않는다.

quality `c70087dccd6337268110417da11c11298ddae303`의 독립 PASS 증거는 로컬
`independent_quality_c70087d/report.json`(SHA-256
`0fd0942aacf75a52a85462fabfd662a28e89c8873391783f2ddf2cfa7253c3c1`)이고, 리드의
source/synthetic 로컬 수락은 `lead_quality_source_and_synthetic_acceptance.json`
(SHA-256 `9558b7c0d577ab41c1c2e9b5cb714afb2cfb8f668c5cb9c67f19608bf20cfaef`)이다.
두 파일은 위 `resumption_20261017_t3v2` 작업 디렉터리에 있다. 이 증거는 actual
financial payload 또는 actual first-five/50 발행을 대신하지 않는다.

identity `6470e0b`의 독립 PASS 증거는 같은 작업 디렉터리의
`independent_identity_6470e0b/report.json`(SHA-256
`9c27d0b20e744bfeea7719a15036d33d7ef0f5c3923ac151fc63dd291809e22f`)이고,
리드의 source/synthetic 로컬 수락은
`lead_identity_source_and_synthetic_acceptance.json`(SHA-256
`0ad31a482176329222dcad631c71145dcbe491fe89766b39bbdb28eca80e0ff8`)이다.
