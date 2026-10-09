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
