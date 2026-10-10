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
