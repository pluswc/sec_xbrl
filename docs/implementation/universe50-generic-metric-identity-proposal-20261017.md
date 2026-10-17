# 50사 generic metric identity attestation 제안 — 2026-10-17

## 상태와 결정 경계

| 항목 | 상태 |
| --- | --- |
| 이 문서 | **PROPOSED** |
| 범위 판단 | 리드 판단 대기 |
| 제품 구현 | 미승인·미구현 |
| 실제 데이터 실행 | 미승인·미실행 |
| 독립 검증·로컬 인수·main 병합 | 미수행 |

이 문서는 확인된 계약 공백과 선택지를 기록하는 제안이다. 구현 승인이나 회계 정책
승인을 뜻하지 않는다.

서로 다른 상태를 다음과 같이 분리한다.

- 기존 21사 native UI의 명시적 저장·다시 열기는 `e84289a…`에서 완료됐다.
- 50사 Raw intake의 exact-50 구성과 수락 증거는 보존한다.
- T3 참조 결함 수리와 재감사 뒤 확장을 재개하는 일은 사용자가 별도로 승인했고,
  현재 수리 중이다.
- 이 문서의 generic metric identity 선택은 위 승인에 포함되지 않는 별도 범위
  판단이다.

T3 수리, tiny PASS, CVX fresh history, pilot 5사의 history와 annual/quarter analysis는
각 단계의 기존 gate를 통과하는 범위에서 독립적으로 계속할 수 있다. 다만 generic
metric identity 확정과 이를 부모로 하는 annual-31, quarterly-17, consumer dataset
v2/v3 전달은 이 제안의 계약을 결정하고 구현·검증하기 전까지 멈춘다.

Raw exact-50 수락은 대상 구성과 Raw intake gate의 수락이다. 제한 표본(기존 110
numeric 확인 포함)의 결과를 50사 전체 회계 의미의 정확성이나 full-semantic `PASS`로
확대 해석하지 않는다.

## 확인된 계약 공백

기존 G4 blueprint는 대략 `history → analysis → completion READY → metric identity →
annual-31 → dataset v2 → quarterly-17 → dataset v3` 순서를 전제한다. 그러나 현재의
public completion 계약에서 `READY`는 수동 검토된 Q4 publication을 요구하고,
generic quarter 생산자는 history quarter와 quarterly metric을 만든다. 두 산출물은
같은 증거 종류가 아니다.

따라서 현재 authoritative first-5 입력만으로는 legacy completion `READY`를 정직하게
만들 수 없다. 빈 reviewed-Q4, 다른 회사의 reviewed-Q4, 또는 generic quarter를
reviewed-Q4로 다시 이름 붙이는 방식은 계약을 위반한다. 원래 G4 경로는 현재
그대로 실행할 수 없으며, identity를 표현하는 추가 계약과 제품 코드가 필요하다.

## 확인된 소스 근거

| 단계 | 파일·함수 | 확인된 의미 |
| --- | --- | --- |
| legacy completion 발행 | `src/sec_xbrl/universe_delivery.py`의 `publish_universe_delivery` | quarterly analysis가 있으면 reviewed-Q4 publication을 요구한다. |
| reviewed-Q4 범위 검증 | 같은 파일의 `_validate_q4_scope` | 허용 회사와 Q4 scope를 엄격히 검증한다. foreign ticker나 다른 scope를 대체 입력으로 쓸 수 없다. |
| analysis 부모 검증 | 같은 파일의 `_validate_c_analysis_links` | analysis가 지정된 reviewed-Q4/history 부모에 연결됐는지 검증한다. |
| legacy readiness 판정 | 같은 파일의 `_readiness_model` | `q4_ready`를 포함한 legacy 조건이 충족돼야 `READY`다. |
| consumer dataset gate | `src/sec_xbrl/screening/dataset.py`의 accuracy 검사와 `_ready_completion_company` | completion `READY`와 accuracy assessment `PASS`를 모두 요구한다. |
| 수동 reviewed-Q4 | `src/sec_xbrl/analytics/reviewed_q4.py` | 특정 검토 결정을 담는 전문 publication이며 generic quarter 증거가 아니다. |
| generic quarter 생산 | `src/sec_xbrl/analytics/history_quarters.py`, `src/sec_xbrl/metrics/quarterly_screening.py` | 회사 이력의 quarter와 governed quarterly metric을 생산한다. manual reviewed-Q4를 생산하지 않는다. |

확인된 기존 reviewed-Q4 manifest 둘은 2026-10-08에 만들어졌고 기준일은
2026-09-06이며 NVDA 한 회사의 16 economic/32 view record 범위다. first-5 또는
exact-50 generic identity 입력으로 재사용할 수 없다. authoritative first-5 입력에는
동일 범위의 reviewed-Q4 publication과 ledger가 없다.

## 권장안: additive generic metric identity attestation

새로운 `generic-metric-identity-attestation-v1`을 추가하고, consumer 입력의 source kind를
명시적으로 다음 둘 중 하나로 고정하는 방식을 권장한다.

1. `LEGACY_UNIVERSE_DELIVERY`: 기존 `UniverseDeliveryReader.READY`, manual
   reviewed-Q4, 기존 accuracy gate를 그대로 사용한다.
2. `GENERIC_METRIC_IDENTITY_ATTESTATION`: generic history/analysis/metric의 정확한
   부모와 범위를 증명하는 새 attestation 및 accuracy `PASS`를 사용한다.

source kind는 설정과 저장 manifest에 명시하고, 파일 모양이나 경로로 추론하지 않는다.
두 종류 사이의 fallback, 혼합, 자동 승격을 허용하지 않는다. 기존 legacy
`UniverseDelivery`의 `READY`, reviewed-Q4 의미, validation은 변경하지 않는다.

### 새 attestation의 필수 입력

- 대상 universe의 exact membership, CIK/ticker identity, financial cutoff
  `2026-10-10`
- collection operation의 회사별 `READY`, `selected == held`, pending/failed 없음과
  그 operation identity
- authoritative Raw intake와 metadata identity; Raw payload 자체를 복제하거나
  다시 해석하지 않음
- 같은 범위에 대한 기존 accuracy assessment 계약 수준의 `PASS`: assessment schema와
  rule version, exact company membership, 기간·cutoff, 표본/검사 범위, 판정 결과,
  source binding, 재현 가능한 입력 manifest·hash와 assessment artifact identity
- 회사별 accepted history identity와 parent hash
- 회사별 annual analysis identity와 고정된 history parent
- 회사별 quarterly analysis/metric identity와 고정된 quarter evidence parent
- annual은 입력 5 FY·표시 4 FY, quarterly는 최근 8 calendar bucket
  `2024Q4–2026Q3`이라는 동일 범위 증명
- 사용한 canonical/rule/schema version, unavailable 상태와 그 이유의 보존
- 위 입력과 source kind를 hash로 고정한 불변 attestation identity

accuracy `PASS`는 선택 사항이 아니다. 기존 assessment/source-binding 계약이 요구하는
재현 가능 입력과 범위가 모두 있어야 한다. assessment 범위가 attestation의 universe,
기간, metric identity와 다르거나 필수 자료가 없으면 identity 단계는 `BLOCKED`이며
발행을 거부한다. Raw intake의 제한 표본 수락을 이 `PASS`로 승격하지 않는다.

## 선택지와 범위 판단

### A. 별도 attestation 추가 — 권장

legacy completion과 회계 의미를 보존하면서 generic producer의 실제 증거를 명시적
dataset identity 부모로 쓴다. source kind별 reader와 negative validation이 추가로
필요하지만, 두 경로의 의미가 가장 분명하다.

### B. `UniverseDelivery`에 generic readiness profile 추가

하나의 public completion API를 유지할 수 있으나, `READY`가 manual reviewed-Q4와
generic metric 두 뜻을 갖게 된다. profile discriminator, 저장 schema, 모든 consumer
검증을 함께 바꾸지 않으면 오분류 위험이 크므로 권장하지 않는다.

### C. first-5에 manual reviewed-Q4 절차 수행

이는 metric identity 보완이 아니라 별도의 회계 검토 범위다. 리드가 회사별 manual
review 정책과 입력을 승인하기 전에는 선택할 수 없고, 이 제안은 그러한 승인을
만들어 내거나 추정하지 않는다.

어느 선택지에서도 빈 reviewed-Q4 생성, NVDA publication 재사용, generic quarter의
manual reviewed-Q4 재분류, accuracy `PASS` 생략, reader의 `READY` 검사 우회는 허용하지
않는다.

## 제안 구현 allowlist

다음 목록은 선택지 A가 승인될 경우에만 적용할 구현 후보이며 현재 승인된 작업이
아니다.

- 새 `src/sec_xbrl/screening/metric_identity.py`: attestation schema, reader,
  validator, immutable identity 계산
- `src/sec_xbrl/screening/dataset.py`: 명시적 source kind와 source별 strict validator
- 필요할 경우 `src/sec_xbrl/screening/cli.py`: source kind와 attestation 경로를
  명시적으로 받는 public entry
- `src/sec_xbrl/metrics/screening.py`: exact identity/source version 연결 검증만 추가
- 대응 unit/integration negative test, fixture manifest, 계약·운영 문서

다음은 이 범위에서 변경하지 않는다.

- Raw parser, accession discovery, period 규칙, metric 산식과 accounting policy
- `reviewed_q4.py`와 legacy `UniverseDelivery` gate의 완화
- consumer dataset v3, service, native UI에서의 계산 또는 암묵적 보정
- 기존 publication, catalog, export, user journal의 migration·삭제·재작성
- 실제 SEC/network 수집과 기존 데이터 삭제

## 제안 수락 조건

1. 기존 21사 legacy completion과 native UI 저장·다시 열기 회귀가 동일 identity로
   통과한다.
2. 새 attestation은 위 필수 입력 전부와 exact universe/기간/부모 hash를 검증하고,
   하나라도 없거나 다르면 발행하지 않는다.
3. `LEGACY_UNIVERSE_DELIVERY`와 `GENERIC_METRIC_IDENTITY_ATTESTATION`의 상호 오분류,
   fallback, 혼합을 negative test로 거부한다.
4. accuracy가 `PASS`가 아니거나 다른 범위를 가리키거나 기존 계약의 재현 가능한
   입력/source binding이 없으면 상태는 `BLOCKED`이고 dataset build를 거부한다.
5. 저장 후 다시 연 consumer는 manifest의 source kind와 attestation identity를 다시
   검증한다.
6. annual-31과 quarterly-17 publication은 정확한 attestation parent를 기록하고,
   dataset v2/v3가 그 identity를 보존한다.
7. Raw, legacy reviewed-Q4/completion gate, 기존 publication/catalog/export와 user
   journal이 변경되지 않았음을 회귀 증거로 남긴다. 정상 manual dimensional-Q4
   gate는 어떤 경로에서도 약화하지 않는다.
8. 실제 first-5 실행 전에 별도 독립 검증자가 계약·negative test·fresh fixture를
   검증하고, 리드가 범위와 회계 의미를 수락한다.

## 다음 결정

리드는 A/B/C 가운데 범위를 선택하거나 보류해야 한다. 선택지 A를 승인하더라도 먼저
계약·테스트 구현과 독립 검증을 완료한 뒤 fresh first-5 identity를 만들 수 있다.
이 문서만으로 구현, 데이터 발행, manual Q4 검토 또는 `READY` 판정을 승인하지 않는다.
