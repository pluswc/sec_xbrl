# L2-M5 Capability Inventory and Discovery Contract

`capability_inventory` is the Layer 2 discovery dataset.  It answers what a
specific company has actually made available to the analytical pipeline before
a consumer asks for a series, report, or spreadsheet.  It is an Analytical
Plane output; it neither changes Layer 1 data nor creates an Excel/API view.

## Source and grain

`CapabilityInventoryMaterializer` reads M3 company-series candidates, M4
analytical-fact selection results, and M1 exclusions.  An optional Layer 1
statement/disclosure evidence lookup can enrich the source role, disclosure,
document, and locator.  It produces:

- one `CONCEPT` row for an observed candidate concept;
- one `DIMENSION_MEMBER` row for each observed Axis/Member assignment; and
- a `COMPANY_COVERAGE` processing row only when a declared company has no
  materialized L2 candidate at all.

There is no product, segment, geography, or statement template.  A Member
exists in the inventory only if an input candidate actually reported it.
`period_classes` and `series_types` remain explicit, so QTD/YTD/FY/INSTANT
are not coalesced by discovery.

## Status contract

The persistent dataset has exactly these statuses:

| Status | Meaning |
| --- | --- |
| `AVAILABLE` | Observed candidate whose mapping and selected input are usable. |
| `PROCESSING_UNAVAILABLE` | A source Fact was observed but could not be safely materialized, or no L2 input exists for a declared company. |
| `MAPPING_REVIEW_REQUIRED` | The observed candidate has unresolved company canonical mapping evidence. |
| `NOT_COMPARABLE` | The candidate exists, but M4 selection marked its requested current/comparable basis unavailable. |

`NOT_REPORTED` is deliberately a **query result**, not a stored generic
missing row.  `CapabilityInventoryQuery.discover()` returns it only when a
known company has no observed company-specific structure matching the exact
requested Concept/Axis/Member/period filter.  It cannot be interpreted as a
claim that every company lacks an unrequested disclosure.

## Drill-down and publication

Every stored row retains raw and canonical Concept identity where available,
observed Axis/Member, period/series types, source Fact and filing IDs, series
candidate IDs, mapping version, selection rule version, and any supplied
role/disclosure/document/locator evidence.  Missing role evidence stays
empty; it is never inferred from labels.

The dataset is accepted by the L2-M0 `Layer2Publisher`, remains subject to its
atomic publication and run-manifest rules, and is written only to ignored
operational Layer 2 storage.  The query boundary is read-only and returns
copies, so consumers cannot alter inventory policy.
