from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from examples.screening.enrich_revenue_q4 import RATIO_RULE, _review_source, enrich
from tests.unit.test_revenue_q4_continuity import inputs, link


@pytest.fixture
def fixture():
    rows = inputs()
    for row in rows:
        kind = row["period_class"]
        row.update(accession="0000000001-26-000001" if kind == "FY" else "0000000001-25-000003",
                   source_snapshot_id="l1:0000000001:" + ("000000000126000001" if kind == "FY" else "000000000125000003") + ":snapshot",
                   raw_concept_id="revenue-" + kind)
    prior = []
    for row, value in zip(rows, ("80", "50"), strict=True):
        previous = {**deepcopy(row), "period_observation_id": row["period_observation_id"] + "-prior",
                    "source_fact_id": row["source_fact_id"] + "-prior", "comparative_type": "PRIOR_YEAR_COMPARABLE", "value_numeric": value,
                    "context_start_date": "2024-01-01", "context_end_date": "2025-01-01" if row["period_class"] == "FY" else "2024-10-01",
                    "context_duration_days": 366 if row["period_class"] == "FY" else 274}
        prior.append(previous)
    total = [{**deepcopy(row), "period_observation_id": row["period_observation_id"] + "-total",
              "source_fact_id": row["source_fact_id"] + "-total", "value_numeric": value,
              "company_canonical_concept_id": "total", "mapping_review_required": False,
              "raw_dimension_signature": [], "canonical_dimension_signature": [], "dimension_mapping_ids": []}
             for row, value in zip(rows, ("500", "300"), strict=True)]
    current = link(rows)
    previous = link(prior)
    previous["id"] = "prior"
    previous["period"].update(fiscal_year=2024, period_start="2024-10-01", period_end="2025-01-01")
    target = {"cik": "0000000001", "group": "products", "row_id": "product", "mapping_epoch": "quarter-epoch", "fiscal_year": 2025, "fiscal_quarter": 4}
    gap = {"value": None, "status": "UNAVAILABLE", "reason": "Q4_MAPPING_REVIEW_REQUIRED", "cell_id": None, "sources": [], "share": None, "yoy": None}
    total_cell = {"value": "200", "status": "DERIVED", "reason": None, "cell_id": "total", "sources": [_review_source(row, row["cik"], "2026-10-25") for row in total], "share": None, "yoy": None}
    row = {"id": "product", "mapping_epoch": "quarter-epoch", "mapping_review_required": False, "scope": None,
           "axis_members": {"srt:ProductOrServiceAxis": "fixture:ProductMember"}, "cells": [gap]}
    view = {"periods": [{"fiscal_year": 2025, "fiscal_quarter": 4, "period_start": "2025-10-01", "period_end": "2026-01-01"}],
            "groups": {"products": [row]}, "totals": [total_cell], "availability": {"products": [{"available_count": 0, "gap_counts": {gap["reason"]: 1}}]}}
    baseline = {"dataset_id": "fixture", "dataset_publication_id": "pub", "dataset_manifest_sha256": "a" * 64, "financial_as_of": "2026-10-25", "companies": {"0000000001": {"quarterly": view}}}
    old = {**{key: baseline[key] for key in ("dataset_id", "dataset_publication_id", "dataset_manifest_sha256", "financial_as_of")}, "companies": {"0000000001": {"derived_metrics": []}}}
    from sec_xbrl.analytics.revenue_q4_continuity import _digest
    review = {"schema_version": "revenue-q4-continuity-review-v1", "authority": "ROOT", "status": "ROOT_APPROVED", "financial_as_of": "2026-10-25",
              "evidence_files": {"disclosure": {}}, "amount_links": [current, previous],
              "projection_grants": [{"amount_id": current["id"], "target": target, "connect_previous": False, "evidence": current["evidence"]}],
              "share_grants": [{"numerator": {"amount_id": current["id"]}, "target": target, "denominator": {"target": {"cik": target["cik"], "group": "totals", "fiscal_year": 2025, "fiscal_quarter": 4}, "cell_id": "total", "cell_sha256": _digest(total_cell)}, "evidence": current["evidence"]}],
              "yoy_grants": [{"current": {"amount_id": current["id"]}, "prior": {"amount_id": "prior"}, "target": target, "evidence": current["evidence"]}]}
    names = {(row["cik"], row["source_filing_id"], raw): name for row in rows for raw, name in (("raw-axis", "srt:ProductOrServiceAxis"), ("raw-member", "fixture:ProductMember"))}
    return review, baseline, old, [*rows, *prior, *total], names


def run(fixture):
    review, baseline, old, observations, names = fixture
    return enrich(review, baseline, old, observations, scope_names=names)


def test_projection_share_and_comparative_yoy_are_independent_and_original_history_is_preserved(fixture):
    original = deepcopy(fixture)
    asset, companion = run(fixture)
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["value"] == "50" and cell["share"] == "25.00"
    assert Decimal(cell["yoy"]) == Decimal("66.66666666666666666666666670")
    assert cell["ratios"]["yoy"]["prior_value"] == "30"
    assert cell["ratios"]["yoy"]["prior_comparison_only"] is True
    assert cell["ratios"]["yoy"]["derivation_rule_version"] == RATIO_RULE
    assert cell["connect_previous"] is cell["connect_next"] is False
    assert companion["derived_metrics"][1]["comparison_only"] is True
    assert fixture == original
    assert asset["companies"]["0000000001"]["quarterly"]["totals"] == original[1]["companies"]["0000000001"]["quarterly"]["totals"]
    fixture[0]["share_grants"] = []
    fixture[0]["yoy_grants"] = []
    asset, _ = run(fixture)
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["share"] is cell["yoy"] is None


@pytest.mark.parametrize("case", ["foreign_target", "wrong_epoch", "wrong_parent_hash", "non_null", "comparison_projection", "unapproved"])
def test_invalid_grants_never_replace_existing_or_foreign_scope(fixture, case):
    review, baseline, _, _, _ = fixture
    if case == "foreign_target":
        baseline["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["axis_members"] = {"other": "scope"}
    elif case == "wrong_epoch":
        review["projection_grants"][0]["target"]["mapping_epoch"] = "other"
    elif case == "wrong_parent_hash":
        review["share_grants"][0]["denominator"]["cell_sha256"] = "0" * 64
    elif case == "non_null":
        baseline["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]["value"] = "99"
    elif case == "comparison_projection":
        review["projection_grants"][0]["amount_id"] = "prior"
    else:
        review["status"] = "PROPOSED"
    with pytest.raises(ValueError):
        run(fixture)


def test_ratio_ineligible_parent_holds_only_share_and_keeps_valid_amount_yoy(fixture):
    from sec_xbrl.analytics.revenue_q4_continuity import _digest
    review, baseline, _, rows, _ = fixture
    for row in rows[-2:]:
        row["value_numeric"] = "300"
    cell = baseline["companies"]["0000000001"]["quarterly"]["totals"][0]
    cell["value"] = "0"
    review["share_grants"][0]["denominator"]["cell_sha256"] = _digest(cell)
    asset, companion = run(fixture)
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["value"] == "50" and cell["yoy"] is not None and cell["share"] is None
    assert companion["exclusions"][0]["reason"] == "Q4_SHARE_PARENT_OR_NUMERATOR_NOT_ELIGIBLE"


def test_explicit_source_tag_diagnostic_changes_only_the_target_null_reason(fixture):
    review, baseline, _, _, _ = fixture
    review["amount_links"] = []
    review["projection_grants"] = []
    review["share_grants"] = []
    review["yoy_grants"] = []
    review["hold_grants"] = [{"target": {"cik": "0000000001", "group": "products", "row_id": "product", "mapping_epoch": "quarter-epoch", "fiscal_year": 2025, "fiscal_quarter": 4},
        "reason": "Q4_SOURCE_TAG_PRESENTATION_CONFLICT", "evidence": [{"file_id": "disclosure", "locator": "inline fact", "assertion": "tag/presentation conflict"}]}]
    asset, _ = run(fixture)
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["value"] is None and cell["reason"] == "Q4_SOURCE_TAG_PRESENTATION_CONFLICT"
    assert baseline["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]["reason"] == "Q4_MAPPING_REVIEW_REQUIRED"



def test_new_publisher_pins_and_overwrite_refusal_use_only_new_outputs(fixture, tmp_path, monkeypatch):
    import json

    from examples.screening import enrich_revenue_q4 as module
    from sec_xbrl.screening.common import sha256_file
    review, baseline, old, observations, names = fixture
    baseline["schema_version"] = "screening-revenue-breakdowns-v1"
    def pinned(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"path": str(path), "sha256": sha256_file(path)}
    review["baseline_asset"] = pinned("baseline.json", baseline)
    review["baseline_companion"] = pinned("old-companion.json", old)
    review["source_inventory"] = pinned("inventory.json", {})
    review["evidence_files"] = {"disclosure": pinned("disclosure.json", {"reviewed": True})}
    review_pin = pinned("review.json", review)
    monkeypatch.setattr(module, "_load_sources", lambda *args: (observations, names))
    asset, companion = tmp_path / "new-asset.json", tmp_path / "new-companion.json"
    assert module.publish(review_pin, asset, companion)["derived_count"] == 2
    original = (asset.read_bytes(), companion.read_bytes())
    with pytest.raises(ValueError, match="new destination"):
        module.publish(review_pin, asset, companion)
    assert (asset.read_bytes(), companion.read_bytes()) == original
    (tmp_path / "disclosure.json").write_text("tampered")
    with pytest.raises(ValueError, match="pin"):
        module.publish(review_pin, tmp_path / "bad-asset.json", tmp_path / "bad-companion.json")
    assert not (tmp_path / "bad-asset.json").exists()


def test_typed_extra_dimension_basis_and_prior_scope_fail_closed(fixture):
    review, _, _, observations, _ = fixture
    from sec_xbrl.analytics.revenue_q4_continuity import review_endpoint
    for index, key in ((2, "annual"), (3, "ytd9")):
        source = observations[index]
        source["raw_dimension_signature"] = [["raw-axis", "other-member", None, "EXPLICIT", "false"]]
        fixture[4][(source["cik"], source["source_filing_id"], "other-member")] = "fixture:OtherMember"
        review["amount_links"][1][key] = review_endpoint(source)
    asset, companion = run(fixture)
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["value"] == "50" and cell["share"] is not None and cell["yoy"] is None
    assert any(row["reason"] == "Q4_YOY_COMPARABLE_PRIOR_NOT_QUALIFIED" for row in companion["exclusions"])


@pytest.mark.parametrize("case", ["dimensioned_total", "different_start", "foreign_company", "unit"])
def test_denominator_source_scope_dates_company_and_units_are_independently_verified(fixture, case):
    for source in fixture[3][-2:]:
        if case == "dimensioned_total":
            source.update(raw_dimension_signature=[["extra-axis", "extra-member", None, "EXPLICIT", "false"]],
                          canonical_dimension_signature=[["canonical-extra", "canonical-member", None, "EXPLICIT", "false"]],
                          dimension_mapping_ids=[["axis-map", "member-map"]])
        elif case == "different_start" and source["period_class"] == "YTD_9M":
            source["context_start_date"] = "2025-01-02"
            source["context_duration_days"] = 272
        elif case == "foreign_company":
            source["cik"] = "0000000002"
        elif case == "unit":
            source["unit_numerator_measures"] = '["iso4217:EUR"]'
    with pytest.raises(ValueError):
        run(fixture)


def test_existing_confirmed_q4_enrichment_preserves_every_amount_identity_and_source(fixture):
    review, baseline, old, rows, _ = fixture
    current = rows[:2]
    for row in current:
        row["mapping_review_required"] = False
        row["company_canonical_concept_id"] = "confirmed"
    existing = {"derived_metric_id": "old-confirmed", "cik": current[0]["cik"], "fiscal_year": 2025,
                "context_start_date": "2025-10-01", "context_end_date": "2026-01-01", "value_numeric": "50",
                "source_fact_ids": [row["source_fact_id"] for row in current],
                "source_inputs": [{**deepcopy(row), "selected_source_fact_id": row["source_fact_id"]} for row in current]}
    old["companies"]["0000000001"]["derived_metrics"] = [existing]
    cell = baseline["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    cell.update(value="50", status="DERIVED", reason=None, cell_id="old-confirmed", sources=[_review_source(row, row["cik"], "2026-10-25") for row in current])
    protected = {key: deepcopy(cell[key]) for key in ("value", "status", "cell_id", "sources")}
    review["amount_links"] = []
    review["projection_grants"] = []
    review["yoy_grants"] = []
    review["share_grants"][0]["numerator"] = {"derived_metric_id": "old-confirmed"}
    output, companion = run(fixture)
    updated = output["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert {key: updated[key] for key in protected} == protected
    assert updated["share"] == "25.00" and companion["derived_metrics"] == []


@pytest.mark.parametrize("field,value", [("raw_concept_qname", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("raw_concept_namespace_uri", "http://fasb.org/us-gaap/2024"), ("raw_concept_id", "foreign-revenue"),
    ("source_filing_id", "foreign-filing")])
def test_share_does_not_mix_other_revenue_concepts_namespaces_or_filings(fixture, field, value):
    for row in fixture[3][-2:]:
        row[field] = value
    output, companion = run(fixture)
    cell = output["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["share"] is None and cell["yoy"] is not None
    assert companion["exclusions"][0]["reason"] == "Q4_SHARE_REVENUE_CONCEPT_OR_FILING_MISMATCH"


def test_same_scope_grant_cannot_hide_a_different_original_member(fixture):
    review, _, _, observations, names = fixture
    review["amount_links"][0]["relation"] = "SAME"
    row = observations[0]
    names[(row["cik"], row["source_filing_id"], "raw-member")] = "fixture:OtherMember"
    with pytest.raises(ValueError, match="scope correspondence"):
        run(fixture)


def test_renamed_member_grant_cannot_change_the_actual_axis(fixture):
    _, _, _, observations, names = fixture
    row = observations[0]
    names[(row["cik"], row["source_filing_id"], "raw-axis")] = "fixture:OtherAxis"
    with pytest.raises(ValueError, match="scope correspondence"):
        run(fixture)


@pytest.mark.parametrize("permission", ["approved", "absent", "wrong_fact", "one_document"])
def test_disclosed_fixed_segment_total_requires_every_separate_permission(fixture, permission):
    from sec_xbrl.analytics.revenue_q4_continuity import review_endpoint
    review, baseline, _, observations, names = fixture
    view = baseline["companies"]["0000000001"]["quarterly"]
    row = view["groups"].pop("products")[0]
    view["groups"]["segments"] = [row]
    view["availability"]["segments"] = view["availability"].pop("products")
    qualifier = {"srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember"}
    row.update(axis_members={"us-gaap:StatementBusinessSegmentsAxis": "fixture:SegmentMember", **qualifier}, fixed_axis_members=qualifier)
    for source in observations[:4]:
        source["raw_dimension_signature"].append(["qual-axis", "qual-member", None, "EXPLICIT", "false"])
        source["canonical_dimension_signature"].append(["canonical-qual-axis", "canonical-qual-member", None, "EXPLICIT", "false"])
        source["dimension_mapping_ids"].append(["qual-axis-map", "qual-member-map"])
        for identity, name in (("raw-axis", "us-gaap:StatementBusinessSegmentsAxis"), ("raw-member", "fixture:SegmentMember"),
                               ("qual-axis", "srt:ConsolidationItemsAxis"), ("qual-member", "us-gaap:OperatingSegmentsMember")):
            names[(source["cik"], source["source_filing_id"], identity)] = name
    for index, approved in enumerate(review["amount_links"]):
        approved["annual"] = review_endpoint(observations[index * 2])
        approved["ytd9"] = review_endpoint(observations[index * 2 + 1])
    for key in ("projection_grants", "share_grants", "yoy_grants"):
        review[key][0]["target"]["group"] = "segments"
    grant = review["share_grants"][0]
    grant["denominator_relation"] = "DISCLOSED_FIXED_SCOPE_TOTAL_EQUIVALENCE"
    grant["denominator_source_fact_ids"] = [source["source_fact_id"] for source in observations[-2:]]
    review["evidence_files"].update({"annual-doc": {"sha256": "1" * 64}, "nine-doc": {"sha256": "2" * 64}})
    grant["evidence"] = [{"file_id": key, "locator": "explicit segment net revenue parent", "assertion": "reviewed total equivalence"}
                         for key in ("annual-doc", "nine-doc")]
    if permission == "absent":
        del grant["denominator_relation"]
    elif permission == "wrong_fact":
        grant["denominator_source_fact_ids"][0] = "foreign"
    elif permission == "one_document":
        grant["evidence"] = grant["evidence"][:1]
    result, companion = run(fixture)
    cell = result["companies"]["0000000001"]["quarterly"]["groups"]["segments"][0]["cells"][0]
    assert cell["value"] == "50"
    if permission == "approved":
        assert cell["share"] == "25.00", companion["exclusions"]
        assert cell["ratios"]["share"]["denominator"] == "DISCLOSED_FIXED_SCOPE_TOTAL"
    else:
        assert cell["share"] is None
        assert companion["exclusions"][0]["reason"] == "Q4_SHARE_FIXED_PARENT_SCOPE_MISMATCH"


def test_publish_uses_real_pinned_parquet_loader_and_name_maps(fixture, tmp_path):
    import json

    import polars as pl

    from examples.screening.enrich_revenue_q4 import publish
    from sec_xbrl.screening.common import sha256_file

    review, baseline, old, observations, names = fixture
    baseline["schema_version"] = "screening-revenue-breakdowns-v1"
    def json_pin(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"path": str(path), "sha256": sha256_file(path)}
    def parquet_pin(name, rows):
        path = tmp_path / name
        pl.DataFrame(rows).write_parquet(path)
        return {"path": str(path), "sha256": sha256_file(path)}
    source = {"analysis": json_pin("analysis.json", {}),
              "history": json_pin("history.json", {"input_fingerprint": "accepted-fixture"}),
              "t1_manifest": json_pin("t1-manifest.json", {"run_fingerprint": "accepted-fixture"}),
              "t2_manifest": json_pin("t2-manifest.json", {})}
    mappings = [{"cik": cik, "source_filing_id": filing, "source_raw_concept_id": raw, "source_qname": qname}
                for (cik, filing, raw), qname in names.items()]
    source["t1_files"] = {"reported_period_observation": parquet_pin("observations.parquet", observations),
        "company_axis_map": parquet_pin("axes.parquet", [row for row in mappings if row["source_raw_concept_id"] == "raw-axis"]),
        "company_member_map": parquet_pin("members.parquet", [row for row in mappings if row["source_raw_concept_id"] == "raw-member"]),
        "company_concept_map": parquet_pin("concepts.parquet", [{"source_qname": "us-gaap:Revenues"}])}
    baseline["companies"]["0000000001"]["quarterly"]["ratio_evidence"] = {
        "history_manifest_sha256": source["history"]["sha256"],
        "reported_panel_manifest_sha256": source["t1_manifest"]["sha256"],
        "reported_observations_sha256": source["t1_files"]["reported_period_observation"]["sha256"]}
    review["baseline_asset"] = json_pin("baseline.json", baseline)
    review["baseline_companion"] = json_pin("old-companion.json", old)
    review["source_inventory"] = json_pin("inventory.json", {"0000000001": source})
    review["evidence_files"] = {"disclosure": json_pin("disclosure.json", {"reviewed": True})}
    review_pin = json_pin("review.json", review)
    outputs = tmp_path / "real-asset.json", tmp_path / "real-companion.json"
    result = publish(review_pin, *outputs)
    assert result["derived_count"] == 2 and result["ratio_count"] == 2
    asset = json.loads(outputs[0].read_bytes())
    cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
    assert cell["value"] == "50" and cell["share"] == "25.00" and cell["yoy"] is not None
    companion = json.loads(outputs[1].read_bytes())
    assert any(pin["sha256"] == source["t1_files"]["reported_period_observation"]["sha256"] for pin in companion["input_pins"])
    # An edited on-disk observation must be rejected before any new output is installed.
    changed = deepcopy(observations)
    changed[0]["value_numeric"] = "999"
    pl.DataFrame(changed).write_parquet(source["t1_files"]["reported_period_observation"]["path"])
    with pytest.raises(ValueError, match="pin"):
        publish(review_pin, tmp_path / "tampered-asset.json", tmp_path / "tampered-companion.json")
    assert not (tmp_path / "tampered-asset.json").exists()

@pytest.mark.parametrize("empty", [{}, None])
def test_absent_and_empty_fixed_scope_both_allow_undimensioned_parent(fixture, empty):
    fixture[1]["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["fixed_axis_members"] = empty
    asset, _ = run(fixture)
    assert asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]["share"] == "25.00"

@pytest.mark.parametrize("extra_axis", [False, True])
def test_fixed_parent_matches_full_parent_axes_not_parent_fixed_metadata(fixture, extra_axis):
    from sec_xbrl.analytics.revenue_q4_continuity import _digest, review_endpoint
    review, baseline, _, observations, names = fixture
    view = baseline["companies"]["0000000001"]["quarterly"]
    row = view["groups"]["products"][0]
    qualifier = {"fixed-axis": "fixed-member"}
    row["fixed_axis_members"] = qualifier
    for source in observations:
        source["raw_dimension_signature"].append(["qual-axis", "qual-member", None, "EXPLICIT", "false"])
        source["canonical_dimension_signature"].append(["canonical-qual-axis", "canonical-qual-member", None, "EXPLICIT", "false"])
        source["dimension_mapping_ids"].append(["qual-axis-map", "qual-member-map"])
        names[(source["cik"], source["source_filing_id"], "qual-axis")] = "fixed-axis"
        names[(source["cik"], source["source_filing_id"], "qual-member")] = "fixed-member"
    for index, approved in enumerate(review["amount_links"]):
        approved["annual"] = review_endpoint(observations[index * 2])
        approved["ytd9"] = review_endpoint(observations[index * 2 + 1])
    parent = {"id": "fixed-parent", "mapping_epoch": "parent", "scope": None, "axis_members": qualifier, "fixed_axis_members": {}, "cells": [deepcopy(view["totals"][0])]}
    parent["cells"][0]["sources"] = [_review_source(source, source["cik"], "2026-10-25") for source in observations[-2:]]
    view["groups"]["products"].append(parent)
    reference = review["share_grants"][0]["denominator"]
    reference["target"].update(group="products", row_id="fixed-parent", mapping_epoch="parent")
    reference["cell_sha256"] = _digest(parent["cells"][0])
    if extra_axis:
        parent["axis_members"]["unexpected"] = "scope"
        with pytest.raises(ValueError, match="full axis/member"):
            run(fixture)
    else:
        asset, _ = run(fixture)
        cell = asset["companies"]["0000000001"]["quarterly"]["groups"]["products"][0]["cells"][0]
        assert cell["share"] == "25.00"
        assert cell["ratios"]["share"]["denominator"] == "FIXED_SCOPE_Q4"
