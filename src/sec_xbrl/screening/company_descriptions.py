"""Governed plain-text company-description preparation and consumption."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import re
import shutil
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from socket import inet_aton
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from sec_xbrl.screening.common import (
    atomic_replace,
    canonical_json,
    contained_file,
    digest_value,
    read_json,
    real_directory,
    regular_file,
    require_cik,
    require_string,
    require_ticker,
    safe_new_destination,
    sha256_file,
    write_json,
)
from sec_xbrl.screening.dataset import MANIFEST as DATASET_MANIFEST
from sec_xbrl.screening.dataset_v2 import open_screening_dataset

PLAN_VERSION = "company-description-plan-v1"
VERSION = "company-description-publication-v1"
MANIFEST = "company_description_manifest.json"
RECORDS = "company_description_records.json"
MODES = {"PROVIDED_TEXT", "AUTHORIZED_FETCH"}
FIXTURE_KINDS = {"ACTUAL_AUTHORIZED", "SYNTHETIC_DESCRIPTION_FIXTURE"}
MAX_SOURCE_BYTES = 512 * 1024
MAX_TEXT_CHARS = 40_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HANGUL_RE = re.compile(r"[가-힣]")
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd",
    "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li",
    "main", "p", "section", "table", "tbody", "td", "th", "thead", "tr", "ul", "ol",
}
IGNORED_TAGS = {"script", "style", "noscript", "svg", "template"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass(frozen=True, slots=True)
class CompanyDescriptionPublication:
    root: Path
    publication_id: str
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: int
    content_type: str
    body: bytes
    final_url: str


FetchFunction = Callable[[str, float, int], FetchResult]


def review_company_description_plan(
    plan_path: Path | str,
    dataset_root: Path | str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Validate a plan without network or destination writes."""
    plan_file = regular_file(Path(plan_path), "company-description source plan")
    dataset = open_screening_dataset(dataset_root)
    plan = _validate_plan(read_json(plan_file, "company-description source plan"), plan_file, dataset)
    checked_on = today or _utc_today()
    rows = []
    for entry in plan["entries"]:
        try:
            _preflight_entry(plan, entry, checked_on)
            state, reason = ("UNAVAILABLE", entry.get("unavailable_reason")) if entry.get("status") == "UNAVAILABLE" else ("READY", None)
        except (PermissionError, TypeError, ValueError) as exc:
            state, reason = "BLOCKED", str(exc)
        rows.append({"cik": entry["cik"], "ticker": entry["ticker"], "state": state, "reason": reason})
    return {
        "schema_version": PLAN_VERSION,
        "dataset_id": plan["dataset_id"],
        "acquisition_mode": plan["acquisition_mode"],
        "network_performed": False,
        "ready_count": sum(row["state"] == "READY" for row in rows),
        "unavailable_count": sum(row["state"] == "UNAVAILABLE" for row in rows),
        "blocked_count": sum(row["state"] == "BLOCKED" for row in rows),
        "entries": rows,
    }


def publish_company_descriptions(
    plan_path: Path | str,
    dataset_root: Path | str,
    destination: Path | str,
    *,
    today: date | None = None,
    fetcher: FetchFunction | None = None,
) -> CompanyDescriptionPublication:
    """Publish Korean plain text from supplied files or an explicitly authorized fetch."""
    plan_file = regular_file(Path(plan_path), "company-description source plan")
    dataset = open_screening_dataset(dataset_root)
    plan = _validate_plan(read_json(plan_file, "company-description source plan"), plan_file, dataset)
    checked_on = today or _utc_today()
    review = review_company_description_plan(plan_file, dataset.root, today=checked_on)
    if review["blocked_count"]:
        problems = "; ".join(
            f"{row['cik']}: {row['reason']}" for row in review["entries"] if row["state"] == "BLOCKED"
        )
        raise PermissionError(f"company-description plan is blocked before network I/O: {problems}")
    destination_path = safe_new_destination(Path(destination), "company-description publication")

    records: list[dict[str, Any]] = []
    for entry in plan["entries"]:
        records.append(
            _record_from_entry(plan, entry, checked_on, fetcher or _fetch_once)
        )
    records.sort(key=lambda row: row["cik"])
    records_sha = hashlib.sha256((canonical_json(records) + "\n").encode("utf-8")).hexdigest()
    identity = {
        "schema_version": VERSION,
        "dataset_id": plan["dataset_id"],
        "dataset_publication_id": plan["dataset_publication_id"],
        "dataset_manifest_sha256": plan["dataset_manifest_sha256"],
        "fixture_kind": plan["fixture_kind"],
        "dataset_fixture_kind": plan["dataset_fixture_kind"],
        "acquisition_mode": plan["acquisition_mode"],
        "plan_sha256": sha256_file(plan_file),
        "company_count": len(records),
        "configured_companies": [{"cik": row["cik"], "ticker": row["ticker"]} for row in records],
        "records_sha256": records_sha,
    }
    publication_id = "company-descriptions-" + digest_value(identity)[:24]
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / RECORDS, records)
        files = {
            RECORDS: {
                "sha256": sha256_file(staging / RECORDS),
                "size": (staging / RECORDS).stat().st_size,
            }
        }
        manifest = {
            **identity,
            "publication_id": publication_id,
            "plan_path": str(plan_file),
            "plan": plan,
            "files": files,
            "expiry_behavior": "HIDE_TEXT_AND_SOURCE_LINK_AT_PROJECTION_AFTER_RIGHTS_EXPIRY",
        }
        write_json(staging / MANIFEST, manifest)
        atomic_replace(staging, destination_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    manifest_path = destination_path / MANIFEST
    return CompanyDescriptionPublication(
        destination_path,
        publication_id,
        manifest_path,
        sha256_file(manifest_path),
    )


class CompanyDescriptionReader:
    """Read a manifest-digest-pinned description publication."""

    def __init__(
        self,
        root: Path | str,
        expected_manifest_sha256: str,
        dataset: Any,
        *,
        today: date | None = None,
    ) -> None:
        self.root = real_directory(Path(root), "company-description publication")
        self.expected_manifest_sha256 = _require_sha256(expected_manifest_sha256, "expected manifest SHA-256")
        self.dataset = dataset
        self.manifest_path = regular_file(self.root / MANIFEST, "company-description manifest")
        self.manifest = read_json(self.manifest_path, "company-description manifest")
        self.records = self._read_records()
        self.dataset_id = self.manifest.get("dataset_id")
        self.publication_id = self.manifest.get("publication_id")
        self.verify_all(today=today)

    def _read_records(self) -> list[dict[str, Any]]:
        value = read_json(contained_file(self.root, RECORDS, "description records"), RECORDS)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise TypeError("company description records must be object rows")
        return value

    def verify_all(self, *, today: date | None = None) -> dict[str, Any]:
        if sha256_file(self.manifest_path) != self.expected_manifest_sha256:
            raise ValueError("company-description manifest differs from pinned digest")
        manifest = read_json(self.manifest_path, "company-description manifest")
        if manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported company-description publication")
        if set(manifest.get("files", {})) != {RECORDS}:
            raise ValueError("company-description declared file set changed")
        record_path = contained_file(self.root, RECORDS, "description records")
        declared = manifest["files"][RECORDS]
        if sha256_file(record_path) != declared.get("sha256") or record_path.stat().st_size != declared.get("size"):
            raise ValueError("company-description records changed")
        current_records = self._read_records()
        if current_records != self.records:
            raise ValueError("company-description cached records differ from publication")
        _require_sha256(manifest.get("plan_sha256"), "source plan SHA-256")
        _validate_embedded_plan(manifest.get("plan"), manifest, current_records, self.dataset)
        dataset_manifest = regular_file(self.dataset.root / DATASET_MANIFEST, "screening dataset manifest")
        if (
            manifest.get("dataset_id") != self.dataset.manifest.get("dataset_id")
            or manifest.get("dataset_publication_id") != self.dataset.publication_id
            or manifest.get("dataset_manifest_sha256") != sha256_file(dataset_manifest)
        ):
            raise ValueError("company-description financial dataset binding changed")
        checked_on = today or _utc_today()
        _validate_records(manifest, current_records, checked_on)
        identity = {
            key: manifest.get(key)
            for key in (
                "schema_version", "dataset_id", "dataset_publication_id",
                "dataset_manifest_sha256", "fixture_kind", "dataset_fixture_kind",
                "acquisition_mode",
                "plan_sha256", "company_count", "configured_companies", "records_sha256",
            )
        }
        if manifest.get("records_sha256") != hashlib.sha256(record_path.read_bytes()).hexdigest():
            raise ValueError("company-description canonical record digest changed")
        if manifest.get("publication_id") != "company-descriptions-" + digest_value(identity)[:24]:
            raise ValueError("company-description publication identity changed")
        return {
            "publication_id": self.publication_id,
            "dataset_id": self.dataset_id,
            "company_count": len(self.records),
            "available_count": sum(
                row["status"] == "AVAILABLE" and _rights_current(row, checked_on)
                for row in self.records
            ),
            "fixture_kind": manifest["fixture_kind"],
            "rights_expired_count": sum(
                row["status"] == "AVAILABLE" and not _rights_current(row, checked_on)
                for row in self.records
            ),
        }

    def company(self, cik: str, *, today: date | None = None) -> dict[str, Any]:
        cik = require_cik(cik)
        rows = [row for row in self.records if row["cik"] == cik]
        if len(rows) != 1:
            raise ValueError("company description is not uniquely prepared")
        row = copy.deepcopy(rows[0])
        if row["status"] == "AVAILABLE" and not _rights_current(row, today or _utc_today()):
            row.update(
                status="RIGHTS_EXPIRED",
                text=None,
                profile_url=None,
                reason="설명 이용 권리의 유효기간이 지나 다시 검토해야 합니다.",
            )
        return row


def _validate_plan(value: Any, plan_file: Path, dataset: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != PLAN_VERSION:
        raise ValueError("unsupported company-description plan")
    mode = require_string(value.get("acquisition_mode"), "acquisition_mode")
    if mode not in MODES:
        raise ValueError("unsupported description acquisition mode")
    fixture_kind = require_string(value.get("fixture_kind"), "fixture_kind")
    if fixture_kind not in FIXTURE_KINDS:
        raise ValueError("unsupported description fixture kind")
    dataset_manifest = regular_file(dataset.root / DATASET_MANIFEST, "screening dataset manifest")
    dataset_sha = _require_sha256(value.get("dataset_manifest_sha256"), "dataset_manifest_sha256")
    if (
        value.get("dataset_id") != dataset.manifest.get("dataset_id")
        or value.get("dataset_publication_id") != dataset.publication_id
        or dataset_sha != sha256_file(dataset_manifest)
    ):
        raise ValueError("description plan differs from verified financial dataset")
    allowed_hosts_value = value.get("allowed_hosts")
    if not isinstance(allowed_hosts_value, list) or not allowed_hosts_value:
        raise ValueError("description plan requires allowed_hosts")
    allowed_hosts = sorted({_validate_host(item) for item in allowed_hosts_value})
    input_root_value = require_string(value.get("input_root", "."), "input_root")
    input_root_path = Path(input_root_value)
    if not input_root_path.is_absolute():
        input_root_path = plan_file.parent / input_root_path
    input_root = real_directory(input_root_path, "description input root")
    entries_value = value.get("entries")
    if not isinstance(entries_value, list) or not entries_value:
        raise ValueError("description plan requires entries")
    entries = [_normalize_entry(row, mode, allowed_hosts) for row in entries_value]
    entries.sort(key=lambda row: row["cik"])
    if len({row["cik"] for row in entries}) != len(entries):
        raise ValueError("duplicate company description CIK")
    expected = sorted(
        ({"cik": row["cik"], "ticker": row["ticker"]} for row in dataset.companies),
        key=lambda row: row["cik"],
    )
    actual = [{"cik": row["cik"], "ticker": row["ticker"]} for row in entries]
    if actual != expected:
        raise ValueError("description plan company membership differs from financial dataset")
    return {
        "schema_version": PLAN_VERSION,
        "dataset_id": value["dataset_id"],
        "dataset_publication_id": value["dataset_publication_id"],
        "dataset_manifest_sha256": dataset_sha,
        "fixture_kind": fixture_kind,
        "dataset_fixture_kind": dataset.manifest.get("fixture_kind"),
        "acquisition_mode": mode,
        "input_root": str(input_root),
        "allowed_hosts": allowed_hosts,
        "entries": entries,
    }


def _normalize_entry(value: Any, mode: str, allowed_hosts: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("company description entry must be an object")
    status = value.get("status", "AVAILABLE")
    if status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ValueError("unsupported company description status")
    entry: dict[str, Any] = {
        "cik": require_cik(value.get("cik")),
        "ticker": require_ticker(value.get("ticker")),
        "status": status,
    }
    if status == "UNAVAILABLE":
        entry.update(
            provider_id=_optional_string(value.get("provider_id"), "provider_id"),
            provider_name=_optional_string(value.get("provider_name"), "provider_name"),
            profile_url=(
                _validate_url(value.get("profile_url"), allowed_hosts)
                if value.get("profile_url") is not None
                else None
            ),
            locale=_optional_string(value.get("locale"), "locale"),
            checked_at=(
                _timestamp(value.get("checked_at"), "checked_at")
                if value.get("checked_at") is not None
                else None
            ),
            observed_at=(
                _timestamp(value.get("observed_at"), "observed_at")
                if value.get("observed_at") is not None
                else None
            ),
            rights_status=None,
            rights_reference=None,
            rights_scope=None,
            rights_valid_from=None,
            rights_expires_at=None,
        )
        if entry["locale"] not in {None, "ko"}:
            raise ValueError("current company-description display requires locale ko")
        entry["unavailable_reason"] = require_string(value.get("unavailable_reason"), "unavailable_reason")
        return entry
    entry.update(
        provider_id=require_string(value.get("provider_id"), "provider_id"),
        provider_name=require_string(value.get("provider_name"), "provider_name"),
        profile_url=_validate_url(value.get("profile_url"), allowed_hosts),
        locale=require_string(value.get("locale"), "locale"),
        checked_at=_timestamp(value.get("checked_at"), "checked_at"),
        observed_at=_timestamp(value.get("observed_at"), "observed_at"),
        rights_status=value.get("rights_status"),
        rights_reference=value.get("rights_reference"),
        rights_scope=value.get("rights_scope"),
        rights_valid_from=value.get("rights_valid_from"),
        rights_expires_at=value.get("rights_expires_at"),
    )
    if entry["locale"] != "ko":
        raise ValueError("current company-description display requires locale ko")
    if mode == "PROVIDED_TEXT":
        entry["text_path"] = require_string(value.get("text_path"), "text_path")
    else:
        selector = value.get("description_dom_id")
        declared = value.get("description_selector")
        if bool(selector) == bool(declared):
            raise ValueError("authorized fetch requires exactly one description DOM id or selector")
        entry["selector"] = "#" + require_string(selector, "description_dom_id") if selector else _selector(require_string(declared, "description_selector"))
    return entry


def _preflight_entry(plan: dict[str, Any], entry: dict[str, Any], today: date) -> None:
    if entry["status"] == "UNAVAILABLE":
        return
    if entry.get("rights_status") != "APPROVED":
        raise PermissionError("rights status is not APPROVED")
    require_string(entry.get("rights_reference"), "rights_reference")
    expected_scope = "DISPLAY_PLAINTEXT" if plan["acquisition_mode"] == "PROVIDED_TEXT" else "FETCH_AND_DISPLAY_PLAINTEXT"
    if entry.get("rights_scope") != expected_scope:
        raise PermissionError(f"rights scope must be {expected_scope}")
    valid_from = _date(entry.get("rights_valid_from"), "rights_valid_from")
    expires_at = _date(entry.get("rights_expires_at"), "rights_expires_at")
    if valid_from > today or expires_at < today or expires_at < valid_from:
        raise PermissionError("description rights are not current")
    if plan["acquisition_mode"] == "PROVIDED_TEXT":
        contained_file(Path(plan["input_root"]), entry["text_path"], "provided description text")


def _record_from_entry(
    plan: dict[str, Any],
    entry: dict[str, Any],
    today: date,
    fetcher: FetchFunction,
) -> dict[str, Any]:
    base = {
        key: entry.get(key)
        for key in (
            "cik", "ticker", "status", "provider_id", "provider_name", "profile_url",
            "locale", "checked_at", "observed_at", "rights_status", "rights_reference",
            "rights_scope", "rights_valid_from", "rights_expires_at",
        )
    }
    base["acquisition_mode"] = plan["acquisition_mode"]
    base["content_fixture_kind"] = plan["fixture_kind"]
    base["temporal_scope"] = "CURRENT_PROVIDER_METADATA_NOT_FISCAL_YEAR"
    if entry["status"] == "UNAVAILABLE":
        return {**base, "text": None, "text_sha256": None, "source_input_sha256": None, "reason": entry["unavailable_reason"]}
    _preflight_entry(plan, entry, today)
    if plan["acquisition_mode"] == "PROVIDED_TEXT":
        source = contained_file(Path(plan["input_root"]), entry["text_path"], "provided description text")
        body = _read_bounded_file(source, "provided description text")
        try:
            text = _normalize_text(body.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("provided description text must be UTF-8") from exc
        source_sha = hashlib.sha256(body).hexdigest()
    else:
        fetched = fetcher(entry["profile_url"], 10.0, MAX_SOURCE_BYTES)
        if fetched.status != 200:
            raise ValueError(f"description fetch returned HTTP {fetched.status}")
        if fetched.final_url != entry["profile_url"]:
            raise ValueError("description fetch redirect is not accepted")
        if fetched.content_type.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("description fetch did not return HTML")
        body = _bounded_bytes(fetched.body, "description HTML")
        if _looks_like_challenge(body):
            raise ValueError("description fetch returned an access challenge")
        try:
            text = _extract_selected_text(body.decode("utf-8"), entry["selector"])
        except UnicodeDecodeError as exc:
            raise ValueError("description HTML must be UTF-8") from exc
        source_sha = hashlib.sha256(body).hexdigest()
    _validate_korean_text(text)
    return {
        **base,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_input_sha256": source_sha,
        "reason": None,
    }


def _validate_records(manifest: dict[str, Any], records: list[dict[str, Any]], today: date) -> None:
    if len(records) != manifest.get("company_count") or len({row.get("cik") for row in records}) != len(records):
        raise ValueError("company-description record counts changed")
    expected = manifest.get("configured_companies")
    actual = [{"cik": row.get("cik"), "ticker": row.get("ticker")} for row in records]
    if actual != expected:
        raise ValueError("company-description company identities changed")
    for row in records:
        require_cik(row.get("cik"))
        require_ticker(row.get("ticker"))
        if row.get("acquisition_mode") != manifest.get("acquisition_mode"):
            raise ValueError("company-description acquisition mode changed")
        if row.get("content_fixture_kind") != manifest.get("fixture_kind"):
            raise ValueError("company-description content fixture kind changed")
        if row.get("profile_url") is not None:
            _validate_url(row.get("profile_url"), [urlsplit(row["profile_url"]).hostname or ""])
        if row.get("status") == "AVAILABLE":
            text = require_string(row.get("text"), "description text")
            _validate_korean_text(text)
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != row.get("text_sha256"):
                raise ValueError("company-description text digest changed")
            if row.get("rights_status") != "APPROVED":
                raise PermissionError("company-description rights are not approved")
            require_string(row.get("rights_reference"), "rights_reference")
            expected_scope = (
                "DISPLAY_PLAINTEXT"
                if row.get("acquisition_mode") == "PROVIDED_TEXT"
                else "FETCH_AND_DISPLAY_PLAINTEXT"
            )
            if row.get("rights_scope") != expected_scope:
                raise PermissionError("company-description rights scope changed")
            valid_from = _date(row.get("rights_valid_from"), "rights_valid_from")
            expires_at = _date(row.get("rights_expires_at"), "rights_expires_at")
            if expires_at < valid_from:
                raise ValueError("company-description rights dates are invalid")
        elif row.get("status") != "UNAVAILABLE" or row.get("text") is not None:
            raise ValueError("invalid unavailable company-description record")
        elif not row.get("reason"):
            raise ValueError("unavailable company-description reason is required")


def _validate_embedded_plan(
    plan: Any,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    dataset: Any,
) -> None:
    """Validate the immutable normalized plan snapshot without its mutable source files."""
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_VERSION:
        raise ValueError("invalid embedded company-description plan")
    for field in (
        "dataset_id", "dataset_publication_id", "dataset_manifest_sha256",
        "fixture_kind", "dataset_fixture_kind", "acquisition_mode",
    ):
        if plan.get(field) != manifest.get(field):
            raise ValueError("embedded company-description scope changed")
    if plan.get("dataset_id") != dataset.manifest.get("dataset_id"):
        raise ValueError("embedded company-description dataset changed")
    if plan.get("acquisition_mode") not in MODES:
        raise ValueError("embedded company-description mode changed")
    hosts = plan.get("allowed_hosts")
    if not isinstance(hosts, list) or hosts != sorted({_validate_host(host) for host in hosts}):
        raise ValueError("embedded company-description hosts changed")
    entries = plan.get("entries")
    if not isinstance(entries, list) or len(entries) != len(records):
        raise ValueError("embedded company-description entries changed")
    entries = sorted(entries, key=lambda row: row.get("cik", ""))
    for entry, record in zip(entries, records, strict=True):
        for field in (
            "cik", "ticker", "status", "provider_id", "provider_name", "profile_url",
            "locale", "checked_at", "observed_at", "rights_status", "rights_reference",
            "rights_scope", "rights_valid_from", "rights_expires_at",
        ):
            if entry.get(field) != record.get(field):
                raise ValueError("embedded plan and description record differ")
        if entry.get("profile_url") is not None:
            _validate_url(entry.get("profile_url"), hosts)


def _rights_current(row: dict[str, Any], today: date) -> bool:
    try:
        return (
            row.get("rights_status") == "APPROVED"
            and _date(row.get("rights_valid_from"), "rights_valid_from") <= today
            and _date(row.get("rights_expires_at"), "rights_expires_at") >= today
        )
    except (TypeError, ValueError):
        return False


def _fetch_once(url: str, timeout: float, max_bytes: int) -> FetchResult:
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers={"User-Agent": "sec_xbrl personal research authorized text fetch"})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            return FetchResult(
                status=response.status,
                content_type=response.headers.get("Content-Type", ""),
                body=body,
                final_url=response.geturl(),
            )
    except HTTPError as exc:
        return FetchResult(exc.code, exc.headers.get("Content-Type", ""), b"", url)


def _extract_selected_text(html: str, selector: str) -> str:
    parser = _SelectedTextParser(selector)
    parser.feed(html)
    parser.close()
    if parser.malformed_target:
        raise ValueError("description target contains malformed HTML boundaries")
    if parser.matches != 1:
        raise ValueError("description selector must match exactly one element")
    return _normalize_text("".join(parser.parts))


class _SelectedTextParser(HTMLParser):
    def __init__(self, selector: str) -> None:
        super().__init__(convert_charrefs=True)
        self.selector = _selector(selector)
        selector_match = re.fullmatch(
            r"([a-zA-Z][a-zA-Z0-9-]*)?(?:#([A-Za-z][\w-]*)|\.([A-Za-z][\w-]*))?",
            self.selector,
        )
        if selector_match is None:  # pragma: no cover - _selector already validated it
            raise ValueError("unsupported description selector")
        self.selector_tag = (selector_match.group(1) or "").lower() or None
        self.stack: list[str] = []
        self.target_depth: int | None = None
        self.ignore_depth = 0
        self.matches = 0
        self.malformed_target = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.stack.append(tag)
        depth = len(self.stack)
        attr_names = [key.lower() for key, _value in attrs]
        duplicate_selector_attributes = {
            key for key in ("id", "class") if attr_names.count(key) > 1
        }
        potential_target = self.selector_tag is None or tag == self.selector_tag
        if duplicate_selector_attributes and (
            self.target_depth is not None or potential_target
        ):
            self.malformed_target = True
        attr = {key.lower(): value or "" for key, value in attrs}
        if _matches_selector(tag, attr, self.selector):
            self.matches += 1
            if self.target_depth is None:
                self.target_depth = depth
        if tag in IGNORED_TAGS:
            self.ignore_depth += 1
        if self.target_depth is not None and self.ignore_depth == 0 and tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag in VOID_TAGS:
            self._close(tag, append_block=False)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack or self.stack[-1] != tag:
            if self.target_depth is not None:
                self.malformed_target = True
            return
        self._close(tag)

    def _close(self, tag: str, *, append_block: bool = True) -> None:
        if (
            append_block
            and self.target_depth is not None
            and self.ignore_depth == 0
            and tag in BLOCK_TAGS
        ):
            self.parts.append("\n")
        if tag in IGNORED_TAGS and self.ignore_depth:
            self.ignore_depth -= 1
        if self.target_depth == len(self.stack):
            self.target_depth = None
        self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.target_depth is not None and self.ignore_depth == 0:
            self.parts.append(data)

    def close(self) -> None:
        super().close()
        if self.target_depth is not None:
            self.malformed_target = True


def _selector(value: str) -> str:
    value = require_string(value, "description selector")
    match = re.fullmatch(
        r"([a-zA-Z][a-zA-Z0-9-]*)?(#[A-Za-z][\w-]*|\.[A-Za-z][\w-]*)",
        value,
    )
    if match is None or (match.group(1) or "").lower() in {"html", "head", "body"}:
        raise ValueError("unsupported description selector")
    return value


def _matches_selector(tag: str, attrs: dict[str, str], selector: str) -> bool:
    match = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9-]*)?(?:#([A-Za-z][\w-]*)|\.([A-Za-z][\w-]*))?", selector)
    if match is None:
        return False
    selected_tag, selected_id, selected_class = match.groups()
    return (
        (selected_tag is None or tag == selected_tag.lower())
        and (selected_id is None or attrs.get("id") == selected_id)
        and (selected_class is None or selected_class in attrs.get("class", "").split())
    )


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\xa0", " ").replace("\x00", ""))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1] != "":
            output.append("")
    text = "\n".join(output).strip()
    if not text:
        raise ValueError("company description text is empty")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("company description text is too large")
    return text


def _optional_string(value: Any, label: str) -> str | None:
    return None if value is None else require_string(value, label)


def _validate_korean_text(text: str) -> None:
    if not HANGUL_RE.search(text):
        raise ValueError("Korean company description text is required")


def _looks_like_challenge(body: bytes) -> bool:
    sample = body[:64_000].lower()
    return any(marker in sample for marker in (b"captcha", b"cf-chl-", b"access denied", b"just a moment"))


def _bounded_bytes(body: bytes, label: str) -> bytes:
    if not body:
        raise ValueError(f"{label} is empty")
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError(f"{label} exceeds the byte limit")
    return body


def _read_bounded_file(path: Path, label: str) -> bytes:
    with path.open("rb") as stream:
        return _bounded_bytes(stream.read(MAX_SOURCE_BYTES + 1), label)


def _validate_url(value: Any, allowed_hosts: list[str]) -> str:
    value = require_string(value, "profile_url")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("profile_url must be a credential-free HTTPS URL without a fragment")
    if host not in allowed_hosts:
        raise ValueError("profile_url host is not explicitly allowed")
    _validate_host(host)
    return value


def _validate_host(value: Any) -> str:
    host = require_string(value, "allowed host").lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("local provider hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            inet_aton(host)
        except OSError:
            pass
        else:
            raise ValueError("noncanonical numeric provider addresses are not allowed")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) or "." not in host:
            raise ValueError("invalid provider host")
    else:
        if not address.is_global:
            raise ValueError("non-public provider addresses are not allowed")
    return host


def _timestamp(value: Any, field: str) -> str:
    value = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed.isoformat()


def _date(value: Any, field: str) -> date:
    value = require_string(value, field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _require_sha256(value: Any, field: str) -> str:
    value = require_string(value, field)
    if not SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _utc_today() -> date:
    return datetime.now(UTC).date()
