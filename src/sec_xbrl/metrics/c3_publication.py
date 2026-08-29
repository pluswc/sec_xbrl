"""C3-M4 bridge from a verified C3 AS_FILED release to derived metrics.

This module is deliberately an orchestration boundary.  It does not decide
what a concept means, calculate a new formula, or make a period comparable.
Those decisions remain respectively with L2-M6, the Metric Registry/M1, and
the C3 quarterly policy.  Its only job is to make the existing governed
contracts usable for one reader-attested C3-M1 publication.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication
from sec_xbrl.longitudinal.metric_input import MetricInputHandoffMaterializer
from sec_xbrl.metrics.materialization import (
    DerivedMetricMaterializer,
    DerivedMetricPublication,
    DerivedMetricPublisher,
    DerivedMetricsRun,
)
from sec_xbrl.metrics.registry import METRIC_REGISTRY_CONTRACT_VERSION, MetricRegistry
from sec_xbrl.metrics.series import DerivedMetricSeriesMaterializer

C3_METRIC_PUBLICATION_VERSION = "c3-m4-derived-metrics-publication-v1"
_DATASETS = ("metric_input_candidate", "metric_input_compatibility", "metric_coverage")
_DEFINITION_BY_ASSESSMENT = {
    "GROSS_MARGIN": "gross_margin@1.0.0",
    "OPERATING_MARGIN": "operating_margin@1.0.0",
    "REVENUE_GROWTH": "revenue_growth@1.0.0",
    "Q4_FLOW": "q4_flow_eligibility@1.0.0",
}
_STANDARD_ROLE_BY_LOCAL_NAME = {
    "revenuefromcontractwithcustomerexcludingassessedtax": "REVENUE",
    "salesrevenuenet": "REVENUE",
    "revenues": "REVENUE",
    "revenue": "REVENUE",
    "grossprofit": "GROSS_PROFIT",
    "operatingincomeloss": "OPERATING_INCOME",
    "earningspersharebasic": "EPS",
    "earningspersharediluted": "EPS",
    "weightedaveragenumberofsharesoutstandingbasic": "WEIGHTED_AVERAGE_SHARES",
    "weightedaveragenumberofdilutedsharesoutstanding": "WEIGHTED_AVERAGE_SHARES",
}
_RESULT_ATTESTATION_TOKEN = object()


class C3MetricPublicationError(RuntimeError):
    """Raised when a C3 metric release cannot preserve its governed inputs."""


@dataclass(frozen=True, slots=True)
class C3MetricPublication:
    """Reader-verified handoff companion plus its immutable M1 metric release."""

    run_root: Path
    manifest_path: Path
    upstream_fingerprint: str
    metric_publication: DerivedMetricPublication
    output_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class C3MetricResult:
    """M6/M1 inputs that remain bound to one exact verified upstream."""

    upstream_layer2_run_fingerprint: str
    upstream_layer2_manifest_sha256: str
    candidates: tuple[dict[str, Any], ...]
    compatibility: tuple[dict[str, Any], ...]
    derived_metrics: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]
    content_fingerprint: str
    _materialization_attestation: object | None = field(default=None, repr=False, compare=False)

    @property
    def is_materialized_by_c3_pipeline(self) -> bool:
        return self._materialization_attestation is _RESULT_ATTESTATION_TOKEN

    def companion_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "metric_input_candidate": self.candidates,
            "metric_input_compatibility": self.compatibility,
            "metric_coverage": self.coverage,
        }


class C3MetricPublicationPipeline:
    """Use existing M6/M1/M2 contracts for exactly one C3-M1 AS_FILED root."""

    def __init__(self, registry: MetricRegistry) -> None:
        self.registry = registry

    def materialize(
        self,
        publication: VerifiedLayer2Publication,
        *,
        evaluated_at: str,
    ) -> C3MetricResult:
        _require_as_filed_publication(publication)
        # JSONL publication rows represent tuple-like governed signatures as
        # lists.  M6 compares them structurally, so restore immutable tuple
        # form before it validates rather than allowing a list/set membership
        # error to turn a valid published fact into an implementation failure.
        facts = tuple(
            _handoff_fact(
                row,
                default_basis=f"AS_FILED:{publication.identity['layer2_run_fingerprint']}",
            )
            for row in publication.records("analytical_fact")
        )
        handoff = MetricInputHandoffMaterializer().materialize(
            analytical_facts=facts,
            metric_definition_ids=_DEFINITION_BY_ASSESSMENT,
        )
        candidates = tuple(dict(row) for row in handoff.candidates)
        compatibility = tuple(dict(row) for row in handoff.compatibility)
        by_candidate = {str(row["metric_input_candidate_id"]): row for row in candidates}
        values_by_fact = {str(row["analytical_fact_id"]): row for row in facts}
        materializer = DerivedMetricMaterializer(self.registry)
        records: list[dict[str, Any]] = []
        for diagnostic in compatibility:
            definition_id = diagnostic.get("metric_definition_id")
            # Q4 is a registry eligibility declaration, not a numerical metric.
            if definition_id == _DEFINITION_BY_ASSESSMENT["Q4_FLOW"]:
                continue
            if not definition_id:
                continue
            definition = self.registry.resolve(str(definition_id))
            if definition.definition_id != definition_id or definition.output_semantics == "ELIGIBILITY_ONLY":
                continue
            selected = tuple(
                by_candidate[str(candidate_id)]
                for candidate_id in diagnostic.get("input_metric_input_candidate_ids", ())
                if str(candidate_id) in by_candidate
            )
            values = tuple(_value_payload(candidate, values_by_fact) for candidate in selected)
            records.append(
                materializer.materialize(
                    definition_id=str(definition_id),
                    candidates=selected,
                    compatibility=diagnostic,
                    selected_observation_values=values,
                    evaluated_at=evaluated_at,
                )
            )
        _reject_duplicate_metric_ids(records)
        coverage = _coverage(
            ciks=publication.input_ciks,
            records=records,
            compatibility=compatibility,
            upstream=publication,
        )
        records_tuple = tuple(records)
        fingerprint = _result_content_fingerprint(candidates, compatibility, records_tuple, coverage)
        return C3MetricResult(
            publication.identity["layer2_run_fingerprint"],
            publication.identity["layer2_manifest_sha256"],
            candidates,
            compatibility,
            records_tuple,
            coverage,
            fingerprint,
            _RESULT_ATTESTATION_TOKEN,
        )

    def publish(
        self,
        publication: VerifiedLayer2Publication,
        *,
        result: C3MetricResult,
        output_root: Path,
        run_version: str,
        metric_run_version: str,
        metric_output_root: Path,
        registry_version: str,
    ) -> C3MetricPublication:
        _require_as_filed_publication(publication)
        _require_result_matches_upstream(result, publication)
        if not run_version or "/" in run_version or "\\" in run_version:
            raise C3MetricPublicationError("C3 metric run_version must be a non-path identifier")
        # M1's existing atomic publisher is the metric-series admission root.
        metric_run = DerivedMetricsRun(
            metric_run_version,
            publication.identity["layer2_run_fingerprint"],
            METRIC_REGISTRY_CONTRACT_VERSION,
            registry_version,
        )
        metric_publication = DerivedMetricPublisher(metric_output_root).publish(
            metric_run, result.derived_metrics
        )
        # Force M2's hash-verified admission before declaring this C3 release usable.
        admitted = DerivedMetricSeriesMaterializer().load_published_candidates(metric_publication.run_root)
        if len(admitted) != len(result.derived_metrics):
            raise C3MetricPublicationError("M2 series admission count differs from M1 metric release")
        return C3MetricCompanionPublisher().publish(
            result,
            output_root=output_root,
            run_version=run_version,
            upstream=publication,
            metric_publication=metric_publication,
        )


class C3MetricCompanionPublisher:
    """Atomic persisted M6 handoff/coverage evidence for the C3 metric release."""

    manifest_name = "c3_metric_publication_manifest.json"

    def publish(
        self,
        result: C3MetricResult,
        *,
        output_root: Path,
        run_version: str,
        upstream: VerifiedLayer2Publication,
        metric_publication: DerivedMetricPublication,
    ) -> C3MetricPublication:
        _require_as_filed_publication(upstream)
        _require_result_matches_upstream(result, upstream)
        rows = {
            name: tuple(sorted((dict(row) for row in values), key=_canonical_json))
            for name, values in result.companion_datasets().items()
        }
        counts = {name: len(rows[name]) for name in _DATASETS}
        hashes = {name: _hash_rows(rows[name]) for name in _DATASETS}
        manifest = {
            "contract_version": C3_METRIC_PUBLICATION_VERSION,
            "run_version": run_version,
            "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
            "upstream_layer2_manifest_sha256": upstream.identity.get("layer2_manifest_sha256"),
            "metric_run_version": metric_publication.run_root.name,
            "metric_run_fingerprint": metric_publication.fingerprint,
            "metric_manifest_sha256": _file_sha256(metric_publication.manifest_path),
            "output_counts": counts,
            "output_content_sha256": hashes,
            "validation": {
                "READER_ATTESTED_AS_FILED_ONLY": "SUCCESS",
                "M6_HANDOFF_PRESERVED": "SUCCESS",
                "M1_M2_VERIFIED_ADMISSION": "SUCCESS",
                "NO_Q4_NUMERIC_METRIC": "SUCCESS",
                "ATOMIC_PUBLICATION": "SUCCESS",
            },
        }
        root, target = Path(output_root), Path(output_root) / run_version
        root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return self._existing(target, manifest, metric_publication)
        staging = Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-", dir=root))
        try:
            for name in _DATASETS:
                (staging / f"{name}.jsonl").write_text(
                    "".join(_canonical_json(row) + "\n" for row in rows[name]), encoding="utf-8"
                )
            (staging / self.manifest_name).write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
            C3MetricCompanionReader().load(staging, upstream=upstream, metric_publication=metric_publication)
            if target.exists():
                return self._existing(target, manifest, metric_publication)
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return C3MetricPublication(
            target, target / self.manifest_name, upstream.identity["layer2_run_fingerprint"], metric_publication, counts
        )

    def _existing(self, target: Path, manifest: Mapping[str, Any], metric: DerivedMetricPublication) -> C3MetricPublication:
        path = target / self.manifest_name
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise C3MetricPublicationError("C3 metric run version is incomplete") from exc
        if existing != manifest:
            raise C3MetricPublicationError("C3 metric run version already exists with different content")
        return C3MetricPublication(target, path, str(existing["upstream_layer2_run_fingerprint"]), metric, existing["output_counts"])


class C3MetricCompanionReader:
    """Fail closed on an altered companion or a mismatched upstream/M1 release."""

    def load(
        self,
        run_root: Path,
        *,
        upstream: VerifiedLayer2Publication,
        metric_publication: DerivedMetricPublication,
    ) -> C3MetricResult:
        _require_as_filed_publication(upstream)
        root = Path(run_root)
        manifest_path = root / C3MetricCompanionPublisher.manifest_name
        if not root.is_dir() or root.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
            raise C3MetricPublicationError("C3 metric companion release is missing or unsafe")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise C3MetricPublicationError("C3 metric companion manifest is invalid") from exc
        required = {
            "contract_version", "run_version", "upstream_layer2_run_fingerprint",
            "upstream_layer2_manifest_sha256", "metric_run_version", "metric_run_fingerprint",
            "metric_manifest_sha256", "output_counts", "output_content_sha256", "validation",
        }
        if set(manifest) != required or manifest.get("contract_version") != C3_METRIC_PUBLICATION_VERSION:
            raise C3MetricPublicationError("C3 metric companion manifest has unsupported contract")
        if (
            manifest.get("upstream_layer2_run_fingerprint") != upstream.identity.get("layer2_run_fingerprint")
            or manifest.get("upstream_layer2_manifest_sha256") != upstream.identity.get("layer2_manifest_sha256")
        ):
            raise C3MetricPublicationError("C3 metric companion does not match verified upstream")
        if (
            manifest.get("metric_run_version") != metric_publication.run_root.name
            or manifest.get("metric_run_fingerprint") != metric_publication.fingerprint
            or manifest.get("metric_manifest_sha256") != _file_sha256(metric_publication.manifest_path)
        ):
            raise C3MetricPublicationError("C3 metric companion does not match verified metric release")
        files = {item.name for item in root.iterdir() if item.is_file() and not item.is_symlink()}
        expected = {C3MetricCompanionPublisher.manifest_name, *(f"{name}.jsonl" for name in _DATASETS)}
        if files != expected or any(item.is_dir() or item.is_symlink() for item in root.iterdir()):
            raise C3MetricPublicationError("C3 metric companion layout is incomplete or unexpected")
        rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for name in _DATASETS:
            try:
                value = tuple(json.loads(line) for line in (root / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if line)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise C3MetricPublicationError("C3 metric companion dataset is invalid") from exc
            if (
                len(value) != manifest["output_counts"].get(name)
                or _hash_rows(value) != manifest["output_content_sha256"].get(name)
            ):
                raise C3MetricPublicationError("C3 metric companion content verification failed")
            rows[name] = tuple(dict(row) for row in value)
        # Repeat M2's admission validation; it checks the M1 manifest/content hash.
        DerivedMetricSeriesMaterializer().load_published_candidates(metric_publication.run_root)
        candidates = rows["metric_input_candidate"]
        compatibility = rows["metric_input_compatibility"]
        coverage = rows["metric_coverage"]
        return C3MetricResult(
            str(manifest["upstream_layer2_run_fingerprint"]),
            str(manifest["upstream_layer2_manifest_sha256"]),
            candidates,
            compatibility,
            (),
            coverage,
            _result_content_fingerprint(candidates, compatibility, (), coverage),
        )

    def load_metric_publication(self, run_root: Path) -> DerivedMetricPublication:
        """Attest one M1 root before it can be bound to a C3 companion.

        The generic M2 reader validates the immutable M1 manifest and JSONL
        contents.  This adapter exposes that verified identity in the shape
        required by ``load``; it does not make a generic M2 root a C3 root.
        ``load`` still checks the companion's exact fingerprint and manifest
        SHA afterwards.
        """
        root = Path(run_root)
        candidates = DerivedMetricSeriesMaterializer().load_published_candidates(root)
        manifest_path = root / DerivedMetricPublisher.manifest_name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise C3MetricPublicationError("C3 metric M1 release is unreadable") from exc
        return DerivedMetricPublication(
            root,
            manifest_path,
            str(manifest["run_fingerprint"]),
            len(candidates),
            reused_existing=False,
        )


def _require_as_filed_publication(publication: VerifiedLayer2Publication) -> None:
    if not publication.is_reader_attested:
        raise C3MetricPublicationError("C3-M4 requires a reader-attested verified C3-M1 publication")
    facts = publication.records("analytical_fact")
    if not facts or any(row.get("view") != "AS_FILED" for row in facts):
        raise C3MetricPublicationError("C3-M4 accepts an AS_FILED-only C3-M1 publication")
    if not publication.identity.get("layer2_run_fingerprint") or not publication.identity.get("layer2_manifest_sha256"):
        raise C3MetricPublicationError("verified C3-M1 publication lacks immutable identity")


def _require_result_matches_upstream(
    result: C3MetricResult, publication: VerifiedLayer2Publication
) -> None:
    if not result.is_materialized_by_c3_pipeline:
        raise C3MetricPublicationError("C3 metric publication requires a pipeline-materialized result")
    if result.content_fingerprint != _result_content_fingerprint(
        result.candidates, result.compatibility, result.derived_metrics, result.coverage
    ):
        raise C3MetricPublicationError("C3 metric materialization result content has been altered")
    if (
        result.upstream_layer2_run_fingerprint != publication.identity.get("layer2_run_fingerprint")
        or result.upstream_layer2_manifest_sha256 != publication.identity.get("layer2_manifest_sha256")
    ):
        raise C3MetricPublicationError(
            "C3 metric materialization result does not match supplied verified upstream"
        )


def _value_payload(candidate: Mapping[str, Any], facts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    source = facts.get(str(candidate.get("analytical_fact_id")))
    if source is None:
        # M1 turns this into an auditable UNAVAILABLE record rather than guessing a value.
        return {"metric_input_candidate_id": candidate["metric_input_candidate_id"]}
    payload = {
        "metric_input_candidate_id": candidate["metric_input_candidate_id"],
        "analytical_fact_id": candidate["analytical_fact_id"],
        "value_decimal": source.get("value_numeric"),
    }
    for key in (
        "source_filing_id", "view", "as_of_date", "basis_version", "series_type", "period_class",
        "period_key", "company_canonical_dimension_key", "unit_semantics", "mapping_version", "source_type",
    ):
        payload[key] = candidate.get(key)
    return payload


def _handoff_fact(source: Mapping[str, Any], *, default_basis: str) -> dict[str, Any]:
    row = dict(source)
    for key in ("company_canonical_dimension_key", "unit_semantics", "source_fact_ids"):
        if key in row:
            row[key] = _freeze(row[key])
    mapping_version = row.get("mapping_version")
    if isinstance(mapping_version, (list, tuple)):
        if len(mapping_version) != 1:
            raise C3MetricPublicationError(
                "C3 analytical fact has no single governed mapping version for M6 handoff"
            )
        row["mapping_version"] = str(mapping_version[0])
    if row.get("basis_version") in {None, ""}:
        # Raw AS_FILED observations need an explicit basis key downstream to
        # prevent any later comparable view from coalescing with them.  This
        # deterministic key names the exact verified input release; it does
        # not alter the raw fact or select a new value.
        row["basis_version"] = default_basis
    # C3's selected fact intentionally retains its opaque raw ID.  The
    # canonical mapping evidence preserves the original standard QName.  An
    # explicit role may therefore be handed off only when one standard QName
    # is present; custom concepts and ambiguous evidence are left unassigned.
    role = _standard_role_from_mapping_evidence(row.get("mapping_evidence"))
    if role:
        row["metric_input_role"] = role
    # M6 also recognises a role from its raw_concept_id convenience field.
    # C3 raw concept IDs are opaque identities (and a custom ID may end in
    # ``:Revenue``), so passing it through would create a forbidden local-name
    # fallback.  The explicit role above is the only semantic bridge here.
    row["raw_concept_id"] = None
    return row


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _standard_role_from_mapping_evidence(value: object) -> str | None:
    roles: set[str] = set()
    items = _mapping_evidence_items(value)
    if not items:
        return None
    for evidence in items:
        qname = evidence.get("qname")
        if not isinstance(qname, str) or not qname.lower().startswith("us-gaap:"):
            return None
        local = "".join(char.lower() for char in qname.rsplit(":", 1)[-1] if char.isalnum())
        role = _STANDARD_ROLE_BY_LOCAL_NAME.get(local)
        if role is None:
            return None
        roles.add(role)
    return next(iter(roles)) if len(roles) == 1 else None


def _mapping_evidence_items(value: object) -> tuple[Mapping[str, Any], ...]:
    """Normalize C3's documented mapping-evidence container shapes.

    A mapping entry can be supplied directly as ``{"qname": ...}``, wrapped
    as ``{"evidence": {"qname": ...}}``, or serialized as a list/tuple of
    those entries.  Other mappings are deliberately not traversed: accepting
    arbitrary nested values would turn incidental text into semantic evidence.
    """
    if isinstance(value, Mapping):
        if "qname" in value:
            return (value,)
        nested = value.get("evidence")
        return _mapping_evidence_items(nested) if nested is not None else ()
    if isinstance(value, (list, tuple)):
        items: list[Mapping[str, Any]] = []
        for entry in value:
            nested = _mapping_evidence_items(entry)
            if not nested:
                return ()
            items.extend(nested)
        return tuple(items)
    return ()


def _coverage(
    *,
    ciks: Iterable[str],
    records: Iterable[Mapping[str, Any]],
    compatibility: Iterable[Mapping[str, Any]],
    upstream: VerifiedLayer2Publication,
) -> tuple[dict[str, Any], ...]:
    by_cik: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        by_cik[str(row.get("cik"))].append(row)
    compatibility_by_cik: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in compatibility:
        compatibility_by_cik[str(row.get("cik"))].append(row)
    output = []
    for cik in sorted({str(value) for value in ciks}):
        rows = by_cik[cik]
        status = Counter(str(row.get("calculation_status")) for row in rows)
        reasons = Counter(str(row.get("unavailable_reason")) for row in rows if row.get("unavailable_reason"))
        output.append({
            "cik": cik,
            "metric_definition_versions": tuple(sorted({str(row["metric_definition_id"]) for row in rows})),
            "available_count": status["AVAILABLE"],
            "unavailable_count": status["UNAVAILABLE"],
            "unavailable_reasons": dict(sorted(reasons.items())),
            "period_classes": tuple(sorted({str(row["period_class"]) for row in rows})),
            "views": tuple(sorted({str(row["view"]) for row in rows})),
            "basis_versions": tuple(sorted({str(row["basis_version"]) for row in rows})),
            "compatibility_count": len(compatibility_by_cik[cik]),
            "input_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
            "input_layer2_manifest_sha256": upstream.identity["layer2_manifest_sha256"],
            "metric_publication_scope": "AS_FILED_ONLY",
        })
    return tuple(output)


def _reject_duplicate_metric_ids(rows: Iterable[Mapping[str, Any]]) -> None:
    ids = [str(row["derived_metric_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise C3MetricPublicationError("C3 input would create duplicate immutable derived_metric IDs")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=list)


def _hash_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(tuple(dict(row) for row in rows)).encode("utf-8")).hexdigest()


def _result_content_fingerprint(
    candidates: Iterable[Mapping[str, Any]],
    compatibility: Iterable[Mapping[str, Any]],
    derived_metrics: Iterable[Mapping[str, Any]],
    coverage: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "candidate": tuple(dict(row) for row in candidates),
        "compatibility": tuple(dict(row) for row in compatibility),
        "derived_metric": tuple(dict(row) for row in derived_metrics),
        "coverage": tuple(dict(row) for row in coverage),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
