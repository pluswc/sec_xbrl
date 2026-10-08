from sec_xbrl.screening.ui import CSS, HTML, JS


def test_screening_ui_exposes_governed_workflows_without_client_storage() -> None:
    assert "task-nav" in HTML
    assert "metadata-prev" in HTML and "metadata-next" in HTML
    assert "전체 XLSX" in HTML and "선택 CSV" in HTML
    assert "사용자 판단 기록" in HTML
    assert "localStorage" not in HTML + JS
    assert "/api/runs/${encodeURIComponent(S.run.run_id)}/trace" in JS
    assert "download_url" in JS
    assert "ACTUAL_PERIOD_REQUIRED" in JS
    assert "조건 펼치기" in JS
    assert "실제 준비 자료" in JS and "검증용 자료" in JS
    assert "canonical 원문" in JS
    assert "function isRevisionEdit(target)" in JS
    assert 'target.closest("#saved-screen,#dataset")' in JS
    assert 'addEventListener("change",trackRevisionEdit)' in JS


def test_screening_ui_keeps_accessibility_and_compact_desktop_contract() -> None:
    assert 'class="skip"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'event.key==="Escape"' in JS
    assert 'S.lastFocus?.focus()' in JS
    assert "@media(max-width:1100px)" in CSS
    assert ":focus-visible" in CSS
    assert "aria-controls=\"criteria-form\"" in HTML
    assert ".criteria.compact" in CSS
    assert "다음 실행 데이터셋" in HTML
