# 재무기간과 공시일의 간결한 표시

2026-11-12 승인. 기준 `e64e11826fd2989718cf2e27c8f6d275a4d9f03e`의
재무·스크리닝 워크벤치를 유지하고, 일반 날짜 표시만 간결하게 한다.
기존 interface system의 숫자 비교 중심·명확한 근거·native controls를 따른다.

일반 정확 날짜는 `2024-09-29`를 `24.09.29`, 기간은
`24.09.29–25.09.27`로 표시한다. FY2025와 회사 회계분기는 그대로 두고
달력연도에서 추론하지 않는다. 회사 기간은 가능하면 첫 줄 FY/기간, 다음 줄
`공시 25.10.31`로 표시하며 여러 공시일도 모두 보존한다. 전체 ISO 날짜/범위는
native title과 접근성 이름으로 유지한다. 각 날짜/범위 토큰은 쪼개지 않는다.

공유 표시 helper는 compact text와 full caption API를 분리한다.
`actualPeriod`, `companyPeriodCaption`, `explorerPeriod`, `comparisonPeriodCaption`,
exclusive-end 변환과 실제 비교/선택 규칙은 수정하지 않는다. 기존 full caption을
짧게 표현할 뿐 새 기간·원값·날짜 계산을 만들지 않는다. 누락·기말잔액·교차 연도·
여러 공시일·conflict 의미를 유지한다.

적용은 탐색 연간/분기/TTM 표, 스크리닝 latest 결과, 프로필의 일반 기간 설명과
개별 지표 기간표, 재무/매출 차트 readout, 회사/peer 비교의 일반 기간, 매출표
caption과 원천 링크다. precise chart title/고정 설명과 펼친 근거·원문·API는
전체 날짜를 유지한다. `#asof` 등 JS 상태로 읽는 DOM 값, 배치 판단/확보 시각과
native input/option 값은 바꾸지 않는다. 공시 재무기간 헤더는 재무기간으로 줄인다.

허용은 app.js/app.css, 관련 Node 검사와 이 계약/계획 등록부다. backend·자료·
생산기·artifact·계산·기록·main·운영 프로세스·원격 작업은 변경하지 않는다.
수락은 누락/instant/duration/교차 연도/윤년/여러 공시일, full precision/escaping,
일반 지표·비교/최근/고정/분기/TTM의 의미 보존과 날짜 토큰 containment다.
전체 Node/Ruff 후 별도 독립 검증·실제 브라우저 인수를 진행한다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-12 표시 구현 승인 |
| 구현 | 표시 구현과 작성자 검사 완료, 커밋 동결 |
| 독립 검증 | 대기 |
| 로컬 인수·운영 | 대기 |
| push·PR·CI·main | 미수행 |

표시 회귀 검사 중 기존 운영본과 날짜 후보 양쪽에서 mouse pin의 Escape 직후
늦은 렌더/포커스 복원이 설명을 다시 여는 baseline race를 확인했다. 리드는
같은 범위의 최소 수정으로 기존 suppressFocus guard를 afterRender의 프로그램
포커스 복원에만 적용하도록 승인했다. pin의 명시적 present 복원은 유지하고
Escape→DOM 교체→포커스 복원이 새 사용자 동작으로 처리되지 않도록 검사한다.
회계·자료·날짜 선택·다른 상호작용 의미를 확장하지 않는다.

작성자 검사: 전체 `node --test tests/screening/*.test.cjs` 98개 및
`ruff check .` 통과. 새 날짜 5개 검사는 유효/누락/잘못된 날짜·교차 연도·윤년,
기말잔액/legacy context와 기존 exclusive-end 결과, 실제 FY·여러 공시일,
full title/접근성 이름·escaping, 반복 표 준비의 DOM 보존, SEC 원천 locator의
동일성을 다룬다. 기존 비교 검사는 visible compact 표시와 exact title을 구분하며
기간 선택·conflict·예외 의미 검사를 유지한다. focus regression은 실제 focusin을
발생시키는 DOM 대체 검사에서 Escape 뒤 재개방하지 않음을 확인한다.
