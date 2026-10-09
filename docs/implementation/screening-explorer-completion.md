# 스크리닝 기업 탐색 R2 완료·로컬 인수 기록

## 1. 최종 상태

기준일은 **2026-10-09 KST**다. 최종 제품 source
`7e7ec154e15ed88a14c2a74d89042c39fa3fadbf`는 별도 읽기 전용 검증에서
**PASS**했고, lead가 같은 날 R2를 **LOCALLY_ACCEPTED**로 판정했다. 실제
loopback runtime도 이 source와 기존 R3 catalog로 전환했다.

이 상태는 로컬 제품 인수다. 사용자의 직접 한국어 walkthrough, push, PR,
remote CI와 `main` 병합은 **PENDING**이다. `main`은
`201acf9aec2f8183acb7dd843579938db14236cd` 그대로다.

## 2. 입력과 전달 범위

R2는 R1의 actual R3 publication을 재발행하지 않고 읽었다.

| 항목 | 값 |
| --- | --- |
| runtime root | `data/processed/screening_runs/20261009_usability` |
| dataset path | `screening_dataset_r3` |
| dataset publication ID | `screening-dataset-370c328056802a7fb42d02a6` |
| dataset manifest SHA-256 | `e735a64e931a1253414612a5eed2eb85666859fa8e48126741a647d884f377bb` |
| metric publication ID | `screening-metrics-2a512baef9131d3dcef0e1da` |
| metric manifest SHA-256 | `b77d9b586acd7a7847256e074f7275189995af4eafb2ce1a20559d7fee5dc188` |
| 범위 | financial as-of 2026-10-08, 21사, 31개 지표, support 651건, observation 2,604건 |

첫 화면은 POST 없이 21개 회사와 공통 8개 지표를 보여준다. 지표 안내는 31개
정의를 검색·분류하고 **선택 FY** coverage를 표시한다. 회사 프로필은 31개 값과
회사의 실제 4개 published FY 흐름을, 비교 화면은 2–4개 회사와 기존 1–31개
지표를 보여준다. 필터된 안내 결과와 전체 지표 metadata를 분리해, 필터 뒤에도
표 단위·이름과 비교 31개 정의, 과거 v1 조건의 호환 판단이 유지된다.

21사 모두에 공통인 기본 연도는 FY2025다. 전체 union은 FY2022–2026이고 회사
coverage는 각각 16/21, 21/21, 21/21, 21/21, 5/21이다. 한 연도를 선택하면 없는
회사는 `선택 연도 자료 없음`으로 남으며 회사별 최신 연도를 섞지 않는다. 값과
누락 사유는 prepared observation 그대로이며, 화면은 새 재무 공식·순위·평균을
만들지 않는다.

## 3. 검증과 실패 이력

지속 보존한 독립 보고서는
`work/screening_explorer_20261009/verification/verification-report.json`이고
SHA-256은
`1ad06eafc996fd186dbddfb02afccc6da7106182dc4f5c6cb82cfeb119d5c4f5`다.
독립 oracle은 observation 2,604건, coverage 대조 155건, 정렬 80건과 전체 지표
비교 15건을 통과했다. 최종 관련 suite는 **82 passed**다. API blob이 같은 직전
후보의 전체 **1,369 passed / 31 skipped**는 변경 없는 범위에만 재사용했고, 최종
UI는 별도로 검증했다. Ruff, JS syntax와 diff도 PASS했다.

현재 8건과 과거 v1 2건의 full/selected/repeated CSV·XLSX가 canonical payload로
재조립됐다. native Windows 최종 보고서는
`work/screening_explorer_20261009/native_final/native-report.json`이고 SHA-256은
`e8b026089ae2857281a701d498cf57624791a3e517156ccb0139d8237bbd53b1`다.
추적 harness와 byte-identical한 native 실행 보고서 SHA-256은
`4f3dcf59099b9f382f7915fbb57cee595f04de4610f9cb7f7b8bba8fb7e5f604`, harness
SHA-256은
`2d51c22261bb81f604d8b6066973d977e17b34c4376815b85c876b27d26ede14`다.

최종 PASS는 앞선 후보를 소급해 통과시키지 않는다.

- `a501d100e50e1cd2fd472ca58b832f463c5f4604`: 안내에서 지표를 반복 추가할 때
  draft 유실, 반복 단위·사유, trend SVG 넘침과 1,440px 표 잘림으로 lead 감사
  **FAIL**
- `dd67e5e877c48e89db91a679a71ca842415cb7ea`: 위 화면 문제를 고쳤지만 필터된
  지표 안내를 전체 metadata처럼 재사용해 비교 정의·단위·v1 호환성이 깨지는
  독립 검증 **FAIL**
- `7e7ec154e15ed88a14c2a74d89042c39fa3fadbf`: 전체 최신-v2 catalog를 필터된
  안내와 분리하고 모든 수리를 묶은 최종 **PASS / LOCALLY_ACCEPTED** 제품

Linux compositor의 물리 click 정지와 native harness가 `FINANCIAL_STABILITY`
지표를 13개로 잘못 기대한 오류(불변 실제 정의는 11개)는 제품 결함과 구분해
보고서에 보존했다. 같은 제품 흐름은 native Windows와 독립 검증에서 통과했다.

## 4. 읽기 전용 재현과 현재 runtime

발행본을 다시 계산하지 않는 상태 확인은 다음과 같다.

```bash
cd /home/plusbdw/.codex/worktrees/screening-explorer/sec_xbrl
PYTHONPATH="$PWD/src" /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python \
  -m sec_xbrl.screening status \
  --dataset /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_usability/screening_dataset_r3
```

현재 주소는 `http://127.0.0.1:18765/`, backend는 `127.0.0.1:8884`다. 재시작은
현재 backend를 먼저 정상 종료한 뒤에만 한다.

전환 뒤 GET-only native 보고서는
`work/screening_explorer_20261009/native_live/native-report.json`이며 SHA-256은
`e8b026089ae2857281a701d498cf57624791a3e517156ccb0139d8237bbd53b1`다. filtered
header와 비율 단위, 비교 31개, old-v1 복사, FY2026 partial coverage, source SHA를
확인했고 POST·외부 요청·page error는 없었다.

```bash
cd /home/plusbdw/.codex/worktrees/screening-explorer/sec_xbrl
PYTHONPATH="$PWD/src" /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python \
  -m sec_xbrl.screening serve \
  --catalog /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_usability/catalog_r3.json \
  --store /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_initial/user_journal.sqlite \
  --exports /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_initial/user_exports \
  --host 127.0.0.1 --port 8884
```

실제 journal은 3 screens, 4 revisions, 4 runs, 2 universe snapshots, 0 decisions,
0 exports였고 전환 전 SHA-256
`fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c`와 table
hash를 보존했다. 근거 `work/screening_explorer_20261009/pre_switch_journal.json`의
SHA-256은
`537fdb8c6ca5638fddd9b4d4159056b1b0b7e892acec7ed7e9fc67db2457e637`다. 검증
write는 격리 store만 사용했다.

## 5. 남은 경계

R2는 새 SEC·시장 자료, 가격·가치평가, 웹사이트·주소·회사 설명, 새 cohort,
새 재무 공식, peer 평균·점수·순위 또는 live refresh를 추가하지 않았다. 사용자
직접 walkthrough가 끝나기 전에는 human acceptance로 표시하지 않는다. 원격
상태도 별도 승인과 push·PR·remote CI·`main` 병합이 실제로 끝날 때만 바꾼다.
