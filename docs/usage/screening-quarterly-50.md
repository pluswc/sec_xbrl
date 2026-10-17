# 50사 연간·분기 스크리닝 사용법

이 기능은 검증된 dataset v3 catalog가 등록된 뒤 사용한다. 기본 화면은 50사 연간
스크리닝이다. 기존 연간 조건과 실행은 원래 dataset에 결합된 채 그대로 열린다.

## 분기 분석

새 조건에서 빈도를 **분기**로 바꾸고 완료된 calendar quarter-end bucket을 고른다.
예를 들어 `2026년 4–6월에 종료한 분기`는 실제 종료 포함일이 4월 1일부터 6월
30일인 issuer 분기를 모은다. 회사의 fiscal quarter 명칭은 서로 다를 수 있으며
결과·상세에 회사별 fiscal label과 실제 시작·종료일이 함께 표시된다.

분기 전환은 새 unsaved draft다. 조건 저장과 스크리닝 실행을 직접 눌러야 기록된다.
누락 회사는 다른 분기나 최신 값으로 채우지 않고 `자료 확인 필요`와 사유로 남는다.
금액 입력은 백만 USD, 비율 입력은 `%`이고 화면은 재무 산술을 하지 않는다.

회사 상세의 최근 8개 분기 표는 모든 bucket을 같은 열로 유지한다. 빈 셀은 0이
아니다. `보고값`, `승인된 분기 계산`, `파생지표` 표시는 producer가 발행한 source
status다. 112일 같은 확장 분기, basis/recast break, 다중 후보와 TTM 입력 부족도
명시적 gap으로 보인다.

## 읽기 전용 API

```text
GET /api/quarter-periods?dataset_id=ID
GET /api/quarter-series?dataset_id=ID&cik=CIK&metric_id=quarter_revenue&limit=8
GET /api/quarter-comparison?dataset_id=ID&ciks=CIK1,CIK2&metric_id=quarter_revenue&calendar_year=2026&calendar_quarter=2
```

비교는 같은 bucket, definition version, unit, period class와 as-of가 호환되는
prepared row만 나란히 보여준다. 평균·순위·점수나 회계적 동등성을 만들지 않는다.

운영 catalog에는 v1, v2, v3를 함께 둔다. 새 v3가 prospective default여도 과거
run을 열면 원래 annual dataset과 값·trace·export가 유지된다. 실제 journal을
초기화하거나 기존 publication을 덮어쓰지 않는다.

운영자는 검증된 연간 v2와 분기 publication의 root, publication ID, manifest SHA를
`screening-prepare-config-v3`에 고정한 뒤 다음처럼 새 wrapper 디렉터리를 만든다.

```bash
python -m sec_xbrl.screening prepare-v3 --config CONFIG.json --destination NEW_V3_DIR
```

`NEW_V3_DIR`은 반드시 새 경로여야 한다. 만든 v3를 catalog 끝에 추가하되 기존 v1/v2
항목과 journal 파일을 수정하지 않는다. 분기 read-only API는
`quarter-metric-catalog`, `quarter-periods`, `quarter-explorer`, `quarter-series`,
`quarter-comparison` 순으로 지표·고정 8개 bucket·회사별 gap·상세·같은 bucket 비교를
제공한다.

연간·분기 전환은 각각의 저장 전 draft를 유지하지만 dataset, 지표 catalog, 기간 정책은
항상 함께 전환한다. `새 조건`은 현재 v3의 연간 화면에서 시작한다. 과거 annual run을
열면 그 run의 dataset을 유지하고, 이후 분기로 전환할 때에만 현재 v3로 명시적으로
이동한다.

## 사용자 시나리오 점검

배포 후보는 다음 흐름을 합성 publication과 임시 journal에서 확인한다.

1. 50사 연간 탐색이 첫 화면이며 공통 FY와 partial coverage를 읽는다.
2. 분기 빈도로 전환해 지표 정의와 2024Q4–2026Q3 coverage를 확인한다. 전환 전
   annual draft는 돌아왔을 때 복원되고 전환만으로 저장·실행되지 않는다.
3. 명시한 calendar quarter-end bucket과 분기 지표로 조건을 저장·실행한다.
4. 회사 상세의 고정 8개 bucket에서 gap과 reported/derived CFO source kind를 읽는다.
5. 같은 bucket의 회사도 서로 다른 fiscal label·실제 날짜가 보이는 상태로 비교한다.
6. 112일 분기와 null-basis TTM은 값 대신 각각의 확인 사유로 남는다.
7. 기존 annual revision/run을 재시작 후 열고 JSON/CSV/XLSX를 원래 identity로
   내보낸다.
8. 키보드, Escape·focus return과 1440px/1024px 결과표를 확인한다.

분기 발행물은 파일 hash와 별도로 선택 입력의 실제 기간·회사·단위·차원·분석 view·
as-of를 검증한다. 누락된 식별자나 서로 다른 범위를 가진 AVAILABLE 값은 로드되지
않는다. TTM은 네 개의 연속 QTD와 동일 non-null basis가 선언되어야 하며,
미확인 basis·기간 불연속·명시적 break는 값을 임의로 채우는 근거가 되지 않는다.
합성 검증 fixture의 통과는 실제 회사 재무자료의 인수를 의미하지 않는다.

생산자가 준비한 FCF·마진·QoQ·YoY와 동일 시점 비율은 버전이 있는 입력 계약을
함께 제공해야 한다. 소비자는 입력 역할·실제 fiscal 기간·단위·품질·부호와 선택
계보를 검증한 뒤 제공된 결과를 그대로 읽는다. 성장률의 이전 분기는 issuer의
fiscal 좌표로 판단하며, 8개 표시 bucket 밖의 YoY 입력은 상세 계보에만 남는다.
입력 누락이나 부적격 상태를 화면에서 계산으로 보완하지 않는다. null basis가
허용된 단순 산술 결과도 recast 검증 완료나 회계적 동등성을 뜻하지 않는다.

## 연간 입력·표시 기간

연간 metric config의 회사 항목은 선택적으로 `input_years`와 `display_years`를 함께
선언할 수 있다. 50사 확장 계약의 일반적인 형태는 계산 입력 5개 FY와 그중 최신
4개 FY 표시다. 가장 오래된 입력 FY는 첫 표시 FY의 YoY 같은 승인된 공식에만
사용되며 별도의 다섯 번째 표시 연도로 발행되지 않는다. 짧은 공시 이력 회사는
승인된 실제 준비 기간과 같은 더 짧은 두 목록을 사용한다.

두 목록은 오름차순의 중복 없는 정수 FY여야 하고, `display_years`는
`input_years` 목록 끝의 최신 suffix여야 한다. 준비된 analysis manifest의 연도 목록은
`input_years`와 정확히 같아야 한다. metric source와 config의 기간 선언이 다르거나
한 목록만 있으면 reader는 발행물을 거부한다. 두 필드가 모두 없는 기존 config는
준비된 모든 연도를 입력과 표시로 사용하는 이전 동작을 유지한다. dataset v2와
v3는 이 검증을 통과한 annual metric publication을 그대로 연다.

이 호환성은 발행물 형식과 검증 경계만 다룬다. 실제 first-five 및 50사 annual·quarter
publication은 아직 `NOT_READY`이며, 검증된 immutable 입력과 별도 독립 인수 전에는
운영 catalog에 등록하지 않는다.
