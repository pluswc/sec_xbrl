# CRM accession-scoped fiscal-focus correction

## Status and authority

On 2026-10-22 the user approved one reviewed Layer 2 input correction for CIK
`0001108524`, accession `0001108524-26-000060`. This approval authorizes local source,
focused tests and a fresh CRM runtime proposal. It does not authorize an actual History
build, audit, financial run, ROOT GO, remote push, PR or merge.

## Source contradiction

The immutable cached primary member `crm-20260131.htm` reports
`dei:DocumentFiscalYearFocus=2025` in inline fact `f-36`, context `c-1`, while
`dei:DocumentFiscalPeriodFocus=FY`. Context `c-1` runs from 2025-02-01 through
2026-01-31. The package manifest SHA-256 is
`097fdd83464cd8deff6491dd11da23bfc38ab6fce031e3a9ed931cb5106e0cbc`; it pins
the XBRL ZIP SHA-256
`ac8c422770e833578a05fc4ce7312ebb5b388aa8442890ef5103bb9c77df6a47`.
Layer 1 preserves the original lexical `2025` and remains immutable.

The same [SEC filing narrative](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm)
defines fiscal 2026 as the fiscal year ending 2026-01-31. The
[official Salesforce FY2026 release](https://investor.salesforce.com/news/news-details/2026/Salesforce-Delivers-Record-Fourth-Quarter-Fiscal-2026-Results/default.aspx)
also identifies the full fiscal year as ending 2026-01-31. The approved effective
Layer 2 fiscal year is therefore `2026` for this accession.

## Governed correction record

The runtime input is a versioned JSON document with a `corrections` array. The sole
approved entry binds all of these values:

- correction ID, CIK and accession;
- primary document, report date, original fiscal-year focus and fiscal-period focus;
- inline fact ID and context ID, plus the context start and end dates;
- package-manifest and XBRL-ZIP SHA-256 values;
- effective fiscal-year focus `2026`;
- reviewed SEC-filing and issuer-release evidence URLs and the approval date.

The loader accepts only a regular file with an exact supported schema. It rejects
missing fields, wrong types, duplicate correction identities, unsupported effective
values, or any mismatch between the correction entry and the immutable Layer 1 filing.
The CLI binds the correction file by path and SHA-256. A configured correction that is
not consumed exactly once also fails closed.

## Layer boundary and provenance

The correction is applied after the verified Layer 1 snapshot is loaded and before
period observation. It returns an analytical copy of the filing metadata with effective
`document_fiscal_year_focus=2026`. It must retain the reported lexical `2025`, correction
ID, reviewed evidence, source hashes and original inline identifiers as provenance on
the affected Layer 2 observation. Raw filing and fact records are never rewritten.

Filings without a correction artifact, and all nonmatching accessions in a configured
artifact, retain the existing behavior byte-for-byte. No ticker exception, report-date
year inference or generic calendar inference is permitted. Period class, actual Context
boundaries, Q4 compatibility, lineage, quality gates and five-year inventory policy stay
unchanged.

## Acceptance boundary

Focused tests must prove:

- the exact approved entry produces effective fiscal year 2026 while retaining reported
  2025 and complete correction provenance;
- wrong CIK/accession, inline fact/context IDs, source hashes, report date, fiscal period
  or context boundaries fail closed;
- duplicate, missing, malformed and unconsumed configured entries fail closed;
- an unrelated filing and the no-artifact default remain unchanged;
- current and comparative fiscal coordinates remain distinct and use their actual Context
  boundaries under the existing period rules.

After source freeze and independent verification, ROOT must separately accept new engine
and runtime bindings. Only then may ROOT author a fresh CRM config and GO. The accepted
CRM History proof and failed inventory evidence remain immutable and are superseded only
by a separately accepted fresh CRM chain.
