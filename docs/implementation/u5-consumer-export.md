# U5 prepared consumer export contract

## Scope and acceptance

U5 saves the selected prepared core overview or one prepared Axis time-series
table for local archival and sharing. The accepted vertical slice is one
canonical snapshot API and CSV, HTML, XLSX, and JSON renderers over that exact
snapshot. It is downstream of `AnalysisClient`: it never collects or parses a
filing, selects a filing/recast, calculates an accounting value, approves a
mapping, or combines independent Axis views.

The canonical APIs are:

```python
from pathlib import Path
from sec_xbrl.analysis import open_analysis
from sec_xbrl.consumer.export import export_snapshot

client = open_analysis(Path("/prepared/admin"))
snapshot = client.overview_snapshot(
    "NFLX", fiscal_start=2023, fiscal_end=2026,
    periods=[(2026, 2), (2026, 1)], row_ids=["revenue"],
)
export_snapshot(snapshot, Path("/archive/nflx-revenue.xlsx"))

context = client.overview("NFLX", fiscal_start=2023, fiscal_end=2026)["context"]
axis = client.axis_snapshot("NFLX", "prepared-lens-id", context=context)
export_snapshot(axis, Path("/archive/nflx-axis.csv"))
```

Explicit period and row sequences define both selection and output order.
Unknown or duplicate identities fail; the exporter never fabricates a period.
Overview row period classes remain separate even though the XLSX `Table` sheet
shows one fiscal-quarter column per visible UI quarter. The display divisor is
fixed at `1` (prepared raw unit); the complete numerator/denominator and
dimension evidence remains in each cell and its provenance.

## Snapshot guarantees

Every snapshot binds the analysis publication, view, as-of date, review cutoff,
source publication, selected rows and periods, warnings, status/reason, unit,
basis and full dimensions. Reported, derived, and unavailable outputs remain
distinct. A quality `BLOCK` exports a blank display value; its raw amount is
retained only as `raw_value_lineage_only`. Null is never converted to zero and
the exporter does not assert disclosure absence for a sparse overview cell.

Cell provenance is complete and fail-closed for reported/derived cells.
Selected derived metric records retain formula/rule/input IDs, and the
referenced prepared input cells and traces are embedded as `inputs_only` even
when outside the visible partial selection. Axis snapshots retain analysis and
companion publication IDs, reviewed relationships, source-comparison evidence,
mapping epochs, importance and warnings. Partial selection records every
excluded required/protected/warning row and excluded quality-warning cell.

`snapshot_id` is the SHA-256 of the canonical snapshot content. Export rejects
a snapshot whose content no longer matches that hash.

## Format behavior

- JSON is the canonical snapshot.
- CSV contains one `SNAPSHOT` record with all non-cell structures and one
  `CELL` record per selected cell containing full cell/provenance JSON.
- HTML presents the table and embeds the complete canonical JSON in an
  `application/json` element.
- XLSX has `Table`, `Cells`, `Provenance`, and `Metadata` sheets. `Table` is the
  row-by-quarter view; the other sheets preserve the exact long-form cells and
  reconstructable canonical snapshot. JSON is chunked below Excel's 32,767
  character cell limit with explicit part numbers.

CSV text beginning with formula trigger characters is escaped. HTML escapes
markup while preserving signed values, and XLSX stores every cell explicitly
as a string, so formulas do not execute and amounts beyond Excel's 15-digit
numeric precision stay exact. Canonical JSON chunks are stored verbatim and
reconstruct losslessly.

The offline hierarchy screen exposes direct links for all four formats while
in Analytical mode. The links follow the selected company, core metric, or Axis
table. They save that whole prepared table and include rows hidden by the
screen-only collapse/depth controls. Source and PRE modes disable U5 exports.
Arbitrary row/period partial exports use the Python API above.

## Delivery boundary

The U5 candidate is based on completion baseline `51c196f`. The lead retains
the prior local delivery boundary: there is no push, PR, CI, or merge in U5 implementation.
This is a documented exception to the delivery workflow's remote freeze step.
Independent verification must use the final local commit SHA; local acceptance
and `main` merge status remain separate decisions.
