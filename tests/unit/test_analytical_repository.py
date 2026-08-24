from __future__ import annotations

from copy import deepcopy

import pytest

from sec_xbrl.analytics import (
    AnalyticalRepository,
    CompanyAmbiguousError,
    CompanyNotFoundError,
    FactNotFoundError,
)


def _repository() -> AnalyticalRepository:
    return AnalyticalRepository(
        companies=(
            {"cik": "0000320193", "ticker": "AAPL", "name": "Apple Inc.", "company_canonical_id": "company:aapl"},
            {"cik": "0000789019", "ticker": "MSFT", "name": "Microsoft Corporation", "company_canonical_id": "company:msft"},
            {"cik": "0001652044", "ticker": "GOOG", "name": "Alphabet Inc.", "company_canonical_id": "company:goog"},
            {"cik": "0001652045", "ticker": "GOOGL", "name": "Alphabet Inc.", "company_canonical_id": "company:googl"},
        ),
        filings=(
            {"filing_id": "aapl-25", "cik": "0000320193", "accession": "0000320193-26-000001", "form": "10-K", "filed_date": "2026-11-01", "report_date": "2026-09-30"},
            {"filing_id": "msft-25", "cik": "0000789019", "accession": "0000789019-26-000001", "form": "10-K", "filed_date": "2026-08-01", "report_date": "2026-06-30"},
        ),
        concepts=(
            {"raw_concept_id": "aapl:revenue", "qname": "us-gaap:Revenue", "namespace_uri": "http://fasb.org/us-gaap/2025", "local_name": "Revenue", "is_standard": True, "is_custom": False},
        ),
        facts=(
            {"fact_id": "reported", "filing_id": "aapl-25", "raw_concept_id": "aapl:revenue", "value_numeric": 100, "reported_or_derived": "REPORTED"},
            {"fact_id": "derived", "filing_id": "aapl-25", "raw_concept_id": "aapl:revenue", "value_numeric": 25, "reported_or_derived": "DERIVED", "source_fact_ids": ["q1", "q2"], "derivation_formula": "q2 - q1"},
        ),
        series=(
            {"fact_id": "fy-24", "filing_id": "aapl-25", "cik": "0000320193", "raw_concept_id": "aapl:revenue", "company_canonical_concept_id": "company:aapl:revenue", "period_class": "FY", "series_type": "ANNUAL", "report_period": "2025-09-30"},
            {"fact_id": "qtd-25", "filing_id": "aapl-25", "cik": "0000320193", "raw_concept_id": "aapl:revenue", "company_canonical_concept_id": "company:aapl:revenue", "period_class": "QTD_3M", "series_type": "CURRENT", "report_period": "2025-12-31"},
        ),
        comparisons=(
            {"fact_id": "aapl-cloud", "filing_id": "aapl-25", "source_raw_id": "aapl:revenue", "company_canonical_id": "company:aapl", "analytical_id": "analytical:CLOUD", "mapping_relation": "SUBCATEGORY_OF", "mapping_confidence": 0.9, "mapping_version": "m8-v1", "source_period": "2026-09-30"},
            {"fact_id": "msft-cloud", "filing_id": "msft-25", "source_raw_id": "msft:cloud", "company_canonical_id": "company:msft", "analytical_id": "analytical:CLOUD", "mapping_relation": "ANALYTICALLY_SIMILAR", "mapping_confidence": 0.4, "mapping_version": "m8-v1", "source_period": "2026-06-30", "mapping_review_required": True},
        ),
    )


def test_resolve_company_handles_cik_and_ambiguous_name() -> None:
    repository = _repository()

    assert repository.resolve_company("320193")["ticker"] == "AAPL"
    with pytest.raises(CompanyAmbiguousError):
        repository.resolve_company("alphabet inc.")
    with pytest.raises(CompanyNotFoundError):
        repository.resolve_company("missing")


def test_fact_series_is_period_aware_and_carries_layer1_provenance() -> None:
    rows = _repository().get_fact_series(
        "AAPL", "company:aapl:revenue", "FY", "2025-01-01", "2025-10-01", "ANNUAL"
    )

    assert [row["fact_id"] for row in rows] == ["fy-24"]
    row = rows[0]
    assert row["accession"] == "0000320193-26-000001"
    assert row["qname"] == "us-gaap:Revenue"
    assert row["is_standard"] is True
    assert row["company_canonical_id"] == "company:aapl"


def test_comparison_keeps_relation_mapping_and_low_confidence_visible() -> None:
    rows = _repository().compare_companies(
        ["AAPL", "MSFT"], "analytical:CLOUD", ("2026-01-01", "2026-12-31"), "m8-v1"
    )

    assert {row["mapping_relation"] for row in rows} == {"SUBCATEGORY_OF", "ANALYTICALLY_SIMILAR"}
    low_confidence = next(row for row in rows if row["mapping_confidence"] == 0.4)
    assert low_confidence["mapping_review_required"] is True
    assert low_confidence["mapping_version"] == "m8-v1"
    assert low_confidence["company_canonical_id"] == "company:msft"


def test_trace_fact_distinguishes_reported_and_derived_provenance() -> None:
    repository = _repository()

    reported = repository.trace_fact("reported")
    derived = repository.trace_fact("derived")
    assert reported["reported_or_derived"] == "REPORTED"
    assert derived["reported_or_derived"] == "DERIVED"
    assert derived["source_fact_ids"] == ["q1", "q2"]
    assert derived["derivation_formula"] == "q2 - q1"
    assert derived["form"] == "10-K"
    with pytest.raises(FactNotFoundError):
        repository.trace_fact("unknown")


def test_repository_never_mutates_inputs_or_returned_records() -> None:
    companies = [{"cik": "0000320193", "ticker": "AAPL", "company_canonical_id": "company:aapl"}]
    facts = [{"fact_id": "f", "filing_id": "a", "raw_concept_id": "r"}]
    original_companies, original_facts = deepcopy(companies), deepcopy(facts)
    repository = AnalyticalRepository(companies=companies, facts=facts)
    companies[0]["ticker"] = "CHANGED"
    facts[0]["fact_id"] = "changed"

    result = repository.resolve_company("AAPL")
    result["ticker"] = "MUTATED"
    assert companies != original_companies
    assert facts != original_facts
    assert repository.resolve_company("AAPL")["ticker"] == "AAPL"
    assert repository.trace_fact("f")["fact_id"] == "f"
