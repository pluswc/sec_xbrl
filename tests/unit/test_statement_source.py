from sec_xbrl.analytics.statement_source import member_paths, presentation_paths


def concept(key):
    return {"raw_concept_id": key, "qname": key, "abstract": key == "axis"}


def relation(a, b, n, *, role="r", target=None, link="link", usable=True):
    return {"network_type": "DEF", "filing_id": "filing", "role_id": role, "role_uri": role,
            "arcrole": "http://x/dimension-domain" if a == "axis" else "http://x/domain-member",
            "link_qname": link, "arc_qname": "arc", "from_raw_concept_id": a, "to_raw_concept_id": b,
            "relationship_id": str(n), "order": str(n), "target_role_uri": target, "usable": usable}


def test_deep_target_role_and_baseset_isolation():
    concepts = {x: concept(x) for x in ["axis", *map(str, range(120)), "foreign"]}
    arcs = [relation("axis", "0", 0, target="other")]
    arcs += [relation(str(n), str(n+1), n+1, role="other") for n in range(119)]
    arcs += [relation("0", "foreign", 200, role="other", link="different-base")]
    facts = {"f": {"fact_id": "f", "scope": {"dimensions": [{"axis": "axis", "member": "119"}]}}}
    paths = member_paths(arcs, concepts, facts)
    assert max(p["depth"] for p in paths) == 120
    assert not any(p["member_id"] == "foreign" for p in paths)
    assert next(p for p in paths if p["member_id"] == "119")["fact_ids"] == ["f"]


def test_diamond_cycle_unusable_and_no_aggregation():
    concepts = {x: concept(x) for x in ["axis", "a", "b", "c", "d"]}
    arcs = [relation("axis", "a", 0), relation("a", "b", 1), relation("a", "c", 2),
            relation("b", "d", 3), relation("c", "d", 4), relation("d", "a", 5)]
    facts = {"f": {"fact_id": "f", "scope": {"dimensions": [{"axis": "axis", "member": "d"}]}}}
    paths = member_paths(arcs, concepts, facts)
    assert len([p for p in paths if p["member_id"] == "d"]) == 2
    assert all(p["aggregation_status"] == "NOT_AUTHORIZED" for p in paths)
    assert sum(p["cycle"] for p in paths) == 2
    arcs[3]["usable"] = False
    paths = member_paths(arcs, concepts, facts)
    assert any(not p["usable"] and not p["fact_ids"] for p in paths if p["member_id"] == "d")


def test_pre_is_separate_ordered_paths_with_alternative_basesets():
    concepts = {x: concept(x) for x in ["axis", "a", "b"]}
    roles = {"r": {"role_definition": "100 - Statement - Consolidated Statements of Income", "role_category": "STATEMENT"}}
    arcs = [{**relation("axis", "b", 2), "network_type": "PRE"},
            {**relation("axis", "a", 1), "network_type": "PRE"}]
    rows = presentation_paths(arcs, concepts, roles)
    assert [r["raw_concept_id"] for r in rows] == ["axis", "a", "b"]
    assert all(r["relationship_type"] == "PRE_DISPLAY" for r in rows)


def test_unusable_member_does_not_disable_usable_descendant():
    concepts = {x: concept(x) for x in ["axis", "a", "b"]}
    arcs = [relation("axis", "a", 0, usable=False), relation("a", "b", 1)]
    facts = {"f": {"fact_id": "f", "scope": {"dimensions": [{"axis": "axis", "member": "b"}]}}}
    paths = member_paths(arcs, concepts, facts)
    assert next(p for p in paths if p["member_id"] == "a")["usable"] is False
    assert next(p for p in paths if p["member_id"] == "b")["fact_ids"] == ["f"]
