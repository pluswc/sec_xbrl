# 정보 일관성 — 지표·기간·조회 범위의 연결

2026-11-14 사용자 승인, 기준 main `df694e4a88`, 격리 branch
`codex/information-consistency`. PR85의 History 수정은 OPEN 별도이며 포함하지 않는다.
단일 writer/독립 reviewer와 기존 승인 구현 fallback을 유지한다. 리드는
frontend-only 기존 API 재사용 범위를 승인했고 원격/운영 작업은 리드가 담당한다.

## 설계 checkpoint와 공통 계약

투자자는 같은 지표를 탐색·상세·비교·조건에서 같은 의미로 읽고 원래 발행물로
되돌아가야 한다. paper/ink/slate/blue/amber와 기존 근접 원장/14px 수치·native
제어를 유지한다. 공통 metric presentation helper에 정확한 catalog 이름/단위/
FY·분기·TTM/비교 종류/출처/미준비와 capability를 모은다. 조회 가능, 조건 등록
가능, 상세 비교 전용을 구분한다. PERCENT/%p/RATIO를 이름만으로 바꾸지 않는다.
현재 current_ratio는 catalog PERCENT이므로 배수로 재표기하지 않는다.

## 승인 구현 범위

1. 연간 catalog 전체 선택·정렬: 기본8/프리셋 유지, 추가 선택열만 기존
   company-comparison API의2~4 CIK batch로 읽는다. 0행은0호출, 잔여1은분할
   재분배/단일 결과는 같은 scope company-profile로 읽는다. 동시성·cache는
   dataset/publication/cutoff/period/latest/CIK/definition에 결속한다. 기본8의
   추가 요청은0이다. 숫자 정렬은 기존 exact decimal/null-last helper만 재사용한다.
2. 스크리닝 결과에서 전체 프로필: run의 dataset/publication/period/resolved
   anchor를 고정한 ephemeral analysis session. 기존 screening draft/run/선택/
   scroll과 원래 explorer context를 보존하고 돌아가기/취소/오류/늦은응답을
   검증한다. 저장 이력의 고정 발행물 대신 현재 자료로 fallback하지 않는다.
3. 2~4기업 비교: catalog 그룹/다중 지표 선택과 metric별 수준+준비된 변화
   패널. 기존 금액/index100과 비교표/기업선택을 보존한다. 서로 다른 단위를
   한 축에 합치지 않는다. PERCENT의 준비된 변화는%p, 금액의 준비된 비교는
   정의된YoY/QoQ/TTM YoY로 표시한다. 일반%에서변화율을 새로 계산하지 않는다.
4. 상세 adjunct growth는 기존 governed 발행물만 소비한다. 카탈로그에 등록되지
   않은 항목은 '상세 비교 전용 · 조건 미지원'이며 브라우저 조건 계산/새 지표
   등록/새 발행은 하지 않는다. 등록된 공개growth만 원래조건 경로로 연결한다.
   screening의 QUARTERLY 값은 그대로 두고 분기·TTM 항목 구분을 명확히 한다.

허용은 app.js/css·관련 Node/표시검사·system.md·이 계약/planning이다. Python/
bridge/producer와 Raw/Derived/journal/발행물은 변경하지 않는다. 운영 governed
artifact는 전체Pythonhash에 결속되어 있으므로 source guard 완화/회계patch
전체복사/재발행 없이 운영app의최신scope UI26줄만 선택 보존한다. 운영은별도
PID47380/backend19074이며 writer가재시작/배포하지 않는다.

## 수락과 상태

Node 전체와 새 행동검사(공통명/단위/capability,31열·추가fetch0·batch1/0·cache/
실패/stale·정밀sort,screening fixed/latest/historical handoff/복귀,복수metric
MONEY/PERCENT/부족growth·missinggap·index100)를 실행하고 Ruff 및 적절표시
pytest를 수행한다. root가 실제 prepared data의 desktop/mobile/표시정확성과
기존기능/History hash를 확인하며 별도 reviewer가 동결소스를 읽기전용검증한다.
실제source/발행물추가정책이필요하면구현전에상향보고한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | frontend-only 명시 범위 GO (2026-11-14) |
| 구현 | 진행 |
| 독립 검증 / 로컬 인수 | 대기 |
| push / PR / CI / main / 운영 | 리드 담당, 이번작업 미수행 |

감사근거는 기존source 및 선택적
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/information-audit-20261114/`의
`audit.json`/`parity.json`이다. 감사 당시 연간31/분기42는 현재publication의
실제수이며 지원회사/지표의고정한계가아니다.
