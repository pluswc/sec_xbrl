# 재무 producer 단일 source 검증 pass 전달 — 2026-10-18

## 결정과 현재 상태

이 문서는 generic metric identity producer의 동일 deep source 검증 3회를 1회로,
combined dataset v3 producer의 동일 annual parent deep 검증 2회를 1회로 줄인 source 구현
후보를 기록한다. 설계 승인 근거는 로컬 설계 계약
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_financial_single_pass_producer_design_contract.json`
(SHA-256 `8bcf066f1cc694c98532e56d422c29c3b1c8b0d8757f7e8e73f1ae2b82291af4`), 구현 승인은
`lead_financial_single_pass_producer_implementation_contract.json`
(SHA-256 `58875e2f4ebb394120523b13517630502f2a5874093d1cf676cbb6dffad86d1a`), quarterly
adapter 보정 승인은 `lead_financial_quarterly_spine_adapter_correction_addendum.json`
(SHA-256 `6b8fd77ff57366cdb75354ef4bb3e707c50b95bf2465f552d87bc25bd9a11b93`)이다.

| 단계 | 상태 |
| --- | --- |
| 문제·최소 방향 결정 | **APPROVED** — identity 3→1, combined v3 2→1 |
| 이 문서의 상태 | **IMPLEMENTED_SOURCE_CANDIDATE / INDEPENDENT_REVIEW_REQUIRED** |
| 기준 source | `02226c91f36b5907f9e4d701c2b788747ef94c0a` |
| product·test 구현 | **COMPLETE IN LOCAL CANDIDATE** — exact frozen SHA/tree는 owned evidence report에 기록 |
| actual first-five R3·FULL50 | **NOT_STARTED / NOT_READY** |
| 독립 검증·로컬 인수·main 병합 | 미수행; source 후보는 아직 미수락·미병합 |

이 변경은 source 폐쇄성, byte 검증, 회계·기간·선택 규칙을 줄이는 성능 shortcut이 아니다.
한 producer invocation 안에서 성공한 deep 검증 결과를 private capability로 결속하고,
발행 직전에 같은 전체 source path set을 다시 hash하여 중복 deep decode만 제거한다. 현재
actual R2는 stage 7 quarterly config spine 불일치로 receipt 없이 종료됐고 앞선 6 PASS는
역사 증거로만 남는다. 이 구현은 actual 산출물을 읽거나 R2를 재시도·재라벨하지 않는다.

## 현재 중복과 승인된 경계

`publish_generic_metric_identity`는 먼저 `_verify_configured_sources`를 직접 실행한 뒤
staging reader를 만든다(`screening/metric_identity.py:62-94`). reader 생성자는
`verify_all`을 호출하고(`:104-135`), 호출자는 다시 `verify_all`을 호출하며, 각 호출은
`_verify_configured_sources`를 다시 실행한다(`:137-176`). 따라서 producer 한 번에 같은
governed source를 세 번 deep 검증한다.

`publish_screening_dataset_v3`는 annual `ScreeningDatasetV2Reader`를 한 번 열어 parent를
검증한 뒤 staging `ScreeningDatasetV3Reader`를 생성한다
(`screening/dataset_v3.py:27-89`). v3 reader 생성자는 같은 annual v2 reader를 다시
열어 deep generic identity까지 재검증한다(`:93-164`). 따라서 v3 producer의 annual
parent deep 검증은 두 번이다.

승인된 구현은 아래 둘뿐이다.

1. identity producer는 deep `_verify_configured_sources`를 정확히 한 번 실행하고, 그 결과와
   전체 source closure를 private capability에 결속한다. staging publication은 동일한 public
   검증 규칙을 private finalizer가 적용한다.
2. combined v3 producer는 처음 연 annual v2와 quarterly parent 검증을 정확히 한 번 유지하고,
   전체 transitive parent closure를 private capability에 결속한다. staging v3는 private
   finalizer가 public reader와 같은 구조·identity·row binding을 검사한다.

annual metrics, annual dataset v2, quarterly metrics, quality producer, ordinary public readers와
명시적 `verify_all()`의 pass 수와 동작은 바꾸지 않는다. H5 audit의 bounded worker 분할과
audit harness의 즉시 중복 v2 호출 제거는 별도 계약이다. first-five strict same-source gate도
바꾸지 않는다.

## source closure의 표현

새 private helper `screening/verified_source_closure.py`는 directory path 하나를 신뢰 근거로
쓰지 않는다. 각 dependency를 다음 immutable role record로 표현한다.

- regular file: canonical absolute path, semantic role, SHA-256, byte size, device/inode와
  `mtime_ns`/`ctime_ns`
- ZIP member: archive의 regular-file record, normalized member name, uncompressed byte size와
  member SHA-256
- exact publication inventory: root의 정규화된 상대 파일·디렉터리 이름과 type을 정렬한
  inventory digest. 파일 hash를 대신하지 않고 missing/extra entry를 검출한다.
- recovery readiness inventory: History root에서 기존 gate가 선택하는 각 ancestor까지 발견한
  `.history-recovery-*`, `.receipt.partial-*`, `reported_recovery_receipt.json`의
  exact name/type set과, 존재할 때 선택된 control directory 파일, final/partial receipt 및
  reported/consumer manifest의 개별 record. parent 전체를 재귀 hash하지 않는다.
  `_check_recovery_access`의 기존 marker 선택·우선순위·READY 판정을 private hash보다 먼저
  실행하며 새 ancestor criterion을 추가하지 않는다. COMPLETE receipt와 보존된
  `.receipt.partial-*`가 같은 inode인 정상 hard-link도 허용한다.

`..`, symlink component, non-regular expected file, path containment 위반은 snapshot 전에
실패한다. 동일 `(canonical path, role)`의 중복 선언은 실패한다. 하나의 물리 파일이
collection manifest이면서 quality evidence처럼 서로 다른 역할을 가질 때만 명시된 role set을
한 번 hash한다. 정상 recovery receipt hard-link처럼 기존 public gate가 허용한 물리 alias를
별도 private 정책으로 거부하지 않는다. 같은 경로의 서로 다른 선언 hash, duplicate
CIK/accession/document identity와 stale role은 실패한다.

Raw와 History root는 편의상 directory digest 하나로 대체하지 않는다. History의 manifest와
모든 declared public data file을 각각 hash한다. configured History root 안에 기존 public reader가
허용하는 retained manifest partial, spill record, chunk가 있으면 이들은
`RETAINED_PHYSICAL:<relative path>` 역할로 각각 hash하고 exact physical inventory에도 넣는다.
이 역할은 byte/path freshness 증거이며 추가 재무 의미 parent가 아니다. configured root 밖의
과거 failed sibling publication이나 선택되지 않은 History root는 재귀적으로 포함하지 않는다.
Raw source-binding dependency는 각 filing마다
`layer1_manifest.json`, `fact.parquet`, `concept.parquet`, `context.parquet`를 각각 hash한다. 해당
Raw snapshot에 존재하지만 현재 source-binding 의미 검증이 참조하지 않는 다른 table은 trusted
closure에 넣지 않는다. 반대로 source-binding document가 선언한 세 table 중 하나라도 빠지거나
추가 role을 선언하면 실패한다.

## identity producer의 완전한 file-role closure

closure planner는 normalized identity config와 manifest bytes에서 아래 집합을 만든다. 각
cardinality와 회사·filing identity를 config/collection/quality/source-binding 사이에서 다시
대조한다.

| role | exact 입력과 검증 |
| --- | --- |
| `IDENTITY_CONFIG` | producer가 받은 config file 한 개. bytes의 SHA/size와 `_validate_config` 결과 digest를 결속 |
| `COLLECTION_MANIFEST`, `COLLECTION_REQUEST` | fixed `collection_manifest.json`과 그 manifest가 exact fixed path/hash로 가리키는 `collection_request.json` |
| `COLLECTION_PLAN`, `COLLECTION_PLAN_IDENTITY` | parent collection의 **모든** company row에 대한 fixed `companies/<ticker>/plan.json`, `plan_identity.json`; parent membership/status 계산에 필요한 범위이므로 subset 밖 45사도 포함 |
| `COLLECTION_STATUS_INTAKE`, `COLLECTION_STATUS_BUILD`, `COLLECTION_STATUS_ATTEMPT`, `STATUS_HISTORY` | `read_universe_status`가 실제 읽는 회사별 `intake/history_intake.json`, 존재하는 `build_manifest.json`, 그리고 `_latest_failed_attempt`가 glob으로 읽는 `operation_attempts/{collect,build}-*.json`의 exact inventory/bytes. present build가 READY이면 scoped 밖 회사도 build가 선언한 exact History manifest/data를 status-only 역할로 hash한다. 이는 financial cohort claim이 아니라 parent status 계산 dependency다 |
| `METADATA_MANIFEST`, `METADATA_DATASET` | `company_metadata_manifest.json`과 manifest가 정확히 선언하는 모든 metadata Parquet. root exact inventory도 함께 고정 |
| `SCOPED_BUILD`, `SCOPED_INTAKE` | config의 각 scoped 회사 build marker와 그 marker의 exact intake. 위 status role과 겹치는 물리 file은 distinct allowed role로 한 번 hash |
| `HISTORY_MANIFEST`, `HISTORY_PUBLIC_DATA`, `HISTORY_RETAINED_PHYSICAL` | scoped 회사별 `history_manifest.json`, 각 table의 `columns`/`rows`/`cells`, 존재하는 `derived_quarter`; manifest declaration과 build `declared_files`의 exact equality. configured root 안의 public-reader-admissible retained spill/private file은 별도 freshness role로 hash하며 회계 source role로 승격하지 않음 |
| `HISTORY_RECOVERY_GATE` | 각 History root의 ordinary-negative 또는 completed-recovery gate inventory. control이 있으면 현재 `_check_recovery_access`/`_validate_recovery_gate`가 읽는 single control directory, receipt, attestation, verification report, source log, reported/consumer manifests와 gate-declared files 전부 |
| `ANNUAL_ANALYSIS_MANIFEST`, `ANNUAL_ANALYSIS_DATA` | scoped 회사별 annual `analysis_manifest.json`과 manifest에 선언된 모든 view file; root exact inventory, `ANNUAL`, input/display FY와 exact History parent |
| `QUARTER_ANALYSIS_MANIFEST`, `QUARTER_ANALYSIS_DATA` | scoped 회사별 quarterly `analysis_manifest.json`과 모든 declared view file; root exact inventory, `QUARTERLY`, cutoff/spine/rule와 exact History parent |
| `QUALITY_MANIFEST`, `QUALITY_REPORT` | exact `generic_metric_quality_manifest.json` 및 유일한 declared conformance report; quality root exact two-file inventory |
| `QUALITY_EVIDENCE` | manifest `evidence_hashes`의 config, collection manifest/request, History manifests, build manifests, source-binding manifest/documents/records, duration index, correction index. expected key set과 scoped ticker set이 exact해야 함 |
| `SOURCE_BINDING_MANIFEST`, `SOURCE_BINDING_DOCUMENTS`, `SOURCE_BINDING_RECORDS` | v2 root의 exact three-file inventory와 각 declared hash/size |
| `DURATION_SOURCE_INDEX`, `CORRECTION_SOURCE_INDEX` | source-binding `candidate_inputs`의 정확히 두 index; path/hash와 filing scope exact |
| `FILING_PACKAGE_ZIP`, `FILING_PRIMARY_MEMBER` | source-binding document마다 exact package ZIP regular file과 collection plan의 normalized primary member bytes; package/member SHA와 CIK/accession/document identity exact |
| `RAW_MANIFEST`, `RAW_FACT`, `RAW_CONCEPT`, `RAW_CONTEXT` | filing마다 exact `layer1_manifest.json`과 세 declared Parquet; package hash, parser profile, CIK/accession 및 source-binding documents/table declaration과 exact equality |
| `VERIFIER_SOURCE_CODE` | loaded source files that define the verification path: helper, identity producer, collection operations, company metadata, History, analysis reader, quality, source bindings and shared screening path/hash helpers. path/SHA set은 capability에 고정 |

`read_universe_status`는 request, 모든 collection company plan/plan identity, intake, build와
실패-attempt 상태를 사용한다(`collection_operations.py:475-549`, `:1185-1279`). 따라서
`EXPLICIT_SUBSET`이어도 parent status 계산에 실제로 읽힌 control을 closure에서 빼지 않는다.
History reader는 생성·각 read·`verify_all`마다 recovery gate를 확인한다
(`history.py:891-975`, `:1419-1439`). recovery marker를 단순히 history manifest hash로
대체할 수 없다.

quality `verify_sources`는 evidence files, collection readiness, History, source-binding과 report
replay를 다시 수행한다(`metric_quality.py:566-676`). source-binding v2는 exact two candidate
indexes, collection request/scope, each ZIP/primary member, Raw manifest와 Fact/Concept/Context를
검증한다(`source_bindings.py:977-1089`). 이 전이 입력을 모두 role closure에 포함해야
`_verify_configured_sources` 한 번의 의미를 보존한다.

## combined v3 producer의 완전한 file-role closure

v3 closure는 처음 성공한 annual v2 및 quarterly reader가 읽은 아래 path set을 고정한다.

- v3 config (`V3_CONFIG`)와 normalized config digest
- annual v2 publication manifest와 exact declared output JSON files
  (`ANNUAL_V2_MANIFEST`, `ANNUAL_V2_OUTPUT`), v2 source config
- annual metrics manifest와 exact declared definitions/support/observations files
  (`ANNUAL_METRIC_MANIFEST`, `ANNUAL_METRIC_OUTPUT`)
- annual v2가 명시적으로 연 generic identity manifest와 위 identity transitive closure 전체.
  legacy identity kind를 새 optimization 대상으로 승격하지 않으며 기존 public 경로를 유지한다.
- v2가 `_identity_rows`에서 다시 여는 metadata manifest와 모든 metadata Parquet
- quarterly metric manifest, exact four declared files(definitions/support/observations/period
  inventory), quarterly config와 quarterly manifest가 고정한 annual metric 및 generic identity
  declarations
- 각 parent root의 exact publication inventory와 verifier source-code set(helper, dataset v3,
  dataset v2, dataset dispatch, annual/quarter metric readers, generic identity와 그 transitive
  verifier modules)

v3 planner는 annual v2 source declaration, annual metric identity declaration, quarterly
`annual_parent` 및 generic identity declaration이 같은 publication ID/root/manifest SHA와 같은
company membership/cutoff를 가리키는지 대조한다. annual/quarter parent의 missing/extra output,
foreign identity, duplicate company/metric/period key, wrong role 또는 stale source declaration은
capability 발급 전에 실패한다.

## snapshot, deep verify, capability, finalization 순서

### 1. discovery와 초기 snapshot

planner는 manifest를 따라 candidate roles를 발견하되, 발견 중 읽은 각 control file의 bytes와
stat identity를 즉시 보존한다. complete candidate set을 만든 다음 모든 regular file/ZIP member를
no-follow open으로 hash하여 정렬된 `initial_snapshot`을 만든다. 이어서 **그 snapshot에 보존한
manifest/control bytes만으로** closure를 두 번째로 재구성한다. 두 path-role set, hash, size,
scope 및 inventories가 exact하지 않으면 deep verifier를 호출하지 않는다. 이 단계가 discovery
도중 manifest 교체로 더 작거나 다른 closure가 승인되는 것을 막는다.

각 file read는 open 전 path component no-symlink 검사, `O_NOFOLLOW` open, open FD `fstat`, full
read/hash, read 후 `fstat`, 현재 path의 device/inode 재대조를 거친다. changed/disappeared/replaced
file은 실패한다. 전체 snapshot 뒤 directory/recovery inventories도 다시 대조한다.

### 2. 실제 deep verify와 issue 전 freshness

identity는 기존 `_verify_configured_sources(config)`를 정확히 한 번 호출한다. v3는 기존 public
annual v2 reader와 quarterly reader를 각각 정확히 한 번 열어 현재 semantic/row 검증을 그대로
수행한다. helper의 private operation-specific entry point가 lazy import로 이 exact verifier와
reader class를 직접 선택하고 호출한다. caller가 임의 callback, boolean 또는 이미 만든 source
payload를 verifier 대용으로 전달하는 API는 두지 않는다. helper는 실제 호출의 성공 return을
normalized expected-source payload로 받고 `initial_snapshot`의 config/scope와 exact equality를
검사한다.

그 뒤 entire closure를 같은 방식으로 다시 hash한 `post_verify_snapshot`이 initial과 byte-for-byte
같아야 한다. directory/recovery inventory와 ZIP member도 다시 검사한다. 같을 때만 capability를
발급한다. deep verifier exception, incomplete consumption 또는 changed byte는 capability를 만들지
않는다.

### 3. private capability

`_VerifiedSourceClosure`는 public API에 export하지 않는 `__slots__` class다. constructor는
module-private issuer sentinel을 요구하고, helper의 operation-specific real-verifier entry point만
registry record를 만들 수 있다. helper의 live in-process registry에 있는 256-bit random nonce
없이는 finalizer가 받을 수 없다. 다음 값을 immutable하게 결속한다.

- issuing PID와 producer invocation nonce
- operation kind(`IDENTITY_PUBLISH` 또는 `COMBINED_V3_PUBLISH`)
- normalized config와 digest
- expected source payload와 digest
- initial/post-verify closure records와 aggregate digest
- exact verifier source-code path/SHA set
- staged destination과 expected publication schema/rules/cohort
- state `ISSUED`, expiry가 아닌 단일 invocation ownership

`__reduce__`, `__reduce_ex__`, `__copy__`, `__deepcopy__`는 `TypeError`를 내고 bytes/JSON/token
serialization API를 제공하지 않는다. registry는 PID 변경, unknown nonce, operation/config/source
code mismatch, already consumed/finalizing capability를 거부한다. Python naming privacy만 신뢰하지
않고 object identity와 registry membership을 검사한다. `skip_verify`, caller-supplied receipt,
deserialization 또는 cross-process reuse 경로는 없다.

### 4. private staged finalizer와 atomic publish

identity finalizer는 fresh staging manifest bytes에서 public `verify_all`과 같은 조건을 직접
검사한다: exact one-file inventory, schema/source kind/readiness, normalized config path/hash/value,
top scope, expected source payload, publication ID. v3 finalizer는 exact one-file staging inventory,
config path/hash/value, annual/quarter root/hash/publication ID, `_verify_parent_binding`, company/metric/
quarter rows와 counts, cutoff, dataset ID, version vector, metadata source, publication ID를 fresh
bytes와 이미 deep-verified parent objects에서 다시 계산한다. staging writer가 만든 in-memory
manifest만 신뢰하지 않는다.

staged shape가 통과한 뒤 finalizer는 entire source closure를 세 번째로 rehash하고 initial과 exact
비교한다. 이 final rehash 이후 다른 source read 없이 capability를 `FINALIZING`으로 단일 소비한
다음 즉시 existing atomic replace를 호출한다. rename 성공 시 registry에서 제거하고 `CONSUMED`,
rename 실패 시에도 `INVALID`로 제거하여 재사용하지 못하게 한다. destination/staging mismatch나
output byte 변경도 실패한다.

producer-private finalizer는 ordinary public constructor나 `verify_all()`을 바꾸지 않는다. 발행
후 새 public reader를 열면 기존처럼 모든 source를 fresh deep 검증하며, 이후 외부 source byte
변조를 잡는다.

## 보존되는 결과와 differential 기준

같은 immutable 입력에 대해 다음 값은 기존 producer와 byte-for-byte 같아야 한다.

- manifest schema와 exact file set
- dataset/publication/source IDs와 version vectors
- company, metadata, metric definition/support/observation, quarter inventory rows와 ordering
- annual/quarter scope, fiscal rules, source selection, reported/derived 구분, unavailable와 manual Q4
- quality assurance scope, parser profiles, source hashes와 provenance payload

기존 코드가 이미 random staging directory UUID를 쓰는 경우 그 temporary path 이름만 비교에서
제외한다. committed publication manifest에 nondeterministic UUID가 없다면 어떤 output byte도
제외하지 않는다. 성능 추정치는 FULL50 실측이 아니다. 기존 first-five metadata에서 계산한
선형 민감도는 구현 우선순위 근거일 뿐 완료·시간 보증으로 쓰지 않는다.

## 구현 file closure와 quarterly adapter 보정

single-pass product 변경은 정확히 다음 세 파일이다.

- `src/sec_xbrl/screening/metric_identity.py`
- `src/sec_xbrl/screening/dataset_v3.py`
- 새 `src/sec_xbrl/screening/verified_source_closure.py`

추가 product helper 수정은 없다. collection/History/quality/source-binding/dataset v2의
public API를 바꾸지 않고 helper가 기존 manifest schema를 따라 closure를 계획하며, 두 producer만
private finalizer를 호출한다.

actual R2 stage 7은 runner가 identity용 2-field `global_quarter_spine`을 quarterly producer에도
그대로 전달해 기존 quarterly validator의 `status=COMPLETED_BUCKET` exact contract에서 발행 전에
실패했다. 추가 승인에 따라 `tools/universe50_financial_ops.py`는 identity의 기존 helper와 schema를
유지하고 quarterly config에서만 같은 8 bucket 각각에 `COMPLETED_BUCKET`을 붙인다. bucket 수·날짜,
cutoff, quarterly producer validator·math·reader는 바꾸지 않았다. 이 수리는 과거 R2 receipt를
만들거나 재시도하지 않으며 새 R3의 fresh 8-stage 실행에만 적용된다.

targeted tests는 기존
`tests/screening/test_generic_metric_identity_contract.py`,
`tests/screening/test_generic_metric_identity_integration.py`,
`tests/screening/test_screening_quarterly_consumer.py`,
`tests/unit/test_universe50_financial_ops.py`에 붙였고 helper 자체 matrix는 새
`tests/screening/test_verified_source_closure.py`에 둔다.

## source/tiny 검증 결과와 남은 수락

| 범주 | 필수 증명 |
| --- | --- |
| pass count | guarded integration에서 identity invocation deep verifier 1회, v3 annual v2/generic deep path 1회 확인; public reader reopen은 별도 fresh pass 유지 |
| closure completeness | 위 모든 role/cardinality/path가 captured; manifest/control discovery 전후 path-role set exact |
| path safety | absolute containment, traversal, symlink component, file exchange, non-regular, missing/extra/duplicate/wrong-role 거부 |
| scope safety | foreign/stale CIK·ticker·accession, subset/parent 혼합, build/intake/history/analysis/quality/source-binding mismatch 거부 |
| recovery | ordinary negative gate와 completed recovery READY gate 모두 성공; marker/receipt/partial/control/evidence 변조 거부 |
| Raw/ZIP | archive byte, primary member, Raw manifest 및 Fact/Concept/Context 각각 변조·교체·missing 거부 |
| timing windows | discovery 중, deep verify 직후, staged write 뒤/final rehash 직전 mutation 각각 거부; capability 미발급 또는 invalidation |
| capability | construction/forgery/copy/pickle/cross-process/replay/wrong producer/wrong destination/second consume 거부 |
| staged output | extra/missing/output mutation, source payload, publication ID, cohort/rule/version mismatch 거부 |
| differential | identity old formula oracle와 새 publication bytes exact equality 확인; v3 public reopen과 publication ID/parent payload regression 통과 |
| public regression | public constructor와 explicit `verify_all()`가 발행 후 source mutation을 계속 검출 |
| unchanged producers | annual metrics/v2/quarter producer와 quality pass count·output unchanged |

검증 worker는 worker당 RSS 1 GiB 이하와 120초 이내, parent-death signal 및 자식 reaping을
사용하고 `RLIMIT_AS`를 쓰지 않았다. test process는 `sec_xbrl` import 전에 actual/cache root와
network 접근을 차단하고 positive denial probe를 통과했다. 최종 source 후보에서 실행한 묶음은
generic identity/closure 46 PASS(peak 160,411,648 bytes), quarterly producer/consumer 63 PASS
(107,659,264 bytes), financial runner 27 PASS(92,504,064 bytes)다. recovery synthetic에는 governed
manifest/data 밖 retained physical file 8개(6 chunk, 1 quarter-spill record, 1 manifest partial)가
있었고 모두 별도 byte-freshness role로 hash됐다. actual payload, actual hash walk, network 또는 C
lock은 사용하지 않았다. 독립 Astra 검증과 lead local acceptance는 아직 남아 있다.

## source 변경 뒤 actual gate

구현이 source HEAD 또는 pinned module hash를 바꾸므로 existing first-five R2 acceptance를 새
source의 증거로 재사용하거나 이름만 바꿀 수 없다. strict `new source == accepted first-five source`
gate는 그대로 둔다. 독립 source/synthetic PASS와 lead local acceptance 뒤에도, 새 source로
first-five R3의 원래 8 stage receipts와 17 publication manifests를 다시 생성·검증하고 actual
audit를 통과해야 FULL50가 가능하다. 이 설계나 향후 single-pass 구현만으로 actual50 readiness,
duration 또는 acceptance를 주장하지 않는다.

