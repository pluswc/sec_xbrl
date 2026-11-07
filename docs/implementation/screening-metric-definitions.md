# 스크리닝 R1 지표 정의 계약

## 1. 공통 표기

기준일은 **2026-10-09 KST**다. `R_t`는 현재 FY 매출, `R_t-1`은 직전 FY 매출,
`GP`, `OI`, `NI`, `CFO`, `CAPEX`는 같은 FY의 직접 보고 선택값이다. `CA`, `CL`,
`L`, `A`, `E`, `D`, `CASH`는 같은 연도말 instant의 직접 보고 선택값이다.

money는 USD exact decimal, percentage/ratio는 `%` 단위의 percentage point다.
reported 값과 derived 값은 별도 stable ID와 source kind를 가진다.

percentage 산술 rule `screening-decimal-rational-v1`은 exact numerator를 만든 뒤
precision 34, `ROUND_HALF_EVEN` local context에서 한 번 나눈다. YoY numerator는
`(R_t-R_t-1)×100`, 나머지는 `numerator×100`이다. FCF와 net debt subtraction은
두 Decimal을 공통 exponent의 정수로 바꿔 정확히 뺀다. fixed-point 출력은 소수부
뒤 0만 제거하고 계산된 `-0`을 `0`으로 정규화한다. reported input은 반올림하지
않는다.

## 2. reported 지표 21개

### FY duration 12개

| metric ID | 사용자 label | category | exact profile row |
| --- | --- | --- | --- |
| `revenue` | 매출 | GROWTH | `revenue` |
| `cost` | 매출원가 | PROFITABILITY | `cost` |
| `gross_profit` | 매출총이익 | PROFITABILITY | `gross_profit` |
| `research` | 연구개발비 | OTHER_REPORTED | `research` |
| `operating_income` | 영업이익 | PROFITABILITY | `operating_income` |
| `net_income` | 순이익 | PROFITABILITY | `net_income` |
| `cfo` | 영업활동 현금흐름 | CASH_FLOW | `cfo` |
| `capex` | 유형자산 취득 지출 | CASH_FLOW | `capex` |
| `cfi` | 투자활동 현금흐름 | CASH_FLOW | `cfi` |
| `cff` | 재무활동 현금흐름 | CASH_FLOW | `cff` |
| `repurchases` | 자사주 취득 지출 | OTHER_REPORTED | `repurchases` |
| `stock_compensation` | 주식보상비용 | OTHER_REPORTED | `stock_compensation` |

EPS는 unit와 의미가 다르므로 제외한다.

### 연도말 INSTANT 9개

| metric ID | 사용자 label | category | exact profile row |
| --- | --- | --- | --- |
| `cash` | 현금 및 현금성자산 | FINANCIAL_STABILITY | `cash` |
| `assets` | 자산 | FINANCIAL_STABILITY | `assets` |
| `current_assets` | 유동자산 | FINANCIAL_STABILITY | `current_assets` |
| `receivables` | 매출채권 | OTHER_REPORTED | `receivables` |
| `inventory` | 재고자산 | OTHER_REPORTED | `inventory` |
| `liabilities` | 부채 | FINANCIAL_STABILITY | `liabilities` |
| `current_liabilities` | 유동부채 | FINANCIAL_STABILITY | `current_liabilities` |
| `debt` | 직접 보고 결합 차입금 | FINANCIAL_STABILITY | `debt` |
| `equity` | 자본 | FINANCIAL_STABILITY | `equity` |

shares는 monetary 스크리닝 범위가 아니므로 제외한다. `liabilities`는 부채총계이며
이자부 차입금 `debt`와 다른 지표다.

`revenue`, `cfo`, `operating_income`, `net_income`은 v1과 exact semantic
compatibility가 있으므로 definition version `annual-core-reported-v1`을 유지한다.
나머지 reported 지표는 `screening-reported-monetary-v1`이다.

## 3. derived 지표 10개

| metric ID | label / formula | period | 핵심 gate |
| --- | --- | --- | --- |
| `revenue_yoy` | 매출 전년 대비 성장률 `(R_t / R_t-1 - 1) × 100` | FY | consecutive year, end gap 330–400일, 양쪽 duration 350–378일, 같은 standard QName/family/type/unit/dims, `R_t-1 > 0`, `R_t >= 0` |
| `gross_margin` | 매출총이익률 `GP / R × 100` | FY | 같은 actual start/end, unit/dims/basis/filing, typed primary IS, `R > 0` |
| `operating_margin` | 영업이익률 `OI / R × 100` | FY | gross margin과 같은 gate, 손실 numerator 허용 |
| `net_margin` | 순이익률 `NI / R × 100` | FY | gross margin과 같은 gate, `NetIncomeLoss` exact profile, attribution 추측 금지 |
| `standardized_fcf` | 표준화 FCF(영업현금흐름−유형자산취득지출) `CFO - CAPEX` | FY | 같은 actual bounds/unit/dims/basis/filing, typed primary CF, `CAPEX >= 0` |
| `fcf_margin` | 표준화 FCF 마진 `standardized_fcf / R × 100` | FY | FCF와 revenue가 같은 기간/basis/filing; CF와 IS role URI 자체는 달라도 각 typed primary evidence 필요, `R > 0` |
| `current_ratio` | 유동비율 `CA / CL × 100` | INSTANT | 같은 연도말 instant/unit/dims/basis/filing, typed BS, `CL > 0` |
| `liabilities_to_equity` | 부채비율 `L / E × 100` | INSTANT | 같은 gate, `E > 0`; 음수·0 자본은 business unavailable |
| `liabilities_to_assets` | 총부채/자산 `L / A × 100` | INSTANT | 같은 gate, `A > 0` |
| `net_debt` | 순차입금 `D - CASH` | INSTANT | 직접 보고 combined debt와 cash, 같은 scope; 아래 exact-QName note allowance 외에는 typed BS, split debt 합산·liabilities 대체 금지 |

`revenue_yoy`는 QOQ, TTM 또는 CAGR이 아니다. 364/365/366/371일 normal FY를
허용하되 실제 duration 차이를 warning에 보존한다. short transition 또는
recast 검증이 없는 의미 변경은 unavailable이다.
YoY observation의 표시 period는 현재 FY의 actual start/end다. ordered input
provenance에는 현재·직전 FY 각각의 fiscal year, period class, actual start/end,
observation ID와 exact input value를 모두 보존한다. 현재 FY input 자체가 없으면
observation period를 직전 FY로 대신 채우지 않는다.

margin은 발행사가 직접 보고한 non-GAAP margin이라고 표시하지 않는다. FCF도
발행사 FCF 정의와 동등하다고 주장하지 않는다. SEC staff의 non-GAAP C&DI
102.07이 uniform FCF definition을 주지 않는 점을 반영해 항상 위 표의 한국어
공식 label과 input lineage를 함께 보존한다.

`net_debt` rule version은 debt leg에만 제한된
`EXACT_STANDARD_COMBINED_DEBT_NOTE_ALLOWANCE`를 가진다. exact standard QName
`us-gaap:DebtLongtermAndShorttermCombinedAmount`, `monetaryItemType`, concept
period type `INSTANT`, unique undimensioned selected reported fact를 요구한다. debt와
cash는 같은 CIK·actual instant·USD·basis·source filing이어야 하며 cash는 typed
primary BS evidence를 유지해야 한다. debt가 note-disclosed이면 source locator와
note allowance를 formula lineage에 남긴다. custom concept, borrowing commitment,
split debt 합산, liabilities 치환, label matching은 허용하지 않는다. 실제 pair가
같은 filing/instant를 만족하지 않으면 unavailable이다.

## 4. 불가 사유 최소 집합

producer는 적어도 다음 business reason을 구분한다.

```text
MISSING_INPUT
MULTIPLE_CANDIDATES
INPUT_NOT_REPORTED
INPUT_NOT_FINITE
INPUT_SOURCE_KIND_UNSUPPORTED
UNIT_NOT_USD
UNIT_MISMATCH
MAPPING_REVIEW_REQUIRED
NON_STANDARD_CONCEPT
QUALITY_BLOCKED
DIMENSION_MISMATCH
PERIOD_MISMATCH
COMPANY_MISMATCH
SOURCE_SCOPE_MISMATCH
SOURCE_FILING_MISMATCH
PRIMARY_STATEMENT_EVIDENCE_MISSING
BASIS_INCOMPATIBLE
NON_POSITIVE_DENOMINATOR
NEGATIVE_NUMERATOR
NEGATIVE_EQUITY
CAPEX_SIGN_UNCERTAIN
NON_CONSECUTIVE_FISCAL_YEAR
FY_DURATION_OUT_OF_RANGE
FISCAL_END_GAP_OUT_OF_RANGE
SEMANTIC_IDENTITY_MISMATCH
DIRECT_COMBINED_DEBT_UNAVAILABLE
```

여러 이유가 있으면 deterministic 우선순위와 전체 진단 목록을 보존한다. business
catalog는 일반 사용자 label을 우선 표시하고 source IDs·QName·version·hash는
상세 provenance에서 조회하게 한다.


## 2026-11-08 총부채 공시 행 검증 후보

동일 공시의 주 재무상태표에서 유일한 `us-gaap:Liabilities`를 확인할 수
있으면 보고값을 우선한다. 보고값이 없을 때만 동일 기업·실제 기말의 연결
USD 자료로 오프라인 후보를 검증한다. 자산과 부채·자본 합계가 같고,
자산에서 총자본을 차감한 값이 같은 역할의 CAL 직접 부채 구성항목
합계와 정확히 일치해야 한다. 비지배지분이 있으면 이를 포함한 총자본을
요구한다. 음수 자본은 양쪽 검산이 일치할 때 허용한다.

CAL 구성항목은 가중치 +1과 정확히 결합된 주재무제표 행을 요구한다.
커스텀 리스는 `Long-term lease liabilities` 행으로 한정하고, 이연법인세
부채와 리스를 포함한 장기부채는 승인된 표준 태그와 행 이름을 함께 확인한다.
합계와 구성항목의 중복, 임시·상환가능 자본, 알 수 없는 CAL 구성항목,
충돌·중복 행, 반올림에 의존하는 차이는 보류한다. 표준 약정·우발사항
태그의 nil 사실은 같은 기말의 정확한 주석 참조 행에서만 제외한다.

`derive_total_liabilities_candidate`에는 기존 `statement_source.prepare_filing`의
결과와 원본 기준 기말일을 전달한다. CAL 1.1은 기존 보완 준비 경로에서
패키지와 계산 링크베이스를 검증해 전달한다. 후보에는 자산·자본·부채
구성항목의 사실 ID, 원문 행 위치, 계산 관계 및 산식을 보존한다.
구현자 집중 검사 21건이 통과했다. 이 후보는 기존 총부채 정의와 발행물에
영향을 주지 않으며, 결합 차입금·매출총이익률·연구개발비는 별도 항목이다.
