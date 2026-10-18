# 50사 재무 스크리닝 재개 상태 — 2026-10-18

## 문서 성격과 현재 결론

이 문서는 2026-10-18 KST의 **CURRENT SNAPSHOT**이다. 최종 완료나 live 전환
기록이 아니다. 제안·승인·구현·독립 검증·로컬 인수·actual data·main 병합을
각각 구분한다. `work/`의 실행 증거는 이 상태를 뒷받침하는 선택적 보존 자료이며,
새 checkout에서 계획을 이해하거나 다음 gate를 재현하기 위한 유일한 권위나
선행 조건이 아니다.

사용자 목표는 exact 50사에 대해 provenance가 보존된 재무 스크리닝을 완성하고,
기존 명시적 저장과 History 재열기 흐름을 같은 governed publication 위에서 유지하는
것이다. 현재 이 목표는 **미완료**다.

## 현재 상태

| 경계 | 2026-10-18 현재 상태 | 아직 성립하지 않는 것 |
| --- | --- | --- |
| Raw·metadata | Raw exact 50사, 1,097 filings·snapshots와 9,873 raw files, metadata 50사가 `LOCALLY_ACCEPTED` | financial·History·UI 인수의 대체 아님 |
| History | first-five `TXN, HD, JNJ, CVX, NEE`가 actual History local acceptance를 받음 | later-45 build·audit·인수 미수행 |
| financial producer | exact source `4357c83…`의 original first-five 8 stages와 17 publication manifests가 PASS | canonical first-five financial acceptance 미작성 |
| H5 actual audit | R8 semantic phase PASS: annual 620, quarter 680 records | public annual·quarter·v2·v3와 seal은 PENDING; all-six PASS 아님 |
| consumer source | `237a56c6fe3b6453f379061e5aeb964a9e0b54a8`가 159 fresh guarded PASS와 prior 483 reused mapping 근거 뒤 source/synthetic local acceptance를 받음. lead acceptance SHA-256은 `7258bd61815659dc847455f08e30a06bb47f127a615be392f3d109ece5a340e7` | actual 50사 data, UAT, live rollout 또는 main 병합 아님 |
| live UI | 기존 21사 source `e84289a54acae92bee45a9d0224d71133acc13aa`와 명시적 저장 기능을 유지 | 50사 dataset이나 journal로 전환하지 않음 |
| repository | main `201acf9aec2f8183acb7dd843579938db14236cd`; 이번 재개 결과의 push·PR·remote CI·merge 미수행 | source/local data 인수를 main 배포로 해석하지 않음 |

따라서 later-45, FULL50 financial/H5, native UAT와 controlled live rollout은 모두
**PENDING / NOT_READY**다. 현재 수치는 완료 예상이나 ETA가 아니다.

## source와 감사기 변경의 의미

R8은 H5 auditor의 native `dir_fd` 호출 origin과 private duplicate FD를 정확히
결속하는 감사 경계 수리다. producer `4357c83…`, accounting formula, period·unit·Q4
선택, Raw bytes와 original 8 receipts를 바꾸지 않는다. R8 actual audit는 semantic
phase까지만 PASS했으므로 canonical first-five acceptance를 만들 수 없다.

R9는 FULL50 plan assembler가 이미 accepted된
`full50_operational.expected_full_manifests`를 사용해 107 manifests를 열거하도록
routing한 audit-only source 수리다. first-five의 기존 17-manifest helper는 그대로다.
R9 source/owned controls와 exact runtime/operator copies는 accepted됐지만 actual FULL50
실행 권한이나 결과가 아니다. R8과 R9 모두 financial source `4357c83…`나 회계 의미를
바꾸지 않는다.

다음 불변조건은 그대로다.

- Raw는 immutable이고 reported·derived 값을 섞거나 덮어쓰지 않는다.
- typed PRE는 validation/provenance evidence이며 public reader는 SQL을 우회하지 않는다.
- manual reviewed-Q4와 generic readiness는 서로 다른 gate다.
- 한 heavy operation만 실행하며 각 worker는 16 GiB RSS, 10,800초 cap과 no `RLIMIT_AS`를
  사용한다. audit 전체에 하나의 10,800초 outer timer를 두지 않고 phase별 예산을 보존한다.
- source acceptance, operational runtime copy, ROOT GO, actual receipt, independent review와
  local acceptance는 서로 대체하지 않는다.

## 남은 운영 순서와 완료 기준

순서는 다음과 같다. 앞 단계의 완료 artifact 없이 뒤 단계를 시작하거나 relabel하지 않는다.

1. **first-five H5 마감:** semantic, public annual, public quarter, public v2, public v3,
   seal의 6 phases가 모두 PASS해야 한다. 8 producer receipts, 17 manifests, exact source와
   typed evidence를 결속한 canonical first-five financial acceptance가 있어야 한다.
2. **protected baseline:** canonical first-five acceptance 뒤 Raw 9,873, package view,
   metadata 50, accepted first-five History와 financial artifacts, 보존된 failed roots의
   exact fileset/hash baseline을 새 ROOT 승인 아래 만든다.
3. **later-45 직렬 처리:** 한 회사씩 History build → L3/H5 audit → governed FY/QTD
   inventory → ROOT company acceptance를 완료한다. 자동 retry나 병렬 45사 실행은 하지 않는다.
4. **FULL50 financial:** accepted 50 History를 대상으로 original financial 8 stages를
   fresh 실행하고 FULL50 H5의 exact 107 manifests와 6 phases를 통과한다.
5. **최종 catalog:** 기존 reference set을 다시 검증한 뒤, first-five를 중복하지 않는
   later-45와 accepted first-five를 결속한 FULL50 catalog를 마지막에 발행한다.
6. **private-journal UAT:** live와 분리된 journal에서 visual·keyboard·restart·save·reopen,
   모든 old reference 재열기를 검증한다. 화면 PASS는 source test나 screenshot으로 대체하지 않는다.
7. **controlled live rollout:** UAT와 ROOT 승인 뒤에만 원래 live journal에 controlled
   전환한다. 기존 21사 운영 상태를 보존하고 rollback/restore 증거를 함께 남긴다.

각 단계의 `DONE`은 expected fileset/hash, bounded execution receipt, independent `PASS`,
lead local acceptance와 미수행 remote/main 상태를 명시한 tracked handoff를 요구한다.

## 규범 입력과 재현 가능한 인계

다음 tracked 문서만으로 순서와 경계를 이해할 수 있어야 한다.

- [공통 전달 절차](delivery-workflow.md)
- [로컬 source composition](universe50-local-source-composition-20261018.md)
- [재무 통합·실행 전달](universe50-financial-delivery.md)
- [History 복구 전달](universe50-history-recovery-delivery.md)
- [스크리닝 대시보드 로드맵](../planning/screening-dashboard-roadmap.md)
- [분석 데이터 모델](../architecture/analytical-data-model.md)

재현 시 각 단계는 accepted source와 runtime map을 확인하고, ROOT가 작성한 config/request/GO,
worker별 16 GiB/10,800초 resource receipt, output fileset/hash, independent report를 차례로
대조한다. actual payload가 없는 checkout에서는 이 문서의 상태·순서·완료 기준을 읽을 수
있어야 하며, 로컬 `work/` locator가 없다는 이유로 계약 의미가 달라지지 않는다.

이 snapshot 뒤 actual H5 또는 later-45 상태가 바뀌면 원문을 고쳐 과거를 지우지 않고,
새 dated status/acceptance commit으로 추가한다.
