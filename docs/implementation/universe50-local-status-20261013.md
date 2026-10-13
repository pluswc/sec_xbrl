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

## 2026-10-13 후속 기술 수리 — bounded verification / complete-stage recovery

위 실행 중 상태의 후속 정정: JNJ attempt 4는 22개 공시에서 reported 12 panel /
36 file / 965,078,742 byte와 staged manifest가 존재하고 rename은 없는 상태에서
SIGKILL 137로 실패했다. 검증 단계의 메모리 실패라는 위치·원인 설명은 프로그램
control-flow와 자원 기록에 근거한 강한 추론이며 traced stack 또는 kernel OOM
확인 결과가 아니다. 실행 시간 1:45:46, max RSS 31,017,632 KiB(약 29.58 GiB)이며 HistoryREADY나
FINANCIAL_READY가 아니다. 파일 hash 확인은 전체 decoded integrity를 대신하지
않는다. 이전 실패 기록과 partial bytes는 보존한다.

반복된 실제 메모리 실패를 근거로 lead는 이번 제한된 구현 역할을 Astra로
상향하고 별도의 Astra 독립 검증 역할을 유지했다. 대상은 history reader의 전체
무결성 검증 메모리, build/quarter 저장 단계의 객체 수명, 독립적으로 complete
attestation을 받은 reported stage의 새 root 복구뿐이다. parser/Raw/회계/기간/
파생 계산/스크리닝/UI 정책 변경, main·원격·OPS·journal 변경은 승인하지 않았다.

[회사 history 계약](company-history-workflow.md#complete-reported-stage-recovery-2026-10-13-technical-exception)에
예외 경계와 public API/CLI, 외부 pinned attestation, exact inventory/schema/log 및
Raw/T1–T4 검증, 원본 바이트 보존·새 transaction cleanup 규칙을 기록한다.
JNJ의 12/36은 해당 실행 inventory이고 범용 코드의 ticker/기간 hard-code가 아니다.
PEP 정책 hold와 incomplete Raw/chunk는 이 예외로 복구할 수 없다.

현재 상태는 **IMPLEMENTED / 자체 검증 PASS / 독립 source 검증·actual recovery·
local acceptance 미수행**이다. 두 공시 cached golden은 lead가 명시적으로 승인한
별도 2 GiB process-group RSS guard·300초 timeout·Polars 2-thread 조건으로 수행했다.
실제 component audit의 8 GiB reservation과 합산한 제한된 병행 예외이며 임의의
추가 cached/실자료 실행 승인이 아니다. frozen source의 독립 PASS와
actual complete-stage attestation 및 lead GO 이전에 attempt 5/CVX를 실행하거나
49/50 financial 완료를 선언하지 않는다.


### 수리 후보 자체 검증 (독립 인수와 구분)

- 관련 unit 149 passed: history workflow/recovery/quarter 및 기존 quarter policy,
  coverage, pivot, derived tests. 새로운 검사는 전체 JSON late failure, hash/count
  우선순위, symlink/unsafe path, exact report/prefix/scope gate, 실패 cleanup,
  원본 immutable bytes와 graph/period/ledger/source-result의 weakref 수명을 포함한다.
- 정확히 NVDA cached 2 filings의 기존 integration을 확장: fresh build와 public
  recovery의 전체 typed record/order/derived records 및 Raw/T1–T4 fingerprint,
  실제 source parent, reported manifest/payload bytes, recovery receipt가 일치했다.
  **1 passed / 14.93초**, 외부 guard 전체 15.12초, 50 ms sampling process-group peak
  **373,391,360 bytes**, 2 GiB/300초 cutoff 미도달. 테스트용 증거는 `CACHED_TEST`로
  표시하며 actual JNJ의 독립 attestation을 대신하지 않는다.
- 같은 작은 cached output에 이전 `a36ea059…` history eager reader와 quarter
  producer를 oracle로 적용: **8 tables / 25 files / 4,686 panel records / 42 derived
  records PASS**. 전체 physical schemas, encoded/decoded ordered values, table
  metadata와 파일 hashes가 일치했다. 4.48초, guard peak **228,536,320 bytes**.
- Ruff와 `git diff --check` PASS. 전체 1,315개 이상 suite 재실행이나 실제 JNJ
  recovery는 이 결과에 포함하지 않는다. 최초 cached 비교의 실패는 테스트가
  null parent locator까지 path로 바꾼 assertion 오류였고, non-null 실제 parent만
  새 경로로 대조하도록 고친 후 통과했다. 제품 값 정규화나 회계 변경은 없었다.

재현 unit 명령은 `PYTHONPATH=src python -m pytest -q` 뒤에
`tests/unit/test_history_recovery.py`, `test_history_workflow.py`,
`test_history_quarters.py`, `test_c3_quarterly_policy.py`,
`test_core_quarterly_coverage.py`, `test_quarterly_analysis_pivot.py`,
`test_quarterly_derived_metrics.py`를 모두 `tests/unit/` 경로로 지정한다.
작은 cached gate는 `tests/integration/test_history_quarters_cached.py`만 대상으로
동일 resource guard 아래 실행한다. 이 테스트는 명시된 기존 offline 2공시가
없으면 skip하며 네트워크 fixture를 만들지 않는다. 이전 source oracle은 위
`a36ea059…` 두 모듈을 별도 임시 module로 로드하고 같은 reported publication과
original operational root를 입력해 새 임시 output을 비교했다.


### 2026-10-13 독립 source 655 FAIL 이후 정정

`65513173…` 독립 source 검증은 **FAIL**이다. 기존 149 unit·cached·oracle
PASS는 유지하되, 외부 proof를 hash한 뒤 pathname으로 다시 읽는 경쟁 조건과
새 output pathname만으로 rollback을 소유한다고 가정한 두 P1 결함이 발견됐다.
실제 recovery는 승인·실행되지 않았다. 원래 독립 보고서
`independent_source_6551317/report.json` SHA
`ef0b69e83f5f177a859ddd730662b2fac81c8c68ca323a794934fe4f53c94274`를 보존한다.

후속 수리는 인증한 단일 bytes buffer의 파싱, source file/directory identity
pin, no-follow FD copy, exclusive output reservation과 inode 소유권 검증,
소유권이 바뀐 root의 rollback 금지에 한정한다. output 또는 ancestor가 교체되면
이동한 자체 transaction과 교체된 다른 root 모두 건드리지 않고 ownership 오류로
중지한다. 새 후보는 다시 동결·독립 검증해야 한다. source generation AE와 actual
reported component 증거는 이 source 수리로 재작성하거나 재계산하지 않는다.

이 날짜의 상태 문구도 정정했다. 관찰값은 all 12 panels·staged manifest 존재,
rename 없음, SIGKILL 137과 위 max RSS이다. `verifier-only OOM`의 위치·원인은
강한 control-flow 추론이지 stack/kernel 진단이 아니었다. 과거 실패 보고서와
증거 바이트는 변경하지 않았다.

후속 writer 검증(독립 source 재검증 전):

- 관련 unit **164 passed / 1.89초**: 기존 149개에 인증 bytes 교체, output/root
  ancestor 교체, concurrent creator, payload 및 T1–T4 identity 변경, source-root
  alias와 quarter 실패 cleanup의 15개 음성 대조를 추가했다.
- 기존 offline NVDA 2공시만 사용하는 public fresh/recovery cached gate
  **1 passed / 15.14초**, guard 전체 15.31초, sampled process-group peak
  **376,655,872 bytes**. 이전 `a36ea059…` quarter/eager oracle도
  **8 tables / 25 files / 4,686 panel records / 42 derived records PASS**,
  전체 4.38초, peak **227,966,976 bytes**였다.
- 각 process group에 10 ms 간격 sampled RSS 2 GiB 중단 threshold와 300초
  timeout을 적용했다. 별도로 각 process에 hard `RLIMIT_AS=2 GiB`를 적용했으며,
  이는 virtual address 한도이지 hard RSS/cgroup allocation 한도가 아니다.
  `POLARS_MAX_THREADS=2`, BLAS/OMP/MKL/NUMEXPR threads 1, Python socket deny
  hooks를 사용했다. 실제 JNJ 재실행이나 actual proof 재작성은 하지 않았다.
- Ruff PASS. cached/oracle 이후 최종 source 조정은 output/source overlap의
  lexical `..` alias 정규화뿐이며 추가 unit 대조를 포함한 164개가 이후 통과했다.
  source 동결과 별도 독립 PASS 및 lead 승인 전에는 actual recovery를 실행하지 않는다.
