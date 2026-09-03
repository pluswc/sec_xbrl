# T5 — 기업 분석 패널

## 사용자 효과

한 회사의 특정 분기·조회 기준일에서 선택된 직접 보고값을 손익계산서 등의
기본 행과 주석의 세부 행으로 함께 표시한다. 기본 행은 `COMMON_GAAP`, 기업
고유 concept 또는 custom axis/member를 쓰는 세부 행은 `COMPANY_CUSTOM`으로
구분된다. 어느 행도 원본 XBRL identity나 공시 이력을 버리지 않는다.

## 입력과 출력

입력은 두 가지다.

- T4-B `ReportedObservationSelector`의 선택 결과: `view`, `as_of_date`,
  selection rule, 직접 보고 Fact, filing/accession/snapshot, context, unit,
  full dimension, mapping 및 T4-A ledger 근거.
- reader-attested T3 exploration graph: filing별 fact/axis/member와 실제
  relationship edge 경로.

T4-B의 `select_period()`는 period 안의 **모든** exact observation identity를
반환한다. 특정 T3 root Fact를 열 때에는 그 Fact의 T1 observation으로 만든
`ReportedObservationIdentity`를 `select_identity()`에 전달해야 한다. 이
precondition은 T3의 filing/fact graph identity와 T4-B selection identity를
임의의 QName·값 필터로 결합하지 않게 한다.

출력 `CompanyAnalysisPanelResult`은 이후 T6가 시간 열을 붙일 수 있게 다음
long-form 객체를 분리한다.

| 객체 | grain | 의미 |
| --- | --- | --- |
| definition | 한 표시 행·탐색 경로 | 행 class, parent, label, deterministic order, full graph path |
| binding | 한 행 → 선택 Fact | raw concept/dimension identity 및 relationship navigation evidence |
| value | 한 행의 한 직접 보고값 | value와 source fact/filing/context/unit/snapshot/mapping/selection/ledger lineage |

`UNAVAILABLE`도 definition/binding/value로 남는다. 값은 채우지 않으며,
`NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION` 같은 T4-B reason을 유지한다.

T3 Fact와 T4-B 선택 행의 join은 CIK, filing ID, Fact ID뿐 아니라 snapshot ID,
accession, context ID, unit ID도 모두 같아야 한다. 하나라도 다르면 패널은
fail closed 한다.

## 탐색과 계층 경계

총액 Fact를 root로 하여 T3의 실제 경로를 따른다. 선택된 detail Fact만 패널
값이 된다. geography·segment·product처럼 병렬 axis는 서로 parent-child로
연결하지 않으며, 각 행에는 자신이 지나온 `path_edges`와 edge ID를 보존한다.
같은 node 쌍이라도 서로 다른 relationship edge인 경우 별도 행/근거로 남는다.

## 의도적으로 하지 않는 일

T5는 filing을 선택하거나 amendment/recast/comparability를 판정하지 않는다.
Q4, QoQ/YoY, margin, subtotal, ratio를 계산하지 않으며 Layer 1을 수정하거나
공시를 파싱하지 않는다. 이 정책은 T4-B와 이후 T6/Derived Metrics의 책임이다.
