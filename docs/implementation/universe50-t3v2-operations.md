# 50사 T3v2 재개 운영 계약 — 2026-10-17

상태는 **IMPLEMENTED, 실행 전 PREPARED 경로**다. 소스 기준은 `8a1b40a…`, 리드의
T3 source/tiny 로컬 수락 증거 SHA-256은 `c6e8c993…`다. 이 문서는 Raw 또는 재무
실행 완료를 기록하지 않는다.

`tools/universe50_t3v2_ops.py`는 다음 단일 경로를 제공한다.

1. `config-preflight`: authoritative config, 49사 matrix, exact-50 KDP candidate,
   독립 KDP Raw 보고서, T3 리드 수락의 고정 hash를 검증한다. PEP 제외, KDP 포함,
   50사·1,097 filings, cutoff `2026-10-10`, annual 입력 5 FY·표시 4 FY와 module
   hash를 기록한다.
2. `prepare-new-collection`: 기존 config shape에 새 universe id를 부여하고 candidate의
   exact plan 50개를 `prepare_universe(..., existing_plans=..., offline=True)`로 준비한다.
3. `adopt-accepted-raw`: 별도 exact GO가 있을 때 각 candidate plan/intake의 hash와
   file identity를 고정하고, 각 filing의 실제 `source_run` snapshot을 public Raw loader와
   plan validator로 전수 검증한다. 새 intake에는 `REUSED` reference만 기록하고 public
   `RAW_COMPLETE`를 재검증한다. Raw 복사·재파싱·network는 없다.
4. `build-one`: ticker별 GO 아래 public `history.build_history`를 새 root
   `{TICKER}-t3v2-{run_id}`에서 실행한다. 기존 build attestation 생성·검증·write-once
   helper로 실제 publication을 검증한 marker만 기록하고 public `READY`를 재확인한다.
5. `status`: parent exact-50과 명시적인 `collection_scope_companies`를 함께 보고한다.
   first-5 품질/identity는 TXN, HD, JNJ, CVX, NEE만 계산하고 나머지 45사의 pending을
   완료로 올리지 않는다. 최종 scope는 50개 모두 READY여야 한다.

runner는 OPS worktree에서 실행하되 engine은 config의 별도 `engine_checkout`에 있는 clean
`8a1b40a…` checkout만 사용한다. 실행 시 그 checkout을 `PYTHONPATH`의 source root로
지정해야 한다. program SHA는 OPS runner 자체를, engine SHA는 실제 import된
`history.py`, `collection_operations.py`와 T3 영향 파일
`longitudinal/exploration_graph.py`, `longitudinal/materialization.py`를 각각 고정한다.
import 경로가 configured engine과 다르거나 engine HEAD/clean 상태 또는 어느 module
hash가 바뀌면 실패한다. 완료 root 재사용은 config, program, engine, intake, marker,
publication hash와 receipt가 모두 일치할 때만 허용한다.
partial output, marker 없는 output, 변경된 output은 자동 재시도하거나 성공으로 표시하지
않는다. 기존 collector/discovery 엔진은 수정하지 않는다.

## 설정·GO·자원 경계

config schema는 `universe50-t3v2-ops-config-v1`이며 `run_id`, source SHA, exact
`engine_checkout`, fresh
`collection_root`/`history_root`, exact first5, artifact별 absolute path와 고정 SHA-256,
다음 limits를 포함한다.

```json
{"process_tree_rss_kib": 16777216, "polars_max_threads": 2,
 "one_heavy_process": true, "timeout_seconds": 10800}
```

GO는 `universe50-t3v2-stage-go-v1`, `status=GO`, operation, run id, engine source SHA,
config/preflight, program SHA, engine module aggregate SHA와 ordered ticker scope가 정확히
일치해야 한다. 첫 실제
History 범위는 CVX 한 회사다. first-5 밖 45사는 별도의 exact-first5
`LOCALLY_ACCEPTED_FIRST5_FINANCIAL` artifact와 명시적 hash 없이는 거부한다. bulk나
financial acceptance는 자동 생성하지 않는다. log, time, RSS sample과 summary는 fresh
root에 남긴다.

quarter 분석 입력은 17개이며 표시 범위는 `2024Q4–2026Q3`의 최근 8 calendar
bucket이다. 현재 source에는 T3 수리까지만 있다. analysis, annual/quarter metric,
accuracy/identity, consumer dataset v3 명령은 다른 동결 구현과 독립 수락 전까지 넣지
않는다. 기존 Raw, legacy gate, publication, user journal과 native UI는 수정하지 않는다.

PREPARED 생성은 다음 두 명령이며 Raw/History를 실행하지 않는다.

```bash
PYTHONPATH=/frozen-8a-engine/src python tools/universe50_t3v2_ops.py config-preflight --config /path/ops-config.json
PYTHONPATH=/frozen-8a-engine/src python tools/universe50_t3v2_ops.py prepare-new-collection --config /path/ops-config.json
```

`adopt-accepted-raw`와 `build-one`은 별도 stage GO 없이는 실패한다. 현재 전달에서는 두
명령을 실행하지 않는다.
