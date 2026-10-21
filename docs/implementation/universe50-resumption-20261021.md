# 50사 재무 스크리닝 재개 상태 — 2026-10-21

## 결정과 현재 상태

사용자는 2026-10-21 남은 exact-50 작업의 재개를 승인했다. 이미 완료되어 수락된
build와 audit는 반복하지 않고, 현재 운영 중인 21사 화면과 원래 저장 기록을
보존한다. 이 승인은 남은 단계의 순차 실행 범위이며, source 의미 변경, 기존 실패
증거 삭제, 자동 재시도, 원격 반영 또는 live 전환 승인이 아니다.

first-five `TXN, HD, JNJ, CVX, NEE`의 original financial 8 receipts, 17 publication
manifests와 H5 6 phases의 완료 증거는 별도 읽기 전용 검토에서 PASS했다. 리드는
exact source `4357c838722da281d2474bfc881b3a4a2ed4e988`와 exact-50 parent에
결속된 strict 10-field
`universe50-first5-financial-acceptance-v1` artifact를 작성해
`LOCALLY_ACCEPTED_FIRST5_FINANCIAL`로 수락했다.

로컬 acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_first5_financial_actual_acceptance_20261021.json`이고
SHA-256은
`c96bc368dbd3e03a6d7080ae8c74c0ff6e62a095b7770a1d85b5f3d186b0b895`다.
이 artifact는 8 receipts와 17 manifests를 정확히 보존한다.

## 중단 뒤 증거 대조의 한계

과거 coordinator tool session `33138`은 종료 뒤 조회할 수 없어 그 프로세스의 exit
code를 직접 관측하지 못했다. 리드는 각 6-phase worker의 supervised return code 0,
owned process 전수 reap, 닫힌 log와 sealed aggregate를 대조해 완성된 immutable artifact
chain을 수락했다. 이 판단은 과거 coordinator exit 0을 주장하지 않으며, 누락된 session
관측을 다시 만들기 위해 완료된 first-five audit를 재실행하지 않는다. 회계 산식,
period/unit/Q4 선택, reader gate와 producer source는 바뀌지 않았다.

결정 기록 locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/resume_20261021_root/first5_reconciliation_decision.json`이고
SHA-256은
`249813a4c54ecad840dc6e12697a6dbb1592cc14773061908354312cbbdef608`다.

## 2026-10-21 실행 결과와 현재 gate

ROOT는 canonical first-five 뒤의 fresh protected baseline을 수락했다. inventory locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/later45_actual_l4_runtime_r2/keeper-results/protected-inventory-r3.json`이고
SHA-256은
`081720ff3b6a2405a53c700e3fa6604bf138933a67c0109d567e7b5efb4c9599`다. local
acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_protected_baseline_acceptance_20261021.json`이고
SHA-256은
`37dbeb4eb8893a8d88c6d1e90af2157d2e3790d87c0b2d6ca05708f473e010b0`다.

baseline capture가 사용하는 pinned validator의 project dependency는 source 또는 전역
환경을 바꾸지 않고 project-local user base에 결속했다.
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/resume_20261021_runtime_deps/lib/python3.12/site-packages/project-runtime.pth`가
기존 main `.venv`의 site-packages를 가리킨다. 실행 시 `PYTHONUSERBASE`를 이 root로
지정하고 `PYTHONNOUSERSITE`는 설정하지 않는다. 이 결정 기록은
`resume_20261021_root/project_runtime_dependency_binding.json`, SHA-256
`28d37fb1b5ded6493d21e502a27aa2e1893afb7faee5960cf94491c5660e34fa`다. package 설치,
source 변경 또는 global environment 변경은 없었다.

첫 later-45 대상 AMD의 metadata-only preflight는 History build 전에
`ValueError: target source scope differs`로 중단했다. request, GO, History worker는 실행하지
않았고 자동 재시도도 하지 않았다. 실패 증거는
`resume_20261021_operator/AMD_metadata_preflight_failed_evidence.json`, SHA-256
`33de4e13148ed84054a652623b12c8cce112073ccd635bc86e650d3675b23b18`다.

ROOT의 45사 metadata-only 대조 결과, 45사 모두 candidate original intake hash와 adopted
collection intake hash가 다르다. JSON을 비교하면 각 filing의 `status`가 original의
`INGESTED`에서 adopted collection의 `REUSED`로 바뀐 것만 다르고 plan, filing metadata,
source 의미에는 다른 차이가 없다. 현재 runner는 두 hash를 하나의 target hash로 동시에
검증하므로 AMD에서 충돌했다. 진단 locator는
`resume_20261021_root/later45_intake_binding_diagnosis.json`, SHA-256
`c2b4667653d774dfb287799c1a8c55be8eb2ff3252c7aba8f8392a02fa88cc41`다. 이를 해결할
최소 별도 original/adopted hash 검증은 사용자 결정 대기 중이다. 따라서 아직 50사
financial-ready 상태가 아니며, 결정 전에는 code 변경이나 metadata 재시도를 하지 않는다.

결정 뒤에도 collection 순서를 유지해 first-five를 뺀 45사를 한 회사씩 처리한다. 각
worker는 process-tree RSS 16 GiB, 10,800초, Polars threads 2, one-heavy-stage, no
`RLIMIT_AS` 경계를 유지한다. 실패 root를 보존하며 자동 retry, cleanup 또는 acceptance를
하지 않는다. 50개 History가 수락된 뒤 source `4357c83…`로 FULL50 financial 8 stages와
H5 exact 107 manifests/6 phases를 검증하고, 별도 private journal UAT와 ROOT 승인 뒤에만
controlled live rollout을 판단한다.

protected baseline은 canonical first-five acceptance, Raw·package·metadata,
first-five History와 failed roots가 모두 동일할 때만 later-45 전 구간에서 재사용한다.
새 later-45 History root를 baseline에 추가하거나 회사별 fresh config/request/GO/receipt를
생략하지 않는다. 어떤 protected input이나 source pin이 바뀌면 즉시 중단해 새 ROOT
판단을 받는다.

## 보존 경계와 repository 상태

현재 21사 live UI와 원래 journal/records는 계속 보존한다. later-45와 FULL50 작업은
그 live process나 journal을 중지·교체·재사용하지 않는다. live 전환 전에는 기존
reference 전수 재열기, 별도 copied journal의 visual·keyboard·restart·save·reopen UAT,
rollback/restore 증거가 필요하다.

이 기록은 local operational status다. source 구현, 테스트, main 병합, push, PR, remote
CI 또는 controlled live rollout 완료를 뜻하지 않는다. 구현 source identity와 runtime
bytes는 기존 accepted pin을 유지하며, 이번 handoff는 문서만 갱신한다.
