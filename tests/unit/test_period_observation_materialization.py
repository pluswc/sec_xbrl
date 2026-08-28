from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.longitudinal import PeriodObservationMaterializer


def _filing(company: str = "0000320193", year: int = 2025) -> dict[str, object]:
    return {
        "filing_id": f"{company}-q3-{year}", "cik": company, "accession": f"{company}-{year}-q3",
        "form": "10-Q", "filed_date": f"{year}-11-01", "report_date": f"{year}-09-27",
        "document_fiscal_year_focus": str(year), "fiscal_year_end": "--09-27",
    }


def _snapshot(company: str = "0000320193", year: int = 2025) -> dict[str, object]:
    filing = _filing(company, year)
    filing_id = str(filing["filing_id"])
    contexts = (
        {"context_id": f"qtd-{year}", "filing_id": filing_id, "period_kind": "DURATION", "start_date": f"{year}-06-29", "end_date": f"{year}-09-27", "instant_date": None, "duration_days": 90},
        {"context_id": f"ytd-{year}", "filing_id": filing_id, "period_kind": "DURATION", "start_date": f"{year}-01-01", "end_date": f"{year}-09-27", "instant_date": None, "duration_days": 269},
        {"context_id": f"instant-{year}", "filing_id": filing_id, "period_kind": "INSTANT", "start_date": None, "end_date": None, "instant_date": f"{year}-09-27", "duration_days": None},
    )
    concepts = (
        {"raw_concept_id": "revenue", "filing_id": filing_id, "qname": "us-gaap:Revenue", "namespace_uri": "http://fasb.org/us-gaap", "local_name": "Revenue", "period_type": "duration", "data_type": "monetaryItemType"},
        {"raw_concept_id": "assets", "filing_id": filing_id, "qname": "us-gaap:Assets", "namespace_uri": "http://fasb.org/us-gaap", "local_name": "Assets", "period_type": "instant", "data_type": "monetaryItemType"},
        {"raw_concept_id": "geo-axis", "filing_id": filing_id, "qname": "ex:GeoAxis", "namespace_uri": "http://example.test", "local_name": "GeoAxis", "period_type": "duration"},
        {"raw_concept_id": "us-member", "filing_id": filing_id, "qname": "ex:USMember", "namespace_uri": "http://example.test", "local_name": "USMember", "period_type": "duration"},
        {"raw_concept_id": "eps", "filing_id": filing_id, "qname": "us-gaap:EarningsPerShareDiluted", "namespace_uri": "http://fasb.org/us-gaap", "local_name": "EarningsPerShareDiluted", "period_type": "duration"},
    )
    facts = (
        {"fact_id": f"revenue-qtd-{year}", "filing_id": filing_id, "raw_concept_id": "revenue", "context_id": f"qtd-{year}", "unit_id": "usd", "value_numeric": "100", "value_text": None, "is_nil": False, "source_document": "x.htm", "source_locator": "f1"},
        {"fact_id": f"revenue-ytd-{year}", "filing_id": filing_id, "raw_concept_id": "revenue", "context_id": f"ytd-{year}", "unit_id": "usd", "value_numeric": "270", "value_text": None, "is_nil": False, "source_document": "x.htm", "source_locator": "f2"},
        {"fact_id": f"assets-{year}", "filing_id": filing_id, "raw_concept_id": "assets", "context_id": f"instant-{year}", "unit_id": "usd", "value_numeric": "500", "value_text": None, "is_nil": False, "source_document": "x.htm", "source_locator": "f3"},
        {"fact_id": f"eps-{year}", "filing_id": filing_id, "raw_concept_id": "eps", "context_id": f"qtd-{year}", "unit_id": "usd-per-share", "value_numeric": "2", "value_text": None, "is_nil": False, "source_document": "x.htm", "source_locator": "f4"},
    )
    return {"filing": filing, "concepts": concepts, "contexts": contexts, "units": ({"unit_id": "usd", "filing_id": filing_id, "numerator_measures": "iso4217:USD", "denominator_measures": None}, {"unit_id": "usd-per-share", "filing_id": filing_id, "numerator_measures": "iso4217:USD", "denominator_measures": "xbrli:shares"}), "facts": facts, "dimension_facts": ({"fact_id": f"revenue-qtd-{year}", "axis_raw_concept_id": "geo-axis", "member_raw_concept_id": "us-member", "typed_member": None, "dimension_type": "EXPLICIT", "is_default_member": False},)}


def test_materializes_each_eligible_fact_with_full_lineage_and_class_identity() -> None:
    snapshot = _snapshot()
    original = deepcopy(snapshot)
    result = PeriodObservationMaterializer().materialize(**snapshot)

    assert snapshot == original
    assert result.exclusions == ()
    assert result.accounted_source_fact_count == len(snapshot["facts"])
    by_fact = {row["source_fact_id"]: row for row in result.observations}
    qtd, ytd, instant = by_fact["revenue-qtd-2025"], by_fact["revenue-ytd-2025"], by_fact["assets-2025"]
    assert qtd["period_class"] == "QTD_3M"
    assert ytd["period_class"] == "YTD_9M"
    assert instant["period_class"] == "INSTANT"
    assert qtd["raw_series_identity"] != ytd["raw_series_identity"]
    assert qtd["dimension_signature"] == (("geo-axis", "us-member", None, "EXPLICIT", False),)
    assert {"source_fact_id", "source_filing_id", "context_id", "unit_id", "raw_concept_qname", "classification_rule_version"} <= qtd.keys()


def test_malformed_l1_references_are_explicit_exclusions_not_silent_drops() -> None:
    snapshot = _snapshot()
    facts = list(snapshot["facts"])
    facts.append({"fact_id": "missing-context", "filing_id": snapshot["filing"]["filing_id"], "raw_concept_id": "revenue", "context_id": "missing", "unit_id": "usd"})
    snapshot["facts"] = tuple(facts)
    result = PeriodObservationMaterializer().materialize(**snapshot)

    assert result.accounted_source_fact_count == len(facts)
    assert [(row["source_fact_id"], row["exclusion_reason"]) for row in result.exclusions] == [("missing-context", "MISSING_OR_UNRESOLVED_CONTEXT")]


def test_q4_requires_explicit_additive_policy_and_never_derives_eps() -> None:
    snapshot = _snapshot()
    filing = dict(snapshot["filing"], form="10-K")
    contexts = list(snapshot["contexts"])
    contexts.extend((
        {"context_id": "fy", "filing_id": filing["filing_id"], "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-12-31", "instant_date": None, "duration_days": 364},
        {"context_id": "ytd9", "filing_id": filing["filing_id"], "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-09-30", "instant_date": None, "duration_days": 272},
    ))
    facts = (
        {"fact_id": "fy", "filing_id": filing["filing_id"], "raw_concept_id": "revenue", "context_id": "fy", "unit_id": "usd", "value_numeric": "1000", "is_nil": False},
        {"fact_id": "ytd9", "filing_id": filing["filing_id"], "raw_concept_id": "revenue", "context_id": "ytd9", "unit_id": "usd", "value_numeric": "750", "is_nil": False},
    )
    no_policy = PeriodObservationMaterializer().materialize(**{**snapshot, "filing": filing, "contexts": tuple(contexts), "facts": facts})
    assert len(no_policy.observations) == 2
    policy = {fact_id: {"canonical_concept_id": "revenue", "is_additive": True, "value_kind": "ADDITIVE_AMOUNT", "semantic_review_state": "REVIEWED_ADDITIVE_AMOUNT", "structural_version": "v1", "recast_version": None, "comparability_flag": "COMPATIBLE"} for fact_id in ("fy", "ytd9")}
    result = PeriodObservationMaterializer().materialize(**{**snapshot, "filing": filing, "contexts": tuple(contexts), "facts": facts}, q4_policy_by_fact_id=policy, source_snapshot_id="fixture/k25")
    derived = [row for row in result.observations if row["reported_or_derived"] == "DERIVED"]
    assert len(derived) == 1
    assert derived[0]["value_numeric"] == "250"
    assert derived[0]["formula"] == "FY - YTD_9M"
    assert derived[0]["source_fact_ids"] == ("fy", "ytd9")
    assert derived[0]["source_fact_id"] is None
    assert derived[0]["source_snapshot_id"] == "fixture/k25"
    assert derived[0]["context_start_date"] == "2025-10-01"
    assert derived[0]["context_end_date"] == "2025-12-31"
    assert derived[0]["period_key"] == "2025-10-01/2025-12-31"


def test_q4_rejects_malicious_policy_for_eps_shares_ratio_margin_and_average() -> None:
    snapshot = _snapshot()
    filing = dict(snapshot["filing"], form="10-K")
    filing_id = str(filing["filing_id"])
    contexts = (
        {"context_id": "fy", "filing_id": filing_id, "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-12-31", "duration_days": 364},
        {"context_id": "ytd9", "filing_id": filing_id, "period_kind": "DURATION", "start_date": "2025-01-01", "end_date": "2025-09-30", "duration_days": 272},
    )
    concepts = (
        {"raw_concept_id": "revenue", "filing_id": filing_id, "qname": "us-gaap:Revenue", "period_type": "duration", "data_type": "monetaryItemType"},
        {"raw_concept_id": "eps", "filing_id": filing_id, "qname": "us-gaap:EarningsPerShareDiluted", "period_type": "duration", "data_type": "perShareItemType"},
        {"raw_concept_id": "shares", "filing_id": filing_id, "qname": "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", "period_type": "duration", "data_type": "sharesItemType"},
        {"raw_concept_id": "margin", "filing_id": filing_id, "qname": "example:OperatingMargin", "period_type": "duration", "data_type": "percentItemType"},
        {"raw_concept_id": "average", "filing_id": filing_id, "qname": "example:AverageSellingPrice", "period_type": "duration", "data_type": "monetaryItemType"},
    )
    units = (
        {"unit_id": "usd", "filing_id": filing_id, "numerator_measures": "iso4217:USD", "denominator_measures": None},
        {"unit_id": "usd-per-share", "filing_id": filing_id, "numerator_measures": "iso4217:USD", "denominator_measures": "xbrli:shares"},
        {"unit_id": "shares", "filing_id": filing_id, "numerator_measures": "xbrli:shares", "denominator_measures": None},
        {"unit_id": "pure", "filing_id": filing_id, "numerator_measures": "xbrli:pure", "denominator_measures": None},
    )
    facts = tuple(
        {"fact_id": f"{concept}-{period}", "filing_id": filing_id, "raw_concept_id": concept, "context_id": period, "unit_id": unit, "value_numeric": value, "is_nil": False}
        for concept, unit, value in (("revenue", "usd", "1000"), ("eps", "usd-per-share", "4"), ("shares", "shares", "200"), ("margin", "pure", "50"), ("average", "usd", "12"))
        for period in ("fy", "ytd9")
    )
    malicious = {fact["fact_id"]: {"canonical_concept_id": fact["raw_concept_id"], "is_additive": True, "value_kind": "ADDITIVE_AMOUNT", "semantic_review_state": "REVIEWED_ADDITIVE_AMOUNT", "structural_version": "v1", "recast_version": None, "comparability_flag": "COMPATIBLE"} for fact in facts}
    result = PeriodObservationMaterializer().materialize(filing=filing, concepts=concepts, contexts=contexts, units=units, facts=facts, q4_policy_by_fact_id=malicious)

    derived = [row for row in result.observations if row["reported_or_derived"] == "DERIVED"]
    assert [row["raw_concept_id"] for row in derived] == ["revenue"]


def test_foreign_layer1_references_are_explicitly_excluded() -> None:
    snapshot = _snapshot()
    concepts = list(snapshot["concepts"])
    concepts[0] = {**concepts[0], "filing_id": "other-filing"}
    result = PeriodObservationMaterializer().materialize(**{**snapshot, "concepts": tuple(concepts)})
    exclusions = {row["source_fact_id"]: row["exclusion_reason"] for row in result.exclusions}

    assert exclusions["revenue-qtd-2025"] == "CROSS_FILING_CONCEPT_REFERENCE"
    assert exclusions["revenue-ytd-2025"] == "CROSS_FILING_CONCEPT_REFERENCE"


@pytest.mark.parametrize(
    ("table", "index", "expected_reason"),
    (
        ("concepts", 0, "MISSING_CONCEPT_REFERENCE_FILING_ID"),
        ("contexts", 0, "MISSING_CONTEXT_REFERENCE_FILING_ID"),
        ("units", 0, "MISSING_UNIT_REFERENCE_FILING_ID"),
        ("concepts", 2, "MISSING_DIMENSION_REFERENCE_FILING_ID"),
        ("concepts", 3, "MISSING_DIMENSION_REFERENCE_FILING_ID"),
    ),
)
def test_referenced_l1_rows_without_filing_identity_are_explicitly_excluded(
    table: str, index: int, expected_reason: str
) -> None:
    snapshot = _snapshot()
    rows = list(snapshot[table])
    rows[index] = {key: value for key, value in rows[index].items() if key != "filing_id"}
    result = PeriodObservationMaterializer().materialize(**{**snapshot, table: tuple(rows)})
    exclusions = {row["source_fact_id"]: row["exclusion_reason"] for row in result.exclusions}

    assert exclusions["revenue-qtd-2025"] == expected_reason


def test_aapl_nvda_tsla_three_year_fixture_surface_is_completely_accounted_for() -> None:
    companies = ("0000320193", "0001045810", "0001318605")
    total = 0
    for company in companies:
        for year in (2023, 2024, 2025):
            snapshot = _snapshot(company, year)
            result = PeriodObservationMaterializer().materialize(**snapshot)
            total += len(snapshot["facts"])
            assert result.accounted_source_fact_count == len(snapshot["facts"])
            assert not result.exclusions
    assert total == 36
