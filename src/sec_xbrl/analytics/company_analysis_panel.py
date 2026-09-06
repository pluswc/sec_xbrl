"""Company analysis panel from selected observations and exploration evidence.

This is a serving model, not a selector or calculator.  T4-B decides which
directly reported fact is eligible; T3 supplies the filing-scoped navigation
evidence.  The panel merely makes those two governed inputs displayable while
retaining their complete provenance.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sec_xbrl.longitudinal.exploration_graph import ExplorationGraphReader
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication

COMPANY_ANALYSIS_PANEL_VERSION = "analysis-t5-company-panel-v1"
_LINE_CLASSES = frozenset({"COMMON_GAAP", "COMPANY_CUSTOM"})


class CompanyAnalysisPanelError(ValueError):
    """Raised when a panel would hide selection or graph provenance."""


@dataclass(frozen=True, slots=True)
class CompanyAnalysisPanelResult:
    """Separate durable row definition, source binding, and displayed value."""

    definitions: tuple[dict[str, Any], ...]
    bindings: tuple[dict[str, Any], ...]
    values: tuple[dict[str, Any], ...]
    scope: dict[str, Any]


class CompanyAnalysisPanelBuilder:
    """Build one filing-aware panel without selecting, deriving, or recasting."""

    def build(
        self,
        *,
        selected_rows: Iterable[Mapping[str, Any]],
        exploration: VerifiedLayer2Publication,
        cik: str,
        fiscal_year: int,
        fiscal_quarter: int | None,
        period_class: str,
        view: str,
        as_of_date: str,
        analysis_view_id: str = "company-analysis",
        analysis_view_version: str = COMPANY_ANALYSIS_PANEL_VERSION,
    ) -> CompanyAnalysisPanelResult:
        """Return a panel for one exact T4-B query scope.

        ``selected_rows`` must be the output of a T4-B direct selection.  A
        selected Fact is admitted only when it resolves to the attested T3
        graph.  An unavailable T4-B result is deliberately emitted as an
        unavailable panel value rather than silently dropped.
        """
        _validate_query(cik, fiscal_year, fiscal_quarter, period_class, view, as_of_date)
        _validate_graph(exploration, cik)
        selected = [dict(row) for row in selected_rows]
        _validate_selection_scope(
            selected, cik, fiscal_year, fiscal_quarter, period_class, view, as_of_date
        )
        nodes = {
            str(row["analysis_exploration_node_id"]): dict(row)
            for row in exploration.records(ExplorationGraphReader.node_dataset)
        }
        facts = {
            (str(row.get("source_filing_id")), str(row.get("source_fact_id"))): row
            for row in nodes.values()
            if row.get("node_kind") == "FACT"
        }
        definitions: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        values: list[dict[str, Any]] = []
        selected_by_fact = {
            (str(row.get("source_filing_id")), str(row.get("selected_source_fact_id"))): row
            for row in selected
            if row["selection_status"] == "SELECTED"
        }
        for selection in _root_selections(selected):
            if selection["selection_status"] == "UNAVAILABLE":
                definition, binding, value = _unavailable_line(
                    selection, analysis_view_id, analysis_view_version
                )
                definitions.append(definition)
                bindings.append(binding)
                values.append(value)
                continue
            fact_key = (
                str(selection.get("source_filing_id")),
                str(selection.get("selected_source_fact_id")),
            )
            root = facts.get(fact_key)
            if root is None:
                raise CompanyAnalysisPanelError(
                    "selected direct fact is not present in the attested exploration graph"
                )
            _require_graph_fact_match(selection, root)
            root_id = str(root["analysis_exploration_node_id"])
            paths = ExplorationGraphReader().traverse(exploration, root_node_ids=(root_id,))
            for path in paths:
                node = path["node"]
                if node.get("node_kind") != "FACT":
                    continue
                path_fact_key = (str(node.get("source_filing_id")), str(node.get("source_fact_id")))
                # T3 graph contains all as-filed facts.  Values enter this
                # panel only if their exact direct observation was selected by
                # T4-B for the requested view/as-of scope.
                source = selected_by_fact.get(path_fact_key)
                if source is None:
                    continue
                _require_graph_fact_match(source, node)
                definition, binding, value = _reported_line(
                    source, selection, path, nodes, analysis_view_id, analysis_view_version
                )
                definitions.append(definition)
                bindings.append(binding)
                values.append(value)
        _reject_duplicates(definitions, bindings, values)
        ordered_definitions = tuple(sorted(definitions, key=_definition_order))
        definition_order = {
            row["analysis_line_id"]: index for index, row in enumerate(ordered_definitions)
        }
        return CompanyAnalysisPanelResult(
            definitions=ordered_definitions,
            bindings=tuple(
                sorted(
                    bindings,
                    key=lambda row: (
                        definition_order[row["analysis_line_id"]],
                        row["analysis_binding_id"],
                    ),
                )
            ),
            values=tuple(
                sorted(
                    values,
                    key=lambda row: (
                        definition_order[row["analysis_line_id"]],
                        row["analysis_line_value_id"],
                    ),
                )
            ),
            scope={
                "cik": cik,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "period_class": period_class,
                "selection_view": view,
                "selection_as_of_date": as_of_date,
            },
        )


class CompanyAnalysisPanelQuery:
    """Read-only display adapter; it intentionally has no metric calculations."""

    def __init__(self, panel: CompanyAnalysisPanelResult) -> None:
        self._definitions = tuple(deepcopy(row) for row in panel.definitions)
        self._bindings = tuple(deepcopy(row) for row in panel.bindings)
        self._values = tuple(deepcopy(row) for row in panel.values)

    def rows(self, *, line_class: str | None = None) -> tuple[dict[str, Any], ...]:
        if line_class is not None and line_class not in _LINE_CLASSES:
            raise CompanyAnalysisPanelError("unknown panel line class")
        by_line = {row["analysis_line_id"]: row for row in self._definitions}
        values = {row["analysis_line_id"]: row for row in self._values}
        result = []
        for definition in self._definitions:
            if line_class is not None and definition["line_class"] != line_class:
                continue
            result.append(
                {
                    "definition": deepcopy(definition),
                    "binding": deepcopy(
                        next(
                            row
                            for row in self._bindings
                            if row["analysis_line_id"] == definition["analysis_line_id"]
                        )
                    ),
                    "value": deepcopy(values[definition["analysis_line_id"]]),
                    "parent_definition": deepcopy(
                        by_line.get(definition.get("parent_analysis_line_id"))
                    )
                    if definition.get("parent_analysis_line_id")
                    else None,
                }
            )
        return tuple(result)


def _validate_query(
    cik: str,
    fiscal_year: int,
    fiscal_quarter: int | None,
    period_class: str,
    view: str,
    as_of_date: str,
) -> None:
    if not cik or fiscal_year < 1 or not period_class or not view or not as_of_date:
        raise CompanyAnalysisPanelError(
            "panel requires a complete company, period, view, and as-of scope"
        )
    if fiscal_quarter is not None and fiscal_quarter not in {1, 2, 3, 4}:
        raise CompanyAnalysisPanelError("fiscal_quarter must be 1 through 4 when supplied")


def _validate_graph(exploration: VerifiedLayer2Publication, cik: str) -> None:
    ExplorationGraphReader()._check(exploration, cik)


def _validate_selection_scope(
    rows: list[dict[str, Any]],
    cik: str,
    fiscal_year: int,
    fiscal_quarter: int | None,
    period_class: str,
    view: str,
    as_of_date: str,
) -> None:
    for row in rows:
        required = (
            "selection_status",
            "selection_view",
            "selection_as_of_date",
            "selection_rule_version",
            "source_type",
        )
        missing = [field for field in required if row.get(field) in (None, "")]
        if missing:
            raise CompanyAnalysisPanelError("T4-B selection row missing: " + ", ".join(missing))
        if (
            str(row.get("cik")),
            row.get("fiscal_year"),
            row.get("fiscal_quarter"),
            row.get("period_class"),
        ) != (cik, fiscal_year, fiscal_quarter, period_class):
            raise CompanyAnalysisPanelError(
                "T4-B selection row is outside the requested company/period scope"
            )
        if row["selection_view"] != view or row["selection_as_of_date"] != as_of_date:
            raise CompanyAnalysisPanelError(
                "T4-B selection row is outside the requested view/as-of scope"
            )
        if row["selection_status"] not in {"SELECTED", "UNAVAILABLE"}:
            raise CompanyAnalysisPanelError("unsupported T4-B selection status")
        if row["selection_status"] == "SELECTED":
            _require(
                row,
                (
                    "selected_source_fact_id",
                    "source_filing_id",
                    "accession",
                    "context_id",
                    "raw_concept_id",
                    "raw_concept_qname",
                    "source_snapshot_id",
                ),
                "selected direct observation",
            )
            if row["source_type"] != "REPORTED":
                raise CompanyAnalysisPanelError("T5 accepts directly reported selection rows only")
        elif row.get("source_type") != "UNAVAILABLE":
            raise CompanyAnalysisPanelError(
                "unavailable selection must have source_type UNAVAILABLE"
            )


def _root_selections(selected: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Choose total facts as graph roots, falling back only when no total exists.

    A dimensioned value may have several parallel lenses.  Starting every
    dimensioned value independently would flatten that evidence and duplicate
    it as a false statement row.  Its total fact is the natural graph entry
    point; an orphaned dimensioned fact is retained as its own root.
    """
    unavailable = [row for row in selected if row["selection_status"] == "UNAVAILABLE"]
    reported = [row for row in selected if row["selection_status"] == "SELECTED"]
    totals = [row for row in reported if not tuple(row.get("raw_dimension_signature") or ())]
    total_concepts = {(row.get("source_filing_id"), row.get("raw_concept_id")) for row in totals}
    orphans = [
        row
        for row in reported
        if (row.get("source_filing_id"), row.get("raw_concept_id")) not in total_concepts
    ]
    return tuple(unavailable + totals + orphans)


def _require_graph_fact_match(selection: Mapping[str, Any], graph_fact: Mapping[str, Any]) -> None:
    """Reject a same-ID join that carries different immutable fact lineage."""
    fields = (
        ("cik", "cik"),
        ("source_filing_id", "source_filing_id"),
        ("selected_source_fact_id", "source_fact_id"),
        ("source_snapshot_id", "source_snapshot_id"),
        ("accession", "accession"),
        ("context_id", "context_id"),
        ("unit_id", "unit_id"),
    )
    mismatches = [
        selection_name
        for selection_name, graph_name in fields
        if str(selection.get(selection_name) or "") != str(graph_fact.get(graph_name) or "")
    ]
    if mismatches:
        raise CompanyAnalysisPanelError(
            "selected observation and exploration FACT lineage disagree: " + ", ".join(mismatches)
        )


def _reported_line(
    source: Mapping[str, Any],
    root_source: Mapping[str, Any],
    path: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    view_id: str,
    view_version: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path_ids = tuple(path["path_node_ids"])
    nav = tuple(deepcopy(edge) for edge in path["path_edges"])
    path_edge_ids = tuple(edge["analysis_exploration_edge_id"] for edge in nav)
    source_fact_id = str(source["selected_source_fact_id"])
    line_id = _id(
        "line",
        view_id,
        view_version,
        source.get("source_filing_id"),
        source_fact_id,
        path_ids,
        path_edge_ids,
    )
    parent_id = _parent_line_id(view_id, view_version, root_source, path_ids)
    detail_member = _last_member(path_ids, nodes)
    line_class, origin = _classify(source, path_ids, nodes)
    scope = "STATEMENT" if len(path_ids) == 1 else "EXPLORATION_DETAIL"
    label = (
        str(detail_member.get("raw_qname"))
        if detail_member is not None
        else str(source["raw_concept_qname"])
    )
    definition = {
        "analysis_line_id": line_id,
        "analysis_view_id": view_id,
        "analysis_view_version": view_version,
        "company_cik": source["cik"],
        "label": label,
        "line_class": line_class,
        "line_kind": "REPORTED",
        "line_scope": scope,
        "parent_analysis_line_id": parent_id,
        "navigation_path_node_ids": path_ids,
        "relationship_navigation": nav,
        "display_order_key": _path_order(path_ids, nav),
        "company_analysis_panel_version": COMPANY_ANALYSIS_PANEL_VERSION,
    }
    binding = {
        "analysis_binding_id": _id("binding", line_id, source_fact_id),
        "analysis_line_id": line_id,
        "binding_kind": "SELECTED_DIRECT_REPORTED_FACT",
        "concept_origin": origin,
        "raw_concept_id": source["raw_concept_id"],
        "raw_concept_qname": source["raw_concept_qname"],
        "raw_concept_taxonomy_family": source.get("raw_concept_taxonomy_family"),
        "raw_concept_taxonomy_version": source.get("raw_concept_taxonomy_version"),
        "raw_concept_namespace_uri": source.get("raw_concept_namespace_uri"),
        "raw_concept_data_type": source.get("raw_concept_data_type"),
        "raw_concept_period_type": source.get("raw_concept_period_type"),
        "raw_concept_is_standard": source.get("raw_concept_is_standard"),
        "raw_dimension_signature": deepcopy(source.get("raw_dimension_signature")),
        "navigation_path_node_ids": path_ids,
        "relationship_navigation": deepcopy(nav),
        "source_fact_id": source_fact_id,
        "source_filing_id": source["source_filing_id"],
    }
    value = {
        "analysis_line_value_id": _id("value", line_id, source_fact_id),
        "analysis_line_id": line_id,
        "value_status": "REPORTED",
        "value_numeric": source.get("value_numeric"),
        "value_text": source.get("value_text"),
        "source_type": source["source_type"],
        "selected_source_fact_id": source_fact_id,
        "source_filing_id": source["source_filing_id"],
        "accession": source["accession"],
        "filed_date": source.get("filed_date"),
        "report_date": source.get("report_date"),
        "source_snapshot_id": source["source_snapshot_id"],
        "context_id": source["context_id"],
        "unit_id": source.get("unit_id"),
        "unit_numerator_measures": deepcopy(source.get("unit_numerator_measures")),
        "unit_denominator_measures": deepcopy(source.get("unit_denominator_measures")),
        "context_start_date": source.get("context_start_date"),
        "context_end_date": source.get("context_end_date"),
        "context_instant_date": source.get("context_instant_date"),
        # A filing can carry current and prior comparative contexts under one
        # filing fiscal label.  Downstream fiscal time-series layout must be
        # able to keep those observation families apart without guessing from
        # date strings.
        "period_class": source.get("period_class"),
        "comparative_type": source.get("comparative_type"),
        "raw_concept_id": source["raw_concept_id"],
        "raw_concept_qname": source["raw_concept_qname"],
        "raw_concept_taxonomy_family": source.get("raw_concept_taxonomy_family"),
        "raw_concept_taxonomy_version": source.get("raw_concept_taxonomy_version"),
        "raw_concept_namespace_uri": source.get("raw_concept_namespace_uri"),
        "raw_concept_data_type": source.get("raw_concept_data_type"),
        "raw_concept_period_type": source.get("raw_concept_period_type"),
        "raw_concept_is_standard": source.get("raw_concept_is_standard"),
        "raw_dimension_signature": deepcopy(source.get("raw_dimension_signature")),
        "canonical_dimension_signature": deepcopy(source.get("canonical_dimension_signature")),
        "dimension_mapping_ids": deepcopy(source.get("dimension_mapping_ids")),
        "concept_mapping_id": source.get("concept_mapping_id"),
        "concept_mapping_version": source.get("concept_mapping_version"),
        "company_canonical_concept_id": source.get("company_canonical_concept_id"),
        "mapping_review_required": source.get("mapping_review_required"),
        "selection_view": source["selection_view"],
        "selection_as_of_date": source["selection_as_of_date"],
        "selection_rule_version": source["selection_rule_version"],
        "selection_reason": source.get("selection_reason"),
        "comparability_status": source.get("comparability_status"),
        "accession_version_ledger_id": source.get("accession_version_ledger_id"),
        "ledger_lineage": {
            key: deepcopy(value) for key, value in source.items() if key.startswith("ledger_")
        },
    }
    return definition, binding, value


def _unavailable_line(
    source: Mapping[str, Any], view_id: str, view_version: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    identity = repr(source.get("selection_identity"))
    line_id = _id("unavailable", view_id, view_version, identity)
    definition = {
        "analysis_line_id": line_id,
        "analysis_view_id": view_id,
        "analysis_view_version": view_version,
        "company_cik": source.get("cik"),
        "label": str(source.get("raw_concept_qname") or "Unavailable selected observation"),
        "line_class": "COMMON_GAAP" if source.get("raw_concept_is_standard") else "COMPANY_CUSTOM",
        "line_kind": "REPORTED",
        "line_scope": "UNAVAILABLE",
        "parent_analysis_line_id": None,
        "navigation_path_node_ids": (),
        "relationship_navigation": (),
        "display_order_key": ("~", line_id),
        "company_analysis_panel_version": COMPANY_ANALYSIS_PANEL_VERSION,
    }
    binding = {
        "analysis_binding_id": _id("unavailable-binding", line_id),
        "analysis_line_id": line_id,
        "binding_kind": "UNAVAILABLE_SELECTION",
        "concept_origin": None,
        "selection_identity": deepcopy(source.get("selection_identity")),
    }
    value = {
        "analysis_line_value_id": _id("unavailable-value", line_id),
        "analysis_line_id": line_id,
        "value_status": "UNAVAILABLE",
        "source_type": "UNAVAILABLE",
        "value_numeric": None,
        "value_text": None,
        "selected_source_fact_id": None,
        "selection_view": source["selection_view"],
        "selection_as_of_date": source["selection_as_of_date"],
        "selection_rule_version": source["selection_rule_version"],
        "selection_reason": source.get("selection_reason"),
        "selection_unavailable_reason": source.get("selection_unavailable_reason"),
        "comparability_status": source.get("comparability_status"),
        "accession_version_ledger_id": source.get("accession_version_ledger_id"),
    }
    return definition, binding, value


def _classify(
    source: Mapping[str, Any], path_ids: tuple[str, ...], nodes: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str]:
    standard = bool(source.get("raw_concept_is_standard"))
    custom_dimension = any(
        nodes[node_id].get("node_kind") in {"AXIS", "MEMBER"}
        and str(nodes[node_id].get("origin", "")).startswith("CUSTOM_")
        for node_id in path_ids
    )
    if not standard:
        return "COMPANY_CUSTOM", "CUSTOM_CONCEPT"
    if custom_dimension:
        return "COMPANY_CUSTOM", "STANDARD_CONCEPT_WITH_CUSTOM_DIMENSION"
    return "COMMON_GAAP", "STANDARD_CONCEPT"


def _last_member(
    path_ids: tuple[str, ...], nodes: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    for node_id in reversed(path_ids[:-1]):
        node = nodes[node_id]
        if node.get("node_kind") == "MEMBER":
            return node
    return None


def _parent_line_id(
    view_id: str, view_version: str, root_source: Mapping[str, Any], path_ids: tuple[str, ...]
) -> str | None:
    if len(path_ids) == 1:
        return None
    root_path = (path_ids[0],)
    # Detail values attach to their statement root, not to another independent
    # dimensional lens.  The complete edge path remains on the binding/value.
    return _id(
        "line",
        view_id,
        view_version,
        root_source.get("source_filing_id"),
        root_source.get("selected_source_fact_id"),
        root_path,
        (),
    )


def _path_order(
    path_ids: tuple[str, ...], navigation: tuple[Mapping[str, Any], ...]
) -> tuple[Any, ...]:
    return tuple(
        (
            edge.get("order") is None,
            str(edge.get("order") or ""),
            edge.get("analysis_exploration_edge_id"),
        )
        for edge in navigation
    ) + (path_ids,)


def _definition_order(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("line_scope")) != "STATEMENT",
        row.get("display_order_key"),
        row["analysis_line_id"],
    )


def _reject_duplicates(
    definitions: list[dict[str, Any]], bindings: list[dict[str, Any]], values: list[dict[str, Any]]
) -> None:
    for name, rows, key in (
        ("definition", definitions, "analysis_line_id"),
        ("binding", bindings, "analysis_binding_id"),
        ("value", values, "analysis_line_value_id"),
    ):
        identities = [row[key] for row in rows]
        if len(identities) != len(set(identities)):
            raise CompanyAnalysisPanelError(f"duplicate panel {name} identity")


def _require(row: Mapping[str, Any], names: tuple[str, ...], label: str) -> None:
    missing = [name for name in names if row.get(name) in (None, "")]
    if missing:
        raise CompanyAnalysisPanelError(f"{label} missing: {', '.join(missing)}")


def _id(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(repr(part) for part in parts).encode()).hexdigest()[:24]
    return f"company-analysis:{digest}"
