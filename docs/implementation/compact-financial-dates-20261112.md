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
| 구현 | 통합 `a19661910d310a6fa3c67d4eca77cc7470722a20` 동결 |
| 독립 검증 | 통합 소스 별도 Node 100개·Python 42개·Ruff PASS |
| 로컬 인수·운영 | LOCALLY_ACCEPTED 2026-11-12 · 리드 18765 적용 PASS |
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

## 기존 인수된 매출 기능의 통합 의존성 — 2026-11-12

배포 가드는 운영 자산이 바뀐 것을 감지해 이전 프로세스를 중지하기 전에
중단했다. 따라서 기존 운영본을 덮어쓰지 않았다. 리드는 이미 인수·운영 중인
매출 완전성 브랜치 `0fbc19e346`(인수 소스
`3c80c529be646fddfbbdf9137cc19db1513a4514`)의 통합을 승인했다.
날짜 브랜치에 merge로 포함하며 incoming 생산기·analytics·검사는 그대로
보존한다. 표시의 누락 사유·계산 Q4/원천 구분·850px 파생 표도 유지한다.

운영 의존성은 당시 PID 44272/backend 19070과 이미 고정된 새 매출 artifact
`db71131a490b479278e49a4708a9518a321212df0efa3a09cffbf9cdbd53b231`이다.
이 구현자는 그 artifact를 재계산하거나 경로·계보·회계 정책·runtime을 변경하지
않는다. 리드가 이 고정 경로를 보존해 재검증·적용을 판단한다. 충돌은 양쪽
계획 추가와 CSS 추가, 매출표의 compact caption/계산 안내 병합뿐이며 양쪽
동작을 보존한다. 날짜 기능의 운영 인수와 원격/main 전달은 아직 별도 단계다.

## 최종 통합 운영 인수 — 2026-11-12

검증·운영 소스는 `a19661910d310a6fa3c67d4eca77cc7470722a20`이다.
이후 완료 문서 커밋과 구분한다. incoming `0fbc19e346`의 생산기·analytics·
검사·매출 계약 7개 파일은 정확히 같고 날짜/포커스 표시와 계획의 텍스트만
통합했다. 작성자의 통합 Node 100개·Ruff와 별도로 독립 검증도 Node 100개·
Python 42개·Ruff를 통과했다. 앞선 98개는 날짜 단독 후보의 검사 수다.

리드의 integrated-final-preview 및 integrated-live 매출 4개 경우가 통과했다.
첫 MSFT 검사는 검사 코드의 기업 전환 완료 대기가 빠져 시간 초과했으며,
`S.profile.company.cik` 완료를 기다리도록 검사만 보완한 뒤 모두 통과했다.
이로 인한 제품 소스 수정은 없다. 날짜 24개 context/6개 그룹은 축약 표시와
full ISO title/접근성 이름, 토큰·범위와 반복 렌더 보존을 확인했다. 재무
워크벤치 10개 그룹(다섯 화면 폭의 4/3/2/1열과 고정 설명·포커스), 스크리닝
7개 그룹의 정확한 응답/상태, 연간·분기·TTM 정렬도 통과했다. Endpoint는
50개 회사 정확한 결과와 잘못된 범위의 409/400을 통과했다.

18765는 당시 새 PID 10580으로 전환했고 backend 19070과 incoming 매출
artifact `db71131a490b479278e49a4708a9518a321212df0efa3a09cffbf9cdbd53b231`의
기존 고정 경로를 유지했다. History API는 변경 전과 같으며 SQLite는 전후
byte-identical이다. SHA-256:
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`.
날짜 표시 때문에 자료·기록·artifact를 재계산하거나 수정하지 않았다.

선택적 실행 증거는
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/compact-financial-dates-20261112/`다.
`integrated-final-preview-report.json`, `integrated-live-report.json`,
`live-dates-report.json`, `live-workbench-report.json`,
`postmerge-live-screening-report.json`, `live-sort-report.json`,
`live-endpoint-report.json`, `history-final.json`이 리드 실제 검사를 기록한다.
`source-pin.json`·`bundle-hashes.json`은 소스/자산 pin이며 `bridge-growth.json`은
현재 bundle의 전체 재시작 인자다. 원격 push·PR·CI·main 병합은 이 작업에서
수행하지 않았다. 앞선 대기 문구는 해당 단계 당시의 기록이다.

## 원격 전달 승인과 최신 main 통합 — 2026-11-13

사용자는 push와 PR을 명시 승인했다. 원격 병합은 승인 범위가 아니다.
`origin/main`의 `72575d89f578d6c0ae01528753d06a469141a1b3`를 일반 merge
`1dfc42b3b04cc3b9ea826afcb22f5ff1328d232b`로 통합했다. 충돌이 없었고,
통합 tree는 직전 로컬 인수 문서 HEAD `ee1bb723cd95947fb77e0b6fbee691df2207bf42`와
정확히 같다. upstream 매출 변경은 이미 포함돼 있어 UI·계산·backend 변화가 없다.

인수된 실행 소스 `d19638fae378a4ef91764d4e291bf0ed3b33958f`의 UI 자산은
그대로다. JS SHA-256은 `802bef69a263758269181179fa794148ac8a77e2229aabdceea2955045e1eb0b`,
CSS는 `6be818971561405eb3f33d943ae8967b94b4264ca1d6900656b82e066e118f7a`다.
이 통합의 별도 독립 재검증과 원격 push·PR·CI는 기록 시점에 대기다.
작업 브랜치를 main에 병합하거나 운영·자료·기록을 변경하지 않았다. 앞선
로컬 인수와 당시 원격 미수행 문구는 역사적 기록으로 보존한다.

## PR 전달 상태 — 2026-11-13

통합 전달 HEAD `bf91b303eac3df2f256dffa4c377457ed55ecdec`는 별도 독립
Node 108개·Ruff·diff, 최신 main 포함 및 인수 UI 동일성 검증을 통과했다.
리드가 push하고 [PR #91](https://github.com/pluswc/sec_xbrl/pull/91)을 열었다.
PR은 OPEN이며 main에 병합하지 않았다. 원격 CI는 기록 시점에 진행 중이고,
최종 근거는 [PR #91 최신 head checks](https://github.com/pluswc/sec_xbrl/pull/91/checks)다.

리드는 실제 운영 JS/CSS가 기존 인수 hash와 같고 History API가 baseline과
정확히 같음을 재확인했다. SQLite SHA-256도
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로 같다.
앞선 로컬 전용/전달 대기 문구는 당시 기록이며 이 항목이 원격 전달 상태를 갱신한다.
