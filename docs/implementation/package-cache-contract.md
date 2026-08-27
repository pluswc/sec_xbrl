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
relative paths. A `FilingRef.primary_document` supplied by Filing Discovery is
also treated as untrusted: the resolver selects it only when it is a safe
relative path and is present in the validated same-accession XBRL ZIP. SEC may
legitimately omit that HTML document from `directory.item` while including it
in the XBRL ZIP, so its absence from the directory index alone is not a
resolution error. If Discovery does not supply a usable primary document, the
resolver selects the unique `EX-101.INS` file, or a single remaining HTML/XML
candidate. It never guesses an arbitrary ZIP HTML file; ambiguity is an
accession-level resolution error.

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
- This resolver correction does not change Layer 1 extraction semantics or its
  parser version. It only permits a Filing Discovery-declared entry point that
  was already present in the validated immutable package; rejected runs have
  no published snapshot to overwrite. Package hash, accession identity, and
  `primary_document` remain the provenance for the selected entry point.

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
