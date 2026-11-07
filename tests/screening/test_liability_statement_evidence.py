from __future__ import annotations

import json
from copy import deepcopy
from decimal import localcontext

import pytest

from sec_xbrl.analytics.calculation11 import ARCROLE
from sec_xbrl.metrics.liability_statement_evidence import derive_total_liabilities_candidate

CIK = "0000000042"
INSTANT = "2026-07-01"
FILING = "filing"
TABLE = "balance-sheet"
ROLE = "role"
URI = "https://example.invalid/role/ConsolidatedBalanceSheet"
HASH = "a" * 64


def _prepared():
    prepared = {
        "filings": [{"cik": CIK, "filing_id": FILING, "accession": "0000000042-26-000001",
                     "filed_date": "2026-08-01", "package_hash": HASH}],
        "source_tables": [{"table_id": TABLE, "section": "BS", "filing_id": FILING, "role_id": ROLE,
                           "source_document": "primary.htm", "source_document_sha256": HASH, "table_sha256": HASH}],
        "statement_facts": [], "source_statement_rows": [], "statement_rows": [], "statement_relationships": [],
    }
    _add_row(prepared, "assets", "us-gaap:Assets", "1000", "Total assets")
    _add_row(prepared, "balance", "us-gaap:LiabilitiesAndStockholdersEquity", "1000", "Total liabilities and equity")
    _add_row(prepared, "current", "us-gaap:LiabilitiesCurrent", "240", "Total current liabilities", child=True)
    _add_row(prepared, "lease", "issuer:AnyLeaseExtension", "90", "Long-term lease liabilities", child=True)
    _add_row(prepared, "debt", "us-gaap:LongTermDebtNoncurrent", "130", "Long-term debt", child=True)
    _add_row(prepared, "other", "us-gaap:OtherLiabilitiesNoncurrent", "80", "Other long-term liabilities", child=True)
    _add_row(prepared, "equity", "us-gaap:StockholdersEquity", "460", "Total stockholders’ equity", child=True)
    _add_row(prepared, "note", "us-gaap:CommitmentsAndContingencies", None,
             "Commitments and contingencies (Note 4)", child=True)
    return prepared


def _add_row(prepared, key, qname, value, label, *, child=False):
    standard = qname.startswith("us-gaap:")
    fact = {
        "fact_id": key, "filing_id": FILING, "raw_concept_id": key, "context_id": "context", "unit_id": "usd",
        "reported_or_derived": "REPORTED", "value_numeric": value, "value_text": None, "is_nil": value is None,
        "scope": {"cik": CIK, "filing_id": FILING, "view": "RAW_AS_FILED", "basis": "RAW:" + FILING,
                  "as_of": "2026-10-25", "unit": {"numerator": ["iso4217:USD"], "denominator": []},
                  "period": {"type": "instant", "class": "INSTANT", "instant": INSTANT, "start": None, "end": None},
                  "dimensions": []},
        "context": {"entity_identifier": "http://www.sec.gov/CIK:" + CIK},
        "concept": {"qname": qname, "is_standard": standard, "is_custom": not standard,
                    "namespace_uri": "http://fasb.org/us-gaap/2026" if standard else "https://example.invalid/issuer",
                    "period_type": "instant", "data_type": "xbrli:monetaryItemType"},
        "source_locations": [{"table_id": TABLE, "row_id": key, "inline_id": key,
                              "binding_status": "EXACT_RAW_ID", "source_document_sha256": HASH,
                              "row_locator": "/table/" + key, "cell_locator": "/table/" + key + "/td"}],
    }
    prepared["statement_facts"].append(fact)
    prepared["source_statement_rows"].append({
        "row_id": key, "table_id": TABLE, "filing_id": FILING, "label": label,
        "coverage_status": "INCLUDED", "source_document_sha256": HASH, "pre_path_ids": [key],
    })
    prepared["statement_rows"].append({
        "row_id": key, "section": "BS", "raw_concept_id": key, "cycle": False,
        "network_identity": {"role_id": ROLE, "role_uri": URI},
    })
    if child:
        prepared["statement_relationships"].append({
            "relationship_id": "arc-" + key, "network_type": "CAL", "filing_id": FILING,
            "role_id": ROLE, "role_uri": URI, "arcrole": ARCROLE, "link_qname": "link:calculationLink",
            "arc_qname": "link:calculationArc", "from_raw_concept_id": "balance",
            "to_raw_concept_id": key, "weight": "1", "evidence_origin": "ADDITIVE_ARELLE_CALCULATION_1_1",
            "source_package_sha256": HASH, "policy_version": "h1-supplemental-cal11-v1",
            "source_document": "cal.xml", "source_document_sha256": HASH, "source_members_sha256": {"cal.xml": HASH},
        })
    return fact


def _fact(prepared, key):
    return next(fact for fact in prepared["statement_facts"] if fact["fact_id"] == key)


def _derive(prepared):
    return derive_total_liabilities_candidate(prepared, cik=CIK, instant=INSTANT)


def test_two_exact_proofs_preserve_raw_identity_and_ignore_only_bound_nil_note():
    prepared = _prepared()
    baseline = deepcopy(prepared)
    result = _derive(prepared)
    assert (result["status"], result["value"], result["reason"]) == ("DERIVED_CANDIDATE", "540", None)
    proof = result["provenance"]
    assert proof["formula"] == "Assets - TotalEquity"
    assert proof["equity"]["source"]["source_fact_id"] == "equity"
    assert {row["source"]["source_fact_id"] for row in proof["liability_components"]} == {
        "current", "lease", "debt", "other",
    }
    assert {row["relationship"]["weight"] for row in proof["liability_components"]} == {"1"}
    assert proof["nonnumeric_note_references"][0]["source"]["source_fact_id"] == "note"
    assert proof["liability_components"][0]["source"]["cell_locator"].startswith("/table/")
    assert json.loads(json.dumps(result)) == result
    assert prepared == baseline


def test_direct_liabilities_has_priority_and_never_falls_back_when_ambiguous():
    prepared = _prepared()
    direct = _add_row(prepared, "reported", "us-gaap:Liabilities", "541", "Total liabilities")
    prepared["statement_relationships"].clear()
    result = _derive(prepared)
    assert (result["status"], result["value"]) == ("REPORTED", "541")
    assert result["provenance"]["reported"]["source_fact_id"] == "reported"
    direct["source_locations"].append(deepcopy(direct["source_locations"][0]))
    assert _derive(prepared)["reason"] == "REPORTED_LIABILITIES_NOT_UNIQUE"


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("currency", "CALCULATION_CHILD_SCOPE_MISMATCH"),
        ("period", "CALCULATION_CHILD_NOT_UNIQUE"),
        ("segment", "CALCULATION_CHILD_NOT_UNIQUE"),
        ("role", "PRIMARY_ROW_ROLE_NOT_PROVEN"),
        ("package", "CALCULATION_NETWORK_NOT_PROVEN"),
        ("negative_weight", "CALCULATION_NETWORK_NOT_PROVEN"),
        ("duplicate_arc", "CALCULATION_NETWORK_NOT_PROVEN"),
        ("numeric_note", "UNKNOWN_CALCULATION_CHILD"),
        ("net_lease", "UNKNOWN_CALCULATION_CHILD"),
        ("rounded", "LIABILITY_COMPONENTS_DO_NOT_RECONCILE"),
        ("negative_component", "INVALID_LIABILITY_COMPONENT"),
        ("different_balance", "BALANCE_TOTAL_NOT_RECONCILED"),
        ("duplicate_primary", "CALCULATION_CHILD_NOT_UNIQUE"),
        ("conflicting_disclosure", "CONFLICTING_SAME_SCOPE_RAW_FACT"),
    ],
)
def test_invalid_component_or_scope_is_held(defect, reason):
    prepared = _prepared()
    debt = _fact(prepared, "debt")
    arc = next(item for item in prepared["statement_relationships"] if item["to_raw_concept_id"] == "debt")
    if defect == "currency":
        debt["scope"]["unit"]["numerator"] = ["iso4217:EUR"]
    elif defect == "period":
        debt["scope"]["period"]["instant"] = "2026-06-30"
    elif defect == "segment":
        debt["scope"]["dimensions"] = [{"axis": "segment", "member": "segment-a"}]
    elif defect == "role":
        next(item for item in prepared["statement_rows"] if item["row_id"] == "debt")["network_identity"]["role_uri"] += "-other"
    elif defect == "package":
        arc["source_package_sha256"] = "b" * 64
    elif defect == "negative_weight":
        arc["weight"] = "-1"
    elif defect == "duplicate_arc":
        prepared["statement_relationships"].append({**arc, "relationship_id": "duplicate"})
    elif defect == "numeric_note":
        _fact(prepared, "note").update(value_numeric="0", is_nil=False)
    elif defect == "net_lease":
        next(row for row in prepared["source_statement_rows"] if row["row_id"] == "lease")["label"] += ", net"
    elif defect == "rounded":
        debt["value_numeric"] = "130.00001"
    elif defect == "negative_component":
        debt["value_numeric"] = "-130"
    elif defect == "different_balance":
        _fact(prepared, "balance")["value_numeric"] = "1000.01"
    elif defect == "duplicate_primary":
        prepared["statement_facts"].append({**deepcopy(debt), "fact_id": "duplicate"})
    elif defect == "conflicting_disclosure":
        prepared["statement_facts"].append({**deepcopy(debt), "fact_id": "note-duplicate",
                                             "source_locations": [], "value_numeric": "131"})
    result = _derive(prepared)
    assert (result["status"], result["value"], result["reason"]) == ("UNAVAILABLE", None, reason)


def test_total_equity_including_nci_is_required_and_temporary_equity_is_held():
    prepared = _prepared()
    _add_row(prepared, "nci", "us-gaap:MinorityInterest", "10", "Noncontrolling interest")
    assert _derive(prepared)["reason"] == "TOTAL_EQUITY_INCLUDING_NCI_REQUIRED"
    equity = _fact(prepared, "equity")
    equity["concept"]["qname"] = "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    assert _derive(prepared)["value"] == "540"
    _add_row(prepared, "mezzanine", "issuer:TemporaryEquity", "0", "Redeemable noncontrolling interests")
    assert _derive(prepared)["reason"] == "TEMPORARY_OR_REDEEMABLE_EQUITY_PRESENT"


def test_negative_equity_and_equal_off_table_occurrence_are_valid():
    prepared = _prepared()
    for key in ("assets", "balance"):
        _fact(prepared, key)["value_numeric"] = "500"
    _fact(prepared, "equity")["value_numeric"] = "-40"
    debt = _fact(prepared, "debt")
    prepared["statement_facts"].append({**deepcopy(debt), "fact_id": "note-duplicate", "source_locations": []})
    with localcontext() as context:
        context.prec = 2
        assert _derive(prepared)["value"] == "540"


@pytest.mark.parametrize("label", ["Deferred tax liabilities", "Deferred income tax liabilities"])
def test_exact_typed_tax_and_note_reference_variants(label):
    prepared = _prepared()
    _fact(prepared, "other")["concept"]["qname"] = "us-gaap:DeferredIncomeTaxLiabilitiesNet"
    rows = {row["row_id"]: row for row in prepared["source_statement_rows"]}
    rows["other"]["label"] = label
    for note in ("Commitments and contingencies (See Note 10)", "Contingencies (Note 14)"):
        rows["note"]["label"] = note
        assert _derive(prepared)["value"] == "540"
    rows["other"]["label"] = "Other liabilities"
    assert _derive(prepared)["reason"] == "UNKNOWN_CALCULATION_CHILD"


def test_combined_long_term_debt_component_rejects_overlapping_lease():
    prepared = _prepared()
    _fact(prepared, "debt")["concept"]["qname"] = "us-gaap:LongTermDebtAndCapitalLeaseObligations"
    assert _derive(prepared)["reason"] == "LIABILITY_COMPONENT_SCOPE_NOT_PROVEN"
    prepared["statement_relationships"] = [
        arc for arc in prepared["statement_relationships"] if arc["to_raw_concept_id"] != "lease"
    ]
    _fact(prepared, "debt")["value_numeric"] = "220"
    assert _derive(prepared)["value"] == "540"
