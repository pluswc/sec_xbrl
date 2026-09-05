# T4--T8 운영 조회 경계

## 사용자 효과

이미 발행된 T1--T4 Parquet 결과만으로 회사/회계연도/분기/조회 뷰/as-of 날짜를
명시해 T5 분석 행, T6 피벗, T7 파생 지표, T8 다기업 비교를 즉시 조회한다.
따라서 조회 요청이 Layer 1 파싱, 관계 그래프 생성, 버전 ledger 생성 또는 Parquet
발행을 다시 수행하지 않는다.

## 입력과 검증

`OperationalAnalyticsQueryService`는 다음 네 개의 immutable publication root를
받는다.

| root | 필수 dataset | 역할 |
| --- | --- | --- |
| T1 | `reported_period_observation` | 직접 보고된 모든 version 후보 |
| T2 | `filing_relationship_edge` | T3 graph의 입력 계보 attestation |
| T3 | `analysis_exploration_node`, `analysis_exploration_edge` | 탐색 관계 |
| T4-A | `accession_version_ledger` | 제출일·수정 근거 |

각 root는 기존 `Layer2PublicationReader`로 manifest/행 계약을 먼저 검증한다. 네
root는 같은 Layer 2 run fingerprint와 CIK 선언을 가져야 한다. 이 조건이 다르면
선택하거나 비교하지 않고 실패한다. T4-B는 이 검증된 T1/T4-A를 입력으로 인메모리
선택만 수행하며, T5--T8도 기존 serving builder만 사용한다.

## 조회와 캐시

`OperationalQueryScope(cik, fiscal_year, fiscal_quarter, period_class, view,
as_of_date)`가 모든 회사 조회의 필수 입력이다. `view`는 현재 `AS_FILED` 또는
`LATEST_REPORTED`만 허용한다. 피벗은 동일 회사·기간 클래스·뷰·as-of의 여러 scope를
받고, 다기업 비교는 회사별 피벗을 T8에 전달한다.

결과 캐시 키에는 네 publication manifest SHA-256과 전체 scope가 포함된다. 호출자는
항상 defensive copy를 받으므로 반환된 dict를 수정해도 이후 조회나 캐시에는 영향을
주지 않는다. 캐시는 프로세스 내 성능 장치일 뿐이며, 새 publication은 새 service로
명시적으로 attestation해야 한다.

## 통합 영향

T4--T8의 선택·행 구성·피벗·지표·비교 규칙과 이미 발행된 Parquet schema는 변경하지
않는다. 이 변경은 그 결과를 소비하는 단일 in-process 진입점만 추가한다. 따라서
사용자 조회에서 앞 단계 파이프라인을 재실행하던 비용을 제거하되, 기존 결과의 값이나
원본 계보를 바꾸지 않는다.

## 비범위

이 경계는 새 Parquet을 쓰지 않고 publisher, Raw Layer 1 parser, SEC 네트워크 접근을
호출하지 않는다. 재작성 판정, Q4 생성, typed dimension 시계열 연결, peer ranking도
추가하지 않는다. 각각 기존 T4--T8의 안전 경계를 그대로 따른다.
