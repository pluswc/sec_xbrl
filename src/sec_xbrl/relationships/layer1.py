"""Immutable extraction of Arelle role and relationship networks for Layer 1.

This boundary records linkbase evidence only.  In particular, a ``targetRole``
is retained as an explicit transition but is never followed here, and PRE,
CAL, and DEF records remain distinct networks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.facts.layer1 import (
    Layer1ExtractionError,
    _concept_row,
    _qname_parts,
    _qname_text,
    _stable_id,
)
from sec_xbrl.filing.company_discovery import canonicalize_cik
from sec_xbrl.filing.contracts import FilingRef

_PRESENTATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/parent-child"
_CALCULATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"

_PARQUET_SCHEMAS: dict[str, dict[str, str]] = {
    "role": {
        "role_id": "string",
        "filing_id": "string",
        "role_uri": "string",
        "role_definition": "string",
        "role_category": "string",
    },
    "relationship": {
        "relationship_id": "string",
        "filing_id": "string",
        "network_type": "string",
        "role_id": "string",
        "arcrole": "string",
        "link_qname": "string",
        "arc_qname": "string",
        "from_raw_concept_id": "string",
        "to_raw_concept_id": "string",
        "order": "string",
        "weight": "string",
        "preferred_label": "string",
        "target_role_uri": "string",
        "usable": "bool",
        "closed": "bool",
        "context_element": "string",
    },
}


@dataclass(frozen=True, slots=True)
class RelationshipTables:
    """As-filed role and relationship records ready for Parquet materialization."""

    roles: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    # Relationship endpoint Concepts are emitted for ingestion to merge into
    # the immutable Layer 1 concept table.  A Fact-only concept inventory would
    # make PRE/CAL/DEF hierarchy labels unavailable for abstract/no-value rows.
    concepts: tuple[dict[str, Any], ...] = ()

    def write_parquet(self, destination: Path) -> None:
        """Write immutable relationship tables without rewriting an existing snapshot."""
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - project dependency.
            raise Layer1ExtractionError(
                "polars is required to materialize Layer 1 Parquet"
            ) from exc
        paths = tuple(destination / f"{name}.parquet" for name in _PARQUET_SCHEMAS)
        if any(path.exists() for path in paths):
            raise Layer1ExtractionError(
                f"Layer 1 relationship snapshot already exists: {destination}"
            )
        destination.mkdir(parents=True, exist_ok=True)
        for name, rows in (("role", self.roles), ("relationship", self.relationships)):
            schema = {
                column: {"string": pl.String, "bool": pl.Boolean}[dtype]
                for column, dtype in _PARQUET_SCHEMAS[name].items()
            }
            pl.DataFrame(list(rows), schema=schema, strict=False).write_parquet(
                destination / f"{name}.parquet"
            )


class RelationshipExtractor:
    """Extract as-filed PRE/CAL/DEF networks without graph traversal."""

    parser_version = "m3-relationships-v1"

    def extract(self, model: Any, filing: FilingRef) -> RelationshipTables:
        """Return role and relationship records from one loaded Arelle model.

        Arelle's ``baseSets`` is used to discover explicit arcrole/linkrole
        pairs.  This avoids creating a synthetic graph across roles or network
        types and also makes the boundary straightforward to fixture-test.
        """
        filing_id = _stable_id("filing", canonicalize_cik(filing.cik), filing.accession)
        role_definitions = _role_definitions(model)
        role_rows: dict[str, dict[str, Any]] = {}
        relationship_rows: dict[str, dict[str, Any]] = {}
        concept_rows: dict[str, dict[str, Any]] = {}

        for role_uri, definition in role_definitions.items():
            row = _role_row(filing_id, role_uri, definition)
            role_rows[row["role_id"]] = row

        for arcrole, role_uri, linkqname, arcqname in _network_keys(model):
            network_type = _network_type(arcrole)
            if network_type is None or not role_uri:
                continue
            role_row = _role_row(filing_id, role_uri, role_definitions.get(role_uri))
            role_rows.setdefault(role_row["role_id"], role_row)
            for relationship in _relationships(model, arcrole, role_uri, linkqname, arcqname):
                from_id = _raw_concept_id(filing_id, getattr(relationship, "fromModelObject", None))
                to_id = _raw_concept_id(filing_id, getattr(relationship, "toModelObject", None))
                if from_id is None or to_id is None:
                    # Non-concept resources (for example labels) do not belong
                    # to the PRE/CAL/DEF concept network contract.
                    continue
                for endpoint in (
                    getattr(relationship, "fromModelObject", None),
                    getattr(relationship, "toModelObject", None),
                ):
                    concept = _relationship_concept_row(filing_id, endpoint)
                    if concept is not None:
                        _store_concept(concept_rows, concept)
                row = {
                    "filing_id": filing_id,
                    "network_type": network_type,
                    "role_id": role_row["role_id"],
                    "arcrole": str(getattr(relationship, "arcrole", None) or arcrole),
                    # Arelle base-set identity includes link/arc QNames.  Keep
                    # them so matching endpoint arcs do not merge across
                    # distinct extended-link networks.
                    "link_qname": _network_qname(linkqname),
                    "arc_qname": _network_qname(arcqname),
                    "from_raw_concept_id": from_id,
                    "to_raw_concept_id": to_id,
                    "order": _text(_attribute(relationship, "order")),
                    "weight": _text(_attribute(relationship, "weight")),
                    "preferred_label": _text(
                        _attribute(relationship, "preferredLabel", "preferredLabel")
                    ),
                    "target_role_uri": _text(_attribute(relationship, "targetRole", "targetRole")),
                    "usable": _bool(_attribute(relationship, "usable", "usable", "isUsable")),
                    "closed": _bool(_attribute(relationship, "closed", "closed")),
                    "context_element": _text(
                        _attribute(relationship, "contextElement", "contextElement")
                    ),
                }
                row["relationship_id"] = _stable_id(
                    "relationship",
                    row["filing_id"],
                    row["network_type"],
                    role_uri,
                    row["arcrole"],
                    row["link_qname"],
                    row["arc_qname"],
                    row["from_raw_concept_id"],
                    row["to_raw_concept_id"],
                    row["order"],
                    row["weight"],
                    row["preferred_label"],
                    row["target_role_uri"],
                    row["usable"],
                    row["closed"],
                    row["context_element"],
                )
                relationship_rows.setdefault(row["relationship_id"], row)

        return RelationshipTables(
            roles=tuple(sorted(role_rows.values(), key=lambda row: row["role_uri"])),
            relationships=tuple(
                sorted(relationship_rows.values(), key=lambda row: row["relationship_id"])
            ),
            concepts=tuple(sorted(concept_rows.values(), key=lambda row: row["raw_concept_id"])),
        )


def _network_keys(model: Any) -> tuple[tuple[str, str, Any, Any], ...]:
    keys = getattr(model, "baseSets", {}) or {}
    by_network: dict[tuple[str, str], list[tuple[str, str, Any, Any]]] = {}
    for key in keys:
        if not isinstance(key, tuple) or len(key) < 2:
            continue
        arcrole, role_uri = key[:2]
        if not isinstance(arcrole, str) or not isinstance(role_uri, str):
            continue
        # Other Arelle base sets (for example XBRL-dimensions infrastructure)
        # are not Layer 1 PRE/CAL/DEF concept networks and are ignored here.
        if _network_type(arcrole) is None or not role_uri:
            continue
        linkqname = key[2] if len(key) > 2 else None
        arcqname = key[3] if len(key) > 3 else None
        by_network.setdefault((arcrole, role_uri), []).append(
            (arcrole, role_uri, linkqname, arcqname)
        )

    result: list[tuple[str, str, Any, Any]] = []
    for network, candidates in by_network.items():
        # Arelle publishes wildcard aliases for the same base set: e.g.
        # (role, None, None), (role, None, arc), (role, link, None), and the
        # fully specified (role, link, arc).  Only the latter identifies the
        # distinct extended-link network.  Reading aliases would reproduce
        # every relationship up to four times.
        fully_specified = [
            key for key in candidates if key[2] is not None and key[3] is not None
        ]
        if not fully_specified:
            arcrole, role_uri = network
            raise Layer1ExtractionError(
                "recognized relationship network lacks a fully specified "
                f"link/arc QName base set: arcrole={arcrole!r}, role={role_uri!r}"
            )
        # Preserve QName objects for ``relationshipSet``. A separate printable
        # identity makes fixture QNames deterministic even when unhashable.
        seen: set[tuple[str, str, str, str]] = set()
        for key in fully_specified:
            identity = (key[0], key[1], str(key[2]), str(key[3]))
            if identity not in seen:
                seen.add(identity)
                result.append(key)
    return tuple(sorted(result, key=lambda key: (key[0], key[1], str(key[2]), str(key[3]))))


def _relationships(
    model: Any, arcrole: str, role_uri: str, linkqname: Any, arcqname: Any
) -> tuple[Any, ...]:
    method = getattr(model, "relationshipSet", None)
    if not callable(method):
        raise Layer1ExtractionError("loaded model does not expose relationshipSet")
    try:
        relationship_set = method(arcrole, role_uri, linkqname, arcqname)
    except TypeError:
        relationship_set = method(arcrole, role_uri)
    return tuple(getattr(relationship_set, "modelRelationships", ()) or ())


def _role_definitions(model: Any) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for role_uri, role_types in (getattr(model, "roleTypes", {}) or {}).items():
        role_type = next(iter(role_types), None) if role_types else None
        result[str(role_uri)] = _text(getattr(role_type, "definition", None))
    return result


def _role_row(filing_id: str, role_uri: str, definition: str | None) -> dict[str, Any]:
    return {
        "role_id": _stable_id("role", filing_id, role_uri),
        "filing_id": filing_id,
        "role_uri": role_uri,
        "role_definition": definition,
        "role_category": _role_category(definition),
    }


def _role_category(definition: str | None) -> str:
    title = (definition or "").lower()
    if "statement" in title:
        return "STATEMENT"
    if "policy" in title:
        return "POLICY"
    if "table" in title:
        return "TABLE"
    if "detail" in title:
        return "DETAIL"
    if "disclosure" in title or "note" in title:
        return "DISCLOSURE"
    return "OTHER"


def _network_type(arcrole: str) -> str | None:
    if arcrole == _PRESENTATION_ARCROLE:
        return "PRE"
    if arcrole == _CALCULATION_ARCROLE:
        return "CAL"
    if arcrole.startswith(
        ("http://xbrl.org/int/dim/arcrole/", "http://www.xbrl.org/2003/arcrole/")
    ):
        return "DEF"
    return None


def _raw_concept_id(filing_id: str, model_object: Any) -> str | None:
    qname = getattr(model_object, "qname", None)
    if qname is None:
        return None
    namespace_uri, _, local_name = _qname_parts(qname)
    return _stable_id("concept", filing_id, namespace_uri, local_name)


def _relationship_concept_row(filing_id: str, model_object: Any) -> dict[str, Any] | None:
    qname = getattr(model_object, "qname", None)
    if qname is None:
        return None
    return _concept_row(filing_id, qname, model_object)


def _store_concept(rows: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    existing = rows.get(row["raw_concept_id"])
    if existing is None or _concept_score(row) > _concept_score(existing):
        rows[row["raw_concept_id"]] = row


def _concept_score(row: dict[str, Any]) -> int:
    return sum(
        row.get(field) is not None
        for field in ("data_type", "period_type", "balance", "label", "documentation")
    )


def _network_qname(value: Any) -> str | None:
    """Render a base-set QName without assuming fixture objects are QNames."""
    if value is None:
        return None
    try:
        return _qname_text(value)
    except Layer1ExtractionError:
        return _text(value)


def _attribute(relationship: Any, *names: str) -> Any:
    for name in names:
        value = getattr(relationship, name, None)
        if value is not None:
            return value
        arc = getattr(relationship, "arcElement", None)
        getter = getattr(arc, "get", None)
        if callable(getter):
            value = getter(name)
            if value is not None:
                return value
    return None


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"true", "1"}:
        return True
    if str(value).lower() in {"false", "0"}:
        return False
    return None


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
