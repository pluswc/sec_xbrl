# Q4 매출 구성 연결·비율 companion — 2026-11-14

## 승인·현재 상태

사용자는 AMD를 포함한 Q4 구성항목 누락 개선을 승인했다. 별도
`codex/revenue-q4-continuity` 작업 트리는 main `245a52bc44`에서 시작한다.
리드는 원본 불변·네 가지 grant 분리 설계를 승인했으며, 실제 연결의 ROOT 승인
파일은 source evidence 검토 뒤 별도로 작성한다. 후보 구현과 자체 검증을 완료했으며
독립 검증·실제 발행/화면 인수는 대기다. 원격 전달·main 병합은 수행하지 않았다.
기존 109 운영과 이력을 유지한다.

상위 계약은 delivery-workflow, analytical-data-model, layer-model, period-rules와
revenue-completeness-20261112다. 기존 Raw/T1/Analytical/canonical/매핑 검토 flag,
기존 reviewed/mechanical/core Q4 및 기존 보고 비율은 변경하지 않는다.

## 조사와 최소 구현

현재 asset `db71131a490b479278e49a4708a9518a321212df0efa3a09cffbf9cdbd53b231`와
companion `c8e3d9c50a00f12ebb15ee48813f9b66d5eabd2608de38dc535b58ca8789a8d1`을
정확한 baseline으로 사용한다. 원래 50사 부모 dataset manifest는
`afb910c063d461c6cfc9adb7f07a8be8bd9cc9db9adc04282810155acf730fc4`,
재무 cutoff는2026-10-25다. 현재109 범위에서의 보조자료 owner 연결은 그대로다.
기존 전체50 analysis를 다시 준비하지 않고, pinned baseline+T1/T2/원문 증거+
별도 ROOT review overlay를 소비하는 좁은 enrichment entrypoint를 만든다.
새 companion과 새 asset만 별도 목적지에 발행하며 원본을 덮어쓰지 않는다.

AMD FY2025 3개 segment는 연간/Q3의 동일한 2025 재편 표시 narrative가 확인된
연결 후보이다. FY source는 매핑 검토 중이며 Q3와 canonical epoch가 다르다.
DataCenterMember/DatacenterMember의 철자와 다른 동일 QName도 자동 연결하지
않는다. FY/YTD9의 실제 source Fact/filing/context와 full raw/canonical scope에
결속한 별도 승인으로만 파생한다. Gaming 제품은 FY segment=Gaming과 Q3
segment=ClientAndGaming이라는 scope 차이 때문에 별도 근거 없으면 HOLD한다.

현재 공시의 2024 comparative는 T1 `fiscal_year`가 공시 focus2025일 수 있다.
prior 선택은 실제 Context 기간·PRIOR_YEAR_COMPARABLE·공시 fiscal-calendar 증거와
명시적 기간 anchor로 검증한다. FY2024 원래 4segment 역사 셀을 소급 덮지 않는다.
필요하면 현재 연간+Q3의 2024 comparative로 comparison-only prior Q4를 만들고
별도 근거로 사용한다. 이는 한 공시의 same-filing 비율이라고 표시하지 않는다.

## 네 가지 권한

1. **금액 연결**: 정확한 FY/YTD9 endpoint 두 개, 실제 출력 Q4 기간, SAME/RENAMED
   full scope 관계, version/ROOT review/evidence pin. 원 flag를 false로 복제하거나
   원 canonical을 바꿔 기존 gate를 통과시키지 않는다. 새 scope-continuity ID다.
2. **projection/차트 연결**: 정확한 baseline row ID/epoch/quarter를 별도로 지정한다.
   금액 승인만으로 label을 합치거나 이전 epoch와 선을 연결하지 않는다.
3. **비중**: 같은 실제 Q4 기간과 호환 basis의 유일한 검증 부모를 명시한다.
   분모>0, 0<=분자<=분모, 기존 segment fixed scope/product fixed parent 정책을
   유지한다. 합계가 같다는 이유로 OperatingSegments qualifier의 부모를 연결
   매출로 자동 대체하지 않는다. 부모가 없으면 금액은 남기고 share만 보류한다.
4. **YoY**: 동일 full scope·호환 표시 기준의 current/prior Q4를 별도 지정한다.
   current>=0/prior>0이며 이전 재편에는 명시적 compatible comparative가 필요하다.
   새 four-leg 규칙과 연간/Q3 paired-filing 근거 및
   ARITHMETIC_ONLY_NOT_RECAST_VALIDATED를 남긴다. UI는
   `Q4 전년비 · 연간−9개월 계산`으로 기존 reported same-filing과 구분한다.

모든 입력은 동일 CIK, USD monetary standard revenue, finite/non-nil/reported,
cutoff 이하·non-amendment, 적격 FY/YTD9/실제 Q4 날짜와 연속성·품질·basis/recast
호환성을 충족해야 한다. 불명확/중복/경쟁 direct Q4, true split/merge/recast,
다른 scope/통화/기간, 분모0·음수는 fail closed한다. 유효 amount0/음수는 금액으로
보존하되 ratio eligibility와 분리한다. 연산은 UI 밖의 Decimal이며 정밀값/모든
입력 ID·source pin·규칙·실제 기간과 누락 사유를 보존한다.

## review 입력 제안

Overlay version은 `revenue-q4-continuity-review-v1`, authority ROOT,
status ROOT_APPROVED, financial_as_of와 정확한 baseline asset/companion pins를 가진다.
회사별 원 T1 관측 parquet/manifest와 필요한 axis/member maps·T2 관계·Raw 원문을
`{path,sha256}`로 등록한다. 개별 grant의 evidence ID는 그 파일의 locator/role 또는
원문 근거를 지목한다. Raw dimension signature는 QName이 아닌 filing concept ID다.
원 QName/namespace/label·역할은 source filing에 맞는 maps/관계/원문에서 확인한다.

금액 endpoint는 observation ID와 전체 원 관측 SHA256 및 원 scope 사본을 묶는다.
source scope에는 raw concept/dimensions, original canonical concept/dimensions,
concept/dimension mapping IDs/version, 원 review flag, filing/snapshot/Context/units를
포함한다. 입력을 고친 사본으로 승인하지 않는다. 실제 코드의 endpoint helper와
빈 review example/CLI를 후속 인계하며 리드가 실제 source pins/grants를 채운다.
금액·표시/선·share·YoY 배열은 독립적이다. grant가 없으면 이유를 남기고 해당
권한만 보류하며 불확실한 다른 회사/기간을 추정하지 않는다.

## 수락·증거 경계

작은 첫 slice는 기존224 Derived Q4의 명시 승인 비율과 AMD 확인3segment 금액
projection부터 진행한다. 현재 원본109/History/재무·비율 원형과 baseline 모든
기존 non-null 셀·계보·hierarchy/period를 비교한다. 새 전체 지원 수를 회사별
실제 가용으로 과장하지 않는다. 실제 원문 검토·overlay 승인·자료 발행·화면/
journal 보존은 리드가 수행하고 writer는 합성·명시 cached 회귀 후 source SHA를
동결한다. 독립 reviewer는 별도 읽기 전용 검증한다.

예정 tests: exact/renamed scope 승인·flag 불변·금액0/음수/작은 차이, duplicate와
wrong cutoff/unit/date/basis/quality, true reorg/scope차이, overlay/endpoint/evidence
변조·미승인·stale, fixed parent/0분모·범위초과 share, prior comparative의 focusFY와
실제기간 구분, four-leg YoY/누락, chart epoch 권한, 기존 reported/Derived224 불변,
source pin/CLI overwrite 거부, UI 근거/전년비 구분과 관련 Node/Python/Ruff 검사를
포함한다. 구현·독립 검증·실제 인수·main 병합 상태는 따로 갱신한다.

## 확정할 입력 형태·enrichment CLI

빈 제안 파일은 `examples/screening/revenue_q4_continuity_review.example.json`이다.
PROPOSED는 실행 권한이 아니며 실제 ROOT_APPROVED 파일의 SHA256을 CLI에서 별도
고정한다. `source_inventory`는 CIK별 기존 analysis/history/T1 manifest/관측과
concept/axis/member maps/T2 manifest pins의 JSON이다. 필요한 추가 Raw/T2 파일은
`evidence_files`의 ID별 `{path,sha256}`로 고정한다.

`analytics.revenue_q4_continuity.review_endpoint(row)`는 정확한 원 T1 행에서
`{observation_id,observation_sha256,scope}`를 만든다. scope에는 원 review flag와
full raw/canonical/mapping·filing/period/unit을 그대로 포함하며 권한을 주지 않는다.

- amount link: `{id,cik,relation,annual,ytd9,period,evidence}`. annual/ytd9는 위
  endpoint, relation은 SAME/RENAMED, period는 실제 output
  `{fiscal_year,fiscal_quarter,period_start,period_end}`다. source의 focus fiscal_year를
  comparison period로 덮어쓰지 않는다. evidence는 `{file_id,locator,assertion}` 배열이다.
- projection grant: `{amount_id,target,connect_previous,evidence}`. target은 정확한
  `{cik,group,row_id,mapping_epoch,fiscal_year,fiscal_quarter}`다. true 선 연결은
  별도 previous-period/cell ID가 결속된 근거가 필요하며 기본값은 false다.
- share grant: `{numerator,target,denominator,evidence}`. numerator는 새
  `{amount_id}` 또는 기존 `{derived_metric_id}`, denominator는 exact baseline
  total/component의 `{target,cell_id,cell_sha256}` 또는 새 `{amount_id}`다. 후자는
명시 projection이 있는 검증 부모에만 사용할 수 있다. target group=totals는 연결
  total이며 그것만으로 fixed scope에 대한 사용 권한이 생기지 않는다.
- YoY grant: `{current,prior,target,evidence}`. current/prior는 각각 새 amount ID
  또는 기존 Derived ID다. 실제 네 source와 별도 비교 가능한 scope/paired-filing
  근거를 모두 검증한다. comparison-only prior에는 projection grant가 필요 없다.

리드는 고정된 schema에 실제 source/evidence/grants를 채우며 unsupported grant를
추정해 통과시키지 않는다. 예정 CLI는 다음과 같다. 새 출력 두 파일만 쓰고 원
50사 analysis 재준비나 원자료 재발행을 수행하지 않는다.

```sh
PYTHONPATH=src python -m examples.screening.enrich_revenue_q4 \
  --review "$ROOT_REVIEW_JSON" --review-sha256 "$ROOT_REVIEW_SHA256" \
  --output "$NEW_REVENUE_ASSET_JSON" --derived-output "$NEW_CONTINUITY_COMPANION_JSON"
```


## 최초 구현·자체 검증 후보

`analytics/revenue_q4_continuity.py`는 원 endpoint와 ROOT의 SAME/RENAMED 관계를
따로 검증해 새 Derived ID를 만든다. 기존 `revenue_quarters.py`, core History/
quarterly policy와 원 `prepare_revenue_breakdowns.py` bytes는 바꾸지 않았다.
새 entrypoint `examples/screening/enrich_revenue_q4.py`는 회사별 원 T1 revenue만
순차로 읽고 exact axis/member maps로 source와 target 전체 scope를 대조한다.
SAME은 원 QName scope도 같아야 하고 RENAMED가 다른 axis를 허용하지 않는다.
ROOT raw HTML/T2/endpoint 검토 권한이 기존 source qualification을 확대하지 않는다.

원 baseline의 모든 기존 non-null 금액/status/ID/sources·non-null ratio,
행/epoch/hierarchy·연결 total·기간·연간 view를 비교해 변경되면 거부한다.
금액 차감은 입력 계수에 충분한 local Decimal precision을 확보하며 0/음수도
그대로 유지한다. 비율은 기존 `percentage_result`와 Decimal28 precision을
명시적으로 재사용해 caller context에 영향받지 않으며 UI에는 계산을 넣지 않는다.
비중의 두 source leg별 매출 QName/namespace/unit와 동일 filing의 원 concept ID/
snapshot을 검사하고, cross-filing denominator bridge는 승인하지 않는다.
연결 total은 원 source가 실제 undimensioned여야 한다. component 부모는 원
full axis/member가 exact target row와 맞아야 하고 공통 FY/YTD9 시작일, 실제
Q4 75–105일, 회사·basis·양의 분모를 따로 검사한다. 유효하지 않은 비율은
금액을 숨기지 않고 비율별 exclusion/hold reason으로 남긴다.

원본 context의 fiscal_year가 filing focus인 prior comparative는 별도로 처리한다.
comparison-only record를 과거 표에 projection하면 거부하며, 새 YoY metadata에
current/prior Q4 금액·실제 기간·4개 source Fact·paired scope/비교 정책을 보존한다.
새 Q4 셀의 선은 기본적으로 앞·뒤 모두 끊고 이전 cell ID의 명시 grant 없이는
같은 row/epoch라도 연결하지 않는다. UI는 table/heading/hover 모두 reported
same-filing과 새 paired-input 비교를 구분하고 과거 as-filed와 다를 수 있음을
알린다. 금액과 비율의 누락 사유는 각각이며 direct-only 문구를 새 비율에 적용하지 않는다.

별도 `hold_grants` 배열은 `{target,reason,evidence,source_observation_ids?}`다.
현재 허용 reason은 `Q4_SOURCE_TAG_PRESENTATION_CONFLICT`뿐이며 정확한 기존
Q4 null component에만 적용한다. 공개 문구는 **공시 태그와 표의 항목 불일치 ·
계산 보류**다. Root가 확인한 AMD2024 표/inline tag 충돌을 T1 오류로 단정하지
않고 원 Q3 등 기존 non-null 보고값은 그대로 둔다. 다른 scope/기간으로
진단을 전파하지 않으며 해당 기간의 generic gap보다 명시 충돌 사유가 우선한다.

실제 입력 권한은 리드의 `root-review-approved-v1.json`, SHA256
`af04df2e35a7deeee24ebdd6fb1ba4095ba7a4d37a2dba0eb1dbfed6ca69b9cd`다.
22 amount link(현재11/prior comparison-only11), 11 projection, 조건부 share216,
YoY17, 명시 hold3을 포함한다. 이 수는 **실제 발행/표시 가용 수가 아니다**.
리드 사전검토의 cross-concept share12는 승인된 concept bridge가 없으므로
적격성 gate에서 보류하는 것이 정상이며 이 파일을 writer가 수정하지 않았다.
승인 파일이나 실제 관측으로 writer가 발행·운영 검사를 실행하지 않았다.

자체 실행:

```sh
PYTHONPATH=src:. POLARS_MAX_THREADS=2 python -m pytest \
  tests/unit/test_revenue_quarters.py tests/unit/test_revenue_q4_continuity.py \
  tests/screening/test_revenue_breakdowns.py tests/screening/test_revenue_q4_enrichment.py -q
node --test tests/screening/*.test.cjs
ruff check .
git diff --check
```

Python **77 PASS** (0.11초), 전체 Node **151 PASS** (35.13초), Ruff/diff PASS다.
합성 검사는 원 flag·full scope 불변, exact endpoint/authority/파일 pin·overwrite,
금액0/음수·작은 차이, 고정 scope/다른 concept·filing/단위·날짜·다른 company,
prior 실제 기간과 focusFY·four-leg 호환/불일치, 금액/비율 독립 가용성,
진단 null 한정, unapproved chart edges, 기존 non-null 보존을 포함한다.
실제 준비·비율 전수 대조·기존224/원자료 보존·109 private/live UI 인수는 리드와
독립 검증이 별도로 수행한다. 아직 이를 PASS나 전체 회사 지원으로 주장하지 않는다.
