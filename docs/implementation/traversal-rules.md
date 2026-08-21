# Traversal Rules Contract

## TR-001 — Anchor root
Begin semantic exploration from concepts shown in the major financial statements.

## TR-002 — Direct dimensional facts first
For an Anchor Concept, first find reported facts of the same raw concept with dimensions. These are the strongest decomposition evidence.

## TR-003 — DEF direction
Traverse only allowed dimensional relationships in semantic direction:
- primary item -> hypercube via `all` / relevant dimensional arcs
- hypercube -> dimension
- dimension -> domain
- domain/member -> member
- preserve `dimension-default`
- preserve semantics of `notAll`

No fixed depth limit. Continue to leaves while respecting cycle control and targetRole.

## TR-004 — targetRole
If a relationship specifies `targetRole`, continue the relevant network in that target role. This transition is explicit XBRL semantics, not a heuristic.

## TR-005 — CAL decomposition
Use CAL only parent -> child when interpreting composition. Do not climb from Revenue to Gross Profit/Operating Income merely because Revenue participates in those calculations.

## TR-006 — PRE usage
PRE is primarily used to:
- identify statement/disclosure placement
- obtain display hierarchy/order
- validate context
It is not a free sibling-expansion mechanism.

## TR-007 — Role separation
Never merge role networks into one undifferentiated graph.

## TR-008 — Role expansion candidates
A new role can be explored when:
1. the same Anchor Concept appears in the role;
2. a CAL/DEF-derived concept appears in the role;
3. `targetRole` explicitly points to it;
4. Disclosure Safety Net independently marks it critical.

Label similarity alone is not sufficient.

## TR-009 — Structural vs used member
Record taxonomy members even when structural, but composition analysis defaults to members actually used by facts.

## TR-010 — Termination
A branch ends when there is no new:
- dimensional fact
- allowed DEF edge
- CAL child
- targetRole transition
- approved role expansion

## TR-011 — Cycle control
Visited key must include enough network identity to prevent role/arc ambiguity, e.g.:
`(filing_id, role_uri, arcrole, from_id, to_id)`.

## TR-012 — Evidence
Every discovered analytical relation records an evidence type:
- `DIRECT_DIMENSION`
- `DEFINITION_MEMBER`
- `CALCULATION_CHILD`
- `ROLE_EXPANSION`
- `STRUCTURAL_ONLY`
- `SAFETY_NET_DISCLOSURE`

## Critical Disclosure Safety Net
P0 default candidates:
- Revenue / Revenue Recognition / Disaggregation
- Segment / Geography / Product-Service
- Customer Concentration
- Debt / Borrowing / Credit Facility / Maturity / Covenant
- Commitments / Contingencies / Litigation / Guarantees
- Going Concern / Liquidity uncertainty
- Business Combination / Acquisition / Divestiture / Discontinued Operations
- Goodwill / Intangibles / Impairment
- Subsequent Events
- Income Taxes / Uncertain Tax Positions / Valuation Allowance
- VIE / Consolidation / Off-balance-sheet structures

P1 candidates include leases, fair value, derivatives/hedging, stock compensation, restructuring, related parties, supplier finance, inventory/write-down, receivables/credit losses, pension, significant policies/estimates and capital returns.
