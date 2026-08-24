from __future__ import annotations

from pathlib import Path

import pytest

from sec_xbrl.traversal.anchor import AnchorTraversal

FILING = "filing_1"
STATEMENT_ROLE = "role_income"
DEF_ROLE = "role_revenue_definition"
MEMBER_ROLE = "role_region_members"
UNRELATED_ROLE = "role_unrelated"


def _role(role_id: str, uri: str, definition: str, category: str = "OTHER") -> dict[str, str]:
    return {
        "filing_id": FILING,
        "role_id": role_id,
        "role_uri": uri,
        "role_definition": definition,
        "role_category": category,
    }


def _edge(
    relationship_id: str,
    network: str,
    role_id: str,
    arcrole: str,
    source: str,
    target: str,
    *,
    order: str = "1",
    target_role_uri: str | None = None,
) -> dict[str, str | None]:
    return {
        "relationship_id": relationship_id,
        "filing_id": FILING,
        "network_type": network,
        "role_id": role_id,
        "arcrole": arcrole,
        "from_raw_concept_id": source,
        "to_raw_concept_id": target,
        "order": order,
        "target_role_uri": target_role_uri,
    }


def _tables() -> dict[str, object]:
    presentation = "http://www.xbrl.org/2003/arcrole/parent-child"
    calculation = "http://www.xbrl.org/2003/arcrole/summation-item"
    dimensional = "http://xbrl.org/int/dim/arcrole/"
    roles = (
        _role(
            STATEMENT_ROLE,
            "http://example.test/role/IncomeStatement",
            "Consolidated Statements of Income",
            "STATEMENT",
        ),
        _role(DEF_ROLE, "http://example.test/role/RevenueDefinition", "Revenue table"),
        _role(MEMBER_ROLE, "http://example.test/role/RegionMembers", "Revenue detail"),
        _role(UNRELATED_ROLE, "http://example.test/role/Unrelated", "Unrelated disclosure"),
    )
    relationships = (
        # PRE identifies display anchors only. It must never be a traversal edge.
        _edge("pre-root", "PRE", STATEMENT_ROLE, presentation, "income_root", "revenue"),
        _edge("pre-sibling", "PRE", STATEMENT_ROLE, presentation, "revenue", "pre_only"),
        # CAL runs only in this stated direction.
        _edge("cal-child", "CAL", STATEMENT_ROLE, calculation, "revenue", "cost_of_revenue"),
        _edge("cal-parent", "CAL", STATEMENT_ROLE, calculation, "gross_profit", "revenue"),
        # DEF transitions from its anchor role to a targetRole and reaches a leaf.
        _edge(
            "def-all",
            "DEF",
            DEF_ROLE,
            dimensional + "all",
            "revenue",
            "region_hypercube",
            target_role_uri="http://example.test/role/RegionMembers",
        ),
        _edge(
            "def-axis",
            "DEF",
            MEMBER_ROLE,
            dimensional + "hypercube-dimension",
            "region_hypercube",
            "region_axis",
        ),
        _edge(
            "def-domain",
            "DEF",
            MEMBER_ROLE,
            dimensional + "dimension-domain",
            "region_axis",
            "region_domain",
        ),
        _edge(
            "def-member",
            "DEF",
            MEMBER_ROLE,
            dimensional + "domain-member",
            "region_domain",
            "north_america_member",
        ),
        # A cycle must not make this traversal terminate by a fixed depth limit.
        _edge(
            "def-cycle",
            "DEF",
            MEMBER_ROLE,
            dimensional + "domain-member",
            "north_america_member",
            "region_hypercube",
            order="2",
        ),
        # This edge shares no anchor/targetRole connection and must remain isolated.
        _edge(
            "def-unrelated",
            "DEF",
            UNRELATED_ROLE,
            dimensional + "domain-member",
            "unrelated_domain",
            "unrelated_member",
        ),
    )
    facts = (
        {
            "filing_id": FILING,
            "fact_id": "fact-revenue-by-region",
            "raw_concept_id": "revenue",
            "reported_or_derived": "REPORTED",
            "is_nil": False,
        },
        {
            "filing_id": FILING,
            "fact_id": "fact-north-america",
            "raw_concept_id": "north_america_member",
            "reported_or_derived": "REPORTED",
            "is_nil": False,
        },
    )
    dimensions = (
        {
            "fact_id": "fact-revenue-by-region",
            "axis_raw_concept_id": "region_axis",
            "member_raw_concept_id": "north_america_member",
        },
    )
    concepts = (
        {"raw_concept_id": "income_root", "abstract": True},
        {"raw_concept_id": "revenue", "abstract": False},
        {"raw_concept_id": "pre_only", "abstract": False},
    )
    return {"roles": roles, "relationships": relationships, "facts": facts, "dimension_facts": dimensions, "concepts": concepts}


def _revenue_evidence() -> tuple[dict[str, object], ...]:
    result = AnchorTraversal().traverse(**_tables())
    return tuple(row for row in result.evidence if row["anchor_raw_concept_id"] == "revenue")


def test_major_statement_anchor_prioritizes_direct_dimensional_fact() -> None:
    result = AnchorTraversal().traverse(**_tables())

    assert {(row["statement_type"], row["raw_concept_id"]) for row in result.anchors} >= {
        ("IS", "revenue")
    }
    evidence = _revenue_evidence()
    direct = next(row for row in evidence if row["evidence_type"] == "DIRECT_DIMENSION")
    first_graph_edge = next(row for row in evidence if row["source_relationship_id"] is not None)
    assert direct["fact_id"] == "fact-revenue-by-region"
    assert direct["axis_raw_concept_id"] == "region_axis"
    assert direct["member_raw_concept_id"] == "north_america_member"
    assert direct["discovery_order"] < first_graph_edge["discovery_order"]


def test_major_statement_role_is_recognized_from_its_definition_not_only_m3_category() -> None:
    tables = _tables()
    tables["roles"] = (
        _role(
            STATEMENT_ROLE,
            "http://example.test/role/BalanceSheet",
            "Consolidated Balance Sheets",
            "OTHER",
        ),
        *tables["roles"][1:],
    )

    result = AnchorTraversal().traverse(**tables)

    assert any(
        row["statement_type"] == "BS" and row["raw_concept_id"] == "revenue"
        for row in result.anchors
    )


def test_definition_follows_target_role_to_leaf_and_stops_cycle() -> None:
    evidence = _revenue_evidence()
    by_relationship = {row["source_relationship_id"]: row for row in evidence}

    assert by_relationship["def-member"]["evidence_type"] == "DEFINITION_MEMBER"
    assert by_relationship["def-member"]["to_raw_concept_id"] == "north_america_member"
    assert by_relationship["def-cycle"]["to_raw_concept_id"] == "region_hypercube"
    assert sum(row["source_relationship_id"] == "def-cycle" for row in evidence) == 1
    transition = next(
        row
        for row in evidence
        if row["evidence_type"] == "ROLE_EXPANSION"
        and row["target_role_uri"] == "http://example.test/role/RegionMembers"
    )
    assert transition["role_id"] == MEMBER_ROLE


def test_calculation_is_parent_to_child_pre_does_not_expand_and_roles_remain_separate() -> None:
    evidence = _revenue_evidence()
    ids = {row["source_relationship_id"] for row in evidence}

    assert "cal-child" in ids
    assert "cal-parent" not in ids
    assert "pre-sibling" not in ids
    assert all(row["network_type"] != "PRE" for row in evidence)
    assert "def-unrelated" not in ids


def test_materialization_preserves_separate_anchor_and_evidence_tables(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    result = AnchorTraversal().traverse(**_tables())

    result.write_parquet(tmp_path)

    assert {path.stem for path in tmp_path.glob("*.parquet")} == {"anchor", "traversal_evidence"}
    evidence = pl.read_parquet(tmp_path / "traversal_evidence.parquet")
    assert "DIRECT_DIMENSION" in evidence["evidence_type"].to_list()
    with pytest.raises(Exception, match="snapshot already exists"):
        result.write_parquet(tmp_path)
