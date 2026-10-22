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

## 2026-10-21 후속 승인과 source 교정 상태

앞 절의 “사용자 결정 대기”는 그 checkpoint 당시 상태를 보존한 기록이다. 사용자는 이후
original candidate와 adopted collection intake의 identity를 분리해 검증하는 최소 수정을
승인했다. runner commit `07d0999ee2666b970bdfdb3cbb8aee8c849c3565`는 adopted
intake hash를 target identity로 계속 검증하면서 original candidate path와 그 자체 hash를
별도로 고정한다. 다른 JSON 의미가 동일한 경우에만 `INGESTED`에서 `REUSED`로의 adoption을
허용하며 plan, CIK, accession, period, source와 기존 complete/attestation 검증은 유지한다.
focused 검증은 110 tests PASS와 Ruff PASS였고, local source acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_history_recovery_source_acceptance_07d0999.json`,
SHA-256 `0152fecacb57955cebb5e3c0dd7d2eb12d1623f7a19efa3253b7cf7a1ba0502a`다.
이 수정은 Raw, filing metadata 또는 회계 의미를 바꾸지 않는다.

서로 다른 physical source root가 우연히 같은 leaf 이름 `intake`를 사용하는 경우의 false
collision도 별도 engine compatibility 수정으로 해소했다. engine commit
`6c1d9de66d8d9b58c8d9bbed9b64571e694f6553`는 기존 directory, top-level symlink와
`root.name == run_id` 검증 뒤 resolved physical root로 중복을 판정한다. 서로 다른 root의
같은 leaf 이름은 허용하지만 동일 physical root의 alias/repeat는 거부하며 snapshot
identity·integrity와 output fingerprint 의미는 유지한다. focused corpus/history 검증은
222 PASS, 1 SKIP였고 별도 독립 검토 뒤 local source acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_history_engine_source_acceptance_6c1d9de.json`,
SHA-256 `dc9b04d9e00db310b969a9905e7e25505b57995d68ba8fd571924a2656b063b9`다.

later-45 runtime은 이 두 accepted source identity에 다시 결속했다. 기존 protected baseline
`081720ff…`는 canonical first-five `c96bc368…`와 원래 capture authority를 정확히 고정한
좁은 compatibility 검증을 거쳐 재사용했으며 baseline capture나 first-five build/audit를
반복하지 않았다. AMD fresh build는 bounded keeper 안에서 operational exit 0과 닫힌
resource/process 증거를 냈다. 그러나 이는 semantic acceptance가 아니며, 현재 L4 R4 AMD
감사가 한 번 실행 중이다. AMD History와 exact-50 전체는 아직 local acceptance 또는
financial-ready 상태가 아니다. 앞선 실패 root와 로그는 그대로 보존한다.

현재 21사 live UI, catalog와 원래 journal/records는 이 source 수정 및 later-45 작업과
분리해 계속 보존한다. 남은 회사도 collection 순서대로 회사 하나, heavy stage 하나씩
ROOT의 별도 request와 GO로만 진행하며 자동 재시도나 자동 acceptance를 하지 않는다.

## 2026-10-22 AMD 수락과 다음 회사 진행 상태

앞 절의 AMD 감사 실행 중 상태는 이후 완료 증거로 대체됐다. intake adoption과 same-leaf
source-root 수정 뒤, actual auditor에도 original candidate와 adopted intake를 분리해
검증하는 동일한 status-only 계약을 적용했다. source-only focused controls는 회사마다
반복하지 않고 이미 독립 검토된 결과를 재사용한다. AMD의 fresh History build와 L4 감사
113 guards, 독립 artifact reconciliation이 PASS했고 ROOT는 AMD History를 local
acceptance했다. acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_AMD_history_actual_acceptance_20261021.json`,
SHA-256 `768943807742961f4e1cd14c108bc15953bbdbc3e41a7d62a102fd6aec57c989`다.

AMD governed period inventory에서 발견된 FY `fiscal_quarter` null-only 가정은 기존
FY-null fixture를 유지하면서 canonical History의 exact integer 4도 허용하는 좁은 adapter
수정으로 교정했다. source row, schema, hash와 order key를 정규화하지 않고 그대로
보존하며 FY와 QTD 목록은 `period_class`로 계속 분리한다. focused owned controls는 16 PASS였고
source acceptance SHA-256은
`c4c6e91b0988ab08903d6e84330bab86a1e4819fe531c4dadb0bab3b26970d79`다.
AMD inventory는 1 GiB/120초 metadata resource 경계에서 PASS했고 FY input 2021–2025,
display 2022–2025, QTD years 2021–2026을 보존했다. History와 period-readiness의 ROOT
acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_AMD_history_period_readiness_acceptance_20261022.json`,
SHA-256 `923c68befd51f8453044ca36acd5dd562b7346e4a1f402948b28fe8d49578801`다.
이로써 accepted History와 governed period scope를 갖춘 회사는 기존 first-five와 AMD를
합쳐 6사다. 이는 50사 financial-ready나 live rollout acceptance를 뜻하지 않는다.

다음 collection 순서인 AAPL은 fresh metadata preflight와 ROOT GO를 거쳐 현재 한 번의
bounded History build가 실행 중이다. AAPL History, 감사, period inventory와 financial은
아직 수락되지 않았다. 회사별 source-only test 재실행, 자동 retry 또는 자동 acceptance는
하지 않으며 실패·운영 보정 증거는 모두 보존한다. 현재 21사 live UI, catalog와 원래
journal/records는 중단하거나 교체하지 않고 계속 보존한다.

## 2026-10-22 INTC 감사 중단과 nullable binding 교정

collection 순서에 따른 단일 회사 실행을 계속해 AMD, AAPL, MSFT, AMZN, NVDA, NFLX,
TSLA, META, GOOGL, AVGO의 History와 governed period inventory를 ROOT가 local
acceptance했다. 기존 first-five를 포함해 History와 period-readiness가 수락된 범위는 현재
15사다. 이는 FULL50 financial-ready 또는 live rollout acceptance가 아니다.

INTC History build는 accepted engine `6c1d9de66d8d9b58c8d9bbed9b64571e694f6553`와
runner `07d0999ee2666b970bdfdb3cbb8aee8c849c3565`로 PASS했지만, R5 L4 감사의 source
eligibility phase에서 중단됐다. 감사 대상 AS_FILED/INSTANT cell 5,700개 중 5,698개는
REPORTED binding과 lineage를 가졌고, 2개는 ambiguous actual-period boundary로 인해
producer 계약대로 `UNAVAILABLE`과 null binding/lineage를 보존했다. auditor가
`value_status`를 확인하기 전에 binding evidence를 읽어 `AttributeError`를 낸 것이 원인이며,
History나 accounting meaning의 불일치는 아니다. 실패 attempt, output과 observer SHA-256
`c36164a7a6f406cd699716bf77300d432a89ccf2a5b5d0b20dbfda54e434c028`는 그대로
보존하고 INTC build를 반복하지 않는다.

R6 auditor 후보는 non-REPORTED cell을 먼저 ineligible로 판정하고, REPORTED cell에는
mapping lineage와 binding, mapping 원소의 evidence list를 fail-closed로 요구한다. 기존
source, namespace, unit, canonical mapping, statement evidence, Q2/Q3/Q4, continuity, recast,
filed-date와 Decimal arithmetic 조건 및 source/consumer full-record equality는 유지한다.
focused synthetic 검증은 19 PASS와 Ruff PASS이며 17개 script 중 checker만 바뀌고 나머지
16개와 protected baseline hints는 byte-identical이다. 이 후보는 아직 독립 검토와 ROOT
acceptance 전이며, 새 INTC audit GO나 actual dispatch 권한을 만들지 않는다.

다음 회사 MU의 build는 기존 accepted R5 runtime과 R4 launcher로 별도 bounded 실행 중이며
nullable-auditor 변경과 무관하다. MU와 INTC 모두 각자의 semantic acceptance 전에는 accepted
15사 집계에 포함하지 않는다. 21사 live UI, catalog, journal과 원래 records는 계속 보존하며,
회사 하나와 heavy stage 하나씩만 실행하고 자동 retry, cleanup 또는 acceptance를 하지 않는다.

## 2026-10-22 INTC R6 복구 수락과 R5b 실행 결속

nullable-binding auditor R6는 writer와 독립 검토에서 각각 focused 19 tests PASS를
기록했다. source acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_l4_nullable_binding_r6_acceptance.json`,
SHA-256 `b736fd14600515118f1c1af91b85361ba6a8305b72274264e2e53beeeb40b290`다.
R5의 첫 복구 시도는 payload phase 전에 keeper policy path가 이전 R4를 가리킨다는
`KEEPER_POLICY_FIXED` 검증으로 중단됐으며, 그 실패 root와 observer는 보존했다. source나
History payload는 바뀌지 않았다.

fresh R5b keeper는 policy를 포함한 모든 keeper role을 새 root에 고정했다. accepted source
pins SHA-256은 `aa0102c1a4764dc5b38954a4d78328372735745204d9663736de76d43b30b8b8`,
bound-runtime acceptance SHA-256은
`8702a20d90f4fc0919e139f047ac75f3f8978e980158450815dcf30e49741491`,
launcher SHA-256은 `565157e81d1a97e6afb7dc3ca7305cd9bc95e8f70c5c46637dcc2ef0d2359e64`다.
ROOT launcher acceptance locator는
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_root_later45_nullable_binding_stable_launcher_r5b_acceptance.json`,
SHA-256 `a2a513c6f2acdfb10740b2383e954934d211ebb3c9b37d88e91757043d0ef013`다.

R6b actual audit는 112 guards와 109 jobs를 통과해 102 files, 416,099 records를 검증했고,
INTC History acceptance SHA-256은
`b565eb587f0fde76a16762a66274f899787092016c59324d538aba0432872276`다.
후속 governed period inventory acceptance SHA-256은
`e07aaac90ce1ce98d2721a9b04254dc86143f03eda6e74acd60efcb74aa4212c`다.
따라서 기존 first-five를 포함한 History와 period-readiness 수락 범위는 16사다. MU 감사는
별도 bounded 실행 중이며 아직 이 집계에 포함하지 않는다. FULL50 financial-ready와 live
rollout은 아직 수락되지 않았다.

21사 live UI, catalog, journal과 원래 records는 이 복구 과정에서도 중단하거나 변경하지
않았다. 남은 회사도 collection 순서, 회사 하나와 heavy stage 하나, 별도 ROOT GO, 실패
root 보존, no automatic retry/acceptance 경계를 유지한다.

## 2026-10-22 20/50 History·period input readiness

MU, QCOM, WMT와 COST의 History proof와 governed period inventory를 ROOT가 각각 local
acceptance했다. exact readiness acceptance는 다음과 같다.

- MU: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_MU_history_period_readiness_acceptance_20261022.json`, SHA-256 `a765119c33fb065125e63d2350d38a48e1bac165b7c99cdc1ab71c93ec84e819`
- QCOM: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_QCOM_history_period_readiness_acceptance_20261022.json`, SHA-256 `8fb6b90acee7bb8f167423ef7829f3f1fda837722f5910618a1d96a5fbc75bba`
- WMT: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_WMT_history_period_readiness_acceptance_20261022.json`, SHA-256 `a30594ee8e9da293e8145bfa6dc808cb7907a05d41553400465663f205a9043e`
- COST: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_COST_history_period_readiness_acceptance_20261022.json`, SHA-256 `26c130184010e715ee9334930013ffb36bcd4e6031d544b8451a3792d8c71e52`

이 네 회사와 앞서 수락한 16사를 합쳐 exact-50 collection 중 20사가 History와 governed
period input ready 상태다. 이는 FULL50 financial 또는 UI ready 상태가 아니며, 30사의
History·period readiness가 더 필요하다. TGT build session 77264는 현재 실행 중이므로
accepted 20사 집계에 포함하지 않는다.

50사 input readiness가 완료된 뒤에도 ROOT가 final FULL50 config와 별도 GO를 확정하고,
annual analysis, quarterly analysis, quality, identity, annual metrics, annual dataset v2,
quarterly metrics, combined dataset v3의 고정 8단계를 실행해야 한다. 이어서 H5의 107개
manifest·6개 phase 검증, 독립 acceptance, private-journal UAT와 controlled rollout이 남아
있다. original first-five acceptance proof와 nullable auditor의 writer·independent 19+19 PASS
source evidence는 변경하거나 반복하지 않고 재사용한다. 기존 21사 live runtime, catalog,
journal과 원래 records도 변경 없이 보존한다.

## 2026-10-22 25/50 History·period input readiness

TGT, CAT, DE, PCAR와 PG의 History proof와 governed period inventory를 ROOT가 각각 local
acceptance했다. exact readiness acceptance는 다음과 같다.

- TGT: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_TGT_history_period_readiness_acceptance_20261022.json`, SHA-256 `8636e59bab788181b832dfee4dbc7ea4889796b9bf63dbde911d8228ea56d3b0`
- CAT: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_CAT_history_period_readiness_acceptance_20261022.json`, SHA-256 `916cac8e08afdfe08d4a06055c70c71bd25fac8dc3dc78ed7a79a5f0a35e72a6`
- DE: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_DE_history_period_readiness_acceptance_20261022.json`, SHA-256 `8eaa7b8d400608768289958d0f57bef86e6406cba74498337d01e94a5c6d097c`
- PCAR: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_PCAR_history_period_readiness_acceptance_20261022.json`, SHA-256 `f67a157fae83ff3a83720a24ef6c986fe5965f55e8348a844768c4eca95be565`
- PG: `work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_PG_history_period_readiness_acceptance_20261022.json`, SHA-256 `e2b270388d01fde92dfe0397ce4cc1c20a0c0ca3af5d056c71edae94021f78b8`

이 다섯 회사와 앞서 수락한 20사를 합쳐 exact-50 collection의 절반인 25사가 History와
governed period input ready 상태다. 나머지 25사에는 현재 build session 58068에서 실행 중인
KO가 포함되며, KO는 아직 accepted 집계에 포함하지 않는다. 남은 회사의 metadata preflight,
request와 build GO는 ROOT가 이미 실제 execution root에 작성했으므로 반복 생성하지 않는다.

이 halfway checkpoint는 FULL50 financial, H5 또는 UI ready 상태가 아니다. 남은 25사의
History·period readiness 뒤 final FULL50 config와 고정 8개 financial stage, H5 107개
manifest·6개 phase 검증, 독립 acceptance, private-journal UAT와 controlled rollout이 여전히
필요하다. original first-five proof와 nullable auditor의 writer·independent 19+19 PASS source
evidence는 변경하거나 반복하지 않고 재사용한다. 기존 21사 live runtime, catalog, journal과
원래 records도 변경 없이 보존한다.

## 2026-10-22 CRM fiscal-focus contradiction and expansion stop

현재 local acceptance 범위는 History 33사, governed period input 32사다. CRM History는
112-guard actual audit를 통과해 SHA-256
`fa56d5a1dba8ba141be2254c4d722cc0dd95dbbecbe26c1e44bb8ccffc33882d`로 수락됐지만,
period inventory는 annual input이 2022–2025 네 해뿐이어서 strict five-year gate에서
중단됐다. 따라서 CRM은 financial-ready가 아니며, 이 차이를 해결할 ROOT 결정 전까지
실제 expansion을 중단하고 ADBE를 dispatch하지 않는다.

원본 cache를 128 KiB prefix로 제한해 확인한 결과, accession
`0001108524-26-000060`의 primary member `crm-20260131.htm`은 실제 inline tag
`<ix:nonNumeric contextRef="c-1" name="dei:DocumentFiscalYearFocus" id="f-36">2025</ix:nonNumeric>`와
`DocumentFiscalPeriodFocus=FY`를 포함한다. context `c-1`은 2025-02-01부터
2026-01-31까지다. cache manifest SHA-256은
`097fdd83464cd8deff6491dd11da23bfc38ab6fce031e3a9ed931cb5106e0cbc`이고, 그 manifest가
고정한 original XBRL ZIP SHA-256은
`ac8c422770e833578a05fc4ce7312ebb5b388aa8442890ef5103bb9c77df6a47`다.

Layer 1 snapshot manifest SHA-256
`9f3d28a4415306406964d36d231ac60c657cc1380ef8f12988d8fa144268ce20`과 filing table
SHA-256 `1afe9fe88cb54d215f70ad1548ba9013b4e0d28ff2cebec8e70c8958e3907898`도 이 값을
그대로 보존했다. 따라서 `2025`는 Layer 1 변환 오류가 아니라 원본 inline metadata다.
동시에 같은 [SEC 10-K 본문](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm)은
fiscal 2026을 2026-01-31에 끝나는 회계연도로 명시하고, [Salesforce FY2026 실적 발표](https://investor.salesforce.com/news/news-details/2026/Salesforce-Delivers-Record-Fourth-Quarter-Fiscal-2026-Results/default.aspx)도
2026-01-31 종료 full fiscal year로 설명한다. 원본 inline DEI fiscal-year focus와 원본
filing narrative가 충돌하는 source-level contradiction이다.

기존 규칙대로 calendar endpoint에서 fiscal year를 추론하거나 five-year gate를 완화하지
않는다. CRM History build/audit, failed inventory와 모든 proof는 그대로 보존하며 ROOT의
명시적 처리 결정 전에는 correction, rebuild 또는 retry를 하지 않는다. 기존 first-five proof와
nullable auditor 19+19 PASS evidence를 계속 재사용하고, 21사 live runtime, catalog, journal과
원래 records도 변경하지 않는다. FULL50 financial, H5와 UI readiness는 아직 성립하지 않는다.


## 2026-10-22 CRM accession-scoped correction 승인

사용자는 CRM accession `0001108524-26-000060`에 한해 Raw lexical `2025`를 보존하고
reviewed effective fiscal year `2026`을 Layer 2 input에 적용하는 보정을 승인했다. exact
CIK/accession, inline fact `f-36`, context `c-1`, primary document, report/context dates와
package manifest·ZIP hashes가 모두 일치해야 하며 mismatch, malformed 또는 unconsumed entry는
fail closed한다. calendar year 추론, ticker-specific core 분기, Raw 수정, five-year gate 완화와
기존 Q4·lineage·quality 정책 변경은 승인 범위가 아니다. 상세 계약은
[CRM accession-scoped fiscal-focus correction](crm-fiscal-focus-correction.md)에 있다.

이 승인은 source와 focused test 구현만 허용한다. fresh CRM History build, audit, inventory,
financial 실행과 ROOT GO·acceptance는 새 source와 runtime의 동결·독립 검증 뒤 별도다.
History 33사, governed period input 32사 상태와 중단된 actual expansion, 기존 21사 live
runtime/catalog/journal 보존 상태는 이 승인만으로 바뀌지 않는다.

## 2026-10-22 CRM correction source freeze

The user-approved accession-scoped correction is frozen in local engine commit
`5de43fa9193ee8972b54a0720d8b26cd0dd4024c` and recovery-runner commit
`27d11238d77129df361ca0a3b13f87e024a6db9a`. Focused validation passed 5 engine
and 2 runner tests; Ruff and diff checks passed. The hash-bound correction artifact
proposal is `resume_20261022_crm_fiscal_focus_correction/crm_fiscal_focus_correction.json`
under the resumption work root, SHA-256
`a5341665926da32479f990d4e776bc0ee1ab897fabbfaf7a0fd4fd57fc3b616c`.

The source keeps Raw `2025`, applies effective `2026` only on the exact approved
CIK/accession evidence before Layer 2 period observation, and preserves reported,
effective and source-approval provenance. It does not relax the governed five-year
inventory or any Q4, lineage or quality rule. CRM remains outside the financial-ready
count until independent source/runtime acceptance, a fresh ROOT-governed build and
audit, and a fresh governed period inventory all pass. The stopped checkpoint remains
33 History and 32 governed-period companies; the existing 21-company live runtime,
catalog and journal remain unchanged.

## 2026-10-22 CRM correction evidence-binding amendment

The initial CRM correction freeze above remains historical and was not accepted. Independent
review report
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/independent_crm_fiscal_focus_correction_20261022/report.json`,
SHA-256 `a81e4c73771a983803e48bfb7e8474c05e862775d9bd7d4ca70fecdff82d5e62`,
found that the first implementation trusted declared fact/context fields without independently
matching them to the cached inline source. The unaccepted artifact bytes are preserved separately
as `crm_fiscal_focus_correction_unaccepted_a5341665_historical.json`, SHA-256
`a5341665926da32479f990d4e776bc0ee1ab897fabbfaf7a0fd4fd57fc3b616c`.

The amended engine commit is `1d4fbc8c03270ffa48dd1b3b11f78d68bab009fd`. It binds the ROOT evidence
supplement SHA-256 `797f2df5ba46a56bff05e9d8555a59824e64534a285196aac9dfcda162dbde6b`,
verifies the exact cached ZIP hash and the single `crm-20260131.htm` member's size and CRC,
then reads at most 131072 member bytes to match fact `f-36`, context `c-1`, reported lexical
`2025`, and context dates 2025-02-01 through 2026-01-31. A synthetic 1900 context fails closed.
The amended governed correction artifact SHA-256 is
`41f14d24b947110c06a7fb4fdc695a0a0141526c51e445b5f4053a91b07cbc35`.

The amended runner commit is `f9a3f20b59064a5b1031e0ebd1417efb62e04123`. Its correction-only seam
requires the exact prior accepted CRM READY marker, keeps the collection plan, intake, marker and
receipts hash-stable, and writes the fresh corrected marker and typed receipt under a separate empty
evidence root. Focused engine validation passed 6 tests; focused runner validation passed the two
correction threading tests and the collection-preservation control, with the latter repeated once
after fixing its fixture setup. Ruff and diff checks passed. ROOT accepted these source-only commits
in `lead_crm_fiscal_focus_source_acceptance_1d4fbc8_f9a3f20.json`, SHA-256
`43d8a092d912806011ad3386d02e9f81fd4947ec87d3abcda82e4707dacfe331`. The R7 runtime
profile remains proposed pending its independent review and ROOT acceptance; no CRM rebuild, audit,
inventory or GO has run from it. The readiness checkpoint therefore remains 33 History and 32 governed-period
companies, while the existing 21-company live runtime, catalog, journal and original records remain
unchanged.

## 2026-10-22 CRM corrected History and governed-period local acceptance

The user-approved CRM accession correction has completed its separately governed source, runtime,
build, audit and period-inventory stages. ROOT accepted the final `1d4fbc8c…` engine,
`f9a3f20b…` runner, R7c audit and R6c keeper/launcher binding in
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_root_crm_fiscal_focus_final_runtime_acceptance_20261022.json`,
SHA-256 `89f3a5fca4e6c7cca3acbcc111e4eeef37770449fe9fbadf9e6332d2830da9f9`.
The earlier independent FAIL reports and the R7/R7b/R6b control attempts remain preserved as historical
evidence; this acceptance applies to the final exact R7c/R6c bytes only.

The fresh corrected CRM History build and 112-guard R7c audit passed with 102 files and 384006 records.
ROOT's company History acceptance is
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_CRM_fiscal_focus_history_actual_acceptance_20261022.json`,
SHA-256 `76d9993b29047ac58a8e694ef0b2f73c7b51dc3f9616272766cbffd76e9dbfa7`.
The governed period inventory then passed with annual input years 2022–2026, display years 2023–2026,
and quarter-input years 2022–2027. Its readiness acceptance is
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_CRM_history_period_readiness_acceptance_20261022.json`,
SHA-256 `da9d019e71e8108dad719d1014fb174c1543a70fd7afa06bb8bba5d80fab546a`.
The accepted History root is
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/ops_writer/history-later45-20261021/CRM-history-recovery-t3v2-later45-20261022-fiscal-focus-r4`;
the accepted period inventory is under
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/ops_writer/period-inventory-later45-20261022/CRM-fiscal-focus-r4-fy-quarter-r2`.

Raw Layer 1 still records the filed lexical fiscal focus `2025`. The corrected History retains that
reported value and its source provenance while applying reviewed effective fiscal year `2026` only to
the exact approved accession's Layer 2 period observation. The earlier as-filed CRM History acceptance
`fa56d5a1…`, original collection marker, failed inventory and immutable Raw source remain preserved.
The corrected acceptance supersedes them only for the downstream financial-input scope described by
[the accession-scoped correction contract](crm-fiscal-focus-correction.md); it does not redefine Raw.

Operationally, each actual stage was authorized by its own hash-bound ROOT GO and invoked through the
accepted bounded launcher or the accepted generic period-inventory worker: corrected History build,
R7c audit, then governed inventory. These evidence paths document the completed run; checkout-local
work directories are not normative prerequisites. Future runs must continue to follow the tracked
[period rules](period-rules.md), correction contract and delivery workflow rather than replaying this
historical session.

The exact-50 checkpoint is now 37 unique companies with locally accepted History and 37 with governed
period inputs. Financial output remains the accepted first five only. NKE is the active next bounded
build, followed by KDP, MCD, GE, HON, UPS, UNP, MRK, ABBV, ABT, COP, DUK and LIN; none is counted before
its separate History and period readiness acceptance. FULL50 financial production, the fixed eight
financial stages, H5, private-journal UAT, controlled live rollout and main merge remain pending. The
existing 21-company live runtime, catalog, journal and original records remain unchanged.

## 2026-10-22 HON fiscal metadata conflict and expansion stop

The exact-50 checkpoint has advanced to 42 companies with locally accepted History and 41 with
governed period inputs. HON History passed its 113-guard actual audit with 103 files and 645206
records; ROOT's History-only acceptance is
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_later45_HON_history_actual_acceptance_20261022.json`,
SHA-256 `1bdaeb851868e8e6394453cf0830055471f2cf444c856a42dd06b12120a64edb`.
HON is not period-ready: the strict inventory found annual years 2020, 2022, 2023, 2024 and 2025,
so the five-consecutive-year contract correctly failed. The failed resource and all accepted History
evidence remain preserved.

ROOT's bounded diagnosis is
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/resume_20261021_root/hon_original_fiscal_metadata_conflict_diagnosis.json`,
SHA-256 `26347259caa139af8cf6ae6831c030e7b62b6d29bfb1dda71b02a4013be71a2e`.
It read at most 131072 bytes from each of two exact cached members and did not reparse or scan the
broader Raw corpus:

- Annual accession `0000773840-22-000018`, member `hon-20211231.htm`, reports
  `DocumentFiscalYearFocus=2020` and `DocumentFiscalPeriodFocus=FY` against context
  2021-01-01 through 2021-12-31. Its immutable ZIP path is
  `data/raw/universe_runs/20261010_universe50_quarterly/resumption_20261013/packages/0000773840/000077384022000018/0000773840-22-000018-xbrl.zip`,
  SHA-256 `0adb0f3401383fb8ecf4d7195f4a87d6700a1f5a5663c45ad9bd497e944494cf`;
  the Layer 1 manifest SHA-256 is
  `cb1a63cb0e8fd482d2263b880deeb42fc6a9e84655a3b0c845d3e693c0481b1c`.
- Quarterly accession `0000773840-21-000065`, member `hon-20210930.htm`, reports
  `DocumentFiscalYearFocus=2021` and `DocumentFiscalPeriodFocus=Q2` against context
  2021-01-01 through 2021-09-30. Its immutable ZIP path is
  `data/raw/universe_runs/20261010_universe50_quarterly/resumption_20261013/packages/0000773840/000077384021000065/0000773840-21-000065-xbrl.zip`,
  SHA-256 `3214759e7e6468681a60fd45630b175ea7df87e1eff6226bb4541e3b92d9d26f`;
  the Layer 1 manifest SHA-256 is
  `5176ed253b2bacc314d9c70f15f1a2fd81b57e39a900bf7b5b05321e09fac3f8`.

The diagnosis proposes two exact, evidence-bound effective values for human accounting review:
annual fiscal year `2020` to `2021` and quarterly fiscal period `Q2` to `Q3`. Neither correction is
approved or implemented. In particular, fiscal-period focus is new accounting meaning beyond the
approved CRM year-only correction contract. Raw remains unchanged, and no rule, source, runtime,
History or inventory has been modified or rerun for HON.

Actual expansion is stopped while the user decision is pending. UPS, UNP, MRK, ABBV, ABT, COP, DUK
and LIN are the other eight companies still lacking accepted governed-period readiness; no remaining
dispatch is authorized by this checkpoint. Raw and metadata remain complete for 50 companies, while
financial output remains the accepted first five only. FULL50 financial production, the fixed eight
financial stages, H5, private-journal UAT, controlled live rollout and main merge remain pending. The
existing 21-company live runtime, catalog, journal and original records remain unchanged.
