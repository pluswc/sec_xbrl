from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FilingRef:
    cik: str
    accession: str
    form: str
    filed_date: date
    report_date: date | None = None
    primary_document: str | None = None
    is_xbrl: bool | None = None
    is_inline_xbrl: bool | None = None
    source: str = "sec_submissions"


class AccessionProvider(Protocol):
    def iter_filings(self, *, forms: set[str]) -> Iterable[FilingRef]: ...
