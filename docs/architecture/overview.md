# Architecture Overview

## 1. Objective
The system is not merely a SEC XBRL parser. It must reconstruct how a reported number is composed and then make that structure usable across time and across companies.

Primary analytical questions include:
- What is the total value?
- Which product/service/segment/geography/customer members compose it?
- Which role/disclosure provided that breakdown?
- Is the concept/member standard US-GAAP or company custom?
- How has that structure changed over time?
- How can economically similar structures be compared across peers without destroying original meaning?

## 2. Filing strategy
- **10-K** establishes the annual baseline: full statements, richer notes, annual taxonomy structure.
- **10-Q** updates the current state: latest performance, balance-sheet changes, interim disclosures and structural changes.
- **Amendments** are additional filings, not replacements in Raw.

## 3. Two-track discovery
### Track A — Anchor Driven
4 major statements -> Anchor Concept -> direct dimensional facts -> DEF/CAL -> related disclosure roles.

### Track B — Disclosure Safety Net
All role metadata -> critical disclosure classification -> selected disclosure/table/detail/text facts -> dimensions/relationships.

The two tracks are merged only at the analytical identity/provenance level; role relationship networks remain distinct.

## 4. Separation of responsibilities
- Existing accession collector: **which filings exist?**
- Filing package resolver: **which SEC files belong to the accession?**
- Arelle extraction: **what facts, taxonomy objects and relationships exist?**
- Layer 1 store: **preserve as-filed truth.**
- Layer 2: **same-company temporal identity.**
- Layer 3: **cross-company analytical semantics.**
- Analytical views: **series, composition, peer comparison.**

## 5. Key design principle
Never solve comparability by discarding company-specific information. Preserve raw identity first; add canonical mappings later.
