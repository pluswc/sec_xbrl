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
| 구현 | 동결 대상 |
| 독립 검증 | 대기 |
| 로컬 인수·운영 | 대기 |
| push·PR·CI·main | 미수행 |

## 구현·검증 기록 (2026-11-13, 인수 대기)

지표 검색 0건은 상세/추가 버튼을 숨기고 선택·입력 draft만 기억한다. draft key는
dataset/publication/FY/metric/definition을 사용한다. 현재 요청 오류만 local status에
표시하며 성공하면 지운다. 연간 안내에서 분기 draft로의 추가는 설명과 함께 거부해
정의를 혼합하거나 기존 실행을 지우지 않는다. 숫자 변환·조건 직렬화는 원래 함수를 유지한다.
이력은 검색/유형을 현재 active 또는 trash 투영에만 적용하고 선택을 초기화한다.
시간은 원문 그대로 표시하고 ID/원문 JSON을 native details에 보존한다.

Writer: 기존 전체 Node 108에 신규 행동 4개(scope/definition draft, filter 선택 경계,
invalid/annual→quarter 추가 실패 보존, 비동기 stale/current 오류 회복)를 추가했다.
최종 전체 Node 112개, `ruff check .`, `git diff --check`가 통과했다. 실행 로그는
writer 작업 근거 `/tmp/phase2-node-final-owned.log`이며 재현은
`node --test tests/screening/*.test.cjs`이다. 리드 초기 실제 브라우저는
3탭×8폭 및 guide/history/screening 7그룹을 통과했으며 최종 스냅샷/독립 검증은 별도다.
실제 이력 삭제·복원/DB 변경은 하지 않는다.
