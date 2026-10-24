# AAPL 분기 추가 처리 성능 개선 (2026-10-24)

## 상태와 범위

- 제품 소스: `18f88728e2ba3a8d5dbc026c0aa4491eebaae8c6`
- 상태: 독립 검증 3건 PASS, 리드 로컬 수락 완료
- 수락 근거: `work/actual_quarter_append_20261024/lead_acceptance.json`
  (SHA-256 `24242a99499fd6f3b1f5cdc09d25dc5763fc0432054c93caf8cb1994f1e4c757`)
- 적용 상태: 로컬 source와 bounded actual fixture 수락이며, `main` 병합·원격 전달·
  운영 runtime 채택은 수행하지 않았다.

이 milestone은 AAPL의 22개 filing 기준 자료에 2026 회계연도 Q3 10-Q 한 건을
추가하는 오프라인 cached replay를 한 번 측정하고, 그 실행에서 가장 큰 단일
함수 경계였던 quarter publisher의 중복 private metadata 저장만 줄였다. 기존 Raw,
완료 50개 회사, 21 UI, 운영 기록과 결과는 변경하거나 다시 검증하지 않았다.

## 측정과 병목

네트워크 다운로드를 제외하고 offline discovery, cached Arelle 추출, 23개 filing
전체 history build와 새 publication 정상 조회를 측정했다. 정확한 pre22 publication이
없어서 22개 setup build 93.232초는 한 번 수행했지만 append 비교에서는 제외했다.
첫 holdout 시도는 cache hit 전 client 생성에 user-agent가 필요해 payload 처리 전에
실패했다. 실패 기록은 보존했고, fetch를 계속 fail-closed로 둔 채 로컬 probe 식별자를
사용한 `holdout-intake-v2`에서 1.317초에 추출했다. 비밀 user-agent나 네트워크 요청은
측정에 포함하지 않았다.

기준 build 101.136초 중 quarter publisher가 42.337초로 가장 큰 직접 분리 함수였다.
제한 attribution에서는 private spill `SET` 115,639건 중 같은 bucket/key 반복이
31,238건(27.0%)이었다. 소유권 `check`는 673,287회였다. 이 수치는 inclusive 호출
시간이 서로 겹치므로 합산하지 않는다.

| 구간 | 기준 | 후보 | 변화 |
| --- | ---: | ---: | ---: |
| quarter publisher | 42.337초 | 38.513초 | -9.03% |
| build | 101.136초 | 96.923초 | -4.17% |
| 공통 앞단 + build + query | 103.324초 | 99.110초 | -4.08% |
| 20ms 표본 process-tree RSS 최고값 | 2,144,870,400 B | 2,183,675,904 B | +1.81% |

공통 앞단의 discovery 0.223초와 cached extraction 1.317초는 한 번만 실행해 양쪽에
같이 더했다. 두 번 수집한 결과가 아니다. RSS는 개선되지 않았다. 두 실행 모두 첫
`QUARTER_SPILL_BEGIN` 전에 worker의 최종 `ru_maxrss` high-water에 도달했으므로 새
작은 ID index가 최고값의 직접 원인이라고 볼 시간 순서 근거는 없지만, 메모리 비용이
0임을 증명하지도 않는다. 이 단일 pair 결과를 다른 회사나 전체 History 성능으로
외삽하지 않는다.

## 구현과 정확성

`_spill_reported_table`은 한 source table 안에서 같은 target row를 다시 저장하지
않는다. column은 target ID만 기억하지 않고 마지막 source column ID를 기억한다.
따라서 서로 다른 source column이 같은 target ID로 수렴해 `A → B → A` 순서로
나타나도 세 변경을 모두 적용한다. 다음 source table에서는 작은 index를 새로 만들어
첫 write를 다시 수행하므로 기존 table 순서와 last-wins 동작을 보존한다.

cell, materialized, additive, derived mutation은 바꾸지 않았다. 실제로 남은 각
mutation의 `PLANNED → SQL → APPLIED`, ancestor/symlink 검사, journal, SQLite typed
encoding과 원자 publication 경계도 그대로다. 구현은 producer 전체를 row 수준으로
증분화하지 않으며, 새 filing 입력은 여전히 23개 전체 History를 다시 생성한다.

기준과 후보는 output parent만 다르고 basename은 모두 `run`이다. path-bearing
provenance 때문에 Parquet SHA와 manifest의 source-manifest SHA는 달라질 수 있다.
두 owned root prefix만 정규화한 뒤 31개 파일의 record 31,230건을 비교했다. schema,
record/key 순서, Python type, 값, ID, 기간, 단위와 provenance가 모두 같았다. plan,
scope, rules, input fingerprint와 count 등 manifest 의미 필드도 같았다. baseline
manifest는 후보 실행 전 기록한 SHA와 실행 후 SHA가 일치했다.

Writer는 직접 영향 4건을 실행해 PASS했고 Ruff와 diff 검사를 통과했다. 검사는
`A → B → A`, source table 경계의 last-wins, 큰 streamed evidence, 소유권 guard 호출
수와 `PLANNED` 이후 ancestor 교체 거부를 포함한다. 별도 reviewer의 수리 범위 3건도
PASS했다. 완료 회사 검증이나 109단계 독립 감사는 실행하지 않았다.

기계 증거는 `work/actual_quarter_append_20261024/`의 `baseline_report.json`,
`quarter_attribution_report.json`, `candidate_report.json`,
`output_equivalence.json`, `final_report.json`에 있다. 이 locator는 선택적 실행
증거이며 본 문서의 계약을 대신하지 않는다.
