"""Broad, structural FY minus YTD-9M candidates for Layer 2.

This is a separate companion contract, not the reviewed Q4 policy registry.
It makes mechanically compatible candidates broadly available for later,
evidence-based consumer selection; it never declares a candidate additive.
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

MECHANICAL_Q4_VERSION = "l2-m8-mechanical-q4-v1"
_DATASETS = ("mechanical_q4_candidate", "mechanical_q4_exclusion")


class MechanicalQ4Error(RuntimeError):
    """Raised when the companion cannot be safely created or consumed."""


@dataclass(frozen=True, slots=True)
class MechanicalQ4Result:
    candidates: tuple[dict[str, Any], ...]
    exclusions: tuple[dict[str, Any], ...]

    def as_datasets(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "mechanical_q4_candidate": self.candidates,
            "mechanical_q4_exclusion": self.exclusions,
        }


@dataclass(frozen=True, slots=True)
class MechanicalQ4Publication:
    run_root: Path
    manifest_path: Path
    output_counts: Mapping[str, int]


class MechanicalQ4Materializer:
    """Create structural residuals from attested AS_FILED facts only."""

    def materialize(
        self, publication: VerifiedLayer2Publication, *, release: CorpusRelease
    ) -> MechanicalQ4Result:
        _validate_inputs(publication, release)
        raw = _index(release.records("fact"), "filing_id", "fact_id")
        concepts = _index(release.records("concept"), "filing_id", "raw_concept_id")
        units = _index(release.records("unit"), "filing_id", "unit_id")
        pre_targets = {
            (str(row.get("filing_id")), str(row.get("to_raw_concept_id")))
            for row in release.records("relationship")
            if row.get("network_type") == "PRE"
        }
        eligible: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        exclusions: list[dict[str, Any]] = []
        for source in publication.records("analytical_fact"):
            if not _input_period(source):
                continue
            fact = raw.get(
                (str(source.get("source_filing_id")), str(source.get("selected_fact_id")))
            )
            if (
                fact is None
                or fact.get("value_numeric") is None
                or source.get("value_numeric") is None
            ):
                exclusions.append(_exclusion(source, "Q4_REPORTED_NUMERIC_RAW_FACT_REQUIRED"))
                continue
            concept = concepts.get(
                (str(source.get("source_filing_id")), str(fact.get("raw_concept_id")))
            )
            if concept is None or str(concept.get("period_type") or "").lower() != "duration":
                exclusions.append(_exclusion(source, "Q4_DURATION_CONCEPT_REQUIRED"))
                continue
            unit = units.get((str(source.get("source_filing_id")), str(fact.get("unit_id"))))
            if not _tokens(None if unit is None else unit.get("numerator_measures")) or _tokens(
                None if unit is None else unit.get("denominator_measures")
            ):
                exclusions.append(_exclusion(source, "Q4_SIMPLE_UNIT_REQUIRED"))
                continue
            row = dict(source)
            row["_concept"], row["_unit"] = concept, unit
            row["_pre_present"] = (
                str(source.get("source_filing_id")),
                str(fact.get("raw_concept_id")),
            ) in pre_targets
            eligible[_scope(row)].append(row)
        candidates: list[dict[str, Any]] = []
        for rows in eligible.values():
            candidates.extend(_derive_scope(rows, exclusions))
        unique = {row["mechanical_q4_exclusion_id"]: row for row in exclusions}
        return MechanicalQ4Result(
            tuple(sorted(candidates, key=lambda row: row["mechanical_q4_id"])),
            tuple(sorted(unique.values(), key=lambda row: row["mechanical_q4_exclusion_id"])),
        )


class MechanicalQ4Publisher:
    """Atomically publish a companion immutablely bound to its two inputs."""

    manifest_name = "mechanical_q4_manifest.json"

    def publish(
        self,
        result: MechanicalQ4Result,
        *,
        output_root: Path,
        run_version: str,
        upstream: VerifiedLayer2Publication,
        release: CorpusRelease,
    ) -> MechanicalQ4Publication:
        _validate_inputs(upstream, release)
        if not run_version or "/" in run_version or "\\" in run_version:
            raise MechanicalQ4Error("mechanical Q4 run_version must be a non-path identifier")
        rows = {
            name: tuple(sorted((dict(row) for row in values), key=_json))
            for name, values in result.as_datasets().items()
        }
        counts, hashes = (
            {name: len(values) for name, values in rows.items()},
            {name: _hash(values) for name, values in rows.items()},
        )
        manifest = {
            "contract_version": MECHANICAL_Q4_VERSION,
            "run_version": run_version,
            "upstream_layer2_run_fingerprint": upstream.identity["layer2_run_fingerprint"],
            "upstream_layer2_manifest_sha256": upstream.identity["layer2_manifest_sha256"],
            "corpus_release_fingerprint": release.layer2_run.fingerprint,
            "output_counts": counts,
            "output_content_sha256": hashes,
        }
        root, target = Path(output_root), Path(output_root) / run_version
        root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            path = target / self.manifest_name
            if not path.is_file() or _read_json(path) != manifest:
                raise MechanicalQ4Error(
                    "mechanical Q4 run_version already exists with different content"
                )
            return MechanicalQ4Publication(target, path, counts)
        staging = Path(tempfile.mkdtemp(prefix=f".partial-{run_version}-", dir=root))
        try:
            for name, values in rows.items():
                (staging / f"{name}.jsonl").write_text(
                    "".join(_json(row) + "\n" for row in values), encoding="utf-8"
                )
            (staging / self.manifest_name).write_text(_json(manifest) + "\n", encoding="utf-8")
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return MechanicalQ4Publication(target, target / self.manifest_name, counts)


class MechanicalQ4Reader:
    """Fail closed unless content and both upstream identities match exactly."""

    def load(
        self, run_root: Path, *, upstream: VerifiedLayer2Publication, release: CorpusRelease
    ) -> MechanicalQ4Result:
        _validate_inputs(upstream, release)
        root, path = Path(run_root), Path(run_root) / MechanicalQ4Publisher.manifest_name
        if not root.is_dir() or root.is_symlink() or not path.is_file() or path.is_symlink():
            raise MechanicalQ4Error("mechanical Q4 companion release is missing or unsafe")
        manifest = _read_json(path)
        required = {
            "contract_version",
            "run_version",
            "upstream_layer2_run_fingerprint",
            "upstream_layer2_manifest_sha256",
            "corpus_release_fingerprint",
            "output_counts",
            "output_content_sha256",
        }
        if set(manifest) != required or manifest.get("contract_version") != MECHANICAL_Q4_VERSION:
            raise MechanicalQ4Error("mechanical Q4 companion manifest has unsupported contract")
        if (
            manifest.get("upstream_layer2_run_fingerprint")
            != upstream.identity["layer2_run_fingerprint"]
            or manifest.get("upstream_layer2_manifest_sha256")
            != upstream.identity["layer2_manifest_sha256"]
            or manifest.get("corpus_release_fingerprint") != release.layer2_run.fingerprint
        ):
            raise MechanicalQ4Error("mechanical Q4 companion does not match verified inputs")
        expected = {MechanicalQ4Publisher.manifest_name, *(f"{name}.jsonl" for name in _DATASETS)}
        actual = {
            child.name for child in root.iterdir() if child.is_file() and not child.is_symlink()
        }
        if actual != expected or any(
            child.is_dir() or child.is_symlink() for child in root.iterdir()
        ):
            raise MechanicalQ4Error("mechanical Q4 companion layout is incomplete or unexpected")
        rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for name in _DATASETS:
            try:
                values = tuple(
                    json.loads(line)
                    for line in (root / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MechanicalQ4Error("mechanical Q4 companion dataset is invalid") from exc
            if (
                any(not isinstance(row, dict) for row in values)
                or len(values) != manifest["output_counts"].get(name)
                or _hash(values) != manifest["output_content_sha256"].get(name)
            ):
                raise MechanicalQ4Error("mechanical Q4 companion content verification failed")
            rows[name] = tuple(dict(row) for row in values)
        return MechanicalQ4Result(rows["mechanical_q4_candidate"], rows["mechanical_q4_exclusion"])


def _validate_inputs(publication: VerifiedLayer2Publication, release: CorpusRelease) -> None:
    if not isinstance(publication, VerifiedLayer2Publication) or not publication.is_reader_attested:
        raise MechanicalQ4Error("mechanical Q4 requires reader-attested Layer 2 publication")
    if (
        not isinstance(release, CorpusRelease)
        or publication.identity.get("layer2_run_fingerprint") != release.layer2_run.fingerprint
        or set(publication.input_ciks) != set(release.ciks)
    ):
        raise MechanicalQ4Error("mechanical Q4 publication does not match CorpusRelease")


def _input_period(row: Mapping[str, Any]) -> bool:
    return (
        row.get("view") == "AS_FILED"
        and row.get("source_type") == "REPORTED"
        and row.get("period_class") in {"FY", "YTD_9M"}
    )


def _derive_scope(
    rows: Iterable[dict[str, Any]], exclusions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    annual, ytd = (
        [row for row in rows if row["period_class"] == kind] for kind in ("FY", "YTD_9M")
    )
    pairs: dict[str, list[tuple[dict[str, Any], dict[str, Any], str]]] = defaultdict(list)
    for fy in annual:
        for nine in ytd:
            if not _compatible(fy, nine):
                continue
            value = _subtract(fy["value_numeric"], nine["value_numeric"])
            if value is None:
                exclusions.extend(
                    (
                        _exclusion(fy, "Q4_NUMERIC_SUBTRACTION_FAILED"),
                        _exclusion(nine, "Q4_NUMERIC_SUBTRACTION_FAILED"),
                    )
                )
                continue
            pairs[_bounds(fy)[1] or ""].append((fy, nine, value))
    result: list[dict[str, Any]] = []
    for compatible_pairs in pairs.values():
        if len(compatible_pairs) == 1:
            result.append(_candidate(*compatible_pairs[0]))
        else:
            exclusions.extend(_ambiguous(compatible_pairs))
    return result


def _scope(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("cik"),
        row.get("company_canonical_concept_id"),
        _freeze(row.get("company_canonical_dimension_key")),
        _freeze(row.get("basis_version")),
        _freeze(row.get("unit_semantics")),
    )


def _bounds(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    values = row.get("actual_period_boundaries") or ()
    return (
        (None if len(values) < 1 or values[0] is None else str(values[0])),
        (None if len(values) < 2 or values[1] is None else str(values[1])),
    )


def _compatible(fy: Mapping[str, Any], ytd: Mapping[str, Any]) -> bool:
    fy_start, fy_end = _bounds(fy)
    ytd_start, ytd_end = _bounds(ytd)
    return bool(
        fy_start and fy_end and ytd_start and ytd_end and fy_start == ytd_start and ytd_end < fy_end
    )


def _candidate(fy: Mapping[str, Any], ytd: Mapping[str, Any], value: str) -> dict[str, Any]:
    ids = (str(fy["analytical_fact_id"]), str(ytd["analytical_fact_id"]))
    return {
        "mechanical_q4_id": "mechanical-q4:" + "|".join(ids),
        "cik": fy["cik"],
        "company_canonical_concept_id": fy["company_canonical_concept_id"],
        "company_canonical_dimension_key": fy.get("company_canonical_dimension_key"),
        "basis_version": fy.get("basis_version"),
        "unit_semantics": fy.get("unit_semantics"),
        "period_class": "QTD_3M",
        "fiscal_year_end_period_key": fy["period_key"],
        "actual_period_boundaries": (_bounds(ytd)[1], _bounds(fy)[1]),
        "value_numeric": value,
        "reported_or_derived": "DERIVED",
        "formula": "FY - YTD_9M",
        "input_analytical_fact_ids": ids,
        "input_source_fact_ids": (str(fy["selected_fact_id"]), str(ytd["selected_fact_id"])),
        "input_source_filing_ids": (str(fy["source_filing_id"]), str(ytd["source_filing_id"])),
        "derivation_rule_version": MECHANICAL_Q4_VERSION,
        "review_flags": _flags(fy, ytd),
        "selection_status": "MECHANICAL_CANDIDATE_REVIEW_REQUIRED",
    }


def _flags(fy: Mapping[str, Any], ytd: Mapping[str, Any]) -> tuple[str, ...]:
    flags: set[str] = set()
    if fy.get("company_canonical_dimension_key") not in (None, (), []):
        flags.add("DIMENSIONED")
    if not fy.get("_pre_present") or not ytd.get("_pre_present"):
        flags.add("PRIMARY_STATEMENT_PRE_ABSENT")
    if fy.get("basis_version") is not None or ytd.get("basis_version") is not None:
        flags.update(("BASIS_VERSION_PRESENT", "RECAST_SENSITIVE"))
    if "us-gaap" not in str(fy["_concept"].get("namespace_uri") or ""):
        flags.add("CUSTOM_CONCEPT")
    measures = _tokens(fy["_unit"].get("numerator_measures") if fy.get("_unit") else None)
    if measures == ("xbrli:pure",):
        flags.add("PURE_UNIT")
    if any("shares" in measure for measure in measures):
        flags.add("SHARES_UNIT")
    return tuple(sorted(flags))


def _ambiguous(pairs: Iterable[tuple[dict[str, Any], dict[str, Any], str]]) -> list[dict[str, Any]]:
    involved = {str(row["analytical_fact_id"]): row for pair in pairs for row in pair[:2]}
    ordered = tuple(involved[key] for key in sorted(involved))
    ids = tuple(str(row["analytical_fact_id"]) for row in ordered)
    return [
        {
            "mechanical_q4_exclusion_id": f"mechanical-q4-exclusion:{row['analytical_fact_id']}:ambiguous",
            "cik": row.get("cik"),
            "analytical_fact_id": row["analytical_fact_id"],
            "exclusion_reason": "Q4_AMBIGUOUS_COMPATIBLE_INPUT_PAIR",
            "implicated_analytical_fact_ids": ids,
            "implicated_source_fact_ids": tuple(str(item["selected_fact_id"]) for item in ordered),
            "implicated_source_filing_ids": tuple(
                str(item["source_filing_id"]) for item in ordered
            ),
            "policy_version": MECHANICAL_Q4_VERSION,
        }
        for row in ordered
    ]


def _exclusion(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "mechanical_q4_exclusion_id": f"mechanical-q4-exclusion:{row.get('analytical_fact_id')}:{reason}",
        "cik": row.get("cik"),
        "analytical_fact_id": row.get("analytical_fact_id"),
        "source_fact_id": row.get("selected_fact_id"),
        "source_filing_id": row.get("source_filing_id"),
        "period_class": row.get("period_class"),
        "exclusion_reason": reason,
        "policy_version": MECHANICAL_Q4_VERSION,
    }


def _index(rows: Iterable[Mapping[str, Any]], *keys: str) -> dict[tuple[str, ...], dict[str, Any]]:
    return {tuple(str(row.get(key)) for key in keys): dict(row) for row in rows}


def _tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple)):
        value = (value,)
    return tuple(str(item).lower() for item in value if str(item))


def _freeze(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    return value


def _subtract(left: Any, right: Any) -> str | None:
    try:
        return str(Decimal(str(left)) - Decimal(str(right)))
    except (InvalidOperation, ValueError):
        return None


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, default=list, sort_keys=True, separators=(",", ":"))


def _hash(rows: Iterable[Mapping[str, Any]]) -> str:
    return hashlib.sha256("".join(_json(row) + "\n" for row in rows).encode()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MechanicalQ4Error("mechanical Q4 companion manifest is invalid") from exc
    if not isinstance(value, dict):
        raise MechanicalQ4Error("mechanical Q4 companion manifest is invalid")
    return value
