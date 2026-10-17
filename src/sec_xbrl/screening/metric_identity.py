"""Immutable readiness identity for generic annual and quarterly metrics.

This publication is an additive alternative to the manual reviewed-Q4
``UniverseDelivery`` path.  It does not calculate a metric or reinterpret Raw
facts.  It binds one exact collection, metadata publication, governed quality
publication, history publications and their annual/quarterly analysis children.
"""

from __future__ import annotations

import copy
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sec_xbrl.analysis import open_analysis
from sec_xbrl.collection_operations import read_universe_status
from sec_xbrl.company_metadata import MANIFEST_NAME as METADATA_MANIFEST
from sec_xbrl.company_metadata import CompanyMetadataReader
from sec_xbrl.history import HistoryPublicationReader
from sec_xbrl.screening.common import (
    atomic_replace,
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

VERSION = "generic-metric-identity-attestation-v1"
CONFIG_VERSION = "generic-metric-identity-config-v1"
SOURCE_KIND = "GENERIC_METRIC_IDENTITY_ATTESTATION"
QUALITY_SCOPE = "RAW_TRANSFORM_SOURCE_CONFORMANCE_ONLY"
MANIFEST_NAME = "generic_metric_identity_manifest.json"
ANNUAL_VIEW = "LATEST_REPORTED"
ANNUAL_BALANCE_SCOPE = {
    "included": True,
    "rule_version": "annual-exact-year-end-instant-v1",
}
QUARTER_SOURCE_EVIDENCE = {
    "included": True,
    "rule_version": "quarter-typed-primary-pre-evidence-v1",
}


@dataclass(frozen=True, slots=True)
class GenericMetricIdentityPublication:
    root: Path
    publication_id: str
    manifest_path: Path


def publish_generic_metric_identity(
    config_path: Path | str, destination: Path | str
) -> GenericMetricIdentityPublication:
    """Validate every governed parent and atomically publish its identity."""
    config_file = regular_file(Path(config_path), "generic metric identity config")
    config = _validate_config(read_json(config_file, "generic metric identity config"))
    destination_path = safe_new_destination(Path(destination), "generic metric identity")
    sources = _verify_configured_sources(config)
    identity = {
        "schema_version": VERSION,
        "source_kind": SOURCE_KIND,
        "readiness": "READY",
        "universe_id": config["universe_id"],
        "financial_as_of": config["financial_as_of"],
        "metadata_observation_cutoff": config["metadata_observation_cutoff"],
        "annual_window": copy.deepcopy(config["annual_window"]),
        "global_quarter_spine": copy.deepcopy(config["global_quarter_spine"]),
        "configured_ciks": [row["cik"] for row in config["companies"]],
        "configured_tickers": [row["ticker"] for row in config["companies"]],
        "config": copy.deepcopy(config),
        "config_path": str(config_file),
        "config_sha256": sha256_file(config_file),
        **sources,
    }
    publication_id = "generic-metric-identity-" + digest_value(identity)[:24]
    manifest = {**identity, "publication_id": publication_id}
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / MANIFEST_NAME, manifest)
        GenericMetricIdentityReader(staging, allow_staging=True).verify_all()
        atomic_replace(staging, destination_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return GenericMetricIdentityPublication(
        destination_path, publication_id, destination_path / MANIFEST_NAME
    )


class GenericMetricIdentityReader:
    """Strictly reopen an attestation and all of its pinned governed parents."""

    def __init__(
        self,
        root: Path | str,
        *,
        manifest_sha256: str | None = None,
        allow_staging: bool = False,
    ) -> None:
        candidate = Path(root)
        if allow_staging:
            if not candidate.is_absolute():
                candidate = candidate.absolute()
            if not candidate.is_dir() or candidate.is_symlink():
                raise ValueError("generic metric identity staging root is unsafe")
            self.root = candidate.resolve()
        else:
            self.root = real_directory(candidate, "generic metric identity publication")
        self.manifest_path = regular_file(
            self.root / MANIFEST_NAME, "generic metric identity manifest"
        )
        if manifest_sha256 is not None and sha256_file(self.manifest_path) != _sha(
            manifest_sha256, "generic metric identity manifest SHA-256"
        ):
            raise ValueError("generic metric identity manifest differs from pinned SHA-256")
        self.manifest = read_json(self.manifest_path, "generic metric identity manifest")
        self.publication_id = require_string(
            self.manifest.get("publication_id"), "generic metric identity publication ID"
        )
        self.companies = tuple(copy.deepcopy(self.manifest.get("companies") or ()))
        self.verify_all()

    def verify_all(self) -> dict[str, Any]:
        if {path.name for path in self.root.iterdir()} != {MANIFEST_NAME}:
            raise ValueError("generic metric identity publication file set changed")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported generic metric identity attestation")
        if self.manifest.get("source_kind") != SOURCE_KIND:
            raise ValueError("generic metric identity source kind changed")
        if self.manifest.get("readiness") != "READY":
            raise ValueError("generic metric identity is not READY")
        config_path = regular_file(
            Path(self.manifest.get("config_path", "")), "generic metric identity source config"
        )
        if sha256_file(config_path) != self.manifest.get("config_sha256"):
            raise ValueError("generic metric identity source config changed")
        config = _validate_config(read_json(config_path, "generic metric identity source config"))
        if config != self.manifest.get("config"):
            raise ValueError("generic metric identity normalized config changed")
        expected_scope = {
            "universe_id": config["universe_id"],
            "financial_as_of": config["financial_as_of"],
            "metadata_observation_cutoff": config["metadata_observation_cutoff"],
            "annual_window": config["annual_window"],
            "global_quarter_spine": config["global_quarter_spine"],
            "configured_ciks": [row["cik"] for row in config["companies"]],
            "configured_tickers": [row["ticker"] for row in config["companies"]],
        }
        if any(self.manifest.get(key) != value for key, value in expected_scope.items()):
            raise ValueError("generic metric identity top-level scope changed")
        expected_sources = _verify_configured_sources(config)
        for key, value in expected_sources.items():
            if self.manifest.get(key) != value:
                raise ValueError(f"generic metric identity {key} changed")
        identity = {
            key: copy.deepcopy(value)
            for key, value in self.manifest.items()
            if key != "publication_id"
        }
        expected_id = "generic-metric-identity-" + digest_value(identity)[:24]
        if self.publication_id != expected_id:
            raise ValueError("generic metric identity publication identity changed")
        return {
            "publication_id": self.publication_id,
            "source_kind": SOURCE_KIND,
            "readiness": "READY",
            "companies": len(self.companies),
            "financial_as_of": self.manifest["financial_as_of"],
        }

    def annual_analysis_source(self, cik: str) -> dict[str, Any]:
        cik = require_cik(cik, "annual analysis source CIK")
        matches = [row["annual_analysis"] for row in self.companies if row["cik"] == cik]
        if len(matches) != 1:
            raise ValueError("generic metric identity annual analysis source is ambiguous")
        return copy.deepcopy(matches[0])


def _verify_configured_sources(config: dict[str, Any]) -> dict[str, Any]:
    collection_path = regular_file(
        Path(config["collection_manifest"]), "generic metric collection manifest"
    )
    if sha256_file(collection_path) != config["collection_manifest_sha256"]:
        raise ValueError("generic metric collection manifest changed")
    status = read_universe_status(manifest_path=collection_path)
    expected = tuple((row["ticker"], row["cik"]) for row in config["companies"])
    actual = tuple(
        sorted(((row.ticker, row.cik) for row in status.companies), key=lambda item: item[1])
    )
    status_by_identity = {(row.ticker, row.cik): row for row in status.companies}
    if (
        status.universe_id != config["universe_id"]
        or status.as_of_date != config["financial_as_of"]
        or status.requested_companies != len(actual)
        or not set(expected) <= set(actual)
    ):
        raise ValueError("generic metric collection parent or cohort scope differs")
    if config["collection_scope_mode"] == "FULL" and actual != expected:
        raise ValueError("FULL generic metric collection scope must match its parent")
    if config["collection_scope_mode"] == "EXPLICIT_SUBSET" and (
        actual == expected or len(expected) >= len(actual)
    ):
        raise ValueError("EXPLICIT_SUBSET must be a proper declared parent subset")
    scoped_status = [status_by_identity[identity] for identity in expected]
    for row in scoped_status:
        if (
            row.state != "READY"
            or row.action != "NONE"
            or row.selected_filings != row.held_filings
            or row.pending_filings != 0
            or row.failed_filings != 0
        ):
            raise ValueError(f"{row.ticker}: collection company is not exactly READY")
    scoped_selected = sum(row.selected_filings for row in scoped_status)
    scoped_held = sum(row.held_filings for row in scoped_status)
    if scoped_selected != scoped_held:
        raise ValueError("generic metric cohort selected/held filing scope differs")

    metadata_root = real_directory(Path(config["metadata_root"]), "company metadata publication")
    metadata_manifest = regular_file(
        metadata_root / METADATA_MANIFEST, "company metadata manifest"
    )
    if sha256_file(metadata_manifest) != config["metadata_manifest_sha256"]:
        raise ValueError("company metadata manifest changed")
    metadata = CompanyMetadataReader(metadata_root)
    metadata_by_cik = {row.cik: row for row in metadata.list_companies()}
    metadata_cutoff = _timestamp_datetime(
        config["metadata_observation_cutoff"], "metadata_observation_cutoff"
    )
    metadata_observations: list[dict[str, str]] = []
    for ticker, cik in expected:
        candidate = metadata_by_cik.get(cik)
        if candidate is None or ticker not in candidate.tickers:
            raise ValueError(f"{ticker}: metadata ticker/CIK identity mismatch")
        observed_at = _timestamp(candidate.observed_at, f"{ticker} metadata observed_at")
        if _timestamp_datetime(observed_at, f"{ticker} metadata observed_at") > metadata_cutoff:
            raise ValueError(f"{ticker}: metadata observation is after its declared cutoff")
        metadata_observations.append(
            {"ticker": ticker, "cik": cik, "observed_at": observed_at}
        )

    company_sources: list[dict[str, Any]] = []
    history_hashes: dict[str, str] = {}
    for company in config["companies"]:
        source = _verify_company_sources(company, config["financial_as_of"], collection_path)
        company_sources.append(source)
        history_hashes[company["ticker"]] = source["history"]["manifest_sha256"]

    quality_root = real_directory(Path(config["quality_root"]), "generic metric quality")
    # The additive mixed-v5/v6 quality implementation is deliberately the only
    # accepted authority.  Missing modules or incompatible APIs fail closed.
    from sec_xbrl.metric_quality import (
        COLLECTOR_PROVENANCE_ASSURANCE,
        COLLECTOR_PROVENANCE_GRANULARITY,
        GenericMetricQualityReader,
    )

    quality = GenericMetricQualityReader(
        quality_root, manifest_sha256=config["quality_manifest_sha256"]
    )
    quality.verify_sources(
        collection_manifest=collection_path,
        history_manifest_sha256s=history_hashes,
        financial_as_of=config["financial_as_of"],
        expected_companies=tuple(
            {"ticker": row["ticker"], "cik": row["cik"]} for row in config["companies"]
        ),
    )
    if (
        quality.manifest.get("state") != "PASS"
        or quality.manifest.get("assurance_scope") != QUALITY_SCOPE
        or quality.manifest.get("full_financial_semantic_assurance") is not False
        or quality.manifest.get("collector_provenance_assurance")
        != COLLECTOR_PROVENANCE_ASSURANCE
        or quality.manifest.get("collector_provenance_granularity")
        != COLLECTOR_PROVENANCE_GRANULARITY
    ):
        raise ValueError("generic metric quality proof has the wrong assurance scope")
    quality_manifest = regular_file(quality.manifest_path, "generic metric quality manifest")
    if sha256_file(quality_manifest) != config["quality_manifest_sha256"]:
        raise ValueError("generic metric quality manifest changed")

    return {
        "collection": {
            "manifest_path": str(collection_path),
            "manifest_sha256": sha256_file(collection_path),
            "status_version": status.version,
            "rule_versions": copy.deepcopy(status.rule_versions),
            "scope_mode": config["collection_scope_mode"],
            "parent_companies": [
                {"ticker": ticker, "cik": cik} for ticker, cik in actual
            ],
            "parent_company_membership_sha256": digest_value(actual),
            "parent_requested_companies": status.requested_companies,
            "scope_companies": [
                {"ticker": ticker, "cik": cik} for ticker, cik in expected
            ],
            "scope_company_membership_sha256": digest_value(expected),
            "scope_ready_companies": len(scoped_status),
            "scope_selected_filings": scoped_selected,
            "scope_held_filings": scoped_held,
            "source_observed_at": status.source_observed_at,
        },
        "metadata": {
            "root": str(metadata_root),
            "publication_id": metadata.publication_id,
            "manifest_sha256": sha256_file(metadata_manifest),
            "observation_cutoff": config["metadata_observation_cutoff"],
            "scope_observations": metadata_observations,
            "historical_membership_assurance": False,
        },
        "quality": {
            "root": str(quality_root),
            "publication_id": quality.publication_id,
            "manifest_sha256": sha256_file(quality_manifest),
            "assurance_scope": QUALITY_SCOPE,
            "full_financial_semantic_assurance": False,
            "collector_provenance_assurance": COLLECTOR_PROVENANCE_ASSURANCE,
            "collector_provenance_granularity": COLLECTOR_PROVENANCE_GRANULARITY,
            "rule_versions": copy.deepcopy(quality.manifest.get("rule_versions", {})),
            "parser_profiles": copy.deepcopy(quality.manifest.get("parser_profiles", [])),
        },
        "companies": company_sources,
        "versions": {
            "collection": status.version,
            "collection_rules": copy.deepcopy(status.rule_versions),
            "quality_rules": copy.deepcopy(quality.manifest.get("rule_versions", {})),
            "history": sorted({row["history"]["version"] for row in company_sources}),
            "annual_analysis": sorted(
                {row["annual_analysis"]["version"] for row in company_sources}
            ),
            "quarterly_analysis": sorted(
                {row["quarterly_analysis"]["version"] for row in company_sources}
            ),
            "annual_balance_rule": ANNUAL_BALANCE_SCOPE["rule_version"],
            "quarter_source_rule": QUARTER_SOURCE_EVIDENCE["rule_version"],
        },
    }


def _verify_company_sources(
    company: dict[str, Any], financial_as_of: str, collection_manifest: Path
) -> dict[str, Any]:
    ticker, cik = company["ticker"], company["cik"]
    build_path = regular_file(
        collection_manifest.parent / "companies" / ticker / "build_manifest.json",
        f"{ticker} collection build attestation",
    )
    build = read_json(build_path, f"{ticker} collection build attestation")
    intake_path = regular_file(
        Path(build.get("intake_manifest", "")), f"{ticker} history intake manifest"
    )
    intake_sha = _sha(build.get("intake_sha256"), f"{ticker} history intake SHA-256")
    history_root = real_directory(Path(company["history_root"]), f"{ticker} history")
    history_manifest = regular_file(history_root / "history_manifest.json", f"{ticker} history manifest")
    history_sha = sha256_file(history_manifest)
    if (
        history_sha != company["history_manifest_sha256"]
        or build.get("status") != "READY"
        or build.get("ticker") != ticker
        or sha256_file(intake_path) != intake_sha
        or Path(str(build.get("publication", ""))).resolve() != history_root
        or build.get("history_manifest_sha256") != history_sha
    ):
        raise ValueError(f"{ticker}: history identity differs from collection build")
    history = HistoryPublicationReader(history_root)
    history.verify_all()

    annual = _verify_analysis(
        company["annual_analysis_root"],
        company["annual_analysis_manifest_sha256"],
        ticker=ticker,
        cik=cik,
        financial_as_of=financial_as_of,
        history_root=history_root,
        history_sha=history_sha,
        period_mode="ANNUAL",
        input_years=company["input_years"],
    )
    quarterly = _verify_analysis(
        company["quarterly_analysis_root"],
        company["quarterly_analysis_manifest_sha256"],
        ticker=ticker,
        cik=cik,
        financial_as_of=financial_as_of,
        history_root=history_root,
        history_sha=history_sha,
        period_mode="QUARTERLY",
        input_years=None,
    )
    return {
        "ticker": ticker,
        "cik": cik,
        "input_years": copy.deepcopy(company["input_years"]),
        "display_years": copy.deepcopy(company["display_years"]),
        "history": {
            "root": str(history_root),
            "manifest_sha256": history_sha,
            "version": require_string(history.manifest.get("version"), f"{ticker} history version"),
            "declared_files": _history_files(history.manifest),
            "collection_build_manifest_sha256": sha256_file(build_path),
            "collection_plan_sha256": _sha(
                build.get("plan_sha256"), f"{ticker} collection plan SHA-256"
            ),
            "intake_manifest": str(intake_path),
            "intake_sha256": intake_sha,
        },
        "annual_analysis": annual,
        "quarterly_analysis": quarterly,
    }


def _verify_analysis(
    root_value: str,
    expected_sha: str,
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    history_root: Path,
    history_sha: str,
    period_mode: str,
    input_years: list[int] | None,
) -> dict[str, Any]:
    root = real_directory(Path(root_value), f"{ticker} {period_mode.lower()} analysis")
    manifest_path = regular_file(root / "analysis_manifest.json", f"{ticker} analysis manifest")
    digest = sha256_file(manifest_path)
    if digest != expected_sha:
        raise ValueError(f"{ticker}: {period_mode.lower()} analysis manifest changed")
    client = open_analysis(root)
    manifest = client.manifest
    declared = _analysis_files(manifest)
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "analysis_manifest.json"
    }
    if set(declared) != actual or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError(f"{ticker}: analysis publication file set changed")
    for relative, sha in declared.items():
        if sha256_file(contained_file(root, relative, f"{ticker} analysis data")) != sha:
            raise ValueError(f"{ticker}: analysis data hash changed")
    declared_period_mode = manifest.get("period_mode", "QUARTERLY")
    if declared_period_mode != period_mode or set(manifest.get("companies", {})) != {ticker}:
        raise ValueError(f"{ticker}: analysis company or period mode differs")
    scope = manifest["companies"][ticker]
    if scope.get("as_of") != financial_as_of:
        raise ValueError(f"{ticker}: analysis financial cutoff differs")
    if manifest.get("source_manifest_hashes", {}).get("history_manifest_sha256") != history_sha:
        raise ValueError(f"{ticker}: analysis history parent hash differs")
    if Path(str(scope.get("source_publication", ""))).resolve() != history_root:
        raise ValueError(f"{ticker}: analysis history publication differs")
    files = scope.get("views", {}).get(ANNUAL_VIEW, {}).get("files", {})
    required = {"core_rows", "core_cells", *(f"trace_{digit}" for digit in "0123456789abcdef")}
    if period_mode == "ANNUAL":
        if manifest.get("balance_scope") != ANNUAL_BALANCE_SCOPE:
            raise ValueError(f"{ticker}: annual balance scope differs")
        if scope.get("years") != input_years:
            raise ValueError(f"{ticker}: annual input years differ")
    else:
        required.add("columns")
        if manifest.get("quarter_source_evidence") != QUARTER_SOURCE_EVIDENCE:
            raise ValueError(f"{ticker}: quarterly typed source evidence differs")
    if not required <= set(files):
        raise ValueError(f"{ticker}: analysis required prepared files are missing")
    return {
        "root": str(root),
        "publication_id": require_string(manifest.get("publication_id"), f"{ticker} analysis ID"),
        "manifest_sha256": digest,
        "version": require_string(manifest.get("version"), f"{ticker} analysis version"),
        "history_manifest_sha256": history_sha,
        "declared_files": declared,
        "period_mode": period_mode,
        "quarter_source_evidence": (
            copy.deepcopy(QUARTER_SOURCE_EVIDENCE) if period_mode == "QUARTERLY" else None
        ),
    }


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported generic metric identity config")
    if value.get("source_kind") != SOURCE_KIND:
        raise ValueError("generic metric identity config requires an explicit source kind")
    financial_as_of = require_string(value.get("financial_as_of"), "financial_as_of")
    date.fromisoformat(financial_as_of)
    metadata_observation_cutoff = _timestamp(
        value.get("metadata_observation_cutoff"), "metadata_observation_cutoff"
    )
    annual_window = value.get("annual_window")
    if annual_window != {"input_fiscal_years": 5, "display_fiscal_years": 4}:
        raise ValueError("generic metric identity requires the approved 5-input/4-display window")
    expected_spine = _quarter_spine(financial_as_of)
    if value.get("global_quarter_spine") != expected_spine:
        raise ValueError("generic metric identity requires the exact completed 8-quarter spine")
    raw_companies = value.get("companies")
    if not isinstance(raw_companies, list) or not raw_companies:
        raise ValueError("generic metric identity requires companies")
    companies: list[dict[str, Any]] = []
    for index, row in enumerate(raw_companies):
        if not isinstance(row, dict):
            raise TypeError("generic metric identity company must be an object")
        input_years = _years(row.get("input_years"), f"companies[{index}].input_years", 5)
        display_years = _years(row.get("display_years"), f"companies[{index}].display_years", 4)
        if display_years != input_years[-4:]:
            raise ValueError("display_years must be the latest four input_years")
        companies.append(
            {
                "ticker": require_ticker(row.get("ticker"), f"companies[{index}].ticker"),
                "cik": require_cik(row.get("cik"), f"companies[{index}].cik"),
                "input_years": input_years,
                "display_years": display_years,
                "history_root": require_string(row.get("history_root"), "history_root"),
                "history_manifest_sha256": _sha(row.get("history_manifest_sha256"), "history SHA"),
                "annual_analysis_root": require_string(row.get("annual_analysis_root"), "annual analysis root"),
                "annual_analysis_manifest_sha256": _sha(row.get("annual_analysis_manifest_sha256"), "annual analysis SHA"),
                "quarterly_analysis_root": require_string(row.get("quarterly_analysis_root"), "quarterly analysis root"),
                "quarterly_analysis_manifest_sha256": _sha(row.get("quarterly_analysis_manifest_sha256"), "quarterly analysis SHA"),
            }
        )
    companies.sort(key=lambda row: row["cik"])
    if len({row["ticker"] for row in companies}) != len(companies) or len(
        {row["cik"] for row in companies}
    ) != len(companies):
        raise ValueError("generic metric identity companies must be unique")
    return {
        "schema_version": CONFIG_VERSION,
        "source_kind": SOURCE_KIND,
        "universe_id": require_string(value.get("universe_id"), "universe_id"),
        "financial_as_of": financial_as_of,
        "metadata_observation_cutoff": metadata_observation_cutoff,
        "annual_window": copy.deepcopy(annual_window),
        "global_quarter_spine": copy.deepcopy(expected_spine),
        "collection_scope_mode": _scope_mode(value.get("collection_scope_mode")),
        "collection_scope_companies": _scope_companies(
            value.get("collection_scope_companies"), companies
        ),
        "collection_manifest": require_string(value.get("collection_manifest"), "collection_manifest"),
        "collection_manifest_sha256": _sha(value.get("collection_manifest_sha256"), "collection manifest SHA"),
        "metadata_root": require_string(value.get("metadata_root"), "metadata_root"),
        "metadata_manifest_sha256": _sha(value.get("metadata_manifest_sha256"), "metadata manifest SHA"),
        "quality_root": require_string(value.get("quality_root"), "quality_root"),
        "quality_manifest_sha256": _sha(value.get("quality_manifest_sha256"), "quality manifest SHA"),
        "companies": companies,
    }


def _analysis_files(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for company in manifest.get("companies", {}).values():
        for view in company.get("views", {}).values():
            for info in view.get("files", {}).values():
                relative = require_string(info.get("path"), "analysis data path")
                sha = _sha(info.get("sha256"), "analysis data SHA-256")
                if relative in result and result[relative] != sha:
                    raise ValueError("analysis manifest has conflicting file declarations")
                result[relative] = sha
    return dict(sorted(result.items()))


def _history_files(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    declarations = [
        info
        for table in manifest.get("tables", [])
        for info in table.get("files", {}).values()
    ]
    if manifest.get("derived_quarter"):
        declarations.append(manifest["derived_quarter"])
    for info in declarations:
        relative = require_string(info.get("path"), "history data path")
        sha = _sha(info.get("sha256"), "history data SHA-256")
        if relative in result and result[relative] != sha:
            raise ValueError("history manifest has conflicting file declarations")
        result[relative] = sha
    if not result:
        raise ValueError("history publication has no declared files")
    return dict(sorted(result.items()))


def _quarter_spine(financial_as_of: str) -> list[dict[str, int]]:
    cutoff = date.fromisoformat(financial_as_of)
    quarter = (cutoff.month - 1) // 3
    year = cutoff.year
    if quarter == 0:
        year -= 1
        quarter = 4
    result = []
    for offset in range(7, -1, -1):
        absolute = year * 4 + quarter - 1 - offset
        result.append({"calendar_year": absolute // 4, "calendar_quarter": absolute % 4 + 1})
    return result


def _years(value: Any, field: str, count: int) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != count
        or any(type(year) is not int for year in value)
        or value != sorted(set(value))
    ):
        raise ValueError(f"{field} must contain exactly {count} ordered unique fiscal years")
    return list(value)


def _scope_mode(value: Any) -> str:
    if value not in {"FULL", "EXPLICIT_SUBSET"}:
        raise ValueError("collection_scope_mode must be FULL or EXPLICIT_SUBSET")
    return str(value)


def _scope_companies(value: Any, companies: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("collection_scope_companies must be explicitly declared")
    normalized = sorted(
        (
            {
                "ticker": require_ticker(row.get("ticker"), "collection scope ticker"),
                "cik": require_cik(row.get("cik"), "collection scope CIK"),
            }
            for row in value
            if isinstance(row, dict)
        ),
        key=lambda row: row["cik"],
    )
    expected = [{"ticker": row["ticker"], "cik": row["cik"]} for row in companies]
    if len(normalized) != len(value) or normalized != expected:
        raise ValueError("collection_scope_companies must exactly match configured companies")
    return normalized


def _sha(value: Any, field: str) -> str:
    digest = require_string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _timestamp(value: Any, field: str) -> str:
    parsed = _timestamp_datetime(value, field)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_datetime(value: Any, field: str) -> datetime:
    raw = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed
