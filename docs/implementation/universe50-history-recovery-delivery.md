# 50사 History bounded-memory 복구 전달 계약 — 2026-10-17

## 결정과 상태

리드는 canonical financial source `fd9a17910a7b1cfbb4e71e2ded6f4bc23cda686e`와
runner ancestry 기준 `9b6e7ec906382fba92adb5209c5b439fc7d7d6ba`를 분리하고,
accepted `8a1b40ab1008fb9109a27b2a5bcea02a257e1694`에서
파생된 별도 bounded-memory History engine을 쓰는 복구 도구의 source/synthetic 구현만
승인했다. 원 계약은 로컬 기록
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_history_recovery_ops_contract.json`
(SHA-256 `79f211796d71ffe7cb720f295107e92a765f3cb551c9be6f36bd1bb9417a9fe0`)에
보존한다. 이 문서는 그 결정을 추적 가능한 제품 계약으로 승격한다.

| 단계 | 현재 상태 |
| --- | --- |
| source/synthetic 구현 | **IMPLEMENTED CANDIDATE** — 별도 독립 검증 전 |
| bounded-memory engine | prior `3a3d7d6…` r1은 TIMEOUT; 새 performance 후보 독립 검증·인수 대기 |
| actual JNJ 복구 | r1 **TIMEOUT**; 새 config·request·GO 전 retry 금지 |
| later-45 복구 | canonical financial source는 exact `fd9a179…`; actual financial은 **NOT_READY** |
| push·PR·main 병합 | 미수행 |

초기 engine 후보 `685185394993ba61493d82ca4b18f2f5464fe183`은 독립 검증에서
실패해 승인 HEAD로 사용하지 않는다. 새 engine 후보가 독립 equivalence PASS를 받고 리드가
아래 source acceptance를 작성하기 전에는 preflight도 유효하지 않다. 초기 source-only 구현과 이번 보정은 actual SEC/Raw/History payload, 실패한 JNJ partial,
완료 publication 또는 financial·metadata 발행을 실행하지 않았다. 이번 보정의 계약 확인은
actual old OPS 실패 summary/config/GO JSON 같은 운영 증거를 읽는 범위에 한정했다.
실제 데이터 payload의 재검증이나 actual retry 결과로 해석하지 않는다.

## 보존하는 경계

`tools/universe50_history_recovery_ops.py`는 기존 OPS source를 수정하지 않고 그 파일의
heavy lock, process-tree RSS 감시, parent-death guard와 owned process-group cleanup만
재사용한다. History 계산은 engine checkout의 공개 `history.build_history`를 호출한다.
collection 상태 전이는 변경하지 않은
`collection_operations._create_build_attestation`, `_validate_build_attestation`, public
`read_universe_status`와 `HistoryPublicationReader`로 확인한다. Raw parser, graph 규칙,
분기 계산, metric, UI, store 또는 회계 정책을 이 도구에 다시 구현하지 않는다.

runner checkout과 engine checkout은 별도다. runner는 clean exact HEAD, accepted financial
`9b6e7ec` ancestry, recovery 도구와 accepted resource OPS hash 및 import path를 확인한다.
engine은 clean exact HEAD, accepted `8a1b40a` ancestry, 아래 일곱 모듈의 exact hash와 실제
import path를 확인한다.

- `sec_xbrl.history`
- `sec_xbrl.analytics.fiscal_time_series`
- `sec_xbrl.analytics.company_analysis_panel`
- `sec_xbrl.collection_operations`
- `sec_xbrl.longitudinal.exploration_graph`
- `sec_xbrl.longitudinal.materialization`
- `sec_xbrl.analytics.history_quarters`

engine checkout에는 generic quality·identity·financial runner가 없을 수 있다. 실행 시
`PYTHONPATH=<engine>/src:<runner>` 순서를 사용하지만 recovery 도구와 resource OPS는 runner
checkout에서, `sec_xbrl` engine 모듈은 engine checkout에서 와야 한다. recovery/8a engine 프로세스는 `tools.universe50_financial_ops`를 import하지 않는다.
Later-45 gate 검증만 accepted first-five config가 선언한 clean exact `fd9a179` checkout의
별도 interpreter에서 수행한다. 이 프로세스는 canonical `_validate_shape`, `_verify_runtime`,
`_verify_output_receipt`, `_output_paths`, `_expected_publication_manifests`를 재사용한다.
Gate-only 결과는 FULL financial 실행 config가 아니며 future 45 회사의 History pin을 만들지 않는다.
validator도 Linux parent-death guard를 financial import 전에 설치하고 별도 owned process group,
16 GiB RSS, Polars 2, 60초 검증 timeout 및 interrupt/timeout cleanup을 적용한다.
실제 History worker의 timeout은 기존 10,800초를 보존한다. 주소 공간 제한은 사용하지 않는다.

## source acceptance와 입력 결속

리드는 새 engine source가 별도 독립 equivalence PASS를 마친 뒤에만 다음 exact schema를
작성한다. recovery 구현자나 runner는 이 artifact를 만들거나 승인하지 않는다.

```json
{
  "schema_version": "lead-history-engine-source-acceptance-v1",
  "status": "LOCALLY_ACCEPTED_HISTORY_ENGINE_SOURCE_AND_SYNTHETIC",
  "engine_source_head": "<40-hex-approved-engine-head>",
  "engine_base_sha": "8a1b40ab1008fb9109a27b2a5bcea02a257e1694",
  "graph_rule_version": "analysis-t3-exploration-graph-v2",
  "module_sha256s": {
    "history": "<64-hex>",
    "fiscal_time_series": "<64-hex>",
    "company_analysis_panel": "<64-hex>",
    "collection_operations": "<64-hex>",
    "exploration_graph": "<64-hex>",
    "longitudinal_materialization": "<64-hex>",
    "history_quarters": "<64-hex>"
  },
  "independent_report": {"path": "/absolute/report.json", "sha256": "<64-hex>"}
}
```

config는 immutable exact-50 collection e manifest와 candidate를 path/hash로 고정한다.
public status와 candidate가 동일한 50개 CIK/ticker, PEP 제외·KDP 포함, cutoff
`2026-10-10`, 정확히 1,097개 선택 filing인지 다시 확인한다. 선택 회사의 plan, complete
intake, filing count와 public state도 exact hash로 결속한다. 기존 READY marker, 기존 OPS receipt, 모든 run_version의 recovery receipt 및 이들의
partial 파일, 선택 destination 또는 승인되지 않은 build attempt가 있으면 거부한다.
collection의 legacy `execution/<ticker>/*.summary.json*`도 전수 대조한다.
새 history parent의 회사별 recovery/old OPS partial은 승인된 abandoned root만 허용한다.
새 History와 execution evidence는 failed tree·그 자손, collection/source checkout 또는
intake source run과 겹칠 수 없으며 symlink ancestor를 거부한다.

현재 실패 예외는 JNJ의 명시적으로 pin한 과거 failed attempts와 abandoned partial
roots다. native `operation_attempts/build-*`는 `result.status=BUILD_FAILED`와 정확한
`result.output_root`를 요구한다. 선언 abandoned roots는 모든 실패 root와 일대일로 같아야 한다.
old OPS56a의 RSS_LIMIT summary는 native attempt가 아니고 `output_root` 필드도 없다.
따라서 이 경우 public RAW_COMPLETE 상태를 보존하며 다음 확장 pin 형식이 필수다:

```json
{
  "path": "/absolute/old-collection/execution/JNJ/<attempt>.summary.json",
  "sha256": "<exact-summary-hash>",
  "legacy_ops": {
    "config": {"path": "/absolute/old-ops-config.json", "sha256": "<exact-config-hash>"},
    "go": {"path": "/absolute/old-build-JNJ-go.json", "sha256": "<exact-go-hash>"},
    "program": {"path": "/absolute/old-checkout/tools/universe50_t3v2_ops.py", "sha256": "5e4a249070e25359ec406c0c727bb0f919ffdd55624936f630e0325a41b3e4f9"}
  }
}
```

고정된 accepted56a program bytes, summary command의 exact config/ticker/GO,
old config의 collection/8a source/resource limits, GO가 pin한 `ops_preflight.json`과
그 program/engine digest를 대조한다. accepted56a destination 규칙
`history_root / "<ticker>-t3v2-<run_id>"`만 사용해 실패 root를 도출한다.
summary를 bare pin으로 보내거나 관련 없는 abandoned root를 보내면 거부한다.
collection universe_id는 opaque 값이다. 실제 e manifest는
`exact50-t3v2-exact50-t3v2-20261017-e`이며 directory basename에서 추정하지 않는다.
과거 root는 보존하며 새 `run_version`과
`JNJ-history-recovery-<run_version>` basename을 써야 한다. marker의 History 전체 출력 root와
consumer publication root는 구분한다. 예를 들어 publication manifest는 새 출력 아래
`panels/history_manifest.json`에 있으며 marker가 선언한 path/hash를 public reader가 확인한다.

first-five 범위는 `TXN, HD, JNJ, CVX, NEE`다. later-45 회복에는 financial `fd9a179`로
만든 canonical `universe50-first5-financial-acceptance-v1` artifact가 필수다. companies는
문자열이 아니라 정확한 CIK/ticker object여야 한다. runner는 exact collection/cutoff/source,
사용한 first-five config, stage receipt 전체 fileset, 다섯 회사 annual·quarterly analysis와
metadata·quality·identity·annual metrics·dataset v2·quarterly metrics·combined v3의 정확한
17개 publication manifest를 다시 연다. 각 stage receipt의 모든 output root는
canonical first-five config의 해당 stage root와 순서까지 같아야 하고, exact 17 manifest
list는 이름별 config root·파일명·hash와 같아야 한다. metadata mode가 EXISTING_PUBLICATION이면
metadata root/hash와 8개 stage receipt, PUBLISH_EXACT50이면 50 source snapshot 선언과 metadata를
포함한 9개 receipt가 필요하다. accepted metadata를 old five-company 경로로 고정하지 않는다.
과거 strings-only OPS gate는 호환 입력이 아니다.

## config, 승인 흐름과 실행 형식

아래는 config shape다. `<...>`는 실행 전에 실제 absolute path와 lowercase hash로 모두
치환한다. engine acceptance가 없는 동안 예시를 actual config로 사용하면 안 된다.

```json
{
  "schema_version": "universe50-history-recovery-config-v1",
  "financial_as_of": "2026-10-10",
  "first5": ["TXN", "HD", "JNJ", "CVX", "NEE"],
  "runner": {
    "checkout": "/absolute/clean/recovery-runner",
    "head": "<40-hex-final-recovery-head>",
    "module_sha256s": {"runner": "<64-hex>", "resource_ops": "<64-hex>"}
  },
  "engine": {
    "checkout": "/absolute/clean/approved-memory-engine",
    "head": "<40-hex-approved-engine-head>",
    "source_acceptance": {"path": "/absolute/lead-engine-acceptance.json", "sha256": "<64-hex>"}
  },
  "collection": {
    "manifest": "/absolute/exact50-e/collection_manifest.json",
    "manifest_sha256": "<64-hex>",
    "candidate": "/absolute/actual50-kdp-candidate.json",
    "candidate_sha256": "<64-hex>",
    "universe_id": "<exact-parent-universe-id>",
    "parent_company_count": 50,
    "selected_filings": 1097,
    "companies": [{"ticker": "AAPL", "cik": "0000320193"}]
  },
  "target": {
    "ticker": "JNJ",
    "cik": "0000200406",
    "plan_sha256": "<64-hex>",
    "intake_sha256": "<64-hex>",
    "selected_filings": 22,
    "run_version": "<new-approved-run-version>",
    "history_parent": "/absolute/new-history-parent",
    "history_basename": "JNJ-history-recovery-<new-approved-run-version>",
    "approved_prior_failed_attempts": [{"path": "/absolute/build-failed.json", "sha256": "<64-hex>"}],
    "abandoned_output_roots": ["/absolute/preserved-old-JNJ-partial"]
  },
  "execution_root": "/absolute/fresh-recovery-evidence",
  "resource_root": "/absolute/exact50-e",
  "limits": {
    "process_tree_rss_kib": 16777216,
    "polars_max_threads": 2,
    "one_heavy_process": true,
    "timeout_seconds": 10800
  },
  "first5_financial_acceptance": null
}
```

`companies` 예시는 한 행만 보였지만 실제 config에는 exact 50개가 필요하다. later-45 target은
마지막 필드를 `{"path":"/absolute/first5-acceptance.json","sha256":"<64-hex>"}`로
바꾼다. first-five target에는 그 artifact를 넣을 수 없다.

도구는 source-only preflight와 stage request까지만 만든다. root lead가 request를 검토한 뒤
`_expected_go`의 exact value와 같은 `universe50-history-recovery-go-v1` JSON을 별도 작성해야
한다. config, preflight, request, source HEAD, collection, target 또는 bulk proof가 바뀌면
GO는 무효다. 명령 형식은 다음과 같다.

```bash
PYTHONPATH=/absolute/engine/src:/absolute/runner \
  /absolute/runner/.venv/bin/python /absolute/runner/tools/universe50_history_recovery_ops.py \
  preflight --config /absolute/outside-execution-root/recovery-config.json

PYTHONPATH=/absolute/engine/src:/absolute/runner \
  /absolute/runner/.venv/bin/python /absolute/runner/tools/universe50_history_recovery_ops.py \
  request-stage --config /absolute/outside-execution-root/recovery-config.json

PYTHONPATH=/absolute/engine/src:/absolute/runner \
  /absolute/runner/.venv/bin/python /absolute/runner/tools/universe50_history_recovery_ops.py \
  run-stage --config /absolute/outside-execution-root/recovery-config.json \
  --go-file /absolute/root-authored-exact-go.json
```

worker 직접 호출은 금지되고 supervisor PID, one-shot pipe capability와 부모가 보유한 shared
heavy lock 없이는 실패한다. process-tree RSS 16 GiB, Polars thread 2, 10,800초 timeout은
고정이다. 실패, RSS 초과, timeout, interrupt 또는 parent death는 child process group을
종료·회수하고 immutable summary/partial output을 남긴다. 같은 execution root, destination,
marker 또는 receipt의 자동 retry와 덮어쓰기는 허용하지 않는다.

성공하면 새 marker를 통해 public state가 READY인지 확인한 뒤에만
`universe50-history-recovery-receipt-v1`을 쓴다. 이 receipt는 runner/engine source와 acceptance,
collection/plan/intake, root GO, 이전 실패와 abandoned root, marker/publication/history hash를
고정하며 기존 `ops_build_receipt.json`을 만들거나 흉내 내지 않는다.

## 검증과 남은 단계

구현자 검증은 synthetic exact-50/실패 JNJ fixture, canonical later-45 financial gate,
runner/engine 분리 import, request·GO mutation, 공개 History→marker→READY→typed receipt,
정상 guarded child, 직접 worker 거부, RSS/timeout, interrupt cleanup을 포함한다. actual cached
History 회귀와 actual JNJ build는 실행하지 않는다.

이 source 후보는 깨끗한 freeze 뒤 별도 읽기 전용 검증이 필요하다. 그 다음에도 새 engine의
독립 PASS와 lead source acceptance, 별도 actual recovery request, exact root GO가 모두 있어야
actual 한 회사 stage를 시작할 수 있다. source/synthetic PASS는 first-five 또는 exact-50
financial readiness, metadata 수락, actual History 성공이나 운영 반영을 뜻하지 않는다.


## 2026-10-17 독립 FAIL 후 좁은 보정

`26d1b8a318fd1651856cc09228b4171d54209b7c`는 canonical config-to-output 결속 누락,
과거 version receipt 누락, failure-to-abandoned root 불일치 및 descendant destination
허용으로 독립 FAIL했다. 리드는 위 R1–R4 보정과 real-public synthetic 증거에 한정해
구현 역할을 별도 Astra writer로 상향했다. 이전 writer는 정지했으며 독립 검증자는 계속
읽기 전용으로 분리된다. 승인 계약의 SHA-256은
`8b76a19f40dd05feaa20f5a2161135f788aa83897a136a8fcc48f0b3418e2df5`,
독립 FAIL 보고서는 `986171c7b76c11f44a0a9da87b1738be8d5bd109c6a2f271b332c35c5442e85e`다.

새 후보는 위 보정을 구현한 상태이며 별도 독립 검증·로컬 인수는 대기 중이다.
real-public test는 한 개 synthetic filing의 Raw table을 임시 경로에 작성하고 실제
History build/reader, 변경 없는 build attestation, public RAW_COMPLETE→READY 및 typed receipt를
실행한다. one-company fixture의 exact-50/source authorization snapshot만 대체했으며
이를 actual authorization으로 주장하지 않는다. synthetic Raw hash 보존과 nonempty cells를
확인한다. canonical validator는 실제 child의 parent death/RSS/timeout/interrupt cleanup도
별도 검사한다. synthetic source checkout은 test-local clone의 exact9b이며 actual metadata나
financial 산출물은 입력하지 않는다.

2026-10-17 테스트 범위 추가 정정은 lead 계약 SHA-256
`b36d68ef113573883b9a41c30e8aee176eb46e376a30d7af7ab7753f48610853`을 따른다.
`tests/unit`에도 actual cached corpus 테스트가 섞여 있으므로 plain full-unit 실행은
source/synthetic-only 검증 명령이 아니다. 이번 writer의 첫 broad run은 1,518 passed /
4 skipped 지점에서 중단했고 완료·수락 결과로 쓰지 않는다. 당시 interrupt는 recovery
resource monitor에서 발생했으며 뒤의 absolute-cache NVDA 테스트까지 진행하지 않았다.
두 번째 deselected run도 outer resource supervisor 보강을 위해 중단했다. 중단 로그는
보존하며 사후 actual 입력 byte-preservation 증거를 주장하지 않는다.

재현 조건은 다음과 같다.

- 실제 cache가 없는 지정 worktree에서 실행하고, 최종 독립 검증은 clean frozen SHA에서 수행한다.
- test import/collection 전에 `SEC_XBRL_CORPUS_ROOT`를 존재하지 않는 evidence sentinel로 설정하고
  `SEC_XBRL_RUN_REVIEWED_Q4_INTEGRATION`은 unset한다.
- 아래 6개 ID를 CLI에서 명시적으로 deselect한다. 기존 테스트를 숨기거나 제품 코드를 변경하지 않는다.
- collection 전에 actual data 파일 open을 거부하는 외부 guard를 설치한다. absolute/relative/symlink
  alias 및 `os.open(..., dir_fd=...)` negative control과 owned output dir-fd positive control을 수행한다.
  허용 evidence 경로의 strict ancestor는 O_DIRECTORY/순회 metadata만 허용한다.
  native library I/O를 Python audit hook만으로 보편적으로 차단한다고 주장하지 않는다.
- 단일 owned worker에 sampled process-tree RSS 16 GiB, Polars 2, 주소 공간 제한 없음,
  timeout·interrupt·parent-death cleanup을 적용하고 실제 peak/exit/reaped 상태를 기록한다.
  첫 unexpected denial에서는 중단한다. 전체 source/synthetic 결과에서 deselected와 skipped를 구분한다.

필수 deselection ID:

```text
tests/unit/test_corpus_release.py::test_actual_seven_company_corpus_is_admitted_when_cached
tests/unit/test_c3_as_filed_publication.py::test_c3_m1_actual_seven_company_corpus_when_cached
tests/unit/test_c3_as_filed_publication.py::test_cached_nvda_fy2024_q1_revenue_selects_direct_10q_when_available
tests/unit/test_versioned_observation_panel.py::test_cached_nvda_fy2024_q3_revenue_is_directly_retrievable
tests/unit/test_reviewed_q4.py::test_cached_nvda_source_to_api_snapshot_xlsx
tests/screening/test_screening_explorer.py::test_actual_r3_projection_matches_frozen_observations_when_available
```

위 guard 아래 Python 의존성을 설치한 환경에서 `POLARS_MAX_THREADS=2`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src:.`와 각각의 `--deselect=<ID>`를 지정해
`python -m pytest tests/unit -q -x -p no:cacheprovider --basetemp=<fresh-owned-tmp>`를 실행한다.
`ruff check --no-cache tools/universe50_history_recovery_ops.py tests/unit/test_universe50_history_recovery_ops.py`
및 `git diff --check`도 필요하다. actual cached integration 또는 actual recovery 명령은 포함하지 않는다.
이 후보의 frozen SHA·writer 결과는 별도 증거 보고서에 기록하며 final acceptance를 대신하지 않는다.

## 2026-10-17 r1 TIMEOUT 결속과 canonical financial gate 보정

승인 계약
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_history_recovery_retry_and_ttm_gate_contract.json`
(SHA-256 `b1be9c79db42ef9069586200d6278d9977e9029852728efa43c877ac22a4a33d`)은
두 가지 source/synthetic 변경만 허용한다. runner ancestry 기준은 `9b6e7ec…`로 보존하되
later-45 canonical financial source를 독립 PASS·리드 인수를 받은 exact
`fd9a17910a7b1cfbb4e71e2ded6f4bc23cda686e`로 갱신한다. 기존 full canonical validator,
stage receipt 전체 fileset, 17개 publication manifest 및 first-five 범위는 바꾸지 않는다.
해당 source/synthetic 리드 인수 artifact SHA-256은
`c1113e7423b4f4a73155299af44302d49ffb81a730fd21ebfffd9f495fdea861`이다.

JNJ recovery r1은 reported 12개 table 완료 뒤 quarter 단계에서 10,800초 TIMEOUT으로
종료됐다. 이는 성공이나 native `BUILD_FAILED`가 아니다. 새 `recovery_ops` 선언은 다음
immutable 운영 증거를 exact hash로 결속한다.

- accepted a02 clean runner HEAD/tree와 recovery/resource program
- lead a02 source acceptance 및 그 writer/independent/contract pins
- prior config, preflight, request, root GO와 TIMEOUT summary
- config가 고정한 collection, 회사·CIK, plan, intake, filing count, cutoff와 resource limits
- prior engine acceptance, independent report, clean HEAD와 일곱 module hashes
- summary의 exact execution location, worker command, nonzero return code, 10,800초 timeout,
  16 GiB cap, log와 RSS sample 위치

고정된 r1 증거 SHA-256은 config `00f61854cf8a0a84c7ed11d11d07005d16216f56a7d10c3e9524f70645952542`,
preflight `aa779aa51cd14dd78bc179412571f3c1bbd1aa5a8575a316269a5f6d605b7f4a`,
request `8206a0a01dcf813e1cfdfe8f9a657a88b591fe34313027851e7b3c2cb6fb15da`,
GO `5c410067c12fbf49b69809b86a76034063c5312e21a861732ddd306ddf204c21`,
TIMEOUT summary `0c07d38130312434acdcfc40cb87cd66c1c6d0774211884948a5620b9e5ae574`다.
accepted a02 source artifact SHA-256은
`8487366d30a29d2d8f225e911ab91f50fb962dbacce07f1edcf71dd168a5a331`이다.

과거 실패 History root는 prior config의 `history_parent/history_basename`에서만 도출한다.
현재 config의 실패 선언과 abandoned root는 old OPS56a와 r1 두 건을 일대일로 모두 포함해야
한다. hash가 바뀐 증거, foreign target, success/running summary, 누락·중복 root, 승인되지 않은
추가 summary, prior execution/source/engine과 겹치는 새 destination 또는 execution root는
거부한다. r1 log와 RSS sample은 summary와 함께 보존하며 JSON failure-summary 전수 검사는
이 부속 파일을 새 attempt로 오인하지 않는다.

이 보정은 retry를 실행하지 않고 새 recovery mode도 추가하지 않는다. r1의 reported staged
산출물을 재사용하는 공개 경로는 별도 계약과 독립 staged attestation 없이는 선택하지 않는다.
후속 actual 실행에는 새 performance engine의 독립 PASS·리드 인수, fresh output run version,
새 config·preflight·request와 별도 root GO가 모두 필요하다. source/synthetic 검증은 actual
Raw, History, publication 또는 cached corpus를 열지 않으며 actual 16 GiB 성공을 주장하지 않는다.

### f74 독립 FAIL과 complete-failure 보정

후보 `f74defdb1947dfead8b9579c6432f5465a1e2931`은 r1 `recovery_ops` 선언과 그
abandoned root를 함께 제거하면 남은 legacy56a 선언만으로 검증을 통과해 독립 FAIL했다.
일대일 비교가 호출자가 제시한 두 목록만 비교했고, r1 execution과 History root가 새
`history_parent` 밖에 있어 orphan 탐색에도 잡히지 않은 것이 원인이다. 독립 보고서 SHA-256은
`b451d3856b05d74ddb58df40e9fa8459193214478b2f4936670d211962910e96`, 좁은 보정 계약
SHA-256은 `dfa4d96413bfa72aef239001af39b94561732cd3e363315e332ceec694534483`다.

이 post-r1 runner의 JNJ config에서 old OPS56a `legacy_ops`가 선언되면 exact accepted a02 r1
`recovery_ops`가 정확히 한 건 있어야 한다. 0건과 복제 선언은 config shape에서 거부하며,
한 건을 외국 summary/source/GO/program으로 바꾸면 기존 exact r1 결속에서 거부한다.
actual collection의 legacy summary 전수 검사는 그대로 유지되므로 legacy56a 선언까지 함께
빼는 경우도 undeclared legacy attempt로 실패한다. 이 둘을 합쳐 현재 JNJ 재시도에는
legacy56a와 r1 TIMEOUT 두 실패와 두 root가 모두 필요하다. legacy-only JNJ post-r1 config는
유효하지 않다.

accepted a02 r1의 과거 config는 자기 실행 전 상태이므로 이 후속 gate 대상이 아니다. 이를
통해 그 config/preflight/request/GO를 검증하면서 과거 의미를 소급 변경하지 않는다. 다른 회사,
native/legacy witness의 개별 형식 검증, 회계·Raw·engine·fd9 canonical fileset 및 lifecycle
정책은 바꾸지 않는다. 이 보정도 source/synthetic 전용이며 새 actual retry 권한이 아니다.
