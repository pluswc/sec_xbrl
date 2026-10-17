# History panel 메모리 전달 계약

기준일은 **2026-10-17 KST**다. 이 전달은 exact-50 History를 16 GiB
process-tree RSS cap 아래에서 다시 실행하기 위한 **실행 소유권 변경**이다. Raw,
T1–T4, selector, 기간 분류, recast, quarter 산식, row/column/cell ID와 정렬,
회계 의미 및 publication schema는 바꾸지 않는다.

## 1. 사건과 증거 경계

JNJ 22 filings의 새 History build는 source
`8a1b40ab1008fb9109a27b2a5bcea02a257e1694`에서 T1–T4와 AS_FILED
FY/INSTANT/OTHER_DURATION table을 쓴 뒤, QTD_3M table을 쓰기 전에 중단됐다.
감시 summary는 633.803초, peak process-tree RSS 16,803,860 KiB, cap
16,777,216 KiB, worker return code -15와 `RSS_LIMIT`을 기록한다. summary SHA-256은
`af79afb404bdcf9c95bda1fbfd4207a0659aab91d672c40e7677281cbf15830b`다.
실패한 `.panels.partial-u5zhmp_v`, 원본과 이전 output은 보존한다. 최종 History
manifest와 READY marker가 없으므로 이 실행은 **NOT_READY**다.

로그·RSS metadata와 source 실행 구조가 증명하는 직접 원인은 다음 중첩 소유권이다.

1. `build_history`가 한 view/period-class의 완성 T5 panel을 모두 `inputs`에 둔다.
2. eager `FiscalTimeSeriesBuilder.build`가 같은 panel들을 tuple로 유지하면서 row,
   candidate lineage와 최종 cell에 nested provenance를 다시 복사한다.
3. 모든 입력 panel과 완성 result는 table staging이 시작될 때까지 함께 살아 있다.

RSS metadata는 마지막 129초 동안 약 11.05 GiB에서 16.03 GiB까지 계속 증가한
현상과 일치한다. 실제 JNJ payload를 이 진단에서 읽거나 재실행하지 않았으므로 이
중첩 소유권을 JNJ의 유일한 원인이나 최종 actual cap 통과 증거로 단정하지 않는다.

## 2. 승인된 최소 구현

기존 public `FiscalTimeSeriesBuilder.build`의 signature와 eager 결과는 유지한다.
추가 `build_spilled` 경계는 입력 iterable에서 T5 panel 하나를 완전히 처리한 뒤 그
참조를 해제하고 다음 panel을 요청한다. 다음 항목만 disk-backed private index에 둔다.

- row ID별 첫 row record
- row/column 좌표별 ordered candidate definition, binding, value
- 작은 fiscal column metadata와 공통 scope

SQLite는 빈 filename의 private temporary database, `temp_store=FILE`, 2 MiB cache,
`mmap_size=0`으로 사용한다. SQLite가 compile-time memory-only temp store이면 fail
closed한다. publication path나 입력이 지정한 DB를 열지 않는다. 별도 run-owned
journal은 checksum frame과 marshal 기반 typed payload를 사용한다. tuple/list,
bool/int/float, bytes, `Decimal`, date/time/datetime/timedelta 및 nested dict의 형식을
문자열로 바꾸지 않는다. time/datetime의 `fold`와 naive/UTC/named
fixed-offset/표준 `ZoneInfo` timezone identity도 typed payload에 둔다. 지원하지 않는
custom `tzinfo`는 값이나 timezone 의미를 바꾸지 않고 명시적으로 실패하며 journal을
보존한다.

첫 구현 동결 `685185394993ba61493d82ca4b18f2f5464fe183`은 독립 검증에서
**FAIL**이었다. checksum byte가 바뀐 journal도 읽고 성공 정리했으며, journal은 그대로인
상태에서 SQLite candidate BLOB의 `value_numeric`을 `2024`에서 `999999`로 바꿔도
변조값을 반환했다. nested `datetime.time(..., fold=1)`도 `fold=0`으로 바뀌었다. 해당
독립 report SHA-256은
`671f6e7cb7ba985a0ea17e40bd674c405a0f17119af8ffc5e3c3c595480f474c`이며 그
동결은 수락 대상이 아니다.

보완 구현은 process memory에 둔 committed checkpoint를 신뢰점으로 사용한다. 이
checkpoint는 다음을 함께 결속한다.

- framed journal의 최종 byte size, event count와 ordered rolling digest
- row와 candidate 각각의 record count 및 ordinal/key/typed BLOB ordered digest
- SQLite table/index schema와 rows/candidates의 ordinal 및 publication order identity

checkpoint 생성 시 SQLite commit, journal checkpoint append와 `fsync`를 마친 뒤 전체를
검증한다. 이후 public `records`/`materialize` 전에 다시 검증하고, 성공 cleanup 직전에도
검증한다. journal checksum을 다시 계산한 payload 변조도 trusted rolling digest와
다르므로 실패한다. journal truncate/append/frame 손상, row/candidate 변경·삭제,
ordinal이나 schema 변경도 실패한다. 검증은 journal payload를 최대 64 KiB chunk씩, SQLite row는 하나씩
순차 처리한다. 손상된 frame length도 전체 journal 크기의 RAM 할당을 유발하지 않는다. 재사용 가능한 public dataset은 각
iteration 시작과 성공 cleanup에서 다시 검증한다. History의 bounded batch iterator는
offset slice로 앞부분을 반복 재주사하지 않으므로 검증은 output row/chunk마다 반복되지
않는다. 손상을 발견하면 public 결과를
반환하거나 성공 publication으로 정리하지 않고 journal 진단을 보존한다.

rows와 cells는 기존 `_row`, `_row_order`, `_resolve_cell`, `_id`를 그대로 사용한다.
rows는 `(mapping_review_required, label, row_id)`, cells는 `(row_id, column_id)` 순서로
재생한다. candidate resolution은 기존 `analysis_line_value_id` sort와 동일하다.
History writer는 이 re-iterable bounded sequence를 기존 global-schema staging에
전달한다. 따라서 table-global nested JSON field 판정, batch 크기, Parquet schema,
count/hash/manifest 생성도 기존 writer를 그대로 거친다.

성공은 세 table이 모두 staging/finalize된 뒤에만 선언한다. 그때 held file descriptor와
root/directory/journal inode를 다시 확인하고 자신이 만든 journal과 빈 디렉터리만
정리한다. selection, staging 또는 finalize 실패 시 SQLite cache만 닫고 typed checksum
journal과 `.panels.partial-*`을 보존한다. 실패 output은 reader 기본 정책상 계속
NOT_READY다.

## 3. 보존해야 하는 의미와 수락 기준

synthetic public Fiscal/History 경계에서 eager와 spilled 결과가 다음 모두에서 같아야
한다.

- columns, rows, cells의 record 수와 순서
- 모든 ID, status, value, candidate 선택과 unavailable reason
- definition/binding/value lineage, role/edge/path, dimensions, unit와 period evidence
- nested tuple/list 및 scalar Python type
- History Parquet count, JSON field set, SHA-256와 재독출 record

증가하는 N의 synthetic panel에서 다음 panel을 요청하기 전에 이전 panel 소유권이
해제돼야 한다. index는 disk-backed여야 하며 성공 cleanup, 실패 journal 보존,
foreign replacement를 지우지 않는 ownership 검사를 수행한다.

손상 negative control은 journal checksum/payload/truncate/append와 SQLite
row/candidate 삭제·변조, ordinal·schema 변경을 포함한다. positive typed control은
time/datetime `fold`, `Decimal` exponent와 signed zero, date/timedelta/tuple/list,
UTC/named fixed-offset/가능한 환경의 `ZoneInfo`를 public eager/spilled builder 경계에서
비교한다. Public History 경계에서는 Parquet count, JSON field set, SHA-256와 재독출
record가 같아야 한다.

unit, synthetic integration, 관련 History spill/recovery regression과 Ruff가 구현자
자체검사를 통과한 뒤 local commit SHA를 동결한다. 별도 검증자가 같은 SHA를 읽기
전용으로 재검증한다. actual cached regression과 JNJ retry는 이 source 전달에 포함되지
않는다.

### 2026-10-17 F3/F4 정정과 검사 경계

두 번째 동결 `5a48407017337debb443c4bbc7a10a4b663431e8`도 독립 검증
**FAIL**이다. F1/F2의 55 controls와 93 Parquet 비교는 통과했지만, NULL BLOB 또는
sort key가 `TypeError`를 일으키면 public close가 DB와 세 FD를 남겼다(F3).
첫 frame length를 journal 전체 나머지 길이로 바꾸면 checksum 거부 전에 전체를
읽는 RAM 요청이 가능했다(F4). 독립 report SHA-256은
`67c4db8dec8f3755b73f4b1433958136305105c17a50ec9b96e16c44b75cb52a`다.

lead는 기존 구현자의 memory 소유권을 종료하고 별도 Astra를 이 두 경계의 단일
구현자로 명시적으로 배정했다. 구현 역할 상향은 오류 양상에 따른 범위 한정 판단이며
모델 성능 우위 주장이 아니다. 승인 계약 SHA-256은
`1ee9b82b8029422595eaf530afb23d4fb40bd319b12dccad1c7fdac6ec76c234`다.
수정 범위는 Fiscal spill 무결성/정리 경계, 해당 unit test와 이 전달 문서/계획이다.
`history.py`, eager API, typed encoding, 기존 checkpoint digest, 회계·기간·선택과
publication 의미는 그대로다.

- F3: BLOB은 실제 `bytes`인지 검사한다. NULL, 잘못된 key/sort/schema 및 일반 검증
  예외는 `FiscalTimeSeriesError`로 정규화한다. 성공 정리 전 검증 실패나 interrupt가
  발생해도 DB와 세 FD를 각각 닫는 시도를 끝내고 오류를 반환하며 journal을 보존한다.
  interrupt는 cleanup 뒤 원래 interrupt로 반환한다. 개별 OS/DB close 자체가 실패하면
  다른 handle도 모두 시도하고, 실패한 handle은 public close로 다시 닫을 수 있게 유지한다.
  실제 남은 handle이 있는 동안 public `_closed`를 terminal로 만들지 않는다.
- F4: payload checksum과 `SHA256(previous_digest || uint64_length || payload)`를
  같은 64 KiB 이하 chunk들로 갱신한다. digest 형식은 그대로이며 untrusted length가
  큰 단일 read/allocation을 결정하지 않는다. 8/128/512 panels의 forged length와
  큰 typed unicode frame/short-read에서 거부 및 원래 digest 호환을 검사한다.

이전 구현자 unit **1,519 passed / 4 skipped**와 독립 검증 초기 **1,522 passed /
1 skipped**는 실제 캐시를 읽는 unmarked unit test를 배제하지 않았다. 해당 결과는
source/synthetic-only 수락 근거에서 제외한다. 이전 interrupted run, 자체검사,
ancestor-directory 과잉 차단 및 launch 실패는 각각 원래 실행 증거로 보존하며
제품 실패나 유효한 source-only PASS로 재분류하지 않는다. 독립 검증자의 수정된
5-test-deselected 재실행은 1,519 passed였으나 F3/F4 제품 FAIL을 해소하지 않았다.

모든 후속 source/synthetic unit 검사에는 다음 절차를 적용한다. 이 규칙은 lead의
검사 범위 정정 SHA-256
`b36d68ef113573883b9a41c30e8aee176eb46e376a30d7af7ab7753f48610853`을
추적 문서에 승격한 것이다.

1. 지정 구현 checkout에서 실행하며 검증용 동결은 clean 상태여야 한다. main이나
   다른 실행 checkout을 cwd/PYTHONPATH로 쓰지 않는다. Python은 승인된 main venv의
   절대 경로를 사용하며 이는 실행기 의존성 공유만을 뜻한다.
2. pytest import/collection 전에 `SEC_XBRL_CORPUS_ROOT`를 존재하지 않는 evidence
   sentinel로 설정하고 `SEC_XBRL_RUN_REVIEWED_Q4_INTEGRATION`을 unset한다.
3. 다음 다섯 node ID를 외부 CLI `--deselect`로 명시적으로 제외한다. 기존 test를
   수정하거나 skip 표시를 추가해 실행 범위 문제를 숨기지 않는다.

```text
tests/unit/test_corpus_release.py::test_actual_seven_company_corpus_is_admitted_when_cached
tests/unit/test_c3_as_filed_publication.py::test_c3_m1_actual_seven_company_corpus_when_cached
tests/unit/test_c3_as_filed_publication.py::test_cached_nvda_fy2024_q1_revenue_selects_direct_10q_when_available
tests/unit/test_versioned_observation_panel.py::test_cached_nvda_fy2024_q3_revenue_is_directly_retrievable
tests/unit/test_reviewed_q4.py::test_cached_nvda_source_to_api_snapshot_xlsx
```

4. collection 전 실제 data/cache/publication roots와 network를 거부하는 guard를 설치한다.
   own evidence 경로의 엄격한 ancestor에는 directory traversal/scandir metadata만 허용하고,
   실제 파일 open이나 무관한 subtree는 계속 거부한다. absolute/relative/symlink/dirfd
   실제 파일 접근 거부와 own output dirfd 허용을 자체 검사한다. 첫 unexpected denial에
   중지하고 harness 실패와 제품 실패를 구분한다. Python audit guard는 native library
   모든 I/O를 보장하지 못하므로 실제 cached entrypoints를 별도로 deselect하고, 남은
   실제 loader의 JSON 접근을 native Parquet read 전에 차단한다.
5. `POLARS_MAX_THREADS=2`, sampled process-tree RSS 16 GiB, timeout 10,800초,
   단일 heavy worker와 parent-death/owned-child cleanup을 적용한다. Python/Polars에는
   address-space 제한을 걸지 않는다. 자체 evidence 및 `/tmp` basetemp만 사용한다.
6. `tests/unit`와 `tests/integration/test_history_panel_memory_synthetic.py`를 실행한다.
   passed/failed/skipped/deselected, warnings, elapsed/peak RSS, guard denials와 child
   reaping을 기록한다. 이 실행은 5개를 제외한 전체 unit이지 cached 포함 full suite가 아니다.
   기존 55 synthetic controls/93 Parquet 비교 및 `ruff check --no-cache src tests`,
   `git diff --check`도 수행한다.

새 F3/F4 후보의 구현자 검사 결과와 source SHA는 인계 report에 기록한다. focused
Fiscal unit/public History synthetic은 **77 passed**이고, 기존 55 controls와 93 Parquet
비교도 PASS다. guarded 전체 허용 unit + public synthetic integration은 **1,561 passed /
5 deselected / 0 skipped**, 73.64초, peak process-tree RSS 301,768,704 bytes였다.
네 가지 예상 실제 open 거부 control을 통과했고 unexpected denial은 0이며 모든 owned
worker는 reap됐다. 전체 src/tests Ruff와 diff check도 PASS다. 독립 검증과 lead 수락은
새 동결 이후 별도 단계다. synthetic RSS는
actual JNJ 16 GiB cap 통과나 실제 input byte 보존의 증거가 아니다.

## 4. 상태와 후속 실행

이 문서의 source/synthetic 보완 구현은 사용자 승인 범위다. 이전 `6851853…`와 `5a48407…` 독립
FAIL은 보존하며 새 F3/F4 동결의 독립 검증과 lead acceptance는 아직 별도 상태다. 16 GiB
actual PASS, JNJ recovery, first-five financial readiness, exact-50 financial readiness를
이 구현만으로 주장하지 않는다.

JNJ retry는 다음 조건을 모두 충족한 별도 실행이다.

1. 새 source commit과 module hash를 동결하고 독립 source/synthetic PASS를 받는다.
2. lead가 별도로 수락한다.
3. 기존 partial을 재사용·삭제·덮어쓰지 않는 새 output root/run version을 쓴다.
4. source-pinned OPS preflight와 새 stage GO를 받는다.

cap 상향, allocator mode만 바꾼 재시도, ticker-specific 조건, accepted OPS 8a 상수
변조, 기존 publication 재표시는 허용하지 않는다.
