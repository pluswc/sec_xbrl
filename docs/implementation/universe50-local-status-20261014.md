# 50 issuer KDP 교체와 로컬 상태 — 2026-10-14

이 문서는 [2026-10-13 로컬 상태](universe50-local-status-20261013.md)의 후속
결정과 수락 범위를 기록한다. 기준 financial cutoff는 2026-10-10이다. 2026-10-14
KST에 사용자는 PEP를 보류하고 KDP(CIK `0001418135`)를 대체 회사로 선택했다.
결정의 정확한 시각은 기록하지 않는다. 원래 49사에 KDP를 더한 exact 50이 현재
선택 집합이며 PEP는 이 집합 밖에서 보존된다.

## 결정과 불변 경계

- PEP의 기존 plan, 성공한 22개 Raw snapshot, custom `xbrli:timeItemType` 오류와
  partial/failure 증거를 그대로 보존한다. 잘못된 source lexical을 강제 변환하거나
  Fact·filing을 삭제하지 않으며, incomplete PEP를 성공으로 분류하지 않는다.
- KDP 교체는 사용자 membership 결정이다. ticker별 parser 예외, 새 회계 의미,
  기간 선택 변경 또는 invalid source 보존 정책을 만들지 않는다.
- annual은 5개 fiscal-year input과 4개 표시 연도, quarter는 17개 지표 정의 ×
  고정 8개 분기 구간을 유지하고 availability/reason 상태를 보존한다.
- 2026-10-13 관찰한 Nasdaq 자료에는 KDP ordinary security가 하나 있었지만,
  이는 2026-10-10 cutoff 당시의 역사적 listing을 증명하지 않는다.

## Raw와 exact-50 로컬 수락

KDP actual Raw는 `m2-layer1-v6` source `4077e87097c294ed779186b613157839f215a63e`로
수집한 22개 filing(10-K 5, 10-Q 17)이다. 759 files, 132,693,374 bytes,
176 Parquet tables와 178,831 records를 public adapter로 검증했다. 독립 semantic
대조는 numeric 110개와 identity 226개 sample에 한정된다. 이 표본은 모든 Fact의
회계 정확성, 모든 transform, taxonomy 의미 또는 relationship 등가성을 증명하지 않는다.

2026-10-14 KST의 lead local acceptance는 다음 두 범위에 한정한다.

1. KDP 22개 actual Raw artifact와 parser provenance.
2. 기존 locally accepted 49사 input matrix에 KDP를 더한 exact 50 metadata/input
   selection.

최종 selection은 unique CIK 50개와 1,097개 accession이다.

| form | count |
| --- | ---: |
| 10-K | 250 |
| 10-K/A | 5 |
| 10-Q | 839 |
| 10-Q/A | 3 |

기존 49사는 1,075개(10-K 245, 10-K/A 5, 10-Q 822, 10-Q/A 3)이며 byte/logical
value가 고정된 input matrix를 재사용한다. KDP의 22개가 이를 1,097개로 만든다.
active v2 evidence chain은 acyclic operational Raw report에서 exact-50 candidate를
거쳐 독립 report로 이어진다. 초기 v1 audit finding은 삭제하거나 성공으로
재해석하지 않는다.

이 수락은 **RAW50_LOCALLY_ACCEPTED**와 **EXACT50_INPUT_SELECTION_LOCALLY_ACCEPTED**다.
`HISTORY_READY`, `FINANCIAL_READY`, annual/quarter publication, native U1–U8 또는
전체 rollout 수락이 아니다.

## history source와 JNJ recovery 상태

history/recovery source `5cd24385ce25ab17d0238df635266812e0069440`은 독립
source-only PASS를 받았다. 이전 source `2027e218…`의 actual CLI 실행은 module-as-main
ContextVar 분리 때문에 reported copy 뒤 NOT_READY로 실패했다. 그 실패 root와 보고서는
보존한다. 최소 CLI owner 수리는 253 unit와 fresh subprocess cached 2-filing gate를
통과했고, `5cd2438…`의 독립 source report와 bound recovery proof가 수락됐다.

Lead는 2026-10-14 KST에 trusted exclusive parent를 사용한 JNJ
`COMPLETE_STAGE_RECOVERY` 한 건만 실행 승인했고 recovery가 시작됐다. 이 transaction
안의 governed quarter-history completion은 승인된 recovery의 일부다. standalone quarter
metrics, CVX, financial publication, bulk 49/50 history 또는 자동 재시도 승인은 아니다.
현재 문서 동결 시점에는 process exit 0, complete artifact, 독립 recovered-artifact audit와
lead local acceptance가 없다. 따라서 JNJ도 아직 `HistoryREADY`가 아니다. 실행 중
checkpoint나 중간 파일을 완료 증거로 고정하지 않는다.

## 상태 분리

| 단계 | 2026-10-14 상태 |
| --- | --- |
| 사용자 membership 결정 | PEP hold, KDP replacement **APPROVED** |
| KDP Raw source | `4077e870…`, v6; source 검증과 actual artifact 독립 PASS |
| exact-50 Raw/input selection | 독립 PASS, lead **LOCALLY_ACCEPTED** |
| history/recovery source | `5cd2438…` 독립 **PASS_SOURCE_ONLY** |
| JNJ actual recovery | lead 승인·실행 시작; 종료와 artifact 수락 미확인 |
| financial/annual/quarter/native | **NOT_READY / 미수락** |
| main·원격·scheduler | 미병합·미배포·미승인 |

`main`의 tracked tree는 clean 상태로
`201acf9aec2f8183acb7dd843579938db14236cd`에 남아 있다. 별도 frozen source/runtime
worktree `5cd2438…`도 이번 docs 변경에서 수정하지 않았으며, 이 로컬 source와 docs는
main merge가 아니다. 보호된 user journal SHA-256
`fbc0f7604e7a6aebb578bdaadc9bc46a980b3d43f7c857c8efeeab4ca465384c`도
변경하지 않았다.

## 다음 gate

1. 실행 중인 JNJ recovery의 exit와 immutable complete artifact를 확인한다.
2. 별도 읽기 전용 검증자가 full inventory/hash/schema/public reader, bound proof,
   old prefix와 recovery receipt를 검증한다.
3. lead가 JNJ recovered artifact를 별도로 local accept한 뒤에만 CVX와 first-five
   financial identity chain을 판단한다.
4. first-five annual/quarter exact gate 뒤 complete exact 50으로 확대하고, 이후
   native U1–U8과 local rollout을 각각 별도 수락한다.

앞 단계의 PASS는 다음 실행, publication, main merge나 scheduler 승인을 자동으로
부여하지 않는다.

## 증거 식별

아래 `work/` 경로는 선택적 provenance locator다. 이 파일이 없는 checkout에서도 위
결정과 상태 경계를 이해할 수 있어야 한다.

| 증거 | locator | SHA-256 |
| --- | --- | --- |
| KDP Raw·exact-50 독립 report | `work/universe50_quarterly_20261010/resumption_20261013/independent_kdp_raw_v6/report.json` | `85dd76ba38025ef233dcf6f70fb827088c29d5f56203ace5fff65907a1e0afe2` |
| KDP operational Raw v2 | `work/universe50_quarterly_20261010/resumption_20261013/kdp_replacement_v6_operational_raw_report_v2.json` | `68d2559222572ca6b38fa6afd72a0362c6cc0f15ffdfb47696a7d35f351af5a6` |
| exact-50 candidate v2 | `work/universe50_quarterly_20261010/resumption_20261013/actual50_kdp_raw_candidate_v2.json` | `cbcf87dd3deedb75035b7bacc752af93d55d96a3f63ed577d416b97b3b994249` |
| accepted 49 input matrix | `work/universe50_quarterly_20261010/resumption_20261013/history_input_matrix_49_v1.json` | `daddaa7b25809aa67c69556cafe296baf9b01bf510bd4ec694b37ab8e4395ddd` |
| 49 matrix 독립 report | `work/universe50_quarterly_20261010/resumption_20261013/independent_history_matrix_49/report.json` | `d575249f80342b59f5adf836489426f09fff2f073f971c148901097e36db9299` |
| 보존된 KDP v1 finding | `work/universe50_quarterly_20261010/resumption_20261013/independent_kdp_raw_v6/binding-failure-v1.json` | `0543af674c436257f616b443da5d10c6ee49777eab1f82555615340f641fd55c` |
| `5cd2438…` source report | `work/universe50_quarterly_20261010/resumption_20261013/independent_source_5cd2438/report.json` | `4129fef083a7741f0c5703a74de57cb48bac29c92635476213c20376daa43887` |
| bound recovery proof | `work/universe50_quarterly_20261010/resumption_20261013/independent_jnj4_binding_5cd2438/recovery_api_attestation_BOUND_5cd2438_v1.json` | `1a2cb835d158a837f9bddc3f6b094cc952035948e89f3a661b0ebc5444a364fd` |
| 보존된 `2027e21…` actual failure | `work/universe50_quarterly_20261010/resumption_20261013/jnj_recovery_2027e21_failure.json` | `3c6c4c92557e9a4df2e28f79c25d6a2b3661776953fe7de44375dcfdf74796c7` |
| `2027e21…` CLI source gap | `work/universe50_quarterly_20261010/resumption_20261013/independent_source_2027e21_cli_diagnosis/finding.json` | `51d2e92338554eb3e4d2b4f51dc309ccd477cf938dd2e27872528a5613187ae2` |

이 문서를 작성한 runtime은 정확한 model identifier를 노출하지 않았다. 기본 모델
배정을 실제 실행 모델의 증거로 사용하지 않으며, 별도 독립 검증 역할을 유지한다.


## 2026-10-14 후속 — actual 5cd resource stop와 bounded quarter 수리

위의 actual 결과 미확인 상태는 후속 실행 증거로 갱신한다. `5cd2438…` 실제
recovery는 971.578초에 sampled process-tree RSS 16,886,848 KiB로 16 GiB
운영 stop을 넘었다. wrapper 70 / child SIGTERM이며 COMPLETE와 consumer panels는
없다. reported component 37 files / 965,106,797 bytes와 NOT_READY root를 보존한다.
quarter partial은 `.chunks` directory만 있고 0 files다. `017` log/GNU time은
0 bytes라 정확한 stack·GNU peak·kernel OOM을 주장하지 않는다. source control flow와
RSS는 첫 source table eager load/repartition 부근을 강하게 가리키지만 traced 원인은
아니다. 데이터/회계 불일치 판정도 아니다.

봉인 report `jnj_recovery_5cd2438_resource_stop.json` SHA-256은
`4f4dd9d97907772da2ee2714edc8f7c67c12d2d890856cce4033c7746095fd60`,
postflight는 `58a5e35ae66dd3cedb0292452170b4ee2fd89098617cb2d076d4c82439b4feff`다.
모두 기존 resumption evidence 경로의 불변 과거 증거이며 수정하지 않는다.

lead는 단일 source writer에게 complete generic bounded-quarter-production을
**APPROVED**했다. accepted docs descendant `5f332215…`로 local fast-forward한 뒤
private disk-backed record/index, bounded whole-field iteration, exact ordered
candidate/derivation assembly, flush telemetry를 구현한다. 구현 상태는
**IMPLEMENTED / writer validation**, 별도 source **INDEPENDENT VERIFICATION PENDING**,
실제 결과 **NOT_READY / NO RETRY**다. 회계·Raw·public T1 validation·기간/window·
source parent·KDP membership 결정은 불변이다. 저장/수명 수리의 상세와 재현 기준은
[회사 history workflow의 bounded quarter 계약](company-history-workflow.md#2026-10-14-bounded-quarter-production-after-actual-source-5cd-resource-stop)에 있다.

새 독립 source PASS와 lead의 별도 실제 실행 GO 전 actual recovery, CVX,
financial/consumer/metric rollout, cap 인상은 하지 않는다. exact-50 Raw 로컬 수락은
계속 유효하되 History/financial 준비 완료와 구분한다. main·journal·기존 data·증거·
실행 config를 바꾸지 않으며 remote/PR/merge/scheduler 실행은 없다.


이번 bounded-quarter 후보의 writer 검사(2026-10-14): 기존 253 controls를 포함한
264 unit PASS(14.48초), cached NVDA 2 filings의 API+fresh CLI PASS(36.73초),
old `a36ea059…` oracle 8 tables/25 files/4,686 ordered panel records/42 derived
PASS(4.39초), Ruff와 diff check PASS다. 각 sampled process-group peak는
276,439,040 / 391,143,424 / 224,862,208 bytes이며 각각 2 GiB hard AS + sampled
RSS/300초 guard 아래 실행했다. 이는 합성/작은 캐시 fixture 결과이고 JNJ actual
메모리 수락 증거가 아니다. 원본 source generation reported bytes는 그대로이고,
consumer Parquet는 32-row group 때문에 physical hash가 달라도 전체 ordered raw
scalar/JSON·schema·decoded values가 oracle과 동일해야 한다. `_sequence`, `_scope`,
`approved_additive`, `derive_quarter`는 `5cd2438…`와 AST 동일성을 확인했다.
새 freeze의 별도 독립 검증과 lead 판단은 아직 대기한다.


## 2026-10-15 후속 — source 951 SQLite ownership FAIL 수리

`9515322417df9da118fc60fa539b75d27793847b`는 독립 source 검증 FAIL
(report SHA256 `06d48bc7abc79f9a89fb0b2a97e98e14250c59a91bce7576c6138f9b4e47569a`).
소유 inode capture 후 SQLite pathname 재개방 사이의 교체가 foreign DB를
변경했다. 기존 보고서·951 실행 미승인 draft·과거 결과는 보존한다. 새 writer의
동결951 source를 사용한 public synthetic probe도 같은 foreign SHA 변경
`4bb48dfb…` → `e014871a…`를 재현했다. 실제 데이터 재실행은 하지 않았다.

lead 승인 범위의 비회계 수리는 anonymous temporary disk SQLite index와
exclusive held-FD typed mutation journal이다. anonymous rebuildable scratch만
close 시 회수하는 명시적 보존 예외이며 모든 named recovery diagnostics는
보존한다. [날짜별 규범 계약](company-history-workflow.md#2026-10-15-sqlite-ownership-repair-after-source-951-fail)에
trust boundary, complete/truncated frames, PLANNED/APPLIED 의미를 기록했다.

새 writer 검사: 273 unit PASS(18.85초, sampled peak 275,349,504 bytes),
NVDA cached 2-filings imported API + exact fresh `python -m` CLI recovery PASS
(118.94초, 397,168,640 bytes), old `a36ea059…` oracle 8 tables/25 files/
4,686 panel records/42 derived records PASS(4.47초, 232,402,944 bytes).
전체 ordered physical scalar/JSON·schema·decoded values 및 logical metadata를
대조했으며 row-group 변경에 따른 consumer Parquet SHA 차이만 허용했다.
Ruff/diff check PASS. `_sequence`, `_scope`, `approved_additive`, `derive_quarter`
AST는 frozen951과 동일하다. 테스트는 2 GiB hard per-process AS 및 sampled
process-group RSS/300초 guard, Polars2/BLAS·OMP·Rayon1, Python socket deny
아래 실행했고 skip 또는 resource stop이 없었다. sampled RSS와 hard virtual
address-space limit는 같은 보장이 아니다.

이는 writer의 작은 fixture 검증이며 새 frozen SHA의 독립 검증·lead 인수·
actual 실행 GO는 아직 대기한다. Raw50/KDP 승인과 원본 source-generation
identity는 불변이다. History/financial READY, main merge, 실제 JNJ memory
수락을 선언하지 않는다. 이전 actual 실패 root와 원본 reported bytes는 불변이다.
