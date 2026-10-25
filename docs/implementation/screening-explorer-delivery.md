# 스크리닝 기업 탐색 R2 전달 계약

## 1. 승인과 상태

기준일은 **2026-10-09 KST**다. 사용자는 locally accepted R1 제품
`271fb1c968ebc03d98aea1561cd096187302a7fe`를 부모로 하는 R2 로컬 구현을
승인했다. 이 절의 상태는 승인 당시 **APPROVED / IMPLEMENTATION_IN_PROGRESS**였다. 구현 브랜치는
`codex/screening-explorer`이며 push, PR, remote CI와 `main` 병합은 승인 범위가
아니다.

R2는 일반 사용자가 조건을 저장·실행하기 전에도 실제 21개 prepared 회사를
둘러보고, 31개 지표를 의미와 선택 회계연도 가용성으로 찾고, 회사별 31개 값과
4 FY 흐름을 읽고, 2–4개 회사를 같은 기간·지표로 비교하게 한다. 기존 스크리닝,
불변 revision/run, decision journal, export와 admin 근거 화면은 그대로 유지한다.

새 SEC·시장 데이터, 가격·가치평가, 회사 설명·주소·웹사이트 추측, peer 평균·순위,
새 재무 공식, raw parsing·selection·recast는 포함하지 않는다. 실제 R3 dataset은
읽기 전용이며 실제 journal에는 검증 write를 하지 않는다.

## 2. 소비 경계와 API

모든 endpoint는 service 시작 때 이미 검증한 screening dataset v2의
`companies`, `metric_definitions`, `metric_support`, `metric_observations`만 읽는다.
HTTP·browser는 재무 공식을 다시 계산하지 않는다. 허용 산술은 exact Decimal을
이용한 정렬·조건 비교와 표시 단위 변환뿐이다.

```text
GET /api/explorer?dataset_id=ID&fiscal_year=FY&query=Q&sort=METRIC&direction=asc|desc
GET /api/metric-library?dataset_id=ID&fiscal_year=FY&query=Q&category=CATEGORY
GET /api/company-profile?dataset_id=ID&cik=CIK&fiscal_year=FY
GET /api/company-comparison?dataset_id=ID&ciks=CIK,...&metric_ids=ID,...&fiscal_year=FY
```

`/api/explorer`는 financial as-of, 선택 가능한 FY, 21개 회사의 name/ticker,
사람이 읽는 industry, 실제 FY bounds와 지정한 지표 projection을 반환한다. 기본
projection은 `revenue`, `revenue_yoy`, `operating_margin`, `net_income`, `cfo`,
`standardized_fcf`, `current_ratio`, `liabilities_to_assets`다. 값은 publication의
status·reason·source kind·definition version을 유지하며 missing은 0이 아니다.
정렬은 표에 보이는 공통 8개 항목 중 하나 또는 기업명만 허용하며 같은 선택 FY의
frozen Decimal 값만 비교하고 null은 마지막이다. 알 수 없거나 숨은 지표 정렬은
silently no-op 하지 않고 거절한다. 기본 FY는 21사 모두에 준비된 가장 최근
FY2025다. 일반화된 cohort에 공통 FY가 없으면 회사 coverage가 가장 큰 한 연도를
고르고 동률이면 최근 연도를 쓰며, `default_year_is_common=false`와 실제 coverage를
반환한다. 서로 다른 회사 연도를 섞지는 않는다. 전체 union인 FY2022–2026도
회사 coverage와 함께 제공하되 FY2026을 선택해도 5개 회사를 “최신 연도”로
바꾸지 않고 21행 중 16행을 `선택 연도 자료 없음`으로 유지한다.

`/api/metric-library`는 31개 정의의 label, category, 쉬운 한국어 의미·사용 맥락,
FY/연도말 구분, reported/derived, money/percentage unit, exact definition version과
**선택 FY**의 available/unavailable 회사 수를 반환한다. any-year support를 선택
FY coverage처럼 표시하지 않는다.

`/api/company-profile`은 저장·실행 없이 회사 기본 정보, prepared FY 목록, 선택
FY의 공통 8개 요약과 전체 31개 grouped 값·상태·reason·실제 날짜를 반환한다.
4 FY trend는 기존 `/api/series`의 frozen observation을 사용한다.
`/api/company-comparison`은 2–4개 CIK와 기존 metric 1–31개만 허용하고 같은 FY의
matrix와 회사별 실제 날짜를 반환한다. 평균, 점수, 순위 또는 새 지표를 만들지
않는다.

## 3. 화면 계약

상단 작업 navigation은 다음 네 화면을 가진다.

1. **기업 둘러보기** — 기본 landing. 검색, FY, 표시 지표 preset, null-safe 정렬,
   21개 회사 표, 2–4개 비교와 독립 회사 프로필 진입
2. **지표 안내** — category·검색 가능한 31개 library와 선택 FY coverage,
   명시적 `조건에 추가`
3. **스크리닝** — 기존 저장 조건, 조건 편집, 실행과 결과
4. **이력** — 기존 run 비교와 decision history

기존 `#criteria-title`, `#results-title`, `#history-title` anchor와 keyboard focus,
Escape 닫기, dirty/saved 표시를 유지한다. library의 `조건에 추가`는 현재 draft에
exact metric definition을 추가할 뿐 자동 저장·실행하지 않는다. money 입력은
화면의 백만 USD를 exact USD로, percentage는 그대로 변환한다. 과거 v1 run을
열어도 explorer/library dataset·FY는 최신 v2 상태를 유지한다.

회사 프로필은 공통 8개 요약, 31개 grouped metric, 선택 metric의 4 FY 표와 작은
접근 가능한 SVG trend를 보여준다. SVG는 이미 준비된 값의 표시 geometry만 만들며
gap을 0으로 연결하지 않는다. ordinary 화면은 CIK·SIC code·raw ID·QName·hash를
노출하지 않고, source/date와 business missing reason은 사람이 읽는 말로 보여준다.
기술 근거와 8,016 metadata inventory는 기존 admin mode에서 유지한다.

API의 `period_start`/`period_end`와 `end_convention=EXCLUSIVE`는 그대로 보존한다.
사람이 읽는 explorer/profile/compare/trend 날짜만 ISO `period_end`에서 UTC 하루를
빼 포함 종료일로 표시한다. 예를 들어 canonical `2024-12-29 → 2025-12-28`은
`2024-12-29 ~ 2025-12-27`로 보인다. 경계가 없으면 날짜를 추측하지 않는다.

정보 구조 참고는 2026-10-09에 확인한 [Koyfin 기능 도움말](https://www.koyfin.com/help/topic/functionality/),
[TradingView 재무자료 도움말](https://www.tradingview.com/support/solutions/43000543506-how-to-access-financial-data-on-tradingview/),
[Finviz Screener 도움말](https://elite.finviz.com/help/screener)의 column view, 재무항목
그룹 탐색, 회사별 시계열 chart/table 패턴으로 한정한다. 외부 자산·수치·점수·재무
정의는 복사하지 않는다.

## 4. 불변성과 수락 gate

- cold start에서 POST 없이 최신 v2의 21개 회사와 공통 8개 지표가 보임
- 선택 FY 기준 31개 library coverage가 frozen observation과 일치함
- library에서 money `0.5`는 exact USD `500000`, percent `0.5`는 `0.5`로 draft에
  추가되며 자동 저장·revision 변경이 없음
- 검색·category·정렬은 null-safe이고, 2–4개 비교와 전체 31개 profile이 가능함
- 4 FY trend가 실제 값·gap·기간을 보존하고 missing을 0으로 만들지 않음
- 과거 v1 run/journal/export와 최신-v2 새 조건 동작이 R1과 동일함
- 독립 source/trace oracle이 explorer/profile/compare 값을 parent observation과 대조함
- ordinary DOM에는 SIC/CIK/raw ID/code가 없고 admin 기능은 유지됨
- keyboard, 1,440/1,024/768px, external request 0, error/empty 상태를 검증함
- full 31 CSV/XLSX canonical roundtrip과 R1 회귀가 유지됨
- 실제 journal, R3 publication, 보호 source는 전후 hash가 같음

구현자는 unit·HTTP·consumer·UI integration, Ruff와 JS syntax를 실행하고 source
SHA를 동결한다. 별도 verifier의 PASS와 lead의 로컬 인수, 사용자의 직접
walkthrough, 원격 병합은 서로 다른 상태다.

## 5. 2026-10-09 완료 상태 추가

최종 제품 `7e7ec154e15ed88a14c2a74d89042c39fa3fadbf`가 독립 **PASS**했고 lead가
**LOCALLY_ACCEPTED**로 판정했다. 실제 R3 publication은 바뀌지 않았다. 검증
식별자, 앞선 FAIL 후보와 남은 human walkthrough·원격 상태는
[R2 완료·로컬 인수 기록](screening-explorer-completion.md)에 보존한다.
