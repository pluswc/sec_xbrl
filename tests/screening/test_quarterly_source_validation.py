"""Rehashed publications must still satisfy declared source and input semantics."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sec_xbrl.screening.quarterly import QuarterlyScreeningMetricReader

WIRE = Path(__file__).parents[1] / "fixtures" / "screening_quarterly_wire_v5"


def _publication(tmp_path: Path, mutate: Callable[[list[dict[str, Any]]], None]) -> Path:
    root = tmp_path / "wire"
    shutil.copytree(WIRE, root)
    manifest_path = root / "quarterly_screening_metric_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    observations = json.loads((root / "quarter_metric_observations.json").read_text())
    support = json.loads((root / "quarter_metric_support.json").read_text())
    mutate(observations["records"])
    for item in support["records"]:
        rows = [
            r
            for r in observations["records"]
            if (r["cik"], r["metric_id"]) == (item["cik"], item["metric_id"])
        ]
        count = sum(r["availability_status"] == "AVAILABLE" for r in rows)
        item.update(
            available_bucket_count=count,
            unavailable_bucket_count=8 - count,
            source_kind_counts=dict(Counter(r["source_kind"] for r in rows)),
            unavailable_reason_counts=dict(Counter(r["reason"] for r in rows if r.get("reason"))),
        )
    definitions = json.loads((root / "quarter_metric_definitions.json").read_text())
    for definition in definitions["records"]:
        if definition["metric_id"] == "ttm_revenue":
            definition["input_metric_id"] = "quarter_revenue"
    for name, payload in (
        ("quarter_metric_observations.json", observations),
        ("quarter_metric_support.json", support),
        ("quarter_metric_definitions.json", definitions),
    ):
        data = (json.dumps(payload, indent=2) + "\n").encode()
        (root / name).write_bytes(data)
        manifest["files"][name].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return root


@pytest.mark.parametrize(
    "field",
    [
        "source_fact_id",
        "context_id",
        "raw_concept_qname",
        "raw_concept_namespace_uri",
        "unit",
        "source_id",
        "source_filing_id",
        "canonical_metric_id",
    ],
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_reported_source_requires_meaningful_identity(tmp_path: Path, field: str, value: Any):
    root = _publication(tmp_path, lambda rs: rs[0]["source_lineage"].update({field: value}))
    with pytest.raises(ValueError, match="source"):
        QuarterlyScreeningMetricReader(root)


@pytest.mark.parametrize(
    "change",
    [
        {"cik": "0000000002"},
        {"cik": None},
        {"unit": "EUR"},
        {"canonical_metric_id": "quarter_cfo"},
        {"dimensions": [{"axis": "geo", "member": "Europe"}]},
        {"selection_as_of_date": "2099-01-01"},
        {"selection_view": "UNREVIEWED_OTHER_VIEW"},
        {"basis_version": "other-basis"},
        {"selected_source_ids": ["other-source"]},
    ],
)
def test_reported_source_scope_must_match_observation(tmp_path: Path, change: dict[str, Any]):
    root = _publication(tmp_path, lambda rs: rs[0]["source_lineage"].update(change))
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(root)


@pytest.mark.parametrize(
    "field,value",
    [
        ("period_start", "2024-01-01"),
        ("period_end", "2024-12-31"),
        ("report_date", "2024-12-30"),
        ("filed_date", "2025-02-02"),
    ],
)
def test_reported_actual_dates_are_bound_to_source(tmp_path: Path, field: str, value: str):
    root = _publication(tmp_path, lambda rs: rs[0].update({field: value}))
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(root)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_consistently_future_source_filing_rejects(tmp_path: Path):
    def mutate(rows):
        accession = rows[0]["source_lineage"]["accession"]
        for row in rows:
            for anchor in _walk(row["source_lineage"]):
                if anchor.get("accession") == accession:
                    anchor["filed_date"] = "2099-01-01"

    with pytest.raises(ValueError, match="cutoff"):
        QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


def _available_ttm(rows):
    row = next(
        r for r in rows if r["metric_id"] == "ttm_revenue" and r["source_kind"] == "DERIVED_METRIC"
    )
    row.update(
        availability_status="AVAILABLE",
        value="580000000",
        reason=None,
        reasons=[],
        basis_version="synthetic-basis-v1",
    )
    row["source_lineage"].pop("compatibility_failure", None)
    for anchor in row["source_lineage"]["derivation_inputs"]:
        anchor["basis_version"] = row["basis_version"]
    return row


def test_declared_compatible_four_quarter_ttm_is_accepted_without_arithmetic(tmp_path: Path):
    def mutate(rows):
        row = _available_ttm(rows)
        # This reader validates lineage/scope, not a producer's monetary calculation.
        row["value"] = "0.0000000000000000000001"

    reader = QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))
    assert next(
        r
        for r in reader.observations
        if r["metric_id"] == "ttm_revenue" and r["availability_status"] == "AVAILABLE"
    )["value"].endswith("1")


@pytest.mark.parametrize(
    "case",
    [
        "three",
        "five",
        "null_basis",
        "other_basis",
        "failure",
        "gap",
        "overlap",
        "reverse",
        "fy",
        "unit",
        "metric",
        "dimensions",
        "view",
        "asof",
        "cik",
        "span",
        "break",
    ],
)
def test_ttm_requires_four_contiguous_compatible_qtd_inputs(tmp_path: Path, case: str):
    def mutate(rows):
        row = _available_ttm(rows)
        lineage = row["source_lineage"]
        inputs = lineage["derivation_inputs"]
        if case == "three":
            inputs.pop()
        elif case == "five":
            inputs.append(copy.deepcopy(inputs[-1]))
        elif case == "null_basis":
            inputs[1]["basis_version"] = None
        elif case == "other_basis":
            inputs[1]["basis_version"] = "other"
        elif case == "failure":
            lineage["compatibility_failure"] = "NULL_BASIS_VERSION"
        elif case in {"gap", "overlap"}:
            inputs[1]["period_start"] = "2025-10-02" if case == "gap" else "2025-09-30"
            inputs[1]["duration_days"] = 91 if case == "gap" else 93
        elif case == "reverse":
            inputs.reverse()
        elif case == "fy":
            inputs[1]["period_class"] = "FY"
        elif case == "unit":
            inputs[1]["unit"] = "EUR"
        elif case == "metric":
            inputs[1]["canonical_metric_id"] = "quarter_cfo"
        elif case == "dimensions":
            inputs[1]["dimensions"] = [{"axis": "geo", "member": "US"}]
        elif case == "view":
            inputs[1]["selection_view"] = "UNREVIEWED_OTHER_VIEW"
        elif case == "asof":
            inputs[1]["selection_as_of_date"] = "2025-10-10"
        elif case == "cik":
            inputs[1]["cik"] = "0000000002"
        elif case == "span":
            row["period_start"] = "2025-06-30"
        elif case == "break":
            inputs[1]["recast_break"] = True

    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


@pytest.mark.parametrize(
    "case",
    ["count", "class", "start", "end", "basis", "metric", "dimensions", "view", "asof", "rule"],
)
def test_derived_quarter_preserves_approved_cumulative_input_scope(tmp_path: Path, case: str):
    def mutate(rows):
        row = next(r for r in rows if r["source_kind"] == "DERIVED_QUARTER")
        lineage = row["source_lineage"]
        inputs = lineage["derivation_inputs"]
        if case == "count":
            inputs.pop()
        elif case == "class":
            inputs[0]["period_class"] = "FY"
        elif case == "start":
            row["period_start"] = "2025-04-02"
        elif case == "end":
            row["period_end"] = "2025-06-30"
        elif case == "basis":
            inputs[0]["basis_version"] = "other"
        elif case == "metric":
            inputs[0]["canonical_metric_id"] = "quarter_revenue"
        elif case == "dimensions":
            inputs[0]["dimensions"] = [{"axis": "geo", "member": "US"}]
        elif case == "view":
            inputs[0]["selection_view"] = "UNREVIEWED_OTHER_VIEW"
        elif case == "asof":
            inputs[0]["selection_as_of_date"] = "2025-10-10"
        elif case == "rule":
            lineage["derivation_rule_version"] = "other-rule"

    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


def test_unavailable_inputs_and_reasons_are_preserved_exactly(tmp_path: Path):
    reader = QuarterlyScreeningMetricReader(_publication(tmp_path, lambda rows: None))
    original = json.loads((WIRE / "quarter_metric_observations.json").read_text())["records"]
    assert reader.observations == original
    assert any(r["reason"] == "UNSUPPORTED_FISCAL_QUARTER_DURATION" for r in original)
    held = next(
        r
        for r in original
        if r["metric_id"] == "ttm_revenue" and r["source_kind"] == "DERIVED_METRIC"
    )
    assert held["source_lineage"]["compatibility_failure"] == "NULL_BASIS_VERSION"


def test_reported_value_must_be_the_selected_value(tmp_path: Path):
    root = _publication(tmp_path, lambda rows: rows[0].update(value="999"))
    with pytest.raises(ValueError, match="value differs"):
        QuarterlyScreeningMetricReader(root)


@pytest.mark.parametrize(
    "field",
    [
        "cik",
        "selection_view",
        "selection_as_of_date",
        "dimensions",
        "canonical_metric_id",
        "canonical_mapping_version",
    ],
)
def test_selected_source_scope_is_never_inherited(tmp_path: Path, field: str):
    root = _publication(tmp_path, lambda rows: rows[0]["source_lineage"].pop(field))
    with pytest.raises(ValueError):
        QuarterlyScreeningMetricReader(root)


def test_nonselected_evidence_is_not_promoted_to_an_input(tmp_path: Path):
    def mutate(rows):
        rows[0]["source_lineage"]["primary_statement_evidence"]["raw_evidence"] = {
            "accession": "unselected-evidence",
            "source_fact_id": None,
            "filed_date": None,
            "basis_version": None,
            "unit": None,
        }

    QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


def _nested_quarter_ttm(reader):
    quarter = copy.deepcopy(
        next(r for r in reader.observations if r["source_kind"] == "DERIVED_QUARTER")
    )
    quarter.update(
        derived_metric_id="synthetic-derived-q2",
        duration_days=91,
        canonical_mapping_version="synthetic-quarter-mapping-v1",
    )
    template = next(
        r
        for r in reader.observations
        if r["metric_id"] == "ttm_revenue" and r["source_kind"] == "DERIVED_METRIC"
    )
    row = copy.deepcopy(template)
    row.update(
        metric_id="ttm_cfo",
        canonical_metric_id="ttm_cfo",
        period_start="2025-01-01",
        period_end="2026-01-01",
        calendar_year=2025,
        calendar_quarter=4,
        fiscal_year=2025,
        fiscal_quarter="Q4",
        filed_date="2026-02-01",
        report_date="2025-12-31",
        availability_status="AVAILABLE",
        reason=None,
        reasons=[],
        value="999",
        basis_version="synthetic-basis-v1",
    )
    inputs = []
    for q in (1, 2, 3, 4):
        if q == 2:
            inputs.append(quarter)
            continue
        source = copy.deepcopy(
            next(
                r["source_lineage"]
                for r in reader.observations
                if r["metric_id"] == "quarter_revenue"
                and r["cik"] == row["cik"]
                and r["calendar_year"] == 2025
                and r["calendar_quarter"] == q
            )
        )
        source.update(
            canonical_metric_id="quarter_cfo",
            raw_concept_qname="us-gaap:NetCashProvidedByUsedInOperatingActivities",
            source_id=f"synthetic-nested-ttm-cfo-source:{q}",
            source_fact_id=f"synthetic-nested-ttm-cfo-fact:{q}",
        )
        source["selected_source_ids"] = [source["source_id"]]
        source["candidate_source_ids"] = [source["source_id"]]
        inputs.append(source)
    row["source_lineage"] = {
        "derivation_inputs": inputs,
        "derivation_rule_version": "quarter-ttm-contiguous-v1",
    }
    definition = copy.deepcopy(
        next(d for d in reader.definitions if d["metric_id"] == "ttm_revenue")
    )
    definition["metric_id"] = "ttm_cfo"
    definition["input_metric_id"] = "quarter_cfo"
    return row, definition


def test_ttm_accepts_governed_quarter_with_its_own_nested_input_lineage():
    reader = QuarterlyScreeningMetricReader(WIRE)
    row, definition = _nested_quarter_ttm(reader)
    reader._verify_observation(row, {"ttm_cfo": definition})


@pytest.mark.parametrize(
    "case", ["derived_metric_id", "nested_identity", "nested_scope", "nested_count"]
)
def test_ttm_cannot_hide_ineligible_inputs_inside_derived_quarter(case: str):
    reader = QuarterlyScreeningMetricReader(WIRE)
    row, definition = _nested_quarter_ttm(reader)
    quarter = row["source_lineage"]["derivation_inputs"][1]
    if case == "derived_metric_id":
        quarter["derived_metric_id"] = None
    elif case == "nested_identity":
        quarter["source_lineage"]["derivation_inputs"][0]["source_fact_id"] = None
    elif case == "nested_scope":
        quarter["source_lineage"]["derivation_inputs"][0]["selection_as_of_date"] = "2099-01-01"
    else:
        quarter["source_lineage"]["derivation_inputs"].pop()
    with pytest.raises(ValueError):
        reader._verify_observation(row, {"ttm_cfo": definition})


@pytest.mark.parametrize(
    "source_block",
    [
        {"quality_blocking": True},
        {"quality_status": "BLOCK"},
        {"quality_blocking": True, "quality_status": "BLOCK"},
    ],
)
@pytest.mark.parametrize(
    "row_block", [None, {"quality_blocking": True}, {"quality_status": "BLOCK"}]
)
def test_reported_selected_source_block_cannot_be_cleared(tmp_path: Path, source_block, row_block):
    def mutate(rows):
        rows[0]["source_lineage"].update(source_block)
        if row_block:
            rows[0].update(row_block)

    root = _publication(tmp_path, mutate)
    if row_block is None:
        with pytest.raises(ValueError, match="blocking is not preserved"):
            QuarterlyScreeningMetricReader(root)
    else:
        reader = QuarterlyScreeningMetricReader(root)
        assert all(reader.observations[0][key] == value for key, value in row_block.items())
        assert all(
            reader.observations[0]["source_lineage"][key] == value
            for key, value in source_block.items()
        )


@pytest.mark.parametrize(
    "field",
    [
        "compatibility_failure",
        "ambiguity",
        "ambiguous",
        "mapping_uncertainty",
        "mapping_review_required",
    ],
)
@pytest.mark.parametrize("location", ["observation", "source"])
def test_reported_selected_scope_must_be_eligible(tmp_path: Path, field: str, location: str):
    def mutate(rows):
        target = rows[0] if location == "observation" else rows[0]["source_lineage"]
        target[field] = True

    with pytest.raises(ValueError, match="incompatible selected inputs"):
        QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


@pytest.mark.parametrize("source_kind", ["REPORTED", "DERIVED_QUARTER"])
def test_null_basis_reported_and_declared_arithmetic_quarter_remain_valid(
    tmp_path: Path, source_kind
):
    def mutate(rows):
        row = next(
            row
            for row in rows
            if row["source_kind"] == source_kind and row["availability_status"] == "AVAILABLE"
        )
        row["basis_version"] = None
        lineage = row["source_lineage"]
        if source_kind == "REPORTED":
            lineage["basis_version"] = None
        else:
            for source in lineage["derivation_inputs"]:
                source["basis_version"] = None

    reader = QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))
    if source_kind == "DERIVED_QUARTER":
        row = next(row for row in reader.observations if row["source_kind"] == source_kind)
        assert (
            row["source_lineage"]["compatibility_policy"] == "ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"
        )


def test_unavailable_partial_candidate_review_lineage_is_preserved(tmp_path: Path):
    def mutate(rows):
        row = next(row for row in rows if row["availability_status"] == "UNAVAILABLE")
        row["source_lineage"]["candidate_evidence"] = [
            {
                "source_fact_id": None,
                "context_id": None,
                "mapping_review_required": True,
                "ambiguity": True,
                "quality_status": "BLOCK",
                "quality_blocking": True,
            }
        ]

    reader = QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))
    row = next(row for row in reader.observations if row["availability_status"] == "UNAVAILABLE")
    assert row["source_lineage"]["candidate_evidence"][0]["mapping_review_required"] is True
    assert row["source_lineage"]["candidate_evidence"][0]["source_fact_id"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("basis_break", True),
        ("structural_break", True),
        ("recast_break", True),
        ("continuity_break", True),
        ("recast_review_required", True),
        ("comparability_status", "REVIEW"),
    ],
)
@pytest.mark.parametrize("location", ["observation", "source"])
def test_comparison_review_does_not_erase_known_reported_value(
    tmp_path: Path, field, value, location
):
    def mutate(rows):
        target = rows[0] if location == "observation" else rows[0]["source_lineage"]
        target[field] = value

    reader = QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))
    row = reader.observations[0]
    assert row["availability_status"] == "AVAILABLE"
    assert (row if location == "observation" else row["source_lineage"])[field] == value


@pytest.mark.parametrize(
    "field",
    [
        "basis_break",
        "structural_break",
        "recast_break",
        "continuity_break",
        "recast_review_required",
    ],
)
@pytest.mark.parametrize("source_kind", ["DERIVED_QUARTER", "DERIVED_METRIC"])
def test_comparison_breaks_still_disqualify_available_derivations(
    tmp_path: Path, field, source_kind
):
    def mutate(rows):
        row = (
            _available_ttm(rows)
            if source_kind == "DERIVED_METRIC"
            else next(row for row in rows if row["source_kind"] == source_kind)
        )
        row["source_lineage"]["derivation_inputs"][0][field] = True

    with pytest.raises(ValueError, match="incompatible selected inputs"):
        QuarterlyScreeningMetricReader(_publication(tmp_path, mutate))


def test_ttm_nested_selected_raw_identity_cannot_contradict_loaded_fact():
    reader = QuarterlyScreeningMetricReader(WIRE)
    row, definition = _nested_quarter_ttm(reader)
    row["source_lineage"]["derivation_inputs"][1]["source_lineage"]["derivation_inputs"][0][
        "value"
    ] = "42"
    with pytest.raises(ValueError, match="raw source identity has contradictory content"):
        reader._verify_observation(row, {"ttm_cfo": definition})
