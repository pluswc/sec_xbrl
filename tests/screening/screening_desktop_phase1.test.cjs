"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}}
function harness(respond=()=>({})){
  const nodes=new Map(),buttons=[],timers=new Map(),calls=[],focus=[];let sequence=0,choices=[],chips=[],companyChips=[];
  const make=(selector="")=>({value:"",hidden:false,disabled:false,options:[],dataset:{},scrollTop:0,scrollLeft:0,style:{setProperty(){}},classList:{add(){},remove(){},toggle(){}},
    setAttribute(){},replaceChildren(){this.innerHTML="";this.textContent=""},scrollIntoView(){},getBoundingClientRect(){return{top:300}},insertAdjacentHTML(){},
    closest(){return{classList:{toggle(){}}}},focus(options){focus.push({selector,options})},
    get innerHTML(){return this.html||""},set innerHTML(html){this.html=html;
      if(selector==="#comparison-metric-choices")choices=[...html.matchAll(/data-comparison-metric="([^"]+)"/g)].map(match=>({...make(),dataset:{comparisonMetric:match[1]}}));
      if(selector==="#comparison-company-chips")companyChips=[...html.matchAll(/data-comparison-remove-company="([^"]+)"/g)].map(match=>({...make(`company-chip:${match[1]}`),dataset:{comparisonRemoveCompany:match[1]}}));
      if(selector==="#comparison-metric-chips")chips=[...html.matchAll(/data-remove-comparison-metric="([^"]+)"/g)].map(match=>({...make(`chip:${match[1]}`),dataset:{removeComparisonMetric:match[1]}}));
    }});
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,make(selector));return nodes.get(selector)};
  const window={scrollY:80,addEventListener(){},scrollTo(value){this.scrollY=value.top}};
  const context=vm.createContext({URLSearchParams,location:{search:""},window,Node:{TEXT_NODE:3},document:{querySelector:get,querySelectorAll:selector=>selector==="[data-profile-cik]"?buttons:selector==="[data-comparison-metric]"?choices:selector==="[data-remove-comparison-metric]"?chips:selector==="[data-comparison-remove-company]"?companyChips:[]},
    setTimeout:fn=>{timers.set(++sequence,fn);return sequence},clearTimeout:id=>timers.delete(id),fetch:async url=>{calls.push(url);const value=await respond(url);return{ok:true,json:async()=>value}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const api=vm.runInContext('({S,desktop:desktopExplorer,picker:comparisonPicker,basis:explorerBasis,enter:enterExplorerAnalysis,back:backToExplorerList,close:closeProfile,closeComparison:closeExplorerComparison,companies:desktopExplorerCompanies,navigate:switchAnalysisCompany,options:comparisonMetricOptions,filter:filteredComparisonMetrics,renderPicker:renderComparisonMetricPicker,setMetric:setComparisonMetric,queue:queueComparisonRefresh,caption:financialMetricCaption,fiscal:profileFiscalPrefix})',context);
  const definitions=[{metric_id:"revenue",label:"매출",unit_kind:"MONEY",unit:"USD",definition_version:"v1",category:"GROWTH"},
    {metric_id:"standardized_fcf",label:"표준화 자유현금흐름",unit_kind:"MONEY",unit:"USD",definition_version:"v1",category:"CASH_FLOW"}];
  api.S.defaultDataset={dataset_id:"D"};api.S.explorerYear=2025;api.S.explorerCatalog={metrics:definitions};
  api.S.explorer={financial_as_of:"2026-10-25",rows:[{company:{cik:"A",ticker:"AAA",name:"Alpha"}},{company:{cik:"M",ticker:"MSFT",name:"Microsoft"}},{company:{cik:"Z",ticker:"ZZZ",name:"Zeta"}}]};
  api.S.profile={company:api.S.explorer.rows[1].company};api.S.explorerSelected.add("A");api.S.explorerSelected.add("M");
  api.basis.basis="ANNUAL";api.desktop.mounted=true;
  for(const company of api.S.explorer.rows.map(row=>row.company)){const button=make(company.cik);button.dataset.profileCik=company.cik;buttons.push(button)}
  const select=get("#comparison-metrics");select.options=definitions.map(definition=>({value:definition.metric_id,textContent:definition.label,selected:true}));
  Object.defineProperty(select,"selectedOptions",{get(){return this.options.filter(option=>option.selected)}});
  get("#comparison-panel").hidden=true;
  return {...api,get,window,buttons,calls,focus,context,timers,flush(){const first=timers.entries().next().value;if(!first)return Promise.resolve();timers.delete(first[0]);return first[1]()}};
}

test("analysis return restores the original list scroll and trigger after switching companies without editing query or selection",()=>{
  const h=harness(),matrix=h.get(".explorer-matrix");matrix.scrollTop=540;matrix.scrollLeft=126;
  h.get("#explorer-query").value="tech";h.get("#explorer-sort").value="revenue";h.get("#explorer-direction").value="desc";h.get("#explorer-preset").value="ALL";
  h.enter("PROFILE");assert.equal(h.desktop.saved.cik,"M");
  matrix.scrollTop=0;matrix.scrollLeft=0;h.window.scrollY=0;
  h.S.profile={company:h.S.explorer.rows[0].company};h.enter("PROFILE");h.back();
  assert.equal(h.desktop.mode,"LIST");assert.equal(matrix.scrollTop,540);assert.equal(matrix.scrollLeft,126);assert.equal(h.window.scrollY,80);
  assert.equal(h.focus.at(-1).selector,"M");assert.equal(h.focus.at(-1).options.preventScroll,true);
  assert.equal(h.get("#explorer-query").value,"tech");assert.equal(h.get("#explorer-sort").value,"revenue");assert.equal(h.get("#explorer-direction").value,"desc");
  assert.equal([...h.S.explorerSelected].join(),"A,M");assert.equal(h.get("#explorer-preset").value,"ALL");
  h.S.profile={company:h.S.explorer.rows[1].company};h.enter("PROFILE");h.buttons.splice(1,1);h.back();assert.equal(h.focus.at(-1).selector,"#explorer-query");
});

test("company navigation follows already filtered/sorted rows and ignores a late error after a later target or close",async()=>{
  const h=harness(),a=deferred(),b=deferred();
  assert.equal(h.companies().map(company=>company.cik).join(),"A,M,Z");
  h.basis.basis="QUARTERLY";h.basis.visibleRows=[h.S.explorer.rows[2],h.S.explorer.rows[0]];
  assert.equal(h.companies().map(company=>company.cik).join(),"Z,A");h.basis.basis="ANNUAL";
  h.context.openTarget=cik=>cik==="A"?a.promise:b.promise;vm.runInContext('openProfile=cik=>openTarget(cik)',h.context);
  h.enter("PROFILE");const first=h.navigate("A"),second=h.navigate("Z");
  b.resolve();await second;a.reject(new Error("old target"));await first;assert.equal(h.get("#analysis-status").hidden,true);
  const late=deferred();h.context.openTarget=()=>late.promise;const request=h.navigate("A");h.back();late.reject(new Error("closed target"));await request;
  assert.equal(h.desktop.mode,"LIST");assert.equal(h.get("#analysis-status").hidden,true);
});

test("comparison search/category filters never mutate the hidden adapter selection and closed-picker chip removal keeps visible focus",()=>{
  const h=harness();h.picker.mounted=true;h.get("#comparison-panel").hidden=false;
  const before=h.options().filter(option=>option.selected).map(option=>option.id).join();
  h.picker.query="no match";h.renderPicker();assert.match(h.get("#comparison-metric-choices").innerHTML,/선택한 지표는 유지/);
  assert.equal(h.options().filter(option=>option.selected).map(option=>option.id).join(),before);
  h.picker.query="";h.picker.category="CASH_FLOW";h.renderPicker();
  assert.match(h.get("#comparison-metric-choices").innerHTML,/standardized_fcf/);assert.doesNotMatch(h.get("#comparison-metric-choices").innerHTML,/data-comparison-metric="revenue"/);
  const picker=h.get("#comparison-metric-picker");picker.open=false;
  // Trigger the removable chips without opening their search disclosure.
  const chips=vm.runInContext('document.querySelectorAll("[data-remove-comparison-metric]")',h.context);chips[0].onclick();
  assert.equal(h.focus.at(-1).selector,"chip:standardized_fcf");
  const last=vm.runInContext('document.querySelectorAll("[data-remove-comparison-metric]")',h.context);last[0].onclick();
  assert.equal(h.focus.at(-1).selector,"#comparison-metric-picker summary");
  assert.equal(h.options().filter(option=>option.selected).length,0);assert.match(h.get("#comparison-result").textContent,/하나 이상/);
});

function comparisonPayload(){return{selected_fiscal_year:2025,date_limitation:"실제 기간 유지",companies:[{cik:"A",name:"Alpha"},{cik:"M",name:"Microsoft"}],actual_periods:{},rows:[]}}

test("pending comparison success and failure cannot replace a newer empty selection or closed view",async()=>{
  for(const fail of [false,true]){
    const pending=deferred(),h=harness(()=>pending.promise);h.picker.mounted=true;h.get("#comparison-panel").hidden=false;
    h.queue();const old=h.flush();await Promise.resolve();
    const before=h.basis.comparisonToken;h.setMetric("revenue",false);h.setMetric("standardized_fcf",false);
    assert(h.basis.comparisonToken>before);assert.match(h.get("#comparison-result").textContent,/하나 이상/);
    if(fail)pending.reject(new Error("old failure"));else pending.resolve(comparisonPayload());await old;
    assert.match(h.get("#comparison-result").textContent,/하나 이상/);assert.doesNotMatch(h.get("#comparison-result").innerHTML,/old failure|Alpha/);
    assert.equal(h.timers.size,0);
  }
  const pending=deferred(),h=harness(()=>pending.promise);h.picker.mounted=true;h.get("#comparison-panel").hidden=false;h.desktop.mode="COMPARE";
  h.queue();const old=h.flush();await Promise.resolve();h.closeComparison(false);pending.resolve(comparisonPayload());await old;
  assert.equal(h.get("#comparison-panel").hidden,true);assert.equal(h.get("#comparison-result").innerHTML,"");
});

test("new selections debounce one automatic request while invalid company counts remain explicit",async()=>{
  const h=harness(()=>comparisonPayload());h.picker.mounted=true;h.get("#comparison-panel").hidden=false;
  h.setMetric("revenue",false);h.setMetric("revenue",true);assert.equal(h.timers.size,1);await h.flush();assert.equal(h.calls.length,1);
  assert.match(h.calls[0],/metric_ids=revenue%2Cstandardized_fcf/);
  h.S.explorerSelected.add("Z");h.S.explorerSelected.add("4");h.S.explorerSelected.add("5");h.queue();assert.equal(h.timers.size,0);assert.match(h.get("#comparison-result").textContent,/2~4개/);
});

test("fiscal deduplication is scoped to one company's identical prepared year and short FCF remains a display alias",()=>{
  const h=harness();assert.equal(h.fiscal({selected_fiscal_year:2025,resolved_period:{fiscal_year:2025}}),"");
  assert.equal(h.fiscal({selected_fiscal_year:2024,resolved_period:{fiscal_year:2025}}),"FY2024 · ");
  assert.equal(h.fiscal({selected_fiscal_year:2025,resolved_period:{fiscal_year:2025,fiscal_quarter:"Q4"}}),"");
  const definition={metric_id:"ttm_standardized_fcf",label:"공표된 표준화 자유현금흐름"},before=JSON.stringify(definition);
  assert.equal(h.caption(definition),"표준화 FCF");assert.equal(JSON.stringify(definition),before);
  assert.equal(h.caption({metric_id:"net_income",label:"당기순이익"}),"당기순이익");
});


test("an active annual company failure is visible and restores the selector to the company whose data remains displayed",async()=>{
  const h=harness(()=>{throw new Error("current request failed")});h.enter("PROFILE");h.get("#analysis-company").value="A";
  await h.navigate("A");
  assert.equal(h.S.profile.company.cik,"M");assert.equal(h.get("#analysis-company").value,"M");
  assert.equal(h.get("#analysis-status").hidden,false);assert.match(h.get("#analysis-status").textContent,/현재 표시한 기업.*current request failed/);
  assert.equal(h.desktop.mode,"PROFILE");
  // Closing and successful new analysis must not inherit the previous target's error.
  h.back();assert.equal(h.get("#analysis-status").hidden,true);assert.equal(h.get("#analysis-status").textContent,"");
  h.S.profile={company:h.S.explorer.rows[0].company};h.enter("PROFILE");
  assert.equal(h.get("#analysis-status").hidden,true);
  h.get("#analysis-status").hidden=false;h.get("#analysis-status").textContent="old company failure";
  h.enter("COMPARE");assert.equal(h.get("#analysis-status").hidden,true);assert.equal(h.get("#analysis-status").textContent,"");
});


test("removing a comparison company restores adjacent live chip focus while two-to-one keeps the list fallback",()=>{
  const h=harness();h.picker.mounted=true;h.desktop.mode="COMPARE";h.get("#comparison-panel").hidden=false;
  h.S.explorerSelected.add("Z");h.S.explorerSelected.add("4");
  vm.runInContext("mountCompanyTrend=()=>{}",h.context);h.renderPicker();
  const chips=()=>vm.runInContext('document.querySelectorAll("[data-comparison-remove-company]")',h.context);
  chips()[1].onclick(); // 4→3, next company replaces the removed chip.
  assert.equal(h.S.explorerSelected.size,3);assert.equal(h.get("#comparison-panel").hidden,false);
  assert.equal(h.focus.at(-1).selector,"company-chip:Z");assert.equal(h.focus.at(-1).options.preventScroll,true);
  chips()[2].onclick(); // 3→2, last removal returns to the preceding chip.
  assert.equal(h.S.explorerSelected.size,2);assert.equal(h.focus.at(-1).selector,"company-chip:Z");
  chips()[1].onclick(); // 2→1 closes comparison; do not override its visible list fallback.
  assert.equal(h.S.explorerSelected.size,1);assert.equal(h.get("#comparison-panel").hidden,true);
  assert.equal(h.focus.at(-1).selector,"#explorer-query");
});
