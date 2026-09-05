"""Stable in-process analytical query boundary."""

from sec_xbrl.analytics.company_analysis_panel import (
    COMPANY_ANALYSIS_PANEL_VERSION,
    CompanyAnalysisPanelBuilder,
    CompanyAnalysisPanelError,
    CompanyAnalysisPanelQuery,
    CompanyAnalysisPanelResult,
)
from sec_xbrl.analytics.data_access import ConsumerDataAccess
from sec_xbrl.analytics.operational_query import (
    OPERATIONAL_ANALYTICS_QUERY_VERSION,
    OperationalAnalyticsQueryError,
    OperationalAnalyticsQueryService,
    OperationalPublicationRoots,
    OperationalQueryScope,
)
from sec_xbrl.analytics.quarterly_analysis_pivot import (
    QUARTERLY_ANALYSIS_PIVOT_VERSION,
    QuarterlyAnalysisPivotBuilder,
    QuarterlyAnalysisPivotError,
    QuarterlyAnalysisPivotQuery,
    QuarterlyAnalysisPivotResult,
)
from sec_xbrl.analytics.quarterly_derived_metrics import (
    QUARTERLY_DERIVED_METRICS_VERSION,
    QuarterlyDerivedMetricsBuilder,
    QuarterlyDerivedMetricsResult,
)
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
    "COMPANY_ANALYSIS_PANEL_VERSION",
    "OPERATIONAL_ANALYTICS_QUERY_VERSION",
    "QUARTERLY_ANALYSIS_PIVOT_VERSION",
    "QUARTERLY_DERIVED_METRICS_VERSION",
    "AnalyticalRepository",
    "AnalyticalRepositoryError",
    "CapabilityInventoryNotFoundError",
    "CompanyAmbiguousError",
    "CompanyAnalysisPanelBuilder",
    "CompanyAnalysisPanelError",
    "CompanyAnalysisPanelQuery",
    "CompanyAnalysisPanelResult",
    "CompanyNotFoundError",
    "ConsumerDataAccess",
    "DerivedMetricConflictError",
    "DerivedMetricNotFoundError",
    "FactNotFoundError",
    "KoreanReviewInventoryReport",
    "KoreanReviewInventoryReportGenerator",
    "OperationalAnalyticsQueryError",
    "OperationalAnalyticsQueryService",
    "OperationalPublicationRoots",
    "OperationalQueryScope",
    "QuarterlyAnalysisPivotBuilder",
    "QuarterlyAnalysisPivotError",
    "QuarterlyAnalysisPivotQuery",
    "QuarterlyAnalysisPivotResult",
    "QuarterlyDerivedMetricsBuilder",
    "QuarterlyDerivedMetricsResult",
    "ReviewInventoryReportInput",
]
