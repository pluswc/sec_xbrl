# Investor financial workbench interface system

Current locally accepted phase 2 source: `745bc76e3a4721de8d7734eb534ac0afc7cba212`
(2026-11-13). Independent Node 116/Ruff/diff and lead exact-bundle preview/live-browser
acceptance passed. The effective CSS viewport checks below are complete; actual browser zoom
was not verified. Phase 1 is merged in main `0a89d5cf` through PR91 (CI 43427104449 passed).
Phase 2 is merged through PR92; governed latest-period/revenue UI scope fixes are now in
main PR95 (`ebdbe938d7`). Information-consistency frontend changes are merged through PR96 (`deb074bc49`).
The prepared-screening-change registration candidate below is separate and awaits verification/acceptance.
The source dataset determines company/metric counts; examples such as 21 or 50 companies are
fixtures and never the supported-company boundary.

## Direction and hierarchy

A calm investor worksheet: use the company matrix to find candidates, then let a selected
company's financial levels and prepared changes own the analysis screen. Preserve list state
instead of building a second independent query. Use financial comparisons as the visual focus;
technical provenance belongs in explicit evidence, never a substitute for missing/quality reasons.
Phase 1 covers explorer/detail/comparison. Phase 2 adds the guide selection/detail, history ledger
and adjacent screening review described below. Further repeated-action redesign is deferred.

- Palette: ledger ivory canvas, filing-paper panels, dark ink, filing slate, annotation blue,
  review amber, blocking red. Color communicates state/action, with text and dash styles too.
- Spacing: 4px base; 8px within controls, 12px between related blocks, 16px between sections.
- Type: local Korean UI fonts; 14px table/body figures, 12–13px context, 11px minimum axis text,
  18px section title and 24–36px task title. Density changes padding, not financial figure size.
- Depth: quiet borders/surface shifts; rounded 8px controls and 12px panels. No repeated card
  decoration for every financial value. A pinned chart explanation may overlay its own plot.
- Native controls and visible focus: buttons, selects, checkboxes and details. Keep keyboard
  order equal to visual order, Escape handling local to active explanations before closing views.

## Desktop viewport and density targets

- Primary design viewport: **1920×1080**. Required smaller desktop: **1440×900**.
  Expanded desktop: **2560×1440**. The default first financial level/change pair should
  finish inside the primary and required desktop viewport before optional evidence is opened.
- Target four financial cards at 1920, three at 1440 when container width permits, and a
  maximum of four at 2560; retain minimum readable charts rather than stretching typography.
- Standard controls target about **40px** height. Ordinary list rows target **44–48px**, with
  more height when names, actual periods or meaningful status require wrapping. These are design
  targets, not a claim that every measured row is 44px; compact mode changes padding only.
- Check layouts corresponding to **125%/150%** scaling: effective CSS viewports such as
  1536×864 / 1280×720 from 1920×1080, and 1152×720 / 960×600 from 1440×900.
  Equivalent CSS viewport checks validate layout availability, not actual browser zoom;
  report actual zoom verification separately. Retain the 390px basic-function fallback.

## Explorer and analysis

- Company explorer is the default task. Company count, prepared periods and available metrics
  come from the selected immutable publication and availability context.
- The list uses the remaining viewport, internal horizontal/vertical scrolling, sticky company/
  selection columns, precise numeric sorting and missing-last behavior. Standard/compact row
  density must retain 14px figures and full labels/periods through accessible descriptions.
- Opening detail/comparison collapses the list into an analysis context with a nearby back action.
  Returning restores query, preset, sort, basis/latest/fixed period, selection and both scroll axes.
  Return focus uses the original list trigger with preventScroll, or a safe visible fallback.
- Company navigation follows the current filtered/sorted list, with that scope stated. Async
  success/error belongs only to the current company/basis/context and cannot reopen a closed view.
- A narrow desktop task rail becomes a compact horizontal strip at small widths. Never hide
  a required action at effective zoom widths or on the 390px fallback.

## Financial detail and dates

- Detail is a full-width inline analysis workspace, not the old fixed 570px company drawer.
  Major summary values remain available in a default-collapsed native disclosure. Bounded
  category ledgers retain all metrics and visible missing/quality explanations.
- Financial boards use catalog groups plus core/custom selections, independent group order and
  a maximum of eight selected metrics. Use 1/2/3/4 columns from actual container width, maximum
  four at large desktop widths. Each card keeps level above a smaller prepared YoY/%p plot.
- Money displays in million USD with zero decimals; PERCENT uses one decimal; RATIO uses its
  declared multiples with appropriate existing precision. Tiny nonzero values use signed bounds,
  not a false zero. Exact decimal values/units stay in native titles and evidence.
- General dates use YY.MM.DD and ranges such as 24.09.29–25.09.27. True FY/company quarter labels
  remain full. Full ISO captions remain in title/accessibility/evidence; state-bearing DOM/input
  values stay canonical. Exclusive-end conversion and all accounting period policy stay upstream.
- Deduplicate an FY label only when it repeats the same company's same prepared fiscal year.
  Do not erase mixed company FY labels or turn TTM into a calendar-quarter financial period.

## Comparison and chart interaction

- Select two to four companies using the shared checkbox/chip registry. Metric comparison uses
  search/category checkboxes and removable selected chips; the existing native select can remain
  a hidden adapter. Search filters choices and never removes selected metrics.
- Changes immediately invalidate old requests, then refresh prepared comparison data. Empty
  metrics or invalid company counts need a visible explanation. No browser financial arithmetic,
  derived ratio policy, scores, averages or claims of accounting equivalence.
- Keep chart/table close on wide desktop and stack at narrow widths. Metric/units sit consistently
  above plots and shared-period readouts below. Use FCF as an approved short display title with
  its full catalog label available; source definitions never change with the alias.
- Revenue supports prepared segment/product/geography views with exact full scope, mapping
  epochs, hierarchy and missing reasons. Overlapping components do not form an inferred 100%.
- Nearby legends retain full names via title/accessibility. Hover/focus links the item/period across
  related plots, click/Enter/Space pins, arrows select periods, and Escape clears explanations.
  Pin/focus survives resize and late responses within a valid scope; company/basis changes clear it.
  Programmatic focus restoration must not reopen an explanation just cleared with Escape.

## Screening, history and boundaries

- Screening is a bounded native worksheet with precise editable thresholds, separate condition/
  result saves, compact metadata groups and content-sized result columns. A changed draft must
  not masquerade as the displayed prior result. Preview never implicitly saves a result.
- History preserves definitions/revisions/runs/lifecycle records, explicit save/reopen/export and
  reversible bulk/trash actions. Presentation state is ephemeral and not journal persistence.
- Raw/Analytical/Derived data and exact publication ownership stay governed upstream. Display
  consumes them without source parsing, recast selection, arithmetic or fabricated gap filling.


## Desktop phase 2 — locally accepted (2026-11-13)

Phase 1 is incorporated through PR91 in main `0a89d5cf`; CI run 43427104449 passed. Phase 2 retains paper/ink/slate/annotation blue/review amber, 14px reading text, native controls and the 4px spacing scale. The guide uses a bounded annual metric list beside one selected detail; empty search hides detail without losing scoped input drafts. History uses adjacent ledger rows, explicit visible-scope search/type filters and original timestamps/IDs in accessible details. At wide desktop widths screening conditions sit beside their last result, with explicit draft-versus-executed state; smaller widths stack. No accounting, storage or source-data policy changes.

All tabs were audited; guide/history/screening were selected for this phase, while the existing
explorer/profile/comparison/revenue workspaces were preserved and regression-tested. Shared
cross-tab scroll memory and further saved-result comparison layout cleanup remain unimplemented,
lower-priority candidates, not automatically authorized follow-up work.


## Information consistency contract — implemented candidate, acceptance pending (2026-11-14)

Use one metric presentation/capability vocabulary in explorer, profile, comparison, guide and
screening: catalog full name and exact definition/unit, FY/quarter/TTM basis, published comparison
kind (YoY/QoQ/TTM YoY or percentage points), source and unavailable reason. Display rounding
never changes raw values or editable thresholds. A PERCENT catalog ratio stays percent; do not
rename it as a multiple. Separate data availability from registered-condition capability.
Board adjunct comparisons that lack a screening catalog definition say “상세 비교 전용 · 조건 미지원”.
Only registered governed catalog metrics can become conditions; never calculate new browser
conditions or infer a comparison formula. Default explorer eight metrics stay unchanged; expanded
columns remain explicit ephemeral display selections. Historical screening analysis pins the run's
publication and period and returns to its original draft/result/selection/scroll context.
Different metrics get independent axes with visible units and company-consistent colors. Preserve
existing amount/index100 behavior, exact evidence, missing gaps, source scopes and keyboard/pins.

Comparison starts with the catalog's revenue, operating income, CFO and standardized FCF
levels when present, keeping their prepared changes paired without a duplicate YoY default
selection. Every registered metric remains selectable. A historical result-profile session is
read-only; condition links additionally require matching dataset, publication and financial cutoff.
The candidate's writer checks passed (Node 138/Python 35/Ruff/diff); independent and final
browser acceptance remain pending.

## Prepared screening changes (candidate, 2026-11-14)

- The selected publication owns capability. A registered comparison pair declares
  `comparison_of`, `comparison_kind` and its exact source definition version. Connect
  the same published value to conditions, company detail and multi-company comparison.
- Ordinary monetary YoY uses `%`; ratio differences use `%p` with raw threshold 1
  meaning one percentage point. Current/prior ratio inputs remain `%`, never `%p`.
  A prepared change metric does not acquire another automatically derived change pair.
- Preserve the visible sign/zero/missing reason and exact evidence when ordinary numeric
  YoY is unavailable. Old publications retain their detail-only adjunct and labels.
- No browser calculation or new display layout is introduced. Implementation/independent
  verification and actual publication/acceptance remain separate in the milestone contract.

## Reviewed Q4 revenue companion

Keep reported same-filing YoY distinct from `Q4 전년비 · 연간−9개월 계산`.
The latter exposes its current/prior Q4 amounts, actual periods, paired input sources,
comparison-only retrospective presentation when applicable, and arithmetic-only assurance.
Amount/share/YoY readiness is independent; a missing denominator does not hide a valid amount.
Distinguish absent prepared input from an unresolved scope or a source tag/table conflict;
`공시 태그와 표의 항목 불일치 · 계산 보류` does not mean no disclosure exists.
Keep original Raw/T1 and accepted amount/source values unchanged. Review evidence grants
never silently merge labels/epochs or connect unapproved chart edges. Retain the current layout.
