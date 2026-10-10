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
**APPROVED**다. 상태는 **M0_CORRECTION_IMPLEMENTATION_APPROVED**이며, 확대 financial
parsing, 29사 추가 history build, quarterly publication과 consumer 연결은
**BLOCKED_PENDING_CORRECTED_21_INDEPENDENT_PASS**다. 새 21사 publication이 독립 검증을
통과하기 전에는 확대 단계로 넘어가지 않는다. 문서의 수락 조건은 이 절에 적은 범위를
넘는 회계 정책이나 UI 구현을 자동 승인하지 않는다.

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
   대표값 자격을 갖는다. 자격 후보가 하나면 그 existing reported fact를 선택하되 모든
   후보와 채택·탈락 evidence를 lineage에 남긴다.
3. **revenue-only reported total.** typed primary revenue 후보가 여러 개이면, 같은 primary
   IS role의 CAL에서 `us-gaap:Revenues`가 competing revenue child와 다른 reported component의
   parent이고 모든 edge weight가 `+1`, measurement scope가 같으며 reported parent 금액과
   child 합계가 exact Decimal 또는 기존 CAL tolerance로 일치할 때만 이미 보고된 parent
   fact를 선택한다. WMT FY2025의 `680985000000 = 674538000000 + 6447000000`이 positive
   control이다. 합계를 새로 만들지 않고, 이 규칙을 net income·cost·custom concept·label·
   order·issuer 예외로 일반화하지 않는다.
4. **reason과 candidate lineage 보존.** 해결되지 않은 경우 source
   `MULTIPLE_CANDIDATES`와 전체 후보/evidence가 analysis에서 metric publication까지
   유지돼야 한다. 이를 `INPUT_NOT_REPORTED`, missing unit 또는 period 오류로 바꾸지 않는다.
   COST cost 항목 두 cell은 별도 evidence가 없으므로 계속 hold이며 core 수락을 위해
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
이번 correction으로 바꾸지 않는다.

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
XOM이 cutoff 기준 지원 issuer로 확정되지 않으면 provisional 대체 후보는 cached inventory의
`COP / CIK 0001163165 / CONOCOPHILLIPS / NYSE`다. COP도 똑같은 live identity·form·SIC·
security-type gate를 통과해야 하며 자동 대체하지 않는다.

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

quarterly YoY와 TTM은 이번 최초 publication의 자동 산출물이 아니다. 필요한 current·
predecessor quarter 또는 rolling inputs의 semantic identity, actual duration, basis와
source availability를 실제 corpus에서 진단한 뒤 별도 lead 승인을 받아야 한다. missing은
missing으로 남긴다.

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

## 7. 재사용 API와 확인된 interface gap

기존 `sec_xbrl.collection_operations`의 public 경계는 다음과 같다.

- `prepare_universe(config_path, run_root, submissions_roots, offline, existing_plans)`
- `collect_universe(..., selected_tickers=...)`
- `build_universe(..., selected_tickers=...)`
- `read_universe_status`와 network-free `status` CLI

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
