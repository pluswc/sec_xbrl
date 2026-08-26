from __future__ import annotations

from sec_xbrl.discovery.statement import CompanyDisclosureDiscovery

FILING = "filing-aapl-like"
PARENT_CHILD = "http://www.xbrl.org/2003/arcrole/parent-child"
SUMMATION_ITEM = "http://www.xbrl.org/2003/arcrole/summation-item"
DIM = "http://xbrl.org/int/dim/arcrole/"


def _concept(identifier: str, *, label: str | None = None, abstract: bool = False) -> dict[str, object]:
    return {
        "filing_id": FILING,
        "raw_concept_id": identifier,
        "qname": f"example:{identifier}",
        "label": label or identifier,
        "taxonomy_family": "company-extension" if identifier.startswith("custom_") else "us-gaap",
        "is_standard": not identifier.startswith("custom_"),
        "is_custom": identifier.startswith("custom_"),
        "period_type": "duration",
        "abstract": abstract,
    }


def _role(identifier: str, title: str, category: str) -> dict[str, str]:
    return {
        "filing_id": FILING,
        "role_id": identifier,
        "role_uri": f"http://example.test/role/{identifier}",
        "role_definition": title,
        "role_category": category,
    }


def _edge(
    identifier: str, network: str, role: str, arcrole: str, source: str, target: str, **kwargs: object
) -> dict[str, object]:
    return {
        "filing_id": FILING,
        "relationship_id": identifier,
        "network_type": network,
        "role_id": role,
        "arcrole": arcrole,
        "from_raw_concept_id": source,
        "to_raw_concept_id": target,
        "order": kwargs.get("order", "1"),
        "target_role_uri": kwargs.get("target_role_uri"),
    }


def _tables() -> dict[str, object]:
    statement = "statement"
    revenue_note = "revenue_note"
    geography_def = "geography_def"
    label_only = "label_only"
    concepts = (
        _concept("income_root", abstract=True),
        _concept("revenue", label="Revenue"),
        _concept("cost_of_revenue", label="Cost of Revenue"),
        _concept("gross_profit", label="Gross Profit"),
        _concept("geography_hypercube", abstract=True),
        _concept("geography_axis", abstract=True),
        _concept("geography_domain", abstract=True),
        _concept("americas_member", label="Americas"),
        _concept("europe_member", label="Europe"),
        _concept("unrelated_revenue_word", label="Revenue-looking but unrelated"),
    )
    roles = (
        _role(statement, "Statement - Consolidated Statements of Operations", "STATEMENT"),
        _role(revenue_note, "Disclosure - Revenue by Geography", "DISCLOSURE"),
        _role(geography_def, "Disclosure - Revenue by Geography (Definition)", "DETAIL"),
        _role(label_only, "Disclosure - Revenue Analysis", "DISCLOSURE"),
    )
    relationships = (
        _edge("pre-income-root", "PRE", statement, PARENT_CHILD, "income_root", "revenue", order="1"),
        _edge("pre-income-cost", "PRE", statement, PARENT_CHILD, "revenue", "cost_of_revenue", order="2"),
        _edge("pre-income-gross", "PRE", statement, PARENT_CHILD, "revenue", "gross_profit", order="3"),
        # The same raw Revenue concept is actual evidence for note expansion.
        _edge("pre-note-revenue", "PRE", revenue_note, PARENT_CHILD, "revenue", "unrelated_revenue_word"),
        _edge("cal-revenue-cost", "CAL", statement, SUMMATION_ITEM, "revenue", "cost_of_revenue"),
        _edge(
            "def-all",
            "DEF",
            geography_def,
            DIM + "all",
            "revenue",
            "geography_hypercube",
            target_role_uri="http://example.test/role/geography_def",
        ),
        _edge("def-axis", "DEF", geography_def, DIM + "hypercube-dimension", "geography_hypercube", "geography_axis"),
        _edge("def-domain", "DEF", geography_def, DIM + "dimension-domain", "geography_axis", "geography_domain"),
        _edge("def-americas", "DEF", geography_def, DIM + "domain-member", "geography_domain", "americas_member"),
        _edge("def-europe", "DEF", geography_def, DIM + "domain-member", "geography_domain", "europe_member", order="2"),
    )
    facts = (
        {"filing_id": FILING, "fact_id": "revenue-total", "raw_concept_id": "revenue", "context_id": "q1", "unit_id": "usd", "value_numeric": "100", "reported_or_derived": "REPORTED", "is_nil": False},
        {"filing_id": FILING, "fact_id": "revenue-americas", "raw_concept_id": "revenue", "context_id": "q1-us", "unit_id": "usd", "value_numeric": "60", "reported_or_derived": "REPORTED", "is_nil": False},
        {"filing_id": FILING, "fact_id": "cost", "raw_concept_id": "cost_of_revenue", "context_id": "q1", "unit_id": "usd", "value_numeric": "40", "reported_or_derived": "REPORTED", "is_nil": False},
    )
    contexts = (
        {"filing_id": FILING, "context_id": "q1", "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-03-31", "instant_date": None, "duration_days": 89},
        {"filing_id": FILING, "context_id": "q1-us", "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-03-31", "instant_date": None, "duration_days": 89},
    )
    dimensions = (
        {"fact_id": "revenue-americas", "axis_raw_concept_id": "geography_axis", "member_raw_concept_id": "americas_member", "dimension_type": "EXPLICIT", "is_default_member": False},
    )
    return {
        "filing": ({"filing_id": FILING, "cik": "0000000001", "accession": "0000000001-25-000001"},),
        "concepts": concepts,
        "contexts": contexts,
        "facts": facts,
        "dimension_facts": dimensions,
        "roles": roles,
        "relationships": relationships,
    }


def test_discovers_income_statement_hierarchy_direct_and_structural_members() -> None:
    result = CompanyDisclosureDiscovery().discover(statement_type="IS", **_tables())

    assert {row["raw_concept_id"] for row in result.anchors} == {"revenue", "cost_of_revenue"}
    assert [(row["parent_raw_concept_id"], row["child_raw_concept_id"]) for row in result.statement_hierarchy] == [
        ("income_root", "revenue"),
        ("revenue", "cost_of_revenue"),
        ("revenue", "gross_profit"),
    ]
    direct = result.direct_dimensions[0]
    assert direct["member_usage"] == "DIRECTLY_REPORTED"
    assert direct["axis_label"] == "geography_axis"
    assert direct["member_label"] == "Americas"
    members = {row["member_raw_concept_id"]: row["member_status"] for row in result.structural_members}
    assert members == {"americas_member": "USED_BY_REPORTED_FACT", "europe_member": "STRUCTURAL_ONLY"}


def test_expands_roles_only_on_xbrl_concept_evidence_not_matching_labels() -> None:
    result = CompanyDisclosureDiscovery().discover(statement_type="IS", **_tables())

    expanded = {
        (row["role_id"], reason)
        for row in result.related_roles
        for reason in row["role_expansion_reasons"]
    }
    assert ("revenue_note", "SAME_ANCHOR_CONCEPT") in expanded
    assert ("geography_def", "SAME_ANCHOR_CONCEPT") in expanded
    revenue_note_rows = [row for row in result.related_roles if row["role_id"] == "revenue_note"]
    assert len(revenue_note_rows) == len({row["anchor_raw_concept_id"] for row in revenue_note_rows})
    assert all(row["role_id"] != "label_only" for row in result.related_roles)
    assert all("LABEL_MATCH" not in row["role_expansion_reasons"] for row in result.related_roles)


def test_period_evidence_preserves_observation_and_does_not_claim_change() -> None:
    result = CompanyDisclosureDiscovery().discover(statement_type="IS", **_tables())

    total = next(row for row in result.period_change_evidence if row["fact_id"] == "revenue-total")
    assert total["dimension_key"] == (None, None)
    assert total["period_kind"] == "DURATION"
    assert total["change_status"] == "OBSERVED_ONLY"
    assert total["change_value"] is None
