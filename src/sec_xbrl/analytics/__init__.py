"""Stable in-process analytical query boundary."""

from sec_xbrl.analytics.repository import (
    AnalyticalRepository,
    AnalyticalRepositoryError,
    CapabilityInventoryNotFoundError,
    CompanyAmbiguousError,
    CompanyNotFoundError,
    DerivedMetricConflictError,
    DerivedMetricNotFoundError,
    FactNotFoundError,
)

__all__ = [
    "AnalyticalRepository",
    "AnalyticalRepositoryError",
    "CapabilityInventoryNotFoundError",
    "CompanyAmbiguousError",
    "CompanyNotFoundError",
    "DerivedMetricConflictError",
    "DerivedMetricNotFoundError",
    "FactNotFoundError",
]
