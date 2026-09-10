# 투자자 분석 로드맵 — U1부터 U5까지

기준일: 2026-09-09. [계획 등록부](README.md)가 상태와 계약의 진입점이다.
이 문서는 기존 U 단계의 목적을 복구하고 인수된 변경과 남은 범위를 통합한
정식 계획이다. **미래 수락안은 기능 구현 승인 또는 일정 약속이 아니다.**
M 번호의 기반 구조 로드맵을 대체하거나 새 번호 체계를 만들지 않는다.

## 전체 사용자 목적과 경계

기업 간 비교보다 한 회사의 실적·현금·재무상태 변화와 구성을 먼저 이해한다.
처음에는 핵심 표를 보고, 항목→독립 Axis→구성→원문/검토/계산 근거로 이동한다.
필수 행·경고는 중요도나 금액 크기로 지우지 않는다. 같은 행 집합과 실제 분기
열을 사용하되 근거가 다른 매핑 구간은 별도 행으로 유지한다.

Raw는 불변이며 보고/파생/검토/표시를 구분한다. 소비자는 준비된 API를 읽고,
수집·파싱·공시 선택·회계 계산·승인은 명시적 준비/관리 경로에서만 수행한다.
QName/레이블만으로 연결하거나 다른 Axis를 합산하지 않는다. QTD, YTD, FY,
INSTANT, 전체 차원·단위·basis·source·as-of·review cutoff를 보존한다.
실제 미공시와 미보유/미준비/검토 필요를 구분하고 missing을 0으로 채우지 않는다.

## U1 — 핵심 요약

목적: 첫 화면에서 수익성, 현금, 재무상태, 자본의 핵심 변화를 읽는다.
기존 계산 경로를 검토된 자료와 연결하고, 준비된 핵심 행과 지표를 설명 가능하게
제공한다. 회사별 설정을 사용하며 고정된 티커 목록을 지원 경계로 삼지 않는다.

인수 기준과 구현된 경계:

- 기본 최근 8분기, 준비된 기간을 지정하면 최근 3개년 12분기까지 조회.
  핵심 profile은 최대 25행이며 필수 미가용 행과 경고를 유지한다.
- 값·보고/파생 상태·출처를 정확한 준비 데이터와 대조한다. QoQ/YoY와
  gross/operating margin은 승인된 입력 호환성과 계산 정책 안에서만 제공한다.
- 원래 NVDA/AMD 중심 수락안을 5사 실자료로 검증했다. 하나의 분기만 준비된
  신규 입력에는 존재하지 않는 연간 baseline이나 다른 분기를 만들지 않는다.

상태: U2와 함께 `9eb37d4715640ef7b8255d806b5ffc1c030653dd`에서 독립 검증,
PR #62 / `7f8cc5232d0df3d4c184de55827111e599b94dbd`로 병합 완료.
남은 범위: 모든 회사·모든 기간 완성, 무제한 custom 연결, narrative→0 전환은
인수되지 않았다. 주요 분석 공백은 별도 Layer 2 근거 검토로 우선순위를 정한다.
계약/재현: [투자자 API](../implementation/investor-analysis-interface.md),
`tests/test_investor_actual.py`, `tests/unit/test_investor_analysis.py`.

## U2 — 단계별 탐색

목적: 관심 항목의 구성만 펼치고, 부모 합계·현재 경로·출처를 유지하며 내려간다.
사업부·지역·제품은 병렬 관점이며 자동 부모·자식 관계가 아니다.

인수 기준과 구현된 경계:

- AMD FY2025 결합 부문→Client/Gaming의 검토된 계층을 두 번의 펼침으로
  접근할 수 있는 흐름을 제공하고 FY2023–2024의 다른 basis와 섞지 않는다.
- 정확한 기간/공시/role 범위의 CAL·DEF 및 명시적 display review를 구분한다.
  PRE를 자유 확장이나 경제적 가산 관계로 바꾸지 않는다. cycle 제어와
  targetRole, 페이지/조상 경로 범위 및 원문 trace를 유지한다.
- 소비자 탐색 중 생산자·네트워크 호출이 없어야 한다. 실자료 계층 증거와
  합성 깊이/DEF 반례를 별도로 보고한다.

상태: U1과 같은 후보/병합에서 완료. 당시 실제 5사 번들의 DEF edge가 0이었다는
검증 한계를 실제 deep DEF 완료로 바꾸지 않는다. 이후 U3의 별도 원문/DEF/Axis
증거는 해당 U3 범위의 추가 인수다. 남은 모든 주석의 해석이나 보편적 계층 보장은
없다. 계약: [T3 탐색](../implementation/t3-analysis-exploration-graph.md),
[투자자 API](../implementation/investor-analysis-interface.md).

## U3 — 중요도 보기에서 구조·Axis 시계열까지

목적: 큰 금액/변화, 고정 항목과 필수 경고를 이유와 함께 확인하고 전체 구성으로
복원한다. 승인된 후속 범위는 원문/PRE/member 검사와 **항목 행 × 분기 열**의
Axis 전체 구성을 같은 실제 표에서 제공하는 데까지 포함한다.

인수 기준:

- 정책·선정 이유·중요도·분모 근거·경고를 보존하고 0/음수/작은 기저/단위·기간·
  basis 불일치를 정상 비교로 숨기지 않는다. 숨긴 행과 전체 복원 경로를 유지한다.
- sticky 핵심 행의 구성 보기→Axis로 전체 Member와 적절한 기준 합계를 연다.
  Member를 필수로 고르지 않는다. 전체 구성은 top-N을 우회한다.
- 별도 매핑 epochs는 같은 이름이어도 합치지 않는다. 실제 열 정렬과 explicit
  null, protected subtotal/경고, 보고·파생 상태·원본 source trace를 검증한다.
- source 검토는 정확한 입력/기간에만 붙는다. NVDA 네 QTD 식/16 facts 중
  현재 두 식만 Analytical exact match이고 전년 두 식은 별도 원문 비교다.
  DC와 Compute/Networking을 Revenue에 중복 가산하지 않는다.

상태: `3098be6db7622f2ec444a9979732b7dfaa685641`에서 독립
**664 passed / 16 skipped**, Ruff PASS, 실제 6사 **84 Axis / 10,824 화면 셀**
검증 후 2026-09-09 로컬 COMPLETE 인수. closeout 문서 SHA는
`32212caba5daf8273663d70ba3075db5d1d56fc7`. 당시 `main`에는 U3가 없었다.
이후 U3–U5 누적 이력은 2026-09-10
[PR #63](https://github.com/pluswc/sec_xbrl/pull/63), merge
`9708508ec953ee4323ae29318c639abc9e0650b6`로 `main`에 포함됐다. 현재 전달
상태와 CI 근거는 [U3–U5 main 전달](../implementation/u3-u5-main-delivery.md)에서
관리한다.

남은 표시 과제: 상세 missing reason UX는 이후 공통 UI/Excel에서 검토한다.
이는 U3 차단 사유가 아니다. 실제 데이터 연결은 별도 Layer 2 근거 검토이며
중요 분석을 막는 큰 공백을 먼저 본다. 모든 기간 완성·가상 연결·가상 값은
약속하지 않는다. 재현과 의미 계약은 [v1](../implementation/u3-important-items-plan.md),
[v2/원문 전달](../implementation/u3-followup-delivery.md),
[Axis 전달](../implementation/u3-axis-timeseries-delivery.md),
[완료 기록](../implementation/u3-closeout-and-followup-priority.md)에 있다.

### 과거 선별 초안과 승인 정책의 구분

2026-09-07의 5% 비중, 최초 top-5, 약 20–25/최대 25 핵심 행은 초안 기본값이었다.
이 수치나 “25”라는 표기만으로 정책을 재승인하지 않는다. 승인된 v1은 해당 계약의
current top-five, pin/critical warning, 50% rate+top-five absolute-change 등이다.
v2는 별도 승인된 share ≥10%, share change ≥5pp, YoY ≥25%와 정확한 양의
기준액 대비 absolute delta ≥1%, top-three 비교 가능 금액 신호를 사용한다.
과거 5%와 v2의 5pp, 핵심 25행과 v2의 25%는 서로 다른 개념이다.
초안이 승인된 v1/v2를 덮어쓰지 않으며, 새 Axis 전체 구성은 선별 상한과 별도다.

## U4 — 계속 갱신

복구된 기존 목적: 새 분기·새 기업에서도 같은 분석 구조를 유지한다.
이미 있는 등록/준비/갱신 API 위에서 다음을 완성·검증하는 제안이다.

- 관리자 회사별 주요 행·순서·관점·기간·허용 설정 관리.
- 제한 조건이 명시된 검토 규칙 재사용과 예외 검토함. 현재 정확한 source/candidate
  재사용을 보존하며, 새 accession의 경제적 승인 재사용을 자동 추정하지 않는다.
- 실제 새 공시 한 건의 **수집→검토→동일 소비자 갱신**을 한 번의 연결된
  운영 증거로 남긴다. 미보유 입력이면 Layer 1 수집/파싱부터 처리한다.
- 마지막 성공 발행본을 유지하고 새/변경/철회된 검토는 명시적 결정과 별도 기준시점으로
  관리한다. 수집 실패를 DISCLOSURE_MISSING이나 0으로 바꾸지 않는다.

상태 정정(2026-09-10): 후속 사용자 승인에 따라 bounded U4가 제품 SHA
`3236778e57872b8ea41e421534e4a9d9ea0d58ff`에서 로컬 인수됐다. 실제 NFLX
신규 2공시 입력, 최종 14공시 offline orchestration, 관리자 quality overlay와 동일
API/화면을 별도 검증했다. 이는 무인 경제 승인이나 main 병합이 아니다. 정확한 범위와
증거는 [U4 완료·인수](../implementation/u4-completion-and-acceptance.md)에 있다.
그 뒤 U4는 U3·U5와 함께 PR #63의 merge
`9708508ec953ee4323ae29318c639abc9e0650b6`로 `main`에 포함됐다.

남은 작업/수락안/입력/재현은 [U4 실행 제안](../implementation/u4-continuous-refresh-plan.md)의
격차 표와 연결된 실제 흐름에서 정의한다. 미래 구현자는 먼저 구체 실행/검토 범위와
필요한 외부 작업 권한을 확인한다. 이 문단의 과거 제안 상태는 위 날짜의 후속 인수
기록으로 갱신됐으며, 일정이나 자동 회계 판단을 약속하지 않는다.

## U5 — 보관·공유

복구된 기존 목적: 지금 보는 핵심 표를 저장하고 전달한다. Excel은 기존 CSV/HTML과
구분되는 별도 납품 항목이며 준비된 API의 소비자다.

후속 수락안:

- 사용자가 선택한 **기간·행·단위·분모·검토 상태·출처**를 함께 내보낸다.
  view/as-of/review cutoff, publication/companion 식별, 보고/파생 구분과 필요한
  산식/입력 lineage를 잃지 않아 동일 준비 셀로 돌아갈 수 있어야 한다.
- 표시 단위와 원 단위를 구분하고, 서로 다른 Axis/basis나 분모를 조용히 합치지 않는다.
  missing과 unavailable reason은 0 또는 공시 부재로 바꾸지 않는다.
- 선택 상태의 API/CSV/HTML/Excel 동등성, 안전한 텍스트 출력, 전체/부분 내보내기와
  필수 경고 보존을 후속 상세 구현 범위에서 검증한다. 내보내기가 수집·공시 선택·
  연결·회계 계산·승인을 실행해서는 안 된다.

상태 정정(2026-09-10): completion baseline `51c196f`에서 승인된 U5 제품
`8867229455f9441807117a4a4a3e1ebaa8ae7eee`는 독립 검증 `PASS` 후
`LOCAL_ACCEPTED_NOT_MERGED`로 인수됐다. canonical snapshot,
CSV/HTML/JSON/XLSX와 오프라인 저장 범위는
[U5 전달 계약](../implementation/u5-consumer-export.md), 검증·제약·재작업 근거는
[U5 완료·인수](../implementation/u5-completion-and-acceptance.md)에 기록한다.
이 로컬 인수 시점에는 `main`에 병합되지 않았다. 이후 U3–U5 통합은
[PR #63](https://github.com/pluswc/sec_xbrl/pull/63), merge
`9708508ec953ee4323ae29318c639abc9e0650b6`로 완료됐으며 PR/main CI 근거는
[main 전달 기록](../implementation/u3-u5-main-delivery.md)에서 구분한다.

## 계속 유지할 잔여 범위와 제외 사항

주요 분석 공백의 Layer 2 근거 검토, 명시적 관리자 판단, 당시 알려진 값과 이후
수정값의 사용성 개선은 구분해서 우선순위를 정한다. 승인되지 않은 Q4 경로,
서술→숫자 전환, cross-filing bridge를 이 로드맵으로 허용하지 않는다.
기업 간 비교·뉴스 결합·모든 주석 전개·모든 업종/기업의 완전 자동 해석은 이
이용 로드맵의 당장 실행 범위가 아니다. 측정하지 않은 성능이나 커밋 일정도 보장하지 않는다.
