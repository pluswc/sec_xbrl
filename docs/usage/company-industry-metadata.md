# Company and SEC SIC metadata usage

This workflow consumes cached SEC submissions root JSON.  It never fetches SEC
data and does not replace `CompanySubmissionsCollector`.

## Python build and publication

Give each cached observation a timezone-aware collection timestamp:

```python
from datetime import UTC, datetime
from pathlib import Path

from sec_xbrl.company_metadata import (
    CompanyMetadataReader,
    SnapshotInput,
    UniverseFilter,
    build_company_metadata,
    publish_company_metadata,
)

snapshot = SnapshotInput(
    Path("/runtime/sec-submissions/0000320193/<sha256>.json"),
    datetime(2026, 10, 8, 4, 30, tzinfo=UTC),
    source_url="https://data.sec.gov/submissions/CIK0000320193.json",
)
build = build_company_metadata([snapshot])
published = publish_company_metadata(
    build,
    Path("/runtime/universe/company-metadata-2026-10-08"),
)
```

When all paths came from one collection observation, bare paths may share the
same timestamp:

```python
build = build_company_metadata(paths, observed_at=collection_observed_at)
```

Use `cutoff=` only to select among metadata observations.  It is not the
analytical `as_of_date`, and the selected current SEC SIC must not be described
as a historical classification at that date.

Publishing creates:

```text
company_metadata_manifest.json
companies.parquet
company_identifiers.parquet
industry_classifications.parquet
```

Publishing the identical build to the same destination reuses the validated
publication.  Different content at that destination raises an immutable
collision; choose a new destination.

## Optional broader candidate inventory

A cached SEC ticker/exchange candidate inventory may broaden the issuer list:

```python
from sec_xbrl.company_metadata import CandidateInventoryInput

inventory = CandidateInventoryInput(
    Path("/runtime/sec/company_tickers_exchange.json"),
    inventory_observed_at,
)
build = build_company_metadata(
    root_snapshots,
    observed_at=collection_observed_at,
    candidate_inventory=inventory,
)
```

Inventory-only issuers are retained with `CANDIDATE_ONLY`,
`ROOT_METADATA_UNAVAILABLE`, and `NOT_CLASSIFIED`.  A pilot with SIC-bearing
root snapshots therefore cannot imply complete SIC coverage for the wider SEC
inventory.

The accepted SEC inventory form is the public `fields` plus `data` object using
`cik`, `name`, `ticker`, and `exchange` fields.  A `data` list of objects with
the same names is also accepted.  A missing exchange is retained and produces
`EXCHANGE_UNAVAILABLE` when an exchange filter is applied.

An optional cached SIC title reference may be passed as a JSON object from code
to title, or a list of objects with `sic`/`code` and `title`.  This supplements
the SEC description and creates no GICS or NAICS mapping.

## Query a governed candidate universe

```python
reader = CompanyMetadataReader(published.root)
rows = reader.list_companies(
    UniverseFilter(
        exchanges=frozenset({"Nasdaq", "NYSE"}),
        forms=frozenset({"10-K", "10-Q"}),
        sic_codes=frozenset({"3571"}),
        ciks=frozenset({"0000320193", "0000789019"}),
    )
)
```

Filters are conjunctive.  The result retains every published company and marks
eligibility and exclusion reasons.  A requested CIK absent from the publication
is returned as `UNAVAILABLE` with `METADATA_UNAVAILABLE`.  Missing SIC is
`INDUSTRY_NOT_CLASSIFIED`; it is never inferred from ticker, name, or labels.

```python
peers = reader.peer_candidates("0000320193")
```

Peer lookup returns other issuers with the same exact observed SEC SIC.  Each
result states that SIC is only a coarse candidate signal and is not accounting
equivalence.

## CLI

```bash
python -m sec_xbrl.company_metadata build \
  /runtime/sec-submissions/0000320193/root.json \
  /runtime/sec-submissions/0000789019/root.json \
  --observed-at 2026-10-08T04:30:00+00:00 \
  --destination /runtime/universe/company-metadata-2026-10-08

python -m sec_xbrl.company_metadata query \
  /runtime/universe/company-metadata-2026-10-08 \
  --exchange Nasdaq --form 10-K --form 10-Q --sic 3571

python -m sec_xbrl.company_metadata peer-candidates \
  /runtime/universe/company-metadata-2026-10-08 0000320193
```

For the optional candidate inventory, provide both
`--candidate-inventory PATH` and `--candidate-observed-at TIMESTAMP`.  CLI output
is JSON Lines suitable for downstream status or completion views.
