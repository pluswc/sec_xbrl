"""Governed Derived Metrics definitions.

This package owns definitions and input-contract validation only.  It does not
calculate or persist a ``derived_metric`` value.
"""

from sec_xbrl.metrics.registry import (
    METRIC_REGISTRY_CONTRACT_VERSION,
    DefinitionStatus,
    FormulaMetadata,
    MetricCategory,
    MetricDefinition,
    MetricDefinitionError,
    MetricInputRole,
    MetricRegistry,
    seed_metric_registry,
)

__all__ = [
    "METRIC_REGISTRY_CONTRACT_VERSION",
    "DefinitionStatus",
    "FormulaMetadata",
    "MetricCategory",
    "MetricDefinition",
    "MetricDefinitionError",
    "MetricInputRole",
    "MetricRegistry",
    "seed_metric_registry",
]
