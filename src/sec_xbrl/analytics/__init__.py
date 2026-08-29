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
from sec_xbrl.analytics.data_access import ConsumerDataAccess

__all__ = [
    "AnalyticalRepository",
    "AnalyticalRepositoryError",
    "CapabilityInventoryNotFoundError",
    "CompanyAmbiguousError",
    "CompanyNotFoundError",
    "ConsumerDataAccess",
    "DerivedMetricConflictError",
    "DerivedMetricNotFoundError",
    "FactNotFoundError",
]
