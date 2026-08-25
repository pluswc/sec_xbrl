# NVIDIA FY2026 geography — recast provenance golden case

This is a validation case for the generic Layer 2 recast-observation adapter,
not a ticker-specific rule.  No NVIDIA label, CIK, accession, or number is
embedded in the production selection logic.

## Filed evidence found

NVIDIA's FY2026 Q3 Form 10-Q, filed 2025-11-19, accession
`0001045810-25-000230`, primary document `nvda-20251026.htm`, contains the
geographic-revenue note.  The note says that geographic revenue is now based
on the customer's headquarters; it says the previous presentation used billing
location and that prior-period information was recast.  The same table has the
United States `us-gaap:Revenues` Fact `f-935`, context `c-163`, for the quarter
ended 2025-10-26: `$39,177m`.  Its nine-month United States Fact is `f-937`,
context `c-165`: `$97,759m`.

These facts and the narrative/table locator are sufficient to create a review
evidence record for the **changed geographic basis** in that filing.  The
record must still bind each selected raw Fact individually; it is not a
company-wide switch.

The later FY2027 Q1 Form 10-Q, filed 2026-05-20, accession
`0001045810-26-000052`, primary document `nvda-20260426.htm`, contains the
United States `us-gaap:Revenues` Fact `f-734`, context `c-202`, for the
quarter ended 2025-04-27: `$25,685m`.  It is a later filed comparative under
the new geography presentation, but this filing alone does not supply a
stand-alone sentence explicitly re-identifying that number as a recast.

## Current evidence gap and safe result

The currently cached filings prove the Q3 narrative/table methodology change
and the cited Q1/Q3 reported comparative Facts.  They do **not yet provide a
reviewed raw-Fact-to-raw-Fact evidence record for every FY2026 quarter,
including the asserted Q2 `$32,897m` and Q4 `$51,858m` figures.  Q2 may be
derived only after compatible recast QTD/YTD components and a derivation rule
are bound; Q4 has the same requirement.  Neither is manufactured from an
older billing-location series.

Accordingly, this golden case requires the following status until the evidence
records are ingested:

- `AS_FILED`: preserve the original FY2026 observations, including Q1 `$20,739m`
  and Q2 `$23,470m`, with their original filing provenance.
- `LATEST_RECAST`: return only evidence-bound new-basis periods; emit `N/A`
  for a period whose compatible new-basis raw or derived observation is absent.
- Never combine original Q1/Q2 with new-basis Q3/Q4 to make an annual total.

The source files above are SEC filing inputs and are intentionally not checked
into this repository.  A future ingestion run should persist their immutable
Layer 1 Fact IDs and create `recast_evidence` rows using the adapter contract
in [layer2-longitudinal.md](layer2-longitudinal.md#recast-observation-materialization).
