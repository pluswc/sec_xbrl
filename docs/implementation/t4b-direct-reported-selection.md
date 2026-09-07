# T4-B — Direct-reported selection views

## 사용자 효과

동일 분기·동일 항목에서 최초 제출값(`AS_FILED`)과 현재까지의 마지막 **직접보고**값
(`LATEST_REPORTED`)을 분리해 조회한다. 선택값은 원본 fact, context, unit, dimensions,
filing/accession/snapshot/mapping 및 T4-A ledger 이력을 그대로 보존한다.

## 선택 경계

`AS_FILED`는 기준일 이하의 첫 직접보고값을, `LATEST_REPORTED`는 기준일 이하의 마지막
직접보고값을 택한다. 동일 범위는 CIK, standard raw QName(연도 namespace 제외) 또는 custom
namespace+QName, canonical concept, complete canonical dimensions(불완전 시 raw fallback),
unit semantics, 실제 context 기간, period class로 구성된다. 정렬은 `filed_date`, 같은 날짜의
`accession`, `source_fact_id`이며 accession 숫자는 수정 차수로 해석하지 않는다.

## 의도적으로 하지 않는 일

수정 연결, 숫자 차이, label, filing 순서는 재작성·비교가능성·수정 범위의 근거가 아니다.
따라서 수정 공시에 matching direct fact가 없으면 원본은
`SELECTED` / `LATEST_ELIGIBLE_DIRECT_REPORTED_OBSERVATION`으로 남되,
`comparability_status=NOT_ASSESSED`이다. 이는 수정본이 원본을 유지하거나 전체를 대체했다는
주장이 아니다. 대상 identity에 기준일 내 직접보고 fact가 없으면 `UNAVAILABLE`과
`NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION`을 낸다.

Q4 파생, 지표·pivot, `CURRENT_COMPARABLE`, `LATEST_RECAST`는 범위 밖이다.
