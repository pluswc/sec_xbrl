from html.parser import HTMLParser

from sec_xbrl.screening.ui import CSS, HTML, JS


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _visible_copy() -> str:
    parser = _Text()
    parser.feed(HTML)
    return " ".join(parser.parts)


def test_ordinary_screen_uses_investor_language_and_hides_admin_clutter() -> None:
    copy = _visible_copy()
    assert "어떤 기업을 찾으시나요?" in copy
    assert "성장성" in copy and "수익성" in copy
    assert "현금흐름" in copy and "재무안정성" in copy and "공시항목" in copy
    assert "금액 기준: 백만 달러" in copy
    for forbidden in (
        "SEC SIC", "CIK", "UNKNOWN_SIC", "ACTUAL_PREPARED",
        "PREDICATE_MATCHED", "기술 근거", "회사·산업 후보 찾기",
    ):
        assert forbidden not in copy


def test_catalog_units_and_durable_workflows_are_bound_without_browser_math() -> None:
    assert "/api/metric-catalog?dataset_id=" in JS
    assert 'unit_kind==="MONEY"' in JS
    assert "thresholdToApi" in JS and "thresholdFromApi" in JS
    assert 'shiftDecimal(v,m.unit_kind==="MONEY"?6:0)' in JS
    assert "definition_version:m.definition_version" in JS
    assert "input_metric_ids" in JS
    assert "/trace?cik=" in JS
    assert "companies_available" in JS
    assert "/api/screens" in JS and "/api/runs" in JS and "/api/decisions" in JS
    assert "localStorage" not in HTML + JS


def test_accessibility_compact_results_and_admin_mode_contract() -> None:
    assert 'class="skip"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'e.key==="Escape"' in JS
    assert "S.lastFocus" in JS
    assert "@media(max-width:1100px)" in CSS
    assert ":focus-visible" in CSS
    assert ".criteria.compact" in CSS
    assert 'get("mode")==="admin"' in JS
    assert "mountAdmin" in JS
    assert "columnEnabled" in JS
    assert 'id="company-query"' in HTML
    assert "renderCompanyOptions" in JS
    assert "저장된 정렬" in JS
