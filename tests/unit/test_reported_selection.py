from __future__ import annotations

from sec_xbrl.longitudinal.reported_selection import (
    ReportedObservationIdentity,
    ReportedObservationSelector,
)


def _observation(accession: str, filed_date: str, value: str, *, fact: str | None = None, dimension=(), numerator: str = "iso4217:USD", end: str = "2025-03-29") -> dict[str, object]:
    suffix = accession[-6:]
    return {
        "cik": "0000320193", "accession": accession, "source_snapshot_id": f"snap:{suffix}", "source_filing_id": f"filing:{accession}", "source_fact_id": fact or f"fact:{suffix}",
        "form": "10-Q/A" if accession.endswith("000002") else "10-Q", "filed_date": filed_date, "report_date": "2025-03-29", "reported_or_derived": "REPORTED", "fiscal_year": 2025, "fiscal_quarter": 1, "period_class": "QTD_3M",
        "raw_concept_qname": "us-gaap:Revenues", "raw_concept_taxonomy_family": "us-gaap", "raw_concept_namespace_uri": "http://fasb.org/us-gaap/2024", "raw_concept_is_standard": True, "company_canonical_concept_id": "company-concept:revenue",
        "raw_dimension_signature": dimension, "canonical_dimension_signature": dimension, "unit_numerator_measures": numerator, "unit_denominator_measures": None, "context_start_date": "2024-12-29", "context_end_date": end, "context_instant_date": None, "value_numeric": value,
    }


def _ledger(*observations: dict[str, object]) -> list[dict[str, object]]:
    return [{
        "cik": row["cik"], "accession": row["accession"], "source_snapshot_id": row["source_snapshot_id"], "source_filing_id": row["source_filing_id"], "form": row["form"], "filed_date": row["filed_date"], "report_date": row["report_date"], "accession_version_ledger_id": f"ledger:{row['accession']}",
        "is_amendment": str(row["form"]).endswith("/A"), "amends_accession": "0000320193-25-000001" if str(row["form"]).endswith("/A") else None,
        "amendment_linkage_state": "LINKED" if str(row["form"]).endswith("/A") else "NOT_APPLICABLE", "amendment_linkage_method": "RAW_FILING_AMENDS_ACCESSION", "amendment_linkage_review_status": "NOT_REQUIRED", "reported_amendment_ordinal": None, "reported_amendment_ordinal_state": "NOT_REPORTED",
        "amendment_linkage_evidence": {"source_field": "filing.amends_accession"}, "amendment_flag_state": "REPORTED_TRUE" if str(row["form"]).endswith("/A") else "NOT_REPORTED",
        "dei_amendment_flag_raw": "true" if str(row["form"]).endswith("/A") else None, "dei_amendment_flag_fact_id": f"fact:amendment-flag:{row['accession']}",
        "dei_amendment_description_raw": "Amendment Number 1" if str(row["form"]).endswith("/A") else None, "dei_amendment_description_fact_id": f"fact:amendment-description:{row['accession']}",
    } for row in observations]


def _select(observations: list[dict[str, object]], view: str, as_of_date: str = "2025-06-30"):
    return ReportedObservationSelector().select_period(observations=observations, ledger=_ledger(*observations), cik="0000320193", fiscal_year=2025, fiscal_quarter=1, period_class="QTD_3M", as_of_date=as_of_date, view=view).rows


def test_as_filed_and_latest_reported_are_distinct_direct_views() -> None:
    original = _observation("0000320193-25-000001", "2025-05-01", "100")
    amendment = _observation("0000320193-25-000002", "2025-06-01", "120")
    assert _select([original, amendment], "AS_FILED")[0]["value_numeric"] == "100"
    latest = _select([original, amendment], "LATEST_REPORTED")[0]
    assert latest["value_numeric"] == "120"
    assert latest["ledger_amendment_linkage_state"] == "LINKED"
    assert latest["ledger_amendment_linkage_evidence"] == {"source_field": "filing.amends_accession"}
    assert latest["ledger_dei_amendment_flag_fact_id"] == "fact:amendment-flag:0000320193-25-000002"
    assert latest["ledger_dei_amendment_description_fact_id"] == "fact:amendment-description:0000320193-25-000002"
    assert latest["comparability_status"] == "NOT_ASSESSED"


def test_as_of_cutoff_and_same_date_accession_tie_breaker_are_deterministic() -> None:
    first = _observation("0000320193-25-000001", "2025-05-01", "100")
    same_day = _observation("0000320193-25-000003", "2025-05-01", "130")
    future = _observation("0000320193-25-000002", "2025-06-01", "120")
    selected = _select([first, same_day, future], "LATEST_REPORTED", "2025-05-01")[0]
    assert selected["value_numeric"] == "130"
    assert selected["selected_accession"] == "0000320193-25-000003"


def test_unmatched_amendment_does_not_replace_original_or_claim_scope() -> None:
    original = _observation("0000320193-25-000001", "2025-05-01", "100")
    # A later amendment fact is for a different actual period: not a replacement.
    unmatched = _observation("0000320193-25-000002", "2025-06-01", "999", end="2025-06-28")
    results = _select([original, unmatched], "LATEST_REPORTED")
    original_result = next(row for row in results if row["value_numeric"] == "100")
    assert original_result["selection_status"] == "SELECTED"
    assert original_result["selection_reason"] == "LATEST_ELIGIBLE_DIRECT_REPORTED_OBSERVATION"
    assert original_result["comparability_status"] == "NOT_ASSESSED"


def test_dimensions_and_unit_semantics_are_selection_boundaries() -> None:
    original = _observation("0000320193-25-000001", "2025-05-01", "100")
    dimensioned = _observation("0000320193-25-000002", "2025-06-01", "120", dimension=(("axis:a", "member:a", None, "EXPLICIT", False),))
    shares = _observation("0000320193-25-000003", "2025-06-02", "130", numerator="shares")
    assert len(_select([original, dimensioned, shares], "LATEST_REPORTED")) == 3


def test_nested_list_dimensions_from_parquet_are_hashable_and_match_exactly() -> None:
    original = _observation("0000320193-25-000001", "2025-05-01", "100")
    amendment = _observation("0000320193-25-000002", "2025-06-01", "120")
    decoded_signature = [["axis:a", "member:a", None, "EXPLICIT", False]]
    original["canonical_dimension_signature"] = decoded_signature
    amendment["canonical_dimension_signature"] = decoded_signature
    original["raw_dimension_signature"] = decoded_signature
    amendment["raw_dimension_signature"] = decoded_signature
    selected = _select([original, amendment], "LATEST_REPORTED")[0]
    assert selected["value_numeric"] == "120"


def test_no_numeric_change_recast_inference_and_absence_is_explicit() -> None:
    original = _observation("0000320193-25-000001", "2025-05-01", "100")
    identity = ReportedObservationIdentity.from_observation(original)
    selector = ReportedObservationSelector()
    selected = selector.select_identity(observations=[original], ledger=_ledger(original), identity=identity, as_of_date="2025-05-01", view="LATEST_REPORTED").rows[0]
    assert selected["source_type"] == "REPORTED"
    assert selected["comparability_status"] == "NOT_ASSESSED"
    unavailable = selector.select_identity(observations=[], ledger=[], identity=identity, as_of_date="2025-05-01", view="AS_FILED").rows[0]
    assert unavailable["selection_status"] == "UNAVAILABLE"
    assert unavailable["selection_unavailable_reason"] == "NO_ELIGIBLE_DIRECT_REPORTED_OBSERVATION"
    assert unavailable["ledger_amendment_linkage_evidence"] is None
