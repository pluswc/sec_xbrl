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

### 8abb4c 독립 FAIL 후 선택 보고값 적격성 교정

`8abb4c27416cda4adb8f63549a4c07833f76705e` 독립 검증에서 이전 식별자·기간·scope·
금액·TTM 교정은 통과했지만, 선택된 REPORTED anchor의 BLOCK과 mapping 검토
상태를 early return이 건너뛰는 결함이 남았다. source BLOCK이 관측 행에서
숨겨지면 잘못된 screening PASS로 이어졌다. 리드는 같은 단일 작성자에게
공통 선택 입력 적격성 검사와 회귀 테스트만 재개하도록 승인했다.

보고값도 선택된 metric identity에 대한 검토·ambiguity를 무시할 수 없다.
선택 출처가 BLOCK인데 관측 행이 차단 상태를 보존하지 않으면 발행물을 거부한다.
관측 행도 BLOCK 또는 quality_blocking을 명시한 알려진 보고값은 그대로 보존하며
실행에서는 UNDETERMINED로 남는다. 소비자는 source 상태를 임의로 정리하거나
UNAVAILABLE 후보의 누락 식별자를 만들어 넣지 않는다.

리드의 추가 범위 결정: REPORTED의 `mapping_review_required`, `mapping_uncertainty`,
`ambiguity`, `ambiguous`, 명시적 `compatibility_failure`는 선택된 binding의
유효성에 관한 부적격 상태로 거부한다. 그러나 비교에 관한 `basis_break`,
`structural_break`, `recast_break`, `continuity_break`, `recast_review_required`와
`comparability_status=REVIEW`는 알려진 보고값 자체를 지우지 않는다. null basis도
보고값에 허용된다. 명시적 품질 차단은 그대로 유지한다. 동일 비교 break는
AVAILABLE DERIVED_QUARTER/TTM 입력에서는 계속 거부하며, 단순 null basis의
보고값·승인된 arithmetic quarter 예외를 TTM의 non-null basis 요건으로 확대하지 않는다.

이 후속 교정의 자체 전체 screening/UI 검사는 **251 passed / 0 skipped**
(7.50초, local loopback 허용)이며, 이전 207개에 선택 보고값 적격성·품질 보존·
비교 전용 검토 메타데이터·기존 null basis 경계 회귀 44개를 추가했다. Ruff와
`git diff --check`가 통과했다. 기존 원본·잔여 probe 및 8abb 독립 extended probe를
새 합성 복사본에서 재실행했다. 잘못된 선택 source BLOCK/mapping 상태를 포함한
음성 사례는 거부했고, 유효한 TTM 양성은 재계산 없이 그대로 수용했다.
증거 디렉터리는 `/tmp/quarter-consumer-eligibility`다. 원본 v5 fixture, UI/service,
생산자와 실제 journal은 수정하지 않았다. 새 동결 SHA의 독립 재검증과 로컬 인수는
대기이며 이전 FAIL 판단을 지우지 않는다.

### 2026-10-10 core 인수와 generic prepared-input 확장

리드는 `8c1aa2961ce26e5d2c812943181e70ba59778c7b`의 source 검증과 fresh-checkout
portability를 로컬 인수했다. 독립 보고서 SHA-256은
`528163ee4a6303a43e49694d08b1a04d975313ac95ba7a003ed1024c2f27162f`다.
이 판단은 실제 50사 재무 publication, native rollout, main 병합을 포함하지 않는다.
후속 승인 범위는 기존 R1의 FCF·마진·QoQ·YoY·동일 시점 비율을 생산자가 준비한
`DERIVED_METRIC`으로 읽기 위한 입력 검증이다. 반복 재작업 후 지정된 단일 구현
작성자가 계속 담당하고, 별도 읽기 전용 검증과 리드 인수는 새 SHA별로 수행한다.

정의의 `input_contract`는 아래 필드를 정확히 선언한다. 버전은
`quarter-derived-input-scope-v1`, `basis_policy`는
`ARITHMETIC_ONLY_NOT_RECAST_VALIDATED`다. `source_lineage.compatibility_policy`도
같은 문자열이며 `derivation_rule_version`은 definition의 `rule_version`과 같다.

| kind | 순서대로 선언할 input_role | value_constraint | denominator_policy |
| --- | --- | --- | --- |
| SAME_PERIOD_DIFFERENCE | CFO, CAPEX | FINITE, NONNEGATIVE | NOT_APPLICABLE |
| SAME_PERIOD_RATIO, QTD | NUMERATOR, DENOMINATOR | FINITE, POSITIVE | STRICTLY_POSITIVE |
| SAME_PERIOD_RATIO, INSTANT | NUMERATOR, DENOMINATOR | NONNEGATIVE, POSITIVE | STRICTLY_POSITIVE |
| ADJACENT_FISCAL_QUARTER_GROWTH | CURRENT, PRIOR | NONNEGATIVE, POSITIVE | STRICTLY_POSITIVE |
| SAME_FISCAL_QUARTER_YOY_GROWTH | CURRENT, PRIOR | NONNEGATIVE, POSITIVE | STRICTLY_POSITIVE |

`inputs`의 각 선언은 `input_role`, `metric_id`, `value_constraint`만 가진다.
`source_lineage.derivation_inputs`에는 같은 순서의 역할과 완전한 prepared 관측
레코드를 넣는다. `value_constraint`는 정의에만 두며 관측 레코드에 복제하지 않는다.
관측 ID는 기존 wire의 `observation_id`다. 같은 publication 안에서 동일 ID의
레코드는 `input_role`만 제외한 canonical JSON 내용 전체가 같아야 한다. 다른 값·
scope·품질을 같은 ID에 담을 수 없다. 정의·버전, 가용성, quality, 실제 기간,
unit, basis, view/as-of, canonical metric ID와 선택 계보를 상위 행에서 추정하지 않는다.

입력은 AVAILABLE REPORTED 또는 governed DERIVED_QUARTER다. 후자는 자체
`derived_metric_id`와 승인된 누적 raw 입력까지 검증한다. generic derived를 다시
입력으로 쓰거나 TTM·FY·YTD로 대체하지 않는다. 선택 PRE/CAL 후보를 입력으로
추정하지 않으며, 누락·부적격 입력은 생산자가 UNAVAILABLE로 발행한다. 소비자는
금액 차이·비율·성장률을 계산하지 않고 생산자가 제공한 exact decimal 값을 보존한다.
부호 검사는 기존 R1의 적격성 제약만 확인한다.

두 입력은 CIK, dimensions, 분석 view/as-of가 같고 USD MONEY여야 한다. 선택
입력 경로에 quality BLOCK, mapping/ambiguity 또는 명시적 continuity/basis/recast
break가 있으면 AVAILABLE generic 결과를 거부한다. null basis는 위 arithmetic
정책 아래 양쪽 모두 null일 때 허용하며, 선언한 non-null basis와 structural/recast
version은 서로 및 출력과 일치해야 한다. 이를 recast 또는 회계 동등성 인수로
표현하지 않는다. TTM은 별도의 네 연속 QTD·non-null 동일 basis 계약을 유지한다.

SAME_PERIOD 두 입력은 출력과 실제 시작·끝·exclusive end·period class 및 fiscal
좌표가 같다. QTD는 75–105일 범위다. INSTANT는 start=null, exclusive period_end,
선택 raw anchor의 duration_days=null 및 context_instant_date=period_end를 보존한다.
차이는 QTD MONEY USD, 비율·성장률은 정의에 명시한 정확한 PERCENT/RATIO 단위를
쓴다. 비율 입력 USD를 출력 dimensionless 단위와 같다고 요구하지 않는다.

성장률은 같은 지표 정의·버전·단위를 사용한다. CURRENT는 출력 기간/fiscal 좌표와
같다. QoQ PRIOR는 실제 날짜가 붙어 있는 이전 issuer fiscal quarter이고 Q1의
이전 분기는 전 fiscal year Q4다. YoY는 이전 fiscal year의 같은 fiscal quarter다.
calendar bucket에서 1년을 빼서 판단하지 않는다. 명시된 company_canonical_concept_id는
양쪽 선택 경로에서 일관되어야 하며 QName·label로 binding을 추정하지 않는다.
8개 출력 spine보다 오래된 YoY 선행값은 완전한 nested prepared input으로만 존재할
수 있으며 출력 spine을 늘리지 않는다. 출력 filed date는 사용 입력의 최대값,
report date는 CURRENT/동일 기간 endpoint의 값이고 모든 입력은 같은 cutoff 안이다.

양성·음성 사례는 추적 v5 fixture의 임시 복사본에 명시적으로 labelled synthetic
정의와 raw/derived 입력을 추가한다. v5 원본과 non-bindable synthetic parent는
실제 자료로 바꾸지 않는다. 새 테스트는 세션 `/tmp` 입력 없이 재현된다.

```bash
PYTHONPATH=src python -m pytest -q tests/screening/test_quarterly_generic_metrics.py
PYTHONPATH=src python -m pytest -q tests/screening tests/test_screening_ui.py
ruff check --no-cache src/sec_xbrl/screening/quarterly.py tests/screening/test_quarterly_generic_metrics.py
```

이 확장은 구현 및 자체 검증 단계다. 동결 후 독립 검증과 로컬 인수는 대기이며,
producer v6·실자료 재무 계산·UI 변경·원격 PR/CI/병합은 이 slice의 범위 밖이다.

이 slice의 최종 자체 검증은 **335 passed / 0 skipped**(screening/UI 전체 선택,
7.98초)다. 기존 core 251개와 generic 계약 회귀 84개를 포함한다. 세션의
`/tmp/universe50-quarterly-*` 파일 접근을 차단한 별도 실행에서 quarterly
consumer/source/generic **224 passed**를 확인했다. Ruff check/format check와
`git diff --check`가 통과했다. 원본 및 추적 v5 manifest SHA는
`84e652322e570f4768c278fa924aaf6c1de98f1158be0d162b9be0a488fa359a`로 유지됐다.
임의 producer 값을 보존하는 다섯 종류의 합성 예시는 `/tmp/quarter-consumer-generic`
아래 별도 복사본으로 내보냈다. 해당 경로는 재현의 필수 입력이 아니며 테스트는
추적 v5에서 예시를 재구성한다. consumer quarterly validator 외 product source,
UI·service·wrapper 및 실제 journal에는 변경을 하지 않았다. native browser,
전체 프로젝트 suite, actual 재무 인수나 원격 CI를 수행했다고 주장하지 않는다.

### 6cccbdb 독립 FAIL 후 G1/G2 교정

`6cccbdb42b8be7e253459d1254ee7c1652750a5c`의 독립 검증은 두 경계에서 FAIL이었다.
보고서 SHA-256은 `28bf011cfbedb746c83a06df1b880e9fe139c93c50cecc91f2d4c0cf163c7b3e`다.
G1은 PERCENT kind를 유지한 채 정의와 출력 unit을 모두 USD로 바꾸면 통과하는
문제였고, G2는 새 observation ID 아래 동일 Raw source의 금액을 바꾸면 기존
prepared ID 검사만으로 검출하지 못하는 문제였다. 리드는 같은 단일 작성자에게
이 두 검증과 회귀 테스트만 재개하도록 승인했다.

AVAILABLE generic definition은 `canonical_value_scale`을 정확한 문자열 `"1"`로
선언해야 한다. MONEY는 USD, PERCENT는 PERCENT 단위만 허용한다. 명시적
`SAME_PERIOD_RATIO` 계약과 `unit_kind=RATIO`가 함께 있을 때만 `unit=RATIO` 또는
문자열 `"1"`을 허용하며 이는 배율을 곱하지 않은 dimensionless ratio다. 별도
input-contract 필드를 만들거나 값·단위·배율을 변환하지 않는다. 성장률은 PERCENT,
차이는 MONEY/USD 계약을 유지한다. 이 필드는 generic 정의의 임시 합성 복사본에만
추가하며 기존 reported/core 정의와 불변 v5 fixture를 변경하지 않는다.

선택된 REPORTED raw anchor는 prepared 관측 ID와 별도로 publication 전체에서
불변 identity를 검증한다. `(CIK, source_id)` alias와 `(CIK, source_filing_id,
source_fact_id, 선언된 source_file_id/source_file/source_snapshot_id)`의 qualified
fact identity를 등록한다. 동일 identity는 exact Decimal 의미의 금액, context,
QName/namespace, unit/unit ID, dimensions, 실제 기간과 instant, filing/report 날짜,
accession·filing·source origin이 같아야 한다. `1`과 `1.0` 같은 Decimal-equal 표현은
허용한다. 분석 selection view/as-of, 품질, mapping/basis와 input-role wrapper는
Raw 내용으로 비교하지 않는다. 그 메타데이터의 유효성은 기존 prepared 입력
검증이 별도로 담당한다. 같은 Raw fact가 다른 prepared ID·분석 view·비차단 품질
메타데이터로 재사용되는 정상 사례를 보존한다.

등록은 검증된 선택 경로의 raw anchor에만 적용한다. top-level 보고값과 generic,
M8 derived-quarter, TTM의 하위 선택 입력을 포함하고 PRE/CAL·candidate evidence는
포함하지 않는다. 누락된 unavailable 후보 식별자를 만들어 채우거나 Raw 저장소를
조회하지 않는다. 같은 observation ID의 완전한 prepared-record 일치 규칙도 유지한다.

교정 자체 검증은 **374 passed / 0 skipped**(screening/UI, 8.25초)이며, 경로 접근
차단을 적용한 quarterly consumer/source/generic 선택은 **263 passed**다. generic
검증은 122개이며 기존 core 및 TTM 중첩 Raw 모순 회귀가 포함된다. 독립 원본
probe 11개를 새 복사본에서 재실행하여 기대 결과와 불일치가 없었다. Ruff
check/format check와 `git diff --check`가 통과했다. 기존 TTM 양성 합성 helper는
Revenue Raw fact ID를 보존한 채 CFO QName을 만들던 문제를 고쳐, 새 합성 CFO
fact/source ID와 선택 ID를 명시했다. 권위 있는 v5 fixture는 그대로다.

재현 증거와 labelled synthetic 예시는 `/tmp/quarter-consumer-g1g2`에 있으며
fresh checkout의 필수 입력이 아니다. source 변경은 quarterly validator에 한정된다.
이 기록은 자체 검증이며 새 동결 SHA의 독립 재검증·리드 인수, actual 재무자료
인수·native rollout·원격 작업 완료를 뜻하지 않는다.

### 4aabf54 독립 FAIL 후 Raw origin identity 우선순위 교정

`4aabf543abefda75ec4e03a1a77365f0fe6d1778`의 독립 검증은 G1과 원래 G2 모순을
통과했지만, 같은 snapshot/file/filing/fact ID에서 선택적 `source_file` 이름만
바꾸거나 생략하면 다른 identity로 분리되는 잔여 G2를 발견했다. 독립 보고서
SHA-256은 `8509a2ba38c8593061dea971bdf75c95988c0f8f2d42879052073f4a08682a19`다.
리드는 해당 qualifier 우회만 같은 단일 작성자에게 반환했다.

이 절은 앞 절의 origin tuple 설명을 다음 안정된 ID 우선순위로 정정한다.

1. `source_snapshot_id`가 있으면 `(CIK, snapshot ID, source_fact_id)`를 쓴다.
   같은 immutable snapshot의 fact는 다른 파일명·file ID·filing metadata로
   새 identity가 되지 않는다.
2. snapshot ID가 없고 `source_file_id`가 있으면
   `(CIK, source_filing_id, source_file_id, source_fact_id)`를 쓴다.
3. 둘 다 없으면 `(CIK, source_filing_id, source_fact_id)`를 쓴다.

선택적 `source_file` 경로는 identity 구성 요소가 아니며 기존 intrinsic origin
metadata 일치 검사에 남는다. `(CIK, source_id)` alias 검사와 prepared observation
ID의 완전한 내용 일치도 유지한다. 실제로 다른 snapshot/file/fact 출처를 합치거나
같은 Raw 값의 Decimal 표현·분석 view 차이를 금지하지 않는다. snapshot 자체가
바뀐 경우의 해석은 이번 잔여 FAIL 또는 추가 정책 변경 범위가 아니다.

자체 집중 검사와 세션 wire 접근 차단 검사는 각각 **280 passed / 0 skipped**이며
새 identity 우선순위 회귀 17개를 포함한다. generic 139개와 기존 quarterly
consumer/source 141개가 모두 통과했다. 독립 원본의 파일명 변경·누락 음성 2개는
거부됐고 Decimal/view 재사용·구별되는 실제 origin 양성 2개는 수용됐다. 원본
스크립트의 changed-snapshot-only 사례는 리드가 이번 FAIL 근거에서 제외했으며,
기존 수용 결과와 스크립트의 과거 expected 값은 증거에서 숨기거나 바꾸지 않았다.
이전 G1/G2 원본 11개 probe도 모두 기대 결과와 일치했다. Ruff check/format check와
`git diff --check`가 통과했다. 증거는 `/tmp/quarter-consumer-origin`이며 테스트는
추적 fixture로 재현하므로 이 세션 경로가 필요하지 않다.

이 좁은 교정에서는 전체 screening/UI 374개를 재실행했다고 주장하지 않는다.
그 결과는 이전 `4aabf54`의 자체 검증 기록이다. UI·producer·단위·재무 계산 정책과
불변 v5에는 변경이 없다. 새 동결 SHA의 독립 재검증과 로컬 인수는 별도로 대기한다.

### 2026-10-13 annual input/display window 소비자 호환성

독립 LIGHT 검토는 consumer의 metric config 정규화가 producer가 승인한 회사별
`input_years`/`display_years`를 버려 정상적인 5 FY 입력·4 FY 표시 발행물을
`ScreeningMetricReader.verify_all()`에서 거부함을 확인했다. dataset v2와 v3도 이
reader를 경유하므로 같은 문제가 이어졌다. 근거 보고서의 SHA-256은
`54ec783d0a667926bd36262b9603de9e4c3be96c9b3354791f448d3c609dff0e`, config
normalization probe의 SHA-256은
`1fc18b60158dd68ee7e9d929b0f455a3e5f1db7fc370a5a0fb4fae35d2d84d90`이다.

승인된 호환 범위는 producer에서 이미 인수된 annual window 동작을 기존
`metrics/screening.py`에만 맞추는 것이다. 회사별 두 필드는 함께 있을 때만
보존한다. 입력은 최대 5개, 표시는 최대 4개의 오름차순 중복 없는 정수 FY이며,
표시는 입력의 최신 suffix다. prepared analysis 연도는 입력과 정확히 일치해야
한다. 모든 입력으로 기존 governed 공식을 재계산한 뒤 표시 FY만 발행하며 source
manifest에도 같은 두 목록을 보존한다. reader의 offline recomputation은 config,
source, prepared membership과 결과를 같은 규칙으로 검증한다. 필드가 없는 legacy
발행은 prepared 연도 전체를 입력·표시로 사용하고 기존 manifest shape을 유지한다.

dataset v2/v3, 분기 의미, 지표 정의·ID, formula, 기본 기간, UI 계산에는 변경이
없다. 합성 테스트는 windowed metric publication의 v2/v3 prepare 및 재개방,
legacy 전체 연도, 오래된 predecessor의 계산 전용 사용, 비정상 목록·source drift·
prepared 기간 축소 거부를 확인한다. 이는 local 구현 후보 상태이며 동결 SHA의
독립 검증과 lead 인수는 대기다. actual first-five/50 재무 payload는 읽거나
발행하지 않았고 두 범위 모두 `NOT_READY`다. 원격 push·PR·main 병합도 미수행이다.
