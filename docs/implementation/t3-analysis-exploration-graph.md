# T3 — 분석 탐색 그래프

## 사용자 효과

분기 손익계산서의 매출 같은 기본 행에서 출발해, 같은 공시 안의 주석
차원과 기업 고유 항목까지 원문 근거를 잃지 않고 열어 볼 수 있다. 예를
들어 NVIDIA 매출은 `지역`, `사업 세그먼트`, `제품/서비스`를 **서로 다른
병렬 관점**으로 제공한다. 한 관점이 다른 관점의 부모나 자식이라는 뜻은
아니다.

## 입력과 경계

T3는 reader-attested T1 `reported_period_observation`과 T2
`filing_relationship_edge`가 같은 Layer 1 input declaration을 가질 때만
발행한다.

- T1은 모든 직접 보고 fact의 기간·공시 버전·Context·Unit·전체 차원을 준다.
- T2는 filing/role/network별 PRE·CAL·DEF 원문 관계를 준다.
- T3는 filing을 선택하지 않고, amendment/recast/Q4/합계/driver/비율을
  계산하거나 추정하지 않는다.

## 운영 Parquet 데이터셋

### `analysis_exploration_node`

각 행은 `CONCEPT`, `FACT`, `AXIS`, `MEMBER` 중 하나의 탐색 노드다. 모든
노드는 raw ID/QName/namespace/taxonomy를 유지하며 다음 origin을 명시한다.

```text
STANDARD_CONCEPT / CUSTOM_CONCEPT
STANDARD_AXIS    / CUSTOM_AXIS
STANDARD_MEMBER  / CUSTOM_MEMBER
```

`FACT` 노드는 raw fact, filing/accession/form/filed date, Context, Unit,
전체 raw/canonical dimension signature, 매핑 ID·버전·검토 상태, 기간과
값을 유지한다. canonical ID와 mapping evidence는 부가 정보이며 raw
identity를 대체하지 않는다.

공유되는 Axis가 매출·비용처럼 서로 다른 항목을 잘못 이어 주지 않도록,
Axis와 Member navigation node는 **원문 concept 범위**를 함께 갖는다.
따라서 `매출 → 지역` 경로가 다른 concept의 지역 fact로 새지 않는다.

### `analysis_exploration_edge`

| edge kind | 의미 | 보존 근거 |
|---|---|---|
| `STATEMENT_COMPONENT` | filing 안의 표시/계산 구성 관계 | 원문 PRE 또는 CAL. `source_network_type`으로 반드시 구분 |
| `DIMENSION_LENS` | 한 concept/fact를 특정 Axis 관점으로 보는 진입점 | 직접 보고 fact의 full dimension signature |
| `FACT_SCOPE` | Axis/Member가 실제 보고 fact의 scope임 | source fact, Context, Unit, dimension assignment |
| `MEMBER_HIERARCHY` | DEF가 제공한 member/domain 관계 | DEF relationship ID, role, targetRole, base-set 속성 |

PRE와 CAL은 `STATEMENT_COMPONENT`라는 조회 분류만 공유할 뿐 서로 합치지
않는다. `MEMBER_HIERARCHY`는 DEF 근거일 때만 만든다. 모든 relationship
edge는 relationship ID, role/role URI, targetRole, arcrole, link/arc QName,
order, weight 등 T2 증거를 유지한다.

## 재귀 조회

`ExplorationGraphReader.traverse()`는 outbound edge를 재귀적으로 따라가되,
현재 path 안에 이미 있는 node로 다시 들어가는 edge는 중단한다. 이는 DEF
또는 표시 구조의 cycle을 안전하게 막는다. 방문 집합을 전역으로 공유하지
않으므로 role이나 lens가 다른 **대안 경로**는 모두 유지된다.

화면은 이 graph를 트리처럼 한 번에 보여 줄 수 있지만, 데이터 모델 자체는
그래프다. 서로 독립인 지역·세그먼트·제품 Axis는 병렬 lens이고 이들을
합쳐 하나의 인공 parent-child 체인으로 표시해서는 안 된다.

## NVIDIA FY2024 Q3 검증 예

캐시 corpus의 10-Q `0001045810-23-000227`에서 총 매출
`us-gaap:Revenues = 18,120,000,000` fact를 root로 조회하면 다음의 병렬
lens가 확인된다.

```text
매출 18.120B
├─ StatementGeographicalAxis
│  └─ country:US, nvda:ChinaIncludingHongKongMember, ...
├─ StatementBusinessSegmentsAxis
│  └─ nvda:ComputeAndNetworkingMember, nvda:GraphicsMember, ...
├─ ProductOrServiceAxis
│  └─ nvda:DataCenterMember, nvda:GamingMember, nvda:AutomotiveMember, ...
└─ ConsolidationItemsAxis
```

custom member는 `CUSTOM_MEMBER` origin으로 보존된다. 이 결과는 매출의
경제적 driver를 자동 판정하거나 Axis별 값을 합산했다는 뜻이 아니다.

## 이후 분석뷰와의 연결

후속 분석뷰는 T3 graph에서 어떤 행·lens를 표에 보일지 versioned
definition으로 정한다. T3는 그 결정 전에도 모든 origin과 lineage를
가지므로, 공통 GAAP 행과 기업 custom 행을 같은 분기 피벗에서 함께
표시할 수 있다.
