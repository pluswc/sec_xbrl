# 21사 screening main runtime 전환 — 2026-10-25

## 상태와 승인 범위

사용자는 2026-10-25 기존 21사 screening runtime을 accepted `main`
`bed55f2cfdd9ed11d5d5b027bfac07a979143bf0`의 제품 bytes로 전환하는 작업을 승인했다.
이 문서는 운영 인계 경계와 실제 결과를 기록한다. Root는 private-copy UAT와 live
GET-only 대조 뒤 총괄이 이 runtime 전환을 로컬 수락했다. 독립 문서 검토는 대기 중이다.
이 수락은 50사 재무 준비 완료나 새 데이터 생성을 뜻하지 않는다.

전환은 기존 catalog의 v1·v2 두 dataset ID, 원본 SQLite journal 경로와 export 경로를
그대로 사용한다. 데이터셋, journal, 기존 export, Raw와 재무 publication을 다시 만들거나
변환하지 않는다. Backend는 WSL loopback `127.0.0.1:18766`, Windows bridge는
`127.0.0.1:18765`를 사용한다. Private UAT는 원본 journal의 SQLite consistent copy와
별도 `18866` backend·`18865` frontend에서 수행한다.

## 전환과 확인 경계

표준 실행 명령은 [screening dashboard 이용 가이드](../usage/screening-dashboard.md)의
`현재 21사 runtime의 표준 재시작 경로`를 따른다. 제품 source는
`/home/plusbdw/user_work/projects/sec_xbrl/src`이고 `--require-existing-store`를 유지한다.

Live 확인은 상태·catalog·회사 목록·기존 저장 결과를 읽는 GET 요청으로 한정한다.
명시적 저장과 재열기 동작은 private journal copy에서만 확인한다. 원본 journal에 시험
POST를 쓰거나 restore를 덮어쓰지 않는다. Private copy에서 다음을 대조한다.

- 기존 screen·revision·run·decision 및 두 catalog entry의 재열기
- 새 screen의 명시적 저장, 결과 저장, service 재시작 뒤 동일 record 재열기
- 회사 목록과 선택한 회사의 기존 source trace·값이 전환 전과 같은지
- SQLite integrity, table별 row count와 content digest

Rollback은 새 backend와 bridge를 정지한 뒤, 전환 전 process record의 PID·명령·source
identity를 확인한 이전 accepted source로 기존 journal 경로를 다시 연다. 기존 journal을
backup bytes로 덮어쓰지 않는다. 별도 복원이 필요하면 consistent copy를 새 경로에
복원하고 검증한 뒤 그 경로를 명시한다.

## 결과

Private UAT는 main source를 `18866` backend와 Windows `18865` bridge에서 실행했다.
원본 DB의 consistent copy는 시작 시 4 revisions·4 runs였다. 다음 결과가 PASS였다.

- 21개 회사 detail 열기·닫기와 두 회사 비교
- 기존 조건 4건과 결과 4건의 context 재열기
- 편집과 preview가 DB를 저장하지 않는 경계
- 조건 저장과 결과 저장의 분리
- private backend 재시작 뒤 저장 revision의 정확한 내용과 전체 run JSON 재열기
- JavaScript error와 실패 HTTP 0건

Live 전환에서는 이전 backend PID `936135`와 Windows bridge PID `39812`의 명령·port 및
process identity를 확인한 뒤 종료했다. 새 main backend PID `1630774`는 `18766`에서
`src/sec_xbrl/screening/cli.py`를 사용하고, 새 Windows bridge PID `31944`는 main bridge와
main `PYTHONPATH`로 `18765`를 사용한다. 두 process 모두 기존 catalog, 원본 journal과
`--require-existing-store`를 유지한다. Live browser GET-only 확인은 21개 회사 detail,
두 회사 비교, 기존 4 revisions·4 runs 재열기에서 PASS했고 JavaScript error와 실패 HTTP는
0건이었다.

원본 journal의 전후 SHA-256은 모두
`e486bb5e504d51272837ed9dc00de267529f74a20c40403b0abd85e480be0997`이다. 모든 table의
logical count·digest도 동일했으며 핵심 수량은 3 definitions, 4 revisions, 4 runs,
2 universes다. Catalog bytes도 변하지 않았다. Rollback journal과 private journal copy는
`work/main_runtime_rollout_20261025/` 아래 별도 파일로 보존했다.

운영 근거는 `work/main_runtime_rollout_20261025/`의 `original-before`, `original-after`,
`live-process`, `live-status` JSON과 Windows visualization task
`main-runtime-20261025/`의 `mutate-report`, `reopen-report`, `readonly-report`,
`bridge-18765` JSON이다. 이 결과는 기존 21사 runtime 전환의 로컬 수락 근거이며,
50사 재무 수락이나 runtime data 재생성을 선언하지 않는다.
