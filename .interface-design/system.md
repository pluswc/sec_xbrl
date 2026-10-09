# Investor screening worksheet interface system

- Direction: a calm investor screening worksheet. The company result matrix is the focal surface; technical provenance stays in the governed backend and explicit admin mode.
- Domain signature: grouped investment criteria become financial columns, then continue into company detail and append-only judgment history.
- Palette: ledger ivory canvas, filing-paper surface, ink charcoal text, filing-table slate, annotation blue, review amber, and blocking red. Color communicates state or action only.
- Depth: borders and small surface shifts. Inputs are inset; the evidence drawer is the sole elevated overlay.
- Spacing: 4px base. Use 8px within controls, 12px for dense groups, and 16px between sections.
- Type: local Korean UI font with fallbacks; 11px metadata, 14px body, 18px section title, 24px page title. Use weight and muted color before adding size.
- Navigation: a narrow screener, company-results, and watchlist/history rail on wide screens; a horizontal strip at compact desktop width.
- Buttons: primary blue for commit/run actions; transparent bordered buttons for secondary actions. Native button semantics and a 3px focus outline.
- Tables: sticky 11px headers, 9px by 12px cells, tabular numbers, blue selected-row tint. Company names open evidence; checkboxes select export scope.
- Status: every state includes text. Amber means review/undetermined, red means failure/block, green means pass. Raw codes belong in expandable technical details where possible.
- Evidence drawer: up to 570px wide, focus-trapped, Escape closes and returns focus. It shows one predicate metric at a time, with actual source dates and raw annual levels.
- Criteria: expanded for new-condition editing, then reversibly compacted after a run opens or executes so the result matrix owns the viewport.
- Data labels: money uses one million-dollar unit cue per criteria group or metric heading. Percent and ratio headings carry `%`. Exact values, IDs, hashes, parser metadata, and diagnostic codes stay out of ordinary mode.
- Criteria catalog: searchable and grouped as growth, profitability, cash flow, financial stability, and reported items. Definition versions and scaling come from the dataset catalog; the browser never calculates financial metrics.
- Administration: collector inventory and unprepared candidates mount only under `?mode=admin`, never in the ordinary investor document.

## R2 company explorer addendum — 2026-10-09

- Default task: company explorer. It opens with the prepared 21-company matrix and common eight metrics before a condition or run exists. The metric guide is a separate task view so it does not form a long stack above screening results.
- Navigation: `기업 둘러보기 / 지표 안내 / 스크리닝 / 이력`. Historical-run context may change screening only; explorer and guide retain the latest verified v2 dataset and their own selected fiscal year.
- Fiscal-year context: use the latest year common to every company when one exists. Show every published year with coverage, preserve all company rows for a partial year, and say `선택 연도 자료 없음` rather than substituting another year.
- Profile: the drawer can open directly from the company matrix. Common eight summaries lead, 31 grouped values follow, and a selected metric shows four published fiscal years as a table plus modest SVG geometry. A missing year breaks the line.
- Compare: two to four selected companies, one to 31 existing metrics, and each company’s actual period. There is no average, score, rank, or peer-equivalence cue.
- Compact widths: keep the company matrix as the horizontally scrollable focal surface. Controls become two columns at 1,024px and one column at 760px; task sections do not stack simultaneously.
- Period captions: prepared API dates remain canonical exclusive-end dates. Ordinary captions subtract one UTC day for an inclusive display end and explain that convention.
- Reference patterns checked 2026-10-09: [Koyfin functionality](https://www.koyfin.com/help/topic/functionality/) for reusable column views and company history chart/table, [TradingView financial data](https://www.tradingview.com/support/solutions/43000543506-how-to-access-financial-data-on-tradingview/) for statement-group discovery, and [Finviz Screener](https://elite.finviz.com/help/screener) for dense financial column views. Only hierarchy and interaction patterns are used; no external assets, values, scores, or definitions are copied.
