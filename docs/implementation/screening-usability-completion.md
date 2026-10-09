# 일반 투자자 스크리닝 R1 완료·로컬 인수 기록

## 1. 최종 상태

기준일은 **2026-10-09 KST**다. 최종 제품 source는
`271fb1c968ebc03d98aea1561cd096187302a7fe`이며 별도 읽기 전용 검증이
**PASS**했다. lead는 같은 날 R1을 **LOCALLY_ACCEPTED**로 판정했고, 실제
loopback runtime도 R3 publication으로 전환해 GET-only native Windows 확인을
마쳤다.

이 상태는 로컬 제품 인수다. 사용자의 직접 한국어 walkthrough, push, PR,
remote CI와 `main` 병합은 **PENDING**이다. `main`은
`201acf9aec2f8183acb7dd843579938db14236cd` 그대로다. 가격·가치평가·TTM,
새 cohort, live 수집과 P7 운영 확장은 이번 결과에 포함되지 않는다.

## 2. 실제 R3 publication

대용량 산출물은 Git에 넣지 않고 다음 ignored runtime에 보존했다.

| 항목 | 값 |
| --- | --- |
| runtime root | `data/processed/screening_runs/20261009_usability` |
| expanded analysis | `expanded_analysis_r3`, 21사 × FY 4개와 정확한 연도말 INSTANT |
| metric config / publication | `metric_config_r3.json`, `screening_metrics_r3` |
| metric publication ID | `screening-metrics-2a512baef9131d3dcef0e1da` |
| metric manifest SHA-256 | `b77d9b586acd7a7847256e074f7275189995af4eafb2ce1a20559d7fee5dc188` |
| dataset config / publication | `prepare_config_r3.json`, `screening_dataset_r3` |
| dataset publication ID | `screening-dataset-370c328056802a7fb42d02a6` |
| dataset manifest SHA-256 | `e735a64e931a1253414612a5eed2eb85666859fa8e48126741a647d884f377bb` |
| scope | financial as-of 2026-10-08, 21사, 31개 정의, support 651건, 4 FY observation 2,604건 |

31개 정의는 reported monetary 21개와 governed derived 10개다. 모든 회사·연도에
모든 값이 있다는 뜻은 아니다. FY2025 독립 control 651건(보고 항목 441,
파생 항목 210)은 모두 일치했지만, 예를 들어 revenue는 18/21, gross margin은
8/21, net debt는 3/21만 사용 가능하다. 불가·복수 후보·quality/review 상태는
0으로 바꾸지 않는다. 표준화 FCF는 계약의 `CFO − PP&E purchases`이고 issuer가
정의한 비GAAP FCF와 같다고 주장하지 않는다.

기존 `revenue`, `cfo`, `operating_income`, `net_income`의
`annual-core-reported-v1` 의미와 과거 v1 run은 유지했다. 기본 ANNUAL과
QUARTERLY 산출물은 각각 49개 파일이 이전 결과와 byte-identical했다. 보호 대상
4,142개 파일과 source/config manifest 24개도 바뀌지 않았다.

## 3. 검증과 실제 화면

지속 보존한 독립 보고서는
`work/screening_usability_20261009/verification/verification-report.json`이며
SHA-256은
`bc5ed1c7ec51a08a85b9dc27c6183e05bc3bbacb4f3abe4e5b52166c06240a9c`다.
결과는 **1,351 passed / 35 skipped**, Ruff와 UI JS·bridge CJS syntax PASS다.
writer 실행과 3건 차이는 main cwd에서만 활성화되는 기존 cached test로 보고서에
명시했다. 별도 oracle, source/manifest 공격, default byte compatibility,
S01–S08와 31개 지표 export를 같은 보고서와 27개 hash-indexed evidence가 묶는다.

실제 Windows physical 흐름은 31개 조건 저장·실행과 full XLSX 2회 다운로드를
확인했다. 두 XLSX는 각각 21행·31 predicate이고 LongText를 독립 재조립한
canonical payload hash가 모두
`4b01a353f120dcce8075e252db91d4b3951f1d91c744b7c2d2128d519e7de10d`였다.
관련 보고서는 `work/screening_usability_20261009/native_windows_r3/`에 보존했다.
최초 harness timing 실패도 삭제하지 않았으며 제품 결함으로 오인하지 않도록
후속 PASS와 함께 남겼다.

현재 로컬 주소는 `http://127.0.0.1:18765/`, WSL backend는
`127.0.0.1:8884`다. R3 전환 뒤 GET-only native 보고서는
`work/screening_usability_20261009/native_windows_live/native-report.json`,
SHA-256
`c0e38ed74f563710b34b80c751e727b10ae4fa1c087b42712edf23f00da59cc0`다.
한글 글꼴, 1,024/768px layout, 기본 v2와 historical v1 열기, 새 조건 reset,
ordinary/admin 경계를 확인했고 외부 요청과 page error는 없었다.

실제 journal은 전환 전후 SHA-256
`e7dc76529778304072ff2c64f3410fb1f455fb8ba0173a065de7d6ced4dc0bb0`로 같았다.
screen 2, revision 3, run 3, decision 0, export 0이며 7개 table의 row hash도 모두
같다. 검증은 격리 journal을 사용했고 실제 사용자의 기존 기록을 재작성하지
않았다.

## 4. 읽기 전용 재현과 재시작

실제 발행본을 다시 계산하지 않고 확인하는 명령은 다음과 같다.

```bash
cd /home/plusbdw/.codex/worktrees/screening-usability/sec_xbrl
PYTHONPATH="$PWD/src" /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python \
  -m sec_xbrl.screening status \
  --dataset /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_usability/screening_dataset_r3
```

현재 backend를 먼저 정상 종료한 뒤 같은 journal로 재시작할 때만 다음 형태를
사용한다. 동시에 두 writer를 열거나 journal을 초기화하지 않는다.

```bash
cd /home/plusbdw/.codex/worktrees/screening-usability/sec_xbrl
PYTHONPATH="$PWD/src" /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/python \
  -m sec_xbrl.screening serve \
  --catalog /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_usability/catalog_r3.json \
  --store /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_initial/user_journal.sqlite \
  --exports /home/plusbdw/user_work/projects/sec_xbrl/data/processed/screening_runs/20261009_initial/user_exports \
  --host 127.0.0.1 --port 8884
```

fresh checkout와 다른 설치 경로에서는 [이용 가이드](../usage/screening-dashboard.md)의
일반 명령을 사용한다. 위 절대 경로는 이번 로컬 인수 runtime을 식별하기 위한
것이며 제품 계약의 필수 경로가 아니다.

## 5. 실패 이력과 남은 상태

최종 PASS는 이전 후보를 소급해 통과시키지 않는다.

- `edf555d039cc89112c895bfa7bbe13a43166925b`: YoY current observation bounds,
  dataset v2 외부 config/publication identity binding과 `.5` 같은 leading-zero
  decimal threshold scaling 결함으로 **FAIL**
- `1d9c7c4526594181132d0f1d0c8257def6b43d78`: 위 문제를 고쳤지만 STANDARD/
  CUSTOM origin 보존, 장문 XLSX canonical row 손실과 old-v1→new-v2 화면 전환
  문제로 **FAIL**
- `271fb1c968ebc03d98aea1561cd096187302a7fe`: current FY/input-period lineage,
  외부 config identity, 정확한 decimal string scaling, origin 보존, 무손실 XLSX와
  latest-v2 reset 수리 및 31개 실제 R3를 묶은 최종 **PASS / LOCALLY_ACCEPTED** 제품

자동 browser와 독립 PASS, lead의 로컬 인수는 사용자가 직접 UX walkthrough를
완료했다는 뜻이 아니다. 다음 상태 변경은 human walkthrough와 별도 승인된
push·PR·remote CI·`main` 병합을 각각 기록해야 한다.

lead 판정 원본은
`work/screening_usability_20261009/lead_acceptance.json`(SHA-256
`e3274e5d75b5f204111a9c5b9057828e2050891d343fcbfebb28ec384d1a059a`), live 전환
결합 기록은 같은 root의 `live_acceptance.json`(SHA-256
`b9057f8913aa0ce0fad2820075f2a831a7ddd4ed8573e83db0f49d6af459c2d6`)이다. 이
후속 closeout은 문서만 바꾸며 독립 검증 대상 제품 SHA를 바꾸지 않는다.
