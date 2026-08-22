"""Company-scoped SEC submissions discovery and FilingRef adaptation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from sec_xbrl.filing.contracts import FilingRef

SUPPORTED_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class DiscoveryError(ValueError):
    """Base error for malformed company discovery inputs."""


class DuplicateAccessionError(DiscoveryError):
    """Raised when source payloads disagree about one accession."""


def canonicalize_cik(value: str | int) -> str:
    """Return a zero-padded ten-digit CIK without accepting lossy input."""
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10:
        raise DiscoveryError(f"invalid CIK: {value!r}")
    return text.zfill(10)


def parse_sec_date(value: object, *, field: str) -> date | None:
    """Parse SEC's compact or ISO date representation; blanks are absent."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise DiscoveryError(f"{field} must be a string date")
    try:
        if len(value) == 8 and value.isdigit():
            return date(int(value[:4]), int(value[4:6]), int(value[6:]))
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DiscoveryError(f"invalid {field}: {value!r}") from exc


def _optional_bool(value: object, *, field: str) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.lower() in {"true", "false", "0", "1"}:
        return value.lower() in {"true", "1"}
    raise DiscoveryError(f"invalid {field}: {value!r}")


@dataclass(frozen=True, slots=True)
class CompanyTarget:
    cik: str
    ticker: str | None = None
    name: str | None = None


def load_company_targets(path: Path) -> tuple[CompanyTarget, ...]:
    """Load a deterministic, duplicate-free JSONL company target list."""
    targets: dict[str, CompanyTarget] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(raw, dict) or "cik" not in raw:
            raise DiscoveryError(f"missing cik at {path}:{line_number}")
        cik = canonicalize_cik(raw["cik"])
        target = CompanyTarget(
            cik=cik,
            ticker=_optional_text(raw.get("ticker"), field="ticker"),
            name=_optional_text(raw.get("name"), field="name"),
        )
        if cik in targets:
            raise DiscoveryError(f"duplicate CIK in targets: {cik}")
        targets[cik] = target
    return tuple(targets[cik] for cik in sorted(targets))


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise DiscoveryError(f"{field} must be text")
    return value


class SubmissionsSnapshotStore:
    """Content-addressed immutable store for raw SEC submissions payloads."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, cik: str | int, payload: bytes) -> Path:
        canonical_cik = canonicalize_cik(cik)
        _decode_payload(payload)
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.root / canonical_cik / f"{digest}.json"
        if destination.exists():
            if destination.read_bytes() != payload:
                raise DiscoveryError(f"immutable snapshot collision: {destination}")
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
        return destination


class DiscoveryStateStore:
    """Mutable company discovery checkpoint, explicitly separate from raw data."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, cik: str | int, snapshot_paths: Sequence[Path]) -> Path:
        canonical_cik = canonicalize_cik(cik)
        destination = self.root / f"{canonical_cik}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cik": canonical_cik,
            "snapshot_hashes": [path.stem for path in snapshot_paths],
        }
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
        return destination


class SubmissionsFetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


class SECSubmissionsClient:
    """Small synchronous SEC client with a configurable user agent and retry policy."""

    def __init__(
        self,
        *,
        user_agent: str,
        min_interval_seconds: float = 0.2,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC user agent is required")
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.retries = retries
        self.transport = transport
        self._last_request_at = 0.0

    def fetch(self, url: str) -> bytes:
        for attempt in range(self.retries + 1):
            delay = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
            self._last_request_at = time.monotonic()
            try:
                with httpx.Client(
                    headers={"User-Agent": self.user_agent}, timeout=30.0, transport=self.transport
                ) as client:
                    response = client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise DiscoveryError(f"SEC submissions request failed: {url}") from exc
        raise AssertionError("unreachable")


class CompanySubmissionsCollector:
    """Fetch a CIK's root and historical submissions payloads into raw cache."""

    base_url = "https://data.sec.gov/submissions"

    def __init__(
        self,
        fetcher: SubmissionsFetcher | Callable[[str], bytes],
        snapshots: SubmissionsSnapshotStore,
        state: DiscoveryStateStore,
    ) -> None:
        self.fetcher = fetcher
        self.snapshots = snapshots
        self.state = state

    def collect(self, cik: str | int) -> tuple[Path, ...]:
        canonical_cik = canonicalize_cik(cik)
        root_path = self.snapshots.store(
            canonical_cik,
            self._fetch(f"{self.base_url}/CIK{canonical_cik}.json"),
        )
        root_payload = _decode_payload(root_path.read_bytes())
        paths = [root_path]
        for filename in _historical_submission_filenames(root_payload):
            paths.append(
                self.snapshots.store(
                    canonical_cik,
                    self._fetch(f"{self.base_url}/{filename}"),
                )
            )
        result = tuple(paths)
        self.state.write(canonical_cik, result)
        return result

    def _fetch(self, url: str) -> bytes:
        if callable(self.fetcher):
            return self.fetcher(url)
        return self.fetcher.fetch(url)


def _historical_submission_filenames(payload: dict[str, Any]) -> tuple[str, ...]:
    files = payload.get("filings", {}).get("files", [])
    if not isinstance(files, list):
        raise DiscoveryError("filings.files must be a list")
    names: list[str] = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise DiscoveryError("historical submissions entry missing name")
        name = item["name"]
        if Path(name).name != name or not name.endswith(".json"):
            raise DiscoveryError(f"unsafe historical submissions name: {name!r}")
        names.append(name)
    return tuple(sorted(set(names)))


class CompanySubmissionsAccessionProvider:
    """Read cached SEC submissions payloads as deterministic FilingRef values."""

    source = "sec_submissions"

    def __init__(self, snapshot_paths: Iterable[Path], *, cik: str | int | None = None) -> None:
        self.snapshot_paths = tuple(sorted(snapshot_paths))
        self.cik = canonicalize_cik(cik) if cik is not None else None

    def iter_filings(self, *, forms: set[str]) -> Iterator[FilingRef]:
        unsupported_forms = forms - SUPPORTED_FORMS
        if unsupported_forms:
            raise DiscoveryError(f"unsupported forms requested: {sorted(unsupported_forms)}")
        records: dict[tuple[str, str], FilingRef] = {}
        for path in self.snapshot_paths:
            for ref in _filing_refs_from_payload(
                _decode_payload(path.read_bytes()), expected_cik=self.cik
            ):
                if ref.form not in forms:
                    continue
                key = (ref.cik, ref.accession)
                existing = records.get(key)
                if existing is not None and existing != ref:
                    raise DuplicateAccessionError(f"conflicting duplicate accession: {key}")
                records[key] = ref
        yield from sorted(records.values(), key=lambda ref: (ref.filed_date, ref.accession, ref.cik))


def _filing_refs_from_payload(
    payload: dict[str, Any], *, expected_cik: str | None
) -> Iterator[FilingRef]:
    payload_cik = payload.get("cik")
    if payload_cik is None:
        if expected_cik is None:
            raise DiscoveryError("submissions payload has no cik; expected CIK is required")
        cik = expected_cik
    else:
        cik = canonicalize_cik(payload_cik)
        if expected_cik is not None and cik != expected_cik:
            raise DiscoveryError(f"submissions CIK mismatch: expected {expected_cik}, got {cik}")
    filings = payload.get("filings")
    columns = filings.get("recent") if isinstance(filings, dict) and "recent" in filings else payload
    if not isinstance(columns, dict):
        raise DiscoveryError("submissions filings must be an object")
    accessions_raw = columns.get("accessionNumber")
    forms_raw = columns.get("form")
    filed_dates_raw = columns.get("filingDate")
    if not all(
        isinstance(value, list) for value in (accessions_raw, forms_raw, filed_dates_raw)
    ):
        raise DiscoveryError("accessionNumber, form, and filingDate must be lists")
    accessions = cast(list[object], accessions_raw)
    forms = cast(list[object], forms_raw)
    filed_dates = cast(list[object], filed_dates_raw)
    row_count = len(accessions)
    if len(forms) != row_count or len(filed_dates) != row_count:
        raise DiscoveryError("submissions columns have inconsistent lengths")
    for index in range(row_count):
        form = forms[index]
        if not isinstance(form, str):
            raise DiscoveryError(f"form must be text at row {index}")
        if form not in SUPPORTED_FORMS:
            continue
        accession = accessions[index]
        if not isinstance(accession, str) or not _ACCESSION_RE.fullmatch(accession):
            raise DiscoveryError(f"invalid accession at row {index}: {accession!r}")
        if accession[:10] != cik:
            raise DiscoveryError(
                f"accession CIK mismatch at row {index}: expected {cik}, got {accession[:10]}"
            )
        filed_date = parse_sec_date(filed_dates[index], field="filingDate")
        if filed_date is None:
            raise DiscoveryError(f"missing filingDate at row {index}")
        yield FilingRef(
            cik=cik,
            accession=accession,
            form=form,
            filed_date=filed_date,
            report_date=parse_sec_date(_column_value(columns, "reportDate", index), field="reportDate"),
            primary_document=_optional_text(
                _column_value(columns, "primaryDocument", index), field="primaryDocument"
            ),
            is_xbrl=_optional_bool(_column_value(columns, "isXBRL", index), field="isXBRL"),
            is_inline_xbrl=_optional_bool(
                _column_value(columns, "isInlineXBRL", index), field="isInlineXBRL"
            ),
            source=CompanySubmissionsAccessionProvider.source,
        )


def _column_value(columns: dict[str, Any], name: str, index: int) -> object:
    values = columns.get(name)
    if values is None:
        return None
    if not isinstance(values, list) or len(values) != len(columns["accessionNumber"]):
        raise DiscoveryError(f"invalid optional submissions column: {name}")
    return values[index]


def _decode_payload(payload: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("submissions payload is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise DiscoveryError("submissions payload must be a JSON object")
    return decoded
