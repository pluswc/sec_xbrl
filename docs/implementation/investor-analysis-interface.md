# Prepared investor analysis interface

## Consumer contract

`sec_xbrl.analysis.open_analysis(bundle_or_catalog)` opens an immutable Parquet
consumer bundle, or an administrator catalogue with `analysis_current.json`.
Queries do not collect SEC documents, parse XBRL, reselect filing versions, or
calculate financial values. Datasets are verified/read once per client and
cached. Trace data uses separate partitions, not duplicated inline in every
cell. HTML is a consumer of these exact functions; its JavaScript only opens
prepared branches and formats their already prepared value tables.

```python
from sec_xbrl.analysis import open_analysis

client = open_analysis("/absolute/path/to/catalog")
panel = client.overview("AMD", fiscal_start=2023, fiscal_end=2025)
groups = client.list_breakdowns("revenue", context=panel["context"])
branch = client.children(groups["groups"][0]["node_id"], context=panel["context"])
all_branch = client.children(groups["groups"][0]["node_id"],
                             context=panel["context"], selection="all",
                             reference_period=(2025, 4))
more = client.children(branch["children"][0]["node_id"],
                       context=panel["context"], path=tuple(branch["path"]))
trace = client.trace(panel["cells"][0]["cell_id"], context=panel["context"])
comparison = client.compare_views("AMD", fiscal_start=2023, fiscal_end=2025)
status = client.target_status("AMD")
```

U3 bundles default `children` to `selection="important"`; `selection="all"`
recovers presentation exclusions and ordinary warnings. `limit` remains the
page size and does not change the policy's top-five threshold. The reference is
the latest requested context quarter unless an exact prepared context period is
supplied. Each child carries prepared amount/change ranks, separate reason and
warning codes, reviewed parent-share evidence or an unavailable reason, and the
historical evidence period when the requested reference has no observation.
The cursor binds policy/version, selection, reference period, context, node and
ancestor path. Pre-U3 immutable bundles remain readable through an explicit
`legacy_fallback` response and retain their old stable-node ordering; queries do
not synthesize importance evidence for them.

`list_breakdowns(..., include_hidden=True)` is the administrator/all-items path
for exact hidden lenses. `target_status` returns a persisted `READY`,
`UNSUPPORTED`, `PREPARATION_FAILED`, `NOT_PREPARED`, `REVIEW_REQUIRED`, or
`DISCLOSURE_MISSING` outcome. Before any consumer bundle exists,
`company_reports.read_target_status` reads the administrator record. A missing
disclosure status requires explicit checked-publication evidence; registration
or an unheld filing range is `NOT_PREPARED`, never disclosure absence.

Omitting year bounds returns the latest eight prepared quarters. Explicit year
bounds can include an incomplete year, including a single newly collected
quarter. No empty annual baseline is invented. QTD and INSTANT columns remain
distinct. Every core row is retained even if unavailable. `as_of` and
`review_cutoff`, when supplied, must exactly match the publication: filtering
cells by an earlier date cannot reproduce an earlier selection/review state.
Open the separately prepared historical publication instead. AS_FILED is the
original filing selection; LATEST_REPORTED is the current eligible selection,
not a guarantee of economically comparable recast statements.

Results retain query context, publication, view, actual dates, basis, full unit
and dimensions, status, source identifiers, stable nodes and provenance. A
cursor is scoped to context, node and ancestor path. Follow the returned path
for deeper queries. Cycles terminate without imposing a fixed depth. CAL
networks retain source filing/role; DEF follows targetRole and positive
dimensional arcs while keeping structural nodes distinct from business values.
PRE supplies statement context only, never invented decomposition. Independent
dimensional views cannot be summed. A reviewed display hierarchy needs exact
basis/full dimensions, an evidence hash, reviewer/time, and an explicit source
table allowlist. New filings do not inherit it.

## Preparation and administration

```python
from pathlib import Path
from datetime import date
from sec_xbrl.analysis import prepare_catalog, refresh_analysis

bundle = prepare_catalog(catalog=Path("/admin"), destination=Path("/new/bundle"),
                         tickers=("AMD",), fiscal_start=2023, fiscal_end=2025)
# Explicitly performs discovery / collection / calculations, then prepares
# and publishes the consumer bundle. Never called implicitly by a query.
bundle = refresh_analysis(admin=Path("/admin"), workspace=Path("/new/work"),
                          as_of=date(2026, 9, 8), review_as_of=date(2026, 9, 8),
                          tickers=("AMD",))
```

The catalogue uses existing `company_reports` registration. Optional
`analysis_profiles.json` maps ticker to core rows/order/exact QName choices,
display notes, `breakdown_sources` and separately reviewed `hierarchies`.
`lens_preferences` can match an existing anchor/lens type/role/basis to set its
label, display order or hidden flag; it cannot create a semantic edge.
An exact `node_id` or complete `axis_signature` (a unique list of the existing
axis identities, order-insensitive) distinguishes otherwise identical views.
For example, `{"match":{"lens_type":"DIMENSIONAL_VIEW","axis_signature":["srt:ProductOrServiceAxis"]},"label":"제품·서비스별","display_order":10}`
does not match a combined product/geography or product/consolidation scope.
Profiles have at most 25 unique core rows. A related statement source is labeled
as such: LiabilitiesAndStockholdersEquity is not relabeled as a liabilities
total. Productive-asset cash outflows are not silently equivalent to PPE-only
cash outflows. A new company requires configuration, not engine code changes.

### Company-independent onboarding

The design goal is for the five currently exercised companies to remain
regression samples, not a ticker allowlist. The existing generic registration
and preparation functions are intended to let an administrator register any
SEC-supported filer, select its filing range and approved configuration, prepare
its data, and expose it through the same catalogue and consumer API. Frozen U3 demonstrated cached NFLX registration, preparation and refresh outside
the original five-company cohort, using the same engine and administrator API.
This does not demonstrate universal-filer or live-collection coverage; acceptance
requirements remain in the [U3 important-items analysis plan](u3-important-items-plan.md).
Onboarding must not add ticker-specific branches to the engine. A generic defect
discovered by a new filer may be fixed for all companies, while company-specific
QName choices, display preferences, and reviewed interpretations remain
administrator configuration or explicit review decisions. A previously unseen
custom disclosure requires a manually scoped administrator review; registration
alone does not approve its meaning.

The current implementation has materially deeper regression evidence for the
five samples than for arbitrary filers. It currently supports the 10-K, 10-Q,
10-K/A, and 10-Q/A preservation and selection rules described by the project
contracts; this is not a claim of complete coverage for financial institutions,
foreign issuers, every taxonomy pattern, or every custom disclosure. Registering
a ticker establishes a preparation target, not proof that its analysis is ready.

Preparation and catalogue publication must distinguish at least these outcomes:

- `UNSUPPORTED`: outside the declared SEC/form or implementation contract
- `PREPARATION_FAILED`: discovery, collection, parsing, analysis, or publication failed
- `NOT_PREPARED`: supported target whose required publication has not been prepared
- `REVIEW_REQUIRED`: collected evidence needs an administrator's explicit interpretation or approval
- `DISCLOSURE_MISSING`: a prepared, eligible filing range was checked and the disclosure is actually absent

These outcomes are persisted in the administrator catalogue and consumer target
status records, and exposed through `target_status` / `read_target_status`. A not-yet-held filing
is a collection target and must never be converted to `DISCLOSURE_MISSING` merely
to fill a cell. Only the administrator makes review and accounting-meaning
decisions. U3 v1 thresholds are approved in its plan; new U3-R v2 thresholds and bounded
source approvals are recorded separately in the followup delivery contract.

`prepare_analysis(publication=..., destination=..., tickers=...)` is the lower
level single-source producer. It reads governed history plus its declared raw
relationship/concept snapshots only during preparation. Existing source files
and publications remain immutable. `prepare_catalog` resolves per-company
publication paths and atomically publishes a pointer after success.

Reviewed-company refresh attempts exact candidate/source-preserving review
republication, including all old decision/quality histories and quarantines.
If new accessions appear for a reviewed company, or candidate identities no longer bind, it retains new collected/Analytical
artifacts, writes `review_refresh_required.json`, and leaves registrations
unchanged. Rebinding approvals to changed identities, or approving new filing
interpretations, is not inferred from an old one-filing decision.

## Derived values and limits

The standard CF policy additionally permits cash-flow-statement-scoped
repurchases, share compensation and productive-asset purchases. Exact currency,
duration, complete dimensions, fiscal boundaries and source lineage remain
required. Q4 remains FY minus nine-month YTD; FY is never replaced. EPS, share
counts, ratios and arbitrary custom facts are not subtraction candidates.

The investor metric adapter never promotes null basis to COMPATIBLE. A separate
versioned *reported-value arithmetic* result preserves null basis and carries
`REPORTED_VALUES_NOT_RECAST_VALIDATED`; it is not reusable as Q4 compatibility
or CURRENT_COMPARABLE evidence. Negative/zero bases are not ordinary growth
rates. Actual duration differences remain warnings. Margins require exact
period/unit/dimensions and primary-statement evidence for each same-filing input
leg; approved quarter-difference inputs must match their complete source-period
pairs. Financial arithmetic is persisted by the producer, never by HTML.

Not implemented: automatic narrative-to-zero extraction, unrestricted custom
concept bridges, cross-company accounting equivalence, automatic new-filing
semantic approvals. U3 v1 importance ranking is implemented in the frozen
`09309c80700fed2115e2b18eddd2c21dc5e200e3` baseline. Missing direct totals are not filled
by an unreviewed Assets-minus-Equity guess. Retained original notes and explicit
review queues are the fallback, not fabricated values.

## Resume a review-stopped refresh

The last successful catalogue pointer remains readable. The failure artifact
identifies the newly prepared parent, new accessions and previous review
publication. Use the existing explicit review workflow, rather than removing
the old review overlay:

```bash
python -m sec_xbrl.disclosure_review prepare --parent NEW_PARENT \
  --locators exact-source-locators.json --rules scoped-review-rules.csv \
  --package-root IMMUTABLE_PACKAGES --quality-decisions quality-history.csv \
  --destination NEW_INVENTORY
```

Review the exact source candidates and record separate A interpretation and B
additive-Q4 decisions with actual knowledge timestamps. Preserve all old
candidates and decision histories when combining the new inventory. Publish
with `publish_review(..., previous_publication=OLD_REVIEW)`; its append-only
checks reject deleted/edited decisions. If old raw sources now bind to different
consumer identities, stop for explicit rebind review—the existing identity is
not silently rewritten. Finally `company_reports.register_company(...,
publication=NEW_REVIEW)` and `prepare_catalog(...)` publish the new consumer
bundle. New accession and changed-concept bridges remain explicit review work,
not a fully automatic refresh capability.

## H1 / U3-R / H2 followup interface

Frozen U3 verified the five-company cohort plus cached NFLX registration,
preparation and refresh. This is an outside-cohort demonstration through the
same engine; it does not establish universal SEC-filer coverage or live
collection in the current followup.

The new local publication adds `statement_catalog(ticker)`,
`statement(ticker, table_id)`, `pre_table(ticker, table_id)`,
`axes(ticker, filing_id, raw_concept_id=...)`,
`member_metrics(ticker, filing_id, axis_id=..., member_id=..., typed_value=...)`,
and `importance_v2(ticker, view=...)`. These are prepared-data-only reads.
Original U3 calls and datasets retain their v1 behavior and byte identity.

H1 preserves independent actual HTML-row coverage, all Raw FY/YTD/QTD/instant
contexts, separate PRE/CAL/DEF networks, exact signed calculations, source-bound
checks and reviewed source reconciliations. U3-R v2 persists five separate
signals and review/denominator evidence under a new policy. The H2 screen uses
one expandable table, protected subtotals/warnings and independent Axis/member
queries. Unknown or unprepared scopes raise an error instead of a disclosure
absence assertion. Amendments and missing current notes remain explicit.

See [followup delivery contract](u3-followup-delivery.md) for bounded NVDA
source reviews, the supplemental MSFT Calculation 1.1 source-gap adapter,
actual versus synthetic evidence, current comparison limitations and local
independent-verification requirements. A later unreviewed filing never inherits
a prior economic share or reviewed source-equation approval.

## 2026-11-08 기업 프로필의 매출 구성과 흐름

기업 둘러보기의 재무 프로필에서 **매출 구성과 흐름**을 열고 연간 또는
분기를 선택한다. 해당 발행물의 재무 기준일에 준비된 최근 4개 회계연도와
8개 회사 회계분기를 사용한다. 프로필 본문의 단일 기간과는 독립된 창이다.
사업부문 축과 제품·서비스 축은 별도 보기다. 제품 축에 사업부문도 있으면
공시의 부문 범위를 유지하며, 같은 이름의 서로 다른 매핑 구간을 연결하지
않는다. 표에는 선택 기간의 금액과 공시·계산 구분, SEC 공시 색인 링크를
표시한다. 추이는 같은 축과 범위의 관측점을 보여 주며 누락이나 매핑 구간
변경에서 선을 끊는다.

오프라인 `examples/screening/prepare_revenue_breakdowns.py`는
`--dataset-manifest`, `--dataset-manifest-sha256`, `--output`을 받는다.
필요하면 `--cik`를 반복해 범위를 제한한다. 정확히 고정한 부모 분석의
`overview`, `list_breakdowns`, `axis_timeseries`, `trace`를 재사용한다.
기존 그래프 연결이 없는 경우 동일 준비 발행의 표준 매출 태그와 명시적
표준 축에 속한 보고값을 원본 사실 ID로 확인해 표시한다. 각 구간, 부문
범위 및 출처를 그대로 두며, 서로 다른 준비값이 같은 범위에 경쟁하면
보류한다. 초기 발행의 비중과 전년비는 기존 검토값에 한해 표시했다.

Windows 브리지에 `--revenue-breakdowns`의 절대 파일 경로와
`--revenue-breakdowns-sha256`을 함께 전달한다. 준비 파일은 최대 16 MiB,
기업 응답은 최대 512 KiB다. `GET /api/revenue-breakdowns`는 현재
데이터셋 ID, 발행 ID, 재무 기준일과 CIK가 맞는 한 기업의 자료만 제공한다.
기존 재무 서비스와 저장 기록은 기존 경로를 유지한다.

구현자 준비 자료 확인에서는 AMZN과 GOOGL의 최신 연간·분기 분해가 표시
가능했다. GOOGL 2026Q2 Google Cloud는 24,768백만 USD이고, MSFT FY2026
Q4 분해는 준비 자료에서 확인되지 않았다. 이 확인은 운영 전환과 독립
검증에 앞선 결과다.


표의 첫 행인 **연결 매출**은 선택 기간의 준비된 연결 금액과 출처를
보여 준다. 구성 자료가 없는 기간에도 표시한다. 제품·서비스가 특정
사업부문 범위에 속하면 같은 기간과 부문 식별자로 확인된 금액을 **부문
소계**에 표시한다. 구성 항목은 포함 범위가 겹칠 수 있으므로 표시된
항목을 합산해 연결 매출이나 소계를 만들지 않는다.

후속 승인 범위인 `same-filing-revenue-ratios-v1`은 오프라인 준비 과정에서
직접 공시된 값만 사용한다. 사업부문 및 부문 제한이 없는 제품·서비스의
비중은 연결 매출을 분모로 삼는다. 특정 사업부문에 속한 제품·서비스의
분모는 같은 기간에 확인한 그 부문의 소계다. 분자와 분모의 공시 스냅샷,
원본 매출 항목, USD 및 실제 기간이 같아야 하고, 분모는 양수이며 분자는
0 이상 분모 이하여야 한다. 부문 소계를 확인할 수 없으면 해당 비중을
비워 둔다. 비중은 표시 항목 전체가 매출을 빠짐없이 설명한다는 뜻이
아니다.

전년비는 현재 값을 공시한 문서의 전년 비교값과 대조한다. 같은 원본
매출 항목과 전체 원본 차원, USD 및 준비된 전년 회계기간의 실제 날짜가
맞아야 한다. 전년 분모는 양수여야 하며, 52·53주나 윤년에 따른 정상적
기간 차이를 허용한다. 다른 공시에서 선택한 전년 추이 금액과 달라질 수
있다. 파생값, 충돌하거나 품질 확인이 필요한 입력은 보류한다. 각 비율의
입력 사실 ID와 전년 실제 기간을 선택 필드에 남긴다.

분석 발행의 History 매니페스트 해시와 그 History가 가리키는 T1 입력
지문을 확인하고 해당 기업의 보고 관측 파티션만 읽는다. 파티션의 기존
형식에는 바이트 해시가 없어 사용한 매니페스트와 파티션의 해시를 새
보조 발행에 기록한다. 기존 부모, 대시보드 API 및 이전 발행 파일은
그대로 사용한다. 구현자 표본 확인 범위는 AMZN AWS와 GOOGL Search의
2026Q2, MSFT Intelligent Cloud의 FY2026이며, 운영 인수와 별개다.

## 2026-11-09 제품·서비스 공시의 표시 계층

사용자가 승인한 범위는 제품·서비스 축의 공시 항목을 정리하는 표시
변경이다. 오프라인 준비기는 `disclosed-revenue-role-presentation-v1`을
기간별 선택 필드에 기록한다. 분석이 고정한 History의 T1에서 선택된
공시 사실을 대조하고 같은 History의 T2에서 공시 역할과 표시 순서를
읽는다. 같은 공시 스냅샷, 원본 매출 항목, USD, 실제 기간, 나머지
원본 차원이 일치하는 양수 보고값에 한해 표시 근거를 판단한다.

각 역할의 구성 금액이 같은 연결 매출 또는 같은 범위의 공시 부문
소계와 정확히 일치하고 공통 항목이 있으면, 한 공시 소계와 다른 역할의
복수 상세 항목이 정확히 대응할 때만 들여쓴다. 공통 항목은 한 번만
보인다. 공통 항목이 없는 완전한 분류는 따로 표시한다. 한 역할 내에서는
공시 순서상 바로 앞에 연속된 항목 중 유일하게 맞는 묶음만 공시 소계
아래에 표시하고, 소계로 대체한 구성도 기준 매출과 일치해야 한다.
공시 역할이나 합산 범위를 확인할 수 없으면 항목별 금액과 그 사유를
표시한다. 매출 항목 또는 적용 가능한 상위 항목이 해당 표에서 명시적으로
제외되거나 역할 전환으로 적용 범위가 불명확하면 계층 표시를 보류한다.
여러 공시 분류로 나눠도 각 행은 화면 읽기 도구에서 부문 제목을 참조한다.
역할이나 순서가 새 회계 관계로 발행되지는 않는다.

기존 보고값, 비중 분모, 전년비, 출처와 추이에는 손대지 않는다.
사업부문 보기에는 연결 금액에 부문 간 거래 제거 등 조정이 포함될 수
있음을 설명한다. 이 변경으로 별도의 사업부문 계층을 확정하지 않는다.
기존 보조 발행도 계속 열 수 있다. 구현자 표본 확인은 AAPL FY2025,
AMZN FY2026 Q2 및 GOOGL FY2026 Q2에 한정했다. 50개사 발행, 독립
검증과 운영 인수는 별도 단계다.
