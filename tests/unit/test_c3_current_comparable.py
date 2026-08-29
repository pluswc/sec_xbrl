from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sec_xbrl.longitudinal import (
    CurrentComparableError,
    CurrentComparableMaterializer,
    CurrentComparablePublicationReader,
    CurrentComparablePublisher,
)
from sec_xbrl.longitudinal.materialization import (
    VerifiedLayer2Publication,
    _READER_ATTESTATION_TOKEN,
)


CIK = "0001045810"


def _fact(period: str) -> dict[str, object]:
    return {
        "analytical_fact_id": f"as-filed:{period}", "cik": CIK, "view": "AS_FILED",
        "company_canonical_concept_id": "company:revenue", "company_canonical_dimension_key": (("geo", "us"),),
        "period_class": "QTD_3M", "period_key": period, "basis_version": "billing-location-v1",
        "source_type": "REPORTED", "selected_fact_id": f"old:{period}", "source_filing_id": f"old-filing:{period}",
        "filed_date": "2026-01-01", "value_numeric": "1", "unit_semantics": "USD",
    }


def _candidate(identifier: str, period: str = "FY26-Q1", value: str = "25685") -> dict[str, object]:
    return {
        "series_candidate_id": identifier, "cik": CIK, "company_canonical_concept_id": "company:revenue",
        "company_canonical_dimension_key": (("geo", "us"),), "period_class": "QTD_3M", "actual_period_key": period,
        "source_filing_id": "new-filing", "source_fact_id": "new:q1", "filed_date": "2026-11-20",
        "value_numeric": value, "unit_semantics": "USD", "basis_version": "customer-headquarters-v2",
        "source_document": "nvda.htm", "source_locator": "geography-table",
    }


def _publication() -> VerifiedLayer2Publication:
    candidates = (_candidate("candidate:new-q1"),)
    observations = ({"source_filing_id": "new-filing", "source_fact_id": "new:q1", "accession": "0001045810-26-000052",
                     "form": "10-Q", "report_date": "2026-10-25", "context_id": "c-q1", "unit_id": "usd",
                     "source_document": "nvda.htm", "source_locator": "geography-table"},)
    return VerifiedLayer2Publication(
        Path("/verified"), Path("/verified/manifest"),
        MappingProxyType({"layer2_run_fingerprint": "f" * 64, "layer2_manifest_sha256": "m" * 64}),
        (CIK,), MappingProxyType({
            "analytical_fact": tuple(MappingProxyType(_fact(period)) for period in ("FY26-Q1", "FY26-Q2", "FY26-Q3", "FY26-Q4")),
            "current_series_candidate": tuple(MappingProxyType(row) for row in candidates),
            "period_observation": tuple(MappingProxyType(row) for row in observations),
        }), _READER_ATTESTATION_TOKEN,
    )


def _evidence(**changes: object) -> dict[str, object]:
    value = {
        "registry_version": "c3-m3-reviewed-recast-evidence-v1",
        "recast_evidence_id": "nvda-us-geography-fy26-v2-q1", "cik": CIK,
        "company_canonical_concept_id": "company:revenue", "company_canonical_dimension_key": (("geo", "us"),),
        "period_class": "QTD_3M", "target_period_keys": ("FY26-Q1",), "old_basis_version": "billing-location-v1",
        "new_basis_version": "customer-headquarters-v2", "source_type": "RECAST_REPORTED",
        "source_series_candidate_id": "candidate:new-q1", "source_filing_id": "new-filing", "source_raw_fact_id": "new:q1",
        "filed_date": "2026-11-20", "source_document": "nvda.htm", "source_locator": "geography-table",
        "evidence_identity": "note:geography-methodology-recast", "evidence_kind": "NARRATIVE_AND_TABLE",
        "explicitly_represented": True, "prior_analytical_fact_ids": ("as-filed:FY26-Q1",),
    }
    return value | changes


def test_nvda_golden_only_evidence_bound_q1_enters_current_comparable() -> None:
    result = CurrentComparableMaterializer().materialize(_publication(), evidence_registry=(_evidence(),))
    rows = {row["period_key"]: row for row in result.facts}
    assert rows["FY26-Q1"]["source_type"] == "RECAST_REPORTED"
    assert rows["FY26-Q1"]["value_numeric"] == "25685"
    assert rows["FY26-Q1"]["basis_version"] == "customer-headquarters-v2"
    assert {rows[key]["unavailable_reason"] for key in ("FY26-Q2", "FY26-Q3", "FY26-Q4")} == {"RECAST_EVIDENCE_NOT_AVAILABLE"}
    assert _publication().records("analytical_fact")[0]["selected_fact_id"] == "old:FY26-Q1"


def test_empty_registry_is_explicit_unavailable_not_as_filed_fallback() -> None:
    result = CurrentComparableMaterializer().materialize(_publication())
    assert {row["source_type"] for row in result.facts} == {"UNAVAILABLE"}
    assert {row["unavailable_reason"] for row in result.facts} == {"RECAST_EVIDENCE_NOT_AVAILABLE"}


@pytest.mark.parametrize("changed", [
    {"company_canonical_dimension_key": (("geo", "non-us"),)},
    {"target_period_keys": ("FY26-Q2",)},
    {"source_raw_fact_id": "wrong"},
    {"source_document": "tampered.htm"},
    {"source_locator": "tampered-locator"},
])
def test_mismatched_evidence_fails_closed(changed: dict[str, object]) -> None:
    with pytest.raises(CurrentComparableError):
        CurrentComparableMaterializer().materialize(_publication(), evidence_registry=(_evidence(**changed),))


def test_derived_recast_requires_exact_inputs() -> None:
    evidence = _evidence(
        source_type="DERIVED_RECAST",
        derivation_rule_version="c3-m3-fy-minus-ytd9m-v1",
        derived_input_bindings=({"role": "FY", "series_candidate_id": "candidate:new-q1"},),
    )
    with pytest.raises(CurrentComparableError, match="FY and YTD_9M"):
        CurrentComparableMaterializer().materialize(_publication(), evidence_registry=(evidence,))


def test_registry_version_and_reader_attestation_are_required() -> None:
    with pytest.raises(CurrentComparableError, match="registry_version"):
        CurrentComparableMaterializer().materialize(
            _publication(), evidence_registry=(_evidence(registry_version=None),)
        )
    forged = VerifiedLayer2Publication(
        Path("/forged"), Path("/forged/manifest"), MappingProxyType({}), (), MappingProxyType({})
    )
    with pytest.raises(CurrentComparableError, match="verified"):
        CurrentComparableMaterializer().materialize(forged)


def test_companion_reader_verifies_upstream_hash_and_tampering(tmp_path: Path) -> None:
    upstream = _publication()
    result = CurrentComparableMaterializer().materialize(upstream, evidence_registry=(_evidence(),))
    published = CurrentComparablePublisher().publish(result, output_root=tmp_path, run_version="c3-m3-fixture", upstream=upstream)
    assert CurrentComparablePublicationReader().load(published.run_root, upstream=upstream).facts[0]["view"] == "CURRENT_COMPARABLE"
    (published.run_root / "current_comparable_fact.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(CurrentComparableError, match="content"):
        CurrentComparablePublicationReader().load(published.run_root, upstream=upstream)
