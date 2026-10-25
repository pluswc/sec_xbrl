# 계획 등록부 — 단일 진입점

기준일: **2026-10-17**. 이 등록부는 목적·계약·현 상태·증거의 위치를 연결한다.
규범적 계획은 Git 추적 문서이며, 임시 계획 파일이나 특정 도구를 읽거나 설치할
필요가 없다. 이 등록부를 만든 과거 변경은 문서 설계만 승인했다. 2026-09-09
후속 승인은 [U4 전달 계약](../implementation/u4-continuous-refresh-delivery.md)의
제한된 로컬 구현으로 확대됐고, 2026-09-10 결과는
[U4 완료·인수](../implementation/u4-completion-and-acceptance.md)에 기록한다.

## 읽기 순서와 문서 소유권

| 문서 | 역할 |
| --- | --- |
| [M 구현 로드맵](../roadmap.md) | Raw/Analytical/Derived/Display 및 Layer 1–3 기반 구축 순서. 현재 완료 목록과 구분 |
| [투자자 U1–U5 로드맵](investor-analysis-roadmap.md) | 사용자 목표, 인수 기준, 현 상태, 남은 작업의 정식 계획 |
| [공통 전달·계획 관리](../implementation/delivery-workflow.md) | 권한·단일 작성자·독립 검증·동결·상태 기록 규칙 |
| [분석 데이터 모델](../architecture/analytical-data-model.md) | 데이터 평면과 소비자 경계 |
| [투자자 API 계약](../implementation/investor-analysis-interface.md) | 이미 존재하는 조회·준비·등록·갱신 계약 |
| [투자자 이용 가이드](../usage/investor-analysis.md) | 준비 bundle 조회·Axis·trace·export와 관리자 준비의 실행 예시 |
| [U3–U5 main 전달](../implementation/u3-u5-main-delivery.md) | 사용자 승인된 누적 통합의 범위, fresh checkout 조건과 PR/CI/merge 상태 경계 |
| [회사 관리](../implementation/company-report-administration.md), [공시 검토](../implementation/disclosure-review.md) | 회사별 설정과 정확한 출처의 검토 결정·재발행 |
| [U3 v1](../implementation/u3-important-items-plan.md), [후속 v2 전달](../implementation/u3-followup-delivery.md), [Axis 전달](../implementation/u3-axis-timeseries-delivery.md) | 승인 정책, 구현·검증 계약과 한계. 로드맵이 수치를 재승인하지 않음 |
| [U3 완료·우선순위](../implementation/u3-closeout-and-followup-priority.md) | 완료 결정과 날짜가 있는 정정 기록 |
| [U4 계속 갱신 제안](../implementation/u4-continuous-refresh-plan.md) | 기존 기능/격차 대조와 후속 실행 수락안. 구현 승인 아님 |
| [U4 완료·인수](../implementation/u4-completion-and-acceptance.md) | 후속 사용자 승인, 동결 소스, live/cache 구분, 독립 검증과 잔여 한계 |
| [회사 universe 데이터 전달](../implementation/universe-data-delivery.md) | 21사 A/B/C 전달의 승인 범위, 입력·runtime 경계, 산출물과 인수 gate |
| [회사 universe 완료 기록](../implementation/universe-data-delivery-completion.md) | A/B/C 후보 이력, 최종 동결 소스, 실제 runtime·browser 독립 검증, 로컬 인수와 잔여 원격 상태 |
| [기업 universe 종목 확보 계획](company-universe-acquisition-plan.md) | 현재 21사 품질 진단을 먼저 수행하고 issuer/security master를 거쳐 50→150→500으로 확장하는 **2026-10-10 PROPOSED** 계획. 구현·수집·자동화 승인 아님 |
| [50 issuer 연차·분기 생산자 전달](../implementation/universe-50-quarterly-delivery.md) | 사용자의 “둘 다 진행” 결정에 따라 기존 21사 안정화, 50 unique issuer의 5 FY 입력·4 FY 표시, 최근 완료 calendar-quarter bucket 8개의 reported/YTD/derived 분리를 승인. **2026-10-14 사용자는 PEP 보류·KDP 교체를 결정했다. KDP Raw 22개와 원래 49사+KDP exact-50 input selection 1,097개는 독립 PASS·Raw 범위 local acceptance를 받았다. history source `5cd2438…`도 source-only PASS 뒤 JNJ complete-stage recovery 한 건이 승인·시작됐지만 종료·artifact 독립 검증·local acceptance는 아직 없다. financial/history/publication·native·전체 rollout은 계속 NOT_READY다.** |
| [50 issuer 2026-10-13 로컬 상태](../implementation/universe50-local-status-20261013.md) | Raw 49사·1,075 complete input과 PEP 정책 hold, producer/consumer source-only gate, CAT·JNJ component 증거의 정확한 한계 및 JNJ→CVX→first-five→49/50→native U1–U8 순서를 기록한 날짜별 handoff. 전체 financial/history/rollout 완료 기록 아님 |
| [50 issuer 2026-10-14 KDP 상태](../implementation/universe50-local-status-20261014.md) | PEP 원본·오류 보존, KDP 교체 결정, KDP Raw와 exact-50 input selection의 좁은 local acceptance, `5cd2438…` source PASS와 실행 중인 JNJ recovery의 미완료 경계를 기록. financial/native/main/remote/scheduler 완료 기록 아님 |
| [50 issuer 2026-10-17 T3 참조 HOLD](../implementation/universe50-t3-reference-hold-20261017.md) | JNJ recovered History component만 좁게 수락한 뒤, 기존 T3 concept edge endpoint와 발행 node의 ID 공식 불일치가 독립 tiny fixture에서 확인됐다. actual CVX payload audit는 NOT_EVALUATED이며 first-five·50사 financial/native 확대는 HOLD. T3 수리·재생성·실제 audit는 PROPOSED / 미승인 |
| [50 issuer T3 참조 무결성 수리 전달](../implementation/universe50-t3-reference-repair-delivery.md) | **2026-10-17 사용자가 “연결 결함 수정 후 데이터 확장 재개”를 승인했다.** concept endpoint ID 일치, 같은 publication의 node/edge 교차검증, publisher/reader fail-closed와 v2 새 output/run version 재생성 경계를 구현한다. 과거 HOLD·원본·기존 publication은 보존하며 구현 후보의 독립 검증, tiny PASS, actual CVX/first-five/exact-50 실행·인수는 별도 후속 단계다. |
| [History panel 메모리 전달](../implementation/history-panel-memory-delivery.md) | JNJ 22-filing fresh History가 T1–T4와 AS_FILED FY/INSTANT/OTHER_DURATION 뒤 16 GiB cap에서 정상 중단된 증거, eager T5/Fiscal 중첩 소유권 진단, 기존 public 의미를 유지하는 panel-at-a-time typed disk spill과 실패 보존 수락 기준을 기록한다. 첫 동결 `6851853…`은 journal/SQLite integrity와 `time.fold` 독립 검증 **FAIL**이며 수락되지 않았다. 두 번째 `5a48407…`도 NULL 정리(F3)/forged frame RAM(F4) 독립 FAIL이다. 별도 Astra 단일 구현자의 F3/F4 보완은 64 KiB streaming 검증·모든 handle cleanup/재시도와 5 cached test 제외 경계를 추가하며 새 독립 검증 대기다. actual JNJ retry·OPS source-pin·cap 변경은 미승인이다. |
| [private quarter spill 성능 전달](../implementation/universe50-quarter-spill-performance-delivery.md) | JNJ recovery의 reported panel 12개 완료 뒤 마지막 table processing timeout을 source/synthetic-only로 진단한다. 최초 `ce45d956…` 후보는 SQL/journal/yield ownership 경계 회귀로 independent FAIL했다. 보정 후보는 각 SQL·journal write와 `items()` record yield 전에 full ancestry 검증을 복구했으며 별도 Astra 재검증·actual retry·로컬 인수·main 반영은 대기다. |
| [회사 설명·외부 프로필 전달 계약](../implementation/company-description-delivery.md) · [완료·로컬 인수](../implementation/company-description-completion.md) · [사용 안내](../usage/company-descriptions.md) | 한국어 plain-text collector/importer·불변 publication·선택적 profile 최소 수직 기능은 최종 `51aeff7…` 독립 PASS·**LOCALLY_ACCEPTED_INFRA_ONLY**. 보호된 Investing.com 본문 취득과 actual 21사 enablement는 **RIGHTS_DECISION_PENDING / BLOCKED** |
| [스크리닝 대시보드 로드맵](screening-dashboard-roadmap.md), [v1 구현 전달 계약](../implementation/screening-dashboard-delivery.md), [사용자 시나리오 인수 계약](../implementation/screening-dashboard-user-acceptance.md), [완료·로컬 인수](../implementation/screening-dashboard-completion.md), [이용 가이드](../usage/screening-dashboard.md) | annual-first 지표 가용성, 영속 screen/run/decision, S01–S08와 화면·운영 경계. **2026-10-09 최종 `acce036…` 독립 PASS·P0–P6 `LOCALLY_ACCEPTED`; 직접 UX walkthrough·P7·원격은 미완료** |
| [일반 투자자 스크리닝 R1 전달](../implementation/screening-usability-delivery.md), [31개 지표 정의](../implementation/screening-metric-definitions.md), [R1 완료·로컬 인수](../implementation/screening-usability-completion.md) | FY+연도말 INSTANT opt-in 준비, 21 reported+10 governed derived publication, dataset v2/catalog와 v1 호환. **최종 `271fb1c…`·실제 R3 독립 PASS·`LOCALLY_ACCEPTED`; 직접 UX walkthrough·원격 미완료** |
| [스크리닝 기업 탐색 R2 전달](../implementation/screening-explorer-delivery.md) · [완료·로컬 인수](../implementation/screening-explorer-completion.md) · [사용법](../usage/screening-explorer.md) | 21개 회사 cold-start 탐색, 선택 FY 기준 31개 지표 안내, 독립 회사 프로필·4 FY 흐름·2–4개 비교. **최종 `7e7ec15…` 독립 PASS·`LOCALLY_ACCEPTED`; 직접 walkthrough·원격 미완료** |
| [기간 규칙](../implementation/period-rules.md), [Layer 2 연결](../implementation/layer2-longitudinal.md), [공시 발견 계약](../implementation/accession-contract.md) | 표시 계획으로 바꿀 수 없는 의미·입력 경계 |

충돌 시 적용되는 사용자 결정과 승인 범위를 먼저 확인하고, 해당 평면의 계약을
따른다. 제안 로드맵은 승인된 회계·검토 정책을 덮어쓰지 않는다. 현재 상태는
아래처럼 별도로 기록하며, 오래된 문서의 “미구현/검증 대기” 문구는 해당 시점의
기록이다. 그 문구를 지우는 대신 후속 결정과 연결한다.

## 상태 등록 — 상태를 서로 대신 쓰지 않는다

| 단계 | 제안 | 승인 | 구현 | 독립 검증 | 로컬 인수 | main 병합 |
| --- | --- | --- | --- | --- | --- | --- |
| U1 핵심 요약 | 기존 제안에서 납품 | 기존 제한 범위 | `9eb37d4`에 존재 | 해당 후보 PASS | 완료 | PR #62, `7f8cc523` |
| U2 단계별 탐색 | 기존 제안에서 납품 | 기존 제한 범위 | `9eb37d4`에 존재 | 해당 후보 PASS | 완료 | PR #62, `7f8cc523` |
| U3 중요도·구조·Axis 시계열 | 승인 범위까지 확장·납품 | 명시적 U3 범위 | `3098be6` | 664 passed / 16 skipped, Ruff, 실제 6사 PASS | 2026-09-09 COMPLETE | PR #63, `9708508` |
| U4 계속 갱신 | 복구된 제안과 후속 전달 계약 | bounded orchestration·복구·재개·live 입력·quality materialization; 원격 제외 | `3236778` | 675 passed / 37 skipped, Ruff, 6사 21, 실제 NFLX 14공시·동일 API/화면 PASS | **2026-09-10 LOCAL_ACCEPTED** | PR #63, `9708508` |
| U5 보관·공유 | 복구된 기존 제안 | `51c196f` 기준 로컬 구현 승인 | product `8867229`; canonical snapshot + CSV/HTML/JSON/XLSX + offline 저장 controls | 679 passed / 37 skipped, cached 21, Ruff, 80 snapshots·320 formats·4,844 cells·24 downloads PASS | **2026-09-10 LOCAL_ACCEPTED** | PR #63, `9708508` |
| 21사 universe A/B/C 전달 | [전달 계약](../implementation/universe-data-delivery.md) | **2026-10-08 APPROVED**; A/B/C, SEC duration 표준 교정, 4종 supported-lexical 보완, 381건 fresh v5 재생성 및 governed source-binding 보완 | final product `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`; source-binding producer `eff3bff3`; parser `c1fdc21`; A/B/C 검증 후보 이력은 [완료 기록](../implementation/universe-data-delivery-completion.md)에 보존 | final consumer 1,288 passed / 31 skipped, focused 41, Ruff PASS; 실제 21사·381공시·741 history Parquet 및 browser PASS | **2026-10-08 LOCALLY_ACCEPTED** | 미병합; push·PR·remote CI 미수행 |
| 종목 확보·universe 확장 | [확보 계획](company-universe-acquisition-plan.md) | 문서 작성만 승인; 미래 M0–M5는 **PROPOSED / 미승인** | 미구현 | 미수행 | 미수행 | 미병합 |
| 50 issuer 연차·분기 생산자 | [전달 계약](../implementation/universe-50-quarterly-delivery.md) | **2026-10-10 APPROVED**; 2026-10-13 bounded history·RAW_ONLY·v6 transform 승인; 2026-10-14 사용자 PEP hold·KDP replacement 결정과 JNJ complete-stage recovery 한 건 lead 실행 승인 | M0/quarter 기반과 v6 Raw 보정 존재; final membership은 original 49+KDP; recovery source `5cd2438…` 존재 | KDP 22 Raw와 exact-50 1,097 input selection 독립 PASS; `5cd2438…` source-only PASS와 bound proof PASS; 이전 `2027e218…` actual CLI NOT_READY와 과거 FAIL 보존; JNJ recovery 결과는 아직 미확인 | **Raw exact-50만 2026-10-14 LOCALLY_ACCEPTED**; history·financial·quarter·native·rollout 미수락 | 미병합; push·PR·remote CI·scheduler 미수행 |
| 50 issuer T3 참조 HOLD | [날짜별 상태](../implementation/universe50-t3-reference-hold-20261017.md) | 상태·후속 제안 문서화만 승인; T3 fix·actual CVX audit·재무 재생성 미승인 | source `998ceee…` frozen; 기존 T3 ID mismatch 확인, 소스 변경 없음 | tiny cached parent 9 files / 30,722 records에서 2,792 missing endpoints·788 distinct IDs **FAIL**; actual CVX payload NOT_ACCESSED / audit NOT_EVALUATED | JNJ recovered History component만 2026-10-17 좁게 LOCALLY_ACCEPTED; Raw50 수락 유지; first-five·50 financial/native 미수락·HOLD | 미병합; PR·CI·merge 없음 |
| 50 issuer T3 참조 수리 | [수리 전달](../implementation/universe50-t3-reference-repair-delivery.md) | **2026-10-17 APPROVED**; T3 reference fix, 새 output/run version, tiny 우선 검증. actual CVX/first-five/exact-50는 tiny PASS 뒤 lead 별도 실행 | 구현 후보 존재; 동결 SHA는 구현 인계에 기록 | 구현자 1,497 unit / 4 skipped, 관련 cached 14 / 0 skipped, Ruff PASS; 별도 Astra 독립 검증 대기 | 미수락; 기존 HOLD와 Raw/JNJ component 수락 경계 유지 | 미병합; push·PR·CI 없음 |
| 50 issuer History panel 메모리 | [메모리 전달](../implementation/history-panel-memory-delivery.md) | **2026-10-17 APPROVED SOURCE/SYNTHETIC CORRECTION ONLY**; 실행 소유권·typed spill·failure preservation 및 trusted checkpoint/typed temporal 보완. actual retry와 OPS 통합 제외 | 첫 `6851853…` 및 두 번째 `5a48407…` 독립 FAIL; F3/F4 범위 한정 Astra 구현 후보, 새 SHA는 인계 report에 기록 | 기존 unguarded unit 결과는 source-only 근거에서 제외. F3/F4 focused 77 passed, guarded 허용 unit+synthetic 1,561 passed/5 deselected, 기존 55 controls/93 Parquet 비교·Ruff·diff PASS. 5 cached node 제외·실제 경로 guard·16 GiB RSS/Polars 2/no AS 검사; 새 독립 검증 대기 | 미수락; JNJ 실패 partial·기존 Raw/History acceptance 불변 | 미병합; push·PR·CI 없음 |
| 50 issuer private quarter spill 성능 | [성능 전달](../implementation/universe50-quarter-spill-performance-delivery.md) | **2026-10-17 APPROVED SOURCE/SYNTHETIC ONLY + QP CORRECTION**; full SQL/journal/yield ownership 경계, safe 중복 stat 제거와 monotonic/elapsed metadata. actual read/retry, cap·timeout 변경 제외 | `ce45d956…` independent FAIL 봉인; 같은 sole-writer worktree에 보정 후보 존재, 새 동결 SHA는 correction 인계에 기록 | QP1 SQL 전 0 rows/no `APPLIED`, QP2 replacement·symlink·ancestor yield 전 거부, nested synthetic state/journal exact equivalence; 별도 Astra 재검증 대기 | 미수락; actual 3시간 원인·완료 여부 미측정 | 미병합; push·PR·CI 없음 |
| History publication 일상 검증 | [검증 정책](../implementation/history-validation-policy-20261024.md) | **2026-10-24 APPROVED**; routine initial/changed/unchanged와 명시적 detailed, recovery strict 보존. 생산자 row 증분·완료 회사 재감사 제외 | accepted base `e4a9f5426454fe9cb2014452529a6eb1930efc49`; final ID/FK 단일-pass `84d5248c937526e78c165facddbb6dc0040522d0` | `e4a9f5…` 독립 r2 PASS; `84d5248…` 독립 직접 영향 14 PASS. 동일 append fixture 시간 -46.08%·5 ms 관측 RSS -6.45% | **2026-10-24 LOCALLY_ACCEPTED SOURCE_AND_BOUNDED_FIXTURE_ONLY**; 실제 회사 runtime·전체 회사 생산자 증분 미포함 | 미병합; push·PR·remote CI 없음 |
| 회사 설명·외부 프로필 | [전달 계약](../implementation/company-description-delivery.md) · [완료 기록](../implementation/company-description-completion.md) · [사용 안내](../usage/company-descriptions.md) | generic collector·reader·선택적 profile과 합성 fixture 구현; 실제 Investing 본문은 **RIGHTS_DECISION_PENDING / BLOCKED** | final `51aeff7665a1f09e4bab2cce562b2250e0f316a0` | **PASS**; 109 relevant / 0 skipped, native 26 controls | **2026-10-10 LOCALLY_ACCEPTED_INFRA_ONLY** | 미병합; push·PR·remote CI 미수행 |
| 스크리닝 대시보드 | [로드맵](screening-dashboard-roadmap.md), [구현 전달 계약](../implementation/screening-dashboard-delivery.md), [S01–S08 인수 계약](../implementation/screening-dashboard-user-acceptance.md), [완료 기록](../implementation/screening-dashboard-completion.md) | **2026-10-09 APPROVED**; P0–P6 로컬 v1, 기존 annual reported metric만. P7·새 회계 정책·원격 제외 | final `acce036d1f8feef2f268b1df740009a11ce537e5`; actual 21사 publication | **PASS**; 1,322 passed / 35 skipped, focused 38, Ruff·JS/CJS, S01–S08·native evidence | **2026-10-09 LOCALLY_ACCEPTED** | 미병합 |
| 일반 투자자 스크리닝 R1 | [R1 전달 계약](../implementation/screening-usability-delivery.md), [지표 정의](../implementation/screening-metric-definitions.md), [완료 기록](../implementation/screening-usability-completion.md) | **2026-10-09 APPROVED**; 21 reported+10 derived, opt-in FY-end INSTANT, v1 호환 | final `271fb1c968ebc03d98aea1561cd096187302a7fe`; metrics `screening-metrics-2a512baef9131d3dcef0e1da`; dataset `screening-dataset-370c328056802a7fb42d02a6` | **PASS**; 1,351 passed / 35 skipped, 651 FY2025 control 일치, native 31조건·XLSX·live GET PASS | **2026-10-09 LOCALLY_ACCEPTED** | 미병합; push·PR·remote CI 미수행 |
| 스크리닝 기업 탐색 R2 | [R2 전달 계약](../implementation/screening-explorer-delivery.md), [완료 기록](../implementation/screening-explorer-completion.md) | **2026-10-09 APPROVED**; R3 prepared rows의 read-only 탐색·library·profile·compare, 새 재무정책 제외 | final `7e7ec154e15ed88a14c2a74d89042c39fa3fadbf`; unchanged actual R3 | **PASS**; final relevant 82, oracle·native·export·filtered/legacy flow PASS | **2026-10-09 LOCALLY_ACCEPTED** | 미병합; push·PR·remote CI 미수행 |

현재 전달 상태(2026-09-10): U3–U5 누적 이력은
[PR #63](https://github.com/pluswc/sec_xbrl/pull/63)으로 `main`에 병합됐다. merge
SHA는 `9708508ec953ee4323ae29318c639abc9e0650b6`이고, 병합 시각은
03:12:14 UTC(12:12:14 KST)다. PR CI와 병합 후 main CI는 모두 성공했으며 상세
링크와 fresh checkout 확인법은 [main 전달 기록](../implementation/u3-u5-main-delivery.md)에
있다. 위 로컬 인수 열은 각 단계의 당시 상태를 보존한다.

회사 universe 전달 상태(2026-10-08): 실제 completion publication
`universe-delivery-1c4337ffe69e81ae8b4ecc61`은 `READY`이며 manifest SHA-256은
`d20188610b699b960fcac4b34fc1c08d0073b6d346bc7d2026df3966fc6ccb29`다.
21/21 회사의 Raw와 governed history, 381/381 공시, duration 3,842건,
승인 transform 보완 104건, 21개 pilot SIC, NVDA Q4 경제값 16개/보기 record
32개를 함께 검증했다. 원격 작업은 승인 범위 밖이므로 `main`은 baseline
`201acf9aec2f8183acb7dd843579938db14236cd`에 남아 있다.

정확한 식별:

- U1/U2 검증 후보: `9eb37d4715640ef7b8255d806b5ffc1c030653dd`.
  PR #62 merge: `7f8cc5232d0df3d4c184de55827111e599b94dbd`.
- U3 인수: `3098be6db7622f2ec444a9979732b7dfaa685641`.
  문서 closeout: `32212caba5daf8273663d70ba3075db5d1d56fc7`.
  문서 커밋은 제품 테스트 결과의 대상 SHA를 바꾸지 않는다.
- U5 product: `8867229455f9441807117a4a4a3e1ebaa8ae7eee`.
  완료·인수 근거: [U5 완료·인수](../implementation/u5-completion-and-acceptance.md).
- 회사 universe final product:
  `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`; completion publication
  `universe-delivery-1c4337ffe69e81ae8b4ecc61`; manifest SHA-256
  `d20188610b699b960fcac4b34fc1c08d0073b6d346bc7d2026df3966fc6ccb29`.
  실제 runtime/browser 독립 검증과 제한은 [회사 universe 완료 기록](../implementation/universe-data-delivery-completion.md)에 있다.
- 스크리닝 대시보드 제안의 제품·문서 기준은 각각 `8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`과
  `473521560fa9e47aa00d6a273cbaa90c708ad366`이다. `main`은
  `201acf9aec2f8183acb7dd843579938db14236cd`이며 서로 다른 상태를 유지한다.
- 스크리닝 대시보드 v1의 최종 로컬 제품은
  `acce036d1f8feef2f268b1df740009a11ce537e5`다. 실제 publication은
  `screening-dataset-75f9df4f5b05c3ff298f8808`, manifest SHA-256
  `c7358afa7f93b1da1c162dd04ee8eeeea97e685f164c17a28d9eb007620dae8a`다.
  독립 검증과 lead 인수 범위·한계는 [완료 기록](../implementation/screening-dashboard-completion.md)에 있다.
- 역사적 `8b3e8e1`, `64ce126`, `6364688` 후보의 발견 결함과 철회된 초기 PASS는
  최종 `acce036…`의 PASS로 덮어쓰지 않는다. 완료 기록은 이 수리 이력을 보존한다.
- 일반 투자자 R1의 최종 로컬 제품은
  `271fb1c968ebc03d98aea1561cd096187302a7fe`다. metric/dataset publication과
  과거 `edf555d…`·`1d9c7c4…` FAIL의 수리 이력은
  [R1 완료 기록](../implementation/screening-usability-completion.md)에 있다.
- 스크리닝 기업 탐색 R2의 최종 로컬 제품은
  `7e7ec154e15ed88a14c2a74d89042c39fa3fadbf`다. unchanged R3 입력, 과거
  `a501d10…`·`dd67e5e…` FAIL과 독립·native 근거는
  [R2 완료 기록](../implementation/screening-explorer-completion.md)에 있다.
- 최초 계획 설계의 기준 부모는 위 `32212ca`였다. 당시 단일 작성자 문서와 별도
  읽기 전용 검증을 요구한 기록은 보존한다. 후속 제품의 독립 PASS·로컬 인수는
  완료 기록에만 반영하며, 아직 수행하지 않은 원격 병합을 완료로 표시하지 않는다.

미래 수락 조건의 작성은 사용자 승인이나 일정 약속이 아니다. 소스 함수나
작업 세션/브랜치의 존재도 전체 기능 승인·완료·배포를 증명하지 않는다.

2026-10-24 history publication의 일상 저장 검증을 routine/detailed로 구분하는 최종
`e4a9f5…`는 독립 r2 PASS 뒤 source 및 bounded fixture 범위에서 로컬 수락됐다. 상세
계약과 교정 측정의 최초/변경 회귀는
[history validation 정책](../implementation/history-validation-policy-20261024.md)에 있다.
이는 producer 계산의 증분화나 과거 50개 회사 의미 감사 반복을 뜻하지 않으며, 실제
회사 runtime 채택·`main` 병합·원격 전달은 아직 수행하지 않았다.

2026-10-24 AAPL cached 분기 한 건 추가 측정에서 가장 큰 단일 함수 경계였던 quarter
publisher의 같은 source-table row/column private spill 재저장을 제거한 `18f8872…`는
독립 3건 PASS 뒤 로컬 수락됐다. 단일 actual pair의 시간·RSS, 결과 동등성, 전체 이력
재생성 한계는 [AAPL 분기 추가 성능 인계](../implementation/aapl-quarter-append-performance-20261024.md)에
기록한다. `main` 병합과 운영 runtime 채택은 수행하지 않았다.

2026-10-24 후속 증분 append 후보는 strictly-later 단일 CIK 공시에서 이전 T1/T2/T4와
깨끗한 History 표를 증명 기반으로 재사용한다. T3는 typed T1 prefix와 ID lookup을
확인한 뒤 현재 T2 순서로 병합하며, 무결성을 증명할 수 없을 때만 전체 생성으로
전환한다. 계약, 검사 범위와 아직 남은 전체 계산은
[History 증분 append v1](../implementation/history-incremental-append-20261024.md)에 기록한다.
source `a83a3b2…`의 실제 AAPL 단일 후보와 full reference 동등성은 로컬에서 확인했고,
2026-10-25 독립 PASS와 ROOT 로컬 수락을 받았다. `main` 병합과 운영 채택은 별도
미완료 단계다.

2026-10-25 후속 [quarter cell delta v1](../implementation/history-quarter-cell-delta-20261025.md)은
dirty 표의 unchanged reported/derived cell payload를 증명 기반으로 재사용하고, 변경·신규
셀과 파생 영향만 기존 규칙으로 다시 계산하는 opt-in source 후보다. cached fixture의
full oracle 동등성은 확인했으나 실제 AAPL 시간·RSS, 독립 검증, 로컬 수락과 운영 반영은
아직 완료되지 않았다.

## 증거와 재현 — 임시 디렉터리에 의존하지 않는 인계

필수 계약과 검증 절차는 위 추적 문서 및 U4 계획의 입력/검증 절에 있다.
실행자는 승인된 범위에서 별도 입력·출력 위치를 제공한다. 대용량 공시 자료나
과거 실행 보고서가 없는 checkout에서도 계획을 이해할 수 있어야 한다.

선택적 보존 증거 locator(원래 프로젝트 루트 기준; 현재 계획의 실행 의존성 아님):

- `work/consumer_focused_analysis_20260908/verification.md`: U1/U2 후보 독립
  526 passed / 9 skipped, PR #62 병합 및 병합 후 관련 33건 기록.
- `work/consumer_focused_analysis_20260908/online_pipeline_verification.md`:
  AAPL 한 공시의 실제 SEC→새 Layer 1→분석→조회 증거. 제한은 U4 계획에 복사했다.
- `work/u3_axis_timeseries_complete/LEAD_ACCEPTANCE.md`,
  `independent/VERIFICATION.md`, `FREEZE.json`, `html/index.html`
  (뒤 세 경로도 같은 `work/u3_axis_timeseries_complete/` 아래): U3 최종 증거.
  독립 6사/84 Axis/10,824 화면 셀; 합성·캐시·live 구분과 유실 임시 목록의 한계 유지.

이 파일들을 과거 상태 그대로 보존한다. 검증 수치는 해당 SHA의 과거 결과이고,
이번 문서 변경에서 pytest/browser를 실행했다는 뜻이 아니다.

## 역사 자료의 출처 — 선택적 정보

복구에 참고한 원본은 `.omx/plans/investor-focused-progressive-analysis-20260907.md`
(2026-09-07 제안)이다. 일반 파일로 읽었으며 스킬·명령·워크플로로 실행하지 않았다.
원래 위치의 바이트를 이동·편집하지 않고 보존한다.
SHA-256: `7e88f7c50e7d9cbacb4994e58bd8542c837cb17d98fe1fa2da4d0e57d65a8911`.

이 provenance는 과거 기록의 식별 정보일 뿐 규범적 지시가 아니다. 원본을 다시
읽을 필요 없이 이 등록부, U 로드맵과 실행 계약만으로 업무를 인계한다.
`.omx/`, `.codex/`, `work/`에서 만든 후속 계획도 같은 원칙을 따른다.

2026-10-13 추가 상태: JNJ attempt 4는 reported 12 panel과 staged manifest가
존재하고 rename이 없는 상태에서 SIGKILL 137로 실패했다. 검증 단계의 메모리
실패라는 설명은 control-flow와 RSS에 근거한 강한 추론이며 traced stack이나
확인된 kernel OOM 원인은 아니다. 전체 완료 상태가 아니다. 제한된 bounded verification·객체 수명·독립
complete-stage recovery 수리와 모델 역할 상향은
[날짜별 상태의 후속 기술 수리](../implementation/universe50-local-status-20261013.md#2026-10-13-후속-기술-수리--bounded-verification--complete-stage-recovery)에 기록한다.
public 복구 계약은 [회사 history workflow](../implementation/company-history-workflow.md#complete-reported-stage-recovery-2026-10-13-technical-exception)에 있다.
독립 검증·actual recovery·local acceptance·main merge는 별도 미완료 단계다.

2026-10-13 recovery 추가 결정: source `65513173…`와 `b0aa40d…` 독립 검증은
FAIL로 보존한다. lead는 trusted exclusive parent·NOT_READY reader gate와 실패
artifact 보존을 승인했다. 재귀 rollback 삭제는 제거하며, 초기 빈 same-UID 교체를
portable mkdir/open으로 방어한다고 주장하지 않는다. 상세 계약은
[retention 결정](../implementation/company-history-workflow.md#2026-10-13-retention-and-not_ready-decision-after-source-b0aa-fail)에 있다.

source `7218940…`도 default COMPLETE gate의 독립 검증에서 FAIL했다.
보고서와 데이터는 보존하고, reported-only 위장 거부·dangling identifier 판별·
immutable receipt 전체 binding을 수리한다. 규범 계약은
[complete-reader gate 수리](../implementation/company-history-workflow.md#2026-10-13-complete-reader-gate-repair-after-source-721-fail)에 있으며 새 독립 PASS 전 actual recovery는 미승인이다.

source `2027e21…`의 실제 recovery는 reported copy 이후 CLI module/context
분리로 NOT_READY 오류가 발생했다. 실패 root·기존 증거를 보존하고
[CLI capability-owner 수리](../implementation/company-history-workflow.md#2026-10-13-cli-capability-owner-repair-after-actual-source-2027-failure)를 적용한다.
새 독립 검증 전 실제 재시도는 하지 않는다.


2026-10-14 후속: `5cd2438…` actual JNJ recovery는 16 GiB guard의
**RESOURCE_STOP / NOT_READY**로 봉인됐으며 blind retry는 중단됐다. lead 승인
bounded-quarter-production은 private disk spool로 전체 record/candidate/order를
보존하는 비회계 storage 수리다. 구현·writer 검사와 새 독립 source 검증·실제 OPS
실행 승인은 별도 상태다. [날짜별 후속 상태](../implementation/universe50-local-status-20261014.md#2026-10-14-후속--actual-5cd-resource-stop와-bounded-quarter-수리)와
[bounded quarter 계약](../implementation/company-history-workflow.md#2026-10-14-bounded-quarter-production-after-actual-source-5cd-resource-stop)을 따른다.


2026-10-15: source `9515322…` failed independent SQLite pathname ownership
verification. The approved repair uses anonymous disk-backed SQLite scratch and
retained held-FD typed journal evidence; previous failed-source evidence remains
unchanged. See the [dated ownership contract](../implementation/company-history-workflow.md#2026-10-15-sqlite-ownership-repair-after-source-951-fail).
New writer checks, independent source acceptance and actual execution remain
separate; actual recovery is pending and financial readiness is not declared.
