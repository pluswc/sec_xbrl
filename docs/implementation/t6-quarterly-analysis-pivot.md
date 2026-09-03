# T6 — 분기 분석 피벗

## 사용자 효과

T5에서 이미 선택되어 계보가 검증된 회사별 분석 행을, 세로 행·가로
회계연도/분기 열의 피벗으로 읽는다. 따라서 사용자는 매출, 비용, 자산 또는
기업 고유 세부항목을 같은 분기 흐름에서 볼 수 있지만, T6가 값·선택·회계
의미를 새로 만들지는 않는다.

## 입력, 출력, 경계

입력은 같은 `CIK + period_class + selection_view + selection_as_of_date`를
공유하는 하나 이상의 `CompanyAnalysisPanelResult`다. 하나라도 다르면 피벗
생성은 실패한다. 출력은 다음 세 long-form 객체다.

| 객체 | grain | 보존하는 것 |
| --- | --- | --- |
| `column` | 회계연도·분기·period class | 열 순서 및 실제 context 날짜 |
| `row` | 안전하게 연결된 분석 의미 | concept/dimension/unit semantic identity, review 상태 |
| `cell` | row × quarter의 T5 값 | definition, binding, value 전체 — 선택·ledger·T3 relationship 계보 |

`QuarterlyAnalysisPivotQuery.matrix()`는 존재하지 않는 row×quarter 조합도
`UNAVAILABLE / NO_T5_PANEL_VALUE_FOR_PERIOD`로 명시한다. 기존 T5가 이미
`UNAVAILABLE`로 낸 값은 원래의 unavailable reason을 유지한다. 어느 경우도
이전 분기 값을 채우지 않는다.

## 안전한 시간 연결 키

T6의 row key는 아래 조합이다.

```text
CIK + line scope/kind + concept identity + complete canonical dimensions
+ normalized numerator/denominator unit measures + period_class
```

공통 GAAP는 확인된 회사 canonical concept을 우선 사용한다. 해당 매핑이
없어도 `STANDARD + taxonomy family + QName`이 완전하게 있는 경우에만 qualified
standard fallback을 쓴다. local name 단독 비교는 하지 않는다.

기업 고유 행은 concept mapping ID/version, complete canonical axis/member/typed
dimension signature, 필요한 dimension mapping ID가 모두 확인되고 review flag가
없을 때만 분기 간에 연결한다. 불확실·미매핑·불완전 unit은
`MAPPING_REVIEW_REQUIRED` 또는 `MISSING_COMPATIBLE_UNIT_SEMANTICS`로 표시하고,
`filing + fact + period` scoped row로 남긴다. 레이블이 같아도 연결하지 않는다.

같은 안전한 row와 같은 fiscal column에 두 T5 값이 도착하면 충돌로 실패한다.
서로 다른 actual period가 하나의 fiscal-year/quarter 레이블에 들어오는 경우도
실패한다.

## 의도적으로 하지 않는 일

T6는 T4-B의 `AS_FILED`/`LATEST_REPORTED` 선택을 바꾸지 않고, amendment/recast
판정도 하지 않는다. Q4, QoQ/YoY, 성장률, 비중, margin, subtotal 및 기타 파생
지표를 계산하지 않는다. 이들은 이후 Derived Metrics 작업의 별도 결과이며,
피벗의 직접 보고값을 대체할 수 없다.
