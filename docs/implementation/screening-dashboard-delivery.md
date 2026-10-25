# 스크리닝 대시보드 v1 구현 전달 계약

## 1. 승인과 상태

이 계약의 기준일은 **2026-10-09 KST**다. 사용자는 이 날짜에 P0–P6의 로컬
구현과 실제 21사 prepared data 실행을 승인했다. 이 문서는 구현 계약이며 현재
상태는 **IMPLEMENTED / INDEPENDENT PASS / LOCALLY_ACCEPTED**다. 최종 제품
source는 `acce036d1f8feef2f268b1df740009a11ce537e5`다. 실제 publication,
S01–S08, 독립 검증과 lead 로컬 인수는
[완료·로컬 인수 기록](screening-dashboard-completion.md)에 고정한다. 사용자의
직접 UX walkthrough, push, PR, remote CI, `main` 병합은 아직 완료되지 않았다.

2026-10-09의 writer 역할은 겹치지 않게 분리한다. 이 구현 writer는 prepared
source integrity, dataset/store/service/server/CLI, test와 문서를 소유한다. 별도
GPT-5.6 Sol 구현 writer는 checkpoint
`e1d19c63d3e7f87a595b6e7695ed1a8ae87bc276`에서 만든 격리 worktree에서
`src/sec_xbrl/screening/ui.py`와 UI 전용 test만 소유했다. 동결된 UI commit
`426592e8f3b2bcc0ba94d69c4259dc95aa2c5b5d`와 polish
`84d92039403e2770bdab7535ce784b699272ba37`을 이 브랜치에 순서대로 통합했다.
이 역할 분리는 독립 검증 또는 로컬 인수 완료를 뜻하지 않는다.

구현 브랜치의 부모는 문서 기준 `d53b9f8e5c9d38e18c93ed75b821b912c1820bfe`다.
그 부모는 locally accepted 회사-universe 제품
`8320ef06292c3855f57f2b01f4ce6b6c85ea03b7`과 추적 문서 기준
`473521560fa9e47aa00d6a273cbaa90c708ad366`의 후속 문서 변경을 포함한다.
원격 `main` 기준 `201acf9aec2f8183acb7dd843579938db14236cd`와는 구분한다.

승인 범위는 다음과 같다.

- 고정된 2026-10-08 financial-as-of 21사 cohort의 annual prepared bundle을 읽는
  immutable screening dataset 발행
- 이름 있는 조건, revision, universe snapshot, 실행, 전 회사 판정, source trace,
  SIC peer 비교, 판단 event, old/new run 비교, CSV/XLSX export
- `127.0.0.1` 전용 표준 라이브러리 HTTP service와 native HTML/CSS/JavaScript UI
- Windows 브라우저가 WSL loopback에 직접 연결하지 못할 때만 쓰는 양쪽
  `127.0.0.1` 전용 JSON-line transport adapter
- SQLite의 append-only 실행·판단 이력과 빈 목적지 backup/restore
- S01–S08의 실제 cohort 및 별도 synthetic/cache fixture 검증

P7의 live SEC refresh, 새 cohort, 가격·가치평가·FCF·TTM, 21사 공통 Q4, 원격
게시·병합은 이 승인에 포함되지 않는다.

## 2. 데이터·회계 경계

대시보드는 SEC/XML/ZIP을 읽거나 Arelle을 실행하지 않는다. 공시·recast·period
selection, canonical mapping, Q4 또는 재무 metric을 새로 계산하지 않는다.
입력은 이미 발행된 회사-universe completion, 회사 metadata와 회사별 `ANNUAL`
`AnalysisClient` bundle뿐이다. 웹 service는 screening publication과 SQLite만
읽는다.

v1에서 지원 후보는 기존 annual `core` profile의 직접 준비된 `REPORTED` 값 중
`revenue`, `cfo`, `operating_income`, `net_income`이다. 발행기는 실제 coverage,
status, unit, period와 trace가 유효한 record만 `AVAILABLE`로 낸다. FY
`revenue_growth`와 `operating_margin`은 기존 policy가
`ACTUAL_PERIOD_REQUIRED`로 거부하므로 `UNAVAILABLE` support entry와 reason을
남기고 실행 가능한 predicate로 공개하지 않는다. 새 formula, semantic mapping,
매수 임계값은 만들지 않는다.

같은 FY label은 날짜 동등성을 뜻하지 않는다. `period_start`와 원천의
`context_end_date`를 그대로 표시하며, end-exclusive를 화면에서 몰래 하루
빼지 않는다. SIC는 현재 관측된 coarse peer 후보 신호다. metadata 후보
8,016개와 `UNKNOWN_SIC` 7,995개는 검색할 수 있지만, prepared financial data가
없는 후보를 21사 screening target에 넣지 않는다. NVDA Q4의 2026-09-06 역사
reference는 이 2026-10-08 annual screen에 섞지 않는다.

## 3. P1 screening publication

외부 JSON config가 다음 입력을 선언한다.

```json
{
  "schema_version": "screening-prepare-config-v1",
  "dataset_id": "pilot-21-annual-20261008",
  "financial_as_of": "2026-10-08",
  "completion_root": "/absolute/prepared/completion",
  "metadata_root": "/absolute/prepared/company_metadata_v2",
  "companies": [
    {"ticker": "AMD", "cik": "0000002488", "analysis_root": "/absolute/prepared/AMD"}
  ]
}
```

경로는 caller가 제공하며 engine에 회사 또는 절대 경로를 hard-code하지 않는다.
발행기는 completion manifest/readiness, metadata manifest/table, 모든 analysis
manifest와 U5 canonical overview snapshot을 hash와 identity로 검증한다. 모든
회사는 같은 financial-as-of, `ANNUAL`, 명시 view를 가져야 한다. configured CIK,
ticker, completion CIK, metadata CIK, analysis company가 정확히 일치해야 한다.
회사·metric·FY·period class·view grain 중복, 누락 trace, 잘못된 hash, stale input,
symlink/경로 이탈은 발행 전에 fail closed 한다.

출력은 새 목적지에 원자적으로 발행한다.

```text
screening_dataset_manifest.json
companies.json
metadata_inventory.json
metric_support.json
metric_observations.json
source_snapshots/<CIK>/<snapshot-id>.json
```

manifest는 모든 파일 hash/size, publication ID, dataset ID, configured CIK,
financial-as-of, metadata/completion/analysis publication identities, parser·mapping·
selection·metric version, source observed/review times를 묶는다. observation은 값과
blank를 구분하고 full unit/dimension, original status/quality reason,
`quality_blocking`, actual period dates, fiscal year, mapping relation, source
cell/Fact/accession와 canonical snapshot/trace를 보존한다. `U5 BLOCK`은 숫자가
아니며 raw amount는 lineage-only로 남긴다. reader constructor는 모든 declared
file과 digest, count, identity, unique grain을 검증하고 안전한 record/snapshot을
메모리에 고정한다. 명시적 `verify_all()`은 현재 publication file hash/set을 다시
확인하며 source anchor 평가는 reader를 열 때 수행한다.

`ACTUAL_PREPARED`와 cache fixture의 reader는 자체 JSON hash만 확인하지 않는다.
config/completion/metadata/analysis source anchor가 모두 있어야 하며, completion과
metadata publication을 다시 검증하고 각 analysis manifest의 정확한 declared file
set/hash 및 history-manifest checksum을 확인한다. 이어 read-only `AnalysisClient`가
같은 prepared parent에서 내는 U5 snapshot을 packaged snapshot과 cell 단위로
대조한다. 이 integrity 단계는 SEC/Raw XML을 읽지 않고 Arelle, filing selection,
recast 또는 metric 계산을 실행하지 않는다. synthetic error fixture만 명시적인
`SELF_CONTAINED_TEST_ONLY` policy로 이 외부 anchor를 사용하지 않는다.

## 4. 영속 계약과 실행 규칙

SQLite schema는 `ScreenDefinition`, immutable `ScreenRevision`, immutable
`UniverseSnapshot`, immutable `ScreenRun`/row/predicate, append-only
`DecisionEvent`, `ExportManifest`를 분리한다. 저장 조건은 원하는 metric
definition/version policy, universe selector, period policy, columns/sort를
기록한다. 실제 data/mapping/parser publication version은 각 run에 묶인다.
새 revision과 decision event만 추가할 수 있고 기존 record update/delete API는
제공하지 않는다.

`ScreeningStore.integrity_check()`는 SQLite page 검사와 foreign-key audit에 더해
append-only 관계 envelope를 다시 계산한다. 각 screen은 revision 1부터 빈틈없는
번호를 가지며 첫 revision은 parent가 없고 definition 생성시각과 일치해야 한다.
그 뒤 revision은 같은 screen의 바로 앞 revision만 parent로 가리킨다. revision
ID는 screen ID, parent ID, 번호, content hash, 생성시각에서 다시 계산하므로
self-cycle, cross-screen parent, orphan, 번호 gap과 ID 치환을 거부한다. universe,
run, decision, export도 canonical payload/hash와 row envelope를 대조하고 모든
run·parent link의 실제 존재를 확인한다. decision ID는
`decision-<event_hash 앞 24자>`와 정확히 일치해야 한다.

predicate 비교는 유한 `Decimal`에 대해서만 수행한다. 누락·불가·검토 필요·
quality block은 0이나 `FAIL`로 바꾸지 않고 `UNDETERMINED`다. 하나 이상의 유효
`FAIL`이 있으면 회사 aggregate는 `FAIL`, 모든 predicate가 유효 `PASS`이고
blocking/unknown이 없으면 `PASS`, 나머지는 `UNDETERMINED`다. target은 정확히
`pass + fail + undetermined`이며 quality-block count는 겹치는 subset이다.
정렬은 저장 column/direction 뒤에 CIK 오름차순을 최종 tie-breaker로 둔다.

run은 평가된 전 target row, predicate reason, count, input/output canonical hash를
보존한다. 같은 저장 조건을 다른 prepared dataset에 실행하면 별도 run이다.
data/rule/universe/manual-decision version 변화는 분리해 보고하며 둘 이상이 함께
바뀌어 원인을 단정할 수 없으면 `MIXED_OR_INCOMPARABLE_VERSION_CHANGE`다.
cache fixture는 `CACHE_FUTURE_UPDATE_FIXTURE`로 표시하고 live라고 부르지 않는다.

DecisionEvent는 `INTEREST`/`HOLD`/`EXCLUDE`, before/after, rationale, actor, run과
evidence ID, 이전 event를 가진다. 메모는 재무값을 바꾸지 않는다. backup은
SQLite online backup과 manifest/hash를 만들고, restore는 새 빈 목적지에서만
성공하며 기존 DB를 덮어쓰지 않는다. backup 전 원본과 backup 직후 복제본,
restore의 임시 복제본에 같은 관계 무결성 검사를 적용하므로 revision/decision
chain이 손상된 journal은 외부 manifest를 다시 hash해도 전달되지 않는다.

## 5. 공개 Python·CLI·HTTP 경계

공개 Python API는 다음 역할을 제공한다.

```python
publish_screening_dataset(config_path, destination) -> ScreeningPublication
ScreeningDatasetReader(root).verify_all()
ScreeningStore(path).create_screen(...)
ScreeningStore(path).revise_screen(...)
ScreeningService(datasets, store).execute(...)
ScreeningService(...).export_run(...)
serve(service, export_root=..., host="127.0.0.1", port=8765)
```

CLI는 다음 형태로 동결한다. `serve`에는 export root도 필수로 전달한다.

```text
python -m sec_xbrl.screening prepare --config CONFIG --destination DATASET
python -m sec_xbrl.screening status --dataset DATASET
python -m sec_xbrl.screening serve --catalog CATALOG --store JOURNAL.sqlite --exports EXPORTS --port 8765
python -m sec_xbrl.screening backup --store JOURNAL.sqlite --destination BACKUP
python -m sec_xbrl.screening restore --backup BACKUP --destination JOURNAL.sqlite
```

HTTP는 loopback host만 허용하고 state-changing request의 `Origin`이 동일
loopback origin인지 확인한다. parameterized SQL과 transaction을 사용한다.
API는 dataset/status, metric availability/series, paginated metadata/SIC peers,
screen create/revise/list, execute/reopen/compare, trace/peer comparison,
decision create/history와 export를 제공한다. 알 수 없는 metric·dataset·run은
fail closed 한다. test fault는 dependency injection/monkeypatch로만 만들고
production debug endpoint는 두지 않는다.

선택형 Windows/WSL adapter는 `examples/screening/windows-loopback-bridge.cjs`의
Windows Node listener와 `python -m sec_xbrl.screening.bridge` relay로 구성한다.
caller가 distribution, Linux Python/source root, backend/frontend port를
명시하며 제품 코드에 실행 환경 절대 경로를 넣지 않는다. Windows listener와
Python relay는 각각 고정된 `127.0.0.1`에만 연결한다. relay는 screening dataset,
SQLite 또는 재무값을 열지 않고 제한된 HTTP bytes만 전달한다.

Windows listener는 원래 frontend `Host`와 state-changing `Origin`을 먼저
검증한 뒤 backend loopback의 `Host`/`Origin`으로 바꾼다. method/path/body size,
request ID와 response size/header를 제한하고 외부 URL, 임의 proxy, secret,
네트워크 설정 변경을 허용하지 않는다. binary export의 status, bytes,
content type/disposition은 보존한다. 이 adapter는 브라우저 도달성만 해결하며
dataset/API/SQLite와 회계 의미를 바꾸지 않는다.

ScreenRun export는 U5가 아닌 별도 `screen-run-export-v1` 계약이다. canonical
JSON을 기준으로 full/selected CSV와 XLSX를 만들고, row/column order, blank,
status, reason, run/screen/universe ID, date와 publication version을 동일하게
보존한다. 각 파일은 `ExportManifest`에 hash/size/scope로 기록한다.

## 6. UI 방향과 component checkpoint

대상은 SEC 문서를 검토한 뒤 후보를 줄이고 근거와 자신의 판단을 남기는
분석자다. 화면은 원장 종이 같은 ivory, ink charcoal, filing slate, 검토 blue,
보류 amber, 차단 red를 쓰는 차분하고 조밀한 분석 작업대다. 한 화면의 초점은
전 회사 결과 표이며 장식 KPI card를 쓰지 않는다.

- **Hierarchy:** 상단에는 financial as-of, 기간, universe/회사 수, 저장 조건,
  짧은 run label, review 상태만 둔다. parser/mapping/hash는 `<details>` 안에 둔다.
- **Depth/surfaces:** border와 미세한 tonal shift만 쓰며 canvas, inset input,
  selected evidence, overlay 네 단계로 제한한다.
- **Typography:** 확인된 번들 font 자산이 없으므로 `Malgun Gothic`,
  `Noto Sans KR`, system sans fallback을 쓴다. 숫자는 tabular다.
- **Spacing:** 4px base, 8px micro gap, 12px control padding, 16px section gap을
  기본으로 한다.
- **Signature:** context strip → revision → result row → right evidence → history
  timeline이 같은 짧은 run label과 내부 ID로 연결된다.

criteria는 native `form` control, 결과는 semantic `table`, provenance는
`details`, evidence는 접근 가능한 side panel/dialog를 쓴다. `PASS`/`FAIL`/
`UNDETERMINED`/block은 색뿐 아니라 text와 reason으로 구분한다. 저장 완료는 DB
commit 뒤에만 표시한다. loading, 0건, invalid metric, save error, missing,
keyboard focus return과 1,440px/1,024px layout을 기본 상태로 구현한다. query
PASS와 사용자 관심/보류/제외는 분리한다.

## 7. 검증과 전달 gate

S01–S08은
[`screening-dashboard-user-acceptance.md`](screening-dashboard-user-acceptance.md)를
그대로 적용한다. 실제 21사 control의 expected CIK/value/status는 executor를
oracle로 재사용하지 않고 frozen input에서 별도 수동/단순 oracle로 작성한다.
tie/missing/save-failure/cached-future는 실제 성과와 분리한 fixture다.

구현 writer는 network-free unit/integration test, 전체 회귀와 Ruff를 수행하고
source commit을 동결한다. 별도 agent가 frozen commit을 읽기 전용 검증한다.
root가 실제 21사 publisher와 browser를 실행해 S01–S08 evidence를 남긴 뒤에만
로컬 인수 여부를 판단한다. 자동 browser PASS는 사람이 UX를 직접 인수했다는
뜻이 아니다. push/PR/CI/main merge는 후속 사용자·lead 결정이다.

### 2026-10-09 writer 검증 기록

source 후보 `8b3e8e18d7548af6e5cf48b8bf433770150d3efc`에는 P1 dataset publisher/reader,
SQLite journal, executor/service/export, loopback HTTP/UI와 선택형 Windows/WSL
adapter가 함께 있다. writer 검증은 다음을 통과했다.

- screening 집중 test **28 passed**
- 저장소 전체 **1,309 passed / 38 skipped**
- 저장소 전체 Ruff와 두 JavaScript file의 Node syntax check
- 실제 21사 prepared input의 브라우저 흐름: target 21 = PASS 11 + FAIL 7 +
  UNDETERMINED 3, quality block 0; 4개년 series, 실제 날짜가 다른 SIC peer,
  metadata-only 7,995개 검색, 판단 event, selected CSV, 재시작, 동일 revision
  재실행 `UNCHANGED`
- 임시 양쪽 loopback 통합: actual `/api/status` 200, 외부 Origin 403,
  same-origin POST가 backend 검증까지 전달됨

실제 검증 publication은 source 동결 뒤 새 immutable 목적지에 다시 발행해야 한다.
위 writer 실행의 `/tmp` 경로와 browser screenshot은 최종 전달 전제조건이나
독립 oracle이 아니다. native Windows Chrome에서의 bridge/export·한글 font 확인,
별도 agent 검증과 lead 인수는 계속 **PENDING**이다.

### 2026-10-09 최종 검증·로컬 인수 후속

위 `8b3e8e1` 기록은 당시 writer 후보의 역사적 상태다. 이후 독립 검증에서
revision/decision 관계 무결성, legacy column 표시, 반복 HTTP export 파일명
충돌을 차례로 발견해 해당 후보의 최종 PASS 주장을 하지 않았다. 각 결함을 새
후보에서 수리하고 원래 실패 증거를 보존했다.

최종 `acce036d1f8feef2f268b1df740009a11ce537e5`는 별도 읽기 전용 검증에서
전체 **1,322 passed / 35 skipped**, focused **38 passed**, Ruff·JS/CJS·diff,
실제 S01–S08과 native Windows 증거 검토를 통과했다. lead는 P0–P6를
**LOCALLY_ACCEPTED**로 판정했다. 정확한 publication identity, scenario 결과,
증거 hash와 남은 범위는
[완료·로컬 인수 기록](screening-dashboard-completion.md)을 따른다.
