# T8 — Cross-company comparison panel

## Purpose

T8 is a read-only serving adapter for a single fiscal-year/quarter column from
two or more T6 quarterly analysis pivots. It makes comparable values and
unresolved values visible side by side without becoming a parser, selector,
recast engine, calculation engine, or peer-ranking product.

## Query boundary

Every input pivot must have a different CIK and the same `period_class`,
`selection_view`, and `selection_as_of_date`, as well as the requested fiscal
year and quarter. Any disagreement, missing selected column, or duplicate
company pivot fails closed. T8 does not silently choose a newer filing,
convert a period basis, or mix information available at different dates.

## Automatic baseline

Automatic `EQUIVALENT` requires two or more companies with an exact qualified
standard QName and matching non-empty taxonomy family, XBRL data type, concept
period type, and unit semantics. It accepts only undimensioned source cells.
The method is `EXACT_STANDARD_TAXONOMY_IDENTITY`; evidence includes the
semantic tuple plus consolidated filing/raw-ID evidence for every company.
Labels, local names, values and superficially similar extension concepts never
produce a relation.

The rule is not a hard-coded US taxonomy allowlist: any Layer 1-qualified
standard family (for example `ifrs-full`) may qualify if its full exact
identity is shared. Taxonomy namespace/version remains provenance and is not
an undocumented matching gate.

The source taxonomy family, version and namespace URI remain on every company
cell and in company-specific mapping evidence. Version/URI are audit evidence,
not automatic identity keys, so annual standard-taxonomy namespace changes do
not incorrectly split a comparable exact QName.

Company extensions, dimensioned facts, missing type metadata and
measurement-incompatible standard concepts remain individual `UNRESOLVED`
rows. They are retained rather than filtered out.

## Reviewed mapping and output

Reviewed inputs may add only `SUBCATEGORY_OF`, `SUPERSET_OF`, or
`ANALYTICALLY_SIMILAR`; each requires `review_state=REVIEWED`, evidence,
method and mapping version. An empty evidence object is rejected. Similarity remains similarity in every output
cell. Mapping-key collision validation rejects an explicit mapping that would
replace an automatic standard identity map.

Every company cell keeps raw/company IDs, all mapping relation fields, source
filing/period, and whole T6 row/cell plus T5 definition/binding/value lineage.
T8 does not create ranks, averages, peer metrics, charts, recasts, or
cross-company calculations.
