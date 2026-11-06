"""Exact signed zero source conformance under the existing numwordsen nil scope."""
from decimal import Decimal

import pytest

from sec_xbrl.metric_quality import _approved_expected, _raw_matches


def _binding(**changes):
    return {"transform":"numwordsen","source_lexical":"nil","source_sign":"-",
            "actual_raw_value":"-0","actual_value_numeric":"-0","actual_value_text":None,
            "actual_is_nil":False,**changes}


@pytest.mark.parametrize("numeric",["-0",Decimal("-0")])
def test_declared_negative_nil_matches_exact_signed_raw_zero_without_rewriting_evidence(numeric):
    binding=_binding(actual_value_numeric=numeric)
    before=dict(binding)
    assert _raw_matches(binding,_approved_expected("numwordsen","nil"))
    assert binding==before
    assert binding["source_sign"]=="-"
    assert binding["actual_raw_value"]=="-0"


def test_existing_unsigned_nil_zero_remains_exact():
    assert _raw_matches(_binding(source_sign=None,actual_raw_value="0",actual_value_numeric="0"),"0")


@pytest.mark.parametrize("changes",[
    {"actual_raw_value":"-1","actual_value_numeric":"-1"},
    {"actual_raw_value":"NaN","actual_value_numeric":"NaN"},
    {"actual_raw_value":"-0","actual_value_numeric":"NaN"},
    {"actual_is_nil":True},
    {"actual_value_text":"nil"},
    {"actual_raw_value":"0"},
    {"actual_value_numeric":"0"},
    {"actual_value_numeric":None},
])
def test_signed_nil_still_rejects_nonzero_nonfinite_nil_text_and_sign_mismatches(changes):
    assert not _raw_matches(_binding(**changes),"0")
