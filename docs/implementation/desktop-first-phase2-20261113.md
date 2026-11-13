# 데스크톱 2차 — 전체 탭의 인접 작업면

2026-11-13 승인, 기준 main `0a89d5cfda`(PR91 병합). 단일 writer와 별도 독립
검증을 유지한다. 기존 탐색/분석·날짜·매출·저장 이력을 보존하고 전체 탭을
점검한 뒤 지표 안내·이력 조회·스크리닝 배치를 이번 우선 개선으로 선정했다.

## Interface-design checkpoint와 선정

투자자는 지표 뜻을 읽고 정확한 조건을 추가하며, 실행 기준과 결과를 비교하고
저장 기록을 찾아 재사용한다. paper/ink/slate/blue/amber, 14px 본문·40px 제어
목표와 4px 간격을 유지한다. 카드 장식 대신 이름·값·조건·근거를 가까이 둔다.
탐색/상세/비교/매출은 1차의 원래 목록 복귀·정렬·고정 설명을 회귀 검증한다.
이번에는 계산·출판·추가 기간 정책·기록 schema 및 새 저장 정책을 구현하지 않는다.

- 지표 안내: 반복 카드를 목록+선택 상세로 바꾼다. 검색·카테고리와 전체 지표,
  의미/활용/단위/가용성·조건 추가를 유지한다. 현재 annual catalog의 의미를
  바꾸지 않는다. 입력 draft는 dataset/year/definition version/metric별로 격리해
  필터/늦은 응답 중 선택·입력을 보존한다. 추가 validation 실패는 기존 결과를
  지우지 않으며, 검증 뒤 기존 clearResult/추가 경로를 사용한다.
- 이력: native 검색·유형 필터와 원장 행을 제공한다. 필터 변경은 선택을 명시
  초기화하고 전체 선택은 현재 보이는 범위에만 적용한다. 긴 ID·원문은 details로
  접근하고 시간 원문을 보존한다. 기존 active/trash·bulk 확인·version/epoch/
  pending·오류 fail-closed를 유지한다. 활성 조건/결과만 기존 읽기·불러오기로 연결한다.
- 스크리닝: 1600px 이상에서 조건과 결과를 인접하게, 1440px 이하에서는 읽기
  좋은 stack으로 둔다. 기존 노드/핸들러/직렬화·열·선택을 유지한다. 결과 가까이
  실행·수정 draft·저장 가능 상태를 표시하고 표에 남은 높이를 사용한다. preview,
  조건 저장, 결과 저장, 판단 기록은 원래 명시적 조작이며 자동 저장하지 않는다.

허용은 app.js/app.css, tests/screening, system.md, 이 계약/planning과 1차/날짜
계약의 병합 상태 기록이다. backend·계산·원본·artifact·DB·기록·runtime·main·
원격 작업은 변경하지 않는다. 숨은 기록을 raw fallback으로 노출하지 않는다.

수락: 1920/1440/2560·effective 125/150% 대응·390px에서 접근/밀도/내부스크롤,
지표 선택·입력 범위/실패 보존, 이력 필터/선택 경계·취소/충돌/오류,
스크리닝 직렬화·결과 상태/저장 재열기, 기존 탐색·비교·날짜·매출과 DB bytes 보존.
전체 Node/Ruff 및 리드의 실제 브라우저와 독립 검증은 별도 단계다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-13 2차 표시 구현 승인 |
| 구현 | 소스 `745bc76e3a4721de8d7734eb534ac0afc7cba212` 동결 |
| 독립 검증 | 별도 reviewer Node 116/Ruff/diff PASS |
| 로컬 인수·운영 | 2026-11-13 LOCALLY_ACCEPTED · 리드 실제 운영 인수 PASS |
| push·PR·CI·main | 미수행 |

## 구현·검증 기록 (2026-11-13, 로컬 인수 완료)

지표 검색 0건은 상세/추가 버튼을 숨기고 선택·입력 draft만 기억한다. draft key는
dataset/publication/FY/metric/definition을 사용한다. 현재 요청 오류만 local status에
표시하며 성공하면 지운다. 연간 안내에서 분기 draft로의 추가는 설명과 함께 거부해
정의를 혼합하거나 기존 실행을 지우지 않는다. 숫자 변환·조건 직렬화는 원래 함수를 유지한다.
이력은 검색/유형을 현재 active 또는 trash 투영에만 적용하고 선택을 초기화한다.
시간은 원래 timezone을 유지한 날짜·분 캡션으로 표시하고 full ISO를 title/aria 및
ID/원문 JSON native details에 보존한다. timezone 없는 값은 추정하지 않고 원문을 표시한다.
기본 이력은 제목+시간/상세의 두 줄 원장이며 toolbar도 가까운 가로 배치를 사용한다.

Writer: 기존 전체 Node 108에 신규 행동 8개(scope/definition draft, filter 선택 경계,
invalid/annual→quarter 추가 실패 보존, 비동기 stale/current 오류 회복, 시간대 캡션 보존, 실행 최신성 분리, epoch 취소 열기, scope 전환 실패 차단)를 추가했다.
최종 전체 Node 116개, `ruff check .`, `git diff --check`가 통과했다. 실행 로그는
writer 작업 근거 `/tmp/phase2-node-review-final.log`이며 재현은
`node --test tests/screening/*.test.cjs`이다. 리드 초기 실제 브라우저는
3탭×8폭 및 guide/history/screening 7그룹을 통과했으며 최종 스냅샷/독립 검증은 별도다.
실제 이력 삭제·복원/DB 변경은 하지 않는다.

독립 사전 검토의 세 경계는 표시 전용 상태로 보완했다. 실행 결과 최신성은 조건의
저장 여부(`S.dirty`)와 분리해 현재 run의 편집 여부만 추적한다. 이력 조건 열기는
기존 epoch 소유 opener에 맡기고 취소 후 탭을 강제로 전환하지 않는다. 성공한 안내
응답의 dataset/publication/FY를 pin하여 새 범위가 로딩/실패 중이면 이전 상세와
추가를 차단한다. 같은 범위 검색 실패는 기존 자료와 명시적 오류를 함께 유지한다.

## 최종 로컬 인수와 증거

별도 독립 reviewer는 동결 소스 `745bc76e3a`에서 Node 116개·Ruff·diff PASS를
확인했다. 리드는 동일 자산의 preview와 실제 `http://127.0.0.1:18765`에서 다음을
검증했다. 독립 코드 검증과 아래 실제 브라우저 검증은 서로 다른 역할의 근거다.

- 2차 8그룹: 3탭×8폭 overflow 없음, 정확한 guide threshold/실패 보존/FY scope
  차단·복구, history 필터/보이는 전체 선택/확인 취소/503 fail-closed 회복,
  screening 수정 draft와 실행 결과 구분 PASS.
- 기존 desktop 배치·interaction 5·race 5, 날짜 24 context, workbench 10, 정렬
  3 basis, screening 7, 매출 4사례, 50회사 정확한 endpoint와 409/400 PASS.
- History API는 변경 전 baseline과 정확히 같고 SQLite SHA256은
  `3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로 동일하다.
  실제 조작은 GET/preview와 삭제·복원 확인 취소만 수행했다. 실제 삭제·복원
  수명은 unit fixture로 검증했으며 운영 기록을 변경하지 않았다.

운영 frontend PID 45320, backend 19070 유지. JS SHA256
`0cf9ea1ae09b0274074954245154254bcff6334e795f68482533e75362c0df32`, CSS
`366ca056538fddf305f4dbcddef22e2e90616a4ea757b89bd40a3261f6416596`가 인수 소스와
같다. growth `a9df827…62938`, revenue `db71131…b231` artifact는 기존 그대로다.
125/150% 검증은 equivalent effective CSS viewport이며 실제 native zoom 검증은 아니다.

리드 근거 위치는
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/desktop-first-phase2-20261113/`다.
`local-acceptance.json`, `source-pin.json`, `live-phase2-report.json`, `live-desktop-*.json`,
`live-dates-report.json`, `live-workbench-report.json`, `live-sort-report.json`,
`postmerge-live-screening-report.json`, `live-revenue-report.json`,
`live-endpoint-report.json` 및 운영/restart 기록 `bridge-growth.json`을 참조한다.
검증 범위는 위 API/SQLite/지정 artifact 및 main·기존 untracked 17개 목록의
보존이며, 모든 raw 파일의 전수 바이트 검사를 주장하지 않는다.
이 문서 완료 commit은 구현 소스 SHA와 별도다. 기준 main `0a89d5cf`, 로컬 branch
`codex/desktop-first-phase2`이며 이 단계의 push·PR·원격 CI·main 병합은 미수행이다.

전탭을 감사한 뒤 반복 카드가 큰 지표 안내, 검색/선택 경계가 필요한 이력, 조건과
결과가 멀어진 screening을 이번 우선순위로 구현했다. 공통 탭 스크롤 기억과
저장 결과 비교 배치 추가 정리는 낮은 우선순위의 미구현 후보이며 이번 인수나
향후 자동 구현으로 간주하지 않는다. 기존 탐색/상세/비교/매출은 회귀 범위다.

## 원격 전달 후속 (2026-11-13)

사용자가 push·PR 전달을 승인했다. 리드는 origin/main `0a89d5cf`가 기준 이후
변경되지 않았음을 확인하고, 문서 완료 head `5b814b944d`에서 별도 독립
Node 116/Ruff/diff PASS 및 인수 소스 `745bc76e3a`와 코드 동일성을 재확인한 뒤
branch를 push하여 [PR #92](https://github.com/pluswc/sec_xbrl/pull/92)를 열었다.
PR은 OPEN·main 미병합이며 원격 CI는 이 기록 시점 대기/진행 중이다. 최종
원격 검증 근거는 [PR92 최신 head checks](https://github.com/pluswc/sec_xbrl/pull/92/checks)다.
merge는 승인·수행하지 않았다. 이 문단은 위 로컬 인수 당시의 원격 미수행 기록을
후속 갱신하며, 과거 검증 상태를 소급 변경하지 않는다.

이번 전달에서도 리드는 live JS/CSS가 인수 자산과 같고 History API가 baseline과
정확히 같으며 SQLite·지정 growth/revenue hash가 그대로임을 재확인했다.
소스·runtime·자료·main은 이 문서 갱신에서 변경하지 않았다.
