import fs from 'node:fs';
import {pathToFileURL} from 'node:url';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const base = process.env.SEC_XBRL_SCREENING_URL;
const modulePath = process.env.SEC_XBRL_PLAYWRIGHT_MODULE;
const executablePath = process.env.SEC_XBRL_CHROMIUM;
assert(base && modulePath && executablePath, 'URL, Playwright module, and Chromium are required');
const {chromium} = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({headless: true, executablePath});
const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
const posts = [];
const external = [];
const errors = [];
page.on('request', request => {
  if (request.method() === 'POST') posts.push(request.url());
  if (!request.url().startsWith(base)) external.push(request.url());
});
page.on('pageerror', error => errors.push(String(error)));

try {
  await page.goto(base, {waitUntil: 'networkidle'});
  await page.locator('#explorer-body tr').first().waitFor();
  assert(await page.locator('#explorer-body tr').count() === 21, 'cold start must show 21 rows');
  const matrixFit = await page.locator('.explorer-matrix').evaluate(
    element => element.scrollWidth <= element.clientWidth,
  );
  assert(matrixFit, 'eight-column matrix must fit at 1440px');
  const matrixText = await page.locator('#explorer-table').innerText();
  assert((matrixText.match(/백만 달러/g) || []).length <= 8, 'units must stay in headings');
  assert(!matrixText.includes('자료 조건을 충족하지 않음'), 'missing cells must stay concise');

  assert(await page.locator('[data-view="library"]').isVisible(), 'metric-guide navigation hidden');
  await page.locator('[data-view="library"]').click({force: true});
  const filteredGuide = page.waitForResponse(response =>
    response.url().includes('/api/metric-library?') && response.url().includes('query='),
  );
  await page.locator('#library-query').fill('영업이익률');
  await filteredGuide;
  await page.waitForFunction(() => document.querySelectorAll('.metric-card').length === 1);
  await page.locator('.metric-card').filter({has: page.locator('h4', {hasText: /^영업이익률$/})}).waitFor();
  const filteredCategory = page.waitForResponse(response =>
    response.url().includes('/api/metric-library?') && response.url().includes('category=PROFITABILITY'),
  );
  await page.locator('#library-category').selectOption('PROFITABILITY');
  await filteredCategory;
  assert(await page.locator('.metric-card').count() === 1, 'guide search must filter only the visible cards');

  await page.locator('[data-view="explorer"]').click({force: true});
  assert((await page.locator('#explorer-head').innerText()).includes('영업이익률\n%'), 'filtered guide corrupted percent metadata');
  const compareChecks = page.locator('[data-explorer-select]');
  for (const index of [0, 1]) {
    await compareChecks.nth(index).evaluate(element => {
      element.checked = true;
      element.dispatchEvent(new Event('change', {bubbles: true}));
    });
  }
  await page.locator('#compare-selected').click({force: true});
  assert(await page.locator('#comparison-metrics option').count() === 31, 'filtered guide truncated comparison metrics');
  assert(await page.locator('#comparison-metrics option[value="operating_margin"]').innerText() === '영업이익률', 'comparison label lost');
  await page.locator('#close-comparison').click({force: true});

  await page.locator('[data-view="history"]').click({force: true});
  const oldRun = page.locator('#old-run option').nth(1);
  await oldRun.waitFor({state: 'attached'});
  await page.locator('#old-run').selectOption(await oldRun.getAttribute('value'));
  const runResponse = page.waitForResponse(response => /\/api\/runs\/run-/.test(response.url()));
  const revisionResponse = page.waitForResponse(response => response.url().includes('/api/revisions/'));
  await page.locator('#open-run').click({force: true});
  await Promise.all([runResponse, revisionResponse]);
  await page.waitForFunction(() => document.querySelector('#dataset')?.value.includes('annual'));
  await page.locator('[data-view="library"]').click({force: true});
  const margin = page.locator('.metric-card').filter({has: page.locator('h4', {hasText: /^영업이익률$/})}).first();
  await margin.locator('input').fill('.5');
  assert(await margin.locator('button').isVisible(), 'margin add button hidden');
  await margin.locator('button').click({force: true});
  await page.waitForTimeout(1000);
  assert(
    await page.locator('.predicate').count() === 2,
    `compatible v1 copy failed: ${await page.locator('#criteria-error').innerText()}`,
  );
  assert(
    (await page.locator('.predicate .metric').evaluateAll(nodes => nodes.map(node => node.value))).join(',') ===
      'revenue,operating_margin',
    'filtered guide rejected or discarded the compatible v1 revenue condition',
  );
  await page.locator('#screen-name').fill('누적 draft 보존');
  await page.locator('#period-mode').selectOption('FIXED_FISCAL_YEAR');
  await page.locator('#fiscal-year').fill('2024');
  await page.locator('#universe-mode').selectOption('CIKS');
  const firstCompany = await page.locator('#company-select option').first().getAttribute('value');
  await page.locator('#company-select').selectOption(firstCompany);
  await page.locator('.predicate .threshold').first().fill('.75');
  await page.locator('.predicate .operator').first().selectOption('GT');
  await page.locator('.view-settings').evaluate(element => { element.open = true; });
  await page.locator('#sort-direction').selectOption('DESC');
  await page.locator('[name="visible-column"][value="decision"]').evaluate(element => {
    element.checked = false;
    element.dispatchEvent(new Event('change', {bubbles: true}));
  });

  await page.locator('[data-view="library"]').click({force: true});
  const clearedCategory = page.waitForResponse(response =>
    response.url().includes('/api/metric-library?') && !response.url().includes('category='),
  );
  await page.locator('#library-category').selectOption('');
  await clearedCategory;
  const growthGuide = page.waitForResponse(response =>
    response.url().includes('/api/metric-library?') && response.url().includes('query='),
  );
  await page.locator('#library-query').fill('매출 전년 대비 성장률');
  await growthGuide;
  await page.waitForFunction(() => document.querySelectorAll('.metric-card').length === 1);
  const growth = page.locator('.metric-card').filter({has: page.locator('h4', {hasText: /^매출 전년 대비 성장률$/})}).first();
  await growth.locator('input').fill('.5');
  assert(await growth.locator('button').isVisible(), 'growth add button hidden');
  await growth.locator('button').click({force: true});
  await page.waitForFunction(() => document.querySelectorAll('.predicate').length === 3);
  assert(await page.locator('#screen-name').inputValue() === '누적 draft 보존', 'name was discarded');
  assert(await page.locator('#fiscal-year').inputValue() === '2024', 'fiscal year was discarded');
  assert(await page.locator('#universe-mode').inputValue() === 'CIKS', 'universe was discarded');
  assert((await page.locator('#company-select').inputValue()) === firstCompany, 'company was discarded');
  assert(await page.locator('#sort-direction').inputValue() === 'DESC', 'sort was discarded');
  assert(!(await page.locator('[name="visible-column"][value="decision"]').isChecked()), 'columns were discarded');
  assert(
    (await page.locator('.predicate .metric').evaluateAll(nodes => nodes.map(node => node.value))).join(',') ===
      'revenue,operating_margin,revenue_yoy',
    'guide additions did not accumulate',
  );
  assert(
    (await page.locator('.predicate .threshold').evaluateAll(nodes => nodes.map(node => node.value))).join(',') ===
      '.75,0.5,0.5',
    'thresholds were discarded',
  );
  assert(
    (await page.locator('.predicate .operator').evaluateAll(nodes => nodes.map(node => node.value))).join(',') ===
      'GT,GTE,GTE',
    'operators were discarded',
  );

  await page.locator('[data-view="explorer"]').click({force: true});
  await page.locator('button.company', {hasText: 'AMD'}).first().click();
  await page.locator('#profile-chart svg').waitFor({state: 'visible'});
  const geometry = [];
  for (const width of [1440, 1024, 768]) {
    await page.setViewportSize({width, height: 900});
    const chart = await page.locator('#profile-chart').boundingBox();
    const svg = await page.locator('#profile-chart svg').boundingBox();
    const series = await page.locator('#profile-series').boundingBox();
    geometry.push({
      width,
      contained: svg.y >= chart.y && svg.y + svg.height <= chart.y + chart.height + 1,
      clear: chart.y + chart.height <= series.y + 1,
    });
  }
  assert(geometry.every(item => item.contained && item.clear), 'profile chart escaped its panel');
  assert(await page.locator('#profile-chart .year-label').count() === 4, 'fiscal-year labels missing');
  assert(await page.locator('#profile-chart .value-label').count() >= 3, 'value labels missing');
  assert(!posts.length, 'read-only explorer flow issued POST');
  assert(!external.length, 'explorer issued an external request');
  assert(!errors.length, 'browser page error occurred');
  const report = {status: 'PASS', matrixFit, geometry, posts, external, errors};
  if (process.env.SEC_XBRL_BROWSER_REPORT) {
    fs.writeFileSync(process.env.SEC_XBRL_BROWSER_REPORT, JSON.stringify(report, null, 2));
  }
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
