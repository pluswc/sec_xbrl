# T2 — Filing-versioned Relationship Index

## User effect

This index lets an analysis view answer “what did this specific filing show as
the structure around this line item?” without reopening the XBRL package or
mixing relationship networks. For example, a user can open NVIDIA's revenue
line in a particular 10-Q and separately inspect its presentation hierarchy
(`PRE`), calculation decomposition (`CAL`), and dimensional structure (`DEF`).

It does **not** claim that a PRE child is a calculation component, that a CAL
edge proves an economic driver, or that a relationship in a later filing
replaces one in an earlier filing.

## Published operational Parquet datasets

- `filing_relationship_edge`: one immutable Layer 1 relationship per row. It
  retains filing snapshot/accession/form/filed date/amendment state;
  relationship ID; PRE/CAL/DEF network type; role ID/URI/definition; arcrole;
  fully specified link and arc QName; raw parent and child QName, namespace,
  taxonomy family/version and local name; `targetRole`; and all retained edge
  attributes. Canonical concept IDs and complete map lineage are additive on
  each endpoint; a missing map stays null/review-required.
The source mapping record is embedded as endpoint lineage. The full mapping
tables are independently published by T1 and are not duplicated by T2.

There is no edge traversal, network merge, value selection, recast policy,
Q4 derivation, subtotal inference, or driver inference in T2.

## Retrieval

`FilingRelationshipIndexReader.get_filing()` and `edges_for_concept()` accept
a verified Layer 2 publication. They return raw edges, retaining filing, role,
link/arc QName and network distinctions; `edges_for_concept()` supports
incoming, outgoing and both directions by exactly one raw or canonical
endpoint identity.

For a fast filing serving query, `query_parquet(accession=...)` reads only
`<run>/<cik>/filing_relationship_edge/<accession>.parquet`, after validating
the small run manifest and every returned edge against its declared Layer 1
input. It never opens other companies' or other filings' Parquet partitions.

## Boundary

T2 is the relationship counterpart to T1's versioned reported-period facts.
Together they make the raw time and structure axes available to a later
analysis-view definition. The analysis-view layer owns which rows are shown,
which values are selected at a given date, and which cross-statement links or
derived ratios are useful to a user.
