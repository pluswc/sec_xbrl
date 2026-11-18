from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from sec_xbrl.metrics.cal_eps import (
    _CONTROL,
    _EPS,
    _EPS_UNIT,
    _GENERIC_INCREMENTAL_SHARES,
    _MONEY_UNIT,
    _SHARES_UNIT,
    _STOCK_AWARD_SHARES,
    _WEIGHTED,
    FilingInputs,
    QualificationError,
    reconstruct_window,
)
from sec_xbrl.relationships.layer1 import CALCULATION_10_ARCROLE, CALCULATION_11_ARCROLE

_CIK = "0000000001"
_START = "2025-01-01"
_Q4 = "2025-10-01"
_END = "2026-01-01"


def _projection(start, end, *, numerator, basic_eps, diluted_eps, arcrole=CALCULATION_11_ARCROLE,
                increment=_STOCK_AWARD_SHARES, explicit=False):
    shares_basic, shares_diluted = _WEIGHTED["basic"][0], _WEIGHTED["diluted"][0]
    eps_basic, eps_diluted = _EPS["basic"][0], _EPS["diluted"][0]
    basic_num = "NetIncomeLossAvailableToCommonStockholdersBasic"
    diluted_num = "NetIncomeLossAvailableToCommonStockholdersDiluted"
    components = [
        ("NetIncomeLoss", numerator, _MONEY_UNIT, "-1"),
        (shares_basic, "1000", _SHARES_UNIT, "0"),
        (shares_diluted, "1010", _SHARES_UNIT, "0"),
        (increment, "10", _SHARES_UNIT, "0"),
        (eps_basic, basic_eps, _EPS_UNIT, "2"),
        (eps_diluted, diluted_eps, _EPS_UNIT, "2"),
        (_CONTROL[0], numerator, _MONEY_UNIT, "-1"),
    ]
    if explicit:
        components.extend(((basic_num, numerator, _MONEY_UNIT, "-1"), (diluted_num, numerator, _MONEY_UNIT, "-1")))
    concepts = [{"raw_concept_id": n, "local_name": n, "namespace_uri": "http://fasb.org/us-gaap/2025",
                 "is_standard": True} for n, *_ in components]
    facts = []
    for name, value, unit, decimals in components:
        row = None if explicit and name in {basic_num, diluted_num} else {
            "table_xpath": "/table", "row_xpath": "/table/" + name, "inline_id": name}
        facts.append({"fact_id": "f:" + name, "raw_concept_id": name, "context_id": "context",
                      "context_key": "equivalent-context", "start": start, "end": end, "unit": unit,
                      "dimensions": [], "is_nil": False, "value_numeric": value, "decimals": decimals,
                      "source_document": "report.htm", "source_table": row, "source_locator": "line:17",
                      "entity_identifier": "http://www.sec.gov/CIK:" + _CIK})
    relationships = [
        _arc("r1", shares_diluted, shares_basic, arcrole),
        _arc("r2", shares_diluted, increment, arcrole),
    ]
    if explicit:
        relationships.extend((_arc("r3", basic_num, "NetIncomeLoss", arcrole),
                              _arc("r4", diluted_num, "NetIncomeLoss", arcrole)))
    return {"filing": {"cik": _CIK, "accession": end}, "facts": facts,
            "concepts": concepts, "relationships": relationships, "eps_treasury_stock_policy": []}


def _arc(ident, parent, child, arcrole=CALCULATION_11_ARCROLE, **updates):
    return {"relationship_id": ident, "filing_id": "filing", "role_id": "eps", "arcrole": arcrole,
            "link_qname": "link:calculationLink", "arc_qname": "link:calculationArc",
            "from_raw_concept_id": parent, "to_raw_concept_id": child, "weight": "1",
            "source_document": "report_cal.xml", "source_locator": "line:41", **updates}


def _standards(*, explicit=False):
    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96",
                         explicit=explicit)
    nine = _projection(_START, _Q4, numerator="3000", basic_eps="3", diluted_eps="2.97",
                       arcrole=CALCULATION_10_ARCROLE, explicit=explicit)
    return annual, nine


def _reconstruct(annual, nine, *, flavor="diluted", direct=None, controls=("1000", "1000", "1000")):
    periods = list(zip((_START, "2025-04-01", "2025-07-01"), ("2025-04-01", "2025-07-01", _Q4), strict=True))
    preceding = [(FilingInputs(_projection(s, e, numerator=n, basic_eps="1", diluted_eps="0.99")), s, e)
                 for (s, e), n in zip(periods, controls, strict=True)]
    with localcontext() as context:
        context.prec = 80
        return reconstruct_window(fy=FilingInputs(annual), nine_month=FilingInputs(nine), preceding=preceding,
                                  flavor=flavor, start=_START, q4_start=_Q4, end=_END, direct_eps=direct)


def test_normal_diluted_cumulative_uses_complete_networks_and_day_weights():
    reconstructed = _reconstruct(*_standards())
    assert Decimal(reconstructed["value"]).quantize(Decimal(".0001")) == Decimal(".9901")
    assert reconstructed["weights"] == ["365", "273", "92"]
    assert reconstructed["direct_comparison"]["status"] == "REFERENCE_UNAVAILABLE"
    assert reconstructed["selected_source_type"] == "DERIVED_Q4_EPS"
    evidence = reconstructed["source_calculation_evidence"]
    assert evidence["FY"]["share_calculations"][0]["network"]["arcrole"] == CALCULATION_11_ARCROLE
    assert evidence["9M"]["share_calculations"][0]["network"]["arcrole"] == CALCULATION_10_ARCROLE
    assert len(evidence["preceding_quarter_controls"]) == 3


def test_explicit_basic_and_diluted_numerators_keep_separate_identities_and_verify_identical_cal():
    annual, nine = _standards(explicit=True)
    assert _reconstruct(annual, nine, flavor="basic")["value"] == "1"
    proof = _reconstruct(annual, nine)["source_calculation_evidence"]["FY"]
    assert proof["common_attribution"]["basis"] == "EQUIVALENT_COMPLETE_CAL_NUMERATOR_COMPOSITION"
    assert proof["numerator"]["selected_fact_id"].endswith("CommonStockholdersDiluted")
    annual["relationships"].pop()
    with pytest.raises(QualificationError, match="DILUTED_NUMERATOR_ADJUSTMENT_BASIS_NOT_PROVEN"):
        _reconstruct(annual, nine)


def test_direct_reported_value_precedes_compatible_reconstruction_and_disjoint_interval_fails():
    direct = {"value": "1.0", "interval": ["0.95", "1.05"], "fact_keys": ["q4-source"]}
    result = _reconstruct(*_standards(), direct=direct)
    assert result["selected_source_type"] == "REPORTED_Q4_EPS"
    assert result["value"] == "1.0"
    assert result["direct_comparison"]["status"] == "ROUNDING_COMPATIBLE"
    with pytest.raises(QualificationError, match="DIRECT_Q4_EPS_ROUNDING_MISMATCH") as raised:
        _reconstruct(*_standards(), direct=dict(direct, value="0.97", interval=["0.965", "0.975"]))
    assert raised.value.status == "FAIL"


def _mutate_child(annual, **kw):
    next(r for r in annual["facts"] if r["raw_concept_id"] == _STOCK_AWARD_SHARES).update(kw)


@pytest.mark.parametrize(("mutation", "reason"), [
    ({"unit": _MONEY_UNIT}, "COMPONENT_UNIT_MISMATCH"),
    ({"context_key": "different-typed-or-residual-context"}, "CALCULATION_CHILD_FACT_MISSING"),
    ({"is_nil": True}, "REPORTED_COMPONENT_NIL_OR_NONNUMERIC"),
    ({"value_numeric": "100"}, "CALCULATION_ROUNDING_MISMATCH"),
    ({"decimals": None}, "SOURCE_ROUNDING_PRECISION_UNKNOWN"),
])
def test_child_cannot_be_taken_from_other_scope_or_an_incompatible_value(mutation, reason):
    annual, nine = _standards()
    _mutate_child(annual, **mutation)
    with pytest.raises(QualificationError, match=reason):
        _reconstruct(annual, nine)


def test_equivalent_context_and_compatible_duplicates_keep_all_raw_references():
    annual, nine = _standards()
    child = next(r for r in annual["facts"] if r["raw_concept_id"] == _STOCK_AWARD_SHARES)
    annual["facts"].append(dict(child, fact_id="duplicate", context_id="equivalent-alias",
                                value_numeric="10.25", decimals="2"))
    proof = _reconstruct(annual, nine)["source_calculation_evidence"]["FY"]["share_calculations"][0]
    references = next(c["component"] for c in proof["children"] if c["concept"][1] == _STOCK_AWARD_SHARES)
    assert references["selected_fact_id"] == "duplicate"
    assert len(references["facts"]) == 2
    annual["facts"][-1]["value_numeric"] = "17"
    with pytest.raises(QualificationError, match="CONFLICTING_REPORTED_DUPLICATES"):
        _reconstruct(annual, nine)


@pytest.mark.parametrize("split", ["role_id", "arcrole", "link_qname", "arc_qname"])
def test_split_network_arcs_cannot_be_combined(split):
    annual, nine = _standards()
    annual["relationships"][1][split] = CALCULATION_10_ARCROLE if split == "arcrole" else "isolated"
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _reconstruct(annual, nine)


def test_cycle_cannot_support_even_a_rounding_compatible_equation():
    annual, nine = _standards()
    annual["relationships"].append(_arc("cycle", _STOCK_AWARD_SHARES, _WEIGHTED["diluted"][0]))
    with pytest.raises(QualificationError, match="CALCULATION_NETWORK_CYCLE"):
        _reconstruct(annual, nine)


@pytest.mark.parametrize("unsupported", [_GENERIC_INCREMENTAL_SHARES, "WeightedAverageNumberOfSharesOutstandingDilutedUsingIfConvertedMethod"])
def test_unresolved_potential_share_population_holds(unsupported):
    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96", increment=unsupported)
    _, nine = _standards()
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _reconstruct(annual, nine)


def test_parent_net_income_arithmetic_needs_structural_source_binding():
    annual, nine = _standards()
    next(r for r in annual["facts"] if r["raw_concept_id"] == "NetIncomeLoss")["source_table"] = None
    with pytest.raises(QualificationError, match="PARENT_NET_INCOME_NOT_BOUND_TO_REPORTED_EPS_TABLE"):
        _reconstruct(annual, nine)


@pytest.mark.parametrize(("value", "decimals"), [("3", "INF"), ("0", "0")])
def test_parent_net_income_binding_and_rounded_eps_do_not_erase_reported_adjustments(value, decimals):
    annual, nine = _standards()
    name = "DividendsPreferredStockCash"
    for period in (annual, nine):
        parent = next(f for f in period["facts"] if f["raw_concept_id"] == "NetIncomeLoss")
        period["concepts"].append({"raw_concept_id": name, "local_name": name,
                                   "namespace_uri": "http://fasb.org/us-gaap/2025", "is_standard": True})
        period["facts"].append(dict(parent, raw_concept_id=name, fact_id="preferred",
                                    value_numeric=value, decimals=decimals,
                                    source_table={"table_xpath": "/table", "row_xpath": "/table/preferred"}))
    with pytest.raises(QualificationError, match="PARENT_NET_INCOME_EPS_ADJUSTMENT_NONZERO_OR_UNCERTAIN") as raised:
        _reconstruct(annual, nine)
    assert raised.value.evidence["component"]["facts"][0]["fact_id"] == "preferred"
    for period in (annual, nine):
        period["facts"][-1].update(value_numeric="0", decimals="INF")
    evidence = _reconstruct(annual, nine)["source_calculation_evidence"]["FY"]["numerator_proof"]
    assert evidence["reported_adjustment_evidence"][0]["component"]["interval"] == ["0", "0"]
    # Another class/context does not supply counterevidence for this EPS scope.
    annual["facts"][-1].update(value_numeric="3", context_key="another-class-context")
    assert _reconstruct(annual, nine)["value"]


def test_source_projection_retains_numerator_counterevidence_without_a_cal_relationship():
    from sec_xbrl.metrics.cal_eps_source import (
        EPS_NAMES,
        EPS_NUMERATOR_ADJUSTMENT_NAMES,
        _projection_roots,
        _select_networks,
    )

    names = {"DividendsPreferredStockCash", "PreferredStockDividendsAndOtherAdjustments",
             "UndistributedEarningsLossAllocatedToParticipatingSecuritiesBasic",
             "InterestOnConvertibleDebtNetOfTax"}
    assert names <= EPS_NUMERATOR_ADJUSTMENT_NAMES <= EPS_NAMES
    tables = type("EmptyRelationships", (), {"relationships": []})()
    custom_names = {"IncomeAllocatedToParticipatingSecurities", "TwoClassEarningsAllocation"}
    concepts = {n: {"local_name": n, "namespace_uri": "http://fasb.org/us-gaap/2025"}
                for n in names}
    concepts.update({n: {"local_name": n, "namespace_uri": "https://example.test/custom"}
                     for n in custom_names | {"CustomNetIncome"}})
    relationships, retained = _select_networks(tables, _projection_roots(concepts))
    assert relationships == []
    assert retained == names | custom_names


def test_two_class_allocation_is_not_temporally_additive_even_when_each_cal_equation_works():
    annual, nine = _standards(explicit=True)
    for period in (annual, nine):
        key = "UndistributedEarningsLossAllocatedToParticipatingSecuritiesDiluted"
        net = next(r for r in period["facts"] if r["raw_concept_id"] == "NetIncomeLoss")
        fact = deepcopy(net)
        fact.update(raw_concept_id=key, fact_id="participating", value_numeric="20", decimals="INF")
        net["value_numeric"] = str(Decimal(net["value_numeric"]) + Decimal(20))
        period["facts"].append(fact)
        period["concepts"].append({"raw_concept_id": key, "local_name": key,
                                   "namespace_uri": "http://fasb.org/us-gaap/2025", "is_standard": True})
        for old in period["relationships"][2:4]:
            arc = _arc(old["relationship_id"] + "-participating", old["from_raw_concept_id"], key, old["arcrole"])
            arc["weight"] = "-1"
            period["relationships"].append(arc)
    with pytest.raises(QualificationError, match="TWO_CLASS_ALLOCATION_ADDITIVITY_NOT_PROVEN") as raised:
        _reconstruct(annual, nine)
    assert raised.value.evidence["calculations"][0]["status"] == "VERIFIED"


@pytest.mark.parametrize(("controls", "reason"), [
    (("1000", "-3", "1000"), "PRECEDING_QUARTER_CONTINUING_CONTROL_NONPOSITIVE"),
    (("1000", "0", "1000"), "PRECEDING_QUARTER_CONTINUING_CONTROL_NONPOSITIVE"),
])
def test_preceding_loss_or_uncertain_zero_controls_hold(controls, reason):
    with pytest.raises(QualificationError, match=reason):
        _reconstruct(*_standards(), controls=controls)


def test_explicit_basic_only_rollup_is_positive_zero_dilution_evidence():
    annual, nine = _standards()
    for period, eps in ((annual, "4"), (nine, "3")):
        period["relationships"].pop()
        next(f for f in period["facts"] if f["raw_concept_id"] == _WEIGHTED["diluted"][0])["value_numeric"] = "1000"
        next(f for f in period["facts"] if f["raw_concept_id"] == _EPS["diluted"][0])["value_numeric"] = eps
    result = _reconstruct(annual, nine)
    assert result["value"] == "1"
    assert len(result["source_calculation_evidence"]["FY"]["share_calculations"][0]["children"]) == 1
    annual["relationships"].clear()
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _reconstruct(annual, nine)


def test_generic_increment_needs_source_bound_stock_award_semantics():
    from sec_xbrl.metrics.cal_eps import _normal_dilution

    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96",
                         increment=_GENERIC_INCREMENTAL_SHARES)
    label = {"text": "Weighted effect of restricted stock units and employee stock purchase plan"}

    def bind_label(fact):
        assert fact["raw_concept_id"] == _GENERIC_INCREMENTAL_SHARES
        return [label]

    source = FilingInputs(annual, source_labels=bind_label)
    shares = source.select(_WEIGHTED["diluted"], _START, _END, _SHARES_UNIT)
    equation, = _normal_dilution(source, shares)
    assert equation["children"][1]["stock_award_source_labels"] == [label]
    label["text"] += " and convertible notes"
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _normal_dilution(source, shares)


def test_continuing_control_can_use_two_signed_equations_in_same_base_set():
    from sec_xbrl.metrics.cal_eps import _EQUITY_METHOD, _PRETAX_EXCLUDING_EQUITY, _TAX

    annual, nine = _standards()
    # 4,000 parent = 4,100 consolidated - 100 NCI
    # 4,100 consolidated = 4,400 pretax + 200 equity − 500 tax
    annual["facts"] = [f for f in annual["facts"] if f["raw_concept_id"] != _CONTROL[0]]
    prototype = next(f for f in annual["facts"] if f["raw_concept_id"] == "NetIncomeLoss")
    nci = "NetIncomeLossAttributableToNoncontrollingInterest"
    for name, value in (("ProfitLoss", "4100"), (nci, "100"), (_PRETAX_EXCLUDING_EQUITY, "4400"),
                        (_EQUITY_METHOD, "200"), (_TAX, "500")):
        annual["concepts"].append({"raw_concept_id": name, "local_name": name,
                                   "namespace_uri": "http://fasb.org/us-gaap/2025", "is_standard": True})
        annual["facts"].append(dict(prototype, raw_concept_id=name, fact_id="f:" + name, value_numeric=value))
    for ix, (parent, child, weight) in enumerate((
        ("NetIncomeLoss", "ProfitLoss", "1"), ("NetIncomeLoss", nci, "-1"),
        ("ProfitLoss", _PRETAX_EXCLUDING_EQUITY, "1"), ("ProfitLoss", _EQUITY_METHOD, "1"),
        ("ProfitLoss", _TAX, "-1"),
    )):
        arc = _arc("continuing-" + str(ix), parent, child)
        arc["weight"] = weight
        annual["relationships"].append(arc)
    equation, = _reconstruct(annual, nine)["source_calculation_evidence"]["FY"]["control_proof"]["calculations"]
    assert equation["profit_loss_continuing_equations"][0]["status"] == "VERIFIED"
    for arc in annual["relationships"][-3:]:
        arc["role_id"] = "another-fully-specified-role"
    with pytest.raises(QualificationError, match="CONTINUING_OPERATIONS_CONTROL_NOT_PROVEN"):
        _reconstruct(annual, nine)


def test_original_accession_selection_uses_explicit_publication_vintage():
    from sec_xbrl.metrics.cal_eps_preparation import _AccessionSources

    def filing(accession, filed_date):
        return {"cik": _CIK, "accession": accession, "form": "10-Q",
                "filed_date": filed_date, "report_date": "2025-09-30"}

    source = _AccessionSources(
        {"snapshots": [], "source_filings": [
            filing("0000000001-25-000001", "2025-10-15"),
            filing("0000000001-26-000001", "2026-10-27"),
        ]},
        {"filings": []},
    )
    selected = source.original(_CIK, "2025-10-01", "10-Q", "2026-02-21")
    assert selected["accession"] == "0000000001-25-000001"
    with pytest.raises(QualificationError, match="ORIGINAL_CURRENT_FOCUS_ACCESSION_AMBIGUOUS"):
        source.original(_CIK, "2025-10-01", "10-Q", "2026-11-13")


def test_affirmative_common_stock_warrant_policy_and_cal_support_normal_dilution():
    from sec_xbrl.metrics.cal_eps import _normal_dilution

    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96",
                         increment=_GENERIC_INCREMENTAL_SHARES)
    sentence = "Stock options and warrants for common stock use the treasury stock method."
    annual["eps_treasury_stock_policy"] = [{
        "snippet": sentence + " The comparative antidilutive table lists historical convertible preferred shares."
    }]
    source = FilingInputs(annual)
    shares = source.select(_WEIGHTED["diluted"], _START, _END, _SHARES_UNIT)
    equation, = _normal_dilution(source, shares)
    assert equation["children"][1]["treasury_stock_policy"][0]["affirmative_method_clause"] == sentence
    for bad in ("Convertible notes, stock options and common stock warrants use the treasury stock method.",
                "Cash-settled common stock warrants use the treasury stock method.",
                "Common stock warrants do not use the treasury stock method.",
                "Common stock warrants aren't measured with the treasury stock method.",
                "Antidilutive common stock warrants were excluded using the treasury stock method."):
        annual["eps_treasury_stock_policy"][0]["snippet"] = bad
        with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
            _normal_dilution(source, shares)


@pytest.mark.parametrize("sentence", [
    "For diluted earnings per share, the terminology stock options and treasury stock method is discussed in Note12.",
    "Common stock warrants would use the treasury stock method if they became exercisable.",
    "Diluted earnings per share could be computed for stock options using the treasury stock method.",
    "We plan to use the treasury stock method for stock options in diluted earnings per share.",
    "The treasury stock method may be used for common stock warrants in diluted earnings per share.",
])
def test_generic_share_adjustment_needs_actual_method_application_not_mentions_or_future_policy(sentence):
    from sec_xbrl.metrics.cal_eps import _normal_dilution

    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96",
                         increment=_GENERIC_INCREMENTAL_SHARES)
    annual["eps_treasury_stock_policy"] = [{"snippet": sentence}]
    source = FilingInputs(annual)
    shares = source.select(_WEIGHTED["diluted"], _START, _END, _SHARES_UNIT)
    assert source.calculations(shares)[0]["status"] == "VERIFIED"
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _normal_dilution(source, shares)


@pytest.mark.parametrize("sentence", [
    "Diluted earnings per share is calculated using the treasury stock method for stock options.",
    "The dilutive effect of restricted stock units is determined using the treasury stock method.",
    "We use the treasury-stock method for stock options in diluted earnings per share.",
    "We apply the treasury stock method to common stock warrants when dilutive.",
    "The treasury stock method is used to compute diluted earnings per share for stock options.",
    "The treasury stock method is applied to stock options if dilutive in diluted earnings per share.",
    "Potentially dilutive securities include common stock from assumed exercise of stock options and warrants using the treasury stock method.",
    "The computation of diluted EPS is based on common shares and stock options that may be issued under our award programs, as determined by using the treasury stock method.",
])
def test_generic_share_adjustment_accepts_current_application_wordings_and_dilutive_conditions(sentence):
    from sec_xbrl.metrics.cal_eps import _normal_dilution

    annual = _projection(_START, _END, numerator="4000", basic_eps="4", diluted_eps="3.96",
                         increment=_GENERIC_INCREMENTAL_SHARES)
    annual["eps_treasury_stock_policy"] = [{"snippet": sentence}]
    source = FilingInputs(annual)
    shares = source.select(_WEIGHTED["diluted"], _START, _END, _SHARES_UNIT)
    equation, = _normal_dilution(source, shares)
    assert equation["children"][1]["treasury_stock_policy"][0]["affirmative_method_clause"] == sentence


def test_negative_reported_share_increment_is_not_admitted_by_a_zero_crossing_interval():
    from sec_xbrl.metrics.cal_eps import _normal_dilution

    annual, _ = _standards()
    _mutate_child(annual, value_numeric="-0.1", decimals="0")
    diluted = next(f for f in annual["facts"] if f["raw_concept_id"] == _WEIGHTED["diluted"][0])
    diluted["value_numeric"] = "1000"
    source = FilingInputs(annual)
    shares = source.select(_WEIGHTED["diluted"], _START, _END, _SHARES_UNIT)
    assert source.calculations(shares)[0]["status"] == "VERIFIED"
    with pytest.raises(QualificationError, match="COMPLETE_NORMAL_STOCK_AWARD_DILUTION_CALCULATION_NOT_PROVEN"):
        _normal_dilution(source, shares)


def test_new_ttm_observation_records_its_cal_source_validation_rule():
    from sec_xbrl.metrics.cal_eps import CAL_EPS_RULE
    from sec_xbrl.metrics.cal_eps_preparation import _ttm_output

    output = _ttm_output(
        row={"cik": _CIK, "ticker": "FIXTURE", "candidate_id": "cal-candidate"},
        quarters=[{"start": a, "end": b, "value": "1", "interval": ["0.995", "1.005"]}
                  for a, b in zip((_START, "2025-04-01", "2025-07-01", _Q4),
                                  ("2025-04-01", "2025-07-01", _Q4, _END), strict=True)],
        grant={"currency": "USD", "financial_scope_id": "consolidated",
               "stock_class_id": "common", "split_basis_id": "unadjusted"},
        sources=[{"filed_date": "2026-02-01"}], run={"policy": {}, "filing_catalog": {}},
        basis={"status": "VERIFIED"}, prepared="2026-11-18T04:00:00+00:00",
    )
    assert output["source_validation_rule_version"] == CAL_EPS_RULE
    assert output["historical_ready"] is False


def test_missing_diluted_numerator_uses_complete_attribution_proof_with_its_own_eps_validation():
    annual, nine = _standards(explicit=True)
    diluted = "NetIncomeLossAvailableToCommonStockholdersDiluted"
    for p in (annual, nine):
        p["facts"] = [f for f in p["facts"] if f["raw_concept_id"] != diluted]
        p["relationships"] = [a for a in p["relationships"] if a["from_raw_concept_id"] != diluted]
    proof = _reconstruct(annual, nine)["source_calculation_evidence"]["FY"]
    assert proof["numerator_proof"]["basis"] == "SAME_COMMON_ATTRIBUTION_VIA_PARENT_CAL_AND_NORMAL_DILUTION"
    assert proof["eps"]["selected_fact_id"].endswith("EarningsPerShareDiluted")
    annual["relationships"].pop()
    with pytest.raises(QualificationError, match="DISTINCT_COMMON_ATTRIBUTION"):
        _reconstruct(annual, nine)


def test_augment_adds_current_roles_and_keeps_prior_eps_payload_and_metadata(tmp_path, monkeypatch):
    import hashlib

    from sec_xbrl.metrics.market_inputs import encoded
    from sec_xbrl.metrics.q4_eps_reconstruction import SOURCE_KIND, augment_q4_eps_ttm

    def observation(cik, oid, value, ready):
        return {"cik": cik, "observation_id": oid, "value": value, "source_kind": SOURCE_KIND,
                "currency": "USD", "scope_id": "consolidated", "stock_class_id": "common",
                "split_basis_id": "unadjusted", "period_end": _END, "ready_at": ready}

    prior_obs = observation(_CIK, "old", "12.37", "2026-11-17T19:00:00+00:00")
    new_cik = "0000000002"
    added_obs = observation(new_cik, "new", "20", "2026-11-18T04:00:00+00:00")
    prior_pin = {"path": "/older-artifact.json", "sha256": "old-pin"}
    prior_grant = {"cik": _CIK, "currency": "USD", "financial_scope_id": "consolidated",
                   "stock_class_id": "common", "split_basis_id": "unadjusted",
                   "financial_anchor": _END, "input_ids": {"diluted_eps_12m": "old"},
                   "evidence_pins": [prior_pin]}
    other_grant = dict(prior_grant, cik=new_cik, input_ids={}, evidence_pins=[])
    base = {"q4_component_derivation": prior_pin, "observations": [prior_obs],
            "compatibility_grants": [prior_grant, other_grant],
            "financial_anchors": [{"cik": cik, "known_on": "2026-08-01", "period_end": _END}
                                  for cik in (_CIK, new_cik)],
            "current_eps_diagnostics": [{"cik": new_cik, "reason": "OLD_HOLD"}]}
    payload = encoded(base)
    path = tmp_path / "base.json"
    path.write_bytes(payload)
    artifact = {"schema_version": "governed-common-q4-eps-v2", "public_cutoff": "2026-11-13",
                "prior_derivation": prior_pin,
                "base_financial_bundle": {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()},
                "quarter_results": [{"cik": new_cik, "flavor": "diluted", "status": "QUALIFIED",
                                     "source_validation_rule_version": "common-q4-eps-effective-cal-v1"}],
                "observations": [prior_obs, added_obs], "holds": []}
    monkeypatch.setattr("sec_xbrl.metrics.q4_eps_reconstruction.verify_q4_eps", lambda _: artifact)
    new_pin = {"path": "/new-artifact.json", "sha256": "new-pin"}
    bundle = augment_q4_eps_ttm(new_pin)
    assert bundle["observations"] == [prior_obs, added_obs]
    assert bundle["compatibility_grants"][0] == prior_grant
    assert bundle["compatibility_grants"][1]["input_ids"]["diluted_eps_12m"] == "new"
    assert bundle["compatibility_grants"][1]["evidence_pins"] == [new_pin]
    assert bundle["current_eps_diagnostics"] == []
    assert path.read_bytes() == payload
