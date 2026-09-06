# 기업 내부 회계연도 시계열 뷰

`FiscalTimeSeriesBuilder`는 T4-B가 이미 선택하고 T5가 보존한 값을
한 기업의 회계연도 시계열로 표시하는 읽기 전용 소비자 모델이다. 이는
새 Layer 1/2 발행기가 아니며, 공시를 찾거나 재작성(recast)을 판단하거나
값을 계산하지 않는다.

## 표의 기본 형태

행은 T5의 표준 GAAP 및 기업 custom 개념·전체 차원 signature를 그대로
이어 받는다. 따라서 매출뿐 아니라 비용·현금흐름·재무상태 및 지역/제품
차원 custom detail도 같은 방식으로 표시된다. 불확실한 매핑은 label로
합쳐지지 않고 period-scoped review 행으로 남는다.

열의 정식 키는 다음이다.

```text
CIK + fiscal_year + fiscal_quarter + period_class
```

`FY2025 Q3` 같은 회계 라벨이 주 표시이며, 각 열에는 실제 context
`actual_start_date`, `actual_end_date`/`actual_instant_date`, `duration_days`,
DEI `fiscal_year_end_as_filed`, `fiscal_calendar_version`도 같이 제공된다.
셀은 T5 definition, binding, selected fact, accession, filing date,
snapshot/context/unit, selection view/as-of를 원본 lineage로 유지한다.

## 비교 및 달력 정책

- 입력은 한 CIK, 한 `period_class`, 한 selection view (`LATEST_REPORTED` 기본,
  `AS_FILED` 선택 가능), 한 as-of date만 허용한다. QTD/YTD/FY/INSTANT는
  절대 한 표에서 섞지 않는다.
- `fiscal_calendar_version`은 raw filing의 DEI `fiscal_year_end`에서 파생한
  결산월 식별자다. 날짜 자체는 별도 evidence로 남긴다. 이 방식은 특정
  회사 결산일을 하드코딩하지 않고, 주말 이동이 있는 52/53주 달력의
  일(day) 변동을 결산 체계 변경으로 오판하지 않는다.
- 인접한 이용 가능 열의 실제 기간 일수 차이가 정확히 7일이면
  `DURATION_EXCEPTION_7_DAYS`으로 눈에 보이게 표시한다. 이것만으로 53주
  회계연도라고 확정하지 않는다. 기간일수는 Layer 1과 동일하게 Arelle의
  배타적 종료 경계에서 시작 경계를 뺀 값이다. 값을 일수로
  보정하지 않는다. 7일 초과, 결산월/버전 변경, DEI 결산일 또는 기간
  경계 누락은 `REVIEW_REQUIRED`다.
- `DERIVED_Q4`는 `QTD_3M`의 Q4 열에만 둘 수 있다. 직접 보고 FY는
  `FY` period class의 별도 열/사실로 남으며, 파생 Q4가 이를 대체할 수 없다.

## 역사 누락

요청된 FY/Q 열에 선택된 T5 panel이 없으면 열과 기존 행 교차점은
`MISSING_HISTORY` / `NO_SELECTED_PANEL_FOR_REQUESTED_FISCAL_PERIOD`이다.
새 개념 행이나 숫자, accession, provenance를 만들어 내지 않는다. 따라서
단일 2024 Q3 공시만 적재된 MSFT·AMZN은 요청된 이전 분기를 명시적으로
누락으로 보여 주고, 다년 Layer 1 snapshot이 있는 NVDA·AMD·AAPL은 실제
선택 panel들을 입력으로 넣어 다기간 표를 만든다.

## 운영 입력 경계

기존 5사 운영 cohort의 T1--T4 root는 회사당 기준 공시 한 건이라 역사
source가 아니다. 다년 시계열은 이미 검증된 immutable Layer 1 snapshot을
명시적으로 모아 별도 T1--T4 operational publication으로 발행한 뒤,
그 root에서 T4-B/T5 panel을 얻어 이 뷰에 공급한다. Raw snapshot을 복사하거나
변경하지 않는다. `fiscal_year_end`는 그 선택 panel의 source Layer 1
`filing` record에서 공급한다.

## 동일 셀 후보의 분석 정책

T4가 선택한 Fact를 피벗에 연결할 때, 회사 canonical concept, **전체** 차원,
unit, period class, comparative family가 같은 후보를 같은 행으로 모은다.
원래 graph 경로와 `STATEMENT`/`EXPLORATION_DETAIL` 표시 위치는 행 identity가
아니며 `candidate_lineage`에 모두 보존한다. 따라서 같은 Fact의 반복 탐색은
표에서 한 숫자가 된다. Custom/차원 행은 총액과 합쳐지지 않는다.

같은 실제 기간·같은 선택 공시 버전 내에서는 PRE 관계의 실제 concept
membership과 primary role 판별로 얻은 손익·재무상태·현금흐름·자본변동표
근거가 있는 후보를 우선하고, 없으면 주석 후보를 쓴다. T5의 root 표시
(`line_scope=STATEMENT`)만으로 본문 재무제표 근거라고 인정하지 않는다.
이 근거는 concept의 PRE 배치이며 개별 inline Fact의 화면 좌표를 증명하는
것은 아니다. 같은 concept을 공유해 우선순위를 구별하지 못하면 값 동등성
검사로 이어진다.

동순위 숫자가 같으면 하나의 값과 모든 Fact/context/path 근거를 함께
제공한다. 다른 값이면 해당 셀만 `UNAVAILABLE`로 남긴다. 서로 다른 실제
기간이나 서로 다른 선택 공시 버전은 placement 순위로 덮어쓰지 않는다.
T4의 기준일/수정공시 선택 정책은 그대로 유지된다. 대표 lineage 정렬은
이미 숫자 동등성을 확인한 후에만 수행하며 숫자 선택 근거로 쓰지 않는다.
이 규칙은 분석 모델 정책이며 Excel/API에서 별도 재선택하지 않는다.

입력 panel이 존재하지만 특정 항목이 없으면 `NOT_REPORTED`이고, 기간
panel 자체가 없을 때에만 `MISSING_HISTORY`다. 결산월 기반
`fiscal_calendar_version`은 관측된 DEI 월 signature일 뿐 완전한 회계달력
regime 또는 회계기준 동등성을 증명하지 않는다.
