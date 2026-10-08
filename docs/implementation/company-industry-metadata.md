# Company and SEC SIC Metadata Publication Contract

## 1. Scope and status

This milestone publishes company identity, identifier, and SEC SIC metadata from
already-cached SEC submissions root snapshots.  It is an approved implementation
slice on the `codex/company-industry-metadata` branch.  Implementation, independent
verification, local acceptance, and merge remain separate delivery states under
`delivery-workflow.md`.

The slice does not discover or download filings, infer accounting equivalence,
score peers, calculate financial or market metrics, or map SIC to GICS/NAICS.  The
existing company submissions collector remains the upstream source.

## 2. Acceptance criteria

The implementation must:

1. build one canonical company row per ten-digit CIK from cached root submissions;
2. preserve source path, SHA-256, source name, source URL when supplied, and an
   explicit timezone-aware `observed_at` for every selected observation;
3. preserve multiple ticker/exchange identifiers without duplicating the issuer;
4. preserve current name, `formerNames`, and supported filing-form inventory;
5. parse SEC SIC as a four-digit code, retain SEC's description, and emit an
   explicit `NOT_CLASSIFIED` row when SIC is absent;
6. resolve multiple root observations only by documented observation-time and
   cutoff rules and reject ambiguous latest observations;
7. atomically publish immutable Parquet datasets plus a versioned manifest and
   defensively validate publications when reading;
8. retain excluded and metadata-unavailable candidates with reason codes when a
   universe filter is evaluated; and
9. support exchange, supported-form, SIC, and explicit-CIK universe filters plus
   coarse same-SIC peer-candidate lookup.

Unit tests cover duplicate share classes, absent and malformed SIC, competing
snapshots, cutoff semantics, immutable reuse/collision, filtering, and source
trace.  Tests use synthetic cached inputs and require no network.

## 3. Input boundary and provenance

`SnapshotInput` identifies a cached JSON file with:

- `path`;
- timezone-aware `observed_at` (the time the bytes were observed, not a filing
  or historical effective date);
- a controlled source name, defaulting to `sec_submissions`; and
- optional source URL.

For convenience, `build_company_metadata(paths, observed_at=...)` applies one
observation time to all paths.  Supplying bare paths without that time fails.
The builder performs no HTTP requests.

A company submissions root object is recognized by root identity fields such as
`name`, `tickers`, `exchanges`, `sic`, `sicDescription`, or `formerNames`.
Historical submissions fragments may contribute no company metadata and are not
silently merged into the root observation.  A payload CIK must agree with an
explicit ten-digit CIK parent directory when one is present.

An optional `CandidateInventoryInput` accepts a caller-cached public SEC
ticker/exchange inventory with its own observation time and provenance.  It may
broaden the candidate set, but an issuer without a selected submissions root is
published as `CANDIDATE_ONLY` and `NOT_CLASSIFIED`.  This prevents a pilot's SIC
coverage from being represented as full classification coverage.

An optional caller-cached SIC reference maps exact four-digit SIC codes to public
titles.  Its title supplements the SEC root description; it does not replace or
rewrite the observed description.

## 4. Observation selection and temporal meaning

For each CIK, the builder selects the root observation with the greatest
`observed_at` at or before the optional cutoff.  Multiple identical byte hashes
at that instant are duplicate references to one observation.  Multiple distinct
hashes at the selected instant are ambiguous and fail closed.  Earlier and later
root snapshots are never field-by-field merged.

The publication describes metadata as observed by the collector.  SEC root SIC
and names are current observations and are not claimed to have been known or
effective at a historical analytical `as_of` date.  `cutoff` limits which
observation may be selected; it does not create historical industry truth.

## 5. Logical datasets

### `companies.parquet`

One row per issuer, keyed by `company_id = "sec-cik:" + cik`:

| Field | Meaning |
| --- | --- |
| `company_id`, `cik` | stable publication ID and ten-digit SEC CIK |
| `name` | observed current SEC name, nullable for inventory-only candidates |
| `former_names_json` | canonical JSON preserving SEC `formerNames` entries |
| `supported_forms` | sorted forms from the supported 10-K/10-Q family present in the root inventory |
| `metadata_status` | `ROOT_OBSERVED` or `CANDIDATE_ONLY` |
| `observed_at`, `source`, `source_url` | observation provenance |
| `source_path`, `source_sha256` | cached input locator and byte hash |

### `company_identifiers.parquet`

One row for the CIK and one row per distinct ticker/exchange pair.  Tickers are
normalized to uppercase for identifier matching while the raw observed ticker is
also retained.  Duplicate ticker/exchange pairs within one input are rejected;
the same root and explicit inventory identity is coalesced with root provenance.
The same ticker/exchange pair cannot identify two CIKs in one publication.
Multiple tickers or share classes for one CIK are preserved.  A missing exchange
is retained as unavailable metadata rather than causing the issuer to disappear.

### `industry_classifications.parquet`

One SEC SIC row per issuer:

| Field | Meaning |
| --- | --- |
| `classification_system` | `SEC_SIC` |
| `sic_code` | exact four-digit code, nullable only when unclassified |
| `classification_status` | `CLASSIFIED` or `NOT_CLASSIFIED` |
| `sec_description` | observed `sicDescription`, nullable |
| `reference_title` | optional caller-cached SIC reference title |
| source fields | copied from the selected company observation |

Missing SIC remains unclassified.  Ticker, labels, names, and filing facts are
never used to guess a code.  SIC supplies coarse peer candidates only; it is not
accounting equivalence or investment comparability.

## 6. Publication and reader contract

`publish_company_metadata(build, destination)` writes the three datasets and
`company_metadata_manifest.json` through a staging directory, then atomically
renames it.  The manifest records schema version, publication ID, build cutoff,
creation time, row counts, file sizes and SHA-256 hashes, selected input
provenance, candidate/reference inputs, and the temporal limitation above.

An existing destination is reusable only when a defensive reader validates it
and its publication ID equals the requested build.  Any collision fails.  The
reader rejects missing, extra, symlinked, hash-mismatched, or schema-mismatched
files before exposing rows.

## 7. Query and universe semantics

`UniverseFilter` may carry exchanges, supported forms, SIC codes, and explicit
CIKs.  Filters are conjunctive.  `CompanyMetadataReader.list_companies()` returns
all publication candidates with `eligible` and stable exclusion reason codes,
rather than dropping unknown metadata.  Explicit CIKs absent from the
publication produce `METADATA_UNAVAILABLE` candidates.  Short filing histories
remain candidates; this slice has no history-length exclusion.

`peer_candidates(cik)` returns other classified issuers with the exact observed
SEC SIC code and includes the coarse-comparison limitation in each result.  An
unclassified or unknown target yields no asserted peers.

## 8. Public Python and CLI surface

```python
build = build_company_metadata(
    [SnapshotInput(path, observed_at, source="sec_submissions")],
    cutoff=cutoff,
)
published = publish_company_metadata(build, destination)
reader = CompanyMetadataReader(published.root)
rows = reader.list_companies(UniverseFilter(exchanges=frozenset({"Nasdaq"})))
peers = reader.peer_candidates("0000320193")
```

The module CLI is available as:

```text
python -m sec_xbrl.company_metadata build ...
python -m sec_xbrl.company_metadata query ...
python -m sec_xbrl.company_metadata peer-candidates ...
```

## 9. Unresolved and deferred cases

- SEC root metadata does not provide a governed historical SIC effective-date
  series.  Historical industry classification needs a separate reviewed source
  and contract.
- Exchange spelling is preserved from SEC inputs.  Alias governance is deferred.
- Delisted/private issuers absent from a supplied complete candidate inventory
  cannot be inferred.
- GICS/NAICS mappings, proprietary classifications, peer scoring, market data,
  and financial screens are outside this milestone.
