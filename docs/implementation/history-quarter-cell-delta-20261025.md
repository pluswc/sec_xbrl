# History quarter cell delta v1

## 범위와 상태

`HISTORY_QUARTER_CELL_DELTA_V1`은 증명된 History append에서 과거 fiscal cell을 다시
분류하고 nested payload를 private spill에 넣는 일을 줄이는 opt-in 경로다. public
Parquet schema, ID, 값, 순서, provenance와 불변 publication 계약은 바꾸지 않는다.
기존 full quarter producer는 oracle과 보수적 fallback으로 남는다. 이 문서는 source
후보 계약이며 실제 AAPL 시간·RSS, 독립 검증, 로컬 수락, 운영 반영과 `main` 병합은
아직 완료되지 않았다.

## FAST 경로의 증명 경계

FAST 경로는 builder가 만든 private capability가 현재 reported manifest SHA-256,
input fingerprint, T1~T4 root와 이전 reported/final publication에 정확히 묶일 때만
활성화된다. 다음 조건을 모두 만족해야 한다.

- strictly-later 단일 CIK의 비수정 `10-Q` 한 건이다.
- as-of, view, selector, period, mapping, quarter 정책과 producer code identity가 같다.
- 새 `CURRENT_FOCUS` fiscal key가 이전 key와 겹치지 않고 fiscal chronology 뒤에 온다.
- typed T1 prefix와 T4 prefix가 같고 T3는 stage-preserving merge를 통과한다.
- 새 filing의 graph node와 edge가 이전 filing scope를 건드리지 않는다.

`10-K`, amendment, backfill, old fiscal insertion, as-of/view/policy 변경, T3 full fallback,
schema·ID·순서 충돌이나 capability 재사용은 FAST 대상이 아니다. 이 경우 증명되지 않은
이전 경로와 dirty flag를 버리고 이미 수락된 table-level full quarter 경로를 실행한다.
특히 as-of 변경은 provenance field를 바꿀 수 있으므로 이전 셀 재사용으로 일반화하지
않는다.

## 처리 방식과 정확성

현재와 이전 reported publication에서는 hash, count와 schema를 먼저 확인한 뒤 compact
cell ID·row ID·column ID 순서와 작은 row/column metadata를 비교한다. 전체 nested
reported payload를 다시 비교하지 않는다. 새 fiscal column의 셀만 전체 디코드하고 기존
period attestation과 reclassification을 실행한다.

이전 final의 unchanged reported cell은 native Parquet projection으로 한 번 스트리밍하며
허용된 `prior_candidate_publication` 경로만 현재 reported publication으로 다시 묶는다.
이전 derived cell과 새 Q2/Q3/Q4 계산에 필요한 이전 additive partner만 선택적으로
디코드한다. 이전 derived metric의 ID·row·column과 두 입력이 모두 unchanged이면 그대로
재사용하고, 새 dependency closure만 기존 규칙으로 계산한다. compact index는 표당
200,000건·64MiB, payload batch는 8MiB로 제한하며 초과하면 full fallback한다.

최종 row/cell 순서는 current reported source occurrence 순서로 만든 bounded ordinal에
따라 복원하고 derived cell을 그 뒤에 붙인다. column은 기존 fiscal order와 comparability
규칙을 유지한다. output은 여전히 full-readable immutable publication이며 unchanged
Parquet도 새 destination에 쓴다. 따라서 저장 I/O 자체를 없애는 기능은 아니다.

성공 이벤트 `QUARTER_CELL_DELTA`는 `fast_path_activated=1`, current scan/compare,
reported reuse/regeneration, derived reuse/recompute/removal을 0값까지 기록한다. 파일 hash,
count, JSON-field schema, ownership, journal과 atomic publication 검사는 그대로다. 오류나
부분 staging은 새 output으로 섞지 않고 폐기한 뒤 full 경로로 전환한다.

## 검증과 측정 경계

작은 단위 검사는 typed scalar 구분, stale capability, fiscal backfill, native copy의 derived
제외와 path rebind, additive derivation reuse/removal을 확인한다. cached NVDA의 Q1→Q2
append는 FAST를 실제 활성화해 fresh full build와 columns/rows/cells 및 T1~T4의 값·타입·ID·
순서·provenance가 같음을 확인한다. 이는 실제 AAPL 성능 증거가 아니다.

실제 비교 기준은 기존 수락 AAPL 22→23 R6 한 회 실행의 quarter 34.0198756초, 전체
92.161452초, 20ms 관측 RSS 2,092,429,312바이트다. baseline과 완료 회사 감사를 다시
실행하지 않는다. 새 후보는 같은 cached front와 migration proof로 한 번만 실행하고,
FAST 활성화·counters·wall time·RSS 및 새 output과 수락 full reference의 동등성을 한 번
확인한다. 단일 pair 결과를 다른 회사, 반복 append나 모든 운영 refresh에 외삽하지 않는다.
