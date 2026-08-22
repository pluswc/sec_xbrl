# M1A Package Cache Contract

Input is one `FilingRef`. M1A downloads only the accession XBRL ZIP and SEC
index-headers HTML; SEC filing `index.json` resolution and Arelle are M1C work.

## Layout

```text
data/raw/sec/packages/{cik}/{accession_nodash}/
  {accession}-xbrl.zip
  {accession}-index-headers.html
  manifest.json
```

`manifest.json` records schema version, CIK, accession, form, and for every
artifact its source URL, SHA-256, and byte size.

## Invariants

- Publish via a temporary sibling directory followed by an atomic rename.
- A published manifest must validate every artifact before it is reused.
- A partial directory or hash mismatch is an integrity error, never a cache hit.
- A valid package is immutable and causes no network request on reuse.
- SEC requests use an explicit User-Agent, bounded retry, and rate-limit delay.
