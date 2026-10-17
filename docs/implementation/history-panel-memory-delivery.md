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
문자열로 바꾸지 않는다.

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

unit, synthetic integration, 관련 History spill/recovery regression과 Ruff가 구현자
자체검사를 통과한 뒤 local commit SHA를 동결한다. 별도 검증자가 같은 SHA를 읽기
전용으로 재검증한다. actual cached regression과 JNJ retry는 이 source 전달에 포함되지
않는다.

## 4. 상태와 후속 실행

이 문서의 source/synthetic 구현은 사용자 승인 범위다. 독립 검증과 lead acceptance는
아직 별도 상태다. 16 GiB actual PASS, JNJ recovery, first-five financial readiness,
exact-50 financial readiness를 이 구현만으로 주장하지 않는다.

JNJ retry는 다음 조건을 모두 충족한 별도 실행이다.

1. 새 source commit과 module hash를 동결하고 독립 source/synthetic PASS를 받는다.
2. lead가 별도로 수락한다.
3. 기존 partial을 재사용·삭제·덮어쓰지 않는 새 output root/run version을 쓴다.
4. source-pinned OPS preflight와 새 stage GO를 받는다.

cap 상향, allocator mode만 바꾼 재시도, ticker-specific 조건, accepted OPS 8a 상수
변조, 기존 publication 재표시는 허용하지 않는다.
