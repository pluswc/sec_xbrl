# 50 issuer 로컬 상태 기록 — 2026-10-13

## 목적과 상태 경계

이 문서는 2026-10-13 KST 현재 50 issuer 연차·분기 전달의 승인 범위, 구현,
독립 검증, 좁은 로컬 인수와 남은 실행 순서를 한 곳에서 연결한다. 기존
[전달 계약](universe-50-quarterly-delivery.md)의 날짜가 있는 후속 상태 기록이며,
새 회계·기간·mapping 정책이나 실행 승인을 만들지 않는다.

현재 결론은 **49개 회사의 complete Raw history input metadata가 준비됐고 PEP 한
회사는 사용자 정책 결정을 기다리며, 전체 financial/history/consumer rollout은 아직
준비되지 않았다**는 것이다. 실행 중인 JNJ 작업의 중간 checkpoint는 최종 상태가
아니다. 이 문서 후보 자체도 별도 읽기 전용 검증과 lead 판단 전에는 문서 전달 후보일
뿐이다.

상태를 다음처럼 분리한다.

| 구분 | 2026-10-13 상태 |
| --- | --- |
| 제안 | 50 unique issuer를 대상으로 한 확장 계획은 승인된 전달 계약 안에서 진행 중이다. |
| 승인 | cutoff, 입력·표시 FY, quarter spine, first-five-before-bulk 순서와 필요한 exact-equivalent 기술 보정이 승인됐다. |
| 구현 | producer `ae856afa8644e08dd1034bd58bb487dc2e80a020`, consumer `39b81464bf4137b162d831eb8646a5a896e65998`에 각 승인 범위가 존재한다. |
| 독립 검증 | 두 source는 source-only PASS다. Raw 5사 artifact와 complete-49 input matrix는 각 좁은 범위에서 독립 PASS다. CAT actual은 이전 2026-10-08 baseline 비교 PASS다. |
| 로컬 인수 | lead가 Raw 5사 artifact와 complete-49 metadata matrix를 그 좁은 범위에서만 수락했다. 전체 JNJ history, first-five financial, actual-50, native U1–U8은 미수락이다. |
| main 병합 | 이 작업의 producer, consumer, actual artifact와 이 문서 후보는 main에 병합되지 않았다. main은 `201acf9aec2f8183acb7dd843579938db14236cd`다. |

## 고정된 대상 계약

- universe는 ticker 행 수가 아니라 **50 unique CIK**다.
- financial cutoff는 **2026-10-10**이다.
- annual producer는 완료 FY **5개를 입력**으로 읽고 최신 **4개 FY만 표시**한다.
  가장 오래된 입력 FY는 첫 표시 FY의 predecessor이며 별도 표시 칸이 아니다.
- quarter publication은 17개 고정 metric과 다음 8개 calendar bucket을 쓴다:
  `2024Q4`, `2025Q1`, `2025Q2`, `2025Q3`, `2025Q4`, `2026Q1`, `2026Q2`,
  `2026Q3`.
- 실제 fiscal context와 52/53-week 신호를 보존한다. calendar bucket은 source fiscal
  의미를 대체하지 않는다.
- 승인된 first five 순서는 TXN, HD, JNJ, CVX, NEE다. first-five financial artifact가
  통과하기 전 bulk financial publication으로 넘어가지 않는다.

## Raw와 complete-49 입력 상태

원래 Raw 경계는 `1d3a068feb74b43145df3abcb506b1285cdf6353`에서 수집한 v5
snapshot이다. UNP, ABBV, ABT, DUK, LIN의 표준 SEC metadata transform 누락은
`4077e87097c294ed779186b613157839f215a63e`의 v6로 보완했다. 다섯 회사의 고정된
110 accession은 새 v6 snapshot 100개와 완전 검증 후 그대로 재사용한 v5 snapshot
10개로 구성된다. 기존 v5 artifact를 v6로 relabel하거나 bulk reparse하지 않았다.

현재 50사 집계는 1,098개 요청 중 1,097개 성공, 1개 실패, 0개 pending이다. 이
1,097개에는 PEP의 성공한 22개 accession도 포함된다. PEP를 제외한 49개 complete
input은 1,075개 unique CIK/accession이며 form 구성은 다음과 같다.

| form | accession 수 |
| --- | ---: |
| 10-K | 245 |
| 10-Q | 822 |
| 10-K/A | 5 |
| 10-Q/A | 3 |
| 합계 | 1,075 |

49개 회사 모두 original plan 기준 완료 10-K baseline 5개를 가진다. 이 결과는
Raw artifact와 입력 metadata의 완전성을 뜻한다. HistoryREADY, 값 정확성, metric,
consumer 또는 50사 financial readiness를 뜻하지 않는다. current status에서
`ready_companies=0`인 이유도 이 downstream gate가 남아 있기 때문이다.

독립 Raw 검증 보고서 `cfb04abf8078e700f25b30599c02996e0f2d36af0f90797775deff1da0482bd1`은
다섯 회사의 110/110, 990 snapshot file, v5/v6 provenance와 immutable prior state를
검증했다. complete-49 matrix 보고서
`d575249f80342b59f5adf836489426f09fff2f073f971c148901097e36db9299`는
위 49개·1,075개·form count와 plan/intake hash를 metadata-only로 검증했다. lead의
수락도 이 두 좁은 범위에 한정된다.

## PEP 정책 hold

PEP는 23개 선택 accession 중 22개가 성공했고
`0000077476-22-000010` 하나가 strict validation에 실패했다. 원인은 custom
`xbrli:timeItemType` Fact 네 개의 transform 없는 month-name text다. 현재 계약은
이를 시간, 문자열 또는 다른 값으로 강제 변환하지 않고 `badTime`으로 fail-closed
유지한다.

다음 중 어느 것도 승인되지 않았다.

- 해당 Fact 또는 filing 삭제
- lexical coercion이나 parser exception
- incomplete 22개만으로 PEP complete 선언
- 다른 issuer로 자동 교체

KDP는 대체 **후보**일 뿐 승인된 replacement가 아니다. PEP를 그대로 처리할지,
명시적 정책을 만들지, universe membership을 바꿀지는 사용자 결정이 필요하다. 그
결정 전에는 50번째 complete Raw input이나 50사 financial readiness를 선언하지 않는다.

## Source와 consumer gate

Producer `ae856af…`는 result-before-final-merge lifetime split, bounded serialization,
v6 Raw compatibility를 포함한다. 독립 보고서
`4c574b6f91519dbe3ee1e7a309706eb0e420666f3bbdf253019d23c61e40e77c`의
판정은 **PASS_SOURCE_ONLY**다. 이 판정은 actual JNJ나 전체 financial artifact를
통과시킨 것이 아니다.

Consumer `39b81464bf4137b162d831eb8646a5a896e65998`의 독립 보고서
`c5ba57d312576d8a92b3e673a7ec958c278331f4806440bef2d30b33fee1ea3e`도
**CONSUMER_SOURCE_ONLY**다. 당시 sandbox에서 실행하지 못했던 exact HTTP 5개는 후속
보고서 `608d6628ac969b99e316eaf1924dc5486a215fb2aee5382402d3bb855936d55b`에서
5/5 PASS했다. 이는 이전 unchanged 377 PASS에 대한 gap closure이며 새 382-test
전체 재실행이 아니다. 두 consumer 보고서 모두 actual first-five/50 financial,
native browser 또는 rollout을 수락하지 않는다.

## CAT와 JNJ 증거의 정확한 범위

CAT actual full golden 보고서
`8388f521668a8a2986ad7ce87d7ad28696cb63b543cae6255bbc41fbb392b93d`는
reported/quarter 61개와 operational 25개 파일의 schema, 순서와 전체 logical value를
비교한 PASS다. 입력은 2026-10-08 accepted CAT baseline이므로 2026-10-10 actual-50
cutoff나 다른 issuer를 수락하는 근거가 아니다.

Source `87d021a…` serializer replay 보고서
`aa29d060a20c99b7951843c5f1379c738ab956c669fdbbf25ec8999985c3a1e2`와
isolated merge 보고서
`65fc25d346c4eb2873c84ce69e0dd65f70df2b20c5e44ec1ef6290a0ee7e1813`는
각각 component evidence다. `65fc…`는 retained 3,065 chunk의 8,160 row를 exact
ordered typed digest로 merge할 수 있음을 보였다. 그러나 후속 light inquiry
`98fc7dde269ceedc6eebf9288c06ed4652f263ec8d436f91b6cb2f04c8350ac9`가
다음 경계를 바로잡았다.

- attempt 3의 3,065 chunk·8,160 row는 **RETAINED_ONLY**다.
- old writer에는 intended count, last-chunk, staging-complete 또는 merge-entry marker가
  없으므로 모든 chunk가 완성됐거나 SIGKILL이 final merge에서 발생했다는 주장은
  입증되지 않았다.
- 따라서 `65fc…` digest는 그 retained 8,160 row에만 유효하고 완전한 JNJ QTD 결과의
  동등성을 증명하지 않는다.

현재 AE 실행의 log는 AS_FILED와 LATEST_REPORTED QTD 각각 8,765 cell을
`PANEL_WRITTEN`으로 기록했다. 이 marker는 해당 table의 columns·rows·cells staging과
finalization이 끝났음을 뜻한다. T1–T4는 attempt 3과 input record, rule, fingerprint,
output count가 같고 manifest 차이는 `published_at`뿐이라는 light inquiry 근거가 있다.
하지만 이 실행의 전체 manifest/hash, public-reader 검증과 old 8,160-row prefix 비교는
아직 완료·수락되지 않았다. 실행 중 checkpoint나 위 두 QTD log만으로 JNJ
HistoryREADY를 선언하지 않는다.

## 남은 실행 순서

다음 순서는 앞 단계의 독립 artifact gate와 lead GO 뒤에만 진행한다.

1. JNJ 전체 history artifact, public-reader 결과와 source scope를 확정한다.
2. 새 AS_FILED QTD의 첫 8,160 ordered raw typed row를 old authenticated digest와
   bounded worker로 비교하고, 전체 8,765 row를 별도로 검증한다. prefix가 다르면
   동등성 주장을 중지하고 첫 차이의 provenance를 조사한다.
3. CVX fresh history와 public-reader gate를 통과한다.
4. governed completion READY, cached metadata와 2026-10-10 cutoff의 exact five annual
   analysis input으로 exact five membership의 `screening-dataset-v1` identity를 만들고
   다음 public chain을 순서대로 검증한다.
   - identity manifest SHA와 annual analysis manifest SHA 5개, `input_years=5`,
     `display_years=4`로 producer `screening-metrics-v1` annual metric publication을
     만들고 governed source를 검증한다.
   - exact identity와 annual metric manifest SHA로 `screening-dataset-v2`를 만든다.
   - exact five QUARTERLY analysis manifest SHA와 annual metric publication의 정확한
     root/manifest SHA를 parent로 `quarterly-screening-metric-manifest-v1` 네 payload를
     만들고 17×8을 검증한다. 이 parent는 annual dataset wrapper나 UI가 아니다.
   - consumer `prepare-v3`가 수락된 annual `screening-dataset-v2`와 quarter metric
     manifest의 exact membership과 parent pin을 결합해 `screening-dataset-v3`를
     만드는지 검증한다.
5. complete 49사로 확대한다. PEP 정책 결정과 complete input이 생기기 전까지
   pending 50번째 회사를 성공으로 포함하지 않는다.
6. actual financial artifact가 통과한 뒤 native U1–U8을 검증한다.
7. 보호된 사용자 journal을 보존한 채 별도 local rollout 판단을 한다.

각 단계는 source 구현, 독립 검증, lead local acceptance를 따로 기록한다. 앞 단계의
PASS는 다음 단계 실행이나 수락을 자동 승인하지 않는다.

## 증거 위치

아래 `work/` 경로는 선택적 provenance locator다. 위 계약과 상태는 이 문서만으로도
이해할 수 있어야 하며, 임시 checkpoint의 현재 phase를 규범 상태로 사용하지 않는다.

| 증거 | 로컬 locator | SHA-256 |
| --- | --- | --- |
| actual 5사 Raw 독립 검증 | `work/universe50_quarterly_20261010/resumption_20261013/independent_actual_raw_v6/report.json` | `cfb04abf8078e700f25b30599c02996e0f2d36af0f90797775deff1da0482bd1` |
| complete-49 input matrix | `work/universe50_quarterly_20261010/resumption_20261013/independent_history_matrix_49/report.json` | `d575249f80342b59f5adf836489426f09fff2f073f971c148901097e36db9299` |
| AE producer source | `work/universe50_quarterly_20261010/resumption_20261013/independent_source_ae856af/report.json` | `4c574b6f91519dbe3ee1e7a309706eb0e420666f3bbdf253019d23c61e40e77c` |
| consumer source | `work/universe50_quarterly_20261010/resumption_20261013/independent_consumer_39b8146/report.json` | `c5ba57d312576d8a92b3e673a7ec958c278331f4806440bef2d30b33fee1ea3e` |
| consumer HTTP gap closure | `work/universe50_quarterly_20261010/resumption_20261013/independent_consumer_http_39b8146/report.json` | `608d6628ac969b99e316eaf1924dc5486a215fb2aee5382402d3bb855936d55b` |
| CAT actual full golden | `work/universe50_quarterly_20261010/resumption_20261013/independent_cat_actual_v2/report.json` | `8388f521668a8a2986ad7ce87d7ad28696cb63b543cae6255bbc41fbb392b93d` |
| source87 serializer replay | `work/universe50_quarterly_20261010/resumption_20261013/independent_source87_actual_replay/report.json` | `aa29d060a20c99b7951843c5f1379c738ab956c669fdbbf25ec8999985c3a1e2` |
| retained-chunk isolated merge | `work/universe50_quarterly_20261010/resumption_20261013/jnj_merge_diagnostic/report.json` | `65fc25d346c4eb2873c84ce69e0dd65f70df2b20c5e44ec1ef6290a0ee7e1813` |
| JNJ count/boundary correction | `work/universe50_quarterly_20261010/resumption_20261013/independent_first5_financial/v2/jnj_qtd_count_inquiry.json` | `98fc7dde269ceedc6eebf9288c06ed4652f263ec8d436f91b6cb2f04c8350ac9` |
