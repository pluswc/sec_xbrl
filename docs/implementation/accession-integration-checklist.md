# Existing Accession Collector Integration Checklist

## Step 1 — Inspect, do not rewrite
Locate the current collector entry point, output storage and one real output sample.
Record:
- output medium: DB table / JSON / parquet / directory metadata
- CIK representation
- accession representation (hyphenated vs no-dash)
- forms collected
- filed/report dates
- amendment handling
- idempotency marker/upsert key

## Step 2 — Choose adapter boundary
Preferred order:
1. If collector already exposes a stable Python function/query: write a thin provider around it.
2. If it writes a DB/table: write a read-only DB adapter.
3. If it writes files: write a file adapter.

Do not make the XBRL parser import internal crawler modules unless that API is intentionally stable.

## Step 3 — Normalize to `FilingRef`
Map existing columns/keys into the contract. Preserve the original accession and source fields.

## Step 4 — Enrich downstream only when needed
Missing `report_date`, `primary_document`, `is_xbrl`, or `is_inline_xbrl` can be added by the Filing Package Resolver using SEC metadata.

## Step 5 — Separate processing state
Collector complete != parser complete. Maintain parser state keyed by accession and parser version.

## Step 6 — Contract tests
Create tests using a small anonymization-free sample of actual collector output. Verify:
- 10-K, 10-Q, 10-K/A, 10-Q/A parse correctly
- CIK and accession are normalized without information loss
- invalid form/date/accession errors are explicit
- repeated reads are deterministic

## Step 7 — Only then implement M1
Once the adapter contract passes, implement SEC archive/index/package resolution. No accession discovery code should be added to M1.
