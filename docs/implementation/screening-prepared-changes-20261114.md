# 스크리닝 준비된 변화 조건 v1

## 원격 전달 승인·최신 main 통합 (2026-11-14)

사용자가 수락된 기능의 **push·PR**을 승인했다. 이 branch에 PR97 native100 병합을
포함한 `origin/main d724c54e24257af9600a6427f83dcea792bea738`을 일반 merge했다.
준비된 변화 제품 bytes는 문서 인수 동결 `62e36392f83692ecf26055073188931046dfd085`와
동일하며 새 회계 연산/정의/reader guard를 추가하지 않는다. main의
`test_universe50_history_recovery_ops.py` polling 보정은 그대로 보존한다.
기존 source/artifact pin과 실제 자료·화면 인수는 같은 제품 bytes에 적용되므로
재발행이나 runtime 재시작을 수행하지 않는다.

원격 전달 승인과 최종 인수/병합은 별개다. 통합 독립 검증·리드 push/PR 생성·
원격 CI는 대기이며 PR 번호는 아직 없다. 준비된 변화 기능은 main에 병합하지 않았다.
아래 원격 미요청/당시 main SHA는 앞선 로컬 인수 당시 기록이다.
통합 후 Node146/Python151(기존 관련150+상류 polling1)/Ruff/diff 검사를 통과했다.
`src`, `examples`, `.interface-design/system.md`, `tests/screening`은 `62e36392f8`과
Git diff가 비어 있다. 상류 unit test는 origin/main과 정확히 같다.

2026-11-14 승인. 기존 native100 소스 `5a8fe55775`를 보존한 별도 branch
`codex/screening-prepared-changes`에 main `deb074bc49`를 일반 merge한다.
단일 writer·별도 독립 reviewer와 기존 승인 모델 fallback을 유지한다. PR85
History 수정은 별도이며 이 작업에서 고치거나 병합하지 않는다.

## 입력과 권한 경계

실제 부모는 `universe-expanded-supported-100-20261025`, publication
`screening-cohort-union-c69e55ff570fce6fd927f1bb`, manifest SHA256
`8983258d3b6314feba883dc05d21ef535c2f139f8811bf0e006cad0daa025075`,
재무 기준일2026-10-25다. 원소스·manifest·approval·reader transition receipt는
변경하지 않는다. 전체 Python source hash와 native qualification의 기존 검사도
완화하지 않는다. 새 소스에서 구 receipt를 다시 쓰거나 자동 latest로 대체하지 않는다.

별도 프로세스가 **원래 수락 소스**로 기존 reader를 완전히 검증해 read snapshot을
export한다. exporter는 원소스 밖 도구이고 입력 source/artifact/pin을 전후 검사한다.
회사별 작은 단위로 기존 관측뿐 아니라 정의·버전·단위·기간·품질·결측·입력 참조·
trace·owner·회사 metadata·support·spine·latest를 그대로 보존한다. fixed rows와
latest_rows를 분리해 WDC의 최신 보충 분기를 유지한다. 새 물리 snapshot ID와
파일별/전체 논리 hash, 원래 logical dataset/publication/관측 ID를 구분한다.
ROOT의 정확한 별도 승인 전에는 reader가 이를 받지 않는다. 같은 logical ID/pub에
다른 snapshot 내용의 중복 등록도 거부한다. snapshot은 원 데이터 재생성이 아니다.

기존 catalog의 source-bound publication도 필요에 따라 같은 명시적 snapshot으로
읽어 과거 저장 결과를 유지한다. 변경된 native/producer 권한을 old reader에
전파하지 않는다. root가 실제 export·승인·파생 발행·복제 UAT·운영 전환을
수행하며 writer는 합성/명시적 cached 검사만 수행한다. 실제 Raw/cache/financial/
기존 Derived/journal 쓰기, live 서버·원격 작업은 금지한다.

## 새27개 정의와 계산 정책

일반 numeric YoY9개: operating_income, cfo, standardized_fcf 각각의 연간·
분기·TTM. ID는 각 원래 ID에 `_yoy`를 붙인 명시 목록이다. 비율 %p18개는
아래 원래 ID에 `_yoy_pp`를 붙인다.

- 연간7: gross_margin, operating_margin, net_margin, fcf_margin, current_ratio,
  liabilities_to_equity, liabilities_to_assets.
- 분기7: 위7의 명시적 quarter_ ID.
- TTM4: ttm_gross_margin, ttm_operating_margin, ttm_net_margin, ttm_fcf_margin.

revenue_yoy·quarter_revenue_qoq/yoy의 재차 %p와 실제 RATIO의 임의 %p는 제외한다.
목표 catalog는 연간41개·분기/TTM59개지만 실제 관측 가용성은 따로 집계한다.
현재 보드의50개사 보조자료만 복사하지 않고 부모100개사의 준비된 입력 전체를
대상으로 하되, 없는 이전 FY/TTM8 legs·연간 baseline·계보를 만들거나 backfill하지 않는다.

기존 v1/v2 비교 엔진과 정확한 Decimal 연산을 재사용하고 같은 계산을 복제하지
않는다. 연간은 직전 FY, 분기/TTM은 전년 같은 회계분기다. 기존 동일 회사/
정의·버전·단위·차원·기준·품질·날짜/연속성·재귀 입력·분모 검사를 유지한다.
금액은 prior>0/current>=0일 때만 일반 YoY이며 양수→0은 -100%다. 부호 전환,
prior0, 둘 다 음수, 음수→0은 numeric YoY UNDETERMINED와 원래 구체 state/
reason을 유지한다. 전환형/음수 축소율 조건은 추가하지 않는다.
비율은 공표 PERCENT 현재−전년의 정확한 percentage points이며 비율의 성장률이
아니다. 단위 PERCENT와 PERCENTAGE_POINT, definition version·input lineage를
명시하고 UI 기준값도 같은 단위를 사용한다.

새 catalog에는 comparison_of/comparison_kind/기간 관계를 명시한다. 상세·
다중 보드도 같은 새 공표 pair를 쓰고 조건 등록 표시로 연결한다. 새 변화 지표
자체에서 다시 변화 쌍을 만들지 않는다. old publication은 기존 aux 비교를 유지한다.

## 검증·인수

합성 단위/통합, Node와 Ruff/diff 및 가능하면 전체 pytest를 수행한다. 원소스
전후 변조/승인 누락·receipt mismatch·행/trace/owner/pub/기간/missing file 변조,
중복 logical scope 거부를 검사한다. sign9·정확 %p·작은 값·0·정의/분모/계보·
TTM gap/duplicate·fixed/latest 구분, 등록/조회/evaluation/threshold/export/저장/
재열기/휴지통 복제본을 검증한다. old50 aux의 같은 좌표 전수 값/상태를 대조해
차이가 있으면 source/gate 원인을 설명하기 전 발행을 보류한다. 회사×지표×기간의
가용/미준비 사유를 집계하고 전체100 준비를 추정하지 않는다.

리드는 실제 모든 catalog publication별 재열기 동등성, 대표 과거 saved run의
행/정렬/판정/ID/trace/CSV와 journal 원형을 private 복제본에서 대조한다.
현재 main의 cached History 실패가 나타나면 baseline으로 분리하고 이번 scope에
포함하지 않는다. 소스 동결·독립 검증·리드 승인·운영 반영은 각각 별도다.

| 단계 | 상태 |
| --- | --- |
| 승인 | 2026-11-14 명시 범위 GO |
| 구현 | IMPLEMENTED: 최종 UI `86b87d592c`, financial producer `2070a27d7a` |
| 실제 export/ROOT 승인/발행 | 리드가 원본 11개 snapshot과 새 27개 발행물 승인·준비 완료 |
| 독립 검증 | INDEPENDENTLY_VERIFIED: Node146/Python150/Ruff 및 아래 범위 PASS |
| 로컬 인수 | LOCALLY_ACCEPTED: 리드, 2026-11-14 |
| 운영 | 18765 실제 화면 인수 PASS; 아래 PID/rollback 기록 참조 |
| 원격 전달/main | 2026-11-14 push·PR 승인; 최신 main `d724c54e24` 통합 검증 완료, 리드 push/PR·CI·기능 main 병합 대기 |

## 구현 경계와 재현 인터페이스

구현은 기존 source qualification을 재승인하지 않는 읽기 전용 스냅샷이다.
원 reader의 수락된 검증 계약과 네 가지 조회 view를 보존한다. 특히 기존 runtime
projection의 `verify_all()`은 수락 당시 status를 돌려주므로 upstream V3 전체를
새로 재검증했다는 주장은 하지 않는다. 리드의 원본 읽기 inventory/strace 대조는
실제로 읽은 의존 파일 누락 여부를 확인하는 별도 증거다. 새 snapshot의 읽기 승인은
기존 Raw·financial producer·release HOLD 권한을 확대하지 않는다.

외부 도구 `tools/export_screening_read_snapshot.py`는 **원소스 PYTHONPATH**로만
실행한다. config는 다음 필드를 요구한다.

- `source_root`: 원래 `src/sec_xbrl` 절대 경로, `source_revision`: 정확한 Git HEAD.
- `source_files`: 그 디렉터리의 모든 Python 파일 `{path,sha256}` 배열.
- `source_aux_files`: 원래 bridge 파일의 정확한 `{path,sha256}` 한 개.
- `artifact_files`: 전이 의존 manifest/receipt/blob/Parquet 등 전체 pin 배열.
- `exporter_sha256`: 동결된 외부 exporter 자체 SHA256.
- `catalog`: 기존 `screening-catalog-v1` envelope 파일 pin, `service_options`: 기존
  runtime_projections/cohort_unions/governed_deltas/batch_evidence의 명시 옵션 그대로.
- `dataset_ids`: export할 기존 logical dataset 목록. 실제 journal 경로는 받지 않는다.

```sh
PYTHONPATH="$ACCEPTED_SOURCE/src:$ACCEPTED_SOURCE" "$PYTHON" \
  "$CANDIDATE_SOURCE/tools/export_screening_read_snapshot.py" \
  --config "$EXPORT_CONFIG" --config-sha256 "$EXPORT_CONFIG_SHA256" \
  --destination "$NEW_SNAPSHOT_DIRECTORY"
```

내부 임시 journal만 만들고 원소스·bridge·artifact·catalog·exporter의 전후 pin과
원소스 HEAD/해당 소스 diff를 확인한 뒤에만 각 `verification.json`을 쓴다.
회사 파일은 작은 core와 전체 근거를 분리하고 hydration 시 원래 trace를 복원한다.
관측 ID가 없던 V1은 내부 저장 좌표만 사용하며 원래 행에 ID를 새로 쓰지 않는다.
전역 행 순서, V1/V2의 원래 explorer/quarterly 비지원 응답도 보존한다.

ROOT는 검증 receipt와 snapshot manifest의 정확한 SHA, 전체 logical SHA,
origin 전체, schema/reader version을 결속한 별도 승인 파일을 작성한다.
승인은 `screening-read-snapshot-root-approval-v1`, `authority: ROOT`, `approved: true`,
`reader_version`, `manifest_sha256`, `verification_sha256`, `logical_sha256`, `origin`의
정확한 객체다. ROOT 승인은 검증을 대체하지 않는다.

새 publisher config는 `{parent_root,parent,dataset_id}`이며 `parent`는
`manifest/verification/approval` 각각의 `{path,sha256}`다.

```sh
PYTHONPATH="$CANDIDATE_SOURCE/src:$CANDIDATE_SOURCE" "$PYTHON" \
  -m examples.screening.prepare_screening_changes \
  --config "$PREPARE_CONFIG" --config-sha256 "$PREPARE_CONFIG_SHA256" \
  --destination "$NEW_CHANGE_SNAPSHOT_DIRECTORY"
```

완료 시 새 manifest/verification과 외부 `*.coverage.json`을 생성한다. 목적지가
있으면 덮어쓰지 않는다. 새 Python 전체·producer·기존 v1/v2 엔진·exporter·bridge
inventory를 새 origin/publication에 묶고 전후 검사한다. 새 결과에도 ROOT의 별도
승인이 필요하다. 구 catalog는 그대로 두고 새 dataset 항목만 추가한다.

서버는 각 scope마다 아래 명시 옵션을 사용한다. `status`의 원래 필드와 원래
logical publication은 old snapshot에서 그대로이며 새 발행물은 별도 ID다.

```text
--read-snapshot DATASET_ID MANIFEST_PATH MANIFEST_SHA256 VERIFICATION_PATH VERIFICATION_SHA256 APPROVAL_PATH APPROVAL_SHA256
```

bridge에서 기존 매출 구성과 다른 상세 비교 보조자료를 유지하려면 기존
`--auxiliary-union` pin에 아래 **세 쌍**을 더한다. 새 publication의 정확한 부모
logical ID/pub/manifest SHA와 owner map이 기존 union과 다르면 거부한다.

```text
--prepared-changes-snapshot PATH --prepared-changes-snapshot-sha256 SHA256
--prepared-changes-verification PATH --prepared-changes-verification-sha256 SHA256
--prepared-changes-approval PATH --prepared-changes-approval-sha256 SHA256
```

이는 새 요청 scope를 기존 소유자에게 연결하는 읽기 relay이며 원 보조자료를
재계산하거나 source qualification을 완화하지 않는다. 기존 요청 scope도 유지한다.
준비된 27개는 공표 pair를 우선 사용하고 다른 항목은 원래 aux 가용성에 따른다.


## 자체 검증 후보 (2026-11-14)

- `node --test tests/screening/*.test.cjs`: **144 PASS**, 호스트 socket 허용 환경.
- `PYTHONPATH=src:. POLARS_MAX_THREADS=2 python -m pytest`에 아래 관련 파일을 지정:
  **145 PASS** (10.48초). `test_financial_growth.py`, `test_financial_comparison_v2.py`,
  `test_runtime_projection.py`, `test_screening_explorer.py`,
  `test_screening_quarterly_consumer.py`, `test_screening_http.py`,
  `test_read_snapshot.py`, `test_prepared_changes.py`.
- 마지막 monetary source-definition-version gate 회귀를 포함해
  `test_read_snapshot.py test_prepared_changes.py`: **28 PASS** (2.99초).
- `ruff check .`, JS/bridge syntax, `git diff --check`: PASS.
- 앞선 관련 Python sandbox 실행은 socket 4건이 EPERM으로 실패했으며 위 호스트
  재실행에서 모두 통과했다. 제품 실패로 분류하지 않는다.
- 전체 pytest는 최종 소규모 gate 수정 전 collection된 중간 후보여서 리드 지시에
  따라 중단했다. 중간 결과는 250 PASS/6 SKIP/1 FAIL이며 최종 전체 결과로 사용하지
  않는다. 실패는 `test_history_quarters_cached.py::test_default_history_build_connects_reported_and_derived_consumer`
  의 기존 `recovery unexpected or missing staged files/directories`이고 PR85의 별도
  범위다. 최종 동결 source 전체 검증은 독립 검증에서 수행한다.

합성 검사는 원 ID/정밀값/trace·support·status·기간 view와 V1/V2/V3 기능 경계의
동등성, ROOT/receipt/파일/전후 source pin 거부, 고정·보충 최신 분리, 부호 정책,
정확 %p·threshold·정의 버전, 새 catalog 등록→preview→저장→새 service 재열기→
trace, 기존 aux와 새 scope의 소유자 결속을 확인했다. 실제 원소스 export·ROOT 승인·
100개사 발행/old50 대조·복제 journal UAT·운영 인수는 아직 미수행이며 리드가 소유한다.


## 독립 검토 반환과 support 보정 (2026-11-14)

초기 후보 `d9afd87aa0`는 최신 view에만 유효한 비교가 있는 경우 fixed view만으로
support를 집계해 조건 등록을 막는 P2가 독립 검토에서 발견되어 동결을 해제했다.
`metric_support`/`quarter_support`는 이제 `view_support.fixed/latest`별 가용/관측
건수를 유지하고, aggregate는 같은 금융 기간 좌표를 중복 집계하지 않는다.
`execution_supported`는 어느 지원 view에서든 유효한 준비값이 있으면 true다.
고정 행을 최신 행으로 채우지 않으며 고정 관측 건수도 바꾸지 않는다.

연간 최신 anchor가 fixed 행만 읽던 한 줄도 리드 승인에 따라 latest 조회로
연결했다. `latest_rows`가 없는 기존 reader는 같은 fallback을 유지한다.
연간·분기 각각 fixed 2023/latest 2023+2024 합성 발행물에서 최신 YoY50의
조건 생성·평가는 PASS, fixed 2023은 UNDETERMINED임을 검사했다. 공통 기간의
fixed/latest 중복은 aggregate 한 건으로 집계한다. 회계 eligibility는 변경하지 않는다.

수정 후 관련 Python **150 PASS** (11.29초), Ruff/diff PASS. 기존 Node144
검사 대상 JS/bridge는 이 수정에서 바뀌지 않았다. exporter와 snapshot reader의
bytes도 초기 동결과 같아 기존 실제 read snapshot을 다시 export할 필요가 없다.
새 source/publication은 별도 재검토 대상이다.

리드는 기존 11개 원 publication의 네 view 전체 458,800개 조회 내용·계약 동등성
대조 후 원본 read snapshot만 별도로 수락했다. 이는 새 27개 정의의 실제 발행이나
운영 인수를 뜻하지 않으며 새 발행물/운영은 계속 HOLD다. 실제 원본·journal·
운영 서버는 writer가 변경하지 않았다.

## 실제 화면의 미준비 근거 보정 (2026-11-14)

`2070a27d7a` 이후 리드의 실제 새 발행물 화면 검사에서 첫 FY의 이전 기간이 없을 때
`delta: null` 또는 `current/prior.value: null`을 정확값 formatter에 전달해 보드가
중단되는 결함을 확인했다. 표시 함수만 null을 명시적 미준비로 처리하도록 수정했다.
0으로 바꾸지 않으며 존재하는 상태·사유·기간·관측 ID와 %/%p 입력 의미는 유지한다.
실제 형태의 all-null evidence와 첫 FY published pair를 포함한 전체 보드 render
회귀를 추가했고 전체 Node **146 PASS**, Ruff/diff PASS다. Python/producer/reader/
bridge 및 이미 준비된 실제 자료 bytes는 이 보정에서 바꾸지 않았다.

리드가 별도로 보고한 실제 자료 검증은 새 27조건×100개사 2,700판정 정확 대조
(683 PASS/428 FAIL/1,589 UNDETERMINED; FY2025/2026Q3), 기존 89 API 응답 동등,
기존 보조 비교 8,800 cell 동등, 부모 45,114개 고유 관측 보존이다. private journal의
기존 8항목 복원·삭제 및 기존 4결과 재열기, 신규 조건·결과 삭제/복원/재열기도
확인했다. 이는 리드의 복제본 검증이며 writer의 실제 journal 변경은 없다.
UI 보정의 독립 재검·리드 실제 화면 인수와 운영 전환은 별도 대기다.


## 최종 로컬·운영 인수 (2026-11-14)

리드는 최종 코드 `86b87d592cc1e2fcd5136e395ae4106af9038f81`과 financial
producer `2070a27d7aa41a651cee15d5906aae8803543b7d`를 로컬 인수했다.
이후 문서 전용 커밋은 이 코드/자료의 인수 근거를 기록하며 source SHA를 바꾸지 않는다.
위 이전의 대기·HOLD 문구는 당시 기록이며, 현재 상태는 이 절과 상태표가 정정한다.
원격 전달과 main 병합은 이번 새 기능의 요청 범위가 아니며 수행하지 않았다.

### 승인된 실제 발행물

- Dataset `universe100-prepared-changes-20261025`, publication
  `screening-prepared-changes-5fe69f578c5e9ce55a6978c2`, 재무 기준일 2026-10-25.
- 100개사, 연간 catalog 41개, 분기·TTM catalog 59개. 이는 정의 수이며 모든
  회사·모든 기간에 수치가 있다는 뜻은 아니다.
- Snapshot manifest SHA256
  `b82caa4c896da4098c23896dac2934dccbb33883c28b8b5efdcc8cdd03059845`.
- Logical publication manifest SHA256
  `9ce9153f336e9a9e68efa20a1b1e746540a6f838b85a60afd4341fe22abb2712`.
- 물리 경로는 `work/screening-prepared-changes-20261114/derived-v1`이며 기존 부모나
  구 publication을 덮어쓰지 않았다. 별도 ROOT read/발행 승인과 catalog/batch 증거를
  사용했다. 새 batch ready_at은 실제 준비 시점이며 재무 cutoff로 소급하지 않는다.

### 검증 결과와 한계

독립 Node **146 PASS**, 관련 Python **150 PASS**, Ruff/diff PASS다.
전체 pytest는 중단된 선택 검사로 **1,085 PASS/34 SKIP/2 FAIL**이며 전체 PASS를
주장하지 않는다. 두 실패는 별도 PR85의 기존 cached History inventory 실패와
환경의 arelle import 실패였다. 올바른 interpreter 환경으로 journal 재시작 검사
한 건을 재실행해 PASS했다. PR85 수정은 이번 코드에 포함하지 않았다.

리드의 실제 자료/소비 검증은 다음과 같다.

- 원래 11개 publication의 네 view **458,800행** 전체 내용·계약 동등성.
- 부모 **45,114개** 고유 관측 및 **90,187개** view 행, metadata/단위/입력 보존.
  신규 고유 관측은 AVAILABLE **5,593**, UNAVAILABLE **11,854**다.
- 기존 50개사 보조 비교 **8,800 cell** 동일; 기존 56 API와 최신 33 API 응답 동일.
- 새 27개 조건×100개사 **2,700판정** 정확 대조(FY2025/2026Q3):
  683 PASS/428 FAIL/1,589 UNDETERMINED. Decimal 5개 연산자 경계,
  AAPL OI 약 7.981…%의 GTE8 FAIL, 저장·재열기·CSV를 확인했다.
- WDC 최신 보충 분기의 4개 성장 조건은 PASS이며 고정 분기는 UNDETERMINED다.
  최신 수치를 고정 spine에 채워 넣지 않았다.
- Private journal에서 기존 휴지통 8항목 복원·삭제, 기존 4결과 동등성, 새 조건/
  결과 저장·삭제·복원·재열기 PASS. **실제 journal의 삭제/복원은 수행하지 않았다.**
- 실제 Chrome 1920px에서 연간·분기·TTM pair, 조건 추가와 조합 preview,
  매출 구성과 다른 상세 aux의 200 응답, page/console error 없음 확인.

위 값 대조는 명시된 입력·API·view/사례 범위다. SEC Raw 전체를 다시 파싱하거나
모든 보관 파일의 바이트를 재감사했다는 주장은 하지 않는다.

### 보존과 운영 locator

리드는 원 native 소스/자료와 운영 입력 **5,535 pin**의 동일성을 확인했다.
원래 journal SHA256은
`3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`로 같고,
version8/active0/trash8 및 history API baseline도 유지됐다.
실제 frontend는 18765/PID48956, backend는 19079/PID1463410이다.
원래 backend 19076/PID1428674와 원 bundle은 rollback용으로 유지했다.
PID는 인수 당시 식별자이며 자동 재사용 대상으로 해석하지 않는다.

프로젝트 상대 위치 `work/screening-prepared-changes-20261114` 아래의
`runtime-v1/live-backend.json`은 source SHA와 정확한 backend 시작 args,
`runtime-v1/read-declarations.json`, `catalog.json`, `batch-evidence.json`은
불변 파일 선언을 보존한다. Windows frontend의 exact args/이전 과정은 아래
visual evidence의 `live-switch.json`을 참조한다. 재시작 때 새로 publish/apply하지
않고 이 기록의 hash 검증된 기존 선언과 args를 사용한다. 실제 재시작/rollback은
프로세스 소유자 확인 후 리드가 수행하며 문서 갱신자가 실행하지 않는다.

### 증거와 재현

자료/API 증거는 프로젝트 상대 `work/screening-prepared-changes-20261114/evidence`의
`original-snapshot-equivalence-v1.json`, `new-publication-preservation-v1.json`,
`old-auxiliary-comparison-v1.json`, `legacy-api-after-v1.json`,
`legacy-latest-api-after-v1.json`, `all-conditions-api-v1.json`,
`new-conditions-api-v1.json`, `wdc-latest-versus-fixed-v1.json`에 있다.
독립 검사는 같은 폴더의 `prepared-independent-final-display-node.log`,
`prepared-independent-final-focused.log`, `prepared-independent-full.log`,
`prepared-independent-journal-recheck.log`에 결과와 중단 한계를 남겼다.

실제 화면/복제 이력/운영 증거의 공통 절대 위치는
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/screening-prepared-changes-20261114`다.
`verify-history.json`, `verify-ui.json`, `verify-live-ui.json`, `live-switch.json`이
각각 복제본 이력·private 화면·실제 화면·운영 전환의 근거다. 실제 1920px 화면은
`live-01-annual-published-conditions.png`, `live-02-screening-yoy-pp.png`에 있다.
리드는 검사 후 private 18885/19078/19077 프로세스를 종료하고 실제 18765/19079와
rollback 19076만 유지했다. 실제 화면 검사 뒤에도 원 journal SHA는 동일했다.

앞선 export/publish 명령은 새 목적지만 받는다. 이미 인수된 자료를 반복 발행하지
않고 재검할 때는 위 config/declarations와 검사 스크립트를 사용한다. 예를 들어
새 출력 보고서 경로를 지정하는 다음 검사는 원 입력을 읽기만 한다.

```sh
"$PYTHON" "$EVIDENCE/verify_new_publication.py" \
  "$ACCEPTED_PARENT_SNAPSHOT" "$ACCEPTED_CHANGE_SNAPSHOT" "$NEW_REPORT_JSON"
```

API/저장·복원 재현은 반드시 private 복제 journal/backend에서 수행하며 원래
journal에 검증용 기록을 쓰지 않는다. writer는 실제 발행·운영 작업을 하지 않았다.

### 지표별 준비 범위

아래는 `old-auxiliary-comparison-v1.json`의 **고정 view** coverage다.
기업 수는 100개 중 **하나 이상의 기간에** AVAILABLE이 있는 회사 수이며 해당 FY/
분기에서 그 모든 회사가 AVAILABLE이라는 뜻이 아니다. 최신 보충 view는 별도로
보존되며 실행 지원은 어느 지원 view에서든 유효한 값이 있는지로 판단한다.

| 지표 ID | 가용 기간이 있는 기업 | 가용 회사×기간 |
| --- | ---: | ---: |
| `operating_income_yoy` | 71 | 196 |
| `cfo_yoy` | 93 | 261 |
| `gross_margin_yoy_pp` | 42 | 118 |
| `operating_margin_yoy_pp` | 71 | 197 |
| `net_margin_yoy_pp` | 78 | 220 |
| `standardized_fcf_yoy` | 69 | 182 |
| `fcf_margin_yoy_pp` | 65 | 180 |
| `current_ratio_yoy_pp` | 94 | 266 |
| `liabilities_to_equity_yoy_pp` | 55 | 148 |
| `liabilities_to_assets_yoy_pp` | 64 | 179 |
| `quarter_cfo_yoy` | 96 | 302 |
| `quarter_current_ratio_yoy_pp` | 96 | 316 |
| `quarter_fcf_margin_yoy_pp` | 62 | 195 |
| `quarter_gross_margin_yoy_pp` | 42 | 137 |
| `quarter_liabilities_to_assets_yoy_pp` | 67 | 221 |
| `quarter_liabilities_to_equity_yoy_pp` | 59 | 195 |
| `quarter_net_margin_yoy_pp` | 74 | 229 |
| `quarter_operating_income_yoy` | 72 | 225 |
| `quarter_operating_margin_yoy_pp` | 67 | 207 |
| `quarter_standardized_fcf_yoy` | 71 | 209 |
| `ttm_cfo_yoy` | 87 | 288 |
| `ttm_fcf_margin_yoy_pp` | 53 | 178 |
| `ttm_gross_margin_yoy_pp` | 37 | 128 |
| `ttm_net_margin_yoy_pp` | 61 | 205 |
| `ttm_operating_income_yoy` | 64 | 208 |
| `ttm_operating_margin_yoy_pp` | 57 | 189 |
| `ttm_standardized_fcf_yoy` | 60 | 197 |
