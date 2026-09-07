"""Read-only operational serving over already-published T1--T4 Parquet runs.

This module is deliberately an *adapter*, not another materialization
pipeline.  It admits only manifest-verified immutable publications, applies
the existing T4-B selector in memory, and then composes the T5--T8 serving
models.  It never imports a Layer 1 parser or a publisher.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.analytics.company_analysis_panel import (
    CompanyAnalysisPanelBuilder,
    CompanyAnalysisPanelQuery,
    CompanyAnalysisPanelResult,
)
from sec_xbrl.analytics.quarterly_analysis_pivot import (
    QuarterlyAnalysisPivotBuilder,
    QuarterlyAnalysisPivotQuery,
    QuarterlyAnalysisPivotResult,
)
from sec_xbrl.analytics.quarterly_derived_metrics import (
    QuarterlyDerivedMetricsBuilder,
    QuarterlyDerivedMetricsResult,
)
from sec_xbrl.cross_company.comparison_panel import (
    CrossCompanyComparisonPanelBuilder,
    CrossCompanyComparisonPanelQuery,
    CrossCompanyComparisonPanelResult,
)
from sec_xbrl.longitudinal.accession_version_ledger import AccessionVersionLedgerReader
from sec_xbrl.longitudinal.exploration_graph import ExplorationGraphReader
from sec_xbrl.longitudinal.materialization import Layer2PublicationReader, VerifiedLayer2Publication
from sec_xbrl.longitudinal.reported_selection import ReportedObservationSelector
from sec_xbrl.longitudinal.versioned_observation_panel import VersionedObservationPanelReader

OPERATIONAL_ANALYTICS_QUERY_VERSION = "operational-t4-t8-query-v1"
_OPERATIONAL_STORAGE_FORMAT = "parquet-operational-v1"


class OperationalAnalyticsQueryError(ValueError):
    """Raised when published inputs cannot safely serve one governed query."""


@dataclass(frozen=True, slots=True)
class OperationalPublicationRoots:
    """The four immutable T1--T4 publication roots required by this adapter."""

    reported_observations: Path
    relationships: Path
    exploration_graph: Path
    accession_ledger: Path


@dataclass(frozen=True, slots=True)
class OperationalQueryScope:
    """An explicit company, fiscal period, selection view, and knowledge date."""

    cik: str
    fiscal_year: int
    fiscal_quarter: int
    period_class: str
    view: str
    as_of_date: str

    def __post_init__(self) -> None:
        if not self.cik or self.fiscal_year < 1 or self.fiscal_quarter not in {1, 2, 3, 4}:
            raise OperationalAnalyticsQueryError("query requires CIK and a valid fiscal year/quarter")
        if not self.period_class or self.view not in {"AS_FILED", "LATEST_REPORTED"} or not self.as_of_date:
            raise OperationalAnalyticsQueryError("query requires period class, supported view, and as-of date")


class OperationalAnalyticsQueryService:
    """In-process, defensive, cache-backed T4--T8 consumer interface.

    The constructor is the publication attestation boundary.  Once created,
    every public method reads the already verified in-memory publication rows
    and composes only T4-B/T5/T6/T7/T8.  Result caches are keyed by the
    immutable manifest identities as well as the full query scope, so a new
    publication cannot accidentally reuse an earlier answer.
    """

    def __init__(self, roots: OperationalPublicationRoots) -> None:
        reader = Layer2PublicationReader()
        self._roots = OperationalPublicationRoots(**{
            # Preserve a symlink in the user-provided path so the existing
            # verified reader can reject it instead of resolving around its
            # immutable-publication boundary.
            key: Path(getattr(roots, key)).absolute()
            for key in ("reported_observations", "relationships", "exploration_graph", "accession_ledger")
        })
        self._publications = {
            name: self._load_operational_root(reader, name, root)
            for name, root in (
                ("reported_observations", self._roots.reported_observations),
                ("relationships", self._roots.relationships),
                ("exploration_graph", self._roots.exploration_graph),
                ("accession_ledger", self._roots.accession_ledger),
            )
        }
        self._attest_compatible_roots()
        self._root_identity = tuple(
            (name, str(publication.identity["layer2_manifest_sha256"]))
            for name, publication in sorted(self._publications.items())
        )
        self._panel_cache: dict[tuple[object, ...], CompanyAnalysisPanelResult] = {}
        self._pivot_cache: dict[tuple[object, ...], QuarterlyAnalysisPivotResult] = {}
        self._metric_cache: dict[tuple[object, ...], QuarterlyDerivedMetricsResult] = {}
        self._comparison_cache: dict[tuple[object, ...], CrossCompanyComparisonPanelResult] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def publication_identity(self) -> dict[str, Any]:
        """Independent copies of the immutable roots that scoped this service."""
        return {
            "operational_analytics_query_version": OPERATIONAL_ANALYTICS_QUERY_VERSION,
            "roots": deepcopy(dict(self._root_identity)),
            "layer2_run_fingerprint": self._fingerprint,
        }

    def cache_info(self) -> dict[str, int]:
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "panels": len(self._panel_cache),
            "pivots": len(self._pivot_cache),
            "metrics": len(self._metric_cache),
            "comparisons": len(self._comparison_cache),
        }

    def company_panel(self, scope: OperationalQueryScope) -> CompanyAnalysisPanelResult:
        key = ("panel", self._root_identity, scope)
        cached = self._panel_cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            return deepcopy(cached)
        self._cache_misses += 1
        observations = VersionedObservationPanelReader().get_period(
            self._publications["reported_observations"],
            cik=scope.cik, fiscal_year=scope.fiscal_year, fiscal_quarter=scope.fiscal_quarter,
            period_class=scope.period_class,
        )
        ledger = AccessionVersionLedgerReader().get_company(
            self._publications["accession_ledger"], cik=scope.cik
        )
        selected = ReportedObservationSelector().select_period(
            observations=observations, ledger=ledger, cik=scope.cik,
            fiscal_year=scope.fiscal_year, fiscal_quarter=scope.fiscal_quarter,
            period_class=scope.period_class, as_of_date=scope.as_of_date, view=scope.view,
        )
        result = CompanyAnalysisPanelBuilder().build(
            selected_rows=selected.rows, exploration=self._publications["exploration_graph"],
            cik=scope.cik, fiscal_year=scope.fiscal_year, fiscal_quarter=scope.fiscal_quarter,
            period_class=scope.period_class, view=scope.view, as_of_date=scope.as_of_date,
        )
        self._panel_cache[key] = deepcopy(result)
        return deepcopy(result)

    def company_panel_rows(self, scope: OperationalQueryScope) -> tuple[dict[str, Any], ...]:
        return CompanyAnalysisPanelQuery(self.company_panel(scope)).rows()

    def company_pivot(self, scopes: Sequence[OperationalQueryScope]) -> QuarterlyAnalysisPivotResult:
        normalized = self._normalize_company_scopes(scopes)
        key = ("pivot", self._root_identity, normalized)
        cached = self._pivot_cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            return deepcopy(cached)
        self._cache_misses += 1
        result = QuarterlyAnalysisPivotBuilder().build(
            panels=tuple(self.company_panel(scope) for scope in normalized)
        )
        self._pivot_cache[key] = deepcopy(result)
        return deepcopy(result)

    def company_pivot_matrix(self, scopes: Sequence[OperationalQueryScope]) -> tuple[dict[str, Any], ...]:
        return QuarterlyAnalysisPivotQuery(self.company_pivot(scopes)).matrix()

    def quarterly_metrics(self, scopes: Sequence[OperationalQueryScope]) -> QuarterlyDerivedMetricsResult:
        normalized = self._normalize_company_scopes(scopes)
        key = ("metrics", self._root_identity, normalized)
        cached = self._metric_cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            return deepcopy(cached)
        self._cache_misses += 1
        result = QuarterlyDerivedMetricsBuilder().build(pivot=self.company_pivot(normalized))
        self._metric_cache[key] = deepcopy(result)
        return deepcopy(result)

    def cross_company_comparison(
        self,
        *,
        company_scopes: Mapping[str, Sequence[OperationalQueryScope]],
        fiscal_year: int,
        fiscal_quarter: int,
        reviewed_concept_mappings: Iterable[Mapping[str, Any]] = (),
    ) -> CrossCompanyComparisonPanelResult:
        if len(company_scopes) < 2:
            raise OperationalAnalyticsQueryError("cross-company comparison requires at least two companies")
        normalized = tuple(
            (cik, self._normalize_company_scopes(scopes, expected_cik=cik))
            for cik, scopes in sorted(company_scopes.items())
        )
        mappings = tuple(deepcopy(dict(row)) for row in reviewed_concept_mappings)
        key = ("comparison", self._root_identity, normalized, fiscal_year, fiscal_quarter, repr(mappings))
        cached = self._comparison_cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            return deepcopy(cached)
        self._cache_misses += 1
        result = CrossCompanyComparisonPanelBuilder().build(
            pivots=tuple(self.company_pivot(scopes) for _, scopes in normalized),
            fiscal_year=fiscal_year, fiscal_quarter=fiscal_quarter,
            reviewed_concept_mappings=mappings,
        )
        self._comparison_cache[key] = deepcopy(result)
        return deepcopy(result)

    def cross_company_matrix(self, **kwargs: Any) -> tuple[dict[str, Any], ...]:
        return CrossCompanyComparisonPanelQuery(self.cross_company_comparison(**kwargs)).matrix()

    @property
    def _fingerprint(self) -> str:
        return str(self._publications["reported_observations"].identity["layer2_run_fingerprint"])

    def _attest_compatible_roots(self) -> None:
        required = {
            "reported_observations": "reported_period_observation",
            "relationships": "filing_relationship_edge",
            "exploration_graph": "analysis_exploration_node",
            "accession_ledger": "accession_version_ledger",
        }
        first: VerifiedLayer2Publication | None = None
        for name, dataset in required.items():
            publication = self._publications[name]
            if dataset not in publication.datasets:
                raise OperationalAnalyticsQueryError(f"{name} root lacks required {dataset} dataset")
            if first is None:
                first = publication
                continue
            if publication.identity["layer2_run_fingerprint"] != first.identity["layer2_run_fingerprint"]:
                raise OperationalAnalyticsQueryError("operational roots must declare the identical immutable Layer 1 input run")
            if publication.input_ciks != first.input_ciks:
                raise OperationalAnalyticsQueryError("operational roots have incompatible declared CIK scope")
        # T3's edge dataset is its own atomic graph contract; check it here so
        # a node-only publication cannot masquerade as navigable evidence.
        graph = self._publications["exploration_graph"]
        if "analysis_exploration_edge" not in graph.datasets:
            raise OperationalAnalyticsQueryError("exploration root lacks required analysis_exploration_edge dataset")
        ExplorationGraphReader()._check(graph, None)

    @staticmethod
    def _load_operational_root(
        reader: Layer2PublicationReader, name: str, root: Path
    ) -> VerifiedLayer2Publication:
        """Reject contract fixtures before the generic reader admits their rows."""
        manifest_path = root / Layer2PublicationReader.manifest_name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # The generic reader supplies a more detailed error only after the
            # operating-format boundary has been established; malformed input
            # is never treated as an alternative storage adapter here.
            raise OperationalAnalyticsQueryError(
                f"{name} root has no readable operational publication manifest"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("storage_format") != _OPERATIONAL_STORAGE_FORMAT:
            raise OperationalAnalyticsQueryError(
                f"{name} root must use {_OPERATIONAL_STORAGE_FORMAT}"
            )
        return reader.load(root)

    @staticmethod
    def _normalize_company_scopes(
        scopes: Sequence[OperationalQueryScope], *, expected_cik: str | None = None
    ) -> tuple[OperationalQueryScope, ...]:
        result = tuple(scopes)
        if not result:
            raise OperationalAnalyticsQueryError("pivot requires at least one explicit fiscal scope")
        first = result[0]
        if expected_cik is not None and first.cik != expected_cik:
            raise OperationalAnalyticsQueryError("company scope key and CIK disagree")
        periods: set[tuple[int, int]] = set()
        for scope in result:
            if expected_cik is not None and scope.cik != expected_cik:
                raise OperationalAnalyticsQueryError("company scopes cannot mix CIKs")
            if any(
                getattr(scope, field) != getattr(first, field)
                for field in ("cik", "period_class", "view", "as_of_date")
            ):
                raise OperationalAnalyticsQueryError("pivot scopes must share CIK, period class, view, and as-of date")
            period = (scope.fiscal_year, scope.fiscal_quarter)
            if period in periods:
                raise OperationalAnalyticsQueryError("pivot scopes cannot repeat one fiscal period")
            periods.add(period)
        return tuple(sorted(result, key=lambda item: (item.fiscal_year, item.fiscal_quarter)))
