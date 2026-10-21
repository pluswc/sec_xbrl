# 21사 스크리닝 runtime 안정화 전달 — 2026-10-21

## 승인 범위와 상태

사용자는 기존 21사 annual v1·expanded v2 catalog, 명시 저장 journal과 회사
탐색/비교를 재시작 뒤에도 안정적으로 다시 여는 최소 운영 보강을 승인했다. 이
slice의 상태는 **IMPLEMENTED / WRITER SELF-VERIFIED**다. 이 문서를 포함한 local
implementation commit을 독립 검증 대상으로 동결한다. 독립 검증, lead 로컬 인수와
live 전환은 별도 단계이며, push·PR·remote CI·`main` 병합은 승인되지 않았다.

변경 허용 범위는 screening CLI, 관련 tests와 사용/전달 문서다. 재무 formula,
parser, Raw, prepared dataset, journal schema와 UI layout은 바꾸지 않는다. 기존
catalog의 `pilot-21-annual-20261008`와 `pilot-21-expanded-20261008` 두 entry를
모두 유지한다.

## milestone과 수락 기준

milestone은 **SCREENING21_RUNTIME_STABILITY**다.

- `serve --require-existing-store`는 journal 파일이 없거나 regular SQLite screening
  store가 아니거나 integrity/version 검사를 통과하지 못하면 `ScreeningStore`
  생성 전에 실패하고 대상 파일을 만들거나 바꾸지 않는다.
- 옵션을 생략한 기존 `serve`는 새 store를 초기화할 수 있어 새 설치와 tests의
  호환성을 유지한다.
- 시작 로그에서 실제 Python executable, import된 CLI module, catalog/store/export
  절대 경로, dataset ID를 확인할 수 있다.
- 원본 journal을 수정하지 않은 SQLite consistent copy에서 기존 조건/결과를
  열고, preview 무저장을 확인하고, 새 조건/결과를 명시 저장한 뒤 process 재시작
  후 다시 연다. explorer 회사 상세와 2사 비교도 같은 v2 publication에서 확인한다.
- live source 전환은 동결 commit의 별도 read-only 검증 PASS와 lead 판단 뒤에만
  한다.

가정은 기존 journal이 현재 `screening-store-v1`이며 explicit-save additive schema를
이미 가진다는 것이다. unresolved XBRL/accounting case는 없다. 이 slice는 prepared
consumer runtime만 다루며 SEC/Raw/metric 계산을 실행하지 않는다.

## 표준 runtime과 보존 경계

shared Python은
`/home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python`, source는 이 delivery
checkout의
`/home/plusbdw/.codex/worktrees/universe50-delivery-status-r5/sec_xbrl/src`다. catalog,
journal과 export root를 포함한 exact command는
[스크리닝 이용 가이드](../usage/screening-dashboard.md#현재-21사-runtime의-표준-재시작-경로)에
있다. WSL backend는 `127.0.0.1:18766`, Windows browser bridge는
`127.0.0.1:18765`다.

private UAT는 원본
`data/processed/screening_runs/20261009_initial/user_journal.sqlite`를 SQLite backup
API로 consistent copy한 뒤 별도 `work/screening21_stability_20261021` 아래에서만
쓴다. live UAT 전에 같은 방법으로 private backup과 table별 row/logical digest를
기록한다. rollback은 server를 정지하고 accepted `e84289a…` source와 기존 journal
경로로 재시작한다. journal 복원은 기존 파일 overwrite 대신 새 경로에 복원하고
integrity/readback을 확인한 뒤 명시적으로 전환한다.

## 검증과 제외 범위

writer 검증 대상은 새 CLI error-before-write/default-init tests,
`test_explicit_save.py`, `test_screening_store_integrity.py`, 관련 service/HTTP
tests와 screening 범위 Ruff다. explorer/UI 동작은 아래 actual browser UAT로 확인한다.
actual UAT evidence는 untracked work directory에
둔다. network SEC, cached heavy fixture 재생성, 실제 50사 pipeline과 financial
verification은 실행하지 않는다.

writer의 최종 bounded 검증은 CLI, explicit-save, store integrity, service와 HTTP
범위 **47 passed in 10.13s**다. 같은 범위 Ruff와 `git diff --check`도 PASS했다.
첫 sandbox 실행의 HTTP 6건은 socket 생성 권한 때문에 실패했고, 같은 명령을
loopback 허용 환경에서 다시 실행해 전부 통과했다. 제품 실패로 분류하지 않는다.

actual 21사 private UAT는 원본 journal의 SQLite consistent copy
`work/screening21_stability_20261021/private_user_journal.sqlite`만 사용했다. copy 전후
원본 byte SHA-256은 모두
`e486bb5e504d51272837ed9dc00de267529f74a20c40403b0abd85e480be0997`이고 SQLite
integrity는 `ok`였다. WSL `18767` backend와 Windows `18768` private bridge에서
21사 상세, 2사 비교, 기존 조건 4개 버전과 결과 4개 재열기, preview 무저장,
조건/결과의 분리 저장을 확인했다. 같은 copy로 backend를 재시작한 뒤 조건 5개
버전과 결과 5개가 모두 열렸고, 새 조건 내용과 전체 저장 결과 JSON이 재시작 전과
정확히 같았다. page error와 failed HTTP는 0이었다. 최초 reopen harness는 결과를
열 때 접힌 조건 form을 펼치지 않아 timeout됐고, 기존 UI control을 펼치도록 고친
읽기 전용 재실행이 PASS했다. 제품 변경이나 journal reset은 없었다.

R8 first-five 보고서의 상태
`PASS_READ_ONLY_AUDIT_PENDING_LEAD_ACCEPTANCE`와 `actual_financial_ready=false`를
그대로 보존한다. 참조 receipt의 PASS/hash 확인은 formal financial acceptance가
아니다. 50사 확대는 계속 pending이며 이 runtime 안정화로 readiness를 올리지
않는다.
