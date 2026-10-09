# 기업 universe 종목 확보 계획

## 1. 상태와 목표

기준일은 **2026-10-10 KST**다. 이 문서는 계획 작성만 승인된 **PROPOSED**
상태다. 수집·코드·회계 정책·자동화·시장 데이터·원격 작업은 승인하지 않는다.
목표는 현재 21개 회사를 먼저 정확히 진단하고, 회사와 증권 식별자를 분리한
governed universe를 50→150→500으로 단계적으로 넓히는 것이다. 목표 숫자는
S&P 500 구성이나 모든 지표의 완전성을 뜻하지 않는다.

현재 기준은 [21사 전달 계약](../implementation/universe-data-delivery.md)과
[완료 기록](../implementation/universe-data-delivery-completion.md)이다. 회사 등록·
검토 결정은 [회사 관리 계약](../implementation/company-report-administration.md),
지표 상태는 [스크리닝 R1 계약](../implementation/screening-usability-delivery.md)의
경계를 유지한다. 이 계획이 그 정책을 변경하지 않는다.

현재 검증된 기반은 21사, 공시 381건, 21개 raw/history `READY`다. candidate issuer
inventory는 8,016건이지만 SIC 분류는 21건이고 7,995건은 unknown이다. 스크리너는
31개 지표, observation 2,604건, 회사별 4 FY를 갖고 FY union은 2022–2026,
21사 공통 기본연도는 FY2025다. FY2025 가용성은 revenue 18/21, gross profit
9/21이다. 따라서 첫 과제는 종목 수를 바로 늘리는 일이 아니라 “왜 값이 없는지”를
구분하는 일이다.

Apple은 이미 등록돼 있다. FY2022 raw revenue `394328000000`, gross profit
`170782000000`이 존재하지만 mapping review가 필요하고 방법은
`STRING_SIMILARITY_ONLY`, 상태 `UNCERTAIN`, confidence `0.35`다. FY2025 두 값은
각각 `416161000000`, `195201000000`으로 사용 가능하며 FY2026 prepared year는
없다. WMT·COST·TSLA의 FY2025 revenue는 원본 cell에서
`MULTIPLE_CANDIDATES`인데 metric 단계에서 `INPUT_NOT_REPORTED`로 단순화되고,
여러 gross-profit 누락은 `REQUIRED_ITEM_NOT_IN_PREPARED_DATA`다. 어느 것도
“회사가 공시하지 않았다”는 증거가 아니다.

## 2. 원칙과 준비 상태

- issuer(CIK)와 security(ticker·share class·exchange)를 별도 entity로 관리한다.
  ticker 연속성을 CIK 동일성으로 보지 않고, GOOG/GOOGL 같은 share class가 issuer
  수를 부풀리지 않게 한다.
- 원자료, 후보, 검토 결정과 발행본은 불변 source hash·관찰 시각·as-of·alias·
  rejection reason을 가진다. 원본을 고치지 않고 scoped decision을 append한다.
- `raw_ready`, `basic_screen_ready`, `comparability_review`, `metric_unavailable`,
  `partial_history`는 서로 독립된 capability다. 누락·검토·비적용을 0으로 만들거나
  회사를 candidate universe에서 숨기지 않는다.
- 기본 core 제안은 최근 완료 FY의 revenue·CFO와 FY 말 assets다. 각각 main
  IS/CF/BS의 unique USD undimensioned exact-period 근거가 있어야 한다. 31개 전체를
  필수로 만들지 않는다. 파생 지표는 입력과 실제 기간이 호환될 때만 가능하며,
  growth에는 최소 2 FY가 필요하다.
- 4개 연도 growth window에는 완료 FY 5개가 필요하다. discovery plan이 **5개 annual
  baseline(화면 4개+명시적 predecessor 1개)**과 as-of까지의 이후 10-Q,
  10-K/A·10-Q/A를 선택한다. fiscal date와 53주 연도를 보존하고 미래 공시를 섞거나
  amendment로 원본을 덮지 않는다. 짧은 IPO는 `partial_history`로 유지한다.
- Q4 미해결은 quarter/TTM에는 영향을 주지만 direct annual baseline의 필수 gate가
  아니다. older FY 보충도 기존 mapping review를 자동 해제하지 않는다.
- reported 표시 범위, comparison eligibility, selector/mapping 승인, 파생 gross
  profit 같은 정책 변경은 별도 승인이 필요하다. 전역 review 해제, ticker별 UI
  예외, zero fill, 사설 공식은 금지한다.

## 3. 단계와 수락 gate

| 단계 | 산출물 | 다음 단계 gate |
| --- | --- | --- |
| **M0: 현재 21사 품질 진단** | 회사×FY×지표 missing-reason inventory. `ABSENT_YEAR`, `RAW_PRESENT_REVIEW`, `CANDIDATE_AMBIGUITY`, `EXACT_ITEM_NOT_FOUND`, 검증된 `NOT_APPLICABLE`, parser failure를 분리. standard QName, PRE primary, unit, full dimensions, period, source filing 근거와 blocker queue | 원본 보존, 모든 21사 상태 존재, silent failure 0, 실제 screenability와 blocker 수 측정. Apple·WMT·COST·TSLA 사례를 원본 상태까지 대조 |
| **M1: candidate master** | as-of별 issuer/security snapshot, SEC alias·CIK conflict, ticker/exchange/share class, source hash·observed/effective-known 시각, security type·제외/보류 이유. SEC SIC는 coarse peer 1차 분류, 수동 business group은 별도 version | CIK join conflict 0 또는 명시적 hold. 8,016건을 “상장 보통주 전체”라고 부르지 않음. unknown·unsupported도 reason과 함께 유지 |
| **M2: 21→50** | 아래 29개 후보의 identity·eligibility 검토, 5개 annual baseline+현재 FY 공시 plan, raw/history/metric coverage matrix | 50 issuer의 선택/보류/제외가 모두 설명되고 source trace·실패가 남음. 선택적 목표로 eligible cohort의 basic core `≥90%`; quota를 맞추려고 규칙을 약화하지 않음 |
| **M3: 50→150** | sector·industry stress, 신규 IPO·issuer 변경, restart/idempotence·memory·storage·시간 benchmark, finance/insurance/REIT 별도 profile pilot | 첫 5사 pilot과 batch 실측으로 예산·ETA 제시. 자동 재개, 중복 없는 산출물, quality-rule coverage와 모든 candidate 상태 확인 |
| **M4: 150→500** | 승인된 batch benchmark에 따른 immutable universe/run과 전체 coverage·오류 보고 | 운영 용량·저장량·실행시간·독립 데이터/화면 검증이 수락된 뒤에만 진행. 500은 index membership 또는 완전 데이터 보장 아님 |
| **M5: 유지 관리 제안** | nightly filing discovery·metadata refresh·incremental new filing, weekly quality check, versioned universe/run | 별도 자동화 승인, 실패 알림·재개·rollback·source preservation 수락. 이 계획에서는 생성하지 않음 |

M0–M4 완료 보고는 요청·선택·보류·성공·실패 수, 실제 기간, source trace,
coverage matrix와 silent failure 0을 함께 제시한다. 회사가 제외되면 eligibility 이유를,
포함됐지만 지표가 없으면 metric reason을 각각 남긴다.

## 4. 50사 후보 구성

다음 29개는 2026-10-08 cached candidate inventory에서 unique CIK와 exchange가
대조된 **후보**일 뿐, 2026-10-10의 live listing·security type·eligibility가 확정된
것은 아니다. bucket은 연구 균형용 임시 분류이며 verified SIC가 아니다.

| 임시 연구 bucket | 수 | 후보 ticker |
| --- | ---: | --- |
| 반도체·기업 기술 | 11 | TXN, ADI, AMAT, LRCX, KLAC, IBM, ORCL, CRM, ADBE, INTU, CSCO |
| 소비재·소매 | 5 | HD, LOW, NKE, PEP, MCD |
| 산업재·운송 | 4 | GE, HON, UPS, UNP |
| 헬스케어 | 4 | JNJ, MRK, ABBV, ABT |
| 에너지 | 2 | XOM, CVX |
| 유틸리티 | 2 | NEE, DUK |
| 소재 | 1 | LIN |

기존 21사와 합쳐 목표 50 issuer다. 특히 cached metadata의 XOM은
CIK `0002115436`, name `ExxonMobilHoldingsCorp`이므로 현재 security와 과거 filing
issuer의 succession을 먼저 확인한다. ticker가 같다는 이유로 과거 history를 새
CIK에 연결하지 않는다.

1차 eligibility 제안은 미국 거래소 상장 ordinary operating security이면서 지원되는
10-K/10-Q, US-GAAP, USD 공시가 있는 경우다. ETF·fund·warrant·preferred·OTC와
지원하지 않는 20-F/40-F는 삭제하지 않고 reason과 함께 제외/보류한다. domicile이나
이름으로 추측하지 않는다. 금융·보험·REIT는 일반 산업 baseline ratio에 섞기 전에
별도 profile pilot을 통과한다.

## 5. 병렬 lane과 운영 한계

작업은 같은 산출물을 동시에 쓰지 않는 네 lane으로 나눈다.

- **A — metadata**: issuer/security/alias/exchange/SIC 검증과 conflict queue
- **B — 품질 검토**: 현재 21사의 mapping·candidate·governed quality decision
- **C — 공시 처리**: 기존 discovery adapter, cache/live filing intake와 parser batch
- **D — 독립 수락**: source 대조, coverage, consumer·frontend 시나리오 검증

A와 B는 병렬 가능하지만 C는 M0/M1의 identity·scope gate를 통과한 company plan만
받는다. D는 동결 publication을 읽는다. SEC 요청은 모든 machine/process 합계로
공식 상한 10 requests/s를 넘지 않으며, 초기 운영은 shared 2–5 requests/s,
I/O worker 2–4개를 제안한다. parser는 초기에는 company process 1개씩 실행한다.
실제 CAT combined build에서 RSS 약 26 GB가 관찰됐기 때문이다. cache·resume을
우선하고 모든 실패를 기록한다. SEC archive, Parquet, cache는 Git에 넣지 않는다.

예산과 ETA는 첫 5사 pilot의 download/cache hit, parse/build wall time, peak RSS,
저장량과 review 시간 실측 뒤 제시한다. 현재 SEC 재무 데이터에는 가격·시가총액·
유동성이 없으므로 이 단계는 **financial-analysis universe**다. 향후
investable universe의 최소 규모·유동성 조건은 별도 governed market feed 제안과
승인이 필요하며, 지금은 순위나 매수 기준을 만들지 않는다.

## 6. 출처와 다음 승인

2026-10-10에 확인된 1차 출처는 [SEC EDGAR API 안내](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[SEC 개발자 자원과 요청 한도](https://www.sec.gov/about/developer-resources),
[Nasdaq Symbol Directory 정의](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs),
[SEC SIC 목록](https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list)이다.
SEC submissions와 older filing pages는 discovery/identity seed이며, companyfacts는
standard entity fact 참고 자료일 뿐 parser relationship의 대체물이 아니다.
Nasdaq directory의 ETF·test issue·venue field는 security 검토 근거지만 모호한
type을 이름으로 확정하지 않는다. NAICS/GICS는 검증된 mapping과 라이선스가 있을
때만 선택적으로 추가하며 accounting equivalence를 뜻하지 않는다.

다음 승인 요청은 M0/M1의 구체 입력·출력 schema, 5사 pilot 목록, live/cached 구분,
예산 측정법과 독립 수락 절차를 확정하는 범위여야 한다. 승인 전에는 29개 후보를
등록·수집하거나 자동화하지 않는다.
