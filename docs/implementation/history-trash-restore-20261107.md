# 2026-11-07 저장 이력 휴지통·복원 계약

## 승인과 현재 단계

사용자가 Git 이력관리와 이력 탭 삭제를 요청했다. ROOT는 조건 버전·저장 결과·판단 메모
세 종류를 **개별 항목의 복원 가능한 휴지통**으로 확정했다. 조건을 숨겨도 연결 결과는
남고, 메모를 숨기면 최신 남은 메모가 표시 상태가 된다고 먼저 설명했다. 이전의 삭제
미지원 범위에 대한 이번 사용자 요청의 후속이다. Git에는 코드·테스트·문서만 기록한다.
Journal SQLite, 개인 기록, publication 및 벌크 자료는 Git에 추가하지 않는다.

기준 main은 `7a54b64ed51120f22bd94dfdec2a32efae4005e9`, 구현 branch는
`codex/history-trash-restore`다. 구현·자체 focused 검사와 ROOT의 private-copy browser
검사는 완료했고, ROOT는 동결648f1c22의 독립 PASS와 private 인수를 확인했다. PR73의
첫 CI는 pytest 전에 Ruff3건으로 실패했다. 후속 수정은 SQLite.Row를 dict로 옮겨 hash
입력을 보존하고 잘못된 body/request type을 TypeError로 분류한다. Worker는 기존대로
ValueError/TypeError 모두 HTTP400으로 처리한다. 새 worker의 `uv run ruff check .`와 관련 Python6검사는 PASS했고 기존 Node35초/browser 검사는 반복하지 않는다. 원본 journal migration과
새 main/live 반영은 아직 별도 대기다. 통합·운영 receipt의 지속 위치는
[PR73](https://github.com/pluswc/sec_xbrl/pull/73)이다. 기존648f1c22 독립 보고서
(hash prefix383ac) PASS·ROOT private 인수와 이번 CI 수정의 재검토/CI·live 대기를
구분한다. 이 기록은 병합을 주장하지 않는다.

## 저장·검증 경계

`examples/screening/journal_history.py` 한 모듈이 기존 journal의 추가 테이블
`journal_lifecycle_events`와 표시 projection만 소유한다. 원본 `ScreeningStore`의 읽기
검증·메모 추가를 재사용한다. Python119/재무 verifier/compatibility packet/publication/
계산 정책은 수정하지 않는다. 장기 backend 확장은 pinned source 승인 범위를 바꾸므로
이번 최소 구현에는 포함하지 않는다.

명시적인 기존 절대 DB 경로만 받으며 없는 파일·symlink/부모 alias·불완전 journal·다른
version·다른 lifecycle schema를 거부한다. 설정된 worker 시작 시에만 transaction으로
빈 lifecycle table을 추가한다. 새 DB를 자동 생성하거나 fallback 조회 중 migration하지
않는다. 시작 전 운영자가 consistent backup을 만든다. **SQLite 전체 bytes는 바뀐다.**
기존 raw table의 ID/내용/hash/link/순서와 기존 exports 파일은 바꾸지 않는다.

각 이벤트는 typed record ID, DELETE/RESTORE, 순번·version·시각·이전 hash·event hash를
보관한다. `BEGIN IMMEDIATE` 안에서 현재 version과 상태를 검증한다. 확인한 version이
낡으면 재확인을 요구하고 동일 동작 재시도는 idempotent다. Cascade/renumber/hard purge는
없다. 기존 backup/restore는 DB 전체를 복사하므로 추가 table도 보존한다. 기존 store의
무결성 검사에 더해 companion이 lifecycle schema와 event chain을 별도로 검증한다.

조건은 기존 store와 동일하게 명시 분류가 없으면 legacy explicit로 취급한다.
RESULT_BACKING만 조건 휴지통 대상에서 제외한다. 숨겨진 조건의 raw metadata는 활성
결과를 열 때 기존 backend 검증을 거쳐 내부 dependency로 읽을 수 있다. 화면에서는
활성 saved revision으로 재사용하지 않고 저장 전 복사본으로 표시한다. 숨겨진 결과는
현재 결과·다운로드·메모 저장 상태에서 제거하며 복원해도 자동으로 다시 열지 않는다.

판단 메모는 **전체 원본 체인을 먼저 검증**한 뒤 숨긴 항목을 제외한다. 표시 화살표는
`display_before_state`, raw `before_state`/`previous_event_id`/hash는 그대로다. 숨겨진
마지막 메모 뒤 새 메모도 원본 마지막 이벤트에 연결한다. 복원 시 표시 상태를 재투영한다.

## Canonical 연결과 화면

기존 Windows bridge에 다음 두 옵션을 함께 명시한다. 둘 다 생략하면 기존 financial
relay 동작을 유지한다. 예시의 모든 경로는 운영자가 지정한 절대 경로다.

```text
--history-worker /absolute/project/examples/screening/journal_history.py
--journal-store /absolute/existing/user_journal.sqlite
```

별도 listening port 없이 WSL stdio JSON-lines child를 사용한다. Shell/HTTP 입력으로
process argv·파일 경로·SQL을 만들지 않는다. 기존 Host/Origin/method/content-type/body
한도와 CSP relay를 유지한다. Worker 오류·종료·timeout은 financial relay와 분리한다.

| 경로 | 계약 |
| --- | --- |
| GET `/api/history/capabilities` | 미설정과 설정됐지만 사용 불가를 구분 |
| GET `/api/history` | version, 활성 revisions/runs/decisions, trash |
| POST `/api/history/delete`, `/restore` | kind(REVISION/RUN/DECISION), record_id, expected_version만 허용 |
| POST `/api/history/decisions` | 기존 메모 입력, worker의 같은 DB에 저장 |

설정된 bridge의 기존 목록 GET도 projection으로 읽고 기존 `/api/decisions` POST는
worker로 보낸다. 재무 조건/결과 저장과 상세/context 조회는 기존 backend를 유지한다.
실행·결과 저장·메모·export 등의 명시된 revision/run 참조에 best-effort 가시성 guard를
적용한다. **별도 backend transaction과 atomic한 ACL은 아니다.** 내부18766 직결은
기존 raw backend이며 canonical18765의 휴지통 정책이 자동 적용되지 않는다.

설정된 worker가 중단되면 이력만 unavailable/disabled/retry로 표시한다. Raw 목록으로
fallback하여 숨긴 기록을 되살리지 않으며 재무 탐색 boot는 계속된다. 설정 자체가 없거나
기존 backend 직결에서 capability404이면 기존 조회를 유지하고 삭제·복원은 제공하지 않는다.

기존 ledger 색·14/11 type·native button/dialog를 사용한다. 행에는 종류·이름/버전·시각·
대상 수·ID를 표시하고 사용자 문자열을 escape한다. 삭제/복원 전에 항목과 비연쇄 범위를
확인한다. 취소·Escape·중복 클릭 방지·local 오류/재연결·focus 복귀를 제공한다.
`#history-active`, `#history-trash`, `#history-retry`, `#history-status`,
`#history-confirm`과 행 `[data-history-kind][data-history-id]`, 버튼
`[data-history-delete]`/`[data-history-restore]`가 안정 hook이다.

## 검사와 증거 구분

- 자체: `PYTHONPATH=src .venv/bin/python -m pytest tests/screening/test_journal_history.py tests/test_screening_history_lifecycle.py -q` →7 PASS(합성 Python6 + Node6 cases wrapper1). 세 종류 왕복, legacy4조건, 비연쇄 결과, memo raw/display chain, restart/backup/restore, raw table 동일, typed 입력·schema·stale version 거부, UI cancel/retry/pending/late-open, bridge fail-closed/35초 timeout을 검사했다.
- 관련 기존 Display/index15 Node cases도 구현 중 PASS했다. 금융 실행/save/export 함수 보존 검사는 범위에 맞는 정확한 allowlist를 사용한다. 재무 publication/company audit·backend restart는 반복하지 않았다.
- ROOT 실제 원본의 **consistent private copy** browser 검사: worker `8b35e6c4`, JS `36c08ece`, bridge `0166f615`, CSS `e760c93d`. 취소 무변경/focus, 세 종류 삭제·복원, page reload 지속, 숨긴 조건의 활성 결과와 원래 output_hash, 삭제 결과의 현재 state 제거, raw EXCLUDE/projected HOLD를 유지한 새 private 메모, page errors0을 확인했다. 종료 상태 version10, 활성 조건4/결과4/메모4, trash0. 원본의 개인 기록을 삭제한 검사가 아니다.
- ROOT 근거 위치: Windows visualization `history-trash-restore-20261107/`와 ROOT `work/history_trash_restore_20261107/`의 private fixture/protected-before 기록. ROOT의 실제 private worker/bridge restart 후에도 version10이 유지됐다. 원본 journal SHA와 기존 table digests는 consistent backup과 동일했고 Python119/catalog도 그대로다. 근거는 ROOT `work/history_trash_restore_20261107/preservation-latest.json`, Windows artifact `private-uat.json`, `restart-check.json`과 before/private-active/trash/restored PNG다. 독립 검증·원본 migration·운영 인수는 별도 receipt에서 확정한다.

이전 연간/분기/TTM·선택/추이·기준100 정책과 명시 저장/원본 재무값은 유지한다.
역사적 raw event chain과 export 파일을 영구 삭제하는 기능은 이번 범위에 없다.
