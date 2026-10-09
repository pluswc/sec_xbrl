# 기업 탐색 R2 사용법

기업 탐색은 검증된 screening dataset v2를 읽는 화면이다. 서비스를 여는 즉시
`기업 둘러보기`에서 prepared 회사와 공통 8개 재무항목을 볼 수 있다. 조건 저장이나
스크리닝 실행은 필요 없다. 기존 실행·조건·판단 이력은 그대로 남는다.

## 화면 흐름

1. **기업 둘러보기**에서 회사명·티커·업종을 검색하고 회계연도를 선택한다.
   기본값은 모든 회사에 준비된 가장 최근 연도다. 공통 연도가 없는 dataset은 가장
   많은 회사가 준비된 한 연도를 쓰고 이를 partial coverage로 표시한다.
2. 표시 항목 preset과 공통 8개 중 정렬 항목을 선택한다. 선택 연도 자료가 없는
   회사도 행에서 사라지지 않으며 `선택 연도 자료 없음`으로 보인다.
3. 회사명을 누르면 실행과 무관한 프로필이 열린다. 공통 8개, 전체 31개, 선택한
   지표의 실제 4개 published FY 흐름을 확인한다. 그래프의 빈 연도는 0으로 잇지 않는다.
4. 회사 2–4개를 선택해 같은 회계연도와 같은 prepared 지표를 나란히 본다. 평균,
   순위, 점수는 만들지 않는다.
5. **지표 안내**에서 31개 지표를 분류·검색하고 선택 FY의 가용 회사 수를 확인한다.
   `조건에 추가`는 최신 v2를 대상으로 새 draft를 열며 저장하거나 실행하지 않는다.
   금액 입력은 백만 USD, 비율 입력은 `%`다.

상단의 **스크리닝**과 **이력**은 기존 R1 기능이다. 과거 v1 실행을 열어도 기업
탐색과 지표 안내의 dataset·FY는 바뀌지 않는다. 직접 bookmark한
`#criteria-title`, `#results-title`, `#history-title`도 해당 작업 화면을 연다.

## 날짜와 누락값

API는 canonical `period_start`, exclusive `period_end`와
`end_convention=EXCLUSIVE`를 유지한다. 일반 화면은 사람이 읽기 쉽게 종료일에서
UTC 하루를 뺀 포함일을 표시한다. 이 변환은 표시 전용이며 회계연도 선택이나 값에는
영향을 주지 않는다. 경계가 없으면 날짜를 추측하지 않는다.

누락값은 항상 누락 사유와 함께 `—`로 보인다. 다른 연도의 값이나 0으로 대체하지
않는다. reported/derived 구분, 단위, definition version, source filing은 prepared
publication에서 복사하며 browser가 재무 공식을 다시 계산하지 않는다.

## 읽기 전용 API

```text
GET /api/explorer?dataset_id=ID&fiscal_year=2025&query=Q&sort=revenue&direction=desc
GET /api/metric-library?dataset_id=ID&fiscal_year=2025&category=PROFITABILITY
GET /api/company-profile?dataset_id=ID&cik=CIK&fiscal_year=2025
GET /api/company-comparison?dataset_id=ID&ciks=CIK1,CIK2&metric_ids=revenue,cfo&fiscal_year=2025
```

첫 두 API의 `fiscal_year`는 생략할 수 있다. 비교는 prepared 회사 2–4개와 기존
지표 1–31개만 허용한다. explorer 정렬은 `company` 또는 화면에 보이는 공통 8개
지표만 허용한다. API 오류는 모르는 dataset·회사·지표·회계연도나 중복 비교 대상을
조용히 무시하지 않는다.

관리자용 8,016개 metadata inventory, CIK·SIC와 기술 근거는 기존 `?mode=admin`
경계에 남는다. ordinary 화면은 SEC 식별자나 raw 코드 대신 회사명, 티커, 사람이
읽는 업종, 재무 기준일, 실제 재무기간과 business missing reason을 보여준다.

## 연결이 끊겼을 때

화면에 과거 제목·버튼이 남아 있는데 회사가 열리지 않거나 `fetch failed`가 보이면
회사 자료부터 의심하지 말고 `127.0.0.1:8884` backend와 Windows
`127.0.0.1:18765` bridge가 모두 응답하는지 먼저 확인한다. 두 서비스가 복구된 뒤
browser를 새로고침해 cached 화면을 교체한다.

오래 유지할 로컬 실행은 backend를 호출 shell의 생명주기와 분리한다. 표준 library
`subprocess.Popen`의 `start_new_session=True`, `stdin=DEVNULL`을 사용하고 stdout과
stderr를 전용 logfile로 보낸다. 이번 runtime의 PID·명령·source·catalog·journal
식별자는 `data/processed/screening_runs/20261009_explorer/dashboard-backend-process.json`,
로그는 같은 디렉터리의 `dashboard-backend.log`에 기록한다. Windows bridge도
`Start-Process`로 launcher가 끝난 뒤 Node가 Windows loopback에 남게 하고,
`screening-explorer-persistent/bridge-process.json`, `bridge.log`, `bridge-error.log`에
소유권과 출력을 기록한다.

둘 다 `127.0.0.1`에만 bind하며 global network 설정, 시작 프로그램과 scheduler를
바꾸지 않는다. 같은 실제 journal을 여는 backend를 중복 실행하지 않는다. 종료나
재시작 전에는 port 번호만 보고 죽이지 말고 process record의 PID·명령·source와
현재 프로세스를 대조한다. PID는 시점별 관찰값이므로 영구 식별자로 쓰지 않는다.
