// Explicit local prepared publication only. No SEC/parser/producer is invoked.
// See u3-followup-delivery.md for the optional Playwright environment variables.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const html = process.env.SEC_XBRL_HIERARCHY_HTML;
const output = process.env.SEC_XBRL_BROWSER_REPORT;
assert(html && output, 'Explicit prepared HTML and new browser report path required');
const moduleName = process.env.SEC_XBRL_PLAYWRIGHT_MODULE;
const {chromium} = await import(moduleName ? pathToFileURL(moduleName).href : 'playwright');
const browser = await chromium.launch({
  executablePath: process.env.SEC_XBRL_CHROMIUM || undefined,
  headless: true, args: ['--no-sandbox'],
});
const page = await browser.newPage({viewport: {width: 1550, height: 1100}});
const errors = [], network = [];
page.on('pageerror', e => errors.push(e.message));
page.on('request', r => {if (/^https?:/.test(r.url())) network.push(r.url());});
await page.route(/^https?:/, r => r.abort());
const results = {companies: {}, synthetic: {}};
try {
  await page.goto(pathToFileURL(path.resolve(html)).href);
  await page.waitForFunction(() => document.querySelector('#rows tr'));
  for (const ticker of ['NVDA', 'AMD', 'MSFT', 'AMZN', 'AAPL', 'NFLX']) {
    await page.selectOption('#company', ticker);
    await page.waitForFunction(t => window.HIERARCHY_DATA?.filing.cik === window.HIERARCHY_CATALOG[t].filings[0].filing.cik && document.querySelector('#rows tr'), ticker);
    // Historical filing selection must never lend its heading to the company overview.
    const historical = await page.evaluate(t => window.HIERARCHY_CATALOG[t].filings.at(-1).filing.filing_id, ticker);
    await page.selectOption('#filing', historical);
    await page.waitForFunction(id => window.HIERARCHY_DATA?.filing.filing_id === id && document.querySelector('#rows tr'), historical);
    await page.selectOption('#mode', 'analytical');
    assert(await page.locator('#filing').isDisabled());
    assert(await page.locator('#statement').isDisabled());
    const scope = await page.evaluate(() => {
      const ctx = window.HIERARCHY_CATALOG[document.querySelector('#company').value].overview.context;
      const visible = document.querySelector('#scope').textContent;
      return {ctx, visible, accession: window.HIERARCHY_DATA.filing.accession,
        count: document.querySelectorAll('#period-header span').length,
        coverage: document.querySelector('#coverage').textContent,
        cells: [...document.querySelectorAll('[data-cell-id]')].map(e => [e.dataset.cellId, e.dataset.rawValue]),
        expectedCells: window.HIERARCHY_CATALOG[ctx.ticker].overview.cells.map(c => [c.cell_id, c.value ?? ''])};
    });
    for (const value of [ticker, scope.ctx.view, scope.ctx.as_of, scope.ctx.review_cutoff]) {
      if (value) assert(scope.visible.includes(value), `explicit prepared context ${value}`);
    }
    assert(!scope.visible.includes(scope.accession), 'historical accession not an Analytical scope');
    assert(!scope.coverage.includes('원문 표'), 'no historical table coverage on Analytical');
    assert(scope.visible.includes('과거 공시 시점 조회가 아닙니다'));
    assert.equal(scope.count, scope.ctx.periods.length);
    assert.deepEqual(scope.cells.sort(), scope.expectedCells.sort(), 'all values keep prepared scope');
    for (const mode of ['source', 'pre']) {
      await page.selectOption('#mode', mode);
      assert(await page.locator('#filing').isEnabled());
      assert(await page.locator('#statement').isEnabled());
      assert((await page.locator('#scope').textContent()).includes(scope.accession));
    }
    await page.selectOption('#mode', 'analytical');
    await page.selectOption('#explore', 'member');
    assert(await page.locator('#filing').isEnabled());
    assert(await page.locator('#statement').isEnabled());
    assert(await page.locator('#axis').isEnabled());
    assert.equal(await page.locator('#mode').inputValue(), 'source');
    await page.selectOption('#mode', 'analytical');
    assert.equal(await page.locator('#explore').inputValue(), 'statement');
    await page.selectOption('#mode', 'source');
    // Return to latest source/PRE for actual critical warning assertions.
    const latest = await page.evaluate(t => window.HIERARCHY_CATALOG[t].filings[0].filing.filing_id, ticker);
    await page.selectOption('#filing', latest);
    await page.waitForFunction(id => window.HIERARCHY_DATA?.filing.filing_id === id && document.querySelector('#rows tr'), latest);
    await page.selectOption('#mode', 'pre');
    await page.click('#collapse');
    await page.selectOption('#depth', '0');
    const warnings = await page.evaluate(() => {
      const panel = window.HIERARCHY_DATA.panels[document.querySelector('#statement').value];
      return (window.HIERARCHY_DATA.pre[panel.table.table_id] || []).flatMap(r => {
        const expected = panel.importance.filter(i => r.facts.some(f => f.fact_id === i.current_fact_id))
          .flatMap(i => i.warnings || []).filter(w => /SIGN|BASE|BASIS|SCOPE|INCOMPATIBLE|SCALAR_UNAVAILABLE|REVIEW_REQUIRED|BLOCK|QUARANTINE/.test(w));
        const tr = [...document.querySelectorAll('#rows tr')].find(e => e.dataset.rowId === r.row_id);
        return expected.length ? [{qname: r.concept.qname, expected, hidden: tr.hidden,
          rendered: [...tr.querySelectorAll('.badge.warn')].map(e => e.textContent)}] : [];
      });
    });
    for (const row of warnings) {
      assert(!row.hidden, `${ticker} PRE warning cannot collapse: ${row.qname}`);
      for (const warning of row.expected) assert(row.rendered.includes(warning));
    }
    if (ticker === 'AMD') {
      for (const name of ['IncomeTaxExpenseBenefit', 'DiscontinuedOperations']) {
        assert(warnings.some(r => r.qname.includes(name)), `actual AMD warning ${name}`);
      }
    }
    assert.equal(await page.locator('table').count(), 1);
    const duration = await page.locator('#period-header').textContent();
    assert(duration.includes('(종료일 제외)'), `${ticker} duration end is exclusive`);
    const isValues = await page.locator('#rows .value small').allTextContents();
    assert(isValues.some(t => t.includes('(종료일 제외)')));
    const bs = await page.evaluate(() => window.HIERARCHY_DATA.tables.find(t => t.section === 'BS').table_id);
    await page.selectOption('#statement', bs);
    assert((await page.locator('#period-header').textContent()).includes('(시점)'));
    assert(!(await page.locator('#period-header').textContent()).includes('(종료)'));
    results.companies[ticker] = {historicalAnalyticalContext: 'PASS', controlsRestore: 'PASS',
      criticalPREWarnings: warnings, periodLabels: 'PASS'};
    await page.selectOption('#mode', 'source');
  }
  // Synthetic exact-ID boundary: warning on another same-concept fact cannot leak.
  results.synthetic = await page.evaluate(() => {
    const panel = D.panels[table.table_id], saved = D.pre[table.table_id];
    const fact = panel.facts[0];
    const warnings = ['ZERO_OR_NEGATIVE_BASE_OR_SIGN_CHANGE', 'SMALL_BASE_OR_SMALL_ABSOLUTE_CHANGE', 'INCOMPATIBLE_SCOPE'];
    const row = (id, parent, depth, facts) => ({row_id: id, parent_row_id: parent, depth,
      concept: fact.concept, facts, protected: false, warnings: []});
    try {
      D.pre[table.table_id] = [row('synthetic-parent', null, 0, []), row('synthetic-exact', 'synthetic-parent', 7, [fact]),
        row('synthetic-unrelated', 'synthetic-parent', 7, [{...fact, fact_id: 'other-id'}])];
      displayRows = preRows({...panel, importance: [{current_fact_id: fact.fact_id, warnings, reasons: []}]});
      collapsed = new Set(['synthetic-parent']);document.querySelector('#depth').value = '0';draw();
      const exact = document.querySelector('[data-row-id="synthetic-exact"]');
      const unrelated = document.querySelector('[data-row-id="synthetic-unrelated"]');
      return {exactVisible: !exact.hidden, exactWarnings: [...exact.querySelectorAll('.badge.warn')].map(e => e.textContent),
        unrelatedHidden: unrelated.hidden, unrelatedWarnings: unrelated.querySelectorAll('.badge.warn').length,
        expected: warnings, duration: periodLabel({class: 'QTD_3M', start: '2024-01-01', end: '2024-04-01'}),
        instant: periodLabel({class: 'INSTANT', instant: '2024-04-01'})};
    } finally {D.pre[table.table_id] = saved;render();}
  });
  assert(results.synthetic.exactVisible);
  assert.deepEqual(results.synthetic.exactWarnings, results.synthetic.expected);
  assert(results.synthetic.unrelatedHidden);
  assert.equal(results.synthetic.unrelatedWarnings, 0);
  assert.equal(results.synthetic.duration, 'QTD_3M · 2024-01-01 → 2024-04-01 (종료일 제외)');
  assert.equal(results.synthetic.instant, 'INSTANT · 2024-04-01 (시점)');
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  results.publication = await page.evaluate(() => window.HIERARCHY_PUBLICATION);
  results.status = 'PASS';
  results.javascriptErrors = errors;results.networkAttempts = network;
  fs.writeFileSync(output, JSON.stringify(results, null, 2) + '\n');
  console.log(JSON.stringify({status: 'PASS', companies: Object.keys(results.companies), publication: results.publication}));
} finally {await browser.close();}
