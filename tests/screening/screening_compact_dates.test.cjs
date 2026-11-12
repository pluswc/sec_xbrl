"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
function harness(){
  const context=vm.createContext({URLSearchParams,location:{search:""},Node:{TEXT_NODE:3},document:{querySelector(){return null},querySelectorAll(){return[]}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  vm.runInContext(source.slice(source.indexOf("function tablePresentationRole("),source.indexOf("function visibleNumberFragment(")),context);
  return {context,...vm.runInContext('({date:compactFinancialDate,text:compactFinancialDateText,caption:compactFinancialCaption,period:financialPeriodDisplay,company:companyFinancialPeriodDisplay,fullPeriod:actualPeriod,fullCompany:companyPeriodCaption,prepare:prepareDisplayTable})',context)};
}
const visible=html=>html.replaceAll('</span><span class="financial-date-line">',"\n").replace(/<[^>]*>/gu,"");

test("compact dates validate complete ISO dates without changing invalid values or fiscal labels",()=>{
  const h=harness();
  for(const [value,expected] of [["2024-09-29","24.09.29"],["2000-02-29","00.02.29"],["1999-12-31","99.12.31"],
    ["2025-02-29","2025-02-29"],["2024-13-01","2024-13-01"],["FY2025 Q4","FY2025 Q4"],[null,"—"],[undefined,"—"],["","—"]])assert.equal(h.date(value),expected);
  assert.equal(h.text("FY2025 Q4 · 2024-09-29 ~ 2025-09-27"),"FY2025 Q4 · 24.09.29–25.09.27");
  assert.equal(h.text("미준비"),"미준비");
});

test("duration, instant, missing and legacy context dates retain their original exact helper meaning",()=>{
  const h=harness();
  for(const [row,full,compact] of [
    [{period_start:"2024-09-29",period_end:"2025-09-28"},"2024-09-29 ~ 2025-09-27","24.09.29–25.09.27"],
    [{period_start:"2023-12-31",period_end:"2024-01-02"},"2023-12-31 ~ 2024-01-01","23.12.31–24.01.01"],
    [{period_start:"2024-02-28",period_end:"2024-03-01"},"2024-02-28 ~ 2024-02-29","24.02.28–24.02.29"],
    [{period_end:"2025-01-01"},"2024-12-31","24.12.31"],
    [{context_end_date:"2024-12-31"},"2024-12-31","24.12.31"],
    [{},"—","—"],
  ]){
    const before=JSON.stringify(row);assert.equal(h.fullPeriod(row),full);
    const markup=h.period(row);assert.equal(visible(markup),compact);
    assert(markup.includes(`title="${full}"`));assert(markup.includes(`aria-label="${full}"`));
    assert.equal(JSON.stringify(row),before);assert.equal(h.fullPeriod(row),full);
  }
});

test("company captions retain true fiscal year and every filed date with exact accessible provenance",()=>{
  const h=harness(),row={fiscal_year:2025,fiscal_quarter:"Q4",period_start:"2024-09-29",period_end:"2025-09-28",source_filed_dates:["2025-10-31","2025-11-01"]};
  const original=JSON.stringify(row),full=h.fullCompany(row),markup=h.company(row);
  assert.equal(visible(markup),"FY2025 Q4 · 24.09.29–25.09.27\n공시 25.10.31, 25.11.01");
  assert(markup.includes(`title="${full}"`));assert(markup.includes('class="financial-date-token">24.09.29</span>–<wbr>'));
  assert.equal(h.fullCompany(row),full);assert.equal(JSON.stringify(row),original);
  assert.equal(visible(h.company({bucket_status:"PERIOD_CONFLICT"})),"실제 기간 확인 필요");
  assert.equal(visible(h.company(null)),"준비된 기간 없음");
  const malicious=h.caption('source <img> "2024-09-29"');
  assert.doesNotMatch(malicious,/<img>/);assert.match(malicious,/&lt;img&gt; &quot;2024-09-29&quot;/);
  assert.match(visible(malicious),/24.09.29/);
});

function tableFixture(role){
  const changes=[];
  const classList={add(){},toggle(){}};
  const marker={title:"2024-09-29 ~ 2025-09-27"};
  function cell(marked=false){
    let text="2024-09-29 ~ 2025-09-27";
    return {hidden:false,colSpan:1,dataset:{},classList,
      get textContent(){return text},set textContent(value){if(marked)throw new Error("compact date markup destroyed");text=value;changes.push(value)},
      querySelector(selector){return marked&&selector==="[data-financial-date]"?marker:null},querySelectorAll(){return[]}};
  }
  const heading=Array.from({length:6},()=>cell()),body=Array.from({length:6},()=>cell());
  heading[3].dataset.displayRole="period";body[3]=cell(true);
  const small=cell(true);heading[1].querySelectorAll=()=>[small];
  const group={children:Array.from({length:6},()=>({style:{}}))};
  const style={setProperty(){}};
  const table={classList,style,tHead:{rows:[{cells:heading}]},rows:[{cells:heading,parentElement:{tagName:"THEAD"}},{cells:body,parentElement:{tagName:"TBODY"}}],
    closest(selector){return selector===(role==="results"?".workspace":"#comparison-result,#comparison-trend-values")||selector===".table-wrap,.display-table-scroll"?{}:null},
    querySelector(selector){return selector===":scope > colgroup"?group:null}};
  return{table,marker,body,small,changes};
}

test("repeated table preparation preserves compact caption DOM titles in period cells and comparison headings",()=>{
  const h=harness();h.context.getComputedStyle=()=>({getPropertyValue(){return"140"}});
  for(const role of ["results","comparison"]){
    const {table,marker,body,small}=tableFixture(role);
    h.prepare(table);h.prepare(table);
    assert.equal(body[3].querySelector("[data-financial-date]"),marker);
    assert.equal(marker.title,"2024-09-29 ~ 2025-09-27");
    assert.equal(small.querySelector("[data-financial-date]"),marker);
    if(role==="results")assert.equal(body[3].dataset.displayPeriod,"true");
  }
});


test("filing links retain their SEC locator and full ISO title while shortening only the visible filing date",()=>{
  const h=harness(),links=vm.runInContext("revenueSourceLinks",h.context);
  const accession="0000320193-25-000079",html=links([{accession,filed_date:"2025-10-31"}],"0000320193");
  assert.match(html,/000032019325000079\/0000320193-25-000079-index.html/);
  assert.match(html,/title="0000320193-25-000079 · 2025-10-31"/);
  assert.match(html,/aria-label="공시 2025-10-31 · 0000320193-25-000079"/);
  assert.match(html,/>공시 25.10.31<\/a>/);
  assert.match(links([{accession}],"0000320193"),/aria-label="공시 미확인/);
});
