# Layer 1 Schema Contract

Layer 1 is immutable, as-filed, and provenance-first. The exact physical store can begin as Parquet and later be materialized into a database.

## M2 materialization boundary

`sec_xbrl.facts.layer1.Layer1Extractor` is the M2 boundary from an already
loaded Arelle model to six independently materialized Parquet tables:
`filing`, `concept`, `context`, `unit`, `fact`, and `dimension_fact`. It only
emits `REPORTED` facts. `period_class` and `comparative_type` remain null until
M6, so this extraction does not apply filing-level period assumptions. Typed
dimensions are stored in `dimension_fact.typed_member`, never discarded.

## M3 relationship materialization boundary

`sec_xbrl.relationships.layer1.RelationshipExtractor` is the M3 boundary from
the same already-loaded Arelle model to two additional independently
materialized Parquet tables: `role` and `relationship`.  It records PRE, CAL,
and DEF networks separately and preserves relationship attributes, including
`targetRole`.  It does not traverse, merge, or otherwise interpret networks;
M4 owns traversal.  Relationship concept identifiers use the same filing- and
QName-scoped raw identity formula as M2 concepts.

## M4 anchor traversal boundary

`sec_xbrl.traversal.anchor.AnchorTraversal` consumes the immutable M2/M3
records, rather than a live Arelle model.  It materializes `anchor` and
`traversal_evidence` as separate Parquet tables.  `anchor` is derived solely
from PRE placement in recognised major-statement roles; PRE never expands a
traversal.  `traversal_evidence` keeps every direct dimension, DEF/CAL edge,
and explicit `targetRole` transition with a typed evidence record.  It does
not perform Disclosure Safety Net discovery (M5) or canonicalize raw IDs.

## M5 disclosure safety-net boundary

`sec_xbrl.disclosure.safety_net.DisclosureSafetyNet` consumes the immutable
M2/M3 records and inventories every role without requiring an M4 anchor
connection.  It materializes `role_inventory`, `disclosure_index`, and
`disclosure_evidence` as separate Parquet tables.  A role-title match is only
a review signal: a P0/P1/P2 classification requires corroborating raw
concept, reported-fact, or text-block evidence.  Text-block, table, and detail
evidence retain role, fact, source-document, and locator provenance.  M5 does
not merge role networks or canonicalize concepts.

## 1. `filing`
- `filing_id`
- `cik`
- `accession`
- `accession_nodash`
- `form`
- `filed_date`
- `report_date`
- `primary_document`
- `document_fiscal_year_focus`
- `document_fiscal_period_focus`
- `fiscal_year_end`
- `is_amendment`
- `amends_accession` nullable
- `source_url`
- `package_hash` / manifest version

## 2. `concept`
- `raw_concept_id`
- `filing_id` or taxonomy scope identifier
- `qname`
- `namespace_uri`
- `namespace_prefix`
- `local_name`
- `taxonomy_family` (`us-gaap`, `dei`, `srt`, company extension, etc.)
- `taxonomy_version`
- `is_standard`
- `is_custom`
- `data_type`
- `period_type`
- `balance` nullable
- `abstract`
- `nillable`
- `label`
- `documentation`

## 3. `context`
- `context_id`
- `filing_id`
- `entity_identifier`
- `period_kind` (`INSTANT`, `DURATION`, `FOREVER`)
- `start_date`
- `end_date`
- `instant_date`
- `duration_days`
- `dimension_count`
- context XML/hash for traceability when useful

## 4. `unit`
- `unit_id`
- `filing_id`
- normalized numerator/denominator measures
- raw representation

## 5. `fact`
- `fact_id`
- `filing_id`
- `raw_concept_id`
- `context_id`
- `unit_id` nullable
- `value_numeric` nullable
- `value_text` nullable
- `decimals`
- `precision` nullable
- `is_nil`
- `source_document`
- `source_locator` when available
- `reported_or_derived` = `REPORTED` for Layer 1 source facts
- `period_class` (see period contract)
- `comparative_type`

## 6. `dimension_fact`
One row per fact-axis-member assignment.
- `fact_id`
- `axis_raw_concept_id`
- `member_raw_concept_id` or typed member representation
- `dimension_type` (`EXPLICIT`, `TYPED`)
- `is_default_member`

## 7. `role`
- `role_id`
- `filing_id`
- `role_uri`
- `role_definition`
- `role_category` (`STATEMENT`, `DISCLOSURE`, `POLICY`, `TABLE`, `DETAIL`, `OTHER`)

## 8. `relationship`
- `relationship_id`
- `filing_id`
- `network_type` (`PRE`, `CAL`, `DEF`)
- `role_id`
- `arcrole`
- `from_raw_concept_id`
- `to_raw_concept_id`
- `order`
- `weight` nullable
- `preferred_label` nullable
- `target_role_uri` nullable
- `usable` nullable
- `closed` nullable
- `context_element` nullable

## 9. `anchor`
- `filing_id`
- `statement_type` (`BS`, `IS`, `CF`, `EQ`, optional `CI`)
- `role_id`
- `raw_concept_id`
- `anchor_rank` / display order

## 10. `disclosure_index`
- `filing_id`
- `role_id`
- `critical_topic` nullable
- `priority` (`P0`, `P1`, `P2`, `UNCLASSIFIED`)
- signal flags from role title/concepts/text blocks/facts
- `deep_scan_required`

## 10a. `role_inventory`
- `filing_id`, `role_id`, `role_uri`, `role_definition`, `role_category`
- relationship, concept, reported-fact, and text-block counts
- table/detail evidence flags

## 10b. `disclosure_evidence`
- `evidence_id`, `filing_id`, `role_id`, `critical_topic`, `signal_type`
- raw concept and fact IDs nullable
- source document and locator nullable
- source role URI and definition

`signal_type` is one of `ROLE_TITLE`, `CONCEPT`, `FACT`, `TEXT_BLOCK`,
`TABLE_ROLE`, or `DETAIL_ROLE`.  It preserves discovery evidence; it does not
turn a role title alone into a critical-disclosure classification.

## 10c. `traversal_evidence`
- `evidence_id`
- `filing_id`
- `anchor_raw_concept_id`, `statement_type`, `role_id`
- `network_type`, `arcrole`, `from_raw_concept_id`, `to_raw_concept_id`
- `fact_id`, `axis_raw_concept_id`, `member_raw_concept_id` nullable
- `evidence_type` (`DIRECT_DIMENSION`, `DEFINITION_MEMBER`,
  `CALCULATION_CHILD`, `ROLE_EXPANSION`, `STRUCTURAL_ONLY`)
- `source_relationship_id`, `target_role_uri`, `discovery_order`

## 11. Raw identity rule
Never identify a concept/member only by local name. Raw identity must include QName/namespace context. SEC bulk DIM strings are not sufficient as the final long-term identity source.
