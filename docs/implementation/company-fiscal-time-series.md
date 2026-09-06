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
  `DURATION_EXCEPTION_53_WEEK`으로 눈에 보이게 표시한다. 값을 일수로
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
