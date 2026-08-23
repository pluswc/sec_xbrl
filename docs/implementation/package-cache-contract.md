# M1A/M1B Package Cache Contract

Input is one `FilingRef`. M1A downloads only the accession XBRL ZIP and SEC
index-headers HTML; M1C adds a separate immutable cache for SEC filing
`index.json` resolution and an offline Arelle load.

## Layout

```text
data/raw/sec/packages/{cik}/{accession_nodash}/
  {accession}-xbrl.zip
  {accession}-index-headers.html
  manifest.json
```

## M1C — Filing index and Arelle entry point

The filing directory response is stored separately from the immutable M1A
package, so adding index metadata never mutates a published package:

```text
data/raw/sec/filing-indexes/{cik}/{accession_nodash}/
  index.json
  manifest.json
```

The index manifest records the filing identity, SEC source URL, SHA-256, and
byte size. A partial, corrupt, or identity-mismatched index cache is never a
cache hit.

`directory.item` is parsed as untrusted SEC metadata. Filenames must be safe
relative paths. The resolver selects `FilingRef.primary_document` when it is
present in both the index and ZIP; otherwise it selects the unique
`EX-101.INS` file, or a single remaining HTML/XML candidate. Ambiguity is an
accession-level resolution error, rather than a guess.

The Arelle loader extracts the already validated ZIP to a caller-owned working
directory and passes Arelle only the local selected file. Its web cache is set
offline; M1C does not download or modify SEC source files during loading.

`manifest.json` records schema version, CIK, accession, form, package `source`,
and for every artifact its SEC source URL, SHA-256, and byte size. New packages
use schema version 2. `source` is `sec_archive` for downloads and
`legacy_xbrl_data_load` for M1B adoption.

## Invariants

- Publish via a temporary sibling directory followed by an atomic rename.
- A published manifest must validate every artifact before it is reused.
- A partial directory or hash mismatch is an integrity error, never a cache hit.
- A valid package is immutable and causes no network request on reuse.
- SEC requests use an explicit User-Agent, bounded retry, and rate-limit delay.

## M1B — Legacy package adoption

`XbrlDataLoad` remains a read-only reference. Its documented legacy layout is:

```text
{legacy_data_root}/{index_date}/index.json
{legacy_data_root}/{index_date}/{accession}/
  {accession}-xbrl.zip
  {accession}-index-headers.html
```

The date index contains a `filings` list with `adsh`, `cik`, and `form`.
M1B does not import the legacy project's code, trust its mutable paths, or alter
its data. For each requested `FilingRef`, it must:

1. find exactly one legacy index record for the accession;
2. require the index CIK, accession, and form to match the request;
3. require non-empty ZIP and header files at the documented location and a
   structurally valid ZIP;
4. copy both files into a temporary sibling destination while calculating
   SHA-256 and byte size, then publish only after the normal manifest validation
   succeeds atomically;
5. write `source = "legacy_xbrl_data_load"` in the destination manifest.

Missing root/index/accession/files, invalid ZIPs, ambiguous index records, and
identity mismatches are rejected with stable, accession-level error codes. A
rejected package never creates or replaces a destination package.
