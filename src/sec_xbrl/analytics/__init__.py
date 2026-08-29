"""Stable in-process analytical query boundary."""

from sec_xbrl.analytics.data_access import ConsumerDataAccess
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
from sec_xbrl.analytics.review_inventory_report import (
    KoreanReviewInventoryReport,
    KoreanReviewInventoryReportGenerator,
    ReviewInventoryReportInput,
)

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
    "KoreanReviewInventoryReport",
    "KoreanReviewInventoryReportGenerator",
    "ReviewInventoryReportInput",
]
