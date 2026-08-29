# ruff: noqa: E701, E702
"""C3-M5 review inventory: evidence to review, never policy to activate.

The companion is intentionally a queue of reader-attested technical matches.
It does not calculate Q4, assert a recast, add a semantic declaration, or
produce a consumer-facing comparable value.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication

REVIEW_INVENTORY_VERSION = "c3-m5-review-inventory-v1"
_DATASETS = ("q4_review_candidate", "recast_review_candidate", "source_artifact_coverage")


class ReviewInventoryError(RuntimeError):
    """Raised when an inventory would not be linked to immutable inputs."""


@dataclass(frozen=True, slots=True)
class ReviewInventoryResult:
    q4_candidates: tuple[dict[str, Any], ...]
    recast_candidates: tuple[dict[str, Any], ...]
    artifact_coverage: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {"q4_review_candidate": self.q4_candidates,
                "recast_review_candidate": self.recast_candidates,
                "source_artifact_coverage": self.artifact_coverage}


@dataclass(frozen=True, slots=True)
class ReviewInventoryPublication:
    run_root: Path
    manifest_path: Path
    upstream_fingerprint: str
    corpus_fingerprint: str
    output_counts: Mapping[str, int]


class ReviewInventoryMaterializer:
    """Discover reviewable technical links without inferring accounting meaning."""

    def materialize(self, publication: VerifiedLayer2Publication, *, release: CorpusRelease) -> ReviewInventoryResult:
        if not isinstance(publication, VerifiedLayer2Publication) or not publication.is_reader_attested:
            raise ReviewInventoryError("C3-M5 requires a reader-attested verified C3-M1 publication")
        if not isinstance(release, CorpusRelease):
            raise ReviewInventoryError("C3-M5 requires an immutable CorpusRelease")
        if publication.identity.get("layer2_run_fingerprint") != release.layer2_run.fingerprint:
            raise ReviewInventoryError("C3-M1 publication does not match supplied CorpusRelease")
        if set(publication.input_ciks) != set(release.ciks):
            raise ReviewInventoryError("C3-M1 publication company scope does not match supplied CorpusRelease")
        facts = [dict(row) for row in publication.records("analytical_fact")
                 if row.get("view") == "AS_FILED" and row.get("source_type") == "REPORTED"
                 and row.get("value_numeric") is not None]
        raw = {(str(row.get("filing_id")), str(row.get("fact_id"))): row for row in release.records("fact")}
        concepts = {(str(row.get("filing_id")), str(row.get("raw_concept_id"))): row for row in release.records("concept")}
        units = {(str(row.get("filing_id")), str(row.get("unit_id"))): row for row in release.records("unit")}
        q4 = self._q4(facts, raw, concepts, units)
        recast = self._recast(facts, publication.records("current_series_candidate"), raw)
        artifact = _artifact_coverage((*q4, *recast), raw)
        return ReviewInventoryResult(tuple(sorted(q4, key=_canonical_json)), tuple(sorted(recast, key=_canonical_json)), tuple(sorted(artifact, key=_canonical_json)))

    def _q4(self, facts: list[dict[str, Any]], raw: Mapping[tuple[str, str], Mapping[str, Any]], concepts: Mapping[tuple[str, str], Mapping[str, Any]], units: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in facts:
            if row.get("period_class") in {"FY", "YTD_9M"}:
                grouped[_scope(row, include_period=False)].append(row)
        output: list[dict[str, Any]] = []
        for scope, rows in grouped.items():
            fy = [r for r in rows if r.get("period_class") == "FY"]
            ytd = [r for r in rows if r.get("period_class") == "YTD_9M"]
            for annual in fy:
                for nine in ytd:
                    if not _q4_technical_match(annual, nine, raw, concepts, units):
                        continue
                    output.append({
                        "review_candidate_id": _id("q4-review", (annual["analytical_fact_id"], nine["analytical_fact_id"])),
                        "candidate_kind": "Q4_TECHNICAL_PAIR", "review_status": "PENDING_SEMANTIC_REVIEW",
                        "cik": annual["cik"], "company_canonical_concept_id": annual["company_canonical_concept_id"],
                        "company_canonical_dimension_key": annual.get("company_canonical_dimension_key"),
                        "basis_version": annual.get("basis_version"), "unit_semantics": annual.get("unit_semantics"),
                        "quarterly_period": "Q4", "formula": None, "value_numeric": None,
                        "semantic_inference": "NOT_PERFORMED", "approval_registry_value": None,
                        "fy_source": _lineage(annual, raw), "ytd_9m_source": _lineage(nine, raw),
                        "inventory_version": REVIEW_INVENTORY_VERSION,
                    })
        return output

    def _recast(self, facts: list[dict[str, Any]], candidates: Iterable[Mapping[str, Any]], raw: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
        historical = defaultdict(list)
        for row in facts:
            historical[_scope(row, include_period=True)].append(row)
        output: list[dict[str, Any]] = []
        for value in candidates:
            candidate = dict(value)
            key = _scope(candidate, include_period=True, candidate_period=True)
            for prior in historical.get(key, []):
                if str(prior.get("source_filing_id")) == str(candidate.get("source_filing_id")):
                    continue
                output.append({
                    "review_candidate_id": _id("recast-review", (prior.get("analytical_fact_id"), candidate.get("series_candidate_id"))),
                    "candidate_kind": "POTENTIAL_COMPARATIVE_OBSERVATION", "review_status": "PENDING_EVIDENCE_REVIEW",
                    "recast_claim": "NOT_MADE", "basis_change": "NOT_INFERRED", "cik": prior["cik"],
                    "company_canonical_concept_id": prior["company_canonical_concept_id"],
                    "company_canonical_dimension_key": prior.get("company_canonical_dimension_key"),
                    "period_class": prior.get("period_class"), "period_key": prior.get("period_key"),
                    "prior_as_filed_source": _lineage(prior, raw),
                    "later_observation": _candidate_lineage(candidate, raw),
                    "inventory_version": REVIEW_INVENTORY_VERSION,
                })
        return output


class ReviewInventoryPublisher:
    manifest_name = "review_inventory_manifest.json"
    def publish(self, result: ReviewInventoryResult, *, output_root: Path, run_version: str, upstream: VerifiedLayer2Publication, release: CorpusRelease) -> ReviewInventoryPublication:
        if not isinstance(upstream, VerifiedLayer2Publication) or not upstream.is_reader_attested:
            raise ReviewInventoryError("C3-M5 publisher requires reader-attested upstream")
        if upstream.identity.get("layer2_run_fingerprint") != release.layer2_run.fingerprint:
            raise ReviewInventoryError("C3-M5 publisher upstream does not match CorpusRelease")
        if not run_version or "/" in run_version or "\\" in run_version:
            raise ReviewInventoryError("review inventory run_version must be a non-path identifier")
        rows = {k: tuple(sorted((dict(x) for x in v), key=_canonical_json)) for k, v in result.as_datasets().items()}
        counts, hashes = ({k: len(v) for k, v in rows.items()}, {k: _hash_rows(v) for k, v in rows.items()})
        manifest = {"contract_version": REVIEW_INVENTORY_VERSION, "run_version": run_version,
                    "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
                    "upstream_layer2_manifest_sha256": upstream.identity.get("layer2_manifest_sha256"),
                    "corpus_release_fingerprint": release.layer2_run.fingerprint,
                    "output_counts": counts, "output_content_sha256": hashes,
                    "validation": {"READER_ATTESTED_C3_M1": "SUCCESS", "IMMUTABLE_CORPUS_LINKAGE": "SUCCESS", "NO_Q4_VALUE": "SUCCESS", "NO_RECAST_ACTIVATION": "SUCCESS", "ATOMIC_PUBLICATION": "SUCCESS"}}
        root, target = Path(output_root), Path(output_root) / run_version; root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            path = target / self.manifest_name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != manifest: raise ReviewInventoryError("review inventory run_version already exists with different content")
            return ReviewInventoryPublication(target, path, manifest["upstream_layer2_run_fingerprint"], manifest["corpus_release_fingerprint"], counts)
        staging = Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-", dir=root))
        try:
            for name, values in rows.items(): (staging / f"{name}.jsonl").write_text("".join(_canonical_json(row) + "\n" for row in values), encoding="utf-8")
            (staging / self.manifest_name).write_text(_canonical_json(manifest) + "\n", encoding="utf-8"); os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True); raise
        return ReviewInventoryPublication(target, target / self.manifest_name, manifest["upstream_layer2_run_fingerprint"], manifest["corpus_release_fingerprint"], counts)


class ReviewInventoryPublicationReader:
    def load(self, run_root: Path, *, upstream: VerifiedLayer2Publication, release: CorpusRelease) -> ReviewInventoryResult:
        if not isinstance(upstream, VerifiedLayer2Publication) or not upstream.is_reader_attested: raise ReviewInventoryError("review inventory reader requires reader-attested upstream")
        root = Path(run_root); path = root / ReviewInventoryPublisher.manifest_name
        if not root.is_dir() or root.is_symlink() or not path.is_file() or path.is_symlink(): raise ReviewInventoryError("review inventory companion release is missing or unsafe")
        try: manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ReviewInventoryError("review inventory companion manifest is invalid") from exc
        required = {"contract_version", "run_version", "upstream_layer2_run_fingerprint", "upstream_layer2_manifest_sha256", "corpus_release_fingerprint", "output_counts", "output_content_sha256", "validation"}
        if set(manifest) != required or manifest.get("contract_version") != REVIEW_INVENTORY_VERSION: raise ReviewInventoryError("review inventory companion manifest has unsupported contract")
        if manifest.get("upstream_layer2_run_fingerprint") != upstream.identity.get("layer2_run_fingerprint") or manifest.get("upstream_layer2_manifest_sha256") != upstream.identity.get("layer2_manifest_sha256") or manifest.get("corpus_release_fingerprint") != release.layer2_run.fingerprint: raise ReviewInventoryError("review inventory companion does not match verified inputs")
        expected = {self_name for self_name in [ReviewInventoryPublisher.manifest_name, *(f"{n}.jsonl" for n in _DATASETS)]}; actual = {x.name for x in root.iterdir() if x.is_file() and not x.is_symlink()}
        if actual != expected or any(x.is_dir() or x.is_symlink() for x in root.iterdir()): raise ReviewInventoryError("review inventory companion layout is incomplete or unexpected")
        rows = {}
        for name in _DATASETS:
            try: values = tuple(json.loads(line) for line in (root / f"{name}.jsonl").read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ReviewInventoryError("review inventory companion dataset is invalid") from exc
            if any(not isinstance(x, dict) for x in values) or len(values) != manifest["output_counts"].get(name) or _hash_rows(values) != manifest["output_content_sha256"].get(name): raise ReviewInventoryError("review inventory companion content verification failed")
            rows[name] = tuple(dict(x) for x in values)
        return ReviewInventoryResult(rows["q4_review_candidate"], rows["recast_review_candidate"], rows["source_artifact_coverage"])


def _scope(row: Mapping[str, Any], *, include_period: bool, candidate_period: bool = False) -> tuple[Any, ...]:
    period = row.get("actual_period_key") if candidate_period else row.get("period_key")
    values = (str(row.get("cik") or ""), str(row.get("company_canonical_concept_id") or ""), repr(row.get("company_canonical_dimension_key")), repr(row.get("unit_semantics")), str(row.get("basis_version") or ""))
    return (*values, str(row.get("period_class") or ""), str(period or "")) if include_period else values

def _q4_technical_match(fy: Mapping[str, Any], ytd: Mapping[str, Any], raw: Mapping[tuple[str, str], Mapping[str, Any]], concepts: Mapping[tuple[str, str], Mapping[str, Any]], units: Mapping[tuple[str, str], Mapping[str, Any]]) -> bool:
    if _scope(fy, include_period=False) != _scope(ytd, include_period=False): return False
    bounds, other = fy.get("actual_period_boundaries") or (), ytd.get("actual_period_boundaries") or ()
    if len(bounds) < 2 or len(other) < 2 or not bounds[0] or bounds[0] != other[0] or not bounds[1] or not other[1] or str(other[1]) >= str(bounds[1]): return False
    for row in (fy, ytd):
        fact = raw.get((str(row.get("source_filing_id")), str(row.get("selected_fact_id"))))
        if not fact: return False
        concept = concepts.get((str(row.get("source_filing_id")), str(fact.get("raw_concept_id"))))
        unit = units.get((str(row.get("source_filing_id")), str(fact.get("unit_id"))))
        nums = _measures(None if unit is None else unit.get("numerator_measures")); dens = _measures(None if unit is None else unit.get("denominator_measures"))
        if not concept or not unit or str(concept.get("period_type") or "").lower() != "duration" or "monetary" not in str(concept.get("data_type") or "").lower() or dens or len(nums) != 1 or not nums[0].startswith("iso4217:"): return False
    return True

def _measures(value: Any) -> tuple[str, ...]:
    if value is None: return ()
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError: value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple)): value = (value,)
    return tuple(str(x).lower().strip() for x in value if str(x).strip())

def _lineage(row: Mapping[str, Any], raw: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    fact = raw.get((str(row.get("source_filing_id")), str(row.get("selected_fact_id")))) or {}
    return {"analytical_fact_id": row.get("analytical_fact_id"), "source_filing_id": row.get("source_filing_id"), "selected_fact_id": row.get("selected_fact_id"), "period_key": row.get("period_key"), "period_boundaries": row.get("actual_period_boundaries"), "context_id": fact.get("context_id"), "unit_id": fact.get("unit_id"), "source_document": fact.get("source_document"), "source_locator": fact.get("source_locator")}

def _candidate_lineage(row: Mapping[str, Any], raw: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    fact = raw.get((str(row.get("source_filing_id")), str(row.get("source_fact_id")))) or {}
    return {"series_candidate_id": row.get("series_candidate_id"), "source_filing_id": row.get("source_filing_id"), "source_fact_id": row.get("source_fact_id"), "period_key": row.get("actual_period_key"), "filed_date": row.get("filed_date"), "context_id": fact.get("context_id"), "unit_id": fact.get("unit_id"), "source_document": fact.get("source_document") or row.get("source_document"), "source_locator": fact.get("source_locator") or row.get("source_locator")}

def _artifact_coverage(records: Iterable[Mapping[str, Any]], raw: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    for record in records:
        for value in (record.get("fy_source"), record.get("ytd_9m_source"), record.get("prior_as_filed_source"), record.get("later_observation")):
            if isinstance(value, Mapping): sources.append(value)
    result = []
    for source in sources:
        filing, fact_id = str(source.get("source_filing_id") or ""), str(source.get("selected_fact_id") or source.get("source_fact_id") or "")
        raw_fact = raw.get((filing, fact_id), {})
        doc, locator = source.get("source_document") or raw_fact.get("source_document"), source.get("source_locator") or raw_fact.get("source_locator")
        status = "ARTIFACT_RETAINED" if doc and locator else "ARTIFACT_NOT_RETAINED"
        result.append({"artifact_coverage_id": _id("artifact", (filing, fact_id)), "source_filing_id": filing, "source_fact_id": fact_id, "artifact_status": status, "reference_status": "REFERENCE_ONLY" if status == "ARTIFACT_NOT_RETAINED" else "RETAINED_SOURCE_REFERENCE", "source_document": doc, "source_locator": locator, "inventory_version": REVIEW_INVENTORY_VERSION})
    return list({row["artifact_coverage_id"]: row for row in result}.values())

def _id(prefix: str, value: Any) -> str: return prefix + ":" + hashlib.sha256(json.dumps(value, default=repr, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
def _canonical_json(row: Mapping[str, Any]) -> str: return json.dumps(row, default=list, sort_keys=True, separators=(",", ":"))
def _hash_rows(rows: Iterable[Mapping[str, Any]]) -> str: return hashlib.sha256("".join(_canonical_json(x) + "\n" for x in rows).encode()).hexdigest()
