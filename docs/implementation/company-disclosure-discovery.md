# Company Disclosure Discovery Contract

## Purpose / 목적

This contract describes the first user-facing discovery boundary above an
immutable Layer 1 filing snapshot.  It answers a question such as:

> “For AAPL's income statement, which reported items exist, which detailed
> disclosures are actually connected to those items, and which Axis/Member
> values were used?”

이는 XBRL 전문 용어를 모르는 분석 사용자에게는 다음과 같이 보인다.

```text
손익계산서 (Income statement)
 └─ 매출 (Revenue)
    ├─ 공시 본문에서의 위치와 기간별 관측값
    ├─ 실제로 보고된 구분값: 지역/제품/사업부 등 (Axis / Member)
    ├─ 관련 주석 표: XBRL Concept 연결 근거가 있을 때만
    └─ 구조상 존재하지만 실제 숫자가 없는 Member
```

It is **not** a canonical Metric mapping and does not assert that all items
with a similar label have the same accounting meaning.

## Terms / 용어

| Term | Korean | Meaning in this interface |
| --- | --- | --- |
| Fact | 공시 수치 | One reported value with a period, unit and optional dimensions. |
| Concept | 항목 정의 | The XBRL identity of a Fact, e.g. Revenue. |
| Axis | 구분 기준 | The basis for a breakdown, e.g. geography or product. |
| Member | 구분값 | A value under an Axis, e.g. Americas or iPhone. |
| Role | 공시 표/주석의 위치 | A separate XBRL network representing a statement or note table. |
| PRE | 표시 구조 | The display parent/child layout of a statement or disclosure. |
| CAL | 합산 구조 | Parent-to-child arithmetic decomposition evidence. |
| DEF | 차원 정의 구조 | Axis/domain/member structure, including structural members. |

## Public Python boundary

```python
from sec_xbrl.discovery import CompanyDisclosureDiscovery

result = CompanyDisclosureDiscovery().discover_snapshot(
    snapshot_dir,
    statement_type="IS",  # IS / BS / CF / EQ
)
```

The lower-level `discover(...)` accepts already loaded Layer 1 rows and is
therefore usable by a future analytical repository, service, or test fixture.
It does not download SEC data, mutate Layer 1, choose a company canonical
mapping, or calculate a derived metric.

## Output contract

| Output | Meaning | Evidence type |
| --- | --- | --- |
| `anchors` | Reported items in the selected primary statement role | statement PRE placement |
| `statement_hierarchy` | Parent/child display rows for rendering a statement tree | `PRESENTATION_HIERARCHY` |
| `direct_dimensions` | Fact instances that actually carry Axis/Member assignments | `DIRECT_DIMENSION` |
| `structural_members` | DEF `domain-member` leaves; status distinguishes used from taxonomy-only | `DEFINITION_MEMBER` / `STRUCTURAL_ONLY` |
| `calculation_decomposition` | Disclosed CAL parent-to-child arcs and weights; not a computed metric | `CALCULATION_CHILD` |
| `concept_role_links` | Why a related disclosure role may be inspected | `ROLE_EXPANSION` |
| `related_roles` | Compact browse list of evidence-backed note roles | `SAME_ANCHOR_CONCEPT` or `TRAVERSED_CAL_OR_DEF_CONCEPT` |
| `period_change_evidence` | Per-Fact period/value observation schema | `REPORTED_PERIOD_OBSERVATION` |

`period_change_evidence` deliberately has `change_status=OBSERVED_ONLY` in a
single-filing discovery.  A change cannot be inferred merely because two
values appear in an interim filing.  Layer 2 performs comparable longitudinal
selection and may later calculate a change only after basis/period validation.

## Expansion rules / 연결 규칙

The interface follows TR-001 through TR-009 and, in particular, TR-008.

1. Start with reported concepts displayed in a qualifying primary statement
   role.  A note table whose title happens to mention “income” is not a primary
   income statement anchor.
2. Inspect direct dimensional Facts first.  A Member is `DIRECTLY_REPORTED`
   only if it is attached to a Fact Context.
3. Traverse DEF only in its permitted dimensional direction and CAL only from
   parent to child.  PRE is display evidence only.  CAL arcs are returned with
   their source relationship ID and weight so a consumer can inspect a
   decomposition without mistaking it for an internally calculated Metric.
4. Expand to a note/disclosure role only where it contains the exact raw
   anchor Concept or a Concept reached by CAL/DEF.  **Labels, keywords, role
   titles, and namespace similarity alone never expand a role.**
5. Where a filing has company-extension namespaces, restrict note expansion to
   filing-scoped role URIs with the same issuer host.  This prevents generic
   taxonomy linkroles loaded by Arelle from becoming apparent company notes.
6. Keep structural Members separate from Members used by reported Facts.

The output always preserves raw Concept IDs, role IDs and source relationship
IDs.  A UI may show labels and indentation, but it must retain the evidence
fields for inspection.

### Readable hierarchy guarantee / 표시 가능한 계층 보장

Layer 1 stores metadata not only for Fact Concepts but also for every Concept
that is an endpoint of a materialized PRE/CAL/DEF relationship.  This is a
bounded endpoint expansion, not wholesale import of the standard taxonomy.
Consequently a returned `statement_hierarchy` row must have both parent and
child QName/label metadata.  A snapshot from an older parser that lacks those
endpoint Concepts is not an acceptable user-rendering input; it must be
re-ingested rather than silently rendered with anonymous IDs.

## AAPL vertical-slice evidence

The non-committed execution report is generated from the current Layer 1
snapshot of AAPL 10-Q accession `0000320193-26-000020` (filed 2026-07-31,
report date 2026-06-27) at:

```text
/tmp/aapl-current-discovery/aapl_is_discovery.json
```

It demonstrates that `RevenueFromContractWithCustomerExcludingAssessedTax`
has direct facts using `StatementBusinessSegmentsAxis` with AAPL geography
members (Americas, Europe, Greater China, Japan and Rest of Asia Pacific), and
that the Revenue disaggregation note is linked by the same raw Concept rather
than a label match.  This is one current filing evidence only; the temporary
three-year corpus attempt identified an older Inline transformation validation
failure (`ix11.11.1.2:invalidTransformation`) in accession
`0000320193-23-000006`.  That failure is retained outside Git as a retryable
Layer 1 parse-state record and no incomplete three-year analytical result is
published.  An independently attempted FY2025--FY2026 two-year window also
remains unpublished: its FY2024 annual baseline `0000320193-24-000123` has
the same validation failure.  The atomic corpus gate is deliberately not
weakened; this vertical slice supplies hierarchy evidence for one current
filing, not a change series.

## Non-goals / 아직 하지 않는 것

- Inferring that every product, geographic or segment table adds to total
  revenue.
- Treating an Axis label as a complete accounting definition.
- Canonicalising AAPL-specific members across filings.
- Extracting non-XBRL HTML-only disclosures.
- Calculating materiality, growth, mix, margin, or user-defined Metrics.

Those are consumers or later layers built on this evidence-first discovery
result.
