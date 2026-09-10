// Actual prepared responses are the browser oracle. Monetary values never calculated here.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.env.SEC_XBRL_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({executablePath:process.env.SEC_XBRL_CHROMIUM,headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1550,height:1100}}),errors=[],network=[],results={companies:{}};
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url())});await page.route(/^https?:/,r=>r.abort());
try{
 await page.goto(pathToFileURL(process.env.SEC_XBRL_HIERARCHY_HTML).href);
 await page.waitForFunction(()=>document.querySelector('#rows tr')&&window.AXIS_DATA);
 assert.equal(await page.locator('#mode').inputValue(),'analytical');
 for(const ticker of ['NVDA','AMD','MSFT','AMZN','AAPL','NFLX']){
  await page.selectOption('#company',ticker);
  await page.waitForFunction(t=>window.AXIS_COMPANY===t&&window.HIERARCHY_DATA?.filing.cik===window.HIERARCHY_CATALOG[t].filings[0].filing.cik&&document.querySelector('#rows tr'),ticker);
  await page.selectOption('#mode','analytical');
  const overview=await page.evaluate(()=>({rows:document.querySelectorAll('#rows tr').length,headers:document.querySelectorAll('#financial-table th[data-period]').length,expected:window.HIERARCHY_CATALOG[document.querySelector('#company').value].overview.context.periods.length}));
  assert.equal(overview.headers,overview.expected);
  if(ticker==='NVDA'){
   const entry=page.locator('#rows tr[data-row-id="analytical:revenue"] td').first().getByRole('button',{name:'구성 보기',exact:true});
   const box=await entry.boundingBox();assert(box&&box.x>=0&&box.x+box.width<=1550,'entry visible without horizontal scroll');
   await entry.click();assert.notEqual(await page.locator('#analytical-axis').inputValue(),'');
  }
  const lenses=await page.evaluate(()=>window.HIERARCHY_CATALOG[document.querySelector('#company').value].axis_lenses);
  let checkedCells=0;
  for(const lens of lenses){
   await page.selectOption('#metric',lens.anchor_row_id);await page.selectOption('#analytical-axis',lens.node_id);
   const evidence=await page.evaluate(id=>{
    const a=window.AXIS_DATA[id], rows=[...document.querySelectorAll('#rows tr')],headers=[...document.querySelectorAll('#financial-table th[data-period]')];
    return {expected:a.rows.length,actual:rows.length,alignment:rows.every(r=>[...r.querySelectorAll('.quarter-cell')].every((td,i)=>Math.abs(td.getBoundingClientRect().x-headers[i].getBoundingClientRect().x)<1&&Math.abs(td.getBoundingClientRect().width-headers[i].getBoundingClientRect().width)<1)),
     values:rows.flatMap(r=>[...r.querySelectorAll('.quarter-cell .value')].map((e,i)=>({id:r.dataset.rowId,i,value:e.dataset.rawValue,status:e.dataset.sourceStatus,fact:e.dataset.factId}))),
     expectedValues:a.rows.flatMap(r=>r.cells.map((c,i)=>({id:r.row_id,i,value:c.value??'',status:c.status,fact:c.source_fact_id||''}))),
     scopes:rows.slice(1).every(r=>r.querySelector('.epoch-scope')?.textContent.includes('관측 ')),
     proof:a.publication,exact:a.reviewed_relationships.filter(c=>c.display_scope==='ANALYTICAL_EXACT_MATCH').length,
     visibleIds:rows.map(r=>r.dataset.rowId),expectedIds:a.rows.map(r=>r.row_id)};
   },lens.node_id);
   assert.equal(evidence.actual,evidence.expected);assert(evidence.alignment,`${ticker} real shared quarter geometry`);assert(evidence.scopes,'visible distinct epoch coverage');assert.deepEqual(evidence.values,evidence.expectedValues);assert.deepEqual(evidence.visibleIds,evidence.expectedIds);checkedCells+=evidence.values.length;
   await page.click('#collapse');await page.selectOption('#depth','0');
   const hiddenProtected=await page.evaluate(()=>[...document.querySelectorAll('#rows tr')].some(r=>(r.dataset.protected==='true'||r.querySelector('.warn'))&&r.hidden));assert(!hiddenProtected);
   await page.click('#restore');assert.equal(await page.locator('#rows tr[hidden]').count(),0);
   if(ticker==='NVDA'&&evidence.exact===2){
    assert.equal(evidence.actual,39);
    const filing=await page.evaluate(id=>window.AXIS_DATA[id].source_comparisons[0].table.filing,lens.node_id);
    const sourceContext=await page.locator('.source-comparison-context').textContent();
    for(const value of [filing.form,filing.accession,filing.report_date,filing.filed_date])assert(sourceContext.includes(value));
    assert((await page.locator('.source-comparison-context a').getAttribute('href')).includes(filing.accession.replaceAll('-','')));
    assert(await page.getByRole('button',{name:'검토된 원문 구성 비교 ↓',exact:true}).isVisible());assert.equal(await page.locator('#source-comparison tbody tr').count(),8);
    assert.equal(await page.locator('#source-comparison thead th').count(),3);
    assert((await page.locator('#source-comparison').textContent()).includes('역사적 Analytical 선택을 대체하지 않습니다'));
    const height=await page.locator('#rows tr').first().evaluate(r=>r.getBoundingClientRect().height);assert(height<200,`compact total row ${height}`);
    await page.locator('#rows tr').first().locator('.proof').first().click();const inspection=await page.locator('#inspection').textContent();assert(inspection.includes(evidence.proof.axis_publication_id));assert(inspection.includes(evidence.proof.axis_decision_cutoff));await page.click('#close-inspector');
    await page.screenshot({path:process.env.SEC_XBRL_AXIS_SCREENSHOT,fullPage:false});
   }
  }
  await page.selectOption('#mode','source');assert.equal(await page.locator('#financial-table thead th').count(),3);assert.equal(await page.locator('#period-header').count(),1);assert(await page.locator('#filing').isEnabled());
  await page.selectOption('#mode','pre');assert.equal(await page.locator('#financial-table thead th').count(),3);
  results.companies[ticker]={axes:lenses.length,checkedCells,geometry:'PASS',nullAndOriginParity:'PASS',epochs:'PASS',collapseAndRestore:'PASS',sourcePRETransition:'PASS'};
 }
 assert.deepEqual(errors,[]);assert.deepEqual(network,[]);results.status='PASS';results.network=network;results.errors=errors;
 fs.writeFileSync(process.env.SEC_XBRL_BROWSER_REPORT,JSON.stringify(results,null,2));
}finally{await browser.close()}
