"""Synthetic contract controls for formula-free governed quarterly metric consumption."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader

WIRE = Path(__file__).parents[1] / "fixtures" / "screening_quarterly_wire_v5"
POLICY = "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
KINDS = {
    "fcf": "SAME_PERIOD_DIFFERENCE",
    "margin": "SAME_PERIOD_RATIO",
    "instant_ratio": "SAME_PERIOD_RATIO",
    "qoq": "ADJACENT_FISCAL_QUARTER_GROWTH",
    "yoy": "SAME_FISCAL_QUARTER_YOY_GROWTH",
}
QNAMES = {
    "quarter_revenue": "us-gaap:Revenues",
    "quarter_gross_profit": "us-gaap:GrossProfit",
    "quarter_capex": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    "quarter_current_assets": "us-gaap:AssetsCurrent",
    "quarter_current_liabilities": "us-gaap:LiabilitiesCurrent",
}


def _reported(
    prototype: dict[str, Any],
    metric: str,
    value: str,
    *,
    instant: bool = False,
    prior_year: bool = False,
) -> dict[str, Any]:
    row = copy.deepcopy(prototype)
    row.update(metric_id=metric, canonical_metric_id=metric, value=value, basis_version=None)
    if prior_year:
        for key in ("period_start", "period_end", "filed_date", "report_date"):
            old = date.fromisoformat(row[key])
            row[key] = old.replace(year=old.year - 1).isoformat()
        row["fiscal_year"] -= 1
        row["calendar_year"] -= 1
    if instant:
        row.update(period_start=None, period_class="INSTANT", observation_basis="INSTANT")
    key = f"synthetic-generic:{metric}:{row['period_end']}"
    source = row["source_lineage"]
    source.update(
        canonical_metric_id=metric,
        value=value,
        basis_version=None,
        source_id=key + ":source",
        source_fact_id=key + ":fact",
        context_id=key + ":context",
        raw_concept_qname=QNAMES[metric],
        company_canonical_concept_id=f"synthetic-company:{metric}",
        selected_source_ids=[key + ":source"],
        candidate_source_ids=[key + ":source"],
    )
    for field in ("period_start", "period_end", "period_class", "filed_date", "report_date"):
        source[field] = row[field]
    if prior_year:
        source["accession"] = "0000000001-24-000002"
        source["source_filing_id"] = "synthetic-filing:" + source["accession"]
    source["duration_days"] = (
        None
        if instant
        else (date.fromisoformat(row["period_end"]) - date.fromisoformat(row["period_start"])).days
    )
    if instant:
        source["context_instant_date"] = row["period_end"]
    row["observation_id"] = key + ":observation"
    return row


def _documents(case: str) -> dict[str, Any]:
    docs = {path.name: json.loads(path.read_text()) for path in WIRE.glob("*.json")}
    rows = docs["quarter_metric_observations.json"]["records"]
    definitions = docs["quarter_metric_definitions.json"]["records"]
    current = next(
        row
        for row in rows
        if row["metric_id"] == "quarter_revenue"
        and row["cik"] == "0000000001"
        and (row["calendar_year"], row["calendar_quarter"]) == (2025, 2)
    )
    revenue = _reported(current, "quarter_revenue", "120000000")
    if case == "fcf":
        left = copy.deepcopy(next(row for row in rows if row["source_kind"] == "DERIVED_QUARTER"))
        left.update(basis_version=None, derived_metric_id="synthetic-generic:cfo:derived")
        for source in left["source_lineage"]["derivation_inputs"]:
            source["basis_version"] = None
        right = _reported(current, "quarter_capex", "3000000")
        roles, constraints = ("CFO", "CAPEX"), ("FINITE", "NONNEGATIVE")
    elif case == "margin":
        left, right = _reported(current, "quarter_gross_profit", "-5000000"), revenue
        roles, constraints = ("NUMERATOR", "DENOMINATOR"), ("FINITE", "POSITIVE")
    elif case == "instant_ratio":
        left = _reported(current, "quarter_current_assets", "30000000", instant=True)
        right = _reported(current, "quarter_current_liabilities", "20000000", instant=True)
        roles, constraints = ("NUMERATOR", "DENOMINATOR"), ("NONNEGATIVE", "POSITIVE")
    else:
        left = revenue
        if case == "qoq":
            previous = next(
                row
                for row in rows
                if row["metric_id"] == "quarter_revenue"
                and row["cik"] == "0000000001"
                and (row["calendar_year"], row["calendar_quarter"]) == (2025, 1)
            )
            right = _reported(previous, "quarter_revenue", "100000000")
        else:
            right = _reported(current, "quarter_revenue", "100000000", prior_year=True)
        roles, constraints = ("CURRENT", "PRIOR"), ("NONNEGATIVE", "POSITIVE")
    for item in (left, right):
        definition = next((d for d in definitions if d["metric_id"] == item["metric_id"]), None)
        if definition is None:
            definition = copy.deepcopy(definitions[0])
            definition.update(metric_id=item["metric_id"], observation_basis=item["period_class"])
            definitions.append(definition)
        item["definition_version"] = definition["definition_version"]
    output = copy.deepcopy(left)
    output.update(
        metric_id="quarter_synthetic_" + case,
        canonical_metric_id="quarter_synthetic_" + case,
        observation_id="synthetic-generic-output:" + case,
        definition_version="synthetic-quarter-derived-v1",
        source_kind="DERIVED_METRIC",
        value="777.12345678901234567890123456789",
        unit="USD" if case == "fcf" else "PERCENT",
        filed_date=max(left["filed_date"], right["filed_date"]),
    )
    contract = {
        "version": "quarter-derived-input-scope-v1",
        "kind": KINDS[case],
        "basis_policy": POLICY,
        "denominator_policy": "NOT_APPLICABLE" if case == "fcf" else "STRICTLY_POSITIVE",
        "inputs": [
            {"input_role": role, "metric_id": item["metric_id"], "value_constraint": constraint}
            for role, item, constraint in zip(roles, (left, right), constraints, strict=True)
        ],
    }
    definition = {
        "metric_id": output["metric_id"],
        "definition_version": output["definition_version"],
        "unit": output["unit"],
        "unit_kind": "MONEY" if case == "fcf" else "PERCENT",
        "canonical_value_scale": "1",
        "observation_basis": left["period_class"],
        "allowed_source_kinds": ["DERIVED_METRIC"],
        "rule_version": "synthetic-quarter-derived-rule-v1",
        "input_contract": contract,
        "formula": "SYNTHETIC_PRODUCER_RESULT_ONLY",
        "status": "ACTIVE",
    }
    definitions.append(definition)
    output["source_lineage"] = {
        "compatibility_policy": POLICY,
        "derivation_rule_version": definition["rule_version"],
        "derivation_inputs": [
            dict(item, input_role=role) for item, role in zip((left, right), roles, strict=True)
        ],
    }
    # Fill every declared metric/company/bucket coordinate, keeping older YoY inputs nested only.
    index = {(r["cik"], r["metric_id"], r["calendar_year"], r["calendar_quarter"]): r for r in rows}
    manifest = docs["quarterly_screening_metric_manifest.json"]
    for definition in definitions:
        for cik in manifest["universe"]["ciks"]:
            for bucket in manifest["global_quarter_spine"]:
                key = (
                    cik,
                    definition["metric_id"],
                    bucket["calendar_year"],
                    bucket["calendar_quarter"],
                )
                if key not in index:
                    gap = copy.deepcopy(
                        next(
                            r
                            for r in rows
                            if r["metric_id"] == "quarter_gross_profit"
                            and (r["cik"], r["calendar_year"], r["calendar_quarter"])
                            == (key[0], key[2], key[3])
                        )
                    )
                    gap.update(
                        metric_id=key[1],
                        canonical_metric_id=key[1],
                        observation_id=f"synthetic-gap:{key}",
                        definition_version=definition["definition_version"],
                        unit=definition["unit"],
                        period_class=definition["observation_basis"],
                        observation_basis=definition["observation_basis"],
                    )
                    index[key] = gap
    for item in (left, right, output):
        key = (item["cik"], item["metric_id"], item["calendar_year"], item["calendar_quarter"])
        if key in index:
            index[key] = copy.deepcopy(item)
    docs["quarter_metric_observations.json"]["records"] = list(index.values())
    return docs


def _target(docs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    row = next(
        row
        for row in docs["quarter_metric_observations.json"]["records"]
        if row["metric_id"].startswith("quarter_synthetic_")
        and row["availability_status"] == "AVAILABLE"
    )
    definition = next(
        d
        for d in docs["quarter_metric_definitions.json"]["records"]
        if d["metric_id"] == row["metric_id"]
    )
    return row, definition


def _publish(tmp_path: Path, docs: dict[str, Any]) -> Path:
    root = tmp_path / "publication"
    shutil.copytree(WIRE, root)
    manifest = docs["quarterly_screening_metric_manifest.json"]
    rows = docs["quarter_metric_observations.json"]["records"]
    support = []
    for definition in docs["quarter_metric_definitions.json"]["records"]:
        for cik in manifest["universe"]["ciks"]:
            selected = [
                row
                for row in rows
                if (row["cik"], row["metric_id"]) == (cik, definition["metric_id"])
            ]
            count = sum(row["availability_status"] == "AVAILABLE" for row in selected)
            support.append(
                {
                    "cik": cik,
                    "metric_id": definition["metric_id"],
                    "fixed_bucket_count": 8,
                    "available_bucket_count": count,
                    "unavailable_bucket_count": 8 - count,
                    "source_kind_counts": dict(Counter(row["source_kind"] for row in selected)),
                    "unavailable_reason_counts": dict(
                        Counter(row["reason"] for row in selected if row.get("reason"))
                    ),
                }
            )
    docs["quarter_metric_support.json"]["records"] = support
    manifest["fixture_kind"] = "SYNTHETIC_GENERIC_QUARTER_CONTRACT_TEST"
    manifest["publication_id"] = "synthetic-generic-quarter-contract-test"
    names = {
        "quarter_metric_definitions.json": "definitions",
        "quarter_metric_support.json": "support",
        "quarter_metric_observations.json": "observations",
        "quarter_period_inventory.json": "period_inventory",
    }
    for name, count_key in names.items():
        docs[name]["fixture_kind"] = manifest["fixture_kind"]
        data = (json.dumps(docs[name], indent=2) + "\n").encode()
        (root / name).write_bytes(data)
        count = len(docs[name]["records"])
        manifest["files"][name].update(
            sha256=hashlib.sha256(data).hexdigest(), size=len(data), record_count=count
        )
        manifest["counts"][count_key] = count
    data = (json.dumps(manifest, indent=2) + "\n").encode()
    (root / "quarterly_screening_metric_manifest.json").write_bytes(data)
    (root / "MANIFEST.sha256").write_text(
        hashlib.sha256(data).hexdigest() + "  quarterly_screening_metric_manifest.json\n"
    )
    return root


@pytest.mark.parametrize("case", KINDS)
def test_generic_prepared_metric_preserves_arbitrary_producer_result_without_math(
    tmp_path: Path, case: str
):
    docs = _documents(case)
    expected = copy.deepcopy(_target(docs)[0])
    reader = QuarterlyScreeningMetricReader(_publish(tmp_path, docs))
    actual = next(
        row for row in reader.observations if row["observation_id"] == expected["observation_id"]
    )
    assert actual == expected
    assert actual["value"] == "777.12345678901234567890123456789"
    assert actual["source_lineage"]["compatibility_policy"] == POLICY


def _source_nodes(item: dict[str, Any]) -> list[dict[str, Any]]:
    lineage = item["source_lineage"]
    return [item, lineage, *lineage.get("derivation_inputs", [])]


def _coherent_input_field(item: dict[str, Any], field: str, value: Any) -> None:
    for node in _source_nodes(item):
        if field in node:
            node[field] = value


def _sync_top_inputs(docs: dict[str, Any]) -> None:
    row, _ = _target(docs)
    inputs = {item["observation_id"]: item for item in row["source_lineage"]["derivation_inputs"]}
    rows = docs["quarter_metric_observations.json"]["records"]
    for index, item in enumerate(rows):
        if item["observation_id"] in inputs:
            rows[index] = {
                key: copy.deepcopy(value)
                for key, value in inputs[item["observation_id"]].items()
                if key != "input_role"
            }


@pytest.mark.parametrize("case", KINDS)
def test_generic_nonnull_equal_basis_remains_explicit(tmp_path: Path, case: str):
    docs = _documents(case)
    row, _ = _target(docs)
    row["basis_version"] = "synthetic-reviewed-basis-v1"
    for item in row["source_lineage"]["derivation_inputs"]:
        _coherent_input_field(item, "basis_version", row["basis_version"])
    _sync_top_inputs(docs)
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize(
    "case,mutation",
    [
        ("margin", "version"),
        ("margin", "kind"),
        ("margin", "extra_contract"),
        ("margin", "missing_role"),
        ("margin", "duplicate_role"),
        ("margin", "input_count"),
        ("margin", "contract_metric"),
        ("margin", "constraint_missing"),
        ("margin", "constraint_relaxed"),
        ("margin", "denominator_policy"),
        ("fcf", "denominator_policy"),
        ("margin", "basis_policy"),
        ("margin", "lineage_policy"),
        ("margin", "rule"),
        ("margin", "cik"),
        ("margin", "dimensions"),
        ("margin", "unit"),
        ("margin", "view"),
        ("margin", "asof"),
        ("margin", "basis"),
        ("margin", "raw_recast_version"),
        ("margin", "period"),
        ("margin", "ytd"),
        ("margin", "fy"),
        ("margin", "quality"),
        ("margin", "raw_quality"),
        ("margin", "mapping_review"),
        ("margin", "continuity"),
        ("margin", "recast_review"),
        ("margin", "quality_missing"),
        ("margin", "fiscal_quarter"),
        ("margin", "fiscal_year"),
        ("margin", "filed"),
        ("margin", "report"),
        ("margin", "future_input"),
        ("margin", "output_unit"),
        ("margin", "generic_nested"),
        ("margin", "self_cycle"),
        ("margin", "ttm_fallback"),
        ("margin", "missing_input"),
        ("margin", "duplicate_input"),
        ("fcf", "derived_identity"),
        ("qoq", "prior_quarter"),
        ("qoq", "prior_year"),
        ("qoq", "gap"),
        ("yoy", "prior_quarter"),
        ("yoy", "prior_year"),
        ("qoq", "semantic_binding"),
        ("yoy", "semantic_binding_missing"),
        ("instant_ratio", "instant_start"),
        ("instant_ratio", "instant_duration"),
        ("instant_ratio", "instant_context"),
    ],
)
def test_generic_metric_rejects_ineligible_declared_inputs(
    tmp_path: Path, case: str, mutation: str
):
    docs = _documents(case)
    row, definition = _target(docs)
    contract = definition["input_contract"]
    inputs = row["source_lineage"]["derivation_inputs"]
    # New synthetic prepared identities isolate semantic probes from the separate copy-identity gate.
    for item in inputs:
        item["observation_id"] += ":scope-probe"
    first, second = inputs
    if mutation == "version":
        contract["version"] = "unsupported-v99"
    elif mutation == "kind":
        contract["kind"] = "SUM_ANYTHING"
    elif mutation == "extra_contract":
        contract["recast_clearance"] = True
    elif mutation == "missing_role":
        first.pop("input_role")
    elif mutation == "duplicate_role":
        second["input_role"] = first["input_role"]
    elif mutation == "input_count":
        inputs.pop()
    elif mutation == "contract_metric":
        contract["inputs"][0]["metric_id"] = "quarter_cfo"
    elif mutation == "constraint_missing":
        contract["inputs"][0].pop("value_constraint")
    elif mutation == "constraint_relaxed":
        contract["inputs"][1]["value_constraint"] = "FINITE"
    elif mutation == "denominator_policy":
        contract["denominator_policy"] = "ANY_FINITE"
    elif mutation == "basis_policy":
        contract.pop("basis_policy")
    elif mutation == "lineage_policy":
        row["source_lineage"]["compatibility_policy"] = "RECAST_CLEARED"
    elif mutation == "rule":
        row["source_lineage"]["derivation_rule_version"] = "other-rule"
    elif mutation == "cik":
        _coherent_input_field(second, "cik", "0000000002")
    elif mutation == "dimensions":
        _coherent_input_field(second, "dimensions", [{"axis": "geo", "member": "US"}])
    elif mutation == "unit":
        _coherent_input_field(second, "unit", "EUR")
    elif mutation == "view":
        _coherent_input_field(second, "selection_view", "AS_FILED")
    elif mutation == "asof":
        _coherent_input_field(second, "selection_as_of_date", "2026-10-09")
    elif mutation == "basis":
        _coherent_input_field(second, "basis_version", "other-basis")
    elif mutation == "raw_recast_version":
        second["source_lineage"]["recast_version"] = "other-recast"
    elif mutation in {"period", "gap"}:
        date_field = "period_end" if mutation == "gap" else "period_start"
        changed = (date.fromisoformat(second[date_field]) - timedelta(days=1)).isoformat()
        _coherent_input_field(second, date_field, changed)
        anchor = second["source_lineage"]
        anchor["duration_days"] = (
            date.fromisoformat(anchor["period_end"]) - date.fromisoformat(anchor["period_start"])
        ).days
    elif mutation in {"ytd", "fy"}:
        _coherent_input_field(second, "period_class", "YTD_6M" if mutation == "ytd" else "FY")
    elif mutation == "quality":
        _coherent_input_field(second, "quality_blocking", True)
    elif mutation == "raw_quality":
        second["source_lineage"]["quality_status"] = "BLOCK"
    elif mutation == "mapping_review":
        second["source_lineage"]["mapping_review_required"] = True
    elif mutation == "continuity":
        second["source_lineage"]["continuity_break"] = True
    elif mutation == "recast_review":
        second["source_lineage"]["recast_review_required"] = True
    elif mutation == "quality_missing":
        second.pop("quality_status")
    elif mutation in {"fiscal_quarter", "prior_quarter"}:
        second["fiscal_quarter"] = "Q4"
    elif mutation in {"fiscal_year", "prior_year"}:
        second["fiscal_year"] -= 2
    elif mutation == "filed":
        row["filed_date"] = "2025-08-02"
    elif mutation == "report":
        row["report_date"] = "2025-06-29"
    elif mutation == "future_input":
        _coherent_input_field(second, "filed_date", "2099-01-01")
    elif mutation == "output_unit":
        row["unit"] = "USD"
    elif mutation == "generic_nested":
        first["source_kind"] = "DERIVED_METRIC"
    elif mutation == "self_cycle":
        first["observation_id"] = row["observation_id"]
    elif mutation == "ttm_fallback":
        definition["observation_basis"] = "TTM"
        row.update(period_class="TTM", basis_version="basis")
    elif mutation == "missing_input":
        first.update(availability_status="UNAVAILABLE", value=None, reason="MISSING_INPUT")
    elif mutation == "duplicate_input":
        second["observation_id"] = first["observation_id"]
    elif mutation == "derived_identity":
        first.pop("derived_metric_id")
    elif mutation == "semantic_binding":
        second["source_lineage"]["company_canonical_concept_id"] = "different-company-concept"
    elif mutation == "semantic_binding_missing":
        second["source_lineage"].pop("company_canonical_concept_id")
    elif mutation == "instant_start":
        _coherent_input_field(second, "period_start", "2025-04-01")
    elif mutation == "instant_duration":
        second["source_lineage"]["duration_days"] = 0
    elif mutation == "instant_context":
        second["source_lineage"]["context_instant_date"] = "2025-06-30"
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize(
    "case,index,value",
    [
        ("fcf", 1, "-1"),
        ("margin", 1, "0"),
        ("margin", 1, "-1"),
        ("instant_ratio", 0, "-1"),
        ("instant_ratio", 1, "0"),
        ("qoq", 0, "-1"),
        ("qoq", 1, "0"),
        ("yoy", 0, "-1"),
        ("yoy", 1, "-1"),
    ],
)
def test_existing_r1_sign_constraints_are_enforced_without_calculation(
    tmp_path: Path, case, index, value
):
    docs = _documents(case)
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][index]
    _coherent_input_field(item, "value", value)
    _sync_top_inputs(docs)
    with pytest.raises(ValueError, match="value constraint"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_same_prepared_observation_id_cannot_carry_a_different_value(tmp_path: Path):
    docs = _documents("margin")
    row, _ = _target(docs)
    _coherent_input_field(row["source_lineage"]["derivation_inputs"][0], "value", "42")
    with pytest.raises(ValueError, match="identity has contradictory content"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_yoy_uses_issuer_fiscal_coordinate_even_when_calendar_bucket_differs(tmp_path: Path):
    docs = _documents("yoy")
    row, _ = _target(docs)
    prior = row["source_lineage"]["derivation_inputs"][1]
    for field, value in {
        "period_start": "2024-05-01",
        "period_end": "2024-08-01",
        "filed_date": "2024-09-01",
        "report_date": "2024-07-31",
    }.items():
        _coherent_input_field(prior, field, value)
    prior["calendar_quarter"] = 3
    prior["source_lineage"]["duration_days"] = 92
    reader = QuarterlyScreeningMetricReader(_publish(tmp_path, docs))
    published = next(
        item for item in reader.observations if item["observation_id"] == row["observation_id"]
    )
    assert published["calendar_quarter"] == 2
    assert published["source_lineage"]["derivation_inputs"][1]["calendar_quarter"] == 3
    assert len(reader.period_inventory) == 16
    assert all(
        item["calendar_year"] != 2024 or item["calendar_quarter"] == 4
        for item in reader.period_inventory
    )


def test_qoq_fiscal_year_rollover_is_independent_of_calendar_quarter(tmp_path: Path):
    docs = _documents("qoq")
    row, _ = _target(docs)
    current, prior = row["source_lineage"]["derivation_inputs"]
    current.update(fiscal_year=2026, fiscal_quarter="Q1")
    prior.update(fiscal_year=2025, fiscal_quarter="Q4")
    row.update(fiscal_year=2026, fiscal_quarter="Q1")
    _sync_top_inputs(docs)
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_unavailable_generic_metric_keeps_missing_input_reason_and_candidates(tmp_path: Path):
    docs = _documents("margin")
    row, _ = _target(docs)
    row.update(
        availability_status="UNAVAILABLE",
        value=None,
        reason="MISSING_INPUT",
        reasons=["MISSING_INPUT"],
    )
    row["source_lineage"]["derivation_inputs"] = []
    row["source_lineage"]["candidate_evidence"] = [
        {"source_fact_id": None, "mapping_review_required": True}
    ]
    expected = copy.deepcopy(row)
    reader = QuarterlyScreeningMetricReader(_publish(tmp_path, docs))
    assert (
        next(
            item
            for item in reader.observations
            if item["observation_id"] == expected["observation_id"]
        )
        == expected
    )


@pytest.mark.parametrize(
    "case,index,value", [("fcf", 0, "-5"), ("fcf", 1, "0"), ("qoq", 0, "0"), ("yoy", 0, "0")]
)
def test_permitted_r1_sign_boundaries_preserve_producer_result(tmp_path: Path, case, index, value):
    docs = _documents(case)
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][index]
    item["value"] = value
    if item["source_kind"] == "REPORTED":
        item["source_lineage"]["value"] = value
    _sync_top_inputs(docs)
    reader = QuarterlyScreeningMetricReader(_publish(tmp_path, docs))
    assert (
        next(r for r in reader.observations if r["observation_id"] == row["observation_id"])[
            "value"
        ]
        == row["value"]
    )


def test_instant_ratio_uses_exact_dimensionless_definition_unit(tmp_path: Path):
    docs = _documents("instant_ratio")
    row, definition = _target(docs)
    definition.update(unit="RATIO", unit_kind="RATIO")
    for item in docs["quarter_metric_observations.json"]["records"]:
        if item["metric_id"] == row["metric_id"]:
            item["unit"] = "RATIO"
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_coherent_unsupported_112_day_qtd_is_not_a_generic_input(tmp_path: Path):
    docs = _documents("yoy")
    row, _ = _target(docs)
    prior = row["source_lineage"]["derivation_inputs"][1]
    _coherent_input_field(prior, "period_start", "2024-03-11")
    prior["source_lineage"]["duration_days"] = 112
    with pytest.raises(ValueError, match="eligible QTD duration"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize(
    "field,value",
    [
        ("dimensions", [{"axis": "synthetic-axis", "member": "synthetic-member"}]),
        ("comparability_status", "NOT_COMPARABLE"),
    ],
)
def test_same_prepared_id_cannot_change_scope_or_metadata(tmp_path: Path, field, value):
    docs = _documents("margin")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    _coherent_input_field(item, field, value)
    item[field] = value
    with pytest.raises(ValueError, match="identity has contradictory content"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_nonnull_prepared_basis_declaration_is_not_empty(tmp_path: Path):
    field, value = "basis_version", ""
    docs = _documents("margin")
    row, _ = _target(docs)
    row[field] = value
    for item in row["source_lineage"]["derivation_inputs"]:
        for scope in _source_nodes(item):
            scope[field] = value
    _sync_top_inputs(docs)
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize("case", ["margin", "instant_ratio", "qoq", "yoy", "fcf"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "USD_INVALID"),
        ("canonical_value_scale", None),
        ("canonical_value_scale", 1),
        ("canonical_value_scale", "100"),
    ],
)
def test_generic_output_requires_typed_unit_and_explicit_canonical_scale(
    tmp_path: Path, case, field, value
):
    docs = _documents(case)
    row, definition = _target(docs)
    definition[field] = value
    if field == "unit":
        definition[field] = "PERCENT" if case == "fcf" else "USD"
        for item in docs["quarter_metric_observations.json"]["records"]:
            if item["metric_id"] == row["metric_id"]:
                item["unit"] = definition[field]
    with pytest.raises(ValueError, match="unit or canonical value scale"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize("unit", ["RATIO", "1"])
def test_explicit_same_period_ratio_contract_permits_dimensionless_unit(tmp_path: Path, unit):
    docs = _documents("instant_ratio")
    row, definition = _target(docs)
    definition.update(unit_kind="RATIO", unit=unit)
    for item in docs["quarter_metric_observations.json"]["records"]:
        if item["metric_id"] == row["metric_id"]:
            item["unit"] = unit
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize("case", ["margin", "qoq"])
@pytest.mark.parametrize("identity_change", ["prepared_only", "source_alias", "fact_alias"])
def test_new_prepared_id_cannot_change_elected_immutable_raw_amount(
    tmp_path: Path, case, identity_change
):
    docs = _documents(case)
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    item["observation_id"] += ":new-prepared"
    _coherent_input_field(item, "value", "42")
    source = item["source_lineage"]
    if identity_change == "source_alias":
        source["source_id"] += ":new-source-alias"
        source["selected_source_ids"] = [source["source_id"]]
    elif identity_change == "fact_alias":
        source["source_fact_id"] += ":new-fact-alias"
    with pytest.raises(ValueError, match="raw source identity has contradictory content"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_id", "different-context"),
        ("raw_concept_qname", "us-gaap:OperatingIncomeLoss"),
        ("raw_concept_namespace_uri", "http://example.invalid/other"),
        ("unit_id", "different-unit-id"),
        ("source_file_id", "different-origin-file"),
        ("source_filing_id", "different-origin-filing"),
    ],
)
def test_new_prepared_id_cannot_change_raw_intrinsic_origin(tmp_path: Path, field, value):
    docs = _documents("margin")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    item["observation_id"] += ":new-prepared"
    item["source_lineage"][field] = value
    with pytest.raises(ValueError, match="raw source identity has contradictory content"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_identical_raw_fact_can_have_distinct_prepared_views_and_quality_metadata(tmp_path: Path):
    docs = _documents("margin")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    original = next(
        r
        for r in docs["quarter_metric_observations.json"]["records"]
        if r["observation_id"] == item["observation_id"]
    )
    _coherent_input_field(original, "selection_view", "AS_FILED")
    original["quality_reasons"] = ["SYNTHETIC_NONBLOCKING_REVIEW"]
    original["source_lineage"]["quality_reasons"] = ["SYNTHETIC_NONBLOCKING_REVIEW"]
    item["observation_id"] += ":another-governed-view"
    _coherent_input_field(item, "value", "-5000000.0000000000000000000000")
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_fact_id_is_qualified_by_source_file_when_source_aliases_are_distinct(tmp_path: Path):
    docs = _documents("margin")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    original = next(
        r
        for r in docs["quarter_metric_observations.json"]["records"]
        if r["observation_id"] == item["observation_id"]
    )
    original["source_lineage"]["source_file_id"] = "synthetic-file-A"
    item["observation_id"] += ":distinct-raw-file"
    source = item["source_lineage"]
    source["source_file_id"] = "synthetic-file-B"
    source["source_id"] += ":distinct-raw-file"
    source["selected_source_ids"] = [source["source_id"]]
    _coherent_input_field(item, "value", "42")
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_generic_m8_nested_raw_cannot_change_under_new_prepared_id(tmp_path: Path):
    docs = _documents("fcf")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    item["observation_id"] += ":different-m8-prepared"
    item["source_lineage"]["derivation_inputs"][0]["value"] = "42"
    with pytest.raises(ValueError, match="raw source identity has contradictory content"):
        QuarterlyScreeningMetricReader(_publish(tmp_path, docs))


def test_candidate_evidence_does_not_register_an_elected_raw_identity(tmp_path: Path):
    docs = _documents("margin")
    row, _ = _target(docs)
    item = row["source_lineage"]["derivation_inputs"][0]
    candidate = copy.deepcopy(item["source_lineage"])
    candidate["value"] = "42"
    row["source_lineage"]["candidate_evidence"] = [candidate]
    QuarterlyScreeningMetricReader(_publish(tmp_path, docs))
