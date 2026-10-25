# History quarter cell delta v1

## 범위와 상태

`HISTORY_QUARTER_CELL_DELTA_V1`은 strictly-later 단일 CIK append에서 이미 증명된
이전 reported publication과 final History publication을 받아, dirty History 표의 모든
셀을 다시 private spill에 저장하던 비용을 줄이는 opt-in 경로다. 기존 full quarter
producer는 oracle과 fallback으로 그대로 남는다. 이 문서는 source 후보 계약이며 실제
AAPL 시간·RSS 측정, 독립 검증, 로컬 수락, 운영 반영과 `main` 병합은 아직 완료되지
않았다.

## 증명과 처리 경계

이 경로는 이전 final manifest가 이전 reported manifest의 정확한 SHA-256과 publication
경로에 묶였는지 먼저 확인한다. 현재와 이전 reported table은
`(ticker, view, period_class)` 순서와 source cell occurrence 순서가 append-compatible해야
한다. 각 source cell, source row와 source column은 타입을 보존해 비교한다. Parquet
round-trip의 list/tuple 차이와 schema union의 부재/null padding만 기존 계약대로 허용하며
`True`, `1`, `1.0`, candidate lineage와 provenance 차이는 같은 값으로 취급하지 않는다.

일치한 reported cell은 기존 final cell의 ID·순서·payload를 재사용하고, 허용된
`prior_candidate_publication` 경로만 현재 불변 reported publication으로 다시 묶는다.
변경되거나 새로 추가된 occurrence만 기존 period attestation과 reclassification을
실행한다. unchanged payload는 작은 bounded Parquet chunk로 전달하므로 큰 nested cell을
SQLite private payload spill에 다시 저장하지 않는다. row/column 인덱스와 최종 full
Parquet publication은 다시 작성되며, 물리 파일 I/O를 생략하는 기능은 아니다.

Q2/Q3/Q4 additive derivation은 입력 두 셀이 모두 unchanged이고 이전 metric/cell의
ID·row·column binding이 일치할 때만 이전 derived metric과 cell을 재사용한다. 나머지는
기존 derivation을 실행한다. 삭제·중복·모호성으로 더 이상 생성되지 않는 이전 metric은
제거 건수로 기록한다. 출력 이벤트는 reported `scanned/compared/reused/regenerated`와
derived `reused/recomputed/removed`를 각각 기록하며 0도 명시한다.

source table 삭제, occurrence 재배열, target period partition 이동, 이전 locator·derived
binding 불일치가 있으면 partial staging을 폐기하고 변경되지 않은 full producer를 새
staging에서 다시 실행한다. hash, count, schema, ownership, journal, atomic publication과
validation 정책은 완화하지 않는다. 이전 publication과 기존 결과는 수정하지 않는다.

## 현재 근거와 남은 측정

bounded cached NVDA append fixture에서 delta 경로는 current 2,456개 셀을 스캔해 이전
1,100개를 비교·재사용하고 1,356개를 재생성했다. 이 fixture에서는 이전에 재사용할
derived cell이 없어 42개를 재계산했다. full build와 append의 final columns/rows/cells 및
T1~T4 값·타입·ID·순서 비교가 통과했다. 이는 실제 AAPL 성능 증거가 아니다.

다음 단계는 source를 동결한 뒤 기존 승인 AAPL 22→23 cached front와 migration proof를
그대로 사용해 후보를 한 번 실행하는 것이다. 기준은 source `a83a3b2…`의 quarter
34.0198756초, 전체 92.161452초, 20ms 관측 RSS 2,092,429,312바이트인 historical 단일
실행이다. baseline은 다시 실행하지 않는다. 후보는 delta 실제 사용, counters, wall time,
RSS와 새 output의 full reference 동등성을 한 번 확인한다. 회귀하거나 이득이 실용적이지
않으면 채택하지 않으며, 다른 회사·반복 append·전체 운영 속도로 외삽하지 않는다.
