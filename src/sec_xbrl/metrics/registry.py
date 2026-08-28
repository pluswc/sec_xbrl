"""Derived Metrics M0 definition registry and L2-M6 handoff guard.

Definitions are declarative contracts.  They intentionally cannot execute a
formula, infer inputs from raw XBRL names, or publish calculated values.  A
later materializer must use this registry together with L2-M6's governed
candidate and compatibility records.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

METRIC_REGISTRY_CONTRACT_VERSION = "derived-metrics-m0-registry-v1"
_PROHIBITED_HANDOFF_FIELDS = frozenset(
    {
        "value",
        "metric_value",
        "calculated_value",
        "formula_result",
        "derived_metric_id",
        "formula",
        "formula_id",
        "formula_version",
    }
)
_CANDIDATE_REQUIRED = (
    "metric_input_candidate_id",
    "cik",
    "metric_input_role",
    "analytical_fact_id",
    "source_filing_id",
    "view",
    "as_of_date",
    "basis_version",
    "series_type",
    "period_class",
    "period_key",
    "company_canonical_dimension_key",
    "unit_semantics",
    "mapping_version",
    "source_type",
    "candidate_status",
    "metric_input_handoff_version",
)
_COMPATIBILITY_REQUIRED = (
    "metric_input_compatibility_id",
    "cik",
    "metric_definition_id",
    "view",
    "as_of_date",
    "series_type",
    "period_class",
    "period_key",
    "basis_version",
    "company_canonical_dimension_key",
    "unit_semantics",
    "mapping_versions",
    "compatibility_status",
    "required_input_roles",
    "input_metric_input_candidate_ids",
    "input_analytical_fact_ids",
    "input_selected_fact_ids",
    "metric_input_handoff_version",
)


class MetricDefinitionError(ValueError):
    """A definition or handoff record crosses the Metrics-plane boundary."""


class MetricCategory(StrEnum):
    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    DERIVED = "DERIVED"


class DefinitionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class MetricInputRole(StrEnum):
    REVENUE = "REVENUE"
    GROSS_PROFIT = "GROSS_PROFIT"
    OPERATING_INCOME = "OPERATING_INCOME"
    CURRENT_REVENUE = "CURRENT_REVENUE"
    PRIOR_REVENUE = "PRIOR_REVENUE"
    CONTROLLED_Q4_FLOW = "CONTROLLED_Q4_FLOW"
    EPS = "EPS"
    WEIGHTED_AVERAGE_SHARES = "WEIGHTED_AVERAGE_SHARES"


@dataclass(frozen=True, slots=True)
class FormulaMetadata:
    """Declarative formula identity; ``expression`` is documentation, not code."""

    formula_id: str
    formula_version: str
    expression: str
    sign_convention: str
    scaling_convention: str


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Versioned, auditable definition of one governed metric contract."""

    metric_id: str
    version: str
    status: DefinitionStatus
    category: MetricCategory
    input_roles: tuple[MetricInputRole, ...]
    period_policy: str
    basis_policy: str
    dimension_policy: str
    output_unit_semantics: str
    output_semantics: str
    formula: FormulaMetadata | None
    direct_observation_required: bool
    dependency_metric_ids: tuple[str, ...]
    definition_source: str
    reviewed_by: str
    reviewed_at: str
    change_note: str

    @property
    def definition_id(self) -> str:
        return f"{self.metric_id}@{self.version}"


class MetricRegistry:
    """Immutable-style registry that validates definitions and L2-M6 records.

    ``validate_*`` returns no value because M0 deliberately does not create a
    calculated output.  Success only says that the governed inputs conform to
    a declared definition and remain eligible for a future materializer.
    """

    def __init__(self, definitions: Iterable[MetricDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._by_id = {definition.definition_id: definition for definition in self._definitions}
        if len(self._by_id) != len(self._definitions):
            raise MetricDefinitionError("duplicate metric definition identity/version")
        self._validate_definitions()

    @property
    def definitions(self) -> tuple[MetricDefinition, ...]:
        return self._definitions

    def resolve(self, definition_id: str) -> MetricDefinition:
        try:
            return self._by_id[definition_id]
        except KeyError as exc:
            raise MetricDefinitionError(f"unknown metric definition: {definition_id}") from exc

    def validate_handoff(
        self,
        *,
        definition_id: str,
        candidates: Iterable[Mapping[str, Any]],
        compatibility: Mapping[str, Any],
    ) -> None:
        """Validate M6 candidate IDs/roles and compatibility, never raw facts.

        The registry requires the candidate records produced by L2-M6.  It
        explicitly rejects value-bearing records, raw concept identifiers, and
        any compatibility result that is not eligible.
        """
        definition = self.resolve(definition_id)
        if definition.category is MetricCategory.DIRECT_OBSERVATION:
            raise MetricDefinitionError("direct metric requires direct-observation candidate boundary")
        _reject_calculated_fields(compatibility)
        _require_schema(compatibility, _COMPATIBILITY_REQUIRED, "compatibility")
        if compatibility.get("metric_definition_id") not in {None, definition_id}:
            raise MetricDefinitionError("compatibility references another metric definition")
        if compatibility.get("compatibility_status") != "ELIGIBLE":
            raise MetricDefinitionError("metric inputs are not eligible")
        records = tuple(dict(candidate) for candidate in candidates)
        if not records:
            raise MetricDefinitionError("metric definition requires L2-M6 candidates")
        ids = set()
        roles: list[str] = []
        for candidate in records:
            _reject_calculated_fields(candidate)
            _require_schema(candidate, _CANDIDATE_REQUIRED, "candidate")
            if candidate.get("raw_concept_id") or candidate.get("label"):
                raise MetricDefinitionError("registry consumes L2-M6 candidates, not raw concept inference")
            candidate_id = str(candidate["metric_input_candidate_id"])
            if candidate_id in ids:
                raise MetricDefinitionError("duplicate metric input candidate")
            ids.add(candidate_id)
            roles.append(str(candidate.get("metric_input_role") or ""))
            _validate_selected_source(candidate, direct=False)
        expected = tuple(role.value for role in definition.input_roles)
        if tuple(roles) != expected:
            raise MetricDefinitionError("candidate roles do not match declared definition input roles")
        compatibility_roles = tuple(str(role) for role in compatibility.get("required_input_roles", ()))
        if compatibility_roles != expected:
            raise MetricDefinitionError("compatibility roles do not match declared definition")
        analytical_ids = tuple(str(candidate["analytical_fact_id"]) for candidate in records)
        if tuple(str(item) for item in compatibility["input_analytical_fact_ids"]) != analytical_ids:
            raise MetricDefinitionError("compatibility analytical Fact IDs do not link to candidates")
        candidate_ids = tuple(str(candidate["metric_input_candidate_id"]) for candidate in records)
        if tuple(str(item) for item in compatibility["input_metric_input_candidate_ids"]) != candidate_ids:
            raise MetricDefinitionError("compatibility candidate IDs do not link to candidates")
        selected_ids = tuple(
            str(candidate["selected_fact_id"])
            for candidate in records
            if candidate.get("selected_fact_id")
        )
        if tuple(str(item) for item in compatibility["input_selected_fact_ids"]) != selected_ids:
            raise MetricDefinitionError("compatibility selected Fact IDs do not link to candidates")
        _validate_governed_scope(definition, records, compatibility)

    def validate_direct_observation(
        self, *, definition_id: str, candidate: Mapping[str, Any]
    ) -> None:
        """Validate the direct-only M6 candidate path for EPS or shares.

        L2-M6 intentionally does not manufacture a ratio-style compatibility
        record for direct observations.  This method is therefore the safe
        candidate-only boundary; it still accepts neither a value nor raw
        semantic inference.
        """
        definition = self.resolve(definition_id)
        if definition.category is not MetricCategory.DIRECT_OBSERVATION:
            raise MetricDefinitionError("derived metric requires compatibility diagnostic")
        record = dict(candidate)
        _reject_calculated_fields(record)
        _require_schema(record, _CANDIDATE_REQUIRED, "candidate")
        if record.get("raw_concept_id") or record.get("label"):
            raise MetricDefinitionError("registry consumes L2-M6 candidates, not raw concept inference")
        expected = definition.input_roles[0].value
        if record.get("metric_input_role") != expected:
            raise MetricDefinitionError("candidate role does not match direct definition")
        _validate_selected_source(record, direct=True)
        self._validate_direct_observations(definition, (record,))

    def _validate_definitions(self) -> None:
        active_by_metric: set[str] = set()
        all_metric_ids = {definition.metric_id for definition in self._definitions}
        for definition in self._definitions:
            if not definition.metric_id or not definition.version:
                raise MetricDefinitionError("metric definition requires metric_id and version")
            if not definition.input_roles:
                raise MetricDefinitionError("metric definition requires declared input roles")
            if not all(
                (definition.period_policy, definition.basis_policy, definition.dimension_policy,
                 definition.output_unit_semantics, definition.output_semantics,
                 definition.definition_source, definition.reviewed_by, definition.reviewed_at,
                 definition.change_note)
            ):
                raise MetricDefinitionError("metric definition lacks required governance metadata")
            if definition.status is DefinitionStatus.ACTIVE:
                if definition.metric_id in active_by_metric:
                    raise MetricDefinitionError("only one active version is allowed per metric")
                active_by_metric.add(definition.metric_id)
            if definition.category is MetricCategory.DERIVED:
                if definition.formula is None:
                    raise MetricDefinitionError("derived metric requires declarative formula metadata")
                if definition.direct_observation_required:
                    raise MetricDefinitionError("derived metric cannot require direct observation")
            else:
                if definition.formula is not None:
                    raise MetricDefinitionError("direct observation metric cannot define a formula")
                if not definition.direct_observation_required:
                    raise MetricDefinitionError("direct observation metric requires direct-observation policy")
            if definition.metric_id in definition.dependency_metric_ids:
                raise MetricDefinitionError("metric definition cannot depend on itself")
            unknown = set(definition.dependency_metric_ids) - all_metric_ids
            if unknown:
                raise MetricDefinitionError(f"metric definition has unknown dependencies: {sorted(unknown)}")
        self._reject_dependency_cycles()

    def _reject_dependency_cycles(self) -> None:
        graph = {item.metric_id: set(item.dependency_metric_ids) for item in self._definitions}
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(metric_id: str) -> None:
            if metric_id in visiting:
                raise MetricDefinitionError("metric dependency graph contains a cycle")
            if metric_id in visited:
                return
            visiting.add(metric_id)
            for dependency in graph[metric_id]:
                visit(dependency)
            visiting.remove(metric_id)
            visited.add(metric_id)

        for metric_id in graph:
            visit(metric_id)

    @staticmethod
    def _validate_direct_observations(
        definition: MetricDefinition, candidates: tuple[dict[str, Any], ...]
    ) -> None:
        if not definition.direct_observation_required:
            return
        for candidate in candidates:
            if candidate.get("candidate_status") != "DIRECT_OBSERVATION_ONLY":
                raise MetricDefinitionError("direct metric requires direct-observation-only candidate")
            if candidate.get("source_type") not in {"REPORTED", "RECAST_REPORTED"}:
                raise MetricDefinitionError("direct metric cannot use derived source type")
            if not candidate.get("selected_fact_id"):
                raise MetricDefinitionError("direct metric requires selected raw Fact lineage")
            if candidate.get("source_type") == "RECAST_REPORTED" and not candidate.get(
                "recast_evidence_id"
            ):
                raise MetricDefinitionError("recast direct metric requires recast evidence")


def _reject_calculated_fields(record: Mapping[str, Any]) -> None:
    found = sorted(field for field in _PROHIBITED_HANDOFF_FIELDS if field in record)
    if found:
        raise MetricDefinitionError(f"definition registry cannot accept calculated value fields: {found}")


def _require_schema(record: Mapping[str, Any], required: tuple[str, ...], name: str) -> None:
    missing = [field for field in required if field not in record]
    if missing:
        raise MetricDefinitionError(f"{name} lacks required L2-M6 provenance: {missing}")
    # A reporting basis may intentionally be unknown in AS_FILED records; its
    # field must nevertheless be preserved.  Empty dimensions are a valid total.
    nonempty = set(required) - {"basis_version", "company_canonical_dimension_key"}
    empty = [field for field in nonempty if record.get(field) is None or record.get(field) == ""]
    if empty:
        raise MetricDefinitionError(f"{name} has empty L2-M6 provenance: {empty}")


def _validate_selected_source(candidate: Mapping[str, Any], *, direct: bool) -> None:
    if candidate.get("candidate_status") == "UNAVAILABLE" or candidate.get("source_type") == "UNAVAILABLE":
        raise MetricDefinitionError("unavailable L2-M6 candidate cannot enter metric definition")
    source_type = str(candidate.get("source_type"))
    if source_type not in {"REPORTED", "RECAST_REPORTED", "DERIVED_RECAST"}:
        raise MetricDefinitionError("candidate has unsupported selected source type")
    selected = candidate.get("selected_fact_id")
    source_ids = tuple(candidate.get("source_fact_ids") or ())
    if not selected and not source_ids:
        raise MetricDefinitionError("candidate lacks selected raw Fact or derived source Fact lineage")
    if source_type in {"REPORTED", "RECAST_REPORTED"} and not selected:
        raise MetricDefinitionError("reported candidate requires selected raw Fact lineage")
    if source_type == "RECAST_REPORTED" and not candidate.get("recast_evidence_id"):
        raise MetricDefinitionError("recast reported candidate requires recast evidence")
    if source_type == "DERIVED_RECAST" and direct:
        raise MetricDefinitionError("direct metric cannot use derived source type")
    if not direct and candidate.get("candidate_status") != "CANDIDATE":
        raise MetricDefinitionError("derived metric requires candidate-status L2-M6 input")


def _validate_governed_scope(
    definition: MetricDefinition,
    candidates: tuple[dict[str, Any], ...],
    compatibility: Mapping[str, Any],
) -> None:
    """Ensure the diagnostic's scope is the candidates' actual governed scope."""
    common_fields = (
        "cik",
        "view",
        "as_of_date",
        "series_type",
        "period_class",
        "basis_version",
        "company_canonical_dimension_key",
        "unit_semantics",
    )
    for candidate in candidates:
        for field in common_fields:
            if candidate.get(field) != compatibility.get(field):
                raise MetricDefinitionError(f"candidate incompatible with diagnostic {field}")
        if definition.metric_id == "revenue_growth":
            expected_period = (
                compatibility.get("comparison_period_key")
                if candidate.get("metric_input_role") == MetricInputRole.PRIOR_REVENUE.value
                else compatibility.get("period_key")
            )
        else:
            expected_period = compatibility.get("period_key")
        if candidate.get("period_key") != expected_period:
            raise MetricDefinitionError("candidate incompatible with diagnostic period_key")
    expected_versions = tuple(sorted({str(row["mapping_version"]) for row in candidates}))
    if tuple(compatibility.get("mapping_versions") or ()) != expected_versions:
        raise MetricDefinitionError("compatibility mapping versions do not link to candidates")


def seed_metric_registry() -> MetricRegistry:
    """Return the deliberately small, reviewed M0 registry seed."""
    audit = {
        "definition_source": "derived-metrics-m0-controlled-seed",
        "reviewed_by": "governed-registry",
        "reviewed_at": "2026-08-28",
        "change_note": "initial controlled definition",
    }
    def formula(metric: str, expression: str) -> FormulaMetadata:
        return FormulaMetadata(
            formula_id=f"formula:{metric}",
            formula_version="v1",
            expression=expression,
            sign_convention="reported sign retained",
            scaling_convention="input scaling must match governed unit semantics",
        )
    return MetricRegistry(
        (
            MetricDefinition(
                "gross_margin", "1.0.0", DefinitionStatus.ACTIVE, MetricCategory.DERIVED,
                (MetricInputRole.GROSS_PROFIT, MetricInputRole.REVENUE), "SAME_PERIOD",
                "SAME_BASIS", "FULL_SIGNATURE_EQUAL", "PERCENT", "RATIO",
                formula("gross_margin", "GROSS_PROFIT / REVENUE"), False, (), **audit,
            ),
            MetricDefinition(
                "operating_margin", "1.0.0", DefinitionStatus.ACTIVE, MetricCategory.DERIVED,
                (MetricInputRole.OPERATING_INCOME, MetricInputRole.REVENUE), "SAME_PERIOD",
                "SAME_BASIS", "FULL_SIGNATURE_EQUAL", "PERCENT", "RATIO",
                formula("operating_margin", "OPERATING_INCOME / REVENUE"), False, (), **audit,
            ),
            MetricDefinition(
                "revenue_growth", "1.0.0", DefinitionStatus.ACTIVE, MetricCategory.DERIVED,
                (MetricInputRole.CURRENT_REVENUE, MetricInputRole.PRIOR_REVENUE),
                "DECLARED_PREDECESSOR", "SAME_BASIS", "FULL_SIGNATURE_EQUAL", "PERCENT",
                "GROWTH_RATE", formula("revenue_growth", "CURRENT_REVENUE / PRIOR_REVENUE - 1"),
                False, (), **audit,
            ),
            MetricDefinition(
                "q4_flow_eligibility", "1.0.0", DefinitionStatus.ACTIVE, MetricCategory.DERIVED,
                (MetricInputRole.CONTROLLED_Q4_FLOW,), "CONTROLLED_Q4", "SAME_BASIS",
                "FULL_SIGNATURE_EQUAL", "INPUT_UNIT", "ELIGIBILITY_ONLY",
                formula("q4_flow_eligibility", "controlled input eligibility; no value calculation"),
                False, (), **audit,
            ),
            MetricDefinition(
                "eps", "1.0.0", DefinitionStatus.ACTIVE, MetricCategory.DIRECT_OBSERVATION,
                (MetricInputRole.EPS,), "REPORTED_PERIOD", "REPORTED_OR_EVIDENCE_BOUND_RECAST",
                "FULL_SIGNATURE_EQUAL", "PER_SHARE", "DIRECT_REPORTED_OBSERVATION", None, True, (),
                **audit,
            ),
            MetricDefinition(
                "weighted_average_shares", "1.0.0", DefinitionStatus.ACTIVE,
                MetricCategory.DIRECT_OBSERVATION, (MetricInputRole.WEIGHTED_AVERAGE_SHARES,),
                "REPORTED_PERIOD", "REPORTED_OR_EVIDENCE_BOUND_RECAST", "FULL_SIGNATURE_EQUAL",
                "SHARES", "DIRECT_REPORTED_OBSERVATION", None, True, (), **audit,
            ),
        )
    )
