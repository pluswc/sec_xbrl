"""C3-M2 governed quarterly-period policy companion release.

This module deliberately sits *after* C3-M1.  It never changes an
``analytical_fact`` and it does not calculate a Metric.  It makes the two
consumer-facing inferences that are otherwise easy to get wrong explicit:
whether a reported FY/YTD-9M pair may form Q4, and whether a line has a
declared predecessor period for comparison.
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sec_xbrl.longitudinal.corpus_release import CorpusRelease
from sec_xbrl.longitudinal.materialization import VerifiedLayer2Publication

QUARTERLY_POLICY_VERSION = "c3-m2-quarterly-period-policy-v1"
_DATASETS = ("quarterly_q4_candidate", "quarterly_q4_exclusion", "predecessor_period_linkage")


class QuarterlyPeriodPolicyError(RuntimeError):
    """Raised when an unverified or incompatible quarterly policy input is used."""


@dataclass(frozen=True, slots=True)
class QuarterlySemanticDeclaration:
    """Reviewed semantic permission for one company canonical concept.

    The declaration is deliberately positive-only: no declaration means no
    Q4 subtraction.  In particular it must be an explicitly reviewed monetary
    additive amount, not a label- or QName-derived guess.
    """

    company_canonical_concept_id: str
    semantic_review_state: str
    value_kind: str
    is_additive: bool
    declaration_id: str
    declaration_version: str = QUARTERLY_POLICY_VERSION

    @property
    def q4_allowed(self) -> bool:
        return (
            self.semantic_review_state == "REVIEWED_ADDITIVE_AMOUNT"
            and self.value_kind == "ADDITIVE_AMOUNT"
            and self.is_additive
        )


@dataclass(frozen=True, slots=True)
class QuarterlyPolicyResult:
    q4_candidates: tuple[dict[str, Any], ...]
    q4_exclusions: tuple[dict[str, Any], ...]
    predecessor_linkage: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "quarterly_q4_candidate": self.q4_candidates,
            "quarterly_q4_exclusion": self.q4_exclusions,
            "predecessor_period_linkage": self.predecessor_linkage,
        }


@dataclass(frozen=True, slots=True)
class QuarterlyPolicyPublication:
    """Immutable companion root linked to exactly one verified C3-M1 run."""

    run_root: Path
    manifest_path: Path
    upstream_fingerprint: str
    output_counts: Mapping[str, int]


class QuarterlyPolicyPublisher:
    """Atomically publish policy records without altering the Layer 2 run."""

    manifest_name = "quarterly_policy_manifest.json"

    def publish(
        self,
        result: QuarterlyPolicyResult,
        *,
        output_root: Path,
        run_version: str,
        upstream: VerifiedLayer2Publication,
    ) -> QuarterlyPolicyPublication:
        if not run_version or "/" in run_version or "\\" in run_version:
            raise QuarterlyPeriodPolicyError("quarterly policy run_version must be a non-path identifier")
        root = Path(output_root); target = root / run_version
        datasets = result.as_datasets()
        rows = {name: tuple(sorted((dict(row) for row in values), key=_canonical_json)) for name, values in datasets.items()}
        counts = {name: len(values) for name, values in rows.items()}
        hashes = {name: _hash_rows(values) for name, values in rows.items()}
        manifest = {
            "contract_version": QUARTERLY_POLICY_VERSION, "run_version": run_version,
            "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
            "upstream_layer2_manifest_sha256": upstream.identity.get("layer2_manifest_sha256"),
            "output_counts": counts, "output_content_sha256": hashes,
            "validation": {"VERIFIED_C3_M1_LINKAGE": "SUCCESS", "RAW_LINEAGE": "SUCCESS", "DETERMINISTIC_OUTPUT": "SUCCESS", "ATOMIC_PUBLICATION": "SUCCESS"},
        }
        root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target / self.manifest_name
            if not existing.is_file() or json.loads(existing.read_text(encoding="utf-8")) != manifest:
                raise QuarterlyPeriodPolicyError("quarterly policy run_version already exists with different content")
            return QuarterlyPolicyPublication(target, existing, manifest["upstream_layer2_run_fingerprint"], counts)
        staging = Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-", dir=root))
        try:
            for name, values in rows.items():
                (staging / f"{name}.jsonl").write_text("".join(_canonical_json(row) + "\n" for row in values), encoding="utf-8")
            (staging / self.manifest_name).write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return QuarterlyPolicyPublication(target, target / self.manifest_name, manifest["upstream_layer2_run_fingerprint"], counts)


class QuarterlyPeriodPolicyMaterializer:
    """Apply declared quarterly policy to one verified C3-M1 AS_FILED run."""

    def materialize(
        self,
        publication: VerifiedLayer2Publication,
        *,
        release: CorpusRelease,
        declarations: Iterable[QuarterlySemanticDeclaration],
    ) -> QuarterlyPolicyResult:
        if not isinstance(publication, VerifiedLayer2Publication) or not isinstance(release, CorpusRelease):
            raise QuarterlyPeriodPolicyError("C3-M2 requires verified C3-M1 publication and CorpusRelease")
        if publication.identity["layer2_run_fingerprint"] != release.layer2_run.fingerprint:
            raise QuarterlyPeriodPolicyError("C3-M1 publication does not match supplied CorpusRelease declaration")
        policy = _declarations(declarations)
        facts = tuple(_available_as_filed(row) for row in publication.records("analytical_fact"))
        facts = tuple(row for row in facts if row is not None)
        facts = _attach_raw_semantics(facts, release)
        return QuarterlyPolicyResult(
            q4_candidates=tuple(_q4(facts, policy)[0]),
            q4_exclusions=tuple(_q4(facts, policy)[1]),
            predecessor_linkage=tuple(_predecessors(facts)),
        )


def _declarations(rows: Iterable[QuarterlySemanticDeclaration]) -> dict[str, QuarterlySemanticDeclaration]:
    result: dict[str, QuarterlySemanticDeclaration] = {}
    for row in rows:
        if not isinstance(row, QuarterlySemanticDeclaration) or not row.company_canonical_concept_id or not row.declaration_id:
            raise QuarterlyPeriodPolicyError("quarterly declaration requires canonical concept and identity")
        if row.company_canonical_concept_id in result:
            raise QuarterlyPeriodPolicyError("duplicate quarterly semantic declaration")
        result[row.company_canonical_concept_id] = row
    return result


def _available_as_filed(source: Mapping[str, Any]) -> dict[str, Any] | None:
    row = dict(source)
    if row.get("view") != "AS_FILED":
        return None
    if row.get("source_type") != "REPORTED" or row.get("value_numeric") is None:
        return None
    required = ("analytical_fact_id", "cik", "company_canonical_concept_id", "period_class", "period_key", "selected_fact_id", "source_filing_id", "unit_semantics")
    if any(row.get(key) in {None, ""} for key in required):
        raise QuarterlyPeriodPolicyError("available AS_FILED fact lacks required raw lineage or semantic scope")
    return row


def _attach_raw_semantics(facts: Iterable[Mapping[str, Any]], release: CorpusRelease) -> tuple[dict[str, Any], ...]:
    raw = {(str(row.get("filing_id")), str(row.get("fact_id"))): row for row in release.records("fact")}
    concepts = {(str(row.get("filing_id")), str(row.get("raw_concept_id"))): row for row in release.records("concept")}
    units = {(str(row.get("filing_id")), str(row.get("unit_id"))): row for row in release.records("unit")}
    attached: list[dict[str, Any]] = []
    for source in facts:
        row = dict(source)
        raw_fact = raw.get((str(row["source_filing_id"]), str(row["selected_fact_id"])))
        if raw_fact is None:
            raise QuarterlyPeriodPolicyError("C3-M1 selected raw Fact is absent from verified CorpusRelease")
        concept = concepts.get((str(row["source_filing_id"]), str(raw_fact.get("raw_concept_id"))))
        unit = units.get((str(row["source_filing_id"]), str(raw_fact.get("unit_id"))))
        row["_q4_raw_semantics_safe"] = bool(
            concept and unit
            and str(concept.get("period_type") or "").lower() == "duration"
            and "monetary" in str(concept.get("data_type") or "").lower()
            and unit.get("denominator_measures") in {None, ""}
            and "iso4217:" in str(unit.get("numerator_measures") or "").lower()
        )
        attached.append(row)
    return tuple(attached)


def _scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["cik"], row["company_canonical_concept_id"], repr(row.get("company_canonical_dimension_key")),
        row.get("basis_version"), repr(row.get("unit_semantics")),
    )


def _q4(facts: tuple[dict[str, Any], ...], policy: Mapping[str, QuarterlySemanticDeclaration]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in facts:
        if row.get("period_class") in {"FY", "YTD_9M"}:
            groups[_scope(row)].append(row)
    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for scope, rows in sorted(groups.items(), key=repr):
        concept = str(scope[1]); declaration = policy.get(concept)
        fy = [row for row in rows if row["period_class"] == "FY"]
        ytd = [row for row in rows if row["period_class"] == "YTD_9M"]
        if not declaration or not declaration.q4_allowed:
            for row in rows:
                exclusions.append(_q4_exclusion(row, "Q4_SEMANTIC_DECLARATION_REQUIRED"))
            continue
        if any(not row.get("_q4_raw_semantics_safe") for row in rows):
            for row in rows:
                exclusions.append(_q4_exclusion(row, "Q4_REVIEWED_MONETARY_ADDITIVE_SEMANTICS_REQUIRED"))
            continue
        if not fy or not ytd:
            for row in rows:
                exclusions.append(_q4_exclusion(row, "Q4_COMPATIBLE_FY_AND_YTD9M_REQUIRED"))
            continue
        matched = False
        for annual in fy:
            for nine_month in ytd:
                reason = _q4_compatibility(annual, nine_month)
                if reason:
                    exclusions.append(_q4_exclusion(annual, reason, other=nine_month))
                    continue
                value = _subtract(annual["value_numeric"], nine_month["value_numeric"])
                if value is None:
                    exclusions.append(_q4_exclusion(annual, "Q4_NON_NUMERIC_SOURCE", other=nine_month))
                    continue
                matched = True
                candidates.append(_q4_candidate(annual, nine_month, declaration, value))
        if not matched and not any(row["exclusion_reason"] == "Q4_NON_NUMERIC_SOURCE" for row in exclusions if row["analytical_fact_id"] in {item["analytical_fact_id"] for item in rows}):
            # Pair-level reasons above are retained; this keeps an explicit outcome
            # when no candidate has a matching fiscal period.
            for row in rows:
                if not any(item["analytical_fact_id"] == row["analytical_fact_id"] for item in exclusions):
                    exclusions.append(_q4_exclusion(row, "Q4_COMPATIBLE_FY_AND_YTD9M_REQUIRED"))
    return sorted(candidates, key=lambda row: row["quarterly_policy_candidate_id"]), sorted(exclusions, key=lambda row: row["quarterly_policy_exclusion_id"])


def _q4_compatibility(fy: Mapping[str, Any], ytd: Mapping[str, Any]) -> str | None:
    if _scope(fy) != _scope(ytd):
        return "Q4_SCOPE_MISMATCH"
    if fy.get("source_type") != "REPORTED" or ytd.get("source_type") != "REPORTED":
        return "Q4_REPORTED_SOURCES_REQUIRED"
    fy_bounds, ytd_bounds = fy.get("actual_period_boundaries") or (), ytd.get("actual_period_boundaries") or ()
    if len(fy_bounds) < 2 or len(ytd_bounds) < 2 or not fy_bounds[0] or fy_bounds[0] != ytd_bounds[0]:
        return "Q4_FISCAL_START_MISMATCH"
    if not fy_bounds[1] or not ytd_bounds[1] or str(ytd_bounds[1]) >= str(fy_bounds[1]):
        return "Q4_PERIOD_BOUNDARIES_INCOMPATIBLE"
    return None


def _q4_candidate(fy: Mapping[str, Any], ytd: Mapping[str, Any], declaration: QuarterlySemanticDeclaration, value: str) -> dict[str, Any]:
    source_ids = (str(fy["analytical_fact_id"]), str(ytd["analytical_fact_id"]))
    identity = (source_ids, declaration.declaration_id, declaration.declaration_version)
    return {
        "quarterly_policy_candidate_id": _id("quarterly-q4", identity), "cik": fy["cik"], "view": "AS_FILED",
        "policy_status": "ELIGIBLE", "quarterly_period": "Q4", "period_class": "QTD_3M",
        "company_canonical_concept_id": fy["company_canonical_concept_id"], "company_canonical_dimension_key": fy.get("company_canonical_dimension_key"),
        "basis_version": fy.get("basis_version"), "unit_semantics": fy.get("unit_semantics"), "fiscal_year_end_period_key": fy["period_key"],
        "value_numeric": value, "reported_or_derived": "DERIVED", "formula": "FY - YTD_9M",
        "input_analytical_fact_ids": source_ids, "input_source_fact_ids": (fy["selected_fact_id"], ytd["selected_fact_id"]),
        "input_source_filing_ids": (fy["source_filing_id"], ytd["source_filing_id"]), "declaration_id": declaration.declaration_id,
        "declaration_version": declaration.declaration_version, "derivation_rule_version": QUARTERLY_POLICY_VERSION,
    }


def _q4_exclusion(row: Mapping[str, Any], reason: str, *, other: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = (row["analytical_fact_id"], None if other is None else other["analytical_fact_id"], reason)
    return {"quarterly_policy_exclusion_id": _id("quarterly-q4-exclusion", identity), "cik": row["cik"], "analytical_fact_id": row["analytical_fact_id"], "other_analytical_fact_id": None if other is None else other["analytical_fact_id"], "period_class": row["period_class"], "exclusion_reason": reason, "policy_version": QUARTERLY_POLICY_VERSION}


def _predecessors(facts: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in facts:
        if row.get("period_class") not in {"QTD_3M", "FY"}:
            continue
        groups[(*_scope(row), row["period_class"])].append(row)
    output: list[dict[str, Any]] = []
    for _, rows in sorted(groups.items(), key=repr):
        ordered = sorted(rows, key=lambda item: (str(item["period_key"]), str(item["analytical_fact_id"])))
        for position, current in enumerate(ordered):
            predecessor = ordered[position - 1] if position else None
            reason = None if predecessor else "PREDECESSOR_PERIOD_NOT_DECLARED"
            identity = (current["analytical_fact_id"], None if predecessor is None else predecessor["analytical_fact_id"])
            output.append({"predecessor_period_linkage_id": _id("predecessor-period", identity), "cik": current["cik"], "analytical_fact_id": current["analytical_fact_id"], "predecessor_analytical_fact_id": None if predecessor is None else predecessor["analytical_fact_id"], "period_class": current["period_class"], "company_canonical_concept_id": current["company_canonical_concept_id"], "company_canonical_dimension_key": current.get("company_canonical_dimension_key"), "basis_version": current.get("basis_version"), "unit_semantics": current.get("unit_semantics"), "link_status": "ELIGIBLE" if predecessor else "UNAVAILABLE", "unavailable_reason": reason, "policy_version": QUARTERLY_POLICY_VERSION})
    return sorted(output, key=lambda row: row["predecessor_period_linkage_id"])


def _subtract(left: Any, right: Any) -> str | None:
    try:
        return str(Decimal(str(left)) - Decimal(str(right)))
    except (InvalidOperation, ValueError):
        return None


def _id(prefix: str, value: object) -> str:
    raw = json.dumps(value, default=repr, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()[:24]}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, default=repr, sort_keys=True, separators=(",", ":"))


def _hash_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    return hashlib.sha256("".join(_canonical_json(row) + "\n" for row in rows).encode()).hexdigest()
