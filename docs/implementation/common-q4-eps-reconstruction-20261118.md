# 공통 Q4 EPS 구성 재구성 — 승인 계약, 2026-11-18

## 상태와 범위

ROOT가 2026-11-18 E0 구현을 승인했다. 기준은 `origin/main
b5d926ed029752702eddec00295676879f50bec9`, 브랜치는
`codex/common-q4-eps-reconstruction`이다. 단일 제품 작성자가 격리 worktree에서
구현한다. 현재 상태는 APPROVED / 구현 중이며 독립 검증, 로컬 인수, 운영 인수,
PR·CI·main 병합은 각각 별도 대기다. 작성자의 commit은 ROOT 최종 freeze 승인
후만 가능하다. network·수집·운영·push·PR은 ROOT 소유다.

허용 변경은 새 `metrics/q4_eps_reconstruction.py`, 필요에 따른
`metrics/{market_inputs,price_financial_inputs,reported_quarter_eps,
company_valuation_readiness,price_related}.py`,
`screening/price_metric_publication.py`, offline CLI, 관련 작은 fixture/tests,
이 문서와 계획 등록부다. AGENTS·지침·스킬·원 Raw·processed·SQLite·운영·assets를
수정하지 않는다. 연구 v3는 제품 적격 자료가 아니다.

## 회계 및 데이터 계약

이 경로는 [기간 계약](period-rules.md)의 단순 EPS/평균 차감 금지를 유지하면서,
별도 Derived Metrics의 구성 재구성과 검증 경로만 추가한다. Raw와 reported
관측은 그대로 둔다. 기본과 희석은 별도 측정값이다.

- `Q4_N = FY_N - 9M_N`; `Q4_W = (FY_W * FY_weight - 9M_W * 9M_weight) / Q4_weight`;
  `Q4_EPS = Q4_N / Q4_W`. EPS 자체의 FY−9M 차감, 기본 EPS의 희석 대체,
  순이익 태그/`EPS*WAVG`/태그 부재만으로 조정 0 승인은 금지한다.
- DAY는 실제 Context 일수와 공시된 기간 시간가중 보통주 분모 정의로 검증한다.
  명시 MONTH/EQUAL_QUARTER 공시는 그 방식의 증거를 사용한다. EPS 일치 결과로
  방식을 고르지 않는다.
- 분자는 explicit EPS reconciliation 또는 원문 정책과 complete adjustment bridge로
  common 귀속을 증명한다. class, split/recast, 전체 dimensions, unit, source vintage,
  공식 namespace와 개념 의미가 호환되어야 한다. 누락 필드는 unknown이다.
- 희석 누적 구성의 가산성은 일반 가정이 아니다. 직접 공시 Q4 분자·분모 표로 N/W를
  검산하거나, continuing control·분기 손실·잠재 주식 집합·treasury-stock·if-converted·
  participating adjustment 전체의 누적 가산성 bridge를 입증해야 한다. 없으면 HOLD다.
- 직접 보고 Q4 EPS가 있으면 직접값을 우선하며 재구성·오차 결과는 검증 근거로 남긴다.
- 원 decimals와 단위의 interval을 전파한다. 회계 basis가 먼저 증명된 경우 rounding
  compatible 구간을 허용한다. canonical point는 고정 Npoint/Wpoint다. reference에
  맞춰 point/weight/unit를 고르지 않는다. 불교집합은 FAIL이다.
- 같은 accession/semantic identity/unit의 duplicate만 decimals interval intersection과
  고정 precision 우선으로 해소하며 모든 원 fact refs를 보존한다. 충돌은 HOLD다.
- public known은 원 filed dates의 최댓값이고 ready는 실제 준비/승인 시각이다.
  11/18 현재 평가와 11/13 종가를 구분하며 역사 backfill을 하지 않는다.
- 기본 Q4는 artifact에서 조회 가능하다. 희석 qualified 값만 빈 current EPS 역할에
  추가하여 PER/EY/고정 band에 연결한다. 기존 9 FY·3 direct TTM/100 grants·저장·
  PR108 timeline은 보존한다. API/UI는 계산 정책을 갖지 않는다.

## Offline interface와 schema

`propose_q4_eps(config_pin)`은 모든 등록 CIK를 정렬해 pinned intake의 검증된
Layer 1 snapshot을 읽고 actual FY/9M/Q4 및 직접 Q4 구성/EPS를 발견한다.
`qualify_q4_eps(run_pin)`은 원 proposal을 재생성하고 global rule 및 후보별
원문 회계 증거를 확인한 뒤 후보·적격 Q4·TTM·HOLD/FAIL을 분리한다.
`verify_q4_eps(pin)`은 실제 준비 시각을 보존해 결과 전체를 재현한다.
`augment_q4_eps_ttm(pin)`은 새 bundle 사본의 빈 current EPS만 추가한다.
이 함수들은 network·운영 변경을 하지 않는다. CLI만 새 파일을 배타 생성한다.

Config `common-q4-eps-config-v1`:

```json
{"schema_version":"common-q4-eps-config-v1","registry":{"path":"/absolute/registry.json","sha256":"..."},"base_financial_bundle":{"path":"/absolute/bundle.json","sha256":"..."},"public_cutoff":"2026-11-13"}
```

Registry는 `companies:[{cik,ticker,intake:PIN}]`이며 기존 common manifest를 사용할 수
있다. Intake는 기존 `filings:[{filing,source_run}]`을 사용한다. optional
`official_components:PIN`은 아래의 별도 공식 table records를 제공한다.

Run `common-q4-eps-run-v1`는 `proposal`, `policy`, `accounting_evidence`,
`evaluation_decision`의 절대경로 SHA256 pins를 갖는다. Global policy는
`common-q4-eps-policy-v1`, `rule_version=common-q4-eps-components-v1`,
`reviewer=ROOT`, `status=APPROVED_GLOBAL_RULE`, `approved_at`이다.
Accounting evidence는 `common-q4-eps-accounting-evidence-v1`, `reviewer=ROOT`,
`status=REVIEWED_SOURCE_ACCOUNTING_EVIDENCE`, `reviewed_at`, `cases`다.
각 case는 `candidate_id`, 정렬된 `source_fact_keys`, `stock_class_id`,
`split_basis_id`, `financial_scope_id`, `weight_method`, `claims`를 갖는다.
각 claim은 `claim`, `citations:[{source_pin:PIN,xpath,expected_text}]`다. XML/HTML
XPath는 정확히 한 요소를 선택하며 공백 정규화한 전체 텍스트가 같아야 한다.
해당 회계 판단은 ROOT 책임이고 코드는 pinned 원문과 후보 귀속을 검증한다.

필수 claims는 `SAME_CLASS_SPLIT_RECAST_BASIS`, `COMPATIBLE_SOURCE_VINTAGE`,
`COMMON_NUMERATOR_ATTRIBUTION`이다. 누적 weighted 경로에는
`PERIOD_TIME_WEIGHTED_COMMON_SHARES`가 필요하고 비 DAY 방식에는
`EXPLICIT_WEIGHT_CONVENTION`이 추가된다. 희석 누적 경로에는
`CUMULATIVE_DILUTION_ADDITIVITY_PROVEN` 및 complete `dilution_bridge`가 필요하다.
직접 Q4 N/W 경로에는 `DIRECT_Q4_RECONCILIATION_COMPONENTS`가 필요하다.
bridge는 `continuing_control`, `quarter_loss`, `potential_share_population`,
`treasury_stock`, `if_converted`, `participating_adjustments` 각 claim의 citations로
원문에 귀속한다. 숫자 재현만으로 이 조건을 대신하지 않는다.

공식 table adapter의 `official_components` JSON은 `records` 배열을 갖는다.
각 record는 `source_record_id`, `cik`, `ticker`, `accession`, `form`, `filed_date`,
`report_date`, `start`, `end`(exclusive), `role`(`basic_eps`, `diluted_eps`,
`basic_numerator`, `diluted_numerator`, `basic_shares`, `diluted_shares`), `value`,
`decimals`, `unit`([numerator measures, denominator measures]), `dimensions`,
`source_pin`, `captured_at`, `source_document`, `source_url`,
`locator:{value_xpath,row_xpath,raw_cell_text,row_text,table_text_sha256,headers}`를 갖는다.
금액은 `scale`(정수 10 지수, 기본 0)을 적용하고 parentheses 음수를 지원한다.
원문 값·행·표 hash·headers를 확인하며 Raw XBRL identity는 생성하지 않는다.
별도 회계 case가 공시 측정 의미와 basis를 증명한다.

## 수락 검사

의미있는 network-free 검사는 양성 기본/희석·직접 구성·negative·손실·0분모,
반올림과 SHOP `.58/.57` 불일치, 동일/다른 accession duplicate, 공식 namespace,
unit/full dimension/vintage/class/split/참여/전환·잠재주식 bridge, mutation pin,
실제 ready time 경계, metadata-only 새 기업과 등록 순서 불변성을 포함한다.
작은 직접 Q4 실자료 회귀 및 ROOT가 준비한 실제 pinned 자료 replay는 합성 검사와
구분한다. 원본 보존·조회·사적 저장/재열기·운영 인수는 ROOT가 수행하고 독립 Sol은
동결 SHA를 읽기 전용으로 검증한다. 후보만 존재하거나 모두 부정이라는 사실로
전체 계열 구현/운영 완료를 주장하지 않는다.

## 자동 source grammar와 현재 평가 v2

`discover_accounting_evidence(proposal_pin, grammar_pin, source_catalog_pin)`은
회사 분기 없이 승인된 원문 패턴을 모든 후보에 적용한다. Catalog는
`documents:[{cik,accession,source_pin:PIN}]`이다. Grammar는
`common-q4-eps-evidence-grammar-v1`, `reviewer=ROOT`,
`status=APPROVED_GLOBAL_SOURCE_GRAMMAR`, `approved_at`, `rules`를 갖는다.
각 rule은 `rule_id`, `route`(`DIRECT_Q4_COMPONENTS` 또는
`CUMULATIVE_COMPONENT_RECONSTRUCTION`), `weight_method`,
`claims:[{claim,xpath,text_pattern}]`, optional `numerator_bridge`와
`dilution_bridge`의 항목별 `{xpath,text_pattern}`을 갖는다. Company selector와
숫자 목표 override는 허용되지 않는다. 모든 해당 source filing에 원문 pattern이
있어야 case를 생성하며 미지원/복수 pattern은 구체 HOLD다. Generated evidence는
원 grammar/catalog/proposal pins를 보존하고 qualify에서 다시 재현한다.
새 기업은 registry/intake/catalog metadata만 추가하면 같은 실행을 거친다.
공시 의미를 pattern으로 승인하는 회계 판단은 ROOT 책임이다.

Parent `NetIncomeLoss` fallback은 `numerator_bridge`의
`preferred_adjustments`, `participating_allocations`, `noncontrolling_interests`
각 citations가 있어야 한다. 부재 자체는 조정 0의 증거가 아니다.

TTM은 기존 승인 current grant만 사용한다. Case의
`TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE` claim 및 `ttm_source_fact_keys`가
실제 네 분기의 모든 원 fact keys와 정확히 같아야 한다. Grammar scanner는 이
keys와 원문 citations도 자동 작성한다. 승인 grant가 없는 기업은 별도 HOLD이며
등록만으로 grant를 새로 승인하지 않는다.

새 현재 정책은 `eps-current-evaluation-policy-v2`다. 기존 fields
`mode`, `decision`, `financial_inputs`, `price_batch`, `quote_session`,
`public_financial_information_cutoff`, `evaluation_as_of`, `evaluation_at`에
`derivations:{reported_quarter_derivation?:PIN,q4_component_derivation:PIN}`을
추가한다. ROOT receipt는 기존 `eps-current-evaluation-root-acceptance-v1`과
`APPROVED_FOR_EXACT_CURRENT_EVALUATION`을 쓴다. 기존 reported TTM은 원 artifact와
ready를 독립 검증해 재사용한다. 새 component artifact만 새 decision에 귀속하며
옛 artifact의 평가일/결정을 재작성하지 않는다. latest PER/EY/고정 band만
현재 평가로 제공하고 저장된 일별 history/timeline에는 현재 EPS를 역산하지 않는다.

CLI는 `examples/screening/prepare_q4_eps_reconstruction.py`의
`propose`, `discover-evidence`, `qualify`, `verify`, `augment`다. 공통
`--input /absolute/file --sha256 SHA`와 생성 작업의 `--output /new/path`를 사용한다.
`discover-evidence`에는 `--grammar`, `--grammar-sha256`, `--source-catalog`,
`--source-catalog-sha256`도 필요하다. `verify`는 새 파일을 만들지 않는다.

## 승인된 구현 보강 — E0 후속 판단

ROOT는 최초 승인 후 다음 최소 범위를 명시 승인했다. 기존 generic additive Q4
정책을 바꾸지 않고 `period-rules.md`와 `analytical-data-model.md`에 이 별도 경로의
연결 문단을 추가한다. `examples/screening/display-assets/app.js`의 typed EPS 명칭,
검산 구간, 직접/재구성 구분, 원 실제 준비 timestamp의 KST 형식 표시와 주요 보류
사유만 변경한다. 현재 승인 운영 UI의 나머지 기능은 ROOT가 exact preimage를
확인하여 보존한다. UI가 금융 값을 계산하거나 회계 정책을 선택하지 않는다.

Pattern의 `filing_scope`는 `COMPONENT_FILINGS`(기본, route의 실제 N/W 입력),
`ANNUAL_FILINGS`(FY 10-K), `QUARTERLY_FILINGS`(9M 10-Q),
`DIRECT_Q4_FILINGS`(직접 Q4 구성/EPS), `TTM_FILINGS` 중 하나다. 빈 scope는
통과가 아니고, 지정 scope의 **모든 filing**에서 해당 pattern이 있어야 한다.
Claims/bridge citations 합집합은 모든 route N/W source filing을 덮어야 한다.
Citation은 `cik`, `accession`, 원문 pin/XPath/text를 함께 보존한다. TTM basis
claim은 실제 네 분기의 source filing 전체도 덮어야 한다. 실패한 scope/pattern,
component availability와 계산 가능성 진단을 각각 남긴다. 미지원 pattern은
회계 정책의 자동 해석/매핑이 아직 검증되지 않았다는 뜻이며 Raw 부재 판정이 아니다.

최종 source review claim은 `SOURCE_REPORTING_BASIS_REVIEW_SUPPORTED`다. 이는
문서 구조·공시 정책의 좁은 검토를 지원한다는 뜻이며 모든 기업 행위의 부재 인증이
아니다. 실제 mandatory basis bridge의 `VERIFIED`와 분리한다. Quarter 결과도
`component_validation_status`, `source_equation_status`, `source_basis_status`를
각각 기록한다. 기본/희석 모두 visible source와 class/split/reporting basis gate를
통과하기 전에는 `QUALIFIED`가 아니다. 숫자 진단의 `accounting_qualified=false`는
명시적으로 남긴다. Current TTM에는 네 분기 전체에서 current grant까지의 추가
검증이 필요하다.

단순 NetIncomeLoss와 EPS 단어의 동시 출현은 common 분자의 증거가 아니다.
현재 좁은 구조 rule `SINGLE_COMMON_NI_BASIC_DILUTED_CLOSED_SECTION_V1`은 Net income
행부터 Basic EPS, Diluted EPS, weighted-average shares caption, Basic shares,
Diluted shares까지 완결된 행 순서를 요구한다. 중간/추가 참여증권 배분,
preferred/if-converted 분자 조정, 다른 numerator 행이 있으면 이 rule은 HOLD다.
Parent NI는 원 visible IX cell의 CIK·Context 실제 기간·값에 귀속해야 한다.
기존 표의 숫자/표시 일치만으로 조정 0을 추론하지 않는다. 직접 공식 Q4는 같은
완결 구조와 선택 cell의 논리적 column(원 colspan 포함)의 3개월·연도·종료일 header를
검증한다. FY column을 Q4라고 선언해 통과할 수 없다. Raw hidden/비표시 cell을
visible 원문으로 인정하지 않는다. 새로운 정당한 표 구조는 별도 global rule 검토가
필요하며 숫자가 맞는다는 이유로 이 closed grammar를 확대하지 않는다.

Config optional `basis_price_batch:PIN`, `source_catalog:PIN`,
`basis_normalizer_dependencies:{"__init__.py":PIN,"security.py":PIN,
"adapters/yahoo_price.py":PIN}`는 기존 승인 자료를 재사용한다. Supplier package의
`adapters/__init__.py`가 존재할 때는 그 pin도 필요하다. Normalizer 본체는 accepted
sidecar의 `input_pins.normalizer_source`다. Source/dependency bytes를 검증한 뒤 기존
supplier `normalize_yahoo_chart_capture`를 읽기 전용으로 사용하며 bytecode·수집·
supplier 변경을 하지 않는다. 정식 FASB/DEI URI의 `YYYY`와 `YYYY-MM-DD` 형식을
지원하고 prefix 문자열로 taxonomy를 판단하지 않는다.

원 batch/sidecar/manifest/checkpoint/raw gzip/decompressed hash·request horizon·
response symbol·거래소 시간대·reviewed actions를 연결한다. FY 시작부터 quote까지의
실제 가격 factor가 1이라는 검사는 보조이며 원 `events.splits`를 별도로 확인한다.
구간 첫날의 이벤트와 상쇄되는 이벤트도 제외하지 않는다. 구간에 영향을 주는
분할/역분할/미분류 후보는 HOLD다. 오래되어 구간에 영향을 주지 않는 후보만으로
최근 구간을 실패시키지는 않는다. 이 결론은 고정 캡처의 split-candidate 범위이며
모든 corporate action 부재 인증이 아니다. Source reporting recast는 별도 SEC 증거와
visible source context/value, class cover, comparative conflict gate가 필요하다.

모든 실제 사용 filing의 DEI Security12bTitle에서 단일 common equity 종류를
확인하고 같은 accession의 primary cover를 사용할 수 있다. 채권 Notes는 추가
보통주 class로 세지 않는다. CIK·정식 DEI namespace를 확인하며 preferred/Class A/B,
ADR/ordinary 등 이 rule에서 미지원인 종류는 HOLD다. Grant의 ID 접두사/접미사를
의미로 신뢰하지 않는다. 기존 ROOT typed-binding receipt→exact proposal의 actual
common-share declaration과 class/split/scope/anchor를 명시 결합한다. 같은 기간·unit·
전체 dimensions의 EPS, shares와 numerator comparative가 원 decimals 구간에서
충돌하면 HOLD다. Current grant 승인만으로 과거 네 분기의 기준을 승인하지 않는다.

`evaluation_decision.evaluation_timezone` 및 current v2 policy의 동일 필드는
기본 UTC이며 `Asia/Seoul`을 명시할 수 있다. 실제 준비/evaluation timestamp가 그
zone의 평가 날짜에 속하는지 검사한다. `ready_at`과 `ready_on`의 UTC 기록은 그대로
보존하고, UI는 KST 날짜·시간·timezone을 명시한다. KST 11/18과 UTC 11/17의 같은
실제 순간을 역산된 과거 준비로 바꾸지 않는다.

## Durable product projection과 성능 경계

전체 2,361 snapshot 검증은 source preparation이다. `propose`는 정책을 바꾸지 않고
CIK/filing 및 `(CIK,start,end,role,full dimensions)` index로 선택 후보를 좁힌다.
동일 selector의 list/index 결과는 byte 동일 검사로 대조한다. DOM cache는 8개로
제한하고 원 SHA/XPath/pattern 결과를 재사용한다. 공개 호출마다 실제 source bytes의
SHA256을 검증하며 호출 중 변조도 종료 전에 다시 확인한다. 캐시 반환은 독립 사본이다.

Cold 소비는 optional `run.source_projection_acceptance:PIN`을 쓸 수 있다.
`common-q4-eps-source-projection-acceptance-v1` receipt는 `reviewer=ROOT`,
`status=ACCEPTED_EXACT_PRODUCT_SOURCE_PROJECTION`, exact `proposal`/`config` pins,
`snapshot_inventory_sha256`, `producer`, `independent_verification`, `approved_at`을
갖는다. 독립 결과는 `status=PASS`, exact proposal pin,
`scope=PRODUCT_RAW_SOURCE_PROJECTION`이다. 새 producer는 원 source SHA stamp를
보존하고 receipt의 `producer={kind:EMBEDDED_PRODUCT_SOURCE_SHA256,sha256:...}`와
일치해야 한다. 초기 stamp 전 제품 추출만은 별도 독립 대조 후
`{kind:ROOT_ATTESTED_UNSTAMPED_PRODUCT_EXTRACTION}`으로 명시 수락할 수 있다.
연구 v3는 이 제품 projection이 아니며 그런 암묵 승격은 허용하지 않는다.

Receipt가 없으면 전체 source 재생을 한다. 수락된 product projection은 원 후보·
source facts의 durable input이다. Cold 실행도 실제 사용할 FY/9M/Q4/TTM의 모든
원 snapshot 8 tables, 공식 table/citation과 가격 basis closure의 full SHA를 검사한다.
선택되지 않은 이전 Raw를 전부 재추출하지 않는 것은 기존 publication 소비 경계와
같다. Source projection pin과 실제 선택 원천의 변조는 캐시로 우회할 수 없다.

Config의 `base_product_projection:PIN` + `base_projection_acceptance:PIN`은
수락된 이번 제품 추출의 Raw projection만 재사용한다. 동일 registry company/intake
pins는 재사용하고, 새 회사와 바뀐 intake는 그 회사만 전체 Raw 검증/추출한다.
새 official records는 현재 config에서 다시 원문 검증한다. 원 projection을 편집하거나
연구 cache를 반입하는 경로가 아니다. 불변 원 proposal pin을 결과에 보존하므로
HOLD/FAIL 결과에 198 MB의 components를 반복 복사할 필요가 없다. 결과의 availability,
source keys, numeric/source-review diagnostics로 원 proposal의 전체 근거를 조회한다.
소비자 근거는 해당 회사/candidate로 제한하며 전체 artifact pin은 유지한다.

## 공식 불일치 사례의 해석

ROOT의 2026-11-18 독립 원문 검색 판단은 다음과 같다. 아래 내용은 예외적 기업
계산 rule이 아니라 공통 gate의 양성/부정 회귀 근거다. 계산된 EPS를 공시값에
맞추려고 가중 방식/단위/point를 바꾸거나 일률적인 `±0.01`을 사용하지 않는다.

| 사례 | 확인된 유형과 제품 처리 |
| --- | --- |
| SHOP 2025 Q4 | Basic은 구간 호환이나 diluted 재구성 약 `.5760`과 보고 `.57`은 구간 불일치다. FY/9M convertible-note 희석 집합이 달라 누적 diluted 가산성을 승인하지 않는다. [FY](https://www.sec.gov/Archives/edgar/data/1594805/000159480526000007/shop-20251231.htm), [9M](https://www.sec.gov/Archives/edgar/data/1594805/000159480525000089/shop-20250930.htm). |
| MELI 2023 Q4 | 직접 Q4 NI 165m, basic W 50,631,669, diluted W 50,697,515와 EPS 3.26/3.25가 있다. 누적 if-converted 분자·분모의 비가산성과 직접 구성 경로를 구분하며 후자는 source basis bridge를 별도로 요구한다. [FY](https://www.sec.gov/Archives/edgar/data/1099590/000109959024000008/meli-20231231.htm), [9M](https://www.sec.gov/Archives/edgar/data/1099590/000109959023000033/meli-20230930.htm). |
| XEL 2021 Q4 | Visible 공식 release의 `.58`, NI315m, diluted W542m은 잔여 구성 구간과 호환한다. 기존 hidden `.54`는 stale prior-year 후보와 충돌한다. Raw를 고치지 않고 visible source/period identity가 없는 비교값을 적격 reference로 쓰지 않는다. [공식 release](https://www.sec.gov/Archives/edgar/data/1123852/000007290322000007/xcelearningsreleaseq42021.htm). |
| ISRG 2020 Q4 | Hidden pre-split EPS와 post-split 재작성 shares를 섞으면 안 된다. 2021 three-for-one split을 근거로 basis 충돌을 보류하며 임의 환산하지 않는다. [2021 FY](https://www.sec.gov/Archives/edgar/data/1035267/000103526722000014/isrg-20211231.htm). |
| DUK/GE | Participating/preferred/common 배분 또는 visible/hidden/recast 충돌은 complete bridge가 필요하다. 검색만으로 모든 수치 불일치가 정량 설명되었다고 주장하지 않는다. 미해결은 HOLD다. |
| AMZN 2025 Q4 | 공식 직접 NI21192m, basic W10709m, diluted W10863m와 EPS1.98/1.95 및 완결 EPS 계산표가 양성 source pattern을 제공한다. 회계 증거와 source-to-current basis bridge는 추가 필수다. 원 layout에서 추린 2.8KB table fixture는 column/period/precision과 allocation 삽입 부정을 CI에서 검사한다. [공식 표](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000002/amzn-20251231xex991.htm). |
| ADBE/CAT | Common 분자 계산이 있어도 performance-conditioned awards 때문에 누적 diluted 가산성을 가정하지 않는다. Basic/직접 구성 경로를 별도로 평가한다. |

회계 기준이 먼저 증명된 뒤 원 decimals 전파 구간의 호환은 허용한다. 유일한 표시값으로
좁히지 않으며 고정 재구성 point와 전체 interval을 보존한다. 직접 Q4 EPS가 있으면
그 보고값을 선택하고 N/W point는 별도 검산으로 남긴다. 서로 닿기만 하는 불확실한
반올림 경계는 호환 증명으로 사용하지 않는다.

## Prepared basic/diluted 조회

`PriceMetricReader.q4_eps(cik, flavor=None)`는 현재 publication이 pin한 Q4 artifact의
해당 회사/basic/diluted 결과·보류·원 projection/derivation pins만 읽는다. 원문/Raw를
재파싱하거나 계산/회계 검증을 실행하지 않는다. 이전 publication에 새 artifact가
없으면 `COMMON_Q4_EPS_ARTIFACT_NOT_PUBLISHED`를 반환한다. CLI의
`query --input /absolute/price_metric_manifest.json --sha256 SHA --cik CIK
[--flavor basic|diluted]`는 같은 prepared 조회 결과를 JSON stdout으로 내보낸다.
`--output /new/file.json`을 주면 배타 생성한다. Producer 검증을 우회하는 임의
artifact query 경로와 새 API route는 추가하지 않는다.

Cold producer/검증은 위 source closure를 확인하지만 이미 인수된 publication을 읽는
조회 worker는 기존 governed publication pin 경계로 충분하다. 매 조회를 Raw 회계
재판정으로 바꾸지 않는다. 최초 artifact replay 이후 같은 process의 캐시는 실제
선택 원천/정책/evidence/가격 basis pins를 다시 full SHA 확인하고 작은 결과만 사본으로
반환한다. 공개 반환값의 변경은 내부 검증 cache와 다음 조회를 오염시키지 않는다.

Local Q4와 current TTM 조건을 구분하기 위해
`TTM_WINDOW_COMMON_CLASS_SPLIT_SCOPE` pattern의 `TTM_FILINGS` scope에만
`optional_if_scope_empty:true`를 허용한다. 완전한 current 네 분기 scope가 없으면
그 claim을 생성하지 않고 local Q4 검증을 계속한다. Scope가 있으면 모든 filing의
pattern 일치가 필수이며 불일치는 HOLD다. 다른 source/basis/adjustment claim의
empty scope를 optional로 만드는 것은 금지한다. TTM 소비자는 claim과 정확한 네
분기 source keys 및 전체 basis bridge를 계속 요구한다.

Metric registry와 v1 definitions/policy는 기존 bytes를 유지한다. 새 source admission은
별도 `common-q4-eps-components-v1`/current evaluation v2로 관리한다. 새 typed source를
사용한 PER/EY 및 fixed PER band에만 `eps_input_admission_policy_version`을 명시하고
현재 평가 metadata에도 추가 admission policy version을 남긴다. 기존 저장 definition,
이전 보고 관측과 old timeline을 새 정책으로 재해석하지 않는다.

새 `GOVERNED_Q4_COMPONENT_TTM`은 실제 준비일 이후 날짜라도 명시적인 검증된 현재
평가가 없으면 `CURRENT_Q4_EPS_EVALUATION_REQUIRED`다. `ready_on <= price date`만으로
당시 준비가 인증된 역사 입력이 되지 않는다. 새 EPS의 PER/EY historical_ready와
backtest_eligible는 항상 false이며 현재 평가 v2에서만 계산을 허용한다. 기존 FY와
이전 direct TTM 동작은 보존한다. 역사 인증이 필요하면 미래의 별도 승인 정책으로
다룬다.

## 구현 후보·작성자 검증 및 실제 자료 준비 결과

2026-11-18 ROOT는 위 보강을 포함한 소스와 작은 회귀 fixture의 commit/freeze를
승인했다. 본 문서와 함께 전달하는 구현 commit이 후보이며 독립 최종 검증, 로컬/
운영 인수, PR·CI·main 병합은 이 기록 시점 각각 별도 대기다. 작성자는 network 수집,
운영 교체, push 또는 PR을 수행하지 않았다.

작성자 최종 관련 검사:

```bash
PYTHONPATH=src /home/plusbdw/user_work/projects/sec_xbrl/.venv/bin/pytest -q \
  tests/screening/test_q4_eps_reconstruction.py \
  tests/screening/test_reported_quarter_eps.py \
  tests/screening/test_price_related_metrics.py \
  tests/screening/test_company_valuation_readiness.py \
  tests/screening/test_price_timeline.py \
  tests/screening/test_price_metric_publication.py \
  tests/screening/test_market_inputs.py
node tests/screening/screening_price_metrics.test.cjs
```

Python은 **145 PASS / 1 SKIP**(새 40 + 기존 105), Node는 **25 PASS**다. 변경된
Python/CLI/tests의 Ruff, app.js syntax와 `git diff --check`도 PASS다. 기존
`definitions()` 소스는 main과 byte 동일하며 SHA256은
`77b1ba599d8879ae73cc0d2f23bb2eeec2a7f1f7e5ad5c0a550baf6da37b7e61`이다.

전체 `pytest -q`는 PASS가 아니다. 최초 전체 실행에서 여러 실패를 관찰한 후
중단하고 `--maxfail=1`로 범위를 줄여 첫 실패를 재현했다. Candidate는
`test_history_quarters_cached.py::test_default_history_build_connects_reported_and_derived_consumer`
에서 1 FAIL / 5 PASS / 1 SKIP(42.24s)이었고, history recovery가
`history.py:2117`에서 `recovery unexpected or missing staged files/directories`를
발생시켰다. 변경하지 않은 main `b5d926ed`의 tracked archive를 `/tmp`에 추출해 같은
cached NVDA 테스트를 재실행해 **동일 실패**(10.16s)를 확인했다. `history.py`와
그 test는 candidate/main byte 동일하다. ROOT는 이를 기존 로컬 cached-fixture
recovery 불일치로 수용했고 이번 범위에서 수정하지 않았다. 전체 CI PASS 전에는
병합하지 않는다. 관찰된 trace 발췌·정확 명령·동일 source hash 기록은 선택적
`/tmp/common-q4-eps-writer-baseline-failure-20261118.txt`에 남겼다. 이 파일은 전체
stdout capture라고 주장하지 않는다.

ROOT가 실제 기존 109 회사/2,361 snapshots와 공식 표를 준비했다. 최종 v4 후보
`qualified-q4-eps-v4.json` SHA256은
`f88ec8a9aa3542f1b246d45a3c5687ac10c12bfd2257eac6a86e53cd893a2b72`다.
6,928 quarter 결과 중 **4 QUALIFIED / 6,924 HOLD**이며 AMZN 2024 기본1.90·희석1.86,
2025 기본1.98·희석1.95가 모두 직접 공시 우선이다. N/W 재구성 point/interval은 별도
검산 진단으로 남는다. 새 current TTM은 AMZN **12.37 한 건**이다. 이 결과는 기존
연구의 numeric candidates를 회계 적격으로 승격한 것이 아니며 나머지 HOLD는
source pattern/회계/입력/basis 등 구체 사유를 보존한다.

ROOT는 새 financial bundle SHA256
`f7a8d283a09d8dcb887214d087d01ff1acd09604a699e10f0e5723cbc188e214`에서 기존 observations
전체 exact 보존 + 새 AMZN 한 행과 해당 회사의 기존 빈 EPS grant 한 곳만 변경됨을
확인했다. 기존 PER12회사에서 13회사로의 연결은 **후보 목표**이며 실제 조회·운영
인수는 이 기록 시점 아직 ROOT 대기다. Writer의 합성/작은 실제 fixture PASS와
ROOT의 실자료 준비, 독립 검증, 최종 운영 수락을 합치지 않는다.
