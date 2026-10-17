# 50 issuer private quarter spill 성능 전달 — 2026-10-17

## 결정과 상태

이번 마일스톤은 exact-50 연차·분기 History 생산의 **private quarter spill
성능 보완**이다. 최초 source/synthetic-only 계약 SHA-256은
`9ab16c36940c280f13c401b76a6fe778ea577d833a86dd6a73bc816d70aa8697`, timing
addendum SHA-256은
`e5467e4f89d45d6f66d2c57a5e4d4e90d58f0bc44775a1268087f6bbac539828`다.

최초 구현 후보 `ce45d956…`는 independent Astra 검증에서 **FAIL**했다. 봉인된
검증 report SHA-256은
`5e9218d974322df7da9594915af01c337e453ee4e077f1ddae131e58927370ad`다. 보정
계약 SHA-256
`8732481ee918c39ff858584fc63bd974e850ac8edab0e017ce8ce9db8088484a`에 따라 같은
sole-writer worktree에서 보호 경계를 복구했다. 현재 상태는
**CORRECTION_IMPLEMENTED_CANDIDATE / INDEPENDENT_REVERIFICATION_PENDING**이다.
최초 후보의 자체 profile과 test는 성능 탐색 자료이며 수락 근거가 아니다.

운영 요약은 JNJ 22-filing 실행이 reported panel 12개를 모두 쓴 뒤 마지막
`LATEST_REPORTED/YTD_6M` table의 2,304/3,701 cells에서 10,800초 timeout으로
중단됐고 peak process-tree RSS는 4,795,900 KiB였다고 기록한다. 이 구현에서는
해당 actual source, partial output, SEC/Raw/History payload를 읽거나 다시 실행하지
않았다. actual 재시도, resource cap·timeout 변경, publication·UI·application journal
운영 변경은 승인되지 않았다.

## 독립 검증 FAIL과 보정 경계

독립 검증은 최초 후보에서 두 ownership 회귀를 재현했다.

1. `PLANNED` 기록 직후 owned ancestor를 옮기고 원래 경로에 foreign tree를 만들면
   최초 기준은 SQL 전에 거부했지만 `ce45d956…`는 SQL과 `APPLIED`를 완료했다.
2. `mapping.items()` 첫 record를 받은 뒤 named journal entry를 교체하면 최초 기준은
   다음 record 전에 거부했지만 `ce45d956…`는 다음 record를 반환했다.

보정 후보는 mutation 시작, `PLANNED` append, 모든 SQL execute, `APPLIED` append마다
full ancestry·symlink·inode·held-FD 검증을 수행한다. `items()`는 ordered SQL query 한
번을 유지하되 record를 반환하기 직전에 full 검증한다. map wrapper가 같은 SQL 바로
앞에서 수행하던 중복 검증과 non-following stat 뒤의 두 번째 symlink stat만 제거한다.
typed value, key, ordinal, event 구조·순서, anonymous SQLite, checkpoint/fsync와 failure
artifact retention은 유지한다.

synthetic QP1 test는 `PLANNED` 뒤 ancestor exchange가 SQL 0 rows와
`OPEN/BUCKET/PLANNED` journal prefix로 끝나며 foreign sentinel을 보존함을 확인한다.
QP2 test는 yield 사이의 journal replacement, journal symlink, ancestor exchange를
모두 다음 record 반환 전에 거부하고 foreign entry를 보존함을 확인한다.

## synthetic profile 결과

profile은 16 GiB owned process-tree RSS guard, 10,800초 timeout, Polars thread 2,
`RLIMIT_AS` 없음, nonexistent corpus sentinel과 actual-data denial 아래 실행했다.

| workload | 기준 `3a3d7d6…` | FAIL 후보 `ce45d956…` | 보정 후보 | 동등성 |
| --- | ---: | ---: | ---: | --- |
| flat mapping, 2,000 records | 1.042초 | 0.183초 | 0.536초 | semantic SHA `49ade870…`, journal 721,684 bytes 동일 |
| `_spill_reported_table`, 3,701 nested cells | 10.662초 | 3.831초 | 6.749초 | paired complete-state SHA `6f482903…`, journal 23,201,609 bytes 동일 |

대표 table profile은 22 synthetic filings, nested `value_lineage`와
`candidate_lineage`, 4-axis dimension evidence, deep owned path, 17,660 mutations와
116 real checkpoint/fsync를 사용했다. full check는 기준 122,139회에서 보정 후보
105,338회, profiled `stat` call은 4,143,058회에서 1,788,422회로 줄었다. 두 paired
run 모두 3,701 input/output cells, 64 ordered rows, deduplicated column, materialized
coordinates와 additive locator 전체가 동일했고 cleanup을 완료했으며 blocked actual
path attempt는 0건이었다. FAIL 후보 수치는 이전 봉인 evidence의 탐색 측정값이며
보정 후보와 같은 보호 의미를 갖지 않는다.

source-only fixture는 수 초에 끝나므로 actual 3시간 전체를 설명하지 못한다. actual
record/payload 분포와 이후 derive/assemble 비용은 측정하지 않았고, 이번 결과로
actual 완료나 timeout 해소를 주장하지 않는다. 기존 `QUARTER_SPILL_BEGIN/FLUSH/END`
JSON에 추가된 nonnegative monotonic/elapsed metadata는 별도 승인된 다음 실행에서
table별 처리율을 판별하기 위한 것이며 `QUARTER_PANEL` payload는 바꾸지 않는다.

## 가정과 열린 XBRL 경계

- 이 변경은 private storage와 progress metadata에만 적용된다. period class,
  additive eligibility, Q4/Q3/Q2 공식, full dimension scope와 reported/derived 구분은
  바꾸지 않는다.
- private spill은 기존 producer와 같이 단일 실행 thread가 소유한다고 가정한다.
  SQLite index는 계속 anonymous이고 named journal FD만 실패 진단으로 남는다.
- actual JNJ의 대형 evidence 구조가 synthetic 분포와 같다고 가정하지 않는다.
  다음 actual 실행 결과 전에는 처리시간 개선의 외삽이나 성공 판정을 하지 않는다.
- 새 XBRL 회계 판단이나 미해결 taxonomy case는 없다. 새로운 의미 판단이 필요하면
  lead에게 반환한다.

## 구현자 자체 검증

보정 후보에서 focused quarter spill/rules 55개, synthetic panel memory와 History
recovery 153개, 전체 unit 1,568개가 통과했고 unit collection의 5개 cached-actual test가
deselect됐다. 명령에는 계약의 cached-actual 6개 node를 모두 명시적으로 deselect했고
screening node는 unit collection 밖이었다. 전체 `src`/`tests` Ruff와 diff check도
통과했다. 최대 measured process-tree RSS는 전체 unit의 310,517,760 bytes였으며 모든
resource run이 child를 회수했다.

모든 guarded pytest에서 actual-data blocked attempt 0건, reviewed-Q4 flag unset,
nonexistent corpus sentinel을 확인했다. cap 17,179,869,184 bytes와 timeout 10,800초,
`RLIMIT_AS` 없음은 유지했다. 이 결과는 구현자 자체 source/synthetic 검증이다. 별도
Astra가 새 동결 SHA를 읽기 전용으로 검증한 뒤 lead가 수락 여부를 판단한다. actual
retry에는 새 config, root GO와 보호 baseline에 대한 별도 승인이 필요하다.
