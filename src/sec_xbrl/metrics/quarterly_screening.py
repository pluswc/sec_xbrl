"""Governed quarterly screening metric publication.

The producer consumes immutable ``prepare_analysis(period_mode="QUARTERLY")``
bundles and an annual screening-metric publication.  It does not open SEC
packages or re-run selection.  Every available value is copied from a prepared
cell or materialized here under one declared arithmetic rule before consumers
read it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from itertools import pairwise
from pathlib import Path
from typing import Any

from sec_xbrl.analysis import open_analysis
from sec_xbrl.metrics.screening import (
    ScreeningMetricReader,
    _declared_analysis_files,
    _verify_analysis_files,
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

VERSION = "quarterly-screening-metric-manifest-v1"
CONFIG_VERSION = "quarterly-screening-metric-config-v1"
MANIFEST = "quarterly_screening_metric_manifest.json"
DEFINITIONS_FILE = "quarter_metric_definitions.json"
SUPPORT_FILE = "quarter_metric_support.json"
OBSERVATIONS_FILE = "quarter_metric_observations.json"
INVENTORY_FILE = "quarter_period_inventory.json"
FILES = (DEFINITIONS_FILE, SUPPORT_FILE, OBSERVATIONS_FILE, INVENTORY_FILE)
VIEW = "LATEST_REPORTED"
ARITHMETIC_POLICY = "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
DECIMAL_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
GIT_SHA1_LENGTH = 40

_SOURCE_ELIGIBILITY_FIELDS = (
    "mapping_review_required",
    "mapping_uncertainty",
    "ambiguity",
    "ambiguous",
    "compatibility_failure",
    "continuity_break",
    "recast_review_required",
    "basis_break",
    "structural_break",
    "recast_break",
)
_IDENTITY_FAILURE_FIELDS = (
    "mapping_uncertainty",
    "ambiguity",
    "ambiguous",
    "compatibility_failure",
)
_ARITHMETIC_BREAK_FIELDS = (
    "basis_break",
    "structural_break",
    "recast_break",
    "continuity_break",
    "recast_review_required",
)


def _reported_definition(
    metric_id: str,
    label: str,
    category: str,
    observation_basis: str,
    *,
    allowed_source_kinds: tuple[str, ...] = ("REPORTED",),
    rule_version: str = "quarter-reported-selection-v1",
    definition_version: str = "quarter-reported-core-v1",
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "label_ko": label,
        "category": category,
        "observation_basis": observation_basis,
        "unit_kind": "MONEY",
        "unit": "USD",
        "canonical_value_scale": "1",
        "source_row_id": metric_id.removeprefix("quarter_"),
        "allowed_source_kinds": list(allowed_source_kinds),
        "definition_version": definition_version,
        "rule_version": rule_version,
        "formula": None,
        "status": "ACTIVE",
    }


def _generic_definition(
    metric_id: str,
    label: str,
    category: str,
    kind: str,
    roles: tuple[tuple[str, str, str], tuple[str, str, str]],
    formula: str,
    rule_version: str,
    *,
    unit_kind: str = "PERCENT",
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "label_ko": label,
        "category": category,
        "observation_basis": "QTD_3M",
        "unit_kind": unit_kind,
        "unit": "USD" if unit_kind == "MONEY" else "PERCENT",
        "canonical_value_scale": "1",
        "allowed_source_kinds": ["DERIVED_METRIC"],
        "definition_version": rule_version,
        "rule_version": rule_version,
        "formula": formula,
        "status": "ACTIVE",
        "input_contract": {
            "version": "quarter-derived-input-scope-v1",
            "kind": kind,
            "inputs": [
                {"input_role": role, "metric_id": source, "value_constraint": constraint}
                for role, source, constraint in roles
            ],
            "denominator_policy": (
                "NOT_APPLICABLE"
                if kind == "SAME_PERIOD_DIFFERENCE"
                else "STRICTLY_POSITIVE"
            ),
            "basis_policy": ARITHMETIC_POLICY,
        },
    }


REPORTED_DEFINITIONS = (
    _reported_definition(
        "quarter_revenue", "분기 매출", "GROWTH", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition(
        "quarter_gross_profit", "분기 매출총이익", "PROFITABILITY", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition(
        "quarter_operating_income", "분기 영업이익", "PROFITABILITY", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition(
        "quarter_net_income", "분기 순이익", "PROFITABILITY", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition(
        "quarter_cfo", "분기 영업활동 현금흐름", "CASH_FLOW", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition(
        "quarter_capex", "분기 유형자산 취득 지출", "CASH_FLOW", "QTD_3M",
        allowed_source_kinds=("REPORTED", "DERIVED_QUARTER"),
        rule_version="approved-core-cumulative-difference-v1",
        definition_version="quarter-core-reported-or-m8-v1",
    ),
    _reported_definition("quarter_assets", "분기말 자산", "FINANCIAL_STABILITY", "INSTANT"),
    _reported_definition("quarter_cash", "분기말 현금 및 현금성자산", "FINANCIAL_STABILITY", "INSTANT"),
    _reported_definition("quarter_liabilities", "분기말 부채", "FINANCIAL_STABILITY", "INSTANT"),
    _reported_definition("quarter_current_assets", "분기말 유동자산", "FINANCIAL_STABILITY", "INSTANT"),
    _reported_definition("quarter_current_liabilities", "분기말 유동부채", "FINANCIAL_STABILITY", "INSTANT"),
)

GENERIC_DEFINITIONS = (
    _generic_definition(
        "quarter_revenue_qoq", "분기 매출 전분기 대비 성장률", "GROWTH",
        "ADJACENT_FISCAL_QUARTER_GROWTH",
        (("CURRENT", "quarter_revenue", "NONNEGATIVE"), ("PRIOR", "quarter_revenue", "POSITIVE")),
        "(current revenue - prior revenue) * 100 / prior revenue",
        "quarter-revenue-qoq-v1",
    ),
    _generic_definition(
        "quarter_revenue_yoy", "분기 매출 전년 동기 대비 성장률", "GROWTH",
        "SAME_FISCAL_QUARTER_YOY_GROWTH",
        (("CURRENT", "quarter_revenue", "NONNEGATIVE"), ("PRIOR", "quarter_revenue", "POSITIVE")),
        "(current revenue - prior-year same-quarter revenue) * 100 / prior-year revenue",
        "quarter-revenue-yoy-v1",
    ),
    _generic_definition(
        "quarter_gross_margin", "분기 매출총이익률", "PROFITABILITY",
        "SAME_PERIOD_RATIO",
        (("NUMERATOR", "quarter_gross_profit", "FINITE"), ("DENOMINATOR", "quarter_revenue", "POSITIVE")),
        "gross profit * 100 / revenue", "quarter-gross-margin-v1",
    ),
    _generic_definition(
        "quarter_operating_margin", "분기 영업이익률", "PROFITABILITY",
        "SAME_PERIOD_RATIO",
        (("NUMERATOR", "quarter_operating_income", "FINITE"), ("DENOMINATOR", "quarter_revenue", "POSITIVE")),
        "operating income * 100 / revenue", "quarter-operating-margin-v1",
    ),
    _generic_definition(
        "quarter_standardized_fcf", "표준화 분기 FCF(영업현금흐름−유형자산취득지출)", "CASH_FLOW",
        "SAME_PERIOD_DIFFERENCE",
        (("CFO", "quarter_cfo", "FINITE"), ("CAPEX", "quarter_capex", "NONNEGATIVE")),
        "quarter CFO - quarter PP&E purchases", "quarter-standardized-fcf-v1",
        unit_kind="MONEY",
    ),
)

TTM_DEFINITION = {
    "metric_id": "ttm_revenue",
    "label_ko": "최근 4개 분기 매출 합계",
    "category": "GROWTH",
    "observation_basis": "TTM",
    "unit_kind": "MONEY",
    "unit": "USD",
    "canonical_value_scale": "1",
    "allowed_source_kinds": ["DERIVED_METRIC"],
    "definition_version": "quarter-ttm-v1",
    "rule_version": "quarter-ttm-contiguous-v1",
    "input_metric_id": "quarter_revenue",
    "formula": "SUM(4 contiguous eligible QTD observations)",
    "status": "ACTIVE",
}

METRIC_DEFINITIONS = (*REPORTED_DEFINITIONS, *GENERIC_DEFINITIONS, TTM_DEFINITION)
DEFINITION_BY_ID = {row["metric_id"]: row for row in METRIC_DEFINITIONS}


@dataclass(frozen=True, slots=True)
class QuarterlyMetricPublication:
    root: Path
    publication_id: str
    manifest_path: Path


def publish_quarterly_screening_metrics(
    config_path: Path | str, destination: Path | str
) -> QuarterlyMetricPublication:
    """Publish one immutable fixed-spine quarterly metric bundle."""
    config_file = regular_file(Path(config_path), "quarterly metric config")
    config = _validate_config(read_json(config_file, "quarterly metric config"))
    destination_path = safe_new_destination(Path(destination), "quarterly metric publication")
    annual_root = real_directory(Path(config["annual_metric_root"]), "annual metric parent")
    annual_manifest_path = regular_file(
        annual_root / "screening_metric_manifest.json", "annual metric manifest"
    )
    if sha256_file(annual_manifest_path) != config["annual_metric_manifest_sha256"]:
        raise ValueError("annual metric manifest differs from quarterly config")
    annual = ScreeningMetricReader(annual_root)
    if annual.manifest.get("financial_as_of") != config["financial_as_of"]:
        raise ValueError("annual and quarterly financial-as-of differ")
    configured_ciks = sorted(row["cik"] for row in config["companies"])
    if sorted(annual.manifest.get("configured_ciks", [])) != configured_ciks:
        raise ValueError("annual and quarterly company membership differ")

    definitions = copy.deepcopy(list(METRIC_DEFINITIONS))
    all_observations: list[dict[str, Any]] = []
    all_inventory: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for company in config["companies"]:
        client, source = _open_company_source(company, config["financial_as_of"])
        observations, inventory = _company_records(
            ticker=company["ticker"],
            cik=company["cik"],
            financial_as_of=config["financial_as_of"],
            client=client,
            spine=config["global_quarter_spine"],
        )
        all_observations.extend(observations)
        all_inventory.extend(inventory)
        sources.append(source)
    all_observations.sort(
        key=lambda row: (
            row["cik"], row["metric_id"], row["calendar_year"], row["calendar_quarter"]
        )
    )
    all_inventory.sort(
        key=lambda row: (row["cik"], row["calendar_year"], row["calendar_quarter"])
    )
    support = _support_rows(config["companies"], all_observations)
    membership_hash = _membership_hash(configured_ciks)
    annual_parent = {
        "schema_version": "screening-metric-publication-v1",
        "publication_id": annual.manifest["publication_id"],
        "manifest_sha256": config["annual_metric_manifest_sha256"],
        "company_membership_sha256": membership_hash,
    }
    identity = {
        "config": config,
        "annual_parent": annual_parent,
        "definitions": definitions,
        "support": support,
        "observations": all_observations,
        "period_inventory": all_inventory,
        "sources": sources,
    }
    publication_id = "quarterly-screening-metrics-" + digest_value(identity)[:24]

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_path.parent / f".{destination_path.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        payloads = {
            DEFINITIONS_FILE: ("quarter-metric-definitions-v1", definitions),
            SUPPORT_FILE: ("quarter-metric-support-v1", support),
            OBSERVATIONS_FILE: ("quarter-metric-observations-v1", all_observations),
            INVENTORY_FILE: ("quarter-period-inventory-v1", all_inventory),
        }
        for filename, (schema_version, records) in payloads.items():
            write_json(
                staging / filename,
                {
                    "schema_version": schema_version,
                    "fixture_kind": config["fixture_kind"],
                    "records": records,
                },
            )
        files = {
            filename: {
                "record_count": len(payloads[filename][1]),
                "sha256": sha256_file(staging / filename),
                "size": (staging / filename).stat().st_size,
            }
            for filename in FILES
        }
        manifest = {
            "schema_version": VERSION,
            "publication_id": publication_id,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "fixture_kind": config["fixture_kind"],
            "financial_as_of": config["financial_as_of"],
            "source_commit_sha": config["source_commit_sha"],
            "global_quarter_spine": copy.deepcopy(config["global_quarter_spine"]),
            "universe": {
                "ciks": configured_ciks,
                "company_count": len(configured_ciks),
                "company_membership_sha256": membership_hash,
            },
            "annual_parent": annual_parent,
            "governance_parents": sources,
            "config": config,
            "config_path": str(config_file),
            "config_sha256": sha256_file(config_file),
            "serialization_contract": _serialization_contract(),
            "counts": {
                "definitions": len(definitions),
                "support": len(support),
                "observations": len(all_observations),
                "period_inventory": len(all_inventory),
            },
            "files": files,
            "limitations": [
                "Calendar buckets do not assert fiscal-period equivalence across issuers.",
                "Unavailable values remain unavailable and are never zero-filled or backfilled.",
            ],
        }
        write_json(staging / MANIFEST, manifest)
        atomic_replace(staging, destination_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    publication = QuarterlyMetricPublication(
        destination_path, publication_id, destination_path / MANIFEST
    )
    QuarterlyMetricReader(destination_path).verify_all()
    return publication


class QuarterlyMetricReader:
    """Verify publication bytes, identity, fixed grain and support counts."""

    def __init__(self, root: Path | str, *, manifest_sha256: str | None = None) -> None:
        self.root = real_directory(Path(root), "quarterly metric publication")
        path = regular_file(self.root / MANIFEST, "quarterly metric manifest")
        if manifest_sha256 is not None and sha256_file(path) != manifest_sha256:
            raise ValueError("quarterly metric manifest differs from pinned SHA-256")
        self.manifest = read_json(path, "quarterly metric manifest")
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("unsupported quarterly metric publication")
        self.definitions = self._payload(DEFINITIONS_FILE)
        self.support = self._payload(SUPPORT_FILE)
        self.observations = self._payload(OBSERVATIONS_FILE)
        self.period_inventory = self._payload(INVENTORY_FILE)
        self.verify_all()

    def _payload(self, filename: str) -> list[dict[str, Any]]:
        info = self.manifest.get("files", {}).get(filename)
        if not isinstance(info, dict):
            raise TypeError("quarterly payload declaration is missing")
        path = contained_file(self.root, filename, "quarterly payload")
        if sha256_file(path) != info.get("sha256") or path.stat().st_size != info.get("size"):
            raise ValueError("quarterly payload changed")
        payload = read_json(path, "quarterly payload")
        rows = payload.get("records") if isinstance(payload, dict) else None
        if (
            not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or len(rows) != info.get("record_count")
            or payload.get("fixture_kind") != self.manifest.get("fixture_kind")
        ):
            raise ValueError("quarterly payload envelope differs")
        return rows

    def verify_all(self) -> dict[str, Any]:
        actual = {
            path.name
            for path in self.root.iterdir()
            if path.is_file() and path.name != MANIFEST
        }
        if actual != set(FILES) or set(self.manifest.get("files", {})) != set(FILES):
            raise ValueError("quarterly payload file set changed")
        if any(path.is_symlink() for path in self.root.iterdir()):
            raise ValueError("quarterly publication cannot contain symlinks")
        if self.definitions != list(METRIC_DEFINITIONS):
            raise ValueError("quarterly definitions differ from governed producer definitions")
        ciks = self.manifest.get("universe", {}).get("ciks")
        if not isinstance(ciks, list) or ciks != sorted(set(ciks)):
            raise ValueError("quarterly universe is not unique and ordered")
        if _membership_hash(ciks) != self.manifest["universe"].get(
            "company_membership_sha256"
        ):
            raise ValueError("quarterly universe membership hash changed")
        spine = [
            (row["calendar_year"], row["calendar_quarter"])
            for row in self.manifest.get("global_quarter_spine", [])
        ]
        definition_ids = [row["metric_id"] for row in self.definitions]
        observation_keys = [
            (row["cik"], row["metric_id"], row["calendar_year"], row["calendar_quarter"])
            for row in self.observations
        ]
        support_keys = [(row["cik"], row["metric_id"]) for row in self.support]
        inventory_keys = [
            (row["cik"], row["calendar_year"], row["calendar_quarter"])
            for row in self.period_inventory
        ]
        expected_observations = {
            (cik, metric, year, quarter)
            for cik in ciks
            for metric in definition_ids
            for year, quarter in spine
        }
        if len(observation_keys) != len(set(observation_keys)) or set(observation_keys) != expected_observations:
            raise ValueError("quarterly observation grain changed")
        if set(support_keys) != {(cik, metric) for cik in ciks for metric in definition_ids}:
            raise ValueError("quarterly support grain changed")
        if set(inventory_keys) != {(cik, year, quarter) for cik in ciks for year, quarter in spine}:
            raise ValueError("quarterly inventory grain changed")
        expected_support = _support_rows(
            [{"cik": cik, "ticker": next(row["ticker"] for row in self.support if row["cik"] == cik)} for cik in ciks],
            self.observations,
        )
        if expected_support != self.support:
            raise ValueError("quarterly support differs from observations")
        counts = self.manifest.get("counts", {})
        if counts != {
            "definitions": len(self.definitions),
            "support": len(self.support),
            "observations": len(self.observations),
            "period_inventory": len(self.period_inventory),
        }:
            raise ValueError("quarterly counts changed")
        publication_id = "quarterly-screening-metrics-" + digest_value(
            {
                "config": self.manifest["config"],
                "annual_parent": self.manifest["annual_parent"],
                "definitions": self.definitions,
                "support": self.support,
                "observations": self.observations,
                "period_inventory": self.period_inventory,
                "sources": self.manifest["governance_parents"],
            }
        )[:24]
        if self.manifest.get("publication_id") != publication_id:
            raise ValueError("quarterly publication identity changed")
        return {
            "publication_id": publication_id,
            "companies": len(ciks),
            **counts,
        }


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != CONFIG_VERSION:
        raise ValueError("unsupported quarterly metric config")
    financial_as_of = require_string(value.get("financial_as_of"), "financial_as_of")
    date.fromisoformat(financial_as_of)
    companies = value.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("quarterly metric config requires companies")
    normalized = []
    for index, row in enumerate(companies):
        if not isinstance(row, dict):
            raise TypeError("quarterly company config must be an object")
        normalized.append(
            {
                "ticker": require_ticker(row.get("ticker"), f"companies[{index}].ticker"),
                "cik": require_cik(row.get("cik"), f"companies[{index}].cik"),
                "analysis_root": require_string(row.get("analysis_root"), f"companies[{index}].analysis_root"),
                "analysis_manifest_sha256": _require_sha(row.get("analysis_manifest_sha256"), "analysis_manifest_sha256"),
            }
        )
    if len({row["ticker"] for row in normalized}) != len(normalized) or len({row["cik"] for row in normalized}) != len(normalized):
        raise ValueError("quarterly config companies must have unique ticker and CIK")
    source_commit = _require_git_sha(value.get("source_commit_sha"), "source_commit_sha")
    fixture_kind = require_string(value.get("fixture_kind", "ACTUAL_PREPARED"), "fixture_kind")
    if fixture_kind != "ACTUAL_PREPARED":
        raise ValueError("production quarterly publisher accepts ACTUAL_PREPARED only")
    expected_spine = _quarter_spine(financial_as_of)
    declared = value.get("global_quarter_spine", expected_spine)
    if declared != expected_spine:
        raise ValueError("quarterly config spine differs from completed cutoff buckets")
    return {
        "schema_version": CONFIG_VERSION,
        "financial_as_of": financial_as_of,
        "fixture_kind": fixture_kind,
        "source_commit_sha": source_commit,
        "annual_metric_root": require_string(value.get("annual_metric_root"), "annual_metric_root"),
        "annual_metric_manifest_sha256": _require_sha(value.get("annual_metric_manifest_sha256"), "annual_metric_manifest_sha256"),
        "global_quarter_spine": copy.deepcopy(expected_spine),
        "companies": sorted(normalized, key=lambda row: row["cik"]),
    }


def _open_company_source(
    company: dict[str, Any], financial_as_of: str
) -> tuple[Any, dict[str, Any]]:
    root = real_directory(Path(company["analysis_root"]), f"{company['ticker']} quarterly analysis")
    manifest_path = regular_file(root / "analysis_manifest.json", "quarterly analysis manifest")
    digest = sha256_file(manifest_path)
    if digest != company["analysis_manifest_sha256"]:
        raise ValueError(f"{company['ticker']}: quarterly analysis manifest changed")
    client = open_analysis(root)
    _verify_analysis_files(root, client.manifest)
    if client.manifest.get("period_mode", "QUARTERLY") != "QUARTERLY":
        raise ValueError(f"{company['ticker']}: quarterly analysis period mode differs")
    if client.manifest.get("quarter_source_evidence") != {
        "included": True,
        "rule_version": "quarter-typed-primary-pre-evidence-v1",
    }:
        raise ValueError(f"{company['ticker']}: quarterly analysis lacks typed source evidence")
    if set(client.manifest.get("companies", {})) != {company["ticker"]}:
        raise ValueError(f"{company['ticker']}: quarterly analysis must contain one company")
    scope = client.manifest["companies"][company["ticker"]]
    if scope.get("as_of") != financial_as_of:
        raise ValueError(f"{company['ticker']}: quarterly analysis as-of differs")
    files = scope.get("views", {}).get(VIEW, {}).get("files", {})
    required = {"columns", "core_rows", "core_cells", *(f"trace_{x}" for x in "0123456789abcdef")}
    if not required <= set(files):
        raise ValueError(f"{company['ticker']}: quarterly analysis lacks required files")
    return client, {
        "kind": "QUARTERLY_ANALYSIS_PUBLICATION",
        "ticker": company["ticker"],
        "cik": company["cik"],
        "root": str(root),
        "publication_id": client.manifest["publication_id"],
        "manifest_sha256": digest,
        "declared_files": _declared_analysis_files(client.manifest),
    }


def _company_records(
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    client: Any,
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    columns = client._records(ticker, VIEW, "columns")
    rows = client._records(ticker, VIEW, "core_rows")
    cells = client._records(ticker, VIEW, "core_cells")
    traces = [
        trace
        for digit in "0123456789abcdef"
        for trace in client._records(ticker, VIEW, f"trace_{digit}")
    ]
    return build_quarterly_company_records(
        ticker=ticker,
        cik=cik,
        financial_as_of=financial_as_of,
        columns=columns,
        rows=rows,
        cells=cells,
        traces=traces,
        spine=spine,
    )


def build_quarterly_company_records(
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one company's fixed-spine records from already prepared data."""
    ticker = require_ticker(ticker, "ticker")
    cik = require_cik(cik, "cik")
    date.fromisoformat(financial_as_of)
    row_ids = {row.get("row_id") for row in rows}
    required_rows = {row["source_row_id"] for row in REPORTED_DEFINITIONS}
    if not required_rows <= row_ids:
        raise ValueError(f"{ticker}: quarterly analysis profile lacks required core rows")
    trace_by_cell = {row.get("cell_id"): row for row in traces}
    if None in trace_by_cell or len(trace_by_cell) != len(traces):
        raise ValueError(f"{ticker}: duplicate or missing trace cell identity")
    column_by_id = {row.get("fiscal_time_series_column_id"): row for row in columns}
    if None in column_by_id or len(column_by_id) != len(columns):
        raise ValueError(f"{ticker}: duplicate or missing quarter column identity")
    cells_by_row: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        cells_by_row.setdefault(str(cell.get("row_id")), []).append(cell)

    direct_all: dict[str, list[dict[str, Any]]] = {}
    for definition in REPORTED_DEFINITIONS:
        direct_all[definition["metric_id"]] = _prepared_metric_rows(
            ticker=ticker,
            cik=cik,
            financial_as_of=financial_as_of,
            definition=definition,
            cells=cells_by_row.get(definition["source_row_id"], []),
            trace_by_cell=trace_by_cell,
            column_by_id=column_by_id,
        )
    inventory = _period_inventory(ticker, cik, spine, direct_all)
    output: list[dict[str, Any]] = []
    output_by_metric_bucket: dict[tuple[str, int, int], dict[str, Any]] = {}
    for definition in REPORTED_DEFINITIONS:
        grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in direct_all[definition["metric_id"]]:
            grouped.setdefault((row["calendar_year"], row["calendar_quarter"]), []).append(row)
        for bucket in spine:
            key = (bucket["calendar_year"], bucket["calendar_quarter"])
            choices = grouped.get(key, [])
            if len(choices) == 1:
                selected = choices[0]
            else:
                selected = _unavailable_observation(
                    ticker=ticker,
                    cik=cik,
                    definition=definition,
                    financial_as_of=financial_as_of,
                    bucket=key,
                    reason="MULTIPLE_CANDIDATES" if choices else _inventory_missing_reason(inventory, key),
                    candidate_evidence=choices,
                )
            output.append(selected)
            output_by_metric_bucket[(definition["metric_id"], *key)] = selected

    fiscal_index: dict[tuple[str, int, str], dict[str, Any]] = {}
    fiscal_conflicts: set[tuple[str, int, str]] = set()
    for rows_for_metric in direct_all.values():
        for row in rows_for_metric:
            if row["availability_status"] == "AVAILABLE":
                coordinate = (row["metric_id"], row["fiscal_year"], row["fiscal_quarter"])
                if coordinate in fiscal_conflicts:
                    continue
                if coordinate in fiscal_index:
                    fiscal_index.pop(coordinate, None)
                    fiscal_conflicts.add(coordinate)
                else:
                    fiscal_index[coordinate] = row
    for definition in GENERIC_DEFINITIONS:
        for bucket in spine:
            key = (bucket["calendar_year"], bucket["calendar_quarter"])
            row = _generic_observation(
                ticker=ticker,
                cik=cik,
                financial_as_of=financial_as_of,
                definition=definition,
                bucket=key,
                current_by_bucket=output_by_metric_bucket,
                fiscal_index=fiscal_index,
                inventory=inventory,
            )
            output.append(row)
            output_by_metric_bucket[(definition["metric_id"], *key)] = row
    for bucket in spine:
        key = (bucket["calendar_year"], bucket["calendar_quarter"])
        output.append(
            _ttm_observation(
                ticker=ticker,
                cik=cik,
                financial_as_of=financial_as_of,
                bucket=key,
                current_by_bucket=output_by_metric_bucket,
                fiscal_index=fiscal_index,
                inventory=inventory,
            )
        )
    output.sort(key=lambda row: (row["metric_id"], row["calendar_year"], row["calendar_quarter"]))
    return output, inventory


def _prepared_metric_rows(
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    definition: dict[str, Any],
    cells: list[dict[str, Any]],
    trace_by_cell: dict[str, dict[str, Any]],
    column_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for cell in cells:
        trace = trace_by_cell.get(cell.get("cell_id"))
        column = column_by_id.get(cell.get("column_id"))
        if trace is None or column is None:
            raise ValueError(f"{ticker}: prepared cell lacks trace or column")
        period_class = definition["observation_basis"]
        if cell.get("period_class") != period_class:
            continue
        end = cell.get("end") or column.get("actual_instant_date") or column.get("actual_end_date")
        if not isinstance(end, str):
            continue
        bucket = _bucket(end)
        prepared = _prepared_observation(
            ticker=ticker,
            cik=cik,
            financial_as_of=financial_as_of,
            definition=definition,
            cell=cell,
            trace=trace,
            column=column,
            bucket=bucket,
        )
        result.append(prepared)
    return result


def _prepared_observation(
    *,
    ticker: str,
    cik: str,
    financial_as_of: str,
    definition: dict[str, Any],
    cell: dict[str, Any],
    trace: dict[str, Any],
    column: dict[str, Any],
    bucket: tuple[int, int],
) -> dict[str, Any]:
    lineage = trace.get("value_lineage")
    reasons: list[str] = []
    if not isinstance(lineage, dict):
        lineage = {}
        reasons.append("SOURCE_LINEAGE_MISSING")
    status = cell.get("status")
    source_kind = "REPORTED" if status == "REPORTED" else "DERIVED_QUARTER" if status == "DERIVED" else "UNAVAILABLE"
    if source_kind not in definition["allowed_source_kinds"]:
        reasons.append(str(cell.get("source_reason") or cell.get("reason") or "INPUT_NOT_REPORTED"))
    if cell.get("as_of") != financial_as_of or lineage.get("selection_as_of_date") != financial_as_of:
        reasons.append("SOURCE_SCOPE_MISMATCH")
    if cell.get("selection_view") != VIEW or lineage.get("selection_view") != VIEW:
        reasons.append("SOURCE_SCOPE_MISMATCH")
    if cell.get("dimensions"):
        reasons.append("DIMENSION_MISMATCH")
    if not _is_usd_unit(cell.get("unit")):
        reasons.append("UNIT_NOT_USD")
    if lineage.get("mapping_review_required") is not False:
        reasons.append("MAPPING_REVIEW_REQUIRED")
    quality_status = lineage.get("quality_status")
    quality_reasons = list(lineage.get("quality_reasons") or [])
    quality_blocking = quality_status == "BLOCK" or bool(lineage.get("quality_blocking"))
    if quality_blocking:
        reasons.append("QUALITY_BLOCKED")
    value = _finite_decimal_string(cell.get("value"))
    if value is None:
        reasons.append(str(cell.get("source_reason") or cell.get("reason") or "INPUT_NOT_REPORTED"))
    start = None if definition["observation_basis"] == "INSTANT" else cell.get("start")
    end = cell.get("end") or column.get("actual_instant_date") or column.get("actual_end_date")
    if not isinstance(end, str) or (start is not None and not isinstance(start, str)):
        reasons.append("PERIOD_SCOPE_INCOMPLETE")
    duration = None
    if isinstance(start, str) and isinstance(end, str):
        duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if definition["observation_basis"] == "QTD_3M" and not 75 <= duration <= 105:
            reasons.append("UNSUPPORTED_FISCAL_QUARTER_DURATION")
    reasons.extend(
        _prepared_source_scope_reasons(
            cell=cell,
            lineage=lineage,
            source_kind=source_kind,
            expected_period_class=definition["observation_basis"],
            expected_start=start,
            expected_end=end,
            expected_value=value,
        )
    )
    fiscal_year = cell.get("fiscal_year")
    quarter = cell.get("fiscal_quarter")
    fiscal_quarter = f"Q{quarter}" if quarter in {1, 2, 3, 4} else None
    if type(fiscal_year) is not int or fiscal_quarter is None:
        reasons.append("FISCAL_COORDINATE_MISSING")
    if source_kind == "REPORTED":
        source_lineage = _reported_source(
            ticker=ticker,
            cik=cik,
            metric_id=definition["metric_id"],
            financial_as_of=financial_as_of,
            cell=cell,
            lineage=lineage,
            start=start,
            end=end,
            duration=duration,
            value=value,
            quality_status=quality_status,
            quality_reasons=quality_reasons,
            quality_blocking=quality_blocking,
        )
        reasons.extend(
            _reported_anchor_reasons(source_lineage, financial_as_of, cik)
        )
    elif source_kind == "DERIVED_QUARTER":
        # A governed M8 value is eligible only when both selected raw inputs and
        # the prepared derived output retain an arithmetic-compatible scope.
        # Preserve the outer flags in lineage; never clear them from the source
        # projection merely because the two nested inputs agree with each other.
        reasons.extend(_arithmetic_source_reasons(lineage))
        source_lineage = _derived_quarter_lineage(
            ticker=ticker,
            cik=cik,
            metric_id=definition["metric_id"],
            financial_as_of=financial_as_of,
            cell=cell,
            lineage=lineage,
            quality_status=quality_status,
            quality_reasons=quality_reasons,
            quality_blocking=quality_blocking,
        )
        if len(source_lineage["derivation_inputs"]) != 2:
            reasons.append("DERIVATION_INPUTS_INCOMPLETE")
        for source in source_lineage["derivation_inputs"]:
            reasons.extend(_reported_anchor_reasons(source, financial_as_of, cik))
        if lineage.get("derivation_rule_version") != definition["rule_version"]:
            reasons.append("DERIVATION_RULE_MISMATCH")
        reasons.extend(
            _derived_quarter_reasons(
                fiscal_quarter=fiscal_quarter,
                period_start=start,
                period_end=end,
                value=value,
                sources=source_lineage["derivation_inputs"],
                expected_scope={
                    "cik": cik,
                    "unit": "USD" if _is_usd_unit(cell.get("unit")) else None,
                    "dimensions": copy.deepcopy(cell.get("dimensions") or []),
                    "selection_view": lineage.get("selection_view"),
                    "selection_as_of_date": lineage.get("selection_as_of_date"),
                    "basis_version": cell.get("basis_version"),
                    "structural_version": lineage.get("structural_version"),
                    "recast_version": lineage.get("recast_version"),
                    "canonical_mapping_version": lineage.get("concept_mapping_version"),
                    "company_canonical_concept_id": lineage.get(
                        "company_canonical_concept_id"
                    ),
                },
                output_filed_date=lineage.get("filed_date"),
                output_report_date=lineage.get("report_date"),
                financial_as_of=financial_as_of,
            )
        )
    else:
        source_lineage = {
            "candidate_evidence": [copy.deepcopy({"cell": cell, "trace": trace})],
            "candidate_source_ids": [],
            "derivation_inputs": [],
        }
    reasons = _unique(reasons)
    available = not reasons and value is not None
    record = {
        "observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "canonical_metric_id": definition["metric_id"],
        "definition_version": definition["definition_version"],
        "observation_basis": definition["observation_basis"],
        "calendar_year": bucket[0],
        "calendar_quarter": bucket[1],
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "period_class": definition["observation_basis"],
        "period_start": start,
        "period_end": end,
        "end_convention": "EXCLUSIVE" if end else None,
        "filed_date": lineage.get("filed_date"),
        "report_date": lineage.get("report_date"),
        "selection_view": VIEW,
        "selection_as_of_date": financial_as_of,
        "source_kind": source_kind if available else "UNAVAILABLE",
        "availability_status": "AVAILABLE" if available else "UNAVAILABLE",
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "value": value if available else None,
        "unit": "USD",
        "dimensions": copy.deepcopy(cell.get("dimensions") or []),
        "basis_version": cell.get("basis_version"),
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        "quality_blocking": quality_blocking,
        "canonical_mapping_version": lineage.get("concept_mapping_version"),
        "company_canonical_concept_id": lineage.get("company_canonical_concept_id"),
        "structural_version": lineage.get("structural_version"),
        "recast_version": lineage.get("recast_version"),
        "source_lineage": source_lineage,
    }
    for field in _SOURCE_ELIGIBILITY_FIELDS:
        record[field] = copy.deepcopy(lineage.get(field))
    if available and source_kind == "DERIVED_QUARTER":
        record["derived_metric_id"] = require_string(
            lineage.get("derived_metric_id"), "derived quarter identity"
        )
    if available and source_kind == "REPORTED":
        for field in (
            "accession", "source_id", "source_filing_id", "source_fact_id", "context_id",
            "raw_concept_qname", "raw_concept_namespace_uri", "unit_id",
            "context_instant_date", "duration_days", "selected_source_ids",
        ):
            record[field] = copy.deepcopy(source_lineage.get(field))
    record["observation_id"] = _observation_id(record)
    return record


def _reported_source(
    *, ticker: str, cik: str, metric_id: str, financial_as_of: str,
    cell: dict[str, Any], lineage: dict[str, Any], start: str | None,
    end: str | None, duration: int | None, value: str | None,
    quality_status: Any, quality_reasons: list[Any], quality_blocking: bool,
) -> dict[str, Any]:
    fact_id = lineage.get("selected_source_fact_id") or cell.get("source_fact_id")
    snapshot = lineage.get("source_snapshot_id")
    source_id = f"{snapshot}:{fact_id}" if snapshot and fact_id else None
    source_filing_id = lineage.get("source_filing_id")
    actual_start = lineage.get("context_start_date")
    actual_end = lineage.get("context_end_date") or lineage.get("context_instant_date")
    actual_dimensions = copy.deepcopy(
        lineage.get("canonical_dimension_signature")
        if lineage.get("canonical_dimension_signature") is not None
        else cell.get("dimensions") or []
    )
    actual_basis = lineage.get("basis_version")
    actual_cik = _source_cik(lineage)
    evidence = _statement_evidence(
        cell=cell,
        lineage=lineage,
        source_filing_id=source_filing_id,
        statement_type=_statement_type(metric_id.removeprefix("quarter_")),
    )
    source = {
        "accession": lineage.get("accession"),
        "cik": actual_cik,
        "ticker": ticker,
        "canonical_metric_id": metric_id,
        "company_canonical_concept_id": lineage.get("company_canonical_concept_id"),
        "canonical_mapping_version": lineage.get("concept_mapping_version"),
        "source_kind": "REPORTED",
        "source_id": source_id,
        "source_filing_id": source_filing_id,
        "source_fact_id": fact_id,
        "source_snapshot_id": snapshot,
        "context_id": lineage.get("context_id"),
        "raw_concept_qname": lineage.get("raw_concept_qname"),
        "raw_concept_namespace_uri": lineage.get("raw_concept_namespace_uri"),
        "unit": "USD" if _lineage_is_usd(lineage) else None,
        "unit_id": lineage.get("unit_id"),
        "dimensions": actual_dimensions,
        "period_class": lineage.get("period_class"),
        "period_start": actual_start,
        "period_end": actual_end,
        "context_instant_date": lineage.get("context_instant_date"),
        "duration_days": _duration_days(actual_start, actual_end),
        "end_convention": "EXCLUSIVE" if actual_end else None,
        "filed_date": lineage.get("filed_date"),
        "report_date": lineage.get("report_date"),
        "selection_view": lineage.get("selection_view"),
        "selection_as_of_date": lineage.get("selection_as_of_date"),
        "basis_version": actual_basis,
        "structural_version": lineage.get("structural_version"),
        "recast_version": lineage.get("recast_version"),
        "value": _finite_decimal_string(lineage.get("value_numeric")),
        "availability_status": "AVAILABLE",
        "reason": None,
        "reasons": [],
        "quality_status": lineage.get("quality_status", quality_status),
        "quality_reasons": list(lineage.get("quality_reasons") or quality_reasons),
        "quality_blocking": bool(lineage.get("quality_blocking")) or quality_blocking,
        "mapping_review_required": lineage.get("mapping_review_required"),
        "ambiguity": lineage.get("ambiguity"),
        "continuity_break": lineage.get("continuity_break"),
        "recast_review_required": lineage.get("recast_review_required"),
        "primary_statement_evidence": evidence,
        "candidate_evidence": [],
        "candidate_source_ids": [source_id] if source_id else [],
        "selected_source_ids": [source_id] if source_id else [],
        "derivation_inputs": [],
        "compatibility_policy": None,
    }
    for field in _SOURCE_ELIGIBILITY_FIELDS:
        source[field] = copy.deepcopy(lineage.get(field))
    return source


def _prepared_source_scope_reasons(
    *,
    cell: dict[str, Any],
    lineage: dict[str, Any],
    source_kind: str,
    expected_period_class: str,
    expected_start: str | None,
    expected_end: str | None,
    expected_value: str | None,
) -> list[str]:
    """Attest the prepared projection without replacing elected source scope."""
    reasons: list[str] = []
    if lineage.get("period_class") != expected_period_class:
        reasons.append("SOURCE_SCOPE_MISMATCH")
    lineage_start = lineage.get("context_start_date")
    lineage_end = lineage.get("context_end_date") or lineage.get("context_instant_date")
    if lineage_start != expected_start or lineage_end != expected_end:
        reasons.append("SOURCE_SCOPE_MISMATCH")
    dimensions = lineage.get("canonical_dimension_signature")
    if dimensions is not None and dimensions != (cell.get("dimensions") or []):
        reasons.append("SOURCE_SCOPE_MISMATCH")
    if lineage.get("basis_version") != cell.get("basis_version"):
        reasons.append("BASIS_INCOMPATIBLE")
    if source_kind == "REPORTED":
        if (
            lineage.get("selected_source_fact_id") != cell.get("source_fact_id")
            or lineage.get("source_filing_id") not in (cell.get("source_filing_ids") or [])
        ):
            reasons.append("SOURCE_IDENTITY_MISMATCH")
        raw_value = _finite_decimal_string(lineage.get("value_numeric"))
        if not _decimal_values_equal(raw_value, expected_value):
            reasons.append("SOURCE_VALUE_MISMATCH")
    if not _lineage_is_usd(lineage):
        reasons.append("UNIT_NOT_USD")
    if lineage.get("ambiguity"):
        reasons.append("SOURCE_AMBIGUITY")
    if lineage.get("continuity_break"):
        reasons.append("CONTINUITY_BREAK")
    if lineage.get("recast_review_required"):
        reasons.append("RECAST_REVIEW_REQUIRED")
    return _unique(reasons)


def _derived_quarter_lineage(
    *, ticker: str, cik: str, metric_id: str, financial_as_of: str,
    cell: dict[str, Any], lineage: dict[str, Any], quality_status: Any,
    quality_reasons: list[Any], quality_blocking: bool,
) -> dict[str, Any]:
    inputs = []
    for raw in lineage.get("source_inputs") or []:
        if not isinstance(raw, dict):
            continue
        start = raw.get("context_start_date")
        end = raw.get("context_end_date") or raw.get("context_instant_date")
        duration = (
            (date.fromisoformat(end) - date.fromisoformat(start)).days
            if isinstance(start, str) and isinstance(end, str)
            else None
        )
        input_cell = {
            "row_id": cell.get("row_id"),
            "dimensions": copy.deepcopy(raw.get("canonical_dimension_signature") or []),
            "primary_statement_evidence": copy.deepcopy(
                raw.get("primary_statement_evidence") or []
            ),
        }
        inputs.append(
            _reported_source(
                ticker=ticker,
                cik=cik,
                metric_id=metric_id,
                financial_as_of=financial_as_of,
                cell={
                    **input_cell,
                    "source_fact_id": raw.get("selected_source_fact_id"),
                    "source_filing_ids": [raw.get("source_filing_id")],
                    "period_class": raw.get("period_class"),
                    "basis_version": raw.get("basis_version"),
                },
                lineage=raw,
                start=start,
                end=end,
                duration=duration,
                value=_finite_decimal_string(raw.get("value_numeric")),
                quality_status=raw.get("quality_status"),
                quality_reasons=list(raw.get("quality_reasons") or []),
                quality_blocking=bool(raw.get("quality_blocking")) or raw.get("quality_status") == "BLOCK",
            )
        )
    result = {
        "canonical_mapping_version": lineage.get("concept_mapping_version"),
        "company_canonical_concept_id": lineage.get("company_canonical_concept_id"),
        "dimensions": copy.deepcopy(cell.get("dimensions") or []),
        "basis_version": cell.get("basis_version"),
        "structural_version": lineage.get("structural_version"),
        "recast_version": lineage.get("recast_version"),
        "candidate_evidence": [],
        "candidate_source_ids": [],
        "selected_source_ids": [],
        "derivation_inputs": inputs,
        "derivation_rule_version": lineage.get("derivation_rule_version"),
        "formula": lineage.get("formula"),
        "source_filing_ids": copy.deepcopy(lineage.get("source_filing_ids") or []),
        "compatibility_policy": ARITHMETIC_POLICY,
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        "quality_blocking": quality_blocking,
    }
    for field in _SOURCE_ELIGIBILITY_FIELDS:
        result[field] = copy.deepcopy(lineage.get(field))
    return result


def _statement_evidence(
    *,
    cell: dict[str, Any],
    lineage: dict[str, Any],
    source_filing_id: Any,
    statement_type: str,
) -> list[dict[str, Any]]:
    candidates = (
        cell.get("primary_statement_evidence")
        or lineage.get("primary_statement_evidence")
        or []
    )
    if not isinstance(candidates, list) or not isinstance(source_filing_id, str):
        return []
    return [
        copy.deepcopy(evidence)
        for evidence in candidates
        if isinstance(evidence, dict)
        and evidence.get("source_filing_id") == source_filing_id
        and evidence.get("cik") == _source_cik(lineage)
        and evidence.get("accession") == lineage.get("accession")
        and evidence.get("source_network_type") == "PRE"
        and statement_type in (evidence.get("statement_types") or [])
        and isinstance(evidence.get("role_uri"), str)
        and evidence["role_uri"]
    ]


def _statement_type(row_id: str) -> str:
    if row_id in {"revenue", "gross_profit", "operating_income", "net_income"}:
        return "IS"
    if row_id in {"cfo", "capex"}:
        return "CF"
    return "BS"


def _derived_quarter_reasons(
    *,
    fiscal_quarter: str | None,
    period_start: str | None,
    period_end: str | None,
    value: str | None,
    sources: list[dict[str, Any]],
    expected_scope: dict[str, Any],
    output_filed_date: Any,
    output_report_date: Any,
    financial_as_of: str,
) -> list[str]:
    if len(sources) != 2:
        return ["DERIVATION_INPUTS_INCOMPLETE"]
    later, earlier = sources
    expected_classes = {
        "Q2": ("YTD_6M", "QTD_3M"),
        "Q3": ("YTD_9M", "YTD_6M"),
        "Q4": ("FY", "YTD_9M"),
    }
    reasons: list[str] = []
    if (
        (later.get("period_class"), earlier.get("period_class"))
        != expected_classes.get(fiscal_quarter)
        or later.get("period_start") != earlier.get("period_start")
        or earlier.get("period_end") != period_start
        or later.get("period_end") != period_end
    ):
        reasons.append("DERIVATION_PERIOD_MISMATCH")
    for field in (
        "cik",
        "unit",
        "dimensions",
        "selection_view",
        "selection_as_of_date",
        "basis_version",
        "structural_version",
        "recast_version",
        "canonical_mapping_version",
        "company_canonical_concept_id",
    ):
        if canonical_json(later.get(field)) != canonical_json(earlier.get(field)):
            reasons.append("DERIVATION_SCOPE_MISMATCH")
    for source in sources:
        for field, expected in expected_scope.items():
            if canonical_json(source.get(field)) != canonical_json(expected):
                reasons.append("DERIVATION_OUTPUT_SCOPE_MISMATCH")
        reasons.extend(_arithmetic_source_reasons(source))
    filed_dates = [source.get("filed_date") for source in sources]
    if (
        any(not isinstance(value, str) for value in filed_dates)
        or output_filed_date != max(filed_dates, default=None)
        or output_report_date != later.get("report_date")
    ):
        reasons.append("DERIVATION_SOURCE_DATE_MISMATCH")
    try:
        cutoff = date.fromisoformat(financial_as_of)
        output_filed = date.fromisoformat(str(output_filed_date))
    except ValueError:
        reasons.append("DERIVATION_SOURCE_DATE_MISMATCH")
    else:
        if output_filed > cutoff:
            reasons.append("DERIVATION_SOURCE_DATE_MISMATCH")
    try:
        expected = _exact_subtract(Decimal(later["value"]), Decimal(earlier["value"]))
        actual = Decimal(value) if value is not None else None
    except (InvalidOperation, KeyError, TypeError):
        reasons.append("DERIVATION_VALUE_INVALID")
    else:
        if actual != expected:
            reasons.append("DERIVATION_VALUE_MISMATCH")
    return reasons


def _reported_anchor_reasons(
    source: dict[str, Any], financial_as_of: str, expected_cik: str
) -> list[str]:
    """Reject an elected value unless its immutable prepared-source scope is complete."""
    reasons: list[str] = []
    for field in (
        "accession",
        "cik",
        "canonical_metric_id",
        "canonical_mapping_version",
        "source_id",
        "source_filing_id",
        "source_fact_id",
        "source_snapshot_id",
        "context_id",
        "raw_concept_qname",
        "raw_concept_namespace_uri",
        "unit_id",
        "period_class",
        "period_end",
        "filed_date",
        "report_date",
        "selection_view",
        "selection_as_of_date",
        "value",
    ):
        if not isinstance(source.get(field), str) or not source[field]:
            reasons.append("SOURCE_ANCHOR_INCOMPLETE")
            break
    if source.get("source_kind") != "REPORTED":
        reasons.append("SOURCE_KIND_MISMATCH")
    if source.get("unit") != "USD" or not isinstance(source.get("dimensions"), list):
        reasons.append("SOURCE_SCOPE_MISMATCH")
    if source.get("period_class") == "INSTANT":
        if source.get("period_start") is not None or source.get("duration_days") is not None:
            reasons.append("PERIOD_SCOPE_INCOMPLETE")
        if source.get("context_instant_date") != source.get("period_end"):
            reasons.append("PERIOD_SCOPE_INCOMPLETE")
    else:
        start, end = source.get("period_start"), source.get("period_end")
        duration = _duration_days(start, end)
        if duration is None or source.get("duration_days") != duration:
            reasons.append("PERIOD_SCOPE_INCOMPLETE")
    if source.get("mapping_review_required") is not False:
        reasons.append("MAPPING_REVIEW_REQUIRED")
    reasons.extend(_identity_source_reasons(source))
    if source.get("continuity_break"):
        reasons.append("CONTINUITY_BREAK")
    if source.get("recast_review_required"):
        reasons.append("RECAST_REVIEW_REQUIRED")
    if source.get("quality_blocking") or source.get("quality_status") == "BLOCK":
        reasons.append("QUALITY_BLOCKED")
    if not source.get("primary_statement_evidence"):
        reasons.append("PRIMARY_STATEMENT_EVIDENCE_MISSING")
    snapshot = source.get("source_snapshot_id")
    if (
        source.get("cik") != expected_cik
        or not isinstance(snapshot, str)
        or not snapshot.startswith(f"l1:{source.get('cik')}:")
    ):
        reasons.append("SOURCE_IDENTITY_MISMATCH")
    try:
        cutoff = date.fromisoformat(financial_as_of)
        filed = date.fromisoformat(str(source.get("filed_date")))
        report = date.fromisoformat(str(source.get("report_date")))
        period_end = date.fromisoformat(str(source.get("period_end")))
    except ValueError:
        reasons.append("SOURCE_DATE_INVALID")
    else:
        if filed > cutoff or report > filed or period_end > filed:
            reasons.append("SOURCE_DATE_INVALID")
    if (
        source.get("selection_view") != VIEW
        or source.get("selection_as_of_date") != financial_as_of
    ):
        reasons.append("SOURCE_SCOPE_MISMATCH")
    return _unique(reasons)


def _identity_source_reasons(source: dict[str, Any]) -> list[str]:
    reasons = []
    for field in _IDENTITY_FAILURE_FIELDS:
        if source.get(field):
            reasons.append(
                "SOURCE_AMBIGUITY"
                if field in {"ambiguity", "ambiguous"}
                else field.upper()
            )
    return _unique(reasons)


def _arithmetic_source_reasons(source: dict[str, Any]) -> list[str]:
    """Reject declared source incompatibility without hiding reported values."""
    reasons = _identity_source_reasons(source)
    if source.get("mapping_review_required") is not False:
        reasons.append("MAPPING_REVIEW_REQUIRED")
    for field in _ARITHMETIC_BREAK_FIELDS:
        if source.get(field):
            reasons.append(field.upper())
    if source.get("quality_blocking") or source.get("quality_status") == "BLOCK":
        reasons.append("QUALITY_BLOCKED")
    return _unique(reasons)


def _prepared_arithmetic_reasons(row: dict[str, Any]) -> list[str]:
    reasons = _arithmetic_source_reasons(row)
    lineage = row.get("source_lineage")
    if not isinstance(lineage, dict):
        return _unique([*reasons, "SOURCE_LINEAGE_MISSING"])
    reasons.extend(_arithmetic_source_reasons(lineage))
    inputs = lineage.get("derivation_inputs") or []
    if not isinstance(inputs, list):
        return _unique([*reasons, "DERIVATION_INPUTS_INCOMPLETE"])
    for source in inputs:
        if not isinstance(source, dict):
            reasons.append("DERIVATION_INPUTS_INCOMPLETE")
            continue
        reasons.extend(_arithmetic_source_reasons(source))
    return _unique(reasons)


def _period_inventory(
    ticker: str,
    cik: str,
    spine: list[dict[str, Any]],
    prepared: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    candidates: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
    for rows in prepared.values():
        for row in rows:
            if row.get("period_end") is None:
                continue
            scope = {
                "accession": row.get("accession") or row["source_lineage"].get("accession"),
                "filed_date": row.get("filed_date"),
                "report_date": row.get("report_date"),
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_quarter": row.get("fiscal_quarter"),
                "period_start": row.get("period_start"),
                "period_end": row.get("period_end"),
                "duration_days": (
                    (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days
                    if row.get("period_start") else None
                ),
            }
            period_identity = canonical_json(
                {
                    key: scope[key]
                    for key in (
                        "fiscal_year",
                        "fiscal_quarter",
                        "period_start",
                        "period_end",
                        "duration_days",
                    )
                }
            )
            bucket_rows = candidates.setdefault(
                (row["calendar_year"], row["calendar_quarter"]), {}
            )
            previous = bucket_rows.get(period_identity)
            if previous is None or (
                str(scope.get("filed_date") or ""), str(scope.get("accession") or "")
            ) > (
                str(previous.get("filed_date") or ""), str(previous.get("accession") or "")
            ):
                bucket_rows[period_identity] = scope
    result = []
    for bucket in spine:
        key = (bucket["calendar_year"], bucket["calendar_quarter"])
        rows = list(candidates.get(key, {}).values())
        duration_rows = [row for row in rows if row["period_start"] is not None]
        selected_pool = duration_rows or rows
        selected = selected_pool[0] if len(selected_pool) == 1 else None
        result.append(
            {
                "inventory_id": f"quarter-period:{cik}:{key[0]}Q{key[1]}",
                "cik": cik,
                "ticker": ticker,
                "calendar_year": key[0],
                "calendar_quarter": key[1],
                "bucket_status": (
                    "NO_FILING_AS_OF_CUTOFF" if not rows else "PERIOD_AVAILABLE" if selected else "PERIOD_CONFLICT"
                ),
                "candidate_periods": sorted(rows, key=canonical_json),
                "accession": selected.get("accession") if selected else None,
                "filed_date": selected.get("filed_date") if selected else None,
                "report_date": selected.get("report_date") if selected else None,
                "fiscal_year": selected.get("fiscal_year") if selected else None,
                "fiscal_quarter": selected.get("fiscal_quarter") if selected else None,
                "period_start": selected.get("period_start") if selected else None,
                "period_end": selected.get("period_end") if selected else None,
                "reported_duration_days": selected.get("duration_days") if selected else None,
                "end_convention": "EXCLUSIVE" if selected else None,
            }
        )
    return result


def _inventory_missing_reason(
    inventory: list[dict[str, Any]], bucket: tuple[int, int]
) -> str:
    row = next(
        item
        for item in inventory
        if (item["calendar_year"], item["calendar_quarter"]) == bucket
    )
    return "NO_FILING_AS_OF_CUTOFF" if row["bucket_status"] == "NO_FILING_AS_OF_CUTOFF" else "INPUT_NOT_REPORTED"


def _unavailable_observation(
    *, ticker: str, cik: str, definition: dict[str, Any], financial_as_of: str,
    bucket: tuple[int, int], reason: str, candidate_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    record = {
        "observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "canonical_metric_id": definition["metric_id"],
        "definition_version": definition["definition_version"],
        "observation_basis": definition["observation_basis"],
        "calendar_year": bucket[0],
        "calendar_quarter": bucket[1],
        "fiscal_year": None,
        "fiscal_quarter": None,
        "period_class": definition["observation_basis"],
        "period_start": None,
        "period_end": None,
        "end_convention": None,
        "filed_date": None,
        "report_date": None,
        "selection_view": VIEW,
        "selection_as_of_date": financial_as_of,
        "source_kind": "UNAVAILABLE",
        "availability_status": "UNAVAILABLE",
        "reason": reason,
        "reasons": [reason],
        "value": None,
        "unit": definition["unit"],
        "dimensions": [],
        "basis_version": None,
        "quality_status": None,
        "quality_reasons": [],
        "quality_blocking": False,
        "canonical_mapping_version": None,
        "company_canonical_concept_id": None,
        "structural_version": None,
        "recast_version": None,
        "source_lineage": {
            "candidate_evidence": copy.deepcopy(candidate_evidence),
            "candidate_source_ids": [],
            "selected_source_ids": [],
            "derivation_inputs": [],
        },
    }
    record["observation_id"] = _observation_id(record)
    return record


def _generic_observation(
    *, ticker: str, cik: str, financial_as_of: str, definition: dict[str, Any],
    bucket: tuple[int, int], current_by_bucket: dict[tuple[str, int, int], dict[str, Any]],
    fiscal_index: dict[tuple[str, int, str], dict[str, Any]],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    contract = definition["input_contract"]
    declarations = contract["inputs"]
    kind = contract["kind"]
    current_metric = declarations[0]["metric_id"]
    current = current_by_bucket.get((current_metric, *bucket))
    second: dict[str, Any] | None = None
    if current is not None and current.get("availability_status") == "AVAILABLE":
        if kind == "SAME_PERIOD_DIFFERENCE" or kind == "SAME_PERIOD_RATIO":
            second = current_by_bucket.get((declarations[1]["metric_id"], *bucket))
        else:
            year = current.get("fiscal_year")
            quarter = current.get("fiscal_quarter")
            if type(year) is int and isinstance(quarter, str) and quarter in {"Q1", "Q2", "Q3", "Q4"}:
                q = int(quarter[1])
                if kind == "ADJACENT_FISCAL_QUARTER_GROWTH":
                    prior_year, prior_q = (year, q - 1) if q > 1 else (year - 1, 4)
                else:
                    prior_year, prior_q = year - 1, q
                second = fiscal_index.get((declarations[1]["metric_id"], prior_year, f"Q{prior_q}"))
    reasons = _generic_input_reasons(current, second, kind)
    value = None
    if not reasons and current is not None and second is not None:
        first_value = Decimal(current["value"])
        second_value = Decimal(second["value"])
        if kind == "SAME_PERIOD_DIFFERENCE":
            if second_value < 0:
                reasons.append("CAPEX_SIGN_UNCERTAIN")
            else:
                value = _decimal_string(_exact_subtract(first_value, second_value))
        elif second_value <= 0:
            reasons.append("NON_POSITIVE_DENOMINATOR")
        elif kind.endswith("GROWTH") and first_value < 0:
            reasons.append("NEGATIVE_CURRENT_VALUE")
        else:
            value = _decimal_string(_percentage(first_value, second_value, subtract_one=kind.endswith("GROWTH")))
    if reasons or current is None or second is None or value is None:
        return _unavailable_observation(
            ticker=ticker, cik=cik, definition=definition, financial_as_of=financial_as_of,
            bucket=bucket, reason=_unique(reasons)[0] if reasons else _inventory_missing_reason(inventory, bucket),
            candidate_evidence=[row for row in (current, second) if row is not None],
        )
    role_inputs = []
    for declaration, prepared in zip(declarations, (current, second)):
        role_inputs.append({**copy.deepcopy(prepared), "input_role": declaration["input_role"]})
    record = _derived_output_base(
        ticker=ticker,
        cik=cik,
        financial_as_of=financial_as_of,
        definition=definition,
        bucket=bucket,
        current=current,
        inputs=role_inputs,
        value=value,
        basis_version=current.get("basis_version"),
        compatibility_policy=ARITHMETIC_POLICY,
    )
    return record


def _generic_input_reasons(
    current: dict[str, Any] | None, second: dict[str, Any] | None, kind: str
) -> list[str]:
    rows = (current, second)
    reasons = []
    for row in rows:
        if row is None or row.get("availability_status") != "AVAILABLE":
            reasons.append(str((row or {}).get("reason") or "MISSING_INPUT"))
    if reasons or current is None or second is None:
        return _unique(reasons)
    for row in rows:
        reasons.extend(_prepared_arithmetic_reasons(row))
    for field in ("cik", "dimensions", "selection_view", "selection_as_of_date"):
        if current.get(field) != second.get(field):
            reasons.append("SOURCE_SCOPE_MISMATCH")
    for field in (
        "basis_version",
        "structural_version",
        "recast_version",
        "canonical_mapping_version",
    ):
        if current.get(field) != second.get(field):
            reasons.append("BASIS_INCOMPATIBLE")
    if current.get("unit") != "USD" or second.get("unit") != "USD":
        reasons.append("UNIT_NOT_USD")
    if kind.startswith("SAME_PERIOD_"):
        for field in ("period_start", "period_end", "period_class", "fiscal_year", "fiscal_quarter"):
            if current.get(field) != second.get(field):
                reasons.append("PERIOD_MISMATCH")
        current_endpoint = _endpoint_source(current)
        second_endpoint = _endpoint_source(second)
        if current_endpoint is None or second_endpoint is None:
            reasons.append("SOURCE_ENDPOINT_MISSING")
        else:
            endpoint_fields = (
                "cik",
                "source_filing_id",
                "accession",
                "period_end",
                "selection_view",
                "selection_as_of_date",
                "unit",
                "dimensions",
                "basis_version",
            )
            if any(
                canonical_json(current_endpoint.get(field))
                != canonical_json(second_endpoint.get(field))
                for field in endpoint_fields
            ):
                reasons.append("SOURCE_FILING_MISMATCH")
    elif (
        current.get("metric_id") != second.get("metric_id")
        or current.get("definition_version") != second.get("definition_version")
        or current.get("company_canonical_concept_id")
        != second.get("company_canonical_concept_id")
    ):
        reasons.append("SEMANTIC_IDENTITY_MISMATCH")
    elif kind == "ADJACENT_FISCAL_QUARTER_GROWTH" and second.get("period_end") != current.get("period_start"):
        reasons.append("PERIOD_NOT_CONTIGUOUS")
    elif kind == "SAME_FISCAL_QUARTER_YOY_GROWTH" and second.get("period_end") > current.get("period_start"):
        reasons.append("PERIOD_OVERLAP")
    return _unique(reasons)


def _endpoint_source(row: dict[str, Any]) -> dict[str, Any] | None:
    lineage = row.get("source_lineage")
    if not isinstance(lineage, dict):
        return None
    if row.get("source_kind") == "REPORTED":
        return lineage
    if row.get("source_kind") != "DERIVED_QUARTER":
        return None
    matches = [
        source
        for source in lineage.get("derivation_inputs") or []
        if isinstance(source, dict) and source.get("period_end") == row.get("period_end")
    ]
    return matches[0] if len(matches) == 1 else None


def _derived_output_base(
    *, ticker: str, cik: str, financial_as_of: str, definition: dict[str, Any],
    bucket: tuple[int, int], current: dict[str, Any], inputs: list[dict[str, Any]],
    value: str, basis_version: str | None, compatibility_policy: str,
) -> dict[str, Any]:
    record = {
        "observation_id": "pending",
        "cik": cik,
        "ticker": ticker,
        "metric_id": definition["metric_id"],
        "canonical_metric_id": definition["metric_id"],
        "definition_version": definition["definition_version"],
        "observation_basis": definition["observation_basis"],
        "calendar_year": bucket[0],
        "calendar_quarter": bucket[1],
        "fiscal_year": current["fiscal_year"],
        "fiscal_quarter": current["fiscal_quarter"],
        "period_class": definition["observation_basis"],
        "period_start": inputs[0]["period_start"] if definition["observation_basis"] == "TTM" else current["period_start"],
        "period_end": current["period_end"],
        "end_convention": "EXCLUSIVE",
        "filed_date": max(row["filed_date"] for row in inputs),
        "report_date": current["report_date"],
        "selection_view": VIEW,
        "selection_as_of_date": financial_as_of,
        "source_kind": "DERIVED_METRIC",
        "availability_status": "AVAILABLE",
        "reason": None,
        "reasons": [],
        "value": value,
        "unit": definition["unit"],
        "dimensions": copy.deepcopy(current["dimensions"]),
        "basis_version": basis_version,
        "quality_status": None,
        "quality_reasons": _unique([reason for row in inputs for reason in row.get("quality_reasons", [])]),
        "quality_blocking": any(row.get("quality_blocking") for row in inputs),
        "canonical_mapping_version": current.get("canonical_mapping_version"),
        "company_canonical_concept_id": current.get("company_canonical_concept_id"),
        "structural_version": current.get("structural_version"),
        "recast_version": current.get("recast_version"),
        "source_lineage": {
            "derivation_inputs": inputs,
            "derivation_rule_version": definition["rule_version"],
            "compatibility_policy": compatibility_policy,
            "formula": definition["formula"],
            "candidate_evidence": [],
            "candidate_source_ids": [],
            "selected_source_ids": [],
        },
    }
    for field in _SOURCE_ELIGIBILITY_FIELDS:
        values = [row.get(field) for row in inputs if field in row]
        record[field] = copy.deepcopy(current.get(field))
        record["source_lineage"][field] = (
            copy.deepcopy(current.get(field))
            if not values or all(value == current.get(field) for value in values)
            else copy.deepcopy(values)
        )
    record["observation_id"] = _observation_id(record)
    return record


def _ttm_observation(
    *, ticker: str, cik: str, financial_as_of: str, bucket: tuple[int, int],
    current_by_bucket: dict[tuple[str, int, int], dict[str, Any]],
    fiscal_index: dict[tuple[str, int, str], dict[str, Any]],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    definition = TTM_DEFINITION
    current = current_by_bucket.get(("quarter_revenue", *bucket))
    inputs: list[dict[str, Any]] = []
    if current is not None and current.get("availability_status") == "AVAILABLE":
        year, quarter = current["fiscal_year"], int(current["fiscal_quarter"][1])
        coordinates = []
        for offset in range(3, -1, -1):
            absolute = year * 4 + quarter - 1 - offset
            y, q0 = divmod(absolute, 4)
            coordinates.append((y, f"Q{q0 + 1}"))
        inputs = [
            fiscal_index.get(("quarter_revenue", y, q))
            for y, q in coordinates
        ]
    reasons = []
    if len(inputs) != 4 or any(row is None or row.get("availability_status") != "AVAILABLE" for row in inputs):
        reasons.append("INPUTS_NOT_COMPATIBLE")
    else:
        prepared = [row for row in inputs if row is not None]
        for row in prepared:
            reasons.extend(_prepared_arithmetic_reasons(row))
        if any(a["period_end"] != b["period_start"] for a, b in pairwise(prepared)):
            reasons.append("INPUTS_NOT_CONTIGUOUS")
        bases = [row.get("basis_version") for row in prepared]
        if (
            any(not isinstance(value, str) or not value for value in bases)
            or len(set(bases)) != 1
        ):
            reasons.append("INPUTS_NOT_COMPATIBLE")
        for field in (
            "cik",
            "unit",
            "dimensions",
            "selection_view",
            "selection_as_of_date",
            "company_canonical_concept_id",
            "canonical_mapping_version",
            "structural_version",
            "recast_version",
        ):
            if len({canonical_json(row.get(field)) for row in prepared}) != 1:
                reasons.append("INPUTS_NOT_COMPATIBLE")
    if reasons or current is None:
        return _unavailable_observation(
            ticker=ticker, cik=cik, definition=definition, financial_as_of=financial_as_of,
            bucket=bucket, reason=_unique(reasons)[0] if reasons else _inventory_missing_reason(inventory, bucket),
            candidate_evidence=[row for row in inputs if row is not None],
        )
    prepared = [row for row in inputs if row is not None]
    value = _decimal_string(_exact_sum(Decimal(row["value"]) for row in prepared))
    return _derived_output_base(
        ticker=ticker,
        cik=cik,
        financial_as_of=financial_as_of,
        definition=definition,
        bucket=bucket,
        current=current,
        inputs=copy.deepcopy(prepared),
        value=value,
        basis_version=prepared[0]["basis_version"],
        compatibility_policy="DECLARED_BASIS:" + prepared[0]["basis_version"],
    )


def _support_rows(
    companies: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for company in sorted(companies, key=lambda row: row["cik"]):
        for definition in METRIC_DEFINITIONS:
            rows = [
                row
                for row in observations
                if row["cik"] == company["cik"] and row["metric_id"] == definition["metric_id"]
            ]
            source_counts = Counter(row["source_kind"] for row in rows)
            reason_counts = Counter(row["reason"] for row in rows if row.get("reason"))
            available = sum(row["availability_status"] == "AVAILABLE" for row in rows)
            result.append(
                {
                    "cik": company["cik"],
                    "ticker": company["ticker"],
                    "metric_id": definition["metric_id"],
                    "definition_version": definition["definition_version"],
                    "fixed_bucket_count": len(rows),
                    "available_bucket_count": available,
                    "unavailable_bucket_count": len(rows) - available,
                    "source_kind_counts": dict(sorted(source_counts.items())),
                    "unavailable_reason_counts": dict(sorted(reason_counts.items())),
                }
            )
    return result


def _serialization_contract() -> dict[str, Any]:
    return {
        "scope_inheritance": "FORBIDDEN",
        "allowed_selection_views": ["AS_FILED", "LATEST_REPORTED"],
        "recast_view_declared": False,
        "observation_required_scope_fields": [
            "cik", "canonical_metric_id", "selection_view", "selection_as_of_date",
            "dimensions", "quality_status", "quality_reasons", "quality_blocking",
        ],
        "source_anchor_required_scope_fields": [
            "cik", "canonical_metric_id", "source_kind", "selection_view",
            "selection_as_of_date", "dimensions", "quality_status",
            "quality_reasons", "quality_blocking",
        ],
        "derived_meaning_fields": [
            "source_kind", "derivation_rule_version", "compatibility_policy", "basis_version",
        ],
    }


def _quarter_spine(financial_as_of: str) -> list[dict[str, Any]]:
    cutoff = date.fromisoformat(financial_as_of)
    last_index = cutoff.year * 4 + (cutoff.month - 1) // 3 - 1
    result = []
    for offset in range(7, -1, -1):
        year, q0 = divmod(last_index - offset, 4)
        result.append({"calendar_year": year, "calendar_quarter": q0 + 1, "status": "COMPLETED_BUCKET"})
    return result


def _bucket(exclusive_end: str) -> tuple[int, int]:
    inclusive = date.fromisoformat(exclusive_end) - timedelta(days=1)
    return inclusive.year, (inclusive.month - 1) // 3 + 1


def _membership_hash(ciks: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(ciks) + "\n").encode()).hexdigest()


def _require_sha(value: Any, field: str) -> str:
    digest = require_string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _require_git_sha(value: Any, field: str) -> str:
    commit = require_string(value, field)
    if len(commit) != GIT_SHA1_LENGTH or any(
        char not in "0123456789abcdef" for char in commit
    ):
        raise ValueError(f"{field} must be a lowercase 40-character Git commit SHA")
    return commit


def _is_usd_unit(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    try:
        numerator = json.loads(value[0]) if isinstance(value[0], str) else value[0]
        denominator = json.loads(value[1]) if isinstance(value[1], str) else value[1]
    except (json.JSONDecodeError, TypeError):
        return False
    return numerator == ["iso4217:USD"] and denominator == []


def _lineage_is_usd(lineage: dict[str, Any]) -> bool:
    numerator = lineage.get("unit_numerator_measures")
    denominator = lineage.get("unit_denominator_measures")
    try:
        numerator = json.loads(numerator) if isinstance(numerator, str) else numerator
        denominator = json.loads(denominator) if isinstance(denominator, str) else denominator
    except (json.JSONDecodeError, TypeError):
        return False
    return numerator == ["iso4217:USD"] and denominator == []


def _source_cik(lineage: dict[str, Any]) -> str | None:
    snapshot = lineage.get("source_snapshot_id")
    if not isinstance(snapshot, str):
        return None
    parts = snapshot.split(":", 3)
    if (
        len(parts) != 4
        or parts[0] != "l1"
        or len(parts[1]) != 10
        or not parts[1].isdigit()
    ):
        return None
    return parts[1]


def _duration_days(start: Any, end: Any) -> int | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _finite_decimal_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return value if number.is_finite() else None


def _decimal_values_equal(first: str | None, second: str | None) -> bool:
    if first is None or second is None:
        return False
    try:
        left, right = Decimal(first), Decimal(second)
    except InvalidOperation:
        return False
    return left.is_finite() and right.is_finite() and left == right


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _exact_subtract(first: Decimal, second: Decimal) -> Decimal:
    parts = second.as_tuple()
    exact_negative = Decimal((0 if parts.sign else 1, parts.digits, parts.exponent))
    return _exact_sum((first, exact_negative))


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    values = list(values)
    if not values or any(not value.is_finite() for value in values):
        raise ValueError("exact sum requires finite decimals")
    exponent = min(value.as_tuple().exponent for value in values)
    total = 0
    for value in values:
        parts = value.as_tuple()
        coefficient = int("".join(str(digit) for digit in parts.digits) or "0")
        total += (-coefficient if parts.sign else coefficient) * (10 ** (parts.exponent - exponent))
    sign = 1 if total < 0 else 0
    digits = tuple(int(char) for char in str(abs(total))) if total else (0,)
    return Decimal((sign, digits, exponent))


def _percentage(first: Decimal, second: Decimal, *, subtract_one: bool) -> Decimal:
    numerator = _exact_subtract(first, second) if subtract_one else first
    parts = numerator.as_tuple()
    scaled = Decimal((parts.sign, parts.digits, parts.exponent + 2))
    with localcontext(DECIMAL_CONTEXT):
        return scaled / second


def _observation_id(row: dict[str, Any]) -> str:
    identity = {key: copy.deepcopy(value) for key, value in row.items() if key != "observation_id"}
    return "quarter-observation-" + digest_value(identity)[:24]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish or inspect governed quarterly metrics")
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--config", type=Path, required=True)
    publish.add_argument("--destination", type=Path, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--publication", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "publish":
        result = publish_quarterly_screening_metrics(args.config, args.destination)
        print(canonical_json({"publication_id": result.publication_id, "root": str(result.root)}))
    else:
        print(canonical_json(QuarterlyMetricReader(args.publication).verify_all()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
