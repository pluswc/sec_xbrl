"""Common, storage-agnostic data-access contract for analysis consumers.

The contract is deliberately an in-process Python protocol.  It is not an
HTTP API, an MCP tool definition, or an Excel-specific interface.  A
publication-backed repository satisfies it today; a future DB or Parquet
adapter must preserve the same governed query behavior.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConsumerDataAccess(Protocol):
    """Read-only contract for governed Analytical and Derived Metrics data.

    Implementations resolve public company selectors exactly, retain the
    upstream period/view/as-of/basis/dimension/status/provenance fields, and
    return independent copies.  They must not parse filings, calculate a
    metric, infer a semantic match from labels, or silently choose an
    incompatible basis.  The methods below are the supported C0/C1 surface;
    callers can depend on them without depending on a physical store.
    """

    def resolve_company(self, selector: str) -> dict[str, Any]:
        """Resolve one exact public company selector or fail explicitly."""

    def get_fact_series(
        self,
        company: str,
        concept: str,
        frequency: str | None = None,
        start: str | None = None,
        end: str | None = None,
        view: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return an exact governed fact series without period coalescing."""

    def discover_capabilities(
        self,
        company: str,
        *,
        raw_concept_id: str | None = None,
        axis_raw_concept_id: str | None = None,
        member_raw_concept_id: str | None = None,
        period_class: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return only observed company-local capability rows or its governed status."""

    def discover_metrics(
        self,
        company: str,
        *,
        metric_id: str | None = None,
        definition_version: str | None = None,
        frequency: str | None = None,
        view: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Discover verified metric candidates without selection or calculation."""

    def get_metric_series(
        self,
        company: str,
        metric: str,
        *,
        as_of_date: str,
        view: str,
        frequency: str | None = None,
        start: str | None = None,
        end: str | None = None,
        definition_version: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return a governed metric selection for an explicit view and as-of date."""

    def trace_fact(self, fact_id: str) -> dict[str, Any]:
        """Return one provenance-enriched reported or analytical fact."""

    def trace_metric(self, derived_metric_id: str) -> dict[str, Any]:
        """Return one provenance-enriched metric admitted from a verified root."""

    def compare_companies(
        self,
        companies: Sequence[str],
        concept_or_metric: str,
        period_or_range: str | tuple[str | None, str | None] | None = None,
        mapping_version: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return Layer 3 comparison rows without upgrading their mapping relation."""
