"""Deterministic screening over immutable prepared screening datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from contextlib import nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sec_xbrl.screening.cohort_union import ScreeningCohortUnionReader
from sec_xbrl.screening.common import (
    canonical_json,
    digest_value,
    require_cik,
    require_string,
    safe_new_destination,
    sha256_file,
)
from sec_xbrl.screening.company_descriptions import CompanyDescriptionReader
from sec_xbrl.screening.dataset import ScreeningDatasetReader
from sec_xbrl.screening.dataset_v2 import ScreeningDatasetV2Reader, open_screening_dataset
from sec_xbrl.screening.dataset_v3 import ScreeningDatasetV3Reader, _share_v3_readers
from sec_xbrl.screening.explorer import (
    LATEST_PERIOD_MODES,
    LATEST_QUARTER,
    ScreeningExplorer,
    latest_company_period,
    latest_period_observation,
    public_copy,
)
from sec_xbrl.screening.governed_delta import ScreeningGovernedDeltaReader
from sec_xbrl.screening.runtime_projection import (
    ScreeningRuntimeProjection,
    compact_observation,
    hydrate_observation,
    observation_rows,
)
from sec_xbrl.screening.store import ScreeningStore

ScreeningReader = ScreeningDatasetReader | ScreeningDatasetV2Reader | ScreeningDatasetV3Reader | ScreeningRuntimeProjection | ScreeningCohortUnionReader | ScreeningGovernedDeltaReader

ENGINE_VERSION = "screening-executor-v1"
EXPORT_VERSION = "screen-run-export-v1"
XLSX_LONG_TEXT_VERSION = "screen-run-xlsx-long-text-v1"
XLSX_DIRECT_TEXT_LIMIT = 32_000
XLSX_CHUNK_TEXT_LIMIT = 16_000
OPERATORS = {"GT", "GTE", "LT", "LTE", "EQ"}
AGGREGATES = {"PASS", "FAIL", "UNDETERMINED"}
VISIBLE_COLUMNS = {
    "company",
    "ticker",
    "name",
    "cik",
    "sic",
    "sic_code",
    "aggregate",
    "predicates",
    "decision",
}


def _preview_response(
    content: dict[str, Any], dataset_id: str, evaluated: dict[str, Any], *, include_evidence: bool = True,
) -> dict[str, Any]:
    frozen = json.loads(canonical_json(content))
    transport = {} if include_evidence else {"include_evidence": False}
    result = json.loads(canonical_json(evaluated))
    preview_hash = digest_value({"dataset_id": dataset_id, "content": frozen, "result": result, **transport})
    return {
        **result,
        **transport,
        "persistence_state": "PREVIEW",
        "content": frozen,
        "condition_hash": digest_value(frozen),
        "preview_hash": preview_hash,
    }



def _compact_evaluation(evaluated: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in evaluated["rows"]:
        predicates = [
            {**predicate, "observation": compact_observation(observation)} if
            (observation := predicate["observation"]) is not None else predicate
            for predicate in row["predicates"]
        ]
        rows.append({**row, "predicates": predicates})
    return {**evaluated, "rows": rows}


def _validate_evidence_option(include_evidence: bool) -> None:
    if type(include_evidence) is not bool:
        raise TypeError("include_evidence must be a boolean")


_NY = ZoneInfo("America/New_York")
_FIXED_QUARTER = "FIXED_CALENDAR_QUARTER_END"
_QUARTER_MODES = frozenset({_FIXED_QUARTER, LATEST_QUARTER})


def _batch_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("batch date requires YYYY-MM-DD")
    return parsed


def _batch_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("batch readiness timestamp requires a timezone")
    return parsed.astimezone(UTC)


def _batch_evidence(
    evidence: dict[str, Any] | None, datasets: dict[str, Any]
) -> tuple[dict[str, datetime], tuple[date, date, tuple[date, ...]] | None]:
    if evidence is None:
        return {}, None
    if (not isinstance(evidence, dict)
        or set(evidence) != {"schema_version", "registrations", "sessions"}
        or evidence["schema_version"] != "screening-batch-availability-v1"
        or not isinstance(evidence["registrations"], list)):
        raise ValueError("unsupported batch availability evidence")
    registrations = {}
    for row in evidence["registrations"]:
        if not isinstance(row, dict) or set(row) != {"dataset_id", "publication_id", "ready_at"}:
            raise ValueError("batch registration requires dataset, publication and readiness timestamp")
        dataset_id = require_string(row["dataset_id"], "batch dataset ID")
        reader = datasets.get(dataset_id)
        if reader is None or reader.publication_id != row["publication_id"] or dataset_id in registrations:
            raise ValueError("batch registration publication differs or is duplicated")
        ready = _batch_timestamp(row["ready_at"])
        if _batch_date(reader.manifest["financial_as_of"]) > ready.astimezone(_NY).date():
            raise ValueError("batch readiness precedes its financial cutoff")
        registrations[dataset_id] = ready
    sessions = evidence["sessions"]
    if sessions is None:
        return registrations, None
    if not isinstance(sessions, dict) or set(sessions) != {"from", "through", "dates"}:
        raise ValueError("trading sessions require an explicit coverage range")
    start, end = _batch_date(sessions["from"]), _batch_date(sessions["through"])
    if not isinstance(sessions["dates"], list):
        raise TypeError("trading session dates must be a list")
    dates = tuple(_batch_date(value) for value in sessions["dates"])
    if start > end or dates != tuple(sorted(set(dates))) or any(not start <= day <= end for day in dates):
        raise ValueError("trading session inventory dates or range differ")
    return registrations, (start, end, dates)


class ScreeningService:
    """Application service over verified publications and an append-only store."""

    def __init__(
        self,
        datasets: dict[str, Path | str],
        store: ScreeningStore | Path | str,
        *,
        company_descriptions: CompanyDescriptionReader | None = None,
        source_compatibility: dict[str, str] | None = None,
        batch_evidence: dict[str, Any] | None = None,
        runtime_projections: dict[str, dict[str, str]] | None = None,
        cohort_unions: dict[str, dict[str, str]] | None = None,
        governed_deltas: dict[str, dict] | None = None,
    ) -> None:
        if not isinstance(datasets, dict) or not datasets:
            raise ValueError("at least one screening dataset is required")
        self.source_compatibility = source_compatibility
        projections = {} if runtime_projections is None else runtime_projections
        if not isinstance(projections, dict) or not set(projections) <= set(datasets):
            raise ValueError("runtime projection is outside the screening catalog")
        unions = {} if cohort_unions is None else cohort_unions
        if not isinstance(unions, dict) or not set(unions) <= set(datasets) or set(unions) & set(projections):
            raise ValueError("cohort union is outside the catalog or overlaps a projection declaration")
        deltas = {} if governed_deltas is None else governed_deltas
        if not isinstance(deltas, dict) or not set(deltas) <= set(datasets) or set(deltas) & (set(unions) | set(projections)):
            raise ValueError("governed delta is outside the catalog or overlaps another declaration")
        self.datasets: dict[str, ScreeningReader] = {}
        self.explorers: dict[str, ScreeningExplorer] = {}
        pending = {}
        with self._compatibility_scope(), _share_v3_readers() as loaded:
            for dataset_id, root in datasets.items():
                if dataset_id in deltas:
                    pending[dataset_id] = ("delta", json.loads(Path(deltas[dataset_id]["manifest"]["path"]).read_bytes()))
                    continue
                dataset_id = require_string(dataset_id, "dataset catalog ID")
                if dataset_id in unions:
                    data = json.loads(Path(unions[dataset_id]["path"]).read_bytes())
                    if data.get("schema_version") == "screening-cohort-union-v2":
                        pending[dataset_id] = ("union", data)
                        continue
                    reader = ScreeningCohortUnionReader(root, unions[dataset_id])
                elif dataset_id in projections:
                    reader = ScreeningRuntimeProjection(root, projections[dataset_id])
                else:
                    reader = loaded.get(Path(root).absolute()) or open_screening_dataset(root)
                if reader.manifest["dataset_id"] != dataset_id:
                    raise ValueError("dataset catalog ID differs from publication")
                self.datasets[dataset_id] = reader
                if isinstance(reader, (ScreeningDatasetV2Reader, ScreeningDatasetV3Reader)):
                    self.explorers[dataset_id] = ScreeningExplorer(reader)
        while pending:
            progressed = False
            for dataset_id, (kind, data) in list(pending.items()):
                pins = ([data["parent"]] if kind == "delta" else
                        [member["declaration"]["manifest"] for member in data["config"]["members"]])
                parents = [next((reader for reader in self.datasets.values()
                                 if getattr(reader, "_manifest_sha256", None) == pin["sha256"]
                                 and reader.root == Path(pin["path"]).parent), None) for pin in pins]
                if any(parent is None for parent in parents):
                    continue
                reader = (ScreeningGovernedDeltaReader(datasets[dataset_id], deltas[dataset_id], parent=parents[0])
                          if kind == "delta" else ScreeningCohortUnionReader(
                              datasets[dataset_id], unions[dataset_id], shared_readers=tuple(parents)))
                if reader.manifest["dataset_id"] != dataset_id:
                    raise ValueError("composed dataset catalog identity differs")
                self.datasets[dataset_id] = reader
                del pending[dataset_id]
                progressed = True
            if not progressed:
                raise ValueError("composed dataset requires its exact acyclic shared parents in the catalog")
        self.datasets = {key: self.datasets[key] for key in datasets}
        self.batch_registrations, self.batch_sessions = _batch_evidence(batch_evidence, self.datasets)
        if company_descriptions is not None:
            bound = self.datasets.get(company_descriptions.dataset_id)
            if bound is None or bound.publication_id != company_descriptions.dataset.publication_id:
                raise ValueError("company descriptions differ from the screening catalog")
        self.company_descriptions = company_descriptions
        self.store = store if isinstance(store, ScreeningStore) else ScreeningStore(store)

    def _compatibility_scope(self):
        if self.source_compatibility is None:
            return nullcontext()
        from sec_xbrl.financial_source_compatibility import use_source_compatibility

        return use_source_compatibility(self.source_compatibility)

    def _batch_snapshot(
        self, dataset_id: str, mode: str, decision_date: date | None, lag: int,
    ) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        return {
            "mode": mode,
            "dataset_id": dataset_id,
            "publication_id": reader.publication_id,
            "financial_as_of": reader.manifest["financial_as_of"],
            "ready_at": self.batch_registrations[dataset_id].isoformat() if mode == "ACTUAL" else None,
            "decision_date": decision_date.isoformat() if decision_date else None,
            "lag": lag,
        }

    def _eligible_batch(self, ready: datetime, day: date, lag: int, now: datetime) -> bool:
        ready_day = ready.astimezone(_NY).date()
        if ready > now or ready_day > day:
            return False
        if not lag:
            return True
        if self.batch_sessions is None:
            raise ValueError("positive lag requires a pinned US trading session inventory")
        start, end, dates = self.batch_sessions
        if not start <= ready_day <= day <= end:
            raise ValueError("trading session inventory does not cover the readiness and decision dates")
        return sum(ready_day < session <= day for session in dates) >= lag

    def batch_availability(
        self, *, mode: str, dataset_id: str | None = None, decision_date: str | None = None, lag: int = 0,
    ) -> dict[str, Any]:
        if type(lag) is not int or lag < 0:
            raise ValueError("lag must be a nonnegative trading session count")
        if mode == "PREPARED_SIMULATION":
            if dataset_id is None or decision_date is not None or lag:
                raise ValueError("prepared simulation uses a selected publication and its own cutoff")
            return self._batch_snapshot(dataset_id, mode, None, 0)
        if mode != "ACTUAL" or dataset_id is not None:
            raise ValueError("actual availability selects a registered batch by decision date")
        now = datetime.now(UTC)
        today = now.astimezone(_NY).date()
        day = _batch_date(decision_date) if decision_date is not None else today
        if day > today:
            raise ValueError("decision date is in the future")
        candidates = sorted(self.batch_registrations.items(), key=lambda pair: pair[1], reverse=True)
        selected = [(key, ready) for key, ready in candidates if ready <= now and ready.astimezone(_NY).date() <= day]
        for key, ready in selected:
            if self._eligible_batch(ready, day, lag, now):
                if sum(other == ready for _, other in selected) != 1:
                    raise ValueError("batch readiness is ambiguous at the selected timestamp")
                return self._batch_snapshot(key, mode, day, lag)
        raise ValueError("no verified batch was eligible on the selected date")

    def _validate_batch_snapshot(self, snapshot: dict[str, Any], reader: Any) -> None:
        dataset_id = reader.manifest["dataset_id"]
        mode = snapshot.get("mode")
        if mode == "PREPARED_SIMULATION":
            expected = self._batch_snapshot(dataset_id, mode, None, 0)
        elif mode == "ACTUAL":
            ready = self.batch_registrations.get(dataset_id)
            day = _batch_date(snapshot["decision_date"])
            lag = snapshot["lag"]
            now = datetime.now(UTC)
            if (ready is None or type(lag) is not int or lag < 0 or day > now.astimezone(_NY).date()
                or not self._eligible_batch(ready, day, lag, now)):
                raise ValueError("saved batch readiness is unverified or ineligible")
            expected = self._batch_snapshot(dataset_id, mode, day, lag)
        else:
            raise ValueError("unknown batch availability mode")
        if snapshot != expected:
            raise ValueError("batch availability snapshot differs from the registered publication")

    def status(self) -> dict[str, Any]:
        with self._compatibility_scope():
            datasets = [reader.verify_all() for reader in self.datasets.values()]
        status = {
            "engine_version": ENGINE_VERSION,
            "datasets": datasets,
            "batch_availability": {"registered": len(self.batch_registrations)},
            "screens": len(self.store.list_screens()),
            "runs": len(self.store.list_runs()),
        }
        if self.company_descriptions is not None:
            status["company_descriptions"] = self.company_descriptions.verify_all()
        return status

    def metric_availability(
        self, dataset_id: str, *, cik: str | None = None
    ) -> list[dict[str, Any]]:
        reader = self._dataset(dataset_id)
        rows = reader.metric_support
        if cik is not None:
            cik = require_cik(cik)
            rows = [row for row in rows if row["cik"] == cik]
        return json.loads(canonical_json(rows))

    def metric_catalog(self, dataset_id: str) -> list[dict[str, Any]]:
        reader = self._dataset(dataset_id)
        definitions = getattr(reader, "metric_definitions", None)
        if definitions is None:
            labels: dict[str, str] = {}
            for row in reader.metric_support:
                labels.setdefault(row["metric_id"], row.get("label") or row["metric_id"])
            definitions = [
                {
                    "metric_id": metric_id,
                    "label": label,
                    "category": "LEGACY_REPORTED",
                    "unit_kind": "MONEY",
                    "unit": "USD",
                    "definition_version": next(
                        row["definition_version"]
                        for row in reader.metric_support
                        if row["metric_id"] == metric_id
                    ),
                    "period_class": "FY",
                    "source_kind": "REPORTED",
                }
                for metric_id, label in sorted(labels.items())
            ]
        result = []
        for definition in definitions:
            rows = [
                row for row in reader.metric_support if row["metric_id"] == definition["metric_id"]
            ]
            result.append(
                {
                    **json.loads(canonical_json(definition)),
                    "coverage": {
                        "companies_available": sum(
                            row.get("execution_supported") is True for row in rows
                        ),
                        "companies_total": len(rows),
                        "periods_available": sum(
                            int(row.get("available_periods") or 0) for row in rows
                        ),
                    },
                    "business_availability": "AVAILABLE"
                    if any(row.get("execution_supported") for row in rows)
                    else "UNAVAILABLE",
                    "unavailable_reasons": sorted(
                        {
                            reason
                            for row in rows
                            for reason in (row.get("reasons") or [row.get("reason")])
                            if reason
                        }
                    ),
                }
            )
        return result

    def quarter_metric_catalog(self, dataset_id: str) -> list[dict[str, Any]]:
        reader = self._quarter_dataset(dataset_id)
        result = []
        by_metric: dict[str, list[dict]] = {}
        for row in observation_rows(reader, quarterly=True):
            by_metric.setdefault(row["metric_id"], []).append(row)
        for definition in reader.quarter_definitions:
            rows = by_metric.get(definition["metric_id"], [])
            result.append(
                {
                    **json.loads(canonical_json(definition)),
                    "label": definition["label_ko"],
                    "period_class": definition["observation_basis"],
                    "coverage": {
                        "companies_available": len(
                            {
                                row["cik"]
                                for row in rows
                                if row["availability_status"] == "AVAILABLE"
                            }
                        ),
                        "companies_total": len(reader.companies),
                        "periods_available": sum(
                            row["availability_status"] == "AVAILABLE" for row in rows
                        ),
                    },
                }
            )
        return result

    def quarter_periods(self, dataset_id: str, *, cik: str | None = None) -> dict[str, Any]:
        reader = self._quarter_dataset(dataset_id)
        if cik is not None:
            cik = require_cik(cik)
        rows = [row for row in reader.quarter_period_inventory if cik is None or row["cik"] == cik]
        return {
            "spine": json.loads(canonical_json(reader.quarterly.manifest["global_quarter_spine"])),
            "rows": json.loads(canonical_json(rows)),
            **({"latest_company_periods": {"schema_version": "screening-latest-company-periods-v1",
                "dataset_id": reader.manifest["dataset_id"], "dataset_publication_id": reader.publication_id,
                "financial_as_of": reader.manifest["financial_as_of"],
                "records": public_copy([row for row in reader.latest_quarter_periods.values()
                                         if cik is None or row["cik"] == cik])}}
               if getattr(reader, "latest_quarter_periods", None) else {}),
        }

    def quarter_series(
        self, dataset_id: str, *, cik: str, metric_id: str, limit: int = 8, latest: bool = False
    ) -> dict[str, Any]:
        reader = self._quarter_dataset(dataset_id)
        cik = require_cik(cik)
        metric_id = require_string(metric_id, "metric_id")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("quarter series limit must be one to eight")
        rows = observation_rows(reader, quarterly=True, cik=cik, metric_id=metric_id, latest=latest)
        if not rows:
            raise ValueError("quarter series is not prepared")
        rows.sort(key=lambda row: (row["calendar_year"], row["calendar_quarter"]))
        if latest:
            anchor = latest_company_period(reader, cik, quarterly=True)
            rows = self._latest_series(rows, anchor, cik=cik, quarterly=True)
        return {
            "metric": next(
                row for row in reader.quarter_definitions if row["metric_id"] == metric_id
            ),
            "observations": json.loads(canonical_json([
                hydrate_observation(reader, row, quarterly=True) for row in rows[-limit:]
            ])),
            **({"period": public_copy(anchor), "unavailable_reason": "LATEST_SOURCE_PERIOD_NOT_PUBLISHED",
                "reason_label": "최신 분기 조회 자료 미준비"}
               if latest and anchor is not None and anchor.get("bucket_status") == "LATEST_SOURCE_PERIOD_NOT_PUBLISHED" else {}),
        }

    def quarter_explorer(
        self, dataset_id: str, *, calendar_year: int | None = None, calendar_quarter: int | None = None,
        latest: bool = False, include_evidence: bool = True,
    ) -> dict[str, Any]:
        _validate_evidence_option(include_evidence)
        reader = self._quarter_dataset(dataset_id)
        if not latest:
            _validate_period_policy({
                "mode": "FIXED_CALENDAR_QUARTER_END",
                "calendar_year": calendar_year,
                "calendar_quarter": calendar_quarter,
            })
        elif calendar_year is not None or calendar_quarter is not None:
            raise ValueError("latest company periods cannot be combined with a fixed quarter")
        inventory = {
            (row["cik"], row["calendar_year"], row["calendar_quarter"]): row
            for row in reader.quarter_period_inventory
        }
        rows = []
        for company in reader.companies:
            period = (latest_company_period(reader, company["cik"], quarterly=True) if latest
                      else inventory[(company["cik"], calendar_year, calendar_quarter)])
            prepared = period is not None and (not latest or period["bucket_status"] == "PERIOD_AVAILABLE")
            row_year = period["calendar_year"] if prepared else None
            row_quarter = period["calendar_quarter"] if prepared else None
            matched = observation_rows(
                reader, quarterly=True, cik=company["cik"], year=row_year, quarter=row_quarter, latest=latest,
            ) if prepared else []
            observations = {}
            for row in matched:
                selected = (hydrate_observation(reader, row, quarterly=True) if include_evidence
                            else compact_observation(row))
                observations[row["metric_id"]] = public_copy(
                    latest_period_observation(selected, period, cik=company["cik"], quarterly=True) if latest else selected
                )
            rows.append(
                {
                    "company": json.loads(canonical_json(company)),
                    "period": json.loads(canonical_json(period)),
                    "metrics": observations,
                }
            )
        selected_metrics = []
        for metric in self.quarter_metric_catalog(dataset_id):
            matching = [row["metrics"].get(metric["metric_id"]) for row in rows]
            available = sum(
                item is not None and item["availability_status"] == "AVAILABLE"
                and not item.get("quality_blocking")
                and item.get("quality_status") != "BLOCK"
                for item in matching
            )
            selected_metrics.append(
                {
                    **metric,
                    "aggregate_coverage": metric["coverage"],
                    "coverage": {
                        "companies_available": available,
                        "companies_total": len(reader.companies),
                        "periods_available": available,
                    },
                }
            )
        return {
            "calendar_year": calendar_year,
            "calendar_quarter": calendar_quarter,
            "financial_as_of": reader.manifest["financial_as_of"],
            "metrics": selected_metrics,
            "rows": rows,
            **({"period_scope": "LATEST_COMPANY"} if latest else {}),
        }

    def quarter_comparison(
        self,
        dataset_id: str,
        *,
        ciks: list[str],
        metric_id: str,
        calendar_year: int | None = None,
        calendar_quarter: int | None = None,
        latest: bool = False,
    ) -> dict[str, Any]:
        reader = self._quarter_dataset(dataset_id)
        if len(ciks) < 2 or len(ciks) > 4 or len(set(ciks)) != len(ciks):
            raise ValueError("quarter comparison requires two to four unique companies")
        if latest and (calendar_year is not None or calendar_quarter is not None):
            raise ValueError("latest company periods cannot be combined with a fixed quarter")
        if latest and not any(row["metric_id"] == metric_id for row in reader.quarter_definitions):
            raise ValueError("quarter comparison metric is not prepared")
        rows = []
        for raw in ciks:
            cik = require_cik(raw)
            company = reader.company(cik)
            period = latest_company_period(reader, cik, quarterly=True) if latest else None
            if latest and (period is None or period["bucket_status"] != "PERIOD_AVAILABLE"):
                rows.append({"company": company, "observation": None, "period": public_copy(period)})
                continue
            row_year = period["calendar_year"] if latest else calendar_year
            row_quarter = period["calendar_quarter"] if latest else calendar_quarter
            matches = observation_rows(
                reader, quarterly=True, cik=cik, metric_id=metric_id, year=row_year, quarter=row_quarter, latest=latest,
            ) if row_year is not None and row_quarter is not None else []
            if len(matches) != 1:
                raise ValueError("quarter comparison cell is not unique")
            full = hydrate_observation(reader, matches[0], quarterly=True)
            rows.append({
                "company": company, "observation": public_copy(
                    latest_period_observation(full, period, cik=cik, quarterly=True) if latest else full
                ),
                **({"period": json.loads(canonical_json(period))} if latest else {}),
            })
        signatures = {
            (
                r["observation"]["definition_version"],
                r["observation"]["unit"],
                r["observation"]["selection_as_of_date"],
            )
            for r in rows if r["observation"] is not None
        }
        if len(signatures) > 1 or (not latest and not signatures):
            raise ValueError("quarter comparison scope is incompatible")
        return {
            "calendar_year": calendar_year,
            "calendar_quarter": calendar_quarter,
            "metric_id": metric_id,
            "rows": rows,
            **({"period_scope": "LATEST_COMPANY"} if latest else {}),
        }

    def company_explorer(
        self,
        dataset_id: str,
        *,
        fiscal_year: int | None = None,
        query: str | None = None,
        latest: bool = False,
        sort: str = "company",
        direction: str = "asc",
    ) -> dict[str, Any]:
        """Return the company browse matrix without creating a screen or run."""
        return public_copy(
            self._explorer(dataset_id).explore(
                fiscal_year=fiscal_year,
                latest=latest,
                query=query,
                sort=sort,
                direction=direction,
            )
        )

    def metric_library(
        self,
        dataset_id: str,
        *,
        fiscal_year: int | None = None,
        query: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Return selected-year coverage and guidance for every governed metric."""
        return public_copy(
            self._explorer(dataset_id).metric_library(
                fiscal_year=fiscal_year,
                query=query,
                category=category,
            )
        )

    def company_profile(
        self, dataset_id: str, *, cik: str, fiscal_year: int | None = None, latest: bool = False
    ) -> dict[str, Any]:
        """Return a run-independent company profile over prepared observations."""
        result = public_copy(
            self._explorer(dataset_id).company_profile(
                cik=cik,
                fiscal_year=fiscal_year,
                latest=latest,
            )
        )
        owner = self._dataset(dataset_id).manifest.get("auxiliary_owners", {}).get(cik)
        description_owner = (self.company_descriptions is not None and owner is not None
            and self.company_descriptions.dataset_id == owner["dataset_id"]
            and self.company_descriptions.dataset.publication_id == owner["dataset_publication_id"]
            and getattr(self.company_descriptions.dataset, "_manifest_sha256", None) == owner["dataset_manifest_sha256"])
        if self.company_descriptions is not None and (self.company_descriptions.dataset_id == dataset_id or description_owner):
            row = self.company_descriptions.company(cik)
            result["company_description"] = {
                key: row.get(key)
                for key in (
                    "status",
                    "text",
                    "locale",
                    "provider_name",
                    "profile_url",
                    "checked_at",
                    "observed_at",
                    "publication_id",
                    "temporal_scope",
                    "reason",
                    "content_fixture_kind",
                )
            }
            result["company_description"]["publication_id"] = (
                self.company_descriptions.publication_id
            )
            if description_owner:
                result["company_description"]["source_scope"] = public_copy(owner)
        return result

    def company_comparison(
        self,
        dataset_id: str,
        *,
        ciks: list[str],
        metric_ids: list[str],
        fiscal_year: int | None = None,
        latest: bool = False,
    ) -> dict[str, Any]:
        """Return a same-year matrix for two to four prepared companies."""
        return public_copy(
            self._explorer(dataset_id).compare(
                ciks=ciks,
                metric_ids=metric_ids,
                fiscal_year=fiscal_year,
                latest=latest,
            )
        )

    def metric_series(self, dataset_id: str, *, cik: str, metric_id: str, latest: bool = False) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        cik = require_cik(cik)
        metric_id = require_string(metric_id, "metric_id")
        if not any(row["metric_id"] == metric_id for row in reader.metric_support):
            raise ValueError("unknown metric_id")
        rows = observation_rows(reader, cik=cik, metric_id=metric_id)
        if not rows:
            raise ValueError("metric is not prepared for this company")
        rows.sort(key=lambda row: (row["fiscal_year"], row["period_class"], row["view"]))
        if latest:
            anchor = latest_company_period(reader, cik, quarterly=False)
            rows = self._latest_series(rows, anchor, cik=cik, quarterly=False)
        return {"company": reader.company(cik), "metric_id": metric_id,
                "observations": [hydrate_observation(reader, row) for row in rows]}

    @staticmethod
    def _latest_series(
        rows: list[dict[str, Any]], anchor: dict[str, Any] | None, *, cik: str, quarterly: bool,
    ) -> list[dict[str, Any]]:
        if anchor is None or anchor.get("bucket_status") == "LATEST_SOURCE_PERIOD_NOT_PUBLISHED":
            return []
        fields = ("calendar_year", "calendar_quarter") if quarterly else ("fiscal_year",)
        end = tuple(anchor[key] for key in fields)
        result = []
        for row in rows:
            coordinate = tuple(row[key] for key in fields)
            if coordinate <= end:
                result.append(latest_period_observation(
                    row, anchor if coordinate == end else None, cik=cik, quarterly=quarterly,
                ))
        return result

    def metadata_inventory(
        self,
        dataset_id: str,
        *,
        query: str | None = None,
        sic_code: str | None = None,
        prepared: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("invalid metadata page")
        rows = self._dataset(dataset_id).metadata
        if query:
            needle = query.casefold()
            rows = [
                row
                for row in rows
                if needle in str(row.get("name") or "").casefold()
                or any(needle in ticker.casefold() for ticker in row.get("tickers", []))
                or needle in row["cik"]
            ]
        if sic_code is not None:
            rows = [row for row in rows if row.get("sic_code") == sic_code]
        if prepared is not None:
            rows = [row for row in rows if row.get("financial_prepared") is prepared]
        return {
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "rows": rows[offset : offset + limit],
        }

    def peer_candidates(self, dataset_id: str, *, cik: str) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        cik = require_cik(cik)
        target = next((row for row in reader.metadata if row["cik"] == cik), None)
        if target is None:
            raise ValueError("company is not present in metadata inventory")
        sic = target.get("sic_code")
        peers = (
            []
            if sic is None
            else [
                row for row in reader.metadata if row["cik"] != cik and row.get("sic_code") == sic
            ]
        )
        return {
            "target": target,
            "peers": peers,
            "limitation": "SEC SIC is a current coarse peer-candidate signal, not accounting equivalence.",
        }

    def _saved_context(self, dataset_id: str) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        return {"dataset_id": dataset_id, "publication_id": reader.publication_id, "manifest_digest": digest_value(reader.manifest)}

    def saved_condition(self, revision_id: str) -> dict[str, Any]:
        revision = self.store.revision(revision_id)
        context = revision["saved_context"]
        if context is not None:
            if self._saved_context(context["dataset_id"]) != context:
                raise ValueError("saved condition dataset publication has changed")
            return {**revision, "context_origin": "SAVED", "open_dataset_id": context["dataset_id"]}
        runs = self.store.list_runs(revision_id)
        identities = {(run["dataset_id"], run["dataset_publication_id"]) for run in runs}
        if len(identities) == 1:
            dataset_id, publication_id = identities.pop()
            if self._dataset(dataset_id).publication_id != publication_id:
                raise ValueError("historical condition dataset publication has changed")
            return {**revision, "context_origin": "HISTORICAL_RUN", "open_dataset_id": dataset_id}
        return {**revision, "context_origin": "UNKNOWN", "open_dataset_id": None}

    def create_screen(self, name: str, content: dict[str, Any], *, dataset_id: str | None = None) -> dict[str, Any]:
        self._validate_revision(content, reader=self._dataset(dataset_id) if dataset_id is not None else None)
        return self.store.create_screen(name, content, context=self._saved_context(dataset_id) if dataset_id is not None else None)

    def revise_screen(self, screen_id: str, content: dict[str, Any], *, dataset_id: str | None = None) -> dict[str, Any]:
        self._validate_revision(content, reader=self._dataset(dataset_id) if dataset_id is not None else None)
        return self.store.revise_screen(screen_id, content, context=self._saved_context(dataset_id) if dataset_id is not None else None)

    def execute(self, revision_id: str, dataset_id: str) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        revision = self.store.revision(revision_id)
        content = revision["content"]
        evaluated = self._evaluate(content, dataset_id)
        universe = self.store.save_universe(evaluated.pop("universe"))
        versions = evaluated["versions"]
        input_material = {
            "revision_id": revision_id,
            "revision_hash": revision["content_hash"],
            "universe_snapshot_id": universe["universe_snapshot_id"],
            "dataset_publication_id": reader.publication_id,
            "versions": versions,
        }
        payload = {
            **evaluated,
            "revision_id": revision_id,
            "universe_snapshot_id": universe["universe_snapshot_id"],
            "input_hash": digest_value(input_material),
        }
        return self.store.save_run(payload)

    def preview(
        self, content: dict[str, Any], dataset_id: str, *, include_evidence: bool = True,
    ) -> dict[str, Any]:
        """Evaluate a draft without writing any journal record."""
        _validate_evidence_option(include_evidence)
        evaluated = (self._evaluate(content, dataset_id) if include_evidence
                     else self._evaluate(content, dataset_id, include_evidence=False))
        evaluated.pop("universe")
        return _preview_response(content, dataset_id, evaluated, include_evidence=include_evidence)

    def save_result(
        self,
        *,
        name: str,
        content: dict[str, Any],
        dataset_id: str,
        preview_hash: str,
        revision_id: str | None = None,
        include_evidence: bool = True,
    ) -> dict[str, Any]:
        """Validate once against the preview digest and persist the full evaluation."""
        _validate_evidence_option(include_evidence)
        evaluated = self._evaluate(content, dataset_id)
        universe = evaluated.pop("universe")
        compared = evaluated if include_evidence else _compact_evaluation(evaluated)
        expected = _preview_response(content, dataset_id, compared, include_evidence=include_evidence)
        if require_string(preview_hash, "preview_hash") != expected["preview_hash"]:
            raise ValueError("preview is stale; run the preview again before saving")
        if revision_id is not None:
            context = self.store.revision(revision_id)["saved_context"]
            if context is not None and context != self._saved_context(dataset_id):
                raise ValueError("saved condition dataset differs from the preview")
        return self.store.save_explicit_result(
            name=name,
            content=content,
            universe_content=universe,
            payload=evaluated,
            revision_id=revision_id,
        )

    def _evaluate(
        self, content: dict[str, Any], dataset_id: str, *, include_evidence: bool = True,
    ) -> dict[str, Any]:
        reader = self._dataset(dataset_id)
        self._validate_revision(content, reader=reader)
        targets = _select_universe(reader, content["universe"])
        universe_payload = {
            "dataset_publication_id": reader.publication_id,
            "metadata_publication_id": reader.manifest["sources"]["metadata"]["publication_id"],
            "selector": content["universe"],
            "ciks": [row["cik"] for row in targets],
        }
        rows = [
            self._evaluate_company(reader, company, content, include_evidence=include_evidence) for company in targets
        ]
        rows = _sort_rows(rows, content["sort"])
        counts = {
            state.lower(): sum(row["aggregate"] == state for row in rows) for state in AGGREGATES
        }
        counts.update(
            target=len(rows),
            quality_block=sum(row["quality_blocking"] for row in rows),
        )
        if counts["target"] != counts["pass"] + counts["fail"] + counts["undetermined"]:
            raise AssertionError("screen result counts do not reconcile")
        dataset_versions = json.loads(canonical_json(reader.manifest.get("versions", {})))
        predicate_versions = sorted(
            {predicate["definition_version"] for predicate in content["predicates"]}
        )
        versions = {
            "engine": ENGINE_VERSION,
            "dataset_publication_id": reader.publication_id,
            "dataset": dataset_versions,
            "predicate_definition_versions": predicate_versions,
            "metadata_publication_id": reader.manifest["sources"]["metadata"]["publication_id"],
        }
        return {
            "universe": universe_payload,
            "dataset_id": dataset_id,
            "dataset_publication_id": reader.publication_id,
            "fixture_kind": reader.manifest["fixture_kind"],
            "financial_as_of": reader.manifest["financial_as_of"],
            "period_policy": content["period_policy"],
            "versions": versions,
            "counts": counts,
            "rows": rows,
        }

    def require_publication(self, dataset_id: str, publication_id: str) -> None:
        """Reject source lookups that would mix a frozen result with newer data."""
        if self._dataset(dataset_id).publication_id != publication_id:
            raise ValueError(
                "dataset publication has changed; 저장 당시 자료가 현재 자료와 다릅니다. "
                "저장 결과는 보존되며 당시 자료를 복원한 뒤 다시 열 수 있습니다."
            )

    def run(self, run_id: str) -> dict[str, Any]:
        run = self.store.run(run_id)
        self.require_publication(run["dataset_id"], run["dataset_publication_id"])
        return run

    def trace(self, run_id: str, *, cik: str, metric_id: str) -> dict[str, Any]:
        run = self.store.run(run_id)
        cik = require_cik(cik)
        metric_id = require_string(metric_id, "metric_id")
        row = next((row for row in run["rows"] if row["cik"] == cik), None)
        if row is None:
            raise ValueError("company is not in the run")
        evaluation = next(
            (item for item in row["predicates"] if item["metric_id"] == metric_id), None
        )
        if evaluation is None:
            raise ValueError("metric is not in the run")
        return {
            "run_id": run_id,
            "company": {key: row[key] for key in ("cik", "ticker", "name", "sic_code")},
            "evaluation": evaluation,
            "trace": (evaluation.get("observation") or {}).get("trace"),
        }

    def compare_peers(
        self,
        dataset_id: str,
        *,
        ciks: list[str],
        metric_id: str,
        fiscal_year: int,
    ) -> dict[str, Any]:
        if len(ciks) < 2 or len(ciks) > 100 or len(ciks) != len(set(ciks)):
            raise ValueError("peer comparison requires two to 100 unique CIKs")
        if type(fiscal_year) is not int or not 1900 <= fiscal_year <= 2200:
            raise ValueError("peer comparison fiscal year is invalid")
        reader = self._dataset(dataset_id)
        definition_versions = {
            row.get("definition_version")
            for row in reader.metric_support
            if row.get("metric_id") == metric_id and row.get("execution_supported") is True
        }
        if len(definition_versions) != 1:
            raise ValueError("peer comparison metric is unavailable or version-ambiguous")
        definition_version = next(iter(definition_versions))
        rows = []
        for cik in ciks:
            cik = require_cik(cik)
            company = reader.company(cik)
            observation = _find_observation(
                reader,
                cik,
                metric_id,
                {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": fiscal_year},
                definition_version=definition_version,
            )
            rows.append({"company": company, "observation": observation})
        return {
            "metric_id": metric_id,
            "fiscal_year": fiscal_year,
            "rows": rows,
            "warning": "같은 FY label은 실제 시작일·context end 날짜의 동등성을 뜻하지 않습니다.",
        }

    def add_decision(self, **kwargs: Any) -> dict[str, Any]:
        return self.store.add_decision(**kwargs)

    def decisions(self, cik: str | None = None) -> list[dict[str, Any]]:
        return self.store.decisions(cik)

    def compare_runs(self, old_run_id: str, new_run_id: str) -> dict[str, Any]:
        old, new = self.store.run(old_run_id), self.store.run(new_run_id)
        old_universe = self.store.universe(old["universe_snapshot_id"])["content"]
        new_universe = self.store.universe(new["universe_snapshot_id"])["content"]
        old_rule_vector = {
            "engine": old["versions"].get("engine"),
            "dataset": old["versions"].get("dataset"),
            "predicate_definition_versions": old["versions"].get("predicate_definition_versions"),
        }
        new_rule_vector = {
            "engine": new["versions"].get("engine"),
            "dataset": new["versions"].get("dataset"),
            "predicate_definition_versions": new["versions"].get("predicate_definition_versions"),
        }
        changed = {
            "data": old["dataset_publication_id"] != new["dataset_publication_id"],
            "rule": old_rule_vector != new_rule_vector,
            "universe": old_universe.get("ciks") != new_universe.get("ciks"),
            "universe_selector": old_universe.get("selector") != new_universe.get("selector"),
            "condition_revision": old["revision_id"] != new["revision_id"],
            "manual_decision": _decision_state(self.store.decisions(), old_run_id)
            != _decision_state(self.store.decisions(), new_run_id),
        }
        changed_dimensions = [name for name, value in changed.items() if value]
        attribution = (
            "NO_VERSION_CHANGE"
            if not changed_dimensions
            else changed_dimensions[0].upper() + "_CHANGE"
            if len(changed_dimensions) == 1
            else "MIXED_OR_INCOMPARABLE_VERSION_CHANGE"
        )
        old_rows = {row["cik"]: row for row in old["rows"]}
        new_rows = {row["cik"]: row for row in new["rows"]}
        differences = [
            {
                "cik": cik,
                "old": old_rows.get(cik),
                "new": new_rows.get(cik),
            }
            for cik in sorted(set(old_rows) | set(new_rows))
            if old_rows.get(cik) != new_rows.get(cik)
        ]
        return {
            "old_run_id": old_run_id,
            "new_run_id": new_run_id,
            "changed_dimensions": changed,
            "attribution": attribution,
            "differences": differences,
            "result_rows_changed": bool(differences),
            "result_state": "CHANGED" if differences else "UNCHANGED",
            "fixture_kinds": [old["fixture_kind"], new["fixture_kind"]],
            "universe_membership": {
                "old_ciks": old_universe.get("ciks", []),
                "new_ciks": new_universe.get("ciks", []),
            },
            "version_vectors": {"old": old_rule_vector, "new": new_rule_vector},
        }

    def export_run(
        self,
        run_id: str,
        destination: Path | str,
        *,
        scope: str = "FULL",
        selected_ciks: list[str] | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        run = self.store.run(run_id)
        if scope not in {"FULL", "SELECTED"}:
            raise ValueError("export scope must be FULL or SELECTED")
        selected = None
        if scope == "SELECTED":
            if not selected_ciks:
                raise ValueError("selected export requires CIKs")
            selected = [require_cik(cik) for cik in selected_ciks]
            if len(selected) != len(set(selected)):
                raise ValueError("selected export contains duplicate CIKs")
        rows = (
            run["rows"]
            if selected is None
            else [row for row in run["rows"] if row["cik"] in selected]
        )
        if selected is not None and {row["cik"] for row in rows} != set(selected):
            raise ValueError("selected export contains a CIK outside the run")
        destination_path = safe_new_destination(Path(destination), "screening export")
        selected_format = (format or destination_path.suffix.lstrip(".")).lower()
        if selected_format not in {"json", "csv", "xlsx"}:
            raise ValueError("screening export format must be JSON, CSV, or XLSX")
        payload = {
            "export_version": EXPORT_VERSION,
            "scope": scope,
            "selected_ciks": selected,
            "run": {key: value for key, value in run.items() if key != "rows"},
            "rows": rows,
        }
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.parent / (
            f".{destination_path.name}.partial-{uuid.uuid4().hex}"
        )
        try:
            if selected_format == "json":
                temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
            elif selected_format == "csv":
                _write_csv(temporary, payload)
            else:
                _write_xlsx(temporary, payload)
            temporary.rename(destination_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        manifest = {
            "export_version": EXPORT_VERSION,
            "run_id": run_id,
            "screen_revision_id": run["revision_id"],
            "universe_snapshot_id": run["universe_snapshot_id"],
            "dataset_publication_id": run["dataset_publication_id"],
            "financial_as_of": run["financial_as_of"],
            "versions": run["versions"],
            "scope": scope,
            "selected_ciks": selected,
            "row_count": len(rows),
            "format": selected_format,
            "path": str(destination_path),
            "sha256": sha256_file(destination_path),
            "size": destination_path.stat().st_size,
            "canonical_payload_hash": digest_value(payload),
        }
        if selected_format == "xlsx":
            manifest["xlsx_encoding_version"] = XLSX_LONG_TEXT_VERSION
        try:
            return self.store.record_export(manifest)
        except Exception:
            destination_path.unlink(missing_ok=True)
            raise

    def _dataset(self, dataset_id: str) -> ScreeningReader:
        try:
            return self.datasets[require_string(dataset_id, "dataset_id")]
        except KeyError as exc:
            raise ValueError("unknown screening dataset") from exc

    def _explorer(self, dataset_id: str) -> ScreeningExplorer:
        dataset_id = require_string(dataset_id, "dataset_id")
        reader = self._dataset(dataset_id)
        if dataset_id not in self.explorers and isinstance(reader, (ScreeningRuntimeProjection, ScreeningCohortUnionReader, ScreeningGovernedDeltaReader)):
            self.explorers[dataset_id] = ScreeningExplorer(reader)
        try:
            return self.explorers[dataset_id]
        except KeyError as exc:
            raise ValueError("company explorer requires a v2 screening dataset") from exc

    def _quarter_dataset(self, dataset_id: str) -> ScreeningDatasetV3Reader | ScreeningRuntimeProjection | ScreeningCohortUnionReader | ScreeningGovernedDeltaReader:
        reader = self._dataset(dataset_id)
        if not isinstance(reader, (ScreeningDatasetV3Reader, ScreeningRuntimeProjection, ScreeningCohortUnionReader, ScreeningGovernedDeltaReader)):
            raise TypeError("quarterly analysis requires a v3 screening dataset")
        return reader

    def _validate_revision(
        self,
        content: dict[str, Any],
        *,
        reader: ScreeningReader | None = None,
    ) -> None:
        if not isinstance(content, dict):
            raise TypeError("screen revision must be an object")
        predicates = content.get("predicates")
        if not isinstance(predicates, list) or not predicates:
            raise ValueError("screen revision requires predicates")
        ids = []
        for predicate in predicates:
            if not isinstance(predicate, dict):
                raise TypeError("predicate must be an object")
            metric_id = require_string(predicate.get("metric_id"), "metric_id")
            ids.append(metric_id)
            if predicate.get("operator") not in OPERATORS:
                raise ValueError("unsupported predicate operator")
            _decimal(predicate.get("threshold"))
            definition_version = require_string(
                predicate.get("definition_version"), "metric definition version"
            )
            if reader is not None:
                quarterly = (
                    content.get("period_policy", {}).get("mode") in _QUARTER_MODES
                )
                supports = [
                    row
                    for row in (
                        getattr(reader, "quarter_support", [])
                        if quarterly
                        else reader.metric_support
                    )
                    if row["metric_id"] == metric_id
                ]
                if not supports:
                    raise ValueError("unknown metric_id")
                if not any(
                    row.get("execution_supported", row.get("available_bucket_count", 0) > 0)
                    for row in supports
                ):
                    reason = sorted({row.get("reason") for row in supports})
                    raise ValueError(f"metric is unavailable for execution: {reason}")
                if definition_version not in {row.get("definition_version") for row in supports}:
                    raise ValueError("metric definition version is not prepared")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate metric predicate")
        _validate_universe(content.get("universe"))
        policy = content.get("period_policy")
        _validate_period_policy(policy)
        if "availability" in policy:
            if reader is None:
                raise ValueError("latest company policy requires a pinned dataset")
            self._validate_batch_snapshot(policy["availability"], reader)
        columns = content.get("columns")
        if (
            not isinstance(columns, list)
            or not columns
            or any(value not in VISIBLE_COLUMNS for value in columns)
            or len(columns) != len(set(columns))
        ):
            raise ValueError("screen columns must be a nonempty string list")
        sort = content.get("sort")
        if not isinstance(sort, dict) or sort.get("direction") not in {"ASC", "DESC"}:
            raise ValueError("invalid screen sort")
        sort_column = require_string(sort.get("column"), "sort column")
        if sort_column.startswith("metric:") and sort_column.split(":", 1)[1] not in ids:
            raise ValueError("metric sort column requires a matching predicate")

    def _evaluate_company(
        self,
        reader: ScreeningReader,
        company: dict[str, Any],
        content: dict[str, Any],
        *,
        include_evidence: bool = True,
    ) -> dict[str, Any]:
        policy = content["period_policy"]
        latest = policy["mode"] in LATEST_PERIOD_MODES
        anchor = None
        if latest:
            quarterly = policy["mode"] == LATEST_QUARTER
            anchor = latest_company_period(reader, company["cik"], quarterly=quarterly)
            if anchor is not None:
                policy = ({"mode": _FIXED_QUARTER, "calendar_year": anchor["calendar_year"],
                           "calendar_quarter": anchor["calendar_quarter"]} if quarterly
                          else {"mode": "FIXED_FISCAL_YEAR", "fiscal_year": anchor["fiscal_year"]})
        evaluations = []
        hold_reason = anchor.get("bucket_status") if anchor is not None else None
        conflict = hold_reason in {"PERIOD_CONFLICT", "LATEST_SOURCE_PERIOD_NOT_PUBLISHED"}
        for predicate in content["predicates"]:
            observation = None if latest and (anchor is None or conflict) else _find_observation(
                reader,
                company["cik"],
                predicate["metric_id"],
                policy,
                definition_version=predicate["definition_version"],
                include_evidence=include_evidence, include_latest=latest,
            )
            if latest:
                observation = latest_period_observation(
                    observation, anchor, cik=company["cik"], quarterly=quarterly,
                )
            evaluation = _evaluate_predicate(predicate, observation)
            if conflict:
                evaluation["reason"] = hold_reason
            evaluations.append(evaluation)
        valid_fail = any(row["result"] == "FAIL" for row in evaluations)
        quality_blocking = any(row["quality_blocking"] for row in evaluations)
        if valid_fail:
            aggregate = "FAIL"
        elif all(row["result"] == "PASS" for row in evaluations) and not quality_blocking:
            aggregate = "PASS"
        else:
            aggregate = "UNDETERMINED"
        return {
            "cik": company["cik"],
            "ticker": company["ticker"],
            "name": company["name"],
            "sic_code": company.get("sic_code"),
            "sic_description": company.get("sic_description"),
            "aggregate": aggregate,
            "quality_blocking": quality_blocking,
            "predicates": evaluations,
            **({"resolved_period": public_copy(anchor)} if latest else {}),
        }


def _select_universe(
    reader: ScreeningReader, selector: dict[str, Any]
) -> list[dict[str, Any]]:
    mode = selector["mode"]
    rows = reader.companies
    if mode == "CIKS":
        selected = set(selector["ciks"])
        rows = [row for row in rows if row["cik"] in selected]
        if {row["cik"] for row in rows} != selected:
            raise ValueError("universe CIK is not financially prepared")
    elif mode == "SIC":
        rows = [row for row in rows if row.get("sic_code") in set(selector["sic_codes"])]
    if not rows:
        raise ValueError("universe selector has no prepared target")
    return sorted(rows, key=lambda row: row["cik"])


def _find_observation(
    reader: ScreeningReader,
    cik: str,
    metric_id: str,
    policy: dict[str, Any],
    *,
    definition_version: str | None = None,
    include_evidence: bool = True,
    include_latest: bool = False,
) -> dict[str, Any] | None:
    quarterly = policy["mode"] == "FIXED_CALENDAR_QUARTER_END"
    fixed_year = policy["mode"] == "FIXED_FISCAL_YEAR"
    year = policy["calendar_year"] if quarterly else policy["fiscal_year"] if fixed_year else None
    rows = observation_rows(
        reader, quarterly=quarterly, cik=cik, metric_id=metric_id, year=year,
        quarter=policy["calendar_quarter"] if quarterly else None, latest=include_latest,
    )
    if definition_version is not None:
        rows = [
            row for row in rows
            if row.get("metric_definition_version", row.get("definition_version")) == definition_version
        ]
    if not (fixed_year or quarterly):
        rows.sort(key=lambda row: row["fiscal_year"], reverse=True)
        offset = policy.get("offset", 0)
        rows = rows[offset : offset + 1]
    if len(rows) > 1:
        raise ValueError("metric observation is not unique at screening grain")
    if not rows:
        return None
    observation = (hydrate_observation(reader, rows[0], quarterly=quarterly) if include_evidence
                   else compact_observation(rows[0]))
    if quarterly:
        observation = {
            **observation,
            "quality_blocking": bool(observation.get("quality_blocking") or observation.get("quality_status") == "BLOCK"),
            **({"trace": observation.get("source_lineage")} if include_evidence else {}),
        }
    return public_copy(observation)


def _evaluate_predicate(
    predicate: dict[str, Any], observation: dict[str, Any] | None
) -> dict[str, Any]:
    base = {
        "metric_id": predicate["metric_id"],
        "definition_version": predicate["definition_version"],
        "operator": predicate["operator"],
        "threshold": str(_decimal(predicate["threshold"])),
        "observation": observation,
        "quality_blocking": bool(observation and observation.get("quality_blocking")),
    }
    if observation is None:
        return {**base, "result": "UNDETERMINED", "reason": "PERIOD_NOT_PREPARED"}
    if observation["availability_status"] != "AVAILABLE" or observation.get("quality_blocking"):
        return {
            **base,
            "result": "UNDETERMINED",
            "reason": (
                observation.get("unavailable_reason")
                or observation.get("reason")
                or "OBSERVATION_UNAVAILABLE"
            ),
        }
    value = _decimal(observation["value"])
    threshold = _decimal(predicate["threshold"])
    operator = predicate["operator"]
    passed = {
        "GT": value > threshold,
        "GTE": value >= threshold,
        "LT": value < threshold,
        "LTE": value <= threshold,
        "EQ": value == threshold,
    }[operator]
    return {
        **base,
        "result": "PASS" if passed else "FAIL",
        "reason": "PREDICATE_MATCHED" if passed else "PREDICATE_NOT_MATCHED",
    }


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("numeric value must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("numeric value must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError("numeric value must be a finite decimal")
    return result


def _validate_universe(value: Any) -> None:
    if not isinstance(value, dict) or value.get("mode") not in {"ALL_PREPARED", "CIKS", "SIC"}:
        raise ValueError("invalid universe selector")
    mode = value["mode"]
    allowed = {"mode"} | ({"ciks"} if mode == "CIKS" else {"sic_codes"} if mode == "SIC" else set())
    if set(value) != allowed:
        raise ValueError("universe selector contains unexpected fields")
    if mode == "CIKS":
        rows = value.get("ciks")
        if not isinstance(rows, list) or not rows:
            raise ValueError("CIK universe requires CIKs")
        ciks = [require_cik(cik) for cik in rows]
        if len(ciks) != len(set(ciks)):
            raise ValueError("duplicate universe CIK")
    if mode == "SIC":
        rows = value.get("sic_codes")
        if not isinstance(rows, list) or not rows or any(not isinstance(row, str) for row in rows):
            raise ValueError("SIC universe requires string SIC codes")
        if len(rows) != len(set(rows)):
            raise ValueError("duplicate universe SIC")


def _validate_period_policy(value: Any) -> None:
    modes = {"FIXED_FISCAL_YEAR", "LATEST_COMPLETE_ANNUAL", _FIXED_QUARTER} | LATEST_PERIOD_MODES
    if not isinstance(value, dict) or value.get("mode") not in modes:
        raise ValueError("invalid period policy")
    if "availability" in value and not isinstance(value["availability"], dict):
        raise TypeError("period availability must be a batch snapshot")
    fields = set(value) - {"availability"}
    if value["mode"] in LATEST_PERIOD_MODES:
        if set(value) != {"mode", "availability"} or not isinstance(value["availability"], dict):
            raise ValueError("latest company policy requires a batch availability snapshot")
    elif value["mode"] == "FIXED_FISCAL_YEAR":
        year = value.get("fiscal_year")
        if (
            type(year) is not int
            or not 1900 <= year <= 2200
            or fields != {"mode", "fiscal_year"}
        ):
            raise ValueError("fixed annual policy requires one fiscal year")
    elif value["mode"] == "LATEST_COMPLETE_ANNUAL":
        offset = value.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 20 or set(value) - {"mode", "offset"}:
            raise ValueError("latest annual offset is invalid")
    else:
        year, quarter = value.get("calendar_year"), value.get("calendar_quarter")
        if (
            type(year) is not int
            or not 1900 <= year <= 2200
            or type(quarter) is not int
            or quarter not in {1, 2, 3, 4}
            or fields != {"mode", "calendar_year", "calendar_quarter"}
        ):
            raise ValueError("fixed calendar quarter-end policy requires one year and quarter")


def _sort_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    column = require_string(spec.get("column"), "sort column")
    direction = spec["direction"]
    if column not in {"cik", "ticker", "name", "aggregate"} and not column.startswith("metric:"):
        raise ValueError("unsupported sort column")

    def value(row: dict[str, Any]) -> tuple[bool, Any]:
        if column.startswith("metric:"):
            metric_id = column.split(":", 1)[1]
            item = next(
                (item for item in row["predicates"] if item["metric_id"] == metric_id), None
            )
            raw = (
                None
                if item is None or item["observation"] is None
                else item["observation"].get("value")
            )
            return raw is None, Decimal(raw) if raw is not None else Decimal(0)
        raw = row.get(column)
        return raw is None, str(raw or "")

    by_cik = sorted(rows, key=lambda row: row["cik"])
    present = [row for row in by_cik if not value(row)[0]]
    missing = [row for row in by_cik if value(row)[0]]
    present.sort(key=lambda row: value(row)[1], reverse=direction == "DESC")
    return [*present, *missing]


def _decision_state(events: list[dict[str, Any]], run_id: str) -> dict[str, str]:
    result = {}
    for event in events:
        if event["run_id"] == run_id:
            result[event["cik"]] = event["state"]
    return result


def _write_csv(path: Path, payload: dict[str, Any]) -> None:
    fields = [
        "record_type",
        "cik",
        "ticker",
        "name",
        "sic_code",
        "aggregate",
        "quality_blocking",
        "record_json",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "record_type": "EXPORT",
                "record_json": _csv_safe(
                    {
                        "metadata": {key: value for key, value in payload.items() if key != "rows"},
                        "canonical_payload_hash": digest_value(payload),
                    }
                ),
            }
        )
        for row in payload["rows"]:
            writer.writerow(
                {
                    "record_type": "ROW",
                    "cik": row["cik"],
                    "ticker": _csv_safe(row["ticker"]),
                    "name": _csv_safe(row.get("name")),
                    "sic_code": row.get("sic_code"),
                    "aggregate": row["aggregate"],
                    "quality_blocking": str(row["quality_blocking"]).lower(),
                    "record_json": _csv_safe(row),
                }
            )


def _write_xlsx(path: Path, payload: dict[str, Any]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    rows_sheet = workbook.active
    rows_sheet.title = "Rows"
    long_records: list[dict[str, Any]] = []
    headers = ["cik", "ticker", "name", "sic_code", "aggregate", "quality_blocking", "record_json"]
    rows_sheet.append(headers)
    for index, row in enumerate(payload["rows"]):
        rows_sheet.append(
            [
                str(row.get(key, ""))
                if key != "record_json"
                else _xlsx_text(
                    canonical_json(row),
                    record_key=f"row:{index}:{row['cik']}",
                    long_records=long_records,
                )
                for key in headers
            ]
        )
    metadata = workbook.create_sheet("Metadata")
    metadata.append(["key", "value"])
    for key, value in (
        ("export_version", payload["export_version"]),
        ("xlsx_long_text_encoding", XLSX_LONG_TEXT_VERSION),
        ("scope", payload["scope"]),
        ("selected_ciks_json", canonical_json(payload["selected_ciks"])),
        ("run_json", canonical_json(payload["run"])),
        ("canonical_payload_hash", digest_value(payload)),
    ):
        metadata.append(
            [
                key,
                _xlsx_text(
                    value,
                    record_key=f"metadata:{key}",
                    long_records=long_records,
                ),
            ]
        )
    long_text = workbook.create_sheet("LongText")
    long_text.append(["record_key", "chunk_index", "chunk_count", "sha256", "chunk_text"])
    for record in long_records:
        long_text.append(
            [
                record["record_key"],
                str(record["chunk_index"]),
                str(record["chunk_count"]),
                record["sha256"],
                record["chunk_text"],
            ]
        )
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for row in sheet.iter_rows():
            for cell in row:
                cell.data_type = "s"
    workbook.save(path)


def _xlsx_text(value: str, *, record_key: str, long_records: list[dict[str, Any]]) -> str:
    """Return inline text or a lossless descriptor backed by safe XLSX chunks."""
    utf16_units = len(value.encode("utf-16-le")) // 2
    if len(value) <= XLSX_DIRECT_TEXT_LIMIT and utf16_units <= 32_000:
        return value
    chunks = [
        value[offset : offset + XLSX_CHUNK_TEXT_LIMIT]
        for offset in range(0, len(value), XLSX_CHUNK_TEXT_LIMIT)
    ]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    for index, chunk in enumerate(chunks):
        if len(chunk.encode("utf-16-le")) // 2 > 32_000:
            raise AssertionError("XLSX long-text chunk exceeds the UTF-16 safety limit")
        long_records.append(
            {
                "record_key": record_key,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "sha256": digest,
                "chunk_text": chunk,
            }
        )
    return canonical_json(
        {
            "encoding": XLSX_LONG_TEXT_VERSION,
            "record_key": record_key,
            "chunk_count": len(chunks),
            "sha256": digest,
        }
    )


def _csv_safe(value: Any) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
