# 스크리닝 대시보드 사용자 시나리오 인수 계약

## 1. 상태와 목적

기준일은 **2026-10-08 KST**다. 이 문서는
[`screening-dashboard-roadmap.md`](../planning/screening-dashboard-roadmap.md)의
미래 구현을 검증하기 위한 **PROPOSED** 계약으로 작성됐다. **2026-10-09 KST에
사용자가 P0–P6 로컬 v1 구현과 실제 21사 실행을 승인했으므로 이제 이 S01–S08은
해당 구현의 인수 계약이다.** 구현 범위는
[`screening-dashboard-delivery.md`](screening-dashboard-delivery.md)에 고정한다.
이 후속 승인은 구현 완료·독립 검증·로컬 인수·원격 병합을 미리 주장하지 않으며,
P7 live refresh와 새 cohort를 승인하지 않는다.

**2026-10-09 최종 후속 상태:** source
`acce036d1f8feef2f268b1df740009a11ce537e5`의 S01–S08이 실제 21사와 분리된
cache/synthetic control에서 독립 **PASS**했고 lead가 P0–P6를
**LOCALLY_ACCEPTED**로 판정했다. 정확한 결과와 증거는
[완료·로컬 인수 기록](screening-dashboard-completion.md)에 있다. 과거
`8b3e8e1`, `64ce126`, `6364688` 후보의 결함·철회 이력도 그 기록에서 보존한다.
사용자의 직접 UX walkthrough와 push·PR·remote CI·`main` 병합은 계속
**PENDING**이다.

### 2026-10-09 R1 지표 확장 보강

사용자가 승인한 R1은 기존 S01–S08의 저장·실행·trace·journal·비교·export·오류
계약을 유지하면서 [31개 지표 정의](screening-metric-definitions.md)를 dataset v2에서
검증한다. **2026-10-09 후속 상태:** R1 최종 source `271fb1c968ebc03d98aea1561cd096187302a7fe`와
실제 R3가 독립 **PASS**했고 lead가 **LOCALLY_ACCEPTED**로 판정했다. 식별자와
한계는 [R1 완료 기록](screening-usability-completion.md)에 있다. 사용자의 직접
walkthrough와 원격 상태는 계속 별도다.

- actual 21사 support matrix에서 31개 정의를 모두 보존하고 available/unavailable
  회사·연도 수와 business reason을 독립 집계와 대조한다.
- 기존 네 `annual-core-reported-v1` 조건은 immutable revision을 고치지 않고 v2에
  재실행하며, 새 reported/derived 조건은 각자의 exact definition version을 쓴다.
- FY와 연도말 INSTANT는 같은 fiscal year 아래에서도 period class와 실제 날짜를
  분리해 보여주고, missing/review/block를 0이나 FAIL로 바꾸지 않는다.
- 화면·HTTP·export는 frozen metric observation을 소비할 뿐 formula나 predecessor
  selection을 실행하지 않는다. 산술 expected 값은 screening executor를 oracle로
  사용하지 않는 별도 검증으로 만든다.
- v1과 v2를 같은 catalog에서 열어도 과거 run의 bound dataset/publication과 현재
  사용자 journal revision/event가 바뀌지 않아야 한다.

인수 목표는 “화면이 열린다”가 아니다. 사용자가 실제 조건을 저장하고 실행한
뒤 모든 대상 회사의 결과와 이유를 보고, 값의 출처를 추적하고, 자신의 판단을
이력으로 남기고, 과거 실행과 새 실행을 구분해 다시 열고, 같은 governed 결과를
내보낼 수 있어야 한다.

## 2. 판정 규칙

각 predicate는 `PASS`, `FAIL`, `UNDETERMINED` 중 하나와 reason을 가진다. 기존
governed record의 `quality_status`와 reason은 `WARN` 등을 포함해 원래 값 그대로
보존한다. 스크리닝 gate가 사용 불가로 판정한 경우에는 별도
`quality_blocking: true`를 기록한다. 이 flag는 기존 quality 계약을
`CLEAR`/`BLOCK`으로 이름 바꾸지 않는다. 누락, `UNAVAILABLE`,
`REVIEW_REQUIRED`, incompatible period/unit/basis, quality block은 0이나 `FAIL`로
바꾸지 않는다.

회사 aggregate는 다음 순서로만 정한다.

1. 하나라도 유효한 값으로 판정한 `FAIL` predicate가 있으면 aggregate는
   `FAIL`이다. 다른 unknown, governed quality warning과 blocking flag는 그대로
   남긴다.
2. 모든 predicate가 유효한 `PASS`이고 `quality_blocking: true`나 unknown이
   하나도 없으면 aggregate는 `PASS`다.
3. 그 밖의 경우 aggregate는 `UNDETERMINED`다.

`quality_blocking: true`인 값을 사용해 `PASS`를 만들 수 없다. 기본 선별
목록에는 aggregate `PASS`만 포함하고, `FAIL`·`UNDETERMINED`·quality-blocked
회사도 전체 결과 표에서는
숨기지 않는다. 사용자가 “미결정 포함”을 켜면 그 상태를 유지한 채 보일 뿐
통과로 바뀌지 않는다. 결과 수는 target, pass, fail, undetermined,
quality-block을 함께 표시한다. `pass + fail + undetermined = target`이어야 하고,
`quality-block`은 그 회사들 중 겹치는 subset count이며 네 번째 summand가 아니다.

정렬은 저장된 column/direction 다음에 CIK 오름차순을 최종 tie-breaker로
사용한다. 같은 입력 publication, screen revision과 rule version은 같은 full-row
결과와 순서를 만들어야 한다.

## 3. 제안 영속 모델

화면 template, 실행 결과, 투자 판단은 서로 다른 record다.

| record | 최소 불변 내용 |
| --- | --- |
| `ScreenDefinition` / `ScreenRevision` | 이름, universe selector, metric predicate와 원하는 metric definition/version policy, period/view/as-of policy, column/sort, 생성자·시각, 이전 revision ID, screen version |
| `UniverseSnapshot` | universe snapshot ID, 전체 CIK 목록과 순서, metadata publication/hash, SIC·unknown 상태, source observed time |
| `ScreenRun` | run ID, screen revision ID, universe snapshot ID, full input/output hash, data/metric/mapping/parser/rule versions, financial as-of, review cutoff, source observed times, 실행 시각 |
| `ScreenRow` / `PredicateEvaluation` | 모든 target CIK, 실제 period boundary, metric ID/value/status/unit, PASS/FAIL/UNDETERMINED, 원래 governed quality status/reason, 별도 quality-blocking flag, Analytical/Derived/raw source IDs |
| `DecisionEvent` | event ID, CIK, `INTEREST`/`HOLD`/`EXCLUDE`, before/after, rationale, evidence IDs, run ID, actor/time, 이전 event ID |
| `ExportManifest` | run/screen/universe ID, export scope, row/column order, source identities와 dates, file hash/size/format |

결정 event는 append-only다. 정정은 과거 event를 덮어쓰지 않고 before/after와
reason이 있는 새 event를 추가한다. 사용자의 note는 판단 근거이며 Analytical
Fact나 Derived Metric을 바꾸지 않는다. browser undo/redo는 편집 편의일 뿐,
data lineage 또는 durable investment decision journal이 아니다.

구현은 local backend 또는 동등한 durable persistent store와 backup/restore를
제공해야 한다. browser `localStorage`만 쓰거나 screenshot만 보관해서는 저장된
조건, frozen run, decision history를 인수할 수 없다. backup을 새 빈 환경에
restore한 뒤 S01, S05, S06의 동일 식별자와 history를 다시 읽는 검사가 필요하다.

## 4. fixture와 독립 expected result

### 실제 fixture

실제 fixture는 locally accepted 21사 universe와 그 immutable prepared
publication을 가리키는 manifest다. 381개 raw filing과 history가 `READY`라는
사실만 사용하며, 후보 metric이 21사 모두에 존재한다고 가정하지 않는다. P1
support matrix에서 `AVAILABLE`로 확인된 **annual metric과 기간만** 실제 positive
control로 고른다.

독립 검증자는 frozen governed input에서 CIK별 선택 값, period, status, expected
predicate와 aggregate pass/fail set을 수동 evidence check 또는 별도 단순 oracle로
작성한다. 이 oracle은 screening executor를 호출하거나 executor의 output을 다시
읽어 예상값을 만들 수 없다. metric 값 표본은 raw Fact/accession 또는 이미
검증된 Analytical/Derived lineage까지 손으로 대조한다. executor 결과와 oracle은
별도 hash와 작성자를 가진다.

### 합성·cache fixture

다음은 실제 결과와 별도 디렉터리·label로 둔다.

- 같은 값·같은 sort key의 deterministic tie
- missing, invalid metric ID, quality block, zero-result 조건
- backend save 실패와 backup/restore 실패
- 새 filing이 나타나는 cached future-update와 rule/mapping version 변경

합성값은 실제 회사 성과나 live refresh 증거가 아니다. cached future filing도
`CACHE_FUTURE_UPDATE_FIXTURE`로 표시하며 SEC live 수집 성공으로 보고하지 않는다.
version이 둘 이상 바뀐 refresh는 원인을 자동으로 단정하지 않고
`MIXED_OR_INCOMPARABLE_VERSION_CHANGE`로 보수적으로 표시한다.

## 5. 사용자 시나리오

### S01 — 이름 있는 조건 저장과 재열기

- **사용자 목표:** universe, industry, period, criteria, columns/sort를 하나의 이름
  있는 screen revision으로 저장하고 중단 후 그대로 다시 연다.
- **전제:** 실제 21사 fixture, P1에서 지원 확인된 annual metric 하나, durable
  backend와 backup 경로가 준비되어 있다.
- **행동:** `새 조건` → 이름 입력 → **전체 21사 universe와 SIC 미분류 포함** 선택
  → industry scope를 `전체`로 명시 → FY period와 predicate 입력 → column/sort
  선택 → `저장` → server와 browser 종료·재시작 → 저장 목록에서 같은 이름과
  revision 열기 → 별도 빈 환경에서 backup restore 후 다시 열기. 이어서 그
  revision을 복사해 한 SIC로 좁힌 별도 revision을 저장하고 실행한다.
- **정확한 기대:** 저장 성공을 backend commit 이후에만 표시한다. screen ID,
  revision ID, universe selector, 원하는 metric definition/version policy,
  period/view/as-of policy, columns/sort가 byte-equivalent canonical record로
  복원된다. 재시작이나 restore로 조건이 사라지지 않는다. full-universe baseline은
  21 CIK를 대상으로 하고, 별도 SIC-narrowed revision의 target count는 그 실행에
  묶인 frozen universe snapshot과 정확히 같다. 실제 data/mapping/parser publication
  version은 저장 template가 아니라 각 `ScreenRun`에 묶인다. 이전 실행 context가
  있으면 별도 run reference로 보일 뿐 template를 덮어쓰지 않는다.
- **영속 증거/검사:** `ScreenDefinition`, `ScreenRevision`, `UniverseSnapshot`,
  backup manifest/hash, save audit event; DOM의 이름·revision·criteria와 backend
  record를 대조한다.
- **단계·경계:** P5 실제 fixture. 저장 실패는 S08의 synthetic fault를 별도 실행한다.

### S02 — 전 CIK 결과와 보수적 선별

- **사용자 목표:** 조건을 실행하고 모든 대상 회사가 왜 통과·실패·미결정·차단인지
  확인한다.
- **전제:** S01의 **전체 21사·SIC 미분류 포함 baseline revision**, 독립 oracle의
  21 CIK expected rows와 pass/fail set, 실제 support matrix가 있다.
- **행동:** `실행` → 전체 결과 count 확인 → PASS/FAIL/UNDETERMINED filter와 별도
  quality-blocking filter를 차례로 선택 → 각 predicate reason과 원래 governed
  quality status를 펼치기 → 같은 run을
  재조회하고 sort를 되돌리기.
- **정확한 기대:** 21개 target CIK가 정확히 한 번씩 존재한다. 모든 predicate에
  판정·reason·quality가 있고 missing 값은 숫자 0으로 표현되지 않는다. 기본
  selected set은 PASS만 포함한다. aggregate 규칙과 count가 oracle과 일치하고
  동률은 CIK 순서로 안정적이다. 숨겨진 회사와 중복 행은 0이다.
- **영속 증거/검사:** immutable `ScreenRun`, 21 `ScreenRow`, predicate records,
  canonical result hash, count reconciliation, 독립 expected-result diff.
- **단계·경계:** P3 executor 검증 후 P5/P6 실제 fixture. synthetic tie/missing은
  실제 결과와 분리한다.

### S03 — 값에서 raw 출처까지 trace

- **사용자 목표:** 선택 회사의 스크리닝 값을 근거까지 추적한다.
- **전제:** 실제 fixture에서 support matrix가 `AVAILABLE`인 회사·annual metric
  한 쌍과 독립 수동 source check가 있다.
- **행동:** 결과 행 선택 → metric cell 선택 → 우측 evidence panel에서 formula와
  compatible input 펼치기 → Analytical/Derived ID → raw Fact → accession으로 이동.
- **정확한 기대:** 화면 값·unit·실제 period start/end·fiscal label이 governed
  record와 같다. reported 값은 raw Fact/accession을, derived 값은 formula/rule
  version과 모든 compatible input ID를 보인다. incompatible·blocked input은
  numeric result로 승인되지 않는다.
- **영속 증거/검사:** selected cell ID, trace JSON/hash, source Fact/accession,
  formula/input IDs, screenshot와 DOM text, 독립 수동 evidence sheet.
- **단계·경계:** P5 실제 positive control. 새 formula를 이 시나리오에서 만들지
  않는다.

### S04 — SIC peer와 서로 다른 실제 fiscal period 비교

- **사용자 목표:** SIC peer 후보를 고르고 실제 fiscal end가 다른 회사의 선택
  기간과 mapping 관계를 혼동 없이 비교한다.
- **전제:** B metadata와 실제 history에서 SIC 후보이면서 서로 다른 fiscal
  period end를 가진 최소 두 CIK를 독립적으로 찾는다. 이 조건이 없으면 fixture
  준비가 `BLOCKED`이며 날짜를 합성하지 않는다.
- **행동:** 한 회사에서 `SIC peers` → peer 선택 → 비교 period 선택 → actual
  start/end, fiscal label, mapping relation, unknown classification toggle 확인.
- **정확한 기대:** 각 회사 열에 자기 실제 날짜가 보이고 같은 FY label만으로
  같은 날짜처럼 표시하지 않는다. mapping relation은 exact/approved/unknown
  상태와 version을 보인다. unclassified 후보를 숨기지 않고 `UNKNOWN_SIC`로
  표시한다. SIC를 회계 동등성으로 쓰지 않는다.
- **영속 증거/검사:** metadata publication/hash, selected CIKs, period IDs/dates,
  mapping IDs/version, peer query result, DOM 날짜·unknown label.
- **단계·경계:** P6 실제 fixture. 역사 membership 또는 투자 추천은 범위 밖이다.

### S05 — 관심·보류·제외 판단 이력

- **사용자 목표:** 회사에 대한 자신의 판단과 근거를 남기고 수정 역사를 본다.
- **전제:** 실제 S02 run과 선택 CIK가 있다.
- **행동:** `관심` 선택 + rationale/evidence 추가 → `보류`로 수정하며 새 reason
  입력 → history timeline에서 두 event 열기 → server 재시작 후 다시 확인.
- **정확한 기대:** 두 event가 같은 CIK·run과 연결되고 두 번째 event가 첫
  event를 참조한다. before/after, actor/time, reason, evidence ID가 남으며 첫
  record는 바뀌지 않는다. note가 metric 값이나 screen result를 바꾸지 않는다.
- **영속 증거/검사:** append-only `DecisionEvent` chain, DB audit/hash, timeline DOM,
  restart 및 backup/restore readback.
- **단계·경계:** P5 실제 run에 사용자 판단 event를 기록한다. 이 판단은
  governed 재무 truth 또는 매수 정책이 아니다.

### S06 — frozen old run과 별도 new run 비교

- **사용자 목표:** 과거 실행을 그대로 열고 같은 저장 조건을 별도 new input
  publication에 다시 실행해 무엇이 달라졌는지 본다.
- **전제:** frozen S02 run, 같은 `ScreenRevision`, 별도 새 input publication 또는
  `CACHE_FUTURE_UPDATE_FIXTURE`가 있다. P6 control은 실제 old run과 명시적으로
  labelled된 cached-future publication을 사용한다.
- **행동:** old run 열기 → `같은 조건으로 새 입력 실행` → 별도 new run 열기 →
  diff panel에서 data/rule/universe/manual-decision version을 비교 → old run으로
  돌아가기.
- **정확한 기대:** run ID와 full rows는 별도이며 old run은 변하지 않는다.
  diff는 data, metric/rule/mapping, universe snapshot, manual decision 변화를
  분리한다. 같은 saved revision은 원하는 query/metric policy를 유지하지만 각
  run은 그 시점에 해결한 실제 data/mapping/parser/rule version을 별도로 기록한다.
  여러 version이 바뀌어 원인을 하나로 귀속할 수 없으면
  `MIXED_OR_INCOMPARABLE_VERSION_CHANGE`를 보인다. 미래 filing fixture를 live
  refresh라고 표시하지 않는다.
- **영속 증거/검사:** 두 `ScreenRun`과 input/output hash, version tuple,
  row/predicate diff, decision-event references, old-run immutability hash.
- **단계·경계:** P6에서 실제 old run과 cached/synthetic new-input control을
  검증한다. 실제 live/운영 refresh와 cohort 확대는 P7의 별도 제안이며 승인·실행
  증거가 있을 때만 인수한다.

### S07 — governed 결과와 동일한 CSV/XLSX export

- **사용자 목표:** 화면에서 검토한 run을 외부 검토용으로 내보낸다.
- **전제:** 실제 S02 run과 U5 canonical snapshot/export boundary가 연결되어 있다.
- **행동:** 전체 scope와 현재 selected scope를 각각 CSV/XLSX로 export → 파일을
  다시 읽어 canonical run과 비교.
- **정확한 기대:** row/column order, 값, status, unknown/block reason이 governed
  result와 같다. 파일 또는 manifest에 screen/revision/run/universe ID, financial
  as-of, review cutoff, source observed time, metric/rule/mapping/parser version,
  export scope를 포함한다. blank display와 numeric zero를 구분한다.
- **영속 증거/검사:** `ExportManifest`, CSV/XLSX hash·size, canonical cell diff 0,
  full/selected scope row count, source identity check.
- **단계·경계:** P5/P6 실제 fixture. 외부 서비스 market data export를 복제하지
  않는다.

### S08 — 회복 가능한 empty/error/accessibility 상태

- **사용자 목표:** 결과가 없거나 입력·저장에 실패해도 원인을 이해하고 keyboard로
  복구한다.
- **전제:** zero-result control과 synthetic missing/invalid-metric/save-error fixture,
  1,440px 및 1,024px browser viewport가 있다.
- **행동:** zero-result 조건 실행 → criteria 수정 → invalid metric URL/record 열기 →
  backend save fault 중 저장 → keyboard만으로 criteria/table/evidence/error action을
  이동 → 1,024px에서 panel 열고 닫기.
- **정확한 기대:** zero result는 `0건`과 조건 수정 action을 보이며 회사가
  사라졌다는 뜻으로 바꾸지 않는다. missing/invalid metric은 reason과 복구 경로를
  보인다. save failure는 절대 `저장됨`을 표시하지 않고 draft/재시도/취소 선택을
  제공한다. focus가 보이고 순서가 논리적이며 panel focus가 열림/닫힘 때 이동·복귀한다.
  1,024px에서 핵심 context, result status, evidence 접근이 잘리거나 겹치지 않는다.
- **영속 증거/검사:** fault ID, save transaction 부재, error audit, DOM/assertion log,
  keyboard focus trace, 1,440px·1,024px screenshot, page error/network log.
- **단계·경계:** P6. zero-result는 실제 support가 허용하면 actual control을 쓰고,
  missing/invalid/save fault는 `SYNTHETIC_ERROR_FIXTURE`로 명시한다.

## 6. requirement → scenario → browser → evidence map

| 요구 | 시나리오 | 필수 browser check | durable evidence |
| --- | --- | --- | --- |
| 저장·재시작·restore | S01 | save state, 재열기 DOM, false-success 없음 | revision, universe snapshot, backup manifest |
| 전 CIK와 deterministic 판정 | S02 | count/filter/sort/reason | run rows, predicate set, independent oracle diff |
| source·formula lineage | S03 | evidence panel, trace navigation | trace hash, raw/Analytical/Derived IDs |
| peer·period·mapping honesty | S04 | actual date와 unknown label | metadata/period/mapping IDs |
| append-only 판단 | S05 | timeline과 restart readback | decision event chain |
| old run과 rerun 분리 | S06 | run switch와 conservative diff label | 두 run hash와 version tuple |
| export 동일성 | S07 | export scope/상태 표시 | export manifest와 canonical diff |
| empty/error/keyboard/compact | S08 | 1,440/1,024 DOM·focus·error recovery | screenshots, DOM/focus/page-error logs |

## 7. 미래 실행과 보고 절차

1. 구현자는 frozen actual fixture manifest와 별도 synthetic fixture manifest를
   만든다.
2. 독립 검증자는 executor 없이 governed input에서 expected row/value/pass/fail
   evidence를 준비하고 hash를 동결한다.
3. 자동 검사는 schema·집계·불변성·export를 확인하고, 실제 browser는 1,440px와
   1,024px에서 S01–S08의 click/keyboard 흐름을 수행한다.
4. 한국어 step-by-step walkthrough는 각 단계의 클릭, 화면에 보여야 할 text·count·
   status·run ID, 기대 근거 panel을 함께 설명한다.
5. 각 시나리오는 `PASS`, `FAIL`, `BLOCKED` 중 하나, 실제/합성/cache 경계, output
   위치, artifact hash, screenshot/DOM/log 위치와 제한을 기록한다. 증거 bundle은
   `/tmp`나 설치 skill에 의존하지 않는 지속 위치에 둔다.
6. 독립 검증 report는 frozen source SHA와 fixture/publication identity를 묶는다.
   자동 browser `PASS`는 사람이 직접 UX를 수락했다는 뜻이 아니다. 독립 `PASS`,
   lead의 `LOCALLY_ACCEPTED`, 한국어 human walkthrough 확인, remote PR/CI/merge는
   서로 다른 상태다.

실패 화면을 screenshot으로만 설명하거나, 같은 executor가 자신의 예상 결과를
만들거나, 일부 selected row만 비교하면 인수할 수 없다. 실제 21사 결과와
synthetic 오류가 한 count나 한 “실제 검증” 주장으로 섞여도 인수할 수 없다.

## 8. 미승인 사항

아래 목록은 최초 v1 범위의 경계다. 2026-10-09 R1에서 별도 계약으로 승인·검증한
정확한 21 reported + 10 derived 정의, 그 10개 공식과 표준화
`CFO−PP&E 취득지출` FCF는 아래 첫 세 항목의 예외다. 이 R1 계약 밖의 새 지표·
공식, issuer가 별도로 정의한 FCF와 나머지 항목은 여전히 승인되지 않았다.

- metric 후보를 실제 screening metric으로 승인하는 일
- 새로운 formula, mapping, comparable/recast 의미 또는 Q4 scope
- FCF, TTM, 가격, valuation, 보편적 21사 quarterly metric
- 자동 매수 기준·점수·추천·색상 순위
- historical universe membership 또는 현재 SIC를 과거에 소급하는 기능
- live refresh, 외부 배포, 새 UI framework, push·PR·CI·merge

이 중 하나가 필요하면 별도 근거, lead의 회계/범위 판단, 구현 승인과 독립
검증 계약을 먼저 추가한다.
