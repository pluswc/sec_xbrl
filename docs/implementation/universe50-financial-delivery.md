# 50사 재무 통합·실행 전달 계약 — 2026-10-17

## 결정과 현재 상태

사용자와 리드는 2026-10-17 exact-50 immutable collection을 부모로 삼아 연차·분기
스크리닝 publication을 만드는 로컬 통합과 fail-closed 실행 경계를 승인했다. 승인된 작업
계약은 로컬 운영 기록
`work/universe50_quarterly_20261010/resumption_20261017_t3v2/lead_integration_and_financial_runner_contract.json`
(SHA-256 `5988e1287fd7163ac7c8ca89fe8552d22b4b444cc39f95cf5809ebcc14f2c449`)에
보존한다. 이 문서는 그 결정을 추적 가능한 구현 계약으로 승격한다.

| 단계 | 현재 상태 |
| --- | --- |
| 범위 승인 | **APPROVED** — 동결 source 통합, quarterly identity 결속, offline runner와 합성 검증 |
| 입력 source | producer `8a1b40a`, generic identity `6470e0b`, OPS `56a9d57`, package view `6e6f379` |
| identity 검증·인수 | `6470e0b` 독립 PASS, source/synthetic 로컬 수락 |
| 통합 구현 | **IMPLEMENTED CANDIDATE** — 새 동결 SHA와 독립 검증 확정 전 |
| actual financial 실행 | **NOT_STARTED / NOT_READY** |
| actual first-five·50사 인수 | 미수행 |
| native UI·저장 journal 반영 | 미수행 |
| push·PR·main 병합 | 미수행 |

source/synthetic PASS는 actual financial payload, actual publication 또는 native 화면 인수를
대신하지 않는다. 최종 통합 후보는 깨끗한 동결 SHA에서 별도 읽기 전용 검증을 통과해야
actual stage GO 후보가 된다.

## 누적 source와 보존 경계

통합 branch는 producer `8a1b40a`를 기준으로 검증된 identity `6470e0b`, OPS
`56a9d57`, package view `6e6f379`를 일반 merge해 각 이력을 보존한다. 이 병합은 다음을
동시에 유지한다.

- annual producer의 회사별 5 fiscal-year 입력, 최신 4 fiscal-year 표시, unavailable과
  source lineage 정책
- legacy `UniverseDelivery`와 manual reviewed-Q4 경로 및 기존 v1/v2/v3 publication
- 명시적 `GENERIC_METRIC_IDENTITY_ATTESTATION` source kind와 fallback 금지
- OPS의 shared heavy lock, process-tree RSS 감시, timeout과 owned process-group cleanup
- package view의 immutable manifest와 archive hash 재검증

Raw parser, history·analysis 구성, 분기 산술, source selection, UI/service/store와 저장 journal의
계산·정책은 바꾸지 않는다. 실행 도구는 이 모듈의 공개 producer API만 순서대로 호출한다.

## quarterly generic identity 결속

legacy annual metric parent에는 기존 quarterly producer 동작을 그대로 적용한다. annual metric
parent가 명시적 generic identity를 선언한 경우에만 quarterly producer는 다음을 추가로
검증한다.

1. annual metric manifest에 기록된 kind, identity root, manifest SHA-256과 publication ID로
   `GenericMetricIdentityReader`를 다시 연다.
2. identity의 financial cutoff와 CIK/ticker cohort가 annual metric membership과 정확히
   일치하는지 확인한다.
3. 각 quarterly analysis의 root, publication ID, manifest SHA-256, 선언 data-file hash,
   history manifest SHA-256, `QUARTERLY` period mode와
   `quarter-typed-primary-pre-evidence-v1`가 identity의 attested parent와 정확히 같은지
   비교한다.
4. foreign CIK, stale manifest, 같은 회사의 다른 analysis root/history 또는 변조된 parent는
   publication 전에 거부한다. 성공한 quarterly manifest는 사용한 generic identity를 다시
   고정한다.

identity는 quarterly *analysis*까지만 부모로 두며 quarterly metric을 부모로 두지 않는다.
따라서 `identity → annual31 → annual dataset v2 → quarterly17 → combined dataset v3`
순서에 순환 의존이 없다.

## offline financial runner

`tools/universe50_financial_ops.py`는 새 실행마다 명시적 JSON config, source-only preflight,
stage request와 운영자가 별도로 작성한 exact GO를 요구한다. config는 다음을 모두 고정한다.

- exact-50 collection manifest path/hash와 parent company count 50
- `FULL` 또는 `EXPLICIT_SUBSET`; first-five는 정확히 `TXN, HD, JNJ, CVX, NEE`
- scoped 회사의 CIK/ticker, history root/manifest hash, collector·plan·intake 선언 hash,
  5 input FY와 4 display FY
- `financial_as_of=2026-10-10`과 별도
  `metadata_observation_cutoff=2026-10-13T23:59:59Z`
- package view root/manifest hash, source HEAD, 실행에 import되는 모든 producer·OPS·package
  view·runner 파일 hash와 checkout 경로
- 겹치지 않는 absolute fresh output root, fresh execution root, shared resource root
- process-tree RSS 16 GiB, `POLARS_MAX_THREADS=2`, 한 번에 하나의 heavy stage와 10,800초
  timeout

preflight는 exact-50 parent를 다시 열고 scoped 회사만 `READY`, `selected == held`,
pending/failed 0인지 확인한다. `EXPLICIT_SUBSET`은 범위 밖 45사를 완료나 PASS로 승격하지
않는다. 부모 collection, package view, 선택 history와 source 파일이 바뀌면 이후 request와
GO가 무효다. 각 GO는 config, source HEAD, preflight, 정확한 cohort, parent receipt와 output
root를 모두 hash로 결속한다.

worker는 부모가 shared heavy lock을 보유한 채 전달한 일회성 pipe capability가 있어야만
실행된다. 각 stage는 별도 process group에서 OPS 감시기를 사용한다. 실패·timeout·RSS 초과나
부분 output은 그대로 실패 증거로 남고 같은 stage의 자동 재시도나 덮어쓰기를 막는다. 성공
receipt는 output의 전체 regular-file 집합, 각 hash와 크기를 고정하며 모든 후속 stage가 이를
다시 확인한다. runner는 독립 수락 기록을 스스로 생성하지 않는다.

공통 producer 순서는 다음과 같다.

1. metadata publication 확인 또는 별도 fresh exact-50 metadata 발행
2. `prepare_analysis` annual 5 FY (`include_year_end_balances=True`)
3. `prepare_analysis` quarterly (`include_quarter_source_evidence=True`)
4. package view와 exact histories를 사용한 generic quality
5. metadata·quality·history·annual/quarterly analysis를 고정한 generic identity
6. annual 31 metrics와 annual dataset v2
7. attested quarterly analysis를 쓰는 quarterly 17 metrics
8. combined dataset v3

### exact config와 실행 CLI

실제 실행 config는 다음 최상위 shape를 사용한다. 아래 한 회사·한 snapshot 항목을 승인된
scope와 exact-50 metadata source 수만큼 반복한다. `<...>`는 실행 전에 실제 absolute
path나 lowercase hash로 모두 치환해야 하며 runner는 placeholder, 상대 경로와 누락 pin을
거부한다.

```json
{
  "schema_version": "universe50-financial-ops-config-v1",
  "universe_id": "<exact-parent-universe-id>",
  "dataset_id": "<new-financial-dataset-id>",
  "financial_as_of": "2026-10-10",
  "metadata_observation_cutoff": "2026-10-13T23:59:59Z",
  "collection_scope_mode": "EXPLICIT_SUBSET",
  "first5": ["TXN", "HD", "JNJ", "CVX", "NEE"],
  "companies": [{
    "ticker": "TXN",
    "cik": "0000097476",
    "input_years": [2021, 2022, 2023, 2024, 2025],
    "display_years": [2022, 2023, 2024, 2025],
    "history_root": "/absolute/fresh/history/TXN",
    "history_manifest_sha256": "<64-hex>",
    "collector_source_commit_sha": "<40-hex>",
    "plan_sha256": "<64-hex>",
    "intake_sha256": "<64-hex>"
  }],
  "collection": {
    "manifest": "/absolute/exact50/collection_manifest.json",
    "manifest_sha256": "<64-hex>",
    "parent_company_count": 50
  },
  "package_view": {
    "root": "/absolute/package-view/archives",
    "manifest_sha256": "<64-hex>"
  },
  "metadata": {
    "mode": "PUBLISH_EXACT50",
    "snapshots": [{
      "ticker": "TXN",
      "cik": "0000097476",
      "path": "/absolute/cached/submissions/CIK0000097476.json",
      "sha256": "<64-hex>",
      "observed_at": "2026-10-10T00:00:00Z",
      "source": "sec_submissions",
      "source_url": "<original-source-url-or-null>"
    }],
    "kdp_acquisition_evidence": {
      "path": "/absolute/KDP-operation-evidence.json",
      "sha256": "<64-hex>",
      "completed_at": "2026-10-13T14:45:00.965796Z"
    }
  },
  "source": {
    "checkout": "/absolute/clean/integration-checkout",
    "head": "<40-hex-final-integration-SHA>",
    "module_sha256s": {
      "analysis": "<64-hex>",
      "company_metadata": "<64-hex>",
      "metric_quality": "<64-hex>",
      "metric_identity": "<64-hex>",
      "annual_metrics": "<64-hex>",
      "annual_dataset_v2": "<64-hex>",
      "quarterly_metrics": "<64-hex>",
      "combined_dataset_v3": "<64-hex>",
      "resource_ops": "<64-hex>",
      "package_view": "<64-hex>",
      "runner": "<64-hex>"
    }
  },
  "outputs": {
    "metadata": "/absolute/fresh/output/metadata",
    "annual_analysis": "/absolute/fresh/output/annual-analysis",
    "quarterly_analysis": "/absolute/fresh/output/quarterly-analysis",
    "quality_indexes": "/absolute/fresh/output/quality-indexes",
    "quality_bindings": "/absolute/fresh/output/quality-bindings",
    "quality": "/absolute/fresh/output/quality",
    "identity": "/absolute/fresh/output/identity",
    "annual_metrics": "/absolute/fresh/output/annual-metrics",
    "annual_dataset_v2": "/absolute/fresh/output/annual-dataset-v2",
    "quarterly_metrics": "/absolute/fresh/output/quarterly-metrics",
    "combined_dataset_v3": "/absolute/fresh/output/combined-dataset-v3"
  },
  "execution_root": "/absolute/fresh/execution-evidence",
  "resource_root": "/absolute/shared-resource-lock-root",
  "limits": {
    "process_tree_rss_kib": 16777216,
    "polars_max_threads": 2,
    "one_heavy_process": true,
    "timeout_seconds": 10800
  }
}
```

기존 first-five metadata를 쓸 때는 `metadata`를
`{"mode":"EXISTING_PUBLICATION","root":"/absolute/root","manifest_sha256":"<64-hex>"}`로
바꾼다. final 50 실행은 `collection_scope_mode=FULL`과 회사 50개를 요구한다.

모든 명령은 clean configured checkout에서 같은 interpreter와 `PYTHONPATH=src:.`를 사용한다.

```bash
python tools/universe50_financial_ops.py preflight --config /absolute/config.json
python tools/universe50_financial_ops.py request-stage --config /absolute/config.json --stage annual-analysis
python tools/universe50_financial_ops.py run-stage --config /absolute/config.json --stage annual-analysis --go-file /absolute/operator-go/annual-analysis.json
```

fresh metadata mode는 `metadata` stage부터 요청한다. 이후 stage 이름은
`annual-analysis`, `quarterly-analysis`, `quality`, `identity`, `annual-metrics`,
`annual-dataset-v2`, `quarterly-metrics`, `combined-dataset-v3`다. 각 stage마다 먼저
`request-stage`를 실행하고, 리드/운영자가 그 request의 source HEAD, config/preflight hash,
scope, parent receipts와 outputs를 그대로 복사한 아래 GO를 별도 경로에 작성한 뒤
`run-stage`를 호출한다.

```json
{
  "schema_version": "universe50-financial-stage-go-v1",
  "status": "GO",
  "stage": "annual-analysis",
  "source_head": "<40-hex-final-integration-SHA>",
  "config_sha256": "<64-hex>",
  "request_sha256": "<64-hex>",
  "scope_companies": [{"ticker": "TXN", "cik": "0000097476"}],
  "parent_receipts": [],
  "outputs": ["/absolute/fresh/output/annual-analysis"]
}
```

runner는 GO를 생성하거나 승인하지 않는다. request와 byte-for-byte 의미가 다른 GO, 이미
시도한 stage, 기존 output과 실패 후 재실행은 모두 거부한다.

## metadata 시간축

기존 PEP 포함 metadata publication은 덮어쓰지 않는다. runner는 기존 immutable publication을
명시 hash로 재사용하는 mode와, original 49 cached SEC root observation에 KDP cached root를
더해 새 exact-50 publication을 만드는 mode를 분리한다. 새 mode는 50개 absolute source
path/hash, 고유 CIK/ticker, 원래 `observed_at`, KDP를 정확히 한 번, KDP prepare 완료 증거
`2026-10-13T14:45:00.965796Z`와 그 파일 hash를 요구한다.

모든 observation과 acquisition evidence는 별도 metadata cutoff 이하여야 한다. 발행 뒤
public `CompanyMetadataReader`의 정확한 50개 CIK/ticker를 collection parent의 50개와 다시
비교한다. `financial_as_of`를 metadata cutoff로 재사용하거나 timestamp를 조작하지 않는다.
이 metadata는 current observation이며 2026-10-10 당시 historical universe membership을
증명하지 않는다. 기존 first-five metadata publication도 명시 hash와 같은 reader 검증을
통해 계속 사용할 수 있다.

## 검증과 실행 전 gate

source 후보는 최소한 다음을 통과해야 한다.

- fresh synthetic quality → identity → annual31 → annual v2 → quarterly17 → combined v3
- foreign/stale/same-company unrelated quarterly parent와 다른 history parent 거부
- metadata cutoff 이후 observation, 잘못된 KDP evidence, exact-50 membership 차이 거부
- first-five publication 뒤 범위 밖 회사 진행에도 기존 publication 재열기 안정성
- legacy annual/quarterly와 v1/v2/v3, explicit save/load 및 관련 golden·HTTP 회귀
- unit/screening tests, Ruff와 clean diff 검사

그 뒤 별도 검증자가 정확한 clean SHA를 검증해 PASS해야 리드가 actual stage GO 여부를
판단한다. actual Raw/history payload 읽기, SEC network, production DB, live UI, main 병합,
push·PR와 scheduler 변경은 이 source 구현·합성 검증 단계에서 수행하지 않는다.
