# AMD · MSFT · META P2 — company dossier review summary

This compact review summary was produced from the six P1-validated, locally
cached as-filed packages on 2026-08-24. Raw packages and generated detailed
dossiers remain ignored. Amounts retain the inline XBRL scale shown below.
`FY`, `QTD_3M`, and `YTD_9M` are different context classes and are not mixed.

## AMD

The annual baseline reports FY 2025 revenue of **34,639 × 10^6 USD**; the
current update reports Q1 2026 revenue of **10,253 × 10^6 USD**. The current
quarter directly reports Data Center revenue of **5,775 × 10^6 USD**,
Client-and-Gaming revenue of **3,605 × 10^6 USD**, and Embedded revenue of
**873 × 10^6 USD**. These are disclosed dimensions, not a reconstructed
product taxonomy. AMD's FY context is 2024-12-29 to 2025-12-27 (363 days),
which is intentionally accepted as FY rather than treated as a calendar year.

- Revenue evidence: 10-K `0000002488-26-000018`, `amd-20251227.htm`,
  inline `f-46`, QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`,
  context 2024-12-29 to 2025-12-27, USD, no dimensions.
- Current revenue evidence: 10-Q `0000002488-26-000076`, `amd-20260328.htm`,
  inline `f-30`, same QName, context 2025-12-28 to 2026-03-28, USD, no dimensions.
- Current Data Center evidence: same 10-Q/document, inline `f-303`, same
  QName, `us-gaap:StatementBusinessSegmentsAxis=amd:DataCenterMember`.
- Current Client-and-Gaming evidence: same 10-Q/document, inline `f-309`, same
  QName, `us-gaap:StatementBusinessSegmentsAxis=amd:ClientAndGamingMember`.
- Current Embedded evidence: same 10-Q/document, inline `f-311`, same QName,
  `us-gaap:StatementBusinessSegmentsAxis=amd:EmbeddedMember`.

## MSFT

The annual baseline reports FY 2025 revenue of **281,724 × 10^6 USD**. The
current update separately reports Q1 2026 **82,886 × 10^6 USD** and YTD nine
months **241,832 × 10^6 USD**; these are intentionally displayed separately.
The Q1 filing reports Intelligent Cloud segment revenue of **34,681 × 10^6
USD** and Microsoft Cloud of **54.5 × 10^9 USD**. Neither measure is labelled
as standalone cloud-services revenue; they must not be used as an equivalent
peer metric.

- Revenue evidence: 10-K `0000950170-25-100235`, `msft-20250630.htm`, inline
  `F_0c259ef1-1d82-480d-8e89-0403e88f0374`, QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`,
  context 2024-07-01 to 2025-06-30, USD, no dimensions.
- Current revenue evidence: 10-Q `0001193125-26-191507`, `msft-20260331.htm`,
  inline `F_5639c226-b557-472b-8f65-cbd0bc2a0b17`, same QName, context 2026-01-01 to 2026-03-31, USD, no dimensions.
- Intelligent Cloud evidence: same 10-Q/document, inline `F_755435a7-623b-4efd-9ad6-f39fdadd2f44`, same QName,
  `us-gaap:StatementBusinessSegmentsAxis=msft:IntelligentCloudMember`.
- YTD revenue evidence: same 10-Q/document, inline
  `F_1a06114e-994b-4615-b743-81434518666e`, same QName, context 2025-07-01 to
  2026-03-31, USD, no dimensions.
- Microsoft Cloud evidence: same 10-Q/document, inline
  `F_e4f6be26-5dad-4a34-b7e4-f898db96f955`, same QName,
  `msft:ProductsOrServicesSecondaryCategorizationAxis=msft:MicrosoftCloudMember`.

## META

The annual baseline reports FY 2025 revenue of **200,966 × 10^6 USD**; the
current update reports Q1 2026 revenue of **56,311 × 10^6 USD**. The Q1
filing directly reports Family of Apps revenue of **55,909 × 10^6 USD**,
Reality Labs revenue of **402 × 10^6 USD**, and advertising revenue within
Family of Apps of **55,024 × 10^6 USD**. These are as-filed segment/product
dimensions, with no assumption that they are comparable to AMD or MSFT scopes.

- Revenue evidence: 10-K `0001628280-26-003942`, `meta-20251231.htm`, inline
  `f-1292`, QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`,
  context 2025-01-01 to 2025-12-31, USD, no dimensions.
- Current revenue evidence: 10-Q `0001628280-26-028526`, `meta-20260331.htm`,
  inline `f-659`, same QName, context 2026-01-01 to 2026-03-31, USD, no dimensions.
- Family of Apps evidence: same 10-Q/document, inline `f-643`, same QName,
  `us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember`.
- Reality Labs evidence: same 10-Q/document, inline `f-651`, same QName,
  `us-gaap:StatementBusinessSegmentsAxis=meta:RealityLabsMember`.
- Advertising-within-Family-of-Apps evidence: same 10-Q/document, inline
  `f-274`, same QName, `srt:ProductOrServiceAxis=us-gaap:AdvertisingMember`
  and `us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember`.

## Disclosure and QA boundary

For every company, the runner inventories P0/P1 disclosure topics from raw
role/concept/fact evidence. A topic present in the 10-K but not corroborated
in the selected 10-Q is marked `NOT_REPORTED_THIS_QUARTER`; it is never
marked resolved. Statement-role QA preserves the as-filed annual and condensed
quarterly statement roles. No derived Q4, forecast, canonical mapping, or
cross-company accounting-equivalence conclusion is produced.

One implementation limitation is explicit: if Arelle's fact collection omits
an inline fact visible in the selected filing document, the P2 runner uses a
narrow fallback only for the three standard total-revenue QNames. It retains
the exact source document, inline fact ID, context, unit, scale, and dimensions
and does not generalize into HTML scraping or an unproven mapping.

## Evidence inventory from the run

The runner writes one fact-level record per selected result. Each record has
the accession, source document and inline-fact locator, QName, context period,
unit, dimensions, and class. The **current-series raw view** consists of the
following observed (not mapped) classes: AMD QTD_3M; MSFT QTD_3M and YTD_9M;
META QTD_3M. This is a Layer 2-ready view only: it adds no canonical ID and
does not combine any of those classes.

| Company | 10-K statement / relationship evidence | 10-Q statement / relationship evidence |
| --- | --- | --- |
| AMD | 6 statement roles; PRE 3, CAL 0, DEF 97 | 7 statement roles; PRE 0, CAL 0, DEF 49 |
| MSFT | 7 statement roles; PRE 24, CAL 0, DEF 174 | 7 statement roles; PRE 13, CAL 0, DEF 128 |
| META | 7 statement roles; PRE 14, CAL 0, DEF 95 | 7 statement roles; PRE 0, CAL 0, DEF 56 |

These are extracted relationship records, kept by network type and role; zero
does not mean an inferred absence of a calculation in the filing.

### P0/P1 disclosure inventory states

| Company | `REPORTED_UNCHANGED` (raw corroboration in 10-Q) | `NOT_REPORTED_THIS_QUARTER` |
| --- | --- | --- |
| AMD | BUSINESS_COMBINATION, COMMITMENTS_CONTINGENCIES, DEBT_BORROWING, FAIR_VALUE, GOODWILL_INTANGIBLES, RECEIVABLES_CREDIT_LOSSES, REVENUE_RECOGNITION | INCOME_TAXES, INVENTORY, LEASES, STOCK_COMPENSATION |
| MSFT | BUSINESS_COMBINATION, CAPITAL_RETURNS, COMMITMENTS_CONTINGENCIES, DEBT_BORROWING, DERIVATIVES_HEDGING, FAIR_VALUE, GOODWILL_INTANGIBLES, LEASES, RECEIVABLES_CREDIT_LOSSES, REVENUE_RECOGNITION, SEGMENT_GEOGRAPHY_PRODUCT | ACCOUNTING_POLICY_ESTIMATES, INCOME_TAXES, RELATED_PARTIES, VIE_CONSOLIDATION |
| META | ACCOUNTING_POLICY_ESTIMATES, BUSINESS_COMBINATION, COMMITMENTS_CONTINGENCIES, FAIR_VALUE, GOODWILL_INTANGIBLES, INCOME_TAXES, LEASES, SEGMENT_GEOGRAPHY_PRODUCT, VIE_CONSOLIDATION | CAPITAL_RETURNS, DEBT_BORROWING, RECEIVABLES_CREDIT_LOSSES |

The topics come from the P0/P1 controlled vocabulary. A state reflects only
corroborated role/concept/fact evidence in this paired-file scope; it does not
say that a topic is economically immaterial or resolved.
