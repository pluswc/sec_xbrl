# Reviewed dimensional Q4 and annual consumer bundles

The reviewed-Q4 producer is an offline, immutable companion. It requires one
exact history publication, the source-pair evidence JSON, and the lead approval
ledger. It does not read or promote the older mechanical-Q4 candidates.

The approved initial paths are:

```text
HISTORY=/home/plusbdw/user_work/projects/sec_xbrl/data/processed/analytical/history/five_company_custom_continuity_v5/panels
SOURCE_PAIRS=/home/plusbdw/user_work/projects/sec_xbrl/data/processed/universe_runs/20261008_initial/q4_lead_review/source_pairs.json
LEAD_APPROVAL=/home/plusbdw/user_work/projects/sec_xbrl/data/processed/universe_runs/20261008_initial/q4_lead_review/lead_approval.json
```

Run the following from the repository checkout with its virtual environment.
Choose new destinations because every producer refuses to overwrite an existing
publication.

```python
from pathlib import Path

from sec_xbrl.analysis import prepare_analysis
from sec_xbrl.analytics.reviewed_q4 import publish_reviewed_q4

history = Path(
    "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/analytical/"
    "history/five_company_custom_continuity_v5/panels"
)
evidence = Path(
    "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/universe_runs/"
    "20261008_initial/q4_lead_review/source_pairs.json"
)
approval = evidence.with_name("lead_approval.json")
run = Path(
    "/home/plusbdw/user_work/projects/sec_xbrl/data/processed/universe_runs/"
    "20261008_initial/reviewed_q4"
)

reviewed = publish_reviewed_q4(
    history_publication=history,
    source_evidence=evidence,
    review_ledger=approval,
    destination=run / "publication",
)
prepare_analysis(
    publication=history,
    destination=run / "quarterly-consumer",
    tickers=("NVDA",),
    fiscal_start=2024,
    fiscal_end=2026,
    reviewed_q4_publication=reviewed,
)
prepare_analysis(
    publication=history,
    destination=run / "annual-consumer",
    tickers=("NVDA",),
    fiscal_start=2024,
    fiscal_end=2026,
    period_mode="ANNUAL",
)
```

Set `PYTHONPATH=<checkout>/src` when the package is not installed. These calls
perform no network access. The history selection remains as-of `2026-09-06`;
the 2026-10-08 review time is separate evidence and does not replace that date.

Verify and inspect the immutable companion with:

```python
from pathlib import Path

from sec_xbrl.analytics.reviewed_q4 import ReviewedQ4Reader

reader = ReviewedQ4Reader(Path("<run>/publication"))
reader.verify_all()
print(reader.manifest["counts"])
print(reader.records("derived"))
print(reader.records("exclusion"))
```

The initial expected counts are 32 candidates, 32 approvals, 32 derived
view-specific records, and four policy exclusion notes. The 32 records represent
16 approved economic product-period values in `AS_FILED` and the same 16 exact
source decisions in `LATEST_REPORTED`. A missing or changed decision leaves the
coordinate unavailable or causes integrity validation to fail.

Use the ordinary prepared API and export boundary. They display the supplied
value and trace without calculating Q4:

```python
from pathlib import Path

from sec_xbrl.analysis import open_analysis
from sec_xbrl.consumer.export import export_snapshot, prepare_axis_snapshot

client = open_analysis(Path("<run>/quarterly-consumer"))
overview = client.overview(
    "NVDA", fiscal_start=2024, fiscal_end=2026, view="LATEST_REPORTED"
)
groups = client.list_breakdowns(
    "revenue", context=overview["context"], include_hidden=True
)["groups"]
product_lens = next(group for group in groups if group["lens_type"] == "DIMENSIONAL_VIEW")
table = client.axis_timeseries(
    "NVDA", product_lens["node_id"], context=overview["context"]
)
snapshot = prepare_axis_snapshot(
    client, "NVDA", product_lens["node_id"], context=overview["context"]
)
export_snapshot(snapshot, Path("nvda-reviewed-products.xlsx"))
```

For annual output, open `<run>/annual-consumer`. Its manifest declares
`period_mode: ANNUAL`; all prepared duration columns and axis responses use
`FY`, and exports label columns `FY2024`, `FY2025`, and `FY2026`. Quarterly and
annual publications must remain separate destinations.
