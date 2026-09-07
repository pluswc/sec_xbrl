# 기업 등록·검토 결정·재무 분석 표

## 목적과 완료 기준

티커를 코드에 추가하지 않고 기업 등록표에 추가하여 같은 경로로 자료를
수집하고, 최근 완료된 회계연도 또는 지정 회계연도를 조회한다. NVDA
FY2024–2026, AMD FY2023–2025의 12개 분기가 최초 실제 대상이다.

`python -m sec_xbrl.company_reports --admin /absolute/admin/path ...`가
공통 경로다. Python 3.12 환경에서 실행한다.

1. `init`: `companies.csv`, `decisions.csv`를 생성한다.
2. `register NVDA --publication /absolute/panels --years 3`: 보유 자료를
   등록한다. `register NVDA --years 2`처럼 기간만 수정하면 기존 자료 위치를
   유지한다. 명시적 회계연도는 `--fiscal-start 2024 --fiscal-end 2026`이다.
3. `report --review-as-of 2026-09-07`: 현재 등록표를 이용해 새 결과를 만든다.
4. `refresh --as-of 2026-09-06 --review-as-of 2026-09-07 --workspace /absolute/work`
   는 기존 공시 발견 → 원문 적재 → 분석 자료 생성 → 같은 표 출력 경로를
   실행한다. 보유 스냅샷은 `--source-run`, 공시 목록은 `--submissions-root`로
   반복 지정한다. `--offline`은 발견 단계의 네트워크 호출을 금지한다.
   원문 미보유 시 적재 단계는 SEC_USER_AGENT가 필요하며 실패를 그대로
   전달한다. 이 경우 가짜 MISSING 결과로 대체하지 않는다.

`report`는 기존 자료 조회다. SEC 최신 자료 수집을 의미하지 않으며,
재무 기준일은 각 자료에 기록된 `selection_as_of_date`다. 관리자 검토
기준일 `review_as_of`는 별개이며 나중에 확인한 오류를 이전 검토 시점에
소급 적용하지 않는다. `refresh`의 재무 기준일은 기존 history 선택 경로로
전달된다. 원문 보존 및 기존 수집기의 계약은 바꾸지 않는다.

## 관리자가 바꾸는 항목

`companies.csv`의 열:

- `active`: `true`/`false`; 기존 기업의 처리 중지·재개.
- `ticker`: 대문자 티커. 새 기업 등록도 같은 방식이다.
- `recent_fiscal_years`: 최근 완료된 회계연도 수. 진행 중인 회계연도 제외.
- `fiscal_start`, `fiscal_end`: 둘 다 지정하면 명시적 연도 범위 우선.
- `publication`: 검증된 분석 자료의 절대 경로. 비어 있으면 먼저 refresh.

관리자가 직접 CSV를 편집해도 같은 유효성 검사를 거친다. 자료에 없는
연도나 기업을 요청하면 수집/생성 필요 오류이며 빈 값의 표로 성공하지 않는다.

`decisions.csv`는 삭제·수정하지 않고 결정을 추가하는 기록이다:

- `decision_id`: 결정마다 새 ID.
- `issue_id`: 같은 문제의 이후 결정을 연결하는 ID.
- `ticker`, `accession`, `concept`: 필수 정확한 대상.
- `axis`, `member`: 세부 구분 한 쌍, 또는 둘 다 빈칸. 빈칸이면 해당 공시의
  해당 항목 전체이며 기업 전체에는 적용되지 않는다.
- `decision`: `WARN` 주의, `BLOCK` 분석 표의 값 보류, `RELEASE` 해당 문제 해제.
- `reviewer`, `reason`, `evidence`, `known_at`: 검토자, 이유, 근거, 확인 시각 필수.
  `2026-09-07T15:30:00+09:00` 같은 시간대 포함 시각을 권장한다. 기존 날짜만
  적힌 값은 한국 시간 해당 날짜 00:00으로 해석한다. 검토 기준일은 한국 시간
  해당 날짜의 끝까지 포함하며 다음 날 00:00은 제외한다.

한 issue의 대상 범위를 바꾸지 못한다. 같은 실제 시각의 두 결정은 순서가
모호하므로 실패한다. 같은 날의 이후 결정은 실제 시각을 기록해 즉시 반영한다.
해제는 앞선 문제가 있어야 하며 다른 issue의 보류나 기존 항목
연결 검토를 해제하지 않는다. 과거 성공 결과에 기록된 결정은 수정·삭제
할 수 없다. 최초 적용 AMD 문제는 원문 대조 근거가 확인된 6개 공시 ×
Client/Gaming/DataCenter 부문 매출만 대상으로 한다. Embedded 및 전체
매출은 해당 보류 대상이 아니다. 원래 태그 이름이나 원문 값은 바꾸지 않는다.

회사별 `review_queue.csv`는 현재 주의/보류 값의 대상 항목·공시·구분을 미리
채워준다. 관리자는 근거를 확인하고 결정 ID·검토자·결정·확인 시각을 작성한
뒤 `decisions.csv`의 해당 열로 옮긴다. 대기 목록 자체는 자동 적용하지 않는다.
이 결정은 사용 주의/보류/해제만 관리하며 항목 연결 승인, Q4 계산 승인,
재작성 재무제표 비교 승인을 뜻하지 않는다. 다중 구분의 각 축은 별도 정확한
검토 범위이며 형제 구분까지 해제하지 않는다. typed 구분은 명시적 Member
결정으로 위장하지 않고 원 출처에서 검토한다.

## 자료와 화면의 분리

`materialize_quality`는 선택 값에 검토 상태와 분석 사용 가능 값을 덧붙인다.
원문 값과 계산 결과는 변경하지 않는다. 계산된 분기는 기록된 입력 출처의
보류도 이어받으며 재계산하지 않는다. `render_company`는 이 결과를 표시한다.
추가 custom Q4, 증감률, 비중 계산 또는 항목 병합은 하지 않는다.

각 실행은 `runs/<고유 ID>`에 저장된다. 적용한 기업/결정 CSV의 **읽은 그대로의
바이트**, 자료 위치·manifest 식별, 별도 검토 기준일, 회사별 `data.json`,
`cells.csv`, `index.html`을 함께 보존한다. 이전 결과는 덮어쓰지 않는다.
중간 실패 디렉터리는 `.partial-`이며 성공 결과로 취급하지 않는다.

표는 손익·재무상태·현금흐름·자본변동을 분리한다. 해당 기간에 선택된 값의
재무제표 근거를 사용한다. 세부 차원/주석은 별도로 모두 접근 가능하며
추가 하위관계의 원래 근거는 data.json의 binding/navigation에 보존된다.
화면의 구분은 접근을 돕는 묶음이지 회사 고유의 새로운 부모·자식 관계가 아니다.

분기·연간·6개월/9개월 누적·기말 잔액을 섞지 않는다. Raw Arelle의 종료/시점
날짜는 배타 경계이므로 화면 말일은 하루 전이며 원문 경계도 보존한다.
USD 단독 금액만 백만 단위로 표시하며 CSV의 값은 원 단위다. 각 셀의 단위를
확인할 수 있다. 빈칸은 0 또는 미공시로 단정하지 않는다. 기업별 세부항목
Q4 빈칸에는 분기 계산 미승인/미제공을 알린다.

## 검증

일반 단위 테스트는 네트워크 없이 실행한다:

```sh
python -m pytest tests/test_company_reports.py -q
```

실제 NVDA/AMD 및 추가 AAPL, 기간 변경, 이전 결과 보존 검증은 명시적으로
보유 publication을 지정한다:

```sh
SEC_XBRL_REPORT_PUBLICATION=/absolute/panels python -m pytest tests/test_company_reports.py -q
```

원격 게시 승인 범위가 없으므로 이번 작업은 로컬 커밋 동결 후 독립 검증한다.
기존 delivery-workflow의 원격 push 선행 단계만 승인 대기 상태로 남긴다.
