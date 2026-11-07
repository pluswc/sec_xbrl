# 2026-11-07 이력 선택 삭제·휴지통 선택 복원

## 범위와 단계

사용자가 이력 다중 선택 삭제, 휴지통 다중 선택 복원, 쉬운 전체 선택/선택 해제를 요청했다.
기준 main은 `f8763ce67337117cc0589e8c8bdc0710d97fb4cd`, 구현 branch는
`codex/history-bulk-actions`다. 기존 [개별 휴지통 계약](history-trash-restore-20261107.md)의
복원 가능·비연쇄·raw chain 보존 정책을 그대로 적용한다. 개별 버튼도 유지한다.

구현·focused 검사·ROOT private-copy UAT는 완료했고 독립 검증·새 PR/CI/main/live는
별도 대기다. 이전 PR73은 기준 main에 반영된 기능이며 이번 batch 전달과 구분한다.
ROOT가 원격/운영을 담당한다. Git에는 코드·테스트·문서만 넣고 개인 SQLite/data는 넣지 않는다.

허용 제품 변경은 standalone journal worker와 companion JS/CSS뿐이다. Bridge namespace는
이미 새 고정 경로를 전달하므로 수정하지 않는다. Python119/재무 verifier/계산/packet/
publication/backend/catalog/journal 원본/지침·design system은 변경하지 않는다.

## Atomic API와 기존 기록

- POST `/api/history/batch-delete`, `/api/history/batch-restore`
- Body: `{"items":[{"kind":"REVISION|RUN|DECISION","record_id":"typed ID"}],"expected_version":0}`
- 빈 배열·중복·잘못된 kind/ID·unknown record·추가 필드를 거부한다. 모든 항목을 먼저
  검증하고 **하나의 SQLite transaction**으로 적용한다. 하나라도 실패하면 append0이며
  중간 INSERT 오류도 전체 rollback한다. 성공 결과는 기존 snapshot이다.
- 일부 항목만 이미 목표 상태라면 현재 version이 일치해야 나머지를 처리한다. 전부 이미
  목표 상태인 lost-response 재시도는 stale version이어도 append 없이 성공한다.
- 기존 단건 route도 같은 내부 batch 함수를 사용한다. Schema·event hash material·이전
  hash 연결은 그대로이며 실제 전이는 요청 순서로 append한다. 기존1MiB HTTP/body 한도를
  유지하고 임의 개수 제한을 추가하지 않는다. Cascade/영구 삭제는 없다.

사용자가 이미 원본의 조건4/결과4를 숨긴 **기존 DELETE8개 상태**를 보존한다. 배포나 UAT가
이를 복원하지 않는다. 실제 삭제·복원 검사는 consistent private copy에서만 수행한다.
원본 DB 전체 SHA·기존 table digests/lifecycle 이벤트는 ROOT가 별도로 보호한다.

## 선택과 확인 화면

기존 ledger palette/14·11 type/4px rhythm을 유지한다. 현재 **활성 이력 또는 휴지통**의
행에 native checkbox를 제공한다. `전체 선택`, `선택 해제`, `선택 N개 삭제/복원`과 visible
count가 범위를 안내한다. 입력 자체는16px, native label hit area는 최소40×40px다.
선택 tint는 기존 `--blue-soft`를 사용하고 compact toolbar는 줄바꿈한다.

탭 전환은 선택을 비우고, 새로고침은 없어진 ID만 제거한다. 새 항목을 자동 추가하거나
충돌 뒤 선택 범위를 확대하지 않는다. 빈 선택/미설정/error/pending에서 batch 버튼을 막고
중복 제출을 방지한다. 확인 dialog는 **선택한 ID 배열과 version**을 캡처하며 종류별 개수,
최대5개 이름(각120자)과 나머지 개수를 표시한다. 취소/Escape는 선택·기록을 바꾸지 않는다.
성공하면 선택을 비우고 기존 snapshot 적용으로 현재 결과/조건·메모 badge도 갱신한다.

409 충돌은 새 snapshot으로 유효 선택만 남기고 기존 확인을 stale로 표시한다. 재확인 없이
같은 dialog를 다시 제출하지 않는다. Worker 오류는 기존 local 오류/재연결 경계를 따른다.
재무 조회/save/export handler와 기존 비교·차트 기능은 변경하지 않는다.

Hooks: `[data-history-select]` + `data-history-kind/id`, `#history-select-all`,
`#history-clear-selection`, `#history-selected-count`, `#history-bulk-action`.
기존 `#history-confirm`/cancel/submit, `#history-lifecycle[aria-busy]`를 재사용한다.

## 검사·실제 증거

- Python: `PYTHONPATH=src .venv/bin/python -m pytest tests/screening/test_journal_history.py -q`
  →10 PASS(신규 batch4 + 기존6). 종류 혼합 왕복, 기존 chain/restart/raw table 동일,
  invalid/stale/idempotence를 검사했다. 임시 SQLite trigger로 두 번째 INSERT를 거부해
  첫 INSERT까지 rollback되는 것을 확인했다.
- Node batch: `node --test --test-name-pattern='batch' tests/screening/screening_history_lifecycle.test.cjs`
  →7 PASS/기존6 skip. 선택0/일부/전체·clear·탭·prune·확인 캡처/cancel/pending/conflict/
  empty/error/40px label을 검사했다. 앞선 negative filter가 suite ancestor와 매치되어
  기존6(35초 timeout 포함)도 한 번 PASS했다. 이후 positive batch filter로만 검사했다.
- `uv run ruff check .` PASS. 금융 publication/company audit/backend restart는 반복하지 않았다.
- ROOT private UAT(worker `e51b61f4`, 초기 JS `acf6b2ac`/CSS `711ebf21`): 기존 trash8을
  **copy에서만** 복원한 뒤 mixed batch/부분 복원·메모 raw/display chain·cancel/Escape·
  keyboard Space·refresh prune·invalid1건 append0·현재 결과 제거·reload를 확인했다.
  최종 private version26, 조건4/결과4/메모3/trash0이며 page errors0,760px overflow0이다.
  원본 SHA `3443d40b…`와 사용자의 DELETE8개, Python119/catalog은 그대로였다.
- 마지막 label/tint 보완은 JS `93b2ee22`/CSS `51bda1aa`다. ROOT label-only 확인도 PASS:
  실제40×40, label edge(3,3) 클릭 선택·Space 해제·전체 선택/해제·760px overflow0과
  process restart 후 version26 유지를 확인했다. 초기 full batch/금융 UAT는 반복하지 않았다.
  새 독립/운영 인수는 별도 receipt로 확정한다.

근거: ROOT `work/history_bulk_actions_20261107/{protected-before,preservation-latest}.json`,
Windows visualization `history-bulk-actions-20261107/private-uat.json`과
`private-{active-selected,trash-selected,restored,compact-selected}.png`. 최종 보완 근거는 같은
Windows directory의 `final-label-check.json`, `final-{active,compact-selected}.png`다.
