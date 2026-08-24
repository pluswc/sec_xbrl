# AMD · MSFT · META Revenue dashboard — pilot scope

`Revenue_Dashboard` is a user-facing display of reported total revenue. Its
current comparison chart contains only `QTD_3M` rows, so FY and YTD facts are
not mixed. It is not a ranking, forecast, composition aggregate, or an
accounting-equivalence claim: every displayed current total-revenue relation
remains `UNRESOLVED`.

`Revenue_Structure` is a reported-row view. `Display depth` is indentation for
reading (total `0`, selected breakdown `1`), while `Scope depth` is simply the
number of dimensions on that fact. A scope depth of `2` is present for Meta's
Family of Apps advertising fact (product/service and segment axes); it does
not evidence that either member is a child of the other, or that it composes a
total. No composition aggregate is calculated.

Presentation evidence is limited to placement/order/context and never used to
expand a path. Definition evidence would require an allowed DEF arc and any
explicit `targetRole`; the workbook never infers either. The current P2/P3
export interface does not carry fact-level relationship rows into the Excel
view, so cache export shows `NOT_EVIDENCED`; committed-summary export shows
`DOCUMENTED_SUMMARY_ONLY` with `NOT_AVAILABLE` role/relationship fields.
Those states are intentionally visible rather than fabricated.

The dashboard is revenue-only and does not change P2/P3 metric selection,
canonical IDs, mapping relations, source provenance, or scope warnings.
