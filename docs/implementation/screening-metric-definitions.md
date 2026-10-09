# 스크리닝 R1 지표 정의 계약

## 1. 공통 표기

기준일은 **2026-10-09 KST**다. `R_t`는 현재 FY 매출, `R_t-1`은 직전 FY 매출,
`GP`, `OI`, `NI`, `CFO`, `CAPEX`는 같은 FY의 직접 보고 선택값이다. `CA`, `CL`,
`L`, `A`, `E`, `D`, `CASH`는 같은 연도말 instant의 직접 보고 선택값이다.

money는 USD exact decimal, percentage/ratio는 `%` 단위의 percentage point다.
reported 값과 derived 값은 별도 stable ID와 source kind를 가진다.

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
UNIT_NOT_USD
MAPPING_REVIEW_REQUIRED
QUALITY_BLOCKED
DIMENSION_MISMATCH
PERIOD_MISMATCH
SOURCE_FILING_MISMATCH
PRIMARY_STATEMENT_EVIDENCE_MISSING
BASIS_INCOMPATIBLE
NON_POSITIVE_DENOMINATOR
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

