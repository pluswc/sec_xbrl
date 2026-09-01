# Consumer Exploration Contract

## Purpose

This contract defines how a consumer discovers a useful same-company analysis
group from Layer 1/2 data.  It is deliberately independent of Excel, an HTTP
API, a database engine, or a metric registry.  A consumer can be a library
function, a query, an Excel builder, a dashboard, or a research workflow.

The contract prevents two opposite mistakes:

- treating every mechanically derived candidate as analysis-ready; and
- hiding company-specific dimensional or custom disclosures because they are
  not in a predefined Concept list.

## Exploration order

Build a group in this order.  Each step retains its evidence; a failed or
missing step narrows the group but does not invent a relationship.

```text
Financial-statement anchor
  -> Presentation / Definition relationship evidence
  -> exact Axis / Member tree
  -> related disclosure/detail Facts
```

1. **Anchor (재무제표 기준 항목):** identify a reported statement Concept,
   role and filing context, such as revenue, operating income or cash flow.
2. **Relationship evidence (표시·정의 관계):** traverse the retained PRE and
   DEF network, including `targetRole`, from that anchor.  PRE explains how a
   filer presents an item; DEF explains dimensional/domain structure.  Neither
   is an arithmetic assertion by itself.
3. **Axis/Member tree (차원·멤버 구조):** collect Facts whose complete
   dimension signature matches the discovered Axis/Member path.  Preserve the
   full signature, not only a displayed Member label.  Parent/child display
   structure must come from retained DEF/PRE evidence or separately labelled
   arithmetic evidence; it must never be inferred solely from row order.
4. **Related detail (연관 주석·세부 공시):** attach the roles, Concepts and
   Facts reached through the same evidence path.  A detail Fact not connected
   by evidence may be shown as an unlinked discovery, never as a child of the
   anchor.

## Minimum group record

An implementation may store these across tables, but a returned group must be
able to expose the following fields.

| Area | Required fields / evidence |
| --- | --- |
| Group identity | `company/cik`, `as_of_date`, selected view, anchor identifier, source filing/role, group rule version |
| Anchor Fact | Concept QName and label, canonical Concept ID when available, Context period, Unit semantics, reported value, raw Fact and filing IDs |
| Relationship path | network type (`PRE`/`DEF`), role URI, arc/evidence IDs, order/preferred-label when present, `targetRole` transition, parent/child raw IDs |
| Dimension path | complete Axis/Member/typed-member/default-member signature, raw and canonical IDs, labels, hierarchy evidence and display depth |
| Detail Fact | Concept/label, Context/period class, Unit, value, dimensions, raw Fact/filing IDs, relation to anchor/path |
| Derived candidate | candidate ID, `reported_or_derived`, source/selection status, formula, derivation rule version, input analytical/raw Fact and filing IDs, actual boundaries |
| Review signals | `CUSTOM_CONCEPT`, `DIMENSIONED`, `PURE_UNIT`, `SHARES_UNIT`, `PRIMARY_STATEMENT_PRE_ABSENT`, `RECAST_SENSITIVE`, mapping/recast status and any exclusion/unavailable reason |

All identifiers and evidence are retained for audit.  A user-facing display may
hide technical identifiers by default, but must preserve a route to inspect
them.

## Selection responsibilities

`MECHANICAL_CANDIDATE_REVIEW_REQUIRED` means only that the period arithmetic
and input scope passed the mechanical contract.  It does **not** mean the value
is additive, comparable across periods, suitable for a particular metric, or
part of the primary financial statements.

The consumer declares its selection rule.  Examples include:

- an earnings view may require a statement-anchor PRE path and a USD amount;
- a product/region view may permit `CUSTOM_CONCEPT` and `DIMENSIONED` but show
  `RECAST_SENSITIVE` prominently;
- a metric may reject `PURE_UNIT`, `SHARES_UNIT`, a denominator-bearing Unit,
  or an unresolved mapping/recast status.

The selection rule is consumer policy.  It does not change Raw Facts or alter
the mechanical candidate.  When no candidate satisfies a rule, return an
explicit unavailable result or an empty group; do not fill from a different
Axis/Member, basis, period class, or earlier filing.

## Excel boundary

Excel consumes this group contract.  It may format chapters, hierarchy,
reported/derived status and review signals, but it must not calculate a Q4
residual itself.  It displays only a Layer 2 reported value or Layer 2-derived
candidate, together with the supplied status and lineage where requested.
