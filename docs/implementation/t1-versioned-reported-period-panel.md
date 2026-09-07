# T1 — Versioned Reported-Period Panel

## User effect

The panel makes every directly reported value for one company and fiscal
period available together.  It does not decide which value is the answer.
This lets a later analysis view answer both “what did the original 10-Q say?”
and “what did the amendment subsequently say?” without reopening a filing or
discarding either value.

For example, when a Q1 revenue is reported as 100 in a 10-Q and 120 in a
10-Q/A, `reported_period_observation` has two rows.  An `AS_FILED`, amended,
or comparable analysis view is a later consumer policy over those rows; T1
does not collapse them.

## Published operational Parquet datasets

- `reported_period_observation`: one eligible Layer 1 `REPORTED` Fact,
  period-classified from its Context.  It includes FY/Q, QTD/YTD/FY/instant
  class, value, raw QName, fact/context/unit/full raw dimensions, filing
  accession/form/filed date, amendment marker/original accession reference,
  and snapshot identity.
- `company_concept_map`, `company_axis_map`, `company_member_map`: additive
  company-scoped mappings.  The observation keeps mapping IDs, canonical IDs
  when available, and `mapping_review_required`; mappings never replace raw
  identity.
- `period_observation_exclusion`, only when a raw Fact cannot safely form an
  eligible observation.  It preserves the explicit exclusion instead of
  silently losing the Fact from the accounting.

There is no `analytical_fact`, recast evidence, AS_OF selection, comparable
selection, or Q4 derivation in this publication.

## Exact retrieval

`VersionedObservationPanelReader.get_period()` requires a
`Layer2PublicationReader`-verified publication plus CIK, fiscal year, fiscal
quarter, and optional period class.  It returns every matching filing version,
sorted by filed date/accession/fact identity.  It deliberately does not choose
an original, amendment, or later comparative value.

## Boundary

This is the Layer2 input to the later company analysis-view model.  A future
analysis line binds common GAAP and company custom rows to these observations;
it owns displayed subtotal, growth, margin, ratio and pivot policies.
