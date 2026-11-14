# 정보 일관성 — 지표·기간·조회 범위의 연결

2026-11-14 사용자 승인. 최초 기준 main `df694e4a88`에서 별도 branch
`codex/information-consistency`를 만들었고, 구현 중 PR95가 병합된 최신 main
`ebdbe938d7`을 일반 merge `27d8397926`로 통합했다. PR85의 History 수정은
별도 OPEN 작업이며 포함하지 않는다. 단일 writer와 독립 reviewer, 기존 승인
구현 fallback을 유지한다. 원격 전달과 운영 배포는 리드가 담당한다.

## 설계 기준

투자자는 탐색·상세·비교·조건에서 같은 지표의 의미를 일관되게 읽고 원래
발행물로 돌아갈 수 있어야 한다. paper/ink/slate/blue/amber, 근접한 원장 행,
14px 수치와 native 제어를 유지한다. 공통 helper에 정확한 catalog 이름·단위,
연간/분기/TTM, 비교 종류, 출처, 미준비 사유와 조건 등록 가능 여부를 모은다.

단위와 비교 의미는 정의를 따른다. MONEY는 백만 USD, PERCENT는 %, 실제
RATIO는 배수로 표시하며 원래 십진 문자열과 편집 기준값을 바꾸지 않는다.
current_ratio는 현재 catalog의 PERCENT 정의를 유지한다. TTM의 공통 명칭은
‘최근 12개월(TTM)’이며 마진 자체를 네 분기 비율의 합계라고 표현하지 않는다.
연간 YoY와 분기 전년 동기를 구분하고, 기말 금액은 ‘기말잔액 YoY · 전년 같은
기준시점’으로 표시한다. QoQ/YoY 지표 자체의 준비된 변화는 ‘QoQ의 전년 동기
변화(%p)’처럼 성장률의 변화임을 명시한다. 실제 RATIO에 %p를 적용하지 않는다.

## 구현 범위와 경계

1. 연간 전체 지표 선택·정렬: 기본 8개와 프리셋을 유지한다. 추가 선택 열만
   기존 company-comparison API의 2~4 CIK batch로 읽는다. 남은 한 회사는
   batch를 재분배하고, 검색 결과가 한 회사이면 같은 범위의 company-profile을
   사용한다. 0행은 0호출이며 기본 8개도 추가 요청이 없다. 동시성은 최대
   세 batch로 제한하고, cache는 dataset/publication/cutoff/기간/CIK/정의에
   결속한다. 최신 관측은 각 원래 탐색 행의 실제 기간까지 검증한다. 정렬은
   기존 정확한 decimal/null-last helper를 재사용한다. 조회 오류를 재무적
   미준비 값으로 만들거나 조용히 다른 정렬 결과와 섞지 않는다.
2. 스크리닝 결과에서 전체 프로필: 실행 결과의 dataset/publication/기간과
   resolved anchor를 고정한 임시 분석 세션을 사용한다. 원래 조건 draft, 실행,
   선택, 검색, 정렬, 지표 선택과 scroll을 보존한다. 분기·TTM 혼합은 공통
   종료 분기를 사용하며 TTM만 선택한 결과는 TTM으로 연다. 과거 offset 정책의
   관측 기간이 서로 다르거나 불명확하면 전체 프로필 연결을 거부하고 기존
   조건 근거를 유지한다. 원래 발행물이 없으면 최신 자료로 대신 열지 않는다.
   취소·닫기·뒤로 가기 이후 늦은 성공이나 오류는 화면을 다시 열지 않는다.
3. 2~4기업 비교: catalog 분류와 다중 지표 선택을 유지하고 최대 8개 지표의
   수준·준비된 변화 패널을 제공한다. 기본 비교는 매출·영업이익·CFO·표준화 FCF를
   선택해 금액과 준비된 변화를 가까이 두고 기본 화면의 성장률 중복 선택을 줄인다.
   이는 연간 탐색의 기본 8개를 바꾸지 않으며, 성장률 자체도 전체 catalog에서
   명시적으로 선택할 수 있다. 더 많은 선택은 비교표에서 계속 접근한다.
   지표별 독립 축과 기업별 같은 색을 사용하며, 기존 단일 금액/index100 보기는
   native details에 유지한다. 수준/수준+변화 전환은 다시 조회하지 않는다.
   기존 공개 성장률을 우선 사용하고 다른 변화는 이미 발행된 adjunct만 읽는다.
   원값·실제 기간·출처와 부호 전환 상태, missing gap, 키보드·고정 설명을 보존한다.
4. 조건 기능: 등록된 catalog 지표만 원래 조건 경로로 연결한다. adjunct의
   별도 비교 값에는 ‘상세 비교 전용 · 조건 미지원’을 표시한다. 새 지표 정의,
   브라우저 조건 계산, 비율의 임의 성장률 계산이나 재발행을 하지 않는다.
   조건 select의 QUARTERLY 값은 유지하고 화면 명칭을 ‘분기·TTM’으로 명확히 한다.

Python/bridge/producer, Raw/Derived 발행물과 journal은 변경하지 않는다.
운영 governed artifact가 전체 Python hash와 정확히 결속되므로 source guard를
완화하거나 새 source로 재발행하지 않는다. 운영의 최신 범위 UI 패치 26줄은
main PR95에 포함됐으며 이번 화면 변경의 기반으로 보존한다. main의 해당
Python/bridge/producer와 검사는 그대로 유지한다. writer는 운영을 재시작하지 않는다.

## 검증·상태

새 행동 검사에는 단위·capability, batch 0/1/5/9, 기본 8개 추가 요청 0, 실제
기간 불일치 거부, stale 응답, 큰 십진 정렬과 null-last, 과거 기간·TTM 판정,
프로필 취소/실패/성공과 복귀, nested 상태 격리, 조건 추가 거부 시 기존 실행
보존, catalog PERCENT/INSTANT 비교와 cache, missing growth 렌더를 포함한다.
초기 기존 Node 122개에 신규 검사를 추가했고 최신 main 통합 뒤 전체 Node
136개가 통과했다. 최종 표시 단위와 비교 기본값 정리 후 전체 Node **138개**(신규 행동13개 포함),
관련 Python **35개**가 통과했다. `ruff check .`와 `git diff --check`도 통과했다.
Node 로그는 `/tmp/information-freeze-node.log`, 새 행동 검사는
`/tmp/information-new5-node.log`, Python은 `/tmp/information-python.log`다.
Ruff/diff와 별도 독립 검증, 리드의 실제 desktop/mobile 브라우저·History 보존
인수는 각각 구분한다. 중간 비교 화면의 없는 관측 날짜 접근은 안전하게 처리하고
원래 actualPeriod helper는 바꾸지 않았다.

| 단계 | 상태 |
| --- | --- |
| 승인 | frontend-only 범위 GO (2026-11-14) |
| 구현 | 최신 main 통합·검토 보완 후보 동결, 작성자 Node139/Ruff/diff PASS·불변 API Python35 근거 유지 |
| 독립 검증 / 로컬 인수 | 대기 |
| push / PR / CI / main / 운영 | 리드 담당, 이 작업의 전달·반영은 미수행 |

감사 근거는 기존 소스와 선택적 로컬 근거
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/information-audit-20261114/`의
`audit.json`/`parity.json`이다. 감사 당시 연간31개/분기42개는 그 발행물의 실제
개수이며 회사나 지표의 고정 지원 한계가 아니다. 신규 실제 화면 검증은 같은
상위 폴더의 `information-consistency-20261114/`에 별도로 기록한다.

추가 조건 버튼은 현재 조건의 dataset/publication/cutoff를 모두 확인한다. 과거
실행 결과에서 연 전체 프로필 세션은 조회 전용이며, 기존 결과로 돌아가 조건을
명시적으로 편집하도록 안내한다. 비교표의 없는 관측은 빈 기간으로 처리하고
그 상태의 최초 렌더와 재렌더를 회귀 검사한다. 연간 지표 picker는 넓은 grid의
전체 폭을 사용하고 desktop에서는 3~4열, 좁은 화면에서는 내부 스크롤로 유지한다.

이 자체 검사는 새 코드의 로컬 인수나 운영 적용을 의미하지 않는다. root의 중간
사본에서는 추가 열 정렬·한 회사 조회·프로필 왕복과 기존 GOOGL/WDC/원본 owner
보존을 확인했으나 최종 동결 자산의 실제 브라우저와 독립 검증은 다음 단계다.
최신 main 대비 Python/bridge/producer 파일 차이가 없음을 확인했고, PR85의
미병합 History 변경이나 새 자료 발행은 이 branch에 포함하지 않았다.

## 독립 사전 검토 보완

`0331864395`의 리드 실제 화면 검사는 기본8/추가92행 정렬/한 회사 조회,
다중 지표,1440·1920·2560과390px, %p와 LEVEL/BOTH 전환, 고정 발행물
프로필 왕복, 취소·실패, 기존 GOOGL/WDC/owner 보존에서 PASS했다. 근거는
`preview-acceptance.json`, `failure-cancel-acceptance.json`,
`preview-browser-acceptance.json`이다. 최종 보완 자산의 재검증은 별도다.

독립 reviewer가 찾은 설명 누락을 보완했다. 조건 근거의 metricHelp도 공통
presentation을 사용하며, description이 없는 QoQ/YoY는 공표된 input_contract
kind와 formula를 설명한다. TTM 금액/비율과 산술 비교의 회계기준 보류 설명을
유지하고 계산 지표를 회사 보고 항목으로 표시하지 않는다. 새로운 계산이나
정의 변경은 없다. 비교 차트 제목은 단위를 한 번만 쓰고 MONEY 수준은 ‘금액’으로
명확히 했다. 실제 renderMetricEvidence의 QoQ/YoY/TTM 회귀를 추가했다.

보완 후 전체 Node **139개**(신규 행동14개 포함), Ruff/diff PASS. 로그는
`/tmp/information-reviewed-node.log`, `/tmp/information-evidence-node.log`다.
앞서 통과한 Python35개가 검사한 API/서비스 소스는 이 보완에서 불변이다.
별도 최종 독립 검증과 로컬 인수·운영·원격 상태는 계속 대기다.
