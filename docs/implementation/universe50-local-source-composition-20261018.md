# 50사 로컬 source composition 전달 — 2026-10-18

## 결정과 상태

이 문서는 이미 source/synthetic 범위에서 인수된 세 component 이력을 한 로컬 Git
history에 보존하는 전달 기록이다. 리드 계약
`lead_local_source_composition_contract.json`의 SHA-256은
`5989906186349511375cad7180bf69d2553830dddfd3f714f36d1f1975b0c891`이다.
이 계약은 로컬 source merge와 추적 문서만 승인했다. actual 데이터 실행·인수, runner
gate 변경, live UI 반영, push·PR·main 병합은 승인하지 않았다.

| 단계 | 상태 |
| --- | --- |
| 제안 | 기존 source inventory에서 `fd9 + f222 + c9` tracked handoff를 권고 |
| 범위 승인 | **APPROVED — LOCAL SOURCE/SYNTHETIC COMPOSITION ONLY** |
| 구현 | exact `fd9`에서 ordinary merge로 exact `f222`, 그 다음 exact `c9`를 통합한 `135d49b…` |
| 독립 검증 | **PASS** — exact `135d49b…`, 410 passed, HTTP 2개 environment-deselected |
| 로컬 인수 | **LOCALLY_ACCEPTED_SOURCE_AND_SYNTHETIC_ONLY** — 2026-10-18 KST root lead |
| main 병합 | 미수행; push·PR·remote CI도 미수행 |

source composition은 component의 actual-data acceptance가 아니다. component별 기존
source/synthetic 인수도 새 merge commit에 자동 승계되지 않는다.

## 2026-10-18 독립 검증과 로컬 source 인수

구현 후보 `135d49bfbd97f77cbd5018efa82ec56a3650c58d`, tree
`5ab9f797cf319233d91edce0ca9c700cc964f1fb`를 별도 Astra가 read-only로 검증해
**PASS**했다. 독립 검증은 세 component의 282개 non-doc path가 exact accepted
component bytes와 같은지, ordinary merge ancestry, source gate 불변, tracked 문서의 상태
분리를 확인했다. guarded source/synthetic test는 410개가 통과했다. sandbox가 owned
loopback socket 생성 자체를 막아 explicit-save HTTP test 2개는 environment-deselected로
분리했으며 실패나 PASS로 바꾸지 않았다. 독립 report SHA-256은
`34b5b06d4527fa8d044009d83acea0fcfc14861dbe316abc99e3cea7f3b0f602`다.

root lead는 이 exact source/tree를
**LOCALLY_ACCEPTED_SOURCE_AND_SYNTHETIC_ONLY**로 인수했다. 인수 결정은 다음을
명시한다.

- 인수 source는 exact `135d49b…`이며 후속 문서 commit은 그 source와 독립 결과를
  변경하지 않는다.
- actual 운영 component HEAD는 계속 exact `fd9a179…`, `f222a8b…`, `c9e1316…`다.
  merged HEAD를 actual runner/engine/financial HEAD로 사용하지 않는다.
- 이 결정이 새로 인수한 actual data와 native UI는 없고 main 병합도 아니다.
- actual JNJ v3는 계속 `RUNNING` reference `90986`으로 별도이며 이 source 인수가 그
  완료·감사·인수를 뜻하지 않는다.
- first-five와 later-45 financial은 계속 `NOT_READY`이고 기존 live 21사 explicit-save는
  변경하지 않았다.

선택적 로컬 결정 기록
`lead_local_source_composition_acceptance_135d49b.json`의 SHA-256은
`22aebf6f8f05fd0b11601f51fda02bd24c7a8b6e7fa6fc49fed6a7be7361ad2a`다.
이 추적 문서가 결정의 범위와 다음 gate를 자체적으로 보존하므로 fresh checkout은
`work/` 기록에 의존하지 않는다.

## exact component와 merge history

새 branch `codex/universe50-local-composition`은 clean
`fd9a17910a7b1cfbb4e71e2ded6f4bc23cda686e`에서 시작했다.

1. `f222a8b77aefff2adb877f587e59cfd9ac03bf7d`를 ordinary `--no-ff` merge해
   merge commit `9b5b28199f4899386b3da51bf31d1598ec6bb95d`를 만들었다.
2. `c9e1316f2f3a3b8b2c3f893f67d24f3f64a2048f`를 ordinary `--no-ff`
   merge해 source merge commit
   `155fb3d8904f53f7789fd984d5fb81e2faa06657`를 만들었다.
3. 두 merge 모두 product/test conflict가 없었다. `docs/planning/README.md`도 Git이
   양쪽 추가를 보존해 conflict 없이 합쳤다. 구현자는 product/test byte를 수정하지 않았다.
4. 명시적 저장의 최종 source
   `e84289a54acae92bee45a9d0224d71133acc13aa`는 `fd9`의 ancestor이므로 다시
   merge하거나 replay하지 않았다.

component별 역할은 다음과 같다.

| Component | 역할 | composition에서 보존한 주요 경계 |
| --- | --- | --- |
| `fd9a179…` | canonical financial source, quarterly/TTM provenance, screening v2/v3 reader·service·store·UI | prepared REPORTED `source_snapshot_id`, explicit-save ancestry, immutable dataset identity |
| `f222a8b…` | bounded History/Fiscal/quarter spill engine | batching, typed spill integrity, ownership·cleanup; 회계·기간·선택 의미 불변 |
| `c9e1316…` | fail-closed History recovery orchestration | exact failed-root witness, attested reported-stage reuse, root GO와 component source pin |

`src/sec_xbrl/metrics/quarterly_screening.py`와 관련 fd9 tests, f222의 세 product
module과 네 tests, c9의 recovery tool/test는 각각 accepted component와 byte-for-byte
같아야 한다. 최종 handoff evidence가 그 hash mapping을 기록한다.

## 운영 source identity와 재현 순서

이 merged HEAD는 추적 가능한 source handoff다. 기존 recovery runner가 허용하는
operational runner/engine/financial checkout identity는 아니다. 그 gate는 의도적으로
변경하지 않았다.

현재 인수된 program entry를 재현할 때는 다음 세 clean historical checkout을 그대로
사용한다.

1. runner: exact `c9e1316…`
2. bounded History engine: exact `f222a8b…`
3. canonical financial validator와 screening source: exact `fd9a179…`

그 상태에서 기존
[History 복구 전달 계약](universe50-history-recovery-delivery.md)의 순서대로
source-only preflight, stage request, 리드의 request 검토와 exact root GO, guarded stage
실행을 진행한다. 이 문서는 새 GO를 만들거나 actual stage를 승인하지 않는다. merged
checkout을 component 중 하나로 대신 넣거나 source gate를 우회하면 안 된다. 미래에 한
checkout 실행이 필요하면 별도 승인된 composition gate 설계·구현·독립 검증이 먼저다.

## 보존하는 데이터·회계·화면 계약

- Raw는 immutable이며 CIK, accession, form, filed/report date, QName, context, unit,
  dimensions, role network와 source provenance를 보존한다.
- `financial_as_of=2026-10-10`과
  `metadata_observation_cutoff=2026-10-13T23:59:59Z`는 서로 다른 cutoff다.
- annual publication은 회사별 5 fiscal-year 입력과 최신 4 fiscal-year 표시를 유지한다.
  quarterly 입력 fiscal year는 회사별 명시 목록이고, 화면은 최근 완료 global calendar
  quarter bucket 최대 8개를 사용한다. 둘을 calendar year에서 추론해 합치지 않는다.
- annual metric 31개와 quarterly metric 17개를 유지한다. ROA·ROE는 추가하지 않는다.
- generic metric readiness는 별도 attested Raw/quality/identity chain이다. manual NVDA Q4
  completion과 같은 source kind로 표현하지 않는다.
- reported와 derived 값을 구분하고 unknown/unavailable을 임의의 0 또는 reported 값으로
  바꾸지 않는다. cross-company similarity는 accounting equivalence가 아니다.
- v3 publication은 immutable annual v2와 quarterly parent를 exact manifest/publication
  identity로 묶는다.
- 기존 journal의 saved context와 historical run이 참조하는 old dataset root/publication을
  catalog에서 보존한다. explicit preview는 저장하지 않고 save/load/reopen은 `e842`의
  dataset context와 hidden result backing을 유지한다.

이 composition은 parser, recast selection, period classification, quarterly arithmetic,
metric formula, UI/store policy 또는 source gate를 새로 바꾸지 않는다.

## 현재 actual 상태와 다음 gate

리드 계약 시점에 exact-50 Raw와 metadata는 인수됐고 History 네 회사가 인수됐다.
JNJ v3 actual run은 `RUNNING`으로 보고됐으며 참조 값은 `90986`이다. 이 문서는 그
payload, process 또는 결과를 읽거나 검증하지 않았다. first-five와 later-45 financial은
모두 **NOT_READY**다. 기존 21사 live explicit-save 상태는 그대로 유지하며 이 branch가
live server, journal 또는 catalog를 변경하지 않는다.

다음 순서를 건너뛰지 않는다.

1. 이 clean source composition 후보에 대한 별도 Astra read-only 검증 — **PASS 완료**
2. 리드의 source composition 로컬 인수 판단 — **SOURCE/SYNTHETIC ONLY 완료**
3. 진행 중인 actual JNJ의 별도 완료·독립 audit·리드 인수
4. accepted History를 부모로 한 first-five financial 실행·독립 검증·로컬 인수
5. first-five acceptance 뒤 later-45 History/financial과 exact-50 publication
6. final catalog/journal 보존 검증과 native UI/UAT

각 actual 단계에는 해당 계약의 config, preflight, request와 exact root GO가 별도로
필요하다. source merge, synthetic PASS 또는 현재 process 상태는 다음 actual gate를
자동 승인하지 않는다.

## source-only 검증과 한계

구현자 검증은 다음으로 제한한다.

- merged product/test bytes와 세 historical accepted checkout의 hash 비교
- bounded History/Fiscal/quarter serialization, recovery runner, quarterly/TTM,
  screening explicit-save/v3 reader의 기존 synthetic tests
- import/collection 전 actual `data`/`work`/corpus와 network 거부, nonexistent corpus
  sentinel, reviewed-Q4 flag unset
- main Python 3.12 venv, `POLARS_MAX_THREADS=2`, invocation당 단일 worker,
  process-tree RSS 1 GiB, timeout 120초, `RLIMIT_AS` 없음, parent-death/process-group cleanup
- 필수 cached-actual six node를 CLI에서 명시적으로 deselect
- `git diff --check`와 clean tracked state

actual Raw/History/financial/journal/catalog, SEC/network, live UI, scheduler, heavy lock과
진행 중인 actual run은 사용하지 않는다. 구현자 결과는 독립 검증이나 리드 인수를
대신하지 않는다.
