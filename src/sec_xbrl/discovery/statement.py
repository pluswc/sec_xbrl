"""Evidence-first discovery of statement items and connected disclosures.

This is a read-only analytical view over one immutable Layer 1 snapshot.  It
does not decide that a company-specific item is a canonical metric and it does
not use label similarity to join a financial statement to a note.  Instead it
returns the raw XBRL evidence that a consumer can render as a browsable
``statement -> item -> detail disclosure`` map.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from sec_xbrl.traversal.anchor import AnchorTraversal

StatementType = Literal["IS", "BS", "CF", "EQ"]
_STATEMENT_TYPES = frozenset({"IS", "BS", "CF", "EQ"})


@dataclass(frozen=True, slots=True)
class StatementDiscovery:
    """Raw-provenance discovery output for one statement in one filing.

    ``statement_hierarchy`` is display evidence from PRE, ``direct_dimensions``
    are facts actually reported with Axis/Member assignments, and
    ``structural_members`` records the distinct DEF taxonomy structure.  A
    structural member is never presented as a reported value merely because it
    appears in the taxonomy.
    """

    statement_type: StatementType
    filing: dict[str, Any]
    anchors: tuple[dict[str, Any], ...]
    statement_hierarchy: tuple[dict[str, Any], ...]
    direct_dimensions: tuple[dict[str, Any], ...]
    structural_members: tuple[dict[str, Any], ...]
    concept_role_links: tuple[dict[str, Any], ...]
    related_roles: tuple[dict[str, Any], ...]
    period_change_evidence: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a copy suitable for JSON/API serialization."""
        return {
            "statement_type": self.statement_type,
            "filing": deepcopy(self.filing),
            "anchors": deepcopy(self.anchors),
            "statement_hierarchy": deepcopy(self.statement_hierarchy),
            "direct_dimensions": deepcopy(self.direct_dimensions),
            "structural_members": deepcopy(self.structural_members),
            "concept_role_links": deepcopy(self.concept_role_links),
            "related_roles": deepcopy(self.related_roles),
            "period_change_evidence": deepcopy(self.period_change_evidence),
        }


class StatementDiscoveryError(ValueError):
    """Raised when records cannot form one complete, coherent filing view."""


class CompanyDisclosureDiscovery:
    """Discover statement anchors and evidence-backed related disclosures.

    Role expansion follows TR-008 only:

    * a role actually contains an anchor concept; or
    * a role contains a CAL/DEF concept reached from that anchor; or
    * an AnchorTraversal record has an explicit ``targetRole`` transition.

    A similar label, role title, namespace, or keyword is deliberately not an
    expansion signal.  The caller may use M5 Safety Net results as a separate
    track, but those are not merged into this result without their own evidence.
    """

    def discover(
        self,
        *,
        statement_type: StatementType,
        filing: Iterable[Mapping[str, Any]],
        concepts: Iterable[Mapping[str, Any]],
        contexts: Iterable[Mapping[str, Any]],
        facts: Iterable[Mapping[str, Any]],
        dimension_facts: Iterable[Mapping[str, Any]],
        roles: Iterable[Mapping[str, Any]],
        relationships: Iterable[Mapping[str, Any]],
    ) -> StatementDiscovery:
        """Build one statement discovery view from one Layer 1 snapshot."""
        if statement_type not in _STATEMENT_TYPES:
            raise StatementDiscoveryError(f"unsupported statement_type: {statement_type!r}")
        filing_rows = _rows(filing)
        concept_rows = _rows(concepts)
        context_rows = _rows(contexts)
        fact_rows = _rows(facts)
        dimension_rows = _rows(dimension_facts)
        role_rows = _rows(roles)
        relationship_rows = _rows(relationships)
        filing_row = _one_filing(filing_rows, concept_rows, context_rows, fact_rows, role_rows)
        concept_by_id = {str(row["raw_concept_id"]): row for row in concept_rows}
        role_by_id = {str(row["role_id"]): row for row in role_rows}
        context_by_id = {str(row["context_id"]): row for row in context_rows}
        facts_by_id = {str(row["fact_id"]): row for row in fact_rows}

        traversal = AnchorTraversal().traverse(
            roles=role_rows,
            relationships=relationship_rows,
            facts=fact_rows,
            dimension_facts=dimension_rows,
            concepts=concept_rows,
        )
        reported_concept_ids = {
            str(row["raw_concept_id"])
            for row in fact_rows
            if row.get("reported_or_derived", "REPORTED") == "REPORTED" and not row.get("is_nil", False)
        }
        anchors = tuple(
            _with_concept(row, concept_by_id, "raw_concept_id")
            for row in traversal.anchors
            if row["statement_type"] == statement_type
            and str(row["raw_concept_id"]) in reported_concept_ids
            and _qualifying_statement_role(role_by_id.get(str(row["role_id"]), {}), statement_type)
        )
        anchor_ids = {str(row["raw_concept_id"]) for row in anchors}
        statement_role_ids = {str(row["role_id"]) for row in anchors}
        hierarchy = _statement_hierarchy(
            statement_type, statement_role_ids, relationship_rows, concept_by_id
        )
        direct_dimensions = _direct_dimensions(
            anchors, facts_by_id, dimension_rows, context_by_id, concept_by_id
        )
        evidence = tuple(
            row
            for row in traversal.evidence
            if row["statement_type"] == statement_type and str(row["anchor_raw_concept_id"]) in anchor_ids
        )
        structural_members = _structural_members(evidence, direct_dimensions, concept_by_id)
        concept_role_links, related_roles = _related_roles(
            anchors, evidence, role_rows, relationship_rows, concept_by_id, statement_role_ids
        )
        period_change_evidence = _period_evidence(
            anchors, fact_rows, context_by_id, concept_by_id, dimension_rows
        )
        return StatementDiscovery(
            statement_type=statement_type,
            filing=deepcopy(filing_row),
            anchors=tuple(
                sorted(
                    anchors,
                    key=lambda row: (
                        str(row["role_id"]),
                        _rank(row.get("anchor_rank")),
                        str(row["raw_concept_id"]),
                    ),
                )
            ),
            statement_hierarchy=tuple(hierarchy),
            direct_dimensions=tuple(direct_dimensions),
            structural_members=tuple(structural_members),
            concept_role_links=tuple(concept_role_links),
            related_roles=tuple(related_roles),
            period_change_evidence=tuple(period_change_evidence),
        )

    def discover_snapshot(
        self, snapshot_dir: Path, *, statement_type: StatementType
    ) -> StatementDiscovery:
        """Load standard Layer 1 Parquet tables and run :meth:`discover`.

        The immutable snapshot remains untouched.  The function is intentionally
        small enough that an API or Excel consumer can call it after choosing a
        filing, while longitudinal comparison remains a Layer 2 responsibility.
        """
        try:
            import polars as pl
        except ImportError as exc:  # pragma: no cover - dependency contract.
            raise StatementDiscoveryError("polars is required to read a Layer 1 snapshot") from exc
        required = ("filing", "concept", "context", "fact", "dimension_fact", "role", "relationship")
        missing = [name for name in required if not (snapshot_dir / f"{name}.parquet").is_file()]
        if missing:
            raise StatementDiscoveryError(f"Layer 1 snapshot missing tables: {', '.join(missing)}")
        tables = {
            name: pl.read_parquet(snapshot_dir / f"{name}.parquet").to_dicts() for name in required
        }
        return self.discover(
            statement_type=statement_type,
            filing=tables["filing"],
            concepts=tables["concept"],
            contexts=tables["context"],
            facts=tables["fact"],
            dimension_facts=tables["dimension_fact"],
            roles=tables["role"],
            relationships=tables["relationship"],
        )


def _rows(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(deepcopy(dict(row)) for row in rows)


def _one_filing(*row_sets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    filing_ids = {
        str(row["filing_id"])
        for rows in row_sets
        for row in rows
        if row.get("filing_id") is not None
    }
    if len(filing_ids) != 1:
        raise StatementDiscoveryError("statement discovery requires exactly one filing")
    filing_rows = [dict(row) for row in row_sets[0]]
    if len(filing_rows) != 1:
        raise StatementDiscoveryError("statement discovery requires exactly one filing metadata row")
    return filing_rows[0]


def _statement_hierarchy(
    statement_type: str,
    role_ids: set[str],
    relationships: Iterable[Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    edges = [
        row
        for row in relationships
        if row.get("network_type") == "PRE" and str(row.get("role_id")) in role_ids
    ]
    children = {str(row["to_raw_concept_id"]) for row in edges}
    roots = sorted({str(row["from_raw_concept_id"]) for row in edges} - children)
    by_parent: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in edges:
        by_parent[str(edge["from_raw_concept_id"])].append(edge)
    for values in by_parent.values():
        values.sort(key=lambda row: (_rank(row.get("order")), str(row.get("relationship_id") or "")))
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def walk(parent: str, depth: int, role_id: str) -> None:
        for edge in by_parent.get(parent, ()):
            child = str(edge["to_raw_concept_id"])
            key = (str(edge.get("relationship_id") or ""), child)
            if key in seen:
                continue
            seen.add(key)
            row = {
                "statement_type": statement_type,
                "role_id": str(edge["role_id"]),
                "parent_raw_concept_id": parent,
                "child_raw_concept_id": child,
                "display_depth": depth,
                "display_order": edge.get("order"),
                "source_relationship_id": edge.get("relationship_id"),
                "evidence_type": "PRESENTATION_HIERARCHY",
            }
            row.update(_concept_fields("parent", concepts.get(parent)))
            row.update(_concept_fields("child", concepts.get(child)))
            result.append(row)
            walk(child, depth + 1, str(edge["role_id"]))

    for root in roots:
        walk(root, 1, "")
    # A malformed/cyclic presentation network may have no root. Preserve its
    # display arcs rather than silently losing them.
    for edge in edges:
        key = (str(edge.get("relationship_id") or ""), str(edge["to_raw_concept_id"]))
        if key not in seen:
            parent = str(edge["from_raw_concept_id"])
            walk(parent, 1, str(edge["role_id"]))
    return result


def _direct_dimensions(
    anchors: Iterable[Mapping[str, Any]],
    facts_by_id: Mapping[str, Mapping[str, Any]],
    dimensions: Iterable[Mapping[str, Any]],
    contexts: Mapping[str, Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    anchor_by_id = {str(row["raw_concept_id"]): row for row in anchors}
    result: list[dict[str, Any]] = []
    for dimension in dimensions:
        fact = facts_by_id.get(str(dimension.get("fact_id")))
        if not fact or str(fact.get("raw_concept_id")) not in anchor_by_id:
            continue
        if fact.get("reported_or_derived", "REPORTED") != "REPORTED" or fact.get("is_nil", False):
            continue
        concept_id = str(fact["raw_concept_id"])
        axis_id = _text(dimension.get("axis_raw_concept_id"))
        member_id = _text(dimension.get("member_raw_concept_id"))
        row = {
            "anchor_raw_concept_id": concept_id,
            "fact_id": str(fact["fact_id"]),
            "axis_raw_concept_id": axis_id,
            "member_raw_concept_id": member_id,
            "dimension_type": dimension.get("dimension_type"),
            "is_default_member": dimension.get("is_default_member"),
            "member_usage": "DIRECTLY_REPORTED",
            "value_numeric": fact.get("value_numeric"),
            "unit_id": fact.get("unit_id"),
            "context_id": fact.get("context_id"),
            "evidence_type": "DIRECT_DIMENSION",
        }
        row.update(_period_fields(contexts.get(str(fact.get("context_id")))))
        row.update(_concept_fields("anchor", concepts.get(concept_id)))
        row.update(_concept_fields("axis", concepts.get(axis_id)))
        row.update(_concept_fields("member", concepts.get(member_id)))
        result.append(row)
    return sorted(result, key=lambda row: (str(row["anchor_raw_concept_id"]), str(row.get("axis_raw_concept_id")), str(row.get("member_raw_concept_id")), str(row["fact_id"])))


def _structural_members(
    evidence: Iterable[Mapping[str, Any]],
    direct_dimensions: Iterable[Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    used = {
        (str(row["anchor_raw_concept_id"]), _text(row.get("axis_raw_concept_id")), _text(row.get("member_raw_concept_id")))
        for row in direct_dimensions
    }
    result: list[dict[str, Any]] = []
    for row in evidence:
        if (
            row.get("network_type") != "DEF"
            or not str(row.get("arcrole") or "").endswith("/domain-member")
            or row.get("evidence_type") not in {"DEFINITION_MEMBER", "STRUCTURAL_ONLY"}
        ):
            continue
        member_id = _text(row.get("to_raw_concept_id"))
        anchor_id = str(row["anchor_raw_concept_id"])
        # DEF leaves can be reached through a different role; retain a concrete
        # axis only where a direct Fact proves that exact pairing.
        matching_axes = sorted(axis for anchor, axis, member in used if anchor == anchor_id and member == member_id)
        axes = matching_axes or [None]
        for axis_id in axes:
            item = {
                "anchor_raw_concept_id": anchor_id,
                "axis_raw_concept_id": axis_id,
                "member_raw_concept_id": member_id,
                "member_status": "USED_BY_REPORTED_FACT" if matching_axes else "STRUCTURAL_ONLY",
                "role_id": row.get("role_id"),
                "source_relationship_id": row.get("source_relationship_id"),
                "target_role_uri": row.get("target_role_uri"),
                "evidence_type": row.get("evidence_type"),
            }
            item.update(_concept_fields("anchor", concepts.get(anchor_id)))
            item.update(_concept_fields("axis", concepts.get(axis_id)))
            item.update(_concept_fields("member", concepts.get(member_id)))
            result.append(item)
    return _unique_sorted(result, ("anchor_raw_concept_id", "axis_raw_concept_id", "member_raw_concept_id", "source_relationship_id"))


def _related_roles(
    anchors: Iterable[Mapping[str, Any]],
    evidence: Iterable[Mapping[str, Any]],
    roles: Iterable[Mapping[str, Any]],
    relationships: Iterable[Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
    statement_role_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    anchor_ids = {str(row["raw_concept_id"]) for row in anchors}
    # Only concepts reached by CAL/DEF traversal are eligible. PRE labels and
    # role definitions never enter this set.
    reached: dict[str, set[str]] = defaultdict(set)
    for row in evidence:
        if row.get("network_type") in {"CAL", "DEF"} and row.get("to_raw_concept_id"):
            reached[str(row["to_raw_concept_id"])].add(str(row["anchor_raw_concept_id"]))
    concepts_by_role: dict[str, set[str]] = defaultdict(set)
    relationship_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge in relationships:
        role_id = str(edge["role_id"])
        for concept_id in (str(edge["from_raw_concept_id"]), str(edge["to_raw_concept_id"])):
            concepts_by_role[role_id].add(concept_id)
            if edge.get("relationship_id") is not None:
                relationship_ids[(role_id, concept_id)].append(str(edge["relationship_id"]))
    role_by_id = {str(row["role_id"]): row for row in roles}
    filing_role_ids = _filing_scoped_role_ids(role_by_id, concepts)
    links: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []
    for role_id, concept_ids in sorted(concepts_by_role.items()):
        role = role_by_id.get(role_id, {})
        if role_id not in statement_role_ids and (
            str(role.get("role_category") or "") not in {"DISCLOSURE", "TABLE", "DETAIL", "POLICY"}
            or (filing_role_ids is not None and role_id not in filing_role_ids)
        ):
            continue
        matching = sorted(concept_ids & (anchor_ids | set(reached)))
        for concept_id in matching:
            relation_type = "SAME_ANCHOR_CONCEPT" if concept_id in anchor_ids else "TRAVERSED_CAL_OR_DEF_CONCEPT"
            for anchor_id in sorted(anchor_ids if concept_id in anchor_ids else reached[concept_id]):
                row = {
                    "anchor_raw_concept_id": anchor_id,
                    "role_id": role_id,
                    "linked_raw_concept_id": concept_id,
                    "role_expansion_reason": relation_type,
                    "source_relationship_ids": tuple(sorted(relationship_ids[(role_id, concept_id)])),
                    "evidence_type": "ROLE_EXPANSION",
                }
                row.update(_concept_fields("anchor", concepts.get(anchor_id)))
                row.update(_concept_fields("linked", concepts.get(concept_id)))
                row["role_uri"] = role.get("role_uri")
                row["role_definition"] = role.get("role_definition")
                row["role_category"] = role.get("role_category")
                links.append(row)
                related.append({key: row[key] for key in ("anchor_raw_concept_id", "role_id", "role_uri", "role_definition", "role_category", "role_expansion_reason", "linked_raw_concept_id")})
    compact: dict[tuple[str, str], dict[str, Any]] = {}
    for row in related:
        key = (str(row["anchor_raw_concept_id"]), str(row["role_id"]))
        current = compact.setdefault(
            key,
            {
                "anchor_raw_concept_id": row["anchor_raw_concept_id"],
                "role_id": row["role_id"],
                "role_uri": row["role_uri"],
                "role_definition": row["role_definition"],
                "role_category": row["role_category"],
                "role_expansion_reasons": set(),
                "linked_raw_concept_ids": set(),
            },
        )
        current["role_expansion_reasons"].add(row["role_expansion_reason"])
        current["linked_raw_concept_ids"].add(row["linked_raw_concept_id"])
    compact_rows = []
    for row in compact.values():
        row["role_expansion_reasons"] = tuple(sorted(row["role_expansion_reasons"]))
        row["linked_raw_concept_ids"] = tuple(sorted(row["linked_raw_concept_ids"]))
        compact_rows.append(row)
    return (
        _unique_sorted(links, ("anchor_raw_concept_id", "role_id", "linked_raw_concept_id", "role_expansion_reason")),
        _unique_sorted(compact_rows, ("anchor_raw_concept_id", "role_id")),
    )


def _filing_scoped_role_ids(
    roles: Mapping[str, Mapping[str, Any]], concepts: Mapping[str, Mapping[str, Any]]
) -> set[str] | None:
    """Return extension-issuer role IDs when such scope can be proven.

    Arelle can expose generic standard-taxonomy linkroles that are part of the
    DTS but not a company disclosure table.  Where the filing contains custom
    concepts, its custom namespace host provides a non-label, filing-specific
    boundary for company linkroles.  If no such evidence exists, the method
    returns ``None`` and preserves the contract's concept-evidence-only rule.
    """
    hosts = {
        urlparse(str(row.get("namespace_uri") or "")).netloc.casefold()
        for row in concepts.values()
        if row.get("is_custom") and urlparse(str(row.get("namespace_uri") or "")).netloc
    }
    if not hosts:
        return None
    result = {
        role_id
        for role_id, role in roles.items()
        if urlparse(str(role.get("role_uri") or "")).netloc.casefold() in hosts
    }
    return result or None


def _period_evidence(
    anchors: Iterable[Mapping[str, Any]],
    facts: Iterable[Mapping[str, Any]],
    contexts: Mapping[str, Mapping[str, Any]],
    concepts: Mapping[str, Mapping[str, Any]],
    dimensions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    dimensions_by_fact: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in dimensions:
        dimensions_by_fact[str(row["fact_id"])].append(row)
    anchor_ids = {str(row["raw_concept_id"]) for row in anchors}
    result: list[dict[str, Any]] = []
    for fact in facts:
        concept_id = str(fact.get("raw_concept_id"))
        if concept_id not in anchor_ids or fact.get("reported_or_derived", "REPORTED") != "REPORTED":
            continue
        if fact.get("is_nil", False):
            continue
        context = contexts.get(str(fact.get("context_id")))
        assignments = dimensions_by_fact.get(str(fact["fact_id"]), ()) or ({},)
        for assignment in assignments:
            row = {
                "anchor_raw_concept_id": concept_id,
                "fact_id": str(fact["fact_id"]),
                "dimension_key": (
                    _text(assignment.get("axis_raw_concept_id")),
                    _text(assignment.get("member_raw_concept_id")),
                ),
                "period_kind": context.get("period_kind") if context else None,
                "start_date": context.get("start_date") if context else None,
                "end_date": context.get("end_date") if context else None,
                "instant_date": context.get("instant_date") if context else None,
                "value_numeric": fact.get("value_numeric"),
                "unit_id": fact.get("unit_id"),
                "change_status": "OBSERVED_ONLY",
                "change_value": None,
                "change_reason": "SINGLE_FILING_NO_LONGITUDINAL_COMPARISON",
                "evidence_type": "REPORTED_PERIOD_OBSERVATION",
            }
            row.update(_concept_fields("anchor", concepts.get(concept_id)))
            result.append(row)
    return _unique_sorted(result, ("fact_id", "dimension_key"))


def _with_concept(row: Mapping[str, Any], concepts: Mapping[str, Mapping[str, Any]], key: str) -> dict[str, Any]:
    result = dict(row)
    result.update(_concept_fields("concept", concepts.get(str(row.get(key)))))
    return result


def _concept_fields(prefix: str, concept: Mapping[str, Any] | None) -> dict[str, Any]:
    fields = ("qname", "label", "taxonomy_family", "is_standard", "is_custom", "period_type", "abstract")
    if concept is None:
        return {f"{prefix}_{field}": None for field in fields} | {f"{prefix}_metadata_status": "MISSING_FROM_SNAPSHOT"}
    return {f"{prefix}_{field}": concept.get(field) for field in fields} | {f"{prefix}_metadata_status": "PRESENT"}


def _period_fields(context: Mapping[str, Any] | None) -> dict[str, Any]:
    fields = ("period_kind", "start_date", "end_date", "instant_date", "duration_days")
    return {field: context.get(field) if context else None for field in fields}


def _unique_sorted(rows: Iterable[Mapping[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        copied = dict(row)
        key = tuple(str(copied.get(name)) for name in keys)
        unique.setdefault(key, copied)
    return [unique[key] for key in sorted(unique)]


def _rank(value: Any) -> tuple[int, str]:
    try:
        return (0, f"{float(str(value)):020.8f}")
    except (TypeError, ValueError):
        return (1, str(value or ""))


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _qualifying_statement_role(role: Mapping[str, Any], statement_type: str) -> bool:
    """Avoid treating a note table as a primary statement from title keywords.

    M3 role classification is raw metadata and can classify a disclosure detail
    as ``STATEMENT``.  A primary-statement anchor therefore needs both a
    statement signal and the absence of a disclosure/table/detail signal.  This
    is placement filtering, not a label-based expansion rule.
    """
    title = str(role.get("role_definition") or "").casefold()
    category = str(role.get("role_category") or "").casefold()
    if any(token in title for token in ("disclosure", "[table]", "(table)", "details", "schedule")):
        return False
    if category not in {"statement", ""}:
        return False
    if "statement" not in title and category != "statement":
        return False
    if statement_type == "IS":
        return ("income" in title or "operations" in title or "earnings" in title) and "comprehensive" not in title
    if statement_type == "BS":
        return "balance sheet" in title or "financial position" in title
    if statement_type == "CF":
        return "cash flow" in title
    return "equity" in title or "stockholder" in title or "shareholder" in title
