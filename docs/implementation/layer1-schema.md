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

## 11. Raw identity rule
Never identify a concept/member only by local name. Raw identity must include QName/namespace context. SEC bulk DIM strings are not sufficient as the final long-term identity source.
