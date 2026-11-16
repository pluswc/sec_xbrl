"""Explicit, hash-bound fiscal calendars. No calendar is inferred from durations."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA = "reviewed-fiscal-calendar-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pinned(pin: dict[str, str]) -> dict:
    path = Path(pin["path"])
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("fiscal calendar source/approval pin mismatch")
    return pin


@dataclass(frozen=True)
class ReviewedFiscalCalendar:
    """A complete, reviewed four-quarter calendar, not financial source approval."""
    calendar_id: str
    cik: str
    fiscal_year: int
    financial_as_of: str
    boundaries: tuple[str, ...]
    artifact_sha256: str
    calendar_sha256: str
    pins: tuple[tuple[str, str], ...]

    def verify(self) -> None:
        for path, sha in self.pins:
            pinned({"path": path, "sha256": sha})

    def matches(self, row: dict, cutoff: str) -> bool:
        return (row.get("cik") == self.cik and row.get("fiscal_year") == self.fiscal_year
            and cutoff == self.financial_as_of and isinstance(row.get("filed_date"), str) and row["filed_date"] <= cutoff
            and not row.get("fiscal_coordinate_problem"))

    def allows(self, row: dict, cutoff: str) -> bool:
        if not self.matches(row, cutoff):
            return False
        start, end = row.get("context_start_date"), row.get("context_end_date")
        period = row.get("period_class")
        allowed = {"FY": [(self.boundaries[0], self.boundaries[4])],
                   "YTD_9M": [(self.boundaries[0], self.boundaries[3])],
                   "QTD_3M": list(zip(self.boundaries[:-1], self.boundaries[1:], strict=True))}
        return (start, end) in allowed.get(period, []) and row.get("context_duration_days") == (date.fromisoformat(end) - date.fromisoformat(start)).days

    def allows_pair(self, later: dict, earlier: dict, cutoff: str) -> bool:
        return self.allows(later, cutoff) and self.allows(earlier, cutoff) and (
            later.get("period_class"), earlier.get("period_class"), later.get("context_start_date"),
            earlier.get("context_end_date"), later.get("context_end_date")) == (
            "FY", "YTD_9M", self.boundaries[0], self.boundaries[3], self.boundaries[4])

    def proof(self) -> dict:
        return {"schema_version": SCHEMA, "calendar_id": self.calendar_id, "cik": self.cik,
                "fiscal_year": self.fiscal_year, "financial_as_of": self.financial_as_of,
                "exclusive_boundaries": list(self.boundaries), "artifact_sha256": self.artifact_sha256,
                "calendar_sha256": self.calendar_sha256, "source_approval_pins": [{"path": p, "sha256": s} for p, s in self.pins]}


@dataclass(frozen=True)
class FiscalCalendarRegistry:
    calendars: tuple[ReviewedFiscalCalendar, ...]

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str) -> FiscalCalendarRegistry:
        pin = pinned({"path": str(path), "sha256": expected_sha256})
        payload = json.loads(path.read_text())
        if payload.get("schema_version") != SCHEMA or not isinstance(payload.get("calendars"), list) or not payload["calendars"]:
            raise ValueError("invalid fiscal calendar registry")
        calendars, identities = [], set()
        for entry in payload["calendars"]:
            body = {k: v for k, v in entry.items() if k != "approval"}
            sha = digest(body)
            approval_pin = pinned(entry["approval"])
            approval = json.loads(Path(approval_pin["path"]).read_text())
            if approval != {"schema_version": "root-fiscal-calendar-approval-v1", "authority": "ROOT", "status": "APPROVED", "calendar_sha256": sha}:
                raise ValueError("unapproved fiscal calendar")
            start = entry["start_date"]
            ends, weeks = entry["quarter_end_dates"], entry["quarter_weeks"]
            if not isinstance(weeks, list) or any(type(week) is not int for week in weeks) or weeks not in ([12, 12, 12, 16], [12, 12, 12, 17]) or len(ends) != 4:
                raise ValueError("unsupported/partial fiscal calendar")
            boundaries = (start, *ends)
            if any((date.fromisoformat(b) - date.fromisoformat(a)).days != w * 7 for a, b, w in zip(boundaries[:-1], boundaries[1:], weeks, strict=True)):
                raise ValueError("noncontiguous fiscal calendar boundaries")
            if type(entry["fiscal_year"]) is not int or not isinstance(entry["cik"], str) or len(entry["cik"]) != 10 or not entry["cik"].isdigit():
                raise ValueError("invalid fiscal calendar owner")
            if entry["financial_as_of"] != payload["financial_as_of"]:
                raise ValueError("fiscal calendar cutoff mismatch")
            date.fromisoformat(entry["financial_as_of"])
            source_pins = [pinned(source) for source in entry["source_pins"]]
            if not source_pins or not entry["evidence"] or any(not item.get("locator") or not item.get("assertion") or not isinstance(item.get("source_index"), int) or not 0 <= item["source_index"] < len(source_pins) for item in entry["evidence"]):
                raise ValueError("fiscal calendar evidence missing")
            identity = entry["cik"], entry["fiscal_year"]
            if identity in identities:
                raise ValueError("ambiguous fiscal calendar owner/year")
            identities.add(identity)
            pins = [pin, approval_pin, *source_pins]
            calendars.append(ReviewedFiscalCalendar(entry["calendar_id"], *identity, entry["financial_as_of"], boundaries, expected_sha256, sha,
                tuple((p["path"], p["sha256"]) for p in pins)))
        return cls(tuple(calendars))

    def get(self, cik: str, fiscal_year: int) -> ReviewedFiscalCalendar | None:
        return next((item for item in self.calendars if (item.cik, item.fiscal_year) == (cik, fiscal_year)), None)
