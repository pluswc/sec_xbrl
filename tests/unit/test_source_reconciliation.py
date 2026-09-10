from copy import deepcopy

import pytest

from sec_xbrl.analytics.source_reconciliation import materialize_source_reconciliations


def fixture():
    scope = {"cik": "0000000001", "filing_id": "f", "view": "RAW_AS_FILED", "basis": "RAW:f", "as_of": "2026-09-08",
             "period": {"type": "duration", "class": "QTD_3M", "start": "2025-01-01", "end": "2025-04-01", "instant": None},
             "unit": {"numerator": ["iso4217:USD"], "denominator": []}, "dimensions": []}
    facts, bindings = [], []
    for key, value, member in [("pretax", "90", None), ("segment", "100", "segments"), ("adjustment", "10", "corporate")]:
        own = deepcopy(scope)
        if member:
            own["dimensions"] = [{"axis": "a", "member": member, "typed_value": None, "is_default": False}]
        binding = {"fact_id": key, "inline_id": key, "row_locator": "/table/"+key, "scope": own}
        bindings.append(binding)
        facts.append({"fact_id": key, "filing_id": "f", "raw_concept_id": key, "canonical_identity": "RAW:"+key,
                      "scope": own, "value_numeric": value, "is_nil": False, "reported_or_derived": "REPORTED",
                      "source_locations": [{"table_id": "table", "inline_id": key, "row_locator": "/table/"+key}]})
    table = {"table_id": "table", "table_locator": "/table", "table_sha256": "b"*64, "source_document_sha256": "a"*64}
    review = {"review_id": "synthetic", "reviewer": "synthetic-only", "reviewed_at": "2026-09-08T00:00:00+00:00", **table,
              "parent": bindings[0], "inputs": [{**bindings[1], "weight": "1"}, {**bindings[2], "weight": "-1"}]}
    return {"facts": facts, "tables": [table], "reviews": [review], "decision_cutoff": "2026-09-08T01:00:00+00:00"}


def test_exact_reviewed_dimension_changes_are_not_cal_or_share():
    result = materialize_source_reconciliations(**fixture())[0]
    assert result["calculated_value"] == "90"
    assert result["relationship_type"] == "REVIEWED_SOURCE_RECONCILIATION"
    assert result["status"] == "MATCH"
    assert result["share_eligibility_status"] == "NOT_AUTHORIZED"


@pytest.mark.parametrize("field", ["unit", "period", "cik", "inline", "dimension", "duplicate"])
def test_exact_binding_cannot_be_relaxed(field):
    args = fixture()
    if field == "unit":
        args["facts"][1]["scope"]["unit"]["numerator"] = ["iso4217:EUR"]
    elif field == "period":
        args["facts"][1]["scope"]["period"]["start"] = "2025-01-02"
    elif field == "cik":
        args["facts"][1]["scope"]["cik"] = "0000000002"
    elif field == "inline":
        args["reviews"][0]["inputs"][0]["inline_id"] = "wrong"
    elif field == "dimension":
        args["reviews"][0]["inputs"][0]["scope"] = deepcopy(args["reviews"][0]["parent"]["scope"])
    else:
        args["reviews"][0]["inputs"].append(args["reviews"][0]["inputs"][0])
    with pytest.raises(ValueError):
        materialize_source_reconciliations(**args)
