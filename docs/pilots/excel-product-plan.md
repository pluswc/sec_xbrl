# Excel product plan — AMD · MSFT · META workbench

This workbench preserves the pilot outside the M0–M9 core product. Its Excel
experience should answer three questions without hiding as-filed meaning:

1. **Peer view:** which reported totals may be inspected side by side, in one
   period class, and what blocks comparability?
2. **Company view:** which selected reported revenue rows describe one
   company, including dimensions and scope?
3. **Evidence view:** where did a number, relationship decision, and warning
   come from in the filing?

## Recommended workbook navigation

`Start_Here` explains scope and has links to three journeys: `Peer_Review`,
`Company_Revenue`, and `Evidence_Trace`. The pilot's existing `Overview`,
`Revenue_Dashboard`, `Revenue_Structure`, `Peer_Comparison`, and
`Source_Trace` can be regrouped under those journeys; disclosure and backlog
remain specialist review tabs. The user-facing sheets show concise labels,
numeric values, period class, dimensions, and warnings. Provenance stays in a
separate trace sheet, reached by a stable raw ID/link rather than duplicated
as overwhelming UI text.

Every peer screen must visibly segregate FY, QTD_3M, and YTD_9M. A displayed
group is not a ranking or accounting-equivalence claim. `UNRESOLVED` and
`NOT_COMPARABLE` remain user-visible states, not blanks.

## Depth and relationship semantics

`Display depth` is only indentation/order. PRE provides presentation placement
and context; it is never a free graph-expansion edge. DEF evidence may be
shown only for allowed dimensional arcs and its explicit `targetRole`; absent
evidence is `NOT_EVIDENCED`, never inferred. `Scope depth` is a dimension
count. A multi-axis fact (for example Meta advertising within Family of Apps)
has scope depth two, but that does not prove a member hierarchy, aggregation,
or composition.

## Delivery milestones

1. **Navigation shell:** add `Start_Here` and journey links; acceptance: a
   first-time user reaches peer/company/evidence paths with no filtering
   knowledge.
2. **Peer guardrails:** period-class selector and comparability banner;
   acceptance: no chart combines duration classes and every peer row exposes
   relation/confidence.
3. **Company composition review:** selectable company/period structure;
   acceptance: only reported selected rows, dimensions and non-aggregate
   wording are retained.
4. **Evidence bridge:** materialize fact-level PRE/DEF records from Layer 1;
   acceptance: each shown relationship has network type, role, relationship,
   locator, and targetRole where applicable, or is explicitly unavailable.
5. **Usability QA:** workbook inspection with analysts; acceptance: source
   links, filters, warning colors, and numeric cells remain intact.

## Out of scope

This plan does not expand the pilot to all four financial statements, invent a
common revenue taxonomy, infer cloud revenue, create composition aggregates,
or modify M0–M9 raw/canonical/cross-company contracts. Those require separate
evidence and product decisions.
