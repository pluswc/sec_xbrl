# 2026-11-07 선택 기업 동일 지표 추이 비교 계약

## 승인·범위와 상태

사용자는 선택 기업의 매출/이익/현금흐름을 같은 chart에서 비교하고 현재 연간·분기·TTM과
기존 기능을 재사용하며 데이터/저장 기록을 보존하도록 요청했다. ROOT 승인 제품 범위는
companion `examples/screening/display-assets/app.js`, `app.css`뿐이다.
기준 main은 `2cd9e2e989fbbc660a3665513c122a93798c1713`, branch는
`codex/explorer-company-trends`다. Python119/bridge/API/backend/verifier/packet,
원본 데이터/catalog/journal/지침을 바꾸지 않는다. Writer는 운영/원격 작업을 하지 않는다.

구현·focused 검사·ROOT19065 preview는 완료했다. 새 동결 SHA의 독립 검증·소스 인수·
18765 frontend 전환·PR/CI/main은 별도 대기다. 이전 PR70/main2cd/live3388 완료와
이번 추가 기능의 상태를 구분한다.

## 사용자 흐름과 표시

기존2~4개 기업 선택/비교 panel header 바로 아래에 `선택 기업 추이 비교`를 둔다.
Native `추이 지표`는 매출·영업이익·순이익·영업활동 현금흐름·표준화 FCF 중 현재 catalog의
정의만 제공하고 최초값은 매출이다. Annual/quarter_/ttm_ 대응을 사용한다.
한 축에는 **동일한 MONEY/USD 지표 하나만** 표시한다. 서로 다른 지표/단위, indexing/
log scale, 새 TTM·재무 계산은 만들지 않는다. 기존 비교 matrix/profile과 저장 동작은 유지한다.

기존 ledger palette/14px body·11px metadata·4px rhythm, SVG/decimal formatter를 재사용한다.
기업은 색+dash/legend로 구분한다. 실제0/negative는 선형 백만 달러 축에 표시하고 중복/
겹침 없는0.0 tick과 zero line을 둔다. Missing/quality BLOCK은0이 아니라 gap이며 단일
available point는 dot, 전체 missing은 이전 chart를 지운 뒤 설명으로 남긴다.
모든 exact value/actual dates/FYQ는 tooltip과 native details 표에 유지한다.

측정한 container 폭으로 SVG를 그려390px에서도 axis 글자를 축소하지 않는다.
ResizeObserver/rAF는 model만 다시 그리며 fetch/scroll하지 않는다. 사용자가 비교를 열 때만
chart로 scroll/focus한다. 기존 matrix controls는 chart 아래에서 그대로 동작한다.
DOM hooks는 `#comparison-trend`(aria-busy), `#comparison-trend-metric`,
`#comparison-trend-chart`, `#comparison-trend-values`, `#comparison-trend-status`다.

## API·좌표·cache·async 계약

Annual은 기존 governed `/api/company-profile?dataset_id&cik&fiscal_year`를 사용한다.
Wrapper dataset/publication/as-of/선택 FY/CIK와 grouped definition/version/MONEY/USD,
row metric/version/FY/prepared_years를 확인한다. Normalized row에 없는 CIK/unit를
요구하지 않으며 raw `/api/series`나 별도 canonical/dedup을 사용하지 않는다.
Interim은 `/api/quarter-series?dataset_id&cik&metric_id&limit=8`의 definition와 각 row
CIK/metric/unit/as-of/basis/calendar 및 EXCLUSIVE 선언을 확인한다.
Incompatible/duplicate 좌표와 published spine 밖 응답은 visible failure로 거부한다.

Raw array 순서나 실제 날짜를 공통 좌표로 가정하지 않는다. Annual은 선택 FY에서 끝나는
최대4개 연속 좌표이며 준비 최초 FY보다 앞으로 늘리지 않는다. 준비2022/2024/2025
사이의2023은 gap으로 남기며 선택FY2024에2025를 그리지 않는다. Interim은 기존 spine의
선택 종료 이하 최대8 slots다. 현재Q2는7 slots, Q3는8이다. 없는 과거를 조회/재구성하지
않는다. 기업별 실제 기간/FYQ는 별도로 유지하며 회계적 동등성을 주장하지 않는다.

16개 bounded cache는 작은 validated display projection만 보관한다. Annual profile 하나의
공통5개를 재사용하고 interim의 deep lineage는 저장하지 않는다. 원본 API/데이터는
provenance 원천으로 보존한다. Key에 dataset/publication/as-of/CIK/definition을 결속하고
failed promise/validation은 제거한다. Toggleback/reopen/window/resize에 불필요한 fetch가 없다.
부분 기업 실패는 legend/status에 보이고 정상 기업 값은 유지한다.

Exact dataset+basis+end+sorted selected CIKs+metric/request token으로 성공·실패를 소유한다.
Basis/period/selection/close는 model/values/legend를 먼저 지우고 token을 무효화한다.
늦은 응답이 닫힌 panel이나 새 context를 덮지 않는다. Loading/error는 chart-local이다.
PR70의 owned switch continuation guard와 `S.run/S.catalog/S.revision`, threshold/execute/
save/open/export, annual guide/profile은 유지하며 기존 회귀 검사로 확인한다.

## 검증·인계

```bash
node --test tests/screening/screening_company_trends.test.cjs
python -m pytest -q -p no:cacheprovider tests/test_screening_display_assets.py
```

신규9건은 좌표/end/gap, scope/duplicates, negative/zero/no-data, projected cache/retry,
partial failure와 close/context/metric races를 검사했다. 기존 Display5+explorer12와 합쳐
**Node26건, pytest wrapper1 PASS**다. Lint/JS syntax/diff PASS이며 main 대비 Python119/
bridge 변경은 없다. 금융/회사 audit/full publication/backend 검사는 다시 하지 않았다.

ROOT 최초 preview는 source38bda430/CSSda6b2795에서10 scenarios/8 screenshots PASS였다.
Annual2회사/profit·cash cache, 기존 matrix, Q2 seven slots/TTM published values,
4회사/390px, 최신Q3 missing, GOOGL negative FCF, 저장21 문맥과FY2024 window를 확인했다.
Chart-first/zero tick을 보완한 최종6ad93d25/CSS0b298fbf에서 추가5 scenarios/6 screenshots도
PASS: details/right alignment, late-close/cache reopen, INTC503 visible failure/no false
zero line·retry, GOOGL FCF-5,855.0/0.0,4개 distinct series·1024/390·resize fetch 없음.
두 phase는 오류0/GET-only/journal API deep-identical이며 최초10개를 반복하지 않았다.

Windows visualizations `explorer-company-trends-20261107/`의 `browser-uat.json`,
`final-visual-uat.json`과 화면이 근거다. `initial-visual-manifest.json`과
`bundle/preview-manifest.json`으로 bytes를 구분한다. 최종 JS SHA는
`6ad93d257055c95d256b1614f667b82906ad5710ad381a5ded39ed27a1ec2311`, CSS는
`0b298fbf3a3b3343e3219dc84ec0e954281f94d2914614e1c1fe50812f6f960e`다.
이는 자체/preview 검증이며 독립/운영/병합 완료가 아니다. ROOT가 동결 SHA를 별도
검토한 뒤 exact assets로 frontend만 전환하며 backend245090·원본 기록은 보존한다.
