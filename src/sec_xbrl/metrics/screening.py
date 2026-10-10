"""Governed reported and derived metrics for the screening consumer.

This producer reads immutable prepared annual analysis bundles.  It never
opens SEC source material, selects a filing, or changes a mapping.  Reported
inputs and every derived formula are materialized before a screening dataset
or HTTP service consumes them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from sec_xbrl.analysis import open_analysis

VERSION = "screening-metrics-v1"
CONFIG_VERSION = "screening-metric-config-v1"
MANIFEST = "screening_metric_manifest.json"
DEFINITIONS = "metric_definitions.json"
SUPPORT = "metric_support.json"
OBSERVATIONS = "metric_observations.json"
VIEW = "LATEST_REPORTED"
ARITHMETIC_POLICY = "REPORTED_VALUES_NOT_RECAST_VALIDATED"
DECIMAL_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
ARITHMETIC_RULE_VERSION = "screening-decimal-rational-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc


def write_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def require_ticker(value: Any, field: str) -> str:
    value = require_string(value, field).upper()
    if not value[0].isalnum() or len(value) > 16 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.^-" for char in value) or ".." in value:
        raise ValueError(f"{field} is unsafe")
    return value


def require_cik(value: Any, field: str) -> str:
    value = require_string(value, field)
    if len(value) != 10 or not value.isdigit():
        raise ValueError(f"{field} must be a ten-digit CIK")
    return value


def regular_file(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if (
        not absolute.is_file()
        or any(ancestor.is_symlink() for ancestor in (absolute, *absolute.parents))
    ):
        raise ValueError(f"{label} is not a regular file: {path}")
    return absolute.resolve()


def real_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if (
        not absolute.is_dir()
        or any(ancestor.is_symlink() for ancestor in (absolute, *absolute.parents))
    ):
        raise ValueError(f"{label} is not a real directory: {path}")
    return absolute.resolve()


def safe_new_destination(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    if absolute.exists() or any(ancestor.is_symlink() for ancestor in (absolute, *absolute.parents)):
        raise ValueError(f"{label} requires a new non-symlink destination")
    return absolute


def contained_file(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError(f"unsafe {label} path")
    current = root.resolve()
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    if not current.is_file() or root.resolve() not in current.resolve().parents:
        raise ValueError(f"{label} is outside its publication")
    return current.resolve()


def atomic_replace(staging: Path, destination: Path) -> None:
    os.rename(staging, destination)


def _definition(
    metric_id: str,
    label: str,
    category: str,
    period_class: str,
    *,
    source_kind: str = "REPORTED",
    formula: str | None = None,
    inputs: tuple[str, ...] = (),
    rule_version: str = "screening-reported-monetary-v1",
    unit_kind: str = "MONEY",
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "label": label,
        "category": category,
        "period_class": period_class,
        "source_kind": source_kind,
        "definition_version": rule_version,
        "rule_version": rule_version,
        "arithmetic_rule_version": (
            ARITHMETIC_RULE_VERSION if source_kind == "DERIVED_METRIC" else None
        ),
        "unit_kind": unit_kind,
        "unit": "USD" if unit_kind == "MONEY" else "PERCENT",
        "formula": formula,
        "input_metric_ids": list(inputs),
        "description": description,
    }


REPORTED_DEFINITIONS = (
    _definition("revenue", "매출", "GROWTH", "FY", rule_version="annual-core-reported-v1"),
    _definition("cost", "매출원가", "PROFITABILITY", "FY"),
    _definition("gross_profit", "매출총이익", "PROFITABILITY", "FY"),
    _definition("research", "연구개발비", "OTHER_REPORTED", "FY"),
    _definition("operating_income", "영업이익", "PROFITABILITY", "FY", rule_version="annual-core-reported-v1"),
    _definition("net_income", "순이익", "PROFITABILITY", "FY", rule_version="annual-core-reported-v1"),
    _definition("cfo", "영업활동 현금흐름", "CASH_FLOW", "FY", rule_version="annual-core-reported-v1"),
    _definition("capex", "유형자산 취득 지출", "CASH_FLOW", "FY"),
    _definition("cfi", "투자활동 현금흐름", "CASH_FLOW", "FY"),
    _definition("cff", "재무활동 현금흐름", "CASH_FLOW", "FY"),
    _definition("repurchases", "자사주 취득 지출", "OTHER_REPORTED", "FY"),
    _definition("stock_compensation", "주식보상비용", "OTHER_REPORTED", "FY"),
    _definition("cash", "현금 및 현금성자산", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("assets", "자산", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("current_assets", "유동자산", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("receivables", "매출채권", "OTHER_REPORTED", "INSTANT"),
    _definition("inventory", "재고자산", "OTHER_REPORTED", "INSTANT"),
    _definition("liabilities", "부채", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("current_liabilities", "유동부채", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("debt", "직접 보고 결합 차입금", "FINANCIAL_STABILITY", "INSTANT"),
    _definition("equity", "자본", "FINANCIAL_STABILITY", "INSTANT"),
)

DERIVED_DEFINITIONS = (
    _definition(
        "revenue_yoy", "매출 전년 대비 성장률", "GROWTH", "FY",
        source_kind="DERIVED_METRIC", formula="(current_revenue / prior_revenue - 1) * 100",
        inputs=("revenue", "revenue"), rule_version="screening-revenue-yoy-v1", unit_kind="PERCENT",
    ),
    _definition(
        "gross_margin", "매출총이익률", "PROFITABILITY", "FY",
        source_kind="DERIVED_METRIC", formula="gross_profit / revenue * 100",
        inputs=("gross_profit", "revenue"), rule_version="screening-gross-margin-v1", unit_kind="PERCENT",
    ),
    _definition(
        "operating_margin", "영업이익률", "PROFITABILITY", "FY",
        source_kind="DERIVED_METRIC", formula="operating_income / revenue * 100",
        inputs=("operating_income", "revenue"), rule_version="screening-operating-margin-v1", unit_kind="PERCENT",
    ),
    _definition(
        "net_margin", "순이익률", "PROFITABILITY", "FY",
        source_kind="DERIVED_METRIC", formula="net_income / revenue * 100",
        inputs=("net_income", "revenue"), rule_version="screening-net-margin-v1", unit_kind="PERCENT",
    ),
    _definition(
        "standardized_fcf", "표준화 FCF(영업현금흐름−유형자산취득지출)", "CASH_FLOW", "FY",
        source_kind="DERIVED_METRIC", formula="cfo - capex", inputs=("cfo", "capex"),
        rule_version="screening-standardized-fcf-v1",
        description="발행사별 non-GAAP FCF와 동등하다고 주장하지 않는 표준 산술값",
    ),
    _definition(
        "fcf_margin", "표준화 FCF 마진", "CASH_FLOW", "FY",
        source_kind="DERIVED_METRIC", formula="standardized_fcf / revenue * 100",
        inputs=("standardized_fcf", "revenue"), rule_version="screening-standardized-fcf-margin-v1", unit_kind="PERCENT",
    ),
    _definition(
        "current_ratio", "유동비율", "FINANCIAL_STABILITY", "INSTANT",
        source_kind="DERIVED_METRIC", formula="current_assets / current_liabilities * 100",
        inputs=("current_assets", "current_liabilities"), rule_version="screening-current-ratio-v1", unit_kind="PERCENT",
    ),
    _definition(
        "liabilities_to_equity", "부채비율", "FINANCIAL_STABILITY", "INSTANT",
        source_kind="DERIVED_METRIC", formula="liabilities / equity * 100",
        inputs=("liabilities", "equity"), rule_version="screening-liabilities-equity-v1", unit_kind="PERCENT",
    ),
    _definition(
        "liabilities_to_assets", "총부채/자산", "FINANCIAL_STABILITY", "INSTANT",
        source_kind="DERIVED_METRIC", formula="liabilities / assets * 100",
        inputs=("liabilities", "assets"), rule_version="screening-liabilities-assets-v1", unit_kind="PERCENT",
    ),
    _definition(
        "net_debt", "순차입금", "FINANCIAL_STABILITY", "INSTANT",
        source_kind="DERIVED_METRIC", formula="direct_combined_debt - cash",
        inputs=("debt", "cash"), rule_version="screening-net-debt-exact-combined-v2",
        description="exact standard combined debt만 사용하며 split debt나 liabilities를 합산하지 않음",
    ),
)

METRIC_DEFINITIONS = (*REPORTED_DEFINITIONS, *DERIVED_DEFINITIONS)
DEFINITION_BY_ID = {row["metric_id"]: row for row in METRIC_DEFINITIONS}
REPORTED_IDS = tuple(row["metric_id"] for row in REPORTED_DEFINITIONS)


@dataclass(frozen=True, slots=True)
class ScreeningMetricPublication:
    root: Path
    publication_id: str
    manifest_path: Path


def expanded_analysis_profile() -> list[dict[str, Any]]:
    """Return the exact 21-row profile used by the opt-in annual preparation."""
    from sec_xbrl.analysis import annual_profile, default_profile

    annual = {row["row_id"]: row for row in annual_profile() if row["row_id"] != "eps"}
    instant = {
        row["row_id"]: row
        for row in default_profile()
        if row["period_class"] == "INSTANT" and row["row_id"] != "shares"
    }
    return [copy.deepcopy(annual[row]) for row in REPORTED_IDS if row in annual] + [
        copy.deepcopy(instant[row]) for row in REPORTED_IDS if row in instant
    ]


def publish_screening_metrics(
    config_path: Path | str, destination: Path | str
) -> ScreeningMetricPublication:
    """Atomically publish reported and governed derived screening metrics."""
    config_file = regular_file(Path(config_path), "screening metric config")
    config = _validate_config(read_json(config_file, "screening metric config"))
    destination_path = safe_new_destination(Path(destination), "screening metric publication")
    from sec_xbrl.screening.dataset import ScreeningDatasetReader

    source_dataset_root = real_directory(
        Path(config["source_dataset_root"]), "screening identity source dataset"
    )
    source_manifest_path = regular_file(
        source_dataset_root / "screening_dataset_manifest.json",
        "screening identity source manifest",
    )
    if sha256_file(source_manifest_path) != config["source_dataset_manifest_sha256"]:
        raise ValueError("screening identity source manifest differs from metric config")
    source_dataset = ScreeningDatasetReader(source_dataset_root)
    if source_dataset.manifest["financial_as_of"] != config["financial_as_of"]:
        raise ValueError("screening identity source financial-as-of differs from metric config")
    if {(row["cik"], row["ticker"]) for row in source_dataset.companies} != {
        (row["cik"], row["ticker"]) for row in config["companies"]
    }:
        raise ValueError("screening metric config company membership differs from identity source")
    definitions = [copy.deepcopy(row) for row in METRIC_DEFINITIONS]
    observations: list[dict[str, Any]] = []
    source_snapshots: list[tuple[str, dict[str, Any]]] = []
    sources: list[dict[str, Any]] = []

    for company in config["companies"]:
        ticker, cik = company["ticker"], company["cik"]
        analysis_root = real_directory(Path(company["analysis_root"]), f"{ticker} analysis")
        manifest_path = regular_file(analysis_root / "analysis_manifest.json", f"{ticker} analysis manifest")
        manifest_sha = sha256_file(manifest_path)
        if manifest_sha != company["analysis_manifest_sha256"]:
            raise ValueError(f"{ticker}: analysis manifest differs from metric config")
        client = open_analysis(analysis_root)
        _verify_analysis_files(analysis_root, client.manifest)
        _validate_analysis_scope(client.manifest, ticker, config["financial_as_of"])
        rows = client._records(ticker, VIEW, "core_rows")
        cells = client._records(ticker, VIEW, "core_cells")
        traces = [
            trace
            for digit in "0123456789abcdef"
            for trace in client._records(ticker, VIEW, f"trace_{digit}")
        ]
        snapshot = _source_snapshot(
            ticker=ticker,
            cik=cik,
            manifest=client.manifest,
            rows=rows,
            cells=cells,
            traces=traces,
        )
        relative = f"source_snapshots/{cik}/{snapshot['snapshot_id']}.json"
        source_snapshots.append((relative, snapshot))
        reported = _reported_observations(
            ticker=ticker,
            cik=cik,
            financial_as_of=config["financial_as_of"],
            snapshot=snapshot,
            years=client.manifest["companies"][ticker]["years"],
        )
        derived = _derived_observations(ticker=ticker, cik=cik, reported=reported)
        observations.extend((*reported, *derived))
        sources.append(
            {
                "ticker": ticker,
                "cik": cik,
                "root": str(analysis_root),
                "manifest_sha256": manifest_sha,
                "publication_id": client.manifest["publication_id"],
                "source_snapshot": relative,
                "source_snapshot_sha256": digest_value(snapshot),
                "declared_files": _declared_analysis_files(client.manifest),
            }
        )

    _assert_unique(observations, ("metric_observation_id",), "metric observation ID")
    _assert_unique(
        observations,
        ("cik", "metric_id", "fiscal_year", "period_class", "view"),
        "metric observation grain",
    )
    support = _support_rows(config["companies"], observations)
    publication_id = "screening-metrics-" + digest_value(
        {
            "config": config,
            "definitions": definitions,
            "observations": observations,
            "support": support,
            "sources": sources,
        }
    )[:24]

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        write_json(staging / DEFINITIONS, definitions)
        write_json(staging / SUPPORT, support)
        write_json(staging / OBSERVATIONS, observations)
        for relative, snapshot in source_snapshots:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json(target, snapshot)
        files = _file_manifest(staging)
        manifest = {
            "schema_version": VERSION,
            "publication_id": publication_id,
            "financial_as_of": config["financial_as_of"],
            "view": VIEW,
            "configured_ciks": [row["cik"] for row in config["companies"]],
            "configured_tickers": [row["ticker"] for row in config["companies"]],
            "config": config,
            "config_path": str(config_file),
            "config_sha256": sha256_file(config_file),
            "definition_count": len(definitions),
            "observation_count": len(observations),
            "support_count": len(support),
            "sources": sources,
            "identity_source": {
                "root": str(source_dataset_root),
                "publication_id": source_dataset.publication_id,
                "manifest_sha256": sha256_file(source_dataset_root / "screening_dataset_manifest.json"),
                "versions": copy.deepcopy(source_dataset.manifest.get("versions", {})),
            },
            "versions": _metric_versions(observations, source_dataset.manifest.get("versions", {})),
            "files": files,
        }
        write_json(staging / MANIFEST, manifest)
        atomic_replace(staging, destination_path)
    except Exception:
        if staging.exists():
            import shutil

            shutil.rmtree(staging)
        raise
    return ScreeningMetricPublication(destination_path, publication_id, destination_path / MANIFEST)


class ScreeningMetricReader:
    """Verify and expose one immutable screening metric publication.

    Normal reads validate the frozen publication and its declared identities.
    ``verify_governed_sources`` is the explicit producer/admin audit that
    reopens prepared analysis parents and recomputes the governed formulas.
    Consumer startup and HTTP requests must not call that deep audit.
    """

    def __init__(self, root: Path | str):
        self.root = real_directory(Path(root), "screening metric publication")
        self.manifest = read_json(
            regular_file(self.root / MANIFEST, "screening metric manifest"),
            "screening metric manifest",
        )
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported screening metric publication")
        self.definitions = self._records(DEFINITIONS)
        self.support = self._records(SUPPORT)
        self.observations = self._records(OBSERVATIONS)
        self.verify_all()

    def _records(self, name: str) -> list[dict[str, Any]]:
        value = read_json(contained_file(self.root, name, name), name)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise TypeError(f"{name} must contain object records")
        return value

    def verify_all(self) -> dict[str, Any]:
        declared = self.manifest.get("files")
        if not isinstance(declared, list):
            raise TypeError("screening metric file manifest is malformed")
        actual = {
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if path.is_file() and path.name != MANIFEST
        }
        expected = set()
        for row in declared:
            relative = require_string(row.get("path"), "screening metric file path")
            path = contained_file(self.root, relative, "screening metric file")
            if sha256_file(path) != row.get("sha256") or path.stat().st_size != row.get("size"):
                raise ValueError("screening metric publication file changed")
            expected.add(relative)
        if expected != actual or any(path.is_symlink() for path in self.root.rglob("*")):
            raise ValueError("screening metric publication file set changed")
        if len(self.definitions) != 31 or self.manifest.get("definition_count") != len(self.definitions):
            raise ValueError("screening metric definition count changed")
        if self.definitions != list(METRIC_DEFINITIONS):
            raise ValueError("screening metric definitions differ from the governed registry")
        if self.manifest.get("observation_count") != len(self.observations):
            raise ValueError("screening metric observation count changed")
        if self.manifest.get("support_count") != len(self.support):
            raise ValueError("screening metric support count changed")
        _assert_unique(self.definitions, ("metric_id",), "metric definition")
        _assert_unique(self.observations, ("metric_observation_id",), "metric observation ID")
        _assert_unique(
            self.observations,
            ("cik", "metric_id", "fiscal_year", "period_class", "view"),
            "metric observation grain",
        )
        _assert_unique(self.support, ("cik", "metric_id"), "metric support")
        expected_support = _support_rows(self.manifest["config"]["companies"], self.observations)
        if expected_support != self.support:
            raise ValueError("screening metric support differs from frozen observations")
        config_path = regular_file(Path(self.manifest["config_path"]), "screening metric source config")
        if (
            sha256_file(config_path) != self.manifest.get("config_sha256")
            or _validate_config(read_json(config_path, "screening metric source config"))
            != self.manifest.get("config")
        ):
            raise ValueError("screening metric source config changed")
        self._verify_identity_manifest()
        expected_publication_id = "screening-metrics-" + digest_value(
            {
                "config": self.manifest["config"],
                "definitions": self.definitions,
                "observations": self.observations,
                "support": self.support,
                "sources": self.manifest["sources"],
            }
        )[:24]
        if self.manifest.get("publication_id") != expected_publication_id:
            raise ValueError("screening metric publication identity changed")
        return {
            "publication_id": self.manifest["publication_id"],
            "financial_as_of": self.manifest["financial_as_of"],
            "companies": len(self.manifest["configured_ciks"]),
            "definitions": len(self.definitions),
            "observations": len(self.observations),
        }

    def verify_governed_sources(self) -> dict[str, Any]:
        """Run the offline producer/admin audit against prepared parent rows."""
        self.verify_all()
        self._verify_identity_source()
        self._verify_sources()
        return {
            "publication_id": self.manifest["publication_id"],
            "sources": len(self.manifest["sources"]),
            "observations": len(self.observations),
            "status": "PASS",
        }

    def _verify_identity_manifest(self) -> None:
        source = self.manifest.get("identity_source") or {}
        root = real_directory(Path(source.get("root", "")), "screening metric identity source")
        manifest_path = regular_file(
            root / "screening_dataset_manifest.json", "identity source manifest"
        )
        if sha256_file(manifest_path) != source.get("manifest_sha256"):
            raise ValueError("screening metric identity source changed")

    def _verify_identity_source(self) -> None:
        from sec_xbrl.screening.dataset import ScreeningDatasetReader

        source = self.manifest.get("identity_source") or {}
        root = real_directory(Path(source.get("root", "")), "screening metric identity source")
        manifest_path = regular_file(root / "screening_dataset_manifest.json", "identity source manifest")
        if sha256_file(manifest_path) != source.get("manifest_sha256"):
            raise ValueError("screening metric identity source changed")
        reader = ScreeningDatasetReader(root)
        if (
            reader.publication_id != source.get("publication_id")
            or reader.manifest.get("versions", {}) != source.get("versions", {})
            or {(row["cik"], row["ticker"]) for row in reader.companies}
            != {
                (row["cik"], row["ticker"])
                for row in self.manifest["config"]["companies"]
            }
            or reader.manifest["financial_as_of"] != self.manifest["financial_as_of"]
        ):
            raise ValueError("screening metric identity source scope changed")

    def _verify_sources(self) -> None:
        source_by_cik = {row["cik"]: row for row in self.manifest.get("sources", [])}
        if set(source_by_cik) != set(self.manifest.get("configured_ciks", [])):
            raise ValueError("screening metric source membership changed")
        recomputed: list[dict[str, Any]] = []
        for cik in self.manifest["configured_ciks"]:
            source = source_by_cik[cik]
            root = real_directory(Path(source["root"]), "screening metric analysis source")
            manifest_path = regular_file(root / "analysis_manifest.json", "screening metric analysis manifest")
            if sha256_file(manifest_path) != source.get("manifest_sha256"):
                raise ValueError("screening metric analysis source changed")
            client = open_analysis(root)
            _verify_analysis_files(root, client.manifest)
            ticker = source["ticker"]
            _validate_analysis_scope(client.manifest, ticker, self.manifest["financial_as_of"])
            if _declared_analysis_files(client.manifest) != source.get("declared_files"):
                raise ValueError("screening metric analysis file declaration changed")
            rows = client._records(ticker, VIEW, "core_rows")
            cells = client._records(ticker, VIEW, "core_cells")
            traces = [
                trace
                for digit in "0123456789abcdef"
                for trace in client._records(ticker, VIEW, f"trace_{digit}")
            ]
            snapshot = _source_snapshot(
                ticker=ticker,
                cik=cik,
                manifest=client.manifest,
                rows=rows,
                cells=cells,
                traces=traces,
            )
            packaged = read_json(
                contained_file(self.root, source["source_snapshot"], "metric source snapshot"),
                "metric source snapshot",
            )
            if snapshot != packaged or digest_value(snapshot) != source.get("source_snapshot_sha256"):
                raise ValueError("screening metric source snapshot differs from prepared parent")
            reported = _reported_observations(
                ticker=ticker,
                cik=cik,
                financial_as_of=self.manifest["financial_as_of"],
                snapshot=snapshot,
                years=client.manifest["companies"][ticker]["years"],
            )
            recomputed.extend((*reported, *_derived_observations(ticker=ticker, cik=cik, reported=reported)))
        if recomputed != self.observations:
            raise ValueError("screening metric observations differ from governed prepared inputs")
        expected_support = _support_rows(self.manifest["config"]["companies"], recomputed)
        if expected_support != self.support:
            raise ValueError("screening metric support differs from governed prepared inputs")


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported screening metric config")
    companies = value.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("screening metric config requires companies")
    normalized = []
    for index, row in enumerate(companies):
        if not isinstance(row, dict):
            raise TypeError("screening metric company config must be an object")
        manifest_sha = require_string(
            row.get("analysis_manifest_sha256"),
            f"companies[{index}].analysis_manifest_sha256",
        )
        if len(manifest_sha) != 64 or any(char not in "0123456789abcdef" for char in manifest_sha):
            raise ValueError("analysis manifest hash must be lowercase SHA-256")
        normalized.append(
            {
                "ticker": require_ticker(row.get("ticker"), f"companies[{index}].ticker"),
                "cik": require_cik(row.get("cik"), f"companies[{index}].cik"),
                "analysis_root": require_string(row.get("analysis_root"), f"companies[{index}].analysis_root"),
                "analysis_manifest_sha256": manifest_sha,
            }
        )
    _assert_unique(normalized, ("ticker",), "configured metric ticker")
    _assert_unique(normalized, ("cik",), "configured metric CIK")
    financial_as_of = require_string(value.get("financial_as_of"), "financial_as_of")
    try:
        date.fromisoformat(financial_as_of)
    except ValueError as exc:
        raise ValueError("financial_as_of must be an ISO date") from exc
    source_manifest_sha = _require_sha256(
        value.get("source_dataset_manifest_sha256"),
        "source_dataset_manifest_sha256",
    )
    return {
        "schema_version": CONFIG_VERSION,
        "financial_as_of": financial_as_of,
        "source_dataset_root": require_string(
            value.get("source_dataset_root"), "source_dataset_root"
        ),
        "source_dataset_manifest_sha256": source_manifest_sha,
        "companies": normalized,
    }


def _require_sha256(value: Any, field: str) -> str:
    digest = require_string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _validate_analysis_scope(manifest: dict[str, Any], ticker: str, financial_as_of: str) -> None:
    if manifest.get("period_mode") != "ANNUAL" or manifest.get("balance_scope") != {
        "included": True,
        "rule_version": "annual-exact-year-end-instant-v1",
    }:
        raise ValueError(f"{ticker}: expanded annual balance scope is not prepared")
    if set(manifest.get("companies", {})) != {ticker}:
        raise ValueError(f"{ticker}: analysis must contain exactly one company")
    company = manifest["companies"][ticker]
    if company.get("as_of") != financial_as_of:
        raise ValueError(f"{ticker}: analysis financial-as-of mismatch")
    files = company.get("views", {}).get(VIEW, {}).get("files", {})
    required = {"core_rows", "core_cells", *(f"trace_{digit}" for digit in "0123456789abcdef")}
    if not required <= set(files):
        raise ValueError(f"{ticker}: expanded analysis lacks required prepared files")


def _source_snapshot(
    *,
    ticker: str,
    cik: str,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    trace_by_cell = {row["cell_id"]: row for row in traces}
    if len(trace_by_cell) != len(traces):
        raise ValueError(f"{ticker}: duplicate analysis trace cell identity")
    selected_rows = [copy.deepcopy(row) for row in rows if row.get("row_id") in REPORTED_IDS]
    if {row.get("row_id") for row in selected_rows} != set(REPORTED_IDS):
        raise ValueError(f"{ticker}: expanded analysis profile does not contain 21 reported rows")
    selected_cells = [copy.deepcopy(row) for row in cells if row.get("row_id") in REPORTED_IDS]
    selected_traces = [
        copy.deepcopy(trace_by_cell[cell["cell_id"]])
        for cell in selected_cells
        if cell.get("cell_id") in trace_by_cell
    ]
    snapshot = {
        "schema_version": "screening-metric-source-snapshot-v1",
        "ticker": ticker,
        "cik": cik,
        "analysis_publication_id": manifest["publication_id"],
        "rows": selected_rows,
        "cells": selected_cells,
        "traces": selected_traces,
    }
    snapshot["snapshot_id"] = "metric-source-" + digest_value(snapshot)[:24]
    return snapshot


def _reported_observations(
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    snapshot: dict[str, Any],
    years: Iterable[int],
) -> list[dict[str, Any]]:
    traces = {row["cell_id"]: row for row in snapshot["traces"]}
    cells: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for cell in snapshot["cells"]:
        cells.setdefault((cell["row_id"], cell["fiscal_year"], cell["period_class"]), []).append(cell)
    result = []
    for definition in REPORTED_DEFINITIONS:
        metric_id = definition["metric_id"]
        for fiscal_year in sorted(years):
            choices = cells.get((metric_id, fiscal_year, definition["period_class"]), [])
            if len(choices) != 1:
                result.append(
                    _unavailable_observation(
                        ticker=ticker,
                        cik=cik,
                        definition=definition,
                        fiscal_year=fiscal_year,
                        financial_as_of=financial_as_of,
                        reason="MULTIPLE_CANDIDATES" if choices else "MISSING_INPUT",
                    )
                )
                continue
            result.append(
                _reported_observation(
                    ticker=ticker,
                    cik=cik,
                    definition=definition,
                    financial_as_of=financial_as_of,
                    cell=choices[0],
                    trace=traces.get(choices[0].get("cell_id")),
                    source_snapshot_id=snapshot["snapshot_id"],
                )
            )
    return result


def _reported_observation(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    financial_as_of: str,
    cell: dict[str, Any],
    trace: dict[str, Any] | None,
    source_snapshot_id: str,
) -> dict[str, Any]:
    lineage = copy.deepcopy((trace or {}).get("value_lineage") or {})
    candidate_lineage = copy.deepcopy(cell.get("candidate_lineage") or [])
    source_reason = cell.get("source_reason") or cell.get("reason")
    input_unavailable = cell.get("status") != "REPORTED"
    reasons: list[str] = []
    value: str | None = None
    if input_unavailable:
        reasons.append(str(source_reason or "INPUT_NOT_REPORTED"))
    else:
        if cell.get("quality_status") == "BLOCK":
            reasons.append("QUALITY_BLOCKED")
        if cell.get("dimensions"):
            reasons.append("DIMENSION_MISMATCH")
        if lineage.get("mapping_review_required") is not False:
            reasons.append("MAPPING_REVIEW_REQUIRED")
        if lineage.get("raw_concept_is_standard") is not True:
            reasons.append("NON_STANDARD_CONCEPT")
        if not _is_usd_unit(cell.get("unit")):
            reasons.append("UNIT_NOT_USD")
        try:
            numeric = Decimal(str(cell.get("value")))
            if not numeric.is_finite():
                reasons.append("INPUT_NOT_FINITE")
            else:
                value = _decimal_string(numeric)
        except (InvalidOperation, TypeError, ValueError):
            reasons.append("INPUT_NOT_FINITE" if cell.get("value") is not None else "MISSING_INPUT")
    source_inputs = lineage.get("source_inputs") or [lineage]
    source_filings = sorted(
        {
            str(item.get("accession") or item.get("source_filing_id"))
            for item in source_inputs
            if item.get("accession") or item.get("source_filing_id")
        }
    )
    source_fact_ids = sorted(
        {
            str(item.get("selected_source_fact_id") or item.get("source_fact_id"))
            for item in source_inputs
            if item.get("selected_source_fact_id") or item.get("source_fact_id")
        }
    )
    if input_unavailable:
        source_filings = sorted(
            {
                str(row.get("source_filing_id"))
                for row in candidate_lineage
                if row.get("source_filing_id")
            }
        )
        source_fact_ids = sorted(
            {
                str(row.get("source_fact_id"))
                for row in candidate_lineage
                if row.get("source_fact_id")
            }
        )
    elif not source_filings or not source_fact_ids or trace is None:
        reasons.append("SOURCE_TRACE_INCOMPLETE")
    period_class = definition["period_class"]
    start = cell.get("start")
    end = cell.get("end")
    if not input_unavailable:
        if period_class == "FY" and (not isinstance(start, str) or not isinstance(end, str)):
            reasons.append("PERIOD_MISMATCH")
        if period_class == "INSTANT" and (start is not None or not isinstance(end, str)):
            reasons.append("PERIOD_MISMATCH")
    evidence = copy.deepcopy(
        cell.get("primary_statement_evidence")
        or lineage.get("primary_statement_evidence")
        or []
    )
    qname = lineage.get("raw_concept_qname")
    observation = {
        "metric_observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "metric_definition_version": definition["definition_version"],
        "source_kind": "REPORTED",
        "fiscal_year": cell.get("fiscal_year"),
        "period_class": period_class,
        "period_start": start,
        "period_end": end,
        "view": VIEW,
        "financial_as_of": financial_as_of,
        "availability_status": "AVAILABLE" if not reasons else "UNAVAILABLE",
        "unavailable_reason": reasons[0] if reasons else None,
        "diagnostic_reasons": _unique(reasons),
        "value": value if not reasons else None,
        "unit_kind": "MONEY",
        "unit": "USD",
        "unit_semantics": copy.deepcopy(cell.get("unit")),
        "dimensions": copy.deepcopy(cell.get("dimensions") or []),
        "basis_version": cell.get("basis_version"),
        "comparability_policy": ARITHMETIC_POLICY if cell.get("basis_version") is None else "DECLARED_BASIS",
        "status": cell.get("status"),
        "source_reason": source_reason,
        "quality_status": cell.get("quality_status"),
        "quality_reasons": copy.deepcopy(cell.get("quality_reasons") or []),
        "mapping_review_required": lineage.get("mapping_review_required"),
        "semantic_identity": lineage.get("company_canonical_concept_id") or cell.get("semantic_id"),
        "raw_concept_qname": qname,
        "raw_concept_is_standard": lineage.get("raw_concept_is_standard"),
        "raw_concept_taxonomy_family": lineage.get("raw_concept_taxonomy_family"),
        "raw_concept_data_type": lineage.get("raw_concept_data_type"),
        "raw_concept_period_type": lineage.get("raw_concept_period_type"),
        "concept_mapping_version": lineage.get("concept_mapping_version"),
        "selection_rule_version": lineage.get("selection_rule_version"),
        "classification_rule_version": lineage.get("classification_rule_version"),
        "parser_version": lineage.get("parser_version"),
        "cell_id": cell.get("cell_id"),
        "source_fact_ids": source_fact_ids,
        "source_filings": source_filings,
        "primary_statement_evidence": evidence,
        "candidate_lineage": candidate_lineage,
        "core_selection_rule_version": cell.get("core_selection_rule_version"),
        "core_selection_evidence": copy.deepcopy(cell.get("core_selection_evidence")),
        "source_snapshot_id": source_snapshot_id,
        "formula": None,
        "input_observation_ids": [],
        "input_values": [],
        "compatibility": None,
        "warnings": [],
        "trace": copy.deepcopy(trace),
    }
    observation["metric_observation_id"] = _observation_id(observation)
    return observation


def _unavailable_observation(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    fiscal_year: int,
    financial_as_of: str,
    reason: str,
) -> dict[str, Any]:
    observation = {
        "metric_observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "metric_definition_version": definition["definition_version"],
        "source_kind": definition["source_kind"],
        "fiscal_year": fiscal_year,
        "period_class": definition["period_class"],
        "period_start": None,
        "period_end": None,
        "view": VIEW,
        "financial_as_of": financial_as_of,
        "availability_status": "UNAVAILABLE",
        "unavailable_reason": reason,
        "diagnostic_reasons": [reason],
        "value": None,
        "unit_kind": definition["unit_kind"],
        "unit": definition["unit"],
        "unit_semantics": None,
        "dimensions": [],
        "basis_version": None,
        "comparability_policy": None,
        "status": "UNAVAILABLE",
        "quality_status": None,
        "quality_reasons": [],
        "mapping_review_required": None,
        "semantic_identity": None,
        "raw_concept_qname": None,
        "raw_concept_is_standard": None,
        "raw_concept_taxonomy_family": None,
        "raw_concept_data_type": None,
        "raw_concept_period_type": None,
        "concept_mapping_version": None,
        "selection_rule_version": None,
        "classification_rule_version": None,
        "parser_version": None,
        "cell_id": None,
        "source_fact_ids": [],
        "source_filings": [],
        "primary_statement_evidence": [],
        "source_snapshot_id": None,
        "formula": definition.get("formula"),
        "input_observation_ids": [],
        "input_values": [],
        "compatibility": None,
        "warnings": [],
        "trace": None,
    }
    observation["metric_observation_id"] = _observation_id(observation)
    return observation


def _derived_observations(
    *, ticker: str, cik: str, reported: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_key = {
        (row["metric_id"], row["fiscal_year"], row["period_class"]): row
        for row in reported
    }
    years = sorted({row["fiscal_year"] for row in reported})
    result: list[dict[str, Any]] = []
    for year in years:
        result.append(
            _derive_revenue_yoy(
                ticker=ticker,
                cik=cik,
                definition=DEFINITION_BY_ID["revenue_yoy"],
                current=by_key.get(("revenue", year, "FY")),
                prior=by_key.get(("revenue", year - 1, "FY")),
                fiscal_year=year,
            )
        )
        for metric_id, numerator in (
            ("gross_margin", "gross_profit"),
            ("operating_margin", "operating_income"),
            ("net_margin", "net_income"),
        ):
            result.append(
                _derive_pair(
                    ticker=ticker,
                    cik=cik,
                    definition=DEFINITION_BY_ID[metric_id],
                    first=by_key.get((numerator, year, "FY")),
                    second=by_key.get(("revenue", year, "FY")),
                    fiscal_year=year,
                    statement_types=({"IS"}, {"IS"}),
                    operation="PERCENT",
                )
            )
        fcf = _derive_pair(
            ticker=ticker,
            cik=cik,
            definition=DEFINITION_BY_ID["standardized_fcf"],
            first=by_key.get(("cfo", year, "FY")),
            second=by_key.get(("capex", year, "FY")),
            fiscal_year=year,
            statement_types=({"CF"}, {"CF"}),
            operation="SUBTRACT",
            require_nonnegative_second=True,
        )
        result.append(fcf)
        result.append(
            _derive_pair(
                ticker=ticker,
                cik=cik,
                definition=DEFINITION_BY_ID["fcf_margin"],
                first=fcf,
                second=by_key.get(("revenue", year, "FY")),
                fiscal_year=year,
                statement_types=({"CF"}, {"IS"}),
                operation="PERCENT",
            )
        )
        for metric_id, first, second, expected in (
            ("current_ratio", "current_assets", "current_liabilities", ({"BS"}, {"BS"})),
            ("liabilities_to_equity", "liabilities", "equity", ({"BS"}, {"BS", "EQ"})),
            ("liabilities_to_assets", "liabilities", "assets", ({"BS"}, {"BS"})),
        ):
            result.append(
                _derive_pair(
                    ticker=ticker,
                    cik=cik,
                    definition=DEFINITION_BY_ID[metric_id],
                    first=by_key.get((first, year, "INSTANT")),
                    second=by_key.get((second, year, "INSTANT")),
                    fiscal_year=year,
                    statement_types=expected,
                    operation="PERCENT",
                    require_nonnegative_first=True,
                    negative_equity_reason=metric_id == "liabilities_to_equity",
                )
            )
        result.append(
            _derive_net_debt(
                ticker=ticker,
                cik=cik,
                definition=DEFINITION_BY_ID["net_debt"],
                debt=by_key.get(("debt", year, "INSTANT")),
                cash=by_key.get(("cash", year, "INSTANT")),
                fiscal_year=year,
            )
        )
    return result


def _derive_revenue_yoy(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    current: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    fiscal_year: int,
) -> dict[str, Any]:
    reasons = _input_reasons((current, prior))
    warnings: list[str] = []
    compatibility = None
    if not reasons and current is not None and prior is not None:
        if prior["fiscal_year"] != fiscal_year - 1:
            reasons.append("NON_CONSECUTIVE_FISCAL_YEAR")
        if not _same_fields(
            current,
            prior,
            (
                "raw_concept_qname",
                "raw_concept_taxonomy_family",
                "raw_concept_data_type",
                "raw_concept_period_type",
                "unit_semantics",
                "dimensions",
                "semantic_identity",
            ),
        ):
            reasons.append("SEMANTIC_IDENTITY_MISMATCH")
        compatibility = _basis_compatibility((current, prior))
        if compatibility is None:
            reasons.append("BASIS_INCOMPATIBLE")
        try:
            durations = [
                (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days
                for row in (current, prior)
            ]
            gap = (date.fromisoformat(current["period_end"]) - date.fromisoformat(prior["period_end"])).days
            if not all(350 <= value <= 378 for value in durations):
                reasons.append("FY_DURATION_OUT_OF_RANGE")
            if not 330 <= gap <= 400:
                reasons.append("FISCAL_END_GAP_OUT_OF_RANGE")
            if durations[0] != durations[1]:
                warnings.append("ACTUAL_DURATION_DIFFERS")
        except (TypeError, ValueError):
            reasons.append("PERIOD_MISMATCH")
    value = None
    if not reasons and current is not None and prior is not None:
        top, bottom = Decimal(current["value"]), Decimal(prior["value"])
        if top < 0:
            reasons.append("NEGATIVE_NUMERATOR")
        elif bottom <= 0:
            reasons.append("NON_POSITIVE_DENOMINATOR")
        else:
            with localcontext(DECIMAL_CONTEXT):
                value = _decimal_string(_percentage(top, bottom, subtract_one=True))
    record = _derived_record(
        ticker=ticker,
        cik=cik,
        definition=definition,
        fiscal_year=fiscal_year,
        inputs=(current, prior),
        reasons=reasons,
        value=value,
        compatibility=compatibility,
        warnings=warnings,
    )
    record["period_start"] = current.get("period_start") if current is not None else None
    record["period_end"] = current.get("period_end") if current is not None else None
    record["metric_observation_id"] = _observation_id(record)
    return record


def _derive_pair(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    first: dict[str, Any] | None,
    second: dict[str, Any] | None,
    fiscal_year: int,
    statement_types: tuple[set[str], set[str]],
    operation: str,
    require_nonnegative_first: bool = False,
    require_nonnegative_second: bool = False,
    negative_equity_reason: bool = False,
) -> dict[str, Any]:
    inputs = (first, second)
    reasons = _input_reasons(inputs)
    compatibility = None
    if not reasons and first is not None and second is not None:
        if not _same_fields(first, second, ("period_class", "period_start", "period_end")):
            reasons.append("PERIOD_MISMATCH")
        if not _same_fields(first, second, ("unit_semantics",)):
            reasons.append("UNIT_MISMATCH")
        if not _same_fields(first, second, ("dimensions",)):
            reasons.append("DIMENSION_MISMATCH")
        if not _same_fields(first, second, ("source_filings",)):
            reasons.append("SOURCE_FILING_MISMATCH")
        compatibility = _basis_compatibility(inputs)
        if compatibility is None:
            reasons.append("BASIS_INCOMPATIBLE")
        for row, expected in zip(inputs, statement_types):
            if row is not None and not _has_statement_type(row, expected):
                reasons.append("PRIMARY_STATEMENT_EVIDENCE_MISSING")
    value = None
    if not reasons and first is not None and second is not None:
        top, bottom = Decimal(first["value"]), Decimal(second["value"])
        if require_nonnegative_first and top < 0:
            reasons.append("NEGATIVE_NUMERATOR")
        elif require_nonnegative_second and bottom < 0:
            reasons.append("CAPEX_SIGN_UNCERTAIN")
        elif operation == "SUBTRACT":
            with localcontext(DECIMAL_CONTEXT):
                value = _decimal_string(_exact_subtract(top, bottom))
        elif bottom <= 0:
            reasons.append("NEGATIVE_EQUITY" if negative_equity_reason and bottom < 0 else "NON_POSITIVE_DENOMINATOR")
        else:
            with localcontext(DECIMAL_CONTEXT):
                value = _decimal_string(_percentage(top, bottom, subtract_one=False))
    return _derived_record(
        ticker=ticker,
        cik=cik,
        definition=definition,
        fiscal_year=fiscal_year,
        inputs=inputs,
        reasons=reasons,
        value=value,
        compatibility=compatibility,
        warnings=[],
    )


def _derive_net_debt(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    debt: dict[str, Any] | None,
    cash: dict[str, Any] | None,
    fiscal_year: int,
) -> dict[str, Any]:
    inputs = (debt, cash)
    reasons = _input_reasons(inputs)
    compatibility = None
    note_allowance = False
    if not reasons and debt is not None and cash is not None:
        if not _same_fields(debt, cash, ("period_class", "period_start", "period_end")):
            reasons.append("PERIOD_MISMATCH")
        if not _same_fields(debt, cash, ("unit_semantics",)):
            reasons.append("UNIT_MISMATCH")
        if not _same_fields(debt, cash, ("dimensions",)):
            reasons.append("DIMENSION_MISMATCH")
        if not _same_fields(debt, cash, ("source_filings",)):
            reasons.append("SOURCE_FILING_MISMATCH")
        compatibility = _basis_compatibility(inputs)
        if compatibility is None:
            reasons.append("BASIS_INCOMPATIBLE")
        if not _has_statement_type(cash, {"BS"}):
            reasons.append("PRIMARY_STATEMENT_EVIDENCE_MISSING")
        if not _has_statement_type(debt, {"BS"}):
            note_allowance = _debt_note_allowed(debt)
            if not note_allowance:
                reasons.append("DIRECT_COMBINED_DEBT_UNAVAILABLE")
    value = None
    if (
        not reasons
        and debt is not None
        and cash is not None
        and (Decimal(debt["value"]) < 0 or Decimal(cash["value"]) < 0)
    ):
        reasons.append("NEGATIVE_BALANCE_COMPONENT")
    if not reasons and debt is not None and cash is not None:
        with localcontext(DECIMAL_CONTEXT):
            value = _decimal_string(
                _exact_subtract(Decimal(debt["value"]), Decimal(cash["value"]))
            )
    record = _derived_record(
        ticker=ticker,
        cik=cik,
        definition=definition,
        fiscal_year=fiscal_year,
        inputs=inputs,
        reasons=reasons,
        value=value,
        compatibility=compatibility,
        warnings=["EXACT_STANDARD_COMBINED_DEBT_NOTE_ALLOWANCE"] if note_allowance else [],
    )
    record["debt_input_policy"] = (
        "EXACT_STANDARD_COMBINED_DEBT_NOTE_ALLOWANCE" if note_allowance else "TYPED_PRIMARY_BS"
    )
    record["debt_note_locator"] = (
        {
            "input_observation_id": debt["metric_observation_id"],
            "cell_id": debt.get("cell_id"),
            "source_fact_ids": copy.deepcopy(debt.get("source_fact_ids", [])),
            "source_filings": copy.deepcopy(debt.get("source_filings", [])),
            "source_snapshot_id": copy.deepcopy(debt.get("source_snapshot_id")),
            "raw_concept_qname": debt.get("raw_concept_qname"),
        }
        if note_allowance and debt is not None
        else None
    )
    return record


def _derived_record(
    *,
    ticker: str,
    cik: str,
    definition: dict[str, Any],
    fiscal_year: int,
    inputs: tuple[dict[str, Any] | None, ...],
    reasons: list[str],
    value: str | None,
    compatibility: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    present = [row for row in inputs if row is not None]
    reasons = _unique(reasons)
    start_values = {row.get("period_start") for row in present}
    end_values = {row.get("period_end") for row in present}
    source_filings = sorted({filing for row in present for filing in row.get("source_filings", [])})
    statement_evidence = [
        copy.deepcopy(evidence)
        for row in present
        for evidence in row.get("primary_statement_evidence", [])
    ]
    observation = {
        "metric_observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "metric_definition_version": definition["definition_version"],
        "source_kind": "DERIVED_METRIC",
        "fiscal_year": fiscal_year,
        "period_class": definition["period_class"],
        "period_start": next(iter(start_values)) if len(start_values) == 1 else None,
        "period_end": next(iter(end_values)) if len(end_values) == 1 else None,
        "view": VIEW,
        "financial_as_of": present[0]["financial_as_of"] if present else None,
        "availability_status": "AVAILABLE" if not reasons and value is not None else "UNAVAILABLE",
        "unavailable_reason": reasons[0] if reasons else None,
        "diagnostic_reasons": reasons,
        "value": value if not reasons else None,
        "unit_kind": definition["unit_kind"],
        "unit": definition["unit"],
        "unit_semantics": copy.deepcopy(present[0].get("unit_semantics")) if present else None,
        "dimensions": copy.deepcopy(present[0].get("dimensions", [])) if present else [],
        "basis_version": present[0].get("basis_version") if present and len({row.get("basis_version") for row in present}) == 1 else None,
        "comparability_policy": compatibility,
        "status": "DERIVED_METRIC" if not reasons and value is not None else "UNAVAILABLE",
        "quality_status": None,
        "quality_reasons": [],
        "mapping_review_required": False if present and all(row.get("mapping_review_required") is False for row in present) else None,
        "semantic_identity": definition["metric_id"],
        "raw_concept_qname": None,
        "raw_concept_taxonomy_family": None,
        "raw_concept_data_type": "xbrli:monetaryItemType" if definition["unit_kind"] == "MONEY" else "xbrli:pureItemType",
        "raw_concept_period_type": "duration" if definition["period_class"] == "FY" else "instant",
        "concept_mapping_version": sorted({str(row.get("concept_mapping_version")) for row in present if row.get("concept_mapping_version")}),
        "selection_rule_version": sorted({str(row.get("selection_rule_version")) for row in present if row.get("selection_rule_version")}),
        "classification_rule_version": sorted({str(row.get("classification_rule_version")) for row in present if row.get("classification_rule_version")}),
        "parser_version": sorted({str(row.get("parser_version")) for row in present if row.get("parser_version")}),
        "cell_id": None,
        "source_fact_ids": sorted({fact for row in present for fact in row.get("source_fact_ids", [])}),
        "source_filings": source_filings,
        "primary_statement_evidence": statement_evidence,
        "source_snapshot_id": sorted({str(row.get("source_snapshot_id")) for row in present if row.get("source_snapshot_id")}),
        "formula": definition["formula"],
        "input_observation_ids": [row["metric_observation_id"] for row in present],
        "input_values": [
            {
                "metric_id": row["metric_id"],
                "observation_id": row["metric_observation_id"],
                "value": row.get("value"),
                "fiscal_year": row.get("fiscal_year"),
                "period_class": row.get("period_class"),
                "period_start": row.get("period_start"),
                "period_end": row.get("period_end"),
            }
            for row in present
        ],
        "compatibility": compatibility,
        "arithmetic_rule_version": ARITHMETIC_RULE_VERSION,
        "warnings": _unique(warnings),
        "trace": None,
    }
    observation["metric_observation_id"] = _observation_id(observation)
    return observation


def _input_reasons(inputs: tuple[dict[str, Any] | None, ...]) -> list[str]:
    reasons: list[str] = []
    for row in inputs:
        if row is None:
            reasons.append("MISSING_INPUT")
        elif row.get("availability_status") != "AVAILABLE" or row.get("value") is None:
            reasons.append(str(row.get("unavailable_reason") or "MISSING_INPUT"))
        elif row.get("source_kind") not in {"REPORTED", "DERIVED_METRIC"}:
            reasons.append("INPUT_SOURCE_KIND_UNSUPPORTED")
        elif row.get("mapping_review_required") is not False:
            reasons.append("MAPPING_REVIEW_REQUIRED")
        elif row.get("quality_status") == "BLOCK":
            reasons.append("QUALITY_BLOCKED")
        elif row.get("unit") != "USD":
            reasons.append("UNIT_NOT_USD")
        elif row.get("dimensions"):
            reasons.append("DIMENSION_MISMATCH")
        else:
            try:
                value = Decimal(str(row["value"]))
                if not value.is_finite():
                    reasons.append("INPUT_NOT_FINITE")
            except (InvalidOperation, TypeError, ValueError):
                reasons.append("INPUT_NOT_FINITE")
    present = [row for row in inputs if row is not None]
    if len({row.get("cik") for row in present}) > 1:
        reasons.append("COMPANY_MISMATCH")
    if len({(row.get("financial_as_of"), row.get("view")) for row in present}) > 1:
        reasons.append("SOURCE_SCOPE_MISMATCH")
    return _unique(reasons)


def _basis_compatibility(inputs: tuple[dict[str, Any] | None, ...]) -> str | None:
    rows = [row for row in inputs if row is not None]
    if len(rows) != len(inputs):
        return None
    bases = [row.get("basis_version") for row in rows]
    if all(value is None for value in bases):
        return ARITHMETIC_POLICY
    if any(value is None for value in bases) or len(set(bases)) != 1:
        return None
    return "DECLARED_BASIS:" + str(bases[0])


def _has_statement_type(row: dict[str, Any], allowed: set[str]) -> bool:
    source_filings = set(row.get("source_filings", []))
    return any(
        allowed.intersection(set(evidence.get("statement_types") or []))
        and bool(
            source_filings.intersection(
                {
                    str(value)
                    for value in (
                        evidence.get("accession"),
                        evidence.get("source_filing_id"),
                    )
                    if value
                }
            )
        )
        for evidence in row.get("primary_statement_evidence", [])
        if isinstance(evidence, dict)
    )


def _debt_note_allowed(row: dict[str, Any]) -> bool:
    return (
        row.get("source_kind") == "REPORTED"
        and row.get("raw_concept_is_standard") is True
        and row.get("raw_concept_qname") == "us-gaap:DebtLongtermAndShorttermCombinedAmount"
        and row.get("raw_concept_data_type") == "xbrli:monetaryItemType"
        and row.get("raw_concept_period_type") == "instant"
        and row.get("period_class") == "INSTANT"
        and row.get("period_start") is None
        and not row.get("dimensions")
        and len(row.get("source_fact_ids", [])) == 1
        and len(row.get("source_filings", [])) == 1
    )


def _same_fields(first: dict[str, Any], second: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return all(first.get(field) == second.get(field) for field in fields)


def _observation_id(row: dict[str, Any]) -> str:
    identity = {
        key: copy.deepcopy(value)
        for key, value in row.items()
        if key not in {"metric_observation_id"}
    }
    return "screening-metric-observation-" + digest_value(identity)[:24]


def _support_rows(companies: list[dict[str, Any]], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for company in companies:
        cik = company["cik"]
        for definition in METRIC_DEFINITIONS:
            rows = [
                row
                for row in observations
                if row["cik"] == cik and row["metric_id"] == definition["metric_id"]
            ]
            available = sum(row["availability_status"] == "AVAILABLE" for row in rows)
            reasons = sorted({row["unavailable_reason"] for row in rows if row.get("unavailable_reason")})
            result.append(
                {
                    "cik": cik,
                    "ticker": company["ticker"],
                    "metric_id": definition["metric_id"],
                    "definition_version": definition["definition_version"],
                    "execution_supported": available > 0,
                    "support_status": "AVAILABLE" if available else "UNAVAILABLE",
                    "available_periods": available,
                    "observed_periods": len(rows),
                    "reasons": reasons,
                }
            )
    return result


def _metric_versions(
    observations: list[dict[str, Any]], source_versions: dict[str, Any]
) -> dict[str, Any]:
    fields = (
        "metric_definition_version",
        "concept_mapping_version",
        "selection_rule_version",
        "classification_rule_version",
        "parser_version",
    )
    observed: dict[str, list[Any]] = {}
    for field in fields:
        values = {
            canonical_json(value)
            for row in observations
            for value in (
                row.get(field)
                if isinstance(row.get(field), list)
                else [row.get(field)]
            )
            if value not in (None, "", [])
        }
        observed[field + "s"] = [json.loads(value) for value in sorted(values)]
    return {
        "arithmetic_rule_version": ARITHMETIC_RULE_VERSION,
        "observed": observed,
        "identity_source_versions": copy.deepcopy(source_versions),
    }


def _verify_analysis_files(root: Path, manifest: dict[str, Any]) -> None:
    declared = _declared_analysis_files(manifest)
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "analysis_manifest.json"
    }
    if set(declared) != actual or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("analysis publication file set mismatch")
    for relative, expected in declared.items():
        path = contained_file(root, relative, "analysis data")
        if sha256_file(path) != expected:
            raise ValueError("analysis publication data hash mismatch")


def _declared_analysis_files(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for company in manifest.get("companies", {}).values():
        for view in company.get("views", {}).values():
            for info in view.get("files", {}).values():
                relative = require_string(info.get("path"), "analysis data path")
                digest = require_string(info.get("sha256"), "analysis data hash")
                if relative in result and result[relative] != digest:
                    raise ValueError("analysis manifest has conflicting file declarations")
                result[relative] = digest
    return dict(sorted(result.items()))


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": str(path.relative_to(root)), "sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _assert_unique(rows: list[dict[str, Any]], fields: tuple[str, ...], label: str) -> None:
    keys = [tuple(canonical_json(row.get(field)) for field in fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {label}")


def _is_usd_unit(unit: Any) -> bool:
    if not isinstance(unit, list) or len(unit) != 2:
        return False
    numerator, denominator = unit
    try:
        numerator = json.loads(numerator) if isinstance(numerator, str) else numerator
        denominator = json.loads(denominator) if isinstance(denominator, str) else denominator
    except (json.JSONDecodeError, TypeError):
        return False
    return numerator == ["iso4217:USD"] and denominator == []


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _percentage(top: Decimal, bottom: Decimal, *, subtract_one: bool) -> Decimal:
    """One rounded division over an exact rational numerator."""
    numerator = _exact_subtract(top, bottom) if subtract_one else top
    scaled = _scale_power_ten(numerator, 2)
    with localcontext(DECIMAL_CONTEXT):
        return scaled / bottom


def _exact_subtract(first: Decimal, second: Decimal) -> Decimal:
    """Subtract finite decimals as scaled integers without context rounding."""
    if not first.is_finite() or not second.is_finite():
        raise ValueError("exact subtraction requires finite decimals")
    exponent = min(first.as_tuple().exponent, second.as_tuple().exponent)
    first_integer = _decimal_integer_at(first, exponent)
    second_integer = _decimal_integer_at(second, exponent)
    return _decimal_from_scaled_integer(first_integer - second_integer, exponent)


def _decimal_integer_at(value: Decimal, exponent: int) -> int:
    parts = value.as_tuple()
    coefficient = int("".join(str(digit) for digit in parts.digits) or "0")
    if parts.sign:
        coefficient = -coefficient
    return coefficient * (10 ** (parts.exponent - exponent))


def _decimal_from_scaled_integer(value: int, exponent: int) -> Decimal:
    sign = 1 if value < 0 else 0
    digits = tuple(int(char) for char in str(abs(value))) if value else (0,)
    return Decimal((sign, digits, exponent))


def _scale_power_ten(value: Decimal, power: int) -> Decimal:
    parts = value.as_tuple()
    return Decimal((parts.sign, parts.digits, parts.exponent + power))


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))

