// Offline U5 controls must follow the selected prepared table without network access.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
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
  await page.selectOption('#metric','revenue');
  const links=await page.evaluate(()=>Object.fromEntries(['json','csv','html','xlsx'].map(ext=>[ext,document.querySelector('#export-'+ext).href])));
  assert(Object.values(links).every(Boolean));
  const json=JSON.parse(fs.readFileSync(fileURLToPath(links.json),'utf8'));
  assert.deepEqual(json.selection.row_ids,['revenue']);
  assert.equal(json.selection.periods.length,14);
  assert.equal(json.cells.length,14);
  assert.equal(json.display_policy.unit_divisor,'1');
  const csv=fs.readFileSync(fileURLToPath(links.csv),'utf8');
  assert(csv.includes(json.snapshot_id));
  assert.equal((csv.match(/\nCELL,/g)||[]).length,14);
  const html=fs.readFileSync(fileURLToPath(links.html),'utf8');
  assert(html.includes(json.snapshot_id));
  assert(fs.statSync(fileURLToPath(links.xlsx)).size>5000);
  await page.selectOption('#analytical-axis','');
  await page.selectOption('#mode','source');
  assert.equal(await page.locator('#export-xlsx').getAttribute('aria-disabled'),'true');
  assert((await page.locator('#export-note').textContent()).includes('Analytical'));
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  fs.writeFileSync(process.env.SEC_XBRL_BROWSER_REPORT,JSON.stringify({status:'PASS',links:Object.fromEntries(Object.entries(links).map(([key,value])=>[key,path.basename(fileURLToPath(value))])),rows:json.cells.length,network,errors},null,2));
}finally{await browser.close()}
