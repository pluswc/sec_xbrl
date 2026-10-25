"""Unrelated optional Inline IDs do not widen the source conformance scope."""
from pathlib import Path

import pytest

from sec_xbrl.source_bindings import SEC_TRANSFORM_NAMESPACE, _extract_source_rows, _FilingScope


def _document(tags):
    return (f'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
            f'xmlns:ixt-sec="{SEC_TRANSFORM_NAMESPACE}" xmlns:test="https://example.test/2026"><head><meta charset="utf-8"/></head><body>'
            + tags + '</body></html>').encode()


def _filing():
    return _FilingScope("TEST","0000000999","0000000999-22-000001","issuer.htm",Path("/unused"),Path("/unused/manifest.json"))


def test_unrelated_optional_ids_match_actual_metadata_shape_and_are_ignored():
    unrelated=[("boolballotbox","☒"),("boolballotbox","☐"),
               ("stateprovnameen","Utah"),("stateprovnameen","Nebraska"),
               ("exchnameen","NYSE"),("exchnameen","New York Stock Exchange"),
               ("entityfilercategoryen","Large accelerated filer"),
               ("entityfilercategoryen","Non-accelerated filer"),("boolballotbox","☒")]
    tags=''.join(f'<ix:nonNumeric name="test:Metadata" contextRef="meta" format="ixt-sec:{transform}">{lexical}</ix:nonNumeric>'
                 for transform,lexical in unrelated)
    tags+='<ix:nonNumeric id="supported" name="test:ExpectedLife" contextRef="duration" format="ixt-sec:duryear">1.5</ix:nonNumeric>'
    rows=_extract_source_rows(_document(tags),_filing())
    assert len(rows)==1
    assert next(iter(rows.values()))["source_id"]=="supported"


@pytest.mark.parametrize(("transform","lexical"),[
    ("durday","1"),("durmonth","1"),("duryear","1"),("durweek","1"),
    ("exchnameen","Nasdaq"),("stateprovnameen","Idaho"),
    ("durwordsen","three\N{NON-BREAKING HYPHEN}year"),
    ("durwordsen","five\N{NON-BREAKING HYPHEN}year"),("numwordsen","nil"),
])
def test_supported_duration_and_correction_sources_still_require_id(transform,lexical):
    tag=f'<ix:nonNumeric name="test:Supported" contextRef="context" format="ixt-sec:{transform}">{lexical}</ix:nonNumeric>'
    with pytest.raises(ValueError,match="source fields are incomplete"):
        _extract_source_rows(_document(tag),_filing())
