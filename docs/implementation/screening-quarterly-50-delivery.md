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
`84e652322e570f4768c278fa924aaf6c1de98f1158be0d162b9be0a488fa359a`인
synthetic v5이다. 이는 schema/consumer 계약 검증용이며 actual 50사 재무 정확성 인수
증거가 아니다. v1–v4 synthetic wire는 모순 재현용 실패 이력으로만 남긴다.

Reader는 파일 hash만 신뢰하지 않는다. CIK membership hash, 정확한 8개 연속 완료
calendar bucket, CIK×definition support grain과 집계, definition의 period/source/basis,
actual 날짜·filing cutoff·as-of·source anchor를 다시 검증한다. Dataset v3는 quarterly
manifest의 `annual_parent`를 annual dataset v2의 `sources.metrics` publication ID와
manifest hash에 직접 결합하며 cutoff와 membership도 같아야 한다. 화면의 선택 bucket
coverage와 전체 8개 bucket coverage는 별도 필드로 제공한다.

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

## 2026-10-10 잔여 F1 교정과 source scope 계약

`ce01d0ceb45c243c72277afaca34c88fb525f61f` 독립 재검증은 F2–F6 PASS,
F1 잔여 FAIL이었다. 필드 이름만 검사하여 빈 source identity, 출처와 관측값의
범위 불일치, 미래 source filing, 세 입력 TTM을 허용했다. 리드는 반복 재작업
근거로 공통 전달 절차의 구현 역할 상향을 승인했다. 이전 작성자는 동결하고
별도 GPT-6 Astra 구현 세션을 단일 source writer로 배정했다. 독립 검증은
구현 세션과 다른 읽기 전용 세션이 맡으며 자체 테스트는 독립 PASS나 로컬 인수를
대신하지 않는다.

리드의 source-scope 결정은 다음과 같다. 실제 분석 view는 `AS_FILED` 또는
`LATEST_REPORTED`이며 원자료와 파생값 구분은 `source_kind`로 표현한다.
과거 합성 v4의 `EXISTING_REPORTED` / `RECAST_DERIVED` 문자열은 실제 recast
의미를 부여하지 않는다. v4 원본은 불변 실패 이력으로 보존하고, 명시적 범위가
있는 후속 합성 wire를 양성 검증 입력으로 사용한다.

- AVAILABLE observation은 canonical metric, full dimensions, 실제 period class,
  분석 view와 as-of를 명시한다. 각 선택 입력도 CIK/view/as-of/metric/dimensions/
  unit/mapping/basis를 직접 선언한다. 소비자는 누락 범위를 상위 행에서 추정하지 않는다.
- REPORTED의 선택 raw anchor는 nonempty fact/context/QName/namespace/unit와
  filing/source ID를 가지며 행의 실제 기간·공시일·보고일·basis·measurement scope와
  일치한다. source value와 reported value의 정확한 일치는 검사하지만 계산하지 않는다.
- DERIVED_QUARTER는 승인된 두 누적 입력의 scope, 동일 fiscal start, 허용된
  period pair와 output residual dates를 검사한다. 출력과 입력은 동일 분석 view를
  보존한다. `ARITHMETIC_ONLY_NOT_RECAST_VALIDATED` 같은 품질·basis 한계를
  recast clearance로 바꾸지 않는다.
- TTM은 정확히 네 개의 유효 QTD 입력, 전체 연속 span, 동일한 non-null basis와
  scope를 요구한다. 입력이 governed DERIVED_QUARTER면 그 자체의 derived ID와
  승인된 하위 누적 입력 계보도 검사한다. FY/YTD 대체, EPS·shares·ratio의 단순
  합산, 소비자 금액·비율 계산은 허용하지 않는다.
- 선택된 값의 계보만 source anchor로 검증한다. PRE/CAL·후보 evidence의 accession을
  선택된 입력으로 오인하지 않는다. UNAVAILABLE 행은 알려진 후보와 사유를 그대로
  유지하며 synthetic ID나 clearance를 만들어 채우지 않는다.

재현 명령은 프로젝트 Python 환경에서 다음과 같다. 네트워크 없이 추적 합성 fixture와
임시 SQLite만 사용한다.

```bash
PYTHONPATH=src python -m pytest -q tests/screening tests/test_screening_ui.py
ruff check --no-cache src/sec_xbrl/screening/quarterly.py tests/screening/test_quarterly_source_validation.py
```

이 교정은 소비자 검증 경계의 구현이다. 실제 21/50사 재무 publication 인수,
실제 journal 운영, main 병합 또는 원격 발행 완료를 뜻하지 않는다.

AVAILABLE TTM의 definition은 `input_metric_id`로 QTD 입력 지표를 명시한다.
소비자는 이름의 접두사로 입력 지표를 추정하지 않는다. 합성 v5의 TTM은
UNAVAILABLE이며 이 입력 지표 선언이 없다. AVAILABLE 양성 회귀 fixture는
분리된 복사본에 `input_metric_id=quarter_revenue`를 명시한다. 선택된 파생 분기
입력의 자체 식별자는 생산자와 같은 `derived_metric_id`다.

### 교정 자체 검증 기록

2026-10-10 구현 세션의 전체 screening/UI 선택은 **207 passed / 0 skipped**,
그중 quarterly consumer/source 집중 선택은 **96 passed**다. 최초 sandbox 실행은
202 passed와 loopback socket 생성 권한 오류 5건이었으며, 승인된 local loopback
환경에서 전체 선택을 재실행하여 207건 모두 통과했다. Ruff와 `git diff --check`도
통과했다. 기존 독립 원본·잔여 probe를 v5의 별도 복사본에 적용하여 모든 음성
사례를 거부했다. 알려진 품질 BLOCK의 UNDETERMINED 처리와 선택 bucket coverage를
다시 확인했다. 임시 재현 증거는 `/tmp/quarter-consumer-scope-v5`이며 규범적 계약이나
fresh checkout 테스트의 필수 입력이 아니다.

이는 구현자의 자체 검증 결과다. 동결 SHA에 대한 별도 read-only 검증과 lead의
로컬 인수는 아직 대기다. 화면 소스는 수정하지 않았고 기존 1440/1024 native
검증을 이번 교정에서 재수행했다고 주장하지 않는다. 전체 프로젝트 suite, actual
회사 재무 인수, 원격 CI·PR·병합도 이 기록의 범위 밖이다.
