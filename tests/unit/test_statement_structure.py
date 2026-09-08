from copy import deepcopy

import pytest

from sec_xbrl.analytics.statement_structure import materialize_signed_calculation_checks as checks


def fact(concept, value, **overrides):
    return {"fact_id": concept, "raw_concept_id": concept, "filing_id": "filing", "canonical_identity": "RAW:" + concept,
            "value_numeric": value, "scope": {"cik": "0000000001", "filing_id": "filing", "view": "RAW_AS_FILED",
            "basis": "RAW:filing", "as_of": "2026-09-08", "period": {"type": "duration", "class": "QTD_3M",
            "start": "2025-01-01", "end": "2025-04-01", "instant": None},
            "unit": {"numerator": ["iso4217:USD"], "denominator": []}, "dimensions": []}, **overrides}


def arc(child="child", **overrides):
    return {"network_type": "CAL", "filing_id": "filing", "role_id": "role", "role_uri": "uri",
            "arcrole": "sum", "link_qname": "link:calculationLink", "arc_qname": "link:calculationArc",
            "relationship_id": "rel:" + child, "from_raw_concept_id": "parent", "to_raw_concept_id": child,
            "weight": "-1", **overrides}


def test_signed_not_share_approval():
    result = checks(facts=[fact("parent", "6"), fact("child", "4"), fact("gross", "10")],
                    relationships=[arc(), arc("gross", weight="1")])[0]
    assert result["status"] == "MATCH"
    assert result["calculated_value"] == "6"
    assert result["share_eligibility_status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("key", ["cik", "filing_id", "period", "unit", "dimensions", "view", "as_of", "basis"])
def test_missing_scope_fails_closed(key):
    f = fact("parent", "0")
    del f["scope"][key]
    with pytest.raises(ValueError):
        checks(facts=[f], relationships=[arc()])


@pytest.mark.parametrize("mutation", [
    {"cik": "0000000002"}, {"as_of": "2026-09-07"},
    {"unit": {"numerator": ["iso4217:EUR"], "denominator": []}},
    {"dimensions": [{"axis": "a", "member": "m", "typed_value": None, "is_default": False}]},
    {"period": {"type": "duration", "class": "QTD_3M", "start": "2025-01-02", "end": "2025-04-01", "instant": None}},
])
def test_exact_scope(mutation):
    child = fact("child", "1")
    child["scope"].update(mutation)
    assert checks(facts=[fact("parent", "-1"), child], relationships=[arc()])[0]["status"] == "INCOMPATIBLE_SCOPE"


def test_duplicates_missing_mismatch_and_ambiguity():
    parent, child = fact("parent", "-1"), fact("child", "1")
    assert checks(facts=[parent, child, deepcopy(child)], relationships=[arc()])[0]["status"] == "MATCH"
    assert checks(facts=[parent, child], relationships=[arc(), arc()])[0]["status"] == "DUPLICATE_RELATIONSHIP_INPUT"
    assert checks(facts=[parent], relationships=[arc()])[0]["status"] == "MISSING_INPUT"
    assert checks(facts=[child], relationships=[arc()])[0]["status"] == "MISSING_PARENT"
    assert checks(facts=[parent, fact("child", "2")], relationships=[arc()])[0]["status"] == "MISMATCH"
    assert checks(facts=[parent, child, {**child, "fact_id": "alias"}], relationships=[arc()])[0]["status"] == "AMBIGUOUS_INPUT"
    with pytest.raises(ValueError, match="conflicting"):
        checks(facts=[child, {**child, "value_numeric": "2"}], relationships=[arc()])


@pytest.mark.parametrize("field", ["role_id", "role_uri", "arcrole", "link_qname", "arc_qname"])
def test_baseset_separation(field):
    result = checks(facts=[fact("parent", "-1"), fact("child", "1")], relationships=[arc(), arc(**{field: "other"})])
    assert len(result) == 2
    assert all(r["status"] == "MATCH" for r in result)


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "-Infinity"])
def test_nonfinite(value):
    assert checks(facts=[fact("parent", "0"), fact("child", value)], relationships=[arc()])[0]["status"] == "NONFINITE_OR_NIL_INPUT"
