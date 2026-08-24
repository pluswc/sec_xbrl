"""Critical-disclosure safety net over immutable Layer 1 records.

This is deliberately independent of M4 anchors.  It inventories *every* raw
role in a filing and classifies a critical disclosure only when a title hint is
corroborated by a concept, a reported fact, or text-block evidence.  The
result is still Layer 1 provenance: it neither joins role networks nor assigns
canonical identities.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.facts.layer1 import Layer1ExtractionError, _stable_id


@dataclass(frozen=True, slots=True)
class _Topic:
    name: str
    priority: str
    phrases: tuple[str, ...]


# The controlled vocabulary is intentionally transparent and conservative.
# Matching is a discovery signal, not a claim of accounting equivalence.
_TOPICS = (
    _Topic("REVENUE_RECOGNITION", "P0", ("revenue recognition", "disaggregation", "contract revenue")),
    _Topic("SEGMENT_GEOGRAPHY_PRODUCT", "P0", ("segment", "geograph", "product", "service")),
    _Topic("CUSTOMER_CONCENTRATION", "P0", ("customer concentration", "major customer")),
    _Topic("DEBT_BORROWING", "P0", ("debt", "borrowing", "credit facility", "maturit", "covenant")),
    _Topic("COMMITMENTS_CONTINGENCIES", "P0", ("commitment", "contingen", "litigation", "guarantee")),
    _Topic("GOING_CONCERN_LIQUIDITY", "P0", ("going concern", "liquidity uncertainty")),
    _Topic("BUSINESS_COMBINATION", "P0", ("business combination", "acquisition", "divestiture", "discontinued operation")),
    _Topic("GOODWILL_INTANGIBLES", "P0", ("goodwill", "intangible", "impairment")),
    _Topic("SUBSEQUENT_EVENTS", "P0", ("subsequent event",)),
    _Topic("INCOME_TAXES", "P0", ("income tax", "uncertain tax", "valuation allowance")),
    _Topic("VIE_CONSOLIDATION", "P0", ("variable interest", "vie", "consolidation", "off-balance")),
    _Topic("LEASES", "P1", ("lease",)),
    _Topic("FAIR_VALUE", "P1", ("fair value",)),
    _Topic("DERIVATIVES_HEDGING", "P1", ("derivative", "hedging")),
    _Topic("STOCK_COMPENSATION", "P1", ("stock compensation", "share-based compensation")),
    _Topic("RELATED_PARTIES", "P1", ("related party",)),
    _Topic("INVENTORY", "P1", ("inventory", "write-down")),
    _Topic("RECEIVABLES_CREDIT_LOSSES", "P1", ("receivable", "credit loss", "allowance")),
    _Topic("PENSION", "P1", ("pension", "retirement benefit")),
    _Topic("ACCOUNTING_POLICY_ESTIMATES", "P2", ("accounting polic", "critical estimate", "significant estimate")),
    _Topic("CAPITAL_RETURNS", "P2", ("share repurchase", "stock repurchase", "dividend")),
)

_PARQUET_SCHEMAS: dict[str, dict[str, str]] = {
    "role_inventory": {
        "filing_id": "string", "role_id": "string", "role_uri": "string", "role_definition": "string",
        "role_category": "string", "relationship_count": "int64", "concept_count": "int64",
        "fact_count": "int64", "text_block_count": "int64", "has_table_evidence": "bool",
        "has_detail_evidence": "bool",
    },
    "disclosure_index": {
        "disclosure_index_id": "string", "filing_id": "string", "role_id": "string",
        "critical_topic": "string", "priority": "string", "has_role_title_signal": "bool",
        "has_concept_signal": "bool", "has_fact_signal": "bool", "has_text_block_signal": "bool",
        "has_table_evidence": "bool", "has_detail_evidence": "bool", "deep_scan_required": "bool",
    },
    "disclosure_evidence": {
        "evidence_id": "string", "filing_id": "string", "role_id": "string", "critical_topic": "string",
        "signal_type": "string", "raw_concept_id": "string", "fact_id": "string",
        "source_document": "string", "source_locator": "string", "source_role_uri": "string",
        "source_role_definition": "string",
    },
}


@dataclass(frozen=True, slots=True)
class DisclosureSafetyNetTables:
    """Immutable role inventory, classification index, and discovery evidence."""

    role_inventory: tuple[dict[str, Any], ...]
    disclosure_index: tuple[dict[str, Any], ...]
    disclosure_evidence: tuple[dict[str, Any], ...]

    def write_parquet(self, destination: Path) -> None:
        """Write an M5 snapshot once; existing raw outputs are never overwritten."""
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - project dependency.
            raise Layer1ExtractionError("polars is required to materialize M5 Parquet") from exc
        paths = tuple(destination / f"{table}.parquet" for table in _PARQUET_SCHEMAS)
        if any(path.exists() for path in paths):
            raise Layer1ExtractionError(f"M5 disclosure snapshot already exists: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        dtypes = {"string": pl.String, "int64": pl.Int64, "bool": pl.Boolean}
        rows_by_table = {
            "role_inventory": self.role_inventory,
            "disclosure_index": self.disclosure_index,
            "disclosure_evidence": self.disclosure_evidence,
        }
        for table, rows in rows_by_table.items():
            schema = {column: dtypes[dtype] for column, dtype in _PARQUET_SCHEMAS[table].items()}
            pl.DataFrame(list(rows), schema=schema, strict=False).write_parquet(
                destination / f"{table}.parquet"
            )


class DisclosureSafetyNet:
    """Inventory and classify critical disclosures without requiring an anchor."""

    def build(
        self,
        *,
        roles: Iterable[Mapping[str, Any]],
        relationships: Iterable[Mapping[str, Any]],
        concepts: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
    ) -> DisclosureSafetyNetTables:
        role_rows = tuple(dict(row) for row in roles)
        relationship_rows = tuple(dict(row) for row in relationships)
        concept_rows = {str(row["raw_concept_id"]): dict(row) for row in concepts}
        fact_rows = tuple(dict(row) for row in facts)
        filing_id = _single_filing_id(role_rows, relationship_rows, concept_rows.values(), fact_rows)
        roles_by_id = {str(row["role_id"]): row for row in role_rows}
        if len(roles_by_id) != len(role_rows):
            raise Layer1ExtractionError("M5 disclosure safety net requires unique role IDs")

        concepts_by_role: dict[str, set[str]] = defaultdict(set)
        relationships_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relationship in relationship_rows:
            role_id = str(relationship["role_id"])
            if role_id not in roles_by_id:
                raise Layer1ExtractionError("relationship references an unknown role")
            relationships_by_role[role_id].append(relationship)
            concepts_by_role[role_id].update(
                (str(relationship["from_raw_concept_id"]), str(relationship["to_raw_concept_id"]))
            )
        facts_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in fact_rows:
            if fact.get("reported_or_derived", "REPORTED") == "REPORTED" and not fact.get("is_nil", False):
                facts_by_concept[str(fact["raw_concept_id"])].append(fact)

        inventory: list[dict[str, Any]] = []
        index: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for role_id, role in sorted(roles_by_id.items()):
            role_concepts = sorted(concepts_by_role[role_id])
            role_facts = [fact for concept_id in role_concepts for fact in facts_by_concept[concept_id]]
            table_evidence = _is_table(role)
            detail_evidence = _is_detail(role)
            text_facts = [fact for fact in role_facts if _is_text_fact(fact, concept_rows.get(str(fact["raw_concept_id"])))]
            inventory.append(
                {
                    "filing_id": filing_id, "role_id": role_id, "role_uri": _text(role.get("role_uri")),
                    "role_definition": _text(role.get("role_definition")), "role_category": _text(role.get("role_category")),
                    "relationship_count": len(relationships_by_role[role_id]), "concept_count": len(role_concepts),
                    "fact_count": len(role_facts), "text_block_count": len(text_facts),
                    "has_table_evidence": table_evidence, "has_detail_evidence": detail_evidence,
                }
            )
            classifications = self._classify_role(
                filing_id, role, role_concepts, role_facts, text_facts, concept_rows, table_evidence, detail_evidence
            )
            if not classifications:
                index.append(_index_row(filing_id, role_id, None, "UNCLASSIFIED", False, False, False, False, table_evidence, detail_evidence))
            else:
                for topic, signals in classifications:
                    title, concept, fact, text = signals
                    index.append(_index_row(filing_id, role_id, topic.name, topic.priority, title, concept, fact, text, table_evidence, detail_evidence))
                    evidence.extend(_topic_evidence(filing_id, role, topic, role_concepts, role_facts, text_facts, concept_rows, table_evidence, detail_evidence))
        return DisclosureSafetyNetTables(
            role_inventory=tuple(inventory),
            disclosure_index=tuple(sorted(index, key=lambda row: row["disclosure_index_id"])),
            disclosure_evidence=tuple(sorted(evidence, key=lambda row: row["evidence_id"])),
        )

    def _classify_role(
        self, filing_id: str, role: Mapping[str, Any], concept_ids: list[str], facts: list[dict[str, Any]],
        text_facts: list[dict[str, Any]], concepts: Mapping[str, Mapping[str, Any]], table: bool, detail: bool,
    ) -> list[tuple[_Topic, tuple[bool, bool, bool, bool]]]:
        del filing_id, table, detail
        result: list[tuple[_Topic, tuple[bool, bool, bool, bool]]] = []
        title_text = _role_text(role)
        for topic in _TOPICS:
            title_signal = _matches(title_text, topic)
            concept_signal = any(_matches(_concept_text(concepts.get(concept_id, {})), topic) for concept_id in concept_ids)
            fact_signal = any(_matches(_fact_text(fact, concepts.get(str(fact["raw_concept_id"]), {})), topic) for fact in facts)
            text_signal = any(_matches(str(fact.get("value_text") or ""), topic) for fact in text_facts)
            # A role title merely prioritizes review.  It cannot itself create a
            # critical result; a raw concept, fact, or text block must corroborate it.
            if title_signal or concept_signal or fact_signal or text_signal:
                if concept_signal or fact_signal or text_signal:
                    result.append((topic, (title_signal, concept_signal, fact_signal, text_signal)))
        return result


def _index_row(
    filing_id: str, role_id: str, topic: str | None, priority: str, title: bool, concept: bool, fact: bool,
    text: bool, table: bool, detail: bool,
) -> dict[str, Any]:
    row = {
        "filing_id": filing_id, "role_id": role_id, "critical_topic": topic, "priority": priority,
        "has_role_title_signal": title, "has_concept_signal": concept, "has_fact_signal": fact,
        "has_text_block_signal": text, "has_table_evidence": table, "has_detail_evidence": detail,
        "deep_scan_required": priority in {"P0", "P1"},
    }
    row["disclosure_index_id"] = _stable_id("disclosure-index", filing_id, role_id, topic, priority)
    return row


def _topic_evidence(
    filing_id: str, role: Mapping[str, Any], topic: _Topic, concept_ids: Iterable[str], facts: Iterable[Mapping[str, Any]],
    text_facts: Iterable[Mapping[str, Any]], concepts: Mapping[str, Mapping[str, Any]], table: bool, detail: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    role_id = str(role["role_id"])
    def add(signal_type: str, concept_id: str | None = None, fact: Mapping[str, Any] | None = None) -> None:
        row = {
            "filing_id": filing_id, "role_id": role_id, "critical_topic": topic.name, "signal_type": signal_type,
            "raw_concept_id": concept_id, "fact_id": None if fact is None else _text(fact.get("fact_id")),
            "source_document": None if fact is None else _text(fact.get("source_document")),
            "source_locator": None if fact is None else _text(fact.get("source_locator")),
            "source_role_uri": _text(role.get("role_uri")), "source_role_definition": _text(role.get("role_definition")),
        }
        row["evidence_id"] = _stable_id("disclosure-evidence", *row.values())
        result.append(row)
    if _matches(_role_text(role), topic):
        add("ROLE_TITLE")
    for concept_id in concept_ids:
        if _matches(_concept_text(concepts.get(concept_id, {})), topic):
            add("CONCEPT", concept_id)
    for fact in facts:
        concept_id = str(fact["raw_concept_id"])
        if _matches(_fact_text(fact, concepts.get(concept_id, {})), topic):
            add("FACT", concept_id, fact)
    for fact in text_facts:
        if _matches(str(fact.get("value_text") or ""), topic):
            add("TEXT_BLOCK", str(fact["raw_concept_id"]), fact)
    if table:
        add("TABLE_ROLE")
    if detail:
        add("DETAIL_ROLE")
    return result


def _single_filing_id(*row_sets: Iterable[Mapping[str, Any]]) -> str:
    filing_ids = {str(row["filing_id"]) for rows in row_sets for row in rows if row.get("filing_id") is not None}
    if len(filing_ids) != 1:
        raise Layer1ExtractionError("M5 disclosure safety net requires records from exactly one filing")
    return filing_ids.pop()


def _matches(value: str, topic: _Topic) -> bool:
    lowered = value.lower()
    return any(phrase in lowered for phrase in topic.phrases)


def _role_text(role: Mapping[str, Any]) -> str:
    return " ".join(str(role.get(field) or "") for field in ("role_definition", "role_uri"))


def _concept_text(concept: Mapping[str, Any]) -> str:
    return " ".join(str(concept.get(field) or "") for field in ("qname", "local_name", "label", "documentation"))


def _fact_text(fact: Mapping[str, Any], concept: Mapping[str, Any]) -> str:
    return _concept_text(concept) + " " + str(fact.get("value_text") or "")


def _is_text_fact(fact: Mapping[str, Any], concept: Mapping[str, Any] | None) -> bool:
    if fact.get("value_text"):
        return True
    return bool(concept and "textblock" in str(concept.get("data_type") or "").lower())


def _is_table(role: Mapping[str, Any]) -> bool:
    return str(role.get("role_category") or "").upper() == "TABLE" or "table" in _role_text(role).lower()


def _is_detail(role: Mapping[str, Any]) -> bool:
    return str(role.get("role_category") or "").upper() == "DETAIL" or "detail" in _role_text(role).lower()


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
