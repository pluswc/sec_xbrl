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
    assert 'q=w.length+Number(m[4]||0)+p-leading' in JS
    assert 'if(/^0+$/.test(raw))return"0"' in JS
    assert "definition_version:m.definition_version" in JS
    assert "input_metric_ids" in JS
    assert "/trace?cik=" in JS
    assert "companies_available" in JS
    assert 'class="field-caption">기준값 (<span class="threshold-unit"></span>)</span>' in JS
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
    assert "companySelection:new Set()" in JS
    assert "syncCompanySelection" in JS
    assert "ciks:[...S.companySelection]" in JS
    assert "#company-query" in JS
    assert "저장된 정렬" in JS
    assert "defaultDataset:null" in JS and "contextToken:0" in JS
    assert "await loadInputContext(r.dataset_id)" in JS
    assert "await loadInputContext(d.dataset_id)" in JS


def test_explorer_is_the_default_read_only_task_surface() -> None:
    assert 'data-task-view="explorer"' in HTML
    assert 'data-task-view="library"' in HTML
    assert 'data-task-view="screening" hidden' in HTML
    assert 'data-task-view="history" hidden' in HTML
    assert "await loadExplorer();await loadLibrary();const initial=" in JS
    assert '"#results-title":"screening"' in JS
    assert "/api/explorer?" in JS
    assert "/api/metric-library?" in JS
    assert "/api/company-profile?" in JS
    assert "/api/company-comparison?" in JS
    assert "explorerDataset" in JS
    assert "async function newScreen" in JS and "조건에 추가" in HTML + JS


def test_explorer_preserves_missing_periods_and_display_only_date_conversion() -> None:
    assert "선택 연도 자료 없음" in JS
    assert "누락 연도는 연결하지 않습니다" in JS
    assert 'class="line"' in JS and 'class="point"' in JS
    assert "inclusiveEnd" in JS
    assert "setUTCDate(d.getUTCDate()-1)" in JS
    assert "배타적 컨텍스트 종료일" not in JS
    assert ".trend-chart svg{display:block;width:100%;height:100%;overflow:hidden}" in CSS
    assert 'class="year-label' in JS
    assert 'class="value-label"' in JS


def test_metric_guide_uses_exact_existing_threshold_scaling_without_autosave() -> None:
    guide = JS[JS.index("async function addGuideMetric"):JS.index("function profileObservationCell")]
    assert "thresholdToApi(threshold,m)" in guide
    assert "definition_version:m.definition_version" in guide
    assert "await newScreen()" not in guide
    assert "guideCompatibility" in JS
    assert "loadScreenRecord({name,content" in guide
    assert "duplicate&&!pristine" in guide
    assert 'value="FIXED_FISCAL_YEAR"' in guide
    assert '$("#fiscal-year").value=String(S.explorerYear)' in guide
    assert "saveScreen" not in guide
    assert 'api("/api/screens"' not in guide


def test_explorer_matrix_uses_heading_units_and_concise_missing_cells() -> None:
    assert "CORE_SHORT_LABELS" in JS
    assert 'm.label)}<small>${esc(unitLabel(m))}</small>' in JS
    assert 'aria-label="자료 없음:' in JS
    explorer_value = JS[JS.index("function explorerValue"):JS.index("function updateExplorerSort")]
    assert "reason_labels" in explorer_value
    assert "<small>" not in explorer_value
    assert "min-width:1180px;table-layout:fixed" in CSS
    assert "min-width:1480px" not in CSS
    assert '.metric-card h4{margin:3px 0 0;font-size:16px;font-weight:600}' in CSS
    comparison = JS[JS.index("async function renderComparison"):JS.index("function openComparison")]
    assert "지표 · 단위" in comparison
    assert "unitLabel(row.metric)" in comparison


def test_filtered_metric_guide_cannot_replace_complete_explorer_catalog() -> None:
    assert "explorerCatalog:null" in JS
    assert "explorerCatalogKey:null" in JS
    assert "async function loadExplorerCatalog" in JS
    load = JS[JS.index("async function loadExplorerCatalog"):JS.index("async function loadExplorer(year")]
    assert "/api/metric-library?dataset_id=" in load
    assert "&fiscal_year=" in load
    assert "query" not in load
    assert "category" not in load
    assert "S.explorerCatalog=r" in load
    filtered = JS[JS.index("async function loadLibrary"):JS.index("function guideCompatibility")]
    assert 'params.set("query",q)' in filtered
    assert 'params.set("category",c)' in filtered
    assert "S.library=r" in filtered
    assert "S.explorerCatalog?.metrics" in JS[JS.index("function guideCompatibility"):]
    assert "S.explorerCatalog?.metrics||[]" in JS[JS.index("function openComparison"):]
    metric = JS[JS.index("function explorerMetric"):JS.index("function updateExplorerSort")]
    assert "S.explorerCatalog?.metrics.find" in metric
    assert 'label:id,unit_kind:"MONEY"' not in metric
