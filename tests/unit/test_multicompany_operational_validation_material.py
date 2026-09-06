from __future__ import annotations

import json
from pathlib import Path

PACK = Path(__file__).parents[2] / "docs/test-materials/multicompany-operational-validation-v1.json"


def _pack() -> dict[str, object]:
    return json.loads(PACK.read_text(encoding="utf-8"))


def test_multicompany_pack_declares_expandable_cohort_and_fail_closed_gate() -> None:
    pack = _pack()
    companies = {row["ticker"]: row for row in pack["companies"]}  # type: ignore[index]
    assert set(companies) == {"NVDA", "AMD", "MSFT", "AAPL", "AMZN"}
    assert companies["NVDA"]["layer1_status"] == "AVAILABLE"
    assert companies["AMD"]["layer1_status"] == "AVAILABLE"
    assert companies["AAPL"]["layer1_status"] == "AVAILABLE"
    assert companies["MSFT"]["layer1_status"] == "AVAILABLE"
    assert companies["AMZN"]["layer1_status"] == "AVAILABLE"
    assert companies["MSFT"]["reference_filing"]["accession"] == "0000950170-24-118967"
    assert companies["AMZN"]["reference_filing"]["accession"] == "0001018724-24-000161"
    assert companies["MSFT"]["reference_filing"]["source_fact_count"] == 1236
    assert companies["AMZN"]["reference_filing"]["source_fact_count"] == 1139
    assert companies["MSFT"]["layer1_evidence"]["taxonomy_resolution"] == "controlled_bootstrap_then_offline_reload"
    gate = pack["publication_gate"]  # type: ignore[index]
    assert gate["storage_format"] == "parquet-operational-v1"
    assert gate["same_layer1_run_fingerprint"] is True
    assert set(gate["required_company_ciks"]) == {  # type: ignore[index]
        "0001045810", "0000002488", "0000789019", "0000320193", "0001018724"
    }
    assert gate["current_status"].startswith("BLOCKED:")


def test_multicompany_pack_preserves_real_amd_amendment_as_distinct_accessions() -> None:
    pack = _pack()
    amendment = pack["amendment_case"]  # type: ignore[index]
    assert amendment["cik"] == "0000002488"
    original = amendment["original_filing"]
    amended = amendment["amendment_filing"]
    assert original["accession"] == "0000002488-26-000018"
    assert original["form"] == "10-K"
    assert amended["accession"] == "0000002488-26-000021"
    assert amended["form"] == "10-K/A"
    assert original["accession"] != amended["accession"]
    assertions = amendment["required_assertions"]
    assert any("not assumed to contain every original fact" in item for item in assertions)
    assert any("not infer an amendment sequence" in item for item in assertions)
