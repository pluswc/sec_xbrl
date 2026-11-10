"""Publish board-only year-over-year comparisons from an immutable screening dataset."""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sec_xbrl.financial_source_compatibility import use_source_compatibility
from sec_xbrl.metrics.quarterly_screening import _decimal_string, _exact_subtract, _percentage
from sec_xbrl.metrics.screening import (
    canonical_json,
    regular_file,
    safe_new_destination,
    sha256_file,
)
from sec_xbrl.screening.dataset_v2 import open_screening_dataset
from sec_xbrl.screening.dataset_v3 import MANIFEST, ScreeningDatasetV3Reader

SCHEMA = "screening-financial-growth-v1"
RULE = "signed-prepared-financial-yoy-v1"
ARITHMETIC = "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
VIEW = "LATEST_REPORTED"
METRICS = ("operating_income", "cfo", "standardized_fcf")
BASIS_PREFIX = {"FY": "", "QTD_3M": "quarter_", "TTM": "ttm_"}
CASH_INPUTS = ("cfo", "capex")
MAX_BYTES = 16 * 1024 * 1024
MAX_COMPANY_BYTES = 512 * 1024
FORMULAS = {
    "ordinary_yoy": {"unit": "PERCENT", "expression": "(current / prior - 1) * 100",
                     "eligibility": "prior > 0 and current >= 0"},
    "negative_magnitude_change": {"unit": "PERCENT", "expression": "(abs(prior) - abs(current)) / abs(prior) * 100",
                                  "eligibility": "prior < 0 and current < 0"},
    "delta": {"unit": "USD", "expression": "current - prior", "eligibility": "compatible pair"},
}


def compare_amounts(current: Decimal, prior: Decimal) -> dict[str, str | None]:
    """Apply the approved sign policy once. A null percentage is intentional."""
    value = magnitude = None
    if prior == 0:
        status = "ZERO_UNCHANGED" if current == 0 else "ZERO_BASE"
    elif current == 0:
        status = "ZERO_REACHED"
        if prior > 0:
            value = "-100"
    elif prior > 0 and current > 0:
        status = "RATE_AVAILABLE"
        value = _decimal_string(_percentage(current, prior, subtract_one=True))
    elif prior < 0 and current < 0:
        before, after = prior.copy_abs(), current.copy_abs()
        status = ("NEGATIVE_MAGNITUDE_REDUCED" if after < before else
                  "NEGATIVE_MAGNITUDE_EXPANDED" if after > before else "NEGATIVE_MAGNITUDE_UNCHANGED")
        magnitude = _decimal_string(_percentage(_exact_subtract(before, after), before, subtract_one=False))
    else:
        status = "POSITIVE_TURN" if current > 0 else "NEGATIVE_TURN"
    return {"status": status, "yoy": value, "negative_magnitude_change": magnitude,
            "delta": _decimal_string(_exact_subtract(current, prior))}


def _id(row: dict) -> str | None:
    return row.get("metric_observation_id") or row.get("observation_id")


def _version(row: dict) -> str | None:
    return row.get("metric_definition_version") or row.get("definition_version")


def _fiscal_index(row: dict) -> int | None:
    year, quarter = row.get("fiscal_year"), row.get("fiscal_quarter")
    if type(year) is not int:
        return None
    if row.get("period_class") == "FY":
        return year * 4
    return year * 4 + int(quarter[1]) - 1 if quarter in ("Q1", "Q2", "Q3", "Q4") else None


def _dates(row: dict, basis: str) -> tuple[date, date] | None:
    if row.get("period_class") != basis or row.get("end_convention", "EXCLUSIVE" if basis == "FY" else None) != "EXCLUSIVE":
        return None
    try:
        start, end = (date.fromisoformat(row[field]) for field in ("period_start", "period_end"))
    except (TypeError, ValueError, KeyError):
        return None
    if (start.isoformat(), end.isoformat()) != (row["period_start"], row["period_end"]):
        return None
    duration = (end - start).days
    normal = 75 <= duration <= 105 if basis == "QTD_3M" else duration in (364, 365, 366, 371)
    return (start, end) if normal else None


def _amount(row: dict) -> Decimal | None:
    try:
        amount = Decimal(row["value"])
    except (TypeError, ValueError, InvalidOperation, KeyError):
        return None
    return amount if isinstance(row.get("value"), str) and amount.is_finite() else None


def _eligible(row: dict, cutoff: str) -> bool:
    annual = row.get("period_class") == "FY"
    view = row.get("view" if annual else "selection_view")
    as_of = row.get("financial_as_of" if annual else "selection_as_of_date")
    unit_ok = not annual or row.get("unit_semantics") == ['["iso4217:USD"]', '[]']
    return (row.get("availability_status") == "AVAILABLE" and row.get("unit") == "USD" and unit_ok
            and all(row.get(key) in (None, 0) for key in ("unit_scale", "scale"))
            and isinstance(row.get("dimensions"), list) and row.get("mapping_review_required") is False
            and row.get("quality_status") != "BLOCK" and not row.get("quality_blocking")
            and isinstance(_id(row), str) and bool(_id(row)) and isinstance(_version(row), str) and bool(_version(row))
            and view == VIEW and as_of == cutoff and _amount(row) is not None)


def _reported_signature(row: dict) -> tuple | None:
    """Bind an annual statement cell or the prepared quarterly meaning of a flow."""
    if row.get("period_class") == "FY":
        fields = ("semantic_identity", "concept_mapping_version", "raw_concept_qname",
                  "raw_concept_taxonomy_family", "raw_concept_data_type", "raw_concept_period_type")
        values = tuple(row.get(key) for key in fields)
        return values if row.get("source_kind") == "REPORTED" and all(isinstance(value, str) and value for value in values) else None
    lineage = row.get("source_lineage") or {}
    if row.get("source_kind") == "REPORTED":
        sources = [lineage]
    elif row.get("source_kind") == "DERIVED_QUARTER" and lineage.get("compatibility_policy") in {
            ARITHMETIC, "DECLARED_BASIS:" + str(row.get("basis_version"))}:
        sources = lineage.get("derivation_inputs") or []
        if len(sources) != 2:
            return None
    else:
        return None
    qnames = {item.get("raw_concept_qname") for item in sources}
    concept, mapping = row.get("company_canonical_concept_id"), row.get("canonical_mapping_version")
    if not (len(qnames) == 1 and None not in qnames and concept and mapping):
        return None
    if any(item.get("mapping_review_required") is not False
           or item.get("company_canonical_concept_id") != concept
           or item.get("quality_status") == "BLOCK" or item.get("quality_blocking") for item in sources):
        return None
    return (concept, mapping, next(iter(qnames)), row.get("structural_version"), row.get("recast_version"))


def _assurance(row: dict) -> str | None:
    basis = row.get("basis_version")
    if isinstance(basis, str) and basis:
        return "DECLARED_BASIS:" + basis
    if basis is not None:
        return None
    if row.get("period_class") == "FY":
        return ARITHMETIC if row.get("comparability_policy") == "REPORTED_VALUES_NOT_RECAST_VALIDATED" else None
    if row.get("source_kind") == "REPORTED":
        # Parent guarantees USD, canonical and source eligibility for reported QTD rows.
        return ARITHMETIC if _reported_signature(row) is not None else None
    return ARITHMETIC if (row.get("source_lineage") or {}).get("compatibility_policy") == ARITHMETIC else None


def _same_input_scope(row: dict, leg: dict) -> bool:
    return all(row.get(key) == leg.get(key) for key in ("cik", "unit", "dimensions", "basis_version"))


def _fcf_inputs(row: dict, annual_by_id: dict[str, dict]) -> list[dict]:
    if row.get("period_class") == "FY":
        refs = row.get("input_values") or []
        if len(refs) != 2 or row.get("input_observation_ids") != [ref.get("observation_id") for ref in refs]:
            return []
        inputs = [annual_by_id.get(ref["observation_id"]) for ref in refs]
        if any(leg is None or any(ref.get(key) != leg.get(key) for key in
                                  ("metric_id", "value", "fiscal_year", "period_class", "period_start", "period_end"))
               for ref, leg in zip(refs, inputs)):
            return []
        return inputs
    return (row.get("source_lineage") or {}).get("derivation_inputs") or []


def _level_signature(row: dict, cutoff: str, annual_by_id: dict[str, dict]) -> tuple | None:
    if not _eligible(row, cutoff) or _assurance(row) is None:
        return None
    if row["metric_id"] not in {"standardized_fcf", "quarter_standardized_fcf"}:
        return _reported_signature(row)
    inputs = _fcf_inputs(row, annual_by_id)
    basis = row["period_class"]
    prefix = BASIS_PREFIX[basis]
    if (row.get("source_kind") != "DERIVED_METRIC" or len(inputs) != 2
            or tuple(leg.get("metric_id") for leg in inputs) != tuple(prefix + name for name in CASH_INPUTS)
            or len({_id(leg) for leg in inputs}) != 2):
        return None
    for leg in inputs:
        if (not _same_input_scope(row, leg) or not _eligible(leg, cutoff) or _assurance(leg) != _assurance(row)
                or _dates(leg, basis) != _dates(row, basis) or _fiscal_index(leg) != _fiscal_index(row)):
            return None
    signatures = tuple(_reported_signature(leg) for leg in inputs)
    return tuple(zip((_version(leg) for leg in inputs), signatures)) if all(signatures) else None


def _ttm_legs(row: dict, cutoff: str, annual_by_id: dict[str, dict]) -> tuple[list[dict], tuple] | None:
    lineage = row.get("source_lineage") or {}
    legs = lineage.get("derivation_inputs") or []
    end = _fiscal_index(row)
    if (row.get("source_kind") != "DERIVED_METRIC" or not isinstance(lineage.get("derivation_rule_version"), str)
            or len(legs) != 4 or end is None or len({_id(leg) for leg in legs}) != 4):
        return None
    windows = [_dates(leg, "QTD_3M") for leg in legs]
    expected = "quarter_" + row["metric_id"].removeprefix("ttm_")
    if (any(window is None for window in windows) or any(
            leg.get("metric_id") != expected or not _same_input_scope(row, leg) or _assurance(leg) != _assurance(row)
            or _fiscal_index(leg) != end - 3 + index for index, leg in enumerate(legs))
            or any(left[1] != right[0] for left, right in pairwise(windows))
            or (windows[0][0], windows[-1][1]) != _dates(row, "TTM")
            or any(row.get(field) != legs[-1].get(field) for field in
                   ("company_canonical_concept_id", "canonical_mapping_version", "structural_version", "recast_version"))):
        return None
    signatures = [(_version(leg), _level_signature(leg, cutoff, annual_by_id)) for leg in legs]
    if any(signature is None or (version, signature) != signatures[0] for version, signature in signatures):
        return None
    return legs, signatures[0]


def _reference(row: dict | None) -> dict | None:
    if row is None or not _id(row):
        return None
    return {"observation_id": _id(row), "end_convention": "EXCLUSIVE",
            "value": row["value"] if _amount(row) is not None else None,
            **{key: row.get(key) for key in ("period_start", "period_end", "fiscal_year", "fiscal_quarter")}}


def compare_periods(current: dict, prior: dict | None, basis: str, cutoff: str,
                    annual_by_id: dict[str, dict], *, ambiguous: bool = False) -> dict:
    result = {"current": _reference(current), "prior": _reference(prior), "status": "UNAVAILABLE",
              "reason": None, "basis_assurance": None, "delta": None, "yoy": None,
              "negative_magnitude_change": None}
    if not _eligible(current, cutoff):
        return {**result, "reason": "CURRENT_UNAVAILABLE"}
    if ambiguous:
        return {**result, "reason": "AMBIGUOUS_FISCAL_PERIOD"}
    if prior is None:
        return {**result, "reason": "PRIOR_NOT_PREPARED"}
    if not _eligible(prior, cutoff):
        return {**result, "reason": "PRIOR_UNAVAILABLE"}
    assurance = _assurance(current)
    if (not _same_input_scope(current, prior) or _version(current) != _version(prior)
            or current.get("metric_id") != prior.get("metric_id")
            or assurance is None or _assurance(prior) != assurance):
        return {**result, "reason": "INCOMPATIBLE_SCOPE"}
    newer, older = _dates(current, basis), _dates(prior, basis)
    now, then = _fiscal_index(current), _fiscal_index(prior)
    if (newer is None or older is None or now is None or then is None or now - then != 4
            or older[1] > newer[0] or (basis in ("FY", "TTM") and older[1] != newer[0])
            or any(not 330 <= (a - b).days <= 400 for a, b in zip(newer, older))):
        return {**result, "reason": "INCOMPATIBLE_PERIOD"}
    if basis == "TTM":
        before, after = (_ttm_legs(row, cutoff, annual_by_id) for row in (prior, current))
        if (before is None or after is None or before[1] != after[1]
                or len({_id(leg) for leg in [*before[0], *after[0]]}) != 8
                or current["source_lineage"]["derivation_rule_version"] != prior["source_lineage"]["derivation_rule_version"]):
            return {**result, "reason": "INCOMPATIBLE_TTM_LINEAGE"}
        result["ttm_input_ids"] = {"current": [_id(row) for row in after[0]], "prior": [_id(row) for row in before[0]]}
    else:
        signature = _level_signature(current, cutoff, annual_by_id)
        if signature is None or _level_signature(prior, cutoff, annual_by_id) != signature:
            return {**result, "reason": "INCOMPATIBLE_SEMANTICS"}
    return {**result, **compare_amounts(_amount(current), _amount(prior)), "basis_assurance": assurance}


def build_artifact(parent: ScreeningDatasetV3Reader, manifest_sha256: str) -> dict[str, Any]:
    manifest = parent.manifest
    cutoff = manifest["financial_as_of"]
    companies = {company["cik"]: {} for company in parent.companies}
    definitions = {}
    annual_by_id = {row["metric_observation_id"]: row for row in parent.observations}
    for basis, prefix in BASIS_PREFIX.items():
        annual = basis == "FY"
        ids = {prefix + metric for metric in METRICS}
        catalog = parent.metric_definitions if annual else parent.quarter_definitions
        applicable = {row["metric_id"]: row for row in catalog if row["metric_id"] in ids}
        if set(applicable) != ids or any(row["unit_kind"] != "MONEY" or row["unit"] != "USD" for row in applicable.values()):
            raise ValueError(f"prepared {basis} financial growth inputs differ from the catalog")
        definitions.update({key: {"basis": basis, "definition_version": row["definition_version"], "formulas": FORMULAS}
                            for key, row in applicable.items()})
        source = parent.observations if annual else parent.quarter_observations
        rows = [row for row in source if row["metric_id"] in ids and row["period_class"] == basis]
        fiscal = defaultdict(list)
        for row in rows:
            coordinate = _fiscal_index(row)
            if coordinate is not None:
                fiscal[(row["cik"], row["metric_id"], coordinate)].append(row)
        for row in rows:
            cik, metric = row["cik"], row["metric_id"]
            if _version(row) != applicable[metric]["definition_version"]:
                raise ValueError("prepared input definition differs from its catalog")
            slot = str(row["fiscal_year"]) if annual else f"{row['calendar_year']}Q{row['calendar_quarter']}"
            output = companies[cik].setdefault(metric, {})
            if slot in output:
                raise ValueError("duplicate prepared display period")
            coordinate = _fiscal_index(row)
            previous = fiscal[(cik, metric, coordinate - 4)] if coordinate is not None else []
            ambiguous = coordinate is not None and (len(fiscal[(cik, metric, coordinate)]) != 1 or len(previous) > 1)
            output[slot] = compare_periods(row, previous[0] if len(previous) == 1 else None,
                                           basis, cutoff, annual_by_id, ambiguous=ambiguous)
    return {"schema_version": SCHEMA, "rule_version": RULE, "dataset_id": manifest["dataset_id"],
            "dataset_publication_id": parent.publication_id, "dataset_manifest_sha256": manifest_sha256,
            "financial_as_of": cutoff, "period_end_convention": "EXCLUSIVE",
            "definitions": definitions, "companies": companies}


def publish(manifest_path: Path, manifest_sha256: str, compatibility: dict[str, str], output: Path) -> str:
    source = regular_file(manifest_path, "financial growth parent manifest")
    destination = safe_new_destination(output, "financial growth artifact")
    if source.name != MANIFEST or sha256_file(source) != manifest_sha256:
        raise ValueError("financial growth parent manifest differs from its pin")
    with use_source_compatibility(compatibility):
        reader = open_screening_dataset(source.parent)
        if not isinstance(reader, ScreeningDatasetV3Reader):
            raise TypeError("financial growth requires a verified combined screening dataset")
        payload = {**build_artifact(reader, manifest_sha256), "source_compatibility_sha256": compatibility["sha256"]}
    if sha256_file(source) != manifest_sha256:
        raise ValueError("financial growth parent manifest changed while preparing")
    if any(len(canonical_json(company).encode()) > MAX_COMPANY_BYTES - 8192 for company in payload["companies"].values()):
        raise ValueError("financial growth company exceeds response limit")
    data = (canonical_json(payload) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("financial growth artifact exceeds size limit")
    # Stage bytes in the same directory, then link without overwriting any destination.
    with NamedTemporaryFile(dir=destination.parent) as staging:
        staging.write(data)
        staging.flush()
        os.link(staging.name, destination)
    return sha256_file(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--dataset-manifest-sha256", required=True)
    parser.add_argument("--source-compatibility", nargs=2, metavar=("PATH", "SHA256"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path, sha256 = args.source_compatibility
    print(publish(args.dataset_manifest, args.dataset_manifest_sha256, {"path": path, "sha256": sha256}, args.output))


if __name__ == "__main__":
    main()
