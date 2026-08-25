"""Contract-bound anchor traversal over immutable Layer 1 records.

This module interprets the M2/M3 records without mutating or combining their
networks.  Presentation is used only to identify concepts displayed in major
financial statements.  Definition and calculation edges are then followed
under their separate rules, with every result retaining its raw provenance.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.facts.layer1 import Layer1ExtractionError, _stable_id

_PRESENTATION = "PRE"
_CALCULATION = "CAL"
_DEFINITION = "DEF"
_REPORTED = "REPORTED"

_DIMENSIONAL_ARCROLE_SUFFIXES = frozenset(
    {
        "/all",
        "/notAll",
        "/hypercube-dimension",
        "/dimension-domain",
        "/domain-member",
        "/dimension-default",
    }
)

_DEF_NEXT_STATES = {
    "PRIMARY": {"all": "HYPERCUBE", "notAll": "HYPERCUBE"},
    "HYPERCUBE": {"hypercube-dimension": "DIMENSION"},
    "DIMENSION": {"dimension-domain": "DOMAIN", "dimension-default": "DEFAULT_MEMBER"},
    "DOMAIN": {"domain-member": "MEMBER"},
    "MEMBER": {"domain-member": "MEMBER"},
}

_PARQUET_SCHEMAS: dict[str, dict[str, str]] = {
    "anchor": {
        "filing_id": "string",
        "statement_type": "string",
        "role_id": "string",
        "raw_concept_id": "string",
        "anchor_rank": "string",
    },
    "traversal_evidence": {
        "evidence_id": "string",
        "filing_id": "string",
        "anchor_raw_concept_id": "string",
        "statement_type": "string",
        "role_id": "string",
        "network_type": "string",
        "arcrole": "string",
        "from_raw_concept_id": "string",
        "to_raw_concept_id": "string",
        "fact_id": "string",
        "axis_raw_concept_id": "string",
        "member_raw_concept_id": "string",
        "evidence_type": "string",
        "source_relationship_id": "string",
        "target_role_uri": "string",
        "discovery_order": "int64",
    },
}


@dataclass(frozen=True, slots=True)
class AnchorTraversalTables:
    """Anchors and immutable, provenance-first traversal evidence."""

    anchors: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]

    def write_parquet(self, destination: Path) -> None:
        """Materialize M4 output once; never rewrite an existing snapshot."""
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - project dependency.
            raise Layer1ExtractionError("polars is required to materialize M4 Parquet") from exc
        paths = tuple(destination / f"{table}.parquet" for table in _PARQUET_SCHEMAS)
        if any(path.exists() for path in paths):
            raise Layer1ExtractionError(f"M4 traversal snapshot already exists: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for table, rows in (("anchor", self.anchors), ("traversal_evidence", self.evidence)):
            dtypes = {"string": pl.String, "int64": pl.Int64}
            schema = {name: dtypes[dtype] for name, dtype in _PARQUET_SCHEMAS[table].items()}
            pl.DataFrame(list(rows), schema=schema, strict=False).write_parquet(
                destination / f"{table}.parquet"
            )


class AnchorTraversal:
    """Discover major-statement anchors and traverse DEF/CAL evidence.

    The input is deliberately the already materialized Layer 1 record shape,
    rather than an Arelle model.  That gives later readers identical behaviour
    from the immutable raw Parquet snapshot and avoids a second model-level
    interpretation boundary.
    """

    def traverse(
        self,
        *,
        roles: Iterable[Mapping[str, Any]],
        relationships: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]],
        concepts: Iterable[Mapping[str, Any]] = (),
    ) -> AnchorTraversalTables:
        role_rows = tuple(dict(row) for row in roles)
        relationship_rows = tuple(dict(row) for row in relationships)
        fact_rows = tuple(dict(row) for row in facts)
        dimension_rows = tuple(dict(row) for row in dimension_facts)
        concept_rows = {str(row["raw_concept_id"]): dict(row) for row in concepts}
        role_by_id = {str(row["role_id"]): row for row in role_rows}
        role_by_uri = {str(row["role_uri"]): row for row in role_rows}
        filing_id = _single_filing_id(role_rows, relationship_rows, fact_rows)

        anchors = _anchors(relationship_rows, role_by_id, concept_rows, filing_id)
        facts_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in fact_rows:
            if fact.get("reported_or_derived") == _REPORTED and not fact.get("is_nil", False):
                facts_by_concept[str(fact["raw_concept_id"])].append(fact)
        dimensions_by_fact: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for dimension in dimension_rows:
            dimensions_by_fact[str(dimension["fact_id"])].append(dimension)

        by_network_and_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for relationship in relationship_rows:
            network = relationship.get("network_type")
            if network in {_DEFINITION, _CALCULATION}:
                by_network_and_role[(str(network), str(relationship["role_id"]))].append(
                    relationship
                )
        for edges in by_network_and_role.values():
            edges.sort(key=_relationship_sort_key)

        evidence: list[dict[str, Any]] = []
        order = 0
        for anchor in anchors:
            anchor_id = str(anchor["raw_concept_id"])
            statement_type = str(anchor["statement_type"])
            # TR-002: stage all direct dimensional evidence before graph expansion.
            for fact in sorted(facts_by_concept[anchor_id], key=lambda row: str(row["fact_id"])):
                for dimension in sorted(
                    dimensions_by_fact.get(str(fact["fact_id"]), ()), key=_dimension_sort_key
                ):
                    order += 1
                    evidence.append(
                        _evidence_row(
                            filing_id=filing_id,
                            anchor_id=anchor_id,
                            statement_type=statement_type,
                            role_id=str(anchor["role_id"]),
                            network_type=None,
                            arcrole=None,
                            from_id=anchor_id,
                            to_id=dimension.get("member_raw_concept_id")
                            or dimension.get("axis_raw_concept_id"),
                            fact_id=str(fact["fact_id"]),
                            axis_id=dimension.get("axis_raw_concept_id"),
                            member_id=dimension.get("member_raw_concept_id"),
                            evidence_type="DIRECT_DIMENSION",
                            relationship_id=None,
                            target_role_uri=None,
                            order=order,
                        )
                    )

            # A role is eligible only because the anchor appears in it (TR-008),
            # or because a DEF edge explicitly transitions via targetRole (TR-004).
            starting_roles = _roles_containing_anchor(
                anchor_id, by_network_and_role, role_by_id, (_DEFINITION, _CALCULATION)
            )
            for network in (_DEFINITION, _CALCULATION):
                for role_id in starting_roles[network]:
                    if role_id != anchor["role_id"]:
                        order += 1
                        evidence.append(
                            _evidence_row(
                                filing_id=filing_id,
                                anchor_id=anchor_id,
                                statement_type=statement_type,
                                role_id=role_id,
                                network_type=network,
                                arcrole=None,
                                from_id=anchor_id,
                                to_id=anchor_id,
                                fact_id=None,
                                axis_id=None,
                                member_id=None,
                                evidence_type="ROLE_EXPANSION",
                                relationship_id=None,
                                # This is a TR-008 anchor-presence expansion,
                                # not an explicit XBRL targetRole transition.
                                target_role_uri=None,
                                order=order,
                            )
                        )
                    order = self._walk_network(
                        filing_id=filing_id,
                        anchor_id=anchor_id,
                        statement_type=statement_type,
                        network=network,
                        start_role_id=role_id,
                        start_concept_id=anchor_id,
                        edges_by_network_role=by_network_and_role,
                        role_by_uri=role_by_uri,
                        facts_by_concept=facts_by_concept,
                        evidence=evidence,
                        order=order,
                    )

        return AnchorTraversalTables(anchors=tuple(anchors), evidence=tuple(evidence))

    def _walk_network(
        self,
        *,
        filing_id: str,
        anchor_id: str,
        statement_type: str,
        network: str,
        start_role_id: str,
        start_concept_id: str,
        edges_by_network_role: Mapping[tuple[str, str], list[dict[str, Any]]],
        role_by_uri: Mapping[str, Mapping[str, Any]],
        facts_by_concept: Mapping[str, list[dict[str, Any]]],
        evidence: list[dict[str, Any]],
        order: int,
    ) -> int:
        """Walk outgoing edges iteratively, with network-aware cycle control."""
        stack = [(start_role_id, start_concept_id, "PRIMARY" if network == _DEFINITION else None)]
        visited: set[tuple[str, str, str, str]] = set()
        while stack:
            role_id, from_id, def_state = stack.pop()
            edges = edges_by_network_role.get((network, role_id), ())
            for edge in edges:
                if str(edge["from_raw_concept_id"]) != from_id:
                    continue
                next_def_state = None
                if network == _DEFINITION:
                    next_def_state = _def_next_state(def_state, edge.get("arcrole"))
                    if next_def_state is None:
                        continue
                to_id = str(edge["to_raw_concept_id"])
                key = (
                    filing_id,
                    network,
                    role_id,
                    _relationship_identity(edge),
                )
                if key in visited:
                    continue
                visited.add(key)
                order += 1
                evidence_type = _edge_evidence_type(network, to_id, facts_by_concept)
                evidence.append(
                    _evidence_row(
                        filing_id=filing_id,
                        anchor_id=anchor_id,
                        statement_type=statement_type,
                        role_id=role_id,
                        network_type=network,
                        arcrole=edge.get("arcrole"),
                        from_id=from_id,
                        to_id=to_id,
                        fact_id=None,
                        axis_id=None,
                        member_id=None,
                        evidence_type=evidence_type,
                        relationship_id=edge.get("relationship_id"),
                        target_role_uri=edge.get("target_role_uri"),
                        order=order,
                    )
                )
                next_role_id = role_id
                target_role_uri = edge.get("target_role_uri")
                if network == _DEFINITION and target_role_uri:
                    target_role = role_by_uri.get(str(target_role_uri))
                    if target_role is not None:
                        next_role_id = str(target_role["role_id"])
                        order += 1
                        evidence.append(
                            _evidence_row(
                                filing_id=filing_id,
                                anchor_id=anchor_id,
                                statement_type=statement_type,
                                role_id=next_role_id,
                                network_type=network,
                                arcrole=edge.get("arcrole"),
                                from_id=to_id,
                                to_id=to_id,
                                fact_id=None,
                                axis_id=None,
                                member_id=None,
                                evidence_type="ROLE_EXPANSION",
                                relationship_id=edge.get("relationship_id"),
                                target_role_uri=str(target_role_uri),
                                order=order,
                            )
                        )
                stack.append((next_role_id, to_id, next_def_state))
        return order


def _single_filing_id(*row_sets: Iterable[Mapping[str, Any]]) -> str:
    ids = {
        str(row["filing_id"])
        for rows in row_sets
        for row in rows
        if row.get("filing_id") is not None
    }
    if len(ids) != 1:
        raise Layer1ExtractionError("M4 traversal requires records from exactly one filing")
    return ids.pop()


def _anchors(
    relationships: Iterable[Mapping[str, Any]],
    role_by_id: Mapping[str, Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
    filing_id: str,
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relationship in relationships:
        if relationship.get("network_type") != _PRESENTATION:
            continue
        role_id = str(relationship["role_id"])
        statement_type = _statement_type(role_by_id.get(role_id, {}))
        if statement_type is None:
            continue
        for concept_id in (
            str(relationship["from_raw_concept_id"]),
            str(relationship["to_raw_concept_id"]),
        ):
            if concepts.get(concept_id, {}).get("abstract") is True:
                continue
            key = (statement_type, role_id, concept_id)
            rank = _rank(relationship.get("order"))
            existing = candidates.get(key)
            if existing is None or rank < _rank(existing["anchor_rank"]):
                candidates[key] = {
                    "filing_id": filing_id,
                    "statement_type": statement_type,
                    "role_id": role_id,
                    "raw_concept_id": concept_id,
                    "anchor_rank": _text_rank(relationship.get("order")),
                }
    return sorted(
        candidates.values(),
        key=lambda row: (row["statement_type"], row["role_id"], _rank(row["anchor_rank"]), row["raw_concept_id"]),
    )


def _statement_type(role: Mapping[str, Any]) -> str | None:
    title = str(role.get("role_definition") or "").lower()
    if "cash flow" in title:
        return "CF"
    if "equity" in title or "stockholder" in title or "shareholder" in title:
        return "EQ"
    if "balance sheet" in title or "financial position" in title:
        return "BS"
    if "income" in title or "operations" in title or "earnings" in title:
        return "IS"
    return None


def _roles_containing_anchor(
    anchor_id: str,
    edges_by_network_role: Mapping[tuple[str, str], list[dict[str, Any]]],
    role_by_id: Mapping[str, Mapping[str, Any]],
    networks: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for network in networks:
        role_ids = [
            role_id
            for (edge_network, role_id), edges in edges_by_network_role.items()
            if edge_network == network
            and any(str(edge["from_raw_concept_id"]) == anchor_id for edge in edges)
        ]
        result[network] = tuple(
            sorted(role_ids, key=lambda role_id: str(role_by_id[role_id].get("role_uri") or role_id))
        )
    return result


def _def_next_state(current_state: str | None, arcrole: Any) -> str | None:
    """Return the allowed next DEF state for one semantic dimensional arc."""
    text = str(arcrole or "")
    for suffix in _DIMENSIONAL_ARCROLE_SUFFIXES:
        if text.endswith(suffix):
            kind = suffix.removeprefix("/")
            return _DEF_NEXT_STATES.get(current_state or "", {}).get(kind)
    return None


def _relationship_identity(edge: Mapping[str, Any]) -> str:
    """Use M3 relationship identity, including base-set provenance, for cycles."""
    relationship_id = edge.get("relationship_id")
    if relationship_id is not None:
        return str(relationship_id)
    return _stable_id(
        "m4-edge",
        edge.get("network_type"),
        edge.get("role_id"),
        edge.get("arcrole"),
        edge.get("link_qname"),
        edge.get("arc_qname"),
        edge.get("from_raw_concept_id"),
        edge.get("to_raw_concept_id"),
    )


def _edge_evidence_type(
    network: str, to_id: str, facts_by_concept: Mapping[str, list[dict[str, Any]]]
) -> str:
    if network == _CALCULATION:
        return "CALCULATION_CHILD"
    return "DEFINITION_MEMBER" if facts_by_concept.get(to_id) else "STRUCTURAL_ONLY"


def _evidence_row(
    *,
    filing_id: str,
    anchor_id: str,
    statement_type: str,
    role_id: str,
    network_type: str | None,
    arcrole: Any,
    from_id: Any,
    to_id: Any,
    fact_id: str | None,
    axis_id: Any,
    member_id: Any,
    evidence_type: str,
    relationship_id: Any,
    target_role_uri: Any,
    order: int,
) -> dict[str, Any]:
    row = {
        "filing_id": filing_id,
        "anchor_raw_concept_id": anchor_id,
        "statement_type": statement_type,
        "role_id": role_id,
        "network_type": network_type,
        "arcrole": _text(arcrole),
        "from_raw_concept_id": _text(from_id),
        "to_raw_concept_id": _text(to_id),
        "fact_id": fact_id,
        "axis_raw_concept_id": _text(axis_id),
        "member_raw_concept_id": _text(member_id),
        "evidence_type": evidence_type,
        "source_relationship_id": _text(relationship_id),
        "target_role_uri": _text(target_role_uri),
        "discovery_order": order,
    }
    row["evidence_id"] = _stable_id("traversal-evidence", *row.values())
    return row


def _relationship_sort_key(row: Mapping[str, Any]) -> tuple[Decimal, str]:
    return _rank(row.get("order")), str(row.get("relationship_id") or "")


def _dimension_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("axis_raw_concept_id") or ""), str(row.get("member_raw_concept_id") or "")


def _rank(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("Infinity")


def _text_rank(value: Any) -> str | None:
    return None if value is None else str(value)


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
