# Q4 매출 구성 연결·비율 companion — 2026-11-14

## 승인·현재 상태

사용자는 AMD를 포함한 Q4 구성항목 누락 개선을 승인했다. 별도
`codex/revenue-q4-continuity` 작업 트리는 main `245a52bc44`에서 시작한다.
상태는 **IMPLEMENTED / INDEPENDENTLY_VERIFIED / LOCALLY_ACCEPTED / OPERATING**다.
최종 인수 판단과 실제 발행·운영 검증은 ROOT가 수행했다. 금융 소스는
`76e475f0be29ef11449256e6d88efbd468c459b1`, 최종 시장 소비자 통합 소스는
`7b6cb45f815b3c75e1406aec8e5060db8ca26ca3`로 구분한다. 문서 전용 후속
커밋은 이 코드 동결을 바꾸지 않는다. 독립 Python 86개·Node 159개와 Ruff/diff,
독립 실제 data-v2 검증이 PASS다. main 기준은 `245a52bc44`이며 원격 push/PR은
요청되지 않았고 수행하지 않았다. main 병합도 수행하지 않았다.

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

## 별도 승인: 공시 부문 총매출의 fixed-scope 동등성

최초 후보 `0eb4b536a4` 동결 뒤 리드와 별도 reviewer가 AMD2025 두 원문 segment
표의 명시적 parent 구조를 추가 확인했다. 연간 f-512/c-1과 Q3 f-460/c-1은 동일한
3부문 아래 Total net revenue를 명시하며 All Other는 매출이 아닌 미배분 비용/
credit 영역이다. 이는 합계 일치만으로 한 추론이 아니라 원문 parent 관계의 별도
판단이다. 원 OperatingSegments qualifier와 무차원 총계 source는 그대로 둔다.

share grant의 선택형 `denominator_relation: DISCLOSED_FIXED_SCOPE_TOTAL_EQUIVALENCE`와
`denominator_source_fact_ids: [FY총계FactID,YTD9총계FactID]`를 추가 승인했다.
정확한 segments target의 StatementBusinessSegmentsAxis+OperatingSegmentsMember
qualifier, 기존 total target/cell ID/hash, 두 개의 서로 다른 원문 pin과 locator,
두 parent FactID 순서가 모두 필요하다. 여전히 같은 Q4 실제 기간/CIK/basis,
paired filing별 원 매출 concept/namespace/unit, 양의 분모와 분자 범위를 검증한다.
이 grant가 없거나 FactID/원문이 부족하면 fixed-scope 거부는 그대로다.
다른 제품·지역·scope에 대한 자동 consolidated fallback을 허용하지 않는다.

공개 denominator enum은 `DISCLOSED_FIXED_SCOPE_TOTAL`, 표시명은 **공시 부문 총매출**이다.
기존 `FIXED_SCOPE_REPORTED`/같은 공시 보고 부모와 구분하고 chart denominator
identity에도 범위를 유지한다. 금액 승인이나 source QName만으로 이 권한이 생기지 않는다.

리드의 별도 입력 `root-review-approved-v2.json` SHA256은
`a61d3f2ff61ac992e8ae8e62d46ef8f14b981eac431dfdb1c52a6bb80d79c86f`다.
v1을 보존하고 정확한 AMD3 share grant만 추가했다(조건부 share219; 나머지
22 amount/11 projection/17 YoY/hold3 동일). v1 3개사 scope 승인과 기존12개
cross-concept share 보류는 이 추가 승인과 별개의 판단이며 여전히 유지한다.
승인 수를 실제 표시 수로 주장하지 않는다. ROOT가 source 독립 검증 후 새 경로에
발행하고 별도 자료 검증·운영 인수를 수행한다. Writer는 실제 입력을 실행하지 않았다.

후속 자체 검사: Python **81 PASS** (0.11초), 전체 Node **152 PASS** (35.13초),
Ruff/diff PASS. 명시 관계 승인/누락, 잘못된 parent Fact, 원문 한 개의 부정 fixture와
별도 공개 분모/hover 범위 검사를 포함한다. 원본 core·legacy revenue policy는 불변이다.

## 독립 검토 P1 반환과 실제 loader 경로 보정

`bfe3effd1b`의 독립 검토에서 `_load_sources`가 계산한 name map을 반환하지 않고
관측 목록만 반환해 `publish()`의 tuple unpack이 실패하는 P1을 확인했다.
초기 publisher fixture는 loader를 대체해 이 결함을 검출하지 못했다. 실제 발행은
아직 실행되지 않았으며 원 자료/운영에 영향은 없었다.

반환 형식과 annotation을 `(observations, scope_names)`로 고쳤다. 추가 회귀는
loader를 대체하지 않고 임시 관측·axis/member/concept Parquet와 정확한 inventory/
manifest/evidence pins를 통해 `publish()`의 새 asset·companion 출력까지 실행한다.
디스크 관측을 변조하면 새 출력 설치 전에 거부하는 것도 확인한다. 합성 파일만
사용했고 실제 ROOT 승인 입력으로 발행하거나 원파일을 수정하지 않았다.

수정 후 관련 Python **82 PASS** (0.15초), 전체 Node **152 PASS** (35.13초),
Ruff/diff PASS다. 추가 blocker가 없다는 독립 검토 반환을 수신했으며, 이 수정
SHA 자체의 독립 재검은 별도로 필요하다. Source/schema/회계 grant의 의미나
실제 승인 v2의 bytes는 바꾸지 않았다.

2026-11-14 추가 검증 후보: 빈 fixed scope와 미지정 scope를 동일하게 처리하고, 고정 범위의 분모는 부모의 전체 축·구성원 및 원문 입력과 정확 대조한다. 신규 비중은 `FIXED_SCOPE_Q4`(같은 Q4 공시 범위의 매출)로 구분한다. 선택 기간에 빈 선택 항목과 미선택 준비 항목이 함께 있으면 `이 기간의 준비 항목 보기` 버튼을 제공한다. 사용자 클릭 전 선택은 불변이며 명시적인 클릭 후에는 해당 기간에 준비된 항목 최대 8개로 선택을 교체한다. 관련 Python 86개 통과; 새 소스 독립 검증 및 실제 v2 발행·운영 인수는 대기 중이다. 기존 published-v1 및 ROOT 승인 v2는 변경하지 않았다.

이 수정 후보 자체 검증: 관련 Python 86개, 전체 Node 154개, Ruff 및 diff 검사 통과. 실제 v2 발행과 새 소스의 독립 검증은 아직 수행 전이다.

### 2026-11-14 기존 운영 시장 입력 소비자 통합

리드의 운영 전환 guard가 예상 PID와 다른 시장 입력 운영 프로세스를 확인하여
전환 전에 중단했다. 이 작업은 프로세스나 기존 자료를 덮어쓰지 않았다.
별도 승인된 `d6df9aa147`의 시장 입력 기능 중 `app.js`, `app.css`,
`windows-loopback-bridge.cjs`, 시장 입력 Node 소비자 테스트만 기준
`245a52bc44`와의 차이를 3-way 적용하여 Q4 UI와 함께 보존한다.
시장 producer Python이나 src 코드는 가져오지 않는다. Q4 금융 Python과 실제
published-v2의 구현 source pins는 불변이며 재발행하지 않는다.

기존 시장 profile 입력(SHA
`271100cca9f27802088ea4bd262fa73bd9e8635248234c8d348f5831c0bd32f6`)
및 `--market-inputs`/`--market-inputs-sha256`의 읽기 전용 소비 기능을
재사용한다. 시장 값 계산·수집·발행 권한을 추가하지 않는다. 이 통합 소스의
독립 검증과 새 운영 인수는 대기 중이며 실제 프로세스 전환은 리드가 수행한다.

통합 후보 자체 검증: 전체 Node **159 PASS**(기존 Q4 154개와 시장 소비자
5개), Ruff/diff PASS. `git diff 76e475f0be -- '*.py'`는 공백이다.
기존 Python 86개 검증의 금융 구현 bytes를 유지하며 실제 자료를 재발행하거나
시장 producer를 이 브랜치에 추가하지 않았다. 새 통합 SHA의 독립 검증과 운영
인수는 별도 단계다.

## 최종 실제 자료·운영 인수 — 2026-11-14

아래 결과는 ROOT의 `local-live-acceptance.json`을 기록한 것이다. writer는 실제
자료 발행·운영 전환·원 journal 쓰기를 실행하지 않았다. 앞 절의 초기 P1,
false HOLD, 후보 대기 문구는 당시 단계의 기록이며 최종 상태는 이 절을 따른다.

- ROOT 승인 v3 SHA: `2b3a3b857d41df3378822890f09224483e0133b7e5606aca30d410b16b3ebde2`.
  22 amount links / 11 projections / 221 conditional shares / 17 YoY / 3 holds.
  특수 공시 총매출 관계는 AMD 3개와 별도 원문 검토한 NVDA 2개만 명시 승인했다.
  AMD 권한을 NVDA나 다른 범위에 자동 전파하지 않았다.
- 실제 published-v2 asset SHA:
  `e75142559ce27b4a2b0eb6e12d0fa541317e81b32e60bab6b0ea2e524ef56636`.
  companion SHA:
  `2a57efd64ebe62e3a50b0d07f559b2d341baf0f53196a2da0034756358cf52c9`.
- 원 50사 annual/totals, 기존 quarterly component 3,228개 금액 및 4,910개 비율의
  값·계보와 408개 입력 pins를 보존했다. 새 금액 11개(AMD 4/AAPL 5/NVDA 2),
  share 209개, YoY 17개를 검증했다. 28사에 비율이 준비되었으며 모든 회사·기간의
  완전한 구성을 뜻하지 않는다. 새 22개 레코드 중 11개 prior comparison-only는
  과거 표시 셀에 투영하지 않았다. AMD 2024 진단 3개와 cross-concept share
  12개의 보류를 유지했다. 원 Raw/T1 및 기존 공시 수치는 바꾸지 않았다.
- 실제 UI 1920/1440에서 AMD Q4·2024 태그 충돌 안내, AAPL/NVDA의 명시적 준비
  항목 선택 버튼, KO의 짧은 분모 캡션과 전체 title/aria를 검증했다. JS 오류와
  가로 넘침은 0이다. 기존 시장 4개 API payload가 정확히 같고 MSFT 가격 524.51,
  EPS 17.95, 표시 날짜 26.10.23, 주식 수 확장 및 고정 기간 숨김도 PASS다.
- live frontend `18765` PID `40460`에서 기존 backend `19078`을 그대로 소비한다.
  datasets 14 / companies 109 / history version 8 / trash 8을 보존했고 실제 GUI
  검증 뒤 원 SQLite SHA를 다시 확인했다:
  `3443d40b615a8208343102f26f38c46b1f611a423534a606fd9cd9497567b96c`.
  Q4 금융 Python 133개 구현 pins와 시장 profile SHA
  `271100cca9f27802088ea4bd262fa73bd9e8635248234c8d348f5831c0bd32f6`는 불변이다.
  시장 소비자 보존은 새 가격 producer 승인이나 가격 재계산을 의미하지 않는다.

증거 기준 디렉터리는
`/mnt/c/Users/plusbdw/.codex/visualizations/2026/11/08/01a1bb67-6275-70d2-989e-208966314006/revenue-q4-continuity-20261114`다.
`local-live-acceptance.json`, `live-ui.json`, `live-market.json`,
`ko-fixed-parent.json` 및 source 작업 상위의 `actual-publication-acceptance.json`과
published-v2를 함께 참조한다. `live-switch.json`과 `original-process.json`은
시장 기능을 포함한 이전 PID 58984의 args를 보존한 현재 롤백 locator다.
`original-process-initial109.json`은 stale PID 23088 guard 이전의 역사 자료이며
현재 롤백 명령으로 쓰지 않는다. guard는 프로세스 중단 전에 안전하게 멈췄다.
잘못된 CLI SHA placeholder는 pin 검사에서 출력 0개로 거부된 운영자 입력 실수로
`operator-bad-sha.stderr`에 보존했고 제품 결함으로 분류하지 않는다.
작업용 private frontend들은 ROOT가 종료했다. 기존 backend·원 자료·store 쓰기는
없었으며 이 보존 확인을 전체 Raw 아카이브 재검증으로 확대 해석하지 않는다.

## 원격 전달 승인 — 2026-11-14

사용자가 이 Q4 개선의 push와 PR 생성을 승인했다. ROOT fetch 확인 시
origin/main은 `245a52bc44`로 추가 변경이 없고, 이 브랜치는 뒤처진 커밋 없이
7개 커밋 앞서 있어 별도 main 통합이나 충돌 해결이 필요하지 않았다.
시장 소비자를 포함한 제품 bytes는 기존 실제 운영 인수 소스와 같으며 자료,
store, runtime을 재발행하거나 변경하지 않는다. 기존 금융 소스 `76e475f0be`,
소비자 `7b6cb45f81`, 독립 data-v2 및 실제 live 인수 근거를 그대로 재사용한다.
이 문서 갱신은 원격 전달 상태만 바꾼다. 앞 절의 미요청 문구는 당시 기록이다.
원격 push·PR 생성·CI 확인은 ROOT 실행 대기이며 main 병합은 요청되지 않았다.
