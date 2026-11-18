"""Conservative fiscal-coordinate diagnostics; never invent an effective year."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any


def fiscal_coordinate_problem(filing: Mapping[str, Any]) -> str | None:
    """Flag gross focus/report-date contradictions, permitting named fiscal years.

    Fiscal names may differ from endpoint calendar years by one. A larger gap is
    diagnostic evidence only: neither a correction nor a new fiscal coordinate.
    Exact approved corrections are evaluated on their effective filing copy.
    """
    try:
        focus = int(str(filing.get("document_fiscal_year_focus")))
        report = date.fromisoformat(str(filing.get("report_date")))
    except (TypeError, ValueError):
        return None
    return "FISCAL_FOCUS_REPORT_DATE_CONFLICT" if abs(focus - report.year) > 1 else None
