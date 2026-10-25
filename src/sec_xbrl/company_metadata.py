"""Immutable SEC company, identifier, and SIC metadata publications.

The builder consumes cached inputs only.  SEC collection remains the concern of
``sec_xbrl.filing.company_discovery``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from sec_xbrl.filing.company_discovery import SUPPORTED_FORMS, canonicalize_cik

SCHEMA_VERSION = 1
MANIFEST_NAME = "company_metadata_manifest.json"
DATASET_NAMES = (
    "companies",
    "company_identifiers",
    "industry_classifications",
)
TEMPORAL_LIMITATION = (
    "SEC root metadata is observed current data. observed_at and cutoff do not establish "
    "when a name, identifier, or SIC classification became historically effective."
)
PEER_LIMITATION = "Exact SEC SIC is a coarse peer-candidate signal, not accounting equivalence."
_CIK_RE = re.compile(r"^\d{10}$")
_SIC_RE = re.compile(r"^\d{1,4}$")


class CompanyMetadataError(ValueError):
    """Raised when metadata cannot be published without weakening its contract."""


@dataclass(frozen=True, slots=True)
class SnapshotInput:
    """One immutable cached SEC submissions observation."""

    path: Path
    observed_at: datetime
    source: str = "sec_submissions"
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateInventoryInput:
    """Caller-cached SEC ticker/exchange candidate inventory."""

    path: Path
    observed_at: datetime
    source: str = "sec_company_tickers_exchange"
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class CompanyMetadataBuild:
    """Deterministic in-memory rows ready for immutable publication."""

    publication_id: str
    cutoff: str | None
    companies: tuple[Mapping[str, Any], ...]
    company_identifiers: tuple[Mapping[str, Any], ...]
    industry_classifications: tuple[Mapping[str, Any], ...]
    selected_inputs: tuple[Mapping[str, Any], ...]
    candidate_inventory: Mapping[str, Any] | None = None
    sic_reference: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PublishedCompanyMetadata:
    """Location and identity of a validated publication."""

    root: Path
    publication_id: str
    manifest_path: Path
    reused: bool = False


@dataclass(frozen=True, slots=True)
class UniverseFilter:
    """Conjunctive candidate-universe constraints."""

    exchanges: frozenset[str] = frozenset()
    forms: frozenset[str] = frozenset()
    sic_codes: frozenset[str] = frozenset()
    ciks: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CompanyCandidate:
    company_id: str
    cik: str
    name: str | None
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    sic_code: str | None
    sic_description: str | None
    metadata_status: str
    observed_at: str | None
    eligible: bool
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PeerCandidate:
    company_id: str
    cik: str
    name: str | None
    tickers: tuple[str, ...]
    sic_code: str
    sic_description: str | None
    limitation: str = PEER_LIMITATION


@dataclass(frozen=True, slots=True)
class _RootObservation:
    cik: str
    payload: Mapping[str, Any]
    trace: Mapping[str, Any]
    observed_at: datetime


def build_company_metadata(
    snapshot_paths: Iterable[Path | SnapshotInput],
    *,
    observed_at: datetime | None = None,
    cutoff: datetime | None = None,
    candidate_inventory: CandidateInventoryInput | None = None,
    sic_reference_path: Path | None = None,
) -> CompanyMetadataBuild:
    """Build deterministic company metadata rows from cached SEC JSON inputs.

    Bare paths require the keyword ``observed_at``.  Per-file observation times
    are supplied with :class:`SnapshotInput`.  No network access occurs.
    """

    cutoff_text = _timestamp(cutoff, field="cutoff") if cutoff is not None else None
    inputs = _normalize_snapshot_inputs(snapshot_paths, observed_at)
    observations: dict[str, list[_RootObservation]] = defaultdict(list)
    for item in inputs:
        if cutoff is not None and item.observed_at > cutoff:
            continue
        trace, payload = _read_traced_json(
            item.path,
            observed_at=item.observed_at,
            source=item.source,
            source_url=item.source_url,
        )
        cik = _payload_cik(payload, item.path)
        if not _is_root_payload(payload):
            continue
        observations[cik].append(_RootObservation(cik, payload, trace, item.observed_at))

    selected = {cik: _select_observation(cik, rows) for cik, rows in observations.items()}
    inventory_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    inventory_trace: Mapping[str, Any] | None = None
    if candidate_inventory is not None:
        _timestamp(candidate_inventory.observed_at, field="candidate_inventory.observed_at")
        if cutoff is None or candidate_inventory.observed_at <= cutoff:
            inventory_trace, raw_inventory = _read_traced_json(
                candidate_inventory.path,
                observed_at=candidate_inventory.observed_at,
                source=candidate_inventory.source,
                source_url=candidate_inventory.source_url,
            )
            inventory_rows = _candidate_trace_rows(
                _parse_candidate_inventory(raw_inventory), inventory_trace
            )

    sic_reference, sic_reference_trace = _read_sic_reference(sic_reference_path)
    all_ciks = sorted(set(selected) | set(inventory_rows))
    if not all_ciks:
        raise CompanyMetadataError("no company metadata candidates found at the requested cutoff")
    companies: list[dict[str, Any]] = []
    identifiers: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []
    ticker_owners: dict[tuple[str, str], str] = {}

    for cik in all_ciks:
        company_id = f"sec-cik:{cik}"
        observation = selected.get(cik)
        inventory = inventory_rows.get(cik, [])
        if observation is not None:
            payload = observation.payload
            trace = observation.trace
            name = _optional_text(payload.get("name"), field=f"{cik}.name")
            former_names = _former_names(payload.get("formerNames"), cik=cik)
            forms = _supported_form_inventory(payload, cik=cik)
            metadata_status = "ROOT_OBSERVED"
        else:
            payload = {}
            trace = _inventory_company_trace(inventory, cik=cik)
            name = _inventory_name(inventory, cik=cik)
            former_names = []
            forms = []
            metadata_status = "CANDIDATE_ONLY"

        companies.append(
            {
                "company_id": company_id,
                "cik": cik,
                "name": name,
                "former_names_json": _canonical_json(former_names),
                "supported_forms": forms,
                "metadata_status": metadata_status,
                **_trace_columns(trace),
            }
        )
        identifiers.append(
            {
                "company_id": company_id,
                "cik": cik,
                "identifier_type": "CIK",
                "identifier_value": cik,
                "raw_identifier_value": cik,
                "exchange": None,
                "ordinal": 0,
                **_trace_columns(trace),
            }
        )
        ticker_rows = _root_tickers(payload, cik=cik, trace=trace) if observation else []
        ticker_rows.extend(_inventory_tickers(inventory))
        seen_for_company: set[tuple[str, str]] = set()
        for ordinal, ticker_row in enumerate(ticker_rows, 1):
            raw_ticker = ticker_row["ticker"]
            ticker = raw_ticker.upper()
            exchange = ticker_row["exchange"]
            key = (ticker, _exchange_key(exchange))
            if key in seen_for_company:
                continue
            seen_for_company.add(key)
            owner = ticker_owners.get(key)
            if owner is not None and owner != cik:
                raise CompanyMetadataError(
                    f"ticker/exchange identity collision: {ticker}/{exchange} belongs to {owner} and {cik}"
                )
            ticker_owners[key] = cik
            identifiers.append(
                {
                    "company_id": company_id,
                    "cik": cik,
                    "identifier_type": "TICKER",
                    "identifier_value": ticker,
                    "raw_identifier_value": raw_ticker,
                    "exchange": exchange,
                    "ordinal": ordinal,
                    **_trace_columns(ticker_row["trace"]),
                }
            )

        sic = _parse_sic(payload.get("sic"), cik=cik) if observation else None
        sec_description = (
            _optional_text(payload.get("sicDescription"), field=f"{cik}.sicDescription")
            if observation
            else None
        )
        classifications.append(
            {
                "company_id": company_id,
                "cik": cik,
                "classification_system": "SEC_SIC",
                "sic_code": sic,
                "classification_status": "CLASSIFIED" if sic is not None else "NOT_CLASSIFIED",
                "sec_description": sec_description,
                "reference_title": sic_reference.get(sic) if sic is not None else None,
                "observed_at": trace["observed_at"],
                "source": trace["source"],
                "source_url": trace["source_url"],
                "source_path": trace["source_path"],
                "source_sha256": trace["source_sha256"],
                "reference_source_path": (
                    sic_reference_trace["source_path"] if sic_reference_trace else None
                ),
                "reference_source_sha256": (
                    sic_reference_trace["source_sha256"] if sic_reference_trace else None
                ),
            }
        )

    companies.sort(key=lambda row: row["cik"])
    identifiers.sort(
        key=lambda row: (row["cik"], 0 if row["identifier_type"] == "CIK" else 1, row["ordinal"])
    )
    classifications.sort(key=lambda row: row["cik"])
    selected_inputs = tuple(selected[cik].trace for cik in sorted(selected))
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "cutoff": cutoff_text,
        "companies": companies,
        "company_identifiers": identifiers,
        "industry_classifications": classifications,
        "selected_inputs": selected_inputs,
        "candidate_inventory": inventory_trace,
        "sic_reference": sic_reference_trace,
    }
    publication_id = _publication_id(identity_payload)
    return CompanyMetadataBuild(
        publication_id=publication_id,
        cutoff=cutoff_text,
        companies=tuple(companies),
        company_identifiers=tuple(identifiers),
        industry_classifications=tuple(classifications),
        selected_inputs=selected_inputs,
        candidate_inventory=inventory_trace,
        sic_reference=sic_reference_trace,
    )


def publish_company_metadata(
    build: CompanyMetadataBuild,
    destination: Path,
) -> PublishedCompanyMetadata:
    """Atomically publish, reuse an identical publication, or fail on collision."""

    if _publication_id(_build_identity_payload(build)) != build.publication_id:
        raise CompanyMetadataError("company metadata build was mutated after construction")
    destination = destination.resolve()
    if destination.exists():
        try:
            reader = CompanyMetadataReader(destination)
        except CompanyMetadataError as exc:
            raise CompanyMetadataError(f"immutable publication collision: {destination}") from exc
        if reader.publication_id != build.publication_id:
            raise CompanyMetadataError(f"immutable publication collision: {destination}")
        return PublishedCompanyMetadata(destination, build.publication_id, reader.manifest_path, True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        rows_by_name = {
            "companies": build.companies,
            "company_identifiers": build.company_identifiers,
            "industry_classifications": build.industry_classifications,
        }
        files: dict[str, dict[str, Any]] = {}
        for name in DATASET_NAMES:
            path = staging / f"{name}.parquet"
            frame = pl.DataFrame(
                list(rows_by_name[name]), schema=_dataset_schema(name), strict=False
            )
            frame.write_parquet(path)
            files[path.name] = {
                "sha256": _sha256(path),
                "size": path.stat().st_size,
                "rows": frame.height,
                "columns": frame.columns,
            }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "publication_id": build.publication_id,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cutoff": build.cutoff,
            "temporal_limitation": TEMPORAL_LIMITATION,
            "selected_inputs": list(build.selected_inputs),
            "candidate_inventory": build.candidate_inventory,
            "sic_reference": build.sic_reference,
            "files": files,
        }
        (staging / MANIFEST_NAME).write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
        staged_reader = CompanyMetadataReader(staging)
        if staged_reader.publication_id != build.publication_id:
            raise CompanyMetadataError("staged metadata identity does not match requested build")
        os.rename(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    reader = CompanyMetadataReader(destination)
    if reader.publication_id != build.publication_id:
        raise CompanyMetadataError("published metadata identity does not match requested build")
    return PublishedCompanyMetadata(destination, build.publication_id, reader.manifest_path)


class CompanyMetadataReader:
    """Defensive read-only access to an immutable metadata publication."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir() or root.is_symlink():
            raise CompanyMetadataError(f"metadata publication is not a real directory: {root}")
        self.manifest_path = self.root / MANIFEST_NAME
        expected_names = {MANIFEST_NAME, *(f"{name}.parquet" for name in DATASET_NAMES)}
        actual_names = {path.name for path in self.root.iterdir()}
        if actual_names != expected_names:
            raise CompanyMetadataError("metadata publication file set mismatch")
        if any(path.is_symlink() or not path.is_file() for path in self.root.iterdir()):
            raise CompanyMetadataError("metadata publication contains unsafe files")
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CompanyMetadataError("invalid company metadata manifest") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
            raise CompanyMetadataError("unsupported company metadata schema version")
        publication_id = manifest.get("publication_id")
        if not isinstance(publication_id, str) or not publication_id.startswith("company-metadata-"):
            raise CompanyMetadataError("invalid company metadata publication ID")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != {
            f"{name}.parquet" for name in DATASET_NAMES
        }:
            raise CompanyMetadataError("invalid company metadata file manifest")
        frames: dict[str, pl.DataFrame] = {}
        for name in DATASET_NAMES:
            filename = f"{name}.parquet"
            path = self.root / filename
            metadata = files[filename]
            if not isinstance(metadata, dict):
                raise CompanyMetadataError(f"invalid manifest entry for {filename}")
            if metadata.get("sha256") != _sha256(path) or metadata.get("size") != path.stat().st_size:
                raise CompanyMetadataError(f"metadata file hash mismatch: {filename}")
            try:
                frame = pl.read_parquet(path)
            except Exception as exc:
                raise CompanyMetadataError(f"invalid Parquet dataset: {filename}") from exc
            expected_schema = pl.Schema(_dataset_schema(name))
            expected_columns = expected_schema.names()
            if frame.schema != expected_schema or metadata.get("columns") != expected_columns:
                raise CompanyMetadataError(f"metadata dataset schema mismatch: {filename}")
            if metadata.get("rows") != frame.height:
                raise CompanyMetadataError(f"metadata dataset row count mismatch: {filename}")
            frames[name] = frame
        self.manifest = manifest
        self.publication_id = publication_id
        self._frames = frames
        self._validate_identity()
        identity_payload = {
            "schema_version": SCHEMA_VERSION,
            "cutoff": manifest.get("cutoff"),
            "companies": frames["companies"].to_dicts(),
            "company_identifiers": frames["company_identifiers"].to_dicts(),
            "industry_classifications": frames["industry_classifications"].to_dicts(),
            "selected_inputs": manifest.get("selected_inputs"),
            "candidate_inventory": manifest.get("candidate_inventory"),
            "sic_reference": manifest.get("sic_reference"),
        }
        if _publication_id(identity_payload) != publication_id:
            raise CompanyMetadataError("company metadata publication identity mismatch")

    def list_companies(
        self, universe: UniverseFilter | None = None
    ) -> tuple[CompanyCandidate, ...]:
        """Return every candidate with eligibility and explicit exclusion reasons."""

        universe = universe or UniverseFilter()
        ciks = frozenset(canonicalize_cik(cik) for cik in universe.ciks)
        sic_codes = frozenset(_parse_sic(code, cik="filter") for code in universe.sic_codes)
        unsupported = universe.forms - SUPPORTED_FORMS
        if unsupported:
            raise CompanyMetadataError(f"unsupported form filters: {sorted(unsupported)}")
        identifier_rows = self._frames["company_identifiers"].to_dicts()
        by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in identifier_rows:
            by_company[row["company_id"]].append(row)
        classifications = {
            row["company_id"]: row
            for row in self._frames["industry_classifications"].to_dicts()
        }
        results: list[CompanyCandidate] = []
        known_ciks: set[str] = set()
        for row in self._frames["companies"].to_dicts():
            known_ciks.add(row["cik"])
            identifier_group = by_company[row["company_id"]]
            ticker_rows = [item for item in identifier_group if item["identifier_type"] == "TICKER"]
            tickers = tuple(item["identifier_value"] for item in ticker_rows)
            exchanges = tuple(
                dict.fromkeys(
                    item["exchange"] for item in ticker_rows if item["exchange"] is not None
                )
            )
            classification = classifications[row["company_id"]]
            reasons: list[str] = []
            if row["metadata_status"] != "ROOT_OBSERVED":
                reasons.append("ROOT_METADATA_UNAVAILABLE")
            if ciks and row["cik"] not in ciks:
                reasons.append("CIK_EXCLUDED")
            if universe.exchanges:
                if not exchanges:
                    reasons.append("EXCHANGE_UNAVAILABLE")
                elif not any(exchange in universe.exchanges for exchange in exchanges):
                    reasons.append("EXCHANGE_EXCLUDED")
            forms = set(row["supported_forms"])
            if universe.forms:
                if not forms:
                    reasons.append("FORM_INVENTORY_UNAVAILABLE")
                elif not universe.forms.issubset(forms):
                    reasons.append("FORM_EXCLUDED")
            if sic_codes:
                if classification["sic_code"] is None:
                    reasons.append("INDUSTRY_NOT_CLASSIFIED")
                elif classification["sic_code"] not in sic_codes:
                    reasons.append("INDUSTRY_EXCLUDED")
            results.append(
                CompanyCandidate(
                    company_id=row["company_id"],
                    cik=row["cik"],
                    name=row["name"],
                    tickers=tickers,
                    exchanges=exchanges,
                    sic_code=classification["sic_code"],
                    sic_description=classification["sec_description"],
                    metadata_status=row["metadata_status"],
                    observed_at=row["observed_at"],
                    eligible=not reasons,
                    exclusion_reasons=tuple(reasons),
                )
            )
        for cik in sorted(ciks - known_ciks):
            results.append(
                CompanyCandidate(
                    company_id=f"sec-cik:{cik}",
                    cik=cik,
                    name=None,
                    tickers=(),
                    exchanges=(),
                    sic_code=None,
                    sic_description=None,
                    metadata_status="UNAVAILABLE",
                    observed_at=None,
                    eligible=False,
                    exclusion_reasons=("METADATA_UNAVAILABLE",),
                )
            )
        return tuple(sorted(results, key=lambda row: row.cik))

    def peer_candidates(self, cik: str | int) -> tuple[PeerCandidate, ...]:
        """Return exact-SIC candidates without asserting accounting equivalence."""

        target = canonicalize_cik(cik)
        companies = {row.cik: row for row in self.list_companies()}
        target_row = companies.get(target)
        if target_row is None or target_row.sic_code is None:
            return ()
        return tuple(
            PeerCandidate(
                company_id=row.company_id,
                cik=row.cik,
                name=row.name,
                tickers=row.tickers,
                sic_code=row.sic_code,
                sic_description=row.sic_description,
            )
            for row in companies.values()
            if row.cik != target and row.sic_code == target_row.sic_code
        )

    def _validate_identity(self) -> None:
        companies = self._frames["companies"].to_dicts()
        company_ids = [row["company_id"] for row in companies]
        ciks = [row["cik"] for row in companies]
        if len(company_ids) != len(set(company_ids)) or len(ciks) != len(set(ciks)):
            raise CompanyMetadataError("duplicate company identity in publication")
        if any(
            not _CIK_RE.fullmatch(row["cik"])
            or row["company_id"] != f"sec-cik:{row['cik']}"
            or row["metadata_status"] not in {"ROOT_OBSERVED", "CANDIDATE_ONLY"}
            for row in companies
        ):
            raise CompanyMetadataError("invalid company identity in publication")
        expected_ids = set(company_ids)
        for name in ("company_identifiers", "industry_classifications"):
            rows = self._frames[name].to_dicts()
            if any(row["company_id"] not in expected_ids for row in rows):
                raise CompanyMetadataError(f"orphan company identity in {name}")
            company_ciks = {row["company_id"]: row["cik"] for row in companies}
            if any(company_ciks[row["company_id"]] != row["cik"] for row in rows):
                raise CompanyMetadataError(f"company CIK mismatch in {name}")
        identifier_rows = self._frames["company_identifiers"].to_dicts()
        identifier_keys = [
            (
                row["company_id"],
                row["identifier_type"],
                row["identifier_value"],
                row["exchange"],
            )
            for row in identifier_rows
        ]
        if len(identifier_keys) != len(set(identifier_keys)):
            raise CompanyMetadataError("duplicate company identifier in publication")
        cik_counts: dict[str, int] = defaultdict(int)
        ticker_owners: dict[tuple[str, str], str] = {}
        for row in identifier_rows:
            if row["identifier_type"] == "CIK":
                cik_counts[row["company_id"]] += 1
                if row["identifier_value"] != row["cik"] or row["exchange"] is not None:
                    raise CompanyMetadataError("invalid CIK identifier in publication")
            elif row["identifier_type"] == "TICKER":
                if not row["identifier_value"]:
                    raise CompanyMetadataError("invalid ticker identifier in publication")
                key = (row["identifier_value"].upper(), _exchange_key(row["exchange"]))
                owner = ticker_owners.setdefault(key, row["company_id"])
                if owner != row["company_id"]:
                    raise CompanyMetadataError("ticker/exchange identity collision in publication")
            else:
                raise CompanyMetadataError("unsupported identifier type in publication")
        if cik_counts != {company_id: 1 for company_id in expected_ids}:
            raise CompanyMetadataError("CIK identifier grain mismatch")
        industry_ids = [
            row["company_id"] for row in self._frames["industry_classifications"].to_dicts()
        ]
        if len(industry_ids) != len(set(industry_ids)) or set(industry_ids) != expected_ids:
            raise CompanyMetadataError("industry classification grain mismatch")
        for row in self._frames["industry_classifications"].to_dicts():
            if row["classification_system"] != "SEC_SIC":
                raise CompanyMetadataError("unsupported industry classification system")
            expected_status = "CLASSIFIED" if row["sic_code"] is not None else "NOT_CLASSIFIED"
            if row["classification_status"] != expected_status:
                raise CompanyMetadataError("industry classification status mismatch")
            if row["sic_code"] is not None and _parse_sic(row["sic_code"], cik=row["cik"]) != row["sic_code"]:
                raise CompanyMetadataError("non-canonical SIC in publication")


def _normalize_snapshot_inputs(
    inputs: Iterable[Path | SnapshotInput], common_observed_at: datetime | None
) -> tuple[SnapshotInput, ...]:
    normalized: list[SnapshotInput] = []
    for value in inputs:
        if isinstance(value, SnapshotInput):
            item = value
        else:
            if common_observed_at is None:
                raise CompanyMetadataError("bare snapshot paths require observed_at")
            item = SnapshotInput(Path(value), common_observed_at)
        _timestamp(item.observed_at, field=f"observed_at for {item.path}")
        if not item.source.strip():
            raise CompanyMetadataError("snapshot source must be non-empty")
        normalized.append(item)
    if not normalized:
        raise CompanyMetadataError("at least one cached snapshot is required")
    return tuple(normalized)


def _read_traced_json(
    path: Path, *, observed_at: datetime, source: str, source_url: str | None
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    try:
        payload_bytes = path.read_bytes()
        payload = json.loads(payload_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompanyMetadataError(f"invalid cached JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise CompanyMetadataError(f"cached JSON input must be an object: {path}")
    trace = {
        "observed_at": _timestamp(observed_at, field=f"observed_at for {path}"),
        "source": source,
        "source_url": source_url,
        "source_path": str(path.resolve()),
        "source_sha256": hashlib.sha256(payload_bytes).hexdigest(),
    }
    return trace, payload


def _payload_cik(payload: Mapping[str, Any], path: Path) -> str:
    payload_cik = payload.get("cik")
    parent_cik = path.parent.name if _CIK_RE.fullmatch(path.parent.name) else None
    if payload_cik is None:
        if parent_cik is None:
            raise CompanyMetadataError(f"metadata input lacks CIK: {path}")
        return parent_cik
    try:
        cik = canonicalize_cik(payload_cik)
    except ValueError as exc:
        raise CompanyMetadataError(f"invalid CIK in metadata input: {path}") from exc
    if parent_cik is not None and cik != parent_cik:
        raise CompanyMetadataError(
            f"metadata CIK mismatch: payload {cik}, directory {parent_cik}"
        )
    return cik


def _is_root_payload(payload: Mapping[str, Any]) -> bool:
    return bool(
        {"name", "tickers", "exchanges", "sic", "sicDescription", "formerNames"}
        & payload.keys()
    )


def _select_observation(cik: str, rows: Sequence[_RootObservation]) -> _RootObservation:
    latest_at = max(row.observed_at for row in rows)
    latest = [row for row in rows if row.observed_at == latest_at]
    hashes = {row.trace["source_sha256"] for row in latest}
    if len(hashes) != 1:
        raise CompanyMetadataError(
            f"ambiguous competing root snapshots for {cik} at {_timestamp(latest_at, field='observed_at')}"
        )
    provenance_by_path: dict[str, set[tuple[str, str | None]]] = defaultdict(set)
    for row in latest:
        provenance_by_path[row.trace["source_path"]].add(
            (row.trace["source"], row.trace["source_url"])
        )
    if any(len(provenance) > 1 for provenance in provenance_by_path.values()):
        raise CompanyMetadataError(
            f"conflicting provenance for identical root snapshot {cik} at "
            f"{_timestamp(latest_at, field='observed_at')}"
        )
    return min(
        latest,
        key=lambda row: (
            row.trace["source_path"],
            row.trace["source"],
            row.trace["source_url"] or "",
        ),
    )


def _parse_candidate_inventory(payload: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    if isinstance(payload.get("fields"), list) and isinstance(payload.get("data"), list):
        fields = payload["fields"]
        if not all(isinstance(field, str) for field in fields):
            raise CompanyMetadataError("candidate inventory fields must be text")
        raw_rows = []
        for index, values in enumerate(payload["data"]):
            if not isinstance(values, list) or len(values) != len(fields):
                raise CompanyMetadataError(f"candidate inventory row {index} has invalid width")
            raw_rows.append(dict(zip(fields, values, strict=True)))
    elif isinstance(payload.get("data"), list) and all(
        isinstance(row, dict) for row in payload["data"]
    ):
        raw_rows = payload["data"]
    else:
        raise CompanyMetadataError("unsupported candidate inventory shape")
    for index, row in enumerate(raw_rows):
        assert isinstance(row, dict)
        try:
            cik = canonicalize_cik(row.get("cik"))
        except ValueError as exc:
            raise CompanyMetadataError(f"invalid candidate inventory CIK at row {index}") from exc
        name = _optional_text(row.get("name"), field=f"candidate[{index}].name")
        ticker = _required_text(row.get("ticker"), field=f"candidate[{index}].ticker")
        exchange = _optional_text(row.get("exchange"), field=f"candidate[{index}].exchange")
        identity = (ticker.upper(), _exchange_key(exchange))
        if any(
            (existing["ticker"].upper(), _exchange_key(existing["exchange"])) == identity
            for existing in result[cik]
        ):
            raise CompanyMetadataError(
                f"duplicate candidate ticker/exchange identity for {cik}: {ticker}/{exchange}"
            )
        result[cik].append({"name": name, "ticker": ticker, "exchange": exchange})
    return result


def _inventory_company_trace(
    rows: Sequence[Mapping[str, Any]], *, cik: str
) -> Mapping[str, Any]:
    if not rows or "trace" not in rows[0]:
        raise CompanyMetadataError(f"candidate-only company lacks provenance: {cik}")
    return rows[0]["trace"]


def _inventory_name(rows: Sequence[Mapping[str, Any]], *, cik: str) -> str | None:
    names = {row["name"] for row in rows if row["name"] is not None}
    if len(names) > 1:
        raise CompanyMetadataError(f"candidate inventory has competing names for {cik}")
    return next(iter(names), None)


def _inventory_tickers(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"ticker": row["ticker"], "exchange": row["exchange"], "trace": row["trace"]}
        for row in rows
    ]


def _root_tickers(
    payload: Mapping[str, Any], *, cik: str, trace: Mapping[str, Any]
) -> list[dict[str, Any]]:
    tickers = payload.get("tickers", [])
    exchanges = payload.get("exchanges", [])
    if not isinstance(tickers, list) or not isinstance(exchanges, list):
        raise CompanyMetadataError(f"ticker/exchange arrays must be lists for {cik}")
    if len(tickers) != len(exchanges):
        raise CompanyMetadataError(f"ticker/exchange arrays have different lengths for {cik}")
    rows = []
    seen: set[tuple[str, str]] = set()
    for index, (ticker, exchange) in enumerate(zip(tickers, exchanges, strict=True)):
        parsed_ticker = _required_text(ticker, field=f"{cik}.tickers[{index}]")
        parsed_exchange = _optional_text(exchange, field=f"{cik}.exchanges[{index}]")
        key = (parsed_ticker.upper(), _exchange_key(parsed_exchange))
        if key in seen:
            raise CompanyMetadataError(f"duplicate ticker/exchange identity for {cik}: {key[0]}")
        seen.add(key)
        rows.append({"ticker": parsed_ticker, "exchange": parsed_exchange, "trace": trace})
    return rows


def _supported_form_inventory(payload: Mapping[str, Any], *, cik: str) -> list[str]:
    filings = payload.get("filings")
    if filings is None:
        return []
    if not isinstance(filings, dict):
        raise CompanyMetadataError(f"filings must be an object for {cik}")
    recent = filings.get("recent", {})
    if not isinstance(recent, dict):
        raise CompanyMetadataError(f"filings.recent must be an object for {cik}")
    forms = recent.get("form", [])
    if not isinstance(forms, list) or not all(isinstance(form, str) for form in forms):
        raise CompanyMetadataError(f"filings.recent.form must be a text list for {cik}")
    return sorted(set(forms) & SUPPORTED_FORMS)


def _former_names(value: object, *, cik: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CompanyMetadataError(f"formerNames must be a list for {cik}")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CompanyMetadataError(f"formerNames is not JSON-safe for {cik}") from exc
    return value


def _parse_sic(value: object, *, cik: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise CompanyMetadataError(f"invalid SIC for {cik}: {value!r}")
    text = str(value).strip()
    if not _SIC_RE.fullmatch(text):
        raise CompanyMetadataError(f"invalid SIC for {cik}: {value!r}")
    return text.zfill(4)


def _read_sic_reference(
    path: Path | None,
) -> tuple[dict[str, str], Mapping[str, Any] | None]:
    if path is None:
        return {}, None
    try:
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompanyMetadataError(f"invalid cached SIC reference: {path}") from exc
    result: dict[str, str] = {}
    if isinstance(payload, dict):
        rows = [{"sic": key, "title": value} for key, value in payload.items()]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise CompanyMetadataError("SIC reference must be an object or row list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CompanyMetadataError(f"invalid SIC reference row {index}")
        code = _parse_sic(row.get("sic", row.get("code")), cik="SIC reference")
        assert code is not None
        title = _required_text(row.get("title"), field=f"SIC reference[{index}].title")
        if code in result and result[code] != title:
            raise CompanyMetadataError(f"conflicting SIC reference title for {code}")
        result[code] = title
    trace = {
        "source_path": str(path.resolve()),
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    return result, trace


def _candidate_trace_rows(
    rows: dict[str, list[Mapping[str, Any]]], trace: Mapping[str, Any]
) -> dict[str, list[Mapping[str, Any]]]:
    return {
        cik: [dict(row, trace=trace) for row in company_rows]
        for cik, company_rows in rows.items()
    }


def _timestamp(value: datetime, *, field: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CompanyMetadataError(f"{field} must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _required_text(value, field=field)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompanyMetadataError(f"{field} must be non-empty text")
    return value.strip()


def _exchange_key(value: str | None) -> str:
    """Return one collision key for both known and unavailable exchanges."""

    return value.casefold() if value is not None else ""


def _trace_columns(trace: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observed_at": trace["observed_at"],
        "source": trace["source"],
        "source_url": trace["source_url"],
        "source_path": trace["source_path"],
        "source_sha256": trace["source_sha256"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _publication_id(identity_payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(identity_payload).encode()).hexdigest()
    return f"company-metadata-{digest[:24]}"


def _build_identity_payload(build: CompanyMetadataBuild) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "cutoff": build.cutoff,
        "companies": build.companies,
        "company_identifiers": build.company_identifiers,
        "industry_classifications": build.industry_classifications,
        "selected_inputs": build.selected_inputs,
        "candidate_inventory": build.candidate_inventory,
        "sic_reference": build.sic_reference,
    }


def _dataset_schema(name: str) -> Mapping[str, pl.DataType]:
    provenance = {
        "observed_at": pl.String,
        "source": pl.String,
        "source_url": pl.String,
        "source_path": pl.String,
        "source_sha256": pl.String,
    }
    if name == "companies":
        return {
            "company_id": pl.String,
            "cik": pl.String,
            "name": pl.String,
            "former_names_json": pl.String,
            "supported_forms": pl.List(pl.String),
            "metadata_status": pl.String,
            **provenance,
        }
    if name == "company_identifiers":
        return {
            "company_id": pl.String,
            "cik": pl.String,
            "identifier_type": pl.String,
            "identifier_value": pl.String,
            "raw_identifier_value": pl.String,
            "exchange": pl.String,
            "ordinal": pl.Int64,
            **provenance,
        }
    if name == "industry_classifications":
        return {
            "company_id": pl.String,
            "cik": pl.String,
            "classification_system": pl.String,
            "sic_code": pl.String,
            "classification_status": pl.String,
            "sec_description": pl.String,
            "reference_title": pl.String,
            "observed_at": pl.String,
            "source": pl.String,
            "source_url": pl.String,
            "source_path": pl.String,
            "source_sha256": pl.String,
            "reference_source_path": pl.String,
            "reference_source_sha256": pl.String,
        }
    raise AssertionError(name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build and publish cached SEC company metadata")
    build.add_argument("snapshots", nargs="+", type=Path)
    build.add_argument("--observed-at", required=True, type=datetime.fromisoformat)
    build.add_argument("--cutoff", type=datetime.fromisoformat)
    build.add_argument("--candidate-inventory", type=Path)
    build.add_argument("--candidate-observed-at", type=datetime.fromisoformat)
    build.add_argument("--sic-reference", type=Path)
    build.add_argument("--destination", required=True, type=Path)
    query = commands.add_parser("query", help="evaluate a universe filter")
    query.add_argument("publication", type=Path)
    query.add_argument("--exchange", action="append", default=[])
    query.add_argument("--form", action="append", default=[])
    query.add_argument("--sic", action="append", default=[])
    query.add_argument("--cik", action="append", default=[])
    peers = commands.add_parser("peer-candidates", help="list exact-SIC peer candidates")
    peers.add_argument("publication", type=Path)
    peers.add_argument("cik")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the cached-input metadata build/query CLI."""

    args = _build_parser().parse_args(argv)
    if args.command == "build":
        if bool(args.candidate_inventory) != bool(args.candidate_observed_at):
            raise CompanyMetadataError(
                "--candidate-inventory and --candidate-observed-at must be supplied together"
            )
        inventory = (
            CandidateInventoryInput(args.candidate_inventory, args.candidate_observed_at)
            if args.candidate_inventory
            else None
        )
        result = build_company_metadata(
            args.snapshots,
            observed_at=args.observed_at,
            cutoff=args.cutoff,
            candidate_inventory=inventory,
            sic_reference_path=args.sic_reference,
        )
        published = publish_company_metadata(result, args.destination)
        print(_canonical_json(asdict(published) | {"root": str(published.root), "manifest_path": str(published.manifest_path)}))
        return 0
    reader = CompanyMetadataReader(args.publication)
    if args.command == "query":
        rows = reader.list_companies(
            UniverseFilter(
                exchanges=frozenset(args.exchange),
                forms=frozenset(args.form),
                sic_codes=frozenset(args.sic),
                ciks=frozenset(args.cik),
            )
        )
    else:
        rows = reader.peer_candidates(args.cik)
    for row in rows:
        print(_canonical_json(asdict(row)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
