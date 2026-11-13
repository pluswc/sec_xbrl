# Nasdaq92 운영 패치의 main 통합

2026-11-14 사용자 승인. 기준 main `cdb8f64b837eab1c6373311bbe9d92fd168598e6`,
운영 원본 `6ea4203b8d`를 비교한 별도 branch `codex/nasdaq92-operating-integration`에서
단일 writer가 최소 제품 차이를 통합한다. 지정 구현 모델 unavailable에 대한
기존 승인 fallback을 유지하고 별도 읽기 전용 독립 검증을 요구한다.

## 범위와 의미

동일 cutoff·spine·정의/버전과 고유 CIK 소유권으로 기존 pinned projection을
연결하는 opt-in cohort union, 정확한 원본 보조자료 owner envelope, 실제 최신
분기가 발행 범위 밖일 때의 HOLD, 명시적 분기 범위 worker를 통합한다.
현재 main CSS/system/Phase2 기능·최신 전달 문서는 후퇴시키지 않는다.
운영 계약 [Nasdaq 운영 연결](nasdaq74-operating-20261113.md)의 당시 승인·후보·
보류·실제 인수 기록은 역사로 보존하며 이 통합의 검증과 혼동하지 않는다.

허용: screening cli/cohort_union/explorer/runtime_projection/service, bridge,
app.js의 owner/미준비 표시 차이, 관련 tests, quarter-window 도구와 tracked docs.
전체 운영 tree 복사, 수집·재분석·재발행, 회계/기간/source-compatibility 변경,
실제 journal·자료·runtime·main 변경은 금지한다. 원격 push·PR은 독립 검증·
리드 GO 뒤 수행하며, 기존 untracked17개도 보존한다.

## 수락과 재현

- opt-in union 및 source scope pin 변조 거부, 원래 보조자료 bytes/기간/정의 유지.
- 새 회사의 없는 보조자료 명시, 최신 coverage HOLD와 연간/고정 분기 불변.
- quarter worker는 기존 공개 API의 명시 범위를 사용하며 기존 출력 덮어쓰기 거부.
- 전체 Node, 관련 Python, Ruff/diff와 가능하면 전체 pytest를 수행한다.
- 기존 자료/History 보존 실제 private/GET 검증과 운영 무변경은 리드가 별도 확인한다.

`node --test tests/screening/*.test.cjs`, `ruff check .`, 관련 pytest
`test_cohort_union.py test_latest_source_coverage.py test_nasdaq_quarter_window.py` 및
관련 consumer/bridge/display 검사를 사용한다. 전체 pytest는 root venv와 이
worktree `src`/root PYTHONPATH로 실행한다. 입력 자료는 기존 불변 발행물이며
이 PR 준비를 위해 운영 자료를 재생성하지 않는다.

| 단계 | 현재 상태 |
| --- | --- |
| 승인 | 2026-11-14 명시 범위 통합 승인 |
| 구현 | 선택적 통합 완료·로컬 commit 동결 |
| 독립 검증 | `41dbd0166838f98ba1c8f60e24df867680c50f9c` 별도 reviewer PASS |
| 리드 인수 | 2026-11-14 LOCALLY_ACCEPTED · 기존 main History 한계 명시 |
| 이번 runtime 전환 | 미수행·금지 |
| push / PR / CI / main 병합 | 리드 push·PR GO, 실행·원격 CI·main 병합은 아직 미수행 |

## 통합 자체 점검과 리드의 읽기 전용 관측

선택한 product/test 파일은 운영 `6ea4203b8d`와 byte 동일하다. main의 CSS,
interface system 및 Phase2 계약은 변경하지 않았다. Node 전체 122개, 관련 Python
12개, `ruff check .`, `git diff --check` PASS. 전체 pytest는 root venv와 이
worktree 소스/POLARS_MAX_THREADS=2로 완료했다: **2983 passed, 38 skipped,
1 failed, 29 warnings, 285.48s**. 전체 통과가 아니며 아래 baseline 한계를 구분한다.
Node 로그 `/tmp/nasdaq92-node.log`, focused Python 로그
`/tmp/nasdaq92-focused-python.log`, 전체 로그 `/tmp/nasdaq92-full-python.log`다.

latest-source-coverage는 optional/partial evidence다. 현재 신규42 중39 records만
있고 빠진 ADP/PANW/LITE는 승인된 기존 분석 재사용3과 일치한다. 92개사 전체의
최신 header를 재감사한 것이 아니다. 리드는39개 owner/analysis pins78개의 현재
hash 일치와 WDC 단독 HOLD를 읽기 전용으로 확인했다. 기존50 growth 원본 응답
정확성, UI92/FANG 5 charts/MSFT 매출/ABNB2026Q2/WDC 분기·TTM HOLD도
GET-only 관측으로 확인했다. 이는 통합 소스의 독립 검증과 별개의 운영 관측이다.
증거 위치:
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/nasdaq92-pr-integration-20261114/`.

리드는 기존 live에서 Phase2 8그룹/3탭×8폭과 매출 NFLX/AAPL/AMZN/MSFT
4사례의 원본·출처를 확인했다. History API baseline 및 지정 journal/growth/revenue
SHA가 같았다. 매출 검사 첫 실행의 URL 인자 오류는 하네스 수정 뒤 PASS였으며
제품 변경으로 처리하지 않았다. 이 통합에서는 새 배포나 자료 재발행을 하지 않았다.
운영 보존 관측을 전체 Raw bytes 전수 검증으로 확대해 주장하지 않는다.

## 전체 검사에서 재현된 기존 main 한계

유일한 실패는
`tests/integration/test_history_quarters_cached.py::test_default_history_build_connects_reported_and_derived_consumer`다.
`history.py:2117`의 엄격한 복구 inventory 검사에서
`ValueError: recovery unexpected or missing staged files/directories`가 발생했다.
변경하지 않은 main `cdb8f64`에서 동일 명령/개별 검사로 **1 failed, 9.87s**를
재현했다(`/tmp/nasdaq92-baseline-history.log`). 이 통합은 history.py를 변경하지 않았다.
기존 [PR85](https://github.com/pluswc/sec_xbrl/pull/85)의 빈 `.chunks` 정상 발행 정리와
관련된 한계로, 2026-11-14 GitHub 읽기 전용 조회에서 PR85는 OPEN·merged=false,
head `b94b751a8b`였고 현재 main에 포함되지 않았다. 이 별도 수정이나 원격 병합을
이번 scope에 끼워 넣지 않았다. 따라서 이 작업의 전체 pytest PASS를 주장하지 않는다.

전체 실행 명령은 이 격리 checkout에서
`PYTHONPATH="$PWD/src:$PWD" POLARS_MAX_THREADS=2 .venv/bin/python -m pytest -q`였다.
root interpreter를 가리키던 임시 `.venv` symlink는 테스트 때만 사용하고 종료 후
제거했다. 테스트 출력/pytest tmp만 생성했고 기존 운영 데이터·journal을 수정하지 않았다.

## 최종 통합 인수 (2026-11-14)

제품 동결은 `914cfe8a9e273505d7cc24c59e26210c564b4f68`, 독립 대상은 문서 후속
포함 `41dbd0166838f98ba1c8f60e24df867680c50f9c`다. 별도 reviewer가 **Node 122,
관련 Python 12, Ruff, diff PASS** 및 product tree 동일성·partial coverage 경계를
확인했다. 리드는 위 전체 pytest의 유일한 기존 main 실패를 한계로 명시하여
LOCALLY_ACCEPTED하고 push·PR GO를 내렸다. 이 완료 문서 commit은 소스 동결과
별도이며 원격 전달은 리드가 수행한다. 현재 origin/main은 `cdb8f64`에서 추가
변경이 없다고 리드가 확인했다. PR 생성·CI 성공·main 병합을 미리 주장하지 않는다.

운영은 기존 18765→19072/PID48788을 유지했다. 리드의 보존 근거는 위 증거 폴더의
`source-equivalence.json`, `source-integrity.json`, `preservation-before.json`,
`preservation-after.json`, `history-before.json`, `history-final.json`,
`live-browser-acceptance.json`, `live-phase2-report.json`, `live-endpoint-report.json`다.
History API baseline exact 및 journal SHA256
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`, 지정 growth/revenue
artifact hash가 유지됐다. 제품 통합은 운영 Python/bridge/JS와 동일하며 main의
CSS/system/Phase2 최신 문서를 보존했다. 실제 저장/복원·새 발행/수집·runtime
재시작은 이번 통합에서 수행하지 않았고 원본·History 전수 재감사를 주장하지 않는다.
