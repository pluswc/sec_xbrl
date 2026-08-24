from __future__ import annotations

from pathlib import Path

import pytest

from sec_xbrl.disclosure.safety_net import DisclosureSafetyNet


FILING = "filing_1"
REVENUE_TABLE = "role_revenue_table"
DEBT_DETAIL = "role_debt_detail"
TITLE_ONLY = "role_title_only"
UNRELATED = "role_unrelated"


def _role(role_id: str, definition: str, category: str) -> dict[str, object]:
    return {
        "filing_id": FILING,
        "role_id": role_id,
        "role_uri": f"https://example.test/role/{role_id}",
        "role_definition": definition,
        "role_category": category,
    }


def _edge(role_id: str, source: str, target: str) -> dict[str, object]:
    return {
        "filing_id": FILING,
        "relationship_id": f"edge-{role_id}-{source}-{target}",
        "role_id": role_id,
        "network_type": "PRE",
        "from_raw_concept_id": source,
        "to_raw_concept_id": target,
    }


def _concept(concept_id: str, label: str, *, data_type: str = "string") -> dict[str, object]:
    return {
        "filing_id": FILING,
        "raw_concept_id": concept_id,
        "qname": f"acme:{concept_id}",
        "local_name": concept_id,
        "label": label,
        "documentation": label,
        "data_type": data_type,
    }


def _fact(concept_id: str, *, value_text: str | None = None, locator: str = "ix:1") -> dict[str, object]:
    return {
        "filing_id": FILING,
        "fact_id": f"fact-{concept_id}",
        "raw_concept_id": concept_id,
        "value_text": value_text,
        "source_document": "acme-2025-10k.htm",
        "source_locator": locator,
        "reported_or_derived": "REPORTED",
        "is_nil": False,
    }


def _records() -> dict[str, object]:
    return {
        "roles": (
            # No anchor data is provided at all: this P0 must still be found.
            _role(REVENUE_TABLE, "Revenue Recognition (Tables)", "TABLE"),
            _role(DEBT_DETAIL, "Debt and Credit Facilities (Detail)", "DETAIL"),
            _role(TITLE_ONLY, "Goodwill and Impairment", "DISCLOSURE"),
            _role(UNRELATED, "Other note", "DISCLOSURE"),
        ),
        "relationships": (
            _edge(REVENUE_TABLE, "revenue_root", "revenue_text"),
            _edge(DEBT_DETAIL, "debt_root", "debt_balance"),
            _edge(TITLE_ONLY, "title_root", "plain_concept"),
            _edge(UNRELATED, "other_root", "other_concept"),
        ),
        "concepts": (
            _concept("revenue_root", "Revenue from contracts"),
            _concept("revenue_text", "Revenue recognition policy", data_type="textBlockItemType"),
            _concept("debt_root", "Debt"),
            _concept("debt_balance", "Borrowings under credit facility"),
            _concept("title_root", "Other assets"),
            _concept("plain_concept", "Plain disclosure"),
            _concept("other_root", "Other note"),
            _concept("other_concept", "Unclassified item"),
        ),
        "facts": (
            _fact("revenue_text", value_text="Revenue recognition and disaggregation by product.", locator="ix:revenue"),
            _fact("debt_balance", value_text=None, locator="ix:debt"),
            _fact("plain_concept", value_text="Generic narrative with no topic terms.", locator="ix:title"),
        ),
    }


def test_p0_discovery_is_independent_of_anchor_and_title_needs_raw_corroboration() -> None:
    result = DisclosureSafetyNet().build(**_records())

    revenue = next(
        row
        for row in result.disclosure_index
        if row["role_id"] == REVENUE_TABLE and row["critical_topic"] == "REVENUE_RECOGNITION"
    )
    assert revenue["priority"] == "P0"
    assert revenue["deep_scan_required"] is True
    assert revenue["has_role_title_signal"] is True
    assert revenue["has_concept_signal"] is True
    assert revenue["has_text_block_signal"] is True
    # The title-only Goodwill role has no corroborating raw concept/fact/text signal.
    assert not any(row["role_id"] == TITLE_ONLY and row["priority"] == "P0" for row in result.disclosure_index)
    assert next(row for row in result.disclosure_index if row["role_id"] == TITLE_ONLY)["priority"] == "UNCLASSIFIED"


def test_inventory_and_evidence_preserve_table_detail_and_text_fact_provenance() -> None:
    result = DisclosureSafetyNet().build(**_records())

    inventory = {row["role_id"]: row for row in result.role_inventory}
    assert inventory[REVENUE_TABLE]["has_table_evidence"] is True
    assert inventory[REVENUE_TABLE]["text_block_count"] == 1
    assert inventory[DEBT_DETAIL]["has_detail_evidence"] is True
    debt = next(
        row
        for row in result.disclosure_index
        if row["role_id"] == DEBT_DETAIL and row["critical_topic"] == "DEBT_BORROWING"
    )
    assert debt["priority"] == "P0"
    text = next(
        row
        for row in result.disclosure_evidence
        if row["role_id"] == REVENUE_TABLE and row["signal_type"] == "TEXT_BLOCK"
    )
    assert text["fact_id"] == "fact-revenue_text"
    assert text["source_document"] == "acme-2025-10k.htm"
    assert text["source_locator"] == "ix:revenue"
    assert any(
        row["role_id"] == REVENUE_TABLE and row["signal_type"] == "TABLE_ROLE"
        for row in result.disclosure_evidence
    )
    assert any(
        row["role_id"] == DEBT_DETAIL and row["signal_type"] == "DETAIL_ROLE"
        for row in result.disclosure_evidence
    )


def test_unclassified_and_p1_p2_priority_are_explicit() -> None:
    records = _records()
    records["roles"] = (*records["roles"], _role("role_leases", "Leases", "DISCLOSURE"), _role("role_policy", "Accounting policies", "POLICY"))
    records["relationships"] = (*records["relationships"], _edge("role_leases", "lease_root", "lease_concept"), _edge("role_policy", "policy_root", "policy_concept"))
    records["concepts"] = (*records["concepts"], _concept("lease_root", "Lease liabilities"), _concept("lease_concept", "Lease"), _concept("policy_root", "Accounting policy"), _concept("policy_concept", "Critical accounting estimates"))

    result = DisclosureSafetyNet().build(**records)

    priority_by_role = {row["role_id"]: row["priority"] for row in result.disclosure_index}
    assert priority_by_role[UNRELATED] == "UNCLASSIFIED"
    assert priority_by_role["role_leases"] == "P1"
    assert priority_by_role["role_policy"] == "P2"
    assert next(row for row in result.disclosure_index if row["role_id"] == "role_policy")["deep_scan_required"] is False


def test_materialization_is_separate_and_immutable(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    result = DisclosureSafetyNet().build(**_records())

    result.write_parquet(tmp_path)

    assert {path.stem for path in tmp_path.glob("*.parquet")} == {
        "role_inventory",
        "disclosure_index",
        "disclosure_evidence",
    }
    evidence = pl.read_parquet(tmp_path / "disclosure_evidence.parquet")
    assert {"source_document", "source_locator", "source_role_uri"} <= set(evidence.columns)
    with pytest.raises(Exception, match="snapshot already exists"):
        result.write_parquet(tmp_path)
