"""Stable in-process analytical query boundary."""

from sec_xbrl.analytics.repository import (
    AnalyticalRepository,
    AnalyticalRepositoryError,
    CompanyAmbiguousError,
    CompanyNotFoundError,
    FactNotFoundError,
)

__all__ = [
    "AnalyticalRepository",
    "AnalyticalRepositoryError",
    "CompanyAmbiguousError",
    "CompanyNotFoundError",
    "FactNotFoundError",
]
