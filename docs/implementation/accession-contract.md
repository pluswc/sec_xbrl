# Accession Ingestion Contract

## 1. Goal
Reuse the existing accession collection process as the upstream `Filing Discovery` component. Do not rebuild discovery inside the XBRL parser.

The downstream pipeline begins from an accession record and resolves the filing package (`index.json`, instance/inline document, schema and linkbases) needed by Arelle.

## 2. Existing process to preserve
The existing process already follows the appropriate pattern:
- CIK list -> `data.sec.gov/submissions/CIK##########.json`
- filter 10-K / 10-Q and amendments
- collect accession and filed date
- incremental/idempotent processing
- SEC User-Agent and rate limiting

Existing internal storage, `.done` markers or database upsert behavior can remain unchanged.

## 3. Minimal downstream contract
An adapter must yield one record per discovered filing with at least:

| Field | Required | Description |
|---|---:|---|
| `cik` | yes | zero-padded 10 digit or canonical numeric CIK |
| `accession` | yes | canonical accession with hyphens |
| `form` | yes | 10-K, 10-Q, 10-K/A, 10-Q/A |
| `filed_date` | yes | SEC filing date |
| `report_date` | recommended | report/period end when available |
| `primary_document` | optional | can be enriched from submission/index |
| `is_xbrl` | optional | downstream may verify |
| `is_inline_xbrl` | optional | downstream may verify |
| `source` | recommended | e.g. `sec_submissions` |

Derived helper fields may include `accession_nodash`, but the original accession with hyphens must be preserved.

## 4. Adapter interface
Recommended boundary:

```python
@dataclass(frozen=True)
class FilingRef:
    cik: str
    accession: str
    form: str
    filed_date: date
    report_date: date | None = None
    primary_document: str | None = None
    is_xbrl: bool | None = None
    is_inline_xbrl: bool | None = None
    source: str = "existing_accession_collector"

class AccessionProvider(Protocol):
    def iter_filings(self, *, forms: set[str]) -> Iterable[FilingRef]: ...
```

Implement adapters for the current output format (DB, JSON, parquet, directory metadata, etc.).

## 5. Downstream responsibility
Given `FilingRef`, the XBRL pipeline owns:
1. SEC archive path construction.
2. filing `index.json` fetch/cache.
3. identify Inline XBRL/instance/schema/linkbase files.
4. fetch/cache required package.
5. load with Arelle.
6. Layer 1 extraction.

## 6. Idempotency boundary
Discovery idempotency and parsing idempotency are separate.

Recommended parse key:
`(cik, accession, parser_version)`.

Do not reuse the collector's `.done` marker as proof that XBRL parsing succeeded. Maintain a separate parse state or manifest.

## 7. Failure handling
Record failures by accession with stage:
- `DISCOVERY_ADAPTER`
- `INDEX_FETCH`
- `PACKAGE_RESOLUTION`
- `DOWNLOAD`
- `ARELLE_LOAD`
- `LAYER1_EXTRACT`
- `VALIDATION`

A failed filing remains retryable without altering the upstream discovery record.

## 8. Migration rule
If the existing collector lacks `report_date`, `primary_document`, or XBRL flags, do not modify it immediately. Enrich these fields in the downstream resolver from SEC metadata. Only change the collector if a field is demonstrably needed for discovery itself.
