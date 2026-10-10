# 50사 연간·분기 스크리닝 소비자 전달 계약

## 상태와 책임

이 문서는 2026-10-10 승인된 소비자 구현 계약이다. 생산자는 50사 연간 v2와
분기 metric publication, M0 품질 증거와 실제 데이터를 소유한다. 소비자는 검증된
발행물만 읽어 dataset v3, service/API/export와 대시보드를 제공한다. SEC 다운로드,
Raw 파싱, Fact 선택, 분기 산술·recast 판단은 소비자에서 실행하지 않는다.

기존 v1/v2 publication, screen revision, run, decision, export와 SQLite 스키마는
수정·이관하지 않는다. v3는 catalog에 추가되는 prospective default이며 과거 run은
원래 dataset publication에 계속 결합된다. 개발·검증은 합성 발행물과 임시 SQLite만
사용한다.

## v3 발행물

Consumer engineering의 양성 wire fixture는 `quarterly-screening-metric-manifest-v1`
manifest SHA-256
`aad6f74c6fdfe23f0663b4adc5b12b49d8b22af09ea130ec06a316e589bcd9c2`인
synthetic v4이다. 이는 schema/consumer 계약 검증용이며 actual 50사 재무 정확성 인수
증거가 아니다. v1–v3 synthetic wire는 모순 재현용 실패 이력으로만 남긴다.

`screening-dataset-v3`는 다음 두 불변 부모를 외부 manifest SHA-256과 publication
ID로 고정한다.

1. 50사 연간 `screening-dataset-v2`; 기존 31개 정의와 annual row를 그대로 제공한다.
2. `quarterly_screening_metric_manifest.json`과 네 payload를 가진 분기 metric
   publication: `quarter_metric_definitions.json`, `quarter_metric_support.json`,
   `quarter_metric_observations.json`, `quarter_period_inventory.json`.

분기 observation의 유일 grain은
`(cik, metric_id, calendar_year, calendar_quarter)`다. 실제 `period_start`, exclusive
`period_end`, `end_convention=EXCLUSIVE`, fiscal year/quarter, period class,
selection view/as-of, exact decimal value/unit, definition version, source kind,
availability/reason, quality/basis와 raw/analytical/derived input lineage를 보존한다.
reader는 부모 file set/hash/ID, 완전한 회사 membership, count, grain, finite decimal,
정의·support 참조와 period inventory를 다시 검증한다. 같은 bucket에 eligible 실제
분기가 둘이면 값을 고르지 않고 명시적 ambiguity row만 허용한다.

bucket은 생산자가 발행한다. 경계 검증은 raw exclusive end에서 UTC 1일을 뺀 포함
종료일을 사용한다. 따라서 raw `2026-04-01`은 2026 Q1이다. inventory는 완료된 최근
8개 bucket `2024Q4`–`2026Q3`와 회사별 available/gap을 모두 포함한다. 2026-10-10
이후 filing은 이 release에 포함하지 않는다.

## 지표와 기간

분기 ID는 annual ID와 충돌하지 않게 `quarter_` 접두사를 쓴다. TTM은 `ttm_`이다.
정의가 각자 `QTD_3M`, `INSTANT` 또는 `TTM`, unit/scaling, category, source kind와
version을 선언한다. source status는 `REPORTED`, `DERIVED_QUARTER`,
`DERIVED_METRIC` 중 하나다.

첫 화면은 annual 50사와 공통 FY다. 분기 요청은 다음 새 정책만 사용한다.

```json
{"mode":"FIXED_CALENDAR_QUARTER_END","calendar_year":2026,"calendar_quarter":2}
```

이는 “2026년 4–6월에 종료한 분기”를 뜻하며 issuer fiscal Q2를 뜻하지 않는다.
선택은 같은 bucket, metric definition/version, unit, definition period class와 as-of가
정확히 일치해야 한다. 누락을 앞뒤 bucket, 최신 회사 분기, annual 또는 YTD로
대체하지 않는다. QTD duration은 기존 75–105일 규칙을 유지하며 COST 112일 Q4는
명시적으로 unavailable이다. INSTANT는 해당 분기말 row만 사용한다.

CFO 같은 현금흐름도 생산자가 승인한 QTD row를 발행하면 사용할 수 있다. Q1 직접
보고 또는 호환 가능한 누적값 차이로 만든 Q2/Q3/Q4는 `DERIVED_QUARTER`와 전체
입력 계보를 보존한다. 소비자가 누적값을 빼지 않는다. TTM은 연속된 호환 QTD 4개,
동일한 non-null basis version, ambiguity/recast break 없음이 생산자 row에 선언된
경우만 사용한다. FY+YTD fallback은 없다. QoQ/YoY/margin/FCF도 생산자가 정의와
결과를 발행한 경우만 노출한다. YoY predecessor는 같은 issuer fiscal year의 이전
fiscal year·같은 fiscal quarter이며 calendar bucket 빼기로 만들지 않는다.

## API·저장·내보내기

기존 endpoint와 annual request/response는 변경하지 않는다. 분기 read surface는
다음과 같다.

```text
GET /api/quarter-periods?dataset_id=ID[&cik=CIK]
GET /api/quarter-series?dataset_id=ID&cik=CIK&metric_id=ID&limit=8
GET /api/quarter-comparison?dataset_id=ID&ciks=A,B&metric_id=ID&calendar_year=Y&calendar_quarter=Q
```

`POST /api/runs`는 새 period policy를 additive하게 받는다. run row와 trace/export는
calendar bucket, issuer fiscal year/quarter, actual dates, period class, source status,
definition/version, as-of와 lineage를 보존한다. 같은 bucket 비교는 definition
version/unit/period class/as-of가 같아야 하며 각 회사 actual dates를 함께 반환한다.

SQLite JSON payload는 새 필드를 그대로 보존하되 SQL migration은 하지 않는다.
기존 annual export canonical payload는 바뀌지 않는다. 분기 JSON/CSV/XLSX는 위
기간·version·trace를 포함하고 exact decimal과 long-text encoding을 보존한다.

## UI 계약

연간이 기본이다. 빈도 전환은 저장된 revision을 몰래 수정하거나 실행하지 않고 새
unsaved draft를 만든다. 분기 selector는 “2026년 4–6월에 종료한 분기”처럼 표시한다.
회사 상세는 고정된 최근 8개 bucket spine과 회사 fiscal label, 실제 시작/종료일,
reported/derived, as-of, gap reason을 보여준다. partial coverage를 숨기지 않는다.
ordinary 화면은 CIK/SIC/raw ID/hash/permission metadata를 노출하지 않으며 브라우저는
값·비율·성장을 계산하지 않는다.

## 검증 gate

- 보호된 v1/v2 publication과 journal의 read-only replay 및 기존 export identity
- annual 50 기본값과 v3 append-only catalog
- exclusive-end bucket 경계, duplicate ambiguity, QTD/YTD 혼동 거부
- missing no-backfill, extended-duration gap, different issuer fiscal labels
- reported/derived/TTM lineage, null-basis TTM unavailable, no UI calculations
- same-bucket comparison compatibility와 unsafe comparison 거부
- 분기 JSON/CSV/XLSX exact period/version/decimal/long text
- restart, keyboard/focus, 1440/1024 browser flow

구현 SHA 동결 뒤 별도 read-only verifier가 합성·actual publication과 M0 품질을
검증하고 lead가 로컬 인수를 결정한다.

## 사용자 시나리오 추적

구현 검증은 `U1 annual 50 browse`, `U2 quarter metric/period discovery`, `U3 explicit
quarter save/run`, `U4 fixed-eight gaps and CFO source kinds`, `U5 fiscal/date-visible
comparison`, `U6 112-day and null-basis TTM holds`, `U7 protected annual restart/export`,
`U8 keyboard and 1440/1024 layout`을 이름 있는 시나리오로 기록한다. 이 목록은 제품
동작 점검표이며 actual 수량·재무 정확성의 독립 인수 증거를 대신하지 않는다.
