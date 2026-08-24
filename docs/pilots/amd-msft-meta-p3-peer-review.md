# AMD · MSFT · META P3 — peer comparison and backlog

This P3 review consumes only P2 evidence from the six validated P1 cached filings. It preserves reported values and makes missing Layer 2 mappings visible; it does not rank companies or infer cloud revenue.

## What can be inspected together

Company-wide reported revenue uses the same as-filed standard QName and USD unit, but the current P2 boundary has no materialized company canonical IDs. These rows are visible candidates, not an `EQUIVALENT` peer series. FY, QTD_3M, and YTD_9M remain separate.

## Comparison rows

### AMD — `REPORTED_TOTAL_REVENUE`

- Reported value: `34639 × 10^6` (`FY`; 2024-12-29 to 2025-12-27; dimensions: none).
- Raw ID: `as-filed-inline-fact:0000002488-26-000018:amd-20251227.htm:inline-id:f-585`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0000002488-26-000018`; document `amd-20251227.htm`; locator `inline-id:f-585`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### AMD — `REPORTED_TOTAL_REVENUE`

- Reported value: `10253 × 10^6` (`QTD_3M`; 2025-12-28 to 2026-03-28; dimensions: none).
- Raw ID: `as-filed-inline-fact:0000002488-26-000076:amd-20260328.htm:inline-id:f-313`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0000002488-26-000076`; document `amd-20260328.htm`; locator `inline-id:f-313`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### AMD — `AMD_CLIENT_AND_GAMING_REVENUE`

- Reported value: `3605 × 10^6` (`QTD_3M`; 2025-12-28 to 2026-03-28; dimensions: srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember; us-gaap:StatementBusinessSegmentsAxis=amd:ClientAndGamingMember).
- Raw ID: `as-filed-inline-fact:0000002488-26-000076:amd-20260328.htm:inline-id:f-309`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0000002488-26-000076`; document `amd-20260328.htm`; locator `inline-id:f-309`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: AMD's combined Client-and-Gaming dimension has no evidenced common peer scope here.

### AMD — `AMD_DATA_CENTER_REVENUE`

- Reported value: `5775 × 10^6` (`QTD_3M`; 2025-12-28 to 2026-03-28; dimensions: srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember; us-gaap:StatementBusinessSegmentsAxis=amd:DataCenterMember).
- Raw ID: `as-filed-inline-fact:0000002488-26-000076:amd-20260328.htm:inline-id:f-303`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0000002488-26-000076`; document `amd-20260328.htm`; locator `inline-id:f-303`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: AMD's disclosed Data Center dimension is not automatically a cloud-services metric.

### AMD — `AMD_EMBEDDED_REVENUE`

- Reported value: `873 × 10^6` (`QTD_3M`; 2025-12-28 to 2026-03-28; dimensions: srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember; us-gaap:StatementBusinessSegmentsAxis=amd:EmbeddedMember).
- Raw ID: `as-filed-inline-fact:0000002488-26-000076:amd-20260328.htm:inline-id:f-311`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0000002488-26-000076`; document `amd-20260328.htm`; locator `inline-id:f-311`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: AMD's Embedded dimension has no evidenced common peer scope here.

### META — `REPORTED_TOTAL_REVENUE`

- Reported value: `200966 × 10^6` (`FY`; 2025-01-01 to 2025-12-31; dimensions: none).
- Raw ID: `as-filed-inline-fact:0001628280-26-003942:meta-20251231.htm:inline-id:f-1292`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0001628280-26-003942`; document `meta-20251231.htm`; locator `inline-id:f-1292`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### META — `REPORTED_TOTAL_REVENUE`

- Reported value: `56311 × 10^6` (`QTD_3M`; 2026-01-01 to 2026-03-31; dimensions: none).
- Raw ID: `as-filed-inline-fact:0001628280-26-028526:meta-20260331.htm:inline-id:f-659`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0001628280-26-028526`; document `meta-20260331.htm`; locator `inline-id:f-659`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### META — `META_FAMILY_OF_APPS_ADVERTISING_REVENUE`

- Reported value: `55024 × 10^6` (`QTD_3M`; 2026-01-01 to 2026-03-31; dimensions: srt:ProductOrServiceAxis=us-gaap:AdvertisingMember; us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember).
- Raw ID: `as-filed-inline-fact:0001628280-26-028526:meta-20260331.htm:inline-id:f-274`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0001628280-26-028526`; document `meta-20260331.htm`; locator `inline-id:f-274`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Advertising within Family of Apps is both product and segment scoped; it is not comparable to the other issuer breakdowns.

### META — `META_FAMILY_OF_APPS_REVENUE`

- Reported value: `55909 × 10^6` (`QTD_3M`; 2026-01-01 to 2026-03-31; dimensions: us-gaap:StatementBusinessSegmentsAxis=meta:FamilyOfAppsMember).
- Raw ID: `as-filed-inline-fact:0001628280-26-028526:meta-20260331.htm:inline-id:f-643`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0001628280-26-028526`; document `meta-20260331.htm`; locator `inline-id:f-643`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Family of Apps is a Meta reportable segment, not an automatically comparable platform or cloud category.

### META — `META_REALITY_LABS_REVENUE`

- Reported value: `402 × 10^6` (`QTD_3M`; 2026-01-01 to 2026-03-31; dimensions: us-gaap:StatementBusinessSegmentsAxis=meta:RealityLabsMember).
- Raw ID: `as-filed-inline-fact:0001628280-26-028526:meta-20260331.htm:inline-id:f-651`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0001628280-26-028526`; document `meta-20260331.htm`; locator `inline-id:f-651`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Reality Labs is a Meta reportable segment, not an automatically comparable hardware or technology category.

### MSFT — `REPORTED_TOTAL_REVENUE`

- Reported value: `281724 × 10^6` (`FY`; 2024-07-01 to 2025-06-30; dimensions: none).
- Raw ID: `as-filed-inline-fact:0000950170-25-100235:msft-20250630.htm:inline-id:F_0c259ef1-1d82-480d-8e89-0403e88f0374`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0000950170-25-100235`; document `msft-20250630.htm`; locator `inline-id:F_0c259ef1-1d82-480d-8e89-0403e88f0374`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### MSFT — `REPORTED_TOTAL_REVENUE`

- Reported value: `82886 × 10^6` (`QTD_3M`; 2026-01-01 to 2026-03-31; dimensions: none).
- Raw ID: `as-filed-inline-fact:0001193125-26-191507:msft-20260331.htm:inline-id:F_5639c226-b557-472b-8f65-cbd0bc2a0b17`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0001193125-26-191507`; document `msft-20260331.htm`; locator `inline-id:F_5639c226-b557-472b-8f65-cbd0bc2a0b17`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### MSFT — `REPORTED_TOTAL_REVENUE`

- Reported value: `241832 × 10^6` (`YTD_9M`; 2025-07-01 to 2026-03-31; dimensions: none).
- Raw ID: `as-filed-inline-fact:0001193125-26-191507:msft-20260331.htm:inline-id:F_1a06114e-994b-4615-b743-81434518666e`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `UNRESOLVED`; confidence: `0.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: All selected facts use the same standard total-revenue QName and USD unit, but P2 did not materialize the required Layer 2 company canonical IDs.
- Source: accession `0001193125-26-191507`; document `msft-20260331.htm`; locator `inline-id:F_1a06114e-994b-4615-b743-81434518666e`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Company-wide reported revenue can be inspected side by side, but this is not yet a materialized EQUIVALENT cross-company mapping. Do not mix period classes.

### MSFT — `MSFT_INTELLIGENT_CLOUD_REVENUE`

- Reported value: `98485 × 10^6` (`YTD_9M`; 2025-07-01 to 2026-03-31; dimensions: us-gaap:StatementBusinessSegmentsAxis=msft:IntelligentCloudMember).
- Raw ID: `as-filed-inline-fact:0001193125-26-191507:msft-20260331.htm:inline-id:F_75165ce2-2594-4fa6-ba40-886e2ff58515`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0001193125-26-191507`; document `msft-20260331.htm`; locator `inline-id:F_75165ce2-2594-4fa6-ba40-886e2ff58515`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Intelligent Cloud is a reportable segment broader than cloud services; it is not a standalone cloud-revenue metric.

### MSFT — `MSFT_MICROSOFT_CLOUD_REVENUE`

- Reported value: `155.1 × 10^9` (`YTD_9M`; 2025-07-01 to 2026-03-31; dimensions: msft:ProductsOrServicesSecondaryCategorizationAxis=msft:MicrosoftCloudMember).
- Raw ID: `as-filed-inline-fact:0001193125-26-191507:msft-20260331.htm:inline-id:F_f252ca92-af18-4503-b56a-beb65daa9ada`.
- Company canonical ID: `UNMAPPED: Layer 2 company canonicalization not materialized`.
- Analytical ID: `none`; relation: `NOT_COMPARABLE`; confidence: `1.00`; version: `p3-amd-msft-meta-v1`.
- Mapping evidence: P2 directly reports the dimensional scope below; no common unit-of-account is evidenced across the three issuers.
- Source: accession `0001193125-26-191507`; document `msft-20260331.htm`; locator `inline-id:F_f252ca92-af18-4503-b56a-beb65daa9ada`; QName `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`; unit `iso4217:USD`.
- Scope warning: Microsoft Cloud is an as-filed product/service categorization, not evidenced as equivalent to another issuer's segment or product measure.

## Panel-wide scope warnings

- Rows are reported as-filed facts, not rankings, forecasts, or derived metrics.
- P2 supplied no Layer 2 company canonical maps. UNMAPPED is therefore visible on every row; this P3 review does not bypass that contract.
- FY, QTD_3M, and YTD_9M remain separate. A value may be read beside another row only when its period class and scope are suitable for the user's question.
- AMD Data Center, MSFT Intelligent Cloud/Microsoft Cloud, and Meta Family of Apps/Reality Labs are not automatically peer-equivalent measures.

## Prioritized backlog

### P0 — correctness blocker — `P3-BLK-001`

- Owner lane: Longitudinal mapping review (Layer 2 mapping).
- Evidence gap: P2 has exact standard-QName revenue evidence but no materialized company canonical concept maps.
- Impact: Without canonical IDs, Layer 3 cannot produce a contract-valid EQUIVALENT total-revenue panel.
- Decision needed: Approve evidence-backed SAME mappings for each issuer's paired total-revenue concepts, or retain UNMAPPED.

### P0 — correctness blocker — `P3-BLK-002`

- Owner lane: Layer 1 / parser (Parser provenance).
- Evidence gap: P2 uses a narrow inline fallback when Arelle omits visible total-revenue facts; fallback rows retain locators but not Layer 1 fact IDs.
- Impact: A materialized downstream panel needs a one-to-one raw fact ID bridge without broadening HTML scraping.
- Decision needed: Decide whether to fix the Arelle collection path or add a tested, provenance-preserving Layer 1 inline fact bridge.

### P1 — decision coverage — `P3-COV-001`

- Owner lane: Cross-company mapping review (Scope review).
- Evidence gap: MSFT Intelligent Cloud and Microsoft Cloud have different disclosed scopes; AMD and Meta breakdowns use different segment/product axes.
- Impact: Prevents a misleading cloud, platform, or infrastructure peer chart.
- Decision needed: Approve only relation-specific mappings supported by disclosure scope, otherwise retain NOT_COMPARABLE.

### P1 — decision coverage — `P3-COV-002`

- Owner lane: Filing selection and Layer 2 (History / recasts).
- Evidence gap: One annual/current pair cannot establish mapping stability, renames, recasts, or continuity across reporting changes.
- Impact: Limits conclusions to the selected filings and may conceal later comparability breaks.
- Decision needed: Select additional annual filings and review documented segment recasts before longitudinal trend comparisons.

### P2 — useful coverage — `P3-COV-003`

- Owner lane: Disclosure taxonomy and mapping review (Disclosure coverage).
- Evidence gap: P2 has selected revenue breakdowns but no reviewed common geography, customer-class, or product/service analytical taxonomy.
- Impact: Would broaden the panel only after correctness blockers are resolved.
- Decision needed: Choose a narrowly defined analytical category and its evidence standard, or explicitly leave the metric unavailable.
