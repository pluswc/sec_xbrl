# 스크리닝 명시적 저장·다시 열기 완료·로컬 운영 반영 — 2026-10-17

## 최종 상태와 인수 범위

동결 제품 source `e84289a54acae92bee45a9d0224d71133acc13aa`는 별도 읽기
전용 검증에서 **PASS**했고, lead가 2026-10-17 KST에
**LOCALLY_ACCEPTED_EXPLICIT_SAVE_UI_ON_EXISTING_21_COMPANY_SNAPSHOTS**로
판정한 뒤 같은 source를 loopback 운영 UI에 반영했다. 현재 주소는
`http://127.0.0.1:18765/#criteria-title`이며, backend는 loopback
`127.0.0.1:18766`에서 준비된 기존 21사 annual v1 및 expanded R3 publication을
읽는다.

이 완료는 고정된 21사 소비자 UI의 저장 동작과 로컬 운영 반영에 한정된다.
원격 push·PR·remote CI·`main` 병합은 수행하지 않았고, `main`은
`201acf9aec2f8183acb7dd843579938db14236cd` 그대로다. 50사 재무 품질,
분기 재무 준비, 새 회계 정책 또는 Raw 수집 결과를 인수한 것이 아니다.

## 완료된 사용자 동작

- 시험 실행은 preview만 만들며 screen/revision/universe/run/decision/export를
  저장하지 않는다.
- `조건 저장`과 `결과 저장`은 서로 분리되어 있다. 같은 조건·같은 데이터 문맥의
  재저장은 revision을 늘리지 않고, 사용자가 명시적으로 `불러오기`를 눌러야
  저장 조건이 현재 편집 내용으로 복원된다.
- 결과 저장은 preview와 동일한 결과 행, 조건, dataset/publication, 기간과 지표
  버전을 보존한다. 이력의 `결과 열기`는 재실행하지 않고 저장 payload를 연다.
- 조건을 먼저 저장하지 않아도 결과만 저장할 수 있다. 이때 run에 필요한 내부
  조건과 universe를 한 트랜잭션으로 기록하는 `RESULT_BACKING`을 사용하며, 숨김
  backing 조건은 명시 저장 조건 목록에 나타나지 않는다.
- 편집으로 preview가 stale해지거나 저장·불러오기·이력 열기가 진행 중이면 경쟁
  동작을 막는다. 저장 실패는 definition, revision, save-kind, universe, run 중
  어느 삽입 단계에서도 전체 rollback한다.
- 기존 조건 4개 버전과 기존 결과 4개는 보존되며 실제 화면 control에서 다시
  열린다. publication이 바뀌어 저장 문맥과 일치하지 않으면 fail closed하고,
  당시 publication을 복구하면 다시 열 수 있다.

구현 계약과 API·데이터 경계는
[명시적 저장·다시 열기 전달 계약](screening-explicit-save-delivery.md)에 있다.

## 동결 후보와 독립 검증

초기 제품 후보 `d81a15940cef967282a6c9011552cc85ddb88d45`는 구형 static UI
assertion 때문에 독립 검증에서 FAIL했다. 최종 `e84289a…`는
`tests/test_screening_ui.py`만 3줄 추가·1줄 삭제해 그 assertion을 실제 동작
coverage 경계와 맞췄다. 두 후보의 `src/`는 동일하다. 따라서 `e84289a…`의
PASS만 최종 판정이며 과거 FAIL을 소급해 바꾸지 않는다.

독립 검증자는 동결 SHA를 수정하지 않고 다음을 확인했다.

| 항목 | 결과 |
| --- | --- |
| 관련 suite | **404 passed in 10.23s** |
| 정적 검사 | Ruff, `git diff --check`, Windows Node `--check app.js` PASS |
| 무저장 preview | 반복 실행 전후 DB byte SHA와 모든 table logical digest 동일 |
| 저장·복원 | 조건 v1/no-op/v2/명시 불러오기, 결과 저장·재열기, result-only hidden backing PASS |
| 기존 이력 | 기존 조건 4개 버전과 기존 결과 4개를 실제 control로 재열기 PASS |
| 재시작 | backend와 새 Chrome process 재시작 뒤 기존·신규 결과 6개 재열기 PASS |
| 원자성·무결성 | 각 insert failure rollback, stale 거부, backup/restore와 orphan/corrupt context 거부 PASS |
| 실제 화면 | Windows Chrome 1440/1024/768, 일반 click/select/fill/keyboard, 한글과 control 가시성 PASS |

독립 보고서의 선택적 원본 locator는
`work/screening_explicit_save_20261016/independent/e84289a/VERIFICATION.md`이고
SHA-256은
`a2059fc0054e7d6616d65b71b2833f2235b6fb78f1d9818c7e28a85a4136a08e`다.
이 locator가 없는 checkout에서도 위 동결 SHA, 범위, 검사와 한계를 이 문서로
이해할 수 있다.

## 로컬 운영 반영과 journal 보존

lead 승인 뒤 원본 journal의 SQLite consistent backup을 먼저 만들고 additive
schema migration만 수행했다. backup은
`work/screening_explicit_save_20261016/local_rollout_20261017/original_journal_pre_migration.sqlite`,
SHA-256은
`068aca4faa78fe6a611d410bb3893d545766b172bc5b32f99133a735eff86889`다.

migration 전 journal SHA-256은
`fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c`였다.
기존 7개 table의 모든 행과 logical digest를 보존하고 빈
`revision_contexts`, `screen_save_kinds` table만 추가했다. migration 후 SHA-256은
`e486bb5e504d51272837ed9dc00de267529f74a20c40403b0abd85e480be0997`이다.
기존 business row는 3 definitions / 4 revisions / 4 runs / 2 universes /
0 decisions / 0 exports이고, 새 두 table은 각각 0행이다.

운영 반영 뒤 별도 Windows Chrome/context로 GET-only smoke를 수행했다. 실제
41 GET, non-GET 시도 0, page error 0이었고, 회사 상세, 저장 조건 4개 버전의
명시 불러오기, 기존 결과 4개 재열기를 실제 control에서 확인했다. smoke 전후
post-migration journal byte SHA와 모든 table의 모든 행은 동일했다. 독립 smoke
보고서의 선택적 locator는
`work/screening_explicit_save_20261016/production_readonly_smoke/VERIFICATION.md`,
SHA-256은
`a41c7d89d0715d64747cb1d6dbd0e7827912079030b5b289926f76716f65e79d`다.

## 재현과 운영 경계

동결 제품 검증 명령은 다음과 같다.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /absolute/project/.venv/bin/python \
  -m pytest tests/screening tests/test_screening_ui.py -q -p no:cacheprovider
PYTHONPATH=src /absolute/project/.venv/bin/python \
  -m ruff check src/sec_xbrl/screening tests/screening tests/test_screening_ui.py
git diff --check
```

현재 운영 상태 확인은 저장을 만들지 않는 GET과 SQLite read-only mode를 사용한다.
운영 smoke에서는 save, trial/preview, export/download, decision button을 누르지
않았다. 이 완료 문서 작성 단계에서는 제품 test나 browser를 다시 실행하지 않았고,
위 결과는 동결 후보와 운영 반영 당시의 독립 증거다.

## 재무 확대 HOLD

Raw exact-50 수집 완료는 유지되지만, CVX 검증 과정에서 기존 T3 graph의 concept
edge endpoint와 발행 concept node ID가 서로 다른 참조 결함이 확인됐다. actual
CVX payload 감사와 first-five/exact-50 재무 준비는 수락되지 않았으며
`FinancialREADY = false`다. 현재 상태는
**HOLD_FINANCIAL_EXPANSION_PENDING_T3_REFERENCE_DISPOSITION**이다.

상세 결함, 수락된 JNJ component의 제한과 미승인 수리 제안은
[50 issuer T3 참조 결함과 확장 중지](universe50-t3-reference-hold-20261017.md)에
있다. T3 수리·actual CVX 재감사·재무 publication 재생성은 사용자 승인 없이
진행하지 않는다. 원본 SEC Raw는 불변이며 이 UI 완료를 재무 확대의 품질 근거로
사용하지 않는다.

위 HOLD 기록의 `d81a159…` UI 후보와 migration 전 journal `fbc0f760…` 표기는
그 문서가 작성된 시점의 병행 상태로 byte-identical 보존한다. 날짜가 같은 이
완료 기록이 UI 상태의 후속 정정이다. 현재 수락 제품은 `e84289a…`이고, 승인된
additive migration 뒤 운영 journal은 `e486bb5e…`이며 기존 business row는 모두
보존됐다. 이 UI 정정은 T3 HOLD 자체를 해제하지 않는다.

## 문서 closeout 경계

이 후속 closeout은 위 완료 상태와 HOLD를 추적 `docs/`에 승격하는 문서 전용
변경이다. 제품 source, tests, data, journal, runtime과 기존 날짜 기록을 수정하지
않는다. closeout 커밋은 `e84289a…` 제품 검증 SHA를 바꾸지 않으며, 원격 상태도
변경하지 않는다.
