"""Recursive, provenance-preserving exploration graph over T1 facts and T2 edges.

The graph is an analysis *navigation* aid.  It never chooses a filing version,
adds a subtotal, or treats an XBRL presentation/calculation arc as a business
driver.  Independent dimensional lenses remain parallel alternatives.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.materialization import (
    Layer2Publication,
    OperationalLayer2Publisher,
    VerifiedLayer2Publication,
)

EXPLORATION_GRAPH_RULE_VERSION = "analysis-t3-exploration-graph-v1"


class ExplorationGraphError(RuntimeError):
    """Raised when a graph would lose the verified T1/T2 provenance boundary."""


@dataclass(frozen=True, slots=True)
class ExplorationGraphResult:
    publication: Layer2Publication
    node_count: int
    edge_count: int


class ExplorationGraphPipeline:
    """Publish graph nodes/edges from reader-attested T1 and T2 publications."""

    def publish(
        self,
        observations: VerifiedLayer2Publication,
        relationships: VerifiedLayer2Publication,
        *,
        output_root: Path,
    ) -> ExplorationGraphResult:
        _check_upstreams(observations, relationships)
        observation_rows = observations.records("reported_period_observation")
        relationship_rows = relationships.records("filing_relationship_edge")
        maps = _mapping_index(observations)
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        def add_node(row: dict[str, Any]) -> str:
            node_id = row["analysis_exploration_node_id"]
            prior = nodes.get(node_id)
            if prior is not None:
                conflicts = {
                    key for key in set(prior) & set(row)
                    if prior[key] is not None and row[key] is not None and prior[key] != row[key]
                }
                if conflicts:
                    raise ExplorationGraphError("exploration node identity has conflicting provenance")
                row = {**prior, **{key: value for key, value in row.items() if value is not None}}
            nodes[node_id] = row
            return node_id

        def add_edge(row: dict[str, Any]) -> None:
            edge_id = row["analysis_exploration_edge_id"]
            prior = edges.get(edge_id)
            if prior is not None and prior != row:
                raise ExplorationGraphError("exploration edge identity has conflicting provenance")
            edges[edge_id] = row

        for observation in observation_rows:
            fact = dict(observation)
            concept_id = _concept_node_id(fact)
            add_node(_concept_node(fact))
            fact_id = add_node(_fact_node(fact))
            dimensions = tuple(fact.get("raw_dimension_signature") or ())
            if not dimensions:
                add_edge(_edge(
                    fact, "FACT_SCOPE", concept_id, fact_id,
                    scope_kind="TOTAL_FACT", source_network_type=None,
                ))
            for item in dimensions:
                axis_raw_id, member_raw_id, typed_member, dimension_type, is_default = tuple(item)
                axis = maps["axis"].get((str(fact["source_filing_id"]), str(axis_raw_id)))
                if axis is None:
                    raise ExplorationGraphError("observed dimension axis has no T1 mapping lineage")
                axis_id = add_node(_dimension_node(fact, axis, "AXIS"))
                add_edge(_edge(
                    fact, "DIMENSION_LENS", concept_id, axis_id,
                    scope_kind="CONCEPT_AXIS_LENS", source_network_type=None,
                    axis_raw_id=axis_raw_id,
                ))
                if member_raw_id:
                    member = maps["member"].get((str(fact["source_filing_id"]), str(member_raw_id)))
                    if member is None:
                        raise ExplorationGraphError("observed dimension member has no T1 mapping lineage")
                    member_id = add_node(_dimension_node(fact, member, "MEMBER"))
                    add_edge(_edge(
                        fact, "FACT_SCOPE", axis_id, member_id,
                        scope_kind="AXIS_MEMBER_SCOPE", source_network_type=None,
                        axis_raw_id=axis_raw_id, member_raw_id=member_raw_id,
                        dimension_type=dimension_type, typed_member=typed_member,
                        is_default_member=is_default,
                    ))
                    add_edge(_edge(
                        fact, "FACT_SCOPE", member_id, fact_id,
                        scope_kind="MEMBER_SCOPED_FACT", source_network_type=None,
                        axis_raw_id=axis_raw_id, member_raw_id=member_raw_id,
                        dimension_type=dimension_type, typed_member=typed_member,
                        is_default_member=is_default,
                    ))
                else:
                    add_edge(_edge(
                        fact, "FACT_SCOPE", axis_id, fact_id,
                        scope_kind="TYPED_AXIS_SCOPED_FACT", source_network_type=None,
                        axis_raw_id=axis_raw_id, dimension_type=dimension_type,
                        typed_member=typed_member, is_default_member=is_default,
                    ))

        # A total fact is the user-facing entry point.  Attach every observed
        # axis for its concept as a *parallel* lens.  We deliberately never
        # connect one axis to another: geography and product are alternatives,
        # not a synthetic hierarchy.
        by_concept: dict[tuple[str, str, int | None, int | None, str], list[dict[str, Any]]] = defaultdict(list)
        for observation in observation_rows:
            item = dict(observation)
            by_concept[(
                str(item["source_filing_id"]), str(item["raw_concept_id"]), item.get("fiscal_year"),
                item.get("fiscal_quarter"), str(item.get("period_class")),
            )].append(item)
        for facts in by_concept.values():
            totals = [row for row in facts if not tuple(row.get("raw_dimension_signature") or ())]
            dimensional = [row for row in facts if tuple(row.get("raw_dimension_signature") or ())]
            for total in totals:
                total_id = _fact_node(total)["analysis_exploration_node_id"]
                for scoped in dimensional:
                    for item in tuple(scoped.get("raw_dimension_signature") or ()):
                        axis_raw_id = next(iter(item))
                        axis = maps["axis"].get((str(scoped["source_filing_id"]), str(axis_raw_id)))
                        if axis is None:
                            continue
                        axis_id = _dimension_node(scoped, axis, "AXIS")["analysis_exploration_node_id"]
                        add_edge(_edge(
                            total, "DIMENSION_LENS", total_id, axis_id,
                            scope_kind="TOTAL_FACT_AXIS_LENS", source_network_type=None,
                            axis_raw_id=axis_raw_id,
                        ))

        for relationship in relationship_rows:
            row = dict(relationship)
            left = add_node(_relationship_concept_node(row, "from"))
            right = add_node(_relationship_concept_node(row, "to"))
            network = str(row["network_type"])
            if network in {"PRE", "CAL"}:
                add_edge(_relationship_edge(row, "STATEMENT_COMPONENT", left, right))
            else:
                add_edge(_relationship_edge(row, "MEMBER_HIERARCHY", left, right))

        datasets = {
            "analysis_exploration_node": tuple(nodes.values()),
            "analysis_exploration_edge": tuple(edges.values()),
        }
        publication = OperationalLayer2Publisher(Path(output_root)).publish(
            _exploration_run(observations), datasets
        )
        return ExplorationGraphResult(publication, len(nodes), len(edges))


class ExplorationGraphReader:
    """Read recursive paths without collapsing alternative axes into a tree."""

    node_dataset = "analysis_exploration_node"
    edge_dataset = "analysis_exploration_edge"

    def roots_for_fact(
        self,
        publication: VerifiedLayer2Publication,
        *,
        cik: str,
        fiscal_year: int,
        fiscal_quarter: int | None,
        raw_concept_qname: str,
        period_class: str = "QTD_3M",
    ) -> tuple[dict[str, Any], ...]:
        self._check(publication, cik)
        return tuple(sorted(
            (
                dict(row) for row in publication.records(self.node_dataset)
                if row.get("node_kind") == "FACT" and row.get("cik") == cik
                and row.get("raw_qname") == raw_concept_qname
                and row.get("fiscal_year") == fiscal_year
                and row.get("fiscal_quarter") == fiscal_quarter
                and row.get("period_class") == period_class
            ), key=lambda row: (str(row.get("filed_date")), str(row.get("accession")), str(row.get("source_fact_id")))
        ))

    def traverse(
        self,
        publication: VerifiedLayer2Publication,
        *,
        root_node_ids: Iterable[str],
        max_depth: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return every simple outbound path; cycle protection is per path.

        Per-path, rather than global, visitation intentionally keeps alternative
        routes to the same node visible (e.g. distinct statement roles).
        """
        self._check(publication, None)
        nodes = {str(row["analysis_exploration_node_id"]): dict(row) for row in publication.records(self.node_dataset)}
        outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in publication.records(self.edge_dataset):
            outgoing[str(edge["from_node_id"])].append(dict(edge))
        result: list[dict[str, Any]] = []
        queue: deque[tuple[str, tuple[str, ...], int, dict[str, Any] | None]] = deque()
        for root in root_node_ids:
            if root not in nodes:
                raise ExplorationGraphError("root node is outside the verified exploration graph")
            queue.append((root, (root,), 0, None))
        while queue:
            node_id, path, depth, incoming = queue.popleft()
            result.append({"depth": depth, "path_node_ids": path, "node": nodes[node_id], "incoming_edge": incoming})
            if max_depth is not None and depth >= max_depth:
                continue
            for edge in sorted(outgoing.get(node_id, ()), key=lambda item: str(item["analysis_exploration_edge_id"])):
                target = str(edge["to_node_id"])
                if target in path:  # semantic/cyclic DEF or presentation paths terminate safely.
                    continue
                queue.append((target, path + (target,), depth + 1, edge))
        return tuple(result)

    def _check(self, publication: VerifiedLayer2Publication, cik: str | None) -> None:
        if not publication.is_reader_attested:
            raise ExplorationGraphError("exploration graph must be loaded by Layer2PublicationReader")
        if self.node_dataset not in publication.datasets or self.edge_dataset not in publication.datasets:
            raise ExplorationGraphError("publication has no exploration graph datasets")
        if cik is not None and cik not in publication.input_ciks:
            raise ExplorationGraphError("requested CIK is outside the verified publication")


def _check_upstreams(observations: VerifiedLayer2Publication, relationships: VerifiedLayer2Publication) -> None:
    for publication, dataset in ((observations, "reported_period_observation"), (relationships, "filing_relationship_edge")):
        if not publication.is_reader_attested or dataset not in publication.datasets:
            raise ExplorationGraphError("T3 requires reader-attested T1 and T2 publications")
    if observations.identity["layer2_run_fingerprint"] != relationships.identity["layer2_run_fingerprint"]:
        raise ExplorationGraphError("T1 and T2 must have the identical declared Layer1 input run")


def _exploration_run(publication: VerifiedLayer2Publication):
    """Reconstruct the verified input declaration; graph remains filing-scoped."""
    from sec_xbrl.longitudinal.materialization import _read_publication_manifest, _run_from_manifest
    return _run_from_manifest(_read_publication_manifest(publication.manifest_path))


def _mapping_index(publication: VerifiedLayer2Publication) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    result: dict[str, dict[tuple[str, str], dict[str, Any]]] = {"axis": {}, "member": {}}
    for kind, dataset in (("axis", "company_axis_map"), ("member", "company_member_map")):
        if dataset not in publication.datasets:
            raise ExplorationGraphError("T1 publication lacks dimension mapping lineage")
        result[kind] = {
            (str(row.get("source_filing_id")), str(row.get("source_raw_id"))): dict(row)
            for row in publication.records(dataset)
        }
    return result


def _concept_node_id(row: Mapping[str, Any]) -> str:
    return _id("concept", row.get("cik"), row.get("source_filing_id"), row.get("raw_concept_id"))


def _concept_node(row: Mapping[str, Any]) -> dict[str, Any]:
    return _node(
        row, "CONCEPT", _concept_origin(row), str(row["raw_concept_id"]), str(row["raw_concept_qname"]),
        taxonomy_family=row.get("raw_concept_taxonomy_family"), taxonomy_version=row.get("raw_concept_taxonomy_version"),
        namespace_uri=row.get("raw_concept_namespace_uri"), local_name=row.get("raw_concept_local_name"),
        source_filing_id=row.get("source_filing_id"), accession=row.get("accession"), filed_date=row.get("filed_date"),
    )


def _fact_node(row: Mapping[str, Any]) -> dict[str, Any]:
    return _node(
        row, "FACT", _concept_origin(row), str(row["source_fact_id"]), str(row["raw_concept_qname"]),
        taxonomy_family=row.get("raw_concept_taxonomy_family"), taxonomy_version=row.get("raw_concept_taxonomy_version"),
        namespace_uri=row.get("raw_concept_namespace_uri"), local_name=row.get("raw_concept_local_name"),
        source_fact_id=row.get("source_fact_id"), source_filing_id=row.get("source_filing_id"),
        source_snapshot_id=row.get("source_snapshot_id"), accession=row.get("accession"), form=row.get("form"),
        filed_date=row.get("filed_date"), report_date=row.get("report_date"), context_id=row.get("context_id"),
        unit_id=row.get("unit_id"), value_numeric=row.get("value_numeric"), value_text=row.get("value_text"),
        raw_dimension_signature=_lineage_json(row.get("raw_dimension_signature")),
        canonical_dimension_signature=_lineage_json(row.get("canonical_dimension_signature")),
        dimension_mapping_ids=_lineage_json(row.get("dimension_mapping_ids")),
        mapping_review_required=row.get("mapping_review_required"),
        concept_mapping_id=row.get("concept_mapping_id"), concept_mapping_version=row.get("concept_mapping_version"),
        company_canonical_concept_id=row.get("company_canonical_concept_id"), fiscal_year=row.get("fiscal_year"),
        fiscal_quarter=row.get("fiscal_quarter"), period_class=row.get("period_class"), period_key=row.get("period_key"),
    )


def _dimension_node(source: Mapping[str, Any], mapping: Mapping[str, Any], kind: str) -> dict[str, Any]:
    origin = ("STANDARD_" if mapping.get("source_is_standard") else "CUSTOM_") + kind
    raw_id = str(mapping["source_raw_id"])
    row = _node(
        source, kind, origin, raw_id, str(mapping.get("source_qname") or raw_id),
        taxonomy_family=mapping.get("source_taxonomy_family"), namespace_uri=mapping.get("source_namespace_uri"),
        local_name=mapping.get("source_local_name"), source_filing_id=mapping.get("source_filing_id"),
        accession=source.get("accession"), filed_date=source.get("filed_date"),
        mapping_id=mapping.get("mapping_id"), mapping_version=mapping.get("mapping_version"),
        company_canonical_id=mapping.get("company_canonical_id"), mapping_evidence=json.dumps(mapping.get("evidence"), sort_keys=True, separators=(",", ":")),
        mapping_review_required=mapping.get("review_required"),
    )
    # The raw Axis/Member identity stays intact, but its navigation node is
    # scoped to the fact concept.  Otherwise a shared Axis would incorrectly
    # make revenue drill into every unrelated concept using that same Axis.
    row["scope_concept_raw_id"] = source.get("raw_concept_id")
    row["analysis_exploration_node_id"] = _id(
        "node", source.get("cik"), row.get("source_filing_id"), kind, raw_id,
        source.get("raw_concept_id"),
    )
    return row


def _relationship_concept_node(row: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    standard = bool(row.get(f"{prefix}_is_standard"))
    return _node(
        row, "CONCEPT", "STANDARD_CONCEPT" if standard else "CUSTOM_CONCEPT",
        str(row[f"{prefix}_raw_concept_id"]), str(row[f"{prefix}_raw_concept_qname"]),
        taxonomy_family=row.get(f"{prefix}_taxonomy_family"), taxonomy_version=row.get(f"{prefix}_taxonomy_version"),
        namespace_uri=row.get(f"{prefix}_namespace_uri"), local_name=row.get(f"{prefix}_local_name"),
        source_filing_id=row.get("source_filing_id"), source_snapshot_id=row.get("source_snapshot_id"),
        accession=row.get("accession"), form=row.get("form"), filed_date=row.get("filed_date"),
        mapping_id=row.get(f"{prefix}_mapping_id"), mapping_version=row.get(f"{prefix}_mapping_version"),
        company_canonical_id=row.get(f"{prefix}_company_canonical_concept_id"),
        mapping_evidence=row.get(f"{prefix}_mapping_evidence"), mapping_review_required=row.get(f"{prefix}_mapping_review_required"),
    )


def _node(source: Mapping[str, Any], kind: str, origin: str, raw_id: str, raw_qname: str, **values: Any) -> dict[str, Any]:
    source_filing_id = values.get("source_filing_id") or source.get("source_filing_id")
    row = {
        "cik": source.get("cik"), "analysis_exploration_node_id": _id("node", source.get("cik"), source_filing_id, kind, raw_id),
        "node_kind": kind, "origin": origin, "raw_id": raw_id, "raw_qname": raw_qname,
        "exploration_graph_rule_version": EXPLORATION_GRAPH_RULE_VERSION,
        **values,
    }
    return {key: value for key, value in row.items() if value is not None}


def _edge(source: Mapping[str, Any], kind: str, left: str, right: str, *, scope_kind: str, source_network_type: str | None, **values: Any) -> dict[str, Any]:
    return {
        "cik": source.get("cik"), "analysis_exploration_edge_id": _id(
            "edge", kind, left, right, scope_kind, source.get("source_fact_id"), values
        ),
        "edge_kind": kind, "from_node_id": left, "to_node_id": right, "scope_kind": scope_kind,
        "source_network_type": source_network_type, "source_fact_id": source.get("source_fact_id"),
        "source_filing_id": source.get("source_filing_id"), "source_snapshot_id": source.get("source_snapshot_id"),
        "accession": source.get("accession"), "form": source.get("form"), "filed_date": source.get("filed_date"),
        "role_id": None, "role_uri": None, "target_role_uri": None,
        "exploration_graph_rule_version": EXPLORATION_GRAPH_RULE_VERSION, **values,
    }


def _relationship_edge(row: Mapping[str, Any], kind: str, left: str, right: str) -> dict[str, Any]:
    return {
        "cik": row.get("cik"), "analysis_exploration_edge_id": _id("relationship", row.get("filing_relationship_edge_id"), kind),
        "edge_kind": kind, "from_node_id": left, "to_node_id": right,
        "source_network_type": row.get("network_type"), "source_relationship_edge_id": row.get("filing_relationship_edge_id"),
        "relationship_id": row.get("relationship_id"), "source_filing_id": row.get("source_filing_id"),
        "source_snapshot_id": row.get("source_snapshot_id"), "accession": row.get("accession"), "form": row.get("form"),
        "filed_date": row.get("filed_date"), "role_id": row.get("role_id"), "role_uri": row.get("role_uri"),
        "role_definition": row.get("role_definition"), "target_role_uri": row.get("target_role_uri"),
        "arcrole": row.get("arcrole"), "link_qname": row.get("link_qname"), "arc_qname": row.get("arc_qname"),
        "order": row.get("order"), "weight": row.get("weight"), "preferred_label": row.get("preferred_label"),
        "usable": row.get("usable"), "closed": row.get("closed"), "context_element": row.get("context_element"),
        "exploration_graph_rule_version": EXPLORATION_GRAPH_RULE_VERSION,
    }


def _concept_origin(row: Mapping[str, Any]) -> str:
    return "STANDARD_CONCEPT" if bool(row.get("raw_concept_is_standard")) else "CUSTOM_CONCEPT"


def _id(*values: Any) -> str:
    payload = "|".join(repr(value) for value in values)
    return "exploration:" + hashlib.sha256(payload.encode()).hexdigest()[:24]


def _lineage_json(value: Any) -> str:
    """Parquet scalar representation that retains heterogeneous XBRL typed values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
