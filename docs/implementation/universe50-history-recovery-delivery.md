# 50사 History bounded-memory 복구 전달 계약 — 2026-10-17

## 결정과 상태

리드는 accepted financial source `9b6e7ec906382fba92adb5209c5b439fc7d7d6ba`를
runner 기준으로 두고, accepted `8a1b40ab1008fb9109a27b2a5bcea02a257e1694`에서
파생된 별도 bounded-memory History engine을 쓰는 복구 도구의 source/synthetic 구현만
승인했다. 원 계약은 로컬 기록
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_history_recovery_ops_contract.json`
(SHA-256 `79f211796d71ffe7cb720f295107e92a765f3cb551c9be6f36bd1bb9417a9fe0`)에
보존한다. 이 문서는 그 결정을 추적 가능한 제품 계약으로 승격한다.

| 단계 | 현재 상태 |
| --- | --- |
| source/synthetic 구현 | **IMPLEMENTED CANDIDATE** — 별도 독립 검증 전 |
| bounded-memory engine | **NOT_ACCEPTED** — 정확한 새 HEAD와 root acceptance artifact 미정 |
| actual JNJ 복구 | **NOT_STARTED / 금지** |
| later-45 복구 | first-five canonical financial acceptance 전 **NOT_READY** |
| push·PR·main 병합 | 미수행 |

초기 engine 후보 `685185394993ba61493d82ca4b18f2f5464fe183`은 독립 검증에서
실패해 승인 HEAD로 사용하지 않는다. 새 engine 후보가 독립 equivalence PASS를 받고 리드가
아래 source acceptance를 작성하기 전에는 preflight도 유효하지 않다. 이 구현은 실제 SEC
payload, 실패한 JNJ partial, 완료된 네 회사 publication, metadata 또는 financial output을
읽거나 실행하지 않았다.

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
checkout에서, `sec_xbrl` engine 모듈은 engine checkout에서 와야 한다. recovery 도구는
`tools.universe50_financial_ops`를 import하지 않는다.

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
intake, filing count와 public state도 exact hash로 결속한다. 기존 READY marker, 기존 OPS
receipt, recovery receipt, 선택 destination 또는 승인되지 않은 build attempt가 있으면
거부한다.

유일한 현재 실패 예외는 JNJ의 명시적으로 pin한 과거 failed attempt와 abandoned partial
root다. 과거 root는 보존하며 새 `run_version`과
`JNJ-history-recovery-<run_version>` basename을 써야 한다. marker의 History 전체 출력 root와
consumer publication root는 구분한다. 예를 들어 publication manifest는 새 출력 아래
`panels/history_manifest.json`에 있으며 marker가 선언한 path/hash를 public reader가 확인한다.

first-five 범위는 `TXN, HD, JNJ, CVX, NEE`다. later-45 회복에는 financial `9b6e7ec`로
만든 canonical `universe50-first5-financial-acceptance-v1` artifact가 필수다. companies는
문자열이 아니라 정확한 CIK/ticker object여야 한다. runner는 exact collection/cutoff/source,
사용한 first-five config, stage receipt 전체 fileset, 다섯 회사 annual·quarterly analysis와
metadata·quality·identity·annual metrics·dataset v2·quarterly metrics·combined v3의 정확한
17개 publication manifest를 다시 연다. 과거 strings-only OPS gate는 호환 입력이 아니다.

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
    "universe_id": "exact50-t3v2-20261017-e",
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
