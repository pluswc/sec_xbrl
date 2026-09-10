// Offline U5 controls must follow the selected prepared table without network access.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';

const {chromium}=await import(pathToFileURL(process.env.SEC_XBRL_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({executablePath:process.env.SEC_XBRL_CHROMIUM,headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1550,height:1100}}),errors=[],network=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('request',request=>{if(/^https?:/.test(request.url()))network.push(request.url())});
await page.route(/^https?:/,route=>route.abort());
try{
  await page.goto(pathToFileURL(process.env.SEC_XBRL_HIERARCHY_HTML).href);
  await page.waitForFunction(()=>document.querySelector('#rows tr')&&window.AXIS_DATA);
  await page.selectOption('#company','NFLX');
  await page.waitForFunction(()=>window.AXIS_COMPANY==='NFLX'&&document.querySelector('#rows tr'));
  const initialURL=page.url(),downloads=[];
  async function saveScope(scope){
    for(const ext of ['json','csv','html','xlsx']){
      const link=page.locator('#export-'+ext),source=fileURLToPath(await link.evaluate(element=>element.href));
      const [download]=await Promise.all([page.waitForEvent('download'),link.click()]);
      const saved=`${process.env.SEC_XBRL_DOWNLOAD_DIR}/${scope}.${ext}`;await download.saveAs(saved);
      assert.deepEqual(fs.readFileSync(saved),fs.readFileSync(source));
      assert.equal(page.url(),initialURL);downloads.push({scope,ext,bytes:fs.statSync(saved).size});
    }
  }
  await saveScope('overview');
  const rapid=[];page.on('download',download=>rapid.push(download));
  await page.evaluate(()=>{document.querySelector('#export-json').click();document.querySelector('#export-html').click()});
  await page.waitForFunction(()=>document.querySelectorAll('script[src$=".download.js"]').length===0);
  for(let attempt=0;attempt<250&&rapid.length<2;attempt++)await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(rapid.length,2,'rapid downloads completed within five seconds');
  assert.deepEqual(new Set(rapid.map(download=>download.suggestedFilename())),new Set(['overview.json','overview.html']));
  await page.selectOption('#metric','revenue');
  const metricJSON=JSON.parse(fs.readFileSync(fileURLToPath(await page.locator('#export-json').evaluate(element=>element.href)),'utf8'));
  assert.deepEqual(metricJSON.selection.row_ids,['revenue']);assert.equal(metricJSON.cells.length,14);
  await saveScope('metric');
  const lens=await page.evaluate(()=>window.HIERARCHY_CATALOG.NFLX.axis_lenses[0]);
  await page.selectOption('#metric',lens.anchor_row_id);await page.selectOption('#analytical-axis',lens.node_id);
  await saveScope('axis');
  await page.selectOption('#mode','source');
  assert.equal(await page.locator('#export-xlsx').getAttribute('aria-disabled'),'true');
  assert((await page.locator('#export-note').textContent()).includes('Analytical'));
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  fs.writeFileSync(process.env.SEC_XBRL_BROWSER_REPORT,JSON.stringify({status:'PASS',downloads,network,errors},null,2));
}finally{await browser.close()}
