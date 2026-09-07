from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.longitudinal import CompanyCanonicalizer


def _fixture(*, same_namespace=False):
    filings, concepts, roles, relationships = [], [], [], []
    for number in (1, 2):
        filing = f"filing-{number}"
        namespace = f"https://issuer.test/{20240101 if same_namespace else 20240000 + number * 100 + 1}"
        filings.append({"filing_id": filing, "cik": "0000000001", "filed_date": f"2024-0{number + 1}-01"})
        for name in ("Parent", "CustomValue"):
            concepts.append({"filing_id": filing, "raw_concept_id": f"{name}-{number}", "qname": "issuer:" + name,
                             "namespace_uri": namespace, "local_name": name, "label": name,
                             "is_standard": False, "period_type": "duration", "data_type": "xbrli:monetaryItemType", "abstract": False})
        roles.append({"filing_id": filing, "role_id": f"role-hash-{number}", "role_uri": "https://issuer.test/role/Income"})
        relationships.append({"filing_id": filing, "relationship_id": f"edge-{number}", "role_id": f"role-hash-{number}",
                              "network_type": "PRE", "arcrole": "http://www.xbrl.org/2003/arcrole/parent-child",
                              "link_qname": "link:presentationLink", "arc_qname": "link:presentationArc",
                              "from_raw_concept_id": f"Parent-{number}", "to_raw_concept_id": f"CustomValue-{number}"})
    return {"filings": filings, "concepts": concepts, "roles": roles, "relationships": relationships}


def _values(arguments):
    return [row for row in CompanyCanonicalizer().build(**arguments).company_concept_map if row["source_local_name"] == "CustomValue"]


@pytest.mark.parametrize("same_namespace", [False, True])
def test_filing_scoped_role_hashes_resolve_to_qualified_stable_network(same_namespace):
    args = _fixture(same_namespace=same_namespace)
    original = deepcopy(args)
    old, new = _values(args)
    assert new["company_canonical_id"] == old["company_canonical_id"]
    assert new["method"] == "CUSTOM_SEMANTIC_NETWORK_CONTINUITY"
    assert not new["review_required"]
    assert new["evidence"]["source_relationship_ids"] == ["edge-2"]
    assert "https://issuer.test/role/Income" in str(new["evidence"]["qualified_network_signature"])
    assert args == original


@pytest.mark.parametrize("case", ["label", "changed_label", "type", "period", "owner", "parent", "target_role", "role_binding", "partial_edge", "base_set", "same_filing", "unknown_arcrole"])
def test_incomplete_changed_or_ambiguous_custom_network_is_not_joined(case):
    args = _fixture()
    latest = args["concepts"][-1]
    if case == "label":
        latest["label"] = None
    elif case == "changed_label":
        latest["label"] = "Different economic meaning"
    elif case == "type":
        latest["data_type"] = "xbrli:sharesItemType"
    elif case == "period":
        latest["period_type"] = "instant"
    elif case == "owner":
        latest["namespace_uri"] = "https://different-issuer.test/20240201"
    elif case == "parent":
        args["concepts"][-2]["local_name"] = "DifferentParent"
    elif case == "target_role":
        args["relationships"][-1]["target_role_uri"] = "https://issuer.test/role/OtherAxis"
    elif case == "role_binding":
        args["roles"][-1]["filing_id"] = "foreign-filing"
    elif case == "partial_edge":
        args["relationships"].append({**args["relationships"][-1], "role_id": "unresolved-role"})
    elif case == "base_set":
        args["relationships"][-1]["arc_qname"] = None
    elif case == "unknown_arcrole":
        args["relationships"][-1]["arcrole"] = "https://issuer.test/unknown-meaning"
    elif case == "same_filing":
        for collection in ("concepts", "roles", "relationships"):
            for row in args[collection]:
                row["filing_id"] = "filing-1"
        args["filings"] = args["filings"][:1]
    old, new = _values(args)
    assert new["company_canonical_id"] != old["company_canonical_id"]
    assert new["review_required"]


def test_company_scope_is_never_shared_across_issuers():
    first, second = _fixture(), _fixture()
    for filing in second["filings"]:
        filing["cik"] = "0000000002"
    assert _values(first)[1]["company_canonical_id"] != _values(second)[1]["company_canonical_id"]


@pytest.mark.parametrize("structural", [True, False])
def test_label_resource_is_not_structural_evidence_or_structural_failure(structural):
    args = _fixture()
    label_edges = [{**edge, "network_type": "DEF", "arcrole": "http://www.xbrl.org/2003/arcrole/concept-label",
                    "from_raw_concept_id": edge["to_raw_concept_id"], "to_raw_concept_id": "label-resource"}
                   for edge in args["relationships"]]
    args["relationships"] = (args["relationships"] if structural else []) + label_edges
    old, new = _values(args)
    assert (old["company_canonical_id"] == new["company_canonical_id"]) is structural


@pytest.mark.parametrize("changed_parent", [False, True])
def test_custom_axis_and_member_maps_keep_qualified_dimensional_parent(changed_parent):
    args = _fixture()
    for row in args["concepts"]:
        if row["local_name"] == "Parent":
            row.update(local_name="ProductAxis", label="Product", is_axis=True)
        else:
            row.update(local_name="CloudMember", label="Cloud", is_member=True, abstract=True, data_type="domainItemType")
    for edge in args["relationships"]:
        edge.update(network_type="DEF", arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain",
                    link_qname="link:definitionLink", arc_qname="link:definitionArc")
    if changed_parent:
        args["concepts"][-2].update(local_name="GeographyAxis", label="Geography")
    tables = CompanyCanonicalizer().build(**args)
    first, second = tables.company_member_map
    assert (first["company_canonical_id"] == second["company_canonical_id"]) is not changed_parent
    first_axis, second_axis = tables.company_axis_map
    assert (first_axis["company_canonical_id"] == second_axis["company_canonical_id"]) is not changed_parent


@pytest.mark.parametrize("change", [None, "suffix", "lookalike", "unrelated", "target"])
def test_versioned_roles_require_exact_same_filing_namespace_prefix(change):
    args = _fixture()
    for index, role in enumerate(args["roles"]):
        namespace = args["concepts"][index * 2]["namespace_uri"]
        role["role_uri"] = namespace + "/taxonomy/role/Income"
        args["relationships"][index]["target_role_uri"] = namespace + "/taxonomy/role/Detail"
    if change == "suffix":
        args["roles"][-1]["role_uri"] += "Changed"
    elif change == "lookalike":
        args["roles"][-1]["role_uri"] = args["concepts"][-1]["namespace_uri"] + "other/taxonomy/role/Income"
    elif change == "unrelated":
        args["roles"][-1]["role_uri"] = "https://other.test/20240201/taxonomy/role/Income"
    elif change == "target":
        args["relationships"][-1]["target_role_uri"] = "https://other.test/20240201/taxonomy/role/Detail"
    old, new = _values(args)
    assert (old["company_canonical_id"] == new["company_canonical_id"]) is (change is None)
