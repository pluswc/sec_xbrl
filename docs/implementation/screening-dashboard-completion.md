# 스크리닝 대시보드 v1 완료·로컬 인수 기록

## 1. 최종 상태

기준일은 **2026-10-09 KST**다. 사용자 승인 범위 P0–P6의 최종 로컬 제품은
`acce036d1f8feef2f268b1df740009a11ce537e5`이며, 별도 읽기 전용 검증이
**PASS**했다. lead는 같은 날 이 범위를 **LOCALLY_ACCEPTED**로 판정했다.

이 상태는 다음을 포함한다.

- 실제 21사 annual prepared publication과 지표 가용성 발행
- 저장 조건·불변 실행·근거 추적·SIC 비교·판단 이력·실행 비교
- full/selected CSV·XLSX export, SQLite backup/restore
- loopback 전용 HTTP UI와 선택형 Windows/WSL loopback bridge
- 실제 21사와 분리된 cache/synthetic control에 대한 S01–S08 독립 검증

사용자의 직접 UX walkthrough, push, PR, remote CI와 `main` 병합은 별도 상태이며
완료되지 않았다. P7 live refresh·새 cohort, 가격·가치평가·FCF·TTM, 21사 공통
Q4와 원격 게시도 이 인수 범위에 없다. 현재 `main`은
`201acf9aec2f8183acb7dd843579938db14236cd` 그대로다.

## 2. 최종 데이터 publication

실제 publication은 프로젝트의 ignored runtime 아래에 있으며 Git에 복사하지
않았다.

| 항목 | 값 |
| --- | --- |
| runtime 위치 | `data/processed/screening_runs/20261009_initial/screening_dataset_v1` |
| publication ID | `screening-dataset-75f9df4f5b05c3ff298f8808` |
| manifest SHA-256 | `c7358afa7f93b1da1c162dd04ee8eeeea97e685f164c17a28d9eb007620dae8a` |
| 재무 기준일·보기 | 2026-10-08, `LATEST_REPORTED` annual |
| 준비 범위 | 21사 × 4 FY, observation 336건, support 126건, U5 snapshot 21개 |
| metadata 범위 | 후보 8,016개, 재무 준비·SIC 분류 21개, 미분류·미준비 7,995개 |

지원되는 조건 지표는 기존 annual core profile의 직접 보고 USD `revenue`, `cfo`,
`operating_income`, `net_income` 네 가지다. FY `revenue_growth`와
`operating_margin`은 `ACTUAL_PERIOD_REQUIRED`로 비활성이다. 새 공식이나 회사별
예외 mapping은 추가하지 않았다.

독립 검토한 FY2025 84개 회사·지표 cell 중 77개 reported cell은 raw source와
일치했고 7개는 upstream 불가 상태를 보존했다. 선택적 quality overlay가 없는
84개 cell은 `null`을 `NOT_DECLARED`로 표시하며 `CLEAR`를 만들지 않는다.
WMT·COST·TSLA의 FY2025 revenue는 `MULTIPLE_CANDIDATES`로 남아 값 0이나 임의의
후보로 바뀌지 않는다.

검증용 조건 `revenue >= USD 50,000,000,000 AND cfo > USD 0`의 실제 결과는
21 = PASS 11 + FAIL 7 + UNDETERMINED 3이다. `revenue >= USD 0` control은
PASS 18 + UNDETERMINED 3이다. 이 임계값은 테스트 예시이며 투자 추천이나 매수
정책이 아니다.

## 3. cache와 synthetic control의 분리

cache 재발행 control은
`data/processed/screening_runs/20261009_initial/cached_republication_control_v1`에
있다. publication ID는 `screening-dataset-38ecc3603e255df0d7bba747`, manifest
SHA-256은
`26ea0b6cbe70124679ca7c97a406ec140dcc27cf9cb959838027ea3f63a48ac4`다.
실제 값과 membership은 같고 publication identity만 다르다. 이는
`CACHE_FUTURE_UPDATE_FIXTURE`이며 새 filing 또는 live refresh 증거가 아니다.

변경값·mapping version·quality block·잘못된 metric·저장 실패를 시험한
self-contained synthetic control은 실제 publication과 별도 임시 journal 및
경로에서 실행했다. synthetic 결과를 실제 21사 성과나 실제 사용자 journal에
합치지 않았다.

## 4. S01–S08 인수 결과

| 시나리오 | 결과 | 확인한 동작 |
| --- | --- | --- |
| S01 | PASS | 전체 21사와 별도 SIC 5사 조건 저장, revision 재열기, 서버 재시작, 빈 목적지 restore, legacy column 표시 호환 |
| S02 | PASS | 전 21사 1회씩, predicate reason과 11/7/3 집계, missing·block을 0으로 만들지 않음 |
| S03 | PASS | AMD 값에서 Fact/QName/accession/unit/dimension/end-exclusive 기간·mapping·4 FY series까지 추적 |
| S04 | PASS | SIC 3674의 AMD/INTC/MU/NVDA/AVGO, 서로 다른 실제 context end, 8,016 metadata 검색과 7,995 unknown 유지 |
| S05 | PASS | 격리 journal의 INTEREST→HOLD append-only before/after chain, 재무·run 불변, 실제 사용자 결정 0건 |
| S06 | PASS | 같은 revision의 실제 frozen run과 cache 재발행 run 비교, 별도 synthetic 변경은 `MIXED`로 보수 표시 |
| S07 | PASS | 실제 UI에서 반복 full/selected CSV·XLSX 10건, 고유 URL·manifest, canonical row 동등성과 이전 파일 보존 |
| S08 | PASS | 0건·missing·invalid metric·synthetic 저장 실패 복구, 1,440/1,024px, keyboard focus/Escape |

독립 expected result는 screening executor를 oracle로 재사용하지 않고 frozen
governed input에서 만들었다. oracle SHA-256은
`beabaa83e96f0fc8bff4660f2c6aab06ca054ae67b69d2893d510cfb3b6d6929`다.

## 5. journal·export·운영 경계

실제 사용자 journal은 검증 전후 같은 SHA-256
`fcd0d7d13b4a965da3c69b324acdbc4296b49bfd94bddf7407a61bfe83e3ee32`를
유지했다. record는 screen 1, revision 1, run 1, decision 0이며 저장 이름은
`예시 · FY2025 연간 매출 확인`이다. 오류·관계 변조·판단 event 검증은 모두
`/tmp`의 격리 journal에서 수행했다. 제품은 자동 투자 판단을 쓰지 않는다.

화면의 HTTP export는 요청마다 새 안전한 파일명을 발급한다. 같은 full export의
반복 요청과 서로 다른 selected subset이 이전 파일이나 `ExportManifest`를
덮어쓰지 않았다. 최종 검증은 full CSV/XLSX 각 2회, AMD selected CSV/XLSX,
NVDA selected CSV/XLSX 각 2회의 10개 파일을 canonical payload와 대조했다.

현재 lead 운영 주소는 `http://127.0.0.1:18765/`다. WSL backend는
`127.0.0.1:8884`이며 Windows browser용 adapter도 Windows `127.0.0.1`에만
bind한다. adapter는 Host/Origin을 검사하고 backend local origin으로 전달했으며
전역 네트워크 설정을 바꾸지 않았다. 현재 runtime의 정확한 재시작 명령은 ignored
`data/processed/screening_runs/20261009_initial/RUNNING.md`에 있다. fresh checkout의
규범적 절차는 [이용 가이드](../usage/screening-dashboard.md)다.

Windows native 화면에서는 설치된 Malgun 글꼴로 한글을 확인했다. Linux 검증
screenshot의 한글 glyph 부족은 제품에 글꼴을 복사해 해결한 것으로 주장하지
않는다. 10개 Windows download는 backend bytes와 hash/size가 같았다.

## 6. 동결 소스와 실패 이력

최종 source `acce036d1f8feef2f268b1df740009a11ce537e5`가 유일한 이번 로컬
인수 대상이다. 다음 이력은 삭제하거나 최종 PASS로 소급하지 않는다.

- `8b3e8e18d7548af6e5cf48b8bf433770150d3efc`: revision/decision 관계 무결성
  결함을 발견한 역사적 후보
- `64ce126c40c0e7eabda8f9c13ff071f4edaacc59`: store 수리 뒤 legacy column UI
  결함을 발견한 역사적 후보
- `63646885496fe79b77e84ed3f6ef121a32bcfef8`: legacy 표시를 수리했지만 반복
  HTTP export 목적지 충돌을 발견해 초기 PASS를 철회한 후보
- `acce036d1f8feef2f268b1df740009a11ce537e5`: 고유 export 목적지 수리와 영향을
  받는 HTTP/UI 검증까지 포함한 최종 독립 PASS·로컬 인수 제품

최종 제품은 기존 보호 대상 4,142개 파일과 원천/config/completion/metadata
manifest 24개를 바꾸지 않았다. bulk data, SQLite, export, screenshot과 cache는
Git에 넣지 않았다.

## 7. 독립 검증 증거

최종 통합 독립 보고서는
`work/screening_dashboard_20261009/verification/verification-report.json`이며
SHA-256은
`b20803c241ec9d0f2b230ccf9c3a4073f7717e48fac76e437102b35900fc3d61`다.
같은 디렉터리의 human-readable Markdown과 `evidence_locations.json`이 27개 보존
증거의 위치와 hash를 연결한다.

최종 독립 결과는 다음과 같다.

- 전체 test **1,322 passed / 35 skipped**, focused **38 passed**
- Ruff, UI JavaScript와 bridge CJS syntax, diff·relative-link 검사 PASS
- source/dataset 위조 공격 거부, store 관계 손상 11종 거부
- 실제 S01–S08, Linux product-button browser, restart·restore, 1,440/1,024px PASS
- native Windows 화면·transport 증거를 독립 검증자가 pixel/report와 download
  bytes로 재검토

전체 test의 3건 차이는 main 프로젝트 cwd에서만 활성화되는 기존 cached test를
포함한 결과로 보고서에 기록했다. skipped 35건을 실행했다고 주장하지 않는다.

native Windows 보고서는
`work/screening_dashboard_20261009/native_windows/final-native-report.json`,
SHA-256
`75c4d01aabe97e0f33ecbfb8c5cbbeab557c4c9e3f38b2b859157f8e6b1f1841`이다.
download 보고서는 같은 디렉터리의 `native-download-report.json`, SHA-256
`964ad0d12d7ed03a9c8140cb5e9b2bb4ad39fe657d61bfc071e091f3c2a881fb`다.

자동화된 S01–S08 PASS, 독립 PASS, lead의 로컬 인수는 각각 기록됐다. 이것이
사용자가 직접 화면 경험을 walkthrough하고 수락했다는 뜻은 아니다. 다음 전달은
현재 managed worktree와 이 기록을 보존한 채 별도 승인 아래 push·PR·remote CI와
`main` 병합 상태를 갱신하는 것이다.
