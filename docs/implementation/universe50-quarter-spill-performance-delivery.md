# 50 issuer private quarter spill 성능 전달 — 2026-10-17

## 결정과 상태

이번 마일스톤은 exact-50 연차·분기 History 생산의 **private quarter spill
성능 보완**이다. 승인 근거는 source/synthetic-only 계약
`lead_quarter_spill_performance_contract.json` SHA-256
`9ab16c36940c280f13c401b76a6fe778ea577d833a86dd6a73bc816d70aa8697`과
timing addendum SHA-256
`e5467e4f89d45d6f66d2c57a5e4d4e90d58f0bc44775a1268087f6bbac539828`다.
현재 상태는 **IMPLEMENTED_CANDIDATE / INDEPENDENT_VERIFICATION_PENDING**이다.

운영 요약은 JNJ 22-filing 실행이 reported panel 12개를 모두 쓴 뒤 마지막
`LATEST_REPORTED/YTD_6M` table의 2,304/3,701 cells에서 10,800초 timeout으로
중단됐고 peak process-tree RSS는 4,795,900 KiB였다고 기록한다. 이 구현에서는
해당 actual source, partial output, SEC/Raw/History payload를 읽거나 다시 실행하지
않았다. actual 재시도, resource cap·timeout 변경, publication·UI·journal 운영
변경은 승인되지 않았다.

## 마일스톤과 수락 기준

구현 후보는 다음 조건을 모두 만족해야 한다.

1. synthetic profile로 병목을 먼저 측정하고 동일 workload 전후를 비교한다.
2. decoded record, 순서, ID, typed value, source provenance, 회계·기간·선택 의미와
   producer schema를 바꾸지 않는다.
3. bounded-memory disk spill, held FD, ancestor·symlink·identity 검증, typed journal,
   failure evidence와 complete cleanup을 유지한다.
4. synthetic exact equivalence, integrity failure와 operation-count scaling test를
   추가한다.
5. 기존 quarter, History recovery와 bounded-memory regression을 actual-data path
   guard 아래 실행한다.
6. 별도 Astra read-only 검증 전에는 독립 검증이나 로컬 인수로 기록하지 않는다.

## 측정된 병목과 최소 변경

변경 전 flat mapping profile은 2,000 inserts, 200 overwrites, 250 point reads에서
1.042초가 걸렸다. full ownership check가 15,507회, stat call이 496,605회였고
`_QuarterSpill.check` 누적 시간은 0.908초였다. 같은 profile에서 SQLite execute
누적 시간은 0.016초였다. 따라서 `_SpillSequence.length`나 SQL row count가 아니라
한 public operation 안에서 ancestry 검증이 mutation, journal append와 SQL execute에
중첩되는 경로를 먼저 보완했다.

- mutation 시작에서 ancestry와 symlink를 한 번 완전히 검사한다.
- `PLANNED → anonymous SQLite → APPLIED` 사이에는 held directory와 journal FD를
  `fstat`하여 exchange를 계속 fail-closed한다.
- 각 binding은 이미 얻은 non-following stat mode로 symlink를 판정하여 같은 path의
  두 번째 stat을 없앤다.
- ordered mapping `items()`는 key별 재조회 대신 한 번의 검증된 ordered SQL
  iteration을 사용한다.
- 기존 `QUARTER_SPILL_BEGIN/FLUSH/END` JSON에 monotonic clock과 table elapsed
  seconds를 추가한다. 기존 `QUARTER_PANEL` record와 producer output은 바꾸지 않는다.

public `execute`, mapping read/mutation, bucket journal과 checkpoint는 계속 검증
경계다. journal event 구조·순서와 disposable anonymous SQLite 설정도 그대로다.
mutation 도중 named journal path를 바꾸는 synthetic attack은 SQL 적용 전에
거부하고 foreign replacement를 건드리지 않는다.

## synthetic profile 결과

두 profile은 16 GiB owned process-tree RSS guard, 10,800초 timeout, Polars thread 2,
`RLIMIT_AS` 없음, nonexistent corpus sentinel과 actual-data denial 아래 실행했다.

| workload | 기준 `3a3d7d6…` | 구현 후보 | full check | stat call | 동등성 |
| --- | ---: | ---: | ---: | ---: | --- |
| flat mapping | 1.042초 | 0.183초 | 15,507 → 2,454 | 496,605 → 39,469 | semantic SHA `49ade870…`, journal 721,684 bytes 동일 |
| `_spill_reported_table`, 3,701 nested cells | 10.593초 | 3.831초 | 122,139 → 34,569 | 4,143,053 → 587,537 | complete-state SHA `1b150520…`, journal 23,149,795 bytes 동일 |

대표 table profile은 22 synthetic filings, nested `value_lineage`와
`candidate_lineage`, 4-axis dimension evidence, deep owned path, 17,660 mutations와
116 real checkpoint/fsync를 사용했다. 3,701 input/output cells, 64 ordered rows,
deduplicated column, materialized coordinates와 additive locator 전체를 canonical JSON으로
hash하여 비교했다. 두 run 모두 synthetic workspace cleanup을 완료했고 blocked actual
path attempt는 0건이다.

구현 후보 profile에도 ownership check 1.306초, nested deepcopy 0.668초, fsync
0.186초, Parquet iteration 0.207초, SQLite execute 0.186초, spill packing 0.141초가
남았다. 이 source-only fixture는 수 초에 끝나므로 actual 3시간 전체를 설명하지
못한다. actual record/payload 분포와 이후 derive/assemble 비용은 측정하지 않았고,
이번 결과로 actual 완료나 timeout 해소를 주장하지 않는다. 새 elapsed telemetry는
별도 승인된 다음 실행에서 table별 처리율을 판별하기 위한 metadata다.

## 가정과 열린 XBRL 경계

- 이 변경은 private storage와 progress metadata에만 적용된다. period class,
  additive eligibility, Q4/Q3/Q2 공식, full dimension scope와 reported/derived 구분은
  바꾸지 않는다.
- private spill은 기존 producer와 같이 단일 실행 thread가 소유한다고 가정한다.
  SQLite index는 계속 anonymous이고 named journal FD만 실패 진단으로 남는다.
- actual JNJ의 대형 evidence 구조가 synthetic 분포와 같다고 가정하지 않는다.
  따라서 다음 actual 실행 결과 전에는 처리시간 개선의 외삽이나 성공 판정을 하지
  않는다.
- 새 XBRL 회계 판단이나 미해결 taxonomy case는 없다. 새로운 의미 판단이
  필요하면 lead에게 반환한다.

## 구현자 자체 검증

2026-10-17 구현 후보에서 다음을 확인했다.

- focused quarter spill/quarter rules: **52 passed**.
- synthetic panel memory + History recovery: **153 passed**.
- 전체 unit: **1,565 passed / 5 deselected**. 명령에는 계약의 cached-actual 6개
  node를 모두 명시적으로 deselect했고 screening node는 unit collection 밖이었다.
- 모든 guarded pytest에서 actual-data blocked attempt 0건, reviewed-Q4 flag unset,
  nonexistent corpus sentinel을 확인했다.
- 최대 measured process-tree RSS는 전체 unit의 322,801,664 bytes였고 모든 resource
  run은 child를 회수했다. cap 17,179,869,184 bytes와 timeout 10,800초는 변경하지
  않았다.
- 전체 `src`/`tests` Ruff와 `git diff --check`: PASS.

이 결과는 구현자 자체 source/synthetic 검증이다. 별도 Astra가 동결 SHA를 읽기
전용으로 검증한 뒤 lead가 수락 여부를 판단한다. actual retry에는 새 config,
root GO와 보호 baseline에 대한 별도 승인이 필요하다.
