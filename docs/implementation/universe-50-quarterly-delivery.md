# 50 issuer 연차·분기 생산자 전달 계약

## 1. 승인과 현재 단계

기준일은 **2026-10-10 KST**다. 사용자는 “둘 다 진행”으로 다음 목표를 승인했다.

1. 기존 21사의 critical systemic mapping·대표값 선택·reason propagation 문제를 먼저
   안정화한다.
2. 지원 가능한 unique issuer를 50개까지 넓히고, 최근 완료 FY 4개를 표시하기 위해
   다섯 번째 완료 annual baseline을 predecessor 입력으로 함께 수집한다.
3. cutoff까지 최근 완료 calendar-quarter-end bucket 8개를 준비하되, reported quarter,
   cumulative YTD, governed derived quarter를 분리한다.

이 계약 작성과 metadata·Filing Discovery 계획, 아래 M0 bounded correction 구현은
**APPROVED**다. M0 source `7eb721cb018ee3723c66fa2801a9836c48d2e0bb`와 새 21사 annual
metric/dataset publication은 독립 검증을 통과해 2026-10-10 KST에 lead가
**LOCALLY_ACCEPTED**했다. 현재 상태는
**FIRST_FIVE_FINANCIAL_BUILD_AND_QUARTER_PRODUCER_APPROVED**다. 동등한 메모리 최적화와
5개 입력 FY/4개 표시 FY 분리는 source·golden·RSS gate를 통과했다. 이제 고정된 runtime에서
첫 5사를 직렬 build하고, 별도 writer checkout에서 분기 producer를 구현한다. 이후 50사
확대와 actual 분기 publication은 각각 별도 immutable artifact gate를 통과해야 한다. 문서의
수락 조건은 이 절에 적은 범위를 넘는 회계 정책이나 UI 구현을 자동 승인하지 않는다.

기준 소스는 `1e2733c61d4c21617c658093137957369af29b8b`이며 기존 actual 21사 Raw,
history, R3 financial publication과 사용자 journal은 읽기 전용이다. 회사 설명 기능의
provider 권리 gate와 이 작업은 무관하며 Investing.com 본문 취득은 계속 비활성이다.
이번 브랜치는 producer 전용이다. `src/sec_xbrl/screening/ui.py`, `service.py`, `server.py`,
`store.py`, `dataset*`, `cli.py`는 별도 consumer 작성자 소유이며 수정하지 않는다.

### 1.1 승인된 M0 correction과 진단 근거

읽기 전용 진단은 `/tmp/universe50-quarterly-diagnosis/diagnosis-report.json`에 보존됐고
SHA-256은 `50a473931920f1ef8d6b5a21e5ac7a4ee7aea367bf336d78bc7f143cb71b8e56`다.
진단은 cached JSON과 제한된 Parquet 조회만 사용했으며 SEC network, Arelle 재실행,
원본 수정이나 정책 release를 하지 않았다. 다음 네 correction만 승인됐다.

1. **공식 historical FASB namespace 연속성.** `http(s)://fasb.org/us-gaap/YYYY`와
   유효한 `http(s)://fasb.org/us-gaap/YYYY-MM-DD`를 공식 annual release 형태로
   인식한다. 두 concept의 `STANDARD`, taxonomy family, local name, data type, period type,
   balance, abstract fingerprint가 기존 규칙대로 모두 맞아야 한다. Raw namespace와 Raw ID는
   바꾸지 않고 새 mapping publication에서만 continuity를 표현한다. lookalike host/path,
   custom concept, 유효하지 않은 달력일, type·period·balance·abstract 변화는 거부한다.
2. **typed primary-statement 우선 선택.** exact company, source filing, actual period, USD,
   full dimension scope를 먼저 맞춘 후보 중 revenue·operating income·net income·gross
   profit은 primary IS, CFO는 primary CF, assets는 primary BS evidence가 있는 후보만
   대표값 자격을 갖는다. panel이 선언한 CIK, selection view, as-of와 실제 start/end 또는
   instant까지 모든 후보를 먼저 검증한다. 후보 하나만 맞아 보여도 다른 후보의 filing,
   기간, unit 또는 dimension scope가 불완전·불일치하면 우선 선택하지 않는다. 자격 후보가
   하나면 그 existing reported fact를 선택하되 모든 후보와 채택·탈락 evidence를 lineage에
   남긴다.
3. **revenue-only reported total.** typed primary revenue 후보가 여러 개이면, 같은 primary
   IS role의 CAL에서 `us-gaap:Revenues`가 competing revenue child와 다른 reported component의
   parent이고 모든 edge weight가 `+1`, measurement scope가 같으며 reported parent 금액과
   child 합계가 exact Decimal 또는 기존 CAL tolerance로 일치할 때만 이미 보고된 parent
   fact를 선택한다. competing revenue child 외에 같은 role·scope의 별도 reported component가
   최소 하나 더 있어야 한다. 합계는 ambient Decimal context와 무관한 정수 계수 정렬로
   정확히 계산한다. WMT FY2025의 `680985000000 = 674538000000 + 6447000000`이 positive
   control이다. 합계를 새로 만들지 않고, 이 규칙을 net income·cost·custom concept·label·
   order·issuer 예외로 일반화하지 않는다.
4. **reason과 candidate lineage 보존.** 해결되지 않은 경우 source
   `MULTIPLE_CANDIDATES`와 전체 후보/evidence가 analysis에서 metric publication까지
   유지돼야 한다. 실제로 안전한 복수 후보가 경쟁할 때만 `MULTIPLE_CANDIDATES`를 쓰며,
   단일 부적격 후보는 `MAPPING_REVIEW_REQUIRED` 같은 원래 eligibility reason을 유지한다.
   이를 `INPUT_NOT_REPORTED`, missing unit 또는 period 오류로 바꾸지 않는다.
   CAT FY2024·FY2025 cost 항목 두 cell은 별도 evidence가 없으므로 계속 hold이며 core 수락을 위해
   강제로 채우지 않는다.

필수 regression은 historical AAPL FY2022 revenue·gross-profit continuity, COST·TSLA의
unique primary IS 후보, WMT의 reported CAL parent, CAL footing·role·weight·scope 실패,
revenue 외 항목의 비적용, unresolved candidate reason 전파를 포함한다. 새 21사 source,
analysis, metric publication은 기존 파일을 덮지 않는 destination에 작성하고 mapping과
대표값 선택을 독립적으로 재확인한다.
새 mapping rule version은 `l2-m2-company-canonical-v4`, expanded annual core selector는
`annual-core-primary-statement-v2`다. 기존 publication과 그 안의 v3 mapping은 변경하지
않으며 새 publication lineage가 적용 rule version을 명시한다. 새 history build의
`Layer2RuleVersions.mapping_version`도 canonical 모듈의 동일한 active version을 직접
사용한다. 따라서 v3 history root를 v4 결과로 재사용하지 않고 새 root에서 다른 run
fingerprint와 manifest rule metadata를 생성한다. period·recast·selection rule version은
이번 correction으로 바꾸지 않는다. completed history와 일부 T1–T4만 있는 partial root도
active input/rule fingerprint를 모든 write 전에 확인하며, 불일치하면 기존 파일을 바꾸지
않고 새 destination을 요구한다.

첫 source 후보 `c1d808f3b386deffb6d4b705b7d099d7fc784370`은 위 scope 선검증,
CAL 구성·정밀도, 단일 부적격 reason, completed/partial history 재사용 경계가 부족해 독립
검증에서 **FAIL**했다. 보고서 SHA-256은
`4df4d59100175f110250a19499edc1678db495239f560fe2b82b8c05478ea7ce`다. 그 코드로 먼저
생성된 WMT·AMD·AAPL과 중단된 MSFT 출력은 `NOT_ACCEPTED_CANDIDATE`이며 후속 수락 결과로
재사용하지 않는다.

### 1.2 M0 통과와 다음 producer checkpoint

수정 source `7eb721cb018ee3723c66fa2801a9836c48d2e0bb`의 독립 source 검증 보고서 SHA-256은
`82be077d222381be100201d3847d22c73b39aecb9fa5b5a31dbec3bbfad6fa06`다. 새 root에서
생성한 21사·31정의·651 support·2,604 observation의 독립 artifact 검증 보고서 SHA-256은
`2eac15e40fc0b7da85feb62bc4539dc710a5bfb110991fafde5d569ac4a29d4e`다. 기존과 새
publication에서 함께 AVAILABLE인 1,864개 값·scope·Fact는 바뀌지 않았고, 160개가 승인된
mapping/대표값 규칙으로 회복됐으며, DE operating income FY2022–2024와 AVGO net income
FY2024 네 칸은 typed primary-statement evidence 부족으로 보수적으로 hold됐다.

다음 source checkpoint는 두 변경만 먼저 구현한다.

1. `publish_quarter_history`가 모든 view·period table의 중첩 lineage를 한꺼번에 Python
   object로 유지하지 않도록 얇은 additive derivation index와 table-at-a-time staging을
   사용한다. 모든 row, cell, candidate, trace, source input, network evidence, 순서와
   manifest count/hash는 그대로 보존하고 실제 읽은 각 입력의 hash/count 검증도 생략하지
   않는다. CAT의 accepted 7eb publication 전체 canonical table/derived records와 비교하고
   peak RSS를 측정한다. 목표는 5FY CAT build를 32GiB 장비에서 안전하게 실행하는 것이며
   `20GiB 이하`는 목표이지 사전 약속이 아니다. writer 후보 실측에서는 CAT의 10개 table,
   30개 dataset, 198개 derived record가 전부 동일했고 peak RSS가 30,621,104KB에서
   15,342,152KB로, wall time이 861.06초에서 515.25초로 줄었다. 이 결과는
   `/tmp/universe50-memory-cat-golden.json`(SHA-256
   `cb57989bc13b9471873028405ad70e7aaf11bb62ec5f07afbbbb7a11fea3ded9`)의 writer
   checkpoint에서 확인됐다. 최종 source `d3783f5cc6a2cd2cdf2b7e39933c689e7f444900`은
   metadata merge precedence correction까지 포함해 독립 검증을 통과했다. 보고서
   `/tmp/universe50-d378-independent/d3783f5-report.json`의 SHA-256은
   `f461ed4951db9b2556b3fd9fff06f8a645c83d281ba2e253de75ed229ec55819`다.
2. annual metric config는 선택적으로 `input_years`와 `display_years`를 선언한다. 5개 완료
   FY를 입력으로 읽어 가장 오래된 표시 FY의 YoY predecessor로 쓸 수 있지만 publication은
   최신 4개 display FY만 노출한다. predecessor는 input lineage에 남고 별도 표시 observation을
   만들지 않는다. 짧은 history는 가능한 집합과 `PARTIAL_HISTORY`를 유지한다. 기존 필드만
   가진 config는 기존 결과와 byte-equivalent여야 한다.

## 2. 불변 입력과 새 run 경계

재실행 가능한 새 run identity는 `universe-50-quarterly-20261010`으로 제안한다.
운영 산출물은 Git 밖의 다음 새 root 아래에서만 생성한다.

| 용도 | 새 root |
| --- | --- |
| SEC submissions·package·index cache | `data/raw/universe_runs/20261010_universe50_quarterly/` |
| metadata·discovery plan·intake·status | `data/processed/universe_runs/20261010_universe50_quarterly/` |
| 향후 history·quarter publication | 위 processed root의 별도 immutable `analysis_history/`, `quarterly/` destination |

기존 `20261008_initial`, `20261008_sec_transform_v5`, screening R3 및 journal 파일은
복사·수정·삭제하지 않는다. 새 manifest는 외부 입력 경로, SHA-256, observed time,
financial cutoff, source/runtime rule version을 고정한다. 같은 publication/run identity에
다른 config나 plan을 쓰지 않고 append-only attempt와 새 destination을 사용한다. 10-K/A와
10-Q/A는 원본 accession과 함께 보존하며 이전 filing이나 Raw snapshot을 덮지 않는다.

SEC network 단계는 이미 설정된 진실한 `SEC_USER_AGENT`만 runtime에서 읽고 manifest,
명령, 로그에 그 값을 기록하지 않는다. 모든 process와 machine을 합친 요청 속도는
초기 **2 requests/s 이하**다. cache hit를 우선하며 실패는 missing disclosure나 0으로
바꾸지 않는다.

## 3. issuer/security와 50 목표

50은 ticker 행 수가 아니라 검증된 **unique issuer CIK** 목표다. issuer와 security
(ticker, share class, exchange)는 분리한다. 같은 issuer의 여러 share class가 issuer
수를 늘리지 않으며 ticker 연속성만으로 CIK succession을 결합하지 않는다.

기존 21사에 [종목 확보 계획의 29개 후보](../planning/company-universe-acquisition-plan.md#4-50사-후보-구성)를
더한다. 2026-10-08 cached SEC candidate inventory는 29 ticker 모두를 29 unique CIK와
NYSE/Nasdaq association으로 관찰했지만 전부 `CANDIDATE_ONLY`이며 SIC와 지원 form,
ordinary-security eligibility는 아직 확인하지 않았다. 해당 source는
`company_tickers_exchange.json`, observed at `2026-10-08T01:32:29.603469Z`, SHA-256
`e0033204d27cbf7149023b2e94432b2c90735fe9c4743ae4f156fd82843bcb3c`다.

특히 cached XOM 행은 `CIK 0002115436 / ExxonMobil Holdings Corp`지만 기존 filing
history는 `CIK 0000034088 / EXXON MOBIL CORP`에 있다. SEC entity identity, security
registration, effective succession과 historical filing ownership을 별도 evidence로
확정하기 전에는 `IDENTITY_HOLD`다. 과거 history를 새 CIK로 이어 붙이지 않는다.
XOM은 `IDENTITY_HOLD_SUCCESSION_REVIEW`로 남는다. SEC CIK 연결과 cached current-security
evidence, 5개 10-K baseline/17개 10-Q plan을 별도로 검증한
`COP / CIK 0001163165 / CONOCOPHILLIPS / NYSE`를 lead가 50사 cohort의 대체 issuer로
승인했다. 이는 membership 승인이고 US-GAAP/USD financial readiness 승인은 아니다.
따라서 최종 50사는 기존 21사에 TXN, ADI, AMAT, LRCX, KLAC, IBM, ORCL, CRM, ADBE, INTU,
CSCO, HD, LOW, NKE, PEP, MCD, GE, HON, UPS, UNP, JNJ, MRK, ABBV, ABT, CVX, NEE, DUK, LIN,
COP를 더한다. XOM hold와 제외 근거는 지우지 않는다.

각 후보는 다음 상태 중 정확히 하나를 갖는다.

- `ELIGIBLE`: 정확한 issuer/security 연결, 지원 10-K/10-Q, US-GAAP/USD 범위와 source가 확인됨
- `IDENTITY_HOLD`: succession, alias, share class 또는 CIK conflict 미해결
- `SCOPE_HOLD`: form/taxonomy/currency/기간 지원 여부 미확인
- `EXCLUDED_WITH_REASON`: ETF·fund·warrant·preferred·OTC 또는 현재 미지원 20-F/40-F 등

unknown과 제외 후보도 metadata snapshot에 남긴다. 50이라는 숫자를 맞추기 위해
eligibility나 회계 규칙을 약화하지 않는다.

## 4. 수집·표시 기간 계약

### 4.1 Annual

회사별 immutable plan은 cutoff `2026-10-10` 이전 제출만 허용하고 다음을 구분한다.

- `completed_fiscal_years=5`: 최신 완료 10-K baseline 5개와 그 범위에 속하는 10-Q,
  10-K/A, 10-Q/A를 Raw/history 입력으로 선택한다.
- `analytical_fiscal_years=4`: 사용자·screening 연차 표시는 최신 완료 FY 4개다.
- 다섯 번째 FY는 4년 growth window의 predecessor 입력이며 기본 결과 열을 하나 늘리는
  값이 아니다. 짧은 history·IPO는 가능한 범위를 보존하고 `PARTIAL_HISTORY`로 표시한다.
- 새 metric producer는 `input_years` 전체에서 reported/derived 입력을 검증한 뒤
  `display_years` 좌표만 publication한다. 두 집합은 company별 manifest/config와
  publication identity에 포함되며 `display_years`는 `input_years`의 ordered subset이어야
  한다. consumer가 predecessor를 다시 선택하거나 계산하지 않는다.

기존 trailing selector는 요청한 5개 10-K와 그보다 앞선 annual의 report date를 exclusive
window boundary로 사용한다. 즉 selector가 말하는 별도 boundary predecessor와, 이번
분석이 요구하는 “표시 4개에 대한 다섯 번째 입력 FY”를 혼동하지 않는다.

### 4.2 Quarterly

cutoff 시점의 최근 완료 calendar-quarter-end bucket은 `2024Q4`부터 `2026Q3`까지 8개다.
bucket은 검색·coverage 좌표일 뿐 회사 fiscal quarter의 회계적 동일성을 선언하지 않는다.
각 observation은 실제 fiscal year/quarter, context start와 exclusive end, filing/report date,
52/53-week·calendar-change signal을 그대로 가진다. 한 bucket에 실제 회사 기간이 없거나
cutoff까지 filing되지 않았으면 `NO_FILING_AS_OF_CUTOFF`이며 최신 값으로 대체하지 않는다.
한 회사에서 한 bucket에 여러 actual fiscal ends가 생기면 자동 선택하지 않고 conflict로
남긴다.

8개 bucket을 재현하기 위해 직접 QTD, YTD-6M, YTD-9M, annual FY, 필요한 이전 QTD와
year-end instant를 함께 수집할 수 있다. 그러나 출력은 다음을 섞지 않는다.

| 종류 | 의미 |
| --- | --- |
| `REPORTED_QTD` | filing에서 직접 보고된 호환 QTD observation |
| `REPORTED_YTD` | 6M·9M 등 누적 observation; quarter 값처럼 표시하지 않음 |
| `DERIVED_QTD` | 기존 승인된 additive 정책으로 materialize한 quarter; formula와 모든 입력 lineage 유지 |
| `INSTANT` | actual instant와 FY-end anchor가 확인된 잔액; duration subtraction 금지 |
| `UNAVAILABLE` | 누락·ambiguous·mapping/recast/basis/period conflict 이유 보존 |

기존 M8/core-quarter 규칙의 Q4=`FY−YTD_9M`, Q3=`YTD_9M−YTD_6M`,
Q2=`YTD_6M−Q1_QTD`는 exact canonical identity, full dimensions, unit, basis, actual fiscal
start, source filing/as-of, endpoint와 additive allowlist가 모두 호환될 때만 재사용한다.
direct reported quarter가 우선하고 failed direct selection을 subtraction으로 덮지 않는다.
EPS, margin, ratio, average, denominator unit, unreviewed custom/recast 범위에는 적용하지 않는다.

quarterly QoQ·YoY·margin·standardized FCF와 TTM은 producer-owned Derived Metrics다.
reported/M8-derived QTD 입력의 exact unit, full dimensions, actual period, source filing,
selection view/as-of와 basis가 호환될 때만 계산하며 missing은 missing으로 남긴다. TTM은
4개의 연속된 eligible QTD, 동일 company/metric/unit/dimensions/view/as-of와 같은 non-null
`basis_version`이 모두 있어야 하고 FY+YTD fallback을 쓰지 않는다. generic input contract와
consumer 검증은 이후 함께 고정됐다. 수락된 consumer source는
`bccd2ea12886c3fc8e479a5d85edb22647ddf7ec`이며 독립 보고서 SHA-256은
`da2b90402fd69831b13a91b718d86897f1cdf4cce63b2c12bf3bad5f93686cdf`다. 이 수락은
serialization/source-scope 검증에 대한 것이며 actual 분기 금액이나 50사 publication을
수락한 것은 아니다.

wire contract는 `quarterly-screening-metric-manifest-v1`과
`quarter_metric_definitions.json`, `quarter_metric_support.json`,
`quarter_metric_observations.json`, `quarter_period_inventory.json` 네 payload다. actual row와
모든 source anchor는 CIK, canonical metric ID, `AS_FILED|LATEST_REPORTED`, as-of, full
dimensions, quality status/reasons/blocking, filing/Fact/context/QName/namespace/unit/period를
명시하며 상위 row에서 누락 scope를 상속하지 않는다. derived 의미는 `source_kind`,
`derivation_rule_version`, `basis_version`, `ARITHMETIC_ONLY_NOT_RECAST_VALIDATED`로 표현하고
recast view를 만들지 않는다. TTM definition은 `input_metric_id`를 명시한다. synthetic v5
wire manifest SHA-256은
`84e652322e570f4768c278fa924aaf6c1de98f1158be0d162b9be0a488fa359a`이며 실제 financial
수락 증거가 아니다. v1–v3 wire는 coherence 결함으로 실패했고 v4는 생략 scope가 있는
schema-only 역사다. actual producer는 11개 prepared core
(`quarter_revenue`, `quarter_gross_profit`, `quarter_operating_income`,
`quarter_net_income`, `quarter_cfo`, `quarter_capex`, `quarter_assets`, `quarter_cash`,
`quarter_liabilities`, `quarter_current_assets`, `quarter_current_liabilities`), generic 5개
(`quarter_revenue_qoq`, `quarter_revenue_yoy`, `quarter_gross_margin`,
`quarter_operating_margin`, `quarter_standardized_fcf`), `ttm_revenue`를 총 17개 definition으로
고정한다. unsupported input은 definition을 없애지 않고 8개 fixed spine의 `UNAVAILABLE`과
정확한 reason으로 남긴다.

generic quarter derived definition은 `input_contract.version =
quarter-derived-input-scope-v1`을 쓰고 `kind`를
`SAME_PERIOD_DIFFERENCE`, `SAME_PERIOD_RATIO`,
`ADJACENT_FISCAL_QUARTER_GROWTH`, `SAME_FISCAL_QUARTER_YOY_GROWTH` 중 하나로 선언한다.
`inputs`는 `{input_role, metric_id, value_constraint}`이며 FCF는
`CFO/FINITE`, `CAPEX/NONNEGATIVE`, margin은 `NUMERATOR/FINITE`,
`DENOMINATOR/POSITIVE`, QoQ·YoY는 `CURRENT/NONNEGATIVE`, `PRIOR/POSITIVE`다.
ratio·growth만 `denominator_policy=STRICTLY_POSITIVE`를 쓰고, definition의
`basis_policy=ARITHMETIC_ONLY_NOT_RECAST_VALIDATED`와 observation lineage의
`compatibility_policy`가 정확히 같아야 한다. input은 완전한 `REPORTED` 또는
`DERIVED_QUARTER` observation과 중첩 lineage이며 역할을 명시한다. consumer는 scope·부호·
lineage만 검증하고 공식을 재계산하지 않는다. QTD percent output은 기존 R1처럼 이미
100을 곱한 decimal string과 `unit_kind=PERCENT`, `unit=PERCENT`를 사용한다.
INSTANT는 `period_start=null`, exclusive `period_end`, `duration_days=null`이며 raw
`context_instant_date`를 lineage에 보존한다. standardized metric ID와 issuer별
`company_canonical_concept_id`를 분리하고 성장 입력의 issuer canonical identity가
호환돼야 한다. source anchor에 `structural_version` 또는 `recast_version`이 있으면 모든
입력과 output 선언이 충돌하지 않아야 하며, 누락을 review-clear로 해석하지 않는다.

## 5. 최초 지표와 품질 gate

최초 quarterly core flow 후보는 existing governed profile이 지원하는 revenue,
operating income, net income, CFO다. balance-sheet는 assets, liabilities, equity, cash 등
기존 정책이 exact year/quarter-end instant로 선택할 수 있는 입력만 제공한다. gross
profit, FCF, debt, margin 등은 이미 승인된 정의와 필요한 입력이 모두 있는 경우에만
별도 Derived Metrics publication에서 다룬다. 이름·label similarity나 ticker별 예외로
canonical identity를 만들지 않는다.

상태는 서로 독립적이다.

- `RAW_READY`: plan의 모든 accession에 검증된 atomic Layer 1 snapshot이 있음
- `ANNUAL_READY`: 표시 4 FY와 predecessor 입력의 가능한 범위·이유가 publication에 있음
- `QUARTER_INPUT_READY`: 8 bucket coverage와 QTD/YTD/FY/instant 입력 상태가 완전하게 설명됨
- `QUARTER_ANALYSIS_READY`: reported/derived/unavailable가 승인 정책으로 materialize됨
- `COMPARABILITY_REVIEW`: mapping·basis·fiscal-calendar conflict가 남음

full Raw 성공을 metric availability나 전체 `READY`로 대신 쓰지 않는다. M0가 확인한
critical systemic mapping, representative-value selection 또는 reason propagation blocker는
별도 승인된 scoped repair와 새 immutable publication, 독립 재검증을 거쳐야 한다.
진짜 미공시·비적용·cutoff 미제출은 reasoned missing으로 남을 수 있다.

## 6. 첫 5사 identity·discovery pilot

재무 parse/build 전의 첫 pilot은 `TXN`, `HD`, `JNJ`, `CVX`, `NEE`다. 기술·소비·
헬스케어·에너지·유틸리티를 한 회사씩 포함해 fiscal calendar와 filing count 차이를
측정하되 sector 대표성이나 매수 추천을 뜻하지 않는다. cached observation은 다음을
제공한다.

| ticker | cached CIK | exchange | 현재 상태 |
| --- | --- | --- | --- |
| TXN | `0000097476` | Nasdaq | `CANDIDATE_ONLY` |
| HD | `0000354950` | NYSE | `CANDIDATE_ONLY` |
| JNJ | `0000200406` | NYSE | `CANDIDATE_ONLY` |
| CVX | `0000093410` | NYSE | `CANDIDATE_ONLY` |
| NEE | `0000753308` | NYSE | `CANDIDATE_ONLY` |

pilot는 0.5초 이상의 shared request interval로 submissions root와 referenced historical
pages를 새 raw root에 content-addressed 저장한다. 그 캐시를 offline Filing Discovery에
넘겨 회사별 5 FY plan을 만들고 다음만 측정한다: exact CIK/ticker/name/SIC/form,
selected 10-K/10-Q/amendment 수, 5 baseline 충족 여부, 8 bucket input coverage와 hold 이유.
package download, Arelle parse, history/metric build는 이 pilot 단계에서 하지 않는다.

### 6.1 최초 operational discovery 결과

같은 날 0.5초 request interval의 기존 `SECSubmissionsClient`와
`CompanySubmissionsCollector`로 5사 root·historical submissions snapshot 14개를 새 raw
root에 저장한 뒤 network-free `discover_history(..., recent_fiscal_years=5)`를 실행했다.
결과는
`data/processed/universe_runs/20261010_universe50_quarterly/pilot_discovery/pilot_discovery_summary.json`
에 있으며 SHA-256은
`d75b672c18c2664149169fd2d36861d1cf73d8481f0e37fa7d9500f6370e4b58`다.

- 5/5 configured CIK, ticker, SEC name이 root submissions와 일치했고 SIC는 각각
  TXN 3674, HD 5211, JNJ 2834, CVX 2911, NEE 4911로 관찰됐다. security type의 최종
  eligibility는 여전히 `PENDING_SECURITY_TYPE_VALIDATION`이며 NEE root가 common ticker와
  여러 preferred ticker를 함께 선언한다는 사실을 보존했다.
- 회사별 정확히 5개 10-K baseline, 전체 25개 baseline과 111개 selected filing을
  계획했다. form 합계는 10-K 25, 10-Q 85, CVX 10-Q/A 1이다.
- `2024Q4`–`2026Q2`에는 5사 모두 해당 calendar bucket의 input filing이 있었다.
  cutoff까지 `2026Q3` input filing은 HD에만 있었고 TXN·JNJ·CVX·NEE는
  `NO_FILING_AS_OF_CUTOFF`다. 이것은 값 누락이나 분석 실패가 아니라 현재 discovery
  availability이며 후속 filing으로 소급 대체하지 않는다.
- package download와 Arelle parse/build는 0건이다. 이 결과는 filing plan 검증이며
  financial metric readiness나 5사 최종 eligibility를 뜻하지 않는다.

### 6.2 첫 5사 financial build 진행 상태

독립 수락된 d378 runtime을 별도 clean checkout에서 실행하며 회사 process는 한 번에 하나만
띄운다. 새 immutable root는
`data/processed/universe_runs/20261010_universe50_quarterly/pilot5_d378_*`와
`data/raw/universe_runs/20261010_universe50_quarterly/pilot5_d378`다. 이 진행 기록은
actual data gate 전의 운영 증거다.

- TXN 22/22와 HD 22/22 accession이 Raw complete, history와 5FY annual analysis verified다.
  TXN total wall 154.354초/peak RSS 6,239,848KB, HD 99.010초/4,898,628KB였다.
- JNJ의 과거 2021 filing 하나는 package 손상이 아니라 pilot taxonomy cache에
  SRT 2019, US-GAAP 2019, country 2017 import가 없어서 실패했다. read-only 진단 보고서
  `/tmp/jnj-20210404-readonly-diagnosis/report.json` SHA-256
  `09e06c077b2ace95e9fac77c587ed96336cd9cdbbd41bc2aa2ffa08f2237fe34` 뒤, 기존 명시적
  `bootstrap_taxonomy=True` 경로로 cache를 채웠고 해당 accession은 새 attempt에서
  INGESTED됐다. 기존 실패, ZIP, 21개 성공 snapshot은 변경하지 않았다.
- CVX 최초 23 package 요청은 transport 단계에서 실패했다. 단일 exact URI를 body 없이
  재확인했을 때 HTTP 200/application-zip였고, 재시도에서 22개가 INGESTED됐다. 남은 2021
  filing 하나는 같은 historical taxonomy import gate로 분리됐다. 이는 metric 미공시가
  아니며 taxonomy recovery 후에만 재시도한다.
- `held_filings`는 validated successful Raw snapshot/outcome 수이며 품질 hold를 뜻하지 않는다.
  회사가 `RAW_COMPLETE`, history verified, annual analysis verified를 모두 통과하기 전에는
  financial READY로 세지 않는다.

## 7. 재사용 API와 확인된 interface gap

기존 `sec_xbrl.collection_operations`의 public 경계는 다음과 같다.

- `prepare_universe(config_path, run_root, submissions_roots, offline, existing_plans)`
- `collect_universe(..., selected_tickers=...)`
- `build_universe(..., selected_tickers=...)`
- `read_universe_status`와 network-free `status` CLI

분기 producer의 새 public 경계는 다음과 같다.

- `publish_quarterly_screening_metrics(config_path, destination)`는 외부 config, 정확한 annual
  metric parent manifest SHA, 회사별 QUARTERLY analysis manifest SHA를 검증하고 네 payload를
  원자적으로 새 destination에 게시한다.
- `QuarterlyMetricReader(root, manifest_sha256=...)`는 SEC, Arelle, history selection이나
  재무 계산을 호출하지 않고 frozen file set/hash/count/grain/publication identity를 읽는다.
- `build_quarterly_company_records(...)`는 이미 준비된 columns/core cells/trace를 받는
  network-free producer 경계다. HTTP/browser consumer에서 호출하지 않는다.
- CLI는 `python -m sec_xbrl.metrics.quarterly_screening publish --config ... --destination ...`와
  `status --publication ...`이다. `status`는 외부 source를 다시 열지 않는다.

config schema `quarterly-screening-metric-config-v1`은 `financial_as_of`, `fixture_kind =
ACTUAL_PREPARED`, `source_commit_sha`, exact `annual_metric_root`와 manifest SHA, 그리고
`{ticker,cik,analysis_root,analysis_manifest_sha256}` 회사 목록을 요구한다. manifest의
`annual_parent`는 같은 CIK membership의 annual **metric** publication ID/SHA를 가리킨다.
annual dataset이나 UI publication을 대신 가리키지 않는다.

현재 config는 `schema_version=1`, `universe_id`, `purpose`, `as_of_date`, optional
`source_observed_at`, collection의 두 fiscal-year 수와 `include_subsequent_quarters=true`,
그리고 external company CIK/ticker/group을 받는다. ticker와 회사 목록은 engine code에
넣지 않는다.

두 gap은 확대 parsing 전에 별도 최소 producer 변경 여부를 결정한다.

1. standard discovery CLI의 `SECSubmissionsClient` 기본 간격은 0.2초이며 config로 노출되지
   않는다. 이번 pilot는 기존 client를 0.5초로 명시해 먼저 cache하고 offline prepare한다.
   향후 adapter는 shared rate를 manifest에 기록하고 모든 process 합계 제한을 보장해야 한다.
2. 기존 plan은 5 FY+subsequent filing을 선택하지만 “8 calendar bucket 모두의 상태가
   설명됐는가”를 attest하지 않는다. 새 coverage validator는 실제 report/context date를
   읽되 새 selection·계산 정책을 만들지 않고 requested/available/missing/conflict 수와
   source accession을 materialize해야 한다.

이 gap은 기존 collector/parser를 재작성하는 근거가 아니다. compatibility adapter 또는
별도 producer publication으로 해결하고 old plan/run은 그대로 읽을 수 있어야 한다.

## 8. 단계별 산출물과 수락

| 단계 | 산출물 | gate |
| --- | --- | --- |
| P0 계약·identity | 이 문서, cached/live source observation, 50 target/hold snapshot | 50 slot 모두 eligible/hold/excluded reason; XOM succession 미해결 시 처리 보류 |
| P1 5사 discovery | immutable submissions snapshots, per-company plan, filing·bucket coverage 보고. 최초 실행은 14 snapshot·111 filing·25 baseline·1 amendment, parse 0 | future filing 0, amendment 보존, 5 baseline/partial-history가 사실대로 기록. 결과 독립 검증은 미수행 |
| P2 현재 21 M0 | source diagnosis, 승인된 scoped repair, 새 publication과 독립 검증 | unresolved critical systemic blocker 0; valid missing은 유지 |
| P3 50사 Raw/history | cache-first intake, 회사별 atomic snapshot과 persisted panel | company failure 격리, full plan/attempt/status, failed Raw를 missing으로 게시하지 않음 |
| P4 quarter producer | reported/YTD/derived/instant 분리 publication과 coverage | 8 bucket 상태 50사 모두 존재, derivation exact lineage, unsupported는 unavailable |
| P5 consumer 통합 | 별도 UI writer의 catalog/profile/screening 연결 | producer manifest hash 고정, browser 계산·SEC 접근 0, old annual runs 불변 |

각 freeze는 unit·network-free integration, cached actual pilot, adversarial plan/hash/as-of/
identity/period tests, relevant full regression과 Ruff를 거친다. 별도 검증자는 frozen SHA와
actual output manifest를 읽기 전용으로 검증한다. source 구현, 독립 PASS, 로컬 인수,
push·PR·remote CI·main merge를 각각 따로 기록한다.

## 9. 운영 자원과 현재 제한

metadata와 discovery는 cache-first, network I/O는 shared 2 requests/s 이하로 수행한다.
향후 package 수집도 동일 rate budget을 공유한다. Arelle parse/build는 회사별 독립
process를 한 번에 하나만 실행해 종료 후 memory를 반환한다. 기존 CAT combined build의
peak RSS 약 26 GiB와 현재 약 31 GiB RAM을 기준으로 여러 회사 parser를 병렬 실행하지
않는다. 최초 5사의 cache hit, accession 수, download bytes/time, parse wall time, peak RSS,
output size를 실측하기 전에는 50사 ETA를 약속하지 않는다.

기존 21사의 immutable source와 manifest, old annual/default screening, historical run,
actual journal은 acceptance 전후 hash로 보호한다. 대용량 SEC archive, Parquet, cache,
운영 manifest와 비밀 연락처는 Git에 넣지 않는다. 이 단계는 price·market cap·liquidity,
매수 기준, 모든 지표 완전성, index membership 또는 cross-company accounting equivalence를
제공하지 않는다.
