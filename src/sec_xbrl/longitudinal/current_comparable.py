"""C3-M3 reviewed current/comparable companion publication.

The companion deliberately consumes an already verified C3-M1 AS_FILED
publication.  It is not a parser and does not attempt to discover a recast
from labels, changed numbers, or filing text.  A reviewer must provide a
versioned evidence binding before a later comparative observation can enter
``CURRENT_COMPARABLE``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication

CURRENT_COMPARABLE_VERSION = "c3-m3-current-comparable-v1"
RECAST_REGISTRY_VERSION = "c3-m3-reviewed-recast-evidence-v1"
_DATASETS = ("current_comparable_fact", "reviewed_recast_evidence", "comparable_coverage")


class CurrentComparableError(RuntimeError):
    """Raised when comparable evidence or a companion release is unsafe."""


@dataclass(frozen=True, slots=True)
class CurrentComparableResult:
    facts: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "current_comparable_fact": self.facts,
            "reviewed_recast_evidence": self.evidence,
            "comparable_coverage": self.coverage,
        }


@dataclass(frozen=True, slots=True)
class CurrentComparablePublication:
    run_root: Path
    manifest_path: Path
    upstream_fingerprint: str
    output_counts: Mapping[str, int]


class ReviewedRecastRegistry:
    """Parse reviewed evidence records; this boundary never performs NLP.

    ``source_series_candidate_id`` identifies the exact later observation in
    C3-M1's retained current-series candidate set.  ``prior_analytical_fact_ids``
    identifies the historical AS_FILED rows replaced in the companion view.
    The full canonical dimensional key is intentionally supplied in every
    record, rather than inferred from a display hierarchy.
    """

    def parse(self, rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        parsed = tuple(_validate_evidence(row) for row in rows)
        identities: set[str] = set()
        source_ids: set[str] = set()
        for row in parsed:
            if row["recast_evidence_id"] in identities:
                raise CurrentComparableError("duplicate reviewed recast evidence identity")
            if row["source_series_candidate_id"] in source_ids:
                raise CurrentComparableError("one source candidate cannot bind two evidence records")
            identities.add(row["recast_evidence_id"])
            source_ids.add(row["source_series_candidate_id"])
        return tuple(sorted(parsed, key=_canonical_json))


class CurrentComparableMaterializer:
    """Make a fail-closed comparable companion from reviewed evidence only."""

    def materialize(
        self,
        publication: VerifiedLayer2Publication,
        *,
        evidence_registry: Iterable[Mapping[str, Any]] = (),
    ) -> CurrentComparableResult:
        if not isinstance(publication, VerifiedLayer2Publication):
            raise CurrentComparableError("C3-M3 requires a verified C3-M1 publication")
        evidence = ReviewedRecastRegistry().parse(evidence_registry)
        as_filed = tuple(
            dict(row) for row in publication.records("analytical_fact") if row.get("view") == "AS_FILED"
        )
        candidates = {str(row.get("series_candidate_id") or ""): dict(row)
                      for row in publication.records("current_series_candidate")}
        observations = {
            (str(row.get("source_filing_id") or ""), str(row.get("source_fact_id") or "")): dict(row)
            for row in publication.records("period_observation")
        }
        _validate_source_indexes(as_filed, candidates)
        by_fact_id = {str(row.get("analytical_fact_id") or ""): row for row in as_filed}
        bound: dict[str, dict[str, Any]] = {}
        for item in evidence:
            source = candidates.get(item["source_series_candidate_id"])
            if source is None:
                raise CurrentComparableError("recast evidence references unknown source series candidate")
            _validate_evidence_binding(item, source, by_fact_id)
            if item["source_type"] == "DERIVED_RECAST":
                _validate_derived_inputs(item, candidates)
            for fact_id in item["prior_analytical_fact_ids"]:
                if fact_id in bound:
                    raise CurrentComparableError("one AS_FILED fact cannot receive two comparable selections")
                bound[fact_id] = {"evidence": item, "source": source}

        result: list[dict[str, Any]] = []
        for historical in as_filed:
            identity = str(historical.get("analytical_fact_id") or "")
            item = bound.get(identity)
            if item is None:
                result.append(_unavailable(historical, "RECAST_EVIDENCE_NOT_AVAILABLE"))
                continue
            evidence_row, source = item["evidence"], item["source"]
            raw = observations.get((str(source.get("source_filing_id") or ""), str(source.get("source_fact_id") or "")))
            if raw is None:
                raise CurrentComparableError("recast source candidate lacks exact period-observation provenance")
            if evidence_row["source_type"] == "RECAST_REPORTED":
                result.append(_reported_recast(historical, source, raw, evidence_row))
            else:
                result.append(_derived_recast(historical, source, raw, candidates, evidence_row))
        coverage = _coverage(as_filed, result)
        return CurrentComparableResult(
            tuple(sorted(result, key=lambda row: str(row["analytical_fact_id"]))),
            evidence,
            coverage,
        )


class CurrentComparablePublisher:
    """Atomically write a companion that cannot replace C3-M1 AS_FILED data."""

    manifest_name = "current_comparable_manifest.json"

    def publish(
        self,
        result: CurrentComparableResult,
        *,
        output_root: Path,
        run_version: str,
        upstream: VerifiedLayer2Publication,
    ) -> CurrentComparablePublication:
        if not run_version or "/" in run_version or "\\" in run_version:
            raise CurrentComparableError("current comparable run_version must be a non-path identifier")
        rows = {name: tuple(sorted((dict(row) for row in values), key=_canonical_json))
                for name, values in result.as_datasets().items()}
        counts = {name: len(values) for name, values in rows.items()}
        hashes = {name: _hash_rows(values) for name, values in rows.items()}
        manifest = {
            "contract_version": CURRENT_COMPARABLE_VERSION,
            "registry_version": RECAST_REGISTRY_VERSION,
            "run_version": run_version,
            "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
            "upstream_layer2_manifest_sha256": upstream.identity.get("layer2_manifest_sha256"),
            "output_counts": counts,
            "output_content_sha256": hashes,
            "validation": {
                "VERIFIED_C3_M1_LINKAGE": "SUCCESS", "REVIEWED_EVIDENCE_ONLY": "SUCCESS",
                "AS_FILED_IMMUTABLE": "SUCCESS", "ATOMIC_PUBLICATION": "SUCCESS",
            },
        }
        root, target = Path(output_root), Path(output_root) / run_version
        root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target / self.manifest_name
            if not existing.is_file() or json.loads(existing.read_text(encoding="utf-8")) != manifest:
                raise CurrentComparableError("current comparable run_version already exists with different content")
            return CurrentComparablePublication(target, existing, manifest["upstream_layer2_run_fingerprint"], counts)
        staging = Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-", dir=root))
        try:
            for name, values in rows.items():
                (staging / f"{name}.jsonl").write_text(
                    "".join(_canonical_json(row) + "\n" for row in values), encoding="utf-8"
                )
            (staging / self.manifest_name).write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return CurrentComparablePublication(target, target / self.manifest_name,
                                            manifest["upstream_layer2_run_fingerprint"], counts)


class CurrentComparablePublicationReader:
    """Read a companion only after its exact upstream and content verification."""

    def load(self, run_root: Path, *, upstream: VerifiedLayer2Publication) -> CurrentComparableResult:
        root, manifest_path = Path(run_root), Path(run_root) / CurrentComparablePublisher.manifest_name
        if not root.is_dir() or root.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
            raise CurrentComparableError("current comparable companion release is missing or unsafe")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CurrentComparableError("current comparable companion manifest is invalid") from exc
        required = {"contract_version", "registry_version", "run_version", "upstream_layer2_run_fingerprint",
                    "upstream_layer2_manifest_sha256", "output_counts", "output_content_sha256", "validation"}
        if set(manifest) != required or manifest.get("contract_version") != CURRENT_COMPARABLE_VERSION or manifest.get("registry_version") != RECAST_REGISTRY_VERSION:
            raise CurrentComparableError("current comparable companion manifest has unsupported contract")
        if manifest.get("upstream_layer2_run_fingerprint") != upstream.identity.get("layer2_run_fingerprint") or manifest.get("upstream_layer2_manifest_sha256") != upstream.identity.get("layer2_manifest_sha256"):
            raise CurrentComparableError("current comparable companion does not match verified C3-M1 publication")
        files = {self_file.name for self_file in root.iterdir() if self_file.is_file() and not self_file.is_symlink()}
        expected = {CurrentComparablePublisher.manifest_name, *(f"{name}.jsonl" for name in _DATASETS)}
        if files != expected or any(child.is_dir() or child.is_symlink() for child in root.iterdir()):
            raise CurrentComparableError("current comparable companion layout is incomplete or unexpected")
        rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for name in _DATASETS:
            try:
                values = tuple(json.loads(line) for line in (root / f"{name}.jsonl").read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CurrentComparableError("current comparable companion dataset is invalid") from exc
            if any(not isinstance(row, dict) for row in values) or len(values) != manifest["output_counts"].get(name) or _hash_rows(values) != manifest["output_content_sha256"].get(name):
                raise CurrentComparableError("current comparable companion content verification failed")
            rows[name] = tuple(dict(row) for row in values)
        return CurrentComparableResult(rows["current_comparable_fact"], rows["reviewed_recast_evidence"], rows["comparable_coverage"])


def _validate_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(value)
    required = ("recast_evidence_id", "cik", "company_canonical_concept_id", "company_canonical_dimension_key",
                "period_class", "target_period_keys", "old_basis_version", "new_basis_version", "source_type",
                "source_series_candidate_id", "source_filing_id", "source_raw_fact_id", "filed_date",
                "source_document", "source_locator", "evidence_identity", "evidence_kind", "explicitly_represented",
                "prior_analytical_fact_ids")
    missing = [key for key in required if row.get(key) is None or row.get(key) == ""]
    if missing:
        raise CurrentComparableError("reviewed recast evidence missing: " + ", ".join(missing))
    if row.get("registry_version", RECAST_REGISTRY_VERSION) != RECAST_REGISTRY_VERSION:
        raise CurrentComparableError("unsupported reviewed recast registry version")
    if row["source_type"] not in {"RECAST_REPORTED", "DERIVED_RECAST"}:
        raise CurrentComparableError("reviewed recast evidence has unsupported source_type")
    if row["explicitly_represented"] is not True:
        raise CurrentComparableError("numeric changes are not recast evidence")
    if row["evidence_kind"] not in {"TABLE", "NARRATIVE", "NARRATIVE_AND_TABLE", "REVIEWED"}:
        raise CurrentComparableError("unsupported reviewed recast evidence kind")
    periods = tuple(str(item) for item in row["target_period_keys"] if item)
    previous = tuple(str(item) for item in row["prior_analytical_fact_ids"] if item)
    if not periods or not previous:
        raise CurrentComparableError("reviewed recast evidence requires periods and prior analytical facts")
    if row["old_basis_version"] == row["new_basis_version"]:
        raise CurrentComparableError("reviewed recast evidence requires distinct old and new basis versions")
    row["target_period_keys"], row["prior_analytical_fact_ids"] = periods, previous
    row["registry_version"] = RECAST_REGISTRY_VERSION
    if row["source_type"] == "DERIVED_RECAST":
        if not row.get("derivation_rule_version") or not row.get("source_series_candidate_ids"):
            raise CurrentComparableError("derived recast evidence requires rule and exact source candidates")
        row["source_series_candidate_ids"] = tuple(str(item) for item in row["source_series_candidate_ids"] if item)
    return row


def _validate_source_indexes(as_filed: tuple[dict[str, Any], ...], candidates: Mapping[str, dict[str, Any]]) -> None:
    if not as_filed or not candidates:
        raise CurrentComparableError("C3-M1 publication lacks AS_FILED facts or retained source candidates")
    if any(not row.get("analytical_fact_id") for row in as_filed) or "" in candidates:
        raise CurrentComparableError("C3-M1 publication has unidentifiable comparable input")


def _validate_evidence_binding(item: Mapping[str, Any], source: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]]) -> None:
    expected = ("cik", "company_canonical_concept_id", "period_class", "source_filing_id")
    if any(str(source.get(key) or "") != str(item.get(key) or "") for key in expected):
        raise CurrentComparableError("recast evidence source candidate scope does not match")
    if str(source.get("source_fact_id") or "") != str(item["source_raw_fact_id"]):
        raise CurrentComparableError("recast evidence raw Fact does not match source candidate")
    if _freeze(source.get("company_canonical_dimension_key")) != _freeze(item["company_canonical_dimension_key"]):
        raise CurrentComparableError("recast evidence full dimensions do not match source candidate")
    if str(source.get("actual_period_key") or "") not in set(item["target_period_keys"]):
        raise CurrentComparableError("recast evidence target period does not match source candidate")
    if str(source.get("filed_date") or "") != str(item["filed_date"]):
        raise CurrentComparableError("recast evidence filing date does not match source candidate")
    for fact_id in item["prior_analytical_fact_ids"]:
        prior = facts.get(fact_id)
        if prior is None:
            raise CurrentComparableError("recast evidence references unknown AS_FILED fact")
        if _scope(prior) != _scope_item(item, str(prior.get("period_key") or "")):
            raise CurrentComparableError("recast evidence prior fact has incompatible period, dimensions, or company scope")
        if prior.get("basis_version") not in {None, item["old_basis_version"]}:
            raise CurrentComparableError("recast evidence prior fact basis does not match old basis")


def _validate_derived_inputs(item: Mapping[str, Any], candidates: Mapping[str, dict[str, Any]]) -> None:
    inputs = [candidates.get(key) for key in item["source_series_candidate_ids"]]
    if any(row is None for row in inputs):
        raise CurrentComparableError("derived recast evidence is missing exact source candidate input")
    source = candidates[item["source_series_candidate_id"]]
    if item["source_series_candidate_id"] not in item["source_series_candidate_ids"]:
        raise CurrentComparableError("derived recast evidence must bind its declared output candidate")
    if len(inputs) != 2:
        raise CurrentComparableError("derived recast requires two exact source candidates")
    if any((_scope(row)[:4] != _scope(source)[:4] or row.get("unit_semantics") != source.get("unit_semantics")) for row in inputs if row):
        raise CurrentComparableError("derived recast inputs are not fully compatible")


def _reported_recast(historical: Mapping[str, Any], source: Mapping[str, Any], raw: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    return _available(historical, source, raw, evidence, source_type="RECAST_REPORTED", value=source.get("value_numeric"), source_fact_ids=(source.get("source_fact_id"),))


def _derived_recast(historical: Mapping[str, Any], source: Mapping[str, Any], raw: Mapping[str, Any], candidates: Mapping[str, dict[str, Any]], evidence: Mapping[str, Any]) -> dict[str, Any]:
    inputs = [candidates[key] for key in evidence["source_series_candidate_ids"]]
    try:
        values = [Decimal(str(row["value_numeric"])) for row in inputs]
    except (InvalidOperation, KeyError, TypeError) as exc:
        raise CurrentComparableError("derived recast input has no numeric value") from exc
    if evidence["derivation_rule_version"] != "c3-m3-fy-minus-ytd9m-v1" or len(values) != 2:
        raise CurrentComparableError("unsupported derived recast rule or input cardinality")
    value = str(values[0] - values[1])
    return _available(historical, source, raw, evidence, source_type="DERIVED_RECAST", value=value,
                      source_fact_ids=tuple(str(row["source_fact_id"]) for row in inputs))


def _available(historical: Mapping[str, Any], source: Mapping[str, Any], raw: Mapping[str, Any], evidence: Mapping[str, Any], *, source_type: str, value: Any, source_fact_ids: tuple[Any, ...]) -> dict[str, Any]:
    identity = ("CURRENT_COMPARABLE", historical.get("analytical_fact_id"), evidence["recast_evidence_id"], source_type)
    return {
        **dict(historical), "analytical_fact_id": _stable_id("current-comparable-fact", identity),
        "view": "CURRENT_COMPARABLE", "basis_version": evidence["new_basis_version"], "source_type": source_type,
        "value_numeric": value, "value_text": None, "selected_fact_id": source.get("source_fact_id") if source_type == "RECAST_REPORTED" else None,
        "source_fact_ids": source_fact_ids, "source_filing_id": source.get("source_filing_id"), "filed_date": source.get("filed_date"),
        "accession": raw.get("accession"), "form": raw.get("form"), "report_date": raw.get("report_date"), "context_id": raw.get("context_id"), "unit_id": raw.get("unit_id"),
        "source_document": raw.get("source_document"), "source_locator": raw.get("source_locator"),
        "recast_evidence_id": evidence["recast_evidence_id"], "recast_evidence_identity": evidence["evidence_identity"],
        "derivation_rule_version": evidence.get("derivation_rule_version"), "selection_rule_version": CURRENT_COMPARABLE_VERSION,
        "unavailable_reason": None,
    }


def _unavailable(historical: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {**dict(historical), "analytical_fact_id": _stable_id("current-comparable-fact", (historical.get("analytical_fact_id"), reason)),
            "view": "CURRENT_COMPARABLE", "source_type": "UNAVAILABLE", "value_numeric": None, "value_text": None,
            "selected_fact_id": None, "source_fact_ids": (), "source_filing_id": None, "filed_date": None,
            "recast_evidence_id": None, "recast_evidence_identity": None, "unavailable_reason": reason,
            "selection_rule_version": CURRENT_COMPARABLE_VERSION}


def _coverage(historical: Iterable[Mapping[str, Any]], output: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    results = list(output)
    return tuple({"cik": str(cik), "as_filed_fact_count": sum(1 for row in historical if row.get("cik") == cik),
                  "current_comparable_fact_count": sum(1 for row in results if row.get("cik") == cik),
                  "available_count": sum(1 for row in results if row.get("cik") == cik and row.get("source_type") != "UNAVAILABLE"),
                  "coverage_status": "REVIEWED_RECAST_AVAILABLE" if any(row.get("cik") == cik and row.get("source_type") != "UNAVAILABLE" for row in results) else "RECAST_EVIDENCE_NOT_AVAILABLE"}
                 for cik in sorted({str(row.get("cik")) for row in results}))


def _scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(row.get("cik") or ""), str(row.get("company_canonical_concept_id") or ""), _freeze(row.get("company_canonical_dimension_key")), str(row.get("period_class") or ""), str(row.get("period_key") or row.get("actual_period_key") or ""))


def _scope_item(row: Mapping[str, Any], period: str) -> tuple[Any, ...]:
    return (str(row["cik"]), str(row["company_canonical_concept_id"]), _freeze(row["company_canonical_dimension_key"]), str(row["period_class"]), period)


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def _stable_id(prefix: str, payload: Any) -> str:
    return prefix + ":" + hashlib.sha256(json.dumps(payload, default=repr, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def _canonical_json(row: Mapping[str, Any]) -> str:
    return json.dumps(row, default=list, sort_keys=True, separators=(",", ":"))


def _hash_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    return hashlib.sha256("".join(_canonical_json(row) + "\n" for row in rows).encode()).hexdigest()
