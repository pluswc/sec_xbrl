from decimal import Decimal

import pytest

from sec_xbrl.analytics.importance_v2 import evaluate_signals


@pytest.mark.parametrize("value,selected", [("9.99999", False), ("10", True), ("10.00001", True)])
def test_share_boundary_outside_top_amount(value, selected):
    reasons, _ = evaluate_signals(amount="1", amount_rank=6, share=value)
    assert bool(reasons) is selected


@pytest.mark.parametrize("value,selected", [("4.99999", False), ("5", True), ("5.00001", True), ("-5", True)])
def test_share_change_only(value, selected):
    reasons, _ = evaluate_signals(amount="1", amount_rank=6, share="9", share_delta=value)
    assert bool(reasons) is selected
    if selected:
        assert reasons == ["REVIEWED_SHARE_CHANGE_AT_LEAST_5_PP"]


@pytest.mark.parametrize("rate,delta,selected", [("24.99999", "1", False), ("25", ".99999", False), ("25", "1", True), ("25.00001", "1.00001", True), ("-25", "-1", True), ("10000", ".000001", False)])
def test_and_boundary_and_tiny_base(rate, delta, selected):
    reasons, _ = evaluate_signals(amount="1", amount_rank=6, rate=rate, delta=delta, scale="100")
    assert bool(reasons) is selected


@pytest.mark.parametrize("value", [None, "0", "-1", "NaN", "Infinity"])
def test_invalid_scale_does_not_suppress_share(value):
    reasons, warnings = evaluate_signals(amount="1", share="15", rate="26", delta="2", scale=value)
    assert reasons == ["REVIEWED_SHARE_AT_LEAST_10_PERCENT"]
    assert warnings == ["EXACT_POSITIVE_REFERENCE_SCALAR_UNAVAILABLE"]


def test_decimal_no_binary_float_boundary():
    reasons, _ = evaluate_signals(amount=Decimal(1), rate=Decimal(25), delta=Decimal(".01"), scale=Decimal(1))
    assert reasons == ["YOY_25_PERCENT_AND_PARENT_SCALE_1_PERCENT"]


@pytest.fixture
def reviewed_pair():
    from copy import deepcopy
    facts, reviews = [], []
    table = {"source_document_sha256": "a"*64, "table_sha256": "b"*64, "table_locator": "/table", "table_id": "table"}
    for year, amounts in [(2024, (100, 80, 20)), (2025, (100, 86, 14))]:
        scope = {"cik": "0000000001", "filing_id": "filing", "view": "RAW_AS_FILED", "as_of": "2026-09-08", "basis": "RAW:filing",
                 "period": {"type": "duration", "class": "QTD_3M", "start": f"{year}-01-01", "end": f"{year}-04-01", "instant": None},
                 "unit": {"numerator": ["iso4217:USD"], "denominator": []}, "dimensions": []}
        ids = []
        source_cells = {}
        for concept, amount in zip(("parent", "a", "b"), amounts, strict=True):
            fid = f"{year}-{concept}"
            source_cells[fid] = {"inline_id": fid, "row_locator": "/table/" + concept}
            ids.append(fid)
            facts.append({"fact_id": fid, "filing_id": "filing", "raw_concept_id": concept, "canonical_identity": "RAW:" + concept,
                          "scope": deepcopy(scope), "reported_or_derived": "REPORTED", "is_nil": False, "value_numeric": str(amount),
                          "source_locations": [{"table_id": "table", **source_cells[fid]}]})
        reviews.append({"review_id": str(year), "reviewer": "synthetic-test-only", "economic_scope_id": "scope", "complete": True, "exclusive": True,
                        "reviewed_at": "2026-09-08T00:00:00+00:00", **table, "parent_fact_id": ids[0], "child_fact_ids": ids[1:],
                        "scope": scope, "source_cells": source_cells})
    return {"facts": facts, "tables": [table], "reviews": reviews, "decision_cutoff": "2026-09-08T01:00:00+00:00"}


def test_bound_two_period_share_and_four_inputs(reviewed_pair):
    from sec_xbrl.analytics.importance_v2 import reviewed_raw_shares
    rows = reviewed_raw_shares(**reviewed_pair)
    row = next(r for r in rows if r["current_fact_id"] == "2025-a")
    assert row["share_change_pp"]["value"] == "6.00"
    assert row["share_change_pp"]["input_ids"] == ["2025-a", "2025-parent", "2024-a", "2024-parent"]
    prior = next(r for r in rows if r["current_fact_id"] == "2024-a")
    assert prior["amount_change"]["reason"] == "NO_COMPATIBLE_PRIOR_REVIEW"


@pytest.mark.parametrize("field,value", [
    ("unit", {"numerator": ["iso4217:EUR"], "denominator": []}),
    ("dimensions", [{"axis": "axis", "member": "member", "typed_value": None, "is_default": False}]),
    ("cik", "0000000002"), ("as_of", "2026-09-07"),
])
def test_two_valid_but_incompatible_reviews_do_not_allow_pp(reviewed_pair, field, value):
    from copy import deepcopy

    from sec_xbrl.analytics.importance_v2 import reviewed_raw_shares
    for f in reviewed_pair["facts"][:3]:
        f["scope"][field] = deepcopy(value)
    reviewed_pair["reviews"][0]["scope"][field] = value
    rows = reviewed_raw_shares(**reviewed_pair)
    current = next(r for r in rows if r["current_fact_id"] == "2025-a")
    assert current["share"]["status"] == "AVAILABLE"
    assert current["share_change_pp"]["status"] == "UNAVAILABLE"


def test_different_parent_definition_same_scope_string_rejected(reviewed_pair):
    from sec_xbrl.analytics.importance_v2 import reviewed_raw_shares
    reviewed_pair["facts"][0].update(raw_concept_id="other-parent", canonical_identity="RAW:other-parent")
    rows = reviewed_raw_shares(**reviewed_pair)
    assert next(r for r in rows if r["current_fact_id"] == "2025-a")["share_change_pp"]["value"] is None


@pytest.mark.parametrize("mutate", ["nil", "empty_scope", "naive_time", "zero_child", "bad_table", "bad_inline"])
def test_invalid_share_review_fails_closed(reviewed_pair, mutate):
    from sec_xbrl.analytics.importance_v2 import reviewed_raw_shares
    if mutate == "nil":
        reviewed_pair["facts"][1]["is_nil"] = True
    elif mutate == "empty_scope":
        for f in reviewed_pair["facts"]:
            f["scope"] = {}
        for r in reviewed_pair["reviews"]:
            r["scope"] = {}
    elif mutate == "naive_time":
        reviewed_pair["reviews"][0]["reviewed_at"] = "2026-09-08T00:00:00"
    elif mutate == "zero_child":
        reviewed_pair["facts"][1]["value_numeric"] = "0"
    elif mutate == "bad_table":
        reviewed_pair["reviews"][0]["table_sha256"] = "c"*64
    else:
        reviewed_pair["reviews"][0]["source_cells"]["2024-a"]["inline_id"] = "wrong"
    with pytest.raises(ValueError):
        reviewed_raw_shares(**reviewed_pair)


def test_raw_standard_same_table_and_custom_remain_distinct(reviewed_pair):
    from sec_xbrl.analytics.importance_v2 import materialize_raw_statement_v2
    facts = reviewed_pair["facts"]
    for f in facts:
        f["concept"] = {"data_type": "xbrli:monetaryItemType", "is_standard": True, "taxonomy_family": "us-gaap", "taxonomy_version": "2025", "namespace_uri": "http://fasb.org/us-gaap/2025"}
    table = {**reviewed_pair["tables"][0], "section": "IS"}
    rows = [{"table_id": "table", "parent_row_id": None, "cells": [{"inline_facts": [{"fact_id": f["fact_id"]}]}]} for f in facts]
    result = materialize_raw_statement_v2(facts=facts, tables=[table], rows=rows, checks=[], reviewed=[])
    current = next(r for r in result if r["current_fact_id"] == "2025-a")
    assert current["amount_change"]["value"] == "6"
    assert current["is_reference_period"] is True
    assert current["share"]["status"] == "UNAVAILABLE"
    assert "REPORTED_ARITHMETIC_NOT_RECAST_VALIDATED" in current["warnings"]
    facts[4]["concept"]["is_standard"] = False
    result = materialize_raw_statement_v2(facts=facts, tables=[table], rows=rows, checks=[], reviewed=[])
    assert next(r for r in result if r["current_fact_id"] == "2025-a")["amount_change"]["reason"] == "CUSTOM_COMPARISON_NOT_APPROVED"


@pytest.mark.parametrize("prior_value,expected", [("NaN", "NONFINITE_OR_NONNUMERIC_PRIOR"), ("invalid", "NONFINITE_OR_NONNUMERIC_PRIOR"), ("0", "ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE"), ("-1", "ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE")])
def test_raw_statement_prior_failures_keep_precise_reasons(reviewed_pair, prior_value, expected):
    from sec_xbrl.analytics.importance_v2 import materialize_raw_statement_v2
    facts = reviewed_pair["facts"]
    for f in facts:
        f["concept"] = {"data_type": "xbrli:monetaryItemType", "is_standard": True, "taxonomy_family": "us-gaap", "taxonomy_version": "2025", "namespace_uri": "http://fasb.org/us-gaap/2025"}
    facts[1]["value_numeric"] = prior_value
    table = {**reviewed_pair["tables"][0], "section": "IS"}
    rows = [{"table_id": "table", "parent_row_id": None, "cells": [{"inline_facts": [{"fact_id": f["fact_id"]}]}]} for f in facts]
    result = materialize_raw_statement_v2(facts=facts, tables=[table], rows=rows, checks=[], reviewed=[])
    current = next(r for r in result if r["current_fact_id"] == "2025-a")
    assert current["rate_change"]["reason"] == expected
    assert current["rate_change"]["value"] is None
    if prior_value in {"0", "-1"}:
        assert current["amount_change"]["value"] is not None
    else:
        assert current["amount_change"]["reason"] == expected
    assert "ACTUAL_DURATION_DIFFERS" in current["warnings"]
