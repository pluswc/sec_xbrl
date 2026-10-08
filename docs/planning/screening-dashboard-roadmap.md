# 기업 스크리닝 대시보드 로드맵

## 1. 상태와 기준

기준일은 **2026-10-08 KST**다. 이 문서는 향후 기업 스크리닝 기능의
**PROPOSED** 계획이다. 구현, 회계 정책 추가, 라이브 수집, 원격 브랜치 작업을
승인하지 않는다. 미래 수락 조건도 구현 승인이 아니다.

| 구분 | 식별과 현재 상태 |
| --- | --- |
| 로컬 제품 기준 | `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`, 2026-10-08 `LOCALLY_ACCEPTED` |
| 추적 문서 기준 | `473521560fa9e47aa00d6a273cbaa90c708ad366` |
| `main` 기준 | `201acf9aec2f8183acb7dd843579938db14236cd`; 이번 로컬 전달은 push·PR·remote CI·merge를 수행하지 않음 |
| 이번 산출물 | 로드맵, 사용자 시나리오 인수 계약, 계획 등록부 링크뿐이며 제품·테스트·데이터 변경 없음 |

기존 회사 universe 결과는 21개 회사, 381개 공시와 21개 governed history가
`READY`임을 증명한다. 이는 모든 회사에 같은 스크리닝 지표가 존재하거나 서로
회계적으로 동등하다는 증명이 아니다. 회사 마스터는 후보 issuer 8,016개 중
pilot 21개의 SIC를 분류하고 7,995개를 미분류로 유지한다. SIC는 현재 관측된
동종 후보 신호이며 과거 시점의 지수 구성, 역사적 membership 또는 회계적
동등성이 아니다.

NVDA의 승인된 Q4 범위는 16개 경제값과 두 보기의 32개 record다. 이 범위는
2026-09-06 역사 분석 reference와 2026-10-08 재무 수집 기준일, 별도 Q4 검토
cutoff를 가진다. 스크리닝 화면은 이 날짜들을 하나의 동일시점 횡단면으로
합치거나 21개 회사 전체의 Q4 가용성으로 확대하지 않는다.

세부 사용자 인수 기준은
[`screening-dashboard-user-acceptance.md`](../implementation/screening-dashboard-user-acceptance.md)에
있다. 기존 universe의 실제 근거와 제한은
[`universe-data-delivery-completion.md`](../implementation/universe-data-delivery-completion.md)에
남는다.

## 2. 목적과 책임 경계

대상 사용자는 회사 후보를 좁히고, 왜 포함·제외·보류됐는지 확인하고, 그 시점의
조건과 판단을 다시 여는 분석자다. 핵심 동사는 **조건을 저장하고 실행하고,
근거를 추적하고, 판단 이력을 남기고, 옛 실행과 새 실행을 비교하는 것**이다.

대시보드는 기존 [Analytical/Derived plane](../architecture/analytical-data-model.md),
[Consumer Data Access Layer](../implementation/consumer-data-access-layer.md)와
[U5 canonical snapshot/export](../implementation/u5-consumer-export.md)를 소비한다.
다음 동작은 하지 않는다.

- SEC 문서 수집·파싱 또는 Arelle 실행
- 공시·recast·comparable view 선택 정책 실행
- 화면에서 새 재무 지표, Q4, TTM, FCF, 가격·가치평가 값을 계산
- 누락·quality block·검토 필요를 0으로 변환
- SIC 또는 한 metric의 유사성을 회계적 동등성으로 승격
- 관심·보류·제외 메모를 governed 재무 사실로 기록

새 라이브러리나 UI framework는 이번 계획에서 선택하지 않는다. 구현 단계는
기존 HTML/JS, 접근 가능한 native control과 현재 디자인 자산을 먼저 조사한 뒤
필요성을 증명해야 한다.

## 3. 먼저 만들어야 할 스크리닝 계약

연간 기간부터 시작한다. `REVENUE`, `revenue_growth`, `operating_margin`, `CFO`는
후보 지표일 뿐이다. 각 지표가 실제 21사 × 지표 × 기간에서 어떤 의미와 상태를
갖는지 검증되기 전에는 필터 목록에 공개하지 않는다. FCF, TTM, 가격, 가치평가,
21사 공통 Q4는 이 범위에 암묵적으로 포함되지 않는다. 매수·매도 또는 “좋은
기업”의 수치 임계값도 정책으로 만들지 않는다.

지표 가용성 publication은 최소한 다음 grain과 상태를 가져야 한다.

```text
company CIK × metric definition/version × actual period × view/as-of
  -> AVAILABLE | UNAVAILABLE | REVIEW_REQUIRED | QUALITY_BLOCKED
```

각 record는 실제 period start/end, fiscal year/period class, unit, full dimension
signature, source type, Analytical/Derived ID, raw Fact와 accession까지의 trace,
metric·mapping·selection·parser version, financial as-of, review cutoff, source
observed time, 불가/차단 reason을 보존한다. 이 publication이 없으면 화면을 먼저
만들지 않는다.

## 4. 단계별 전달 순서

| 단계 | 제안 작업 | 종료 증거 |
| --- | --- | --- |
| P0 기준 통합 gate | 로컬 accepted 제품과 추적 문서가 구현 브랜치의 명시적 부모인지 확인하고, 아직 수행하지 않은 remote PR/CI/merge를 별도 상태로 둔다. | 부모 SHA, 포함 관계, 원격 상태를 기록한 구현 계약. 현재는 **미수행** |
| P1 지표 가용성·의미 | 연간 후보 지표별 21 × metric × period inventory와 실제 fiscal boundary, mapping 관계, unavailable/block reason을 publish한다. | 전체 CIK grain, 중복 0, 숨긴 회사 0, 독립 source/semantics 검토 |
| P2 영속 계약 | screen definition/revision, immutable universe snapshot, execution run/row/predicate, decision event, export manifest를 정의한다. | schema·불변성·backup/restore·append-only 결정 이력 계약 |
| P3 실행기 | 저장 조건을 deterministic하게 평가하고 독립 oracle의 예상 결과와 대조한다. | 실제 fixture의 전 CIK 결과, predicate별 상태·reason, 정렬·집계 증거 |
| P4 방향·wireframe | 아래 reference와 provenance signature를 반영한 주석 wireframe을 만든다. P1/P2의 의미·영속 계약 조사와 독립적인 visual exploration은 병렬로 할 수 있다. | 1,440px·1,024px 화면 상태, focus 순서, 데이터/상태 label; 모두 `PROPOSED`/`MOCK` 표시 |
| P5 실제 한 줄기 | 한 annual metric 조건 저장 → 실행 → 회사 trace → 판단 event → 재열기 → export를 실제 prepared publication으로 연결한다. | S01·S02·S03·S05·S07의 실제 end-to-end 증거 |
| P6 전체 인수 | S01–S08을 실제 21사 fixture와 별도 synthetic 오류 fixture로 독립 실행하고 실제 브라우저를 검사한다. | requirement→scenario→browser check→artifact map, 독립 `PASS`/`FAIL` |
| P7 refresh·cohort 확장 | frozen old run과 새 publication rerun 차이를 분리하고, 추가 cohort를 같은 계약으로 검증한다. | data/rule/universe/manual-decision diff와 cache/synthetic/live label; 새 승인 없이는 범위 확대 금지 |

각 단계는 제안·승인·구현·독립 검증·로컬 인수·main merge를 따로 기록한다.
P4의 mock이나 screenshot은 P5의 실제 데이터 연결을 대신하지 않는다. 실제
dashboard binding은 P1의 governed availability와 P2의 persisted contract가
동결되기 전에는 시작하지 않는다.

## 5. 화면 방향 — 차분한 분석 작업대

이 방향은 설치된 `interface-design` 지침을 적용해 도메인 탐색부터 정했다. 사용한
skill source는 upstream `2f9be3206855bcb2d1d0af262c8bae25cba6658d`에 고정되어
있고 설치 파일 digest는
`720b31a31276e899fbe3006a33cbfeaceb77a73ba4c27b80d29afd38c8b7b208`이다.
이 도구는 설계 검토 보조이며 추적 문서나 인수 근거의 전제조건이 아니다.
`.interface-design/system.md`는 아직 없고, 저장·확정된 design system이 있다는
주장을 하지 않는다.

### 도메인 탐색

- **도메인 언어:** CIK, accession, financial as-of, fiscal year boundary,
  review cutoff, source observation, mapping version, decision event, frozen
  run, evidence chain.
- **자연스러운 색 세계:** 원장 종이의 옅은 ivory, 오래된 문서의 ink charcoal,
  filing 표의 slate, 검토 주석의 blue, 보류 표식의 amber, 차단 도장의 red.
- **signature:** 화면을 이동해도 유지되는 **run context + 회사별 decision/trace
  chain**이다. 이 signature는 (1) 상단 financial context strip, (2) criteria
  revision header, (3) 결과 행의 상태·짧은 run label, (4) 우측 evidence panel,
  (5) history timeline의 다섯 위치에서 같은 실행을 연결한다. 전체 ID와 hash는
  provenance 상세에서만 노출한다.
- **버릴 기본값:** 장식용 KPI 카드 grid는 context ledger strip으로, 색만 있는
  red/green 순위는 상태명·reason이 있는 표로, 하나의 mutable “최신 저장 화면”은
  immutable run과 append-only decision history로 바꾼다.

### 제안된 구성

한 화면의 초점은 결과 표다. 상단 context strip에는 사용자가 판단에 바로 쓰는
financial as-of, 선택 기간, universe 이름·회사 수, 저장 조건 이름·revision,
짧은 run label, review 상태를 둔다. source observation과 metric/mapping/parser/rule
version 및 전체 hash는 펼칠 수 있는 provenance 상세로 내린다. 그 아래 criteria
zone에서 universe와 predicate를 편집하고 저장 상태를 명확히 보인다. 가운데에는
CIK grain의 조밀한 결과 표와 보기·정렬·비교 control을 둔다. 오른쪽 evidence
panel은 선택 행의 metric → Analytical/Derived → raw Fact/accession trace와 quality
reason을 보여준다. 아래 history timeline은 저장 revision, 실행,
관심/보류/제외 decision event를 섞지 않고 시간순으로 연결한다.

### component checkpoint

| 항목 | `PROPOSED` 방향 |
| --- | --- |
| Intent | 분석자가 많은 숫자보다 조건·결과·근거·판단의 연결을 차분하게 확인한다. |
| Hierarchy | 결과 표가 초점이고, context strip과 criteria는 짧게, evidence panel은 선택 시 깊어진다. |
| Palette | ivory/ink/slate가 대부분을 차지하고 blue는 annotation/action, amber는 review, red는 block에만 쓴다. PASS/FAIL은 색 외 text·icon·reason을 함께 쓴다. |
| Depth | 조밀한 도구에 맞는 borders-only와 미세한 surface shift 한 전략을 쓴다. overlay만 한 단계 위 surface다. |
| Surfaces | canvas, inset input, selected row/evidence, overlay의 제한된 네 단계다. 장식 shadow를 섞지 않는다. |
| Typography | 기존 한국어 font 지원과 `PreparedKorean` loading path를 먼저 조사하고 실제 사용 가능한 자산이면 재사용한다. 없으면 접근 가능한 system Korean fallback을 쓴다. 표 숫자는 tabular, 값·label·metadata·disabled의 네 단계 weight/color를 제안하며 새 font 다운로드를 요구하지 않는다. |
| Spacing | 4px base, 8px micro gap, 12px control padding, 16px section gap의 밀도 높은 체계를 제안한다. 구현 전 실제 화면에서 조정한다. |

native semantic table, button, input을 우선하고 기존 접근 가능한 primitive가
있으면 재사용한다. keyboard focus, loading, empty, invalid, save failure,
quality block, narrow desktop 상태가 기본 화면과 함께 설계되어야 한다. 실제 시각
검증은 1,440px desktop, 1,024px compact desktop과 keyboard-only 흐름에서 한다.
이번 문서는 screenshot 또는 visual `PASS`를 주장하지 않는다.

## 6. 외부 reference register

확인일은 모두 **2026-10-08**이다. reference는 interaction과 정보 구조를
관찰하기 위한 것이며, 외부 market data, brand, code 또는 회계 의미를 복사하지
않는다.

| 출처 | 확인한 패턴 | 제안 화면과 시나리오 | 근거 한계 |
| --- | --- | --- | --- |
| [Finviz Screener](https://finviz.com/screener) | 공개 DOM에서 descriptive/fundamental/technical filter군, order control, 조밀한 sortable 결과 표를 확인 | criteria zone·결과 표 → S02, S08 | 로그인 기능·인기·데이터 정확성을 측정하지 않았고 공개 DOM만 관찰 |
| [Koyfin My Screens](https://www.koyfin.com/help/my-screens/) | 공식 도움말의 name → universe → criteria → results, criteria column, sort/edit, watchlist/CSV 흐름 | 저장 정의·실행·export → S01, S02, S07 | 문서와 공식 screenshot을 읽었을 뿐 로그인 앱을 조작하지 않음 |
| [Koyfin My Views](https://www.koyfin.com/help/my-views/) | 재사용 column/settings, grouping/sort, manual save/save-as, screen으로 view 이동 | column view revision → S01, S06 | Koyfin의 autosave 의미를 채택하지 않으며 우리 run/decision 불변성은 별도 계약 |
| [Koyfin 공식 screener screenshot](https://www.koyfin.com/help/content/images/2024/06/screener-header.png) | 실제 pixel에서 왼쪽 작업 navigation, named tabs, `Universe Criteria`/`Filter Criteria`, `Modify Criteria`, selectable dense table, Columns/Summary/Sort, Save as watchlist/Download를 확인 | table-primary workbench 전체 방향 → S01, S02, S07 | 선택적 관찰 파일 `/tmp/sec-screening-koyfin-reference.png`, SHA-256 `de075b6f3a15e5cfeda72f1c7c2f0430ce389b9f4bcdff3e716db69dbcf084e5`; `/tmp`는 인수 전제조건이 아니며 화면 수치도 복사하지 않음 |
| [TradingView filter 도움말](https://www.tradingview.com/support/solutions/43000718745-how-to-use-filters-in-screener/) | top filter chip, preset/manual condition, reset/remove, expanded/collapsed panel과 keyboard shortcut | criteria interaction·compact state → S01, S08 | 공식 문서만 확인했고 실제 계정 화면이나 market data는 사용하지 않음 |
| [TradingView saved screen 도움말](https://www.tradingview.com/support/solutions/43000718804-how-to-create-save-and-update-a-custom-screen/) | filter, column, sort, view mode, name 저장과 save/copy/undo 흐름 | 저장 revision·old run/rerun → S01, S06 | 외부의 mutable template 동작을 그대로 채택하지 않고 immutable execution을 추가 |

## 7. 재현 가능한 다음 인계

다음 구현 제안자는 임시 screenshot이나 설치된 skill 없이도 이 문서와 사용자
인수 계약만으로 작업할 수 있어야 한다. 순서는 다음과 같다.

1. P0의 정확한 부모와 원격 미수행 상태를 기록한다.
2. 실제 21사 publication으로 P1 availability matrix를 만들고 회계 의미 검토를
   요청한다.
3. S01–S08의 evidence field를 만족하는 영속 계약과 fixture manifest를 먼저
   동결한다.
4. executor와 독립 expected-result oracle을 만든 뒤 reference가 반영된 주석
   wireframe을 검토한다.
5. 한 실제 annual end-to-end slice를 통과시킨 뒤 전체 브라우저 범위로 넓힌다.
6. synthetic 오류와 cached future-update fixture를 실제 21사 결과와 분리해
   보고한다.

승인이 필요한 충돌은 새로운 metric 정의·formula·mapping, 비교 view 의미,
quality block 처리의 회계적 확대, 매수 기준, 역사적 cohort membership 주장이다.
그 외 시각 배치와 접근성 세부는 이 계약 안에서 구현 단계가 검증 가능한 선택을
제안할 수 있다.
